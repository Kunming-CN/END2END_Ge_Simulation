"""Owned local jobs for the bounded native-readout mouse interface.

The unchanged scenario CLI is the only computation/verification authority.
Stop is cooperative: every invocation has a one-electronics-group budget; all
missing charge and calibration precede that boundary. Nothing kills a worker.
The HTTP/session lease belongs to local_ui.py, not this backend adapter.
"""
from __future__ import annotations

import copy
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import threading
import time
import uuid

BASE = '.local/native-readout-integration-v1/implementation/outputs'
STATE = '.local/local-control-v1'
KIND = 'native_charge_readout_integration_v1'
DETECTORS = ('AK02', 'SAP22')
TERMINAL = ('completed', 'completed_with_native_failures')
PHASES = ('charge', 'calibration', 'electronics')
NAME = re.compile(r'[A-Za-z0-9_-]{1,24}\Z')
LOG_LINES = 80
LOG_BYTES = 1024 * 1024
JSON_BYTES = 2 * 1024 * 1024
STATE_REPLACE_DELAYS = (0.05, 0.1, 0.2, 0.4, 0.8)
STATE_REPLACE_WINERRORS = (5, 32, 33)


class ControlError(Exception):
    def __init__(self, message, code='refused'):
        super().__init__(message)
        self.code = code


def existing_julia_environment(env):
    """Select the existing readable launcher in a CHILD environment only."""
    if os.name != 'nt':
        return env
    # WindowsApps app-execution aliases can execute yet cannot be read
    # for the backend's launcher-byte provenance gate. Use the exact
    # already-installed fallback that the shared backend documents.
    # An explicit value, including an empty/unreadable one, is honored
    # as a request and refuses instead of silently choosing another.
    explicit = next((k for k in env if k.casefold() == 'julia_exe'), None)
    if explicit is not None:
        chosen = env[explicit]
        if not chosen:
            raise ControlError('Explicit JULIA_EXE is empty. Select an existing readable Julia executable; no fallback was used.', 'unsupported_runtime')
    else:
        profile = env.get('USERPROFILE') or env.get('UserProfile')
        if not profile:
            raise ControlError('Existing pinned Julia cannot be located. Set JULIA_EXE to a readable existing executable; nothing was installed.', 'unsupported_runtime')
        chosen = str(Path(profile) / '.julia/juliaup/julia-1.13.0+0.x64.w64.mingw32/bin/julia.exe')
    try:
        candidate = Path(chosen)
        if not candidate.is_file():
            raise OSError('not a file')
        with candidate.open('rb') as stream:
            if not stream.read(1):
                raise OSError('empty executable')
    except (OSError, ValueError) as error:
        raise ControlError(('Explicit JULIA_EXE is not readable; no fallback was used.' if explicit is not None else
                            'The existing pinned Julia 1.13.0 binary is missing or unreadable. Set JULIA_EXE to a readable existing executable; nothing was installed.'),
                           'unsupported_runtime') from error
    for key in list(env):
        if key.casefold() == 'julia_exe':
            del env[key]
    env['JULIA_EXE'] = chosen
    return env


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def safe_path(root, relative):
    """Reject every existing linked/reparse component, including root and leaf."""
    root = Path(os.path.abspath(root))
    relative = str(relative).replace('\\', '/')
    if (not relative or relative.startswith('/') or ':' in relative or
            any(p in ('', '.', '..') for p in relative.split('/'))):
        raise ControlError('Unsafe local path.', 'unsafe_path')
    path = root.joinpath(*relative.split('/'))
    for item in (root, *[root.joinpath(*relative.split('/')[:i])
                        for i in range(1, len(relative.split('/')) + 1)]):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ControlError('Linked or reparse local path refused.', 'unsafe_path')
    return path


def decode_json(text):
    def pairs(items):
        result = {}
        for k, v in items:
            if k in result:
                raise ValueError('duplicate JSON key')
            result[k] = v
        return result
    def nonfinite(value):
        raise ValueError('nonfinite JSON token')
    def floating(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError('nonfinite JSON number')
        return result
    return json.loads(text, object_pairs_hook=pairs, parse_constant=nonfinite, parse_float=floating)


def read_json(path):
    if path.stat().st_size > JSON_BYTES:
        raise ControlError('Local receipt exceeds the bounded reader.', 'invalid_receipt')
    try:
        value = decode_json(path.read_text(encoding='utf-8-sig'))
    except (ValueError, UnicodeError) as error:
        raise ControlError('Local receipt is invalid JSON.', 'invalid_receipt') from error
    if not isinstance(value, dict):
        raise ControlError('Local receipt must be an object.', 'invalid_receipt')
    return value


def process_identity(pid):
    """Windows creation FILETIME disambiguates reused PIDs; unknown stays blocking."""
    if os.name != 'nt':
        try:
            os.kill(pid, 0)
            return 'live'
        except ProcessLookupError:
            return None
        except PermissionError:
            return 'unknown'
    from ctypes import wintypes
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    api.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    api.OpenProcess.restype = wintypes.HANDLE
    api.GetProcessTimes.argtypes = (wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4))
    api.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = api.OpenProcess(0x1000, False, pid)
    if not handle:
        return None if ctypes.get_last_error() == 87 else 'unknown'
    try:
        times = [wintypes.FILETIME() for _ in range(4)]
        if not api.GetProcessTimes(handle, *[ctypes.byref(t) for t in times]):
            return 'unknown'
        return str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)
    finally:
        api.CloseHandle(handle)


def lock_busy(path):
    """Probe an existing backend lease without changing or deleting its bytes."""
    if not path.exists():
        return False
    if not path.is_file():
        return True
    if os.name == 'nt':
        from ctypes import wintypes
        api = ctypes.WinDLL('kernel32', use_last_error=True)
        api.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                   ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
        api.CreateFileW.restype = wintypes.HANDLE
        api.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = api.CreateFileW(str(path), 0x80000000, 0, None, 3, 0x80, None)
        if handle == ctypes.c_void_p(-1).value:
            return True
        api.CloseHandle(handle)
        return False
    import fcntl
    try:
        with path.open('rb') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(stream, fcntl.LOCK_UN)
        return False
    except OSError:
        return True


def run_command(argv, *, cwd, env, on_output, on_spawn):
    """Injectable subprocess protocol. No timeout/stop path terminates children."""
    p = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    on_spawn(p.pid, process_identity(p.pid))
    # The backend emits one bounded JSON result. Retain a bounded tail if a
    # failing launcher produces noise; continue draining so it cannot deadlock.
    tail = bytearray()
    while True:
        block = p.stdout.read(4096)
        if not block:
            break
        tail.extend(block)
        if len(tail) > JSON_BYTES:
            del tail[:-JSON_BYTES]
        on_output(block.decode('utf-8', errors='replace'))
    code = p.wait()
    p.stdout.close()
    return {'exit_code': code, 'output': tail.decode('utf-8', errors='replace')}


class Controller:
    """One active owned job; durable names, read-only reopening, verified steps."""
    def __init__(self, root=None, runner=None, *, identity_probe=None, lock_probe=None,
                 coordination_lock=None, peer_busy=None):
        self.root = Path(os.path.abspath(root or Path(__file__).parent.parent))
        self._runner = runner or run_command
        self._identity_probe = identity_probe or process_identity
        self._lock_probe = lock_probe or lock_busy
        self._lock = coordination_lock or threading.RLock()
        self._peer_busy = peer_busy or (lambda: False)
        self._active = None
        self._checking = False
        self._thread = None
        self._last_runtime_choice = {}
        self._jobs = []
        self._state_path = safe_path(self.root, STATE + '/jobs.json')
        # Safety checks precede directory creation, including any state-file link.
        safe_path(self.root, BASE)
        safe_path(self.root, STATE + '/logs')
        if self._state_path.exists():
            saved = read_json(self._state_path)
            if saved.get('kind') != 'local_control_jobs_v1' or saved.get('schema_version') != 1 or not isinstance(saved.get('jobs'), list):
                raise ControlError('Unsupported local controller state; preserve it for inspection.', 'invalid_state')
            seen = set()
            for job in saved['jobs']:
                if (not isinstance(job, dict) or not NAME.fullmatch(str(job.get('name', ''))) or
                        job.get('detector') not in DETECTORS or not re.fullmatch(r'[0-9a-f]{32}', str(job.get('id', ''))) or
                        job['id'] in seen or job.get('output') != BASE + '/' + job['name']):
                    raise ControlError('Invalid owned job state; preserve it for inspection.', 'invalid_state')
                seen.add(job['id'])
                self._jobs.append(job)
                self._reconcile(job)
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        safe_path(self.root, STATE + '/logs').mkdir(exist_ok=True)
        self._persist()

    def _name(self, name):
        if (not isinstance(name, str) or not NAME.fullmatch(name) or
                re.fullmatch(r'(?i)(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])', name)):
            raise ControlError('Use 1–24 letters, digits, underscores or hyphens for the output name.', 'invalid_name')
        return name

    def _detector(self, detector):
        if detector not in DETECTORS:
            raise ControlError('This entry supports AK02 or SAP22 only.', 'invalid_detector')
        return detector

    def _path(self, name, suffix=''):
        relative = BASE + '/' + self._name(name)
        return safe_path(self.root, relative + ('/' + suffix if suffix else ''))

    def _persist(self):
        path = safe_path(self.root, STATE + '/jobs.json')
        temp = safe_path(self.root, STATE + '/jobs.json.pending')
        raw = json.dumps({'kind': 'local_control_jobs_v1', 'schema_version': 1,
                          'jobs': self._jobs}, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
        with temp.open('w', encoding='utf-8', newline='\n') as stream:
            stream.write(raw + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        # Replace the same flushed serialization atomically. Windows file
        # sharing/access failures may be temporary; every other error and the
        # bounded final failure propagate with prior state and pending evidence.
        for attempt in range(len(STATE_REPLACE_DELAYS) + 1):
            path = safe_path(self.root, STATE + '/jobs.json')
            temp = safe_path(self.root, STATE + '/jobs.json.pending')
            try:
                os.replace(temp, path)
                return
            except OSError as error:
                if (os.name != 'nt' or getattr(error, 'winerror', None) not in STATE_REPLACE_WINERRORS or
                        attempt == len(STATE_REPLACE_DELAYS)):
                    raise
                time.sleep(STATE_REPLACE_DELAYS[attempt])

    def _sanitized(self, value):
        text = str(value).replace(str(self.root), '[project]').replace(str(self.root).replace('\\', '/'), '[project]')
        text = re.sub(r'(?i)(?:[A-Z]:[\\/]|\\\\)[^\r\n"<>|]*', '[private path]', text)
        text = re.sub(r'(?<![\w.])/(?:home|Users|tmp|mnt|var)/[^\s"<>]*', '[private path]', text)
        return text[:1500]

    def _log(self, job, text):
        with self._lock:
            private = safe_path(self.root, STATE + '/logs/' + job['id'] + '.log')
            # This is a diagnostic tail, not a science artifact. Backend attempts
            # retain their own complete private failure records independently.
            prior = private.read_bytes() if private.exists() else b''
            data = (prior + text.encode('utf-8', errors='replace'))[-LOG_BYTES:]
            private.write_bytes(data)
            lines = [self._sanitized(line) for line in text.splitlines() if line.strip()]
            job['logs'] = (job.get('logs', []) + lines)[-LOG_LINES:]
            job['updated_at'] = utc_now()
            self._persist()

    def _live(self, job):
        child = job.get('child')
        if isinstance(child, dict) and type(child.get('pid')) is int and child['pid'] > 0:
            now = self._identity_probe(child['pid'])
            if now == 'unknown' or (now is not None and (child.get('identity') in (None, 'unknown') or now == child['identity'])):
                return True
        return self._lock_probe(self._path(job['name'], 'run.lock'))

    def _reconcile(self, job):
        job.pop('complete_sha256', None)
        job.pop('verification_required', None)
        # Derived identity is regenerated from the saved manifest/stages rather
        # than trusting a label or discrepancy in mutable controller metadata.
        job.pop('identity_mismatch', None)
        if self._live(job):
            job['status'] = 'blocked'
            job['error'] = {'code': 'backend_still_active', 'message': 'An owned backend process or run lease remains active. Wait for it to finish; no replacement worker was launched.'}
            return
        # A server restart never adopts a terminal label without another
        # requested backend verification. It also never resumes computation.
        job['child'] = None
        receipt = self._receipt(job)
        if receipt:
            job['backend'] = self._backend_view(receipt)
            if receipt.get('status') in ('paused', *TERMINAL):
                try:
                    self._saved_identity(job, receipt)
                except ControlError as error:
                    self._identity_block(job, error)
                    return
            if receipt.get('status') == 'paused':
                job['status'] = 'stopped' if job.get('stop_requested') else 'paused'
                job.pop('error', None)
            elif receipt.get('status') == 'failed':
                job['status'] = 'failed'
            elif receipt.get('status') in TERMINAL and self._path(job['name'], 'COMPLETE.json').is_file():
                job['status'] = receipt['status']
                job['verification_required'] = True
                job.pop('error', None)
            else:
                job['status'] = 'blocked'
                job['error'] = {'code': 'verification_required', 'message': 'Saved receipts remain. Resume verifies them before any continuation; reopening starts no computation.'}
        elif job.get('status') not in ('cancelled', 'stopped', 'blocked', 'failed'):
            job['status'] = 'blocked'
            job['error'] = {'code': 'interrupted_before_receipt', 'message': 'The prior controller did not retain a verified backend receipt. Inspect or resume the saved output; no new computation was started.'}

    def _guard_idle(self):
        if self._peer_busy():
            raise ControlError('Another owned calculation or input check is active; wait before launching.', 'busy')
        if self._active is not None or self._checking:
            raise ControlError('One job or input check is already active.', 'busy')
        for job in self._jobs:
            if self._live(job):
                raise ControlError('An owned backend process or run lease is still active; wait before launching.', 'backend_still_active')

    def own_busy(self):
        """Nonrecursive peer probe; shared lock covers decision and reservation."""
        with self._lock:
            return self._active is not None or self._checking or any(self._live(j) for j in self._jobs)

    def set_peer_busy(self, probe):
        with self._lock:
            self._peer_busy = probe

    def _argv(self, name, detector=None, *, resume=False, dry=False, step=False):
        safe_path(self.root, 'tools/scenario_cli.ps1')
        command = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                   'tools/scenario_cli.ps1', 'native-readout', '-Name', self._name(name), '-Json']
        if resume:
            command.append('-Resume')
        elif detector is not None:
            command.extend(('-Detector', self._detector(detector)))
        if dry:
            command.append('-DryRun')
        if step:
            command.extend(('-StopAfterGroups', '1'))
        return command

    def _environment(self, *, select_julia=True):
        # Only the new child receives these; the backend owns its pinned runtime.
        env = dict(os.environ, JULIA_NUM_THREADS='2', OPENBLAS_NUM_THREADS='1',
                   OMP_NUM_THREADS='1', JULIA_PKG_OFFLINE='true', PYTHONDONTWRITEBYTECODE='1')
        if os.name == 'nt':
            # A PowerShell7 host can pass its own Utility7 module first in
            # PSModulePath to Windows PowerShell5.1, hiding Get-FileHash. The
            # unchanged public route requires only existing Windows built-ins.
            # Restrict discovery in this child; do not edit PATH/profile/modules
            # or either the parent process or the user's global environment.
            # os.environ normalizes Windows keys to uppercase; a plain copied
            # dict is case-sensitive. Remove every old spelling to avoid two
            # case-insensitively identical entries in CreateProcess's block.
            system_root = env.get('SYSTEMROOT') or env.get('SystemRoot') or env.get('WINDIR')
            if not system_root:
                raise ControlError('Existing Windows PowerShell system modules cannot be located.', 'unsupported_runtime')
            modules = Path(system_root) / 'System32/WindowsPowerShell/v1.0/Modules'
            if not (modules / 'Microsoft.PowerShell.Utility/Microsoft.PowerShell.Utility.psd1').is_file():
                raise ControlError('Existing Windows PowerShell Utility module is unavailable; nothing was installed.', 'unsupported_runtime')
            for key in list(env):
                if key.casefold() == 'psmodulepath':
                    del env[key]
            env['PSModulePath'] = str(modules)
            if not select_julia:
                # Saved Resume/DryRun is backend-only receipt verification and
                # retains the public route's no-Julia-discovery/no-launch path.
                return env
            existing_julia_environment(env)
        return env

    def _runtime_label(self, env, *, selected=True):
        if not selected:
            return {'label': 'Saved runtime verification; no Julia launch',
                    'selection': 'saved_verification', 'backend_verifies_version': True}
        explicit = any(k.casefold() == 'julia_exe' for k in os.environ)
        return {'label': 'Explicit existing Julia executable' if explicit else 'Existing pinned Julia 1.13.0 path',
                'selection': 'explicit' if explicit else 'pinned_existing',
                'backend_verifies_version': True}

    def _command(self, argv, job=None):
        if job is not None:
            with self._lock:
                job['command'] = argv
                job['updated_at'] = utc_now()
                self._persist()
            self._log(job, ('Read-only verification: ' if '-DryRun' in argv else 'One verified electronics step: ') + ' '.join(argv) + '\n')
        def spawned(pid, identity):
            if job is not None:
                with self._lock:
                    job['child'] = {'pid': pid, 'identity': identity}
                    self._persist()
        def output(text):
            if job is not None:
                self._log(job, text)
        select_julia = not ('-Resume' in argv and '-DryRun' in argv)
        env = self._environment(select_julia=select_julia)
        with self._lock:
            self._last_runtime_choice = self._runtime_label(env, selected=select_julia)
            if job is not None:
                if select_julia or 'runtime_choice' not in job:
                    job['runtime_choice'] = copy.deepcopy(self._last_runtime_choice)
                self._persist()
        try:
            call = self._runner(argv, cwd=str(self.root), env=env,
                                on_output=output, on_spawn=spawned)
        except BaseException as error:
            # Keep the last child identity if the transport itself failed while
            # a child may still exist; subsequent launches probe it conservatively.
            raise ControlError('Backend launcher failed; preserved diagnostics require inspection.', 'launcher_failed') from error
        if job is not None:
            with self._lock:
                job['child'] = None
                self._persist()
        try:
            raw = call['output'].strip()
            # PowerShell may emit a diagnostic before the driver's final JSON.
            result = decode_json(raw.splitlines()[-1])
            if not isinstance(result, dict):
                raise ValueError('object required')
        except (KeyError, IndexError, AttributeError, ValueError, TypeError) as error:
            raise ControlError('Backend returned no valid JSON receipt; shell success is insufficient.', 'invalid_backend_json') from error
        if result.get('kind') != KIND or result.get('schema_version') != 1:
            raise ControlError('Backend receipt identity is unsupported.', 'invalid_backend_receipt')
        if type(call.get('exit_code')) is not int or call['exit_code'] != 0 or result.get('verification_final') is not True:
            message = '; '.join(self._sanitized(f.get('detail', f.get('message', f.get('code', 'blocked'))))
                                for f in result.get('findings', []) if isinstance(f, dict))
            error = ControlError('Backend refused or failed verification.' + (' ' + message if message else ''), 'backend_refused')
            error.result = result
            raise error
        self._check_census(result)
        if job is not None:
            counts = self._backend_view(result)['completed_counts']
            self._log(job, 'Backend ' + str(result.get('status')) + ': ' +
                      ', '.join(p + '=' + str(counts[p]) for p in PHASES) + '\n')
        return result

    def _check_census(self, result):
        expected = {'initial_primaries': 3, 'zero_ge_primaries': 1, 'nonzero_primaries': 2, 'groups': 2}
        if result.get('selected_census') != expected or any(type(v) is not int for v in result.get('selected_census', {}).values()):
            raise ControlError('Backend census does not match this fixed bounded example.', 'invalid_backend_receipt')

    def _backend_view(self, result):
        view = {key: copy.deepcopy(result.get(key)) for key in ('status', 'verification_final', 'selected_census', 'stages')}
        stages = result.get('stages') or {}
        view['completed_counts'] = {p: stages.get(p, {}).get('completed_count') for p in PHASES}
        view['expected_counts'] = {p: stages.get(p, {}).get('expected_count') for p in PHASES}
        view['counts'] = {model: copy.deepcopy(item['counts']) for model, item in result.get('detectors', {}).items()
                          if model in DETECTORS and isinstance(item, dict) and isinstance(item.get('counts'), dict)}
        return view

    def _result_view(self, result):
        view = self._backend_view(result)
        for key in ('output', 'read_only', 'idempotent', 'scientific_workers_launched'):
            if key in result:
                view[key] = result[key]
        view['limitations'] = [self._sanitized(v) for v in result.get('limitations', [])]
        view['findings'] = [{'code': self._sanitized(f.get('code', '')), 'detail': self._sanitized(f.get('detail', ''))}
                            for f in result.get('findings', []) if isinstance(f, dict)]
        return view

    def _receipt(self, job):
        path = self._path(job['name'], 'run.json')
        if not path.exists():
            return None
        try:
            return read_json(path)
        except (OSError, ControlError):
            # A live atomic receipt replacement can race a poll. Never invent
            # progress from an unreadable snapshot; backend verification decides.
            return None

    def _saved_identity(self, job, result):
        """Bind the UI label to the exact manifest and saved stage identities.

        Current backend verification remains the scientific authority. Reopening
        uses this same local link only to withhold misleading display authority;
        it never promotes a saved receipt into a new verified completion.
        """
        manifest_path = self._path(job['name'], 'manifest.json')
        try:
            raw = manifest_path.read_bytes()
            if len(raw) > JSON_BYTES:
                raise ValueError('bounded manifest required')
            manifest = decode_json(raw.decode('utf-8-sig'))
        except (OSError, UnicodeError, ValueError) as error:
            raise ControlError('Saved detector identity cannot be read; preserve the output for inspection.',
                               'invalid_saved_identity') from error
        if (not isinstance(manifest, dict) or manifest.get('kind') != KIND or
                manifest.get('schema_version') != 1 or manifest.get('name') != job['name'] or
                hashlib.sha256(raw).hexdigest() != result.get('manifest_sha256')):
            raise ControlError('Saved detector manifest does not match the backend receipt.', 'invalid_saved_identity')
        plan = manifest.get('plan')
        model = plan.get('model') if isinstance(plan, dict) else None
        groups = plan.get('groups') if isinstance(plan, dict) else None
        if (model not in DETECTORS or not isinstance(groups, list) or len(groups) != 2 or
                any(not isinstance(g, dict) or not isinstance(g.get('key'), str) or
                    not g['key'].startswith(model + '-') for g in groups)):
            raise ControlError('Saved detector/group identity is unsupported.', 'invalid_saved_identity')
        keys = [g['key'] for g in groups]
        expected = {'charge': keys, 'calibration': [model], 'electronics': keys}
        stages = result.get('stages')
        if (len(set(keys)) != len(keys) or not isinstance(stages, dict) or set(stages) != set(PHASES) or
                any(not isinstance(stages[p], dict) or stages[p].get('expected_keys') != expected[p] or
                    type(stages[p].get('expected_count')) is not int or stages[p]['expected_count'] != len(expected[p]) or
                    not isinstance(stages[p].get('completed_keys'), list) or
                    any(k not in expected[p] for k in stages[p]['completed_keys']) or
                    len(set(stages[p]['completed_keys'])) != len(stages[p]['completed_keys']) or
                    type(stages[p].get('completed_count')) is not int or
                    stages[p]['completed_count'] != len(stages[p]['completed_keys']) for p in PHASES)):
            raise ControlError('Saved detector and calibration/stage identities disagree.', 'invalid_saved_identity')
        if model != job['detector']:
            error = ControlError('Recorded detector ' + job['detector'] + ' differs from saved detector ' + model +
                                 '; continuation and result access are blocked. Preserve this discrepancy for inspection.',
                                 'detector_identity_mismatch')
            error.discrepancy = {'recorded_detector': job['detector'], 'saved_detector': model}
            raise error
        return model

    def _identity_block(self, job, error):
        job['status'] = 'blocked'
        job['error'] = {'code': error.code, 'message': self._sanitized(error)}
        job.pop('complete_sha256', None)
        if hasattr(error, 'discrepancy'):
            job['identity_mismatch'] = copy.deepcopy(error.discrepancy)

    def _verified_saved(self, job, result):
        """Backend validates full hashes; this checks the UI receipt/census link."""
        receipt = self._receipt(job)
        if not receipt or any(receipt.get(k) != result.get(k) for k in ('kind', 'schema_version', 'manifest_sha256', 'selected_census')):
            raise ControlError('Saved progress does not match the verified backend receipt.', 'invalid_saved_receipt')
        self._check_census(receipt)
        self._saved_identity(job, result)
        # Stale completed counts may be repaired by the shared backend, but the
        # saved progress cannot identify a different detector or stage cohort.
        self._saved_identity(job, receipt)
        if result['status'] in TERMINAL:
            complete_path = self._path(job['name'], 'COMPLETE.json')
            if (not complete_path.is_file() or receipt.get('status') != result['status'] or
                    receipt.get('verification_final') is not True or receipt.get('stages') != result.get('stages')):
                raise ControlError('Terminal completion is missing its verified saved receipt.', 'missing_complete')
            complete = read_json(complete_path)
            stages = result.get('stages')
            if (complete.get('kind') != KIND or complete.get('manifest_sha256') != result.get('manifest_sha256') or
                    not isinstance(stages, dict) or set(stages) != set(PHASES) or
                    complete.get('completed_keys') != {p: stages[p].get('expected_keys') for p in PHASES} or
                    any(stages[p].get('completed_keys') != stages[p].get('expected_keys') or
                        stages[p].get('completed_count') != stages[p].get('expected_count') for p in PHASES)):
                raise ControlError('Terminal stage identities do not agree with COMPLETE.', 'invalid_saved_receipt')
            # The web server may serve only fixed files whose hashes are bound
            # by this independently validated COMPLETE serialization.
            with self._lock:
                job['complete_sha256'] = hashlib.sha256(complete_path.read_bytes()).hexdigest()
                job['manifest_sha256'] = result['manifest_sha256']
                job.pop('verification_required', None)
        elif result['status'] != 'paused':
            raise ControlError('Unexpected verified saved status.', 'invalid_backend_receipt')
        with self._lock:
            job.pop('identity_mismatch', None)
        return result

    def check(self, name, detector):
        name, detector = self._name(name), self._detector(detector)
        with self._lock:
            self._guard_idle()
            if self._path(name).exists() or any(j['name'].casefold() == name.casefold() for j in self._jobs):
                raise ControlError('This output name is already recorded or exists. Use a new name.', 'output_exists')
            self._checking = True
        try:
            argv = self._argv(name, detector, dry=True)
            result = self._command(argv)
            if result.get('status') != 'planned' or result.get('read_only') is not True or result.get('scientific_workers_launched') != 0:
                raise ControlError('Input check did not return a read-only planned receipt.', 'invalid_backend_receipt')
            return dict(self._result_view(result), name=name, detector=detector, command=argv,
                        runtime_choice=copy.deepcopy(self._last_runtime_choice))
        finally:
            with self._lock:
                self._checking = False

    def start(self, name, detector):
        name, detector = self._name(name), self._detector(detector)
        with self._lock:
            self._guard_idle()
            if self._path(name).exists() or any(j['name'].casefold() == name.casefold() for j in self._jobs):
                raise ControlError('This output name is already recorded or exists. Use a new name.', 'output_exists')
            job = {'id': uuid.uuid4().hex, 'name': name, 'detector': detector, 'output': BASE + '/' + name,
                   'status': 'preflight', 'stop_requested': False, 'child': None, 'logs': [],
                   'created_at': utc_now(), 'updated_at': utc_now(), 'backend': {}, 'result': {}, 'command': []}
            self._jobs.append(job)
            try:
                return self._launch(job, resume=False)
            except OSError:
                # Failed reservation is not an active job. Keep the pending
                # bytes for inspection while restoring prior in-memory state.
                self._jobs.remove(job)
                raise

    def resume(self, name):
        name = self._name(name)
        with self._lock:
            self._guard_idle()
            found = [j for j in self._jobs if j['name'] == name]
            if not found:
                raise ControlError('Only outputs recorded by this local interface can be resumed.', 'unknown_run')
            job = found[-1]
            if not self._path(name).is_dir():
                raise ControlError('The recorded output is missing; it cannot be resumed.', 'missing_output')
            prior = copy.deepcopy(job)
            job.update(status='preflight', stop_requested=False, updated_at=utc_now())
            job.pop('error', None)
            job.pop('complete_sha256', None)
            job.pop('verification_required', None)
            try:
                return self._launch(job, resume=True)
            except OSError:
                job.clear()
                job.update(prior)
                raise

    def _launch(self, job, resume):
        # Durable reservation must succeed before any active mark or dispatch.
        self._persist()
        self._active = job['id']
        initial = self._public_job(job)
        self._thread = threading.Thread(target=self._work, args=(job, resume),
                                        name='local-native-readout-' + job['id'][:8], daemon=True)
        self._thread.start()
        return initial

    def stop(self, job_id):
        with self._lock:
            found = [j for j in self._jobs if j['id'] == job_id]
            if not found:
                raise ControlError('Unknown owned job.', 'unknown_job')
            job = found[-1]
            if self._active == job_id:
                job['stop_requested'] = True
                job['status'] = 'stop-requested'
                job['updated_at'] = utc_now()
                self._persist()
            return self._public_job(job)

    def _work(self, job, resume):
        try:
            result = self._command(self._argv(job['name'], None if resume else job['detector'], resume=resume, dry=True), job)
            if resume:
                self._verified_saved(job, result)
            elif result.get('status') != 'planned' or result.get('read_only') is not True or result.get('scientific_workers_launched') != 0:
                raise ControlError('Preflight was not a read-only plan.', 'invalid_backend_receipt')
            with self._lock:
                job.update(backend=self._backend_view(result), result=self._result_view(result))
                if result['status'] in TERMINAL:
                    job['status'] = result['status']
                    return  # Last-step completion always wins over a late Stop.
                if job['stop_requested']:
                    job['status'] = 'stopped' if self._path(job['name']).exists() else 'cancelled'
                    return
                job['status'] = 'running'
                self._persist()
            while True:
                # The dispatch boundary and stop decision share the same lock.
                # A Stop accepted before this mark prevents the next invocation;
                # after the mark it waits for this declared current step.
                with self._lock:
                    if job['stop_requested']:
                        job['status'] = 'stopped' if self._path(job['name']).exists() else 'cancelled'
                        return
                    if result.get('status') in ('paused', *TERMINAL):
                        self._saved_identity(job, result)
                    job['step_dispatched_at'] = utc_now()
                    self._persist()
                result = self._command(self._argv(job['name'], None if resume else job['detector'], resume=resume, step=True), job)
                if result.get('status') not in ('paused', *TERMINAL):
                    raise ControlError('A step returned an unexpected status.', 'invalid_backend_receipt')
                # Independent shared-backend saved-data verification is mandatory
                # even when a successful command claims completion.
                verified = self._command(self._argv(job['name'], resume=True, dry=True), job)
                self._verified_saved(job, verified)
                if any(verified.get(k) != result.get(k) for k in ('status', 'manifest_sha256', 'selected_census', 'stages')):
                    raise ControlError('Step and saved verification disagree.', 'invalid_saved_receipt')
                with self._lock:
                    job.update(backend=self._backend_view(verified), result=self._result_view(verified), updated_at=utc_now())
                    if verified['status'] in TERMINAL:
                        job['status'] = verified['status']
                        return
                    if job['stop_requested']:
                        job['status'] = 'stopped'
                        return
                    job['status'] = 'running'
                    self._persist()
                resume = True  # Selectors are absent from every subsequent call.
        except BaseException as error:
            with self._lock:
                code = getattr(error, 'code', 'controller_failed')
                try:
                    has_output = self._path(job['name']).exists()
                except ControlError:
                    has_output = False
                job['status'] = 'failed' if has_output else 'blocked'
                job['error'] = {'code': code, 'message': self._sanitized(error)}
                if code in ('detector_identity_mismatch', 'invalid_saved_identity'):
                    self._identity_block(job, error)
                if hasattr(error, 'result'):
                    job.update(backend=self._backend_view(error.result), result=self._result_view(error.result))
                    if error.result.get('status') in ('blocked', 'failed'):
                        job['status'] = error.result['status']
                self._log(job, str(error) + '\n')
        finally:
            with self._lock:
                job['updated_at'] = utc_now()
                self._active = None
                self._persist()

    def _public_job(self, job):
        result = copy.deepcopy({k: job[k] for k in ('id', 'name', 'detector', 'output', 'status',
                               'stop_requested', 'logs', 'created_at', 'updated_at', 'backend',
                               'result', 'command', 'error', 'complete_sha256', 'manifest_sha256',
                               'verification_required', 'runtime_choice') if k in job})
        if job.get('identity_mismatch'):
            result['identity_mismatch'] = copy.deepcopy(job['identity_mismatch'])
            result['detector'] = job['identity_mismatch']['saved_detector']
            result['status'] = 'blocked'
            result.pop('complete_sha256', None)
        receipt = self._receipt(job)
        if receipt:
            result['backend'] = self._backend_view(receipt)
        # Persisted controller state and backend receipts are private inputs too.
        # Whitelist displayed fields; do not forward runtime/source/private paths.
        result['logs'] = [self._sanitized(s) for s in result.get('logs', [])][-LOG_LINES:]
        result['can_resume'] = self._path(job['name']).is_dir() and self._active != job['id']
        def safe_display(value):
            if isinstance(value, str):
                return self._sanitized(value)
            if isinstance(value, list):
                return [safe_display(v) for v in value]
            if isinstance(value, dict):
                return {self._sanitized(k): safe_display(v) for k, v in value.items()}
            return value
        return safe_display(result)

    def runs(self):
        with self._lock:
            result = []
            for job in reversed(self._jobs):
                item = self._public_job(job)
                files = []
                identity_blocked = item.get('error', {}).get('code') in ('detector_identity_mismatch', 'invalid_saved_identity')
                inventory = () if identity_blocked else ('manifest.json', 'run.json', 'COMPLETE.json', 'worker/report.json',
                            'worker/' + job['detector'] + '/scalars.jsonl', 'worker/' + job['detector'] + '/traces.jsonl')
                for rel in inventory:
                    path = self._path(job['name'], rel)
                    if path.is_file():
                        files.append({'path': job['output'] + '/' + rel, 'label': rel, 'bytes': path.stat().st_size})
                item['files'] = files
                result.append(item)
            return result

    def snapshot(self):
        with self._lock:
            jobs = [self._public_job(j) for j in reversed(self._jobs[-20:])]
            active = next((j for j in jobs if j['id'] == self._active), None)
            return {'active': active, 'jobs': jobs, 'runs': self.runs(), 'checking': self._checking}

    def wait_for_idle(self, timeout=10):
        """Finite test/local shutdown convenience; never kills or resumes a job."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                if self._active is None:
                    return self.snapshot()
            time.sleep(0.01)
        raise TimeoutError('Owned job is still active.')
