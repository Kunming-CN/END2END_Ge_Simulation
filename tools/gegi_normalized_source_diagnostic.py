"""Score the saved GeGI cohorts on declared points under the ideal topology measure."""

import argparse
from collections import Counter, defaultdict
import math
from pathlib import Path
import time

import numpy as np
from scipy.special import logsumexp

import gegi_incident_range_controls as reference_io
import scenario_workflow as W


def event_mixture(weights, absorption, escape):
    """Marginalize topology, then the original pairing and two diagnostic order weights."""
    weights = np.asarray(weights,dtype=float)
    a,e = np.asarray(absorption),np.asarray(escape)
    known = (np.isfinite(a)|np.isneginf(a)) & (np.isfinite(e)|np.isneginf(e))
    mass = np.sum(weights[:,None]*known,axis=0)
    terms = np.logaddexp(np.where(known,a,-np.inf),np.where(known,e,-np.inf))+np.log(weights)[:,None]
    result = logsumexp(terms,axis=0)
    complete = np.isclose(mass,1.,atol=1e-12,rtol=0.)
    result[~complete] = np.nan
    return result,mass


def prepare_events(joint,a,e,lines,indices):
    rows = defaultdict(list)
    for i,b in enumerate(joint['branch_rows']):
        rows[b['original_trigger_id'],b['incident_keV']].append((i,b))
    manifest, values = {}, {}
    for trigger in joint['measured_triggers']:
        tid = trigger['original_trigger_id']
        pair_weight = {p['pair_index']:p['original_pair_mass'] for p in trigger['pairs']}
        covered = {}
        for energy in lines:
            entries = [(i,pair_weight[b['pair_index']]/2) for i,b in rows[tid,energy] if pair_weight[b['pair_index']]]
            if entries:
                ii,weights = zip(*entries)
                result,mass = event_mixture(weights,a[np.ix_(ii,indices)],e[np.ix_(ii,indices)])
            else:
                result,mass = np.full(len(indices),np.nan),np.zeros(len(indices))
            covered[energy] = dict(minimum_computed_pair_order_mass=float(mass.min()),
                                   maximum_computed_pair_order_mass=float(mass.max()),
                                   complete_point_count=int(np.count_nonzero(~np.isnan(result))))
            values[tid,energy] = result
        manifest[tid] = dict(trigger,diagnostic_line_coverage_keV=[dict(incident_keV=energy,**s) for energy,s in covered.items()],
            diagnostic_complete=all(c['complete_point_count']==len(indices) for c in covered.values()))
    return manifest,values


def point_probabilities(cases,line):
    entries = [next(x for x in p['lines'] if x['incident_keV']==line) for p in cases]
    fine = np.array([e['estimates'][-1]['known_topology_probability'] for e in entries])
    coarse = np.array([e['estimates'][0]['known_topology_probability'] for e in entries])
    gap = np.array([e['uninitialized_exit_mass_analytic_upper_bound'] for e in entries])
    seeds = [[s['seed'] for s in e['seed_results']] for e in entries]
    W.require(all(s==seeds[0] for s in seeds),'Normalized grid points must use the same Sobol streams')
    by_seed = np.array([[s['estimates'][-1]['contained_photoelectric']+
                         s['estimates'][-1]['known_compton_and_escape'] for s in e['seed_results']] for e in entries])
    W.require(np.all(fine>0.) and np.all(coarse>0.) and np.all(by_seed>0.),
              'Known normalizer mass is required on the declared comparison grid')
    return fine,coarse,gap,by_seed,seeds[0]


def compare_scores(cases,line,raw,event_count):
    fine,coarse,gap,replicates,seeds = point_probabilities(cases,line)
    scores = raw-event_count*np.log(fine)
    coarse_scores = raw-event_count*np.log(coarse)
    by_seed = raw[:,None]-event_count*np.log(replicates)
    lower = raw-event_count*np.log(fine+gap)
    full = characterize_grid(cases,raw,scores,coarse_scores,by_seed,np.arange(len(cases)))
    external = np.array([i for i,p in enumerate(cases) if p['source_region']=='outside_ge'],dtype=int)
    return dict(incident_keV=line, **full,
                external_geometric_view=characterize_grid(cases,raw,scores,coarse_scores,by_seed,external)
                    if 0<len(external)<len(cases) else None,
                largest_coarse_fine_score_difference=float(np.max(np.abs(scores-coarse_scores))),
                seed=seeds,grid_scores=dict(grid_indices=[p['grid_index'] for p in cases],joint_log_score=raw.tolist(),
                    normalized_known_mass_log_score=scores.tolist(),
                    normalized_with_missing_exit_upper_bound_log_score=lower.tolist(),
                    normalized_coarse_log_score=coarse_scores.tolist(),normalized_seed_log_scores=by_seed.tolist(),
                    known_topology_probability=fine.tolist()))


def characterize_grid(cases,raw,scores,coarse,by_seed,indices):
    ix = int(indices[np.argmax(scores[indices])])
    peak = cases[ix]
    shells = defaultdict(list)
    for i in indices:
        shells[cases[i]['radial_index']].append(i)
    radius = peak['radial_index']
    low,high = min(shells),max(shells)
    radial_boundary = ('only_tested_radius' if low==high else 'minimum_tested_radius' if radius==low else
                       'maximum_tested_radius' if radius==high else 'radial_interior')
    radial_profile = []
    for shell,subset in sorted(shells.items()):
        i = subset[int(np.argmax(scores[subset]))]
        p = cases[i]
        radial_profile.append(dict(radial_index=shell, radius_mm=math.hypot(*p['source_mm']),grid_index=p['grid_index'],
            direction_index=p['direction_index'],source_region=p['source_region'], score_drop=float(scores[ix]-scores[i])))
    neighbors = sorted((reference_io.angle_between(peak['source_mm'],cases[i]['source_mm']),i)
                       for i in shells[radius] if i!=ix)[:4]
    other = indices[indices!=ix]
    return dict(highest_tested_grid_index=peak['grid_index'],highest_tested_source_mm=peak['source_mm'],
                highest_tested_source_region=peak['source_region'],highest_tested_radial_index=radius,
                highest_tested_direction_index=peak['direction_index'],radial_boundary_status=radial_boundary,
                best_known_mass_log_score=float(scores[ix]),highest_raw_grid_index=cases[indices[np.argmax(raw[indices])]]['grid_index'],
                best_to_next_score_difference=float(scores[ix]-scores[other].max()) if other.size else None,
                coarse_highest_grid_index=cases[indices[np.argmax(coarse[indices])]]['grid_index'],
                seed_highest_grid_indices=[cases[indices[i]]['grid_index'] for i in np.argmax(by_seed[indices],axis=0)],
                radial_profile=radial_profile,nearest_sampled_directions=[dict(grid_index=cases[i]['grid_index'],
                    angle_deg=angle,score_drop=float(scores[ix]-scores[i])) for angle,i in neighbors])


def fit_blind(joint,normalization,arrays):
    full = normalization.get('trial_scope')=='full_declared_grid'
    role = 'full_grid' if full else 'outer_pilot'
    cases = [point for point in normalization['normalization_cases'] if point['role']==role]
    W.require(bool(cases),'The diagnostic needs declared points with normalizers')
    indices = [p['grid_index'] for p in cases]
    if full:
        W.require(indices==list(range(len(arrays['trial_positions_mm']))),'The full diagnostic must preserve every trial point')
    W.require(np.array_equal(arrays['trial_positions_mm'][indices],np.array([p['source_mm'] for p in cases])) and
              [joint['source_region_codes'][i] for i in arrays['trial_source_region'][indices]] ==
              [p['source_region'] for p in cases], 'Normalized and joint grid coordinates differ')
    lines = sorted({p['incident_keV'] for p in cases[0]['lines']})
    W.require(all(sorted(l['incident_keV'] for l in p['lines'])==lines for p in cases),'Modeled incident lines differ')
    a,e = (arrays[f'log_{h}_per_emitted_photon_mm6_keV2'] for h in ('absorption','escape'))
    events,values = prepare_events(joint,a,e,lines,indices)
    groups = {}
    for label,group in joint['measured_cohorts'].items():
        ids = group['selected_original_trigger_ids']
        supported = [tid for tid in ids if events[tid]['diagnostic_complete']]
        profiles = []
        if supported:
            for line in lines:
                raw = np.sum([values[tid,line] for tid in supported],axis=0)
                profiles.append(compare_scores(cases,line,raw,len(supported)))
        groups[label] = dict(group, fixed_supported_trigger_ids=supported,
            unknown_trigger_ids=[tid for tid in ids if tid not in supported], hypotheses=profiles)
    W.require({i for r in groups.values() for i in r['selected_original_trigger_ids']}==events.keys(),
              'The diagnostic must retain all original cohorts and trigger records')
    return dict(measured_groups=groups,measured_triggers=list(events.values()),
            scored_points=[{k:v for k,v in p.items() if k not in ('lines','timing_seconds')} for p in cases],
            trial_grid=joint['trial_grid'], joint_source_region_counts=joint['source_region_counts'],
            trial_scope='full_declared_grid' if full else 'prespecified_outer_pilot',
            scope='Per-trigger log mixtures use the sum of modeled absorption and escape densities and the original compatible '
                  'pairing mass split equally between both orders. Each fixed incident line divides by the sum of the corresponding '
                  'ideal topology masses at that trial point. The fixed supported triggers have complete modeled mass on every '
                  'tested point and line. Unknown triggers retain their original ledger and have undefined ideal scores. '
                  'This ranks only the declared grid points. A separate external view uses the Ge boundary alone. '
                  'Source activity, ADC candidate-selection efficiency, '
                  'passive attenuation and calibrated confidence remain outside this diagnostic.')


def score_after(blind, origins_path, truth_path):
    origins,origins_sha = reference_io.controls.read(origins_path)
    truth,truth_sha = reference_io.controls.read(truth_path)
    W.require(truth['input_sha256']['chronological_origins']==origins_sha,'Post-score truth references differ')
    chrono = {r['original_trigger_id']:r for window in origins['science']['windows'].values() for r in window['triggers']}
    exact = {r['original_trigger_id']:r for r in truth['rows']}
    measured = {r['original_trigger_id']:r for r in blind['measured_triggers']}
    groups = {}
    for label,fit in blind['measured_groups'].items():
        coords,unknown,topologies = defaultdict(list),[],Counter()
        for tid in fit['selected_original_trigger_ids']:
            measured_record = measured[tid]['archive_record_sha256']
            q = exact[tid]
            W.require(q['original_archive_record_sha256']==measured_record and
                      q['original_archive_adc_sha256']==measured[tid]['archive_adc_sha256'], 'Post-score saved identity changed')
            topologies[q['topology']] += 1
            if fit['cohort']=='chronological_measured_window':
                event = chrono[tid]
                W.require(event['measured_window']==label and event['archive_record_sha256']==measured_record,
                          'Chronological post-score identity changed')
                pos = event.get('programmed_source_position_mm_for_scoring')
            else:
                pos = (q['photon_kinetics'] or {}).get('source_position_mm_for_scoring')
            if pos is None:
                unknown.append(tid)
            else:
                coords[tuple(pos)].append(tid)
        points = []
        for point,ids in sorted(coords.items()):
            comparison = []
            for h in fit['hypotheses']:
                winner = h['highest_tested_source_mm']
                observed = dict(incident_keV=h['incident_keV'], highest_tested_grid_index=h['highest_tested_grid_index'],
                    position_difference_mm=math.dist(point,winner), angle_difference_deg=reference_io.angle_between(winner,point),
                    center_distance_difference_mm=math.hypot(*winner)-math.hypot(*point))
                external = h['external_geometric_view']
                if external is not None:
                    v = external['highest_tested_source_mm']
                    observed['external_geometric_view'] = dict(grid_index=external['highest_tested_grid_index'],
                        position_difference_mm=math.dist(point,v),angle_difference_deg=reference_io.angle_between(v,point),
                        center_distance_difference_mm=math.hypot(*v)-math.hypot(*point))
                comparison.append(observed)
            points.append(dict(verified_source_position_mm=list(point),original_trigger_ids=ids,
                               scoring_supported_trigger_ids=[tid for tid in ids if tid in fit['fixed_supported_trigger_ids']],
                               comparisons=comparison))
        groups[label] = dict(verified_source_points=points,unknown_reference_triggers=unknown,topology_counts=dict(topologies))
    return dict(chronological_origins_sha256=origins_sha,exact_kinetics_sha256=truth_sha,cohorts=groups)


def run(args):
    start = time.perf_counter()
    W.require(not args.output.exists(),'Select a new source diagnostic path')
    joint,norm = W.read(args.joint),W.read(args.normalization)
    path = args.joint.parent/joint['dataset']['name']
    W.require(joint['basis']==norm['basis'] and W.sha(path)==joint['dataset']['sha256'],
              'The numerator and ideal topology normalizers must share their basis')
    with np.load(path) as arrays:
        blind = fit_blind(joint,norm,arrays)
    frozen = W.digest(blind)
    scored = score_after(blind,args.origins,args.truth)
    W.require(W.digest(blind)==frozen,'Post-scoring modified the source-blind outcome')
    result = dict(kind='gegi_ideal_normalized_source_diagnostic_v1',joint_grid_sha256=W.sha(args.joint),
            normalization_sha256=W.sha(args.normalization),blind_fit_sha256=frozen,measured_analysis=blind,
            post_fit_truth_scores=scored,source_sha256={Path(f).name:W.sha(f) for f in (__file__,reference_io.__file__)},
            elapsed_seconds=time.perf_counter()-start)
    with args.output.open('xb') as stream:
        stream.write(W.encoded(result)+b'\n')
    print(dict(points=len(blind['scored_points']),triggers=len(blind['measured_triggers']),
               hypotheses=sum(len(g['hypotheses']) for g in blind['measured_groups'].values())))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('joint','normalization','origins','truth','output'):
        p.add_argument('--'+name,type=Path,required=True)
    run(p.parse_args())


if __name__=='__main__':
    main()
