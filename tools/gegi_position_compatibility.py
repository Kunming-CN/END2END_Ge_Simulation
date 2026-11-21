"""Evaluate two-site GeGI positions against retained ADC and controlled mixtures."""

import argparse
from collections import Counter, defaultdict
from dataclasses import replace
import gzip
import json
import math
from pathlib import Path
from time import perf_counter

import numpy as np

import gegi_candidate_imaging as imaging
import gegi_candidate_storage as storage
import gegi_cs_joint_lateral_holdout as cs
from gegi_event_store import encoded
import gegi_joint_calibration as calibration
import gegi_joint_two_site as joint
import gegi_joint_two_site_study as study
import scenario_workflow as workflow


ROOT = study.ROOT
RUN = ROOT / '.local/gegi-candidate-runs/steady-five-seconds'
CENTERS = study.LOCAL / 'gegi-center-calibration.npz'
BASELINE = RUN / 'candidate-imaging.json.gz'
BASELINE_SHA = '78124e398de1dbe41f2f4ca5d17269c9b213ae7f207d4c13b4943b8fc90e0863'
CONTROL_BASELINES = (
    (study.LOCAL / 'study.json', '86dafb062393a68cd30db5f5424581a49e469d83bab8280642645c1b29c2085f'),
    (cs.BASE / 'held-out-study.json', '939d7a78fc5f83586e6a4c464e18f0215808721f4ede3a7a1c91be843ee5da44'),
)
OUTPUT = ROOT / '.local/gegi-reconstruction-v1/position-compatibility.json'
REFIT_STRIDE = 24
METHODS = ('waveform_center', 'waveform_all_center', 'waveform_lateral', 'waveform_all_lateral')


def distribution(values):
    if not len(values):
        return {'n': 0}
    return {'n': len(values), 'median': float(np.median(values)), 'p90': float(np.quantile(values, .9)),
            'max': float(np.max(values))}


def n_rms(values):
    return math.sqrt(np.mean(np.square(values))) if len(values) else None


def compatibility_scores(fit):
    data = fit['compatibility']
    residual_rms = np.array(data['adc_rms_codes'])
    fitted = np.isin(data['contact_ids'], data['fitted_contact_ids'])
    return {'all_adc_rms_codes': n_rms(residual_rms), 'fitted_adc_rms_codes': n_rms(residual_rms[fitted]),
            'nonfit_adc_rms_codes': n_rms(residual_rms[~fitted]),
            'optimizer_success': fit['optimizer_success'],
            'invalid_modeled_crossings': [r['contact_id'] for r in data['collector_timing']
                                          if not r['modeled_crossing_valid']],
            'boundaries': {key: side for key, side in fit['parameter_boundaries'].items() if side is not None}}


def trial_method(fits, method):
    mode, form = method.rsplit('_', 1)
    return fits[mode][form]


def controlled_summary(result, baseline, digest):
    trials = []
    original_method_max_axis_shift = 0.
    for trial, saved in zip(result['trials'], baseline['trials'], strict=True):
        if trial['adc_sha256'] != saved['adc_sha256']:
            raise ValueError('Controlled trial ADC differs from its archived baseline')
        truth = trial['truth_comparison']
        correct_pattern = [r['contact_ids'] for r in trial['truth_injections']]
        correct = next((row for row in trial['fits'] if row['status'] == 'fitted'
                        and sorted(row['contact_ids']) == sorted(correct_pattern)), None)
        scored = {}
        for method in METHODS:
            if method not in truth:
                continue
            fit = trial_method(correct['fits'], method)
            scored[method] = {**compatibility_scores(fit),
                              **{k: truth[method][k] for k in ('axis_error_deg', 'site_depth_error_mm', 'site_xy_error_mm')}}
            if method in saved['truth_comparison']:
                shift = truth[method]['axis_error_deg'] - saved['truth_comparison'][method]['axis_error_deg']
                original_method_max_axis_shift = max(original_method_max_axis_shift, abs(shift))
        trials.append({'id': trial.get('trial_index', trial.get('index')), 'adc_sha256': trial['adc_sha256'],
                       'neighborhood': trial['neighborhood'], 'fits': scored})

    def paired(base, changed):
        common = [t for t in trials if base in t['fits'] and changed in t['fits']]
        if not common:
            return {'shared_trials': 0}
        pairs = [[t['fits'][m] for m in (base, changed)] for t in common]
        return {'shared_trials': len(common), 'trial_ids': [t['id'] for t in common],
                'axis_error_rms_deg': [n_rms([p[i]['axis_error_deg'] for p in pairs]) for i in (0, 1)],
                'xy_error_rms_mm': [n_rms([err for p in pairs for err in p[i]['site_xy_error_mm']]) for i in (0, 1)],
                'depth_error_rms_mm': [n_rms([err for p in pairs for err in p[i]['site_depth_error_mm']]) for i in (0, 1)],
                'all_adc_rms_codes_median': [float(np.median([p[i]['all_adc_rms_codes'] for p in pairs])) for i in (0, 1)],
                'axis_error_increased': sum(p[1]['axis_error_deg'] > p[0]['axis_error_deg'] for p in pairs),
                'xy_error_increased': sum(n_rms(p[1]['site_xy_error_mm']) > n_rms(p[0]['site_xy_error_mm']) for p in pairs),
                'depth_error_increased': sum(n_rms(p[1]['site_depth_error_mm']) > n_rms(p[0]['site_depth_error_mm']) for p in pairs),
                'adc_residual_increased': sum(p[1]['all_adc_rms_codes'] > p[0]['all_adc_rms_codes'] for p in pairs),
                'invalid_modeled_crossings': [sum(bool(p[i]['invalid_modeled_crossings']) for p in pairs) for i in (0, 1)]}

    comparisons = ((METHODS[0], METHODS[1]), (METHODS[0], METHODS[2]),
                   (METHODS[1], METHODS[3]), (METHODS[2], METHODS[3]))
    return {'trials_total': len(trials), 'computed_waveform_coverage': dict(Counter(m for t in trials for m in t['fits'])),
            'archived_baseline_sha256': digest, 'archive_adc_matches': len(trials),
            'maximum_local_baseline_axis_metric_difference_deg': original_method_max_axis_shift,
            'matched_comparisons': {f'{a}_to_{b}': paired(a, b) for a, b in comparisons},
            'trials': trials, 'source_sha256': result['source_sha256'], 'input_sha256': result['input_sha256']}


def retained_candidate_inputs():
    report_path = RUN / 'candidate-acquisition.json'
    database = RUN / storage.ARCHIVE_NAME
    paths = {'acquisition': report_path, 'candidate_store': database, 'calibration': CENTERS, 'baseline_fit': BASELINE}
    stamps = {name: workflow.sha(p) for name, p in paths.items()}
    if stamps['baseline_fit'] != BASELINE_SHA:
        raise ValueError('Expected the verified full original five-second fit')
    report = workflow.read(report_path)
    with gzip.open(BASELINE) as stream:
        baseline = json.load(stream)
    if (report['verification']['status'] != 'verified_exact'
            or report['artifacts'][storage.ARCHIVE_NAME]['sha256'] != stamps['candidate_store']
            or baseline['input_sha256'] != {k: stamps[k] for k in ('acquisition', 'candidate_store', 'calibration')}):
        raise ValueError('Baseline fit, stored ADC and calibration must share the original acquisition identity')
    manifest, templates, _, _ = calibration.load(CENTERS)
    if manifest['identity'] != baseline['candidate_analysis']['calibration_admission']['identity']:
        raise ValueError('Stored center template identity differs from the admitted acquisition field/electronics')
    point_inputs = study.cfd.scan.Inputs()
    lateral_cells = set(cs.TARGETS) | {(2, 25), (3, 26), (9, 19), (10, 18)}
    points = study.load_templates(point_inputs, lateral_cells, manifest['identity'], manifest['channels'],
                                  set(), lateral_captures=((cs.CAPTURE, cs.CAPTURE_SHA),))
    lateral_cells = {cell for cell, template in points.items() if template.lateral_correction_v_per_keV is not None}
    for cell in sorted(lateral_cells):
        if not np.array_equal(templates[cell].center_v_per_keV, points[cell].center_v_per_keV):
            raise ValueError(f'Archived lateral correction and portable center disagree at {cell}')
        templates[cell] = replace(templates[cell], lateral_correction_v_per_keV=points[cell].lateral_correction_v_per_keV)

    fit_rows = baseline['fit_receipt']['candidates']
    trigger_ids = baseline['candidate_analysis']['selected_original_trigger_ids']
    if (len(fit_rows) != len(trigger_ids) or len(set(trigger_ids)) != len(trigger_ids)
            or len(fit_rows) != baseline['candidate_analysis']['two_strip_candidates']):
        raise ValueError('Original baseline two-strip roster differs')
    return paths, stamps, report, manifest, templates, point_inputs.hashes, lateral_cells, fit_rows, trigger_ids


def retained_candidates():
    paths, stamps, report, manifest, templates, point_hashes, lateral_cells, fit_rows, trigger_ids = retained_candidate_inputs()
    database = paths['candidate_store']
    all_rms, nonfit_rms = defaultdict(list), defaultdict(list)
    all_fast_residual = defaultdict(list)
    statuses, invalid_cfd, boundaries, lateral_coverage = Counter(), Counter(), Counter(), Counter()
    fitted_pairs = 0
    refits = []
    baseline_contact_residuals = []
    for ordinal, (trigger_id, row) in enumerate(zip(trigger_ids, fit_rows, strict=True), 1):
        if row['ordinal'] != ordinal:
            raise ValueError('Retained baseline ordinals changed')
        for stored in row['pairings']:
            statuses[stored['fit']['status']] += 1
        eligible = [p for p in row['pairings'] if p['fit']['status'] == 'fitted']
        if not eligible:
            continue
        saved = storage.load_candidate(database, trigger_id)
        volts, status = imaging.voltage_window(saved, report['excluded_intervals_ns'])
        if status != 'captured' or row['window_status'] != status or row['time_ns'] != saved['trigger_time_ns']:
            raise ValueError(f'Retained trigger {trigger_id} no longer matches its baseline window')
        event = saved['card']['two_strip_pairings']
        for stored in eligible:
            ordinal_fit = fitted_pairs
            fitted_pairs += 1
            pairing = next(p for p in event['pairings'] if p['index'] == stored['index'])
            cells = [(site['x_contact_id'], site['y_contact_id']) for site in pairing['sites']]
            if [list(cell) for cell in cells] != stored['cells'] or not pairing['energy_compatible']:
                raise ValueError('Retained measured pairings changed')
            local_fit = stored['fit']['fits']['waveform']['center']
            contacts = stored['fit']['contacts']
            residual = joint.evaluate_waveform_compatibility(pairing, event['collectors'], templates, local_fit,
                                                             contacts, local_adc_volts=volts)
            if (any(not r['modeled_crossing_valid'] for r in residual['collector_timing']) ==
                    local_fit['modeled_cfd_available']):
                raise ValueError('Retained model crossing validity changed')
            modeled_rms = n_rms([residual['adc_rms_codes'][cid-1] for cid in contacts])
            archived_rms = local_fit['weighted_residual_rms'] * joint.NOISE_RMS_V / joint.digital._LSB_V
            if not math.isclose(modeled_rms, archived_rms, rel_tol=1e-10, abs_tol=1e-10):
                raise ValueError(f'Archive local fit residual {archived_rms:.9g} changed to {modeled_rms:.9g}')
            for idx, cid in enumerate(residual['contact_ids']):
                all_rms[cid].append(residual['adc_rms_codes'][idx])
                all_fast_residual[cid].append(abs(residual['measured_window_fast_keV_equiv'][idx] -
                                                  residual['modeled_window_fast_keV_equiv'][idx]))
                if cid not in contacts:
                    nonfit_rms[cid].append(residual['adc_rms_codes'][idx])
            invalid_cfd.update(r['contact_id'] for r in residual['collector_timing'] if not r['modeled_crossing_valid'])
            boundaries.update(f'{k}_{v}' for k, v in residual['parameter_boundaries'].items() if v is not None)
            supported_count = sum(cell in lateral_cells for cell in cells)
            lateral_coverage[supported_count] += 1
            baseline_contact_residuals.append([trigger_id, pairing['index'], residual['adc_rms_codes']])
            if ordinal_fit % REFIT_STRIDE and supported_count != 2:
                continue
            result = joint.fit_pairing(pairing, event['collectors'], templates, manifest['feature_scales'],
                                       local_adc_volts=volts, compatibility=True, include_all_channels=True)
            if result['status'] != 'fitted':
                raise ValueError('Re-fit of a retained fit lost the original support')
            refits.append({'original_trigger_id': trigger_id, 'pairing_index': pairing['index'],
                           'cells': pairing['sites'], 'lateral_coverage': supported_count,
                           'systematic_sample': ordinal_fit % REFIT_STRIDE == 0,
                           'fits': {mode: supports for mode, supports in result['fits'].items() if mode != 'features'}})
    if len(baseline_contact_residuals) != statuses['fitted']:
        raise ValueError('Saved fitted pairing count changed during compatibility replay')
    if any(workflow.sha(path) != stamps[key] for key, path in paths.items()):
        raise ValueError('An immutable acquisition or calibration input changed during evaluation')
    return {
        'input_sha256': stamps, 'lateral_input_sha256': point_hashes,
        'retained_two_strip_triggers': len(trigger_ids), 'saved_pairing_statuses': statuses,
        'baseline_waveform_center': {
            'scored_pairings': fitted_pairs,
            'invalid_modeled_crossings_by_contact': invalid_cfd,
            'boundaries_by_parameter_and_side': boundaries,
            'contact_summary': [
                {'contact_id': cid, 'adc_rms_codes': distribution(all_rms[cid]), 'nonfit_adc_rms_codes': distribution(nonfit_rms[cid]),
                 'absolute_fast_residual_keV_equiv': distribution(all_fast_residual[cid])}
                for cid in joint.digital.CONTACT_IDS],
            'residual_columns': ['original_trigger_id', 'pairing_index', 'adc_rms_codes_in_contact_id_order'],
            'residual_rows': baseline_contact_residuals},
        'lateral_grid_cells': sorted(lateral_cells), 'fitted_pairings_by_lateral_supported_site_count': lateral_coverage,
        'refit_scope': f'Every {REFIT_STRIDE}th original fitted pairing from index zero, plus every pairing with two supported lateral grids.',
        'refit_pairings': len(refits), 'refits': refits,
    }


def run():
    start = perf_counter()
    controls = {}
    for (path, stamp), label, replay in zip(CONTROL_BASELINES, ('general', 'targeted_cs'),
                                         (study.run, cs.run), strict=True):
        original = study.cfd.scan.Inputs().read(path, stamp)
        controls[label] = controlled_summary(replay(compatibility=True), original, stamp)
    candidates = retained_candidates()
    return {'kind': 'gegi_position_compatibility_v1',
            'method': 'Measured slow energies, summed fixed-field point responses, shared onset; residuals measured minus modeled after independent quiet-tail subtraction.',
            'adc_lsb_V': joint.digital._LSB_V, 'optional_noise_rms_V': joint.NOISE_RMS_V,
            'samples_relative_to_trigger_ns': joint.SAMPLE_NS.tolist(), 'contact_ids': list(joint.digital.CONTACT_IDS),
            'boundary_tolerance_in_parameter_units': joint.BOUNDARY_TOLERANCE,
            'near_tie_weighted_rms_increment': joint.NEAR_TIE_RMS_INCREMENT,
            'controls': controls, 'candidates': candidates,
            'scope': 'Original ADC only. Residuals, boundaries and deterministic multistart near-ties are diagnostics without acceptance cuts, probabilities or physical coverage guarantees.',
            'elapsed_seconds': perf_counter() - start,
            'source_sha256': {Path(m.__file__).name: workflow.sha(Path(m.__file__))
                              for m in (joint, imaging, storage, calibration, study, cs)}
                             | {Path(__file__).name: workflow.sha(Path(__file__))}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    args = parser.parse_args()
    if args.output.exists() or not args.output.resolve().is_relative_to(OUTPUT.parent):
        parser.error('Choose a new output in the reconstruction evidence directory')
    result = run()
    args.output.parent.mkdir(exist_ok=True)
    with args.output.open('xb') as stream:
        stream.write(encoded(result) + b'\n')
    print(json.dumps({'retained_baseline_pairs': result['candidates']['baseline_waveform_center']['scored_pairings'],
                      'refit_pairs': result['candidates']['refit_pairings'],
                      'elapsed_seconds': result['elapsed_seconds']}, indent=2))


if __name__ == '__main__':
    main()
