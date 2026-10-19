"""Protected saved-GeGI UI adapter; fixtures only, no physical calculations."""
import http.client
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock,patch

import gegi_saved_control as G
import local_ui as U
import local_ui_workflow_jobs as J
import scenario_workflow as W


class Adapter(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='gegi-saved-control-',dir=W.ROOT/'.local')
        self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.campaign=self.root/'.local/dataset/campaign';self.campaign.mkdir(parents=True)
        (self.campaign/'chunks').mkdir()
        W.write(self.campaign/'COMPLETE.json',{'kind':'gegi_campaign_plan_v1','status':'completed','chunks':{'0':'f'*64}})
        self.calibration=self.campaign.parent/'independent-templates';self.calibration.mkdir()
        W.write(self.calibration/'identity.json',{});W.write(self.calibration/'depth-calibration.json',{})
        self.workflow=J.WorkflowController(self.root);self.started=threading.Event();self.finish=threading.Event()
        self.addCleanup(self.finish.set)
        self.calls=[]
        def runner(campaign,calibration,output,*,resume):
            self.calls.append((campaign,calibration,output,resume));output.mkdir(parents=True,exist_ok=True)
            W.write(output/'progress.json',{'status':'running_saved_reconstruction','chunks':1,'counts':{'pulse_groups':2}})
            self.started.set()
            if not self.finish.wait(3):raise AssertionError('Test worker was not released')
            status='stopped_saved_reconstruction' if (output/'stop.request').exists() else 'completed_conditional_reconstruction'
            return {'status':status}
        self.control=G.SavedGeGIControl(self.workflow,runner=runner)
        admission=patch.object(G.A,'campaign',side_effect=lambda campaign,calibration,**kwargs:
                               None if calibration is None else {'status':'fixture_compatible'})
        self.admission=admission.start();self.addCleanup(admission.stop)
        inventory=self.control.options();self.cid=inventory['campaigns'][0]['id'];self.tid=inventory['calibrations'][0]['id']

    def wait_finished(self):
        self.finish.set()
        deadline=time.monotonic()+3
        while self.workflow._active is not None and time.monotonic()<deadline:time.sleep(.01)
        self.assertIsNone(self.workflow._active)

    def test_discovery_only_offers_completed_sealed_format_and_saved_templates(self):
        before=W.sha(self.campaign/'COMPLETE.json')
        value=self.control.options();self.assertEqual(len(value['campaigns']),1);self.assertEqual(len(value['calibrations']),1)
        self.assertEqual(value['new_science_calls'],0);self.assertEqual(before,W.sha(self.campaign/'COMPLETE.json'))
        self.assertFalse((self.root/G.STATE).exists())
        W.write(self.campaign/'COMPLETE.json',{'kind':'standalone_control_run','status':'completed','chunks':{'0':'f'*64}})
        self.assertEqual(self.control.options()['campaigns'],[])

    def test_closed_inputs_and_unused_derivative_name_are_required(self):
        for campaign,calibration,name in (('../private','', 'new'),(self.cid,'../templates','new'),(self.cid,'','../new'),(self.cid,'','CON')):
            with self.assertRaises(W.ControlError):self.control.start(campaign,calibration,name)
        self.assertEqual(self.calls,[]);self.assertIsNone(self.workflow._active)
        path=self.root/G.OUTPUTS/'existing';path.mkdir(parents=True)
        with self.assertRaises(W.ControlError):self.control.start(self.cid,'','existing')

    def test_one_shared_worker_reads_selected_inputs_and_stops_at_chunk_boundary(self):
        initial=W.sha(self.campaign/'COMPLETE.json')
        reply=self.control.start(self.cid,self.tid,'derived');self.assertEqual(reply['status'],'running')
        self.assertTrue(self.started.wait(2));self.assertTrue(self.workflow.own_busy())
        self.assertEqual(self.calls[0],(self.campaign,self.calibration,self.root/G.OUTPUTS/'derived',False))
        self.admission.assert_called_with(self.campaign,self.calibration,root=self.root)
        with self.assertRaises(W.ControlError):self.control.start(self.cid,'','competing')
        state=self.control.state('derived');self.assertEqual(state['progress']['counts']['pulse_groups'],2)
        self.assertEqual(self.control.stop('derived')['status'],'stop_requested')
        self.assertTrue((self.root/G.OUTPUTS/'derived/stop.request').is_file())
        self.wait_finished();self.assertEqual(self.control.state('derived')['status'],'stopped_saved_reconstruction')
        self.assertEqual(initial,W.sha(self.campaign/'COMPLETE.json'))
        with self.assertRaises(W.ControlError):self.control.start(self.cid,'','derived',resume=True)
        restarted=G.SavedGeGIControl(self.workflow,runner=lambda *a,**k:{'status':'completed_conditional_reconstruction'})
        resumed=restarted.start(self.cid,self.tid,'derived',resume=True);self.assertEqual(resumed['status'],'running')
        self.wait_finished();self.assertEqual(restarted.state('derived')['status'],'completed_conditional_reconstruction')

    def test_no_bank_is_explicit_and_only_named_derivative_summaries_are_read(self):
        self.control.start(self.cid,'','no-bank');self.assertTrue(self.started.wait(2));self.wait_finished()
        self.assertIsNone(self.calls[0][1])
        self.assertEqual(json.loads(self.control.artifact('no-bank','progress.json'))['chunks'],1)
        for name,file in (('unknown','progress.json'),('no-bank','../events.sqlite'),('no-bank','chunks/000.jsonl.gz')):
            with self.assertRaises(W.ControlError):self.control.artifact(name,file)

    def test_bound_completion_outranks_interrupted_status_and_prevents_replay(self):
        self.control.start(self.cid,'','sealed');self.assertTrue(self.started.wait(2));self.wait_finished()
        directory=self.root/G.OUTPUTS/'sealed'
        W.write(directory/'identity.json',{'campaign_complete_sha256':W.sha(self.campaign/'COMPLETE.json')})
        W.write(directory/'summary.json',{'status':'completed_conditional_reconstruction','counts':{'pulse_groups':2}})
        W.write(directory/'COMPLETE.json',{'kind':'gegi_saved_reconstruction_v3','status':'completed_conditional_reconstruction',
            'summary_sha256':W.sha(directory/'summary.json'),'identity_sha256':W.sha(directory/'identity.json')})
        self.control.jobs['sealed']['status']='interrupted'
        self.assertEqual(self.control.state('sealed')['status'],'completed_conditional_reconstruction')
        with self.assertRaises(W.ControlError):self.control.start(self.cid,'','sealed',resume=True)
        self.assertEqual(len(self.calls),1)
        (directory/'summary.json').write_bytes(b'{}')
        with self.assertRaises(W.ControlError):self.control.state('sealed')


class Protocol(unittest.TestCase):
    def setUp(self):
        self.workflow=Mock();self.server=U.Server(0,Mock(),token='saved-test',workflow_controller=self.workflow)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.addCleanup(self.close)
    def close(self):self.server.shutdown();self.server.server_close();self.thread.join()
    def request(self,path,body=None,headers=None):
        values={'Host':'127.0.0.1:'+str(self.server.server_port),'X-Control-Token':self.server.token}
        if body is not None:values.update({'Content-Type':'application/json','Origin':self.server.origin})
        for key,value in (headers or {}).items():
            if value is None:values.pop(key,None)
            else:values[key]=value
        c=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
        c.request('POST' if body is not None else 'GET',path,json.dumps(body) if body is not None else None,values)
        response=c.getresponse();result=response.status,response.read();c.close();return result

    def test_inventory_and_state_use_exact_authenticated_gets_without_dispatch(self):
        self.workflow.gegi_saved_options.return_value={'kind':'gegi_saved_options_v1','campaigns':[]}
        self.workflow.gegi_saved_state.return_value={'name':'derived','status':'completed_conditional_reconstruction'}
        self.assertEqual(self.request('/api/workflow/gegi-saved/options')[0],200)
        self.assertEqual(self.request('/api/workflow/gegi-saved/state?name=derived')[0],200)
        self.workflow.gegi_saved_state.assert_called_once_with('derived')
        for suffix in ('?name=derived&name=other','?name=derived&file=secret','?name=derived&ignored','?name=../private','?name=CON','#fragment'):
            self.assertEqual(self.request('/api/workflow/gegi-saved/state'+suffix)[0],400,suffix)
        self.assertEqual(self.request('/api/workflow/gegi-saved/options?extra=1')[0],400)
        for headers in ({'X-Control-Token':None},{'Origin':'https://foreign.invalid'},{'Sec-Fetch-Site':'cross-site'}):
            self.assertEqual(self.request('/api/workflow/gegi-saved/options',headers=headers)[0],403)
        self.workflow.reprocess_gegi_saved.assert_not_called();self.workflow.start.assert_not_called()

    def test_reprocess_stop_and_file_routes_are_closed_and_session_protected(self):
        body={'campaign_id':'a'*64,'calibration_id':'','name':'derived','resume':False}
        self.workflow.reprocess_gegi_saved.return_value={'status':'running'}
        self.workflow.stop_gegi_saved.return_value={'status':'stop_requested'}
        self.workflow.gegi_saved_artifact.return_value=b'{"groups":2}'
        self.assertEqual(self.request('/api/workflow/gegi-saved/reprocess',body)[0],200)
        self.workflow.reprocess_gegi_saved.assert_called_once_with(**body)
        for wrong in ({**body,'output':'C:/private'},dict(body,resume='false'),dict(body,name='../private')):
            self.assertEqual(self.request('/api/workflow/gegi-saved/reprocess',wrong)[0],400)
        self.assertEqual(self.request('/api/workflow/gegi-saved/reprocess',body,{'Origin':'https://foreign.invalid'})[0],403)
        self.assertEqual(self.request('/api/workflow/gegi-saved/stop',{'name':'derived'})[0],200)
        self.assertEqual(self.request('/api/workflow/gegi-saved/file?name=derived&file=summary.json'),(200,b'{"groups":2}'))
        self.workflow.gegi_saved_artifact.assert_called_once_with('derived','summary.json')
        self.assertEqual(self.request('/api/workflow/gegi-saved/file?name=derived&file=summary.json',headers={'X-Control-Token':None})[0],403)
        self.workflow.start.assert_not_called();self.workflow.check.assert_not_called()


if __name__=='__main__':unittest.main()
