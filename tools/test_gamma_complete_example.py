import copy
import inspect
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import gamma_complete_example as F
import gamma_showcase as S

class CompleteTests(unittest.TestCase):
    def test_native_failure_recording_requires_explicit_opt_in(self):
        self.assertEqual(inspect.signature(F.run).parameters['policy'].default,'abort')

    def test_camera_does_not_change_tail(self):
        t=[float(i*2) for i in range(5002)];q=[0.,100.]+[100.+i*1e-9 for i in range(5000)]
        before=copy.deepcopy((t,q));self.assertLess(F.focus_end(t,q),100)
        self.assertEqual((t,q),before);self.assertEqual(t[-1],10002.)

    def test_only_census_profile_change(self):
        reader,plans=F.load_inputs()
        for plan in plans:
            expected=dict(S.CONFIG,expected_primary_count=20);S.exact(plan['readout_config'],expected)
            for key in ('trace_max_points','gain','feedback_capacitance_pF','threshold_V'):
                mutant=copy.deepcopy(plan['readout_config']);mutant[key]+=1
                with self.assertRaises(ValueError):S.exact(mutant,expected)
        reader.recheck()

class RecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.before=json.loads((F.ROOT/F.RECOVERY/'BEFORE.json').read_text(encoding='utf-8'))
        cls.reader,cls.plans=F.load_inputs()
        cls.plan=copy.deepcopy(next(p for p in cls.plans if p['model_id']=='AK02'))
        cls.plan['native_failure_policy']='record'

    def fixture(self):
        directory=tempfile.TemporaryDirectory(prefix='bounded-recovery-test-',dir=F.ROOT/'.local')
        self.addCleanup(directory.cleanup);return Path(directory.name)

    def test_report_cap_is_role_scoped_and_retains_strict_json(self):
        root=self.fixture();folder=root/'AK02';folder.mkdir()
        report=folder/'report.json'
        report.write_bytes(b'{"value":-0.0,"padding":"'+b'x'*F.C.MAX_JSON+b'"}')
        self.assertGreater(report.stat().st_size,F.C.MAX_JSON)
        self.assertEqual(F.CompletionReader(root).report('AK02/report.json')['value'].hex(),(-0.0).hex())
        with self.assertRaises(F.C.Rejected):F.CompletionReader(root).json('AK02/report.json')
        with self.assertRaises(F.C.Rejected):F.CompletionReader(root).report('AK02/request.json')
        report.write_bytes(b' '*(F.MAX_COMPLETE_REPORT+1))
        with self.assertRaisesRegex(F.C.Rejected,'16MiB'):F.CompletionReader(root).report('AK02/report.json')
        for raw in (b'{"value":1,"value":2}',b'{"value":NaN}',b'{"value":1e999}'):
            report.write_bytes(raw)
            with self.subTest(raw=raw),self.assertRaises(F.C.Rejected):F.CompletionReader(root).report('AK02/report.json')

    def test_actual_terminal_ak_is_read_only_and_preserves_exact_inventory(self):
        directory=F.ROOT/F.BASE/'example';before=F.all_inventory(directory)
        with patch.object(F.G,'child',side_effect=AssertionError('Read-only verification dispatched science')):
            report=F.verify_stage(directory/'AK02',self.plan,2,self.before['original_source_pins'],self.before['stages'][0])
        self.assertEqual(report['status'],'completed');self.assertEqual(len(report['cases']),20)
        self.assertEqual(report['counts']['native_calls'],4);self.assertEqual(report['counts']['unprocessed_primaries'],0)
        self.assertEqual(F.all_inventory(directory),before)

    def test_scientific_pin_change_cannot_be_rehashed_into_maintenance(self):
        old=self.before['original_source_pins'];current=dict(old)
        for name in F.MAINTENANCE_SOURCES:current[name]=hashlib.sha256(('updated '+name).encode()).hexdigest()
        freeze={'status':'frozen_after_writer_exit','files':{name:{'sha256':digest} for name,digest in current.items()}}
        self.assertEqual(set(F.maintenance_delta(self.before,current,freeze)),set(F.MAINTENANCE_SOURCES))
        for name in ('simulation/readout.jl','models/AK02.yaml','.local/cs137-1m-native/cache/AK02.jls',
                     'simulation/native_readout_profile.json','simulation/Manifest.toml',F.WORKER):
            mutant=dict(current);mutant[name]='a'*64
            rehashed=copy.deepcopy(freeze);rehashed['files'][name]['sha256']='a'*64
            with self.subTest(name=name),self.assertRaisesRegex(F.C.Rejected,'two approved Python'):
                F.maintenance_delta(self.before,mutant,rehashed)
        bad=copy.deepcopy(freeze);bad['files'][F.MAINTENANCE_SOURCES[0]]['sha256']='b'*64
        with self.assertRaisesRegex(F.C.Rejected,'Current frozen'):F.maintenance_delta(self.before,current,bad)

    def test_rehashed_recovery_record_cannot_replace_captured_authority(self):
        root=self.fixture();folder=root/F.RECOVERY;folder.mkdir(parents=True)
        mutant=copy.deepcopy(self.before);mutant['original_error']='some other failure'
        (folder/'BEFORE.json').write_text(json.dumps(mutant),encoding='utf-8')
        with self.assertRaisesRegex(F.C.Rejected,'hash mismatch'):F.recovery_authority(root,{})

    def test_partial_or_extra_output_is_never_adopted(self):
        root=self.fixture();dest=root/F.BASE/'example';dest.mkdir(parents=True)
        (dest/'run.json').write_text(json.dumps({'status':'failed'}),encoding='utf-8')
        for policy,threads in (('abort',2),('record',1),('record',2)):
            with patch.object(F,'recovery_authority',return_value=(self.before,{})), \
                 patch.object(F.G,'child',side_effect=AssertionError('Invalid adoption dispatched science')):
                with self.subTest(policy=policy,threads=threads),self.assertRaises(F.C.Rejected):
                    F.admit_resume(self.reader,copy.deepcopy(self.plans),threads,policy,root)

    def test_rehashed_report_still_requires_original_truth_and_complete_ids(self):
        report=F.CompletionReader(F.ROOT/F.BASE/'example/AK02').report('report.json')
        for mode in ('truth','identity','calibration','source_row','native_counts'):
            mutant=copy.deepcopy(report)
            if mode=='truth':mutant['cases'][8]['truth_ge_edep_keV']+=1.
            elif mode=='identity':mutant['cases'][19]['initial_primary_id']=18
            elif mode=='calibration':mutant['calibration']['volts_per_keV']*=2
            elif mode=='source_row':mutant['cases'][8]['raw_row_indices'].pop()
            else:mutant['native_calls']=3
            raw=json.dumps(mutant,allow_nan=False).encode();self.assertNotEqual(hashlib.sha256(raw).hexdigest(),self.before['artifact_inventory']['AK02/report.json']['sha256'])
            with self.subTest(mode=mode),self.assertRaises(F.C.Rejected):F.verify_report(json.loads(raw),self.plan,2)

if __name__=='__main__':unittest.main()
