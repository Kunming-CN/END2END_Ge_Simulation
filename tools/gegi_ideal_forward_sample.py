"""Forward-sample the ideal free-electron two-interaction Ge model.

Each attempt emits into the existing enclosing cone, with its exact fraction
of isotropic solid angle recorded. Simulate ordinary untruncated exponential
flights and competing reactions. Accept first-Compton/photoelectric or
first-Compton/second-Compton with uncollided Ge exit. Independent Gaussian
energy observations and randomized labels have their own PCG64 stream.
"""

import argparse
from collections import Counter
import math
from pathlib import Path
import time

import numpy as np

import gegi_ideal_two_interaction_mass as ideal
import scenario_workflow as W


def draw_compton(rng, incident):
    """Sample KN cosine by rejection of its exact unnormalized differential."""
    while True:
        x, u = rng.random(2)
        x *= 2
        outgoing = ideal.outgoing_energy(incident, x)
        ratio = outgoing/incident
        # k^3 + k <= 2 and the subtracted sin^2 term is nonnegative.
        if 2*u < ratio**2*(ratio+1/ratio-x*(2-x)):
            return outgoing, x, 2*math.pi*rng.random()


def flight(rng, rates, chord):
    if chord == 0. or rates.total_per_mm == 0.:
        return 'exit', None
    depth = float(rng.exponential(1/rates.total_per_mm))
    if depth >= chord:
        return 'exit', None
    channel = rng.random()*rates.total_per_mm
    if channel < rates.compton_per_mm:
        return 'compton', depth
    if channel < rates.compton_per_mm+rates.photoelectric_per_mm:
        return 'photoelectric', depth
    return 'other', depth


def attempt(rng, crystal, source, incoming, start, chord, incident, rate_at, interval):
    if chord == 0.:
        return 'cone_miss', None
    reaction, d1 = flight(rng, rate_at(incident), chord)
    if reaction != 'compton':
        return 'first_'+reaction, None
    first = source+(start+d1)*incoming
    intermediate, x1, phi1 = draw_compton(rng, incident)
    direction = ideal.directions(incoming, x1, phi1)
    _, chord1 = ideal.ray_intervals(crystal, first, direction)
    reaction, d2 = flight(rng, rate_at(intermediate), chord1)
    if reaction in ('exit', 'other'):
        return 'second_'+reaction, None
    second = first+d2*direction
    truth = dict(ordered_vertices_mm=[first.tolist(), second.tolist()],
                 incident_direction=incoming.tolist(), intermediate_direction=direction.tolist(),
                 incoming_ge_chord_mm=float(chord), ge_entry_distance_mm=float(start),
                 first_travel_ge_mm=d1, second_ge_chord_mm=float(chord1), second_travel_ge_mm=d2,
                 first_scatter_cosine=float(1-x1), intermediate_energy_keV=float(intermediate))
    if reaction == 'photoelectric':
        final, label = 0., 'absorption'
    else:
        final, x2, phi2 = draw_compton(rng, intermediate)
        exiting = ideal.directions(direction, x2, phi2)
        _, chord2 = ideal.ray_intervals(crystal, second, exiting)
        truth.update(second_scatter_cosine=float(1-x2), exiting_direction=exiting.tolist(),
                     exit_ge_chord_mm=float(chord2), final_photon_energy_keV=float(final))
        if not interval[0] <= final <= interval[1]:
            return 'exit_coefficients_unavailable', truth
        follow, _ = flight(rng, rate_at(final), chord2)
        if follow != 'exit':
            return 'third_ge_interaction', None
        label = 'escape'
    truth.update(deposited_energy_keV=[float(incident-intermediate), float(intermediate-final)],
                 exiting_energy_keV=float(final))
    return label, truth


def sample_cohort(crystal, source, incident, sigmas, count, seed, cohort_id, rate_at, interval, pilot):
    streams = np.random.SeedSequence(seed).spawn(2)
    rng, observations_rng = (np.random.Generator(np.random.PCG64(s)) for s in streams)
    source = np.asarray(source, dtype=float)
    counters = Counter()
    events, truth, failures = [], [], []
    attempt_id = 0
    started = time.perf_counter()
    pilot_result = None
    while len(events) < count:
        ray, fraction = ideal.incoming_rays(crystal, source, rng.random((1, 2)))
        incoming, = ray
        start, chord = ideal.ray_intervals(crystal, source, incoming)
        label, record = attempt(rng, crystal, source, incoming, start, chord, incident, rate_at, interval)
        counters[label] += 1
        if label in ('absorption', 'escape'):
            permutation = [0, 1] if observations_rng.integers(2) == 0 else [1, 0]
            deposited = np.asarray(record['deposited_energy_keV'])
            observed = deposited[permutation]+observations_rng.normal(0., sigmas)
            events.append(dict(attempt_id=attempt_id,
                               site_positions_mm=[record['ordered_vertices_mm'][j] for j in permutation],
                               observed_site_energies_keV=observed.tolist()))
            truth.append(dict(attempt_id=attempt_id, accepted_branch=label, label_to_ordered_site=permutation, **record))
            if len(events) == pilot:
                pilot_result = dict(accepted=pilot, emitted_in_cone=attempt_id+1,
                                    elapsed_seconds=time.perf_counter()-started)
                print(dict(cohort=cohort_id, pilot=pilot_result), flush=True)
        elif record is not None:
            failures.append(dict(attempt_id=attempt_id, reason=label, **record))
        attempt_id += 1
    entered = attempt_id-counters['cone_miss']
    W.require(sum(counters.values()) == attempt_id and counters['absorption']+counters['escape'] == count,
              'The attempt and topology denominators must reconcile')
    accounting = dict(cohort_id=cohort_id, emitted_cone_fraction_of_4pi=float(fraction),
                      emitted_in_cone=attempt_id, entered_ge=entered, accepted=count,
                      rejected_after_entry=entered-count, run_counts=dict(counters),
                      accepted_attempt_ids=[r['attempt_id'] for r in events],
                      seed=seed, pcg64_spawn_keys=[list(s.spawn_key) for s in streams],
                      measured_prefix=pilot_result, elapsed_seconds=time.perf_counter()-started)
    return dict(cohort_id=cohort_id, events=events), dict(cohort_id=cohort_id, source_mm=source.tolist(),
                accepted_events=truth, unique_failures=failures), accounting


def run(args):
    bank = ideal.bank
    _, _, basis, coefficients, crystal, _ = bank.setup(args.measured_plan, args.plan, args.probe, args.new_rates)
    interval = basis['coefficient_support_keV']
    rate_at, _ = bank.trial.rate_functions(coefficients)
    incident, sigmas = args.incident_kev, args.sigma_site_kev
    minimum = ideal.outgoing_energy(ideal.outgoing_energy(incident, 2.), 2.)
    W.require(interval[0] <= minimum <= incident <= interval[1],
              'The declared line needs complete initialized coefficients through two successive backscatters')
    W.require(len(args.source_mm) == len(args.seed) and len(set(args.seed)) == len(args.seed),
              'Supply one distinct seed for each source')
    normals, offsets = crystal
    W.require(all(np.isfinite(s).all() and np.max(normals @ s-offsets) > 0. for s in args.source_mm),
              'The declared pilot sources must be external to Ge')
    W.require(args.accepted > 0 and 0 < args.pilot_accepted <= args.accepted and
              all(math.isfinite(s) and s > 0. for s in sigmas), 'Supply positive counts and Gaussian widths')
    args.output.mkdir(parents=True, exist_ok=False)
    cohorts, truth_cohorts, counts = [], [], []
    for i, (source, seed) in enumerate(zip(args.source_mm, args.seed, strict=True)):
        events, truth, count = sample_cohort(crystal, source, incident, sigmas, args.accepted, seed, f'cohort-{i+1}',
                                            rate_at, interval, args.pilot_accepted)
        cohorts.append(events)
        truth_cohorts.append(truth)
        counts.append(count)
    observed = dict(kind='gegi_ideal_forward_observations_v1', incident_keV=incident,
                    sigma_site_keV=sigmas, coefficient_basis=basis, cohorts=cohorts)
    observations_path = args.output/'observations.json'
    with observations_path.open('xb') as stream:
        stream.write(W.encoded(observed)+b'\n')
    observations_sha = W.sha(observations_path)
    for filename, payload in (
            ('truth.json', dict(kind='gegi_ideal_forward_truth_v1', observations_sha256=observations_sha,
                                cohorts=truth_cohorts)),
            ('execution.json', dict(kind='gegi_ideal_forward_acceptance_v1', observations_sha256=observations_sha,
                    incident_keV=incident, sigma_site_keV=sigmas, coefficient_basis=basis, cohorts=counts,
                    source_sha256={Path(p).name: W.sha(p) for p in (__file__, ideal.__file__)}, software=bank.software(),
                    scope='Independent pseudorandom ideal homogeneous-Ge forward sampler. Attempts condition on the enclosing cone. '
                          'No passive materials, Geant4 transport, finite vertex resolution, ADC selection or calibrated performance.'))):
        with (args.output/filename).open('xb') as stream:
            stream.write(W.encoded(payload)+b'\n')
    print(dict(incident_keV=incident, cohorts=counts), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('measured-plan', 'plan', 'probe', 'new-rates', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--incident-kev', type=float, required=True)
    parser.add_argument('--sigma-site-kev', type=float, nargs=2, required=True)
    parser.add_argument('--source-mm', type=float, nargs=3, action='append', required=True)
    parser.add_argument('--seed', type=int, action='append', required=True)
    parser.add_argument('--accepted', type=int, required=True)
    parser.add_argument('--pilot-accepted', type=int, default=10)
    run(parser.parse_args())


if __name__ == '__main__':
    main()
