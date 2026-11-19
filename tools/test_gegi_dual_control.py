"""Dual-source Control selection, session protection and async state contract."""

from io import BytesIO
import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from urllib.parse import urlencode

import gegi_dual_control as G
from gegi_pixel_map import project_pixel_map, read_pixel_map
import local_ui as U
import local_ui_workflow_jobs as J
import scenario_workflow as W


def trigger(time, single=None, multi=None, x=(), y=(), guard=()):
    return dict(trigger_time_ns=time, single_pixel_energy_keV=single, additional_multi_strip_energy_keV=multi,
                x_collecting_strips=list(x), y_collecting_strips=list(y), guard_contact_ids=list(guard))


def fixture_report(sources, activities, duration, seed):
    def spectrum(n):
        return dict(bin_edges_keV=[0, 20, 40], counts=[n, 0], entries=n, underflow=0, overflow=0, exact_zero=0)
    return dict(kind=G.REPORT_KIND, status='completed', design=dict(clock_seed=seed, live_time_s=duration),
                exposure=dict(clock_live_time_ns=100, qualified_adc_live_time_ns=80, masked_live_time_ns=20,
                              total_live_adc_samples=5, qualified_live_adc_samples=4),
                sources=[dict(activity_bq=bq, original=source, input_directory={'absolute': 'private-science-path'},
                              counts=dict(parents=2, marked_zero_parents=1, group_onsets_in_live_time=1))
                         for source, bq in zip(sources, activities)],
                counts=dict(initial_parents_in_live_time=4, deposit_groups=2, complete_deposit_groups=2,
                            right_censored_deposit_groups=0, native_unavailable_groups=0, prehistory_unqualified_groups=0,
                            qualified_triggers=2, single_pixel_energies=1, additional_multi_strip_energies=1,
                            qualified_energies=2, triggers_without_energy=0),
                spectra=dict(single_pixel=spectrum(1), additional_multi_strip=spectrum(1), combined=spectrum(2)),
                triggers=[{**trigger(20, single=15, x=(2,), y=(33,)), 'large_private_array': True},
                          trigger(60, multi=16, x=(2, 3), y=(33,))])


def add_measured_features(report):
    def neighbor(contact, fast, flags=()):
        return dict(contact_id=contact, fast_keV_equiv=fast, flags=list(flags))

    report['design']['single_pixel_features'] = dict(fast_area_gate_ns=[0, 240])
    first, multi = report['triggers']
    x = dict(contact_id=2, slow_energy_keV=14.9, low=neighbor(1, -1.5), high=neighbor(3, 0), fast_ratio=-0.1)
    y = dict(contact_id=33, slow_energy_keV=15.1, low=neighbor(32, None, ('fast_pileup',)), high=None,
             fast_ratio=None)
    first['single_pixel_features'] = dict(x={**x, 'private_row': 'private-measurement'}, y=y)
    multi['single_pixel_features'] = None
    report['triggers'].append({**trigger(80, single=18, x=(2,), y=(33,)),
                               'single_pixel_features': dict(x={**x, 'slow_energy_keV': 18.2,
                                                                'high': neighbor(3, 2.1), 'fast_ratio': -0.2},
                                                             y={**y, 'slow_energy_keV': 17.8})})
    report['counts'].update(qualified_triggers=3, single_pixel_energies=2, qualified_energies=3)
    for name in ('single_pixel', 'combined'):
        spectrum = report['spectra'][name]
        spectrum['counts'][0] += 1
        spectrum['entries'] += 1


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
            W.write(report, fixture_report([describe(path) for path in paths], activities, duration, seed))

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
        pixels = job['result']['pixel_map']
        self.assertEqual(pixels['counts'][15][1], 1)
        self.assertEqual(pixels['totals'], dict(qualified_triggers=2, mapped_single_pixel_triggers=1,
                        multi_strip_energy_triggers=1, triggers_without_energy=0, occupied_pixels=1))
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

    def test_old_completed_job_keeps_spectrum_if_saved_report_changes_or_is_missing(self):
        _, options = self.request('options')
        request = dict(source_ids=[source['id'] for source in options['libraries']],
                       activities_bq=[18, 74], live_time_s=.05, seed='18', name='preserved')
        self.assertEqual(self.request('start', request)[0], 200)
        self.assertTrue(self.ready.wait(2))
        self.finish()
        old_state = (self.root/G.STATE).read_bytes()
        job = J.WorkflowController(self.root).gegi_dual_source().state('preserved')
        self.assertEqual(job['result']['pixel_map']['status'], 'available')
        path = self.root/job['output']
        report_sha = W.sha(path)
        with path.open('ab') as out:
            out.write(b'\n')
        for reason in ('report_changed', 'report_missing'):
            result = J.WorkflowController(self.root).gegi_dual_source().state('preserved')
            self.assertEqual(result['status'], 'completed')
            self.assertEqual(result['report_sha256'], report_sha)
            self.assertEqual(result['result']['spectra'], job['result']['spectra'])
            pixels = result['result']['pixel_map']
            self.assertEqual((pixels['status'], pixels['reason'], pixels['counts']), ('unavailable', reason, None))
            self.assertEqual(result['result']['single_pixel_features'], dict(status='unavailable', reason=reason))
            if reason == 'report_changed':
                path.unlink()
        self.assertEqual((self.root/G.STATE).read_bytes(), old_state)

    def test_standalone_report_is_discovered_without_persisting_a_job(self):
        _, options = self.request('options')
        payload = fixture_report(options['libraries'], [18, 74], .05, 18)
        archive = self.root/G.report_ref('archived')
        W.write(archive, payload)
        W.write(self.root/G.report_ref('not a valid name'), payload)
        original = archive.read_bytes()
        _, options = self.request('options')
        self.assertEqual(options['jobs'], [{'name': 'archived', 'status': 'completed', 'archived_report': True}])
        status, job = self.request('state?name=archived')
        self.assertEqual((status, job['status'], job['archived_report']), (200, 'completed', True))
        self.assertEqual(job['activities_bq'], [18, 74])
        self.assertEqual(job['sources'][0]['source_position_mm'], [-40, 0, 40])
        self.assertEqual(job['result']['spectra']['combined']['entries'], 2)
        self.assertEqual(job['result']['pixel_map']['counts'][15][1], 1)
        self.assertEqual(job['result']['single_pixel_features'], dict(status='unavailable', reason='not_captured'))
        self.assertNotIn('private-science-path', json.dumps(job))
        self.assertFalse((self.root/G.STATE).exists())
        self.assertEqual(archive.read_bytes(), original)
        self.assertEqual(read_pixel_map(archive), job['result']['pixel_map'])
        self.assertFalse(self.calls)

    def test_protected_feature_navigation_reads_only_selected_projection(self):
        _, options = self.request('options')
        payload = fixture_report(options['libraries'], [18, 74], .05, 18)
        add_measured_features(payload)
        archive = self.root/G.report_ref('featured')
        W.write(archive, payload)
        original = archive.read_bytes()
        status, job = self.request('state?name=featured')
        self.assertEqual(status, 200)
        result = job['result']
        self.assertEqual(result['pixel_map']['counts'][15][1], 2)
        self.assertEqual(result['spectra']['combined']['entries'], 3)
        features = result['single_pixel_features']
        self.assertEqual((features['status'], features['count'], features['fast_area_gate_ns']), ('available', 2, [0, 240]))
        first = features['trigger']
        self.assertEqual((first['ordinal'], first['trigger_time_ns'], first['single_pixel_energy_keV']), (1, 20, 15))
        self.assertEqual(first['x']['low'], dict(contact_id=1, fast_keV_equiv=-1.5, flags=[]))
        self.assertEqual(first['x']['high']['fast_keV_equiv'], 0)
        self.assertEqual(first['y']['low'], dict(contact_id=32, fast_keV_equiv=None, flags=['fast_pileup']))
        self.assertIsNone(first['y']['high'])
        self.assertIsNone(first['y']['fast_ratio'])
        self.assertNotIn('private-measurement', json.dumps(job))
        query = dict(name='featured', report_sha256=job['report_sha256'], ordinal=2)
        route = 'single-pixel?' + urlencode(query)
        self.assertEqual(self.request(route, headers={'X-Control-Token': 'wrong'})[0], 403)
        status, selected = self.request(route)
        self.assertEqual(status, 200)
        self.assertEqual(set(selected), {'name', 'report_sha256', 'trigger'})
        self.assertEqual(selected['report_sha256'], job['report_sha256'])
        second = selected['trigger']
        self.assertEqual((second['ordinal'], second['trigger_time_ns'], second['x']['fast_ratio']), (2, 80, -0.2))
        for bad in (dict(ordinal=0), dict(ordinal=3), dict(name='../sealed'),
                    dict(report_sha256='a'*64), dict(file='report.json')):
            self.assertEqual(self.request('single-pixel?' + urlencode({**query, **bad}))[0], 400)
        self.assertEqual(archive.read_bytes(), original)
        self.assertFalse((self.root/G.STATE).exists())
        self.assertFalse(self.calls)
        with archive.open('ab') as out:
            out.write(b'\n')
        status, error = self.request(route)
        self.assertEqual(status, 400)
        self.assertIn('differs from its completion receipt', error['error'])

    def test_malformed_fast_face_does_not_hide_existing_spectrum_and_map(self):
        _, options = self.request('options')
        payload = fixture_report(options['libraries'], [18, 74], .05, 18)
        add_measured_features(payload)
        payload['triggers'][0]['single_pixel_features']['y']['high'] = dict(contact_id=34, fast_keV_equiv=0, flags=[])
        W.write(self.root/G.report_ref('bad-feature'), payload)
        status, job = self.request('state?name=bad-feature')
        self.assertEqual(status, 200)
        self.assertEqual(job['result']['pixel_map']['status'], 'available')
        self.assertEqual(job['result']['spectra']['combined']['entries'], 3)
        self.assertEqual(job['result']['single_pixel_features'], dict(status='unavailable', reason='invalid_features'))


class PixelMapTests(unittest.TestCase):
    def report(self, samples, triggers, singles, multis, missing):
        return {'kind': G.REPORT_KIND, 'status': 'completed', 'exposure': {'qualified_live_adc_samples': samples},
                'triggers': triggers, 'counts': dict(qualified_triggers=len(triggers) if triggers is not None else None,
                    single_pixel_energies=singles, additional_multi_strip_energies=multis,
                    qualified_energies=None if singles is None else singles + multis, triggers_without_energy=missing)}

    def test_orientation_and_exclusive_counting(self):
        rows = [trigger(20, single=20., x=(16,), y=(18,)), trigger(40, single=30., x=(16,), y=(18,)),
                trigger(60, single=20., x=(1,), y=(33,)), trigger(80, multi=42, x=(1, 16), y=(33,)),
                trigger(100, guard=(17, 34))]
        pixels = project_pixel_map(self.report(400, rows, 3, 1, 1))
        self.assertEqual((pixels['counts'][0][15], pixels['counts'][15][0]), (2, 1))
        self.assertEqual(sum(map(sum, pixels['counts'])), 3)
        self.assertEqual(pixels['totals'], dict(qualified_triggers=5, mapped_single_pixel_triggers=3,
                        multi_strip_energy_triggers=1, triggers_without_energy=1, occupied_pixels=2))

    def test_no_qualified_samples_and_measurable_empty_are_distinct(self):
        unknown = project_pixel_map(self.report(0, None, None, None, None))
        self.assertEqual((unknown['status'], unknown['reason'], unknown['counts'], unknown['totals']),
                         ('unavailable', 'no_qualified_adc_samples', None, None))
        empty = project_pixel_map(self.report(100, [trigger(20)], 0, 0, 1))
        self.assertEqual((empty['status'], empty['reason']), ('empty', 'no_qualified_single_pixel_energies'))
        self.assertEqual(sum(map(sum, empty['counts'])), 0)
        self.assertEqual(empty['totals']['triggers_without_energy'], 1)

    def test_malformed_single_or_duplicate_triggers_are_not_projected(self):
        bad = trigger(20, single=30., x=(17,), y=(33,))
        good = trigger(20, single=30., x=(1,), y=(33,))
        for report in (self.report(100, [bad], 1, 0, 0), self.report(100, [good, good], 2, 0, 0),
                       self.report(100, [good], 0, 0, 1)):
            self.assertEqual(project_pixel_map(report)['reason'], 'invalid_report')


if __name__ == '__main__':
    unittest.main()
