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
from html import escape
from unittest.mock import patch
from pathlib import Path
from urllib.parse import urlsplit, unquote
import site_restructure as S
import ring_site as R
import result_web_delivery as delivery
from gegi_digital_display import render as render_gegi
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
            # Restore the two exact archives used by the saved-report generator.
            # The normal archive binding still applies in this owned test stage.
            with patch.object(delivery,'_stage',side_effect=delivery.directory):
                delivery.materialize_for_build(fixture)
            original_ids={p.relative_to(fixture).as_posix():set(ids(p.read_text(encoding='utf-8')))
                          for p in fixture.rglob('*.html')}
            gamma=fixture/'examples/gamma-native'
            gamma_bytes={p.name:p.read_bytes() for p in gamma.glob('*') if p.is_file()}
            formal=fixture/'results/gegi-campaign/publication.json'
            formal_before=json.loads(formal.read_bytes())
            saved_hashes={p.relative_to(fixture).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in fixture.rglob('*') if p.is_file() and p.suffix!='.html'}
            def maintain():
                S.apply(fixture)
                render_gegi(fixture)
                R.apply(fixture)
            maintain()
            first={p.relative_to(fixture).as_posix():p.read_bytes() for p in fixture.rglob('*.html')}
            maintain()
            second={p.relative_to(fixture).as_posix():p.read_bytes() for p in fixture.rglob('*.html')}
            self.assertEqual(first,second,'Repeated navigation generation changed HTML')
            self.assertEqual(gamma_bytes,{p.name:p.read_bytes() for p in gamma.glob('*') if p.is_file()})
            formal_after=json.loads(formal.read_bytes())
            for stamp in (formal_before,formal_after):
                stamp.pop('display_source_sha256',None)
                stamp['artifacts'].pop('index.html')
            self.assertEqual(formal_before,formal_after,'Formal campaign data provenance changed')
            current_hashes={p.relative_to(fixture).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in fixture.rglob('*') if p.is_file() and p.suffix!='.html'}
            presentation_receipts={'methods/native-li-display.json','methods/lithium-display.json',
                                   'results/gegi-campaign/publication.json'}
            self.assertEqual({name:h for name,h in saved_hashes.items() if name not in presentation_receipts},
                             {name:h for name,h in current_hashes.items() if name not in presentation_receipts})
            added=set(current_hashes)-set(saved_hashes)
            self.assertTrue(added <= {'methods/native-li-display.json','methods/lithium-display.json'})
            from saved_archive_display import validate as validate_archive_display
            validate_archive_display(fixture)
            for relative,anchors in original_ids.items():
                current=set(ids((fixture/relative).read_text(encoding='utf-8')))
                self.assertTrue(anchors<=current,'Old fragments removed from '+relative+': '+str(anchors-current))
            home=(fixture/'index.html').read_text(encoding='utf-8')
            self.assertIn('id="main-result-link" href="results/index.html"',home)
            self.assertLess(home.index('id="main-result-link"'),home.index('id="pipeline-example"'))
            self.assertNotIn('<figure class="spectrum-panel"',home)
            guide=(fixture/'guide.html').read_text(encoding='utf-8')
            self.assertIn('Julia 1.13.0',guide)
            self.assertIn('PowerShell in the project root',guide)
            self.assertIn('four-case Cs137 10K',guide)
            self.assertIn('BuildPortableSourceExporter',guide)
            learn=(fixture/'learn/index.html').read_text(encoding='utf-8')
            results=(fixture/'results/index.html').read_text(encoding='utf-8')
            self.assertEqual(learn.count('href="../spectra/pipeline.html"'),1)
            self.assertNotIn('../examples/gamma-native/gamma.html',learn)
            self.assertNotIn('../examples/gamma-native/gamma.html',results)
            panels={m.group(1):m.group(2) for m in re.finditer(
                r'<section id="(teaching|gamma|tenk|million)"[^>]*>(.*?)</section>',results,re.S)}
            self.assertEqual(list(panels),['teaching','tenk','million','gamma'])
            self.assertLess(results.index('id="gegi-data-methods"'),results.index('id="historical-studies"'))
            self.assertIn('../methods/index.html#gegi-acquisition-method',results)
            self.assertIn('../spectra/pipeline.html',panels['teaching'])
            self.assertIn('have been retired',panels['gamma'])
            self.assertIn('four separate cases',panels['tenk'])
            self.assertIn('one million initial decays per detector',panels['million'])
            self.assertNotIn('viewers/events.html',panels['million'])
            catalog=json.loads((fixture/'models/catalog.json').read_text())
            selected=['index.html','guide.html','learn/index.html','detectors/index.html','results/index.html',
                      'results/cs137-1m/index.html','results/cs137-10k/index.html','methods/index.html',
                      'scenarios/lbnl-cs137/index.html']
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
                self.assertIn('earlier saved gallery',gallery)
                self.assertIn('Original synthetic SSD study',gallery)
                for href in re.findall(r'<a href="([^"]+)">Detector library</a>',gallery):
                    self.assertEqual(local_target(base+'gallery.html',href),'detectors/index.html')

            for relative in selected:
                html=(fixture/relative).read_text(encoding='utf-8')
                primary=re.search(r'<nav aria-label="Primary"[^>]*>(.*?)</nav>',html,re.S)
                if primary:
                    self.assertEqual(re.findall(r'>([^<]+)</a>',primary.group(1)),
                                     [label for _,label in PRIMARY],relative)
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
