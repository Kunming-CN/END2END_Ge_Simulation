"""Fixed owned Gamma jobs; the unchanged Gamma CLI owns all science checks.

No stop/resume/adoption path exists. A dead Python driver cannot prove that its
unrecorded Julia child stopped. Uncertain dispatches remain blocking, including
after reopening, until an explicit check of existing terminal receipts succeeds.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import sys
import threading
import time
import uuid

from local_ui_jobs import (ControlError, STATE, JSON_BYTES, STATE_REPLACE_DELAYS,
                           STATE_REPLACE_WINERRORS, decode_json, read_json,
                           run_command, safe_path, process_identity, utc_now,
                           existing_julia_environment)
from gamma_native_example import JULIA_SHA
from replay_readout import julia_executable

BASE = '.local/m11c-gamma-native-v1'
KIND = 'source_gamma_native_example_v1'
MODELS = ('AK02', 'SAP22')
FILES = ('run.json', 'COMPLETE.json', *tuple(model + '/' + artifact
    for model in MODELS for artifact in ('request.json', 'report.json',
        'calibration.json', 'truth-ledger.jsonl', 'signals.csv')))
MAX_FILE_BYTES = 8 * 1024 * 1024
ID = re.compile(r'[0-9a-f]{32}\Z')
CHECK_ID = re.compile(r'[0-9a-f]{64}\Z')
SHA = re.compile(r'[0-9a-f]{64}\Z')
STATUSES = ('dispatch-uncertain', 'running', 'verification-required', 'completed', 'failed', 'blocked')
ERRORS = {
    'invalid_threads': 'Choose one or two Julia threads.',
    'busy': 'An owned calculation or input check is active. Wait before another action.',
    'invalid_check': 'Check these fixed Gamma inputs before starting.',
    'unknown_job': 'Unknown owned Gamma job.',
    'uncertain_dispatch': 'A prior Gamma driver has uncertain nested-worker lifetime. Preserve its output for owner inspection.',
    'verification_required': 'Verify the existing completed Gamma receipt before downloading.',
    'backend_refused': 'Gamma input or receipt verification failed; inspect preserved local evidence.',
    'invalid_backend_receipt': 'Gamma returned an unsupported receipt; inspect preserved local evidence.',
    'launcher_failed': 'Gamma launcher failed; inspect preserved local evidence.',
    'incomplete_output': 'Only existing completed Gamma receipts can be verified.',
    'output_exists': 'The generated Gamma output already exists; no replacement was launched.',
    'invalid_state': 'Unsupported Gamma control state; preserve it for inspection.',
    'download_refused': 'Verified Gamma artifact is unavailable or changed.',
    'controller_failed': 'Gamma action failed; inspect preserved local evidence.'}


def refused(code):
    return ControlError(ERRORS[code], code)


def finite_seconds(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def gamma_environment(mode, threads=None):
    """Preflight the pinned launcher without executing it or changing globals.

    Saved verification reads the CLI's recorded executable; it never discovers
    a replacement. Check/run use the same existing Windows selector as Cs137.
    """
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', OPENBLAS_NUM_THREADS='1',
               OMP_NUM_THREADS='1', JULIA_PKG_OFFLINE='true')
    if threads is not None:
        env['JULIA_NUM_THREADS'] = str(threads)
    if mode in ('check', 'run'):
        try:
            existing_julia_environment(env)
            selected = env.get('JULIA_EXE')
            if selected is None:
                selected = julia_executable()
            if not selected or hashlib.sha256(Path(selected).read_bytes()).hexdigest() != JULIA_SHA:
                raise ValueError('Pinned existing executable differs')
            env['JULIA_EXE'] = selected
        except (OSError, ValueError, ControlError) as error:
            raise refused('backend_refused') from error
    return env


class GammaController:
    def __init__(self, root=None, runner=None, *, identity_probe=None,
                 coordination_lock=None, peer_busy=None):
        self.root = Path(os.path.abspath(root or Path(__file__).parent.parent))
        self._runner = runner or run_command
        self._identity_probe = identity_probe or process_identity
        self._lock = coordination_lock or threading.RLock()
        self._peer_busy = peer_busy or (lambda: False)
        self._active = None
        self._checking = False
        self._thread = None
        self._jobs = []
        self._checks = {}
        self._state_path = safe_path(self.root, STATE + '/gamma-jobs.json')
        safe_path(self.root, BASE)
        safe_path(self.root, STATE + '/gamma-logs').mkdir(parents=True, exist_ok=True)
        if self._state_path.exists():
            try:
                saved = read_json(self._state_path)
                if (saved.get('kind') != 'gamma_local_control_jobs_v1' or saved.get('schema_version') != 1 or
                        not isinstance(saved.get('jobs'), list) or not isinstance(saved.get('checks'), dict)):
                    raise ValueError('state kind')
                seen = set()
                for job in saved['jobs']:
                    if (not isinstance(job, dict) or not ID.fullmatch(str(job.get('id', ''))) or
                            job['id'] in seen or job.get('output') != BASE + '/ui-gamma-' + job['id'] or
                            type(job.get('threads')) is not int or job['threads'] not in (1, 2) or
                            job.get('status') not in STATUSES or type(job.get('uncertain')) is not bool or
                            not finite_seconds(job.get('started_seconds')) or
                            not isinstance(job.get('created_at'), str) or not isinstance(job.get('updated_at'), str) or
                            any(not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00', job[k])
                                for k in ('created_at', 'updated_at'))):
                        raise ValueError('job identity')
                    child = job.get('child')
                    if child is not None and (not isinstance(child, dict) or type(child.get('pid')) is not int or
                            child['pid'] <= 0 or (child.get('identity') is not None and not isinstance(child['identity'], str))):
                        raise ValueError('child identity')
                    seen.add(job['id'])
                    self._jobs.append(job)
                for key, item in saved['checks'].items():
                    if (not CHECK_ID.fullmatch(key) or not isinstance(item, dict) or
                            type(item.get('threads')) is not int or item['threads'] not in (1, 2) or
                            not isinstance(item.get('created_at'), str) or
                            (item.get('job_id') is not None and item['job_id'] not in seen)):
                        raise ValueError('check identity')
                self._checks = saved['checks']
            except (OSError, ValueError, TypeError, KeyError, ControlError) as error:
                raise refused('invalid_state') from error
            # Reopening performs no CLI call, no adoption and no science. These
            # display changes stay in memory until a later explicit action.
            for job in self._jobs:
                # A prior verified completion establishes ended worker lifetime.
                # Rechecking its files is a separate requirement. Interrupted or
                # failed dispatches never obtain this classification from a dead
                # driver or merely from the presence of terminal-looking files.
                known_completion = ((job['status'] == 'completed' and not job['uncertain'] and
                    all(isinstance(job.get(key), str) and SHA.fullmatch(job[key])
                        for key in ('complete_sha256', 'run_sha256'))) or
                    (job['status'] == 'verification-required' and not job['uncertain']))
                job.pop('complete_sha256', None)
                job.pop('run_sha256', None)
                if (known_completion or self._terminal_receipts(job)) and not self._driver_live(job):
                    job.update(status='verification-required', uncertain=not known_completion,
                               error={'code': 'verification_required', 'message': ERRORS['verification_required']})
                elif job['uncertain'] or job['status'] in ('dispatch-uncertain', 'running') or self._driver_live(job):
                    job.update(status='blocked', uncertain=True,
                               error={'code': 'uncertain_dispatch', 'message': ERRORS['uncertain_dispatch']})

    def set_peer_busy(self, probe):
        with self._lock:
            self._peer_busy = probe

    def _path(self, job, artifact=''):
        return safe_path(self.root, job['output'] + ('/' + artifact if artifact else ''))

    def _persist(self):
        path = safe_path(self.root, STATE + '/gamma-jobs.json')
        pending = safe_path(self.root, STATE + '/gamma-jobs.json.pending')
        raw = json.dumps({'kind': 'gamma_local_control_jobs_v1', 'schema_version': 1,
                          'jobs': self._jobs, 'checks': self._checks}, allow_nan=False, separators=(',', ':'))
        with pending.open('w', encoding='utf-8', newline='\n') as stream:
            stream.write(raw + '\n'); stream.flush(); os.fsync(stream.fileno())
        for attempt in range(len(STATE_REPLACE_DELAYS) + 1):
            path = safe_path(self.root, STATE + '/gamma-jobs.json')
            pending = safe_path(self.root, STATE + '/gamma-jobs.json.pending')
            try:
                os.replace(pending, path)
                return
            except OSError as error:
                if (os.name != 'nt' or getattr(error, 'winerror', None) not in STATE_REPLACE_WINERRORS or
                        attempt == len(STATE_REPLACE_DELAYS)):
                    raise
                time.sleep(STATE_REPLACE_DELAYS[attempt])

    def _driver_live(self, job):
        child = job.get('child')
        if not child:
            return False
        now = self._identity_probe(child['pid'])
        return now == 'unknown' or (now is not None and
            (child.get('identity') in (None, 'unknown') or now == child['identity']))

    def own_busy(self):
        """No recursive peer call; uncertainty outlives a dead driver PID."""
        with self._lock:
            return (self._active is not None or self._checking or
                    any(j['uncertain'] or j['status'] == 'verification-required' or
                        self._driver_live(j) for j in self._jobs))

    def _guard_idle(self):
        if self._active is not None or self._checking or self._peer_busy():
            raise refused('busy')
        for job in self._jobs:
            if (self._driver_live(job) or job['uncertain'] or
                    job['status'] == 'verification-required'):
                raise refused('busy')

    def _verification_idle(self, job):
        # This existing-output CLI mode never launches science. An unrelated
        # workflow's uncertainty must not prevent clearing this terminal hold.
        # Own active/unknown lifetimes and other uncertain Gamma jobs still block.
        return (self._active is None and not self._checking and not any(
            self._driver_live(other) or (other is not job and other['uncertain'])
            for other in self._jobs))

    def _argv(self, mode, job=None):
        safe_path(self.root, 'tools/gamma_native_example.py')
        command = [sys.executable]
        if Path(sys.executable).name.casefold() == 'pvpython.exe':
            command += ['--no-mpi', '--disable-registry']
        command += ['-B', 'tools/gamma_native_example.py', mode]
        if mode == 'run':
            command += ['--output', job['output'], '--threads', str(job['threads']),
                        '--native-failure-policy', 'abort']
        elif mode == 'verify':
            command.append(job['output'])
        return command

    def _log(self, identity, text):
        # Control diagnostics are never appended to the CLI's hash-bound output.
        with self._lock:
            path = safe_path(self.root, STATE + '/gamma-logs/' + identity + '.log')
            prior = path.read_bytes() if path.exists() else b''
            path.write_bytes((prior + str(text).encode('utf-8', errors='replace'))[-1024 * 1024:])

    def _command(self, mode, *, job=None, check_id=None):
        identity = job['id'] if job else check_id
        def spawned(pid, creation):
            if job is not None:
                with self._lock:
                    job['child'] = {'pid': pid, 'identity': creation}
                    if mode == 'run':
                        job['status'] = 'running'
                    job['updated_at'] = utc_now()
                    self._persist()
        try:
            env = gamma_environment(mode, job['threads'] if job else None)
            call = self._runner(self._argv(mode, job), cwd=str(self.root), env=env,
                on_output=lambda value: self._log(identity, value), on_spawn=spawned)
        except BaseException as error:
            self._log(identity, repr(error) + '\n')
            raise refused('launcher_failed') from error
        self._log(identity, '\nDriver return: ' + repr(call) + '\n')
        if type(call.get('exit_code')) is not int or call['exit_code'] != 0:
            raise refused('backend_refused')
        try:
            result = decode_json(call['output'].strip().splitlines()[-1])
            if not isinstance(result, dict):
                raise ValueError('object required')
        except (ValueError, IndexError, KeyError, TypeError, AttributeError) as error:
            raise refused('invalid_backend_receipt') from error
        # A returned subprocess is known exited; keep the identity record, but
        # ambiguity from run errors remains independently recorded by uncertain.
        if job:
            with self._lock:
                job['child'] = None
                self._persist()
        return result

    def check(self, threads=2):
        if type(threads) is not int or threads not in (1, 2):
            raise refused('invalid_threads')
        check_id = secrets.token_hex(32)
        with self._lock:
            self._guard_idle()
            self._checking = True
        try:
            result = self._command('check', check_id=check_id)
            expected = dict(status='checked_no_execution', models=list(MODELS),
                radiation_primaries=40, selected_primaries=6, native_calls=0, injection_calibrations=0)
            if result != expected or any(type(result[k]) is not int for k in
                    ('radiation_primaries', 'selected_primaries', 'native_calls', 'injection_calibrations')):
                raise refused('invalid_backend_receipt')
            with self._lock:
                self._checks[check_id] = {'threads': threads, 'created_at': utc_now(), 'job_id': None}
                try:
                    self._persist()
                except BaseException:
                    self._checks.pop(check_id, None)
                    raise
            return dict(kind='gamma_local_control_check_v1', **expected,
                        unprocessed_primaries=34, threads=threads, check_id=check_id)
        finally:
            with self._lock:
                self._checking = False

    def _find(self, job_id):
        if not isinstance(job_id, str) or not ID.fullmatch(job_id):
            raise refused('unknown_job')
        found = next((j for j in self._jobs if j['id'] == job_id), None)
        if not found:
            raise refused('unknown_job')
        return found

    def start(self, check_id):
        with self._lock:
            if not isinstance(check_id, str) or not CHECK_ID.fullmatch(check_id) or check_id not in self._checks:
                raise refused('invalid_check')
            checked = self._checks[check_id]
            if checked['job_id'] is not None:
                return {'kind': 'gamma_local_control_start_v1', 'job': self._public_job(self._find(checked['job_id']))}
            self._guard_idle()
            job_id = uuid.uuid4().hex
            job = dict(id=job_id, output=BASE + '/ui-gamma-' + job_id, threads=checked['threads'],
                status='dispatch-uncertain', uncertain=True, child=None,
                created_at=utc_now(), updated_at=utc_now(), started_seconds=time.time())
            if self._path(job).exists():
                raise refused('output_exists')
            self._jobs.append(job)
            checked['job_id'] = job_id
            try:
                # One-use check binding, owned output and uncertain dispatch are
                # durable BEFORE a thread/subprocess can start.
                self._persist()
            except BaseException:
                checked['job_id'] = None
                self._jobs.remove(job)
                raise
            self._active = job_id
            self._thread = threading.Thread(target=self._work, args=(job,),
                name='local-gamma-' + job_id[:8], daemon=True)
            try:
                self._thread.start()
            except BaseException as error:
                self._active = None
                job.update(status='blocked', error={'code': 'launcher_failed', 'message': ERRORS['launcher_failed']})
                self._log(job_id, repr(error))
                self._persist()
                raise refused('launcher_failed') from error
            return {'kind': 'gamma_local_control_start_v1', 'job': self._public_job(job)}

    def _receipt(self, job):
        try:
            run = read_json(self._path(job, 'run.json'))
            return run if isinstance(run, dict) and run.get('kind') == KIND and run.get('schema_version') == 1 else None
        except (OSError, ControlError, ValueError):
            return None

    def _terminal_receipts(self, job):
        run = self._receipt(job)
        try:
            return (run is not None and run.get('status') == 'completed' and
                    self._path(job, 'COMPLETE.json').is_file())
        except (OSError, ControlError):
            return False

    def _bind_verified(self, job, result):
        expected = dict(kind=KIND, status='completed', radiation_primaries=40,
                        selected_primaries=6, unprocessed_primaries=34)
        if result != expected or any(type(result[k]) is not int for k in
                ('radiation_primaries', 'selected_primaries', 'unprocessed_primaries')):
            raise refused('invalid_backend_receipt')
        try:
            run_raw = self._path(job, 'run.json').read_bytes()
            complete_raw = self._path(job, 'COMPLETE.json').read_bytes()
            if len(run_raw) > JSON_BYTES or len(complete_raw) > JSON_BYTES:
                raise ValueError('metadata bound')
            run = decode_json(run_raw.decode('utf-8-sig'))
            complete = decode_json(complete_raw.decode('utf-8-sig'))
            counts = dict(radiation_primaries=40, selected_primaries=6,
                          unprocessed_primaries=34, native_calls=4, injection_calibrations=2)
            if (run.get('kind') != KIND or run.get('schema_version') != 1 or run.get('status') != 'completed' or
                    type(run.get('threads')) is not int or run['threads'] != job['threads'] or
                    run.get('native_failure_policy') != 'abort' or
                    [s.get('model_id') for s in run.get('stages', [])] != list(MODELS) or
                    run.get('additional_radiation_calls') != 0 or run.get('field_solve_seconds') != 0.0 or
                    not finite_seconds(run.get('orchestration_seconds')) or
                    complete.get('kind') != KIND or complete.get('schema_version') != 1 or
                    complete.get('status') != 'completed' or complete.get('counts') != counts or
                    any(type(complete['counts'][k]) is not int for k in counts) or
                    complete.get('source_pins') != run.get('source_pins') or
                    complete.get('run_sha256') != hashlib.sha256(run_raw).hexdigest() or
                    not isinstance(complete.get('artifacts'), dict)):
                raise ValueError('terminal identity')
            for artifact in FILES[2:]:
                stamp = complete['artifacts'].get(artifact)
                if (not isinstance(stamp, dict) or not isinstance(stamp.get('sha256'), str) or
                        not SHA.fullmatch(stamp['sha256']) or type(stamp.get('bytes')) is not int or stamp['bytes'] < 0):
                    raise ValueError('artifact identity')
        except (OSError, ValueError, TypeError, KeyError, AttributeError, ControlError) as error:
            raise refused('invalid_backend_receipt') from error
        job.update(status='completed', uncertain=False, child=None,
                   complete_sha256=hashlib.sha256(complete_raw).hexdigest(),
                   run_sha256=hashlib.sha256(run_raw).hexdigest(),
                   elapsed_seconds=max(0.0, time.time() - job['started_seconds']), updated_at=utc_now())
        job.pop('error', None)

    def _work(self, job):
        try:
            result = self._command('run', job=job)
            if (set(result) != {'status', 'output', 'native_calls', 'injection_calibrations'} or
                    result.get('status') != 'completed' or
                    result.get('output') != str(self._path(job)) or
                    type(result.get('native_calls')) is not int or result['native_calls'] != 4 or
                    type(result.get('injection_calibrations')) is not int or result['injection_calibrations'] != 2):
                raise refused('invalid_backend_receipt')
            verified = self._command('verify', job=job)
            with self._lock:
                self._bind_verified(job, verified)
        except BaseException as error:
            self._log(job['id'], repr(error) + '\n')
            with self._lock:
                code = getattr(error, 'code', 'controller_failed')
                if code not in ERRORS:
                    code = 'controller_failed'
                job.update(status='failed', uncertain=True,
                           error={'code': code, 'message': ERRORS[code]}, updated_at=utc_now(),
                           elapsed_seconds=max(0.0, time.time() - job['started_seconds']))
                job.pop('complete_sha256', None)
                job.pop('run_sha256', None)
        finally:
            with self._lock:
                self._active = None
                self._persist()

    def verify(self, job_id):
        with self._lock:
            job = self._find(job_id)
            if not self._verification_idle(job):
                raise refused('busy')
            if not self._terminal_receipts(job):
                raise refused('incomplete_output')
            self._checking = True
            job.pop('complete_sha256', None)
            job.pop('run_sha256', None)
            job.update(status='verification-required', uncertain=True)
            try:
                self._persist()
            except BaseException:
                self._checking = False
                raise
        try:
            result = self._command('verify', job=job)
            with self._lock:
                self._bind_verified(job, result)
                self._persist()
                return dict(kind='gamma_local_control_verify_v1', status='verified',
                            scientific_workers_launched=0, job=self._public_job(job))
        except BaseException as error:
            with self._lock:
                code = getattr(error, 'code', 'controller_failed')
                if code not in ERRORS:
                    code = 'controller_failed'
                job.update(status='blocked', uncertain=True,
                           error={'code': code, 'message': ERRORS[code]}, updated_at=utc_now())
                self._persist()
            raise
        finally:
            with self._lock:
                self._checking = False

    def _public_job(self, job):
        run = self._receipt(job)
        completed = []
        if run:
            # Only exact observed prefix stages; private paths/errors are omitted.
            stages = run.get('stages')
            if isinstance(stages, list):
                for index, stage in enumerate(stages[:2]):
                    if (not isinstance(stage, dict) or stage.get('model_id') != MODELS[index] or
                            type(stage.get('exit_code')) is not int or stage['exit_code'] != 0):
                        break
                    completed.append(MODELS[index])
        verified = (job['status'] == 'completed' and isinstance(job.get('complete_sha256'), str) and
                    isinstance(job.get('run_sha256'), str))
        current = None
        if run and run.get('status') == 'running' and len(completed) < 2 and job['status'] == 'running':
            candidate = MODELS[len(completed)]
            try:
                # A driver PID alone is not an observed model stage. A request
                # marks only that fixed serial model phase, not per-event work.
                if self._path(job, candidate + '/request.json').is_file():
                    current = candidate
            except (OSError, ControlError):
                pass
        stage = ('complete' if verified else 'verification' if self._terminal_receipts(job) else
                 'failed' if job['status'] == 'failed' else 'native_models' if current else
                 'waiting' if job['status'] in ('dispatch-uncertain', 'running') else 'unknown')
        can_verify = self._verification_idle(job) and self._terminal_receipts(job)
        error = job.get('error')
        safe_error = None
        if isinstance(error, dict) and error.get('code') in ERRORS:
            safe_error = {'code': error['code'], 'message': ERRORS[error['code']]}
        seconds = job.get('elapsed_seconds', max(0.0, time.time() - job['started_seconds']))
        return dict(id=job['id'], label='ui-gamma-' + job['id'], threads=job['threads'],
            status=job['status'], created_at=job['created_at'], updated_at=job['updated_at'],
            elapsed_seconds=seconds if finite_seconds(seconds) else 0.0,
            calculation_seconds=run['orchestration_seconds'] if run and finite_seconds(run.get('orchestration_seconds')) else None,
            progress=dict(completed_models=completed, current_model=current, stage=stage),
            can_verify=bool(can_verify),
            blocks_new_work=bool(self._driver_live(job) or job['uncertain'] or job['status']=='verification-required'),
            verified=verified, files=list(FILES) if verified else [],
            complete_sha256=job.get('complete_sha256') if verified else None,
            run_sha256=job.get('run_sha256') if verified else None, error=safe_error)

    def snapshot(self):
        """Whitelisted read-only observation; no CLI call or persistence."""
        with self._lock:
            jobs = [self._public_job(j) for j in reversed(self._jobs[-20:])]
            active = next((j for j in jobs if j['id'] == self._active and
                           j['status'] in ('dispatch-uncertain', 'running')), None)
            return dict(kind='gamma_local_control_state_v1', active=active, jobs=jobs,
                        checking=self._checking, busy=bool(self.own_busy() or self._peer_busy()))

    def download(self, job_id, artifact):
        """Exact byte capability bound to owned COMPLETE and run serialization.

        Metadata alone uses the 2 MiB reader. Reports are fetched directly under
        the 8 MiB artifact bound, including the historical >2 MiB AK02 report.
        These are checked ordinary file reads, not a race-resistant sandbox.
        """
        with self._lock:
            try:
                job = self._find(job_id)
                if artifact not in FILES or job['status'] != 'completed' or not job.get('complete_sha256') or not job.get('run_sha256'):
                    raise ValueError('ownership')
                complete_path = self._path(job, 'COMPLETE.json')
                run_path = self._path(job, 'run.json')
                if complete_path.stat().st_size > JSON_BYTES or run_path.stat().st_size > JSON_BYTES:
                    raise ValueError('metadata bound')
                complete_raw = complete_path.read_bytes()
                run_raw = run_path.read_bytes()
                if (hashlib.sha256(complete_raw).hexdigest() != job['complete_sha256'] or
                        hashlib.sha256(run_raw).hexdigest() != job['run_sha256']):
                    raise ValueError('receipt changed')
                complete = decode_json(complete_raw.decode('utf-8-sig'))
                if complete.get('run_sha256') != job['run_sha256']:
                    raise ValueError('run binding')
                path = self._path(job, artifact)
                if path.stat().st_size > MAX_FILE_BYTES:
                    raise ValueError('artifact bound')
                body = path.read_bytes()
                if len(body) > MAX_FILE_BYTES:
                    raise ValueError('artifact bound')
                expected_hash = job['complete_sha256'] if artifact == 'COMPLETE.json' else job['run_sha256'] if artifact == 'run.json' else None
                if expected_hash is None:
                    stamp = complete['artifacts'].get(artifact)
                    if not isinstance(stamp, dict) or type(stamp.get('bytes')) is not int or len(body) != stamp['bytes']:
                        raise ValueError('artifact bytes')
                    expected_hash = stamp.get('sha256')
                if hashlib.sha256(body).hexdigest() != expected_hash:
                    raise ValueError('artifact hash')
                return body, 'ui-gamma-' + job['id'] + '-' + artifact.replace('/', '-')
            except (OSError, ValueError, KeyError, TypeError, AttributeError, UnicodeError, ControlError) as error:
                raise refused('download_refused') from error

    def wait_for_idle(self, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                if self._active is None and not self._checking:
                    return self.snapshot()
            time.sleep(0.01)
        raise TimeoutError('Owned Gamma job is still active.')
