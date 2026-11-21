"""Extend observed escape-curve sides using saved direct endpoint references."""

import argparse
from collections import defaultdict
from contextlib import closing
import json
import math
from pathlib import Path
import sqlite3
import time

import numpy as np

import gegi_ideal_forward_continuous as continuous
import gegi_ideal_forward_fast_bank as fast
import gegi_ideal_forward_reconstruction as forward
import gegi_ideal_forward_score as fixed
import gegi_photon_continuation as photon
import scenario_workflow as W


KIND = 'gegi_ideal_forward_saved_endpoint_curve_extensions_v1'


def bounds(incident):
    return incident/(1+2*(incident/photon.ELECTRON_REST_KEV)),incident


def read_database(path):
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        recipe = json.loads(db.execute('SELECT recipe FROM manifest WHERE id=1').fetchone()[0])
        samples = {(k,e):json.loads(row) for k,e,row in db.execute('SELECT curve,energy,response FROM samples')}
    return recipe,samples


def load_inputs(args):
    obs,plan,basis,rates,crystal,points,cohorts,keys,branches = forward.inputs(args)
    obs_hash = W.sha(args.observations)
    bank_hash,overlay_hash = W.sha(args.bank),W.sha(args.curve_overlay)
    info,rows = fixed.load_bank(args.bank,obs_hash,basis,keys,cohorts)
    _,added = fixed.overlay.replacements(args.curve_overlay,bank_hash,info,rows)
    rows |= added
    endpoint_hash = W.sha(args.saved_endpoints)
    prior,samples = read_database(args.saved_endpoints)
    W.require(prior['basis']==basis and prior['observation_sha256']==obs_hash and prior['curve_bank_sha256']==bank_hash and
        prior['overlay_sha256']==overlay_hash and prior['source_sha256'][Path(fast.gaussian.__file__).name]==
        W.sha(fast.gaussian.__file__), 'Use the original exact endpoint samples and curve banks')
    bindings = dict(basis=basis,observation_sha256=obs_hash,curve_bank_sha256=bank_hash,overlay_sha256=overlay_hash,
                    old_endpoint_store_sha256=endpoint_hash,endpoint_settings=prior['settings'])
    return obs,plan,rates,crystal,points,cohorts,keys,branches,rows,samples,bindings


def curves_for(sides):
    m = sides['model']
    result = {}
    for side,item in sides['extensions'].items():
        if item['status']=='verified_extension':
            nodes = item['nodes']
            result[side] = forward.bank.curve.EscapeResponseCurve(
                [q['intermediate_keV'] for q in nodes], [q['log_escape_density'] for q in nodes],
                observed_keV=m['measured_second_site_keV'], sigma_keV=m['sigma_second_keV'])
    return result


def evaluated(direct,energy,settings):
    refs = []
    for order in settings['endpoint_orders']:
        refs.append(direct(energy,order))
        if refs[-1]['log_quadrature_difference']<=settings['max_log_error_target']:
            break
    return dict(reference=refs[-1],orders_tried=refs,
                accepted=refs[-1]['log_quadrature_difference']<=settings['max_log_error_target'])


def errors(curve,references):
    if not references:
        return dict(count=0,max_abs_log_error=None,max_relative_density_error=None,max_abs_density_error=None)
    energies = [row['intermediate_keV'] for row in references]
    baseline = np.array([row['log_escape_density'] for row in references])
    prediction = curve.log_density(energies)
    delta = prediction-baseline
    return dict(count=len(references),max_abs_log_error=float(np.max(np.abs(delta))),
        max_relative_density_error=float(np.max(np.abs(np.expm1(delta)))),
        max_abs_density_error=float(np.max(np.abs(np.exp(prediction)-np.exp(baseline)))))


def extend_side(model,anchor,saved,limit,direct,settings):
    """Pin the old edge, use saved energies for training, and withhold alternate saved rows."""
    target = settings['max_log_error_target']
    lower = limit<anchor['intermediate_keV']
    ordered = sorted(saved,key=lambda p:p['intermediate_keV'],reverse=not lower)
    train,holdout = ordered[::2],ordered[1::2]
    cached = {p['intermediate_keV']:p for p in train}
    saved_e = {r['intermediate_keV'] for r in saved}
    computed = {}

    def sample(energy):
        if energy not in computed:
            computed[energy] = evaluated(direct,energy,settings)
        return computed[energy]['reference']

    def fail(reason,**extra):
        return dict(status=reason,saved_count=len(saved),computed=[p for p in computed.values()],**extra)

    edge = cached.get(limit) or sample(limit)
    if edge['log_quadrature_difference']>target:
        return fail('direct_physical_endpoint_unresolved')
    nodes = {anchor['intermediate_keV']:anchor,edge['intermediate_keV']:edge,train[0]['intermediate_keV']:train[0]}

    def make():
        energies = sorted(nodes)
        return forward.bank.curve.EscapeResponseCurve(energies,[nodes[k]['log_escape_density'] for k in energies],
            observed_keV=model['measured_second_site_keV'],sigma_keV=model['sigma_second_keV'])

    while True:
        curve = make()
        checks = [r for r in train if r['intermediate_keV'] not in nodes]
        if checks:
            delta = np.abs(curve.log_density([r['intermediate_keV'] for r in checks])-
                           np.array([r['log_escape_density'] for r in checks]))
            i = int(np.argmax(delta))
            if delta[i]>target/2:
                row = checks[i]
                nodes[row['intermediate_keV']] = row
                continue
        validation = []
        for a,b in zip(curve.nodes[:-1],curve.nodes[1:],strict=True):
            # The between-knot check is distinct from every old reference.
            mid = float(forward.bank.independent_energy(a,b,saved_e))
            row = sample(mid)
            if not computed[mid]['accepted']:
                return fail('direct_midpoint_unresolved')
            validation.append(row)
        val_error = errors(curve,validation)
        if val_error['max_abs_log_error']>target:
            for row in validation:
                e = row['intermediate_keV']
                if abs(curve.log_density(e)-row['log_escape_density'])>target:
                    nodes[e] = row
            continue
        old_errors = errors(curve,holdout)
        if old_errors['max_abs_log_error'] is not None and old_errors['max_abs_log_error']>target:
            return fail('old_withheld_references_disagree',saved_holdout=old_errors,midpoint_validation=val_error)
        return dict(status='verified_extension',domain_keV=[float(curve.nodes[0]),float(curve.nodes[-1])],
            nodes=[nodes[e] for e in sorted(nodes)],source_side='lower' if lower else 'upper',
            saved_count=len(saved),saved_holdout=old_errors,midpoint_validation=val_error,
            midpoint_references=validation,
            computed=list(computed.values()))


def build(args):
    started = time.perf_counter()
    W.require(not args.output.exists(),'Select a new extension evidence path')
    obs,_,rates,crystal,_,_,_,_,rows,samples,bindings = load_inputs(args)
    lookup,total = forward.bank.trial.rate_functions(rates)
    low,high = bounds(obs['incident_keV'])
    groups = defaultdict(lambda:defaultdict(list))
    for (key,energy),p in samples.items():
        a,b = rows[key]['domain_keV']
        W.require(p['accepted'] and low<=energy<=high and (energy<a or energy>b),
                  'Saved endpoints must be independently accepted outside the old curve')
        groups[key]['lower' if energy<a else 'upper'].append(p['reference'])
    result = {}
    for key,sides in sorted(groups.items()):
        model = rows[key]['model']
        refs = rows[key]['comparison']['nodes']
        direct = fast.checked_evaluator(model,crystal,lookup,total,bindings['endpoint_settings']['azimuth_samples'])
        result[key] = dict(model=model,extensions={side:extend_side(model,refs[i],sides[side],limit,direct,
                    bindings['endpoint_settings']) for side,i,limit in (('lower',0,low),('upper',-1,high)) if side in sides})
    receipt = dict(kind=KIND,bindings=bindings,physical_intermediate_bounds_keV=[low,high],curves=result,
        source_sha256={Path(p).name:W.sha(p) for p in (__file__,fast.__file__,continuous.__file__,photon.__file__)},
        software=forward.bank.software(),elapsed_seconds=time.perf_counter()-started)
    with args.output.open('xb') as stream:
        stream.write(W.encoded(receipt)+b'\n')
    print(dict(status={k:{s:d['status'] for s,d in v['extensions'].items()} for k,v in result.items()},
               elapsed_seconds=receipt['elapsed_seconds'],sha256=W.sha(args.output)))


def common(parser):
    forward.common(parser)
    for name in ('bank','curve-overlay','saved-endpoints'):
        parser.add_argument('--'+name,type=Path,required=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    common(parser)
    parser.add_argument('--output',type=Path,required=True)
    build(parser.parse_args())


if __name__=='__main__':
    main()
