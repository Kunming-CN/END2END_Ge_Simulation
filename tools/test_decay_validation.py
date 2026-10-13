"""Public saved-response regression fixtures; no raw data, physics or private evidence."""
import copy,csv,json,math,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import decay_validation as V
import scenario_workflow as W
import decay_workflow as D
import histogram_normalization as H
class ResponseValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name)
        self.out=self.base/'response';self.out.mkdir();(self.base/'transport').mkdir()
        # Full admitted source metadata, synthetic event data, and exact registry
        # bytes. Only request/ledger producers are injected; the live response
        # route, source-aware histogram gate and artifact hashes are real.
        (self.base/'scenarios').mkdir();(self.base/D.REGISTRY).write_bytes((W.ROOT/D.REGISTRY).read_bytes())
        source=D.preset('am241_point_decay_v1');model={'model_id':'SAP22'}
        pins={'simulation/native_response.jl':W.sha(W.ROOT/'simulation/native_response.jl')}
        self.resolved={'selection':{'source':source['id'],'detector':'SAP22','primary_count':1},
          'decay_source_contract':source,'source_sha256':pins,'numerics':{'bias_V':700},
          'electronics_configuration':{'calibration_energy_keV':500,'max_window_ns':1000000,'tail_shaping_constants':20,'expected_primary_count':None},
          'operating_model':{'signed_bias_V':700,'wiring_factor':1,'contact_potentials_V':{'1':0,'2':700}}}
        self.request={'source_sha256':copy.deepcopy(self.resolved['source_sha256'])}
        W.write(self.base/'decay-request.json',self.request);W.write(self.base/'transport/prepared.json',{'model_contract':model})
        cal={'energy_keV':500,'time_step_ns':2,'ionisation_energy_eV':2.95,
            'charge_C':500000/2.95*1.602176634e-19,'peak_V':.25,'volts_per_keV':.0005}
        self.report={'kind':'workflow_decay_native_response_v1','configuration_sha256':W.digest(self.resolved),
          'request_sha256':W.sha(self.base/'decay-request.json'),'source_id':source['id'],'source_contract':source,
          'model_contract':model,'signed_operating_bias_V':700,'wiring_factor':1,'contact_potentials_V':{'1':0,'2':700},
          'new_field_solution':True,'geometry_checks':{'field_cache_used':False},'independent_calibration_calls':1,
          'status':'completed_provisional_native_response','model_id':'SAP22',
          'source_sha256':{'native_response.jl':pins['simulation/native_response.jl']},
          'stored_temperature_K':78,'temperature_K':77,'bias_V':700,'parcels':16,'seed_family':2609261,
          'calibration':cal,'counts':{}}
        self.group={'group_id':0,'origin_time_ns':0,'row_indices':[0]}
        self.truth=[{'event_id':0,'global_decay_id':0,'steps':[{'raw_row_index':0,'energy_keV':10,'time_ns':0}],
            'pulse_groups':[self.group],'line_photon_count':1,'decay_photon_count':1,
            'line_photon_counts':{'Np237_59.54092':1}}]
        self.primary={'record_kind':'decay','event_id':0,'global_decay_id':0,'zero_deposit':False,
            'deposited_energy_keV':10,'raw_row_indices':[0],'pulse_count':1}
        self.pulse={'record_kind':'pulse','event_id':0,'group_id':0,'origin_time_ns':0,'group':self.group,
            'raw_row_indices':[0],'deposited_energy_keV':10,'accepted':True,'readout':{}}
        (self.out/'truth.jsonl').write_text(json.dumps(self.truth[0])+'\n',encoding='utf-8')
    def prepare(self,pulse,*,legacy=False):
        source=self.resolved['decay_source_contract'];self.report.update(source_id=source['id'],source_contract=source)
        accepted=pulse['accepted'];failed=pulse.get('status')=='native_transport_failed'
        counts=dict(initial_primaries=1,initial_decays=1,zero_deposit_primaries=0,groups=1,accepted=int(accepted),rejected=int(not accepted),
            native_failed_groups=int(failed),readout_rejected=int(not accepted and not failed),
            line_photons=self.truth[0]['line_photon_count'],decay_photons=self.truth[0]['decay_photon_count'],
            line_photon_counts=copy.deepcopy(self.truth[0]['line_photon_counts']))
        self.report['counts']=counts
        native=H.LEGACY_NATIVE_SHA256 if legacy else W.sha(W.ROOT/'simulation/native_response.jl')
        self.report['source_sha256']['native_response.jl']=native
        self.request['source_sha256']['simulation/native_response.jl']=native
        self.resolved['source_sha256']['simulation/native_response.jl']=native
        key=H.LEGACY_KEY if legacy else H.DIAGNOSTIC_KEY
        h=dict(width_keV=5,normalization_denominators=counts,note=H.NOTE,
            bins=[H.row(stage,202,1,counts,key) for stage in
                (['deposited_per_decay','deposited_per_group','accepted_peak_ADC'] if accepted else ['deposited_per_decay','deposited_per_group'])])
        H.attach(h,None if legacy else H.descriptor(source['id'],source,root=self.base))
        W.write(self.out/'histograms.json',h);self.write_csv(h,key)
        W.write(self.out/'readout-config.json',dict(self.resolved['electronics_configuration'],expected_primary_count=1))
        (self.out/'truth.jsonl').write_text(json.dumps(self.truth[0])+'\n',encoding='utf-8')
        self.write_scalars(pulse);self.reseal()

    def write_csv(self,h,key):
        with (self.out/'histograms.csv').open('w',encoding='utf-8',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=H.fields(key));writer.writeheader();writer.writerows(h['bins'])

    def write_scalars(self,pulse):
        (self.out/'scalars.jsonl').write_text('\n'.join(json.dumps(v) for v in [self.primary,pulse])+'\n',encoding='utf-8')

    def reseal(self):
        self.report['configuration_sha256']=W.digest(self.resolved)
        self.report['artifacts']={p.name:W.sha(p) for p in self.out.iterdir() if p.name not in ('run.json','workflow-decay-response.json')}
        W.write(self.base/'decay-request.json',self.request);self.report['request_sha256']=W.sha(self.base/'decay-request.json')
        W.write(self.out/'run.json',self.report)
        W.write(self.out/'workflow-decay-response.json',dict(self.report,kind='workflow_decay_response_v1',
            native_report_sha256=W.sha(self.out/'run.json'),source_sha256=self.request['source_sha256']))

    def validate(self,pulse,*,route=False,refresh=True,legacy=False):
        if refresh:self.prepare(pulse,legacy=legacy)
        with patch.object(V,'request',return_value=self.request),patch.object(V,'ledger',return_value=self.truth):
            return W.validate_stage(self.base,'response',self.resolved,root=self.base) if route else V.response(self.base,self.resolved,self.report,root=self.base)
    def test_successful_pulse_without_status_matches_real_native_schema(self):
        self.assertNotIn('status',self.pulse)
        self.assertIs(self.validate(self.pulse),self.report)
    def test_native_failure_explicit_status_requires_null_unknown_quantities(self):
        pulse=dict(self.pulse,status='native_transport_failed',accepted=False)
        nulls=('readout','final_induced_keV','transport_flags','charge_end_ns','native_any_negative_charge',
            'native_min_charge_keV','native_max_charge_keV','endpoints','current_nA','induced_charge_fC')
        pulse.update({k:None for k in nulls})
        self.assertIs(self.validate(pulse),self.report)
        pulse['final_induced_keV']=0
        with self.assertRaises(W.ControlError):self.validate(pulse)

    def test_actual_stage_route_reaches_shared_histogram_gate(self):
        with patch.object(H,'validate',wraps=H.validate) as checked:
            inventory=self.validate(self.pulse,route=True)
        checked.assert_called_once();self.assertIn('histograms.json',inventory)

    def test_actual_route_refuses_three_rehashed_contract_corruptions(self):
        for case in ('window','csv','stripped'):
            with self.subTest(case=case):
                self.prepare(self.pulse);h=W.read(self.out/'histograms.json')
                if case=='window':
                    h['normalization']['diagnostic_lines'][0]['window_keV']=[660,663];W.write(self.out/'histograms.json',h)
                elif case=='csv':
                    path=self.out/'histograms.csv';path.write_text(path.read_text().replace(H.DIAGNOSTIC_KEY,H.LEGACY_KEY))
                else:
                    h.pop('normalization');h.pop('schema_version')
                    for row in h['bins']:row[H.LEGACY_KEY]=row.pop(H.DIAGNOSTIC_KEY)
                    W.write(self.out/'histograms.json',h);self.write_csv(h,H.LEGACY_KEY)
                self.reseal()
                with self.assertRaises(W.ControlError):self.validate(self.pulse,route=True,refresh=False)

    def test_actual_route_accepts_known_source_bound_historical_alias(self):
        inventory=self.validate(self.pulse,route=True,legacy=True)
        self.assertIn('histograms.csv',inventory)
        h=W.read(self.out/'histograms.json');before=W.sha(self.out/'histograms.json')
        interpreted=H.validate(h,self.report['counts'],self.report['source_id'],self.report['source_contract'],
            self.report['source_sha256'],root=self.base,csv_path=self.out/'histograms.csv')
        self.assertEqual(interpreted['legacy_alias']['interpreted_key'],H.DIAGNOSTIC_KEY)
        self.assertEqual(W.sha(self.out/'histograms.json'),before)

    def test_report_only_legacy_downgrade_cannot_override_checked_request_authority(self):
        self.prepare(self.pulse)
        request_pins=copy.deepcopy(self.request['source_sha256']);resolved_pins=copy.deepcopy(self.resolved['source_sha256'])
        h=W.read(self.out/'histograms.json');h.pop('normalization');h.pop('schema_version')
        for row in h['bins']:row[H.LEGACY_KEY]=row.pop(H.DIAGNOSTIC_KEY)
        W.write(self.out/'histograms.json',h);self.write_csv(h,H.LEGACY_KEY)
        self.report['source_sha256']['native_response.jl']=H.LEGACY_NATIVE_SHA256;self.reseal()
        self.assertEqual(self.request['source_sha256'],request_pins)
        self.assertEqual(self.resolved['source_sha256'],resolved_pins)
        self.assertEqual(W.read(self.out/'workflow-decay-response.json')['source_sha256'],request_pins)
        with self.assertRaisesRegex(W.ControlError,'historical exporter authority'):
            self.validate(self.pulse,route=True,refresh=False)

    def test_actual_route_refuses_rehashed_named_window_swaps_and_totals(self):
        for source in ('ba133_point_decay_v1','co60_point_decay_v1'):
            p=D.preset(source);self.resolved['selection']['source']=source;self.resolved['decay_source_contract']=p
            names=[x['name'] for x in p['diagnostic_lines']]
            self.truth[0].update(line_photon_counts={names[0]:6,names[1]:1},line_photon_count=7,decay_photon_count=7)
            for case in ('swap','total','ratio'):
                with self.subTest(source=source,case=case):
                    self.prepare(self.pulse);counts=self.report['counts'];h=W.read(self.out/'histograms.json')
                    if case=='swap':counts['line_photon_counts']={names[0]:1,names[1]:6}
                    if case=='total':counts.update(line_photon_counts={names[0]:7,names[1]:1},line_photons=8)
                    h['normalization_denominators']=counts
                    h['bins']=[H.row(row['stage'],row['bin'],row['count'],counts,H.DIAGNOSTIC_KEY) for row in h['bins']]
                    if case=='ratio':h['bins'][0][H.DIAGNOSTIC_KEY]=.5
                    W.write(self.out/'histograms.json',h);self.write_csv(h,H.DIAGNOSTIC_KEY);self.reseal()
                    with self.assertRaises(W.ControlError):self.validate(self.pulse,route=True,refresh=False)
if __name__=='__main__':unittest.main()
