"""Resume only retained floating-boundary failures, preserving the sealed cap layer."""
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

import gegi_native_failure_recovery as R

response, store, digital, ROOT = R.response, R.store, R.digital, R.ROOT
KIND = 'gegi_boundary_cause_recovery_v1'


def baseline(path, expected=None):
    path = Path(path).resolve()
    store.require(path.is_relative_to(ROOT/'.local'), 'Use a retained project-local baseline')
    binding = {'ref': str(path.relative_to(ROOT)), 'sha256': {n: response.file_sha(path/n) for n in R.PARENT_FILES}}
    store.require(expected is None or binding == expected, 'Sealed boundary baseline changed')
    identity, receipt, summary = (response.read(path/n) for n in ('identity.json', 'recovery.json', 'recovery-status-summary.json'))
    parent_binding = identity['cap_extension']['parent']
    _, parent_identity, request, support, _, parent_rows = R.sealed_parent(ROOT/parent_binding['ref'], parent_binding)
    with (path/'recovery-status.jsonl').open(encoding='utf-8') as stream:
        rows = [json.loads(line) for line in stream]
    by_id = {(r['event_id'], r['group_id']): r for r in rows}
    store.require(response.read(path/'active-worker.json')['status'] == 'closed' and receipt['status'] == 'completed'
                  and receipt['identity'] == identity and len(rows) == len(by_id) == identity['group_count']
                  and identity['source_sha256'] == parent_identity['source_sha256']
                  and summary['status_ledger_sha256'] == binding['sha256']['recovery-status.jsonl']
                  and dict(Counter(r['new_status'] for r in rows)) == summary['counts'] == receipt['conditional_history']['effective_counts'],
                  'Full cap baseline census or reconciled ledger differs')
    selected = set(identity['cap_extension']['selected_ordinals'])
    selected_support = R.ready_support(response.read(path/'native-ready.json'), response.read(path/'native-request.json'))
    with closing(store.Store(path/'native.sqlite', identity)) as native:
        seal = native.db.execute('SELECT body FROM completion WHERE singleton=1').fetchone()
        store.require(seal is not None and json.loads(seal[0]) == receipt
                      and native.db.execute('SELECT count(*) FROM events').fetchone()[0] == len(selected), 'Cap SQLite seal differs')
        for ordinal, group, _ in R.groups(ROOT/identity['source_ref']):
            key = group['event_id'], group['group_id']; digest = store.sha(store.encoded(group)); row = by_id[key]
            old = parent_rows[key]
            store.require((row['ordinal'], row['input_sha256']) == (ordinal, digest), 'Baseline original input changed')
            if ordinal in selected:
                store.require(native.has(*key, digest), 'Selected cap record missing')
                event = native.read(*key)[0]
                expected_state = event['status'], digital.terminal_contacts_complete(event), selected_support
            else:
                expected_state = old['new_status'], old['complete'], support
            store.require((row['new_status'], row['complete'], row['native_support_ns']) == expected_state,
                          'Baseline status, endpoint completion or actual support differs')
    return binding, identity, request, receipt, by_id


def selected_rows(rows):
    result = {row['ordinal'] for row in rows.values() if row['new_status'] == 'native_failed'
              and row['new_domain_error'] == 'Native floating-boundary projection failed'}
    store.require(result and len(result) == sum(row['new_status'] == 'native_failed' for row in rows.values()),
                  'Select the concrete retained floating-boundary failure class only')
    return result


def prepare(parent, accepted, output):
    binding, old_identity, request, _, rows = baseline(parent)
    selected = selected_rows(rows); output = Path(output).resolve(); accepted = Path(accepted).resolve()
    store.require(output.is_relative_to(ROOT/'.local') and not output.exists(), 'Use a new local boundary-recovery root')
    validation = response.read(accepted/'validation.json'); accepted_binding = response.read(accepted/'binding.json')
    store.require(accepted.is_relative_to(ROOT/'.local') and validation['worker_exit_code'] == 0
                  and validation['source_hashes_unchanged'] and validation['exact_success_controls'] == 20
                  and accepted_binding['request_1000_sha256'] == validation['request_1000_sha256'] == response.file_sha(accepted/'request-1000.json')
                  and accepted_binding['producer_archive_sha256'] == validation['producer_archive_sha256'] == response.file_sha(accepted/'producer-source.zip')
                  and validation['results_sha256'] == response.file_sha(accepted/'results.json')
                  and response.read(accepted/'active-worker.json')['status'] == 'completed',
                  'Use the closed whole-group boundary acceptance')
    old_request = response.read(accepted/'request-1000.json')
    store.require(all(old_request[k] == request[k] for k in ('numerics', 'model_sha256', 'field_cache')),
                  'Accepted native settings differ from the retained failure settings')
    for ref, digest in accepted_binding['source_file_sha256'].items():
        store.require(response.file_sha(ROOT/ref) == digest, 'Accepted producer source changed')
    inherited = {}
    for row in response.read(accepted/'results.json')['results']:
        if row['drift_cap_ns'] != request['numerics']['drift_cap_ns'] or row['status'] != 'completed':
            continue
        event_path = Path(row['event_ref']); event = response.read(event_path); signal = accepted/event['signals_ref']
        key = event['event_id'], event['input_group']['group_id']
        if key not in rows or rows[key]['ordinal'] not in selected: continue
        store.require(digital.terminal_contacts_complete(event)
                      and store.sha(store.encoded(event['input_group'])) == rows[key]['input_sha256']
                      and response.file_sha(signal) == row['signals_sha256'], 'Accepted complete group does not bind')
        inherited[str(rows[key]['ordinal'])] = {'event_ref': str(event_path.relative_to(ROOT)), 'event_sha256': response.file_sha(event_path),
            'signals_ref': str(signal.relative_to(ROOT)), 'signals_sha256': row['signals_sha256'],
            'acceptance_ref': str(accepted.relative_to(ROOT)), 'validation_sha256': response.file_sha(accepted/'validation.json'),
            'request_sha256': accepted_binding['request_1000_sha256'], 'producer_archive_sha256': accepted_binding['producer_archive_sha256'],
            'native_support_ns': R.native_support_ns(request['numerics'])}
    refs = set(request['source_sha256']) | {'simulation/native_segment_crossing.jl', 'simulation/native_boundary_guard.jl',
        'tools/gegi_boundary_failure_recovery.py', 'tools/gegi_native_failure_recovery.py', 'tools/gegi_native_failure_diagnostic.py',
        'tools/gegi_missing_history.py', 'tools/gegi_resource_monitor.py', 'tools/gegi_digital_readout.py'}
    request['source_sha256'] = {ref: response.file_sha(ROOT/ref) for ref in sorted(refs)}
    identity = {'kind': KIND, 'source_ref': old_identity['source_ref'], 'source_sha256': old_identity['source_sha256'],
        'original_groups': old_identity['group_count'], 'baseline': binding, 'selected_ordinals': sorted(selected),
        'selected_groups': len(selected), 'inherited_acceptance': inherited, 'producer_sha256': response.file_sha(__file__)}
    output.mkdir(parents=True); response.write(output/'native-request.json', request)
    identity['request_sha256'] = response.file_sha(output/'native-request.json'); response.write(output/'identity.json', identity)
    with zipfile.ZipFile(output/'producer-source.zip', 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for ref in sorted(refs): archive.write(ROOT/ref, ref)
        for name in ('native-request.json', 'identity.json'): archive.write(output/name, name)
    return identity


def inherit(ordinal, group, identity, native):
    binding = identity['inherited_acceptance'].get(str(ordinal))
    if binding is None: return None
    event_path, signal_path = (ROOT/binding[k] for k in ('event_ref', 'signals_ref'))
    store.require(response.file_sha(event_path) == binding['event_sha256']
                  and response.file_sha(signal_path) == binding['signals_sha256'], 'Accepted inherited result changed')
    event = response.read(event_path); digest = store.sha(store.encoded(group))
    store.require(event['input_group'] == group and digital.terminal_contacts_complete(event), 'Inherited contact-complete input differs')
    signals = store.native_csv(signal_path, event['channels'])
    event.update(group_id=group['group_id'], input_event_sha256=digest, input_steps=group['steps'],
                 readout_recipe_sha256=None, native_recovery_inherited={**binding,
                 'policy': 'Exact accepted terminal-complete response; actual request and producer retained; no drift repeated.'})
    native.append(group['event_id'], group['group_id'], event, signals, digest)
    return response.verify_store_roundtrip(native, group['event_id'], group['group_id'], event, signals, digest)


def snapshot(source_rows, native, acquisition, previous, previous_rows, selected, support, layer, timings):
    history = R.MissingHistory(acquisition['live_time_ns'], native_support_ns=support)
    effective, outcomes, origins = Counter(), Counter(), Counter(); ledger = []
    for ordinal, group, _ in source_rows:
        key = group['event_id'], group['group_id']; digest = store.sha(store.encoded(group)); old = previous_rows[key]
        store.require((old['ordinal'], old['input_sha256']) == (ordinal, digest), 'Boundary input differs from baseline')
        row = dict(old)
        if ordinal in selected and native.has(*key, digest):
            event = native.read(*key)[0]; timing = timings.get(key)
            store.require(event['input_group'] == group, 'Repaired native input differs')
            row.update(new_status=event['status'], new_domain_error=event.get('native_domain_error'),
                complete=digital.terminal_contacts_complete(event), native_support_ns=support,
                native_origin='selected_boundary_result', native_recovery_inherited=event.get('native_recovery_inherited'),
                elapsed_seconds=None if timing is None else timing['elapsed_seconds'],
                timing_status=('inherited_exact_acceptance' if event.get('native_recovery_inherited') else 'no_retained_timing_entry') if timing is None else timing['timing_status'],
                native_record_binding={**layer, 'event_metadata_sha256': native.db.execute(
                    'SELECT metadata_sha256 FROM events WHERE primary_id=? AND group_id=?', key).fetchone()[0]})
            outcomes[row['new_status']] += 1
        store.require(row['complete'] == (row['new_status'] == 'completed'), 'Native completion lacks physical contact endpoints')
        effective[row['new_status']] += 1; origins[row['native_origin']] += 1; ledger.append(row)
        if not row['complete']:
            history.native_support_ns = row['native_support_ns']
            history.add(group['group_origin_time_ns'], max(s['time_ns'] for s in group['steps']), math.fsum(s['energy_keV'] for s in group['steps']))
    store.require(len(ledger) == len(previous_rows) and len({r['ordinal'] for r in ledger}) == len(ledger)
                  and sum(outcomes.values()) == native.db.execute('SELECT count(*) FROM events').fetchone()[0],
                  'Original denominator or selected boundary store census differs')
    old_history = previous['conditional_history']; current = history.intervals()
    return ledger, {'original_groups': len(ledger), 'selected_groups': len(selected), 'processed_selected_groups': sum(outcomes.values()),
        'effective_counts': dict(effective), 'selected_outcomes': dict(outcomes), 'provenance_counts': dict(origins),
        'old_unavailable_union': old_history['old_unavailable_union'], 'baseline_remaining_unknown_union': old_history['remaining_unknown_union'],
        'remaining_unknown_union': history.statistics(), 'remaining_intervals_ns': current,
        'original_mask_comparison': R.mask_overlap(acquisition['excluded_intervals_ns'], current),
        'baseline_mask_comparison': R.mask_overlap(old_history['remaining_intervals_ns'], current),
        'scope': 'Conditional native availability only; actual per-group producer layers and configured supports retained. No original ADC or trigger requalification.'}


def run(output, *, stop_after_new=None):
    output = Path(output).resolve(); identity = response.read(output/'identity.json'); request = response.read(output/'native-request.json')
    store.require(identity['producer_sha256'] == response.file_sha(__file__)
                  and identity['request_sha256'] == response.file_sha(output/'native-request.json'), 'Boundary producer or request changed')
    _, old_identity, _, previous, rows = baseline(ROOT/identity['baseline']['ref'], identity['baseline'])
    selected = set(identity['selected_ordinals']); source = ROOT/identity['source_ref']
    store.require(selected == selected_rows(rows) and identity['selected_groups'] == len(selected)
                  and identity['source_sha256'] == old_identity['source_sha256'] == response.file_sha(source/'compton-candidates.sqlite'),
                  'Boundary selection or original acquisition changed')
    path = output/'native.sqlite'; native = store.Store(path, identity, create=not path.exists())
    sealed = native.db.execute('SELECT body FROM completion WHERE singleton=1').fetchone()
    if sealed: native.close(); return json.loads(sealed[0])
    worker = response.ResidentWorker(output/'native-request.json', output/'native-spool')
    monitor = R.Monitor(output, response.read(output/'resources.json') if (output/'resources.json').exists() else None)
    monitor.data['available_memory_before_worker_bytes'] = R.available_memory(); new_count = 0; status = 'running'; started = time.perf_counter()
    try:
        with monitor:
            ready = worker.start(); monitor.pids['native'] = worker.process.pid; support = R.ready_support(ready, request)
            response.write(output/'native-ready.json', ready)
            response.write(output/'active-worker.json', {'status':'running', 'python_pid':os.getpid(), 'native_pid':worker.process.pid,
                'request_sha256':identity['request_sha256'], 'producer_archive_sha256':response.file_sha(output/'producer-source.zip')})
            handoff={'owner':'/root/native_response','status':'running','current_python_pid':os.getpid(),'current_native_pid':worker.process.pid,
                'request_sha256':identity['request_sha256'],'producer_archive_sha256':response.file_sha(output/'producer-source.zip'),
                'selected_groups':len(selected),'checkpoint_ref':str((output/'checkpoint.json').relative_to(ROOT))}
            counts=Counter(native.read(*key)[0]['status'] for key in native.keys())
            response.write(output/'continuation-handoff.json',{**handoff,'processed_groups':sum(counts.values()),'selected_counts':dict(counts)})
            with (output/'recovery-ledger.jsonl').open('ab') as stream:
                for ordinal, group, _ in R.groups(source):
                    if ordinal not in selected: continue
                    digest = store.sha(store.encoded(group)); key = group['event_id'], group['group_id']
                    store.require((rows[key]['ordinal'],rows[key]['input_sha256']) == (ordinal,digest), 'Selected boundary input changed')
                    if not native.has(*key,digest):
                        if (output/'stop.request').exists() or (stop_after_new is not None and new_count>=stop_after_new): status='stopped'; break
                        begin=time.perf_counter(); event=inherit(ordinal,group,identity,native); inherited=event is not None
                        if not inherited: event=worker.process_group(group,native); new_count+=1
                        counts[event['status']]+=1
                        stream.write(store.encoded({'ordinal':ordinal,'event_id':key[0],'group_id':key[1],'input_sha256':digest,
                            'new_status':event['status'],'complete':digital.terminal_contacts_complete(event),
                            'elapsed_seconds':None if inherited else time.perf_counter()-begin,
                            'timing_status':'inherited_exact_acceptance' if inherited else 'measured'})+b'\n');stream.flush();os.fsync(stream.fileno())
                    response.write(output/'checkpoint.json',{'status':'running','processed_groups':sum(counts.values()),'selected_groups':len(selected),
                        'counts':dict(counts),'new_groups_this_activation':new_count,'last_ordinal':ordinal,'last_event_id':key[0]})
                    response.write(output/'continuation-handoff.json',{**handoff,'processed_groups':sum(counts.values()),'selected_counts':dict(counts)})
                else: status='completed'
            worker.close()
    finally:
        worker.close();response.write(output/'resources.json',monitor.data)
        response.write(output/'active-worker.json',{'status':'closed','python_pid':os.getpid()})
        native.close()
    native=store.Store(path,identity)
    try:
        lines=(output/'recovery-ledger.jsonl').read_bytes().splitlines(keepends=True)
        timings={(r['event_id'],r['group_id']):r for r in (json.loads(line) for line in lines if line.endswith(b'\n'))}
        layer={'ref':str(output.relative_to(ROOT)),'request_sha256':identity['request_sha256'],
            'producer_archive_sha256':response.file_sha(output/'producer-source.zip'),'ready_sha256':response.file_sha(output/'native-ready.json')}
        ledger,history=snapshot(R.groups(source),native,response.read(source/'candidate-acquisition.json'),previous,rows,selected,support,layer,timings)
        with (output/'recovery-status.jsonl').open('wb') as stream:
            for row in ledger:stream.write(store.encoded(row)+b'\n')
        store.require(response.file_sha(ROOT/request['field_cache']['ref'])==request['field_cache']['sha256'],'Original field cache changed')
        store.require(all(response.file_sha(ROOT/ref)==digest for ref,digest in request['source_sha256'].items()),'Pinned boundary producer source changed')
        result={'kind':KIND,'status':status,'identity':identity,'counts':history['selected_outcomes'],'conditional_history':history,
            'new_groups_this_activation':new_count,'activation_seconds':time.perf_counter()-started,'resources':monitor.data,
            'status_ledger_sha256':response.file_sha(output/'recovery-status.jsonl')}
        response.write(output/'checkpoint.json',result)
        if status=='completed':
            store.require(history['processed_selected_groups']==len(selected),'Selected boundary census does not close')
            native.seal(result);response.write(output/'recovery.json',result)
        response.write(output/'continuation-handoff.json',{'owner':'/root/native_response','status':status,'current_python_pid':None,
            'current_native_pid':None,'request_sha256':identity['request_sha256'],'producer_archive_sha256':layer['producer_archive_sha256'],
            'processed_groups':history['processed_selected_groups'],'selected_groups':len(selected),'selected_counts':result['counts'],
            'effective_counts':history['effective_counts'],'checkpoint_ref':str((output/'checkpoint.json').relative_to(ROOT))})
        print(json.dumps({'status':status,'counts':result['counts'],'effective_counts':history['effective_counts']}),flush=True)
        return result
    finally:native.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--prepare',action='store_true');parser.add_argument('--baseline',type=Path);parser.add_argument('--accepted',type=Path)
    parser.add_argument('--stop-after-new',type=int);args=parser.parse_args()
    if args.prepare:
        if args.baseline is None or args.accepted is None:parser.error('Preparation requires the sealed cap baseline and accepted witness phase')
        prepare(args.baseline,args.accepted,args.output)
    else:
        if args.baseline is not None or args.accepted is not None:parser.error('Baseline and acceptance are bound during preparation')
        if args.stop_after_new is not None and args.stop_after_new<1:parser.error('Use a positive cooperative prefix size')
        run(args.output,stop_after_new=args.stop_after_new)
