/* Native mesh canvas projection/controls adapted from tools/geometry_events.html.
   GeGI uses its own saved hierarchy and identity transform; no event simulation. */
'use strict';
const $=id=>document.getElementById(id), canvas=$('canvas'),ctx=canvas.getContext('2d');
const scene=JSON.parse($('scene-data').textContent), visible=new Set(scene.volumes.filter(v=>v.material!=='G4_Galactic').map(v=>v.name));
let yaw=.55,pitch=-.35,zoom=1,panX=0,panY=0,center=[0,0,-26.4],radius=76;
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
  const origin=projected([0,0,0]);ctx.font='14px system-ui';
  for(const [p,c,t] of [[[20,0,0],'#ff9090','+x'],[[0,20,0],'#83e7a6','+y'],[[0,0,20],'#9dbfff','+z front']]){const q=projected(p);line(origin,q,c,2);ctx.fillStyle=c;ctx.fillText(t,q[0]+4,q[1]-4);}
  $('status').textContent=`${visible.size} of ${scene.volumes.length} assembly volumes shown · ${cut?'half cutaway y ≤ 0':'complete surfaces'} · zoom ${zoom.toFixed(2)}×`;
}
function fit(view='default'){
  yaw=view==='side'?0:view==='front'?0:.55;pitch=view==='side'?-Math.PI/2:view==='front'?0:-.35;
  zoom=1;panX=panY=0;
  const points=scene.volumes.filter(v=>v.material!=='G4_Galactic').flatMap(v=>v.vertices_global_mm);
  const lo=[Infinity,Infinity,Infinity],hi=[-Infinity,-Infinity,-Infinity];for(const p of points)for(let i=0;i<3;i++){lo[i]=Math.min(lo[i],p[i]);hi[i]=Math.max(hi[i],p[i]);}
  center=lo.map((v,i)=>(v+hi[i])/2);radius=Math.max(...points.map(p=>Math.hypot(...p.map((v,i)=>v-center[i]))));draw();
}
for(const v of scene.volumes){const label=document.createElement('label');label.className='volume';const box=document.createElement('input');box.type='checkbox';box.checked=visible.has(v.name);box.setAttribute('aria-label',v.label);box.onchange=()=>{if(box.checked)visible.add(v.name);else visible.delete(v.name);draw();};const title=document.createElement('span');title.textContent=v.label;title.style.color=v.color;const small=document.createElement('small');small.textContent=v.material+' · '+v.basis;label.append(box,title,small);$('volumes').append(label);}
document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>fit(b.dataset.view));
for(const id of ['cut','faces'])$(id).onchange=draw;
function zoomBy(f){zoom=Math.max(.15,Math.min(30,zoom*f));draw();}
$('zin').onclick=()=>zoomBy(1.25);$('zout').onclick=()=>zoomBy(.8);
let drag=null;canvas.oncontextmenu=e=>e.preventDefault();canvas.onpointerdown=e=>{canvas.setPointerCapture(e.pointerId);drag={x:e.clientX,y:e.clientY,pan:e.shiftKey||e.button===2};};canvas.onpointerup=canvas.onpointercancel=()=>drag=null;
canvas.onpointermove=e=>{if(!drag)return;const dx=e.clientX-drag.x,dy=e.clientY-drag.y;drag.x=e.clientX;drag.y=e.clientY;if(drag.pan){panX+=dx;panY+=dy;}else{yaw+=dx*.008;pitch=Math.max(-Math.PI/2,Math.min(Math.PI/2,pitch+dy*.008));}draw();};
canvas.addEventListener('wheel',e=>{e.preventDefault();zoomBy(Math.exp(-e.deltaY*.001));},{passive:false});
canvas.onkeydown=e=>{if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','+','=','-','r','R'].includes(e.key))return;e.preventDefault();if(e.key==='r'||e.key==='R')return fit();if(e.key==='+'||e.key==='=')return zoomBy(1.25);if(e.key==='-')return zoomBy(.8);if(e.key==='ArrowLeft')yaw-=.12;if(e.key==='ArrowRight')yaw+=.12;if(e.key==='ArrowUp')pitch=Math.max(-Math.PI/2,pitch-.12);if(e.key==='ArrowDown')pitch=Math.min(Math.PI/2,pitch+.12);draw();};
new ResizeObserver(draw).observe(canvas);fit();
