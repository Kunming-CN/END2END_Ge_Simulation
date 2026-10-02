"""Four-model reader contracts with explicit mock rings and real old data.

No native inspection, transport, drift, readout or ring exporter is invoked.
The mock fixture is not a scientific/publication acceptance bundle.
"""
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import viewer_navigation as V

EVIDENCE=V.ROOT/'.local/ring-delivery-v1/reader'


def encoded(value):
    return (json.dumps(value,ensure_ascii=True,allow_nan=False,separators=(',',':'))+'\n').encode()


def fixture(site):
    import gzip
    folder=site/V.RING_BASE;files={};models={}
    old=json.loads((V.ROOT/'docs/examples/cs137-10k-hits/manifest.json').read_text())

    def save(name,body):
        p=folder/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(body)
        files[name]={'sha256':V.sha(p),'bytes':len(body)}

    for name in V.RING_MODELS:
        ids=[42,560,9999];chunks=[];proof=[];events=[]
        row={'raw_row_index':17,'xloc':-0.0,'yloc':1e-200,'zloc':0.1,
             'xloc_pre':-0.0,'yloc_pre':0.0,'zloc_pre':0.1,
             'xloc_post':0.001,'yloc_post':0.0,'zloc_post':0.1,
             'edep':62.86589960084667,'particle':22,'trackid':2}
        keys=list(row)
        for i in range(100):
            records=[{'event_id':id,'tables':{'stp/germanium':[dict(row)] if id in ids else [],'tracks':[]}}
                     for id in range(i*100,(i+1)*100)]
            filename=f'events-{i*100:05d}.json';save(name+'/'+filename,encoded({'model':name,'first':i*100,'events':records}))
            chunks.append({'file':filename,'first':i*100,'count':100,'sha256':files[name+'/'+filename]['sha256']})
        for id in ids:
            group={'group_id':0,'categories':['compact','full'] if id==42 else ['partial','unknown'],
                   'ge_energy_keV':row['edep'],'source_photon_energy_keV':661.657,
                   'source_photon_track_ids':[2],'origin_time_ns':1e10+id,'relative_delays_ns':[-0.0,15.5],
                   'deposit_diameter_mm':0.001,'ge_raw_row_indices':[17],'observed_compton_site_count':1,
                   'reason':'Explicit mock; radiation evidence remains independent of unknown charge response.'}
            groups=[group]
            if id==42:groups.append({**group,'group_id':7,'categories':['partial']})
            proof.append({'event_id':id,'groups':groups,'ge_step_count':1,'graph_errors':[],
                          'relevant_photon_track_ids':[2],'native_response_known':id!=560})
            events.append({'event_id':id,'tables':{'stp/germanium':[[row[k] for k in keys]],'tracks':[]}})
        cats={k:[{'event_id':e['event_id'],'group_id':g['group_id']} for e in proof for g in e['groups'] if k in g['categories']]
              for k in old['category_labels']}
        selected={'schema_version':1,'model':name,'event_ids':ids,'columns':{'stp/germanium':keys,'tracks':[]},
                  'events':events,'evidence':proof,'categories':cats,
                  'representatives':{k:values[0] if values else None for k,values in cats.items()}}
        save(name+'/selected.json.gz',gzip.compress(encoded(selected),mtime=0))
        index={'event_count':10000,'chunks':chunks,'ge_hit_ids':ids,'zero_ge_primaries':9997,
               'raw_rows':{'stp/germanium':3,'tracks':0},'raw_columns':{'stp/germanium':keys,'tracks':[]}}
        scene={'model':name,'volumes':[],'source_position_global_mm':[-0.0,37.073,0.290],
               'event_index':index,'scenario':{'qualification':'mock contract only'},'seed':128,
               'raw_lh5_sha256':hashlib.sha256(name.encode()).hexdigest(),'omissions':['No scientific geometry in mock.']}
        save(name+'/scene.json',encoded(scene))
        for file,body in [('originals.zip',b'explicit mock archive'),('response/summary.html',b'<title>Mock saved response</title>'),
                          ('response/run.json',encoded({'mock':True})),('response/signals.csv',b'signed_keV\n-0.0\n-17.5\n'),
                          ('response/readout-input.csv',b'current_nA\n1.25\n')]:save(name+'/'+file,body)
        binding={'kind':'ring_model_saved_dataset_binding_v1','model_id':name,'primary_count':10000,
                 'variant_id':'lithium_50min' if name=='GeRC02' else 'candidate_fixed_minus_one',
                 'terminal_receipt_sha256':hashlib.sha256((name+' terminal').encode()).hexdigest(),
                 'readout_wiring_factor':1 if name=='GeRC02' else -1,'raw_lh5_sha256':scene['raw_lh5_sha256']}
        models[name]={'model_id':name,'scene':name+'/scene.json','selected':name+'/selected.json.gz','selected_count':3,
                      'source_scene_sha256':files[name+'/scene.json']['sha256'],'dataset_binding':binding,
                      'dataset_binding_sha256':hashlib.sha256(encoded(binding)).hexdigest(),'variant_id':binding['variant_id'],
                      'originals':name+'/originals.zip','response':name+'/response/summary.html','response_report':name+'/response/run.json',
                      'readout_wiring':{'factor':binding['readout_wiring_factor']},'counts':{'initial_decays':10000},
                      'category_group_counts':{k:len(v) for k,v in cats.items()}}
    manifest={'kind':V.RING_KIND,'schema_version':1,'status':'complete','models':models,'files':files,
              'category_labels':old['category_labels'],'method':old['method'],'limitations':['Mock reader test only.']}
    (folder/'manifest.json').write_bytes(encoded(manifest))
    return manifest


class RingReaders(unittest.TestCase):
    @classmethod
    def setUpClass(cls):EVIDENCE.mkdir(parents=True,exist_ok=True)

    def site(self):return tempfile.TemporaryDirectory(dir=EVIDENCE,prefix='contract-mock-')

    def test_absent_bundle_preserves_original_config(self):
        with self.site() as tmp:
            self.assertEqual(V.config(Path(tmp)),V.config())
            self.assertNotIn('models',V.config(Path(tmp)))

    def test_completed_bundle_selects_same_real_manifest_per_ring(self):
        with self.site() as tmp:
            site=Path(tmp);m=fixture(site);config=V.config(site)
            self.assertEqual(set(config['models']),set(V.RING_MODELS))
            for name in V.RING_MODELS:
                self.assertEqual(config['models'][name]['assembly'],config['models'][name]['positive'])
                self.assertEqual(config['models'][name]['assembly']['kind'],V.RING_KIND)
                self.assertEqual(config['models'][name]['assembly']['sha256'],V.sha(site/V.RING_BASE/'manifest.json'))
            self.assertNotIn('campaign_run_sha256',m)
            self.assertEqual(V.ring_records(site,m)[V.RING_BASE+'/manifest.json']['sha256'],config['models']['GeRC02']['assembly']['sha256'])

    def test_rehashed_contract_mutations_and_incomplete_bundle_refused(self):
        for mutation,message in [('incomplete','Incomplete'),('binding','dataset binding'),('scene','scene/selected'),
                                 ('chunks','chunk census'),('missing','file inventory'),('extra','file inventory'),('wrong_model','Incomplete')]:
            with self.subTest(mutation=mutation),self.site() as tmp:
                site=Path(tmp);m=fixture(site);folder=site/V.RING_BASE;e=m['models']['GeRC02']
                if mutation=='incomplete':m['status']='running'
                elif mutation=='binding':e['dataset_binding']['readout_wiring_factor']=-1
                elif mutation=='scene':e['source_scene_sha256']='0'*64
                elif mutation=='chunks':
                    s=V.read(folder/e['scene']);s['event_index']['chunks'][5]['first']=499
                    (folder/e['scene']).write_bytes(encoded(s));m['files'][e['scene']]={'sha256':V.sha(folder/e['scene']),'bytes':(folder/e['scene']).stat().st_size}
                    e['source_scene_sha256']=m['files'][e['scene']]['sha256']
                elif mutation=='missing':(folder/e['selected']).unlink()
                elif mutation=='extra':(folder/'extra.json').write_text('{}')
                elif mutation=='wrong_model':m['models'].pop('KMRC01_candidate')
                (folder/'manifest.json').write_bytes(encoded(m))
                with self.assertRaisesRegex(ValueError,message):V.config(site)
        with self.site() as tmp:
            (Path(tmp)/V.RING_BASE).mkdir(parents=True)
            with self.assertRaisesRegex(ValueError,'no manifest'):V.config(Path(tmp))

    def test_changed_science_bytes_and_unsafe_rehashed_path_refused(self):
        for unsafe in (False,True):
            with self.subTest(unsafe=unsafe),self.site() as tmp:
                site=Path(tmp);m=fixture(site);folder=site/V.RING_BASE
                if unsafe:m['files']['../escape']={'sha256':'0'*64,'bytes':0}
                else:(folder/'GeRC02/response/signals.csv').write_bytes(b'rectified\n17.5\n')
                if unsafe:
                    (folder/'manifest.json').write_bytes(encoded(m))
                    with self.assertRaisesRegex(ValueError,'Unsafe'):V.config(site)
                else:
                    with self.assertRaisesRegex(ValueError,'asset changed'):V.config(site)

    def test_source_reader_with_mock_rings_and_real_old_saved_payloads(self):
        # A stable retained fixture/log is evidence, not a public science bundle.
        site=EVIDENCE/'mock-site';site.mkdir(exist_ok=True);fixture(site)
        html=V.render(site);(site/'viewer-source.html').write_text(html,encoding='utf-8')
        result=subprocess.run(['node',str(V.ROOT/'tools/test_ring_viewer.mjs'),str(site)],cwd=V.ROOT,text=True,
                              capture_output=True,encoding='utf-8',check=False)
        (EVIDENCE/'mock-reader-node.log').write_text(result.stdout+result.stderr,encoding='utf-8')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_previous_whole_manifest_and_current_reader_source_gates(self):
        self.assertIn('27ec5778f811eae44a70f91106056567cd4bf07d0d503c2e4526ee4cc900941a',V.TRUSTED_PREVIOUS_UNIFIED_MANIFESTS)
        V.validate(V.ROOT/'docs')
        manifest = V.ROOT/'docs/viewers/manifest.json'
        if V.sha(manifest) in V.TRUSTED_PREVIOUS_UNIFIED_MANIFESTS:
            with self.assertRaisesRegex(ValueError,'Unknown adapter source'):V.validate(V.ROOT/'docs',True)
        else:
            V.validate(V.ROOT/'docs',True)


if __name__=='__main__':unittest.main(verbosity=2)
