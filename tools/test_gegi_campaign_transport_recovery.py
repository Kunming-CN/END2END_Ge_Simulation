"""Synthetic saved-reader transaction; no radiation, field or native calls."""
import copy
from pathlib import Path
import shutil
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

import gegi_campaign as C
import gegi_campaign_analysis as A
import gegi_campaign_quota as Q
import gegi_campaign_recovery as R
import gegi_campaign_transport_recovery as T
from test_gegi_campaign import FakeTransport,FakeWorker
from test_gegi_campaign_quota import QuotaTests


class TransportRevisionTests(unittest.TestCase):
    def setUp(self):
        self.q=QuotaTests('runTest');self.q.setUp();self.addCleanup(self.q.doCleanups)
        self.q.prepare();self.q.apply();self.root=self.q.root;self.directory=self.q.directory
        self.old=C.read_plan(self.directory,root=self.root);self.old_sha=C.sha(self.directory/'plan.json')
        self.totals={g['id']:{'initial_primaries':g['primary_count']} for g in self.old['groups'][:3]}
        self.required_disk=C.required_launch_disk_bytes(self.old,self.totals,root=self.root)
        self.chunks=list(C.chunks(self.old));self.chunk=self.chunks[70];self.folder=C.chunk_path(self.directory,self.chunk)
        for chunk in self.chunks[2:70]:
            folder=C.chunk_path(self.directory,chunk)
            manifest=FakeTransport().process(folder,C.selection_for(self.old,chunk),lambda:None)
            response=FakeWorker(C.bound_file(self.root,self.old['native_request']),folder/'unused').run_chunk(
                manifest,folder/'events.sqlite',C.chunk_identity(self.directory,self.old,chunk,root=self.root),
                calibration=self.old['calibration'],photopeak_windows=next(g['photopeak_windows'] for g in self.old['groups'] if g['id']==chunk['source_group']),
                receipt_path=folder/'response.json')
            C.seal_chunk(self.directory,self.old,chunk,response,root=self.root)
        self.sealed=[R.sealed_inventory(self.directory,c) for c in self.chunks[:70]]
        self.identities=[C.chunk_identity(self.directory,self.old,c,root=self.root) for c in self.chunks[:70]]
        # Quota STOP is an obsolete boundary record, as in the actual resumed campaign.
        (self.directory/'STOP.json').unlink()
        C.progress(self.directory,self.old,'failed',{},self.chunk,error='saved reader failure')
        target=self.folder/'transport';target.mkdir(parents=True)
        selection=C.selection_for(self.old,self.chunk);C.write(self.folder/'selection.json',selection)
        self.checked={'selection':selection,'source_sha256':{k:self.old['source_sha256'][k] for k in T.READERS},
            'model_contract':{'fixed':1},'cryostat_contract':{'fixed':1},'runtime':{'fixed':1.}}
        for path in (self.folder/'source-checked.json',target/'checked-plan.json'):C.write(path,self.checked)
        for name,text in (('geometry.gdml','geometry'),('run.mac','radiation macro'),('geometry.mac','geometry macro'),
                          ('geometry.log','geometry okay'),('run.log','10000 completed')):(target/name).write_text(text)
        (target/'truth.lh5').write_bytes(b'SYNTHETIC COMPLETE RADIATION; NEVER EXECUTED')
        C.write(target/'emlow-data.json',{'directory':'fixed','package_metadata':{},'hash_wall_s':1.})
        C.write(target/'prepare-receipt.json',{'status':'complete','returncode':0,'command':['geometry']})
        meta={'kind':'gegi_source_prepared_v1','status':'complete','selection':selection,'source_sha256':self.checked['source_sha256'],
              'files_sha256':{'checked-plan.json':C.sha(target/'checked-plan.json')},'primary_count':10000}
        C.write(target/'prepared.json',meta)
        C.write(target/'run.json',{'kind':'gegi_transport_run_v1','status':'failed','returncode':0,'error':T.ERROR,
            'source_lh5_sha256':C.sha(target/'truth.lh5'),'prepared_sha256':C.sha(target/'prepared.json'),
            'command':['radiation'],'seed':selection['seed'],'remage_wall_s':7.6,'total_wall_s':11.6,'transport_threads':1})
        self.snapshot=self.root/'.local/reader-failure';self.snapshot.mkdir()
        shutil.copytree(self.folder,self.snapshot/'chunk')
        for name in ('plan.json','FROZEN.json','progress.json'):shutil.copy2(self.directory/name,self.snapshot/name)
        for ref in T.ALLOWED_SOURCES-{T.HELPER}:
            dest=self.snapshot/'sources'/ref;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(self.root/ref,dest)
        info={k:{**v,'mtime_ns':(self.folder/k).stat().st_mtime_ns} for k,v in C.file_inventory(self.folder).items()}
        C.write(self.snapshot/'manifest.json',{'kind':'gegi_transport_recoil_failure_preservation_v1','status':'preserved',
            'error':T.ERROR,'chunk_index':70,'source_group':'co60-right','formal_sealed_initial_primaries':700000,
            'completed_radiation_initial_decays_in_unsealed_chunk':10000,'radiation_rerun':False,'supervisor_and_children_exited':True,
            'files':info,'raw_sha256':C.sha(target/'truth.lh5'),
            'source_sha256':{k:self.old['source_sha256'][k] for k in T.ALLOWED_SOURCES-{T.HELPER}}})
        self.evidence=R.binding(self.snapshot/'manifest.json',self.root)
        for ref in T.ALLOWED_SOURCES:(self.root/ref).write_text('READER REPAIR '+ref)
        self.output=self.root/'.local/reader-revision'
        self.counts={'initial_primaries':10000,'initial_decays':10000,'zero_deposit_primaries':9999,'nonzero_primaries':1,
            'nonzero_event_ids':[3891],'positive_ge_rows':2,'pulse_groups':1,'decay_photons':20000,
            'line_photons':20000,'line_photon_counts':{'Co60_1173':10000,'Co60_1332':10000}}
        checked=copy.deepcopy(self.checked);checked['source_sha256']={k:C.sha(self.root/k) for k in T.READERS}
        self.transport=SimpleNamespace(check=Mock(return_value=checked),census=Mock(return_value=self.counts),
            G=SimpleNamespace(gdml_text=lambda *a:'geometry'),macro=lambda checked,geometry_only=False:'geometry macro' if geometry_only else 'radiation macro',
            command=lambda checked,geometry_only=False:['geometry' if geometry_only else 'radiation'],geometry_log_check=Mock(),
            DIAGNOSTIC='FATAL',T=SimpleNamespace(emlow_manifest=lambda *a:{'directory':'fixed','package_metadata':{},'hash_wall_s':2.}),
            P=SimpleNamespace(project_identity=Mock()),
            run=Mock(side_effect=AssertionError('No radiation')),prepare=Mock(side_effect=AssertionError('No geometry run')))

    def prepare(self):
        return T.prepare(self.directory,self.evidence,self.output,reason='Preserve completed radiation; repair target recoil census',
            root=self.root,reader=lambda pid:None,source_commit='b'*40)

    def derive(self):return T.revalidate_saved_transport(self.output,root=self.root,transport=self.transport,windows_root=str(self.root))
    def apply(self):return T.apply(self.output,root=self.root,reader=lambda pid:'test-owner' if pid==C.os.getpid() else None)

    def test_saved_raw_metadata_derivation_and_all_historical_identities(self):
        raw=self.folder/'transport/truth.lh5';before=(C.sha(raw),raw.stat().st_mtime_ns)
        self.prepare();self.derive()
        self.assertEqual(C.sha(self.directory/'plan.json'),self.old_sha)
        self.assertEqual(C.read(self.folder/'transport/run.json')['status'],'failed')
        self.assertEqual(self.apply()['status'],'complete')
        plan=C.read_plan(self.directory,root=self.root)
        self.assertEqual(T.original_plan(plan,self.root),Q.original_plan(self.old,self.root,_audit_current=False,_plan_sha256=self.old_sha))
        self.assertEqual(C.required_launch_disk_bytes(plan,self.totals,root=self.root),self.required_disk)
        self.assertEqual((C.sha(raw),raw.stat().st_mtime_ns),before)
        self.assertEqual(self.old['groups'],plan['groups']);self.assertEqual(len(list(C.chunks(plan))),100)
        self.assertNotEqual(plan['native_request'],self.old['native_request']);self.assertNotEqual(plan['physics_sha256'],self.old['physics_sha256'])
        request=C.read(C.bound_file(self.root,plan['native_request']));oldrequest=C.read(C.bound_file(self.root,self.old['native_request']))
        self.assertEqual(set(R._changes(request['source_sha256'],oldrequest['source_sha256'])),{'transport/gegi_source.py'})
        for entry,identity in zip(self.sealed,self.identities):
            self.assertEqual(R.sealed_inventory(self.directory,entry['chunk']),entry)
            self.assertEqual(C.verify_done(self.directory,plan,entry['chunk'],root=self.root)['identity'],identity)
        self.assertEqual(self.identities[69]['campaign_plan_sha256'],self.old_sha)
        self.assertEqual(C.chunk_identity(self.directory,plan,self.chunk,root=self.root)['campaign_plan_sha256'],C.sha(self.directory/'plan.json'))
        self.assertEqual(len(list(A.sealed_chunks(self.directory,plan,allow_partial=True,root=self.root))),70)
        A.validate_analysis_revision(plan,root=self.root)
        self.assertNotEqual(T.spool_path(self.directory,plan,self.root),R.spool_path(self.directory,self.old,self.root))
        spool=T.spool_path(self.directory,plan,self.root);spool.mkdir()
        C.write(spool/'worker-process.json',{'status':'running','pid':12345,'process_start_identity':'alive'})
        with self.assertRaisesRegex(ValueError,'live'):C.inactive_children(self.directory,root=self.root,reader=lambda pid:'alive')
        self.transport.census.assert_called_once();self.transport.run.assert_not_called();self.transport.prepare.assert_not_called()
        self.transport.P.project_identity.assert_called_once_with(str(self.root))
        derived=C.read(self.folder/'transport/run.json')
        self.assertEqual(derived['counts'],self.counts);self.assertEqual(derived['remage_wall_s'],7.6)
        self.assertFalse(derived['transport_reader_revision']['radiation_replayed'])

    def test_interrupted_metadata_apply_resumes_without_touching_raw_or_seals(self):
        self.prepare();self.derive();replace=R._replace;calls=[]
        def interrupt(source,target):
            calls.append(target)
            if len(calls)==3:raise OSError('synthetic metadata interruption')
            replace(source,target)
        with patch.object(R,'_replace',side_effect=interrupt):
            with self.assertRaisesRegex(OSError,'metadata interruption'):self.apply()
        self.assertEqual(self.apply()['status'],'complete')
        for entry in self.sealed:self.assertEqual(R.sealed_inventory(self.directory,entry['chunk']),entry)

    def test_changed_producer_raw_and_typed_physics_refused(self):
        path=self.root/'tools/gegi_campaign_response.py';original=path.read_bytes();path.write_bytes(b'CHANGED')
        with self.assertRaisesRegex(ValueError,'allowlist'):self.prepare()
        path.write_bytes(original);self.prepare()
        raw=self.folder/'transport/truth.lh5';original=raw.read_bytes();stamp=raw.stat().st_mtime_ns;raw.write_bytes(b'CHANGED')
        with self.assertRaisesRegex(ValueError,'bytes or timestamp'):self.derive()
        raw.write_bytes(original);C.os.utime(raw,ns=(stamp,stamp))
        changed=copy.deepcopy(self.transport.check.return_value);changed['runtime']['fixed']=1
        self.transport.check.return_value=changed
        with self.assertRaisesRegex(ValueError,'physics/runtime'):self.derive()
        self.transport.census.assert_not_called()
        request=C.read(self.output/'native-request.json');request['numerics']['field_policy']='fresh'
        C.write(self.output/'native-request.json',request)
        revised=C.read(self.output/'candidate-plan.json');revised['native_request']=R.binding(self.output/'native-request.json',self.root)
        with self.assertRaisesRegex(ValueError,'beyond source pins'):T._request_change(self.old,revised,self.root)

    def test_rehashed_derivation_or_changed_sealed_data_refused(self):
        self.prepare();self.derive();plan=C.read(self.output/'plan.json');record=T._record(plan,self.root)
        path=C.bound_file(self.root,record['derived_metadata']['transport/run.json']);value=C.read(path)
        value['seed']+=1;C.write(path,value);record['derived_metadata']['transport/run.json']=R.binding(path,self.root)
        body=C.read(C.bound_file(self.root,record['derivation']));body['metadata']=record['derived_metadata']
        C.write(self.output/'transport-derivation.json',body);record['derivation']=R.binding(self.output/'transport-derivation.json',self.root)
        with self.assertRaisesRegex(ValueError,'radiation execution'):T._derivation(record,self.root)
        file=C.chunk_path(self.directory,self.chunks[69])/'transport/geometry.gdml';file.write_bytes(b'CHANGED')
        with self.assertRaisesRegex(ValueError,'sealed chunk bytes'):R.verify_sealed_prefix(self.directory,record)
        self.assertEqual(C.sha(self.directory/'plan.json'),self.old_sha)


def load_tests(loader,tests,pattern):return loader.loadTestsFromTestCase(TransportRevisionTests)


if __name__=='__main__':unittest.main()
