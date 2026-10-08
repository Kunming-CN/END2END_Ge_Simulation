import json,re,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from html.parser import HTMLParser
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
        self.assertRegex(home,r'<section class="cards">\s*<article class="card"><h2>Browse</h2>')
        primary=re.search(r'<nav aria-label="Primary"[^>]*>(.*?)</nav>',home).group(1)
        self.assertEqual(re.findall(r'href="([^"]+)"',primary),
                         ['guide.html#local-control','results/index.html','spectra/pipeline.html','spectra/cs137-10k.html','detectors/index.html'])
        self.assertEqual(re.findall(r'>([^<]+)</a>',primary),['Run','Results','Waveforms','Spectra','Detectors'])
        self.assertIn('Use Control',home)
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
        self.assertIn('Cs137, Am241 and Ba133 accept an exact positive initial-nucleus count',scenario)
        self.assertIn('Control offers 10 separate detector configurations',scenario)
        self.assertIn('not redistributed',scenario)

    def test_home_folds_secondary_routes_without_losing_destinations(self):
        class HomeLinks(HTMLParser):
            def __init__(self):
                super().__init__(); self.closed=[]; self.links=[]; self.outside=[]
            def handle_starttag(self,tag,attrs):
                values=dict(attrs)
                if tag=='details':self.closed.append('open' not in values)
                if tag=='a':
                    self.links.append(values['href'])
                    if not any(self.closed):self.outside.append(values['href'])
            def handle_endtag(self,tag):
                if tag=='details':self.closed.pop()
        root=self.fixture(with_results=True);S.apply(root)
        home=(root/'index.html').read_text();parser=HomeLinks();parser.feed(home)
        # The owner reported that folded routes made useful views hard to find.
        # Waveforms, spectra, 3D events and data help must be visible directly.
        for href in ('index.html','spectra/pipeline.html','spectra/cs137-10k.html',
                     'viewers/events.html','guide.html#saved-analysis',
                     'guide.html#setup','guide.html#local-control'):
            self.assertIn(href,parser.outside)
        for href in ('learn/index.html','methods/index.html','examples/pipeline.html','results/cs137-10k/index.html',
                     'downloads/all-models.zip','https://github.com/Kunming-CN/END2END_Ge_Simulation'):
            self.assertIn(href,parser.links);self.assertNotIn(href,parser.outside)
        self.assertIn('Inspect events, signals and spectra',home)
        self.assertIn('choose one of 10 configurations available in the current cryostat',home)
        self.assertIn('Fresh-machine setup remains unvalidated',home)
        self.assertIn('<summary>Pipeline, methods and earlier examples</summary>',home)
        self.assertIn('<summary>More project resources</summary>',home)
        for name in ('learn/index.html','results/index.html','detectors/index.html'):
            self.assertNotIn('More project resources',(root/name).read_text(),'Fold is homepage-only')

    def test_result_hubs_are_conditional(self):
        root=self.fixture(with_results=True);S.apply(root)
        self.assertTrue((root/'results/cs137-1m/index.html').is_file())
        self.assertTrue((root/'results/cs137-10k/index.html').is_file())
        scenario=(root/'scenarios/lbnl-cs137/index.html').read_text()
        self.assertIn('1M-per-detector campaign',scenario);self.assertIn('Cs137 10K results',scenario)
        overview=(root/'results/cs137-1m/index.html').read_text()
        self.assertIn('12,420',overview);self.assertIn('10,757',overview)
        results=(root/'results/index.html').read_text()
        self.assertLess(results.index('Separate Cs137 · 1M campaign'),results.index('Main teaching example'))
        self.assertLess(results.index('Main teaching example'),results.index('Compact teaching example'))
        self.assertLess(results.index('Compact teaching example'),results.index('<h2>Earlier campaign</h2>'))
        self.assertLess(results.index('<h2>Earlier campaign</h2>'),results.index('Earlier Cs137 · 10k'))
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
        self.assertEqual(results.count('Additional cryostat gamma example · 20 primaries per detector'),1)
        self.assertNotIn('Completed gamma',results)
        self.assertEqual(results.count('../examples/gamma-native/gamma.html'),1)
        self.assertIn('Compact teaching example',results)
        self.assertIn('../examples/pipeline.html',results)
        order=('Separate Cs137 · 1M campaign','Main teaching example',
               'Compact teaching example','Additional cryostat gamma example · 20 primaries per detector',
               '<h2>Earlier campaign</h2>','Earlier Cs137 · 10k')
        self.assertEqual([results.index(label) for label in order],
                         sorted(results.index(label) for label in order))
        learn=(root/'learn/index.html').read_text()
        self.assertEqual(learn.count('../examples/gamma-native/gamma.html'),1)
        self.assertEqual(learn.count('../examples/pipeline.html'),1)
        self.assertLess(learn.index('../examples/pipeline.html'),learn.index('../examples/gamma-native/gamma.html'))
        self.assertIn('Open the additional cryostat example',learn)
        self.assertIn('Compact teaching example',learn)
        self.assertNotIn('pending saved results',results)
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
        anchors=('local-routes','browse','setup','choose','local-control','electronics','replay',
                 'native-readout','source-preparation','results','recovery','validation','workspace','downloads')
        ids=re.findall(r'\bid="([^"]+)"',guide)
        self.assertEqual(len(ids),len(set(ids)))
        self.assertTrue(set(anchors).issubset(ids))
        for name in ('choose','replay','native-readout','source-preparation','results','recovery'):
            self.assertRegex(guide,r'<details id="'+name+r'">')
        self.assertIn('four-case Cs137 10K results',guide)
        self.assertIn('WSL2',guide)
        self.assertIn('-Detector AK02 -CheckpointGroups -Resume',guide)
        native=re.search(r'<details id="native-readout">(.*?)</details>',guide,re.S).group(1)
        self.assertIn('checked local',native);self.assertIn('not supplied by a clone',native)
        resume_lines=[line for line in native.splitlines() if 'Run.cmd native-readout' in line and '-Resume' in line]
        self.assertEqual(len(resume_lines),2)
        self.assertTrue(all('-Detector' not in line and '-PrimaryIds' not in line for line in resume_lines))
        self.assertIn('electronics-group boundary after native charge',native)
        self.assertIn('not interrupted native-group recovery',guide)
        self.assertIn('not general failed-stage retry controls',guide)
        self.assertIn('Successful processing does not establish calibrated charge-collection efficiency',guide)
        self.assertIn('not Control\'s <code>-BuildPortableSourceExporter</code>',guide)
        self.assertNotIn('Electronics-only replay is still NOT_IMPLEMENTED',guide)

if __name__=='__main__':unittest.main(verbosity=2)
