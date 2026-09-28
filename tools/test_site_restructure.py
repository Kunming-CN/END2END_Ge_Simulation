import json,tempfile,unittest
from pathlib import Path
import site_restructure as S

class SiteStructureTests(unittest.TestCase):
    def fixture(self,with_results=False):
        t=tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup); root=Path(t.name)
        (root/'models').mkdir(); (root/'detectors/AK02').mkdir(parents=True);(root/'detectors/SAP22').mkdir(parents=True)
        (root/'index.html').write_text('old',encoding='utf-8')
        for ident in ('AK02','SAP22'):
            (root/'detectors'/ident/'index.html').write_text('<html><main><h1>'+ident+'</h1></main></html>',encoding='utf-8')
        catalog={'detectors':[{'id':'AK02','status':'geometry','coordinate_system':'cylindrical','contacts':[{},{}]},
                              {'id':'SAP22','status':'geometry','coordinate_system':'cylindrical','contacts':[{},{}]}]}
        (root/'models/catalog.json').write_text(json.dumps(catalog),encoding='utf-8')
        if with_results:
            (root/'examples/cs137-1m-response').mkdir(parents=True);(root/'examples/cs137-1m').mkdir(parents=True)
            summary={'totals':{'accepted':21672},'models':{
                'AK02':{'positive_ge_decays':12420,'response':{'accepted':10757}},
                'SAP22':{'positive_ge_decays':11272,'response':{'accepted':10915}}}}
            (root/'examples/cs137-1m-response/summary.json').write_text(json.dumps(summary),encoding='utf-8')
            (root/'examples/cs137-1m/summary.json').write_text('{}',encoding='utf-8')
            (root/'examples/cs137-10k').mkdir();(root/'examples/cs137-10k/comparison.html').write_text('x')
        return root
    def test_three_primary_entries_and_download(self):
        root=self.fixture(); result=S.apply(root)
        home=(root/'index.html').read_text()
        self.assertEqual(result['detectors'],2)
        for label in S.PRIMARY:self.assertIn(label,home)
        self.assertEqual(home.count('<article class="card">'),3)
        self.assertIn('downloads/all-models.zip',home)
        for p in ('learn/index.html','detectors/index.html','results/index.html',
                  'methods/index.html','scenarios/lbnl-cs137/index.html'):
            self.assertTrue((root/p).is_file(),p)

    def test_result_hubs_are_conditional(self):
        root=self.fixture(with_results=True);S.apply(root)
        self.assertTrue((root/'results/cs137-1m/index.html').is_file())
        self.assertTrue((root/'results/cs137-10k/index.html').is_file())
        scenario=(root/'scenarios/lbnl-cs137/index.html').read_text()
        self.assertIn('1M-per-detector campaign',scenario);self.assertIn('earlier 10k campaign',scenario)
        overview=(root/'results/cs137-1m/index.html').read_text()
        self.assertIn('12,420',overview);self.assertIn('10,757',overview)

    def test_repeat_application_is_idempotent(self):
        root=self.fixture(with_results=True);S.apply(root)
        owned=('index.html','learn/index.html','detectors/index.html','results/index.html','results/cs137-1m/index.html','results/cs137-10k/index.html','methods/index.html','scenarios/lbnl-cs137/index.html')
        first={p:(root/p).read_bytes() for p in owned};S.apply(root)
        self.assertEqual(first,{p:(root/p).read_bytes() for p in owned})
    def test_source_removal_replaces_owned_hubs_with_unavailable_pages(self):
        root=self.fixture(with_results=True);S.apply(root)
        (root/'examples/cs137-1m-response/summary.json').unlink();(root/'examples/cs137-1m/summary.json').unlink();(root/'examples/cs137-10k/comparison.html').unlink()
        S.apply(root)
        self.assertNotIn('Open campaign overview',(root/'results/index.html').read_text())
        self.assertNotIn('Saved campaigns',(root/'scenarios/lbnl-cs137/index.html').read_text())
        self.assertIn('unavailable in this snapshot',(root/'results/cs137-1m/index.html').read_text())
        self.assertIn('unavailable in this snapshot',(root/'results/cs137-10k/index.html').read_text())
    def test_unsafe_detector_id_refused(self):
        root=self.fixture(); c=json.loads((root/'models/catalog.json').read_text())
        c['detectors'][0]['id']='../escape';(root/'models/catalog.json').write_text(json.dumps(c))
        with self.assertRaisesRegex(ValueError,'Unsafe detector ID'):S.apply(root)

if __name__=='__main__':unittest.main(verbosity=2)
