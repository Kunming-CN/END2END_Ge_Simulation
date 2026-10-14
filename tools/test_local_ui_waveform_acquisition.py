"""Focused saved-acquisition GET/controller contracts; no real export or workers."""
import copy
import hashlib
import http.client
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import local_ui as U
import local_ui_workflow_jobs as J
import psd_features as P
import scenario_workflow as W

CONFIG_SHA='a'*64
PROFILE_SHA='b'*64
SOURCE_MANIFEST_SHA='c'*64
SOURCE_PROFILE_SHA='d'*64


class LocalFixture(unittest.TestCase):
    def setUp(self):
        base=W.ROOT/'.local/psd-acquisition-v1/viewer-implementation/tests'
        base.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)


class AcquisitionRoutes(LocalFixture):
    def setUp(self):
        super().setUp()
        self.workflow=Mock()
        self.workflow.acquisition.return_value={'kind':'local_saved_waveform_acquisition_v1','available':False}
        self.server=U.Server(0,Mock(root=self.root),token='fixture-token',workflow_controller=self.workflow)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start();self.addCleanup(self.close)

    def close(self):
        self.server.shutdown();self.server.server_close();self.thread.join()

    def request(self,route,headers=None,method='GET'):
        values={'Host':'127.0.0.1:'+str(self.server.server_port),'X-Control-Token':self.server.token}
        if method=='POST':values.update(Origin=self.server.origin,**{'Content-Type':'application/json'})
        for key,value in (headers or {}).items():
            if value is None:values.pop(key,None)
            else:values[key]=value
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
        try:
            connection.request(method,route,body='{}' if method=='POST' else None,headers=values)
            response=connection.getresponse()
            return response.status,response.read(),dict(response.getheaders())
        finally:connection.close()

    def test_exact_safe_global_primary_optional_group_and_no_mutation_route(self):
        for route,args in (
                ('name=fixture&primary=371',('fixture',371,None)),
                ('name=fixture&primary=371&group=0',('fixture',371,0)),
                ('name=fixture&primary=9007199254740991&group=9007199254740991',('fixture',9007199254740991,9007199254740991))):
            status,data,headers=self.request('/api/workflow/acquisition?'+route)
            self.assertEqual(status,200);self.assertFalse(json.loads(data)['available'])
            self.assertEqual(headers['Cache-Control'],'no-store')
            self.workflow.acquisition.assert_called_with(*args)
        for method in ('features','start','check','check_batches','finalize_results','verify','artifact'):
            getattr(self.workflow,method).assert_not_called()
        self.assertEqual(self.request('/api/workflow/acquisition?name=fixture&primary=0',method='POST')[0],404)

    def test_protected_get_does_not_accept_download_cookie(self):
        for headers in ({'X-Control-Token':None},{'Host':'evil.example'},
                {'Origin':'https://evil.example'},{'Sec-Fetch-Site':'cross-site'},
                {'X-Control-Token':None,'Sec-Fetch-Site':'same-origin',
                 'Cookie':self.server.workflow_download_cookie+'='+self.server.workflow_download_token}):
            self.assertEqual(self.request('/api/workflow/acquisition?name=fixture&primary=0',headers)[0],403)
        self.workflow.acquisition.assert_not_called()

    def test_closed_query_unsafe_names_and_inexact_ids_rejected(self):
        for suffix in ('','name=fixture','name=fixture&primary=0&file=private',
                'name=fixture&primary=0&primary=1','name=fixture&primary=',
                'name=fixture&primary=-1','name=fixture&primary=01','name=fixture&primary=1.0',
                'name=fixture&primary=9007199254740992','name=fixture&primary=0&group=',
                'name=fixture&primary=0&group=none','name=fixture&primary=0&group=-1',
                'name=fixture&primary=0&group=00','name=fixture&primary=0&group=1&group=2',
                'name=fixture&primary=0#x','name=../private&primary=0',
                'name=C%3A%5Cprivate&primary=0','name=CON&primary=0'):
            self.assertEqual(self.request('/api/workflow/acquisition?'+suffix)[0],400,suffix)
        self.workflow.acquisition.assert_not_called()


class AcquisitionController(LocalFixture):
    def setUp(self):
        super().setUp()
        self.controller=J.WorkflowController(self.root,launcher=lambda *args:self.fail('Unexpected launch'))
        self.job={'name':'fixture','status':'completed','plan':{'configuration_sha256':CONFIG_SHA}}
        self.controller._jobs=[self.job]
        self.directory=self.root/'.local/waveform-acquisition'/CONFIG_SHA/'bundle'
        group={'global_initial_id':1,'group_id':0,'event_id':0,'batch_index':1,'local_initial_id':0,
               'selection':{'valid':False,'reasons':['native_step_limit']},'Erec_keV':3.9,
               'features':{'A_nA':None},'deposits':[{'raw_row_index':7,'position_mm':[1,2,3]}],
               'acquisition':{'selection':{'valid':False,'reasons':['source_feature_invalid']},
                    'acquisition_energy_keV':None,'trace':{'time_since_origin_ns':[-10,0,10],
                    'adc_center_V':[0,-.003,-.001],'adc_code':[8192,7946,8110]},
                    'observed':{'candidate_energy_keV':4.1}}}
        self.dataset={'kind':'saved_waveform_acquisition_v1','configuration_sha256':CONFIG_SHA,
                      'profile':{'kind':'synthetic_waveform_acquisition_profile_v1'},'calibrations':[],
                      'records':[{'global_initial_id':0,'pulse_groups':[],'acquisition_energy_keV':None},
                                 {'global_initial_id':1,'pulse_groups':[group]}],
                      'counts':{'primaries':2,'pulse_groups':1,'selected_groups':0},
                      'provenance':{'run_ref':'.local/runs/fixture','profile_sha256':PROFILE_SHA,
                         'source_features_ref':'.local/psd-features/'+CONFIG_SHA+'/bundle',
                         'source_features_manifest_sha256':SOURCE_MANIFEST_SHA,'source_profile_sha256':SOURCE_PROFILE_SHA}}
        self.backend=SimpleNamespace(default_bundle_dir=lambda root,cfg:Path(root)/'.local/waveform-acquisition'/cfg/'bundle',
                   load_bundle=Mock(return_value=self.dataset),get_record=Mock(wraps=P.get_record),encoded=P.encoded,
                   export_bundle=Mock())
        self.patch=patch.object(J,'acquisition_backend',return_value=self.backend)
        self.patch.start();self.addCleanup(self.patch.stop)

    def test_absent_bundle_is_friendly_and_creates_nothing(self):
        with patch.object(self.controller,'_persist') as persist:
            reply=self.controller.acquisition('fixture',0)
        self.assertFalse(reply['available']);self.assertIsNone(reply['group_id'])
        self.assertEqual(reply['configuration_sha256'],CONFIG_SHA)
        for key in ('profile_sha256','bundle_sha256','source_features_manifest_sha256','source_profile_sha256'):
            self.assertIsNone(reply[key])
        self.assertIn('does not export',reply['note']);self.assertFalse(self.directory.exists())
        self.backend.load_bundle.assert_not_called();self.backend.export_bundle.assert_not_called();persist.assert_not_called()

    def test_verified_join_preserves_originals_signed_samples_and_null_energy(self):
        self.directory.mkdir(parents=True);original=copy.deepcopy(self.dataset)
        with patch.object(self.controller,'_persist') as persist:
            reply=self.controller.acquisition('fixture',1,0)
        self.backend.load_bundle.assert_called_once_with(self.directory,expected_config_sha256=CONFIG_SHA,root=self.root,verify_inputs=True)
        self.backend.get_record.assert_called_once_with(self.dataset,1,0)
        self.assertEqual(reply['record'],self.dataset['records'][1]['pulse_groups'][0])
        self.assertEqual(reply['bundle_sha256'],hashlib.sha256(P.encoded(self.dataset)).hexdigest())
        self.assertEqual(reply['source_features_manifest_sha256'],SOURCE_MANIFEST_SHA)
        self.assertEqual(reply['record']['acquisition']['trace']['adc_center_V'],[0,-.003,-.001])
        self.assertIsNone(reply['record']['acquisition']['acquisition_energy_keV'])
        self.assertEqual(reply['record']['Erec_keV'],3.9);self.assertEqual(self.dataset,original)
        self.backend.export_bundle.assert_not_called();persist.assert_not_called()

    def test_unknown_nonterminal_bool_and_noncanonical_requests_refused(self):
        for name,pid,gid in (('../private',0,None),('missing',0,None),('fixture',True,None),
                             ('fixture',0,True),('fixture',-1,None),('fixture',9007199254740992,None)):
            with self.assertRaises(J.ControlError):self.controller.acquisition(name,pid,gid)
        for status in ('running','stopped','dispatch_uncertain'):
            self.job['status']=status
            with self.assertRaises(J.ControlError):self.controller.acquisition('fixture',0)
        self.job['status']='completed';self.job['plan']['configuration_sha256']='../private'
        with self.assertRaises(J.ControlError):self.controller.acquisition('fixture',0)
        self.job['plan']['configuration_sha256']=CONFIG_SHA
        self.backend.default_bundle_dir=lambda *args:self.root/'.local/other'
        with self.assertRaises(J.ControlError):self.controller.acquisition('fixture',0)

    def test_changed_source_run_or_unverifiable_inputs_are_sanitized(self):
        self.directory.mkdir(parents=True)
        for key,value in (('run_ref','.local/runs/another'),('source_features_ref','.local/psd-features/other/bundle'),
                          ('source_features_manifest_sha256','private'),('source_profile_sha256',None)):
            changed=copy.deepcopy(self.dataset);changed['provenance'][key]=value
            self.backend.load_bundle.return_value=changed
            with self.assertRaisesRegex(J.ControlError,'could not be verified'):
                self.controller.acquisition('fixture',1,0)
        for error in (OSError('C:/private-input'),ValueError('secret'),J.ControlError('private hash mismatch')):
            self.backend.load_bundle.side_effect=error
            with self.assertRaisesRegex(J.ControlError,'could not be verified') as caught:
                self.controller.acquisition('fixture',1,0)
            self.assertNotIn('private',str(caught.exception));self.assertNotIn('secret',str(caught.exception))
        self.backend.export_bundle.assert_not_called()


if __name__=='__main__':unittest.main()
