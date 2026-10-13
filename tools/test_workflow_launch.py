"""Pre-Popen recovery and uncertainty-boundary regressions; no science starts."""
import copy
from contextlib import contextmanager, ExitStack
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import scenario_workflow as W
import local_ui_workflow_jobs as J
import workflow_launch as L


def fixture_plan(name='not-launched'):
    return {'kind': J.B.CHECKED_KIND, 'schema_version': 3,
            'status': 'checked_configuration', 'execution_enabled': True,
            'science_calls': 0, 'configuration_sha256': 'synthetic-controller-only',
            'resolved': {'selection': {'name': name, 'detector': 'AK02',
                         'source': W.CS, 'primary_count': 500},
                         'batching': {'batch_count': 1}}}


def reserved_controller(root, plan=None):
    plan = plan or fixture_plan()
    controller = J.WorkflowController(root, batch_resolver=lambda config, root: copy.deepcopy(plan))
    checked = controller.check_batches({'kind': 'local_scenario_batch_request_v2',
                                       'schema_version': 2, 'selection': plan['resolved']['selection']})
    with patch.object(controller, '_launch', side_effect=controller._view):
        controller.start(checked['check_id'])
    return controller


def make_preparation_failure(root, plan=None):
    """Desktop fixture: real preparation failure before the actual launcher.

    Only the dispatch-plan publication fails. All journal/state writes are real;
    subprocess.Popen is an assertion guard and must receive no invocation.
    """
    controller = reserved_controller(root, plan)
    original_write = W.write
    plan_path = L.auxiliary(controller._jobs[0], root)['plan']
    def fail_plan(path, value, **kwargs):
        if Path(path) == plan_path: raise PermissionError('Synthetic dispatch-plan publication denied before Popen')
        return original_write(path, value, **kwargs)
    with patch.object(W, 'write', side_effect=fail_plan), patch.object(J.subprocess, 'Popen', side_effect=AssertionError('Unexpected process creation')) as popen:
        controller._work(controller._jobs[0]); popen.assert_not_called()
    return controller


class LaunchRecovery(unittest.TestCase):
    def setUp(self):
        base = W.ROOT/'.local/strict01-recovery-v1/implementation/test-fixtures'
        base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def recover(self, controller):
        return controller.recover_launch(controller._jobs[0]['name'])

    def test_preparation_failure_reopen_repeat_preserves_error_and_releases_cli(self):
        controller = make_preparation_failure(self.root); job = controller._jobs[0]
        failed = W.read(L.directory(job, self.root)/'failure.json')
        self.assertFalse(failed['popen_invoked']); self.assertEqual(failed['boundary'], 'controller_preparation')
        self.assertIsNone(job['driver']); self.assertTrue(controller.own_busy())
        self.assertTrue(controller.snapshot()['jobs'][0]['can_recover_launch'])
        with self.assertRaises(W.ControlError): W.verify_dispatch_reservations(None, self.root)
        reopened = J.WorkflowController(self.root)
        before = W.inventory(L.directory(job, self.root))
        recovered = self.recover(reopened)
        self.assertEqual(recovered['status'], 'launch_failed'); self.assertIn('publication denied', recovered['error'])
        self.assertFalse(reopened.own_busy())
        self.assertEqual(self.recover(controller)['status'], 'launch_failed')
        W.verify_inventory(L.directory(job, self.root), before)
        # Exercise actual shared CLI admission and lease, not only GUI busy.
        with W.execution_lease(self.root): W.verify_dispatch_reservations(fixture_plan('fresh-cli'), self.root)
        self.assertFalse(W.run_path(job['name'], self.root).exists())
        self.assertFalse(J.WorkflowController(self.root).own_busy())
        self.assertEqual(len(W.read(controller._state_path)['jobs']), 1)

    def test_managed_log_open_failure_has_proof_without_popen(self):
        controller = reserved_controller(self.root); job = controller._jobs[0]
        original_open = Path.open; log = L.auxiliary(job, self.root)['log']
        def open_file(path, *args, **kwargs):
            if path == log: raise PermissionError('Synthetic log creation denial')
            return original_open(path, *args, **kwargs)
        with patch.object(Path, 'open', open_file), patch.object(J.subprocess, 'Popen') as popen:
            controller._work(job); popen.assert_not_called()
        failed = L.verify_failure(job, self.root)
        self.assertEqual(failed['boundary'], 'managed_launcher_preparation')
        self.assertEqual(self.recover(controller)['status'], 'launch_failed')

    def test_arbitrary_launcher_exception_and_old_null_driver_have_no_authority(self):
        controller = reserved_controller(self.root)
        controller._launcher = Mock(side_effect=OSError('Uncontrolled launcher failed; child may exist'))
        controller._work(controller._jobs[0])
        self.assertFalse(controller.snapshot()['jobs'][0]['can_recover_launch'])
        with self.assertRaises((OSError, W.ControlError)): self.recover(controller)
        job = controller._jobs[0]; job.pop('launch_intent_sha256'); controller._persist()
        with self.assertRaises((OSError, W.ControlError)): self.recover(J.WorkflowController(self.root))
        self.assertTrue(controller.own_busy())

    def test_popen_oserror_even_after_possible_creation_stays_uncertain(self):
        controller = reserved_controller(self.root); job = controller._jobs[0]
        def created_then_failed(*args, **kwargs):
            self.assertTrue((L.directory(job, self.root)/'popen-entered.json').is_file())
            # Models an API that created a child but failed before returning it.
            raise OSError('Child possibly created, no process object returned')
        with patch.object(J.subprocess, 'Popen', side_effect=created_then_failed): controller._work(job)
        self.assertIsNone(job['driver']); self.assertNotIn('launch_failure_sha256', job)
        reopened = J.WorkflowController(self.root)
        self.assertTrue(reopened.own_busy()); self.assertFalse(reopened.snapshot()['jobs'][0]['can_recover_launch'])
        with self.assertRaises((OSError, W.ControlError)): self.recover(reopened)
        with self.assertRaises(W.ControlError): W.verify_dispatch_reservations(None, self.root)

    def test_popen_success_callback_persistence_failure_is_not_recoverable(self):
        controller = reserved_controller(self.root); job = controller._jobs[0]
        original_persist = controller._persist; failed_once = False
        def persist():
            nonlocal failed_once
            if job['driver'] is not None and not failed_once:
                failed_once = True; raise PermissionError('Created child callback publication failed')
            original_persist()
        child = Mock(pid=999991); child.wait.return_value = 0
        with patch.object(J.subprocess, 'Popen', return_value=child), patch.object(J, 'process_identity', return_value='created-child'), patch.object(controller, '_persist', side_effect=persist):
            controller._work(job)
        self.assertTrue((L.directory(job, self.root)/'popen-returned.json').is_file())
        child.wait.assert_not_called(); self.assertTrue(controller.own_busy())
        with patch.object(W, 'process_identity', return_value=None), self.assertRaises((OSError, W.ControlError)): self.recover(controller)

    def test_missing_child_commit_after_popen_return_blocks_across_reopen(self):
        controller = reserved_controller(self.root); job = controller._jobs[0]
        child = Mock(pid=999991)
        original_write = W.write
        def write(path, value, **kwargs):
            if Path(path).name == 'popen-returned.json': raise PermissionError('Lost post-create receipt')
            return original_write(path, value, **kwargs)
        with patch.object(W, 'write', side_effect=write), patch.object(J.subprocess, 'Popen', return_value=child): controller._work(job)
        self.assertIsNone(job['driver']); self.assertTrue(J.WorkflowController(self.root).own_busy())
        with self.assertRaises((OSError, W.ControlError)): self.recover(controller)

    def test_created_child_can_acquire_shared_lease_and_complete_identity_handshake(self):
        controller = reserved_controller(self.root); job = controller._jobs[0]; worker_errors = []
        def worker():
            try:
                with W.execution_lease(self.root):
                    W.verify_dispatch_reservations(job['plan'], self.root, job['id'])
                    output=W.run_path(job['name'], self.root);output.mkdir(parents=True)
                    W.write(output/'run.json', {'status':'stopped', 'stages':{}})
            except BaseException as error: worker_errors.append(error)
        thread=threading.Thread(target=worker)
        def create(*args, **kwargs):
            self.assertTrue((L.directory(job, self.root)/'popen-entered.json').is_file())
            self.assertFalse(W.lease_busy(self.root))
            thread.start()
            child=Mock(pid=os.getpid())
            def wait():thread.join(6);self.assertFalse(thread.is_alive());return 0
            child.wait.side_effect=wait;return child
        with patch.object(J.subprocess,'Popen',side_effect=create),patch.object(J,'process_identity',return_value='synthetic-child'),patch.object(W,'process_identity',return_value='synthetic-child'):
            controller._work(job)
        self.assertEqual(worker_errors, []);self.assertEqual(job['status'], 'stopped')
        self.assertTrue((L.directory(job, self.root)/'popen-returned.json').is_file())
        self.assertNotIn('launch_failure_sha256',job)

    def test_two_reopened_controllers_do_not_duplicate_recovery(self):
        first=make_preparation_failure(self.root);second=J.WorkflowController(self.root)
        ready=threading.Barrier(2);results=[]
        def recover(controller):
            ready.wait(5)
            try:results.append(('settled',self.recover(controller)['status']))
            except W.ControlError:results.append(('lease_conflict',None))
        threads=[threading.Thread(target=recover,args=(controller,)) for controller in (first,second)]
        for thread in threads:thread.start()
        for thread in threads:thread.join(5);self.assertFalse(thread.is_alive())
        self.assertTrue(any(result==('settled','launch_failed') for result in results))
        self.assertEqual(self.recover(first)['status'],'launch_failed')
        self.assertEqual(self.recover(second)['status'],'launch_failed')
        self.assertEqual(len(W.read(first._state_path)['jobs']),1)
        L.verify_retirement(first._jobs[0],self.root)

    def test_partial_output_changed_plan_log_and_corrupt_evidence_refused(self):
        for mutation in ('output', 'plan', 'log', 'failure', 'rehashed_failure', 'extra_boundary'):
            with self.subTest(mutation=mutation):
                root = self.root/mutation; root.mkdir(); controller = make_preparation_failure(root); job = controller._jobs[0]
                if mutation == 'output': W.run_path(job['name'], root).mkdir(parents=True)
                elif mutation == 'plan': job['plan']['resolved']['selection']['primary_count'] = 501; controller._persist()
                elif mutation == 'log':
                    log=L.auxiliary(job, root)['log'];log.parent.mkdir(parents=True,exist_ok=True);log.write_bytes(b'Unexplained late log')
                elif mutation in ('failure', 'rehashed_failure'):
                    path = L.directory(job, root)/'failure.json'; value = W.read(path); value['popen_invoked'] = True; W.write(path, value)
                    if mutation == 'rehashed_failure': job['launch_failure_sha256'] = W.sha(path); controller._persist()
                else: L.event(job, root, 'popen-entered')
                reopened = J.WorkflowController(root)
                self.assertFalse(reopened.snapshot()['jobs'][0]['can_recover_launch'])
                with self.assertRaises((OSError, W.ControlError)): self.recover(reopened)
                with self.assertRaises(W.ControlError): W.verify_dispatch_reservations(None, root)

    def test_live_lease_and_peer_or_other_reservation_prevent_recovery(self):
        controller = make_preparation_failure(self.root)
        with W.execution_lease(self.root), self.assertRaises(W.ControlError): self.recover(controller)
        controller.set_peer_busy(lambda: True)
        with self.assertRaises(W.ControlError): self.recover(controller)
        controller.set_peer_busy(lambda: False)
        W.write(self.root/(J.STATE+'/gamma-jobs.json'), {'jobs': [{'status': 'running', 'uncertain': True}]})
        with self.assertRaises(W.ControlError): self.recover(controller)
        self.assertTrue(controller.own_busy())

    def test_preparation_lifetime_holds_shared_lease_until_failure_sealed(self):
        controller = reserved_controller(self.root); job = controller._jobs[0]
        entered = threading.Event(); finish = threading.Event(); original_write = W.write
        def paused_write(path, value, **kwargs):
            if Path(path) == L.auxiliary(job, self.root)['plan']:
                entered.set(); self.assertTrue(finish.wait(5)); raise PermissionError('Paused pre-Popen failure')
            return original_write(path, value, **kwargs)
        with patch.object(W, 'write', side_effect=paused_write), patch.object(J.subprocess, 'Popen') as popen:
            worker = threading.Thread(target=controller._work, args=(job,)); worker.start()
            try:
                self.assertTrue(entered.wait(5)); reopened = J.WorkflowController(self.root)
                with self.assertRaises(W.ControlError): self.recover(reopened)
                with self.assertRaises(W.ControlError):
                    with W.execution_lease(self.root): self.fail('CLI acquired live preparation lease')
            finally: finish.set(); worker.join(5)
            self.assertFalse(worker.is_alive()); popen.assert_not_called()
        self.assertEqual(self.recover(J.WorkflowController(self.root))['status'], 'launch_failed')

    def test_recovery_publication_interruption_reconciles_existing_record(self):
        controller = make_preparation_failure(self.root)
        with patch.object(controller, '_persist', side_effect=PermissionError('Recovery state publication denied')):
            with self.assertRaises(PermissionError): self.recover(controller)
        reopened = J.WorkflowController(self.root)
        self.assertTrue(reopened.snapshot()['jobs'][0]['can_recover_launch'])
        path = L.directory(reopened._jobs[0], self.root)/'recovery.json'; original = path.read_bytes()
        self.assertEqual(self.recover(reopened)['status'], 'launch_failed'); self.assertEqual(path.read_bytes(), original)

    def test_retired_authority_is_rechecked_by_cli_and_busy_state(self):
        controller = make_preparation_failure(self.root); self.recover(controller)
        job = controller._jobs[0]; L.event(job, self.root, 'popen-entered')
        reopened = J.WorkflowController(self.root); self.assertTrue(reopened.own_busy())
        with self.assertRaises(W.ControlError): W.verify_dispatch_reservations(fixture_plan('later'), self.root)
        with self.assertRaises(W.ControlError): self.recover(reopened)

    def test_prelaunch_failed_resume_restores_only_verified_unchanged_seal(self):
        controller = make_preparation_failure(self.root); self.recover(controller)
        job = controller._jobs[0]; job['status'] = 'stopped'; job.pop('launch_recovery_sha256'); job.pop('launch_failure_sha256'); job.pop('launch_intent_sha256')
        output = W.run_path(job['name'], self.root); output.mkdir(parents=True)
        W.write(output/'run.json', {'status': 'stopped', 'stages': {}, 'configuration_sha256': job['plan']['configuration_sha256']})
        W.write(output/'STOP.json', {'requested_utc': 'fixture'})
        controller._persist()
        with patch.object(J.B, 'admit', return_value=job['plan']), patch.object(controller, '_launch', side_effect=controller._view): controller.resume(job['name'])
        # Resume skips plan publication, so fail its managed log opening.
        log = L.auxiliary(job, self.root)['log']; original_open = Path.open
        def open_file(path, *args, **kwargs):
            if path == log: raise PermissionError('Failed Resume log before Popen')
            return original_open(path, *args, **kwargs)
        with patch.object(Path, 'open', open_file), patch.object(J.subprocess, 'Popen') as popen: controller._work(job); popen.assert_not_called()
        before = W.inventory(output)
        with patch.object(J.B, 'inspect', return_value={'status': 'stopped', 'configuration_sha256': job['plan']['configuration_sha256'], 'resume_allowed': False}), self.assertRaises(W.ControlError): self.recover(controller)
        verified = {'status': 'stopped', 'configuration_sha256': job['plan']['configuration_sha256'], 'resume_allowed': True, 'verification': 'sealed_prefix_verified'}
        with patch.object(J.B, 'inspect', return_value=verified): self.assertEqual(self.recover(controller)['status'], 'stopped')
        W.verify_inventory(output, before); W.verify_dispatch_reservations(None, self.root)
        W.write(output/'STOP.json', {'changed': True})
        with self.assertRaises(W.ControlError): W.verify_dispatch_reservations(None, self.root)


class LifecycleCorrections(unittest.TestCase):
    setUp=LaunchRecovery.setUp

    @contextmanager
    def inspection(self,controller):
        """Inject only configuration/physics authority, retaining real inspectors.

        Batch stage-prefix science is synthetic. Journal, checkpoint, completion
        inventory, process/lease and control publication are real in these tests.
        """
        job=controller._jobs[0]
        with ExitStack() as stack:
            if controller._batch_job(job):
                stack.enter_context(patch.object(J.B,'saved_plan',return_value=job['plan']))
                stack.enter_context(patch.object(J.B,'checked_prefix',return_value={
                    'completed_batch_count':0,'completed_primary_count':0,'counts':{},'batch_receipt_chain_sha256':None}))
            elif controller._catalog_job(job):
                backend=J.catalog_backend()
                stack.enter_context(patch.object(backend,'model_contracts',return_value=[job['plan']['resolved']['model_contract']]))
                stack.enter_context(patch.object(backend,'validate_stage',return_value={}))
            else:
                stack.enter_context(patch.object(W,'admit',return_value=job['plan']))
                stack.enter_context(patch.object(W,'saved_plan',return_value=None))
                stack.enter_context(patch.object(W,'validate_stage',return_value={}))
            yield

    def failed_resume(self,kind=J.B.CHECKED_KIND,*,root=None,recover=True):
        root=root or self.root;plan=fixture_plan('resume-fixture');plan['kind']=kind
        if kind==J.CATALOG_KIND:plan['resolved']['model_contract']={'model_id':'AK02','synthetic':True}
        plan['configuration_sha256']=W.digest(plan['resolved'])
        controller=J.WorkflowController(root)
        job={'id':'a'*32,'name':'resume-fixture','status':'stopped','plan':plan,'created_utc':W.utc(),'driver':None,'mode':'run'}
        output=W.run_path(job['name'],root);output.mkdir(parents=True)
        W.write(output/'resolved-config.json',plan);W.write(output/'STOP.json',{'requested_utc':'original-stop'})
        (output/'fixture.bin').write_bytes(b'Original sealed fixture; no science')
        receipt={'kind':kind,'status':'stopped','resolved':plan['resolved'],'configuration_sha256':plan['configuration_sha256'],
                 'stages':{},'resume_allowed':True,'supervisor':{'pid':999991,'identity':'original-ended'}}
        if kind==J.B.CHECKED_KIND:W.write(output/'run.json',receipt)
        else:W.stopped_checkpoint(output,receipt,root)
        controller._jobs=[job];controller._persist()
        backend=J.B if kind==J.B.CHECKED_KIND else J.catalog_backend() if kind==J.CATALOG_KIND else W
        with patch.object(backend,'admit',return_value=plan),patch.object(controller,'_launch',side_effect=controller._view):controller.resume(job['name'])
        log=L.auxiliary(job,root)['log'];original_open=Path.open
        def open_file(path,*args,**kwargs):
            if path==log:raise PermissionError('Synthetic Resume log failure before Popen')
            return original_open(path,*args,**kwargs)
        with patch.object(Path,'open',open_file),patch.object(J.subprocess,'Popen') as popen:
            controller._work(job);popen.assert_not_called()
        if recover:
            with self.inspection(controller):controller.recover_launch(job['name'])
        return controller,output

    def terminal(self,controller,output,*,status='completed'):
        job=controller._jobs[0];receipt=W.read(output/'run.json')
        receipt.update(status=status,supervisor={'pid':999992,'identity':'new-ended'},resume_allowed=False)
        receipt['stages']={stage:{'status':'completed','artifacts':{}} for stage in W.STAGES}
        W.write(output/'run.json',receipt);(output/'STOP.json').unlink(missing_ok=True)
        W.write(output/'COMPLETE.json',{'kind':job['plan']['kind'],'status':status,
                'configuration_sha256':job['plan']['configuration_sha256'],
                'artifacts':W.inventory(output,exclude=('COMPLETE.json','STOP.json'))})
        return receipt

    def test_shared_cli_forbids_preserved_failed_name_case_insensitively(self):
        controller=make_preparation_failure(self.root);name=controller._jobs[0]['name'];controller.recover_launch(name)
        for reused in (name,name.upper()):
            with self.subTest(name=reused),W.execution_lease(self.root),self.assertRaisesRegex(W.ControlError,'reserves this name'):
                W.verify_dispatch_reservations(fixture_plan(reused),self.root)
        with W.execution_lease(self.root):W.verify_dispatch_reservations(fixture_plan('different-name'),self.root)
        self.assertFalse(W.run_path(name,self.root).exists())
        W.run_path(name,self.root).mkdir(parents=True)
        with self.assertRaises(W.ControlError):W.verify_dispatch_reservations(fixture_plan('different-name'),self.root)
        self.assertTrue(J.WorkflowController(self.root).own_busy())

    def test_legacy_and_catalog_recovery_require_original_checkpoint_inventory(self):
        for kind in (W.KIND,J.CATALOG_KIND):
            for mutation in ('artifact','missing_checkpoint','changed_checkpoint'):
                with self.subTest(kind=kind,mutation=mutation):
                    root=self.root/(('legacy' if kind==W.KIND else 'catalog')+'-'+mutation)
                    controller,output=self.failed_resume(kind,root=root,recover=False)
                    run=W.read(output/'run.json');checkpoint=W.safe_path(root,J.STATE+'/checkpoints/'+run['checkpoint_id']+'.json')
                    if mutation=='artifact':(output/'fixture.bin').write_bytes(b'Changed sealed artifact')
                    elif mutation=='missing_checkpoint':checkpoint.unlink()
                    else:value=W.read(checkpoint);value['run_sha256']='f'*64;W.write(checkpoint,value)
                    with self.inspection(controller),self.assertRaises((OSError,W.ControlError)):controller.recover_launch('resume-fixture')
                    self.assertTrue(controller.own_busy());self.assertEqual(W.read(controller._state_path)['jobs'][0]['status'],'dispatch_uncertain')

    def test_verified_cli_terminal_supersedes_stopped_constraint_and_preserves_history(self):
        for kind in (W.KIND,J.CATALOG_KIND):
            with self.subTest(kind=kind):
                root=self.root/('legacy' if kind==W.KIND else 'catalog');controller,output=self.failed_resume(kind,root=root)
                job=controller._jobs[0];history=W.inventory(L.directory(job,root))
                with W.execution_lease(root):W.verify_dispatch_reservations(job['plan'],root)
                self.terminal(controller,output)
                self.assertTrue(J.WorkflowController(root).own_busy())
                self.assertTrue(controller.snapshot()['jobs'][0]['can_verify_saved_execution'])
                with self.inspection(controller),patch.object(W,'process_identity',return_value=None):
                    self.assertEqual(controller.verify(job['name'])['status'],'completed')
                    self.assertFalse(controller.own_busy())
                    W.verify_dispatch_reservations(fixture_plan('later-cli'),root)
                W.verify_inventory(L.directory(job,root),history)
                current=controller._jobs[0];authority=L.verification_path(current,root,current['launch_verified_boundary']['run_sha256'])
                original=authority.read_bytes()
                with self.inspection(controller),patch.object(W,'process_identity',return_value=None):controller.verify(job['name'])
                self.assertEqual(authority.read_bytes(),original)
                later=J.WorkflowController(root,batch_resolver=lambda config,root:fixture_plan('later-gui'))
                with patch.object(W,'process_identity',return_value=None):
                    checked=later.check_batches({'kind':'local_scenario_batch_request_v2','schema_version':2,'selection':fixture_plan('later-gui')['resolved']['selection']})
                    with patch.object(later,'_launch',side_effect=later._view):self.assertEqual(later.start(checked['check_id'])['name'],'later-gui')

    def test_real_cli_batch_resume_can_stop_again_then_be_verified_without_science(self):
        controller,output=self.failed_resume();job=controller._jobs[0];history=W.inventory(L.directory(job,self.root))
        for round_index in (1,2):
            def prefix(plan,directory):
                W.write(directory/'STOP.json',{'requested_utc':'new-stop-'+str(round_index)},fresh=True)
                return {'completed_batch_count':0,'completed_primary_count':0,'counts':{},'batch_receipt_chain_sha256':None}
            with patch.object(J.B,'checked_prefix',side_effect=prefix),patch.object(W,'process_identity',return_value=None),patch.object(J.B,'process_identity',return_value='synthetic-ended-'+str(round_index)):
                result=J.B.execute(job['plan'],root=self.root,resume=True,admitter=lambda plan,root,**kw:plan,
                    executor=lambda *a,**kw:self.fail('Scientific worker requested'))
            self.assertEqual(result['status'],'stopped')
            with self.assertRaises(W.ControlError):W.verify_dispatch_reservations(fixture_plan('later'),self.root)
            with self.inspection(controller),patch.object(W,'process_identity',return_value=None):
                self.assertEqual(controller.verify(job['name'])['status'],'stopped');self.assertFalse(controller.own_busy())
                W.verify_dispatch_reservations(job['plan'],self.root)
            job=controller._jobs[0]
        W.verify_inventory(L.directory(job,self.root),history)
        self.assertEqual(len(list(W.safe_path(self.root,J.STATE+'/workflow-boundaries').glob('*.json'))),2)

    def test_verify_rejects_active_lease_missing_unknown_supervisor_partial_and_bad_completion(self):
        for mutation in ('lease','missing_supervisor','malformed_supervisor','unknown_identity','active_supervisor','unknown_lifetime','partial','bad_complete'):
            with self.subTest(mutation=mutation):
                root=self.root/mutation;controller,output=self.failed_resume(W.KIND,root=root);job=controller._jobs[0]
                receipt=self.terminal(controller,output)
                if mutation=='missing_supervisor':receipt.pop('supervisor');W.write(output/'run.json',receipt)
                elif mutation=='malformed_supervisor':receipt['supervisor']={'pid':True,'identity':'new-ended'};W.write(output/'run.json',receipt)
                elif mutation=='unknown_identity':receipt['supervisor']['identity']='unknown';W.write(output/'run.json',receipt)
                elif mutation=='partial':receipt['status']='running';W.write(output/'run.json',receipt)
                elif mutation=='bad_complete':(output/'fixture.bin').write_bytes(b'Unverified changed result')
                # For supervisor-specific tests, keep completion inventory valid so
                # refusal must come from lifecycle identity, not stale hashes.
                if mutation in ('missing_supervisor','malformed_supervisor','unknown_identity'):
                    complete=W.read(output/'COMPLETE.json');complete['artifacts']=W.inventory(output,exclude=('COMPLETE.json','STOP.json'));W.write(output/'COMPLETE.json',complete)
                lifetime='new-ended' if mutation=='active_supervisor' else 'unknown' if mutation=='unknown_lifetime' else None
                with ExitStack() as stack:
                    stack.enter_context(self.inspection(controller));stack.enter_context(patch.object(W,'process_identity',return_value=lifetime))
                    if mutation=='lease':stack.enter_context(W.execution_lease(root))
                    with self.assertRaises((OSError,W.ControlError)):controller.verify(job['name'])
                self.assertNotIn('launch_verified_boundary',W.read(controller._state_path)['jobs'][0])
                self.assertTrue(J.WorkflowController(root).own_busy())

    def test_new_nonbatch_stopped_seal_and_interrupted_verification_publication(self):
        for kind in (W.KIND,J.CATALOG_KIND):
            with self.subTest(kind=kind):
                root=self.root/('legacy' if kind==W.KIND else 'catalog');controller,output=self.failed_resume(kind,root=root);job=controller._jobs[0]
                receipt=W.read(output/'run.json');receipt['supervisor']={'pid':999992,'identity':'new-ended'}
                W.write(output/'STOP.json',{'requested_utc':'new-stop'});W.stopped_checkpoint(output,receipt,root)
                history=W.inventory(L.directory(job,root))
                with self.inspection(controller),patch.object(W,'process_identity',return_value=None),patch.object(controller,'_persist',side_effect=PermissionError('Control publication interrupted')):
                    with self.assertRaises(PermissionError):controller.verify(job['name'])
                reopened=J.WorkflowController(root)
                with self.inspection(reopened),patch.object(W,'process_identity',return_value=None):
                    self.assertEqual(reopened.verify(job['name'])['status'],'stopped');self.assertFalse(reopened.own_busy())
                    W.verify_dispatch_reservations(job['plan'],root)
                W.verify_inventory(L.directory(job,root),history)
                (output/'fixture.bin').write_bytes(b'Broken new stopped seal')
                with self.inspection(reopened),self.assertRaises(W.ControlError):reopened.verify(job['name'])

    def test_verified_authority_stamp_changes_are_blocking(self):
        controller,output=self.failed_resume(W.KIND);self.terminal(controller,output)
        with self.inspection(controller),patch.object(W,'process_identity',return_value=None):controller.verify('resume-fixture')
        job=controller._jobs[0];path=L.verification_path(job,self.root,job['launch_verified_boundary']['run_sha256'])
        value=W.read(path);value['status']='stopped';W.write(path,value)
        with self.assertRaises(W.ControlError):W.verify_dispatch_reservations(fixture_plan('later'),self.root)
        self.assertTrue(J.WorkflowController(self.root).own_busy())

    def test_receipt_change_during_independent_inspection_cannot_gain_authority(self):
        controller,output=self.failed_resume(W.KIND);self.terminal(controller,output)
        inspect=controller._inspect
        def changed(job):
            verified=inspect(job)
            run=W.read(output/'run.json');run['finished_utc']='Unexpected writer during verification';W.write(output/'run.json',run)
            return verified
        with self.inspection(controller),patch.object(W,'process_identity',return_value=None),patch.object(controller,'_inspect',side_effect=changed),self.assertRaisesRegex(W.ControlError,'changed during'):
            controller.verify('resume-fixture')
        self.assertNotIn('launch_verified_boundary',W.read(controller._state_path)['jobs'][0])


if __name__ == '__main__': unittest.main()
