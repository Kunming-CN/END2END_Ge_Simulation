import unittest

from gegi_native_readout_compare import TRIGGER_FIELDS, baseline_mismatches, compare_ledgers


def trigger(trigger_id, time_ns, rise_end_ns, decision='candidate'):
    return dict(trigger_id=trigger_id, time_ns=time_ns, rise_end_ns=rise_end_ns, decision=decision,
                reason='test', context_sample_indexes=[10, 20], group_ordinals=[120],
                all34_context_adc_sha256='adc', candidate_adc_sha256='adc', record_sha256='record')


class ReadoutComparisonTests(unittest.TestCase):
    def test_baseline_reports_a_candidate_adc_mismatch(self):
        old = trigger(19, 100., 120.)
        reference = [tuple(old[k] for k in TRIGGER_FIELDS)]
        replayed = dict(old, candidate_adc_sha256='different')
        mismatch = baseline_mismatches(reference, [replayed])
        self.assertEqual(mismatch['missing_original_trigger_ids'], [])
        self.assertEqual(mismatch['changed'], [{'original_trigger_id': 19,
                                               'fields': {'candidate_adc_sha256': ['adc', 'different']}}])

    def test_association_uses_time_and_retains_unresolved_overlap(self):
        old = [trigger(19, 100., 140.), trigger(20, 160., 190.), trigger(21, 400., 425.)]
        new = [trigger(19, 120., 180.), trigger(20, 400., 425., 'rejected'), trigger(21, 500., 520.)]
        result = compare_ledgers(old, new)
        self.assertEqual(result['equal_time_associations'], [dict(original_trigger_id=21,
            counterfactual_trigger_id=20, time_ns=400., changed_fields=['decision'])])
        self.assertEqual(result['baseline_without_equal_time_counterfactual'], [19, 20])
        self.assertEqual(result['counterfactual_without_equal_time_baseline'][0]
                         ['original_trigger_ids_with_overlapping_rise'], [19, 20])
        self.assertEqual(result['counterfactual_without_equal_time_baseline'][1]
                         ['original_trigger_ids_with_overlapping_rise'], [])


if __name__ == '__main__':
    unittest.main()
