"""Saved-results fixtures only: no workers, science, calibration or servers."""
import copy
import io
import json
from pathlib import Path
import shutil
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch

import scenario_workflow as W
import workflow_finalize as F
import local_ui_workflow_jobs as J
import test_ring_workflow as T


class Finalization(unittest.TestCase):
    # Reuse fixture builders, without rerunning the inherited ring test methods.
    setUpClass=T.Rings.__dict__['setUpClass']
    setUp=T.Rings.setUp
    plan=T.Rings.plan
    geometry=T.Rings.geometry
    stream=T.Rings.stream
    readout=T.Rings.readout

    def fixture(self):
        directory,plan,report,rows=self.readout('GeRC02');r=plan['resolved'];out=directory/'response'
        report.update(model_id='GeRC02',stored_temperature_K=78,temperature_K=77,bias_V=240,parcels=16,seed_family=2609261,
            input_sha256=W.sha(directory/'transport/stream/manifest.json'),profile_sha256=W.sha(directory/'electronics/profile.json'),
            source_sha256={ref[len('simulation/'):]:h for ref,h in r['source_sha256'].items() if ref.startswith('simulation/')})
        config=dict(r['electronics_configuration'],expected_primary_count=20)
        for key in ('calibration_energy_keV','max_window_ns','tail_shaping_constants'):config[key]=float(config[key])
        W.write(out/'readout-config.json',config)
        (out/'scalars.csv').write_text('SYNTHETIC FIXTURE CSV\n',encoding='utf-8');(out/'summary.html').write_text('Synthetic fixture summary',encoding='utf-8')
        report['artifacts']={p.name:W.sha(p) for p in out.iterdir() if p.name not in ('run.json','workflow-ring-response.json')}
        W.write(out/'run.json',report);env=W.read(out/'workflow-ring-response.json');env['native_report_sha256']=W.sha(out/'run.json');W.write(out/'workflow-ring-response.json',env)
        for ref in set(r['source_sha256'])|set(F.VALIDATORS):
            path=W.safe_path(self.root,ref);path.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(W.safe_path(W.ROOT,ref),path)
        W.write(directory/'resolved-config.json',plan)
        commands=W.stage_commands(directory,r,self.root,{'JULIA_EXE':r['runtime_identity']['julia_executable']})
        (directory/'transport/run.log').write_text('SYNTHETIC radiation log',encoding='utf-8')
        stages={}
        for i,stage in enumerate(W.STAGES[:-1]):
            (directory/(stage+'.log')).write_text('SYNTHETIC ended stage '+stage,encoding='utf-8')
            stages[stage]={'status':'command_exited' if stage=='response' else 'completed','exit_code':0,
                'pid':999991+i,'process_identity':'synthetic-ended-'+stage,'arguments':commands[stage],'elapsed_seconds':i+1,
                'started_utc':'synthetic','finished_utc':'synthetic'}
            if stage!='response':stages[stage]['artifacts']=W.validate_stage(directory,stage,r,self.root,historical=True)
        receipt={'kind':W.KIND,'status':'failed','error':F.ERROR,'resolved':r,'configuration_sha256':plan['configuration_sha256'],
            'stages':stages,'supervisor':{'pid':999990,'identity':'synthetic-ended-driver'},'runtime':{'julia':r['runtime_identity']['julia_executable']}}
        W.write(directory/'run.json',receipt)
        job={'id':'a'*32,'name':directory.name,'status':'dispatch_uncertain','plan':plan,'driver':receipt['supervisor'],
             'mode':'run','created_utc':'synthetic'}
        W.write(self.root/'.local/local-control-v1/workflow-jobs.json',{'kind':'local_workflow_jobs_v1','jobs':[job]})
        basis={'kind':'m14a2_ge_completed_science_validation_failure_basis_v1','run':W.BASE+'/'+directory.name,
            'original_run_sha256':W.sha(directory/'run.json'),'science_report_sha256':W.sha(out/'run.json'),'original_inventory':W.inventory(directory)}
        W.write(self.root/F.BASIS,basis,fresh=True)
        for key,value in (('RUN_NAME',directory.name),('BASIS_SHA',W.sha(self.root/F.BASIS))):
            scoped=patch.object(F,key,value);scoped.start();self.addCleanup(scoped.stop)
        self.quiet={'windows_succeeded':True,'linux_succeeded':True,'relevant_windows_workers':[],'relevant_linux_workers':[]}
        return directory,plan,report,receipt,job

    def test_explicit_finalization_preserves_science_and_failed_receipt(self):
        directory,plan,report,receipt,job=self.fixture();before=W.inventory(directory);body=(directory/'run.json').read_bytes()
        with patch.object(W,'process_identity',return_value=None),patch.object(W,'command',side_effect=AssertionError('Science dispatched')),patch.object(W,'admit',side_effect=AssertionError('Historical plan readmitted')):
            done=F.finalize(directory.name,self.root,probe=lambda root:self.quiet)
        self.assertEqual(done['status'],'completed');self.assertEqual(done['counts'],report['counts'])
        self.assertEqual((self.root/F.STATE/directory.name/'original-run.json').read_bytes(),body)
        for file,stamp in before.items():
            if file!='run.json':self.assertEqual(W.inventory(directory)[file],stamp)
        self.assertEqual(set(W.inventory(directory))-set(before),{'index.html','COMPLETE.json'})
        self.assertEqual(done['stages']['response']['elapsed_seconds'],4)
        self.assertEqual(W.read(self.root/'.local/local-control-v1/workflow-jobs.json')['jobs'][0]['status'],'completed')
        with self.assertRaises(W.ControlError):F.finalize(directory.name,self.root,probe=lambda root:self.quiet)
        (self.root/F.STATE/directory.name/'original-run.json').write_bytes(b'changed original failure')
        with self.assertRaises(W.ControlError):W.inspect(directory.name,self.root)

    def test_unknown_live_and_inventory_failures_do_not_write(self):
        directory,*_=self.fixture();before=W.inventory(directory)
        for identity in ('unknown','synthetic-ended-driver','synthetic-ended-response'):
            with patch.object(W,'process_identity',return_value=identity),self.assertRaises(W.ControlError):F.finalize(directory.name,self.root,probe=lambda root:self.quiet)
        for key,value in (('windows_succeeded',False),('linux_succeeded',False),('relevant_windows_workers',[{'pid':12}]),('relevant_linux_workers',[{'pid':13}])):
            with patch.object(W,'process_identity',return_value=None),self.assertRaises(W.ControlError):F.finalize(directory.name,self.root,probe=lambda root:dict(self.quiet,**{key:value}))
        self.assertEqual(before,W.inventory(directory));self.assertFalse((self.root/F.STATE).exists())

    def test_terminal_exit_dispatch_and_producer_tampering_refused(self):
        directory,plan,report,receipt,job=self.fixture();path=directory/'run.json'
        for mutate in (lambda r:r.update(error='Unexpected exception'),lambda r:r['stages']['response'].update(exit_code=1),
                       lambda r:r['stages']['response'].update(status='running'),lambda r:r['stages']['response']['arguments'].append('--extra'),
                       lambda r:r['stages']['geometry']['artifacts'].pop('prepared.json'),lambda r:r['resolved']['selection'].update(seed=999)):
            other=copy.deepcopy(receipt);mutate(other);W.write(path,other)
            with patch.object(W,'process_identity',return_value=None),self.assertRaises((W.ControlError,KeyError)):F.finalize(directory.name,self.root,probe=lambda root:self.quiet)
        W.write(path,receipt);source=self.root/'simulation/readout.jl';source.write_bytes(source.read_bytes()+b'changed')
        with patch.object(W,'process_identity',return_value=None),self.assertRaises(W.ControlError):F.finalize(directory.name,self.root,probe=lambda root:self.quiet)
        self.assertFalse((directory/'index.html').exists());self.assertFalse((self.root/F.STATE).exists())

    def test_rehashed_response_truth_and_exact_config_types_refused(self):
        directory,plan,report,receipt,job=self.fixture();out=directory/'response';config=W.read(out/'readout-config.json')
        W.validate_stage(directory,'response',plan['resolved'],self.root,historical=True)
        for key,value in (('schema_version',2.0),('require_all_events',1),('expected_primary_count',20.0),
                          ('calibration_energy_keV',True),('tail_shaping_constants',21),('gain',22)):
            other=dict(config,**{key:value});W.write(out/'readout-config.json',other)
            with self.subTest(key=key),self.assertRaises(W.ControlError):W.validate_stage(directory,'response',plan['resolved'],self.root,historical=True)
        W.write(out/'readout-config.json',config);rows=[W.decode_json(v) for v in (out/'scalars.jsonl').read_text().splitlines()]
        rows[1]['deposited_energy_keV']+=.01;(out/'scalars.jsonl').write_text(''.join(W.encoded(r).decode()+'\n' for r in rows),encoding='utf-8')
        report['artifacts']['scalars.jsonl']=W.sha(out/'scalars.jsonl');W.write(out/'run.json',report);envelope=W.read(out/'workflow-ring-response.json');envelope['native_report_sha256']=W.sha(out/'run.json');W.write(out/'workflow-ring-response.json',envelope)
        with patch.object(W,'process_identity',return_value=None),self.assertRaises(W.ControlError):F.finalize(directory.name,self.root,probe=lambda root:self.quiet)

    def test_controller_and_cli_share_closed_saved_data_entry(self):
        directory,plan,report,receipt,job=self.fixture();controller=J.WorkflowController(self.root,launcher=lambda *a:self.fail('Launched worker'))
        self.assertTrue(controller.snapshot()['jobs'][0]['can_finalize_results'])
        def settled(name,root):
            self.assertTrue(W.lease_busy(root) is False)
            state=W.read(controller._state_path);state['jobs'][0]['status']='completed';W.write(controller._state_path,state)
            return {'status':'completed'}
        with patch.object(F,'finalize',side_effect=settled):self.assertEqual(controller.finalize_results(directory.name)['status'],'completed')
        with patch.object(F,'finalize',return_value={'science_calls':0}) as finalize,patch('builtins.print'):
            W.main(['finalize-results','--name',directory.name]);finalize.assert_called_once_with(directory.name)

    def test_all_four_rehashed_review_probes_fail_full_stage_validation(self):
        directory,plan,report,receipt,job=self.fixture();out=directory/'response'
        rows=[W.decode_json(v) for v in (out/'scalars.jsonl').read_text().splitlines()]
        traces=(out/'traces.jsonl').read_bytes();original_report=copy.deepcopy(report)
        def bind():
            report['artifacts']={p.name:W.sha(p) for p in out.iterdir() if p.name not in ('run.json','workflow-ring-response.json')}
            W.write(out/'run.json',report);envelope=W.read(out/'workflow-ring-response.json')
            envelope.update(native_report_sha256=W.sha(out/'run.json'),counts=report['counts'],status=report['status']);W.write(out/'workflow-ring-response.json',envelope)
        for probe in ('primary','counts','trace','failed-unknowns'):
            report=copy.deepcopy(original_report);altered=copy.deepcopy(rows);(out/'traces.jsonl').write_bytes(traces)
            if probe=='primary':altered[3].update(global_decay_id=666,deposited_energy_keV=12,zero_deposit=False,pulse_count=99,raw_row_indices=[999])
            if probe=='counts':report['counts'].update(zero_deposit_primaries=0,initial_decays=999,line_photons=999,decay_photons=999)
            if probe=='trace':
                values=[W.decode_json(v) for v in traces.decode().splitlines()];values[0].update(event_id=999,global_decay_id=999,group_id=999)
                (out/'traces.jsonl').write_text(''.join(W.encoded(v).decode()+'\n' for v in values),encoding='utf-8')
            if probe=='failed-unknowns':
                altered[1].update(status='native_transport_failed',accepted=False,readout=None,final_induced_keV=None,transport_flags=None,
                    native_error={'type':'ArgumentError','message':'Invalid waveform support'},charge_end_ns=0,endpoints=[],current_nA=[0],induced_charge_fC=[0],trace_saved=True)
                report['counts'].update(accepted=1,rejected=1,native_failed_groups=1);report['status']='completed_with_native_failures'
            (out/'scalars.jsonl').write_text(''.join(W.encoded(v).decode()+'\n' for v in altered),encoding='utf-8');bind()
            with self.subTest(probe=probe),self.assertRaises(W.ControlError):W.validate_stage(directory,'response',plan['resolved'],self.root,historical=True)

    def test_finalization_handler_auth_and_fields_without_a_server(self):
        import local_ui as U
        backend=Mock();backend.finalize_results.return_value={'status':'completed','science_calls':0}
        def request(data,headers=None):
            body=json.dumps(data).encode();h=object.__new__(U.Handler)
            h.path='/api/workflow/finalize-results';h.server=SimpleNamespace(origin='http://127.0.0.1:9999',token='session',workflow_controller=backend)
            h.headers={'Host':'127.0.0.1:9999','Origin':h.server.origin,'X-Control-Token':'session','Content-Type':'application/json','Content-Length':str(len(body))}
            h.headers.update(headers or {});h.rfile=io.BytesIO(body);h.send_data=Mock();h.do_POST()
            return h.send_data.call_args.args[0]
        for headers in ({'X-Control-Token':''},{'Host':'evil.example'},{'Origin':'https://evil.example'},{'Origin':None},{'Sec-Fetch-Site':'cross-site'},
                        {'X-Control-Token':'','Cookie':'read-only-cookie'}):self.assertEqual(request({'name':'saved'},headers),403)
        for data in ({'name':True},{'name':'saved','retry':True},[]):self.assertEqual(request(data),400)
        backend.finalize_results.assert_not_called();self.assertEqual(request({'name':'saved'}),200)
        backend.finalize_results.assert_called_once_with(name='saved')

    def test_rehashed_immutable_basis_cannot_grant_rights(self):
        directory,*_=self.fixture();path=self.root/F.BASIS;basis=W.read(path)
        (directory/'response.log').write_text('rehashed false ended log',encoding='utf-8');basis['original_inventory']=W.inventory(directory);W.write(path,basis)
        with patch.object(W,'process_identity',return_value=None),self.assertRaises(W.ControlError):F.finalize(directory.name,self.root,probe=lambda root:self.quiet)
        self.assertFalse((directory/'COMPLETE.json').exists())


if __name__=='__main__':
    unittest.main()
