"""Checks for archived IDs, conserved order support and truth-blind perturbations."""

from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import zlib

import gegi_candidate_diagnostic as D
from test_gegi_continuous_plane import sample


class CandidateDiagnosticTests(unittest.TestCase):
    def setUp(self):
        acquisition, fit = sample([
            ([[10, 26], [11, 27]], [417., 245.], [[0, 1], [1, 0]], [[-7., 7., 1.], [1., 14., 2.]]),
            ([[10, 27], [11, 26]], [407., 255.], [[0, 1], [1, 0]], None),
        ])
        trigger = acquisition['triggers'][1]
        for pair in trigger['two_strip_pairings']['pairings']:
            for site in pair['sites']:
                site['x_minus_y_energy_keV'] = 0.
        fit['calibration_bundle'] = {}
        fitted = fit['candidates'][0]
        fitted.update(window_status='captured', flags=[])
        fitted['pairings'][0]['fit']['status'] = 'fitted'
        fitted['pairings'][1]['fit']['status'] = 'no_center_template_for_pixel'

        # Three original triggers, all in the same measured window. Two share a time block.
        second = deepcopy(trigger)
        second['trigger_time_ns'] = 500.
        other_fit = deepcopy(fitted)
        other_fit.update(ordinal=2, time_ns=500.)
        other_fit['pairings'][0]['fit']['fits']['waveform']['center']['positions_mm'] = [[-7., 7., -4.], [1., 14., 4.]]
        last = deepcopy(second)
        last['trigger_time_ns'] = D.BLOCK_NS+60.
        last_fit = deepcopy(other_fit)
        last_fit.update(ordinal=3, time_ns=last['trigger_time_ns'])
        for pair in last_fit['pairings']:
            pair['fit'] = {'status': 'no_center_template_for_pixel'}
        acquisition['triggers'].extend((second, last))
        acquisition['counts'] = dict(qualified_triggers=4, qualified_energies=3)
        acquisition['exposure'] = dict(clock_live_time_ns=2*D.BLOCK_NS, qualified_adc_live_time_ns=2*D.BLOCK_NS-10.)
        fit['candidates'].extend((other_fit, last_fit))
        fit['two_strip_triggers'] = 3
        self.settings = dict(z_mm=40., extent_mm=24., step_mm=4.)
        self.acquisition, self.fit = acquisition, fit
        self.saved = json.loads(json.dumps(D.PLANE.reconstruct(acquisition, fit, **self.settings)))
        self.ids = [9, 21, 38]
        self.saved.update(fit_receipt=fit, candidate_analysis=dict(kind=D.I.KIND, scope='all_two_strip_candidates',
                                                                  selected_original_trigger_ids=self.ids))
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.archive = Path(temporary.name) / 'candidates.sqlite'
        with closing(sqlite3.connect(self.archive)) as db, db:
            db.execute('CREATE TABLE triggers (trigger_id INTEGER PRIMARY KEY, record BLOB, adc_sha256 TEXT, record_sha256 TEXT)')
            for tid, row, card in zip(self.ids, self.saved['triggers'], (trigger, second, last), strict=True):
                groups = [tid+100, tid+101]
                row.update(original_trigger_id=tid, diagnostic_input_group_ordinals=groups)
                record = dict(trigger_id=tid, decision='candidate', trigger_time_ns=card['trigger_time_ns'],
                              identities=groups, card=card)
                packed = zlib.compress(json.dumps(record).encode())
                adc_sha = '9'*64
                db.execute('INSERT INTO triggers VALUES (?, ?, ?, ?)',
                           (tid, packed, adc_sha, D.I.storage._record_digest(record, adc_sha)))

    def test_archive_join_preserves_exact_original_trigger_energies_and_geometry(self):
        events, rows = D.events_from_saved(self.saved, self.archive)
        self.assertEqual([event.identity for event in events], [(tid, 0) for tid in self.ids])
        self.assertEqual([r['input_group_ordinals'] for r in rows], [[109, 110], [121, 122], [138, 139]])
        self.assertEqual([r['two_strip_ordinal'] for r in rows], [1, 2, 3])
        self.assertEqual([e.energy_keV for e in events], [662.]*3)
        changed = deepcopy(self.saved)
        changed['triggers'][0]['pairings'][0]['orders'][0]['vertex_mm'][0] += .1
        with self.assertRaisesRegex(ValueError, 'Saved geometry differs'):
            D.events_from_saved(changed, self.archive)
        changed = deepcopy(self.saved)
        changed['triggers'][0]['diagnostic_input_group_ordinals'] = [1]
        with self.assertRaisesRegex(ValueError, 'differs from its archive record'):
            D.events_from_saved(changed, self.archive)

    def test_reprojection_and_leave_whole_trigger_out_for_both_priors(self):
        events, rows = D.events_from_saved(self.saved, self.archive)
        windows = '661.657_keV'
        for prior in D.PLANE.PLANE_PRIORS:
            baseline = D.PLANE.reconstruct(self.acquisition, self.fit, **self.settings, plane_prior=prior)
            args = dict(**self.settings, prior=prior, saved_extent_mm=24., source_mm=[-2., 6., 40.],
                        live_time_ns=2*D.BLOCK_NS, excluded_intervals=[[5., 15.]])
            result = D.evaluate(events, rows, D.J.ResponseSettings(), **args, original_layer=baseline['layers'][windows])
            retained = D.evaluate(events[1:], rows[1:], D.J.ResponseSettings(), **args)
            first, _, unresolved = result['trigger_contributions']
            self.assertEqual([(o['pair_index'], o['order']) for o in first['orders']], [(0, (0, 1)), (0, (1, 0))])
            self.assertAlmostEqual(result['census']['projected_mass'], 1.)
            self.assertAlmostEqual(result['census']['unresolved_mass'], 2.)
            self.assertLessEqual(result['reproduction_maximum_absolute_pixel_error'], D.MASS_ATOL)
            self.assertEqual(first['without_trigger']['peak']['position_mm'], retained['peak']['position_mm'])
            self.assertAlmostEqual(first['without_trigger']['peak']['mass'], retained['peak']['mass'])
            self.assertEqual(unresolved['without_trigger']['peak'], result['peak'])
            self.assertEqual([b['selected_trigger_ids'] for b in result['time_blocks']], [[9, 21], [38]])
            self.assertEqual(result['time_blocks'][0]['qualified_adc_live_time_ns'], D.BLOCK_NS-10.)
            self.assertIsNone(result['time_blocks'][0]['without_block']['peak'])

    def test_source_position_changes_scores_only(self):
        events, rows = D.events_from_saved(self.saved, self.archive)
        args = dict(**self.settings, prior='uniform-area', saved_extent_mm=24., live_time_ns=2*D.BLOCK_NS,
                    excluded_intervals=[])
        a = D.evaluate(events, rows, D.J.ResponseSettings(), **args, source_mm=[-2., 6., 40.])
        b = D.evaluate(events, rows, D.J.ResponseSettings(), **args, source_mm=[0., -40., 40.])
        self.assertNotEqual(a['source_score'], b['source_score'])
        for key in ('census', 'peak', 'blind_peaks', 'trigger_concentration'):
            self.assertEqual(a[key], b[key])
        for ra, rb in zip(a['trigger_contributions'], b['trigger_contributions'], strict=True):
            self.assertEqual(ra['without_trigger']['peak'], rb['without_trigger']['peak'])

    def test_runtime_peak_preview_closes_and_serializes(self):
        preview = D.record_support.peak_cell_contributors(self.saved, self.archive, '661.657_keV')
        self.assertEqual(set(item['original_trigger_id'] for item in preview['contributors']), {9, 21})
        self.assertAlmostEqual(sum(item['peak_cell_share'] for item in preview['contributors']), 1.)
        for item in preview['contributors']:
            self.assertAlmostEqual(sum(o['peak_cell_mass'] for pair in item['pairings'] for o in pair['orders']),
                                   item['peak_cell_mass'])
        self.assertIsInstance(json.loads(json.dumps(preview, allow_nan=False))['peak']['on_image_edge'], bool)
        self.assertEqual(D.record_support.peak_cell_contributors(self.saved, self.archive, '1173.23_keV'),
                         dict(peak=None, contributors=[]))


if __name__ == '__main__':
    unittest.main()
