// Current generated reader, real immutable AK/SAP data, explicit mock ring data.
// Logic/contracts only: no browser, science, native inspector or exporter runs.
import fs from 'node:fs';import path from 'node:path';import vm from 'node:vm';
import zlib from 'node:zlib';import {createHash,webcrypto} from 'node:crypto';import assert from 'node:assert/strict';
const site=path.resolve(process.argv[2]),root=process.cwd(),html=fs.readFileSync(path.join(site,'viewer-source.html'),'utf8');
const base='../examples/cs137-10k-rings/',manifest=JSON.parse(fs.readFileSync(path.join(site,'examples/cs137-10k-rings/manifest.json'),'utf8'));
const sha=b=>createHash('sha256').update(b).digest('hex');
let scalars=0;
function exact(a,b,label='saved'){
  if(b===null||typeof b!=='object'){assert.ok(Object.is(a,b),label);scalars++;return;}
  assert.equal(Array.isArray(a),Array.isArray(b),label);assert.deepEqual(Object.keys(a).sort(),Object.keys(b).sort(),label);
  for(const key of Object.keys(b))exact(a[key],b[key],label+'.'+key);
}
class Element{
  constructor(tag='div'){this.tagName=tag;this.children=[];this._value='';this.checked=false;this.disabled=false;this.textContent='';this.dataset={};this.style={};this.clientWidth=800;this.clientHeight=600;this.open=false;this.attrs={};}
  get value(){return this._value;}set value(v){this._value=String(v);}
  append(...els){this.children.push(...els);}replaceChildren(...els){this.children=[...els];this.textContent='';if(this.tagName==='select')this.value=els[0]?.value??'';}
  setAttribute(k,v){this.attrs[k]=v;}removeAttribute(k){delete this.attrs[k];if(k==='href')delete this.href;}
  addEventListener(){}setPointerCapture(){}
  getContext(){return new Proxy({}, {get:(t,k)=>t[k]||(()=>{}),set:(t,k,v)=>(t[k]=v,true)});}
}
async function viewer(query,options={}){
  const els=new Map();for(const m of html.matchAll(/<(\w+)\b[^>]*id="([^"]+)"[^>]*>/g)){
    const e=new Element(m[1]);e.checked=/\bchecked\b/.test(m[0]);e.disabled=/\bdisabled\b/.test(m[0]);els.set(m[2],e);}
  els.get('category').value='all';const location={pathname:'/viewers/events.html',search:query},requests=[],calls=[],listeners=new Map();
  const move=url=>{const u=new URL(url,'https://test.invalid');location.pathname=u.pathname;location.search=u.search;};
  const history={state:null,pushState(state,_title,url){this.state=state;calls.push({kind:'push',state,url});move(url);},replaceState(state,_title,url){this.state=state;calls.push({kind:'replace',state,url});move(url);}};
  const realFetch=async url=>{
    assert.ok(url.startsWith('../examples/'),'unexpected '+url);
    const saved=url.startsWith(base)?site:path.join(root,'docs'),file=path.resolve(saved,'viewers',url);
    assert.ok(file.startsWith(path.join(saved,'examples')+path.sep),'escaped path');return new Response(fs.readFileSync(file));};
  let intercept=options.fetch;
  const c=vm.createContext({URL,URLSearchParams,TextDecoder,Uint8Array,Blob,Response,DecompressionStream:options.decoder||DecompressionStream,
    crypto:webcrypto,devicePixelRatio:1,location,history,ResizeObserver:class{observe(){}},addEventListener:(name,fn)=>listeners.set(name,fn),
    document:{getElementById:id=>els.get(id),createElement:tag=>new Element(tag),querySelectorAll:()=>[]},
    fetch:async url=>{requests.push(url);return intercept?intercept(url,realFetch):realFetch(url);}});
  const run=code=>vm.runInContext(code,c);for(const m of html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/g)){
    run(m[2]);if(m[1].includes('viewer-config')){if(options.noRings)run('delete VIEWER_CONFIG.models');if(options.setup)options.setup(run);}}
  await run('unifiedViewer.ready');
  return {run,state:()=>run('unifiedViewer.getState()'),els,requests,calls,location,history,listeners,
    setFetch:fn=>{intercept=fn;},until:async predicate=>{for(let n=0;n<500;n++){if(predicate())return;await new Promise(r=>setTimeout(r,5));}throw Error('timeout '+els.get('status').textContent);}};
}
function checkIdentity(v,model,event,group,view){const s=v.state();assert.equal(s.requested.model,model);assert.equal(s.requested.event,event);assert.equal(s.requested.group,group);assert.equal(s.requested.view,view);}
function fold(v){v.els.get('recordPanel').open=true;v.els.get('evidencePanel').open=true;v.els.get('recordPanel').ontoggle();}
function ringPrimary(model,id){const e=manifest.models[model],s=JSON.parse(fs.readFileSync(path.join(site,'examples/cs137-10k-rings',e.scene),'utf8')),index=s.event_index.chunks[Math.floor(id/100)];
  return JSON.parse(fs.readFileSync(path.join(site,'examples/cs137-10k-rings',model,index.file),'utf8')).events[id-index.first];}
let groups=0;
for(const name of ['GeRC02','KMRC01_candidate']){
  const v=await viewer('?model='+name+'&event=42&group=0&view=positive');fold(v);checkIdentity(v,name,42,0,'positive');
  assert.deepEqual(v.els.get('model').children.map(e=>e.value),['AK02','SAP22','GeRC02','KMRC01_candidate']);
  assert.equal(v.state().scene.model,name);assert.equal(v.state().overlayCount,3);
  const e=manifest.models[name],data=JSON.parse(zlib.gunzipSync(fs.readFileSync(path.join(site,'examples/cs137-10k-rings',e.selected))));
  for(const proof of data.evidence)for(const group of proof.groups){
    await v.run('selectEvent('+proof.event_id+','+group.group_id+')');checkIdentity(v,name,proof.event_id,group.group_id,'positive');
    exact(v.state().primary,ringPrimary(name,proof.event_id));exact(v.state().group,group);exact(JSON.parse(v.els.get('records').textContent),ringPrimary(name,proof.event_id));
    exact(JSON.parse(v.els.get('evidenceRaw').textContent).event,proof);groups++;}
  assert.equal(v.els.get('savedResponse').href,'../results/cs137-10k/'+name+'/charge-readout.html');assert.equal(v.els.get('savedResponseReport').href,v.els.get('savedResponse').href+'#data-files');
  assert.equal(v.els.get('savedSignals').href,base+name+'/response/signals.csv');assert.equal(v.els.get('savedCurrent').href,base+name+'/response/readout-input.csv');
  assert.match(v.els.get('modelNotes').textContent,name==='GeRC02'?/original 30 min.*independent 50 min/:/candidate.*signed and negative.*fixed −1.*separate negative injection/);
  assert.ok(Object.is(v.state().primary.tables['stp/germanium'][0].xloc,-0));
  await v.run('selectEvent(42,999)');checkIdentity(v,name,42,999,'positive');assert.equal(v.state().group,null);assert.equal(v.state().overlayCount,3);
  await v.run('selectEvent(42,0)');v.els.get('category').value='compton2';await v.run('filterCategory()');
  checkIdentity(v,name,42,0,'positive');assert.equal(v.state().group,null);assert.equal(v.state().overlayCount,3);
  v.els.get('category').value='all';await v.run('filterCategory()');assert.equal(v.state().group.group_id,0);
  for(const id of [0,9999]){
    await v.run('selectEvent('+id+')');checkIdentity(v,name,id,id===9999?0:null,'positive');exact(v.state().primary,ringPrimary(name,id));
    if(id===0){assert.equal(v.state().group,null);assert.equal(v.state().primary.tables['stp/germanium'].length,0);}}
  await v.run('requestSelection({model:'+JSON.stringify(name)+',event:42,group:7,view:"assembly",invalid:""})');
  checkIdentity(v,name,42,7,'assembly');assert.equal(v.state().group,null);assert.match(v.els.get('identity').textContent,/return-navigation context/);
  const n=v.calls.length;v.location.search='?model='+name+'&event=560&group=0&view=positive';v.history.state={viewer:1,category:'all'};
  await v.listeners.get('popstate')();checkIdentity(v,name,560,0,'positive');assert.equal(v.calls.length,n);assert.equal(v.state().group.group_id,0);
  // Unknown native response does not remove the independent radiation primary.
  assert.equal(JSON.parse(v.els.get('evidenceRaw').textContent).event.native_response_known,false);
  for(const id of [0,100,200,300])await v.run('selectEvent('+id+')');assert.ok(v.run('chunkCache.size')<=2);
}
assert.equal(groups,8);
for(const name of ['GeRC02','KMRC01_candidate']){
  const v=await viewer('?model='+name+'&event=560&group=7&view=positive',{noRings:true});
  checkIdentity(v,name,560,7,'positive');assert.equal(v.state().primary,null);assert.equal(v.state().scene,null);assert.equal(v.state().group,null);
  assert.equal(v.requests.length,0);assert.match(v.els.get('status').textContent,/No completed saved 10K bundle/);
  assert.equal(v.els.get('model').value,name);assert.equal(v.els.get('model').children.at(-1).disabled,true);
  assert.equal(v.location.search,'?model='+name+'&event=560&group=7&view=positive');
  await v.run('selectModel("AK02")');checkIdentity(v,'AK02',213,0,'positive');assert.equal(v.state().primary.event_id,213);
  assert.equal(v.els.get('responseLinks').hidden,false);assert.equal(v.els.get('savedResponse').href,'../results/cs137-10k/AK02/charge-readout.html');
}
// Switch among all four real/mocked populations in one instance. Manifest cache
// identity is a pinned bundle, never one shared mutable assembly/positive slot.
{
  const v=await viewer('?model=AK02&event=213&group=0&view=positive');
  for(const [model,event]of [['GeRC02',42],['SAP22',5930],['KMRC01_candidate',42],['AK02',213],['GeRC02',560]]){
    await v.run('requestSelection({model:'+JSON.stringify(model)+',event:'+event+',group:0,view:"positive",invalid:""})');
    checkIdentity(v,model,event,0,'positive');assert.equal(v.state().scene.model,model);assert.equal(v.state().primary.event_id,event);assert.equal(v.state().group.group_id,0);
    assert.equal(v.state().overlayCount,model==='AK02'?121:model==='SAP22'?115:3);}
  const oldRequests=v.requests.filter(u=>u.includes('cs137-10k-geometry/manifest.json'));assert.equal(oldRequests.length,1);
  assert.equal(v.requests.filter(u=>u===base+'manifest.json').length,1);
}
let crossBindingFailures=0;
for(const failure of ['kind','dataset','dataset_sha','source_scene','positive_scene']){
  const name='GeRC02',bad=structuredClone(manifest),e=bad.models[name];
  if(failure==='kind')bad.kind='wrong';
  if(failure==='dataset')e.dataset_binding.readout_wiring_factor=-1;
  if(failure==='dataset_sha')e.dataset_binding_sha256='0'.repeat(64);
  if(failure==='source_scene')e.source_scene_sha256='0'.repeat(64);
  if(failure==='positive_scene')bad.files[e.scene].sha256='0'.repeat(64);
  const body=Buffer.from(JSON.stringify(bad)),alternate='../examples/mock-positive/';
  const v=await viewer('?model='+name+'&event=42&group=0&view=positive',{
    setup:run=>run('VIEWER_CONFIG.models.GeRC02.positive='+JSON.stringify({base:alternate,sha256:sha(body),kind:'ring_saved_publication_v1'})),
    fetch:(url,real)=>url===alternate+'manifest.json'?new Response(body):real(url)});
  checkIdentity(v,name,42,0,'positive');exact(v.state().primary,ringPrimary(name,42));assert.equal(v.state().group,null);
  assert.equal(v.state().overlayCount,0);assert.ok(v.state().overlayError);crossBindingFailures++;}
// The old AK/SAP campaign gate remains mandatory, including deliberately
// rehashed positive metadata that leaves the saved scene identity untouched.
{
  const oldRoot=path.join(root,'docs/examples/cs137-10k-hits'),m=JSON.parse(fs.readFileSync(path.join(oldRoot,'manifest.json'),'utf8'));
  m.input_pins.campaign_run='0'.repeat(64);const body=Buffer.from(JSON.stringify(m));
  const v=await viewer('?model=AK02&event=213&group=0&view=positive',{
    setup:run=>run('VIEWER_CONFIG.positive.sha256='+JSON.stringify(sha(body))),
    fetch:(url,real)=>url.endsWith('/cs137-10k-hits/manifest.json')?new Response(body):real(url)});
  assert.equal(v.state().primary.event_id,213);assert.equal(v.state().group,null);assert.equal(v.state().overlayCount,0);assert.ok(v.state().overlayError);
}
let staleCases=0;
for(const layer of ['scene','primary','positive'])for(const fail of [false,true]){
  const v=await viewer('?model=AK02&event=213&group=0&view=assembly');fold(v);const pending=[];
  const suffix=layer==='scene'?'/GeRC02/scene.json':layer==='primary'?'/GeRC02/events-00000.json':'/GeRC02/selected.json.gz';
  v.setFetch((url,real)=>url.endsWith(suffix)?new Promise((resolve,reject)=>pending.push({url,real,resolve,reject})):real(url));
  const stale=v.run('requestSelection({model:"GeRC02",event:42,group:0,view:"positive",invalid:""})');await v.until(()=>pending.length>0);
  await v.run('requestSelection({model:"KMRC01_candidate",event:560,group:0,view:"positive",invalid:""})');
  const primary=v.state().primary,scene=v.state().scene,raw=v.els.get('records').textContent,status=v.els.get('status').textContent;
  for(const p of pending){if(fail)p.reject(Error('intentional late ring failure'));else p.resolve(await p.real(p.url));}
  await stale;checkIdentity(v,'KMRC01_candidate',560,0,'positive');assert.equal(v.state().primary,primary);assert.equal(v.state().scene,scene);
  assert.equal(v.els.get('records').textContent,raw);assert.equal(v.els.get('status').textContent,status);staleCases++;
}
for(const failure of ['hash','gzip','census']){
  const e=manifest.models.GeRC02,bytes=fs.readFileSync(path.join(site,'examples/cs137-10k-rings',e.selected)),options={};
  if(failure==='hash')options.fetch=(url,real)=>url===base+e.selected?new Response(Buffer.concat([bytes,Buffer.from('tamper')])):real(url);
  if(failure==='gzip')options.decoder=class{constructor(){throw Error('mock decoder unavailable');}};
  if(failure==='census'){
    const data=JSON.parse(zlib.gunzipSync(bytes));data.event_ids=data.event_ids.slice(1);const bad=zlib.gzipSync(Buffer.from(JSON.stringify(data))),m=structuredClone(manifest);
    m.files[e.selected].sha256=sha(bad);m.files[e.selected].bytes=bad.length;const body=Buffer.from(JSON.stringify(m));
    options.setup=run=>run('for(const n of ["GeRC02","KMRC01_candidate"])for(const k of ["assembly","positive"])VIEWER_CONFIG.models[n][k].sha256='+JSON.stringify(sha(body)));
    options.fetch=(url,real)=>url===base+'manifest.json'?new Response(body):url===base+e.selected?new Response(bad):real(url);}
  const v=await viewer('?model=GeRC02&event=42&group=0&view=positive',options);checkIdentity(v,'GeRC02',42,0,'positive');
  exact(v.state().primary,ringPrimary('GeRC02',42));assert.equal(v.state().group,null);assert.equal(v.state().overlayCount,0);assert.ok(v.state().overlayError);
}
console.log(JSON.stringify({status:'passed',scope:'source-generated minimal-DOM reader: real old saved data and explicit mock rings; not browser/science/publication acceptance',
  mockRingGroups:groups,exactScalarComparisons:scalars,crossBindingFailures,oldCampaignGate:true,staleCases,overlayFailures:3,
  absentRingRequestsRetained:true,fourModelCacheIsolation:true,zerosAndUnknownResponseRetained:true,history:true,chunkCacheMaximum:2,newPhysics:0},null,2));
