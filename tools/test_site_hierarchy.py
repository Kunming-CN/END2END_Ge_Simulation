"""Test full generated navigation using a disposable structural site fixture.
HTML/JSON/Markdown/CSV use saved bytes; large media are placeholders for existence checks.
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
from site_fragments import ids
from check_site import Links, local_target
ROOT=Path(__file__).resolve().parents[1]

class HierarchyTests(unittest.TestCase):
    def test_all_model_repeat_generation_and_fragments(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'.local') as tmp:
            fixture=Path(tmp)/'site'
            def copy(source,dest):
                path=Path(source)
                if path.suffix in ('.html','.json','.md','.csv','.js') or path.name=='ledgers.zip':
                    shutil.copyfile(source,dest)
                else:
                    Path(dest).write_bytes(b'fixture existence marker')
                return dest
            shutil.copytree(ROOT/'docs',fixture,copy_function=copy)
            original_ids={p.relative_to(fixture).as_posix():set(ids(p.read_text(encoding='utf-8')))
                          for p in fixture.rglob('*.html')}
            old_home=(fixture/'index.html').read_text(encoding='utf-8')
            old_preview=re.findall(r'<figure class="spectrum-panel".*?</figure>',old_home,re.S)
            if not old_preview:
                old_preview=re.findall(r'<figure class="spectrum-panel".*?</figure>',(fixture/'results/cs137-1m/index.html').read_text(),re.S)
            gamma=fixture/'examples/gamma-native'
            gamma_bytes={p.name:p.read_bytes() for p in gamma.iterdir() if p.is_file()}
            saved_hashes={p.relative_to(fixture).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in fixture.rglob('*') if p.is_file() and p.suffix!='.html'}
            # Structural placeholders do not represent ring payload validation.
            # Reuse checked source metadata; ring source validation has separate tests.
            cases=R.cases(ROOT/'docs')
            def maintain():
                S.apply(fixture)
                with patch.object(R,'cases',return_value=cases):R.apply(fixture)
            maintain()
            first={p.relative_to(fixture).as_posix():p.read_bytes() for p in fixture.rglob('*.html')}
            maintain()
            second={p.relative_to(fixture).as_posix():p.read_bytes() for p in fixture.rglob('*.html')}
            self.assertEqual(first,second,'Repeated navigation generation changed HTML')
            self.assertEqual(gamma_bytes,{p.name:p.read_bytes() for p in gamma.iterdir() if p.is_file()})
            current_hashes={p.relative_to(fixture).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in fixture.rglob('*') if p.is_file() and p.suffix!='.html'}
            self.assertEqual({name:h for name,h in saved_hashes.items() if name not in {'methods/native-li-display.json','methods/lithium-display.json'}},
                             {name:current_hashes[name] for name in saved_hashes if name not in {'methods/native-li-display.json','methods/lithium-display.json'}})
            added=set(current_hashes)-set(saved_hashes)
            self.assertTrue(added <= {'methods/native-li-display.json','methods/lithium-display.json'})
            from saved_archive_display import validate as validate_archive_display
            validate_archive_display(fixture)
            for relative,anchors in original_ids.items():
                if relative=='index.html':
                    # Preview asset IDs move with the exact1M panel; user-facing historical anchors stay.
                    anchors=anchors-{'spectrum-style','spectrum-controls-script'}
                    campaign_ids=set(ids((fixture/'results/cs137-1m/index.html').read_text()))
                    self.assertTrue({'spectrum-style','spectrum-controls-script'}<=campaign_ids)
                current=set(ids((fixture/relative).read_text(encoding='utf-8')))
                self.assertTrue(anchors<=current,'Old fragments removed from '+relative+': '+str(anchors-current))
            home=(fixture/'index.html').read_text(encoding='utf-8')
            self.assertNotIn('Featured completed result',home)
            for card in re.findall(r'<article class="card">.*?</article>',home,re.S):
                if '<figure' in card:
                    self.assertLess(card.index('<a '),card.index('<figure'),'Primary action follows preview')
            self.assertEqual([],re.findall(r'<figure class="spectrum-panel".*?</figure>',home,re.S))
            self.assertEqual(old_preview,re.findall(r'<figure class="spectrum-panel".*?</figure>',(fixture/'results/cs137-1m/index.html').read_text(),re.S))
            self.assertIn('Fresh-machine setup remains unvalidated',home)
            guide=(fixture/'guide.html').read_text(encoding='utf-8')
            self.assertIn('Julia 1.13.0',guide)
            self.assertIn('PowerShell in the project root',guide)
            self.assertIn('four-case Cs137 10K',guide)
            self.assertIn('BuildPortableSourceExporter',guide)
            learn=(fixture/'learn/index.html').read_text(encoding='utf-8')
            results=(fixture/'results/index.html').read_text(encoding='utf-8')
            self.assertEqual(learn.count('../spectra/pipeline.html'),1)
            self.assertNotIn('../examples/gamma-native/gamma.html',learn)
            self.assertEqual(results.count('../examples/gamma-native/gamma.html'),1)
            panels={m.group(1):m.group(2) for m in re.finditer(
                r'<section id="(teaching|gamma|tenk|million)"[^>]*>(.*?)</section>',results,re.S)}
            self.assertEqual(list(panels),['teaching','gamma','tenk','million'])
            self.assertIn('../spectra/pipeline.html',panels['teaching'])
            self.assertIn('bare geometry',panels['teaching'])
            self.assertIn('Different geometry and event IDs',panels['gamma'])
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
                    self.assertIn('Open this detector’s 10K result',overview)
                    self.assertIn('Separate Cs137 1M campaign',overview)
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
                                     ['Results','Detectors','Run locally','Methods'],relative)
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
