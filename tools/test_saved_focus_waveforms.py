"""Read-only saved gamma/KM numeric projection and full identity refusal."""
import unittest
import scenario_workflow as W
import saved_focus_waveforms as F

class FocusTests(unittest.TestCase):
    def test_saved_sap_dense_head_camera_and_zero(self):
        directory=W.ROOT/'.local/runs/m14a-gamma-ui-03';complete=W.read(directory/'COMPLETE.json')
        for eid,group in ((2,0),(0,None)):
            p=F.project(directory,directory.name,complete['configuration_sha256'],eid,group)
            self.assertEqual(len(p['panels']),4);self.assertIsNone(p['sidecar_manifest_sha256'])
            self.assertLess(p['panels'][2]['focus_end_ns'],p['panels'][2]['full_end_ns'])
        with self.assertRaises(Exception):F.project(directory,directory.name,complete['configuration_sha256'],2,None)
        with self.assertRaises(Exception):F.project(directory,directory.name,'0'*64,2,0)

    def test_km_raw_sign_and_exact_group_origin(self):
        directory=W.ROOT/'.local/runs/m14a2-km-ui-02';complete=W.read(directory/'COMPLETE.json')
        records=F.rows(directory/'response/scalars.jsonl');case=next(r for r in records if r['record_kind']=='pulse')
        p=F.project(directory,directory.name,complete['configuration_sha256'],case['event_id'],case['group_id'])
        self.assertEqual(p['global_decay_id'],case['global_decay_id']);self.assertEqual(p['origin_time_ns'],case['origin_time_ns'])
        self.assertEqual(p['panels'][3]['peak'],{'t':case['readout']['peak_time_ns'],'v':case['readout']['peak_V']})
        self.assertTrue(any(q<0 for q in p['panels'][0]['values']))
        self.assertEqual(p['panels'][2]['full_end_ns'],99998.0);self.assertIsNone(p['panels'][2]['focus_series'])

if __name__=='__main__':unittest.main()
