"""Estimate normalized ideal topology mass under the empirical first-scatter joint measure.

The original eight Sobol ray coordinates are retained exactly. An independently
scrambled ninth coordinate samples the conditional outgoing-energy atom. The
first angular importance factor for a uniform solid-angle proposal is
4*pi*p_empirical(Omega). The same atom controls second-site cross sections,
flight, and canonical free-Compton continuation. Integrating unit-normalized
energy measurements removes both Gaussian factors from this denominator.
"""

import argparse
import math
from pathlib import Path
import time

import numpy as np
from scipy.stats import qmc

import gegi_empirical_atom_sampling as sampling
import gegi_empirical_compton_joint as joint
import gegi_shared_topology_normalization as ideal_shared
import scenario_workflow as W


def sobol_draws(seed, power):
    original = qmc.Sobol(8, scramble=True, seed=seed).random_base2(power)
    independent = np.random.default_rng(np.random.SeedSequence([seed, 9]))
    atom = qmc.Sobol(9, scramble=True, seed=independent).random_base2(power)[:, 8]
    return np.column_stack((original, atom))


def empirical_factors(uniforms, kernel, incident, rate_at, outgoing_total, support):
    model = joint.angular_model(kernel, incident)
    draws = [sampling.sample_conditional_atom(kernel, incident, 1-2*u, v, model)
             for u, v in zip(uniforms[:, 3], uniforms[:, 8], strict=True)]
    W.require(all(d['status'] == 'sampled' for d in draws), 'The declared empirical incident line must cover every proposed angle')
    intermediate = np.array([d['outgoing_keV'] for d in draws])
    angular_per_sr = np.array([d['angular_density_per_sr'] for d in draws])
    atom_mass = np.array([d['conditional_mass'] for d in draws])
    canonical = ideal_shared.ideal
    x2 = 2*uniforms[:, 6]
    outgoing = canonical.outgoing_energy(intermediate, x2)
    lo, hi = support
    W.require(lo <= np.min(outgoing) and np.max(intermediate) <= hi and np.max(outgoing) <= hi,
              'A sampled shared atom or second outgoing energy exceeds the initialized coefficient support')
    partial = np.array([(r.total_per_mm, r.photoelectric_per_mm, r.compton_per_mm)
                        for r in map(rate_at, intermediate)])
    p2 = np.array([2*canonical.photon.cosine_density(e, 1-x) for e, x in zip(intermediate, x2, strict=True)])
    return dict(first=rate_at(incident), first_angle=4*math.pi*angular_per_sr, second_angle=p2, second=partial,
                known=np.ones(len(uniforms), dtype=bool), exit_rate=np.array([outgoing_total(e) for e in outgoing]),
                missing_bound_per_fraction=0.), dict(intermediate_keV=intermediate, second_outgoing_keV=outgoing,
                                                    atom_conditional_mass=atom_mass)


def atom_census(seed, factors, traces, powers):
    return dict(seed=seed, estimates=[dict(
        points=2**p, sampled_intermediate_range_keV=[float(np.min(traces['intermediate_keV'][:2**p])),
                                                     float(np.max(traces['intermediate_keV'][:2**p]))],
        sampled_second_outgoing_range_keV=[float(np.min(traces['second_outgoing_keV'][:2**p])),
                                         float(np.max(traces['second_outgoing_keV'][:2**p]))],
        mean_angular_importance_weight=float(np.mean(factors['first_angle'][:2**p])),
        max_atom_conditional_mass_difference_from_one=float(np.max(np.abs(traces['atom_conditional_mass'][:2**p]-1))))
        for p in powers])


def merge_rates(probe, basis, original, global_support):
    bank = ideal_shared.ideal.bank
    first_dir, second_dir = (probe/name for name in ('empirical-first-scatter-rates', 'empirical-global-rates'))
    first_request, second_request = (W.read(d/'request.json') for d in (first_dir, second_dir))
    first, first_binding = bank.trial.verified_extension(first_dir, W.sha(first_dir/'request.json'),
        basis['original_rate_basis'], first_request['new_query_energies_keV'])
    second, second_binding = bank.trial.verified_extension(second_dir, W.sha(second_dir/'request.json'),
        basis['original_rate_basis'], second_request['new_query_energies_keV'])
    W.require(global_support['base_rate_basis'] == basis == second_request['initialized_base_basis'] and
              W.sha(probe/'first-scatter-global-support.json') == second_request['global_energy_support_sha256'] and
              first_binding == global_support['added_rate_binding'] == second_request['prior_rate_extension'] and
              not (original.keys() & first.keys() or (original.keys() | first.keys()) & second.keys()),
              'Coefficient tables must match and add only disjoint initialized anchors')
    rates = original | first | second
    return rates, [first_binding, second_binding]


def run(probe, output):
    W.require(not output.exists(), 'Use a fresh empirical normalizer output path')
    started = time.perf_counter()
    ideal, bank = ideal_shared.ideal, ideal_shared.ideal.bank
    _, plan, basis, original, crystal, _ = bank.setup(probe/'measured-response-plan.json',
                                                       probe/'source-trial-response-plan.json', probe, probe/'source-trial-rates')
    inputs = dict(kernel=probe/'first-scatter-energy-kernel.json',
                  support=probe/'first-scatter-global-support.json',
                  joint=probe/'first-scatter-joint-controls.json',
                  prior=probe/'ideal-two-interaction-normalization-controls.json')
    kernel, closure, reference, prior = (W.read(p) for p in inputs.values())
    W.require(prior['basis'] == basis and closure['joint_receipt_sha256'] == W.sha(inputs['joint']) and
              closure['empirical_kernel_sha256'] == W.sha(inputs['kernel']) ==
              reference['baseline_recipe']['empirical_kernel_sha256'] and
              closure['free_second_scatter_electron_rest_keV'] == ideal.photon.ELECTRON_REST_KEV and
              closure['native_first_scatter_electron_rest_keV'] == kernel['native_metadata']['native_electron_rest_keV'],
              'Use matching archived kernel, joint response, support and material inputs')
    rates, bindings = merge_rates(probe, basis, original, closure)
    support = min(rates), max(rates)
    energies = kernel['incident_energies_keV']
    W.require(all(support[0] <= row['second_backscatter_minimum_keV'] and row['incident_keV'] <= support[1]
                  for row in closure['lines']) and [row['incident_keV'] for row in closure['lines']] == energies,
              'Initialized coefficients must cover the exact global atom and continuation support')
    rates_at, total = bank.trial.rate_functions(rates)
    powers, seeds = (9, 12), (3100, 3101, 3102, 3103)
    selected = [(i, plan['selected_trials'][i]) for i in (1, 4)]
    accum = {(i, e): [] for i, _ in selected for e in energies}
    atom_info = {e: [] for e in energies}
    timings = []
    for seed in seeds:
        before = time.perf_counter()
        u = sobol_draws(seed, powers[-1])
        by_trial = [(i, ideal_shared.first_rays(crystal, trial['source_mm'], u)) for i, trial in selected]
        for e in energies:
            factors, sampled = empirical_factors(u, kernel, e, rates_at, total, support)
            atom_info[e].append(atom_census(seed, factors, sampled, powers))
            for i, ray in by_trial:
                rows, bound = ideal_shared.cached_exact_weights(crystal, ray, factors)
                accum[i, e].append(ideal_shared.seed_summary(seed, rows, ray, bound, powers))
        duration = time.perf_counter()-before
        timings.append(dict(seed=seed, seconds=duration))
        print(dict(seed=seed, seconds=duration), flush=True)
    cases = []
    for i, trial in selected:
        retained = next(case for case in prior['cases'] if case['trial'] == trial)
        trials = []
        for e in energies:
            checks = []
            old = next((line for line in retained['lines'] if line['incident_keV'] == e), None)
            if old is not None:
                for a,b in zip(accum[i, e],old['seed_results'],strict=True):
                    for x,y in zip(a['estimates'],b['estimates'],strict=True):
                        W.require(a['seed'] == b['seed'] and x['points'] == y['points'] and x['hit_rays'] == y['hit_rays'],
                                  'Use the original geometry scrambles and nested ray scopes')
                        difference = x['first_compton']-y['first_compton']
                        W.require(abs(difference) <= 8*np.finfo(float).eps*abs(y['first_compton']),
                                  'The unchanged first-Compton mass differs from the archived control')
                        checks.append(dict(seed=a['seed'], points=x['points'], first_compton_difference=difference,
                                           archived_free_topology_mass=y['contained_photoelectric']+y['known_compton_and_escape']))
            trials.append(dict(incident_keV=e, estimates=ideal_shared.summarize(accum[i, e], powers),
                               seed_results=accum[i, e], original_free_control_comparison=checks))
        cases.append(dict(trial_index=i, trial=trial, lines=trials))
    result = dict(kind='gegi_empirical_ideal_topology_normalization_pilot_v1', cases=cases,
                  input_sha256={k:W.sha(p) for k,p in inputs.items()}, base_rate_basis=basis, rate_extensions=bindings,
                  coefficient_support_keV=list(support), coefficients=len(rates),
                  atom_streams=[dict(incident_keV=e, scrambles=atom_info[e]) for e in energies],
                  sample_powers=powers, seeds=seeds, seed_cost_seconds=timings,
                  elapsed_seconds=time.perf_counter()-started, software=bank.software(),
                  source_sha256={Path(f).name:W.sha(f) for f in (__file__,sampling.__file__,joint.__file__,
                                                                ideal_shared.__file__,ideal.__file__)},
                  native_first_scatter_electron_rest_keV=closure['native_first_scatter_electron_rest_keV'],
                  canonical_second_scatter_electron_rest_keV=closure['free_second_scatter_electron_rest_keV'],
                  unsupported=closure['unrepresented_lines'],
                  measure='Dimensionless ideal topology probability per emitted photon. Original uniform solid-angle '
                          'proposal with 4*pi*p_emp first-angle weight and canonical KN at second scatter. Ninth atom '
                          'coordinate uses Sobol dimension nine scrambled with SeedSequence([seed, 9]); first eight '
                          'numbers are unchanged. Gaussian measurements integrate to one. No ADC selection or source fit.')
    with output.open('xb') as f:
        f.write(W.encoded(result)+b'\n')
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--probe', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    run(args.probe, args.output)
