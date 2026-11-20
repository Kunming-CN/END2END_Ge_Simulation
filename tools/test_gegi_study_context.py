"""Presentation-only deep-page context; no transport, SSD or full site build."""
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

import gegi_assembly as assembly
import gegi_digital_display as D
import site_restructure as S


class GeGIStudyContextTests(unittest.TestCase):
    def temporary(self):
        context = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'.local')
        self.addCleanup(context.cleanup)
        return Path(context.name)

    def test_related_links_state_distinct_main_samples_and_same_prior_control_sample(self):
        shared = D._related_studies('shared-readout')
        self.assertIn('1,000,000 initial records',shared)
        self.assertIn('four acquisitions do not mean four 250 ms windows',shared)
        self.assertIn('324 measured two-strip triggers',shared)
        self.assertIn('four independent 250 ms windows (1 s total)',shared)
        prior = D._related_studies('plane-prior-study')
        self.assertIn('6.25 s total, with electronics reset between windows',prior)
        self.assertIn('same historical four-window sample',prior)
        controls = D._related_studies('shared-clock-controls')
        self.assertIn('another analysis of the same 324',controls)
        self.assertNotIn('gegi-shared-readout/index.html',shared)

    def test_long_page_contents_have_four_existing_targets_only(self):
        for key in ('position-calibration','plane-prior-study'):
            with self.subTest(key=key):
                anchors = [anchor for anchor,_ in D.STUDY_CONTENTS[key]]
                content = ''.join('<h2 id="'+anchor+'">Saved section</h2>' for anchor in anchors)
                contents = D._study_contents(key,content)
                self.assertEqual(re.findall(r'href="#([^"]+)"',contents),anchors)
                self.assertEqual(len(anchors),4)
                partial = D._study_contents(key,'<h2 id="'+anchors[0]+'">One saved section</h2>')
                self.assertEqual(re.findall(r'href="#([^"]+)"',partial),anchors[:1])
        self.assertEqual(D._study_contents('plane-prior-study','no saved sections'),'')

    def test_reading_sequence_explains_energy_position_pairing_then_imaging(self):
        self.assertIn('beyond the single-pixel energy',D._study_reading_path('short-exposure'))
        position = D._study_reading_path('position-calibration')
        self.assertIn('<strong>Before:</strong>',position)
        self.assertIn('gegi-short-exposure/index.html#gegi-event-energy',position)
        self.assertIn('gegi-pairing-benchmark/index.html',position)
        self.assertIn('several interaction candidates',position)
        pairing = D._study_reading_path('pairing-benchmark')
        self.assertIn('gegi-campaign/index.html',pairing)
        self.assertIn('different dataset',pairing)

    def test_page_writer_preserves_saved_content_and_resolves_original_asset_links(self):
        site = self.temporary()
        payload = '<h2 id="gegi-fast-gate">Saved neighbor evidence</h2><table><tr><td>1.2345678901234567</td></tr></table>'
        payload += '<p>Original event 683, pulse group 0</p><img src="gegi-digital/signals.png" alt="Saved signal">'
        D._write_study(site,'position-calibration',payload)
        page = site/D.GEGI_PAGE_PATHS['position-calibration']; first = page.read_bytes()
        html = first.decode()
        self.assertIn('<table><tr><td>1.2345678901234567</td></tr></table>',html)
        self.assertIn('Original event 683, pulse group 0',html)
        self.assertIn('src="../gegi-digital/signals.png"',html)
        self.assertIn('href="#gegi-fast-gate"',html)
        self.assertEqual(html.count('class="site-brand"'),1)
        D._write_study(site,'position-calibration',payload)
        self.assertEqual(page.read_bytes(),first)

    def test_four_acquisition_context_links_exact_setup_and_other_sample(self):
        site = self.temporary(); directory = site/'results/gegi-campaign'; directory.mkdir(parents=True)
        record = {'kind':'gegi_saved_publication_v3','artifacts':{},'deferred_historical_journey':{}}
        (directory/'publication.json').write_text(json.dumps(record))
        sections = ''.join('<section id="'+key+'"><p>Original '+key+' 837</p></section>'
                           for key in ('new-map','spectra','journey','saved-evidence'))
        (directory/'index.html').write_text('<!doctype html><html><head><title>Saved</title></head><body><h1>Saved</h1>'
            '<span id="campaign-reading-order"></span>'+sections+'</body></html>')
        with patch('gegi_saved_publication.validate_public'):
            S.refresh_gegi_reading_order(site)
            html = (directory/'index.html').read_text()
            first = (directory/'index.html').read_bytes()
            S.refresh_gegi_reading_order(site)
        self.assertEqual(first,(directory/'index.html').read_bytes())
        for href in ('../../detectors/GeGI_3D/index.html','../../assemblies/gegi/index.html',
                     '../../methods/index.html#gegi-acquisition-method','../gegi-pairing-benchmark/index.html',
                     '../gegi-plane-prior-study/index.html','../gegi-shared-readout/index.html'):
            self.assertIn('href="'+href+'"',html)
        for population in ('1,000,000 initial records','434 signal-selected groups','837 candidate orders','708 groups',
                           '324 measured two-strip triggers','6.25 s with electronics reset'):
            self.assertIn(population,html)
        for key in ('new-map','spectra','journey','saved-evidence'):
            self.assertEqual(html.count('Original '+key+' 837'),1)

    def test_assembly_template_names_actual_target_and_retains_embedded_records(self):
        scene = {'vertices_global_mm':[[1.2345678901234567,0,0]]}
        events = {'records':[{'event_id':683,'group_id':0}]}
        html = assembly.render_page(scene,events,{'kind':'synthetic presentation test'},{'geometry':{'parts':[]}})
        self.assertNotIn('>GeGI saved results<',html)
        self.assertNotIn('>full GeGI study<',html)
        self.assertIn('Four independent GeGI acquisitions: signals and conditional imaging',html)
        self.assertIn('href="../../results/gegi-campaign/index.html#journey"',html)
        self.assertIn('href="../../results/gegi-shared-readout/index.html"',html)
        self.assertIn('different historical library replay',html)
        for ident,expected in (('scene-data',scene),('event-data',events)):
            payload = re.search(r'id="'+ident+'">(.*?)</script>',html,re.S)[1]
            self.assertEqual(json.loads(payload),expected)


if __name__ == '__main__': unittest.main()
