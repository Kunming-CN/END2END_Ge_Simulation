"""Score declared ideal forward observations on the fixed normalized source grid."""

import argparse
from contextlib import closing
from collections import Counter
import json
import math
from pathlib import Path
import sqlite3
import time

import numpy as np

import gegi_candidate_grid_response as grid
import gegi_first_compton_arrival as arrival
import gegi_ideal_forward_curve_overlay as overlay
import gegi_ideal_forward_reconstruction as forward
import gegi_normalized_source_diagnostic as source
import gegi_trial_joint_photon_response as joint
import scenario_workflow as W


BLIND_KIND = 'gegi_ideal_forward_source_score_v1'
TRUTH_KIND = 'gegi_ideal_forward_truth_v1'


def load_bank(path,observation_hash,basis,keys,cohorts):
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        info = json.loads(db.execute('SELECT recipe FROM manifest WHERE id=1').fetchone()[0])
        rows = {k:json.loads(r) for k,r in db.execute('SELECT curve,summary FROM curves')}
    W.require(info['kind']==forward.BANK_KIND and info['scope']=='declared_observation_bank' and info['basis']==basis and
        info['observation_sha256']==observation_hash and set(info['scheduled_curve_keys'])==keys.keys() and rows.keys()==keys.keys() and
        info['curves']=={k:dict(model=v['model'],domain_keV=v['domain_keV']) for k,v in keys.items()} and all(
            info['cohorts'][c]['first_accepted_attempt_ids']==[e['attempt_id'] for e in cohort['first_accepted']]
            for c,cohort in cohorts.items()),'Use the completed curve bank for the exact declared observations')
    return info,rows


def observed_log_densities(observations,points,crystal,rates,branches,keys,rows):
    conditional = grid.evaluate_arrays(rows,keys,branches,len(points),
                                       {'sigma_first_keV':observations['sigma_site_keV'][0]},rates)
    energy = observations['incident_keV']
    c,_ = forward.bank.trial.rate_functions(rates)
    rate = c(energy)
    log_first = np.full(conditional['log_absorption_per_mm3_keV2'].shape,np.nan)
    for i,b in enumerate(branches):
        if b['geometry_status']!='available_geometry':
            continue
        for j,point in enumerate(points):
            log = arrival.first_compton_arrival(crystal,point,b['first_fitted_mm'],rate)['log_first_compton_per_emitted_photon_mm3']
            if log is not None:
                log_first[i,j] = log
    return {h:joint.join_density(log_first,conditional[f'log_{h}_per_mm3_keV2']) for h in ('absorption','escape')}


def compute_blind(observations,cohorts,points,branches,conditional,normalization):
    cases = normalization['normalization_cases']
    W.require(normalization['trial_scope']=='full_declared_grid' and [p['grid_index'] for p in cases]==list(range(len(points))) and
              np.array_equal([p['source_mm'] for p in cases],points),'Use every point of the original normalized grid')
    scope = {(label,e['attempt_id']):i for i,(label,e) in enumerate(
        (c,event) for c,s in cohorts.items() for event in s['first_accepted'])}
    group_values = {label:[] for label in cohorts}
    group_ledger = {label:[] for label in cohorts}
    for key,index in scope.items():
        label,attempt = key
        slots = slice(2*index,2*index+2)
        bb = branches[slots]
        W.require([(b['cohort_id'],b['attempt_id'],tuple(b['site_index_order'])) for b in bb]==[
            (label,attempt,o) for o in forward.ORDERS],'Randomized observation labels or attempt identity changed')
        logs,mass = source.event_mixture([.5,.5],conditional['absorption'][slots],conditional['escape'][slots])
        eligible = not np.isnan(logs).any()
        group_ledger[label].append(dict(attempt_id=attempt,profile_eligible=eligible,
            original_labels=[0,1],compared_orders=[list(o) for o in forward.ORDERS],
            minimum_computed_order_mass=float(mass.min()), maximum_computed_order_mass=float(mass.max()),
            complete_trial_points=int(np.count_nonzero(~np.isnan(logs))),
            curve_keys=[b.get('curve_key') for b in bb]))
        if eligible:
            group_values[label].append(logs)
    fits = {}
    for label,ledger in group_ledger.items():
        included = [r['attempt_id'] for r in ledger if r['profile_eligible']]
        output = source.compare_scores(cases,observations['incident_keV'],np.sum(group_values[label],axis=0),len(included)) if included else None
        fits[label] = dict(all_accepted_count=cohorts[label]['all_accepted_count'],selected_events=ledger,
            retained_for_expansion_count=cohorts[label]['retained_for_expansion_count'],scored_attempt_ids=included,
            unknown_attempt_ids=[r['attempt_id'] for r in ledger if not r['profile_eligible']],profile=output)
    return dict(cohorts=fits,trial_points=len(cases),incident_keV=observations['incident_keV'],
                sigma_site_keV=observations['sigma_site_keV'],
                scope='Ideal forward validation with the independent recorded site labels. Two random relabelings contribute '
                      'equal order shares and absorption and escape are summed within an order. Each event is counted once. '
                      'Ideal topology mass normalizes each trial over its emitted photons. This is a finite-grid diagnostic.')


def score(args):
    started = time.perf_counter()
    W.require(not args.output.exists(),'Select a fresh source-blind output path')
    observations,_,basis,rates,crystal,points,cohorts,keys,branches = forward.inputs(args)
    ohash = W.sha(args.observations)
    normalization = W.read(args.normalization)
    W.require(normalization['basis']==basis,'Forward observations and normalizers use different material or grid inputs')
    bank_hash = W.sha(args.bank)
    info,rows = load_bank(args.bank,ohash,basis,keys,cohorts)
    extension_hash,extension = None,None
    if args.curve_overlay is not None:
        extension_hash = W.sha(args.curve_overlay)
        extension,refined = overlay.replacements(args.curve_overlay,bank_hash,info,rows)
        rows |= refined
    densities = observed_log_densities(observations,points,crystal,rates,branches,keys,rows)
    blind = compute_blind(observations,cohorts,points,branches,densities,normalization)
    W.require(W.sha(args.bank)==bank_hash and W.sha(args.observations)==ohash,
              'Observation or bank changed during source-blind scoring')
    if extension_hash is not None:
        W.require(W.sha(args.curve_overlay)==extension_hash,'Forward-curve refinement changed during scoring')
    result = dict(kind=BLIND_KIND,observations_sha256=ohash,normalization_sha256=W.sha(args.normalization),
        curve_bank_sha256=bank_hash,curve_status_counts=dict(Counter(r['status'] for r in rows.values())),
        curve_overlay_sha256=extension_hash,curve_overlay_recipe=extension,
        curve_producers=info['source_sha256'],source_sha256={Path(f).name:W.sha(f) for f in (
            __file__,forward.__file__,grid.__file__,arrival.__file__,source.__file__,joint.__file__)},
        software=forward.bank.software(), blind_fit_sha256=W.digest(blind), measured_analysis=blind,
        elapsed_seconds=time.perf_counter()-started)
    with args.output.open('xb') as stream:
        stream.write(W.encoded(result)+b'\n')
    print(dict(grid_points=len(points),cohorts={k:len(s['scored_attempt_ids']) for k,s in blind['cohorts'].items()},
               blind_file_sha256=W.sha(args.output)))


def truth_score(args):
    W.require(not args.output.exists(),'Select a fresh truth-comparison output path')
    blind = W.read(args.blind)
    measurement = blind['measured_analysis']
    W.require(blind['kind']==BLIND_KIND and W.digest(measurement)==blind['blind_fit_sha256'],
              'Verify sealed source-blind scores before opening truth')
    truth = W.read(args.truth)
    W.require(truth['kind']==TRUTH_KIND and truth['observations_sha256']==blind['observations_sha256'],
              'The scoring truth must match the sealed observations')
    values = {}
    for c in truth['cohorts']:
        label = c['cohort_id']
        outcome = measurement['cohorts'][label]
        ids = [x['attempt_id'] for x in outcome['selected_events']]
        events = {x['attempt_id']:x for x in c['accepted_events']}
        W.require(len(events)==outcome['all_accepted_count'] and ids==[x['attempt_id'] for x in c['accepted_events'][:len(ids)]],
                  'Truth join changed accepted order or measurement scope')
        position = c['source_mm']
        local = {}
        if outcome['profile'] is not None:
            r = outcome['profile']
            profiles = [('full_grid',r),('external_geometry',r['external_geometric_view'])]
            for view,s in profiles:
                if s is not None:
                    point = s['highest_tested_source_mm']
                    local[view] = dict(highest_tested_grid_index=s['highest_tested_grid_index'],
                        position_difference_mm=math.dist(position,point),
                        angular_difference_deg=source.reference_io.angle_between(position,point),
                        range_difference_mm=math.hypot(*point)-math.hypot(*position))
        values[label] = dict(source_mm=position,selected_attempt_ids=ids,
                             branch_counts=dict(Counter(events[i]['accepted_branch'] for i in ids)),comparisons=local)
    W.require(values.keys()==measurement['cohorts'].keys(),'The scored cohorts must remain complete')
    payload = dict(kind='gegi_ideal_forward_source_truth_score_v1',blind_output_sha256=W.sha(args.blind),
                   blind_fit_sha256=blind['blind_fit_sha256'],truth_sha256=W.sha(args.truth),
                   source_sha256={Path(__file__).name:W.sha(__file__)},cohorts=values)
    with args.output.open('xb') as stream:
        stream.write(W.encoded(payload)+b'\n')
    print(values)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='stage',required=True)
    fit = sub.add_parser('score')
    forward.common(fit)
    for name in ('bank','normalization','output'):
        fit.add_argument('--'+name,type=Path,required=True)
    fit.add_argument('--curve-overlay',type=Path)
    fit.set_defaults(run=score)
    t = sub.add_parser('score-truth')
    for name in ('blind','truth','output'):
        t.add_argument('--'+name,type=Path,required=True)
    t.set_defaults(run=truth_score)
    args = p.parse_args()
    args.run(args)


if __name__=='__main__':
    main()
