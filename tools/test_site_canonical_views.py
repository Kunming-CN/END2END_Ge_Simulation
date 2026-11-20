"""Display relocation and saved-selection contracts; no scientific computation."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import site_canonical_views as views


class CanonicalViews(unittest.TestCase):
    def test_retained_hit_viewer_has_archive_identity_returns_and_reversible_bytes(self):
        path = 'examples/cs137-10k-hits/hit_event_view.html'
        raw = (views.ROOT / 'tools/hit_event_view.html').read_bytes()
        with tempfile.TemporaryDirectory(dir=views.ROOT / '.local', prefix='archive-frame-') as directory:
            site = Path(directory)
            page = site / path
            page.parent.mkdir(parents=True)
            page.write_bytes(raw)
            asset = page.with_name('science.json')
            asset.write_bytes(b'{"event":26,"signed":-0.0001234567890123456}')
            receipt = views.apply(site)
            output = page.read_text(encoding='utf-8')
            for label in ('Primary', 'Breadcrumb'):
                self.assertEqual(output.count('<nav aria-label="'+label+'"'), 1)
            self.assertIn('Historical AK02/SAP22 Ge-positive viewer', output)
            self.assertIn('Return to the current 10K study', output)
            self.assertIn('Return to the current event viewer', output)
            self.assertIn('../../results/cs137-10k/events.html?model=', output)
            self.assertNotIn("$('allEvents').href=m.all_events_url", output)
            self.assertEqual(output.count('/* archive-current-view-links */'), 1)
            from site_chrome import frame_html
            self.assertEqual(frame_html(output, path), output)
            self.assertEqual(receipt['pages'][0]['mode'], 'framed')
            self.assertEqual(views.apply(site), receipt)
            self.assertTrue(views.prepare(site))
            self.assertEqual(page.read_bytes(), raw)
            self.assertEqual(asset.read_bytes(), b'{"event":26,"signed":-0.0001234567890123456}')

    def test_predecessor_receipt_can_restore_before_archive_framing_is_added(self):
        path = 'examples/cs137-10k-hits/hit_event_view.html'
        raw = (views.ROOT / 'tools/hit_event_view.html').read_bytes()
        with tempfile.TemporaryDirectory(dir=views.ROOT / '.local', prefix='archive-upgrade-') as directory:
            site = Path(directory)
            page = site / path
            page.parent.mkdir(parents=True)
            page.write_bytes(raw)
            prior = dict(kind=views.KIND, science_calls=0, routes=views.CANONICAL_VIEWS,
                         generators={'tools/site_canonical_views.py':'previous source'}, pages=[])
            (site / views.RECEIPT).write_text(json.dumps(prior),encoding='utf-8')
            self.assertTrue(views.prepare(site))
            self.assertEqual(page.read_bytes(),raw)
            views.apply(site)
            self.assertIn(b'Historical AK02/SAP22',page.read_bytes())
            # Current-source receipts must not omit the newly registered archive.
            current=json.loads((site / views.RECEIPT).read_bytes())
            current['pages']=[]
            (site / views.RECEIPT).write_text(json.dumps(current),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'inventory differs'):
                views.validate(site,current=True)

    def test_ring_report_local_archive_notice_is_reversible_and_keeps_data(self):
        path = 'examples/cs137-10k-rings/GeRC02/response/summary.html'
        raw = (b'<html><body><h1>Original ring report</h1><p>Complete truth, endpoints, scalar CSV, histogram CSV and saved traces are delivered byte-for-byte inside the complete ledger ZIP; these download links open that ZIP. Direct signed signals, JSONL scalars and JSON histograms remain available.</p>'
               b'<script type="application/json">{"event":26,"charge":null,"signed":-0.0001234567890123456}</script></body></html>')
        with tempfile.TemporaryDirectory(dir=views.ROOT / '.local', prefix='ring-frame-') as directory:
            site=Path(directory);page=site/path;page.parent.mkdir(parents=True);page.write_bytes(raw)
            views.apply(site)
            output=page.read_bytes()
            self.assertIn(b'not available for download on this website',output)
            self.assertIn(b'../../../../results/cs137-10k/GeRC02/charge-readout.html#data-files',output)
            self.assertNotIn(b'these download links open that ZIP',output)
            self.assertIn(re.search(rb'<script type="application/json">.*?</script>',raw)[0],output)
            views.prepare(site)
            self.assertEqual(page.read_bytes(),raw)

    def test_main_viewer_assembly_entry_is_current_and_explicitly_scoped(self):
        text=(views.ROOT/'tools/unified_event_viewer.html').read_text(encoding='utf-8')
        self.assertIn('href="events.html?model=AK02&amp;view=assembly">AK02 assembly context (current viewer)',text)
        self.assertNotIn('Earlier assembly viewer (archive)',text)
        self.assertNotIn('href="../examples/cs137-10k-geometry/geometry.html"',text)

    def test_direct_links_preserve_queries_fragments_and_scientific_bytes(self):
        source = b'''<!doctype html><html><body>
<a href="strip_explorer.html?event=two_wide_equal&amp;group=0#charge">Saved event</a>
<a href="../../viewers/geant4-assembly.html?event=26&amp;model=KMRC01_candidate#data">Assembly</a>
<a href="../../viewers/ge-positive.html?view=assembly&amp;event=26">Explicit mode</a>
<script type="application/json">{"original_path":"strip_explorer.html","event":26,"signed":-0.0001234567890123456}</script>
<script>const target='../../viewers/events.html?'+location.search;const science='saved.json';</script>
</body></html>'''
        output = views.direct_links_html(source, 'detectors/GeGI_3D/gallery.html')
        text = output.decode()
        self.assertIn('href="../../results/gegi-strip-study/index.html?event=two_wide_equal&amp;group=0#charge"', text)
        self.assertIn('href="../../results/cs137-10k/events.html?event=26&amp;model=KMRC01_candidate&amp;view=assembly#data"', text)
        self.assertIn('href="../../results/cs137-10k/events.html?view=assembly&amp;event=26"', text)
        self.assertIn("target='../../results/cs137-10k/events.html?'+location.search", text)
        self.assertIn("const science='saved.json';", text)
        original_json = re.search(rb'<script type="application/json">.*?</script>', source)[0]
        self.assertIn(original_json, output)
        self.assertEqual(views.direct_links_html(output, 'detectors/GeGI_3D/gallery.html'), output)

    def test_direct_link_receipt_is_reversible_and_apply_is_idempotent(self):
        with tempfile.TemporaryDirectory(dir=views.ROOT / '.local', prefix='canonical-links-') as directory:
            site = Path(directory)
            original = site / 'detectors/GeGI_3D/gallery.html'
            original.parent.mkdir(parents=True)
            raw = b'<html><body><a href="strip_explorer.html?event=cloud#charge">Saved cloud</a><script type="application/json">{"event":26}</script></body></html>'
            original.write_bytes(raw)
            receipt = views.apply(site)
            self.assertEqual([row['mode'] for row in receipt['pages']], ['linked'])
            first = original.read_bytes()
            first_receipt = (site / views.RECEIPT).read_bytes()
            self.assertEqual(views.apply(site), receipt)
            self.assertEqual((site / views.RECEIPT).read_bytes(), first_receipt)
            with views.validation_view(site) as mirror:
                self.assertEqual((mirror / 'detectors/GeGI_3D/gallery.html').read_bytes(), raw)
                self.assertEqual(original.read_bytes(), first)
            self.assertTrue(views.prepare(site))
            self.assertEqual(original.read_bytes(), raw)
            views.apply(site)
            self.assertEqual(original.read_bytes(), first)
            self.assertEqual((site / views.RECEIPT).read_bytes(), first_receipt)

    def test_linked_landing_pin_survives_discovery(self):
        import site_discovery as discovery
        with tempfile.TemporaryDirectory(dir=views.ROOT / '.local', prefix='canonical-discovery-') as directory:
            site = Path(directory)
            page = site / 'assemblies/index.html'
            page.parent.mkdir(parents=True)
            raw = b'<!doctype html><html><head><title>Assemblies</title></head><body><a href="../viewers/events.html?model=AK02&amp;view=assembly#geometry">Geometry</a></body></html>'
            page.write_bytes(raw)
            views.apply(site)
            pinned = page.read_bytes()
            discovery.assemble(site)
            self.assertEqual(page.read_bytes(), pinned)
            views.validate(site, current=True)
            self.assertTrue(views.prepare(site))
            self.assertEqual(page.read_bytes(), raw)

    def test_interrupted_discovery_recovery_requires_exact_source_and_metadata(self):
        with tempfile.TemporaryDirectory(dir=views.ROOT / '.local', prefix='canonical-recovery-') as directory:
            site = Path(directory)
            page = site / 'assemblies/index.html'
            page.parent.mkdir(parents=True)
            raw = b'<!doctype html><html><head><title>Assemblies</title></head><body><a href="../viewers/events.html?view=assembly#geometry">Geometry</a></body></html>'
            page.write_bytes(raw)
            receipt = views.apply(site)
            discovered = page.read_bytes()
            old_pin = views.direct_links_html(raw, 'assemblies/index.html')
            receipt['pages'][0]['canonical_sha256'] = views.digest(old_pin)
            receipt['generators']['tools/site_canonical_views.py'] = '0' * 64
            (site / views.RECEIPT).write_text(json.dumps(receipt), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Direct-link page changed'):
                views.prepare(site)
            page.write_bytes(discovered.replace(b'>Geometry</a>', b'>Changed science</a>'))
            tampered = page.read_bytes()
            with self.assertRaisesRegex(ValueError, 'existing publication stage'):
                views.recover_discovery_metadata(site)
            with patch.object(views, 'STAGED_ROOT', site), \
                 self.assertRaisesRegex(ValueError, 'beyond exact discovery metadata'):
                views.recover_discovery_metadata(site)
            self.assertEqual(page.read_bytes(), tampered)
            page.write_bytes(discovered)
            with patch.object(views, 'STAGED_ROOT', site):
                recovered = views.recover_discovery_metadata(site)
            self.assertEqual(recovered, [dict(path='assemblies/index.html',
                discovered_sha256=views.digest(discovered), restored_sha256=views.digest(old_pin),
                source_proven=True)])
            self.assertEqual(page.read_bytes(), old_pin)
            self.assertTrue(views.prepare(site))
            self.assertEqual(page.read_bytes(), raw)

    def test_urls_rebase_once_and_saved_payload_stays_exact(self):
        source = b'''<!doctype html><html><head><title>saved</title></head><body>
<a href="../spectra/cs137-10k.html?model=AK02&amp;event=213#tenk-AK02">Spectrum</a>
<script type="application/json">{"original_path":"../saved.json","value":-0.0001234567890123456}</script>
<script>const config={base:'../examples/cs137-10k-geometry/'};const path='../'+name;const destination='../spectra/cs137-10k.html?'+query;fetch('../examples/data.json');</script>
</body></html>'''
        output = views.canonical_html(source, 'viewers/events.html', 'results/cs137-10k/events.html').decode()
        self.assertIn('href="spectra.html?model=AK02&amp;event=213#tenk-AK02"', output)
        self.assertIn("base:'../../examples/cs137-10k-geometry/'", output)
        self.assertIn("path='../../'+name", output)
        self.assertIn("destination='spectra.html?'+query", output)
        self.assertIn("fetch('../../examples/data.json')", output)
        self.assertIn('{"original_path":"../saved.json","value":-0.0001234567890123456}', output)

    def test_teaching_dynamic_links_keep_study_and_data_roots(self):
        script = '''const folder="../"+m.source_folder;link("case-3d","../viewers/events.html?"+query+'&view=positive');link("case-spectrum","cs137-10k.html#tenk-"+c.model);'''
        output = views.rebase_script(script, 'spectra/pipeline.html', 'learn/signals/index.html')
        self.assertIn('folder="../../"+m.source_folder', output)
        self.assertIn('"../../results/cs137-10k/events.html?"+query', output)
        self.assertIn('"../../results/cs137-10k/spectra.html#tenk-"+c.model', output)

    def test_receipt_restores_sources_without_touching_published_hardlinks(self):
        with tempfile.TemporaryDirectory(dir=views.ROOT / '.local', prefix='canonical-contract-') as directory:
            site = Path(directory)
            source = b'<!doctype html><html><head><title>saved</title></head><body><p>original evidence</p></body></html>'
            original = site / 'viewers/events.html'
            original.parent.mkdir(parents=True)
            original.write_bytes(source)
            asset = site / 'viewers/science.json'
            asset.write_bytes(b'{"original_id":213,"signed":-1.2345678901234567}')
            for alias in views.VIEWER_ALIASES:
                (site / alias).write_bytes(source)
            receipt = views.apply(site)
            self.assertEqual(len(receipt['pages']), 3)
            canonical = site / 'results/cs137-10k/events.html'
            canonical_bytes, alias_bytes = canonical.read_bytes(), original.read_bytes()
            with views.validation_view(site) as mirror:
                self.assertEqual((mirror / 'viewers/events.html').read_bytes(), source)
                self.assertFalse((mirror / 'results/cs137-10k/events.html').exists())
                self.assertEqual((mirror / 'viewers/science.json').read_bytes(), asset.read_bytes())
                self.assertEqual(canonical.read_bytes(), canonical_bytes)
                self.assertEqual(original.read_bytes(), alias_bytes)
            views.validate(site, current=True)
            canonical.write_bytes(canonical_bytes + b'changed')
            with self.assertRaisesRegex(ValueError, 'Canonical page changed'):
                views.prepare(site)
            canonical.write_bytes(canonical_bytes)
            self.assertTrue(views.prepare(site))
            self.assertEqual(original.read_bytes(), source)
            self.assertEqual(asset.read_bytes(), b'{"original_id":213,"signed":-1.2345678901234567}')

    def test_alias_runs_one_hop_with_encoded_query_and_fragment(self):
        node = shutil.which('node')
        self.assertTrue(node, 'Existing Node runtime required')
        rows = []
        for old, new in views.CANONICAL_VIEWS.items():
            script = re.search(r'<script>(.*?)</script>', views.alias_html(old, new).decode(), re.S)[1]
            rows.append(dict(script=script, target=views.posixpath.relpath(new, views.posixpath.dirname(old)), view=None))
        for old, view in views.VIEWER_ALIASES.items():
            new = views.CANONICAL_VIEWS['viewers/events.html']
            script = re.search(r'<script>(.*?)</script>', views.alias_html(old, new, view).decode(), re.S)[1]
            rows.append(dict(script=script, target=views.posixpath.relpath(new, views.posixpath.dirname(old)), view=view))
        runtime = '''const vm=require('node:vm'),assert=require('node:assert/strict'),fs=require('node:fs');
for(const row of JSON.parse(fs.readFileSync(0,'utf8'))){
 const search='?study=cs137-10k&model=KMRC01_candidate&variant=KMRC01_candidate&event=26&group=0&encoded=a%20b',hash='#data-files';let result=null;
 const context={location:{search,hash,replace:x=>result=x},document:{getElementById:()=>({})},URLSearchParams};vm.runInNewContext(row.script,context);
 assert.equal(result,row.target+search+(row.view?'&view='+row.view:'')+hash);
}console.log('12 one-hop aliases retain original queries and fragments');'''
        result = subprocess.run([node, '-e', runtime], input=json.dumps(rows), capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_alias_keeps_known_anchor_targets(self):
        source = b'<html><body><section id="tenk-GeRC02"></section><a name="old-event"></a></body></html>'
        output = views.alias_html('spectra/cs137-10k.html', 'results/cs137-10k/spectra.html', raw=source).decode()
        self.assertIn('<span id="tenk-GeRC02"></span>', output)
        self.assertIn('<span id="old-event"></span>', output)

    def test_actual_migrated_spectrum_controller_keeps_canonical_case_links(self):
        site = views.ROOT / 'docs'
        old = 'spectra/cs137-10k.html'
        if (site / views.RECEIPT).is_file():
            raw = views.source_bytes(next(row for row in views.read_receipt(site)['pages'] if row['source'] == old))
        else:
            raw = (site / old).read_bytes()
        output = views.canonical_html(raw, old, 'results/cs137-10k/spectra.html').decode()
        context = json.loads(re.search(r'<script id="spectrum-case-context" type="application/json">(.*?)</script>', output, re.S)[1])
        controller = re.search(r'<script id="spectrum-controls-script">(.*?)</script>', output, re.S)[1]
        original_context = json.loads(re.search(r'<script id="spectrum-case-context" type="application/json">(.*?)</script>', raw.decode(), re.S)[1])
        for model, entry in context.items():
            for key in ('study', 'model', 'variant', 'label'):
                self.assertEqual(entry[key], original_context[model][key])
        runtime = r'''
const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),input=JSON.parse(fs.readFileSync(0,'utf8'));
class Element{constructor(){this.dataset={};this.hidden=false;this.textContent='';this.value='';this.handlers={};}setAttribute(k,v){this[k]=v;}removeAttribute(k){delete this[k];}addEventListener(k,fn){this.handlers[k]=fn;}}
for(const model of Object.keys(input.context)){
 const nodes=new Map(),get=id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);};get('spectrum-case').dataset.prefix='tenk';get('spectrum-case-context').textContent=JSON.stringify(input.context);
 const links=['result','files','events','spectrum'].map(kind=>{const n=new Element();n.dataset.contextLink=kind;n.dataset.baseHref=kind==='events'?'events.html':kind==='spectrum'?'spectra.html':undefined;return n;});
 const variant=input.context[model].variant,event=model==='KMRC01_candidate'?26:213;
 const location=new URL('https://test.invalid/results/cs137-10k/spectra.html?'+new URLSearchParams({study:'cs137-10k',model,variant,event:String(event),group:'0'})+'#tenk-'+model),history={replaceState:(_,__,href)=>{location.href=new URL(href,location).href;}};
 const document={readyState:'loading',getElementById:get,addEventListener(){},querySelectorAll:selector=>selector==='[data-context-link]'?links:[]};
 const c=vm.createContext({document,location,history,URLSearchParams,addEventListener(){}});vm.runInContext(input.controller,c);c.SpectrumUI.installCaseSelection();
 for(const [link,path]of [[links[0],'/results/cs137-10k/'+model+'/charge-readout.html'],[links[1],'/results/cs137-10k/'+model+'/charge-readout.html'],[links[2],'/results/cs137-10k/events.html'],[links[3],'/results/cs137-10k/spectra.html']]){const url=new URL(link.href,location);assert.equal(url.pathname,path);for(const [key,value]of Object.entries({study:'cs137-10k',model,variant,event:String(event),group:'0'}))assert.equal(url.searchParams.get(key),value);}
 assert.equal(new URL(links[2].href,location).searchParams.get('view'),'positive');assert.equal(new URL(links[3].href,location).hash,location.hash);
 assert.equal(new URL(get('spectrum-return-3d').href,location).pathname,'/results/cs137-10k/events.html');
}
console.log('four actual migrated spectrum cases retain canonical cross-view paths and event identities');
'''
        result = subprocess.run([shutil.which('node'), '-e', runtime], input=json.dumps({'context': context, 'controller': controller}), capture_output=True, text=True, timeout=25)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_actual_strip_preview_assignment_resolves_all_saved_images(self):
        site = views.ROOT / 'docs'
        old = 'detectors/GeGI_3D/strip_explorer.html'
        if (site / views.RECEIPT).is_file():
            raw = views.source_bytes(next(row for row in views.read_receipt(site)['pages'] if row['source'] == old))
        else:
            raw = (site / old).read_bytes()
        output = views.canonical_html(raw, old, 'results/gegi-strip-study/index.html').decode()
        data = json.loads(re.search(r'<script id="data" type="application/json">(.*?)</script>', output, re.S)[1])
        statement = re.search(r"\$\('preview'\)\.src=[^;]+;", output)[0]
        runtime = r'''
const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path'),input=JSON.parse(fs.readFileSync(0,'utf8'));
for(const preview of input.previews){const image={},c=vm.createContext({current:{preview},$:()=>image});vm.runInContext(input.statement,c);const url=new URL(image.src,'https://test.invalid/results/gegi-strip-study/index.html');assert.equal(url.pathname,'/detectors/GeGI_3D/'+preview);assert.ok(fs.existsSync(path.join(input.site,url.pathname)));}
console.log('all saved strip previews resolve to their original detector assets');
'''
        result = subprocess.run([shutil.which('node'), '-e', runtime], input=json.dumps({'previews': [row['preview'] for row in data['events']], 'statement': statement, 'site': str(site)}), capture_output=True, text=True, timeout=25)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
