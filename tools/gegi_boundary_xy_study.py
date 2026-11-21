"""Compare frozen linear and PCHIP lateral responses on saved GeGI boundary ADC."""

import argparse
from collections import Counter
import hashlib
from itertools import product
import json
import math
from pathlib import Path

import numpy as np
import scipy
from scipy.interpolate import PchipInterpolator

import gegi_boundary_overlap_validation as overlap


D = overlap.depth
G = D.grid
J = D.J
W = G.workflow
XY = np.array(J.LATERAL_FRACTION)
FROZEN_OVERLAP = 'c3567a4cc684053df73f16b2e79f11fe555f34482d9fa408f7ecda77e649d740'
FROZEN_ISOLATED = '1827f655b95bc3442e72a410fd075f02456879d8f1927a32a099d30c04f49ab5'


def pchip_xy(values, x, y):
    x_first = PchipInterpolator(XY, values, axis=0, extrapolate=False)(x)
    y_first = PchipInterpolator(XY, values, axis=1, extrapolate=False)(y)
    return (PchipInterpolator(XY, x_first, axis=0, extrapolate=False)(y)
            + PchipInterpolator(XY, y_first, axis=0, extrapolate=False)(x))/2


def predictor(template, depths):
    """Use the frozen isolated-control kernel within one terminal-verified cell."""
    center, = G.boundary.centers_for({template.cell: template}, [template.cell])
    corrections = template.lateral_correction_v_per_keV
    depth_axis = np.array(depths)

    def sample(point, times, energy):
        x, y, z = point
        if not (XY[0] <= x <= XY[-1] and XY[0] <= y <= XY[-1]
                and depth_axis[0] <= z <= depth_axis[-1]):
            raise ValueError('Shape-preserving interpolation stays inside the calibrated cell')
        head = np.maximum(np.floor(times).astype(int), 0)
        tail = np.maximum(times, 0.)-head
        indices = np.r_[head, head+1]
        left = min(int(np.searchsorted(depth_axis, z, side='right'))-1, len(depth_axis)-2)
        frac = (z-depth_axis[left])/(depth_axis[left+1]-depth_axis[left])
        lower = pchip_xy(np.take(corrections[:, :, left], indices, axis=-1), x, y)
        upper = pchip_xy(np.take(corrections[:, :, left+1], indices, axis=-1), x, y)
        analog = center([z])[0][:, indices] + (1.-frac)*lower+frac*upper
        n = len(times)
        return energy*(analog[:, :n]*(1.-tail)+analog[:, n:]*tail)*(times >= 0.)

    return sample


def fit_points(volts, templates, samples, cells, energies, center_seed):
    """Repeat the eleven-depth fit with only the lateral interpolator changed."""
    J._check_adc(volts)
    depths, onset = center_seed
    limits = [(XY[0], XY[-1]), (XY[0], XY[-1]), (J.DEPTH_MM[0], J.DEPTH_MM[-1])]*len(cells)
    limits.append(J.SHIFT_LIMIT_NS)
    scale = np.array([.4, .4, 5.]*len(cells)+[20.])
    observed = J.remove_quiet_tail(volts)

    def predict(point):
        times = J.SAMPLE_NS-point[-1]
        sites = point[:-1].reshape(-1, 3)
        return sum(samples[c](xyz, times, e) for c, xyz, e in zip(cells, sites, energies, strict=True))

    def residual(point):
        return ((J.remove_quiet_tail(predict(point))-observed)/J.NOISE_RMS_V).ravel()

    slots = [[(x, y, z) for x, y in G.START_OFFSETS] for z in depths]
    starts = [np.array([q for xyz in sites for q in xyz]+[onset]) for sites in product(*slots)]
    selected = sorted(starts, key=lambda p: np.linalg.norm(residual(p)))[:3]
    best, near, diagnostic = J._best_refinement(residual, selected, tuple(zip(*limits)), scale)

    def positions(point):
        return [[templates[c].origin_mm[0]+x*templates[c].pitch_mm,
                 templates[c].origin_mm[1]+y*templates[c].pitch_mm, z]
                for c, (x, y, z) in zip(cells, point[:-1].reshape(-1, 3), strict=True)]

    return {'status': 'scored' if best.success else 'optimizer_unconverged',
            'positions_mm': positions(best.x), 'onset_relative_to_trigger_ns': float(best.x[-1]),
            'parameters_at_bounds': [i for i, (x, (a, b)) in enumerate(zip(best.x, limits, strict=True))
                                     if min(x-a, b-x) <= J.BOUNDARY_TOLERANCE],
            'sampled_near_ties_mm': [positions(p.x) for p in near if p is not best],
            'optimizer': diagnostic, **G.boundary.rms(volts, predict(best.x))}


def geometry_diagnostics(fit, cells, templates):
    positions = fit['positions_mm']
    ties = fit['sampled_near_ties_mm']
    bounds = []
    for i in fit['parameters_at_bounds']:
        if i == 3*len(cells):
            cell, axis = None, 'onset'
            value = fit['onset_relative_to_trigger_ns']
            limits = J.SHIFT_LIMIT_NS
        else:
            site, component = divmod(i, 3)
            cell = cells[site]
            axis = 'xyz'[component]
            value = positions[site][component]
            limits = (J.DEPTH_MM[0], J.DEPTH_MM[-1])
            if component < 2:
                template = templates[cell]
                value = (value-template.origin_mm[component])/template.pitch_mm
                limits = (XY[0], XY[-1])
        bounds.append({'cell': cell, 'parameter': axis,
                       'side': 'lower' if value-limits[0] < limits[1]-value else 'upper'})
    return fit | {'outer_bound_directions': bounds,
                  'maximum_sampled_near_tie_displacement_mm': [
                      max((math.dist(pos, tie[i]) for tie in ties), default=0.)
                      for i, pos in enumerate(positions)],
                  'maximum_sampled_near_tie_displacement_xyz_mm': [
                      [max((abs(pos[a]-tie[i][a]) for tie in ties), default=0.) for a in range(3)]
                      for i, pos in enumerate(positions)]}


def observed_strip_evidence(card):
    return {'collecting_contacts': card['x_collecting_strips']+card['y_collecting_strips'],
            'measured_xy_face_sums_keV': [card['x_sum_keV'], card['y_sum_keV']]}


def compare_control(row, items, request, coarse, templates, samples):
    result = dict(row, shape_preserving_xy=None)
    baseline = row['refined_eleven_depth']
    if row['readout_status'] != 'evaluated' or baseline is None:
        return result
    card, volts = D.control_adc(row, items, row['phase_ns'], request)
    cells = tuple(map(tuple, row['measured_cells']))
    energies = row['measured_energies_keV']
    _, flows, _, _, _, _ = G.topology.matching_marginals(card['two_strip_pairings']['collectors'])
    measured, = [{(x, y): e for x, y, e in flow} for flow in flows if {(x, y) for x, y, _ in flow} == set(cells)]
    if [measured[cell] for cell in cells] != energies:
        raise ValueError('The original readout-derived component energies changed')
    center = G.fit_points(volts, coarse, cells, energies, use_lateral=False)
    fit = fit_points(volts, templates, samples, cells, energies, D.cause.fit_start(center))
    # The independent deposited positions are used only after fitting the ADC.
    scored = overlap.fit_evidence(fit, cells, items)
    return result | {'observed_strips': observed_strip_evidence(card),
                     'center_start': D.cause.fit_start(center),
                     'refined_eleven_depth': geometry_diagnostics(baseline, cells, templates),
                     'shape_preserving_xy': geometry_diagnostics(scored, cells, templates)}


def compare_original(report, request, templates, samples, acquisition, archive):
    hashes = report['input_sha256']
    exposure = G.bound(acquisition, hashes['acquisition'])
    if W.sha(archive) != hashes['candidate_store']:
        raise ValueError('The original measured candidate store changed')
    scope = report['measured_scope']
    record = G.storage.load_candidate(archive, scope['trigger_id'])
    context = record['context']
    volts, status = G.imaging.voltage_window(record, exposure['excluded_intervals_ns'])
    adc = hashlib.sha256(context['adc_codes'].tobytes()).hexdigest()
    if (status != 'captured' or adc != hashes['original_adc']
            or list(context['contact_ids']) != [c['id'] for c in request['channels']]):
        raise ValueError('The original measured ADC samples or contact ordering changed')
    saved = report['original_adc']
    center = saved['coarse']['center']['saved_fit']
    seed = ([p[2] for p in center['site_positions_mm']], center['onset_relative_to_trigger_ns'])
    cells = tuple(map(tuple, scope['cells']))
    energies = center['site_energies_keV']
    fit = fit_points(volts, templates, samples, cells, energies, seed)
    return {'trigger_id': scope['trigger_id'], 'adc_sha256': adc, 'status': status,
            'measured_cells': cells, 'measured_energies_keV': energies,
            'observed_strips': observed_strip_evidence(record['card']), 'center_start': seed,
            'original_alternatives': saved['coarse']['original_alternatives'],
            'coarse_three_depth': saved['coarse']['within_cell_fit'],
            'refined_eleven_depth': geometry_diagnostics(saved['refined_lateral_fit'], cells, templates),
            'shape_preserving_xy': geometry_diagnostics(fit, cells, templates),
            'original_projected_mass': scope['original_projected_mass'],
            'original_unresolved_mass': scope['original_unresolved_mass'],
            'position_error_mm': None}


def paired_summary(rows, design):
    methods = ('refined_eleven_depth', 'shape_preserving_xy')
    matched = [row for row in rows if all(row[m] and row[m]['position_errors_mm'] is not None for m in methods)]
    weak_slot = [min(range(len(f)), key=f.__getitem__) for f in design['fractions_in_measured_cell_order']]
    outputs = {'matched_position_conditions': len(matched)}
    for method in methods:
        fits = [row[method] for row in matched]
        weak = [weak_slot[row['allocation_index']] for row in matched]
        outputs[method] = {
            'all34_adc_rms_codes': overlap.rms([fit['all34_adc_rms_codes'] for fit in fits]),
            'all_component_position_rms_mm': overlap.rms([x for fit in fits for x in fit['position_errors_mm']]),
            'weak_component_position_rms_mm': overlap.rms([fit['position_errors_mm'][i] for fit, i in zip(fits, weak, strict=True)]),
            'max_weak_near_tie_displacement_mm': max((fit['maximum_sampled_near_tie_displacement_mm'][i]
                                                     for fit, i in zip(fits, weak, strict=True)), default=None),
            'conditions_at_outer_bounds': sum(bool(fit['outer_bound_directions']) for fit in fits)}
    return outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('depth-comparison', 'depth-request', 'depth-capture', 'prior-comparison', 'prior-request',
                 'prior-capture', 'center-calibration', 'isolated-comparison', 'overlap-comparison',
                 'acquisition', 'candidate-store', 'output'):
        parser.add_argument(f'--{flag}', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Choose a new output path')
    report, request, layouts, coarse, templates, axes = overlap.frozen_inputs(
        args.depth_comparison, args.depth_request, args.depth_capture, args.prior_comparison,
        args.prior_request, args.prior_capture, args.center_calibration)
    isolated = G.bound(args.isolated_comparison, FROZEN_ISOLATED)
    baseline = G.bound(args.overlap_comparison, FROZEN_OVERLAP)
    if (any(tuple(depths) != D.DENSE_DEPTHS for depths in axes.values())
            or baseline['input_sha256']['frozen_depth_comparison'] != overlap.EXPECTED_DEPTH_RECEIPT
            or isolated['input_sha256']['frozen_eleven_depth_comparison'] != overlap.EXPECTED_DEPTH_RECEIPT
            or not isolated['measured_scope'] == baseline['measured_scope'] == report['measured_scope']):
        raise ValueError('The previously scored samples, same-terminal templates, or original allocation changed')
    samples = {cell: predictor(template, axes[cell]) for cell, template in templates.items()}
    original = compare_original(report, request, templates, samples, args.acquisition, args.candidate_store)
    rows = [compare_control(row, layouts[row['layout_index']], request, coarse, templates, samples)
            for row in baseline['conditions']]
    methods = ('coarse_three_depth', 'refined_eleven_depth', 'shape_preserving_xy')
    counts = {m: dict(Counter(r[m]['status'] if r[m] is not None else 'unavailable' for r in rows)) for m in methods}
    outcome = {'kind': 'gegi_frozen_xy_overlap_and_original_adc_v1', 'capture_count': 0,
               'input_sha256': report['input_sha256'] | {'frozen_depth_comparison': overlap.EXPECTED_DEPTH_RECEIPT,
                                                        'isolated_xy_comparison': FROZEN_ISOLATED, 'overlap_comparison': FROZEN_OVERLAP},
               'software': {'scipy': scipy.__version__, 'numpy': np.__version__},
               'source_sha256': {Path(f).name: W.sha(f) for f in (__file__, overlap.__file__, D.__file__, G.__file__, J.__file__)},
               'frozen_isolated_xy_producer_sha256': isolated['source_sha256']['xy_interpolation_validation.py'],
               'interpolation_references': isolated['interpolation_references'],
               'measured_scope': report['measured_scope'], 'design': baseline['design'],
               'source_position_mm': None, 'source_activity_Bq': None, 'original_adc': original,
               'fit_status_by_method': counts, 'summary_on_matched_position_conditions': paired_summary(rows, baseline['design']),
               'conditions': rows,
               'interpretation': 'Same measured component energies, ADC windows, three-start lateral fit budget, bounds, '
                                 'and quiet-tail subtraction. The predeclared average of both within-cell PCHIP axis orders '
                                 'changes only X/Y waveform interpolation. Eleven-level depth and sample time stay linear. '
                                 'Coordinate errors describe independent charge positions of two fixed layouts and 24 readout conditions. '
                                 'The original ADC has no coordinate truth in this evaluation. The two allocations lacking '
                                 'full cell support retain their original results; original imaging weights are unchanged.'}
    with args.output.open('xb') as stream:
        stream.write(W.encoded(outcome)+b'\n')
    print(json.dumps({'sha256': W.sha(args.output), 'conditions': len(rows), 'counts': counts}))


if __name__ == '__main__':
    main()
