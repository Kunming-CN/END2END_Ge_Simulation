"""Build a resumable escape-response bank for the saved GeGI trial grid."""

import argparse
from collections import Counter
import math
from pathlib import Path
import platform
import sqlite3
import time

import numpy as np
import scipy

import gegi_candidate_trial_response as trial
import gegi_escape_response_curve as curve
import gegi_photon_continuation as photon
import scenario_workflow as W


KIND = 'gegi_saved_trial_escape_curve_bank_v1'
REFERENCE_FIELDS = ('intermediate_keV', 'log_escape_density', 'raw_escape_density', 'density_status',
                    'log_quadrature_difference')


def curve_identity(first, second, observation, sigma):
    return dict(first_fitted_mm=first, second_fitted_mm=second, measured_second_site_keV=observation, sigma_second_keV=sigma)


def producers():
    files = (__file__, trial.__file__, curve.__file__, trial.point.__file__, photon.__file__,
             curve.measured.__file__, curve.logarithms.__file__)
    return {Path(f).name:W.sha(f) for f in files}


def software():
    return dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__, sqlite=sqlite3.sqlite_version)


def setup(measured_path, plan_path, probe, extension):
    measured, plan = W.read(measured_path), W.read(plan_path)
    measured_sha, plan_sha = W.sha(measured_path), W.sha(plan_path)
    W.require(plan['kind'] == trial.PLAN_KIND and plan['measured_plan_sha256'] == measured_sha,
              'The trial grid uses different saved candidate records')
    rates, _, basis = trial.retained_rates(probe, measured_path, measured)
    W.require(plan['rate_basis'] == basis, 'The trial energy domain uses different coefficients')
    new, new_binding = trial.verified_extension(extension, plan_sha, basis, plan['rate_request']['new_query_energies_keV'])
    W.require(not (rates.keys() & new.keys()), 'Initialized coefficient energies must be distinct')
    rates |= new
    grid = plan['trial_grid']
    points = ((np.array(grid['radii_mm'])[:,None,None]*np.array(grid['unit_vectors']))+grid['origin_mm']).reshape(-1,3)
    crystal = photon.ge_halfspaces_from_gdml(probe/'geometry.gdml')
    basis = dict(measured_plan_sha256=measured_sha, trial_plan_sha256=plan_sha, original_rate_basis=basis,
                 new_rate_binding=new_binding, coefficients=len(rates), coefficient_support_keV=[min(rates),max(rates)])
    return measured, plan, basis, rates, crystal, points


def geometries(measured, plan, crystal, points, rate_bounds):
    low, high = rate_bounds
    keys, branches = {}, []
    for tid, pair, order, line, status in trial.scoped_branches(measured, crystal):
        branch = dict(original_trigger_id=tid, pair_index=pair['pair_index'], site_index_order=order['site_index_order'],
                      incident_keV=line['incident_line_keV'], prior_fixed_first_status=line['status'], geometry_status=status)
        branches.append(branch)
        if status != 'available_geometry':
            continue
        i, j = order['site_index_order']
        first, second = [pair['fitted_vertices_mm'][k] for k in (i,j)]
        obs_first, obs_second = [pair['measured_site_energies_keV'][k] for k in (i,j)]
        model = curve_identity(first, second, obs_second, plan['sigma_second_keV'])
        key = W.digest(model)
        branch.update(curve_key=key, measured_first_site_keV=obs_first)
        states = np.full((len(points),3), np.nan)
        ids = np.flatnonzero(np.any(points != first, axis=1))
        e0 = branch['incident_keV']
        for index in ids:
            state = trial.point.first_compton_state(points[index], first, second, e0)
            states[index] = (state['intermediate_keV'], state['first_scatter_cosine'], state['expected_first_deposit_keV'])
        e = states[:,0]
        escape_min = e/(1+2*e/photon.ELECTRON_REST_KEV)
        available = (escape_min>=low) & (e<=high)
        branch.update(states=states, escape_coefficients_available=available, first_vertex_distinct=np.isfinite(e))
        item = keys.setdefault(key,dict(model=model, supported_energies=[]))
        item['supported_energies'].append(e[available])
    for item in keys.values():
        energies = np.concatenate(item.pop('supported_energies'))
        item['energies'] = energies
        item['domain_keV'] = [float(energies.min()),float(energies.max())] if len(energies) else None
    return keys, branches


def reused_samples(paths, basis, settings, hashes, known):
    reuse = {}
    for path in paths:
        prior = W.read(path)
        for k in ('measured_plan_sha256','trial_plan_sha256','original_rate_basis','new_rate_binding'):
            W.require(prior[k] == basis[k], 'A previous curve used different inputs or material coefficients')
        for k in ('azimuth_samples','energy_order','sigma_second_keV'):
            W.require(prior['settings'][k] == settings[k], 'A previous curve used different numerical settings')
        for name in (trial.__file__, photon.__file__, curve.measured.__file__, curve.logarithms.__file__):
            name = Path(name).name
            W.require(prior['source_sha256'][name] == hashes[name], 'A previous curve used different direct producers')
        W.require(prior['software'] == {k:v for k,v in software().items() if k!='sqlite'},
                  'A previous curve used a different numerical environment')
        for b in prior['branches']:
            model = curve_identity(b['first_fitted_mm'],b['second_fitted_mm'],b['measured_second_site_keV'],settings['sigma_second_keV'])
            key = W.digest(model)
            if key not in known:
                continue
            saved = reuse.setdefault(key,dict(rows={}, nodes=set()))
            result = b['comparison']
            for row in result['nodes']+result['held_out']:
                e = row['intermediate_keV']
                reference = {k:row[k] for k in REFERENCE_FIELDS}
                W.require(saved['rows'].setdefault(e,reference)==reference, 'Retained direct responses disagree')
            saved['nodes'].update(r['intermediate_keV'] for r in result['nodes'])
    return reuse


def create_bank(db, receipt):
    with db:
        db.execute('CREATE TABLE IF NOT EXISTS manifest (id INTEGER PRIMARY KEY, recipe BLOB NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS samples (curve TEXT, energy REAL, response TEXT NOT NULL, seconds REAL, '
                   'PRIMARY KEY(curve,energy))')
        db.execute('CREATE TABLE IF NOT EXISTS curves (curve TEXT PRIMARY KEY, summary BLOB NOT NULL)')
        db.execute('INSERT OR IGNORE INTO manifest VALUES (1,?)', (W.encoded(receipt),))
        match = db.execute('SELECT recipe FROM manifest WHERE id=1').fetchone()[0]
        W.require(match == W.encoded(receipt), 'Resume requires identical trial plan, rate basis, software, settings and source bytes')


def build_curve(db, key, item, reused, crystal, rates_at, total, settings):
    import json

    previous = db.execute('SELECT summary FROM curves WHERE curve=?',(key,)).fetchone()
    if previous:
        return json.loads(previous[0])
    model, energies = item['model'], item['energies']
    if not len(energies) or item['domain_keV'][0] == item['domain_keV'][1]:
        summary = dict(status='curve_domain_unavailable', domain_keV=item['domain_keV'])
    else:
        lo, hi = item['domain_keV']
        first, second = model['first_fitted_mm'], model['second_fitted_mm']
        obs, sigma = model['measured_second_site_keV'], model['sigma_second_keV']
        kwargs = {k:settings[k] for k in ('azimuth_samples','energy_order')}
        seeded = reused.get(key,dict(rows={},nodes=set()))
        base = curve.response_nodes(lo,hi,obs,sigma,settings['base_knots'])
        seed_nodes = sorted(e for e in seeded['nodes'] if lo<=e<=hi)
        if seed_nodes:
            nodes = np.unique(np.r_[lo,hi,base[(base<seed_nodes[0]) | (base>seed_nodes[-1])],seed_nodes])
        else:
            nodes = base
        with db:
            db.executemany('INSERT OR IGNORE INTO samples VALUES (?,?,?,NULL)',
                           [(key,e,W.encoded(row)) for e,row in seeded['rows'].items() if lo<=e<=hi])
        cache = {e:json.loads(row) for e,row in db.execute('SELECT energy,response FROM samples WHERE curve=?',(key,))}

        def references(es):
            for e in es:
                if e not in cache:
                    before = time.perf_counter()
                    row, = curve.direct_logs([e],crystal,first,second,obs,rates_at,total,sigma_keV=sigma,**kwargs)
                    with db:
                        db.execute('INSERT INTO samples VALUES (?,?,?,?)',(key,e,W.encoded(row),time.perf_counter()-before))
                    cache[e] = row
            return [cache[e] for e in es]

        trace = []
        target = settings['max_log_error_target']
        while True:
            held_out = np.array([independent_energy(a,b,seeded['rows']) for a,b in zip(nodes[:-1],nodes[1:],strict=True)])
            result = curve.compare(references(nodes),references(held_out),energies,obs,sigma,target)
            if result['max_direct_log_quadrature_difference'] > target:
                status = 'direct_quadrature_accuracy_unresolved'
                break
            failed = [r['intermediate_keV'] for r in result['held_out'] if abs(r['log_error'])>target]
            if not failed:
                status = 'verified_heldout_curve'
                break
            trace.append(dict(max_absolute_log_error=result['max_absolute_log_error'],promoted_keV=failed))
            nodes = np.sort(np.r_[nodes,failed])
        computed, seconds = db.execute('SELECT COUNT(*),COALESCE(SUM(seconds),0) FROM samples WHERE curve=? AND seconds IS NOT NULL',
                                       (key,)).fetchone()
        summary = dict(status=status, domain_keV=item['domain_keV'], model=model, comparison=result, refinement_passes=trace,
                       computed_direct_points=computed, retained_direct_points=len(cache)-computed, direct_seconds=seconds)
    with db:
        db.execute('INSERT INTO curves VALUES (?,?)',(key,W.encoded(summary)))
    return summary


def independent_energy(a,b,used):
    e = (a+b)/2
    while e in used and a < e < b:
        e = (a+e)/2
    W.require(a < e < b, 'No independent within-interval energy remains at floating-point precision')
    return e


def build(args):
    started = time.perf_counter()
    measured, plan, basis, rates, crystal, points = setup(args.measured_plan,args.plan,args.probe,args.new_rates)
    keys, branches = geometries(measured,plan,crystal,points,basis['coefficient_support_keV'])
    shape = Counter(b['geometry_status'] for b in branches)
    settings = dict(sigma_second_keV=plan['sigma_second_keV'], base_knots=args.base_knots,
                    azimuth_samples=args.azimuth_samples, energy_order=args.energy_order, max_log_error_target=args.max_log_error)
    hashes = producers()
    prior = reused_samples(args.reuse,basis,settings,hashes,keys)
    manifest = dict(kind=KIND, basis=basis, source_sha256=hashes, software=software(), settings=settings,
                    reused_results_sha256=[W.sha(p) for p in args.reuse],
                    curves={k:dict(model=v['model'], domain_keV=v['domain_keV']) for k,v in keys.items()})
    rates_at, total = trial.rate_functions(rates)
    stats = Counter()
    print(dict(unique_curves=len(keys), original_branch_slots=dict(shape), grid_points=len(points), reused_curves=len(prior)),flush=True)
    with sqlite3.connect(args.bank) as db:
        create_bank(db,manifest)
        for i,(key,item) in enumerate(keys.items(),1):
            result = build_curve(db,key,item,prior,crystal,rates_at,total,settings)
            stats[result['status']] += 1
            report = result.get('comparison',{})
            print(dict(curve=i,total=len(keys),key=key,status=result['status'], max_log_error=report.get('max_absolute_log_error'),
                       direct_points=result.get('computed_direct_points',0),direct_seconds=result.get('direct_seconds',0)),flush=True)
    print(dict(bank_status=dict(stats), invocation_elapsed_seconds=time.perf_counter()-started),flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('measured-plan','plan','probe','new-rates','bank'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--reuse',type=Path,action='append',default=[])
    parser.add_argument('--base-knots',type=int,default=25)
    parser.add_argument('--azimuth-samples',type=int,default=256)
    parser.add_argument('--energy-order',type=int,default=256)
    parser.add_argument('--max-log-error',type=float,default=.01)
    args = parser.parse_args()
    if not math.isfinite(args.max_log_error) or args.max_log_error<=0:
        parser.error('Supply a positive finite log-error target')
    build(args)


if __name__=='__main__':
    main()
