"""Evaluate a saved GeGI trial grid with a verified escape-response bank."""

import argparse
from collections import Counter
from contextlib import closing
import json
import math
from pathlib import Path
import sqlite3
import time

import numpy as np

import gegi_candidate_trial_curve_bank as bank
import gegi_trial_curve_quadrature_repair as repair
from gegi_escape_response_curve import EscapeResponseCurve
from gegi_photon_continuation import solid_angle_density_per_sr
from gegi_photon_log_response import gaussian_log_density_per_kev
import scenario_workflow as W


STATUS = ('original_geometry_unavailable', 'trial_source_at_first_vertex', 'initialized_coefficients_unavailable',
          'escape_curve_unverified', 'outside_validated_curve_domain', 'conditional_factor_computed')


def read_bank(path, basis, keys):
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        manifest = json.loads(db.execute('SELECT recipe FROM manifest WHERE id=1').fetchone()[0])
        rows = {key:json.loads(row) for key,row in db.execute('SELECT curve,summary FROM curves')}
    W.require(manifest['kind']==bank.KIND and manifest['basis']==basis and manifest['source_sha256']==bank.producers() and
        manifest['software']==bank.software() and manifest['curves']=={
            k:dict(model=v['model'],domain_keV=v['domain_keV']) for k,v in keys.items()}, 'Curve bank uses a different trial recipe')
    return manifest, rows


def escape_logs(summary, intermediate, eligible):
    """Return explicit coverage statuses and finite log response only on validated domains."""
    logs = np.full(intermediate.shape,np.nan)
    status = np.full(intermediate.shape,STATUS.index('escape_curve_unverified'),dtype=np.uint8)
    if summary and summary['status']=='verified_heldout_curve':
        lo,hi = summary['domain_keV']
        covered = eligible & (intermediate>=lo) & (intermediate<=hi)
        nodes = summary['comparison']['nodes']
        model = summary['model']
        curve = EscapeResponseCurve([x['intermediate_keV'] for x in nodes],[x['log_escape_density'] for x in nodes],
                                    observed_keV=model['measured_second_site_keV'],sigma_keV=model['sigma_second_keV'])
        status[:] = STATUS.index('outside_validated_curve_domain')
        logs[covered] = curve.log_density(intermediate[covered])
        status[covered] = STATUS.index('conditional_factor_computed')
    status[~eligible] = STATUS.index('initialized_coefficients_unavailable')
    status[~np.isfinite(intermediate)] = STATUS.index('trial_source_at_first_vertex')
    return logs,status


def evaluate_arrays(rows, keys, branches, npoints, plan, rates):
    shape = (len(branches),npoints)
    names = ('intermediate_keV','log_first_measurement_per_keV','log_second_absorption_per_mm_keV',
             'log_second_escape_per_mm_keV','log_absorption_per_mm3_keV2','log_escape_per_mm3_keV2')
    arrays = {name:np.full(shape,np.nan) for name in names}
    arrays.update(absorption_status=np.zeros(shape,dtype=np.uint8),escape_status=np.zeros(shape,dtype=np.uint8))
    rates_at,_ = bank.trial.rate_functions(rates)
    codes = {s:i for i,s in enumerate(STATUS)}
    for i,b in enumerate(branches):
        if b['geometry_status']!='available_geometry':
            continue
        e1,cosine,d1 = b['states'].T
        arrays['intermediate_keV'][i] = e1
        model = keys[b['curve_key']]['model']
        length = math.dist(model['first_fitted_mm'],model['second_fitted_mm'])
        first_logs = arrays['log_first_measurement_per_keV'][i]
        common = np.full(npoints,np.nan)
        for j in np.flatnonzero(b['first_vertex_distinct']):
            first_logs[j] = gaussian_log_density_per_kev(b['measured_first_site_keV'],d1[j],plan['sigma_first_keV'])
            common[j] = math.log(solid_angle_density_per_sr(b['incident_keV'],cosine[j]))-2*math.log(length)+first_logs[j]
        second_a = arrays['log_second_absorption_per_mm_keV'][i]
        rate_support = (e1>=min(rates)) & (e1<=max(rates))
        for j in np.flatnonzero(rate_support):
            c = rates_at(e1[j])
            second_a[j] = (math.log(c.photoelectric_per_mm)-length*c.total_per_mm
                +gaussian_log_density_per_kev(model['measured_second_site_keV'],e1[j],model['sigma_second_keV']))
        status_a = arrays['absorption_status'][i]
        status_a[:] = codes['initialized_coefficients_unavailable']
        status_a[~b['first_vertex_distinct']] = codes['trial_source_at_first_vertex']
        status_a[rate_support] = codes['conditional_factor_computed']
        arrays['log_absorption_per_mm3_keV2'][i] = common+second_a
        second_e,status_e = escape_logs(rows.get(b['curve_key']),e1,b['escape_coefficients_available'])
        arrays['log_second_escape_per_mm_keV'][i] = second_e
        arrays['escape_status'][i] = status_e
        arrays['log_escape_per_mm3_keV2'][i] = common+second_e
    return arrays


def branch_id(b):
    return b['original_trigger_id'],b['pair_index'],tuple(b['site_index_order']),b['incident_keV']


def compare_exact(reference, arrays, branches, points, plan, measured, plan_sha):
    before = reference['measured_response']
    W.require(before['trial_plan_sha256']==plan_sha and before['measured_triggers']==measured['measured_triggers'] and
              before['selected_trials']==plan['selected_trials'] and W.digest(before)==reference['measured_response_sha256_before_truth'],
              'Direct reference differs from the original trial and candidates')
    branches_by_id = {branch_id(b):i for i,b in enumerate(branches)}
    directions = len(plan['trial_grid']['unit_vectors'])
    indices = [b['radial_index']*directions+b['direction_index'] for b in plan['selected_trials']]
    W.require(np.array_equal(points[indices],np.array([x['source_mm'] for x in plan['selected_trials']])),
              'Direct reference trial coordinates differ')
    quantities = {'log_first_measurement_per_keV':'first', 'log_second_absorption_per_mm_keV':'second_absorption',
                  'log_second_escape_per_mm_keV':'second_escape','log_absorption_per_mm3_keV2':'joint_absorption',
                  'log_escape_per_mm3_keV2':'joint_escape'}
    stats = {q:Counter() for q in quantities.values()}
    worst = {q:None for q in quantities.values()}
    intermediate_error = 0.
    normal_threshold = np.finfo(float).tiny
    for b in before['branches']:
        i = branches_by_id[branch_id(dict(b,incident_keV=b['incident_line_keV']))]
        for j,row in zip(indices,b['trial_results'],strict=True) if b['trial_results'] else ():
            if row['status']!='conditional_factors_computed':
                continue
            direct = row['response']
            iid = arrays['intermediate_keV'][i,j]
            intermediate_error = max(intermediate_error,abs(iid-direct['intermediate_keV']))
            second, = direct['second_site_response']['observations']
            values = (direct['first_measurement_density_per_keV'],second['absorption_per_mm_observed_keV'],
                      second['escape_per_mm_observed_keV'],direct['absorption_per_mm3_observed_keV2'],
                      direct['escape_per_mm3_observed_keV2'])
            for (name,q),raw in zip(quantities.items(),values,strict=True):
                predicted = arrays[name][i,j]
                if not math.isfinite(predicted):
                    stats[q]['unavailable_in_grid'] += 1
                    continue
                if raw < normal_threshold:
                    stats[q]['raw_direct_zero' if raw==0 else 'raw_direct_subnormal'] += 1
                    continue
                stats[q]['compared_finite_log'] += 1
                difference = abs(predicted-math.log(raw))
                if worst[q] is None or difference>worst[q]['abs_log_difference']:
                    worst[q] = dict(abs_log_difference=difference, original_trigger_id=b['original_trigger_id'],
                        pair_index=b['pair_index'], site_index_order=b['site_index_order'], incident_keV=b['incident_line_keV'],
                        grid_index=j, intermediate_keV=iid)
    return dict(quantities={q:dict(counts=dict(stats[q]),worst=worst[q]) for q in quantities.values()},
                maximum_intermediate_difference_keV=intermediate_error)


def run(args):
    started = time.perf_counter()
    dataset = args.output.with_suffix('.npz')
    W.require(not args.output.exists() and not dataset.exists(), 'Select fresh JSON and NPZ output paths')
    measured,plan,basis,rates,crystal,points = bank.setup(args.measured_plan,args.plan,args.probe,args.new_rates)
    keys,branches = bank.geometries(measured,plan,crystal,points,basis['coefficient_support_keV'])
    bank_sha = W.sha(args.bank)
    manifest, rows = read_bank(args.bank,basis,keys)
    W.require(rows.keys()==keys.keys(), 'Wait for the declared curve bank to finish before sealing the full grid')
    extension_sha, extension_receipt = None, None
    if args.quadrature_extension is not None:
        extension_sha = W.sha(args.quadrature_extension)
        extension_receipt, replacement = repair.read_extension(args.quadrature_extension,bank_sha,manifest,rows)
        rows |= replacement
    arrays = evaluate_arrays(rows,keys,branches,len(points),plan,rates)
    exact = compare_exact(W.read(args.exact),arrays,branches,points,plan,measured,W.sha(args.plan))
    exact['sha256'] = W.sha(args.exact)
    W.require(W.sha(args.bank)==bank_sha, 'The curve bank changed during full-grid evaluation')
    if extension_sha is not None:
        W.require(W.sha(args.quadrature_extension)==extension_sha, 'The quadrature extension changed during full-grid evaluation')
    for b in branches:
        for name in ('states','escape_coefficients_available','first_vertex_distinct'):
            b.pop(name,None)
    with dataset.open('xb') as stream:
        np.savez_compressed(stream,trial_positions_mm=points,**arrays)
    counts = {code:{name:int((arrays[code]==i).sum()) for i,name in enumerate(STATUS)}
              for code in ('absorption_status','escape_status')}
    sources = extension_receipt['source_sha256'] if extension_receipt is not None else manifest['source_sha256']
    result = dict(kind='gegi_trial_grid_conditional_response_v1',bank_sha256=bank_sha,bank_basis=basis,
        quadrature_extension=dict(sha256=extension_sha,recipe=extension_receipt) if extension_sha is not None else None,
        source_sha256=sources | {Path(__file__).name:W.sha(__file__)}, software=bank.software(),
        dataset=dict(name=dataset.name,sha256=W.sha(dataset),bytes=dataset.stat().st_size,shape=[len(branches),len(points)]),
        measured_cohorts=measured['scoped_cohorts'],measured_triggers=measured['measured_triggers'],
        trial_grid=plan['trial_grid'],branch_rows=branches,status_codes=list(STATUS),trial_status_counts=counts,
        numerical_settings=manifest['settings'] | {'sigma_first_keV':plan['sigma_first_keV']},
        curve_status_counts=dict(Counter(r['status'] for r in rows.values())),
        curve_domains_keV={k:v['domain_keV'] for k,v in keys.items()},
        maximum_curve_heldout_error=max((r['comparison']['max_absolute_log_error'] for r in rows.values()
            if r['status']=='verified_heldout_curve'),default=None),six_point_direct_comparison=exact,
        scientific_scope='Conditional densities after fixing first Compton vertex. No source solution, truth selection or fitted weights. '
                         'Nonfinite dataset entries are uncomputed and their status identifies the reason. Finite natural logs preserve tails. '
                         'The interpolation errors are measured at held-out energies and do not certify a uniform bound.',
        elapsed_seconds=time.perf_counter()-started)
    with args.output.open('xb') as stream:
        stream.write(W.encoded(result)+b'\n')
    print(counts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ('measured-plan','plan','probe','new-rates','bank','exact','output'):
        parser.add_argument('--'+option,type=Path,required=True)
    parser.add_argument('--quadrature-extension',type=Path)
    run(parser.parse_args())


if __name__=='__main__':
    main()
