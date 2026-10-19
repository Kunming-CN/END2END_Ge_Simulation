"""Saved GeGI calibration identity admission; no waveform fit or solver calls."""
import copy
from pathlib import Path
import tempfile
import unittest

import gegi_calibration_admission as A
import scenario_workflow as W


class Admission(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='gegi-calibration-admission-',dir=W.ROOT/'.local')
        self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.dataset=self.root/'.local/dataset'
        self.campaign=self.dataset/'campaign';self.bank=self.dataset/'templates';self.bank.mkdir(parents=True)
        self.channels=[{'id':i,'wiring_factor':1 if i<=17 else -1,'strip_center_mm':float(i)} for i in range(1,35)]
        native={name:'f'*64 for name in A.SHARED_NATIVE};native.update({'Manifest.toml':'c'*64,'Project.toml':'b'*64})
        self.request={'kind':'gegi_campaign_response_request_v1','model_sha256':'d'*64,
            'field_cache':{'sha256':'e'*64},'numerics':{'field_policy':'reuse-only','drift_dt_ns':1.,'drift_cap_ns':1000.,
                'precision_bits':64,'diffusion':False,'self_repulsion':False},
            'source_sha256':{'simulation/'+k:v for k,v in native.items()}}
        request_path=self.dataset/'native.json';W.write(request_path,self.request)
        oldrequest=copy.deepcopy(self.request);oldrequest['generation']='retained_reader_revision'
        old_path=self.dataset/'original-native.json';W.write(old_path,oldrequest)
        oldplan=self.dataset/'original-plan.json';W.write(oldplan,{'native_request':{'ref':old_path.relative_to(self.root).as_posix(),'sha256':W.sha(old_path)}})
        revision=self.dataset/'revision.json';W.write(revision,{'original_plan':{'ref':oldplan.relative_to(self.root).as_posix(),'sha256':W.sha(oldplan)}})
        plan={'native_request':{'ref':request_path.relative_to(self.root).as_posix(),'sha256':W.sha(request_path)},
              'model_sha256':'d'*64,'recovery':{'ref':revision.relative_to(self.root).as_posix(),'sha256':W.sha(revision)}}
        W.write(self.campaign/'plan.json',plan);self.plan=plan
        recipe={'channels':self.channels,'drift_dt_ns':1.,'source_code_sha256':native};seals={}
        for index,path in enumerate((request_path,old_path)):
            done={'identity':{'chunk_index':index,'model_sha256':'d'*64,'native_request_sha256':W.sha(path)},
                  'response':{'native_request_sha256':W.sha(path),'new_field_solve':False,
                              'readout_recipe':recipe,'readout_recipe_sha256':W.digest(recipe)}}
            seal=self.campaign/'chunks'/f'g{index}'/'b000'/ 'DONE.json';W.write(seal,done);seals[str(index)]=W.sha(seal)
        W.write(self.campaign/'COMPLETE.json',{'kind':'gegi_campaign_plan_v1','status':'completed',
            'plan_sha256':W.sha(self.campaign/'plan.json'),'chunks':seals})
        self.identity={'kind':'gegi_pixel_calibration_identity_v1','model_sha256':'d'*64,'channels':self.channels,
            'field_cache':{'sha256':'e'*64},'field_precision_bits':32,'numerics':{'dt':1.,'max_steps':1001},
            'source_sha256':native,'environment':{'manifest_sha256':'c'*64,'julia_version':'1.13.0'}}
        self.save_bank(self.identity)

    def save_bank(self,identity):
        W.write(self.bank/'identity.json',identity)
        W.write(self.bank/'depth-calibration.json',{'identity_sha256':W.sha(self.bank/'identity.json')})

    def test_exact_cache_and_retained_request_generations_are_admitted(self):
        result=A.campaign(self.campaign,self.bank,root=self.root)
        self.assertEqual(result['sealed_chunks_checked'],2)
        self.assertEqual(len(result['original_native_request_variants_checked']),2)
        self.assertEqual(result['channel_count'],34);self.assertEqual(result['field_precision_bits'],32)
        self.assertEqual(result['drift_dt_ns'],1.);self.assertEqual(result['max_steps'],1001)
        self.assertIsNone(A.campaign(self.campaign,None,root=self.root))

    def test_rehashed_incompatible_bank_metadata_are_rejected(self):
        for mutate in (lambda x:x.update(model_sha256='0'*64),lambda x:x['field_cache'].update(sha256='0'*64),
                       lambda x:x['numerics'].update(max_steps=1002),lambda x:x['numerics'].update(dt=2.),
                       lambda x:x['channels'][0].update(wiring_factor=-1),lambda x:x.update(field_precision_bits=128),
                       lambda x:x['environment'].update(manifest_sha256='0'*64),
                       lambda x:x['source_sha256'].update({'readout.jl':'0'*64})):
            identity=copy.deepcopy(self.identity);mutate(identity);self.save_bank(identity)
            with self.assertRaises(W.ControlError):A.campaign(self.campaign,self.bank,root=self.root)

    def test_changed_request_revision_and_chunk_receipts_are_not_rebaselined(self):
        request_path=self.dataset/'original-native.json';request_path.write_bytes(request_path.read_bytes()+b' ')
        with self.assertRaisesRegex(W.ControlError,'generation changed'):A.campaign(self.campaign,self.bank,root=self.root)

    @unittest.skipUnless((W.ROOT/'.local/gegi-10m/pixel-calibration/depth-calibration.json').is_file(),
                         'Original campaign/calibration evidence is local only')
    def test_actual_current_campaign_bank_admission_without_numerical_replay(self):
        result=A.campaign(W.ROOT/'.local/gegi-10m/campaign',W.ROOT/'.local/gegi-10m/pixel-calibration')
        self.assertEqual(result['sealed_chunks_checked'],100)
        self.assertEqual(len(result['original_native_request_variants_checked']),3)
        self.assertEqual(result['table_sha256'],'61f59e2fcdd43aa0f04d6a49a6e59c448bc6059057207a8bcd80d46074d29694')
        self.assertEqual(result['field_precision_bits'],32)


if __name__=='__main__':unittest.main()
