"""Dual-source Control selection, session protection and async state contract."""

from io import BytesIO
import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest

import gegi_dual_control as G
import local_ui as U
import local_ui_workflow_jobs as J
import scenario_workflow as W


class DualControlTests(unittest.TestCase):
    def setUp(self):
        area = tempfile.TemporaryDirectory(prefix='gegi-dual-control-', dir=W.ROOT/'.local')
        self.addCleanup(area.cleanup)
        self.root = Path(area.name)
        self.ready, self.release = threading.Event(), threading.Event()
        self.calls = []
        for name in ('first', 'second', 'incomplete'):
            (self.root/G.IMPORTS/name).mkdir(parents=True)

        def describe(path):
            if path.name == 'incomplete':
                raise ValueError('Missing sealed receipt')
            first = path.name == 'first'
            return dict(isotope='Cs-137' if first else 'Co-60', source_position_mm=[-40 if first else 40, 0, 40],
                        original={'initial_primaries': 10000}, chunk_sha256=('a' if first else 'b')*64)

        def runner(paths, activities, duration, seed, report):
            self.calls.append((paths, activities, duration, seed, report))
            self.ready.set()
            if not self.release.wait(5):
                raise RuntimeError('Test fixture timed out')
            def spectrum(n):
                return dict(bin_edges_keV=[0, 20, 40], counts=[n, 0], entries=n, underflow=0, overflow=0, exact_zero=0)
            payload = dict(kind=G.REPORT_KIND, status='completed', design=dict(clock_seed=seed, live_time_s=duration),
                exposure=dict(clock_live_time_ns=100, qualified_adc_live_time_ns=80, masked_live_time_ns=20,
                              total_live_adc_samples=5, qualified_live_adc_samples=4),
                sources=[dict(activity_bq=bq, original=describe(path),
                              counts=dict(parents=2, marked_zero_parents=1, group_onsets_in_live_time=1))
                         for path, bq in zip(paths, activities)],
                counts=dict(initial_parents_in_live_time=4, deposit_groups=2, complete_deposit_groups=2,
                            right_censored_deposit_groups=0, native_unavailable_groups=0, prehistory_unqualified_groups=0,
                            qualified_triggers=2, single_pixel_energies=1, additional_multi_strip_energies=1,
                            qualified_energies=2, triggers_without_energy=0),
                spectra=dict(single_pixel=spectrum(1), additional_multi_strip=spectrum(1), combined=spectrum(2)),
                triggers=[{'large_private_array': True}])
            W.write(report, payload)

        self.workflow = J.WorkflowController(self.root)
        self.workflow._gegi_dual_control = G.DualSourceControl(self.workflow, describe=describe, runner=runner)
        self.server = SimpleNamespace(origin='http://127.0.0.1:8765', token='local-dual-test',
                                      workflow_controller=self.workflow)
        self.addCleanup(self.finish)

    def finish(self):
        self.release.set()
        end = time.monotonic()+5
        while self.workflow._active is not None and time.monotonic()<end:
            time.sleep(.01)
        self.assertIsNone(self.workflow._active)

    def request(self, route, data=None, headers=None):
        handler = object.__new__(U.Handler)
        handler.server = self.server
        handler.path = '/api/workflow/gegi-dual/'+route
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

    def test_protected_inventory_exact_post_async_job_and_compact_receipt(self):
        self.assertEqual(self.request('options', headers={'X-Control-Token': 'wrong'})[0], 403)
        status, inventory = self.request('options')
        self.assertEqual(status, 200)
        a, b = inventory['libraries']
        self.assertEqual((a['isotope'], a['source_position_mm'], b['isotope']), ('Cs-137', [-40, 0, 40], 'Co-60'))
        self.assertEqual(inventory['rejected'], [{'label': 'incomplete', 'error': 'Missing sealed receipt'}])
        self.assertNotIn(str(self.root), json.dumps(inventory))
        request = dict(source_ids=[a['id'], b['id']], activities_bq=[18500, 74000], live_time_s=.05,
                       seed='18446744073709551615', name='changed')
        for changes in ({'output': '../escape.json'}, {'source_ids': ['../private', b['id']]},
                        {'seed': '18446744073709551616'}, {'name': '../escape'}, {'activities_bq': [True, 0]}):
            self.assertEqual(self.request('start', {**request, **changes})[0], 400)
        self.assertEqual(self.request('start', request, {'Origin': 'https://foreign.invalid'})[0], 403)
        self.assertFalse(self.calls)
        status, job = self.request('start', request)
        self.assertEqual((status, job['status']), (200, 'running'))
        self.assertTrue(self.ready.wait(2))
        self.assertTrue(self.workflow.own_busy())
        self.assertEqual(self.request('start', {**request, 'name': 'second-run'})[0], 400)
        self.assertEqual(self.request('state?name=changed&file=../private')[0], 400)
        self.assertEqual(self.calls[0][1:4], ([18500, 74000], .05, 2**64-1))
        self.finish()
        status, job = self.request('state?name=changed')
        self.assertEqual((status, job['status'], job['result']['spectra']['combined']['entries']), (200, 'completed', 2))
        self.assertNotIn('large_private_array', json.dumps(job))
        self.assertEqual(job['report_sha256'], W.sha(self.root/job['output']))
        self.assertEqual(J.WorkflowController(self.root).gegi_dual_source().state('changed'), job)
        self.assertEqual(self.request('start', request)[0], 400)
        stale = {key: value for key, value in job.items() if key not in ('result', 'report_sha256', 'finished_utc')}
        stale['status'] = 'running'
        W.write(self.root/G.STATE, {'kind': G.KIND, 'jobs': [stale, dict(stale, name='in-progress')]})
        restored = J.WorkflowController(self.root).gegi_dual_source()
        self.assertEqual(restored.state('changed')['report_sha256'], job['report_sha256'])
        self.assertEqual(restored.state('changed')['status'], 'completed')
        self.assertEqual(restored.state('in-progress')['status'], 'interrupted')
        self.assertEqual(len(self.calls), 1)


if __name__ == '__main__':
    unittest.main()
