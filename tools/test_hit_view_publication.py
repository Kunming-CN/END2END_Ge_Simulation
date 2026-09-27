import gzip, hashlib, io, json, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import hit_view_publication as pub

def encoded(x): return json.dumps(x,separators=(',',':')).encode()
def fixture(folder):
    meta={'status':'complete','models':{},'files':{},'category_labels':{'partial':'candidate'}}
    for model,n in pub.MODELS.items():
        d=folder/model; d.mkdir(); ids=list(range(n))
        columns={'stp/germanium':['raw_row_index','evtid','edep']}
        scene={'model':model,'source_position_global_mm':[0,37.073,.29],
               'event_index':{'ge_hit_ids':ids,'raw_columns':{'stp/germanium':{'evtid':{},'edep':{}}}}}
        data={'model':model,'event_ids':ids,'columns':columns,
              'events':[{'event_id':i,'tables':{'stp/germanium':[[i,i,1.0]]}} for i in ids],
              'evidence':[{'event_id':i,'groups':[]} for i in ids],
              'categories':{'partial':[]},'representatives':{'partial':None}}
        (d/'scene.json').write_bytes(encoded(scene)); (d/'selected.json.gz').write_bytes(gzip.compress(encoded(data),mtime=0))
        meta['models'][model]={'selected_count':n,'source_scene_sha256':pub.sha((d/'scene.json').read_bytes()),'category_group_counts':{'partial':0}}
    (folder/'hit_event_view.html').write_text('<main>Fixture</main>'); (folder/'README.md').write_text('Fixture')
    bind(folder,meta); return meta

def bind(folder,meta):
    meta['files']={n:{'bytes':(folder/n).stat().st_size,'sha256':pub.sha((folder/n).read_bytes())} for n in pub.NAMES-{'manifest.json'}}
    (folder/'manifest.json').write_bytes(encoded(meta))

class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name); self.meta=fixture(self.root)
    def tearDown(self): self.tmp.cleanup()
    def test_complete(self): self.assertEqual(pub.validate(self.root),self.meta)
    def test_changed_payload(self):
        (self.root/'AK02/selected.json.gz').write_bytes(b'bad')
        with self.assertRaisesRegex(ValueError,'Changed'): pub.validate(self.root)
    def test_rehashed_mixed_id(self):
        f=self.root/'AK02/selected.json.gz'; d=json.loads(gzip.decompress(f.read_bytes()))
        d['events'][0]['tables']['stp/germanium'][0][1]=9
        f.write_bytes(gzip.compress(encoded(d))); bind(self.root,self.meta)
        with self.assertRaisesRegex(ValueError,'mixed'): pub.validate(self.root)
    def test_rehashed_false_representative(self):
        f=self.root/'AK02/selected.json.gz'; d=json.loads(gzip.decompress(f.read_bytes()))
        d['representatives']['partial']={'event_id':0,'group_id':0}
        f.write_bytes(gzip.compress(encoded(d))); bind(self.root,self.meta)
        with self.assertRaisesRegex(ValueError,'Fabricated'): pub.validate(self.root)
    def test_private_compressed_data(self):
        f=self.root/'AK02/selected.json.gz'; d=json.loads(gzip.decompress(f.read_bytes()))
        d['private']='C:/Users/synthetic-test/file'; f.write_bytes(gzip.compress(encoded(d))); bind(self.root,self.meta)
        with self.assertRaisesRegex(ValueError,'Private'): pub.validate(self.root)
    def test_unlisted_file(self):
        (self.root/'extra.txt').write_text('extra')
        with self.assertRaisesRegex(ValueError,'inventory'): pub.validate(self.root)

    def test_all_payloads_live_verified(self):
        from check_site import verify_live, MANIFEST
        from urllib.parse import unquote,urlsplit
        name='examples/cs137-10k-hits/AK02/selected.json.gz'
        body=b'synthetic-gzip'; report={'build_id':'fixture','files':[{'path':name,'bytes':len(body),'sha256':pub.sha(body)}]}
        files={MANIFEST:encoded(report),name:body}; requested=[]
        def open_fake(request,timeout):
            key=unquote(urlsplit(request.full_url).path).removeprefix('/site/')
            requested.append(key); return io.BytesIO(files[key])
        with patch.dict(sys.modules,{'ssl':object()}),patch('urllib.request.urlopen',open_fake):
            verify_live('https://example.org/site/',report)
            self.assertIn(name,requested)
            files[name]=b'wrong'
            with self.assertRaises(ValueError): verify_live('https://example.org/site/',report)
            del files[name]
            with self.assertRaises(KeyError): verify_live('https://example.org/site/',report)

if __name__=='__main__': unittest.main(verbosity=2)
