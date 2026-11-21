"""Checks for retained measured orders, peak mass and independent truth scoring."""

from contextlib import closing
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import zlib

import gegi_candidate_kinematics as kinematics
from test_gegi_continuous_plane import sample


class CandidateKinematicsTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.archive = self.root/'archive.sqlite'
        self.plane = self.root/'plane.json.gz'
        self.lines = [661.657, 1173.228, 1332.492]
        acquisition, fit = sample([
            ([[10, 26], [11, 27]], [417., 245.], [[0, 1], [1, 0]], [[-7., 7., 1.], [1., 14., 2.]]),
            ([[10, 27], [11, 26]], [407., 255.], [], None),
        ])
        trigger = acquisition['triggers'][1]
        pairs = trigger['two_strip_pairings']['pairings']
        pairs[1]['energy_compatible'] = False
        fit['candidates'][0]['pairings'][1]['energy_compatible'] = False
        for measured, fitted in zip(pairs, fit['candidates'][0]['pairings'], strict=True):
            fitted['compton_orders'] = measured['compton_orders']
            fitted['fit']['status'] = 'fitted' if measured['energy_compatible'] else 'energy_incompatible'
        fit['candidates'][0]['flags'] = []
        second = deepcopy(trigger)
        second['trigger_time_ns'] = 240.
        other_fit = deepcopy(fit['candidates'][0])
        other_fit.update(ordinal=2, time_ns=240.)
        other_fit['pairings'][0]['fit'] = {'status': 'no_center_template_for_pixel'}
        acquisition['triggers'].append(second)
        acquisition['counts'].update(qualified_triggers=3, qualified_energies=2)
        fit['candidates'].append(other_fit)
        fit['two_strip_triggers'] = 2
        self.ids = [11, 29]
        self.saved = kinematics.plane.reconstruct(acquisition, fit, z_mm=40., extent_mm=24., step_mm=4.)
        self.saved.update(fit_receipt=fit, candidate_analysis=dict(kind=kinematics.records.ANALYSIS_KIND,
                                                                  scope='all_two_strip_candidates',
                                                                  selected_original_trigger_ids=self.ids))
        with closing(sqlite3.connect(self.archive)) as db, db:
            db.execute('CREATE TABLE triggers (trigger_id INTEGER PRIMARY KEY, record BLOB, adc_sha256 TEXT, record_sha256 TEXT)')
            for tid, row, card in zip(self.ids, self.saved['triggers'], (trigger, second), strict=True):
                row.update(original_trigger_id=tid, diagnostic_input_group_ordinals=[100+tid])
                record = dict(trigger_id=tid, decision='candidate', trigger_time_ns=card['trigger_time_ns'],
                              identities=[100+tid], card=card)
                adc_sha = '2'*64
                db.execute('INSERT INTO triggers VALUES (?,?,?,?)',
                           (tid, zlib.compress(kinematics.workflow.encoded(record)), adc_sha,
                            kinematics.storage._record_digest(record, adc_sha)))
        self.saved['input_sha256'] = {'candidate_store': kinematics.workflow.sha(self.archive)}
        self.plane.write_bytes(gzip.compress(kinematics.workflow.encoded(self.saved)))

    def test_keeps_every_measured_pair_and_original_weight_without_adc_columns(self):
        result = kinematics.run(self.plane, self.archive, self.lines)
        original, unavailable = result['triggers']
        self.assertEqual([original['original_trigger_id'], unavailable['original_trigger_id']], self.ids)
        self.assertEqual(original['projected_mass'], 1.)
        self.assertEqual(unavailable['unresolved_mass'], 1.)
        for pair in (original, unavailable):
            coherent, incompatible = pair['pairings']
            self.assertEqual(kinematics.escape_lines(coherent), (1173.228, 1332.492))
            self.assertEqual(incompatible['measured_site_energies_keV'], [407., 255.])
            self.assertIsNone(incompatible['original_plane'])
            self.assertEqual(incompatible['kinematics']['status'], 'energy_incompatible')
            self.assertIsNone(coherent['kinematics']['unresolved_or_mixed']['direction'])
            self.assertEqual(coherent['kinematics']['incident_line_hypotheses'][0]['observed_sum_minus_incident_keV'],
                             662.-661.657)
        self.assertEqual([o['nominal_mass'] for o in original['pairings'][0]['original_plane']['orders']], [.5, .5])
        summary = result['windows']['661.657_keV']
        self.assertEqual(summary['original_order_status_counts'], {'projected': 2, 'no_waveform_fit': 2})
        self.assertEqual(summary['measured_pairings'], 4)
        self.assertEqual(summary['supplied_line_escape_counts'][1]['triggers_with_any_nominal_escape_order'], 2)
        self.assertIsNone(result['photon_origin_score'])

    def test_peak_partition_and_photon_join_do_not_change_kinematics(self):
        base = kinematics.run(self.plane, self.archive, self.lines)
        label = '661.657_keV'
        case = dict(peak={'mass': .3}, trigger_contributions=[
            dict(original_trigger_id=11, support={'peak_cell': .3, 'edge_cells': .7},
                 orders=[dict(pair_index=0, order=[0, 1], peak_cell=.1, edge_cells=.3),
                         dict(pair_index=0, order=[1, 0], peak_cell=.2, edge_cells=.4)]),
            dict(original_trigger_id=29, support={'peak_cell': 0., 'edge_cells': 0.}, orders=[]),
        ])
        attribution = dict(kind='gegi_five_second_candidate_peak_attribution_v1',
                           input_sha256=base['input_sha256'], windows={label: {'cases': {'24_mm_uniform-area': case}}})
        attribution_path = self.root/'attribution.json.gz'
        attribution_path.write_bytes(gzip.compress(kinematics.workflow.encoded(attribution)))
        scored_original = dict(original_trigger_id=11, measured_energy_keV=662., original_peak_cell_share=1.,
                               photon_truth={'emitted_gammas': [{'emitted_keV': 1173.23, 'ge_deposited_keV': 662.}],
                                             'ge_interactions_matched_to_births': [{}, {}]},
                               measured_pairings=[dict(pair_index=0, cells=[[10, 26], [11, 27]],
                                                       measured_site_energies_keV=[417., 245.],
                                                       nominal_first_two_distinct_cell_order=[1, 0],
                                                       nominal_order_survives_saved_projection=True)])
        origin_path = self.root/'origin.json'
        origin_path.write_bytes(kinematics.workflow.encoded(dict(
            kind='gegi_ten_cobalt_peak_trigger_origins_v1',
            science=dict(analysis_input_sha256=base['input_sha256']['saved_plane'],
                         attribution_sha256=kinematics.workflow.sha(attribution_path),
                         windows={label: {'triggers': [scored_original]}}))))
        result = kinematics.run(self.plane, self.archive, self.lines, attribution_path=attribution_path, origin_path=origin_path)
        self.assertEqual(result['triggers'], base['triggers'])
        support = result['windows'][label]['peak_support']
        self.assertEqual(len(support['order_contributions']), 2)
        self.assertAlmostEqual(sum(p['peak_cell_share'] for p in support['by_nominal_escape_lines']), 1.)
        scored = result['photon_origin_score']['triggers'][0]['pairings'][0]['line_scores'][1]
        self.assertEqual(scored['nominal_escape_in_truth_cell_order']['site_index_order'], (1, 0))
        self.assertTrue(scored['nominal_escape_in_truth_cell_order']['nominally_admissible'])
        case['trigger_contributions'][0]['orders'][0]['pair_index'] = 1
        with self.assertRaisesRegex(ValueError, 'pair/order identities'):
            kinematics.peak_support(base['triggers'], case)

    def test_archive_digest_mismatch_stops_before_pairing_analysis(self):
        path = self.root/'wrong.sqlite'
        path.write_bytes(hashlib.sha256(b'other archive').digest())
        with self.assertRaisesRegex(ValueError, 'archive SHA-256'):
            kinematics.run(self.plane, path, self.lines)


if __name__ == '__main__':
    unittest.main()
