"""Apply conditional second-site energy factors to original measured GeGI pairs and orders."""

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import platform
import time

import numpy as np
import scipy

from gegi_incident_hypotheses import ORDERS, configuration
import gegi_incident_range_controls as controls
from gegi_interaction_hypothesis_controls import read
import gegi_photon_continuation as photon
import gegi_photon_observed_energy as measured_energy
import scenario_workflow as W


def first_state(incident_keV, measured_first_keV):
    """Fix the measured first deposit under a stated line and free-electron kinematics."""
    energy = math.fsum((incident_keV, -measured_first_keV))
    cosine = 1-photon.ELECTRON_REST_KEV*(1/energy-1/incident_keV) if energy > 0 else None
    return energy, cosine


def measured_branches(row, lines, crystal):
    """Retain original identity and all nominal branches, including unusable cells and orders."""
    normals, offsets = crystal
    pairs = []
    for pair in row['conditional_escape_pairings']:
        original = pair['original_plane_pairing']
        positions = pair['saved_waveform_positions_mm']
        energies = original['site_energies_keV'] if original is not None else None
        ordered = []
        for order in ORDERS:
            reference = next((branch for branch in original['orders'] if tuple(branch['order'])==order),None) if original else None
            states = []
            for line in lines:
                branch = dict(incident_line_keV=line, status='original_strip_pairing_incompatible')
                if energies is not None:
                    first, second = (energies[i] for i in order)
                    E1, cosine = first_state(line,first)
                    branch.update(measured_first_site_keV=first, measured_second_site_keV=second,
                        fixed_intermediate_keV=E1, raw_first_scatter_cosine=cosine,
                        status='fixed_first_scatter_inadmissible')
                    if cosine is not None and -1 <= cosine <= 1:
                        if positions is None:
                            branch['status']='fitted_vertices_unavailable'
                        elif np.any(np.asarray(positions)@normals.T > offsets+1e-9):
                            branch['status']='fitted_vertex_outside_crystal'
                        elif positions[0]==positions[1]:
                            branch['status']='coincident_fitted_vertices'
                        else:
                            branch.update(status='prepared_conditional_state',
                                min_outgoing_keV=E1/(1+2*E1/photon.ELECTRON_REST_KEV))
                states.append(branch)
            ordered.append(dict(site_index_order=list(order), original_absorption_order=reference, lines=states))
        pairs.append(dict(pair_index=pair['pair_index'], cells=pair['cells'], fitted_vertices_mm=positions,
                         waveform_model=pair['saved_waveform_position_model'], measured_site_energies_keV=energies,
                         original_pair_mass=original['nominal_mass'] if original is not None else None, orders=ordered))
    return dict(original_trigger_id=row['original_trigger_id'], trigger_time_ns=row['trigger_time_ns'],
        archive_record_sha256=row['archive_record_sha256'], archive_adc_sha256=row['archive_adc_sha256'],
        original_measured_trigger_energy_keV=row['energy_keV'],
        original_projected_mass=row['projected_mass'], original_unresolved_mass=row['unresolved_mass'],
        physical_topology_status='unidentified_by_two_site_response', pairs=pairs)


def base_tables(probe):
    parent = W.read(probe/'execution.json')
    extension = probe/'observed-energy-rates'
    added = W.read(extension/'execution.json')
    csv1,csv2 = probe/'photon-rates.csv',extension/'photon-rates.csv'
    W.require(parent['returncode']==parent['primaries']==added['returncode']==added['primaries']==0 and
        added['original_execution_sha256']==W.sha(probe/'execution.json') and
        parent['binary_sha256']==added['binary_sha256'] and W.sha(csv1)==parent['photon_rates_sha256'] and
        W.sha(csv2)==added['artifacts_sha256']['photon-rates.csv'] and
        W.sha(probe/'geometry.gdml')==parent['inquiry_sha256']['geometry.gdml'] and
        W.sha(probe/'rates.mac')==parent['inquiry_sha256']['rates.mac'], 'Original initialized rate basis changed')
    first, extra = [photon.rates_from_csv(path) for path in (csv1,csv2)]
    W.require(not (first.keys() & extra.keys()), 'Original coefficient extensions must keep exact anchors once')
    spacing = max(math.log(b/a) for a,b in zip(added['nested_query_energies_keV'][:-1],added['nested_query_energies_keV'][1:],strict=True))
    binding = dict(geometry_sha256=W.sha(probe/'geometry.gdml'), rate_macro_sha256=W.sha(probe/'rates.mac'),
        exporter_sha256=parent['binary_sha256'], original_rates_sha256=W.sha(csv1), prior_extension_rates_sha256=W.sha(csv2),
        original_init_sha256=W.sha(probe/'execution.json'), prior_extension_init_sha256=W.sha(extension/'execution.json'))
    return first | extra, spacing, binding


def coefficient_request(triggers, existing, log_spacing):
    admitted = [line for row in triggers for pair in row['pairs'] for order in pair['orders'] for line in order['lines']
                if line['status']=='prepared_conditional_state']
    if not admitted:
        return dict(initialized_anchors_needed_keV=[], new_query_energies_keV=[], continuum_bounds_keV=None)
    exact = {line['fixed_intermediate_keV'] for line in admitted}
    lo, hi = min(line['min_outgoing_keV'] for line in admitted), max(exact)
    grid = sorted({lo,hi} | exact | {e for e in existing if lo <= e <= hi})
    add = set(grid)-existing.keys()
    for a,b in zip(grid[:-1],grid[1:],strict=True):
        size = math.log(b/a)
        n = max(1,math.ceil(size/log_spacing))
        add.update(math.exp(math.log(a)+size*j/n) for j in range(1,n))
    return dict(initialized_anchors_needed_keV=sorted(exact-existing.keys()), new_query_energies_keV=sorted(add),
                continuum_bounds_keV=[lo,hi], max_log_energy_spacing=log_spacing,
                scope='Add exact fixed-intermediate energies and subdivide only gaps exceeding the previous verified log-grid spacing.')


def make_plan(saved_path, geometry_path, selection_path, probe, lines, peak_triggers, sigma_keV):
    lines = configuration(lines)['incident_energies_keV']
    W.require(bool(lines), 'Supply explicit incident-line energies')
    measured_energy.gaussian_density_per_kev(0.,0.,sigma_keV)
    saved, saved_sha = read(saved_path)
    geometry, geo_sha = read(geometry_path)
    selection, selection_sha = read(selection_path)
    W.require(geometry['input_sha256']==dict(saved_plane=saved_sha,candidate_store=saved['input_sha256']['candidate_store']),
              'Saved measured geometry belongs to another reconstruction')
    rows, cohorts = controls.measured_cohorts(saved,geometry,selection,peak_triggers)
    crystal = photon.ge_halfspaces_from_gdml(probe/'geometry.gdml')
    triggers = [measured_branches(rows[tid],lines,crystal) for tid in sorted(rows)]
    rates, spacing, binding = base_tables(probe)
    counts = Counter(line['status'] for trigger in triggers for pair in trigger['pairs']
                     for order in pair['orders'] for line in order['lines'])
    return dict(kind='gegi_measured_second_site_response_plan_v1',input_sha256=dict(saved_plane=saved_sha,
        saved_conditional_geometry=geo_sha, chronological_selection=selection_sha, candidate_store=saved['input_sha256']['candidate_store']),
        measured_only=True, explicit_nominal_sigma_keV=sigma_keV, incident_lines_keV=lines,
        rate_basis=binding, scoped_cohorts=cohorts, state_counts=dict(counts), measured_triggers=triggers,
        rate_request=coefficient_request(triggers,rates,spacing))


def evaluate(plan_path, probe, new_rates, *, azimuth_samples, energy_order):
    begun = time.perf_counter()
    plan = W.read(plan_path)
    W.require(plan['kind']=='gegi_measured_second_site_response_plan_v1','Select the fixed measured response plan')
    rates, _, binding = base_tables(probe)
    W.require(binding==plan['rate_basis'],'Fixed measured response uses another coefficient/geometry basis')
    new_binding = None
    if new_rates is not None:
        receipt = W.read(new_rates/'execution.json')
        table = new_rates/'photon-rates.csv'
        W.require(receipt['returncode']==receipt['primaries']==0 and receipt['plan_sha256']==W.sha(plan_path) and
            receipt['binary_sha256']==binding['exporter_sha256'] and receipt['geometry_sha256']==binding['geometry_sha256'] and
            receipt['rate_macro_sha256']==binding['rate_macro_sha256'] and W.sha(table)==receipt['rates_sha256'],
            'New coefficient export differs from the fixed measured plan or original runtime')
        new = photon.rates_from_csv(table)
        W.require(set(new)==set(plan['rate_request']['new_query_energies_keV']) and not (set(new)&set(rates)),
                  'Coefficient queries do not reproduce the exact missing energy roster')
        rates |= new
        new_binding = dict(initialization_sha256=W.sha(new_rates/'execution.json'), rates_sha256=W.sha(table), energies=len(new))
    total = measured_energy.total_rate_interpolator(rates)
    crystal = photon.ge_halfspaces_from_gdml(probe/'geometry.gdml')
    counts = Counter()
    for trigger in plan['measured_triggers']:
        for pair in trigger['pairs']:
            for order in pair['orders']:
                for branch in order['lines']:
                    if branch['status']=='prepared_conditional_state':
                        e1=branch['fixed_intermediate_keV']
                        if e1 not in rates or branch['min_outgoing_keV'] < min(rates):
                            branch['status']='initialized_coefficients_unavailable'
                        else:
                            r1,r2=(pair['fitted_vertices_mm'][i] for i in order['site_index_order'])
                            branch['measured_energy_factors']=measured_energy.observed_continuation(crystal,r1,r2,e1,rates[e1],total,
                                [branch['measured_second_site_keV']],sigma_keV=plan['explicit_nominal_sigma_keV'],
                                azimuth_samples=azimuth_samples,energy_order=energy_order)
                            branch['status']='conditional_factors_computed'
                    counts[branch['status']]+=1
    return dict(measured_plan_sha256=W.sha(plan_path), input_sha256=plan['input_sha256'], rate_basis=binding,
        new_rate_binding=new_binding, azimuth_samples=azimuth_samples, energy_order=energy_order,
        explicit_nominal_sigma_keV=plan['explicit_nominal_sigma_keV'], incident_lines_keV=plan['incident_lines_keV'],
        scoped_cohorts=plan['scoped_cohorts'], measured_triggers=plan['measured_triggers'], state_counts=dict(counts),
        scope='Condition on a fixed measured first deposit and point-to-point ray under each explicit incident line. '
              'Compare absorption and final escape in inverse millimeters per observed second-site keV. '
              'The original strip pairing test compares the X and Y energies of each cell. '
              'The response includes observation tails beyond the absorption endpoint and escape support. '
              'The site-energy width is a nominal analytic input. First-site response, joint charge topology, '
              'secondary containment and trigger selection need separate physical response terms. Original weights are retained.',
        elapsed_seconds=time.perf_counter()-begun)


def score_after(measured, truth_path):
    truth = {row['original_trigger_id']:row for row in W.read(truth_path)['rows']}
    output = []
    for trigger in measured['measured_triggers']:
        ref = truth[trigger['original_trigger_id']]
        W.require(ref['original_archive_adc_sha256']==trigger['archive_adc_sha256'] and
                  ref['original_archive_record_sha256']==trigger['archive_record_sha256'], 'Independent scoring identity changed')
        item = dict(original_trigger_id=ref['original_trigger_id'], cohort=ref['sample'], verified_topology=ref['topology'],
                    measurement_reference_status=ref['score_status'], matched_chronology_at_nearest_supplied_line=None)
        if ref['topology'] in ('compton_then_absorption','two_compton_then_escape'):
            obs = ref['photon_kinetics']
            cells = [step['nominal_cell'] for step in obs['exact_ge_photon_interactions']]
            born = obs['simulated_birth_energy_keV']
            line = min(measured['incident_lines_keV'],key=lambda e:abs(e-born))
            matching = []
            for pair in trigger['pairs']:
                if all(cell in pair['cells'] for cell in cells):
                    chronological=[pair['cells'].index(cell) for cell in cells]
                    order = next(order for order in pair['orders'] if order['site_index_order']==chronological)
                    state = next(branch for branch in order['lines'] if branch['incident_line_keV']==line)
                    matching.append(dict(pair_index=pair['pair_index'], site_index_order=chronological, incident_line_keV=line,
                        supplied_line_minus_birth_keV=line-born,
                        response_status=state['status'], exact_intermediate_keV=obs['exact_ge_photon_interactions'][1]['pre']['kinetic_keV'],
                        fixed_measured_intermediate_keV=state.get('fixed_intermediate_keV')))
            item['matched_chronology_at_nearest_supplied_line']=matching
        output.append(item)
    return dict(input_sha256=W.sha(truth_path), source_coordinates_used=False, controls=output)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='mode', required=True)
    plan=sub.add_parser('plan')
    for name in ('saved','geometry','selection','probe','output'):
        plan.add_argument('--'+name,type=Path,required=True)
    plan.add_argument('--peak-trigger-id',type=int,action='append',default=[])
    plan.add_argument('--incident-kev',type=float,action='append',required=True)
    plan.add_argument('--sigma-kev',type=float,required=True)
    run=sub.add_parser('evaluate')
    for name in ('plan','probe','output'):
        run.add_argument('--'+name,type=Path,required=True)
    run.add_argument('--new-rates',type=Path)
    run.add_argument('--truth-controls',type=Path)
    run.add_argument('--azimuth-samples',type=int,default=256)
    run.add_argument('--energy-order',type=int,default=256)
    args=parser.parse_args()
    if args.output.exists():
        parser.error('Choose a new output path')
    if args.mode=='plan':
        result=make_plan(args.saved,args.geometry,args.selection,args.probe,args.incident_kev,args.peak_trigger_id,args.sigma_kev)
    else:
        measured=evaluate(args.plan,args.probe,args.new_rates,azimuth_samples=args.azimuth_samples,energy_order=args.energy_order)
        completed=hashlib.sha256(W.encoded(measured)).hexdigest()
        scored=score_after(measured,args.truth_controls) if args.truth_controls is not None else None
        W.require(hashlib.sha256(W.encoded(measured)).hexdigest()==completed,'Post-computation scoring changed the response')
        result=dict(kind='gegi_saved_candidate_observed_second_site_v1', measured_response=measured,
            measured_response_sha256_before_scoring=completed, post_computation_truth_score=scored)
    result['source_sha256']={Path(file).name:W.sha(file) for file in (__file__,controls.__file__,photon.__file__,measured_energy.__file__)}
    result['software'] = dict(python=platform.python_version(),numpy=np.__version__,scipy=scipy.__version__)
    with args.output.open('xb') as out:
        out.write(W.encoded(result)+b'\n')
    print(json.dumps(result.get('state_counts') or result['measured_response']['state_counts']))


if __name__=='__main__':
    main()
