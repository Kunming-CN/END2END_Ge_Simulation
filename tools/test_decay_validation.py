"""Public saved-response regression fixtures; no raw data, physics or private evidence."""
import copy,json,math,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import decay_validation as V
import scenario_workflow as W
class ResponseValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name)
        self.out=self.base/'response';self.out.mkdir();(self.base/'transport').mkdir()
        source={'id':'synthetic_public_fixture'};model={'model_id':'SAP22'}
        self.resolved={'selection':{'source':source['id'],'detector':'SAP22','primary_count':1},
          'decay_source_contract':source,'source_sha256':{'public_source.py':'a'*64},
          'operating_model':{'signed_bias_V':700,'wiring_factor':1,'contact_potentials_V':{'1':0,'2':700}}}
        self.request={'source_sha256':self.resolved['source_sha256']}
        W.write(self.base/'decay-request.json',self.request);W.write(self.base/'transport/prepared.json',{'model_contract':model})
        cal={'energy_keV':500,'time_step_ns':2,'ionisation_energy_eV':2.95,
            'charge_C':500000/2.95*1.602176634e-19,'peak_V':.25,'volts_per_keV':.0005}
        self.report={'kind':'workflow_decay_native_response_v1','configuration_sha256':W.digest(self.resolved),
          'request_sha256':W.sha(self.base/'decay-request.json'),'source_id':source['id'],'source_contract':source,
          'model_contract':model,'signed_operating_bias_V':700,'wiring_factor':1,'contact_potentials_V':{'1':0,'2':700},
          'new_field_solution':True,'geometry_checks':{'field_cache_used':False},'independent_calibration_calls':1,
          'calibration':cal,'counts':{'groups':1}}
        W.write(self.out/'run.json',self.report)
        env=dict(self.report,kind='workflow_decay_response_v1',native_report_sha256=W.sha(self.out/'run.json'),
          source_sha256=self.request['source_sha256'])
        W.write(self.out/'workflow-decay-response.json',env)
        self.group={'group_id':0,'origin_time_ns':0,'row_indices':[0]}
        self.truth=[{'event_id':0,'global_decay_id':0,'steps':[{'raw_row_index':0,'energy_keV':10,'time_ns':0}],
            'pulse_groups':[self.group]}]
        self.primary={'record_kind':'decay','event_id':0,'global_decay_id':0,'zero_deposit':False,
            'deposited_energy_keV':10,'raw_row_indices':[0],'pulse_count':1}
        self.pulse={'record_kind':'pulse','event_id':0,'group_id':0,'origin_time_ns':0,'group':self.group,
            'raw_row_indices':[0],'deposited_energy_keV':10,'accepted':True,'readout':{}}
        (self.out/'truth.jsonl').write_text(json.dumps(self.truth[0])+'\n',encoding='utf-8')
    def validate(self,pulse):
        (self.out/'scalars.jsonl').write_text('\n'.join(json.dumps(v) for v in [self.primary,pulse])+'\n',encoding='utf-8')
        with patch.object(V,'request',return_value=self.request),patch.object(V,'ledger',return_value=self.truth):
            return V.response(self.base,self.resolved,self.report,root=self.base)
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
if __name__=='__main__':unittest.main()
