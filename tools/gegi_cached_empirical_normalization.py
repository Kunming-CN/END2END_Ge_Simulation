"""Reuse the verified empirical angular-energy factors across the cobalt source grid."""

import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import time

import numpy as np

import gegi_empirical_topology_normalization as empirical
import scenario_workflow as W


COBALT = (1173.228, 1332.492)
KIND = 'gegi_cached_empirical_topology_normalizer_v1'


def prepare_streams(kernel, energies, powers, seeds, coefficients):
    bank = empirical.ideal_shared.ideal.bank
    rate_at, outgoing_total = bank.trial.rate_functions(coefficients)
    support = min(coefficients), max(coefficients)
    result = []
    for seed in seeds:
        u = empirical.sobol_draws(seed, powers[-1])
        factors = {e: empirical.empirical_factors(u, kernel, e, rate_at, outgoing_total, support)[0]
                   for e in energies}
        result.append((seed, u, factors))
    return result


def evaluate_point(crystal, point, streams, powers):
    shared = empirical.ideal_shared
    samples = {incident: [] for incident in streams[0][2]}
    for seed, u, factors in streams:
        ray = shared.first_rays(crystal, point['source_mm'], u)
        for incident, factors_at_energy in factors.items():
            rows, bound = shared.cached_exact_weights(crystal, ray, factors_at_energy)
            samples[incident].append(shared.seed_summary(seed, rows, ray, bound, powers))
    return dict(point, lines=[dict(incident_keV=e, estimates=shared.summarize(by_seed, powers), seed_results=by_seed)
                              for e, by_seed in samples.items()])


def exact_pilot_comparison(rows, original):
    checks = []
    for saved in original['cases']:
        match, = (row for row in rows if row['source_mm'] == saved['trial']['source_mm'])
        for old in saved['lines']:
            if old['incident_keV'] not in COBALT:
                continue
            actual, = (row for row in match['lines'] if row['incident_keV'] == old['incident_keV'])
            W.require(actual['seed_results'] == old['seed_results'] and actual['estimates'] == old['estimates'],
                      'Cached empirical results must exactly reproduce every retained pilot mass')
            checks.append(dict(trial_index=saved['trial_index'], grid_index=match['grid_index'],
                               incident_keV=actual['incident_keV'],
                               matched_nested_scramble_rows=sum(len(r['estimates']) for r in actual['seed_results'])))
    return checks


def open_checkpoint(db, recipe):
    expected = W.encoded(recipe)
    with db:
        db.execute('CREATE TABLE IF NOT EXISTS manifest (recipe BLOB NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS points (grid_index INTEGER PRIMARY KEY, result BLOB NOT NULL)')
        saved = db.execute('SELECT recipe FROM manifest').fetchall()
        if not saved:
            db.execute('INSERT INTO manifest VALUES (?)', (expected,))
        else:
            W.require(saved == [(expected,)], 'The checkpoint belongs to a different model or exact Sobol grid')


def batch_points(db, points, crystal, streams, powers):
    existing = {i for i, in db.execute('SELECT grid_index FROM points')}
    missing = [p for p in points if p['grid_index'] not in existing]
    for offset in range(0, len(missing), 24):
        committed = [evaluate_point(crystal, p, streams, powers) for p in missing[offset:offset+24]]
        with db:
            db.executemany('INSERT INTO points VALUES (?,?)',
                           [(p['grid_index'], W.encoded(p)) for p in committed])
        if (offset+len(committed)) % 240 == 0:
            print(dict(new_committed=offset+len(committed), requested=len(missing)), flush=True)
    rows = []
    for point in points:
        raw, = db.execute('SELECT result FROM points WHERE grid_index=?', (point['grid_index'],)).fetchone()
        current = json.loads(raw)
        W.require(all(current[k] == v for k, v in point.items()), 'Checkpoint source point does not match the grid')
        rows.append(current)
    return rows, len(missing)


def write(path, result):
    with path.open('xb') as stream:
        stream.write(W.encoded(result)+b'\n')


def run(probe, pilot_output, output, checkpoint):
    W.require(not output.exists() and len({path.resolve() for path in (pilot_output, output, checkpoint)}) == 3,
              'Select new full-grid output and separate pilot and checkpoint paths')
    start = time.perf_counter()
    bank = empirical.ideal_shared.ideal.bank
    _, plan, basis, original, crystal, positions = bank.setup(probe/'measured-response-plan.json',
        probe/'source-trial-response-plan.json', probe, probe/'source-trial-rates')
    files = {key: probe/name for key, name in (
        ('kernel', 'first-scatter-energy-kernel.json'), ('support', 'first-scatter-global-support.json'),
        ('empirical_reference', 'empirical-topology-normalization-pilot.json'),
        ('free_grid_design', 'shared-ideal-topology-normalization-pilot.json'))}
    kernel, closure, saved, grid_design = (W.read(f) for f in files.values())
    W.require(saved['base_rate_basis'] == grid_design['basis'] == closure['base_rate_basis'] == basis and
              W.sha(files['kernel']) == saved['input_sha256']['kernel'] == closure['empirical_kernel_sha256'] and
              W.sha(files['support']) == saved['input_sha256']['support'] and
              W.sha(empirical.__file__) == saved['source_sha256'][Path(empirical.__file__).name],
              'Use exactly the accepted angular-energy kernel, pilot and initialized rates')
    powers, seeds = saved['sample_powers'], saved['seeds']
    W.require(powers == grid_design['sample_powers'] and seeds == grid_design['seed'], 'Shared pilot scramble scopes differ')
    rates, bindings = empirical.merge_rates(probe, basis, original, closure)
    W.require(bindings == saved['rate_extensions'] and [min(rates), max(rates)] == saved['coefficient_support_keV'] and
              len(rates) == saved['coefficients'], 'The matching coefficient tables changed')
    n = len(plan['trial_grid']['unit_vectors'])
    normals, offsets = crystal
    points = []
    for index, p in enumerate(positions):
        margin = float(np.min(offsets-normals@p))
        region = 'outside_ge' if margin < -1e-9 else 'ge_boundary' if margin <= 1e-9 else 'inside_ge'
        points.append(dict(grid_index=index, radial_index=index//n, direction_index=index % n,
                           source_mm=p.tolist(), source_region=region))
    pilot_points = [points[p['grid_index']] for p in grid_design['normalization_cases']]
    W.require(len(pilot_points) == 13 and all(all(q[k] == p[k] for k in q) for q,p in
              zip(pilot_points, grid_design['normalization_cases'], strict=True)), 'Use the previously declared 13-point grid design')
    prep_start = time.perf_counter()
    streams = prepare_streams(kernel, COBALT, powers, seeds, rates)
    preparation_seconds = time.perf_counter()-prep_start
    recipe = dict(kind=KIND, inputs_sha256={key:W.sha(f) for key,f in files.items()}, source_sha256={
                    Path(f).name:W.sha(f) for f in (__file__, empirical.__file__, empirical.ideal_shared.__file__)},
                  base_rate_basis=basis, rate_extensions=bindings, coefficient_support_keV=[min(rates),max(rates)],
                  line_energies_keV=list(COBALT), reference_only_energy_keV=662., unsupported=saved['unsupported'],
                  native_first_scatter_electron_rest_keV=saved['native_first_scatter_electron_rest_keV'],
                  canonical_second_scatter_electron_rest_keV=saved['canonical_second_scatter_electron_rest_keV'],
                  seeds=seeds, sample_powers=powers, software=bank.software(),
                  stream_sha256={str(seed):hashlib.sha256(u.astype('<f8').tobytes()).hexdigest()
                                 for seed,u,_ in streams},
                  measure=saved['measure'])
    with closing(sqlite3.connect(checkpoint)) as db:
        open_checkpoint(db, recipe)
        began = time.perf_counter()
        pilot, new_pilot = batch_points(db, pilot_points, crystal, streams, powers)
        pilot_science = dict(recipe=recipe, normalization_cases=pilot, exact_pilot_comparisons=exact_pilot_comparison(pilot, saved))
        if pilot_output.exists():
            W.require(W.read(pilot_output)['science'] == pilot_science, 'A different pilot receipt already exists')
        else:
            write(pilot_output, dict(science=pilot_science, cache_preparation_seconds=preparation_seconds,
                                     pilot_geometry_and_checkpoint_seconds=time.perf_counter()-began,
                                     newly_computed_points=new_pilot))
        print(dict(pilot_sha256=W.sha(pilot_output), new_pilot_points=new_pilot,
                   preparation_seconds=preparation_seconds,
                   pilot_geometry_seconds=time.perf_counter()-began), flush=True)
        began = time.perf_counter()
        complete, new_full = batch_points(db, points, crystal, streams, powers)
        whole_seconds = time.perf_counter()-began
    W.require(all(complete[p['grid_index']] == p for p in pilot), 'The full grid changed the verified pilot')
    write(output, dict(kind=KIND, recipe=recipe, exact_pilot_sha256=W.sha(pilot_output),
                       checkpoint_sha256=W.sha(checkpoint), normalization_cases=complete,
                       cache_preparation_calls=len(streams)*len(COBALT), cache_preparation_seconds=preparation_seconds,
                       full_geometry_and_checkpoint_seconds=whole_seconds, newly_computed_full_points=new_full,
                       elapsed_seconds=time.perf_counter()-start))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for option in ('probe', 'pilot-output', 'output', 'checkpoint'):
        p.add_argument('--'+option, type=Path, required=True)
    a = p.parse_args()
    run(a.probe, a.pilot_output, a.output, a.checkpoint)
