"""Saved GeGI path identity, units and browser contracts; no physics calls."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which('node') or 'C:/Program Files/nodejs/node.exe'
SCRIPT = ROOT/'tools/gegi_assembly.js'


class SavedGeGIPaths(unittest.TestCase):
    def node(self, code):
        result = subprocess.run([NODE], input=code, text=True, capture_output=True, cwd=ROOT)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)

    def test_raw_and_normalized_segments_preserve_units_rows_and_gaps(self):
        self.node(r"""
const assert=require('node:assert/strict'),G=require('./tools/gegi_assembly.js');
const id={source_group:'fixture',chunk_index:3,raw_primary_id:9,pulse_group_id:0,campaign_initial_id:39};
const base={evtid:9,raw_row_index:7,trackid:2,parent_trackid:1,particle:22,xloc:.003,yloc:.004,zloc:.005};
const step={...base,edep:12,time:4,xloc_pre:.001,yloc_pre:.002,zloc_pre:.003,xloc_post:.003,yloc_post:.004,zloc_post:.005};
const raw={original_identity:id,radiation:{event_id:9,tables:{tracks:[base],'stp/germanium':[step,{...step,raw_row_index:8,xloc_pre:.02,xloc_post:.021}]}}};
G.validatePayload({kind:'gegi_saved_path_display_v1',records:[raw]});
const p=G.pathPrimitives(raw);
assert.equal(p.segments.length,2);assert.deepEqual(p.segments[0].a,[1,2,3]);assert.deepEqual(p.segments[0].b,[3,4,5]);
assert.deepEqual(p.segments[1].a,[20,2,3]);assert.equal(p.segments[1].row.raw_row_index,8);assert.deepEqual(p.deposits[0].p,[3,4,5]);
const saved={pre_mm:[1,2,3],post_mm:[3,4,5],position_mm:[2.5,4,5],energy_keV:12,time_ns:4,raw_row_index:7,track_id:2,parent_track_id:1,particle_pdg:22};
const normalized={original_identity:id,radiation:{event_id:9,scope:'positive_energy_Ge_scored_step_chords_only',segments:[saved],births:[]}};
G.validatePayload({kind:'gegi_saved_path_display_v1',records:[normalized]});
const q=G.pathPrimitives(normalized);assert.deepEqual(q.segments[0].a,[1,2,3]);assert.deepEqual(q.deposits[0].p,saved.position_mm);assert.equal(q.births.length,0);
assert.equal(q.segments[0].row.raw_row_index,7);assert.equal(saved.edep,undefined);
const bad=structuredClone(normalized);bad.radiation.segments[0].post_mm[2]=null;
assert.throws(()=>G.validatePayload({kind:'gegi_saved_path_display_v1',records:[bad]}),/Invalid saved/);
bad.radiation.segments[0].post_mm[2]=5;bad.radiation.scope='all_paths';
assert.throws(()=>G.validatePayload({kind:'gegi_saved_path_display_v1',records:[bad]}),/scope/);
const ancestry=structuredClone(raw);ancestry.radiation.tables['stp/germanium'][0].parent_trackid=99;
assert.throws(()=>G.validatePayload({kind:'gegi_saved_path_display_v1',records:[ancestry]}),/ancestry/);
""")

    def test_original_signal_identity_is_required_and_stale_loads_clear(self):
        self.node(r"""
const assert=require('node:assert/strict'),G=require('./tools/gegi_assembly.js');
const id={source_group:'fixture',chunk_index:3,raw_primary_id:9,pulse_group_id:0,campaign_initial_id:39};
const record={original_identity:id,radiation:{event_id:9,scope:'positive_energy_Ge_scored_step_chords_only',segments:[],births:[]},signal_event:{original_identity:{...id},reconstruction:{paired_site_hypotheses:[]}}};
const p={kind:'gegi_saved_path_display_v1',records:[record]};G.validatePayload(p);
record.signal_event.original_identity.pulse_group_id=1;assert.throws(()=>G.validatePayload(p),/identities differ/);
record.signal_event.original_identity.pulse_group_id=0;record.signal_event.original_identity.campaign_initial_id=49;assert.throws(()=>G.validatePayload(p),/campaign_initial_id/);
record.signal_event.original_identity.campaign_initial_id=39;
Object.defineProperty(record.signal_event,'sites',{get(){throw Error('truth sites must not be read');}});
assert.deepEqual(G.reconstructedSites(record),[]);
(async()=>{let finish,fail,clears=0,shown=[];const gate=G.selectionGate(()=>clears++);
const old=gate.run(()=>new Promise(resolve=>finish=resolve),v=>shown.push(v),e=>shown.push(e.message));
await gate.run(async()=>2,v=>shown.push(v),()=>{});finish(1);await old;assert.deepEqual(shown,[2]);
const late=gate.run(()=>new Promise((resolve,reject)=>fail=reject),v=>shown.push(v),e=>shown.push(e.message));
gate.invalidate();fail(Error('obsolete failure'));await late;assert.deepEqual(shown,[2]);assert.equal(clears,4);
})().catch(e=>{console.error(e);process.exitCode=1;});
""")

    def test_browser_draws_independent_chords_and_mounts_exact_saved_signal(self):
        self.node(r"""
const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');
class Element{constructor(){this.children=[];this.style={};this.checked=false;this.hidden=false;this.clientWidth=800;this.clientHeight=500;this.value='';}append(...v){this.children.push(...v);}replaceChildren(...v){this.children=v;}setAttribute(){}addEventListener(){}setPointerCapture(){}}
const nodes=new Map(),get=id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);};
const strokes=[],arcs=[],ctx={setTransform(){},clearRect(){strokes.length=arcs.length=0;},beginPath(){},moveTo(x,y){this.start=[x,y];},lineTo(x,y){this.end=[x,y];},stroke(){strokes.push({start:this.start,end:this.end,color:this.strokeStyle});},arc(x,y,r){arcs.push([x,y,r]);},fill(){},fillText(){},closePath(){},strokeRect(){}};
get('canvas').getContext=()=>ctx;
get('scene-data').textContent=JSON.stringify({volumes:[{name:'ge',material:'Ge',label:'Ge',basis:'fixture',color:'#ccc',vertices_global_mm:[[-1,-1,-1],[1,-1,1],[0,1,0]],triangles:[[0,1,2]],wireframe:[[0,1],[1,2],[2,0]],section_y0_mm:[]}]});
get('event-data').textContent='';get('steps').checked=get('deposits').checked=true;
const doc={getElementById:get,createElement:()=>new Element(),querySelectorAll:()=>[]},mounts=[];
const sandbox={document:doc,devicePixelRatio:1,ResizeObserver:class{observe(){}},console,GeGISignalJourney:{mount(element,payload){mounts.push(payload);return{destroy(){}};}}};
vm.runInNewContext(fs.readFileSync('tools/gegi_assembly.js','utf8'),sandbox);
const id={source_group:'fixture',chunk_index:3,raw_primary_id:9,pulse_group_id:0,campaign_initial_id:39};
const common={energy_keV:12,time_ns:4,parent_track_id:1,particle_pdg:22};
const record={label:'Actual ID fixture',original_identity:id,radiation:{event_id:9,scope:'positive_energy_Ge_scored_step_chords_only',segments:[{...common,pre_mm:[0,0,0],post_mm:[1,0,0],track_id:2,raw_row_index:7},{...common,pre_mm:[9,0,0],post_mm:[10,0,0],track_id:2,raw_row_index:8}],births:[]},signal_event:{original_identity:{...id},channels:[{contact_id:1,trace:{time_ns:[0,1],charge_fC:[0,-2]}}],reconstruction:{status:'rejected',reason:'fixture no cone'}}};
sandbox.GeGIAssemblyEvents.setPayload({kind:'gegi_saved_path_display_v1',records:[record]});
assert.equal(strokes.length,8,'three mesh edges + three axes + exactly two original step chords');
assert.equal(strokes.filter(s=>s.color==='#6ee4ff').length,2);assert.equal(arcs.length,2);
assert.equal(mounts.length,1);assert.equal(mounts[0].groups['Actual ID fixture'].representative,record.signal_event);
assert.match(get('event-identity').textContent,/campaign initial 39.*raw primary 9.*pulse group 0/);
assert.match(get('event-status').textContent,/positive-energy Ge.*passive-material and zero-energy steps are absent/);
assert.equal(get('births').checked,false);assert.equal(get('reconstructed').checked,false);assert.equal(get('journey-link').hidden,false);
assert.equal(get('signal-journey').hidden,false);assert.equal(get('reconstructed-layer').hidden,false);
get('reconstructed').checked=true;
sandbox.GeGIAssemblyEvents.setPayload({kind:'gegi_saved_path_display_v1',records:[{...record,signal_event:null}]});
assert.equal(mounts.length,1);assert.equal(get('signal-journey').hidden,true);assert.equal(get('journey-link').hidden,true);
assert.equal(get('reconstructed').checked,false);assert.equal(get('reconstructed').disabled,true);
assert.equal(get('reconstructed-layer').hidden,true);assert.equal(get('reconstructed-key').hidden,true);
assert.match(get('event-status').textContent,/Radiation-only sample; no saved signal counterpart/);
""")

    def test_default_assembly_describes_radiation_only_samples_and_links_the_full_study(self):
        template=(ROOT/'tools/gegi_assembly.html').read_text(encoding='utf-8')
        self.assertIn('four built-in samples',template)
        self.assertIn('<strong>radiation-only</strong>',template)
        self.assertIn('../../results/gegi-campaign/index.html#event-journey',template)
        self.assertNotIn('follow the same pulse group through its electrode signals',template)
        self.assertIn('id="reconstructed-layer" hidden',template)

    @unittest.skipUnless((ROOT/'.local/gegi-10m/reconstruction-v3/assembly-events.json').is_file(),
                         'Saved local derived path display is not in clean student clones')
    def test_actual_saved_display_has_original_nonzero_rows_and_no_fabricated_path(self):
        path = ROOT/'.local/gegi-10m/reconstruction-v3/assembly-events.json'
        self.node("const fs=require('node:fs'),assert=require('node:assert/strict'),G=require('./tools/gegi_assembly.js');"
                  "const data=JSON.parse(fs.readFileSync("+json.dumps(str(path))+",'utf8'));"
                  "G.validatePayload(data);assert.equal(data.records.length,4);"
                  "for(const r of data.records){const p=G.pathPrimitives(r);"
                  "assert.equal(p.segments.length,r.radiation.segments.length);"
                  "assert(p.segments.length>0);assert.equal(p.births.length,0);"
                  "for(let i=0;i<p.segments.length;i++){assert.deepEqual(p.segments[i].a,r.radiation.segments[i].pre_mm);"
                  "assert.deepEqual(p.segments[i].b,r.radiation.segments[i].post_mm);"
                  "assert.equal(p.segments[i].row.raw_row_index,r.radiation.segments[i].raw_row_index);}}")


if __name__ == '__main__':
    unittest.main()
