"""New-round software fixtures and separately opt-in, source-frozen host harness.

Default mode mocks native AND electronics math. It never starts Julia. Host
mode is coordinator-only after the writer exits; all attempts remain evidence.
"""
import argparse
import ast
import copy
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import unittest
from unittest import mock

import charge_check as C
import group_checkpoints as G
import native_group_checkpoints as N
import native_readout_integration as I
import replay_readout as R
import test_native_group_checkpoints as NF
import test_replay_readout as RF

ROOT=I.ROOT
HOME=ROOT/'.local/native-readout-integration-v1/implementation'
CLOSURE_HOME=ROOT/'.local/m5-close-v1/implementation'
EVIDENCE=None
FREEZE_SOURCES=tuple(sorted(set((*I.SOURCES,'tools/test_native_readout_integration.py',
    'tools/test_native_group_checkpoints.py','tools/test_replay_readout.py','tools/test_charge_check.py',
    '.local/native-readout-integration-v1/implementation/run-host.ps1','tools/NATIVE_READOUT_INTEGRATION.md',
    '.gitignore','.gitattributes'))))
BASE='.local/o'
HOST_FREEZE=None


def freeze_sources(home):
    if home.is_relative_to(CLOSURE_HOME):
        # Documentation is tested separately; it cannot invalidate real science.
        return tuple(sorted(set(FREEZE_SOURCES)-{
            '.local/native-readout-integration-v1/implementation/run-host.ps1',
            'tools/NATIVE_READOUT_INTEGRATION.md'} | {
            '.local/m5-close-v1/implementation/run-host.ps1'}))
    return FREEZE_SOURCES


def runtime_locations(home):
    return '.local/m5-close-v1/runtime-locations.json' if home.is_relative_to(CLOSURE_HOME) else '.local/native-readout-integration-v1/runtime-locations.json'


def public_command(args):
    # PowerShell owns batch quoting at the project root, including spaces.
    quoted=['\''+str(value).replace("'","''")+'\'' for value in [ROOT/'Run.cmd',*args]]
    return ['powershell.exe','-NoProfile','-Command','& '+' '.join(quoted)+'; exit $LASTEXITCODE']

snapshot=NF.snapshot
read=NF.read
save=NF.save


def recorded_cache_fixture(root,settings,events=None):
    """Written synthetic provenance for the real integration/legacy plan gates."""
    def put(path,value):
        path.parent.mkdir(parents=True,exist_ok=True);NF.replace_json(path,value)
    p=NF.plan_fixture(root,'abort')
    put(root/'models/catalog.json',dict(detectors=[dict(id='AK02',readout_contact_id=1)]))
    (root/'models/AK02.yaml').write_bytes(b'MOCK MODEL, never loaded\n')
    prepared=dict(p['prepared'],model_sha256=G.digest_bytes((root/'models/AK02.yaml').read_bytes()))
    put(root/'.local/cs137-1m/inputs/AK02/prepared.json',prepared)
    cache=N.BATCH+'/cache.bin';(root/cache).parent.mkdir(parents=True,exist_ok=True)
    (root/cache).write_bytes(b'MOCK FIELD CACHE, never loaded\n')
    contract=dict(kind='selected_native_hdf5_pilot_v1',status='complete',model_id='AK02',source_sha256={},
        input_sha256={'fixture-input.bin':p['cache_sha256']},prepared=prepared,model_sha256=prepared['model_sha256'],
        events=p['events'] if events is None else events,input_population_reference=p['population_reference'],seed_rule=p['seed_rule'])
    put(root/N.CONTRACT,contract)
    put(root/N.EXPORT,dict(kind='selected_native_hdf5_pilot_v1',status='exported_checked_inputs',
        contracts={'AK02':dict(file='AK02.json',sha256=G.digest_bytes((root/N.CONTRACT).read_bytes()))},
        source_sha256=contract['source_sha256'],input_sha256=contract['input_sha256']))
    put(root/(N.BATCH+'/config.json'),dict(kind='native_checkpoint_batch_v1',settings=settings,
        models={'AK02':dict(prepared=prepared,cache_file='cache.bin',cache_sha256=G.digest_bytes((root/cache).read_bytes()),expected_field_fingerprint={})},
        source_sha256={n:G.digest_bytes((root/n).read_bytes()) for n in N.NUMERICAL},
        expected_environment=dict(environment_manifest_sha256=G.digest_bytes((root/'simulation/Manifest.toml').read_bytes()))))
    (root/(N.BATCH+'/config.sha256')).write_bytes((G.digest_bytes((root/(N.BATCH+'/config.json')).read_bytes())+'\n').encode())


@contextmanager
def lease_writes(dest):
    """Observe real fixture writes and independently contend for the Windows lease."""
    events=[];acquired=[False];lock=C.existing_lock;write=G.write_bytes
    @contextmanager
    def tracked(reader,relative):
        with lock(reader,relative):
            acquired[0]=True;events.append(dict(event='lease_acquired'))
            try:yield
            finally:events.append(dict(event='lease_released'))
    def observed(path,data):
        if acquired[0] and path.is_relative_to(dest):
            held=False
            try:
                with lock(C.Reader(dest),'run.lock'):pass
            except C.Rejected as error:held=error.code=='held_or_inaccessible_lock'
            item=dict(event='write',file=path.relative_to(dest).as_posix(),lease_held=held)
            if path.name=='failure.json' or path.name.startswith('run.json.pending-'):item['record']=C.decode(data.decode())
            events.append(item)
        return write(path,data)
    with mock.patch.object(C,'existing_lock',tracked),mock.patch.object(G,'write_bytes',observed):yield events


class Fixture:
    def __init__(self,root):
        self.root=root;self.calls=[];self.native_failure=None;self.native_exception=None
        self.after_native=False;self.after_calibration=False;self.after_electronics=False;self.bad_event=None
        self.nr=None;self.rr=None;self.endpoint_mix=False

    def load(self,reader,primary_ids=None):
        plan=NF.plan_fixture(self.root,'record' if self.native_failure else 'abort')
        if primary_ids is not None:
            ids=N.parse_primary_ids(primary_ids)
            plan['events']=[next(e for e in plan['events'] if e['event_id']==eid) for eid in ids]
            plan.update(selected_primary_ids=ids,primary_selection_mode='explicit',groups=N.expected_groups(plan['events'],plan['prepared']))
            plan['selected_census']=dict(initial_primaries=len(ids),zero_ge_primaries=sum(e['zero_ge'] for e in plan['events']),
                nonzero_primaries=sum(not e['zero_ge'] for e in plan['events']),groups=len(plan['groups']))
        plan['source_sha256']={n:reader.digest(n) for n in I.SOURCES}
        reader.digest('fixture-plan.json');reader.digest('fixture-input.bin',plan['cache_sha256'])
        profile=reader.json(I.PROFILE);reader.digest(I.PROFILE,C.ES_DEFAULTS[I.PROFILE])
        config=R.expected_config(reader,profile,len(plan['events']))
        d=dict(model='AK02',profile=profile,config=config,dt=2,eion=2.95,primary_count=len(plan['events']),
            model_sha256=plan['model_sha256'],readout_contact_id=plan['readout_contact_id'])
        return plan,d,dict(mocked_profile_dispatch=True,profile=profile,configuration=dict(config,expected_primary_count=None))

    def native_runtime(self):
        r=NF.fixture_runtime(self.root);r.update(executable=str(self.root/'fixture-runtime.bin'),launcher_executable=str(self.root/'fixture-runtime.bin'))
        r['launcher_sha256']=r['executable_sha256']=G.digest_bytes((self.root/'fixture-runtime.bin').read_bytes());return r

    def native_probe(self,reader,plan):
        self.calls.append('MOCK_NATIVE_PROBE');return self.nr or self.native_runtime(),dict(mocked=True)

    def readout_probe(self,reader):
        self.calls.append('MOCK_READOUT_PROBE');r=self.native_runtime()
        return self.rr or dict(executable=r['executable'],launcher_executable=r['launcher_executable'],launcher_sha256=r['launcher_sha256'],
            executable_sha256=r['executable_sha256'],mocked_readout=True),dict(mocked=True)

    def native_session(self,reader,dest,m,groups,attempt,callback,**kwargs):
        for g in groups:
            if self.native_exception:raise self.native_exception
            self.calls.append(['MOCK_EXECUTED_NATIVE',g['key']])
            stage=attempt/('charge-'+g['key']);stage.mkdir()
            record=NF.synthetic_record(m['plan'],g,m['runtime'],self.native_failure)
            if self.endpoint_mix:
                endpoints=record['native']['steps'][0]['endpoints']
                endpoints[0].update(samples=5001,step_limit_reached=True,status='step_limit')
                endpoints[1].update(contact_ids=[1],status='contact')
                record['transport_flags'].update(step_limits=1,geometric_contacts=1,stopped_without_contact=len(endpoints)-2)
            G.write_json(stage/'charge.json',record)
            event=dict(kind='group_ready',key=g['key'],directory=stage.name)
            if self.bad_event:event.update(self.bad_event)
            callback(event)
            if self.after_native:raise RuntimeError('MOCK interruption after charge commit before ACK')

    def electronics_session(self,root,dest,m,mh,runtime,groups,attempt,callback):
        # Reuse the prior source-only synthetic math fixture; never claim these
        # fabricated values establish Julia loading or numerical acceptance.
        scratch=attempt/'mock';scratch.mkdir();folder=scratch/'inputs/AK02';folder.mkdir(parents=True)
        G.write_bytes(folder/'scalars.jsonl',b''.join(G.encoded(r) for r in I.ledger(dest,m['plan'])))
        data=','.join(C.SIGNAL_COLUMNS)+'\n'
        for g in m['plan']['groups']:
            data+=''.join((dest/'charge'/g['key']/'signals.csv').read_text().splitlines(keepends=True)[1:])
        G.write_bytes(folder/'signals.csv',data.encode())
        report=RF.tiny_worker(scratch,{'detectors':m['detectors']});d=m['detectors'][0]
        if not (dest/'calibration/AK02').exists():
            self.calls.append(['MOCK_EXECUTED_CALIBRATION','AK02']);stage=attempt/'calibration-AK02';stage.mkdir()
            cal=dict(kind='saved_charge_calibration_v1',model='AK02',config=d['config'],runtime=G.raw_runtime(runtime),
                calibration=report['detectors']['AK02']['calibration'],calibration_seconds=0.)
            G.write_json(stage/'calibration.json',cal)
            callback(dict(kind='group_ready',phase='calibration',key='AK02',directory=stage.name))
            if self.after_calibration:raise RuntimeError('MOCK interruption after calibration commit before ACK')
        for g in groups:
            self.calls.append(['MOCK_EXECUTED_ELECTRONICS',g['key']]);stage=attempt/('electronics-'+g['key']);stage.mkdir()
            rec=next(r for r in C.Reader(scratch).jsonl('worker/AK02/scalars.jsonl') if r['record_kind']=='pulse' and r['event_id']==g['identity']['event_id'])
            traces=[r for r in C.Reader(scratch).jsonl('worker/AK02/traces.jsonl') if r['event_id']==rec['event_id']]
            counts=dict.fromkeys(R.COUNT_FIELDS,0);counts.update(groups=1,rejected=1)
            if rec['status']=='native_transport_failed':counts['native_failed_groups']=1
            else:counts.update(readout_rejected=1,native_charge_samples=3,analog_samples=50000)
            cal=read(dest/'calibration/AK02/calibration.json')
            G.write_json(stage/'result.json',dict(kind='saved_charge_electronics_group_v1',key=g['key'],runtime=G.raw_runtime(runtime),config=d['config'],
                calibration_sha256=G.digest_bytes(G.encoded(cal)),counts=counts,electronics_seconds=0.))
            G.write_bytes(stage/'scalars.jsonl',G.encoded(rec));G.write_bytes(stage/'traces.jsonl',b''.join(G.encoded(r) for r in traces))
            callback(dict(kind='group_ready',phase='electronics',key=g['key'],directory=stage.name))
            if self.after_electronics:raise RuntimeError('MOCK interruption after electronic commit before ACK')

    def run(self,name='new',**kwargs):
        with mock.patch.object(I,'BASE',BASE),mock.patch.object(I,'load_plan',side_effect=self.load),mock.patch.object(I,'probe_readout',side_effect=self.readout_probe),\
            mock.patch.object(N,'probe_runtime',side_effect=self.native_probe),mock.patch.object(N,'run_session',side_effect=self.native_session),\
            mock.patch.object(G,'run_session',side_effect=self.electronics_session):
            return I.integrate(self.root,name,**kwargs)


class Tests(unittest.TestCase):
    def setUp(self):
        self.home=EVIDENCE/('t-'+G.digest_bytes(self.id().encode())[:8]);self.root=self.home/'r';NF.make_fixture(self.root)
        for n in I.SOURCES:
            p=self.root/n;p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/n,p)
        G.write_bytes(self.root/'fixture-runtime.bin',b'MOCK runtime, never executable\n')
        self.f=Fixture(self.root);self.dest=self.root/BASE/'new';self.original=snapshot(self.root/'simulation')

    def tearDown(self):self.assertEqual(snapshot(self.root/'simulation'),self.original)

    def paused(self):
        r=self.f.run(stop_after_groups=1);self.assertEqual(r['status'],'paused',r);return r

    def first(self,phase='charge'):return next((self.dest/phase).iterdir())

    def refusal(self):
        before=snapshot(self.dest);self.f.calls=[];r=self.f.run(resume=True)
        self.assertEqual(r['status'],'blocked',r);self.assertFalse(r['verification_final']);self.assertEqual(self.f.calls,[])
        self.assertEqual(snapshot(self.dest),before);return r

    def retain(self,path):
        folder=self.dest/'attempts'/('retained-'+uuid_suffix());folder.mkdir()
        path.rename(folder/path.name)

    def remove_commit(self,phase):
        p=self.first(phase);self.retain(G.witness_path(p));self.retain(p)

    def cache_gate(self,settings,valid=False):
        recorded_cache_fixture(self.root,settings)
        profile=C.Reader(self.root).json(I.PROFILE);config=R.expected_config(C.Reader(self.root),profile,3)
        selection=dict(mocked_profile_dispatch=True,profile=profile,configuration=dict(config,expected_primary_count=None))
        def probe(reader,plan):
            self.f.calls.append('MOCK_NATIVE_PROBE');raise RuntimeError('MOCK intercepted probe; no runtime started')
        before=snapshot(self.root)
        with mock.patch.object(I,'BASE',BASE),mock.patch.object(R,'resolve_profile',return_value=(selection,None)),\
            mock.patch.object(N,'probe_runtime',side_effect=probe),mock.patch.object(I,'probe_readout',side_effect=self.f.readout_probe),\
            mock.patch.object(N,'run_session',side_effect=self.f.native_session),mock.patch.object(G,'run_session',side_effect=self.f.electronics_session):
            planned=I.integrate(self.root,'new',dry_run=True);started=I.integrate(self.root,'new')
        save(self.home/'cache-gate.json',dict(mocked_runtime=True,settings=settings,planned=planned,started=started,actual_calls=self.f.calls,
            rehashed_config_sha256=G.digest_bytes((self.root/(N.BATCH+'/config.json')).read_bytes())))
        self.assertEqual(planned['status'],'planned' if valid else 'blocked',planned)
        self.assertEqual(started['status'],'blocked',started)
        self.assertEqual(self.f.calls,['MOCK_NATIVE_PROBE'] if valid else [])
        self.assertEqual(started['scientific_workers_launched'],0)
        self.assertEqual(snapshot(self.root),before);self.assertFalse(self.dest.exists())
        if not valid:
            self.assertEqual(planned['findings'],started['findings'])
            self.assertIn('exact recorded cache settings',started['findings'][0]['detail'])

    def test_recorded_cache_exact_settings_valid(self):
        self.cache_gate(dict(drift_cap_ns=10000,drift_dt_ns=2,parcels=16,seed_family=2609261,temperature_K=77),valid=True)
    def test_recorded_cache_rehashed_missing_setting_refused(self):
        self.cache_gate(dict(drift_dt_ns=2,parcels=16,seed_family=2609261,temperature_K=77))
    def test_recorded_cache_rehashed_empty_settings_refused(self):self.cache_gate({})
    def test_recorded_cache_rehashed_extra_setting_refused(self):
        self.cache_gate(dict(drift_cap_ns=10000,drift_dt_ns=2,parcels=16,seed_family=2609261,temperature_K=77,diffusion=True))
    def test_recorded_cache_rehashed_incorrect_value_refused(self):
        self.cache_gate(dict(drift_cap_ns=9999,drift_dt_ns=2,parcels=16,seed_family=2609261,temperature_K=77))
    def test_recorded_cache_rehashed_incorrect_type_refused(self):
        self.cache_gate(dict(drift_cap_ns=10000,drift_dt_ns=2.,parcels=16,seed_family=2609261,temperature_K=77))

    def failure_under_lease(self,error,**kwargs):
        with lease_writes(self.dest) as events:r=self.f.run(**kwargs)
        save(self.home/'lease-publication.json',dict(actual_host=False,actual_calls=self.f.calls,result=r,events=events))
        self.assertEqual(r['status'],'failed',r);self.assertFalse((self.dest/'COMPLETE.json').exists())
        failure=read(self.dest/next(e['file'] for e in events if e.get('file','').endswith('/failure.json')))
        self.assertEqual(failure['finding'],C.finding(error));self.assertEqual(failure['result'],r)
        self.assertEqual(read(self.dest/'run.json'),r)
        writes=[e for e in events if e['event']=='write']
        self.assertTrue(writes);self.assertTrue(all(e['lease_held'] for e in writes),events)
        failed=[e for e in writes if e.get('record',{}).get('status')=='failed']
        self.assertEqual(len(failed),1);self.assertEqual(failed[0]['record'],r)
        self.assertTrue(writes[-1]['file'].endswith('/failure.json'))
        self.assertEqual(events[-1]['event'],'lease_released')
        return r

    def test_unexpected_native_failure_receipts_under_lease(self):
        error=RuntimeError('MOCK unexpected native worker exception');self.f.native_exception=error;self.failure_under_lease(error)
    def test_strict_native_error_failure_receipts_under_lease(self):
        error=C.Rejected('child_failed','ArgumentError: Noncontact endpoint outside crystal')
        self.f.native_exception=error;self.failure_under_lease(error)
    def test_readout_failure_receipts_under_lease_preserve_charge(self):
        self.f.after_native=True;self.f.run();self.f.after_native=False
        error=RuntimeError('MOCK unexpected readout worker exception')
        def fail(*args,**kwargs):raise error
        self.f.electronics_session=fail;protected=durable(self.dest)
        self.failure_under_lease(error,resume=True);assert_preserved(self.dest,protected)
    def test_post_calibration_failure_receipts_under_lease(self):
        self.f.after_calibration=True
        self.failure_under_lease(RuntimeError('MOCK interruption after calibration commit before ACK'))
    def test_post_electronics_failure_receipts_under_lease(self):
        self.f.after_electronics=True
        self.failure_under_lease(RuntimeError('MOCK interruption after electronic commit before ACK'))
    def test_preinit_probe_failure_read_only(self):
        before=snapshot(self.root)
        def fail(reader,plan):self.f.calls.append('MOCK_NATIVE_PROBE');raise RuntimeError('MOCK pre-init probe failure')
        self.f.native_probe=fail;r=self.f.run()
        save(self.home/'preinit-refusal.json',dict(result=r,actual_calls=self.f.calls))
        self.assertEqual(r['status'],'blocked');self.assertEqual(self.f.calls,['MOCK_NATIVE_PROBE'])
        self.assertEqual(r['findings'],[C.finding(RuntimeError('MOCK pre-init probe failure'))])
        self.assertEqual(snapshot(self.root),before);self.assertFalse(self.dest.exists())

    def test_new_charge_readout_and_original_ids(self):
        r=self.f.run();self.assertEqual(r['status'],'completed',r)
        rows=list(C.Reader(self.dest).jsonl('worker/AK02/scalars.jsonl'))
        self.assertEqual([x['event_id'] for x in rows if x['record_kind']=='decay'],[0,2594,3950])
        self.assertEqual(r['detectors']['AK02']['counts']['zero_deposit_primaries'],1)
        for row in rows:
            if row['record_kind']=='pulse':
                self.assertEqual(row['final_induced_keV'],-2);self.assertTrue(row['readout']['negative_input'])
                self.assertEqual(row['transport_flags']['stopped_without_contact'],32)
                self.assertEqual(len(row['native_steps'][0]['endpoints']),32)

    def test_charge_crash_then_electronics_pause_then_resume_exact(self):
        self.assertEqual(self.f.run(name='ref')['status'],'completed')
        self.f.after_native=True;self.assertEqual(self.f.run()['status'],'failed');frozen=snapshot(self.dest/'charge')
        self.f.after_native=False;self.f.calls=[];r=self.f.run(resume=True,stop_after_groups=1);self.assertEqual(r['status'],'paused',r)
        self.assertEqual(len([c for c in self.f.calls if isinstance(c,list) and c[0]=='MOCK_EXECUTED_NATIVE']),1)
        self.assertTrue(all(snapshot(self.dest/'charge')[n]==v for n,v in frozen.items()))
        protected=durable(self.dest);self.f.calls=[];r=self.f.run(resume=True);self.assertEqual(r['status'],'completed',r)
        self.assertFalse(any(c=='MOCK_NATIVE_PROBE' or isinstance(c,list) and c[0] in ('MOCK_EXECUTED_NATIVE','MOCK_EXECUTED_CALIBRATION') for c in self.f.calls))
        assert_preserved(self.dest,protected)
        for n in ('scalars.jsonl','traces.jsonl'):self.assertEqual((self.dest/'worker/AK02'/n).read_bytes(),(self.root/BASE/'ref/worker/AK02'/n).read_bytes())

    def test_calibration_crash_reuses_all_charge_and_calibration(self):
        self.f.after_calibration=True;self.assertEqual(self.f.run()['status'],'failed');protected=durable(self.dest)
        self.f.after_calibration=False;self.f.calls=[];r=self.f.run(resume=True);self.assertEqual(r['status'],'completed',r)
        self.assertFalse(any(c=='MOCK_NATIVE_PROBE' or isinstance(c,list) and c[0]!='MOCK_EXECUTED_ELECTRONICS' for c in self.f.calls));assert_preserved(self.dest,protected)

    def test_forward_charge_commit_ahead_of_progress(self):
        self.f.after_native=True;self.f.run();m=read(self.dest/'manifest.json');g=m['plan']['groups'][1]
        stage=self.dest/'attempts/forward';stage.mkdir();record=NF.synthetic_record(m['plan'],g,m['native_runtime']);G.write_json(stage/'charge.json',record)
        _,files=I.adapter(record,m['plan'],g)
        for n,b in files.items():G.write_bytes(stage/n,b)
        G.commit(stage,self.dest/'charge'/g['key'],G.binding(G.digest_bytes((self.dest/'manifest.json').read_bytes()),'charge',g['key']))
        self.f.after_native=False;self.f.calls=[];r=self.f.run(resume=True);self.assertEqual(r['status'],'completed',r)
        self.assertFalse(any(c=='MOCK_NATIVE_PROBE' or isinstance(c,list) and c[0]=='MOCK_EXECUTED_NATIVE' for c in self.f.calls))

    def test_forward_calibration_and_electronics_commits(self):
        self.paused();p=self.dest/'run.json';r=read(p)
        for phase in ('calibration','electronics'):r['stages'][phase].update(completed_keys=[],completed_count=0)
        NF.replace_json(p,r);self.f.calls=[];r=self.f.run(resume=True);self.assertEqual(r['status'],'completed',r)
        self.assertEqual([c[0] for c in self.f.calls if isinstance(c,list)],['MOCK_EXECUTED_ELECTRONICS'])

    def test_missing_progress_refused(self):self.paused();self.retain(self.dest/'run.json');self.refusal()
    def test_corrupt_progress_refused(self):self.paused();(self.dest/'run.json').write_bytes(b'{');self.refusal()
    def test_stage_identity_schema_required(self):
        self.paused();p=self.dest/'run.json';r=read(p);r['stages'].pop('calibration');NF.replace_json(p,r);self.refusal()
    def test_stage_completed_identity_required(self):
        self.paused();p=self.dest/'run.json';r=read(p);r['stages']['charge'].pop('completed_keys');NF.replace_json(p,r);self.refusal()
    def test_progress_manifest_identity_refused(self):
        self.paused();p=self.dest/'run.json';r=read(p);r['manifest_sha256']='a'*64;NF.replace_json(p,r);self.refusal()
    def test_progress_duplicate_identity_refused(self):
        self.paused();p=self.dest/'run.json';r=read(p);r['stages']['charge']['completed_keys']*=2;NF.replace_json(p,r);self.refusal()
    def test_progress_count_identity_mismatch(self):
        self.paused();p=self.dest/'run.json';r=read(p);r['stages']['electronics']['completed_count']=2;NF.replace_json(p,r);self.refusal()
    def test_progress_expected_identity_mismatch(self):
        self.paused();p=self.dest/'run.json';r=read(p);r['stages']['charge']['expected_keys'][0]='bad';NF.replace_json(p,r);self.refusal()
    def test_missing_reported_charge_refused(self):self.paused();self.remove_commit('charge');self.refusal()
    def test_missing_reported_calibration_refused(self):self.paused();self.remove_commit('calibration');self.refusal()
    def test_missing_reported_electronics_refused(self):self.paused();self.remove_commit('electronics');self.refusal()
    def test_corrupt_charge_refused(self):self.paused();(self.first()/'charge.json').write_bytes(b'{}');self.refusal()
    def test_corrupt_calibration_refused(self):self.paused();(self.first('calibration')/'calibration.json').write_bytes(b'{}');self.refusal()
    def test_corrupt_electronics_refused(self):self.paused();(self.first('electronics')/'result.json').write_bytes(b'{}');self.refusal()
    def test_missing_commit_receipt_refused(self):self.paused();self.retain(self.first()/'COMMIT.json');self.refusal()
    def test_missing_commit_witness_refused(self):self.paused();self.retain(G.witness_path(self.first()));self.refusal()
    def test_source_change_refused(self):
        self.paused();p=self.root/'tools/native_readout_integration.py';p.write_bytes(p.read_bytes()+b'\n');self.refusal()
    def test_cache_change_refused(self):self.paused();(self.root/'fixture-input.bin').write_bytes(b'changed');self.refusal()
    def test_saved_runtime_bytes_change_refused(self):self.paused();(self.root/'fixture-runtime.bin').write_bytes(b'changed');self.refusal()
    def test_frozen_profile_change_refused(self):
        self.paused();p=self.root/I.PROFILE;original=p.read_bytes();stamp=p.stat();r=read(p);r['settings']['gain']=21;NF.replace_json(p,r)
        try:self.refusal()
        finally:
            p.write_bytes(original);os.utime(p,ns=(stamp.st_atime_ns,stamp.st_mtime_ns)) # NEW fixture only
    def test_rehashed_config_change_independent_gate(self):
        self.f.native_exception=RuntimeError('MOCK before native call');self.f.run();m=read(self.dest/'manifest.json');m['detectors'][0]['config']['gain']=21
        NF.replace_json(self.dest/'manifest.json',m);NF.replace_json(self.dest/'inputs/effective-config.json',m['detectors'][0]['config'])
        initial=read(self.dest/'INITIAL.json');out=C.Reader(self.dest);initial['manifest']=G.stamps(out,['manifest.json'])['manifest.json']
        initial['inputs']=G.stamps(out,['inputs/'+n for n in G.inventory(self.dest/'inputs')]);NF.replace_json(self.dest/'INITIAL.json',initial)
        p=self.dest/'run.json';r=read(p);r['manifest_sha256']=out.digest('manifest.json');NF.replace_json(p,r);self.refusal()
    def test_settings_change_refused(self):
        self.paused();p=self.root/'fixture-plan.json';r=read(p);r['settings']['parcels']=8;NF.replace_json(p,r);self.refusal()
    def test_completed_noop_no_probes_or_writes(self):
        self.assertEqual(self.f.run()['status'],'completed');before=snapshot(self.dest);self.f.calls=[]
        with mock.patch.dict(os.environ,JULIA_EXE='INVALID'):
            r=self.f.run(resume=True);self.assertTrue(r['idempotent']);self.assertEqual(self.f.calls,[]);self.assertEqual(snapshot(self.dest),before)
    def test_saved_dryrun_no_probes_or_writes(self):
        self.paused();before=snapshot(self.dest);self.f.calls=[];r=self.f.run(resume=True,dry_run=True)
        self.assertEqual(r['status'],'paused');self.assertEqual(self.f.calls,[]);self.assertEqual(snapshot(self.dest),before)
    def test_new_dryrun_no_probes_or_writes(self):
        before=snapshot(self.root);r=self.f.run(dry_run=True);self.assertEqual(r['status'],'planned');self.assertEqual(self.f.calls,[]);self.assertEqual(snapshot(self.root),before)
    def test_failure_nulls_full_truth_ledger(self):
        self.f.native_failure=dict(type='ArgumentError',message='Noncontact endpoint outside crystal',exact_error='ArgumentError: Noncontact endpoint outside crystal',stage='NativeLiExample.native_event')
        r=self.f.run();self.assertEqual(r['status'],'completed_with_native_failures',r)
        rows=list(C.Reader(self.dest).jsonl('worker/AK02/scalars.jsonl'));self.assertEqual(len(rows),5)
        for row in rows:
            if row['record_kind']=='pulse':
                for k in ('readout','native_steps','transport_flags','charge_end_ns','final_induced_keV'):self.assertIsNone(row[k])
                self.assertEqual(len(row['event']['steps']),1);self.assertFalse(row['accepted'])
        self.assertEqual((self.dest/'worker/AK02/traces.jsonl').read_bytes(),b'')
    def test_unexpected_native_error_strict(self):
        self.f.native_exception=RuntimeError('unexpected');r=self.f.run();self.assertEqual(r['status'],'failed');self.assertFalse((self.dest/'COMPLETE.json').exists())
    def test_contact_and_cap_flags_survive_readout(self):
        self.f.endpoint_mix=True;r=self.f.run();self.assertEqual(r['status'],'completed',r)
        for row in C.Reader(self.dest).jsonl('worker/AK02/scalars.jsonl'):
            if row['record_kind']=='pulse':
                self.assertEqual(row['transport_flags'],dict(carrier_parcels=32,geometric_contacts=1,step_limits=1,stopped_without_contact=30))
                self.assertTrue(row['native_steps'][0]['endpoints'][0]['step_limit_reached'])
                self.assertEqual(row['native_steps'][0]['endpoints'][1]['contact_ids'],[1])
    def rehash_stage(self,p):
        receipt=read(p/'COMMIT.json');receipt['artifacts']=G.stamps(C.Reader(p),list(receipt['artifacts']));NF.replace_json(p/'COMMIT.json',receipt)
        witness=G.witness_path(p);data=read(witness);data['commit']=G.stamps(C.Reader(p),['COMMIT.json'])['COMMIT.json'];NF.replace_json(witness,data)
    def test_rehashed_charge_endpoint_mismatch_refused(self):
        self.paused();p=self.first();r=read(p/'charge.json');r['native']['signal'][-1]=0;NF.replace_json(p/'charge.json',r);self.rehash_stage(p);self.refusal()
    def test_rehashed_signed_bridge_mismatch_refused(self):
        self.paused();p=self.first();file=p/'signals.csv';file.write_bytes(file.read_bytes().replace(b'-2.0',b'0.0'));self.rehash_stage(p);self.refusal()
    def test_unexpected_duplicate_group_notification_refused(self):
        self.f.bad_event={'key':'AK02-e3950-d3950-g0'};r=self.f.run();self.assertEqual(r['status'],'failed');self.assertEqual(list((self.dest/'charge').iterdir()),[])
    def test_stop_bound_and_unsafe_name(self):
        for kw in ({'stop_after_groups':0},{'stop_after_groups':3},{'name':'../x'}):self.assertEqual(self.f.run(**kw)['status'],'blocked')
        self.assertEqual(self.f.calls,[])
    def test_output_lock_refused(self):
        self.paused();before=snapshot(self.dest);self.f.calls=[]
        with C.existing_lock(C.Reader(self.dest),'run.lock'):r=self.f.run(resume=True)
        self.assertEqual(r['status'],'blocked');self.assertEqual(self.f.calls,[]);self.assertEqual(snapshot(self.dest),before)
    def test_terminal_without_complete_refused(self):
        self.f.run();self.retain(self.dest/'COMPLETE.json');self.refusal()
    def test_julia_entrypoint_import_scope_static_only(self):
        text=(ROOT/I.WORKER).read_text();self.assertIn('include("native_groups.jl")',text)
        self.assertLess(text.index('using JSON'),text.index('if abspath(PROGRAM_FILE)'))
        self.assertIn('NativeGroups.session(',text);self.assertIn('println(JSON.json(NativeGroups.runtime()))',text)
        # This static assertion is not Julia parser/loading evidence.
    def test_python_parser(self):
        for n in ('tools/native_readout_integration.py','tools/test_native_readout_integration.py'):ast.parse((ROOT/n).read_text())
    def freeze_fixture(self,name):
        path=self.home/name
        location=runtime_locations(path)
        value=dict(kind='native_readout_integration_source_freeze_v1',schema_version=1,source_stamps=G.stamps(C.Reader(ROOT),freeze_sources(path)),
            runtime_locations_sha256=G.digest_bytes((ROOT/location).read_bytes()))
        save(path,value);return path,value
    def test_explicit_corrected_freeze_keeps_original_receipt(self):
        original,_=self.freeze_fixture('freeze-original.json');before=snapshot(self.home)
        corrected,_=self.freeze_fixture('freeze-corrected.json')
        for path in (original,corrected):verify_freeze(path.relative_to(ROOT).as_posix())
        self.assertTrue(all(snapshot(self.home)[n]==stamp for n,stamp in before.items()))
    def test_freeze_missing_source_inventory_refused(self):
        path,value=self.freeze_fixture('freeze.json');value['source_stamps'].pop(next(iter(value['source_stamps'])));NF.replace_json(path,value)
        before=snapshot(self.home)
        with self.assertRaises(C.Rejected):verify_freeze(path.relative_to(ROOT).as_posix())
        self.assertEqual(snapshot(self.home),before)
    def test_freeze_runtime_locations_binding_refused(self):
        path,value=self.freeze_fixture('freeze.json');value['runtime_locations_sha256']='0'*64;NF.replace_json(path,value)
        with self.assertRaises(C.Rejected):verify_freeze(path.relative_to(ROOT).as_posix())
    def test_freeze_source_hash_binding_refused(self):
        path,value=self.freeze_fixture('freeze.json');value['source_stamps']['tools/native_readout_integration.py']['sha256']='0'*64;NF.replace_json(path,value)
        with self.assertRaises(C.Rejected):verify_freeze(path.relative_to(ROOT).as_posix())

    def selection_events(self):
        events=NF.plan_fixture(self.root,'abort')['events']
        for original,eid in zip(events[1:],[176,457]):
            e=copy.deepcopy(original)
            for k in ('event_id','global_decay_id','seed_event_id'):e[k]=eid
            for k in ('local_primary_id','global_primary_id'):e['identity'][k]=eid
            s=e['steps'][0];s['raw_row_index']=s['raw']['raw_row_index']=eid;s['raw']['evtid']=eid
            e['pulse_groups'][0]['row_indices']=[eid]
            # Retain an explicit zero-energy raw row outside the positive group.
            z=copy.deepcopy(s);z['raw_row_index']=z['raw']['raw_row_index']=eid+1
            z['energy_keV']=z['raw']['edep']=0.;e['steps'].append(z);events.append(e)
        return events

    def selection_fixture(self,events=None):
        recorded_cache_fixture(self.root,dict(drift_cap_ns=10000,drift_dt_ns=2,parcels=16,seed_family=2609261,temperature_K=77),
            self.selection_events() if events is None else events)

    def selected_run(self,**kwargs):
        def profile(reader,path):
            p=reader.json(path);config=R.expected_config(reader,p,3)
            return dict(mocked_profile_dispatch=True,profile=p,configuration=dict(config,expected_primary_count=None)),None
        with mock.patch.object(I,'BASE',BASE),mock.patch.object(R,'resolve_profile',side_effect=profile),\
            mock.patch.object(N,'probe_runtime',side_effect=self.f.native_probe),mock.patch.object(I,'probe_readout',side_effect=self.f.readout_probe),\
            mock.patch.object(N,'run_session',side_effect=self.f.native_session),mock.patch.object(G,'run_session',side_effect=self.f.electronics_session):
            return I.integrate(self.root,kwargs.pop('name','new'),**kwargs)

    def selected_refusal(self,**kwargs):
        before=snapshot(self.root);self.f.calls=[];r=self.selected_run(**kwargs)
        self.assertEqual(r['status'],'blocked',r);self.assertEqual(self.f.calls,[]);self.assertEqual(snapshot(self.root),before)
        return r

    def test_selector_canonical_grammar_and_duplicate_refusal(self):
        for value in ('',' 0,176','0,176 ','0,,176','0,','01,176','+1,176','-1,176','1.0,176','1e2,176',
                      'cs137-1m:176','176\n','0;176','0/176','0,0','0,1000000','０,176',0,[0,176],True):
            with self.subTest(value=value):self.selected_refusal(primary_ids=value)
        self.assertEqual(N.parse_primary_ids('457,0,176'),[457,0,176]);self.assertEqual(N.COHORT,[0,2594,3950])

    def test_selector_primary_limit_before_plan_read(self):
        self.selected_refusal(primary_ids='0,1,2,3,4,5,6,7,8')

    def test_selector_default_contract_and_config_unchanged(self):
        self.selection_fixture()
        default=N.load_plan(C.Reader(self.root),'abort')
        self.assertEqual(default['selected_primary_ids'],[0,2594,3950]);self.assertNotIn('primary_selection_mode',default)
        self.assertEqual(default['selected_census'],dict(initial_primaries=3,zero_ge_primaries=1,nonzero_primaries=2,groups=2))
        self.assertEqual(self.selected_run(dry_run=True)['status'],'planned')
        self.assertEqual(self.selected_run(primary_ids='457,0,176',dry_run=True)['status'],'planned')
        self.assertEqual(self.f.calls,[]);self.assertFalse(self.dest.exists())

    def test_selector_membership_duplicate_contract_and_namespace_refused(self):
        events=self.selection_events();self.selection_fixture(events)
        self.selected_refusal(primary_ids='0,999999')
        self.selection_fixture(events+[copy.deepcopy(events[-1])]);self.selected_refusal(primary_ids='0,457')
        events[-1]['namespace']='legacy';self.selection_fixture(events);self.selected_refusal(primary_ids='0,457')

    def test_selector_zero_only_refused_preflight(self):
        self.selection_fixture();self.selected_refusal(primary_ids='0')

    def test_selector_full_event_identity_and_zero_rows(self):
        self.selection_fixture();requested='457,0,176'
        r=self.selected_run(primary_ids=requested);self.assertEqual(r['status'],'completed',r)
        m=read(self.dest/'manifest.json');original=read(self.root/N.CONTRACT)
        self.assertEqual(m['plan']['selected_primary_ids'],[457,0,176]);self.assertEqual(m['plan']['primary_selection_mode'],'explicit')
        self.assertEqual(m['plan']['events'],[next(e for e in original['events'] if e['event_id']==eid) for eid in [457,0,176]])
        ledger=list(C.Reader(self.dest).jsonl('worker/AK02/scalars.jsonl'))
        self.assertEqual([e['event_id'] for e in ledger if e['record_kind']=='decay'],[457,0,176])
        self.assertEqual(sum(len(e['steps']) for e in m['plan']['events']),4)
        self.assertEqual(sum(s['energy_keV']==0 for e in m['plan']['events'] for s in e['steps']),2)
        reader=C.Reader(self.root)
        profile=m['detectors'][0]['profile'];expected=R.expected_config(reader,profile,3)
        self.assertEqual(m['detectors'][0]['config'],expected)
        baseline=R.expected_config(reader,profile,1)
        self.assertEqual({k:v for k,v in expected.items() if k!='expected_primary_count'},
                         {k:v for k,v in baseline.items() if k!='expected_primary_count'})

    def test_selector_caps_count_all_zero_energy_rows(self):
        events=self.selection_events();e=events[-1];zero=e['steps'][-1]
        for i in range(99):
            z=copy.deepcopy(zero);z['raw_row_index']=z['raw']['raw_row_index']=459+i;e['steps'].append(z)
        self.selection_fixture(events);self.selected_refusal(primary_ids='457')
        e['steps'].pop();self.selection_fixture(events)
        self.assertEqual(self.selected_run(primary_ids='457',dry_run=True)['status'],'planned')

    def test_selector_group_limit_before_work(self):
        events=self.selection_events();e=events[-1];base=e['steps'][0]
        e['steps']=[];e['pulse_groups']=[]
        for i in range(5):
            s=copy.deepcopy(base);s['raw_row_index']=s['raw']['raw_row_index']=457+i
            s['time_ns']=s['raw']['time']=8.+100000*i;e['steps'].append(s)
            g=copy.deepcopy(events[1]['pulse_groups'][0]);g.update(group_id=i,origin_time_ns=s['time_ns'],last_deposit_time_ns=s['time_ns'],
                row_indices=[s['raw_row_index']],recovery_not_established=i>0);e['pulse_groups'].append(g)
        e['ge_energy_keV']=e['material_energy_keV']['G4_Ge']=50.
        self.selection_fixture(events);self.selected_refusal(primary_ids='457')
        e['steps'].pop();e['pulse_groups'].pop();e['ge_energy_keV']=e['material_energy_keV']['G4_Ge']=40.
        self.selection_fixture(events);self.assertEqual(self.selected_run(primary_ids='457',dry_run=True)['status'],'planned')

    def test_selector_eight_primary_boundary(self):
        events=self.selection_events();zero=events[0]
        for eid in range(1,7):
            e=copy.deepcopy(zero)
            for k in ('event_id','global_decay_id','seed_event_id'):e[k]=eid
            for k in ('local_primary_id','global_primary_id'):e['identity'][k]=eid
            events.append(e)
        self.selection_fixture(events);self.assertEqual(self.selected_run(primary_ids='0,1,2,3,4,5,6,176',dry_run=True)['status'],'planned')

    def test_selector_independent_original_alias_seed_and_clock_checks(self):
        for key in ('seed_event_id','global_decay_id','raw_alias','clock','row_index'):
            with self.subTest(key=key):
                events=self.selection_events();e=events[-1]
                if key in e:e[key]+=1
                elif key=='raw_alias':e['steps'][0]['raw']['evtid']+=1
                elif key=='clock':e['steps'][0]['time_ns']+=1
                else:e['steps'][0]['raw']['raw_row_index']+=1
                self.selection_fixture(events);self.selected_refusal(primary_ids='457')

    def test_selector_resume_override_including_identical_refused(self):
        self.selection_fixture();self.assertEqual(self.selected_run(primary_ids='0,176,457',stop_after_groups=1)['status'],'paused')
        for value in ('0,176,457','457,0,176','', 'bad'):
            with self.subTest(value=value):self.selected_refusal(resume=True,primary_ids=value)

    def test_selector_resume_binds_initial_before_selection_read(self):
        self.selection_fixture();self.selected_run(primary_ids='0,176,457',stop_after_groups=1)
        m=read(self.dest/'manifest.json');m['plan']['selected_primary_ids']=[999999];NF.replace_json(self.dest/'manifest.json',m)
        with mock.patch.object(N,'parse_primary_ids',side_effect=AssertionError('Unbound selector was read')):
            r=self.selected_refusal(resume=True)
        self.assertNotIn('Unbound selector',str(r))

    def test_selector_rehashed_saved_ids_cannot_replace_full_ledger(self):
        self.selection_fixture();self.selected_run(primary_ids='0,176,457',stop_after_groups=1)
        m=read(self.dest/'manifest.json');m['plan']['selected_primary_ids']=[457,0,176];NF.replace_json(self.dest/'manifest.json',m)
        initial=read(self.dest/'INITIAL.json');initial['manifest']=G.stamps(C.Reader(self.dest),['manifest.json'])['manifest.json']
        NF.replace_json(self.dest/'INITIAL.json',initial);self.selected_refusal(resume=True)

    def test_selector_selected_crash_recovery_noop_uses_saved_selection(self):
        self.selection_fixture();self.assertEqual(self.selected_run(name='ref',primary_ids='457,0,176')['status'],'completed')
        self.f.after_native=True;self.assertEqual(self.selected_run(primary_ids='457,0,176')['status'],'failed');protected=durable(self.dest)
        self.f.after_native=False;self.f.calls=[]
        with mock.patch.dict(os.environ,JULIA_EXE='INVALID'):
            before=snapshot(self.dest);self.assertEqual(self.selected_run(resume=True,dry_run=True)['status'],'paused');self.assertEqual(snapshot(self.dest),before)
        self.assertEqual(self.f.calls,[])
        self.assertEqual(self.selected_run(resume=True,stop_after_groups=1)['status'],'paused');assert_preserved(self.dest,protected)
        self.assertEqual(len([c for c in self.f.calls if isinstance(c,list) and c[0]=='MOCK_EXECUTED_NATIVE']),1)
        protected=durable(self.dest);self.f.calls=[];self.assertEqual(self.selected_run(resume=True)['status'],'completed');assert_preserved(self.dest,protected)
        self.assertFalse(any(c=='MOCK_NATIVE_PROBE' or isinstance(c,list) and c[0] in ('MOCK_EXECUTED_NATIVE','MOCK_EXECUTED_CALIBRATION') for c in self.f.calls))
        self.assertEqual(semantic(self.dest),semantic(self.root/BASE/'ref'))
        self.f.calls=[];before=snapshot(self.dest)
        with mock.patch.dict(os.environ,JULIA_EXE='INVALID'):
            for dry in (False,True):self.assertTrue(self.selected_run(resume=True,dry_run=dry)['idempotent'])
        self.assertEqual(self.f.calls,[]);self.assertEqual(snapshot(self.dest),before)

    def test_selector_julia_opt_in_and_before_cache_boundaries_static(self):
        text=(ROOT/'simulation/native_groups.jl').read_text();adapter=(ROOT/I.WORKER).read_text()
        self.assertIn('allow_primary_selection=false',text);self.assertIn('allow_primary_selection=true',adapter)
        self.assertLess(text.index('selection(plan,allow_primary_selection)'),text.index('sim=deserialize('))
        for gate in ('length(unique(ids))','Exact selected-event correspondence','cs137-1m','Tiny complete-row/group caps',
                     'Exact selected group/event correspondence','V.validate_event(e,plan["prepared"])'):
            self.assertIn(gate,text)
        self.assertNotIn('N.COHORT=',(ROOT/'tools/native_readout_integration.py').read_text())

    def test_selector_public_dispatch_readonly_with_invalid_julia(self):
        name='m5fixture-dispatch';dest=ROOT/I.BASE/name;self.assertFalse(dest.exists())
        env=dict(os.environ,JULIA_EXE='INVALID_NO_PROBE',SITE_PYTHON=sys.executable)
        cases=[(['native-readout','-Name',name,'-PrimaryIds','0,176,457','-DryRun','-Json'],0),
               (['native-readout','-Name',name,'-DryRun','-Json'],0),
               (['native-readout','-Name',name,'-PrimaryIds','0,0','-DryRun'],2),
               (['native-readout','-Name',name,'-PrimaryIds','0,999999','-DryRun'],2),
               (['native-readout','-Name',name,'-PrimaryIds','0','-DryRun'],2),
               (['native-readout','-Name',name,'-PrimaryIds','0,176,457','-Resume','-DryRun'],1),
               (['status','-Name',name,'-PrimaryIds','0,176,457'],1)]
        for index,(args,expected) in enumerate(cases):
            with self.subTest(args=args):
                argv=public_command(args);r=subprocess.run(argv,cwd=ROOT,env=env,capture_output=True,text=True,timeout=60)
                save(self.home/(str(index)+'.json'),dict(arguments=argv,exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr,actual_host=False))
                self.assertEqual(r.returncode,expected,r.stdout+r.stderr);self.assertFalse(dest.exists())
                if expected==0:
                    result=C.decode(next(line for line in r.stdout.splitlines() if line.startswith('{')))
                    self.assertEqual(result['status'],'planned');self.assertEqual(result['scientific_workers_launched'],0)
                    self.assertEqual(result['selected_census'],dict(initial_primaries=3,zero_ge_primaries=1,nonzero_primaries=2,groups=2))

    def test_selector_powershell_parsing_static(self):
        names=['tools/scenario_cli.ps1','tools/native_readout_integration.ps1','.local/m5-close-v1/implementation/run-host.ps1']
        for name in names:
            script="$parseTokens=$null; $parseErrors=$null; [void][System.Management.Automation.Language.Parser]::ParseFile('"+str(ROOT/name).replace("'","''")+"',[ref]$parseTokens,[ref]$parseErrors); if($parseErrors.Count){$parseErrors | Out-String | Write-Output; exit 1}"
            r=subprocess.run(['powershell.exe','-NoProfile','-Command',script],capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stdout+r.stderr)


def uuid_suffix():return __import__('uuid').uuid4().hex[:8]


def durable(path):
    return {n:v for n,v in snapshot(path).items() if n.startswith(('charge/','calibration/','electronics/','receipts/','inputs/')) or n in ('manifest.json','INITIAL.json')}


def assert_preserved(path,old):
    now=snapshot(path);C.require(all(now.get(n)==v for n,v in old.items()),'previous committed artifacts/input/hash/size/mtime changed')


def command(home,label,args,env=None,public=False):
    record=home/(label+'.json');C.require(not record.exists(),'command receipt already exists')
    C.require(HOST_FREEZE is not None,'host commands require explicit source freeze')
    verify_freeze(HOST_FREEZE)
    argv=(public_command(args) if public else
          [sys.executable,'--no-mpi','--disable-registry','-B',*args])
    started=time.monotonic()
    with (home/(label+'.stdout')).open('xb') as out,(home/(label+'.stderr')).open('xb') as err:
        result=subprocess.run(argv,cwd=ROOT,env=env or os.environ,stdout=out,stderr=err,timeout=900)
    save(record,dict(arguments=argv,exit_code=result.returncode,wall_seconds=time.monotonic()-started,
        source_freeze=HOST_FREEZE,source_freeze_sha256=G.digest_bytes((ROOT/HOST_FREEZE).read_bytes())))
    return result


def notify_driver_death(name,primary_ids=None):
    original=N.run_session
    def session(*args,**kwargs):
        callback=args[5]
        def verified(event):
            callback(event)
            # This is after product reopening/verification/status, before ACK.
            sys.stdout.flush();sys.stderr.flush();os._exit(75)
        return original(*args[:5],verified,**kwargs)
    with mock.patch.object(N,'run_session',side_effect=session):return I.integrate(ROOT,name,primary_ids=primary_ids)


def ready_events(path):
    events=[]
    for attempt in sorted((path/'attempts').iterdir()):
        file=attempt/'worker.log'
        if not file.is_file():continue
        for line in file.read_text(encoding='utf-8').splitlines():
            if not line.startswith('{'):continue
            item=C.decode(line)
            if item.get('kind')=='group_ready':events.append(dict(attempt=attempt.name,phase=item.get('phase','charge'),key=item['key']))
    return events


def wait_crashed_worker(path):
    # Owned child only, inspected through an existing PowerShell process API.
    records=[read(p) for p in (path/'attempts').glob('*/worker-process.json')]
    C.equal(len(records),1,'one owned native worker before driver death')
    pid=records[0]['pid'];deadline=time.monotonic()+45
    while time.monotonic()<deadline:
        result=subprocess.run(['powershell.exe','-NoProfile','-Command',f'if(Get-Process -Id {pid} -ErrorAction SilentlyContinue){{exit 1}}else{{exit 0}}'],capture_output=True)
        if result.returncode==0:return
        time.sleep(.5)
    raise RuntimeError('Owned driver-death child remains active; inspect, do not retry')


def semantic(path):
    """Exact values. Only enumerated nondeterministic provenance/timing omitted."""
    m=read(path/'manifest.json');charges=[]
    for g in m['plan']['groups']:
        charge=read(path/'charge'/g['key']/'charge.json');charge.pop('native_seconds');charges.append(charge)
    calibration=read(path/'calibration/AK02/calibration.json');calibration.pop('calibration_seconds')
    electronics=[]
    for g in m['plan']['groups']:
        info=read(path/'electronics'/g['key']/'result.json');info.pop('electronics_seconds');info.pop('calibration_sha256')
        electronics.append(info)
    report=read(path/'worker/report.json')
    for d in report['detectors'].values():d.pop('electronics_seconds');d.pop('calibration_seconds')
    return dict(charge=charges,calibration=calibration,electronics=electronics,report=report,
        scalars=list(C.Reader(path).jsonl('worker/AK02/scalars.jsonl')),traces=list(C.Reader(path).jsonl('worker/AK02/traces.jsonl')))


def verify_freeze(relative):
    reader=C.Reader(ROOT);path=reader.path(relative)
    C.require(any(path.resolve().is_relative_to(p) for p in (HOME,CLOSURE_HOME)),'explicit implementation freeze only')
    freeze=reader.json(relative)
    C.equal(freeze['kind'],'native_readout_integration_source_freeze_v1','explicit freeze kind')
    C.equal(C.integer(freeze['schema_version'],'freeze schema',1,1),1,'freeze schema')
    C.equal(set(freeze['source_stamps']),set(freeze_sources(path.resolve())),'freeze source inventory')
    G.check_stamps(reader,freeze['source_stamps'])
    C.equal(freeze['runtime_locations_sha256'],reader.digest(runtime_locations(path.resolve())),'frozen runtime locations')
    reader.recheck();return freeze


def host_acceptance(home,prefix,freeze_relative,primary_ids=None):
    global HOST_FREEZE
    freeze=verify_freeze(freeze_relative);HOST_FREEZE=freeze_relative
    locations=read(ROOT/runtime_locations((ROOT/freeze_relative).resolve()))
    C.equal(Path(sys.executable).resolve(),Path(locations['python']).resolve(),'frozen installed Python')
    C.equal(Path(os.environ.get('JULIA_EXE','')).resolve(),Path(locations['julia']).resolve(),'Julia selected only by explicit child wrapper')
    C.require(re.fullmatch('[A-Za-z0-9_-]{1,18}',prefix or ''),'bounded host prefix')
    names=[prefix+'-ref',prefix+'-rec'];paths=[ROOT/I.BASE/n for n in names]
    C.require(all(not p.exists() for p in paths),'exactly two NEW host outputs required; inspect existing receipts before retry')
    C.require(primary_ids in (None,'0,176,457'),'only declared host cohorts')
    plan,_,_=I.load_plan(C.Reader(ROOT),primary_ids)
    C.equal(plan['selected_primary_ids'],[0,2594,3950] if primary_ids is None else [0,176,457],'host cohort')
    C.equal(sum(len(e['steps']) for e in plan['events']),91 if primary_ids is None else 61,'real raw row count')
    if primary_ids is not None:
        C.equal(sum(s['energy_keV']==0 for e in plan['events'] for s in e['steps']),4,'retained zero-energy rows')
    save(home/'GATES.json',dict(source_freeze=freeze_relative,source_freeze_sha256=G.digest_bytes((ROOT/freeze_relative).read_bytes()),
        expected_native_calculations=4,outputs=names,numeric_comparison='exact semantic equality, no tolerance',
        exclusions=['native_seconds','calibration_seconds','electronics_seconds','calibration_sha256 (binds run-specific calibration timing bytes)'],
        note='Readout validators retain their existing M4b implementation tolerances; cross-run deterministic equality is exact.',
        actual_host=True,mocked_math=False))
    cli=str(ROOT/'tools/native_readout_integration.py');harness=str(Path(__file__).resolve())
    print('HOST reference: two new native groups then calibration/readout',flush=True)
    if primary_ids is None:
        reference=command(home,'reference',[cli,'--name='+names[0]])
    else:
        reference=command(home,'reference',['native-readout','-Name',names[0],'-PrimaryIds',primary_ids,'-Json'],public=True)
    C.equal(reference.returncode,0,'reference host exit')
    print('HOST recovery: driver death after first verified charge commit before ACK',flush=True)
    selection_args=[] if primary_ids is None else ['--primary-ids='+primary_ids]
    C.equal(command(home,'driver-death',[harness,'--host-crash='+names[1],'--source-freeze='+freeze_relative,*selection_args]).returncode,75,'injected driver death')
    target=paths[1];wait_crashed_worker(target)
    reader=C.Reader(ROOT);p,d,s=I.load_plan(reader,I.saved_primary_ids(target,names[1]));m,mh,done,_,_=I.validate_saved(reader,target,names[1],p,d,s)
    C.equal(done,dict(charge=[p['groups'][0]['key']],calibration=[],electronics=[]),'verified first commit only')
    protected=durable(target);save(home/'preserved-after-charge.json',protected)
    invalid=dict(os.environ,JULIA_EXE='INVALID_DRYRUN_MUST_NOT_LAUNCH')
    before=snapshot(target);C.equal(command(home,'paused-dryrun',[cli,'--name='+names[1],'--resume','--dry-run'],invalid).returncode,0,'paused dryrun')
    C.equal(snapshot(target),before,'dryrun no writes')
    print('HOST resume missing charge and pause after first electronics group',flush=True)
    C.equal(command(home,'resume-first-electronics',[cli,'--name='+names[1],'--resume','--stop-after-groups=1']).returncode,0,'first electronics pause')
    assert_preserved(target,protected);saved=read(target/'run.json');C.equal(saved['status'],'paused','electronics pause status')
    C.equal(saved['stages']['calibration']['completed_keys'],['AK02'],'calibration complete once')
    C.equal(saved['stages']['electronics']['completed_count'],1,'one electronics commit')
    protected=durable(target);save(home/'preserved-after-electronics.json',protected)
    events_before=ready_events(target);save(home/'executed-before-electronics-resume.json',events_before)
    print('HOST resume remaining electronics only',flush=True)
    C.equal(command(home,'resume-electronics',[cli,'--name='+names[1],'--resume']).returncode,0,'electronics resume')
    assert_preserved(target,protected)
    C.equal(semantic(paths[0]),semantic(paths[1]),'exact FULL native/scalar/calibration/trace deterministic equality')
    all_events=[]
    for path in paths:
        reader=C.Reader(ROOT);p,d,s=I.load_plan(reader,I.saved_primary_ids(path,path.name));I.validate_saved(reader,path,path.name,p,d,s)
        C.equal(p['events'],plan['events'],'entire selected event/raw/zero ledger')
        r=read(path/'run.json');C.equal(r['status'],'completed','host successful pipeline')
        counts=r['detectors']['AK02']['counts'];C.equal((counts['initial_primaries'],counts['zero_deposit_primaries'],counts['groups']),(3,1,2),'whole selected primary ledger')
        events=ready_events(path);save(home/('executed-'+path.name+'.json'),events);all_events+=events
        for phase,keys in I.expected(p).items():C.equal(sorted(e['key'] for e in events if e['phase']==phase),sorted(keys),'actual executed once '+phase)
        # Requested-but-never-executed groups are evidence, not work counts.
        requests=[dict(attempt=f.parent.name,request=read(f)) for f in (path/'attempts').glob('*/session.json')]
        save(home/('planned-'+path.name+'.json'),requests)
        frozen=snapshot(path)
        for suffix,args in (('noop',[]),('complete-dryrun',['--dry-run'])):
            C.equal(command(home,suffix+'-'+path.name,[cli,'--name='+path.name,'--resume',*args],invalid).returncode,0,'invalid Julia completed no-op')
            C.equal(snapshot(path),frozen,'completed no writes')
    C.equal(sum(e['phase']=='charge' for e in all_events),4,'exactly four actual new native calculations')
    additions=[e for e in ready_events(target) if e['attempt'] not in {e['attempt'] for e in events_before}]
    C.equal([(e['phase'],e['key']) for e in additions],[('electronics',p['groups'][1]['key'])],'electronics resume no native/calibration redo')
    for path in paths:
        groups=[read(path/'charge'/g['key']/'charge.json') for g in p['groups']]
        if primary_ids is None:C.equal([r['transport_flags']['step_limits'] for r in groups],[143,93],'native step-limit diagnostics')
        else:
            reference_groups=[read(paths[0]/'charge'/g['key']/'charge.json') for g in p['groups']]
            C.equal([r['transport_flags'] for r in groups],[r['transport_flags'] for r in reference_groups],'exact selected endpoint/step-cap flags')
        if primary_ids is None:C.require(any(v<0 for r in groups for v in r['native']['signal']),'negative signed segment retained')
    G.check_stamps(C.Reader(ROOT),freeze['source_stamps'])
    save(home/'COMPLETE.json',dict(status='passed',actual_host=True,mocked_math=False,source_freeze=freeze_relative,
        outputs=names,actual_native_group_calculations=4,exact_semantic_equality=True,committed_hash_size_mtime_unchanged=True,
        selected_census=p['selected_census'],limitations=['Bounded engineering integration; no Li CCE or experimental calibration claim.']))


def source_tests(home):
    global EVIDENCE
    EVIDENCE=home
    sources=G.stamps(C.Reader(ROOT),freeze_sources(home))
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Tests))
    G.check_stamps(C.Reader(ROOT),sources)
    save(home/'RESULT.json',dict(tests=result.testsRun,errors=len(result.errors),failures=len(result.failures),
        source_stamps=sources,actual_host=False,mocked_native=True,mocked_electronics=True,Julia_loading_established=False))
    return 0 if result.wasSuccessful() else 1


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--evidence');p.add_argument('--host',action='store_true');p.add_argument('--prefix')
    p.add_argument('--source-freeze');p.add_argument('--host-crash');p.add_argument('--primary-ids');p.add_argument('--freeze',action='store_true');a=p.parse_args()
    if a.host_crash:
        C.require(a.source_freeze is not None and re.fullmatch('[A-Za-z0-9_-]{1,24}',a.host_crash),'explicit freeze/crash name')
        verify_freeze(a.source_freeze)
        print(G.encoded(notify_driver_death(a.host_crash,a.primary_ids)).decode());return 2
    C.require(a.evidence is not None,'explicit new implementation evidence path required')
    home=(ROOT/a.evidence).resolve();C.require(any(home.is_relative_to(p) for p in (HOME,CLOSURE_HOME)),'new-round implementation evidence only')
    if a.freeze:
        C.require(not a.host and a.source_freeze is None,'freeze is source-only')
        save(home,dict(kind='native_readout_integration_source_freeze_v1',schema_version=1,
            base_head='45f733303e44a53c3d63c9fef961f13b4d87b537' if home.is_relative_to(CLOSURE_HOME) else '3d7175be258042e74d20d24990d1e37f65ef4d00',
            source_stamps=G.stamps(C.Reader(ROOT),freeze_sources(home)),runtime_locations_sha256=G.digest_bytes((ROOT/runtime_locations(home)).read_bytes())))
        return 0
    home.mkdir(parents=True,exist_ok=False)
    save(home/'scope.json',dict(actual_host=a.host,mocked_native=not a.host,mocked_electronics=not a.host,python=sys.version,executable=sys.executable,arguments=sys.argv))
    try:
        if a.host:
            C.require(a.source_freeze is not None,'explicit original or corrected source freeze required')
            host_acceptance(home,a.prefix,a.source_freeze,a.primary_ids);return 0
        C.require(a.source_freeze is None and a.prefix is None and a.primary_ids is None,'host flags forbidden in software mode')
        return source_tests(home)
    except BaseException as error:save(home/'FAILED.json',dict(detail=str(error)));raise


if __name__=='__main__':sys.exit(main())
