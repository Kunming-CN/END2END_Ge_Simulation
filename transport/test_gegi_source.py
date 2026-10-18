"""Synthetic flat-LH5 isotope identity, timing and sparse-output checks; no science."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import gegi_source as S
sys.path.insert(0,str(S.h.ROOT/'tools'))
import gegi_workflow as W


def selection(source=S.SOURCE):
    value={'name':'gegi-source-fixture','cryostat':'gegi_cryostat_v1','detector':'GeGI_3D',
           'source':source,'pose':'custom','primary_count':2,'seed':26101731,'threads':1,
           'electronics':{},'source_position_mm':[-40.1234567890123,0.,40.],
           'gamma_energy_keV':662. if source==S.SOURCE else None}
    return value


class GeGISourceContracts(unittest.TestCase):
    def checked(self,source=S.SOURCE):
        value=selection(source)
        with patch.object(S,'runtime_snapshot',return_value={'fixture':True}),\
             patch.object(S,'isotope_data',return_value={'fixture':'recorded isotope data'}):
            return S.check(value)

    def test_registered_isotopes_keep_registry_and_explicit_count_units(self):
        for source,isotope,pdg in ((S.CS137,'Cs137',S.cs.ION),(S.CO60,'Co60',1000270600)):
            checked=self.checked(source);contract=checked['source_contract']
            self.assertEqual(contract['registered_preset'],S.registered_preset(source))
            self.assertEqual(contract['count_unit'],'initial '+isotope+' decays')
            self.assertEqual(contract['pdg'],pdg);self.assertEqual(contract['kinetic_energy_keV'],0)
            self.assertNotIn('energy_keV',contract)
            self.assertEqual(contract['position_global_mm'],selection(source)['source_position_mm'])
            self.assertEqual(contract['grouping_policy'],S.cs.POLICY)
            self.assertEqual(contract['daughter_lifetime_limit_ns'],-1 if source==S.CS137 else 100000)
            for ref in ('transport/decay_source.py','tools/decay_workflow.py',S.REGISTRY):
                self.assertEqual(checked['source_sha256'][ref],S.h.sha256(S.h.ROOT/ref))

    def test_isotope_macros_delegate_real_ion_and_clock_semantics(self):
        for source,ion,cap in ((S.CS137,'55 137','-1'),(S.CO60,'27 60','100000')):
            checked=self.checked(source);text=S.macro(checked)
            report={'volumes':[{'name':'germanium','copy_number':0},*S.G.layout(checked['cryostat_contract'])['parts']]}
            original=(S.cs.macro_text(report,2,selection(source)['source_position_mm']) if source==S.CS137 else
                      S.decay.macro_text(report,2,checked['source_contract']['registered_preset'],selection(source)['source_position_mm']))
            self.assertTrue(text.endswith(original.replace('/gps/pos/centre ',
                '/control/useDoublePrecision true\n/gps/pos/centre ',1)))
            for line in ('/gps/particle ion','/gps/ion '+ion,'/gps/energy 0 eV',
                         '/RMG/Processes/Stepping/ResetInitialDecayTime true',
                         '/RMG/Processes/Stepping/DaughterNucleusMaxLifetime '+cap+' ns','/run/beamOn 2'):
                self.assertIn(line,text)
            self.assertNotIn('/gps/ene/mono',text);self.assertNotIn('/gps/ang/direction',text)
            self.assertIn(' '.join(format(v,'.17g') for v in selection(source)['source_position_mm'])+' mm',text)
            geometry=S.macro(checked,True)
            self.assertNotIn('/run/beamOn',geometry);self.assertNotIn('/gps/',geometry)

    def test_gamma_macro_retains_original_generator_and_zero_clock(self):
        checked=self.checked();text=S.macro(checked)
        for line in ('/gps/particle gamma','/gps/ang/type iso','/gps/ene/mono 662 keV',
                     '/gps/time 0 ns','/gps/number 1','/run/beamOn 2'):
            self.assertIn(line,text)
        self.assertNotIn('/gps/particle ion',text)
        self.assertNotIn('ResetInitialDecayTime',text)
        self.assertNotIn('DaughterNucleusMaxLifetime',text)
        self.assertNotIn('/control/useDoublePrecision',text)
        self.assertEqual(checked['source_contract']['count_unit'],'emitted gamma')

    def test_workflow_and_transport_refuse_mislabelling_and_unbounded_batches(self):
        invalid=[dict(selection(S.CS137),gamma_energy_keV=662),
                 dict(selection(S.CO60),primary_count=10001),dict(selection(S.CS137),primary_count=True),
                 dict(selection(S.CO60),source='am241_point_decay_v1'),
                 dict(selection(S.CS137),cryostat='lbnl_modular_nominal_v1'),
                 dict(selection(S.CO60),source_position_mm=[False,0,40]),
                 dict(selection(),gamma_energy_keV=None)]
        for value in invalid:
            with self.subTest(selection=value),self.assertRaises((ValueError,W.W.ControlError)):
                S.check(value)
            with self.subTest(workflow=value),self.assertRaises(W.W.ControlError):
                W.validate_selection(value)
        for source in (S.CS137,S.CO60):
            for include_null in (False,True):
                value=selection(source)
                if not include_null:value.pop('gamma_energy_keV')
                self.assertIs(W.validate_selection(value),value)
                with patch.object(S,'runtime_snapshot',return_value={}),patch.object(S,'isotope_data',return_value={}):
                    self.assertEqual(S.check(value)['selection'],value)


class GeGILH5(unittest.TestCase):
    def setUp(self):
        try:
            import h5py
        except ImportError:
            self.skipTest('Run flat-LH5 tests in the existing locked transport Python with h5py')
        self.h5py=h5py
        self.temp=tempfile.TemporaryDirectory(prefix='gegi-isotope-reader-',dir=S.h.ROOT/'.local')
        self.addCleanup(self.temp.cleanup);self.directory=Path(self.temp.name);self.path=self.directory/'truth.lh5'

    def table(self,raw,path,rows,integers=(),floats=None,strings=()):
        table=raw.create_group(path);floats=floats or {}
        for key in sorted(set(integers)|set(floats)|set(strings)):
            dtype='i8' if key in integers else 'f8' if key in floats else self.h5py.string_dtype('utf-8')
            ds=table.create_dataset(key,data=[row[key] for row in rows],dtype=dtype)
            ds.attrs['units']=floats.get(key,'')
        return table

    def fixture(self,source=S.CS137,mutate=None):
        chosen=selection(source);cryostat=S.G.load_cryostat();contract=S.source_contract(chosen,cryostat)
        position=chosen['source_position_mm'];vertices=[];particles=[];tracks=[];steps=[]
        for eid in range(2):
            vertices.append(dict(evtid=eid,n_part=1,time=0.,**dict(zip(('xloc','yloc','zloc'),[p/1000 for p in position]))))
            particles.append(dict(evtid=eid,particle=contract['pdg'],vertexid=0,ekin=0.,px=0.,py=0.,pz=0.))
            def track(tid,parent,pdg,time=0.,energy=0.,point=position,procid=1):
                row=dict(evtid=eid,trackid=tid,parent_trackid=parent,particle=pdg,procid=procid,
                         time=time,ekin=energy,px=0.,py=0.,pz=energy if pdg==22 else 0.)
                row.update(zip(('xloc','yloc','zloc'),[p/1000 for p in point]));tracks.append(row)
            track(1,0,contract['pdg'],procid=-1)
            track(2,1,1000561371 if source==S.CS137 else 1000280600)
            track(3,1,11,energy=.1)
            late=200000.25 if source==S.CS137 else 0.
            track(4,2,22,time=late,energy=.6617 if source==S.CS137 else 1.173239)
            track(5,4,11,time=late+.1,energy=.2,point=[0.,0.,0.],procid=2)
            if source==S.CO60:track(6,2,22,energy=1.332514)
            if eid==1:
                for tid,parent,energy,time in ((3,1,20.,1.),(5,4,100.,late+.5)):
                    row=dict(evtid=eid,trackid=tid,parent_trackid=parent,particle=11,edep=energy,time=time)
                    row.update({axis+suffix:0. for suffix in ('','_pre','_post') for axis in ('xloc','yloc','zloc')})
                    row.update({name:0.001 for name in ('dist_to_surf','dist_to_surf_pre','dist_to_surf_post')});steps.append(row)
        processes=[{'procid':1,'name':'RadioactiveDecay'},{'procid':2,'name':'compt'}]
        bundle={'vertices':vertices,'particles':particles,'tracks':tracks,'steps':steps,'processes':processes}
        if mutate:mutate(bundle)
        with self.h5py.File(self.path,'w') as raw:
            raw.create_dataset('number_of_simulated_events',data=2,dtype='i8')
            origins=self.table(raw,'detector_origins',[{'name':'germanium','xloc':0.,'yloc':0.,'zloc':0.}],
                               floats={a:'m' for a in ('xloc','yloc','zloc')},strings=('name',))
            origins.attrs['datatype']='table{name,xloc,yloc,zloc}'
            self.table(raw,'vtx',vertices,{'evtid','n_part'},{'time':'ns',**{a:'m' for a in ('xloc','yloc','zloc')}})
            self.table(raw,'particles',particles,{'evtid','particle','vertexid'},{a:'MeV' for a in ('ekin','px','py','pz')})
            self.table(raw,'tracks',tracks,{'evtid','parent_trackid','particle','procid','trackid'},
                       {'time':'ns',**{a:'m' for a in ('xloc','yloc','zloc')},**{a:'MeV' for a in ('ekin','px','py','pz')}})
            self.table(raw,'processes',processes,{'procid'},strings=('name',))
            floats={'edep':'keV','time':'ns',**{a:'m' for a in S.T.POSITIONS},
                    **{a:'m' for a in ('dist_to_surf','dist_to_surf_pre','dist_to_surf_post')}}
            self.table(raw,'stp/germanium',steps,S.T.STEP_INTS,floats)
        meta={'primary_count':2,'source_id':source,'source_contract':contract,'source_position_global_mm':position,
              'model_contract':S.G.load_model(),'cryostat_contract':cryostat,'coordinate_transform':S.G.TRANSFORM,
              'material_tables':{'stp/germanium':'G4_Ge'},'seed':chosen['seed'],'random_engine':'CLHEP::HepJamesRandom','source_sha256':{}}
        meta.update(S.decay_metadata({'source_contract':contract,'decay_data':{'synthetic_test':True}}))
        return meta

    def test_delayed_cs137_groups_keep_original_times_rows_and_all_initial_denominators(self):
        meta=self.fixture();events=list(S.events(self.path,meta));first=events[1]
        self.assertEqual([e['event_id'] for e in events],[0,1]);self.assertEqual(events[0]['steps'],[])
        self.assertEqual(first['global_decay_id'],first['initial_primary_id'])
        self.assertEqual(first['truth_edep_keV'],120.)
        self.assertEqual(first['pulse_groups'],S.cs.group_deposits(first['steps'],100000))
        self.assertEqual([g['row_indices'] for g in first['pulse_groups']],[[0],[1]])
        self.assertEqual([g['origin_time_ns'] for g in first['pulse_groups']],[1.,200000.75])
        self.assertEqual(first['decay_photons'][0]['time_ns'],200000.25)
        counts=S.census(self.path,meta)
        for key,value in {'initial_primaries':2,'initial_decays':2,'zero_deposit_primaries':1,
                          'nonzero_primaries':1,'positive_ge_rows':2,'pulse_groups':2,'decay_photons':2,'line_photons':2}.items():
            self.assertEqual(counts[key],value,key)
        self.assertEqual(counts['nonzero_event_ids'],[1])

    def test_co60_prompt_cascade_counts_two_photons_per_initial_nucleus(self):
        meta=self.fixture(S.CO60);counts=S.census(self.path,meta)
        self.assertEqual(counts['initial_decays'],2);self.assertEqual(counts['decay_photons'],4)
        self.assertEqual(counts['line_photon_counts'],{'Ni60_1173.239':2,'Ni60_1332.514':2})
        self.assertEqual(counts['pulse_groups'],1)

    def add_conversion(self,bundle,pdg=1000320700,point=(0.,0.,0.),scored=True):
        """Synthetic pair final state, not a generated/calibrated decay spectrum."""
        gamma=next(t for t in bundle['tracks'] if t['evtid']==1 and t['trackid']==4)
        gamma['ekin']=gamma['pz']=1.332514
        bundle['processes'].append({'procid':3,'name':'conv'})
        for tid,particle,energy in ((7,11,.2),(8,-11,.1105),(9,pdg,.000005)):
            row=dict(gamma,trackid=tid,parent_trackid=4,particle=particle,procid=3,
                     time=gamma['time']+.2,ekin=energy,px=0.,py=0.,pz=0.)
            row.update(zip(('xloc','yloc','zloc'),point));bundle['tracks'].append(row)
        if scored:
            step=dict(bundle['steps'][-1],trackid=9,parent_trackid=4,particle=pdg,
                      time=row['time'],edep=.005)
            step.update({axis+suffix:v for suffix in ('','_pre','_post')
                         for axis,v in zip(('xloc','yloc','zloc'),point)})
            bundle['steps'].append(step)

    def test_conversion_recoil_keeps_rows_energy_and_initial_denominators_for_both_readers(self):
        for source in (S.CS137,S.CO60):
            meta=self.fixture(source,self.add_conversion);events=list(S.events(self.path,meta))
            self.assertEqual([e['event_id'] for e in events],[0,1])
            self.assertEqual([t['trackid'] for t in events[1]['tracks']][-3:],[7,8,9])
            self.assertEqual(events[1]['steps'][-1]['particle_pdg'],1000320700)
            self.assertEqual(events[1]['steps'][-1]['energy_keV'],.005)
            self.assertEqual(events[1]['steps'][-1]['raw_row_index'],2)
            self.assertEqual(events[1]['truth_edep_keV'],120.005)
            counts=S.census(self.path,meta)
            self.assertEqual((counts['initial_decays'],counts['zero_deposit_primaries'],
                              counts['nonzero_primaries'],counts['positive_ge_rows']),(2,1,1,3))

    def test_world_air_conversion_needs_geometric_material_evidence(self):
        for source in (S.CS137,S.CO60):
            for z,a in S.decay.CONVERSION_TARGET_ISOTOPES['G4_AIR']:
                pdg=1000000000+10000*z+10*a
                meta=self.fixture(source,lambda b:self.add_conversion(b,pdg,(.1,0.,0.),False))
                events=list(S.events(self.path,meta))
                self.assertEqual(events[1]['tracks'][-1]['particle'],pdg)
                self.assertEqual(len(events[1]['steps']),2)  # No fabricated air step.
                self.assertEqual(events[1]['truth_edep_keV'],120.)
        layout=S.G.layout(meta['cryostat_contract']);world=meta['cryostat_contract']['world']['half_width_mm']/1000
        invalid_points=[(0.,0.,0.),(0.,0.,-.006),
                        (layout['vacuum_radius_mm']/1000,0.,0.),(world,0.,0.),(world+.001,0.,0.)]
        for point in invalid_points:
            with self.subTest(point=point):
                meta=self.fixture(S.CO60,lambda b:self.add_conversion(b,1000070140,point,False))
                with self.assertRaisesRegex(ValueError,'Unexpected descendant nuclear family'):
                    list(S.events(self.path,meta))
        for pdg in (1000060140,1000070141,1000320700):
            meta=self.fixture(S.CO60,lambda b:self.add_conversion(b,pdg,(.1,0.,0.),False))
            with self.subTest(pdg=pdg),self.assertRaises(ValueError):list(S.events(self.path,meta))
        meta=self.fixture(S.CO60,lambda b:self.add_conversion(b,1000070140,(.1,0.,0.),False))
        meta['cryostat_contract']['world']['material']='G4_Galactic'
        with self.assertRaises(ValueError):list(S.events(self.path,meta))

    def test_scored_material_requires_exact_birth_step_and_supported_isotope(self):
        mutations={
            'missing birth step':lambda b:b['steps'].pop(),
            'wrong birth prepoint':lambda b:b['steps'][-1].update(xloc_pre=1e-12),
            'wrong birth time':lambda b:b['steps'][-1].update(time=b['steps'][-1]['time']+.001),
            'wrong birth identity':lambda b:b['steps'][-1].update(parent_trackid=2),
            'wrong material isotope':lambda b:(b['tracks'][-1].update(particle=1000130270),
                                               b['steps'][-1].update(particle=1000130270)),
            'missing positron':lambda b:b['tracks'].pop(-2),
            'wrong creator':lambda b:b['processes'][-1].update(name='compt'),
        }
        for source in (S.CS137,S.CO60):
            for name,mutate in mutations.items():
                def prepare(bundle):
                    self.add_conversion(bundle);mutate(bundle)
                with self.subTest(source=source,name=name):
                    meta=self.fixture(source,prepare)
                    with self.assertRaises(ValueError):list(S.events(self.path,meta))

    def test_sparse_extraction_keeps_counts_and_groups_without_zero_event_records(self):
        meta=self.fixture();counts=S.census(self.path,meta)
        for name in ('prepared.json','run.json','geometry.gdml','run.mac'):
            (self.directory/name).write_text('synthetic fixture',encoding='utf-8')
        receipt={'counts':counts,'source_lh5_sha256':S.h.sha256(self.path)}
        with patch.object(S,'read_run',return_value=(self.directory,meta,{},receipt)):
            manifest=S.extract(self.directory)
        lines=(self.directory/'stream/events.jsonl').read_text(encoding='utf-8').splitlines()
        self.assertEqual(len(lines),1);self.assertEqual(json.loads(lines[0])['event_id'],1)
        self.assertEqual(manifest['event_storage']['efficiency_denominator'],2)
        self.assertEqual(manifest['counts']['pulse_groups'],2)
        self.assertEqual(manifest['source_count_unit'],'initial Cs137 decays')
        self.assertEqual(manifest['daughter_lifetime_limit_ns'],-1)

    def test_wrong_ion_daughter_reset_clock_and_step_ancestry_are_refused(self):
        mutations=[lambda b:b['particles'][0].update(particle=22),
                   lambda b:b['tracks'][1].update(particle=1000280600),
                   lambda b:b['tracks'][2].update(time=1.),
                   lambda b:b['steps'][1].update(parent_trackid=999),
                   lambda b:b['steps'][1].update(time=100.),
                   lambda b:b['vertices'][0].update(xloc=0.)]
        for index,mutate in enumerate(mutations):
            with self.subTest(index=index):
                meta=self.fixture(mutate=mutate)
                with self.assertRaises(ValueError):list(S.events(self.path,meta))
        meta=self.fixture(S.CO60,lambda b:b['tracks'][3].update(time=100001.))
        with self.assertRaisesRegex(ValueError,'escaped cap'):list(S.events(self.path,meta))


if __name__=='__main__':unittest.main(verbosity=2)
