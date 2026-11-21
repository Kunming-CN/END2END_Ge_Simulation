"""Compare joint cone stability on the saved GeGI wrong-topology controls."""

import argparse
from collections import Counter
import json
from pathlib import Path
from statistics import median

import numpy as np

from gegi_event_store import encoded, sha
import gegi_position_cone_spread as spread
import gegi_position_uncertainty_study as uncertainty


POSITIVE_SHA = 'eca34f3061c45cacc74dfd852e44634a2042a04daf1a6697ac10b72a929360c1'


def fit_inputs(saved):
    """Recover the original ADC from archived inputs, never transport or drift."""
    study = uncertainty.study
    inputs = study.cfd.scan.Inputs()
    field = inputs.read(study.cfd.CURVES, study.cfd.CURVES_SHA)['provenance']
    scales = inputs.read(study.SCALES, study.SCALES_SHA)
    if any(scales[k] != field[k] for k in ('digital_profile_sha256', 'digital_timing_sha256')):
        raise ValueError('Negative controls and fit scales must share the saved electronics configuration')
    positive_positions = {tuple(s['xyz_mm']) for t in saved['trials'] if t['cohort'] != 'negative_mixture'
                          for s in t['reference_sites']}
    layouts = {name: refs for name, refs, _ in uncertainty.NEGATIVE_GEOMETRIES}
    refs = {ref for layout in layouts.values() for ref in layout}
    channels, traces, positions = uncertainty.load_archived_traces(inputs, field, refs, positive_positions)
    cases = []
    for prior in saved['trials']:
        if prior['cohort'] != 'negative_mixture':
            continue
        components = []
        for ref, site in zip(layouts[prior['geometry']], prior['reference_sites'], strict=True):
            trace = traces[ref]
            if trace['source_sha256'] != site['native_record_sha256']:
                raise ValueError('A retained negative-control native trace changed')
            components.append((trace['native'], study.cfd.ONSET_NS, site['energy_keV']/study.cfd.depth.ENERGY_KEV))
        adc, count, status, card, volts = uncertainty.measure_adc(
            components, channels, prior['adc_phase_ns'], prior['noise_seed'])
        if (adc, count, status) != (prior['adc_sha256'], prior['triggers'], prior['trigger_status']):
            raise ValueError(f"ADC replay differs from original negative control {prior['trial']}")
        cases.append((prior, card, volts))
    cells = {(s['x_contact_id'], s['y_contact_id']) for _, card, _ in cases if card is not None
             for pair in card['pairings'] if pair['energy_compatible'] for s in pair['sites']}
    templates = study.load_templates(inputs, cells, field, channels, positions | positive_positions)
    if len(cases) != saved['negative_conditions'] or any(saved['input_sha256'].get(k) != v for k, v in inputs.hashes.items()):
        raise ValueError('Original negative control or calibration input scope changed')
    return cases, templates, scales['controls']['group_rms_scales'], inputs.hashes


def compare_trial(prior, card, volts, templates, scales, points):
    pairs = []
    original_pairs = prior['pairings']
    for pair, original in zip(card['pairings'] if card else (), original_pairs, strict=True):
        fit = uncertainty.joint.fit_pairing(pair, card['collectors'], templates, scales, local_adc_volts=volts,
                                            compatibility=True, include_all_channels=True, include_partial_lateral=True)
        cells = [[s['x_contact_id'], s['y_contact_id']] for s in pair['sites']]
        energies = [s['energy_keV'] for s in pair['sites']]
        if (pair['index'], cells, fit['status']) != (original['pairing_index'], original['cells'], original['status']):
            raise ValueError('The retained pairing identities or status changed')
        models, deltas, projection = {}, {}, {}
        for name in spread.MODELS:
            model = fit.get('fits', {}).get('waveform_all', {}).get(name)
            reference = original['hypotheses'].get(f'waveform_all_{name}')
            if (model is None) != (reference is None):
                raise ValueError('The replay has a different center/lateral model roster')
            models[name] = spread.solutions(model) if model is not None else []
            if model is not None:
                deltas[name] = spread.replay_differences(model, reference, energies)
                projection[name] = {'archived_available_cones': reference['available_cones'],
                                    'current_available_cones': uncertainty.available_cones(model, energies, pair['compton_orders'])}
        orders = [o | {'models': {name: spread.order_geometry(models[name], energies, o, points, spread.RADII_MM)
                                  for name in spread.MODELS}} for o in pair['compton_orders']]
        pairs.append({'pairing_index': pair['index'], 'cells': cells, 'pairing_status': fit['status'],
                      'measured_site_energies_keV': energies, 'energy_compatible': pair['energy_compatible'],
                      'models': models, 'orders': orders, 'archived_fit_replay_differences': deltas,
                      'best_solution_projection_availability': projection,
                      'posthoc_cell_match': original['match_label']})
    # Attach the archived multi-point labels only once measured fitting is complete.
    keys = ('trial', 'adc_sha256', 'triggers', 'trigger_status', 'noise_seed', 'adc_phase_ns',
            'holdout_group', 'input_site_count', 'true_collecting_cells', 'reference_sites')
    return {k: prior[k] for k in keys} | {'pairings': pairs}


def distribution(values):
    return {'n': len(values), 'min': min(values, default=None), 'median': median(values) if values else None,
            'max': max(values, default=None)}


def scope_summary(trials, model, *, known_pair_only=False):
    by_trial = [[order['models'][model] for pair in t['pairings']
                 if not known_pair_only or pair['posthoc_cell_match'] == 'true_two_site_assignment'
                 for order in pair['orders'] if order['models'][model]['geometry_count'] > 1]
                for t in trials]
    orders = [o for trial in by_trial for o in trial]
    by_radius = []
    for i, radius in enumerate(spread.RADII_MM):
        key = 'geometric_angle_span_max_deg'
        by_radius.append({'radius_mm': radius,
                          'order_spans_deg': distribution([o['finite_vertex_response_by_radius'][i][key] for o in orders]),
                          'trigger_maxima_deg': distribution([max(o['finite_vertex_response_by_radius'][i][key] for o in q)
                                                             for q in by_trial if q])})
    return {'readout_conditions': len(trials), 'trials_with_multiple_geometries_for_an_order': sum(bool(q) for q in by_trial),
            'physical_layouts': len({t['holdout_group'] for t in trials}),
            'order_axis_span_deg': distribution([o['axis_pairwise_span_max_deg'] for o in orders]),
            'trigger_max_axis_span_deg': distribution([max(o['axis_pairwise_span_max_deg'] for o in q)
                                                       for q in by_trial if q]),
            'finite_vertex_angle_span_by_radius': by_radius}


def run(uncertainty_path, positive_path):
    prior = spread.bound(uncertainty_path, spread.UNCERTAINTY_SHA)
    positive = spread.bound(positive_path, POSITIVE_SHA)
    if (positive['input_sha256']['position_uncertainty'] != spread.UNCERTAINTY_SHA
            or tuple(positive['grid']['radii_mm']) != spread.RADII_MM
            or positive['grid']['fixed_angular_kernel_sigma_deg'] != spread.SIGMA_DEG):
        raise ValueError('The positive comparison must use the original control data and source-blind grid')
    grid = positive['grid']
    points = np.vstack([r*np.asarray(grid['unit_directions']) for r in grid['radii_mm']]) + grid['origin_mm']
    cases, templates, scales, hashes = fit_inputs(prior)
    trials = [compare_trial(old, card, volts, templates, scales, points) for old, card, volts in cases]
    groups = sorted({r['holdout_group'] for r in trials})
    matrices = {m: {'retained_positive_trials_all_pairings': scope_summary(positive['trials'], m),
                    'retained_positive_trials_known_pairing_posthoc': scope_summary(positive['trials'], m, known_pair_only=True),
                    'negative_trials_all_pairings': scope_summary(trials, m),
                    'negative_trials_by_layout': {g: scope_summary([r for r in trials if r['holdout_group'] == g], m)
                                                  for g in groups}}
                for m in spread.MODELS}
    paths = (__file__, spread.__file__, uncertainty.__file__, uncertainty.joint.__file__, uncertainty.study.__file__)
    return {'kind': 'gegi_wrong_topology_joint_cone_spread_v1', 'grid': grid,
            'input_sha256': hashes | {'position_uncertainty': spread.UNCERTAINTY_SHA, 'positive_cone_spread': POSITIVE_SHA},
            'source_sha256': {Path(f).name: sha(Path(f).read_bytes()) for f in paths},
            'archived_source_sha256': prior['source_sha256'], 'negative_controls': trials,
            'negative_pairing_statuses': dict(Counter(p['pairing_status'] for r in trials for p in r['pairings'])),
            'comparison': matrices,
            'definition': 'Current-producer replay retains the original twelve negative ADC identities, measured fit energies '
                          'and pairings. Both positions move together. Statistics use orders with at least two '
                          'mathematically available sampled geometries. Single/absent samples remain explicit in the raw '
                          'ledger. The positive comparison is read from its frozen receipt. Physical layouts are repeated '
                          'readout conditions. Topology labels and the known positive pairing comparison are post-fit. '
                          'Spans measure the sampled optimization alternatives without a topology threshold, confidence '
                          'level, source location, or imaging-weight change.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--uncertainty', required=True, type=Path)
    parser.add_argument('--positive-cone-spread', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Choose a new output path')
    result = run(args.uncertainty, args.positive_cone_spread)
    data = encoded(result)+b'\n'
    with args.output.open('xb') as stream:
        stream.write(data)
    print(json.dumps({'sha256': sha(data), 'negative_conditions': len(result['negative_controls'])}))


if __name__ == '__main__':
    main()
