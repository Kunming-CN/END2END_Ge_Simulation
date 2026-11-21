"""Evaluate conditional photon response at declared trial positions using original GeGI fits."""

import argparse
from collections import Counter
import math
from pathlib import Path
import platform
import time

import numpy as np
import scipy

import gegi_candidate_observed_energy as observed
import gegi_candidate_range as grid
import gegi_photon_continuation as photon
import gegi_photon_observed_energy as energy
import gegi_point_source_response as point
import scenario_workflow as W


PLAN_KIND = 'gegi_candidate_trial_response_plan_v1'


def original_geometry_status(pair, crystal):
    if pair['measured_site_energies_keV'] is None:
        return 'original_strip_pairing_incompatible'
    xyz = pair['fitted_vertices_mm']
    if xyz is None:
        return 'fitted_vertices_unavailable'
    normals, offsets = crystal
    if np.any(np.asarray(xyz) @ normals.T > offsets+1e-9):
        return 'fitted_vertex_outside_crystal'
    if xyz[0] == xyz[1]:
        return 'coincident_fitted_vertices'
    return 'available_geometry'


def trials(radius_min, radius_max, radial_points, directions):
    if not (math.isfinite(radius_min) and math.isfinite(radius_max) and 0 < radius_min < radius_max
            and radial_points >= 2 and directions >= 1):
        raise ValueError('Supply a positive increasing radial range and a full-sphere grid')
    radii = np.geomspace(radius_min, radius_max, radial_points)
    unit_vectors = grid.direction(grid.sphere_grid(directions))
    return radii, unit_vectors, radii[:, None, None]*unit_vectors[None, :, :]


def verified_extension(path, plan_sha, basis, queries):
    receipt = W.read(path/'execution.json')
    table = path/'photon-rates.csv'
    W.require(receipt['returncode'] == receipt['primaries'] == 0 and
              receipt['plan_sha256'] == plan_sha and receipt['binary_sha256'] == basis['exporter_sha256'] and
              receipt['geometry_sha256'] == basis['geometry_sha256'] and
              receipt['rate_macro_sha256'] == basis['rate_macro_sha256'] and W.sha(table) == receipt['rates_sha256'],
              'Initialized photon coefficients use a different plan or producer')
    rates = photon.rates_from_csv(table)
    W.require(set(rates) == set(queries), 'Initialized photon coefficients differ from the requested energies')
    return rates, dict(initialization_sha256=W.sha(path/'execution.json'), rates_sha256=W.sha(table))


def retained_rates(probe, plan_file, measured):
    rates, spacing, basis = observed.base_tables(probe)
    W.require(measured['rate_basis'] == basis, 'Saved measured geometry uses a different coefficient basis')
    extension, receipt = verified_extension(probe/'measured-second-site-rates', W.sha(plan_file), basis,
                                              measured['rate_request']['new_query_energies_keV'])
    W.require(not (rates.keys() & extension.keys()), 'Initialized coefficients must have unique energy anchors')
    return rates | extension, spacing, dict(basis, measured_extension=receipt)


def required_knots(lo, hi, available, max_spacing):
    """Add missing bounds and tighten only logarithmic gaps overlapping trial support."""
    lower = max((e for e in available if e <= lo), default=lo)
    upper = min((e for e in available if e >= hi), default=hi)
    grid = sorted({lower, upper} | {e for e in available if lower < e < upper})
    required = set(grid)-available.keys()
    for start, stop in zip(grid[:-1], grid[1:], strict=True):
        width = math.log(stop/start)
        count = math.ceil(width/max_spacing)
        required.update(math.exp(math.log(start)+width*i/count) for i in range(1, count))
    return sorted(required)


def rate_functions(table):
    """Interpolate positive Ge rates on the same energy grid, keeping every exact anchor."""
    energies = sorted(table)
    log_energies = np.log(energies)
    partials = np.array([(table[e].photoelectric_per_mm, table[e].compton_per_mm) for e in energies])
    if np.any(partials <= 0):
        raise ValueError('The bulk-Ge interpolant requires positive photoelectric and Compton rates')
    log_photo, log_compton = np.log(partials).T
    total = energy.total_rate_interpolator(table)

    def rates_at(e):
        if e in table:
            return table[e]
        total_rate = total(e)
        photo = math.exp(np.interp(math.log(e), log_energies, log_photo))
        compton = math.exp(np.interp(math.log(e), log_energies, log_compton))
        return photon.PhotonRates(total_rate, photo, compton)

    return rates_at, total


def scoped_branches(measured, crystal):
    for trigger in measured['measured_triggers']:
        for pair in trigger['pairs']:
            status = original_geometry_status(pair, crystal)
            for order in pair['orders']:
                for line in order['lines']:
                    yield trigger['original_trigger_id'], pair, order, line, status


def make_plan(measured_path, probe, radius_min, radius_max, radial_points, directions, selected, sigmas):
    started = time.perf_counter()
    measured = W.read(measured_path)
    W.require(measured['kind'] == 'gegi_measured_second_site_response_plan_v1' and measured['measured_only'],
              'Select the saved source-blind measured response plan')
    for sigma in sigmas:
        energy.gaussian_density_per_kev(0., 0., sigma)
    radii, units, points = trials(radius_min, radius_max, radial_points, directions)
    indices = [tuple(pair) for pair in selected]
    W.require(bool(indices) and len(indices) == len(set(indices)) and all(
        0 <= i < len(radii) and 0 <= j < len(units) for i, j in indices), 'Specify distinct in-range trial grid indices')
    rates, spacing, binding = retained_rates(probe, measured_path, measured)
    crystal = photon.ge_halfspaces_from_gdml(probe/'geometry.gdml')
    normals, offsets = crystal
    flat = points.reshape(-1, 3)
    inside = np.all(flat @ normals.T <= offsets+1e-9, axis=1)
    selected_points = [dict(radial_index=i, direction_index=j, source_mm=points[i, j].tolist(),
                            inside_ge=bool(inside[i*len(units)+j])) for i, j in indices]
    lower, upper = min(rates), max(rates)
    bands, eligible, prior, coincidences, below, above = {}, Counter(), Counter(), 0, 0, 0
    for _, pair, order, line, status in scoped_branches(measured, crystal):
        eligible[status] += 1
        prior[line['status']] += 1
        if status != 'available_geometry':
            continue
        r1, r2 = (pair['fitted_vertices_mm'][i] for i in order['site_index_order'])
        e0 = line['incident_line_keV']
        valid = np.any(flat != r1, axis=1)
        e1 = np.array([point.first_compton_state(s, r1, r2, e0)['intermediate_keV'] for s in flat[valid]])
        escape_min = e1/(1+2*e1/photon.ELECTRON_REST_KEV)
        coincidences += int(np.count_nonzero(~valid))
        below += int(np.count_nonzero(escape_min < lower))
        above += int(np.count_nonzero(e1 > upper))
        if not len(e1):
            continue
        item = bands.setdefault(e0, [math.inf, 0., math.inf])
        item[0] = min(item[0], float(e1.min()))
        item[1] = max(item[1], float(e1.max()))
        item[2] = min(item[2], float(escape_min.min()))
    W.require(bool(bands), 'There are no trial states with fitted, distinct vertices')
    lo, hi = min(v[2] for v in bands.values()), max(v[1] for v in bands.values())
    return dict(kind=PLAN_KIND, measured_plan_sha256=W.sha(measured_path), rate_basis=binding,
        sigma_first_keV=sigmas[0], sigma_second_keV=sigmas[1],
        trial_grid=dict(origin_mm=[0., 0., 0.], radii_mm=radii.tolist(), unit_vectors=units.tolist(),
                        points=len(flat), inside_ge_points=int(inside.sum())), selected_trials=selected_points,
        preflight=dict(branch_geometry_status_counts=dict(eligible), prior_fixed_first_status_counts=dict(prior),
                       valid_geometry_states=eligible['available_geometry']*len(flat)-coincidences,
                       coincident_source_states=coincidences, support_below_previous_table_states=below,
                       support_above_previous_table_states=above,
                       energies_by_line=[dict(incident_keV=e, intermediate_bounds_keV=v[:2], minimum_escaping_keV=v[2])
                                         for e, v in sorted(bands.items())]),
        rate_request=dict(support_keV=[lo, hi], prior_interpolation_log_spacing=spacing,
                          new_query_energies_keV=required_knots(lo, hi, rates, spacing)),
        elapsed_seconds=time.perf_counter()-started)


def evaluate(plan_file, measured_file, probe, extension, *, azimuth_samples, energy_order):
    started = time.perf_counter()
    plan, measured = W.read(plan_file), W.read(measured_file)
    W.require(plan['kind'] == PLAN_KIND and plan['measured_plan_sha256'] == W.sha(measured_file),
              'The trial grid was scoped to different original measured records')
    rates, _, basis = retained_rates(probe, measured_file, measured)
    W.require(plan['rate_basis'] == basis, 'The trial plan uses a different initialized rate basis')
    new_binding = None
    if extension is not None:
        new, new_binding = verified_extension(extension, W.sha(plan_file), basis, plan['rate_request']['new_query_energies_keV'])
        W.require(not (rates.keys() & new.keys()), 'New coefficients must keep each previous anchor intact')
        rates |= new
    rates_at, total = rate_functions(rates)
    crystal = photon.ge_halfspaces_from_gdml(probe/'geometry.gdml')
    low, high = min(rates), max(rates)
    branches = []
    counts = Counter()
    primitive_seconds = 0.
    for tid, pair, order, line, geometry_status in scoped_branches(measured, crystal):
        item = dict(original_trigger_id=tid, pair_index=pair['pair_index'], site_index_order=order['site_index_order'],
                    incident_line_keV=line['incident_line_keV'], previous_status=line['status'],
                    geometry_status=geometry_status, trial_results=[])
        branches.append(item)
        if geometry_status != 'available_geometry':
            counts[geometry_status] += len(plan['selected_trials'])
            continue
        i, j = order['site_index_order']
        r1, r2 = pair['fitted_vertices_mm'][i], pair['fitted_vertices_mm'][j]
        obs1, obs2 = pair['measured_site_energies_keV'][i], pair['measured_site_energies_keV'][j]
        for trial in plan['selected_trials']:
            src = trial['source_mm']
            result = dict(status='trial_source_at_first_vertex')
            if src != r1:
                state = point.first_compton_state(src, r1, r2, line['incident_line_keV'])
                e1 = state['intermediate_keV']
                escaped_min = e1/(1+2*e1/photon.ELECTRON_REST_KEV)
                result = dict(state, status='initialized_coefficients_unavailable')
                if low <= escaped_min and e1 <= high:
                    before = time.perf_counter()
                    factors = point.point_source_response(crystal, src, r1, r2, line['incident_line_keV'], obs1, obs2,
                        rates_at, total, sigma_first_keV=plan['sigma_first_keV'], sigma_second_keV=plan['sigma_second_keV'],
                        azimuth_samples=azimuth_samples, energy_order=energy_order)
                    primitive_seconds += time.perf_counter()-before
                    result = dict(status='conditional_factors_computed', response=factors)
            counts[result['status']] += 1
            item['trial_results'].append(result)
    return dict(input_sha256=measured['input_sha256'], trial_plan_sha256=W.sha(plan_file), new_rates=new_binding,
                coefficient_basis=basis, coefficient_model='piecewise log-linear positive bulk-Ge rates with exact table anchors',
                measured_triggers=measured['measured_triggers'], cohorts=measured['scoped_cohorts'],
                selected_trials=plan['selected_trials'], branches=branches, trial_state_counts=dict(counts),
                azimuth_samples=azimuth_samples, energy_order=energy_order,
                sigma_first_keV=plan['sigma_first_keV'], sigma_second_keV=plan['sigma_second_keV'],
                primitive_seconds=primitive_seconds, elapsed_seconds=time.perf_counter()-started,
                interpretation='Conditional two-vertex response after fixing a first Compton vertex. The two widths are analytic inputs. '
                               'First-vertex incidence, candidate selection and merged-event response are separate factors. '
                               'Trial locations and branch responses carry no fitted source estimate or new weights.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest='mode', required=True)
    planner, runner = modes.add_parser('plan'), modes.add_parser('evaluate')
    for mode in (planner, runner):
        for name in ('measured-plan', 'probe', 'output'):
            mode.add_argument('--'+name, type=Path, required=True)
    planner.add_argument('--radius-min-mm', type=float, default=20.)
    planner.add_argument('--radius-max-mm', type=float, default=10000.)
    planner.add_argument('--radial-points', type=int, default=25)
    planner.add_argument('--directions', type=int, default=96)
    planner.add_argument('--trial-index', nargs=2, type=int, action='append', required=True, metavar=('RADIAL', 'DIRECTION'))
    planner.add_argument('--sigma-first-kev', type=float, required=True)
    planner.add_argument('--sigma-second-kev', type=float, required=True)
    runner.add_argument('--plan', type=Path, required=True)
    runner.add_argument('--new-rates', type=Path)
    runner.add_argument('--truth-controls', type=Path)
    runner.add_argument('--azimuth-samples', type=int, default=256)
    runner.add_argument('--energy-order', type=int, default=256)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Choose a new output path')
    if args.mode == 'plan':
        result = make_plan(args.measured_plan, args.probe, args.radius_min_mm, args.radius_max_mm,
            args.radial_points, args.directions, args.trial_index, (args.sigma_first_kev, args.sigma_second_kev))
        status = result['preflight']
    else:
        measured = evaluate(args.plan, args.measured_plan, args.probe, args.new_rates,
            azimuth_samples=args.azimuth_samples, energy_order=args.energy_order)
        digest = W.digest(measured)
        truth = observed.score_after(measured | {'incident_lines_keV': W.read(args.measured_plan)['incident_lines_keV']},
                                     args.truth_controls) if args.truth_controls else None
        W.require(W.digest(measured) == digest, 'Independent truth comparison changed the measured response')
        result = dict(kind='gegi_candidate_trial_point_response_v1', measured_response=measured,
                      measured_response_sha256_before_truth=digest, post_computation_original_order_reference=truth)
        status = measured['trial_state_counts']
    producers = (__file__, point.__file__, photon.__file__, energy.__file__, observed.__file__, grid.__file__)
    result['source_sha256'] = {Path(file).name: W.sha(file) for file in producers}
    result['software'] = dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__)
    with args.output.open('xb') as stream:
        stream.write(W.encoded(result)+b'\n')
    print(status)


if __name__ == '__main__':
    main()
