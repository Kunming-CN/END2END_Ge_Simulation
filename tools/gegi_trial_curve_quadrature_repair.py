"""Continue only unresolved escape curves using a higher observation quadrature order."""

import argparse
from collections import Counter
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import time

import numpy as np

import gegi_candidate_trial_curve_bank as bank
import scenario_workflow as W


KIND = 'gegi_saved_trial_escape_quadrature_extension_v1'
UNRESOLVED = 'direct_quadrature_accuracy_unresolved'


def pending_curves(rows):
    return {k:v for k,v in rows.items() if v['status']==UNRESOLVED}


def extension_recipe(source_hash, prior, pending, order):
    return dict(kind=KIND, parent_bank_sha256=source_hash, basis=prior['basis'], pending_keys=sorted(pending),
        old_settings=prior['settings'], settings=prior['settings'] | {'energy_order':order},
        software=bank.software(), source_sha256=bank.producers() | {Path(__file__).name:W.sha(__file__)})


def read_extension(path, parent_hash, prior, rows):
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        recipe = json.loads(db.execute('SELECT recipe FROM manifest WHERE id=1').fetchone()[0])
        results = {k:json.loads(v) for k,v in db.execute('SELECT curve,summary FROM curves')}
    pending = pending_curves(rows)
    expected = extension_recipe(parent_hash,prior,pending,recipe['settings']['energy_order'])
    W.require(recipe==expected and pending.keys()==results.keys(), 'Use a completed quadrature extension of the same bank')
    return recipe,results


def direct_reference(e, prior, target, low, high, evaluate):
    """Keep a passing low-order result, or retain it alongside the higher-order convergence check."""
    first = evaluate(e,low) if prior is None else prior
    if first['log_quadrature_difference']<=target:
        return dict(first,energy_order=low)
    return dict(evaluate(e,high),energy_order=high,lower_order_reference=first)


def repair_curve(db, key, initial, item, saved, evaluate, low, high, target):
    prior = db.execute('SELECT summary FROM curves WHERE curve=?',(key,)).fetchone()
    if prior is not None:
        return json.loads(prior[0])
    nodes = np.array([r['intermediate_keV'] for r in initial['comparison']['nodes']])
    passing = {e:r for e,r in saved.items() if r['log_quadrature_difference']<=target}
    with db:
        db.executemany('INSERT OR IGNORE INTO samples VALUES (?,?,?,NULL)',
                       [(key,e,W.encoded(row)) for e,row in passing.items()])
    cache = {e:json.loads(r) for e,r in db.execute('SELECT energy,response FROM samples WHERE curve=?',(key,))}

    def references(values):
        for e in values:
            if e not in cache:
                start = time.perf_counter()
                row = direct_reference(e,saved.get(e),target,low,high,evaluate)
                with db:
                    db.execute('INSERT INTO samples VALUES (?,?,?,?)',(key,e,W.encoded(row),time.perf_counter()-start))
                cache[e] = row
        return [cache[e] for e in values]

    model = item['model']
    obs, sigma = model['measured_second_site_keV'], model['sigma_second_keV']
    trace = []
    while True:
        held_out = [bank.independent_energy(a,b,{}) for a,b in zip(nodes[:-1],nodes[1:],strict=True)]
        comparison = bank.curve.compare(references(nodes),references(held_out),item['energies'],obs,sigma,target)
        if comparison['max_direct_log_quadrature_difference']>target:
            status = UNRESOLVED
            break
        bad = [r['intermediate_keV'] for r in comparison['held_out'] if abs(r['log_error'])>target]
        if not bad:
            status = 'verified_heldout_curve'
            break
        trace.append(dict(promoted_keV=bad,max_absolute_log_error=comparison['max_absolute_log_error']))
        nodes = np.sort(np.r_[nodes,bad])
    count, seconds = db.execute('SELECT COUNT(*),COALESCE(SUM(seconds),0) FROM samples WHERE curve=? AND seconds IS NOT NULL',
                                (key,)).fetchone()
    result = dict(status=status, model=model, domain_keV=item['domain_keV'], comparison=comparison, refinement_passes=trace,
                  retained_direct_points=len(passing), computed_direct_points=count, direct_seconds=seconds,
                  higher_order_points=sum(r.get('energy_order')==high for r in cache.values()),
                  old_convergence_failures_keV=sorted(e for e in saved if e not in passing))
    with db:
        db.execute('INSERT INTO curves VALUES (?,?)',(key,W.encoded(result)))
    return result


def repair(args):
    started = time.perf_counter()
    W.require(args.parent.resolve()!=args.output.resolve(), 'The original curve bank must remain intact')
    source_hash = W.sha(args.parent)
    measured, plan, basis, rates, crystal, points = bank.setup(args.measured_plan,args.plan,args.probe,args.new_rates)
    keys,_ = bank.geometries(measured,plan,crystal,points,basis['coefficient_support_keV'])
    with closing(sqlite3.connect(args.parent.resolve().as_uri()+'?mode=ro',uri=True)) as parent:
        prior = json.loads(parent.execute('SELECT recipe FROM manifest WHERE id=1').fetchone()[0])
        rows = {k:json.loads(v) for k,v in parent.execute('SELECT curve,summary FROM curves')}
        W.require(rows.keys()==keys.keys() and prior['basis']==basis and prior['source_sha256']==bank.producers() and
            prior['software']==bank.software() and W.sha(args.parent)==source_hash,
            'Only extend the completed original curve bank and numerical producers')
        W.require(args.energy_order>prior['settings']['energy_order'], 'Use a strictly higher direct quadrature order')
        pending = pending_curves(rows)
        receipt = extension_recipe(source_hash,prior,pending,args.energy_order)
        settings, low = receipt['settings'], prior['settings']['energy_order']
        rates_at,total = bank.trial.rate_functions(rates)
        states = Counter()
        with closing(sqlite3.connect(args.output)) as extension:
            bank.create_bank(extension,receipt)
            for key,row in pending.items():
                saved = {e:json.loads(raw) for e,raw in parent.execute('SELECT energy,response FROM samples WHERE curve=?',(key,))}
                model = keys[key]['model']
                def evaluate(energy,order):
                    value, = bank.curve.direct_logs([energy],crystal,model['first_fitted_mm'],model['second_fitted_mm'],
                        model['measured_second_site_keV'],rates_at,total,sigma_keV=model['sigma_second_keV'],
                        azimuth_samples=settings['azimuth_samples'],energy_order=order)
                    return value

                result = repair_curve(extension,key,row,keys[key],saved,evaluate,low,args.energy_order,settings['max_log_error_target'])
                states[result['status']] += 1
                print(dict(key=key,status=result['status'],old_convergence_failures_keV=result['old_convergence_failures_keV'],
                    reused_points=result['retained_direct_points'], fresh_points=result['computed_direct_points'],
                    higher_order_points=result['higher_order_points'],
                    reference_max_log_difference=result['comparison']['max_direct_log_quadrature_difference'],
                    heldout_max_log_difference=result['comparison']['max_absolute_log_error']),flush=True)
    print(dict(curves_repaired=dict(states), invocation_elapsed_seconds=time.perf_counter()-started,
               original_bank_sha256=source_hash),flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('measured-plan','plan','probe','new-rates','parent','output'):
        p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--energy-order',type=int,required=True)
    repair(p.parse_args())


if __name__=='__main__':
    main()
