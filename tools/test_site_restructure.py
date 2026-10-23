import json,re,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from html.parser import HTMLParser
import site_restructure as S

class DisclosureScopes(HTMLParser):
    def __init__(self):
        super().__init__();self.closed=[];self.ids={};self.links=[]
    def handle_starttag(self,tag,attrs):
        values=dict(attrs)
        if tag=='details':
            self.closed.append(values.get('id','details') if 'open' not in values else None)
        scope=tuple(ident for ident in self.closed if ident)
        if 'id' in values:self.ids[values['id']]=scope
        if tag=='a':self.links.append((values['href'],scope))
    def handle_endtag(self,tag):
        if tag=='details':self.closed.pop()

class SiteStructureTests(unittest.TestCase):
    def test_historical_gegi_payload_is_exact_and_only_loaded_on_expansion(self):
        import hashlib
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'.local') as tmp:
            root=Path(tmp);script=root/'gegi_signal_journey.js'
            original=(Path(S.__file__).parent/'gegi_signal_journey.js').read_bytes();script.write_bytes(original)
            payload='{"records": [1.2345678901234567, null], "identity": "historical"}'
            text=('<details><summary>Historical signals</summary><div id="gegi-signal-journey"></div></details>'
                  '<script type="application/json" id="gegi-journey-data">'+payload+'</script>'
                  '<script src="gegi_signal_journey.js"></script>'
                  '<script>GeGISignalJourney.mount(document.getElementById("gegi-signal-journey"),'
                  'JSON.parse(document.getElementById("gegi-journey-data").textContent),{scope:"student"});</script>')
            record={'artifacts':{}}
            result=S.defer_gegi_journey(root,text,record)
            self.assertNotIn('gegi-journey-data',result)
            self.assertNotIn(payload,result)
            self.assertIn('if(!panel.open||loading||ready)return',result)
            self.assertNotIn('<script src="gegi_signal_journey.js">',result)
            self.assertIn('panel.addEventListener(\'toggle\',load)',result)
            moved=script.read_bytes()
            self.assertTrue(moved.startswith(original))
            self.assertIn(payload.encode(),moved)
            self.assertEqual(record['deferred_historical_journey']['payload_sha256'],hashlib.sha256(payload.encode()).hexdigest())
            self.assertEqual(S.defer_gegi_journey(root,result,record),result)
            self.assertEqual(script.read_bytes(),moved)

    def fixture(self,with_results=False):
        t=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'.local'); self.addCleanup(t.cleanup); root=Path(t.name)
        (root/'models').mkdir(); (root/'detectors/AK02').mkdir(parents=True);(root/'detectors/SAP22').mkdir(parents=True)
        (root/'index.html').write_text('old',encoding='utf-8')
        for ident in ('AK02','SAP22'):
            (root/'detectors'/ident/'index.html').write_text('<html><main><h1>'+ident+'</h1></main></html>',encoding='utf-8')
        catalog={'detectors':[{'id':'AK02','status':'geometry','coordinate_system':'cylindrical','contacts':[{},{}]},
                              {'id':'SAP22','status':'geometry','coordinate_system':'cylindrical','contacts':[{},{}]}]}
        (root/'models/catalog.json').write_text(json.dumps(catalog),encoding='utf-8')
        (root/'examples').mkdir()
        (root/'examples/data.json').write_bytes(b'{"fixture":"saved teaching data"}\r\n')
        (root/'spectra').mkdir();(root/'spectra/teaching-examples.json').write_text('{}')
        if with_results:
            (root/'examples/cs137-1m-response').mkdir(parents=True);(root/'examples/cs137-1m').mkdir(parents=True)
            summary={'totals':{'accepted':21672},'models':{
                'AK02':{'positive_ge_decays':12420,'response':{'accepted':10757}},
                'SAP22':{'positive_ge_decays':11272,'response':{'accepted':10915}}}}
            (root/'examples/cs137-1m-response/summary.json').write_text(json.dumps(summary),encoding='utf-8')
            (root/'examples/cs137-1m/summary.json').write_text('{}',encoding='utf-8')
            (root/'examples/cs137-10k').mkdir();(root/'examples/cs137-10k/comparison.html').write_text('x')
        return root
    def result_panels(self,html):
        panels={m.group(1):m.group(2) for m in re.finditer(
            r'<section id="(gegi|teaching|gamma|tenk|million)"[^>]*>(.*?)</section>',html,re.S)}
        self.assertEqual(set(panels),{'gegi','teaching','tenk','million','gamma'})
        return panels

    def test_current_gegi_and_campaigns_precede_collapsed_small_studies(self):
        root=self.fixture(with_results=True)
        rings=root/'examples/cs137-10k-rings';rings.mkdir();(rings/'manifest.json').write_text('{}')
        formal=root/'results/gegi-campaign';formal.mkdir(parents=True)
        (formal/'publication.json').write_text('{}')
        summary={'kind':'gegi_saved_publication_v3','initial_records':1000000,
                 'selected_conditional_imaging_groups':434,
                 'counts':{'conditional_candidate_groups':434,'conditional_candidates':837,
                           'native_failed_groups':426}}
        (formal/'summary.json').write_text(json.dumps(summary))
        original=(formal/'summary.json').read_bytes()
        gamma=root/'examples/gamma-native';gamma.mkdir();(gamma/'gamma.html').write_bytes(b'original gamma')
        with patch('gegi_campaign_publication.validate_bundle'),patch('gamma_showcase.validate_bundle'):
            S.apply(root)
        html=(root/'results/index.html').read_text();panels=self.result_panels(html)
        self.assertEqual(list(panels),['gegi','teaching','tenk','million','gamma'])
        self.assertIn('All 434 conditional signal groups · 837 candidate cones',panels['gegi'])
        self.assertIn('energy layers are optional',panels['gegi'])
        self.assertEqual(html.count('Same-energy source separation remains unresolved'),1)
        self.assertIn('six representative Cs137 signals',panels['teaching'])
        self.assertIn('four separate cases',panels['tenk'])
        self.assertIn('one million initial decays per detector',panels['million'])
        scope=DisclosureScopes();scope.feed(html)
        for ident in ('gegi','teaching','tenk','million','current-ring-10k'):
            self.assertEqual(scope.ids[ident],(),ident)
        self.assertEqual(scope.ids['gamma'],('historical-studies',))
        for href in ('../examples/pipeline.html','../examples/gegi/index.html',
                     '../examples/gamma-native/gamma.html'):
            self.assertNotIn(href,[url for url,closed in scope.links])
        ids=re.findall(r'\bid="([^"]+)"',html)
        self.assertEqual(len(ids),len(set(ids)))
        self.assertEqual((formal/'summary.json').read_bytes(),original)
        self.assertEqual((gamma/'gamma.html').read_bytes(),b'original gamma')

    def test_bare_detector_never_replaces_missing_current_teaching(self):
        root=self.fixture();(root/'spectra/teaching-examples.json').unlink();S.apply(root)
        html=(root/'results/index.html').read_text();scope=DisclosureScopes();scope.feed(html)
        self.assertEqual(scope.ids['teaching'],())
        self.assertEqual(scope.ids['gamma'],('historical-studies',))
        self.assertIn('unavailable in this snapshot',self.result_panels(html)['teaching'])
        self.assertIn('have been retired',html)
        self.assertNotIn('../examples/pipeline.html',html)

    def test_catalog_folds_only_unavailable_models_and_keeps_all_seventeen(self):
        root=self.fixture()
        catalog=json.loads((Path(S.__file__).resolve().parents[1]/'models/catalog.json').read_text())
        (root/'models/catalog.json').write_text(json.dumps(catalog))
        S.apply(root)
        html=(root/'detectors/index.html').read_text();scope=DisclosureScopes();scope.feed(html)
        capabilities=S.detector_pages.execution_capabilities()
        runnable=(S.detector_pages.control_capabilities(capabilities)|
                  S.detector_pages.dedicated_control_capabilities(capabilities))
        models=[item['id'] for item in catalog['detectors']]
        self.assertEqual(len(models),17)
        self.assertEqual(len(set(models)-runnable),6)
        self.assertIn('6 more models · larger cryostat needed',html)
        self.assertEqual(html.count('<article class="card">'),17)
        for model in models:
            scopes=[closed for href,closed in scope.links if href==model+'/index.html']
            self.assertEqual(len(scopes),2,model)
            expected=() if model in runnable else ('other-models',)
            self.assertTrue(all(closed==expected for closed in scopes),model)
            capability=S.detector_pages.catalog_model_summary(model)
            self.assertIn(capability['label'],html)
            self.assertIn(capability['detail'],html)

    def test_primary_tasks_and_dataset_entries(self):
        root=self.fixture()
        with patch('gamma_showcase.validate_bundle') as checked:
            result=S.apply(root)
        checked.assert_not_called()
        home=(root/'index.html').read_text()
        self.assertEqual(result['detectors'],2)
        for label in S.PRIMARY:self.assertIn(label,home)
        self.assertEqual(home.count('<article class="card">'),0)
        self.assertNotIn('href="downloads/all-models.zip"',home)
        self.assertIn('href="spectra/pipeline.html">Learn the signal chain',home)
        primary=re.search(r'<nav aria-label="Primary"[^>]*>(.*?)</nav>',home).group(1)
        self.assertEqual(re.findall(r'href="([^"]+)"',primary),
                         ['results/index.html','detectors/index.html','assemblies/index.html','guide.html','methods/index.html'])
        self.assertEqual(re.findall(r'>([^<]+)</a>',primary),['Results','Detectors','Assemblies','Run locally','Methods'])
        self.assertIn('with Control',home)
        for p in ('learn/index.html','detectors/index.html','results/index.html',
                  'methods/index.html','scenarios/lbnl-cs137/index.html','assemblies/index.html'):
            self.assertTrue((root/p).is_file(),p)
        learn=(root/'learn/index.html').read_text()
        self.assertEqual(learn.count('href="../spectra/pipeline.html"'),1)
        self.assertNotIn('../examples/gamma-native/gamma.html',learn)
        panels=self.result_panels((root/'results/index.html').read_text())
        self.assertIn('../spectra/pipeline.html',panels['teaching'])
        self.assertNotIn('../examples/data.json',panels['teaching'])
        self.assertEqual(panels['teaching'].count('<a '),1)
        for ident in ('gegi','tenk','million'):
            self.assertIn('unavailable in this snapshot',panels[ident])
        scenario=(root/'scenarios/lbnl-cs137/index.html').read_text()
        self.assertIn('guide.html#choose',scenario)
        self.assertIn('guide.html',scenario)
        self.assertNotIn('Run.cmd run',scenario)
        self.assertIn('Cs137, Am241, Ba133 and Co60',scenario)
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
        # Visible task entrances lead to the dataset catalog; legacy destinations
        # remain available without implying that their saved event IDs match.
        for href in ('index.html','results/index.html','detectors/index.html','assemblies/index.html','guide.html','methods/index.html'):
            self.assertIn(href,parser.outside)
        for href in ('spectra/cs137-10k.html','viewers/events.html','downloads/all-models.zip'):
            self.assertNotIn(href,parser.links)
        self.assertIn('spectra/pipeline.html',parser.outside)
        self.assertNotIn('results/cs137-10k/index.html',parser.outside)
        self.assertNotIn('1,000,000 initial decays per detector',home)
        self.assertNotIn('Methods and retained links',home)
        for anchor in ('pipeline-example','native-cs137-10k','current-ring-10k'):
            self.assertIn('id="'+anchor+'"',home)
        self.assertIn('<summary>More project resources</summary>',home)

    def test_home_explains_the_chain_without_cropped_scientific_plots(self):
        home=S.homepage()
        self.assertIn('END2END_Ge_Simulation',home)
        self.assertIn('high-purity germanium (HPGe)',home)
        self.assertIn('Conceptual diagram',home)
        self.assertIn('Geant4 / remage',home)
        self.assertIn('SolidStateDetectors.jl',home)
        self.assertIn('analog-to-digital converter',home)
        self.assertEqual(home.count('<svg '),3)
        self.assertEqual(re.findall(r'<a href="([^"]+)"',home),
                         ['spectra/pipeline.html','results/index.html','guide.html'])
        self.assertNotIn('polyline',home)
        self.assertNotIn('primary 61',home)
        self.assertNotIn('first 5',home)
        self.assertNotIn('half',home)
        self.assertIn('Windows · local setup',home)

    def test_result_hubs_are_conditional(self):
        root=self.fixture(with_results=True);S.apply(root)
        self.assertTrue((root/'results/cs137-1m/index.html').is_file())
        self.assertTrue((root/'results/cs137-10k/index.html').is_file())
        scenario=(root/'scenarios/lbnl-cs137/index.html').read_text()
        self.assertNotIn('Saved campaigns',scenario)
        overview=(root/'results/cs137-1m/index.html').read_text()
        self.assertIn('12,420',overview);self.assertIn('10,757',overview)
        self.assertIn('11,272',overview);self.assertIn('10,915',overview)
        self.assertIn('href="../../spectra/million-response.html">Response spectra · AK02 &amp; SAP22',overview)
        self.assertIn('href="../../spectra/million-truth.html">Deposition spectra · AK02 &amp; SAP22',overview)
        results=(root/'results/index.html').read_text()
        panels=self.result_panels(results)
        self.assertIn('Six saved signals',panels['teaching'])
        self.assertIn('have been retired',panels['gamma'])
        self.assertIn('two separate cases',panels['tenk'])
        self.assertIn('cs137-10k/index.html',panels['tenk'])
        self.assertIn('cs137-1m/index.html',panels['million'])
        self.assertIn('one million initial decays per detector',panels['million'])
        self.assertNotIn('viewers/events.html',panels['million'])
        self.assertNotIn('spectra/cs137-10k.html',panels['teaching'])

    def test_repeat_application_is_idempotent(self):
        root=self.fixture(with_results=True);S.apply(root)
        owned=('index.html','learn/index.html','detectors/index.html','assemblies/index.html','results/index.html','results/cs137-1m/index.html','results/cs137-10k/index.html','methods/index.html','scenarios/lbnl-cs137/index.html')
        first={p:(root/p).read_bytes() for p in owned};S.apply(root)
        self.assertEqual(first,{p:(root/p).read_bytes() for p in owned})

    def test_assembly_entries_open_the_shared_saved_event_viewer(self):
        root=self.fixture();S.apply(root)
        for relative,prefix in (('assemblies/index.html','../'),
                                ('scenarios/lbnl-cs137/index.html','../../')):
            text=(root/relative).read_text()
            self.assertIn('href="'+prefix+'viewers/events.html?model=AK02&amp;view=positive"',text)
            self.assertNotIn('view=geometry',text)
            parser=DisclosureScopes();parser.feed(text)
            viewer_links=[href for href,closed in parser.links if 'viewers/events.html?' in href]
            self.assertEqual(viewer_links,[prefix+'viewers/events.html?model=AK02&view=positive'])
            self.assertNotIn('event=',viewer_links[0])
            self.assertNotIn('group=',viewer_links[0])

    def test_retired_gamma_is_not_validated_promoted_or_modified_by_hub(self):
        root=self.fixture(with_results=True);S.apply(root)
        before={p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*') if p.is_file()}
        gamma=root/'examples/gamma-native';gamma.mkdir(parents=True)
        (gamma/'gamma.html').write_bytes(b'synthetic checked fixture\r\n')
        with patch('gamma_showcase.validate_bundle') as checked:
            S.apply(root)
        checked.assert_not_called()
        results=(root/'results/index.html').read_text()
        panels=self.result_panels(results)
        self.assertIn('40-primary cryostat gamma',panels['gamma'])
        self.assertNotIn('Completed gamma',results)
        self.assertNotIn('../examples/gamma-native/gamma.html',results)
        self.assertIn('../spectra/pipeline.html',panels['teaching'])
        self.assertNotIn('../examples/gamma-native/gamma.html',panels['teaching'])
        learn=(root/'learn/index.html').read_text()
        self.assertNotIn('../examples/gamma-native/gamma.html',learn)
        self.assertEqual(learn.count('href="../spectra/pipeline.html"'),1)
        self.assertEqual((root/'learn/index.html').read_bytes(),before['learn/index.html'])
        self.assertNotIn('pending saved results',results)
        for name,raw in before.items():
            if name!='results/index.html':
                self.assertEqual((root/name).read_bytes(),raw,name)
        self.assertEqual((gamma/'gamma.html').read_bytes(),b'synthetic checked fixture\r\n')
        invalid_before={p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*') if p.is_file()}
        with patch('gamma_showcase.validate_bundle',side_effect=ValueError('retired gamma must not be read')) as checked:
            S.apply(root)
        checked.assert_not_called()
        self.assertEqual(invalid_before,{p.relative_to(root).as_posix():p.read_bytes()
                                       for p in root.rglob('*') if p.is_file()})
    def test_source_removal_replaces_owned_hubs_with_unavailable_pages(self):
        root=self.fixture(with_results=True);S.apply(root)
        (root/'examples/cs137-1m-response/summary.json').unlink();(root/'examples/cs137-1m/summary.json').unlink();(root/'examples/cs137-10k/comparison.html').unlink()
        S.apply(root)
        panels=self.result_panels((root/'results/index.html').read_text())
        self.assertIn('../spectra/pipeline.html',panels['teaching'])
        for ident in ('gegi','tenk','million'):
            self.assertIn('unavailable in this snapshot',panels[ident])
            self.assertNotRegex(panels[ident],r'<a\b')
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
        self.assertIn('four-case Cs137 10K',guide)
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

    def test_gegi_formal_campaign_takes_over_public_entries(self):
        root=self.fixture();saved=root/'examples/gegi';saved.mkdir(parents=True)
        (saved/'publication.json').write_bytes(b'legacy fixture')
        formal=root/'results/gegi-campaign';formal.mkdir(parents=True)
        (formal/'publication.json').write_bytes(b'{}')
        (formal/'summary.json').write_text(json.dumps({'processed_initial_records':1000000,
            'groups':{'a':{'counts':{'imaging_accepted_groups':708,'native_failed_groups':426}}}}))
        with patch('gegi_campaign_publication.validate_bundle') as checked,patch('gegi_publication.validate_bundle') as old:
            S.apply(root)
        checked.assert_called_once_with(formal);old.assert_not_called()
        for path in ('results/index.html',):
            text=(root/path).read_text(encoding='utf-8')
            self.assertIn('1,000,000 initial records',text)
            self.assertIn('708 imaging-accepted pulse groups',text)
            self.assertIn('results/gegi-campaign/index.html',text)
            if path=='index.html':self.assertNotIn('examples/gegi/index.html',text)

    def test_conditional_gegi_summary_never_becomes_imaging_acceptance(self):
        root=self.fixture();formal=root/'results/gegi-campaign';formal.mkdir(parents=True)
        (formal/'publication.json').write_bytes(b'{}')
        (formal/'summary.json').write_text(json.dumps({'kind':'gegi_saved_publication_v3',
            'initial_records':1000000,'selected_conditional_imaging_groups':162,
            'counts':{'conditional_candidate_groups':434,'native_failed_groups':426}}))
        original=(formal/'summary.json').read_bytes()
        with patch('gegi_campaign_publication.validate_bundle'):
            S.apply(root)
        text=(root/'results/index.html').read_text(encoding='utf-8')
        self.assertIn('434 conditional signal groups',text)
        self.assertIn('162 selected for the joint map',text)
        self.assertIn('Same-energy source separation remains unresolved',text)
        self.assertNotIn('imaging-accepted',text)
        self.assertEqual((formal/'summary.json').read_bytes(),original)

    def test_retired_gegi_is_not_promoted_or_rewritten_by_hub(self):
        root=self.fixture();saved=root/'examples/gegi';saved.mkdir(parents=True)
        payload={'kind':'gegi_saved_source_comparison_v1','counts':{'initial_primaries':10000},
                 'imaging':{'accepted_events':5,'ambiguous_events':4}}
        (saved/'summary.json').write_text(json.dumps(payload),encoding='utf-8')
        (saved/'publication.json').write_bytes(b'checked fixture')
        (saved/'index.html').write_bytes(b'<html>immutable saved science</html>\r\n')
        before={p.name:p.read_bytes() for p in saved.iterdir()}
        with patch('gegi_publication.validate_bundle') as checked:
            S.apply(root)
        checked.assert_not_called()
        self.assertEqual(before,{p.name:p.read_bytes() for p in saved.iterdir()})
        home=(root/'index.html').read_text(encoding='utf-8')
        results=(root/'results/index.html').read_text(encoding='utf-8')
        self.assertNotIn('imaging-accepted events',home)
        text=self.result_panels(results)['gegi']
        self.assertIn('unavailable in this snapshot',text)
        self.assertNotIn('examples/gegi/index.html',results)
        self.assertNotIn('5 imaging-accepted events',results)
        assemblies=(root/'assemblies/index.html').read_text(encoding='utf-8')
        for href in ('../scenarios/lbnl-cs137/index.html','gegi/index.html',
                     '../viewers/events.html?model=AK02&amp;view=positive'):
            self.assertIn(href,assemblies)

if __name__=='__main__':unittest.main(verbosity=2)
