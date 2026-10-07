"""Public synthetic source contracts; never launches radiation, fields or drift."""
import copy, tempfile, unittest
from pathlib import Path
import h5py
import decay_source as d
import test_cs137 as fixtures
import handoff as h
class SharedDecayTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.presets=[p for p in d.D.presets(h.ROOT) if p['adapter']==d.ADAPTER]
    def fixture(self,p,name='truth'):
        path=self.root/(name+'.lh5');meta=fixtures.fixture(path)
        meta.update(source_contract=p,source_position_global_mm=[0,0,0])
        with h5py.File(path,'r+') as f:
            f['particles/particle'][:]=p['pdg']
            for i in range(3):
                f['tracks/particle'][i*3]=p['pdg'];f['tracks/particle'][i*3+1]=p['ground_daughter_pdg']
                f['tracks/time'][i*3+2]=67.2+i
            f['stp/germanium/time'][:]=[67.2,68.2,100068.2]
        return path,meta
    def test_all_three_share_macro_without_monogamma_or_nucleuslimits(self):
        report={'volumes':[{'name':'ledger_0_PV','copy_number':0},{'name':'germanium','copy_number':1}]}
        for p in self.presets:
            text=d.macro_text(report,500,p,p['position_global_mm'])
            for value in (f'/gps/ion {p["Z"]} {p["A"]}','/gps/energy 0 eV','/run/beamOn 500',
                'ResetInitialDecayTime true','DaughterNucleusMaxLifetime 100000 ns','thresholdForVeryLongDecayTime 1e27 ns'):
                self.assertIn(value,text)
            self.assertNotIn('nucleusLimits',text);self.assertNotIn('/gps/ang/direction',text);self.assertNotIn('ledger_0_PV',text)
    def test_complete_initial_zeros_raw_time_and_rows_for_each_source(self):
        for p in self.presets:
            path,meta=self.fixture(p,p['isotope']);events=list(d.iter_decays(path,meta))
            self.assertEqual([e['event_id'] for e in events],[0,1,2])
            self.assertEqual([len(e['steps']) for e in events],[3,0,0])
            self.assertTrue(all(e['source_id']==p['id'] for e in events))
            self.assertEqual(events[0]['steps'][0]['energy_keV'],0)
            self.assertEqual(events[0]['steps'][2]['time_ns'],100068.2)
            self.assertEqual([g['row_indices'] for g in events[0]['pulse_groups']],[[1],[2]])
            self.assertEqual(events[2]['tracks'][2]['time'],69.2)
    def test_photons_from_atomic_em_processes_are_retained_not_selected(self):
        p=self.presets[0];path,meta=self.fixture(p)
        with h5py.File(path,'r+') as f:f['processes/name'][1]='eBrem'
        events=list(d.iter_decays(path,meta))
        self.assertEqual([e['decay_photon_count'] for e in events],[1,1,1])
        self.assertEqual(events[0]['decay_photons'][0]['creation_process'],'eBrem')
        self.assertEqual(events[0]['line_photon_count'],0)
        self.assertEqual(len(events[0]['steps']),3)
    def test_ground_code_prompt_gamma_preserved_long_ground_chain_rejected(self):
        path,meta=self.fixture(self.presets[0]);self.assertEqual(len(list(d.iter_decays(path,meta))),3)
        with h5py.File(path,'r+') as f:f['tracks/time'][2]=1e20
        with self.assertRaisesRegex(ValueError,'cap'):list(d.iter_decays(path,meta))
    def test_excited_code_prompt_gamma_preserved_suffix_not_excitation_claim(self):
        path,meta=self.fixture(self.presets[0])
        with h5py.File(path,'r+') as f:f['tracks/particle'][1]=meta['source_contract']['ground_daughter_pdg']+1
        self.assertEqual(len(list(d.iter_decays(path,meta))),3)
    def test_unexpected_pa_chain_and_invalid_graph_fail(self):
        for name,table,column,row,value in (
            ('pa','tracks','particle',2,1000912330),('wrongroot','particles','particle',0,22),
            ('cycle','tracks','parent_trackid',2,3),('missing','tracks','parent_trackid',2,99),
            ('childclock','tracks','time',1,1),('precede','tracks','time',2,-1),
            ('census','vtx','evtid',1,0),('depositbefore','stp/germanium','time',1,1)):
            path,meta=self.fixture(self.presets[0],name)
            with h5py.File(path,'r+') as f:f[table][column][row]=value
            with self.subTest(name=name),self.assertRaises(ValueError):list(d.iter_decays(path,meta))
    def test_double_units_precision_missing_material_uid_census(self):
        for mode in ('units','precision','missing','alias'):
            path,meta=self.fixture(self.presets[1],mode)
            with h5py.File(path,'r+') as f:
                if mode=='units':f['tracks/ekin'].attrs['units']='keV'
                elif mode=='precision':
                    v=f['tracks/ekin'][:];del f['tracks/ekin'];ds=f['tracks'].create_dataset('ekin',data=v,dtype='float32');ds.attrs['units']='MeV'
                elif mode=='missing':meta['material_tables']['stp/missing']='G4_Al'
                else:
                    g=f['stp'].create_group('__by_uid__');g['det1']=h5py.SoftLink('/tracks')
            with self.subTest(mode=mode),self.assertRaises(ValueError):list(d.iter_decays(path,meta))
    def test_source_data_modes_are_data_entries_not_combination_templates(self):
        self.assertEqual({p['decay_mode'] for p in self.presets},{'alpha','beta_minus','electron_capture'})
        for p in self.presets:self.assertEqual(d.D.validate_source(p),p)
        for model in d.W.MODELS:
            points,probes,volume=d.geometry_contract(model)
            self.assertGreater(volume,0);self.assertTrue(points and probes)
    def test_isotope_does_not_change_exporter_geometric_parameters(self):
        mounts=[d.scenario(p['id']) for p in self.presets]
        params=[d.P.parameter_text(s,s['source']['position_global_mm'],False) for s in mounts]
        self.assertEqual(params,[params[0]]*3)
        self.assertEqual([s['coordinate_transform'] for s in mounts],[mounts[0]['coordinate_transform']]*3)
    def test_original_build_bound_inputs_match_public_pins(self):
        # The protected public adapter map is independent of ignored milestone evidence.
        d.P.recheck_map(d.P.PINNED,h.ROOT)
if __name__=='__main__':unittest.main()
