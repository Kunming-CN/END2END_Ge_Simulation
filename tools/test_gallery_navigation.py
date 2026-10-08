"""Small presentation fixtures; no science, public build, server or export."""
import hashlib
from html import unescape
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import tempfile
import unittest
import zipfile
from unittest.mock import patch

import site_detector_pages as D
import site_restructure as N
import ring_site as R

ROOT=Path(__file__).resolve().parents[1]

class Elements(HTMLParser):
    def __init__(self):super().__init__();self.tags=[]
    def handle_starttag(self,tag,attrs):self.tags.append((tag,dict(attrs)))

class GalleryTests(unittest.TestCase):
    def setUp(self):
        base=ROOT/'.local';base.mkdir(exist_ok=True)
        self.temporary=tempfile.TemporaryDirectory(prefix='gallery-navigation-test-',dir=base)
        self.addCleanup(self.temporary.cleanup);self.site=Path(self.temporary.name)
        self.catalog=json.loads((ROOT/'models/catalog.json').read_text())
        (self.site/'models').mkdir();(self.site/'models/catalog.json').write_text(json.dumps(self.catalog))
        (self.site/'index.html').write_text('<main>Saved snapshot fixture</main>')
        for item in self.catalog['detectors']:
            folder=self.site/'detectors'/item['id'];(folder/'runs'/D.RUN).mkdir(parents=True)
            (folder/'runs'/D.RUN/'01_geometry.png').write_bytes(b'fixture image bytes')
            (folder/'index.html').write_text('<html><body><main><section id="original-evidence"><p>Earlier saved signed value −0.00012; original assumptions retained.</p></section></main></body></html>')
            (folder/'geometry.html').write_text('<html>Saved geometry fixture</html>')
        self.notebook=('<html><body><nav>Back to GeGI results | Supplementary saved notebook; not a live simulation. Original code inputs are omitted. Parameters belong to this earlier study.</nav>'
            '<p>The full calculation used <strong>5,068,800 nodes</strong>. Dimensions and model inputs are listed in <code>README.md</code>.</p>'
            '<p>Kernel: <strong>Julia 1.13 — GeGI</strong>. Run all cells in order.</p>'
            '<h2 id="saved-output">Earlier output</h2><img src="saved.png"></body></html>')
        (self.site/'detectors/GeGI_3D/supplement.html').write_text(self.notebook)

    def structure(self):
        with patch('ssd_geometry_publication.refresh_viewers'):
            N.apply(self.site)

    def test_all17_cards_use_reviewed_types_one_overview_target_lazy_contained_images(self):
        self.structure();html=(self.site/'detectors/index.html').read_text();parser=Elements();parser.feed(html)
        images=[attrs for tag,attrs in parser.tags if tag=='img']
        self.assertEqual(len(images),17);self.assertEqual(set(D.TYPE_LABELS),{i['id'] for i in self.catalog['detectors']})
        cards=re.findall(r'<article class="card">.*?</article>',html,re.S);self.assertEqual(len(cards),17)
        for item,card in zip(sorted(self.catalog['detectors'],key=lambda i:(i['id'] not in D.control_capabilities(),self.catalog['detectors'].index(i))),cards):
            model=item['id'];poster=f'{model}/runs/{D.RUN}/01_geometry.png'
            self.assertNotIn('href="'+poster+'"',card);self.assertIn('src="'+poster+'"',card)
            self.assertEqual(set(re.findall(r'href="([^"]+)"',card)),{model+'/index.html'})
            self.assertIn('loading="lazy"',card);self.assertIn('object-fit:contain',card)
            self.assertIn(D.TYPE_LABELS[model],unescape(card));self.assertNotIn('class="tag"',card)
            self.assertNotIn(item['status'],unescape(card))
        before={p.relative_to(self.site).as_posix():p.read_bytes() for p in self.site.rglob('*') if p.is_file()}
        self.structure();self.assertEqual(before,{p.relative_to(self.site).as_posix():p.read_bytes() for p in self.site.rglob('*') if p.is_file()})

    def test_secondary_model_qualification_and_ge_signal_are_preserved(self):
        self.structure()
        for item in self.catalog['detectors']:
            html=(self.site/'detectors'/item['id']/'technical.html').read_text()
            self.assertIn('<strong>GeSignal</strong>',html);self.assertNotIn('END2END Ge Simulation',html)
            self.assertIn(item['status'],unescape(html))
            for statement in item['assumptions']+item.get('sources',[]):self.assertIn(statement,unescape(html))
            self.assertIn('Canonical model catalog and hashes',html)
        generic={model for model,row in D.execution_capabilities().items() if row['lbnl_execution_implemented']}
        self.assertEqual(generic,{'AK02','SAP22'})
        self.assertEqual(D.control_capabilities(),{'AK02','SAP22','GeRC02','KMRC01_candidate','SAP18_ring08_scenario','AK01','SAP16','SAP17','Bipolar_reference_3D','KL01_3D'})
        self.assertIn('Control supports GeRC02',(self.site/'detectors/GeRC02/index.html').read_text())
        self.assertIn('needs a future larger cryostat',(self.site/'detectors/GeGI_3D/index.html').read_text())
        presentation=D.catalog_control_capabilities(D.execution_capabilities())
        blocked={model for model,row in presentation.items() if not row['available']}
        self.assertEqual(len(blocked),7)
        for model in blocked:
            page=unescape((self.site/'detectors'/model/'index.html').read_text())
            self.assertIn(presentation[model]['reason'],page)
            self.assertNotIn('not integrated',page)
        self.assertIn('7 models need a future larger cryostat',(self.site/'detectors/index.html').read_text())


    def test_catalog_presentation_rejects_changed_authority_and_model_binding(self):
        refs=('scenarios/catalog-presentation.json','scenarios/detector-capabilities.json',
              'models/catalog.json','transport/cryostat_nominal.json')
        with tempfile.TemporaryDirectory(dir=ROOT/'.local') as directory:
            root=Path(directory)
            for ref in refs:
                path=root/ref;path.parent.mkdir(parents=True,exist_ok=True)
                path.write_bytes((ROOT/ref).read_bytes())
            cap=D.execution_capabilities()
            self.assertEqual(len(D.catalog_control_capabilities(cap,root)),17)
            snapshot=root/'scenarios/catalog-presentation.json'
            data=json.loads(snapshot.read_text(encoding='utf-8'))
            data['models'][0]['model_sha256']='0'*64
            snapshot.write_text(json.dumps(data),encoding='utf-8',newline='\n')
            with self.assertRaisesRegex(ValueError,'model binding'):
                D.catalog_control_capabilities(cap,root)
            snapshot.write_bytes((ROOT/refs[0]).read_bytes())
            (root/'transport/cryostat_nominal.json').write_bytes(b'changed authority')
            with self.assertRaisesRegex(ValueError,'authority bytes changed'):
                D.catalog_control_capabilities(cap,root)

    def test_three_actions_ring_context_and_no_stale_pending_claim(self):
        self.structure();home=(self.site/'index.html').read_text();results=(self.site/'results/index.html').read_text()
        self.assertEqual(re.findall(r'<article class="card"><h2>(.*?)</h2>',home),['Results','Detectors','Run locally','Methods'])
        self.assertNotIn('pending saved results',results)
        scenario=(self.site/'scenarios/lbnl-cs137/index.html').read_text()
        self.assertIn('Control offers 10 separate detector configurations',scenario)
        self.assertIn('Legacy Run.cmd',scenario);self.assertIn('GeRC02 Li50min',scenario)

    def test_notebook_invitation_corrected_without_saved_output_or_anchor_loss(self):
        corrected=D.archive_notebook(self.notebook)
        self.assertNotIn('Run all cells in order',corrected);self.assertIn('Recorded notebook kernel',corrected)
        self.assertIn('private <code>README.md</code>',corrected);self.assertIn('not included in this archive',corrected)
        for retained in ('5,068,800 nodes','id="saved-output"','<img src="saved.png">'):self.assertIn(retained,corrected)
        self.assertEqual(D.archive_notebook(corrected),corrected)
        self.assertIn('Run all cells in order',self.notebook)
        self.assertEqual(corrected.count('aria-label="Primary"'),1)
        self.assertEqual(corrected.count('aria-label="Breadcrumb"'),1)
        self.assertIn('href="gallery.html">Return to GeGI saved fields &amp; signals',corrected)

    def test_detector_views_and_saved_studies_keep_one_shared_navigation(self):
        self.structure()
        for item in self.catalog['detectors']:
            model=item['id'];folder=self.site/'detectors'/model
            for name in ('index.html','gallery.html','technical.html'):
                text=(folder/name).read_text()
                self.assertEqual(text.count('aria-label="Primary"'),1,(model,name))
                self.assertEqual(text.count('aria-label="Breadcrumb"'),1,(model,name))
                self.assertEqual(text.count('aria-label="Detector views"'),1,(model,name))
                for label in ('Overview','Geometry','Saved fields &amp; signals','Model &amp; files'):
                    self.assertIn(label,text)
                self.assertNotIn('aria-label="Detector pages"',text)
            overview=(folder/'index.html').read_text()
            self.assertLess(overview.index('id="ssd-interactive-geometry"'),overview.index('id="saved-studies"'))
            self.assertIn(item['status'],unescape(overview))
        gegi=(self.site/'detectors/GeGI_3D/index.html').read_text()
        studies=re.search(r'<section id="saved-studies".*?</section>',gegi,re.S).group(0)
        for target in ('strip_explorer.html','supplement.html'):
            self.assertIn('href="'+target+'"',studies)
        for name in ('index.html','technical.html'):
            text=(self.site/'detectors/GeRC02'/name).read_text()
            self.assertIn('original 30-minute',text)
            self.assertIn('separate Li50min operating variant',text)

    def test_strip_reader_navigation_preserves_exact_scripts_and_scientific_body(self):
        original=(ROOT/'docs/detectors/GeGI_3D/strip_explorer.html').read_text(encoding='utf-8')
        repaired=D.strip_navigation(original)
        self.assertEqual(repaired,D.strip_navigation(repaired))
        self.assertEqual(repaired.count('aria-label="Primary"'),1)
        self.assertEqual(repaired.count('aria-label="Breadcrumb"'),1)
        self.assertIn('href="gallery.html">Return to GeGI saved fields &amp; signals',repaired)
        self.assertEqual(original[original.index('<main>'):],repaired[repaired.index('<main>'):])

    def test_saved_supplement_keeps_exact_scientific_elements_and_anchors(self):
        original=(ROOT/'docs/detectors/GeGI_3D/supplement.html').read_text(encoding='utf-8')
        repaired=D.archive_notebook(original)
        for pattern in (r'<img\b[^>]*>',r'<svg\b[^>]*>.*?</svg>',r'<table\b[^>]*>.*?</table>',r'<script\b[^>]*>.*?</script>'):
            self.assertEqual(re.findall(pattern,original,re.S),re.findall(pattern,repaired,re.S))
        original_ids=set(re.findall(r'\bid="([^"]+)"',original))
        self.assertTrue(original_ids<=set(re.findall(r'\bid="([^"]+)"',repaired)))
        self.assertEqual(repaired,D.archive_notebook(repaired))

    def test_four_direct_reports_keep_raw_bytes_and_one_primary_case_action(self):
        self.structure();items=[];raw={}
        for model in R.ALL_MODELS:
            base='examples/cs137-10k'+('-rings' if model in R.RING_MODELS else '')+'/'+model
            counts=dict(zero_deposit_primaries=9999,groups=1,accepted=1,native_failed_groups=0,readout_rejected=0)
            items.append(dict(model=model,label=model,note='Separate saved engineering fixture.',counts=counts,base=base))
            folder=self.site/base/'response';folder.mkdir(parents=True)
            report=('<!doctype html>\r\n<title>Original frozen report</title><h1>Saved response</h1>'
                    '<p>−0.0001, null, 10000 original IDs</p><details><summary>Event 1 / group 0</summary>'
                    '<svg viewBox="0 0 600 205"><polyline points="0,-1 2,0"/></svg></details>').encode('utf-8')
            (folder/'summary.html').write_bytes(report);raw[base+'/response/summary.html']=hashlib.sha256(report).hexdigest()
            (folder/'run.json').write_text(json.dumps({'counts':counts}))
            with zipfile.ZipFile(folder/'ledgers.zip','w') as bundle:
                for name in ('truth.jsonl','scalars.jsonl','endpoints.jsonl','histograms.json','traces.jsonl','run.json'):
                    bundle.writestr(name,b'{}\n')
            if model=='KMRC01_candidate':
                (folder/'original-native').mkdir();(folder/'original-native/summary.html').write_text('<p>Original readout: 0/231 accepted.</p>')
        with patch.object(R,'cases',return_value=items):R.apply(self.site)
        for case in items:
            html=(self.site/'results/cs137-10k'/case['model']/'charge-readout.html').read_text()
            self.assertIn('Saved response',html);self.assertIn('<svg viewBox="0 0 600 205">',html)
            self.assertNotIn('<iframe',html);self.assertNotIn('Waveforms and calibration record',html)
            self.assertIn('Original saved charge/readout report',html)
            self.assertEqual(html.count('href="../../../'+case['base']+'/response/ledgers.zip"'),1)
        hub=(self.site/'results/cs137-10k/index.html').read_text()
        cards=re.findall(r'<article class="card">.*?</article>',hub,re.S)
        self.assertEqual(len(cards),4);self.assertTrue(all(card.count('<a ')==1 for card in cards))
        self.assertNotIn('ledgers.zip',hub)
        for name,digest in raw.items():self.assertEqual(hashlib.sha256((self.site/name).read_bytes()).hexdigest(),digest)
        for case in items:
            detector=(self.site/'detectors'/case['model']/'index.html').read_text()
            self.assertLess(detector.index('saved-studies'),detector.index('current-ring-10k'))

    def test_english_guide_keeps_anchors_and_source_recipe_and_correct_build_check(self):
        guide=(ROOT/'tools/site_guide.html').read_text();parser=Elements();parser.feed(guide)
        anchors={attrs['id'] for _,attrs in parser.tags if 'id' in attrs}
        expected={'local-routes','browse','setup','local-control','saved-analysis','control-recovery','control-electronics','validation','choose','electronics','results','replay','native-readout','source-preparation','recovery','workspace','downloads','advanced-title'}
        self.assertTrue(expected<=anchors);self.assertIsNone(re.search('[\u3400-\u9fff]',guide))
        self.assertIn('Check environment</strong> reports file readiness',guide)
        self.assertIn('Check plan</strong> to verify its current build, source, runtime and settings',guide)
        self.assertIn('Run.cmd setup -BuildPortableSourceExporter',guide)
        self.assertIn('legacy exporter, not Control',guide)
        contents=re.search(r'<nav aria-label="Guide contents">.*?</nav>',guide,re.S).group(0)
        self.assertEqual(re.findall(r'href="([^"]+)"',contents),['#setup','#local-control','#saved-analysis','#control-recovery'])
        positions=[guide.index('<section id="'+name+'"') for name in ('setup','local-control','saved-analysis','control-recovery')]
        self.assertEqual(positions,sorted(positions))
        advanced=re.search(r'<section id="advanced-routes".*?</section>',guide,re.S).group(0)
        for name in ('choose','replay','source-preparation','recovery','workspace'):
            self.assertIn('<details id="'+name+'">',advanced)
        draft=(ROOT/'.local/product-delivery-v1/english-guide-draft/GUIDE.html')
        # The recipe is public source syntax; its private preparation copy is
        # optional. A public checkout still checks all required recipe commands.
        recipe=re.search(r'<pre><code>(\$m = Get-Content .*?)</code></pre>',guide,re.S).group(1)
        for value in ('cryostat-source.json','Get-FileHash','Invoke-WebRequest','[IO.File]::Move','throw "Downloaded bytes differ'):
            self.assertIn(value,unescape(recipe))
        if draft.exists():self.assertEqual(recipe,re.search(r'<pre><code>(\$m = Get-Content .*?)</code></pre>',draft.read_text(),re.S).group(1))

    def test_completed_gamma_renderer_fixture_remains_offline_without_private_inputs(self):
        import gamma_complete_showcase as F
        html=F.render({'kind':'portable_fixture','value':-0.0,'text':'</script>'}).decode()
        self.assertIn('SavedFocusPlots',html);self.assertIn('Full saved window',html)
        self.assertIn('\\u003c/script\\u003e',html);self.assertNotIn('src="http',html)

if __name__=='__main__':unittest.main()
