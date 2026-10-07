"""Synthetic failure inspection tests; OS inventories and workers are mocked."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import workflow_inspection as I
import scenario_workflow as W


class Inspection(unittest.TestCase):
    def setUp(self):
        base=W.ROOT/'.local/product-delivery-v1/implementation-tests';base.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=base);self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.directory=W.run_path('synthetic-denial',self.root);self.directory.mkdir(parents=True)
        self.resolved={'selection':{'name':'synthetic-denial','source':W.GAMMA,'detector':'AK02','threads':2,'primary_count':20,'seed':26092631}}
        self.job={'id':'a'*32,'name':'synthetic-denial','status':'dispatch_uncertain','driver':{'pid':999991,'identity':'old-driver'},
                  'plan':{'configuration_sha256':W.digest(self.resolved),'resolved':self.resolved}}
        self.receipt={'kind':W.KIND,'status':'failed','resolved':self.resolved,'configuration_sha256':W.digest(self.resolved),
                      'stages':{'geometry':{'status':'command_exited','exit_code':4294967295,'pid':999992,'process_identity':'old-stage',
                                           'arguments':W.stage_commands(self.directory,self.resolved,self.root,{'JULIA_EXE':'not-dispatched'})['geometry']}}}
        W.write(self.directory/'run.json',self.receipt,fresh=True);W.write(self.directory/'resolved-config.json',self.job['plan'],fresh=True)
        W.write(self.directory/'electronics/profile.json',{'synthetic_fixture':True},fresh=True)
        (self.directory/'geometry.log').write_bytes('Access is denied.\r\nError code: Wsl/Service/E_ACCESSDENIED\r\n'.encode('utf-16-le'))
        I.capture(self.job,self.root);self.assertIn('failure_authority_sha256',self.job)
        self.quiet={'windows_succeeded':True,'linux_succeeded':True,'relevant_windows_workers':[],'relevant_linux_workers':[]}

    def retire(self,probe=None):
        with patch.object(W,'process_identity',return_value=None):
            stamp=I.inspect_failure(self.job,self.root,probe=probe or (lambda root:self.quiet))
        self.job.update(status='inspected_failure',inspection_sha256=stamp)
        W.write(self.root/(I.STATE+'/workflow-jobs.json'),{'kind':'local_workflow_jobs_v1','jobs':[self.job]})
        return stamp

    def test_generic_decay_python_worker_is_kept_in_science_inventory(self):
        for command in ('python -B ./decay_source.py prepare --request run.json',
                        '/existing/python /project/transport/decay_source.py run --directory run',
                        'PYTHON DECAY_SOURCE.PY extract --directory run'):
            with self.subTest(command=command):self.assertIsNotNone(I.SCIENCE.search(command))
        for command in ('notepad.exe notes.txt','python readme_analysis.py'):
            with self.subTest(command=command):self.assertIsNone(I.SCIENCE.search(command))

    def test_recognized_ended_failure_preserves_every_failed_byte(self):
        before=W.inventory(self.directory);self.retire();self.assertEqual(before,W.inventory(self.directory))
        with patch.object(W,'process_identity',return_value=None):self.assertTrue(I.verified_retirement(self.directory,self.root))
        self.assertTrue(self.directory.exists())

    def test_changed_or_rehashed_failure_never_releases(self):
        r=copy.deepcopy(self.receipt);r['resolved']={'selection':{'name':'different'}};W.write(self.directory/'run.json',r)
        with patch.object(W,'process_identity',return_value=None),self.assertRaises(W.ControlError):I.inspect_failure(self.job,self.root,probe=lambda root:self.quiet)
        self.assertFalse((self.root/(I.STATE+'/inspected-failures/synthetic-denial.json')).exists())

    def test_changed_log_never_releases(self):
        (self.directory/'geometry.log').write_bytes('Error code: Wsl/Service/E_ACCESSDENIED\nchanged'.encode('utf-16-le'))
        with self.assertRaises(W.ControlError):I.inspect_failure(self.job,self.root,probe=lambda root:self.quiet)

    def test_unknown_or_matching_driver_remains_blocked(self):
        for identity in ('unknown','old-driver','old-stage'):
            with self.subTest(identity=identity),patch.object(W,'process_identity',return_value=identity),self.assertRaises(W.ControlError):I.inspect_failure(self.job,self.root,probe=lambda root:self.quiet)

    def test_failed_inventory_or_worker_remains_blocked(self):
        for field,value in [('windows_succeeded',False),('linux_succeeded',False),('relevant_linux_workers',[{'pid':12}]),('relevant_windows_workers',[{'pid':34}])]:
            q=dict(self.quiet);q[field]=value
            with self.subTest(field=field),patch.object(W,'process_identity',return_value=None),self.assertRaises(W.ControlError):I.inspect_failure(self.job,self.root,probe=lambda root:q)

    def test_later_or_unrecognized_failure_remains_blocked(self):
        self.receipt['stages']['radiation']={'status':'failed'};W.write(self.directory/'run.json',self.receipt)
        with self.assertRaises(W.ControlError):I.recognized(self.directory)

    def test_retirement_changed_after_inspection_remains_blocked(self):
        self.retire();(self.directory/'geometry.log').write_bytes(b'changed')
        with patch.object(W,'process_identity',return_value=None),self.assertRaises((W.ControlError,UnicodeError)):I.verified_retirement(self.directory,self.root)

    def test_inventory_privacy_and_failed_system_queries(self):
        class Result:
            def __init__(self,body,code=0):self.stdout=body;self.returncode=code
        windows=json.dumps([{'ProcessId':42,'ParentProcessId':1,'CreationDate':'old','Name':'other.exe','CommandLine':'secret-unrelated-token'}]).encode()
        replies=[Result(windows),Result(b' PID PPID COMMAND\n 1 0 /sbin/init\n')]
        q=I.inventories(self.root,runner=lambda *a,**k:replies.pop(0))
        self.assertNotIn('secret',json.dumps(q));self.assertTrue(q['windows_succeeded'])
        with self.assertRaises(W.ControlError):I.inventories(self.root,runner=lambda *a,**k:Result(b'',1))
        windows=json.dumps([{'ProcessId':42,'ParentProcessId':1,'CreationDate':'old','Name':'julia.exe','CommandLine':'julia.exe worker'}]).encode()
        replies=[Result(windows),Result(b' PID PPID COMMAND\n 1 0 /sbin/init\n')]
        with self.assertRaises(W.ControlError):I.inventories(self.root,runner=lambda *a,**k:replies.pop(0))


if __name__=='__main__':unittest.main()
