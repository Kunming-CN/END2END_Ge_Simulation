"""Saved-only parent-gamma interaction references for the fixed153map groups."""
from __future__ import annotations
import argparse
from collections import Counter
from contextlib import closing
import gzip
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import time
import zlib

import numpy as np
import gegi_rejection_diagnostic as D
import gegi_recovery_validation as V
import gegi_saved_reconstruction as S

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ('tools/gegi_parent_gamma_reference.py', 'tools/test_gegi_parent_gamma_reference.py',
    'tools/gegi_rejection_diagnostic.py', 'tools/gegi_recovery_validation.py', 'tools/gegi_saved_reconstruction.py',
    'transport/gegi_source.py', 'transport/gegi_geometry.py')


def rows(path):
    with gzip.open(path, 'rt', encoding='utf-8') as stream:
        return [json.loads(line) for line in stream]


def ancestry(track_id, tracks):
    chain, seen = [], set()
    cursor = track_id
    while cursor in tracks and cursor not in seen:
        seen.add(cursor); chain.append(cursor)
        parent = tracks[cursor]['parent_trackid']
        if parent == 0:
            gammas = [i for i, tid in enumerate(chain) if tracks[tid]['particle'] == 22]
            if not gammas:
                return None, None, 'no_gamma_ancestor'
            index = gammas[-1]
            return chain[index], chain[index-1] if index else None, None
        cursor = parent
    return None, None, 'ancestry_cycle' if cursor in seen else 'missing_ancestor'


def reference(interactions, root_ids, unassigned_energy, conflicts, threshold):
    significant = [a for a in interactions if a['deposited_energy_keV'] >= threshold]
    base = {'threshold_keV': threshold, 'significant_interaction_count': len(significant),
        'unassigned_energy_keV': unassigned_energy, 'reference_cells_in_birth_order': None,
        'reference_interaction_keys_in_birth_order': None}
    reason = ('ancestry_or_identity_conflict' if conflicts else 'root_gamma_count_not_one' if len(root_ids) != 1 else
        'unassigned_energy_reaches_threshold' if unassigned_energy >= threshold else
        'significant_interaction_count_not_two' if len(significant) != 2 else None)
    cells = []
    if reason is None:
        for interaction in significant:
            xs = [cid for cid, e in interaction['endpoint_x_input_keV'].items() if e >= threshold]
            ys = [cid for cid, e in interaction['endpoint_y_input_keV'].items() if e >= threshold]
            pairs = [tuple(v['cell']) for v in interaction['collector_cells'] if v['energy_keV'] >= threshold]
            if len(xs) != 1 or len(ys) != 1 or len(pairs) != 1 or pairs[0] != (xs[0], ys[0]):
                reason = 'interaction_spans_multiple_or_no_significant_cells'; break
            cells.append(pairs[0])
        if reason is None and cells[0] == cells[1]:
            reason = 'parent_interactions_share_significant_cell'
        if reason is None and significant[0]['birth_time_ns'] == significant[1]['birth_time_ns']:
            reason = 'interaction_birth_times_tied'
    if reason is not None:
        return {**base, 'status': 'unknown', 'unknown_reason': reason}
    order = sorted(range(2), key=lambda i: significant[i]['birth_time_ns'])
    return {**base, 'status': 'major_interaction_reference_with_small_unassigned' if unassigned_energy > 0 else
        'major_interaction_reference', 'unknown_reason': None,
        'reference_cells_in_birth_order': [list(cells[i]) for i in order],
        'reference_interaction_keys_in_birth_order': [significant[i]['interaction_key'] for i in order]}


def evaluate(event, process_names, old):
    original_tracks = event['input_group']['parent_event_metadata']['tracks']
    tracks = {t['trackid']: t for t in original_tracks}
    conflicts = []
    duplicate_identity = len(tracks) != len(original_tracks)
    if duplicate_identity:
        conflicts.append('duplicate_track_identity')
    native_steps = {s['input_step_index']-1: s for s in (event.get('steps') or [])}
    interaction_map, root_energy, ledger, resolved = {}, Counter(), [], {}
    unassigned, assignment_reasons = 0., Counter()
    for index, step in enumerate(event['input_steps']):
        tid = step['track_id']
        if tid not in resolved:
            resolved[tid] = ancestry(tid, tracks)
        root, child, reason = resolved[tid]
        node = tracks.get(tid)
        if node is None or node['particle'] != step['particle_pdg']:
            root, child, reason = None, None, 'deposit_track_identity_conflict'
        if duplicate_identity:
            reason = 'duplicate_track_identity'
        if reason in ('ancestry_cycle', 'missing_ancestor', 'deposit_track_identity_conflict'):
            conflicts.append(reason)
        if root is not None:
            root_energy[root] += step['energy_keV']
        if reason is None and child is None:
            reason = 'direct_root_gamma_deposit_no_child_birth'
        child_record = tracks.get(child)
        required = ('xloc', 'yloc', 'zloc', 'time', 'procid')
        if reason is None and any(k not in child_record for k in required):
            reason = 'missing_child_birth_fields'; conflicts.append(reason)
        interaction_key = None
        if reason is None:
            position = D.pos(child_record)
            interaction_key = (*D.anchor_key(root, position), child_record['time'], child_record['procid'])
        saved = native_steps.get(index)
        if saved is not None and (saved['raw_row_index'] != step['raw_row_index'] or abs(saved['energy_keV']-step['energy_keV']) >= 1e-7):
            raise ValueError('Native endpoint row differs from input deposition')
        endpoint_energy = saved['energy_keV'] if saved else 0.
        endpoints = saved.get('endpoints', []) if saved else []
        xs = {cid for ep in endpoints for cid in ep.get('contact_ids', []) if 1 <= cid <= 16}
        ys = {cid for ep in endpoints for cid in ep.get('contact_ids', []) if 18 <= cid <= 33}
        cell = (next(iter(xs)), next(iter(ys))) if len(xs) == len(ys) == 1 else None
        if interaction_key is not None:
            item = interaction_map.setdefault(interaction_key, {'interaction_key': list(interaction_key),
                'root_gamma_trackid': root, 'birth_position_mm': list(position), 'birth_time_ns': child_record['time'],
                'birth_procid': child_record['procid'], 'birth_process': process_names.get(child_record['procid'], str(child_record['procid'])),
                'first_child_trackids': set(), 'deposited_energy_keV': 0., 'raw_row_indices': [],
                'endpoint_x_input_keV': Counter(), 'endpoint_y_input_keV': Counter(), 'cells': Counter()})
            item['first_child_trackids'].add(child); item['deposited_energy_keV'] += step['energy_keV']
            item['raw_row_indices'].append(step['raw_row_index'])
            for cid in xs:
                item['endpoint_x_input_keV'][cid] += endpoint_energy
            for cid in ys:
                item['endpoint_y_input_keV'][cid] += endpoint_energy
            if cell:
                item['cells'][cell] += endpoint_energy
        else:
            unassigned += step['energy_keV']; assignment_reasons[reason] += 1
        row = {'raw_row_index': step['raw_row_index'], 'depositing_trackid': tid,
            'energy_keV': step['energy_keV'], 'root_gamma_trackid': root, 'first_child_trackid': child,
            'interaction_key': list(interaction_key) if interaction_key else None, 'unassigned_reason': reason,
            'position_mm': step['position_mm'], 'step_clock_ns': step['time_ns'],
            'collector_pair': list(cell) if cell else None}
        if interaction_key is None:
            row['native_endpoints'] = endpoints
        ledger.append(row)
    interactions = []
    for item in interaction_map.values():
        item['first_child_trackids'] = sorted(item['first_child_trackids'])
        item['collector_cells'] = [{'cell': list(pair), 'energy_keV': energy} for pair, energy in sorted(item.pop('cells').items())]
        interactions.append(item)
    total = math.fsum(s['energy_keV'] for s in event['input_steps'])
    assigned = math.fsum(s['deposited_energy_keV'] for s in interactions)
    rooted = math.fsum(root_energy.values())
    unrooted = math.fsum(s['energy_keV'] for s in ledger if s['root_gamma_trackid'] is None)
    if not math.isclose(assigned+unassigned, total, abs_tol=1e-7) or not math.isclose(rooted+unrooted, total, abs_tol=1e-7):
        raise ValueError('Parent-interaction or root energy ledger does not conserve deposition')
    roots = []
    for root, energy in sorted(root_energy.items()):
        track = tracks[root]; birth_keV = track.get('ekin')
        birth_keV = birth_keV*1000 if birth_keV is not None and math.isfinite(birth_keV) else None
        roots.append({'trackid': root, 'parent_trackid': track['parent_trackid'], 'birth_time_ns': track.get('time'),
            'birth_procid': track.get('procid'), 'birth_process': process_names.get(track.get('procid')),
            'birth_kinetic_energy_keV': birth_keV, 'group_germanium_descendant_deposition_keV': energy,
            'group_deposition_minus_birth_kinetic_energy_keV': energy-birth_keV if birth_keV is not None else None})
    by_index = {h['hypothesis_index']: h for h in old['spatial_diagnostics']}
    references = {}
    for threshold in (5., 1.):
        ref = reference(interactions, root_energy, unassigned, conflicts, threshold)
        evaluations = []
        for candidate in old['candidates']:
            hypothesis = by_index[candidate['hypothesis_index']]
            sites = hypothesis['charge_deposition_centroid']
            predicted = [sites[i]['cell'] for i in candidate['order']]
            expected = ref['reference_cells_in_birth_order']
            status = ('unknown' if expected is None or sorted(predicted) != sorted(expected) else
                'correct' if predicted == expected else 'wrong')
            evaluations.append({'hypothesis_index': candidate['hypothesis_index'], 'order': candidate['order'],
                'prior_weight': candidate['prior_weight'], 'sequence_status': status,
                'sequence_unknown_reason': ref['unknown_reason'] if expected is None else
                    'predicted_cells_do_not_match_parent_interactions' if status == 'unknown' else None})
        ref['candidate_evaluation'] = evaluations
        references[f'ge{threshold:g}keV'] = ref
    return {'root_gammas': roots, 'parent_interactions': interactions, 'row_assignment_ledger': ledger,
        'input_deposited_energy_keV': total, 'assigned_interaction_energy_keV': assigned,
        'unassigned_interaction_energy_keV': unassigned, 'unrooted_energy_keV': unrooted,
        'interaction_assignment_closure_keV': assigned+unassigned-total,
        'root_assignment_closure_keV': rooted+unrooted-total,
        'unassigned_row_count': sum(s['interaction_key'] is None for s in ledger),
        'unassigned_row_reasons': dict(assignment_reasons), 'ancestry_or_identity_conflicts': sorted(set(conflicts)),
        'references': references}


def summarize(records, threshold):
    counts, reasons, roots, interactions, unassigned_reasons = Counter(), Counter(), Counter(), Counter(), Counter()
    energies = []
    for row in records:
        data = row['parent_gamma_evaluation']; ref = data['references'][threshold]
        counts['groups'] += 1; counts['candidate_count'] += len(ref['candidate_evaluation'])
        counts['groups_with_reference'] += ref['reference_cells_in_birth_order'] is not None
        counts['groups_with_small_unassigned_reference'] += ref['status'] == 'major_interaction_reference_with_small_unassigned'
        counts['groups_with_unassigned_energy'] += data['unassigned_interaction_energy_keV'] > 0
        counts['unassigned_rows'] += data['unassigned_row_count']
        counts['ancestry_or_identity_conflict_groups'] += bool(data['ancestry_or_identity_conflicts'])
        if ref['unknown_reason']:
            reasons[ref['unknown_reason']] += 1
        statuses = {c['sequence_status'] for c in ref['candidate_evaluation']}
        counts['correct_present'] += 'correct' in statuses
        counts['correct_only'] += statuses == {'correct'}
        counts['wrong_only'] += statuses == {'wrong'}
        counts['both_correct_and_wrong'] += {'correct', 'wrong'}.issubset(statuses)
        counts['unknown_only'] += statuses == {'unknown'}
        roots[str(len(data['root_gammas']))] += 1
        interactions[str(ref['significant_interaction_count'])] += 1
        energies.append(data['unassigned_interaction_energy_keV'])
        unassigned_reasons.update(data['unassigned_row_reasons'])
    return {'counts': dict(counts), 'reference_unknown_reasons': dict(reasons),
        'all_positive_root_gamma_count_histogram': dict(roots), 'significant_parent_interaction_count_histogram': dict(interactions),
        'unassigned_energy_keV': V.describe(energies), 'unassigned_row_reasons': dict(unassigned_reasons)}


def run(campaign, previous, schema, output, max_seconds=180):
    started = time.perf_counter()
    if not 0 < max_seconds <= 180:
        raise ValueError('At most180seconds for this saved-only evaluation')
    campaign, previous, schema, output = map(Path, (campaign, previous, schema, output))
    if output.exists():
        raise FileExistsError('Preserve previous attempts')
    old = S.read(previous/'result.json'); seal = S.read(previous/'COMPLETE.json')
    if S.sha(previous/'result.json') != seal['result_sha256'] or S.sha(previous/'groups.jsonl.gz') != seal['group_ledger_sha256']:
        raise ValueError('Original153group evaluation seal differs')
    cohort = rows(previous/'groups.jsonl.gz')
    if len(cohort) != 153 or sum(len(r['candidates']) for r in cohort) != 287:
        raise ValueError('Use exact153mapgroups/287candidates')
    schema_report = S.read(schema/'schema-check.json')
    cache = {r['original_identity']['campaign_initial_id']: r for r in schema_report['records']}
    if len(cache) != 3:
        raise ValueError('Expected exactly3schema metadata caches')
    complete, chunks = S.sealed_chunks(campaign)
    if S.sha(campaign/'COMPLETE.json') != schema_report['campaign_complete_sha256']:
        raise ValueError('Campaign seal differs from schema evidence')
    chunk_map = {index: (seal_path, done) for index, seal_path, done in chunks}
    frozen = {name: S.sha(ROOT/name) for name in SOURCES}
    output.mkdir(parents=True)
    identity = {'kind': 'gegi_parent_gamma_reference_v1', 'source_sha256': frozen,
        'previous_result_sha256': seal['result_sha256'], 'previous_group_ledger_sha256': seal['group_ledger_sha256'],
        'schema_sha256': S.sha(schema/'schema-check.json'), 'campaign_complete_sha256': S.sha(campaign/'COMPLETE.json'),
        'max_seconds': max_seconds, 'working_root': str(ROOT), 'model': 'gpt-6.1-sol', 'reasoning_effort': 'ultra',
        'new_calls': {'physics': 0, 'waveform_read': 0, 'fit': 0, 'map': 0},
        'definition': 'Earliest recorded gamma ancestor, then its first child birth; key rootID+xyz rounded1e-6mm+exact birthtime+processID. Direct-root gamma deposition remains unassigned. No nearest matching.'}
    S.write(output/'identity.json', identity)
    processed, bindings = [], {}
    with gzip.open(output/'groups.jsonl.gz', 'xb') as target:
        for old_row in cohort:
            if time.perf_counter()-started > max_seconds:
                raise TimeoutError('Saved-only time limit; preserve this attempt, no automatic retry')
            original = old_row['original_identity']; eid = original['campaign_initial_id']
            index = original['chunk_index']; seal_path, done = chunk_map[index]
            if index not in bindings:
                manifest_path = seal_path.parent/'transport/stream/manifest.json'
                if S.sha(manifest_path) != done['artifacts']['transport/stream/manifest.json']['sha256']:
                    raise ValueError('Bound process table changed')
                manifest = S.read(manifest_path)
                bindings[index] = {'seal_sha256': S.sha(seal_path), 'manifest_sha256': S.sha(manifest_path),
                    'events_store_sha256_from_seal': done['artifacts']['events.sqlite']['sha256'], 'seed': manifest['seed'],
                    'process_names': {p['procid']: p['name'] for p in manifest['processes']}}
            if eid in cache:
                saved = cache[eid]; path = schema/'metadata'/f'{eid}.json.gz'
                if saved['original_identity'] != original or S.sha(path) != saved['cached_metadata_gzip_sha256']:
                    raise ValueError('Schema metadata cache identity differs')
                with gzip.open(path, 'rb') as stream:
                    body = stream.read()
                origin = 'schema_cache'
            else:
                path = seal_path.parent/'events.sqlite'; before = path.stat()
                with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True)) as db:
                    db.execute('PRAGMA query_only=ON')
                    blob, digest = db.execute('SELECT metadata,metadata_sha256 FROM events WHERE primary_id=? AND group_id=?',
                        (original['raw_primary_id'], original['pulse_group_id'])).fetchone()
                body = zlib.decompress(blob); after = path.stat()
                if digest != original['metadata_sha256'] or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise ValueError('Metadata identity or immutable-store stamp differs')
                origin = 'new_metadata_read'
            if hashlib.sha256(body).hexdigest() != original['metadata_sha256']:
                raise ValueError('Decompressed metadata hash differs')
            event = json.loads(body)
            if event['campaign_initial_offset']+original['raw_primary_id'] != eid or event['status'] != 'completed':
                raise ValueError('Original group identity/status differs')
            result = {'original_identity': original, 'cohort': old_row['cohort'],
                'map_reconstruction_energy_keV': old_row['map_reconstruction_energy_keV'], 'metadata_origin': origin,
                'unchanged_original_strict_candidates': old_row['candidates'],
                'parent_gamma_evaluation': evaluate(event, bindings[index]['process_names'], old_row)}
            processed.append(result); target.write(S.encoded(result)); target.flush()
            if len(processed) % 30 == 0:
                print(json.dumps({'groups': len(processed), 'elapsed_seconds': time.perf_counter()-started}), flush=True)
    if frozen != {name: S.sha(ROOT/name) for name in SOURCES} or S.sha(previous/'groups.jsonl.gz') != seal['group_ledger_sha256']:
        raise ValueError('Frozen source or original evaluation changed')
    for row in bindings.values():
        row.pop('process_names')
    report = {**identity, 'status': 'completed_parent_gamma_posthoc_reference',
        'elapsed_seconds': time.perf_counter()-started, 'metadata_cache_reused': sum(r['metadata_origin'] == 'schema_cache' for r in processed),
        'new_metadata_records_read': sum(r['metadata_origin'] == 'new_metadata_read' for r in processed),
        'map': {t: summarize(processed, t) for t in ('ge5keV', 'ge1keV')},
        'energy_closure_max_absolute_keV': {field: max(abs(r['parent_gamma_evaluation'][field]) for r in processed)
            for field in ('interaction_assignment_closure_keV', 'root_assignment_closure_keV')},
        'four_birth_order_only_groups': [{'campaign_initial_id': r['original_identity']['campaign_initial_id'],
            'map_reconstruction_energy_keV': r['map_reconstruction_energy_keV'],
            'root_gammas': r['parent_gamma_evaluation']['root_gammas'],
            'unassigned_interaction_energy_keV': r['parent_gamma_evaluation']['unassigned_interaction_energy_keV'],
            'parent_interactions': [{k: a[k] for k in ('root_gamma_trackid', 'birth_process', 'birth_procid',
                'birth_time_ns', 'birth_position_mm', 'deposited_energy_keV', 'collector_cells')}
                for a in r['parent_gamma_evaluation']['parent_interactions']]}
            for r in processed if r['original_identity']['campaign_initial_id'] in (235273, 879908, 906665, 913963)],
        'spectral_layers': {f'{center:g}_keV': {t: summarize([r for r in processed if
            abs(r['map_reconstruction_energy_keV']-center) <= max(5., .02*center)], t) for t in ('ge5keV', 'ge1keV')}
            for center in (661.657, 1173.228, 1332.492)}, 'original_chunk_bindings': bindings,
        'original_initial_denominators': complete['groups'], 'group_ledger_sha256': S.sha(output/'groups.jsonl.gz'),
        'limits': ['This separate reference never changes strict labels, priors, thresholds, map or fits.',
            'Birth kinetic energy is not detector-entry energy. Near energy balance alone does not establish full absorption or absence of preceding scatter.',
            'Direct-root gamma rows retain position, step clock, energy and endpoints without inventing interaction birth times.',
            'A main-interaction reference may retain unassigned energy below its declared threshold; it does not assert exactly2microscopic interactions.',
            'Endpoint X/Y and unique pair allocation follow the existing D.topology native-step logic; no native arrays are read.']}
    S.write(output/'result.json', report)
    S.write(output/'COMPLETE.json', {'status': report['status'], 'identity_sha256': S.sha(output/'identity.json'),
        'result_sha256': S.sha(output/'result.json'), 'group_ledger_sha256': report['group_ledger_sha256']})
    print(json.dumps({'result_sha256': S.sha(output/'result.json'), 'elapsed_seconds': report['elapsed_seconds'],
        'cache_reused': report['metadata_cache_reused'], 'new_metadata_records_read': report['new_metadata_records_read'],
        'map': report['map']}), flush=True)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('campaign', 'previous', 'schema', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--max-seconds', type=float, default=180)
    args = parser.parse_args()
    run(args.campaign, args.previous, args.schema, args.output, args.max_seconds)
