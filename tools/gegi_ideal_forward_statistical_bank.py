"""Checkpoint curves for chronological, disjoint ideal-observation blocks."""

import argparse
from contextlib import closing
import math
from pathlib import Path
import sqlite3
import time

import numpy as np

import gegi_ideal_forward_curve_extensions as ext
import gegi_ideal_forward_fast_bank as fast
import gegi_ideal_forward_reconstruction as forward
import gegi_ideal_forward_score as fixed
import gegi_trial_curve_quadrature_repair as refine
import scenario_workflow as W


BANK_KIND = 'gegi_ideal_forward_chronological_blocks_curve_bank_v1'


def chronological_scope(observations,blind):
    W.require(blind['kind']==fixed.BLIND_KIND and W.digest(blind['measured_analysis'])==blind['blind_fit_sha256'],
              'Use the sealed first-block blind baseline')
    prior = blind['measured_analysis']['cohorts']
    blocks = {}
    for row in observations['cohorts']:
        label = row['cohort_id']
        events = row['events']
        ids = [event['attempt_id'] for event in events]
        first = prior[label]['scored_attempt_ids']
        n = len(first)
        W.require(n>0 and len(ids)==prior[label]['all_accepted_count'] and first==ids[:n] and
            all(a<b for a,b in zip(ids,ids[1:])) and label not in blocks,
            'Keep accepted chronology and the sealed first-block identities')
        blocks[label] = [events[i:i+n] for i in range(0,len(events),n)]
    W.require(blocks.keys()==prior.keys(),'Keep both original independent cohorts')
    return blocks


def new_curve_scope(blocks,sigma,incident,crystal):
    low,high = ext.bounds(incident)
    models,rows = {},[]
    normals,offsets = crystal
    for label,groups in blocks.items():
        for block_id,events in enumerate(groups[1:],1):
            for event in events:
                positions,energies = np.asarray(event['site_positions_mm']),event['observed_site_energies_keV']
                W.require(positions.shape==(2,3) and np.isfinite(positions).all() and len(energies)==2 and
                          all(map(math.isfinite,energies)) and np.all(positions@normals.T<=offsets+1e-9) and
                          not np.array_equal(positions[0],positions[1]),'Expect two distinct finite measured sites in Ge')
                for i,j in forward.ORDERS:
                    model = forward.bank.curve_identity(positions[i].tolist(),positions[j].tolist(),energies[j],sigma)
                    key = W.digest(model)
                    models.setdefault(key,model)
                    rows.append(dict(cohort_id=label,block_id=block_id,attempt_id=event['attempt_id'],
                                     site_index_order=[i,j],curve_key=key))
    return [low,high],models,rows


def setup(args):
    observed,blind = W.read(args.observations),W.read(args.fixed_blind)
    obs_sha = W.sha(args.observations)
    _,plan,basis,rates,crystal,points = forward.bank.setup(args.measured_plan,args.plan,args.probe,args.new_rates)
    W.require(observed['kind']==forward.OBSERVATIONS_KIND and observed['coefficient_basis']==basis and
        obs_sha==blind['observations_sha256'],'Statistics must use the original independent observations and material inputs')
    blocks = chronological_scope(observed,blind)
    sigma = observed['sigma_site_keV'][1]
    domain,models,orders = new_curve_scope(blocks,sigma,observed['incident_keV'],crystal)
    low = domain[0]/(1+2*domain[0]/forward.photon.ELECTRON_REST_KEV)
    W.require(min(rates)<=low and domain[1]<=max(rates),'The full new first/second scatter energy domain must be initialized')
    source_sha = forward.bank.producers()|{Path(p).name:W.sha(p) for p in (
        __file__,ext.__file__,fast.__file__,fast.gaussian.__file__,refine.__file__)}
    recipe = dict(kind=BANK_KIND,basis=basis,observation_sha256=obs_sha,fixed_baseline_sha256=W.sha(args.fixed_blind),
        fixed_bank_sha256=blind['curve_bank_sha256'],fixed_overlay_sha256=blind['curve_overlay_sha256'],
        incident_keV=observed['incident_keV'], sigma_site_keV=observed['sigma_site_keV'], physical_domain_keV=domain,
        chronological_blocks={c:[[e['attempt_id'] for e in group] for group in g] for c,g in blocks.items()},
        additional_orders=orders,models=models,source_sha256=source_sha,software=forward.bank.software(),
        settings=dict(max_log_error_target=.01,base_knots=25,azimuth_samples=256,
                      gaussian_order=32,measured_failure_order=128))
    return observed,blind,plan,basis,rates,crystal,points,blocks,recipe


def build(args):
    started = time.perf_counter()
    _,_,_,_,rates,crystal,_,blocks,recipe = setup(args)
    W.require(1<=args.through_block<min(len(g) for g in blocks.values()),'Select the additional chronological block extent')
    cfg = recipe['settings']
    lookup,total = forward.bank.trial.rate_functions(rates)
    orders = [r for r in recipe['additional_orders'] if r['block_id']<=args.through_block]
    keys = dict.fromkeys(order['curve_key'] for order in orders)
    domain = recipe['physical_domain_keV']
    finished = 0
    with closing(sqlite3.connect(args.bank)) as db:
        forward.bank.create_bank(db,recipe)
        sealed = {k for (k,) in db.execute('SELECT curve FROM curves')}
        for key in keys:
            if key in sealed:
                continue
            model = recipe['models'][key]
            nodes = forward.bank.curve.response_nodes(*domain,model['measured_second_site_keV'],model['sigma_second_keV'],cfg['base_knots'])
            initial = dict(comparison=dict(nodes=[dict(intermediate_keV=float(e)) for e in nodes]))
            item = dict(model=model,domain_keV=domain,energies=domain)
            direct = fast.checked_evaluator(model,crystal,lookup,total,cfg['azimuth_samples'])
            r = refine.repair_curve(db,key,initial,item,{},direct,cfg['gaussian_order'],cfg['measured_failure_order'],
                                    cfg['max_log_error_target'])
            finished += 1
            identity = next(o for o in orders if o['curve_key']==key)
            print(dict(identity,status=r['status'],fresh=r['computed_direct_points'],direct_seconds=r['direct_seconds'],
                max_log_error=r['comparison']['max_absolute_log_error']),flush=True)
        print(dict(requested_curves=len(keys),previously_sealed=len(sealed & keys.keys()),sealed_this_run=finished,
            total_planned_new_curves=len(recipe['models']),elapsed_seconds=time.perf_counter()-started),flush=True)


def common(p):
    for name in ('observations','measured-plan','plan','probe','new-rates','fixed-blind','bank'):
        p.add_argument('--'+name,type=Path,required=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    common(p)
    p.add_argument('--through-block',type=int,required=True)
    build(p.parse_args())


if __name__=='__main__':
    main()
