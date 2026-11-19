"""Check the timing-only association and conservative reference selection."""

import unittest

from gegi_heldout_pairing_study import link_groups


def deposit(onset, *, classification='awaiting_match', arrival='isolated'):
    return dict(first_ge_deposit_ns=onset, classification=classification, arrival_class=arrival,
                isolated_triggers=[])


def trigger(time):
    return dict(trigger_time_ns=time, rise_end_ns=time+60, x_collecting_strips=[3, 4],
                y_collecting_strips=[23, 24], guard_contact_ids=[])


class HeldOutTimingTests(unittest.TestCase):
    def test_isolated_merged_and_ambiguous_keep_their_group_identities(self):
        groups = [deposit(10_000), deposit(20_000, arrival='close'), deposit(20_010, arrival='close'), deposit(31_000)]
        triggers = [trigger(t) for t in (10_020, 20_020, 31_000, 31_300)]
        links = link_groups(groups, triggers, [])
        self.assertEqual([(r['association'], r['group_indices']) for r in links], [
            ('unique_matched', [0]), ('merged', [1, 2]), ('ambiguous', [3]), ('ambiguous', [3])])
        self.assertEqual([r['truth_link_scope'] for r in links], ['isolated_rise_time_match', 'merged', 'ambiguous', 'ambiguous'])
        self.assertEqual([r['classification'] for r in groups], ['unique_matched', 'merged', 'merged', 'ambiguous'])

    def test_broad_timing_match_can_be_withheld_for_truth(self):
        groups = [deposit(40_000, arrival='close'), deposit(50_000), deposit(60_000, classification='history_unqualified')]
        triggers = [trigger(t) for t in (40_020, 50_300, 60_040)]
        links = link_groups(groups, triggers, [[59_960, 60_020]])
        self.assertEqual([r['truth_link_scope'] for r in links], [
            'near_another_scheduled_ge_group', 'no_rise_onset_overlap_within_60ns', 'history_boundary_unknown'])
        self.assertEqual([r['association'] for r in links], ['unique_matched', 'unique_matched', 'history_boundary_unknown'])


if __name__ == '__main__':
    unittest.main()
