"""Targeted ancestry and comparator checks; no science processes or fixtures."""
import unittest
from gegi_single_two_site_prefilter import classify, comparison
from gegi_transport_prefilter_feasibility import one_gamma_anchor


def track(tid, parent, particle, x=0):
    return {'trackid': tid, 'parent_trackid': parent, 'particle': particle,
        'xloc': x/1000, 'yloc': 0, 'zloc': 0}


def step(tid, particle=11, x=0):
    return {'track_id': tid, 'particle_pdg': particle, 'position_mm': [x, 0, 0], 'energy_keV': 1}


class AnchorTests(unittest.TestCase):
    def test_descendant_rows_are_one_anchor_not_sites(self):
        event = {'tracks': [track(1, 0, 22), track(2, 1, 11), track(3, 2, 11)]}
        group = {'steps': [step(2), step(3, x=4), step(2, x=6)]}
        result = classify(group, event)
        self.assertEqual(result['complete_anchor_count'], 1)
        self.assertTrue(one_gamma_anchor(group, event))
        self.assertEqual(result['decision'], 'retain_le2')

    def test_two_vertices_keep_three_vertices_screen(self):
        event = {'tracks': [track(1, 0, 22), track(2, 1, 11), track(3, 1, 11, 2), track(4, 1, 11, 4)]}
        for n, decision in ((2, 'retain_le2'), (3, 'screen_gt2')):
            group = {'steps': [step(i) for i in range(2, n+2)]}
            result = classify(group, event)
            self.assertEqual(result['complete_anchor_count'], n)
            self.assertEqual(result['decision'], decision)

    def test_noncontributing_births_do_not_count(self):
        event = {'tracks': [track(1, 0, 22), track(2, 1, 11), track(3, 1, 11, 2)]}
        self.assertEqual(classify({'steps': [step(2)]}, event)['complete_anchor_count'], 1)

    def test_secondary_gamma_and_matching_gamma_deposit(self):
        event = {'tracks': [track(1, 0, 22), track(2, 1, 11), track(3, 2, 22), track(4, 3, 11, 2)]}
        result = classify({'steps': [step(2), step(4), step(3, 22, 2)]}, event)
        self.assertEqual(result['complete_anchor_count'], 2)
        self.assertEqual(result['unknown_rows'], 0)

    def test_unknown_retained_even_above_two_known_anchors(self):
        event = {'tracks': [track(1, 0, 22), track(2, 1, 11), track(3, 1, 11, 2), track(4, 1, 11, 4), track(5, 0, 11)]}
        result = classify({'steps': [step(i) for i in range(2, 6)]}, event)
        self.assertEqual(result['known_anchor_count'], 3)
        self.assertIsNone(result['complete_anchor_count'])
        self.assertEqual(result['decision'], 'retain_unknown')

    def test_missing_cycle_duplicate_and_unmatched_are_unknown(self):
        cases = [({'tracks': []}, [step(9)]),
            ({'tracks': [track(2, 3, 11), track(3, 2, 11)]}, [step(2)]),
            ({'tracks': [track(2, 0, 11), track(2, 0, 11)]}, [step(2)]),
            ({'tracks': [track(1, 0, 22)]}, [step(1, 22)]),
            ({'tracks': [track(1, 0, 22), track(2, 1, 11)]}, [step(2, -11)])]
        for event, steps in cases:
            result = classify({'steps': steps}, event)
            self.assertEqual(result['decision'], 'retain_unknown')
            self.assertEqual(result['unknown_rows'], 1)

    def test_comparator_keeps_mismatch_distinct_from_supported(self):
        reconstruction = {'hypotheses': [{'status': 'model_mismatch', 'sites': [{}, {}]},
            {'status': 'conditional_fit', 'sites': [{}, {}, {}]}], 'candidates': [{'order': [0, 1, 2]}]}
        use = {'conditional_candidate_count': 1, 'spectroscopy': {'accepted': True}, 'category': 'ambiguous_imaging'}
        result = comparison(reconstruction, use, 'completed')
        self.assertTrue(result['has_saved_1or2_site_hypothesis'])
        self.assertFalse(result['has_saved_1or2_site_conditional_fit'])
        self.assertEqual(result['saved_candidate_site_counts'], [3])


if __name__ == '__main__':
    unittest.main()
