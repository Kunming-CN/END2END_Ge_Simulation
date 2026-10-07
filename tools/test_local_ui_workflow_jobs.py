"""Owned plan/start/reopen tests. Every scientific launch is mocked."""
import copy
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import local_ui_workflow_jobs as J
import workflow_recovery as R
import scenario_workflow as W


class Jobs(unittest.TestCase):
    def setUp(self):
        base=W.ROOT/'.local/product-delivery-v1/implementation-tests';base.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=base);self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.config={'name':'owned-fixture','detector':'AK02','source':W.GAMMA,'primary_count':20}
        self.plan={'kind':W.KIND,'status':'checked_configuration','science_calls':0,'resolved':{'selection':self.config},'configuration_sha256':'original'}
        self.resolver=lambda config,root:copy.deepcopy(self.plan)
        self.controller=J.WorkflowController(self.root,resolver=self.resolver,launcher=lambda *a:self.fail('Unrequested launch'))


    def catalog_plan(self):
        plan=copy.deepcopy(self.plan);plan['kind']=J.CATALOG_KIND
        plan['resolved']['selection']['detector']='AK01'
        return plan

    def test_catalog_check_is_read_only_and_reserves_versioned_authority(self):
        plan=self.catalog_plan();self.controller._catalog_resolver=lambda config,root:copy.deepcopy(plan)
        checked=self.controller.check_catalog(plan['resolved']['selection'])
        self.assertEqual(checked['kind'],J.CATALOG_KIND);self.assertFalse(W.run_path('owned-fixture',self.root).exists())
        with patch.object(self.controller,'_launch',side_effect=self.controller._view):
            job=self.controller.start(checked['check_id'])
        self.assertEqual(job['workflow_kind'],J.CATALOG_KIND)
        self.assertFalse(job['can_inspect_failure']);self.assertFalse(job['can_continue_prefix'])
        reopened=J.WorkflowController(self.root,resolver=self.resolver)
        self.assertEqual(reopened.snapshot()['jobs'][0]['workflow_kind'],J.CATALOG_KIND)
        self.assertTrue(reopened.own_busy())

    def test_catalog_changed_plan_and_preview_cannot_start(self):
        plan=self.catalog_plan();self.controller._catalog_resolver=lambda config,root:copy.deepcopy(plan)
        checked=self.controller.check_catalog(plan['resolved']['selection'])
        plan['configuration_sha256']='changed'
        with self.assertRaisesRegex(W.ControlError,'changed after Check'):self.controller.start(checked['check_id'])
        self.assertEqual(self.controller._jobs,[])
        self.controller._checks['preview']={'kind':'local_scenario_batch_preview_v2'}
        with self.assertRaisesRegex(W.ControlError,'preview'):self.controller.start('preview')
        self.assertFalse(self.controller._state_path.exists())

    def test_catalog_route_uses_catalog_cli_without_legacy_failure_inspection(self):
        plan=self.catalog_plan();self.controller._catalog_resolver=lambda config,root:copy.deepcopy(plan)
        with patch.object(self.controller,'_launch',return_value={}):
            checked=self.controller.check_catalog(plan['resolved']['selection']);self.controller.start(checked['check_id'])
        job=self.controller._jobs[0];calls=[]
        def launch(argv,log,on_spawn):
            calls.append(argv)
            directory=W.run_path(job['name'],self.root);directory.mkdir(parents=True)
            W.write(directory/'run.json',{'status':'stopped','stages':{}},fresh=True)
            return 0
        self.controller._launcher=launch
        with patch.object(W,'inspect',side_effect=AssertionError('Legacy inspector called')):
            self.controller._work(job)
        self.assertIn('run-catalog',calls[0]);self.assertIn('--plan',calls[0])
        self.assertEqual(job['status'],'stopped')
        with self.assertRaises(W.ControlError):self.controller.inspect_failure(job['name'])

    def test_new_exporter_readiness_does_not_block_original_setup(self):
        for relative in ('transport/cryostat-source.json','simulation/Manifest.toml'):
            path=self.root/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'fixture')
        backend=SimpleNamespace(EXPORTER_REF='.local/new-exporter',BUILD_REF='.local/new-build.json')
        portable=SimpleNamespace(file_readiness=lambda root:{'available':True})
        with patch.dict('sys.modules',{'scenario_source_portable':portable}),patch.object(W,'runtime_identity',return_value={}),patch.object(W,'source_pins',return_value={}),patch.object(W,'catalog',return_value={'setup_guide':'fixture'}),patch.object(J,'catalog_backend',return_value=backend):
            reply=self.controller.setup()
            self.assertTrue(reply['ready_for_config_check']);self.assertFalse(reply['catalog_models_file_ready']);self.assertEqual(reply['science_calls'],0)
            for relative in (backend.EXPORTER_REF,backend.BUILD_REF):
                path=self.root/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'fixture')
            self.assertTrue(self.controller.setup()['catalog_models_file_ready'])

    def test_check_does_not_launch_or_create_run(self):
        result=self.controller.check(self.config)
        self.assertTrue(result['check_id']);self.assertFalse((self.root/W.BASE).exists())

    def test_unknown_check_identity_cannot_start(self):
        with self.assertRaises(W.ControlError):self.controller.start('unknown')

    def test_changed_resolver_refuses_start(self):
        checked=self.controller.check(self.config);self.plan['configuration_sha256']='changed'
        with self.assertRaises(W.ControlError):self.controller.start(checked['check_id'])

    def test_exact_plan_reserved_and_double_launch_refused(self):
        checked=self.controller.check(self.config)
        with patch.object(self.controller,'_launch',side_effect=lambda job:self.controller._view(job)):
            job=self.controller.start(checked['check_id']);self.assertEqual(job['name'],'owned-fixture')
            with self.assertRaises(W.ControlError):self.controller.start(checked['check_id'])

    def test_reopen_keeps_uncertain_dispatch_blocking(self):
        checked=self.controller.check(self.config)
        with patch.object(self.controller,'_launch',return_value={}):self.controller.start(checked['check_id'])
        reopened=J.WorkflowController(self.root,resolver=self.resolver)
        self.assertTrue(reopened.own_busy());self.assertEqual(reopened.snapshot()['jobs'][0]['status'],'dispatch_uncertain')
        with self.assertRaises(W.ControlError):reopened.check(self.config)

    def test_peer_activity_blocks_new_check(self):
        self.controller.set_peer_busy(lambda:True)
        with self.assertRaises(W.ControlError):self.controller.check(self.config)

    def test_stopped_only_resume_gate(self):
        with self.assertRaises(W.ControlError):self.controller.resume('unknown')

    def test_stop_before_committed_receipt_never_creates_output(self):
        checked=self.controller.check(self.config)
        with patch.object(self.controller,'_launch',return_value={}):self.controller.start(checked['check_id'])
        self.controller._jobs[0]['status']='running'
        with self.assertRaises(W.ControlError):self.controller.stop('owned-fixture')
        self.assertFalse(W.run_path('owned-fixture',self.root).exists())

    def test_malformed_saved_process_identity_refused(self):
        checked=self.controller.check(self.config)
        with patch.object(self.controller,'_launch',return_value={}):self.controller.start(checked['check_id'])
        self.controller._jobs[0]['driver']={'pid':True,'identity':'unknown'};self.controller._persist()
        with self.assertRaises(W.ControlError):J.WorkflowController(self.root,resolver=self.resolver)

    def test_verify_and_busy_keep_unknown_creation_identity_blocked(self):
        checked=self.controller.check(self.config)
        with patch.object(self.controller,'_launch',return_value={}):self.controller.start(checked['check_id'])
        job=self.controller._jobs[0];job['driver']={'pid':999998,'identity':'saved-creation'}
        receipt={'status':'completed','configuration_sha256':'original'}
        for identity in ('unknown','saved-creation'):
            with self.subTest(identity=identity),patch.object(W,'inspect',return_value=receipt),patch.object(W,'process_identity',return_value=identity),self.assertRaises(W.ControlError):self.controller.verify(job['name'])
        with patch.object(W,'inspect',return_value=receipt),patch.object(W,'process_identity',return_value=None):self.controller.verify(job['name']);self.assertFalse(self.controller.own_busy())
        with patch.object(W,'process_identity',return_value='unknown'):self.assertTrue(self.controller.own_busy())

    def test_common_lease_blocks_retained_route_reservation(self):
        with W.execution_lease(self.root):
            self.assertTrue(self.controller.own_busy())
            with self.assertRaises(W.ControlError):
                with self.controller.scientific_entry():self.fail('Legacy dispatch admitted under CLI lease')

    def test_retained_durable_reservation_blocks_cli(self):
        with self.controller.scientific_entry():
            W.write(self.root/'.local/local-control-v1/gamma-jobs.json',{'jobs':[{'status':'running','uncertain':True}]},fresh=True)
        with self.assertRaises(W.ControlError):W.verify_dispatch_reservations(None,self.root)

    def test_competing_requests_commit_only_one_reservation(self):
        checks=[self.controller.check(self.config)['check_id'] for _ in range(2)]
        barrier=threading.Barrier(2);outcomes=[]
        def start(identity):
            barrier.wait()
            try:self.controller.start(identity);outcomes.append('reserved')
            except W.ControlError:outcomes.append('refused')
        with patch.object(self.controller,'_launch',return_value={}):
            workers=[threading.Thread(target=start,args=(identity,)) for identity in checks]
            for worker in workers:worker.start()
            for worker in workers:worker.join(5);self.assertFalse(worker.is_alive())
        self.assertCountEqual(outcomes,['reserved','refused']);self.assertEqual(len(self.controller._jobs),1)

    def test_prefix_continuation_reserves_under_shared_lease_once(self):
        self._prefix_reservation(R.PARENT,R.PARENT_DISPATCH)

    def test_km_prefix_continuation_uses_same_closed_reservation(self):
        self._prefix_reservation(R.KM_PARENT,R.KM_DISPATCH)

    def _prefix_reservation(self,name,dispatch):
        parent={'id':dispatch,'name':name,'plan':copy.deepcopy(self.plan),'driver':None,'status':'dispatch_uncertain','created_utc':'synthetic','mode':'run'}
        parent['plan']['resolved']['selection']['name']=name;self.controller._jobs=[parent];self.controller._persist()
        self.assertTrue(self.controller._view(parent)['can_continue_prefix'])
        def resolve(config,root):
            value=copy.deepcopy(parent['plan']);value['resolved']['selection']=config;return value
        self.controller._resolver=resolve
        def inspection(*args):
            self.assertTrue(W.lease_busy(self.root));self.assertEqual(parent['status'],'dispatch_uncertain');return {}
        with patch.object(R,'inspect_parent',side_effect=inspection),patch.object(R,'compatible',return_value=[]),patch.object(R,'release',return_value='a'*64),patch.object(self.controller,'_launch',side_effect=self.controller._view):
            result=self.controller.continue_prefix(name,'prefix-derived')
            self.assertEqual(result['name'],'prefix-derived');self.assertEqual(parent['status'],'verified_transport')
            self.assertEqual(self.controller._jobs[1]['mode'],'continue')
            with self.assertRaises(W.ControlError):self.controller.continue_prefix(name,'prefix-derived-again')
        saved=W.read(self.controller._state_path)['jobs'];self.assertEqual(len(saved),2);self.assertEqual(saved[1]['status'],'dispatch_uncertain')

    def test_cli_lease_blocks_continuation_before_inspection(self):
        parent={'id':R.PARENT_DISPATCH,'name':R.PARENT,'plan':self.plan,'driver':None,'status':'dispatch_uncertain'}
        self.controller._jobs=[parent]
        with patch.object(R,'inspect_parent') as inspection,W.execution_lease(self.root),self.assertRaises(W.ControlError):self.controller.continue_prefix(R.PARENT,'prefix-derived')
        inspection.assert_not_called();self.assertEqual(parent['status'],'dispatch_uncertain')


if __name__=='__main__':unittest.main()
