"""Display relocation and saved-selection contracts; no scientific computation."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

import site_canonical_views as views


class CanonicalViews(unittest.TestCase):
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
