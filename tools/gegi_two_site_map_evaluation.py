"""Posthoc evaluation of the already frozen153two-site map groups.

Only saved metadata is read; no waveform, response, fit or map is recomputed.
The original400split stays fixed. Additional map groups are supplemental.
"""
from __future__ import annotations
import argparse
from collections import Counter
from contextlib import closing
import copy
import gzip
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import time
import zlib

import numpy as np
import gegi_recovery_validation as V
import gegi_rejection_diagnostic as D
import gegi_saved_reconstruction as S


ROOT = Path(__file__).resolve().parents[1]
SOURCES = ('tools/gegi_two_site_map_evaluation.py', 'tools/test_gegi_two_site_map_evaluation.py',
    'tools/gegi_recovery_validation.py', 'tools/gegi_rejection_diagnostic.py',
    'tools/gegi_saved_reconstruction.py')


def load_rows(path):
    with gzip.open(path, 'rt', encoding='utf-8') as stream:
        return [json.loads(line) for line in stream]


def key(identity):
    return identity['campaign_initial_id'], identity['pulse_group_id']


def anchor_identity_map(event):
    """Preserve every positive-row ancestry link, with no significance cut."""
    tracks = {t['trackid']: t for t in event['input_group']['parent_event_metadata']['tracks']}
    births, seed_records = {}, {}
    for tid, track in tracks.items():
        parent = tracks.get(track['parent_trackid'])
        if track['particle'] != 22 and parent and parent['particle'] == 22:
            anchor = D.anchor_key(parent['trackid'], D.pos(track))
            births[tid] = anchor
            seed_records.setdefault(anchor, []).append(tid)
    anchors, assignments, used_tracks = {}, [], set()
    for step in event['input_steps']:
        tid = step['track_id']; anchor = None; seen = set()
        if step['particle_pdg'] == 22:
            anchor = D.anchor_key(tid, step['position_mm'])
        else:
            cursor = tid
            while cursor in tracks and cursor not in seen:
                seen.add(cursor)
                if cursor in births:
                    anchor = births[cursor]; break
                if tracks[cursor]['particle'] == 22:
                    break
                cursor = tracks[cursor]['parent_trackid']
        used_tracks.update(seen); used_tracks.add(tid)
        if anchor is not None:
            used_tracks.add(anchor[0]); used_tracks.update(seed_records.get(anchor, []))
            birth_position = D.pos(tracks[seed_records[anchor][0]]) if anchor in seed_records else step['position_mm']
            row = anchors.setdefault(anchor, {'anchor_key': list(anchor), 'recorded_photon_track_id': anchor[0],
                'birth_position_mm': list(birth_position), 'recorded_secondary_birth': anchor in seed_records,
                'secondary_birth_track_ids': seed_records.get(anchor, []), 'deposited_energy_keV': 0.,
                'raw_row_indices': [], 'deposition_centroid_mm': np.zeros(3)})
            row['deposited_energy_keV'] += step['energy_keV']
            row['deposition_centroid_mm'] += step['energy_keV']*np.asarray(step['position_mm'])
            row['raw_row_indices'].append(step['raw_row_index'])
        assignments.append({'raw_row_index': step['raw_row_index'], 'depositing_track_id': tid,
            'energy_keV': step['energy_keV'], 'anchor_key': list(anchor) if anchor is not None else None})
    for row in anchors.values():
        row['deposition_centroid_mm'] = (row['deposition_centroid_mm']/row['deposited_energy_keV']).tolist()
    # Retain all relevant ancestry IDs/processes/clocks, without source positions.
    for tid in list(used_tracks):
        seen = set()
        while tid in tracks and tid not in seen:
            seen.add(tid); used_tracks.add(tid); tid = tracks[tid]['parent_trackid']
    identities = [{k: tracks[tid][k] for k in ('trackid', 'parent_trackid', 'particle', 'procid', 'time')
                   if k in tracks[tid]} for tid in sorted(used_tracks) if tid in tracks]
    return {'anchors_all_positive_energy': list(anchors.values()), 'row_anchor_assignments': assignments,
        'track_identity_ancestry': identities,
        'contributing_recorded_photon_ids_all_positive_energy': sorted({a[0] for a in anchors}),
        'unmapped_positive_rows': sum(r['anchor_key'] is None for r in assignments)}


def spatial_diagnostics(result, sites, cells, truth_order, unknown, endpoint_known):
    """Cell centroids and, only with an exact reference, photon birth vertices."""
    indices = {c['hypothesis_index'] for c in result['candidates']}
    good = {cell: v for cell, v in cells.items() if v[0] >= 5.}
    vertices = {}
    if endpoint_known and truth_order is not None and len(sites) == 2:
        for site in sites:
            xs = [cid for cid, e in site['x'].items() if e >= 5.]
            ys = [cid for cid, e in site['y'].items() if e >= 5.]
            if len(xs) == len(ys) == 1:
                vertices[xs[0], ys[0]] = site['position']
    rows = []
    for hypothesis in result['hypotheses']:
        if hypothesis['hypothesis_index'] not in indices:
            continue
        predicted = hypothesis['sites']
        pairs = [(s['x_contact'], s['y_contact']) for s in predicted]
        centroid_rows = []
        for site, cell in zip(predicted, pairs):
            if cell not in good:
                continue
            energy, moment = good[cell]; centroid = moment/energy
            delta = np.asarray(site['position_mm'])-centroid
            centroid_rows.append({'cell': list(cell), 'reconstructed_position_mm': site['position_mm'],
                'deposition_centroid_mm': centroid.tolist(), 'position_error_xyz_mm': delta.tolist(),
                'position_error_3d_mm': float(np.linalg.norm(delta)),
                'endpoint_input_energy_keV': energy, 'reconstructed_energy_keV': site['energy_keV'],
                'energy_error_keV': site['energy_keV']-energy})
        vertex_rows = None
        reason = ('native_endpoint_topology_incomplete' if not endpoint_known else
            unknown if truth_order is None else 'significant_anchor_count_not_two' if len(sites) != 2 else
            'predicted_cells_not_exact_reference_pair' if set(pairs) != set(vertices) or len(pairs) != 2 else None)
        if reason is None:
            vertex_rows = []
            for site, cell in zip(predicted, pairs):
                delta = np.asarray(site['position_mm'])-vertices[cell]
                vertex_rows.append({'cell': list(cell), 'reconstructed_position_mm': site['position_mm'],
                    'photon_interaction_birth_position_mm': list(vertices[cell]),
                    'position_error_xyz_mm': delta.tolist(), 'position_error_3d_mm': float(np.linalg.norm(delta))})
        rows.append({'hypothesis_index': hypothesis['hypothesis_index'],
            'charge_deposition_centroid': centroid_rows, 'photon_interaction_vertex': vertex_rows,
            'photon_vertex_unknown_reason': reason})
    return rows


def summarize(rows):
    counts, hypotheses, sequence, topology = Counter(), Counter(), Counter(), Counter()
    residuals = {k: [] for k in ('centroid_error_3d_mm', 'centroid_abs_x_mm', 'centroid_abs_y_mm',
        'centroid_abs_z_mm', 'cell_abs_energy_error_keV', 'photon_vertex_error_3d_mm',
        'photon_vertex_abs_x_mm', 'photon_vertex_abs_y_mm', 'photon_vertex_abs_z_mm')}
    reasons, group_reasons = Counter(), Counter()
    for row in rows:
        counts['groups'] += 1; counts['candidates'] += len(row['candidates'])
        counts['reused_prior_evaluation_groups'] += row['evaluation_metrics_reused']
        counts['supplemental_map_population_groups'] += row['cohort'] == 'supplemental_map_population_diagnosis'
        counts['native_failed_groups'] += row['native_status'] == 'native_failed'
        counts['native_incomplete_groups'] += row['native_status'] != 'completed'
        statuses = {c['sequence_status'] for c in row['candidates']}
        counts['correct_present'] += 'correct' in statuses
        counts['wrong_only'] += statuses == {'wrong'}
        counts['both_correct_and_wrong'] += {'correct', 'wrong'}.issubset(statuses)
        counts['unknown_only'] += statuses == {'unknown'}
        counts['correct_only'] += statuses == {'correct'}
        counts['other_mixed'] += len(statuses) > 1 and not {'correct', 'wrong'}.issubset(statuses)
        unknown = [c['sequence_unknown_reason'] for c in row['candidates'] if c['sequence_status'] == 'unknown']
        reasons.update(unknown); group_reasons.update(set(unknown))
        for c in row['candidates']:
            sequence[c['sequence_status']] += 1
            sequence[c['sequence_status']+'_prior_mass'] += c['prior_weight']
        for h in row['hypotheses']:
            hypotheses['conditional_hypotheses'] += 1
            for name, value in (('pairing_matches', h['endpoint_pairing_matches'] is True),
                ('pairing_mismatches', h['endpoint_pairing_matches'] is False),
                ('pairing_unknown', h['endpoint_pairing_matches'] is None),
                ('false_splitting', h['false_gamma_anchor_splitting'] is True),
                ('splitting_unknown', h['false_gamma_anchor_splitting'] is None)):
                hypotheses[name] += value
        truth = row['truth']; n = truth['significant_gamma_anchors_ge5keV']
        topology['gamma_anchors_ge5:'+str(n)] += 1
        topology['contributing_recorded_photons_ge5:'+str(len(truth['contributing_recorded_photon_ids_ge5']))] += 1
        for name in ('more_than_two_gamma_anchors_ge5', 'one_recorded_photon_ge5',
                     'direct_charged_ge5', 'multiple_anchors_shared_strip', 'multiple_anchors_shared_cell',
                     'single_anchor_multiple_strips', 'unmatched_significant_gamma_deposit'):
            topology[name] += bool(truth[name])
        for h in row['spatial_diagnostics']:
            for v in h['charge_deposition_centroid']:
                residuals['centroid_error_3d_mm'].append(v['position_error_3d_mm'])
                residuals['cell_abs_energy_error_keV'].append(abs(v['energy_error_keV']))
                for axis, delta in zip('xyz', v['position_error_xyz_mm']):
                    residuals['centroid_abs_'+axis+'_mm'].append(abs(delta))
            for v in h['photon_interaction_vertex'] or []:
                residuals['photon_vertex_error_3d_mm'].append(v['position_error_3d_mm'])
                for axis, delta in zip('xyz', v['position_error_xyz_mm']):
                    residuals['photon_vertex_abs_'+axis+'_mm'].append(abs(delta))
    return {'counts': dict(counts), 'hypotheses': dict(hypotheses), 'sequence': dict(sequence),
        'unknown_reasons_candidate_counts': dict(reasons), 'unknown_reasons_group_counts': dict(group_reasons),
        'overlapping_topology_counts': dict(topology), 'errors': {k: V.describe(v) for k, v in residuals.items()}}


def run(campaign, reconstruction, selected_output, validation, output, max_seconds=180, checkpoint=None):
    started = time.perf_counter()
    if not 0 < max_seconds <= 180:
        raise ValueError('This saved-only evaluation is bounded to at most180seconds')
    campaign, reconstruction, selected_output, validation, output = map(Path,
        (campaign, reconstruction, selected_output, validation, output))
    if output.exists():
        raise FileExistsError('Preserve existing evaluation evidence')
    prior = S.read(selected_output/'result.json'); prior_seal = S.read(selected_output/'COMPLETE.json')
    if (S.sha(selected_output/'result.json') != prior_seal['result_sha256'] or
            S.sha(selected_output/'selected-records.jsonl.gz') != prior['artifact_sha256']['selected-records.jsonl.gz']):
        raise ValueError('Frozen two-site selection binding differs')
    selected = load_rows(selected_output/'selected-records.jsonl.gz')
    chosen = {key(r): r for r in selected}
    if len(chosen) != 153 or sum(len(r['candidates']) for r in selected) != 287:
        raise ValueError('Use the exact frozen153groups/287candidates')
    sources = {name: S.sha(ROOT/name) for name in SOURCES}
    output.mkdir(parents=True)
    frozen = {'selection_records_sha256': S.sha(selected_output/'selected-records.jsonl.gz'),
        'selection_result_sha256': S.sha(selected_output/'result.json'),
        'selection_fields': 'Existing campaign_initial_id, pulse_group_id, reconstructed energy and candidate list only',
        'truth_or_source_used_to_select': False,
        'groups': [{'campaign_initial_id': r['campaign_initial_id'], 'pulse_group_id': r['pulse_group_id'],
            'energy_keV': r['energy_keV'], 'candidate_count': len(r['candidates']),
            'candidates_sha256': hashlib.sha256(S.encoded(r['candidates'])).hexdigest()} for r in selected]}
    S.write(output/'frozen-selection.json', frozen)
    pins = {'campaign_complete': S.sha(campaign/'COMPLETE.json'),
        'reconstruction_complete': S.sha(reconstruction/'COMPLETE.json'),
        'prior_two_site_evaluation': S.sha(selected_output/'evaluation-groups.jsonl.gz'),
        'original_split_manifest': S.sha(validation/'split-manifest.json')}
    if pins['reconstruction_complete'] != prior['input_sha256']['reconstruction_complete']:
        raise ValueError('Frozen selection refers to another reconstruction')
    if pins['prior_two_site_evaluation'] != prior['artifact_sha256']['evaluation-groups.jsonl.gz']:
        raise ValueError('Prior evaluation rows changed')
    split = S.read(validation/'split-manifest.json')
    if pins['original_split_manifest'] != prior['input_sha256']['split_manifest']:
        raise ValueError('Original400split changed')
    V.check_disjoint(split['groups'])
    membership = {r['campaign_initial_id']: r['split'] for r in split['assignments']}
    reused = {key(r['original_identity']): r for r in load_rows(selected_output/'evaluation-groups.jsonl.gz')
              if key(r['original_identity']) in chosen}
    if len(reused) != 8:
        raise ValueError('Expected exactly8previously evaluated map groups')
    identity = {'kind': 'gegi_two_site_map_posthoc_evaluation_v1', 'source_sha256': sources,
        'input_sha256': pins, 'frozen_selection_sha256': S.sha(output/'frozen-selection.json'),
        'model': 'gpt-6.1-sol', 'reasoning_effort': 'ultra', 'working_root': str(ROOT),
        'model_effort_evidence': 'Assigned worker session context; not external runtime attestation',
        'max_seconds': max_seconds, 'new_calls': {'transport': 0, 'native_drift': 0, 'field_solve': 0,
            'calibration': 0, 'waveform_fit': 0, 'map_optimizer': 0}}
    checkpoint_rows = {}
    if checkpoint is not None:
        checkpoint = Path(checkpoint)
        previous = S.read(checkpoint/'identity.json')
        if (previous['input_sha256'] != pins or
                S.read(checkpoint/'frozen-selection.json') != frozen or
                any(previous['source_sha256'][name] != sources[name] for name in SOURCES
                    if name != 'tools/gegi_two_site_map_evaluation.py')):
            raise ValueError('Checkpoint cohort, scientific helper or input binding differs')
        for row in load_rows(checkpoint/'groups.jsonl.gz'):
            k = key(row['original_identity'])
            if k not in chosen or k in checkpoint_rows:
                raise ValueError('Checkpoint contains duplicate or foreign group')
            expected = [(c['hypothesis_index'], c['order'], c['prior_weight']) for c in chosen[k]['candidates']]
            actual = [(c['hypothesis_index'], c['order'], c['prior_weight']) for c in row['candidates']]
            if actual != expected:
                raise ValueError('Checkpoint candidate identity/order/priors differ')
            checkpoint_rows[k] = row
        identity['preceding_checkpoint'] = {'identity_sha256': S.sha(checkpoint/'identity.json'),
            'group_ledger_sha256': S.sha(checkpoint/'groups.jsonl.gz'), 'groups': len(checkpoint_rows),
            'source_sha256': previous['source_sha256']['tools/gegi_two_site_map_evaluation.py']}
    S.write(output/'identity.json', identity)

    def budget():
        if time.perf_counter()-started > max_seconds:
            raise TimeoutError('Bounded saved-metadata evaluation time limit; checkpoints retained')

    saved = {}
    for record in V.records(reconstruction):
        budget(); k = key(record['original_identity'])
        if k in chosen:
            result = record['reconstruction']
            projected = {'campaign_initial_id': k[0], 'pulse_group_id': k[1], 'energy_keV': result['energy_keV'],
                'candidates': [c for c in result['candidates'] if len(c['order']) == 2]}
            if projected != chosen[k]:
                raise ValueError('Saved reconstruction differs from frozen observable candidate list')
            saved[k] = record
    if set(saved) != set(chosen):
        raise ValueError('Frozen map group missing from sealed reconstruction')
    complete, chunks = S.sealed_chunks(campaign)
    chunk_map = {index: (seal, done) for index, seal, done in chunks}
    all_rows, inventories = [], {}
    with gzip.open(output/'groups.jsonl.gz', 'xb') as target:
        for k in sorted(chosen):
            budget(); record = saved[k]; original = record['original_identity']
            index, pid, gid = (original[x] for x in ('chunk_index', 'raw_primary_id', 'pulse_group_id'))
            seal, done = chunk_map[index]; dbpath = seal.parent/'events.sqlite'
            if index not in inventories:
                manifest_path = seal.parent/'transport/stream/manifest.json'
                if S.sha(manifest_path) != done['artifacts']['transport/stream/manifest.json']['sha256']:
                    raise ValueError('Process manifest changed')
                manifest = S.read(manifest_path)
                receipt = S.read(reconstruction/'chunks'/f'{index:03d}.json')
                if receipt['input_store_sha256'] != done['artifacts']['events.sqlite']['sha256']:
                    raise ValueError('Sealed reconstruction/store binding differs')
                inventories[index] = {'seal_sha256': S.sha(seal), 'events_store_sha256_from_seal': receipt['input_store_sha256'],
                    'process_manifest_sha256': S.sha(manifest_path), 'seed': manifest['seed'],
                    'process_names': {t['procid']: t['name'] for t in manifest['processes']},
                    'metadata_records_read': 0, 'checkpoint_metadata_records_reused': 0}
            if k in checkpoint_rows:
                row = checkpoint_rows[k]
                if row['original_identity'] != original:
                    raise ValueError('Checkpoint original metadata identity differs')
                inventories[index]['checkpoint_metadata_records_reused'] += 1
                all_rows.append(row); target.write(S.encoded(row)); target.flush()
                continue
            before = dbpath.stat()
            with closing(sqlite3.connect(dbpath.resolve().as_uri()+'?mode=ro', uri=True)) as db:
                db.execute('PRAGMA query_only=ON')
                blob, digest = db.execute('SELECT metadata,metadata_sha256 FROM events WHERE primary_id=? AND group_id=?',
                    (pid, gid)).fetchone()
                body = zlib.decompress(blob)
            if hashlib.sha256(body).hexdigest() != digest or digest != original['metadata_sha256']:
                raise ValueError('Saved metadata differs from original identity/hash')
            event = json.loads(body); after = dbpath.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ValueError('Original store changed during metadata read')
            if (event['event_id'] != pid or event.get('group_id', 0) != gid or
                    event['campaign_initial_offset']+pid != k[0] or event['status'] != record['native_status']):
                raise ValueError('Saved metadata original group identity differs')
            inventories[index]['metadata_records_read'] += 1
            topology, endpoint_known = V.posthoc_topology(event, inventories[index]['process_names'])
            sites, sites1, compton, spread, shared, direct, cells, length = topology
            truth_order, unknown = (V.sequence_truth(event, sites, direct) if endpoint_known else
                (None, 'native_endpoint_topology_incomplete'))
            result = {**record['reconstruction'], 'candidates': chosen[k]['candidates']}
            if k in reused:
                old = reused[k]
                if old['original_identity'] != original:
                    raise ValueError('Prior evaluation original identity differs')
                hypotheses, candidates = copy.deepcopy(old['hypotheses']), copy.deepcopy(old['candidates'])
            else:
                hypotheses, candidates = V.evaluate_reconstruction(result, sites, direct, cells, truth_order, unknown)
            significant_cells = []
            for site in sites:
                xs = [cid for cid, energy in site['x'].items() if energy >= 5.]
                ys = [cid for cid, energy in site['y'].items() if energy >= 5.]
                if len(xs) == len(ys) == 1:
                    significant_cells.append((xs[0], ys[0]))
            photon_ids = sorted({s['photon_id'] for s in sites})
            anchor_map = anchor_identity_map(event)
            for anchor in anchor_map['anchors_all_positive_energy']:
                match = next((s for s in sites1 if D.anchor_key(s['photon_id'], s['position']) == tuple(anchor['anchor_key'])), None)
                if match:
                    anchor['endpoint_x_input_keV'] = dict(match['x']); anchor['endpoint_y_input_keV'] = dict(match['y'])
                    anchor['process_names'] = sorted(match['processes'])
            row = {'original_identity': original, 'map_reconstruction_energy_keV': chosen[k]['energy_keV'],
                'cohort': membership.get(k[0], 'supplemental_map_population_diagnosis'),
                'evaluation_metrics_reused': k in reused, 'native_status': record['native_status'],
                'endpoint_topology_known': endpoint_known, 'hypotheses': hypotheses, 'candidates': candidates,
                'unresolved_hypothesis_mass': max(0., 1-math.fsum(c['prior_weight'] for c in candidates)),
                'spatial_diagnostics': spatial_diagnostics(result, sites, cells, truth_order, unknown, endpoint_known),
                'truth': {'significant_gamma_anchors_ge5keV': len(sites), 'gamma_anchors_ge1keV': len(sites1),
                    'contributing_recorded_photon_ids_ge5': photon_ids,
                    'contributing_recorded_photon_ids_ge1': sorted({s['photon_id'] for s in sites1}),
                    'direct_charged_energy_keV': direct, 'input_deposited_energy_keV': sum(s['energy_keV'] for s in event['input_steps']),
                    'compton': compton, 'single_anchor_multiple_strips': spread,
                    'multiple_anchors_shared_strip': shared,
                    'multiple_anchors_shared_cell': len(set(significant_cells)) < len(significant_cells),
                    'more_than_two_gamma_anchors_ge5': len(sites) > 2, 'one_recorded_photon_ge5': len(photon_ids) == 1,
                    'direct_charged_ge5': direct >= 5.,
                    'unmatched_significant_gamma_deposit': any('photon_deposit_without_recorded_secondary' in s['processes'] for s in sites),
                    'strict_sequence_reference_cells': truth_order, 'strict_sequence_unknown_reason': unknown,
                    'anchor_identity_mapping': anchor_map}}
            all_rows.append(row); target.write(S.encoded(row)); target.flush()
            if len(all_rows) % 20 == 0:
                print(json.dumps({'groups': len(all_rows), 'elapsed_seconds': time.perf_counter()-started}), flush=True)
    budget()
    if (sources != {name: S.sha(ROOT/name) for name in SOURCES} or
            S.sha(selected_output/'result.json') != prior_seal['result_sha256'] or
            S.sha(campaign/'COMPLETE.json') != pins['campaign_complete'] or
            S.sha(validation/'split-manifest.json') != pins['original_split_manifest']):
        raise ValueError('Frozen source, cohort, original campaign or split changed')
    centers = prior['saved_signal_accounting']['selection']['centers_keV']
    layers = {f'{center:g}_keV': summarize([r for r in all_rows
        if abs(r['map_reconstruction_energy_keV']-center) <= max(5., .02*center)]) for center in centers}
    for center, metrics in layers.items():
        if metrics['counts']['groups'] != prior['spectral_layers'][center]['retained_groups']:
            raise ValueError('Existing spectral-layer cohort census differs')
    for inventory in inventories.values():
        inventory.pop('process_names')
    report = {**identity, 'status': 'completed_posthoc_map_population_diagnosis',
        'elapsed_seconds': time.perf_counter()-started, 'map': summarize(all_rows), 'spectral_layers': layers,
        'by_original_cohort': {c: summarize([r for r in all_rows if r['cohort'] == c])
            for c in ('development', 'holdout', 'supplemental_map_population_diagnosis')},
        'original_initial_denominators': complete['groups'], 'original_failure_counts': prior['saved_signal_accounting']['counts'],
        'checks_used': {'sqlite_mode': 'read-only/query_only', 'whole_sqlite_hash_repeated': False,
            'native_arrays_opened': False, 'metadata_records_read_total': len(all_rows),
            'metadata_records_read_this_invocation': len(all_rows)-len(checkpoint_rows),
            'checkpoint_metadata_records_reused': len(checkpoint_rows),
            'existing_evaluation_metrics_reused': len(reused), 'new_evaluation_metric_groups': len(all_rows)-len(reused),
            'new_evaluation_metric_groups_this_invocation': sum(not r['evaluation_metrics_reused'] and
                key(r['original_identity']) not in checkpoint_rows for r in all_rows),
            'per_record_checks': 'decompressed metadata SHA equals stored SHA and sealed reconstruction original_identity SHA; event/group/offset/status; store size/mtime unchanged; DONE/COMPLETE/manifest and reconstruction chunk pins'},
        'original_chunk_bindings': inventories, 'group_ledger_sha256': S.sha(output/'groups.jsonl.gz'),
        'definitions': {'anchor_thresholds': 'Unchanged existing topology: significant>=5keV, sensitivity>=1keV; allpositive ancestry links additionally retained without a cut.',
            'pairing_and_centroid': 'Existing endpoint-cell comparison. Each conditional hypothesis once; residuals to energy-weighted native-input cell deposition centroid. Cells/hypotheses are not independent events.',
            'photon_vertex': 'Only when existing strict sequence reference has exactly2recorded same-photon anchors with unique cells and the predicted cell set exactly matches. Otherwise null with reason; no nearest-vertex assignment.',
            'sequence': 'Saved posthoc original birth-time reference, not hard-choice order error rate. Unknowns explicit; correct-present overlaps both-correct-and-wrong.',
            'cohort': 'Exact already-saved153observable-only mapgroups; original400split preserved.145additional groups are supplemental map-population diagnosis, never an untouched holdout.',
            'photon_identity': 'Recorded contributing gamma trackIDs, with parent/process/clock identity links. Secondary photons retain separate trackIDs; no source positions used.',
            'scope': 'Simulation posthoc diagnosis only, not hardware validation. No truth enters selection, fitting or map. No waveform reading, classification, reconstruction, calibration or cut tuning.'}}
    S.write(output/'result.json', report)
    S.write(output/'COMPLETE.json', {'status': report['status'], 'identity_sha256': S.sha(output/'identity.json'),
        'frozen_selection_sha256': S.sha(output/'frozen-selection.json'), 'result_sha256': S.sha(output/'result.json'),
        'group_ledger_sha256': report['group_ledger_sha256']})
    S.write(output/'progress.json', {'status': report['status'], 'groups': len(all_rows)})
    print(json.dumps({'elapsed_seconds': report['elapsed_seconds'], 'checks': report['checks_used'],
        'map': report['map'], 'result_sha256': S.sha(output/'result.json')}), flush=True)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('campaign', 'reconstruction', 'selected-output', 'validation', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--max-seconds', type=float, default=180)
    parser.add_argument('--checkpoint', type=Path, help='Explicit prior interrupted metadata ledger; never retried automatically')
    args = parser.parse_args()
    run(args.campaign, args.reconstruction, args.selected_output, args.validation, args.output, args.max_seconds, args.checkpoint)
