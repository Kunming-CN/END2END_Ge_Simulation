"""Synthetic identity recovery only; no native worker or radiation is started."""
import copy
import sqlite3
import unittest
from unittest.mock import patch

import gegi_campaign as C
import gegi_campaign_analysis as A
import gegi_campaign_recovery as R
import gegi_event_store as S
from test_gegi_campaign import CampaignTests,FakeTransport


class Fixture(CampaignTests):
    def pilots(self,plan):
        wrapper=self.root/R.WRAPPER;wrapper.parent.mkdir(exist_ok=True);wrapper.write_bytes(b'ORIGINAL WRAPPER')
        request_path=self.root/plan['native_request']['ref'];request=C.read(request_path)
        request['source_sha256']={R.WRAPPER:C.sha(wrapper)};C.write(request_path,request)
        plan['native_request']=self.binding(request_path)
        accepted=super().pilots(plan);path=self.root/accepted['ref'];value=C.read(path)
        self.recipe={'source_code_sha256':{'gegi_campaign_response.jl':C.sha(wrapper)},'fixed_gain':2.}
        for record in value['groups']:
            response_path=self.root/record['response_receipt']['ref'];response=C.read(response_path)
            response.update(readout_recipe=self.recipe,readout_recipe_sha256=S.sha(S.encoded(self.recipe)))
            C.write(response_path,response)
            db=sqlite3.connect(self.root/record['store']['ref'])
            db.execute('UPDATE completion SET body=?',(S.encoded(response),));db.commit();db.close()
            record['response_receipt']=self.binding(response_path);record['store']=self.binding(self.root/record['store']['ref'])
            record.update(C.pilot_storage_bytes(response_path.parent))
        C.write(path,value);return self.binding(path)


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.f=Fixture('runTest');self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.root=self.f.root;self.directory=self.f.directory;self.plan=self.f.freeze()
        self.chunk=next(C.chunks(self.plan));self.folder=C.chunk_path(self.directory,self.chunk)
        FakeTransport().process(self.folder,C.selection_for(self.plan,self.chunk),lambda:None)
        self.store=self.folder/'events.sqlite'
        db=S.Store(self.store,C.chunk_identity(self.directory,self.plan,self.chunk),create=True)
        event={'event_id':1,'group_id':0,'status':'completed','readout_recipe_sha256':S.sha(S.encoded(self.f.recipe)),
               'channels':[{'contact_id':1,'trace':{'time_ns':[0.,1.],'value':[0.,2.]}}]}
        db.append(1,0,event,{1:{'time_ns':[0.,1.],'signed_induced_keV':[0.,2.]}},'1'*64);db.close()
        evidence=self.root/'.local/failure.json'
        C.write(evidence,{'kind':'gegi_contact_failure_preservation_v1','status':'preserved','error':R.ERROR,
            'old_plan_sha256':C.sha(self.directory/'plan.json'),'files':{
                self.store.relative_to(self.root).as_posix():{'sha256':C.sha(self.store)}}})
        self.evidence=R.binding(evidence,self.root)
        for ref in R.ALLOWED_SOURCES:
            path=self.root/ref;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(('REVISED '+ref).encode())
        request=copy.deepcopy(C.read(self.root/self.plan['native_request']['ref']))
        request['source_sha256']={ref:C.sha(self.root/ref) for ref in request['source_sha256']}
        target=self.root/'.local/revised-request.json';C.write(target,request)
        self.request=R.binding(target,self.root);self.output=self.root/'.local/recovery'

    def prepare(self):
        return R.prepare(self.directory,self.request,self.evidence,self.output,reason='Record exact contact-domain failure without physics edits',
                         allowed_sources=sorted(R.ALLOWED_SOURCES),root=self.root,reader=lambda pid:None)

    def apply(self):
        return R.apply(self.output,root=self.root,reader=lambda pid:'owned-test' if pid==C.os.getpid() else None)

    def test_identity_only_recovery_preserves_original_blobs_and_acceptance(self):
        before=R.store_snapshot(self.store);original_plan=(self.directory/'plan.json').read_bytes();old_store=C.sha(self.store)
        self.prepare()
        self.assertEqual((self.directory/'plan.json').read_bytes(),original_plan)
        self.assertEqual(C.sha(self.store),old_store)
        result=self.apply();self.assertEqual(result['status'],'complete')
        revised=C.read_plan(self.directory,root=self.root)
        self.assertEqual(R.store_snapshot(self.store)['tables'],before['tables'])
        self.assertNotEqual(R.store_snapshot(self.store)['identity'],before['identity'])
        self.assertEqual((self.output/'original-plan.json').read_bytes(),original_plan)
        self.assertEqual(C.sha(self.output/'original-events.sqlite'),old_store)
        self.assertEqual(revised['acceptance'],self.plan['acceptance']);self.assertEqual(revised['resource_budget'],self.plan['resource_budget'])
        self.assertNotEqual(R.spool_path(self.directory,revised,self.root),self.directory/'native-spool')
        self.assertFalse(R.spool_path(self.directory,revised,self.root).exists())
        prior=R.prior_provenance(revised,self.chunk,root=self.root)
        self.assertEqual(prior['events'],before['events'])
        current_recipe=copy.deepcopy(self.f.recipe);current_recipe['source_code_sha256']['gegi_campaign_response.jl']=C.sha(self.root/R.WRAPPER)
        response={'readout_recipe':current_recipe,'readout_recipe_sha256':S.sha(S.encoded(current_recipe)),'prior_recipe_provenance':prior}
        db=S.Store(self.store,C.chunk_identity(self.directory,revised,self.chunk))
        try:event,_=db.read(1,0);self.assertTrue(db.has(1,0,'1'*64))
        finally:db.close()
        self.assertEqual(A.response_recipe_for_event(response,event),self.f.recipe)
        event['invented_field']=True
        with self.assertRaisesRegex(ValueError,'metadata/version'):A.response_recipe_for_event(response,event)

    def test_interrupted_apply_resumes_without_touching_preserved_rows(self):
        self.prepare();before=R.store_snapshot(self.store)['tables']
        with patch.object(R,'_replace',side_effect=OSError('interrupted metadata apply')):
            with self.assertRaisesRegex(OSError,'interrupted metadata'):self.apply()
        self.assertEqual(C.read(self.output/'application.json')['status'],'applying')
        self.assertEqual(R.store_snapshot(self.store)['tables'],before)
        self.assertEqual(self.apply()['status'],'complete')
        self.assertEqual(R.store_snapshot(self.store)['tables'],before)

    def test_source_audit_and_request_physics_refuse_before_acceptance(self):
        request=C.read(self.root/self.request['ref']);request['numerics']['field_policy']='fresh'
        C.write(self.root/self.request['ref'],request);self.request=R.binding(self.root/self.request['ref'],self.root)
        with patch.object(C,'verify_acceptance_value',side_effect=AssertionError('Acceptance must not precede source/equivalence audit')):
            with self.assertRaisesRegex(ValueError,'beyond source pins'):self.prepare()
        self.assertEqual(C.sha(self.directory/'plan.json'),self.evidence and C.read(self.root/self.evidence['ref'])['old_plan_sha256'])

    def test_unlisted_producer_change_is_not_admitted(self):
        (self.root/'transport/gegi_geometry.py').write_bytes(b'CHANGED GEOMETRY')
        with patch.object(C,'verify_acceptance_value',side_effect=AssertionError('Must refuse before acceptance')):
            with self.assertRaisesRegex(ValueError,'allowlist'):self.prepare()
        self.assertFalse(self.output.exists())

    def test_completed_store_is_never_rebound(self):
        db=sqlite3.connect(self.store);db.execute('INSERT INTO completion VALUES(1,?)',(b'{}',));db.commit();db.close()
        with self.assertRaisesRegex(ValueError,'Completed Store'):self.prepare()


def load_tests(loader,tests,pattern):return loader.loadTestsFromTestCase(RecoveryTests)


if __name__=='__main__':unittest.main()
