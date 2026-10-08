"""Focused injected batch acceptance. No Geant4, SSD or calibration runs."""
from contextlib import nullcontext
import copy, itertools, json, math, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import batch_execution as E
import scenario_workflow as W
import workflow_batches as B
import decay_workflow as D

class Execution(unittest.TestCase):
    def setUp(self):
        base=W.ROOT/'.local/student-batches-v1/execution-v1/test-work';base.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=base);self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        (self.root/'fixture.txt').write_text('source fixture')
        self.settings=W.read(W.ROOT/'simulation/native_readout_profile.json')['settings']
        self.selection=dict(name='fixture',cryostat=W.CRYOSTAT,detector='AK02',source=W.CS,pose='nominal',primary_count=3,seed=42,threads=2,electronics=self.settings)
        self.operating=D.operating('AK02');self.model=D.model_contract('AK02')
        self.sources=D.presets();self.calls=[]
        self.readers=dict(validate_settings=self.electronics,pin_reader=lambda m,r:{'fixture.txt':W.sha(self.root/'fixture.txt')},
            runtime_reader=lambda n:{'python_sha256':'a'*64,'julia_sha256':'b'*64},transport_reader=self.transport)
        self.plan=self.check();self.directory=W.run_path('fixture',self.root)
        self.patches=[patch.object(W,'identity_ended',return_value=True),patch.object(W,'verify_dispatch_reservations')]
        for p in self.patches:p.start();self.addCleanup(p.stop)

    def electronics(self,values,root):
        return {'profile':dict(schema_version=2,kind='native_readout_profile_v1',name='fixture',settings=copy.deepcopy(values)),
            'configuration':dict(values,schema_version=2,calibration_energy_keV=500,expected_primary_count=None,max_samples_per_event=500000,
                max_window_ns=1000000,require_all_events=True,tail_shaping_constants=20,trace_max_points=600),'physics_sha256':'c'*64}

    def transport(self,selection,root):
        bounded=copy.deepcopy(selection);bounded['primary_count']=20
        if selection['detector'] in W.MODELS:
            legacy=dict(kind=('sap18_source_checked_plan_v1' if selection['detector']==W.SAP18 else 'portable_source_checked_plan_v1') if selection['source']==W.CS else 'decay_source_checked_plan_v1',schema_version=1,
                request=W.portable_request(bounded),portable_source_sha256={},runtime={})
            if selection['source']!=W.CS:legacy.update(source_contract=D.preset(selection['source'],W.ROOT),placement_contract=D.anchors(W.ROOT))
        else:
            mc=dict(self.model,model_id=selection['detector'],model_ref='models/'+selection['detector']+'.yaml',model_sha256='e'*64,
                wiring_factor=1,bias_span_V=2000,stored_temperature_K=78,runtime_temperature_K=78,placement={'blocking_reasons':[]})
            legacy=dict(kind='catalog_source_checked_v1',selection=bounded,model_contract=mc,source_position_global_mm=[0,37.073,.290],source_sha256={},runtime={})
        return dict(kind='batch_transport_checked_v1',schema_version=1,selection=copy.deepcopy(selection),geometry_preparation_count=20,legacy_geometry_plan=legacy,runtime={})

    def check(self,selection=None):
        selection=selection or self.selection
        acceptance=dict(kind='bounded_batch_acceptance_v1',batch_cap=2,primary_count=selection['primary_count'],selection_sha256=W.digest(selection)) if selection['primary_count']<=500 else None
        with patch.object(D,'operating',return_value=self.operating),patch.object(D,'presets',return_value=self.sources),patch.object(D,'anchors',return_value=D.anchors(W.ROOT)),patch.object(D,'capability',return_value={'accepted':True}):
            return E.check(selection,root=self.root,acceptance=acceptance,**self.readers)

    def execute(self,*,resume=False,worker=None,after_seal=None):
        return E.execute(self.plan,root=self.root,resume=resume,executor=worker or self.worker,
            admitter=lambda p,r,**kw:p,lease=lambda r:nullcontext(),after_seal=after_seal)

    def rows(self,batch):
        for local in range(batch['primary_count']):
            globalid=batch['global_initial_offset']+local;nonzero=globalid in (0,2)
            step=dict(raw_row_index=0,energy_keV=500.,time_ns=120.)
            group=dict(group_id=0,origin_time_ns=120.,row_indices=[0],horizon_ns=100000.)
            yield dict(event_id=local,global_decay_id=local,batch_index=batch['batch_index'],local_initial_id=local,global_initial_id=globalid,
                steps=[step] if nonzero else [],pulse_groups=[group] if nonzero else [],line_photon_count=1,decay_photon_count=1,
                material_energy_keV={'HPGe':500. if nonzero else 0.})

    def write_lines(self,path,rows):
        with path.open('x',encoding='utf-8') as out:
            for row in rows:out.write(W.encoded(row).decode()+'\n')

    def worker(self,stage,plan,directory,batch,root):
        self.calls.append((stage,None if batch is None else batch['batch_index']));base=E.stage_base(directory,stage,batch)
        if stage=='results':return E.export_results(plan,directory)
        base.mkdir(parents=True)
        if stage=='geometry':
            result=dict(kind='batch_shared_transport_prepared_v1',status='complete',checked_transport=plan['resolved']['transport_plan'],model_contract=self.model,files_sha256={})
            W.write(base/'prepared.json',result);return result
        if stage=='native_preparation':
            request=E.native_request(plan,directory,root);W.write(directory/'native-prepare-request.json',request)
            (base/'state.bin').write_bytes(b'owned fake native state, never deserialized')
            cal=dict(energy_keV=500,time_step_ns=2,ionisation_energy_eV=2.96,charge_C=500000/2.96*1.602176634e-19,peak_V=1.,volts_per_keV=.002)
            result={k:request[k] for k in ('parent_configuration_sha256','shared_prepared_sha256','profile_sha256','source_sha256','numerics','operating_model')}
            result.update(kind='batch_native_preparation_v1',status='complete',model_contract=self.model,request_sha256=W.sha(directory/'native-prepare-request.json'),
                independent_calibration_calls=1,state_sha256=W.sha(base/'state.bin'),field_fingerprint={'fixture':'sealed'},calibration=cal,
                artifacts={'state.bin':W.sha(base/'state.bin')})
            W.write(base/'preparation.json',result);return result
        if stage=='radiation':
            (base/'run.mac').write_text('/run/beamOn '+str(batch['primary_count'])+'\n')
            result=dict(status='complete',number_of_simulated_events=batch['primary_count'],initial_ledger_count=batch['primary_count'])
            W.write(base/'run.json',result);return result
        if stage=='event_ledger':
            self.write_lines(base/'chunk.jsonl',self.rows(batch))
            result=dict(batch=batch,primary_count=batch['primary_count'],chunks=[dict(file='chunk.jsonl',first_global_decay_id=0,count=batch['primary_count'],sha256=W.sha(base/'chunk.jsonl'))])
            W.write(base/'manifest.json',result);return result
        request=E.native_request(plan,directory,root,batch);W.write(E.batch_directory(directory,batch['batch_index'])/'native-request.json',request)
        prep=W.read(directory/'shared/native/preparation.json');scalars=[];counts=dict(initial_primaries=batch['primary_count'],initial_decays=batch['primary_count'],zero_deposit_primaries=0,
            groups=0,accepted=0,rejected=0,native_failed_groups=0,readout_rejected=0,line_photons=batch['primary_count'],decay_photons=batch['primary_count'])
        bins={}
        def histogram(stage,value):
            bin=-1 if value< -1000 else 1000 if value>=4000 else math.floor((value+1000)/5)
            bins[stage,bin]=bins.get((stage,bin),0)+1
        for truth in self.rows(batch):
            ids={k:truth[k] for k in ('event_id','global_decay_id','batch_index','local_initial_id','global_initial_id')};energy=500. if truth['steps'] else 0.
            counts['zero_deposit_primaries']+=energy==0
            scalars.append(dict(ids,record_kind='decay',group_id=None,deposited_energy_keV=energy,pulse_count=len(truth['pulse_groups']),zero_deposit=energy==0,
                raw_row_indices=[s['raw_row_index'] for s in truth['steps']],line_photon_count=1,decay_photon_count=1,material_energy_keV=truth['material_energy_keV']))
            histogram('deposited_per_decay',energy)
            for group in truth['pulse_groups']:
                failed=truth['global_initial_id']==2;counts['groups']+=1;counts['accepted']+=not failed;counts['rejected']+=failed;counts['native_failed_groups']+=failed
                scalar=dict(ids,record_kind='pulse',group_id=0,group=group,origin_time_ns=120.,raw_row_indices=[0],deposited_energy_keV=500.,accepted=not failed,
                    final_induced_keV=-400.,transport_flags={},charge_end_ns=240.,native_any_negative_charge=True,native_min_charge_keV=-400.,native_max_charge_keV=0.,readout={'accepted':True})
                if failed:
                    scalar.update(status='native_transport_failed',rejection_reason='native_transport_failed',native_error={'type':'NativeBoundaryStall','raw':'exact error'})
                    for key in ('readout','final_induced_keV','transport_flags','charge_end_ns','native_any_negative_charge','native_min_charge_keV','native_max_charge_keV','endpoints','current_nA','induced_charge_fC'):scalar[key]=None
                scalars.append(scalar);histogram('deposited_per_group',500.)
                if not failed:histogram('native_terminal_charge',-400.)
        self.write_lines(base/'truth.jsonl',self.rows(batch));self.write_lines(base/'scalars.jsonl',scalars)
        self.write_lines(base/'traces.jsonl',[]);self.write_lines(base/'endpoints.jsonl',[])
        W.write(base/'readout-config.json',dict(plan['resolved']['electronics_configuration'],expected_primary_count=batch['primary_count']))
        W.write(base/'histograms.json',dict(width_keV=5,normalization_denominators=counts,bins=[E.histogram_row(stage,bin,n,counts) for (stage,bin),n in sorted(bins.items())]))
        result={k:request[k] for k in ('parent_configuration_sha256','shared_prepared_sha256','profile_sha256','source_sha256','numerics','operating_model','batch','native_preparation_sha256')}
        result.update(kind='batch_native_response_v1',status='completed_with_native_failures' if counts['native_failed_groups'] else 'completed_provisional_native_response',
            model_contract=self.model,request_sha256=W.sha(E.batch_directory(directory,batch['batch_index'])/'native-request.json'),counts=counts,
            independent_calibration_calls=0,calibration_calls=0,new_field_solution=False,calibration=prep['calibration'],field_fingerprint=prep['field_fingerprint'],ionisation_energy_eV=2.96,
            artifacts={p.name:W.sha(p) for p in base.iterdir()})
        W.write(base/'run.json',result);return result

    def test_partition_exact_defaults_and_acceptance_cap(self):
        for n,sizes in ((1,[1]),(499,[499]),(500,[500]),(9999,[9999]),(10000,[10000]),(10001,[10000,1]),(25001,[10000,10000,5001])):
            p=E.partition(n,42);self.assertEqual([b['primary_count'] for b in E.iter_batches(p)],sizes)
        for value in (True,1.,'1',B.MAX_SAFE_INTEGER+1,0):
            with self.assertRaises(W.ControlError):E.partition(value,42)
        self.assertEqual(self.plan['resolved']['batching']['batch_cap'],2)

    def test_original_and_catalog_sources_use_shared_route(self):
        for model in (*W.MODELS,'AK01','SAP16','SAP17','Bipolar_reference_3D','KL01_3D'):
            for source in (W.CS,'am241_point_decay_v1','ba133_point_decay_v1'):
                selection=dict(self.selection,detector=model,source=source)
                p=self.check(selection);self.assertEqual(p['resolved']['selection'],selection);self.assertTrue(p['execution_enabled'])

    def test_rehashed_plan_edits_refused_and_preview_not_start_token(self):
        for key,value in (('numerics',{'parcels':1}),('execution_rules',dict(E.RULES,independent_calibrations=3)),('electronics_configuration',dict(self.plan['resolved']['electronics_configuration'],gain=99))):
            bad=copy.deepcopy(self.plan);bad['resolved'][key]=value;bad['configuration_sha256']=W.digest(bad['resolved'])
            with patch.object(E,'check',return_value=self.plan),self.assertRaises(W.ControlError):E.admit(bad,self.root)
        bad=copy.deepcopy(self.plan);bad['kind']=B.KIND;bad['execution_enabled']=False
        with self.assertRaises(W.ControlError):E.admit(bad,self.root)

    def test_once_only_preparation_stop_resume_and_terminal_resume(self):
        def stop(stage,batch,stamp):
            if stage=='batch' and batch['batch_index']==0:E.request_stop('fixture',self.root)
        first=self.execute(after_seal=stop);self.assertEqual(first['status'],'stopped');self.assertEqual(first['completed_primary_count'],2)
        before={p:W.sha(p) for p in (self.directory/'shared').rglob('*') if p.is_file()}
        before.update({p:W.sha(p) for p in E.batch_directory(self.directory,0).rglob('*') if p.is_file()})
        final=self.execute(resume=True);self.assertEqual(final['status'],'completed_with_native_failures');self.assertEqual(final['completed_primary_count'],3)
        self.assertEqual(final['counts']['zero_deposit_primaries'],1);self.assertEqual(final['counts']['native_failed_groups'],1)
        self.assertEqual([stage for stage,index in self.calls].count('geometry'),1);self.assertEqual([stage for stage,index in self.calls].count('native_preparation'),1)
        self.assertTrue(all(W.sha(p)==h for p,h in before.items()))
        calls=list(self.calls);self.execute(resume=True);self.assertEqual(self.calls,calls)
        merged=W.read(self.directory/'results/histograms.json');self.assertEqual(sum(r['count'] for r in merged['bins'] if r['stage']=='deposited_per_decay'),3)
        page=E.event_page('fixture',1,root=self.root);self.assertEqual(page['records'][0]['global_initial_id'],2);self.assertIsNone(page['records'][0]['pulse_groups'][0]['readout'])

    def test_controller_crash_after_terminal_worker_before_receipt_recovers_bytes(self):
        def crash(stage,*args):
            result=self.worker(stage,*args)
            if stage=='response' and args[2]['batch_index']==0:raise RuntimeError('controller lost terminal response')
            return result
        with self.assertRaises(RuntimeError):self.execute(worker=crash)
        self.assertFalse(E.stage_receipt(self.directory,'response',E.batch_at(self.plan['resolved']['batching'],0)).exists())
        final=self.execute(resume=True);self.assertEqual(final['completed_primary_count'],3)
        self.assertEqual(self.calls.count(('response',0)),1)
        seal=W.read(E.stage_receipt(self.directory,'response',E.batch_at(self.plan['resolved']['batching'],0)))
        self.assertTrue(seal['recovered_terminal_worker']);self.assertIsNone(seal['elapsed_seconds'])

    def test_crash_after_stage_and_after_batch_seal_reuses_terminal_work(self):
        def crash(stage,batch,stamp):
            if stage=='batch':raise RuntimeError('lost batch reply')
        with self.assertRaises(RuntimeError):self.execute(after_seal=crash)
        self.execute(resume=True);self.assertEqual(self.calls.count(('radiation',0)),1);self.assertEqual(self.calls.count(('response',0)),1)

    def test_partial_worker_refused_and_rehashed_readout_correction_refused(self):
        def partial(stage,*args):
            if stage=='native_preparation':
                E.stage_base(args[1],stage).mkdir(parents=True);raise RuntimeError('partial state')
            return self.worker(stage,*args)
        with self.assertRaises(RuntimeError):self.execute(worker=partial)
        with self.assertRaisesRegex(W.ControlError,'unsealed'):self.execute(resume=True)
        self.assertEqual(self.calls.count(('geometry',None)),1)

    def test_rehashed_failure_zero_or_sign_changes_refused(self):
        self.execute();batch=E.batch_at(self.plan['resolved']['batching'],1);base=E.stage_base(self.directory,'response',batch)
        result=W.read(base/'run.json');rows=list(E.stream_jsonl(base/'scalars.jsonl'));rows[1]['final_induced_keV']=0.
        (base/'scalars.jsonl').unlink();self.write_lines(base/'scalars.jsonl',rows);result['artifacts']['scalars.jsonl']=W.sha(base/'scalars.jsonl')
        with self.assertRaisesRegex(W.ControlError,'invented'):E.validate_output('response',self.plan,self.directory,batch,result)

if __name__=='__main__':unittest.main()
