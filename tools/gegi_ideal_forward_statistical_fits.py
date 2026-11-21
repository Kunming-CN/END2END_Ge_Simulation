"""Blind repeatability fits for disjoint chronological ideal-observation blocks."""

import argparse
from contextlib import closing
import json
import math
from pathlib import Path
import sqlite3
import statistics
import time
from types import SimpleNamespace

import numpy as np

import gegi_ideal_forward_continuous as continuous
import gegi_ideal_forward_curve_extensions as ext
import gegi_ideal_forward_extended_profile as extended
import gegi_ideal_forward_reconstruction as forward
import gegi_ideal_forward_score as fixed
import gegi_ideal_forward_statistical_bank as stat
import gegi_normalized_source_diagnostic as scoring
import scenario_workflow as W


KIND = 'gegi_ideal_forward_blind_repeatability_v1'


def read_curves(path,recipe):
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        W.require(db.execute('SELECT recipe FROM manifest WHERE id=1').fetchone()[0]==W.encoded(recipe),
                  'Statistics bank must have the same frozen scientific recipe')
        return {key:json.loads(row) for key,row in db.execute('SELECT curve,summary FROM curves')}


def audit(args):
    started = time.perf_counter()
    W.require(not args.output.exists(),'Select a fresh positive-reference comparison receipt')
    _,_,_,_,rates,crystal,_,_,recipe = stat.setup(args)
    rows = read_curves(args.bank,recipe)
    curve_ids = {r['curve_key'] for r in recipe['additional_orders'] if r['block_id']==1}
    W.require(curve_ids<=rows.keys(),'Seal both first independent blocks before checking convergence')
    with closing(sqlite3.connect(args.bank.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        samples = [(key,e,json.loads(r)) for key,e,r in db.execute('SELECT curve,energy,response FROM samples') if key in curve_ids]
    selected = {
        'largest_fast_order_difference': max(samples,key=lambda x:x[2]['log_quadrature_difference']),
        'deepest_log_density': min(samples,key=lambda x:x[2]['log_escape_density']),
    }
    lookup,total = forward.bank.trial.rate_functions(rates)
    results = {}
    cfg = recipe['settings']
    for role,(key,e,old) in selected.items():
        model = recipe['models'][key]
        previous = []
        for order in (256,512):
            ref, = forward.bank.curve.direct_logs([e],crystal,model['first_fitted_mm'],model['second_fitted_mm'],
                model['measured_second_site_keV'],lookup,total,sigma_keV=model['sigma_second_keV'],
                azimuth_samples=cfg['azimuth_samples'],energy_order=order)
            previous.append(dict(ref,energy_order=order))
            if ref['log_quadrature_difference']<=cfg['max_log_error_target']:
                break
        delta = abs(old['log_escape_density']-ref['log_escape_density'])
        results[role] = dict(curve_key=key,original_identity=next(o for o in recipe['additional_orders'] if o['curve_key']==key),
            fast=old,positive=previous,abs_log_difference=delta,verified=delta<=cfg['max_log_error_target'] and
                ref['log_quadrature_difference']<=cfg['max_log_error_target'])
    report = dict(kind='gegi_ideal_forward_first_block_frozen_positive_comparison_v1',basis=recipe['basis'],
        recipe_sha256=W.digest(recipe),records=results,all_verified=all(r['verified'] for r in results.values()),
        source_sha256={Path(f).name:W.sha(f) for f in (__file__,stat.__file__,forward.bank.curve.__file__)},
        elapsed_seconds=time.perf_counter()-started)
    with args.output.open('xb') as stream:
        stream.write(W.encoded(report)+b'\n')
    print(dict(sha256=W.sha(args.output),results={k:(r['abs_log_difference'],r['verified']) for k,r in results.items()}))


def starts_fit(response,norm,label,grid,points,radii,nd,cfg):
    external = [continuous.exterior(response.crystal,p) for p in points]
    indices = continuous.chosen_indices(grid,points,external,nd,cfg.starts)
    coarse,fine = norm.powers
    def evaluate(point,power=coarse,seeds=None):
        return continuous.objective(response,norm,label,power,norm.original if seeds is None else seeds,np.asarray(point))

    checks = [abs(evaluate(points[i],fine)['log_score']-grid['grid_scores']['normalized_known_mass_log_score'][i]) for i in indices]
    W.require(max(checks)<1e-8,'Continuous numerator must match the same fitted grid and normalization')
    coarse_runs = [continuous.local_fit(evaluate,points[i],radii,cfg.max_evals,cfg.angular_step) for i in indices]
    found = continuous.best_attempt(coarse_runs)
    if found is None:
        return dict(status='no_complete_local_fit',starts=indices,multistart=coarse_runs)
    fine_run = continuous.local_fit(lambda p:evaluate(p,fine),found['source_mm'],radii,cfg.max_evals,cfg.angular_step/4)
    best = fine_run['best']
    if best is None:
        return dict(status='no_complete_fine_fit',starts=indices,multistart=coarse_runs,fine=fine_run)
    radius = best['center_distance_mm']
    radial = ('minimum_tested_radius' if math.isclose(radius,radii[0],rel_tol=1e-6) else
              'maximum_tested_radius' if math.isclose(radius,radii[-1],rel_tol=1e-6) else 'radial_interior')
    point = best['source_mm']
    return dict(status=fine_run['status'],starts=indices,multistart=coarse_runs,fine=fine_run,
                radial_boundary_status=radial,max_frozen_grid_difference=max(checks),
                independent_coarse=evaluate(point,coarse,norm.validation),independent_fine=evaluate(point,fine,norm.validation))


def block_grid(obs,rows,points,rates,crystal,events,label):
    keys,branches = forward.prepare(obs,{label:{'first_accepted':events}},crystal,points,rates)
    missing = [b for b in branches if b.get('curve_key') not in rows or rows[b['curve_key']]['status']!='verified_heldout_curve']
    fields = ('cohort_id','attempt_id','curve_key','site_index_order','geometry_status','measured_first_site_keV','first_fitted_mm')
    identities = [{k:b[k] for k in fields if k in b} for b in branches]
    if missing:
        return None,identities,{b['attempt_id'] for b in missing}
    values = fixed.observed_log_densities(obs,points,crystal,rates,branches,keys,rows)
    grouped = []
    for i in range(len(events)):
        span = slice(i*2,i*2+2)
        v,_ = scoring.event_mixture([.5,.5],values['absorption'][span],values['escape'][span])
        grouped.append(v)
    missing = {ev['attempt_id'] for ev,v in zip(events,grouped,strict=True) if not np.isfinite(v).all()}
    return None if missing else np.sum(grouped,axis=0).tolist(),identities,missing


def run(args):
    started = time.perf_counter()
    W.require(not args.output.exists(),'Select a fresh blind repeatability output path')
    obs,blind,plan,basis,rates,crystal,points,blocks,recipe = stat.setup(args)
    rows = read_curves(args.bank,recipe)
    old_args = SimpleNamespace(**vars(args))
    old_args.bank,old_args.first_per_cohort = args.original_bank,len(next(iter(blocks.values()))[0])
    _,_,_,_,_,_,_,old_branches,old_rows,endpoints,bindings = ext.load_inputs(old_args)
    extension,reference,norm = [W.read(p) for p in (args.extensions,args.extended_profile,args.normalization)]
    W.require(extension['bindings']==bindings and reference['kind']==continuous.FIT_KIND and
        W.digest(reference['fit'])==reference['blind_fit_sha256'] and
        reference['extension_replay']['extension_sha256']==W.sha(args.extensions) and
        blind['normalization_sha256']==W.sha(args.normalization) and norm['basis']==basis,
        'Reuse the exact baseline response, extension and normalization')
    audit_receipt = W.read(args.audit)
    W.require(audit_receipt['all_verified'] and audit_receipt['recipe_sha256']==W.digest(recipe),
              'The first independent block must agree with the frozen positive rule')
    settings = reference['fit']['settings']
    cfg = SimpleNamespace(**settings)
    normalizer = continuous.Normalizers(crystal,rates,obs['incident_keV'],norm,cfg.independent_validation_seeds)
    cases = norm['normalization_cases']
    W.require(np.array_equal(points,np.array([p['source_mm'] for p in cases])),'Normalization grid differs')
    radii,nd = plan['trial_grid']['radii_mm'],len(plan['trial_grid']['unit_vectors'])
    target = args.through_block
    W.require(1<=target<min(len(g) for g in blocks.values()),'Select the same additional extent for both cohorts')
    meta = dict(kind='gegi_ideal_forward_statistical_fit_checkpoint_v1',bank_recipe_sha256=W.digest(recipe),
        extension_sha256=W.sha(args.extensions),original_profile_sha256=W.sha(args.extended_profile),
        normalization_sha256=W.sha(args.normalization),positive_rule_audit_sha256=W.sha(args.audit),
        source_sha256={Path(p).name:W.sha(p) for p in (__file__,extended.__file__,continuous.__file__)})
    fit_records = {}
    with closing(sqlite3.connect(args.checkpoint)) as db:
        forward.bank.create_bank(db,meta)
        db.execute('CREATE TABLE IF NOT EXISTS repeatability (scope TEXT PRIMARY KEY, result BLOB NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS block_grid (scope TEXT PRIMARY KEY, result BLOB NOT NULL)')
        ready = {scope:json.loads(row) for scope,row in db.execute('SELECT scope,result FROM repeatability')}
        grids = {scope:json.loads(row) for scope,row in db.execute('SELECT scope,result FROM block_grid')}

        def seal(label,scope,ids,raw,branches,missing):
            if scope not in ready:
                now = time.perf_counter()
                data = dict(cohort_id=label,attempt_ids=ids,uncomputed_attempt_ids=sorted(missing))
                if raw is None:
                    result = dict(data,status='unavailable_response')
                else:
                    book = extended.ExtendedResponse(crystal,rates,obs,branches,old_rows|rows,db,bindings['endpoint_settings'],
                                                     extensions=extension['curves'],saved=endpoints)
                    grid = scoring.compare_scores(cases,obs['incident_keV'],np.asarray(raw),len(ids))
                    result = dict(data,**starts_fit(book,normalizer,label,grid,points,radii,nd,cfg),
                                  response_census=dict(book.state_count),fixed_grid_highest=grid['highest_tested_grid_index'])
                result['elapsed_seconds'] = time.perf_counter()-now
                with db:
                    db.execute('INSERT INTO repeatability VALUES (?,?)',(scope,W.encoded(result)))
                ready[scope] = result
                print(dict(scope=scope,status=result['status'],elapsed_seconds=result['elapsed_seconds']),flush=True)
            fit_records[scope] = ready[scope]

        for label,groups in blocks.items():
            prefix = blind['measured_analysis']['cohorts'][label]['profile']['grid_scores']['joint_log_score']
            cumulative = np.asarray(prefix)
            combined = [b for b in old_branches if b['cohort_id']==label]
            missing_prefix = set()
            for k,events in enumerate(groups[1:target+1],1):
                scope = f'{label}:block:{k}'
                ids = [e['attempt_id'] for e in events]
                keys = {o['curve_key'] for o in recipe['additional_orders'] if o['cohort_id']==label and o['block_id']==k}
                W.require(keys<=rows.keys(),'Complete the selected curve blocks before performing their blind fits')
                if scope not in grids:
                    raw,branches,missing = block_grid(obs,rows,points,rates,crystal,events,label)
                    block = dict(raw=raw,branches=branches,missing=sorted(missing))
                    with db:
                        db.execute('INSERT INTO block_grid VALUES (?,?)',(scope,W.encoded(block)))
                    grids[scope] = block
                block = grids[scope]
                missing = set(block['missing'])
                seal(label,scope,ids,block['raw'],block['branches'],missing)
                combined.extend(block['branches'])
                missing_prefix |= missing
                if block['raw'] is not None:
                    cumulative = cumulative+np.asarray(block['raw'])
                all_ids = [e['attempt_id'] for group in groups[:k+1] for e in group]
                if len(all_ids) in (50,100):
                    seal(label,f'{label}:cumulative:{len(all_ids)}',all_ids,
                         None if missing_prefix else cumulative.tolist(),combined,missing_prefix)
    measured = dict(by_scope=fit_records,through_block=target,settings=settings,
        chronological_blocks=recipe['chronological_blocks'],development_block=0,counts=dict(
            declared_observations=sum(len(g) for cohort in blocks.values() for g in cohort),phase_fits=len(fit_records)))
    result = dict(kind=KIND,observation_sha256=recipe['observation_sha256'],blind_fit_sha256=W.digest(measured),
        measured=measured,checkpoint_sha256=W.sha(args.checkpoint),bookkeeping=meta,elapsed_seconds=time.perf_counter()-started)
    with args.output.open('xb') as stream:
        stream.write(W.encoded(result)+b'\n')
    print(dict(fits=len(fit_records),sha256=W.sha(args.output),elapsed_seconds=result['elapsed_seconds']),flush=True)


def truth(args):
    W.require(not args.output.exists(),'Select a fresh repeatability truth score path')
    blind = W.read(args.blind)
    data = blind['measured']
    W.require(blind['kind']==KIND and W.digest(data)==blind['blind_fit_sha256'] and
        all(data['through_block']==len(groups)-1 for groups in data['chronological_blocks'].values()),
        'Verify the sealed complete blind fits before opening truth')
    reference = W.read(args.truth)
    W.require(reference['kind']==fixed.TRUTH_KIND and reference['observations_sha256']==blind['observation_sha256'],
              'Truth belongs to different observations')
    results = {}
    for cohort in reference['cohorts']:
        label,target = cohort['cohort_id'],cohort['source_mm']
        names = data['chronological_blocks'][label]
        W.require([i for part in names for i in part]==[e['attempt_id'] for e in cohort['accepted_events']],
                  'Accepted observation identities changed after fitting')
        blocks,cumulative = [],[]
        for scope,fit in data['by_scope'].items():
            if fit['cohort_id']!=label:
                continue
            mode = scope.split(':')[1]
            record = dict(scope=scope,attempt_ids=fit['attempt_ids'],status=fit['status'],
                          uncomputed_attempt_ids=fit['uncomputed_attempt_ids'])
            best = fit.get('fine',{}).get('best')
            if best is not None:
                point = best['source_mm']
                record.update(source_mm=point,position_error_mm=math.dist(point,target),
                    angular_error_deg=fixed.source.reference_io.angle_between(point,target),
                    signed_range_error_mm=math.hypot(*point)-math.hypot(*target),
                    radial_boundary_status=fit['radial_boundary_status'])
            (blocks if mode=='block' else cumulative).append(record)
        comparable = [r for r in blocks if r['status']=='converged']
        spread = {}
        for k in ('position_error_mm','angular_error_deg','signed_range_error_mm'):
            values = [r[k] for r in comparable]
            spread[k] = dict(median=statistics.median(values),bounds=[min(values),max(values)]) if values else None
        results[label] = dict(reference_source_mm=target,independent_blocks=blocks,cumulative=cumulative,
                              delimited_repeatability=spread,converged=len(comparable),declared=len(blocks))
    result = dict(kind='gegi_ideal_forward_repeatability_truth_score_v1',blind_sha256=W.sha(args.blind),
                  blind_fit_sha256=blind['blind_fit_sha256'],truth_sha256=W.sha(args.truth),cohorts=results,
                  scope='Descriptive held-out errors at two ideal external sources. Cumulative fits share observations.')
    with args.output.open('xb') as stream:
        stream.write(W.encoded(result)+b'\n')
    print(dict(output_sha256=W.sha(args.output),cohorts={k:(r['converged'],r['declared']) for k,r in results.items()}))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    stages = p.add_subparsers(dest='mode',required=True)
    a = stages.add_parser('audit-first-block')
    f = stages.add_parser('fit')
    t = stages.add_parser('score-truth')
    for s in (a,f):
        stat.common(s)
        s.add_argument('--output',type=Path,required=True)
    for name in ('original-bank','curve-overlay','saved-endpoints','extensions','extended-profile',
                 'normalization','audit','checkpoint'):
        f.add_argument('--'+name,type=Path,required=True)
    f.add_argument('--through-block',type=int,required=True)
    for name in ('blind','truth','output'):
        t.add_argument('--'+name,type=Path,required=True)
    a.set_defaults(run=audit)
    f.set_defaults(run=run)
    t.set_defaults(run=truth)
    args = p.parse_args()
    args.run(args)


if __name__=='__main__':
    main()
