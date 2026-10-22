import shutil,subprocess,tempfile,unittest
from pathlib import Path
import ssd_geometry_publication as P
class GeometryPublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.site=Path(self.tmp.name)
        for m in P.MODELS:
            d=self.site/'detectors'/m; (d/'runs/20260922_suite_v3').mkdir(parents=True)
            (d/'index.html').write_text('<html><main><h1>'+m+'</h1></main></html>',encoding='utf-8')
            (d/'runs/20260922_suite_v3/01_geometry.png').write_bytes(b'poster')
        self.source=P.ROOT/'.local/ssd-geometry-v1'
    def test_publish_and_validate(self):
        rows=P.assemble(self.source,self.site); checked=P.validate_site(self.site)
        self.assertEqual(set(rows),set(P.MODELS));self.assertEqual(checked,{m:rows[m]['asset_id'] for m in P.MODELS})
        for m in P.MODELS:
            page=(self.site/'detectors'/m/'index.html').read_text()
            viewer=(self.site/'detectors'/m/'geometry.html').read_text()
            active=P.read(self.site/'detectors'/m/'geometry-active.json')
            scene=P.read(self.site/'detectors'/m/'geometry'/active['asset_id']/'scene.json')
            self.assertEqual(P.canonical_scene_id(scene),active['asset_id'])
            self.assertEqual(page.count('id="ssd-interactive-geometry"'),1)
            self.assertIn('Enable drag rotation',viewer);self.assertIn('target="_top"',viewer);self.assertNotIn('__MODEL__',viewer)
    def test_scene_mutation_is_rejected(self):
        P.assemble(self.source,self.site)
        m='AK02';root=self.site/'detectors'/m/'geometry';asset=next(root.iterdir())
        scene=asset/'scene.json';scene.write_bytes(scene.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError,'scene hash'):P.validate_site(self.site)
    def test_geometry_switch_keeps_task_and_navigation_for_every_model(self):
        for model in P.GC.catalog():
            text=P.viewer_html(model,'0'*64)
            self.assertEqual(text.count('aria-label="Primary"'),1)
            self.assertEqual(text.count('aria-label="Breadcrumb"'),1)
            self.assertEqual(text.count('aria-label="Detector views"'),1)
            for label in ('Overview','Geometry','Saved fields &amp; signals','Model &amp; files'):
                self.assertIn(label,text)
            handler=text[text.index("document.getElementById('model-select').addEventListener"):]
            self.assertIn("encodeURIComponent(e.target.value)+'/geometry.html'",handler)
            self.assertIn('window.top.location.href=destination.href',handler)
            self.assertIn('location.href=destination.href',handler)
            self.assertNotIn("new URL('index.html'",handler)
            self.assertIn('target="_top"',text)
            self.assertIn('Recorded model status:',text)
            if model=='GeRC02':
                self.assertIn('original 30-minute',text)
                self.assertIn('separate Li50min',text)
    def test_repeat_publication_reuses_content_addressed_assets(self):
        first=P.assemble(self.source,self.site); second=P.assemble(self.source,self.site)
        self.assertEqual(first,second); self.assertEqual(P.validate_site(self.site),{m:first[m]['asset_id'] for m in P.MODELS})
        for m in P.MODELS:self.assertEqual(len([p for p in (self.site/'detectors'/m/'geometry').iterdir() if p.is_dir()]),1)
    def test_viewer_axes_scale_and_bounds_use_original_vertices_and_keep_controls(self):
        code=r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('tools/ssd_geometry_viewer.html','utf8').match(/<script>([\s\S]*?)<\/script>/)[1];
const scene={display_note:'fixture',default_view:{rotation_rad:[-.45,.65],zoom:1},layers:[
 {id:'crystal',label:'Crystal',contact:null,vertices_mm:[[-2,-3,0],[2,-3,0],[0,3,10]],faces:[[0,1,2]],display_transform:{scale:[1,1,1],translation_mm:[0,0,0]},style:{rgb:[.5,.5,.5],opacity:1}},
 {id:'contact:9',label:'9 · readout · −879 V',contact:{id:9},vertices_mm:[[-1,0,0],[1,0,0],[0,1,10]],faces:[[0,1,2]],display_transform:{scale:[100,100,100],translation_mm:[1000,1000,1000]},style:{rgb:[1,0,0],opacity:1}}
]};
function sandbox(fails=false){
 const labels=[],nodes=new Map();let document;
 class Element{constructor(){this.children=[];this.style={};this.dataset={readout:'9'};this.handlers={};this.disabled=true;this.hidden=false;this.value='';this.textContent='';}append(...values){this.children.push(...values);}addEventListener(name,handler){this.handlers[name]=handler;}setAttribute(){}setPointerCapture(){}getBoundingClientRect(){return{width:800,height:500};}focus(){document.activeElement=this;}get selectedOptions(){return this.children.filter(e=>e.value===this.value);}}
 const get=id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);};
 const ctx={clearRect(){labels.length=0;},fillRect(){},beginPath(){},moveTo(){},lineTo(){},closePath(){},fill(){},stroke(){},arc(){},fillText(text){labels.push(text);}};get('view').getContext=()=>ctx;
 document={getElementById:get,createElement:()=>new Element(),createTextNode:text=>text,querySelectorAll:selector=>selector.startsWith('.controls')?['reset','zin','zout','isolate','show-all'].map(get):['front','side','top'].map(view=>{const b=get(view);b.dataset.view=view;return b;})};
 const context=vm.createContext({document,devicePixelRatio:1,fetch:async()=>{if(fails)throw Error('fixture unavailable');return{ok:true,json:async()=>scene};},addEventListener(){},URL,location:{href:'https://fixture/detectors/GeGI_3D/geometry.html'},window:{}});
 vm.runInContext(source,context);return{get,labels,context};
}
(async()=>{
 const original=JSON.stringify(scene),test=sandbox();await new Promise(setImmediate);
 assert.deepEqual(JSON.parse(vm.runInContext('JSON.stringify(physicalBounds)',test.context)),{min:[-2,-3,0],max:[2,3,10],extent:[4,6,10]});
 assert.deepEqual(JSON.parse(vm.runInContext('JSON.stringify(center)',test.context)),[0,0,5]);
 assert.match(test.get('physical-bounds').textContent,/x \[-2, 2\].*y \[-3, 3\].*z \[0, 10\].*4 × 6 × 10 mm/);
 assert(['+x','+y','+z'].every(axis=>test.labels.includes(axis)));assert(test.labels.includes('2 mm'));
 assert.equal(vm.runInContext('scaleLength(.9)',test.context),.5);assert.equal(vm.runInContext('scaleLength(245)',test.context),200);
 test.get('activate').handlers.click();assert.equal(test.get('view').style.touchAction,'none');
 test.get('activate').handlers.click();assert.equal(test.get('view').style.touchAction,'pan-y');
 test.get('isolate').handlers.click();assert.match(test.get('status').textContent,/readout.*−879 V/);
 for(const view of ['front','side','top']){test.get(view).handlers.click();assert(test.labels.some(text=>/toward|away/.test(text)));assert(test.labels.some(text=>/ mm$/.test(text)));}
 assert.equal(test.get('poster').hidden,true);assert.equal(JSON.stringify(scene),original);
 const failed=sandbox(true);await new Promise(setImmediate);assert.equal(failed.get('view').hidden,true);assert.equal(failed.get('poster').hidden,false);assert.match(failed.get('status').textContent,/showing saved static geometry/);
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
        result=subprocess.run([shutil.which('node') or 'C:/Program Files/nodejs/node.exe'],input=code,text=True,capture_output=True,cwd=P.ROOT)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
if __name__=='__main__':unittest.main(verbosity=2)
