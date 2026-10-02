// Execute generated scripts with real saved payloads and the existing minimal DOM.
// This is a logic/data regression, not browser/layout or physics acceptance.
import fs from 'node:fs';import path from 'node:path';import vm from 'node:vm';
import zlib from 'node:zlib';import {createHash,webcrypto} from 'node:crypto';
import assert from 'node:assert/strict';
const site=path.resolve(process.argv[2]||'docs');
const read=p=>JSON.parse(fs.readFileSync(p,'utf8')),sha=b=>createHash('sha256').update(b).digest('hex');
const assemblyRoot=path.join(site,'examples/cs137-10k-geometry'),positiveRoot=path.join(site,'examples/cs137-10k-hits');
const assembly=read(path.join(assemblyRoot,'manifest.json')),positive=read(path.join(positiveRoot,'manifest.json'));
// Exercise current sources against the protected saved payloads without a site
// build or copying/regenerating science. Python tests separately cover render().
const sourceMode=process.argv.includes('--source');
const sourceHTML=sourceMode?fs.readFileSync('tools/unified_event_viewer.html','utf8')
  .replace('__VIEWER_NAVIGATION__',()=>fs.readFileSync('tools/viewer_navigation.js','utf8'))
  .replace('__VIEWER_CONFIG__',()=>JSON.stringify({assembly:{base:'../examples/cs137-10k-geometry/',sha256:sha(fs.readFileSync(path.join(assemblyRoot,'manifest.json')))},
    positive:{base:'../examples/cs137-10k-hits/',sha256:sha(fs.readFileSync(path.join(positiveRoot,'manifest.json')))}}))
  .replace('__VIEWER_CONTROLLER__',()=>fs.readFileSync('tools/unified_event_viewer.js','utf8')):null;
const oracles=new Map(),chunks=new Map();let scalarComparisons=0;
function exact(a,b,p='value'){
  if(b===null||typeof b!=='object'){assert.ok(Object.is(a,b),p+': scalar/type differs');scalarComparisons++;return;}
  assert.equal(Array.isArray(a),Array.isArray(b),p+': container differs');
  assert.deepEqual(Object.keys(a).sort(),Object.keys(b).sort(),p+': keys differ');
  for(const k of Object.keys(b))exact(a[k],b[k],p+'.'+k);
}
function oracle(model){
  if(!oracles.has(model)){
    const scene=read(path.join(assemblyRoot,assembly.models[model].scene)),entry=positive.models[model];
    const bytes=fs.readFileSync(path.join(positiveRoot,entry.selected));assert.equal(sha(bytes),positive.files[entry.selected].sha256);
    const data=JSON.parse(zlib.gunzipSync(bytes));
    oracles.set(model,{scene,data,evidence:new Map(data.evidence.map(e=>[e.event_id,e]))});
  }return oracles.get(model);
}
function originalPrimary(model,id){
  const entry=oracle(model).scene.event_index.chunks[Math.floor(id/100)],key=model+'/'+entry.file;
  if(!chunks.has(key)){const bytes=fs.readFileSync(path.join(assemblyRoot,key));assert.equal(sha(bytes),entry.sha256);
    chunks.set(key,JSON.parse(bytes));if(chunks.size>2)chunks.delete(chunks.keys().next().value);}
  return chunks.get(key).events[id-entry.first];
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
  const html=sourceHTML||fs.readFileSync(path.join(site,'viewers/events.html'),'utf8'),els=new Map();
  for(const m of html.matchAll(/<(\w+)\b[^>]*id="([^"]+)"[^>]*>/g)){
    const e=new Element(m[1]);e.checked=/\bchecked\b/.test(m[0]);e.disabled=/\bdisabled\b/.test(m[0]);els.set(m[2],e);}
  els.get('category').value='all';els.get('model').value='AK02';
  const location={pathname:'/viewers/events.html',search:query},requests=[],historyCalls=[],listeners=new Map();
  const move=url=>{const u=new URL(url,'https://test.invalid');location.pathname=u.pathname;location.search=u.search;};
  const history={state:null,pushState(state,_title,url){this.state=state;historyCalls.push({kind:'push',state,url});move(url);},replaceState(state,_title,url){this.state=state;historyCalls.push({kind:'replace',state,url});move(url);}};
  const realFetch=async url=>{assert.ok(url.startsWith('../examples/'),'Unexpected data path '+url);
    const file=path.resolve(site,'viewers',url);assert.ok(file.startsWith(path.join(site,'examples')+path.sep));return new Response(fs.readFileSync(file));};
  let intercept=options.fetch;
  const context={URL,URLSearchParams,TextDecoder,Uint8Array,Blob,Response,DecompressionStream:options.decoder||DecompressionStream,crypto:webcrypto,devicePixelRatio:1,
    location,history,ResizeObserver:class{observe(){}},addEventListener:(name,fn)=>listeners.set(name,fn),
    document:{getElementById:id=>els.get(id),createElement:tag=>new Element(tag),querySelectorAll:()=>[]},
    fetch:async url=>{requests.push(url);return intercept?intercept(url,realFetch):realFetch(url);}};
  const c=vm.createContext(context),run=code=>vm.runInContext(code,c);
  const scripts=[...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/g)];
  assert.deepEqual(scripts.map(m=>/id="([^"]+)"/.exec(m[1])?.[1]),['viewer-navigation','viewer-config','viewer-controller']);
  for(const m of scripts){run(m[2]);if(m[1].includes('viewer-config')&&options.setup)options.setup(run);}
  await run('unifiedViewer.ready');
  const until=async predicate=>{for(let n=0;n<500;n++){if(predicate())return;await new Promise(r=>setTimeout(r,10));}throw Error('Timeout / '+els.get('status').textContent);};
  return{run,state:()=>run('unifiedViewer.getState()'),els,requests,historyCalls,location,history,listeners,until,setFetch:fn=>{intercept=fn;}};
}
function identity(v,model,id,group,view){const s=v.state();assert.equal(s.requested.model,model);assert.equal(s.requested.event,id);assert.equal(s.requested.group,group);assert.equal(s.requested.view,view);assert.equal(s.primary?.event_id??null,id);assert.equal(s.scene.model,model);}
function fold(v){v.els.get('recordPanel').open=true;v.els.get('evidencePanel').open=true;v.els.get('recordPanel').ontoggle();}
function primary(v,model,id){exact(v.state().primary,originalPrimary(model,id),model+'/'+id+'/primary');}
const results=[];let groups=0;
for(const model of ['AK02','SAP22']){
  const first=model==='AK02'?213:5930,v=await viewer('?model='+model+'&event='+first+'&group=0&view=positive');fold(v);
  identity(v,model,first,0,'positive');assert.equal(v.state().group.group_id,0);
  for(const proof of oracle(model).data.evidence)for(const g of proof.groups){
    await v.run('selectEvent('+proof.event_id+','+g.group_id+')');identity(v,model,proof.event_id,g.group_id,'positive');primary(v,model,proof.event_id);
    exact(v.state().group,g,model+'/'+proof.event_id+'/group');
    const rows=new Map(v.state().primary.tables['stp/germanium'].map(r=>[r.raw_row_index,r]));
    const packed=oracle(model).data.events.find(e=>e.event_id===proof.event_id),keys=oracle(model).data.columns['stp/germanium'];
    const saved=new Map(packed.tables['stp/germanium'].map(r=>[r[keys.indexOf('raw_row_index')],Object.fromEntries(keys.map((k,i)=>[k,r[i]]))]));
    for(const id of g.ge_raw_row_indices){assert.ok(rows.has(id));exact(rows.get(id),saved.get(id),'Ge-row/'+id);}
    exact(JSON.parse(v.els.get('records').textContent),originalPrimary(model,proof.event_id),'raw fold');
    const raw=JSON.parse(v.els.get('evidenceRaw').textContent);exact(raw.event,proof,'proof fold');assert.equal(raw.selected_group_id,g.group_id);groups++;
  }
  assert.equal(v.state().overlayCount,model==='AK02'?121:115);await v.run('selectEvent('+first+',0)');
  const missing=Object.keys(positive.category_labels).find(k=>!oracle(model).evidence.get(first).groups.some(g=>g.categories.includes(k)));
  assert.ok(missing);v.els.get('category').value=missing;await v.run('filterCategory()');
  identity(v,model,first,0,'positive');assert.equal(v.state().group,null);assert.equal(v.els.get('evidenceRaw').textContent,'');assert.ok(v.state().overlayError);
  v.els.get('category').value='all';await v.run('filterCategory()');assert.equal(v.state().group.group_id,0);
  await v.run('selectEvent('+first+',999)');identity(v,model,first,999,'positive');assert.equal(v.state().group,null);
  for(const id of [0,9999])for(const view of ['assembly','positive']){
    await v.run('requestSelection({model:'+JSON.stringify(model)+',event:'+id+',group:null,view:'+JSON.stringify(view)+',invalid:""})');
    identity(v,model,id,null,view);primary(v,model,id);assert.equal(v.state().group,null);
  }results.push({model,saved_groups:oracle(model).data.evidence.reduce((n,e)=>n+e.groups.length,0),whole_primary_and_group_oracle:true});
}
assert.equal(groups,236);
for(const [route,view] of [['geant4-assembly','assembly'],['ge-positive','positive']]){
  const html=fs.readFileSync(path.join(site,'viewers',route+'.html'),'utf8');
  for(const query of ['?model=AK02&event=213&group=0','?model=SAP22&event=5930']){
    let target=null;const c=vm.createContext({URLSearchParams,location:{search:query,hash:'#recordPanel',replace:t=>{target=t;}},document:{getElementById:()=>new Element()}});
    for(const m of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g))vm.runInContext(m[1],c);
    assert.ok(target,'Valid alias did not redirect');const u=new URL(target,'https://test.invalid/viewers/');assert.equal(u.pathname,'/viewers/events.html');assert.equal(u.searchParams.get('view'),view);assert.equal(u.hash,'#recordPanel');
    const v=await viewer(u.search),id=query.includes('5930')?5930:213,model=id===213?'AK02':'SAP22';
    identity(v,model,id,query.includes('group=')?0:(view==='positive'?0:null),view);
    if(view==='assembly'){assert.equal(v.state().group,null);assert.ok(v.els.get('identity').textContent.includes('return-navigation context')||!query.includes('group='));await v.run('selectEvent(0)');assert.equal(v.state().requested.group,null);}
  }
  for(const query of ['?event=0&event=1','?model=AK02&model=SAP22','?foo=1','?view=assembly','?event=213&group=1.5']){
    let target=null;const status=new Element(),c=vm.createContext({URLSearchParams,location:{search:query,hash:'',replace:t=>{target=t;}},document:{getElementById:()=>status}});
    for(const m of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g))vm.runInContext(m[1],c);
    assert.equal(target,null,query);assert.ok(status.textContent.includes(query),'Refusal must retain requested query');
  }
}
for(const query of ['?model=X','?event=-1','?event=10000','?event=01','?group=0','?event=213&group=1.5','?event=0&event=1','?foo=1','?view=other']){
  const v=await viewer(query);assert.ok(v.state().requested.invalid,query);assert.equal(v.state().primary,null);assert.equal(v.state().group,null);assert.equal(v.requests.length,0);
}
{
  const v=await viewer('?model=AK02&event=213&group=999&view=assembly');identity(v,'AK02',213,999,'assembly');assert.equal(v.state().group,null);primary(v,'AK02',213);
  await v.run('setView("positive")');identity(v,'AK02',213,999,'positive');assert.equal(v.state().group,null);assert.ok(v.state().overlayError);
  await v.run('selectEvent(0)');assert.equal(v.state().requested.group,null);
}
{
  const v=await viewer('?model=AK02&event=213&group=0&view=positive');fold(v);
  const n=v.historyCalls.length;await v.run('selectEvent(213,0)');assert.equal(v.historyCalls.length,n);
  await v.run('requestSelection({model:"SAP22",event:5930,group:0,view:"positive",invalid:""})');assert.equal(v.historyCalls.at(-1).kind,'push');
  const length=v.historyCalls.length;v.location.search='?model=AK02&event=213&group=0&view=assembly';v.history.state={viewer:1,category:'all'};
  await v.listeners.get('popstate')();identity(v,'AK02',213,0,'assembly');assert.equal(v.state().group,null);assert.equal(v.historyCalls.length,length);primary(v,'AK02',213);
  v.location.search='?model=SAP22&event=5930&group=0&view=positive';await v.listeners.get('popstate')();identity(v,'SAP22',5930,0,'positive');assert.equal(v.historyCalls.length,length);assert.equal(JSON.parse(v.els.get('records').textContent).event_id,5930);
}
for(const layer of ['model','event','positive'])for(const fail of [false,true]){
  const v=await viewer('?model=AK02&event=213&view=assembly');fold(v);const pending=[];
  const oldChunk=oracle('AK02').scene.event_index.chunks[35].file;
  const match=layer==='model'?url=>url.endsWith('/SAP22/scene.json'):layer==='event'?url=>url.endsWith('/AK02/'+oldChunk):url=>url.endsWith('/AK02/selected.json.gz');
  v.setFetch((url,real)=>match(url)?new Promise((resolve,reject)=>pending.push({url,resolve,reject,real})):real(url));
  const stale=layer==='model'?v.run('selectModel("SAP22")'):layer==='event'?v.run('selectEvent(3500)'):v.run('setView("positive")');
  assert.equal(v.state().primary,null);assert.equal(v.els.get('records').textContent,'');assert.equal(v.els.get('evidenceRaw').textContent,'');await v.until(()=>pending.length>0);
  if(layer==='positive')await v.run('requestSelection({model:"SAP22",event:5930,group:0,view:"positive",invalid:""})');
  else await v.run('requestSelection({model:"AK02",event:9999,group:null,view:"assembly",invalid:""})');
  const current=v.state(),status=v.els.get('status').textContent,proof=v.els.get('evidenceRaw').textContent;
  for(const p of pending.splice(0)){if(fail)p.reject(Error('intentional stale failure'));else p.resolve(await p.real(p.url));}
  await stale;exact(v.state().requested,current.requested,'stale '+layer);assert.equal(v.state().primary,current.primary);assert.equal(v.state().scene,current.scene);assert.equal(v.els.get('status').textContent,status);assert.equal(v.els.get('evidenceRaw').textContent,proof);
}
for(const failure of ['hash','gzip','census']){
  const entry=positive.models.AK02,bytes=fs.readFileSync(path.join(positiveRoot,entry.selected)),options={};
  if(failure==='hash')options.fetch=(url,real)=>url.endsWith('/AK02/selected.json.gz')?new Response(Buffer.concat([bytes,Buffer.from('tamper')])):real(url);
  if(failure==='gzip')options.decoder=class{constructor(){throw Error('intentional unavailable gzip decoder');}};
  if(failure==='census'){
    const data=JSON.parse(zlib.gunzipSync(bytes));data.event_ids=data.event_ids.slice(1);const corrupt=zlib.gzipSync(Buffer.from(JSON.stringify(data)));
    const m=structuredClone(positive);m.files[entry.selected].sha256=sha(corrupt);m.files[entry.selected].bytes=corrupt.length;const manifest=Buffer.from(JSON.stringify(m));
    options.setup=run=>run('VIEWER_CONFIG.positive.sha256='+JSON.stringify(sha(manifest)));
    options.fetch=(url,real)=>url.endsWith('/cs137-10k-hits/manifest.json')?new Response(manifest):url.endsWith('/AK02/selected.json.gz')?new Response(corrupt):real(url);
  }
  const v=await viewer('?model=AK02&event=213&group=0&view=positive',options);identity(v,'AK02',213,0,'positive');primary(v,'AK02',213);
  assert.equal(v.state().group,null);assert.equal(v.state().overlayCount,0);assert.ok(v.state().overlayError);assert.equal(v.els.get('evidenceRaw').textContent,'');
  assert.equal(v.els.get('originals').href,'../examples/cs137-10k-geometry/'+assembly.models.AK02.originals);
}
{
  const v=await viewer('?model=AK02&event=0&view=assembly');assert.ok(!v.requests.some(p=>p.includes('cs137-10k-hits')),'Overlay must load lazily');
  for(const id of [0,100,200,300])await v.run('selectEvent('+id+')');assert.ok(v.run('chunkCache.size')<=2);
}
let typedInputCases=0;
{
  const v=await viewer('?model=AK02&event=213&group=0&view=positive');fold(v);
  for(const raw of ['', '-1', '10000', '01', '1.5', 'nonnumeric']){
    const requests=v.requests.length,history=v.historyCalls.length,address=v.location.search;
    v.els.get('eid').value=raw;assert.equal(await v.els.get('show').onclick(),false);
    assert.equal(v.state().primary,null);assert.equal(v.state().group,null);assert.equal(v.state().scene,null);
    assert.equal(v.els.get('records').textContent,'');assert.equal(v.els.get('evidenceRaw').textContent,'');
    assert.ok(v.els.get('identity').textContent.includes(JSON.stringify(raw)));
    assert.ok(!v.els.get('identity').textContent.includes('recorded initial default'));
    assert.ok(v.els.get('status').textContent.includes(JSON.stringify(raw)));
    assert.ok(!v.els.get('status').textContent.includes('Query:'));
    assert.equal(v.requests.length,requests);assert.equal(v.historyCalls.length,history);assert.equal(v.location.search,address);
    typedInputCases++;
  }
  v.els.get('eid').value='0';assert.equal(await v.els.get('show').onclick(),true);identity(v,'AK02',0,null,'positive');primary(v,'AK02',0);
  v.els.get('eid').value='213';assert.equal(await v.els.get('show').onclick(),true);identity(v,'AK02',213,0,'positive');primary(v,'AK02',213);
}
console.log(JSON.stringify({status:'passed',kind:'generated-script minimal-DOM saved-payload regression, not browser acceptance',sourceMode,site,groups,scalarComparisons,results,asyncCases:6,overlayFailureCases:3,historyAndAliases:true,typedInputCases,numericalSourceWrites:0},null,2));
