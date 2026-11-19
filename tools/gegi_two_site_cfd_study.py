"""Test conditional cone axes from two simultaneous saved GeGI point signals."""

import argparse
from collections import Counter
from itertools import product
import json
import math
from pathlib import Path
import time

import gegi_digital_pairs as pairs
import gegi_dual_source as dual
from gegi_event_store import encoded, sha
from gegi_exposure_stream import ADCExposure, reconstruct_exposure
from gegi_imaging import cone
import gegi_pixel_cfd_depth_study as depth
import gegi_pulse_scan as scan
import gegi_pulse_stream as pulse


LOCAL = scan.ROOT / '.local/gegi-two-site-cfd'
CURVES = scan.ROOT / '.local/gegi-pixel-cfd-depth/study.json'
CURVES_SHA = 'fbf5f9eb76bee6c82f256de3515c350df4c350539c8f5062a7fd0c965794a399'
# Fixed independent off-center receipts. Select their strip separation before replay.
CASES = (
    ('near', ((0, 'injections/point-025.json'), (0, 'injections/point-056.json'))),
    ('near', ((0, 'injections/point-138.json'), (0, 'injections/point-167.json'))),
    ('disjoint', ((0, 'injections/point-054.json'), (0, 'injections/point-140.json'))),
    ('disjoint', ((0, 'injections/point-137.json'), (1, 'injections/point-11.json'))),
)
ENERGIES = ((331., 331.), (132.4, 529.6), (529.6, 132.4))
PHASE_NS = (0, 10)
ONSET_NS = 1000
END_NS = ONSET_NS + scan.WINDOW_END_NS
BASE_NOISE_SEED = 20261123


def topology(cells):
    return 'disjoint' if all(abs(a-b) >= 3 for a, b in zip(*cells, strict=True)) else 'near'


def load_sources(inputs, calibration):
    capture_info = []
    for _, folder, digest in depth.CAPTURES:
        complete = inputs.read(folder/'COMPLETE.json', digest)
        request = inputs.read(folder/'bound-request.json', complete['request_sha256'])
        identity = calibration['provenance']
        if (request['model_sha256'] != identity['model_sha256']
                or request['field_cache']['sha256'] != identity['field_cache_sha256']
                or request['field_precision_bits'] != identity['field_precision_bits']
                or request['injection_energy_keV'] != depth.ENERGY_KEV):
            raise ValueError('Saved injections and depth curves use different fields or energy references')
        capture_info.append((folder, complete, request['channels']))
    channels = capture_info[0][2]
    if any(chcs != channels for _, _, chcs in capture_info):
        raise ValueError('Saved injections use different channel geometry')
    training_positions = {tuple(row['injected_xyz_mm']) for item in calibration['pixels'] for row in item['center_measurements']}
    sources = {}
    for _, refs in CASES:
        for capture, ref in refs:
            folder, complete, _ = capture_info[capture]
            receipt, = [row for row in complete['records'] if row['record_ref'] == ref and row['role'] == 'holdout']
            raw = inputs.read(folder/ref, receipt['record_sha256'])
            payload, _ = scan.qualify(raw, receipt, receipt, complete['request_sha256'], depth.ENERGY_KEV)
            position = payload['position_mm']
            if tuple(position) in training_positions:
                raise ValueError('A scored injection was included in the center-depth fit')
            waveforms = {row['contact_id']: row for row in payload['channel_signals']}
            sources[capture, ref] = {'contact_ids': payload['contact_ids'], 'xyz_mm': position,
                                     'record_sha256': receipt['record_sha256'], 'record': (folder/ref).relative_to(scan.ROOT).as_posix(),
                                     'waveform': pulse.prepare_native(waveforms, channels, terminal_complete=True)}
    if len(sources) != 8 or len({tuple(row['xyz_mm']) for row in sources.values()}) != 8:
        raise ValueError('Expected eight independent saved holdout coordinates')
    return channels, sources


def measure_depth(cell, collectors, curves):
    times = [collectors.get(cid, {}).get('preamp_cfd50_ns') for cid in cell]
    delta = times[0] - times[1] if all(isinstance(t, (int, float)) and math.isfinite(t) for t in times) else None
    measurement = {'measurement_status': 'measured' if delta is not None else 'collector_cfd_unavailable',
                   'cfd_x_minus_y_ns': delta}
    curve = curves.get(tuple(cell), {'status': 'pixel_curve_unavailable'})
    status, z = depth.estimate_depth(curve, measurement)
    return {'contact_ids': list(cell), 'collector_cfd50_ns': times, 'cfd_x_minus_y_ns': delta,
            'depth_status': status, 'estimated_z_mm': z}


def conditional_estimates(card, curves, geometry):
    """Only measured energies and collector times enter the candidates."""
    collectors = {row['contact_id']: row for row in card['collectors']}
    result = []
    for pairing in card['pairings']:
        sites = []
        for measured in pairing['sites']:
            cell = [measured['x_contact_id'], measured['y_contact_id']]
            position = measure_depth(cell, collectors, curves) if pairing['energy_compatible'] else (
                {'contact_ids': cell, 'depth_status': 'incompatible_energies', 'estimated_z_mm': None})
            z = position['estimated_z_mm']
            sites.append(dict(position, energy_keV=measured['energy_keV'],
                              position_mm=[geometry[cid]['strip_center_mm'] for cid in cell] + [z] if z is not None else None))
        orders = []
        for order in pairing['compton_orders']:
            a, b = (sites[i] for i in order['site_index_order'])
            proposed = cone(a,b) if order['kinematically_allowed'] and a['position_mm'] is not None and b['position_mm'] is not None else None
            orders.append(dict(order, conditional_cone=proposed))
        result.append({'index': pairing['index'], 'energy_compatible': pairing['energy_compatible'], 'sites': sites, 'orders': orders})
    return result


def observe(components, phase, seed, neighbors, channels):
    adc = ADCExposure(components, live_time_ns=END_NS, phase_ns=phase, noise_seed=seed)
    result = reconstruct_exposure(adc)
    events = result['events']
    return (dual._trigger_card(events[0], neighbors, geometry=channels) if len(events) == 1 else None), result['adc_sha256'], len(events)


def isolated_control(card, curves):
    if not card or card['single_pixel_features'] is None:
        return None
    features = list(card['single_pixel_features'].values())
    ids = [row['contact_id'] for row in features]
    return measure_depth(ids, {row['contact_id']: row for row in features}, curves)


def angle_error(a, b):
    dot = math.fsum(x*y for x, y in zip(a, b, strict=True))
    cosine = dot / (math.hypot(*a)*math.hypot(*b))
    return math.degrees(math.acos(max(-1., min(1., cosine))))


def axis_between(first, second):
    return [a-b for a,b in zip(first, second, strict=True)]


def score(estimates, truth, isolated, energies, geometry):
    """Identify the held-out (known cell) hypothesis after freezing all measurement outputs."""
    expected = [item['contact_ids'] for item in truth]
    matching = [row for row in estimates if sorted(site['contact_ids'] for site in row['sites']) == sorted(expected)]
    if not matching or not matching[0]['energy_compatible']:
        return {'status': 'truth_cells_absent_or_energy_incompatible'}
    selected, = matching
    order = [next(i for i, s in enumerate(selected['sites']) if s['contact_ids'] == pair) for pair in expected]
    sites = [selected['sites'][i] for i in order]
    truth_xyz = [v['xyz_mm'] for v in truth]
    sites_scored = []
    for observed, control, actual in zip(sites, isolated, truth, strict=True):
        reference = control if control and control['contact_ids'] == actual['contact_ids'] else {}
        delta, z = observed['cfd_x_minus_y_ns'], observed['estimated_z_mm']
        single_delta, single_z = reference.get('cfd_x_minus_y_ns'), reference.get('estimated_z_mm')
        true_z = actual['xyz_mm'][2]
        sites_scored.append({'depth_status': observed['depth_status'],
                            'cfd_delta_vs_isolated_ns': delta - single_delta if delta is not None and single_delta is not None else None,
                            'depth_error_mm': z - true_z if z is not None else None,
                            'isolated_depth_error_mm': single_z - true_z if single_z is not None else None})
    centers = [[geometry[cid]['strip_center_mm'] for cid in site['contact_ids']] for site in sites]
    estimate_xyz = [site['position_mm'] for site in sites]
    truth_axis = axis_between(*truth_xyz)
    axes = None
    if all(value is not None for value in estimate_xyz):
        axes = {'candidate_depth_deg': angle_error(truth_axis, axis_between(*estimate_xyz)),
                'strip_center_midplane_deg': angle_error(truth_axis, axis_between(*[xy+[0.] for xy in centers])),
                'strip_center_true_depth_deg': angle_error(truth_axis, axis_between(*[xy+[xyz[2]] for xy,xyz in zip(centers, truth_xyz, strict=True)]))}
    orders = []
    true_angle = {tuple(order[row] for row in item['site_index_order']): item for item in
                  pairs.compton_orders([{'energy_keV': energy} for energy in energies])}
    for hypothesis in selected['orders']:
        expected_order = true_angle[tuple(hypothesis['site_index_order'])]
        angle_ok = hypothesis['kinematically_allowed'] and expected_order['kinematically_allowed']
        orders.append({'site_index_order': hypothesis['site_index_order'],
                       'matches_injected_kinematic_allowance': hypothesis['kinematically_allowed'] == expected_order['kinematically_allowed'],
                       'half_angle_error_deg': hypothesis['half_angle_deg'] - expected_order['half_angle_deg'] if angle_ok else None})
    return {'status': 'compared', 'truth_pair_index': selected['index'], 'sites': sites_scored,
            'axis_error_deg': axes, 'half_angle_errors': orders}


def metrics(values):
    values = [v for v in values if v is not None]
    return {'n': len(values), 'rms': math.sqrt(math.fsum(v*v for v in values)/len(values)) if values else None,
            'max_abs': max(map(abs, values), default=None)}


def summarize(rows):
    scored = [row['evaluation'] for row in rows if row['evaluation']['status'] == 'compared']
    sites = [site for row in scored for site in row['sites']]
    axes = [row['axis_error_deg'] for row in scored if row['axis_error_deg'] is not None]
    paired_sites = [row for row in sites if row['depth_error_mm'] is not None and row['isolated_depth_error_mm'] is not None]
    return {'trials': len(rows), 'status': dict(Counter(row['evaluation']['status'] for row in rows)),
            'truth_pair_scored': len(scored), 'truth_sites_estimated': sum(row['depth_error_mm'] is not None for row in sites),
            'both_depths_available': len(axes),
            'axis_errors_deg': {name: metrics(row[name] for row in axes)
                                for name in ('candidate_depth_deg', 'strip_center_midplane_deg', 'strip_center_true_depth_deg')},
            'site_cfd_delta_vs_isolated_ns': metrics(row['cfd_delta_vs_isolated_ns'] for row in sites),
            'site_depth_errors_paired_mm': {name: metrics(row[name] for row in paired_sites)
                                           for name in ('depth_error_mm', 'isolated_depth_error_mm')},
            'half_angle_errors_deg': metrics(order['half_angle_error_deg'] for row in scored for order in row['half_angle_errors']),
            'kinematic_allowance_flips': sum(not order['matches_injected_kinematic_allowance'] for row in scored for order in row['half_angle_errors'])}


def saved_candidate_support(acquisition, calibration, curves):
    counts = Counter()
    holdouts = {tuple(row['injected_contact_ids']) for row in calibration['validation'] if row['measurement_status'] == 'measured'}
    ratio_values = []
    for event in acquisition['triggers']:
        card = event.get('two_strip_pairings')
        if card is None:
            continue
        collectors = {row['contact_id']: row for row in card['collectors']}
        for pairing in card['pairings']:
            if not pairing['energy_compatible']:
                continue
            cells = [(s['x_contact_id'], s['y_contact_id']) for s in pairing['sites']]
            energies = [s['energy_keV'] for s in pairing['sites']]
            ratio_values.append(max(energies)/min(energies))
            key = topology(cells)
            counts[key, 'candidate_pairings'] += 1
            measured = [measure_depth(c, collectors, curves) for c in cells]
            counts[key, 'four_measured_cfds'] += all(row['cfd_x_minus_y_ns'] is not None for row in measured)
            counts[key, 'both_in_calibration_range'] += all(row['estimated_z_mm'] is not None for row in measured)
            counts[key, 'off_center_both_sites'] += all(c in holdouts for c in cells)
    return {'counts_by_neighborhood': {key: {name: v for (group,name),v in counts.items() if group == key}
                                        for key in ('near', 'disjoint')},
            'measured_site_energy_ratio_max_to_min': [min(ratio_values), max(ratio_values)]}


def run(*, pilot=False):
    start = time.perf_counter()
    paths = (Path(__file__), *(scan.ROOT/'tools'/name for name in ('gegi_pixel_cfd_depth_study.py', 'gegi_pulse_stream.py',
             'gegi_pulse_scan.py', 'gegi_dual_source.py', 'gegi_imaging.py', 'gegi_exposure_stream.py', 'gegi_digital_pairs.py')))
    sources_hash = {path.relative_to(scan.ROOT).as_posix(): scan.digest(path) for path in paths}
    inputs = scan.Inputs()
    calibration = inputs.read(CURVES, CURVES_SHA)
    acquisition = inputs.read(depth.ACQUISITION, depth.ACQUISITION_SHA)
    if (calibration['provenance']['digital_profile_sha256'] != pulse.D.PROFILE_SHA256 or
            calibration['provenance']['digital_timing_sha256'] != pulse.D.TIMING_SHA256):
        raise ValueError('Timing calibration and replay use different digital settings')
    curves = {tuple(row['contact_ids']): row['curve'] for row in calibration['pixels']}
    channels, sources = load_sources(inputs, calibration)
    geometry = {row['id']: row for row in channels}
    neighbors = dual._strip_neighbors(channels)
    rows = []
    design = product(enumerate(CASES), ENERGIES, PHASE_NS, ('none', 'nominal'))
    for (index, (group, refs)), energies, phase, noise in design:
        if pilot and (index not in (0, 2) or energies != ENERGIES[1] or phase != 0 or noise != 'none'):
            continue
        truth = [sources[ref] for ref in refs]
        if topology([site['contact_ids'] for site in truth]) != group:
            raise ValueError('Fixed case topology changed')
        seed = int(sha(encoded((BASE_NOISE_SEED, index, energies, phase)))[:16], 16) if noise == 'nominal' else None
        components = [(site['waveform'], ONSET_NS, energy/depth.ENERGY_KEV) for site, energy in zip(truth, energies, strict=True)]
        card, adc, n = observe(components, phase, seed, neighbors, channels)
        visible = card.get('two_strip_pairings') if card else None
        estimates = conditional_estimates(visible, curves, geometry) if visible else []
        single = [observe([component], phase, seed, neighbors, channels) for component in components]
        isolated = [isolated_control(card, curves) for card, _, _ in single]
        evaluation = score(estimates, truth, isolated, energies, geometry) if visible else {'status': 'two_by_two_measurement_unavailable'}
        rows.append({'case_index': index, 'neighborhood': group, 'energies_keV': energies, 'adc_phase_ns': phase,
                     'noise': noise, 'noise_seed': seed, 'adc_sha256': adc, 'triggers': n,
                     'paired_collectors': visible['collectors'] if visible else None, 'paired_flags': card['flags'] if card else None,
                     'energy_compatible_pairings': visible['compatible_pairing_count'] if visible else 0,
                     'measured_pairings': estimates, 'isolated': isolated, 'isolated_adc_sha256': [s[1] for s in single],
                     'truth_injections': [{k:v for k,v in value.items() if k != 'waveform'} for value in truth], 'evaluation': evaluation})
    if sources_hash != {path.relative_to(scan.ROOT).as_posix(): scan.digest(path) for path in paths}:
        raise ValueError('Readout source changed during the study')
    return {'kind': 'gegi_saved_two_site_cfd_cone_study_v1', 'status': 'completed',
            'design': {'sites': 'Eight sealed off-center points excluded from center-curve calibration. Pick fixed nearby and disjoint strip neighborhoods.',
                       'measurement': 'Add the two scaled signed native responses before one ADC at the same onset. Estimate depths independently from measured per-site X minus Y CFD50 using the saved center curves.',
                       'axis': 'Use measured contact strip centers for XY and CFD estimates for Z. Compare the absorber-to-scatter axis against the exact injection sites, and against strip-center axes using Z=0 and the injected Z.',
                       'order_scope': 'Both pair permutations and all permitted orders remain visible. Compare half angles for the exact injection cells and the same conditional order. Simultaneous injected pulses carry no physical photon trajectory or order.',
                       'physical_scope': 'No measured detector validation, waveform fit, diffusion correction or new field/transport/drift.',
                       'conditions_are_reused_waveforms': True, 'new_field_solves': 0, 'new_transport_calls': 0, 'new_drift_calls': 0},
            'candidate_support_in_saved_acquisition': saved_candidate_support(acquisition, calibration, curves),
            'summary': {kind: summarize([row for row in rows if row['neighborhood'] == kind]) for kind in ('near', 'disjoint')},
            'input_sha256': inputs.hashes, 'source_sha256': sources_hash, 'trials': rows, 'wall_s': time.perf_counter()-start}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--pilot', action='store_true', help='Compare one nearby and one disjoint case without saving a report')
    args = parser.parse_args()
    if not args.pilot and (args.output is None or not args.output.resolve().is_relative_to(LOCAL) or args.output.exists()):
        parser.error('Choose a new report path under .local/gegi-two-site-cfd')
    report = run(pilot=args.pilot)
    if not args.pilot:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('xb') as target:
            target.write(encoded(report) + b'\n')
    print(json.dumps({'summary': report['summary'], 'candidate_support': report['candidate_support_in_saved_acquisition'],
                      'wall_s': report['wall_s']}, indent=2))


if __name__ == '__main__':
    main()
