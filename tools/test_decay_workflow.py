"""Source registry/model/eligibility contracts using public inputs only."""
import copy, unittest
from pathlib import Path
from unittest.mock import patch
import decay_workflow as D
import scenario_workflow as W
class SourceCoreTests(unittest.TestCase):
    def test_registry_legacy_and_generic_identity_are_distinct(self):
        allp=D.presets();self.assertEqual(len(allp),5)
        self.assertFalse(D.is_source(W.CS));self.assertFalse(D.is_source(W.GAMMA));self.assertFalse(D.is_source('unknown'))
        for p in allp:
            if p['adapter']==D.ADAPTER:self.assertTrue(D.is_source(p['id']))
    def test_anchor_supported_pose_matches_original(self):
        a=D.anchors();original=W.read(W.ROOT/'transport/cryostat_nominal.json')
        self.assertEqual(a['coordinate_transform'],original['coordinate_transform'])
        self.assertEqual(a['capsule']['axis_global'],[0,1,0]);self.assertEqual(a['source_pose']['position_global_mm'],[0,37.073,.290])
    def test_all_five_detector_contracts_retain_signed_bias_and_originals(self):
        for model,signed in [('AK02',500),('SAP22',700),('GeRC02',240),('KMRC01_candidate',-370),(W.SAP18,-380)]:
            with self.subTest(model=model):
                c=D.model_contract(model,'.local/runs/unit/transport/effective-model/GeRC02.yaml' if model=='GeRC02' else None)
                self.assertEqual(c['model_id'],model);self.assertEqual(c['stored_temperature_K'],78)
                self.assertEqual(c['runtime_temperature_K'],77);self.assertEqual(c['contact_potentials_V'],{'1':0,'2':signed})
                self.assertEqual(D.operating(model)['wiring_factor'],1 if signed>0 else -1)
                if model==W.SAP18:self.assertIn('identity unresolved',c['qualification'])
    def test_policy_cannot_be_rehashed_to_change_science(self):
        p=D.preset('am241_point_decay_v1')
        mutations=[('nuclear_policy',dict(D.POLICY,ground_secondary_lifetime_cap_ns=-1)),('generator','GPS_gamma'),
            ('pdg',22),('position_global_mm',[0,42.073,.290]),('kinetic_energy_keV',662),('allowed_light_nuclear_pdgs',[])]
        for key,value in mutations:
            c=copy.deepcopy(p);c[key]=value
            with self.subTest(key=key),self.assertRaises(W.ControlError):D.validate_source(c)
    def test_pending_presets_and_strict_acceptance_metadata(self):
        p=D.preset('am241_point_decay_v1')
        reader=W.read
        with patch.object(W,'read',side_effect=lambda path: {} if Path(path).name=='detector-capabilities.json' else reader(path)):
            self.assertIsNone(D.capability(p))
        self.assertFalse(D.expected_acceptance(p,{}))
        good={'status':'accepted','detector':'SAP22','primary_count':500,'seed':26092631,'accepted_groups':1,
              'native_failed_groups':0,'readout_rejected':0,'saturated_groups':0,'configuration_sha256':'a'*64,
              'complete_sha256':'b'*64,'source_contract_sha256':W.digest(p),'run_ref':'.local/runs/source-am241-500-v1'}
        self.assertTrue(D.expected_acceptance(p,good))
        for key,value in [('accepted_groups',0),('native_failed_groups',1),('seed',1),('primary_count',20),('source_contract_sha256','c'*64)]:
            changed=dict(good);changed[key]=value;self.assertFalse(D.expected_acceptance(p,changed))
if __name__=='__main__':unittest.main()
