"""Joint-source transport, disk-backed delayed deposits and continuous readout.

Blocks are computational checkpoints, never separate physical acquisitions. The source
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
import time
import zlib

import numpy as np

import gegi_candidate_run as candidates
import gegi_candidate_storage as storage
import gegi_candidate_truth as truth
import gegi_campaign_response as response
import gegi_digital_readout as digital
import gegi_dual_source as dual
import gegi_event_store as native_store
import gegi_mixed_acquisition as mixed
from gegi_missing_history import MissingHistory, native_support_ns
import gegi_native_continuation as continuation
import gegi_stream_id_continuation as stream_ids
import gegi_pulse_stream as pulse
from gegi_resource_monitor import Monitor, TimerTotals, _linked, available_memory
from gegi_streaming_readout import StreamingReadout
import gegi_workflow as workflow
import scenario_workflow as W

ROOT = Path(__file__).resolve().parents[1]
KIND = 'gegi_streaming_acquisition_v1'
OWN_SOURCES = ('tools/gegi_streaming_acquisition.py', 'tools/gegi_streaming_readout.py',
               'tools/gegi_candidate_storage.py', 'tools/gegi_candidate_run.py', 'tools/gegi_candidate_truth.py',
               'tools/gegi_mixed_acquisition.py', 'tools/gegi_resource_monitor.py', 'tools/gegi_missing_history.py',
               'tools/gegi_native_continuation.py',
               'tools/gegi_stream_id_continuation.py',
               'transport/gegi_streaming_source.py', 'transport/gegi_source_inventory.py')
STARTUP_POLICY = 'new_parent_decays_empty_daughters_at_start'
STEADY_POLICY = 'secular_equilibrium_poisson_daughters_v1'
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


def source_config(name, count, seed, activities, positions, duration_s=None,
                  initial_state_policy=STARTUP_POLICY):
    config = {'kind': 'gegi_streaming_source_config_v1', 'acquisition_id': name,
        'seed': seed, 'clock_seed': seed, 'stop': {'mode': 'count', 'parent_count': count},
        'initial_state': {'policy': STARTUP_POLICY,
            'acquisition_start_ns': 0, 'initial_daughter_populations': {},
            'pre_acquisition_history': 'none', 'scope': 'startup acceptance, not secular equilibrium'},
        'sources': [{'id': sid, 'activity_Bq': rate, 'position_global_mm': list(position)}
            for sid, rate, position in zip((workflow.CS137, workflow.CO60), activities, positions, strict=True)]}
    if duration_s is not None:
        config['stop'] = {'mode': 'duration', 'duration_ns': duration_s * 1e9}
    if initial_state_policy == STEADY_POLICY:
        config['initial_state'] = {'policy': STEADY_POLICY, 'acquisition_start_ns': 0}
    return config


def producer_identity(config, request):
    return {'kind': KIND, 'source_config': config, 'native_request_sha256': mixed.file_sha(request),
        'candidate_truth_kind': truth.KIND,
        'environment': {'python': platform.python_version(), 'numpy': np.__version__, 'sqlite': sqlite3.sqlite_version},
        'source_sha256': {ref: mixed.file_sha(ROOT / ref) for ref in OWN_SOURCES},
        'readout_tail_ns': mixed.READOUT_TAIL_NS, 'scope': 'Fresh shared-clock bounded streaming acquisition.',
        'native_primary_count_semantics': 'Configured count for startup; expected new-parent count for duration. Actual census is measured separately.'}


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
        CREATE TABLE IF NOT EXISTS native_processing_phases (ordinal INTEGER PRIMARY KEY, phase INTEGER NOT NULL);
        INSERT OR IGNORE INTO native_processing_phases
          SELECT ordinal,0 FROM input_groups WHERE status NOT IN ('pending','daughter_deposits_after_acquisition');
    ''')


def _group_meta(group):
    parent = group['parent_event_metadata']
    return {'parent_decay_id': parent['parent_decay_id'], 'global_decay_id': group['event_id'],
        'new_parent_decay_id': parent.get('new_parent_decay_id', parent['parent_decay_id']),
        'initial_daughter_id': parent.get('initial_daughter_id'), 'origin': parent.get('origin', 'new_parent_decay'),
        'source_id': group['source_id'],
        'group_id': group['group_id'], 'first_ge_deposit_ns': group['group_origin_time_ns'],
        'last_ge_deposit_ns': max(row['time_ns'] for row in group['steps']),
        'positive_ge_energy_keV': sum(row['energy_keV'] for row in group['steps']),
        'raw_row_indices': [row['raw_row_index'] for row in group['steps']],
        'parent_event_metadata': group['parent_event_metadata']}


def _ingest(sink, directory, after, census, *, retain_truth=False):
    manifest_path = directory / 'stream/manifest.json'
    manifest = W.read(manifest_path)
    events = manifest_path.parent / manifest['events_file']
    manifest_hash = mixed.file_sha(manifest_path)
    if mixed.file_sha(events) != manifest['events_sha256']:
        raise ValueError('The completed source deposit stream changed')
    if retain_truth and manifest.get('candidate_photon_truth_kind') != truth.PHOTON_KIND:
        raise ValueError('This acquisition requires the scored Ge photon truth stream before retiring transport')
    event_count = 0
    with events.open(encoding='utf-8') as handle:
        for line in handle:
            event = mixed.absolute_event(json.loads(line))
            if retain_truth:
                truth.store_event(sink.db, event, manifest, manifest_hash)
                event_count += 1
            for group in mixed.native_groups(event):
                meta = _group_meta(group)
                body = native_store.encoded(group)
                sink.db.execute('INSERT INTO input_groups(parent,group_id,onset_ns,last_ns,status,metadata,pending,input_sha256) VALUES (?,?,?,?,?,?,?,?)',
                    (group['event_id'], group['group_id'], meta['first_ge_deposit_ns'], meta['last_ge_deposit_ns'],
                     'pending', native_store.encoded(meta), zlib.compress(body), hashlib.sha256(body).hexdigest()))
                census['deposit_groups'] += 1
    counts = manifest['counts']
    if retain_truth and event_count != counts['nonzero_primaries']:
        raise ValueError('Staged photon truth does not close against the original positive-deposit transport census')
    census['transport_primaries'] += manifest['primary_count']
    census['initial_parents'] += counts.get('new_parent_primaries', manifest['primary_count'])
    census['initial_daughter_decays'] += counts.get('initial_daughter_primaries', 0)
    census['zero_deposit_parents'] += counts.get('zero_deposit_parents', counts['zero_deposit_primaries'])
    census['nonzero_parents'] += counts.get('nonzero_parents', counts['nonzero_primaries'])
    for key in ('zero_deposit_initial_daughters', 'nonzero_initial_daughters'):
        census[key] += counts.get(key, 0)
    sink.db.execute('INSERT INTO source_blocks VALUES (?,?,?,?)',
        (after['next_block_index'] - 1, native_store.encoded(manifest), manifest_hash, native_store.encoded(after)))


def _retire_block(output, directory, *, retain_truth=False):
    receipt = directory / 'candidate-retention.json'
    if (directory / 'retired-artifacts.json').exists():
        return
    if not receipt.exists():
        candidates.write_new(receipt, {'kind': 'gegi_streaming_source_consumer_receipt_v1', 'status': 'committed',
            'block_index': W.read(directory / 'checkpoint-after.json')['next_block_index'] - 1,
            'source_manifest_sha256': mixed.file_sha(directory / 'stream/manifest.json'),
            'checkpoint_after_sha256': mixed.file_sha(directory / 'checkpoint-after.json'),
            'database_ref': (output / storage.ARCHIVE_NAME).relative_to(ROOT).as_posix(),
            **({'candidate_truth_scratch_ref': (output / truth.SCRATCH).relative_to(ROOT).as_posix()}
               if retain_truth else {})})
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
    artifacts = [database]
    truth_retention = {'status': 'unavailable_legacy',
                       'scope': 'Readout context ordinals alone cannot identify the initiating photon or recreate retired steps.'}
    if identity.get('candidate_truth_kind') == truth.KIND:
        target = output / truth.ARTIFACT
        truth_retention = truth.publish(database, output / truth.SCRATCH, target, identity)
        artifacts.append(target)
    ledger = output / 'input-groups.jsonl.gz'
    if not ledger.exists():
        def export(handle):
            with gzip.GzipFile(fileobj=handle, mode='wb', mtime=0) as zipped, closing(sqlite3.connect(database)) as db:
                for ordinal, status, body, phase in db.execute('SELECT g.ordinal,g.status,g.metadata,p.phase FROM input_groups g LEFT JOIN native_processing_phases p ON p.ordinal=g.ordinal ORDER BY g.ordinal'):
                    zipped.write(native_store.encoded({'input_group_ordinal': ordinal, 'status': status,
                        'native_processing_phase': phase, **json.loads(body)}) + b'\n')
        dual._publish_artifact(ledger, export)
    artifacts.append(ledger)
    histograms = {name: Counter({int(k): v for k, v in values.items()}) for name, values in state['histograms'].items()}
    report = {'kind': candidates.KIND, 'status': 'completed', 'identity': identity,
        'selection_policy': storage.POLICY, 'source': state['census'], 'counts': state['counts'],
        'storage_counts': {key: completion[key] for key in ('observed_coincident_rises', 'saved_candidates',
            'rejected_rises', 'selection_reason_counts')},
        'readout': state['readout_statistics'], 'spectra': _spectra(histograms),
        'live_time_ns': state['live_time_ns'], 'excluded_intervals_ns': state['excluded_intervals_ns'],
        'verification': verification, 'resources': resources, 'stage_timings': state.get('stage_timings'),
        'first_native_group_seconds_per_session': state.get('first_native_group_seconds_per_session', []),
        'missing_history_statistics': state.get('missing_history_statistics'),
        'execution_provenance': state.get('execution_provenance'),
        'stage_timing_baselines_by_native_phase': state.get('phase_timing_baselines'),
        'source_initial_state': state['source_checkpoint'].get('initial_inventory', identity['source_config']['initial_state']),
        'electronics_initial_state': 'Quiet zero state at t=0; stationary noise starts at acquisition t=0.',
        'software': {'readout': identity.get('environment'), 'native': state.get('native_environment')},
        'artifacts': {p.name: {'bytes': p.stat().st_size, 'sha256': mixed.file_sha(p)} for p in artifacts},
        'retention': {'full_adc_stream_saved': False, 'native_inputs_saved_here': False,
            'candidate_signals': 'Exact all-34-electrode ADC contexts and fast/slow/timing measurements.',
            'truth_association': 'One-based input_groups ordinals; diagnostic association only, not event selection.',
            'candidate_truth': truth_retention,
            'delayed_deposits': 'Disk-backed original groups beyond the acquisition remain explicitly censored.',
            'native_failure_policy': ('Preserve exact failures and finite summed two-pole unavailable-history bounds.'
                if state.get('missing_history') is not None else
                'Preserve exact failure and conservatively mark subsequent startup history unknown.')},
        'limitations': [('Steady nuclear inventory; electronics start from quiet zero state.'
                         if identity['source_config']['initial_state']['policy'] == STEADY_POLICY else
                         'Bounded startup acceptance with no pre-existing daughter inventory.'),
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
        positions_mm=((-40, 0, 40), (40, 0, 40)), on_progress=None, *, block_parents=None,
        resume=False, stop_requested=None, stop_after_blocks=None, stop_after_groups=None,
        retain_validation_inputs=False, duration_s=None, initial_state_policy=STARTUP_POLICY):
    output = Path(output).resolve()
    if not output.is_relative_to((ROOT / '.local').resolve()) or output == (ROOT / '.local').resolve():
        raise ValueError('Use an owned acquisition directory under this project .local')
    if duration_s is not None and (type(duration_s) not in (int, float) or not math.isfinite(duration_s) or duration_s <= 0):
        raise ValueError('Physical acquisition duration must be a positive finite number.')
    if initial_state_policy not in (STARTUP_POLICY, STEADY_POLICY):
        raise ValueError('Unknown nuclear source initial-state policy')
    if initial_state_policy == STEADY_POLICY and duration_s is None:
        raise ValueError('Steady inventory requires an explicit physical acquisition duration')
    if duration_s is None and (type(primary_count) is not int or primary_count <= 0):
        raise ValueError('Initial parent count must be a positive integer.')
    if block_parents is None:
        block_parents = 500 if duration_s is not None else 50
    if type(block_parents) is not int or block_parents <= 0:
        raise ValueError('Source block size must be a positive integer.')
    if any(_linked(p) for p in (output, *output.parents) if p.is_relative_to(ROOT)):
        raise ValueError('Linked acquisition directory refused')
    config = source_config(output.name, primary_count, seed, activities_bq, positions_mm, duration_s, initial_state_policy)
    duration_ns = None if duration_s is None else duration_s * 1e9
    state = None
    def progress(status, stage, **fields):
        saved_census = (state or {}).get('census', {})
        source = (state or {}).get('source_checkpoint', {})
        value = {'status': status, 'stage': stage, 'duration_s': duration_s,
            'acquisition_time_ns': ((state or {}).get('readout') or {}).get('input_watermark_ns', 0),
            'source_time_ns': source.get('safe_frontier_ns', 0),
            'new_parent_decays': saved_census.get('initial_parents', 0),
            'initial_daughter_decays': saved_census.get('initial_daughter_decays', 0), **fields}
        W.write(output / 'progress.json', value)
        if on_progress:
            on_progress(value)
    if resume:
        if W.read(output / 'source-config.json') != config:
            raise ValueError('Resume requires the original sources, seed, count and source state')
        request = output / ('stream-id-repair/native-request.json' if (output / 'stream-id-continuation.json').exists()
                            else 'native-only/native-request.json' if (output / 'native-only-continuation.json').exists()
                            else 'native-request.json')
    else:
        if output.exists() and any(output.iterdir()):
            raise FileExistsError('Choose a fresh name or explicitly resume the existing acquisition')
        output.mkdir(parents=True, exist_ok=True)
        candidates.write_new(output / 'source-config.json', config)
        # Native primary_count configures legacy readout metadata, not a physical
        # source denominator. Duration counts are measured only by transport census.
        nominal_count = primary_count if duration_s is None else max(1, math.ceil(sum(activities_bq) * duration_s))
        request = mixed.native_request(output, nominal_count, response_mode='native_signals_only_v1',
            **({'event_id_policy': 'streaming_transport_driver_v1'} if duration_s is not None else {}))
    current_identity = producer_identity(config, request)
    active = (stream_ids.admit(output, current_identity) or continuation.admit(output, current_identity)) if resume else None
    identity = active['original_identity'] if active is not None else current_identity
    retain_truth = identity.get('candidate_truth_kind') == truth.KIND
    truth_scratch = output / truth.SCRATCH
    if retain_truth and _linked(truth_scratch):
        raise ValueError('Linked candidate truth scratch refused')
    spool_path = Path(active['active_spool']) if active is not None else output / 'native-spool'
    native_path = Path(active['active_store']) if active is not None else output / 'native-scratch.sqlite'
    native_phase = active.get('native_phase', 1) if active is not None else 0
    if resume and (output / candidates.REPORT_NAME).exists():
        report = W.read(output / candidates.REPORT_NAME)
        if report['identity'] != identity:
            raise ValueError('Completed acquisition producer changed')
        candidates.verify_candidates(output / storage.ARCHIVE_NAME)
        if retain_truth:
            truth_path = W.safe_path(output, truth.ARTIFACT)
            binding = report['artifacts'].get(truth.ARTIFACT, {})
            retention = report.get('retention', {}).get('candidate_truth', {})
            if (retention.get('status') != 'verified_exact' or not truth_path.is_file()
                    or truth_path.stat().st_size != binding.get('bytes') or mixed.file_sha(truth_path) != binding.get('sha256')):
                raise ValueError('Completed acquisition candidate truth is missing or differs from its verified artifact')
        return report
    database = output / storage.ARCHIVE_NAME
    if resume and database.exists():
        sealed = _sealed_state(database, identity)
        if sealed is not None:
            state, completion = sealed
            resources = W.read(output / 'resources.json') if (output / 'resources.json').exists() else state['resources']
            report = _write_report(output, identity, state, completion, resources)
            if retain_truth and not retain_validation_inputs:
                mixed._retire_success_scratch(output, [native_path, truth_scratch])
            progress('completed', 'Recovered the completed acquisition report', resources=resources)
            return report
        stop_marker = output / 'stop.request'
        if _linked(stop_marker):
            raise ValueError('Linked stop marker refused')
        stop_marker.unlink(missing_ok=True)
    sink = storage.CandidateStore(database, identity, resume=resume and database.exists())
    try:
        _schema(sink)
        if retain_truth:
            truth.attach(sink.db, truth_scratch)
    except BaseException:
        sink.close()
        raise
    worker = native = None
    completed = False
    state = sink.load_checkpoint() if resume else None
    if state is None:
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
    receipt_path = active.get('receipt_path', 'native-only-continuation.json') if active is not None else None
    state['execution_provenance'] = {'active_producer_identity': current_identity,
        'native_processing_phase': native_phase,
        'continuation_receipt': ({'path': receipt_path,
            'sha256': mixed.file_sha(output / receipt_path)} if active is not None else None)}
    census, counts = Counter(state['census']), Counter(state['counts'])
    histograms = {name: Counter({int(k): v for k, v in values.items()}) for name, values in state['histograms'].items()}
    readout = None
    channels = state['channels']
    worker_group_count = 0
    last_progress = time.perf_counter()
    native_support = native_support_ns(response.read(request)['numerics'])
    missing = (MissingHistory.restore(state['missing_history'], native_support_ns=native_support)
               if state.get('missing_history') is not None else
               MissingHistory(duration_ns, native_support_ns=native_support) if duration_ns is not None else None)

    def observe(event, context):
        card = dual._trigger_card(event, dual._strip_neighbors(channels), geometry=channels)
        reason = context['readout_rejection_reason']
        if missing is not None and missing.contains(event['rise_end_ns'], trigger_time_ns=event['trigger_time_ns']):
            reason = 'unknown_native_history'
        elif missing is None and state['unknown_since_ns'] is not None and event['rise_end_ns'] >= state['unknown_since_ns']:
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
        observed = sink.observe(card, context, event=event, identities=related, rejection_reason=reason)
        if retain_truth and observed['decision'] == 'candidate':
            truth.link_candidate(sink.db, observed['trigger_id'], related)

    readout = (StreamingReadout.restore(state['readout'], on_readout_context=observe) if state['readout'] else
               StreamingReadout(noise_seed=seed + 100000000, live_time_ns=duration_ns, on_readout_context=observe))
    timers = TimerTotals(state.get('stage_timings'))
    state.setdefault('phase_timing_baselines', {}).setdefault(str(native_phase), timers.snapshot())
    previous_resources = W.read(output / 'resources.json') if resume and (output / 'resources.json').exists() else state.get('resources')
    monitor = Monitor(output, previous_resources)
    def checkpoint():
        counts['qualified_energies'] = counts['single_pixel_energies'] + counts['additional_multi_strip_energies']
        counts['triggers_without_energy'] = counts['qualified_triggers'] - counts['qualified_energies']
        state.update(readout=readout.checkpoint(), census=dict(census), stage_timings=timers.snapshot(),
                     missing_history=None if missing is None else missing.checkpoint(),
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
        worker = response.ResidentWorker(request, spool_path)
        with timers.measure('native_worker_load'):
            ready = worker.start()
        channels = ready['channels']
        environment = ready.get('environment')
        if state.get('native_environment') is not None and state['native_environment'] != environment:
            raise ValueError('Native runtime versions changed; retain the original acquisition environment')
        state['native_environment'] = environment
        monitor.pids['native'] = worker.process.pid
        native = native_store.Store(native_path, {'request_sha256': mixed.file_sha(request)}, create=not native_path.exists())
        progress('running', 'Processing continuous detector signals', native_processing_phase=native_phase)
        return True
    try:
        with monitor:
            while True:
                source = state['source_checkpoint']
                frontier = source['safe_frontier_ns']
                if source['finished']:
                    frontier = duration_ns if duration_ns is not None else source['last_parent_time_ns'] + mixed.READOUT_TAIL_NS
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
                    native_started = time.perf_counter()
                    with timers.measure('native_group'):
                        saved = worker.process_group(group, native)
                        _, signals = native.read(group['event_id'], group['group_id'], with_signals=True)
                    if worker_group_count == 0:
                        state.setdefault('first_native_group_seconds_per_session', []).append(time.perf_counter()-native_started)
                    worker_group_count += 1
                    complete = digital.terminal_contacts_complete(saved)
                    timers.record_native('completed' if complete else 'failed' if saved['status'] == 'native_failed' else 'unavailable')
                    with sink.transaction():
                        if retain_truth:
                            truth.store_response(sink.db, ordinal, group, saved, native_phase)
                        if not complete:
                            if missing is not None:
                                missing.add(group['group_origin_time_ns'], max(s['time_ns'] for s in group['steps']),
                                            math.fsum(s['energy_keV'] for s in group['steps']))
                            else:
                                start = max(0., group['group_origin_time_ns'] - dual.POST_NS)
                                state['unknown_since_ns'] = min(start, state['unknown_since_ns']) if state['unknown_since_ns'] is not None else start
                            sink.db.execute('INSERT INTO native_failures VALUES (?,?)', (ordinal,
                                zlib.compress(native_store.encoded({'group': group, 'event': saved, 'native': signals}))))
                            census['unavailable_native_groups'] += 1
                        with timers.measure('readout'):
                            # Classify later native input before committing any
                            # trigger whose feature window could include it.
                            readout.advance(max(0., group['group_origin_time_ns'] - dual.POST_NS)
                                            if missing is not None else group['group_origin_time_ns'])
                            if complete:
                                readout.push(pulse.prepare_native(signals, channels, terminal_complete=True), group['group_origin_time_ns'], 1.)
                                census['complete_native_groups'] += 1
                        sink.db.execute('UPDATE input_groups SET status=?,pending=NULL WHERE ordinal=?', (saved['status'], ordinal))
                        sink.db.execute('INSERT INTO native_processing_phases VALUES (?,?)', (ordinal, native_phase))
                        with timers.measure('checkpoint'):
                            checkpoint()
                    if not retain_validation_inputs:
                        with native.db:
                            native.db.execute('DELETE FROM events'); native.db.execute('DELETE FROM arrays')
                    if time.perf_counter() - last_progress >= 1:
                        progress('running', 'Processing continuous detector signals',
                            complete_native_groups=census['complete_native_groups'],
                            unavailable_native_groups=census['unavailable_native_groups'],
                            native_processing_phase=native_phase)
                        last_progress = time.perf_counter()
                    continue
                if channels is not None or source['finished']:
                    if channels is None and not start_native():
                        return suspended('Stopped before detector loading: insufficient available memory')
                    with sink.transaction():
                        with timers.measure('readout'):
                            readout.advance(max(0., frontier - dual.POST_NS)
                                            if missing is not None and not source['finished'] else frontier)
                        with timers.measure('checkpoint'):
                            checkpoint()
                if source['finished']:
                    with sink.transaction():
                        with timers.measure('readout'):
                            measured = readout.finalize(frontier)
                        census['delayed_groups_after_acquisition'] = sink.db.execute("SELECT count(*) FROM input_groups WHERE status='pending'").fetchone()[0]
                        sink.db.execute("UPDATE input_groups SET status='daughter_deposits_after_acquisition' WHERE status='pending'")
                        state['readout_statistics'] = measured
                        state['excluded_intervals_ns'] = (missing.intervals(frontier) if missing is not None else
                            [] if state['unknown_since_ns'] is None else [[state['unknown_since_ns'], frontier]])
                        state['missing_history_statistics'] = None if missing is None else missing.statistics()
                        checkpoint()
                    if census['initial_parents'] != census['zero_deposit_parents'] + census['nonzero_parents']:
                        raise ValueError('Source denominator does not close')
                    if (census['initial_daughter_decays'] != census['zero_deposit_initial_daughters'] + census['nonzero_initial_daughters'] or
                            census['transport_primaries'] != census['initial_parents'] + census['initial_daughter_decays']):
                        raise ValueError('Initial daughter and transport-root denominators do not close')
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
                with timers.measure('transport_cli'):
                    transport_call(['process-block', '--config', relative(output / 'source-config.json'),
                        '--checkpoint', relative(output / 'source-checkpoint.json'), '--output', relative(directory),
                        '--max-parents', str(block_parents), *(['--candidate-truth'] if retain_truth else [])], output / 'transport.log')
                after = W.read(directory / 'checkpoint-after.json')
                run_receipt = W.read(directory / 'run.json')
                if 'elapsed_seconds' in run_receipt:
                    timers.record('transport_run', run_receipt['elapsed_seconds'])
                with sink.transaction():
                    _ingest(sink, directory, after, census, retain_truth=retain_truth)
                    state['source_checkpoint'] = after
                    checkpoint()
                if not retain_validation_inputs:
                    with timers.measure('transport_cli'):
                        _retire_block(output, directory, retain_truth=retain_truth)
                progress('running', 'Joint-source block committed', block_index=index,
                         stage_timings=timers.snapshot(), resources=monitor.data)
        with timers.measure('export'):
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
        W.write(output / 'stage-timings.json', timers.snapshot())
        if completed and not retain_validation_inputs:
            scratch = [native_path, truth_scratch] if retain_truth else [native_path]
            if any(path.exists() for path in scratch):
                mixed._retire_success_scratch(output, scratch)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--parents', type=int, default=100)
    parser.add_argument('--duration-s', type=float)
    parser.add_argument('--initial-state-policy', choices=(STARTUP_POLICY, STEADY_POLICY), default=STARTUP_POLICY)
    parser.add_argument('--seed', type=int, default=20261120)
    parser.add_argument('--block-parents', type=int)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--stop-after-blocks', type=int)
    parser.add_argument('--stop-after-groups', type=int)
    parser.add_argument('--retain-validation-inputs', action='store_true')
    args = parser.parse_args()
    with W.execution_lease(ROOT):
        result = run(args.output, args.parents, args.seed, block_parents=args.block_parents,
            resume=args.resume, stop_after_blocks=args.stop_after_blocks,
            stop_after_groups=args.stop_after_groups,
            retain_validation_inputs=args.retain_validation_inputs, duration_s=args.duration_s,
            initial_state_policy=args.initial_state_policy)
    print(json.dumps({'status': result['status'], 'source': result['source']}))


if __name__ == '__main__':
    main()
