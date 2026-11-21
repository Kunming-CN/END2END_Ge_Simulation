"""Test measured GeGI two-site positions with one archived lateral-response grid."""

import argparse
from collections import Counter
import json
import math
from pathlib import Path
from time import perf_counter

from gegi_event_store import encoded
import gegi_joint_two_site as joint
import gegi_position_compatibility as evidence
from gegi_two_site_cfd_study import angle_error, axis_between
import scenario_workflow as workflow


OUTPUT = evidence.OUTPUT.with_name('partial-lateral-compatibility.json')
MODES = ('waveform', 'waveform_all')


def differences(rows, methods):
    return {method: {metric: evidence.distribution([item[method][metric] for item in rows])
                     for metric in ('all_adc_rms_codes', 'abs_axis_shift_deg')}
            for method in methods}


def controlled_mixtures():
    replay = evidence.study.run(compatibility=True, partial_lateral=True, case_indices={3})
    base_path, base_digest = evidence.CONTROL_BASELINES[0]
    archived = evidence.study.cfd.scan.Inputs().read(base_path, base_digest)
    rows = []
    for row in replay['trials']:
        old = archived['trials'][row['trial_index']]
        if row['adc_sha256'] != old['adc_sha256']:
            raise ValueError('Controlled ADC changed on the one-grid trial')
        data = row['truth_comparison']
        truth_cells = [d['contact_ids'] for d in row['truth_injections']]
        original = next(f for f in row['fits'] if sorted(f['contact_ids']) == sorted(truth_cells))
        models = original['fits']
        fits = {}
        for mode in MODES:
            # Truth comparisons use the same measured pairing in both models.
            fits[mode] = []
            for variant in ('center', 'partial_lateral'):
                key = mode + '_' + variant
                item = models[mode][variant]
                comparison = data[key]
                fits[mode].append({**evidence.compatibility_scores(item),
                                   **{k: comparison[k] for k in ('axis_error_deg', 'site_xy_error_mm', 'site_depth_error_mm')},
                                   'site_lateral_support': item.get('site_lateral_support', [False, False])})
            if any(fits[mode][0]['site_xy_error_mm'][i] != fits[mode][1]['site_xy_error_mm'][i]
                   for i, supported in enumerate(fits[mode][1]['site_lateral_support']) if not supported):
                raise ValueError('The unsupported site moved laterally')
        rows.append({'trial_id': row['trial_index'], 'adc_sha256': row['adc_sha256'], 'fits': fits})

    summary = {}
    for mode in MODES:
        paired = [row['fits'][mode] for row in rows]
        summary[mode] = {
            'shared_trials': len(paired),
            'axis_error_rms_deg': [evidence.n_rms([p[i]['axis_error_deg'] for p in paired]) for i in (0, 1)],
            'xy_error_rms_mm': [evidence.n_rms([e for p in paired for e in p[i]['site_xy_error_mm']]) for i in (0, 1)],
            'supported_site_xy_error_rms_mm': [evidence.n_rms([
                e for p in paired for e, ok in zip(p[i]['site_xy_error_mm'], p[1]['site_lateral_support'], strict=True) if ok])
                for i in (0, 1)],
            'depth_error_rms_mm': [evidence.n_rms([e for p in paired for e in p[i]['site_depth_error_mm']]) for i in (0, 1)],
            'axis_error_increased': sum(p[1]['axis_error_deg'] > p[0]['axis_error_deg'] for p in paired),
            'invalid_modeled_crossings': [sum(bool(p[i]['invalid_modeled_crossings']) for p in paired) for i in (0, 1)],
            'optimizer_converged': [sum(p[i]['optimizer_success'] for p in paired) for i in (0, 1)],
            'global_adc_rms_codes': [evidence.distribution([p[i]['all_adc_rms_codes'] for p in paired]) for i in (0, 1)],
        }
    return {'scope': 'Same two independent off-center injection coordinates at twelve energy/phase/noise conditions.',
            'control_baseline_sha256': base_digest, 'input_sha256': replay['input_sha256'], 'summary': summary, 'trials': rows}


def retained_pairings():
    paths, stamps, report, manifest, templates, training, lateral_cells, fit_rows, ids = evidence.retained_candidate_inputs()
    rows = []
    missing = Counter()
    coverage = Counter()
    for trigger_id, fitted in zip(ids, fit_rows, strict=True):
        selected = []
        for prior in fitted['pairings']:
            if prior['fit']['status'] != 'fitted':
                continue
            cells = [tuple(cell) for cell in prior['cells']]
            support = [cell in lateral_cells for cell in cells]
            coverage[sum(support)] += 1
            if sum(support) == 1:
                selected.append((prior, cells, support))
        if not selected:
            continue
        saved = evidence.storage.load_candidate(paths['candidate_store'], trigger_id)
        volts, status = evidence.imaging.voltage_window(saved, report['excluded_intervals_ns'])
        if status != 'captured' or fitted['window_status'] != status or saved['trigger_time_ns'] != fitted['time_ns']:
            raise ValueError('Partial-lateral replay does not use the original ADC window')
        event = saved['card']['two_strip_pairings']
        original = {p['index']: p for p in event['pairings']}
        for prior, cells, support in selected:
            pairing = original[prior['index']]
            if not pairing['energy_compatible'] or cells != [(s['x_contact_id'], s['y_contact_id']) for s in pairing['sites']]:
                raise ValueError('Partial-lateral replay pairing is not the original measured pair')
            result = joint.fit_pairing(pairing, event['collectors'], templates, manifest['feature_scales'],
                                       local_adc_volts=volts, compatibility=True, include_all_channels=True,
                                       include_partial_lateral=True)
            fits = {}
            for mode in MODES:
                modes = result['fits'][mode]
                base, partial = modes['center'], modes['partial_lateral']
                if mode == 'waveform':
                    expected = prior['fit']['fits']['waveform']['center']['weighted_residual_rms']
                    if not math.isclose(expected, base['weighted_residual_rms'], rel_tol=1e-6, abs_tol=1e-6):
                        raise ValueError('Original local center objective did not reproduce')
                if partial['site_lateral_support'] != support or any(
                        a[:2] != b[:2] for a, b, ok in zip(base['positions_mm'], partial['positions_mm'], support, strict=True)
                        if not ok):
                    raise ValueError('Partial fit used an unsupported lateral response')
                axes = [axis_between(*item['positions_mm']) for item in (base, partial)]
                fits[mode] = {**evidence.compatibility_scores(partial),
                              'baseline_all_adc_rms_codes': evidence.compatibility_scores(base)['all_adc_rms_codes'],
                              'abs_axis_shift_deg': angle_error(*axes),
                              'positions_mm': partial['positions_mm'],
                              'sampled_near_tie_spread': partial['sampled_near_tie_spread']}
            missing.update(cell for cell, ok in zip(cells, support, strict=True) if not ok)
            rows.append({'original_trigger_id': trigger_id, 'pairing_index': prior['index'], 'cells': cells,
                         'site_lateral_support': support, 'fits': fits})
    if len(rows) != coverage[1] or any(workflow.sha(path) != stamps[key] for key, path in paths.items()):
        raise ValueError('Partial-lateral replay denominator or original inputs changed')
    summary = differences([row['fits'] for row in rows], MODES)
    for mode, data in summary.items():
        items = [row['fits'][mode] for row in rows]
        data.update(optimizer_converged=sum(fit['optimizer_success'] for fit in items),
                    valid_modeled_crossings=sum(not fit['invalid_modeled_crossings'] for fit in items),
                    any_parameter_boundary=sum(bool(fit['boundaries']) for fit in items),
                    global_adc_rms_increased=sum(fit['all_adc_rms_codes'] > fit['baseline_all_adc_rms_codes'] for fit in items),
                    baseline_adc_rms_codes=evidence.distribution([fit['baseline_all_adc_rms_codes'] for fit in items]))
    return {'input_sha256': stamps, 'lateral_training_input_sha256': training,
            'full_candidate_fitted_pairings_by_supported_site_count': coverage,
            'partial_lateral_refits': len(rows), 'summary': summary, 'rows': rows,
            'missing_lateral_cells_by_observed_one_grid_pairing_count':
                [{'cell': cell, 'count': count} for cell, count in sorted(missing.items(), key=lambda pair: (-pair[1], pair[0]))]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    args = parser.parse_args()
    if args.output.exists() or not args.output.resolve().is_relative_to(OUTPUT.parent):
        parser.error('Choose a new output in the reconstruction evidence directory')
    begun = perf_counter()
    result = {'kind': 'gegi_partial_lateral_compatibility_v1',
              'scope': 'Existing calibration grid for one site. The unsupported site remains at its measured strip-center XY. '
                       'Both depths and one common onset still fit. No truth-selected acceptance or new drift.',
              'controlled_mixtures': controlled_mixtures(), 'retained_candidates': retained_pairings(),
              'source_sha256': {Path(m.__file__).name: workflow.sha(Path(m.__file__)) for m in (joint, evidence, evidence.study)}
                               | {Path(__file__).name: workflow.sha(Path(__file__))},
              'elapsed_s': perf_counter() - begun}
    args.output.parent.mkdir(exist_ok=True)
    with args.output.open('xb') as stream:
        stream.write(encoded(result) + b'\n')
    print(json.dumps({'control_summary': result['controlled_mixtures']['summary'],
                      'candidate_summary': result['retained_candidates']['summary'],
                      'elapsed_s': result['elapsed_s']}, indent=2))


if __name__ == '__main__':
    main()
