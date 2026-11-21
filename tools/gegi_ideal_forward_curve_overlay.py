"""Refine only the failed quadrature references in the sealed forward curve bank."""

import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import time

import gegi_ideal_forward_fast_bank as fast
import gegi_ideal_forward_reconstruction as forward
import gegi_trial_curve_quadrature_repair as refine
import scenario_workflow as W


KIND = 'gegi_ideal_forward_gaussian_refinement_v1'


def recipe(parent_hash,info,rows,order):
    affected = sorted(k for k,r in rows.items() if r['status']==refine.UNRESOLVED)
    return dict(kind=KIND,parent_sha256=parent_hash,observation_sha256=info['observation_sha256'],basis=info['basis'],
                affected_keys=affected,base_energy_order=info['settings']['energy_order'],refinement_order=order,
                source_sha256=info['source_sha256'] | {Path(__file__).name:W.sha(__file__)})


def replacements(path,parent_hash,info,rows):
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        actual = json.loads(db.execute('SELECT recipe FROM manifest WHERE id=1').fetchone()[0])
        values = {k:json.loads(v) for k,v in db.execute('SELECT curve,summary FROM curves')}
    W.require(actual==recipe(parent_hash,info,rows,actual['refinement_order']) and
              set(actual['affected_keys'])==values.keys(),'Use the completed bound forward-curve refinement')
    return actual,values


def run(args):
    started = time.perf_counter()
    W.require(args.parent.resolve()!=args.bank.resolve(),'Preserve the original forward bank')
    _,_,basis,rates,crystal,_,_,keys,_ = forward.inputs(args)
    base_hash = W.sha(args.parent)
    with closing(sqlite3.connect(args.parent.resolve().as_uri()+'?mode=ro',uri=True)) as original:
        info = json.loads(original.execute('SELECT recipe FROM manifest WHERE id=1').fetchone()[0])
        rows = {k:json.loads(v) for k,v in original.execute('SELECT curve,summary FROM curves')}
        W.require(info['kind']==forward.BANK_KIND and info['scope']=='declared_observation_bank' and info['basis']==basis and
            info['observation_sha256']==W.sha(args.observations) and keys.keys()==rows.keys() and
            info['source_sha256'][Path(fast.gaussian.__file__).name]==W.sha(fast.gaussian.__file__) and
            args.energy_order>info['settings']['fallback_order'], 'The original measured failure and unchanged model are required')
        meta = recipe(base_hash,info,rows,args.energy_order)
        rate_at,total = forward.bank.trial.rate_functions(rates)
        cfg = info['settings']
        with closing(sqlite3.connect(args.bank)) as overlay:
            forward.bank.create_bank(overlay,meta)
            for k in meta['affected_keys']:
                saved = {e:json.loads(raw) for e,raw in original.execute('SELECT energy,response FROM samples WHERE curve=?',(k,))}
                at = fast.checked_evaluator(keys[k]['model'],crystal,rate_at,total,cfg['azimuth_samples'])
                r = refine.repair_curve(overlay,k,rows[k],keys[k],saved,at,cfg['energy_order'],
                                        args.energy_order,cfg['max_log_error_target'])
                print(dict(key=k,status=r['status'],reused=r['retained_direct_points'],fresh=r['computed_direct_points'],
                           higher=r['higher_order_points'],refinement=r['old_convergence_failures_keV'],
                           max_log_error=r['comparison']['max_absolute_log_error']),flush=True)
    W.require(W.sha(args.parent)==base_hash,'The original bank changed during refinement')
    print(dict(elapsed_seconds=time.perf_counter()-started,parent_sha256=base_hash))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    forward.common(p)
    p.add_argument('--parent',type=Path,required=True)
    p.add_argument('--bank',type=Path,required=True)
    p.add_argument('--energy-order',type=int,required=True)
    run(p.parse_args())


if __name__=='__main__':
    main()
