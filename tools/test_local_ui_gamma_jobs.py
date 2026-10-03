"""Injected-runner Gamma ownership tests; no real Gamma/Julia invocation."""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import local_ui_gamma_jobs as G
import local_ui_jobs as C

FIXTURES = Path(__file__).resolve().parents[1] / '.local/m11k-gamma-control-v1/backend/test-fixtures'
CHECK = dict(status='checked_no_execution', models=['AK02', 'SAP22'], radiation_primaries=40,
             selected_primaries=6, native_calls=0, injection_calibrations=0)
VERIFIED = dict(kind=G.KIND, status='completed', radiation_primaries=40,
                selected_primaries=6, unprocessed_primaries=34)


def write_json(path, value):
    path.write_text(json.dumps(value, allow_nan=False), encoding='utf-8')


def finished_fixture(root, output, threads=2, report_bytes=b'{"fixture":true}'):
    """Adapter receipt binding only; never a scientific-validator substitute."""
    folder = Path(root) / output
    folder.mkdir(parents=True, exist_ok=True)
    artifacts = {}
    for model in G.MODELS:
        (folder / model).mkdir(exist_ok=True)
    for artifact in G.FILES[2:]:
        body = report_bytes if artifact.endswith('/report.json') else b'fixture exact bytes\n'
        (folder / artifact).write_bytes(body)
        artifacts[artifact] = {'sha256': hashlib.sha256(body).hexdigest(), 'bytes': len(body)}
    run = dict(kind=G.KIND, schema_version=1, status='completed', threads=threads,
        native_failure_policy='abort', source_pins={'fixture': '0' * 64},
        stages=[dict(model_id=model, exit_code=0, arguments=['private fixture path']) for model in G.MODELS],
        additional_radiation_calls=0, field_solve_seconds=0.0, orchestration_seconds=0.125)
    write_json(folder / 'run.json', run)
    complete = dict(kind=G.KIND, schema_version=1, status='completed', artifacts=artifacts,
        source_pins=run['source_pins'], run_sha256=hashlib.sha256((folder / 'run.json').read_bytes()).hexdigest(),
        counts=dict(radiation_primaries=40, selected_primaries=6, unprocessed_primaries=34,
                    native_calls=4, injection_calibrations=2))
    write_json(folder / 'COMPLETE.json', complete)
    return folder


class Runner:
    def __init__(self):
        self.calls = []
        self.run_entered = threading.Event()
        self.run_release = threading.Event(); self.run_release.set()
        self.check_entered = threading.Event()
        self.check_release = threading.Event(); self.check_release.set()
        self.fail_mode = None
        self.report_bytes = b'{"fixture":true}'
        self.before_run = None

    def __call__(self, argv, *, cwd, env, on_output, on_spawn):
        mode = argv[argv.index('tools/gamma_native_example.py') + 1]
        self.calls.append((mode, argv.copy(), env.copy()))
        if mode == 'run' and self.before_run:
            self.before_run()
        on_spawn(70001, 'fixture-driver')
        on_output('private diagnostic C:/private/input/cache\n')
        if mode == 'check':
            self.check_entered.set(); self.check_release.wait(3)
            result = CHECK.copy()
        elif mode == 'run':
            self.run_entered.set(); self.run_release.wait(3)
            output = argv[argv.index('--output') + 1]
            threads = int(argv[argv.index('--threads') + 1])
            folder = finished_fixture(cwd, output, threads, self.report_bytes)
            result = dict(status='completed', output=str(folder), native_calls=4, injection_calibrations=2)
        else:
            result = VERIFIED.copy()
        if self.fail_mode == mode:
            return {'exit_code': 2, 'output': 'private native failure C:/private/input'}
        return {'exit_code': 0, 'output': json.dumps(result)}


class GammaJobs(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(G, 'gamma_environment', side_effect=lambda mode, threads=None:
            dict(os.environ, PYTHONDONTWRITEBYTECODE='1', OPENBLAS_NUM_THREADS='1',
                 OMP_NUM_THREADS='1', JULIA_PKG_OFFLINE='true',
                 **({'JULIA_NUM_THREADS': str(threads)} if threads is not None else {}))))
        FIXTURES.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=FIXTURES)
        self.root = Path(self.temp.name)
        (self.root / 'tools').mkdir()
        (self.root / 'tools/gamma_native_example.py').write_bytes(b'fixture only')
        self.runner = Runner()
        self.controller = G.GammaController(self.root, self.runner, identity_probe=lambda pid: None)

    def tearDown(self):
        self.runner.run_release.set(); self.runner.check_release.set()
        self.controller.wait_for_idle()
        self.temp.cleanup()

    def completed(self, threads=2):
        checked = self.controller.check(threads)
        response = self.controller.start(checked['check_id'])
        state = self.controller.wait_for_idle()
        self.assertEqual(state['jobs'][0]['status'], 'completed')
        return self.controller._find(response['job']['id'])

    def test_default_check_bound_threads_and_fixed_serial_run_argv(self):
        checked = self.controller.check()
        self.assertEqual((checked['threads'], checked['models'], checked['unprocessed_primaries']), (2, ['AK02', 'SAP22'], 34))
        job = self.controller.start(checked['check_id'])['job']
        final = self.controller.wait_for_idle()['jobs'][0]
        modes = [call[0] for call in self.runner.calls]
        self.assertEqual(modes, ['check', 'run', 'verify'])
        argv = self.runner.calls[1][1]
        self.assertEqual(argv[-4:], ['--threads', '2', '--native-failure-policy', 'abort'])
        self.assertEqual(self.runner.calls[1][2]['JULIA_NUM_THREADS'], '2')
        self.assertEqual(final['progress']['completed_models'], ['AK02', 'SAP22'])
        self.assertEqual(final['files'], list(G.FILES)); self.assertTrue(final['verified'])
        self.assertTrue(job['label'].startswith('ui-gamma-'))
        self.assertNotIn('/example', json.dumps(final)); self.assertNotIn('private', json.dumps(final))

    def test_one_thread_and_existing_pvpython_flags(self):
        with patch.object(G.sys, 'executable', 'C:/fixture/pvpython.exe'):
            job = self.completed(1)
        argv = self.runner.calls[1][1]
        self.assertEqual(argv[:5], ['C:/fixture/pvpython.exe', '--no-mpi', '--disable-registry', '-B', 'tools/gamma_native_example.py'])
        self.assertEqual(job['threads'], 1)

    def test_invalid_settings_and_unchecked_start_never_dispatch(self):
        for value in (True, False, 0, 3, 2.0, '2', None):
            with self.assertRaises(C.ControlError): self.controller.check(value)
        for value in ('', '0' * 64, '../path', None, 2):
            with self.assertRaises(C.ControlError): self.controller.start(value)
        self.assertEqual(self.runner.calls, [])

    def test_check_receipt_typed_identity_not_bool_census(self):
        def bad(*args, **kwargs):
            return {'exit_code': 0, 'output': json.dumps({**CHECK, 'radiation_primaries': 40.0})}
        self.controller._runner = bad
        with self.assertRaises(C.ControlError): self.controller.check()
        self.assertFalse(self.controller.snapshot()['checking'])
        self.assertEqual(self.controller._checks, {})

    def test_check_persistence_failure_no_start_or_ticket(self):
        with patch.object(self.controller, '_persist', side_effect=OSError('fixture persist failure')):
            with self.assertRaises(OSError): self.controller.check()
        self.assertEqual(self.controller._checks, {})
        self.assertEqual([v[0] for v in self.runner.calls], ['check'])

    def test_reservation_failure_prevents_thread_and_preserves_ticket(self):
        ticket = self.controller.check()['check_id']
        with patch.object(self.controller, '_persist', side_effect=OSError('fixture persist failure')):
            with self.assertRaises(OSError): self.controller.start(ticket)
        self.assertIsNone(self.controller._checks[ticket]['job_id'])
        self.assertEqual(self.controller._jobs, [])
        self.assertEqual([v[0] for v in self.runner.calls], ['check'])

    def test_consumed_ticket_and_dispatch_uncertainty_durable_before_spawn(self):
        ticket = self.controller.check()['check_id']
        def inspect():
            state = C.read_json(self.root / C.STATE / 'gamma-jobs.json')
            self.assertEqual(state['checks'][ticket]['job_id'], state['jobs'][0]['id'])
            self.assertEqual(state['jobs'][0]['status'], 'dispatch-uncertain')
            self.assertTrue(state['jobs'][0]['uncertain'])
            self.assertFalse((self.root / state['jobs'][0]['output']).exists())
        self.runner.before_run = inspect
        self.completed_from_ticket = self.controller.start(ticket)
        self.assertEqual(self.controller.wait_for_idle()['jobs'][0]['status'], 'completed')

    def test_concurrent_duplicate_ticket_starts_exactly_one_worker(self):
        ticket = self.controller.check()['check_id']
        self.runner.run_release.clear()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.controller.start(ticket), range(2)))
        self.assertEqual(results[0]['job']['id'], results[1]['job']['id'])
        self.assertTrue(self.runner.run_entered.wait(2))
        self.assertEqual([v[0] for v in self.runner.calls].count('run'), 1)
        self.runner.run_release.set(); self.controller.wait_for_idle()
        reopened = G.GammaController(self.root, self.runner, identity_probe=lambda pid: None)
        self.assertEqual(reopened.start(ticket)['job']['id'], results[0]['job']['id'])
        self.assertEqual([v[0] for v in self.runner.calls].count('run'), 1)

    def test_second_ticket_refused_while_worker_live_and_lock_released(self):
        first = self.controller.check()['check_id']; second = self.controller.check()['check_id']
        self.runner.run_release.clear(); self.controller.start(first)
        self.assertTrue(self.runner.run_entered.wait(2))
        with self.controller._lock:
            self.assertTrue(self.controller.snapshot()['busy'])
        with self.assertRaises(C.ControlError): self.controller.start(second)
        with self.assertRaises(C.ControlError): self.controller.check()

    def test_shared_peer_blocks_cs_check_start_resume_and_gamma_check_start(self):
        lock = threading.RLock()
        cs = C.Controller(self.root, runner=lambda *a, **k: self.fail('Cs runner dispatched'), coordination_lock=lock)
        self.controller._lock = lock
        self.controller.set_peer_busy(cs.own_busy); cs.set_peer_busy(self.controller.own_busy)
        cs._checking = True
        with self.assertRaises(C.ControlError): self.controller.check()
        ticket = 'a' * 64
        self.controller._checks[ticket] = dict(threads=2, created_at=C.utc_now(), job_id=None)
        with self.assertRaises(C.ControlError): self.controller.start(ticket)
        cs._checking = False; self.controller._checking = True
        for operation in (lambda: cs.check('fresh', 'AK02'), lambda: cs.start('fresh', 'AK02'), lambda: cs.resume('fresh')):
            with self.assertRaises(C.ControlError): operation()
        self.controller._checking = False
        self.assertEqual(self.runner.calls, [])

    def test_two_coordinated_checks_race_only_one_check_enters(self):
        lock = threading.RLock()
        cs = C.Controller(self.root, coordination_lock=lock)
        self.controller._lock = lock
        self.controller.set_peer_busy(cs.own_busy); cs.set_peer_busy(self.controller.own_busy)
        self.runner.check_release.clear()
        task = threading.Thread(target=self.controller.check); task.start()
        self.assertTrue(self.runner.check_entered.wait(2))
        with self.assertRaises(C.ControlError): cs.check('fresh', 'AK02')
        with self.assertRaises(C.ControlError): cs.start('fresh', 'SAP22')
        self.runner.check_release.set(); task.join(3)
        self.assertFalse(task.is_alive())

    def test_coordinated_cs_start_and_resume_race_gamma_start_one_dispatch(self):
        # Both real adapters share the reservation lock; only the Cs worker
        # body is injected so no existing scientific CLI is used here.
        for resume in (False, True):
            root = self.root / ('race-resume' if resume else 'race-start')
            root.mkdir()
            lock = threading.RLock(); release = threading.Event(); entered = threading.Event()
            cs = C.Controller(root, coordination_lock=lock)
            runner = Runner(); runner.run_release.clear()
            gamma = G.GammaController(root, runner, identity_probe=lambda pid: None,
                                      coordination_lock=lock, peer_busy=cs.own_busy)
            cs.set_peer_busy(gamma.own_busy)
            ticket = gamma.check()['check_id']
            def cs_work(job, resuming):
                entered.set(); release.wait(3)
                with lock:
                    job['status'] = 'blocked'; cs._active = None; cs._persist()
            cs._work = cs_work
            if resume:
                (root / C.BASE / 'owned').mkdir(parents=True)
                cs._jobs.append(dict(id='c' * 32, name='owned', detector='AK02', output=C.BASE + '/owned',
                    status='blocked', stop_requested=False, child=None, logs=[], created_at=C.utc_now(),
                    updated_at=C.utc_now(), backend={}, result={}, command=[]))
            barrier = threading.Barrier(2)
            def race(operation):
                barrier.wait()
                try:
                    operation(); return 'accepted'
                except C.ControlError:
                    return 'refused'
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                    a = pool.submit(race, lambda: gamma.start(ticket))
                    b = pool.submit(race, lambda: cs.resume('owned') if resume else cs.start('fresh', 'AK02'))
                    outcomes = [a.result(), b.result()]
                self.assertCountEqual(outcomes, ['accepted', 'refused'])
                self.assertTrue(runner.run_entered.wait(2) if outcomes[0] == 'accepted' else entered.wait(2))
                self.assertEqual(int(entered.is_set()) + int(runner.run_entered.is_set()), 1)
            finally:
                release.set(); runner.run_release.set()
                cs.wait_for_idle(); gamma.wait_for_idle()

    def test_progress_requires_observed_request_and_prefix_not_driver_pid(self):
        ticket = self.controller.check()['check_id']
        self.runner.run_release.clear(); response = self.controller.start(ticket)
        self.assertTrue(self.runner.run_entered.wait(2))
        job = self.controller._find(response['job']['id'])
        public = self.controller.snapshot()['jobs'][0]
        self.assertEqual((public['progress']['current_model'], public['progress']['stage']), (None, 'waiting'))
        folder = self.controller._path(job); folder.mkdir(parents=True)
        run = dict(kind=G.KIND, schema_version=1, status='running', stages=[])
        write_json(folder / 'run.json', run)
        (folder / 'AK02').mkdir(); (folder / 'AK02/request.json').write_bytes(b'fixture')
        public = self.controller.snapshot()['jobs'][0]
        self.assertEqual(public['progress'], dict(completed_models=[], current_model='AK02', stage='native_models'))
        run['stages'] = [dict(model_id='AK02', exit_code=0)]; write_json(folder / 'run.json', run)
        public = self.controller.snapshot()['jobs'][0]
        self.assertEqual(public['progress']['completed_models'], ['AK02'])
        self.assertIsNone(public['progress']['current_model'])
        (folder / 'SAP22').mkdir(); (folder / 'SAP22/request.json').write_bytes(b'fixture')
        self.assertEqual(self.controller.snapshot()['jobs'][0]['progress']['current_model'], 'SAP22')
        run['stages'][0]['exit_code'] = False; write_json(folder / 'run.json', run)
        self.assertEqual(self.controller.snapshot()['jobs'][0]['progress']['completed_models'], [])

    def test_strict_failure_keeps_uncertainty_raw_local_evidence_no_retry(self):
        self.runner.fail_mode = 'run'
        ticket = self.controller.check()['check_id']
        self.controller.start(ticket)
        job = self.controller.wait_for_idle()['jobs'][0]
        self.assertEqual(job['status'], 'failed'); self.assertFalse(job['verified'])
        self.assertTrue(self.controller.own_busy())
        self.assertEqual(job['error'], dict(code='backend_refused', message=G.ERRORS['backend_refused']))
        self.assertNotIn('private', json.dumps(job))
        self.assertIn('private native failure', (self.root / C.STATE / 'gamma-logs' / (job['id'] + '.log')).read_text())
        self.assertFalse((self.root / G.BASE / job['label'] / 'adapter.log').exists())
        with self.assertRaises(C.ControlError): self.controller.check()
        self.assertEqual([v[0] for v in self.runner.calls], ['check', 'run'])

    def test_dead_unknown_reused_driver_reopen_never_clears_uncertainty(self):
        ticket = self.controller.check()['check_id']
        self.runner.run_release.clear(); self.controller.start(ticket)
        self.assertTrue(self.runner.run_entered.wait(2))
        for probe in (lambda pid: None, lambda pid: 'unknown', lambda pid: 'different-reused-pid'):
            reopened = G.GammaController(self.root, self.runner, identity_probe=probe)
            self.assertTrue(reopened.own_busy())
            self.assertEqual(reopened.snapshot()['jobs'][0]['status'], 'blocked')
            with self.assertRaises(C.ControlError): reopened.check()
        self.assertEqual([v[0] for v in self.runner.calls].count('run'), 1)

    def test_completed_reload_requires_explicit_verify_no_constructor_or_get_calls(self):
        job = self.completed()
        before = len(self.runner.calls)
        reopened = G.GammaController(self.root, self.runner, identity_probe=lambda pid: None)
        state_bytes = (self.root / C.STATE / 'gamma-jobs.json').read_bytes()
        for _ in range(2):
            self.assertTrue(reopened.snapshot()['busy'])
            observed = reopened.snapshot()['jobs'][0]
            self.assertEqual(observed['status'], 'verification-required')
            self.assertTrue(observed['can_verify']); self.assertFalse(observed['verified'])
            self.assertEqual(observed['files'], [])
        self.assertEqual(len(self.runner.calls), before)
        self.assertEqual((self.root / C.STATE / 'gamma-jobs.json').read_bytes(), state_bytes)
        checked = reopened.verify(job['id'])
        self.assertEqual(checked['status'], 'verified')
        self.assertEqual(checked['scientific_workers_launched'], 0)
        self.assertFalse(reopened.own_busy())
        self.assertEqual(self.runner.calls[-1][0], 'verify')

    def test_completed_reload_missing_or_corrupt_receipts_retains_verification_hold(self):
        job = self.completed()
        unused_ticket = self.controller.check()['check_id']
        folder = self.controller._path(job)
        original_complete = (folder / 'COMPLETE.json').read_bytes()
        original_run = (folder / 'run.json').read_bytes()
        state_bytes = (self.root / C.STATE / 'gamma-jobs.json').read_bytes()
        before = len(self.runner.calls)
        for damage in ('missing_complete', 'corrupt_run'):
            with self.subTest(damage=damage):
                (folder / 'COMPLETE.json').write_bytes(original_complete)
                (folder / 'run.json').write_bytes(original_run)
                if damage == 'missing_complete':
                    (folder / 'COMPLETE.json').unlink()
                else:
                    (folder / 'run.json').write_bytes(b'not JSON')
                reopened = G.GammaController(self.root, self.runner, identity_probe=lambda pid: None)
                observed = reopened.snapshot()['jobs'][0]
                self.assertEqual(observed['status'], 'verification-required')
                self.assertFalse(observed['verified']); self.assertFalse(observed['can_verify'])
                self.assertEqual(observed['files'], [])
                self.assertIsNone(observed['complete_sha256']); self.assertIsNone(observed['run_sha256'])
                self.assertFalse(reopened._jobs[0]['uncertain'])
                self.assertTrue(reopened.snapshot()['busy'])
                with self.assertRaises(C.ControlError): reopened.check()
                with self.assertRaises(C.ControlError): reopened.start(unused_ticket)
                with self.assertRaises(C.ControlError): reopened.verify(job['id'])
                self.assertEqual(len(self.runner.calls), before)
                self.assertEqual((self.root / C.STATE / 'gamma-jobs.json').read_bytes(), state_bytes)

    def test_can_verify_ignores_unrelated_peer_but_excludes_own_uncertain_jobs(self):
        job = self.completed()
        self.controller.set_peer_busy(lambda: True)
        self.assertTrue(self.controller.snapshot()['jobs'][0]['can_verify'])
        before = len(self.runner.calls)
        self.assertEqual(self.controller.verify(job['id'])['scientific_workers_launched'], 0)
        self.assertEqual([call[0] for call in self.runner.calls[before:]], ['verify'])
        with self.assertRaises(C.ControlError): self.controller.check()
        other = dict(job, id='f' * 32, output=G.BASE + '/ui-gamma-' + 'f' * 32,
                     status='blocked', uncertain=True, child=None)
        self.controller._jobs.append(other)
        current = next(j for j in self.controller.snapshot()['jobs'] if j['id'] == job['id'])
        self.assertFalse(current['can_verify'])
        before_runs = [call[0] for call in self.runner.calls].count('run')
        with self.assertRaises(C.ControlError): self.controller.verify(job['id'])
        self.assertTrue(other['uncertain'])
        self.assertTrue(self.controller.snapshot()['busy'])
        with self.assertRaises(C.ControlError): self.controller.check()
        self.assertEqual([call[0] for call in self.runner.calls].count('run'), before_runs)

    def test_multiple_completed_reload_can_verify_serially_without_new_run(self):
        first = self.completed()
        second = self.completed()
        before_runs = [call[0] for call in self.runner.calls].count('run')
        reopened = G.GammaController(self.root, self.runner, identity_probe=lambda pid: None)
        snapshot = reopened.snapshot()
        self.assertTrue(snapshot['busy'])
        self.assertTrue(all(j['can_verify'] and j['status'] == 'verification-required' for j in snapshot['jobs']))
        self.assertTrue(all(not j['uncertain'] for j in reopened._jobs))
        reopened.verify(first['id'])
        self.assertTrue(reopened.snapshot()['busy'])
        with self.assertRaises(C.ControlError): reopened.check()
        reopened.verify(second['id'])
        self.assertFalse(reopened.snapshot()['busy'])
        self.assertEqual([call[0] for call in self.runner.calls].count('run'), before_runs)

    def test_verify_own_active_checking_incomplete_unknown_and_live_driver_refuse(self):
        job = self.completed()
        self.controller.set_peer_busy(lambda: True)
        self.controller._active = job['id']
        with self.assertRaises(C.ControlError): self.controller.verify(job['id'])
        self.controller._active = None; self.controller._checking = True
        with self.assertRaises(C.ControlError): self.controller.verify(job['id'])
        self.controller._checking = False
        for identity in ('unknown', 'fixture-driver'):
            job['child'] = dict(pid=123, identity='fixture-driver')
            self.controller._identity_probe = lambda pid: identity
            self.assertFalse(self.controller.snapshot()['jobs'][0]['can_verify'])
            with self.assertRaises(C.ControlError): self.controller.verify(job['id'])
        job['child'] = None
        with self.assertRaises(C.ControlError): self.controller.verify('f' * 32)
        self.controller._path(job, 'COMPLETE.json').unlink()
        with self.assertRaises(C.ControlError): self.controller.verify(job['id'])

    def test_verify_persistence_failure_never_dispatches_or_leaves_checking(self):
        job = self.completed(); before = len(self.runner.calls)
        with patch.object(self.controller, '_persist', side_effect=OSError('fixture failure')):
            with self.assertRaises(OSError): self.controller.verify(job['id'])
        self.assertEqual(len(self.runner.calls), before)
        self.assertFalse(self.controller.snapshot()['checking'])
        self.assertFalse(self.controller.snapshot()['jobs'][0]['verified'])

    def test_public_blocking_flag_matches_existing_guard_not_failed_label(self):
        completed=self.completed()
        failed=dict(completed,id='f'*32,output=G.BASE+'/ui-gamma-'+'f'*32,
                    status='failed',uncertain=False,child=None)
        self.controller._jobs.append(failed)
        public={j['id']:j for j in self.controller.snapshot()['jobs']}
        self.assertFalse(public[completed['id']]['blocks_new_work'])
        self.assertFalse(public[failed['id']]['blocks_new_work'])
        self.assertEqual(public[failed['id']]['status'],'failed')
        self.assertFalse(self.controller.own_busy());self.controller._guard_idle()
        before=len(self.runner.calls)
        for uncertain,child,identity in ((True,None,None),(False,{'pid':999999,'identity':'old'},'unknown'),
                                         (False,{'pid':999999,'identity':'old'},'old')):
            failed.update(uncertain=uncertain,child=child);self.controller._identity_probe=lambda pid:identity
            self.assertTrue(self.controller._public_job(failed)['blocks_new_work'])
            self.assertTrue(self.controller.own_busy())
            with self.assertRaises(C.ControlError):self.controller._guard_idle()
        failed.update(uncertain=False,child=None);completed['status']='verification-required'
        public=self.controller._public_job(completed)
        self.assertTrue(public['blocks_new_work']);self.assertTrue(public['can_verify'])
        self.assertEqual(len(self.runner.calls),before)

    def test_rehashed_policy_or_threads_receipt_refused_after_cli_claim(self):
        job = self.completed()
        for key, value in (('threads', 1), ('native_failure_policy', 'record')):
            folder = finished_fixture(self.root, job['output'])
            run = C.read_json(folder / 'run.json'); run[key] = value
            write_json(folder / 'run.json', run)
            complete = C.read_json(folder / 'COMPLETE.json')
            complete['run_sha256'] = hashlib.sha256((folder / 'run.json').read_bytes()).hexdigest()
            write_json(folder / 'COMPLETE.json', complete)
            with self.assertRaises(C.ControlError): self.controller.verify(job['id'])
        self.assertFalse(self.controller.snapshot()['jobs'][0]['verified'])

    def test_download_exact_twelve_and_report_above_metadata_bound(self):
        self.runner.report_bytes = b'x' * (G.JSON_BYTES + 7)
        job = self.completed()
        for artifact in G.FILES:
            body, filename = self.controller.download(job['id'], artifact)
            self.assertEqual(body, self.controller._path(job, artifact).read_bytes())
            self.assertNotIn('/', filename)
        self.assertGreater(len(self.controller.download(job['id'], 'AK02/report.json')[0]), G.JSON_BYTES)

    def test_changed_and_deliberately_rehashed_complete_refuse_pinned_download(self):
        job = self.completed(); path = self.controller._path(job, 'AK02/signals.csv')
        original = path.read_bytes(); path.write_bytes(original + b'changed')
        with self.assertRaises(C.ControlError): self.controller.download(job['id'], 'AK02/signals.csv')
        complete_path = self.controller._path(job, 'COMPLETE.json')
        complete = C.read_json(complete_path)
        complete['artifacts']['AK02/signals.csv'] = dict(bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        write_json(complete_path, complete)
        with self.assertRaises(C.ControlError): self.controller.download(job['id'], 'AK02/signals.csv')
        with self.assertRaises(C.ControlError): self.controller.download(job['id'], 'COMPLETE.json')

    def test_changed_run_traversal_unknown_nonterminal_oversize_and_reparse_refuse(self):
        job = self.completed()
        for artifact in ('../run.json', 'AK02/../run.json', 'worker.log', 'gamma.html', 'C:/private'):
            with self.assertRaises(C.ControlError): self.controller.download(job['id'], artifact)
        with self.assertRaises(C.ControlError): self.controller.download('f' * 32, 'run.json')
        job['status'] = 'blocked'
        with self.assertRaises(C.ControlError): self.controller.download(job['id'], 'run.json')
        job['status'] = 'completed'
        path = self.controller._path(job, 'AK02/report.json')
        path.write_bytes(b'x' * (G.MAX_FILE_BYTES + 1))
        with self.assertRaises(C.ControlError): self.controller.download(job['id'], 'AK02/report.json')
        with patch.object(G, 'safe_path', side_effect=C.ControlError('reparse fixture')):
            with self.assertRaises(C.ControlError): self.controller.download(job['id'], 'run.json')
        self.controller._path(job, 'run.json').write_bytes(b'changed')
        with self.assertRaises(C.ControlError): self.controller.download(job['id'], 'run.json')

    def test_download_existing_reparse_or_symlink_component_refused(self):
        import stat
        job = self.completed()
        target = self.controller._path(job, 'COMPLETE.json')
        original = Path.lstat
        for symbolic in (False, True):
            def linked(path, *args, **kwargs):
                info = original(path, *args, **kwargs)
                if path == target:
                    return SimpleNamespace(st_mode=stat.S_IFLNK if symbolic else info.st_mode,
                                           st_file_attributes=0 if symbolic else 0x400)
                return info
            with patch.object(Path, 'lstat', linked):
                with self.assertRaises(C.ControlError): self.controller.download(job['id'], 'run.json')

    def test_state_identity_invalid_or_original_example_owned_claim_refuse(self):
        job = self.completed()
        state_path = self.root / C.STATE / 'gamma-jobs.json'
        state = C.read_json(state_path); state['jobs'][0]['output'] = G.BASE + '/example'
        write_json(state_path, state)
        with self.assertRaises(C.ControlError): G.GammaController(self.root, self.runner)


class GammaRuntime(unittest.TestCase):
    """Synthetic launchers only; preflight never executes Julia or a CLI."""
    def setUp(self):
        FIXTURES.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=FIXTURES)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.exe = self.root / 'synthetic-launcher.exe'
        self.exe.write_bytes(b'only synthetic bytes, never executable')
        self.enterContext(patch.object(G, 'JULIA_SHA', hashlib.sha256(self.exe.read_bytes()).hexdigest()))

    def test_explicit_pinned_preflight_child_only_and_bounded_threads(self):
        with patch.dict(os.environ, {'JULIA_EXE': str(self.exe)}, clear=True):
            before = dict(os.environ)
            with patch.object(G, 'julia_executable', side_effect=AssertionError('No replacement discovery')):
                check = G.gamma_environment('check')
                run = G.gamma_environment('run', 1)
            self.assertEqual(check['JULIA_EXE'], str(self.exe))
            self.assertEqual(run['JULIA_NUM_THREADS'], '1')
            self.assertEqual(run['OPENBLAS_NUM_THREADS'], '1')
            self.assertEqual(run['OMP_NUM_THREADS'], '1')
            self.assertEqual(dict(os.environ), before)

    def test_existing_windows_fallback_ignores_alias_without_global_change(self):
        fallback = self.root / '.julia/juliaup/julia-1.13.0+0.x64.w64.mingw32/bin/julia.exe'
        fallback.parent.mkdir(parents=True)
        fallback.write_bytes(self.exe.read_bytes())
        with patch.dict(os.environ, {'USERPROFILE': str(self.root), 'PATH': 'synthetic-WindowsApps'}, clear=True):
            before = dict(os.environ)
            with patch.object(G, 'julia_executable', side_effect=AssertionError('Do not use WindowsApps')):
                child = G.gamma_environment('check')
            self.assertEqual(child['JULIA_EXE'], str(fallback))
            self.assertEqual(dict(os.environ), before)

    def test_empty_missing_and_wrong_hash_refuse_before_check_ticket_or_runner(self):
        wrong = self.root / 'wrong.exe'
        wrong.write_bytes(b'wrong launcher')
        for value in ('', str(self.root / 'missing.exe'), str(wrong)):
            with self.subTest(value=value), patch.dict(os.environ, {'JULIA_EXE': value}, clear=True):
                runner = Runner()
                controller = G.GammaController(self.root, runner)
                with self.assertRaises(C.ControlError):
                    controller.check()
                self.assertEqual(runner.calls, [])
                self.assertEqual(controller._checks, {})
                self.assertFalse(controller.snapshot()['checking'])
                self.assertFalse(controller.snapshot()['busy'])

    def test_saved_verify_never_selects_or_hashes_current_launcher(self):
        with patch.dict(os.environ, {'JULIA_EXE': ''}, clear=True), \
                patch.object(G, 'existing_julia_environment', side_effect=AssertionError('No discovery')), \
                patch.object(G, 'julia_executable', side_effect=AssertionError('No discovery')), \
                patch.object(G.hashlib, 'sha256', side_effect=AssertionError('No launcher hash')):
            child = G.gamma_environment('verify', 2)
        self.assertEqual(child['JULIA_EXE'], '')
        self.assertEqual(child['JULIA_NUM_THREADS'], '2')


if __name__ == '__main__':
    unittest.main()
