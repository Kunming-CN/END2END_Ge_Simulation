"""Reuse a fixed-pair, fixed-observation escape response as a function of photon energy."""

import argparse
import math
from pathlib import Path
import platform
import time

import numpy as np
import scipy
from scipy.interpolate import PchipInterpolator
from scipy.special import log_ndtr

import gegi_candidate_trial_response as trial
import gegi_photon_continuation as photon
import gegi_photon_log_response as logarithms
import gegi_photon_observed_energy as measured
import scenario_workflow as W


def log_tail_envelope(intermediate_keV, observed_keV, sigma_keV):
    """Factor the Gaussian integral below the Compton energy-transfer endpoint."""
    e = np.asarray(intermediate_keV)
    endpoint = 2*e*e/(photon.ELECTRON_REST_KEV+2*e)
    return log_ndtr((endpoint-observed_keV)/sigma_keV)


def response_nodes(low, high, observed_keV, sigma_keV, count):
    """Cover the whole energy span and resolve where the endpoint crosses the observation."""
    if not (0 < low < high and math.isfinite(high) and count >= 2):
        raise ValueError('Require a nonempty positive energy interval and at least two base knots')
    measured.gaussian_density_per_kev(observed_keV, 0., sigma_keV)
    deposits = observed_keV+sigma_keV*np.array([-8., -4., -2., -1., 0., 1., 2., 4., 8.])
    deposits = deposits[deposits > 0]
    transitions = (deposits+np.sqrt(deposits*(deposits+2*photon.ELECTRON_REST_KEV)))/2
    return np.unique(np.r_[np.linspace(low, high, count), transitions[(low < transitions) & (transitions < high)]])


class EscapeResponseCurve:
    """Interpolate the residual natural log after removing an analytic Gaussian envelope."""

    def __init__(self, nodes, log_density, *, observed_keV, sigma_keV):
        self.nodes = np.asarray(nodes, dtype=float)
        logs = np.asarray(log_density, dtype=float)
        measured.gaussian_density_per_kev(observed_keV, 0., sigma_keV)
        if (self.nodes.ndim != 1 or self.nodes.size < 2 or np.any(self.nodes <= 0)
                or logs.shape != self.nodes.shape or not np.isfinite(logs).all()):
            raise ValueError('Require positive nodes and finite logs for a supported escape channel')
        self.observed_keV, self.sigma_keV = observed_keV, sigma_keV
        residual = logs-log_tail_envelope(self.nodes, observed_keV, sigma_keV)
        self._interpolator = PchipInterpolator(self.nodes, residual, extrapolate=False)

    def log_density(self, intermediate_keV):
        """Return ln of the escape density per path-mm per observed keV, within the fitted interval."""
        e = np.asarray(intermediate_keV, dtype=float)
        if not np.isfinite(e).all() or np.any(e < self.nodes[0]) or np.any(e > self.nodes[-1]):
            raise ValueError('Intermediate energy outside the escape curve domain')
        return self._interpolator(e)+log_tail_envelope(e, self.observed_keV, self.sigma_keV)


def direct_logs(energies, crystal, first, second, observation, rates_at, outgoing_total, *, sigma_keV,
                azimuth_samples, energy_order):
    for e in energies:
        result = measured.observed_continuation(crystal, first, second, e, rates_at(e), outgoing_total, [observation],
            sigma_keV=sigma_keV, azimuth_samples=azimuth_samples, energy_order=energy_order, include_log=True)
        row, = result['observations']
        yield dict(intermediate_keV=float(e), log_escape_density=row['log_escape_per_mm_observed_keV'],
                   raw_escape_density=row['escape_per_mm_observed_keV'], density_status=row['escape_density_status'],
                   log_quadrature_difference=row['log_escape_quadrature_difference'])


def compare(fit, validation, energies, observation, sigma_keV, max_log_error):
    nodes = [row['intermediate_keV'] for row in fit]
    held_out = [row['intermediate_keV'] for row in validation]
    fit_logs = [row['log_escape_density'] for row in fit]
    start = time.perf_counter()
    curve = EscapeResponseCurve(nodes, fit_logs, observed_keV=observation, sigma_keV=sigma_keV)
    curve_build_seconds = time.perf_counter()-start
    start = time.perf_counter()
    interpolated = curve.log_density(held_out)
    heldout_query_seconds = time.perf_counter()-start
    start = time.perf_counter()
    curve.log_density(energies)
    grid_query_seconds = time.perf_counter()-start
    naive_logs = PchipInterpolator(nodes, fit_logs)(held_out)
    errors = []
    for row, log_curve, log_naive in zip(validation, interpolated, naive_logs, strict=True):
        delta = float(log_curve-row['log_escape_density'])
        errors.append(dict(row, log_curve=float(log_curve), log_error=delta,
                   log_error_without_envelope=float(log_naive-row['log_escape_density']),
                   density_error_per_mm_observed_keV=math.exp(log_curve)-row['raw_escape_density'],
                   relative_density_error_from_logs=math.expm1(delta) if delta < math.log(np.finfo(float).max) else None))
    worst = max(errors, key=lambda row:abs(row['log_error']))
    quad_worst = max(row['log_quadrature_difference'] for row in fit+validation)
    return dict(interpolant='PCHIP of ln density minus ln Gaussian CDF at the Compton deposit endpoint',
        log_density_units='ln of numerical density in inverse-mm per observed keV',
        nodes=fit, held_out=errors, worst_log_error=worst,
        max_absolute_log_error=abs(worst['log_error']),
        max_absolute_log_error_without_envelope=max(abs(row['log_error_without_envelope']) for row in errors),
        max_absolute_density_error=max(abs(row['density_error_per_mm_observed_keV']) for row in errors),
        max_direct_log_quadrature_difference=quad_worst,
        matches_log_target=abs(worst['log_error']) <= max_log_error and quad_worst <= max_log_error,
        timing_seconds=dict(interpolator_build=curve_build_seconds, heldout_curve_query=heldout_query_seconds,
                            trial_grid_curve_query=grid_query_seconds), trial_grid_queries=len(energies))


def benchmark_curve(energies, crystal, first, second, observation, rates_at, outgoing_total, *, sigma_keV,
                    azimuth_samples, energy_order, base_nodes, max_log_error, prior=None):
    nodes = response_nodes(float(min(energies)), float(max(energies)), observation, sigma_keV, base_nodes)
    cached = {}
    reference_seconds = 0.
    if prior is not None:
        W.require([row['intermediate_keV'] for row in prior['nodes']] == list(nodes),
                  'Refinement must begin at the preserved node energies')
        raw_fields = ('intermediate_keV', 'log_escape_density', 'raw_escape_density', 'density_status', 'log_quadrature_difference')
        cached = {r['intermediate_keV']:{key:r[key] for key in raw_fields} for r in prior['nodes']+prior['held_out']}
        reference_seconds = prior['timing_seconds']['direct_node_quadrature']+prior['timing_seconds']['heldout_direct_quadrature']
    cached_before = len(cached)
    kwargs = dict(sigma_keV=sigma_keV, azimuth_samples=azimuth_samples, energy_order=energy_order)

    def reference(values):
        start = time.perf_counter()
        missing = [e for e in values if e not in cached]
        for row in direct_logs(missing, crystal, first, second, observation, rates_at, outgoing_total, **kwargs):
            cached[row['intermediate_keV']] = row
        return [cached[e] for e in values], time.perf_counter()-start

    fit_seconds = validation_seconds = 0.
    passes = []
    while True:
        held_out = (nodes[:-1]+nodes[1:])/2
        W.require(np.all((nodes[:-1] < held_out) & (held_out < nodes[1:])),
                  'No distinct midpoint remains at floating-point precision')
        fit, wall = reference(nodes)
        fit_seconds += wall
        independent, wall = reference(held_out)
        validation_seconds += wall
        result = compare(fit, independent, energies, observation, sigma_keV, max_log_error)
        failures = [r['intermediate_keV'] for r in result['held_out'] if abs(r['log_error']) > max_log_error]
        if prior is None or not failures or result['max_direct_log_quadrature_difference'] > max_log_error:
            break
        passes.append(dict(promoted_midpoints_keV=failures, max_absolute_log_error=result['max_absolute_log_error'],
                           worst_log_error=result['worst_log_error']))
        nodes = np.sort(np.r_[nodes, failures])
    result['timing_seconds'].update(direct_node_quadrature=fit_seconds, heldout_direct_quadrature=validation_seconds,
                                    previous_reference_quadrature=reference_seconds)
    result.update(refinement_passes=passes, retained_direct_points=cached_before, new_direct_points=len(cached)-cached_before)
    return result


def benchmark_branches(measured_plan, crystal, lines):
    """Take the first saved pair/order in each successive geometry-available chronological trigger."""
    rows = sorted(measured_plan['measured_triggers'], key=lambda u:(u['trigger_time_ns'], u['original_trigger_id']))
    select = iter(lines)
    line = next(select, None)
    used = set()
    for tid, pair, order, state, status in trial.scoped_branches({'measured_triggers':rows}, crystal):
        if status != 'available_geometry' or tid in used or state['incident_line_keV'] != line:
            continue
        yield tid, pair, order, line
        used.add(tid)
        line = next(select, None)
        if line is None:
            return
    if line is not None:
        raise ValueError('The measured plan does not supply the requested chronological, line-specific branches')


def run(measured_path, plan_path, probe, extra_path, lines, *, base_nodes, max_log_error, azimuth_samples, energy_order,
        prior_path=None):
    start = time.perf_counter()
    measured_plan, plan = W.read(measured_path), W.read(plan_path)
    W.require(plan['kind'] == trial.PLAN_KIND and plan['measured_plan_sha256'] == W.sha(measured_path),
              'Select the original measured and trial plans together')
    W.require(lines and set(lines) <= set(measured_plan['incident_lines_keV']), 'Supply explicit saved incident energies')
    rates, _, basis = trial.retained_rates(probe, measured_path, measured_plan)
    W.require(basis == plan['rate_basis'], 'The trial energy domain uses a different material basis')
    new, binding = trial.verified_extension(extra_path, W.sha(plan_path), basis, plan['rate_request']['new_query_energies_keV'])
    W.require(not (rates.keys() & new.keys()), 'Initialized energies must have distinct anchors')
    rates_at, total = trial.rate_functions(rates | new)
    crystal = photon.ge_halfspaces_from_gdml(probe/'geometry.gdml')
    grid = plan['trial_grid']
    points = (np.array(grid['radii_mm'])[:, None, None]*np.array(grid['unit_vectors']))+grid['origin_mm']
    sigma = plan['sigma_second_keV']
    settings = dict(sigma_second_keV=sigma, base_nodes=base_nodes, azimuth_samples=azimuth_samples,
                    energy_order=energy_order, max_log_error_target=max_log_error)
    producers = {Path(f).name:W.sha(f) for f in (
        __file__, trial.__file__, trial.point.__file__, photon.__file__, measured.__file__, logarithms.__file__)}
    software = dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__)
    prior = W.read(prior_path) if prior_path is not None else None
    if prior is not None:
        W.require(prior['measured_plan_sha256'] == W.sha(measured_path) and prior['trial_plan_sha256'] == W.sha(plan_path)
            and prior['original_rate_basis'] == basis and prior['new_rate_binding'] == binding and prior['settings'] == settings
            and prior['software'] == software and all(prior['source_sha256'][f] == digest for f,digest in producers.items()
                if f != Path(__file__).name), 'Refinement requires the original direct reference settings and producers')
    output = []
    picked = list(benchmark_branches(measured_plan, crystal, lines))
    if prior is not None:
        W.require(len(prior['branches']) == len(picked) and all(
            (r['original_trigger_id'],r['pair_index'],r['site_index_order'],r['incident_keV']) == (tid,p['pair_index'],o['site_index_order'],e)
            for r,(tid,p,o,e) in zip(prior['branches'],picked,strict=True)), 'Refinement changed the original branch identities')
    for index, (tid, pair, order, line) in enumerate(picked):
        i, j = order['site_index_order']
        first, second = (pair['fitted_vertices_mm'][k] for k in (i, j))
        energies = np.array([trial.point.first_compton_state(p, first, second, line)['intermediate_keV']
                             for p in points.reshape(-1, 3) if np.any(p != first)])
        obs = pair['measured_site_energies_keV'][j]
        result = benchmark_curve(energies, crystal, first, second, obs, rates_at, total, sigma_keV=sigma,
            azimuth_samples=azimuth_samples, energy_order=energy_order, base_nodes=base_nodes, max_log_error=max_log_error,
            prior=prior['branches'][index]['comparison'] if prior is not None else None)
        output.append(dict(original_trigger_id=tid, pair_index=pair['pair_index'], site_index_order=order['site_index_order'],
                           incident_keV=line, measured_second_site_keV=obs, first_fitted_mm=first, second_fitted_mm=second,
                           separation_mm=math.dist(first, second), comparison=result))
    return dict(kind='gegi_escape_response_curve_benchmark_v1', measured_plan_sha256=W.sha(measured_path),
                trial_plan_sha256=W.sha(plan_path), original_rate_basis=basis, new_rate_binding=binding,
                branch_selection='First saved available pair/order in each successive geometry-available chronological trigger. '
                                 'Line energies are supplied independently and no photon truth enters.',
                settings=settings, prior_reference_sha256=W.sha(prior_path) if prior_path is not None else None,
                branches=output, software=software, source_sha256=producers, elapsed_seconds=time.perf_counter()-start)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('measured-plan', 'trial-plan', 'probe', 'new-rates', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--incident-kev', type=float, action='append', required=True)
    parser.add_argument('--base-nodes', type=int, default=25)
    parser.add_argument('--azimuth-samples', type=int, default=256)
    parser.add_argument('--energy-order', type=int, default=256)
    parser.add_argument('--max-log-error', type=float, default=.01)
    parser.add_argument('--refine-from', type=Path, help='Reuse direct quadrature from the first benchmark')
    args = parser.parse_args()
    if args.output.exists() or not math.isfinite(args.max_log_error) or args.max_log_error <= 0:
        parser.error('Supply a new output path and positive finite accuracy target')
    result = run(args.measured_plan, args.trial_plan, args.probe, args.new_rates, args.incident_kev,
                 base_nodes=args.base_nodes, max_log_error=args.max_log_error,
                 energy_order=args.energy_order, azimuth_samples=args.azimuth_samples, prior_path=args.refine_from)
    with args.output.open('xb') as out:
        out.write(W.encoded(result)+b'\n')
    for row in result['branches']:
        print(row['original_trigger_id'], row['comparison']['max_absolute_log_error'], row['comparison']['matches_log_target'])


if __name__ == '__main__':
    main()
