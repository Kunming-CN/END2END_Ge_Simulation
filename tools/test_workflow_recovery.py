"""Lossless prefix derivative boundaries. Only the response worker is mocked.

Fixtures copy the preserved transport bytes into classified temporary roots.
No radiation/field/native/calibration execution; no original artifact is written.
"""
import copy
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import scenario_workflow as W
import workflow_recovery as R


class Recovery(unittest.TestCase):
    def setUp(self):
        base=W.ROOT/'.local/product-delivery-v1/implementation-tests';base.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=base);self.root=Path(self.temp.name)
        assert self.root.resolve().is_relative_to(base.resolve())
        self.addCleanup(self.temp.cleanup)
        self.directory=W.run_path(R.PARENT,self.root);self.directory.mkdir(parents=True)
        original=W.run_path(R.PARENT)
        for name in W.inventory(original):
            target=W.safe_path(self.directory,name);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(W.safe_path(original,name),target)
        self.original=W.read(self.directory/'run.json');self.oldplan=W.read(self.directory/'resolved-config.json')
        commands=W.stage_commands(self.directory,self.original['resolved'],self.root,{'JULIA_EXE':self.original['runtime']['julia']})
        for stage in self.original['stages']:self.original['stages'][stage]['arguments']=commands[stage]
        W.write(self.directory/'run.json',self.original)
        self.authority=W.read(W.ROOT/R.AUTHORITY)
        frozen=W.ROOT/self.authority['source_freeze'];destination=self.root/self.authority['source_freeze']
        destination.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(frozen,destination)
        self.bind_authority()
        authority_patch=patch.object(R,'AUTHORITY_SHA',W.sha(self.root/R.AUTHORITY));authority_patch.start();self.addCleanup(authority_patch.stop)
        gamma=W.gamma_request
        # Current source admission/producer hashes are separately asserted by the
        # compatibility tests. These relocated test roots contain science inputs only.
        gamma_patch=patch.object(W,'gamma_request',side_effect=lambda directory,resolved,root,**kwargs:gamma(directory,resolved,root,historical=True))
        gamma_patch.start();self.addCleanup(gamma_patch.stop)
        self.job={'id':R.PARENT_DISPATCH,'name':R.PARENT,'plan':self.oldplan,'driver':self.original['supervisor'],'status':'dispatch_uncertain'}
        self.plan=copy.deepcopy(self.oldplan);self.plan['resolved']['selection']['name']='synthetic-prefix-derivative'
        pins=self.plan['resolved']['source_sha256'];pins['tools/scenario_workflow.py']='b'*64;pins['simulation/scenario_response.jl']=R.PATCHED_BOOTSTRAP;pins['tools/workflow_recovery.py']='c'*64
        self.plan['configuration_sha256']=W.digest(self.plan['resolved'])
        self.quiet={'windows_succeeded':True,'linux_succeeded':True,'relevant_windows_workers':[],'relevant_linux_workers':[]}

    def bind_authority(self):
        self.authority['run_sha256']=W.sha(self.directory/'run.json');self.authority['original_inventory']=W.inventory(self.directory)
        W.write(self.root/R.AUTHORITY,self.authority)

    def inspect(self,quiet=None):
        with patch.object(W,'process_identity',return_value=None):return R.inspect_parent(self.job,self.root,probe=lambda root:quiet or self.quiet)

    def retire(self):
        stamp=R.release(self.job,self.plan,self.inspect(),self.root)
        self.job.update(status='verified_transport',prefix_authority_sha256=stamp)
        W.write(self.root/(R.STATE+'/workflow-jobs.json'),{'kind':'local_workflow_jobs_v1','jobs':[self.job]},fresh=True)

    def test_recognized_parent_checks_complete_raw_census_without_science(self):
        before=W.inventory(self.directory);value=self.inspect()
        self.assertEqual(value['new_radiation_calls'],0);self.assertEqual(value['response_entrypoint_calls'],0)
        self.assertEqual(before,W.inventory(self.directory))

    def test_changed_log_hash_source_or_unexpected_response_output_refused(self):
        for name in ('response.log','resolved-config.json','transport/prepared.json'):
            original=(self.directory/name).read_bytes();(self.directory/name).write_bytes(original+b' ')
            with self.subTest(file=name),self.assertRaises(W.ControlError):self.inspect()
            (self.directory/name).write_bytes(original)
        (self.directory/'response').mkdir()
        with self.assertRaises(W.ControlError):self.inspect()

    def test_rehashed_wrong_prepared_model_fails_independent_semantics(self):
        path=self.directory/'transport/prepared.json';prepared=W.read(path);prepared['model_id']='AK02';W.write(path,prepared)
        self.original['stages']['geometry']['artifacts']['prepared.json']={'sha256':W.sha(path),'bytes':path.stat().st_size}
        W.write(self.directory/'run.json',self.original);self.bind_authority()
        with patch.object(R,'AUTHORITY_SHA',W.sha(self.root/R.AUTHORITY)),self.assertRaises(W.ControlError):self.inspect()

    def test_unknown_or_matching_stage_identity_stays_blocked(self):
        for identity in ('unknown',self.original['supervisor']['identity'],self.original['stages']['response']['process_identity']):
            with self.subTest(identity=identity),patch.object(W,'process_identity',return_value=identity),self.assertRaises(W.ControlError):R.inspect_parent(self.job,self.root,probe=lambda root:self.quiet)

    def test_failed_quiescence_or_observed_worker_stays_blocked(self):
        for key,value in [('windows_succeeded',False),('linux_succeeded',False),('relevant_windows_workers',[{'pid':1}]),('relevant_linux_workers',[{'pid':2}])]:
            quiet=dict(self.quiet);quiet[key]=value
            with self.subTest(key=key),self.assertRaises(W.ControlError):self.inspect(quiet)

    def test_mismatched_dispatch_or_rehashed_selected_settings_refused(self):
        self.job['id']='d'*32
        with self.assertRaises(W.ControlError):self.inspect()
        self.job['id']=R.PARENT_DISPATCH;self.job['plan']=copy.deepcopy(self.oldplan);self.job['plan']['resolved']['selection']['electronics']['gain']=22
        self.job['plan']['configuration_sha256']=W.digest(self.job['plan']['resolved'])
        with self.assertRaises(W.ControlError):self.inspect()

    def test_derivative_source_runtime_settings_and_removed_pins_refused(self):
        R.compatible(self.oldplan['resolved'],self.plan['resolved'])
        for mutate in (lambda r:r['selection'].update(detector='AK02'),lambda r:r['selection']['electronics'].update(gain=22),
                       lambda r:r['runtime_identity'].update(julia_sha256='d'*64),lambda r:r['source_sha256'].update({'simulation/readout.jl':'d'*64}),
                       lambda r:r['source_sha256'].pop('transport/handoff.py')):
            altered=copy.deepcopy(self.plan['resolved']);mutate(altered)
            with self.assertRaises(W.ControlError):R.compatible(self.oldplan['resolved'],altered)

    def test_lossless_transfer_keeps_runtime_path_and_inherited_timings(self):
        self.retire();target=W.run_path('synthetic-prefix-derivative',self.root);target.mkdir()
        W.write(target/'electronics/profile.json',self.plan['resolved']['profile'],fresh=True);receipt={'stages':{}}
        before=W.inventory(self.directory)
        with patch.object(W,'process_identity',return_value=None):R.transfer(target,self.plan,receipt,self.root,probe=lambda root:self.quiet)
        self.assertEqual(before,W.inventory(self.directory));self.assertFalse((target/'response.log').exists());self.assertFalse((target/'gamma-request.json').exists())
        self.assertEqual((target/'transport/run.json').read_bytes(),(self.directory/'transport/run.json').read_bytes())
        self.assertEqual((target/'emlow-data.json').read_bytes(),(self.directory/'emlow-data.json').read_bytes())
        for stage,record in receipt['stages'].items():
            self.assertNotIn('elapsed_seconds',record);self.assertEqual(record['original_elapsed_seconds'],self.original['stages'][stage]['elapsed_seconds'])
        self.assertEqual(receipt['transport_reuse']['new_radiation_calls'],0)

    def test_successful_derivative_dispatches_response_and_results_only(self):
        self.retire();called=[];before=W.inventory(self.directory);original_validator=W.validate_stage
        def execute(argv,directory,stage,receipt,environment,root):
            called.append(stage);self.assertEqual(stage,'response')
            old=W.read(self.directory/'gamma-request.json');new=W.read(directory/'gamma-request.json')
            self.assertEqual(old['events'],new['events']);self.assertNotEqual(old['configuration_sha256'],new['configuration_sha256'])
            self.assertIn('.local/runs/synthetic-prefix-derivative/transport/prepared.json',new['pins'])
            W.write(directory/'response/run.json',{'counts':{'native_failed_groups':0}},fresh=True)
            receipt['stages'][stage]={'status':'command_exited','elapsed_seconds':.01}
        def validate(directory,stage,resolved,root,**kwargs):
            return W.inventory(directory/'response') if stage=='response' else original_validator(directory,stage,resolved,root,**kwargs)
        with patch.object(W,'admit',return_value=self.plan),patch.object(W,'verify_pins'),patch.object(W,'child_env',return_value={'JULIA_EXE':self.original['runtime']['julia']}),patch.object(W,'process_identity',return_value=None),patch.object(R.I,'inventories',return_value=self.quiet),patch.object(W,'validate_stage',side_effect=validate):
            result=W.execute(self.plan,root=self.root,continuation=True,executor=execute)
        self.assertEqual(called,['response']);self.assertEqual(result['status'],'completed');self.assertEqual(set(result['stages']),set(W.STAGES))
        self.assertEqual(before,W.inventory(self.directory));self.assertGreaterEqual(result['stages']['results']['elapsed_seconds'],0)


if __name__=='__main__':unittest.main()
