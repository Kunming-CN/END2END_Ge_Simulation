/* Saved-data cameras and exact original-bin current from complete charge inputs.
   No analog replay, smoothing, rectification or calibration is performed here. */
(function(global){
  'use strict';
  const NS='http://www.w3.org/2000/svg',ELECTRON_C=1.602176634e-19;
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
  function currentFromCharge(t,q,eion,options={}){
    if(!Array.isArray(t)||!Array.isArray(q)||t.length<2||t.length!==q.length||t[0]!==0||q[0]!==0)throw Error('Complete original charge samples starting at zero are required');
    const dt=options.time_step_ns,end=options.readout_end_ns??t.at(-1),tolerance=Math.max(1e-9,dt*1e-8);
    if(!Number.isFinite(eion)||eion<=0||!Number.isFinite(dt)||dt<=0)throw Error('Recorded ionisation energy and original time step are required');
    for(let i=0;i<t.length;i++)if(!Number.isFinite(t[i])||!Number.isFinite(q[i])||Math.abs(t[i]-i*dt)>tolerance||(i&&t[i]<=t[i-1]))throw Error('Charge input is incomplete or is not on the original uniform grid');
    const steps=Math.round(end/dt);
    if(!Number.isFinite(end)||end<dt||Math.abs(end-steps*dt)>tolerance||steps+1>(options.max_samples??500000))throw Error('Invalid original readout window');
    // Match Readout.process_event operation order, including its initial empty bin.
    // The recorded electronics boundary may truncate a longer native charge input.
    const factor=1000/eion*ELECTRON_C,time=[],values=[],start=[],stop=[];
    for(let i=0;i<=steps;i++){
      time.push(i*dt);start.push(Math.max(0,i-1)*dt);stop.push(i*dt);
      values.push(i===0||i>=q.length?0:(q[i]-q[i-1])*factor/dt*1e18);
    }
    return {time_ns:time,values,bin_start_ns:start,bin_end_ns:stop,origin:'exact_original_bins_from_full_saved_signed_charge'};
  }
  function gammaPanels(rec,edge,settings={}){
    const r=rec.readout,t=r.trace,w=rec.charge_input,input=w.time_since_initial_primary_ns,q=w.induced_equivalent_energy_keV;
    const end=focusEnd(input,q),peak={t:r.peak_time_ns,v:r.peak_V},complete=settings.ionisation_energy_eV!==undefined||settings.time_step_ns!==undefined;
    return [
      {title:'Signed charge · induced equivalent keV',time_ns:input,values:q,full_end_ns:input.at(-1),focus_end_ns:Math.min(input.at(-1),end),note:'Every signed input sample remains available. Sampled-variation focus is a camera choice, not proof of complete charge collection; endpoint and cap flags remain.'},
      {title:'Signed original-bin current · nA',time_ns:t.time_ns,values:t.current_nA,bin_start_ns:t.current_bin_start_ns,bin_end_ns:t.current_bin_end_ns,full_end_ns:r.readout_end_ns,focus_end_ns:Math.min(r.readout_end_ns,end),current_from_charge:complete?{time_ns:input,values:q,...settings,readout_end_ns:r.readout_end_ns}:null,note:complete?'Every original (start, end] current bin is calculated from the complete saved signed charge with the recorded ionisation energy and time step. No smoothing or polarity change; the original zero-current tail remains.':'Only retained original (start, end] bins are available. Gaps are unsaved bins, not zero current; do not integrate across them.'},
      {title:'Signed analog preamp · V',time_ns:t.time_ns,values:t.preamp_V,full_end_ns:r.readout_end_ns,focus_end_ns:Math.min(r.readout_end_ns,edge?edge.captured_stop_ns:end),focus_series:edge?{time_ns:edge.time_ns,values:edge.preamp_V}:null,note:(edge?'Collection-edge focus uses an electronics-only replay from full saved signed charge with the unchanged five-state transition. Full saved window uses the original compact trace. Unsaved original analog arrays are not recovered.':'Original retained samples. Lines are visual guides; omitted analog samples remain unavailable.')+' Positive input charge produces a negative preamp voltage with this circuit polarity.'},
      {title:'Analog shaper · V',time_ns:t.time_ns,values:t.shaped_V,full_end_ns:r.readout_end_ns,focus_end_ns:shaperEnd(t.time_ns,t.shaped_V,peak,r.readout_end_ns),peak,note:'Gold marker is the exact sampled peak; ADC, reconstructed energy and flags remain unchanged. Lines connect original retained samples.'}
    ];
  }
  function draw(host,panels,clock='Time since initial primary · ns'){
    host.replaceChildren();
    for(const original of panels){
      const charge=original.current_from_charge,panel=charge?{...original,...currentFromCharge(charge.time_ns,charge.values,charge.ionisation_energy_eV,charge)}:original;
      if(!Array.isArray(panel.time_ns)||!Array.isArray(panel.values)||panel.time_ns.length!==panel.values.length||!panel.time_ns.length)throw Error('Invalid saved plot samples');
      for(let i=0;i<panel.time_ns.length;i++)if(!Number.isFinite(panel.time_ns[i])||!Number.isFinite(panel.values[i])||(i&&panel.time_ns[i]<=panel.time_ns[i-1]))throw Error('Invalid saved sample or time order');
      const bins=panel.bin_start_ns!==undefined;
      if(bins){
        if(!Array.isArray(panel.bin_start_ns)||!Array.isArray(panel.bin_end_ns)||panel.bin_start_ns.length!==panel.values.length||panel.bin_end_ns.length!==panel.values.length)throw Error('Invalid original current bin arrays');
        for(let i=0;i<panel.values.length;i++)if(!Number.isFinite(panel.bin_start_ns[i])||!Number.isFinite(panel.bin_end_ns[i])||panel.bin_start_ns[i]>panel.bin_end_ns[i]||(i&&panel.bin_start_ns[i]<panel.bin_end_ns[i-1]))throw Error('Invalid or overlapping original current bins');
      }
      const fig=el('figure'),heading=el('figcaption',panel.title),controls=el('div'),focus=el('button','Collection-edge focus'),full=el('button','Full saved window'),range=el('small'),plot=svg('svg',{viewBox:'0 0 560 260',role:'img','aria-label':panel.title+' versus '+clock}),note=el('p',panel.note);
      fig.style.margin='0';fig.style.minWidth='0';plot.style.width='100%';controls.style.display='flex';controls.style.flexWrap='wrap';controls.style.gap='8px';note.style.fontSize='.83rem';range.style.display='block';
      controls.append(focus,full);fig.append(heading,controls,range,plot,note);host.append(fig);
      function render(focused){
        let xmax=focused?panel.focus_end_ns:panel.full_end_ns;
        // Keep any lobe >=1% of the retained/full-bin current maximum visible.
        if(focused&&bins){let amplitude=0,last=0;for(const value of panel.values)amplitude=Math.max(amplitude,Math.abs(value));if(amplitude)for(let i=0;i<panel.values.length;i++)if(Math.abs(panel.values[i])>=amplitude*.01)last=panel.bin_end_ns[i];if(last>xmax)xmax=Math.min(panel.full_end_ns,last+Math.max(10,last*.2));}
        const source=focused&&panel.focus_series?panel.focus_series:panel;
        if(!Number.isFinite(xmax)||xmax<0)throw Error('Invalid saved time range');
        if(!Array.isArray(source.time_ns)||!Array.isArray(source.values)||source.time_ns.length!==source.values.length)throw Error('Invalid saved focus samples');
        const limit=xmax||1,indices=source.time_ns.map((_,i)=>i).filter(i=>bins?panel.bin_end_ns[i]>0&&panel.bin_start_ns[i]<xmax:source.time_ns[i]>=0&&source.time_ns[i]<=xmax);
        let lo=0,hi=0;for(const i of indices){const value=source.values[i];if(!Number.isFinite(value))throw Error('Nonfinite saved sample');lo=Math.min(lo,value);hi=Math.max(hi,value);}
        const visiblePeak=panel.peak&&panel.peak.t>=0&&panel.peak.t<=xmax;
        if(visiblePeak){lo=Math.min(lo,panel.peak.v);hi=Math.max(hi,panel.peak.v);}
        const pad=(hi-lo)*.08||.5;lo-=pad;hi+=pad;const x=v=>84+v/limit*458,y=v=>214-(v-lo)/(hi-lo)*188;
        plot.replaceChildren(svg('title',{},panel.title+' · '+(focused?'Collection-edge focus':'Full saved window')));
        for(let k=0;k<=4;k++){const xv=limit*k/4,yv=lo+(hi-lo)*k/4;plot.append(svg('line',{x1:84,x2:542,y1:y(yv),y2:y(yv),stroke:'#d7e3e5'}),svg('text',{x:x(xv),y:235,'text-anchor':'middle','font-size':10},xv.toPrecision(3)));if(Math.abs(y(yv)-y(0))>10)plot.append(svg('text',{x:76,y:y(yv)+4,'text-anchor':'end','font-size':10},yv.toPrecision(3)));}
        plot.append(svg('line',{x1:84,x2:542,y1:y(0),y2:y(0),stroke:'#657c83','stroke-width':1}),svg('text',{x:76,y:y(0)+4,'text-anchor':'end','font-size':10},'0'),svg('path',{d:'M84,26V214H542',stroke:'#405963',fill:'none'}),svg('text',{x:310,y:256,'text-anchor':'middle','font-size':11},clock),svg('text',{transform:'translate(12 120) rotate(-90)','text-anchor':'middle','font-size':11},panel.y_label||panel.title.split(' · ').at(-1)));
        if(bins){
          let d='',previous=null;
          for(const i of indices){const a=panel.bin_start_ns[i],b=panel.bin_end_ns[i],left=Math.max(0,a),right=Math.min(b,xmax),v=panel.values[i];
            // Adjacent original bins form one step. Unknown gaps start a new run.
            d+=previous&&previous.b===a?`V${y(v)}H${x(right)}`:`M${x(left)},${y(v)}H${x(right)}`;previous={b};
          }
          const mark=svg('path',{d,stroke:'#3a60a7','stroke-width':1.5,fill:'none','data-series':'current'});mark.append(svg('title',{},`${indices.length} signed original current bins; gaps remain unsaved.`));plot.append(mark);
        }else{
          const d=indices.map((i,k)=>(k?'L':'M')+x(source.time_ns[i])+','+y(source.values[i])).join(' ');plot.append(svg('path',{d,stroke:'#007b80','stroke-width':1.6,fill:'none','data-series':'samples'}));
          // Mark retained points; the dense replay has its own explicit origin.
          if(indices.length<=160)for(const i of indices){const mark=svg('circle',{cx:x(source.time_ns[i]),cy:y(source.values[i]),r:2.1,fill:'#007b80'});mark.append(svg('title',{},`${exact(source.time_ns[i])} ns: ${exact(source.values[i])}`));plot.append(mark);}
        }
        if(visiblePeak){const p=panel.peak;plot.append(svg('line',{x1:x(p.t),x2:x(p.t),y1:26,y2:214,stroke:'#ad6216','stroke-dasharray':'4 4'}));const mark=svg('circle',{cx:x(p.t),cy:y(p.v),r:4,fill:'#ad6216'});mark.append(svg('title',{},`Exact sampled peak ${exact(p.v)} V at ${exact(p.t)} ns`));plot.append(mark);}
        range.textContent=(focused?'Collection-edge focus':'Full saved window')+' · 0–'+exact(xmax)+' ns · '+indices.length+(bins?' displayed original bins':' displayed samples');focus.setAttribute('aria-pressed',String(focused));full.setAttribute('aria-pressed',String(!focused));
      }
      focus.onclick=()=>render(true);full.onclick=()=>render(false);render(true);
    }
  }
  global.SavedFocusPlots={focusEnd,shaperEnd,currentFromCharge,gammaPanels,draw};
})(typeof window==='undefined'?globalThis:window);
