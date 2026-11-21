"""Combine first arrival and saved continuation on the fixed GeGI trial grid."""

import argparse
from collections import Counter
from pathlib import Path
import time

import numpy as np

import gegi_candidate_trial_curve_bank as bank
import gegi_first_compton_arrival as arrival
import scenario_workflow as W


ARRIVAL_STATUS = ('original_geometry_unavailable', 'source_at_first_vertex', 'first_vertex_outside_ge',
                  'incident_coefficients_unavailable', 'zero_first_compton_rate', 'computed')
SOURCE_REGION = ('outside_ge', 'ge_boundary', 'inside_ge')


def identity(row):
    return row['original_trigger_id'],row['pair_index'],tuple(row['site_index_order']),row['incident_keV']


def join_density(arrival_log, conditional_log):
    """Join densities in the ordered vertex volumes and observed-energy measure."""
    return np.asarray(arrival_log)+np.asarray(conditional_log)


def evaluate(receipt, measured, plan, rates, crystal, points, conditional):
    branches = receipt['branch_rows']
    records = {(tid,pair['pair_index'],tuple(order['site_index_order']),state['incident_line_keV']): (pair,status)
               for tid,pair,order,state,status in bank.trial.scoped_branches(measured,crystal)}
    W.require(len(records)==len(branches) and receipt['measured_triggers']==measured['measured_triggers'] and
              receipt['trial_grid']==plan['trial_grid'], 'The saved conditional grid uses different data or trials')
    get_rate,_ = bank.trial.rate_functions(rates)
    incident_rates = {e:get_rate(e) if min(rates)<=e<=max(rates) else None for e in measured['incident_lines_keV']}
    shape = (len(branches),len(points))
    log_first = np.full(shape,np.nan)
    lengths = np.full(shape,np.nan)
    status = np.zeros(shape,dtype=np.uint8)
    normals,offsets = crystal
    margins = np.min(offsets-points@normals.T,axis=1)
    region = np.where(margins < -1e-9,0,np.where(margins<=1e-9,1,2)).astype(np.uint8)
    W.require(int(np.count_nonzero(region))==plan['trial_grid']['inside_ge_points'], 'Saved trial Ge region changed')
    for i,row in enumerate(branches):
        pair, geometry = records.pop(identity(row))
        W.require(row['geometry_status']==geometry, 'A saved order geometry changed')
        if geometry!='available_geometry':
            continue
        first = pair['fitted_vertices_mm'][row['site_index_order'][0]]
        rate = incident_rates[row['incident_keV']]
        for j,source in enumerate(points):
            result = arrival.first_compton_arrival(crystal,source,first,rate)
            status[i,j] = ARRIVAL_STATUS.index(result['density_status'])
            if result['ge_path_to_first_mm'] is not None:
                lengths[i,j] = result['ge_path_to_first_mm']
            if result['log_first_compton_per_emitted_photon_mm3'] is not None:
                log_first[i,j] = result['log_first_compton_per_emitted_photon_mm3']
    W.require(not records,'Missing original pair/order identities in the grid')
    arrays = dict(arrival_status=status, trial_source_region=region, trial_positions_mm=points,
                  ge_path_to_first_mm=lengths, log_first_compton_per_emitted_photon_mm3=log_first)
    for h in ('absorption','escape'):
        previous = conditional[f'log_{h}_per_mm3_keV2']
        old_status = conditional[h+'_status']
        W.require(previous.shape==shape and old_status.shape==shape and np.array_equal(np.isfinite(previous),
                  old_status==receipt['status_codes'].index('conditional_factor_computed')), 'Conditional grid mask disagrees')
        arrays[f'log_{h}_per_emitted_photon_mm6_keV2'] = join_density(log_first,previous)
        arrays[h+'_conditional_status'] = old_status
    return arrays


def compare_six(reference, plan, branches, arrays):
    W.require(reference['trial_points']==plan['selected_trials'], 'First-arrival reference uses different trial points')
    by_id = {identity(row):index for index,row in enumerate(branches)}
    ndir = len(plan['trial_grid']['unit_vectors'])
    indices = [r['radial_index']*ndir+r['direction_index'] for r in plan['selected_trials']]
    values = arrays['log_first_compton_per_emitted_photon_mm3']
    compared = []
    for r in reference['branch_rows']:
        i = by_id.pop(identity(r))
        for j,old in zip(indices,r['trial_results'],strict=True) if r['trial_results'] else ():
            W.require(ARRIVAL_STATUS[arrays['arrival_status'][i,j]]==old['density_status'], 'First-arrival status changed')
            if old['density_status']=='computed':
                compared.append(abs(values[i,j]-old['log_first_compton_per_emitted_photon_mm3']))
    W.require(not by_id,'First-arrival reference has missing original branches')
    worst = max(compared,default=0.)
    W.require(worst<1e-12,'Full-grid arrival differs from the independent six-point reference')
    return dict(compared=len(compared),max_log_density_difference=worst)


def run(args):
    start = time.perf_counter()
    output = args.output.with_suffix('.npz')
    W.require(not args.output.exists() and not output.exists(),'Choose new JSON and NPZ output paths')
    measured,plan,basis,rates,crystal,points = bank.setup(args.measured_plan,args.plan,args.probe,args.new_rates)
    receipt, reference = W.read(args.conditional), W.read(args.arrival)
    array_path = args.conditional.parent/receipt['dataset']['name']
    W.require(receipt['kind']=='gegi_trial_grid_conditional_response_v1' and receipt['bank_basis']==basis and
              reference['basis']==basis and W.sha(array_path)==receipt['dataset']['sha256'],
              'Use the unchanged conditional grid, first-arrival reference and coefficient basis')
    with np.load(array_path) as conditional:
        W.require(np.array_equal(conditional['trial_positions_mm'],points),'Saved trial coordinates changed')
        arrays = evaluate(receipt,measured,plan,rates,crystal,points,conditional)
    acceptance = compare_six(reference,plan,receipt['branch_rows'],arrays)
    with output.open('xb') as stream:
        np.savez_compressed(stream,**arrays)
    density_counts = {h:int(np.count_nonzero(np.isfinite(arrays[f'log_{h}_per_emitted_photon_mm6_keV2'])))
                      for h in ('absorption','escape')}
    result = dict(kind='gegi_trial_grid_joint_photon_response_v1',basis=basis,
        conditional_grid_sha256=W.sha(args.conditional), conditional_arrays_sha256=W.sha(array_path),
        first_arrival_receipt_sha256=W.sha(args.arrival),
        dataset=dict(name=output.name,sha256=W.sha(output),bytes=output.stat().st_size,
                     shape=list(arrays['arrival_status'].shape)),
        arrival_status_codes=list(ARRIVAL_STATUS), source_region_codes=list(SOURCE_REGION),
        arrival_status_counts=dict(Counter(ARRIVAL_STATUS[i] for i in arrays['arrival_status'].ravel())),
        source_region_counts=dict(Counter(SOURCE_REGION[i] for i in arrays['trial_source_region'])),
        conditional_status_codes=receipt['status_codes'], conditional_status_counts=receipt['trial_status_counts'],
        finite_joint_density_counts=density_counts, six_point_arrival_comparison=acceptance,
        trial_grid=receipt['trial_grid'],branch_rows=receipt['branch_rows'],
        measured_triggers=receipt['measured_triggers'],measured_cohorts=receipt['measured_cohorts'],
        scope=dict(measure='Per emitted isotropic photon per mm^6 per observed keV^2 in two ordered vertex volumes '
                           'and two observed energy coordinates.', passive_materials='Unmodeled.',
                   source_activity='Unspecified.', selected_acquisition_normalization='Unmodeled.'),
        source_sha256=bank.producers() | {p.name:W.sha(p) for p in (Path(__file__),Path(arrival.__file__))},
        elapsed_seconds=time.perf_counter()-start)
    with args.output.open('xb') as stream:
        stream.write(W.encoded(result)+b'\n')
    print(dict(counts=density_counts,six_point_acceptance=acceptance))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for option in ('measured-plan','plan','probe','new-rates','conditional','arrival','output'):
        p.add_argument('--'+option,type=Path,required=True)
    run(p.parse_args())


if __name__=='__main__':
    main()
