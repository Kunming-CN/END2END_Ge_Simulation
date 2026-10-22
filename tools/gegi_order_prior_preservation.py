"""Migrate only priors of frozen saved hypotheses; no refitting or new cones."""
from __future__ import annotations
import argparse
from collections import Counter
import copy
import gzip
import json
import math
from pathlib import Path
import time

import gegi_recovery_validation as V

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ('tools/gegi_signal_reconstruction.py', 'tools/test_gegi_signal_reconstruction.py',
           'tools/gegi_order_prior_preservation.py', 'tools/gegi_recovery_validation.py')


def migrate(result):
    """Use complete saved sites/alternatives, retaining every existing candidate."""
    revised = copy.deepcopy(result)
    if not result['candidates']:
        return revised
    hypotheses = {h['hypothesis_index']: h for h in result['hypotheses']}
    if len(hypotheses) != len(result['hypotheses']):
        raise ValueError('Duplicate saved hypothesis index')
    rank_deficient = result['energy_bookkeeping']['rank_deficient_supports']
    alternatives = len(hypotheses) + int(rank_deficient > 0)
    valid_counts = Counter(c['hypothesis_index'] for c in result['candidates'])
    for candidate in revised['candidates']:
        index = candidate['hypothesis_index']
        hypothesis = hypotheses[index]
        sites = hypothesis['sites']
        if (hypothesis['status'] != 'conditional_fit' or not 2 <= len(sites) <= 4 or
                sorted(candidate['order']) != list(range(len(sites)))):
            raise ValueError('Saved candidate needs complete conditional sites and their full permutation')
        old = 1/(alternatives*valid_counts[index])
        if not all(math.isclose(candidate[k], old, rel_tol=0., abs_tol=1e-12)
                   for k in ('prior_weight', 'weight')):
            raise ValueError('Saved weights do not match the original valid-order prior')
        candidate['prior_weight'] = candidate['weight'] = 1/(alternatives*math.factorial(len(sites)))
    old_total = math.fsum(c['prior_weight'] for c in result['candidates'])
    if not math.isclose(old_total+result['unsupported_hypothesis_mass'], 1., rel_tol=0., abs_tol=1e-12):
        raise ValueError('Saved prior and unresolved mass do not sum to one')
    revised['unsupported_hypothesis_mass'] = max(0., 1-math.fsum(c['prior_weight'] for c in revised['candidates']))
    revised['candidate_weight_scope'] = 'Equal site-order priors before kinematic screening within equally weighted energy-flow alternatives; unsupported orders remain unresolved. Not calibrated posterior probabilities.'
    return revised


def compressed_rows(path, rows):
    with gzip.open(path, 'xb') as stream:
        for row in rows:
            stream.write(json.dumps(row, separators=(',', ':'), allow_nan=False).encode()+b'\n')


def summary(rows):
    return {'groups': len(rows), 'candidates': sum(r['candidate_count'] for r in rows),
            'changed_groups': sum(r['changed_candidates'] > 0 for r in rows),
            'changed_candidates': sum(r['changed_candidates'] for r in rows),
            'native_failed_groups': sum(r['native_status'] == 'native_failed' for r in rows),
            'native_noncomplete_groups': sum(r['native_status'] != 'completed' for r in rows),
            'old_candidate_prior_mass': math.fsum(r['old_prior_mass'] for r in rows),
            'new_candidate_prior_mass': math.fsum(r['new_prior_mass'] for r in rows),
            'known_unresolved_mass_groups': sum(r['old_unresolved_mass'] is not None for r in rows),
            'unknown_unresolved_mass_groups': sum(r['old_unresolved_mass'] is None for r in rows),
            'old_known_unresolved_mass': math.fsum(r['old_unresolved_mass'] for r in rows if r['old_unresolved_mass'] is not None),
            'new_known_unresolved_mass': math.fsum(r['new_unresolved_mass'] for r in rows if r['new_unresolved_mass'] is not None)}


def run(reconstruction, validation, selected_output, output, max_seconds=120):
    started = time.perf_counter()
    if not 0 < max_seconds <= 120:
        raise ValueError('Saved-prior migration is bounded to at most120seconds')
    reconstruction, validation, selected_output, output = map(Path, (reconstruction, validation, selected_output, output))
    inputs = {'reconstruction_complete': reconstruction/'COMPLETE.json',
              'split_manifest': validation/'split-manifest.json', 'selection_result': selected_output/'result.json',
              'selection_complete': selected_output/'COMPLETE.json', 'selection_records': selected_output/'selected-records.jsonl.gz'}
    pins = {name: V.sha(path) for name, path in inputs.items()}
    split, selected_result, selected_complete = map(V.read, (inputs['split_manifest'], inputs['selection_result'], inputs['selection_complete']))
    if (split['reconstruction_complete_sha256'] != pins['reconstruction_complete'] or
            selected_result['input_sha256']['reconstruction_complete'] != pins['reconstruction_complete'] or
            selected_result['input_sha256']['split_manifest'] != pins['split_manifest'] or
            selected_complete['result_sha256'] != pins['selection_result'] or
            selected_result['artifact_sha256']['selected-records.jsonl.gz'] != pins['selection_records']):
        raise ValueError('Frozen cohorts refer to different or changed saved inputs')
    V.check_disjoint(split['groups'])
    frozen = {tuple(g['group_key']): g for g in split['groups']}
    with gzip.open(inputs['selection_records'], 'rt', encoding='utf-8') as stream:
        selected = [json.loads(line) for line in stream]
    map_key = lambda r: (r['campaign_initial_id'], r['pulse_group_id'])
    chosen = {map_key(r): r for r in selected}
    if len(frozen) != 400 or len(chosen) != 153 or sum(len(r['candidates']) for r in selected) != 287:
        raise ValueError('Use the original frozen400 and153map groups/287map candidates')
    sources = {name: V.sha(ROOT/name) for name in SOURCES}
    output.mkdir(parents=True, exist_ok=False)
    identity = {'kind': 'gegi_order_prior_preservation_v1', 'source_sha256': sources, 'input_sha256': pins,
                'max_seconds': max_seconds, 'selection_or_fitting_truth_used': False,
                'scope': 'Only existing candidate weights change. Unsupported orders retain unresolved mass; no new cones, fits, raw metadata, source pose, calibration, maps or transport.'}
    V.write_new(output/'identity.json', identity)
    records, ledger, revised_map, seen_frozen, seen_map = [], [], [], set(), set()
    scanned = 0
    for record in V.records(reconstruction):
        scanned += 1
        if time.perf_counter()-started > max_seconds:
            raise TimeoutError('Saved-prior migration budget exceeded; no automatic retry')
        key = V.group_key(record); original = record['original_identity']; mkey = map_key(original)
        if key not in frozen and mkey not in chosen:
            continue
        if key in frozen:
            expected = frozen[key]
            if (key in seen_frozen or original['metadata_sha256'] != expected['metadata_sha256'] or
                    original['campaign_initial_id'] != expected['campaign_initial_id']):
                raise ValueError('Frozen group original identity changed')
            seen_frozen.add(key)
        if mkey in chosen:
            if mkey in seen_map:
                raise ValueError('Duplicate original map group')
            seen_map.add(mkey)
            old_map = chosen[mkey]
            old_two = [c for c in record['reconstruction']['candidates'] if len(c['order']) == 2]
            if old_map['energy_keV'] != record['reconstruction']['energy_keV'] or old_map['candidates'] != old_two:
                raise ValueError('Frozen map candidate content differs from the full saved hypotheses')
        old = record['reconstruction']; new = migrate(old)
        records.append({**record, 'reconstruction': new})
        ledger.append({'original_identity': original, 'split': frozen[key]['split'] if key in frozen else None,
                       'frozen_map_group': mkey in chosen, 'native_status': record['native_status'],
                       'candidate_count': len(old['candidates']),
                       'changed_candidates': sum(a['prior_weight'] != b['prior_weight'] for a,b in zip(old['candidates'], new['candidates'])),
                       'old_prior_mass': math.fsum(c['prior_weight'] for c in old['candidates']),
                       'new_prior_mass': math.fsum(c['prior_weight'] for c in new['candidates']),
                       'old_unresolved_mass': old.get('unsupported_hypothesis_mass'),
                       'new_unresolved_mass': new.get('unsupported_hypothesis_mass')})
        if mkey in chosen:
            revised_map.append({**chosen[mkey], 'candidates': [c for c in new['candidates'] if len(c['order']) == 2]})
    if seen_frozen != frozen.keys() or seen_map != chosen.keys():
        raise ValueError('A frozen original group is absent from the saved reconstruction')
    complete = V.read(inputs['reconstruction_complete']); saved_summary = V.read(reconstruction/'summary.json')
    if scanned != saved_summary['counts']['pulse_groups'] or V.sha(reconstruction/'identity.json') != complete['identity_sha256']:
        raise ValueError('Saved reconstruction group census or identity changed')
    for name, rows in (('groups.jsonl.gz', records), ('weight-ledger.jsonl.gz', ledger), ('map-records.jsonl.gz', revised_map)):
        compressed_rows(output/name, rows)
    if pins != {name: V.sha(path) for name, path in inputs.items()} or sources != {name: V.sha(ROOT/name) for name in SOURCES}:
        raise ValueError('Frozen inputs or migration source changed')
    result = {**identity, 'status': 'completed_saved_prior_migration', 'elapsed_seconds': time.perf_counter()-started,
              'saved_groups_scanned': scanned, 'distinct_target_groups': len(records),
              'original_initial_denominators': saved_summary['original_initial_denominators'],
              'frozen400': {s: summary([r for r in ledger if r['split'] == s]) for s in ('development', 'holdout')},
              'map153_full_hypotheses': summary([r for r in ledger if r['frozen_map_group']]),
              'map153_two_site_candidates': {'groups': len(revised_map), 'candidates': sum(len(r['candidates']) for r in revised_map),
                  'old_prior_mass': math.fsum(c['prior_weight'] for r in selected for c in r['candidates']),
                  'new_prior_mass': math.fsum(c['prior_weight'] for r in revised_map for c in r['candidates']),
                  'old_unresolved_mass': math.fsum(1-math.fsum(c['prior_weight'] for c in r['candidates']) for r in selected),
                  'new_unresolved_mass': math.fsum(1-math.fsum(c['prior_weight'] for c in r['candidates']) for r in revised_map)},
              'artifact_sha256': {name: V.sha(output/name) for name in ('groups.jsonl.gz', 'weight-ledger.jsonl.gz', 'map-records.jsonl.gz')}}
    V.write_new(output/'result.json', result)
    V.write_new(output/'COMPLETE.json', {'status': result['status'], 'result_sha256': V.sha(output/'result.json')})
    print(json.dumps({'elapsed_seconds': result['elapsed_seconds'], 'frozen400': result['frozen400'],
                      'map153_two_site_candidates': result['map153_two_site_candidates']}), flush=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('reconstruction', 'validation', 'selected-output', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--max-seconds', type=float, default=120)
    args = parser.parse_args()
    run(args.reconstruction, args.validation, args.selected_output, args.output, args.max_seconds)
