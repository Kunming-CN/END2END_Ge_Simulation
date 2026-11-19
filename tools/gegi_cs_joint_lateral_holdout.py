"""Compare joint center and lateral fits on the independent Cs pixel captures."""

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
from time import perf_counter

import numpy as np

import gegi_dual_source as dual
import gegi_joint_two_site_study as joint
from gegi_event_store import encoded
from gegi_exposure_stream import ADCExposure, reconstruct_exposure
from gegi_imaging import cone


ROOT = joint.ROOT
BASE = ROOT / '.local/gegi-joint-two-site/cs-full-energy-lateral'
CAPTURE = BASE / 'results'
CAPTURE_SHA = 'c1c88572d7711f4c20a162125dcef3cdb9a2a62b4db3dbb10feab47f95ae957a'
VERIFY_SHA = '2b57504c24cad7e83b997918bd82f360fe600f753491d415d61f6f30f5793096'
TARGETS = ((13, 27), (14, 26))
ENERGIES_KEV = (193., 468.)
ADC_PHASE_NS = 0
NOISE_SEED = joint.cfd.BASE_NOISE_SEED + 400


def holdouts(inputs, field):
    seal = inputs.read(CAPTURE/'COMPLETE.json', CAPTURE_SHA)
    verification = inputs.read(CAPTURE/'verification.json', VERIFY_SHA)
    request = inputs.read(CAPTURE/'bound-request.json', seal['request_sha256'])
    if (verification['completion_sha256'] != CAPTURE_SHA or
            (request['model_sha256'], request['field_cache']['sha256'], request['field_precision_bits']) !=
            tuple(field[key] for key in ('model_sha256', 'field_cache_sha256', 'field_precision_bits'))
            or request['injection_energy_keV'] != joint.cfd.depth.ENERGY_KEV):
        raise ValueError('Held-out waveforms differ from the fixed same-field capture')
    by_cell = defaultdict(list)
    for row in seal['records']:
        if row['role'] != 'holdout':
            continue
        record = inputs.read(CAPTURE/row['record_ref'], row['record_sha256'])
        payload, _ = joint.cfd.scan.qualify(record, row, row, seal['request_sha256'], request['injection_energy_keV'])
        signals = {channel['contact_id']: channel for channel in payload['channel_signals']}
        waveform = joint.cfd.pulse.prepare_native(signals, request['channels'], terminal_complete=True)
        by_cell[tuple(row['contact_ids'])].append((row, waveform))
    xyz = {tuple(row['position_mm']) for rows in by_cell.values() for row, _ in rows}
    if set(by_cell) != set(TARGETS) or any(len(by_cell[cell]) != 8 for cell in TARGETS) or len(xyz) != 16:
        raise ValueError('Expected eight independently captured points in each of the two Cs pixels')
    cases = [sorted(by_cell[cell], key=lambda item: (*item[0]['offsets_pitch_fraction'], item[0]['position_mm'][2]))
             for cell in TARGETS]
    return request['channels'], xyz, list(zip(cases[0], cases[1][::-1], strict=True))


def acquire_case(index, inputs, channels, neighbors):
    references = []
    components = []
    for (record, pulse), energy in zip(inputs, ENERGIES_KEV, strict=True):
        components.append((pulse, joint.cfd.ONSET_NS, energy / joint.cfd.depth.ENERGY_KEV))
        references.append(dict(contact_ids=record['contact_ids'], xyz_mm=record['position_mm'],
                               input_energy_keV=energy, record_ref=record['record_ref'], record_sha256=record['record_sha256']))
    clock = ADCExposure(components, live_time_ns=joint.cfd.END_NS, phase_ns=ADC_PHASE_NS, noise_seed=NOISE_SEED+index)
    result = reconstruct_exposure(clock)
    events = result['events']
    trial = dict(index=index, neighborhood=joint.cfd.topology([row['contact_ids'] for row in references]),
                 truth_injections=references, noise_seed=NOISE_SEED+index, adc_sha256=result['adc_sha256'],
                 triggers=len(events), saturated_contact_ids=result['saturated_contact_ids'], fits=[], truth_comparison={})
    if len(events) != 1:
        return dict(trial, status='missing_or_multiple_triggers'), None, None
    trigger, = events
    card = dual._trigger_card(trigger, neighbors, geometry=channels)
    if card.get('two_strip_pairings') is None:
        return dict(trial, status='qualified_two_strip_pairing_unavailable'), None, None
    blocks = list(clock.blocks())
    origin = blocks[0][0]
    codes = np.concatenate([block for _, block in blocks], axis=1)
    sample_period = joint.cfd.pulse.D._DT
    indices = np.rint((trigger['trigger_time_ns'] + joint.SAMPLE_NS - ADC_PHASE_NS) / sample_period).astype(int) - origin
    if indices[0] < 0 or indices[-1] >= codes.shape[1]:
        raise ValueError('The nominal ADC did not retain its full measured local window')
    volts = codes[:, indices] * joint.cfd.pulse.D._LSB_V
    return dict(trial, status='pairings_measured', trigger_time_ns=trigger['trigger_time_ns']), card['two_strip_pairings'], volts


def fit_orders(pairing, result):
    output = []
    for order in pairing['compton_orders']:
        by_method = {}
        if order['kinematically_allowed'] and result['status'] == 'fitted':
            for mode, supports in result['fits'].items():
                for support, fit in supports.items():
                    sites = [dict(energy_keV=site['energy_keV'], position_mm=xyz)
                             for site, xyz in zip(pairing['sites'], fit['positions_mm'], strict=True)]
                    by_method[f'{mode}_{support}'] = cone(*(sites[i] for i in order['site_index_order']))
        output.append(dict(order, conditional_cones=by_method))
    return output


def run():
    start = perf_counter()
    scan = joint.cfd.scan
    paths = [ROOT/'tools'/name for name in (Path(__file__).name, 'gegi_joint_two_site_study.py', 'gegi_joint_two_site.py',
             'gegi_two_site_cfd_study.py', 'gegi_dual_source.py', 'gegi_pixel_cfd_depth_study.py',
             'gegi_pulse_stream.py', 'gegi_exposure_stream.py', 'gegi_digital_readout.py', 'gegi_imaging.py')]
    source_sha = {p.relative_to(ROOT).as_posix(): scan.digest(p) for p in paths}
    inputs = scan.Inputs()
    calibration = inputs.read(joint.cfd.CURVES, joint.cfd.CURVES_SHA)
    field = calibration['provenance']
    scale_report = inputs.read(joint.SCALES, joint.SCALES_SHA)
    if any(scale_report[key] != field[key] for key in ('digital_profile_sha256', 'digital_timing_sha256')):
        raise ValueError('The original fit scales and measured ADC use different electronics')
    scales = scale_report['controls']['group_rms_scales']
    channels, excluded_positions, cases = holdouts(inputs, field)
    neighbors = dual._strip_neighbors(channels)
    observed = [acquire_case(i, case, channels, neighbors) for i, case in enumerate(cases)]
    cells = {(site['x_contact_id'], site['y_contact_id']) for _, card, _ in observed if card
             for pairing in card['pairings'] if pairing['energy_compatible'] for site in pairing['sites']}
    templates = joint.load_templates(inputs, cells, field, channels, excluded_positions,
                                     lateral_captures=[(CAPTURE, CAPTURE_SHA)])
    rows = []
    for trial, card, volts in observed:
        if card is not None:
            for pairing in card['pairings']:
                result = joint.fit_pairing(pairing, card['collectors'], templates, scales, local_adc_volts=volts)
                pattern = [dict(contact_ids=[site['x_contact_id'],site['y_contact_id']]) for site in pairing['sites']]
                truth = joint.compare_fit(result, trial, {'sites': pattern})
                trial['fits'].append(dict(result, pairing_index=pairing['index'],
                                          contact_ids=[site['contact_ids'] for site in pattern],
                                          energy_compatible=pairing['energy_compatible'],
                                          measured_site_energies_keV=[site['energy_keV'] for site in pairing['sites']],
                                          order_hypotheses=fit_orders(pairing, result)))
                if truth is not None:
                    if trial['truth_comparison']:
                        raise ValueError('The held-out cells uniquely identify one measured pairing')
                    trial['truth_comparison'] = truth
        rows.append(trial)
    if any(scan.digest(ROOT/ref) != stamp for ref, stamp in source_sha.items()):
        raise ValueError('Readout or joint fit source changed during the closed evaluation')
    paired = {}
    for mode in ('features', 'waveform'):
        methods = [f'{mode}_center', f'{mode}_lateral']
        shared = [row for row in rows if all(key in row['truth_comparison'] for key in methods)]
        shared_metrics = joint.summary(shared)['near']['summary_by_method']
        paired[mode] = dict(trials=len(shared), metrics={key: shared_metrics[key] for key in methods if key in shared_metrics})
    return dict(
        kind='gegi_cs_joint_lateral_held_out_v1', status='completed',
        design=dict(energy_by_pixel_keV=[dict(contact_ids=cell, energy_keV=energy)
                    for cell, energy in zip(TARGETS, ENERGIES_KEV, strict=True)],
                    adc_phase_ns=ADC_PHASE_NS, nominal_noise_rms_V=joint.cfd.pulse.D._PROFILE['optional_noise_rms_V'],
                    pairing='Use each fixed off-center point once; pair the sorted first-pixel roster with the reversed second-pixel roster.',
                    scope='Simultaneous held-out point mixtures at two post-hoc selected Cs pixels. Apply both measured strip permutations '
                          'and every allowed energy order. Use positions only for scoring the known cell correspondence. '
                          'These simultaneous injections provide an axis reference and no photon chronology.',
                    new_field_solves=0, new_transport_calls=0, new_drift_calls=0),
        source_sha256=source_sha, input_sha256=inputs.hashes,
        counts=dict(trials=len(rows), independent_sites=len(excluded_positions),
                    adc_status=dict(Counter(row['status'] for row in rows)),
                    exact_truth_cell_fits=sum(bool(row['truth_comparison']) for row in rows),
                    center_templates=len(templates),
                    lateral_training_pixels=[cell for cell, template in templates.items()
                                             if template.lateral_correction_v_per_keV is not None]),
        identical_trial_support=paired, summary=joint.summary(rows), trials=rows,
        elapsed_s=perf_counter()-start,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(BASE) or output.exists():
        raise ValueError('Choose a new derivative path in the saved Cs lateral capture')
    report = run()
    with output.open('xb') as out:
        out.write(encoded(report)+b'\n')
    print(json.dumps({key: report[key] for key in ('counts', 'identical_trial_support', 'elapsed_s')}, indent=2))


if __name__ == '__main__':
    main()
