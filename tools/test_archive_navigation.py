"""Archive and fixed-route return contracts; no site build or physics."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest
from unittest.mock import patch

import site_chrome
import site_routes as routes


class ArchiveNavigation(unittest.TestCase):
    def test_four_spectra_archive_status_matches_actual_publication(self):
        import spectrum_display as display
        from ring_site import cases
        site=Path(__file__).resolve().parents[1]/'docs'
        import result_web_delivery as delivery
        manifest_path=site/delivery.PREFIX/'manifest.json'
        self.assertEqual(delivery.file_stamp(manifest_path)['sha256'],delivery.SOURCE_MANIFEST_SHA256)
        # Public reports already have a reversible outer frame. This focused
        # display test supplies their exact pinned manifest without restoring
        # or copying a whole site merely to read the unchanged numeric inputs.
        with patch('ring_site.ring_manifest',return_value=json.loads(manifest_path.read_bytes())):
            rows=cases(site)
            specs=display.tenk_specs(site)
            page=display.four_detector_spectra(site,specs)
        self.assertEqual(display.embedded_specs(page),specs)
        for row in rows:
            archive='../'+row['base']+'/response/ledgers.zip'
            if row['model'] in ('GeRC02','KMRC01_candidate'):
                self.assertNotIn('href="'+archive+'"',page)
            else:
                self.assertIn('href="'+archive+'">Complete ledger archive</a>',page)
        self.assertEqual(page.count('Complete ledger archive: retained locally; not available on this website.'),2)

    def test_saved_case_return_validates_identity_and_carries_late_same_model_link(self):
        paths = ['detectors/GeRC02/index.html','assemblies/lbnl/index.html','methods/index.html']
        scripts = {path:re.search(r'<script data-saved-case-return>(.*?)</script>',routes.page_navigation(path),re.S)[1] for path in paths}
        node=shutil.which('node')
        self.assertTrue(node,'Existing Node runtime required')
        code = r'''
const assert=require('node:assert/strict'),vm=require('node:vm');
const scripts=__SCRIPTS__;
function setup(path,search){
 const callbacks={},box={hidden:true},link={removeAttribute(key){delete this[key];}},tabs=[{href:'https://test.invalid/END2END_Ge_Simulation/detectors/GeRC02/index.html'},{href:'https://test.invalid/END2END_Ge_Simulation/detectors/GeRC02/technical.html'},{href:'https://test.invalid/END2END_Ge_Simulation/detectors/AK02/index.html'}],late=[];
 const location={search,href:'https://test.invalid/END2END_Ge_Simulation/'+path+search,origin:'https://test.invalid'};
 const document={getElementById:id=>id==='saved-case-return'?box:link,querySelectorAll:()=>tabs.concat(late)};
 vm.runInNewContext(scripts[path],{document,location,URL,URLSearchParams,encodeURIComponent,addEventListener:(name,cb)=>callbacks[name]=cb});
 return {box,link,tabs,late,callbacks,location};
}
const query='?study=cs137-10k&model=GeRC02&variant=GeRC02_Li50min&event=61&group=0';
for(const path of Object.keys(scripts)){
 const s=setup(path,query);assert.equal(s.box.hidden,false);assert.match(s.link.textContent,/GeRC02 · Li50min \/ primary 61 \/ group 0 charge & readout/);
 assert.equal(new URL(s.link.href).pathname,'/END2END_Ge_Simulation/results/cs137-10k/GeRC02/charge-readout.html');assert.equal(new URL(s.link.href).search,query);
 assert.equal(new URL(s.tabs[0].href).search,query);assert.equal(new URL(s.tabs[1].href).search,query);assert.equal(new URL(s.tabs[2].href).search,'');
 s.late.push({href:'https://test.invalid/END2END_Ge_Simulation/detectors/GeRC02/technical.html#run-variant'});s.callbacks.DOMContentLoaded();
 assert.equal(new URL(s.late[0].href).search,query);assert.equal(new URL(s.late[0].href).hash,'#run-variant');
}
for(const search of ['?study=cs137-1m&model=GeRC02&variant=GeRC02_Li50min',query+'&model=AK02',query+'&return=https://external.invalid',query.replace('Li50min','Li30min'),query.replace('event=61&',''),query.replace('event=61','event=10000'),query.replace('event=61','event=1.5'),query.replace('event=61','event=-1')]){
 const s=setup('methods/index.html',search);assert.equal(s.box.hidden,true);assert.equal(s.link.href,undefined);assert.ok(s.tabs.every(t=>new URL(t.href).search===''));
}
const mismatch=setup('detectors/GeRC02/index.html','?study=cs137-10k&model=AK02&variant=AK02&event=61');assert.equal(mismatch.box.hidden,true);
for(const [model,variant]of Object.entries({AK02:'AK02',SAP22:'SAP22',GeRC02:'GeRC02_Li50min',KMRC01_candidate:'KMRC01_candidate'})){
 const s=setup('methods/index.html','?study=cs137-10k&model='+model+'&variant='+variant);assert.equal(s.box.hidden,false);assert.equal(new URL(s.link.href).pathname,'/END2END_Ge_Simulation/results/cs137-10k/'+model+'/charge-readout.html');
}
console.log('fixed-route return identities and late detector links passed');
'''.replace('__SCRIPTS__',json.dumps(scripts))
        result=subprocess.run([node,'-e',code],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertNotIn('data-saved-case-return',routes.page_navigation('results/cs137-10k/events.html'))

    def test_assembly_relations_use_maintained_prose_and_keep_saved_payload(self):
        source=('<html><body><header><p><a href="../../results/gegi-campaign/index.html">GeGI saved results</a> · '
                '<a href="../../detectors/GeGI_3D/index.html">GeGI detector</a></p></header><main>'
                '<h2>Geometry and saved radiation steps</h2><p>The four built-in samples are radiation-only. '
                'Open <a href="../../results/gegi-campaign/index.html#journey">full GeGI study</a>.</p>'
                '<div class="bar" aria-label="Camera controls"></div><details id="event-record-panel"></details>'
                '<script type="application/json">{"event":26,"position_mm":[-1.2345678901234567,0,5.5]}</script>'
                '</main></body></html>')
        result=site_chrome.assembly_html(source,'assemblies/gegi/index.html')
        self.assertIn('Four independent GeGI acquisitions: signals and conditional imaging',result)
        self.assertIn('1,000,000 initial records across those acquisitions',result)
        self.assertIn('different historical library replay: 6.25 s',result)
        self.assertIn('electronics reset between windows',result)
        self.assertNotIn('full GeGI study',result)
        self.assertIn(re.search(r'<script type="application/json">.*?</script>',source)[0],result)
        self.assertEqual(result,site_chrome.assembly_html(result,'assemblies/gegi/index.html'))


if __name__ == '__main__':
    unittest.main()
