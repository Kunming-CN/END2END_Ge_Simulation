import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

import gegi_candidate_observed_energy as candidate
import gegi_photon_continuation as photon


class CandidateObservedEnergyTests(unittest.TestCase):
    def setUp(self):
        self.crystal = (np.vstack((np.eye(3), -np.eye(3))), np.full(6, 10.))
        self.original_order = dict(order=[0, 1], nominal_mass=.5, status='available')
        self.row = dict(original_trigger_id=7, trigger_time_ns=120., energy_keV=663.,
                        archive_record_sha256='record', archive_adc_sha256='adc', projected_mass=.5, unresolved_mass=.5,
                        conditional_escape_pairings=[
                            dict(pair_index=0, cells=[[1, 3], [2, 4]], saved_waveform_positions_mm=[[0., 0., 0.], [2., 0., 0.]],
                                 saved_waveform_position_model='center', original_plane_pairing=dict(
                                     site_energies_keV=[250., 413.], nominal_mass=1., orders=[self.original_order])),
                            dict(pair_index=1, cells=[[1, 4], [2, 3]], saved_waveform_positions_mm=None,
                                 saved_waveform_position_model=None, original_plane_pairing=None)])

    def test_original_identity_and_unavailable_slot_survive(self):
        row = candidate.measured_branches(self.row, [300., 662.], self.crystal)
        compatible, incompatible = row['pairs']
        first, reverse = compatible['orders']
        self.assertEqual(first['original_absorption_order'], self.original_order)
        self.assertIsNone(reverse['original_absorption_order'])
        self.assertEqual(row['original_projected_mass'] + row['original_unresolved_mass'], 1.)
        self.assertEqual(row['original_measured_trigger_energy_keV'], 663.)
        self.assertEqual(row['physical_topology_status'], 'unidentified_by_two_site_response')
        self.assertEqual(first['lines'][0]['status'], 'fixed_first_scatter_inadmissible')
        self.assertEqual(first['lines'][1]['status'], 'prepared_conditional_state')
        self.assertEqual(reverse['lines'][1]['status'], 'prepared_conditional_state')
        self.assertTrue(all(line['status'] == 'original_strip_pairing_incompatible'
                            for order in incompatible['orders'] for line in order['lines']))

    def test_observed_energy_above_both_true_supports_retains_gaussian_tails(self):
        row = candidate.measured_branches(self.row, [662.], self.crystal)
        plan = dict(kind='gegi_measured_second_site_response_plan_v1', rate_basis={}, measured_triggers=[row],
                    explicit_nominal_sigma_keV=20., input_sha256={}, incident_lines_keV=[662.], scoped_cohorts={})
        rates = {e:photon.PhotonRates(.15,.025,.1) for e in (100., 249., 412.)}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'plan.json'
            path.write_text(json.dumps(plan), encoding='utf-8')
            with patch.object(candidate,'base_tables',return_value=(rates,.1,{})), patch.object(
                    photon,'ge_halfspaces_from_gdml',return_value=self.crystal):
                result = candidate.evaluate(path, Path(folder), None, azimuth_samples=16, energy_order=64)
        self.assertEqual(result['state_counts'], {'conditional_factors_computed':2, 'original_strip_pairing_incompatible':2})
        state = result['measured_triggers'][0]['pairs'][0]['orders'][0]['lines'][0]
        factors = state['measured_energy_factors']
        obs, = factors['observations']
        self.assertEqual(obs['observed_keV'], 413.)
        self.assertGreater(obs['observed_keV'], factors['true_absorption_endpoint_keV'])
        self.assertGreater(obs['observed_keV'], factors['true_escape_deposit_support_keV'][1])
        self.assertGreater(obs['escape_per_mm_observed_keV'], 0.)
        expected = math.exp(-.15*2)*.025*math.exp(-.5*(1/20)**2)/(math.sqrt(2*math.pi)*20)
        self.assertAlmostEqual(obs['absorption_per_mm_observed_keV'], expected, places=14)

    def test_queries_reuse_exact_anchors_and_bound_log_grid(self):
        row = candidate.measured_branches(self.row, [662.], self.crystal)
        existing = {100.:None, 200.:None, 249.:None, 412.:None, 600.:None}
        result = candidate.coefficient_request([row], existing, .1)
        self.assertEqual(result['initialized_anchors_needed_keV'], [])
        self.assertFalse(set(result['new_query_energies_keV']) & existing.keys())
        lo, hi = result['continuum_bounds_keV']
        relevant = sorted(set(result['new_query_energies_keV']) | {e for e in existing if lo <= e <= hi})
        self.assertEqual([relevant[0],relevant[-1]], [lo,hi])
        self.assertLessEqual(max(math.log(b/a) for a,b in zip(relevant[:-1],relevant[1:],strict=True)), .1)


if __name__ == '__main__':
    unittest.main()
