"""Score GeGI position compatibility and empirical errors on saved native traces."""

import argparse
from collections import Counter, defaultdict
from itertools import product
import json
import math
from pathlib import Path
from time import perf_counter

import numpy as np

import gegi_cs_joint_lateral_holdout as cs
import gegi_dual_source as dual
from gegi_event_store import encoded
from gegi_exposure_stream import ADCExposure, reconstruct_exposure
from gegi_imaging import cone
import gegi_joint_two_site as joint
import gegi_joint_two_site_study as study
import gegi_position_compatibility as evidence
from gegi_position_transfer_study import load_record


OUTPUT = evidence.OUTPUT.with_name('position-uncertainty-controls.json')
OUTPUT_SHA256 = '6accb91c8e3076b0b535e5d3a1fea662c951450aab9645b97a1c9ad79fcccd24'
ADDITIONAL_OUTPUT = OUTPUT.with_name('additional-lateral-grid-controls.json')
GENERAL_CAPTURE = study.cfd.depth.CAPTURES[0][1]
NOISE_BASE = study.cfd.BASE_NOISE_SEED + 1000
NEGATIVE_GEOMETRIES = (
    ('three_distinct_cells', ('injections/point-053.json', 'injections/point-139.json',
                              'diagnostic-injections/9-26/x_plus-z3.json'),
     ((331., 331., 4.), (331., 331., 40.))),
    ('three_points_two_cells', ('injections/point-081.json', 'injections/point-109.json', 'injections/point-082.json'),
     ((132.4, 494.6, 35.), (291., 331., 40.))),
    ('four_points_two_cells', ('injections/point-193.json', 'injections/point-194.json',
                               'injections/point-221.json', 'injections/point-222.json'),
     ((165., 166., 165., 166.), (40., 291., 40., 291.))),
)
METHODS = ('waveform_center', 'waveform_partial_lateral', 'waveform_lateral',
           'waveform_all_center', 'waveform_all_partial_lateral', 'waveform_all_lateral')
ADDITIONAL_GRIDS = (
    ('additional_far_layout_1', ('injections/point-083.json', 'injections/point-110.json')),
    ('additional_far_layout_2', ('injections/point-084.json', 'injections/point-111.json')),
    ('additional_near_layout_1', ('injections/point-195.json', 'injections/point-223.json')),
    ('additional_near_layout_2', ('injections/point-196.json', 'injections/point-224.json')),
)


def position_error(estimated_xyz, energy_keV, truth):
    xyz = [a - b for a, b in zip(estimated_xyz, truth['xyz_mm'], strict=True)]
    return xyz + [energy_keV - truth['energy_keV']]


def summarize_errors(vectors):
    if not vectors:
        return {'n': 0, 'bias': None, 'sample_covariance': None, 'rms': None}
    matrix = np.asarray(vectors, dtype=float)
    return {'n': len(matrix), 'bias': matrix.mean(axis=0).tolist(),
            'sample_covariance': np.cov(matrix, rowvar=False, ddof=1).tolist() if len(matrix) > 1 else None,
            'rms': np.sqrt(np.mean(matrix**2, axis=0)).tolist()}


def exact_cell_order(cells, true_sites):
    truth_cells = [site['contact_ids'] for site in true_sites]
    if len(truth_cells) != 2 or len({tuple(cell) for cell in truth_cells}) != 2 or sorted(truth_cells) != sorted(cells):
        return None
    return [cells.index(cell) for cell in truth_cells]


def available_cones(model, energies, orders):
    if not model['optimizer_success']:
        return 0
    sites = [dict(position_mm=xyz, energy_keV=e) for xyz, e in zip(model['positions_mm'], energies, strict=True)]
    return sum(cone(*(sites[i] for i in order['site_index_order'])) is not None
               for order in orders if order['kinematically_allowed'])


def observed_hypotheses(fits, true_sites):
    """Score every observed hypothesis; truth supplies labels and signed errors after fitting."""
    records = []
    for pair in fits:
        cells = pair['contact_ids']
        order = exact_cell_order(cells, true_sites)
        label = ('true_two_site_assignment' if order is not None else
                 'wrong_cell_pairing' if len(true_sites) == 2 else 'wrong_spatial_topology')
        data = {'pairing_index': pair['pairing_index'], 'cells': cells, 'status': pair['status'],
                'match_label': label, 'hypotheses': {}}
        for mode, models in pair.get('fits', {}).items():
            for representation, model in models.items():
                method = f'{mode}_{representation}'
                if method not in METHODS:
                    continue
                energies = pair['measured_site_energies_keV']
                xyz = model['positions_mm']
                score = {**evidence.compatibility_scores(model), 'contact_rms_adc_codes': model['compatibility']['adc_rms_codes'],
                         'fit_contact_ids': model['compatibility']['fitted_contact_ids'],
                         'near_tie_parameter_spread': model['sampled_near_tie_spread'],
                         'near_tie_axis_spread_deg': max((study.cfd.angle_error(
                              study.cfd.axis_between(*xyz), study.cfd.axis_between(*alt['positions_mm']))
                              for alt in model['sampled_alternates']), default=0.),
                         'available_cones': available_cones(model, energies, pair['order_hypotheses']),
                         'positions_mm': xyz, 'measured_site_energies_keV': energies,
                         'site_lateral_support': model.get('site_lateral_support', [representation == 'lateral'] * 2)}
                if order is not None:
                    ordered = [xyz[i] for i in order]
                    actual = [site['xyz_mm'] for site in true_sites]
                    score.update(axis_error_deg=study.cfd.angle_error(study.cfd.axis_between(*ordered), study.cfd.axis_between(*actual)),
                                 site_errors_in_input_order=[position_error(xyz[i], energies[i], target)
                                                             for i, target in zip(order, true_sites, strict=True)])
                data['hypotheses'][method] = score
        records.append(data)
    return records


def yes_controls():
    general = study.run(compatibility=True, partial_lateral=True)
    targeted = cs.run(compatibility=True)
    inputs = study.cfd.scan.Inputs()
    original = inputs.read(study.STUDY, study.STUDY_SHA)
    rows = []
    for row in general['trials']:
        archived = original['trials'][row['trial_index']]
        if row['adc_sha256'] != archived['adc_sha256']:
            raise ValueError('General controls do not use their original ADC samples')
        truth = [dict(q, energy_keV=energy) for q, energy in zip(row['truth_injections'], row['energies_keV'], strict=True)]
        for fit, pair in zip(row['fits'], archived['measured_pairings'], strict=True):
            if fit['pairing_index'] != pair['index']:
                raise ValueError('General measured pairing identity changed')
            fit['measured_site_energies_keV'] = [site['energy_keV'] for site in pair['sites']]
        group = f'general_geometry_{row["case_index"] + 1}'
        rows.append({'trial': row['trial_index'], 'cohort': 'general', 'holdout_group': group,
                     'geometry': group, 'adc_sha256': row['adc_sha256'], 'reference_sites': truth,
                     'trigger_status': 'pairings_measured', 'pairings': observed_hypotheses(row['fits'], truth)})
    baseline = inputs.read(*evidence.CONTROL_BASELINES[1])
    for row, old in zip(targeted['trials'], baseline['trials'], strict=True):
        if row['adc_sha256'] != old['adc_sha256']:
            raise ValueError('Targeted controls do not use their original ADC samples')
        truth = [dict(q, energy_keV=q['input_energy_keV']) for q in row['truth_injections']]
        rows.append({'trial': row['index'], 'cohort': 'targeted_cs', 'holdout_group': 'targeted_cs_cell_pair',
                     'geometry': f'targeted_cs_layout_{row["index"] + 1}', 'adc_sha256': row['adc_sha256'],
                     'reference_sites': truth, 'trigger_status': row['status'],
                     'pairings': observed_hypotheses(row['fits'], truth)})
    return rows, general['input_sha256'] | targeted['input_sha256'] | inputs.hashes


def load_archived_traces(inputs, field, refs, excluded_positions):
    seal = inputs.read(GENERAL_CAPTURE/'COMPLETE.json', study.cfd.depth.CAPTURES[0][2])
    request = inputs.read(GENERAL_CAPTURE/'bound-request.json', seal['request_sha256'])
    bank = study.cfd.depth.FULL
    complete = inputs.read(bank/'COMPLETE.json', study.cfd.scan.FULL_COMPLETE_SHA)
    bank_request = inputs.read(bank/'bound-request.json', complete['request_sha256'])
    identity = inputs.read(bank/'identity.json', complete['bundle_identity_sha256'])
    channels = request['channels']
    for specification in (request, bank_request):
        if (specification['channels'] != channels or specification['model_sha256'] != field['model_sha256']
                or specification['field_cache']['sha256'] != field['field_cache_sha256']
                or specification['field_precision_bits'] != field['field_precision_bits']
                or specification['injection_energy_keV'] != study.cfd.depth.ENERGY_KEV):
            raise ValueError('Additional traces use a different field or channel configuration')
    bank_entries = study.cfd.depth.bank_manifest(inputs, complete, {ref for ref in refs if ref.startswith('diagnostic-injections/')})
    traces = {}
    for row in seal['records']:
        ref = row['record_ref']
        if ref in refs and row['role'] == 'holdout' and row['status'] == 'completed' and row['valid']:
            traces[ref] = load_record(inputs, GENERAL_CAPTURE, row, row, seal['request_sha256'], channels, 'capture_holdout')
    for point in bank_request['grid']:
        ref = point['target_ref']
        if ref in bank_entries and bank_entries[ref]['status'] == 'completed' and bank_entries[ref]['valid']:
            traces[ref] = load_record(inputs, bank/'bank', point, bank_entries[ref], identity['calibration_identity_sha256'],
                                      channels, 'off_center_bank_diagnostic')
    locations = {tuple(record['truth_xyz_mm']) for record in traces.values()}
    if traces.keys() != refs or len(locations) != len(refs) or locations & excluded_positions:
        raise ValueError('Additional geometry is incomplete, repeated or reused from earlier tests')
    return channels, traces, locations


def measure_adc(components, channels, phase_ns, noise_seed):
    clock = ADCExposure(components, live_time_ns=study.cfd.END_NS, phase_ns=phase_ns, noise_seed=noise_seed)
    result = reconstruct_exposure(clock)
    trigger_count = len(result['events'])
    if trigger_count != 1:
        return result['adc_sha256'], trigger_count, 'missing_or_multiple_triggers', None, None
    event, = result['events']
    card = dual._trigger_card(event, dual._strip_neighbors(channels), geometry=channels)['two_strip_pairings']
    if card is None:
        return result['adc_sha256'], trigger_count, 'no_two_strip_pairing', None, None
    blocks = list(clock.blocks())
    start = blocks[0][0]
    codes = np.concatenate([block for _, block in blocks], axis=1)
    indices = np.rint((event['trigger_time_ns'] + joint.SAMPLE_NS - phase_ns) / joint.digital._DT).astype(int) - start
    if indices[0] < 0 or indices[-1] >= codes.shape[1]:
        raise ValueError('The nominal ADC record is missing the measured fit window')
    return result['adc_sha256'], trigger_count, 'pairings_measured', card, codes[:, indices]*joint.digital._LSB_V


def no_controls(positive_rows):
    inputs = study.cfd.scan.Inputs()
    field = inputs.read(study.cfd.CURVES, study.cfd.CURVES_SHA)['provenance']
    scale_report = inputs.read(study.SCALES, study.SCALES_SHA)
    if any(scale_report[key] != field[key] for key in ('digital_profile_sha256', 'digital_timing_sha256')):
        raise ValueError('Negative fit scales use a different digital profile')
    positive_positions = {tuple(site['xyz_mm']) for row in positive_rows for site in row['reference_sites']}
    refs = {ref for _, selected, _ in NEGATIVE_GEOMETRIES for ref in selected}
    channels, traces, locations = load_archived_traces(inputs, field, refs, positive_positions)
    cases = []
    for name, refs, spreads in NEGATIVE_GEOMETRIES:
        for energies, phase in product(spreads, study.cfd.PHASE_NS):
            trial = len(cases)
            noise_seed = NOISE_BASE + trial
            source = [traces[ref] for ref in refs]
            truth = [dict(xyz_mm=r['truth_xyz_mm'], contact_ids=r['truth_contact_ids'], energy_keV=energy,
                          native_record_sha256=r['source_sha256']) for r, energy in zip(source, energies, strict=True)]
            components = [(r['native'], study.cfd.ONSET_NS, e/study.cfd.depth.ENERGY_KEV)
                          for r, e in zip(source, energies, strict=True)]
            adc, n, status, event, volts = measure_adc(components, channels, phase, noise_seed)
            cases.append(({'trial': trial, 'cohort': 'negative_mixture', 'holdout_group': name, 'geometry': name,
                           'adc_sha256': adc, 'triggers': n, 'trigger_status': status, 'reference_sites': truth,
                           'input_site_count': len(truth), 'true_collecting_cells': len({tuple(s['contact_ids']) for s in truth}),
                           'adc_phase_ns': phase, 'noise_seed': noise_seed}, event, volts))
    cells = {(s['x_contact_id'], s['y_contact_id']) for _, event, _ in cases if event is not None
             for pair in event['pairings'] if pair['energy_compatible'] for s in pair['sites']}
    templates = study.load_templates(inputs, cells, field, channels, locations | positive_positions)
    scales = scale_report['controls']['group_rms_scales']
    rows = []
    for row, event, volts in cases:
        fits = []
        for pair in event['pairings'] if event else ():
            fit = joint.fit_pairing(pair, event['collectors'], templates, scales, local_adc_volts=volts, compatibility=True,
                                    include_all_channels=True, include_partial_lateral=True)
            fits.append(dict(fit, pairing_index=pair['index'], order_hypotheses=pair['compton_orders'],
                             contact_ids=[[s['x_contact_id'], s['y_contact_id']] for s in pair['sites']],
                             measured_site_energies_keV=[s['energy_keV'] for s in pair['sites']]))
        row['pairings'] = observed_hypotheses(fits, row['reference_sites'])
        rows.append(row)
    return rows, inputs.hashes


def additional_grids():
    start = perf_counter()
    inputs = study.cfd.scan.Inputs()
    control = inputs.read(OUTPUT, OUTPUT_SHA256)
    field = inputs.read(study.cfd.CURVES, study.cfd.CURVES_SHA)['provenance']
    scale_report = inputs.read(study.SCALES, study.SCALES_SHA)
    if any(scale_report[key] != field[key] for key in ('digital_profile_sha256', 'digital_timing_sha256')):
        raise ValueError('Additional grid fit scales use a different digital profile')
    excluded = {tuple(site['xyz_mm']) for row in control['trials'] for site in row['reference_sites']}
    refs = {ref for _, pair in ADDITIONAL_GRIDS for ref in pair}
    channels, traces, locations = load_archived_traces(inputs, field, refs, excluded)
    cases = []
    for name, refs in ADDITIONAL_GRIDS:
        for energies, phase in product(((331., 331.), (132.4, 529.6)), study.cfd.PHASE_NS):
            trial = len(cases)
            seed = NOISE_BASE + 3000 + trial
            source = [traces[ref] for ref in refs]
            truth = [dict(xyz_mm=r['truth_xyz_mm'], contact_ids=r['truth_contact_ids'], energy_keV=e,
                          native_record_sha256=r['source_sha256']) for r, e in zip(source, energies, strict=True)]
            components = [(r['native'], study.cfd.ONSET_NS, e/study.cfd.depth.ENERGY_KEV)
                          for r, e in zip(source, energies, strict=True)]
            adc, n, status, event, volts = measure_adc(components, channels, phase, seed)
            cases.append(({'trial': trial, 'holdout_group': name, 'geometry': name, 'reference_sites': truth,
                           'adc_sha256': adc, 'triggers': n, 'trigger_status': status, 'adc_phase_ns': phase,
                           'noise_seed': seed}, event, volts))
    cells = {(s['x_contact_id'], s['y_contact_id']) for _, event, _ in cases if event is not None
             for pair in event['pairings'] if pair['energy_compatible'] for s in pair['sites']}
    templates = study.load_templates(inputs, cells, field, channels, excluded | locations)
    scales = scale_report['controls']['group_rms_scales']
    rows = []
    for row, event, volts in cases:
        fits = []
        for pair in event['pairings'] if event else ():
            fit = joint.fit_pairing(pair, event['collectors'], templates, scales, local_adc_volts=volts,
                                    compatibility=True, include_all_channels=True)
            fits.append(dict(fit, pairing_index=pair['index'], order_hypotheses=pair['compton_orders'],
                             contact_ids=[[s['x_contact_id'], s['y_contact_id']] for s in pair['sites']],
                             measured_site_energies_keV=[s['energy_keV'] for s in pair['sites']]))
        row['pairings'] = observed_hypotheses(fits, row['reference_sites'])
        rows.append(row)
    comparisons = {}
    for mode in ('waveform', 'waveform_all'):
        comparisons[mode] = {}
        for geometry in ('all', *(case for case, _ in ADDITIONAL_GRIDS)):
            group = [r for r in rows if geometry == 'all' or r['geometry'] == geometry]
            pairs = [p['hypotheses'] for r in group for p in r['pairings'] if p['match_label'] == 'true_two_site_assignment']
            methods = [f'{mode}_center', f'{mode}_lateral']
            matched = [pair for pair in pairs if all(m in pair for m in methods)]
            comparisons[mode][geometry] = {
                'total_conditions': len(group), 'exact_pair_matched_conditions': len(matched),
                'axis_rmse_deg': [evidence.n_rms([p[m]['axis_error_deg'] for p in matched]) for m in methods],
                'xy_rmse_mm': [evidence.n_rms([math.hypot(*error[:2]) for p in matched for error in p[m]['site_errors_in_input_order']])
                               for m in methods],
                'depth_rmse_mm': [evidence.n_rms([error[2] for p in matched for error in p[m]['site_errors_in_input_order']])
                                 for m in methods],
                'axis_error_increased': sum(p[methods[1]]['axis_error_deg'] > p[methods[0]]['axis_error_deg'] for p in matched),
                'projectable_fit_counts': [sum(p[m]['available_cones'] > 0 for p in matched) for m in methods],
            }
    return {'kind': 'gegi_additional_existing_lateral_grid_controls_v1', 'trials': rows, 'matched_comparisons': comparisons,
            'sites_with_additional_archived_lateral_grids': sorted(cell for cell, t in templates.items()
                                                                  if t.lateral_correction_v_per_keV is not None),
            'scope': 'Four independent physical layouts, two energy divisions and two ADC phases. Coordinates are distinct '
                     'from every earlier clean and mixed-topology control and every fitted native template.',
            'input_sha256': inputs.hashes, 'elapsed_seconds': perf_counter()-start,
            'source_sha256': {Path(p.__file__).name: evidence.workflow.sha(Path(p.__file__))
                              for p in (joint, study, evidence)} | {Path(__file__).name: evidence.workflow.sha(Path(__file__))}}


def hypotheses(rows, method, label):
    return [pair['hypotheses'][method] for row in rows for pair in row['pairings']
            if pair['match_label'] == label and method in pair['hypotheses']]


def short_scores(rows):
    return {'fit_hypotheses': len(rows),
            'all_contact_adc_rms_codes': evidence.distribution([r['all_adc_rms_codes'] for r in rows]),
            'nonfit_contact_adc_rms_codes': evidence.distribution([r['nonfit_adc_rms_codes'] for r in rows
                                                                  if r['nonfit_adc_rms_codes'] is not None]),
            'near_tie_axis_spread_deg': evidence.distribution([r['near_tie_axis_spread_deg'] for r in rows]),
            'any_boundary': sum(bool(r['boundaries']) for r in rows),
            'invalid_crossing': sum(bool(r['invalid_modeled_crossings']) for r in rows),
            'projectable_hypotheses': sum(r['available_cones'] > 0 for r in rows)}


def summary(positive, negative):
    result = {}
    groups = sorted({r['holdout_group'] for r in positive})
    for method in METHODS:
        matched = {}
        group_mean_errors = []
        for group in groups:
            rows = [r for r in positive if r['holdout_group'] == group]
            correct = hypotheses(rows, method, 'true_two_site_assignment')
            wrong = hypotheses(rows, method, 'wrong_cell_pairing')
            vectors = [e[0] + e[1] for q in correct if (e := q['site_errors_in_input_order'])]
            moments = summarize_errors(vectors)
            if moments['bias'] is not None:
                group_mean_errors.append(moments['bias'])
            matched[group] = {'trials': len(rows), 'matched': short_scores(correct), 'wrong_pairing': short_scores(wrong),
                              'axis_errors_deg': evidence.distribution([q['axis_error_deg'] for q in correct]),
                              'paired_error_statistics': moments}
        wrong_topology = hypotheses(negative, method, 'wrong_spatial_topology')
        topology_by_group = {}
        for group in sorted({r['holdout_group'] for r in negative}):
            rows = [r for r in negative if r['holdout_group'] == group]
            available = sum(any(p['hypotheses'].get(method, {}).get('available_cones', 0)
                                for p in row['pairings']) for row in rows)
            topology_by_group[group] = {'conditions': len(rows), 'wrong_topology_available_to_projection': available,
                                        'trigger_statuses': Counter(row['trigger_status'] for row in rows)}
        result[method] = {'whole_geometry_groups': matched, 'between_group_mean_error_statistics': summarize_errors(group_mean_errors),
                          'wrong_topology': short_scores(wrong_topology), 'wrong_topology_groups': topology_by_group}
    return result


def run():
    start = perf_counter()
    positive, input_positive = yes_controls()
    negative, input_negative = no_controls(positive)
    return {'kind': 'gegi_position_empirical_uncertainty_controls_v1',
            'error_order': ['site_1_dx_mm', 'site_1_dy_mm', 'site_1_dz_mm', 'site_1_dE_keV',
                            'site_2_dx_mm', 'site_2_dy_mm', 'site_2_dz_mm', 'site_2_dE_keV'],
            'definition': 'All signed differences are measured minus injected. Site numbering follows input order for comparison '
                          'only. Point mixtures are generated from archived native traces at a common onset and read with the existing ADC.',
            'validation_groups': 'The 48 general controls use four physically distinct two-point geometries, each with 12 readout '
                                 'conditions. Each targeted Cs trial has a unique point pair within one fixed pair of cells; these trials '
                                 'remain one whole holdout group. Negative mixtures use additional disjoint coordinates and nominal ADC noise.',
            'calibration_status': 'descriptive_only_insufficient_independent_geometry_groups_for_a_new_compatibility_gate',
            'scope': 'Within-group and between-group statistics are sample summaries for the listed simulated conditions. '
                     'The repeated noise, phase and energy conditions share geometries. No intervals, detector covariance, or threshold transfer.',
            'positive_conditions': len(positive), 'negative_conditions': len(negative),
            'summary': summary(positive, negative), 'trials': positive + negative,
            'input_sha256': input_positive | input_negative, 'elapsed_seconds': perf_counter() - start,
            'source_sha256': {Path(p.__file__).name: evidence.workflow.sha(Path(p.__file__))
                              for p in (joint, study, cs, evidence)} | {Path(__file__).name: evidence.workflow.sha(Path(__file__))}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--additional-grids', action='store_true', help='Score the four other archived grids on unused clean coordinates')
    args = parser.parse_args()
    output = args.output or (ADDITIONAL_OUTPUT if args.additional_grids else OUTPUT)
    if output.exists() or not output.resolve().is_relative_to(OUTPUT.parent):
        parser.error('Choose a new output in the reconstruction evidence directory')
    result = additional_grids() if args.additional_grids else run()
    output.parent.mkdir(exist_ok=True)
    with output.open('xb') as stream:
        stream.write(encoded(result) + b'\n')
    if args.additional_grids:
        print(json.dumps(result['matched_comparisons'], indent=2))
    else:
        print(json.dumps({k: result[k] for k in ('positive_conditions', 'negative_conditions', 'elapsed_seconds')}, indent=2))


if __name__ == '__main__':
    main()
