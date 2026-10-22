"""Targeted contracts for the saved-signal inverse model; no physics execution."""
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import zlib
import numpy as np
import gegi_event_store as S
import gegi_signal_reconstruction as G
import gegi_order_prior_preservation as P


class Bank:
    sha256 = 'independent-test-bank'
    def templates(self, x, y, grid):
        return np.array([[self.shape(grid, z, 1), self.shape(grid, z, -1)] for z in range(-5, 6)])
    @staticmethod
    def shape(grid, z, face):
        return np.clip((grid-(45+face*z*6))/20, 0, 1)
    def calibrate_discrepancy(self):
        return {'normalized_rms': .001, 'depth_error_mm': .25, 'diagnostic_count': 1}


def fixture(sites):
    grid = np.arange(151.)
    waves = {}
    totals = {}
    for x, y, e, z in sites:
        for cid, wiring in ((x, 1), (y, -1)):
            waves[cid] = waves.get(cid, np.zeros(len(grid))) + e*Bank.shape(grid, z, wiring)*wiring
            totals[cid] = totals.get(cid, 0) + e
    channels = [{'id': cid, 'wiring_factor': 1 if cid <= 17 else -1,
                 'strip_center_mm': (cid-(8.5 if cid <= 17 else 25.5))*G.I.PITCH_MM}
                for cid in sorted(waves)]
    native = {cid: {'time_ns': grid.tolist(), 'signed_induced_keV': w.tolist()} for cid, w in waves.items()}
    event = {'event_id': 7, 'group_id': 2, 'status': 'completed', 'channels': []}
    for c in channels:
        cid = c['id']; e = totals[cid]
        event['channels'].append({'contact_id': cid, 'accepted': True, 'collection_candidate': True,
            'final_induced_keV': e*c['wiring_factor'], 'reconstructed_energy_keV': e,
            'saturated': False, 'charge_clipped_at_window': False})
    return event, native, channels


class ReconstructionTests(unittest.TestCase):
    def _order_prior_result(self, energies, *, rank_deficient=0):
        event, native, channels = fixture([(4, 21, sum(energies), -2)])
        sites = [{'position_mm': [10.*i, 0., 0.], 'energy_keV': energy,
                  'position_covariance_mm2': np.diag([10., 10., 10.]).tolist(),
                  'energy_sigma_keV': None} for i, energy in enumerate(energies)]
        flow = [(4, 21+i, energy) for i, energy in enumerate(energies)]
        with patch.object(G, 'energy_flows', return_value=([flow], {'rank_deficient_supports': rank_deficient})), \
                patch.object(G, '_fit_flow', return_value={'status': 'conditional_fit', 'sites': sites}):
            return G.reconstruct_event(event, native, channels, Bank())

    def _assert_order_prior_conservation(self, out):
        self.assertAlmostEqual(sum(c['prior_weight'] for c in out['candidates'])+
                               out['unsupported_hypothesis_mass'], 1.)
        self.assertTrue(all(c['weight'] == c['prior_weight'] for c in out['candidates']))
        expected = G.sequence_candidates(out['hypotheses'][0]['sites'])
        extra = {'hypothesis_index', 'prior_weight', 'weight', 'uncertainty_scope'}
        self.assertEqual([{k: v for k, v in c.items() if k not in extra} for c in out['candidates']], expected)

    def test_order_prior_two_valid_orders_unchanged(self):
        out = self._order_prior_result([200., 462.])
        self.assertEqual([c['prior_weight'] for c in out['candidates']], [.5, .5])
        self.assertEqual(out['unsupported_hypothesis_mass'], 0.)
        self._assert_order_prior_conservation(out)

    def test_order_prior_single_valid_order_keeps_other_half_unresolved(self):
        out = self._order_prior_result([507.351, 153.809])
        self.assertEqual([c['order'] for c in out['candidates']], [[1, 0]])
        self.assertEqual(out['candidates'][0]['prior_weight'], .5)
        self.assertEqual(out['unsupported_hypothesis_mass'], .5)
        self._assert_order_prior_conservation(out)

    def test_order_prior_all_site_permutations_precede_screening(self):
        for energies in ([100., 150., 412.], [80., 100., 120., 362.]):
            with self.subTest(sites=len(energies)):
                out = self._order_prior_result(energies)
                self.assertTrue(out['candidates'])
                self.assertTrue(all(c['prior_weight'] == 1/G.math.factorial(len(energies))
                                    for c in out['candidates']))
                self._assert_order_prior_conservation(out)

    def test_order_prior_retains_rank_deficient_aggregate_alternative(self):
        out = self._order_prior_result([200., 462.], rank_deficient=7)
        self.assertEqual(out['energy_bookkeeping']['rank_deficient_supports'], 7)
        self.assertEqual([c['prior_weight'] for c in out['candidates']], [.25, .25])
        self.assertEqual(out['unsupported_hypothesis_mass'], .5)
        self._assert_order_prior_conservation(out)

    def test_saved_order_prior_migration_matches_runtime_without_refit(self):
        expected = self._order_prior_result([507.351, 153.809])
        legacy = copy.deepcopy(expected)
        legacy['candidates'][0].update(prior_weight=1., weight=1.)
        legacy['unsupported_hypothesis_mass'] = 0.
        legacy['candidate_weight_scope'] = 'Equal conditional candidates, not calibrated posterior probabilities.'
        before = copy.deepcopy(legacy)
        with patch.object(G, '_fit_flow', side_effect=AssertionError('Saved migration must not refit')), \
                patch.object(G, 'sequence_candidates', side_effect=AssertionError('Saved migration must not rebuild candidates')):
            self.assertEqual(P.migrate(legacy), expected)
        self.assertEqual(legacy, before)

    def test_saved_order_prior_migration_rejects_incomplete_site_order(self):
        legacy = self._order_prior_result([200., 462.])
        legacy['hypotheses'][0]['sites'].append(copy.deepcopy(legacy['hypotheses'][0]['sites'][0]))
        with self.assertRaisesRegex(ValueError, 'complete conditional sites'):
            P.migrate(legacy)

    def test_one_to_many_energy_bookkeeping(self):
        event, native, channels = fixture([(4, 21, 200, -2), (4, 29, 462, 3)])
        out = G.reconstruct_event(event, native, channels, Bank())
        self.assertEqual(out['energy_keV'], 662)
        self.assertEqual(out['strip_counts'], [1, 2])
        self.assertEqual(out['hypotheses'][0]['status'], 'conditional_fit')
        self.assertEqual([s['position_mm'][2] for s in out['hypotheses'][0]['sites']], [-2, 3])
        self.assertTrue(out['candidates'])
        self.assertFalse(out['imaging_accepted'])
        self.assertIn('unresolved', out['reason'])

    def test_truth_and_source_values_cannot_change_answer(self):
        event, native, channels = fixture([(4, 21, 200, -2), (13, 29, 462, 3)])
        baseline = G.reconstruct_event(event, native, channels, Bank())
        event.update(truth_edep_keV=-999, source_id='wrong', source_group='arbitrary',
                     input_steps=[{'position_mm': [1e9, 0, 0]}], steps=[{'endpoints': 'wrong'}],
                     reconstruction={'sites': [{'position_mm': [0, 0, -5]}]})
        self.assertEqual(baseline, G.reconstruct_event(event, native, channels, Bank()))

    def test_native_failure_is_null_and_never_fabricated(self):
        out = G.reconstruct_event({'event_id': 3, 'status': 'native_failed', 'channels': None}, None, [], None)
        self.assertIsNone(out['energy_keV'])
        self.assertEqual(out['candidates'], [])
        self.assertEqual(out['status'], 'native_failed_or_incomplete')

    def test_no_independent_bank_does_not_use_legacy_ctd(self):
        event, native, channels = fixture([(4, 21, 200, -2)])
        out = G.reconstruct_event(event, native, channels, None)
        self.assertEqual(out['reason'], 'independent_waveform_templates_unavailable')
        self.assertFalse(out['imaging_accepted'])

    def test_same_pixel_does_not_invent_two_interactions(self):
        event, native, channels = fixture([(4, 21, 662, -2)])
        out = G.reconstruct_event(event, native, channels, Bank())
        self.assertEqual(out['hypotheses'][0]['sites'][0]['position_mm'][2], -2)
        self.assertEqual(out['reason'], 'same_pixel_multiplicity_unidentifiable')
        self.assertEqual(out['candidates'], [])

    def test_unmodelled_bipolar_induction_is_mismatch_not_last_crossing_depth(self):
        event, native, channels = fixture([(4, 21, 200, -2), (13, 29, 462, 3)])
        for cid in (4, 21):
            t = np.array(native[cid]['time_ns'])
            q = np.array(native[cid]['signed_induced_keV'])
            q += (1 if cid == 4 else -1)*-300*np.exp(-((t-100)/12)**2)
            q[-1] = (1 if cid == 4 else -1)*200
            native[cid]['signed_induced_keV'] = q.tolist()
        out = G.reconstruct_event(event, native, channels, Bank())
        self.assertEqual(out['candidates'], [])
        self.assertTrue(any(h['status'] == 'model_mismatch' for h in out['hypotheses']))

    def test_energy_flow_preserves_both_face_constraints(self):
        xs = [{'contact_id': 2, 'reconstructed_energy_keV': 100}, {'contact_id': 7, 'reconstructed_energy_keV': 200}]
        ys = [{'contact_id': 20, 'reconstructed_energy_keV': 130}, {'contact_id': 28, 'reconstructed_energy_keV': 170}]
        flows, _ = G.energy_flows(xs, ys)
        self.assertGreater(len(flows), 1)
        for flow in flows:
            for c in xs:
                self.assertAlmostEqual(sum(e for x,y,e in flow if x == c['contact_id']), c['reconstructed_energy_keV'])
            for c in ys:
                self.assertAlmostEqual(sum(e for x,y,e in flow if y == c['contact_id']), c['reconstructed_energy_keV'])

    def test_adc_difference_does_not_create_subthreshold_false_site(self):
        xs = [{'contact_id': 2, 'reconstructed_energy_keV': 100}, {'contact_id': 7, 'reconstructed_energy_keV': 200}]
        ys = [{'contact_id': 20, 'reconstructed_energy_keV': 100.7}, {'contact_id': 28, 'reconstructed_energy_keV': 199.3}]
        flows, _ = G.energy_flows(xs, ys)
        self.assertTrue(any(len(f) == 2 for f in flows))
        self.assertTrue(all(e >= 5 for f in flows for _,_,e in f))

    def test_no_residual_dilution_by_long_flat_tail(self):
        event, native, channels = fixture([(4, 21, 200, -2), (13, 29, 462, 3)])
        before = G.reconstruct_event(event, native, channels, Bank())
        for wave in native.values():
            wave['time_ns'].extend(range(151, 1001))
            wave['signed_induced_keV'].extend([wave['signed_induced_keV'][-1]]*850)
        after = G.reconstruct_event(event, native, channels, Bank())
        self.assertEqual(before['hypotheses'], after['hypotheses'])

    def test_nonfinite_and_nonmonotonic_signal_rejected(self):
        with self.assertRaises(ValueError):
            G._wave({'time_ns': [0, 0], 'signed_induced_keV': [0, 1]})
        with self.assertRaises(ValueError):
            G._wave({'time_ns': [0, 1], 'signed_induced_keV': [0, float('nan')]})

    def test_sequence_uses_total_remaining_energy(self):
        sites = [{'position_mm': [0,0,0], 'energy_keV': 100}, {'position_mm': [10,0,0], 'energy_keV': 150},
                 {'position_mm': [20,10,0], 'energy_keV': 412}]
        for s in sites:
            s.update(position_covariance_mm2=np.diag([10.,10.,10.]).tolist(), energy_sigma_keV=2.)
        candidates = G.sequence_candidates(sites)
        self.assertTrue(candidates)
        for c in candidates:
            self.assertAlmostEqual(c['scatter_energy_keV']+c['absorbed_energy_keV'], 662)

    def test_sqlite_reader_is_hash_checked_and_does_not_mutate(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'.local') as root:
            path = Path(root)/'saved.sqlite'
            db = sqlite3.connect(path)
            db.execute('CREATE TABLE events(primary_id,group_id,metadata,metadata_sha256)')
            db.execute('CREATE TABLE arrays(digest,count,value)')
            digest, count, blob = S.pack_array([0., 1.])
            event = {'event_id': 8, 'native_signals': {'4': {'time_ns': {'sha256': digest, 'count': count}}}}
            body = S.encoded(event)
            db.execute('INSERT INTO arrays VALUES(?,?,?)', (digest,count,blob))
            db.execute('INSERT INTO events VALUES(?,?,?,?)', (8,0,zlib.compress(body),S.sha(body)))
            db.commit(); db.close()
            before = path.read_bytes()
            loaded, arrays, _ = G.read_saved_group(path,8,0)
            self.assertEqual(arrays[4]['time_ns'], [0.,1.])
            self.assertEqual(before,path.read_bytes())
            self.assertFalse(Path(str(path)+'-wal').exists())


if __name__ == '__main__':
    unittest.main()
