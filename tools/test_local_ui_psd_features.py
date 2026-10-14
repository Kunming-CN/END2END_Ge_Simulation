"""Focused saved-feature GET/control contracts; no simulation or real export."""
import copy
import hashlib
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import local_ui as U
import local_ui_workflow_jobs as J
import psd_features as P
import scenario_workflow as W


CONFIG_SHA = 'a' * 64
PROFILE_SHA = 'b' * 64


class LocalFixture(unittest.TestCase):
    def setUp(self):
        base=W.ROOT/'.local/psd-features-v1/viewer-implementation/tests'
        base.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)


class FeatureRoutes(LocalFixture):
    def setUp(self):
        super().setUp()
        self.workflow=Mock()
        self.workflow.features.return_value={'kind':'local_saved_psd_features_v1','available':False}
        controller=Mock(root=self.root)
        self.server=U.Server(0,controller,token='fixture-token',workflow_controller=self.workflow)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.addCleanup(self.close)

    def close(self):
        self.server.shutdown();self.server.server_close();self.thread.join()

    def request(self,route,headers=None,method='GET'):
        values={'Host':'127.0.0.1:'+str(self.server.server_port),'X-Control-Token':self.server.token}
        if method=='POST':values.update(Origin=self.server.origin,**{'Content-Type':'application/json'})
        for key,value in (headers or {}).items():
            if value is None:values.pop(key,None)
            else:values[key]=value
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
        connection.request(method,route,body='{}' if method=='POST' else None,headers=values)
        response=connection.getresponse()
        answer=(response.status,response.read(),dict(response.getheaders()))
        connection.close();return answer

    def test_exact_global_primary_and_optional_group_are_read_only(self):
        for route,args in (
            ('/api/workflow/features?name=fixture&primary=371',('fixture',371,None)),
            ('/api/workflow/features?name=fixture&primary=371&group=0',('fixture',371,0)),
            ('/api/workflow/features?name=fixture&primary=9007199254740991&group=9007199254740991',('fixture',9007199254740991,9007199254740991))):
            status,data,headers=self.request(route)
            self.assertEqual(status,200);self.assertFalse(json.loads(data)['available'])
            self.assertEqual(headers['Cache-Control'],'no-store')
            self.workflow.features.assert_called_with(*args)
        for name in ('start','check','check_batches','finalize_results','verify','artifact'):
            getattr(self.workflow,name).assert_not_called()
        self.assertEqual(self.request('/api/workflow/features?name=fixture&primary=0',method='POST')[0],404)

    def test_protected_get_has_no_download_cookie_authority(self):
        route='/api/workflow/features?name=fixture&primary=0'
        for headers in ({'X-Control-Token':None},{'Host':'evil.example'},
                {'Origin':'https://evil.example'},{'Sec-Fetch-Site':'cross-site'},
                {'X-Control-Token':None,'Sec-Fetch-Site':'same-origin',
                 'Cookie':self.server.workflow_download_cookie+'='+self.server.workflow_download_token}):
            self.assertEqual(self.request(route,headers)[0],403)
        self.workflow.features.assert_not_called()

    def test_closed_query_exact_numeric_ids_and_unsafe_names(self):
        for suffix in ('','name=fixture','name=fixture&primary=0&file=private',
                'name=fixture&primary=0&primary=1','name=fixture&primary=',
                'name=fixture&primary=-1','name=fixture&primary=01','name=fixture&primary=1.0',
                'name=fixture&primary=9007199254740992','name=fixture&primary=0&group=',
                'name=fixture&primary=0&group=none','name=fixture&primary=0&group=-1',
                'name=fixture&primary=0&group=00','name=fixture&primary=0&group=1&group=2',
                'name=fixture&primary=0#x','name=../private&primary=0',
                'name=C%3A%5Cprivate&primary=0','name=CON&primary=0'):
            self.assertEqual(self.request('/api/workflow/features?'+suffix)[0],400,suffix)
        self.workflow.features.assert_not_called()


class FeatureController(LocalFixture):
    def setUp(self):
        super().setUp()
        self.controller=J.WorkflowController(self.root,launcher=lambda *args:self.fail('Unexpected launch'))
        self.job={'name':'fixture','status':'completed','plan':{'configuration_sha256':CONFIG_SHA}}
        self.controller._jobs=[self.job]
        self.directory=P.default_bundle_dir(self.root,CONFIG_SHA)
        group={'global_initial_id':1,'group_id':0,'event_id':0,'batch_index':1,'local_initial_id':0,
               'selection':{'valid':False,'reasons':['native_step_limit']},
               'features':{'A_nA':None,'A_over_E_nA_per_keV':None,'charge_rise_10_90_ns':None},
               'observed':{'signed_filtered_current_peak_nA':-.003},'deposits':[{'raw_row_index':7,'position_mm':[1,2,3]}]}
        self.dataset={'kind':P.KIND,'configuration_sha256':CONFIG_SHA,'profile':{'kind':P.PROFILE_KIND},
                      'records':[{'global_initial_id':0,'pulse_groups':[],'selection':{'valid':False,'reasons':['zero_deposit']}},
                                 {'global_initial_id':1,'pulse_groups':[group]}],
                      'counts':{'primaries':2,'pulse_groups':1,'selected_groups':0},
                      'provenance':{'run_ref':'.local/runs/fixture','profile_sha256':PROFILE_SHA}}

    def test_absent_bundle_is_friendly_and_creates_nothing(self):
        with (patch.object(J,'psd_backend',return_value=P),patch.object(P,'load_bundle') as loader,
                patch.object(P,'export_bundle') as exporter,patch.object(self.controller,'_persist') as persist):
            reply=self.controller.features('fixture',0)
        self.assertFalse(reply['available']);self.assertIsNone(reply['group_id'])
        self.assertEqual(reply['configuration_sha256'],CONFIG_SHA)
        self.assertIsNone(reply['profile_sha256']);self.assertIsNone(reply['bundle_sha256'])
        self.assertIn('does not export',reply['note'])
        self.assertFalse(self.directory.exists())
        loader.assert_not_called();exporter.assert_not_called();persist.assert_not_called()

    def test_verified_bundle_uses_owned_config_and_shared_exact_record(self):
        self.directory.mkdir(parents=True)
        original=copy.deepcopy(self.dataset)
        with (patch.object(J,'psd_backend',return_value=P),patch.object(P,'load_bundle',return_value=self.dataset) as loader,
                patch.object(P,'get_record',wraps=P.get_record) as selector,
                patch.object(P,'export_bundle') as exporter,patch.object(self.controller,'_persist') as persist):
            reply=self.controller.features('fixture',1,0)
            loader.assert_called_once_with(self.directory,expected_config_sha256=CONFIG_SHA,root=self.root,verify_inputs=True)
            selector.assert_called_once_with(self.dataset,1,0)
        self.assertTrue(reply['available']);self.assertEqual(reply['record'],self.dataset['records'][1]['pulse_groups'][0])
        self.assertEqual(reply['bundle_sha256'],hashlib.sha256(P.encoded(self.dataset)).hexdigest())
        self.assertEqual(reply['profile_sha256'],PROFILE_SHA)
        self.assertIsNone(reply['record']['features']['A_nA'])
        self.assertEqual(reply['record']['observed']['signed_filtered_current_peak_nA'],-.003)
        self.assertEqual(self.dataset,original)
        exporter.assert_not_called();persist.assert_not_called()

    def test_unknown_nonterminal_malformed_and_noncanonical_requests_refused(self):
        for name,pid,gid in (('../private',0,None),('missing',0,None),('fixture',True,None),
                             ('fixture',0,True),('fixture',-1,None),('fixture',9007199254740992,None)):
            with self.assertRaises(J.ControlError):self.controller.features(name,pid,gid)
        for status in ('running','stopped','dispatch_uncertain'):
            self.job['status']=status
            with self.assertRaises(J.ControlError):self.controller.features('fixture',0)
        self.job['status']='completed';self.job['plan']['configuration_sha256']='../private'
        with self.assertRaises(J.ControlError):self.controller.features('fixture',0)
        self.job['plan']['configuration_sha256']=CONFIG_SHA
        with patch.object(P,'default_bundle_dir',return_value=self.root/'.local/other'),self.assertRaises(J.ControlError):
            self.controller.features('fixture',0)

    def test_changed_or_unverifiable_inputs_are_sanitized_and_not_reexported(self):
        self.directory.mkdir(parents=True)
        for error in (OSError('C:/private-input'),ValueError('secret'),J.ControlError('private hash mismatch')):
            with patch.object(P,'load_bundle',side_effect=error),patch.object(P,'export_bundle') as exporter:
                with self.assertRaisesRegex(J.ControlError,'could not be verified') as caught:
                    self.controller.features('fixture',1,0)
                self.assertNotIn('private',str(caught.exception));self.assertNotIn('secret',str(caught.exception))
                exporter.assert_not_called()
        changed=copy.deepcopy(self.dataset);changed['provenance']['run_ref']='.local/runs/another'
        with patch.object(P,'load_bundle',return_value=changed),self.assertRaisesRegex(J.ControlError,'another saved run'):
            self.controller.features('fixture',1,0)


if __name__=='__main__':unittest.main()
