/* Shared saved-bin renderer. Scale changes never alter counts or bin edges. */
(function (global) {
  'use strict';
  const NS='http://www.w3.org/2000/svg';
  const check=(ok,message)=>{if(!ok)throw Error(message);};
  function validate(s){
    check(s.edges.length>1 && s.edges.every(Number.isFinite),'Invalid spectrum edges');
    check(s.edges.slice(1).every((x,i)=>x>s.edges[i]),'Unordered spectrum edges');
    check(s.view[0]<s.view[1] && s.edges.includes(s.view[0]) && s.edges.includes(s.view[1]),'Invalid view');
    for(const v of s.series){
      check(v.counts.length===s.edges.length-1 && v.counts.every(n=>Number.isSafeInteger(n)&&n>=0),'Invalid counts');
      check(v.counts.reduce((a,b)=>a+b,0)+v.underflow+v.overflow+v.exact_zero===v.total,'Histogram census mismatch');
    }
    return s;
  }
  function presentation(v){
    if(/^(Geant4|Edep|Deposited energy)/.test(v.label))return ['Geant4 deposited-energy truth','#406090'];
    if(/^(Accepted peak-ADC|Erec)/.test(v.label))return ['Accepted peak-ADC reconstructed energy','#b05040'];
    return [v.label,v.label.startsWith('Native')?'#72529a':'#15745b'];
  }
  function geometry(s,scale,visible=s.series.map(()=>true)){
    validate(s);check(scale==='log'||scale==='linear','Unknown scale');
    check(visible.length===s.series.length&&visible.every(v=>typeof v==='boolean'),'Invalid series mask');
    const selected=[];s.edges.slice(0,-1).forEach((v,i)=>{if(v>=s.view[0]&&s.edges[i+1]<=s.view[1])selected.push(i);});
    const peak=Math.max(1,...s.series.flatMap(v=>selected.map(i=>v.counts[i])));
    const low=scale==='log'?0.5:0, high=scale==='log'?Math.max(10,10**Math.ceil(Math.log10(peak*1.1))):Math.max(1,peak*1.1);
    const x=v=>70+660*(v-s.view[0])/(s.view[1]-s.view[0]);
    const y=v=>scale==='log'?242-204*(Math.log10(v)-Math.log10(low))/(Math.log10(high)-Math.log10(low)):242-204*v/high;
    const ticks=[];
    if(scale==='log'){for(let e=0;e<=Math.log10(high);e++)for(const a of (high<=10?[1,2,5]:[1]))if(a*10**e<=high)ticks.push(a*10**e);}
    else for(let i=0;i<5;i++)ticks.push(peak*i/4);
    const paths=s.series.map((v,j)=>{if(!visible[j])return '';let last=null;const d=[];for(const i of selected){const count=v.counts[i];if(scale==='log'&&count===0){last=null;continue;}if(last!==i-1)d.push('M'+x(s.edges[i]).toFixed(3)+','+y(low).toFixed(3));d.push('L'+x(s.edges[i]).toFixed(3)+','+y(count).toFixed(3));d.push('L'+x(s.edges[i+1]).toFixed(3)+','+y(count).toFixed(3));if(i===selected[selected.length-1]||(scale==='log'&&v.counts[i+1]===0))d.push('L'+x(s.edges[i+1]).toFixed(3)+','+y(low).toFixed(3));last=i;}return d.join(' ');});
    return {selected,peak,low,high,x,y,ticks,paths};
  }
  function node(tag,attrs={},text){const n=document.createElementNS(NS,tag);for(const [k,v] of Object.entries(attrs))n.setAttribute(k,String(v));if(text!==undefined)n.textContent=String(text);return n;}
  function svg(s,scale,visible){
    const g=geometry(s,scale,visible),out=node('svg',{class:'spectrum-chart',viewBox:'0 0 760 292',role:'img','aria-label':s.title+'; '+scale+' count axis'});
    out.append(node('title',{},s.title+': exact saved bins, '+scale+' count scale'));
    for(const tick of g.ticks){out.append(node('path',{d:'M70 '+g.y(tick).toFixed(3)+'H730',stroke:'#dce3e8',fill:'none'}),node('text',{x:62,y:g.y(tick)+4,'text-anchor':'end'},tick));}
    for(let i=0;i<6;i++){const v=s.view[0]+(s.view[1]-s.view[0])*i/5;out.append(node('text',{x:g.x(v),y:262,'text-anchor':i===0?'start':i===5?'end':'middle'},Number(v.toPrecision(5))));}
    out.append(node('path',{d:'M70 38V242H730',stroke:'#677988',fill:'none'}));
    s.series.forEach((v,i)=>{const [label,color]=presentation(v),line=node('path',{class:'spectrum-step',d:g.paths[i],fill:'none',stroke:color,'stroke-width':1.4,'vector-effect':'non-scaling-stroke'});line.append(node('title',{},label));out.append(line);});
    if(!s.series.some((v,j)=>(!visible||visible[j])&&g.selected.some(i=>v.counts[i]>0)))out.append(node('text',{x:400,y:140,'text-anchor':'middle'},visible&&!visible.some(Boolean)?'All series hidden — select a checkbox to show data':'No positive-count bins in this view'));
    out.append(node('text',{x:70,y:21},scale==='log'?'Counts / bin (log10 scale)':'Counts / bin (linear scale)'),node('text',{x:400,y:285,'text-anchor':'middle'},s.xlabel));
    return out;
  }
  function table(panel){
    const s=panel._spectrum,g=geometry(s,panel.dataset.scale),container=panel.querySelector('.spectrum-table');
    container.replaceChildren();if(!panel.querySelector('details').open)return;
    const t=document.createElement('table'),head=t.createTHead().insertRow();
    for(const label of ['Lower keV','Upper keV',...s.series.map(v=>presentation(v)[0])]){const th=document.createElement('th');th.textContent=label;head.append(th);}
    const body=t.createTBody();
    for(const i of g.selected){if(s.series.every(v=>v.counts[i]===0))continue;const row=body.insertRow();for(const value of [s.edges[i],s.edges[i+1],...s.series.map(v=>v.counts[i])])row.insertCell().textContent=String(value);}
    container.append(t);
  }
  function render(panel){
    const s=panel._spectrum,scale=panel.dataset.scale||'log';
    const visible=s.series.map(v=>panel._seriesVisible[presentation(v)[0]]!==false);
    panel.querySelector('.spectrum-chart').replaceWith(svg(s,scale,visible));
    panel.querySelector('.spectrum-status').textContent=!visible.some(Boolean)?'All series hidden. Select a checkbox to show data.':!s.series.some((v,j)=>visible[j]&&geometry(s,scale).selected.some(i=>v.counts[i]>0))?'No positive-count bins in the selected series.':'';
    panel.querySelectorAll('button[data-scale]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.scale===scale)));
    table(panel);
  }
  function controls(panel){
    const legend=panel.querySelector('.spectrum-legend');legend.replaceChildren();
    for(const [i,v] of panel._spectrum.series.entries()){
      const [label,color]=presentation(v),row=document.createElement('label'),box=document.createElement('input'),mark=document.createElement('i'),text=document.createElement('span');
      box.type='checkbox';box.dataset.series=i;box.checked=panel._seriesVisible[label]!==false;
      mark.className='spectrum-key';mark.style.borderColor=color;mark.setAttribute('aria-hidden','true');text.textContent=label;
      box.addEventListener('change',()=>{panel._seriesVisible[label]=box.checked;render(panel);});
      row.append(box,mark,text);legend.append(row);
    }
  }
  function attach(panel){
    if(panel._spectrumBound)return;
    panel._spectrum=panel._spectrum||validate(JSON.parse(panel.querySelector('.spectrum-data').textContent));
    panel._spectrumBound=true;
    panel._seriesVisible={};controls(panel);
    panel.querySelectorAll('button[data-scale]').forEach(b=>b.disabled=false);
    panel.querySelector('details').hidden=false;
    panel.querySelectorAll('button[data-scale]').forEach(b=>b.addEventListener('click',()=>{panel.dataset.scale=b.dataset.scale;render(panel);}));
    panel.querySelector('details').addEventListener('toggle',()=>table(panel));
  }
  function update(key,s){
    const panel=document.querySelector('[data-spectrum-key="'+key+'"]');check(panel,'Missing spectrum panel');
    validate(s);panel._spectrum=s;attach(panel);
    panel.querySelector('figcaption').textContent=s.title;
    controls(panel);
    const g=geometry(s,panel.dataset.scale),notes=s.series.map(v=>{const shown=g.selected.reduce((n,i)=>n+v.counts[i],0),outside=v.counts.reduce((a,b)=>a+b,0)-shown;return presentation(v)[0]+': '+shown.toLocaleString('en-US')+' in view; '+outside.toLocaleString('en-US')+' outside view; under/overflow '+v.underflow+'/'+v.overflow+(v.exact_zero?'; '+v.exact_zero.toLocaleString('en-US')+' exact-zero events listed separately':'')+'; population '+v.total.toLocaleString('en-US')+'.';});
    panel.querySelector('.spectrum-account').textContent=notes.join(' ');
    panel.querySelector('.spectrum-data').textContent=JSON.stringify(s);
    render(panel);
  }
  global.SpectrumUI={geometry,validate,attach,update,presentation};
  if(typeof document!=='undefined'){
    const init=()=>document.querySelectorAll('.spectrum-panel').forEach(attach);
    if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
  }
})(globalThis);
