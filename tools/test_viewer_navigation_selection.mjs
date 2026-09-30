// Execute the actual adapted scripts with real saved payloads and a minimal DOM.
// This is an async selection regression, not a browser/layout acceptance test.
import fs from 'node:fs';import path from 'node:path';import vm from 'node:vm';
import {webcrypto} from 'node:crypto';import assert from 'node:assert/strict';
const preview=process.argv[2]||'.local/viewer-navigation-v1/implementation/preview';
class Element {
  constructor(tag='div'){this.tagName=tag;this.children=[];this._value='';this.checked=true;this.disabled=false;this.textContent='';this.dataset={};this.style={};this.clientWidth=800;this.clientHeight=600;this.open=false;this.attrs={};}
  get value(){return this._value}set value(v){this._value=String(v)}
  append(...els){this.children.push(...els)}replaceChildren(...els){this.children=[...els];this.textContent='';if(this.tagName==='select')this.value=els[0]?.value??'';}
  setAttribute(k,v){this.attrs[k]=v}removeAttribute(k){delete this.attrs[k];if(k==='href')delete this.href}
  addEventListener(){}getContext(){return new Proxy({}, {get:(t,k)=>t[k]||(()=>{}),set:(t,k,v)=>(t[k]=v,true)})}
}
async function viewer(route,query){
  const html=fs.readFileSync(path.join(preview,'viewers',route+'.html'),'utf8'),els=new Map();
  for(const m of html.matchAll(/<(\w+)\b[^>]*id="([^"]+)"[^>]*>/g))els.set(m[2],new Element(m[1]));
  els.get('model').value='AK02';els.get('category')&&(els.get('category').value='all');
  els.get('reciprocal').dataset={route:route==='ge-positive'?'geant4-assembly.html':'ge-positive.html',kind:route==='ge-positive'?'overlay':'assembly'};
  const requests=[],context={URLSearchParams,TextDecoder,Uint8Array,Blob,Response,DecompressionStream,crypto:webcrypto,devicePixelRatio:1,
    location:{search:query,pathname:'/viewers/'+route+'.html'},history:{replaceState(){}},ResizeObserver:class {observe(){}},
    document:{getElementById:id=>els.get(id),createElement:tag=>new Element(tag),querySelectorAll:()=>[]},
    fetch:async url=>{requests.push(url);assert.ok(url.startsWith('../examples/'),'Unexpected data path '+url);const bytes=fs.readFileSync(path.resolve('docs/viewers',url));return new Response(bytes);}};
  const c=vm.createContext(context),run=code=>vm.runInContext(code,c);
  for(const m of html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g))run(m[1]);
  const until=async expr=>{for(let n=0;n<500;n++){if(run(expr))return;await new Promise(r=>setTimeout(r,10));}throw Error('Timeout '+expr+' / '+els.get('status').textContent)};
  await until("manifest!==null && (selected!==null || document.getElementById('status').textContent.startsWith('Unavailable:') || navigation.invalid!=='')");
  return {run,until,els,requests};
}
const results=[];
for(const [model,id] of [['AK02',213],['SAP22',74]]){
  let v=await viewer('ge-positive',`?model=${model}&event=${id}&group=0`);
  assert.equal(v.run('selected.event_id'),id);assert.equal(v.run('selectedGroup.group_id'),0);assert.equal(v.run('activeModel'),model);
  const missing=v.run("Object.keys(data.categories).find(k=>!selectedGroup.categories.includes(k))");
  v.els.get('category').value=missing;v.run('filterCategory()');await v.until("$('status').textContent.startsWith('Unavailable:')");assert.equal(v.run('selected'),null);
  assert.equal(v.run('navigation.event'),id);v.els.get('category').value='all';v.run('filterCategory()');await v.until('selected!==null');assert.equal(v.run('selected.event_id'),id);
  await v.run(`selectEvent(${id},999)`);assert.equal(v.run('selected'),null);assert.equal(v.run('navigation.group'),999);
  await v.run(`selectEvent(${id},0)`);assert.equal(v.run('selectedGroup.group_id'),0);
  for(const e of [0,9999]){await v.run(`selectEvent(${e},0)`);assert.equal(v.run('selected'),null);assert.equal(v.run('navigation.event'),e);}
  for(const proof of v.run('data.evidence'))for(const group of proof.groups){await v.run(`selectEvent(${proof.event_id},${group.group_id})`);assert.equal(v.run('selectedGroup.group_id'),group.group_id);assert.equal(v.run('selected.event_id'),proof.event_id);}
  results.push({model,all_saved_groups:v.run('data.evidence.reduce((n,e)=>n+e.groups.length,0)'),unavailable_and_category_misses:true});
  v=await viewer('geant4-assembly',`?model=${model}&event=${id}&group=0`);assert.equal(v.run('selected.event_id'),id);assert.ok(v.els.get('identity').textContent.includes('return-navigation context only'));
  for(const e of [0,9999,id]){await v.run(`selectEvent(${e})`);assert.equal(v.run('selected.event_id'),e);}
  assert.equal(v.run('navigation.group'),null);
  v.run(`globalThis.originalFetch=fetch;globalThis.pending=[];globalThis.fetch=(url)=>url.includes('/SAP22/')?new Promise((r,j)=>pending.push({r,j,url})):originalFetch(url);`);
  v.els.get('model').value='SAP22';v.run("selectModel('SAP22')");await v.until('pending.length>0');v.els.get('model').value='AK02';await v.run("selectModel('AK02')");await v.until('selected!==null');
  await v.run('Promise.all(pending.splice(0).map(async p=>p.r(await originalFetch(p.url))))');await new Promise(r=>setTimeout(r,50));assert.equal(v.run('model'),'AK02');assert.equal(v.run('selected.event_id'),id);
  v.els.get('model').value='SAP22';v.run("selectModel('SAP22')");await v.until('pending.length>0');v.els.get('model').value='AK02';await v.run("selectModel('AK02')");await v.until('selected!==null');v.run("pending.splice(0).forEach(p=>p.j(Error('intentional stale failure')))");await new Promise(r=>setTimeout(r,50));assert.equal(v.run('selected.event_id'),id);assert.ok(!v.els.get('status').textContent.includes('failed'));
}
for(const route of ['ge-positive','geant4-assembly'])for(const q of ['?event=0','?event=9999','?event=-1','?event=10000','?model=X','?group=0','?event=213&group=1.5']){
  const v=await viewer(route,q);if(q==='?event=0'||q==='?event=9999'){assert.equal(v.run('selected?.event_id??null'),route==='ge-positive'?null:Number(q.split('=')[1]));}else{assert.equal(v.run('selected'),null);assert.ok(v.run('navigation.invalid'));}
}
console.log(JSON.stringify({status:'passed',kind:'real-script minimal-DOM async regression, not a browser',results},null,2));
