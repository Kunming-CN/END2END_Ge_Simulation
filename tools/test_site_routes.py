"""Bounded task/dataset navigation and saved-gallery preservation checks."""
import json
import re
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

import site_detector_pages as DetectorPages
import site_restructure as Structure
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
            self.assertEqual(hrefs(Structure.navigation(up)),[up+'results/index.html',
                up+'detectors/index.html',up+'guide.html',up+'methods/index.html'])
            self.assertNotIn('Waveforms',Structure.navigation(up))
            self.assertNotIn('Spectra',Structure.navigation(up))

    def test_dataset_views_never_substitute_another_saved_study(self):
        allowed={
            'teaching':{'spectra/pipeline.html'},
            'gamma':{'examples/gamma-native/gamma.html'},
            'tenk':{'results/cs137-10k/index.html','spectra/cs137-10k.html','viewers/events.html'},
            'million':{'results/cs137-1m/index.html','spectra/million-truth.html','spectra/million-response.html',
                       'results/cs137-1m/index.html#data-files'},
        }
        for dataset,views in allowed.items():
            self.assertEqual(set(hrefs(Structure.dataset_navigation(dataset,current_path='index.html'))),views)
            self.assertEqual(set(hrefs(Structure.dataset_navigation(dataset,current_path='detectors/AK02/index.html'))),
                             {'../../'+path for path in views})
        focused=hrefs(Structure.dataset_navigation('tenk',current_path='index.html',model='GeRC02'))
        self.assertIn('viewers/events.html?model=GeRC02&view=positive',focused)
        self.assertIn('spectra/cs137-10k.html#tenk-GeRC02',focused)
        with self.assertRaisesRegex(ValueError,'Unknown saved dataset'):
            Structure.dataset_navigation('arbitrary')

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
                 patch('ssd_geometry_publication.refresh_viewers'),patch.object(Structure,'apply_detector_pages'):
                Structure.apply(site)
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
            cleaned=DetectorPages.gallery_navigation(original,gallery.parent.name)
            media=lambda t:re.findall(r'<(?:img|video|source)\b[^>]*>',t)
            self.assertEqual(media(original),media(cleaned),gallery.parent.name)
            self.assertEqual(re.findall(r'<script\b[^>]*>.*?</script>',original,re.S),
                             re.findall(r'<script\b[^>]*>.*?</script>',cleaned,re.S))
            self.assertTrue(set(ids(original))<=set(ids(cleaned)),gallery.parent.name)
            settings=re.findall(r'<p>Crystal bounds:.*?</p>',original,re.S)
            self.assertTrue(all(value in cleaned for value in settings),gallery.parent.name)
            self.assertNotIn('<h2>Start here</h2>',cleaned)
            self.assertEqual(cleaned,DetectorPages.gallery_navigation(cleaned,gallery.parent.name))

    def test_gegi_preview_captions_keep_original_images_and_exact_channels(self):
        gallery=ROOT/'docs/detectors/GeGI_3D/gallery.html'
        original=gallery.read_text(encoding='utf8')
        captioned=DetectorPages.gegi_channel_captions(original,ROOT/'docs')
        self.assertEqual(re.findall(r'<img\b[^>]*>',original),re.findall(r'<img\b[^>]*>',captioned))
        events=re.findall(r'src="runs/'+DetectorPages.RUN+r'/events/([A-Za-z0-9_-]+)/preview\.png"',original)
        self.assertEqual(len(events),20)
        self.assertEqual(captioned.count('class="saved-channel-caption"'),len(events))
        self.assertEqual(captioned,DetectorPages.gegi_channel_captions(captioned,ROOT/'docs'))
        self.assertTrue(all((ROOT/'docs/detectors/GeGI_3D/runs'/DetectorPages.RUN/'events'/event/'channels.csv').is_file()
                            for event in events))

    def test_gegi_return_repair_preserves_saved_payload(self):
        original=(ROOT/'docs/detectors/GeGI_3D/strip_explorer.html').read_text(encoding='utf8')
        repaired=DetectorPages.strip_navigation(original)
        self.assertIn('href="../index.html">Detectors',repaired)
        self.assertIn('href="gallery.html">Return to GeGI saved fields &amp; signals',repaired)
        self.assertEqual(re.findall(r'<script\b[^>]*>.*?</script>',original,re.S),
                         re.findall(r'<script\b[^>]*>.*?</script>',repaired,re.S))
        self.assertEqual(repaired,DetectorPages.strip_navigation(repaired))



import hashlib
import audit_site_navigation as A
import check_site as C
import site_discovery as D
import site_routes as R

class RouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / '.local')
        self.addCleanup(self.temp.cleanup)
        self.site = Path(self.temp.name)

    def write(self, path, text):
        target = self.site / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8', newline='\n')

    def test_all_current_pages_have_independent_registry_ownership(self):
        records = R.registry(Path(__file__).resolve().parents[1] / 'docs')
        self.assertEqual(len(records), 105)
        self.assertEqual(sum(row['role'] == 'archive' for row in records.values()), 12)
        self.assertEqual(sum(row['role'] == 'alias' for row in records.values()), 2)
        for path, record in records.items():
            with self.subTest(path=path):
                seen = set()
                while record['parent_id']:
                    self.assertNotIn(record['path'], seen)
                    seen.add(record['path'])
                    record = records[record['parent_id']]
        km = records['examples/cs137-10k-rings/KMRC01_candidate/response/original-native/summary.html']
        self.assertEqual(km['role'], 'archive')
        self.assertEqual(km['parent_id'], R.case_result_path('KMRC01_candidate'))

    def test_relative_query_fragment_and_absolute_project_identity(self):
        expected = dict(path='viewers/events.html', query='model=GeRC02&view=positive',
                        fragment='selected', project_absolute=False)
        self.assertEqual(C.resolve_reference('spectra/cs137-10k.html',
                          '../viewers/events.html?model=GeRC02&view=positive#selected'), expected)
        expected['project_absolute'] = True
        for prefix in (D.SITE_URL, '//kunming-cn.github.io/END2END_Ge_Simulation/'):
            self.assertEqual(C.resolve_reference('index.html', prefix + 'viewers/events.html?model=GeRC02&view=positive#selected'), expected)
        self.assertEqual(C.resolve_reference('guide.html', '#getting-started')['path'], 'guide.html')
        self.assertEqual(C.resolve_reference('guide.html', D.SITE_URL)['path'], 'index.html')
        self.assertEqual(C.resolve_reference('guide.html', D.SITE_URL.rstrip('/'))['path'], 'index.html')

    def test_duplicate_queries_are_retained_for_runtime_rejection(self):
        url = R.event_view_path('GeRC02') + '&model=SAP22#end'
        resolved = C.resolve_reference('index.html', url)
        self.assertEqual(resolved['query'], 'model=GeRC02&view=positive&model=SAP22')
        self.assertEqual(resolved['fragment'], 'end')
        self.assertEqual(R.relative_url(url, 'spectra/cs137-10k.html'), '../' + url)

    def test_project_absolute_wrong_case_missing_and_escape_are_not_ignored(self):
        self.write('index.html', '<a href="' + D.SITE_URL + 'Missing.html">Missing</a>')
        with self.assertRaisesRegex(ValueError, 'wrong-case'):
            C.validate(self.site, require_manifest=False)
        for url in ('../secret.html', D.SITE_URL + '../secret.html', D.SITE_URL + '%2E%2E/secret.html', '/wrong-root.csv', 'file:///private.csv'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                C.resolve_reference('index.html', url)
        self.assertIsNone(C.resolve_reference('index.html', 'https://kunming-cn.github.io/another-project/'))
        self.assertIsNone(C.resolve_reference('index.html', 'https://foreign.invalid/END2END_Ge_Simulation/'))

    def test_resources_downloads_metadata_and_navigation_have_separate_census(self):
        self.write('index.html', ('<html><head><link rel="canonical" href="' + D.SITE_URL + '"></head><body id="start">'
                                 '<a href="guide.html?model=GeRC02#section">Guide</a>'
                                 '<a href="#start">Start</a><a href="./">Home</a>'
                                 '<a href="data.csv" download>CSV</a><img src="plot.png">'
                                 '<video poster="plot.png"></video></body></html>'))
        self.write('guide.html', '<p id="section">A section</p>')
        self.write('data.csv', 'x\n1\n')
        (self.site / 'plot.png').write_bytes(b'image fixture')
        report = C.validate(self.site, require_manifest=False)
        self.assertEqual(report['local_links_checked'], 5)
        self.assertEqual(report['resource_references_checked'], 7)
        self.assertEqual(report['page_navigation_checked'], 3)
        self.assertEqual(report['downloads_checked'], 1)
        self.assertEqual(report['media_references_checked'], 2)
        self.assertEqual(report['metadata_references_checked'], 1)
        self.assertEqual(report['fragments_checked'], 2)
        report = A.audit(self.site)
        self.assertEqual(report['failures'], [])
        self.assertEqual(report['reference_counts']['internal_fragment'], 1)
        homepage = next(row for row in report['pages'] if row['path'] == 'index.html')
        row = next(row for row in homepage['references'] if row['url'].startswith('guide.html'))
        self.assertEqual(row['resolved_url'], 'guide.html?model=GeRC02#section')

    def test_missing_encoded_fragment_is_refused_and_named_anchor_accepted(self):
        self.write('index.html', '<a href="guide.html#saved%20study">Saved study</a>')
        self.write('guide.html', '<a name="saved study"></a>')
        C.validate(self.site, require_manifest=False)
        self.write('guide.html', '<p id="other">Other</p>')
        with self.assertRaisesRegex(ValueError, 'Broken fragment'):
            C.validate(self.site, require_manifest=False)
        self.assertFalse(A.audit(self.site)['failures'][0]['fragment_exists'])

    def test_disconnected_archive_is_inventoried_and_js_is_not_claimed_tested(self):
        self.write('index.html', '<body><a href="guide.html#run">Run</a></body>')
        self.write('guide.html', '<a id="run" href="index.html">Home</a><a id="dynamic" data-context-link="events">Events</a><script>link.href = target; history.replaceState(null,"",url);fetch("data.json");</script>')
        self.write('results/index.html', '<p>Results</p>')
        self.write('results/cs137-10k/index.html', '<p>10K</p>')
        self.write(R.case_result_path('KMRC01_candidate'), '<p>Saved result</p>')
        path = 'examples/cs137-10k-rings/KMRC01_candidate/response/original-native/summary.html'
        self.write(path, '<p>Original 0/231 history</p>')
        report = A.audit(self.site)
        self.assertEqual(report['html_pages'], 6)
        self.assertEqual(report['failures'], [])
        self.assertEqual(report['role_counts']['archive'], 1)
        dynamic = next(row for row in report['pages'] if row['path'] == 'guide.html')['dynamic']
        self.assertEqual(dynamic['status'], 'not_executed')
        self.assertEqual(dynamic['script_blocks'], 1)
        self.assertEqual(len(dynamic['marked_elements']), 1)
        self.assertEqual(dynamic['source_navigation_operations']['.href ='], 1)
        self.assertEqual(dynamic['literal_fetch_resources'][0]['url'], 'data.json')
        self.assertEqual(dynamic['literal_fetch_resources'][0]['status'], 'not_executed')

    def test_legitimate_crosslinks_do_not_create_an_ownership_cycle(self):
        self.write('index.html', '<a href="guide.html">Run</a>')
        self.write('guide.html', '<a href="index.html">Home</a>')
        self.assertEqual(A.audit(self.site)['failures'], [])
        original = R.page_record
        def cycle(path):
            record = original(path)
            if path == 'index.html':
                record['parent_id'] = 'guide.html'
            return record
        with patch.object(R, 'page_record', side_effect=cycle):
            report = A.audit(self.site)
        self.assertTrue(any('parent_cycle' in row for row in report['failures']))

    def test_thirty_indexable_content_routes_exclude_aliases_and_archives(self):
        catalog = json.loads((Path(__file__).resolve().parents[1] / 'docs/models/catalog.json').read_text(encoding='utf-8'))
        selected = list(D.LANDINGS) + [R.case_result_path(model) for model in R.CASE_MODELS]
        selected += [f'detectors/{row["id"]}/index.html' for row in catalog['detectors']]
        for path in selected:
            self.write(path, '<html><head><title>Saved content</title></head><body>Saved</body></html>')
        self.write('models/catalog.json', json.dumps(catalog))
        for path in ('viewers/events.html', *R.ALIASES, 'examples/cs137-1m/report.html', 'spectra/cs137-10k.html'):
            self.write(path, '<html>Protected content</html>')
        before = {path: (self.site / path).read_bytes() for path in ('viewers/events.html', *R.ALIASES, 'examples/cs137-1m/report.html', 'spectra/cs137-10k.html')}
        D.assemble(self.site)
        self.assertEqual(len(D.landing_descriptions(self.site)), 30)
        self.assertEqual(set(D.landing_descriptions(self.site)), set(selected))
        for path, content in before.items():
            self.assertEqual((self.site / path).read_bytes(), content)
            self.assertNotIn(D.canonical(path), (self.site / D.SITEMAP).read_text(encoding='utf-8'))
        D.validate(self.site)

    def test_only_exact_predecessor_metadata_and_sitemap_may_pass_before_rebuild(self):
        self.write('index.html', '<html><head><title>Home</title></head><body>Saved</body></html>')
        for model in R.CASE_MODELS:
            self.write(R.case_result_path(model), '<html><head><title>Saved case</title></head><body>Saved</body></html>')
        # Small controlled fixture mirrors the exact deployed old discovery:
        # case wrappers existed but were not indexed or assigned head metadata.
        with patch.object(R, 'CASE_MODELS', ()):
            D.assemble(self.site)
        identity = D.snapshot_identity(self.site)
        old_report = dict(schema_version=1, build_id=identity)
        (self.site / C.MANIFEST).write_text(json.dumps(old_report), encoding='utf-8')
        with patch.object(D, 'NAVIGATION_PREDECESSOR', identity):
            D.validate(self.site)
            self.write(R.case_result_path('AK02'), '<html><head><title>Changed case</title></head><body>Changed</body></html>')
            # The claimed predecessor build ID does not grant admission after
            # bytes change, even before a new manifest is written.
            with self.assertRaisesRegex(ValueError, 'sitemap differs'):
                D.validate(self.site)
            D.assemble(self.site)
            D.validate(self.site)

    def test_standalone_identity_uses_manifest_sort_order_on_windows(self):
        self.write('index.html', '<p>Home</p>')
        self.write('Zoo.html', '<p>Uppercase filename</p>')
        self.assertEqual(D.snapshot_identity(self.site), C.validate(self.site, require_manifest=False)['build_id'])

    def test_only_exact_old_manifest_counter_schema_is_accepted(self):
        self.write('index.html', '<a href="guide.html">Run</a>')
        self.write('guide.html', '<p>Run</p>')
        report = C.validate(self.site, require_manifest=False)
        old = {key: value for key, value in report.items()
               if key in {'schema_version', 'build_id', 'file_count', 'total_bytes', 'html_pages', 'local_links_checked', 'files'}}
        raw = json.dumps(old).encode()
        (self.site / C.MANIFEST).write_bytes(raw)
        with patch.object(D, 'NAVIGATION_PREDECESSOR', report['build_id']), patch.object(C, 'NAVIGATION_PREDECESSOR_MANIFEST_SHA256', hashlib.sha256(raw).hexdigest()):
            self.assertEqual(C.validate(self.site), report)
            (self.site / C.MANIFEST).write_bytes(raw + b'\n')
            with self.assertRaisesRegex(ValueError, 'differs from its manifest'):
                C.validate(self.site)
            self.write('guide.html', '<p>Changed</p>')
            changed = C.validate(self.site, require_manifest=False)
            changed_old = {key: value for key, value in changed.items() if key in old}
            (self.site / C.MANIFEST).write_text(json.dumps(changed_old), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'differs from its manifest'):
                C.validate(self.site)


if __name__ == '__main__':
    unittest.main(verbosity=2)
