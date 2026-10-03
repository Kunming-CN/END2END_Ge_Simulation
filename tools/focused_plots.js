/* Numerical saved-data cameras only. No interpolation, processing or calibration. */
(function(global){
  'use strict';
  const NS='http://www.w3.org/2000/svg';
  const el=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
  const svg=(tag,attrs={},text)=>{const n=document.createElementNS(NS,tag);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,String(v));if(text!==undefined)n.textContent=text;return n;};
  const exact=v=>Object.is(v,-0)?'-0':String(v);
  function focusEnd(t,q){
    let total=0;for(let i=1;i<q.length;i++)total+=Math.abs(q[i]-q[i-1]);
    let index=Math.min(1,t.length-1),sum=0;
    if(total)for(index=1;index<t.length;index++){sum+=Math.abs(q[index]-q[index-1]);if(sum>=.995*total)break;}
    const edge=t[Math.min(index,t.length-1)];return 2*Math.ceil((edge+Math.max(10,.2*edge))/2);
  }
  function shaperEnd(t,v,peak,window){
    if(!peak||!peak.v)return Math.min(window,1000);
    let last=peak.t;for(let i=0;i<t.length;i++)if(Math.abs(v[i])>=Math.abs(peak.v)*.01)last=Math.max(last,t[i]);
    return Math.min(window,Math.ceil((last+Math.max(100,last*.06))/2)*2);
  }
  function gammaPanels(rec,edge){
    const r=rec.readout,t=r.trace,w=rec.charge_input,input=w.time_since_initial_primary_ns,q=w.induced_equivalent_energy_keV;
    const end=focusEnd(input,q),peak={t:r.peak_time_ns,v:r.peak_V};
    return [
      {title:'Charge · induced equivalent keV',time_ns:input,values:q,full_end_ns:input.at(-1),focus_end_ns:Math.min(input.at(-1),end),note:'Every signed input sample remains available. Sampled-variation focus is a camera choice, not proof of complete charge collection; endpoint and cap flags remain.'},
      {title:'Original-bin current · nA',time_ns:t.time_ns,values:t.current_nA,bin_start_ns:t.current_bin_start_ns,bin_end_ns:t.current_bin_end_ns,full_end_ns:r.readout_end_ns,focus_end_ns:Math.min(r.readout_end_ns,end),note:'Original (start, end] bins only; omitted-bin gaps remain. Do not integrate connecting display points.'},
      {title:'Analog preamp · V',time_ns:t.time_ns,values:t.preamp_V,full_end_ns:r.readout_end_ns,focus_end_ns:Math.min(r.readout_end_ns,edge?edge.captured_stop_ns:end),focus_series:edge?{time_ns:edge.time_ns,values:edge.preamp_V}:null,note:edge?'Collection-edge focus uses an electronics-only replay from full saved signed charge with the unchanged five-state transition. Full saved window uses the original compact trace. Unsaved original analog arrays are not recovered.':'Original retained samples. Lines are visual guides; omitted analog samples remain unavailable.'},
      {title:'Analog shaper · V',time_ns:t.time_ns,values:t.shaped_V,full_end_ns:r.readout_end_ns,focus_end_ns:shaperEnd(t.time_ns,t.shaped_V,peak,r.readout_end_ns),peak,note:'Gold marker is the exact sampled peak; ADC, reconstructed energy and flags remain unchanged. Lines connect original retained samples.'}
    ];
  }
  function draw(host,panels,clock='Time since initial primary · ns'){
    host.replaceChildren();
    for(const panel of panels){
      if(!Array.isArray(panel.time_ns)||panel.time_ns.length!==panel.values.length||!panel.time_ns.length)throw Error('Invalid saved plot samples');
      const fig=el('figure'),heading=el('figcaption',panel.title),controls=el('div'),focus=el('button','Collection-edge focus'),full=el('button','Full saved window'),range=el('small'),plot=svg('svg',{viewBox:'0 0 560 260',role:'img','aria-label':panel.title+' versus '+clock}),note=el('p',panel.note);
      fig.style.margin='0';fig.style.minWidth='0';plot.style.width='100%';controls.style.display='flex';controls.style.flexWrap='wrap';controls.style.gap='8px';note.style.fontSize='.83rem';range.style.display='block';
      controls.append(focus,full);fig.append(heading,controls,range,plot,note);host.append(fig);
      function render(focused){
        const xmax=focused?panel.focus_end_ns:panel.full_end_ns,source=focused&&panel.focus_series?panel.focus_series:panel;
        if(!Number.isFinite(xmax)||xmax<0)throw Error('Invalid saved time range');
        const limit=xmax||1,indices=source.time_ns.map((_,i)=>i).filter(i=>source.time_ns[i]<=xmax);
        let lo=0,hi=0;for(const i of indices){const value=source.values[i];if(!Number.isFinite(value))throw Error('Nonfinite saved sample');lo=Math.min(lo,value);hi=Math.max(hi,value);}
        if(panel.peak&&panel.peak.t<=xmax){lo=Math.min(lo,panel.peak.v);hi=Math.max(hi,panel.peak.v);}
        const pad=(hi-lo)*.08||.5;lo-=pad;hi+=pad;const x=v=>72+v/limit*470,y=v=>214-(v-lo)/(hi-lo)*188;
        plot.replaceChildren(svg('title',{},panel.title+' · '+(focused?'Collection-edge focus':'Full saved window')));
        for(let k=0;k<=4;k++){const xv=limit*k/4,yv=lo+(hi-lo)*k/4;plot.append(svg('line',{x1:72,x2:542,y1:y(yv),y2:y(yv),stroke:'#d7e3e5'}),svg('text',{x:64,y:y(yv)+4,'text-anchor':'end','font-size':10},yv.toPrecision(3)),svg('text',{x:x(xv),y:235,'text-anchor':'middle','font-size':10},xv.toPrecision(3)));}
        plot.append(svg('path',{d:'M72,26V214H542',stroke:'#405963',fill:'none'}),svg('text',{x:300,y:256,'text-anchor':'middle','font-size':11},clock));
        if(panel.bin_start_ns){
          panel.values.forEach((v,i)=>{const a=panel.bin_start_ns[i],b=panel.bin_end_ns[i];if(a>xmax||b<0)return;const right=Math.min(b,xmax),mark=svg('path',{d:`M${x(Math.max(0,a))},${y(v)}H${x(right)}`+(b<=xmax?`M${x(b)},${y(0)}V${y(v)}`:''),stroke:'#3a60a7','stroke-width':1.5,fill:'none'});mark.append(svg('title',{},`Original bin (${exact(a)}, ${exact(b)}] ns: ${exact(v)} nA`));plot.append(mark);});
        }else{
          const d=indices.map((i,k)=>(k?'L':'M')+x(source.time_ns[i])+','+y(source.values[i])).join(' ');plot.append(svg('path',{d,stroke:'#007b80','stroke-width':1.6,fill:'none'}));
          // Mark retained points; the dense replay has its own explicit origin.
          if(indices.length<=160)for(const i of indices){const mark=svg('circle',{cx:x(source.time_ns[i]),cy:y(source.values[i]),r:2.1,fill:'#007b80'});mark.append(svg('title',{},`${exact(source.time_ns[i])} ns: ${exact(source.values[i])}`));plot.append(mark);}
        }
        if(panel.peak&&panel.peak.t<=xmax){const p=panel.peak;plot.append(svg('line',{x1:x(p.t),x2:x(p.t),y1:26,y2:214,stroke:'#ad6216','stroke-dasharray':'4 4'}));const mark=svg('circle',{cx:x(p.t),cy:y(p.v),r:4,fill:'#ad6216'});mark.append(svg('title',{},`Exact sampled peak ${exact(p.v)} V at ${exact(p.t)} ns`));plot.append(mark);}
        range.textContent=(focused?'Collection-edge focus':'Full saved window')+' · 0–'+exact(xmax)+' ns · '+indices.length+' displayed samples';focus.setAttribute('aria-pressed',String(focused));full.setAttribute('aria-pressed',String(!focused));
      }
      focus.onclick=()=>render(true);full.onclick=()=>render(false);render(true);
    }
  }
  global.SavedFocusPlots={focusEnd,shaperEnd,gammaPanels,draw};
})(typeof window==='undefined'?globalThis:window);
