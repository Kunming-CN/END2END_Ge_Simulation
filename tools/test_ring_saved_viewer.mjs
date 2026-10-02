// Real four-detector saved-data regression. This does not run simulations,
// exporters or a browser, and does not replace layout/physics acceptance.
import fs from 'node:fs';import path from 'node:path';import vm from 'node:vm';
import zlib from 'node:zlib';import {createHash,webcrypto} from 'node:crypto';import assert from 'node:assert/strict';
const site=path.resolve(process.argv[2]||'docs'),sourceMode=process.argv.includes('--source');
const arg=process.argv.indexOf('--ring-root'),ringRoot=arg<0?path.join(site,'examples/cs137-10k-rings'):path.resolve(process.argv[arg+1]);
const ringBase='../examples/cs137-10k-rings/',assemblyRoot=path.join(site,'examples/cs137-10k-geometry'),positiveRoot=path.join(site,'examples/cs137-10k-hits');
const inputPins=new Map(),sha=b=>createHash('sha256').update(b).digest('hex');
function bytes(file){const b=fs.readFileSync(file);inputPins.set(path.resolve(file),{sha256:sha(b),bytes:b.length});return b;}
const read=file=>JSON.parse(bytes(file)),assembly=read(path.join(assemblyRoot,'manifest.json')),positive=read(path.join(positiveRoot,'manifest.json'));
const rings=read(path.join(ringRoot,'manifest.json'));
assert.equal(rings.kind,'ring_saved_publication_v1');assert.equal(rings.status,'complete');
const names=['AK02','SAP22','GeRC02','KMRC01_candidate'];
const expected={AK02:{groups:121,zeros:9879},SAP22:{groups:115,zeros:9885},GeRC02:{groups:297,zeros:9703},KMRC01_candidate:{groups:231,zeros:9769}};
for(const n of names.slice(2)){assert.equal(rings.models[n].event_count,10000);assert.equal(rings.models[n].group_count,expected[n].groups);assert.equal(rings.models[n].zero_ge_primaries,expected[n].zeros);}
const config={assembly:{base:'../examples/cs137-10k-geometry/',sha256:sha(bytes(path.join(assemblyRoot,'manifest.json')))},
  positive:{base:'../examples/cs137-10k-hits/',sha256:sha(bytes(path.join(positiveRoot,'manifest.json')))},
  models:Object.fromEntries(names.slice(2).map(n=>[n,Object.fromEntries(['assembly','positive'].map(k=>[k,{base:ringBase,sha256:sha(bytes(path.join(ringRoot,'manifest.json'))),kind:rings.kind}]))]))};
const html=sourceMode?bytes('tools/unified_event_viewer.html').toString('utf8')
  .replace('__VIEWER_NAVIGATION__',()=>bytes('tools/viewer_navigation.js').toString('utf8'))
  .replace('__VIEWER_CONFIG__',()=>JSON.stringify(config))
  .replace('__VIEWER_CONTROLLER__',()=>bytes('tools/unified_event_viewer.js').toString('utf8')):bytes(path.join(site,'viewers/events.html')).toString('utf8');
const oracles=new Map(),chunks=new Map();let scalars=0,negativeZeros=0;
function exact(a,b,label='saved'){
  if(b===null||typeof b!=='object'){assert.ok(Object.is(a,b),label+': scalar/type differs');scalars++;if(Object.is(b,-0))negativeZeros++;return;}
  assert.equal(Array.isArray(a),Array.isArray(b),label+': container differs');assert.deepEqual(Object.keys(a).sort(),Object.keys(b).sort(),label+': keys differ');
  for(const k of Object.keys(b))exact(a[k],b[k],label+'.'+k);
}
function oracle(model){
  if(!oracles.has(model)){
    const ring=names.slice(2).includes(model),a=ring?rings:assembly,p=ring?rings:positive,aRoot=ring?ringRoot:assemblyRoot,pRoot=ring?ringRoot:positiveRoot;
    const sceneBytes=bytes(path.join(aRoot,a.models[model].scene));assert.equal(sha(sceneBytes),a.files[a.models[model].scene].sha256);
    const scene=JSON.parse(sceneBytes),entry=p.models[model],selected=bytes(path.join(pRoot,entry.selected));assert.equal(sha(selected),p.files[entry.selected].sha256);
    const data=JSON.parse(zlib.gunzipSync(selected));assert.equal(scene.model,model);assert.equal(scene.event_index.event_count,10000);
    assert.equal(scene.event_index.chunks.length,100);assert.equal(scene.event_index.zero_ge_primaries,expected[model].zeros);
    assert.deepEqual(data.event_ids,scene.event_index.ge_hit_ids);assert.equal(data.evidence.reduce((n,e)=>n+e.groups.length,0),expected[model].groups);
    oracles.set(model,{scene,data,entry,a,p,aRoot,pRoot,evidence:new Map(data.evidence.map(e=>[e.event_id,e])),events:new Map(data.events.map(e=>[e.event_id,e]))});
  }return oracles.get(model);
}
function originalPrimary(model,id){
  const o=oracle(model),entry=o.scene.event_index.chunks[Math.floor(id/100)],key=model+'/'+entry.file;
  if(!chunks.has(key)){
    assert.equal(entry.first,Math.floor(id/100)*100);assert.equal(entry.count,100);
    const b=bytes(path.join(o.aRoot,model,entry.file));assert.equal(sha(b),entry.sha256);assert.equal(sha(b),o.a.files[model+'/'+entry.file].sha256);
    const decoded=entry.file.endsWith('.gz')?zlib.gunzipSync(b):b;
    if(entry.file.endsWith('.gz')){assert.equal(sha(decoded),entry.uncompressed_sha256);assert.equal(decoded.length,entry.uncompressed_bytes);}
    const c=JSON.parse(decoded);assert.equal(c.model,model);assert.equal(c.first,entry.first);assert.equal(c.events.length,100);
    for(let i=0;i<100;i++)assert.equal(c.events[i].event_id,entry.first+i);
    chunks.set(key,c);if(chunks.size>2)chunks.delete(chunks.keys().next().value);
  }return chunks.get(key).events[id-entry.first];
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
  els.get('category').value='all';const location={pathname:'/viewers/events.html',search:query},requests=[],historyCalls=[],listeners=new Map();
  const move=url=>{const u=new URL(url,'https://test.invalid');location.pathname=u.pathname;location.search=u.search;};
  const history={state:null,pushState(state,_title,url){this.state=state;historyCalls.push({kind:'push',state,url});move(url);},replaceState(state,_title,url){this.state=state;historyCalls.push({kind:'replace',state,url});move(url);}};
  const realFetch=async url=>{
    assert.ok(url.startsWith('../examples/'),'unexpected '+url);
    const saved=url.startsWith(ringBase)?ringRoot:site,file=url.startsWith(ringBase)?path.resolve(ringRoot,url.slice(ringBase.length)):path.resolve(site,'viewers',url);
    assert.ok(file.startsWith(saved+path.sep),'escaped path');return new Response(bytes(file));};
  let intercept=options.fetch;
  const c=vm.createContext({URL,URLSearchParams,TextDecoder,Uint8Array,Blob,Response,DecompressionStream:options.decoder||DecompressionStream,
    crypto:webcrypto,devicePixelRatio:1,location,history,ResizeObserver:class{observe(){}},addEventListener:(name,fn)=>listeners.set(name,fn),
    document:{getElementById:id=>els.get(id),createElement:tag=>new Element(tag),querySelectorAll:()=>[]},
    fetch:async url=>{requests.push(url);return intercept?intercept(url,realFetch):realFetch(url);}});
  const run=code=>vm.runInContext(code,c),scripts=[...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/g)];
  assert.deepEqual(scripts.map(m=>/id="([^"]+)"/.exec(m[1])?.[1]),['viewer-navigation','viewer-config','viewer-controller']);
  for(const m of scripts){run(m[2]);if(m[1].includes('viewer-config')){if(options.noRings)run('delete VIEWER_CONFIG.models');if(options.setup)options.setup(run);}}
  await run('unifiedViewer.ready');
  return {run,state:()=>run('unifiedViewer.getState()'),els,requests,historyCalls,location,history,listeners,
    setFetch:fn=>{intercept=fn;},until:async predicate=>{for(let n=0;n<500;n++){if(predicate())return;await new Promise(r=>setTimeout(r,5));}throw Error('timeout '+els.get('status').textContent);}};
}
function identity(v,model,event,group,view){const s=v.state();assert.equal(s.requested.model,model);assert.equal(s.requested.event,event);assert.equal(s.requested.group,group);assert.equal(s.requested.view,view);assert.equal(s.primary?.event_id??null,event);assert.equal(s.scene.model,model);}
function fold(v){v.els.get('recordPanel').open=true;v.els.get('evidencePanel').open=true;v.els.get('recordPanel').ontoggle();}
function modelLinks(v,model){
  const ids=['savedResponse','savedResponseReport','savedSignals','savedCurrent'];
  if(!names.slice(2).includes(model)){
    assert.equal(v.els.get('responseLinks').hidden,true);for(const id of ids){assert.equal(v.els.get(id).href,undefined);assert.equal(v.els.get(id).hidden,true);}return;
  }
  const e=rings.models[model],files=[e.response,e.response_report,model+'/response/signals.csv',model+'/response/readout-input.csv'];
  assert.equal(v.els.get('responseLinks').hidden,false);
  for(let i=0;i<ids.length;i++){
    const element=v.els.get(ids[i]),pin=rings.files[files[i]];assert.equal(element.hidden,!pin,model+'/'+ids[i]+'/visibility');
    if(pin){assert.equal(element.href,ringBase+files[i]);const b=bytes(path.join(ringRoot,files[i]));assert.equal(sha(b),pin.sha256);assert.equal(b.length,pin.bytes);}
    else assert.equal(element.href,undefined,model+'/'+ids[i]+'/unavailable href');
  }
  assert.equal(v.els.get('savedCurrent').hidden,model==='GeRC02');
}
const first=model=>oracle(model).data.event_ids[0],firstGroup=model=>oracle(model).evidence.get(first(model)).groups[0].group_id;
let groups=0,primaries=0,zeros=0;const results=[];
for(const model of names){
  const o=oracle(model),v=await viewer('?model='+model+'&event='+first(model)+'&group='+firstGroup(model)+'&view=positive');fold(v);
  assert.deepEqual(v.els.get('model').children.map(e=>e.value),names);identity(v,model,first(model),firstGroup(model),'positive');
  for(const proof of o.data.evidence)for(const group of proof.groups){
    await v.run('selectEvent('+proof.event_id+','+group.group_id+')');identity(v,model,proof.event_id,group.group_id,'positive');
    exact(v.state().primary,originalPrimary(model,proof.event_id),model+'/'+proof.event_id+'/primary');exact(v.state().group,group,model+'/'+proof.event_id+'/group');
    const rows=new Map(v.state().primary.tables['stp/germanium'].map(r=>[r.raw_row_index,r])),packed=o.events.get(proof.event_id),keys=o.data.columns['stp/germanium'];
    const saved=new Map(packed.tables['stp/germanium'].map(r=>[r[keys.indexOf('raw_row_index')],Object.fromEntries(keys.map((k,i)=>[k,r[i]]))]));
    for(const id of group.ge_raw_row_indices){assert.ok(rows.has(id));exact(rows.get(id),saved.get(id),model+'/Ge-row/'+id);}
    exact(JSON.parse(v.els.get('records').textContent),originalPrimary(model,proof.event_id),model+'/raw fold');
    const raw=JSON.parse(v.els.get('evidenceRaw').textContent);exact(raw.event,proof,model+'/proof fold');assert.equal(raw.selected_group_id,group.group_id);groups++;
  }
  assert.equal(v.state().overlayCount,o.data.event_ids.length);
  modelLinks(v,model);
  if(names.slice(2).includes(model)){
    assert.match(v.els.get('modelNotes').textContent,model==='GeRC02'?/original 30 min.*independent 50 min/:/candidate.*signed and negative.*fixed −1.*separate negative injection/);
  }
  // Every primary traverses the actual reader's hash-checked chunk loader.
  // Rendering is bounded to groups/edge cases; this does not sample the ledger.
  v.els.get('recordPanel').open=false;v.els.get('evidencePanel').open=false;
  const hitIds=[];let modelZeros=0;
  for(let id=0;id<10000;id++){
    const actual=await v.run('loadPrimary('+JSON.stringify(model)+',unifiedViewer.getState().scene,'+id+')'),saved=originalPrimary(model,id);
    exact(actual,saved,model+'/'+id+'/all-primary');assert.equal(actual.event_id,id);
    if(actual.tables['stp/germanium'].some(row=>row.edep>0))hitIds.push(id);else modelZeros++;
    primaries++;assert.ok(v.run('chunkCache.size')<=2);
  }
  assert.deepEqual(hitIds,o.scene.event_index.ge_hit_ids);assert.equal(modelZeros,expected[model].zeros);zeros+=modelZeros;
  fold(v);
  const zero=Array.from({length:10000},(_,i)=>i).find(i=>!o.evidence.has(i));assert.notEqual(zero,undefined);
  for(const id of new Set([0,9999,zero]))for(const view of ['assembly','positive']){
    await v.run('requestSelection({model:'+JSON.stringify(model)+',event:'+id+',group:null,view:'+JSON.stringify(view)+',invalid:""})');
    const group=view==='positive'&&o.evidence.has(id)?o.evidence.get(id).groups[0].group_id:null;
    identity(v,model,id,group,view);exact(v.state().primary,originalPrimary(model,id),model+'/edge/'+id);exact(JSON.parse(v.els.get('records').textContent),originalPrimary(model,id),model+'/edge raw');
    if(!o.evidence.has(id))assert.equal(v.state().group,null);
  }
  await v.run('selectEvent('+first(model)+',999)');identity(v,model,first(model),999,'positive');assert.equal(v.state().group,null);assert.equal(v.els.get('evidenceRaw').textContent,'');
  await v.run('selectEvent('+first(model)+','+firstGroup(model)+')');
  const missing=Object.keys(o.p.category_labels).find(k=>!o.evidence.get(first(model)).groups.some(g=>g.categories.includes(k)));
  assert.ok(missing);v.els.get('category').value=missing;await v.run('filterCategory()');identity(v,model,first(model),firstGroup(model),'positive');assert.equal(v.state().group,null);
  v.els.get('category').value='all';await v.run('filterCategory()');assert.equal(v.state().group.group_id,firstGroup(model));
  results.push({model,groups:expected[model].groups,all_primary_reader_oracles:10000,zero_ge_primaries:modelZeros});
}
assert.equal(groups,764);assert.equal(primaries,40000);assert.ok(negativeZeros>0);
const nullPhotonIdentities=[];
for(const model of names.slice(2))for(const proof of oracle(model).data.evidence)for(const group of proof.groups){
  if(group.source_photon_energy_keV!==null)continue;
  const v=await viewer('?model='+model+'&event='+proof.event_id+'&group='+group.group_id+'&view=positive');fold(v);
  identity(v,model,proof.event_id,group.group_id,'positive');assert.equal(v.state().group.source_photon_energy_keV,null);
  assert.ok(v.els.get('evidence').children.some(e=>e.textContent.includes('source photon unknown.')),'null photon label '+model+'/'+proof.event_id);
  exact(JSON.parse(v.els.get('evidenceRaw').textContent).event,proof,'null photon proof retained');
  nullPhotonIdentities.push(model+'/'+proof.event_id+'/'+group.group_id);
}
assert.deepEqual(nullPhotonIdentities,['GeRC02/77/0','GeRC02/4548/0','KMRC01_candidate/4096/0','KMRC01_candidate/7554/0']);
// Public response ledgers keep scientific unknowns and both KM signal signs.
function jsonl(file){return bytes(file).toString('utf8').trimEnd().split(/\r?\n/).map(JSON.parse);}
function csv(file){const rows=bytes(file).toString('utf8').trimEnd().split(/\r?\n/).map(line=>line.split(',').map(s=>s.startsWith('"')?s.slice(1,-1).replaceAll('""','"'):s));
  const columns=rows.shift();return rows.map(row=>{assert.equal(row.length,columns.length);return Object.fromEntries(columns.map((c,i)=>[c,Number(row[i])]))});}
const ge=jsonl(path.join(ringRoot,'GeRC02/response/scalars.jsonl')),geFailures=ge.filter(r=>r.record_kind==='pulse'&&r.status==='native_transport_failed');
assert.deepEqual(geFailures.map(r=>r.event_id),[560,1519,3230,5212]);
for(const record of geFailures){
  for(const key of ['readout','final_induced_keV','transport_flags','charge_end_ns','current_nA','induced_charge_fC','endpoints'])assert.equal(record[key],null);
  assert.equal(record.group_id,0);assert.equal(record.trace_saved,false);assert.equal(record.native_error.exact_error,'ArgumentError: Noncontact endpoint outside crystal');
  const v=await viewer('?model=GeRC02&event='+record.event_id+'&group=0&view=positive');fold(v);identity(v,'GeRC02',record.event_id,0,'positive');
  exact(v.state().primary,originalPrimary('GeRC02',record.event_id),'failed native primary retained');
  // Real classify() evidence describes radiation topology. Native status/nulls
  // live in the hash-bound response ledger, not the mock-only status field.
  exact(JSON.parse(v.els.get('evidenceRaw').textContent).event,oracle('GeRC02').evidence.get(record.event_id),'failed native radiation proof');
  exact(v.state().group,oracle('GeRC02').evidence.get(record.event_id).groups.find(g=>g.group_id===0),'failed native truth group');
}
const km=jsonl(path.join(ringRoot,'KMRC01_candidate/response/scalars.jsonl')).filter(r=>r.record_kind==='pulse');
assert.equal(km.length,231);let negativeNativeGroups=0;
for(const record of km){assert.equal(record.readout_wiring.factor,-1);assert.ok(Object.is(record.electronics_input_final_charge_keV,-record.final_induced_keV));
  assert.ok(Object.is(record.readout.raw_native_final_charge_keV,record.final_induced_keV));assert.equal(record.original_accepted,false);
  if(record.final_induced_keV<0)negativeNativeGroups++;}
assert.equal(negativeNativeGroups,230);
const raw=csv(path.join(ringRoot,'KMRC01_candidate/response/signals.csv')),wired=csv(path.join(ringRoot,'KMRC01_candidate/response/readout-input.csv'));
assert.equal(raw.length,14897);assert.equal(wired.length,raw.length);let negativeSamples=0,wiringNegativeZeros=0;
for(let i=0;i<raw.length;i++){
  const a=raw[i],b=wired[i];for(const key of ['event_id','global_decay_id','group_id','time_since_origin_ns'])assert.ok(Object.is(a[key],b[key]),'KM sample identity/'+i+'/'+key);
  assert.ok(Object.is(a.induced_equivalent_energy_keV,b.raw_native_charge_keV),'KM raw sample/'+i);
  for(const [native,input]of [['raw_native_charge_keV','electronics_input_charge_keV'],['raw_native_charge_fC','electronics_input_charge_fC'],['raw_native_current_nA','electronics_input_current_nA']]){
    assert.ok(Object.is(b[input],-b[native]),'fixed -1/'+i+'/'+native);if(Object.is(b[input],-0))wiringNegativeZeros++;}
  if(a.induced_equivalent_energy_keV<0)negativeSamples++;
}assert.ok(negativeSamples>0);assert.ok(wiringNegativeZeros>0);
// Both old compatibility aliases preserve requested identities and default view.
let aliases=0;
for(const [route,view]of [['geant4-assembly','assembly'],['ge-positive','positive']]){
  const alias=bytes(path.join(site,'viewers',route+'.html')).toString('utf8');
  for(const query of ['?model=AK02&event=213&group=0','?model=SAP22&event=5930']){
    let target=null;const c=vm.createContext({URLSearchParams,location:{search:query,hash:'#recordPanel',replace:t=>{target=t;}},document:{getElementById:()=>new Element()}});
    for(const m of alias.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g))vm.runInContext(m[1],c);
    assert.ok(target);const u=new URL(target,'https://test.invalid/viewers/');assert.equal(u.pathname,'/viewers/events.html');assert.equal(u.searchParams.get('view'),view);assert.equal(u.hash,'#recordPanel');
    const v=await viewer(u.search),model=query.includes('5930')?'SAP22':'AK02',id=model==='SAP22'?5930:213;
    identity(v,model,id,query.includes('group=')?0:view==='positive'?0:null,view);if(view==='assembly')assert.equal(v.state().group,null);aliases++;
  }
}
// All four model caches remain isolated; history follows the current identity.
{
  const v=await viewer('?model=AK02&event=213&group=0&view=positive');fold(v);
  for(const model of ['GeRC02','SAP22','KMRC01_candidate','AK02','GeRC02']){
    await v.run('requestSelection({model:'+JSON.stringify(model)+',event:'+first(model)+',group:'+firstGroup(model)+',view:"positive",invalid:""})');
    identity(v,model,first(model),firstGroup(model),'positive');assert.equal(v.state().overlayCount,oracle(model).data.event_ids.length);exact(v.state().group,oracle(model).evidence.get(first(model)).groups[0]);modelLinks(v,model);}
  assert.equal(v.requests.filter(u=>u===ringBase+'manifest.json').length,1);assert.equal(v.requests.filter(u=>u.includes('cs137-10k-geometry/manifest.json')).length,1);
  const n=v.historyCalls.length;v.location.search='?model=KMRC01_candidate&event='+first('KMRC01_candidate')+'&group=0&view=positive';v.history.state={viewer:1,category:'all'};
  await v.listeners.get('popstate')();identity(v,'KMRC01_candidate',first('KMRC01_candidate'),0,'positive');assert.equal(v.historyCalls.length,n);
  assert.equal(JSON.parse(v.els.get('records').textContent).event_id,first('KMRC01_candidate'));
}
let staleCases=0;
for(const layer of ['scene','primary','positive'])for(const fail of [false,true]){
  const v=await viewer('?model=AK02&event=213&group=0&view=assembly');fold(v);const pending=[],id=first('GeRC02');
  const suffix=layer==='scene'?'/GeRC02/scene.json':layer==='primary'?'/GeRC02/'+oracle('GeRC02').scene.event_index.chunks[Math.floor(id/100)].file:'/GeRC02/selected.json.gz';
  v.setFetch((url,real)=>url.endsWith(suffix)?new Promise((resolve,reject)=>pending.push({url,real,resolve,reject})):real(url));
  const stale=v.run('requestSelection({model:"GeRC02",event:'+id+',group:0,view:"positive",invalid:""})');await v.until(()=>pending.length>0);
  if(layer==='scene'){
    assert.equal(v.els.get('responseLinks').hidden,true);
    for(const link of ['savedResponse','savedResponseReport','savedSignals','savedCurrent']){assert.equal(v.els.get(link).href,undefined);assert.equal(v.els.get(link).hidden,true);}
  }
  await v.run('requestSelection({model:"KMRC01_candidate",event:'+first('KMRC01_candidate')+',group:0,view:"positive",invalid:""})');
  const current=v.state(),status=v.els.get('status').textContent,records=v.els.get('records').textContent,evidence=v.els.get('evidenceRaw').textContent;
  for(const p of pending){if(fail)p.reject(Error('intentional late ring failure'));else p.resolve(await p.real(p.url));}
  await stale;identity(v,'KMRC01_candidate',first('KMRC01_candidate'),0,'positive');assert.equal(v.state().primary,current.primary);assert.equal(v.state().scene,current.scene);
  assert.equal(v.els.get('status').textContent,status);assert.equal(v.els.get('records').textContent,records);assert.equal(v.els.get('evidenceRaw').textContent,evidence);modelLinks(v,'KMRC01_candidate');staleCases++;
}
let crossBindingFailures=0;
for(const model of names.slice(2))for(const failure of ['kind','dataset','dataset_sha','source_scene','positive_scene']){
  const bad=structuredClone(rings),e=bad.models[model];
  if(failure==='kind')bad.kind='wrong';if(failure==='dataset')e.dataset_binding.readout_wiring_factor=model==='GeRC02'?-1:1;
  if(failure==='dataset_sha')e.dataset_binding_sha256='0'.repeat(64);if(failure==='source_scene')e.source_scene_sha256='0'.repeat(64);
  if(failure==='positive_scene')bad.files[e.scene].sha256='0'.repeat(64);
  const body=Buffer.from(JSON.stringify(bad)),alternate='../examples/intentional-invalid-positive/';
  const v=await viewer('?model='+model+'&event='+first(model)+'&group=0&view=positive',{
    setup:run=>run('VIEWER_CONFIG.models['+JSON.stringify(model)+'].positive='+JSON.stringify({base:alternate,sha256:sha(body),kind:rings.kind})),
    fetch:(url,real)=>url===alternate+'manifest.json'?new Response(body):real(url)});
  identity(v,model,first(model),0,'positive');exact(v.state().primary,originalPrimary(model,first(model)));assert.equal(v.state().group,null);assert.equal(v.state().overlayCount,0);assert.ok(v.state().overlayError);crossBindingFailures++;
}
// A deliberately rehashed old positive manifest cannot bypass the old campaign gate.
{
  const m=structuredClone(positive);m.input_pins.campaign_run='0'.repeat(64);const body=Buffer.from(JSON.stringify(m));
  const v=await viewer('?model=AK02&event=213&group=0&view=positive',{
    setup:run=>run('VIEWER_CONFIG.positive.sha256='+JSON.stringify(sha(body))),fetch:(url,real)=>url.endsWith('/cs137-10k-hits/manifest.json')?new Response(body):real(url)});
  identity(v,'AK02',213,0,'positive');assert.equal(v.state().group,null);assert.equal(v.state().overlayCount,0);assert.ok(v.state().overlayError);
}
let overlayFailures=0;
for(const failure of ['hash','gzip','census']){
  const model='GeRC02',entry=rings.models[model],saved=bytes(path.join(ringRoot,entry.selected)),options={};
  if(failure==='hash')options.fetch=(url,real)=>url===ringBase+entry.selected?new Response(Buffer.concat([saved,Buffer.from('tamper')])):real(url);
  if(failure==='gzip'){
    // With losslessly compressed raw chunks, preserve their working decoder
    // while faulting only the subsequent positive overlay decode.
    const rawGzip=oracle(model).scene.event_index.chunks[0].file.endsWith('.gz');let decodes=0;
    options.decoder=class{constructor(format){
      if(rawGzip&&++decodes===1)return new DecompressionStream(format);
      throw Error('intentional overlay decoder unavailable');
    }};
  }
  if(failure==='census'){
    const data=JSON.parse(zlib.gunzipSync(saved));data.event_ids=data.event_ids.slice(1);const corrupt=zlib.gzipSync(Buffer.from(JSON.stringify(data))),m=structuredClone(rings);
    m.files[entry.selected].sha256=sha(corrupt);m.files[entry.selected].bytes=corrupt.length;const body=Buffer.from(JSON.stringify(m));
    options.setup=run=>run('for(const n of ["GeRC02","KMRC01_candidate"])for(const k of ["assembly","positive"])VIEWER_CONFIG.models[n][k].sha256='+JSON.stringify(sha(body)));
    options.fetch=(url,real)=>url===ringBase+'manifest.json'?new Response(body):url===ringBase+entry.selected?new Response(corrupt):real(url);
  }
  const v=await viewer('?model=GeRC02&event='+first(model)+'&group=0&view=positive',options);identity(v,model,first(model),0,'positive');
  exact(v.state().primary,originalPrimary(model,first(model)));assert.equal(v.state().group,null);assert.equal(v.state().overlayCount,0);assert.ok(v.state().overlayError);overlayFailures++;
}
let gzipAssemblyFailures=0;
for(const model of names.slice(2))if(oracle(model).scene.event_index.chunks[0].file.endsWith('.gz')){
  const v=await viewer('?model='+model+'&event='+first(model)+'&group=0&view=positive',{
    decoder:class{constructor(){throw Error('intentional all gzip decoding unavailable');}}});
  const state=v.state();assert.equal(state.requested.model,model);assert.equal(state.requested.event,first(model));
  assert.equal(state.requested.group,0);assert.equal(state.requested.view,'positive');assert.equal(state.scene.model,model);
  assert.equal(state.primary,null);assert.equal(state.group,null);assert.equal(state.overlayCount,0);
  assert.match(v.els.get('status').textContent,/Assembly unavailable: intentional all gzip decoding unavailable/);
  assert.equal(v.els.get('records').textContent,'');assert.equal(v.els.get('evidenceRaw').textContent,'');gzipAssemblyFailures++;
}
for(const model of names.slice(2)){
  const v=await viewer('?model='+model+'&event=560&group=7&view=positive',{noRings:true});
  assert.equal(v.state().requested.model,model);assert.equal(v.state().requested.event,560);assert.equal(v.state().requested.group,7);
  assert.equal(v.state().primary,null);assert.equal(v.state().scene,null);assert.equal(v.state().group,null);assert.equal(v.requests.length,0);assert.match(v.els.get('status').textContent,/No completed saved 10K bundle/);
}
let typedInputCases=0;
{
  const v=await viewer('?model=KMRC01_candidate&event='+first('KMRC01_candidate')+'&group=0&view=positive');fold(v);
  for(const raw of ['', '-1', '10000', '01', '1.5', 'nonnumeric']){
    const requests=v.requests.length,history=v.historyCalls.length,address=v.location.search;v.els.get('eid').value=raw;assert.equal(await v.els.get('show').onclick(),false);
    assert.equal(v.state().primary,null);assert.equal(v.state().group,null);assert.equal(v.state().scene,null);assert.equal(v.els.get('records').textContent,'');assert.equal(v.els.get('evidenceRaw').textContent,'');
    assert.ok(v.els.get('identity').textContent.includes(JSON.stringify(raw)));assert.ok(v.els.get('status').textContent.includes(JSON.stringify(raw)));assert.equal(v.requests.length,requests);assert.equal(v.historyCalls.length,history);assert.equal(v.location.search,address);typedInputCases++;
  }
  v.els.get('eid').value='0';assert.equal(await v.els.get('show').onclick(),true);identity(v,'KMRC01_candidate',0,null,'positive');exact(v.state().primary,originalPrimary('KMRC01_candidate',0));
}
// Detect a saved file changing while this run was reading it.
for(const [file,pin]of inputPins){const b=fs.readFileSync(file);assert.equal(sha(b),pin.sha256,'changed test input '+file);assert.equal(b.length,pin.bytes);}
console.log(JSON.stringify({status:'passed',kind:'real four-detector minimal-DOM reader regression; not browser/layout or physics acceptance',sourceMode,site,ringRoot,
  groups,ringGroups:528,oldGroups:236,allPrimaryReaderComparisons:primaries,zeroGePrimaries:zeros,exactScalarComparisons:scalars,negativeZeroComparisons:negativeZeros,results,
  geNativeFailuresRetained:geFailures.length,nullPhotonIdentities,kmNegativeNativeGroups:negativeNativeGroups,kmRawSignedSamples:raw.length,kmNegativeSamples:negativeSamples,kmFixedWiringNegativeZeroSamples:wiringNegativeZeros,
  crossBindingFailures,oldCampaignGate:true,staleCases,overlayFailures,gzipAssemblyFailures,aliases,historyAndFourModelCacheIsolation:true,typedInputCases,missingRingRequestsRetained:true,chunkCacheMaximum:2,
  newPhysics:0,inputPins:Object.fromEntries(inputPins)},null,2));
