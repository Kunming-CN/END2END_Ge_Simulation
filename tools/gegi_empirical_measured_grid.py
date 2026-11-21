"""Build measured empirical cobalt numerators and score the matching saved grid."""

import argparse
from collections import Counter
from contextlib import closing
import json
import math
from pathlib import Path
import sqlite3
import time
from types import SimpleNamespace

import numpy as np
from scipy.special import logsumexp

import gegi_empirical_compton_joint as joint
import gegi_empirical_energy_support as support_math
import gegi_empirical_escape_tails as tails
import gegi_escape_response_curve as curves
import gegi_normalized_source_diagnostic as scorer
import gegi_trial_joint_photon_response as arrival
import scenario_workflow as W


COBALT = (1173.228, 1332.492)
FIELDS = [f'log_{branch}_per_emitted_photon_mm6_keV2' for branch in ('absorption', 'escape')]


def read_curves(path):
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True)) as db:
        return {key: json.loads(row) for key, row in db.execute('SELECT curve,summary FROM curves')}


def context(probe):
    def file(name):
        return probe/name
    cfg = SimpleNamespace(reference=file('empirical-first-scatter-response-overlay-controls.json'),
        kernel=file('first-scatter-energy-kernel.json'), rate_support=file('empirical-first-scatter-rate-support-controls.json'),
        measured_plan=file('measured-response-plan.json'), plan=file('source-trial-response-plan.json'), probe=probe,
        new_rates=file('source-trial-rates'), bank=file('trial-escape-curve-bank.sqlite'),
        quadrature_extension=file('trial-escape-curve-repair512.sqlite'),
        coefficient_extension=file('empirical-first-scatter-rates'))
    _, required, parent, recipe, crystal, rates, coefficient_support = tails.setup(cfg)
    tail_path, tail_index = file('empirical-escape-tail-bank.sqlite'), file('empirical-escape-tail-controls.json')
    tail_receipt, tail_segments = W.read(tail_index), read_curves(tail_path)
    W.require(tail_receipt['recipe'] == recipe and tail_receipt['tail_bank_sha256'] == W.sha(tail_path) and
              tail_segments.keys() == required.keys() and all(x['status'] == tails.VERIFIED for x in tail_segments.values()),
              'Use the preserved independently verified six-point continuations')
    normal_path, joint_path = file('cached-empirical-normalization-full.json'), file('first-scatter-joint-controls.json')
    normal, reference = W.read(normal_path), W.read(joint_path)
    W.require(reference['baseline_recipe'] == recipe and reference['tail_bank_sha256'] == W.sha(tail_path) and
              normal['recipe']['inputs_sha256']['kernel'] == W.sha(cfg.kernel),
              'The measured numerator and normalizer must use the same empirical measure')
    extra = file('empirical-global-rates')
    query = W.read(extra/'request.json')
    basis = normal['recipe']['base_rate_basis']
    added, binding = joint.response.bank.trial.verified_extension(extra, W.sha(extra/'request.json'),
                                                                   basis['original_rate_basis'], query['new_query_energies_keV'])
    W.require(not rates.keys() & added.keys() and
              normal['recipe']['rate_extensions'] == [coefficient_support['coefficient_binding'], binding],
              'Use the same 225 initialized coefficients as normalization')
    rates |= added
    W.require(list(normal['recipe']['coefficient_support_keV']) == [min(rates), max(rates)], 'Rate support differs')
    arrival_path = file('trial-grid-joint-photon-response.json')
    indexed = W.read(arrival_path)
    arrays_path = arrival_path.parent/indexed['dataset']['name']
    measured = W.read(cfg.measured_plan)
    W.require(indexed['basis'] == basis and indexed['measured_triggers'] == measured['measured_triggers'] and
              indexed['measured_cohorts'] == measured['scoped_cohorts'] and W.sha(arrays_path) == indexed['dataset']['sha256'],
              'Use the sealed original measured geometry, cohort and first-arrival arrays')
    with np.load(arrays_path) as arrays:
        first_log = arrays['log_first_compton_per_emitted_photon_mm3']
        points, region = (arrays[k] for k in ('trial_positions_mm', 'trial_source_region'))
    W.require(np.array_equal(points, np.array([r['source_mm'] for r in normal['normalization_cases']])),
              'The matched normalizer uses different trial coordinates')
    kernel = W.read(cfg.kernel)
    masses = kernel['native_metadata']['native_electron_rest_keV'], joint.response.ELECTRON_REST_KEV
    W.require(masses == tuple(normal['recipe'][k] for k in ('native_first_scatter_electron_rest_keV',
              'canonical_second_scatter_electron_rest_keV')), 'Use the same first and second scatter masses')
    closed = {k: [row]+[tail_segments[k+':'+side] for side in ('lower', 'upper') if k+':'+side in tail_segments]
              for k, row in parent.items()}
    return SimpleNamespace(normalization=normal, reference=reference, indexed=indexed, first_log=first_log,
        points=points, region=region, kernel=kernel, rates=rates, crystal=crystal, closed=closed,
        sigma_first=W.read(cfg.plan)['sigma_first_keV'],
        inputs_sha256={Path(p).name: W.sha(p) for p in (cfg.kernel, normal_path, joint_path, arrival_path, arrays_path,
            tail_path, tail_index, cfg.plan, cfg.bank, cfg.quadrature_extension, extra/'execution.json')})


def cosine_at(model, points):
    first, second = (np.asarray(model[k]) for k in ('first_fitted_mm', 'second_fitted_mm'))
    axis = second-first
    length = math.hypot(*axis)
    direction = axis/length
    # Preserve the scalar dot order at calibrated curve endpoints. Batch
    # matmul can move an atom a few ulps outside an accepted endpoint.
    cosine = [(v/math.hypot(*v)) @ direction for v in first-points]
    return np.clip(cosine, -1., 1.), length


def angular_hats(kernel, incident, cosine):
    model = joint.angular_model(kernel, incident)
    bins = kernel['incident_groups'][kernel['incident_energies_keV'].index(incident)]['livermore_bins']
    for j, group in enumerate(bins):
        values = np.zeros(len(model['x']))
        values[j+1] = 1.
        if j == 0:
            values[0] = 1.
        if j == len(bins)-1:
            values[-1] = 1.
        h = np.interp(cosine, model['x'], values)
        use = np.flatnonzero(h > 0.)
        if use.size:
            atoms = np.asarray(group['development_residual_atoms'])
            yield use, h[use]*model['peaks'][j]/(2*math.pi), atoms


def compiled_segments(rows):
    model = rows[0]['model']
    segments = []
    for row in rows:
        if row['status'] == tails.VERIFIED:
            nodes = row['comparison']['nodes']
            segments.append(curves.EscapeResponseCurve([r['intermediate_keV'] for r in nodes],
                [r['log_escape_density'] for r in nodes], observed_keV=model['measured_second_site_keV'],
                sigma_keV=model['sigma_second_keV']))
    return segments


def branch_factors(kernel, incident, cosine, length, first_obs, sigma_first, model, segments, rate_vectors):
    values = np.full((2, len(cosine)), -np.inf)
    angular = np.zeros(len(cosine))
    unavailable = np.zeros(len(cosine))
    obs2, sig2 = (model[k] for k in ('measured_second_site_keV', 'sigma_second_keV'))
    mass = kernel['native_metadata']['native_electron_rest_keV']
    energies, log_photo, log_total = rate_vectors
    for use, angle, atoms in angular_hats(kernel, incident, cosine):
        for i in range(0, len(use), 256):
            ix, angular_factor = use[i:i+256], angle[i:i+256]
            free = support_math.kernel.free_outgoing(incident, cosine[ix], mass)[:, None]
            outgoing = support_math.transport(atoms, free, incident)
            log_e = np.log(outgoing)
            W.require(np.all((log_e >= energies[0]) & (log_e <= energies[-1])), 'An empirical atom exceeds the rate table')
            photo = np.interp(log_e, energies, log_photo)
            attenuation = length*np.exp(np.interp(log_e, energies, log_total))
            log_first = joint.response.log_gaussian(first_obs, incident-outgoing, sigma_first)
            common = log_first+(np.log(angular_factor/len(atoms))-2*math.log(length))[:, None]
            absorb = photo-attenuation+joint.response.log_gaussian(obs2, outgoing, sig2)
            escape = np.full(outgoing.shape, np.nan)
            for segment in segments:
                inside = np.isnan(escape) & (outgoing >= segment.nodes[0]) & (outgoing <= segment.nodes[-1])
                escape[inside] = segment.log_density(outgoing[inside])
            known = np.isfinite(escape)
            angular[ix] += angular_factor
            unavailable[ix] += angular_factor*np.count_nonzero(~known, axis=1)/len(atoms)
            values[0, ix] = np.logaddexp(values[0, ix], logsumexp(common+absorb, axis=1))
            values[1, ix] = np.logaddexp(values[1, ix], logsumexp(common+np.where(known, escape, -np.inf), axis=1))
    W.require(np.all(angular > 0.), 'The represented first-angle measure has no mass')
    values[1, unavailable > 0.] = np.nan
    return values, unavailable/angular


def evaluate(data, point_indices, extra=None):
    arrays = {f: np.full((len(data.indexed['branch_rows']), len(point_indices)), np.nan) for f in FIELDS}
    arrays['escape_unknown_atom_mass'] = np.full_like(arrays[FIELDS[0]], np.nan)
    rate_at = sorted(data.rates)
    rates = (np.log(rate_at), np.log([data.rates[e].photoelectric_per_mm for e in rate_at]),
             np.log([data.rates[e].total_per_mm for e in rate_at]))
    by_key = {}
    for k, rows in data.closed.items():
        added = [] if extra is None else [extra[k+':'+side] for side in ('lower', 'upper') if k+':'+side in extra]
        by_key[k] = compiled_segments(rows+added)
    for i, b in enumerate(data.indexed['branch_rows']):
        if b['incident_keV'] not in COBALT or b['geometry_status'] != 'available_geometry':
            continue
        first = data.first_log[i, point_indices]
        usable = np.isfinite(first)
        key = b['curve_key']
        model = data.closed[key][0]['model']
        c, length = cosine_at(model, data.points[point_indices[usable]])
        values, missing = branch_factors(data.kernel, b['incident_keV'], c, length,
                                        b['measured_first_site_keV'], data.sigma_first, model, by_key[key], rates)
        for k, v in zip(FIELDS, values, strict=True):
            arrays[k][i, usable] = v+first[usable]
        arrays['escape_unknown_atom_mass'][i, usable] = missing
    return arrays


def six_point_indices(data):
    n = len(data.indexed['trial_grid']['unit_vectors'])
    return np.asarray([r['radial_index']*n+r['direction_index'] for r in data.reference['selected_trials']])


def compare_six(data, arrays, column_indices):
    by_id = {arrival.identity(row): i for i, row in enumerate(data.indexed['branch_rows'])}
    errors = [[], []]
    points = six_point_indices(data)
    for s in data.reference['states']:
        i, j = by_id[arrival.identity(s)], s['trial_index']
        col = column_indices[j]
        for k, branch in enumerate(('absorption', 'escape')):
            expected = data.first_log[i, points[j]]+s['joint_log_factors'][branch]
            errors[k].append(abs(arrays[FIELDS[k]][i, col]-expected))
    worst = [max(a) for a in errors]
    W.require(all(np.isfinite(e).all() for e in errors) and all(e <= 2e-8 for e in worst),
              'The same six-point record must reproduce the stored joint densities without model changes')
    return dict(states=len(data.reference['states']), max_abs_log_difference=dict(zip(('absorption', 'escape'), worst)))


def score(data, arrays):
    cases = []
    for row in data.normalization['normalization_cases']:
        lines = [dict(line, uninitialized_exit_mass_analytic_upper_bound=max(
            est['uninitialized_exit_mass_analytic_upper_bound'] for s in line['seed_results'] for est in s['estimates']))
            for line in row['lines']]
        cases.append(dict(row, lines=lines, role='full_grid'))
    normalized = dict(normalization_cases=cases, trial_scope='full_declared_grid')
    return scorer.fit_blind(data.indexed, normalized,
        arrays | dict(trial_positions_mm=data.points, trial_source_region=data.region))


def write(path, value):
    with path.open('xb') as stream:
        stream.write(W.encoded(value)+b'\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--extensions', type=Path)
    args = parser.parse_args()
    W.require(not args.output.exists(), 'Choose a fresh empirical measured grid output')
    data = context(args.probe)
    six = six_point_indices(data)
    started = time.perf_counter()
    if args.extensions is None:
        arrays = evaluate(data, six)
        result = dict(kind='gegi_measured_empirical_grid_pilot_v1', comparison=compare_six(data, arrays, np.arange(len(six))),
                      evaluation_seconds=time.perf_counter()-started, input_sha256=data.inputs_sha256,
                      source_sha256=W.sha(__file__))
    else:
        from gegi_empirical_measured_extensions import read_extensions
        extra = read_extensions(data, args.extensions)
        arrays = evaluate(data, np.arange(len(data.points)), extra)
        accepted = compare_six(data, arrays, six)
        blind = score(data, arrays)
        arrays_path = args.output.with_suffix('.npz')
        with arrays_path.open('xb') as stream:
            np.savez_compressed(stream, **arrays)
        result = dict(kind='gegi_measured_empirical_grid_blind_v1', comparison=accepted, input_sha256=data.inputs_sha256,
            source_sha256=W.sha(__file__), extensions_sha256=W.sha(args.extensions),
            unsupported_incident_lines=data.normalization['recipe']['unsupported'], blind_sha256=W.digest(blind), measured_analysis=blind,
            dataset=dict(name=arrays_path.name, sha256=W.sha(arrays_path)), evaluation_seconds=time.perf_counter()-started,
            extension_statuses=dict(Counter(row['status'] for row in extra.values())))
    write(args.output, result)
    print(result['comparison'], result['evaluation_seconds'], flush=True)


if __name__ == '__main__':
    main()
