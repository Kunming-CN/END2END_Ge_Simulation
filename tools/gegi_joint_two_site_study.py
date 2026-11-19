"""Compare joint GeGI two-site fits on the 48 sealed controlled ADC mixtures."""

import argparse
from collections import Counter
from itertools import product
import json
import math
from pathlib import Path
import time

import numpy as np

import gegi_dual_source as dual
from gegi_event_store import encoded
from gegi_exposure_stream import ADCExposure, reconstruct_exposure
from gegi_joint_two_site import (DEPTH_MM, LATERAL_DEPTH_MM, LATERAL_FRACTION, SAMPLE_NS,
                                  Template, analog_template, fit_pairing)
import gegi_two_site_cfd_study as cfd


ROOT = cfd.scan.ROOT
LOCAL = ROOT / '.local/gegi-joint-two-site'
STUDY = cfd.LOCAL/'study.json'
STUDY_SHA = '308a0f5ec78757cc929d26b2d3280d78c685b91b38ee88837b157178cb85e2d7'
SCALES = ROOT/'.local/gegi-digital-v1/two-site-pairing-study.json'
SCALES_SHA = '61a09e18a72a33fdda849b208e6bc3e5587d3c8a5f0f789082dba60469e66ad5'


def load_templates(inputs, cells, calibration, channels, excluded_positions, *, lateral_captures=()):
    bank = cfd.scan.FULL
    complete = inputs.read(bank/'COMPLETE.json',cfd.scan.FULL_COMPLETE_SHA)
    request = inputs.read(bank/'bound-request.json',complete['request_sha256'])
    bundle = inputs.read(bank/'identity.json',complete['bundle_identity_sha256'])
    identity = bundle['calibration_identity_sha256']
    _, default_dir, default_digest = cfd.depth.CAPTURES[0]
    captures = [(folder, inputs.read(folder/'COMPLETE.json', digest))
                for folder, digest in [(default_dir, default_digest), *lateral_captures]]
    specifications = [inputs.read(folder/'bound-request.json', seal['request_sha256']) for folder, seal in captures]
    for specification in [request, *specifications]:
        if (specification['channels'] != channels or specification['model_sha256'] != calibration['model_sha256']
                or specification['field_cache']['sha256'] != calibration['field_cache_sha256']
                or specification['field_precision_bits'] != calibration['field_precision_bits']
                or specification['injection_energy_keV'] != cfd.depth.ENERGY_KEV):
            raise ValueError('Training matches neither the frozen field nor the independent point captures')
    selected = {point['target_ref']:point for point in request['grid']
                if point['target_ref'].startswith('injections/') and tuple(point['contact_ids']) in cells}
    entries = cfd.depth.bank_manifest(inputs, complete, set(selected))
    center, correction = {}, {}

    def extract(folder, point, entry, digest):
        raw = inputs.read(folder/entry['record_ref'], entry['record_sha256'])
        payload, _ = cfd.scan.qualify(raw, point, entry, digest, cfd.depth.ENERGY_KEV)
        if tuple(payload['position_mm']) in excluded_positions:
            raise ValueError('A holdout coordinate overlaps a training template')
        return analog_template(payload, channels)

    for ref, point in selected.items():
        if entries[ref]['status'] != 'completed' or not entries[ref]['valid']:
            continue
        cell = tuple(point['contact_ids'])
        z = point['position_mm'][2]
        center.setdefault(cell,{})[z] = extract(bank/'bank',point,entries[ref],identity)
    for fit_dir, capture in captures:
        for item in capture['records']:
            cell = tuple(item['contact_ids'])
            if item['role'] != 'fit' or cell not in cells or not item['valid'] or item['status'] != 'completed':
                continue
            coord = (*item['offsets_pitch_fraction'], item['position_mm'][2])
            if coord[2] in center.get(cell, {}):
                spectra = extract(fit_dir,item,item,capture['request_sha256'])
                correction.setdefault(cell,{})[coord] = spectra-center[cell][coord[2]]
    templates = {}
    pitch = channels[1]['strip_center_mm']-channels[0]['strip_center_mm']
    for cell in sorted(cells):
        z_map = center.get(cell,{})
        if sorted(z_map) != list(DEPTH_MM):
            continue
        grid = None
        required = {(x,y,z) for x,y,z in product(LATERAL_FRACTION,LATERAL_FRACTION,LATERAL_DEPTH_MM) if x or y}
        if required <= correction.get(cell,{}).keys():
            grid = np.array([np.zeros_like(z_map[z]) if x == y == 0 else correction[cell][x,y,z]
                             for x,y,z in product(LATERAL_FRACTION,LATERAL_FRACTION,LATERAL_DEPTH_MM)])
            grid = grid.reshape(3,3,3,*grid.shape[1:])
        templates[cell] = Template(cell, tuple(channels[cid-1]['strip_center_mm'] for cid in cell),
                                   pitch, np.array([z_map[z] for z in DEPTH_MM]), grid)
    return templates


def adc_window(trial, sources, channels):
    refs = cfd.CASES[trial['case_index']][1]
    components = [(sources[ref]['waveform'], cfd.ONSET_NS, energy/cfd.depth.ENERGY_KEV)
                  for ref, energy in zip(refs, trial['energies_keV'], strict=True)]
    clock = ADCExposure(components, live_time_ns=cfd.END_NS, phase_ns=trial['adc_phase_ns'], noise_seed=trial['noise_seed'])
    reconstructed = reconstruct_exposure(clock)
    if reconstructed['adc_sha256'] != trial['adc_sha256'] or len(reconstructed['events']) != 1:
        raise ValueError('Matched held-out ADC samples changed')
    event, = reconstructed['events']
    checked = dual._trigger_card(event, dual._strip_neighbors(channels), geometry=channels)['two_strip_pairings']
    if checked['collectors'] != trial['paired_collectors']:
        raise ValueError('Saved measured collector outputs changed')
    blocks = list(clock.blocks())
    origin = blocks[0][0]
    codes = np.concatenate([block for _,block in blocks],axis=1)
    trigger_ns = event['trigger_time_ns']
    times = trigger_ns+SAMPLE_NS
    indices = np.rint((times-clock.phase_ns)/cfd.pulse.D._DT).astype(int)-origin
    return codes[:,indices]*cfd.pulse.D._LSB_V


def compare_fit(result, trial, pairing):
    if result['status'] != 'fitted':
        return None
    expected = [row['contact_ids'] for row in trial['truth_injections']]
    pattern = [row['contact_ids'] for row in pairing['sites']]
    if sorted(expected) != sorted(pattern):
        return None
    truth = [trial['truth_injections'][expected.index(cell)]['xyz_mm'] for cell in pattern]
    output = {}
    for mode, fits in result['fits'].items():
        for support, fit in fits.items():
            xyz = fit['positions_mm']
            output[f'{mode}_{support}'] = {
                'axis_error_deg': cfd.angle_error(cfd.axis_between(*xyz),cfd.axis_between(*truth)),
                'site_depth_error_mm': [a[2]-b[2] for a,b in zip(xyz,truth,strict=True)],
                'site_xy_error_mm': [math.dist(a[:2],b[:2]) for a,b in zip(xyz,truth,strict=True)],
                'weighted_residual_rms': fit['weighted_residual_rms'],
                'minimum_scaled_jacobian_singular_value': min(fit['scaled_jacobian_singular_values']),
                'largest_near_tie_depth_spread_mm': max(fit['sampled_near_tie_spread'][i] for i in ((2,5) if support == 'lateral' else (0,1))),
                'model_crossings_available': fit['modeled_cfd_available'], 'optimizer_success': fit['optimizer_success'],
            }
    return output


def summary(rows):
    result = {}
    for group in ('near','disjoint'):
        subset = [row for row in rows if row['neighborhood'] == group]
        methods = {}
        for key in sorted({k for r in subset for k in r['truth_comparison']}):
            matched = [row['truth_comparison'][key] for row in subset if key in row['truth_comparison']]
            methods[key] = {
                'trials': len(matched), 'depth_error_mm': cfd.metrics(v for row in matched for v in row['site_depth_error_mm']),
                'xy_error_mm': cfd.metrics(v for row in matched for v in row['site_xy_error_mm']),
                'axis_error_deg': cfd.metrics(row['axis_error_deg'] for row in matched),
                'weighted_residual_rms_median': float(np.median([row['weighted_residual_rms'] for row in matched])),
                'largest_near_tie_depth_spread_mm': max(row['largest_near_tie_depth_spread_mm'] for row in matched),
                'smallest_scaled_jacobian_singular_value': min(row['minimum_scaled_jacobian_singular_value'] for row in matched),
                'available_modeled_crossings': sum(row['model_crossings_available'] for row in matched),
                'best_fit_converged': sum(row['optimizer_success'] for row in matched),
            }
        result[group] = {'trials': len(subset), 'summary_by_method': methods,
                         'measurement_only_pairing_fit_statuses': dict(Counter(p['status'] for row in subset for p in row['fits']))}
    return result


def run(*, pilot=False):
    start = time.perf_counter()
    sources = ('gegi_joint_two_site_study.py','gegi_joint_two_site.py','gegi_two_site_cfd_study.py',
               'gegi_pixel_cfd_depth_study.py','gegi_pulse_scan.py','gegi_dual_source.py','gegi_pulse_stream.py',
               'gegi_exposure_stream.py','gegi_digital_readout.py')
    def source_hashes():
        return {f'tools/{name}':cfd.scan.digest(ROOT/'tools'/name) for name in sources}
    implementation = source_hashes()
    inputs = cfd.scan.Inputs()
    saved = inputs.read(STUDY,STUDY_SHA)
    calibration = inputs.read(cfd.CURVES,cfd.CURVES_SHA)
    scale_report = inputs.read(SCALES,SCALES_SHA)
    for key in ('digital_profile_sha256','digital_timing_sha256'):
        if scale_report[key] != calibration['provenance'][key]:
            raise ValueError('Archived scales describe a different digital profile')
    scales = scale_report['controls']['group_rms_scales']
    channels, injection = cfd.load_sources(inputs,calibration)
    cells = {tuple(site['contact_ids']) for trial in saved['trials'] for pairing in trial['measured_pairings']
             if pairing['energy_compatible'] for site in pairing['sites']}
    templates = load_templates(inputs,cells,calibration['provenance'],channels,{tuple(v['xyz_mm']) for v in injection.values()})
    results = []
    for index,trial in enumerate(saved['trials']):
        if pilot and not (trial['case_index'] in (0,2) and trial['energies_keV'] == [132.4,529.6]
                          and trial['adc_phase_ns'] == 0 and trial['noise'] == 'none'):
            continue
        volts = adc_window(trial,injection,channels)
        fits, truth = [], {}
        for pairing in trial['measured_pairings']:
            measured = {'energy_compatible': pairing['energy_compatible'],
                        'sites': [dict(x_contact_id=site['contact_ids'][0],y_contact_id=site['contact_ids'][1],
                                       energy_keV=site['energy_keV']) for site in pairing['sites']]}
            result = fit_pairing(measured,trial['paired_collectors'],templates,scales,local_adc_volts=volts)
            fits.append(dict(result,pairing_index=pairing['index'],contact_ids=[site['contact_ids'] for site in pairing['sites']],
                             order_hypotheses=[{k:v for k,v in order.items() if k != 'conditional_cone'} for order in pairing['orders']]))
        for fit,pairing in zip(fits,trial['measured_pairings'],strict=True):
            comparison = compare_fit(fit,trial,pairing)
            if comparison is not None:
                truth = comparison
        results.append({'trial_index':index,'neighborhood':trial['neighborhood'],'case_index':trial['case_index'],
                        'adc_sha256':trial['adc_sha256'],'energies_keV':trial['energies_keV'],'fits':fits,'truth_comparison':truth})
    if implementation != source_hashes():
        raise ValueError('Fit or readout code changed during replay')
    return {'kind':'gegi_saved_joint_two_site_study_v1','status':'completed','design':{
        'fit':'Sum local nominal analog templates at measured face-average site energies, with one common onset offset. Center-only fits vary two depths. Lateral fits add bounded offsets using independent archived corrections.',
        'comparison':'Use matched saved ADC codes to compare retained fast/CFD features with all available local preamp samples. Subtract a per-contact exponential tail using the first three quiet samples. No ADC rounding or noise is added to the forward model.',
        'residual_scales':scales,'waveform_noise_scale_V':cfd.pulse.D._PROFILE['optional_noise_rms_V'],
        'sampled_near_tie':'Runs started from distinct deterministic seeds with weighted RMS within 0.25 of the best sampled optimum. The spread and scaled Jacobian diagnostics are local or sampled, without coverage interpretation.',
        'scope':'48 repeated conditions from eight coordinate-distinct held-out injections. Truth is applied after fitting both energy hypotheses.',
        'new_transport_calls':0,'new_field_solves':0,'new_drift_calls':0},
        'samples_ns_relative_to_trigger':SAMPLE_NS.tolist(),
        'training':{'center_pixels':len(templates),'center_templates':len(templates)*len(DEPTH_MM),
                    'center_unavailable_pixels':[list(cell) for cell in sorted(cells-templates.keys())],
                    'lateral_pixels':[list(cell) for cell,model in templates.items() if model.lateral_correction_v_per_keV is not None]},
        'summary':summary(results),'trials':results,'source_sha256':implementation,'input_sha256':inputs.hashes,'wall_s':time.perf_counter()-start}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--pilot',action='store_true',help='Fit two fixed trials and print the result without writing a receipt')
    args = parser.parse_args()
    if not args.pilot and (args.output is None or args.output.exists() or not args.output.resolve().is_relative_to(LOCAL)):
        parser.error('Choose a fresh output path under .local/gegi-joint-two-site')
    report = run(pilot=args.pilot)
    if not args.pilot:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        with args.output.open('xb') as target:
            target.write(encoded(report)+b'\n')
    print(json.dumps({k:report[k] for k in ('training','summary','wall_s')},indent=2))


if __name__ == '__main__':
    main()
