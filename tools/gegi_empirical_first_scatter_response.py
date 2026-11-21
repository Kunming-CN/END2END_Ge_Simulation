"""Integrate a conditional Livermore first-scatter kernel over shared site energies.

At fixed first vertex and scattering cosine, integrate the first Gaussian at
E0-E and the second response at the SAME outgoing energy E. The second response
is per path-mm per observed keV. Division by the squared intersite distance
supplies the geometric factor used in point-source volume densities. The
resulting factors have units mm^-3 keV^-2 conditional on the scattering angle.
An angular density per sr is a separate factor, intentionally absent here.
"""

import argparse
from collections import Counter
import math
from pathlib import Path

import numpy as np
from scipy.special import logsumexp

import gegi_candidate_grid_response as grid
import gegi_candidate_trial_curve_bank as bank
import gegi_compton_energy_kernel as kernel
from gegi_photon_continuation import ELECTRON_REST_KEV
from gegi_point_source_response import first_compton_state
import gegi_trial_curve_quadrature_repair as repair
import scenario_workflow as W


BRANCHES = ('absorption', 'escape')
COBALT_LINES_KEV = (1173.228, 1332.492)
COMPUTED = 'conditional_factor_computed'
UNSUPPORTED_RATE = 'initialized_coefficients_unavailable'


def log_gaussian(observed_keV, expected_keV, sigma_keV):
    """Vectorized normalized Gaussian in the observed-energy measure."""
    if not math.isfinite(observed_keV) or not math.isfinite(sigma_keV) or sigma_keV <= 0:
        raise ValueError('Supply finite observed keV and a positive finite analytic width')
    z = (observed_keV-expected_keV)/sigma_keV
    return -.5*z*z-.5*math.log(2*math.pi)-math.log(sigma_keV)


def coverage_status(mask):
    return 'full' if mask.all() else 'partial' if mask.any() else 'unavailable'


def summarize_branch(weights, log_first, log_second, statuses, inverse_area_log, *, zero_rate=None):
    covered = statuses == COMPUTED
    by_status = {str(status): dict(nodes=int(np.count_nonzero(statuses == status)),
                                   mass=math.fsum(weights[statuses == status]))
                 for status in np.unique(statuses)}
    result = dict(coverage_status=coverage_status(covered),
                  covered_mass=math.fsum(weights[covered]), uncovered_mass=math.fsum(weights[~covered]),
                  node_accounting=by_status, log_covered_factor_per_mm3_observed_keV2=None,
                  covered_factor_per_mm3_observed_keV2=None, covered_density_status='unavailable')
    if covered.any():
        terms = np.log(weights[covered])+log_first[covered]+log_second[covered]
        log_factor = float(logsumexp(terms)+inverse_area_log)
        if zero_rate is not None and zero_rate[covered].all():
            result.update(covered_factor_per_mm3_observed_keV2=0., covered_density_status='physical_zero')
        elif not math.isfinite(log_factor):
            result.update(covered_density_status='density_outside_finite_log_range')
        elif log_factor > math.log(np.finfo(float).max):
            result.update(log_covered_factor_per_mm3_observed_keV2=log_factor, covered_density_status='overflow')
        else:
            factor = math.exp(log_factor)
            result.update(log_covered_factor_per_mm3_observed_keV2=log_factor,
                          covered_factor_per_mm3_observed_keV2=factor,
                          covered_density_status='positive' if factor else 'underflow')
    return result


def coefficient_gaps(lower, upper, low, high):
    """Endpoints needed beyond the current table, before testing curve coverage."""
    below, above = lower[lower < low], upper[upper > high]
    return dict(below_table_keV=[float(below.min()), float(below.max())] if below.size else None,
                above_table_keV=[float(above.min()), float(above.max())] if above.size else None)


def integrate_atoms(incident_keV, length_mm, observed_keV, sigma_keV, outgoing_keV, weights,
                    rates_at, rate_support_keV, escape_summary):
    """Evaluate two branches on the original normalized atom weights.

    Supply initialized bulk-Ge rates and a verified escape curve summary for
    this exact ordered geometry and second observation. None means no verified
    escape curve. Any reported partial factor sums its available terms with
    their original weights. The result includes the entire remaining mass.
    """
    outgoing = np.asarray(outgoing_keV, dtype=float)
    weights = np.asarray(weights, dtype=float)
    if (not math.isfinite(incident_keV) or incident_keV <= 0 or not math.isfinite(length_mm) or length_mm <= 0
            or outgoing.ndim != 1 or not outgoing.size or weights.shape != outgoing.shape
            or not np.isfinite(outgoing).all() or not np.isfinite(weights).all()
            or (outgoing <= 0).any() or (outgoing > incident_keV).any() or (weights <= 0).any()
            or not math.isclose(math.fsum(weights), 1., rel_tol=0., abs_tol=8*np.finfo(float).eps)):
        raise ValueError('Require a positive path and a normalized finite kernel on 0 < E <= incident energy')
    low, high = rate_support_keV
    if not (0 < low <= high and math.isfinite(high)):
        raise ValueError('Require a finite positive material coefficient interval')
    log_first = log_gaussian(observed_keV[0], incident_keV-outgoing, sigma_keV[0])
    log_absorption = log_gaussian(observed_keV[1], outgoing, sigma_keV[1])
    rate_available = (outgoing >= low) & (outgoing <= high)
    zero_photoelectric = np.zeros(outgoing.shape, dtype=bool)
    for index in np.flatnonzero(rate_available):
        rate = rates_at(outgoing[index])
        if rate.photoelectric_per_mm:
            log_absorption[index] += math.log(rate.photoelectric_per_mm)-length_mm*rate.total_per_mm
        else:
            log_absorption[index] = -math.inf
            zero_photoelectric[index] = True
    absorption_status = np.where(rate_available, COMPUTED, UNSUPPORTED_RATE)
    # Each second-site escape quadrature requires coefficients down to
    # backscatter at this particular incoming energy, not the first-site E0.
    backscatter_energy = outgoing/(1+2*outgoing/ELECTRON_REST_KEV)
    escape_rate_available = (backscatter_energy >= low) & rate_available
    if escape_summary and escape_summary['status'] == 'verified_heldout_curve':
        model = escape_summary['model']
        if (model['measured_second_site_keV'], model['sigma_second_keV']) != (observed_keV[1], sigma_keV[1]):
            raise ValueError('The escape curve must use this second-site observation and width')
    log_escape, escape_codes = grid.escape_logs(escape_summary, outgoing, escape_rate_available)
    escape_status = np.asarray(grid.STATUS)[escape_codes]
    escape_status[rate_available & ~escape_rate_available] = 'outgoing_coefficients_unavailable'
    inverse_area_log = -2*math.log(length_mm)
    absorption = summarize_branch(weights, log_first, log_absorption, absorption_status,
                                  inverse_area_log, zero_rate=zero_photoelectric)
    escape = summarize_branch(weights, log_first, log_escape, escape_status, inverse_area_log)
    absorption['missing_coefficient_endpoint_ranges_keV'] = coefficient_gaps(outgoing, outgoing, low, high)
    escape['missing_coefficient_endpoint_ranges_keV'] = coefficient_gaps(backscatter_energy, outgoing, low, high)
    absorption['coefficient_coverage_status'] = coverage_status(rate_available)
    escape['coefficient_coverage_status'] = coverage_status(escape_rate_available)
    return dict(absorption=absorption, escape=escape)


def point_response(kernel_receipt, source_mm, first_mm, second_mm, incident_keV,
                   observed_keV, sigma_keV, rates_at, rate_support_keV, escape_summary):
    """Evaluate the empirical conditional factors at one trial position with no angular prior."""
    if incident_keV not in kernel_receipt['incident_energies_keV']:
        return unavailable('incident_energy_unrepresented')
    if np.array_equal(source_mm, first_mm):
        return unavailable('trial_source_at_first_vertex')
    state = first_compton_state(source_mm, first_mm, second_mm, incident_keV)
    nodes = kernel.conditional_nodes(kernel_receipt, incident_keV, state['first_scatter_cosine'])
    if nodes['weights'] is None:
        return unavailable(nodes['status']) | {'angular_bin_weights': nodes['angular_bin_weights']}
    return dict(status=nodes['status'], first_scatter_cosine=state['first_scatter_cosine'],
                separation_mm=state['site_separation_mm'], angular_bin_weights=nodes['angular_bin_weights'],
                outgoing_atoms=len(nodes['weights']), kernel_mass=math.fsum(nodes['weights']),
                outgoing_support_keV=[float(nodes['outgoing_energies_keV'].min()),
                                      float(nodes['outgoing_energies_keV'].max())],
                branches=integrate_atoms(incident_keV, state['site_separation_mm'], observed_keV, sigma_keV,
                                         nodes['outgoing_energies_keV'], nodes['weights'],
                                         rates_at, rate_support_keV, escape_summary))


def unavailable(reason):
    return dict(status=reason, kernel_mass=None, branches={
        name: dict(coverage_status='unavailable', covered_mass=None, uncovered_mass=None,
                   node_accounting=None, log_covered_factor_per_mm3_observed_keV2=None,
                   covered_factor_per_mm3_observed_keV2=None, covered_density_status='unavailable',
                   coefficient_coverage_status='unavailable',
                   missing_coefficient_endpoint_ranges_keV=None)
        for name in BRANCHES})


def evaluate(plan, keys, rows, original, empirical_kernel, rates, coefficient_support):
    rates_at, _ = bank.trial.rate_functions(rates)
    selected = plan['selected_trials']
    sigmas = plan['sigma_first_keV'], plan['sigma_second_keV']
    result = []
    for branch in original:
        row = {k: v for k, v in branch.items() if k not in
               ('states', 'escape_coefficients_available', 'first_vertex_distinct')}
        incident = branch['incident_keV']
        row['empirical_line_status'] = ('supported_cobalt_line' if incident in COBALT_LINES_KEV else
                                       'incident_energy_unrepresented' if incident not in
                                       empirical_kernel['incident_energies_keV'] else 'outside_declared_cobalt_scope')
        if row['empirical_line_status'] != 'supported_cobalt_line':
            results = [unavailable(row['empirical_line_status']) for trial in selected]
        elif branch['geometry_status'] != 'available_geometry':
            results = [unavailable(branch['geometry_status']) for trial in selected]
        else:
            key = branch['curve_key']
            model = keys[key]['model']
            observations = (branch['measured_first_site_keV'], model['measured_second_site_keV'])
            results = [point_response(empirical_kernel, trial['source_mm'], model['first_fitted_mm'],
                                      model['second_fitted_mm'], incident, observations, sigmas, rates_at,
                                      coefficient_support, rows.get(key)) for trial in selected]
        row['trial_results'] = results
        result.append(row)
    return result


def coefficient_extension(trials, rates, spacing):
    low, high = min(rates), max(rates)
    result = {}
    for name in BRANCHES:
        gaps = [r['branches'][name]['missing_coefficient_endpoint_ranges_keV'] for r in trials]
        endpoints = {}
        queries = set()
        for direction in ('below_table_keV', 'above_table_keV'):
            ranges = [g[direction] for g in gaps if g and g[direction]]
            spread = [min(x[0] for x in ranges), max(x[1] for x in ranges)] if ranges else None
            endpoints[direction] = spread
            if spread:
                limits = (spread[0], low) if direction == 'below_table_keV' else (high, spread[1])
                queries.update(bank.trial.required_knots(*limits, rates, spacing))
        result[name] = dict(missing_endpoint_ranges_keV=endpoints, suggested_query_energies_keV=sorted(queries))
    return dict(prior_interpolation_log_spacing=spacing, branches=result,
                scope='Only extensions of the material coefficient domain. Escape curves still require independent verification.')


def run(args):
    W.require(not args.output.exists(), 'Select a fresh empirical response output path')
    empirical_kernel = W.read(args.kernel)
    represented = empirical_kernel['incident_energies_keV']
    W.require(set(COBALT_LINES_KEV).issubset(represented) and 661.657 not in represented,
              'The empirical control uses the two recorded cobalt lines and retains 661.657 keV as unrepresented')
    measured, plan, basis, rates, crystal, points = bank.setup(args.measured_plan, args.plan, args.probe, args.new_rates)
    W.require(len(plan['selected_trials']) == 6, 'Supply the declared six-point trial plan for this acceptance')
    keys, original = bank.geometries(measured, plan, crystal, points, basis['coefficient_support_keV'])
    base_sha = W.sha(args.bank)
    manifest, rows = grid.read_bank(args.bank, basis, keys)
    W.require(rows.keys() == keys.keys(), 'Use a completed base escape bank')
    extension = None
    if args.quadrature_extension is not None:
        extension_sha = W.sha(args.quadrature_extension)
        recipe, replacement = repair.read_extension(args.quadrature_extension, base_sha, manifest, rows)
        rows |= replacement
        extension = dict(sha256=extension_sha, recipe=recipe)
    for key, row in rows.items():
        if row['status'] == 'verified_heldout_curve':
            W.require(all(row[field] == keys[key][field] for field in ('model', 'domain_keV')),
                      'A verified escape curve does not match the ordered geometry or domain in its manifest')
    branches = evaluate(plan, keys, rows, original, empirical_kernel, rates, basis['coefficient_support_keV'])
    W.require(W.sha(args.bank) == base_sha and
              (extension is None or W.sha(args.quadrature_extension) == extension['sha256']),
              'An escape bank changed during evaluation')
    trials = [r for b in branches for r in b['trial_results']]
    provenance = manifest['source_sha256'] | {
        Path(p).name: W.sha(p) for p in (__file__, kernel.__file__, grid.__file__)}
    result = dict(kind='gegi_empirical_first_scatter_response_controls_v1', kernel_sha256=W.sha(args.kernel),
                  represented_incident_keV=represented, evaluated_incident_keV=COBALT_LINES_KEV,
                  base_bank_sha256=base_sha, quadrature_extension=extension, bank_basis=basis,
                  first_scatter_angular_density_per_sr=None,
                  first_scatter_angular_factor_status='not_applied_conditional_on_scatter_cosine',
                  conditional_factor_units='mm^-3 keV^-2 at a specified scattering angle',
                  source_sha256=provenance, software=bank.software(), selected_trials=plan['selected_trials'],
                  settings=dict(sigma_first_keV=plan['sigma_first_keV'], sigma_second_keV=plan['sigma_second_keV'],
                                escape_curve_settings=manifest['settings']),
                  measured_cohorts=measured['scoped_cohorts'], measured_triggers=measured['measured_triggers'],
                  branches=branches, trial_status_counts=dict(Counter(r['status'] for r in trials)),
                  branch_coverage_counts={name: dict(Counter(r['branches'][name]['coverage_status'] for r in trials))
                                          for name in BRANCHES},
                  coefficient_coverage_counts={
                      name: dict(Counter(r['branches'][name]['coefficient_coverage_status'] for r in trials))
                      for name in BRANCHES},
                  prospective_coefficient_extension=coefficient_extension(
                      trials, rates, plan['rate_request']['prior_interpolation_log_spacing']),
                  curve_status_counts=dict(Counter(r['status'] for r in rows.values())),
                  scientific_scope=[
                      'Conditional Livermore outgoing-energy kernel at the trial scattering cosine with approximate angular-bin interpolation. '
                      'No first-scatter angular density is included. The native angular marginal and energy interpolation are separate.',
                      'The same outgoing atom sets first deposited energy and enters second absorption or the free-electron second-escape curve. '
                      'Numerical support gaps retain their original mass. Partial values contain only covered contributions with no renormalization.',
                      'Gaussian widths are analytic settings. Position uncertainty, entrance attenuation and acquisition selection normalization are omitted. '
                      'No source choice, model probabilities, data-driven reweighting or imaging score is reported.'])
    encoded = W.encoded(result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('xb') as stream:
        stream.write(encoded+b'\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ('kernel', 'measured-plan', 'plan', 'probe', 'new-rates', 'bank', 'output'):
        parser.add_argument('--'+option, type=Path, required=True)
    parser.add_argument('--quadrature-extension', type=Path)
    result = run(parser.parse_args())
    print(result['trial_status_counts'], result['branch_coverage_counts'])


if __name__ == '__main__':
    main()
