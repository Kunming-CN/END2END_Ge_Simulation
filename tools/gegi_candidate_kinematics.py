"""Evaluate nominal incident-line hypotheses for a complete saved candidate map."""

import argparse
from collections import Counter, defaultdict
from contextlib import closing
import gzip
import hashlib
import json
import math
from pathlib import Path
import platform
import time
from types import SimpleNamespace
import zlib

import numpy as np

import gegi_candidate_records as records
import gegi_candidate_storage as storage
import gegi_continuous_plane as plane
import gegi_incident_hypotheses as hypotheses
import gegi_joint_imaging as joint
import scenario_workflow as workflow


MASS_ATOL = 1e-12


def close_mass(value, expected):
    return math.isclose(value, expected, rel_tol=0., abs_tol=MASS_ATOL)


def measured_pairing(measured, fit, original, lines):
    sites = measured['sites']
    index = measured['index']
    cells = [[s['x_contact_id'], s['y_contact_id']] for s in sites]
    energies = [s['energy_keV'] for s in sites]
    compatible = measured['energy_compatible']
    measured_orders = measured['compton_orders']
    if (fit['cells'] != cells or fit['energy_compatible'] != compatible or fit['compton_orders'] != measured_orders
            or (original is not None) != compatible):
        raise ValueError(f'Saved pair {index} differs from the archived measurement')
    if original is not None and (
            original['cells'] != cells or original['site_energies_keV'] != energies
            or [o['order'] for o in original['orders']]
            != [o['site_index_order'] for o in measured_orders if o['kinematically_allowed']]):
        raise ValueError(f'Saved plane order or energy differs for pair {index}')
    return dict(pair_index=index, cells=cells, measured_site_energies_keV=energies,
                measured_sites=sites, energy_compatible=compatible, original_fit_status=fit['fit']['status'],
                original_observed_sum_orders=measured_orders, original_plane=original,
                kinematics=hypotheses.evaluate(energies, lines, unavailable=None if compatible else 'energy_incompatible'))


def measured_ledger(saved, archive, lines):
    """Read scalar cards only and retain original pairing/order decisions."""
    original_rows = saved['triggers']
    receipt = saved['fit_receipt']
    analysis = saved['candidate_analysis']
    ids = [row['original_trigger_id'] for row in original_rows]
    if (saved['kind'] != plane.PLANE_KIND or analysis['kind'] != records.ANALYSIS_KIND
            or analysis['scope'] != 'all_two_strip_candidates' or analysis['selected_original_trigger_ids'] != ids
            or ids != sorted(set(ids)) or len(ids) != receipt['two_strip_triggers']
            or len(ids) != saved['selection']['two_strip_triggers']):
        raise ValueError('Select a measured map covering every original two-strip candidate')
    rows = []
    with closing(storage._open_readonly(archive)) as db:
        for original, fit in zip(original_rows, receipt['candidates'], strict=True):
            trigger_id = original['original_trigger_id']
            measurement = db.execute(
                'SELECT record,adc_sha256,record_sha256 FROM triggers WHERE trigger_id=?', (trigger_id,)).fetchone()
            if measurement is None:
                raise ValueError(f'Missing archived trigger {trigger_id}')
            body, adc_sha, record_sha = measurement
            record = json.loads(zlib.decompress(body))
            card = record['card']
            if (storage._record_digest(record, adc_sha) != record_sha or record['decision'] != 'candidate'
                    or record['trigger_id'] != trigger_id
                    or record['trigger_time_ns'] != original['trigger_time_ns'] or fit['time_ns'] != original['trigger_time_ns']
                    or card['energy_keV'] != original['energy_keV'] or fit['ordinal'] != original['two_strip_ordinal']
                    or record['identities'] != original['diagnostic_input_group_ordinals']):
                raise ValueError(f'Saved candidate differs from the archive at trigger {trigger_id}')
            measured = card['two_strip_pairings']['pairings']
            plane_pairs = {pair['index']: pair for pair in original['pairings']}
            if ([pair['index'] for pair in fit['pairings']] != [pair['index'] for pair in measured]
                    or list(plane_pairs) != [pair['index'] for pair in measured if pair['energy_compatible']]):
                raise ValueError(f'Saved pairing identities differ at trigger {trigger_id}')
            pairings = [measured_pairing(pair, fitted, plane_pairs.get(pair['index']), lines)
                        for pair, fitted in zip(measured, fit['pairings'], strict=True)]
            rows.append({**original, 'pairings': pairings, 'archive_record_sha256': record_sha,
                         'archive_adc_sha256': adc_sha, 'flags': fit['flags']})
    return rows


def escape_lines(pair, order=None):
    """Return the supplied energies admitting this order, or any order for the pair."""
    return tuple(line['incident_energy_keV'] for line in pair['kinematics'].get('incident_line_hypotheses', [])
                 if any(case['nominally_admissible'] and (order is None or case['site_index_order'] == order)
                        for case in line['two_resolved_scatter_escape_orders']))


def census(rows, lines, layer):
    pairs = [pair for row in rows for pair in row['pairings']]
    compatible = [pair for pair in pairs if pair['energy_compatible']]
    trigger_escape_sets = [set(line for p in row['pairings'] for line in escape_lines(p)) for row in rows]
    summary = dict(
        triggers=len(rows), triggers_with_projected_mass=sum(row['projected_mass'] > 0 for row in rows),
        projected_mass=math.fsum(row['projected_mass'] for row in rows),
        unresolved_mass=math.fsum(row['unresolved_mass'] for row in rows),
        original_order_status_counts=dict(Counter(order['status'] for p in compatible for order in p['original_plane']['orders'])),
        triggers_without_energy_compatible_pairing=sum(not any(p['energy_compatible'] for p in r['pairings']) for r in rows),
        triggers_with_nominal_observed_sum_order=sum(any(o['kinematically_allowed'] for p in r['pairings']
                                                         for o in p['original_observed_sum_orders']) for r in rows),
        measured_pairings=len(pairs), energy_compatible_pairings=len(compatible),
        energy_incompatible_pairings=len(pairs)-len(compatible),
        triggers_without_admissible_nominal_escape=sum(not allowed for allowed in trigger_escape_sets),
        supplied_line_escape_counts=[dict(incident_energy_keV=line,
                                          triggers_with_any_nominal_escape_order=sum(line in allowed for allowed in trigger_escape_sets))
                                     for line in lines])
    if any(summary[key] != layer[key] for key in ('triggers', 'projected_mass', 'unresolved_mass')):
        raise ValueError('The original measured window census does not close')
    return summary


def peak_support(rows, case):
    """Partition original order contributions by their nominal escape compatibility."""
    contributions = case['trigger_contributions']
    if [row['original_trigger_id'] for row in rows] != [r['original_trigger_id'] for r in contributions]:
        raise ValueError('Peak attribution belongs to different measured trigger IDs')
    partition = defaultdict(list)
    order_contributions = []
    for row, attribution in zip(rows, contributions, strict=True):
        original = {(p['pair_index'], tuple(o['order'])): (p, o['status'])
                    for p in row['pairings'] if p['energy_compatible']
                    for o in p['original_plane']['orders'] if o['status'] in ('projected', 'no_plane_response')}
        support = attribution['orders']
        ids = [(o['pair_index'], tuple(o['order'])) for o in support]
        if len(set(ids)) != len(ids) or set(ids) != set(original):
            raise ValueError('Peak attribution belongs to different projected pair/order identities')
        if any(not close_mass(math.fsum(o[key] for o in support), attribution['support'][key])
               for key in ('peak_cell', 'edge_cells')):
            raise ValueError('Saved order contributions do not close against the original trigger support')
        for order, identity in zip(support, ids, strict=True):
            pair, status = original[identity]
            allowed = escape_lines(pair, identity[1])
            part = dict(original_trigger_id=row['original_trigger_id'], pair_index=identity[0],
                        order=identity[1], original_plane_status=status, nominal_escape_lines_keV=allowed,
                        peak_cell_mass=order['peak_cell'], edge_cells_mass=order['edge_cells'])
            order_contributions.append(part)
            partition[allowed].append(part)
    peak = case['peak']
    peak_mass = peak['mass'] if peak else 0.
    if not close_mass(math.fsum(o['peak_cell_mass'] for o in order_contributions), peak_mass):
        raise ValueError('Order contributions do not close against the original peak cell')
    groups = []
    for allowed, orders in sorted(partition.items()):
        mass = math.fsum(o['peak_cell_mass'] for o in orders)
        groups.append(dict(nominal_escape_lines_keV=allowed,
                           original_projected_orders=sum(o['original_plane_status'] == 'projected' for o in orders),
                           peak_cell_mass=mass, peak_cell_share=mass/peak_mass if peak_mass else None,
                           edge_cells_mass=math.fsum(o['edge_cells_mass'] for o in orders)))
    return dict(original_peak=peak, order_contributions=order_contributions, by_nominal_escape_lines=groups)


def score_origins(rows, origin, saved_sha256, attribution_sha256):
    """Join measured hypotheses to independent, peak-selected photon histories."""
    science = origin['science']
    if (origin['kind'] != 'gegi_ten_cobalt_peak_trigger_origins_v1'
            or science['analysis_input_sha256'] != saved_sha256 or science['attribution_sha256'] != attribution_sha256):
        raise ValueError('Photon histories do not refer to the same saved map and peak attribution')
    by_id = {r['original_trigger_id']: r for r in rows}
    scored = []
    for label, window in science['windows'].items():
        for trigger in window['triggers']:
            tid = trigger['original_trigger_id']
            row = by_id[tid]
            if row['measured_window'] != label or row['energy_keV'] != trigger['measured_energy_keV']:
                raise ValueError(f'Photon history differs from saved trigger {tid}')
            truth = trigger['photon_truth']
            photons = [p for p in truth['emitted_gammas'] if p['ge_deposited_keV'] > 0]
            energy = photons[0]['emitted_keV'] if len(photons) == 1 else None
            result = dict(original_trigger_id=tid, measured_window=label,
                          original_peak_cell_share=trigger['original_peak_cell_share'], depositing_photons=photons,
                          physical_ge_interactions=len(truth['ge_interactions_matched_to_births']), pairings=[])
            for reference in trigger['measured_pairings']:
                pair = next(p for p in row['pairings'] if p['pair_index'] == reference['pair_index'])
                if pair['cells'] != reference['cells'] or pair['measured_site_energies_keV'] != reference['measured_site_energies_keV']:
                    raise ValueError(f'Photon history uses a different measured pair at trigger {tid}')
                index_order = tuple(reference['nominal_first_two_distinct_cell_order'] or ())
                line_scores = []
                for line in pair['kinematics'].get('incident_line_hypotheses', []):
                    incident = line['incident_energy_keV']
                    orders = line['two_resolved_scatter_escape_orders']
                    reference_order = next((o for o in orders if o['site_index_order'] == index_order), None)
                    line_scores.append(dict(
                        incident_energy_keV=incident, incident_minus_true_emitted_keV=incident-energy if energy is not None else None,
                        observed_sum_minus_incident_keV=line['observed_sum_minus_incident_keV'],
                        nominal_escape_orders=[o['site_index_order'] for o in orders if o['nominally_admissible']],
                        nominal_escape_in_truth_cell_order=reference_order))
                result['pairings'].append(dict(pair_index=pair['pair_index'],
                                               truth_first_two_distinct_cell_order=index_order or None,
                                               truth_cell_order_survives_original_projection=reference['nominal_order_survives_saved_projection'],
                                               line_scores=line_scores))
            scored.append(result)
    return dict(scope='Peak-selected photon histories, descriptive checks only. The physical cell sequence can contain merged scatters.',
                triggers=scored)


def run(saved_path, archive, lines, *, attribution_path=None, origin_path=None):
    started = time.perf_counter()
    model = hypotheses.configuration(lines)
    lines = model['incident_energies_keV']
    if not lines:
        raise ValueError('Supply at least one nominal incident energy')
    payload = saved_path.read_bytes()
    saved = json.loads(gzip.decompress(payload))
    hashes = dict(saved_plane=hashlib.sha256(payload).hexdigest(), candidate_store=workflow.sha(archive))
    if hashes['candidate_store'] != saved['input_sha256']['candidate_store']:
        raise ValueError('Candidate archive SHA-256 differs from the saved measured map')
    rows = measured_ledger(saved, archive, lines)
    masks = joint.spectral_membership([SimpleNamespace(energy_keV=row['energy_keV']) for row in rows], plane.LINE_ENERGIES_KEV)
    members = {label: [row for row, included in zip(rows, mask, strict=True) if included] for label, mask in masks.items()}
    for label, selected in members.items():
        for row in selected:
            row['measured_window'] = label
    members['all'] = rows
    windows = {label: census(selected, lines, saved['layers'][label]) for label, selected in members.items()}
    if attribution_path is not None:
        packed = attribution_path.read_bytes()
        attribution = json.loads(gzip.decompress(packed))
        hashes['peak_attribution'] = hashlib.sha256(packed).hexdigest()
        if (attribution['kind'] != 'gegi_five_second_candidate_peak_attribution_v1'
                or attribution['input_sha256']['saved_plane'] != hashes['saved_plane']):
            raise ValueError('Peak attribution was produced for a different saved map')
        baseline = f"{saved['grid']['extent_mm']:g}_mm_{saved['model']['plane_prior']}"
        for label, estimates in attribution['windows'].items():
            windows[label]['peak_support'] = peak_support(members[label], estimates['cases'][baseline])
    truth_score = None
    if origin_path is not None:
        if attribution_path is None:
            raise ValueError('Supply the original peak attribution when scoring photon histories')
        origin_payload = origin_path.read_bytes()
        truth_score = score_origins(rows, json.loads(origin_payload), hashes['saved_plane'], hashes['peak_attribution'])
        hashes['photon_origin_score_only'] = hashlib.sha256(origin_payload).hexdigest()
    modules = (records, storage, plane, hypotheses, joint, workflow)
    source = {Path(module.__file__).name: workflow.sha(module.__file__) for module in modules}
    source[Path(__file__).name] = workflow.sha(__file__)
    return dict(kind='gegi_saved_candidate_kinematic_ledger_v1', input_sha256=hashes, source_sha256=source,
                model=model, original_selection=saved['selection'], windows=windows, triggers=rows,
                photon_origin_score=truth_score,
                methods=dict(
                    measured_pair='Original X/Y face assignments and ADC-derived cell energies. Incompatible face assignments retain their measurements but lack a coherent two-cell energy hypothesis.',
                    projections='All original plane weights and statuses are retained. A nominal energy check supplies neither a new projection nor a fitted source or event classification.',
                    peak_support='Each original order contributes to one set of admissible supplied escape energies. Empty sets represent orders outside all supplied nominal escape hypotheses.',
                    origin_score='Independent photon histories enter only after the saved-population ledger and original peak summaries are complete.'),
                software=dict(python=platform.python_version(), numpy=np.__version__, sqlite=storage.sqlite3.sqlite_version),
                elapsed_seconds=time.perf_counter()-started)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--saved-plane', type=Path, required=True)
    parser.add_argument('--archive', type=Path, help='Candidate archive alongside the saved map by default.')
    parser.add_argument('--incident-energy-keV', type=float, action='append', required=True)
    parser.add_argument('--peak-attribution', type=Path)
    parser.add_argument('--photon-origin-score', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    result = run(args.saved_plane, args.archive or args.saved_plane.parent/storage.ARCHIVE_NAME, args.incident_energy_keV,
                 attribution_path=args.peak_attribution, origin_path=args.photon_origin_score)
    packed = gzip.compress(workflow.encoded(result)+b'\n', mtime=0)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('xb') as stream:
        stream.write(packed)
    print(json.dumps(dict(elapsed_seconds=result['elapsed_seconds'], **result['windows']['all']), indent=2))


if __name__ == '__main__':
    main()
