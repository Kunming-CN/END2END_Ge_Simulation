"""Check the truth and full-energy gates in the saved GeGI pairing study."""

import unittest

from gegi_continuous_pairing_study import containment, pairing_score


def pairing(index, cells, *, compatible, allowed=()):
    return {'index': index, 'energy_compatible': compatible,
            'sites': [{'x_contact_id': x, 'y_contact_id': y, 'energy_keV': e} for (x, y), e in zip(cells, (200., 462.))],
            'compton_orders': [{'site_index_order': list(order), 'kinematically_allowed': order in allowed}
                               for order in ((0, 1), (1, 0))] if compatible else []}


class ContinuousPairingTruthTests(unittest.TestCase):
    def setUp(self):
        self.reference = {'containment': 'full_energy_at_photon_birth', 'sites_in_birth_order': [
            {'cell': [4, 21], 'deposited_energy_keV': 461.}, {'cell': [3, 24], 'deposited_energy_keV': 201.}]}

    def test_both_allowed_orders_include_the_original_without_selecting_it(self):
        cards = [pairing(0, [(3, 21), (4, 24)], compatible=True, allowed=((0, 1),)),
                 pairing(1, [(3, 24), (4, 21)], compatible=True, allowed=((0, 1), (1, 0)))]
        score = pairing_score(cards, self.reference)
        self.assertEqual(score['pair_outcome'], 'truth_pair_energy_compatible')
        self.assertEqual(score['truth_site_index_order'], [1, 0])
        self.assertEqual(score['energy_minus_deposit_in_birth_order_keV'], [1., -1.])
        self.assertEqual(score['full_energy_order_outcome'], 'both_allowed')

    def test_full_energy_pair_exclusion_is_scored_and_incomplete_order_is_unscored(self):
        cards = [pairing(0, [(3, 21), (4, 24)], compatible=True, allowed=((0, 1),)),
                 pairing(1, [(3, 24), (4, 21)], compatible=False)]
        self.assertEqual(pairing_score(cards, self.reference)['full_energy_order_outcome'], 'truth_pair_excluded')
        cards[1] = pairing(1, [(3, 24), (4, 21)], compatible=True, allowed=((0, 1),))
        incomplete = {**self.reference, 'containment': 'incomplete_energy_at_photon_birth'}
        self.assertEqual(pairing_score(cards, self.reference)['full_energy_order_outcome'], 'only_reverse_order')
        self.assertNotIn('full_energy_order_outcome', pairing_score(cards, incomplete))
        self.assertIsNone(pairing_score(cards, {'status': 'missing_transport_or_native_metadata'}))

    def test_photon_count_and_other_group_are_kept_in_containment(self):
        root = {'birth_kinetic_energy_keV': 662., 'group_germanium_descendant_deposition_keV': 662.}
        self.assertEqual(containment([root], 662., []), 'full_energy_at_photon_birth')
        self.assertEqual(containment([root], 662., [{'same_root_gamma_deposit_keV': .1}]), 'extra_or_inconsistent_energy')
        self.assertEqual(containment([root, root], 662., []), 'multiple_depositing_photons')
        self.assertEqual(containment([root], 662.5, []), 'extra_or_inconsistent_energy')


if __name__ == '__main__':
    unittest.main()
