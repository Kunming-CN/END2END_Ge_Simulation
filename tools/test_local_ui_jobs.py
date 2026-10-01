"""Finite mocked protocol acceptance; never launches PowerShell, Julia or physics."""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

import local_ui_jobs as J

ROOT = Path(__file__).absolute().parent.parent
CENSUS = dict(initial_primaries=3, zero_ge_primaries=1, nonzero_primaries=2, groups=2)


def planned():
    return dict(kind=J.KIND, schema_version=1, status='planned', verification_final=True,
                scientific_workers_launched=0, read_only=True, selected_census=CENSUS.copy(), findings=[])


def progress(model, done, status='paused'):
    ids = {'AK02': (2594, 3950), 'SAP22': (207, 263)}[model]
    keys = [model + '-e' + str(i) + '-d' + str(i) + '-g0' for i in ids]
    stages = {}
    for phase, expected, count in [('charge', keys, 2), ('calibration', [model], 1), ('electronics', keys, done)]:
        stages[phase] = dict(expected_keys=expected, completed_keys=expected[:count],
                             expected_count=len(expected), completed_count=count)
    return dict(kind=J.KIND, schema_version=1, status=status, verification_final=True,
                manifest_sha256='a' * 64, selected_census=CENSUS.copy(), stages=stages,
                scientific_workers_launched=1, findings=[])


def saved_manifest(target, name, model):
    keys = progress(model, 0)['stages']['charge']['expected_keys']
    raw = json.dumps(dict(kind=J.KIND, schema_version=1, name=name,
                         plan=dict(model=model, groups=[dict(key=k) for k in keys]))).encode('utf-8')
    (target / 'manifest.json').write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


class FakeBackend:
    def __init__(self, root):
        self.root = root
        self.calls = []
        self.before = None
        self.after = None
        self.override = None

    def __call__(self, argv, *, cwd, env, on_output, on_spawn):
        self.calls.append((argv.copy(), env.copy()))
        on_spawn(999991, 'fake-created')
        if self.before:
            self.before(argv)
        if self.override:
            value = self.override(argv)
            if value is not None:
                return value
        name = argv[argv.index('-Name') + 1]
        target = self.root / J.BASE / name
        dry, resume = '-DryRun' in argv, '-Resume' in argv
        if resume:
            saved = json.loads((target / 'run.json').read_text(encoding='utf-8'))
            model = saved['stages']['calibration']['expected_keys'][0]
        else:
            model = argv[argv.index('-Detector') + 1]
        if dry:
            result = dict(saved, read_only=True, scientific_workers_launched=0) if resume else planned()
        else:
            done = saved['stages']['electronics']['completed_count'] + 1 if resume else 1
            result = progress(model, done, 'completed' if done == 2 else 'paused')
            target.mkdir(parents=True, exist_ok=True)
            result['manifest_sha256'] = (saved['manifest_sha256'] if resume else
                                         saved_manifest(target, name, model))
            (target / 'run.lock').write_text('fake test lease', encoding='utf-8')
            (target / 'run.json').write_text(json.dumps(result), encoding='utf-8')
            if done == 2:
                (target / 'COMPLETE.json').write_text(json.dumps(dict(kind=J.KIND,
                    manifest_sha256=result['manifest_sha256'], completed_keys={p: result['stages'][p]['expected_keys'] for p in J.PHASES},
                    artifacts={})), encoding='utf-8')
        on_output('private diagnostic ' + str(self.root / 'private' / 'source.json') + '\n')
        if self.after:
            self.after(argv, result)
        return dict(exit_code=0, output=json.dumps(result))


class JobProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture_parent = ROOT / '.local/m10-local-ui-v1/test-fixtures'
        cls.fixture_parent.mkdir(parents=True, exist_ok=True)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='protocol-', dir=self.fixture_parent)
        self.root = Path(self.tmp.name)
        (self.root / 'tools').mkdir()
        (self.root / 'tools/scenario_cli.ps1').write_text('# fixture only', encoding='utf-8')
        self.fake = FakeBackend(self.root)
        self.c = J.Controller(self.root, self.fake, identity_probe=lambda pid: None, lock_probe=lambda p: False)

    def tearDown(self):
        self.c.wait_for_idle(3)
        self.tmp.cleanup()

    def job(self):
        return self.c.snapshot()['jobs'][0]

    def test_check_only_shared_structured_dry_run(self):
        parent_env = dict(os.environ)
        got = self.c.check('abc-1', 'SAP22')
        self.assertEqual(got['status'], 'planned')
        self.assertEqual(self.fake.calls[0][0], ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
            '-File', 'tools/scenario_cli.ps1', 'native-readout', '-Name', 'abc-1', '-Json', '-Detector', 'SAP22', '-DryRun'])
        self.assertFalse((self.root / J.BASE / 'abc-1').exists())
        self.assertEqual(self.c.runs(), [])
        self.assertEqual(dict(os.environ), parent_env)
        self.assertEqual(self.fake.calls[0][1]['JULIA_NUM_THREADS'], '2')

    @unittest.skipUnless(os.name == 'nt', 'Windows PowerShell child module isolation')
    def test_windows_child_uses_existing_builtin_modules_without_parent_change(self):
        with mock.patch.dict(os.environ, {'PSModulePath': 'C:/fixture/PowerShell7/Modules'}):
            before = dict(os.environ)
            self.c.check('modules', 'AK02')
            child = self.fake.calls[-1][1]
            expected = str(Path(os.environ.get('SystemRoot') or os.environ['WINDIR']) /
                           'System32/WindowsPowerShell/v1.0/Modules')
            self.assertEqual(child['PSModulePath'], expected)
            self.assertEqual(sum(k.casefold() == 'psmodulepath' for k in child), 1)
            self.assertEqual(dict(os.environ), before)
            self.assertEqual(child['PATH'], before['PATH'])
            self.assertNotIn('PowerShell7', child['PSModulePath'])

    @unittest.skipUnless(os.name == 'nt', 'Windows PowerShell child module isolation')
    def test_missing_windows_builtin_module_refuses_before_dispatch(self):
        before = len(self.fake.calls)
        with mock.patch.dict(os.environ, {'SystemRoot': str(self.root / 'missing-windows')}):
            with self.assertRaises(J.ControlError) as error:
                self.c.check('missingmodule', 'AK02')
        self.assertEqual(error.exception.code, 'unsupported_runtime')
        self.assertEqual(len(self.fake.calls), before)

    def julia_fixture(self):
        profile = self.root / 'fixture-user'
        exe = profile / '.julia/juliaup/julia-1.13.0+0.x64.w64.mingw32/bin/julia.exe'
        exe.parent.mkdir(parents=True)
        exe.write_bytes(b'fixture readable binary; never executed')
        return profile, exe

    @unittest.skipUnless(os.name == 'nt', 'Windows app-execution alias bypass')
    def test_windows_alias_path_uses_existing_pinned_julia_child_only(self):
        profile, exe = self.julia_fixture()
        with mock.patch.dict(os.environ, {'USERPROFILE': str(profile), 'PATH': str(self.root / 'WindowsApps')}):
            os.environ.pop('JULIA_EXE', None)
            before = dict(os.environ)
            result = self.c.check('juliapinned', 'AK02')
            child = self.fake.calls[-1][1]
            self.assertEqual(child['JULIA_EXE'], str(exe))
            self.assertEqual(sum(k.casefold() == 'julia_exe' for k in child), 1)
            self.assertEqual(child['PATH'], before['PATH'])
            self.assertEqual(dict(os.environ), before)
            self.assertEqual(result['runtime_choice']['selection'], 'pinned_existing')
            self.assertNotIn(str(profile), json.dumps(result))

    @unittest.skipUnless(os.name == 'nt', 'Windows explicit Julia selection')
    def test_explicit_julia_is_exact_and_invalid_never_falls_back(self):
        profile, exe = self.julia_fixture()
        explicit = self.root / 'explicit-runtime.exe'
        explicit.write_bytes(b'explicit test binary; never executed')
        with mock.patch.dict(os.environ, {'USERPROFILE': str(profile), 'JULIA_EXE': str(explicit)}):
            before = dict(os.environ)
            result = self.c.check('juliaexplicit', 'SAP22')
            self.assertEqual(self.fake.calls[-1][1]['JULIA_EXE'], str(explicit))
            self.assertEqual(result['runtime_choice']['selection'], 'explicit')
            self.assertEqual(dict(os.environ), before)
        for value in ('', str(self.root / 'missing-explicit.exe'), str(profile)):
            before_calls = len(self.fake.calls)
            with mock.patch.dict(os.environ, {'USERPROFILE': str(profile), 'JULIA_EXE': value}):
                with self.assertRaises(J.ControlError) as error:
                    self.c.check('invalidexplicit', 'AK02')
            self.assertEqual(error.exception.code, 'unsupported_runtime')
            self.assertEqual(len(self.fake.calls), before_calls)

    @unittest.skipUnless(os.name == 'nt', 'Windows pinned Julia availability')
    def test_absent_pinned_julia_refuses_before_any_runner_or_alias_fallback(self):
        with mock.patch.dict(os.environ, {'USERPROFILE': str(self.root / 'missing-user'), 'PATH': str(self.root / 'WindowsApps')}):
            os.environ.pop('JULIA_EXE', None)
            before = len(self.fake.calls)
            with self.assertRaises(J.ControlError) as error:
                self.c.check('missingjulia', 'AK02')
            self.assertEqual(error.exception.code, 'unsupported_runtime')
            self.assertEqual(len(self.fake.calls), before)

    @unittest.skipUnless(os.name == 'nt', 'Completed Windows resume keeps no-Julia path')
    def test_completed_resume_dry_run_skips_current_julia_discovery(self):
        self.c.start('savedruntime', 'AK02')
        self.c.wait_for_idle(3)
        count = len(self.fake.calls)
        with mock.patch.dict(os.environ, {'JULIA_EXE': str(self.root / 'invalid-runtime.exe'),
                                         'USERPROFILE': str(self.root / 'no-current-julia')}):
            self.c.resume('savedruntime')
            self.c.wait_for_idle(3)
        self.assertEqual(self.job()['status'], 'completed')
        self.assertEqual(len(self.fake.calls), count + 1)
        self.assertIn('-Resume', self.fake.calls[-1][0])
        self.assertIn('-DryRun', self.fake.calls[-1][0])
        self.assertEqual(self.fake.calls[-1][1]['JULIA_EXE'], str(self.root / 'invalid-runtime.exe'))

    def test_full_run_requires_final_saved_validation_and_no_resume_selectors(self):
        self.c.start('full', 'SAP22')
        self.c.wait_for_idle(3)
        got = self.job()
        self.assertEqual(got['status'], 'completed')
        self.assertRegex(got['complete_sha256'], '^[0-9a-f]{64}$')
        self.assertEqual(len(self.fake.calls), 5)
        for argv, env in self.fake.calls:
            if '-Resume' in argv:
                self.assertNotIn('-Detector', argv)
                self.assertNotIn('-PrimaryIds', argv)
                self.assertNotIn('-ElectronicsProfile', argv)
            if '-DryRun' not in argv:
                self.assertEqual(argv[-2:], ['-StopAfterGroups', '1'])
        self.assertEqual(got['backend']['completed_counts'], dict(charge=2, calibration=1, electronics=2))

    def test_real_stop_flag_waits_current_step_then_selector_free_resume(self):
        entered, release = threading.Event(), threading.Event()
        def before(argv):
            if '-DryRun' not in argv and '-Resume' not in argv:
                entered.set()
                self.assertTrue(release.wait(3))
        self.fake.before = before
        first = self.c.start('stop', 'AK02')
        self.assertTrue(entered.wait(3))
        stopped = self.c.stop(first['id'])
        self.assertEqual(stopped['status'], 'stop-requested')
        self.assertIsNotNone(self.c.snapshot()['active'])
        release.set()
        self.c.wait_for_idle(3)
        self.assertEqual(self.job()['status'], 'stopped')
        self.assertEqual(self.job()['backend']['completed_counts']['electronics'], 1)
        before_resume = len(self.fake.calls)
        self.c.resume('stop')
        self.c.wait_for_idle(3)
        self.assertEqual(self.job()['status'], 'completed')
        self.assertEqual(len(self.fake.calls) - before_resume, 3)
        for argv, _ in self.fake.calls[before_resume:]:
            self.assertIn('-Resume', argv)
            self.assertNotIn('-Detector', argv)

    def test_last_step_completion_wins_stop_race(self):
        entered, release = threading.Event(), threading.Event()
        def before(argv):
            if '-DryRun' not in argv and '-Resume' in argv:
                entered.set()
                self.assertTrue(release.wait(3))
        self.fake.before = before
        got = self.c.start('last', 'AK02')
        self.assertTrue(entered.wait(3))
        self.c.stop(got['id'])
        release.set()
        self.c.wait_for_idle(3)
        self.assertEqual(self.job()['status'], 'completed')
        self.assertTrue(self.job()['stop_requested'])

    def test_duplicate_launch_and_output_reuse_refuse_before_worker(self):
        entered, release = threading.Event(), threading.Event()
        def before(argv):
            entered.set()
            self.assertTrue(release.wait(3))
        self.fake.before = before
        got = self.c.start('dup', 'AK02')
        self.assertTrue(entered.wait(3))
        with self.assertRaises(J.ControlError) as error:
            self.c.start('other', 'SAP22')
        self.assertEqual(error.exception.code, 'busy')
        self.c.stop(got['id'])
        release.set()
        self.c.wait_for_idle(3)
        before_count = len(self.fake.calls)
        with self.assertRaises(J.ControlError):
            self.c.start('DUP', 'AK02')
        self.assertEqual(len(self.fake.calls), before_count)
        old = self.root / J.BASE / 'prior'
        old.mkdir(parents=True)
        with self.assertRaises(J.ControlError):
            self.c.start('prior', 'AK02')

    def test_exit_zero_without_verification_refuses(self):
        bad = planned()
        bad['verification_final'] = False
        self.fake.override = lambda argv: dict(exit_code=0, output=json.dumps(bad))
        self.c.start('unverified', 'AK02')
        self.c.wait_for_idle(3)
        self.assertEqual(self.job()['status'], 'blocked')
        self.assertEqual(self.job()['error']['code'], 'backend_refused')
        self.assertEqual(len(self.fake.calls), 1)

    def test_bad_json_and_census_are_not_success(self):
        self.fake.override = lambda argv: dict(exit_code=0, output='{"status":')
        self.c.start('badjson', 'AK02')
        self.c.wait_for_idle(3)
        self.assertEqual(self.job()['error']['code'], 'invalid_backend_json')
        bad = planned()
        bad['selected_census']['initial_primaries'] = 2
        self.fake.override = lambda argv: dict(exit_code=0, output=json.dumps(bad))
        self.c.start('badcensus', 'AK02')
        self.c.wait_for_idle(3)
        self.assertEqual(self.job()['error']['code'], 'invalid_backend_receipt')

    def test_complete_claim_without_complete_record_refuses(self):
        def after(argv, result):
            if result['status'] == 'completed':
                target = self.root / J.BASE / 'nocomplete' / 'COMPLETE.json'
                if target.exists():
                    target.unlink()
        self.fake.after = after
        self.c.start('nocomplete', 'AK02')
        self.c.wait_for_idle(3)
        self.assertEqual(self.job()['status'], 'failed')
        self.assertEqual(self.job()['error']['code'], 'missing_complete')
        self.assertNotIn('complete_sha256', self.job())

    def test_browser_snapshots_and_controller_reopen_launch_nothing(self):
        self.c.start('reopen', 'AK02')
        self.c.wait_for_idle(3)
        count = len(self.fake.calls)
        for _ in range(2):
            self.c.snapshot()
        reopened = J.Controller(self.root, self.fake, identity_probe=lambda pid: None, lock_probe=lambda p: False)
        reopened.snapshot()
        self.assertEqual(len(self.fake.calls), count)
        self.assertEqual(reopened.snapshot()['jobs'][0]['status'], 'completed')
        self.assertTrue(reopened.snapshot()['jobs'][0]['verification_required'])
        self.assertNotIn('complete_sha256', reopened.snapshot()['jobs'][0])
        reopened.resume('reopen')
        reopened.wait_for_idle(3)
        self.assertEqual(len(self.fake.calls), count + 1)
        self.assertIn('-DryRun', self.fake.calls[-1][0])
        self.assertEqual(reopened.snapshot()['jobs'][0]['status'], 'completed')

    def test_allowed_label_tamper_on_completed_reopen_blocks_resume_and_result_authority(self):
        self.assert_label_tamper_refused(paused=False)

    def test_allowed_label_tamper_on_paused_reopen_blocks_before_any_scientific_step(self):
        self.assert_label_tamper_refused(paused=True)

    def assert_label_tamper_refused(self, paused):
        for model, other in [('AK02', 'SAP22'), ('SAP22', 'AK02')]:
            with self.subTest(model=model, paused=paused):
                name = ('paused-' if paused else 'terminal-') + model
                if paused:
                    def after(argv, result):
                        if '-DryRun' not in argv and result['status'] == 'paused':
                            self.c.stop(self.c._jobs[-1]['id'])
                    self.fake.after = after
                self.c.start(name, model)
                self.c.wait_for_idle(3)
                self.fake.after = None
                self.assertEqual(self.job()['status'], 'stopped' if paused else 'completed')
                output = self.root / J.BASE / name
                preserved = {p.name: (p.read_bytes(), p.stat().st_mtime_ns)
                             for p in output.iterdir() if p.is_file()}
                state_path = self.root / J.STATE / 'jobs.json'
                state = json.loads(state_path.read_text(encoding='utf-8'))
                recorded = next(j for j in state['jobs'] if j['name'] == name)
                recorded['detector'] = other  # Allowed string; scientific files remain exact.
                state_path.write_text(json.dumps(state), encoding='utf-8')
                before_calls = len(self.fake.calls)
                self.c = J.Controller(self.root, self.fake, identity_probe=lambda pid: None, lock_probe=lambda p: False)
                got = self.job()
                self.assertEqual(len(self.fake.calls), before_calls)
                self.assertEqual(got['status'], 'blocked')
                self.assertEqual(got['detector'], model)
                self.assertEqual(got['error']['code'], 'detector_identity_mismatch')
                self.assertEqual(got['identity_mismatch'], dict(recorded_detector=other, saved_detector=model))
                self.assertNotIn('complete_sha256', got)
                self.assertEqual(self.c.runs()[0]['files'], [])
                self.c.resume(name)
                self.c.wait_for_idle(3)
                calls = self.fake.calls[before_calls:]
                self.assertEqual(len(calls), 1)
                self.assertIn('-DryRun', calls[0][0])
                self.assertIn('-Resume', calls[0][0])
                self.assertNotIn('-Detector', calls[0][0])
                self.assertFalse(any('-DryRun' not in argv for argv, _ in calls))
                self.assertEqual(self.job()['status'], 'blocked')
                self.assertEqual(self.job()['detector'], model)
                self.assertNotIn('complete_sha256', self.job())
                self.assertEqual(self.c.runs()[0]['files'], [])
                persisted = json.loads(state_path.read_text(encoding='utf-8'))
                kept = next(j for j in persisted['jobs'] if j['name'] == name)
                self.assertEqual(kept['detector'], other)
                self.assertEqual(kept['identity_mismatch'], dict(recorded_detector=other, saved_detector=model))
                self.assertEqual(preserved, {p.name: (p.read_bytes(), p.stat().st_mtime_ns)
                                            for p in output.iterdir() if p.is_file()})

    def test_saved_calibration_model_must_match_manifest_before_resume_dispatch(self):
        for phase in J.PHASES:
            with self.subTest(phase=phase):
                name = 'identity-' + phase
                self.c.start(name, 'AK02')
                self.c.wait_for_idle(3)
                receipt_path = self.root / J.BASE / name / 'run.json'
                receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
                stage = receipt['stages'][phase]
                if phase == 'calibration':
                    stage.update(expected_keys=['SAP22'], completed_keys=['SAP22'])
                else:
                    stage['completed_keys'][0] = 'SAP22-e207-d207-g0'
                receipt_path.write_text(json.dumps(receipt), encoding='utf-8')
                before = len(self.fake.calls)
                self.c.resume(name)
                self.c.wait_for_idle(3)
                self.assertEqual(self.job()['status'], 'blocked')
                self.assertEqual(self.job()['error']['code'], 'invalid_saved_identity')
                self.assertNotIn('complete_sha256', self.job())
                self.assertEqual(self.c.runs()[0]['files'], [])
                self.assertEqual(len(self.fake.calls), before + 1)
                self.assertIn('-Resume', self.fake.calls[-1][0])
                self.assertIn('-DryRun', self.fake.calls[-1][0])
                self.assertNotIn('-Detector', self.fake.calls[-1][0])

    def test_restart_live_pid_and_held_lease_block_new_writer(self):
        self.c.start('live', 'AK02')
        self.c.wait_for_idle(3)
        with self.c._lock:
            self.c._jobs[0]['child'] = {'pid': 999991, 'identity': 'started'}
            self.c._persist()
        reopened = J.Controller(self.root, self.fake, identity_probe=lambda pid: 'started', lock_probe=lambda p: False)
        before = len(self.fake.calls)
        with self.assertRaises(J.ControlError) as error:
            reopened.start('second', 'SAP22')
        self.assertEqual(error.exception.code, 'backend_still_active')
        self.assertEqual(len(self.fake.calls), before)
        held = J.Controller(self.root, self.fake, identity_probe=lambda pid: None, lock_probe=lambda p: p.name == 'run.lock')
        with self.assertRaises(J.ControlError):
            held.resume('live')

    def test_only_owned_runs_safe_names_and_fixed_detectors(self):
        for name in ('', '../bad', 'a' * 25, 'abc;whoami', 'abc/path', 'abc:stream', 'NUL', 'con'):
            with self.assertRaises(J.ControlError):
                self.c.start(name, 'AK02')
        for model in ('both', 'GeGI', None):
            with self.assertRaises(J.ControlError):
                self.c.start('valid', model)
        with self.assertRaises(J.ControlError):
            self.c.resume('unknown')
        prior = self.root / J.BASE / 'old'
        prior.mkdir(parents=True)
        (prior / 'run.json').write_text(json.dumps(progress('SAP22', 2, 'completed')), encoding='utf-8')
        self.assertEqual(self.c.runs(), [])
        self.assertEqual(self.fake.calls, [])

    def test_reparse_output_and_state_components_refuse(self):
        original = Path.lstat
        def fake_stat(path, *args, **kwargs):
            if str(path).endswith('local-control-v1') or str(path).endswith('linked'):
                return type('Reparse', (), {'st_mode': stat_mode, 'st_file_attributes': 0x400})()
            return original(path, *args, **kwargs)
        stat_mode = 0o040755
        with mock.patch.object(Path, 'lstat', fake_stat):
            with self.assertRaises(J.ControlError):
                J.Controller(self.root, self.fake)
            with self.assertRaises(J.ControlError):
                J.safe_path(self.root, J.BASE + '/linked/child')
        self.assertEqual(self.fake.calls, [])

    def test_private_paths_remain_local_not_browser_logs(self):
        self.c.start('privacy', 'AK02')
        self.c.wait_for_idle(3)
        browser = json.dumps(self.c.snapshot())
        self.assertNotIn(str(self.root), browser)
        self.assertIn('[project]', browser)
        logfile = self.root / J.STATE / 'logs' / (self.job()['id'] + '.log')
        self.assertIn(str(self.root), logfile.read_text(encoding='utf-8'))

    def test_stop_during_new_preflight_cancels_without_resume_artifact(self):
        entered, release = threading.Event(), threading.Event()
        def before(argv):
            entered.set()
            self.assertTrue(release.wait(3))
        self.fake.before = before
        got = self.c.start('cancel', 'AK02')
        self.assertTrue(entered.wait(3))
        self.c.stop(got['id'])
        release.set()
        self.c.wait_for_idle(3)
        self.assertEqual(self.job()['status'], 'cancelled')
        self.assertFalse(self.job()['can_resume'])
        self.assertFalse((self.root / J.BASE / 'cancel').exists())
        self.assertEqual(len(self.fake.calls), 1)
        with self.assertRaises(J.ControlError):
            self.c.resume('cancel')

    def test_valid_backend_resume_can_recover_stale_progress_without_recomputation(self):
        target = self.root / J.BASE / 'stale'
        target.mkdir(parents=True)
        saved = progress('AK02', 1)
        saved['manifest_sha256'] = saved_manifest(target, 'stale', 'AK02')
        saved['status'] = 'running'
        saved['verification_final'] = False
        saved['stages']['electronics']['completed_keys'] = []
        saved['stages']['electronics']['completed_count'] = 0
        (target / 'run.json').write_text(json.dumps(saved), encoding='utf-8')
        job = dict(id='b' * 32, name='stale', detector='AK02', output=J.BASE + '/stale',
                   status='blocked', stop_requested=False, logs=[], child=None, backend={}, result={})
        self.c._jobs.append(job)
        self.c._persist()
        def override(argv):
            if '-DryRun' in argv:
                result = dict(progress('AK02', 1), read_only=True, scientific_workers_launched=0)
                result['manifest_sha256'] = saved['manifest_sha256']
                return dict(exit_code=0, output=json.dumps(result))
            return None
        self.fake.override = override
        # This fixture isolates valid shared-backend preflight: stop immediately
        # after it, so stale run.json cannot fabricate or recompute an event.
        entered, release = threading.Event(), threading.Event()
        def before(argv):
            entered.set()
            self.assertTrue(release.wait(3))
        self.fake.before = before
        got = self.c.resume('stale')
        self.assertTrue(entered.wait(3))
        self.c.stop(got['id'])
        release.set()
        self.c.wait_for_idle(3)
        self.assertEqual(self.job()['status'], 'stopped')
        self.assertEqual(self.job()['result']['completed_counts']['electronics'], 1)
        self.assertEqual(len(self.fake.calls), 1)

    def test_native_failures_terminal_status_is_retained(self):
        def after(argv, result):
            if result['status'] == 'completed':
                result['status'] = 'completed_with_native_failures'
                path = self.root / J.BASE / 'nf' / 'run.json'
                path.write_text(json.dumps(result), encoding='utf-8')
        self.fake.after = after
        self.c.start('nf', 'AK02')
        self.c.wait_for_idle(3)
        self.assertEqual(self.job()['status'], 'completed_with_native_failures')


if __name__ == '__main__':
    unittest.main(verbosity=2)
