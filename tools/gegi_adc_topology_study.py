"""Compare sparse and continuous strip-energy allocations on matched GeGI ADC windows."""

import argparse
from collections import Counter
from itertools import product
import json
import math
from pathlib import Path
from time import perf_counter

import numpy as np

import gegi_cs_joint_lateral_holdout as cs
from gegi_event_store import encoded
import gegi_imaging as imaging
import gegi_joint_calibration as calibration
import gegi_joint_two_site as joint
import gegi_position_compatibility as evidence
import gegi_position_uncertainty_study as controls
import gegi_signal_reconstruction as signal


OUTPUT = controls.OUTPUT.with_name('adc-topology-controls.json')


def matching_marginals(collectors):
    """Project measured X / Y strip energies to equal face totals with existing tolerance weights."""
    xs = sorted((q['contact_id'], q['slow_energy_keV']) for q in collectors if q['contact_id'] <= 16)
    ys = sorted((q['contact_id'], q['slow_energy_keV']) for q in collectors if 18 <= q['contact_id'] <= 33)
    if len(xs) != 2 or len(ys) != 2:
        raise ValueError('ADC topology comparison needs original two-strip-per-face energy measurements')
    rows = [[dict(contact_id=cid, reconstructed_energy_keV=e) for cid, e in face] for face in (xs, ys)]
    flows, ledger = signal.energy_flows(*rows)
    measured = np.array([energy for _, energy in (*xs, *ys)])
    tolerances = np.maximum(imaging.PAIR_ABS_KEV, imaging.PAIR_REL * measured)
    contrast = np.array([1., 1., -1., -1.])
    weights = tolerances**2
    marginals = measured - weights * contrast * (contrast @ measured) / sum(weights)
    if (ledger.get('reason') == 'face_energy_mismatch' or not np.isfinite(marginals).all()
            or np.any(marginals < 0.) or np.any(np.abs(marginals-measured) > tolerances + 1e-9)):
        marginals = None
    cells = tuple(product((x for x, _ in xs), (y for y, _ in ys)))
    return cells, flows, ledger, measured, tolerances, marginals


def energy_family(marginals):
    """A reconciled nonnegative 2×2 allocation has a single free corner energy."""
    a, b, c, _ = marginals
    bounds = (max(0., c - b), min(a, c))

    def allocate(value):
        return np.maximum(np.array([value, a - value, c - value, b - c + value]), 0.)

    return bounds, allocate


def fit_flow(cells, templates, volts, *, energies=None, family=None):
    if any(cell not in templates for cell in cells):
        return {'status': 'missing_center_template', 'cells': cells}
    n = len(cells)
    templates = [templates[cell] for cell in cells]
    centers = joint._interpolators(templates, slice(None), (False,) * n)
    observed = joint.remove_quiet_tail(volts)
    depth_lo, depth_hi = float(joint.DEPTH_MM[0]), float(joint.DEPTH_MM[-1])
    bounds = ([depth_lo] * n + [joint.SHIFT_LIMIT_NS[0]], [depth_hi] * n + [joint.SHIFT_LIMIT_NS[1]])
    scales = [5.] * n + [20.]
    frac = [()]
    if family is not None:
        (low, high), allocate = family
        if not high > low:
            return {'status': 'continuum_had_no_free_width', 'cells': cells}
        width = high-low
        bounds[0].append(low)
        bounds[1].append(high)
        scales.append(width)
        frac = [(low + width*f,) for f in (.05, .5, .95)]

    def energy_values(point):
        return allocate(point[-1]) if family is not None else energies

    def residual(point):
        interpolated = sum(energy * center([z])[0] for z, energy, (center, _) in
                           zip(point[:n], energy_values(point), centers, strict=True))
        samples = joint.shifted_samples(interpolated, point[n])
        return ((joint.remove_quiet_tail(samples) - observed) / joint.NOISE_RMS_V).ravel()

    grid = ((*z, onset, *t) for z, onset, t in product(product((-4., 0., 4.), repeat=n), (-15., 5.), frac))
    starts = sorted((np.array(v) for v in grid), key=lambda v: np.linalg.norm(residual(v)))[:3]
    best, near, diagnostics = joint._best_refinement(residual, starts, bounds, np.array(scales))

    def record(row):
        e = energy_values(row.x)
        return {'energies_keV': list(e), 'depths_mm': row.x[:n].tolist(),
                'onset_relative_to_trigger_ns': float(row.x[n]),
                'weighted_residual_rms': math.sqrt(2 * row.cost / len(row.fun)),
                'at_energy_bound': bool(family is not None and min(row.x[-1]-low, high-row.x[-1]) <= 1e-4),
                'depth_boundary_sites': [i for i, depth in enumerate(row.x[:n])
                                         if min(depth-depth_lo, depth_hi-depth) <= joint.BOUNDARY_TOLERANCE]}

    top = record(best)
    rms = np.sqrt(np.mean(best.fun.reshape(volts.shape)**2, axis=1)) * joint.NOISE_RMS_V / joint.digital._LSB_V
    return {'status': 'scored', 'cells': cells, 'global_adc_rms_codes': float(np.sqrt(np.mean(rms**2))),
            'per_contact_adc_rms_codes': rms.tolist(), 'fit': top, 'optimizer': diagnostics,
            'other_sampled_near_ties': [record(row) for row in near if row is not best]}


def trial_allocations(card, volts, templates):
    cells, flows, ledger, measured, tolerances, matched = matching_marginals(card['collectors'])
    result = {'observed_collectors_keV': measured.tolist(), 'strip_tolerances_keV': tolerances.tolist(),
              'sparse_flow_bookkeeping': ledger, 'fits': []}
    for flow in flows:
        selected, energies = zip(*[((x, y), e) for x, y, e in flow], strict=True)
        result['fits'].append(dict(fit_flow(selected, templates, volts, energies=energies), kind=f'{len(flow)}_corner_sparse'))
    if matched is not None:
        bounds, allocate = energy_family(matched)
        result.update(matched_marginal_energies_keV=matched.tolist(), free_energy_bounds_keV=bounds)
        for side, t in zip(('lower', 'upper'), bounds, strict=True):
            endpoint = [(cell, float(e)) for cell, e in zip(cells, allocate(t), strict=True) if e > 1e-9]
            if len(endpoint) == 3 and any(e < imaging.MIN_COLLECTED_KEV for _, e in endpoint):
                selected, energies = zip(*endpoint, strict=True)
                result['fits'].append(dict(fit_flow(selected, templates, volts, energies=energies),
                                           kind=f'3_corner_weak_endpoint_{side}'))
        result['fits'].append(dict(fit_flow(cells, templates, volts, family=(bounds, allocate)), kind='4_corner_continuum'))
    return result


def replay_conditions(inputs, assumed, field):
    """Recreate the verified digital controls from archived native signals without refitting their baselines."""
    original = inputs.read(controls.study.STUDY, controls.study.STUDY_SHA)
    curves = inputs.read(controls.study.cfd.CURVES, controls.study.cfd.CURVES_SHA)
    channels, traces = controls.study.cfd.load_sources(inputs, curves)
    channels_cs, _, cs_cases = cs.holdouts(inputs, field)
    positive_positions = {tuple(s['xyz_mm']) for row in assumed if row['cohort'] != 'negative_mixture'
                          for s in row['reference_sites']}
    refs = {ref for _, support, _ in controls.NEGATIVE_GEOMETRIES for ref in support}
    channels_negative, negative_traces, _ = controls.load_archived_traces(inputs, field, refs, positive_positions)
    if channels != channels_cs or channels != channels_negative:
        raise ValueError('Control cohorts differ in their detector contacts')
    negative_refs = {name: refs for name, refs, _ in controls.NEGATIVE_GEOMETRIES}
    for row in assumed:
        k = row['trial']
        if row['cohort'] == 'general':
            archived = original['trials'][k]
            pulse_refs = controls.study.cfd.CASES[archived['case_index']][1]
            pulses = [traces[ref]['waveform'] for ref in pulse_refs]
            phase, seed = archived['adc_phase_ns'], archived['noise_seed']
        elif row['cohort'] == 'targeted_cs':
            pulses = [wave for _, wave in cs_cases[k]]
            phase, seed = cs.ADC_PHASE_NS, cs.NOISE_SEED + k
        else:
            pulses = [negative_traces[ref]['native'] for ref in negative_refs[row['geometry']]]
            phase, seed = row['adc_phase_ns'], row['noise_seed']
        comps = [(wave, controls.study.cfd.ONSET_NS, site['energy_keV']/controls.study.cfd.depth.ENERGY_KEV)
                 for wave, site in zip(pulses, row['reference_sites'], strict=True)]
        digest, _, status, card, volts = controls.measure_adc(comps, channels, phase, seed)
        if (digest, status) != (row['adc_sha256'], row['trigger_status']):
            raise ValueError('A topology case does not share the archived original ADC and strip readout')
        yield row, card, volts


def support_scores(row, candidate):
    if candidate['status'] != 'scored':
        return {}
    actual = {tuple(q['contact_ids']) for q in row['reference_sites']}
    hypothesized = {tuple(cell) for cell, e in zip(candidate['cells'], candidate['fit']['energies_keV'], strict=True)
                    if e >= imaging.MIN_COLLECTED_KEV}
    weak = {tuple(cell) for cell, e in zip(candidate['cells'], candidate['fit']['energies_keV'], strict=True)
            if 1e-9 < e < imaging.MIN_COLLECTED_KEV}
    actual_by_cell = {}
    for site in row['reference_sites']:
        cell = tuple(site['contact_ids'])
        actual_by_cell[cell] = actual_by_cell.get(cell, 0.) + site['energy_keV']
    return {'recovered_collecting_cells_ge_5_keV': sorted(hypothesized),
            'weak_corners_below_5_keV': sorted(weak),
            'true_collecting_cells_above_threshold': sorted(cell for cell, e in actual_by_cell.items()
                                                           if e >= imaging.MIN_COLLECTED_KEV),
            'all_true_cells_recovered_if_weak_corners_count': actual <= hypothesized | weak,
            'exact_ge_5_keV_cell_match': actual == hypothesized,
            'missed_true_collecting_cells': sorted(actual - hypothesized - weak),
            'above_threshold_cell_count_equals_injected_point_count': len(hypothesized) == len(row['reference_sites']),
            'cell_energy_errors_keV': [e - actual_by_cell.get(tuple(cell), 0.)
                                       for cell, e in zip(candidate['cells'], candidate['fit']['energies_keV'], strict=True)]}


def summary(rows):
    groups = {}
    for label in sorted({row['geometry'] for row in rows}):
        selected = [r for r in rows if r['geometry'] == label]
        delta = []
        four_scores = []
        for row in selected:
            alternatives = [f for f in row['allocations']['fits'] if f['status'] == 'scored']
            best_two = min((p['all_adc_rms_codes'] for p in row['original_center_waveform_alternatives']), default=None)
            best_more = min((f['global_adc_rms_codes'] for f in alternatives if not f['kind'].startswith('2_')), default=None)
            if best_two is not None and best_more is not None:
                delta.append(best_two-best_more)
            four_scores.extend(f for f in alternatives if f['kind'] == '4_corner_continuum')
        groups[label] = {
            'conditions': len(selected), 'status_counts': Counter(r['status'] for r in selected),
            'conditions_with_two_vs_more_comparison': len(delta),
            'adc_rms_improvement_with_more_corners_codes': evidence.distribution(delta),
            'improvement_by_trial_codes': delta,
            'four_corner_scored_conditions': len(four_scores),
            'four_corner_optimizer_at_energy_boundary': sum(r['fit']['at_energy_bound'] for r in four_scores),
            'four_corner_exact_ge5kev_cell_matches': sum(r['truth_score']['exact_ge_5_keV_cell_match'] for r in four_scores),
        }
    return groups


def run():
    begun = perf_counter()
    inputs = controls.study.cfd.scan.Inputs()
    prior = inputs.read(controls.OUTPUT, controls.OUTPUT_SHA256)
    manifest, bank, _, archive_sha = calibration.load(evidence.CENTERS)
    identity = inputs.read(controls.study.cfd.CURVES, controls.study.cfd.CURVES_SHA)['provenance']
    if manifest['identity'] != {k: identity[k] for k in calibration.IDENTITY_KEYS}:
        raise ValueError('ADC topology template fields or electronics differ from control identity')
    rows = []
    tie_width = joint.NEAR_TIE_RMS_INCREMENT * joint.NOISE_RMS_V / joint.digital._LSB_V
    for before, card, volts in replay_conditions(inputs, prior['trials'], identity):
        baseline = [dict(model['hypotheses']['waveform_all_center'], pairing_index=model['pairing_index'], cells=model['cells'])
                    for model in before['pairings'] if 'waveform_all_center' in model['hypotheses']]
        result = trial_allocations(card, volts, bank) if card is not None else {'fits': []}
        for fit in result['fits']:
            fit['truth_score'] = support_scores(before, fit)
        comparison = [(f'two_site_pairing_{p["pairing_index"]}', p['all_adc_rms_codes']) for p in baseline]
        comparison += [(p['kind'], p['global_adc_rms_codes']) for p in result['fits'] if p['status'] == 'scored']
        lowest = min((score for _, score in comparison), default=None)
        near_tie = [name for name, score in comparison if score - lowest <= tie_width]
        rows.append({'trial': before['trial'], 'geometry': before['geometry'], 'cohort': before['cohort'],
                     'adc_sha256': before['adc_sha256'], 'status': before['trigger_status'],
                     'reference_sites': before['reference_sites'],
                     'original_center_waveform_alternatives': baseline, 'allocations': result,
                     'sampled_cross_model_near_ties': near_tie})
    return {'kind': 'gegi_adc_topology_comparison_v1', 'position_grid': joint.DEPTH_MM.tolist(),
            'contacts': list(joint.digital.CONTACT_IDS), 'noise_scale_V': joint.NOISE_RMS_V,
            'units': 'Energies in keV, detector coordinates in mm, original ADC time in ns.',
            'scope': 'Independent same-ADC center-template comparisons. Sparse fits use existing energy flow and strip tolerances. '
                     'Four-corner flows conserve a tolerance-weighted reconciliation of the two measured face totals. Common onset, '
                     'per-corner depth, and one free energy allocation for the four-corner family.',
            'ambiguity_policy': 'All sampled compatible hypotheses remain. Additional corners can absorb center-template errors. '
                                'Residual proximity has no calibrated topology probability. Different deposits within one cell '
                                'cannot be identified as distinct positions by this template family.',
            'near_tie_rms_increment_adc_codes': tie_width,
            'summary': summary(rows), 'rows': rows, 'input_sha256': inputs.hashes | {'center_template_archive': archive_sha},
            'elapsed_seconds': perf_counter()-begun,
            'source_sha256': {Path(m.__file__).name: evidence.workflow.sha(Path(m.__file__))
                              for m in (controls, cs, calibration, joint, signal)}
                             | {Path(__file__).name: evidence.workflow.sha(Path(__file__))}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    args = parser.parse_args()
    if args.output.exists() or not args.output.resolve().is_relative_to(OUTPUT.parent):
        parser.error('Choose a new output in the reconstruction evidence directory')
    report = run()
    args.output.parent.mkdir(exist_ok=True)
    with args.output.open('xb') as stream:
        stream.write(encoded(report) + b'\n')
    print(json.dumps({'conditions': len(report['rows']), 'elapsed_seconds': report['elapsed_seconds']}, indent=2))


if __name__ == '__main__':
    main()
