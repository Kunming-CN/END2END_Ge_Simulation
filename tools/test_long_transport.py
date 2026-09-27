"""Synthetic storage/recovery tests; no radiation simulation or SSD."""
import contextlib, json, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import h5py
import numpy as np
import long_transport as lt

def raw_fixture(path,zero=False):
    meta={'primary_count':2,'model_id':'AK02','material_tables':{'stp/germanium':'G4_Ge','stp/al':'G4_Al'},'decay_photon_line_window_keV':[660,663]}
    with h5py.File(path,'x') as f:
        f.create_dataset('number_of_simulated_events',data=2)
        for key in ('vtx','particles','tracks','stp/germanium','stp/al'):
            g=f.require_group(key); g.attrs['kind']='table'
            ids=np.array([0,1],dtype='int32') if key in ('vtx','particles','tracks') else np.array([0],dtype='int32')
            g.create_dataset('evtid',data=ids)
            if key=='tracks':
                for name,v in {'particle':[22,22],'procid':[7,7],'trackid':[2,2],'parent_trackid':[1,1]}.items():g.create_dataset(name,data=np.array(v,dtype='int32'))
                g.create_dataset('ekin',data=[.661657,.661657]).attrs['units']='MeV'
            if key.startswith('stp/'):
                g.create_dataset('edep',data=[0. if zero else (10. if key.endswith('germanium') else 3.)]).attrs['units']='keV'
                g.create_dataset('xloc',data=np.array([-0.],dtype='float64')).attrs['units']='m'
        procs=f.create_group('processes');procs.create_dataset('procid',data=[7]);procs.create_dataset('name',data=np.array(['RadioactiveDecay'],dtype=h5py.string_dtype()))
    return meta

def fake_events(path,meta):
    with h5py.File(path,'r') as f: g=float(f['stp/germanium/edep'][0]); a=float(f['stp/al/edep'][0])
    for i in range(2):
        yield {'event_id':i,'steps':[{'energy_keV':g}] if i==0 else [],'decay_photon_count':1,'line_photon_count':1,'material_energy_keV':{'G4_Ge':g if i==0 else 0.,'G4_Al':a if i==0 else 0.}}

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='unit-',dir=lt.ROOT/'.local/million-transport-dev');self.d=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def fixture(self,zero=False):
        raw=self.d/'input.lh5'; meta=raw_fixture(raw,zero); target=self.d/'compact.h5'
        with patch.object(lt.cs,'iter_decays',fake_events):counts=lt.compact(raw,meta,target,100)
        return raw,meta,target,counts
    def test_lossless_selection_and_ids(self):
        raw,meta,out,counts=self.fixture();self.assertEqual(counts['ge_positive'],1)
        with h5py.File(out) as f:
            self.assertEqual(f['events/global_decay_id'][:].tolist(),[100,101])
            self.assertEqual(f['details/stp/germanium/xloc'][:].tobytes(),np.array([-0.]).tobytes())
            self.assertEqual(f['row_maps/tracks'][:].tolist(),[0])
    def test_zero_chunk(self):
        raw,meta,out,counts=self.fixture(True);self.assertEqual(counts['ge_positive'],0)
        with h5py.File(out) as f:self.assertEqual(len(f['details/stp/al/edep']),0)
    def test_duplicate_global_id_rejected(self):
        raw,meta,out,_=self.fixture()
        with h5py.File(out,'r+') as f:f['events/global_decay_id'][1]=100
        with self.assertRaisesRegex(ValueError,'Global'):lt.verify_compact(raw,meta,out,100)
    def test_archive_roundtrip_and_no_raw_deletion(self):
        raw,meta,out,_=self.fixture(); before=lt.sha(raw)
        r=lt.archive_raw(raw,self.d/'raw.gz');self.assertEqual(r['raw_sha256'],before);self.assertTrue(raw.exists())
        lt.verify_archive(self.d/'raw.gz',before,raw.stat().st_size)
        with self.assertRaises(Exception):lt.verify_archive(self.d/'raw.gz','0'*64,raw.stat().st_size)
    def test_nooverwrite(self):
        raw,meta,out,_=self.fixture()
        with self.assertRaisesRegex(ValueError,'exists'):lt.compact(raw,meta,out)
    def test_seeds_and_disjoint_ranges(self):
        c={'events_per_model':1000000,'chunk_size':10000,'seed':26092701}; p=lt.plan(c)
        self.assertEqual(len(p),200);self.assertEqual(len({r['seed'] for r in p}),200)
        self.assertEqual(p,lt.plan(c))
        for m in lt.MODELS:self.assertEqual([r['start'] for r in p if r['model']==m],list(range(0,1000000,10000)))
    def test_path_escape(self):
        with self.assertRaises(ValueError):lt.local(lt.ROOT/'outside')
    @unittest.skipUnless(sys.platform.startswith('linux'),'OS flock exercised on WSL')
    def test_duplicate_worker_lock(self):
        with lt.locked(self.d):
            code='import sys;sys.path.insert(0,"tools");import long_transport as x;from pathlib import Path;h=x.locked(Path(sys.argv[1]));h.__enter__()'
            p=subprocess.run([sys.executable,'-c',code,str(self.d)],cwd=lt.ROOT,capture_output=True,text=True)
            self.assertNotEqual(p.returncode,0);self.assertIn('already has',p.stderr)
        with lt.locked(self.d):pass
    def test_configuration_and_rehashed_geometry_mutation(self):
        campaign=self.d/'campaign';lt.prepare(campaign,2,1);self.assertEqual(lt.config(campaign)['events_per_model'],2)
        p=campaign/'inputs/AK02/run.mac';p.write_text(p.read_text()+'\n/gps/ang/type beam\n')
        c=lt.read(campaign/'config.json');c['templates']['AK02']['run.mac']=lt.sha(p)
        lt.atomic(campaign/'config.json',c);(campaign/'config.sha256').write_text(lt.sha(campaign/'config.json'))
        with self.assertRaisesRegex(ValueError,'physical setup'):lt.config(campaign)
    def test_recovered_raw_does_not_rerun_transport(self):
        campaign=self.d/'campaign';campaign.mkdir();lt.atomic(campaign/'config.json',{'fixture':True})
        row={'model':'AK02','index':0,'start':0,'count':2,'seed':42}
        attempt,_=lt.select_attempt(campaign,row);raw_fixture(attempt/'truth.lh5')
        receipt={'status':'process_completed','plan':row,'config_sha256':lt.sha(campaign/'config.json'),'raw_sha256':lt.sha(attempt/'truth.lh5')}
        lt.atomic(attempt/'transport.json',receipt)
        recovered,r=lt.select_attempt(campaign,row)
        self.assertEqual(attempt,recovered);self.assertEqual(r,receipt)
    def test_interrupt_reduction_and_durable_completion(self):
        campaign=self.d/'campaign';campaign.mkdir();lt.atomic(campaign/'config.json',{'fixture':True})
        row={'model':'AK02','index':0,'start':0,'count':2,'seed':42}
        attempt,_=lt.select_attempt(campaign,row);meta=raw_fixture(attempt/'truth.lh5')
        inputs=campaign/'inputs/AK02';inputs.mkdir(parents=True);lt.atomic(inputs/'prepared.json',meta)
        receipt={'status':'process_completed','plan':row,'config_sha256':lt.sha(campaign/'config.json'),'raw_sha256':lt.sha(attempt/'truth.lh5')}
        lt.atomic(attempt/'transport.json',receipt)
        with patch.object(lt.cs,'iter_decays',fake_events),patch.object(lt,'run_transport',side_effect=AssertionError('Must reuse raw')):
            with patch.object(lt,'archive_raw',side_effect=RuntimeError('Synthetic interruption')):
                with self.assertRaisesRegex(RuntimeError,'Synthetic'):lt.process_chunk(campaign,{},row,None,lambda:None)
            self.assertTrue((attempt/'truth.lh5').exists());self.assertFalse((attempt.parent/'DONE.json').exists())
            d=lt.process_chunk(campaign,{},row,None,lambda:None)
        self.assertFalse((attempt/'truth.lh5').exists());self.assertEqual(d,lt.validate_done(campaign,{},row))
        (attempt/'compact.h5').write_bytes(b'corruption')
        with self.assertRaises(ValueError):lt.validate_done(campaign,{},row)

if __name__=='__main__':unittest.main(verbosity=2)
