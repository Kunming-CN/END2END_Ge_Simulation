"""M4b software fixtures, public dispatch and OPTIONAL actual Julia acceptance.

Default tests explicitly mock runtime/electronics; they are not physics or
numerical acceptance. --real executes the unchanged readout modules with Julia
on the specified stored source, then one threshold-only derivative. No transport.
Every fixture and failed attempt is retained below the supplied evidence root.
"""
import argparse
import copy
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest import mock

import charge_check as C
import replay_readout as R
import test_charge_check as F

ROOT=Path(__file__).resolve().parents[1]
EVIDENCE=None


def command(home,args,root=ROOT,timeout=660):
    argv=['cmd.exe','/d','/c','Run.cmd',*args]
    before=F.snapshot(root/'.local/runs')
    got=subprocess.run(argv,cwd=root,env=dict(os.environ,SITE_PYTHON=sys.executable,PYTHONDONTWRITEBYTECODE='1'),capture_output=True,text=True,timeout=timeout)
    F.save(home,dict(arguments=argv,cwd=str(root),exit_code=got.returncode,stdout=got.stdout,stderr=got.stderr,
                     source_unchanged=before==F.snapshot(root/'.local/runs')))
    if before!=F.snapshot(root/'.local/runs'):raise AssertionError('Source checksum/size/mtime changed')
    return got


def tiny_worker(dest,request):
    """TEST ONLY synthetic outputs. No numerical calculation or scientific claim."""
    report=dict(kind='electronics_replay_worker_v1',status='worker_complete_untrusted',runtime={'executable':sys.executable},detectors={},artifacts={})
    for d in request['detectors']:
        m=d['model']; c=d['config']; factor=1000/d['eion']*1.602176634e-19; lsb=c['adc_full_scale_V']/2**c['adc_bits']
        counts=dict.fromkeys(R.COUNT_FIELDS,0); output=[]; traces=[]
        for rec in C.Reader(dest).jsonl('inputs/'+m+'/scalars.jsonl'):
            if rec['record_kind']=='decay':
                counts['initial_primaries']+=1;counts['zero_deposit_primaries']+=rec['zero_deposit']
            else:
                counts['groups']+=1;counts['rejected']+=1
                if rec.get('status')=='native_transport_failed':counts['native_failed_groups']+=1
                else:
                    r={k:False for k in R.READOUT_FIELDS}
                    r.update(accepted=False,adc_code=0,adc_midpoint_V=.5*lsb,analog_energy_keV=0.,peak_V=0.,peak_time_ns=0.,
                             rejection_reason='below_threshold',reconstructed_energy_keV=None,below_threshold=True,
                             nonpositive_peak=True,negative_input=True,peak_policy=c['peak_policy'],
                             charge_end_ns=4.,final_charge_C=-2*factor,input_sample_count=3,original_sample_count=50000,
                             isolated_horizon_ns=100000,electronics_state='reset_nominal_isolated_window',readout_end_ns=99998,
                             tail_window_ns=99994,tail_truncated_possible=True,untruncated_charge_end_ns=4.,
                             untruncated_final_charge_keV=-2.,current_balance=dict(passed=True),
                             peak_gate_start_ns=0.,peak_gate_end_ns=99998.,preamp_min_V=0.,preamp_max_V=0.,
                             preamp_peak_charge_equivalent_keV=0.)
                    rec.update(readout=r,accepted=False,rejection_reason='below_threshold',trace_saved=True)
                    counts['readout_rejected']+=1;counts['native_charge_samples']+=3;counts['analog_samples']+=50000
                    tr=dict(time_ns=[0.,4.,99998.],induced_charge_fC=[0.,-2*factor*1e15,-2*factor*1e15],
                            current_bin_start_ns=[0.,2.,99996.],current_bin_end_ns=[0.,4.,99998.],
                            current_nA=[0.,-factor/2*1e18,0.],preamp_V=[0.,0.,0.],shaped_V=[0.,0.,0.])
                    traces.append(dict(event_id=rec['event_id'],global_decay_id=rec['global_decay_id'],group_id=rec['group_id'],origin_time_ns=rec['origin_time_ns'],trace=tr))
            output.append(rec)
        folder=dest/'worker'/m;folder.mkdir(parents=True)
        F.jsonl(folder/'scalars.jsonl',output);F.jsonl(folder/'traces.jsonl',traces)
        cal=dict(method='single delta-charge injection at t=0; sampled analog peak; fixed across events',
                 energy_keV=c['calibration_energy_keV'],charge_C=c['calibration_energy_keV']*factor,
                 ionisation_energy_eV=d['eion'],peak_V=1.,peak_time_ns=1000.,volts_per_keV=1/c['calibration_energy_keV'],
                 time_step_ns=2,adc_lsb_V=lsb)
        report['detectors'][m]=dict(counts=counts,calibration=cal,config=c,electronics_seconds=0.)
        report['artifacts'].update({m+'/'+n:F.sha(folder/n) for n in ('scalars.jsonl','traces.jsonl')})
    F.save(dest/'worker/report.json',report)
    return report


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.home=EVIDENCE/self.id().split('.')[-1];self.root=self.home/'root'
        F.fixture(self.root)
        for n in R.SOURCES:
            dest=self.root/n;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/n,dest)
        self.run=self.root/'.local/runs/synthetic';self.base=self.run/'AK02/response'
        self.calls=[];self.fault=None

    def fake_child(self,argv,cwd,**kwargs):
        self.calls.append(argv)
        result=dict(arguments=argv,exit_code=0,wall_seconds=0,output=json.dumps({'executable':sys.executable}),output_limit_exceeded=False)
        if argv[-1]=='--probe':
            if self.fault=='runtime':result.update(exit_code=1,output='TEST runtime incompatible')
            return result
        dest=Path(argv[-1]).parent
        if self.fault=='exit':result.update(exit_code=7,output='TEST child failed');return result
        if self.fault=='incomplete':return result
        req=F.read(dest/'request.json');tiny_worker(dest,req)
        if self.fault=='malformed-output':
            p=dest/'worker/AK02/scalars.jsonl';rows=[json.loads(x) for x in p.read_text().splitlines()];rows[1]['readout']['adc_code']=3;F.jsonl(p,rows)
            report=F.read(dest/'worker/report.json');report['artifacts']['AK02/scalars.jsonl']=F.sha(p);F.save(dest/'worker/report.json',report)
        return result

    def replay(self,**kwargs):
        def mocked_runtime(reader,runtime,inspection,exe):
            runtime.update(launcher_executable=exe,launcher_sha256=F.sha(Path(exe)),executable_sha256=F.sha(Path(exe)))
        with mock.patch.object(R,'child',side_effect=self.fake_child),mock.patch.object(R,'julia_executable',return_value=sys.executable),mock.patch.object(R,'verify_runtime',side_effect=mocked_runtime):
            return R.replay_run(self.root,'synthetic','new',**kwargs)

    def test_public_dryrun_no_write_no_julia(self):
        before=F.snapshot(self.root)
        with mock.patch.dict(os.environ,JULIA_EXE='MISSING_JULIA_MUST_NOT_RUN'):
            got=command(self.home/'cli.json',['replay-readout','-Name','synthetic','-ReplayName','new','-DryRun','-Json'],self.root)
        self.assertEqual(got.returncode,0,got.stderr);r=json.loads(got.stdout)
        self.assertEqual(r['status'],'planned');self.assertFalse(r['output_reserved']);self.assertEqual(r['scientific_workers_launched'],0)
        self.assertEqual(r['runtime_verified'],'NOT_CHECKED');self.assertEqual(F.snapshot(self.root),before)

    def test_unrelated_public_flags_and_missing_name_rejected(self):
        for i,args in enumerate((['-Seed','26092631'],['-Preset','demo'],['-SettingsMode','check'],['-ElectronicsProfile',''],['-BadFlag','1'])):
            got=command(self.home/f'cli-{i}.json',['replay-readout','-Name','synthetic','-ReplayName','new','-DryRun',*args],self.root)
            self.assertNotEqual(got.returncode,0)
        got=command(self.home/'missing.json',['replay-readout','-Name','synthetic','-DryRun'],self.root)
        self.assertNotEqual(got.returncode,0);self.assertFalse((self.root/'.local/replays').exists())

    def test_unsupported_runtime_refused_before_reservation(self):
        self.fault='runtime';r=self.replay();self.assertEqual(r['status'],'blocked');self.assertFalse((self.root/'.local/replays').exists())

    def test_source_lease_retained_during_child(self):
        old=self.fake_child
        def checked(*args,**kwargs):
            with self.assertRaises(C.Rejected):
                with C.existing_lock(C.Reader(self.root),'.local/runs/synthetic/run.lock'):pass
            return old(*args,**kwargs)
        self.fake_child=checked
        r=self.replay();self.assertEqual(r['status'],'completed',r['findings']);self.assertTrue(r['verification_final'])
        F.save(self.home/'mocked-result.json',r)

    def test_zero_native_failure_signed_synthetic_ledger(self):
        # Explicitly MOCKED electronics, real strict inspection and reconciliation.
        self.root=self.home/'failure-root';F.fixture(self.root,fail=True)
        for n in R.SOURCES:
            dest=self.root/n;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/n,dest)
        self.run=self.root/'.local/runs/synthetic';self.base=self.run/'AK02/response'
        r=self.replay();self.assertEqual(r['status'],'completed_with_native_failures',r['findings'])
        counts=r['detectors']['AK02']['counts'];self.assertEqual(counts['initial_primaries'],3);self.assertEqual(counts['zero_deposit_primaries'],1)
        self.assertEqual(counts['native_failed_groups'],1);self.assertEqual(counts['readout_rejected'],1)
        rows=[json.loads(x) for x in (self.root/'.local/replays/new/worker/AK02/scalars.jsonl').read_text().splitlines()]
        pulse=next(row for row in rows if row['record_kind']=='pulse')
        self.assertTrue(pulse['readout']['negative_input']);self.assertIsNone(rows[-1]['readout']);self.assertEqual(rows[-1]['native_error']['exact_error'],'ArgumentError: Invalid waveform support')

    def test_child_failure_retains_failed_receipt(self):
        self.fault='exit';r=self.replay();self.assertEqual(r['status'],'failed');self.assertFalse(r['verification_final'])
        self.assertEqual(F.read(self.root/'.local/replays/new/run.json')['status'],'failed');self.assertIn('TEST child failed',(self.root/'.local/replays/new/worker.log').read_text())

    def test_child_exit_zero_incomplete_rejected(self):
        self.fault='incomplete';r=self.replay();self.assertEqual(r['status'],'failed');self.assertFalse(r['verification_final'])

    def test_rehashed_wrong_adc_output_rejected(self):
        self.fault='malformed-output';r=self.replay();self.assertEqual(r['status'],'failed');self.assertFalse(r['verification_final'])

    def test_no_overwrite_repeat_even_failed(self):
        self.fault='exit';self.replay();before=F.snapshot(self.root/'.local/replays');self.calls=[]
        r=self.replay();self.assertEqual(r['status'],'blocked');self.assertEqual(self.calls,[]);self.assertEqual(F.snapshot(self.root/'.local/replays'),before)

    def test_concurrent_reservation_collision(self):
        old=self.fake_child
        def collision(*args,**kwargs):
            out=old(*args,**kwargs)
            if args[0][-1]=='--probe':(self.root/'.local/replays/new').mkdir(parents=True)
            return out
        self.fake_child=collision;r=self.replay();self.assertEqual(r['status'],'blocked');self.assertFalse((self.root/'.local/replays/new/run.json').exists())

    def test_missing_and_held_source_lock(self):
        with C.existing_lock(C.Reader(self.root),'.local/runs/synthetic/run.lock'):
            self.assertEqual(self.replay()['status'],'blocked')
        (self.run/'run.lock').unlink();self.assertEqual(self.replay()['status'],'blocked');self.assertFalse((self.root/'.local/replays').exists())

    def test_source_change_after_verified_child_invalidates(self):
        original=R.verify_outputs
        def mutate(*args):
            checked=original(*args);p=self.base/'signals.csv';p.write_bytes(p.read_bytes()+b'\n');return checked
        with mock.patch.object(R,'verify_outputs',side_effect=mutate):r=self.replay()
        self.assertEqual(r['status'],'failed');self.assertFalse(r['verification_final']);self.assertFalse(r['inspection']['storage_complete'])

    def test_source_mtime_only_change_rejected(self):
        original=R.verify_outputs
        def mutate(*args):
            checked=original(*args);p=self.base/'signals.csv';st=p.stat();os.utime(p,ns=(st.st_atime_ns,st.st_mtime_ns+1000000000));return checked
        with mock.patch.object(R,'verify_outputs',side_effect=mutate):r=self.replay()
        self.assertEqual(r['status'],'failed');self.assertFalse(r['verification_final'])

    def test_input_snapshot_changed_after_child_rejected(self):
        old=self.fake_child
        def mutate(*args,**kwargs):
            result=old(*args,**kwargs)
            if args[0][-1]!='--probe':
                p=Path(args[0][-1]).parent/'inputs/AK02/signals.csv';p.write_bytes(p.read_bytes()+b'\n')
            return result
        self.fake_child=mutate;r=self.replay();self.assertEqual(r['status'],'failed')

    def test_malformed_missing_truncated_duplicate_nonfinite_charge(self):
        original=(self.base/'signals.csv').read_bytes()
        cases=(b'malformed\n',b'\n'.join(original.splitlines()[:-1])+b'\n',original+original.splitlines()[-1]+b'\n',original.replace(b'-1.0',b'NaN'))
        for data in cases:
            (self.base/'signals.csv').write_bytes(data);F.refresh(self.root);self.calls=[]
            self.assertEqual(self.replay()['status'],'blocked');self.assertEqual(self.calls,[])
        (self.base/'signals.csv').unlink();self.assertEqual(self.replay()['status'],'blocked')

    def test_incompatible_source_and_unsupported_format(self):
        p=self.root/'simulation/readout.jl';p.write_bytes(p.read_bytes()+b'\n');r=self.replay();self.assertEqual(r['status'],'blocked');self.assertEqual(self.calls,[])
        parent=F.read(self.run/'run.json');parent['kind']='serialized';F.save(self.run/'run.json',parent)
        self.assertEqual(self.replay()['status'],'blocked')

    def test_malformed_settings_configuration_refused(self):
        p=F.read(self.base/'profile.json');p['settings']['gain']=True;F.save(self.root/'profile.json',p)
        before=F.snapshot(self.root)
        r=R.replay_run(self.root,'synthetic','new',electronics_profile='profile.json',dry_run=True)
        self.assertEqual(r['status'],'blocked');self.assertEqual(F.snapshot(self.root),before)

    def test_real_profile_and_bundle_contract_dryrun(self):
        profile=F.read(self.base/'profile.json');profile['settings']['threshold_V']=1.
        F.save(self.root/'profile.json',profile)
        r=R.replay_run(self.root,'synthetic','new',electronics_profile='profile.json',dry_run=True)
        self.assertEqual(r['status'],'planned',r['findings']);self.assertEqual(r['configuration'][0]['config']['threshold_V'],1.)
        sources={n:F.sha(self.root/n) for n in C.ES_SOURCES};conf=dict(r['configuration'][0]['config'],expected_primary_count=None)
        bundle=dict(schema_version=1,kind='electronics_settings_bundle_v1',revision=1,profile=profile,configuration=conf,physics_sha256=C.settings_physics_hash(conf),provenance=dict(input=dict(path='profile.json',sha256=F.sha(self.root/'profile.json'),schema_version=2,kind=profile['kind']),defaults=dict(path='simulation/readout_demo.json',sha256=sources['simulation/readout_demo.json'],schema_version=1),sources_sha256=sources))
        F.save(self.root/'bundle.json',bundle)
        r=R.replay_run(self.root,'synthetic','new',electronics_profile='bundle.json',dry_run=True);self.assertEqual(r['status'],'planned',r['findings'])
        bundle['configuration']['gain']=2.;bundle['physics_sha256']=C.settings_physics_hash(bundle['configuration']);F.save(self.root/'bundle.json',bundle)
        r=R.replay_run(self.root,'synthetic','new',electronics_profile='bundle.json',dry_run=True);self.assertEqual(r['status'],'blocked')

    def test_gate_needs_two_samples_before_runtime(self):
        for start,stop in ((0,1),(.1,1.9),(.1,2.1)):
            profile=F.read(self.base/'profile.json')
            profile['settings'].update(peak_gate_start_ns=start,peak_gate_end_ns=stop)
            F.save(self.root/'invalid-gate.json',profile)
            for dry in (True,False):
                with self.subTest(start=start,stop=stop,dry_run=dry):
                    before=F.snapshot(self.root)
                    with mock.patch.object(R,'julia_executable',side_effect=AssertionError('Julia must not be selected')) as runtime:
                        r=R.replay_run(self.root,'synthetic','invalid',electronics_profile='invalid-gate.json',dry_run=dry)
                    runtime.assert_not_called()
                    self.assertEqual(r['status'],'blocked')
                    self.assertEqual(r['findings'][-1]['code'],'not_supported')
                    self.assertIn('at least two',r['findings'][-1]['detail'])
                    self.assertEqual(before,F.snapshot(self.root))
        profile['settings'].update(peak_gate_start_ns=.1,peak_gate_end_ns=4.1)
        self.assertEqual(R.expected_config(C.Reader(self.root),profile,3)['peak_gate_end_ns'],4.1)

    def test_public_single_sample_gate_refuses_without_output(self):
        profile=F.read(self.base/'profile.json');profile['settings'].update(peak_gate_start_ns=0,peak_gate_end_ns=1)
        F.save(self.root/'invalid-gate.json',profile)
        for dry in (True,False):
            args=['replay-readout','-Name','synthetic','-ReplayName','invalid','-ElectronicsProfile','invalid-gate.json','-Json']
            if dry:args+=['-DryRun']
            before=F.snapshot(self.root)
            with mock.patch.dict(os.environ,{'JULIA_EXE':str(self.home/'missing-julia.exe')}):
                p=command(self.home/('gate-cli-'+str(dry)+'.json'),args,root=self.root)
            r=json.loads(p.stdout)
            self.assertEqual(p.returncode,2)
            self.assertEqual(r['status'],'blocked')
            self.assertEqual(r['findings'][-1]['code'],'not_supported')
            self.assertIn('at least two',r['findings'][-1]['detail'])
            self.assertNotIn('Traceback',p.stderr)
            self.assertEqual(before,F.snapshot(self.root))
            self.assertFalse((self.root/'.local/replays/invalid').exists())

    def test_explicit_empty_profile_never_falls_back(self):
        before=F.snapshot(self.root)
        for value in ('',False,0):
            with self.subTest(value=value):
                with mock.patch.object(R,'julia_executable',side_effect=AssertionError('No runtime')) as runtime:
                    r=R.replay_run(self.root,'synthetic','empty',electronics_profile=value,dry_run=True)
                runtime.assert_not_called()
                self.assertEqual(r['status'],'blocked')
                self.assertEqual(r['findings'][-1]['code'],'invalid_profile')
                self.assertEqual(before,F.snapshot(self.root))
        argv=[sys.executable,'--no-mpi','--disable-registry','-B',str(self.root/'tools/replay_readout.py'),
              '--name','synthetic','--replay-name','empty','--electronics-profile=','--dry-run','--json']
        p=subprocess.run(argv,capture_output=True,text=True,timeout=30)
        F.save(self.home/'empty-python-cli.json',dict(command=argv,exit_code=p.returncode,stdout=p.stdout,stderr=p.stderr))
        r=json.loads(p.stdout)
        self.assertEqual(p.returncode,2)
        self.assertEqual(r['status'],'blocked')
        self.assertEqual(r['findings'][-1]['code'],'invalid_profile')
        self.assertEqual(before,F.snapshot(self.root))

    def test_non_grid_gate_uses_sampled_boundaries(self):
        """Synthetic verifier contract, not a calculated physical waveform."""
        for tick in (2,4):
            with self.subTest(sampled_peak_ns=tick):
                dest=self.home/('gate-'+str(tick));(dest/'inputs/AK02').mkdir(parents=True)
                for name in ('signals.csv','scalars.jsonl'):
                    shutil.copyfile(self.base/name,dest/'inputs/AK02'/name)
                c=F.read(self.base/'readout-config.json');c.update(peak_gate_start_ns=.1,peak_gate_end_ns=4.1)
                req={'detectors':[dict(model='AK02',config=c,eion=2.95,dt=2,primary_count=3)]}
                report=tiny_worker(dest,req);folder=dest/'worker/AK02'
                rows=[json.loads(s) for s in (folder/'scalars.jsonl').read_text().splitlines()]
                traces=[json.loads(s) for s in (folder/'traces.jsonl').read_text().splitlines()]
                lsb=c['adc_full_scale_V']/2**c['adc_bits'];peak=.002;code=math.floor(peak/lsb)
                factor=1000/2.95*1.602176634e-19
                for row in rows:
                    if row['record_kind']!='pulse':continue
                    row['rejection_reason']='peak_at_gate_boundary'
                    row['readout'].update(peak_V=peak,peak_time_ns=float(tick),adc_code=code,
                        adc_midpoint_V=(code+.5)*lsb,analog_energy_keV=peak*500,
                        below_threshold=False,nonpositive_peak=False,explicit_peak_gate=True,
                        gate_limited=True,peak_gate_start_ns=2.,peak_gate_end_ns=4.,
                        rejection_reason='peak_at_gate_boundary')
                for row in traces:
                    row['trace'].update(time_ns=[0.,2.,4.,99998.],
                        current_bin_start_ns=[0.,0.,2.,99996.],current_bin_end_ns=[0.,2.,4.,99998.],
                        induced_charge_fC=[0.,-factor*1e15,-2*factor*1e15,-2*factor*1e15],
                        current_nA=[0.,-factor/2*1e18,-factor/2*1e18,0.],preamp_V=[0.]*4,
                        shaped_V=[0.,peak if tick==2 else 0.,peak if tick==4 else 0.,0.])
                F.jsonl(folder/'scalars.jsonl',rows);F.jsonl(folder/'traces.jsonl',traces)
                report['artifacts']={n:F.sha(dest/'worker'/n) for n in report['artifacts']}
                F.save(dest/'worker/report.json',report)
                got=R.verify_outputs(C.Reader(self.root),C.Reader(dest),req,report['runtime'])
                self.assertEqual(got['detectors']['AK02']['counts']['readout_rejected'],2)

    def test_sample_budget_refused(self):
        p=F.read(self.base/'profile.json');p['settings']['shaping_tau_us']=1000;F.save(self.root/'profile.json',p)
        r=R.replay_run(self.root,'synthetic','new',electronics_profile='profile.json',dry_run=True);self.assertEqual(r['status'],'blocked');self.assertFalse((self.root/'.local/replays').exists())

    def test_total_charge_budget_refused_in_dryrun(self):
        original=C._inspect_leased
        def injected(*args):
            original(*args);args[-1]['detectors'][0]['stored_samples']=2_000_001
        with mock.patch.object(C,'_inspect_leased',side_effect=injected):r=self.replay(dry_run=True)
        self.assertEqual(r['status'],'blocked');self.assertEqual(self.calls,[])
        self.assertFalse((self.root/'.local/replays').exists())

    def test_child_output_and_timeout_bounds_actual_python(self):
        big=R.child([sys.executable,'-c','print("x"*20000)'],str(self.root),timeout=10,limit=1024)
        self.assertTrue(big['output_limit_exceeded']);self.assertLessEqual(len(big['output']),1024)
        with self.assertRaises(subprocess.TimeoutExpired):R.child([sys.executable,'-c','import time;time.sleep(2)'],str(self.root),timeout=.1)

    def test_direct_worker_cannot_write_outer_receipt(self):
        source=(ROOT/'simulation/replay_readout.jl').read_text()
        self.assertNotIn('native_response',source);self.assertNotIn('using SolidStateDetectors',source)
        self.assertNotIn('"run.json"',source);self.assertIn('worker_complete_untrusted',source)

    def test_runtime_identity_and_inventory_checks_synthetic(self):
        # Assertions on invented probe data, not a successfully loaded Julia.
        runtime=dict(julia_version='1.13.0',pinned_julia_version='1.13.0',json_version='1.9.0',
                     ssd_loaded=False,threads=2,active_project=str((self.root/'simulation/Project.toml').resolve()),
                     process_source=str((self.root/'simulation/readout_profiles.jl').resolve()),readout_module='Main.ReadoutProfiles',
                     executable=sys.executable,json_source_sha256='0'*64,
                     source_sha256={n:F.sha(self.root/'simulation'/n) for n in ('readout.jl','readout_profiles.jl','readout_demo.json','replay_readout.jl')},
                     project_sha256=F.sha(self.root/'simulation/Project.toml'),manifest_sha256=F.sha(self.root/'simulation/Manifest.toml'))
        inspection={'detectors':[{'provenance':{'recorded_readout_environment':{'json_source_sha256':'0'*64}}}]}
        R.verify_runtime(C.Reader(self.root),copy.deepcopy(runtime),inspection,sys.executable)
        for key,value in dict(julia_version='1.13.1',json_version='1.8.0',ssd_loaded=True,threads=1,
                              active_project='wrong',process_source='wrong',readout_module='Other',manifest_sha256='f'*64,
                              json_source_sha256='f'*64,source_sha256={}).items():
            candidate=copy.deepcopy(runtime);candidate[key]=value
            with self.assertRaises(C.Rejected):R.verify_runtime(C.Reader(self.root),candidate,inspection,sys.executable)


def compare(actual,expected,path=''):
    """Predeclared numerical gates; exact categorical/clock/ADC fields."""
    if isinstance(expected,dict):
        if set(actual)!=set(expected):raise AssertionError('Keys: '+path)
        for k,v in expected.items():compare(actual[k],v,path+'.'+k)
    elif isinstance(expected,list):
        if len(actual)!=len(expected):raise AssertionError('Length: '+path)
        for a,b in zip(actual,expected):compare(a,b,path)
    elif type(expected) in (int,float) and path.endswith(('_V','_keV','_C','_nA','_fC')):
        atol=1e-25 if path.endswith('_C') else 1e-8 if path.endswith(('_keV','_fC','_nA')) else R.V_ATOL
        if not math.isclose(actual,expected,rel_tol=R.RTOL,abs_tol=atol):raise AssertionError('Numerical gate: '+path)
    elif type(actual)!=type(expected) and not (type(actual) in (int,float) and type(expected) in (int,float)) or actual!=expected:
        raise AssertionError('Exact field: '+path)


def real_acceptance(home, same_name, changed_name):
    """Exactly two new electronics derivatives; no successful run is repeated."""
    source='custom-electronics-500-ak02-v1';base=ROOT/'.local/runs'/source/'AK02/response'
    frozen=F.snapshot(ROOT/'.local/runs'/source)
    gates=dict(voltage_absolute_V=R.V_ATOL,relative=R.RTOL,energy_absolute_keV=1e-8,charge_absolute_C=1e-25,
               exact=['peak times','ADC codes','acceptance/reasons','counts','clocks','identities','endpoint flags'],
               sensitivity='Floating propagation may change analog roundoff; gates are fixed before execution. ADC and threshold decisions remain exact; no gate loosening.',
               variation=dict(setting='threshold_V',value=1.0,expectation='Same calibration, analog fields, times and ADC codes; all four peaks below 1 V become below_threshold; all 500 primaries/496 zeros remain.'))
    F.save(home/'gates-before-execution.json',gates)
    same=command(home/'same-command.json',['replay-readout','-Name',source,'-ReplayName',same_name,'-Detector','AK02','-Json'])
    if same.returncode:raise RuntimeError('Same-setting replay blocked/failed; see same-command.json')
    same_root=ROOT/'.local/replays'/same_name;sr=F.read(same_root/'run.json')
    C.equal(sr['verification_final'],True,'trusted same replay');C.equal(sr['status'],'completed','same status')
    original=F.read(base/'run.json');compare(sr['detectors']['AK02']['calibration'],original['calibration'],'calibration')
    old=[json.loads(x) for x in (base/'scalars.jsonl').read_text().splitlines()]
    new=[json.loads(x) for x in (same_root/'worker/AK02/scalars.jsonl').read_text().splitlines()]
    compare(new,old,'scalars')
    compare([json.loads(x) for x in (same_root/'worker/AK02/traces.jsonl').read_text().splitlines()],
            [json.loads(x) for x in (base/'traces.jsonl').read_text().splitlines()],'traces')
    expected_counts={k:original['counts'][k] for k in R.COUNT_FIELDS};C.equal(sr['detectors']['AK02']['counts'],expected_counts,'same counts')
    profile=F.read(base/'profile-input.json');profile['settings']['threshold_V']=1.
    F.save(home/'threshold-profile.json',profile)
    changed=command(home/'changed-command.json',['replay-readout','-Name',source,'-ReplayName',changed_name,'-Detector','AK02','-ElectronicsProfile',(home/'threshold-profile.json').relative_to(ROOT).as_posix(),'-Json'])
    if changed.returncode:raise RuntimeError('Changed-setting replay blocked/failed; see changed-command.json')
    cr=F.read(ROOT/'.local/replays'/changed_name/'run.json');C.equal(cr['verification_final'],True,'trusted changed replay')
    compare(cr['detectors']['AK02']['calibration'],sr['detectors']['AK02']['calibration'],'calibration')
    changed_rows=[json.loads(x) for x in (ROOT/'.local/replays'/changed_name/'worker/AK02/scalars.jsonl').read_text().splitlines()]
    for a,b in zip(new,changed_rows):
        if a['record_kind']=='decay':C.equal(a,b,'all primary ledger');continue
        C.equal(b['accepted'],False,'threshold selection');C.equal(b['rejection_reason'],'below_threshold','threshold reason')
        C.equal({k:v for k,v in a.items() if k not in ('readout','accepted','rejection_reason')},{k:v for k,v in b.items() if k not in ('readout','accepted','rejection_reason')},'threshold original metadata')
        expected=dict(a['readout'],accepted=False,rejection_reason='below_threshold',below_threshold=True,reconstructed_energy_keV=None)
        compare(b['readout'],expected,'threshold readout')
    counts=dict(expected_counts,accepted=0,rejected=4,readout_rejected=4);C.equal(cr['detectors']['AK02']['counts'],counts,'threshold counts')
    compare([json.loads(x) for x in (ROOT/'.local/replays'/changed_name/'worker/AK02/traces.jsonl').read_text().splitlines()],
            [json.loads(x) for x in (same_root/'worker/AK02/traces.jsonl').read_text().splitlines()],'unchanged traces')
    C.equal(F.snapshot(ROOT/'.local/runs'/source),frozen,'source checksum/bytes/mtime')
    receipt=dict(status='passed',actual_existing_Julia=True,science_transport_calls=0,source_files=len(frozen),source_unchanged=True,
                 same=same_name,changed=changed_name,groups=[[r['event_id'],r['group_id'],r['readout']['input_sample_count'],r['transport_flags']['step_limits']] for r in new if r['record_kind']=='pulse'],
                 output_sha256={n:F.snapshot(ROOT/'.local/replays'/n) for n in (same_name,changed_name)},gates=gates)
    F.save(home/'acceptance.json',receipt)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--evidence',required=True);p.add_argument('--real',action='store_true');p.add_argument('--same-name',default='m4b-ak02-same-v1');p.add_argument('--changed-name',default='m4b-ak02-threshold-v1');a=p.parse_args()
    EVIDENCE=(ROOT/a.evidence).resolve()
    if not EVIDENCE.is_relative_to(ROOT/'.local/charge-replay-v1/implementation'):p.error('Use this round implementation evidence')
    EVIDENCE.mkdir(parents=True,exist_ok=False)
    F.save(EVIDENCE/'scope.json',dict(actual_numerical_acceptance=a.real,mocked_runtime_and_electronics=not a.real,python=sys.executable,python_version=sys.version,argv=sys.argv))
    if a.real:
        try:real_acceptance(EVIDENCE,a.same_name,a.changed_name)
        except BaseException as e:
            F.save(EVIDENCE/'FAILED.json',dict(status='failed_or_blocked',detail=str(e),actual_numerical_acceptance=False));raise
    else:unittest.main(argv=[__file__],verbosity=2)
