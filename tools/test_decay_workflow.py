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
        good=W.read(W.ROOT/'scenarios/detector-capabilities.json')['source_adapters'][p['id']]['acceptance']
        self.assertTrue(D.expected_acceptance(p,good))
        for key,value in [('accepted_groups',0),('accepted_groups',999),('native_failed_groups',1),('seed',1),('primary_count',20),('source_contract_sha256','c'*64),('complete_sha256','f'*64)]:
            changed=dict(good);changed[key]=value;self.assertFalse(D.expected_acceptance(p,changed))

    def test_reviewed_co60_retains_threshold_and_admits_engineering_use(self):
        p=D.preset('co60_point_decay_v1');cap=D.capability(p);a=cap['acceptance']
        self.assertTrue(D.expected_acceptance(p,a))
        self.assertEqual(a['accepted_groups'],8);self.assertEqual(a['readout_rejected'],1)
        self.assertEqual(a['readout_rejection_reasons'],{'below_threshold':1})
        proof=W.read(W.ROOT/a['threshold_evidence_ref']);record=proof['threshold_rejections'][0]
        self.assertEqual((record['event_id'],record['group_id']),(475,0))
        self.assertIsNone(record['reconstructed_energy_keV']);self.assertLess(record['final_induced_keV'],0)
        self.assertEqual(proof['primary_count'],500);self.assertEqual(proof['zero_deposit_primaries'],491)
        self.assertEqual(proof['groups'],proof['accepted_groups']+proof['readout_rejected'])
        for source in ('am241_point_decay_v1','ba133_point_decay_v1'):
            self.assertEqual(D.capability(D.preset(source))['acceptance']['readout_rejected'],0)

    def test_co60_nonthreshold_failure_and_rehashed_metadata_are_refused(self):
        p=D.preset('co60_point_decay_v1');original=D.capability(p)['acceptance']
        mutations=[('native_failed_groups',1),('saturated_groups',1),('accepted_groups',0),('accepted_groups',9),
            ('readout_rejected',0),('readout_rejection_reasons',{'saturated':1}),
            ('readout_rejection_reasons',{'negative_input':1}),('complete_sha256','f'*64),
            ('threshold_evidence_sha256','f'*64)]
        for key,value in mutations:
            changed=copy.deepcopy(original);changed[key]=value
            with self.subTest(key=key,value=value):self.assertFalse(D.expected_acceptance(p,changed))
        missing=copy.deepcopy(original);missing.pop('threshold_evidence_ref')
        self.assertFalse(D.expected_acceptance(p,missing))

    def test_co60_missing_raw_provenance_or_rehashed_evidence_is_refused(self):
        p=D.preset('co60_point_decay_v1');registry=W.read(W.ROOT/'scenarios/detector-capabilities.json')
        a=registry['source_adapters'][p['id']]['acceptance'];proof=W.read(W.ROOT/a['threshold_evidence_ref']);reader=W.read
        for key in ('raw_row_indices','truth_record_sha256','pulse_record_sha256','trace_record_sha256','endpoint_records_sha256'):
            edited=copy.deepcopy(proof);edited['threshold_rejections'][0].pop(key)
            rehashed=copy.deepcopy(registry)
            rehashed['source_adapters'][p['id']]['acceptance']['threshold_evidence_sha256']=W.digest(edited)
            with self.subTest(key=key),patch.object(W,'read',side_effect=lambda path:rehashed if Path(path).name=='detector-capabilities.json' else reader(path)):
                with self.assertRaises(W.ControlError):D.capability(p)
            # The semantic gate also refuses missing provenance if a caller
            # supplies a newly hashed proof, before relying on reviewed pins.
            changed=dict(a,threshold_evidence_sha256=W.digest(edited))
            with patch.object(W,'sha',return_value=changed['threshold_evidence_sha256']),patch.object(W,'read',return_value=edited):
                with self.assertRaises(W.ControlError):D.threshold_evidence(p,changed)
        with patch.object(Path,'is_file',return_value=False):
            with self.assertRaises(W.ControlError):D.capability(p)
if __name__=='__main__':unittest.main()
