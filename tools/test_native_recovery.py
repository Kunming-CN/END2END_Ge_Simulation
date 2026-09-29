"""Public Windows CLI/driver recovery tests with source-only MOCK children.
No physics or runtime executed. Abrupt failure hooks live only in cloned fixture
sources, installed before the driver records hashes. All evidence is retained.
"""
import argparse
import copy
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from electronics_execution_fixture import clone, read, save, sha

ROOT=Path(__file__).resolve().parents[1]
EVIDENCE=None

def snapshot(root):
    return {str(p.relative_to(root)):(sha(p),p.stat().st_size,p.stat().st_mtime_ns)
            for p in root.rglob('*') if p.is_file()}

class Recovery(unittest.TestCase):
    def setUp(self):
        # Stay below Windows Python MAX_PATH even with SHA256 transaction names.
        self.home=EVIDENCE/('c-'+hashlib.sha256(self.id().encode()).hexdigest()[:8]);self.root=self.home/'r';self.seq=0
        clone(ROOT,self.root,Path(sys.executable),recovery=True)
        save(self.home/'test-case.json',dict(test=self.id()))
        self.run=self.root/'.local/runs/run'
    def cmd(self,*args,ok=True):
        self.seq+=1;command=['cmd.exe','/d','/c','Run.cmd',*args]
        got=subprocess.run(command,cwd=self.root,capture_output=True,text=True,errors='replace',timeout=120)
        save(self.home/f'command-{self.seq:03}.json',dict(command=command,cwd=str(self.root),exit_code=got.returncode,stdout=got.stdout,stderr=got.stderr))
        if ok:self.assertEqual(got.returncode,0,got.stdout+got.stderr)
        else:self.assertNotEqual(got.returncode,0,got.stdout+got.stderr)
        return got
    def fault(self,boundary):save(self.root/'recovery-fixture-control.json',dict(boundary=boundary))
    def start(self,boundary='final_child_AK02',custom=False,detector='AK02',preset='smoke'):
        args=[]
        if custom:
            p=read(self.root/'simulation/native_readout_profile.json');p['settings']['gain']=13
            save(self.root/'inputs/custom.json',p)
            self.cmd('settings','save','-SettingsFile','inputs/custom.json','-SaveName','custom','-Json')
            args=['-ElectronicsProfile','.local/electronics-profiles/custom.json']
        self.fault(boundary)
        self.cmd('run','-Name','run','-Preset',preset,'-Detector',detector,*args,ok=not bool(boundary))
        self.fault('')
    def recover(self,*args,ok=True):return self.cmd('recover','-Name','run','-Json',*args,ok=ok)
    def no_write(self,*args,ok=False):
        before=snapshot(self.root);got=self.recover(*args,ok=ok);self.assertEqual(snapshot(self.root),before);return got
    def child(self):return self.run/'AK02/response/run.json'
    def reseal(self,artifact=None):
        p=self.child();r=read(p)
        if artifact:
            f=p.parent/artifact;r['artifacts'][artifact]=sha(f);r['artifact_bytes'][artifact]=f.stat().st_size
            if artifact=='readout-config.json':r['config_sha256']=sha(f)
        save(p,r)
    def test_canonical_recovery_dryrun_idempotence_and_preservation(self):
        self.start();before=(self.run/'run.json').read_bytes();science=snapshot(self.run/'AK02')
        calls=list(self.root.glob('child-call-*'));probes=(self.root/'runtime-probes.log').read_bytes()
        dry=json.loads(self.no_write('-DryRun',ok=True).stdout);self.assertEqual(dry['pending_detectors'],['AK02'])
        self.assertFalse(dry['runtime_readiness_checked']);self.assertEqual(dry['simulations_started'],0)
        self.assertEqual(read(self.root/'native-launch-observed.json')['intent_sha256'],read(self.run/'run.json')['child_launches']['AK02']['sha256'])
        self.recover();parent=read(self.run/'run.json');child=read(self.child())
        self.assertEqual(parent['models']['AK02']['counts'],child['counts']);self.assertEqual(parent['models']['AK02']['native_seconds'],child['native_drift_and_charge_seconds'])
        self.assertEqual(parent['stages'],json.loads(before)['stages']);self.assertEqual(science,snapshot(self.run/'AK02'))
        tx=next((self.run/'recovery-v1').iterdir());self.assertEqual((tx/'parent-before.json').read_bytes(),before)
        self.assertEqual(read(tx/'PREPARED.json')['state'],'PREPARED');self.assertEqual(read(tx/'COMMITTED.json')['state'],'COMMITTED')
        self.no_write(ok=True);self.no_write('-DryRun',ok=True)
        self.assertEqual(list(self.root.glob('child-call-*')),calls);self.assertEqual((self.root/'runtime-probes.log').read_bytes(),probes)
    def test_custom_profile_copies_survive_missing_originals(self):
        self.start(custom=True);(self.root/'.local/electronics-profiles/custom.json').rename(self.home/'saved-original.json')
        (self.root/'inputs/custom.json').rename(self.home/'input-original.json')
        self.recover();self.assertEqual(read(self.child())['profile']['settings']['gain'],13);self.no_write(ok=True)
    def test_complete_parent_is_noop_without_transaction(self):
        self.start(boundary='');self.no_write(ok=True);self.assertFalse((self.run/'recovery-v1').exists())
    def test_child_completed_before_stage_save(self):
        self.start(boundary='child_return');parent=read(self.run/'run.json')
        self.assertFalse(any(s['stage']=='AK02-native-response' for s in parent['stages']))
        self.recover();self.assertEqual(read(self.run/'run.json')['stages'],parent['stages']);self.no_write(ok=True)
    def test_before_intent_after_intent_and_missing_final_boundaries(self):
        for boundary in ['before_intent_AK02','intent_file_AK02','after_intent_AK02']:
            with self.subTest(boundary=boundary):
                self.start(boundary);self.no_write();self.no_write('-DryRun')
                if boundary!='before_intent_AK02':
                    before=snapshot(self.run);self.cmd('resume','-Name','run',ok=False);self.assertEqual(before,snapshot(self.run))
                # Preserve each entire MOCK attempt; never reuse its output name.
                self.run.rename(self.home/boundary)
    def test_legacy_missing_intent_does_not_authorize_orphan(self):
        self.start();p=read(self.run/'run.json');p.pop('child_launches');p.pop('recovery_contract');save(self.run/'run.json',p)
        self.no_write();self.no_write('-DryRun')
    def test_partial_guard_and_artifact_fail_closed(self):
        self.start();rf=self.child();original=rf.read_bytes()
        for mode in ['missing','partial','guard','artifact']:
            with self.subTest(mode=mode):
                r=json.loads(original)
                if mode=='missing':rf.rename(self.home/'preserved-missing-receipt.json')
                else:
                    if mode=='partial':r['status']='running'
                    if mode=='guard':r.pop('boundary_guard')
                    if mode=='artifact':r['artifacts']['truth.jsonl']='0'*64
                    save(rf,r)
                self.no_write();self.no_write('-DryRun');rf.write_bytes(original)
    def test_rehashed_incompatible_configuration_counts_sources_inputs_paths(self):
        self.start(custom=True);rf=self.child();original=rf.read_bytes()
        for key,value in [('seed_family',99),('input_sha256','0'*64),('model_id','SAP22'),('parcels',17)]:
            with self.subTest(key=key):
                r=json.loads(original);r[key]=value;save(rf,r);self.no_write();rf.write_bytes(original)
        r=json.loads(original);r['counts']['initial_decays']=21;save(rf,r);self.no_write();rf.write_bytes(original)
        r=json.loads(original);r['source_sha256']['native_response.jl']='0'*64;save(rf,r);self.no_write();rf.write_bytes(original)
        path=rf.parent/'readout-config.json';cfg=read(path);cfg['gain']=99;save(path,cfg);self.reseal('readout-config.json');self.no_write()
    def test_resealed_intent_paths_settings_and_census_are_independent(self):
        self.start();ip=self.run/'AK02/native-launch-intent.json';ib=ip.read_bytes();pp=self.run/'run.json';pb=pp.read_bytes()
        for key,value in [('output','.local/runs/stolen/AK02/response'),('events',500),('arguments',['--inspect']),('guard_required',False)]:
            intent=json.loads(ib);intent[key]=value;save(ip,intent);parent=json.loads(pb);parent['child_launches']['AK02']['sha256']=sha(ip);save(pp,parent)
            self.no_write();ip.write_bytes(ib);pp.write_bytes(pb)
        intent=json.loads(ib);intent['configuration']['gain']=99;save(ip,intent);parent=json.loads(pb);parent['child_launches']['AK02']['sha256']=sha(ip);save(pp,parent);self.no_write()
    def test_resealed_consumer_source_is_still_bound_by_prelaunch_intent(self):
        self.start();source=self.root/'simulation/test_native_stream.jl';source.write_bytes(source.read_bytes()+b'\n# TEST mutation\n')
        r=read(self.child());r['source_sha256']['test_native_stream.jl']=sha(source);save(self.child(),r)
        self.no_write();self.no_write('-DryRun')
    def test_resealed_input_copy_and_parent_count_mismatch(self):
        self.start();path=self.child().parent/'input-contract.json';m=read(path);m['units']['time']='us';save(path,m);self.reseal('input-contract.json');self.no_write()
    def test_durable_prepared_revalidates_after_failure_and_marker_corruption(self):
        self.start();self.fault('prepared_receipt');self.recover(ok=False);self.fault('')
        artifact=self.child().parent/'truth.jsonl';old=artifact.read_bytes();artifact.write_bytes(b'corrupt');self.no_write();artifact.write_bytes(old)
        self.recover();tx=next((self.run/'recovery-v1').iterdir());save(tx/'COMMITTED.json',dict(state='PREPARED'));self.no_write()
    def test_stolen_directory_and_missing_bound_child(self):
        self.start();self.run.rename(self.root/'.local/runs/stolen')
        before=snapshot(self.root);self.cmd('recover','-Name','stolen','-Json',ok=False);self.assertEqual(before,snapshot(self.root))
        (self.root/'.local/runs/stolen').rename(self.run);self.recover()
        (self.run/'AK02/response').rename(self.home/'preserved-bound-child');self.no_write()
        before=snapshot(self.run);self.cmd('resume','-Name','run',ok=False);self.assertEqual(before,snapshot(self.run))
    def test_missing_and_held_lock(self):
        self.start();lock=self.run/'run.lock';lock.rename(self.home/'preserved-lock');self.no_write();(self.home/'preserved-lock').rename(lock)
        kernel=ctypes.WinDLL('kernel32',use_last_error=True);kernel.CreateFileW.restype=ctypes.c_void_p
        kernel.CreateFileW.argtypes=[ctypes.c_wchar_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p]
        handle=kernel.CreateFileW(str(lock),0x80000000,0,None,3,0,None)
        self.assertNotEqual(handle,ctypes.c_void_p(-1).value)
        try:
            # Snapshot cannot read an exclusively held file, so exclude only lock bytes.
            before=snapshot(self.run/'AK02');self.recover(ok=False);self.assertEqual(before,snapshot(self.run/'AK02'));self.assertFalse((self.run/'recovery-v1').exists())
        finally:kernel.CloseHandle(ctypes.c_void_p(handle))
    def test_rejects_all_unrelated_explicit_defaults(self):
        for args in [('-Preset','demo'),('-Detector','both'),('-Seed','26092631'),('-Scenario','lbnl-cs137'),('-Pilot','unused'),('-BuildExporter',),('-Open',),('-SettingsMode','interactive'),('-View','simple'),('-ElectronicsProfile','unused'),('-SettingsFile','unused'),('-CompareTo','unused'),('-SetJson','{}'),('-SaveName','unused')]:
            self.no_write(*args)
    def test_every_transaction_boundary(self):
        self.start();baseline=self.home/'interrupted-baseline';shutil.copytree(self.root,baseline)
        for boundary in ['transaction_directory','before_bytes','after_bytes','prepared_receipt','replacement_bytes','parent_replaced','committed_marker']:
            with self.subTest(boundary=boundary):
                self.fault(boundary);self.recover(ok=False);self.fault('')
                self.no_write('-DryRun',ok=True)
                tx=next((self.run/'recovery-v1').iterdir());before=read(tx/'parent-before.json') if (tx/'parent-before.json').exists() else read(self.run/'run.json')
                stages=before['stages'];self.recover();self.no_write(ok=True)
                self.assertEqual(read(self.run/'run.json')['stages'],stages)
                self.assertEqual(read(tx/'COMMITTED.json')['state'],'COMMITTED')
                self.root.rename(self.home/('finished-'+boundary));shutil.copytree(baseline,self.root)
    def test_prepared_neither_parent_and_corrupt_staging_block(self):
        self.start();self.fault('prepared_receipt');self.recover(ok=False);self.fault('')
        pp=self.run/'run.json';original=pp.read_bytes();p=read(pp);p['unrelated_edit']=True;save(pp,p);self.no_write();pp.write_bytes(original)
        tx=next((self.run/'recovery-v1').iterdir());(tx/'parent-after.json').write_text('{}');self.no_write('-DryRun');self.no_write()
    def test_native_failures_preserve_nulls_and_zeros(self):
        self.start(preset='demo');rp=self.child();r=read(rp);r['status']='completed_with_native_failures'
        r['counts'].update(accepted=0,rejected=1,native_failed_groups=1,native_charge_samples=0,analog_samples=0)
        save(rp.parent/'native-failures.jsonl',dict(test_only=True,charge=None,endpoint=None,readout=None,error='Invalid waveform support'))
        save(rp.parent/'scalars.jsonl',dict(test_only=True,charge=None,endpoint=None,readout=None))
        save(rp.parent/'histograms.json',dict(width_keV=5,normalization_denominators=r['counts']))
        for name in ['native-failures.jsonl','histograms.json','scalars.jsonl']:
            r['artifacts'][name]=sha(rp.parent/name);r['artifact_bytes'][name]=(rp.parent/name).stat().st_size
        save(rp,r);science=snapshot(rp.parent);self.recover()
        self.assertEqual(read(self.run/'run.json')['status'],'completed_with_native_failures');self.assertEqual(science,snapshot(rp.parent))
        self.assertEqual(read(self.run/'run.json')['models']['AK02']['counts']['zero_deposit_primaries'],499)
    def test_sequential_detector_boundaries(self):
        self.start(detector='both');self.recover();parent=read(self.run/'run.json')
        self.assertEqual(parent['status'],'nonterminal_recovered');self.assertNotIn('SAP22',parent['models']);self.assertFalse((self.run/'SAP22').exists())
        self.no_write() # no new completed child: no duplicate transaction
        self.fault('final_child_SAP22');self.cmd('resume','-Name','run',ok=False);self.fault('')
        self.recover();parent=read(self.run/'run.json');self.assertEqual(parent['status'],'completed_provisional_native_campaign')
        self.assertEqual(set(parent['models']),{'AK02','SAP22'});self.no_write(ok=True)
    def test_other_incomplete_transport_remains_nonterminal(self):
        self.start(detector='both');path=self.run/'SAP22/transport';path.mkdir(parents=True);(path/'partial.log').write_text('TEST interrupted transport')
        before=snapshot(path);self.recover();self.assertEqual(read(self.run/'run.json')['status'],'nonterminal_recovered');self.assertEqual(before,snapshot(path))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--evidence',required=True);parser.add_argument('tests',nargs='*');opts=parser.parse_args()
    EVIDENCE=(ROOT/opts.evidence).resolve()
    if not EVIDENCE.is_relative_to(ROOT/'.local/recovery-plan-v1/implementation'):parser.error('Use recovery implementation evidence directory')
    EVIDENCE.mkdir(parents=True,exist_ok=False)
    save(EVIDENCE/'scope.json',dict(test_only=True,scientific_execution=False,python=sys.executable,argv=sys.argv))
    shutil.copy2(__file__,EVIDENCE/'executed_test.py')
    unittest.main(argv=[__file__,*opts.tests],verbosity=2)
