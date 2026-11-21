"""Read-only retained native-response census; never relabel saved acquisition triggers."""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import zlib


def endpoint_region(position):
    """Nominal frozen GeGI octagonal prism; geometry proximity, not a stop reason."""
    x, y, z = position
    distances = {'z_face': abs(abs(z)-5.5), 'x_face': abs(abs(x)-45.),
                 'y_face': abs(abs(y)-45.),
                 'diagonal_face': abs(abs(x)+abs(y)-45.*math.sqrt(2))/math.sqrt(2)}
    name = min(distances, key=distances.get)
    return name if distances[name] <= 1e-4 else 'interior'


def summarize_record(record):
    event, native, group = record['event'], record['native'], record['group']
    endpoints = [endpoint for step in event['steps'] for endpoint in step.get('endpoints', [])]
    limits = [endpoint for endpoint in endpoints if endpoint['step_limit_reached']]
    real_limits = [endpoint for endpoint in limits if not endpoint['contact_ids']]
    return {'status': event['status'], 'truth_rows': len(group['steps']),
            'native_available': native is not None, 'endpoint_count': len(endpoints),
            'contact_at_limit': len(limits)-len(real_limits), 'noncontact_at_limit': len(real_limits),
            'stopped_regions': Counter(endpoint_region(endpoint['position_mm'])
                for endpoint in endpoints if endpoint['status'] == 'stopped_without_contact'),
            'terminal_bin_moving': (any(wave['signed_induced_keV'][-1] != wave['signed_induced_keV'][-2]
                for wave in native.values()) if native is not None else None),
            'domain_error': event.get('native_domain_error', event.get('error'))}


def readonly(path):
    return sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True)


def reconciled_recovery_rows(source_rows, native, timing_rows):
    """The transactional native store is authoritative when a timing append was interrupted."""
    import gegi_digital_readout as digital
    import gegi_event_store as storage
    timings = {(row['event_id'], row['group_id']): row for row in timing_rows}
    for ordinal, group, original in source_rows:
        primary, gid = group['event_id'], group['group_id']
        digest = storage.sha(storage.encoded(group))
        saved = native.read(primary, gid)[0] if native.has(primary, gid, digest) else None
        timing = timings.get((primary, gid))
        if timing is not None:
            storage.require(timing['input_sha256'] == digest, 'Recovery timing entry changed its original input')
        complete = False if saved is None else digital.terminal_contacts_complete(saved)
        if saved is not None and saved['status'] == 'completed':
            storage.require(complete, 'Completed native status lacks two collected carriers per deposit')
        yield {'ordinal': ordinal, 'event_id': primary, 'group_id': gid, 'input_sha256': digest,
               'original_status': original['status'], 'original_domain_error': original.get('native_domain_error'),
               'new_status': None if saved is None else saved['status'],
               'new_domain_error': None if saved is None else saved.get('native_domain_error'),
               'complete': complete,
               'native_recovery_inherited': None if saved is None else saved.get('native_recovery_inherited'),
               'elapsed_seconds': None if timing is None else timing['elapsed_seconds'],
               'timing_status': (timing.get('timing_status', 'measured') if timing is not None else
                                 'unprocessed' if saved is None else 'no_retained_timing_entry')}


def reconcile_recovery(output):
    """Write one complete derivative ledger after the recovery worker has closed."""
    import gegi_campaign_response as response
    import gegi_event_store as storage
    from gegi_native_failure_recovery import groups
    output = Path(output).resolve()
    identity = response.read(output/'identity.json')
    if (output/'active-worker.json').exists():
        storage.require(response.read(output/'active-worker.json')['status'] == 'closed',
                        'Reconcile after the native recovery worker has closed')
    target, summary = output/'recovery-status.jsonl', output/'recovery-status-summary.json'
    storage.require(not target.exists() and not summary.exists(), 'Keep the existing reconciled recovery ledger')
    timing_blob = (output/'recovery-ledger.jsonl').read_bytes()
    lines = timing_blob.splitlines(keepends=True)
    trailing = lines[-1] if lines and not lines[-1].endswith(b'\n') else b''
    timings = [json.loads(line) for line in (lines[:-1] if trailing else lines)]
    source = response.ROOT/identity['source_ref']
    storage.require(response.file_sha(source/'compton-candidates.sqlite') == identity['source_sha256'],
                    'Original recovery input changed')
    native = storage.Store(output/'native.sqlite', identity)
    counts, transitions, timing_counts = Counter(), Counter(), Counter()
    recovered = total = 0
    try:
        with target.open('xb') as stream:
            for row in reconciled_recovery_rows(groups(source), native, timings):
                stream.write(storage.encoded(row)+b'\n'); total += 1; recovered += row['complete']
                counts[row['new_status'] or 'unprocessed'] += 1
                original = row['original_domain_error'] or row['original_status']
                transitions[original+' -> '+str(row['new_status'])] += 1
                timing_counts[row['timing_status']] += 1
        storage.require(total == identity['group_count'], 'Reconciled original group census does not close')
        storage.require(total-counts['unprocessed'] == native.db.execute('SELECT count(*) FROM events').fetchone()[0],
                        'Native store contains a missing or extraneous original group')
        result = {'kind': 'gegi_reconciled_native_recovery_ledger_v1', 'groups': total,
                  'complete_native_groups': recovered, 'counts': dict(counts), 'transitions': dict(transitions),
                  'timing_counts': dict(timing_counts), 'retained_timing_tail_bytes': len(trailing),
                  'retained_timing_tail_sha256': hashlib.sha256(trailing).hexdigest() if trailing else None,
                  'status_ledger_sha256': response.file_sha(target),
                  'scope': 'Source identities joined to committed native records; missing append times remain null. '
                           'No original trigger or shared readout record changes.'}
        response.write(summary, result)
        return result
    finally:
        native.close()


def diagnose(run):
    run = Path(run)
    counts, endpoints, terminal_bins, regions, errors = (Counter() for _ in range(5))
    exemplars, selected_inputs = {}, []
    with readonly(run/'compton-candidates.sqlite') as connection:
        census = dict(connection.execute('SELECT status, count(*) FROM input_groups GROUP BY status'))
        for ordinal, blob in connection.execute('SELECT ordinal, record FROM native_failures ORDER BY ordinal'):
            record = json.loads(zlib.decompress(blob)); row = summarize_record(record)
            status = row['status']; counts[status] += 1
            counts['truth_inputs_retained'] += bool(row['truth_rows'])
            counts['native_arrays_retained'] += row['native_available']
            endpoints['contact_at_limit'] += row['contact_at_limit']
            endpoints['noncontact_at_limit'] += row['noncontact_at_limit']
            endpoints['stopped_without_contact'] += sum(row['stopped_regions'].values())
            regions.update(row['stopped_regions'])
            if status == 'step_limit':
                counts['step_limit_with_real_noncontact_limit'] += bool(row['noncontact_at_limit'])
                counts['step_limit_only_contact_limit'] += not row['noncontact_at_limit']
            if row['native_available']:
                terminal_bins[status+('_moving' if row['terminal_bin_moving'] else '_flat')] += 1
            if status == 'native_failed':
                errors[row['domain_error']] += 1
            key = row['domain_error'] if status == 'native_failed' else status
            if key not in exemplars:
                exemplars[key] = {'ordinal': ordinal, 'event_id': record['group']['event_id'],
                                  'group_id': record['group']['group_id']}
                selected_inputs.append({'ordinal': ordinal, 'group': record['group'],
                                        'old_status': status, 'old_domain_error': row['domain_error']})
    prefix = []
    for path in (run/'native-scratch.sqlite', run/'native-only/native-scratch.sqlite'):
        if path.is_file():
            with readonly(path) as connection:
                count = truth = 0
                for blob, in connection.execute('SELECT metadata FROM events'):
                    event = json.loads(zlib.decompress(blob)); count += 1
                    truth += bool(event.get('input_group', {}).get('steps'))
                prefix.append({'ref': path.relative_to(run).as_posix(), 'events': count,
                               'events_with_truth_inputs': truth})
    request = json.loads((run/'native-request.json').read_text(encoding='utf-8-sig'))
    dt = request['numerics']['drift_dt_ns']; cap = request['numerics']['drift_cap_ns']
    support = math.ceil(cap/dt)*dt+dt
    result = {'kind': 'gegi_retained_native_failure_diagnostic_v1',
              'input_ref': (run/'compton-candidates.sqlite').as_posix(),
              'input_sha256': hashlib.file_digest((run/'compton-candidates.sqlite').open('rb'), 'sha256').hexdigest(),
              'input_group_census': census, 'retained_failure_census': dict(counts),
              'endpoint_counts': dict(endpoints), 'stopped_endpoint_geometric_proximity': dict(regions),
              'terminal_native_bin': dict(terminal_bins), 'failed_domain_errors': dict(errors),
              'retained_prefix_stores': prefix, 'exemplar_identities': exemplars,
              'configured_native_support_ns': support,
              'legacy_missing_history_support_ns': 1001.,
              'missing_history_matches_actual_request': support == 1001.,
              'limits': ['Terminal bin movement is signed induced-charge change, not a carrier stop diagnosis.',
                         'Proximity to the nominal crystal face is not a proof of the SSD termination branch.',
                         'No acquired trigger, exclusion interval, native record or truth input is modified.']}
    return result, selected_inputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path); parser.add_argument('--output', type=Path)
    parser.add_argument('--exemplars', type=Path)
    parser.add_argument('--reconcile-recovery', action='store_true')
    args = parser.parse_args()
    if args.reconcile_recovery:
        print(json.dumps(reconcile_recovery(args.run), sort_keys=True)); return
    if args.output is None:
        parser.error('Diagnostic census requires --output')
    result, exemplars = diagnose(args.run)
    for path in (args.output, args.exemplars):
        if path is not None and path.exists():
            raise ValueError('Use a new derivative output; preserve previous diagnosis')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    if args.exemplars:
        args.exemplars.write_text(json.dumps(exemplars, separators=(',', ':'), allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps(result['retained_failure_census'], sort_keys=True))


if __name__ == '__main__':
    main()
