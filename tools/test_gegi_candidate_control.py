"""Bounded Control lifecycle, protection and saved selected-electrode contracts."""

import copy
from io import BytesIO
import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
from urllib.parse import urlencode
import unittest

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
        self.assertEqual(estimate['execution_primary_limit'], 500)
        self.assertEqual(estimate['new_science_calls'], 0)
        self.assertEqual(estimate['shared_field_cache_bytes'], 857068900)
        self.assertGreater(estimate['planning_range_bytes'][1], estimate['planning_range_bytes'][0])
        self.assertFalse(estimate['runtime_scratch']['production_ready'])
        self.assertEqual(estimate['runtime_scratch']['status'], 'not_estimated_from_this_readout_reference')
        self.assertIsNone(estimate['runtime_prediction'])
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
        settings = self.settings()
        for changed in ({'name': '../escape'}, {'primary_count': 501}, {'primary_count': True}, {'seed': 0},
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


if __name__ == '__main__':
    unittest.main()
