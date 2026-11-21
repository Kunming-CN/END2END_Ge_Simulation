"""Resumable native-only replay of retained unavailable groups; no acquisition or trigger relabeling."""
from __future__ import annotations
import argparse
from collections import Counter
from contextlib import closing
import json
import math
import os
from pathlib import Path
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
PARENT_FILES = ('identity.json', 'native-request.json', 'native-ready.json', 'native.sqlite',
                'recovery.json', 'recovery-status-summary.json', 'recovery-status.jsonl', 'producer-source.zip')


def groups(source):
    """One decompressed group at a time, in its original absolute onset order."""
    with closing(readonly(Path(source)/'compton-candidates.sqlite')) as connection:
        query = '''SELECT f.ordinal, f.record FROM native_failures f
                   JOIN input_groups g USING(ordinal) ORDER BY g.onset_ns, f.ordinal'''
        for ordinal, blob in connection.execute(query):
            record = json.loads(zlib.decompress(blob))
            yield ordinal, record['group'], record['event']


def prepare(source, output, *, prior_recovery=None):
    source = Path(source).resolve()
    request = response.read(source/'native-request.json')
    request['response_mode'] = store.NATIVE_SIGNAL_ONLY
    request['event_id_policy'] = 'streaming_transport_driver_v1'
    request['numerics'].update(cached_drift_precision_bits=64, analytic_semiconductor_boundary=True)
    return _prepare(source, output, request, prior_recovery=prior_recovery)


def _prepare(source, output, request, *, prior_recovery=None, extension=None):
    output = Path(output).resolve()
    store.require(output.is_relative_to(ROOT/'.local') and not output.exists(), 'Use a new project-local recovery root')
    refs = set(request['source_sha256']) | {'simulation/native_boundary_guard.jl', 'simulation/native_segment_crossing.jl',
        'tools/gegi_native_failure_recovery.py', 'tools/gegi_missing_history.py',
        'tools/gegi_native_failure_diagnostic.py', 'tools/gegi_resource_monitor.py', 'tools/gegi_digital_readout.py'}
    request['source_sha256'] = {ref: response.file_sha(ROOT/ref) for ref in sorted(refs)}
    with closing(readonly(source/'compton-candidates.sqlite')) as connection:
        count = connection.execute('SELECT count(*) FROM native_failures').fetchone()[0]
    identity = {'kind': KIND, 'source_ref': str(source.relative_to(ROOT)),
                'source_sha256': response.file_sha(source/'compton-candidates.sqlite'),
                'recovery_producer_sha256': response.file_sha(__file__), 'group_count': count}
    if extension is not None:
        store.require(count == extension['original_groups'] and identity['source_sha256'] == extension['source_sha256'],
                      'The extension must preserve the parent original census and candidate archive')
        identity['cap_extension'] = extension
    if prior_recovery is not None:
        prior = Path(prior_recovery).resolve()
        old = response.read(prior/'identity.json'); old_request = response.read(prior/'native-request.json')
        store.require(prior.is_relative_to(ROOT/'.local') and response.read(prior/'active-worker.json')['status'] == 'closed',
                      'Prior native recovery must be project-local and closed')
        store.require(old['source_sha256'] == identity['source_sha256'] and
                      all(old_request[key] == request[key] for key in ('field_cache', 'model_sha256', 'numerics')),
                      'Prior recovery inputs, field solution or configured drift differ')
        if extension is not None:
            old_extension = old.get('cap_extension', {})
            receipt = response.read(prior/'recovery.json')
            ready = response.read(prior/'native-ready.json')
            with closing(readonly(prior/'native.sqlite')) as db:
                sealed = db.execute('SELECT body FROM completion WHERE singleton=1').fetchone()
            store.require(old_request == request and old_extension.get('parent') == extension['parent']
                          and receipt['status'] == 'completed' and receipt['identity'] == old
                          and sealed is not None and json.loads(sealed[0]) == receipt
                          and ready['request_sha256'] == old['request_sha256'] == response.file_sha(prior/'native-request.json')
                          and ready_support(ready, old_request) == extension['requested_native_support_ns']
                          and set(old_extension['selected_ordinals']) <= set(extension['selected_ordinals']),
                          'The prior pilot must be sealed under the same parent and extended response')
        identity['prior_recovery'] = {'ref': str(prior.relative_to(ROOT)),
            'identity_sha256': response.file_sha(prior/'identity.json'),
            'store_sha256': response.file_sha(prior/'native.sqlite'),
            'ready_sha256': response.file_sha(prior/'native-ready.json'),
            'producer_archive_sha256': response.file_sha(prior/'producer-source.zip'),
            'request_sha256': old['request_sha256']}
    output.mkdir(parents=True)
    response.write(output/'native-request.json', request)
    identity['request_sha256'] = response.file_sha(output/'native-request.json')
    response.write(output/'identity.json', identity)
    with zipfile.ZipFile(output/'producer-source.zip', 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for ref in sorted(refs):
            archive.write(ROOT/ref, ref)
        archive.write(output/'native-request.json', 'native-request.json')
        archive.write(output/'identity.json', 'identity.json')
    return identity


def ready_support(ready, request):
    dt, steps = ready['drift_dt_ns'], ready['drift_numerics']['max_steps']
    support = dt*steps
    store.require(type(steps) is int and steps > 0 and dt == request['numerics']['drift_dt_ns']
                  and support == native_support_ns(request['numerics'])
                  and ready['field_cache_sha256'] == request['field_cache']['sha256']
                  and ready['model_sha256'] == request['model_sha256'],
                  'Effective native field, model or configured drift support differs from the request')
    return support


def sealed_parent(path, expected=None):
    path = Path(path).resolve()
    store.require(path.is_relative_to(ROOT/'.local') and response.read(path/'active-worker.json')['status'] == 'closed',
                  'Use a closed project-local full recovery as the cap-extension parent')
    binding = {'ref': str(path.relative_to(ROOT)), 'sha256': {name: response.file_sha(path/name) for name in PARENT_FILES}}
    store.require(expected is None or expected == binding, 'The sealed cap-extension parent changed')
    identity, request, ready, receipt, summary = (response.read(path/name) for name in
        ('identity.json', 'native-request.json', 'native-ready.json', 'recovery.json', 'recovery-status-summary.json'))
    store.require(identity['kind'] == KIND and 'cap_extension' not in identity and receipt['status'] == 'completed'
                  and receipt['identity'] == identity and summary['groups'] == identity['group_count']
                  and summary['counts'] == receipt['counts']
                  and summary['status_ledger_sha256'] == binding['sha256']['recovery-status.jsonl']
                  and ready['request_sha256'] == identity['request_sha256'] == binding['sha256']['native-request.json'],
                  'The full parent phase, request and reconciled status evidence do not bind')
    with (path/'recovery-status.jsonl').open(encoding='utf-8') as stream:
        rows = [json.loads(line) for line in stream]
    by_id = {(row['event_id'], row['group_id']): row for row in rows}
    with closing(readonly(path/'native.sqlite')) as db:
        saved_identity = db.execute('SELECT body FROM identity WHERE singleton=1').fetchone()
        completion = db.execute('SELECT body FROM completion WHERE singleton=1').fetchone()
        seen = {}
        for event, group, digest, packed, expected_metadata in db.execute(
                'SELECT primary_id,group_id,input_sha256,metadata,metadata_sha256 FROM events'):
            body = zlib.decompress(packed)
            store.require(store.sha(body) == expected_metadata, 'Sealed parent native metadata changed')
            result = json.loads(body)
            seen[event, group] = digest, result['status'], digital.terminal_contacts_complete(result)
    store.require(saved_identity is not None and json.loads(saved_identity[0]) == {'kind': store.KIND, 'identity': identity}
                  and completion is not None and json.loads(completion[0]) == receipt
                  and len(by_id) == len(rows) == identity['group_count']
                  and len({row['ordinal'] for row in rows}) == len(rows)
                  and seen == {key: (row['input_sha256'], row['new_status'], row['complete']) for key, row in by_id.items()}
                  and Counter(row['new_status'] for row in rows) == receipt['counts']
                  and all(row['complete'] == (row['new_status'] == 'completed') for row in rows),
                  'The immutable native store and original group identities do not close')
    return binding, identity, request, ready_support(ready, request), receipt, by_id


def prepare_extension(parent, output, drift_cap_ns, *, event_ids=None, prior_recovery=None):
    binding, old_identity, request, old_support, _, rows = sealed_parent(parent)
    request['numerics']['drift_cap_ns'] = drift_cap_ns
    new_support = native_support_ns(request['numerics'])
    store.require(new_support > old_support, 'The requested cap must extend native signal support')
    eligible = [row for row in rows.values() if row['new_status'] == 'step_limit']
    chosen = eligible
    if event_ids is not None:
        requested = set(event_ids)
        store.require(requested and all(type(event) is int and event >= 0 for event in requested)
                      and requested <= {row['event_id'] for row in eligible},
                      'Each selected original event must have a sealed step-limit group')
        chosen = [row for row in eligible if row['event_id'] in requested]
    store.require(bool(chosen), 'The selected parent has no eligible step-limit groups')
    source = ROOT/old_identity['source_ref']
    extension = {'parent': binding, 'source_sha256': old_identity['source_sha256'],
                 'acquisition_sha256': response.file_sha(source/'candidate-acquisition.json'),
                 'original_groups': old_identity['group_count'], 'selected_ordinals': [row['ordinal'] for row in chosen],
                 'eligible_step_limit_groups': len(eligible), 'parent_native_support_ns': old_support,
                 'requested_native_support_ns': new_support}
    return _prepare(source, output, request, prior_recovery=prior_recovery, extension=extension)


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


def mask_overlap(before, after):
    """Report common and exclusive durations for two sample-aligned unions."""
    i = j = 0
    common = []
    while i < len(before) and j < len(after):
        first, last = before[i], after[j]
        common.append(max(0., min(first[1], last[1])-max(first[0], last[0])))
        if first[1] <= last[1]:
            i += 1
        else:
            j += 1
    shared = math.fsum(common)
    old, new = (math.fsum(end-start for start, end in intervals) for intervals in (before, after))
    return dict(overlap_ns=shared, before_only_ns=old-shared, after_only_ns=new-shared, union_ns=old+new-shared)


def extension_history(source_rows, native, acquisition, parent, parent_rows, selected, old_support, new_support):
    """Recompute one joint bound with each unavailable group's actual phase support."""
    live = acquisition['live_time_ns']
    remaining = MissingHistory(live, native_support_ns=old_support)
    effective, deferred, sources, selected_outcomes = Counter(), Counter(), Counter(), Counter()
    accounted = 0
    for ordinal, group, _ in source_rows:
        key = group['event_id'], group['group_id']
        digest = store.sha(store.encoded(group))
        old = parent_rows[key]
        store.require((ordinal, digest) == (old['ordinal'], old['input_sha256']), 'Original cap-extension input differs')
        status, complete, support = old['new_status'], old['complete'], old_support
        current = ordinal in selected and native.has(*key, digest)
        if current:
            saved, _ = native.read(*key)
            status, complete, support = saved['status'], digital.terminal_contacts_complete(saved), new_support
            store.require(complete == (status == 'completed'), 'Extended completion lacks terminal charge collection')
            selected_outcomes[status] += 1
            sources['selected_extended'] += 1
        elif complete:
            sources['retained_parent_complete'] += 1
        else:
            deferred[status] += 1
            sources['selected_not_processed' if ordinal in selected else 'unselected_parent_unavailable'] += 1
        effective[status] += 1
        if not complete:
            # MissingHistory stores absolute horizons. Set the support before each
            # admission so concurrent tails are summed with their own horizons.
            remaining.native_support_ns = float(support)
            remaining.add(group['group_origin_time_ns'], max(step['time_ns'] for step in group['steps']),
                          math.fsum(step['energy_keV'] for step in group['steps']))
        accounted += 1
    store.require(accounted == len(parent_rows) and remaining.statistics()['failure_count'] == accounted-effective['completed'],
                  'The extended and deferred whole-acquisition census does not close')
    history = parent['conditional_history']
    original, previous = acquisition['excluded_intervals_ns'], history['remaining_intervals_ns']
    original_union = history['old_unavailable_union']
    store.require(math.fsum(end-start for start, end in original) == original_union['excluded_time_ns']
                  and len(original) == original_union['merged_excluded_intervals'],
                  'Original acquisition mask differs from the sealed parent original union')
    current = remaining.intervals()
    return dict(original_groups=accounted, selected_groups=len(selected), processed_selected_groups=sum(selected_outcomes.values()),
                effective_counts=dict(effective), deferred_unavailable_counts=dict(deferred), provenance_counts=dict(sources),
                selected_outcomes=dict(selected_outcomes), old_unavailable_union=original_union,
                parent_remaining_unknown_union=history['remaining_unknown_union'], remaining_unknown_union=remaining.statistics(),
                remaining_intervals_ns=current, original_mask_comparison=mask_overlap(original, current),
                parent_mask_comparison=mask_overlap(previous, current), parent_native_support_ns=old_support, extended_native_support_ns=new_support,
                scope='Conditional native availability for the original recording, preserving deferred groups at parent support. '
                      'A continuous ADC and trigger replay is required to measure recovery at readout.')


def run(output, *, stop_after_new=None):
    output = Path(output).resolve(); identity = response.read(output/'identity.json')
    source = ROOT/identity['source_ref']; request = output/'native-request.json'
    store.require(identity['recovery_producer_sha256'] == response.file_sha(__file__) and
                  identity['request_sha256'] == response.file_sha(request) and
                  identity['source_sha256'] == response.file_sha(source/'compton-candidates.sqlite'),
                  'Recovery producer, request or original retained inputs changed')
    extension = identity.get('cap_extension')
    selected = set(extension['selected_ordinals']) if extension is not None else None
    selected_count = len(selected) if selected is not None else identity['group_count']
    request_value = response.read(request)
    if extension is not None:
        _, parent_identity, parent_request, old_support, parent, parent_rows = sealed_parent(
            ROOT/extension['parent']['ref'], extension['parent'])
        comparable = {**request_value, 'source_sha256': parent_request['source_sha256'],
                      'numerics': {**request_value['numerics'], 'drift_cap_ns': parent_request['numerics']['drift_cap_ns']}}
        eligible = {row['ordinal'] for row in parent_rows.values() if row['new_status'] == 'step_limit'}
        store.require(comparable == parent_request and parent_identity['source_sha256'] == identity['source_sha256']
                      and extension['acquisition_sha256'] == response.file_sha(source/'candidate-acquisition.json')
                      and extension['original_groups'] == identity['group_count'] == len(parent_rows)
                      and old_support == extension['parent_native_support_ns']
                      and native_support_ns(request_value['numerics']) == extension['requested_native_support_ns'] > old_support
                      and bool(selected) and selected <= eligible and len(eligible) == extension['eligible_step_limit_groups']
                      and selected_count == len(extension['selected_ordinals']), 'The cap-only continuation identity changed')
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
            if extension is not None:
                new_support = ready_support(ready, request_value)
            response.write(output/'native-ready.json', ready)
            response.write(output/'active-worker.json', {'status': 'running', 'python_pid': os.getpid(),
                           'native_pid': worker.process.pid, 'request_sha256': identity['request_sha256']})
            with (output/'recovery-ledger.jsonl').open('ab') as ledger:
                for ordinal, group, original in groups(source):
                    if selected is not None and ordinal not in selected:
                        continue
                    digest = store.sha(store.encoded(group))
                    old_status = original['status']
                    if extension is not None:
                        old = parent_rows[(group['event_id'], group['group_id'])]
                        store.require((old['ordinal'], old['input_sha256'], old['new_status']) == (ordinal, digest, 'step_limit'),
                                      'Selected group differs from its sealed step-limit history')
                        old_status = old['new_status']
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
                            'inheritance_verification_seconds': elapsed if inherited else None,
                            **({'parent_status': old_status} if extension is not None else {})})+b'\n')
                        ledger.flush(); os.fsync(ledger.fileno())
                    else:
                        saved = native.read(group['event_id'], group['group_id'])[0]
                    counts[saved['status']] += 1; transitions[old_status+' -> '+saved['status']] += 1
                    if new_count == 1 or new_count % 20 == 0:
                        monitor.sample()
                        response.write(resources, monitor.data)
                        response.write(output/'checkpoint.json', {'kind': KIND, 'status': 'running',
                            'processed_groups': sum(counts.values()), 'group_count': identity['group_count'],
                            'counts': dict(counts), 'transitions': dict(transitions),
                            'last_ordinal': ordinal, 'last_event_id': group['event_id'],
                            'new_native_seconds': math.fsum(measured), 'new_groups_this_activation': new_count,
                            **({'selected_group_count': selected_count} if extension is not None else {})})
                        print(f"Native recovery {sum(counts.values())}/{selected_count}: {dict(counts)}", flush=True)
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
        acquisition = response.read(source/'candidate-acquisition.json')
        if extension is None:
            history = conditional_history(source, native, acquisition['live_time_ns'], native_support_ns(request_value['numerics']))
            processed = history['processed_groups']
        else:
            history = extension_history(groups(source), native, acquisition, parent, parent_rows, selected, old_support, new_support)
            processed = history['processed_selected_groups']
            store.require(dict(counts) == history['selected_outcomes']
                          and native.db.execute('SELECT count(*) FROM events').fetchone()[0] == processed,
                          'Cap-extension store contains missing or unselected groups')
        result = {'kind': KIND, 'status': status, 'identity': identity, 'counts': dict(counts),
                  'transitions': dict(transitions), 'new_groups_this_activation': new_count,
                  'new_native_seconds': math.fsum(measured), 'activation_seconds': time.perf_counter()-started,
                  'conditional_history': history, 'resources': monitor.data,
                  'native_store_ref': str(path.relative_to(ROOT))}
        response.write(output/'checkpoint.json', result)
        if status == 'completed':
            store.require(sum(counts.values()) == selected_count, 'Recovery group census does not close')
            native.seal(result)
            response.write(output/'recovery.json', result)
        print(json.dumps({'status': status, 'processed_groups': processed, 'counts': dict(counts)}), flush=True)
        return result
    finally:
        native.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--prior-recovery', type=Path)
    parser.add_argument('--extend-from', type=Path, help='Sealed full parent phase. Selects its original step-limit groups.')
    parser.add_argument('--drift-cap-ns', type=float, help='Explicit longer cap for the selected native responses.')
    parser.add_argument('--event-id', type=int, action='append', help='Limit extension preparation to these original event IDs.')
    parser.add_argument('--stop-after-new', type=int)
    args = parser.parse_args()
    if args.prepare:
        if args.extend_from is not None:
            if args.source is not None or args.drift_cap_ns is None:
                parser.error('--extend-from binds the original source and requires --drift-cap-ns')
            prepare_extension(args.extend_from, args.output, args.drift_cap_ns, event_ids=args.event_id,
                              prior_recovery=args.prior_recovery)
        else:
            if args.source is None or args.drift_cap_ns is not None or args.event_id is not None:
                parser.error('--prepare requires --source or an explicit cap extension')
            prepare(args.source, args.output, prior_recovery=args.prior_recovery)
    else:
        if args.extend_from is not None or args.drift_cap_ns is not None or args.event_id is not None:
            parser.error('Set cap-extension options when preparing its new output')
        if args.stop_after_new is not None and args.stop_after_new < 1:
            parser.error('Use a positive cooperative prefix size')
        run(args.output, stop_after_new=args.stop_after_new)


if __name__ == '__main__':
    main()
