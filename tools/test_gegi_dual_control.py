"""Dual-source Control selection, session protection and async state contract."""

from io import BytesIO
import json
import math
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

import gegi_dual_control as G
from gegi_pixel_map import project_pixel_energy, project_pixel_map, read_pixel_map
import local_ui as U
import local_ui_workflow_jobs as J
import scenario_workflow as W


def trigger(time, single=None, multi=None, x=(), y=(), guard=()):
    return dict(trigger_time_ns=time, single_pixel_energy_keV=single, additional_multi_strip_energy_keV=multi,
                x_collecting_strips=list(x), y_collecting_strips=list(y), guard_contact_ids=list(guard))


def fixture_trigger_settings(profile):
    return dict(id=profile, coincidence_threshold_keV_per_sample=4.0 if profile == 'low-energy' else 5.0,
                quiet_threshold_keV_per_sample=3.0, sample_period_ns=20)


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
        self.report_profile = None
        for name in ('first', 'second', 'incomplete'):
            (self.root/G.IMPORTS/name).mkdir(parents=True)

        def describe(path):
            if path.name == 'incomplete':
                raise ValueError('Missing sealed receipt')
            first = path.name == 'first'
            return dict(isotope='Cs-137' if first else 'Co-60', source_position_mm=[-40 if first else 40, 0, 40],
                        original={'initial_primaries': 10000}, chunk_sha256=('a' if first else 'b')*64)

        def runner(paths, activities, duration, seed, report, *, trigger_profile):
            self.calls.append((paths, activities, duration, seed, report, trigger_profile))
            self.ready.set()
            if not self.release.wait(5):
                raise RuntimeError('Test fixture timed out')
            payload = fixture_report([describe(path) for path in paths], activities, duration, seed)
            settings = fixture_trigger_settings(self.report_profile or trigger_profile)
            payload['design']['trigger_profile'] = settings
            payload['receipt'] = {'trigger_profile': settings}
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
                       seed='18446744073709551615', name='changed', trigger_profile='low-energy')
        for changes in ({'output': '../escape.json'}, {'source_ids': ['../private', b['id']]},
                        {'seed': '18446744073709551616'}, {'name': '../escape'}, {'activities_bq': [True, 0]},
                        {'trigger_profile': 'custom'}, {'trigger_profile': None}):
            self.assertEqual(self.request('start', {**request, **changes})[0], 400)
        self.assertEqual(self.request('start', request, {'Origin': 'https://foreign.invalid'})[0], 403)
        self.assertFalse(self.calls)
        status, job = self.request('start', request)
        self.assertEqual((status, job['status']), (200, 'running'))
        self.assertEqual(job['trigger_profile'], 'low-energy')
        self.assertTrue(self.ready.wait(2))
        self.assertTrue(self.workflow.own_busy())
        self.assertEqual(self.request('start', {**request, 'name': 'second-run'})[0], 400)
        self.assertEqual(self.request('state?name=changed&file=../private')[0], 400)
        self.assertEqual(self.calls[0][1:4], ([18500, 74000], .05, 2**64-1))
        self.assertEqual(self.calls[0][5], 'low-energy')
        self.finish()
        status, job = self.request('state?name=changed')
        self.assertEqual((status, job['status'], job['result']['spectra']['combined']['entries']), (200, 'completed', 2))
        self.assertEqual(job['result']['trigger_profile'], fixture_trigger_settings('low-energy'))
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

    def test_worker_refuses_result_with_different_trigger_profile(self):
        self.report_profile = 'standard'
        _, options = self.request('options')
        request = dict(source_ids=[source['id'] for source in options['libraries']], activities_bq=[18, 74],
                       live_time_s=.05, seed='18', name='wrong-profile', trigger_profile='low-energy')
        self.assertEqual(self.request('start', request)[0], 200)
        self.assertTrue(self.ready.wait(2))
        self.finish()
        status, job = self.request('state?name=wrong-profile')
        self.assertEqual((status, job['status']), (200, 'failed'))
        self.assertIn('used a different trigger profile', job['error'])

    def test_old_completed_job_keeps_spectrum_if_saved_report_changes_or_is_missing(self):
        _, options = self.request('options')
        request = dict(source_ids=[source['id'] for source in options['libraries']],
                       activities_bq=[18, 74], live_time_s=.05, seed='18', name='preserved')
        self.assertEqual(self.request('start', request)[0], 200)
        self.assertTrue(self.ready.wait(2))
        self.finish()
        self.assertEqual(self.calls[0][5], 'standard')
        legacy_state = W.read(self.root/G.STATE)
        legacy_state['jobs'][0].pop('trigger_profile')
        legacy_state['jobs'][0]['result'].pop('trigger_profile')
        W.write(self.root/G.STATE, legacy_state)
        old_state = (self.root/G.STATE).read_bytes()
        job = J.WorkflowController(self.root).gegi_dual_source().state('preserved')
        self.assertEqual(job['result']['pixel_map']['status'], 'available')
        self.assertEqual(job['result']['trigger_profile'], fixture_trigger_settings('standard'))
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
        self.assertEqual(job['result']['trigger_profile'], fixture_trigger_settings('standard'))
        self.assertEqual(job['result']['pixel_map']['counts'][15][1], 1)
        self.assertEqual(job['result']['single_pixel_features'], dict(status='unavailable', reason='not_captured'))
        self.assertNotIn('two_strip_pairings', job['result'])
        query = urlencode(dict(name='archived', report_sha256=job['report_sha256'], ordinal=1))
        self.assertEqual(self.request('two-strip?' + query)[0], 400)
        self.assertNotIn('private-science-path', json.dumps(job))
        self.assertFalse((self.root/G.STATE).exists())
        self.assertEqual(archive.read_bytes(), original)
        self.assertEqual(read_pixel_map(archive), job['result']['pixel_map'])
        self.assertFalse(self.calls)

    def test_protected_feature_navigation_reads_only_selected_projection(self):
        _, options = self.request('options')
        payload = fixture_report(options['libraries'], [18, 74], .05, 18)
        add_measured_features(payload)
        settings = fixture_trigger_settings('low-energy')
        payload['design']['trigger_profile'] = settings
        payload['receipt'] = {'trigger_profile': settings}
        archive = self.root/G.report_ref('featured')
        W.write(archive, payload)
        original = archive.read_bytes()
        status, job = self.request('state?name=featured')
        self.assertEqual(status, 200)
        result = job['result']
        self.assertEqual(result['trigger_profile'], settings)
        self.assertEqual(result['pixel_map']['counts'][15][1], 2)
        self.assertEqual(result['spectra']['combined']['entries'], 3)
        features = result['single_pixel_features']
        self.assertEqual((features['status'], features['count'], features['fast_area_gate_ns']), ('available', 2, [0, 240]))
        first = features['trigger']
        self.assertEqual((first['ordinal'], first['trigger_time_ns'], first['single_pixel_energy_keV']), (1, 20, 15))
        self.assertNotIn('calibrated_ordinals', features)
        self.assertNotIn('nominal_position', first)
        self.assertNotIn('preamp_cfd50_ns', first['x'])
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

    def test_nominal_position_shortcuts_and_selected_axis_projection(self):
        _, options = self.request('options')
        payload = fixture_report(options['libraries'], [18, 74], .05, 18)
        add_measured_features(payload)
        first, multi, _ = payload['triggers']
        first['nominal_position'] = dict(status='uncalibrated_pixel', energy_scope='outside_tested_range')
        first['single_pixel_features']['x']['preamp_cfd50_ns'] = -1.25
        first['single_pixel_features']['y']['preamp_cfd50_ns'] = None

        def measured(time, energy, estimate):
            def face(contact, cfd):
                return dict(contact_id=contact, slow_energy_keV=energy, preamp_cfd50_ns=cfd,
                            low=dict(contact_id=contact-1, fast_keV_equiv=2, flags=[]),
                            high=dict(contact_id=contact+1, fast_keV_equiv=1, flags=[]), fast_ratio=1/energy)
            return {**trigger(time, single=energy, x=(11,), y=(24,)), 'nominal_position': estimate,
                    'single_pixel_features': {'x': face(11, -1.25), 'y': face(24, 2.75)}}

        axes = dict(x=dict(status='estimated', position_mm=4.25, slot=0, private='private-fit'),
                    y=dict(status='estimated', position_mm=-9.4, slot=1),
                    z=dict(status='estimated', position_mm=-1.3))
        full = dict(status='estimated', energy_scope='within_tested_range', axes=axes,
                    position_mm=[4.25, -9.4, -1.3], method='direct_strip_calibration',
                    tested_energies_keV=[250, 500, 662])
        partial = dict(status='partial', energy_scope='outside_tested_range', position_mm=None,
                       method='family_template_transfer', tested_energies_keV=[500],
                       axes={**axes, 'y': dict(status='ratio_outside_calibration', position_mm=None, slot=None)})
        payload['triggers'] = [first, measured(40, 400, full), multi, measured(80, 680, partial)]
        pixel_depths = {
            2: dict(status='estimated', apparent_depth_mm=-1.45, cfd_x_minus_y_ns=-4.,
                    evidence_level='local_independent_off_center_check'),
            3: dict(status='outside_calibrated_cfd_range', apparent_depth_mm=None, cfd_x_minus_y_ns=150.,
                    evidence_level='center_calibration_only'),
        }
        payload['triggers'][1]['pixel_depth'] = {**pixel_depths[2], 'debug': 'private-pixel-data'}
        payload['triggers'][3]['pixel_depth'] = pixel_depths[3]
        payload['counts'].update(qualified_triggers=4, single_pixel_energies=3, qualified_energies=4)
        for name, counts in (('single_pixel', [1, 1, 1]), ('additional_multi_strip', [1, 0, 0]), ('combined', [2, 1, 1])):
            payload['spectra'][name].update(bin_edges_keV=[0, 250, 500, 750], counts=counts, entries=sum(counts))
        W.write(self.root/G.report_ref('positions'), payload)

        status, job = self.request('state?name=positions')
        self.assertEqual(status, 200)
        view = job['result']['single_pixel_features']
        self.assertEqual(view['calibrated_ordinals'], [2, 3])
        self.assertEqual(view['trigger']['nominal_position'], first['nominal_position'])
        self.assertEqual(view['trigger']['x']['preamp_cfd50_ns'], -1.25)
        self.assertIsNone(view['trigger']['y']['preamp_cfd50_ns'])
        self.assertNotIn('pixel_depth', view['trigger'])
        for ordinal, estimate in ((2, full), (3, partial)):
            query = urlencode(dict(name='positions', report_sha256=job['report_sha256'], ordinal=ordinal))
            status, detail = self.request('single-pixel?' + query)
            self.assertEqual(status, 200)
            self.assertEqual(detail['trigger']['ordinal'], ordinal)
            position = detail['trigger']['nominal_position']
            self.assertEqual(position['status'], estimate['status'])
            self.assertEqual(position['energy_scope'], estimate['energy_scope'])
            self.assertEqual(position['position_mm'], estimate['position_mm'])
            self.assertEqual(position['method'], estimate['method'])
            self.assertEqual(position['tested_energies_keV'], estimate['tested_energies_keV'])
            self.assertEqual(position['axes']['x'], dict(status='estimated', position_mm=4.25, slot=0))
            self.assertEqual(position['axes']['y'], estimate['axes']['y'])
            self.assertEqual(detail['trigger']['y']['preamp_cfd50_ns'], 2.75)
            self.assertEqual(detail['trigger']['pixel_depth'], pixel_depths[ordinal])
            self.assertNotIn('private-fit', json.dumps(detail))
            self.assertNotIn('private-pixel-data', json.dumps(detail))
        with self.assertRaisesRegex(G.ControlError, 'Invalid apparent pixel depth'):
            G.pixel_depth_record({**pixel_depths[3], 'apparent_depth_mm': 4.})

    def test_two_strip_pairing_view_retains_alternatives_and_reads_one_trigger(self):
        _, options = self.request('options')
        payload = fixture_report(options['libraries'], [18, 74], .05, 18)
        payload['design']['two_strip_pairings'] = {'selection': 'two collecting strips per face'}
        xs, ys = (2, 3), (32, 33)

        def measured(time, values):
            pairings = []
            for index, order in enumerate((ys, ys[::-1])):
                sites = [dict(x_contact_id=x, y_contact_id=y, x_energy_keV=values[xs.index(x)],
                              y_energy_keV=values[ys.index(y)],
                              energy_keV=(values[xs.index(x)]+values[ys.index(y)])/2,
                              position_mm=['private-spatial-data']) for x, y in zip(xs, order, strict=True)]
                compatible = all(site['x_energy_keV'] == site['y_energy_keV'] for site in sites)
                orders = []
                if compatible:
                    energy = sum(values)
                    for first, second in ((0, 1), (1, 0)):
                        cosine = 1 - 511*(1/sites[second]['energy_keV'] - 1/energy)
                        allowed = -1 <= cosine <= 1
                        orders.append(dict(site_index_order=[first, second], kinematically_allowed=allowed,
                                           half_angle_deg=math.degrees(math.acos(cosine)) if allowed else None,
                                           cos_theta=cosine))
                paired = dict(index=index, energy_compatible=compatible, sites=sites, compton_orders=orders)
                if time == 60 and compatible:
                    paired['pixel_depths'] = [
                        dict(status='estimated', apparent_depth_mm=index-1.25, cfd_x_minus_y_ns=20.+index,
                             evidence_level='local_independent_off_center_check'),
                        dict(status='outside_calibrated_cfd_range', apparent_depth_mm=None, cfd_x_minus_y_ns=123.+index,
                             evidence_level='center_calibration_only'),
                    ]
                pairings.append(paired)
            features = dict(compatible_pairing_count=sum(pair['energy_compatible'] for pair in pairings),
                            pairings=pairings, flags=['overlapping_x_neighborhoods'])
            return {**trigger(time, multi=sum(values), x=xs, y=ys), 'two_strip_pairings': features}

        payload['triggers'][1:] = [measured(40, (100, 500)), measured(60, (300, 300))]
        payload['counts'].update(qualified_triggers=3, additional_multi_strip_energies=2, qualified_energies=3)
        payload['spectra']['additional_multi_strip'].update(counts=[0, 0], overflow=2, entries=2)
        payload['spectra']['combined'].update(counts=[1, 0], overflow=2, entries=3)
        path = self.root/G.report_ref('two-strip')
        W.write(path, payload)
        status, job = self.request('state?name=two-strip')
        self.assertEqual(status, 200)
        view = job['result']['two_strip_pairings']
        self.assertEqual((view['status'], view['count']), ('available', 2))
        first = view['trigger']
        self.assertEqual((first['ordinal'], first['trigger_time_ns'], first['energy_keV']), (1, 40, 600))
        pairs = first['two_strip_pairings']
        self.assertEqual(pairs['compatible_pairing_count'], 1)
        self.assertEqual([pair['energy_compatible'] for pair in pairs['pairings']], [True, False])
        self.assertTrue(all('pixel_depths' not in pair for pair in pairs['pairings']))
        self.assertEqual(pairs['flags'], ['overlapping_x_neighborhoods'])
        orders = pairs['pairings'][0]['compton_orders']
        self.assertEqual([order['kinematically_allowed'] for order in orders], [True, False])
        self.assertIsNone(orders[1]['half_angle_deg'])
        self.assertNotIn('private-spatial-data', json.dumps(job))
        query = dict(name='two-strip', report_sha256=job['report_sha256'], ordinal=2)
        route = 'two-strip?' + urlencode(query)
        self.assertEqual(self.request(route, headers={'X-Control-Token': 'wrong'})[0], 403)
        status, reply = self.request(route)
        self.assertEqual(status, 200)
        self.assertEqual(set(reply), {'name', 'report_sha256', 'trigger'})
        selected = reply['trigger']
        self.assertEqual((selected['ordinal'], selected['trigger_time_ns']), (2, 60))
        self.assertEqual(selected['two_strip_pairings']['compatible_pairing_count'], 2)
        self.assertEqual([site['y_contact_id'] for site in selected['two_strip_pairings']['pairings'][1]['sites']],
                         [33, 32])
        for projected, saved in zip(selected['two_strip_pairings']['pairings'],
                                    payload['triggers'][2]['two_strip_pairings']['pairings'], strict=True):
            self.assertEqual(projected['pixel_depths'], saved['pixel_depths'])
        self.assertNotEqual(selected['two_strip_pairings']['pairings'][0]['pixel_depths'],
                            selected['two_strip_pairings']['pairings'][1]['pixel_depths'])
        self.assertNotIn('private-spatial-data', json.dumps(reply))
        self.assertEqual(self.request('two-strip?' + urlencode({**query, 'ordinal': 3}))[0], 400)
        self.assertEqual(self.request('two-strip?' + urlencode({**query, 'report_sha256': '0'*64}))[0], 400)

        old_adc = 'two-strip-adc?' + urlencode({**query, 'contact_id': 2})
        status, missing = self.request(old_adc)
        self.assertEqual((status, missing['status'], missing['preamp_V']), (200, 'not_captured', None))

        import numpy as np
        import gegi_digital_readout as D
        payload['design']['adc_phase_ns'] = 0
        payload['exposure'].update(clock_live_time_ns=2000, qualified_adc_live_time_ns=1980,
                                   total_live_adc_samples=100, qualified_live_adc_samples=99,
                                   excluded_intervals_ns=[[1200, 1220]])
        payload['triggers'][1:] = [measured(t, (300, 300)) for t in (100, 1000, 1940)]
        payload['counts'].update(qualified_triggers=4, additional_multi_strip_energies=3, qualified_energies=4)
        payload['spectra']['additional_multi_strip'].update(overflow=3, entries=3)
        payload['spectra']['combined'].update(overflow=3, entries=4)
        payload['receipt'] = dict(known_component_adc_sha256='1'*64, digital_profile_sha256=D.PROFILE_SHA256,
                                  digital_timing_sha256=D.TIMING_SHA256)
        path = self.root/G.report_ref('adc-window')
        W.write(path, payload)
        codes = np.arange(34*29, dtype=np.int16).reshape(1, 34, 29) - 500
        sidecar = path.with_name(G.TWO_STRIP_ADC_FILE)
        arrays = dict(report_sha256=W.sha(path), **payload['receipt'], contact_ids=list(range(1, 35)),
                      relative_time_ns=list(range(-80, 481, 20)), volts_per_code=D._LSB_V,
                      trigger_time_ns=[100., 1000., 1940.], two_strip_ordinal=[1], adc_codes=codes,
                      window_status=['captured', 'excluded_history', 'outside_live_time'])
        np.savez_compressed(sidecar, **arrays)
        query = dict(name='adc-window', report_sha256=W.sha(path), ordinal=1, contact_id=4)

        with patch.object(G, 'adc_window', side_effect=AssertionError('Archive read before request')):
            self.assertEqual(self.request('state?name=adc-window')[0], 200)
            self.assertEqual(self.request('two-strip?' + urlencode({k: v for k, v in query.items() if k != 'contact_id'}))[0], 200)
        adc_route = 'two-strip-adc?' + urlencode(query)
        self.assertEqual(self.request(adc_route, headers={'X-Control-Token': 'wrong'})[0], 403)
        self.assertEqual(self.request(adc_route + '&contact_id=2')[0], 400)
        for invalid in ({'file': G.TWO_STRIP_ADC_FILE}, {'contact_id': 17}, {'name': '../adc-window'},
                        {'report_sha256': '0'*64}, {'ordinal': 4}):
            self.assertEqual(self.request('two-strip-adc?' + urlencode({**query, **invalid}))[0], 400)
        self.assertEqual(self.request(adc_route), (200, {**query, 'trigger_time_ns': 100., 'status': 'captured',
                         'relative_time_ns': arrays['relative_time_ns'], 'preamp_V': (codes[0, 3]*D._LSB_V).tolist()}))
        for ordinal, expected in ((2, 'excluded_history'), (3, 'outside_live_time')):
            status, excluded = self.request('two-strip-adc?' + urlencode({**query, 'ordinal': ordinal}))
            self.assertEqual((status, excluded['status'], excluded['relative_time_ns'], excluded['preamp_V']), (200, expected, None, None))
        np.savez_compressed(sidecar, **{**arrays, 'known_component_adc_sha256': '2'*64})
        status, changed = self.request(adc_route)
        self.assertEqual((status, changed['status'], changed['preamp_V']), (200, 'unverified', None))

    def test_energy_selection_uses_exact_bounds_and_full_pixel_spectrum(self):
        _, options = self.request('options')
        report = fixture_report(options['libraries'], [18, 74], .05, 18)
        add_measured_features(report)
        path = self.root/G.report_ref('window')
        W.write(path, report)
        route = 'pixel-energy?' + urlencode(dict(name='window', report_sha256=W.sha(path),
                                                  min_kev=15, max_kev=18, x=2, y=16))
        status, view = self.request(route)
        self.assertEqual(status, 200)
        self.assertEqual(view['name'], 'window')
        self.assertEqual(view['selection'], dict(min_keV=15, max_keV=18, available_single_pixel_triggers=2,
                                               selected_single_pixel_triggers=1))
        self.assertEqual(view['pixel_map']['counts'][15][1], 1)
        detail = view['pixel_spectrum']
        self.assertEqual((detail['selected_entries'], detail['spectrum']['entries'], detail['spectrum']['counts']),
                         (1, 2, [2, 0]))
        empty = project_pixel_energy(report, (20, 40), (2, 16))
        self.assertEqual((empty['pixel_map']['status'], empty['pixel_spectrum']['spectrum']['entries']), ('empty', 2))
        self.assertEqual(self.request(route.replace('min_kev=15', 'min_kev=nan'))[0], 400)
        self.assertEqual(self.request(route, headers={'X-Control-Token': 'wrong'})[0], 403)
        bounds = report['spectra']['single_pixel']['bin_edges_keV']
        report['triggers'][0]['single_pixel_energy_keV'] = bounds[-1]
        detail = project_pixel_energy(report, (bounds[-1], bounds[-1]+1), (2, 16))['pixel_spectrum']
        self.assertEqual((detail['selected_entries'], detail['spectrum']['entries'], detail['spectrum']['overflow']),
                         (1, 2, 1))

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
