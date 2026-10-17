"""GeGI Control admission and saved-data protection; no scientific workers."""
import copy
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import local_ui as U
import local_ui_workflow_jobs as J
import scenario_workflow as W


class GeGIProtocol(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='gegi-control-',dir=W.ROOT/'.local')
        self.addCleanup(self.temp.cleanup)
        self.workflow=Mock()
        self.server=U.Server(0,Mock(root=Path(self.temp.name)),token='gegi-test',workflow_controller=self.workflow)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start();self.addCleanup(self.close)

    def close(self):
        self.server.shutdown();self.server.server_close();self.thread.join()

    def request(self,route,*,data=None,token=True,origin=None):
        headers={'Host':'127.0.0.1:'+str(self.server.server_port)}
        if token:headers['X-Control-Token']=self.server.token
        if data is not None:headers.update({'Origin':self.server.origin,'Content-Type':'application/json'})
        if origin is not None:headers['Origin']=origin
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
        connection.request('POST' if data is not None else 'GET',route,
                           json.dumps(data) if data is not None else None,headers)
        response=connection.getresponse();body=response.read();status=response.status;connection.close()
        return status,json.loads(body)

    def test_saved_results_are_closed_authenticated_and_read_only(self):
        reply={'kind':'gegi_multichannel_results_v1','name':'gegi-owned','configuration_sha256':'a'*64}
        self.workflow.gegi_results.return_value=reply
        self.assertEqual(self.request('/api/workflow/gegi-results?name=gegi-owned'),(200,reply))
        self.workflow.gegi_results.assert_called_once_with('gegi-owned')
        for route in ('/api/workflow/gegi-results?name=gegi-owned&name=other',
                      '/api/workflow/gegi-results?run=gegi-owned',
                      '/api/workflow/gegi-results?name=../private',
                      '/api/workflow/gegi-results?name=gegi-owned&file=secret',
                      '/api/workflow/gegi-results?name=gegi-owned#fragment'):
            self.assertEqual(self.request(route)[0],400,route)
        self.assertEqual(self.request('/api/workflow/gegi-results?name=gegi-owned',token=False)[0],403)
        self.assertEqual(self.request('/api/workflow/gegi-results?name=gegi-owned',origin='https://foreign.invalid')[0],403)
        self.assertEqual(self.workflow.gegi_results.call_count,1)
        for method in ('start','check','check_gegi','resume','verify','artifact'):
            getattr(self.workflow,method).assert_not_called()

    def test_check_requires_exact_config_wrapper_and_session(self):
        self.workflow.check_gegi.return_value={'check_id':'checked-gegi'}
        config={'detector':'GeGI_3D'}
        self.assertEqual(self.request('/api/workflow/check-gegi',data={'config':config}),
                         (200,{'check_id':'checked-gegi'}))
        self.workflow.check_gegi.assert_called_once_with(config=config)
        for body in ({'config':config,'run':True},{'config':[]},{'selection':config}):
            self.assertEqual(self.request('/api/workflow/check-gegi',data=body)[0],400)
        self.assertEqual(self.request('/api/workflow/check-gegi',data={'config':config},token=False)[0],403)
        self.assertEqual(self.workflow.check_gegi.call_count,1)
        self.workflow.start.assert_not_called()


class GeGIController(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='gegi-controller-',dir=W.ROOT/'.local')
        self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.plan={'kind':J.GEGI_KIND,'status':'checked_configuration','science_calls':0,
                   'configuration_sha256':'a'*64,'resolved':{'selection':{'name':'owned'}}}
        self.resolver=Mock(return_value=copy.deepcopy(self.plan))
        self.controller=J.WorkflowController(self.root,gegi_resolver=self.resolver)

    def test_gegi_check_is_read_only_and_rejects_other_plan_kinds(self):
        checked=self.controller.check_gegi({'detector':'GeGI_3D'})
        self.assertEqual(checked['kind'],J.GEGI_KIND);self.assertEqual(len(checked['check_id']),64)
        self.assertFalse((self.root/J.STATE/'workflow-jobs.json').exists())
        self.resolver.return_value=dict(self.plan,kind=W.KIND)
        with self.assertRaises(W.ControlError):self.controller.check_gegi({})

    def test_saved_view_requires_owned_terminal_kind_and_matching_config(self):
        job={'name':'owned','status':'completed','plan':copy.deepcopy(self.plan)}
        self.controller._jobs=[job]
        backend=Mock();backend.result_view.return_value={
            'kind':'gegi_multichannel_results_v1','configuration_sha256':'a'*64,'events':[]}
        with patch.object(J,'gegi_backend',return_value=backend):
            self.assertEqual(self.controller.gegi_results('owned')['name'],'owned')
            backend.result_view.assert_called_once_with('owned',self.root)
            backend.inspect.assert_not_called()
            backend.result_view.return_value['configuration_sha256']='b'*64
            with self.assertRaises(W.ControlError):self.controller.gegi_results('owned')
            backend.reset_mock();job['status']='running'
            with self.assertRaises(W.ControlError):self.controller.gegi_results('owned')
            backend.inspect.assert_not_called();backend.result_view.assert_not_called()
            job['status']='completed';job['plan']['kind']=W.KIND
            with self.assertRaises(W.ControlError):self.controller.gegi_results('owned')
            with self.assertRaises(W.ControlError):self.controller.gegi_results('unowned')


if __name__=='__main__':unittest.main()
