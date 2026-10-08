'use strict';
const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
class Element{
  constructor(tag){this.tag=tag;this.children=[];this.attributes={};this.style={};this.textContent='';}
  append(...children){this.children.push(...children);}
  replaceChildren(...children){this.children=[...children];}
  setAttribute(name,value){this.attributes[name]=String(value);}
}
const document={createElement:tag=>new Element(tag),createElementNS:(_,tag)=>new Element(tag)};
const context=vm.createContext({document});vm.runInContext(fs.readFileSync(__dirname+'/focused_plots.js','utf8'),context);
const api=context.SavedFocusPlots;
const t=Array.from({length:5002},(_,i)=>i*2),q=[0,100,...Array.from({length:5000},(_,i)=>100+i*1e-9)];
const before=JSON.stringify([t,q]);assert.equal(api.focusEnd(t,q),12);assert.equal(JSON.stringify([t,q]),before);assert.equal(t.at(-1),10002);
assert.equal(api.shaperEnd([0,1000,4900,8000],[0,1,.01,.001],{t:1000,v:1},10000),5194);
// A later retained lobe extends the shaper camera; zero and negative signs are untouched.
assert.equal(api.shaperEnd([0,1000,4900,8000],[0,1,.01,-.02],{t:1000,v:1},10000),8480);
const eion=2.95,factor=1000/eion*1.602176634e-19;
const signedT=[0,2,4,6],signedQ=[0,10,4,-2],unchanged=JSON.stringify([signedT,signedQ]);
const current=api.currentFromCharge(signedT,signedQ,eion,{time_step_ns:2,readout_end_ns:10});
assert.deepEqual(Array.from(current.bin_start_ns),[0,0,2,4,6,8]);
assert.deepEqual(Array.from(current.bin_end_ns),[0,2,4,6,8,10]);
assert.equal(current.values[1],10*factor/2*1e18);assert.ok(current.values[2]<0&&current.values[3]<0);
assert.equal(current.values[4],0);assert.equal(current.values[5],0);
const integrated=current.values.reduce((sum,v,i)=>sum+v*(current.bin_end_ns[i]-current.bin_start_ns[i])*1e-18,0);
assert.ok(Math.abs(integrated-signedQ.at(-1)*factor)<=1e-28);
assert.equal(JSON.stringify([signedT,signedQ]),unchanged);
// An isolated electronics window may end before the untruncated native charge.
const truncated=api.currentFromCharge(signedT,signedQ,eion,{time_step_ns:2,readout_end_ns:4});
assert.equal(truncated.values.length,3);assert.deepEqual(Array.from(truncated.bin_end_ns),[0,2,4]);
const truncatedCharge=truncated.values.reduce((sum,v,i)=>sum+v*(truncated.bin_end_ns[i]-truncated.bin_start_ns[i])*1e-18,0);
assert.ok(Math.abs(truncatedCharge-signedQ[2]*factor)<=1e-28);assert.ok(Math.abs(truncatedCharge-signedQ[3]*factor)>1e-17);
assert.equal(JSON.stringify([signedT,signedQ]),unchanged);
assert.ok(api.currentFromCharge([0,2],[0,0],eion,{time_step_ns:2,readout_end_ns:10}).values.every(v=>v===0));
assert.throws(()=>api.currentFromCharge([0,2,10],[0,1,2],eion,{time_step_ns:2}),/original uniform grid/);
assert.throws(()=>api.currentFromCharge([0,2],[0,null],eion,{time_step_ns:2}),/incomplete/);
assert.throws(()=>api.currentFromCharge([0,2],[0,1],eion,{}),/time step/);
assert.throws(()=>api.currentFromCharge([0,2],[0,1],eion,{time_step_ns:2,readout_end_ns:3}),/window/);

const walk=n=>[n,...n.children.flatMap(walk)],series=(host,name)=>walk(host).find(n=>n.attributes['data-series']===name),range=host=>walk(host).find(n=>n.tag==='small'),button=(host,text)=>walk(host).find(n=>n.tag==='button'&&n.textContent===text);
function render(panel){const host=new Element('div');api.draw(host,[{title:'Signed original-bin current · nA',note:'Saved bins',...panel}]);return host;}
// Observed bug: a bin overlaps the view, but its END timestamp is outside it.
// The old y bounds excluded that bin and drew its current far outside the chart.
const overlap=render({time_ns:[0,10],values:[0,500],bin_start_ns:[0,0],bin_end_ns:[0,10],focus_end_ns:5,full_end_ns:5});
const overlapPath=series(overlap,'current').attributes.d,overlapY=Number(overlapPath.match(/^M[\d.]+,([\d.]+)/)[1]);
assert.ok(overlapY>=26&&overlapY<=214);assert.ok(overlapPath.endsWith('H542'));assert.match(range(overlap).textContent,/1 displayed original bins/);
const contiguous=render({time_ns:[0,2,4],values:[0,5,-6],bin_start_ns:[0,0,2],bin_end_ns:[0,2,4],focus_end_ns:4,full_end_ns:4});
const contiguousPath=series(contiguous,'current').attributes.d;
assert.equal((contiguousPath.match(/M/g)||[]).length,1);assert.equal((contiguousPath.match(/V/g)||[]).length,1);
assert.ok(walk(contiguous).some(n=>n.tag==='text'&&n.textContent==='0'));assert.ok(walk(contiguous).some(n=>n.tag==='text'&&n.textContent==='nA'));
const gapped=render({time_ns:[0,2,8],values:[0,5,6],bin_start_ns:[0,0,6],bin_end_ns:[0,2,8],focus_end_ns:8,full_end_ns:8});
assert.equal((series(gapped,'current').attributes.d.match(/M/g)||[]).length,2);assert.equal((series(gapped,'current').attributes.d.match(/V/g)||[]).length,0);
const lateLobe=render({time_ns:[0,2,100],values:[0,1,-100],bin_start_ns:[0,0,98],bin_end_ns:[0,2,100],focus_end_ns:12,full_end_ns:120});
assert.match(range(lateLobe).textContent,/0–120 ns/);
assert.throws(()=>render({time_ns:[0,2],values:[0,null],bin_start_ns:[0,0],bin_end_ns:[0,2],focus_end_ns:2,full_end_ns:2}),/Invalid saved sample/);
const clipped=render({title:'Signed charge · keV',time_ns:[0,2,100],values:[0,1,1000],focus_end_ns:2,full_end_ns:100});
assert.equal((series(clipped,'samples').attributes.d.match(/L/g)||[]).length,1);
const clippedLastY=Number(series(clipped,'samples').attributes.d.match(/L[\d.]+,([\d.]+)$/)[1]);
assert.ok(clippedLastY>=26&&clippedLastY<60); // Outside sample cannot set the focus y scale.
button(clipped,'Full saved window').onclick();assert.equal((series(clipped,'samples').attributes.d.match(/L/g)||[]).length,2);

// Read-only comparison against every retained original bin in the real saved
// gamma data. These are display contracts, not a rerun of SSD or electronics.
const saved=JSON.parse(fs.readFileSync(__dirname+'/../docs/examples/gamma-native/data.json','utf8'));
let cases=0,bins=0;
for(const model of saved.science.models){
  const settings={ionisation_energy_eV:model.report.ionisation_energy_eV,time_step_ns:model.report.calibration.time_step_ns};
  for(const record of model.report.cases){
    if(!record.readout)continue;
    const input=record.charge_input,rd=record.readout,trace=rd.trace,snapshot=JSON.stringify(record);
    const full=api.currentFromCharge(input.time_since_initial_primary_ns,input.induced_equivalent_energy_keV,settings.ionisation_energy_eV,{...settings,readout_end_ns:rd.readout_end_ns});
    assert.equal(full.values.length,rd.original_sample_count);
    for(let i=0;i<trace.time_ns.length;i++){
      const k=Math.round(trace.time_ns[i]/settings.time_step_ns);
      assert.equal(full.bin_start_ns[k],trace.current_bin_start_ns[i]);assert.equal(full.bin_end_ns[k],trace.current_bin_end_ns[i]);
      assert.equal(full.values[k],trace.current_nA[i],`${model.model_id}/${record.initial_primary_id} original current bin ${i}`);bins++;
    }
    const charge=full.values.reduce((sum,value)=>sum+value,0)*settings.time_step_ns*1e-18;
    assert.ok(Math.abs(charge-rd.current_balance.charge_change_C)<=Math.max(rd.current_balance.tolerance_C,1e-30));
    assert.equal(JSON.stringify(record),snapshot);cases++;
    if(model.model_id==='AK02'&&record.initial_primary_id===11){
      const panels=api.gammaPanels(record,model.display_edges['11'],settings),host=new Element('div');api.draw(host,panels);
      const currentFigure=host.children[1],currentRange=range(currentFigure).textContent;
      assert.match(currentRange,/19 displayed original bins/);assert.equal((series(currentFigure,'current').attributes.d.match(/M/g)||[]).length,1);
      assert.ok(panels[2].note.includes('negative preamp voltage'));button(currentFigure,'Full saved window').onclick();assert.match(range(currentFigure).textContent,/10001 displayed original bins/);
    }
  }
}
assert.equal(cases,40);
console.log(`Saved plot contracts passed: signed/zero charge conservation, gaps/steps, clipping, cameras and ${bins} original-bin exact comparisons across ${cases} saved gamma cases.`);
