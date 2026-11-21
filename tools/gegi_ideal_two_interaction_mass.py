"""Integrate the idealized two-interaction Ge response per emitted photon.

Integrating both unit-normalized measured-energy Gaussians leaves the latent
transport mass. Convert each ordered vertex volume to ray solid angle and
flight distance, cancelling the inverse-square volume Jacobian. The branches
are first Compton then contained photoelectric, or two Compton interactions
followed by an uncollided Ge exit. Each flight competes with all initialized
Ge interaction rates. See Yoneda et al., https://arxiv.org/html/2107.01846,
equations 15–21, and Tarpau et al., https://arxiv.org/html/2402.07676v2,
appendix A, for sampling incoming rays from an enclosing cone.
"""

import argparse
import math
from pathlib import Path
import time

import numpy as np
from scipy.stats import qmc

import gegi_candidate_trial_curve_bank as bank
import gegi_photon_continuation as photon
import scenario_workflow as W


def ray_intervals(crystal, origin, direction):
    """Return the occupied distance intervals of forward unit rays in convex Ge."""
    normals, offsets = crystal
    projections = direction @ normals.T
    clearance = offsets - origin @ normals.T
    lower = np.full(projections.shape,-np.inf)
    upper = np.full(projections.shape,np.inf)
    np.divide(clearance,projections,out=lower,where=projections<0.)
    np.divide(clearance,projections,out=upper,where=projections>0.)
    start = np.maximum(0.,lower.max(axis=-1))
    chord = upper.min(axis=-1)-start
    hit = (chord>0.) & ~np.any((projections==0.) & (clearance<0.),axis=-1)
    return np.where(hit,start,0.),np.where(hit,chord,0.)


def directions(axis, one_minus_cosine, azimuth):
    side = np.cross(axis,np.eye(3)[np.argmin(np.abs(axis),axis=-1)])
    side /= np.linalg.norm(side,axis=-1,keepdims=True)
    cross = np.cross(axis,side)
    x = np.asarray(one_minus_cosine)
    return ((1-x)[...,None]*axis + np.sqrt(x*(2-x))[...,None]*
            (np.cos(azimuth)[...,None]*side+np.sin(azimuth)[...,None]*cross))


def incoming_rays(crystal, source, uniforms):
    """Use the circumsphere of the first saved rectangular Ge solid to enclose every ray hit."""
    normals, offsets = crystal
    axes = normals[:3]
    if not np.allclose(normals[3:6],-axes) or not np.allclose(axes @ axes.T,np.eye(3)):
        raise ValueError('The saved Ge halfspaces must start with the enclosing box')
    center = axes.T @ ((offsets[:3]-offsets[3:6])/2)
    radius = np.linalg.norm((offsets[:3]+offsets[3:6])/2)
    delta = center-source
    distance = np.linalg.norm(delta)
    if distance<=radius:
        axis, fraction = np.array([0.,0.,1.]),1.
    else:
        square = (radius/distance)**2
        axis, fraction = delta/distance,square/(2*(1+math.sqrt(1-square)))
    return directions(axis,2*fraction*uniforms[:,0],2*math.pi*uniforms[:,1]),fraction


def competing_ray(total, channel, length, uniform):
    """Return a process mass and a path length under its truncated exponential."""
    hit = -np.expm1(-total*length)
    shape = np.shape(hit)
    share = np.divide(channel,total,out=np.zeros(shape),where=total>0)
    depth = np.divide(-np.log1p(-uniform*hit),total,out=np.zeros(shape),where=total>0)
    return share*hit,depth


def outgoing_energy(incident, one_minus_cosine):
    return incident/(1+incident*one_minus_cosine/photon.ELECTRON_REST_KEV)


def missing_exit_mass_bound(incident, min_rate_energy, fraction, first_compton_fraction):
    """Conservative missing-rate mass from the doubly-backscattered angular region."""
    m = photon.ELECTRON_REST_KEV
    area_edge = max(0., 4-m*(1/min_rate_energy-1/incident))
    # Each normalized KN cosine density is <= (1+2*incident/m)**2:
    # the kernel is <=2 and its normalization is >=2*k_min**2.
    density_bound = (1+2*incident/m)**2
    angular_mass = min(1., area_edge**2/2*density_bound**2)
    return fraction*first_compton_fraction*angular_mass


def ray_weights(crystal, source, incident, rate_at, outgoing_total, support, u):
    lo,hi = support
    e1_min = outgoing_energy(incident,2.)
    W.require(lo<=e1_min and incident<=hi, 'The material table must cover first and intermediate photon energies')
    incoming,fraction = incoming_rays(crystal,source,u)
    starts,length = ray_intervals(crystal,source,incoming)
    intersects = length>0
    weight = np.zeros((len(u),4))
    c = rate_at(incident)
    known_bound = missing_exit_mass_bound(incident,lo,fraction,c.compton_per_mm/c.total_per_mm if c.total_per_mm else 0.)
    idx = np.flatnonzero(intersects)
    uv, incoming = u[idx], incoming[idx]
    first_mass, travel = competing_ray(c.total_per_mm,c.compton_per_mm,length[idx],uv[:,2])
    x1 = 2*uv[:,3]
    first = source+(starts[idx]+travel)[:,None]*incoming
    scattered = directions(incoming,x1,2*math.pi*uv[:,4])
    intermediate = outgoing_energy(incident,x1)
    first_cosine_density = photon._angle_model(incident)
    s1 = np.array([2*first_cosine_density(1-x) for x in x1])
    _,remaining = ray_intervals(crystal,first,scattered)
    second_rate = [rate_at(e) for e in intermediate]
    total = np.array([r.total_per_mm for r in second_rate])
    photo = np.array([r.photoelectric_per_mm for r in second_rate])
    comp = np.array([r.compton_per_mm for r in second_rate])
    absorption,_ = competing_ray(total,photo,remaining,uv[:,5])
    scatter,travel = competing_ray(total,comp,remaining,uv[:,5])
    second = first+travel[:,None]*scattered
    x2 = 2*uv[:,6]
    final = outgoing_energy(intermediate,x2)
    s2 = np.array([2*photon.cosine_density(e,1-x) for e,x in zip(intermediate,x2,strict=True)])
    exiting = directions(scattered,x2,2*math.pi*uv[:,7])
    _,exit_path = ray_intervals(crystal,second,exiting)
    known = final>=lo
    exit_survival = np.zeros(len(final))
    exit_survival[known] = np.exp(-np.array([outgoing_total(e) for e in final[known]])*exit_path[known])
    factor = fraction*first_mass
    weight[idx,0] = factor
    weight[idx,1] = factor*s1*absorption
    weight[idx,2] = factor*s1*scatter*s2*exit_survival
    weight[idx,3] = factor*s1*scatter*s2*(~known)
    return weight,intersects,fraction,known_bound


def summarize(samples, indices, fraction, bound):
    p = samples.mean(axis=0)
    return dict(first_compton=float(p[0]), contained_photoelectric=float(p[1]),
                known_compton_and_escape=float(p[2]), unresolved_escape_sample_mass=float(p[3]),
                hit_rays=int(indices.sum()), emitted_solid_angle_fraction=float(fraction),
                uninitialized_exit_mass_analytic_upper_bound=float(bound))


def estimate(crystal, source, incident, rate_at, outgoing_total, support, powers, seeds):
    per_seed = []
    for seed in seeds:
        u = qmc.Sobol(8,scramble=True,seed=seed).random_base2(powers[-1])
        sample, hits, fraction,bound = ray_weights(crystal,np.asarray(source),incident,rate_at,outgoing_total,support,u)
        per_seed.append(dict(seed=seed, estimates=[dict(points=2**power, **summarize(
            sample[:2**power],hits[:2**power],fraction,bound)) for power in powers]))
    columns = ['first_compton','contained_photoelectric','known_compton_and_escape','unresolved_escape_sample_mass']
    stats = []
    for j,power in enumerate(powers):
        estimates = [x['estimates'][j] for x in per_seed]
        means = {k:float(np.mean([e[k] for e in estimates])) for k in columns}
        stats.append(dict(points=2**power,means=means, replicate_sd={k:float(np.std([e[k] for e in estimates],ddof=1))
                          for k in columns}, known_topology_probability=means['contained_photoelectric']+
                          means['known_compton_and_escape']))
    return dict(incident_keV=incident,physical_escape_energy_bounds_keV=[outgoing_energy(outgoing_energy(incident,2.),2.),incident],
                uninitialized_exit_mass_analytic_upper_bound=bound, estimates=stats,seed_results=per_seed)


def run(args):
    started = time.perf_counter()
    W.require(not args.output.exists(),'Select a new normalization receipt path')
    measured,plan,basis,rates,crystal,_ = bank.setup(args.measured_plan,args.plan,args.probe,args.new_rates)
    rate_at, total = bank.trial.rate_functions(rates)
    W.require(1<=args.coarse_power<args.fine_power and len(set(args.seed))==len(args.seed) and len(args.seed)>=2,
              'Supply distinct replicate seeds and increasing Sobol sample powers')
    indices = args.trial_index
    W.require(len(set(indices))==len(indices) and all(0<=k<len(plan['selected_trials']) for k in indices),
              'Select distinct prescribed trial points')
    cases = []
    for k in indices:
        trial = plan['selected_trials'][k]
        estimates = [estimate(crystal,trial['source_mm'],energy,rate_at,total,basis['coefficient_support_keV'],
            [args.coarse_power,args.fine_power],args.seed) for energy in measured['incident_lines_keV']]
        cases.append(dict(trial_index=k,trial=trial,lines=estimates))
    result = dict(kind='gegi_ideal_two_interaction_normalization_v1',basis=basis,
        source_sha256=bank.producers() | {Path(__file__).name:W.sha(__file__)}, software=bank.software(),cases=cases,
        definition='Idealized probability per emitted isotropic photon for the two ordered active-Ge branches represented '
                   'by the response. Both unit-Gaussian energy densities are integrated over the full real line. '
                   'Ge flight, competing rates and normalized free-electron angles define the remaining integral.',
        omitted='Passive materials, secondary transport beyond the assumed local deposit, strip pairing, positional resolution, '
                'readout and candidate selection are separate. The result is an idealized topology mass.',
        quadrature='Scrambled Sobol ray quadrature. Prefix and independent scramble differences quantify numerical stability. '
                   'Unsampled low-energy rate gaps retain an analytic probability bound; this is separate from sampling error.',
        elapsed_seconds=time.perf_counter()-started)
    with args.output.open('xb') as stream:
        stream.write(W.encoded(result)+b'\n')
    for s in cases:
        print(s['trial_index'],[(l['incident_keV'],l['estimates'][-1]['known_topology_probability']) for l in s['lines']])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for option in ('measured-plan','plan','probe','new-rates','output'):
        p.add_argument('--'+option,type=Path,required=True)
    p.add_argument('--trial-index',type=int,action='append',required=True,help='Zero-based index into the prescribed six trials')
    p.add_argument('--seed',type=int,action='append',required=True)
    p.add_argument('--coarse-power',type=int,required=True)
    p.add_argument('--fine-power',type=int,required=True)
    run(p.parse_args())


if __name__=='__main__':
    main()
