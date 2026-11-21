"""Reuse energy quadrature and Ge ray geometry across source points and lines."""

import argparse
import math
from pathlib import Path
import time

import numpy as np
from scipy.stats import qmc

import gegi_ideal_two_interaction_mass as ideal
import gegi_photon_continuation as photon
import scenario_workflow as W


FIELDS = ('first_compton','contained_photoelectric','known_compton_and_escape','unresolved_escape_sample_mass')


def energy_factors(u, energies, rate_at, outgoing_total, support):
    """Prepare angle, recoil and material factors once per shared Sobol stream."""
    lo,hi = support
    result = {}
    x1,x2 = 2*u[:,3],2*u[:,6]
    for incident in energies:
        W.require(lo<=ideal.outgoing_energy(incident,2.) and incident<=hi,
                  'The material table must cover first and intermediate photon energies')
        intermediate = ideal.outgoing_energy(incident,x1)
        outgoing = ideal.outgoing_energy(intermediate,x2)
        c = rate_at(incident)
        first_angle = photon._angle_model(incident)
        p1 = np.array([2*first_angle(1-x) for x in x1])
        p2 = np.array([2*photon.cosine_density(e,1-x) for e,x in zip(intermediate,x2,strict=True)])
        partial = np.array([(r.total_per_mm,r.photoelectric_per_mm,r.compton_per_mm)
                            for r in map(rate_at,intermediate)])
        known = outgoing>=lo
        exit_rate = np.zeros(len(u))
        exit_rate[known] = [outgoing_total(e) for e in outgoing[known]]
        bound = ideal.missing_exit_mass_bound(incident,lo,1.,c.compton_per_mm/c.total_per_mm if c.total_per_mm else 0.)
        result[incident] = dict(first=c, first_angle=p1, second_angle=p2, second=partial,
                                known=known, exit_rate=exit_rate, missing_bound_per_fraction=bound)
    return result


def first_rays(crystal,source,u):
    source = np.asarray(source,dtype=float)
    directions,fraction = ideal.incoming_rays(crystal,source,u)
    entry,first_chord = ideal.ray_intervals(crystal,source,directions)
    hit = first_chord>0.
    idx = np.flatnonzero(hit)
    return dict(source=source,directions=directions[idx],entry=entry[idx],first_chord=first_chord[idx],
                fraction=float(fraction),hit=hit,indices=idx, uniforms=u[idx])


def cached_exact_weights(crystal,ray,response):
    """Reuse cached energy factors with the original energy-dependent path proposal."""
    idx,uv = ray['indices'],ray['uniforms']
    total,photo,comp = response['second'][idx].T
    rate = response['first']
    first_mass,travel = ideal.competing_ray(rate.total_per_mm,rate.compton_per_mm,ray['first_chord'],uv[:,2])
    first = ray['source']+(ray['entry']+travel)[:,None]*ray['directions']
    scattered = ideal.directions(ray['directions'],2*uv[:,3],2*math.pi*uv[:,4])
    _,remaining = ideal.ray_intervals(crystal,first,scattered)
    absorption,_ = ideal.competing_ray(total,photo,remaining,uv[:,5])
    scatter,travel = ideal.competing_ray(total,comp,remaining,uv[:,5])
    second = first+travel[:,None]*scattered
    exiting = ideal.directions(scattered,2*uv[:,6],2*math.pi*uv[:,7])
    _,exit_path = ideal.ray_intervals(crystal,second,exiting)
    known = response['known'][idx]
    survival = np.zeros(len(idx))
    survival[known] = np.exp(-response['exit_rate'][idx][known]*exit_path[known])
    factor = ray['fraction']*first_mass
    p1,p2 = response['first_angle'][idx],response['second_angle'][idx]
    weights = np.zeros((len(ray['hit']),4))
    weights[idx,0] = factor
    weights[idx,1] = factor*p1*absorption
    weights[idx,2] = factor*p1*scatter*p2*survival
    weights[idx,3] = factor*p1*scatter*p2*(~known)
    return weights,float(ray['fraction']*response['missing_bound_per_fraction'])


def summarize(per_seed,powers):
    output = []
    for j,power in enumerate(powers):
        values = [s['estimates'][j] for s in per_seed]
        means = {k:float(np.mean([p[k] for p in values])) for k in FIELDS}
        sd = {k:float(np.std([p[k] for p in values],ddof=1)) for k in FIELDS}
        combined = [p['contained_photoelectric']+p['known_compton_and_escape'] for p in values]
        output.append(dict(points=2**power,means=means,replicate_sd=sd,known_topology_probability=float(np.mean(combined)),
                           topology_replicate_sd=float(np.std(combined,ddof=1))))
    return output


def benchmark(crystal, coords, energies, rate_at, outgoing_total, support, powers, seeds):
    """Prepare all shared streams, then evaluate one source point at a time."""
    t = time.perf_counter()
    streams = []
    for seed in seeds:
        u = qmc.Sobol(8,scramble=True,seed=seed).random_base2(powers[-1])
        streams.append((seed,u,energy_factors(u,energies,rate_at,outgoing_total,support)))
    timing = dict(shared_preparation_seconds=time.perf_counter()-t,shared_first_ray_seconds=0.,
                  cached_original_proposal_seconds=0.)
    cases = []
    for point in coords:
        lines = {e:[] for e in energies}
        wall = {'first_rays':0.,'cached_proposal':0.}
        for seed,u,factors in streams:
            t = time.perf_counter()
            ray = first_rays(crystal,point['source_mm'],u)
            wall['first_rays'] += time.perf_counter()-t
            t = time.perf_counter()
            for e,f in factors.items():
                samples,bound = cached_exact_weights(crystal,ray,f)
                lines[e].append(seed_summary(seed,samples,ray,bound,powers))
            wall['cached_proposal'] += time.perf_counter()-t
        timing['shared_first_ray_seconds'] += wall['first_rays']
        timing['cached_original_proposal_seconds'] += wall['cached_proposal']
        cases.append(dict(point,timing_seconds=wall,lines=[dict(incident_keV=e,estimates=summarize(samples,powers),seed_results=samples,
            uninitialized_exit_mass_analytic_upper_bound=samples[0]['estimates'][-1]['uninitialized_exit_mass_analytic_upper_bound'])
            for e,samples in lines.items()]))
    return cases,timing


def seed_summary(seed,samples,ray,bound,powers):
    return dict(seed=seed,estimates=[dict(points=2**p,**ideal.summarize(
        samples[:2**p],ray['hit'][:2**p],ray['fraction'],bound)) for p in powers])


def compare_prior(cases,prior,basis):
    W.require(prior['basis']==basis,'Prior normalizer used a different material or trial basis')
    matched = []
    for case in cases:
        same = next((r for r in prior['cases'] if r['trial']['source_mm']==case['source_mm']),None)
        if same is None:
            continue
        for new,old in zip(case['lines'],same['lines'],strict=True):
            W.require(new['incident_keV']==old['incident_keV'],'Prior incident line changed')
            a,b = new['estimates'][-1],old['estimates'][-1]
            first = abs(a['means']['first_compton']-b['means']['first_compton'])
            value,reference = a['known_topology_probability'],b['known_topology_probability']
            shared = {(r['seed'],p['points']):p for r in new['seed_results'] for p in r['estimates']}
            previous = {(r['seed'],p['points']):p for r in old['seed_results'] for p in r['estimates']}
            compare = [abs(shared[i][k]-previous[i][k]) for i in shared.keys() & previous.keys() for k in FIELDS]
            matched.append(dict(grid_index=case['grid_index'],incident_keV=new['incident_keV'], first_compton_abs_difference=first,
                               comparable_seed_values=len(compare), maximum_seed_mass_abs_difference=max(compare,default=None),
                               shared_topology_probability=value, previous_topology_probability=reference,
                               relative_difference=(value-reference)/reference if reference else None))
    return matched


def run(args):
    start = time.perf_counter()
    W.require(not args.output.exists(),'Select a new shared normalization receipt')
    measured,plan,basis,rates,crystal,points = ideal.bank.setup(args.measured_plan,args.plan,args.probe,args.new_rates)
    W.require(1<=args.coarse_power<args.fine_power and len(set(args.seed))==len(args.seed) and len(args.seed)>=2,
              'Use distinct replicate seeds and increasing Sobol sample powers')
    nr,nd = len(plan['trial_grid']['radii_mm']),len(plan['trial_grid']['unit_vectors'])
    replay = {tuple(a) for a in args.replay_grid_index}
    if args.full_grid:
        W.require(not replay,'Full grid already contains both prior replay coordinates')
        indices = [(i,j) for i in range(nr) for j in range(nd)]
    else:
        indices = [tuple(a) for a in args.grid_index+args.replay_grid_index]
    W.require(len(set(indices))==len(indices) and all(0<=i<nr and 0<=j<nd for i,j in indices),
              'Choose unique radial/direction indices from the declared source grid')
    normals,offsets = crystal
    coords = []
    for i,j in indices:
        p = points[i*nd+j]
        margin = float(np.min(offsets - normals@p))
        role = 'full_grid' if args.full_grid else 'declared_prior_replay' if (i,j) in replay else 'outer_pilot'
        coords.append(dict(grid_index=i*nd+j,radial_index=i,direction_index=j,source_mm=p.tolist(),role=role,
                           source_region='outside_ge' if margin < -1e-9 else 'ge_boundary' if margin<=1e-9 else 'inside_ge'))
    rate_at,total = ideal.bank.trial.rate_functions(rates)
    powers = [args.coarse_power,args.fine_power]
    cases,timing = benchmark(crystal,coords,measured['incident_lines_keV'],rate_at,total,basis['coefficient_support_keV'],
                             powers,args.seed)
    prior = W.read(args.reference)
    matched = compare_prior(cases,prior,basis)
    result = dict(kind='gegi_shared_ideal_topology_normalization_v1',basis=basis,normalization_cases=cases,
        prior_normalizer_sha256=W.sha(args.reference), prior_comparison=matched,seed=args.seed,sample_powers=powers,
        trial_scope='full_declared_grid' if args.full_grid else 'prespecified_pilot',
        timing_seconds=timing, elapsed_seconds=time.perf_counter()-start,
        source_sha256=ideal.bank.producers() | {Path(f).name:W.sha(f) for f in (__file__,ideal.__file__)},
        software=ideal.bank.software(),
        method='Same per-emitted-photon ordered two-interaction transport mass. Energy coefficients and incoming rays are reused '
               'with the original exponential chord proposals. Shared Sobol draws and independent scrambles preserve paired source comparisons. '
               'The two unit-normalized Gaussian observations integrate out. This is an ideal topology normalization.')
    with args.output.open('xb') as stream:
        stream.write(W.encoded(result)+b'\n')
    print(dict(normalizers=len(cases)*len(measured['incident_lines_keV']),timing=timing,prior_matched=len(matched)))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('measured-plan','plan','probe','new-rates','reference','output'):
        p.add_argument('--'+name,type=Path,required=True)
    scope = p.add_mutually_exclusive_group(required=True)
    scope.add_argument('--grid-index',type=int,nargs=2,action='append',metavar=('RADIAL','DIRECTION'))
    scope.add_argument('--full-grid',action='store_true')
    p.add_argument('--replay-grid-index',type=int,nargs=2,action='append',default=[],metavar=('RADIAL','DIRECTION'))
    p.add_argument('--seed',type=int,action='append',required=True)
    p.add_argument('--coarse-power',type=int,required=True)
    p.add_argument('--fine-power',type=int,required=True)
    run(p.parse_args())


if __name__=='__main__':
    main()
