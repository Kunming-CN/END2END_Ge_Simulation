"""Use the verified Gaussian-measure quadrature for the declared forward bank."""

import argparse
from contextlib import closing
import json
import math
from pathlib import Path
import sqlite3
import time

import gegi_gaussian_escape_quadrature as gaussian
import gegi_ideal_forward_reconstruction as forward
import gegi_trial_curve_quadrature_repair as refine
import scenario_workflow as W


PROOF_KIND = 'gegi_ideal_forward_gaussian_reference_comparison_v1'


def saved_reference(path,basis,observations,keys):
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        info = json.loads(db.execute('SELECT recipe FROM manifest WHERE id=1').fetchone()[0])
        key, = info['scheduled_curve_keys']
        row, = db.execute('SELECT summary FROM curves WHERE curve=?',(key,)).fetchone()
        result = json.loads(row)
        cached = {energy:json.loads(r) for energy,r in db.execute('SELECT energy,response FROM samples WHERE curve=?',(key,))}
    W.require(info['kind']==forward.BANK_KIND and info['scope']=='first_accepted_first_order_reference' and
        info['basis']==basis and info['observation_sha256']==observations and result['status']=='verified_heldout_curve' and
        result['model']==keys[key]['model'] and result['domain_keV']==keys[key]['domain_keV'] and
        info['software']==forward.bank.software() and info['source_sha256']==forward.bank.producers() |
        {Path(forward.__file__).name:W.sha(forward.__file__)},'Use the original verified ordered observation reference')
    return key,info,result,cached


def checked_evaluator(model,crystal,rates_at,outgoing_total,azimuth_samples):
    def at(energy,order):
        rates = rates_at(energy)
        positional = (crystal,model['first_fitted_mm'],model['second_fitted_mm'],energy,rates,
                      outgoing_total,model['measured_second_site_keV'])
        opts = dict(sigma_keV=model['sigma_second_keV'],azimuth_samples=azimuth_samples)
        a = gaussian.observed_escape(*positional,**opts,energy_order=order//2)
        b = gaussian.observed_escape(*positional,**opts,energy_order=order)
        low,high = (r['log_escape_per_mm_observed_keV'] for r in (a,b))
        W.require(low is not None and high is not None,'The declared Ge escape channel is unavailable')
        return dict(intermediate_keV=float(energy),log_escape_density=high,raw_escape_density=b['escape_per_mm_observed_keV'],
                    density_status=b['escape_density_status'],log_quadrature_difference=abs(high-low),
                    lower_order_log_density=low, energy_order=order,
                    spectrum_evaluations=a['spectrum_evaluations']+b['spectrum_evaluations'])
    return at


def parameters(args):
    obs,_,basis,rates,crystal,_,cohorts,keys,branches = forward.inputs(args)
    obs_sha = W.sha(args.observations)
    ref_sha = W.sha(args.reference_bank)
    key,ref_info,ref,old = saved_reference(args.reference_bank,basis,obs_sha,keys)
    rates_at,total = forward.bank.trial.rate_functions(rates)
    settings = dict(ref_info['settings'],reference_energy_order=ref_info['settings']['energy_order'],
                    energy_order=args.energy_order,fallback_order=args.fallback_order,
                    max_reference_log_error=args.max_reference_log_error)
    W.require(args.energy_order>=2 and args.fallback_order>args.energy_order and
              math.isfinite(args.max_reference_log_error) and args.max_reference_log_error>0.,
              'Use increasing positive Gaussian quadrature orders and a finite comparison target')
    hashes = {Path(f).name:W.sha(f) for f in (__file__,gaussian.__file__,refine.__file__)}
    info = forward.manifest(args,obs,basis,cohorts,keys,branches,settings,'declared_observation_bank')
    info.update(source_sha256=info['source_sha256']|hashes,reference_bank_sha256=ref_sha,
                quadrature='Gaussian-measure observed escape with two positive rules.')
    return info,keys,key,ref,old,crystal,rates_at,total


def compare(args):
    W.require(not args.output.exists(),'Select a fresh fast-reference comparison path')
    info,keys,key,ref,old,crystal,rates_at,total = parameters(args)
    cfg = info['settings']
    evaluate = checked_evaluator(keys[key]['model'],crystal,rates_at,total,cfg['azimuth_samples'])
    start = time.perf_counter()
    checks = []
    for e,reference in sorted(old.items()):
        result = evaluate(e,cfg['energy_order'])
        checks.append(dict(result,reference_log_density=reference['log_escape_density'],
                           reference_abs_log_difference=abs(result['log_escape_density']-reference['log_escape_density'])))
    seconds = time.perf_counter()-start
    largest = max(r['reference_abs_log_difference'] for r in checks)
    delta = max(r['log_quadrature_difference'] for r in checks)
    output = dict(kind=PROOF_KIND,curve_key=key,observation_sha256=info['observation_sha256'],basis=info['basis'],
        reference_bank_sha256=info['reference_bank_sha256'],source_sha256=info['source_sha256'],settings=cfg,
        compared_points=len(checks),checks=checks,max_abs_log_difference=largest,max_adjacent_gaussian_log_difference=delta,
        reference_full_response_seconds=ref['direct_seconds'],gaussian_observed_escape_only_seconds=seconds,
        within_reference_target=max(largest,delta)<=cfg['max_reference_log_error'])
    with args.output.open('xb') as stream:
        stream.write(W.encoded(output)+b'\n')
    print({k:v for k,v in output.items() if k in ('compared_points','max_abs_log_difference','max_adjacent_gaussian_log_difference',
          'reference_full_response_seconds','gaussian_observed_escape_only_seconds','within_reference_target')})


def build(args):
    started = time.perf_counter()
    W.require(args.bank.resolve()!=args.reference_bank.resolve(),'Preserve the original direct reference bank')
    info,keys,key,ref,old,crystal,rates_at,total = parameters(args)
    proof = W.read(args.proof)
    W.require(proof['kind']==PROOF_KIND and proof['within_reference_target'] and proof['curve_key']==key and all(
        proof[k]==info[k] for k in ('observation_sha256','basis','reference_bank_sha256','source_sha256','settings')),
        'A passing same-observation quadrature comparison is required before scaling')
    info.update(scheduled_curve_keys=list(keys),gaussian_reference_proof_sha256=W.sha(args.proof))
    cfg = info['settings']
    max_log = cfg['max_log_error_target']
    with closing(sqlite3.connect(args.bank)) as db:
        forward.bank.create_bank(db,info)
        for i,(k,item) in enumerate(keys.items(),1):
            if k==key:
                initial,saved = ref,old
            else:
                model = item['model']
                nodes = forward.bank.curve.response_nodes(*item['domain_keV'],model['measured_second_site_keV'],
                                                          model['sigma_second_keV'],cfg['base_knots'])
                initial,saved = dict(comparison=dict(nodes=[dict(intermediate_keV=float(e)) for e in nodes])),{}
            at = checked_evaluator(item['model'],crystal,rates_at,total,cfg['azimuth_samples'])
            result = refine.repair_curve(db,k,initial,item,saved,at,cfg['energy_order'],cfg['fallback_order'],max_log)
            print(dict(curve=i,total=len(keys),key=k,status=result['status'],reused=result['retained_direct_points'],
                fresh=result['computed_direct_points'],higher_order_points=result['higher_order_points'],
                direct_seconds=result['direct_seconds'],max_log_error=result['comparison']['max_absolute_log_error']),flush=True)
    print(dict(elapsed_seconds=time.perf_counter()-started),flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    modes = p.add_subparsers(dest='mode',required=True)
    w = modes.add_parser('compare')
    b = modes.add_parser('build')
    for a in (w,b):
        forward.common(a)
        a.add_argument('--reference-bank',type=Path,required=True)
        a.add_argument('--energy-order',type=int,default=32)
        a.add_argument('--fallback-order',type=int,default=64)
        a.add_argument('--max-reference-log-error',type=float,default=.001)
    w.add_argument('--output',type=Path,required=True)
    w.set_defaults(run=compare)
    b.add_argument('--proof',type=Path,required=True)
    b.add_argument('--bank',type=Path,required=True)
    b.set_defaults(run=build)
    args = p.parse_args()
    args.run(args)


if __name__=='__main__':
    main()
