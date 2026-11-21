"""Profile the ideal forward model continuously in the exterior Ge geometry."""

import argparse
from collections import Counter
from contextlib import closing
import json
import math
from pathlib import Path
import sqlite3
import time

import numpy as np
from scipy.optimize import minimize
from scipy.special import logsumexp
from scipy.stats import qmc

import gegi_first_compton_arrival as arrival
import gegi_ideal_forward_fast_bank as fast
import gegi_ideal_forward_reconstruction as forward
import gegi_ideal_forward_score as fixed
import gegi_photon_continuation as photon
from gegi_photon_log_response import gaussian_log_density_per_kev
import gegi_shared_topology_normalization as shared
import scenario_workflow as W


FIT_KIND = 'gegi_ideal_forward_continuous_external_fit_v1'


def unit(vector):
    return np.asarray(vector,dtype=float)/math.hypot(*vector)


def exterior(crystal, point):
    normals,offsets = crystal
    return bool(np.any(normals@point > offsets+1e-9))


def singular_witnesses(cohorts,crystal,radii):
    """Point-vertex density has D^-2 divergence at modeled selected sites."""
    by_cohort = {}
    for label,c in cohorts.items():
        rows = []
        for e in c['first_accepted']:
            for i,p in enumerate(e['site_positions_mm']):
                if radii[0]<=math.hypot(*p)<=radii[-1] and not exterior(crystal,np.asarray(p)):
                    rows.append(dict(attempt_id=e['attempt_id'],observed_label=i,position_mm=p))
        by_cohort[label] = rows
    return by_cohort


class Normalizers:
    def __init__(self,crystal,rates,energy,grid_receipt,validation_seeds):
        self.crystal = crystal
        self.original = tuple(grid_receipt['seed'])
        self.validation = tuple(validation_seeds)
        self.powers = tuple(grid_receipt['sample_powers'])
        self.cache = {}
        self.streams = {}
        rate_at,total = forward.bank.trial.rate_functions(rates)
        for seed in self.original+self.validation:
            draws = qmc.Sobol(8,scramble=True,seed=seed).random_base2(self.powers[-1])
            response = shared.energy_factors(draws,[energy],rate_at,total,[min(rates),max(rates)])[energy]
            for power in self.powers:
                n = 2**power
                self.streams[seed,power] = draws[:n],{k:(v[:n] if isinstance(v,np.ndarray) else v)
                                                    for k,v in response.items()}
        for case in grid_receipt['normalization_cases']:
            line = next(l for l in case['lines'] if l['incident_keV']==energy)
            p = tuple(case['source_mm'])
            for i,power in enumerate(self.powers):
                for b in line['seed_results']:
                    a = b['estimates'][i]
                    self.cache[p,b['seed'],power] = a['contained_photoelectric']+a['known_compton_and_escape']
        self.computed = 0

    def at(self,point,power,seeds):
        p = tuple(map(float,point))
        result = []
        for seed in seeds:
            key = p,seed,power
            if key not in self.cache:
                draws,response = self.streams[seed,power]
                ray = shared.first_rays(self.crystal,np.asarray(p),draws)
                weights,_ = shared.cached_exact_weights(self.crystal,ray,response)
                avg = weights.mean(axis=0)
                self.cache[key] = float(avg[1]+avg[2])
                self.computed += 1
            result.append(self.cache[key])
        return result


class Response:
    def __init__(self,crystal,rates,observations,branches,rows,db,settings):
        self.crystal = crystal
        self.rate_at,total = forward.bank.trial.rate_functions(rates)
        self.energy = observations['incident_keV']
        self.rate0 = self.rate_at(self.energy)
        self.sigma1,self.sigma2 = observations['sigma_site_keV']
        self.first_angle = photon._angle_model(self.energy)
        self.db,self.cfg = db,settings
        self.branches = {}
        self.cache = {}
        self.state_count = Counter()
        for label in {row['cohort_id'] for row in branches}:
            self.branches[label] = []
        for b in branches:
            W.require(b['geometry_status']=='available_geometry','Continuous forward comparison requires fixed complete observations')
            key = b['curve_key']
            r = rows[key]
            W.require(r['status']=='verified_heldout_curve','Use only the verified original/overlay escape curves')
            k = r['comparison']['nodes']
            m = r['model']
            curve = forward.bank.curve.EscapeResponseCurve([x['intermediate_keV'] for x in k],[x['log_escape_density'] for x in k],
                        observed_keV=m['measured_second_site_keV'],sigma_keV=m['sigma_second_keV'])
            direct = fast.checked_evaluator(m,crystal,self.rate_at,total,settings['azimuth_samples'])
            self.branches[b['cohort_id']].append((b,key,m,curve,direct))
        self.endpoint = {(k,e):json.loads(r) for k,e,r in db.execute('SELECT curve,energy,response FROM samples')}

    def escape(self,key,curve,direct,energy):
        if curve.nodes[0]<=energy<=curve.nodes[-1]:
            self.state_count['interpolation_within_domain'] += 1
            return float(curve.log_density(energy))
        pair = key,energy
        if pair not in self.endpoint:
            t = time.perf_counter()
            tried = []
            for order in self.cfg['endpoint_orders']:
                row = direct(energy,order)
                tried.append(row)
                if row['log_quadrature_difference']<=self.cfg['max_log_error_target']:
                    break
            result = dict(reference=row,orders_tried=tried,accepted=
                          row['log_quadrature_difference']<=self.cfg['max_log_error_target'])
            with self.db:
                self.db.execute('INSERT INTO samples VALUES (?,?,?,?)',(key,energy,W.encoded(result),time.perf_counter()-t))
            self.endpoint[pair] = result
            self.state_count['new_endpoint_references'] += 1
        result = self.endpoint[pair]
        self.state_count['outside_domain_lookups'] += 1
        if not result['accepted']:
            self.state_count['endpoint_quadrature_unresolved'] += 1
            return None
        return result['reference']['log_escape_density']

    def at(self,cohort,point):
        idx = cohort,tuple(map(float,point))
        if idx in self.cache:
            return self.cache[idx]
        logs = []
        for b,key,m,curve,direct in self.branches[cohort]:
            first,second = m['first_fitted_mm'],m['second_fitted_mm']
            incoming = arrival.first_compton_arrival(self.crystal,point,first,self.rate0)
            if incoming['density_status']!='computed':
                self.state_count[incoming['density_status']] += 1
                self.cache[idx] = None
                return None
            state = forward.bank.trial.point.first_compton_state(point,first,second,self.energy)
            e1 = state['intermediate_keV']
            e2 = self.escape(key,curve,direct,e1)
            if e2 is None:
                self.cache[idx] = None
                return None
            r = self.rate_at(e1)
            length = state['site_separation_mm']
            emission = incoming['log_first_compton_per_emitted_photon_mm3']
            first_obs = gaussian_log_density_per_kev(b['measured_first_site_keV'],state['expected_first_deposit_keV'],self.sigma1)
            angular = math.log(self.first_angle(state['first_scatter_cosine'])/(2*math.pi))
            absorption = (math.log(r.photoelectric_per_mm)-length*r.total_per_mm+
                          gaussian_log_density_per_kev(m['measured_second_site_keV'],e1,self.sigma2))
            logs.append(emission+first_obs+angular-2*math.log(length)+float(np.logaddexp(absorption,e2)))
        events = logsumexp(np.array(logs).reshape(-1,2),axis=1)-math.log(2.)
        value = float(events.sum())
        self.cache[idx] = value
        return value


def objective(response,normalizers,cohort,power,seeds,point):
    if not exterior(response.crystal,point):
        return None
    raw = response.at(cohort,point)
    if raw is None:
        return None
    q = normalizers.at(point,power,seeds)
    if not all(x>0. for x in q):
        return None
    n = len(response.branches[cohort])//2
    return dict(known_mass=float(np.mean(q)),masses=q,raw_log_score=raw,
                log_score=raw-n*math.log(float(np.mean(q))),per_scramble_log_scores=[raw-n*math.log(x) for x in q])


def local_fit(evaluate,start,radii,max_evals,angular_step,*,radius=None):
    """Optimize in the tangent-coordinate hemisphere around a blind starting direction."""
    center = unit(start)
    e1 = unit(np.cross(center,np.eye(3)[np.argmin(np.abs(center))]))
    e2 = np.cross(center,e1)
    parameters = [0.,0.]
    lower,upper = math.log(radii[0]),math.log(radii[-1])
    steps = [angular_step,angular_step]
    bounds = [(None,None),(None,None)]
    if radius is None:
        r = min(upper,max(lower,math.log(math.hypot(*start))))
        parameters.append(r)
        steps.append(.13 if r+.13<=upper else -.13)
        bounds.append((lower,upper))
    initial = np.array(parameters)
    simplex = np.vstack((initial,initial+np.diag(steps)))

    def position(values):
        return unit(center + values[0]*e1 + values[1]*e2)*(math.exp(values[2]) if radius is None else radius)

    best = None
    def loss(values):
        nonlocal best
        point = position(values)
        q = evaluate(point)
        if q is None:
            return math.inf
        if best is None or q['log_score']>best['log_score']:
            best = dict(q,source_mm=point.tolist(),center_distance_mm=math.hypot(*point))
        return -q['log_score']

    if evaluate(position(initial)) is None:
        return dict(status='start_unavailable',start_mm=list(start),best=None)
    result = minimize(loss,initial,method='Nelder-Mead',bounds=bounds,options=dict(initial_simplex=simplex,
                      maxfev=max_evals,xatol=1e-6,fatol=1e-5))
    return dict(status='converged' if result.success else 'optimizer_stopped',message=str(result.message),
                function_evaluations=int(result.nfev),start_mm=list(start),best=best)


def chosen_indices(profile,points,external_mask,ndirections,starts,*,shell=None,ranks=None):
    stored = profile['external_geometric_view'] or profile
    field = profile['grid_scores']['normalized_known_mass_log_score'] if ranks is None else ranks
    order = np.argsort(-np.asarray(field),kind='stable')
    selected,directions = [],set()
    for i in order:
        j = int(i)%ndirections
        if not external_mask[i] or j in directions or (shell is not None and int(i)//ndirections!=shell):
            continue
        selected.append(int(i))
        directions.add(j)
        if len(selected)==starts:
            break
    if shell is None and ranks is None and selected:
        W.require(selected[0]==stored['highest_tested_grid_index'],'External grid start no longer matches the frozen winner')
    return selected


def best_attempt(tries):
    valid = [r['best'] for r in tries if r['best'] is not None]
    return max(valid,key=lambda q:q['log_score']) if valid else None


def compare_validation(opt,coarse_check,fine_check):
    return dict(source_mm=opt['source_mm'],center_distance_mm=opt['center_distance_mm'],
                training=opt,independent_coarse=coarse_check,independent_fine=fine_check)


def profile_cohort(label,cfg,points,radii,nd,grid,resp,norm,pilot):
    coarse,fine = norm.powers
    def training(point,power=coarse):
        return objective(resp,norm,label,power,norm.original,point)

    external = [exterior(resp.crystal,p) for p in points]
    starts = chosen_indices(grid,points,external,nd,cfg.starts)
    # Independent arithmetic through the continuous objective at existing grid maxima.
    parity = []
    for j in starts:
        current = training(points[j],fine)
        old = grid['grid_scores']['normalized_known_mass_log_score'][j]
        W.require(current is not None and abs(current['log_score']-old)<1e-8,'Continuous scorer differs at a frozen grid start')
        parity.append(dict(grid_index=j,abs_log_score_difference=abs(current['log_score']-old)))
    free = [local_fit(training,points[j],radii,cfg.max_evals,cfg.angular_step) for j in starts]
    found = best_attempt(free)
    W.require(found is not None,'No complete exterior response among the blind starts')
    fine_fit = local_fit(lambda p:training(p,fine),found['source_mm'],radii,cfg.max_evals,cfg.angular_step/4)
    final = fine_fit['best']
    W.require(final is not None,'The fine training response remains incomplete')

    def assess(p):
        def check(power):
            return objective(resp,norm,label,power,norm.validation,np.asarray(p['source_mm']))
        return compare_validation(p,check(coarse),check(fine))

    profile = []
    shells = [int(grid['highest_tested_radial_index'])] if pilot else range(len(radii))
    for shell in shells:
        radius = radii[shell]
        picks = chosen_indices(grid,points,external,nd,1,shell=shell)
        directions = [points[i] for i in picks]+[final['source_mm']]
        tries = [local_fit(training,s,radii,cfg.profile_max_evals,cfg.angular_step,radius=radius) for s in directions]
        found = best_attempt(tries)
        profile.append(dict(radial_index=shell,radius_mm=radius,direction_fits=tries,
            selected=assess(found) if found is not None else None))
    legacy_j = (grid['external_geometric_view'] or grid)['highest_tested_grid_index']
    legacy = training(points[legacy_j],fine)
    compare_grid = assess(dict(legacy,source_mm=points[legacy_j].tolist(),center_distance_mm=math.hypot(*points[legacy_j])))
    return dict(starts=starts,frozen_grid_parity=parity,multistart_coarse=free,local_fine_fit=fine_fit,
                selected=assess(final),fixed_grid_comparison=compare_grid,radial_profile=profile)


def run(args):
    started = time.perf_counter()
    W.require(not args.output.exists(),'Select a fresh continuous blind output path')
    observations,plan,basis,rates,crystal,points,cohorts,keys,branches = forward.inputs(args)
    blind,norm = W.read(args.fixed_blind),W.read(args.normalization)
    observation_hash = W.sha(args.observations)
    W.require(blind['kind']==fixed.BLIND_KIND and blind['observations_sha256']==observation_hash and
        W.digest(blind['measured_analysis'])==blind['blind_fit_sha256'] and
        blind['normalization_sha256']==W.sha(args.normalization) and norm['basis']==basis and
        len(set(args.validation_seed))==len(args.validation_seed) and not (set(args.validation_seed)&set(norm['seed'])) and
        len(args.validation_seed)>=2,'Use the sealed fixed-grid blind result and independent validation scrambles')
    bank_hash = W.sha(args.bank)
    info,rows = fixed.load_bank(args.bank,observation_hash,basis,keys,cohorts)
    extension_hash = W.sha(args.curve_overlay)
    W.require(blind['curve_bank_sha256']==bank_hash and blind['curve_overlay_sha256']==extension_hash,'Curve banks differ from blind baseline')
    _,extensions = fixed.overlay.replacements(args.curve_overlay,bank_hash,info,rows)
    rows |= extensions
    cfg = dict(azimuth_samples=info['settings']['azimuth_samples'],max_log_error_target=info['settings']['max_log_error_target'],
               endpoint_orders=args.endpoint_order)
    W.require(cfg['endpoint_orders']==sorted(set(cfg['endpoint_orders'])) and min(cfg['endpoint_orders'])>=2 and
        args.starts>0 and args.max_evals>0 and args.profile_max_evals>0 and math.isfinite(args.angular_step) and args.angular_step>0.,
        'Use increasing numerical orders and explicit positive search settings')
    radii,nd = plan['trial_grid']['radii_mm'],len(plan['trial_grid']['unit_vectors'])
    norm_model = Normalizers(crystal,rates,observations['incident_keV'],norm,args.validation_seed)
    recipe = dict(kind='gegi_ideal_forward_continuous_endpoint_store_v1',basis=basis,observation_sha256=observation_hash,
        source_sha256={Path(p).name:W.sha(p) for p in (__file__,fast.__file__,fast.gaussian.__file__,photon.__file__)},
        curve_bank_sha256=bank_hash,overlay_sha256=extension_hash,settings=cfg)
    with closing(sqlite3.connect(args.endpoint_store)) as db:
        forward.bank.create_bank(db,recipe)
        resp = Response(crystal,rates,observations,branches,rows,db,cfg)
        out = {}
        for label,c in blind['measured_analysis']['cohorts'].items():
            W.require(c['scored_attempt_ids']==[e['attempt_id'] for e in cohorts[label]['first_accepted']],
                      'The continuous fit cannot silently alter the sealed event support')
            t = time.perf_counter()
            out[label] = dict(profile_cohort(label,args,points,radii,nd,c['profile'],resp,norm_model,args.pilot),
                              scored_attempt_ids=c['scored_attempt_ids'],all_accepted_count=c['all_accepted_count'],
                              retained_for_expansion_count=c['retained_for_expansion_count'])
            print(dict(cohort=label,elapsed_seconds=time.perf_counter()-t,
                       chosen_source_mm=out[label]['selected']['source_mm']),flush=True)
        endpoint_stats = dict(total_unique=len(resp.endpoint),unresolved=sum(not p['accepted'] for p in resp.endpoint.values()))
    fit = dict(cohorts=out,source_geometry='Exterior geometric view of the existing full-sphere trial domain.',
        unrestricted_continuous_singularity=dict(witnesses=singular_witnesses(cohorts,crystal,radii),
            cause='The point-source first-arrival density diverges as inverse squared distance at the observed vertex.'),
        accepted_incident_keV=observations['incident_keV'],sigma_site_keV=observations['sigma_site_keV'],
        mode='one_shell_pilot' if args.pilot else 'full_radial_profile',
        fitted_trial_radius_bounds_mm=(radii[0],radii[-1]),radial_sample_mm=radii,
        settings=dict(cfg,starts=args.starts,max_evals=args.max_evals,profile_max_evals=args.profile_max_evals,
            angular_step=args.angular_step,training_seeds=norm['seed'],independent_validation_seeds=args.validation_seed,
            nested_sample_powers=norm['sample_powers']),
        objective_census=dict(source_normalizer_components_computed=norm_model.computed,numerator_cached_points=len(resp.cache),
            endpoint=endpoint_stats,curve_state_counts=dict(resp.state_count)))
    result = dict(kind=FIT_KIND,observation_sha256=observation_hash,fixed_blind_sha256=W.sha(args.fixed_blind),
        normalization_sha256=W.sha(args.normalization),endpoint_store_sha256=W.sha(args.endpoint_store),
        fixed_curve_bank_sha256=bank_hash,curve_overlay_sha256=extension_hash,source_sha256=recipe['source_sha256'] |
        {Path(p).name:W.sha(p) for p in (shared.__file__,arrival.__file__,fixed.__file__)},
        software=forward.bank.software(),blind_fit_sha256=W.digest(fit),fit=fit,elapsed_seconds=time.perf_counter()-started)
    with args.output.open('xb') as stream:
        stream.write(W.encoded(result)+b'\n')
    print(dict(blind_sha256=W.sha(args.output),elapsed_seconds=result['elapsed_seconds']))


def truth_score(args):
    W.require(not args.output.exists(),'Select a fresh continuous truth score path')
    blind = W.read(args.blind)
    fit = blind['fit']
    W.require(blind['kind']==FIT_KIND and fit['mode']=='full_radial_profile' and
              W.digest(fit)==blind['blind_fit_sha256'],'Verify the complete sealed continuous fit before reading truth')
    truth = W.read(args.truth)
    W.require(truth['kind']==fixed.TRUTH_KIND and truth['observations_sha256']==blind['observation_sha256'],
              'Truth reference does not match the unchanged forward observations')
    values = {}
    for record in truth['cohorts']:
        label = record['cohort_id']
        c = fit['cohorts'][label]
        ids = c['scored_attempt_ids']
        W.require(len(record['accepted_events'])==c['all_accepted_count'] and
                  ids==[x['attempt_id'] for x in record['accepted_events'][:len(ids)]],
                  'Continuous post-score changed accepted observation identity')
        actual = record['source_mm']
        def compare(result):
            predicted = result['source_mm']
            return dict(source_mm=predicted,position_difference_mm=math.dist(actual,predicted),
                angular_difference_deg=fixed.source.reference_io.angle_between(actual,predicted),
                range_difference_mm=math.hypot(*predicted)-math.hypot(*actual))

        radius = math.hypot(*actual)
        complete = [q for q in c['radial_profile'] if q['selected'] is not None]
        nearest = min(complete,key=lambda x:abs(x['radius_mm']-radius))
        values[label] = dict(ideal_source_mm=actual,source_center_distance_mm=radius,
            continuous=compare(c['selected']), fixed_external_grid=compare(c['fixed_grid_comparison']),
            nearest_prespecified_radius_mm=nearest['radius_mm'],
            nearest_radius_profile=compare(nearest['selected']),scored_attempt_ids=ids)
    W.require(values.keys()==fit['cohorts'].keys(),'Missing held-out source geometry')
    record = dict(kind='gegi_ideal_forward_continuous_truth_score_v1',blind_sha256=W.sha(args.blind),
                  blind_fit_sha256=blind['blind_fit_sha256'],truth_sha256=W.sha(args.truth),cohorts=values,
                  source_sha256={Path(__file__).name:W.sha(__file__)})
    with args.output.open('xb') as stream:
        stream.write(W.encoded(record)+b'\n')
    print(values)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    stages = p.add_subparsers(dest='stage',required=True)
    fit = stages.add_parser('fit')
    forward.common(fit)
    for name in ('fixed-blind','normalization','bank','curve-overlay','endpoint-store','output'):
        fit.add_argument('--'+name,type=Path,required=True)
    fit.add_argument('--validation-seed',type=int,action='append',required=True)
    fit.add_argument('--endpoint-order',type=int,action='append',required=True)
    fit.add_argument('--starts',type=int,default=4)
    fit.add_argument('--max-evals',type=int,default=190)
    fit.add_argument('--profile-max-evals',type=int,default=100)
    fit.add_argument('--angular-step',type=float,default=.075)
    fit.add_argument('--pilot',action='store_true')
    fit.set_defaults(run=run)
    truth = stages.add_parser('score-truth')
    for name in ('blind','truth','output'):
        truth.add_argument('--'+name,type=Path,required=True)
    truth.set_defaults(run=truth_score)
    args = p.parse_args()
    args.run(args)


if __name__=='__main__':
    main()
