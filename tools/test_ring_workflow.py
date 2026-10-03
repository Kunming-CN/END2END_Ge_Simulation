"""Pure ring configuration/semantic tamper fixtures; zero scientific calls.

Geometry fixture bytes come from preserved completed pilot preparation only.
Stream/readout records below are explicitly synthetic contract fixtures; no
radiation, field, transport, propagator or calibration is executed.
"""
import copy
import math
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import scenario_workflow as W
import ring_workflow as R
import ring_model_contract as M


class Rings(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.defaults=W.catalog()['electronics_defaults']
        cls.validated=W.settings_check(dict(cls.defaults,gain=21,adc_bits=16,peak_gate_start_ns=0,peak_gate_end_ns=9000))
        cls.runtime=W.runtime_identity(1)

    def setUp(self):
        base=W.ROOT/'.local/product-delivery-v1/implementation-tests';base.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=base);self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.config={'name':'ring-contract-fixture','cryostat':W.CRYOSTAT,'detector':'GeRC02','source':W.CS,'pose':'nominal',
            'primary_count':20,'seed':26100241,'threads':1,'electronics':copy.deepcopy(self.validated['profile']['settings'])}

    def plan(self,model=None):
        config=copy.deepcopy(self.config)
        if model:config['detector']=model
        return W.check(config,root=self.root,validate_settings=lambda e,r:copy.deepcopy(self.validated),
                       pin_reader=lambda model,r:W.source_pins(model),runtime_reader=lambda t:copy.deepcopy(self.runtime),portable_reader=lambda c,r:None)

    def geometry(self,model='GeRC02'):
        plan=self.plan(model);resolved=plan['resolved'];s=resolved['selection'];directory=W.run_path(s['name'],self.root);t=directory/'transport'
        original=W.ROOT/('.local/ring-cs137-v1/pilot500/'+model+'/transport');p=W.read(original/'prepared.json')
        self.assertEqual(p['model_contract'],R.model_contract(model,p['model_contract']['effective_model_ref']))
        for name in (*p['files_sha256'],'prepare-receipt.json'):
            target=W.safe_path(t,name);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(W.safe_path(original,name),target)
        p['primary_count']=20;p['seed']=s['seed'];ref=W.BASE+'/'+s['name']+'/transport/effective-model/GeRC02.yaml' if model=='GeRC02' else 'models/KMRC01_candidate.yaml'
        p['model_contract']=R.model_contract(model,ref);W.write(t/'effective-model/model-contract.json',p['model_contract'])
        (t/'run.mac').write_text(R.producers().cs.macro_text(W.read(t/'geometry-report.json'),20,p['source_position_global_mm']),encoding='utf-8')
        p['files_sha256']={name:W.sha(W.safe_path(t,name)) for name in p['files_sha256']};W.write(t/'prepared.json',p,fresh=True)
        W.write(directory/'electronics/profile.json',resolved['profile'],fresh=True)
        return directory,plan,p

    def stream(self,model='GeRC02'):
        directory,plan,p=self.geometry(model);t=directory/'transport'
        (t/'truth.lh5').write_bytes(b'SYNTHETIC CONTRACT FIXTURE; NOT RADIATION DATA')
        W.write(t/'run.json',{'status':'complete','returncode':0,'prepared_sha256':W.sha(t/'prepared.json'),
            'source_lh5_sha256':W.sha(t/'truth.lh5'),'versions':{'remage':'1.1.0','geant4':'11.3.2'}},fresh=True)
        events=[]
        for id in range(20):
            steps=[{'raw_row_index':0,'time_ns':10,'energy_keV':2},{'raw_row_index':1,'time_ns':200010,'energy_keV':1}] if id==0 else []
            if id==1:steps=[{'raw_row_index':2,'time_ns':20,'energy_keV':0}]
            events.append({'event_id':id,'global_decay_id':id,'steps':steps,'pulse_groups':R.producers().cs.group_deposits(steps),
                           'line_photon_count':1,'decay_photon_count':2,'material_energy_keV':{'G4_Ge':sum(v['energy_keV'] for v in steps)}})
        folder=t/'stream';folder.mkdir();(folder/'chunk-00000.jsonl').write_text(''.join(W.encoded(e).decode()+'\n' for e in events),encoding='utf-8')
        m={key:p[key] for key in ('model_id','model_sha256','model_contract','primary_count','coordinate_transform','grouping_policy','clock_policy','source_sha256','ring_source_sha256','mounting_contract')}
        m.update(kind='cs137_decay_stream_v1',producer_adapter='ring_cs137_v1',status='complete',global_decay_id_range=[0,19],
                 units={'energy':'keV','length':'mm','time':'ns'},source_lh5='../truth.lh5',raw_track_energy_unit='MeV',raw_position_unit='m',ledger={'full_energy_closure':None},
                 chunks=[{'file':'chunk-00000.jsonl','count':20,'first_global_decay_id':0,'sha256':W.sha(folder/'chunk-00000.jsonl')}])
        for file,key in (('prepared.json','prepared_sha256'),('run.json','run_sha256'),('truth.lh5','source_lh5_sha256'),('scenario.json','config_sha256'),('geometry.gdml','geometry_sha256'),('run.mac','macro_sha256')):m[key]=W.sha(t/file)
        W.write(folder/'manifest.json',m,fresh=True)
        return directory,plan,p,events,m

    def readout(self,model='KMRC01_candidate'):
        directory,plan,p,events,m=self.stream(model);out=directory/'response';out.mkdir();resolved=plan['resolved'];op=R.operating(model)
        request=R.request(directory,resolved,self.root);W.write(directory/'ring-request.json',request,fresh=True)
        c=resolved['electronics_configuration'];charge=500000/3*1.602176634e-19
        cal={'energy_keV':500,'time_step_ns':2,'ionisation_energy_eV':3,'charge_C':charge,'peak_V':.5,'peak_time_ns':1000,
             'volts_per_keV':.001,'adc_lsb_V':c['adc_full_scale_V']/2**c['adc_bits'],'method':'single delta-charge injection at t=0; sampled analog peak; fixed across events'}
        if model=='KMRC01_candidate':
            cal.update(method='independent negative fixture injection',raw_charge_C=-charge,electronics_input_charge_C=charge,wiring_factor=-1)
            W.write(out/'negative-injection.json',{'kind':'independent_negative_charge_injection_v1','calibration':cal,
                'raw_delta_charge_C':-charge,'electronics_input_delta_charge_C':charge,'wiring':{'factor':-1},'input_is_independent_of_event_truth':True},fresh=True)
        rows=[]
        for e in events:
            rows.append({'record_kind':'decay','event_id':e['event_id'],'global_decay_id':e['global_decay_id'],'group_id':None,
                         'deposited_energy_keV':sum(v['energy_keV'] for v in e['steps']),'pulse_count':len(e['pulse_groups']),'zero_deposit':all(v['energy_keV']==0 for v in e['steps']),
                         'raw_row_indices':[v['raw_row_index'] for v in e['steps']], 'full_energy_closure':None,
                         **{k:e[k] for k in ('line_photon_count','decay_photon_count','material_energy_keV')}})
            for g in e['pulse_groups']:
                raw=-1 if model=='KMRC01_candidate' else 1
                readout={'wiring':{'factor':op['wiring_factor'],'model_id':model},'raw_native_final_charge_keV':raw,'raw_native_min_charge_keV':min(0,raw),'raw_native_max_charge_keV':max(0,raw)}
                rows.append({'record_kind':'pulse','event_id':e['event_id'],'global_decay_id':e['global_decay_id'],'group_id':g['group_id'],
                    'group':g,'origin_time_ns':g['origin_time_ns'],'raw_row_indices':g['row_indices'],
                    'deposited_energy_keV':sum(e['steps'][i]['energy_keV'] for i in g['row_indices']),
                    'final_induced_keV':raw,'native_min_charge_keV':min(0,raw),'native_max_charge_keV':max(0,raw),'readout':readout,'accepted':True,'trace_saved':True})
        (out/'scalars.jsonl').write_text(''.join(W.encoded(r).decode()+'\n' for r in rows),encoding='utf-8')
        (out/'truth.jsonl').write_text(''.join(W.encoded(e).decode()+'\n' for e in events),encoding='utf-8')
        trace={'induced_charge_fC':[0,1],'current_nA':[1,0],'raw_native_induced_charge_fC':[0,-1],'raw_native_current_nA':[-1,0]}
        (out/'traces.jsonl').write_text(''.join(W.encoded({'event_id':0,'global_decay_id':0,'group_id':g['group_id'],
              'origin_time_ns':g['origin_time_ns'],'trace':trace}).decode()+'\n' for g in events[0]['pulse_groups']),encoding='utf-8')
        report={'kind':'workflow_ring_native_response_v1','status':'completed_provisional_native_response','configuration_sha256':plan['configuration_sha256'],
            'request_sha256':W.sha(directory/'ring-request.json'),'model_contract':p['model_contract'],'signed_operating_bias_V':op['signed_bias_V'],
            'contact_potentials_V':op['contact_potentials_V'],'wiring_factor':op['wiring_factor'],'new_field_solution':True,'geometry_checks':{'field_cache_used':False},
            'independent_calibration_calls':1,'calibration':cal,'source_lh5_sha256':W.sha(directory/'transport/truth.lh5'),
            'counts':{'initial_primaries':20,'initial_decays':20,'zero_deposit_primaries':19,'line_photons':20,'decay_photons':40,
                      'groups':2,'accepted':2,'rejected':0,'readout_rejected':0,'native_failed_groups':0}}
        W.write(out/'run.json',report,fresh=True)
        envelope={'kind':'workflow_ring_response_v1',**{k:report[k] for k in ('status','configuration_sha256','request_sha256','model_contract','signed_operating_bias_V','wiring_factor','new_field_solution','independent_calibration_calls','calibration','counts')},
                  'source_sha256':resolved['source_sha256'],'native_report_sha256':W.sha(out/'run.json')}
        W.write(out/'workflow-ring-response.json',envelope,fresh=True)
        return directory,plan,report,rows

    def test_four_detector_catalog_and_closed_ring_sources(self):
        enabled=[d for d in W.catalog()['detectors'] if d['available']]
        self.assertEqual({d['id'] for d in enabled},set(W.MODELS))
        for d in enabled:
            if d['id'] in R.MODELS:self.assertEqual(d['sources'],[W.CS])
        self.assertIn('fresh-clone',W.catalog()['setup_limit'].lower())
        c=dict(self.config,source=W.GAMMA,pose='plus5mm',seed=26092631)
        with self.assertRaises(W.ControlError):W.check(c,root=self.root)

    def test_both_selected_commands_and_all_electronics_are_forwarded(self):
        for model in R.MODELS:
            plan=self.plan(model);r=plan['resolved'];s=r['selection'];cmd=W.stage_commands(W.run_path(s['name'],self.root),r,self.root,{'JULIA_EXE':'pinned-julia'})
            self.assertIn('./ring_cs137.py',cmd['geometry']);self.assertIn(model,cmd['geometry']);self.assertIn('20',cmd['geometry'])
            self.assertIn('./ring_cs137.py',cmd['radiation']);self.assertIn(str(self.root/'simulation/workflow_ring_response.jl'),cmd['response'])
            self.assertEqual(r['profile']['settings'],s['electronics']);self.assertTrue(all(r['electronics_configuration'][k]==s['electronics'][k] for k in W.SETTINGS))
            self.assertEqual(r['operating_model']['signed_bias_V'],240 if model=='GeRC02' else -370)
            self.assertEqual(r['numerics']['bias_V'],240 if model=='GeRC02' else 370)

    def test_rehashed_plan_wrong_wiring_bias_variant_or_removed_sources_refused(self):
        plan=self.plan('KMRC01_candidate')
        for mutate in (lambda r:r['operating_model'].update(wiring_factor=1),lambda r:r['operating_model'].update(signed_bias_V=370),
                       lambda r:r['operating_model']['contact_potentials_V'].update({'2':370}),lambda r:r['operating_model'].update(effective_model_sha256='e'*64),
                       lambda r:r['source_sha256'].pop('simulation/ring_polarity.jl')):
            other=copy.deepcopy(plan);mutate(other['resolved']);other['configuration_sha256']=W.digest(other['resolved'])
            with self.subTest(mutation=mutate),patch.object(W,'check',return_value=plan),self.assertRaises(W.ControlError):W.admit(other,self.root)

    def test_effective_ge_model_and_current_geometry_contract(self):
        directory,plan,p=self.geometry();R.prepared(directory,plan['resolved'],self.root)
        self.assertIn(b'30minute',(W.ROOT/'models/GeRC02.yaml').read_bytes())
        self.assertIn(b'50minute',(directory/'transport/effective-model/GeRC02.yaml').read_bytes())
        for key,value in [('model_id','KMRC01_candidate'),('source_pdg',22),('source_position_global_mm',[0,42.073,.290])]:
            altered=copy.deepcopy(p);altered[key]=value;W.write(directory/'transport/prepared.json',altered)
            with self.subTest(key=key),self.assertRaises((W.ControlError,ValueError)):R.prepared(directory,plan['resolved'],self.root)
        W.write(directory/'transport/prepared.json',p)
        path=directory/'transport/effective-model/GeRC02.yaml';path.write_bytes(path.read_bytes().replace(b'50minute',b'51minute'))
        p['model_contract']['effective_model_sha256']=W.sha(path);W.write(directory/'transport/prepared.json',p)
        with self.assertRaises(W.ControlError):R.prepared(directory,plan['resolved'],self.root)

    def test_km_rehashed_unsigned_contact_contract_refused(self):
        directory,plan,p=self.geometry('KMRC01_candidate');R.prepared(directory,plan['resolved'],self.root)
        p['model_contract']['contact_potentials_V']['2']=370;W.write(directory/'transport/prepared.json',p)
        with self.assertRaises(W.ControlError):R.prepared(directory,plan['resolved'],self.root)

    def test_complete_zero_and_delayed_group_ledger_preserved(self):
        directory,plan,p,events,m=self.stream();actual=R.ledger(directory,plan['resolved'],self.root)
        self.assertEqual(actual,events);self.assertEqual(len(actual),20);self.assertEqual(actual[0]['pulse_groups'][1]['origin_time_ns'],200010)
        self.assertEqual(sum(all(v['energy_keV']==0 for v in e['steps']) for e in actual),19)
        self.assertEqual(actual[1]['steps'][0]['raw_row_index'],2)
        request=R.request(directory,plan['resolved'],self.root);self.assertEqual(request['selection']['electronics'],plan['resolved']['profile']['settings'])
        self.assertEqual(request['operating_model']['annealing_time_minutes'],50)

    def test_rehashed_stream_missing_primary_or_changed_delays_refused(self):
        directory,plan,p,events,m=self.stream();folder=directory/'transport/stream';path=folder/'chunk-00000.jsonl'
        for records in (events[:-1],copy.deepcopy(events)):
            if len(records)==20:records[0]['steps'][1]['time_ns']=100011
            path.write_text(''.join(W.encoded(e).decode()+'\n' for e in records),encoding='utf-8');m['chunks'][0]['sha256']=W.sha(path);W.write(folder/'manifest.json',m)
            with self.subTest(count=len(records)),self.assertRaises((W.ControlError,ValueError)):R.ledger(directory,plan['resolved'],self.root)

    def test_km_negative_calibration_raw_sign_and_wire_authority(self):
        directory,plan,report,rows=self.readout();R.response(directory,plan['resolved'],report,self.root)
        envelope=W.read(directory/'response/workflow-ring-response.json')
        report['wiring_factor']=1;W.write(directory/'response/run.json',report);envelope['wiring_factor']=1;envelope['native_report_sha256']=W.sha(directory/'response/run.json');W.write(directory/'response/workflow-ring-response.json',envelope)
        with self.assertRaises(W.ControlError):R.response(directory,plan['resolved'],report,self.root)

    def test_km_rehashed_trace_rectification_refused(self):
        directory,plan,report,rows=self.readout();path=directory/'response/traces.jsonl';values=[W.decode_json(v) for v in path.read_text().splitlines()];values[0]['trace']['raw_native_current_nA']=[1,0]
        path.write_text(''.join(W.encoded(v).decode()+'\n' for v in values),encoding='utf-8')
        with self.assertRaises(W.ControlError):R.response(directory,plan['resolved'],report,self.root)

    def test_native_failure_keeps_nulls_and_the_original_group(self):
        directory,plan,report,rows=self.readout();pulse=next(r for r in rows if r['record_kind']=='pulse')
        pulse.update({k:None for k in ('readout','final_induced_keV','transport_flags','charge_end_ns','native_any_negative_charge',
            'native_min_charge_keV','native_max_charge_keV','endpoints','current_nA','induced_charge_fC')})
        pulse.update(status='native_transport_failed',accepted=False,trace_saved=False,rejection_reason='native_transport_failed',
                     deposition_delays_ns=[0],source_lh5_sha256=report['source_lh5_sha256'],raw_table='stp/germanium',parcels=16,seed_family=2609261,
                     endpoint_details_note='Strict NativeLiExample.native_event does not expose rejected endpoint details; private supervisor diagnostics are separate.',
                     native_error={'type':'ArgumentError','message':'Invalid waveform support','exact_error':'ArgumentError: Invalid waveform support','stage':'NativeLiExample.native_event'})
        keys=('model_id','model_sha256','input_sha256','source_sha256','temperature_K','bias_V','parcels','seed_family','seed_rule','diffusion',
              'end_drift_when_no_field','self_repulsion','drift_dt_ns','nominal_drift_cap_ns','readout_contact_id','field_settings','field_fingerprint',
              'profile_sha256','config_sha256','calibration','native_failure_policy')
        for k in keys:report.setdefault(k,'synthetic-diagnostic-setting')
        event=W.decode_json((directory/'response/truth.jsonl').read_text().splitlines()[0])
        W.write(directory/'response/native-failures.jsonl',{'record_kind':'native_failure_diagnostic','pulse':copy.deepcopy(pulse),
            'original_event':event,'original_group':pulse['group'],'original_steps':[event['steps'][0]],'settings':{k:report[k] for k in keys}})
        tracepath=directory/'response/traces.jsonl';tracepath.write_text(tracepath.read_text().splitlines()[1]+'\n',encoding='utf-8')
        report['counts'].update(accepted=1,rejected=1,native_failed_groups=1)
        W.write(directory/'response/run.json',report);envelope=W.read(directory/'response/workflow-ring-response.json')
        envelope['counts']=report['counts'];envelope['native_report_sha256']=W.sha(directory/'response/run.json');W.write(directory/'response/workflow-ring-response.json',envelope)
        path=directory/'response/scalars.jsonl';path.write_text(''.join(W.encoded(r).decode()+'\n' for r in rows),encoding='utf-8')
        R.response(directory,plan['resolved'],report,self.root)
        pulse['final_induced_keV']=0;path.write_text(''.join(W.encoded(r).decode()+'\n' for r in rows),encoding='utf-8')
        with self.assertRaises(W.ControlError):R.response(directory,plan['resolved'],report,self.root)

    def test_derived_nonnegative_reduction_rounding_only(self):
        values=[600.,.000001,.000002,.000003,.000004,.000005,.000006,.000007,.000008]
        target=math.fsum(values);other=target
        for _ in range(3):other=math.nextafter(other,math.inf)
        self.assertTrue(R.energy_sum_matches(other,values))
        self.assertFalse(R.energy_sum_matches(target+.00001,values))
        self.assertTrue(R.energy_sum_matches(0,[0.,0.]))
        self.assertFalse(R.energy_sum_matches(math.ulp(0.),[0.,0.]))
        for bad in (-1,math.inf,math.nan,True):
            with self.subTest(bad=bad),self.assertRaises(W.ControlError):R.energy_sum_matches(bad,values)

    def test_rehashed_primary_and_aggregate_census_refused(self):
        directory,plan,report,rows=self.readout('GeRC02');out=directory/'response'
        for key,value in (('global_decay_id',666),('deposited_energy_keV',12),('zero_deposit',False),('pulse_count',99),
                          ('raw_row_indices',[999]),('material_energy_keV',{}),('line_photon_count',9),('full_energy_closure',0)):
            altered=copy.deepcopy(rows);altered[3][key]=value
            (out/'scalars.jsonl').write_text(''.join(W.encoded(v).decode()+'\n' for v in altered),encoding='utf-8')
            with self.subTest(key=key),self.assertRaises(W.ControlError):R.response(directory,plan['resolved'],report,self.root)
        (out/'scalars.jsonl').write_text(''.join(W.encoded(v).decode()+'\n' for v in rows),encoding='utf-8')
        for key in ('initial_decays','zero_deposit_primaries','line_photons','decay_photons'):
            bad=copy.deepcopy(report);bad['counts'][key]=999;W.write(out/'run.json',bad);env=W.read(out/'workflow-ring-response.json');env['counts']=bad['counts'];env['native_report_sha256']=W.sha(out/'run.json');W.write(out/'workflow-ring-response.json',env)
            with self.subTest(key=key),self.assertRaises(W.ControlError):R.response(directory,plan['resolved'],bad,self.root)

    def test_saved_trace_exact_identity_and_selection(self):
        directory,plan,report,rows=self.readout('GeRC02');out=directory/'response';path=out/'traces.jsonl'
        original=[W.decode_json(v) for v in path.read_text().splitlines()]
        variants=[]
        for key,value in (('event_id',999),('group_id',999),('global_decay_id',999),('origin_time_ns',0)):
            altered=copy.deepcopy(original);altered[0][key]=value;variants.append(altered)
        variants.extend((original[:-1],original+[original[0]]))
        for values in variants:
            path.write_text(''.join(W.encoded(v).decode()+'\n' for v in values),encoding='utf-8')
            with self.assertRaises(W.ControlError):R.response(directory,plan['resolved'],report,self.root)
        path.write_text(''.join(W.encoded(v).decode()+'\n' for v in original),encoding='utf-8');rows[1]['trace_saved']=False
        (out/'scalars.jsonl').write_text(''.join(W.encoded(v).decode()+'\n' for v in rows),encoding='utf-8')
        with self.assertRaises(W.ControlError):R.response(directory,plan['resolved'],report,self.root)

    def test_rehashed_pulse_group_or_truth_identity_refused(self):
        directory,plan,report,rows=self.readout();pulse=next(r for r in rows if r['record_kind']=='pulse')
        pulse['origin_time_ns']=0;path=directory/'response/scalars.jsonl';path.write_text(''.join(W.encoded(r).decode()+'\n' for r in rows),encoding='utf-8')
        with self.assertRaises(W.ControlError):R.response(directory,plan['resolved'],report,self.root)

    def test_ge_positive_calibration_is_separate_from_km_wiring(self):
        directory,plan,report,rows=self.readout('GeRC02');R.response(directory,plan['resolved'],report,self.root)
        W.write(directory/'response/negative-injection.json',{'fixture':'wrong model injection'},fresh=True)
        with self.assertRaises(W.ControlError):R.response(directory,plan['resolved'],report,self.root)


if __name__=='__main__':unittest.main()
