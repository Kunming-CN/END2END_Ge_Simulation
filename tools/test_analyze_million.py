"""Bounded saved-data tests; one actual compact fixture, no simulation."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import h5py
import numpy as np
import analyze_million as a


class MillionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        a.BASE.mkdir(parents=True, exist_ok=True)
        cls.work = Path(tempfile.mkdtemp(prefix='analysis-tests-', dir=a.BASE))
        cls.c = a.read(a.CAMPAIGN/'config.json')
        cls.row = a.plans(cls.c)[0]
        cls.template = a.read(a.CAMPAIGN/'inputs/AK02/prepared.json')
        base = a.CAMPAIGN/'chunks/AK02/0000'
        cls.done = a.read(base/'DONE.json')
        cls.path = base/cls.done['attempt']/'compact.h5'
        cls.raw = a.read(base/cls.done['attempt']/'archive.json')['raw_sha256']
        cls.chunk = a.load_chunk(cls.path, cls.row, cls.template, cls.raw)

    def mutation(self, name, callback):
        path = self.work/(name+'.h5'); shutil.copyfile(self.path, path)
        with h5py.File(path, 'r+') as f:
            callback(f)
        # An updated outer hash must not defeat semantic validation.
        a.verified(path, a.sha(path))
        with self.assertRaises(ValueError):
            a.load_chunk(path, self.row, self.template, self.raw)

    def test_actual_compact_schema_fixture(self):
        self.assertEqual(self.chunk['counts'], self.done['counts'])
        self.assertEqual(self.chunk['counts']['decays'], 10000)
        self.assertEqual(len(self.chunk['events']), 116)
        self.assertEqual(self.chunk['schemas']['tracks']['ekin']['attrs']['units'], 'MeV')
        self.assertEqual(self.chunk['schemas']['stp/germanium']['xloc']['attrs']['units'], 'm')
        event = next(iter(self.chunk['events'].values()))
        self.assertEqual(a.classify_retained(event, self.chunk['processes']), a.hv.classify(event, self.chunk['processes'], a.HORIZON))

    def test_zero_census(self):
        ge = self.chunk['ledger']['ge_energy_keV']
        self.assertEqual(int((ge == 0).sum()), 9884)
        h = a.Histogram(); h.add(ge)
        self.assertEqual(h.result()['total'], 10000)
        self.assertEqual(h.result()['exact_zero'], 9884)

    def test_histogram_boundaries_tails(self):
        h = a.Histogram([0,1,2]); h.add([-1,0,0,np.nextafter(0,1),np.nextafter(1,0),1,np.nextafter(2,0),2,3])
        r = h.result()
        self.assertEqual((r['underflow'],r['exact_zero'],r['counts'],r['overflow'],r['total']), (1,2,[2,2],2,9))
        with self.assertRaises(ValueError): h.add([float('nan')])
        with self.assertRaises(ValueError): a.Histogram([0,1,1])

    def test_multichunk_local_collision(self):
        # Actual schema copied to a second synthetic chunk; repeated local IDs are expected.
        row = dict(self.row, index=1, start=10000, seed=a.seed_for(self.c['seed'],'AK02',1))
        path = self.work/'second.h5'; shutil.copyfile(self.path,path)
        with h5py.File(path,'r+') as f:
            f.attrs['global_offset'] = row['start']
            f['events/global_decay_id'][:] = np.arange(10000,20000)
            meta = json.loads(f.attrs['metadata_json']); meta['seed'] = row['seed']
            f.attrs['metadata_json'] = json.dumps(meta)
        second = a.load_chunk(path,row,self.template,self.raw)
        first_ids = set(self.chunk['ledger']['global_decay_id'])
        second_ids = set(second['ledger']['global_decay_id'])
        self.assertFalse(first_ids & second_ids)
        self.assertEqual(set(self.chunk['events']),set(second['events']))
        self.assertEqual(len(first_ids | second_ids),20000)
        with self.assertRaises(ValueError): a.load_chunk(path,self.row,self.template,self.raw)

    def test_rehashed_duplicate_global_id(self):
        self.mutation('duplicate-global', lambda f: f['events/global_decay_id'].__setitem__(1,0))

    def test_rehashed_duplicate_local_id(self):
        self.mutation('duplicate-local', lambda f: f['events/local_event_id'].__setitem__(1,0))

    def test_rehashed_row_map_duplicate(self):
        self.mutation('duplicate-row', lambda f: f['row_maps/stp/germanium'].__setitem__(1,0))

    def test_rehashed_zero_flag(self):
        self.mutation('zero-flag', lambda f: f['events/has_ge_energy'].__setitem__(0,not f['events/has_ge_energy'][0]))

    def test_rehashed_metadata_change(self):
        def change(f):
            meta=json.loads(f.attrs['metadata_json']); meta['source_position_global_mm'][0] += 1
            f.attrs['metadata_json'] = json.dumps(meta)
        self.mutation('changed-source',change)

    def test_rehashed_units_change(self):
        self.mutation('units', lambda f: f['details/stp/germanium/xloc'].attrs.__setitem__('units','mm'))

    def test_rehashed_seed_change(self):
        def change(f):
            meta=json.loads(f.attrs['metadata_json']); meta['seed'] += 1
            f.attrs['metadata_json'] = json.dumps(meta)
        self.mutation('seed',change)

    def test_rehashed_energy_change(self):
        self.mutation('energy', lambda f: f['events/ge_energy_keV'].__setitem__(0,123))

    def test_photon_group_normalization(self):
        # Two isolated groups from one initial decay must not become two emitted photons.
        event = copy.deepcopy(next(iter(self.chunk['events'].values())))
        ge = [r for r in event['tables']['stp/germanium'] if r['edep'] > 0]
        event['tables']['stp/germanium'] = [copy.deepcopy(ge[0]),copy.deepcopy(ge[0])]
        event['tables']['stp/germanium'][1]['time'] += a.HORIZON
        event['tables']['stp/germanium'][1]['raw_row_index'] += 100000
        result = a.classify_retained(event,self.chunk['processes'])
        self.assertEqual(len(result['groups']),2)
        self.assertEqual(a.ratio(1,3)['fraction'],1/3)
        self.assertNotEqual(a.ratio(1,2)['fraction'],a.ratio(1,3)['fraction'])
        self.assertEqual(sum(g['ge_energy_keV'] for g in result['groups']),2*ge[0]['edep'])

    def test_failed_classifier_retained(self):
        event = next(iter(self.chunk['events'].values()))
        def fail(*args): raise RuntimeError('deliberate test failure')
        result = a.classify_retained(event,self.chunk['processes'],fail)
        self.assertIn('classifier_error',result)
        self.assertTrue(all(g['categories'] == ['unknown'] for g in result['groups']))
        self.assertEqual(sorted(i for g in result['groups'] for i in g['ge_raw_row_indices']),
                         sorted(r['raw_row_index'] for r in event['tables']['stp/germanium'] if r['edep'] > 0))

    def test_classifier_silent_drop_retained(self):
        event = next(iter(self.chunk['events'].values()))
        result = a.classify_retained(event,self.chunk['processes'],lambda e,p,h: dict(event_id=e['event_id'],groups=[]))
        self.assertIn('classifier_error',result)
        self.assertTrue(result['groups'])

    def test_unknown_ancestry_retained(self):
        event = copy.deepcopy(next(iter(self.chunk['events'].values())))
        event['tables']['tracks'] = []
        result = a.classify_retained(event,self.chunk['processes'])
        self.assertTrue(result['groups'])
        self.assertTrue(all(g['categories'] == ['unknown'] for g in result['groups']))
        self.assertNotIn('classifier_error',result)

    def test_duplicate_track_unknown(self):
        event = copy.deepcopy(next(iter(self.chunk['events'].values())))
        event['tables']['tracks'].append(copy.deepcopy(event['tables']['tracks'][0]))
        result = a.classify_retained(event,self.chunk['processes'])
        self.assertIn('duplicate track IDs',result['graph_errors'])
        self.assertTrue(all(g['categories'] == ['unknown'] for g in result['groups']))

    def test_families_and_actual_representative_energy(self):
        f = a.Families()
        for e in (31.8,661.657,661.65700000001,None):
            f.add(dict(source_photon_energy_keV=e,categories=['full'] if e else ['unknown']))
        self.assertEqual([r['groups'] for r in f.rows],[1,2,1])
        self.assertEqual(f.rows[0]['categories']['full'],1)
        low=dict(source_photon_energy_keV=31.8,group_id=0)
        line=dict(source_photon_energy_keV=661.657,group_id=0)
        self.assertLess(a.representative_rank(line,dict(global_decay_id=100)),a.representative_rank(low,dict(global_decay_id=1)))

    def test_output_non_overwrite_and_scope(self):
        with self.assertRaises(ValueError): a.output_path(self.work)
        with self.assertRaises(ValueError): a.output_path(a.ROOT/'docs/report.html')
        path=self.work/'test.json'; a.write_json(path,{'a':1})
        with self.assertRaises(FileExistsError): a.write_json(path,{'a':2})
        self.assertEqual(a.read(path),{'a':1})

    def test_source_freeze_guard(self):
        hashes=a.source_hashes()
        a.check_sources(dict(source_sha256=hashes))
        hashes['tools/analyze_million.py']='0'*64
        with self.assertRaises(ValueError): a.check_sources(dict(source_sha256=hashes))

    def test_plan_seed_and_completion_read_only(self):
        c,receipt,rows,templates=a.campaign_inputs(a.CAMPAIGN)
        self.assertEqual(len(rows),200)
        self.assertEqual(len({r['seed'] for r in rows}),200)
        self.assertEqual(rows[0]['seed'],514663347)
        path,done,evidence=a.checkpoint(a.CAMPAIGN,rows[0],a.sha(a.CAMPAIGN/'config.json'))
        self.assertEqual(path,self.path)
        self.assertEqual(done['counts'],self.chunk['counts'])
        self.assertEqual(receipt['completed_decays'],2000000)

    def test_old_comparison_saved_only(self):
        old=a.compare_old()
        self.assertEqual(old['models']['AK02']['positive_ge_decays'],121)
        self.assertEqual(old['models']['SAP22']['positive_ge_decays'],115)

    def test_small_multichunk_end_to_end_export(self):
        # Twelve synthetic primary slots, based on one actual retained event.
        # Mock the receipt/input adapter, exercise the complete writer/verifier/report.
        c = dict(self.c, events_per_model=6, chunk_size=3)
        rows = a.plans(c)
        event = copy.deepcopy(next(iter(self.chunk['events'].values())))
        old_id = event['event_id']; event['event_id'] = 0
        for table in event['tables'].values():
            for r in table: r['evtid'] = 0
        ge_value = self.chunk['ledger']['ge_energy_keV'][old_id]
        decays = int(self.chunk['ledger']['decay_photons'][old_id])
        line = int(self.chunk['ledger']['line_photons'][old_id])
        counts = dict(decays=3,ge_positive=1,decay_photons=decays+3,line_photons=line)
        complete = dict(models={m: {k: 2*v for k,v in counts.items()} for m in a.MODELS})
        def load(path,row,template,raw):
            ledger = dict(local_event_id=np.arange(3),global_decay_id=np.arange(row['start'],row['start']+3),
                          ge_energy_keV=np.array([ge_value,0.,0.]),has_ge_energy=np.array([True,False,False]),
                          decay_photons=np.array([decays,1,2]),line_photons=np.array([line,0,0]),
                          material_energy_keV=np.array([[ge_value],[0.],[0.]]))
            return dict(ledger=ledger,events={0:event},processes=self.chunk['processes'],counts=counts,
                        materials=['G4_Ge'],retained_raw_rows={'stp/germanium':len(event['tables']['stp/germanium'])},schemas={})
        def checkpoint(directory,row,digest):
            return self.path,dict(counts=counts),dict(raw_sha256=self.raw,plan=row)
        frozen=dict(source_sha256=a.source_hashes(),config_sha256=a.sha(a.CAMPAIGN/'config.json'),
                    complete_sha256=a.sha(a.CAMPAIGN/'COMPLETE.json'))
        target=a.BASE/(self.work.name+'-integration')
        with patch.object(a,'campaign_inputs',return_value=(c,complete,rows,{m:self.template for m in a.MODELS})), \
             patch.object(a,'checkpoint',side_effect=checkpoint), patch.object(a,'load_chunk',side_effect=load):
            result=a.analyze(a.CAMPAIGN,target,frozen)
        self.assertEqual(result['models']['AK02']['initial_decays'],6)
        self.assertEqual(result['models']['AK02']['positive_ge_decays'],2)
        self.assertEqual(a.verify_output(target)['AK02']['positive_events'],2)
        self.assertEqual(a.read(target/'histograms.json')['AK02']['per_initial_decay']['exact_zero'],4)
        self.assertTrue((target/'COMPLETE.json').exists())
        with self.assertRaises(ValueError): a.analyze(a.CAMPAIGN,target,frozen)
        report=(target/'report.html').read_text(encoding='utf-8')
        self.assertNotIn('<script',report)
        self.assertNotIn('src=',report)
        # A rehashed derivative histogram mutation still fails independent bin rebuilding.
        h=a.read(target/'histograms.json'); h['AK02']['per_initial_decay']['counts'][0] += 1
        (target/'histograms.json').write_text(json.dumps(h),encoding='utf-8')
        s=a.read(target/'summary.json'); hp=target/'histograms.json'
        s['files']['histograms.json']=dict(sha256=a.sha(hp),bytes=hp.stat().st_size)
        (target/'summary.json').write_text(json.dumps(s),encoding='utf-8')
        with self.assertRaises(ValueError): a.verify_output(target)


if __name__ == '__main__':
    unittest.main(verbosity=2)
