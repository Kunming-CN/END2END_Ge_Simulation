"""Changed gamma seams only: saved input reads and synthetic products, no science."""
import copy
import csv
import json
from pathlib import Path
import tempfile
import unittest

import gamma_native_example as A
import nonzero_events as N
import scenario_workflow as W


class GammaOptions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base=A.ROOT/A.SOURCE/'SAP22'
        cls.manifest=A.decode((base/'stream/manifest.json').read_text(encoding='utf-8-sig'))
        cls.prepared=A.decode((base/'prepared.json').read_text(encoding='utf-8-sig'))
        cls.events=[A.decode(line) for line in (base/'stream'/cls.manifest['chunks'][0]['file']).read_text(encoding='utf-8-sig').splitlines()]

    def options(self,energy=1000,pose='nominal'):
        m=copy.deepcopy(self.manifest);p=copy.deepcopy(self.prepared);events=copy.deepcopy(self.events)
        marker={'kind':'portable_gamma_source_configuration_v1','schema_version':1,'canonical_preset':A.GAMMA_CANONICAL,
            'energy_keV':energy,'source_pose':pose,'position_global_mm':[0,37.073,.290] if pose=='nominal' else [0,42.073,.290],
            'direction_global':[0,-1,0],'time_ns':0,'units':{'energy':'keV','length':'mm','time':'ns','direction':'dimensionless'}}
        for document in (m,p):document.update(gamma_source_configuration=copy.deepcopy(marker),source_position_global_mm=marker['position_global_mm'])
        p['instance']['source_pose']=pose
        for event in events:
            event['particles'][0].update(ekin=energy/1000,py=-energy/1000)
            event['vtx'][0]['yloc']=marker['position_global_mm'][1]/1000
        zero=sum(not N.has_nonzero_deposit(e) for e in events)
        m['event_storage']=N.descriptor(20,zero)
        m['initial_summary']={'initial_primaries':20,'initial_gamma_primaries':20,'zero_deposit_primaries':zero,'nonzero_primaries':20-zero}
        return list(N.nonzero_events(events)),m,p

    def test_historical_dense_662_plus5_remains_strict(self):
        A.validate_events(self.events,self.manifest,self.prepared)
        bad=copy.deepcopy(self.manifest);bad['source_position_global_mm']=[0,37.073,.290]
        with self.assertRaises(A.C.Rejected):A.validate_events(self.events,bad,self.prepared)
        events=copy.deepcopy(self.events);events[0]['particles'][0]['ekin']=1
        with self.assertRaises(A.C.Rejected):A.validate_events(events,self.manifest,self.prepared)

    def test_explicit_energy_pose_sparse_census_and_original_ids(self):
        events,m,p=self.options();A.validate_events(events,m,p)
        self.assertEqual([e['event_id'] for e in events],[e['event_id'] for e in self.events if not e['zero_ge']])
        self.assertEqual(m['event_storage']['efficiency_denominator'],20)
        self.assertEqual(m['assets']['source']['kinetic_energy_keV'],662)
        self.assertTrue(all(e['particles'][0]['ekin']==1 for e in events))

    def test_effective_marker_momentum_and_row_identity_are_independent_gates(self):
        for mutate in (
            lambda e,m,p:m['gamma_source_configuration'].update(energy_keV=True),
            lambda e,m,p:m['gamma_source_configuration'].update(direction_global=[1,0,0]),
            lambda e,m,p:p['instance']['source'].update(sha256='0'*64),
            lambda e,m,p:e[0]['particles'][0].update(ekin=.662),
            lambda e,m,p:e[0].update(initial_primary_id=True),
            lambda e,m,p:e.reverse(),
            lambda e,m,p:m['initial_summary'].update(zero_deposit_primaries=0),
        ):
            events,m,p=self.options();mutate(events,m,p)
            with self.subTest(mutate=mutate),self.assertRaises((A.C.Rejected,W.ControlError)):
                A.validate_events(events,m,p)

    def test_saved_plan_binds_exact_effective_gamma_source(self):
        _,m,_=self.options();marker=m['gamma_source_configuration']
        selection={'name':'p4-plan-configuration-fixture','cryostat':W.CRYOSTAT,'detector':'SAP22','source':W.GAMMA,
            'pose':'nominal','gamma_energy_keV':1000,'primary_count':20,'seed':26092631,'threads':2,
            'electronics':W.read(W.ROOT/'simulation/native_readout_profile.json')['settings']}
        portable={'kind':'portable_source_checked_plan_v1','schema_version':1,'request':W.portable_request(selection),
            'portable_source_sha256':{'synthetic-not-executed':'a'*64},'gamma_source_configuration':marker}
        plan=W.check(selection,pin_reader=lambda model,root:{'synthetic-not-executed':'a'*64},
            runtime_reader=lambda threads:{'python_sha256':'b'*64,'julia_sha256':'c'*64},portable_reader=lambda config,root:portable)
        W.saved_plan(plan)
        for mutate in (
            lambda r:r['gamma_source_configuration'].update(energy_keV=1001),
            lambda r:r['selection'].update(gamma_energy_keV=662),
            lambda r:r.update(source_position_global_mm=[0,42.073,.290]),
            lambda r:r['portable_source_plan']['request'].update(gamma_energy_keV=662),
        ):
            changed=copy.deepcopy(plan);mutate(changed['resolved']);changed['configuration_sha256']=W.digest(changed['resolved'])
            with self.subTest(mutate=mutate),self.assertRaises(W.ControlError):W.saved_plan(changed)

    def synthetic_products(self,failed=False):
        events,m,p=self.options();events=events[:2];policy=N.descriptor(20,18)
        marker=m['gamma_source_configuration'];request={'events':events,'event_storage':policy,'gamma_source_configuration':marker}
        cases=[]
        for i,event in enumerate(events):
            case={'event_id':event['event_id'],'initial_primary_id':event['initial_primary_id'],'zero_ge':False,
                'truth_ge_edep_keV':event['truth_ge_edep_keV'],'raw_row_indices':[s['raw_row_index'] for s in event['steps']],
                'status':'native_completed','error':None,'native':{'times':[0.0,2.0,4.0],'signal':[0.0,-.25,-.5]},
                'transport_flags':{},'charge_input':{'time_since_initial_primary_ns':[0.0,2.0,4.0],'induced_equivalent_energy_keV':[0.0,-.25,-.5]},
                'final_induced_keV':-.5,'charge_end_ns':4.0,'readout':{'accepted':False,'trace':{'signed_test':[-.25,-.5]}}}
            if failed and i==0:
                case.update(status='native_failed',error={'type':'ArgumentError','message':A.FAILURES[0]})
                for key in ('native','transport_flags','charge_input','final_induced_keV','charge_end_ns','readout'):case[key]=None
            cases.append(case)
        report={'cases':cases,'event_storage':policy,'gamma_source_configuration':marker,'calibration_calls':1,'ionisation_energy_eV':2.95,
            'calibration':{'energy_keV':500,'time_step_ns':2,'ionisation_energy_eV':2.95,'charge_C':500000/2.95*1.602176634e-19,'peak_V':1,'volts_per_keV':1/500},
            'counts':{'initial_primaries':20,'zero_deposit_primaries':18,'nonzero_primaries':2,'groups':2,'accepted':0,
                'native_failed_groups':int(failed),'readout_rejected':2-int(failed),'rejected':2,'processed_primaries':20,'unprocessed_primaries':0}}
        return request,report

    def write_products(self,directory,request,report):
        out=directory/'response';out.mkdir()
        rows=lambda name,values:(out/name).write_text(''.join(json.dumps(value,allow_nan=False)+'\n' for value in values),encoding='utf-8')
        rows('truth.jsonl',request['events']);rows('scalars.jsonl',report['cases'])
        rows('traces.jsonl',[{'event_id':c['event_id'],'group_id':0,'origin_time_ns':0.0,'trace':c['readout']['trace']} for c in report['cases'] if c['readout'] is not None])
        for case in report['cases']:W.write(out/('event-'+str(case['event_id'])+'.json'),case,fresh=True)
        with (out/'signals.csv').open('w',encoding='utf-8',newline='') as stream:
            writer=csv.writer(stream);writer.writerow(A.SIGNAL_COLUMNS)
            for case in report['cases']:
                if case['charge_input'] is not None:
                    writer.writerows([case['initial_primary_id'],t,q] for t,q in zip(case['charge_input']['time_since_initial_primary_ns'],case['charge_input']['induced_equivalent_energy_keV']))

    def test_saved_nonzero_signed_rejected_and_failure_products(self):
        base=W.ROOT/'.local/gamma-options-p4';base.mkdir(exist_ok=True)
        for failed in (False,True):
            with tempfile.TemporaryDirectory(dir=base) as temporary:
                directory=Path(temporary);request,report=self.synthetic_products(failed);self.write_products(directory,request,report)
                W.gamma_response_census(directory,request,report,request['event_storage'])
                self.assertEqual(report['event_storage']['efficiency_denominator'],20)
                if failed:
                    report['cases'][0]['final_induced_keV']=0.0
                    with self.assertRaises(W.ControlError):W.gamma_response_census(directory,request,report,request['event_storage'])
                else:
                    with (directory/'response/signals.csv').open('a',encoding='utf-8') as stream:stream.write('0,0,0\n')
                    with self.assertRaises(A.C.Rejected):W.gamma_response_census(directory,request,report,request['event_storage'])


if __name__=='__main__':unittest.main()
