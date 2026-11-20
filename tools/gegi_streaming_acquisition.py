"""Bounded joint-source transport, disk-backed delayed deposits and continuous readout.

The first supported execution is a 1–500 parent startup acceptance. Blocks are
computational checkpoints, never separate physical acquisitions. The source
clock, transport RNG, active electrode currents and electronics survive resume.
"""
from __future__ import annotations
import argparse
from collections import Counter
from contextlib import closing
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import shutil
import sqlite3
import subprocess
import zlib

import numpy as np

import gegi_candidate_run as candidates
import gegi_candidate_storage as storage
import gegi_campaign_response as response
import gegi_digital_readout as digital
import gegi_dual_source as dual
import gegi_event_store as native_store
import gegi_mixed_acquisition as mixed
import gegi_pulse_stream as pulse
from gegi_resource_monitor import Monitor, _linked, available_memory
from gegi_streaming_readout import StreamingReadout
import gegi_workflow as workflow
import scenario_workflow as W

ROOT = Path(__file__).resolve().parents[1]
KIND = 'gegi_streaming_acquisition_v1'
OWN_SOURCES = ('tools/gegi_streaming_acquisition.py', 'tools/gegi_streaming_readout.py',
               'tools/gegi_candidate_storage.py', 'tools/gegi_candidate_run.py',
               'transport/gegi_streaming_source.py')
COUNT_FIELDS = ('qualified_triggers', 'single_pixel_energies', 'additional_multi_strip_energies',
                'qualified_energies', 'triggers_without_energy')


def transport_call(arguments, log):
    command = W.transport_prefix(ROOT) + ['python', '-B', './gegi_streaming_source.py', *arguments]
    command += W.transport_root_args(ROOT)
    with Path(log).open('ab') as handle:
        result = subprocess.run(command, cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    if result.returncode:
        raise RuntimeError('Source block did not complete. Its inputs, RNG state and error log are preserved.')


def relative(path):
    return '../' + Path(path).relative_to(ROOT).as_posix()


def source_config(name, count, seed, activities, positions):
    return {'kind': 'gegi_streaming_source_config_v1', 'acquisition_id': name,
        'seed': seed, 'clock_seed': seed, 'stop': {'mode': 'count', 'parent_count': count},
        'initial_state': {'policy': 'new_parent_decays_empty_daughters_at_start',
            'acquisition_start_ns': 0, 'initial_daughter_populations': {},
            'pre_acquisition_history': 'none', 'scope': 'startup acceptance, not secular equilibrium'},
        'sources': [{'id': sid, 'activity_Bq': rate, 'position_global_mm': list(position)}
            for sid, rate, position in zip((workflow.CS137, workflow.CO60), activities, positions, strict=True)]}


def _schema(sink):
    sink.db.executescript('''
        CREATE TABLE IF NOT EXISTS input_groups (
          ordinal INTEGER PRIMARY KEY, parent INTEGER NOT NULL, group_id INTEGER NOT NULL,
          onset_ns REAL NOT NULL, last_ns REAL NOT NULL, status TEXT NOT NULL,
          metadata BLOB NOT NULL, pending BLOB, input_sha256 TEXT NOT NULL,
          UNIQUE(parent,group_id));
        CREATE INDEX IF NOT EXISTS pending_time ON input_groups(status,onset_ns,ordinal);
        CREATE INDEX IF NOT EXISTS group_time ON input_groups(onset_ns);
        CREATE TABLE IF NOT EXISTS source_blocks (block_index INTEGER PRIMARY KEY, manifest BLOB NOT NULL,
          manifest_sha256 TEXT NOT NULL, after_state BLOB NOT NULL);
        CREATE TABLE IF NOT EXISTS native_failures (ordinal INTEGER PRIMARY KEY, record BLOB NOT NULL);
    ''')


def _group_meta(group):
    return {'parent_decay_id': group['event_id'], 'source_id': group['source_id'],
        'group_id': group['group_id'], 'first_ge_deposit_ns': group['group_origin_time_ns'],
        'last_ge_deposit_ns': max(row['time_ns'] for row in group['steps']),
        'positive_ge_energy_keV': sum(row['energy_keV'] for row in group['steps']),
        'raw_row_indices': [row['raw_row_index'] for row in group['steps']],
        'parent_event_metadata': group['parent_event_metadata']}


def _ingest(sink, directory, after, census):
    manifest_path = directory / 'stream/manifest.json'
    manifest = W.read(manifest_path)
    events = manifest_path.parent / manifest['events_file']
    if mixed.file_sha(events) != manifest['events_sha256']:
        raise ValueError('The completed source deposit stream changed')
    with events.open(encoding='utf-8') as handle:
        for line in handle:
            event = mixed.absolute_event(json.loads(line))
            for group in mixed.native_groups(event):
                meta = _group_meta(group)
                body = native_store.encoded(group)
                sink.db.execute('INSERT INTO input_groups(parent,group_id,onset_ns,last_ns,status,metadata,pending,input_sha256) VALUES (?,?,?,?,?,?,?,?)',
                    (group['event_id'], group['group_id'], meta['first_ge_deposit_ns'], meta['last_ge_deposit_ns'],
                     'pending', native_store.encoded(meta), zlib.compress(body), hashlib.sha256(body).hexdigest()))
                census['deposit_groups'] += 1
    counts = manifest['counts']
    census['initial_parents'] += manifest['primary_count']
    census['zero_deposit_parents'] += counts['zero_deposit_primaries']
    census['nonzero_parents'] += counts['nonzero_primaries']
    sink.db.execute('INSERT INTO source_blocks VALUES (?,?,?,?)',
        (after['next_block_index'] - 1, native_store.encoded(manifest), mixed.file_sha(manifest_path), native_store.encoded(after)))


def _retire_block(output, directory):
    receipt = directory / 'candidate-retention.json'
    if (directory / 'retired-artifacts.json').exists():
        return
    if not receipt.exists():
        candidates.write_new(receipt, {'kind': 'gegi_streaming_source_consumer_receipt_v1', 'status': 'committed',
            'block_index': W.read(directory / 'checkpoint-after.json')['next_block_index'] - 1,
            'source_manifest_sha256': mixed.file_sha(directory / 'stream/manifest.json'),
            'checkpoint_after_sha256': mixed.file_sha(directory / 'checkpoint-after.json'),
            'database_ref': (output / storage.ARCHIVE_NAME).relative_to(ROOT).as_posix()})
    transport_call(['retire', '--directory', relative(directory), '--consumer-receipt', relative(receipt)], output / 'transport.log')


def _spectra(histograms):
    edges = list(range(0, dual.BIN_STOP_KEV + 1, dual.BIN_STEP_KEV))
    return {name: {'bin_edges_keV': edges, 'counts': [hist[i] for i in range(len(edges)-1)],
        'underflow': sum(n for i, n in hist.items() if i < 0),
        'overflow': sum(n for i, n in hist.items() if i >= len(edges)-1),
        'entries': sum(hist.values())} for name, hist in histograms.items()}


def _write_report(output, identity, state, completion, resources):
    database = output / storage.ARCHIVE_NAME
    verification = candidates.verify_candidates(database)
    ledger = output / 'input-groups.jsonl.gz'
    if not ledger.exists():
        def export(handle):
            with gzip.GzipFile(fileobj=handle, mode='wb', mtime=0) as zipped, closing(sqlite3.connect(database)) as db:
                for ordinal, status, body in db.execute('SELECT ordinal,status,metadata FROM input_groups ORDER BY ordinal'):
                    zipped.write(native_store.encoded({'input_group_ordinal': ordinal, 'status': status, **json.loads(body)}) + b'\n')
        dual._publish_artifact(ledger, export)
    histograms = {name: Counter({int(k): v for k, v in values.items()}) for name, values in state['histograms'].items()}
    report = {'kind': candidates.KIND, 'status': 'completed', 'identity': identity,
        'selection_policy': storage.POLICY, 'source': state['census'], 'counts': state['counts'],
        'storage_counts': {key: completion[key] for key in ('observed_coincident_rises', 'saved_candidates',
            'rejected_rises', 'selection_reason_counts')},
        'readout': state['readout_statistics'], 'spectra': _spectra(histograms),
        'live_time_ns': state['live_time_ns'], 'excluded_intervals_ns': state['excluded_intervals_ns'],
        'verification': verification, 'resources': resources,
        'software': {'readout': identity.get('environment'), 'native': state.get('native_environment')},
        'artifacts': {p.name: {'bytes': p.stat().st_size, 'sha256': mixed.file_sha(p)} for p in (database, ledger)},
        'retention': {'full_adc_stream_saved': False, 'native_inputs_saved_here': False,
            'candidate_signals': 'Exact all-34-electrode ADC contexts and fast/slow/timing measurements.',
            'truth_association': 'One-based input_groups ordinals; diagnostic association only, not event selection.',
            'delayed_deposits': 'Disk-backed original groups beyond the acquisition remain explicitly censored.',
            'native_failure_policy': 'Preserve exact failure and conservatively mark subsequent history unknown.'},
        'limitations': ['Bounded startup acceptance with no pre-existing daughter inventory.',
            'Continuous processing and restart do not establish detector accuracy or long-run throughput.']}
    candidates.write_new(output / candidates.REPORT_NAME, report)
    return report


def _sealed_state(path, identity):
    """Recover only the final export if completion committed before an interruption."""
    with closing(storage._open_readonly(path)) as db:
        completion = db.execute('SELECT body FROM completion WHERE singleton=1').fetchone()
        if completion is None:
            return None
        metadata = json.loads(db.execute('SELECT body FROM metadata WHERE singleton=1').fetchone()[0])
        if metadata != storage._metadata(identity):
            raise ValueError('Completed acquisition identity differs')
        bound, last_id, last_candidate, last_record, body, digest = db.execute(
            'SELECT identity_sha256,last_trigger_id,last_candidate_trigger_id,last_record_sha256,state,checkpoint_sha256 FROM checkpoint').fetchone()
        expected = storage._digest(native_store.encoded({'kind': storage.CHECKPOINT_KIND,
            'identity_sha256': bound, 'last_trigger_id': last_id, 'last_candidate_trigger_id': last_candidate,
            'last_record_sha256': last_record, 'state_sha256': storage._digest(body)}))
        if bound != storage._digest(native_store.encoded(identity)) or expected != digest:
            raise ValueError('Completed checkpoint changed before export')
        return json.loads(body), json.loads(completion[0])


def run(output, primary_count=100, seed=20261120, activities_bq=(185000, 37000),
        positions_mm=((-40, 0, 40), (40, 0, 40)), on_progress=None, *, block_parents=50,
        resume=False, stop_requested=None, stop_after_blocks=None, stop_after_groups=None,
        retain_validation_inputs=False):
    output = Path(output).resolve()
    if not output.is_relative_to((ROOT / '.local').resolve()) or output == (ROOT / '.local').resolve():
        raise ValueError('Use an owned acquisition directory under this project .local')
    if type(primary_count) is not int or not 1 <= primary_count <= 500:
        raise ValueError('This streaming acceptance supports 1–500 initial parents. Long production remains a separate milestone.')
    if type(block_parents) is not int or not 1 <= block_parents <= 500:
        raise ValueError('Use a source block of 1–500 initial parents')
    if any(_linked(p) for p in (output, *output.parents) if p.is_relative_to(ROOT)):
        raise ValueError('Linked acquisition directory refused')
    config = source_config(output.name, primary_count, seed, activities_bq, positions_mm)
    def progress(status, stage, **fields):
        value = {'status': status, 'stage': stage, **fields}
        W.write(output / 'progress.json', value)
        if on_progress:
            on_progress(value)
    if resume:
        if W.read(output / 'source-config.json') != config:
            raise ValueError('Resume requires the original sources, seed, count and source state')
        request = output / 'native-request.json'
    else:
        if output.exists() and any(output.iterdir()):
            raise FileExistsError('Choose a fresh name or explicitly resume the existing acquisition')
        output.mkdir(parents=True, exist_ok=True)
        candidates.write_new(output / 'source-config.json', config)
        request = mixed.native_request(output, primary_count)
    identity = {'kind': KIND, 'source_config': config, 'native_request_sha256': mixed.file_sha(request),
        'environment': {'python': platform.python_version(), 'numpy': np.__version__, 'sqlite': sqlite3.sqlite_version},
        'source_sha256': {ref: mixed.file_sha(ROOT / ref) for ref in OWN_SOURCES},
        'readout_tail_ns': mixed.READOUT_TAIL_NS, 'scope': 'Fresh shared-clock startup acquisition; bounded streaming acceptance.'}
    if resume and (output / candidates.REPORT_NAME).exists():
        report = W.read(output / candidates.REPORT_NAME)
        if report['identity'] != identity:
            raise ValueError('Completed acquisition producer changed')
        candidates.verify_candidates(output / storage.ARCHIVE_NAME)
        return report
    database = output / storage.ARCHIVE_NAME
    if resume and database.exists():
        sealed = _sealed_state(database, identity)
        if sealed is not None:
            state, completion = sealed
            resources = W.read(output / 'resources.json') if (output / 'resources.json').exists() else state['resources']
            report = _write_report(output, identity, state, completion, resources)
            progress('completed', 'Recovered the completed acquisition report', resources=resources)
            return report
        stop_marker = output / 'stop.request'
        if _linked(stop_marker):
            raise ValueError('Linked stop marker refused')
        stop_marker.unlink(missing_ok=True)
    sink = storage.CandidateStore(database, identity, resume=resume and database.exists())
    worker = native = None
    completed = False
    state = sink.load_checkpoint() if resume else None
    if state is None:
        _schema(sink)
        try:
            if not (output / 'source-checkpoint.json').exists():
                transport_call(['init', '--config', relative(output / 'source-config.json'),
                                '--output', relative(output / 'source-checkpoint.json')], output / 'transport.log')
        except BaseException as error:
            sink.close()
            progress('failed', str(error), resumable=True, partial_data_retained=True)
            raise
        state = {'source_checkpoint': W.read(output / 'source-checkpoint.json'), 'readout': None,
            'census': {}, 'counts': {}, 'histograms': {name: {} for name in ('single_pixel', 'additional_multi_strip', 'combined')},
            'unknown_since_ns': None, 'channels': None, 'live_time_ns': None, 'resources': {}}
        with sink.transaction():
            sink.save_checkpoint(state)
    census, counts = Counter(state['census']), Counter(state['counts'])
    histograms = {name: Counter({int(k): v for k, v in values.items()}) for name, values in state['histograms'].items()}
    readout = None
    channels = state['channels']

    def observe(event, context):
        card = dual._trigger_card(event, dual._strip_neighbors(channels), geometry=channels)
        reason = context['readout_rejection_reason']
        if state['unknown_since_ns'] is not None and event['rise_end_ns'] >= state['unknown_since_ns']:
            reason = 'unknown_native_history'
        if reason is None:
            counts['qualified_triggers'] += 1
            for name, field in (('single_pixel', 'single_pixel_energy_keV'), ('additional_multi_strip', 'additional_multi_strip_energy_keV')):
                energy = card[field]
                if energy is not None:
                    counts[name + '_energies'] += 1
                    bucket = math.floor(energy / dual.BIN_STEP_KEV)
                    histograms[name][bucket] += 1; histograms['combined'][bucket] += 1
        first = context['first_sample_index'] * 20 + context['adc_phase_ns'] - 40 * digital._TAU
        last = context['stop_sample_index'] * 20 + context['adc_phase_ns']
        related = [row[0] for row in sink.db.execute('SELECT ordinal FROM input_groups WHERE onset_ns BETWEEN ? AND ? ORDER BY onset_ns,ordinal', (first, last))]
        sink.observe(card, context, event=event, identities=related, rejection_reason=reason)

    readout = (StreamingReadout.restore(state['readout'], on_readout_context=observe) if state['readout'] else
               StreamingReadout(noise_seed=seed + 100000000, on_readout_context=observe))
    previous_resources = W.read(output / 'resources.json') if resume and (output / 'resources.json').exists() else state.get('resources')
    monitor = Monitor(output, previous_resources)
    def checkpoint():
        counts['qualified_energies'] = counts['single_pixel_energies'] + counts['additional_multi_strip_energies']
        counts['triggers_without_energy'] = counts['qualified_triggers'] - counts['qualified_energies']
        state.update(readout=readout.checkpoint(), census=dict(census),
                     counts={key: counts[key] for key in COUNT_FIELDS}, histograms={k: {str(i): n for i, n in v.items()} for k, v in histograms.items()},
                     channels=channels, resources=monitor.data)
        sink.save_checkpoint(state)
    def should_stop():
        return ((stop_requested is not None and stop_requested()) or (output / 'stop.request').exists() or
                (stop_after_blocks is not None and state['source_checkpoint']['next_block_index'] >= stop_after_blocks) or
                (stop_after_groups is not None and census['complete_native_groups'] + census['unavailable_native_groups'] >= stop_after_groups))
    def suspended(stage):
        progress('stopped', stage, initial_parents=census['initial_parents'], resumable=True)
        return {'kind': KIND, 'status': 'stopped', 'source': dict(census), 'resumable': True}
    def start_native():
        nonlocal worker, native, channels
        cache = W.read(request).get('field_cache', {}).get('ref')
        estimated = 3 * (ROOT / cache).stat().st_size + 512 * 1024**2 if cache else 512 * 1024**2
        available = available_memory()
        monitor.data['native_start_memory_check'] = {'available_bytes': available,
            'estimated_initial_need_bytes': estimated,
            'scope': 'Three cached-state file sizes plus 512 MiB reserve, covering the measured 2.49 GB native peak; measured peaks are reported separately.'}
        if available is not None and available < estimated:
            return False
        progress('running', 'Loading the shared detector response', initial_parents=census['initial_parents'])
        worker = response.ResidentWorker(request, output / 'native-spool')
        ready = worker.start(); channels = ready['channels']
        environment = ready.get('environment')
        if state.get('native_environment') is not None and state['native_environment'] != environment:
            raise ValueError('Native runtime versions changed; retain the original acquisition environment')
        state['native_environment'] = environment
        monitor.pids['native'] = worker.process.pid
        native_path = output / 'native-scratch.sqlite'
        native = native_store.Store(native_path, {'request_sha256': mixed.file_sha(request)}, create=not native_path.exists())
        return True
    try:
        with monitor:
            while True:
                source = state['source_checkpoint']
                frontier = source['safe_frontier_ns']
                if source['finished']:
                    frontier = source['last_parent_time_ns'] + mixed.READOUT_TAIL_NS
                    state['live_time_ns'] = frontier
                if should_stop():
                    return suspended('Stopped at a durable acquisition checkpoint')
                row = sink.db.execute("SELECT ordinal,pending,input_sha256 FROM input_groups WHERE status='pending' AND onset_ns<? ORDER BY onset_ns,ordinal LIMIT 1", (frontier,)).fetchone()
                if row is not None:
                    ordinal, packed, digest = row
                    body = zlib.decompress(packed)
                    if hashlib.sha256(body).hexdigest() != digest:
                        raise ValueError('Queued delayed-deposit identity changed')
                    group = json.loads(body)
                    if worker is None:
                        if not start_native():
                            return suspended('Stopped before detector loading: insufficient available memory')
                    saved = worker.process_group(group, native)
                    _, signals = native.read(group['event_id'], group['group_id'], with_signals=True)
                    complete = digital.terminal_contacts_complete(saved)
                    with sink.transaction():
                        if not complete:
                            start = max(0., group['group_origin_time_ns'] - dual.POST_NS)
                            state['unknown_since_ns'] = min(start, state['unknown_since_ns']) if state['unknown_since_ns'] is not None else start
                            sink.db.execute('INSERT INTO native_failures VALUES (?,?)', (ordinal,
                                zlib.compress(native_store.encoded({'group': group, 'event': saved, 'native': signals}))))
                            census['unavailable_native_groups'] += 1
                        readout.advance(group['group_origin_time_ns'])
                        if complete:
                            readout.push(pulse.prepare_native(signals, channels, terminal_complete=True), group['group_origin_time_ns'], 1.)
                            census['complete_native_groups'] += 1
                        sink.db.execute('UPDATE input_groups SET status=?,pending=NULL WHERE ordinal=?', (saved['status'], ordinal))
                        checkpoint()
                    if not retain_validation_inputs:
                        with native.db:
                            native.db.execute('DELETE FROM events'); native.db.execute('DELETE FROM arrays')
                    continue
                if channels is not None or source['finished']:
                    if channels is None and not start_native():
                        return suspended('Stopped before detector loading: insufficient available memory')
                    with sink.transaction():
                        readout.advance(frontier)
                        checkpoint()
                if source['finished']:
                    with sink.transaction():
                        measured = readout.finalize(frontier)
                        census['delayed_groups_after_acquisition'] = sink.db.execute("SELECT count(*) FROM input_groups WHERE status='pending'").fetchone()[0]
                        sink.db.execute("UPDATE input_groups SET status='daughter_deposits_after_acquisition' WHERE status='pending'")
                        state['readout_statistics'] = measured
                        state['excluded_intervals_ns'] = ([] if state['unknown_since_ns'] is None else [[state['unknown_since_ns'], frontier]])
                        checkpoint()
                    if census['initial_parents'] != census['zero_deposit_parents'] + census['nonzero_parents']:
                        raise ValueError('Source denominator does not close')
                    completion = sink.finalize(acquisition_statistics={'source': dict(census), 'counts': state['counts'], 'readout': measured,
                        'live_time_ns': frontier, 'excluded_intervals_ns': state['excluded_intervals_ns']})
                    break
                if shutil.disk_usage(output).free < 1024**3:
                    return suspended('Stopped before the next source block: less than 1 GiB disk headroom')
                available = available_memory()
                if available is not None and available < 256 * 1024**2:
                    return suspended('Stopped before the next source block: low available memory')
                index = source['next_block_index']
                directory = output / 'transport' / f'b{index:06d}'
                W.write(output / 'source-checkpoint.json', source)
                progress('running', 'Generating the next joint-source block', initial_parents=census['initial_parents'], block_index=index)
                if not (directory / 'prepared.json').exists():
                    transport_call(['prepare-block', '--config', relative(output / 'source-config.json'),
                        '--checkpoint', relative(output / 'source-checkpoint.json'), '--output', relative(directory),
                        '--max-parents', str(block_parents)], output / 'transport.log')
                if not (directory / 'run.json').exists():
                    transport_call(['run-block', '--directory', relative(directory)], output / 'transport.log')
                if not (directory / 'stream/manifest.json').exists():
                    transport_call(['extract', '--directory', relative(directory)], output / 'transport.log')
                transport_call(['verify', '--directory', relative(directory)], output / 'transport.log')
                after = W.read(directory / 'checkpoint-after.json')
                with sink.transaction():
                    _ingest(sink, directory, after, census)
                    state['source_checkpoint'] = after
                    checkpoint()
                if not retain_validation_inputs:
                    _retire_block(output, directory)
        report = _write_report(output, identity, state, completion, monitor.data)
        completed = True
        progress('completed', 'Completed continuous candidate acquisition', resources=monitor.data)
        return report
    except BaseException as error:
        progress('failed', str(error), resumable=True, partial_data_retained=True)
        raise
    finally:
        if native is not None:
            native.close()
        if worker is not None:
            worker.close()
        sink.close()
        W.write(output / 'resources.json', monitor.data)
        if completed and not retain_validation_inputs and (output / 'native-scratch.sqlite').exists():
            mixed._retire_success_scratch(output, [output / 'native-scratch.sqlite'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--parents', type=int, default=100)
    parser.add_argument('--seed', type=int, default=20261120)
    parser.add_argument('--block-parents', type=int, default=50)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--stop-after-blocks', type=int)
    parser.add_argument('--stop-after-groups', type=int)
    parser.add_argument('--retain-validation-inputs', action='store_true')
    args = parser.parse_args()
    with W.execution_lease(ROOT):
        result = run(args.output, args.parents, args.seed, block_parents=args.block_parents,
            resume=args.resume, stop_after_blocks=args.stop_after_blocks,
            stop_after_groups=args.stop_after_groups,
            retain_validation_inputs=args.retain_validation_inputs)
    print(json.dumps({'status': result['status'], 'source': result['source']}))


if __name__ == '__main__':
    main()
