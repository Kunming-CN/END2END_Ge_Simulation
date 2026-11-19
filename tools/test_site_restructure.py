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
        panels={m[1]:m[2] for m in re.finditer(
            r'<(?:article|section)\b[^>]*\bid="(gegi-shared-readout|gegi-campaign|teaching|gamma|tenk|million)"[^>]*>(.*?)</(?:article|section)>',html,re.S)}
        self.assertEqual(set(panels),{'gegi-shared-readout','gegi-campaign','teaching','tenk','million','gamma'})
        return panels

    def test_catalog_has_four_visible_main_studies_and_distinct_historical_topics(self):
        root=self.fixture(with_results=True)
        formal=root/'results/gegi-campaign';formal.mkdir(parents=True)
        (formal/'publication.json').write_text('{}')
        summary={'kind':'gegi_saved_publication_v3','initial_records':1000000,
                 'selected_conditional_imaging_groups':434,
                 'counts':{'conditional_candidate_groups':434,'conditional_candidates':837,'native_failed_groups':426}}
        (formal/'summary.json').write_text(json.dumps(summary))
        original=(formal/'summary.json').read_bytes()
        with patch('gegi_campaign_publication.validate_bundle'):
            S.apply(root)
        html=(root/'results/index.html').read_text();panels=self.result_panels(html)
        scope=DisclosureScopes();scope.feed(html)
        for ident in ('gegi-shared-readout','gegi-campaign','tenk','million'):
            self.assertEqual(scope.ids[ident],(),ident)
        self.assertIn('434 conditional signal groups; 434 selected for the joint map; 837 candidate orders',panels['gegi-campaign'])
        self.assertIn('708-group historical control',panels['gegi-campaign'])
        self.assertIn('40-iteration budget',panels['gegi-campaign'])
        self.assertIn('25 independent windows, 6.25 s total clock',panels['gegi-shared-readout'])
        self.assertIn('archived',panels['gegi-shared-readout'].lower())
        self.assertIn('4',panels['gegi-campaign'])
        self.assertIn('10,000 initial decays per case',panels['tenk'])
        self.assertIn('Li50min',panels['tenk']);self.assertIn('231',panels['tenk'])
        self.assertIn('1,000,000 initial Cs-137 decays per detector',panels['million'])
        for topic in ('gegi-short-exposure','gegi-shared-clock-controls','gegi-plane-prior-study',
                      'gegi-position-calibration','gegi-double-pulse','gegi-pairing-benchmark'):
            self.assertIn('href="'+topic+'/index.html"',html)
        for topic in ('native-li-selected-events','lithium-diagnostics','gegi-strip-study','gegi-notebook-study'):
            self.assertIn('href="'+topic+'/index.html"',html)
        self.assertIn('original-native/summary.html',html)
        self.assertIn('0/231',html)
        self.assertIn('historical-studies',scope.ids);self.assertIn('earlier-studies-title',scope.ids)
        ids=re.findall(r'\bid="([^"]+)"',html)
        self.assertEqual(len(ids),len(set(ids)))
        self.assertEqual((formal/'summary.json').read_bytes(),original)

    def test_missing_teaching_keeps_learning_directory_without_substituting_pilot(self):
        root=self.fixture();(root/'spectra/teaching-examples.json').unlink();S.apply(root)
        html=(root/'results/index.html').read_text();panels=self.result_panels(html)
        self.assertIn('unavailable in this snapshot',panels['teaching'])
        self.assertIn('../learn/index.html',panels['teaching'])
        self.assertNotIn('../examples/pipeline.html',html)
        self.assertIn('have been retired',panels['gamma'])

    def test_model_filters_keep_all_models_visible_and_qualifications_exact(self):
        root=self.fixture()
        catalog=json.loads((Path(S.__file__).resolve().parents[1]/'models/catalog.json').read_text())
        (root/'models/catalog.json').write_text(json.dumps(catalog));S.apply(root)
        html=(root/'detectors/index.html').read_text();scope=DisclosureScopes();scope.feed(html)
        models=[item['id'] for item in catalog['detectors']]
        self.assertEqual(len(models),17)
        self.assertEqual(len(re.findall(r'<article class="card" data-model=',html)),17)
        for name in ('geometry','assembly','status'):
            self.assertIn('id="filter-'+name+'"',html)
        self.assertIn('role="status" aria-live="polite"',html)
        self.assertEqual(html.count('data-assembly="lbnl"'),10)
        self.assertEqual(html.count('data-assembly="gegi"'),1)
        self.assertEqual(html.count('data-assembly="larger"'),6)
        for item in catalog['detectors']:
            model=item['id'];scopes=[closed for href,closed in scope.links if href==model+'/index.html']
            self.assertEqual(len(scopes),2,model);self.assertTrue(all(not closed for closed in scopes),model)
            self.assertIn(item['status'],html)
            self.assertIn('<code>'+model+'</code>',html)
        self.assertIn('PONaMa1 reference',html)
        self.assertIn('KMRC01 candidate',html)
        self.assertIn('SAP18 ring scenario',html)
        self.assertIn('GeRC02 Li50min operating variant; catalog download is the 30-minute baseline.',html)

    def test_home_has_three_task_actions_and_accurate_featured_study(self):
        home=S.homepage(commercial=True);scope=DisclosureScopes();scope.feed(home)
        actions=re.search(r'<div class="home-actions"[^>]*>(.*?)</div>',home,re.S)[1]
        self.assertEqual(re.findall(r'href="([^"]+)"',actions),['results/index.html','learn/signals/index.html','guide.html'])
        self.assertIn('25 × 250 ms',home)
        self.assertIn('archived single-isotope histories',home)
        self.assertIn('6.25 s',home);self.assertIn('reset between windows',home)
        self.assertIn('results/gegi-shared-readout/index.html',home)
        self.assertIn('simultaneous-spectrum-and-images.png',home)
        self.assertNotIn('<svg',home)
        self.assertNotIn('at least 60 seconds',home)
        self.assertNotIn('continuous acquisition',home)
        self.assertNotIn('source-plane maps',S.homepage(False))

    def test_shared_primary_tasks_and_real_learning_directory(self):
        root=self.fixture();result=S.apply(root)
        self.assertEqual(result['detectors'],2)
        home=(root/'index.html').read_text()
        self.assertIn('<head>',home);self.assertIn('</head>',home)
        self.assertEqual(home.count('class="site-brand"'),1)
        for label in S.PRIMARY:self.assertIn(label,home)
        primary=re.search(r'<nav aria-label="Primary"[^>]*>(.*?)</nav>',home)[1]
        self.assertEqual(re.findall(r'href="([^"]+)"',primary),[path for path,label in S.DISPLAY_PRIMARY])
        learn=(root/'learn/index.html').read_text()
        self.assertNotIn('http-equiv="refresh"',learn)
        for href in ('signals/index.html','../methods/index.html','../detectors/index.html','../guide.html','../results/cs137-10k/index.html'):
            self.assertIn('href="'+href+'"',learn)
        self.assertIn('model variant, primary and group IDs',learn)
        methods=(root/'methods/index.html').read_text()
        self.assertIn('LBNL analog electronics',methods)
        self.assertIn('GeGI digitized strip readout',methods)
        self.assertIn('X and Y are two measurements of the same deposited charge',methods)
        self.assertIn('an unknown response is not zero',methods)

    def test_million_case_counts_and_stage_links_stay_independent_of_tenk(self):
        root=self.fixture(with_results=True);S.apply(root)
        overview=(root/'results/cs137-1m/index.html').read_text()
        for count in ('12,420','10,757','11,272','10,915'):self.assertIn(count,overview)
        self.assertIn('href="spectra/response.html"',overview)
        self.assertIn('href="spectra/deposition.html"',overview)
        self.assertIn('No 3D events from these million-decay runs are published',overview)
        self.assertIn('3D events from the separate 10K study',overview)
        self.assertIn('isolated 100 µs reset windows',overview)
        panels=self.result_panels((root/'results/index.html').read_text())
        self.assertNotIn('viewers/events.html',panels['million'])

    def test_repeat_application_is_idempotent_and_keeps_scientific_inputs(self):
        root=self.fixture(with_results=True)
        originals={p.relative_to(root):p.read_bytes() for p in (root/'examples').rglob('*') if p.is_file()}
        S.apply(root)
        owned=('index.html','learn/index.html','detectors/index.html','assemblies/index.html','results/index.html','guide.html','results/cs137-1m/index.html','results/cs137-10k/index.html','methods/index.html','scenarios/lbnl-cs137/index.html')
        first={p:(root/p).read_bytes() for p in owned};S.apply(root)
        self.assertEqual(first,{p:(root/p).read_bytes() for p in owned})
        self.assertEqual(originals,{p:(root/p).read_bytes() for p in originals})

    def test_retired_pilot_evidence_is_not_validated_or_rewritten_by_catalog(self):
        root=self.fixture(with_results=True)
        for folder,name,payload in (('gamma-native','gamma.html',b'original gamma\r\n'),('gegi','index.html',b'original GeGI\r\n')):
            directory=root/'examples'/folder;directory.mkdir();(directory/name).write_bytes(payload)
        before={p.relative_to(root):p.read_bytes() for p in (root/'examples').rglob('*') if p.is_file()}
        with patch('gamma_showcase.validate_bundle') as gamma,patch('gegi_publication.validate_bundle') as gegi:
            S.apply(root)
        gamma.assert_not_called();gegi.assert_not_called()
        self.assertEqual(before,{p:(root/p).read_bytes() for p in before})
        results=(root/'results/index.html').read_text()
        self.assertIn('retirement record',results)
        self.assertNotIn('imaging-accepted events',results)

    def test_source_removal_shows_missing_studies_without_reusing_other_science(self):
        root=self.fixture(with_results=True);S.apply(root)
        for p in ('examples/cs137-1m-response/summary.json','examples/cs137-1m/summary.json','examples/cs137-10k/comparison.html'):(root/p).unlink()
        S.apply(root)
        panels=self.result_panels((root/'results/index.html').read_text())
        for ident in ('gegi-shared-readout','gegi-campaign','tenk','million'):
            self.assertIn('Unavailable in this saved snapshot',panels[ident])
            self.assertNotRegex(panels[ident],r'<a\b')
        for ident in ('cs137-1m','cs137-10k'):
            self.assertIn('unavailable in this snapshot',(root/'results'/ident/'index.html').read_text())
        self.assertIn('../learn/signals/index.html',panels['teaching'])

    def test_unsafe_detector_id_is_refused(self):
        root=self.fixture();catalog=json.loads((root/'models/catalog.json').read_text())
        catalog['detectors'][0]['id']='../escape';(root/'models/catalog.json').write_text(json.dumps(catalog))
        with self.assertRaisesRegex(ValueError,'Unsafe detector ID'):S.apply(root)

    def test_guide_follows_task_order_and_preserves_old_anchors_and_scopes(self):
        root=self.fixture();S.apply(root);guide=(root/'guide.html').read_text()
        order=('download-software','setup','setup-macos','setup-linux','local-control','find-results','control-recovery','saved-analysis','troubleshooting')
        offsets=[guide.index('id="'+ident+'"') for ident in order]
        self.assertEqual(offsets,sorted(offsets))
        ids=re.findall(r'\bid="([^"]+)"',guide);self.assertEqual(len(ids),len(set(ids)))
        self.assertTrue(set(('local-routes','browse','setup','choose','local-control','electronics','replay','native-readout','source-preparation','results','recovery','validation','workspace','downloads')).issubset(ids))
        for name in ('choose','replay','native-readout','source-preparation','results','recovery'):
            self.assertRegex(guide,r'<details id="'+name+r'">')
        self.assertIn('1,143,142 bytes',guide);self.assertIn('303,891,603 bytes',guide)
        self.assertIn('student-runtime-f44859b48267',guide)
        self.assertIn('no packaged Linux Control launcher',guide)
        self.assertIn('field caches and calibration banks are excluded',guide)
        self.assertIn('four independent GeGI source acquisitions',guide)
        self.assertIn('WSL2',guide)
        self.assertIn('not interrupted native-group recovery',guide)
        self.assertIn('not general failed-stage retry controls',guide)
        self.assertIn('Successful processing does not establish calibrated charge-collection efficiency',guide)
        native=re.search(r'<details id="native-readout">(.*?)</details>',guide,re.S)[1]
        resume_lines=[line for line in native.splitlines() if 'Run.cmd native-readout' in line and '-Resume' in line]
        self.assertEqual(len(resume_lines),2)
        self.assertTrue(all('-Detector' not in line and '-PrimaryIds' not in line for line in resume_lines))

    def test_conditional_summary_never_becomes_imaging_acceptance(self):
        root=self.fixture();formal=root/'results/gegi-campaign';formal.mkdir(parents=True)
        (formal/'publication.json').write_text('{}')
        (formal/'summary.json').write_text(json.dumps({'kind':'gegi_saved_publication_v3','initial_records':1000000,
            'selected_conditional_imaging_groups':162,'counts':{'conditional_candidate_groups':434,'native_failed_groups':426}}))
        original=(formal/'summary.json').read_bytes()
        with patch('gegi_campaign_publication.validate_bundle'):S.apply(root)
        text=(root/'results/index.html').read_text()
        self.assertIn('434 conditional signal groups',text)
        self.assertIn('162 selected for the joint map',text)
        self.assertIn('Same-energy source separation remains unresolved',text)
        self.assertNotIn('imaging-accepted',text)
        self.assertEqual((formal/'summary.json').read_bytes(),original)

if __name__=='__main__':unittest.main(verbosity=2)
