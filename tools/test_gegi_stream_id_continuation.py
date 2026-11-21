"""Synthetic phase-1 stores; no live acquisition changes or physics."""
import copy
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import unittest
import zipfile
import zlib

import gegi_event_store as E
import gegi_native_continuation as C
import gegi_stream_id_continuation as S
import scenario_workflow as W
import test_gegi_native_continuation as native_fixtures


class StreamIdContinuation(unittest.TestCase):
    def setUp(self):
        # Reuse the accepted synthetic native-only proof/store fixture and its
        # original C.prepare/C.admit path, replacing placeholder hashes with
        # hashes of actual synthetic producer bytes for the phase-1 ZIP check.
        b=native_fixtures.ContinuationTests('runTest');b.setUp();self.addCleanup(b.doCleanups);self.b=b
        self.output=b.output
        with zipfile.ZipFile(b.package) as package:
            sources={ref[len('END2END-Ge-Student/'):]:package.read(ref) for ref in package.namelist()}
        self.sources=sources
        b.old_request['selection']={'primary_count':10,'threads':1}
        W.write(b.output/'native-request.json',b.old_request)
        b.old_identity['native_request_sha256']=W.sha(b.output/'native-request.json')
        b.new_request['selection']=copy.deepcopy(b.old_request['selection'])
        for ref in ('tools/gegi_event_store.py','tools/gegi_streaming_acquisition.py','tools/gegi_native_continuation.py'):
            sources[ref]=(ref+' phase1').encode()
        b.new_request['source_sha256']['tools/gegi_event_store.py']=hashlib.sha256(sources['tools/gegi_event_store.py']).hexdigest()
        W.write(b.request,b.new_request)
        b.new_identity['native_request_sha256']=W.sha(b.request)
        for ref in ('tools/gegi_streaming_acquisition.py','tools/gegi_native_continuation.py'):
            b.new_identity['source_sha256'][ref]=hashlib.sha256(sources[ref]).hexdigest()
        with closing(sqlite3.connect(b.database)) as db,db:
            db.execute('UPDATE metadata SET body=?',(W.encoded({'identity':b.old_identity}),))
            for sql in ('ALTER TABLE input_groups ADD COLUMN ordinal INTEGER',
                        'ALTER TABLE input_groups ADD COLUMN onset_ns REAL',
                        'ALTER TABLE input_groups ADD COLUMN last_ns REAL',
                        "ALTER TABLE input_groups ADD COLUMN status TEXT DEFAULT 'completed'",
                        'ALTER TABLE input_groups ADD COLUMN pending BLOB'):
                db.execute(sql)
            db.execute('UPDATE input_groups SET ordinal=1')
        with closing(sqlite3.connect(b.output/'native-scratch.sqlite')) as db,db:
            db.execute('UPDATE identity SET body=?',(E.encoded({'kind':E.KIND,'identity':{'request_sha256':b.old_identity['native_request_sha256']}}),))
        b.proof.update(original_request_sha256=b.old_identity['native_request_sha256'],new_request_sha256=W.sha(b.request))
        W.write(b.proof_path,b.proof)
        b.save_checkpoint({'source':'original'})
        C.prepare(b.output,b.new_identity,b.request,b.proof_path,b.package)
        self.old_identity=copy.deepcopy(b.new_identity)
        self.phase1_package=b.root/'phase1-producer.zip'
        with zipfile.ZipFile(self.phase1_package,'w') as package:
            for ref,body in sources.items():package.writestr('END2END-Ge-Student/'+ref,body)
        old_store=E.Store(b.output/'native-only/native-scratch.sqlite',{'request_sha256':b.new_identity['native_request_sha256']},create=True)
        old_store.close()
        W.write(self.output/'source-config.json',self.old_identity['source_config'])
        self.state={'source_checkpoint':{'rng':'unchanged','config_sha256':W.digest(self.old_identity['source_config'])},
                    'execution_provenance':{'active_producer_identity':self.old_identity,'native_processing_phase':1,
                        'continuation_receipt':{'path':'native-only-continuation.json','sha256':W.sha(self.output/'native-only-continuation.json')}}}
        b.save_checkpoint(self.state)
        self.group={'event_id':11,'group_id':0,'group_origin_time_ns':100.,'steps':[{'time_ns':100.,'energy_keV':1.}],
                    'parent_event_metadata':{'parent_decay_id':None,'initial_daughter_id':1}}
        self.group_body=E.encoded(self.group)
        self.input_sha=hashlib.sha256(self.group_body).hexdigest()
        with closing(sqlite3.connect(b.database)) as db,db:
            db.execute("INSERT INTO input_groups(parent,group_id,input_sha256,ordinal,onset_ns,last_ns,status,pending) VALUES (11,0,?,2,100,100,'pending',?)",
                       (self.input_sha,zlib.compress(self.group_body)))
        W.write(self.output/'progress.json',{'status':'failed','stage':S.FAILURE_STAGE,'resumable':True,'partial_data_retained':True})
        self.request=b.root/'phase2-request.json'
        self.new_request=copy.deepcopy(b.new_request);self.new_request['event_id_policy']=S.POLICY
        for ref in ('simulation/gegi_response.jl','simulation/gegi_campaign_response.jl','tools/gegi_campaign_response.py'):
            self.new_request['source_sha256'][ref]=hashlib.sha256((ref+' phase2').encode()).hexdigest()
        W.write(self.request,self.new_request)
        self.identity=copy.deepcopy(self.old_identity);self.identity['native_request_sha256']=W.sha(self.request)
        self.identity['source_sha256'][S.MODULE]=hashlib.sha256(b'new explicit repair guard').hexdigest()
        self.identity['source_sha256']['tools/gegi_streaming_acquisition.py']=hashlib.sha256(b'phase2 orchestration').hexdigest()

    def prepare(self):
        return S.prepare(self.output,self.identity,self.request,self.phase1_package)

    def transport_failure_fixture(self):
        self.prepare()
        state=copy.deepcopy(self.state)
        state['source_checkpoint'].update(next_block_index=2,rng='phase2 advanced')
        state['execution_provenance']={'active_producer_identity':self.identity,'native_processing_phase':2,
            'continuation_receipt':{'path':S.RECEIPT,'sha256':W.sha(self.output/S.RECEIPT)}}
        self.b.save_checkpoint(state)
        with closing(sqlite3.connect(self.b.database)) as db,db:
            db.execute("UPDATE input_groups SET status='completed',pending=NULL WHERE ordinal=2")
        native=E.Store(self.output/S.NAMESPACE/'native-scratch.sqlite',
                       {'request_sha256':self.identity['native_request_sha256']},create=True)
        native.close()
        spool=self.output/S.NAMESPACE/'native-spool';spool.mkdir()
        (spool/'existing-record.txt').write_bytes(b'phase2 original spool')
        W.write(self.output/'progress.json',{'status':'failed','stage':S.TRANSPORT_FAILURE_STAGE,
                                           'resumable':True,'partial_data_retained':True})
        sources=dict(self.sources)
        for ref in ('simulation/gegi_response.jl','simulation/gegi_campaign_response.jl','tools/gegi_campaign_response.py'):
            sources[ref]=(ref+' phase2').encode()
        sources[S.MODULE]=b'new explicit repair guard'
        sources['tools/gegi_streaming_acquisition.py']=b'phase2 orchestration'
        package=self.b.root/'phase2-producer.zip'
        with zipfile.ZipFile(package,'w') as archive:
            for ref,body in sources.items():archive.writestr('END2END-Ge-Student/'+ref,body)
        identity=copy.deepcopy(self.identity)
        identity['source_sha256'][S.MODULE]=hashlib.sha256(b'phase3 guard').hexdigest()
        identity['source_sha256']['transport/gegi_streaming_source.py']=hashlib.sha256(b'exact block-cap compatibility').hexdigest()
        return package,identity,state

    def test_transport_bridge_preserves_phase2_receipt_request_store_and_spool(self):
        package,identity,state=self.transport_failure_fixture()
        names=(S.RECEIPT,S.NAMESPACE+'/native-request.json',S.NAMESPACE+'/native-scratch.sqlite',
               S.NAMESPACE+'/native-spool/existing-record.txt','compton-candidates.sqlite','progress.json')
        before={name:(self.output/name).read_bytes() for name in names}
        receipt=S.prepare_transport(self.output,identity,package)
        self.assertEqual(before,{name:(self.output/name).read_bytes() for name in names})
        active=S.admit(self.output,identity)
        self.assertEqual(active['native_phase'],3)
        self.assertEqual(active['receipt_path'],S.TRANSPORT_RECEIPT)
        self.assertEqual(active['original_identity'],self.b.old_identity)
        self.assertEqual(Path(active['active_store']),self.output/S.NAMESPACE/'native-scratch.sqlite')
        self.assertEqual(Path(active['active_spool']),self.output/S.NAMESPACE/'native-spool')
        self.assertEqual(receipt['next_block_index'],2)
        with self.assertRaises(W.ControlError):S.prepare_transport(self.output,identity,package)

    def test_transport_admission_uses_bound_phase2_bridge_then_phase3_provenance(self):
        package,identity,state=self.transport_failure_fixture()
        S.prepare_transport(self.output,identity,package)
        state['source_checkpoint']['rng']='phase3 advanced'
        self.b.save_checkpoint(state)
        with self.assertRaisesRegex(W.ControlError,'phase/provenance'):S.admit(self.output,identity)
        state['execution_provenance']={'active_producer_identity':identity,'native_processing_phase':3,
            'continuation_receipt':{'path':S.TRANSPORT_RECEIPT,'sha256':W.sha(self.output/S.TRANSPORT_RECEIPT)}}
        self.b.save_checkpoint(state)
        self.assertEqual(S.admit(self.output,identity)['native_phase'],3)
        with (self.output/S.TRANSPORT_NAMESPACE/'bridge-checkpoint.json').open('ab') as handle:handle.write(b' ')
        with self.assertRaisesRegex(W.ControlError,'evidence changed'):S.admit(self.output,identity)

    def test_transport_repair_only_changes_two_hashes_and_requires_unstarted_block(self):
        package,identity,state=self.transport_failure_fixture()
        for edit in ('seed','native_request','worker_root','addition'):
            changed=copy.deepcopy(identity)
            if edit=='seed':changed['source_config']['seed']=10
            if edit=='native_request':changed['native_request_sha256']='d'*64
            if edit=='worker_root':changed['source_sha256']['tools/gegi_mixed_acquisition.py']='d'*64
            if edit=='addition':changed['source_sha256']['tools/new.py']='d'*64
            with self.subTest(edit=edit),self.assertRaises(W.ControlError):
                S._transport_contracts(self.identity,changed)
        with self.assertRaisesRegex(W.ControlError,'producer package mismatch'):
            S.prepare_transport(self.output,identity,self.phase1_package)
        self.assertFalse((self.output/S.TRANSPORT_NAMESPACE).exists())
        next_block=self.output/'transport/b000002';next_block.mkdir(parents=True)
        with self.assertRaisesRegex(W.ControlError,'before the next source block exists'):
            S.prepare_transport(self.output,identity,package)
        self.assertFalse((self.output/S.TRANSPORT_NAMESPACE).exists())

    def test_preserves_old_evidence_and_admits_same_original_ids(self):
        paths=[self.output/name for name in ('compton-candidates.sqlite','progress.json','native-only-continuation.json',
              'native-only/native-request.json','native-only/native-scratch.sqlite')]
        before={str(path):path.read_bytes() for path in paths}
        receipt=self.prepare();active=S.admit(self.output,self.identity)
        self.assertEqual({str(path):path.read_bytes() for path in paths},before)
        self.assertEqual(active['original_identity'],self.b.old_identity)
        self.assertEqual(active['native_phase'],2)
        self.assertEqual(active['receipt_path'],S.RECEIPT)
        self.assertEqual(Path(active['active_store']),self.output/S.NAMESPACE/'native-scratch.sqlite')
        self.assertEqual(Path(active['active_request']).read_bytes(),self.request.read_bytes())
        self.assertEqual((self.output/S.NAMESPACE/'failed-pending-group.json').read_bytes(),self.group_body)
        self.assertEqual(receipt['failed_input']['input_sha256'],self.input_sha)
        with self.assertRaises(W.ControlError):self.prepare()

    def test_checkpoint_resume_requires_phase2_provenance(self):
        self.prepare()
        state=copy.deepcopy(self.state);state['source_checkpoint']['rng']='advanced'
        self.b.save_checkpoint(state)
        with self.assertRaisesRegex(W.ControlError,'phase/provenance'):S.admit(self.output,self.identity)
        state['execution_provenance']={'active_producer_identity':self.identity,'native_processing_phase':2,
            'continuation_receipt':{'path':S.RECEIPT,'sha256':W.sha(self.output/S.RECEIPT)}}
        self.b.save_checkpoint(state)
        with closing(sqlite3.connect(self.b.database)) as db,db:
            db.execute("UPDATE input_groups SET status='completed',pending=NULL WHERE ordinal=2")
        self.assertEqual(S.admit(self.output,self.identity)['native_phase'],2)

    def test_physics_nominal_count_and_other_producers_cannot_change(self):
        for edit in ('seed','count','numerics','root','worker','addition','policy'):
            identity,new=copy.deepcopy(self.identity),copy.deepcopy(self.new_request)
            if edit=='seed':identity['source_config']['seed']=10
            if edit=='count':new['selection']['primary_count']=12
            if edit=='numerics':new['numerics']['native_seed']=10
            if edit=='root':identity['source_sha256']['tools/gegi_streaming_readout.py']='d'*64
            if edit=='worker':new['source_sha256']['models/GeGI_3D.yaml']='d'*64
            if edit=='addition':identity['source_sha256']['tools/other.py']='d'*64
            if edit=='policy':new['event_id_policy']='other'
            with self.subTest(edit=edit),self.assertRaises(W.ControlError):
                S._contracts(self.old_identity,identity,self.b.new_request,new)

    def test_requires_exact_failure_and_crossing_next_pending_id(self):
        for progress in ({'status':'running'},{'status':'failed','stage':'different failure','resumable':True,'partial_data_retained':True}):
            W.write(self.output/'progress.json',progress)
            with self.assertRaisesRegex(W.ControlError,'original-ID worker failure'):self.prepare()
        W.write(self.output/'progress.json',{'status':'failed','stage':S.FAILURE_STAGE,'resumable':True,'partial_data_retained':True})
        with closing(sqlite3.connect(self.b.database)) as db,db:
            db.execute('UPDATE input_groups SET parent=9 WHERE ordinal=2')
        with self.assertRaisesRegex(W.ControlError,'finite-ID bound'):self.prepare()
        self.assertFalse((self.output/S.NAMESPACE).exists())

    def test_old_bound_boundary_is_repairable_and_pending_digest_is_strict(self):
        self.group['event_id']=10;body=E.encoded(self.group)
        with closing(sqlite3.connect(self.b.database)) as db,db:
            db.execute('UPDATE input_groups SET parent=10,pending=?,input_sha256=? WHERE ordinal=2',
                       (zlib.compress(body),hashlib.sha256(body).hexdigest()))
        self.assertEqual(self.prepare()['failed_input']['event_id'],10)
        self.assertEqual(S.admit(self.output,self.identity)['native_phase'],2)
        with closing(sqlite3.connect(self.b.database)) as db,db:
            db.execute("UPDATE input_groups SET input_sha256='changed' WHERE ordinal=2")
        with self.assertRaisesRegex(W.ControlError,'ledger association'):S.admit(self.output,self.identity)

    def test_package_checkpoint_and_phase1_provenance_are_required(self):
        with zipfile.ZipFile(self.phase1_package,'a') as package:
            package.writestr('END2END-Ge-Student/tools/gegi_native_continuation.py',b'wrong producer')
        with self.assertRaisesRegex(W.ControlError,'producer package mismatch'):self.prepare()
        self.assertFalse((self.output/S.NAMESPACE).exists())
        state=copy.deepcopy(self.state);state['execution_provenance']['native_processing_phase']=0
        self.b.save_checkpoint(state)
        with self.assertRaisesRegex(W.ControlError,'phase/provenance'):self.prepare()
        with closing(sqlite3.connect(self.b.database)) as db,db:
            db.execute("UPDATE checkpoint SET checkpoint_sha256='changed'")
        with self.assertRaises(W.ControlError):self.prepare()

    def test_no_receipt_and_preserved_failure_tamper(self):
        self.assertIsNone(S.admit(self.output,self.identity))
        self.assertIsNone(S.admit(Path('not-an-existing-run-outside-project'),self.identity))
        self.prepare()
        with (self.output/S.NAMESPACE/'failure-progress.json').open('ab') as handle:handle.write(b' ')
        with self.assertRaisesRegex(W.ControlError,'evidence changed'):S.admit(self.output,self.identity)


if __name__ == '__main__':unittest.main()
