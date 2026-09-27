"""In-memory checks for public CSV/evidence and histogram semantics."""
import copy,json,unittest
from million_publication import checked_group,check_bins
class Semantics(unittest.TestCase):
    def row(self):
        g=dict(group_id=0,ge_energy_keV=10.5,source_photon_energy_keV=20.,categories=['partial'])
        return dict(group_id='0',ge_energy_keV='10.5',source_photon_energy_keV='20.0',categories='partial',classifier_status='returned',evidence_json=json.dumps(dict(group=g,classifier_error=None)))
    def test_evidence_consistency(self):
        r=self.row();self.assertEqual(checked_group(r),10.5)
        for key,value in [('ge_energy_keV','11'),('source_photon_energy_keV','21'),('classifier_status','failed_unknown'),('categories','full'),('group_id','1')]:
            changed=dict(r);changed[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):checked_group(changed)
    def test_unknown_failure_is_distinct(self):
        r=self.row();e=json.loads(r['evidence_json']);e['classifier_error']={'type':'ValueError'};e['group']['categories']=['unknown']
        r.update(categories='unknown',classifier_status='failed_unknown',evidence_json=json.dumps(e));self.assertEqual(checked_group(r),10.5)
        r['classifier_status']='returned'
        with self.assertRaisesRegex(ValueError,'status'):checked_group(r)
    def test_bins_and_explicit_tails(self):
        h=dict(edges_keV=[0.,1.,2.],counts=[1,1],exact_zero=3,underflow=1,overflow=1)
        check_bins([.5,1.,-1.,2.],h,zeros=3)
        changed=copy.deepcopy(h);changed['counts']=[0,2]
        with self.assertRaisesRegex(ValueError,'bin'):check_bins([.5,1.,-1.,2.],changed,zeros=3)
        with self.assertRaises(ValueError):check_bins([float('nan')],h)
if __name__=='__main__':unittest.main(verbosity=2)
