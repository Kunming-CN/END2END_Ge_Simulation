"""Resumable native-only replay of retained unavailable groups; no acquisition or trigger relabeling."""
from __future__ import annotations
import argparse
from collections import Counter
import json
import math
import os
from pathlib import Path
import sys
import time
import zipfile
import zlib

import gegi_campaign_response as response
import gegi_digital_readout as digital
import gegi_event_store as store
from gegi_missing_history import MissingHistory, native_support_ns
from gegi_native_failure_diagnostic import readonly
from gegi_resource_monitor import Monitor, available_memory

ROOT = response.ROOT
KIND = 'gegi_retained_native_recovery_v1'


def groups(source):
    """One decompressed group at a time, in its original absolute onset order."""
    with readonly(Path(source)/'compton-candidates.sqlite') as connection:
        query = '''SELECT f.ordinal, f.record FROM native_failures f
                   JOIN input_groups g USING(ordinal) ORDER BY g.onset_ns, f.ordinal'''
        for ordinal, blob in connection.execute(query):
            record = json.loads(zlib.decompress(blob))
            yield ordinal, record['group'], record['event']


def prepare(source, output, *, prior_recovery=None):
    source, output = Path(source).resolve(), Path(output).resolve()
    store.require(output.is_relative_to(ROOT/'.local') and not output.exists(), 'Use a new project-local recovery root')
    request = response.read(source/'native-request.json')
    request['response_mode'] = store.NATIVE_SIGNAL_ONLY
    request['event_id_policy'] = 'streaming_transport_driver_v1'
    request['numerics'].update(cached_drift_precision_bits=64, analytic_semiconductor_boundary=True)
    refs = set(request['source_sha256']) | {'simulation/native_boundary_guard.jl',
        'tools/gegi_native_failure_recovery.py', 'tools/gegi_missing_history.py',
        'tools/gegi_native_failure_diagnostic.py', 'tools/gegi_resource_monitor.py', 'tools/gegi_digital_readout.py'}
    request['source_sha256'] = {ref: response.file_sha(ROOT/ref) for ref in sorted(refs)}
    output.mkdir(parents=True)
    response.write(output/'native-request.json', request)
    with readonly(source/'compton-candidates.sqlite') as connection:
        count = connection.execute('SELECT count(*) FROM native_failures').fetchone()[0]
    identity = {'kind': KIND, 'source_ref': str(source.relative_to(ROOT)),
                'source_sha256': response.file_sha(source/'compton-candidates.sqlite'),
                'request_sha256': response.file_sha(output/'native-request.json'),
                'recovery_producer_sha256': response.file_sha(__file__), 'group_count': count}
    if prior_recovery is not None:
        prior = Path(prior_recovery).resolve()
        old = response.read(prior/'identity.json'); old_request = response.read(prior/'native-request.json')
        store.require(prior.is_relative_to(ROOT/'.local') and response.read(prior/'active-worker.json')['status'] == 'closed',
                      'Prior native recovery must be project-local and closed')
        store.require(old['source_sha256'] == identity['source_sha256'] and
                      all(old_request[key] == request[key] for key in ('field_cache', 'model_sha256', 'numerics')),
                      'Prior recovery inputs, field solution or configured drift differ')
        identity['prior_recovery'] = {'ref': str(prior.relative_to(ROOT)),
            'identity_sha256': response.file_sha(prior/'identity.json'),
            'store_sha256': response.file_sha(prior/'native.sqlite'),
            'ready_sha256': response.file_sha(prior/'native-ready.json'),
            'producer_archive_sha256': response.file_sha(prior/'producer-source.zip'),
            'request_sha256': old['request_sha256']}
    response.write(output/'identity.json', identity)
    with zipfile.ZipFile(output/'producer-source.zip', 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for ref in sorted(refs):
            archive.write(ROOT/ref, ref)
        archive.write(output/'native-request.json', 'native-request.json')
        archive.write(output/'identity.json', 'identity.json')
    return identity


def inherit_complete(prior, binding, group, native):
    """Copy exact complete native records with their actual prior producer binding."""
    digest = store.sha(store.encoded(group)); primary, gid = group['event_id'], group['group_id']
    if not prior.has(primary, gid, digest):
        return None
    saved, signals = prior.read(primary, gid, with_signals=True)
    if not digital.terminal_contacts_complete(saved):
        return None
    store.require(saved['input_group'] == group and signals is not None, 'Inherited native truth or signals changed')
    metadata_sha = prior.db.execute('SELECT metadata_sha256 FROM events WHERE primary_id=? AND group_id=?',
                                   (primary, gid)).fetchone()[0]
    saved['native_recovery_inherited'] = {**binding, 'event_metadata_sha256': metadata_sha,
        'policy': 'Exact terminal-complete prior native response; original producer retained, no new drift executed.'}
    native.append(primary, gid, saved, signals, digest)
    return response.verify_store_roundtrip(native, primary, gid, saved, signals, digest)


def conditional_history(source, native, live_ns, support):
    old, remaining = (MissingHistory(live_ns, native_support_ns=support) for _ in range(2))
    processed = recovered = 0
    for _, group, _ in groups(source):
        first = group['group_origin_time_ns']; last = max(step['time_ns'] for step in group['steps'])
        energy = math.fsum(step['energy_keV'] for step in group['steps'])
        old.add(first, last, energy)
        digest = store.sha(store.encoded(group))
        complete = False
        if native.has(group['event_id'], group['group_id'], digest):
            processed += 1
            complete = digital.terminal_contacts_complete(native.read(group['event_id'], group['group_id'])[0])
            recovered += complete
        if not complete:
            remaining.add(first, last, energy)
    return {'processed_groups': processed, 'recovered_complete_groups': recovered,
            'old_unavailable_union': old.statistics(), 'remaining_unknown_union': remaining.statistics(),
            'remaining_intervals_ns': remaining.intervals(),
            'scope': 'Conditional native availability only; original ADC stream, triggers and images are unchanged. '
                     'Unprocessed groups remain unknown. Original completed groups are not recomputed.'}


def run(output, *, stop_after_new=None):
    output = Path(output).resolve(); identity = response.read(output/'identity.json')
    source = ROOT/identity['source_ref']; request = output/'native-request.json'
    store.require(identity['recovery_producer_sha256'] == response.file_sha(__file__) and
                  identity['request_sha256'] == response.file_sha(request) and
                  identity['source_sha256'] == response.file_sha(source/'compton-candidates.sqlite'),
                  'Recovery producer, request or original retained inputs changed')
    path = output/'native.sqlite'
    native = store.Store(path, identity, create=not path.exists())
    completed = native.db.execute('SELECT body FROM completion WHERE singleton=1').fetchone()
    if completed:
        native.close()
        return json.loads(completed[0])
    worker = response.ResidentWorker(request, output/'native-spool')
    prior = None
    if identity.get('prior_recovery') is not None:
        binding = identity['prior_recovery']; prior_path = ROOT/binding['ref']
        store.require(response.file_sha(prior_path/'identity.json') == binding['identity_sha256'] and
                      response.file_sha(prior_path/'native.sqlite') == binding['store_sha256'] and
                      response.file_sha(prior_path/'native-ready.json') == binding['ready_sha256'],
                      'Prior native recovery binding changed')
        prior = store.Store(prior_path/'native.sqlite', response.read(prior_path/'identity.json'))
    resources = output/'resources.json'
    monitor = Monitor(output, response.read(resources) if resources.exists() else None)
    monitor.data['available_memory_before_worker_bytes'] = available_memory()
    response.write(resources, monitor.data)
    status, new_count, counts, transitions = 'running', 0, Counter(), Counter()
    started = time.perf_counter(); measured = []
    try:
        with monitor:
            ready = worker.start(); monitor.pids['native'] = worker.process.pid
            response.write(output/'native-ready.json', ready)
            response.write(output/'active-worker.json', {'status': 'running', 'python_pid': os.getpid(),
                           'native_pid': worker.process.pid, 'request_sha256': identity['request_sha256']})
            with (output/'recovery-ledger.jsonl').open('ab') as ledger:
                for ordinal, group, original in groups(source):
                    digest = store.sha(store.encoded(group))
                    existing = native.has(group['event_id'], group['group_id'], digest)
                    if not existing:
                        if (output/'stop.request').exists() or (stop_after_new is not None and new_count >= stop_after_new):
                            status = 'stopped'; break
                        begin = time.perf_counter()
                        saved = inherit_complete(prior, identity['prior_recovery'], group, native) if prior is not None else None
                        inherited = saved is not None
                        if not inherited:
                            saved = worker.process_group(group, native)
                        elapsed = time.perf_counter()-begin
                        if not inherited:
                            measured.append(elapsed); new_count += 1
                        # Store append and its exact array roundtrip already committed before this ledger.
                        ledger.write(store.encoded({'ordinal': ordinal, 'event_id': group['event_id'],
                            'group_id': group['group_id'], 'input_sha256': digest,
                            'original_status': original['status'], 'original_domain_error': original.get('native_domain_error'),
                            'new_status': saved['status'], 'new_domain_error': saved.get('native_domain_error'),
                            'complete': digital.terminal_contacts_complete(saved),
                            'elapsed_seconds': None if inherited else elapsed,
                            'timing_status': 'inherited_exact_prior_native' if inherited else 'measured',
                            'inheritance_verification_seconds': elapsed if inherited else None})+b'\n')
                        ledger.flush(); os.fsync(ledger.fileno())
                    else:
                        saved = native.read(group['event_id'], group['group_id'])[0]
                    counts[saved['status']] += 1; transitions[original['status']+' -> '+saved['status']] += 1
                    if new_count == 1 or new_count % 20 == 0:
                        monitor.sample()
                        response.write(resources, monitor.data)
                        response.write(output/'checkpoint.json', {'kind': KIND, 'status': 'running',
                            'processed_groups': sum(counts.values()), 'group_count': identity['group_count'],
                            'counts': dict(counts), 'transitions': dict(transitions),
                            'last_ordinal': ordinal, 'last_event_id': group['event_id'],
                            'new_native_seconds': math.fsum(measured), 'new_groups_this_activation': new_count})
                        print(f"Native recovery {sum(counts.values())}/{identity['group_count']}: {dict(counts)}", flush=True)
                else:
                    status = 'completed'
            worker.close()
    finally:
        worker.close()
        response.write(resources, monitor.data)
        response.write(output/'active-worker.json', {'status': 'closed', 'python_pid': os.getpid()})
        native.close()
        if prior is not None:
            prior.close()
    native = store.Store(path, identity)
    try:
        live = response.read(source/'candidate-acquisition.json')['live_time_ns']
        support = native_support_ns(response.read(request)['numerics'])
        history = conditional_history(source, native, live, support)
        result = {'kind': KIND, 'status': status, 'identity': identity, 'counts': dict(counts),
                  'transitions': dict(transitions), 'new_groups_this_activation': new_count,
                  'new_native_seconds': math.fsum(measured), 'activation_seconds': time.perf_counter()-started,
                  'conditional_history': history, 'resources': monitor.data,
                  'native_store_ref': str(path.relative_to(ROOT))}
        response.write(output/'checkpoint.json', result)
        if status == 'completed':
            store.require(sum(counts.values()) == identity['group_count'], 'Recovery group census does not close')
            native.seal(result)
            response.write(output/'recovery.json', result)
        print(json.dumps({'status': status, 'processed_groups': history['processed_groups'], 'counts': dict(counts)}), flush=True)
        return result
    finally:
        native.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--prior-recovery', type=Path)
    parser.add_argument('--stop-after-new', type=int)
    args = parser.parse_args()
    if args.prepare:
        if args.source is None:
            parser.error('--prepare requires the original --source run')
        prepare(args.source, args.output, prior_recovery=args.prior_recovery)
    else:
        if args.stop_after_new is not None and args.stop_after_new < 1:
            parser.error('Use a positive cooperative prefix size')
        run(args.output, stop_after_new=args.stop_after_new)


if __name__ == '__main__':
    main()
