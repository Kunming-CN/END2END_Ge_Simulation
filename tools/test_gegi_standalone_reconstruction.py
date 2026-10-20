"""Standalone v3 integration using tiny saved CSVs; never launch Julia/physics."""
import copy
import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import gegi_response as P
import gegi_standalone_reconstruction as G
import scenario_workflow as W


class Standalone(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='gegi-standalone-v3-',dir=W.ROOT/'.local')
        self.addCleanup(self.temp.cleanup);self.base=Path(self.temp.name)

    def native_fixture(self,response):
        response.mkdir(parents=True);(response/'events').mkdir()
        channels=[{'id':i,'wiring_factor':1 if i<=17 else -1,'strip_center_mm':float(i),
                   'name':str(i),'family':'X' if i<=17 else 'Y'} for i in range(1,35)]
        scalar=[{'contact_id':m['id'],'wiring_factor':m['wiring_factor'],'accepted':True,
            'collection_candidate':m['id'] in (1,18),'final_induced_keV':100.*m['wiring_factor'] if m['id'] in (1,18) else 0.,
            'reconstructed_energy_keV':99.5 if m['id'] in (1,18) else 0.,'t50_ns':7.25,'t90_ns':9.,
            'timing_method':'ideal_charge_last_rising_constant_fraction_terminal_v2',
            'saturated':False,'charge_clipped_at_window':False,
            'trace':{'time_ns':[0.,10.],'charge_fC':[0.,-.1234567890123456]}} for m in channels]
        csvpath=response/'events/17-signals.csv'
        with csvpath.open('w',newline='',encoding='utf-8') as stream:
            writer=csv.writer(stream);writer.writerow(['contact_id','time_ns','signed_induced_keV','wired_induced_keV'])
            for c in scalar:
                writer.writerow([c['contact_id'],0.,0.,0.]);writer.writerow([c['contact_id'],10.,c['final_induced_keV'],c['final_induced_keV']*c['wiring_factor']])
        event={'event_id':17,'status':'completed','channels':scalar,'truth_edep_keV':100.,
            'primary_time_ns':0.,'steps':[{'position_mm':[10.,20.,30.],'energy_keV':100.}],
            'signals_ref':'events/17-signals.csv','signals_sha256':W.sha(csvpath)}
        failure={'event_id':49,'status':'native_failed','channels':None,'truth_edep_keV':2.,
                 'signals_ref':None,'signals_sha256':None,'error':'Original native failure retained.'}
        for e in (event,failure):W.write(response/'events'/f'{e["event_id"]}.json',e)
        counts={'initial_primaries':100,'zero_deposit_primaries':98,'nonzero_primaries':2,
                'native_failed_groups':1,'accepted_nonzero_primaries':1,'rejected_nonzero_primaries':0}
        payload={'kind':'gegi_multichannel_results_v1','status':'completed_with_native_failures',
            'configuration_sha256':'a'*64,'channels':channels,'counts':counts,'events':[event,failure],
            'depth_calibration':{'ctd_ns':[999.,-999.],'depth_mm':[-5.,5.]},'limitations':[]}
        artifacts={p.relative_to(response).as_posix():W.sha(p) for p in (csvpath,response/'events/17.json',response/'events/49.json')}
        request={'kind':'gegi_native_request_v1','configuration_sha256':'a'*64,'source_sha256':{},'selection':{'threads':1}}
        receipt={'kind':'gegi_native_response_v1','status':payload['status'],'configuration_sha256':'a'*64,
                 'counts':counts,'channels':channels,'artifacts':artifacts}
        W.write(response/'results.json',payload);receipt['artifacts']['results.json']=W.sha(response/'results.json')
        return payload,receipt,request

    def test_no_bank_preserves_native_readout_ids_failures_and_diagnostics_without_map(self):
        response=self.base/'response';payload,receipt,request=self.native_fixture(response)
        original=copy.deepcopy(payload);before={p.relative_to(response):W.sha(p) for p in response.rglob('*') if p.is_file()}
        G.analyze(payload,response,receipt,request=request)
        self.assertEqual(payload['counts'],original['counts']);self.assertEqual([e['event_id'] for e in payload['events']],[17,49])
        self.assertEqual(payload['events'][0]['channels'],original['events'][0]['channels'])
        self.assertIsNone(payload['events'][1]['channels']);self.assertEqual(payload['depth_calibration'],original['depth_calibration'])
        self.assertEqual(payload['events'][0]['reconstruction']['reason'],'independent_waveform_templates_unavailable')
        self.assertEqual(payload['events'][1]['reconstruction']['status'],'native_failed_or_incomplete')
        self.assertIsNone(payload['imaging']['values']);self.assertEqual(payload['imaging']['cones'],[])
        self.assertEqual(payload['imaging']['validated_recovered_groups'],0)
        self.assertEqual(payload['signal_use_counts'],{'spectroscopy_only':1,'failed_or_incomplete':1})
        use=payload['events'][0]['reconstruction']['signal_use']
        self.assertTrue(use['spectroscopy']['accepted'])
        self.assertIsNone(payload['events'][1]['reconstruction']['signal_use']['spectroscopy']['energy_keV'])
        self.assertEqual(before,{p.relative_to(response):W.sha(p) for p in response.rglob('*') if p.is_file()})

    def test_csv_hash_wiring_and_terminal_charge_changes_are_refused(self):
        response=self.base/'response';payload,receipt,_=self.native_fixture(response);event=payload['events'][0]
        path=response/event['signals_ref'];original=path.read_bytes();path.write_bytes(original+b'\n')
        with self.assertRaisesRegex(W.ControlError,'bytes changed'):G.reconstruct_event_csv(event,payload['channels'],response,receipt['artifacts'])
        path.write_bytes(original);event['channels'][0]['final_induced_keV']+=1
        with self.assertRaisesRegex(W.ControlError,'terminal induced charge'):G.reconstruct_event_csv(event,payload['channels'],response,receipt['artifacts'])
        event['channels'][0]['final_induced_keV']-=1;event['channels'][0]['wiring_factor']=-1
        with self.assertRaisesRegex(W.ControlError,'wiring'):G.reconstruct_event_csv(event,payload['channels'],response,receipt['artifacts'])

    def test_same_shared_algorithm_is_used_and_truth_is_outside_observable_allowlist(self):
        response=self.base/'response';payload,receipt,_=self.native_fixture(response);event=payload['events'][0]
        from gegi_signal_reconstruction import reconstruct_observables
        with patch.object(G.R,'reconstruct_observables',wraps=reconstruct_observables) as shared:
            original=G.reconstruct_event_csv(event,payload['channels'],response,receipt['artifacts'])
        observed=shared.call_args.args[0]
        self.assertEqual(len(observed['channels']),34);self.assertEqual(len(observed['native']),34)
        for key in ('steps','truth_edep_keV','source','depth_calibration','t50_ns'):self.assertNotIn(key,observed)
        changed=copy.deepcopy(event);changed['truth_edep_keV']=1e9;changed['steps']=[{'position_mm':[999.,999.,999.]}]
        for c in changed['channels']:c['t50_ns']=-99999.
        self.assertEqual(original,G.reconstruct_event_csv(changed,payload['channels'],response,receipt['artifacts']))

    def test_new_native_wrapper_never_calls_legacy_imaging(self):
        output=self.base/'response';request_path=self.base/'request.json'
        request={'kind':'gegi_native_request_v1','configuration_sha256':'a'*64,'source_sha256':{},'selection':{'threads':1}}
        W.write(request_path,request);original={}
        def native_worker(*args,**kwargs):
            payload,receipt,_=self.native_fixture(output);original['counts']=copy.deepcopy(payload['counts'])
            original['native_bytes']=(output/'results.json').read_bytes()
            receipt['request_sha256']=W.sha(request_path);W.write(output/'run.json',receipt)
            return Mock(returncode=0)
        with patch.object(P.subprocess,'run',side_effect=native_worker) as worker, \
             patch.object(P.W,'child_env',return_value={'JULIA_EXE':'mock-native-worker'}), \
             patch.object(G.R.I,'analyze',side_effect=AssertionError('Legacy imaging must not run')):
            P.run(request_path,output)
        self.assertEqual(worker.call_count,1)
        result=W.read(output/'results.json');receipt=W.read(output/'run.json')
        self.assertEqual(result['imaging']['method'],G.KIND);self.assertEqual(result['counts'],original['counts'])
        self.assertIsNone(result['imaging']['values']);self.assertEqual(receipt['artifacts']['results.json'],W.sha(output/'results.json'))
        self.assertEqual(receipt['imaging']['status'],'unsupported_independent_waveform_templates')
        self.assertEqual((output/'native-results.json').read_bytes(),original['native_bytes'])
        self.assertEqual(receipt['artifacts']['native-results.json'],W.sha(output/'native-results.json'))
        self.assertEqual(receipt['native_results']['sha256'],receipt['imaging']['input_native_results_sha256'])
        with self.assertRaises(W.ControlError):P.preserve_native_results(output,'0'*64)

    def test_completed_standalone_cli_writes_separate_derivative_and_preserves_old_maps(self):
        run=self.base/'old-run';response=run/'response';payload,receipt,request=self.native_fixture(response)
        legacy={'method':'signal_derived_two_site_compton_backprojection_v2','values':[[1.]],'cones':[]}
        payload['imaging']=legacy;payload['events'][0]['reconstruction']={'status':'accepted','old_depth_mm':1.23}
        W.write(response/'results.json',payload);receipt['artifacts']['results.json']=W.sha(response/'results.json')
        W.write(run/'gegi-request.json',request);receipt['request_sha256']=W.sha(run/'gegi-request.json');W.write(response/'run.json',receipt)
        W.write(run/'COMPLETE.json',{'kind':'local_gegi_workflow_v1','status':'completed_with_native_failures','configuration_sha256':'a'*64,
            'artifacts':{ref:{'sha256':W.sha(run/ref)} for ref in ('response/results.json','response/run.json')}})
        before={p.relative_to(run):W.sha(p) for p in run.rglob('*') if p.is_file()};output=self.base/'derivative'
        with patch.object(P.subprocess,'run',side_effect=AssertionError('No worker is allowed')):
            G.postprocess(run,output)
        result=W.read(output/'results.json')
        self.assertEqual(result['legacy_imaging'],legacy);self.assertEqual(result['events'][0]['legacy_reconstruction']['old_depth_mm'],1.23)
        self.assertEqual(result['counts'],payload['counts']);self.assertIsNone(result['imaging']['values'])
        self.assertEqual(before,{p.relative_to(run):W.sha(p) for p in run.rglob('*') if p.is_file()})
        with self.assertRaises(W.ControlError):G.postprocess(run,output)

    def test_all_zero_native_run_preserves_census_without_fabricated_events(self):
        response=self.base/'response';payload,receipt,_=self.native_fixture(response)
        payload['events']=[];payload['counts']={'initial_primaries':100,'zero_deposit_primaries':100,'nonzero_primaries':0}
        receipt['counts']=payload['counts'];G.analyze(payload,response,receipt)
        self.assertEqual(payload['events'],[]);self.assertEqual(payload['imaging']['initial_primaries'],100)
        self.assertIsNone(payload['imaging']['values'])

    def test_explicit_calibration_requires_exact_model_fields_channels_and_native_grid(self):
        response=self.base/'response';payload,receipt,request=self.native_fixture(response)
        request.update(model_sha256='d'*64,field_cache={'sha256':'e'*64},
                       numerics={'drift_dt_ns':1.,'drift_cap_ns':1000.,'diffusion':False,'self_repulsion':False})
        receipt.update(model_sha256='d'*64,fields={'cache_sha256':'e'*64,'precision_bits':32},
                       source_code_sha256={name:'f'*64 for name in G.A.SHARED_NATIVE},
                       environment={'environment_manifest_sha256':'c'*64,'julia_version':'1.13.0'})
        identity={'kind':'gegi_pixel_calibration_identity_v1','model_sha256':'d'*64,'channels':payload['channels'],
                  'field_cache':{'sha256':'e'*64},'field_precision_bits':32,'numerics':{'dt':1.,'max_steps':1001},
                  'environment':{'manifest_sha256':'c'*64,'julia_version':'1.13.0'},
                  'source_sha256':{name:'f'*64 for name in G.A.SHARED_NATIVE}}
        calibration=self.base/'templates';calibration.mkdir();path=calibration/'identity.json';W.write(path,identity)
        table=calibration/'depth-calibration.json';W.write(table,{'identity_sha256':W.sha(path)})
        sentinel=object()
        with patch.object(G.R,'TemplateBank',return_value=sentinel) as bank:
            self.assertIs(G.compatible_bank(calibration,request,receipt,payload['channels']),sentinel)
            for mutate in (lambda x:x.update(model_sha256='1'*64),lambda x:x['field_cache'].update(sha256='2'*64),
                           lambda x:x['numerics'].update(dt=2.),lambda x:x['channels'].reverse(),
                           lambda x:x['environment'].update(manifest_sha256='3'*64),
                           lambda x:x['source_sha256'].update({'gegi_response.jl':'4'*64})):
                changed=copy.deepcopy(identity);mutate(changed);W.write(path,changed);W.write(table,{'identity_sha256':W.sha(path)})
                with self.assertRaises(W.ControlError):G.compatible_bank(calibration,request,receipt,payload['channels'])
            self.assertEqual(bank.call_count,1)

    @unittest.skipUnless((W.ROOT/'.local/runs/gegi-source-left-v1/response/events/1016.json').is_file(),
                         'Original standalone example is local science, never bundled')
    def test_one_actual_saved_standalone_metadata_csv_pair_without_full_result_load(self):
        response=W.ROOT/'.local/runs/gegi-source-left-v1/response';receipt=W.read(response/'run.json')
        event_path=response/'events/1016.json';event=W.read(event_path)
        self.assertEqual(W.sha(event_path),receipt['artifacts']['events/1016.json'])
        paths=[event_path,response/event['signals_ref']];before={p:W.sha(p) for p in paths}
        result=G.reconstruct_event_csv(event,receipt['channels'],response,receipt['artifacts'])
        self.assertEqual(result['event_id'],1016);self.assertEqual(result['reason'],'independent_waveform_templates_unavailable')
        self.assertEqual(result['candidates'],[]);self.assertEqual(before,{p:W.sha(p) for p in paths})


if __name__=='__main__':unittest.main()
