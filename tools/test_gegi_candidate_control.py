"""Bounded Control lifecycle, protection and saved selected-electrode contracts."""

import copy
import gzip
from io import BytesIO
import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
from urllib.parse import urlencode
import unittest
from unittest.mock import patch

import gegi_candidate_control as C
import gegi_candidate_storage as storage
import gegi_exposure_stream as stream
import local_ui as U
import local_ui_workflow_jobs as J
import scenario_workflow as W
from test_gegi_candidate_storage import card
from test_gegi_pulse_stream import prepare, pulse


class CandidateControlTests(unittest.TestCase):
    def setUp(self):
        base = W.ROOT / '.local' / 'candidate-storage-v1'
        base.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix='control-', dir=base)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.workflow = J.WorkflowController(self.root)
        self.ready, self.release = threading.Event(), threading.Event()
        self.calls = []
        self.failure = False
        clock = stream.ADCExposure([(prepare(pulse((3, 24), 190., neighbor=True)), 1017., 1.),
                                    (prepare(pulse((11, 26), 470.)), 1017., 1.)], live_time_ns=5000., noise_seed=23)
        self.sample = []
        stream.reconstruct_exposure(clock, on_readout_context=lambda event, context:
                                    self.sample.append((copy.deepcopy(event), copy.deepcopy(context))))

        def runner(output, **settings):
            self.calls.append((output, settings))
            settings['on_progress']({'stage': 'unit_fixture'})
            self.ready.set()
            if not self.release.wait(5):
                raise RuntimeError('Unit fixture timed out')
            if self.failure:
                (output/'partial.json').write_text('{"preserved":true}', encoding='utf-8')
                raise ValueError('Initialize the existing GeGI field cache before this acquisition.')
            event, context = self.sample[0]
            with storage.CandidateStore(output/storage.ARCHIVE_NAME, {'kind': 'unit_fixture'}) as sink:
                sink.observe(card(event), context, event=event)
                sink.finalize(acquisition_statistics={'initial_parents': settings['primary_count']})
            database = output/storage.ARCHIVE_NAME
            W.write(output/C.REPORT_NAME, {'kind': C.REPORT_KIND, 'status': 'completed',
                'identity': {'kind': 'unit_fixture'}, 'counts': {'qualified_triggers': 1},
                'storage_counts': {'saved_candidates': 1, 'rejected_rises': 0}, 'live_time_ns': 5000.,
                'artifacts': {storage.ARCHIVE_NAME: {'bytes': database.stat().st_size, 'sha256': W.sha(database)}}})

        self.workflow._gegi_candidate_control = C.CandidateControl(self.workflow, runner=runner)
        self.control = self.workflow.gegi_candidates()
        self.server = SimpleNamespace(origin='http://127.0.0.1:8765', token='candidate-unit-token',
                                      workflow_controller=self.workflow)
        self.addCleanup(self.finish)

    def finish(self):
        self.release.set()
        stop = time.monotonic()+5
        while self.workflow._active is not None and time.monotonic()<stop:
            time.sleep(.01)
        self.assertIsNone(self.workflow._active)

    def request(self, route, data=None, headers=None):
        handler = object.__new__(U.Handler)
        handler.server = self.server
        handler.path = '/api/workflow/gegi-candidates/'+route
        values = {'Host': '127.0.0.1:8765', 'X-Control-Token': self.server.token}
        if data is not None:
            raw = json.dumps(data).encode()
            handler.rfile = BytesIO(raw)
            values.update({'Origin': self.server.origin, 'Content-Type': 'application/json', 'Content-Length': str(len(raw))})
        values.update(headers or {})
        handler.headers = values
        reply = []
        handler.send_data = lambda status, value: reply.append((status, value))
        handler.do_GET() if data is None else handler.do_POST()
        self.assertEqual(len(reply), 1)
        return reply[0]

    def settings(self):
        return {'name': 'mixed-unit', 'primary_count': 100, 'seed': 20261120,
                'activities_bq': [185000, 37000], 'positions_mm': [[-40, 0, 40], [40, 0, 40]]}

    def test_storage_estimate_is_protected_readonly_bounded_and_source_specific(self):
        fields = {'total_parents': '20000000', 'activity_a_bq': '185000', 'activity_b_bq': '37000',
                  'a_x': '-40', 'a_y': '0', 'a_z': '40', 'b_x': '40', 'b_y': '0', 'b_z': '40'}
        route = 'estimate?'+urlencode(fields)
        self.assertEqual(self.request(route, headers={'X-Control-Token': 'wrong'})[0], 403)
        before = set(self.root.rglob('*'))
        status, estimate = self.request(route)
        self.assertEqual(status, 200)
        self.assertEqual(estimate['total_parents'], 20000000)
        self.assertEqual(estimate['activities_bq'], [185000, 37000])
        self.assertIsNone(estimate['execution_primary_limit'])
        self.assertIsNone(estimate['execution_duration_limit_s'])
        self.assertEqual(estimate['new_science_calls'], 0)
        self.assertEqual(estimate['shared_field_cache_bytes'], 857068900)
        self.assertGreater(estimate['planning_range_bytes'][1], estimate['planning_range_bytes'][0])
        self.assertIsNone(estimate['runtime_scratch']['future_peak_disk_bytes'])
        self.assertEqual(estimate['runtime_prediction']['status'], 'conditional_measured_rate_scenarios')
        self.assertGreater(estimate['whole_retained_with_shared_planning_range_bytes'][0], estimate['planning_range_bytes'][0])
        self.assertEqual(estimate['analysis_extension']['shared_calibration_once_bytes'], 303891603)
        self.assertGreater(estimate['complete_pipeline_runtime_prediction']['planning_range_seconds'][0],
                           estimate['runtime_prediction']['planning_range_seconds'][0])
        for changes in ({'total_parents': '0'}, {'total_parents': '9007199254740992'},
                        {'total_parents': '1.5'}, {'activity_a_bq': 'nan'},
                        {'activity_a_bq': '37000'}, {'a_x': '-39'}, {'b_z': 'inf'}, {'path': '../private'}):
            self.assertEqual(self.request('estimate?'+urlencode(fields | changes))[0], 400)
        self.assertEqual(before, set(self.root.rglob('*')))
        self.assertFalse(self.calls)
        self.assertFalse(self.control.state_path.exists())
        self.assertNotIn(str(self.root), json.dumps(estimate))

    def test_protected_async_start_original_candidate_and_readonly_selected_channel(self):
        self.assertEqual(self.request('options', headers={'X-Control-Token': 'wrong'})[0], 403)
        status, options = self.request('options')
        self.assertEqual((status, options['defaults']['primary_count']), (200, 100))
        self.assertEqual(options['defaults']['mode'], 'duration')
        self.assertEqual(options['defaults']['duration_s'], 5)
        self.assertIsNone(options['defaults']['maximum_duration_s'])
        self.assertIsNone(options['defaults']['maximum_primary_count'])
        settings = self.settings()
        for changed in ({'name': '../escape'}, {'primary_count': 0}, {'primary_count': -1},
                        {'primary_count': 1.5}, {'primary_count': '100'}, {'primary_count': True}, {'seed': 0},
                        {'activities_bq': [True, 37000]}, {'positions_mm': [[0, 0], [0, 0, 40]]},
                        {'output': '.local/other'}):
            self.assertEqual(self.request('start', settings | changed)[0], 400)
        self.assertEqual(self.request('start', settings, {'Origin': 'https://foreign.invalid'})[0], 403)
        self.assertFalse(self.calls)
        status, job = self.request('start', settings)
        self.assertEqual((status, job['status']), (200, 'running'))
        self.assertTrue(self.ready.wait(2))
        self.assertTrue(self.workflow.own_busy())
        self.assertEqual(self.request('start', settings | {'name': 'another'})[0], 400)
        self.finish()
        status, job = self.request('state?name=mixed-unit')
        self.assertEqual((status, job['status']), (200, 'completed'))
        path = self.root/C.OUTPUTS/'mixed-unit'
        before = {p.name: W.sha(p) for p in path.iterdir() if p.is_file()}
        control_before = self.control.state_path.read_bytes()
        digest = job['report_sha256']
        status, page = self.request('list?name=mixed-unit&report_sha256='+digest+'&offset=0')
        self.assertEqual((status, page['total'], page['items'][0]['trigger_id']), (200, 1, 1))
        query = 'event?name=mixed-unit&report_sha256='+digest+'&trigger_id=1&contact_id='
        status, event = self.request(query+'3')
        self.assertEqual((status, event['contact_id'], event['trigger_id']), (200, 3, 1))
        self.assertEqual(set(event['trace']), {'time_ns', 'adc_codes', 'preamp_V', 'fast_V', 'slow_keV'})
        self.assertIsInstance(event['trace']['adc_codes'][0], int)
        self.assertNotIn('channels', event)
        gate = [value for t, value in zip(event['trace']['time_ns'], event['trace']['slow_keV']) if 880 <= t <= 980]
        self.assertAlmostEqual(sum(gate)/len(gate), event['channel']['slow_energy_keV'], places=12)
        status, neighbor = self.request(query+'4')
        self.assertEqual(status, 200)
        self.assertLess(neighbor['channel']['fast_signal_keV_equiv'], 0.)
        self.assertEqual(self.request(query+'35')[0], 400)
        self.assertEqual(self.request('list?name=mixed-unit&report_sha256='+'0'*64+'&offset=0')[0], 400)
        self.assertEqual(self.request('state?name=../escape')[0], 400)
        self.assertEqual(before, {p.name: W.sha(p) for p in path.iterdir() if p.is_file()})
        self.assertEqual(control_before, self.control.state_path.read_bytes())
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.request('start', settings)[0], 400)
        restored = J.WorkflowController(self.root).gegi_candidates()
        self.assertEqual(restored.state('mixed-unit')['report_sha256'], digest)

    def test_failed_attempt_preserves_partial_files_error_log_and_exclusive_name(self):
        self.failure = True
        self.control.start(**self.settings())
        self.assertTrue(self.ready.wait(2))
        self.finish()
        state = self.control.state('mixed-unit')
        self.assertEqual(state['status'], 'failed')
        self.assertIn('field cache', state['error'])
        directory = self.root/C.OUTPUTS/'mixed-unit'
        self.assertTrue((directory/'partial.json').is_file())
        self.assertIn('ValueError', (directory/'worker-error.log').read_text())
        self.assertEqual(len(self.calls), 1)
        with self.assertRaisesRegex(W.ControlError, 'fresh acquisition name'):
            self.control.start(**self.settings())

    def test_default_streaming_stop_restart_resume_keeps_original_settings_and_results(self):
        invocations = []
        identity = {'scope': 'synthetic_control_checkpoint_only'}

        def runner(output, **settings):
            invocations.append(settings)
            settings['on_progress']({'stage': 'unit_checkpoint', 'status': 'running'})
            self.ready.set()
            if not settings['resume']:
                if not self.release.wait(5):
                    raise RuntimeError('Unit fixture timed out')
                self.assertTrue(settings['stop_requested']())
                self.assertEqual(list(output.iterdir()), [])
                with storage.CandidateStore(output/storage.ARCHIVE_NAME, identity) as sink:
                    with sink.transaction():
                        sink.save_checkpoint({'source_cursor': 50, 'readout': {'next_sample': 180}})
                settings['on_progress']({'stage': 'Saved unit checkpoint', 'status': 'stopped'})
                return {'status': 'stopped', 'resumable': True}
            self.assertFalse(settings['stop_requested']())
            event, context = self.sample[0]
            with storage.CandidateStore(output/storage.ARCHIVE_NAME, identity, resume=True) as sink:
                self.assertEqual(sink.load_checkpoint()['source_cursor'], 50)
                with sink.transaction():
                    sink.observe(card(event), context, event=event)
                    sink.save_checkpoint({'source_cursor': 100, 'readout': {'next_sample': 360}})
                sink.finalize(acquisition_statistics={'scope': 'synthetic_unit_only'})
            database = output/storage.ARCHIVE_NAME
            W.write(output/C.REPORT_NAME, {'kind': C.REPORT_KIND, 'status': 'completed',
                'identity': identity, 'counts': {'qualified_triggers': 1},
                'storage_counts': {'saved_candidates': 1, 'rejected_rises': 0}, 'live_time_ns': 5000.,
                'artifacts': {storage.ARCHIVE_NAME: {'bytes': database.stat().st_size, 'sha256': W.sha(database)}}})
            return {'status': 'completed'}

        self.control.runner = None
        with patch.dict('sys.modules', {'gegi_streaming_acquisition': SimpleNamespace(run=runner)}):
            self.assertEqual(self.request('start', self.settings())[0], 200)
            self.assertTrue(self.ready.wait(2))
            self.assertEqual(self.request('stop', {'name': 'mixed-unit'}, {'Origin': 'https://foreign.invalid'})[0], 403)
            self.assertEqual(self.request('stop', {'name': 'mixed-unit', 'kill': True})[0], 400)
            status, stopping = self.request('stop', {'name': 'mixed-unit'})
            self.assertEqual((status, stopping['status']), (200, 'stop_requested'))
            self.assertTrue(self.workflow.own_busy())
            self.assertEqual(self.request('resume', {'name': 'mixed-unit'})[0], 400)
            self.finish()
            stopped = self.control.state('mixed-unit')
            self.assertEqual(stopped['status'], 'stopped')
            self.assertTrue(stopped['resumable'])
            self.assertFalse(stopped['results_available'])
            # Restart recovery never silently relaunches the saved job.
            saved = W.read(self.control.state_path)
            saved['jobs'][0]['status'] = 'stop_requested'
            W.write(self.control.state_path, saved)
            self.workflow = J.WorkflowController(self.root)
            self.control = self.workflow.gegi_candidates()
            self.server.workflow_controller = self.workflow
            restored = self.control.state('mixed-unit')
            self.assertEqual(restored['status'], 'interrupted')
            self.assertTrue(restored['resumable'])
            self.assertEqual(len(invocations), 1)
            self.assertEqual(self.request('resume', {'name': 'mixed-unit', 'seed': 99})[0], 400)
            self.assertEqual(self.request('resume', {'name': '../escape'})[0], 400)
            self.assertEqual(self.request('resume', {'name': 'mixed-unit'})[0], 200)
            self.finish()
            completed = self.control.state('mixed-unit')
            self.assertEqual(completed['status'], 'completed')
            self.assertFalse(completed['resumable'])
            self.assertEqual(self.request('resume', {'name': 'mixed-unit'})[0], 400)
            self.assertEqual(self.request('stop', {'name': 'mixed-unit'})[0], 400)
            status, page = self.request('list?name=mixed-unit&report_sha256='+completed['report_sha256']+'&offset=0')
            self.assertEqual((status, page['total'], page['items'][0]['trigger_id']), (200, 1, 1))
        self.assertEqual(len(invocations), 2)
        for fields in invocations:
            self.assertEqual(fields['primary_count'], 100)
            self.assertEqual(fields['seed'], 20261120)
            self.assertEqual(fields['activities_bq'], [185000, 37000])
            self.assertEqual(fields['positions_mm'], [[-40, 0, 40], [40, 0, 40]])
            self.assertEqual(fields['block_parents'], 50)
            self.assertEqual(fields['initial_state_policy'], C.STARTUP_POLICY)
        self.assertFalse(invocations[0]['resume'])
        self.assertTrue(invocations[1]['resume'])

    def test_failed_resume_preserves_the_first_error_record(self):
        invocations = []

        def runner(output, **settings):
            invocations.append(settings)
            if not (output/storage.ARCHIVE_NAME).exists():
                with storage.CandidateStore(output/storage.ARCHIVE_NAME, {'scope': 'unit_fixture'}) as sink:
                    with sink.transaction():
                        sink.save_checkpoint({'source_cursor': 0})
            raise ValueError('Preserved synthetic failure '+str(len(invocations)))

        self.control.runner = runner
        self.control.start(**self.settings())
        self.finish()
        directory = self.root/C.OUTPUTS/'mixed-unit'
        first = (directory/'worker-error.log').read_bytes()
        self.assertTrue(self.control.state('mixed-unit')['resumable'])
        self.control.resume('mixed-unit')
        self.finish()
        self.assertEqual((directory/'worker-error.log').read_bytes(), first)
        self.assertIn('synthetic failure 2', (directory/'worker-error-2.log').read_text())
        self.assertEqual(self.control.state('mixed-unit')['error_log'], 'worker-error-2.log')
        self.assertEqual(len(invocations), 2)

    def test_sealed_checkpoint_without_report_resumes_export_only(self):
        def interrupted_export(output, **settings):
            with storage.CandidateStore(output/storage.ARCHIVE_NAME, {'scope': 'unit_sealed_recovery'}) as sink:
                with sink.transaction():
                    sink.save_checkpoint({'source_cursor': 100})
                sink.finalize(acquisition_statistics={'scope': 'synthetic_unit_only'})
            raise RuntimeError('Interrupted after sealing before report export')

        self.control.runner = interrupted_export
        self.control.start(**self.settings())
        self.finish()
        directory = self.root/C.OUTPUTS/'mixed-unit'
        database = directory/storage.ARCHIVE_NAME
        sealed_sha = W.sha(database)
        self.assertFalse((directory/C.REPORT_NAME).exists())
        self.assertTrue(self.control.state('mixed-unit')['resumable'])
        recoveries = []

        def recover_report(output, **settings):
            recoveries.append(settings)
            self.assertTrue(settings['resume'])
            self.assertEqual(storage.store_summary(database)['status'], 'completed')
            self.assertEqual(W.sha(database), sealed_sha)
            report = {'kind': C.REPORT_KIND, 'status': 'completed',
                'identity': {'scope': 'unit_sealed_recovery'}, 'counts': {'qualified_triggers': 0},
                'storage_counts': {'saved_candidates': 0, 'rejected_rises': 0}, 'live_time_ns': 5000.,
                'artifacts': {storage.ARCHIVE_NAME: {'bytes': database.stat().st_size, 'sha256': sealed_sha}}}
            W.write(output/C.REPORT_NAME, report)
            return report

        self.control.runner = None
        with patch.dict('sys.modules', {'gegi_streaming_acquisition': SimpleNamespace(run=recover_report)}):
            self.assertEqual(self.request('resume', {'name': 'mixed-unit'})[0], 200)
            self.finish()
        self.assertEqual(len(recoveries), 1)
        self.assertEqual(W.sha(database), sealed_sha)
        self.assertEqual(self.control.state('mixed-unit')['status'], 'completed')
        self.assertFalse(self.control.state('mixed-unit')['resumable'])
        self.assertEqual(self.request('resume', {'name': 'mixed-unit'})[0], 400)

    def test_physical_duration_equilibrium_progress_and_resume_are_immutable(self):
        settings = self.settings()
        settings.pop('primary_count')
        settings['duration_s'] = 5
        for changes in ({'duration_s': 0}, {'duration_s': -1}, {'duration_s': float('inf')},
                        {'duration_s': True}, {'duration_s': '5'}, {'duration_s': None},
                        {'duration_s': float('nan')}, {'primary_count': 100},
                        {'initial_state_policy': C.STARTUP_POLICY}):
            self.assertEqual(self.request('start', settings | changes)[0], 400)
        self.assertFalse(self.calls)
        invocations = []
        identity = {'scope': 'synthetic_duration_control_only'}

        def runner(output, **fields):
            invocations.append(fields)
            self.assertEqual(fields['duration_s'], 5)
            self.assertEqual(fields['initial_state_policy'], C.STEADY_POLICY)
            self.assertNotIn('primary_count', fields)
            if not fields['resume']:
                with storage.CandidateStore(output/storage.ARCHIVE_NAME, identity) as sink:
                    with sink.transaction():
                        sink.save_checkpoint({'acquisition_time_ns': 2e9})
                fields['on_progress']({'status': 'running', 'stage': 'unit_duration_progress',
                    'acquisition_time_ns': 2e9, 'duration_s': 5,
                    'new_parent_decays': 1001, 'initial_daughter_decays': 73})
                self.ready.set()
                if not self.release.wait(5):
                    raise RuntimeError('Unit fixture timed out')
                self.assertTrue(fields['stop_requested']())
                return {'status': 'stopped', 'resumable': True}
            with storage.CandidateStore(output/storage.ARCHIVE_NAME, identity, resume=True) as sink:
                with sink.transaction():
                    sink.save_checkpoint({'acquisition_time_ns': 5e9})
                sink.finalize(acquisition_statistics={'scope': 'synthetic_unit_only', 'duration_s': 5})
            database = output/storage.ARCHIVE_NAME
            report = {'kind': C.REPORT_KIND, 'status': 'completed', 'identity': identity,
                'counts': {'qualified_triggers': 0}, 'storage_counts': {'saved_candidates': 0, 'rejected_rises': 0},
                'live_time_ns': 5e9, 'source': {'initial_parents': 1001, 'initial_daughter_decays': 73,
                    'transport_primaries': 1074},
                'artifacts': {storage.ARCHIVE_NAME: {'bytes': database.stat().st_size, 'sha256': W.sha(database)}}}
            W.write(output/C.REPORT_NAME, report)
            return report

        self.control.runner = None
        with patch.dict('sys.modules', {'gegi_streaming_acquisition': SimpleNamespace(run=runner)}):
            status, job = self.request('start', settings)
            self.assertEqual((status, job['mode'], job['duration_s']), (200, 'duration', 5))
            self.assertIsNone(job['primary_count'])
            self.assertEqual(job['initial_state_policy'], C.STEADY_POLICY)
            self.assertTrue(self.ready.wait(2))
            progress = self.control.state('mixed-unit')['progress']
            self.assertEqual(progress['acquisition_time_ns'], 2e9)
            self.assertEqual(progress['new_parent_decays'], 1001)
            self.assertEqual(progress['initial_daughter_decays'], 73)
            self.assertEqual(self.request('stop', {'name': 'mixed-unit'})[0], 200)
            self.finish()
            self.workflow = J.WorkflowController(self.root)
            self.control = self.workflow.gegi_candidates()
            self.server.workflow_controller = self.workflow
            stopped = self.control.state('mixed-unit')
            self.assertTrue(stopped['resumable'])
            self.assertEqual((stopped['duration_s'], stopped['initial_state_policy']), (5, C.STEADY_POLICY))
            self.assertEqual(self.request('resume', {'name': 'mixed-unit', 'duration_s': 1})[0], 400)
            self.assertEqual(self.request('resume', {'name': 'mixed-unit', 'activities_bq': [1, 2]})[0], 400)
            self.assertEqual(self.request('resume', {'name': 'mixed-unit'})[0], 200)
            self.finish()
        completed = self.control.state('mixed-unit')
        self.assertEqual(completed['status'], 'completed')
        self.assertEqual(completed['result']['source'], {'initial_parents': 1001,
            'initial_daughter_decays': 73, 'transport_primaries': 1074})
        self.assertEqual(len(invocations), 2)
        self.assertFalse(invocations[0]['resume'])
        self.assertTrue(invocations[1]['resume'])
        for fields in invocations:
            self.assertEqual(fields['block_parents'], 10000)
            self.assertEqual(fields['seed'], 20261120)
            self.assertEqual(fields['activities_bq'], [185000, 37000])
            self.assertEqual(fields['positions_mm'], [[-40, 0, 40], [40, 0, 40]])

    def test_default_runner_source_root_block_sizes_follow_acquisition_mode(self):
        captured = {}

        def runner(output, **settings):
            captured[output.name] = settings
            with storage.CandidateStore(output/storage.ARCHIVE_NAME, {'scope': 'unit_block_size_capture'}) as sink:
                with sink.transaction():
                    sink.save_checkpoint({'source_cursor': 0})
            return {'status': 'stopped', 'resumable': True}

        self.control.runner = None
        with patch.dict('sys.modules', {'gegi_streaming_acquisition': SimpleNamespace(run=runner)}):
            for name, selection in (('startup-block', {'primary_count': 100}),
                                    ('large-count', {'primary_count': 20000000}),
                                    ('duration-block', {'duration_s': 5}),
                                    ('long-duration', {'duration_s': 90.09})):
                settings = self.settings() | {'name': name}
                settings.pop('primary_count')
                status, job = self.request('start', settings | selection)
                self.assertEqual((status, job['status']), (200, 'running'))
                for field, value in selection.items():
                    self.assertEqual(job[field], value)
                self.finish()
        self.assertEqual(captured['startup-block']['block_parents'], 50)
        self.assertEqual(captured['startup-block']['primary_count'], 100)
        self.assertEqual(captured['large-count']['primary_count'], 20000000)
        self.assertEqual(captured['large-count']['block_parents'], 50)
        self.assertEqual(captured['duration-block']['block_parents'], 10000)
        self.assertEqual(captured['duration-block']['duration_s'], 5)
        self.assertNotIn('primary_count', captured['duration-block'])
        self.assertEqual(captured['long-duration']['duration_s'], 90.09)
        self.assertEqual(captured['long-duration']['block_parents'], 10000)
        self.assertNotIn('primary_count', captured['long-duration'])
        for name, settings in captured.items():
            self.assertEqual(settings['initial_state_policy'], C.STEADY_POLICY if 'duration_s' in settings else C.STARTUP_POLICY)
            self.assertEqual(settings['activities_bq'], [185000, 37000])
            self.assertEqual(settings['positions_mm'], [[-40, 0, 40], [40, 0, 40]])

    def imaging_fixture(self):
        self.control.start(**self.settings()); self.finish()
        directory = self.root/C.OUTPUTS/'mixed-unit'
        report = W.read(directory/C.REPORT_NAME)
        report['counts']['qualified_energies'] = 1
        report.update(source={'initial_parents': 100, 'initial_daughter_decays': 0, 'unavailable_native_groups': 1},
                      excluded_intervals_ns=[[1000., 2000.]], verification={'status': 'verified_exact'})
        W.write(directory/C.REPORT_NAME, report)
        # This is an input-discovery fixture, never loaded as a physical calibration.
        calibration = self.root/'.local/gegi-center-calibration.npz'
        calibration.write_bytes(b'synthetic separate waveform calibration')
        self.control.jobs['mixed-unit'].pop('report_sha256', None)
        digest = W.sha(directory/C.REPORT_NAME)
        request = dict(name='mixed-unit', report_sha256=digest,
                       calibration_id=self.control.options()['calibrations'][0]['id'],
                       z_mm=40., extent_mm=2., step_mm=4., sigma_deg=5., plane_prior='uniform-area')
        layer = dict(triggers=1, triggers_with_geometry=1, allowed_hypotheses=1, hypotheses=1,
                     projected_mass=1., unresolved_mass=0., mass=[[1., 0.], [0., 0.]])
        result = dict(kind=C.PLANE_KIND,
            input_sha256={'acquisition': digest, 'candidate_store': report['artifacts'][storage.ARCHIVE_NAME]['sha256'],
                          'calibration': W.sha(calibration)},
            grid=dict(x_mm=[-2., 2.], y_mm=[-2., 2.], step_mm=4., extent_mm=2., assumed_z_mm=40.),
            model=dict(plane_prior='uniform-area', angular_nuisance_sigma_deg=5., geometry='Synthetic fixture',
                       normalization='Nominal mass', ambiguity='Retain unresolved alternatives', limits='No scientific fit'),
            layers={'all': layer, 'other_energy': copy.deepcopy(layer)},
            selection=dict(qualified_triggers=1, qualified_energies=1, two_strip_triggers=1,
                           clock_live_time_ns=5000., qualified_adc_live_time_ns=4000., energy_windows='Fixture'),
            candidate_analysis=dict(kind=C.ANALYSIS_KIND, scope='all_two_strip_candidates',
                two_strip_candidates=1, selected_original_trigger_ids=[1], qualified_counts=report['counts'],
                storage_counts=report['storage_counts'], source_census=report['source'],
                excluded_intervals_ns=report['excluded_intervals_ns']),
            fit_receipt=dict(kind='gegi_candidate_measured_waveform_fits_v1', two_strip_triggers=1),
            triggers=[{'original_trigger_id': 1}])
        return directory, request, result

    def test_shared_plane_is_a_separate_bound_recipe_and_rejects_duplicate_ids(self):
        _, request, saved = self.imaging_fixture()
        saved['candidate_analysis'].update(include_shared_strip=True, saved_candidates=3,
                                           retained_candidates_outside_two_strip_scope=2)
        saved['shared_strip_plane'] = {'kind': C.SHARED_PLANE_KIND, 'scope': 'all_shared_strip_candidates',
            'population': {'saved_candidates': 3, 'shared_strip_candidates': 1,
                           'shared_topology_counts': {'1x2': 1}, 'shared_fit_input_status': {'ready': 1}},
            'omitted_original_trigger_count': 0, 'fit_status_counts': {'scored': 1},
            'layers': copy.deepcopy(saved['layers']), 'triggers': [{'original_trigger_id': 2}]}
        view = C._shared_plane_view(saved, 2, 2, [1])
        self.assertEqual(view['original_trigger_ids'], [2])
        self.assertNotIn('triggers', view)
        analysis = dict(request, calibration_sha256=saved['input_sha256']['calibration'])
        self.assertFalse(C._matching_analysis(saved, analysis))
        analysis['include_shared_strip'] = True
        self.assertTrue(C._matching_analysis(saved, analysis))
        self.assertIn('--include-shared-strip', C.CandidateControl._analysis_arguments(
            dict(analysis, calibration_ref='center.npz', analysis_id='candidate-imaging-shared.json.gz'), 'imaging', './'))
        saved['shared_strip_plane']['triggers'][0]['original_trigger_id'] = 1
        with self.assertRaisesRegex(W.ControlError, 'shared-strip trigger identities'):
            C._shared_plane_view(saved, 2, 2, [1])

    def test_imaging_protected_child_recipe_saved_view_and_matching_reuse(self):
        directory, request, result = self.imaging_fixture()
        original = {name: W.sha(directory/name) for name in (C.REPORT_NAME, storage.ARCHIVE_NAME)}
        captured = []; self.ready.clear(); self.release.clear()
        def runner(argv, **kwargs):
            captured.append(argv); kwargs['on_output']('Saved-data unit fixture only\n'); self.ready.set()
            if not self.release.wait(5): raise RuntimeError('Unit fixture timed out')
            output = (self.root/'transport'/argv[argv.index('--output')+1]).resolve()
            output.write_bytes(gzip.compress(W.encoded(result), mtime=0))
            return {'exit_code': 0, 'output': '{}'}
        self.control.analysis_runner = runner
        for changes in ({'report_sha256': '0'*64}, {'calibration_id': '../private'}, {'step_mm': 0},
                        {'z_mm': float('nan')}, {'plane_prior': 'unknown'}, {'trigger_ids': [1]}):
            self.assertEqual(self.request('analyze', request | changes)[0], 400)
        self.assertEqual(self.request('analyze', request, {'Origin': 'https://foreign.invalid'})[0], 403)
        self.assertFalse(captured)
        with patch.object(W, 'transport_prefix', return_value=['existing-transport-helper']) as prefix:
            status, job = self.request('analyze', request)
            self.assertEqual((status, job['status']), (200, 'running'))
            self.assertTrue(self.ready.wait(2)); self.assertTrue(self.workflow.own_busy())
            self.assertEqual(self.control.state('mixed-unit')['analysis']['status'], 'running')
            self.assertEqual(self.request('analyze', request)[0], 400)
            self.finish(); prefix.assert_called_once_with(self.root)
        argv = captured[0]
        self.assertEqual(argv[:7], ['existing-transport-helper', 'env', 'OPENBLAS_NUM_THREADS=1',
                                   'OMP_NUM_THREADS=1', 'python', '-B', '../tools/gegi_candidate_imaging.py'])
        self.assertEqual(argv[argv.index('--calibration')+1], '../.local/gegi-center-calibration.npz')
        self.assertNotIn('--max-two-strip', argv); self.assertNotIn('--trigger-id', argv)
        job = self.control.state('mixed-unit'); self.assertEqual(job['analysis']['status'], 'completed')
        saved = job['analysis_maps'][0]
        query = 'plane?'+urlencode(dict(name='mixed-unit', report_sha256=request['report_sha256'], **saved))
        # Inventory display fields are not accepted as arbitrary route parameters.
        self.assertEqual(self.request(query)[0], 400)
        query = 'plane?'+urlencode({key: value for key, value in dict(name='mixed-unit', report_sha256=request['report_sha256'], **saved).items()
                                    if key in ('name','report_sha256','analysis_id','analysis_sha256')})
        status, view = self.request(query)
        self.assertEqual(status, 200); self.assertEqual(view['candidate_analysis']['source_census'], result['candidate_analysis']['source_census'])
        self.assertEqual(view['original_trigger_ids'], [1])
        self.assertEqual(view['candidate_analysis']['excluded_intervals_ns'], [[1000., 2000.]])
        self.assertNotIn('triggers', view); self.assertNotIn('fit_receipt', view)
        self.assertEqual(self.request(query.replace(saved['analysis_sha256'], '0'*64))[0], 400)
        self.assertEqual(self.request(query.replace(request['report_sha256'], '0'*64))[0], 400)
        self.assertEqual(self.request(query, headers={'X-Control-Token': 'wrong'})[0], 403)
        status, reused = self.request('analyze', request)
        self.assertEqual((status, reused['status'], reused['reused']), (200, 'completed', True))
        self.assertEqual(len(captured), 1)
        self.assertEqual(original, {name: W.sha(directory/name) for name in original})
        # An already completed map survives a Control interruption without a refit.
        saved_state = W.read(self.control.state_path)
        saved_state['jobs'][0]['analysis'].update(status='running', driver=None)
        W.write(self.control.state_path, saved_state)
        restored = J.WorkflowController(self.root).gegi_candidates()
        self.assertEqual(restored.state('mixed-unit')['analysis']['status'], 'completed')
        self.assertEqual(len(captured), 1)

    def test_imported_partial_map_is_explicit_and_never_reused_as_full(self):
        directory, request, result = self.imaging_fixture()
        result['candidate_analysis'].update(scope='explicit_analysis_subset', selected_original_trigger_ids=[])
        for layer in result['layers'].values():
            layer.update(triggers_with_geometry=0, hypotheses=0, projected_mass=0., unresolved_mass=1., mass=[[0.,0.],[0.,0.]])
        path = directory/'candidate-imaging-prefix.json.gz'; path.write_bytes(gzip.compress(W.encoded(result), mtime=0))
        saved = self.control.state('mixed-unit')['analysis_maps'][0]
        view = self.control.analysis_plane('mixed-unit', request['report_sha256'], saved['analysis_id'], saved['analysis_sha256'])
        self.assertEqual(view['candidate_analysis']['scope'], 'explicit_analysis_subset')
        self.control.analysis_runner = lambda *a, **k: {'exit_code': 7, 'output': 'Synthetic failed analysis'}
        status, job = self.request('analyze', request); self.assertEqual((status, job['status']), (200, 'running'))
        self.finish(); self.assertEqual(self.control.state('mixed-unit')['analysis']['status'], 'failed')
        self.assertEqual(json.loads(gzip.decompress(path.read_bytes()))['candidate_analysis']['scope'], 'explicit_analysis_subset')
        result['candidate_analysis']['source_census']['initial_parents'] = 99
        path.write_bytes(gzip.compress(W.encoded(result), mtime=0))
        with self.assertRaisesRegex(W.ControlError, 'denominators differ'):
            self.control.analysis_plane('mixed-unit', request['report_sha256'], saved['analysis_id'], W.sha(path))

    def test_peak_contributors_are_bound_to_map_window_and_paged(self):
        directory, acquisition, result = self.imaging_fixture()
        path = directory/'candidate-imaging.json.gz'
        path.write_bytes(gzip.compress(W.encoded(result), mtime=0))
        fields = dict(name='mixed-unit', report_sha256=acquisition['report_sha256'], analysis_id=path.name,
                      analysis_sha256=W.sha(path), layer='other_energy', offset=0)
        route = 'contributors?'+urlencode(fields)
        self.assertEqual(self.request(route, headers={'X-Control-Token': 'wrong'})[0], 403)
        for changes in ({'offset': -1}, {'analysis_id': '../file'}, {'analysis_sha256': '0'*64}, {'layer': 'unknown'}):
            self.assertEqual(self.request('contributors?'+urlencode(fields | changes))[0], 400)
        before = {p.name: W.sha(p) for p in directory.iterdir() if p.is_file()}
        with patch('gegi_candidate_records.peak_cell_contributors', return_value={
                'peak': {'position_mm': [-2., -2., 40.], 'on_image_edge': True, 'mass': 1.},
                'contributors': [dict(original_trigger_id=tid) for tid in range(1, 12)]}) as projector:
            status, first = self.request(route)
            self.assertEqual((status, first['offset'], first['total']), (200, 0, 11))
            self.assertEqual(first['items'][0]['original_trigger_id'], 1)
            status, last = self.request('contributors?'+urlencode(fields | {'offset': 10}))
            self.assertEqual((status, last['offset'], last['items']), (200, 10, [dict(original_trigger_id=11)]))
            self.assertEqual(first['analysis_sha256'], fields['analysis_sha256'])
            projector.assert_called_once()
        self.assertEqual(before, {p.name: W.sha(p) for p in directory.iterdir() if p.is_file()})

    def test_electrode_compatibility_recipe_does_not_reuse_plain_map(self):
        directory, request, result = self.imaging_fixture()
        plain = directory/'candidate-imaging.json.gz'
        plain.write_bytes(gzip.compress(W.encoded(result), mtime=0))
        self.assertEqual(self.request('analyze', request | {'compatibility': 'yes'})[0], 400)
        status, reused = self.request('analyze', request)
        self.assertEqual((status, reused['reused'], reused['compatibility']), (200, True, False))
        calls = []
        def runner(argv, **kwargs):
            calls.append(argv)
            compatible = copy.deepcopy(result)
            compatible['candidate_analysis']['compatibility'] = True
            output = (self.root/'transport'/argv[argv.index('--output')+1]).resolve()
            output.write_bytes(gzip.compress(W.encoded(compatible), mtime=0))
            return {'exit_code': 0, 'output': '{}'}
        self.control.analysis_runner = runner
        with patch.object(W, 'transport_prefix', return_value=['installed-transport-tool']):
            status, job = self.request('analyze', request | {'compatibility': True})
            self.assertEqual((status, job['status']), (200, 'running'))
            self.finish()
        self.assertIn('--compatibility', calls[0])
        status, reused = self.request('analyze', request | {'compatibility': True})
        self.assertEqual((status, reused['reused'], reused['compatibility']), (200, True, True))
        self.assertNotEqual(reused['analysis_id'], plain.name)

    def test_lateral_overlay_admits_distinct_bound_analysis_recipe(self):
        directory, request, result = self.imaging_fixture()
        overlay = self.root/'.local/gegi-lateral-calibration.npz'
        overlay.write_bytes(b'synthetic lateral overlay')
        found, = self.control.options()['lateral_calibrations']
        self.assertNotIn(found['id'], {row['id'] for row in self.control.options()['calibrations']})
        self.assertEqual(self.request('analyze', request | {'lateral_calibration_id':'../escape'})[0], 400)
        calls = []
        def runner(argv, **kwargs):
            calls.append(argv)
            bundle = {'archive_sha256':W.sha(overlay),'coverage_cells':[[3,24]]}
            modified = copy.deepcopy(result)
            modified['input_sha256']['lateral_calibration'] = bundle['archive_sha256']
            modified['candidate_analysis'].update(position_model='lateral',lateral_calibration=bundle)
            modified['fit_receipt'].update(position_model='lateral',lateral_calibration_bundle=bundle)
            output = (self.root/'transport'/argv[argv.index('--output')+1]).resolve()
            output.write_bytes(gzip.compress(W.encoded(modified),mtime=0))
            return {'exit_code':0,'output':'{}'}
        self.control.analysis_runner = runner
        selected = request | {'lateral_calibration_id':found['id']}
        with patch.object(W,'transport_prefix',return_value=['installed-transport-tool']):
            status, job = self.request('analyze', selected)
            self.assertEqual((status,job['status']),(200,'running'))
            self.finish()
        self.assertEqual(calls[0][calls[0].index('--position-model'):],
                         ['--position-model','lateral','--lateral-calibration','../.local/gegi-lateral-calibration.npz'])
        status, reused = self.request('analyze', selected)
        self.assertEqual((status,reused['reused'],reused['position_model']),(200,True,'lateral'))

    def test_range_open_is_read_only_and_range_worker_reuses_only_same_recipe(self):
        directory, request, saved = self.imaging_fixture()
        empty = dict(saved['layers']['all'], triggers=0, triggers_with_geometry=0, allowed_hypotheses=0,
                     hypotheses=0, projected_mass=0., unresolved_mass=0., mass=[[0.,0.],[0.,0.]])
        saved['layers'].update({key:empty for key in C.RANGE_WINDOWS[:3]})
        map_path = directory/'candidate-imaging.json.gz'
        map_path.write_bytes(gzip.compress(W.encoded(saved),mtime=0))
        binding = dict(name=request['name'], report_sha256=request['report_sha256'], analysis_id=map_path.name,
                       analysis_sha256=W.sha(map_path))
        range_result = dict(kind=C.RANGE_KIND, status='complete', input_sha256=binding['analysis_sha256'],
                            input_bindings=saved['input_sha256'], acquisition_selection=saved['selection'],
                            source_sha256=self.control._range_sources(), model=dict(radial_search_mm=[20.,10000.],
                            radial_points=49,directional_seeds=192,optimized_starts=6,extra_uniform_angle_fraction=.25,
                            background_profiling=True), fits={key:dict(status='insufficient_geometry_for_clock_halves',
                            selected_triggers=0) for key in C.RANGE_WINDOWS})
        archived = directory/'candidate-range-archive.json'
        W.write(archived,range_result | {'source_sha256':{key:'1'*64 for key in C.RANGE_SOURCES}})
        before = set(directory.iterdir())
        calls = []
        def runner(argv, **kwargs):
            calls.append(argv)
            output = (self.root/'transport'/argv[argv.index('--output')+1]).resolve()
            W.write(output,range_result)
            return {'exit_code':0,'output':'{}'}
        self.control.analysis_runner = runner
        status, plane = self.request('plane?'+urlencode(binding))
        self.assertEqual(status,200)
        entry, = plane['range_options']
        self.assertFalse(entry['current_solver'])
        self.assertTrue(entry['profile_background'])
        query = 'range?'+urlencode(binding | {k:entry[k] for k in ('range_id','range_sha256')})
        self.assertEqual(self.request(query,headers={'X-Control-Token':'no'})[0],403)
        self.assertEqual(self.request(query.replace(entry['range_sha256'],'0'*64))[0],400)
        status, opened = self.request(query)
        self.assertEqual((status,opened['result']['input_sha256']),(200,binding['analysis_sha256']))
        self.assertEqual(set(directory.iterdir()),before)
        self.assertFalse(calls)
        analysis = binding | dict(radius_min_mm=20.,radius_max_mm=10000.,profile_background=True)
        for wrong in ({'analysis_sha256':'0'*64},{'radius_min_mm':0},{'profile_background':'true'},{'source_position':[1,2,3]}):
            self.assertEqual(self.request('range',analysis | wrong)[0],400)
        with patch.object(W,'transport_prefix',return_value=['installed-transport']):
            status, start = self.request('range',analysis)
            self.assertEqual((status,start['status']),(200,'running'))
            self.finish()
        self.assertIn('../tools/gegi_candidate_range.py',calls[0])
        self.assertIn('--profile-background',calls[0])
        job = self.control.state('mixed-unit')['range_analysis']
        self.assertEqual(job['status'],'completed')
        self.assertEqual(self.control.state('mixed-unit')['range_analysis']['range_result']['range_sha256'],
                         W.sha(directory/start['range_file']))
        status, reused = self.request('range',analysis)
        self.assertEqual((status,reused['status'],reused['reused'],reused['current_solver']),(200,'completed',True,True))
        self.assertEqual(len(calls),1)


if __name__ == '__main__':
    unittest.main()
