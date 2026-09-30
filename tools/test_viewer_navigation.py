"""Bounded reader adapter checks; original physics is never regenerated."""
import gzip
import json
import re
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
import viewer_navigation as V

class Readers(unittest.TestCase):
    def test_signed_saved_bundles(self):
        records=V.origins(V.ROOT/'docs',checked=True)
        self.assertEqual(len(records),len(list((V.ROOT/'docs/examples/cs137-10k-geometry').rglob('*')))-2+7)

    def test_original_sources_and_payload_populations(self):
        self.assertEqual({p:V.sha(V.ROOT/p) for p in V.ORIGINAL_SOURCES},V.ORIGINAL_SOURCES)
        for model,count in [('AK02',121),('SAP22',115)]:
            p=V.ROOT/f'docs/examples/cs137-10k-hits/{model}/selected.json.gz'
            data=json.loads(gzip.decompress(p.read_bytes()))
            self.assertEqual(len(data['event_ids']),count)
            self.assertIn(213 if model=='AK02' else 74,data['event_ids'])
            if model=='SAP22':self.assertNotIn(213,data['event_ids'])
            for e in data['evidence']:
                self.assertTrue(e['groups'])
                self.assertTrue(all(type(g['group_id']) is int and g['group_id']>=0 for g in e['groups']))

    def test_adapter_reuses_renderers_and_paths(self):
        for src,dest in V.ROUTES.items():
            text=V.render(V.ROOT/'docs',src);original=(V.ROOT/'docs'/src).read_text(encoding='utf-8')
            # Exact renderer bodies, no second rendering implementation.
            for name,end in [('draw','function fit')]:
                start=original.index('function '+name+'(');stop=original.index(end,start)
                self.assertIn(original[start:stop],text)
            self.assertIn('id="reciprocal"',text)
            self.assertIn('all 20,000 initial events',text)
            self.assertIn('121 AK02 / 115 SAP22',text)
            for href in re.findall(r'<a\b[^>]*href="([^"]+)"',text):
                if href=='#':continue
                resolved=(V.ROOT/'docs'/Path(dest).parent/href).resolve()
                self.assertTrue(resolved.is_relative_to(V.ROOT/'docs'))
                if '/viewers/' not in resolved.as_posix():self.assertTrue(resolved.is_file(),href)
            self.assertIn('await fetch("../'+str(Path(src).parent).replace('\\','/')+'/"+path)',text)
            self.assertNotIn("$('allEvents').href=m.all_events_url",text)

    def test_guards_refuse_anchor_source_and_pin_changes(self):
        with self.assertRaisesRegex(ValueError,'anchor'):V.replace('old old','old','new')
        with patch.dict(V.FROZEN,{'tools/viewer_navigation.js':'changed'}):
            with self.assertRaisesRegex(ValueError,'sources changed'):V.frozen()
        with patch.dict(V.PINS,{'examples/cs137-10k-hits/manifest.json':'changed'}):
            with self.assertRaisesRegex(ValueError,'manifest changed'):V.origins(V.ROOT/'docs')

    def test_rehashed_adapter_mutation_still_fails(self):
        # Origin payloads have their own real sealed-bundle test above. This
        # fixture isolates deterministic HTML enforcement after malicious rehash.
        with tempfile.TemporaryDirectory(dir=V.ROOT/'.local',prefix='reader-test-') as tmp:
            site=Path(tmp);pages={}
            for src,dest in V.ROUTES.items():
                (site/src).parent.mkdir(parents=True,exist_ok=True)
                (site/src).write_bytes((V.ROOT/'docs'/src).read_bytes())
                V.write(site/dest,V.render(site,src));pages[dest]={'source':src,'sha256':V.sha(site/dest)}
            m={'kind':'reciprocal_geant4_readers_v1','original_files':{},'original_sources':V.ORIGINAL_SOURCES,'adapter_sources':V.FROZEN,'pages':pages}
            V.write(site/'viewers/manifest.json',json.dumps(m))
            with patch.object(V,'origins',return_value={}):
                V.validate(site,True)
                dest=site/'viewers/ge-positive.html'
                V.write(dest,dest.read_text(encoding='utf-8').replace('No matching pulse group.','Wrong message') if 'No matching pulse group.' in dest.read_text(encoding='utf-8') else dest.read_text(encoding='utf-8').replace('No primary or group is highlighted.','A fabricated primary is highlighted.'))
                m['pages']['viewers/ge-positive.html']['sha256']=V.sha(dest)
                V.write(site/'viewers/manifest.json',json.dumps(m))
                with self.assertRaisesRegex(ValueError,'Nondeterministic'):V.validate(site)
                # Unknown self-declared code hashes cannot disable reconstruction.
                m['adapter_sources']=dict(V.FROZEN)
                m['adapter_sources']['tools/viewer_navigation.js']='0'*64
                V.write(site/'viewers/manifest.json',json.dumps(m))
                with self.assertRaisesRegex(ValueError,'Unknown adapter source'):V.validate(site)
                # A previous version is trusted only by the entire exact manifest.
                V.write(dest,V.render(site,'examples/cs137-10k-hits/hit_event_view.html'))
                m['pages']['viewers/ge-positive.html']['sha256']=V.sha(dest)
                V.write(site/'viewers/manifest.json',json.dumps(m))
                previous=V.sha(site/'viewers/manifest.json')
                with patch.object(V,'TRUSTED_PREVIOUS_MANIFESTS',frozenset({previous})):
                    V.validate(site)
                    with self.assertRaisesRegex(ValueError,'Unknown adapter source'):V.validate(site,True)
                    V.write(dest,dest.read_text(encoding='utf-8').replace('No primary or group is highlighted.','Fabricated selection.'))
                    m['pages']['viewers/ge-positive.html']['sha256']=V.sha(dest)
                    V.write(site/'viewers/manifest.json',json.dumps(m))
                    with self.assertRaisesRegex(ValueError,'Unknown adapter source'):V.validate(site)


    def test_current_route_rebase_retains_identity(self):
        original='<a href="../../examples/cs137-10k-hits/hit_event_view.html?model=SAP22&amp;event=0&amp;group=0">Event</a>'
        result=V.route_links(original,'detectors/SAP22/index.html')
        self.assertIn('../../viewers/ge-positive.html?model=SAP22&amp;event=0&amp;group=0',result)
        self.assertEqual(V.route_links(result,'detectors/SAP22/index.html'),result)

if __name__=='__main__':unittest.main(verbosity=2)
