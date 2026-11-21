"""Compare interaction hypotheses on the same saved ADC fits and verified photon histories."""

import argparse
from collections import Counter
import gzip
import hashlib
import json
import math
from pathlib import Path
import platform
import statistics

import numpy as np
import scipy

import gegi_candidate_imaging as imaging
import gegi_candidate_storage as storage
import gegi_digital_readout as digital
import gegi_incident_geometry as geometry
from gegi_incident_hypotheses import ORDERS
import gegi_joint_calibration as calibration
import gegi_joint_two_site as joint
import scenario_workflow as W


CLEAN = {'compton_then_absorption': 'absorption', 'two_compton_then_escape': 'resolved_escape'}


def read(path):
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == '.gz' else raw), hashlib.sha256(raw).hexdigest()


def absorption_cone(positions, order, scatter):
    if positions is None or not scatter['nominally_admissible']:
        return None
    vertex, second = (positions[i] for i in order)
    separation = math.dist(vertex, second)
    if not separation:
        return None
    return dict(vertex_mm=vertex, second_site_mm=second, axis=[(a-b)/separation for a, b in zip(vertex, second, strict=True)],
                half_angle_deg=scatter['scatter_angle_deg'], site_separation_mm=separation)


def paired_orders(pair):
    """Use the very same measured energies and saved vertices for either photon hypothesis."""
    kinematics = pair['kinematics']
    original = pair['original_plane_pairing']
    positions = pair['saved_waveform_positions_mm']
    source = [dict(site_index_order=list(order), absorption=None, resolved_escape=[], original_projection=None)
              for order in ORDERS]
    if kinematics['status'] != 'evaluated':
        return source
    original_orders = {tuple(row['order']): row for row in original['orders']}
    for out, absorption in zip(source, kinematics['observed_sum_full_absorption_orders'], strict=True):
        order = tuple(out['site_index_order'])
        if list(order) != absorption['site_index_order']:
            raise ValueError('Saved absorption order changed')
        scatter = absorption['first_scatter']
        out['absorption'] = dict(first_scatter=scatter, cone=absorption_cone(positions, order, scatter))
        out['original_projection'] = original_orders.get(order)
        for line in kinematics['incident_line_hypotheses']:
            escape = next(item for item in line['two_resolved_scatter_escape_orders'] if tuple(item['site_index_order']) == order)
            out['resolved_escape'].append(dict(escape, incident_energy_keV=line['incident_energy_keV'],
                observed_sum_minus_incident_keV=line['observed_sum_minus_incident_keV'],
                escape_photon_energy_keV=line['escape_photon_energy_keV']))
    return source


def linear_depth_split(depth, energy, grid):
    """Replace one interior interpolated depth by two distinct calibrated grid points."""
    hi = int(np.searchsorted(grid, depth))
    if hi == 0 or hi == len(grid) or depth == grid[hi]:
        return None
    zlo, zhi = float(grid[hi-1]), float(grid[hi])
    fraction = (depth-zlo)/(zhi-zlo)
    lower = energy * (1-fraction)
    return (zlo, zhi), (lower, energy-lower)


def center_split(pair, samples, templates, fit):
    """A constructive three-point explanation within the existing linear center model."""
    original = pair['original_plane_pairing']
    saved = fit['fit'].get('fits', {}).get('waveform', {}).get('center')
    if original is None or not saved or not saved['optimizer_success'] or samples is None:
        return dict(status='center_prediction_unavailable', sites=[])
    positions = pair['saved_waveform_positions_mm']
    if positions != saved['positions_mm'] or pair['saved_waveform_position_model'] != 'center':
        raise ValueError('The requested ADC witness differs from the saved center fit')
    energies = original['site_energies_keV']
    points = saved['parameters']
    individual = [templates[tuple(cell)] for cell in pair['cells']]
    models = joint._interpolators(individual, np.arange(len(digital.CONTACT_IDS)), (False, False))
    waveforms = [energy*model([depth])[0] for (model, _), depth, energy in zip(models, points[:2], energies, strict=True)]
    expected = joint.shifted_samples(sum(waveforms), points[-1])
    data = joint.remove_quiet_tail(samples)

    def rms(volts):
        return float(np.sqrt(np.mean(((data-joint.remove_quiet_tail(volts))/digital._LSB_V)**2)))

    witnesses = []
    for i, ((model, _), depth, energy) in enumerate(zip(models, points[:2], energies, strict=True)):
        split = linear_depth_split(depth, energy, joint.DEPTH_MM)
        if split is None:
            witnesses.append(dict(site_index=i, status='existing_depth_grid_node'))
            continue
        (lo, hi), (elo, ehi) = split
        three = waveforms[1-i] + elo*model([lo])[0] + ehi*model([hi])[0]
        predicted = joint.shifted_samples(three, points[-1])
        witnesses.append(dict(site_index=i, status='two_distinct_depths_in_same_nominal_cell',
                              split_depths_mm=[lo, hi], split_energies_keV=[elo, ehi],
                              max_abs_difference_adc_codes=float(np.max(np.abs(predicted-expected))/digital._LSB_V),
                              split_all34_residual_rms_adc_codes=rms(predicted)))
    return dict(status='evaluated', two_point_all34_residual_rms_adc_codes=rms(expected), sites=witnesses)


def measure(saved_geometry, fits, adc, templates, excluded):
    raw = adc['context']['adc_codes']
    digest = hashlib.sha256(raw.tobytes()).hexdigest()
    if digest != saved_geometry['archive_adc_sha256'] or adc['trigger_time_ns'] != saved_geometry['trigger_time_ns']:
        raise ValueError('Saved hypothesis results and ADC samples refer to different records')
    samples, status = imaging.voltage_window(adc, excluded)
    if status != fits['window_status']:
        raise ValueError('The ADC fitting window differs from the saved fit')
    pairs = []
    for pair, fit in zip(saved_geometry['conditional_escape_pairings'], fits['pairings'], strict=True):
        if (pair['pair_index'], pair['cells']) != (fit['index'], fit['cells']):
            raise ValueError('Saved pairing identity differs')
        old = pair['original_plane_pairing']
        pairs.append(dict(pair_index=pair['pair_index'], cells=pair['cells'], original_pairing=old,
            measured_site_energies_keV=old['site_energies_keV'] if old is not None else None,
            saved_waveform_positions_mm=pair['saved_waveform_positions_mm'], fit_status=fit['fit']['status'],
            orders=paired_orders(pair), merged_center_model_witness=center_split(pair, samples, templates, fit)))
    return dict(original_trigger_id=saved_geometry['original_trigger_id'], energy_keV=saved_geometry['energy_keV'],
                archive_adc_sha256=digest, archive_record_sha256=saved_geometry['archive_record_sha256'],
                adc_window_status=status, original_projected_mass=saved_geometry['projected_mass'],
                original_unresolved_mass=saved_geometry['unresolved_mass'],
                merged_or_mixed_direction_status='point_topology_unresolved', pairings=pairs)


def score(measured, reference, incident_lines):
    """Join truth only after every measured branch has been generated."""
    if (reference['original_trigger_id'], reference['original_archive_adc_sha256'], reference['original_archive_record_sha256']) != (
            measured['original_trigger_id'], measured['archive_adc_sha256'], measured['archive_record_sha256']):
        raise ValueError('Verified photon and measured identities differ')
    topology = reference['topology']
    scored = dict(cohort=reference['sample'], verified_topology=topology, reference_status=reference['score_status'],
                  photon_kinetics_status=reference['exact_history_status'], clean_pair_orders=None)
    if topology not in CLEAN:
        return scored
    photon = reference['photon_kinetics']
    steps = photon['exact_ge_photon_interactions']
    if len(steps) != 2 or steps[0]['nominal_cell'] == steps[1]['nominal_cell']:
        raise ValueError('Clean control requires two distinct verified photon cells')
    cells = [step['nominal_cell'] for step in steps]
    energy = photon['simulated_birth_energy_keV']
    line = min(incident_lines, key=lambda value: abs(value-energy))
    source = photon['source_position_mm_for_scoring']
    scored.update(nominal_line_for_scoring_keV=line, nominal_minus_birth_keV=line-energy,
                  chronological_nominal_cells=cells, clean_pair_orders=[])
    for pair in measured['pairings']:
        if not all(cell in pair['cells'] for cell in cells):
            continue
        chronological = [pair['cells'].index(cell) for cell in cells]
        for order in pair['orders']:
            absorption = order['absorption']
            escape = next((branch for branch in order['resolved_escape'] if branch['incident_energy_keV']==line), None)
            result = dict(pair_index=pair['pair_index'], site_index_order=order['site_index_order'],
                          matches_photon_chronology=order['site_index_order']==chronological)
            for name, branch in (('absorption', absorption), ('resolved_escape', escape)):
                cone = branch['cone'] if branch is not None else None
                compatible = None if branch is None else (branch['first_scatter']['nominally_admissible']
                                                          if name=='absorption' else branch['nominally_admissible'])
                result[name] = dict(nominally_admissible=compatible, has_geometry=cone is not None,
                                    signed_source_arm_deg=geometry.angular_residual_deg(cone, source) if cone else None)
            result['measured_sum_minus_true_nominal_line_keV'] = escape['observed_sum_minus_incident_keV'] if escape else None
            scored['clean_pair_orders'].append(result)
    return scored


def summary(rows):
    groups, scores = {}, {}
    for row in rows:
        topology = row['truth_score']['verified_topology']
        count = groups.setdefault(topology, Counter())
        orders = [order for pair in row['pairings'] for order in pair['orders']]
        support = [(bool(order['absorption'] and order['absorption']['cone']),
                    any(escape['cone'] for escape in order['resolved_escape'])) for order in orders]
        a, e = (any(value[i] for value in support) for i in range(2))
        count.update(triggers=1, absorption_cone=int(a), resolved_escape_cone=int(e), both_point_hypotheses=int(a and e),
                     same_pair_order_both_cones=int(any(x and y for x, y in support)), neither_point_hypothesis=int(not (a or e)))
        if topology in CLEAN:
            order_scores = scores.setdefault(topology, {'chronological': [], 'reverse': []})
            for order in row['truth_score']['clean_pair_orders']:
                order_scores['chronological' if order['matches_photon_chronology'] else 'reverse'].append(order)

    def arm_metrics(branches):
        arm = [item['signed_source_arm_deg'] for item in branches if item['has_geometry']]
        return dict(nominally_admissible=sum(item['nominally_admissible'] is True for item in branches),
            nominally_inadmissible=sum(item['nominally_admissible'] is False for item in branches),
            unavailable=sum(item['nominally_admissible'] is None for item in branches), arm_count=len(arm),
            arm_rms_deg=math.sqrt(statistics.mean(value*value for value in arm)) if arm else None,
            arm_median_absolute_deg=statistics.median(map(abs, arm)) if arm else None)

    return dict(by_verified_topology={key: dict(value) for key, value in groups.items()},
                clean_pair_order_scores={topology: {side: {branch: arm_metrics([row[branch] for row in orders])
                    for branch in ('absorption', 'resolved_escape')} for side, orders in cases.items()}
                    for topology, cases in scores.items()})


def run(saved_path, geometry_path, archive, center_path, truth_path, selection_path):
    saved, saved_sha = read(saved_path)
    source_free, geo_sha = read(geometry_path)
    archive_sha = W.sha(archive)
    if source_free['input_sha256'] != {'saved_plane': saved_sha, 'candidate_store': archive_sha}:
        raise ValueError('Saved map, archive and conditional geometries differ')
    _, templates, content_sha, center_sha = calibration.load(center_path)
    bundle = saved['fit_receipt']['calibration_bundle']
    if (center_sha, content_sha) != (bundle['archive_sha256'], bundle['content_sha256']):
        raise ValueError('Center calibration differs from the saved waveform fit')
    acquisition, acquisition_sha = read(saved_path.parent/'candidate-acquisition.json')
    if acquisition_sha != saved['input_sha256']['acquisition']:
        raise ValueError('Original readout mask differs from the saved fit')
    fits = {trigger['original_trigger_id']: fit for trigger, fit in zip(saved['triggers'], saved['fit_receipt']['candidates'], strict=True)}
    from_adc = [measure(info, fits[info['original_trigger_id']], storage.load_candidate(archive, info['original_trigger_id']),
                        templates, acquisition['excluded_intervals_ns']) for info in source_free['triggers']]
    truth, truth_sha = read(truth_path)
    selection, selection_sha = read(selection_path)
    selected = {entry['original_trigger_id'] for window in selection['windows'].values() for entry in window['sampled_triggers']}
    known = {row['original_trigger_id']: row for row in truth['rows']}
    if (selected != {key for key, row in known.items() if row['sample']=='chronological_sample'} or
            set(known) != {row['original_trigger_id'] for row in from_adc}):
        raise ValueError('Hypotheses must preserve the complete fixed chronological and peak-control identities')
    lines = source_free['incident_line_configuration']['incident_energies_keV']
    rows = [dict(row, truth_score=score(row, known[row['original_trigger_id']], lines)) for row in from_adc]
    by_cohort = {label: summary([row for row in rows if row['truth_score']['cohort']==label])
                 for label in ('chronological_sample', 'peak_control')}
    witnesses = [site for row in rows for pair in row['pairings'] for site in pair['merged_center_model_witness']['sites']
                 if site['status']=='two_distinct_depths_in_same_nominal_cell']
    sources = (imaging, storage, digital, geometry, calibration, joint)
    return dict(kind='gegi_same_adc_interaction_hypothesis_controls_v1',
                input_sha256=dict(saved_plane=saved_sha, candidate_store=archive_sha, acquisition=acquisition_sha, center_calibration=center_sha,
                    conditional_geometries=geo_sha, verified_photon_controls=truth_sha, chronological_selection=selection_sha),
                source_sha256={Path(module.__file__).name: W.sha(module.__file__) for module in sources} |
                              {Path(__file__).name: W.sha(__file__)},
                software=dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__),
                incident_lines_keV=lines, summary_by_cohort=by_cohort,
                merged_witness_summary=dict(split_sites=len(witnesses), max_abs_difference_adc_codes=max(
                    (site['max_abs_difference_adc_codes'] for site in witnesses), default=None)),
                scope='The chronological controls preserve the prespecified six-per-window sample. Three earlier peak cases are reported separately. '
                      'All branches are frozen from the same measured energies, samples and saved fitted positions before photon truth enters scoring. '
                      'For scoring clean histories, the nominal incident line is the supplied line nearest the verified photon birth energy.',
                limitations='The depth-split witness is an algebraic property of the linear center-template interpolation at the same onset. '
                            'It does not validate the actual waveform of a distributed or merged physical interaction. Nominal support is conditional '
                            'and gives no assignment, probability or production weight. Merged or mixed histories have no two-point reference order.',
                rows=rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('saved', 'geometry', 'archive', 'center-calibration', 'truth-controls', 'selection', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    result = run(args.saved, args.geometry, args.archive, args.center_calibration, args.truth_controls, args.selection)
    with args.output.open('xb') as output:
        output.write(W.encoded(result)+b'\n')
    print(json.dumps(dict(triggers=len(result['rows']), **result['merged_witness_summary'])))


if __name__ == '__main__':
    main()
