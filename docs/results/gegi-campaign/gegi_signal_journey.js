/* Shared saved-data GeGI walkthrough. No reconstruction, fitting or network calls.
 * mount(element,{groups:{label:{representative:event,...}},criteria?},options?)
 * accepts publication representatives or original student events. Only the saved
 * event.reconstruction supplies sites/cones; event.sites (truth) is never read.
 */
(function (global) {
  'use strict';
  const RAD=Math.PI/180, REST_KEV=510.99895069;
  const palette=['#b74d18','#006e9a','#7252a0','#24784b'];
  const finite=Number.isFinite, clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
  const dot=(a,b)=>a.reduce((s,v,i)=>s+v*b[i],0);
  const add=(a,b)=>a.map((v,i)=>v+b[i]);
  const mul=(a,k)=>a.map(v=>v*k);
  const norm=a=>Math.hypot(...a);
  const unit=a=>mul(a,1/norm(a));
  const cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
  const fmt=(v,n=3)=>finite(v)?Number(v.toPrecision(n)).toLocaleString('en-US',{maximumFractionDigits:8}):'unknown';
  const vec=v=>Array.isArray(v)&&v.length===3&&v.every(finite);

  function validCones(event) {
    const cones=event?.reconstruction?.cones;
    if(event?.reconstruction?.status!=='accepted'||!Array.isArray(cones))return [];
    const valid=cones.length>0&&cones.every(c=>vec(c.axis)&&vec(c.vertex_mm)&&Math.abs(norm(c.axis)-1)<1e-7&&
      finite(c.half_angle_deg)&&c.half_angle_deg>=0&&c.half_angle_deg<=180&&finite(c.weight)&&c.weight>0)&&
      Math.abs(cones.reduce((s,c)=>s+c.weight,0)-1)<1e-8;
    // Never silently turn a malformed hypothesis set into a selected subset.
    return valid?cones:[];
  }
  function coneRay(cone,phiDeg) {
    const axis=cone.axis,seed=Math.abs(axis[2])<.9?[0,0,1]:[0,1,0];
    const u=unit(cross(axis,seed)),v=cross(axis,u),theta=cone.half_angle_deg*RAD,phi=phiDeg*RAD;
    return add(mul(axis,Math.cos(theta)),mul(add(mul(u,Math.cos(phi)),mul(v,Math.sin(phi))),Math.sin(theta)));
  }
  function directionMap(cones,step=5,sigma=5) {
    const xs=Array.from({length:360/step},(_,i)=>-180+i*step);
    const ys=Array.from({length:180/step},(_,i)=>-90+step/2+i*step);
    const areas=ys.map(y=>step*RAD*(Math.sin((y+step/2)*RAD)-Math.sin((y-step/2)*RAD)));
    const rays=ys.map(y=>xs.map(x=>[Math.cos(y*RAD)*Math.cos(x*RAD),Math.cos(y*RAD)*Math.sin(x*RAD),Math.sin(y*RAD)]));
    const values=ys.map(()=>xs.map(()=>0));
    for(const cone of cones) {
      const scores=rays.map(row=>row.map(ray=>Math.exp(-.5*((Math.acos(clamp(dot(ray,cone.axis),-1,1))/RAD-cone.half_angle_deg)/sigma)**2)));
      const total=scores.reduce((s,row,j)=>s+row.reduce((a,b)=>a+b,0)*areas[j],0);
      if(total>0)for(let j=0;j<ys.length;j++)for(let i=0;i<xs.length;i++)values[j][i]+=cone.weight*scores[j][i]/total;
    }
    return {xs,ys,values,areas,units:'weighted pulse groups / sr',kind:'direction',step,sigma};
  }
  function planeMap(cones,z=40,step=2,sigma=5) {
    const xs=Array.from({length:240/step},(_,i)=>-120+step/2+i*step),ys=xs.slice();
    const values=ys.map(()=>xs.map(()=>0));let unmappedWeight=0;
    for(const cone of cones) {
      const scores=ys.map(y=>xs.map(x=>{
        const delta=[x-cone.vertex_mm[0],y-cone.vertex_mm[1],z-cone.vertex_mm[2]],distance=norm(delta);
        return distance?Math.exp(-.5*((Math.acos(clamp(dot(delta,cone.axis)/distance,-1,1))/RAD-cone.half_angle_deg)/sigma)**2):0;
      }));
      const total=scores.reduce((s,row)=>s+row.reduce((a,b)=>a+b,0),0)*step*step;
      if(total>0)for(let j=0;j<ys.length;j++)for(let i=0;i<xs.length;i++)values[j][i]+=cone.weight*scores[j][i]/total;
      else unmappedWeight+=cone.weight;
    }
    return {xs,ys,values,z,step,sigma,unmappedWeight,units:'weighted pulse groups / mm²',kind:'plane'};
  }
  function entries(payload) {
    return Object.entries(payload?.groups||{}).map(([label,g])=>({label,...g,event:g.representative}));
  }
  function illustrativeMap(records,kind='direction',criteria={}) {
    const cones=records.flatMap(r=>validCones(r.event));
    return kind==='plane'?planeMap(cones,criteria.plane_z_mm??40,criteria.plane_bin_mm??2,criteria.kernel_sigma_deg??5):
      directionMap(cones,criteria.angular_bin_deg??5,criteria.kernel_sigma_deg??5);
  }
  const pure={REST_KEV,coneRay,directionMap,planeMap,validCones,entries,illustrativeMap};
  if(typeof module!=='undefined'&&module.exports)module.exports=pure;
  global.GeGISignalJourney={...pure,mount};

  function mount(element,payload,options={}) {
    const doc=element.ownerDocument;
    function el(tag,text,cls) {const n=doc.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
    function svg(tag,attrs={}) {const n=doc.createElementNS('http://www.w3.org/2000/svg',tag);for(const [k,v]of Object.entries(attrs))n.setAttribute(k,String(v));return n;}
    function textSvg(x,y,text,attrs={}) {const n=svg('text',{x,y,...attrs});n.textContent=text;return n;}
    function paragraph(parent,text,cls) {const p=el('p',text,cls);parent.append(p);return p;}
    function select(parent,label,values,value,change) {const wrap=el('label',label+' '),s=el('select');for(const [v,title]of values){const o=el('option',title);o.value=v;s.append(o);}s.value=String(value);s.onchange=()=>change(s.value);wrap.append(s);parent.append(wrap);return s;}
    function range(parent,label,min,max,value,change) {const wrap=el('label'),caption=el('span',label+' '),output=el('output',String(value)),input=el('input');input.type='range';input.min=min;input.max=max;input.value=value;input.setAttribute('aria-label',label);input.oninput=()=>{output.textContent=input.value;change(Number(input.value));};wrap.append(caption,output,input);parent.append(wrap);return input;}
    function table(parent,headers,rows) {const wrap=el('div',undefined,'gj-scroll'),t=el('table'),head=el('tr');for(const h of headers)head.append(el('th',h));t.append(head);for(const row of rows){const tr=el('tr');for(const v of row)tr.append(el('td',String(v)));t.append(tr);}wrap.append(t);parent.append(wrap);}
    function section(title) {const p=el('section',undefined,'gj-card');p.append(el('h3',title));return p;}
    const css=`.gegi-journey{font:16px/1.55 system-ui;color:#173047}.gegi-journey *{box-sizing:border-box}.gegi-journey .gj-intro{font-size:1.08em;max-width:78ch}.gegi-journey .gj-controls,.gegi-journey .gj-steps{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:14px 0}.gegi-journey label{display:inline-flex;align-items:center;gap:6px;flex-wrap:wrap}.gegi-journey select,.gegi-journey button{font:inherit;padding:7px 10px;border:1px solid #9bb0bf;border-radius:6px;background:#fff;color:#173047;max-width:100%}.gegi-journey button{cursor:pointer}.gegi-journey button[aria-current=step]{background:#075e80;color:white;border-color:#075e80}.gegi-journey input[type=range]{width:145px}.gegi-journey .gj-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,360px),1fr));gap:16px}.gegi-journey .gj-card{border:1px solid #cbd9df;border-radius:10px;padding:18px;background:#fff;margin:14px 0}.gegi-journey .gj-card h3{font-size:1.13em;margin:0 0 12px}.gegi-journey svg{width:100%;height:auto;display:block;background:#f6fafb;border-radius:6px;touch-action:pan-y}.gegi-journey svg text{font:13px system-ui}.gegi-journey .gj-muted{color:#476475;font-size:.93em}.gegi-journey .gj-note{background:#edf5f8;border-left:4px solid #008699;padding:12px}.gegi-journey .gj-formula{font:1.05em/1.65 ui-monospace,monospace;background:#edf5f8;padding:12px;overflow-wrap:anywhere}.gegi-journey .gj-scroll{overflow:auto}.gegi-journey table{border-collapse:collapse;width:100%;font-size:.92em}.gegi-journey th,.gegi-journey td{padding:7px;border-bottom:1px solid #d4e0e6;text-align:left;vertical-align:top}.gegi-journey .gj-small{font-size:.88em}.gegi-journey .gj-identity{overflow-wrap:anywhere}.gegi-journey figure{margin:0}.gegi-journey figcaption{font-size:.9em;margin-top:7px}.gegi-journey [hidden]{display:none!important}`;
    if(!doc.getElementById('gegi-signal-journey-style')){const style=el('style',css);style.id='gegi-signal-journey-style';doc.head.append(style);}
    const shell=el('div',undefined,'gegi-journey'),records=entries(payload),accepted=records.filter(r=>validCones(r.event).length);
    element.replaceChildren(shell);
    paragraph(shell,'Follow one saved pulse group: its 34 electrode signals give strip energies and timing; those measurements give candidate interactions and Compton cones; many weighted cones build an image.','gj-intro');
    const controls=el('div',undefined,'gj-controls'),identity=el('p',undefined,'gj-identity gj-muted'),steps=el('nav',undefined,'gj-steps'),body=el('div');steps.setAttribute('aria-label','Signal-to-image steps');shell.append(controls,identity,steps,body);
    function preferredContact(event){return (event?.channels||[]).slice().sort((a,b)=>Math.abs(b.final_induced_keV??0)-Math.abs(a.final_induced_keV??0)||a.contact_id-b.contact_id)[0]?.contact_id??1;}
    let current=0,stage=0,contact=options.selectedContactId??preferredContact(records[0]?.event),coneIndex=0,yaw=-35,pitch=20,phi=0,showTruth=false,mapKind='direction',accumulate=1;
    const criteria=payload?.criteria||{};
    if(!records.length){paragraph(body,'No stored nonzero pulse group is available. No signal, site or cone has been invented.');return {destroy:()=>element.replaceChildren()};}
    select(controls,'Saved source / event',records.map((r,i)=>[i,r.label]),0,v=>{current=Number(v);coneIndex=0;contact=preferredContact(records[current].event);render();});
    const stepNames=['1 · Signals','2 · Interactions','3 · Compton cone','4 · Image accumulation'];
    const buttons=stepNames.map((name,i)=>{const b=el('button',name);b.type='button';b.onclick=()=>{stage=i;render();};steps.append(b);return b;});

    function tracePlot(channel,key,title,unitLabel) {
      const fig=el('figure'),t=channel?.trace?.time_ns,ys=channel?.trace?.[key];fig.append(el('h4',title+' · '+unitLabel));
      if(!Array.isArray(t)||!Array.isArray(ys)||!t.length||t.length!==ys.length||!t.every(finite)||!ys.every(finite)){paragraph(fig,'No saved trace for this quantity. Unknown remains unknown.','gj-muted');return fig;}
      let lo=0,hi=0;for(const y of ys){lo=Math.min(lo,y);hi=Math.max(hi,y);}const span=hi-lo||1,x0=t[0],x1=t[t.length-1],xspan=x1-x0||1;
      const plot=svg('svg',{viewBox:'0 0 520 210',role:'img','aria-label':title+' versus group-relative time in ns'});
      const yzero=160-120*(0-lo)/span;plot.append(svg('line',{x1:60,y1:yzero,x2:500,y2:yzero,stroke:'#bacbd4','stroke-dasharray':'3 3'}));
      plot.append(svg('polyline',{points:ys.map((v,i)=>(60+440*(t[i]-x0)/xspan)+','+(160-120*(v-lo)/span)).join(' '),fill:'none',stroke:'#00798e','stroke-width':1.8}));
      plot.append(textSvg(5,28,fmt(hi)+' '+unitLabel),textSvg(5,163,fmt(lo)),textSvg(60,185,fmt(x0)+' ns'),textSvg(400,185,fmt(x1)+' ns'));
      fig.append(plot,el('figcaption',t.length+' exact saved display samples; no new resampling.','gj-muted'));return fig;
    }
    function stripPlot(event) {
      const channels=event?.channels||[],plot=svg('svg',{viewBox:'0 0 1000 230',role:'img','aria-label':'Fixed-gain energy of all 34 electrodes, X and Y faces separate'});
      const values=channels.map(c=>c.reconstructed_energy_keV).filter(finite),max=Math.max(1,...values);
      for(let i=1;i<=34;i++) {
        const c=channels.find(c=>c.contact_id===i),x=44+(i-1)*27.5,value=c?.reconstructed_energy_keV;
        if(finite(value))plot.append(svg('rect',{x,y:155-110*Math.max(0,value)/max,width:19,height:110*Math.max(0,value)/max,fill:i<=17?'#006e9a':'#b74d18',opacity:c.accepted?1:.35}));
        else plot.append(textSvg(x+3,150,'?',{'font-size':12}));
        plot.append(textSvg(x,178,String(i),{'font-size':11}));
      }
      plot.append(textSvg(5,25,fmt(max)+' keV'),textSvg(55,213,'X: contacts 1–16; guard 17'),textSvg(515,213,'Y: contacts 18–33; guard 34'));
      return plot;
    }
    function signals(record) {
      const event=record.event,p=section('Actual electrode signals → one shared electronics calibration');
      paragraph(p,'A gamma deposit creates electron–hole charge. Drifting charge induces signed signals on several electrodes. Fixed wiring, the preamplifier, analog shaper and peak ADC turn those signals into channel energies. The same independent calibration applies to every event.');
      if(!Array.isArray(event?.channels)||!event.channels.length){paragraph(p,'Native response is '+(event?.status||'unavailable')+'. There is no saved channel waveform to plot.','gj-note');body.append(p);return;}
      p.append(stripPlot(event));paragraph(p,'Both strip faces see the same deposited energy. X and Y are averaged when paired; adding the faces would double count. A small induced transient does not by itself identify a collecting strip.','gj-muted');
      const control=el('div',undefined,'gj-controls');const ids=event.channels.map(c=>c.contact_id);
      if(!ids.includes(Number(contact)))contact=ids[0];
      select(control,'Inspect contact',event.channels.map(c=>[c.contact_id,'Contact '+c.contact_id+(c.contact_id===17||c.contact_id===34?' · guard':c.contact_id<18?' · X':' · Y')]),contact,v=>{contact=Number(v);options.onChannelChange?.(contact);render();});
      p.append(control);const channel=event.channels.find(c=>c.contact_id===Number(contact));
      paragraph(p,'Contact '+contact+': fixed-gain energy '+fmt(channel?.reconstructed_energy_keV)+' keV; terminal signed induced response '+fmt(channel?.final_induced_keV)+' keV-equivalent; t50 '+fmt(channel?.t50_ns)+' ns. '+(channel?.accepted?'Channel readout accepted.':'Channel readout rejected or unavailable.')+(channel?.rejection_reason?' '+channel.rejection_reason+'.':''),'gj-note');
      const plots=el('div',undefined,'gj-grid');for(const [key,label,unitLabel]of [['charge_fC','Raw signed induced charge','fC'],['current_nA','Current after fixed wiring','nA'],['preamp_V','Preamplifier output','V'],['shaped_V','Analog shaper output','V']])plots.append(tracePlot(channel,key,label,unitLabel));p.append(plots);
      paragraph(p,'Time is relative to the pulse-group origin. Transport deposition time is separate from carrier drift time. The displayed trace is a retained display grid, not a waveform-digitizing acquisition. Current uses the original integration bins, so differences between adjacent display points do not reproduce its samples.','gj-muted');body.append(p);
    }
    function interactions(record) {
      const event=record.event,reco=event?.reconstruction,p=section('Strip pairing and timing → reconstructed interaction candidates');
      paragraph(p,'Two resolved collecting strips on each face give candidate X–Y pairs. Pair energies must agree within max(2 keV, 2%); each site uses the mean of its two strip energies. Transverse coordinates use strip centres. X–Y charge-collection timing difference gives depth through an independent simulated timing table.');
      paragraph(p,'These are signal-derived positions with model assumptions. They are distinct from the radiation truth deposits. Unresolved same-strip sites, guards, rejected collecting channels and unavailable calibration can exclude an event.','gj-note');
      const hypotheses=reco?.paired_site_hypotheses||(reco?.sites?.length?[{pairing_index:0,sites:reco.sites}]:[]);
      if(!hypotheses.length)paragraph(p,'No accepted interaction pairing. '+(reco?.reason||event?.rejection_reason||'Reconstruction unavailable.')+'.');
      for(const h of hypotheses) {
        p.append(el('h4','Pairing '+h.pairing_index+(hypotheses.length>1?' · retained alternative':'')));
        table(p,['Site','X / Y contact','X energy / Y energy (keV)','Site energy (keV)','tX50 − tY50 (ns)','Reconstructed x, y, z (mm)'],h.sites.map((s,i)=>{const x=event.channels?.find(c=>c.contact_id===s.x_contact),y=event.channels?.find(c=>c.contact_id===s.y_contact);return [i,s.x_contact+' / '+s.y_contact,fmt(x?.reconstructed_energy_keV)+' / '+fmt(y?.reconstructed_energy_keV),fmt(s.energy_keV),fmt(s.ctd_ns),s.position_mm.map(v=>fmt(v)).join(', ')];}));
        paragraph(p,'Depth method: '+String(h.sites[0]?.method||'saved model calibration').replaceAll('_',' ')+'. Timing outside its support is rejected; unavailable pixels are not replaced using truth.','gj-muted');
      }
      if(reco?.rejected_pairings?.length)table(p,['Excluded pairing','Saved reason'],reco.rejected_pairings.map(r=>[r.pairing_index,r.reason]));
      paragraph(p,'Saved result: '+(reco?.status||'unavailable')+'; '+validCones(event).length+' weighted cone candidates. '+(reco?.pairing_ambiguous?'Strip pairing remains ambiguous. ':'')+(reco?.ordering_ambiguous?'Interaction order remains ambiguous.':'No saved ordering ambiguity.'),'gj-muted');body.append(p);
    }
    function geometry(cone,truth) {
      const view=svg('svg',{viewBox:'0 0 760 440',role:'img','aria-label':'Rotatable source-pointing Compton candidate cone and reconstructed interaction sites'}),centre=cone.vertex_mm;
      function project(point){const q=point.map((v,i)=>v-centre[i]),a=yaw*RAD,b=pitch*RAD,x=Math.cos(a)*q[0]-Math.sin(a)*q[1],y=Math.sin(a)*q[0]+Math.cos(a)*q[1],z=q[2];return [340+2.7*x,235-2.7*(Math.sin(b)*y+Math.cos(b)*z)];}
      function line(points,colour,width=2,dash){view.append(svg('polyline',{points:points.map(project).map(p=>p.join(',')).join(' '),fill:'none',stroke:colour,'stroke-width':width,...(dash?{'stroke-dasharray':dash}:{})}));}
      function arrow(start,end,colour,width=3){line([start,end],colour,width);const a=project(start),b=project(end),d=[b[0]-a[0],b[1]-a[1]],n=Math.hypot(...d);if(n<1)return;const u=d.map(v=>v/n),v=[-u[1],u[0]],base=[b[0]-9*u[0],b[1]-9*u[1]];view.append(svg('polygon',{points:[b,[base[0]+4*v[0],base[1]+4*v[1]],[base[0]-4*v[0],base[1]-4*v[1]]].map(p=>p.join(',')).join(' '),fill:colour}));}
      function label(point,text,colour){const q=project(point);view.append(textSvg(q[0]+7,q[1]-7,text,{fill:colour}));}
      const length=70,ring=[];for(let a=0;a<=360;a+=4)ring.push(add(centre,mul(coneRay(cone,a),length)));
      const rim=ring.map(project);view.append(svg('polygon',{points:[project(centre),...rim].map(p=>p.join(',')).join(' '),fill:'#edaf7a','fill-opacity':.2,stroke:'none'}));line(ring,'#b74d18',2);
      for(let a=0;a<360;a+=30)line([centre,add(centre,mul(coneRay(cone,a),length))],'#c67d4b',.8);
      const axisEnd=add(centre,mul(cone.axis,length)),second=add(centre,mul(cone.axis,-cone.site_separation_mm)),rayEnd=add(centre,mul(coneRay(cone,phi),length));
      line([centre,axisEnd],'#24784b',2,'6 4');label(axisEnd,'source-pointing axis a','#24784b');
      arrow(centre,rayEnd,'#b74d18');label(rayEnd,'one allowed source direction','#b74d18');
      line([centre,second],'#006e9a',4);label(second,'2 · absorb E₂','#006e9a');label(centre,'1 · scatter E₁','#173047');
      // An incoming photon propagates opposite to the source-pointing ray.
      const incoming=add(centre,mul(coneRay(cone,phi),28)),tip=add(centre,mul(coneRay(cone,phi),8));arrow(incoming,tip,'#6c557d');label(incoming,'incoming γ → site 1','#6c557d');
      const tip2=add(centre,mul(cone.axis,-cone.site_separation_mm*.8)),base2=add(centre,mul(cone.axis,-cone.site_separation_mm*.5));arrow(base2,tip2,'#006e9a',4);
      for(const [point,colour]of [[centre,'#173047'],[second,'#006e9a']]){const p=project(point);view.append(svg('circle',{cx:p[0],cy:p[1],r:5,fill:colour,stroke:'white','stroke-width':1.5}));}
      if(showTruth&&vec(truth)){line([centre,add(centre,mul(unit(truth.map((v,i)=>v-centre[i])),length))],'#9a1864',3,'2 5');label(add(centre,mul(unit(truth.map((v,i)=>v-centre[i])),length)),'known setup · evaluation only','#9a1864');}
      const anchor=[110,365];for(const [axis,name,col]of [[[1,0,0],'+x','#a04425'],[[0,1,0],'+y','#24784b'],[[0,0,1],'+z front','#006e9a']]){const p=project(add(centre,mul(axis,20))),o=project(centre),end=[anchor[0]+p[0]-o[0],anchor[1]+p[1]-o[1]];view.append(svg('line',{x1:anchor[0],y1:anchor[1],x2:end[0],y2:end[1],stroke:col,'stroke-width':2}),textSvg(end[0]+3,end[1],name));}
      view.append(textSvg(20,25,'Illustrative cone surface; 70 mm ray length is a drawing choice.'),textSvg(20,420,'Sites and vertex: saved reconstructed coordinates. Camera rotation changes the view only.'));return view;
    }
    function compton(record) {
      const event=record.event,cones=validCones(event),p=section('Compton energy → an opening angle, not a unique source ray');
      paragraph(p,'For an assumed first Compton scatter followed by full absorption, E₁ is energy given to the first recoil electron and E₂ is the remaining scattered-photon energy absorbed at the second site. Energy conservation gives incoming energy E₁ + E₂. Compton kinematics gives the deflection angle θ.');
      paragraph(p,'cos θ = 1 − 511 keV × (1/E₂ − 1/(E₁ + E₂))','gj-formula');
      paragraph(p,'Energies are in keV; the calculation uses electron rest energy 510.99895069 keV. This relation assumes a two-site, full-energy Compton-plus-absorption interpretation. Missing energy or unresolved interactions can invalidate that interpretation. No source pose or transport truth chooses the order.','gj-muted');
      if(!cones.length){paragraph(p,'No accepted candidate cone. '+(event?.reconstruction?.reason||'Saved reconstruction unavailable.')+'.','gj-note');body.append(p);return;}
      coneIndex=clamp(coneIndex,0,cones.length-1);const controls=el('div',undefined,'gj-controls');
      select(controls,'Candidate',cones.map((c,i)=>[i,'Pair '+(c.pairing_index??0)+' · order '+(c.order||[]).join(' → ')+' · weight '+fmt(c.weight)]),coneIndex,v=>{coneIndex=Number(v);render();});p.append(controls);
      const c=cones[coneIndex],calculated=1-REST_KEV*(1/c.absorbed_energy_keV-1/(c.scatter_energy_keV+c.absorbed_energy_keV));
      paragraph(p,'E₁ = '+fmt(c.scatter_energy_keV)+' keV; E₂ = '+fmt(c.absorbed_energy_keV)+' keV; E₁ + E₂ = '+fmt(c.scatter_energy_keV+c.absorbed_energy_keV)+' keV. cos θ = '+fmt(calculated,6)+'; saved θ = '+fmt(c.half_angle_deg,5)+'°. Weight '+fmt(c.weight)+' of '+cones.length+' retained candidate'+(cones.length>1?'s':'')+'.','gj-note');
      const dynamic=el('div'),rot=el('div',undefined,'gj-controls');p.append(dynamic,rot);
      function redraw(){dynamic.replaceChildren(geometry(c,record.truth_position_mm_for_evaluation_only));}
      range(rot,'Rotate view',-180,180,yaw,v=>{yaw=v;redraw();});range(rot,'Tilt view',-80,80,pitch,v=>{pitch=v;redraw();});range(rot,'Move around cone',0,360,phi,v=>{phi=v;redraw();});
      if(vec(record.truth_position_mm_for_evaluation_only)){const label=el('label'),check=el('input');check.type='checkbox';check.checked=showTruth;check.onchange=()=>{showTruth=check.checked;redraw();};label.append(check,el('span','Show known source setup (evaluation only)'));rot.append(label);}redraw();
      paragraph(p,'The scattered photon travels from site 1 to site 2. The source-pointing axis a = (r₁ − r₂)/|r₁ − r₂| points in the opposite direction. Possible source directions make angle θ with a; incoming photon propagation is opposite to those source directions. Rotating a ray around a produces the cone.','gj-muted');
      paragraph(p,'All '+cones.length+' candidate weights sum to '+fmt(cones.reduce((s,c)=>s+c.weight,0))+'. Uniform weights are a declared convention, not calibrated probabilities. The selector inspects one cone; the event map always includes every saved candidate.','gj-muted');body.append(p);
    }
    function heatmap(image,truth) {
      const fig=el('figure'),plot=svg('svg',{viewBox:'0 0 760 420',role:'img','aria-label':image.kind==='direction'?'Illustrative direction density':'Illustrative density on assumed z=40 mm plane'}),left=65,top=30,w=650,h=310;
      let maximum=0;for(const row of image.values)for(const v of row)maximum=Math.max(maximum,v);
      for(let j=0;j<image.ys.length;j++)for(let i=0;i<image.xs.length;i++){const fraction=maximum?image.values[j][i]/maximum:0;plot.append(svg('rect',{x:left+w*i/image.xs.length,y:top+h*(image.ys.length-j-1)/image.ys.length,width:w/image.xs.length+.1,height:h/image.ys.length+.1,fill:'rgb('+Math.round(20+235*fraction)+','+Math.round(35+190*fraction)+','+Math.round(95-45*fraction)+')'}));}
      plot.append(textSvg(left,365,fmt(image.xs[0])),textSvg(655,365,fmt(image.xs[image.xs.length-1])),textSvg(6,40,fmt(image.ys[image.ys.length-1])),textSvg(6,340,fmt(image.ys[0])),textSvg(240,390,image.kind==='direction'?'azimuth (°); y = elevation (°)':'x (mm); y = y (mm); assumed z = '+image.z+' mm'));
      if(showTruth&&vec(truth)){
        const x=image.kind==='direction'?Math.atan2(truth[1],truth[0])/RAD:truth[0],y=image.kind==='direction'?Math.asin(truth[2]/norm(truth))/RAD:truth[1];
        const xmin=image.kind==='direction'?-180:-120,xmax=image.kind==='direction'?180:120,ymin=image.kind==='direction'?-90:-120,ymax=image.kind==='direction'?90:120;
        if(x>=xmin&&x<=xmax&&y>=ymin&&y<=ymax&&(image.kind==='direction'||Math.abs(truth[2]-image.z)<1e-9)){
          const px=left+w*(x-xmin)/(xmax-xmin),py=top+h*(ymax-y)/(ymax-ymin);plot.append(svg('circle',{cx:px,cy:py,r:7,fill:'none',stroke:'#f65cb7','stroke-width':3}),textSvg(left,18,'Pink ring: known selected source setup; evaluation only.'));
        }
      }
      fig.append(plot,el('figcaption','Illustrative recomputation from the displayed representatives. Linear colour 0 → '+fmt(maximum)+' '+image.units+'. '+(image.kind==='plane'?'Unmapped cone weight '+fmt(image.unmappedWeight)+'.':''),'gj-muted'));return fig;
    }
    function accumulation(record) {
      const p=section('Weighted candidate cones → a direction map or an assumed-plane image');
      paragraph(p,'A single event contributes a ring of possible directions. Its ambiguity shares one unit of event weight across every valid cone. Other events add their own rings; consistent intersections can become peaks. The fixed 5° Gaussian kernel spreads angular mismatch around each cone. Its width is an analysis setting, not measured angular resolution.');
      if(!validCones(record.event).length){paragraph(p,'This event has no accepted saved candidate cones. No event map is fabricated. '+(record.event?.reconstruction?.reason||'Reconstruction unavailable.')+'.','gj-note');body.append(p);return;}
      const mode=el('div',undefined,'gj-controls');select(mode,'Projection',[['direction','Direction on the sky'],['plane','Assumed z = 40 mm source plane']],mapKind,v=>{mapKind=v;render();});p.append(mode);
      const chosen=section('This selected event · all saved candidates');chosen.append(heatmap(illustrativeMap([record],mapKind,criteria),record.truth_position_mm_for_evaluation_only));p.append(chosen);
      if(accepted.length>1){
        accumulate=clamp(accumulate,1,accepted.length);const cumulative=section('Illustrative accumulation · representative events only'),control=el('div',undefined,'gj-controls'),display=el('div');
        function draw(){const subset=accepted.slice(0,accumulate);display.replaceChildren(heatmap(illustrativeMap(subset,mapKind,criteria),record.truth_position_mm_for_evaluation_only),el('p',subset.map(r=>r.label).join(' + ')+' · '+subset.length+' representative event weights. This is not the full campaign map.','gj-muted'));}
        range(control,'Add representative events',1,accepted.length,accumulate,v=>{accumulate=v;draw();});cumulative.append(control,display);draw();p.append(cumulative);
      }
      if(vec(record.truth_position_mm_for_evaluation_only)){const label=el('label'),check=el('input');check.type='checkbox';check.checked=showTruth;check.onchange=()=>{showTruth=check.checked;render();};label.append(check,el('span','Overlay known selected source setup (evaluation only)'));p.append(label);}
      paragraph(p,'The direction map integrates with solid-angle cell areas and neglects each cone vertex offset: it is a far-field diagnostic. The plane map uses each reconstructed vertex and integrates with 2 × 2 mm² cells. Each mapped event contributes its preserved cone weights. The imposed z = 40 mm plane supplies a depth assumption; it does not recover range or a true 3D source position.','gj-note');
      paragraph(p,options.scope==='student'?'The separate saved-run direction map retains all accepted events and original candidate weights. The event contribution above is an illustration from this selected event; it does not replace or modify that saved map. Initial counts, zero-deposit totals, rejected events and failures remain in the full run census.':'The complete campaign maps below are unchanged saved results, with all accepted pulse groups. Independent-source mixtures use 0.5 × mapA/NA + 0.5 × mapB/NB, where NA and NB are each source’s initial yield. A weak-efficiency source is not renormalized to equal accepted-event area. Photon initials and initial nuclear decays remain distinct denominators.','gj-muted');body.append(p);
    }
    function render() {
      const record=records[current],event=record.event;buttons.forEach((b,i)=>{if(stage===i)b.setAttribute('aria-current','step');else b.removeAttribute('aria-current');});
      body.replaceChildren();const id=event?.original_identity||{};
      identity.textContent=record.label+' · '+Object.entries(id).map(([k,v])=>k.replaceAll('_',' ')+' '+v).join(' · ')+'. '+(event?.selection_rule||'Selected original saved event.')+' Readout energy '+fmt(event?.readout_energy_keV??event?.readout_summary?.energy_keV)+' keV.';
      if(!event){paragraph(body,'This source has no accepted representative. No signal, site or cone is fabricated.','gj-note');return;}
      [signals,interactions,compton,accumulation][stage](record);
    }
    render();return {destroy:()=>element.replaceChildren()};
  }
})(typeof window!=='undefined'?window:globalThis);
