"""Lossless reference/template checks and completed numerical bundle when present."""
import copy
import unittest
import gamma_showcase as S
import gamma_complete_showcase as F

class CompleteShowcaseTests(unittest.TestCase):
    def test_lossless_existing_response_reference(self):
        science,_,reader=S.read_saved_science()
        for m in science['models']:
            cases=m['report']['cases'];byid={c['initial_primary_id']:i for i,c in enumerate(cases)}
            for row in m['truth_ledger']:
                if row['response'] is None:continue
                original=copy.deepcopy(row);packed=copy.deepcopy(row)
                packed.pop('response');packed['response_index']=byid[row['initial_primary_id']]
                restored=copy.deepcopy(packed);restored['response']=cases[restored.pop('response_index')]
                S.exact(restored,original,'Lossless reference including signs/types/flags')
        reader.recheck()

    def test_render_is_offline_and_exact(self):
        data={'kind':'fixture','value':-0.0,'text':'</script>'};html=F.render(data).decode('utf-8')
        self.assertNotIn('__FOCUSED_PLOTS_JS__',html);self.assertIn('SavedFocusPlots',html)
        self.assertIn('\\u003c/script\\u003e',html);self.assertNotIn('src="http',html)
        self.assertIn('Full saved window',html);self.assertIn('response_index',html)
        self.assertIn('Native processing failed: truth is recorded; unknown charge and readout remain null.',html)

    @unittest.skipUnless((F.ROOT/F.BASE/'bundle/COMPLETE.json').exists() or (F.ROOT/F.BASE/'bundle/publication.json').exists(),'Full40 compute/export not yet admitted')
    def test_actual_completed_bundle(self):
        data=F.validate_bundle(F.ROOT/F.BASE/'bundle')
        self.assertEqual(sum(len(m['report']['cases']) for m in data['science']['models']),40)

if __name__=='__main__':unittest.main()
