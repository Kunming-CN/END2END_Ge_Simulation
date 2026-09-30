"""M5a source-only fixtures and opt-in existing-host electronics acceptance.

No new charge/field/transport. Fixtures mock Julia/electronics explicitly.
Process death is injected only in this test harness, never the product CLI.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest import mock

import charge_check as C
import group_checkpoints as G
import replay_readout as R
import test_charge_check as F
import test_replay_readout as T

ROOT=Path(__file__).resolve().parents[1]
EVIDENCE=None
REAL_CHILD=R.child


class Fixture:
    def __init__(self,root):self.root=root;self.calls=[];self.crash=None

    def probe(self,argv,cwd,**kwargs):
        if argv[0]=='powershell.exe':return REAL_CHILD(argv,cwd,**kwargs)
        self.calls.append(argv)
        return dict(arguments=argv,exit_code=0,wall_seconds=0,output_limit_exceeded=False,
            output=json.dumps(dict(executable=sys.executable,group_process_module='Main',group_process_source=str((self.root/'simulation/replay_groups.jl').resolve()))))

    def runtime(self,reader,runtime,inspection,exe,**kwargs):
        runtime.update(launcher_executable=exe,launcher_sha256=F.sha(Path(exe)),executable_sha256=F.sha(Path(exe)))

    def session(self,root,dest,manifest,mh,runtime,groups,attempt,callback):
        self.calls.append(['MOCKED_SESSION',*[g['key'] for g in groups]])
        source=attempt/'mock-one-shot';source.mkdir();shutil.copytree(dest/'inputs',source/'inputs')
        report=T.tiny_worker(source,{'detectors':manifest['detectors']})
        for d in manifest['detectors']:
            m=d['model']
            if (dest/'calibration'/m).exists():continue
            p=attempt/('calibration-'+m);p.mkdir()
            info=dict(kind='saved_charge_calibration_v1',model=m,config=d['config'],runtime=G.raw_runtime(runtime),
                      calibration=report['detectors'][m]['calibration'],calibration_seconds=0.)
            G.write_json(p/'calibration.json',info)
            callback(dict(kind='group_ready',phase='calibration',key=m,directory=p.name))
        for g in groups:
            m=g['model'];p=attempt/('electronics-'+g['key']);p.mkdir()
            rec=next(r for r in C.Reader(source).jsonl('worker/'+m+'/scalars.jsonl') if r['record_kind']=='pulse' and
                     [r[k] for k in ('event_id','global_decay_id','group_id')]==[g['identity'][k] for k in ('event_id','global_decay_id','group_id')])
            traces=[r for r in C.Reader(source).jsonl('worker/'+m+'/traces.jsonl') if r['event_id']==rec['event_id'] and r['group_id']==rec['group_id']]
            G.write_bytes(p/'scalars.jsonl',G.encoded(rec));G.write_bytes(p/'traces.jsonl',b''.join(G.encoded(r) for r in traces))
            counts=dict.fromkeys(R.COUNT_FIELDS,0);counts.update(groups=1,rejected=1)
            if rec.get('status')=='native_transport_failed':counts['native_failed_groups']=1
            else:counts.update(readout_rejected=1,native_charge_samples=3,analog_samples=50000)
            cal=C.Reader(dest/'calibration'/m).json('calibration.json')
            G.write_json(p/'result.json',dict(kind='saved_charge_electronics_group_v1',key=g['key'],config=G.config_for(manifest,m)['config'],
                        runtime=G.raw_runtime(runtime),calibration_sha256=G.digest_bytes(G.encoded(cal)),counts=counts,electronics_seconds=0.))
            if self.crash=='before-receipt' and g==groups[-1]:os._exit(73)
            callback(dict(kind='group_ready',phase='electronics',key=g['key'],directory=p.name))
            if self.crash=='after-receipt':os._exit(74)
        return dict(exit_code=0,wall_seconds=0,mocked_electronics=True)

    def run(self,**kwargs):
        with mock.patch.object(R,'child',side_effect=self.probe),mock.patch.object(R,'julia_executable',return_value=sys.executable),\
             mock.patch.object(R,'verify_runtime',side_effect=self.runtime),mock.patch.object(G,'run_session',side_effect=self.session):
            return R.replay_run(self.root,'synthetic','new',checkpoint_groups=True,**kwargs)


class GroupTests(unittest.TestCase):
    def setUp(self):
        self.home=EVIDENCE/('t-'+G.digest_bytes(self.id().encode())[:8]);self.root=self.home/'root'
        F.save(self.home/'case.json',dict(test=self.id()))
        self.create()

    def create(self,fail=False):
        F.fixture(self.root,fail=fail)
        for n in G.SOURCES:
            p=self.root/n;p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/n,p)
        self.fixture=Fixture(self.root);self.dest=self.root/'.local/replays/new'
        self.original=F.snapshot(self.root/'.local/runs')

    def tearDown(self):self.assertEqual(F.snapshot(self.root/'.local/runs'),self.original)

    def stopped(self):
        r=self.fixture.run(stop_after_groups=1);self.assertEqual(r['status'],'paused',r['findings']);self.assertEqual(r['completed_groups'],1);return r

    def protected(self):
        return {phase:F.snapshot(self.dest/phase) for phase in ('charge','electronics','calibration','inputs','receipts')}

    def rehash_witness(self,folder):
        path=G.witness_path(folder);receipt=F.read(path);receipt['commit']=G.stamps(C.Reader(folder),['COMMIT.json'])['COMMIT.json'];F.save(path,receipt)

    def test_stop_resume_completed_noop_and_calibration_reuse(self):
        self.stopped();before=self.protected();calls=len(self.fixture.calls)
        r=self.fixture.run(resume=True);self.assertEqual(r['status'],'completed',r['findings']);self.assertEqual(r['completed_groups'],2)
        for phase,items in before.items():
            current=F.snapshot(self.dest/phase)
            self.assertTrue(all(current[n]==v for n,v in items.items()))
        self.assertEqual(len(self.fixture.calls)-calls,2) # one probe, one sequential worker
        all_before=F.snapshot(self.dest)
        with mock.patch.object(R,'julia_executable',side_effect=AssertionError('Completed no-op launches no Julia')):
            r=R.replay_run(self.root,'synthetic','new',checkpoint_groups=True,resume=True)
        self.assertTrue(r['idempotent']);self.assertEqual(r['scientific_workers_launched'],0);self.assertEqual(F.snapshot(self.dest),all_before)

    def test_signed_zero_and_failed_native_population(self):
        self.root=self.home/'failure-root';self.create(fail=True)
        self.stopped();r=self.fixture.run(resume=True);self.assertEqual(r['status'],'completed_with_native_failures',r['findings'])
        counts=r['detectors']['AK02']['counts'];self.assertEqual((counts['initial_primaries'],counts['zero_deposit_primaries'],counts['groups'],counts['native_failed_groups']),(3,1,2,1))
        rows=list(C.Reader(self.dest).jsonl('worker/AK02/scalars.jsonl'));self.assertTrue(rows[2]['readout']['negative_input'])
        self.assertIsNone(rows[-1]['readout']);self.assertIsNone(rows[-1]['final_induced_keV']);self.assertEqual(rows[-1]['native_error']['exact_error'],'ArgumentError: Invalid waveform support')
        failed=G.config_for(F.read(self.dest/'manifest.json'),'AK02');self.assertEqual(failed['primary_count'],3)

    def test_new_public_dryrun_no_write_no_julia(self):
        before=F.snapshot(self.root)
        with mock.patch.dict(os.environ,JULIA_EXE='DO_NOT_LAUNCH'):
            got=T.command(self.home/'command.json',['replay-readout','-Name','synthetic','-ReplayName','new','-CheckpointGroups','-StopAfterGroups','1','-DryRun','-Json'],self.root)
        self.assertEqual(got.returncode,0,got.stderr);self.assertEqual(json.loads(got.stdout)['status'],'planned');self.assertEqual(F.snapshot(self.root),before)

    def test_group_budget_preflight_before_runtime_or_reservation(self):
        original=C._inspect_leased
        def inject(*args):
            original(*args);args[-1]['detectors'][0]['counts']['groups']=401;args[-1]['detectors'][0]['counts']['native_failed_groups']=401
        with mock.patch.object(C,'_inspect_leased',side_effect=inject):
            r=self.fixture.run(dry_run=True)
        self.assertEqual(r['status'],'blocked');self.assertEqual(r['findings'][0]['code'],'not_supported')
        self.assertEqual(self.fixture.calls,[]);self.assertFalse(self.dest.exists())

    def test_saved_public_dryrun_no_write_no_julia(self):
        self.stopped();before=F.snapshot(self.root)
        with mock.patch.dict(os.environ,JULIA_EXE='DO_NOT_LAUNCH'):
            got=T.command(self.home/'command.json',['replay-readout','-Name','synthetic','-ReplayName','new','-CheckpointGroups','-Resume','-DryRun','-Json'],self.root)
        self.assertEqual(got.returncode,0,got.stderr);r=json.loads(got.stdout);self.assertEqual(r['completed_groups'],1);self.assertEqual(r['expected_groups'],2)
        self.assertEqual(r['runtime_verified'],'NOT_CHECKED');self.assertEqual(F.snapshot(self.root),before)

    def test_invalid_flags_and_explicit_profile_overrides(self):
        for i,args in enumerate((['-Resume'],['-StopAfterGroups','1'],['-CheckpointGroups','-StopAfterGroups','0'],
                ['-CheckpointGroups','-Resume','-ElectronicsProfile','simulation/native_readout_profile.json'],
                ['-CheckpointGroups','-Resume','-ElectronicsProfile',''],['-CheckpointGroups','-Seed','7'],['-CheckpointGroups','-BadFlag'])):
            before=F.snapshot(self.root);got=T.command(self.home/f'command-{i}.json',['replay-readout','-Name','synthetic','-ReplayName','new','-DryRun',*args],self.root)
            self.assertNotEqual(got.returncode,0);self.assertEqual(F.snapshot(self.root),before)
        for value in ('',False,0,'simulation/native_readout_profile.json'):
            r=self.fixture.run(resume=True,electronics_profile=value);self.assertEqual(r['status'],'blocked');self.assertEqual(r['findings'][0]['code'],'invalid_flags')

    def test_legacy_and_native_folders_never_adopted(self):
        self.dest.mkdir(parents=True);G.write_bytes(self.dest/'run.lock',b'TEST\n');G.write_json(self.dest/'run.json',dict(kind='electronics_replay_v1',status='completed'))
        before=F.snapshot(self.dest);r=self.fixture.run(resume=True);self.assertEqual(r['status'],'blocked');self.assertEqual(F.snapshot(self.dest),before);self.assertEqual(self.fixture.calls,[])

    def test_corrupt_missing_extra_committed_data_fail_before_julia(self):
        self.stopped();p=next((self.dest/'electronics').iterdir())/'scalars.jsonl';original=p.read_bytes()
        for data in (b'BROKEN\n',original+original,b''):
            p.write_bytes(data);before=F.snapshot(self.dest);self.fixture.calls=[];r=self.fixture.run(resume=True)
            self.assertEqual(r['status'],'blocked');self.assertEqual(self.fixture.calls,[]);self.assertEqual(F.snapshot(self.dest),before)
        p.unlink();self.assertEqual(self.fixture.run(resume=True)['status'],'blocked')

    def test_rehashed_wrong_identity_and_adc_rejected(self):
        self.stopped();folder=next((self.dest/'electronics').iterdir());p=folder/'scalars.jsonl';original=p.read_bytes()
        for field in ('event_id','adc_code'):
            row=json.loads(original)
            if field=='event_id':row[field]+=10
            else:row['readout'][field]=3
            p.write_bytes(G.encoded(row));receipt=F.read(folder/'COMMIT.json');receipt['artifacts']['scalars.jsonl']=G.stamps(C.Reader(folder),['scalars.jsonl'])['scalars.jsonl'];F.save(folder/'COMMIT.json',receipt)
            self.rehash_witness(folder)
            self.fixture.calls=[];r=self.fixture.run(resume=True);self.assertEqual(r['status'],'blocked');self.assertEqual(self.fixture.calls,[])

    def test_rehashed_configuration_and_expected_ids_rejected(self):
        self.stopped();path=self.dest/'manifest.json';original=F.read(path)
        for kind in ('config','missing','duplicate','extra'):
            value=copy.deepcopy(original)
            if kind=='config':value['detectors'][0]['config']['gain']*=2
            elif kind=='missing':value['groups'].pop()
            elif kind=='duplicate':value['groups'].append(value['groups'][0])
            else:value['groups'][0]['identity']['event_id']=99
            F.save(path,value);receipt=F.read(self.dest/'INITIAL.json');receipt['manifest']=G.stamps(C.Reader(self.dest),['manifest.json'])['manifest.json'];F.save(self.dest/'INITIAL.json',receipt)
            self.fixture.calls=[];r=self.fixture.run(resume=True);self.assertEqual(r['status'],'blocked');self.assertEqual(self.fixture.calls,[])

    def test_changed_source_runtime_and_source_mtime_rejected(self):
        self.stopped();p=self.root/'simulation/replay_groups.jl';data=p.read_bytes();stamp=p.stat()
        p.write_bytes(data+b'\n');self.fixture.calls=[];self.assertEqual(self.fixture.run(resume=True)['status'],'blocked');self.assertEqual(self.fixture.calls,[])
        p.write_bytes(data);os.utime(p,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
        original=self.fixture.probe
        def changed(*args,**kwargs):
            r=original(*args,**kwargs);value=json.loads(r['output']);value['changed_runtime']=True;r['output']=json.dumps(value);return r
        self.fixture.probe=changed;before=self.protected();r=self.fixture.run(resume=True);self.assertEqual(r['status'],'blocked');self.assertEqual(before,self.protected())

    def test_held_source_and_output_leases_and_concurrent_resume(self):
        self.stopped();before=F.snapshot(self.dest)
        for home,relative in ((self.root,'.local/runs/synthetic/run.lock'),(self.dest,'run.lock')):
            with C.existing_lock(C.Reader(home),relative):
                self.assertEqual(self.fixture.run(resume=True)['status'],'blocked')
            self.assertEqual(F.snapshot(self.dest),before)
        original=self.fixture.session
        def simultaneous(*args):
            got=Fixture(self.root).run(resume=True);self.assertEqual(got['status'],'blocked');self.assertEqual(got['findings'][0]['code'],'held_or_inaccessible_lock')
            return original(*args)
        self.fixture.session=simultaneous;self.assertEqual(self.fixture.run(resume=True)['status'],'completed')

    def test_partial_stages_are_evidence_not_results(self):
        self.stopped();p=self.dest/'attempts'/'orphan';p.mkdir();G.write_bytes(p/'scalars.jsonl',b'partial unbound evidence\n')
        before=F.snapshot(p);self.assertEqual(self.fixture.run(resume=True)['status'],'completed');self.assertEqual(F.snapshot(p),before)

    def test_after_data_before_receipt_conservative_refusal(self):
        self.stopped();original=G.os.rename
        def fault(src,dst):
            if Path(src).name=='PENDING.json' and Path(src).parent.parent.name=='electronics':raise OSError('TEST death after directory rename')
            return original(src,dst)
        with mock.patch.object(G.os,'rename',side_effect=fault):r=self.fixture.run(resume=True)
        self.assertEqual(r['status'],'failed');before=F.snapshot(self.dest);self.fixture.calls=[]
        r=self.fixture.run(resume=True);self.assertEqual(r['status'],'blocked');self.assertEqual(r['findings'][0]['code'],'uncommitted_boundary');self.assertEqual(self.fixture.calls,[]);self.assertEqual(F.snapshot(self.dest),before)

    def test_before_data_and_receipt_boundaries(self):
        original=G.commit
        for phase in ('charge','electronics'):
            root=self.home/phase;self.root=root;self.create();hit=[False]
            def fault(stage,dest,bind):
                if bind['phase']==phase and not hit[0]:hit[0]=True;raise OSError('TEST staged data before commit')
                return original(stage,dest,bind)
            with mock.patch.object(G,'commit',side_effect=fault):r=self.fixture.run()
            self.assertEqual(r['status'],'failed');attempts=F.snapshot(self.dest/'attempts');r=self.fixture.run(resume=True)
            self.assertEqual(r['status'],'completed',r['findings']);self.assertTrue(all(F.snapshot(self.dest/'attempts')[n]==v for n,v in attempts.items()))

    def test_actual_fixture_process_death_after_earlier_commit(self):
        self.stopped();before=self.protected()
        # Source-only harness child dies at a known staged boundary before the
        # second group receipt. Earlier commits and calibration survive.
        argv=[sys.executable,'--no-mpi','--disable-registry','-B',str(ROOT/'tools/test_group_checkpoints.py'),
              '--crash-fixture='+str(self.root),'--boundary=before-receipt']
        got=subprocess.run(argv,cwd=ROOT,capture_output=True,text=True,timeout=60)
        F.save(self.home/'death.json',dict(arguments=argv,exit_code=got.returncode,stdout=got.stdout,stderr=got.stderr,test_only=True))
        self.assertEqual(got.returncode,73,got.stderr)
        for phase,items in before.items():self.assertTrue(all(F.snapshot(self.dest/phase)[n]==v for n,v in items.items()))
        r=self.fixture.run(resume=True);self.assertEqual(r['status'],'completed',r['findings'])

    def test_source_and_committed_mtime_checks(self):
        self.stopped();p=next((self.dest/'electronics').iterdir())/'traces.jsonl';st=p.stat();os.utime(p,ns=(st.st_atime_ns,st.st_mtime_ns+1000000000))
        self.fixture.calls=[];self.assertEqual(self.fixture.run(resume=True)['status'],'blocked');self.assertEqual(self.fixture.calls,[])

    def test_whole_committed_group_missing_never_recomputed(self):
        self.stopped();folder=next((self.dest/'electronics').iterdir());folder.rename(self.dest/'attempts'/'retained-removed-commit')
        before=F.snapshot(self.dest);self.fixture.calls=[];r=self.fixture.run(resume=True)
        self.assertEqual(r['status'],'blocked');self.assertEqual(self.fixture.calls,[]);self.assertEqual(F.snapshot(self.dest),before)

    def test_unknown_extra_group_refused(self):
        self.stopped();(self.dest/'electronics'/'AK02-e99-d99-g0').mkdir();before=F.snapshot(self.dest);self.fixture.calls=[]
        r=self.fixture.run(resume=True);self.assertEqual(r['status'],'blocked');self.assertEqual(self.fixture.calls,[]);self.assertEqual(F.snapshot(self.dest),before)

    def test_after_commit_before_witness_refused(self):
        self.stopped();original=G.os.rename
        def fault(src,dst):
            if Path(dst).parent.name=='electronics' and Path(dst).suffix=='.json':raise OSError('TEST death before separate witness')
            return original(src,dst)
        with mock.patch.object(G.os,'rename',side_effect=fault):self.assertEqual(self.fixture.run(resume=True)['status'],'failed')
        before=F.snapshot(self.dest);self.fixture.calls=[];r=self.fixture.run(resume=True)
        self.assertEqual(r['status'],'blocked');self.assertEqual(self.fixture.calls,[]);self.assertEqual(F.snapshot(self.dest),before)

    def test_final_data_without_complete_is_not_adopted(self):
        self.assertEqual(self.fixture.run()['status'],'completed');(self.dest/'COMPLETE.json').rename(self.dest/'retained-complete.json')
        before=F.snapshot(self.dest);self.fixture.calls=[];r=self.fixture.run(resume=True);self.assertEqual(r['status'],'blocked');self.assertEqual(F.snapshot(self.dest),before);self.assertEqual(self.fixture.calls,[])

    def test_external_profile_changed_after_snapshot_is_unused(self):
        profile=F.read(self.root/'.local/runs/synthetic/AK02/response/profile-input.json');p=self.root/'saved-profile.json';F.save(p,profile)
        r=self.fixture.run(electronics_profile='saved-profile.json',stop_after_groups=1);self.assertEqual(r['status'],'paused',r['findings'])
        p.write_bytes(b'This external profile has changed\n');self.assertEqual(self.fixture.run(resume=True)['status'],'completed')


def host_acceptance(home,replay_name):
    """Coordinator-only actual host acceptance: ONE NEW derivative, no reference recalculation."""
    source='custom-electronics-500-ak02-v1';reference=ROOT/'.local/replays/m4b-coordinator-host-v2-same'
    frozen=F.snapshot(ROOT/'.local/runs'/source);ref=F.snapshot(reference)
    common=['replay-readout','-Name',source,'-ReplayName',replay_name,'-Detector','AK02','-CheckpointGroups','-Json']
    first=T.command(home/'stop-command.json',[*common,'-StopAfterGroups','1'])
    if first.returncode:raise RuntimeError('Stop command failed; retain output and command receipt')
    dest=ROOT/'.local/replays'/replay_name;stop=json.loads(first.stdout);C.equal(stop['status'],'paused','stopped status')
    C.equal(stop['completed_groups'],1,'one committed group')
    retained={phase:F.snapshot(dest/phase) for phase in ('charge','electronics','calibration','inputs','receipts')};F.save(home/'retained-at-stop.json',retained)
    second=T.command(home/'resume-command.json',[*common,'-Resume'])
    if second.returncode:raise RuntimeError('Resume failed; retain evidence')
    run=F.read(dest/'run.json');C.equal(run['status'],'completed','final status')
    C.equal(run['detectors']['AK02']['counts'],F.read(reference/'run.json')['detectors']['AK02']['counts'],'reference census')
    C.equal((run['detectors']['AK02']['counts']['initial_primaries'],run['detectors']['AK02']['counts']['zero_deposit_primaries'],run['detectors']['AK02']['counts']['native_charge_samples']),(500,496,20008),'source population')
    T.compare(run['detectors']['AK02']['calibration'],F.read(reference/'run.json')['detectors']['AK02']['calibration'],'calibration')
    for n in ('scalars.jsonl','traces.jsonl'):
        T.compare(list(C.Reader(dest).jsonl('worker/AK02/'+n)),list(C.Reader(reference).jsonl('worker/AK02/'+n)),n)
    pulses=[r for r in C.Reader(dest).jsonl('worker/AK02/scalars.jsonl') if r['record_kind']=='pulse']
    C.equal([r['event_id'] for r in pulses],[213,220,325,450],'four original IDs')
    C.equal([r['transport_flags']['step_limits'] for r in pulses],[26,88,35,59],'endpoint flags')
    for phase,files in retained.items():C.require(all(F.snapshot(dest/phase)[n]==tuple(v) for n,v in files.items()),'Committed data rewritten')
    before=F.snapshot(dest)
    with mock.patch.dict(os.environ,JULIA_EXE='INVALID_COMPLETED_RESUME_MUST_NOT_LAUNCH'):
        final=T.command(home/'noop-command.json',[*common,'-Resume'])
    C.equal(final.returncode,0,'completed noop exit');C.equal(F.snapshot(dest),before,'completed no writes')
    C.equal(F.snapshot(ROOT/'.local/runs'/source),frozen,'source exact preservation');C.equal(F.snapshot(reference),ref,'reference exact preservation')
    F.save(home/'COMPLETE.json',dict(status='passed',actual_host_electronics=True,new_derivatives=1,replay_name=replay_name,
           groups=[r['event_id'] for r in pulses],source_unchanged=True,reference_unchanged=True,committed_files_unchanged=True))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--evidence');p.add_argument('--host',action='store_true');p.add_argument('--replay-name')
    p.add_argument('--crash-fixture');p.add_argument('--boundary',choices=('before-receipt','after-receipt'))
    a=p.parse_args()
    if a.crash_fixture:
        root=Path(a.crash_fixture).resolve();C.require(root.is_relative_to(ROOT/'.local/group-checkpoint-v1/implementation'),'Test-only fixture root')
        fixture=Fixture(root);fixture.crash=a.boundary;r=fixture.run(resume=True);print(json.dumps(r));sys.exit(2)
    C.require(a.evidence is not None,'Evidence required');EVIDENCE=(ROOT/a.evidence).resolve()
    C.require(EVIDENCE.is_relative_to(ROOT/'.local/group-checkpoint-v1/implementation'),'Use checkpoint implementation evidence')
    EVIDENCE.mkdir(parents=True,exist_ok=False);F.save(EVIDENCE/'scope.json',dict(actual_host_electronics=a.host,mocked_electronics=not a.host,python=sys.version,executable=sys.executable,argv=sys.argv))
    if a.host:
        C.require(a.replay_name is not None,'Host acceptance requires explicit NEW replay name')
        try:host_acceptance(EVIDENCE,a.replay_name)
        except BaseException as error:F.save(EVIDENCE/'FAILED.json',dict(detail=str(error)));raise
    else:
        result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(GroupTests))
        F.save(EVIDENCE/'RESULT.json',dict(tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),actual_numerical_acceptance=False))
        sys.exit(0 if result.wasSuccessful() else 1)
