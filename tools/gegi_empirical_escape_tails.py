"""Extend only the escape domains required by the saved empirical cobalt atoms."""

import argparse
from collections import Counter, defaultdict
from contextlib import closing
import json
import math
from pathlib import Path
import sqlite3
import time

import numpy as np

import gegi_empirical_first_scatter_response as empirical
import scenario_workflow as W


KIND = 'gegi_empirical_escape_tail_bank_v1'
VERIFIED = 'verified_heldout_curve'


def used_atoms(reference, kernel, rows):
    all_cases, outside = [], defaultdict(list)
    for b in reference['branches']:
        for index, result in enumerate(b['trial_results']):
            if result['status'] != 'empirical_conditional_nodes':
                continue
            key = b['curve_key']
            lo, hi = rows[key]['domain_keV']
            nodes = empirical.kernel.conditional_nodes(kernel, b['incident_keV'], result['first_scatter_cosine'])
            energy, weight = nodes['outgoing_energies_keV'], nodes['weights']
            parts = []
            for side, boundary, mask in (('lower', lo, energy < lo), ('upper', hi, energy > hi)):
                if mask.any():
                    tail = key+':'+side
                    outside[tail].extend(energy[mask])
                    parts.append((tail, boundary, mask))
            all_cases.append((b, index, result, energy, weight, parts))
    return all_cases, outside


def setup(args):
    bank, grid, repair = empirical.bank, empirical.grid, empirical.repair
    ref_sha, kernel_sha = W.sha(args.reference), W.sha(args.kernel)
    reference, kernel = W.read(args.reference), W.read(args.kernel)
    support = W.read(args.rate_support)
    W.require(ref_sha == support['reference_sha256'] and kernel_sha == reference['kernel_sha256'] == support['kernel_sha256'],
              'Use the saved empirical comparison and conditional kernel bound to the added coefficients')
    measured, plan, basis, rates, crystal, points = bank.setup(args.measured_plan, args.plan, args.probe, args.new_rates)
    W.require(basis == reference['bank_basis'] and plan['selected_trials'] == reference['selected_trials'] and
              measured['measured_triggers'] == reference['measured_triggers'], 'The original six-point inputs changed')
    keys, _ = bank.geometries(measured, plan, crystal, points, basis['coefficient_support_keV'])
    base_sha, quad_sha = W.sha(args.bank), W.sha(args.quadrature_extension)
    W.require(base_sha == support['unchanged_curve_bank_sha256'] and
              quad_sha == support['unchanged_quadrature_overlay_sha256'], 'Use the original bank and quadrature overlay')
    manifest, rows = grid.read_bank(args.bank, basis, keys)
    _, replacements = repair.read_extension(args.quadrature_extension, base_sha, manifest, rows)
    rows |= replacements
    W.require(rows.keys() == keys.keys() and all(row['status'] == VERIFIED for row in rows.values()),
              'All parent curve domains must be verified and preserved')
    request_path = args.coefficient_extension/'request.json'
    request = W.read(request_path)
    rates_added, binding = bank.trial.verified_extension(args.coefficient_extension, W.sha(request_path),
                                                        basis['original_rate_basis'], request['new_query_energies_keV'])
    W.require(not rates.keys() & rates_added.keys() and binding == support['coefficient_binding'] and
              W.sha(request_path) == support['request_sha256'], 'Use the sealed additive coefficient table')
    rates |= rates_added
    cases, outside = used_atoms(reference, kernel, rows)
    tails = {}
    for tail, atoms in outside.items():
        key, side = tail.split(':')
        bounds = rows[key]['domain_keV']
        lo, hi = (min(atoms), bounds[0]) if side == 'lower' else (bounds[1], max(atoms))
        W.require(lo/(1+2*lo/empirical.ELECTRON_REST_KEV) >= min(rates) and hi <= max(rates),
                  'An exact requested escape endpoint exceeds the initialized coefficient table')
        tails[tail] = dict(domain_keV=[float(lo), float(hi)], model=keys[key]['model'],
                           required_atom_range_keV=[float(min(atoms)), float(max(atoms))],
                           required_atom_count=len(atoms), energies=np.unique(atoms))
    sources = manifest['source_sha256'] | {Path(path).name: W.sha(path) for path in
              (__file__, empirical.__file__, grid.__file__, repair.__file__, empirical.kernel.__file__)}
    recipe = dict(kind=KIND, empirical_reference_sha256=ref_sha, empirical_kernel_sha256=kernel_sha,
                  rate_support_sha256=W.sha(args.rate_support), coefficient_binding=binding,
                  original_curve_bank_sha256=base_sha, quadrature_extension_sha256=quad_sha,
                  preserved_curve_count=len(rows), source_sha256=sources, software=bank.software(),
                  settings=manifest['settings'] | {'initial_uniform_tail_knots': 3, 'fallback_energy_order': 512},
                  tails={key: {k: v for k, v in value.items() if k != 'energies'} for key, value in tails.items()})
    return cases, tails, rows, recipe, crystal, rates, support


def stored_samples(db, key, limits):
    return {e: json.loads(raw) for e, raw in db.execute(
        'SELECT energy,response FROM samples WHERE curve=? AND energy>=? AND energy<=?', (key, *limits))}


def build(args):
    cases, tails, rows, recipe, crystal, rates, support = setup(args)
    bank, repair = empirical.bank, empirical.repair
    settings = recipe['settings']
    rates_at, total = bank.trial.rate_functions(rates)
    # Use the widest interval as the standalone cost and convergence pilot.
    order = sorted(tails, key=lambda key: (tails[key]['domain_keV'][0]-tails[key]['domain_keV'][1], key))
    if args.pilot:
        order = order[:1]
    with closing(sqlite3.connect(args.bank.resolve().as_uri()+'?mode=ro', uri=True)) as base, \
         closing(sqlite3.connect(args.quadrature_extension.resolve().as_uri()+'?mode=ro', uri=True)) as extension, \
         closing(sqlite3.connect(args.tail_bank)) as db:
        bank.create_bank(db, recipe)
        for tail in order:
            item = tails[tail]
            key, side = tail.split(':')
            limits, model = item['domain_keV'], item['model']
            obs, sigma = model['measured_second_site_keV'], model['sigma_second_keV']
            nodes = bank.curve.response_nodes(*limits, obs, sigma, settings['initial_uniform_tail_knots'])
            saved = stored_samples(base, key, limits) | stored_samples(extension, key, limits)
            boundary = rows[key]['comparison']['nodes'][0 if side == 'lower' else -1]
            saved[boundary['intermediate_keV']] = boundary

            def evaluate(energy, energy_order):
                value, = bank.curve.direct_logs([energy], crystal, model['first_fitted_mm'], model['second_fitted_mm'],
                                               obs, rates_at, total, sigma_keV=sigma, energy_order=energy_order,
                                               azimuth_samples=settings['azimuth_samples'])
                return value

            initial = {'comparison': {'nodes': [{'intermediate_keV': float(e)} for e in nodes]}}
            result = repair.repair_curve(db, tail, initial, item, saved, evaluate, settings['energy_order'],
                                         settings['fallback_energy_order'], settings['max_log_error_target'])
            print(dict(tail=tail, domain_keV=limits, status=result['status'],
                       new_direct_points=result['computed_direct_points'], reused_points=result['retained_direct_points'],
                       direct_seconds=result['direct_seconds'], heldout_log_error=result['comparison']['max_absolute_log_error'],
                       quadrature_log_difference=result['comparison']['max_direct_log_quadrature_difference']), flush=True)
        computed = {key: json.loads(text) for key, text in db.execute('SELECT curve,summary FROM curves')}
    if not args.pilot:
        score(args, cases, tails, computed, support, recipe)


def score(args, cases, tails, computed, support, recipe):
    W.require(computed.keys() == tails.keys(), 'Complete the declared tail roster before writing acceptance')
    before = {(r['original_trigger_id'], r['pair_index'], tuple(r['site_index_order']), r['incident_keV'],
               r['trial_index']): r['response'] for r in support['changed_rows'] if r['branch'] == 'escape'}
    changed, coverage = [], Counter()
    for branch, index, result, energy, weight, parts in cases:
        if not parts:
            coverage['full'] += 1
            continue
        identity = (branch['original_trigger_id'], branch['pair_index'], tuple(branch['site_index_order']),
                    branch['incident_keV'], index)
        original = before[identity]
        length = result['separation_mm']
        g1 = empirical.log_gaussian(branch['measured_first_site_keV'], branch['incident_keV']-energy, args.sigma_first_keV)
        log_tail = np.full(energy.shape, np.nan)
        status = np.full(energy.shape, 'inside_original_curve', dtype='<U64')
        for tail, boundary, outside in parts:
            summary = computed[tail]
            status[outside] = summary['status']
            if summary['status'] == VERIFIED:
                logs, codes = empirical.grid.escape_logs(summary, energy[outside], np.ones(outside.sum(), dtype=bool))
                W.require(np.isfinite(logs).all(), 'A verified extension omitted its required atoms')
                log_tail[outside] = logs
                status[outside] = empirical.COMPUTED
        tail_part = empirical.summarize_branch(weight, g1, log_tail, status, -2*math.log(length))
        unknown = (status != 'inside_original_curve') & (status != empirical.COMPUTED)
        scope = 'partial' if unknown.any() else 'full'
        coverage[scope] += 1
        original_log = original['log_covered_factor_per_mm3_observed_keV2']
        tail_log = tail_part['log_covered_factor_per_mm3_observed_keV2']
        combined = float(np.logaddexp(original_log, tail_log)) if tail_log is not None else original_log
        W.require(math.isclose(tail_part['covered_mass']+math.fsum(weight[unknown]), original['uncovered_mass'],
                               rel_tol=0, abs_tol=8*np.finfo(float).eps), 'The tail weights changed')
        changed.append(dict(original_trigger_id=identity[0], pair_index=identity[1], site_index_order=identity[2],
                            incident_keV=identity[3], trial_index=identity[4], tail=tail_part,
                            original_log_covered_factor_per_mm3_observed_keV2=original_log,
                            extended_log_covered_factor_per_mm3_observed_keV2=combined,
                            extended_coverage_status=scope, extended_uncovered_mass=math.fsum(weight[unknown])))
    result = dict(kind='gegi_empirical_escape_tail_coverage_v1', recipe=recipe, tail_bank_sha256=W.sha(args.tail_bank),
                  evaluated_cobalt_states=len(cases), coverage_counts=dict(coverage), changed_states=changed,
                  curve_status_counts=dict(Counter(row['status'] for row in computed.values())),
                  separate_first_scatter_angular_factor='not_applied_conditional_on_scatter_cosine',
                  original_escape_factors='Unchanged and combined only with new independently verified tail contributions.',
                  excluded='Unavailable original geometry and the unrepresented 661.657 keV line retain their original statuses.')
    with args.output.open('xb') as stream:
        stream.write(W.encoded(result)+b'\n')
    print(result['curve_status_counts'], result['coverage_counts'], flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ('reference', 'kernel', 'measured-plan', 'plan', 'probe', 'new-rates', 'bank',
                   'quadrature-extension', 'coefficient-extension', 'rate-support', 'tail-bank'):
        parser.add_argument('--'+option, type=Path, required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--pilot', action='store_true')
    args = parser.parse_args()
    if not args.pilot and (args.output is None or args.output.exists()):
        parser.error('Supply a fresh output path for the completed acceptance')
    W.require(args.tail_bank.resolve() not in {args.bank.resolve(), args.quadrature_extension.resolve()},
              'Use a separate bank for extensions')
    args.sigma_first_keV = W.read(args.reference)['settings']['sigma_first_keV']
    build(args)


if __name__ == '__main__':
    main()
