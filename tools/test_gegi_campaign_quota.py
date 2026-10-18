"""Quota transaction checks with synthetic stores; no radiation or drift."""
import copy
import unittest
from unittest.mock import patch

import gegi_campaign as C
import gegi_campaign_analysis as A
import gegi_campaign_quota as Q
import gegi_campaign_recovery as R
import gegi_campaign_response as Response
import gegi_event_store as S
import test_gegi_campaign_recovery as T


class FullAllocationFixture(T.Fixture):
    def pilots(self,plan):
        for group in plan['groups']:
            group['primary_count']=Q.QUOTAS[group['id']]*10
            group['partition']=C.B.partition(group['primary_count'],group['master_seed'])
        plan['total_initial_primaries']=10000000
        return super().pilots(plan)


class QuotaTests(unittest.TestCase):
    def setUp(self):
        self.r=T.RecoveryTests('runTest')
        with patch.object(T,'Fixture',FullAllocationFixture):self.r.setUp()
        self.addCleanup(self.r.doCleanups)
        self.r.second_stage();self.r.prepare();self.r.apply()
        self.root=self.r.root;self.directory=self.r.directory
        old=C.read_plan(self.directory,root=self.root);chunk=self.r.chunk;folder=self.r.folder
        identity=C.chunk_identity(self.directory,old,chunk,root=self.root)
        recipe=copy.deepcopy(self.r.first_response['readout_recipe'])
        recipe['source_code_sha256']['gegi_campaign_response.jl']=C.sha(self.root/R.WRAPPER)
        spec=R.saved_failure(old,chunk,root=self.root)
        db=S.Store(self.r.store,identity)
        worker=object.__new__(Response.ResidentWorker)
        worker.ready={'channels':[],'readout_config':{},'electronics_calibration':{},'ionisation_energy_eV':3.,
            'drift_dt_ns':1.,'source_code_sha256':recipe['source_code_sha256']}
        worker.command=lambda *a,**kw:self.fail('Synthetic quota fixture must never call native processing')
        with patch.object(Response,'ROOT',self.root):worker.process_group(self.r.failed_group,db,saved_native_failure=spec)
        response={'kind':C.RESPONSE_KIND,'status':'completed_with_native_failures',
            'input_manifest_sha256':C.sha(folder/'transport/stream/manifest.json'),'store_identity_sha256':C.digest(identity),
            'counts':{'initial_primaries':10000,'zero_deposit_primaries':9999,'nonzero_primaries':1,'native_failed_groups':1},
            'calibration_sha256':old['calibration']['sha256'],'photopeak_windows_sha256':identity['photopeak_windows_sha256'],
            'native_request_sha256':old['native_request']['sha256'],'new_field_solve':False,'source_id':C.GAMMA,
            'readout_recipe':recipe,'readout_recipe_sha256':S.sha(S.encoded(recipe)),
            'prior_recipe_provenance':R.prior_provenance(old,chunk,root=self.root),'saved_native_failure':spec}
        db.seal(response);db.close();C.write(folder/'response.json',response,fresh=True)
        C.seal_chunk(self.directory,old,chunk,response,root=self.root)
        self.old=old;self.old_sha=C.sha(self.directory/'plan.json')
        self.sealed=[R.sealed_inventory(self.directory,c) for c in list(C.chunks(old))[:2]]
        self.identities=[C.verify_done(self.directory,old,e['chunk'],root=self.root)['identity'] for e in self.sealed]
        C.write(self.directory/'STOP.json',{'plan_sha256':self.old_sha,'requested_utc':'fixture-owner-stop'})
        C.progress(self.directory,old,'stopped',{'gamma-left':{'initial_primaries':20000}},None)
        for ref in Q.ALLOWED_SOURCES:
            path=self.root/ref;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(('QUOTA MAINTAINER '+ref).encode())
        self.output=self.root/'.local/quota-amendment'

    def prepare(self):
        return Q.prepare(self.directory,self.output,reason='Owner reduces total formal campaign to one million',
            root=self.root,reader=lambda pid:None,source_commit='a'*40)

    def apply(self):
        return Q.apply(self.output,root=self.root,reader=lambda pid:'owned' if pid==C.os.getpid() else None)

    def test_exact_million_subset_preserves_both_ancestor_identities_and_offsets(self):
        original=(self.directory/'plan.json').read_bytes();self.prepare()
        self.assertEqual((self.directory/'plan.json').read_bytes(),original)
        self.assertEqual(self.apply()['effective_chunks'],100)
        amended=C.read_plan(self.directory,root=self.root);chunks=list(C.chunks(amended))
        self.assertEqual(amended['total_initial_primaries'],1000000);self.assertEqual(len(chunks),100)
        self.assertEqual([g['primary_count'] for g in amended['groups']],[200000,200000,300000,300000])
        self.assertEqual([chunks[i]['campaign_initial_offset'] for i in (0,20,40,70)],[0,200000,400000,700000])
        for group in amended['groups']:
            selected=[c['batch'] for c in chunks if c['source_group']==group['id']]
            original=[c['batch'] for c in C.chunks(self.old) if c['source_group']==group['id']]
            self.assertEqual(selected,original[:len(selected)])
        self.assertEqual(amended['native_request'],self.old['native_request'])
        self.assertEqual(amended['resource_budget'],self.old['resource_budget'])
        for entry,identity in zip(self.sealed,self.identities):
            self.assertEqual(R.sealed_inventory(self.directory,entry['chunk']),entry)
            self.assertEqual(C.verify_done(self.directory,amended,entry['chunk'],root=self.root)['identity'],identity)
        self.assertNotEqual(self.identities[0]['campaign_plan_sha256'],self.old_sha)
        self.assertEqual(self.identities[1]['campaign_plan_sha256'],self.old_sha)
        self.assertEqual(C.chunk_identity(self.directory,amended,chunks[2],root=self.root)['campaign_plan_sha256'],C.sha(self.directory/'plan.json'))
        self.assertEqual(R.spool_path(self.directory,amended,self.root),R.spool_path(self.directory,self.old,self.root))
        self.assertEqual(len(list(A.sealed_chunks(self.directory,amended,allow_partial=True,root=self.root))),2)
        failed_done=C.read(self.r.folder/'DONE.json')
        with A.scalar_store(self.r.store,failed_done['identity'],failed_done['response']) as db:
            failed,_=db.read(0,1)
        self.assertEqual(failed['status'],'native_failed');self.assertIsNone(failed['native_signals'])
        self.assertFalse(failed['saved_native_failure']['drift_replayed'])
        self.assertEqual(C.read(self.directory/'STOP.json')['plan_sha256'],C.sha(self.directory/'plan.json'))
        with self.assertRaisesRegex(ValueError,'original 10M'):Q.effective_plan(amended)

    def test_remaining_disk_uses_original_allowance_ratio_with_effective_quota(self):
        self.prepare();self.apply();amended=C.read_plan(self.directory,root=self.root)
        basis=Q.original_plan(amended,self.root);budget=basis['resource_budget']
        acceptance=C.read(C.bound_file(self.root,basis['acceptance']))
        baseline,_=C.storage_projection(basis,acceptance)
        effective_remaining=sum((baseline[g['id']]*Q.QUOTAS[g['id']]+g['primary_count']-1)//g['primary_count'] for g in basis['groups'])
        expected=(budget['projected_retained_bytes']*effective_remaining+sum(baseline.values())-1)//sum(baseline.values())
        expected+=budget['max_chunk_temporary_bytes']+budget['reserve_bytes']
        self.assertEqual(C.required_launch_disk_bytes(amended,{},root=self.root),expected)
        self.assertLess(expected-budget['max_chunk_temporary_bytes']-budget['reserve_bytes'],budget['projected_retained_bytes']//5)

    def test_interrupted_metadata_apply_resumes_without_store_edits(self):
        self.prepare();replace=R._replace;calls=[]
        def interrupt(source,target):
            calls.append(target.name)
            if len(calls)==2:raise OSError('synthetic quota interruption')
            replace(source,target)
        with patch.object(R,'_replace',side_effect=interrupt):
            with self.assertRaisesRegex(OSError,'quota interruption'):self.apply()
        self.assertEqual(self.apply()['status'],'complete')
        for entry in self.sealed:self.assertEqual(R.sealed_inventory(self.directory,entry['chunk']),entry)

    def test_nonmaintainer_source_change_is_refused_before_admission(self):
        (self.root/'tools/gegi_campaign_response.py').write_bytes(b'CHANGED RESPONSE')
        with self.assertRaisesRegex(ValueError,'non-maintainer'):self.prepare()
        self.assertFalse(self.output.exists())

    def test_changed_sealed_bytes_block_apply_and_keep_original_plan(self):
        self.prepare();p=C.chunk_path(self.directory,self.sealed[1]['chunk'])/'transport/geometry.gdml';p.write_bytes(b'CHANGED')
        with self.assertRaisesRegex(ValueError,'sealed chunk bytes'):self.apply()
        self.assertEqual(C.sha(self.directory/'plan.json'),self.old_sha)


def load_tests(loader,tests,pattern):return loader.loadTestsFromTestCase(QuotaTests)


if __name__=='__main__':unittest.main()
