"""Publication and sealed KM-prefix fixtures only; no science or servers."""
import copy
import hashlib
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

import scenario_workflow as W
import workflow_recovery as R


def access_error(code=5):
    error=PermissionError('synthetic Windows publication denial');error.winerror=code;return error


class Publication(unittest.TestCase):
    def setUp(self):
        base=W.ROOT/'.local/product-delivery-v1/implementation-tests';base.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=base);self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        assert self.root.resolve().is_relative_to(base.resolve())
        self.path=self.root/'run.json'

    def test_transient_replace_denial_retries_same_atomic_file(self):
        real=os.replace
        for code in (5,32,33):
            calls=[]
            def replace(src,dst):
                calls.append((src,dst))
                if len(calls)<=2:raise access_error(code)
                real(src,dst)
            with self.subTest(code=code),patch.object(W.os,'replace',side_effect=replace),patch.object(W.time,'sleep') as sleep:W.write(self.path,{'status':'running'})
            self.assertEqual(W.read(self.path),{'status':'running'});self.assertEqual(len(calls),3)
            self.assertEqual(len({src for src,dst in calls}),1);self.assertEqual(sleep.call_count,2)
            self.assertEqual(list(self.root.glob('*.pending-*')),[])

    def test_exhaustion_retains_evidence_and_next_write_uses_new_nonce(self):
        W.write(self.path,{'old':'canonical'});body=self.path.read_bytes()
        with patch.object(W.os,'replace',side_effect=access_error(32)) as replace,patch.object(W.time,'sleep') as sleep,self.assertRaises(PermissionError):
            W.write(self.path,{'unpublished':'child identity'})
        self.assertEqual(replace.call_count,7);self.assertEqual(sleep.call_count,6);self.assertEqual(self.path.read_bytes(),body)
        pending=list(self.root.glob('*.pending-*'));self.assertEqual(len(pending),1);before=pending[0].read_bytes()
        W.write(self.path,{'failed':'receipt'});self.assertEqual(pending[0].read_bytes(),before)
        self.assertEqual(W.read(self.path),{'failed':'receipt'})

    def test_foreign_errors_are_not_retried(self):
        for error in (access_error(87),OSError('foreign I/O failure'),FileNotFoundError('missing directory')):
            with patch.object(W.os,'replace',side_effect=error) as replace,patch.object(W.time,'sleep') as sleep,self.assertRaises(type(error)):W.write(self.path,{'failed':'publication'})
            self.assertEqual(replace.call_count,1);sleep.assert_not_called()
        self.assertEqual(len(list(self.root.glob('*.pending-*'))),3)

    def test_existing_or_racing_fresh_output_is_never_overwritten(self):
        self.path.write_bytes(b'other writer')
        with self.assertRaises(W.ControlError):W.write(self.path,{'mine':True},fresh=True)
        self.path.unlink()
        def racing(src,dst):
            self.path.write_bytes(b'other writer');raise FileExistsError('fresh publication collision')
        with patch.object(W.os,'link',side_effect=racing) as link,patch.object(W.time,'sleep') as sleep,self.assertRaises(FileExistsError):W.write(self.path,{'mine':True},fresh=True)
        self.assertEqual(self.path.read_bytes(),b'other writer');self.assertEqual(link.call_count,1);sleep.assert_not_called()
        self.assertEqual(len(list(self.root.glob('*.pending-*'))),1)

    def test_nonce_collision_cannot_overwrite_a_pending_file(self):
        other=self.path.with_name(self.path.name+'.pending-'+str(os.getpid())+'-'+'f'*24);other.write_bytes(b'preserved other write')
        with patch.object(W.secrets,'token_hex',return_value='f'*24),self.assertRaises(FileExistsError):W.write(self.path,{'mine':True})
        self.assertEqual(other.read_bytes(),b'preserved other write');self.assertFalse(self.path.exists())

    def test_secondary_receipt_failure_preserves_original_exception(self):
        selection={'name':'synthetic-write-failure','detector':'AK02','source':W.CS,'threads':1,'primary_count':20,'seed':123}
        plan={'resolved':{'selection':selection,'profile':{}},'configuration_sha256':'synthetic'}
        original=ValueError('original dispatch failure');write=W.write
        def broken_write(path,value,**kwargs):
            if value.get('status')=='failed':raise access_error()
            return write(path,value,**kwargs)
        def executor(*args):raise original
        with (patch.object(W,'admit',return_value=plan),patch.object(W,'verify_pins'),patch.object(W,'verify_dispatch_reservations'),
              patch.object(W,'child_env',return_value={'JULIA_EXE':sys.executable}),patch.object(W,'write',side_effect=broken_write),self.assertRaises(ValueError) as caught):
            W.execute(plan,root=self.root,executor=executor)
        self.assertIs(caught.exception,original);self.assertIn('Failure receipt could not be published',original.__notes__[0])


class KMPrefix(unittest.TestCase):
    def setUp(self):
        base=W.ROOT/'.local/product-delivery-v1/implementation-tests';base.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=base);self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        assert self.root.resolve().is_relative_to(base.resolve())
        self.directory=W.run_path(R.KM_PARENT,self.root);source=W.run_path(R.KM_PARENT)
        for ref in R.preserved_inventory(source):
            target=W.safe_path(self.directory,ref);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(W.safe_path(source,ref),target)
        self.receipt=W.read(self.directory/'run.json');self.pending=W.read(self.directory/R.KM_PENDING);self.oldplan=W.read(self.directory/'resolved-config.json')
        runtime=patch.object(W,'runtime_identity',return_value=copy.deepcopy(self.oldplan['resolved']['runtime_identity']))
        runtime.start();self.addCleanup(runtime.stop)
        commands=W.stage_commands(self.directory,self.receipt['resolved'],self.root,{'JULIA_EXE':self.receipt['runtime']['julia']})
        for stage in R.PREFIX:
            self.receipt['stages'][stage]['arguments']=commands[stage];self.pending['stages'][stage]['arguments']=commands[stage]
        W.write(self.directory/'run.json',self.receipt);W.write(self.directory/R.KM_PENDING,self.pending)
        self.basis=W.read(W.ROOT/R.KM_AUTHORITY)
        for ref in self.oldplan['resolved']['source_sha256']:
            target=W.safe_path(self.root,ref);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(W.safe_path(W.ROOT,ref),target)
        ref=self.basis['driver_log'];target=W.safe_path(self.root,ref);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(W.ROOT/ref,target)
        archived=W.ROOT/R.KM_AUTHORITY;target=W.safe_path(self.root,R.KM_AUTHORITY).parent/self.basis['source_archive'];target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(archived.parent/self.basis['source_archive'],target)
        # Exercise the historical recovery contract with its recorded producer
        # bytes. M14a3 deliberately changes current workflow admission; it does
        # not broaden this frozen two-source recovery exception.
        with zipfile.ZipFile(target) as original:
            for ref,h in self.oldplan['resolved']['source_sha256'].items():
                if ref in original.namelist() and ref not in ('tools/scenario_workflow.py','tools/workflow_recovery.py'):
                    data=original.read(ref)
                    self.assertEqual(hashlib.sha256(data).hexdigest(),h)
                    W.safe_path(self.root,ref).write_bytes(data)
        self.bind_basis()
        scoped=patch.object(R,'KM_AUTHORITY_SHA',W.sha(self.root/R.KM_AUTHORITY));scoped.start();self.addCleanup(scoped.stop)
        self.job={'id':R.KM_DISPATCH,'name':R.KM_PARENT,'plan':self.oldplan,'driver':self.receipt['supervisor'],'status':'dispatch_uncertain'}
        config=copy.deepcopy(self.oldplan['resolved']['selection']);config['name']='synthetic-km-prefix-derivative'
        old=self.oldplan['resolved']
        self.plan=W.check(config,root=self.root,validate_settings=lambda e,r:{'profile':old['profile'],'configuration':old['electronics_configuration'],
            'physics_sha256':old['electronics_physics_sha256']},pin_reader=lambda m,r:{ref:W.sha(W.safe_path(self.root,ref)) for ref in old['source_sha256']},runtime_reader=lambda t:old['runtime_identity'],portable_reader=lambda c,r:None)
        self.quiet={'windows_succeeded':True,'linux_succeeded':True,'relevant_windows_workers':[],'relevant_linux_workers':[]}

    def bind_basis(self):
        self.basis.update(original_run_sha256=W.sha(self.directory/'run.json'),original_pending_sha256=W.sha(self.directory/R.KM_PENDING),
            original_inventory_including_pending=R.preserved_inventory(self.directory))
        W.write(self.root/R.KM_AUTHORITY,self.basis)

    def inspect(self):
        with patch.object(W,'process_identity',return_value=None):return R.inspect_parent(self.job,self.root,probe=lambda root:self.quiet)

    def retire(self):
        value=self.inspect();stamp=R.release(self.job,self.plan,value,self.root)
        self.job.update(status='verified_transport',prefix_authority_sha256=stamp)
        W.write(self.root/(R.STATE+'/workflow-jobs.json'),{'kind':'local_workflow_jobs_v1','jobs':[self.job]})

    def test_exact_prefix_preserves_pending_and_unknown_exit_time(self):
        before=R.preserved_inventory(self.directory);value=self.inspect();self.assertEqual(value['new_radiation_calls'],0)
        self.assertEqual(len(value['original_inventory']),27);self.assertEqual(before,R.preserved_inventory(self.directory))
        _,receipt,_=R.km_parent(self.root);stage=receipt['stages']['event_ledger']
        for key in ('exit_code','elapsed_seconds','finished_utc'):self.assertIsNone(stage[key])
        self.assertEqual(stage['pid'],self.pending['stages']['event_ledger']['pid'])

    def test_changed_or_rehashed_unknown_pending_transition_is_rejected(self):
        self.pending['resolved']['selection']['electronics']['gain']=22;W.write(self.directory/R.KM_PENDING,self.pending);self.bind_basis()
        with patch.object(R,'KM_AUTHORITY_SHA',W.sha(self.root/R.KM_AUTHORITY)),self.assertRaises(W.ControlError):self.inspect()

    def test_rehashed_manifest_wrong_model_fails_independent_semantics(self):
        path=self.directory/'transport/stream/manifest.json';value=W.read(path);value['model_id']='GeRC02';W.write(path,value)
        (self.directory/'event_ledger.log').write_bytes(path.read_bytes());self.bind_basis()
        self.basis['verified_stage_artifacts']['event_ledger']['manifest.json']={'sha256':W.sha(path),'bytes':path.stat().st_size};W.write(self.root/R.KM_AUTHORITY,self.basis)
        with patch.object(R,'KM_AUTHORITY_SHA',W.sha(self.root/R.KM_AUTHORITY)),self.assertRaises((W.ControlError,ValueError)):self.inspect()

    def test_unknown_pid_quiescence_failures_and_foreign_sources_block(self):
        for identity in ('unknown',self.receipt['supervisor']['identity'],self.pending['stages']['event_ledger']['process_identity']):
            with patch.object(W,'process_identity',return_value=identity),self.assertRaises(W.ControlError):R.inspect_parent(self.job,self.root,probe=lambda root:self.quiet)
        for key,value in (('windows_succeeded',False),('linux_succeeded',False),('relevant_windows_workers',[{'pid':1}]),('relevant_linux_workers',[{'pid':2}])):
            with patch.object(W,'process_identity',return_value=None),self.assertRaises(W.ControlError):R.inspect_parent(self.job,self.root,probe=lambda root:dict(self.quiet,**{key:value}))
        path=self.root/'simulation/readout.jl';path.write_bytes(path.read_bytes()+b'foreign source')
        with self.assertRaises(W.ControlError):self.inspect()

    def test_new_plan_cannot_change_settings_runtime_sources_or_remove_pins(self):
        R.compatible(self.oldplan['resolved'],self.plan['resolved'])
        for mutate in (lambda r:r['selection'].update(seed=123),lambda r:r['selection']['electronics'].update(gain=22),
                       lambda r:r['runtime_identity'].update(julia_sha256='d'*64),lambda r:r['source_sha256'].update({'simulation/readout.jl':'d'*64}),
                       lambda r:r['source_sha256'].pop('transport/handoff.py')):
            other=copy.deepcopy(self.plan['resolved']);mutate(other)
            with self.assertRaises(W.ControlError):R.compatible(self.oldplan['resolved'],other)

    def test_lossless_copy_null_ledger_and_new_request_only(self):
        self.retire();target=W.run_path(self.plan['resolved']['selection']['name'],self.root);target.mkdir()
        W.write(target/'electronics/profile.json',self.plan['resolved']['profile'],fresh=True);receipt={'stages':{}};before=R.preserved_inventory(self.directory)
        with patch.object(W,'process_identity',return_value=None):R.transfer(target,self.plan,receipt,self.root,probe=lambda root:self.quiet)
        stage=receipt['stages']['event_ledger'];self.assertEqual(stage['status'],'completed')
        for key in ('exit_code','elapsed_seconds','finished_utc','original_elapsed_seconds'):self.assertIsNone(stage[key])
        self.assertEqual(stage['original_pending_stage_receipt'],self.pending['stages']['event_ledger'])
        self.assertEqual(receipt['transport_reuse']['new_geometry_calls'],0);self.assertEqual(receipt['transport_reuse']['new_ledger_calls'],0)
        import ring_workflow as ring
        request=ring.request(target,self.plan['resolved'],self.root)
        self.assertEqual(request['operating_model']['wiring_factor'],-1);self.assertEqual(request['selection']['seed'],26100342)
        self.assertEqual(request['selection']['electronics']['gain'],21);self.assertEqual(request['selection']['electronics']['peak_gate_end_ns'],9000)
        self.assertEqual(request['configuration_sha256'],self.plan['configuration_sha256']);self.assertEqual(before,R.preserved_inventory(self.directory))
        self.assertFalse((target/R.KM_PENDING).exists());self.assertFalse((target/'response').exists())

    def test_orchestration_never_redispatches_completed_prefix(self):
        self.retire();calls=[];validate=W.validate_stage
        def saved_validate(directory,stage,resolved,root,**kwargs):
            return W.inventory(directory/'response') if stage=='response' else validate(directory,stage,resolved,root,**kwargs)
        def response(argv,directory,stage,receipt,environment,root):
            calls.append(stage);self.assertEqual(stage,'response')
            receipt['stages'][stage]={'status':'command_exited','exit_code':0}
            W.write(directory/'response/run.json',{'counts':{'initial_primaries':500,'native_failed_groups':0}})
        with (patch.object(W,'process_identity',return_value=None),patch.object(R.I,'inventories',return_value=self.quiet),
              patch.object(W,'admit',return_value=self.plan),patch.object(W,'verify_pins'),patch.object(W,'verify_dispatch_reservations'),
              patch.object(W,'runtime_identity',return_value=self.oldplan['resolved']['runtime_identity']),
              patch.object(W,'child_env',return_value={'JULIA_EXE':sys.executable}),patch.object(W,'validate_stage',side_effect=saved_validate)):
            done=W.execute(self.plan,root=self.root,executor=response,continuation=True)
        self.assertEqual(calls,['response']);self.assertEqual(done['status'],'completed');self.assertEqual(done['stages']['event_ledger']['exit_code'],None)

if __name__=='__main__':unittest.main()
