"""Real protected loopback workflow routes; every backend action is mocked."""
import http.client
import hashlib
import copy
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
import local_ui as U
import scenario_workflow as W
import local_ui_workflow_jobs as J
import local_ui_gamma_jobs as G
import workflow_recovery as R
from test_local_ui_gamma_jobs import Runner, finished_fixture


class Protocol(unittest.TestCase):
    def setUp(self):
        base=W.ROOT/'.local/product-delivery-v1/implementation-tests';base.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=base);self.addCleanup(self.temp.cleanup)
        legacy=Mock(root=Path(self.temp.name));legacy.snapshot.return_value={'jobs':[]}
        self.workflow=Mock();self.workflow.snapshot.return_value={'kind':'fixture','jobs':[],'busy':False}
        self.workflow.check.return_value={'check_id':'checked'}
        self.workflow.start.return_value={'status':'dispatch_uncertain'}
        self.workflow.artifact.return_value=(b"<a href='run.json'>Data</a><details><summary>Event 7 / group 2</summary></details>",'text/html; charset=utf-8')
        self.server=U.Server(0,legacy,token='test-session',workflow_controller=self.workflow)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.close)

    def close(self):self.server.shutdown();self.server.server_close();self.thread.join()

    def request(self,method='GET',route='/api/workflow/state',body=None,headers=None):
        values={'Host':'127.0.0.1:'+str(self.server.server_port),'X-Control-Token':self.server.token}
        if method=='POST':values.update({'Origin':self.server.origin,'Content-Type':'application/json'})
        for key,value in (headers or {}).items():
            if value is None:values.pop(key,None)
            else:values[key]=value
        if isinstance(body,dict):body=json.dumps(body)
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
        connection.request(method,route,body=body,headers=values);r=connection.getresponse()
        result=(r.status,r.read(),dict(r.getheaders()));connection.close();return result

    def test_catalog_inspection_metadata_preserves_all17_and_execution_boundary(self):
        catalog = W.catalog()
        source = W.read(W.ROOT/'models/catalog.json')['detectors']
        self.assertEqual(len(catalog['detectors']), 17)
        self.assertEqual([d['id'] for d in catalog['detectors']], [m['id'] for m in source])
        for item, model in zip(catalog['detectors'], source):
            self.assertEqual(item['model']['contacts'], model['contacts'])
            self.assertEqual(item['model']['status'], model['status'])
            self.assertEqual(item['model']['model_sha256'], model['model_sha256'])
            self.assertIn(item['id']+'/geometry.html', item['geometry_url'])
            self.assertTrue(item['type_label'])
            if not item['available']:
                self.assertEqual(item['sources'], [])
                self.assertTrue(item['reason'])
                candidate=dict(name='catalog-fixture',cryostat=W.CRYOSTAT,
                    detector=item['id'],source=W.CS,pose='nominal',primary_count=20,
                    seed=26092631,threads=2,electronics=catalog['electronics_defaults'])
                if item['id'] not in W.MODELS:
                    with patch.object(W,'settings_check',side_effect=AssertionError('Settings executed')), self.assertRaises(W.ControlError):
                        W._resolve(candidate,root=self.server.controller.root)
        self.assertTrue({d['id'] for d in catalog['detectors'] if d['available']} <=
                        set(W.MODELS)|{'AK01','SAP16','SAP17','Bipolar_reference_3D','KL01_3D'})
        self.assertTrue({'AK02','SAP22','GeRC02','KMRC01_candidate'} <= {d['id'] for d in catalog['detectors'] if d['available']})

    def test_sap18_exact_capability_after_acceptance_and_unchecked_edits_refused(self):
        catalog=W.catalog()
        sap=next(d for d in catalog['detectors'] if d['id']==W.SAP18)
        self.assertTrue(sap['available'])
        legacy={s['id'] for s in catalog['sources'] if s['source_contract']['adapter'].startswith('legacy_')}
        self.assertEqual([s for s in sap['sources'] if s in legacy],[W.CS])
        self.assertNotIn(W.GAMMA,sap['sources'])
        self.assertIn('identity unresolved',sap['operating_label'])
        self.assertEqual({d['id'] for d in catalog['detectors'] if d['available'] and d.get('workflow_kind')!=J.CATALOG_KIND},
                         {'AK02','SAP22','GeRC02','KMRC01_candidate',W.SAP18})
        original=W.read(W.ROOT/'scenarios/detector-capabilities.json')
        self.assertIs(next(d for d in original['detectors'] if d['model_id']==W.SAP18)['lbnl_execution_implemented'],False)
        for mutate in (lambda r:r['control_adapters'].pop(W.SAP18),
                lambda r:r['control_adapters'][W.SAP18].update(sources=[W.CS,W.GAMMA]),
                lambda r:r['control_adapters'][W.SAP18].update(counts=[20,500,10000]),
                lambda r:r['control_adapters'][W.SAP18].update(variant='KMRC01_candidate')):
            changed=copy.deepcopy(original);mutate(changed)
            reader=W.read
            with patch.object(W,'read',side_effect=lambda p:changed if str(p).endswith('detector-capabilities.json') else reader(p)):
                item=next(d for d in W.catalog()['detectors'] if d['id']==W.SAP18)
            self.assertFalse(item['available']);self.assertEqual(item['sources'],[])

    def test_saved_preview_route_is_exact_authenticated_and_read_only(self):
        with patch.object(U,'saved_model_preview',return_value=b'saved-png') as reader:
            status,body,headers=self.request(route='/api/model-preview?model=AK02')
            self.assertEqual((status,body,headers['Content-Type']),(200,b'saved-png','image/png'))
            reader.assert_called_once_with('AK02')
            reader.reset_mock()
            for headers in ({'X-Control-Token':''},{'Host':'evil.example'},
                    {'Origin':'https://evil.example'},{'Sec-Fetch-Site':'cross-site'}):
                self.assertEqual(self.request(route='/api/model-preview?model=AK02',headers=headers)[0],403)
            for route in ('/api/model-preview','/api/model-preview?model=AK02&model=SAP22',
                    '/api/model-preview?model=AK02&file=private','/api/model-preview?model=AK02#x'):
                self.assertEqual(self.request(route=route)[0],400)
            self.assertEqual(self.request('POST','/api/model-preview?model=AK02',{})[0],404)
            reader.assert_not_called()
        self.workflow.check.assert_not_called();self.workflow.start.assert_not_called()

    def test_saved_preview_exact_bytes_and_failure_is_sanitized(self):
        for model in W.read(W.ROOT/'models/catalog.json')['detectors']:
            self.assertTrue(U.saved_model_preview(model['id']).startswith(b'\x89PNG'))
        for model in ('../AK02','AK02/../../private','unknown','AK02\\\\private'):
            with self.assertRaises(ValueError):U.saved_model_preview(model)
        for error in (ValueError('C:/private/path'), OSError('secret inputs')):
            with patch.object(U,'saved_model_preview',side_effect=error):
                code,data,_=self.request(route='/api/model-preview?model=AK02')
            self.assertEqual(code,503);self.assertNotIn(b'private',data);self.assertNotIn(b'secret',data)

    def test_saved_preview_refuses_changed_catalog_hash_bytes_and_links(self):
        model=W.read(W.ROOT/'models/catalog.json')['detectors'][0]
        root=self.server.controller.root
        (root/'models').mkdir();(root/'docs/models').mkdir(parents=True)
        def save_model(current,published):
            (root/'models/catalog.json').write_text(json.dumps({'detectors':[current]}))
            (root/'docs/models/catalog.json').write_text(json.dumps({'detectors':[published]}))
        changed=copy.deepcopy(model);changed['model_sha256']='f'*64
        save_model(model,changed)
        with self.assertRaises(ValueError):U.saved_model_preview(model['id'],root)
        save_model(model,model)
        relative='detectors/'+model['id']+'/runs/20260922_suite_v3/01_geometry.png'
        image=root/'docs'/relative;image.parent.mkdir(parents=True);image.write_bytes(b'\x89PNG\r\n\x1a\nfixture')
        (root/'docs/site-manifest.json').write_text(json.dumps({'files':[{'path':relative,'bytes':image.stat().st_size,'sha256':W.sha(image)}]}))
        self.assertEqual(U.saved_model_preview(model['id'],root),image.read_bytes())
        image.write_bytes(image.read_bytes()+b'changed')
        with self.assertRaises(ValueError):U.saved_model_preview(model['id'],root)
        with patch.object(U,'safe_path',side_effect=W.ControlError('Linked path refused')):
            with self.assertRaises(W.ControlError):U.saved_model_preview(model['id'],root)

    def test_catalog_check_route_is_closed_protected_and_read_only(self):
        self.workflow.check_catalog.return_value={'kind':J.CATALOG_KIND,'status':'checked_configuration','check_id':'catalog-check'}
        for data in ({'config':{},'start':True},{'config':[]},{'config':True},'null'):
            self.assertEqual(self.request('POST','/api/workflow/check-catalog',data)[0],400)
        for headers in ({'X-Control-Token':''},{'Origin':'https://evil.example'},{'Origin':None}):
            self.assertEqual(self.request('POST','/api/workflow/check-catalog',{'config':{}},headers)[0],403)
        self.workflow.check_catalog.assert_not_called()
        status,body,_=self.request('POST','/api/workflow/check-catalog',{'config':{'detector':'AK01'}})
        self.assertEqual(status,200);self.assertEqual(json.loads(body)['kind'],J.CATALOG_KIND)
        self.workflow.check_catalog.assert_called_once_with(config={'detector':'AK01'})
        self.workflow.check.assert_not_called();self.workflow.start.assert_not_called()

    def test_exact_checked_identity_only_start(self):
        self.assertEqual(self.request('POST','/api/workflow/check',{'config':{'name':'fixture'}})[0],200)
        self.workflow.check.assert_called_once_with(config={'name':'fixture'})
        for data in ({'check_id':'checked','config':{}},{'check_id':True},'[]','null'):
            self.assertEqual(self.request('POST','/api/workflow/start',data)[0],400)
        self.workflow.start.assert_not_called()
        self.assertEqual(self.request('POST','/api/workflow/start',{'check_id':'checked'})[0],200)
        self.workflow.start.assert_called_once_with(check_id='checked')

    def test_batch_preview_route_is_closed_authenticated_and_read_only(self):
        self.workflow.preview_batches.return_value={'kind':'local_scenario_batch_preview_v2',
            'schema_version':2,'science_calls':0,'execution_enabled':False}
        for data in ({'request':{} ,'start':True},{'request':[]},{'request':True},'null'):
            self.assertEqual(self.request('POST','/api/workflow/preview-batches',data)[0],400)
        for headers in ({'X-Control-Token':''},{'Origin':'https://evil.example'},{'Origin':None}):
            self.assertEqual(self.request('POST','/api/workflow/preview-batches',{'request':{}},headers)[0],403)
        self.workflow.preview_batches.assert_not_called()
        status,raw,_=self.request('POST','/api/workflow/preview-batches',{'request':{'schema_version':2}})
        self.assertEqual(status,200);self.assertIs(json.loads(raw)['execution_enabled'],False)
        self.workflow.preview_batches.assert_called_once_with(request={'schema_version':2})
        self.workflow.start.assert_not_called()

    def test_actual_gui_and_cli_batch_import_admission_matches(self):
        import workflow_batches as B
        root=self.server.controller.root
        request={'kind':B.REQUEST_KIND,'schema_version':2,'selection':dict(name='fixture-v2',
            cryostat=W.CRYOSTAT,detector='AK02',source=W.CS,pose='nominal',primary_count=25001,
            seed=26092631,threads=2,electronics=W.catalog()['electronics_defaults'])}
        readers=dict(validate_settings=lambda e,r:{'profile':{'settings':e},
            'configuration':dict(e,expected_primary_count=None,max_samples_per_event=500000,max_window_ns=1000000),
            'physics_sha256':W.digest(e)},pin_reader=lambda d,r:{'fixture.txt':'no-science'},
            runtime_reader=lambda t:{'python_sha256':'fixture','julia_sha256':'fixture'})
        original=W.preview
        with patch.object(W,'preview',side_effect=lambda c,root=None:original(c,root=self.server.controller.root,**readers)):
            self.server.workflow_controller=J.WorkflowController(root,launcher=Mock())
            for n in (1,499,500,9999,10000,10001,25001):
                candidate=copy.deepcopy(request);candidate['selection']['primary_count']=n
                status,body,_=self.request('POST','/api/workflow/preview-batches',{'request':candidate})
                self.assertEqual(status,200)
                cli=W.preview(W.preview_request(candidate),root=root)
                self.assertTrue(B.typed_equal(json.loads(body),cli))
            for n in (0,-1,True,1.0,'25001',None,B.MAX_SAFE_INTEGER+1,B.MAX_SEEDED_PRIMARIES+1):
                candidate=copy.deepcopy(request);candidate['selection']['primary_count']=n
                self.assertEqual(self.request('POST','/api/workflow/preview-batches',{'request':candidate})[0],400)
                with self.assertRaises(W.ControlError):W.preview(W.preview_request(candidate),root=root)
            duplicate=json.dumps({'request':request}).replace('"primary_count": 25001',
                '"primary_count": 25001, "primary_count": 1')
            self.assertEqual(self.request('POST','/api/workflow/preview-batches',duplicate)[0],400)
            self.assertEqual(self.server.workflow_controller._checks,{})
            self.server.workflow_controller._launcher.assert_not_called()
        self.assertFalse((root/W.BASE).exists());self.assertFalse((root/J.STATE).exists())

    def test_origin_host_and_token_refused_before_backend(self):
        for headers in ({'X-Control-Token':''},{'Host':'evil.example'},{'Origin':'https://evil.example'},
                        {'Sec-Fetch-Site':'cross-site'},{'Origin':None}):
            self.assertEqual(self.request('POST','/api/workflow/start',{'check_id':'checked'},headers)[0],403)
        self.workflow.start.assert_not_called()

    def test_explicit_saved_results_route_is_closed_and_authenticated(self):
        self.workflow.finalize_results.return_value={'status':'completed','science_calls':0}
        for data in ({'name':'saved','resume':True},{'name':True},'[]'):
            self.assertEqual(self.request('POST','/api/workflow/finalize-results',data)[0],400)
        for headers in ({'X-Control-Token':''},{'Origin':'https://evil.example'},{'Origin':None}):
            self.assertEqual(self.request('POST','/api/workflow/finalize-results',{'name':'saved'},headers)[0],403)
        self.workflow.finalize_results.assert_not_called()
        self.assertEqual(self.request('POST','/api/workflow/finalize-results',{'name':'saved'})[0],200)
        self.workflow.finalize_results.assert_called_once_with(name='saved')

    def test_cookie_read_only_and_same_origin(self):
        status,_,headers=self.request();self.assertEqual(status,200)
        self.assertIn('; Path=/api/workflow-file; HttpOnly; SameSite=Strict',headers['Set-Cookie'])
        cookie=self.server.workflow_download_cookie+'='+self.server.workflow_download_token
        browser={'X-Control-Token':'','Cookie':cookie,'Sec-Fetch-Site':'same-origin'}
        route='/api/workflow-file?name=fixture&file=response%2Fsummary.html'
        self.assertEqual(self.request(route=route,headers=browser)[0],200)
        self.assertEqual(self.request(headers=browser)[0],403)
        self.assertEqual(self.request('POST','/api/workflow/start',{'check_id':'checked'},browser)[0],403)
        self.assertEqual(self.request(route=route,headers={**browser,'Sec-Fetch-Site':'cross-site'})[0],403)

    def test_html_navigation_and_group_anchor_are_derived(self):
        _,body,_=self.request(route='/api/workflow-file?name=fixture&file=response%2Fsummary.html')
        self.assertIn(b'/api/workflow-file?name=fixture&file=response%2Frun.json',body)
        self.assertIn(b'id="event-7-group-2"',body)
        self.workflow.artifact.assert_called_once_with('fixture','response/summary.html')

    def test_raw_html_download_preserves_original_bytes_and_view_derivative(self):
        original='<html>\r\n<a href="run.json">π data</a><details><summary>Event 7 / group 2</summary></details>\r\n</html>'.encode('utf-8')
        self.workflow.artifact.return_value=(original,'text/html; charset=utf-8')
        route='/api/workflow-file?name=fixture&file=response%2Fsummary.html'
        view_status,view,_=self.request(route=route)
        raw_status,raw,headers=self.request(route=route+'&download=1')
        self.assertEqual((view_status,raw_status),(200,200))
        self.assertEqual(raw,original)
        self.assertEqual(hashlib.sha256(raw).hexdigest(),hashlib.sha256(original).hexdigest())
        self.assertEqual(int(headers['Content-Length']),len(original))
        self.assertNotEqual(view,original)
        self.assertIn(b'/api/workflow-file?name=fixture&file=response%2Frun.json',view)
        self.assertIn(b'id="event-7-group-2"',view)
        self.assertNotIn(b'id="event-7-group-2"',raw)
        self.assertEqual(self.workflow.artifact.call_args_list,[
            unittest.mock.call('fixture','response/summary.html'),
            unittest.mock.call('fixture','response/summary.html')])

    def test_raw_download_keeps_session_and_controller_boundaries(self):
        route='/api/workflow-file?name=fixture&file=response%2Fsummary.html&download=1'
        cookie=self.server.workflow_download_cookie+'='+self.server.workflow_download_token
        browser={'X-Control-Token':'','Cookie':cookie,'Sec-Fetch-Site':'same-origin'}
        self.assertEqual(self.request(route=route,headers=browser)[0],200)
        self.workflow.artifact.reset_mock()
        wrong=self.server.download_cookie+'='+self.server.download_token
        for headers in ({'X-Control-Token':''},{'Origin':'https://evil.example'},
                {**browser,'Sec-Fetch-Site':'cross-site'},
                {**browser,'Sec-Fetch-Site':'same-site'},
                {**browser,'Cookie':wrong},{**browser,'Sec-Fetch-Site':None}):
            with self.subTest(headers=headers):self.assertEqual(self.request(route=route,headers=headers)[0],403)
        self.workflow.artifact.assert_not_called()
        # The raw mode must still invoke the existing owner/path/hash authority.
        self.workflow.artifact.side_effect=W.ControlError('Saved artifact changed','workflow_refused')
        status,body,_=self.request(route=route)
        self.assertEqual(status,400)
        self.assertIn(b'Saved artifact changed',body)
        self.workflow.artifact.assert_called_once_with('fixture','response/summary.html')

    def test_query_alias_and_duplicate_artifact_fields_refused(self):
        for route in ('/api/workflow/state?','/api/workflow/state?name=a','/api/workflow/state#x'):
            self.assertEqual(self.request(route=route)[0],404)
        self.workflow.snapshot.assert_not_called()
        for route in ('/api/workflow-file?name=a&name=b&file=run.json',
                      '/api/workflow-file?name=a&file=run.json&extra=1',
                      '/api/workflow-file?name=a&file=run.json#x',
                      '/api/workflow-file?name=a&file=run.json&download=',
                      '/api/workflow-file?name=a&file=run.json&download=0',
                      '/api/workflow-file?name=a&file=run.json&download=true',
                      '/api/workflow-file?name=a&file=run.json&download=01',
                      '/api/workflow-file?name=a&file=run.json&download=1&download=1'):
            self.assertEqual(self.request(route=route)[0],400)
        self.workflow.artifact.assert_not_called()

    def test_actual_shared_lease_blocks_both_retained_start_routes(self):
        root=self.server.controller.root
        self.server.workflow_controller=J.WorkflowController(root)
        gamma=Mock();gamma.start.return_value={};self.server.gamma_controller=gamma
        with W.execution_lease(root):
            self.assertEqual(self.request('POST','/api/start',{'name':'new','detector':'AK02'})[0],400)
            self.assertEqual(self.request('POST','/api/gamma-start',{'check_id':'checked'})[0],400)
        self.server.controller.start.assert_not_called();gamma.start.assert_not_called()

    def test_continuation_route_uses_exact_string_names_only(self):
        self.workflow.continue_prefix.return_value={'status':'dispatch_uncertain'}
        for data in ({'name':'parent','new_name':'new','ignore':True},{'name':'parent'},{'name':'parent','new_name':True}):
            self.assertEqual(self.request('POST','/api/workflow/continue-prefix',data)[0],400)
        self.workflow.continue_prefix.assert_not_called()
        self.assertEqual(self.request('POST','/api/workflow/continue-prefix',{'name':'parent','new_name':'new'})[0],200)
        self.workflow.continue_prefix.assert_called_once_with(name='parent',new_name='new')

    def test_selected_plots_exact_identity_and_none_distinct_from_zero(self):
        self.workflow.waveforms.return_value={'kind':'saved_waveform_projection_v1','science_calls':0}
        for group,expected in (('none',None),('0',0),('2',2)):
            status,raw,_=self.request(route='/api/workflow-file/plots?name=fixture&primary=7&group='+group)
            self.assertEqual(status,200);self.assertEqual(json.loads(raw)['science_calls'],0)
            self.workflow.waveforms.assert_called_with('fixture',7,expected)
        self.workflow.start.assert_not_called()

    def test_selected_plots_reject_missing_token_cross_origin_and_wrong_cookie_scope(self):
        route='/api/workflow-file/plots?name=fixture&primary=7&group=2'
        for headers in ({'X-Control-Token':None},{'Origin':'https://evil.example'},
                        {'Sec-Fetch-Site':'cross-site'},{'Sec-Fetch-Site':'same-site'},
                        {'Host':'evil.example'}):
            self.assertEqual(self.request(route=route,headers=headers)[0],403)
        cookie=self.server.download_cookie+'='+self.server.download_token
        self.assertEqual(self.request(route=route,headers={'X-Control-Token':'','Cookie':cookie,'Sec-Fetch-Site':'same-origin'})[0],403)
        self.workflow.waveforms.assert_not_called()

    def test_selected_plots_cookie_is_read_only_same_origin_not_direct_navigation(self):
        self.workflow.waveforms.return_value={'science_calls':0}
        cookie=self.server.workflow_download_cookie+'='+self.server.workflow_download_token
        browser={'X-Control-Token':'','Cookie':cookie,'Sec-Fetch-Site':'same-origin'}
        route='/api/workflow-file/plots?name=fixture&primary=7&group=none'
        self.assertEqual(self.request(route=route,headers=browser)[0],200)
        for site in ('none','cross-site','same-site',None):
            self.assertEqual(self.request(route=route,headers={**browser,'Sec-Fetch-Site':site})[0],403)
        self.assertEqual(self.request(headers=browser)[0],403)
        self.assertEqual(self.request('POST','/api/workflow/start',{'check_id':'checked'},browser)[0],403)
        self.workflow.start.assert_not_called()

    def test_selected_plots_closed_query_refuses_alias_duplicate_invalid_and_fragment(self):
        prefix='/api/workflow-file/plots?'
        for query in ('name=a&primary=2&group=0&extra=1','name=a&primary=2&primary=3&group=0',
                      'name=a&primary=2','name=a&primary=true&group=0','name=a&primary=02&group=0',
                      'name=a&primary=-1&group=none','name=a&primary=2&group=nothing',
                      'name=a&primary=2&group=null','name=a&primary=2&group=-1',
                      'name=a&primary=2147483647&group=0','name=a&primary=2&group=2147483647',
                      'name=a&primary=2&group=0#x'):
            self.assertEqual(self.request(route=prefix+query)[0],400,query)
        self.workflow.waveforms.assert_not_called()

    def test_focused_plots_closed_same_origin_identity_contract(self):
        route='/api/workflow-file/focus?name=fixture&primary=7&group='
        self.workflow.focused_waveforms.return_value={'kind':'saved_focus_waveforms_v1','science_calls':0}
        for group,expected in (('none',None),('0',0),('2',2)):
            status,raw,_=self.request(route=route+group)
            self.assertEqual(status,200);self.assertEqual(json.loads(raw)['science_calls'],0)
            self.workflow.focused_waveforms.assert_called_with('fixture',7,expected)
        self.workflow.focused_waveforms.reset_mock()
        for headers in ({'X-Control-Token':None},{'Origin':'https://evil.example'},
                        {'Sec-Fetch-Site':'cross-site'},{'Host':'evil.example'}):
            self.assertEqual(self.request(route=route+'2',headers=headers)[0],403)
        for query in ('name=fixture&primary=7&group=2&extra=1','name=fixture&primary=7&group=2&group=0',
                      'name=fixture&primary=07&group=2','name=fixture&primary=7&group=-1',
                      'name=fixture&primary=7&group=2#x'):
            self.assertEqual(self.request(route='/api/workflow-file/focus?'+query)[0],400)
        cookie=self.server.download_cookie+'='+self.server.download_token
        self.assertEqual(self.request(route=route+'2',headers={'X-Control-Token':'','Cookie':cookie,'Sec-Fetch-Site':'same-origin'})[0],403)
        self.workflow.focused_waveforms.assert_not_called();self.workflow.start.assert_not_called()

    def test_terminal_gamma_verify_clears_cross_state_continuation_deadlock_without_science(self):
        root=self.server.controller.root;lock=threading.RLock();runner=Runner()
        gamma=G.GammaController(root,runner,identity_probe=lambda pid:None,coordination_lock=lock)
        old={'id':'e'*32,'output':G.BASE+'/ui-gamma-'+'e'*32,'threads':2,
             'status':'completed','uncertain':False,'child':None,'started_seconds':time.time(),
             'created_at':G.utc_now(),'updated_at':G.utc_now()}
        folder=finished_fixture(root,old['output'])
        old['complete_sha256']=W.sha(folder/'COMPLETE.json');old['run_sha256']=W.sha(folder/'run.json')
        gamma._jobs=[old];gamma._persist()
        gamma=G.GammaController(root,runner,identity_probe=lambda pid:None,coordination_lock=lock)
        selection={'name':R.PARENT,'detector':'SAP22','source':W.GAMMA,'primary_count':20}
        plan={'kind':W.KIND,'status':'checked_configuration','science_calls':0,
              'resolved':{'selection':selection},'configuration_sha256':'synthetic-original'}
        def resolver(config,root):
            value=copy.deepcopy(plan);value['resolved']['selection']=config;return value
        workflow=J.WorkflowController(root,resolver=resolver,coordination_lock=lock,peer_busy=gamma.own_busy)
        parent={'id':R.PARENT_DISPATCH,'name':R.PARENT,'status':'dispatch_uncertain',
                'plan':plan,'driver':None,'created_utc':'synthetic','mode':'run'}
        workflow._jobs=[parent];workflow._persist();gamma.set_peer_busy(workflow.own_busy)
        self.server.gamma_controller=gamma;self.server.workflow_controller=workflow
        original_files={p.relative_to(folder).as_posix():p.read_bytes() for p in folder.rglob('*') if p.is_file()}
        original_parent=W.read(workflow._state_path)['jobs'][0]
        body={'name':R.PARENT,'new_name':'cross-state-derived'}
        def inspected(*args):
            self.assertTrue(W.lease_busy(root));return {}
        with patch.object(G,'gamma_environment',return_value={}), \
                patch.object(R,'inspect_parent',side_effect=inspected) as inspection, \
                patch.object(R,'compatible',return_value=[]), \
                patch.object(R,'release',return_value='a'*64), \
                patch.object(workflow,'_launch',side_effect=workflow._view) as dispatch:
            self.assertTrue(workflow.own_busy());self.assertTrue(gamma.own_busy())
            self.assertTrue(gamma.snapshot()['jobs'][0]['can_verify'])
            self.assertEqual(self.request('POST','/api/workflow/continue-prefix',body)[0],400)
            inspection.assert_not_called()
            self.assertEqual(self.request('POST','/api/gamma-start',{'check_id':'unchecked'})[0],400)
            status,raw,_=self.request('POST','/api/gamma-verify',{'job_id':old['id']})
            self.assertEqual(status,200);self.assertEqual(json.loads(raw)['scientific_workers_launched'],0)
            self.assertEqual([call[0] for call in runner.calls],['verify'])
            self.assertFalse(gamma.own_busy());self.assertTrue(workflow.own_busy())
            self.assertEqual(W.read(workflow._state_path)['jobs'][0],original_parent)
            self.assertEqual(self.request('POST','/api/workflow/continue-prefix',body)[0],200)
            inspection.assert_called_once();dispatch.assert_called_once()
            self.assertEqual(parent['status'],'verified_transport')
            self.assertEqual(workflow._jobs[1]['mode'],'continue')
        self.assertFalse(W.run_path(body['new_name'],root).exists())
        self.assertEqual(original_files,{p.relative_to(folder).as_posix():p.read_bytes() for p in folder.rglob('*') if p.is_file()})


if __name__=='__main__':unittest.main()
