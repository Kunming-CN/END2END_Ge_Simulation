"""Historical/checkpoint boundaries with synthetic receipts; no science runs."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import scenario_workflow as W


class History(unittest.TestCase):
    def setUp(self):
        base=W.ROOT/'.local/product-delivery-v1/implementation-tests';base.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=base);self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.plan=copy.deepcopy(W.read(W.ROOT/'.local/product-delivery-v1/implementation/M14a1-PREFLIGHT.json'))
        self.plan['resolved']['selection']['name']='historical-synthetic';self.plan['configuration_sha256']=W.digest(self.plan['resolved'])
        self.directory=W.run_path('historical-synthetic',self.root);self.directory.mkdir(parents=True)
        W.write(self.directory/'resolved-config.json',self.plan,fresh=True)
        W.write(self.directory/'electronics/profile.json',self.plan['resolved']['profile'],fresh=True)

    def terminal(self):
        (self.directory/'index.html').write_text('<p>synthetic result-container fixture</p>')
        result={'index.html':{'sha256':W.sha(self.directory/'index.html'),'bytes':(self.directory/'index.html').stat().st_size}}
        stages={stage:{'status':'completed','artifacts':result if stage=='results' else {}} for stage in W.STAGES}
        self.receipt={'kind':W.KIND,'status':'completed','resolved':self.plan['resolved'],
                      'configuration_sha256':self.plan['configuration_sha256'],'stages':stages}
        W.write(self.directory/'run.json',self.receipt,fresh=True)
        W.write(self.directory/'COMPLETE.json',{'kind':W.KIND,'status':'completed','configuration_sha256':self.plan['configuration_sha256'],
            'artifacts':W.inventory(self.directory,exclude=('COMPLETE.json','STOP.json'))},fresh=True)

    def test_historical_inspection_never_readmits_current_sources(self):
        self.terminal()
        with patch.object(W,'admit',side_effect=AssertionError('Historical inspection readmits current source')),patch.object(W,'validate_stage',return_value={}) as validator:
            result=W.inspect('historical-synthetic',self.root)
        self.assertEqual(result['verification'],'terminal_artifacts_verified')
        self.assertTrue(all(call.kwargs=={'historical':True} for call in validator.call_args_list))

    def test_historical_removed_or_changed_artifact_refused(self):
        self.terminal();(self.directory/'index.html').write_text('edited')
        with patch.object(W,'admit',side_effect=AssertionError('Current admission used')),self.assertRaises(W.ControlError):W.inspect('historical-synthetic',self.root)

    def test_current_changed_source_unfinished_admission_still_refuses(self):
        original=W.read(W.ROOT/'.local/product-delivery-v1/implementation/M14a1-PREFLIGHT.json')
        with self.assertRaises(W.ControlError):W.admit(original,resume=True)

    def geometry(self):
        t=self.directory/'transport';t.mkdir()
        W.write(t/'geometry-report.json',{'overlaps_passed':True,'source_inside_fill':True},fresh=True)
        prepared={'model_id':'AK02','instance':{'primary_count':20,'seed':26092631},'source_position_global_mm':[0,42.073,.290],
                  'files_sha256':{'geometry-report.json':W.sha(t/'geometry-report.json')}}
        W.write(t/'prepared.json',prepared,fresh=True);W.write(t/'prepare-receipt.json',{'status':'complete'},fresh=True)
        r={'kind':W.KIND,'status':'stopped','resolved':self.plan['resolved'],'configuration_sha256':self.plan['configuration_sha256'],
           'stages':{'geometry':{'status':'completed','artifacts':W.inventory(t)}}}
        W.write(self.directory/'STOP.json',{'requested_utc':'synthetic'},fresh=True);W.stopped_checkpoint(self.directory,r,self.root)
        return r

    def resume(self):
        def no_dispatch(*a):self.fail('A resume boundary mutant dispatched a worker')
        def commands(*a):W.write(self.directory/'STOP.json',{'requested_utc':'synthetic-next-boundary'},fresh=True);return {}
        with patch.object(W,'admit',return_value=self.plan),patch.object(W,'verify_pins'),patch.object(W,'child_env',return_value={'JULIA_EXE':__file__}),patch.object(W,'stage_commands',side_effect=commands):
            return W.execute(self.plan,root=self.root,resume=True,executor=no_dispatch)

    def test_unchanged_checkpoint_revalidates_then_stops_at_next_boundary(self):
        self.geometry();result=self.resume();self.assertEqual(result['status'],'stopped');self.assertEqual(set(result['stages']),{'geometry'})

    def test_rehashed_prepared_model_refused_by_checkpoint(self):
        r=self.geometry();p=W.read(self.directory/'transport/prepared.json');p['model_id']='SAP22';W.write(self.directory/'transport/prepared.json',p)
        r['stages']['geometry']['artifacts']=W.inventory(self.directory/'transport');W.write(self.directory/'run.json',r)
        with self.assertRaises(W.ControlError):self.resume()

    def test_rehashed_prepared_model_also_has_independent_semantic_refusal(self):
        r=self.geometry();p=W.read(self.directory/'transport/prepared.json');p['model_id']='SAP22';W.write(self.directory/'transport/prepared.json',p)
        r['stages']['geometry']['artifacts']=W.inventory(self.directory/'transport');W.write(self.directory/'run.json',r)
        with patch.object(W,'verify_checkpoint'),self.assertRaises(W.ControlError):self.resume()

    def test_removed_stage_inventory_refused_independently(self):
        r=self.geometry();r['stages']['geometry']['artifacts']={};W.write(self.directory/'run.json',r)
        with patch.object(W,'verify_checkpoint'),self.assertRaises(W.ControlError):self.resume()

    def test_geometry_inventory_ignores_later_stage_owned_files(self):
        r=self.geometry();(self.directory/'transport/run.log').write_text('synthetic later-stage artifact')
        actual=W.validate_stage(self.directory,'geometry',self.plan['resolved'],self.root)
        self.assertEqual(actual,r['stages']['geometry']['artifacts'])

    def test_historical_normalized_numbers_accept_but_boolean_settings_refuse(self):
        W.saved_plan(self.plan)
        altered=copy.deepcopy(self.plan);altered['resolved']['profile']['settings']['threshold_V']=False
        altered['configuration_sha256']=W.digest(altered['resolved'])
        with self.assertRaises(W.ControlError):W.saved_plan(altered)

    def test_historical_gamma_ledger_keeps_validation_but_skips_current_producers(self):
        t=self.directory/'transport';stream=t/'stream';stream.mkdir(parents=True)
        (t/'truth.lh5').write_bytes(b'Synthetic binding fixture, not radiation data');W.write(t/'run.json',{'status':'complete','returncode':0},fresh=True)
        assets={'source':{'id':W.GAMMA}};prepared={'assets':assets,'coordinate_transform':{}}
        W.write(t/'prepared.json',prepared,fresh=True)
        (stream/'events.jsonl').write_text('{}\n'*20)
        manifest={'kind':'scenario_gamma_event_stream_v1','status':'complete','model_id':'AK02','primary_count':20,'assets':assets,'coordinate_transform':{},
            'prepared_sha256':W.sha(t/'prepared.json'),'run_sha256':W.sha(t/'run.json'),'source_lh5_sha256':W.sha(t/'truth.lh5'),
            'source_position_global_mm':[0,42.073,.290],'prepared_source_sha256':{'obsolete-producer.py':'a'*64},'transport_source_sha256':{},
            'chunks':[{'count':20,'file':'events.jsonl','sha256':W.sha(stream/'events.jsonl')}]}
        W.write(stream/'manifest.json',manifest,fresh=True)
        with patch('gamma_native_example.validate_events') as validator:
            request=W.gamma_request(self.directory,self.plan['resolved'],self.root,historical=True)
            validator.assert_called_once();self.assertEqual(len(request['events']),20)
        with patch('gamma_native_example.validate_events'),self.assertRaises(FileNotFoundError):W.gamma_request(self.directory,self.plan['resolved'],self.root)


if __name__=='__main__':unittest.main()
