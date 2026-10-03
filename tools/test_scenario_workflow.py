"""Finite workflow boundary tests. Fixtures are synthetic; no science is run."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import scenario_workflow as W


class Workflow(unittest.TestCase):
    def setUp(self):
        base=W.ROOT/'.local/product-delivery-v1/implementation-tests';base.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=base);self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.default=W.catalog()['electronics_defaults']
        self.config=dict(name='fixture-01',cryostat=W.CRYOSTAT,detector='AK02',source=W.GAMMA,pose='plus5mm',
                         primary_count=20,seed=26092631,threads=2,electronics=self.default)
        self.settings=lambda values,root: {'profile':{'schema_version':2,'settings':copy.deepcopy(values)},
            'configuration':dict(values,expected_primary_count=None,max_samples_per_event=500000,max_window_ns=1000000),'physics_sha256':W.digest(values)}
        self.pins=lambda model,root: {'pinned.txt':'science-not-run'}
        self.runtime=lambda threads:{'python_sha256':'test-only','julia_sha256':'test-only'}

    def check(self,c=None):
        return W.check(c or self.config,root=self.root,validate_settings=self.settings,
                       pin_reader=self.pins,runtime_reader=self.runtime,portable_reader=lambda c,r:None)

    def test_actual_source_and_detector_choices_change_config(self):
        p=self.check();c=copy.deepcopy(self.config);c.update(detector='SAP22');q=self.check(c)
        self.assertNotEqual(p['configuration_sha256'],q['configuration_sha256']);self.assertEqual(q['resolved']['numerics']['bias_V'],700)
        c.update(source=W.CS,pose='nominal',primary_count=500,seed=123);q=self.check(c)
        self.assertEqual(q['resolved']['source_kind'],'radioactive_decay');self.assertEqual(q['resolved']['source_position_global_mm'],[0,37.073,.290])

    def test_all_electronics_and_thread_choices_are_bound(self):
        original=self.check()
        for key,value in [('gain',10),('adc_bits',16),('peak_gate_start_ns',100),('peak_gate_end_ns',9000)]:
            c=copy.deepcopy(self.config);c['electronics'][key]=value
            if key=='peak_gate_start_ns':c['electronics']['peak_gate_end_ns']=9000
            if key=='peak_gate_end_ns':c['electronics']['peak_gate_start_ns']=0
            changed=self.check(c);self.assertNotEqual(original['configuration_sha256'],changed['configuration_sha256'])
        c=copy.deepcopy(self.config);c['threads']=1;self.assertEqual(self.check(c)['resolved']['selection']['threads'],1)

    def test_unsupported_selections_and_types_fail_before_pins(self):
        for key,value in [('detector','GeRC02'),('cryostat','other'),('source','Am241'),('pose','nominal'),
                          ('primary_count',500),('seed',42),('threads',True),('primary_count',20.0),('seed',True),('name','../escape'),('name','CON')]:
            c=copy.deepcopy(self.config);c[key]=value
            with self.subTest(key=key,value=value),self.assertRaises(W.ControlError):self.check(c)
        c=copy.deepcopy(self.config);c['extra']=1
        with self.assertRaises(W.ControlError):self.check(c)

    def test_existing_output_is_refused(self):
        W.run_path(self.config['name'],self.root).mkdir(parents=True)
        with self.assertRaises(W.ControlError):self.check()

    def test_rehashed_resolved_mutants_do_not_become_authority(self):
        plan=self.check()
        for mutate in (lambda r:r['numerics'].update(bias_V=501),lambda r:r['source_sha256'].clear(),
                       lambda r:r['electronics_configuration'].update(gain=11),lambda r:r['runtime_identity'].update(julia_sha256='other')):
            changed=copy.deepcopy(plan);mutate(changed['resolved']);changed['configuration_sha256']=W.digest(changed['resolved'])
            with patch.object(W,'check',return_value=plan),self.assertRaises(W.ControlError):W.admit(changed,self.root)

    def test_source_change_after_check_is_refused(self):
        (self.root/'pinned.txt').write_text('first');r={'source_sha256':{'pinned.txt':W.sha(self.root/'pinned.txt')}}
        (self.root/'pinned.txt').write_text('different')
        with self.assertRaises(W.ControlError):W.verify_pins(r,self.root)

    def test_command_dispatch_uses_correct_existing_source_backend(self):
        plan=self.check();env={'JULIA_EXE':'julia-pinned.exe'}
        cmds=W.stage_commands(W.run_path('fixture-01',self.root),plan['resolved'],self.root,env)
        self.assertIn('./scenario_transport.py',cmds['radiation']);self.assertIn(str(self.root/'simulation/scenario_response.jl'),cmds['response'])
        c=copy.deepcopy(self.config);c.update(source=W.CS,pose='nominal',primary_count=20)
        cmds=W.stage_commands(W.run_path('fixture-01',self.root),self.check(c)['resolved'],self.root,env)
        self.assertIn('./cs137.py',cmds['radiation']);self.assertIn(str(self.root/'simulation/native_response_guarded.jl'),cmds['response'])
        self.assertNotIn('gamma_native_example.py',' '.join(cmds['response']))

    def test_artifact_and_linked_paths_are_refused(self):
        with self.assertRaises(W.ControlError):W.run_path('bad/name',self.root)
        (self.root/'artifact.json').write_text('original');files=W.inventory(self.root)
        (self.root/'artifact.json').write_text('changed')
        with self.assertRaises(W.ControlError):W.verify_inventory(self.root,files)

    def test_stop_before_first_stage_dispatch(self):
        plan=self.check();directory=W.run_path('fixture-01',self.root)
        # mkdir/run receipts are real IO; all runtime/science functions are blocked/mocked.
        def no_science(*args):self.fail('Stop must prevent dispatch')
        def on_commands(*args):W.write(directory/'STOP.json',{'test':True},fresh=True);return {}
        with patch.object(W,'admit',return_value=plan),patch.object(W,'verify_pins'),patch.object(W,'child_env',return_value={'JULIA_EXE':__file__}),patch.object(W,'stage_commands',side_effect=on_commands):
            r=W.execute(plan,root=self.root,executor=no_science)
        self.assertEqual(r['status'],'stopped');self.assertEqual(r['stages'],{})

    def test_partial_stage_cannot_resume(self):
        plan=self.check();d=W.run_path('fixture-01',self.root);d.mkdir(parents=True)
        W.write(d/'run.json',{'kind':W.KIND,'configuration_sha256':plan['configuration_sha256'],'status':'stopped','stages':{'response':{'status':'running'}}},fresh=True)
        with patch.object(W,'admit',return_value=plan),patch.object(W,'verify_pins'),patch.object(W,'child_env',return_value={'JULIA_EXE':__file__}),self.assertRaises(W.ControlError):W.execute(plan,root=self.root,resume=True)

    def test_uncertain_other_run_prevents_new_dispatch(self):
        plan=self.check();d=W.run_path('old-uncertain',self.root);d.mkdir(parents=True)
        W.write(d/'run.json',{'kind':W.KIND,'status':'running','stages':{}},fresh=True)
        with patch.object(W,'admit',return_value=plan),self.assertRaises(W.ControlError):W.execute(plan,root=self.root)

    def test_gui_reservation_blocks_cli_even_without_output(self):
        plan=self.check()
        W.write(self.root/'.local/local-control-v1/workflow-jobs.json',{'kind':'local_workflow_jobs_v1',
            'jobs':[{'id':'a'*32,'status':'dispatch_uncertain','plan':plan,'driver':None}]},fresh=True)
        with self.assertRaises(W.ControlError):W.verify_dispatch_reservations(plan,self.root)

    def test_only_committed_exact_gui_driver_may_dispatch(self):
        plan=self.check();import os
        path=self.root/'.local/local-control-v1/workflow-jobs.json'
        job={'id':'a'*32,'status':'running','plan':plan,'driver':{'pid':os.getpid(),'identity':'own-identity'}}
        W.write(path,{'kind':'local_workflow_jobs_v1','jobs':[job]},fresh=True)
        with patch.object(W,'process_identity',return_value='own-identity'):W.verify_dispatch_reservations(plan,self.root,'a'*32)
        for identity in (None,'unknown','different-creation'):
            with patch.object(W,'process_identity',return_value=identity),self.assertRaises(W.ControlError):W.verify_dispatch_reservations(plan,self.root,'a'*32)

    def test_resume_changed_completed_artifact_refused(self):
        plan=self.check();d=W.run_path('fixture-01',self.root);t=d/'transport';t.mkdir(parents=True)
        (t/'geometry.json').write_text('first');artifacts=W.inventory(t);(t/'geometry.json').write_text('changed')
        W.write(d/'run.json',{'kind':W.KIND,'configuration_sha256':plan['configuration_sha256'],'status':'stopped',
                            'stages':{'geometry':{'status':'completed','artifacts':artifacts}}},fresh=True)
        with patch.object(W,'admit',return_value=plan),patch.object(W,'verify_pins'),patch.object(W,'child_env',return_value={'JULIA_EXE':__file__}),self.assertRaises(W.ControlError):W.execute(plan,root=self.root,resume=True)

    def test_shared_existing_settings_authority_actual_default_and_custom(self):
        # PowerShell data-only schema checks; no Julia/WSL or propagator executes.
        result=W.settings_check(self.default)
        self.assertEqual(result['status'],'valid_configuration_only')
        changed=dict(self.default,gain=10.0,adc_bits=16)
        actual=W.settings_check(changed)
        self.assertEqual(actual['configuration']['gain'],10);self.assertEqual(actual['configuration']['adc_bits'],16)
        with self.assertRaises(W.ControlError):W.settings_check(dict(self.default,threshold_V=11))

    def test_calibration_and_fractional_gate_fail_before_pins(self):
        for patch_values in ({'shaping_tau_us':51},{'shaping_tau_us':.00001},{'shaping_tau_us':1e308},
                             {'peak_gate_start_ns':0,'peak_gate_end_ns':.1},
                             {'peak_gate_start_ns':.1,'peak_gate_end_ns':2.1}):
            c=copy.deepcopy(self.config);c['electronics'].update(patch_values)
            with self.subTest(patch=patch_values),self.assertRaises(W.ControlError):self.check(c)
        actual=W.settings_check(dict(self.default,shaping_tau_us=51))
        with self.assertRaises(W.ControlError):W.electronics_feasibility(actual['configuration'])
        c=copy.deepcopy(self.config);c['electronics'].update(peak_gate_start_ns=.1,peak_gate_end_ns=4.1)
        self.check(c)
        raw=dict(self.default,max_samples_per_event=500000,max_window_ns=1000000,peak_gate_start_ns=0,peak_gate_end_ns=1000000)
        with self.assertRaises(W.ControlError):W.electronics_feasibility(raw)

    def test_cs_finite_window_has_source_specific_gate_admission(self):
        c=copy.deepcopy(self.config);c.update(source=W.CS,pose='nominal');c['electronics'].update(peak_gate_start_ns=.1,peak_gate_end_ns=100000)
        with self.assertRaises(W.ControlError):self.check(c)
        c['electronics']['peak_gate_end_ns']=99997.9;self.check(c)
        c.update(source=W.GAMMA,pose='plus5mm');c['electronics']['peak_gate_end_ns']=100000;self.check(c)

    def test_gamma_two_sample_zero_input_tail_exact_budget(self):
        c=copy.deepcopy(self.config);c['electronics']['shaping_tau_us']=49.9999
        with self.assertRaises(W.ControlError):self.check(c)
        c['electronics']['shaping_tau_us']=49.9998;self.check(c)


if __name__=='__main__':unittest.main()
