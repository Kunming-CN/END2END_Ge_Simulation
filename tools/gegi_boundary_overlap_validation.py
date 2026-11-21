"""Compare frozen depth banks on two fresh three-component GeGI layouts."""

import argparse
from collections import Counter
from itertools import combinations, product
import json
import math
from pathlib import Path

import gegi_boundary_depth_study as depth


G = depth.grid
TOTAL_KEV = 661.657
FRACTIONS = ((.29,.55,.16),(.45,.45,.10),(.10,.45,.45))
PHASES_NS = (0.,10.)
FIRST_SEED = 202611212271000
EXPECTED_DEPTH_RECEIPT = '35286f3f8051908280c5e81300288da35a4698a094c2e7f07be7638b7e7c02c9'


def frozen_inputs(depth_comparison, depth_request, depth_capture, prior_comparison, prior_request, prior_capture, center_calibration):
    report = G.bound(depth_comparison,EXPECTED_DEPTH_RECEIPT)
    hashes = report['input_sha256']
    prior,prior_sha,request,old_points,_ = depth.retained(prior_request,prior_capture,prior_comparison)
    dense_request = G.bound(depth_request,hashes['depth_point_request'])
    points,seal_sha = G.capture_points(depth_capture,dense_request,hashes['depth_point_request'])
    meta,all_centers,_,center_sha = G.calibration.load(center_calibration)
    producers = report['source_sha256']
    if (prior_sha!=hashes['prior_comparison'] or seal_sha!=hashes['depth_native_capture']
            or center_sha!=hashes['center_calibration'] or not meta['channels']==request['channels']==dense_request['channels']
            or any(producers[Path(m.__file__).name]!=G.workflow.sha(m.__file__)
                   for m in (depth,G,depth.J,depth.cause))):
        raise ValueError('Frozen captures, depth scorer or center templates changed')
    cells = tuple(map(tuple,prior['measured_scope']['cells']))
    centers = {c:all_centers[c] for c in cells}
    coarse,_ = G.lateral_templates(centers,old_points)
    training = [p for p in (*old_points,*points) if p['role']=='fit']
    refined,axes,coverage = depth.templates_on_depths(centers,coarse,training,depth.DENSE_DEPTHS)
    if len(training)!=264 or json.loads(json.dumps(coverage))!=report['calibration_support']:
        raise ValueError('The frozen local depth-bank training set changed')
    retained_fresh = {v['injection_id']:v['coarse']['held_out_positions_for_scoring'][0]
                      for v in report['independent_fresh_interior_controls']}
    fresh = {p['injection_id']:p for p in points if p['role']=='fresh_interior_holdout'}
    if set(fresh)!=set(retained_fresh) or len(fresh)!=6:
        raise ValueError('The original six fresh interior positions changed')
    for i,p in fresh.items():
        q = retained_fresh[i]
        if p['position_mm']!=q['position_mm'] or p['role']!=q['role'] or p['contact_ids']!=q['contact_ids']:
            raise ValueError('A held-out native point is outside the frozen validation roster')
    per_cell = [sorted((p for p in fresh.values() if tuple(p['contact_ids'])==c),key=lambda p:p['position_mm'][2])
                for c in cells]
    layouts = list(zip(*per_cell,strict=True))
    if len(layouts)!=2:
        raise ValueError('Expected two disjoint physical layouts')
    return report,request,layouts,coarse,refined,axes


def fit_evidence(fit, cells, points):
    data = dict(fit)
    ties = fit['sampled_near_ties_mm']
    data['maximum_sampled_near_tie_displacement_mm'] = [
        max((math.dist(pos,tie[i]) for tie in ties),default=0.) for i,pos in enumerate(fit['positions_mm'])]
    by_cell = {p['collected_cell']:p['position_mm'] for p in points}
    data['position_errors_mm'] = (
        [math.dist(p,by_cell[c]) for p,c in zip(fit['positions_mm'],cells,strict=True)]
        if fit['status']=='scored' and len(by_cell)==len(points) and set(cells)==set(by_cell) else None)
    return data


def condition(index, layout_id, items, allocation_id, phase, replicate, request, coarse, refined, axes):
    fractions = FRACTIONS[allocation_id]
    energies = [TOTAL_KEV*f for f in fractions[:2]]
    energies.append(TOTAL_KEV-math.fsum(energies))
    seed = FIRST_SEED+index
    coarse_row = G.score_holdout(items,energies,coarse,phase,request,seed)
    row = {'condition_index':index,'layout_index':layout_id,'allocation_index':allocation_id,
           'phase_ns':phase,'noise_replicate':replicate,'noise_seed':seed,'input_energies_keV':energies,
           'holdout_injection_ids':[p['injection_id'] for p in items],
           'readout_status':coarse_row['status'],'adc_sha256':coarse_row.get('adc_sha256'),
           'coarse_three_depth':None,'refined_eleven_depth':None}
    if coarse_row['status']!='evaluated' or coarse_row['lateral'] is None:
        return row
    _,volts = depth.control_adc(coarse_row,items,phase,request)
    cells = tuple(map(tuple,coarse_row['measured_cells']))
    measured = coarse_row['measured_energies_keV']
    fit = depth.fit_depth_points(volts,refined,axes,cells,measured,depth.cause.fit_start(coarse_row['center']))
    return row | {'measured_cells':cells,'measured_energies_keV':measured,
                  'coarse_three_depth':fit_evidence(coarse_row['lateral'],cells,items),
                  'refined_eleven_depth':fit_evidence(fit,cells,items)}


def rms(values):
    return math.sqrt(math.fsum(x*x for x in values)/len(values)) if values else None


def summaries(rows):
    methods = ('coarse_three_depth','refined_eleven_depth')
    outputs = []
    for i,fractions in enumerate(FRACTIONS):
        selection = [r for r in rows if r['allocation_index']==i]
        weak = min(range(3),key=fractions.__getitem__)
        common = [r for r in selection if all(r[m] is not None and r[m]['position_errors_mm'] is not None
                                              for m in methods)]
        output = {'allocation_index':i,'conditions':len(selection),'common_position_conditions':len(common),
                  'weak_component_index':weak,'fit_statistics':{}}
        for method in methods:
            fits = [r[method] for r in common]
            distances = [math.dist(a[method]['positions_mm'][weak],b[method]['positions_mm'][weak])
                         for a,b in combinations(common,2) if a['layout_index']==b['layout_index']]
            output['fit_statistics'][method] = {
                'all_component_position_rms_mm':rms([err for f in fits for err in f['position_errors_mm']]),
                'weak_component_position_rms_mm':rms([f['position_errors_mm'][weak] for f in fits]),
                'all34_adc_rms_codes':rms([f['all34_adc_rms_codes'] for f in fits]),
                'max_weak_near_tie_displacement_mm':max((f['maximum_sampled_near_tie_displacement_mm'][weak] for f in fits),default=None),
                'max_weak_between_readout_positions_mm':max(distances,default=None),
                'conditions_with_outer_parameter_bounds':sum(bool(f['parameters_at_bounds']) for f in fits)}
        outputs.append(output)
    return outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--depth-comparison',type=Path,required=True,help='Sealed eleven-depth comparison JSON')
    parser.add_argument('--depth-request',type=Path,required=True,help='Sealed eleven-depth native request JSON')
    parser.add_argument('--depth-capture',type=Path,required=True,help='Eleven-depth native capture directory')
    parser.add_argument('--prior-comparison',type=Path,required=True,help='Sealed three-depth comparison JSON')
    parser.add_argument('--prior-request',type=Path,required=True,help='Sealed three-depth native request JSON')
    parser.add_argument('--prior-capture',type=Path,required=True,help='Three-depth native capture directory')
    parser.add_argument('--center-calibration',type=Path,required=True,help='Center template archive')
    parser.add_argument('--output',type=Path,required=True,help='New JSON receipt')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Choose a new output path')
    report,request,layouts,coarse,refined,axes = frozen_inputs(
        args.depth_comparison,args.depth_request,args.depth_capture,args.prior_comparison,args.prior_request,
        args.prior_capture,args.center_calibration)
    combinations_to_test = tuple(product(range(2),range(3),PHASES_NS,range(2)))
    if len(combinations_to_test)!=24:
        raise ValueError('Two layouts, three allocations, two phases and two noise replicates yield 24 controls')
    rows = [condition(i,l,layouts[l],a,p,r,request,coarse,refined,axes)
            for i,(l,a,p,r) in enumerate(combinations_to_test)]
    result = {'kind':'gegi_fresh_weak_component_overlap_validation_v1','input_sha256':report['input_sha256']
               | {'frozen_depth_comparison':EXPECTED_DEPTH_RECEIPT},
              'source_sha256':{Path(p).name:G.workflow.sha(p) for p in (__file__,G.__file__,depth.__file__)},
              'source_position_mm':None,'source_activity_Bq':None,
              'measured_scope':report['measured_scope'],
              'design':{'total_energy_keV':TOTAL_KEV,'fractions_in_measured_cell_order':FRACTIONS,'adc_phases_ns':PHASES_NS,
                        'physical_layout_count':len(layouts),'readout_condition_count':len(rows),
                        'fresh_noise_seed_count':len({r['noise_seed'] for r in rows}),
                        'physical_layouts':[[{'injection_id':p['injection_id'],'cell':p['contact_ids'],
                                              'position_mm':p['position_mm'],'sha256':p['record_sha256']}
                                             for p in items] for items in layouts]},
              'fit_status_by_method':{m:dict(Counter(r[m]['status'] if r[m] is not None else 'unavailable' for r in rows))
                                      for m in ('coarse_three_depth','refined_eleven_depth')},
              'summary_by_energy_allocation':summaries(rows),'conditions':rows,
              'interpretation':'Two fixed physical layouts and 24 quantized readout conditions. '
                               'Both banks fit the same measured energies and ADC from each condition. '
                               'Truth coordinates score positions only after fitting. '
                               'These controlled mixtures carry no source inference or imaging weight.'}
    with args.output.open('xb') as stream:
        stream.write(G.workflow.encoded(result)+b'\n')
    print(json.dumps({'sha256':G.workflow.sha(args.output),'conditions':len(rows),'counts':result['fit_status_by_method']}))


if __name__ == '__main__':
    main()
