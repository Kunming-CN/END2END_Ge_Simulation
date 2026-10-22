"""Saved-data census for a frozen pre-SSD one/two gamma-anchor predicate.

This diagnostic never enables production selection or recomputes a response.
Anchors follow the existing one_gamma_anchor convention, not Geant4 row count.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
import os
from pathlib import Path
import time

import gegi_campaign_response as C
import gegi_saved_reconstruction as S
from gegi_rejection_diagnostic import anchor_key, pos


KIND = 'gegi_single_two_site_prefilter_v1'
PREDICATE = {
    'anchor': 'Existing gamma-parent/non-gamma-secondary birth anchor: (gamma trackID, birth xyz rounded to1e-6mm). Only anchors contributing positive group deposition rows count; no energy or distance cut.',
    'row_mapping': 'Non-gamma deposit follows ancestry to the first recorded gamma-parent birth; gamma deposit matches its own trackID/position to an existing birth anchor. Secondary gamma interactions have their own anchors.',
    'decision': 'All rows uniquely mapped: keep1or2complete anchors, screen more than2. Any direct/unmatched/missing/ambiguous ancestry: retain_unknown, even with more than2known anchors.',
    'hardware_correspondence': 'Transport ancestry proxy, not the ImagerPro single/two-site definition; actual.bin schema/sample still required.',
}
SOURCES = ('tools/gegi_single_two_site_prefilter.py', 'tools/gegi_campaign_response.py',
    'tools/gegi_saved_reconstruction.py', 'tools/gegi_rejection_diagnostic.py',
    'tools/gegi_transport_prefilter_feasibility.py', 'tools/test_gegi_single_two_site_prefilter.py')


def classify(group, event):
    """Classify a validated positive pulse group; uncertainty always retains it."""
    tracks = {t['trackid']: t for t in event['tracks']}
    if len(tracks) != len(event['tracks']):
        return {'decision': 'retain_unknown', 'complete_anchor_count': None,
            'known_anchor_count': 0, 'unknown_rows': len(group['steps']),
            'unknown_reasons': {'duplicate_track_id': len(group['steps'])}}
    births = {}
    for tid, track in tracks.items():
        parent = tracks.get(track['parent_trackid'])
        if track['particle'] != 22 and parent and parent['particle'] == 22:
            births[tid] = anchor_key(parent['trackid'], pos(track))
    anchors = set(births.values())
    resolved = {}

    def ancestor(tid):
        if tid in resolved:
            return resolved[tid]
        seen = set()
        cursor = tid
        while cursor in tracks and cursor not in seen:
            seen.add(cursor)
            if cursor in births:
                result = births[cursor], None
                break
            track = tracks[cursor]
            if track['particle'] == 22:
                result = None, 'unmatched_gamma_ancestor'
                break
            if track['parent_trackid'] == 0:
                result = None, 'direct_non_gamma'
                break
            cursor = track['parent_trackid']
        else:
            result = None, 'ancestry_cycle' if cursor in seen else 'missing_track_ancestor'
        resolved[tid] = result
        return result

    used, unknown = set(), Counter()
    for step in group['steps']:
        tid = step['track_id']
        if tid in tracks and tracks[tid]['particle'] != step['particle_pdg']:
            key, reason = None, 'particle_identity_mismatch'
        elif step['particle_pdg'] == 22:
            key = anchor_key(tid, step['position_mm'])
            if key not in anchors:
                key = None
            reason = None if key is not None else 'unmatched_gamma_deposit'
        else:
            key, reason = ancestor(tid)
        if key is None:
            unknown[reason] += 1
        else:
            used.add(key)
    count = None if unknown else len(used)
    return {'decision': 'retain_unknown' if unknown else 'screen_gt2' if count > 2 else 'retain_le2',
        'complete_anchor_count': count, 'known_anchor_count': len(used),
        'unknown_rows': sum(unknown.values()), 'unknown_reasons': dict(unknown)}


def comparison(reconstruction, use, native_status):
    """Saved hypotheses remain an imperfect comparator, never a rule input."""
    hypotheses = reconstruction['hypotheses']
    counts = [len(h['sites']) for h in hypotheses if 'sites' in h]
    supported = [len(h['sites']) for h in hypotheses if h['status'] == 'conditional_fit']
    return {'saved_hypothesis_site_counts': counts,
        'saved_conditional_fit_site_counts': supported,
        'saved_candidate_site_counts': [len(c['order']) for c in reconstruction['candidates']],
        'has_saved_1or2_site_hypothesis': any(n in (1, 2) for n in counts),
        'has_saved_1or2_site_conditional_fit': any(n in (1, 2) for n in supported),
        'conditional_imaging_candidates': use['conditional_candidate_count'],
        'spectroscopy_accepted': use['spectroscopy']['accepted'],
        'category': use['category'], 'native_status': native_status}


def tally(rows):
    result = defaultdict(Counter)
    primaries = defaultdict(set)
    for row in rows:
        split = row['frozen_split']
        labels = ['all', row['decision']]
        if split:
            labels += ['frozen_'+split, 'frozen_'+split+':'+row['decision']]
        for label in labels:
            c = result[label]
            c['groups'] += 1
            c['positive_rows'] += row['positive_rows']
            c['spectroscopy_accepted'] += bool(row['spectroscopy_accepted'])
            c['conditional_imaging_groups'] += bool(row['conditional_imaging_candidates'])
            c['conditional_imaging_candidates'] += row['conditional_imaging_candidates']
            c['has_saved_1or2_site_hypothesis'] += row['has_saved_1or2_site_hypothesis']
            c['has_saved_1or2_site_conditional_fit'] += row['has_saved_1or2_site_conditional_fit']
            c['native_failed'] += row['native_status'] == 'native_failed'
            c['category:'+row['category']] += 1
            c['complete_anchor_count:'+str(row['complete_anchor_count'])] += 1
            c.update({'unknown_rows:'+k: v for k, v in row['unknown_reasons'].items()})
            ident = row['original_identity']
            primaries[label].add((ident['chunk_index'], ident['raw_primary_id']))
    for label in result:
        result[label]['distinct_initial_primaries'] = len(primaries[label])
    return {k: dict(v) for k, v in result.items()}


def run(campaign, signal_use, reconstruction, split_manifest, output, max_seconds=300):
    started = time.perf_counter()
    if not 0 < max_seconds <= 300:
        raise ValueError('This saved scan is bounded to at most300seconds')
    campaign, signal_use, reconstruction, split_manifest, output = map(Path,
        (campaign, signal_use, reconstruction, split_manifest, output))
    if output.exists():
        raise ValueError('Preserve existing studies; use a new output directory')
    complete, chunks = S.sealed_chunks(campaign)
    use_complete, use_summary = S.read(signal_use/'COMPLETE.json'), S.read(signal_use/'summary.json')
    reco_complete, reco_summary = S.read(reconstruction/'COMPLETE.json'), S.read(reconstruction/'summary.json')
    for root, receipt, summary in ((signal_use, use_complete, use_summary), (reconstruction, reco_complete, reco_summary)):
        if (receipt['summary_sha256'] != S.sha(root/'summary.json') or
                receipt['identity_sha256'] != S.sha(root/'identity.json') or
                summary['campaign_complete_sha256'] != S.sha(campaign/'COMPLETE.json')):
            raise ValueError('Saved derivative completion binding differs')
    if use_summary['reconstruction_complete_sha256'] != S.sha(reconstruction/'COMPLETE.json'):
        raise ValueError('Saved uses refer to another reconstruction')
    split = S.read(split_manifest)
    if split['reconstruction_complete_sha256'] != S.sha(reconstruction/'COMPLETE.json'):
        raise ValueError('Frozen evaluation split refers to another reconstruction')
    assignments = {r['campaign_initial_id']: r['split'] for r in split['assignments']}
    frozen_groups = {tuple(r['group_key']): r for r in split['groups']}
    sources = {name: S.sha(S.ROOT/name) for name in SOURCES}
    identity = {'kind': KIND, 'predicate_frozen_before_scan': PREDICATE,
        'source_sha256': sources, 'campaign_complete_sha256': S.sha(campaign/'COMPLETE.json'),
        'signal_use_complete_sha256': S.sha(signal_use/'COMPLETE.json'),
        'reconstruction_complete_sha256': S.sha(reconstruction/'COMPLETE.json'),
        'split_manifest_sha256': S.sha(split_manifest), 'max_seconds': max_seconds,
        'working_root': str(S.ROOT), 'model': 'gpt-6.1-sol', 'reasoning_effort': 'ultra',
        'model_effort_evidence': 'Assigned worker session context; not external runtime attestation',
        'production_selection_changed': False,
        'new_science_calls': {'transport': 0, 'native_drift': 0, 'field_solve': 0, 'calibration': 0, 'waveform_fit': 0}}
    output.mkdir(parents=True)
    (output/'chunks').mkdir()
    S.write(output/'identity.json', identity)
    uses = {r['chunk_index']: r for r in use_complete['chunks']}
    recos = {r['chunk_index']: r for r in reco_complete['chunks']}
    all_rows, inventory = [], []

    def budget():
        if time.perf_counter()-started > max_seconds:
            raise TimeoutError('Bounded saved-data scan reached its time limit; sealed chunks retained')

    try:
        for index, seal, done in chunks:
            budget()
            base = seal.parent
            transport = base/'transport/stream/events.jsonl.gz'
            manifest_path = base/'transport/stream/manifest.json'
            use_path = signal_use/'chunks'/f'{index:03d}.jsonl.gz'
            reco_path = reconstruction/'chunks'/f'{index:03d}.jsonl.gz'
            receipt_path = reconstruction/'chunks'/f'{index:03d}.json'
            pins = {'transport': done['artifacts']['transport/stream/events.jsonl.gz']['sha256'],
                'manifest': done['artifacts']['transport/stream/manifest.json']['sha256'],
                'signal_use': uses[index]['sha256'], 'reconstruction': recos[index]['data_sha256'],
                'reconstruction_receipt': recos[index]['receipt_sha256']}
            for name, path in (('transport', transport), ('manifest', manifest_path),
                    ('signal_use', use_path), ('reconstruction', reco_path), ('reconstruction_receipt', receipt_path)):
                if S.sha(path) != pins[name]:
                    raise ValueError('Bound transport or saved derivative chunk changed')
            if S.read(receipt_path)['input_store_sha256'] != done['artifacts']['events.sqlite']['sha256']:
                raise ValueError('Saved reconstruction original-store binding differs')
            manifest = S.read(manifest_path)
            saved = {}
            with gzip.open(use_path, 'rt', encoding='utf-8') as f:
                for line in f:
                    row = json.loads(line); i = row['original_identity']
                    saved[i['raw_primary_id'], i['pulse_group_id']] = row
            with gzip.open(reco_path, 'rt', encoding='utf-8') as f:
                for line in f:
                    row = json.loads(line); i = row['original_identity']
                    target = saved[i['raw_primary_id'], i['pulse_group_id']]
                    if i != target['original_identity']:
                        raise ValueError('Saved uses and hypothesis identity differ')
                    target['comparison'] = comparison(row['reconstruction'], target['signal_use'], row['native_status'])
                    if len(row['reconstruction']['candidates']) != target['signal_use']['conditional_candidate_count']:
                        raise ValueError('Saved candidate census differs')
            context = {k: done['identity'][k] for k in ('source_group', 'chunk_index', 'campaign_initial_offset')}
            rows = []
            with gzip.open(transport, 'rt', encoding='utf-8') as f:
                for line in f:
                    budget()
                    event = json.loads(line)
                    for group in C.pulse_groups(event, manifest['source_id'], context):
                        key = event['event_id'], group['group_id']
                        saved_row = saved.pop(key); original = saved_row['original_identity']
                        if (original['chunk_index'] != index or original['source_group'] != context['source_group'] or
                                original['campaign_initial_id'] != context['campaign_initial_offset']+key[0]):
                            raise ValueError('Transport and saved group identity differ')
                        frozen = frozen_groups.get((index, *key))
                        if frozen and frozen['metadata_sha256'] != original['metadata_sha256']:
                            raise ValueError('Frozen evaluation group identity differs')
                        rows.append({'original_identity': original, **classify(group, event),
                            'positive_rows': len(group['steps']), **saved_row['comparison'],
                            'frozen_split': assignments.get(original['campaign_initial_id'])})
            if saved or len(rows) != uses[index]['counts']['pulse_groups']:
                raise ValueError('Transport and saved pulse-group census differs')
            destination = output/'chunks'/f'{index:03d}.jsonl.gz'
            pending = Path(str(destination)+'.pending')
            with gzip.open(pending, 'wb') as f:
                for row in rows:
                    f.write(S.encoded(row))
            os.replace(pending, destination)
            record = {'chunk_index': index, 'seed': manifest['seed'], 'input_sha256': pins,
                'groups': len(rows), 'decision_ledger_sha256': S.sha(destination)}
            S.write(output/'chunks'/f'{index:03d}.json', record)
            inventory.append(record); all_rows.extend(rows)
            S.write(output/'progress.json', {'status': 'running_saved_data_only', 'chunks': len(inventory),
                'groups': len(all_rows), 'elapsed_seconds': time.perf_counter()-started})
            if len(inventory) % 20 == 0:
                print(json.dumps({'chunks': len(inventory), 'groups': len(all_rows)}), flush=True)
        counts = tally(all_rows)
        expected = use_summary['counts']
        if (counts['all']['groups'] != expected['pulse_groups'] or
                counts['all']['spectroscopy_accepted'] != expected['spectroscopy_groups'] or
                counts['all']['conditional_imaging_groups'] != expected['conditional_candidate_groups'] or
                counts['all']['conditional_imaging_candidates'] != reco_summary['counts']['conditional_candidates'] or
                counts['frozen_development']['groups'] != 200 or counts['frozen_holdout']['groups'] != 200 or
                sources != {name: S.sha(S.ROOT/name) for name in SOURCES}):
            raise ValueError('Final group/comparator/split census or frozen source differs')
        result = {**identity, 'status': 'completed_saved_data_only', 'count_table': counts,
            'elapsed_seconds': time.perf_counter()-started,
            'denominators': {k: sum(v[k] for v in complete['groups'].values()) for k in
                ('initial_primaries', 'zero_deposit_primaries', 'nonzero_primaries', 'pulse_groups')},
            'chunk_inventory': inventory,
            'evaluation_scope': 'Fixed400development/holdout assignments are post-rule evaluation only; no thresholds tuned. Saved1/2-site hypotheses include model mismatches; conditional_fit is reported separately. Neither saved comparator nor ancestry is hardware truth.',
            'cost_scope': 'Screened positive rows proxy requested SSD deposit work avoided, not measured drift calls or walltime. Native failures may stop a group early; per-row costs differ.',
            'unknown_scope': 'Unknown/direct/ambiguous ancestry is retained. complete_anchor_count=null; known_anchor_count is only a lower bound. No unknown is counted as a complete1/2-site group.'}
        S.write(output/'result.json', result)
        S.write(output/'COMPLETE.json', {'kind': KIND, 'status': result['status'],
            'identity_sha256': S.sha(output/'identity.json'), 'result_sha256': S.sha(output/'result.json'),
            'chunk_inventory_sha256': hashlib.sha256(S.encoded(inventory)).hexdigest()})
        S.write(output/'progress.json', {'status': result['status'], 'chunks': len(inventory), 'groups': len(all_rows)})
        print(json.dumps({'output': str(output), 'elapsed_seconds': result['elapsed_seconds'],
            'result_sha256': S.sha(output/'result.json'), 'count_table': counts}), flush=True)
        return result
    except (TimeoutError, ValueError, KeyError) as error:
        S.write(output/'failure.json', {'status': 'incomplete_saved_scan', 'error': str(error),
            'chunks': len(inventory), 'groups': len(all_rows), 'elapsed_seconds': time.perf_counter()-started})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('campaign', 'signal-use', 'reconstruction', 'split-manifest', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--max-seconds', type=float, default=300)
    args = parser.parse_args()
    run(args.campaign, args.signal_use, args.reconstruction, args.split_manifest, args.output, args.max_seconds)
