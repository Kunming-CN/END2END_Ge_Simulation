"""Test full generated navigation using a disposable structural site fixture.
HTML/JSON use the saved site; large media are placeholders for existence checks.
This does not replace the real site's manifest/media validation or browser tests.
"""
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlsplit, unquote
import site_restructure as S
from site_fragments import ids
from check_site import Links, local_target
ROOT=Path(__file__).resolve().parents[1]

class HierarchyTests(unittest.TestCase):
    def test_all_model_repeat_generation_and_fragments(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture=Path(tmp)/'site'
            def copy(source,dest):
                path=Path(source)
                if path.suffix in ('.html','.json','.md'):
                    shutil.copyfile(source,dest)
                else:
                    Path(dest).write_bytes(b'fixture existence marker')
                return dest
            shutil.copytree(ROOT/'docs',fixture,copy_function=copy)
            original_ids={p.relative_to(fixture).as_posix():set(ids(p.read_text(encoding='utf-8')))
                          for p in fixture.rglob('*.html')}
            old_home=(fixture/'index.html').read_text(encoding='utf-8')
            old_preview=re.findall(r'<figure class="spectrum-panel".*?</figure>',old_home,re.S)
            S.apply(fixture)
            first={p.relative_to(fixture).as_posix():p.read_bytes() for p in fixture.rglob('*.html')}
            S.apply(fixture)
            second={p.relative_to(fixture).as_posix():p.read_bytes() for p in fixture.rglob('*.html')}
            self.assertEqual(first,second,'Repeated navigation generation changed HTML')
            for relative,anchors in original_ids.items():
                current=set(ids((fixture/relative).read_text(encoding='utf-8')))
                self.assertTrue(anchors<=current,'Old fragments removed from '+relative+': '+str(anchors-current))
            home=(fixture/'index.html').read_text(encoding='utf-8')
            self.assertNotIn('Featured completed result',home)
            for card in re.findall(r'<article class="card">.*?</article>',home,re.S):
                if '<figure' in card:
                    self.assertLess(card.index('<a '),card.index('<figure'),'Primary action follows preview')
            self.assertEqual(old_preview,re.findall(r'<figure class="spectrum-panel".*?</figure>',home,re.S))
            self.assertIn('Fresh-machine reproduction remains unvalidated',home)
            guide=(fixture/'guide.html').read_text(encoding='utf-8')
            self.assertIn('Julia <strong>1.13.0</strong>',guide)
            self.assertIn('PowerShell in the repository root',guide)
            self.assertNotRegex(guide,r'(?<!\\)Run\.cmd (?:check|run|setup|open|resume)')
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
                self.assertIn('../../downloads/'+model['id']+'.zip',overview)
                if model['id'] in ('AK02','SAP22'):
                    self.assertIn('id="native-cs137-10k"',overview)
                    self.assertLess(overview.index('<strong>Current:</strong>'),overview.index('<strong>Earlier:</strong>'))
                    self.assertIn('../../guide.html#local-routes',overview)
                self.assertNotIn('Run.cmd run',overview)
                technical=(fixture/base/'technical.html').read_text(encoding='utf-8')
                self.assertIn('Model at a glance',technical)
                self.assertIn('Coordinate bounds:',technical)
                self.assertIn('href="index.html">Overview',technical)
                gallery=(fixture/base/'gallery.html').read_text(encoding='utf-8')
                self.assertIn('earlier saved gallery',gallery)
                self.assertIn('Original synthetic SSD study',gallery)
                for href in re.findall(r'<a href="([^"]+)">Detector library</a>',gallery):
                    self.assertEqual(local_target(base+'gallery.html',href),'detectors/index.html')

            for relative in selected:
                html=(fixture/relative).read_text(encoding='utf-8')
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
