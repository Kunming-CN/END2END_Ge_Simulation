"""Synthetic fixed-cone and sealed-scalar tests; no radiation/native execution."""
import copy
import io
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import gegi_campaign_analysis as A
import gegi_event_store as S
import gegi_imaging as I

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = ROOT/'.local/gegi-analysis-tests'


def cone(event_id=3, weight=1.):
    return {'event_id': event_id, 'vertex_mm': [0., 0., 0.], 'axis': [0., 0., 1.],
            'half_angle_deg': 60., 'weight': weight, 'order': [0, 1], 'pairing_index': 0}


def event(primary=3, pulse=0, failed=False):
    channels = [{'contact_id': i, 'accepted': True, 'reconstructed_energy_keV': 1.,
                 'derived_trace_sha256': 'd'*64} for i in range(1, 35)]
    references = {str(i): {'time_ns': {'sha256': 'e'*64, 'count': 2},
                          'signed_induced_keV': {'sha256': 'f'*64, 'count': 2}} for i in range(1, 35)}
    return {'event_id': primary, 'group_id': pulse, 'status': 'native_failed' if failed else 'completed',
            'channels': None if failed else channels, 'native_signals': None if failed else references,
            'error': 'retained synthetic failure' if failed else None,
            'calibration_sha256': 'a'*64, 'photopeak_windows_sha256': 'b'*64, 'readout_recipe_sha256': 'c'*64,
            'truth_edep_keV': 9999., 'readout_summary': {'accepted': not failed, 'energy_keV': None if failed else 662.,
                                                       'reason': 'native_failed' if failed else None},
            'reconstruction': {'event_id': primary, 'status': 'rejected' if failed else 'accepted',
                'reason': 'native_response_incomplete' if failed else None, 'ordering_ambiguous': False,
                'pairing_ambiguous': False, 'cones': [] if failed else [cone(primary)]}}


def identity(count=10):
    return {'source_group': 'left', 'chunk_index': 0, 'batch': {'primary_count': count, 'global_initial_offset': 100},
            'campaign_initial_offset': 500, 'raw_initial_id_base': 0,
            'calibration_sha256': 'a'*64, 'photopeak_windows_sha256': 'b'*64}


def counts(initial=10, failed=False):
    result = {name: 0 for name in A.COUNT_FIELDS}
    result.update(initial_primaries=initial, zero_deposit_primaries=initial-1, nonzero_primaries=1,
                  pulse_groups=2 if failed else 1, readout_accepted_groups=1, imaging_accepted_groups=1,
                  readout_accepted_primaries=1, imaging_accepted_primaries=1)
    if failed:
        result.update(native_failed_groups=1, native_failed_primaries=1, readout_rejected_groups=1,
                      readout_rejected_primaries=1, imaging_rejected_groups=1, imaging_rejected_primaries=1)
    return result


def group(name='left', x=-40, initial=10):
    return {'id': name, 'source': 'gegi_mono_gamma_v1', 'source_position_mm': [x, 0., 40.],
            'primary_count': initial, 'count_unit': 'emitted gamma'}


class FixedMetrics(unittest.TestCase):
    def test_frozen_criteria_and_exact_isotope_windows(self):
        c = A.criteria()
        self.assertEqual(c['kernel_sigma_deg'], I.KERNEL_SIGMA_DEG)
        self.assertEqual(c['minimum_accepted_groups_per_component'], 20)
        self.assertEqual(c['direction_localization_tolerance_deg'], 15.)
        self.assertEqual(c['plane_localization_tolerance_mm'], 15.)
        self.assertEqual([w['line_energy_keV'] for w in c['isotope_windows']], [661.657, 1173.228, 1332.492])
        self.assertFalse(c['bootstrap']['automatic'])

    def test_vertex_plane_kernel_matches_existing_publication(self):
        from gegi_publication import planar_backproject
        cones = [cone(weight=.5), dict(cone(weight=.5), vertex_mm=[4., -3., 2.])]
        expected = planar_backproject(cones, 40.)
        actual = A.plane_backproject(cones, ticks=expected['x_mm'], step_mm=2.5)
        self.assertLess(max(abs(a-b) for ra, rb in zip(actual['values'], expected['values']) for a, b in zip(ra, rb)), 1e-14)
        campaign = A.plane_backproject(cones)
        self.assertEqual((len(campaign['x_mm']), campaign['x_mm'][0], campaign['x_mm'][-1]), (120, -119., 119.))
        self.assertAlmostEqual(sum(map(sum, campaign['values']))*4, 1., places=12)

    def test_unequal_or_missing_candidate_weights_are_rejected(self):
        A.validate_cones([cone(weight=.5), cone(weight=.5)])
        with self.assertRaises(ValueError): A.validate_cones([cone(weight=.2), cone(weight=.8)])
        with self.assertRaises(ValueError): A.validate_cones([])

    @staticmethod
    def two_peak_plane():
        ticks = [-60., -40., -20., 0., 20., 40., 60.]
        values = [[0. for _ in ticks] for _ in ticks]
        values[3][1] = 2.; values[3][5] = 1.
        return {'x_mm': ticks, 'y_mm': ticks, 'plane_z_mm': 40., 'values': values}

    def test_resolution_and_truth_matching_are_separate_and_fixed(self):
        image = self.two_peak_plane()
        good = A.evaluate(image, [[-40, 0, 40], [40, 0, 40]], [20, 20], 'plane')
        self.assertEqual(good['status'], 'pass'); self.assertTrue(good['source_separation_demonstrated'])
        wrong = A.evaluate(image, [[-5, 40, 40], [5, 40, 40]], [20, 20], 'plane')
        self.assertEqual(good['peaks'], wrong['peaks'])
        self.assertEqual(wrong['two_peak_resolution_status'], 'pass')
        self.assertFalse(wrong['localization_within_declared_tolerance'])
        self.assertEqual(wrong['status'], 'fail')
        low = A.evaluate(image, [[-40, 0, 40], [40, 0, 40]], [19, 20], 'plane')
        self.assertEqual(low['status'], 'inconclusive'); self.assertIsNone(low['source_separation_demonstrated'])

    def test_valley_rejection_and_equal_plateau_merging(self):
        image = self.two_peak_plane()
        image['values'][3][2:5] = [.9, .9, .9]
        result = A.evaluate(image, [[-40, 0, 40], [40, 0, 40]], [20, 20], 'plane')
        self.assertEqual(result['two_peak_resolution_status'], 'fail')
        sky = {'azimuth_deg': [-180., -90., 0., 90.], 'elevation_deg': [-45., 0., 45.],
               'values': [[0., 0., 0., 0.], [1., 0., 0., 1.], [0., 0., 0., 0.]]}
        peaks = A.local_peaks(sky, 'direction')
        self.assertEqual(len(peaks), 1); self.assertEqual(peaks[0]['plateau_cells'], 2)

    def test_null_failures_sparse_ids_stage_overlap_and_fixed_gain_spectrum(self):
        acc = A.Accumulator([group()]); ledger = io.BytesIO()
        good, bad = event(), event(pulse=1, failed=True)
        with mock.patch.object(I, 'reconstruct_event', side_effect=AssertionError('Analysis must not reconstruct')):
            acc.consume('left', [(3, 0, good), (3, 1, bad)], declared_counts=counts(failed=True), identity=identity(),
                        store_ref='chunks/left/b000000/events.sqlite', store_sha256='0'*64, ledger=ledger)
        groups, maps = acc.results(); g = groups['left']
        self.assertEqual(g['counts']['initial_primaries'], 10); self.assertEqual(g['counts']['zero_deposit_primaries'], 9)
        self.assertEqual(g['counts']['readout_accepted_primaries'], 1)
        self.assertEqual(g['counts']['readout_rejected_primaries'], 1)
        self.assertEqual(g['unknown_readout_energy_groups'], 1)
        self.assertEqual(g['native_error_counts'], {'retained synthetic failure': 1})
        self.assertEqual(g['exclusive_stage_counts']['native_failed'], 1)
        self.assertEqual(g['exclusive_stage_counts']['readout_rejected_after_native_completion'], 0)
        self.assertEqual(g['spectrum']['counts'][331], 1); self.assertEqual(g['spectrum']['overflow'], 0)
        self.assertIsNone(bad['readout_summary']['energy_keV']); self.assertIsNone(bad['channels'])
        stored = json.loads(ledger.getvalue()); self.assertEqual(stored['raw_primary_id'], 3)
        self.assertEqual(stored['source_global_initial_id'], 103); self.assertEqual(stored['campaign_initial_id'], 503)
        self.assertEqual(g['line_counts']['661.657']['readout_selected_groups'], 1)
        self.assertEqual(len(g['representative']['channels']), 34)

    def test_exact_errors_and_exclusive_stages_do_not_double_count_upstream_failures(self):
        records = [event(primary=i, failed=i < 2) for i in range(6)]
        records[0]['error'] = 'ArgumentError: first saved error'
        records[1]['error'] = 'ArgumentError: first saved error\n  exact retained detail'
        for i in (2, 3, 4):
            records[i]['reconstruction'].update(status='rejected', reason='saved imaging rejection', cones=[])
        records[2]['status'] = 'step_limit'
        for i in (2, 3):
            records[i]['readout_summary'].update(accepted=False, energy_keV=None,
                reason='native_response_incomplete' if i == 2 else 'collecting_channel_readout_rejected')
        declared = counts()
        declared.update(zero_deposit_primaries=4, nonzero_primaries=6, pulse_groups=6,
            native_failed_groups=2, native_failed_primaries=2, native_flagged_groups=1, native_flagged_primaries=1,
            readout_accepted_groups=2, readout_accepted_primaries=2, readout_rejected_groups=4,
            readout_rejected_primaries=4, imaging_accepted_groups=1, imaging_accepted_primaries=1,
            imaging_rejected_groups=5, imaging_rejected_primaries=5)
        acc = A.Accumulator([group()])
        acc.consume('left', [(e['event_id'], 0, e) for e in records], declared_counts=declared, identity=identity(),
                    store_ref='chunks/left/b000000/events.sqlite', store_sha256='0'*64)
        result = acc.results()[0]['left']
        self.assertEqual(result['native_error_counts'], {records[i]['error']: 1 for i in (0, 1)})
        self.assertEqual(result['exclusive_stage_counts'], {'native_failed': 2, 'native_flagged': 1,
            'readout_rejected_after_native_completion': 1, 'imaging_rejected_after_readout_acceptance': 1,
            'imaging_accepted': 1})
        self.assertEqual(sum(result['readout_rejection_reasons'].values()), 4)
        self.assertEqual(sum(result['rejection_reasons'].values()), 5)
        self.assertEqual(result['spectrum']['selected_readout_groups'], 2)

    def test_native_failure_without_exact_saved_error_is_rejected(self):
        for error in (None, '', '   ', 123):
            with self.subTest(error=error), self.assertRaisesRegex(ValueError, 'exact saved error'):
                A.outcome(dict(event(failed=True), error=error))

    def test_mixture_retains_acceptance_yields_not_unit_area(self):
        groups, maps = {}, {}
        for key, accepted in (('a', 20), ('b', 40)):
            groups[key] = {'source': 'gegi_mono_gamma_v1', 'count_unit': 'emitted gamma',
                'initial_primary_denominator': 100, 'truth_position_mm_for_evaluation_only': [-40 if key == 'a' else 40, 0, 40],
                'counts': {'imaging_accepted_groups': accepted}}
            base = A.blank_maps(); base['direction']['values'][18][36] = accepted/base['direction']['solid_angle_per_cell_sr_by_row'][18]
            base['plane']['values'][60][60] = accepted/4
            maps[key] = {window: copy.deepcopy(base) for window in ('all', *(A.line_key(e) for e in A.LINES))}
        result, mixed = A.mixtures(groups, maps)
        plane = mixed['a__b']['all']['plane']
        self.assertAlmostEqual(sum(map(sum, plane['values']))*4, .3)
        self.assertEqual([d['map_scale'] for d in result['a__b']['initial_denominators']], [.005, .005])

    def test_energy_windows_keep_cross_isotope_contributors(self):
        components = [dict(group('cs'), source='cs137_point_decay_v1', count_unit='initial isotope decay'),
                      dict(group('co', x=40), source='co60_point_decay_v1', count_unit='initial isotope decay')]
        acc = A.Accumulator(components)
        for component in components:
            ident = dict(identity(), source_group=component['id'])
            acc.consume(component['id'], [(3, 0, event())], declared_counts=counts(), identity=ident,
                        store_ref='chunks/'+component['id']+'/b000000/events.sqlite', store_sha256='0'*64)
        groups, maps = acc.results(); result, mixed = A.mixtures(groups, maps)
        for source in ('cs', 'co'):
            self.assertEqual(groups[source]['line_counts']['661.657']['imaging_accepted_groups'], 1)
            self.assertEqual(groups[source]['line_counts']['1173.228']['imaging_accepted_groups'], 0)
        # Both sources have observed 662-keV energy: Co continuum is retained in the Cs window.
        self.assertAlmostEqual(sum(map(sum, mixed['cs__co']['661.657']['plane']['values']))*4, .1)
        self.assertEqual(result['cs__co']['family'], 'initial_decay')

    def test_representative_is_first_unambiguous_in_original_order(self):
        acc = A.Accumulator([group()])
        records = [event(primary=i) for i in (1, 3, 5)]
        records[0]['reconstruction']['ordering_ambiguous'] = True
        declared = counts()
        declared.update(zero_deposit_primaries=7, nonzero_primaries=3, pulse_groups=3,
                        readout_accepted_groups=3, imaging_accepted_groups=3,
                        readout_accepted_primaries=3, imaging_accepted_primaries=3)
        acc.consume('left', [(e['event_id'], 0, e) for e in records], declared_counts=declared, identity=identity(),
                    store_ref='chunks/left/b000000/events.sqlite', store_sha256='0'*64)
        representative = acc.results()[0]['left']['representative']
        self.assertEqual(representative['raw_primary_id'], 3)
        self.assertTrue(representative['unambiguous'])
        self.assertEqual(len(representative['channels']), 34)


class SealedStreaming(unittest.TestCase):
    def setUp(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=SCRATCH); self.folder = Path(self.temp.name)

    def tearDown(self): self.temp.cleanup()

    def fixture(self, failed=False, source_pin_overrides=None):
        import gegi_campaign as C
        import workflow_batches as B
        campaign = self.folder/'campaign'; campaign.mkdir()
        plan = C.draft(); g = plan['groups'][0]; g.update(primary_count=10, partition=B.partition(10, g['master_seed']))
        plan.update(groups=[g], total_initial_primaries=10, status='frozen', source_sha256=C.source_pins(ROOT),
                    transport_context={'runtime': {}, 'decay_data': {}, 'emlow_sha256': '7'*64},
                    native_request={'ref': '.local/synthetic-request.json', 'sha256': '9'*64},
                    calibration={'ref': '.local/synthetic-calibration.json', 'sha256': 'a'*64},
                    resource_budget={'projected_retained_bytes': 1, 'max_chunk_temporary_bytes': 1,
                                     'reserve_bytes': 20*1024**3,
                                     'evidence': {'ref': '.local/synthetic-acceptance.json', 'sha256': '8'*64}},
                    acceptance={'ref': '.local/synthetic-acceptance.json', 'sha256': '8'*64})
        plan['source_sha256'].update(source_pin_overrides or {})
        plan['physics_sha256'] = C.physics_sha256(plan)
        (campaign/'plan.json').write_bytes(A.encoded(plan))
        (campaign/'FROZEN.json').write_bytes(A.encoded({'kind': C.KIND, 'plan_sha256': A.sha(campaign/'plan.json'), 'physics_sha256': plan['physics_sha256']}))
        chunk = next(C.chunks(plan)); folder = C.chunk_path(campaign, chunk); folder.mkdir(parents=True)
        ident = C.chunk_identity(campaign, plan, chunk); saved = event()
        saved['photopeak_windows_sha256'] = ident['photopeak_windows_sha256']
        for channel in saved['channels']: channel['trace'] = {'time_ns': [0., 1.], 'value': [0., 1.]}
        signals = {i: {'time_ns': [0., 1.], 'signed_induced_keV': [0., 1.]} for i in range(1, 35)}
        terminal = 'completed_with_native_failures' if failed else 'completed'
        response = {'kind': C.RESPONSE_KIND, 'status': terminal, 'counts': counts(failed=failed),
            'store_identity_sha256': S.sha(S.encoded(ident)), 'calibration_sha256': ident['calibration_sha256'],
            'photopeak_windows_sha256': ident['photopeak_windows_sha256'], 'readout_recipe_sha256': 'c'*64}
        store = S.Store(folder/'events.sqlite', ident, create=True)
        store.append(3, 0, saved, signals, '1'*64)
        if failed:
            unknown = event(primary=3, pulse=1, failed=True)
            unknown['photopeak_windows_sha256'] = ident['photopeak_windows_sha256']
            store.append(3, 1, unknown, None, '2'*64)
        store.seal(response); store.close()
        (folder/'response.json').write_bytes(A.encoded(response))
        done = {'kind': C.DONE_KIND, 'identity': ident, 'response': response,
                'artifacts': {name: {'sha256': A.sha(folder/name), 'bytes': (folder/name).stat().st_size}
                              for name in ('events.sqlite', 'response.json')}}
        (folder/'DONE.json').write_bytes(A.encoded(done))
        (campaign/'COMPLETE.json').write_bytes(A.encoded({'kind': C.KIND, 'status': terminal, 'plan_sha256': A.sha(campaign/'plan.json'),
            'initial_primaries': 10, 'groups': {g['id']: counts(failed=failed)},
            'physics_sha256': plan['physics_sha256'], 'chunks': {'0': A.sha(folder/'DONE.json')}}))
        return campaign, folder, plan

    def test_completed_with_native_failure_retains_unknown_energy_and_denominator(self):
        campaign, folder, _ = self.fixture(failed=True)
        original = A.sha(folder/'events.sqlite')
        result = A.analyze(campaign, self.folder/'analysis', root=ROOT)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['processed_initial_records'], 10)
        group_result = result['groups']['gamma-left']
        self.assertEqual(group_result['counts']['native_failed_groups'], 1)
        self.assertEqual(group_result['counts']['nonzero_primaries'], 1)
        self.assertEqual(group_result['unknown_readout_energy_groups'], 1)
        self.assertEqual(group_result['native_error_counts'], {'retained synthetic failure': 1})
        self.assertEqual(group_result['exclusive_stage_counts']['native_failed'], 1)
        self.assertEqual(group_result['exclusive_stage_counts']['imaging_accepted'], 1)
        self.assertEqual(A.sha(folder/'events.sqlite'), original)

    def test_full_sealed_scalar_path_never_loads_arrays_or_reconstructs(self):
        campaign, folder, _ = self.fixture(); old = A.sha(folder/'events.sqlite')
        with mock.patch.object(S, 'unpack_array', side_effect=AssertionError('No waveform decompression')), \
             mock.patch.object(I, 'reconstruct_event', side_effect=AssertionError('No reconstruction')), \
             mock.patch.object(A, 'bootstrap_peaks', side_effect=AssertionError('No automatic bootstrap')):
            result = A.analyze(campaign, self.folder/'analysis', root=ROOT)
        self.assertEqual(result['status'], 'complete'); self.assertEqual(result['processed_initial_records'], 10)
        self.assertEqual(result['initial_denominators_by_unit'], {'emitted gamma': 10})
        self.assertEqual(A.sha(folder/'events.sqlite'), old)
        manifest = A.read(self.folder/'analysis/manifest.json')
        self.assertEqual(set(manifest['files']), {'summary.json', 'maps.json', 'cones.jsonl'})
        self.assertEqual(manifest['radiation_calls'], 0)
        self.assertEqual(manifest['analysis_revision'], result['analysis_revision'])
        self.assertFalse(result['analysis_revision']['allowed'])
        self.assertFalse(result['analysis_revision']['applied'])

    def test_analysis_revision_requires_explicit_opt_in_and_records_exact_hashes(self):
        campaign, folder, _ = self.fixture(source_pin_overrides={A.ANALYSIS_REF: '0'*64})
        originals = {p: (A.sha(p), p.stat().st_mtime_ns) for p in
                     (campaign/'plan.json', campaign/'FROZEN.json', campaign/'COMPLETE.json', folder/'DONE.json', folder/'events.sqlite')}
        output = self.folder/'analysis'
        with self.assertRaisesRegex(ValueError, 'explicit --allow-analysis-revision'):
            A.analyze(campaign, output, root=ROOT)
        self.assertFalse(output.exists())
        result = A.analyze(campaign, output, root=ROOT, allow_analysis_revision=True)
        revision = result['analysis_revision']
        self.assertTrue(revision['allowed']); self.assertTrue(revision['applied'])
        self.assertEqual(revision['original_analysis_sha256'], '0'*64)
        self.assertEqual(revision['current_analysis_sha256'], A.sha(ROOT/A.ANALYSIS_REF))
        self.assertEqual(A.read(output/'manifest.json')['analysis_revision'], revision)
        self.assertEqual(originals, {p: (A.sha(p), p.stat().st_mtime_ns) for p in originals})

    def test_revision_does_not_admit_any_producer_or_criteria_change(self):
        _, _, plan = self.fixture(source_pin_overrides={A.ANALYSIS_REF: '0'*64})
        for ref in ('tools/gegi_imaging.py', 'tools/gegi_event_store.py', 'transport/gegi_geometry.py'):
            changed = copy.deepcopy(plan); changed['source_sha256'][ref] = '1'*64
            with self.subTest(ref=ref), self.assertRaisesRegex(ValueError, 'Frozen producer source changed'):
                A.validate_analysis_revision(changed, root=ROOT, allow_analysis_revision=True)
        changed = copy.deepcopy(plan); changed['analysis_criteria']['kernel_sigma_deg'] = 6.
        with self.assertRaisesRegex(ValueError, 'criteria changed'):
            A.validate_analysis_revision(changed, root=ROOT, allow_analysis_revision=True)
        with self.assertRaisesRegex(ValueError, 'must be boolean'):
            A.validate_analysis_revision(plan, root=ROOT, allow_analysis_revision='yes')

    def test_unsealed_or_tampered_scalar_data_fail_closed(self):
        campaign, folder, plan = self.fixture()
        database = folder/'events.sqlite'; database.write_bytes(database.read_bytes()+b'changed')
        with self.assertRaises(ValueError): list(A.sealed_chunks(campaign, plan))

    def test_optional_bootstrap_failure_preserves_checked_main_outputs(self):
        campaign, _, _ = self.fixture()
        with mock.patch.object(A, 'bootstrap_peaks', side_effect=ValueError('explicit budget exhausted')):
            summary = A.analyze(campaign, self.folder/'analysis', root=ROOT, bootstrap=True,
                                bootstrap_cost_receipt=self.folder/'requested-cost.json', bootstrap_budget_seconds=1.)
        self.assertEqual(summary['status'], 'complete')
        self.assertEqual(summary['bootstrap']['status'], 'failed')
        self.assertIsNone(summary['bootstrap']['result'])
        manifest = A.read(self.folder/'analysis/manifest.json')
        self.assertEqual(manifest['files']['summary.json']['sha256'], A.sha(self.folder/'analysis/summary.json'))

    def test_immutable_store_refuses_writes_and_checks_identity(self):
        import sqlite3
        campaign, folder, plan = self.fixture()
        done = A.read(folder/'DONE.json')
        with A.scalar_store(folder/'events.sqlite', done['identity'], done['response']) as store:
            with self.assertRaises(sqlite3.OperationalError): store.db.execute('DELETE FROM events')
        with self.assertRaises(ValueError):
            with A.scalar_store(folder/'events.sqlite', {}, done['response']): pass


if __name__ == '__main__': unittest.main()
