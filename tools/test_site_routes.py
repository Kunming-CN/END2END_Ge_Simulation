"""Bounded task/dataset navigation and saved-gallery preservation checks."""
import json
import re
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

import site_detector_pages as D
import site_restructure as S
from site_fragments import ids

ROOT=Path(__file__).resolve().parents[1]


class Links(HTMLParser):
    def __init__(self):
        super().__init__();self.links=[]
    def handle_starttag(self,tag,attrs):
        if tag=='a':self.links.append(dict(attrs)['href'])


def hrefs(text):
    reader=Links();reader.feed(text);return reader.links


class RoutesTests(unittest.TestCase):
    def test_primary_tasks_do_not_select_a_dataset(self):
        for up in ('','../','../../','../../../'):
            self.assertEqual(hrefs(S.navigation(up)),[up+'guide.html#local-control',
                up+'results/index.html',up+'detectors/index.html',up+'guide.html#saved-analysis'])
            self.assertNotIn('Waveforms',S.navigation(up))
            self.assertNotIn('Spectra',S.navigation(up))

    def test_dataset_views_never_substitute_another_saved_study(self):
        allowed={
            'teaching':{'spectra/pipeline.html','learn/index.html'},
            'gamma':{'examples/gamma-native/gamma.html'},
            'tenk':{'results/cs137-10k/index.html','spectra/cs137-10k.html','viewers/events.html'},
            'million':{'results/cs137-1m/index.html','spectra/million-truth.html','spectra/million-response.html'},
        }
        for dataset,views in allowed.items():
            self.assertEqual(set(hrefs(S.dataset_navigation(dataset))),views|{'results/index.html#'+dataset})
            self.assertEqual(set(hrefs(S.dataset_navigation(dataset,'../../'))),
                             {'../../'+path for path in views|{'results/index.html#'+dataset}})
        with self.assertRaisesRegex(ValueError,'Unknown saved dataset'):
            S.dataset_navigation('arbitrary')

    def test_catalog_has_four_explicit_dataset_entries(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'.local') as tmp:
            site=Path(tmp)
            (site/'index.html').write_text('fixture',encoding='utf8')
            (site/'models').mkdir()
            catalog={'detectors':[{'id':m,'contacts':[{},{}]} for m in ('AK02','SAP22')]}
            (site/'models/catalog.json').write_text(json.dumps(catalog),encoding='utf8')
            for rel in ('examples/data.json','examples/gamma-native/gamma.html',
                        'examples/cs137-10k/comparison.html','examples/cs137-10k-rings/manifest.json',
                        'examples/cs137-1m/summary.json'):
                p=site/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('{}',encoding='utf8')
            p=site/'examples/cs137-1m-response/summary.json';p.parent.mkdir(parents=True)
            p.write_text(json.dumps({'models':{m:{'positive_ge_decays':1,'response':{'accepted':1}}
                                                for m in ('AK02','SAP22')}}),encoding='utf8')
            with patch('gamma_publication.validate_bundle'),patch('gamma_publication.completed',return_value=True),\
                 patch('spectrum_display.homepage_preview',return_value=None),\
                 patch('ssd_geometry_publication.refresh_viewers'),patch.object(S,'apply_detector_pages'):
                S.apply(site)
            text=(site/'results/index.html').read_text(encoding='utf8')
            panels={m.group(1):m.group(2) for m in re.finditer(
                r'<section id="(teaching|gamma|tenk|million)"[^>]*>(.*?)</section>',text,re.S)}
            self.assertEqual(set(panels),{'teaching','gamma','tenk','million'})
            self.assertIn('bare geometry',panels['teaching'])
            self.assertIn('Different geometry and event IDs',panels['gamma'])
            self.assertIn('four separate cases',panels['tenk'])
            self.assertIn('one million initial decays per detector',panels['million'])
            self.assertNotIn('viewers/events.html',panels['million'])
            self.assertNotIn('viewers/events.html',panels['gamma'])
            self.assertNotIn('spectra/cs137-10k.html',panels['teaching'])

    def test_all_saved_gallery_media_settings_and_anchors_survive(self):
        for gallery in sorted((ROOT/'docs/detectors').glob('*/gallery.html')):
            original=gallery.read_text(encoding='utf8')
            cleaned=D.gallery_navigation(original,gallery.parent.name)
            media=lambda t:re.findall(r'<(?:img|video|source)\b[^>]*>',t)
            self.assertEqual(media(original),media(cleaned),gallery.parent.name)
            self.assertEqual(re.findall(r'<script\b[^>]*>.*?</script>',original,re.S),
                             re.findall(r'<script\b[^>]*>.*?</script>',cleaned,re.S))
            self.assertTrue(set(ids(original))<=set(ids(cleaned)),gallery.parent.name)
            settings=re.findall(r'<p>Crystal bounds:.*?</p>',original,re.S)
            self.assertTrue(all(value in cleaned for value in settings),gallery.parent.name)
            self.assertNotIn('<h2>Start here</h2>',cleaned)
            self.assertEqual(cleaned,D.gallery_navigation(cleaned,gallery.parent.name))

    def test_gegi_preview_captions_keep_original_images_and_exact_channels(self):
        gallery=ROOT/'docs/detectors/GeGI_3D/gallery.html'
        original=gallery.read_text(encoding='utf8')
        captioned=D.gegi_channel_captions(original,ROOT/'docs')
        self.assertEqual(re.findall(r'<img\b[^>]*>',original),re.findall(r'<img\b[^>]*>',captioned))
        events=re.findall(r'src="runs/'+D.RUN+r'/events/([A-Za-z0-9_-]+)/preview\.png"',original)
        self.assertEqual(len(events),20)
        self.assertEqual(captioned.count('class="saved-channel-caption"'),len(events))
        self.assertEqual(captioned,D.gegi_channel_captions(captioned,ROOT/'docs'))
        self.assertTrue(all((ROOT/'docs/detectors/GeGI_3D/runs'/D.RUN/'events'/event/'channels.csv').is_file()
                            for event in events))

    def test_gegi_return_repair_preserves_saved_payload(self):
        original=(ROOT/'docs/detectors/GeGI_3D/strip_explorer.html').read_text(encoding='utf8')
        repaired=D.strip_navigation(original)
        self.assertIn('href="../index.html">All detectors',repaired)
        self.assertIn('href="index.html">GeGI overview',repaired)
        self.assertEqual(re.findall(r'<script\b[^>]*>.*?</script>',original,re.S),
                         re.findall(r'<script\b[^>]*>.*?</script>',repaired,re.S))
        self.assertEqual(repaired,D.strip_navigation(repaired))


if __name__=='__main__':unittest.main(verbosity=2)
