"""Saved-reader adapter integrity checks; no numerical output is regenerated."""
import gzip
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit
import viewer_navigation as V

class Readers(unittest.TestCase):
    def original_html(self, site):
        for source in V.ROUTES:
            destination=site/source
            destination.parent.mkdir(parents=True,exist_ok=True)
            destination.write_bytes((V.ROOT/'docs'/source).read_bytes())

    def current_fixture(self, site):
        self.original_html(site)
        pages={}
        for destination,binding in V.PAGES.items():
            V.write(site/destination,V.render(site,destination))
            pages[destination]={**binding,'sha256':V.sha(site/destination)}
        manifest={'kind':'unified_geant4_reader_v1','original_files':{},
                  'original_sources':V.ORIGINAL_SOURCES,'adapter_sources':dict(V.FROZEN),
                  'pages':pages,'new_simulations':0}
        self.save_manifest(site,manifest)
        return manifest

    def save_manifest(self, site, manifest):
        V.write(site/'viewers/manifest.json',json.dumps(manifest,indent=2)+'\n')

    def test_signed_saved_bundles(self):
        records=V.origins(V.ROOT/'docs',checked=True)
        expected={p.relative_to(V.ROOT/'docs').as_posix()
                  for folder in ('cs137-10k-geometry','cs137-10k-hits')
                  for p in (V.ROOT/'docs/examples'/folder).rglob('*') if p.is_file()}
        self.assertEqual(set(records),expected)

    def test_original_sources_and_payload_populations(self):
        self.assertEqual({p:V.sha(V.ROOT/p) for p in V.ORIGINAL_SOURCES},V.ORIGINAL_SOURCES)
        groups=0
        for model,count in [('AK02',121),('SAP22',115)]:
            path=V.ROOT/f'docs/examples/cs137-10k-hits/{model}/selected.json.gz'
            data=json.loads(gzip.decompress(path.read_bytes()))
            self.assertEqual(len(data['event_ids']),count)
            self.assertEqual([e['event_id'] for e in data['events']],data['event_ids'])
            self.assertEqual([e['event_id'] for e in data['evidence']],data['event_ids'])
            self.assertIn(213 if model=='AK02' else 5930,data['event_ids'])
            if model=='SAP22':self.assertNotIn(213,data['event_ids'])
            for evidence in data['evidence']:
                self.assertTrue(evidence['groups'])
                for group in evidence['groups']:
                    self.assertIs(type(group['group_id']),int)
                    self.assertGreaterEqual(group['group_id'],0)
                    self.assertTrue(group['ge_raw_row_indices'])
                    groups+=1
        self.assertEqual(groups,236)

    def test_three_routes_deterministic_controller_and_data_binding(self):
        self.assertEqual(set(V.PAGES),{'viewers/events.html','viewers/ge-positive.html','viewers/geant4-assembly.html'})
        main=V.render(V.ROOT/'docs')
        self.assertEqual(main,V.render(V.ROOT/'docs','viewers/events.html'))
        scripts=re.findall(r'<script\b[^>]*id="([^"]+)"[^>]*>([\s\S]*?)</script>',main)
        self.assertEqual([name for name,_ in scripts],['viewer-navigation','viewer-config','viewer-controller'])
        self.assertEqual(scripts[0][1],(V.ROOT/'tools/viewer_navigation.js').read_text(encoding='utf-8'))
        self.assertEqual(scripts[2][1],(V.ROOT/'tools/unified_event_viewer.js').read_text(encoding='utf-8'))
        config=json.loads(re.fullmatch(r'const VIEWER_CONFIG = (.*);',scripts[1][1]).group(1))
        expected_config={'assembly':{'base':'../examples/cs137-10k-geometry/',
                         'sha256':V.PINS['examples/cs137-10k-geometry/manifest.json']},
                         'positive':{'base':'../examples/cs137-10k-hits/',
                         'sha256':V.PINS['examples/cs137-10k-hits/manifest.json']}}
        ring_manifest=V.ROOT/'docs/examples/cs137-10k-rings/manifest.json'
        if ring_manifest.is_file():
            expected_config['models']={model:{layer:{'base':'../examples/cs137-10k-rings/',
                'sha256':V.sha(ring_manifest),'kind':'ring_saved_publication_v1'}
                for layer in ('assembly','positive')} for model in ('GeRC02','KMRC01_candidate')}
        self.assertEqual({key:config[key] for key in expected_config},expected_config)
        self.assertEqual(set(config['case_routes']),{'AK02','SAP22','GeRC02','KMRC01_candidate'})
        for name,entry in config['case_routes'].items():
            self.assertEqual(entry['result'],'../results/cs137-10k/'+name+'/charge-readout.html')
            self.assertEqual(entry['files'],entry['result']+'#data-files')
            self.assertEqual(entry['spectrum'],'../spectra/cs137-10k.html#tenk-'+name)
            for item in entry['original_files'].values():
                path=(V.ROOT/'docs/viewers'/item['href']).resolve()
                self.assertEqual(V.sha(path),item['sha256'])
                self.assertEqual(path.stat().st_size,item['bytes'])
        self.assertNotIn('savedCurrent',config['case_routes']['AK02']['original_files'])
        self.assertNotIn('savedCurrent',config['case_routes']['SAP22']['original_files'])
        if ring_manifest.is_file():
            for name in ('GeRC02','KMRC01_candidate'):
                self.assertTrue(config['case_routes'][name]['original_files']['savedScalars']['href'].endswith('/response/scalars.jsonl'))
        self.assertEqual(len(re.findall(r'<canvas\b',main)),1)
        ids=re.findall(r'\bid="([^"]+)"',main)
        self.assertEqual(len(ids),len(set(ids)))
        for required in ('model','eid','view','group','recordPanel','records','evidencePanel','evidenceRaw'):
            self.assertIn(required,ids)
        for page,binding in V.PAGES.items():
            text=V.render(V.ROOT/'docs',page)
            self.assertEqual(text,V.render(V.ROOT/'docs',page))
            if binding['role']=='alias':
                self.assertEqual(re.findall(r'<script\b[^>]*id="([^"]+)"',text),['viewer-navigation','viewer-alias'])
                self.assertNotIn('<canvas',text)
                self.assertNotIn('fetch(',text)
                self.assertIn('legacyViewerTarget(location.search,'+json.dumps(binding['view'])+')',text)
                self.assertEqual(text,V.render(V.ROOT/'docs',binding['source']))
            for href in re.findall(r'<a\b[^>]*href="([^"]+)"',text):
                parts=urlsplit(href)
                if parts.scheme or parts.netloc or not parts.path:continue
                resolved=(V.ROOT/'docs'/Path(page).parent/parts.path).resolve()
                self.assertTrue(resolved.is_relative_to(V.ROOT/'docs'))
                if resolved.relative_to(V.ROOT/'docs').as_posix() not in {*V.PAGES,'viewers/manifest.json'}:
                    self.assertTrue(resolved.is_file(),href)

    def test_guards_refuse_anchor_source_pin_and_unknown_page(self):
        with self.assertRaisesRegex(ValueError,'anchor'):V.replace('old old','old','new')
        with patch.dict(V.FROZEN,{'tools/viewer_navigation.js':'changed'}):
            with self.assertRaisesRegex(ValueError,'sources changed'):V.frozen()
        with patch.dict(V.PINS,{'examples/cs137-10k-hits/manifest.json':'changed'}):
            with self.assertRaisesRegex(ValueError,'manifest changed'):V.origins(V.ROOT/'docs')
        with self.assertRaisesRegex(ValueError,'Unknown reader page'):V.render(V.ROOT/'docs','viewers/unknown.html')

    def test_response_files_are_exactly_available_and_rehashing_is_not_authority(self):
        import shutil
        with tempfile.TemporaryDirectory(dir=V.ROOT/'.local/student-navigation-v2',prefix='response-links-') as tmp:
            site=Path(tmp);folder=site/V.RESPONSE_BASE;folder.mkdir(parents=True)
            shutil.copyfile(V.ROOT/'docs'/V.RESPONSE_BASE/'publication.json',folder/'publication.json')
            for name in ('AK02','SAP22'):
                for file in ('signals.csv','scalars.csv'):
                    path=folder/name/'response'/file;path.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copyfile(V.ROOT/'docs'/V.RESPONSE_BASE/name/'response'/file,path)
            config=V.config(site)
            for name in ('AK02','SAP22'):
                self.assertEqual(set(config['case_routes'][name]['original_files']),{'savedSignals','savedScalars'})
                self.assertNotIn('readout-input.csv',json.dumps(config['case_routes'][name]))
            path=folder/'AK02/response/signals.csv';path.write_bytes(path.read_bytes()+b'\nunauthorized')
            with self.assertRaisesRegex(ValueError,'asset changed'):V.config(site)
            m=V.read(folder/'publication.json');m['files']['AK02/response/signals.csv']['sha256']=V.sha(path)
            m['files']['AK02/response/signals.csv']['bytes']=path.stat().st_size
            V.write(folder/'publication.json',json.dumps(m))
            with self.assertRaisesRegex(ValueError,'publication changed'):V.config(site)

    def test_rehashed_current_html_and_unknown_code_are_refused(self):
        with tempfile.TemporaryDirectory(dir=V.ROOT/'.local',prefix='reader-test-') as tmp:
            site=Path(tmp);manifest=self.current_fixture(site)
            with patch.object(V,'origins',return_value={}):
                V.validate(site,True)
                destination=site/'viewers/events.html'
                V.write(destination,destination.read_text(encoding='utf-8')+'\n<!-- rehashed unauthorized HTML -->')
                manifest['pages']['viewers/events.html']['sha256']=V.sha(destination)
                self.save_manifest(site,manifest)
                with self.assertRaisesRegex(ValueError,'Nondeterministic'):V.validate(site)
                V.write(destination,V.render(site))
                manifest['pages']['viewers/events.html']['sha256']=V.sha(destination)
                manifest['adapter_sources']['tools/unified_event_viewer.js']='0'*64
                self.save_manifest(site,manifest)
                with self.assertRaisesRegex(ValueError,'Unknown adapter source'):V.validate(site)
                # Unlike an explicitly trusted OLD whole manifest, a new schema
                # cannot authorize arbitrary code merely by pinning itself.
                with patch.object(V,'TRUSTED_PREVIOUS_MANIFESTS',frozenset({V.sha(site/'viewers/manifest.json')})):
                    with self.assertRaisesRegex(ValueError,'Unknown adapter source'):V.validate(site)

    def test_exact_viewer_file_set_and_route_metadata(self):
        with tempfile.TemporaryDirectory(dir=V.ROOT/'.local',prefix='reader-test-') as tmp:
            site=Path(tmp);manifest=self.current_fixture(site)
            with patch.object(V,'origins',return_value={}):
                V.write(site/'viewers/extra.html','<title>Extra</title>')
                with self.assertRaisesRegex(ValueError,'file inventory'):V.validate(site)
                (site/'viewers/extra.html').unlink()
                alias=site/'viewers/ge-positive.html';saved=alias.read_bytes();alias.unlink()
                with self.assertRaisesRegex(ValueError,'file inventory'):V.validate(site)
                alias.write_bytes(saved)
                manifest['pages']['viewers/ge-positive.html']['view']='assembly'
                self.save_manifest(site,manifest)
                with self.assertRaisesRegex(ValueError,'route binding'):V.validate(site)

    def test_old_whole_manifest_compatibility_not_self_rebase(self):
        # A disposable old-schema stand-in tests the trust boundary. The real
        # protected whole-manifest pin and original science pins remain distinct.
        self.assertIn('2c65448b9bf9ab1eaf603e22e091d061cd6ace669601c9442fb5194a77a23e12',V.TRUSTED_PREVIOUS_MANIFESTS)
        with tempfile.TemporaryDirectory(dir=V.ROOT/'.local',prefix='reader-test-') as tmp:
            site=Path(tmp);pages={}
            for source,destination in V.ROUTES.items():
                V.write(site/destination,'<!doctype html><title>Protected prior fixture</title>')
                pages[destination]={'source':source,'sha256':V.sha(site/destination)}
            manifest={'kind':'reciprocal_geant4_readers_v1','original_files':{},
                      'original_sources':V.ORIGINAL_SOURCES,
                      'adapter_sources':{p:'1'*64 for p in ('tools/viewer_navigation.py','tools/viewer_navigation.js','tools/viewer_overlay_selection.js')},
                      'pages':pages,'new_simulations':0}
            self.save_manifest(site,manifest);previous=V.sha(site/'viewers/manifest.json')
            with patch.object(V,'origins',return_value={}),patch.object(V,'TRUSTED_PREVIOUS_MANIFESTS',frozenset({previous})):
                V.validate(site)
                with self.assertRaisesRegex(ValueError,'Unknown older display'):V.validate(site,True)
                destination=site/'viewers/ge-positive.html'
                V.write(destination,'<!doctype html><title>Changed old fixture</title>')
                with self.assertRaisesRegex(ValueError,'Changed older display HTML'):V.validate(site)
                manifest['pages']['viewers/ge-positive.html']['sha256']=V.sha(destination)
                self.save_manifest(site,manifest)
                with self.assertRaisesRegex(ValueError,'Unknown older display'):V.validate(site)

    def test_current_route_rebase_retains_identity_and_fragment(self):
        for source,view in [('cs137-10k-hits/hit_event_view.html','positive'),
                            ('cs137-10k-geometry/geometry.html','assembly')]:
            original='<a href="../../examples/'+source+'?model=SAP22&amp;event=0&amp;group=0#detail">Event</a>'
            result=V.route_links(original,'detectors/SAP22/index.html')
            self.assertIn('../../viewers/events.html?model=SAP22&amp;event=0&amp;group=0&amp;view='+view+'#detail',result)
            self.assertEqual(V.route_links(result,'detectors/SAP22/index.html'),result)
        malformed='<a href="../../examples/cs137-10k-hits/hit_event_view.html?event=0&amp;event=1&amp;view=assembly">Bad</a>'
        mapped=V.route_links(malformed,'detectors/SAP22/index.html')
        self.assertIn('event=0&amp;event=1&amp;view=assembly&amp;view=positive',mapped)

    def test_orphan_unified_page_invokes_site_guard(self):
        import check_site
        with tempfile.TemporaryDirectory(dir=V.ROOT/'.local',prefix='reader-test-') as tmp:
            site=Path(tmp)
            V.write(site/'index.html','<!doctype html><html><head><title>Fixture</title></head><body></body></html>')
            V.write(site/'viewers/events.html','<!doctype html><html><head><title>Orphan</title></head><body></body></html>')
            with patch.object(V,'validate',side_effect=ValueError('orphan viewer checked')) as guard:
                with self.assertRaisesRegex(ValueError,'orphan viewer checked'):
                    check_site.validate(site,require_manifest=False)
                guard.assert_called_once_with(site.resolve())

if __name__=='__main__':unittest.main(verbosity=2)
