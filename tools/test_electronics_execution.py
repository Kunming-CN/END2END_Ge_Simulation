"""Mocked public Run.cmd -> actual CLI/driver -> intercepted child contract tests.
Source-only clones: no historic Git objects, science files, Julia or transport.
Commands, exact cloned sources and all failures remain in --evidence.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from electronics_execution_fixture import clone, read, save, sha

ROOT=Path(__file__).resolve().parents[1]
EVIDENCE=None
PYTHON=Path(sys.executable)

def snapshot(root):
    return {str(p.relative_to(root)):(sha(p),p.stat().st_size,p.stat().st_mtime_ns)
            for p in root.rglob('*') if p.is_file()}

class Execution(unittest.TestCase):
    def setUp(self):
        self.home=EVIDENCE/self.id().split('.')[-1];self.root=self.home/'root'
        clone(ROOT,self.root,PYTHON);self.seq=0
    def cmd(self,*tokens,ok=True):
        self.seq+=1
        command=['cmd.exe','/d','/c','Run.cmd',*tokens]
        result=subprocess.run(command,cwd=self.root,capture_output=True,text=True,timeout=100)
        save(self.home/f'command-{self.seq:03}.json',dict(command=command,cwd=str(self.root),exit_code=result.returncode,stdout=result.stdout,stderr=result.stderr))
        if ok:self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        else:self.assertNotEqual(result.returncode,0,result.stdout+result.stderr)
        return result
    def saved(self,name='custom',gain=11,**edits):
        # JSON passed via a source input avoids cmd.exe quote interpretation.
        p=read(self.root/'simulation/native_readout_profile.json');p['settings'].update(gain=gain,**edits)
        save(self.root/f'inputs/{name}.json',p)
        self.cmd('settings','save','-SettingsFile',f'inputs/{name}.json','-SaveName',name,'-Json')
        return f'.local/electronics-profiles/{name}.json'
    def run_new(self,bundle=None,name='run',preset='smoke',detector='AK02',*extra):
        tokens=['run','-Name',name,'-Preset',preset,'-Detector',detector]
        if bundle:tokens+=['-ElectronicsProfile',bundle]
        self.cmd(*tokens,*extra)
        return self.root/f'.local/runs/{name}'
    def inspect(self,name='run',ok=True):return self.cmd('inspect','-Name',name,'-Json',ok=ok)
    def reseal(self,run,artifact=None):
        rp=run/'AK02/response/run.json';r=read(rp)
        if artifact:
            f=rp.parent/artifact;r['artifacts'][artifact]=sha(f);r['artifact_bytes'][artifact]=f.stat().st_size
            if artifact=='readout-config.json':r['config_sha256']=sha(f)
        save(rp,r);p=read(run/'run.json');p['models']['AK02']['response_report_sha256']=sha(rp);save(run/'run.json',p)
    def assert_no_start(self):
        self.assertFalse((self.root/'runtime-probes.log').exists())
        self.assertFalse((self.root/'.local/runs').exists())
        self.assertFalse(list(self.root.glob('child-call-*')))
    def test_two_profiles_reach_actual_invoked_child_and_copies(self):
        for name,gain in [('one',11),('two',13)]:
            bundle=self.saved(name,gain);run=self.run_new(bundle,name)
            p=read(run/'run.json');child=read(run/'AK02/response/run.json')
            stage=[s for s in p['stages'] if s['stage']=='AK02-native-response'][0]
            args=stage['arguments']; selected=args[args.index('--profile')+1]
            self.assertEqual(selected,f'.local/runs/{name}/electronics/profile.json')
            calls=[read(f) for f in self.root.glob('child-call-*.json')]
            self.assertIn(args,calls)
            self.assertEqual(child['profile']['settings']['gain'],gain)
            cfg=read(run/'AK02/response/readout-config.json');expected=copy.deepcopy(p['electronics']['configuration']);expected['expected_primary_count']=20
            self.assertEqual(cfg,expected)
            self.assertEqual(child['profile_sha256'],sha(self.root/selected))
            self.assertEqual(p['electronics']['input']['sha256'],sha(self.root/bundle))
            self.assertEqual(json.loads(self.inspect(name).stdout)['electronics']['selection'],'saved_custom')
    def test_default_regression_keeps_implicit_canonical_child(self):
        run=self.run_new();p=read(run/'run.json');r=read(run/'AK02/response/run.json')
        self.assertNotIn('electronics',p)
        self.assertNotIn('--profile',p['stages'][-1]['arguments'])
        self.assertEqual(r['profile_sha256'],sha(self.root/'simulation/native_readout_profile.json'))
        self.assertEqual(r['counts']['zero_deposit_primaries'],20)
        self.assertEqual(json.loads(self.inspect().stdout)['electronics']['selection'],'canonical')
    def test_malformed_missing_and_raw_profile_fail_before_runtime(self):
        for bundle in ['missing.json','.local/electronics-profiles/missing.json','simulation/native_readout_profile.json']:
            self.cmd('run','-ElectronicsProfile',bundle,'-Name','bad','-DryRun',ok=False)
            self.assert_no_start()
        bundle=self.saved();data=read(self.root/bundle);data['profile']['settings']['gain']=0;save(self.root/bundle,data)
        self.cmd('run','-ElectronicsProfile',bundle,'-Name','bad',ok=False);self.assert_no_start()
    def test_finite_sample_checks_before_runtime_and_dryrun_no_allocation(self):
        for name,edits in [('emptygate',dict(peak_gate_start_ns=0.1,peak_gate_end_ns=1.9)),
                           ('onepoint',dict(peak_gate_start_ns=1,peak_gate_end_ns=3)),
                           ('huge',dict(shaping_tau_us=50)),('tiny',dict(shaping_tau_us=0.00001))]:
            b=self.saved(name,**edits)
            self.cmd('run','-Name','bad','-ElectronicsProfile',b,'-DryRun',ok=False);self.assert_no_start()
        b=self.saved('valid',peak_gate_start_ns=99996,peak_gate_end_ns=99998)
        before=snapshot(self.root/'.local');self.cmd('run','-Name','dry','-ElectronicsProfile',b,'-DryRun')
        self.assertEqual(before,snapshot(self.root/'.local'));self.assertFalse(list(self.root.glob('child-call-*')))
    def test_source_and_bundle_lineage_mutation_before_runtime(self):
        b=self.saved();source=self.root/'inputs/custom.json';original=source.read_bytes()
        data=read(source);data['settings']['gain']=12;save(source,data)
        self.cmd('run','-ElectronicsProfile',b,ok=False);self.assert_no_start();source.write_bytes(original)
        p=self.root/'simulation/readout_profiles.jl';p.write_bytes(p.read_bytes()+b'\n# mutation\n')
        self.cmd('run','-ElectronicsProfile',b,ok=False);self.assert_no_start()
    def test_rehashed_child_config_mismatch_independently_rejected(self):
        run=self.run_new(self.saved());p=run/'AK02/response/readout-config.json';data=read(p);data['gain']=99;save(p,data);self.reseal(run,'readout-config.json')
        before=snapshot(self.root);result=self.inspect(ok=False)
        self.assertIn('resolved electronics settings',result.stdout);self.assertEqual(before,snapshot(self.root))
    def test_missing_and_corrupt_child_copies(self):
        run=self.run_new(self.saved())
        for name in ['profile-input.json','profile.json','readout-config.json']:
            path=run/'AK02/response'/name;original=path.read_bytes();path.unlink()
            before=snapshot(self.root);self.inspect(ok=False);self.assertEqual(before,snapshot(self.root))
            path.write_bytes(b'{}');self.reseal(run,name);self.inspect(ok=False)
            path.write_bytes(original);self.reseal(run,name)
        self.inspect()
    def test_parent_removal_tamper_and_missing_snapshot(self):
        run=self.run_new(self.saved());path=run/'run.json';original=path.read_bytes()
        data=read(path);del data['electronics'];save(path,data);self.inspect(ok=False);path.write_bytes(original)
        data=read(path);data['electronics']['configuration']['gain']=99;save(path,data)
        self.assertIn('Parent independent effective configuration',self.inspect(ok=False).stdout);path.write_bytes(original)
        data=read(path);data['electronics']['profile_path']='simulation/native_readout_profile.json';save(path,data);self.inspect(ok=False);path.write_bytes(original)
        (run/'electronics/inputs/inputs/custom.json').unlink();self.inspect(ok=False)
    def test_rehashed_snapshot_cannot_override_saved_bundle(self):
        run=self.run_new(self.saved());path=run/'electronics/profile.json';data=read(path);data['settings']['gain']=99;save(path,data)
        p=read(run/'run.json');p['electronics']['profile_sha256']=sha(path);save(run/'run.json',p)
        self.assertIn('Standalone profile versus saved bundle',self.inspect(ok=False).stdout)
    def test_resume_uses_self_contained_copies_and_inspection_writes_nothing(self):
        b=self.saved();run=self.run_new(b)
        (self.root/b).unlink();(self.root/'inputs/custom.json').unlink()
        before=snapshot(self.root);self.inspect();self.cmd('resume','-Name','run','-DryRun')
        self.assertEqual(before,snapshot(self.root))
        native_calls=len([s for s in read(run/'run.json')['stages'] if s['stage']=='AK02-native-response'])
        self.cmd('resume','-Name','run')
        p=read(run/'run.json');self.assertEqual(p['electronics']['configuration']['gain'],11)
        stages=[s for s in p['stages'] if s['stage']=='AK02-native-response']
        self.assertEqual(len(stages),native_calls+1);self.assertEqual(stages[-1]['status'],'reused_verified')
    def test_resume_overrides_and_unknown_cli_options_refused(self):
        run=self.run_new(self.saved());before=snapshot(self.root)
        for flag,value in [('-ElectronicsProfile','missing.json'),('-Preset','smoke'),('-Seed','2'),('-Detector','SAP22'),('-Pilot','bad'),('-Scenario','lbnl-cs137'),('-Typo','bad')]:
            self.cmd('resume','-Name','run',flag,value,ok=False)
        self.assertEqual(before,snapshot(self.root))
    def test_resume_before_intent_uses_recorded_profile_argument(self):
        b=self.saved();run=self.run_new(b)
        # Preserve the old MOCK child; model a stopped attempt with no child yet.
        (run/'AK02/response').rename(run/'AK02/preserved-mock-response')
        (run/'AK02/native-launch-intent.json').rename(run/'AK02/preserved-mock-intent.json')
        p=read(run/'run.json');p['models']={};p['child_launches']={};p['status']='failed';save(run/'run.json',p)
        (self.root/b).unlink();(self.root/'inputs/custom.json').unlink()
        self.saved('unrelated',17)
        self.cmd('resume','-Name','run')
        p=read(run/'run.json');args=p['stages'][-1]['arguments']
        self.assertEqual(args[args.index('--profile')+1],'.local/runs/run/electronics/profile.json')
        child=read(run/'AK02/response/run.json');self.assertEqual(child['profile']['settings']['gain'],11)
        self.inspect()
    def test_custom_pilot_matches_effective_settings_not_names(self):
        b=self.saved('pilot',11);self.run_new(b,'pilot','demo','both')
        renamed=self.saved('renamed',11)
        self.run_new(renamed,'large','larger','both','-Pilot','.local/runs/pilot')
        self.assertEqual(read(self.root/'.local/runs/large/run.json')['events_per_model'],10000)
        self.inspect('large')
        # Binary identity, not the exporter's local directory name, governs match.
        (self.root/'.local/alternate-exporter').write_bytes((self.root/'.local/m2a/cs137-build-v1/cryostat_export').read_bytes())
        script=self.home/'alternate-exporter.ps1'
        script.write_text("$ErrorActionPreference='Stop'\nSet-Location '"+str(self.root).replace("'","''")+"'\n"+
                          "$c=(Get-Content .local/runs/pilot/run.json -Raw|ConvertFrom-Json).electronics.configuration\n"+
                          "& ./tools/verify_native_pilot.ps1 -Pilot .local/runs/pilot -Exporter .local/alternate-exporter -ExpectedConfiguration $c\n",encoding='utf-8')
        command=['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(script)]
        before=snapshot(self.root);r=subprocess.run(command,cwd=self.root,capture_output=True,text=True,timeout=60)
        save(self.home/'alternate-exporter.json',dict(command=command,exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr))
        self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(before,snapshot(self.root))
    def test_saved_custom_source_change_reports_incompatible_without_writes(self):
        self.run_new(self.saved());p=self.root/'simulation/readout_profiles.jl';p.write_bytes(p.read_bytes()+b'\n# changed\n')
        before=snapshot(self.root);result=json.loads(self.inspect(ok=False).stdout)
        self.assertEqual(result['source_compatibility'],'incompatible');self.assertEqual(before,snapshot(self.root))
    def test_canonical_and_custom_mismatched_pilots_fail_before_allocation(self):
        self.run_new(None,'canonical','demo','AK02');custom=self.saved()
        self.run_new(custom,'custom','demo','AK02');changed=self.saved('changed',12)
        for pilot,bundle in [('canonical',custom),('custom',changed)]:
            before=snapshot(self.root)
            result=self.cmd('run','-Name','bad','-Preset','larger','-Detector','AK02','-Pilot',f'.local/runs/{pilot}','-ElectronicsProfile',bundle,ok=False)
            self.assertIn('Pilot effective electronics',result.stderr)
            self.assertEqual(before,snapshot(self.root))
    def test_pilot_own_binding_checked_before_matching_and_compute_mismatch(self):
        b=self.saved();run=self.run_new(b,'pilot','demo')
        path=run/'AK02/response/readout-config.json';data=read(path);data['gain']=12;save(path,data);self.reseal(run,'readout-config.json')
        before=snapshot(self.root)
        result=self.cmd('run','-Name','bad','-Preset','larger','-Detector','AK02','-Pilot','.local/runs/pilot','-ElectronicsProfile',b,ok=False)
        self.assertIn('resolved electronics',result.stderr);self.assertEqual(before,snapshot(self.root))
        data['gain']=11;save(path,data);self.reseal(run,'readout-config.json')
        source=self.root/'transport/cs137.py';source.write_bytes(source.read_bytes()+b'\n# changed\n')
        before=snapshot(self.root)
        self.cmd('run','-Name','bad','-Preset','larger','-Detector','AK02','-Pilot','.local/runs/pilot','-ElectronicsProfile',b,ok=False)
        self.assertEqual(before,snapshot(self.root))
    def test_legacy_unguarded_pilot_cannot_authorize_new_guarded_execution(self):
        run=self.run_new(None,'pilot','demo')
        rp=run/'AK02/response/run.json';r=read(rp);r.pop('boundary_guard')
        for name in ['native_response_guarded.jl','native_boundary_guard.jl']:r['source_sha256'].pop(name)
        save(rp,r);self.reseal(run)
        before=snapshot(self.root)
        result=self.cmd('run','-Name','bad','-Preset','larger','-Detector','AK02','-Pilot','.local/runs/pilot',ok=False)
        self.assertIn('requires a guarded pilot',result.stderr);self.assertEqual(before,snapshot(self.root))

    def test_custom_pilot_control_hash_and_missing_binding_rejected(self):
        bundle=self.saved();run=self.run_new(bundle,'pilot','demo')
        path=run/'run.json';original=path.read_bytes()
        for key in ['tools/electronics_execution.ps1','tools/electronics_settings.ps1','tools/scenario_cli.ps1','tools/run_native_campaign.ps1','tools/verify_native_pilot.ps1']:
            for remove in (False,True):
                parent=json.loads(original)
                if remove:parent['source_sha256'].pop(key)
                else:parent['source_sha256'][key]='0'*64
                save(path,parent);before=snapshot(self.root)
                result=self.cmd('run','-Name','blocked','-Preset','larger','-Detector','AK02','-Pilot','.local/runs/pilot','-ElectronicsProfile',bundle,ok=False)
                self.assertEqual(snapshot(self.root),before)
                self.assertFalse((self.root/'.local/runs/blocked').exists())
        path.write_bytes(original)
        self.inspect('pilot')

    def test_final_binding_recheck_failure_clears_success_flags(self):
        self.run_new(self.saved())
        path=self.root/'tools/inspect_native_run.ps1';source=path.read_text(encoding='utf-8-sig')
        anchor='try{[void](Get-EERecordedProfile $root $dir $r)}'
        self.assertEqual(source.count(anchor),1)
        injected=source.replace(anchor,"try{throw 'File binding mismatch: injected final profile-copy check'}")
        path.write_text(injected,encoding='utf-8')
        save(self.home/'fault-injection.json',{'test_only':True,'target':'final custom-binding recheck','science_execution':False})
        before=snapshot(self.root);result=json.loads(self.inspect(ok=False).stdout)
        self.assertEqual(snapshot(self.root),before)
        self.assertFalse(result['terminal_compatible'])
        self.assertFalse(result['saved_artifacts_verified'])
        self.assertFalse(result['electronics']['binding_verified'])
        self.assertFalse(result['snapshot_stable'])
        self.assertEqual(result['artifact_integrity'],'not_fully_checked')
        self.assertIn('changed_during_inspection',[b['code'] for b in result['blockers']])

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--evidence',required=True);parser.add_argument('tests',nargs='*');opts=parser.parse_args()
    EVIDENCE=(ROOT/opts.evidence).resolve()
    if not any(EVIDENCE.is_relative_to(ROOT/p) for p in ('.local/electronics-execution-v1/implementation','.local/recovery-plan-v1/implementation')):parser.error('Use implementation evidence directory')
    EVIDENCE.mkdir(parents=True,exist_ok=False)
    save(EVIDENCE/'scope.json',dict(mocked_child_execution=True,uninstrumented_full_chain=False,python=sys.executable,argv=sys.argv))
    unittest.main(argv=[__file__,*opts.tests],verbosity=2)
