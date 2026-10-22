/* Native mesh canvas projection/controls adapted from tools/geometry_events.html.
   GeGI uses its own saved hierarchy and identity transform; no event simulation.
   Saved-event contract: {kind:'gegi_saved_path_display_v1', records:[{
     original_identity:{raw_primary_id,pulse_group_id,...},
     radiation:{event_id,tables:{tracks:[], 'stp/germanium':[], ...}},
     signal_event?:{original_identity,reconstruction,channels,...}, provenance?:{...}
   }]}. Alternatively radiation may contain exact normalized segments (pre_mm,
   post_mm, track_id, parent_track_id, particle_pdg, energy_keV, time_ns,
   raw_row_index) and births (position_mm, track_id,...), with explicit scope
   'positive_energy_Ge_scored_step_chords_only'. Raw table coordinates are metres;
   normalized/display coordinates are millimetres. */
(function(global){
'use strict';
const finite=Number.isFinite,vector=p=>Array.isArray(p)&&p.length===3&&p.every(finite);
function requireValue(ok,message){if(!ok)throw Error(message);}
function position(row,suffix=''){return ['xloc','yloc','zloc'].map(k=>row[k+suffix]*1000);}
function identityKey(identity){return ['source_group','chunk_index','raw_primary_id','pulse_group_id'].map(k=>identity?.[k]??'').join('/');}
function validatePayload(payload){
  requireValue(payload?.kind==='gegi_saved_path_display_v1'&&Array.isArray(payload.records),'Choose a saved GeGI path display.');
  const seen=new Set();
  for(const record of payload.records){
    const identity=record.original_identity,event=record.radiation,key=identityKey(identity);
    requireValue(Number.isInteger(identity?.raw_primary_id)&&identity.raw_primary_id>=0&&Number.isInteger(identity?.pulse_group_id)&&identity.pulse_group_id>=0,'Original primary and pulse-group IDs are required.');
    requireValue(!seen.has(key),'Duplicate original pulse-group identity.');seen.add(key);
    requireValue(event?.event_id===identity.raw_primary_id,'Radiation primary identity differs from the selected pulse group.');
    if(Array.isArray(event.segments)){
      requireValue(event.scope==='positive_energy_Ge_scored_step_chords_only'&&Array.isArray(event.births),'Normalized radiation scope and saved births are required.');
      for(const row of event.segments)requireValue(vector(row.pre_mm)&&vector(row.post_mm)&&(row.position_mm===undefined||vector(row.position_mm))&&finite(row.energy_keV)&&row.energy_keV>0&&Number.isInteger(row.raw_row_index)&&row.raw_row_index>=0&&Number.isInteger(row.track_id)&&Number.isInteger(row.parent_track_id)&&Number.isInteger(row.particle_pdg)&&finite(row.time_ns),'Invalid saved positive-energy Ge step.');
      for(const row of event.births)requireValue(vector(row.position_mm)&&Number.isInteger(row.track_id)&&Number.isInteger(row.parent_track_id)&&Number.isInteger(row.particle_pdg)&&finite(row.time_ns),'Invalid saved creation vertex.');
    }else{
    requireValue(event.tables&&typeof event.tables==='object'&&Array.isArray(event.tables.tracks)&&Array.isArray(event.tables['stp/germanium']),'Saved track and Ge step tables are required.');
    const tracks=new Map();
    for(const row of event.tables.tracks){
      requireValue(row.evtid===event.event_id&&Number.isInteger(row.raw_row_index)&&row.raw_row_index>=0&&Number.isInteger(row.trackid)&&!tracks.has(row.trackid)&&vector(position(row)),'Invalid saved track identity or creation position.');
      tracks.set(row.trackid,row);
    }
    for(const [table,rows]of Object.entries(event.tables)){
      if(!table.startsWith('stp/'))continue;
      requireValue(Array.isArray(rows),'Invalid saved step table.');
      for(const row of rows){
        const track=tracks.get(row.trackid);
        requireValue(row.evtid===event.event_id&&Number.isInteger(row.raw_row_index)&&row.raw_row_index>=0&&vector(position(row,'_pre'))&&vector(position(row,'_post'))&&vector(position(row))&&finite(row.edep)&&row.edep>=0,'Invalid saved step identity, coordinates or deposited energy.');
        requireValue(track&&track.parent_trackid===row.parent_trackid&&track.particle===row.particle,'Saved step and track ancestry differ.');
      }
    }
    }
    if(record.signal_event){
      const signalIdentity=record.signal_event.original_identity;
      requireValue(signalIdentity&&identityKey(signalIdentity)===key,'Saved signal and radiation identities differ.');
      for(const k of ['campaign_initial_id','source_global_initial_id'])if(identity[k]!==undefined||signalIdentity[k]!==undefined)requireValue(identity[k]===signalIdentity[k],'Saved signal and radiation '+k+' differ.');
    }
  }
  return payload;
}
function pathPrimitives(record){
  const segments=[],deposits=[],births=[];
  if(Array.isArray(record.radiation.segments)){
    for(const saved of record.radiation.segments){
      const row={...saved,trackid:saved.track_id,parent_trackid:saved.parent_track_id,particle:saved.particle_pdg,edep:saved.energy_keV};
      segments.push({a:saved.pre_mm,b:saved.post_mm,table:'stp/germanium',row});
      // Preserve a saved deposit position; otherwise explicitly identify the
      // post-step marker, without inventing a chord midpoint or centroid.
      deposits.push({p:saved.position_mm||saved.post_mm,table:'stp/germanium',row,position_basis:saved.position_mm?'saved_deposit':'post_step'});
    }
    for(const row of record.radiation.births)births.push({p:row.position_mm,row});
    return {segments,deposits,births};
  }
  for(const [table,rows]of Object.entries(record.radiation.tables)){
    if(!table.startsWith('stp/'))continue;
    for(const row of rows){
      segments.push({a:position(row,'_pre'),b:position(row,'_post'),table,row});
      if(table==='stp/germanium'&&row.edep>0)deposits.push({p:position(row),table,row});
    }
  }
  for(const row of record.radiation.tables.tracks)births.push({p:position(row),row});
  return {segments,deposits,births};
}
function reconstructedSites(record){
  const hypotheses=record.signal_event?.reconstruction?.paired_site_hypotheses||[];
  return hypotheses.flatMap(h=>(h.sites||[]).filter(s=>vector(s.position_mm)).map((site,index)=>({site,index,pairing_index:h.pairing_index})));
}
function selectionGate(clear){
  let generation=0;
  return {invalidate(){++generation;clear();},async run(load,apply,fail){const ticket=++generation;clear();try{const value=await load();if(ticket!==generation)return false;apply(value);return true;}catch(error){if(ticket===generation)fail(error);return false;}}};
}
const api={validatePayload,pathPrimitives,reconstructedSites,identityKey,selectionGate};
if(typeof module!=='undefined'&&module.exports)module.exports=api;
global.GeGIAssemblyEvents=api;
if(typeof document==='undefined')return;
const $=id=>document.getElementById(id), canvas=$('canvas'),ctx=canvas.getContext('2d');
const scene=JSON.parse($('scene-data').textContent), visible=new Set(scene.volumes.filter(v=>v.material!=='G4_Galactic').map(v=>v.name));
let yaw=.55,pitch=-.35,zoom=1,panX=0,panY=0,center=[0,0,-26.4],radius=76;
let payload=null,selected=null,journey=null;
function cutPolygon(points){
  const result=[];
  for(let i=0;i<points.length;i++){
    const a=points[i],b=points[(i+1)%points.length],inside=a[1]<=0,other=b[1]<=0;
    if(inside)result.push(a);
    if(inside!==other){const t=-a[1]/(b[1]-a[1]);result.push(a.map((v,j)=>v+t*(b[j]-v)));}
  }
  return result;
}
function cutLine(a,b){
  if(a[1]>0&&b[1]>0)return null;
  if(a[1]<=0&&b[1]<=0)return[a,b];
  const t=-a[1]/(b[1]-a[1]),p=a.map((v,j)=>v+t*(b[j]-v));
  return a[1]<=0?[a,p]:[p,b];
}
function projected(p){
  const [x,y,z]=p.map((v,i)=>v-center[i]);
  const a=Math.cos(yaw)*x+Math.sin(yaw)*z,b=-Math.sin(yaw)*x+Math.cos(yaw)*z;
  const c=Math.cos(pitch)*y-Math.sin(pitch)*b,d=Math.sin(pitch)*y+Math.cos(pitch)*b;
  const scale=Math.min(canvas.clientWidth,canvas.clientHeight)*.43/radius*zoom;
  return[canvas.clientWidth/2+a*scale+panX,canvas.clientHeight/2-c*scale+panY,d];
}
function line(a,b,color,width=1){ctx.beginPath();ctx.moveTo(a[0],a[1]);ctx.lineTo(b[0],b[1]);ctx.strokeStyle=color;ctx.lineWidth=width;ctx.stroke();}
function dot(p,color,size=3){const q=projected(p);ctx.beginPath();ctx.arc(q[0],q[1],size,0,Math.PI*2);ctx.fillStyle=color;ctx.fill();}
function drawEvent(){
  if(!selected)return;
  const {segments,deposits,births}=pathPrimitives(selected);
  if($('steps').checked)for(const segment of segments){const ge=segment.table==='stp/germanium',gamma=segment.row.particle===22;line(projected(segment.a),projected(segment.b),gamma?'#6ee4ff':ge?'#ffed76':'#ffb063',gamma?2.5:1.7);}
  if($('deposits').checked)for(const item of deposits)dot(item.p,'#ffed76',3.4);
  if($('births').checked)for(const item of births)dot(item.p,'#e39cff',2.2);
  if($('reconstructed').checked){ctx.font='12px system-ui';for(const item of reconstructedSites(selected)){const p=projected(item.site.position_mm);ctx.strokeStyle='#a6f0aa';ctx.lineWidth=2;ctx.strokeRect(p[0]-5,p[1]-5,10,10);ctx.fillStyle='#a6f0aa';ctx.fillText('pair '+item.pairing_index+' site '+(item.index+1),p[0]+8,p[1]-5);}}
}
function draw(){
  const ratio=devicePixelRatio||1,w=canvas.clientWidth,h=canvas.clientHeight;
  if(canvas.width!==Math.round(w*ratio)||canvas.height!==Math.round(h*ratio)){canvas.width=Math.round(w*ratio);canvas.height=Math.round(h*ratio);}
  ctx.setTransform(ratio,0,0,ratio,0,0);ctx.clearRect(0,0,w,h);
  const meshes=scene.volumes.filter(v=>visible.has(v.name)),cut=$('cut').checked,faces=[];
  if($('faces').checked){
    for(const v of meshes)for(const t of v.triangles){let ps=t.map(i=>v.vertices_global_mm[i]);if(cut)ps=cutPolygon(ps);if(ps.length>2)faces.push({p:ps.map(projected),c:v.color});}
    faces.sort((a,b)=>a.p.reduce((s,p)=>s+p[2],0)/a.p.length-b.p.reduce((s,p)=>s+p[2],0)/b.p.length);
    ctx.globalAlpha=.1;for(const f of faces){ctx.beginPath();ctx.moveTo(f.p[0][0],f.p[0][1]);for(const p of f.p.slice(1))ctx.lineTo(p[0],p[1]);ctx.closePath();ctx.fillStyle=f.c;ctx.fill();}ctx.globalAlpha=1;
  }
  ctx.globalAlpha=.35;
  for(const v of meshes)for(const edge of v.wireframe){let ps=edge.map(i=>v.vertices_global_mm[i]);if(cut)ps=cutLine(...ps);if(ps)line(...ps.map(projected),v.color);}
  ctx.globalAlpha=1;
  if(cut)for(const v of meshes)for(const seg of v.section_y0_mm)line(...seg.map(projected),v.color,2);
  drawEvent();
  const origin=projected([0,0,0]);ctx.font='14px system-ui';
  for(const [p,c,t] of [[[20,0,0],'#ff9090','+x'],[[0,20,0],'#83e7a6','+y'],[[0,0,20],'#9dbfff','+z front']]){const q=projected(p);line(origin,q,c,2);ctx.fillStyle=c;ctx.fillText(t,q[0]+4,q[1]-4);}
  $('status').textContent=`${visible.size} of ${scene.volumes.length} assembly volumes shown · ${cut?'half cutaway y ≤ 0':'complete surfaces'} · zoom ${zoom.toFixed(2)}×`;
}
function fit(view='default'){
  yaw=view==='side'?0:view==='front'?0:.55;pitch=view==='side'?-Math.PI/2:view==='front'?0:-.35;
  zoom=1;panX=panY=0;
  const points=scene.volumes.filter(v=>v.material!=='G4_Galactic').flatMap(v=>v.vertices_global_mm);
  if(view==='event'&&selected){const p=pathPrimitives(selected);for(const s of p.segments)points.push(s.a,s.b);if($('births').checked)points.push(...p.births.map(b=>b.p));}
  const lo=[Infinity,Infinity,Infinity],hi=[-Infinity,-Infinity,-Infinity];for(const p of points)for(let i=0;i<3;i++){lo[i]=Math.min(lo[i],p[i]);hi[i]=Math.max(hi[i],p[i]);}
  center=lo.map((v,i)=>(v+hi[i])/2);radius=Math.max(...points.map(p=>Math.hypot(...p.map((v,i)=>v-center[i]))));draw();
}
for(const v of scene.volumes){const label=document.createElement('label');label.className='volume';const box=document.createElement('input');box.type='checkbox';box.checked=visible.has(v.name);box.setAttribute('aria-label',v.label);box.onchange=()=>{if(box.checked)visible.add(v.name);else visible.delete(v.name);draw();};const title=document.createElement('span');title.textContent=v.label;title.style.color=v.color;const small=document.createElement('small');small.textContent=v.material+' · '+v.basis;label.append(box,title,small);$('volumes').append(label);}
function clearEvent(){selected=null;journey?.destroy();journey=null;$('event-records').replaceChildren();$('signal-journey').replaceChildren();$('signal-journey').hidden=true;$('event-identity').textContent='';$('journey-link').hidden=true;$('reconstructed').checked=false;$('reconstructed').disabled=true;$('reconstructed-layer').hidden=$('reconstructed-key').hidden=true;draw();}
const gate=selectionGate(clearEvent);
function eventError(error){$('event-status').textContent='Saved display unavailable: '+error.message;}
function showRecords(){
  const panel=$('event-record-panel');$('event-records').replaceChildren();if(!panel.open||!selected)return;
  const pre=document.createElement('pre');pre.textContent=JSON.stringify({original_identity:selected.original_identity,provenance:selected.provenance,radiation:selected.radiation},null,2);$('event-records').append(pre);
}
function chooseEvent(index){
  gate.invalidate();if(!payload?.records[index])return;
  selected=payload.records[index];$('event-select').value=String(index);
  const id=selected.original_identity,p=pathPrimitives(selected),energy=p.deposits.reduce((s,d)=>s+d.row.edep,0);
  $('event-identity').textContent=[id.source_group,'campaign initial '+(id.campaign_initial_id??'unavailable'),'chunk '+(id.chunk_index??'unavailable'),'raw primary '+id.raw_primary_id,'pulse group '+id.pulse_group_id].filter(Boolean).join(' · ');
  const restricted=selected.radiation.scope==='positive_energy_Ge_scored_step_chords_only';
  const postOnly=p.deposits.some(d=>d.position_basis==='post_step');
  $('event-status').textContent=p.segments.length+' recorded '+(restricted?'positive-energy Ge':'scored')+' STEP chords · '+energy.toPrecision(8)+' keV '+(restricted?'selected pulse-group':'full-primary')+' truth Edep. '+(restricted?'Only the saved pulse-group Ge steps are available here; passive-material and zero-energy steps are absent. '+(postOnly?'Markers without a separate saved deposit position use the recorded post-step point.':'Markers use the original saved deposit positions.'):'The matched pulse group may contain a subset of these deposits.');
  $('previous-event').disabled=index===0;$('next-event').disabled=index===payload.records.length-1;
  const signal=selected.signal_event;
  if(signal&&global.GeGISignalJourney?.mount){journey=global.GeGISignalJourney.mount($('signal-journey'),{groups:{[selected.label||id.source_group||'Selected event']:{representative:signal}},criteria:payload.criteria||{}});$('journey-link').hidden=false;$('signal-journey').hidden=false;}
  else if(signal){const p=document.createElement('p');p.textContent='Saved signals are present. Load the shared GeGI signal walkthrough to inspect them.';$('signal-journey').append(p);$('signal-journey').hidden=false;}
  else $('event-status').textContent+=' Radiation-only sample; no saved signal counterpart is attached.';
  const hasReconstruction=!!signal?.reconstruction;
  $('reconstructed').disabled=!hasReconstruction;$('reconstructed-layer').hidden=$('reconstructed-key').hidden=!hasReconstruction;showRecords();draw();
}
function setPayload(value){
  validatePayload(value);payload=value;$('event-select').replaceChildren();
  for(const [i,record]of value.records.entries()){const option=document.createElement('option'),id=record.original_identity;option.value=String(i);option.textContent=(record.label||id.source_group||'Saved event')+' · initial '+(id.campaign_initial_id??id.raw_primary_id)+' / group '+id.pulse_group_id;$('event-select').append(option);}
  $('event-controls').hidden=!value.records.length;
  if(value.records.length)chooseEvent(0);else{gate.invalidate();$('event-status').textContent='No retained nonzero saved event is available. Full event counts remain in the original data; no zero waveform is fabricated.';}
  return value.records.length;
}
api.setPayload=setPayload;api.select=chooseEvent;
$('event-select').onchange=()=>chooseEvent(Number($('event-select').value));
$('previous-event').onclick=()=>chooseEvent(Number($('event-select').value)-1);$('next-event').onclick=()=>chooseEvent(Number($('event-select').value)+1);
$('event-record-panel').ontoggle=showRecords;
$('open-events').onchange=()=>{const file=$('open-events').files[0];if(!file)return;$('event-status').textContent='Reading saved display…';gate.run(async()=>validatePayload(JSON.parse(await file.text())),setPayload,eventError);};
document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>fit(b.dataset.view));
for(const id of ['cut','faces','steps','births','deposits','reconstructed'])$(id).onchange=draw;
function zoomBy(f){zoom=Math.max(.15,Math.min(30,zoom*f));draw();}
$('zin').onclick=()=>zoomBy(1.25);$('zout').onclick=()=>zoomBy(.8);
let drag=null;canvas.oncontextmenu=e=>e.preventDefault();canvas.onpointerdown=e=>{canvas.setPointerCapture(e.pointerId);drag={x:e.clientX,y:e.clientY,pan:e.shiftKey||e.button===2};};canvas.onpointerup=canvas.onpointercancel=()=>drag=null;
canvas.onpointermove=e=>{if(!drag)return;const dx=e.clientX-drag.x,dy=e.clientY-drag.y;drag.x=e.clientX;drag.y=e.clientY;if(drag.pan){panX+=dx;panY+=dy;}else{yaw+=dx*.008;pitch=Math.max(-Math.PI/2,Math.min(Math.PI/2,pitch+dy*.008));}draw();};
canvas.addEventListener('wheel',e=>{e.preventDefault();zoomBy(Math.exp(-e.deltaY*.001));},{passive:false});
canvas.onkeydown=e=>{if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','+','=','-','r','R'].includes(e.key))return;e.preventDefault();if(e.key==='r'||e.key==='R')return fit();if(e.key==='+'||e.key==='=')return zoomBy(1.25);if(e.key==='-')return zoomBy(.8);if(e.key==='ArrowLeft')yaw-=.12;if(e.key==='ArrowRight')yaw+=.12;if(e.key==='ArrowUp')pitch=Math.max(-Math.PI/2,pitch-.12);if(e.key==='ArrowDown')pitch=Math.min(Math.PI/2,pitch+.12);draw();};
new ResizeObserver(draw).observe(canvas);fit();
const embedded=$('event-data');
if(embedded?.textContent.trim()){try{setPayload(JSON.parse(embedded.textContent));}catch(error){eventError(error);}}
})(typeof globalThis!=='undefined'?globalThis:this);
