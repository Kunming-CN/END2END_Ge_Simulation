"""Synthetic identity recovery only; no native worker or radiation is started."""
import copy
import sqlite3
import unittest
from unittest.mock import patch

import gegi_campaign as C
import gegi_campaign_analysis as A
import gegi_campaign_recovery as R
import gegi_campaign_response as Response
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
        db=S.Store(self.store,C.chunk_identity(self.directory,revised,self.chunk,root=self.root))
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

    def second_stage(self):
        self.prepare();self.apply()
        predecessor=C.read_plan(self.directory,root=self.root)
        recipe=copy.deepcopy(self.f.recipe)
        recipe['source_code_sha256']['gegi_campaign_response.jl']=C.sha(self.root/R.WRAPPER)
        identity=C.chunk_identity(self.directory,predecessor,self.chunk,root=self.root)
        response={'kind':C.RESPONSE_KIND,'status':'completed',
            'input_manifest_sha256':C.sha(self.folder/'transport/stream/manifest.json'),
            'store_identity_sha256':C.digest(identity),'counts':{'initial_primaries':2,'zero_deposit_primaries':1,'nonzero_primaries':1},
            'calibration_sha256':predecessor['calibration']['sha256'],'photopeak_windows_sha256':identity['photopeak_windows_sha256'],
            'native_request_sha256':predecessor['native_request']['sha256'],'new_field_solve':False,
            'source_id':C.selection_for(predecessor,self.chunk)['source'],
            'readout_recipe':recipe,'readout_recipe_sha256':S.sha(S.encoded(recipe)),
            'prior_recipe_provenance':R.prior_provenance(predecessor,self.chunk,root=self.root)}
        db=S.Store(self.store,identity);db.seal(response);db.close()
        C.write(self.folder/'response.json',response,fresh=True)
        C.seal_chunk(self.directory,predecessor,self.chunk,response,root=self.root)
        self.first_chunk=self.chunk;self.first_store=self.store;self.first_response=response
        self.sealed=R.sealed_inventory(self.directory,self.chunk)
        self.chunk=list(C.chunks(predecessor))[1];self.folder=C.chunk_path(self.directory,self.chunk)
        FakeTransport().process(self.folder,C.selection_for(predecessor,self.chunk),lambda:None)
        self.store=self.folder/'events.sqlite'
        db=S.Store(self.store,C.chunk_identity(self.directory,predecessor,self.chunk,root=self.root),create=True)
        event={'event_id':0,'group_id':0,'status':'completed','readout_recipe_sha256':response['readout_recipe_sha256'],'channels':[]}
        db.append(0,0,event,{},'2'*64);db.close()
        evidence=self.root/'.local/second-failure.json'
        self.failed_group={'event_id':0,'group_id':1,'source_group':self.chunk['source_group'],
            'chunk_index':self.chunk['chunk_index'],'campaign_initial_offset':self.chunk['campaign_initial_offset'],
            'steps':[{'raw_row_index':7,'energy_keV':1.,'position_mm':[1.,2.,3.],'time_ns':0.}],
            'source_id':C.selection_for(predecessor,self.chunk)['source'],'initial_primary_id':0}
        digest=S.sha(S.encoded(self.failed_group));spool_ref='.local/campaign/native-spool-recovery-fixture/g-'+digest
        self.failed_path=evidence.parent/'originals'/(spool_ref+'.json');self.failed_path.parent.mkdir(parents=True)
        failure={'event_id':0,'status':'unexpected_failure','exception_type':'ArgumentError','error':R.SECOND_ERROR,
            'input_group':self.failed_group,'steps':self.failed_group['steps'],'channels':None,'signals_ref':None,
            'signals_sha256':None,'transport_flags':None,'native_domain_error':None,'truth_edep_keV':1.,
            'native_failure_policy':'gegi_campaign_native_domain_errors_v2'}
        C.write(self.failed_path,failure)
        input_path=evidence.parent/'originals'/(spool_ref+'-input.json');C.write(input_path,self.failed_group)
        C.write(evidence,{'kind':'gegi_native_charge_failure_preservation_v1','status':'preserved','error':R.SECOND_ERROR,
            'event_id':0,'group_id':1,'chunk':self.chunk,
            'old_plan_sha256':C.sha(self.directory/'plan.json'),'sealed_chunks':[self.sealed],
            'files':{self.store.relative_to(self.root).as_posix():{'sha256':C.sha(self.store)},
                spool_ref+'.json':{'sha256':C.sha(self.failed_path)},spool_ref+'-input.json':{'sha256':C.sha(input_path)}}})
        self.evidence=R.binding(evidence,self.root)
        for ref in R.ALLOWED_SOURCES:(self.root/ref).write_bytes(('SECOND REPAIR '+ref).encode())
        request=C.read(self.root/predecessor['native_request']['ref'])
        request['source_sha256']={ref:C.sha(self.root/ref) for ref in request['source_sha256']}
        target=self.root/'.local/second-request.json';C.write(target,request)
        self.request=R.binding(target,self.root);self.output=self.root/'.local/second-recovery'
        self.predecessor=predecessor;return R.store_snapshot(self.store)

    def test_second_generation_preserves_sealed_bytes_and_both_recipe_versions(self):
        before=self.second_stage();self.prepare();self.apply()
        revised=C.read_plan(self.directory,root=self.root)
        self.assertEqual(R.original_plan(revised,self.root),self.plan)
        self.assertEqual(R.sealed_inventory(self.directory,self.first_chunk),self.sealed)
        self.assertEqual(R.store_snapshot(self.store)['tables'],before['tables'])
        self.assertNotEqual(R.store_snapshot(self.store)['identity'],before['identity'])
        done=C.verify_done(self.directory,revised,self.first_chunk,root=self.root)
        self.assertEqual(done['identity']['campaign_plan_sha256'],C.sha(self.output/'original-plan.json'))
        self.assertEqual(R.prior_provenance(revised,self.first_chunk,root=self.root),self.first_response['prior_recipe_provenance'])
        with A.scalar_store(self.first_store,done['identity'],done['response']) as db:
            event,_=db.read(1,0)
        self.assertEqual(A.response_recipe_for_event(done['response'],event),self.f.recipe)
        self.assertEqual([c[0] for c in A.sealed_chunks(self.directory,revised,allow_partial=True,root=self.root)],[self.first_chunk])
        current=copy.deepcopy(self.first_response['readout_recipe'])
        current['source_code_sha256']['gegi_campaign_response.jl']=C.sha(self.root/R.WRAPPER)
        response={'readout_recipe':current,'readout_recipe_sha256':S.sha(S.encoded(current)),
                  'prior_recipe_provenance':R.prior_provenance(revised,self.chunk,root=self.root)}
        db=S.Store(self.store,C.chunk_identity(self.directory,revised,self.chunk,root=self.root))
        event,_=db.read(0,0);db.close()
        self.assertEqual(A.response_recipe_for_event(response,event),self.first_response['readout_recipe'])
        self.assertEqual(len(R.spool_paths(self.directory,revised,self.root)),3)
        self.output=self.root/'.local/third-recovery'
        with self.assertRaisesRegex(ValueError,'two admitted generations'):self.prepare()

    def test_second_apply_refuses_changed_sealed_file_without_rebinding_partial(self):
        before=self.second_stage();self.prepare()
        path=C.chunk_path(self.directory,self.first_chunk)/'transport/geometry.gdml'
        path.write_bytes(b'CHANGED SEALED INPUT')
        with self.assertRaisesRegex(ValueError,'sealed chunk bytes'):self.apply()
        self.assertEqual(R.store_snapshot(self.store),before)

    def test_second_generation_requires_exact_preserved_prefix(self):
        self.second_stage()
        path=self.root/self.evidence['ref'];evidence=C.read(path);evidence['sealed_chunks']=[]
        C.write(path,evidence);self.evidence=R.binding(path,self.root)
        with self.assertRaisesRegex(ValueError,'preserved failure snapshot'):self.prepare()
        self.assertFalse(self.output.exists())

    def test_second_generation_refuses_changed_predecessor_application(self):
        self.second_stage()
        path=self.root/'.local/recovery/application.json';record=C.read(path);record['new_plan_sha256']='0'*64;C.write(path,record)
        with self.assertRaisesRegex(ValueError,'transaction is not complete'):self.prepare()
        self.assertFalse(self.output.exists())

    def test_saved_failure_import_is_null_idempotent_and_never_calls_native(self):
        self.second_stage();self.prepare();self.apply()
        plan=C.read_plan(self.directory,root=self.root);spec=R.saved_failure(plan,self.chunk,root=self.root)
        original=self.failed_path.read_bytes()
        worker=object.__new__(Response.ResidentWorker)
        worker.ready={'channels':[],'readout_config':{},'electronics_calibration':{},'ionisation_energy_eV':3.,
                      'drift_dt_ns':1.,'source_code_sha256':{'gegi_campaign_response.jl':C.sha(self.root/R.WRAPPER)}}
        worker.command=lambda *a,**kw:self.fail('Preserved failure must never execute a native command')
        db=S.Store(self.store,C.chunk_identity(self.directory,plan,self.chunk,root=self.root));self.addCleanup(db.close)
        args={'calibration':{},'photopeak_windows':[{'line_energy_keV':662.,'half_width_keV':13.24}],
              'calibration_sha256':plan['calibration']['sha256'],'saved_native_failure':spec}
        with patch.object(Response,'ROOT',self.root):
            saved=worker.process_group(self.failed_group,db,**args)
            self.assertEqual(worker.process_group(self.failed_group,db,**args),saved)
        self.assertEqual(saved['status'],'native_failed');self.assertEqual(saved['error'],R.SECOND_ERROR)
        self.assertIsNone(saved['channels']);self.assertIsNone(saved['native_signals']);self.assertIsNone(saved['transport_flags'])
        self.assertFalse(saved['readout_summary']['accepted']);self.assertIsNone(saved['readout_summary']['energy_keV'])
        self.assertEqual(saved['reconstruction']['status'],'rejected')
        self.assertEqual(saved['input_steps'],self.failed_group['steps'])
        self.assertEqual(saved['saved_native_failure']['original_failure']['sha256'],C.sha(self.failed_path))
        self.assertFalse(saved['saved_native_failure']['drift_replayed'])
        self.assertEqual(saved['native_failure_policy'],'gegi_campaign_native_domain_errors_v2')
        self.assertEqual(self.failed_path.read_bytes(),original)
        self.assertEqual(db.db.execute('SELECT COUNT(*) FROM events').fetchone()[0],2)
        self.assertEqual(R.sealed_inventory(self.directory,self.first_chunk),self.sealed)

    def test_saved_failure_import_rejects_altered_binding_group_or_original_error(self):
        self.second_stage();self.prepare();self.apply()
        plan=C.read_plan(self.directory,root=self.root);spec=R.saved_failure(plan,self.chunk,root=self.root)
        bad=copy.deepcopy(spec);bad['original_failure']['sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'explicitly bound'):R.load_saved_failure(bad,self.failed_group,root=self.root)
        group=copy.deepcopy(self.failed_group);group['steps'][0]['energy_keV']=2.
        with self.assertRaisesRegex(ValueError,'input group/digest/rows'):R.load_saved_failure(spec,group,root=self.root)
        changed=C.read(self.failed_path);changed['error']='ArgumentError: different unexpected failure';C.write(self.failed_path,changed)
        with self.assertRaisesRegex(ValueError,'snapshot bytes'):R.load_saved_failure(spec,self.failed_group,root=self.root)


def load_tests(loader,tests,pattern):return loader.loadTestsFromTestCase(RecoveryTests)


if __name__=='__main__':unittest.main()
