import json,re,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
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
        root=self.fixture()
        with patch('gamma_showcase.validate_bundle') as checked:
            result=S.apply(root)
        checked.assert_not_called()
        home=(root/'index.html').read_text()
        self.assertEqual(result['detectors'],2)
        for label in S.PRIMARY:self.assertIn(label,home)
        self.assertEqual(home.count('<article class="card">'),3)
        self.assertEqual(home.count('href="downloads/all-models.zip"'),1)
        self.assertRegex(home,r'<section class="cards">\s*<article class="card"><h2>Results</h2>')
        primary=re.search(r'<nav aria-label="Primary">(.*?)</nav>',home).group(1)
        self.assertEqual(re.findall(r'href="([^"]+)"',primary),
                         ['results/index.html','detectors/index.html','guide.html'])
        self.assertEqual(re.findall(r'>([^<]+)</a>',primary),list(S.PRIMARY))
        self.assertIn('Run.cmd',home)
        for p in ('learn/index.html','detectors/index.html','results/index.html',
                  'methods/index.html','scenarios/lbnl-cs137/index.html'):
            self.assertTrue((root/p).is_file(),p)
        for name in ('learn/index.html','results/index.html'):
            page=(root/name).read_text()
            self.assertIn('Compact teaching example',page)
            self.assertEqual(page.count('../examples/pipeline.html'),1)
            self.assertNotIn('../examples/gamma-native/gamma.html',page)
        scenario=(root/'scenarios/lbnl-cs137/index.html').read_text()
        self.assertIn('guide.html#choose',scenario)
        self.assertIn('guide.html#local-routes',scenario)
        self.assertNotIn('Run.cmd run',scenario)
        self.assertIn('10k requires a verified 500-event pilot',scenario)
        self.assertIn('not redistributed',scenario)

    def test_result_hubs_are_conditional(self):
        root=self.fixture(with_results=True);S.apply(root)
        self.assertTrue((root/'results/cs137-1m/index.html').is_file())
        self.assertTrue((root/'results/cs137-10k/index.html').is_file())
        scenario=(root/'scenarios/lbnl-cs137/index.html').read_text()
        self.assertIn('1M-per-detector campaign',scenario);self.assertIn('earlier 10k campaign',scenario)
        overview=(root/'results/cs137-1m/index.html').read_text()
        self.assertIn('12,420',overview);self.assertIn('10,757',overview)
        results=(root/'results/index.html').read_text()
        self.assertLess(results.index('Current completed campaign'),results.index('Saved engineering examples'))
        self.assertLess(results.index('Saved engineering examples'),results.index('Compact teaching example'))
        self.assertLess(results.index('Compact teaching example'),results.index('<h2>Earlier campaign</h2>'))
        self.assertLess(results.index('<h2>Earlier campaign</h2>'),results.index('Earlier Cs137 · 10k'))
        self.assertIn('Original reports remain available as archived presentations of this same campaign',results)
        self.assertNotIn('1M per detector',''.join(re.findall(r'<article class="card">.*?</article>',results,re.S)))
        self.assertIn('Compact teaching example',results)

    def test_repeat_application_is_idempotent(self):
        root=self.fixture(with_results=True);S.apply(root)
        owned=('index.html','learn/index.html','detectors/index.html','results/index.html','results/cs137-1m/index.html','results/cs137-10k/index.html','methods/index.html','scenarios/lbnl-cs137/index.html')
        first={p:(root/p).read_bytes() for p in owned};S.apply(root)
        self.assertEqual(first,{p:(root/p).read_bytes() for p in owned})

    def test_checked_gamma_promotes_both_hubs_and_preserves_saved_bytes(self):
        root=self.fixture(with_results=True);S.apply(root)
        before={p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*') if p.is_file()}
        gamma=root/'examples/gamma-native';gamma.mkdir(parents=True)
        (gamma/'gamma.html').write_bytes(b'synthetic checked fixture\r\n')
        with patch('gamma_showcase.validate_bundle') as checked:
            S.apply(root)
        checked.assert_called_once_with(gamma)
        results=(root/'results/index.html').read_text()
        self.assertEqual(results.count('Completed gamma → native SSD → peak ADC'),1)
        self.assertEqual(results.count('../examples/gamma-native/gamma.html'),1)
        self.assertIn('Compact teaching example',results)
        self.assertIn('../examples/pipeline.html',results)
        order=('Current completed campaign','Saved engineering examples',
               'Completed gamma → native SSD → peak ADC','Compact teaching example',
               '<h2>Earlier campaign</h2>','Earlier Cs137 · 10k')
        self.assertEqual([results.index(label) for label in order],
                         sorted(results.index(label) for label in order))
        learn=(root/'learn/index.html').read_text()
        self.assertEqual(learn.count('../examples/gamma-native/gamma.html'),1)
        self.assertEqual(learn.count('../examples/pipeline.html'),1)
        self.assertLess(learn.index('../examples/gamma-native/gamma.html'),learn.index('../examples/pipeline.html'))
        self.assertIn('Open the saved engineering example',learn)
        self.assertIn('Compact teaching example',learn)
        for page in (learn,results):
            for wording in ('40 truth events','six selected responses','four positive responses',
                            'two selected true zeros','34 responses stay unknown/unprocessed',
                            'Small engineering sample','unresolved collection limits',
                            'independent synthetic injection calibration'):
                self.assertIn(wording,page)
        for name,raw in before.items():
            if name not in ('learn/index.html','results/index.html'):
                self.assertEqual((root/name).read_bytes(),raw,name)
        self.assertEqual((gamma/'gamma.html').read_bytes(),b'synthetic checked fixture\r\n')
        invalid_before={p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*') if p.is_file()}
        with patch('gamma_showcase.validate_bundle',side_effect=ValueError('incomplete gamma')) as checked, \
             patch.object(S,'write_page') as write:
            with self.assertRaisesRegex(ValueError,'incomplete gamma'):S.apply(root)
        checked.assert_called_once_with(gamma)
        write.assert_not_called()
        self.assertEqual(invalid_before,{p.relative_to(root).as_posix():p.read_bytes()
                                       for p in root.rglob('*') if p.is_file()})
    def test_source_removal_replaces_owned_hubs_with_unavailable_pages(self):
        root=self.fixture(with_results=True);S.apply(root)
        (root/'examples/cs137-1m-response/summary.json').unlink();(root/'examples/cs137-1m/summary.json').unlink();(root/'examples/cs137-10k/comparison.html').unlink()
        S.apply(root)
        self.assertNotIn('Open campaign overview',(root/'results/index.html').read_text())
        self.assertIn('Current campaign unavailable in this snapshot',(root/'results/index.html').read_text())
        self.assertNotIn('Saved campaigns',(root/'scenarios/lbnl-cs137/index.html').read_text())
        self.assertIn('unavailable in this snapshot',(root/'results/cs137-1m/index.html').read_text())
        self.assertIn('unavailable in this snapshot',(root/'results/cs137-10k/index.html').read_text())
    def test_unsafe_detector_id_refused(self):
        root=self.fixture(); c=json.loads((root/'models/catalog.json').read_text())
        c['detectors'][0]['id']='../escape';(root/'models/catalog.json').write_text(json.dumps(c))
        with self.assertRaisesRegex(ValueError,'Unsafe detector ID'):S.apply(root)

    def test_guide_keeps_distinct_local_routes_and_historical_scopes(self):
        root=self.fixture();S.apply(root)
        guide=(root/'guide.html').read_text()
        sections=dict(re.findall(r'<section id="([^"]+)">(.*?)</section>',guide,re.S))
        anchors=('local-routes','browse','setup','choose','local-control','electronics','replay',
                 'native-readout','source-preparation','results','recovery','validation','workspace','downloads')
        self.assertEqual(set(sections),set(anchors))
        self.assertEqual(len(re.findall(r'<section id="([^"]+)"',guide)),len(anchors))
        self.assertIn('href="results/index.html">All saved results and engineering examples</a>',sections['local-routes'])
        self.assertIn('WSL2',sections['setup'])
        self.assertIn('full signed <code>signals.csv</code>',sections['replay'])
        self.assertIn('no group recovery',sections['replay'])
        self.assertIn('-Detector AK02 -CheckpointGroups -Resume',sections['replay'])
        native=sections['native-readout']
        self.assertIn('checked private',native);self.assertIn('not in a fresh checkout',native)
        resume_lines=[line for line in native.splitlines() if 'Run.cmd native-readout' in line and '-Resume' in line]
        self.assertEqual(len(resume_lines),2)
        self.assertTrue(all('-Detector' not in line and '-PrimaryIds' not in line for line in resume_lines))
        self.assertIn('newly committed <strong>electronics</strong> groups',native)
        self.assertIn('does not provide per-group recovery',sections['results'])
        self.assertIn('Neither command starts missing calculations',sections['recovery'])
        self.assertIn('Those historical checks alone',sections['validation'])
        self.assertIn('one custom-profile AK02 500-decay uninstrumented run',sections['validation'])
        self.assertNotIn('Electronics-only replay is still NOT_IMPLEMENTED',guide)

if __name__=='__main__':unittest.main(verbosity=2)
