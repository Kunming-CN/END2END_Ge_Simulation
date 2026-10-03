"""Small presentation fixtures; no science, public build, server or export."""
import hashlib
from html import unescape
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import tempfile
import unittest
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

    def test_all17_cards_use_reviewed_types_original_fullsize_lazy_contained_images(self):
        self.structure();html=(self.site/'detectors/index.html').read_text();parser=Elements();parser.feed(html)
        images=[attrs for tag,attrs in parser.tags if tag=='img']
        self.assertEqual(len(images),17);self.assertEqual(set(D.TYPE_LABELS),{i['id'] for i in self.catalog['detectors']})
        cards=re.findall(r'<article class="card">.*?</article>',html,re.S);self.assertEqual(len(cards),17)
        for item,card in zip(sorted(self.catalog['detectors'],key=lambda i:(i['id'] not in D.control_capabilities(),self.catalog['detectors'].index(i))),cards):
            model=item['id'];poster=f'{model}/runs/{D.RUN}/01_geometry.png'
            self.assertIn('href="'+poster+'"',card);self.assertIn('src="'+poster+'"',card)
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
        self.assertEqual(D.control_capabilities(),{'AK02','SAP22','GeRC02','KMRC01_candidate'})
        self.assertIn('Control supports GeRC02',(self.site/'detectors/GeRC02/index.html').read_text())
        self.assertIn('not integrated',(self.site/'detectors/GeGI_3D/index.html').read_text())

    def test_three_actions_ring_context_and_no_stale_pending_claim(self):
        self.structure();home=(self.site/'index.html').read_text();results=(self.site/'results/index.html').read_text()
        self.assertEqual(re.findall(r'<article class="card"><h2>(.*?)</h2>',home),['Browse','Setup','Use'])
        self.assertNotIn('pending saved results',results)
        scenario=(self.site/'scenarios/lbnl-cs137/index.html').read_text()
        self.assertIn('Control offers four separate detector configurations',scenario)
        self.assertIn('Legacy Run.cmd',scenario);self.assertIn('GeRC02 Li50min',scenario)

    def test_notebook_invitation_corrected_without_saved_output_or_anchor_loss(self):
        corrected=D.archive_notebook(self.notebook)
        self.assertNotIn('Run all cells in order',corrected);self.assertIn('Recorded notebook kernel',corrected)
        self.assertIn('private <code>README.md</code>',corrected);self.assertIn('not included in this archive',corrected)
        for retained in ('5,068,800 nodes','id="saved-output"','<img src="saved.png">'):self.assertIn(retained,corrected)
        self.assertEqual(D.archive_notebook(corrected),corrected)
        self.assertIn('Run all cells in order',self.notebook)

    def test_four_wrappers_keep_raw_report_bytes_and_one_distinct_zip_per_case(self):
        self.structure();items=[];raw={}
        for model in R.ALL_MODELS:
            base='examples/cs137-10k'+('-rings' if model in R.RING_MODELS else '')+'/'+model
            counts=dict(zero_deposit_primaries=9999,groups=1,accepted=1,native_failed_groups=0,readout_rejected=0)
            items.append(dict(model=model,label=model,note='Separate saved engineering fixture.',counts=counts,base=base))
            folder=self.site/base/'response';folder.mkdir(parents=True)
            report='<!doctype html>\r\n<title>Original frozen report</title><p>−0.0001, null, 10000 original IDs</p>'.encode('utf-8')
            (folder/'summary.html').write_bytes(report);raw[base+'/response/summary.html']=hashlib.sha256(report).hexdigest()
        with patch.object(R,'cases',return_value=items):R.apply(self.site)
        for case in items:
            html=(self.site/'results/cs137-10k'/case['model']/'charge-readout.html').read_text()
            self.assertIn('← Four-detector 10K results',html);self.assertIn('<iframe',html)
            self.assertIn('src="../../../'+case['base']+'/response/summary.html"',html)
            self.assertEqual(html.count('href="../../../'+case['base']+'/response/ledgers.zip"'),1)
        hub=(self.site/'results/cs137-10k/index.html').read_text()
        self.assertEqual(hub.count('Download complete ledgers (ZIP)'),4)
        self.assertEqual(len(set(re.findall(r'href="([^"]+ledgers.zip)"',hub))),4)
        for name,digest in raw.items():self.assertEqual(hashlib.sha256((self.site/name).read_bytes()).hexdigest(),digest)
        front=(self.site/'index.html').read_text();self.assertLess(front.index('current-ring-10k'),front.index('<h2>Browse</h2>'))

    def test_english_guide_keeps_anchors_and_source_recipe_and_correct_build_check(self):
        guide=(ROOT/'tools/site_guide.html').read_text();parser=Elements();parser.feed(guide)
        anchors={attrs['id'] for _,attrs in parser.tags if 'id' in attrs}
        expected={'local-routes','browse','setup','local-control','control-electronics','validation','choose','electronics','results','replay','native-readout','source-preparation','recovery','workspace','downloads','advanced-title'}
        self.assertTrue(expected<=anchors);self.assertIsNone(re.search('[\u3400-\u9fff]',guide))
        self.assertIn('Check environment</strong> reports file readiness',guide)
        self.assertIn('Check plan</strong> to verify its current build, source, runtime and settings',guide)
        self.assertIn('Run.cmd setup -BuildPortableSourceExporter',guide)
        self.assertIn('legacy exporter, not Control',guide)
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
