"""Saved gamma adapter fixtures/mocked workers only; never executes physics."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import gamma_native_example as A

TEST_ROOT = os.environ.get('GAMMA_TEST_ROOT', A.BASE+'/tests/writer-v1')


def seed_schedule(e):
    return [dict(raw_row_index=s['raw_row_index'], parcels=[dict(parcel_index=i,
        seed_uint64_decimal=str(int.from_bytes(hashlib.sha256(f"2609261/{e['event_id']}/{s['raw_row_index']}/{i}".encode()).digest()[:8], 'big')))
        for i in range(1,17)]) for s in e['steps'] if s['energy_keV']>0]


def mocked_report(request, request_path, failed_id=None):
    """Deliberately synthetic signed outputs; never native or electronics code."""
    cases=[];cal=request['expected_calibration'];failed=0
    for id in request['selected_ids']:
        e=request['events'][id]
        case=dict(initial_primary_id=id,event_id=id,primary_time_ns=0.0,clock_policy='synthetic_primary_time_zero',
            truth_ge_edep_keV=e['truth_ge_edep_keV'],zero_ge=e['zero_ge'],raw_row_indices=[s['raw_row_index'] for s in e['steps']],
            deposition_delays_ns=[s['time_ns'] for s in e['steps']],parcel_seeds=seed_schedule(e),native=None,transport_flags=None,
            readout=None,error=None,native_seconds=0.0,electronics_seconds=0.0,field_solve_seconds=0.0)
        if id==failed_id:
            failed+=1;case.update(status='native_failed',charge_input=None,charge_end_ns=None,final_induced_keV=None,
                error=dict(type='ArgumentError',message=A.FAILURES[0],exact_error='ArgumentError: '+A.FAILURES[0],stage='NativeLiExample.native_event'))
        else:
            t=[0.0,2.0] if e['zero_ge'] else [0.0,2.0,4.0]
            q=[0.0,0.0] if e['zero_ge'] else [0.0,-0.01,e['truth_ge_edep_keV']*.5]
            case.update(status='native_not_applicable_true_zero' if e['zero_ge'] else 'native_completed',
                charge_input=dict(time_since_initial_primary_ns=t,induced_equivalent_energy_keV=q),charge_end_ns=t[-1],final_induced_keV=q[-1])
            if not e['zero_ge']:
                steps=[dict(raw_row_index=s['raw_row_index'],deposited_energy_keV=s['energy_keV'],
                    deposition_delay_ns=s['time_ns'],parcel_weight_keV=s['energy_keV']/16,
                    endpoints=[dict(parcel_index=i,contact_ids=[1],step_limit_reached=False,status='contact') for i in range(1,17)])
                    for s in e['steps'] if s['energy_keV']>0]
                case['native']=dict(times=t,signal=q,steps=steps)
                case['transport_flags']=dict(carrier_parcels=16*len(steps),geometric_contacts=16*len(steps),step_limits=0,stopped_without_contact=0)
            code=0 if e['zero_ge'] else 1
            case['readout']=dict(accepted=not e['zero_ge'],current_balance=dict(passed=True),negative_input=any(v<0 for v in q),
                input_sample_count=len(t),peak_V=0.0 if e['zero_ge'] else .001,
                analog_energy_keV=0.0 if e['zero_ge'] else .001/cal['volts_per_keV'],adc_code=code,
                reconstructed_energy_keV=None if e['zero_ge'] else (code+.5)*cal['adc_lsb_V']/cal['volts_per_keV'])
        cases.append(case)
    return dict(kind=A.KIND,schema_version=1,status='completed_with_native_failures' if failed else 'completed',
        model_id=request['model_id'],selected_ids=request['selected_ids'],settings=A.SETTINGS,native_failure_policy=request['native_failure_policy'],
        request_sha256=hashlib.sha256(request_path.read_bytes()).hexdigest(),readout_config=request['readout_config'],
        calibration=cal,calibration_calls=1,native_calls=2,field_solve_seconds=0.0,ionisation_energy_eV=2.95,
        field_fingerprint_before=request['expected_field_fingerprint'],field_fingerprint_after=request['expected_field_fingerprint'],
        runtime=dict(threads=request['threads'],blas_threads=1,executable_sha256=A.JULIA_SHA,ssd_loaded=True,
            environment=dict(julia_version='1.13.0',ssd_version='0.11.8'),readout_environment=dict(json_version='1.9.0'),
            native_drift_sha256='0358c255e37c38f62eee6f1e476c0ed48560708dfcd3d367d2688eaa022232ad'),
        guard=dict(installed=True,package_files_modified=False,native_source_sha256='0358c255e37c38f62eee6f1e476c0ed48560708dfcd3d367d2688eaa022232ad'),
        counts=dict(radiation_primaries=20,selected_primaries=3,unprocessed_primaries=17,selected_true_zeros=1,native_calls=2,
            native_failed=failed,native_completed=2-failed,readout_completed=3-failed,readout_accepted=2-failed,electronics_rejected=1),cases=cases)


class GammaFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reader,cls.plans=A.load_inputs()
        cls.exe=A.julia_executable() # file/hash inspection only, no process
        cls.root=A.ROOT/TEST_ROOT
        cls.root.mkdir(parents=True,exist_ok=False)
        A.save(cls.root/'TEST-SCOPE.json',dict(scope='synthetic fixture/mocked native/calibration/readout only',
            actual_native_calls=0,actual_calibration_calls=0,actual_readout_calls=0,cache_deserializations=0,field_solves=0,radiation_calls=0))

    def plan(self,model='AK02'):
        return copy.deepcopy(next(p for p in self.plans if p['model_id']==model))

    def bad_event(self,mutate):
        p=self.plan();mutate(p)
        with self.assertRaises(A.C.Rejected): A.validate_events(p['events'],p['source_manifest'],p['prepared'])

    def mock_run(self,policy='abort',failed=False,mutate_source=False):
        relative=TEST_ROOT+'/'+self._testMethodName
        calls=[]
        def runner(args,cwd,threads):
            request_path=Path(args[args.index('--request')+1]);request=json.loads(request_path.read_text());out=request_path.parent
            calls.append(request['model_id']);report=mocked_report(request,request_path,request['selected_ids'][1] if failed else None)
            A.save(out/'report.json',report)
            for case in report['cases']: A.save(out/('event-'+str(case['initial_primary_id'])+'.json'),case)
            if mutate_source:
                raise A.C.Rejected('changed_during_read','mock source mutation abort before trusted completion')
            return dict(arguments=args,exit_code=0,wall_seconds=0.0,output='MOCKED WORKER; native/calibration/readout calls=0\n')
        with patch.object(A,'BASE',TEST_ROOT):
            result=A.run_example(relative,policy=policy,runner=runner,executable=lambda:self.exe)
            checked=A.verify_example(result['output'])
        self.assertEqual(calls,['AK02','SAP22']);self.assertEqual(checked['radiation_primaries'],40)
        return Path(result['output'])

    def test_whole_truth_census_and_preselection(self):
        for p in self.plans:
            rows=A.truth_ledger(p,[])
            self.assertEqual(len(rows),20);self.assertEqual(sum(r['selected'] for r in rows),3)
            self.assertEqual(sum(not r['selected'] for r in rows),17)
            for row,e in zip(rows,p['events']): A.exact(row['source_truth'],e,'full raw truth')

    def test_raw_ancestry_changed(self):
        self.bad_event(lambda p:p['events'][4]['material_rows']['stp/germanium'][0].update(parent_trackid=999))

    def test_clock_changed(self): self.bad_event(lambda p:p['events'][0]['vtx'][0].update(time=1.0))
    def test_initial_id_changed(self): self.bad_event(lambda p:p['events'][1].update(initial_primary_id=0))
    def test_units_changed(self): self.bad_event(lambda p:p['source_manifest'].update(raw_track_energy_unit='keV'))
    def test_transform_changed(self): self.bad_event(lambda p:p['source_manifest']['coordinate_transform'].update(translation_global_mm=[0,0,0]))
    def test_zero_row_dropped(self): self.bad_event(lambda p:p['events'][0]['steps'].clear())
    def test_material_table_dropped(self): self.bad_event(lambda p:p['events'][0]['material_rows'].pop('stp/ledger_1'))
    def test_raw_alias_changed(self): self.bad_event(lambda p:p['events'][4]['steps'][0].update(energy_keV=1.0))
    def test_binary64_preservation(self):
        with self.assertRaises(A.C.Rejected): A.exact(-0.0,0.0,'truth signed zero')

    def test_descriptor_object_and_strict_json(self):
        descriptor=A.decode('{"columns":{"evtid":{"dtype":"int32","units":""}}}')
        self.assertIsInstance(descriptor['columns']['evtid'],dict)
        for text in ('{"x":1,"x":2}','{"x":NaN}','{"x":Infinity}','{"x":1e9999}'):
            with self.assertRaises(A.C.Rejected): A.decode(text)

    def test_true_id_boolean_rejected(self): self.bad_event(lambda p:p['events'][0].update(event_id=False))
    def test_true_id_float_rejected(self): self.bad_event(lambda p:p['events'][0].update(initial_primary_id=0.0))
    def test_zero_label_integer_rejected(self): self.bad_event(lambda p:p['events'][0].update(zero_ge=1))

    def test_mocked_serial_full_run(self): self.mock_run()
    def test_mocked_record_failure_nulls(self): self.mock_run(policy='record',failed=True)

    def test_rehashed_gain_cannot_pass(self):
        output=self.mock_run();p=output/'AK02'/'report.json';report=json.loads(p.read_text());report['readout_config']['gain']*=2
        A.save(p,report,replace=True)
        complete=json.loads((output/'COMPLETE.json').read_text());complete['artifacts']=A.inventory(output);A.save(output/'COMPLETE.json',complete,replace=True)
        with patch.object(A,'BASE',TEST_ROOT),self.assertRaises(A.C.Rejected): A.verify_example(output)

    def test_rehashed_truth_drop_cannot_pass(self):
        output=self.mock_run();path=output/'AK02'/'truth-ledger.jsonl';lines=path.read_text().splitlines();path.write_text('\n'.join(lines[1:])+'\n')
        complete=json.loads((output/'COMPLETE.json').read_text());complete['artifacts']=A.inventory(output);A.save(output/'COMPLETE.json',complete,replace=True)
        with patch.object(A,'BASE',TEST_ROOT),self.assertRaises(A.C.Rejected): A.verify_example(output)

    def test_rehashed_config_boolean_cannot_pass(self):
        p=self.plan();request=dict(p,native_failure_policy='abort',threads=2);path=self.root/(self._testMethodName+'.json');A.save(path,request)
        report=mocked_report(request,path)
        for key,value in (('require_all_events',1),('expected_primary_count',3.0)):
            changed=copy.deepcopy(report);changed['readout_config'][key]=value
            with self.assertRaises(A.C.Rejected): A.verify_report(changed,p,2)

    def test_failed_charge_never_zero(self):
        p=self.plan();request=dict(p,native_failure_policy='record',threads=2);path=self.root/(self._testMethodName+'.json');A.save(path,request)
        report=mocked_report(request,path,failed_id=4);report['cases'][1]['final_induced_keV']=0.0
        with self.assertRaises(A.C.Rejected): A.verify_report(report,p,2)

    def test_no_clobber(self):
        output=self.mock_run();before=hashlib.sha256((output/'COMPLETE.json').read_bytes()).hexdigest()
        with patch.object(A,'BASE',TEST_ROOT),self.assertRaises(A.C.Rejected):
            A.run_example(output.relative_to(A.ROOT).as_posix(),runner=lambda *x:self.fail('child launched'),executable=lambda:self.exe)
        self.assertEqual(before,hashlib.sha256((output/'COMPLETE.json').read_bytes()).hexdigest())

    def test_unexpected_child_exception_has_no_complete(self):
        relative=TEST_ROOT+'/'+self._testMethodName
        with patch.object(A,'BASE',TEST_ROOT),self.assertRaises(A.C.Rejected):
            A.run_example(relative,runner=lambda *x:(_ for _ in ()).throw(A.C.Rejected('mock_unexpected','unexpected mock child failure')),executable=lambda:self.exe)
        self.assertFalse((A.ROOT/relative/'COMPLETE.json').exists())
        self.assertEqual(json.loads((A.ROOT/relative/'run.json').read_text())['status'],'failed')

    def test_actual_changed_pin_aborts(self):
        path=self.root/'pin.txt';path.write_text('frozen');reader=A.C.Reader(self.root);reader.digest('pin.txt');path.write_text('changed')
        with self.assertRaises(A.C.Rejected): reader.recheck()

    def test_source_change_during_mock_dispatch(self):
        path=self.root/(self._testMethodName+'.txt');path.write_text('frozen fixture input')
        reader,plans=A.load_inputs();reader.digest(path.relative_to(A.ROOT).as_posix())
        relative=TEST_ROOT+'/'+self._testMethodName
        def runner(args,cwd,threads):
            path.write_text('changed fixture input')
            return dict(arguments=args,exit_code=0,wall_seconds=0.0,output='MOCK only; no calculations\n')
        with patch.object(A,'BASE',TEST_ROOT),patch.object(A,'load_inputs',return_value=(reader,plans)),self.assertRaises(A.C.Rejected):
            A.run_example(relative,runner=runner,executable=lambda:self.exe)
        self.assertFalse((A.ROOT/relative/'COMPLETE.json').exists())
        self.assertEqual(json.loads((A.ROOT/relative/'run.json').read_text())['status'],'failed')

    def test_inventory_root_only_receipt_exclusion(self):
        directory=self.root/self._testMethodName;directory.mkdir()
        for name in ('run.json','COMPLETE.json','AK02/run.json','SAP22/COMPLETE.json','AK02/extra.bin'):
            path=directory/name;path.parent.mkdir(exist_ok=True);path.write_bytes(name.encode())
        inventory=A.inventory(directory)
        self.assertEqual(set(inventory),{'AK02/run.json','SAP22/COMPLETE.json','AK02/extra.bin'})
        self.assertEqual(inventory['AK02/run.json']['sha256'],hashlib.sha256(b'AK02/run.json').hexdigest())

    def test_fresh_python_check_has_no_runtime(self):
        args=[sys.executable]
        if Path(sys.executable).name.lower()=='pvpython.exe': args+=['--disable-registry','--no-mpi']
        args+=['-B',str(A.ROOT/'tools/gamma_native_example.py'),'check']
        done=subprocess.run(args,cwd=A.ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=90)
        (self.root/'fresh-check.log').write_bytes(done.stdout)
        self.assertEqual(done.returncode,0,done.stdout.decode(errors='replace'))
        result=json.loads(done.stdout.decode().strip().splitlines()[-1])
        self.assertEqual(result['native_calls'],0);self.assertEqual(result['injection_calibrations'],0)


if __name__=='__main__': unittest.main(verbosity=2)
