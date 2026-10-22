"""Complete-input boundary tests; no native or readout execution."""
import copy
import unittest
import gegi_native_pair_readout as B


def fixture():
    return {'status':'completed','valid':True,
        'endpoints':[{'status':'contact','step_limit_reached':False,'contact_ids':[1]}],
        'signal_coverage':copy.deepcopy(B.R.ALL34_COVERAGE),
        'channel_signals':[{'contact_id':i,'time_ns':[0.,1.,2.],
            'signed_induced_keV':[0.,.5 if i<=17 else -.5,1. if i<=17 else -1.]} for i in range(1,35)]}


class CompleteNativeTests(unittest.TestCase):
    def test_preserves_complete34_polarity_ids_and_actual_time_support(self):
        row=fixture(); before=copy.deepcopy(row)
        result=B.complete_native(row)
        self.assertEqual(result['end_ns'],2.)
        self.assertEqual(result['channels'],34)
        self.assertEqual(row,before)

    def test_step_limit_or_missing_channel_cannot_receive_terminal_hold(self):
        row=fixture(); row['endpoints'][0]['step_limit_reached']=True
        with self.assertRaisesRegex(ValueError,'Complete contact endpoints'):
            B.complete_native(row)
        row=fixture(); row['channel_signals'].pop()
        with self.assertRaisesRegex(ValueError,'All34 original channel'):
            B.complete_native(row)

    def test_truncated_mismatched_axes_and_wrong_polarity_metadata_rejected(self):
        row=fixture(); row['channel_signals'][0]['time_ns']=[0.,1.]
        row['channel_signals'][0]['signed_induced_keV']=[0.,.5]
        with self.assertRaisesRegex(ValueError,'Common complete'):
            B.complete_native(row)
        row=fixture(); row['signal_coverage']['polarity']='rectified'
        with self.assertRaisesRegex(ValueError,'native-signed34'):
            B.complete_native(row)


if __name__=='__main__':
    unittest.main()
