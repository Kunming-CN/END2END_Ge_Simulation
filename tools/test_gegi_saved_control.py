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

    def standalone_fixture(self,*,owned=True):
        from test_gegi_standalone_reconstruction import Standalone
        run=self.root/W.BASE/'owned-gegi';response=run/'response'
        payload,receipt,request=Standalone().native_fixture(response)
        W.write(run/'gegi-request.json',request)
        receipt['request_sha256']=W.sha(run/'gegi-request.json');W.write(response/'run.json',receipt)
        W.write(run/'COMPLETE.json',{'kind':'local_gegi_workflow_v1','status':payload['status'],
            'configuration_sha256':payload['configuration_sha256'],
            'artifacts':{ref:{'sha256':W.sha(run/ref),'bytes':(run/ref).stat().st_size}
                         for ref in ('response/results.json','response/run.json','gegi-request.json')}})
        if owned:
            self.workflow._jobs.append({'name':run.name,'status':payload['status'],
                'plan':{'kind':'local_gegi_workflow_v1','configuration_sha256':payload['configuration_sha256']}})
        return run,payload

    def standalone_verifier(self):
        return patch('gegi_workflow.inspect',return_value={'verification':'terminal_artifacts_verified',
                                                        'configuration_sha256':'a'*64})

    def test_owned_standalone_discovery_is_lightweight_and_excludes_unowned_runs(self):
        run,_=self.standalone_fixture(owned=False)
        self.assertFalse(any(c.get('input_kind')=='standalone' for c in self.control.options()['campaigns']))
        self.workflow._jobs.append({'name':run.name,'status':'completed_with_native_failures',
                                   'plan':{'kind':'local_gegi_workflow_v1','configuration_sha256':'a'*64}})
        with patch.object(W,'sha',side_effect=AssertionError('Discovery must not hash saved signals/results')):
            choices=self.control.options()['campaigns']
        selected=next(c for c in choices if c.get('input_kind')=='standalone')
        self.assertEqual(selected['source_run_name'],run.name)
        self.assertFalse(selected['resume_supported']);self.assertFalse(selected['stop_supported'])
        self.assertEqual(selected['counts']['initial_primaries'],100)

    def test_real_postprocess_owned_fixture_preserves_signals_ids_nulls_and_result_api(self):
        run,original=self.standalone_fixture();before=W.inventory(run)
        choice=next(c for c in self.control.options()['campaigns'] if c.get('input_kind')=='standalone')
        # The fixture supplies tiny real signed CSVs and a native-failure record.
        # Only the unrelated full workflow-stage inspector is replaced; the real
        # postprocess seal/event/CSV/wiring checks and reconstruction all execute.
        with self.standalone_verifier() as verified, \
             patch('gegi_response.subprocess.run',side_effect=AssertionError('No physics or subprocess allowed')):
            job=self.control.start(choice['id'],'','standalone-derived')
            self.assertFalse(job['resume_supported']);self.assertFalse(job['stop_supported'])
            self.wait_finished()
            state=self.control.state(job['name'])
            self.assertEqual(state['status'],'completed_conditional_reconstruction',state)
            self.assertEqual(state['files'],['identity.json','results.json','COMPLETE.json'])
            self.assertEqual(state['summary']['counts']['initial_primaries'],100)
            self.assertEqual(state['summary']['counts']['zero_deposit_primaries'],98)
            self.assertEqual(state['summary']['counts']['nonzero_primaries'],2)
            self.assertNotIn('pulse_groups',state['summary']['counts'])
            result=self.control.results(job['name'])
            self.assertEqual(result['name'],run.name);self.assertEqual(result['saved_derivative_name'],job['name'])
            self.assertEqual(result['counts'],original['counts'])
            self.assertEqual([e['event_id'] for e in result['events']],[17,49])
            self.assertEqual(result['events'][0]['channels'],original['events'][0]['channels'])
            self.assertEqual(result['events'][0]['signals_ref'],'events/17-signals.csv')
            self.assertIsNone(result['events'][1]['channels']);self.assertIsNone(result['events'][1]['signals_ref'])
            self.assertIsNone(result['imaging']['values']);self.assertEqual(result['imaging']['validated_recovered_groups'],0)
            raw=json.loads(self.control.artifact(job['name'],'results.json'))
            self.assertEqual(raw['events'],result['events'])
            self.assertEqual(verified.call_args.args,(run.name,self.root))
            for action in (lambda:self.control.stop(job['name']),
                           lambda:self.control.start(choice['id'],'',job['name'],resume=True)):
                with self.assertRaisesRegex(W.ControlError,'does not support|no stop boundary'):action()
        self.assertEqual(before,W.inventory(run));self.assertFalse((run/'stop.request').exists())
        self.assertEqual(self.calls,[])  # Campaign runner did not handle this input.

    def test_standalone_incompatible_templates_rejected_before_worker(self):
        self.standalone_fixture()
        choice=next(c for c in self.control.options()['campaigns'] if c.get('input_kind')=='standalone')
        with self.standalone_verifier(),patch.object(G.A,'standalone',side_effect=W.ControlError('Independent templates differ')) as admission:
            with self.assertRaisesRegex(W.ControlError,'templates differ'):
                self.control.start(choice['id'],self.tid,'incompatible')
            admission.assert_called_once()
        self.assertIsNone(self.workflow._active);self.assertFalse((self.root/G.OUTPUTS/'incompatible').exists())

    def test_standalone_completed_output_recovers_but_rehashed_changes_fail(self):
        self.standalone_fixture()
        choice=next(c for c in self.control.options()['campaigns'] if c.get('input_kind')=='standalone')
        with self.standalone_verifier():
            self.control.start(choice['id'],'','standalone-sealed');self.wait_finished()
            self.control.jobs['standalone-sealed']['status']='interrupted';self.control._persist()
            restored=G.SavedGeGIControl(self.workflow)
            self.assertEqual(restored.state('standalone-sealed')['status'],'completed_conditional_reconstruction')
            directory=self.root/G.OUTPUTS/'standalone-sealed';path=directory/'results.json'
            changed=W.read(path);changed['counts']['initial_primaries']=99;W.write(path,changed)
            complete=W.read(directory/'COMPLETE.json');complete['files']['results.json']=W.sha(path)
            W.write(directory/'COMPLETE.json',complete)
            with self.assertRaisesRegex(W.ControlError,'completion receipt changed'):restored.results('standalone-sealed')


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

    def test_completed_derivative_result_get_is_closed_authenticated_and_read_only(self):
        self.workflow.gegi_saved_results.return_value={'kind':'gegi_multichannel_results_v1',
            'name':'original-gegi','saved_derivative_name':'derived','events':[]}
        status,body=self.request('/api/workflow/gegi-saved/results?name=derived')
        self.assertEqual(status,200);self.assertEqual(json.loads(body)['name'],'original-gegi')
        self.workflow.gegi_saved_results.assert_called_once_with('derived')
        for suffix in ('?name=derived&name=other','?name=derived&file=results.json','?name=../private','?name=CON',''):
            self.assertEqual(self.request('/api/workflow/gegi-saved/results'+suffix)[0],400)
        self.assertEqual(self.request('/api/workflow/gegi-saved/results?name=derived',headers={'X-Control-Token':None})[0],403)
        self.workflow.reprocess_gegi_saved.assert_not_called();self.workflow.start.assert_not_called()


if __name__=='__main__':unittest.main()
