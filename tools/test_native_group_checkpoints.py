"""Isolated mocked-native fixtures; opt-in coordinator-only SSD host acceptance.

Only this harness injects death before ACK. Product code has no test bypass.
Every fixture, failed attempt and host command stays in the implementation root.
"""
import argparse
import copy
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

ROOT=N.ROOT
HOME=ROOT/'.local/native-group-checkpoint-v1/implementation'
EVIDENCE=None
REAL_POPEN=subprocess.Popen
FIXTURE_BASE='.local/o'
FREEZE_SOURCES=(*N.SOURCES,'tools/test_native_group_checkpoints.py','tools/NATIVE_GROUP_CHECKPOINTS.md',
                'tools/MAINTENANCE.md','.gitignore','.gitattributes')


def snapshot(path):
    return {p.relative_to(path).as_posix():dict(sha256=G.digest_bytes(p.read_bytes()),bytes=p.stat().st_size,mtime_ns=p.stat().st_mtime_ns)
            for p in path.rglob('*') if p.is_file()}


def save(path, data):
    path.parent.mkdir(parents=True,exist_ok=True);G.write_json(path,data)


def read(path):return C.decode(path.read_text(encoding='utf-8-sig'))


def replace_json(path, data):
    # Deliberately tampered NEW fixture only, never science inputs.
    path.write_bytes(G.encoded(data))


def plan_fixture(root, policy):
    saved=read(root/'fixture-plan.json');saved['settings']['native_failure_policy']=policy
    return saved


def make_fixture(root, zero=False):
    root.mkdir(parents=True)
    for n in N.SOURCES:
        p=root/n;p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/n,p)
    G.write_bytes(root/'fixture-input.bin',b'NOT A REAL RADIATION OR FIELD CACHE\n')
    prepared=dict(coordinate_transform=dict(rotation_local_to_global=[[1,0,0],[0,1,0],[0,0,1]],translation_global_mm=[0,0,0]),
                  grouping_policy=dict(horizon_ns=100000))
    events=[]
    for eid in ([0] if zero else [0,2594,3950]):
        raw=dict(raw_row_index=eid,evtid=eid,edep=10.,time=8.,trackid=1,parent_trackid=0,particle=22)
        for a in ('xloc','yloc','zloc'):
            for suffix in ('','_pre','_post'):raw[a+suffix]=0.
        step=dict(raw_row_index=eid,raw=raw,energy_keV=10.,time_ns=8.,track_id=1,parent_track_id=0,particle_pdg=22,
                  position_mm=[0.,0.,0.],pre_position_mm=[0.,0.,0.],post_position_mm=[0.,0.,0.],global_position_m=[0.,0.,0.],
                  boundary_classifications=dict(deposit='inside',_pre='inside',_post='inside'))
        group=dict(group_id=0,origin_time_ns=8.,horizon_ns=100000,row_indices=[eid],relative_times_ns=[0.],
                   tail_truncated_possible=True,recovery_not_established=False,boundary_split_within_horizon=False,
                   electronics_state='reset_nominal_isolated_window',last_deposit_time_ns=8.)
        events.append(dict(namespace='cs137-1m',event_id=eid,global_decay_id=eid,seed_event_id=eid,seed_family=2609261,
            identity=dict(model_id='AK02',chunk_index=0,global_offset=0,local_primary_id=eid,global_primary_id=eid,chunk_count=10000,radiation_seed=123),
            source_lh5_sha256='a'*64,source_campaign_sha256='b'*64,raw_table='stp/germanium',steps=[] if eid==0 else [step],
            ge_energy_keV=0. if eid==0 else 10.,material_energy_keV=dict(G4_Ge=0. if eid==0 else 10.),zero_ge=eid==0,
            pulse_groups=[] if eid==0 else [group]))
    plan=dict(model='AK02',selected_primary_ids=[e['event_id'] for e in events],events=events,groups=N.expected_groups(events,prepared),prepared=prepared,
        selected_census=dict(initial_primaries=len(events),zero_ge_primaries=1,nonzero_primaries=len(events)-1,groups=len(events)-1),
        population_reference=dict(initial_primaries=1000000),nonselected_response=None,
        cache_file='fixture-input.bin',cache_sha256=G.digest_bytes((root/'fixture-input.bin').read_bytes()),expected_field_fingerprint={},
        model_sha256='c'*64,readout_contact_id=1,expected_environment={'mock':True},settings=dict(N.SETTINGS,native_failure_policy='abort'),
        source_sha256={n:G.digest_bytes((root/n).read_bytes()) for n in N.SOURCES},units=dict(time='ns',signed_charge='induced_equivalent_energy_keV'),
        seed_rule='MOCKED ONLY original IDs/rows',input_files=['fixture-input.bin'])
    save(root/'fixture-plan.json',plan)


def fixture_runtime(root):
    h=G.digest_bytes(Path(sys.executable).read_bytes())
    return dict(environment={'mock':True},threads=2,blas_threads=1,executable=sys.executable,worker_source=str(root/'simulation/native_groups.jl'),
                boundary_native_sha256='0358c255e37c38f62eee6f1e476c0ed48560708dfcd3d367d2688eaa022232ad',
                launcher_executable=sys.executable,launcher_sha256=h,executable_sha256=h)


def synthetic_record(plan, group, runtime, failure=None):
    event=plan['events'][group['event_index']];byrow={s['raw_row_index']:s for s in event['steps']};steps=[]
    for row in group['group']['row_indices']:
        source=byrow[row];endpoints=[]
        for i in range(1,17):
            for species in ('electron','hole'):
                endpoints.append(dict(species=species,samples=3,position_mm=[0.,0.,0.],contact_ids=[],
                    step_limit_reached=False,inside_semiconductor=True,status='stopped_without_contact',parcel_index=i))
        steps.append(dict(raw_row_index=row,deposited_energy_keV=source['energy_keV'],deposition_delay_ns=source['time_ns']-group['group']['origin_time_ns'],
                          parcel_weight_keV=source['energy_keV']/16,final_induced_keV=-2.,endpoints=endpoints))
    record=dict(kind='native_charge_group_v1',group=group,runtime=G.raw_runtime(runtime),status='native_completed',
        native=dict(times=[0.,2.,4.],signal=[0.,-1.,-2.],steps=steps),transport_flags=dict(carrier_parcels=len(steps)*32,
        geometric_contacts=0,step_limits=0,stopped_without_contact=len(steps)*32),error=None,readout=None,native_seconds=0.,field_solve_seconds=0)
    for k in ('settings','cache_sha256','model_sha256','readout_contact_id','units'):record[k]=plan[k]
    if failure:
        record.update(status='native_failed',native=None,transport_flags=None,error=failure)
    return record


class Fixture:
    def __init__(self,root):self.root=root;self.calls=[];self.failure=None;self.exception=None;self.runtime=None;self.real_session=False;self.event_mutator=None

    def load(self,reader,policy):
        p=plan_fixture(self.root,policy)
        for n,h in p['source_sha256'].items():reader.digest(n,h)
        reader.digest('fixture-plan.json');reader.digest('fixture-input.bin',p['cache_sha256'])
        return p

    def probe(self,reader,plan):
        self.calls.append('MOCK_PROBE');return self.runtime or fixture_runtime(self.root),dict(mocked=True,exit_code=0)

    def session(self,reader,dest,manifest,groups,attempt,callback):
        self.calls.append(['MOCK_NATIVE',[g['key'] for g in groups]])
        for g in groups:
            stage=attempt/('charge-'+g['key']);stage.mkdir()
            if self.exception:raise self.exception
            if self.failure and manifest['plan']['settings']['native_failure_policy']=='abort':raise RuntimeError('MOCK strict native error')
            record=synthetic_record(manifest['plan'],g,manifest['runtime'],self.failure)
            G.write_json(stage/'charge.json',record)
            event=dict(kind='group_ready',key=g['key'],directory=stage.name)
            callback(self.event_mutator(event) if self.event_mutator else event)
        return dict(mocked_native=True,exit_code=0,events=[dict(kind='group_ready',key=g['key']) for g in groups])

    def run(self,**kwargs):
        with mock.patch.object(N,'BASE',FIXTURE_BASE),mock.patch.object(N,'load_plan',side_effect=self.load),mock.patch.object(N,'probe_runtime',side_effect=self.probe):
            if self.real_session:
                def substitute(argv,**options):
                    command=[sys.executable,'--no-mpi','--disable-registry','-B',str(ROOT/'tools/test_native_group_checkpoints.py'),
                             '--mock-worker='+argv[-1]]
                    return REAL_POPEN(command,**options)
                with mock.patch.object(N.subprocess,'Popen',side_effect=substitute):return N.generate(self.root,'new',**kwargs)
            with mock.patch.object(N,'run_session',side_effect=self.session):return N.generate(self.root,'new',**kwargs)


class Tests(unittest.TestCase):
    def setUp(self):
        self.home=EVIDENCE/('t-'+G.digest_bytes(self.id().encode())[:8]);self.root=self.home/'r';make_fixture(self.root)
        self.fixture=Fixture(self.root);self.dest=self.root/FIXTURE_BASE/'new';self.original=snapshot(self.root/'simulation')

    def tearDown(self):self.assertEqual(snapshot(self.root/'simulation'),self.original)

    def paused(self,**kwargs):
        r=self.fixture.run(stop_after_new_groups=1,**kwargs);self.assertEqual(r['status'],'paused',r);return r

    def protected(self):
        return {n:snapshot(self.dest/n) for n in ('charge','receipts','inputs')},snapshot(self.dest).get('manifest.json'),snapshot(self.dest).get('INITIAL.json')

    def unchanged(self,old):
        phases,m,i=old
        for name,items in phases.items():
            now=snapshot(self.dest/name);self.assertTrue(all(now[k]==v for k,v in items.items()))
        now=snapshot(self.dest);self.assertEqual(now['manifest.json'],m);self.assertEqual(now['INITIAL.json'],i)

    def refusal(self):
        before=snapshot(self.dest);self.fixture.calls=[];r=self.fixture.run(resume=True)
        self.assertEqual(r['status'],'blocked',r);self.assertFalse(r['verification_final']);self.assertEqual(self.fixture.calls,[])
        self.assertEqual(snapshot(self.dest),before);return r

    def first(self):return next((self.dest/'charge').iterdir())

    def hide_first(self):
        retained=self.dest/'attempts/retained-loss';retained.mkdir()
        p=self.first();G.witness_path(p).rename(retained/'group-witness.json');p.rename(retained/'group')
        return retained

    def commit_ahead_of_progress(self):
        m=read(self.dest/'manifest.json');group=m['plan']['groups'][1]
        stage=self.dest/'attempts/forward-commit';stage.mkdir()
        G.write_json(stage/'charge.json',synthetic_record(m['plan'],group,m['runtime']))
        p=self.dest/'charge'/group['key'];binding=G.binding(G.digest_bytes((self.dest/'manifest.json').read_bytes()),'charge',group['key'])
        G.commit(stage,p,binding);G.committed(p,binding);N.verify_charge(p,group,m['plan'],m['runtime'])
        return group['key']

    def test_progress_exists_before_initial_receipt(self):
        original=G.write_json;observed=[]
        def inspect(path,value):
            if Path(path).name=='INITIAL.json':
                saved=read(self.dest/'run.json');observed.append(saved)
                self.assertEqual(saved['kind'],N.KIND);self.assertEqual(saved['schema_version'],1)
                self.assertEqual(saved['manifest_sha256'],G.digest_bytes((self.dest/'manifest.json').read_bytes()))
                self.assertEqual((saved['expected_groups'],saved['completed_groups'],saved['completed_keys']),(2,0,[]))
            return original(path,value)
        with mock.patch.object(G,'write_json',side_effect=inspect):self.paused()
        self.assertEqual(len(observed),1)
        saved=read(self.dest/'run.json');self.assertEqual(saved['completed_keys'],[p.name for p in (self.dest/'charge').iterdir()])

    def test_initialized_empty_progress_resumes_before_first_status(self):
        original=G.status
        def stop(path,value):
            if value['status']=='running':raise RuntimeError('MOCK interruption after INITIAL before work')
            return original(path,value)
        with mock.patch.object(G,'status',side_effect=stop):r=self.fixture.run()
        self.assertEqual(r['status'],'failed',r);self.assertTrue((self.dest/'INITIAL.json').is_file())
        saved=read(self.dest/'run.json');self.assertEqual((saved['completed_groups'],saved['completed_keys']),(0,[]))
        self.assertFalse(any(isinstance(c,list) for c in self.fixture.calls))
        old=self.protected();self.assertEqual(self.fixture.run(resume=True)['status'],'completed_native_charge');self.unchanged(old)

    def test_missing_progress_with_commits_intact_refused(self):
        self.paused();(self.dest/'run.json').rename(self.dest/'attempts/retained-run.json');self.refusal()

    def test_missing_progress_and_hidden_commit_refused(self):
        self.paused();retained=self.hide_first();(self.dest/'run.json').rename(retained/'run.json');self.refusal()

    def test_removed_progress_count_and_hidden_commit_refused(self):
        self.paused();retained=self.hide_first();p=self.dest/'run.json';saved=read(p)
        G.write_bytes(retained/'run.json',p.read_bytes());saved.pop('completed_groups');replace_json(p,saved);self.refusal()

    def test_removed_progress_keys_and_hidden_commit_refused(self):
        self.paused();retained=self.hide_first();p=self.dest/'run.json';saved=read(p)
        G.write_bytes(retained/'run.json',p.read_bytes());saved.pop('completed_keys');replace_json(p,saved);self.refusal()

    def test_stale_count_cannot_substitute_different_group(self):
        self.paused();reported=read(self.dest/'run.json');second=self.commit_ahead_of_progress();self.hide_first()
        self.assertEqual(reported['completed_groups'],1);self.assertNotIn(second,reported['completed_keys'])
        self.assertEqual(len(list((self.dest/'charge').iterdir())),1)
        self.assertEqual(self.refusal()['findings'][0]['code'],'missing_commit')

    def test_valid_commit_ahead_of_progress_reused_without_generation(self):
        self.paused();reported=read(self.dest/'run.json');second=self.commit_ahead_of_progress();old=self.protected()
        self.assertEqual(reported['completed_groups'],1);self.assertNotIn(second,reported['completed_keys'])
        self.fixture.calls=[];r=self.fixture.run(resume=True)
        self.assertEqual(r['status'],'completed_native_charge',r);self.assertEqual(r['scientific_workers_launched'],0)
        self.assertFalse(any(isinstance(c,list) for c in self.fixture.calls));self.unchanged(old)
        self.assertEqual(read(self.dest/'run.json')['completed_keys'],[g['key'] for g in read(self.dest/'manifest.json')['plan']['groups']])

    def test_progress_required_fields_and_structural_mismatches_refused(self):
        self.paused();p=self.dest/'run.json';original=read(p);retained=self.dest/'attempts/progress-tampering';retained.mkdir()
        G.write_bytes(retained/'original.json',p.read_bytes())
        mutations=[]
        for key in ('kind','schema_version','manifest_sha256','status','expected_groups','completed_groups','completed_keys'):
            value=copy.deepcopy(original);value.pop(key);mutations.append(('missing-'+key,value))
        for label,key,value in (
            ('kind','kind','other'),('schema','schema_version',2),('schema-bool','schema_version',True),
            ('schema-float','schema_version',1.),('manifest','manifest_sha256','0'*64),('status','status','planned'),
            ('expected','expected_groups',1),('expected-bool','expected_groups',True),('expected-float','expected_groups',2.),
            ('count-bool','completed_groups',True),('count-float','completed_groups',1.),('count-negative','completed_groups',-1),
            ('count-key-mismatch','completed_groups',0),('keys-null','completed_keys',None),('keys-string','completed_keys',original['completed_keys'][0]),
            ('keys-integer','completed_keys',[1]),('keys-foreign','completed_keys',['AK02-e9-d9-g0']),
            ('keys-duplicate','completed_keys',original['completed_keys']*2),('keys-empty','completed_keys',[])):
            altered=copy.deepcopy(original);altered[key]=value;mutations.append((label,altered))
        for label,altered in mutations+[('not-object',[]),('incomplete-object',{})]:
            with self.subTest(case=label):
                replace_json(p,altered);G.write_bytes(retained/(label+'.json'),p.read_bytes());self.refusal()

    def test_pause_resume_full_signed_and_zero_ledger_noop(self):
        self.paused();old=self.protected();r=self.fixture.run(resume=True)
        self.assertEqual(r['status'],'completed_native_charge',r);self.assertEqual(r['completed_groups'],2);self.unchanged(old)
        self.assertEqual(r['completed_keys'],[g['key'] for g in read(self.dest/'manifest.json')['plan']['groups']])
        self.assertEqual(r['selected_census'],dict(initial_primaries=3,zero_ge_primaries=1,nonzero_primaries=2,groups=2))
        requests=[g for call in self.fixture.calls if isinstance(call,list) for g in call[1]];self.assertEqual(len(requests),len(set(requests)))
        self.assertEqual(read(self.first()/'charge.json')['native']['signal'],[0.,-1.,-2.])
        before=snapshot(self.dest);self.fixture.calls=[]
        with mock.patch.dict(os.environ,JULIA_EXE='INVALID_MUST_NOT_BE_LOOKED_UP'):
            r=self.fixture.run(resume=True)
        self.assertTrue(r['idempotent']);self.assertEqual(self.fixture.calls,[]);self.assertEqual(snapshot(self.dest),before)

    def test_all_zero_census_no_worker(self):
        root=self.home/'zero';make_fixture(root,zero=True);f=Fixture(root)
        r=f.run();self.assertEqual(r['status'],'completed_native_charge',r);self.assertEqual(r['expected_groups'],0)
        self.assertEqual(r['scientific_workers_launched'],0);self.assertFalse(any(isinstance(c,list) for c in f.calls))
        before=snapshot(root/FIXTURE_BASE/'new');self.assertTrue(f.run(resume=True)['idempotent']);self.assertEqual(snapshot(root/FIXTURE_BASE/'new'),before)

    def test_known_failure_nulls_explicit_record(self):
        self.fixture.failure=dict(type='ArgumentError',message='Invalid waveform support',exact_error='ArgumentError: Invalid waveform support',stage='NativeLiExample.native_event')
        self.paused(native_failure_policy='record');old=self.protected();r=self.fixture.run(resume=True)
        self.assertEqual(r['status'],'completed_native_charge_with_failures',r);self.assertEqual(r['native_failed_groups'],2);self.unchanged(old)
        rec=read(self.first()/'charge.json');self.assertIsNone(rec['native']);self.assertIsNone(rec['readout']);self.assertIsNone(rec['transport_flags'])

    def test_boundary_failure_nulls(self):
        self.fixture.failure=dict(type='NativeBoundaryStall',message='Native floating-boundary projection exhausted; unwritten path row refused at step 4',
                                 step=4,start_position_m=[0.,0.,0.],last_valid_position_m=[0.,0.,0.],rejected_position_m=[0.,0.,0.],charge_unknown=True)
        r=self.fixture.run(native_failure_policy='record');self.assertEqual(r['status'],'completed_native_charge_with_failures',r)

    def test_default_strict_abort_and_unexpected_exception(self):
        self.fixture.exception=ValueError('MOCK unexpected native exception');r=self.fixture.run(native_failure_policy='record')
        self.assertEqual(r['status'],'failed');self.assertFalse((self.dest/'COMPLETE.json').exists());self.assertEqual(list((self.dest/'charge').iterdir()),[])
        before=snapshot(self.dest/'attempts');self.fixture.exception=None;r=self.fixture.run(resume=True);self.assertEqual(r['status'],'completed_native_charge',r)
        self.assertTrue(all(snapshot(self.dest/'attempts')[k]==v for k,v in before.items()))

    def test_allowed_failure_still_aborts_default(self):
        self.fixture.failure=dict(type='ArgumentError',message='Invalid waveform support',exact_error='ArgumentError: Invalid waveform support',stage='NativeLiExample.native_event')
        r=self.fixture.run();self.assertEqual(r['status'],'failed');self.assertFalse((self.dest/'COMPLETE.json').exists())

    def test_nonallowlisted_failure_refused(self):
        self.fixture.failure=dict(type='ArgumentError',message='Something else',exact_error='ArgumentError: Something else',stage='NativeLiExample.native_event')
        r=self.fixture.run(native_failure_policy='record');self.assertEqual(r['status'],'failed');self.assertEqual(list((self.dest/'charge').iterdir()),[])

    def test_read_only_new_and_saved_dryrun(self):
        before=snapshot(self.root);r=self.fixture.run(dry_run=True);self.assertEqual(r['status'],'planned');self.assertEqual(self.fixture.calls,[])
        self.assertFalse(self.dest.exists());self.assertEqual(snapshot(self.root),before)
        self.paused();before=snapshot(self.dest);self.fixture.calls=[];r=self.fixture.run(resume=True,dry_run=True)
        self.assertEqual(r['status'],'paused');self.assertEqual(self.fixture.calls,[]);self.assertEqual(snapshot(self.dest),before)

    def test_held_lease_and_failure_release(self):
        self.paused()
        before=snapshot(self.dest);self.fixture.calls=[]
        with C.existing_lock(C.Reader(self.dest),'run.lock'):
            r=self.fixture.run(resume=True);self.assertEqual(r['findings'][0]['code'],'held_or_inaccessible_lock')
            self.assertEqual(r['status'],'blocked');self.assertEqual(self.fixture.calls,[])
        self.assertEqual(snapshot(self.dest),before)
        self.fixture.exception=RuntimeError('test worker failure');self.assertEqual(self.fixture.run(resume=True)['status'],'failed')
        with C.existing_lock(C.Reader(self.dest),'run.lock'):pass
        self.fixture.exception=None;self.assertEqual(self.fixture.run(resume=True)['status'],'completed_native_charge')

    def test_simultaneous_writer_blocked_while_callback_active(self):
        original=self.fixture.session
        def concurrent(*args):
            r=self.fixture.run(resume=True);self.assertEqual(r['status'],'blocked');self.assertEqual(r['findings'][0]['code'],'held_or_inaccessible_lock')
            return original(*args)
        self.fixture.session=concurrent;self.assertEqual(self.fixture.run()['status'],'completed_native_charge')

    def test_corrupt_charge(self):
        self.paused();(self.first()/'charge.json').write_bytes(b'{}\n');self.refusal()

    def test_rehashed_charge_refused(self):
        self.paused();p=self.first();rec=read(p/'charge.json');rec['group']['event_id']=7;replace_json(p/'charge.json',rec)
        receipt=read(p/'COMMIT.json');receipt['artifacts']=G.stamps(C.Reader(p),['charge.json']);replace_json(p/'COMMIT.json',receipt)
        witness=G.witness_path(p);w=read(witness);w['commit']=G.stamps(C.Reader(p),['COMMIT.json'])['COMMIT.json'];replace_json(witness,w);self.refusal()

    def test_deleted_entire_group_cannot_be_unstarted(self):
        self.paused();self.first().rename(self.dest/'attempts/retained-whole-commit');self.refusal()

    def test_deleted_data_and_witness_refused_by_driver_count(self):
        self.paused();p=self.first();G.witness_path(p).rename(self.dest/'attempts/retained-witness.json')
        p.rename(self.dest/'attempts/retained-whole-commit');r=self.refusal();self.assertEqual(r['findings'][0]['code'],'missing_commit')

    def test_deleted_commit(self):
        self.paused();p=self.first();(p/'COMMIT.json').rename(p/'retained-commit.json');self.refusal()

    def test_deleted_witness(self):
        self.paused();p=G.witness_path(self.first());p.rename(self.dest/'attempts/retained-witness.json');self.refusal()

    def test_corrupt_witness(self):
        self.paused();G.witness_path(self.first()).write_bytes(b'{}\n');self.refusal()

    def test_extra_group_and_witness(self):
        self.paused();(self.dest/'charge/AK02-e9-d9-g0').mkdir();self.refusal()

    def test_extra_witness(self):
        self.paused();G.write_json(self.dest/'receipts/charge/unknown.json',{});self.refusal()

    def test_source_drift(self):
        self.paused();(self.root/'tools/native_group_checkpoints.py').write_bytes(b'changed source\n');self.refusal()

    def test_input_drift(self):
        self.paused();(self.root/'fixture-input.bin').write_bytes(b'changed input\n');self.refusal()

    def test_rehashed_configuration_drift(self):
        self.paused();p=self.dest/'manifest.json';m=read(p);m['plan']['settings']['parcels']=32;replace_json(p,m)
        initial=read(self.dest/'INITIAL.json');initial['manifest']=G.stamps(C.Reader(self.dest),['manifest.json'])['manifest.json'];replace_json(self.dest/'INITIAL.json',initial)
        self.refusal()

    def test_runtime_drift_before_new_work(self):
        self.paused();before=self.protected();self.fixture.runtime=dict(fixture_runtime(self.root),environment={'changed':True})
        r=self.fixture.run(resume=True);self.assertEqual(r['status'],'blocked');self.unchanged(before)
        self.assertEqual(len([c for c in self.fixture.calls if isinstance(c,list)]),1)

    def test_recorded_executable_corrupt(self):
        self.paused();fake=self.root/'mock-runtime.bin';G.write_bytes(fake,b'runtime')
        p=self.dest/'manifest.json';m=read(p);m['runtime']['executable']=str(fake);m['runtime']['executable_sha256']='0'*64;replace_json(p,m)
        initial=read(self.dest/'INITIAL.json');initial['manifest']=G.stamps(C.Reader(self.dest),['manifest.json'])['manifest.json'];replace_json(self.dest/'INITIAL.json',initial);self.refusal()

    def test_duplicate_missing_extra_ledger(self):
        self.paused();original=self.fixture.load
        for mutation in ('duplicate','missing','extra'):
            def changed(reader,policy):
                p=original(reader,policy)
                if mutation=='duplicate':p['events'].append(copy.deepcopy(p['events'][1]))
                elif mutation=='missing':p['events'].pop()
                else:p['groups'].append(dict(p['groups'][0],key='AK02-e9-d9-g0'))
                return p
            self.fixture.load=changed;self.refusal()
        self.fixture.load=original

    def test_independent_event_validator_duplicate_alias_clock(self):
        p=plan_fixture(self.root,'abort')
        for mutation in ('duplicate','alias','clock','seed','zero','extra_row'):
            events=copy.deepcopy(p['events'])
            if mutation=='duplicate':events.append(copy.deepcopy(events[1]))
            elif mutation=='alias':events[1]['steps'][0]['raw']['edep']=8.
            elif mutation=='clock':events[1]['pulse_groups'][0]['origin_time_ns']=7.
            elif mutation=='seed':events[1]['seed_event_id']=13
            elif mutation=='zero':events[0]['zero_ge']=False
            else:events[1]['pulse_groups'][0]['row_indices'].append(99)
            with self.assertRaises(C.Rejected):N.expected_groups(events,p['prepared'])

    def test_uncommitted_attempt_retained(self):
        self.paused();p=self.dest/'attempts/partial';p.mkdir();G.write_bytes(p/'partial.bin',b'inflight evidence');before=snapshot(p)
        self.assertEqual(self.fixture.run(resume=True)['status'],'completed_native_charge');self.assertEqual(snapshot(p),before)

    def test_incomplete_initialization_refused(self):
        self.dest.mkdir(parents=True);G.write_bytes(self.dest/'run.lock',b'incomplete fixture');G.write_bytes(self.dest/'manifest.json',b'{}\n');self.refusal()

    def test_commit_boundary_orphan_refused(self):
        original=G.os.rename
        def fail(src,dst):
            if Path(src).name=='PENDING.json':raise OSError('TEST interruption before COMMIT rename')
            return original(src,dst)
        with mock.patch.object(G.os,'rename',side_effect=fail):self.assertEqual(self.fixture.run()['status'],'failed')
        self.refusal()

    def test_witness_boundary_orphan_refused(self):
        original=G.os.rename
        def fail(src,dst):
            if Path(dst).parent.name=='charge' and Path(dst).suffix=='.json':raise OSError('TEST before witness rename')
            return original(src,dst)
        with mock.patch.object(G.os,'rename',side_effect=fail):self.assertEqual(self.fixture.run()['status'],'failed')
        self.refusal()

    def test_duplicate_worker_event_strict(self):
        self.fixture.event_mutator=lambda e:dict(e,key='AK02-e1-d1-g0')
        self.assertEqual(self.fixture.run()['status'],'failed');self.assertEqual(list((self.dest/'charge').iterdir()),[])

    def test_repeated_worker_group_preserves_first_commit(self):
        first=plan_fixture(self.root,'abort')['groups'][0]['key']
        self.fixture.event_mutator=lambda e:dict(e,key=first)
        self.assertEqual(self.fixture.run()['status'],'failed');self.assertEqual(len(list((self.dest/'charge').iterdir())),1)
        old=self.protected();self.fixture.event_mutator=None;r=self.fixture.run(resume=True)
        self.assertEqual(r['status'],'completed_native_charge',r);self.unchanged(old)

    def test_stop_and_resume_flags(self):
        for k,v in (('stop_after_new_groups',0),('stop_after_new_groups',5),('native_failure_policy','other')):
            self.assertEqual(self.fixture.run(**{k:v})['status'],'blocked')
        self.paused();before=snapshot(self.dest);self.assertEqual(self.fixture.run(resume=True,native_failure_policy='abort')['status'],'blocked');self.assertEqual(snapshot(self.dest),before)

    def test_mtime_drift(self):
        self.paused();p=self.first()/'charge.json';s=p.stat();os.utime(p,ns=(s.st_atime_ns,s.st_mtime_ns+1000000000));self.refusal()

    def test_deleted_final_complete_conservatively_refused(self):
        self.assertEqual(self.fixture.run()['status'],'completed_native_charge')
        (self.dest/'COMPLETE.json').rename(self.dest/'attempts/retained-COMPLETE.json');self.refusal()

    def test_driver_worker_death_after_commit_before_ack(self):
        # NEW root, real driver + process protocol; synthetic charge explicitly.
        command=[sys.executable,'--no-mpi','--disable-registry','-B',str(ROOT/'tools/test_native_group_checkpoints.py'),'--fixture-crash='+str(self.root)]
        proc=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=30)
        save(self.home/'death-command.json',dict(arguments=command,exit_code=proc.returncode,stdout=proc.stdout,stderr=proc.stderr,mocked_native=True))
        self.assertEqual(proc.returncode,75,proc.stderr)
        old=self.protected();self.assertEqual(len(list((self.dest/'charge').iterdir())),1)
        wait_closed(self.dest)
        self.fixture.real_session=True;r=self.fixture.run(resume=True);self.assertEqual(r['status'],'completed_native_charge',r);self.unchanged(old)
        requested=requested_keys(self.dest);self.assertEqual(len(requested),2);self.assertEqual(len(set(requested)),2)
        before=snapshot(self.dest);self.assertTrue(self.fixture.run(resume=True)['idempotent']);self.assertEqual(snapshot(self.dest),before)

    def freeze_fixture(self):
        for name in FREEZE_SOURCES:
            p=self.root/name
            if not p.is_file():
                p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/name,p)
        home=self.root/'.local/f';home.mkdir(parents=True)
        freeze=dict(kind='m5b_author_source_freeze_v1',status='fixtures_passed_host_pending',
                    source_sha256={n:G.digest_bytes((self.root/n).read_bytes()) for n in FREEZE_SOURCES})
        save(home/'FREEZE.json',freeze)
        return home,freeze

    def test_source_freeze_default_and_explicit_receipt_read_only(self):
        home,freeze=self.freeze_fixture();save(home/'corrected.json',freeze);before=snapshot(self.root)
        with mock.patch.multiple(sys.modules[__name__],ROOT=self.root,HOME=home):
            default,_=load_source_freeze();explicit,_=load_source_freeze('.local/f/corrected.json')
        self.assertEqual(default,freeze);self.assertEqual(explicit,freeze);self.assertEqual(snapshot(self.root),before)

    def test_source_freeze_incomplete_inventory_and_drift_refused(self):
        home,freeze=self.freeze_fixture()
        with mock.patch.multiple(sys.modules[__name__],ROOT=self.root,HOME=home):
            missing=copy.deepcopy(freeze);missing['source_sha256'].pop('simulation/native_groups.jl');save(home/'missing.json',missing)
            with self.assertRaises(C.Rejected):load_source_freeze('.local/f/missing.json')
            drift=copy.deepcopy(freeze);drift['source_sha256']['simulation/native_groups.jl']='0'*64;save(home/'drift.json',drift)
            with self.assertRaises(C.Rejected):load_source_freeze('.local/f/drift.json')
            null=copy.deepcopy(freeze);null['source_sha256']['simulation/native_groups.jl']=None;save(home/'null.json',null)
            with self.assertRaises(C.Rejected):load_source_freeze('.local/f/null.json')

    def test_source_freeze_unsafe_and_missing_paths_refused(self):
        home,_=self.freeze_fixture()
        with mock.patch.multiple(sys.modules[__name__],ROOT=self.root,HOME=home):
            for path in ('.local/f/missing.json','fixture-plan.json','../FREEZE.json',str(home/'FREEZE.json'),'.local/f/'+'x'*260+'.json'):
                with self.assertRaises(C.Rejected):load_source_freeze(path)


def inject_driver_death(call):
    original=G.status
    def death(path,value):
        original(path,value)
        if value.get('status')=='running' and value.get('completed_groups')==1:
            os._exit(75) # test harness only: after reopened verified commit, before ACK
    with mock.patch.object(G,'status',side_effect=death):return call()


def mock_worker(session):
    req=read(session);attempt=session.parent
    for group in req['groups']:
        p=attempt/('charge-'+group['key']);p.mkdir();G.write_json(p/'charge.json',synthetic_record(req['plan'],group,req['runtime']))
        print(json.dumps(dict(kind='group_ready',key=group['key'],directory=p.name)),flush=True)
        ack=sys.stdin.readline()
        if not ack:
            save(attempt/'mock-worker-exit.json',dict(status='closed_pipe',mocked_native=True));return 71
        C.equal(C.decode(ack),dict(kind='committed',key=group['key']),'mock ACK')
    print(json.dumps(dict(kind='session_done')),flush=True);return 0


def requested_keys(dest):
    # Session lists plan the remainder. Native work cannot advance past an
    # unacknowledged group. Count actual worker-ready events, not unfinished plans.
    return [C.decode(line)['key'] for path in sorted((dest/'attempts').glob('*/worker.log'))
            for line in path.read_text(encoding='utf-8').splitlines() if line.startswith('{') and C.decode(line).get('kind')=='group_ready']


def wait_closed(dest):
    deadline=time.monotonic()+10
    while time.monotonic()<deadline:
        if list((dest/'attempts').glob('*/mock-worker-exit.json')):return
        time.sleep(.1)
    raise RuntimeError('owned mock worker did not observe driver EOF')


def wait_owned_host_worker(dest):
    """Read-only wait for this harness's tiny Julia child; never stop processes."""
    import ctypes
    from ctypes import wintypes
    record=read(next((dest/'attempts').glob('*/worker-process.json')))
    api=ctypes.WinDLL('kernel32',use_last_error=True)
    api.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];api.OpenProcess.restype=wintypes.HANDLE
    api.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD];api.WaitForSingleObject.restype=wintypes.DWORD
    api.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=api.OpenProcess(0x00100000,False,record['pid']) # SYNCHRONIZE only, no termination rights
    if not handle:
        C.equal(ctypes.get_last_error(),87,'owned worker already exited')
        return
    try:C.equal(api.WaitForSingleObject(handle,30000),0,'owned host worker exited after pipe closure')
    finally:api.CloseHandle(handle)


def command(home,label,args,env=None,timeout=1200):
    argv=[sys.executable,'--no-mpi','--disable-registry','-B',*args]
    result=subprocess.run(argv,cwd=ROOT,env=env,capture_output=True,text=True,timeout=timeout)
    save(home/(label+'.json'),dict(arguments=argv,exit_code=result.returncode,stdout=result.stdout,stderr=result.stderr))
    return result


def load_source_freeze(source_freeze=None):
    """An explicit correction receipt never replaces the original author pin."""
    name=source_freeze if source_freeze is not None else (HOME/'FREEZE.json').relative_to(ROOT).as_posix()
    C.require(isinstance(name,str) and len(str(ROOT/name))<260,'bounded source freeze path','unsafe_path')
    reader=C.Reader(ROOT);path=reader.path(name)
    C.require(path.is_relative_to(HOME) and path.suffix=='.json' and len(str(path))<260,
              'source freeze must be a bounded implementation-root JSON receipt','unsafe_path')
    freeze=reader.json(name)
    C.equal((freeze['kind'],freeze['status']),('m5b_author_source_freeze_v1','fixtures_passed_host_pending'),'source freeze receipt')
    C.equal(set(freeze['source_sha256']),set(FREEZE_SOURCES),'complete source freeze inventory')
    for n,h in freeze['source_sha256'].items():C.equal(reader.digest(n),h,'source freeze '+n)
    reader.recheck();return freeze,name


def host_acceptance(home,prefix,source_freeze=None):
    """After source freeze only: two outputs, four NEW tiny native group calls."""
    C.require(re.fullmatch('[A-Za-z0-9_-]{1,20}',prefix or ''),'bounded explicit NEW host prefix')
    freeze,freeze_name=load_source_freeze(source_freeze)
    names=[prefix+'-ref',prefix+'-crash'];destinations=[ROOT/N.BASE/n for n in names]
    C.require(not any(p.exists() for p in destinations),'new host output names only')
    reader=C.Reader(ROOT);plan=N.load_plan(reader,'record');before=G.stamps(reader,list(reader.watched))
    save(home/'predeclared-gates.json',dict(selected_primary_ids=N.COHORT,selected_census=plan['selected_census'],
         native_numeric_gate='exact full signed times/signal/steps and flags; only native_seconds excluded',
         source_freeze=freeze['source_sha256'],source_freeze_receipt=freeze_name,old_input_stamps=before,actual_SSD=True,new_groups_per_output=2))
    cli=str(ROOT/'tools/native_group_checkpoints.py')
    print('HOST: generating tiny uninterrupted charge-only reference',flush=True)
    ref=command(home,'reference',[cli,'--name='+names[0],'--native-failure-policy=record'])
    C.equal(ref.returncode,0,'host reference exit')
    print('HOST: test driver death after first verified native commit, before ACK',flush=True)
    crash=command(home,'driver-death',[str(Path(__file__).resolve()),'--host-crash='+names[1]])
    C.equal(crash.returncode,75,'host driver death exit')
    target=destinations[1];wait_owned_host_worker(target)
    out=C.Reader(target);manifest=out.json('manifest.json');mh=out.digest('manifest.json')
    groups=plan['groups'];first=target/'charge'/groups[0]['key']
    G.committed(first,G.binding(mh,'charge',groups[0]['key']));N.verify_charge(first,groups[0],plan,manifest['runtime'])
    C.equal(len(list((target/'charge').iterdir())),1,'one committed group before crash')
    protected={n:snapshot(target/n) for n in ('charge','receipts','inputs')}
    protected['immutable']={n:snapshot(target)[n] for n in ('manifest.json','INITIAL.json')}
    save(home/'preserved-at-crash.json',protected)
    dry=command(home,'saved-dryrun',[cli,'--name='+names[1],'--resume','--dry-run'])
    C.equal(dry.returncode,0,'host read-only progress exit')
    print('HOST: resuming unfinished native group only',flush=True)
    resumed=command(home,'resume',[cli,'--name='+names[1],'--resume'])
    C.equal(resumed.returncode,0,'host resume exit')
    for name,items in protected.items():
        now=snapshot(target if name=='immutable' else target/name)
        C.require(all(now[n]==stamp for n,stamp in items.items()),'previous native commit/input rewritten')
    for group in groups:
        a=read(destinations[0]/'charge'/group['key']/'charge.json');b=read(target/'charge'/group['key']/'charge.json')
        C.equal(a['status'],'native_completed','declared reference native success')
        C.equal(b['status'],'native_completed','declared resumed native success')
        C.require(any(q!=0 for q in a['native']['signal']),'actual new signed native response required')
        a.pop('native_seconds');b.pop('native_seconds');C.equal(a,b,'exact full native group '+group['key'])
    for path in destinations:
        run=read(path/'run.json');C.require(run['status'] in N.TERMINAL and run['verification_final'],'driver final completion')
        C.equal(run['selected_census'],plan['selected_census'],'entire selected zero census')
        keys=requested_keys(path);C.equal(sorted(keys),sorted(g['key'] for g in groups),'groups requested once per output')
        frozen=snapshot(path);env=dict(os.environ,JULIA_EXE='INVALID_COMPLETED_RESUME_MUST_NOT_LAUNCH')
        no=command(home,'noop-'+path.name,[cli,'--name='+path.name,'--resume'],env=env)
        C.equal(no.returncode,0,'host completed invalid-runtime noop');C.equal(snapshot(path),frozen,'host completed no writes')
    G.check_stamps(C.Reader(ROOT),before)
    save(home/'COMPLETE.json',dict(status='passed',actual_SSD=True,mocked_native=False,new_outputs=names,selected_census=plan['selected_census'],
        exact_full_native_equality=True,completed_group_files_unchanged=True,groups_requested_once=True,readout='pending',power_loss_claim=False))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--evidence');p.add_argument('--host',action='store_true');p.add_argument('--prefix')
    p.add_argument('--source-freeze',help='Host-only project-relative implementation JSON receipt; default original FREEZE.json')
    p.add_argument('--fixture-crash');p.add_argument('--mock-worker');p.add_argument('--host-crash')
    a=p.parse_args()
    C.require(a.source_freeze is None or a.host,'--source-freeze is host-only','invalid_flags')
    if a.mock_worker:
        path=Path(a.mock_worker).resolve();C.require(path.is_relative_to(HOME),'owned fixture process only');sys.exit(mock_worker(path))
    if a.fixture_crash:
        root=Path(a.fixture_crash).resolve();C.require(root.is_relative_to(HOME),'owned new fixture only');f=Fixture(root);f.real_session=True
        print(json.dumps(inject_driver_death(f.run)),flush=True);sys.exit(2)
    if a.host_crash:
        C.require(re.fullmatch('[A-Za-z0-9_-]{1,32}',a.host_crash or ''),'bounded host output')
        print(json.dumps(inject_driver_death(lambda:N.generate(ROOT,a.host_crash,native_failure_policy='record'))),flush=True);sys.exit(2)
    C.require(a.evidence is not None,'explicit new evidence root required')
    EVIDENCE=(ROOT/a.evidence).resolve();C.require(EVIDENCE.is_relative_to(HOME),'implementation evidence only')
    EVIDENCE.mkdir(parents=True,exist_ok=False)
    save(EVIDENCE/'scope.json',dict(actual_SSD=a.host,mocked_native=not a.host,python=sys.version,executable=sys.executable,arguments=sys.argv,
        source_sha256={n:G.digest_bytes((ROOT/n).read_bytes()) for n in (*N.SOURCES,'tools/test_native_group_checkpoints.py')}))
    if a.host:
        try:host_acceptance(EVIDENCE,a.prefix,a.source_freeze)
        except BaseException as error:save(EVIDENCE/'FAILED.json',dict(detail=str(error)));raise
    else:
        class Tee:
            def __init__(self,log):self.log=log
            def write(self,text):self.log.write(text);sys.stderr.write(text)
            def flush(self):self.log.flush();sys.stderr.flush()
        with (EVIDENCE/'suite.log').open('x',encoding='utf-8') as log:
            result=unittest.TextTestRunner(stream=Tee(log),verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Tests))
        save(EVIDENCE/'RESULT.json',dict(tests=result.testsRun,errors=len(result.errors),failures=len(result.failures),
            exit_code=0 if result.wasSuccessful() else 1,actual_SSD=False,mocked_native=True))
        sys.exit(0 if result.wasSuccessful() else 1)
