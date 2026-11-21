"""Reconstruct held-out ideal observations without opening their separate truth file."""

import argparse
from contextlib import closing
from collections import Counter
import math
from pathlib import Path
import sqlite3
import time

import numpy as np

import gegi_candidate_trial_curve_bank as bank
import gegi_photon_continuation as photon
import scenario_workflow as W


BANK_KIND = 'gegi_ideal_forward_observation_curve_bank_v1'
OBSERVATIONS_KIND = 'gegi_ideal_forward_observations_v1'
ORDERS = ((0,1),(1,0))


def selected_observations(observations, first_per_cohort):
    W.require(observations['kind']==OBSERVATIONS_KIND and first_per_cohort>=1,'Select accepted forward observations')
    selected = {}
    for cohort in observations['cohorts']:
        label = cohort['cohort_id']
        events = cohort['events']
        ids = [r['attempt_id'] for r in events]
        W.require(label not in selected and all(x<y for x,y in zip(ids,ids[1:])) and len(events)>=first_per_cohort,
                  'Forward observations must preserve acceptance order and unique cohort identities')
        selected[label] = dict(all_accepted_count=len(events),first_accepted=events[:first_per_cohort],
                               retained_for_expansion_count=len(events)-first_per_cohort)
    return selected


def prepare(observations,cohorts,crystal,points,rates):
    low,high = min(rates),max(rates)
    sigmas = observations['sigma_site_keV']
    W.require(len(sigmas)==2 and all(math.isfinite(w) and w>0. for w in sigmas),
              'Use two declared positive interaction-site response widths')
    incident = observations['incident_keV']
    normals,offsets = crystal
    keys,branches = {},[]
    for label,cohort in cohorts.items():
        for event in cohort['first_accepted']:
            positions = np.asarray(event['site_positions_mm'])
            energies = np.asarray(event['observed_site_energies_keV'])
            W.require(positions.shape==(2,3) and energies.shape==(2,) and np.isfinite(positions).all() and
                      np.isfinite(energies).all(),'Each accepted observation must have two finite measured sites')
            for i,j in ORDERS:
                branch = dict(cohort_id=label,attempt_id=event['attempt_id'],site_index_order=(i,j),incident_keV=incident,
                    measured_first_site_keV=float(energies[i]),first_fitted_mm=positions[i].tolist(),
                    geometry_status='available_geometry')
                branches.append(branch)
                if np.any(positions@normals.T>offsets+1e-9):
                    branch['geometry_status'] = 'site_outside_ge'
                    continue
                if np.array_equal(*positions):
                    branch['geometry_status'] = 'coincident_observed_sites'
                    continue
                model = bank.curve_identity(positions[i].tolist(),positions[j].tolist(),float(energies[j]),sigmas[1])
                key = W.digest(model)
                states = np.full((len(points),3),np.nan)
                distinct = np.any(points!=positions[i],axis=1)
                for at in np.flatnonzero(distinct):
                    a = bank.trial.point.first_compton_state(points[at],positions[i],positions[j],incident)
                    states[at] = a['intermediate_keV'],a['first_scatter_cosine'],a['expected_first_deposit_keV']
                e = states[:,0]
                escape_min = e/(1+2*e/photon.ELECTRON_REST_KEV)
                available = (escape_min>=low) & (e<=high)
                branch.update(curve_key=key,states=states,escape_coefficients_available=available,first_vertex_distinct=distinct)
                keys.setdefault(key,dict(model=model,energies=e[available]))
    for item in keys.values():
        e = item['energies']
        item['domain_keV'] = [float(e.min()),float(e.max())] if len(e) else None
    return keys,branches


def inputs(args):
    observations = W.read(args.observations)
    _,plan,basis,rates,crystal,points = bank.setup(args.measured_plan,args.plan,args.probe,args.new_rates)
    W.require(observations['coefficient_basis']==basis,'Forward observations and response use different material coefficients')
    cohorts = selected_observations(observations,args.first_per_cohort)
    keys,branches = prepare(observations,cohorts,crystal,points,rates)
    return observations,plan,basis,rates,crystal,points,cohorts,keys,branches


def manifest(args,observations,basis,cohorts,keys,branches,settings,mode):
    return dict(kind=BANK_KIND, basis=basis,observation_sha256=W.sha(args.observations),incident_keV=observations['incident_keV'],
                sigma_site_keV=observations['sigma_site_keV'], scope=mode,
                cohorts={c:dict(all_accepted_count=r['all_accepted_count'],first_accepted_attempt_ids=[
                    e['attempt_id'] for e in r['first_accepted']],retained_for_expansion_count=r['retained_for_expansion_count'])
                    for c,r in cohorts.items()},
                ordered_observations=[{k:v for k,v in b.items() if k not in ('states','first_vertex_distinct','escape_coefficients_available')}
                                      for b in branches],
                geometry_counts=dict(Counter(b['geometry_status'] for b in branches)),
                curves={k:dict(model=v['model'],domain_keV=v['domain_keV']) for k,v in keys.items()},
                software=bank.software(),source_sha256=bank.producers() | {Path(__file__).name:W.sha(__file__)},
                settings=settings)


def build(args):
    started = time.perf_counter()
    observations,_,basis,rates,crystal,points,cohorts,keys,branches = inputs(args)
    mode = 'first_accepted_first_order_reference' if args.pilot else 'declared_observation_bank'
    settings = dict(sigma_second_keV=observations['sigma_site_keV'][1],base_knots=args.base_knots,
                    azimuth_samples=args.azimuth_samples,energy_order=args.energy_order,max_log_error_target=args.max_log_error)
    info = manifest(args,observations,basis,cohorts,keys,branches,settings,mode)
    if args.pilot:
        W.require(branches[0]['geometry_status']=='available_geometry','The predeclared pilot observation has no fit geometry')
        info['scheduled_curve_keys'] = [branches[0]['curve_key']]
    else:
        info['scheduled_curve_keys'] = list(keys)
    rates_at,total = bank.trial.rate_functions(rates)
    print(dict(mode=mode,durable_target=len(info['scheduled_curve_keys']),all_ordered_slots=len(branches),
               total_declared_curve_keys=len(keys),trial_points=len(points)),flush=True)
    with closing(sqlite3.connect(args.bank)) as db:
        bank.create_bank(db,info)
        for i,key in enumerate(info['scheduled_curve_keys'],1):
            summary = bank.build_curve(db,key,keys[key],{},crystal,rates_at,total,settings)
            q = summary.get('comparison',{})
            print(dict(done=i,key=key,status=summary['status'],direct_points=summary.get('computed_direct_points'),
                       direct_seconds=summary.get('direct_seconds'),max_log_error=q.get('max_absolute_log_error')),flush=True)
    print(dict(elapsed_seconds=time.perf_counter()-started),flush=True)


def common(p):
    for option in ('observations','measured-plan','plan','probe','new-rates'):
        p.add_argument('--'+option,type=Path,required=True)
    p.add_argument('--first-per-cohort',type=int,required=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    common(p)
    p.add_argument('--bank',type=Path,required=True)
    p.add_argument('--pilot',action='store_true')
    p.add_argument('--base-knots',type=int,default=25)
    p.add_argument('--azimuth-samples',type=int,default=256)
    p.add_argument('--energy-order',type=int,default=256)
    p.add_argument('--max-log-error',type=float,default=.01)
    args = p.parse_args()
    if not math.isfinite(args.max_log_error) or args.max_log_error<=0.:
        p.error('Use a positive finite interpolation target')
    build(args)


if __name__=='__main__':
    main()
