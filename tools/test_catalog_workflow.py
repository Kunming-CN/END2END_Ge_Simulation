"""Focused shared catalog contracts; injected stages never run science."""
import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import scenario_workflow as W
import catalog_workflow as C
import decay_workflow as D
import catalog_result_validation as V

class CatalogWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.settings=W.read(W.ROOT/'simulation/native_readout_profile.json')['settings']
        self.selection={'name':'new-shared-fixture','cryostat':W.CRYOSTAT,'detector':'Bipolar_reference_3D','source':W.CS,'pose':'nominal',
            'primary_count':20,'seed':26092631,'threads':1,'electronics':self.settings}
        self.model={'model_id':'Bipolar_reference_3D','stored_temperature_K':78.,'runtime_temperature_K':78.,'bias_span_V':2000.,
            'readout_contact_id':1,'contact_potentials_V':{'1':0.,'2':2000.},'wiring_factor':1,'placement':{'blocking_reasons':[]},'model_ref':'models/Bipolar_reference_3D.yaml','model_sha256':'a'*64,'dependencies_sha256':{}}
        self.effective=lambda e,r:{'profile':{'schema_version':2,'kind':'native_readout_profile_v1','name':'fixture','settings':copy.deepcopy(e)},
            'configuration':dict(e,schema_version=2,expected_primary_count=None,calibration_energy_keV=500,max_samples_per_event=500000,max_window_ns=1000000,require_all_events=True,tail_shaping_constants=20,trace_max_points=600),
            'physics_sha256':'b'*64}
        self.transport=lambda s,r:{'kind':'catalog_source_checked_v1','selection':copy.deepcopy(s),'model_contract':copy.deepcopy(self.model),'source_position_global_mm':[0,37.073,.290],'source_sha256':{}}
        self.runtime=lambda n:{'python_executable':'fixture','python_sha256':'c'*64,'julia_executable':'fixture','julia_sha256':'d'*64}
        self.sources=D.presets()
    def check(self,selection=None):
        with patch.object(D,'presets',return_value=self.sources),patch.object(D,'capability',return_value={'accepted':True}):
            return C.check(selection or self.selection,root=self.root,validate_settings=self.effective,transport_reader=self.transport,pin_reader=lambda m,r:{},runtime_reader=self.runtime)
    def test_original_model_temperature_and_contact_are_bound(self):
        p=self.check();self.assertEqual(p['kind'],C.KIND);self.assertEqual(p['resolved']['numerics']['runtime_temperature_K'],78)
        self.assertEqual(p['resolved']['numerics']['bias_V'],2000);self.assertEqual(p['resolved']['model_contract']['readout_contact_id'],1)
    def test_boolean_float_count_and_unsupported_tuple_refused(self):
        for key,value in (('primary_count',True),('primary_count',20.),('primary_count',5000),('threads',True),('seed',True),('cryostat','bare'),('pose','plus5mm'),('detector','SAP22')):
            s=copy.deepcopy(self.selection);s[key]=value
            with self.subTest(key=key,value=value),self.assertRaises(W.ControlError):self.check(s)
    def test_held_source_is_not_admitted(self):
        s=copy.deepcopy(self.selection);s['source']='co60_point_decay_v1'
        with patch.object(D,'presets',return_value=self.sources),patch.object(D,'capability',return_value=None),self.assertRaises(W.ControlError):
            C.check(s,root=self.root,validate_settings=self.effective,transport_reader=self.transport)
    def test_rehashed_settings_numerics_and_geometry_mismatch_refused(self):
        p=self.check()
        for mutate in (lambda r:r['numerics'].update(runtime_temperature_K=77),lambda r:r['model_contract'].update(bias_span_V=1),lambda r:r['electronics_configuration'].update(gain=99)):
            changed=copy.deepcopy(p);mutate(changed['resolved']);changed['configuration_sha256']=W.digest(changed['resolved'])
            with patch.object(C,'check',return_value=p),self.assertRaises(W.ControlError):C.admit(changed,self.root)
    def test_legacy_admission_refuses_new_plan(self):
        with self.assertRaises(W.ControlError):W.admit(self.check(),self.root)
    def test_parent_uses_existing_stage_boundary_stop_and_resume(self):
        p=self.check();d=W.run_path(p['resolved']['selection']['name'],self.root);calls=[]
        def execute(argv,directory,stage,receipt,environment,root):
            calls.append(stage);base=directory/'response' if stage=='response' else directory/'transport/stream' if stage=='event_ledger' else directory/'transport';base.mkdir(parents=True,exist_ok=True)
            (base/(stage+'.txt')).write_text('sealed '+stage)
            if stage=='geometry':W.write(directory/'STOP.json',{'fixture':True},fresh=True)
            if stage=='response':W.write(base/'run.json',{'counts':{'initial_primaries':20,'native_failed_groups':0}})
            receipt['stages'][stage]={'status':'command_exited'}
        def validate(directory,stage,*args,**kwargs):
            base=directory/'response' if stage=='response' else directory/'transport/stream' if stage=='event_ledger' else directory/'transport'
            # Geometry binds its original file only, rather than later outputs.
            names=[stage+'.txt']
            if stage=='response':names.append('run.json')
            return {n:{'sha256':W.sha(base/n),'bytes':(base/n).stat().st_size} for n in names}
        def page(directory,receipt):(directory/'index.html').write_text('Synthetic completed result')
        mocks=(patch.object(C,'admit',return_value=p),patch.object(W,'verify_pins'),patch.object(W,'child_env',return_value={'JULIA_EXE':__file__}),
            patch.object(C,'stage_commands',return_value={s:[] for s in W.STAGES[:-1]}),patch.object(C,'validate_stage',side_effect=validate),
            patch.object(C,'native_request',return_value={'fixture':True}),patch.object(W,'result_page',side_effect=page))
        with mocks[0],mocks[1],mocks[2],mocks[3],mocks[4],mocks[5],mocks[6]:
            stopped=C.execute(p,root=self.root,executor=execute);self.assertEqual(stopped['status'],'stopped');self.assertEqual(calls,['geometry'])
            completed=C.execute(p,root=self.root,resume=True,executor=execute)
        self.assertEqual(completed['kind'],C.KIND);self.assertEqual(completed['status'],'completed');self.assertEqual(calls,['geometry','radiation','event_ledger','response'])
        self.assertEqual(W.read(d/'COMPLETE.json')['kind'],C.KIND)
    def test_semantic_readout_rehash_refused(self):
        p=self.check();d=self.root/'run';base=d/'response';base.mkdir(parents=True)
        (d/'electronics').mkdir();W.write(d/'electronics/profile.json',p['resolved']['profile'])
        (d/'transport/stream').mkdir(parents=True);W.write(d/'transport/stream/manifest.json',{'fixture':True});(d/'transport/truth.lh5').write_bytes(b'raw fixture')
        request=C.native_request(d,p['resolved'],self.root);W.write(d/'catalog-request.json',request)
        r={'status':'completed_provisional_native_response','model_id':self.model['model_id'],'stored_temperature_K':78.,'temperature_K':78.,'bias_V':2000.,'readout_contact_id':1,'calibration_calls':1,
            'kind':'catalog_native_response_v1','configuration_sha256':request['configuration_sha256'],'source_id':self.selection['source'],'source_contract':p['resolved']['source_contract'],
            'model_contract':self.model,'source_sha256':p['resolved']['source_sha256'],'profile_sha256':request['profile_sha256'],'input_sha256':request['stream_sha256'],
            'source_lh5_sha256':W.sha(d/'transport/truth.lh5'),'request_sha256':W.sha(d/'catalog-request.json'),'contact_potentials_V':self.model['contact_potentials_V'],
            'wiring_factor':1,'independent_calibration_calls':1,'new_field_solution':True,
            'numerics':copy.deepcopy(p['resolved']['numerics']),'parcels':16,'seed_family':2609261,'drift_dt_ns':2,'nominal_drift_cap_ns':10000,
            'native_failure_policy':'record','diffusion':True,'self_repulsion':False,'end_drift_when_no_field':False,
            'counts':{'initial_primaries':20,'initial_decays':20,'zero_deposit_primaries':19,'accepted':1,'rejected':0,'groups':1,'native_failed_groups':0,'readout_rejected':0},'artifacts':{}}
        W.write(base/'run.json',r);config=dict(p['resolved']['electronics_configuration'],expected_primary_count=20,gain=99);W.write(base/'readout-config.json',config)
        with self.assertRaises(W.ControlError):C.validate_stage(d,'response',p['resolved'],self.root,semantic=False)
        config['gain']=p['resolved']['electronics_configuration']['gain'];W.write(base/'readout-config.json',config)
        C.validate_stage(d,'response',p['resolved'],self.root,semantic=False)
        original_report_sha=W.sha(base/'run.json')
        for key,value in (('configuration_sha256','f'*64),('wiring_factor',-1),('independent_calibration_calls',2),
            ('numerics',dict(p['resolved']['numerics'],precision_bits=32,min_spacing_mm=100)),('parcels',1),('seed_family',17),
            ('drift_dt_ns',999),('nominal_drift_cap_ns',20),('native_failure_policy','ignore'),('diffusion',False),
            ('self_repulsion',True),('end_drift_when_no_field',True),('diffusion',1),('self_repulsion',0),('end_drift_when_no_field',0)):
            changed=copy.deepcopy(r);changed[key]=value;W.write(base/'run.json',changed)
            self.assertNotEqual(W.sha(base/'run.json'),original_report_sha) # Rehashed report; every artifact/census input stays fixed.
            with self.subTest(key=key),self.assertRaises(W.ControlError):C.validate_stage(d,'response',p['resolved'],self.root,semantic=False)
    def test_capability_size_blocking_not_a_missing_physics_input(self):
        model=dict(self.model,contact_potentials_V={'1':0,'2':2000},wiring_factor=1)
        blocked=copy.deepcopy(model);blocked.update(model_id='large');blocked['placement']={'blocking_reasons':['Width exceeds fixed cavity 41.148 mm.']}
        entries=C.catalog_capabilities(self.root,reader=lambda r:[model,blocked]);self.assertEqual(entries['large']['block_code'],'cryostat_size')
        self.assertIn('41.148',entries['large']['reason']);self.assertEqual(entries[self.model['model_id']]['block_code'],'setup_required')
    def test_streamed_saved_census_retains_zero_and_failed_primaries(self):
        base=self.root/'census';out=base/'response';stream=base/'transport/stream';out.mkdir(parents=True);stream.mkdir(parents=True)
        source=[];scalars=[]
        for eid in range(20):
            steps=[{'raw_row_index':10+eid,'energy_keV':1.2}] if eid<3 else []
            groups=[{'group_id':0,'origin_time_ns':0.,'row_indices':[10+eid]}] if steps else []
            event={'event_id':eid,'global_decay_id':eid,'steps':steps,'pulse_groups':groups,'line_photon_count':0,'decay_photon_count':1,'material_energy_keV':{'G4_Ge':1.2 if steps else 0.}}
            source.append(event);scalars.append({'record_kind':'decay','event_id':eid,'global_decay_id':eid,'zero_deposit':not steps,'pulse_count':len(groups),
                'deposited_energy_keV':1.2 if steps else 0.,'raw_row_indices':[10+eid] if steps else [],'line_photon_count':0,'decay_photon_count':1,'material_energy_keV':event['material_energy_keV']})
            if groups:
                pulse={'record_kind':'pulse','event_id':eid,'global_decay_id':eid,'group_id':0,'group':groups[0],'origin_time_ns':0.,'raw_row_indices':[10+eid],
                    'deposited_energy_keV':1.2,'accepted':eid==0,'readout':{'accepted':eid==0}}
                if eid==1:
                    pulse['status']='native_transport_failed'
                    pulse.update({k:None for k in ('readout','final_induced_keV','transport_flags','charge_end_ns','native_any_negative_charge','native_min_charge_keV','native_max_charge_keV','endpoints','current_nA','induced_charge_fC')})
                scalars.append(pulse)
        def save_rows(path,rows):path.write_bytes(b''.join(W.encoded(row)+b'\n' for row in rows))
        save_rows(stream/'events.jsonl',source);W.write(stream/'manifest.json',{'chunks':[{'file':'events.jsonl'}]});save_rows(out/'truth.jsonl',source);save_rows(out/'scalars.jsonl',scalars)
        cal={'energy_keV':500,'time_step_ns':2,'ionisation_energy_eV':2.95,'charge_C':500000/2.95*1.602176634e-19,'peak_V':1.,'volts_per_keV':.002}
        counts={'initial_primaries':20,'initial_decays':20,'zero_deposit_primaries':17,'groups':3,'accepted':1,'rejected':2,'native_failed_groups':1,'readout_rejected':1,'line_photons':0,'decay_photons':20}
        report={'counts':counts,'calibration':cal,'ionisation_energy_eV':2.95};resolved={'selection':{'primary_count':20}}
        self.assertEqual(V.response_census(base,resolved,report),counts)
        edited=copy.deepcopy(scalars);edited[3]['final_induced_keV']=.9;save_rows(out/'scalars.jsonl',edited)
        with self.assertRaises(W.ControlError):V.response_census(base,resolved,report)
        save_rows(out/'scalars.jsonl',scalars);changed=copy.deepcopy(report);changed['counts']['zero_deposit_primaries']=16
        with self.assertRaises(W.ControlError):V.response_census(base,resolved,changed)
        edited=copy.deepcopy(source);edited[-1]['event_id']=18;save_rows(out/'truth.jsonl',edited)
        with self.assertRaises(W.ControlError):V.response_census(base,resolved,report)

if __name__=='__main__':unittest.main()
