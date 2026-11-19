"""Test full generated navigation using a disposable structural site fixture.
Hash-bound exhibits and rendered sources use saved bytes. Unbound media use existence markers.
This does not replace the real site's manifest/media validation or browser tests.
"""
import json
import re
import shutil
import hashlib
import tempfile
import unittest
from collections import Counter
from html import escape
from unittest.mock import patch
from pathlib import Path
from urllib.parse import urlsplit, unquote
import site_restructure as S
import ring_site as R
import result_web_delivery as delivery
import site_canonical_views as Canonical
import site_routes as Routes
from gegi_digital_display import GEGI_PAGE_PATHS, GEGI_SECTION_TARGETS, render as render_gegi
from site_fragments import ids
from site_routes import PRIMARY
from check_site import Links, local_target
ROOT=Path(__file__).resolve().parents[1]

class HierarchyTests(unittest.TestCase):
    def test_all_model_repeat_generation_and_fragments(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'.local') as tmp:
            fixture=Path(tmp)/'site'
            published=ROOT/'docs'
            bound_prefixes=('results/gegi-campaign/','results/gegi-digital/','lithium/',
                            delivery.PREFIX+'/', 'results/cs137-10k/')
            def copy(source,dest):
                path=Path(source)
                relative=path.relative_to(published).as_posix()
                if (relative.startswith(bound_prefixes) or
                        path.suffix in ('.html','.json','.md','.csv','.js') or path.name=='ledgers.zip'):
                    shutil.copyfile(source,dest)
                else:
                    Path(dest).write_bytes(b'fixture existence marker')
                return dest
            shutil.copytree(published,fixture,copy_function=copy)
            Canonical.prepare(fixture)
            # Restore the two exact archives used by the saved-report generator.
            # The normal archive binding still applies in this owned test stage.
            with patch.object(delivery,'_stage',side_effect=delivery.directory):
                delivery.materialize_for_build(fixture)
            original_ids={p.relative_to(fixture).as_posix():set(ids(p.read_text(encoding='utf-8')))
                          for p in fixture.rglob('*.html')}
            original_report=(fixture/'results/index.html').read_text(encoding='utf-8')
            legacy_panel=re.search(r'<section id="gegi"[^>]*>.*?</section>',original_report,re.S)
            if legacy_panel:
                original_exhibits={'results/index.html':legacy_panel[0]}
            else:
                original_exhibits={path:(fixture/path).read_text(encoding='utf-8')
                                   for path in GEGI_PAGE_PATHS.values()}
            original_tables=[table for html in original_exhibits.values()
                             for table in re.findall(r'<table\b.*?</table>',html,re.S)]
            def scientific_assets(pages):
                assets=set()
                for relative,html in pages.items():
                    links=Links();links.feed(html)
                    for url in links.urls:
                        target=local_target(relative,url)
                        if target and target.startswith('results/gegi-digital/'):
                            assets.add(target)
                return assets
            original_assets=scientific_assets(original_exhibits)
            gamma=fixture/'examples/gamma-native'
            gamma_bytes={p.name:p.read_bytes() for p in gamma.glob('*') if p.is_file()}
            formal=fixture/'results/gegi-campaign/publication.json'
            formal_before=json.loads(formal.read_bytes())
            journey=fixture/'results/gegi-campaign/gegi_signal_journey.js'
            journey_before=journey.read_bytes()
            journey_html=(formal.parent/'index.html').read_text(encoding='utf-8')
            journey_payload=re.search(r'<script type="application/json" id="gegi-journey-data">(.*?)</script>',journey_html,re.S)
            saved_hashes={p.relative_to(fixture).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in fixture.rglob('*') if p.is_file() and p.suffix!='.html'}
            def maintain():
                Canonical.prepare(fixture)
                S.apply(fixture)
                render_gegi(fixture)
                R.apply(fixture)
                Routes.legacy_results_links(fixture)
                Canonical.apply(fixture)
            maintain()
            first={p.relative_to(fixture).as_posix():p.read_bytes() for p in fixture.rglob('*.html')}
            maintain()
            second={p.relative_to(fixture).as_posix():p.read_bytes() for p in fixture.rglob('*.html')}
            self.assertEqual(first,second,'Repeated navigation generation changed HTML')
            self.assertEqual(gamma_bytes,{p.name:p.read_bytes() for p in gamma.glob('*') if p.is_file()})
            formal_after=json.loads(formal.read_bytes())
            if journey_payload:
                payload=journey_payload[1].encode('utf-8')
                expected=journey_before+(b'\n/* Deferred exact saved historical payload. */\n'
                    b'globalThis.mountGeGIHistoricalJourney=function(host){return GeGISignalJourney.mount(host,'
                    +payload+b',{scope:"student"});};\n')
                self.assertEqual(journey.read_bytes(),expected,'Saved historical signal payload changed')
                self.assertEqual(formal_after['deferred_historical_journey']['payload_sha256'],hashlib.sha256(payload).hexdigest())
            else:
                self.assertEqual(journey.read_bytes(),journey_before)
            for stamp in (formal_before,formal_after):
                stamp.pop('display_source_sha256',None)
                stamp['artifacts'].pop('index.html')
                stamp['artifacts'].pop('gegi_signal_journey.js')
                stamp.pop('deferred_historical_journey',None)
            self.assertEqual(formal_before,formal_after,'Formal campaign data provenance changed')
            current_hashes={p.relative_to(fixture).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in fixture.rglob('*') if p.is_file() and p.suffix!='.html'}
            presentation_receipts={'methods/native-li-display.json','methods/lithium-display.json',
                                   'results/gegi-campaign/publication.json',
                                   'results/gegi-campaign/gegi_signal_journey.js','canonical-views.json'}
            self.assertEqual({name:h for name,h in saved_hashes.items() if name not in presentation_receipts},
                             {name:h for name,h in current_hashes.items() if name not in presentation_receipts})
            added=set(current_hashes)-set(saved_hashes)
            self.assertTrue(added <= {'methods/native-li-display.json','methods/lithium-display.json','canonical-views.json'},added)
            from saved_archive_display import validate as validate_archive_display
            with Canonical.validation_view(fixture) as legacy:
                validate_archive_display(legacy)
            missing_fragments=[]
            for relative,anchors in original_ids.items():
                target=Routes.CANONICAL_VIEWS.get(relative,relative)
                current=set(ids((fixture/target).read_text(encoding='utf-8')))
                for anchor in anchors:
                    # The obsolete gallery CSS block is replaced by the shared
                    # frame; it was neither a content nor a scientific anchor.
                    if anchor=='saved-gallery-navigation-style':
                        continue
                    destination=GEGI_SECTION_TARGETS.get(anchor) if relative=='results/index.html' else None
                    if destination:
                        page,fragment=destination.split('#',1)
                        if fragment not in ids((fixture/page).read_text(encoding='utf-8')):
                            missing_fragments.append(relative+'#'+anchor+' -> '+destination)
                    else:
                        if anchor not in current:
                            missing_fragments.append(relative+'#'+anchor+' -> '+target)
            with self.subTest(check='old-content-fragments'):
                self.assertFalse(missing_fragments,'Old fragments removed: '+', '.join(sorted(missing_fragments)))
            exhibits={path:(fixture/path).read_text(encoding='utf-8') for path in GEGI_PAGE_PATHS.values()}
            combined='\n'.join(exhibits.values())
            self.assertTrue(original_tables,'Expected saved GeGI evidence tables')
            current_tables=re.findall(r'<table\b.*?</table>',combined,re.S)
            stamps=lambda tables:Counter(hashlib.sha256(table.encode('utf-8')).hexdigest() for table in tables)
            self.assertEqual(stamps(original_tables),stamps(current_tables),
                             'Original scientific tables were omitted, changed or duplicated')
            self.assertTrue(original_assets<=scientific_assets(exhibits),'Original scientific asset links disappeared')
            for anchor,destination in GEGI_SECTION_TARGETS.items():
                page,fragment=destination.split('#',1)
                self.assertIn(fragment,ids(exhibits[page]),anchor)
            home=(fixture/'index.html').read_text(encoding='utf-8')
            self.assertIn('id="main-result-link" href="results/gegi-shared-readout/index.html"',home)
            self.assertLess(home.index('id="main-result-link"'),home.index('id="pipeline-example"'))
            self.assertNotIn('<figure class="spectrum-panel"',home)
            guide=(fixture/'guide.html').read_text(encoding='utf-8')
            self.assertIn('Julia 1.13.0',guide)
            self.assertIn('PowerShell in the project root',guide)
            self.assertIn('four-case Cs137 10K',guide)
            self.assertIn('BuildPortableSourceExporter',guide)
            learn=(fixture/'learn/index.html').read_text(encoding='utf-8')
            results=(fixture/'results/index.html').read_text(encoding='utf-8')
            self.assertEqual(learn.count('href="signals/index.html"'),1)
            self.assertNotIn('http-equiv="refresh"',learn)
            self.assertNotIn('../examples/gamma-native/gamma.html',learn)
            studies={m.group(1):m.group(2) for m in re.finditer(
                r'<article class="card" id="([^"]+)"[^>]*>(.*?)</article>',results,re.S)}
            self.assertEqual(list(studies),['gegi-shared-readout','gegi-campaign','tenk','million'])
            self.assertIn('gegi-shared-readout/index.html',studies['gegi-shared-readout'])
            for population in ('434 conditional signal groups','434 selected for the joint map',
                               '837 candidate orders','708-group historical control'):
                self.assertIn(population,studies['gegi-campaign'])
            self.assertIn('../learn/signals/index.html',results)
            self.assertIn('1,000,000 initial Cs-137 decays per detector',studies['million'])
            self.assertNotIn('events.html',studies['million'])
            main=exhibits[GEGI_PAGE_PATHS['shared-readout']]
            for text in ('25 independent 250 ms','summed 6.25 s','resets its source clocks and electronics state',
                         '5.03987132 s','53,033 qualified triggers','40,979 accepted energies','≥60 s'):
                self.assertIn(text,main)
            self.assertNotIn('id="gegi-source-exposure"',main)
            self.assertNotIn('<figure class="gegi-result-figure"',results)
            self.assertIn('../../methods/index.html#gegi-acquisition-method',main)
            catalog=json.loads((fixture/'models/catalog.json').read_text())
            selected=['index.html','guide.html','learn/index.html','detectors/index.html','results/index.html',
                      'results/cs137-1m/index.html','results/cs137-10k/index.html','methods/index.html',
                      *GEGI_PAGE_PATHS.values(),*Routes.CANONICAL_VIEWS.values(),
                      'results/gegi-campaign/index.html']
            for model in catalog['detectors']:
                base='detectors/'+model['id']+'/'
                selected.extend(base+name for name in ('index.html','gallery.html','technical.html','geometry.html'))
                overview=(fixture/base/'index.html').read_text(encoding='utf-8')
                self.assertEqual(overview.count('id="featured-detector-navigation"'),1)
                self.assertEqual(overview.count('id="ssd-interactive-geometry"'),1)
                self.assertIn('href="geometry.html"',overview)
                self.assertIn('href="runs/20260922_suite_v3/01_geometry.png"',overview)
                self.assertNotRegex(overview,r'<iframe\b')
                self.assertNotIn('../../downloads/'+model['id']+'.zip',overview)
                self.assertNotIn('../../models/'+model['id']+'.yaml',overview)
                self.assertNotIn('Canonical contact name',overview)
                self.assertIn('href="technical.html"',overview)
                if model['id'] in ('AK02','SAP22'):
                    self.assertIn('id="native-cs137-10k"',overview)
                    self.assertIn(f'../../results/cs137-10k/{model["id"]}/charge-readout.html',overview)
                    self.assertIn('../../results/cs137-1m/index.html',overview)
                    self.assertIn('../../guide.html#local-control',overview)
                self.assertNotIn('Run.cmd run',overview)
                technical=(fixture/base/'technical.html').read_text(encoding='utf-8')
                self.assertIn('Model at a glance',technical)
                self.assertIn('Coordinate bounds:',technical)
                self.assertIn('href="index.html">Overview',technical)
                self.assertIn('../../downloads/'+model['id']+'.zip',technical)
                self.assertIn('../../models/'+model['id']+'.yaml',technical)
                self.assertIn('Canonical contact name',technical)
                for contact in model['contacts']:
                    self.assertIn('<td>'+str(contact['id'])+'</td><td>'+escape(contact['name'])+
                                  '</td><td>'+str(contact['potential_V'])+'</td>',technical)
                gallery=(fixture/base/'gallery.html').read_text(encoding='utf-8')
                self.assertIn('id="saved-gallery-intro"',gallery)
                self.assertIn('aria-label="Fields and signals"',gallery)
                self.assertIn('Original synthetic SSD study',gallery)
                for href in re.findall(r'<a href="([^"]+)">Detector library</a>',gallery):
                    self.assertEqual(local_target(base+'gallery.html',href),'detectors/index.html')

            for relative in selected:
                html=(fixture/relative).read_text(encoding='utf-8')
                primary=re.findall(r'<nav aria-label="Primary"[^>]*>(.*?)</nav>',html,re.S)
                self.assertEqual(len(primary),1,'Expected one shared primary navigation in '+relative)
                self.assertEqual(re.findall(r'>([^<]+)</a>',primary[0]),
                                 [label for _,label in PRIMARY],relative)
                for nav in re.findall(r'<nav\b[^>]*>.*?</nav>',html,re.S):
                    self.assertLessEqual(len(re.findall(r'\baria-current=',nav)),1,relative)
                self.assertEqual(len(ids(html)),len(set(ids(html))),'Duplicate IDs in '+relative)
                links=Links();links.feed(html)
                for url in links.urls:
                    target=local_target(relative,url)
                    if target is None:
                        continue
                    path=fixture/target
                    if path.is_dir():
                        path=path/'index.html'
                    self.assertTrue(path.exists(),relative+' -> '+url)
                    fragment=unquote(urlsplit(url).fragment)
                    if fragment and path.suffix=='.html':
                        self.assertIn(fragment,ids(path.read_text(encoding='utf-8')),relative+' -> '+url)

if __name__=='__main__':
    unittest.main(verbosity=2)
