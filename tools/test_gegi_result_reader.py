"""Exact bounded GeGI ranges and closed UI requests; synthetic data only."""
import copy
import hashlib
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock,patch

import gegi_result_reader as G
import local_ui as U
import local_ui_workflow_jobs as J
import scenario_workflow as W


class ResultReader(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='gegi-bounded-reader-',dir=W.ROOT/'.local')
        self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.path=self.root/'results.json';self.seal=self.root/'COMPLETE.json'
        self.payload={'kind':'gegi_multichannel_results_v1','status':'completed_with_native_failures',
            'configuration_sha256':'a'*64,'channels':[{'id':i,'name':str(i)} for i in range(1,35)],
            'counts':{'initial_primaries':100,'zero_deposit_primaries':98,'nonzero_primaries':2,'native_failed_groups':1},
            'events':[{'event_id':17,'status':'completed','truth_edep_keV':1.0000000000000002,
                       'channels':[{'contact_id':i,'trace':{'time_ns':[0.,1.,2.],
                           'charge_fC':[-0.,-.1234567890123456,-2.]}} for i in range(1,35)],
                       'reconstruction':{'kind':'updated_aggregate','depth_mm':1.2345678901234567},
                       'signals_ref':'events/17-signals.csv','text':'Braces {} [] and escaped quote " and slash \\ é'},
                      {'event_id':49,'status':'native_failed','truth_edep_keV':2.,'channels':None,'signals_ref':None,
                       'reconstruction':{'status':'native_failed_or_incomplete','energy_keV':None}}],
            'imaging':{'values':[[1.,-0.]],'cones':[{'event_id':17,'angle_rad':.1234567890123456}]},
            'legacy_imaging':{'values':[[999.]]},'limitations':['Saved finite fixture.'],
            'reconstruction_algorithm':{'kind':'standalone-saved-fixture'},'signal_use_counts':{'spectroscopy_only':1}}
        self.save()

    def save(self):
        self.path.write_bytes(W.encoded(self.payload)+b'\n')
        self.sha=W.sha(self.path);self.seal.write_text(self.sha,encoding='utf-8')

    def reader(self,derivative=None):
        return G.Reader(self.path,self.sha,name='owned',configuration_sha256='a'*64,
                        derivative=derivative,seal_paths=[self.seal])

    def test_exact_event_reconstruction_signed_samples_nulls_and_lazy_imaging(self):
        reader=self.reader('derived');summary=reader.summary()
        self.assertNotIn('events',summary);self.assertNotIn('imaging',summary);self.assertNotIn('legacy_imaging',summary)
        self.assertEqual([e['event_id'] for e in summary['event_index']],[17,49])
        self.assertEqual(summary['counts'],self.payload['counts']);self.assertEqual(summary['channels'],self.payload['channels'])
        self.assertEqual(reader.event(17)['event'],self.payload['events'][0])
        self.assertEqual(reader.event(49)['event'],self.payload['events'][1])
        self.assertEqual(reader.imaging()['imaging'],self.payload['imaging'])
        for response in (summary,reader.event(17),reader.imaging()):
            self.assertEqual((response['name'],response['configuration_sha256'],response['saved_derivative_name'],response['results_sha256']),
                             ('owned','a'*64,'derived',self.sha))
        self.assertEqual(reader.index['scan_bytes'],self.path.stat().st_size)
        self.assertLessEqual(reader.index['peak_scan_buffer_bytes'],G.BLOCK)

    def test_chunk_boundaries_and_escaped_strings_preserve_exact_ranges(self):
        with patch.object(G,'BLOCK',19):reader=self.reader()
        self.assertEqual(reader.event(17)['event'],self.payload['events'][0])
        self.assertEqual(reader.imaging()['imaging'],self.payload['imaging'])
        self.assertLessEqual(reader.index['peak_scan_buffer_bytes'],19)

    def test_index_skips_large_waveforms_and_imaging_without_json_parsing_them(self):
        self.payload['events'][0]['channels'][0]['trace']['time_ns']=list(range(20000))
        self.payload['imaging']['values']=[list(range(20000))];self.save()
        original=json.loads;sizes=[]
        def load(body,*args,**kwargs):sizes.append(len(body));return original(body,*args,**kwargs)
        with patch.object(G.json,'loads',side_effect=load):reader=self.reader()
        self.assertLess(max(sizes),10000)
        with patch.object(G,'scan',side_effect=AssertionError('No repeated full-file scan')), \
             patch.object(W,'sha',wraps=W.sha) as digest:
            self.assertEqual(reader.event(49)['event']['event_id'],49)
            reader.summary();reader.imaging()
        self.assertTrue(all(call.args[0]==self.seal for call in digest.call_args_list))

    def test_changed_source_and_changed_small_seal_fail(self):
        reader=self.reader();self.path.write_bytes(self.path.read_bytes()+b' ')
        with self.assertRaisesRegex(W.ControlError,'source or completion seal changed'):reader.event(17)
        self.save();reader=self.reader();self.seal.write_text('0'*64,encoding='utf-8')
        with self.assertRaisesRegex(W.ControlError,'source or completion seal changed'):reader.summary()

    def test_each_selected_range_is_independently_hash_checked(self):
        reader=self.reader();body=self.path.read_bytes().replace(b'updated_aggregate',b'changed_aggregate')
        self.path.write_bytes(body)
        # Simulate unchanged external file metadata; the selected range still
        # has its independently recorded digest from the sealed original scan.
        reader.index['source_state']=G.file_state(self.path)
        with self.assertRaisesRegex(W.ControlError,'Selected saved GeGI bytes changed'):reader.event(17)

    def test_unknown_event_wrong_open_version_and_limits_fail(self):
        reader=self.reader()
        for action in (lambda:reader.event(0),lambda:reader.event(True),lambda:reader.summary('0'*64),lambda:reader.imaging('0'*64)):
            with self.assertRaises(W.ControlError):action()
        with patch.object(G,'MAX_PART',16):
            with self.assertRaisesRegex(W.ControlError,'viewer limit'):reader.event(17)

    def test_zero_event_census_and_rehashed_duplicate_or_missing_census_fail(self):
        self.payload['events']=[];self.payload['counts'].update(zero_deposit_primaries=100,nonzero_primaries=0)
        self.save();self.assertEqual(self.reader().summary()['event_index'],[])
        self.payload['counts']['nonzero_primaries']=1;self.save()
        with self.assertRaisesRegex(W.ControlError,'census changed'):self.reader()

    def test_original_owned_controller_caches_reader_and_refuses_unowned_derivative(self):
        workflow=J.WorkflowController(self.root)
        job={'name':'owned','status':'completed','plan':{'kind':J.GEGI_KIND,'configuration_sha256':'a'*64}}
        workflow._jobs=[job];backend=Mock();backend.result_reader.return_value=self.reader()
        with patch.object(J,'gegi_backend',return_value=backend):
            workflow.gegi_browse('owned','summary');workflow.gegi_browse('owned','event',event_id=17,results_sha256=self.sha)
            workflow.gegi_browse('owned','imaging',results_sha256=self.sha)
            backend.result_reader.assert_called_once_with('owned',self.root)
            backend.result_view.assert_not_called()
            with self.assertRaises(W.ControlError):workflow.gegi_browse('unknown','summary')
            with self.assertRaises(W.ControlError):workflow.gegi_browse('owned','summary',derivative='unknown')


class Protocol(unittest.TestCase):
    def setUp(self):
        self.workflow=Mock();self.server=U.Server(0,Mock(root=W.ROOT),token='bounded-fixture',workflow_controller=self.workflow)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.addCleanup(self.close)

    def close(self):self.server.shutdown();self.server.server_close();self.thread.join()

    def request(self,path,token=True):
        headers={'Host':'127.0.0.1:'+str(self.server.server_port)}
        if token:headers['X-Control-Token']=self.server.token
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
        connection.request('GET',path,headers=headers);response=connection.getresponse();body=response.read();connection.close()
        return response.status,json.loads(body)

    def test_three_routes_bind_original_derivative_event_version_and_authentication(self):
        self.workflow.gegi_browse.return_value={'kind':'bounded_fixture'}
        for part in ('summary','event','imaging'):
            suffix='&event=49' if part=='event' else ''
            path='/api/workflow/gegi-'+part+'?name=owned&derivative=derived&results_sha256='+'a'*64+suffix
            self.assertEqual(self.request(path),(200,{'kind':'bounded_fixture'}))
            self.workflow.gegi_browse.assert_called_with('owned',part,event_id=49 if part=='event' else None,
                                                       derivative='derived',results_sha256='a'*64)
            self.assertEqual(self.request(path,token=False)[0],403)
        self.workflow.gegi_results.assert_not_called();self.workflow.gegi_saved_results.assert_not_called()

    def test_bounded_routes_reject_extra_paths_event_aliases_and_bad_versions(self):
        routes=('/api/workflow/gegi-summary?name=owned&file=private',
                '/api/workflow/gegi-summary?name=owned&name=other',
                '/api/workflow/gegi-summary?name=owned&derivative=../private',
                '/api/workflow/gegi-summary?name=owned&results_sha256=wrong',
                '/api/workflow/gegi-summary?name=owned&event=49',
                '/api/workflow/gegi-event?name=owned',
                '/api/workflow/gegi-event?name=owned&event=049',
                '/api/workflow/gegi-event?name=owned&event=-1',
                '/api/workflow/gegi-event?name=owned&event=9007199254740992')
        for path in routes:self.assertEqual(self.request(path)[0],400,path)
        self.workflow.gegi_browse.assert_not_called()


if __name__=='__main__':unittest.main()
