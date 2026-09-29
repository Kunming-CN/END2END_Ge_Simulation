"""Read-only launcher regression with isolated mocked source-only fixtures.
No Geant4, Julia, WSL, installation, field solve or response computation is invoked.
Fixture-only parent receipts are explicitly marked; originals are never rebased.
"""
import copy
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import argparse
import sys
from electronics_execution_fixture import clone
ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT
EVIDENCE = None
BASE = None
COMMAND_NUMBER = 0
PS = shutil.which('powershell.exe')
def read(path): return json.loads(path.read_text(encoding='utf-8-sig'))
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def save(path, value): path.write_text(json.dumps(value, indent=2), encoding='utf-8')
def quote(value): return "'" + str(value).replace("'", "''") + "'"
def command(code):
    global COMMAND_NUMBER
    COMMAND_NUMBER += 1
    script=EVIDENCE/f'command-{COMMAND_NUMBER:03}.ps1';script.write_text(code,encoding='utf-8')
    argv=[PS,'-NoProfile','-ExecutionPolicy','Bypass','-File',str(script)]
    env=dict(os.environ);env['PATH']=str(ROOT/'fixture-bin')+os.pathsep+env.get('PATH','')
    result=subprocess.run(argv,cwd=ROOT,env=env,capture_output=True,text=True,errors='replace',timeout=100)
    save(EVIDENCE/f'command-{COMMAND_NUMBER:03}.json',dict(command=argv,cwd=str(ROOT),exit_code=result.returncode,stdout=result.stdout,stderr=result.stderr))
    return result
def shared(code):
    return command('. '+quote(ROOT/'tools/native_run_validation.ps1')+'; '+code)
def snapshot(folder):
    return {str(p.relative_to(folder)):(sha(p),p.stat().st_size,p.stat().st_mtime_ns)
            for p in folder.rglob('*') if p.is_file()}
@unittest.skipUnless(PS, 'Windows PowerShell required')
class SavedRunTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global ROOT, BASE
        ROOT=EVIDENCE/'baseline';clone(PROJECT,ROOT,Path(sys.executable))
        out=command('& '+quote(ROOT/'Run.cmd')+' run -Name run -Preset smoke -Detector AK02; exit $LASTEXITCODE')
        if out.returncode:raise RuntimeError(out.stdout+out.stderr)
        BASE=ROOT/'.local/runs/run'
        cls.original = snapshot(BASE)
        got=shared("Get-NRCampaignSources '.local/m2a/cs137-build-v1/cryostat_export' 'scenarios/lbnl-cs137.json' | ConvertTo-Json")
        if got.returncode: raise RuntimeError(got.stderr)
        cls.sources=json.loads(got.stdout)
    @classmethod
    def tearDownClass(cls):
        if snapshot(BASE)!=cls.original: raise AssertionError('Original guarded fixture changed')
    def setUp(self):
        global ROOT
        ROOT=EVIDENCE/self.id().split('.')[-1]/'root'
        shutil.copytree(EVIDENCE/'baseline',ROOT)
        self.run=ROOT/'.local/runs/run'
        r=read(self.run/'run.json')
        r['source_sha256']={name:sha(ROOT/name) for name in self.sources}
        r['test_fixture_only']=True
        r['fixture_origin_receipt_sha256']=sha(BASE/'run.json')
        save(self.run/'run.json',r)
        self.response=self.run/'AK02/response';self.rf=self.response/'run.json'
    def inspect(self, *extra):
        return command('& '+quote(ROOT/'Run.cmd')+' inspect -Name '+quote(self.run.name)+' -Json '+ ' '.join(extra)+'; exit $LASTEXITCODE')
    def validate_response(self):
        return shared('$ErrorActionPreference="Stop"; $r=Test-NRResponse -Root '+quote(ROOT)+' -Directory '+quote(self.response)+' -Model AK02 -Events 20 -Manifest '+quote(self.run/'AK02/transport/stream/manifest.json')+' -ExpectedReportHash '+quote(sha(self.rf))+'; $r.counts | ConvertTo-Json')
    def mutate_response(self, change):
        r=read(self.rf);change(r);save(self.rf,r)
        parent=read(self.run/'run.json');parent['models']['AK02']['response_report_sha256']=sha(self.rf);save(self.run/'run.json',parent)
    def test_complete_inspection_json_preserves_every_file(self):
        before=snapshot(self.run);out=self.inspect()
        self.assertEqual(out.returncode,0,out.stdout+out.stderr)
        result=json.loads(out.stdout)
        self.assertEqual(result['status'],'terminal_verified')
        self.assertEqual(result['detectors'],['AK02'])
        self.assertTrue(result['saved_artifacts_verified'])
        self.assertFalse(result['runtime_readiness_checked'])
        self.assertEqual(result['files_written'],0)
        self.assertEqual(len(result['stages']),4)
        self.assertEqual(before,snapshot(self.run))
    def test_read_only_response_accepts_zero_case(self):
        got=self.validate_response();self.assertEqual(got.returncode,0,got.stderr)
        self.assertEqual(json.loads(got.stdout)['zero_deposit_primaries'],20)
    def test_rehashed_setting_mutations_rejected(self):
        original=read(self.rf)
        changes={'seed_family':2609262,'parcels':32,'diffusion':False,
                 'end_drift_when_no_field':True,'self_repulsion':True,
                 'drift_dt_ns':4,'nominal_drift_cap_ns':20000,'readout_contact_id':2,
                 'temperature_K':78,'stored_temperature_K':77,'bias_V':700,
                 'native_failure_policy':'abort','charge_csv_policy':'all',
                 'trace_selection':'all pulse groups','input_kind':'other',
                 'seed_rule':'unreviewed seed rule','native_failure_allowlist':['anything']}
        # seed_rule has an explicit guard added by the contract, not a JSON self-hash.
        for key,value in changes.items():
            with self.subTest(field=key):
                self.mutate_response(lambda r:r.update({key:value}))
                self.assertNotEqual(self.validate_response().returncode,0,key)
                save(self.rf,original)
    def test_rehashed_missing_inventories_and_bytes(self):
        original=read(self.rf)
        cases=[lambda r:r['artifacts'].pop('scalars.jsonl'),
               lambda r:r['source_sha256'].pop('test_native_stream.jl'),
               lambda r:r.update(artifacts={}),
               lambda r:r['artifact_bytes'].update({'traces.jsonl':123}),
               lambda r:r['field_settings'].update(min_spacing_mm=0.1),
               lambda r:r['boundary_guard'].update(installed='true'),
               lambda r:r['counts'].update(accepted=True),
               lambda r:r['counts'].update(native_failed_groups=None)]
        for i,change in enumerate(cases):
            with self.subTest(mutation=i):
                self.mutate_response(change)
                self.assertNotEqual(self.validate_response().returncode,0)
                save(self.rf,original)
    def test_rehashed_resolved_configuration_is_not_trusted(self):
        cfg=self.response/'readout-config.json';value=read(cfg);value['gain']=99;save(cfg,value)
        def rehash(r):
            r['config_sha256']=sha(cfg);r['artifacts']['readout-config.json']=sha(cfg)
            r['artifact_bytes']['readout-config.json']=cfg.stat().st_size
        self.mutate_response(rehash)
        out=self.validate_response();self.assertNotEqual(out.returncode,0)
        self.assertIn('resolved electronics',out.stderr)
    def test_missing_parent_binding_is_blocked(self):
        r=read(self.run/'run.json');r['models']['AK02'].pop('response_report_sha256');save(self.run/'run.json',r)
        before=snapshot(self.run);out=self.inspect();self.assertEqual(out.returncode,2)
        self.assertFalse(json.loads(out.stdout)['terminal_compatible'])
        self.assertEqual(before,snapshot(self.run))
    def test_source_mismatch_is_not_called_corruption(self):
        r=read(self.run/'run.json');r['source_sha256']['tools/run_native_campaign.ps1']='0'*64;save(self.run/'run.json',r)
        out=self.inspect();self.assertEqual(out.returncode,2)
        result=json.loads(out.stdout)
        self.assertTrue(result['saved_artifacts_verified'])
        self.assertIn('source_changed',[b['code'] for b in result['blockers']])
    def test_partial_response_keeps_original_attempt(self):
        self.rf.unlink();before=snapshot(self.run);out=self.inspect()
        self.assertEqual(out.returncode,2)
        row=json.loads(out.stdout)['stages'][-1];self.assertEqual(row['saved_state'],'partial')
        self.assertEqual(before,snapshot(self.run))
    def test_resume_dry_run_is_inspection_only(self):
        before=snapshot(self.run)
        out=command('& '+quote(ROOT/'Run.cmd')+' resume -Name '+quote(self.run.name)+' -DryRun; exit $LASTEXITCODE')
        self.assertEqual(out.returncode,0,out.stdout+out.stderr)
        self.assertIn('Inspection did not check runtime',out.stdout)
        self.assertEqual(before,snapshot(self.run))
    def test_existing_lock_is_never_created_or_overwritten(self):
        lock=self.run/'run.lock';lock.unlink();before=snapshot(self.run)
        out=self.inspect();self.assertEqual(out.returncode,2)
        self.assertEqual(json.loads(out.stdout)['lock_observation'],'missing')
        self.assertEqual(before,snapshot(self.run));self.assertFalse(lock.exists())
    def test_conflicting_inspect_options_rejected(self):
        before=snapshot(self.run);out=self.inspect('-Open')
        self.assertNotEqual(out.returncode,0);self.assertEqual(before,snapshot(self.run))
    def test_held_lock_blocks_inspection(self):
        api=ctypes.windll.kernel32
        api.CreateFileW.restype=ctypes.c_void_p
        api.CreateFileW.argtypes=[ctypes.c_wchar_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p]
        api.CloseHandle.argtypes=[ctypes.c_void_p]
        handle=api.CreateFileW(str(self.run/'run.lock'),0x80000000,0,None,3,0x80,None)
        self.assertNotEqual(handle,ctypes.c_void_p(-1).value)
        try:
            out=self.inspect();self.assertEqual(out.returncode,2)
            self.assertEqual(json.loads(out.stdout)['lock_observation'],'held_or_inaccessible')
        finally:api.CloseHandle(handle)
    def test_linked_response_directory_is_refused(self):
        source=self.run/'AK02/response';target=self.run/'saved-response';source.rename(target)
        out=subprocess.run(['cmd','/c','mklink','/J',str(source),str(target)],capture_output=True)
        if out.returncode:self.skipTest('Windows junction unavailable')
        try:
            got=self.inspect();self.assertEqual(got.returncode,2)
            self.assertIn('Linked',got.stdout)
        finally:os.rmdir(source)
    def test_actual_saved_positive_outputs_without_recompute(self):
        for model in ('AK02','SAP22'):
            response=PROJECT/f'.local/launcher-acceptance-v1/positive-v2/{model}'
            if not response.is_dir():self.skipTest('Saved-positive maintainer evidence absent')
            before=snapshot(response)
            manifest=PROJECT/f'.local/peak-native-delivery/cs500-v4/{model}/transport/stream/manifest.json'
            code='$r=Test-NRResponse -Root '+quote(PROJECT)+' -Directory '+quote(response)+' -Model '+model+' -Events 500 -Manifest '+quote(manifest)+' -NewChild; $r.counts | ConvertTo-Json'
            got=shared('$ErrorActionPreference="Stop"; '+code)
            self.assertEqual(got.returncode,0,got.stderr)
            self.assertEqual(json.loads(got.stdout)['accepted'],4)
            self.assertEqual(before,snapshot(response))
    def test_driver_rejects_resealed_child_before_any_receipt_write(self):
        self.mutate_response(lambda r:r.update(seed_family=2609262))
        before=snapshot(self.run)
        relative=self.run.relative_to(ROOT).as_posix()
        code='& '+quote(ROOT/'tools/run_native_campaign.ps1')+' -Output '+quote(relative)+' -Resume; exit $LASTEXITCODE'
        out=command('$ErrorActionPreference="Stop"; '+code)
        self.assertNotEqual(out.returncode,0)
        self.assertIn('seed_family',out.stderr)
        self.assertEqual(before,snapshot(self.run))
    def test_legacy_pilot_remains_explicit(self):
        pilot=PROJECT/'.local/peak-native-delivery/cs500-v4'
        if not pilot.is_dir():self.skipTest('Saved clean pilot absent')
        before=snapshot(pilot)
        got=command('& '+quote(PROJECT/'tools/verify_native_pilot.ps1')+" -Pilot .local/peak-native-delivery/cs500-v4 -Exporter .local/m2a/cs137-build-v1/cryostat_export")
        self.assertEqual(got.returncode,0,got.stderr)
        data=json.loads(got.stdout)
        self.assertTrue(all(m['contract']=='legacy_unguarded' for m in data['models'].values()))
        self.assertEqual(before,snapshot(pilot))

    def test_missing_bound_child_fails_before_driver_writes(self):
        self.rf.unlink();before=snapshot(self.run)
        relative=self.run.relative_to(ROOT).as_posix()
        got=command('$ErrorActionPreference="Stop"; & '+quote(ROOT/'tools/run_native_campaign.ps1')+' -Output '+quote(relative)+' -Resume')
        self.assertNotEqual(got.returncode,0);self.assertIn('terminal receipt is missing',got.stderr)
        self.assertEqual(before,snapshot(self.run))
    def test_parent_count_mismatch_prevents_driver_write(self):
        parent=read(self.run/'run.json');parent['models']['AK02']['counts']['groups']=1;save(self.run/'run.json',parent)
        before=snapshot(self.run);relative=self.run.relative_to(ROOT).as_posix()
        got=command('$ErrorActionPreference="Stop"; & '+quote(ROOT/'tools/run_native_campaign.ps1')+' -Output '+quote(relative)+' -Resume')
        self.assertNotEqual(got.returncode,0);self.assertIn('parent response counts',got.stderr)
        self.assertEqual(before,snapshot(self.run))
    def test_irrelevant_saved_setting_overrides_rejected(self):
        for args in ('-Seed 123','-Detector SAP22','-Preset demo'):
            self.assertNotEqual(self.inspect(args).returncode,0,args)
    def test_rehashed_stream_configuration_is_rejected(self):
        path=self.run/'AK02/transport/stream/manifest.json';m=read(path);m['config_sha256']='0'*64;save(path,m)
        out=self.inspect();self.assertEqual(out.returncode,2)
        self.assertIn('scenario.json',out.stdout)
    def test_profile_boolean_numeric_and_unknown_keys_rejected(self):
        profile=read(ROOT/'simulation/native_readout_profile.json')
        mutations=[lambda p:p.update(extra=True),lambda p:p['settings'].update(gain=True),lambda p:p['settings'].update(adc_bits=25),lambda p:p['settings'].update(peak_gate_start_ns=0)]
        path=self.run/'profile-test.json'
        for mutate in mutations:
            candidate=copy.deepcopy(profile);mutate(candidate);save(path,candidate)
            got=shared('$ErrorActionPreference="Stop"; Test-NRProfile (Get-Content -LiteralPath '+quote(path)+' -Raw | ConvertFrom-Json)')
            self.assertNotEqual(got.returncode,0)
    def test_child_source_mismatch_is_labelled_unchecked(self):
        self.mutate_response(lambda r:r['source_sha256'].update({'test_native_stream.jl':'0'*64}))
        out=self.inspect();self.assertEqual(out.returncode,2)
        result=json.loads(out.stdout)
        self.assertEqual(result['artifact_integrity'],'not_fully_checked')
        self.assertEqual(result['stages'][-1]['saved_state'],'source_incompatible')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--evidence',required=True);parser.add_argument('tests',nargs='*');options=parser.parse_args()
    EVIDENCE=(PROJECT/options.evidence).resolve()
    if not EVIDENCE.is_relative_to(PROJECT/'.local/electronics-execution-v1/implementation'):parser.error('Use implementation evidence directory')
    EVIDENCE.mkdir(parents=True,exist_ok=False)
    unittest.main(argv=[__file__,*options.tests],verbosity=2)
