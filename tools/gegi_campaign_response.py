"""Bounded resident GeGI response and transactional sparse campaign storage.

No command implicitly calibrates or launches transport. Completed group inputs,
native arrays, scalar readout and cone hypotheses remain identity-bound in SQLite.
"""
from __future__ import annotations
import argparse
import collections
import copy
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys

import gegi_event_store as S
import gegi_imaging as I
import scenario_workflow as W
from local_ui_jobs import process_identity

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = 'gegi_campaign_response_protocol_v1'
HORIZON_NS = 100000
MAX_JSON_BYTES = 100_000_000
require = S.require


def read(path):
    path = Path(path)
    require(path.is_file() and path.stat().st_size <= MAX_JSON_BYTES, 'Missing or oversized JSON')
    return json.loads(path.read_text(encoding='utf-8-sig'))


def file_sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def bound_file(binding):
    path = Path(binding['ref'])
    path = path if path.is_absolute() else ROOT/path
    require(path.resolve().is_relative_to(ROOT.resolve()) and file_sha(path) == binding['sha256'],
            'Pinned project artifact changed')
    return path


def write(path, value):
    W.write(Path(path), value)


def pulse_groups(event, source_id, context):
    """Retain the transport's exact anchored-window assignment and original rows."""
    steps = event['steps']
    require(isinstance(steps, list) and 0 < len(steps) <= 100000, 'Sparse event requires bounded positive rows')
    require(all(s['energy_keV'] > 0 for s in steps), 'Zero input belongs only in the primary census')
    rows = {s['raw_row_index']: s for s in steps}
    require(len(rows) == len(steps), 'Duplicate transport raw row')
    if 'pulse_groups' in event:
        transport = str(ROOT/'transport')
        if transport not in sys.path:
            sys.path.insert(0, transport)
        import cs137
        groups = event['pulse_groups']
        cs137.validate_group_map(steps, groups, HORIZON_NS)
        finite = True
    else:
        require('global_decay_id' not in event, 'Decay event is missing its original pulse grouping')
        groups = [{'group_id': 0, 'origin_time_ns': min(s['time_ns'] for s in steps),
                   'row_indices': [s['raw_row_index'] for s in steps]}]
        finite = False
    metadata = {k: v for k, v in event.items() if k not in ('steps', 'pulse_groups')}
    parent_time = event.get('primary_time_ns', event.get('vertex', {}).get('time'))
    require(I.finite(parent_time) and parent_time >= 0, 'Missing original primary vertex time in ns')
    for group in groups:
        selected = [rows[i] for i in group['row_indices']]
        result = {'event_id': event['event_id'], 'group_id': group['group_id'],
                  'primary_time_ns': parent_time, 'group_origin_time_ns': group['origin_time_ns'],
                  'horizon_ns': HORIZON_NS if finite else None, 'steps': selected,
                  'pulse_group': group, 'parent_event_metadata': metadata, 'source_id': source_id,
                  **context}
        for key in ('global_decay_id', 'initial_primary_id', 'root'):
            if key in event:
                result[key] = event[key]
        yield result


def readout_summary(event):
    """Fixed-calibration face sums; opposite faces are averaged, never added."""
    result = {'accepted': False, 'energy_keV': None, 'x_energy_keV': None, 'y_energy_keV': None,
              'significant_collecting_channel_ids': [], 'reason': None,
              'scope': 'All above-threshold collecting channels, including guards; imaging separately vetoes guards.'}
    channels = event.get('channels')
    if event.get('status') != 'completed' or not isinstance(channels, list):
        result['reason'] = 'native_response_incomplete'
        return result
    hits = [c for c in channels if c.get('collection_candidate') is True]
    result['significant_collecting_channel_ids'] = [c['contact_id'] for c in hits]
    if any(c.get('accepted') is not True or not I.finite(c.get('reconstructed_energy_keV')) for c in hits):
        result['reason'] = 'collecting_channel_readout_rejected'
        return result
    xs = [c for c in hits if 1 <= c['contact_id'] <= 17]
    ys = [c for c in hits if 18 <= c['contact_id'] <= 34]
    if not xs or not ys:
        result['reason'] = 'requires_collection_on_both_faces'
        return result
    ex = sum(c['reconstructed_energy_keV'] for c in xs)
    ey = sum(c['reconstructed_energy_keV'] for c in ys)
    result.update(accepted=True, energy_keV=(ex+ey)/2, x_energy_keV=ex, y_energy_keV=ey,
                  face_energy_difference_keV=ex-ey)
    return result


def verify_store_roundtrip(store, primary_id, group_id, event, signals, input_sha256):
    require(store.has(primary_id, group_id, input_sha256), 'Group transaction missing after append')
    saved, native = store.read(primary_id, group_id, with_signals=True)
    if signals is None:
        require(native is None and saved['channels'] is None, 'Unknown native response was fabricated')
    else:
        require(set(native) == set(signals), 'Stored channel census changed')
        for channel in event['channels']:
            other = next(c for c in saved['channels'] if c['contact_id'] == channel['contact_id'])
            require(other['derived_trace_sha256'] == S.trace_hash(channel['trace']), 'Stored electronics trace identity changed')
            require({k: v for k, v in other.items() if k != 'derived_trace_sha256'} ==
                    {k: v for k, v in channel.items() if k != 'trace'}, 'Stored scalar channel changed')
        for contact in signals:
            for key, values in signals[contact].items():
                actual = native[contact][key]
                require(struct.pack('<'+'d'*len(values), *values) == struct.pack('<'+'d'*len(actual), *actual),
                        'Stored native Float64 bits changed')
    for key, value in event.items():
        if key not in ('channels', 'signals_ref', 'signals_sha256'):
            require(saved[key] == value, 'Stored event metadata changed: '+key)
    return saved


def verify_replayed_channels(saved_event, replay):
    """Exact scalar and trace-hash comparison after real shared-electronics replay."""
    expected = saved_event['channels']
    require(replay.get('drift_executed') is False, 'Replay must not rerun drift')
    actual = {c['contact_id']: c for c in replay['channels']}
    require(set(actual) == {c['contact_id'] for c in expected}, 'Replay channel census changed')
    for channel in expected:
        result = actual[channel['contact_id']]
        trace_digest = channel.get('derived_trace_sha256', S.trace_hash(channel['trace']) if 'trace' in channel else None)
        require(trace_digest == S.trace_hash(result['trace']), 'Electronics replay trace mismatch')
        scalars = {k: v for k, v in channel.items() if k not in ('trace', 'derived_trace_sha256')}
        require(S.encoded(scalars) == S.encoded({k: v for k, v in result.items() if k != 'trace'}),
                'Electronics replay scalar mismatch')
    return {'status': 'verified_exact', 'channels': len(expected), 'drift_executed': False,
            'trace_and_scalar_policy': 'Exact canonical trace SHA256 and scalar JSON equality'}


class ResidentWorker:
    def __init__(self, request_path, spool_root):
        self.request_path = Path(request_path).resolve()
        self.spool = Path(spool_root).resolve()
        require(self.spool.is_relative_to((ROOT/'.local').resolve()) and self.spool != (ROOT/'.local').resolve(),
                'Resident spool must be below project .local')
        self.request = read(self.request_path)
        self.request_sha256 = file_sha(self.request_path)
        self.process = None
        self.ready = None
        self.request_id = 0
        self._lock = self._log = None

    def _check_previous_process(self):
        path = self.spool/'worker-process.json'
        if not path.exists():
            return
        previous = read(path)
        require(previous.get('status') != 'launching', 'Unresolved prior native launch requires inspection')
        pid = previous.get('pid')
        require(type(pid) is int and pid > 0, 'Unknown prior native process requires inspection')
        actual = process_identity(pid)
        require(actual is None or (actual != 'unknown' and
                previous.get('process_start_identity') not in (None, 'unknown', 'live') and
                actual != previous['process_start_identity']), 'Prior native worker is live or unknown')

    def start(self):
        require(self.process is None, 'Resident worker already started')
        require(self.request['kind'] == 'gegi_campaign_response_request_v1' and
                self.request['numerics']['field_policy'] == 'reuse-only' and self.request.get('field_cache'),
                'Resident response requires pinned reuse-only fields')
        self.spool.mkdir(parents=True, exist_ok=True)
        require(not self.spool.is_symlink(), 'Linked spool refused')
        identity = {'kind': PROTOCOL, 'request_sha256': self.request_sha256,
                    'adapter_sha256': file_sha(__file__)}
        path = self.spool/'adapter-identity.json'
        if path.exists():
            require(read(path) == identity, 'Adapter spool identity changed')
        else:
            require(not any(self.spool.iterdir()), 'New adapter spool must be empty')
            write(path, identity)
        self._lock = (self.spool/'resident.lock').open('a+b')
        self._lock.seek(0)
        if self._lock.read(1) == b'':
            self._lock.write(b'0');self._lock.flush()
        self._lock.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self._lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._check_previous_process()
            env = W.child_env(self.request['selection']['threads'])
            self._log = (self.spool/'worker-stderr.log').open('ab')
            write(self.spool/'worker-process.json', {'status': 'launching', 'request_sha256': self.request_sha256})
            self.process = subprocess.Popen([env['JULIA_EXE'], '--startup-file=no',
                '--threads='+str(self.request['selection']['threads']), '--project='+str(ROOT/'simulation'),
                str(ROOT/'simulation/gegi_campaign_response.jl'), '--request', str(self.request_path), '--spool', str(self.spool)],
                cwd=ROOT, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._log,
                text=True, encoding='utf-8', bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            write(self.spool/'worker-process.json', {'status': 'running', 'pid': self.process.pid,
                  'process_start_identity': process_identity(self.process.pid), 'request_sha256': self.request_sha256})
            self.ready = self._receive()
            require(self.ready['status'] == 'ready' and self.ready['request_sha256'] == self.request_sha256 and
                    self.ready['new_field_solve'] is False and
                    self.ready['field_cache_sha256'] == self.request['field_cache']['sha256'], 'Resident readiness identity mismatch')
            return self.ready
        except BaseException:
            self.close()
            raise

    def _receive(self):
        line = self.process.stdout.readline(MAX_JSON_BYTES+1)
        require(bool(line) and len(line.encode('utf-8')) <= MAX_JSON_BYTES and line.endswith('\n'),
                'Resident worker ended or returned an oversized/incomplete record; retained stderr explains the failure')
        response = json.loads(line)
        require(response.get('protocol') == PROTOCOL, 'Unexpected resident protocol output')
        require(response.get('status') != 'error', 'Resident worker failed: '+str(response.get('error')))
        return response

    def command(self, name, **fields):
        require(self.process is not None and self.process.poll() is None, 'Resident worker is unavailable')
        self.request_id += 1
        payload = {'command': name, 'request_id': self.request_id, **fields}
        self.process.stdin.write(S.encoded(payload).decode('utf-8')+'\n');self.process.stdin.flush()
        response = self._receive()
        require(response['request_id'] == self.request_id, 'Resident command identity changed')
        return response

    def calibrate(self, output, *, max_new_injections=None, resume=False):
        if resume:
            stop = self.spool/'calibration-stop.request'
            require(not stop.is_symlink(), 'Linked stop marker refused')
            stop.unlink(missing_ok=True)
        return self.command('calibrate', output=str(Path(output).resolve()), max_new_injections=max_new_injections)

    def request_calibration_stop(self):
        (self.spool/'calibration-stop.request').touch(exist_ok=True)

    def _spool_paths(self, receipt, input_sha256):
        stem = 'g-'+input_sha256
        expected = {'event_path': self.spool/(stem+'.json'), 'input_path': self.spool/(stem+'-input.json'),
                    'receipt_path': self.spool/(stem+'-receipt.json'), 'signals_path': self.spool/(stem+'-signals.csv')}
        for key, target in expected.items():
            if receipt.get(key) is None and key == 'signals_path':
                continue
            require(Path(receipt[key]).resolve() == target and target.is_file() and not target.is_symlink(),
                    'Unowned or linked native spool path')
        return expected

    def process_group(self, group, store, *, calibration=None, photopeak_windows=None, calibration_sha256=None):
        body = S.encoded(group)
        digest = S.sha(body)
        primary_id, group_id = group['event_id'], group['group_id']
        if store.has(primary_id, group_id, digest):
            return store.read(primary_id, group_id)[0]
        receipt = self.command('process', group_json=body.decode('utf-8'), input_sha256=digest)
        require(receipt['input_sha256'] == digest and receipt['event_id'] == primary_id and receipt['group_id'] == group_id,
                'Native group identity changed')
        paths = self._spool_paths(receipt, digest)
        require(file_sha(paths['event_path']) == receipt['event_sha256'], 'Native event spool changed')
        event = read(paths['event_path'])
        require(event['input_group'] == group and event['input_event_sha256'] == digest, 'Original group provenance changed')
        native = None
        if receipt['signals_path'] is not None:
            require(file_sha(paths['signals_path']) == receipt['signals_sha256'], 'Native signal spool changed')
            native = S.native_csv(paths['signals_path'], event['channels'])
        require((event['status'] == 'native_failed') == (native is None), 'Unknown native signals must remain null')
        event['readout_summary'] = readout_summary(event)
        if calibration is not None:
            event['reconstruction'] = I.reconstruct_event(event, self.ready['channels'], calibration, photopeak_windows)
            event['calibration_sha256'] = calibration_sha256
            event['photopeak_windows_sha256'] = S.sha(S.encoded(photopeak_windows))
        event['readout_recipe_sha256'] = S.sha(S.encoded(self.recipe()))
        store.append(primary_id, group_id, event, native, digest)
        saved = verify_store_roundtrip(store, primary_id, group_id, event, native, digest)
        if event['status'] != 'native_failed':
            # Exact, owned regular files only; no directory deletion or recursion.
            for path in paths.values():
                require(path.parent == self.spool and path.is_file() and not path.is_symlink(), 'Spool changed before deletion')
            for path in paths.values():
                path.unlink()
        return saved

    def recipe(self):
        require(self.ready is not None, 'Resident recipe unavailable')
        return {k: self.ready[k] for k in ('channels', 'readout_config', 'electronics_calibration',
                                          'ionisation_energy_eV', 'drift_dt_ns', 'source_code_sha256')}

    def verify_saved_group(self, store, primary_id, group_id):
        event, native = store.read(primary_id, group_id, with_signals=True)
        require(native is not None, 'No electronics waveform exists for a native failure')
        request = {**self.recipe(), 'native_signals': native, 'horizon_ns': event.get('readout_horizon_ns')}
        digest = S.sha(S.encoded(request))
        path = self.spool/('replay-input-'+digest+'.json')
        write(path, request)
        result = self.command('replay', input_ref=str(path), input_sha256=file_sha(path))
        output = Path(result['output_path']).resolve()
        require(output.parent == self.spool and output.name == 'replay-'+file_sha(path)+'.json' and
                not output.is_symlink() and file_sha(output) == result['output_sha256'], 'Unowned/changed replay output')
        verified = verify_replayed_channels(event, read(output))
        verified.update(event_id=primary_id, group_id=group_id, native_input_sha256=digest,
                        readout_recipe_sha256=S.sha(S.encoded(self.recipe())))
        # Successful replay is fully summarized by exact identities in the receipt.
        output.unlink();path.unlink()
        return verified

    def run_chunk(self, manifest_path, store_path, store_identity, *, calibration, photopeak_windows, receipt_path,
                  prior_recipe_provenance=None):
        manifest_path = Path(manifest_path).resolve()
        manifest = read(manifest_path);manifest_sha256 = file_sha(manifest_path)
        require(manifest['kind'] == 'gegi_event_stream_v1' and manifest['events_file'] == 'events.jsonl', 'Unsupported sparse manifest')
        require(manifest['model_sha256'] == self.ready['model_sha256'], 'Chunk detector model changed')
        calibration_path = bound_file(calibration);table = read(calibration_path)
        require(table['kind'] == 'gegi_pixel_simulated_depth_v1' and table['per_pixel_calibration'] is True,
                'Production requires an explicit pixel depth calibration')
        require(table['model_sha256'] == self.ready['model_sha256'] and
                table['field_cache_sha256'] == self.ready['field_cache_sha256'] and
                table['drift_numerics'] == self.ready['drift_numerics'], 'Depth calibration fields/numerics differ from response')
        require(table['calibration_source_sha256'] == {name: digest for name, digest in
                    self.ready['source_code_sha256'].items() if name != 'gegi_campaign_response.jl'},
                'Depth calibration source changed')
        windows = I.photopeak_windows(photopeak_windows);windows_sha256 = S.sha(S.encoded(windows))
        require(store_identity['calibration_sha256'] == calibration['sha256'] and
                store_identity['photopeak_windows_sha256'] == windows_sha256 and
                store_identity['native_request_sha256'] == self.request_sha256, 'Chunk response identity changed')
        stream = manifest_path.parent/manifest['events_file']
        require(file_sha(stream) == manifest['events_sha256'], 'Sparse event stream changed')
        n, zero, nonzero = (manifest[k] for k in ('primary_count', 'zero_deposit_primaries', 'nonzero_primaries'))
        require(all(type(v) is int and v >= 0 for v in (n, zero, nonzero)) and zero+nonzero == n and n > 0, 'Invalid initial census')
        store_path = Path(store_path)
        store = S.Store(store_path, store_identity, create=not store_path.exists())
        try:
            if prior_recipe_provenance is not None:
                from gegi_campaign_analysis import response_recipe_for_event
                check_response={'readout_recipe':self.recipe(),'readout_recipe_sha256':S.sha(S.encoded(self.recipe())),
                                'prior_recipe_provenance':prior_recipe_provenance}
                for record in prior_recipe_provenance['events']:
                    require(store.has(record['event_id'],record['group_id'],record['input_sha256']),
                            'Recovery lost a preserved native group')
                    old,_=store.read(record['event_id'],record['group_id'],with_signals=False)
                    response_recipe_for_event(check_response,old)
            existing = store.db.execute('SELECT body FROM completion WHERE singleton=1').fetchone()
            if existing:
                result = json.loads(existing[0])
                require(result['input_manifest_sha256'] == manifest_sha256 and
                        result['store_identity_sha256'] == S.sha(S.encoded(store_identity)) and
                        result.get('prior_recipe_provenance') == prior_recipe_provenance, 'Sealed response identity changed')
                for key in store.keys():
                    store.read(*key, with_signals=True)
            else:
                counters = collections.Counter(initial_primaries=n, zero_deposit_primaries=zero, nonzero_primaries=nonzero)
                outcomes = {key: set() for key in ('native_failed', 'native_flagged', 'readout_accepted',
                            'readout_rejected', 'imaging_accepted', 'imaging_rejected')}
                seen = set();keys = set();replay_receipt = None
                context = {k: store_identity[k] for k in ('source_group', 'chunk_index', 'campaign_initial_offset')}
                context['root'] = str(manifest_path.parent.relative_to(ROOT)).replace('\\', '/')
                source_id = manifest.get('source_id') or manifest['source_contract']['id']
                with stream.open(encoding='utf-8') as input_stream:
                    for line in input_stream:
                        require(len(line.encode('utf-8')) <= MAX_JSON_BYTES, 'Sparse event exceeds bounded input')
                        event = json.loads(line);eid = event['event_id']
                        require(type(eid) is int and 0 <= eid < n and eid not in seen, 'Duplicate/out-of-range original primary')
                        seen.add(eid)
                        for group in pulse_groups(event, source_id, context):
                            gid = group['group_id'];keys.add((eid, gid))
                            saved = self.process_group(group, store, calibration=table, photopeak_windows=windows,
                                                       calibration_sha256=calibration['sha256'])
                            counters['pulse_groups'] += 1
                            if saved['status'] == 'native_failed':
                                counters['native_failed_groups'] += 1;outcomes['native_failed'].add(eid)
                            elif saved['status'] != 'completed':
                                counters['native_flagged_groups'] += 1;outcomes['native_flagged'].add(eid)
                            for stage, accepted in (('readout', saved['readout_summary']['accepted']),
                                                    ('imaging', saved['reconstruction']['status'] == 'accepted')):
                                label = stage+('_accepted' if accepted else '_rejected')
                                counters[label+'_groups'] += 1;outcomes[label].add(eid)
                            if replay_receipt is None and saved.get('channels') is not None:
                                replay_receipt = self.verify_saved_group(store, eid, gid)
                require(len(seen) == nonzero and set(store.keys()) == keys, 'Sparse primary/group census changed')
                require(file_sha(stream) == manifest['events_sha256'] and file_sha(manifest_path) == manifest_sha256,
                        'Transport inputs changed during response')
                for name, ids in outcomes.items():
                    counters[name+'_primaries'] = len(ids)
                    counters.setdefault(name+'_groups', 0)
                counters.setdefault('pulse_groups', 0)
                for name in ('initial_decays', 'decay_photons', 'line_photons', 'line_photon_counts'):
                    if name in manifest.get('counts', {}):
                        counters[name] = manifest['counts'][name]
                result = {'kind': 'gegi_campaign_chunk_response_v1',
                    'status': 'completed_with_native_failures' if counters['native_failed_groups'] else 'completed',
                    'input_manifest_sha256': manifest_sha256, 'store_identity_sha256': S.sha(S.encoded(store_identity)),
                    'counts': dict(counters), 'calibration_sha256': calibration['sha256'],
                    'photopeak_windows_sha256': windows_sha256, 'readout_recipe': self.recipe(),
                    'readout_recipe_sha256': S.sha(S.encoded(self.recipe())), 'electronics_replay': replay_receipt,
                    'count_scope': 'Readout/imaging group acceptance and rejection partition all nonzero groups. Unique-primary outcome sets mean at least one group with that outcome and may overlap.',
                    'transport_counts': manifest.get('counts'), 'source_id': source_id,
                    'native_request_sha256': self.request_sha256, 'new_field_solve': False}
                if prior_recipe_provenance is not None:result['prior_recipe_provenance']=prior_recipe_provenance
                store.seal(result)
        finally:
            store.close()
        write(receipt_path, result)
        return result

    def close(self):
        if self.process is not None:
            try:
                if self.process.poll() is None:
                    self.command('quit')
                self.process.wait(timeout=30)
            except (OSError, ValueError, subprocess.TimeoutExpired):
                if self.process.poll() is None:
                    self.process.terminate()
                    self.process.wait(timeout=30)
            finally:
                if self.process.poll() is not None:
                    owner = read(self.spool/'worker-process.json')
                    owner.update(status='completed', returncode=self.process.returncode)
                    write(self.spool/'worker-process.json', owner)
                if self.process.stdin:
                    self.process.stdin.close()
                if self.process.stdout:
                    self.process.stdout.close()
                self.process = None
        if self._log is not None:
            self._log.close();self._log = None
        if self._lock is not None:
            self._lock.close();self._lock = None


def verify_saved_event(event_path, signals_path, run_path, output):
    """Acceptance helper: saved native arrays -> Store -> exact readout replay; no drift."""
    output = Path(output).resolve()
    require(output.is_relative_to((ROOT/'.local').resolve()) and not output.exists(), 'Replay acceptance needs a new owned .local directory')
    output.mkdir(parents=True)
    event = read(event_path);run = read(run_path)
    native = S.native_csv(signals_path, event['channels'])
    identity = {'event_sha256': file_sha(event_path), 'signals_sha256': file_sha(signals_path), 'run_sha256': file_sha(run_path)}
    store = S.Store(output/'saved-event.sqlite3', identity, create=True)
    try:
        store.append(event['event_id'], event.get('group_id', 0), event, native, identity['event_sha256'])
        saved, native = store.read(event['event_id'], event.get('group_id', 0), with_signals=True)
        request = {'channels': run['channels'], 'readout_config': run['readout_config'],
            'electronics_calibration': run['calibration']['electronics'], 'ionisation_energy_eV': run['ionisation_energy_eV'],
            'drift_dt_ns': run['calibration']['electronics']['time_step_ns'], 'native_signals': native,
            'horizon_ns': event.get('readout_horizon_ns')}
        write(output/'replay-input.json', request)
        env = W.child_env(1)
        with (output/'replay.log').open('wb') as log:
            call = subprocess.run([env['JULIA_EXE'], '--startup-file=no', '--threads=1', '--project='+str(ROOT/'simulation'),
                str(ROOT/'simulation/gegi_campaign_response.jl'), '--replay-only', str(output/'replay-input.json'),
                '--output', str(output/'replay-output.json')], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        require(call.returncode == 0, 'Saved native electronics replay failed; retained replay.log contains the error')
        receipt = verify_replayed_channels(saved, read(output/'replay-output.json'))
        receipt.update(kind='gegi_saved_native_replay_acceptance_v1', inputs=identity,
                       replay_source_sha256=file_sha(ROOT/'simulation/gegi_campaign_response.jl'))
        store.seal(receipt);write(output/'receipt.json', receipt)
        return receipt
    finally:
        store.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-saved-event', required=True)
    parser.add_argument('--signals', required=True)
    parser.add_argument('--run', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(S.encoded(verify_saved_event(args.verify_saved_event, args.signals, args.run, args.output)).decode('utf-8'))
