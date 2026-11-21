"""Substitute matched GeGI interaction position, energy and order after ADC fitting."""

import argparse
from collections import Counter
import math
from pathlib import Path

from gegi_event_store import encoded
from gegi_imaging import cone
import gegi_joint_acquisition_study as acquisition
import gegi_position_compatibility as position
from gegi_pulse_scan import Inputs
from gegi_two_site_cfd_study import angle_error, axis_between
import scenario_workflow as workflow


ROOT = acquisition.ROOT
GEOMETRY = acquisition.REFERENCE.with_name('geometry-reference.json')
GEOMETRY_SHA = 'e45a116a278c5c89c9df7ba1e9d3c9c49aae8d620cea7b00acbf0dd8263672c0'
FITS = position.study.LOCAL / 'continuous-cs-lateral.json'
FITS_SHA = '2be7ee9c53d0c8c16f925dda089b16f8aa4a3230ca5a39896a6f4ef59a22e99f'
OUTPUT = position.OUTPUT.with_name('interaction-truth-control.json')
FULL_ENERGY = 'full_energy_at_photon_birth'


def arm(positions, energies, source_mm):
    """Signed angle from source to cone axis minus the energy opening, in degrees."""
    candidate = cone(*(dict(position_mm=p, energy_keV=e) for p, e in zip(positions, energies, strict=True)))
    if candidate is None:
        return {'status': 'no_supported_cone'}
    to_source = axis_between(source_mm, candidate['vertex_mm'])
    angle = angle_error(candidate['axis'], to_source) if math.hypot(*to_source) else None
    outgoing = {'status': 'scored' if angle is not None else 'source_coincides_with_vertex',
                'geometric_source_angle_deg': angle, 'energy_opening_deg': candidate['half_angle_deg'],
                'site_spacing_mm': candidate['site_separation_mm']}
    return dict(outgoing, signed_arm_deg=angle-candidate['half_angle_deg'] if angle is not None else None)


def measured_models(fitted_pair):
    return {'waveform_' + support: item['positions_mm']
            for support, item in fitted_pair['fit'].get('fits', {}).get('waveform', {}).items()
            if item['optimizer_success'] and item['modeled_cfd_available']}


def measured_orders(candidates, saved_row, source_mm):
    """Evaluate every original available measured hypothesis without re-ranking it."""
    hypotheses = []
    for pairing, fitted in zip(candidates, saved_row['pairings'], strict=True):
        cells = [[site['x_contact_id'], site['y_contact_id']] for site in pairing['sites']]
        if cells != fitted['cells'] or any(pairing[key] != fitted[key] for key in ('index', 'energy_compatible')):
            raise ValueError('Original fit and measured pairing identities differ')
        if not pairing['energy_compatible']:
            hypotheses.append({'pairing_index': pairing['index'], 'cells': cells, 'status': 'energy_incompatible'})
            continue
        energies = [site['energy_keV'] for site in pairing['sites']]
        if pairing['compton_orders'] != fitted['compton_orders']:
            raise ValueError('Original measured Compton order ledger differs')
        for candidate in pairing['compton_orders']:
            order = candidate['site_index_order']
            result = {'pairing_index': pairing['index'], 'cells': cells, 'order': order, 'fits': {}}
            if candidate['kinematically_allowed']:
                result.update(status=fitted['fit']['status'],
                              fits={name: arm([xyz[i] for i in order], [energies[i] for i in order], source_mm)
                                    for name, xyz in measured_models(fitted).items()})
            else:
                result['status'] = 'kinematically_disallowed'
            hypotheses.append(result)
    return hypotheses


def site_control(sites, prior, pair, order, source_mm, containment, root_energy_keV):
    ordered_cells = [[pair['sites'][i]['x_contact_id'], pair['sites'][i]['y_contact_id']] for i in order]
    if ordered_cells != [s['cell'] for s in sites]:
        raise ValueError('Photon site correspondence does not use the original strip pairing')
    step_args = [s['photon_step'] for s in sites]
    xyz = [step['post_position_mm'] for step in step_args]
    if step_args[0]['raw_row_index'] >= step_args[1]['raw_row_index']:
        raise ValueError('Photon interaction row order differs')
    contiguous = math.dist(xyz[0], step_args[1]['pre_position_mm']) <= 1e-6
    directions = [axis_between(s['post_position_mm'], s['pre_position_mm']) for s in step_args]
    model_xyz = measured_models(prior)
    position_modes = {name: [p[i] for i in order] for name, p in model_xyz.items()}
    position_modes.update(photon_vertex=xyz,
                          endpoint_cell_deposit_centroid=[s['cell_deposit_centroid_mm'] for s in sites],
                          interaction_deposit_centroid=[s['interaction_deposit_centroid_mm'] for s in sites])
    energy_modes = {'measured_slow': [pair['sites'][i]['energy_keV'] for i in order]}
    if containment == FULL_ENERGY:
        energy_modes.update(endpoint_cell_deposit=[s['cell_deposited_energy_keV'] for s in sites],
                            interaction_deposit=[s['interaction_deposited_energy_keV'] for s in sites])
    axes = {name: angle_error(axis_between(*p), axis_between(*xyz)) if math.dist(*p) else None
            for name, p in position_modes.items()}
    return {
        'positions_mm_in_photon_order': position_modes,
        'energies_keV_in_photon_order': energy_modes,
        'axis_error_to_photon_vertices_deg': axes,
        'photon_root_birth_energy_keV': root_energy_keV,
        'scored_photon_step_rows': [s['raw_row_index'] for s in step_args],
        'photon_steps_contiguous': contiguous,
        'ge_photon_turn_deg': angle_error(*directions) if contiguous and all(math.hypot(*d) for d in directions) else None,
        'source_to_incoming_chord_difference_deg': angle_error(axis_between(xyz[0], source_mm), directions[0])
        if math.dist(xyz[0], source_mm) and math.hypot(*directions[0]) else None,
        'arm_by_position_then_energy': {p: {e: arm(positions, energies, source_mm)
                                           for e, energies in energy_modes.items()}
                                       for p, positions in position_modes.items()},
        'energy_transfer_status': 'ge_deposit_controls_available' if containment == FULL_ENERGY else
                                  'partial_absorption_no_energy_substitution',
        'photon_kinetic_energy_at_vertices_keV': None,
    }


def run():
    inputs = Inputs()
    fits = inputs.read(FITS, FITS_SHA)
    pairing = inputs.read(acquisition.REFERENCE, acquisition.REFERENCE_SHA)
    geometry = inputs.read(GEOMETRY, GEOMETRY_SHA)
    report_ref = acquisition.REPORT.relative_to(ROOT).as_posix()
    windows_ref = acquisition.WINDOWS.relative_to(ROOT).as_posix()
    ref = acquisition.REFERENCE.relative_to(ROOT).as_posix()
    report = inputs.read(acquisition.REPORT, fits['input_sha256'][report_ref])
    windows_sha = workflow.sha(acquisition.WINDOWS)
    if (fits['adc_windows_sha256'] != windows_sha
            or fits['input_sha256'][ref] != acquisition.REFERENCE_SHA
            or geometry['input_sha256'][ref] != acquisition.REFERENCE_SHA
            or pairing['adc_sha256'] != report['receipt']['known_component_adc_sha256']):
        raise ValueError('ADC windows, measured fits and transport geometry do not share the original acquisition')
    inputs.hashes[windows_ref] = windows_sha
    source_positions = {}
    for source in report['sources']:
        original = source['original']
        transform = original['coordinate_transform']
        if (transform['rotation_local_to_global'] != [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
                or transform['translation_global_mm'] != [0, 0, 0]
                or any(original[k] != v for k, v in geometry['calibration_field'].items())):
            raise ValueError('Photon reference and fit source use different coordinate or field conventions')
        source_positions[source['key']] = original['source_position_mm']
    occurrences = {row['trigger_index']: row for row in geometry['occurrences']}
    groups = {tuple(row['original_group_key']): row for row in geometry['geometry_references']}
    truth_status = Counter()
    rows = []
    for row, fit in zip(pairing['candidates'], fits['candidates'], strict=True):
        trigger_id = row['trigger_index']
        trigger = report['triggers'][trigger_id]
        if trigger['trigger_time_ns'] != row['trigger_time_ns'] or fit['time_ns'] != row['trigger_time_ns']:
            raise ValueError('Unknown original trigger identity')
        ref_row = occurrences.get(trigger_id)
        if ref_row is None:
            truth_status[(row['reference'] or {}).get('status', 'association_unresolved')] += 1
            continue
        identity = tuple(ref_row['original_group_key'])
        group = groups[identity]
        selected, = row['deposit_groups']
        truth = row['reference']
        comparison = row['comparison']
        if (row['association'] != 'unique_matched' or ref_row['trigger_time_ns'] != row['trigger_time_ns']
                or ref_row['occurrence_id'] != selected['occurrence_id']
                or any(selected[k] != v for k, v in group['original_identity'].items())
                or any(truth[k] != group[k] for k in ('containment', 'native_metadata_sha256', 'transport_event_sha256'))
                or any(ref_row[k] != comparison[k] for k in ('truth_pairing_index', 'truth_site_index_order'))
                or group['photon_order_status'] != 'ordered_direct_photon_ge_steps'):
            raise ValueError('The retained exact photon pair has a conflicting original identity')
        root, = truth['depositing_root_gammas']
        sites = group['sites_in_child_birth_order']
        if any(s['photon_step']['photon_trackid'] != group['root_gamma_trackid'] for s in sites) or root['trackid'] != group['root_gamma_trackid']:
            raise ValueError('Matched photon STEP row belongs to a different depositing photon')
        source_mm = source_positions[identity[0]]
        pair_index = ref_row['truth_pairing_index']
        order = ref_row['truth_site_index_order']
        candidates = trigger['two_strip_pairings']['pairings']
        fitted_pair = next(p for p in fit['pairings'] if p['index'] == pair_index)
        truth_pair = next(p for p in candidates if p['index'] == pair_index)
        measured = measured_orders(candidates, fit, source_mm)
        status = group['containment']
        truth_status[status] += 1
        rows.append({
            'original_trigger_index': trigger_id, 'trigger_time_ns': row['trigger_time_ns'],
            'original_group_key': identity, 'occurrence_id': selected['occurrence_id'],
            'programmed_source_position_mm': source_mm, 'containment': status,
            'measured_total_energy_keV': trigger['energy_keV'],
            'truth_pairing_index': pair_index, 'truth_site_index_order': order,
            'truth_order_available_from_measured_energies': order in comparison['allowed_orders_for_truth_pair'],
            'measured_pairings_and_orders': measured,
            'position_energy_substitutions': site_control(sites, fitted_pair, truth_pair, order, source_mm,
                                                        status, root['birth_kinetic_energy_keV']),
        })
    if len(rows) != len(occurrences) or sum(truth_status.values()) != len(fits['candidates']):
        raise ValueError('Truth availability and matched original triggers do not reconcile')
    folders = sorted(p for p in (position.RUN / 'transport').glob('b*') if p.is_dir())
    raw_kept = [p.name for p in folders if (p / 'truth.lh5').is_file() and (p / 'stream/events.jsonl').is_file()]
    return {
        'kind': 'gegi_matched_interaction_truth_control_v1',
        'scope': 'Historical independent replay; repeated occurrences share original transport interactions. The measured fits stay fixed before every truth substitution.',
        'trigger_index_definition': 'Original zero-based index in the hash-bound historical acquisition receipt.',
        'arm_definition': 'Angle from cone axis to programmed source minus energy-derived Compton opening; degrees. Measured cones for incomplete absorption are apparent two-site absorption hypotheses.',
        'energy_definition': 'Ge interaction and endpoint-cell deposit sums are explicit same-event controls. They can differ from one another and from the unsaved photon kinetic energy at the vertices.',
        'qualified_trigger_denominator': pairing['qualified_trigger_denominator'],
        'two_strip_triggers': len(fits['candidates']), 'matched_exact_photon_occurrences': len(rows),
        'independent_original_groups': len(groups),
        'full_energy_occurrences': sum(r['containment'] == FULL_ENERGY for r in rows),
        'truth_status_counts': truth_status, 'rows': rows,
        'fresh_five_second_truth_join': {
            'status': 'unverified_current_pulse_association',
            'transport_blocks': len(folders), 'blocks_with_raw_truth_and_stream': raw_kept,
            'blocks_with_retirement_receipt': sum((p / 'retired-artifacts.json').is_file() for p in folders),
            'basis': 'Retained fresh candidate group ordinals mark recent readout context. A unique causal photon-to-trigger link is necessary before replacing the measured geometry or energy.'
        },
        'input_sha256': inputs.hashes, 'source_sha256': workflow.sha(Path(__file__)),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    args = parser.parse_args()
    if args.output.exists() or not args.output.resolve().is_relative_to(OUTPUT.parent):
        parser.error('Choose a new output in the reconstruction evidence directory')
    result = run()
    args.output.parent.mkdir(exist_ok=True)
    with args.output.open('xb') as stream:
        stream.write(encoded(result) + b'\n')
    print(f"{result['matched_exact_photon_occurrences']} matched occurrences, "
          f"{result['full_energy_occurrences']} with full photon birth energy")


if __name__ == '__main__':
    main()
