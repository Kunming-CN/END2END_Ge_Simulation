'use strict';
const $=id=>document.getElementById(id), canvas=$('canvas'), ctx=canvas.getContext('2d');
const DETAIL_CAP=2000, categories=['all','compact','compton1','compton2','full','partial','unknown'];
const viewer={generation:0,requested:parseViewerQuery(location.search),scene:null,primary:null,group:null,
  assemblyManifest:null,positiveManifest:null,data:null,events:new Map(),evidence:new Map(),category:'all',overlayError:''};
const RING_KIND='ring_saved_publication_v1',ringModels=['GeRC02','KMRC01_candidate'];
const sceneCache=new Map(),positiveCache=new Map(),chunkCache=new Map(),manifestCache=new Map();
let mode=null,pendingSelection=null;
let yaw=.55,pitch=-.2,zoom=1,panX=0,panY=0,center=[0,0,0],radius=1,panMode=false,visible=new Set();
const labels={ledger_0_PV:'World air',ledger_1:'Flange',ledger_2:'Outer Al wall / endCap',ledger_3:'Outer hollow',ledger_4:'Inner Al shield',ledger_5:'Inner vacuum',ledger_6:'Holder: stage',ledger_7:'Holder: backStage',ledger_12:'Holder: BN block',ledger_13:'Holder: lower indium',ledger_14:'Holder: copper plate',ledger_15:'Holder: upper indium',germanium:'Germanium crystal',ledger_17:'Nominal BN spacer',ledger_18:'Nominal Al source capsule',ledger_19:'Nominal source fill'};
const color=v=>v.name==='germanium'?'#c697ff':v.material==='G4_Al'?'#a9c2d5':v.material==='G4_Cu'?'#d78d5e':v.material==='boron_nitride'?'#7fdcae':v.material==='G4_Galactic'?'#5c7593':'#ddd290';
// Native JSON.stringify loses binary64 -0. These saved-data panels must retain
// it; delegate every other scalar and object key to ordinary JSON escaping.
function exactJSON(value){
  function encode(v,depth){
    if(v===null||typeof v!=='object')return Object.is(v,-0)?'-0':JSON.stringify(v);
    const array=Array.isArray(v),rows=array?Array.from(v,x=>encode(x,depth+1)??'null'):
      Object.keys(v).flatMap(key=>{const text=encode(v[key],depth+1);return text===undefined?[]:[JSON.stringify(key)+': '+text];});
    const open=array?'[':'{',close=array?']':'}',indent='  '.repeat(depth+1);
    return rows.length?open+'\n'+indent+rows.join(',\n'+indent)+'\n'+'  '.repeat(depth)+close:open+close;
  }
  return encode(value,0);
}
function requireViewer(ok,message){if(!ok)throw Error(message);}
function option(value,label){const e=document.createElement('option');e.value=String(value);e.textContent=label;return e;}
function paragraph(box,text){const p=document.createElement('p');p.textContent=text;box.append(p);}
async function fetchJSON(path,expected){
  const response=await fetch(path);if(!response.ok)throw Error(path+': HTTP '+response.status);
  let bytes=await response.arrayBuffer();
  requireViewer(globalThis.crypto?.subtle,'SHA-256 requires HTTPS or localhost.');
  const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),v=>v.toString(16).padStart(2,'0')).join('');
  requireViewer(hash===expected,'SHA-256 mismatch: '+path);
  if(path.endsWith('.gz')){
    requireViewer(typeof DecompressionStream!=='undefined','Native gzip DecompressionStream is required.');
    bytes=await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'))).arrayBuffer();
  }
  return JSON.parse(new TextDecoder().decode(bytes));
}
function modelBinding(kind,name){
  const binding=ringModels.includes(name)?VIEWER_CONFIG.models?.[name]?.[kind]:VIEWER_CONFIG[kind];
  requireViewer(binding,'No completed saved 10K bundle is available for '+name+'. Requested identity is retained.');
  if(ringModels.includes(name))requireViewer(binding.kind===RING_KIND,'Unsupported saved ring binding.');
  return binding;
}
function bundlePath(kind,file,name){return modelBinding(kind,name).base+file;}
function bundleKey(kind,name){const binding=modelBinding(kind,name);return binding.base+'|'+binding.sha256+'|'+name;}
async function savedManifest(kind,name){
  const binding=modelBinding(kind,name),key=binding.base+'|'+binding.sha256;
  if(!manifestCache.has(key))manifestCache.set(key,fetchJSON(binding.base+'manifest.json',binding.sha256)
    .then(m=>{requireViewer(m.status==='complete'&&m.schema_version===1&&(!binding.kind||m.kind===binding.kind),
      'Unsupported '+kind+' manifest.');return m;})
    .catch(e=>{manifestCache.delete(key);throw e;}));
  return manifestCache.get(key);
}
function assemblyManifest(name){return savedManifest('assembly',name);}
function positiveManifest(name){return savedManifest('positive',name);}
async function loadScene(name){
  const manifest=await assemblyManifest(name),key=bundleKey('assembly',name);
  if(!sceneCache.has(key)){
    const entry=manifest.models[name];requireViewer(entry,'No recorded assembly for '+name+'.');
    const scene=await fetchJSON(bundlePath('assembly',entry.scene,name),manifest.files[entry.scene].sha256);
    requireViewer(scene.model===name&&scene.event_index.event_count===10000,'Assembly model/census mismatch.');
    if(ringModels.includes(name))requireViewer(scene.event_index.chunks.length===100&&
      scene.event_index.chunks.every((c,i)=>c.first===i*100&&c.count===100&&
        manifest.files[name+'/'+c.file]?.sha256===c.sha256),'Saved ring chunk census mismatch.');
    sceneCache.set(key,scene);
  }
  return {manifest,scene:sceneCache.get(key)};
}
async function loadPrimary(name,scene,id){
  const index=scene.event_index.chunks[Math.floor(id/100)],file=name+'/'+index.file,key=bundleKey('assembly',name)+'/'+index.file;
  let chunk=chunkCache.get(key);
  if(!chunk){chunk=await fetchJSON(bundlePath('assembly',file,name),index.sha256);
    requireViewer(chunk.model===name&&chunk.first===index.first&&chunk.events.length===index.count&&
      chunk.events.every((e,i)=>e.event_id===index.first+i),'Chunk event census mismatch.');}
  chunkCache.delete(key);chunkCache.set(key,chunk);while(chunkCache.size>2)chunkCache.delete(chunkCache.keys().next().value);
  return chunk.events[id-index.first];
}
function unpackEvent(event,columns){
  return {event_id:event.event_id,tables:Object.fromEntries(Object.entries(columns).map(([table,keys])=>
    [table,(event.tables[table]||[]).map(row=>{requireViewer(row.length===keys.length,'Positive raw row schema mismatch.');return Object.fromEntries(keys.map((key,i)=>[key,row[i]]));})]))};
}
async function loadPositive(name,assembly,scene){
  const manifest=await positiveManifest(name),entry=manifest.models[name],assemblyEntry=assembly.models[name],key=bundleKey('positive',name);
  const bound=ringModels.includes(name)?assembly.kind===RING_KIND&&manifest.kind===RING_KIND&&
    entry?.dataset_binding&&assemblyEntry?.dataset_binding&&
    sameBinding(entry.dataset_binding,assemblyEntry.dataset_binding)&&
    entry.dataset_binding.model_id===name&&entry.dataset_binding.primary_count===10000&&
    typeof entry.dataset_binding_sha256==='string'&&/^[a-f0-9]{64}$/.test(entry.dataset_binding_sha256)&&
    entry.dataset_binding_sha256===assemblyEntry.dataset_binding_sha256:
    manifest.input_pins.campaign_run===assembly.campaign_run_sha256;
  requireViewer(entry&&assemblyEntry&&bound&&
    entry.source_scene_sha256===assembly.files[assemblyEntry.scene].sha256&&
    manifest.files[entry.scene].sha256===entry.source_scene_sha256,'Positive/assembly campaign or scene mismatch.');
  if(!positiveCache.has(key)){
    const data=await fetchJSON(bundlePath('positive',entry.selected,name),manifest.files[entry.selected].sha256);
    requireViewer(data.model===name&&data.schema_version===1&&data.event_ids.length===entry.selected_count&&
      data.events.length===entry.selected_count&&data.evidence.length===entry.selected_count&&
      data.events.every((e,i)=>e.event_id===data.event_ids[i])&&data.evidence.every((e,i)=>e.event_id===data.event_ids[i])&&
      JSON.stringify(data.event_ids)===JSON.stringify(scene.event_index.ge_hit_ids),'Positive model/census mismatch.');
    positiveCache.set(key,{data,events:new Map(data.events.map(e=>[e.event_id,unpackEvent(e,data.columns)])),
      evidence:new Map(data.evidence.map(e=>[e.event_id,e]))});
  }
  return {manifest,...positiveCache.get(key)};
}
function sameBinding(a,b){
  if(a===null||b===null||typeof a!=='object'||typeof b!=='object')return Object.is(a,b);
  if(Array.isArray(a)!==Array.isArray(b))return false;
  const keys=Object.keys(a);return keys.length===Object.keys(b).length&&keys.every(k=>Object.hasOwn(b,k)&&sameBinding(a[k],b[k]));
}
function modelOptions(name){
  const names=['AK02','SAP22',...ringModels.filter(n=>VIEWER_CONFIG.models?.[n]?.assembly&&VIEWER_CONFIG.models[n].positive)];
  const options=names.map(n=>option(n,n==='GeRC02'?'GeRC02 · Li50min':n==='KMRC01_candidate'?'KMRC01 · candidate':n));
  if(!names.includes(name)){const unavailable=option(name,name+' · saved data unavailable');unavailable.disabled=true;options.push(unavailable);}
  $('model').replaceChildren(...options);$('model').value=name;
}
function clearModelLinks(){for(const id of ['savedResponse','savedResponseReport','savedSignals','savedCurrent']){$(id).removeAttribute('href');$(id).hidden=true;}$('modelNotes').textContent='';$('responseLinks').hidden=true;}
function clearGroup(){viewer.group=null;$('group').replaceChildren();$('group').disabled=true;$('evidence').replaceChildren();$('evidenceRaw').textContent='';}
function clearOverlay(){clearGroup();viewer.data=null;viewer.events=new Map();viewer.evidence=new Map();$('representatives').replaceChildren();}
function clearPrimary(){viewer.primary=null;$('records').textContent='';clearGroup();}
function identityText(){
  const r=viewer.requested;
  if(r.invalid){$('identity').textContent='Requested: '+r.model+'; unavailable identity: '+r.invalid;return;}
  $('identity').textContent='Requested: '+r.model+(r.event===null?' (recorded initial default)':', original primary '+r.event)+
    (r.group===null?'':', group '+r.group)+(r.view==='assembly'&&r.group!==null?' (return-navigation context only; no pulse group is selected).':'; '+r.view+' view.');
}
function writeHistory(action){
  if(action==='none'||viewer.requested.invalid)return;
  const next=viewerHistoryTarget(viewer.requested,location.pathname,location.search),state={viewer:1,category:viewer.category};
  if(action==='replace')history.replaceState(state,'',next.target);
  else if(next.changed||history.state?.category!==viewer.category)history.pushState(state,'',next.target);
}
function applyMode(view){
  if(mode===view)return;mode=view;
  for(const id of ['shells','steps','births'])$(id).checked=view==='assembly';
  $('overlay').checked=view==='positive';$('detail').checked=false;
  $('category').disabled=view==='assembly';
}
function showScene(scene,manifest,name){
  viewer.scene=scene;viewer.assemblyManifest=manifest;
  visible=new Set(scene.volumes.filter(v=>!['G4_AIR','G4_Galactic'].includes(v.material)).map(v=>v.name));
  $('volumes').replaceChildren();
  for(const v of scene.volumes){const label=document.createElement('label');label.className='volume';const check=document.createElement('input');check.type='checkbox';check.checked=visible.has(v.name);
    check.onchange=()=>{if(check.checked)visible.add(v.name);else visible.delete(v.name);draw();};
    const title=document.createElement('span');title.textContent=labels[v.name]||'Holder: '+v.original_path.split('/').pop();title.style.color=color(v);
    const small=document.createElement('small');small.textContent=v.name+' · '+v.material+' · '+v.solid_type;label.append(check,title,small);$('volumes').append(label);}
  const entry=manifest.models[name];$('originals').href=bundlePath('assembly',entry.originals,name);clearModelLinks();
  if(ringModels.includes(name)){
    $('modelNotes').textContent=name==='GeRC02'?
      'GeRC02: the original 30 min annealing model is preserved; this saved 10K case is the independent 50 min variant. Functional engineering example; Li CCE remains unvalidated.':
      'KMRC01 candidate: raw native signals remain signed and negative. This saved response uses fixed −1 electronics wiring and a separate negative injection calibration; original rejections remain available. No eventwise gain or charge rectification.';
    for(const [id,file]of [['savedResponse',entry.response],['savedResponseReport',entry.response_report],
      ['savedSignals',name+'/response/signals.csv'],['savedCurrent',name+'/response/readout-input.csv']])
      if(manifest.files[file]){$(id).href=bundlePath('assembly',file,name);$(id).hidden=false;}
    $('responseLinks').hidden=false;
  }
  $('census').textContent=scene.event_index.event_count+' primaries; '+scene.event_index.ge_hit_ids.length+' Ge-positive; '+scene.event_index.zero_ge_primaries+' zero-Ge';
  $('provenance').textContent=exactJSON({model:name,scenario:scene.scenario,raw_lh5_sha256:scene.raw_lh5_sha256,originals_sha256:scene.originals_sha256,
    raw_rows:scene.event_index.raw_rows,raw_columns:scene.event_index.raw_columns,versions:scene.raw_software_versions,seed:scene.seed,
    source_position_global_mm:scene.source_position_global_mm,exporter_sha256:manifest.exporter_sha256,upstream:manifest.upstream,omissions:scene.omissions,
    ...(ringModels.includes(name)?{variant_id:entry.variant_id,dataset_binding:entry.dataset_binding,dataset_binding_sha256:entry.dataset_binding_sha256,
      model_contract:entry.model_contract,counts:entry.counts,original_native_counts:entry.original_native_counts,readout_wiring:entry.readout_wiring,calibration:entry.calibration}:{})});
}
function refreshDetails(){
  if($('recordPanel').open)$('records').textContent=viewer.primary?exactJSON(viewer.primary):'';
  if($('evidencePanel').open)$('evidenceRaw').textContent=viewer.group?exactJSON({event:viewer.evidence.get(viewer.primary.event_id),selected_group_id:viewer.group.group_id}):'';
}
function describeGroup(){
  const g=viewer.group,e=viewer.evidence.get(viewer.primary.event_id);$('evidence').replaceChildren();
  const lines=[viewer.requested.model+' primary '+viewer.primary.event_id+', pulse group '+g.group_id,
    g.categories.map(k=>viewer.positiveManifest.category_labels[k]).join(' · '),
    'Ge Edep '+g.ge_energy_keV.toPrecision(10)+' keV; source photon '+(g.source_photon_energy_keV===null?'unknown':g.source_photon_energy_keV.toPrecision(10)+' keV')+'.',
    'Source photon track(s): '+(g.source_photon_track_ids.join(', ')||'unresolved')+'. Group origin '+g.origin_time_ns+' ns; saved delay span '+Math.max(...g.relative_delays_ns)+' ns.',
    'Deposit diameter '+g.deposit_diameter_mm.toPrecision(6)+' mm; '+g.ge_raw_row_indices.length+' positive Ge steps ('+e.ge_step_count+' total Ge steps in primary).',
    'Observed in-window Compton creation sites: '+(g.observed_compton_site_count??'unknown')+'.',g.reason];
  if(g.root_non_ge_energy_keV!==undefined)lines.push('Recorded root-linked non-Ge Edep: '+g.root_non_ge_energy_keV+' keV; same-root Ge energy outside this group: '+g.root_other_group_ge_energy_keV+' keV.');
  if(e.graph_errors.length)lines.push('Graph errors: '+e.graph_errors.join('; '));
  for(const text of lines)paragraph($('evidence'),text);
  refreshDetails();
}
function representativeButtons(){
  $('representatives').replaceChildren();if(!viewer.data||viewer.requested.view!=='positive')return;
  for(const key of ['compact','compton1','compton2','partial']){const b=document.createElement('button'),rep=viewer.data.representatives[key],g=rep?viewer.evidence.get(rep.event_id).groups.find(g=>g.group_id===rep.group_id):null;
    b.textContent=viewer.positiveManifest.category_labels[key]+' ('+viewer.data.categories[key].length+')'+(g?' · Eγ '+g.source_photon_energy_keV.toPrecision(6)+' keV':'');b.disabled=!rep;
    b.onclick=()=>{viewer.category=key;$('category').value=key;selectEvent(rep.event_id,rep.group_id);};$('representatives').append(b);}
}
function resolveGroup(){
  clearGroup();
  if(viewer.requested.view==='assembly'){paragraph($('evidence'),'Assembly view: group IDs are return-navigation context only.');return;}
  const proof=viewer.evidence.get(viewer.primary.event_id);
  if(!proof)throw Error('This valid primary has no saved Ge-positive pulse group (zero-Ge or otherwise unrepresented).');
  const matches=proof.groups.filter(g=>viewer.category==='all'||g.categories.includes(viewer.category));
  const group=viewer.requested.group===null?matches[0]:matches.find(g=>g.group_id===viewer.requested.group);
  if(!group)throw Error('Requested group / candidate filter is not represented. No group is highlighted.');
  viewer.group=group;$('group').replaceChildren(...matches.map(g=>option(g.group_id,g.group_id+' · '+g.ge_energy_keV.toPrecision(6)+' keV')));
  $('group').disabled=false;$('group').value=String(group.group_id);describeGroup();
}
function normalizeRequest(identity){
  const q=new URLSearchParams({model:identity.model,view:identity.view});
  if(identity.event!==null)q.set('event',String(identity.event));if(identity.group!==null)q.set('group',String(identity.group));
  const r=parseViewerQuery('?'+q);if(identity.invalid)r.invalid=identity.invalid;return r;
}
async function applySelection(identity,options={}){
  const r=normalizeRequest(identity),ticket=++viewer.generation,previousModel=viewer.requested.model,previousScene=viewer.scene,previousMode=mode;
  viewer.requested=r;clearPrimary();viewer.overlayError='';$('overlayStatus').textContent='';$('status').className='';
  if(previousModel!==r.model){viewer.scene=null;clearOverlay();$('provenance').textContent='';$('census').textContent='';$('volumes').replaceChildren();$('originals').removeAttribute('href');clearModelLinks();}
  modelOptions(r.model);$('view').value=r.view;if(r.event!==null)$('eid').value=String(r.event);identityText();
  if(r.invalid){viewer.scene=null;clearOverlay();$('provenance').textContent='';$('census').textContent='';$('volumes').replaceChildren();$('originals').removeAttribute('href');clearModelLinks();$('status').textContent='Unavailable request: '+r.invalid+(options.rejectedInput===undefined?' Query: '+location.search:'');$('status').className='error';draw();return false;}
  applyMode(r.view);writeHistory(options.history||'push');draw();
  const current=()=>ticket===viewer.generation;
  try{
    $('status').textContent='Loading '+r.model+' saved assembly / primary…';
    const {manifest,scene}=await loadScene(r.model);if(!current())return false;
    if(viewer.scene!==scene)showScene(scene,manifest,r.model);else viewer.assemblyManifest=manifest;
    if(r.event===null){r.event=scene.event_index.ge_hit_ids[0]??0;viewer.requested={...r};$('eid').value=String(r.event);writeHistory(options.history==='none'?'none':'replace');identityText();}
    const primary=await loadPrimary(r.model,scene,r.event);if(!current())return false;
    viewer.primary=primary;const rows=primary.tables['stp/germanium'],energy=rows.reduce((s,row)=>s+row.edep,0);
    $('status').textContent=r.model+' primary '+r.event+' · '+rows.length+' recorded Ge steps · '+energy.toPrecision(8)+' keV Ge Edep · '+primary.tables.tracks.length+' creation vertices. '+(energy>0?'Ge-positive primary.':'Zero-Ge primary retained.');
    refreshDetails();if(previousScene!==scene||previousMode!==mode)fit();else draw();
  }catch(error){if(!current())return false;clearPrimary();$('status').textContent='Assembly unavailable: '+error.message;$('status').className='error';draw();return false;}
  if(r.view==='positive'||$('overlay').checked){
    let positiveLoaded=false;
    try{
      $('overlayStatus').textContent='Loading saved Ge-positive evidence…';
      const positive=await loadPositive(r.model,viewer.assemblyManifest,viewer.scene);if(!current())return false;
      viewer.positiveManifest=positive.manifest;viewer.data=positive.data;viewer.events=positive.events;viewer.evidence=positive.evidence;
      positiveLoaded=true;
      const oldCategory=viewer.category;$('category').replaceChildren(option('all','All saved groups'),...Object.entries(positive.manifest.category_labels).map(([k,label])=>option(k,label)));
      $('category').value=oldCategory;representativeButtons();resolveGroup();
      $('overlayStatus').textContent='All '+viewer.events.size+' saved Ge-positive primaries available; '+(viewer.group?'highlight: group '+viewer.group.group_id+'.':'no pulse group selected.');
      if(viewer.group&&r.group===null){viewer.requested.group=viewer.group.group_id;identityText();writeHistory(options.history==='none'?'none':'replace');}
    }catch(error){if(!current())return false;clearGroup();viewer.overlayError=error.message;
      // A group/category miss keeps the checked full overlay population. A load
      // failure clears all positive data, never the independently checked assembly.
      if(!positiveLoaded)clearOverlay();
      $('overlayStatus').textContent='Ge-positive selection unavailable: '+error.message+' Verified assembly / primary remains available.';
      paragraph($('evidence'),'No pulse group is highlighted. Requested identity is retained.');
    }
  }else{clearGroup();paragraph($('evidence'),'Assembly view: group IDs are return-navigation context only.');$('overlayStatus').textContent='Ge-positive overlay is off. All initial primaries remain available.';}
  refreshDetails();draw();return true;
}
function requestSelection(identity,options={}){pendingSelection=applySelection(identity,options);return pendingSelection;}
function selectModel(name){return requestSelection({...viewer.requested,model:name,invalid:''});}
function selectEvent(id,groupId=null){return requestSelection({...viewer.requested,event:id,group:groupId,invalid:''});}
function setView(view){return requestSelection({...viewer.requested,view,invalid:''});}
function filterCategory(){viewer.category=$('category').value;return requestSelection({...viewer.requested});}
function restoreViewerHistory(){
  viewer.category=history.state?.viewer===1&&categories.includes(history.state.category)?history.state.category:'all';
  return requestSelection(parseViewerQuery(location.search),{history:'none'});
}
function nextHit(forward){
  if(!viewer.scene)return;const ids=viewer.scene.event_index.ge_hit_ids,id=viewer.requested.event;
  const next=forward?ids.find(x=>x>id):ids.findLast(x=>x<id);
  if(next!==undefined)return selectEvent(next);$('status').textContent='No '+(forward?'later':'earlier')+' Ge-positive primary; selection unchanged.';
}
const position=(row,suffix='')=>['xloc','yloc','zloc'].map(k=>row[k+suffix]*1000);
function projected(p){
  const [x,y,z]=p.map((v,i)=>v-center[i]),a=Math.cos(yaw)*x+Math.sin(yaw)*z,b=-Math.sin(yaw)*x+Math.cos(yaw)*z;
  const c=Math.cos(pitch)*y-Math.sin(pitch)*b,d=Math.sin(pitch)*y+Math.cos(pitch)*b,s=Math.min(canvas.clientWidth,canvas.clientHeight)*.43/radius*zoom;
  return [canvas.clientWidth/2+a*s+panX,canvas.clientHeight/2-c*s+panY,d];
}
function line(a,b,c,width=1){ctx.beginPath();ctx.moveTo(a[0],a[1]);ctx.lineTo(b[0],b[1]);ctx.strokeStyle=c;ctx.lineWidth=width;ctx.stroke();}
function dot(p,c,size=3){const a=projected(p);ctx.beginPath();ctx.arc(a[0],a[1],size,0,Math.PI*2);ctx.fillStyle=c;ctx.fill();}
function chord(row,c,width=1){line(projected(position(row,'_pre')),projected(position(row,'_post')),c,width);}
function drawPositive(event,highlight=false){
  const proof=viewer.evidence.get(event.event_id);if(!proof)return;
  const photons=new Set(proof.relevant_photon_track_ids),groupRows=new Set(highlight?(viewer.group?.ge_raw_row_indices||[]):[]);
  for(const row of event.tables['stp/germanium']){const chosen=highlight&&groupRows.has(row.raw_row_index);ctx.globalAlpha=highlight?.95:.18;
    chord(row,chosen?'#ff8f61':highlight?'#ffe5a0':'#edd896',highlight?2:1);if(row.edep>0&&$('deposits').checked)dot(position(row),chosen?'#ff8f61':'#edd896',highlight?3:1.4);}
  if($('photons').checked){ctx.globalAlpha=highlight?.9:.12;
    for(const [name,rows] of Object.entries(event.tables))if(name.startsWith('stp/')&&name!=='stp/germanium')for(const row of rows)
      if(row.particle===22&&photons.has(row.trackid))chord(row,'#67cde4',highlight?2:1);
    for(const row of event.tables.tracks)if(row.particle===22&&photons.has(row.trackid))dot(position(row),'#67cde4',highlight?3:1.3);}
  ctx.globalAlpha=1;
}
function draw(){
  const ratio=globalThis.devicePixelRatio||1,w=canvas.clientWidth,h=canvas.clientHeight;
  if(canvas.width!==Math.round(w*ratio)||canvas.height!==Math.round(h*ratio)){canvas.width=Math.round(w*ratio);canvas.height=Math.round(h*ratio);}
  ctx.setTransform(ratio,0,0,ratio,0,0);ctx.clearRect(0,0,w,h);if(!viewer.scene)return;
  const meshes=viewer.scene.volumes.filter(v=>visible.has(v.name)&&(v.name==='germanium'||$('shells').checked)).map(v=>({v,points:v.vertices_global_mm.map(projected)}));
  if($('faces').checked){const faces=[];for(const {v,points}of meshes)for(const t of v.triangles)faces.push({p:t.map(i=>points[i]),c:color(v)});
    faces.sort((a,b)=>a.p.reduce((s,p)=>s+p[2],0)-b.p.reduce((s,p)=>s+p[2],0));ctx.globalAlpha=.045;
    for(const f of faces){ctx.beginPath();ctx.moveTo(f.p[0][0],f.p[0][1]);for(const p of f.p.slice(1))ctx.lineTo(p[0],p[1]);ctx.closePath();ctx.fillStyle=f.c;ctx.fill();}ctx.globalAlpha=1;}
  ctx.globalAlpha=.32;for(const {v,points}of meshes)for(const [a,b]of v.wireframe)line(points[a],points[b],color(v));ctx.globalAlpha=1;
  const primary=viewer.primary;
  if(primary){for(const [name,rows]of Object.entries(primary.tables))if(name.startsWith('stp/'))for(const row of rows){const ge=name==='stp/germanium';
    if($('steps').checked)chord(row,ge?'#ffed76':'#ffb063',1.8);
    if(ge&&row.edep>0&&$('deposits').checked&&viewer.requested.view==='assembly')dot(position(row),'#ffed76',2.5);}
    if($('births').checked)for(const row of primary.tables.tracks)dot(position(row),'#6ee4ff',2);}
  if($('overlay').checked)for(const event of viewer.events.values())if(!viewer.group||event.event_id!==primary?.event_id)drawPositive(event);
  if(primary&&$('detail').checked){let count=0,total=0;ctx.globalAlpha=.5;
    for(const [name,rows]of Object.entries(primary.tables))if(name.startsWith('stp/'))for(const row of rows){total++;if(count++<DETAIL_CAP)chord(row,'#8ca3b8');}
    ctx.globalAlpha=1;$('detailLimit').textContent='Optional detail: '+Math.min(total,DETAIL_CAP)+' / '+total+' recorded STEP chords drawn (cap '+DETAIL_CAP+'); every original row remains in the raw panel.';
  }else $('detailLimit').textContent='Optional detail caps drawing only; original rows and event census are never capped.';
  if(primary&&viewer.group)drawPositive(primary,true);
  dot(viewer.scene.source_position_global_mm,'#ffe169',5);const p=projected(viewer.scene.source_position_global_mm);ctx.fillStyle='#ffe169';ctx.font='13px system-ui';ctx.fillText('Source (+y / curved wall)',p[0]+9,p[1]-8);
  const origin=projected([0,0,0]);for(const [q,c,text]of [[[15,0,0],'#ff8080','+x'],[[0,15,0],'#85ef9a','+y'],[[0,0,15],'#86b6ff','+z']]){const point=projected(q);line(origin,point,c,2);ctx.fillStyle=c;ctx.fillText(text,point[0]+3,point[1]-3);}
}
function fit(view='default'){
  yaw=view==='front'?0:view==='side'?Math.PI/2:.55;pitch=view==='default'?-.2:0;zoom=1;panX=panY=0;
  if(viewer.scene){const pts=viewer.scene.volumes.filter(v=>visible.has(v.name)&&(v.name==='germanium'||$('shells').checked)).flatMap(v=>v.vertices_global_mm);pts.push(viewer.scene.source_position_global_mm);
    const lo=[Infinity,Infinity,Infinity],hi=[-Infinity,-Infinity,-Infinity];for(const p of pts)for(let a=0;a<3;a++){lo[a]=Math.min(lo[a],p[a]);hi[a]=Math.max(hi[a],p[a]);}
    center=lo.map((v,i)=>(v+hi[i])/2);radius=1;for(const p of pts)radius=Math.max(radius,Math.hypot(...p.map((v,i)=>v-center[i])));}
  draw();
}
$('model').onchange=()=>selectModel($('model').value);$('view').onchange=()=>setView($('view').value);
function showInput(){
  const raw=$('eid').value,id=/^(0|[1-9][0-9]*)$/.test(raw)?Number(raw):NaN;
  if(!Number.isSafeInteger(id)||id>9999)return requestSelection({...viewer.requested,event:null,group:null,
    invalid:'Invalid typed primary ID '+JSON.stringify(raw)+'; use an integer from 0 to 9999.'},{rejectedInput:raw});
  return selectEvent(id);
}
$('show').onclick=showInput;$('eid').onkeydown=e=>{if(e.key==='Enter')showInput();};
$('prev').onclick=()=>nextHit(false);$('next').onclick=()=>nextHit(true);$('category').onchange=filterCategory;
$('group').onchange=()=>selectEvent(viewer.requested.event,Number($('group').value));
$('recordPanel').ontoggle=$('evidencePanel').ontoggle=refreshDetails;
for(const id of ['steps','births','deposits','faces','photons','detail'])$(id).onchange=draw;
$('overlay').onchange=()=>requestSelection({...viewer.requested});$('shells').onchange=()=>fit();
document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>fit(b.dataset.view));
$('zin').onclick=()=>{zoom=Math.min(50,zoom*1.3);draw();};$('zout').onclick=()=>{zoom=Math.max(.1,zoom/1.3);draw();};
$('pan').onclick=()=>{panMode=!panMode;$('pan').setAttribute('aria-pressed',String(panMode));};
let drag=null;canvas.oncontextmenu=e=>e.preventDefault();canvas.onpointerdown=e=>{canvas.setPointerCapture(e.pointerId);drag={x:e.clientX,y:e.clientY,pan:panMode||e.shiftKey||e.button===2};};canvas.onpointerup=canvas.onpointercancel=()=>drag=null;
canvas.onpointermove=e=>{if(!drag)return;const dx=e.clientX-drag.x,dy=e.clientY-drag.y;drag.x=e.clientX;drag.y=e.clientY;if(drag.pan){panX+=dx;panY+=dy;}else{yaw+=dx*.008;pitch=Math.max(-1.5,Math.min(1.5,pitch+dy*.008));}draw();};
canvas.addEventListener('wheel',e=>{e.preventDefault();zoom=Math.max(.1,Math.min(50,zoom*Math.exp(-e.deltaY*.001)));draw();},{passive:false});new ResizeObserver(draw).observe(canvas);
globalThis.addEventListener('popstate',restoreViewerHistory);
globalThis.unifiedViewer={requestSelection,selectModel,selectEvent,setView,filterCategory,restoreViewerHistory,
  whenIdle:()=>pendingSelection,
  getState:()=>({requested:{...viewer.requested},scene:viewer.scene,primary:viewer.primary,group:viewer.group,category:viewer.category,
    overlayCount:viewer.events.size,overlayError:viewer.overlayError,generation:viewer.generation})};
const viewerReady=requestSelection(viewer.requested,{history:'replace'});
globalThis.unifiedViewer.ready=viewerReady;
