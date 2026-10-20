"""Add signal-use records to completed reconstruction without repeating fits."""
from __future__ import annotations
import argparse
from collections import Counter
from contextlib import closing
import gzip
import hashlib
import itertools
import json
from pathlib import Path
import sqlite3
import time
import zlib

import gegi_saved_reconstruction as S
import gegi_signal_reconstruction as R
import gegi_signal_recovery as U

SOURCES = ('tools/gegi_saved_signal_use.py', 'tools/gegi_signal_recovery.py',
           'tools/gegi_imaging.py',
           'tools/gegi_signal_reconstruction.py', 'tools/gegi_saved_reconstruction.py')


def process(campaign, reconstruction, output):
    campaign, reconstruction, output = map(lambda p: Path(p).resolve(), (campaign, reconstruction, output))
    if output.exists() or any(output == p or output.is_relative_to(p) for p in (campaign, reconstruction)):
        raise ValueError('Use a new derivative outside the original campaign and reconstruction')
    complete, chunks = S.sealed_chunks(campaign)
    prior_complete = S.read(reconstruction/'COMPLETE.json')
    prior = S.read(reconstruction/'summary.json')
    if (prior_complete['summary_sha256'] != S.sha(reconstruction/'summary.json')
            or prior_complete['identity_sha256'] != S.sha(reconstruction/'identity.json')
            or prior['campaign_complete_sha256'] != S.sha(campaign/'COMPLETE.json')):
        raise ValueError('Original reconstruction completion binding changed')
    pins = {name: S.sha(S.ROOT/name) for name in SOURCES}
    identity = {'kind': U.KIND, 'source_sha256': pins,
        'campaign_complete_sha256': S.sha(campaign/'COMPLETE.json'),
        'reconstruction_complete_sha256': S.sha(reconstruction/'COMPLETE.json'),
        'reconstruction_summary_sha256': S.sha(reconstruction/'summary.json'),
        'new_radiation_calls': 0, 'new_native_calls': 0, 'new_field_calls': 0,
        'new_calibration_calls': 0, 'repeated_waveform_fits': 0}
    output.mkdir(parents=True); (output/'chunks').mkdir()
    (output/'source-bindings').mkdir()
    for name, digest in pins.items():
        body = (S.ROOT/name).read_bytes()
        if hashlib.sha256(body).hexdigest() != digest:
            raise ValueError('Source changed before export')
        (output/'source-bindings'/Path(name).name).write_bytes(body)
    S.write(output/'identity.json', identity)
    manifests = {row['chunk_index']: row for row in prior_complete['chunks']}
    started = time.perf_counter(); counts = Counter(); categories = Counter(); reasons = {}; inventory = []
    for index, seal, done in chunks:
        source = reconstruction/'chunks'/f'{index:03d}.jsonl.gz'
        receipt = reconstruction/'chunks'/f'{index:03d}.json'
        binding = manifests[index]; old_receipt = S.read(receipt)
        if (S.sha(source) != binding['data_sha256'] or S.sha(receipt) != binding['receipt_sha256']
                or old_receipt['input_store_sha256'] != done['artifacts']['events.sqlite']['sha256']):
            raise ValueError('Saved candidate chunk or original store binding changed')
        database = seal.parent/'events.sqlite'; before = database.stat()
        if S.sha(database) != old_receipt['input_store_sha256']:
            raise ValueError('Original saved scalar store changed')
        destination = output/'chunks'/f'{index:03d}.jsonl.gz'
        chunk_counts = Counter()
        with closing(sqlite3.connect(database.as_uri()+'?mode=ro', uri=True)) as db, \
                gzip.open(source, 'rt', encoding='utf-8') as saved, gzip.open(destination, 'wb') as target:
            db.execute('PRAGMA query_only=ON')
            rows = db.execute('SELECT primary_id,group_id,metadata,metadata_sha256 FROM events ORDER BY primary_id,group_id')
            for row, line in itertools.zip_longest(rows, saved):
                if row is None or line is None:
                    raise ValueError('Saved reconstruction and original event census differ')
                pid, gid, blob, digest = row; body = zlib.decompress(blob)
                if hashlib.sha256(body).hexdigest() != digest:
                    raise ValueError('Original metadata checksum changed')
                event, previous = json.loads(body), json.loads(line); original = previous['original_identity']
                if (original['metadata_sha256'] != digest or original['raw_primary_id'] != pid
                        or original['pulse_group_id'] != gid
                        or original['campaign_initial_id'] != event['campaign_initial_offset']+pid):
                    raise ValueError('Saved reconstruction event identity differs')
                observed = R.observables(event, None, done['response']['readout_recipe']['channels'])
                result = U.classify_observables(observed, previous['reconstruction'])
                if U.I.readout_summary(observed) != event['readout_summary']:
                    raise ValueError('Fixed-gain spectroscopy changed from original readout')
                target.write(S.encoded({'original_identity': original, 'signal_use': result}))
                categories[result['category']] += 1; chunk_counts['pulse_groups'] += 1
                chunk_counts['spectroscopy_groups'] += result['spectroscopy']['accepted']
                chunk_counts['spectroscopy_face_compatible_groups'] += result['spectroscopy'].get('face_compatible', False)
                chunk_counts['conditional_candidate_groups'] += bool(result['conditional_candidate_count'])
                chunk_counts['guard_collection_groups'] += bool(result['guard']['collecting_ids'])
                chunk_counts['guard_transient_groups'] += bool(result['guard']['transient_ids'])
                chunk_counts['adjacent_strip_groups'] += bool(result['adjacent_strip_pairs'])
                chunk_counts['native_failed_groups'] += event['status']=='native_failed'
                reason = previous['reconstruction']['reason']
                reasons.setdefault(reason, Counter())[result['category']] += 1
            after = database.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ValueError('Original saved store changed during processing')
        counts.update(chunk_counts)
        inventory.append({'chunk_index': index, 'sha256': S.sha(destination), 'counts': dict(chunk_counts)})
        print(json.dumps({'chunks': len(inventory), 'groups': counts['pulse_groups']}), flush=True)
    if (counts['pulse_groups'] != prior['counts']['pulse_groups']
            or counts['conditional_candidate_groups'] != prior['counts']['conditional_candidate_groups']
            or pins != {name: S.sha(S.ROOT/name) for name in SOURCES}):
        raise ValueError('Group census, unchanged candidate count or source identity changed')
    summary = {**identity, 'status': 'completed_signal_use_classification', 'counts': dict(counts),
        'categories': dict(categories), 'by_previous_reason': {k: dict(v) for k, v in reasons.items()},
        'original_initial_denominators': complete['groups'], 'new_validated_imaging_recoveries': 0,
        'new_energy_reconstructions': 0, 'spectroscopy_matches_original_readout': True,
        'elapsed_seconds': time.perf_counter()-started,
        'scope': 'Existing spectroscopy retained; ambiguous topology remains unresolved; no new cones or refits'}
    S.write(output/'summary.json', summary)
    S.write(output/'COMPLETE.json', {'kind': U.KIND, 'status': summary['status'], 'chunks': inventory,
        'summary_sha256': S.sha(output/'summary.json'), 'identity_sha256': S.sha(output/'identity.json')})
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('campaign', 'reconstruction', 'output'):
        parser.add_argument('--'+key, required=True)
    args = parser.parse_args(); process(args.campaign, args.reconstruction, args.output)
