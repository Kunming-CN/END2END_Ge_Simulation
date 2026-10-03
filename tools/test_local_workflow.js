// Browser contract checks with a small DOM substitute; no scientific workers.
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class Element {
  constructor(tag='div'){this.tagName=tag;this.children=[];this.value='';this.checked=false;this.disabled=false;this.textContent='';this.isConnected=true;this.dataset={};}
  append(...nodes){this.children.push(...nodes);if(this.tagName==='select'&&this.children.length&&this.value==='')this.value=this.children[0].value;}
  replaceChildren(...nodes){this.children=[];this.value='';this.append(...nodes);}
  addEventListener(name,fn){this['on'+name]=fn;}
  scrollIntoView(){}
  setAttribute(name,value){this[name]=value;}
}
const svgNs='http://www.w3.org/2000/svg';
function xml(tag,attrs={},children=[]){return {nodeType:1,localName:tag,prefix:null,namespaceURI:null,attributes:Object.entries(attrs).map(([name,value])=>({name,value,prefix:null})),childNodes:children};}
const svgDocument={doctype:null,documentElement:xml('svg',{role:'img',viewBox:'0 0 600 205'},[xml('polyline',{points:'55,160 565,35',fill:'none',stroke:'currentColor','stroke-width':'1.7'}),xml('text',{x:'5',y:'35'},[{nodeType:3,nodeValue:'-0.003'}])]),getElementsByTagName:()=>[]};
class Parser{parseFromString(){return svgDocument;}}
const elements=new Map(),get=id=>{if(!elements.has(id))elements.set(id,new Element(id==='event'||id==='group'?'select':'div'));return elements.get(id);};
const context=vm.createContext({document:{getElementById:get,createElement:tag=>new Element(tag),createElementNS:(ns,tag)=>{const n=new Element(tag);n.namespaceURI=ns;return n;},createTextNode:text=>({textContent:text})},DOMParser:Parser,
  location:{hash:'#fixture',pathname:'/'},sessionStorage:{getItem:()=>'',setItem:()=>{}},history:{replaceState:()=>{}},
  URLSearchParams,TextDecoder,Uint8Array,fetch:()=>new Promise(()=>{}),setInterval:()=>{},setTimeout:()=>{}});
vm.runInContext(fs.readFileSync(__dirname+'/local_workflow.js','utf8'),context);
function run(code){return vm.runInContext(code,context);}
run(`catalog={electronics_keys:Object.keys(labels),electronics_defaults:{},sources:[{id:'mono_gamma_662_axis_v1',label:'Gamma',pose:'plus5mm',counts:[20]},{id:'cs137_point_decay_v1',label:'Cs137',pose:'nominal',counts:[20,500]}],cryostats:[{id:'lbnl_modular_nominal_v1',available:true}],detectors:[{id:'AK02',available:true,sources:['mono_gamma_662_axis_v1','cs137_point_decay_v1']},{id:'SAP22',available:true,sources:['mono_gamma_662_axis_v1','cs137_point_decay_v1']},{id:'GeRC02',available:true,sources:['cs137_point_decay_v1'],operating_label:'Li50min +240 V'},{id:'KMRC01_candidate',available:true,sources:['cs137_point_decay_v1'],operating_label:'−370 V; fixed −1 wiring'}]};`);
// A primary's delayed groups and zero primaries are all independently selectable.
run(`result={job:{name:'fixture'},records:[
 {record_kind:'decay',event_id:7,deposited_energy_keV:4,pulse_count:2,zero_deposit:false},
 {record_kind:'pulse',event_id:7,group_id:0,origin_time_ns:10,deposited_energy_keV:1,final_induced_keV:-0.003,readout:{reconstructed_energy_keV:null}},
 {record_kind:'pulse',event_id:7,group_id:1,origin_time_ns:500000,deposited_energy_keV:3,final_induced_keV:1e-12,readout:{reconstructed_energy_keV:2.5}},
 {record_kind:'decay',event_id:8,deposited_energy_keV:0,pulse_count:0,zero_deposit:true}],traces:[]};$('event').value='7';showEvent();`);
assert.equal(get('group').children.length,3);
get('group').value='1';run('showGroup()');
assert.match(get('event-identity').textContent,/primary 7 · pulse group 0 · origin 10 ns/);
assert.equal(get('result-data').children[0].children[1].children[0].textContent,'-0.003');
get('group').value='2';run('showGroup()');
assert.equal(get('result-data').children[0].children[1].children[0].textContent,'1e-12');
assert.equal(get('result-data').children[0].children[2].children[0].textContent,'2.5');
assert.match(get('event-record').textContent,/500000/);
get('event').value='8';run('showEvent()');
assert.equal(get('group').children.length,1);
assert.equal(get('result-data').children[0].children[0].children[0].textContent,'0');
assert.equal(get('result-data').children[0].children[1].children[0].textContent,'0');
// Initial presentation finds saved native-completed pulses even with negative
// KM charge. No primary/zero/failure is removed from the actual selector.
run(`const ringRows=[{record_kind:'decay',event_id:0,deposited_energy_keV:0,pulse_count:0,zero_deposit:true},
 {record_kind:'pulse',event_id:1,group_id:0,deposited_energy_keV:4,status:'native_transport_failed',readout:null},
 {record_kind:'decay',event_id:2,deposited_energy_keV:4,pulse_count:1},
 {record_kind:'pulse',event_id:2,group_id:0,deposited_energy_keV:4,final_induced_keV:-3.9,readout:{reconstructed_energy_keV:4}}];`);
assert.deepEqual(JSON.parse(run("JSON.stringify(firstSavedWaveform(ringRows,[{event_id:2,group_id:0}]))")),{id:2,groupIndex:1});
assert.equal(run('firstSavedWaveform(ringRows,[])'),null);
// Every selected field and both gate boundaries are part of the checked data.
run('electronics();');
for(const label of get('electronics').children)assert.equal(label.htmlFor,label.children[0].id);
const html=fs.readFileSync(__dirname+'/local_workflow.html','utf8');
for(const id of ['cryostat','detector','source','pose','count','threads','seed','name','use-peak-gate','event','group'])assert.match(html,new RegExp('<label for="'+id+'"'));
for(const [id,value]of Object.entries({name:'fixture',cryostat:'lbnl_modular_nominal_v1',detector:'AK02',source:'mono_gamma_662_axis_v1',pose:'plus5mm',count:'20',seed:'26092631',threads:'2'}))get(id).value=value;
for(const key of run('Object.keys(labels)'))get('setting-'+key).value=key==='peak_policy'?'signed_input_positive_peak':key.startsWith('peak_gate_')?'':1;
get('setting-peak_gate_start_ns').value='100';get('setting-peak_gate_end_ns').value='2000';
assert.equal(run('config().electronics.peak_gate_start_ns'),null);
get('use-peak-gate').checked=true;run('gateFields();');
assert.equal(run('config().electronics.peak_gate_start_ns'),100);
assert.equal(run('config().electronics.peak_gate_end_ns'),2000);
run("checked={check_id:'old'};invalidate();");assert.equal(run('checked'),null);assert.equal(get('start').disabled,true);
assert.equal(run('importedConfig(config()).seed'),26092631);
assert.throws(()=>run('importedConfig({...config(),seed:42})'),/unavailable/);
assert.throws(()=>run('importedConfig({...config(),extra:1})'),/fields/);
// Ring changes visibly remove unavailable gamma; imports cannot bypass this.
get('detector').value='KMRC01_candidate';run('detectorChanged();');
assert.equal(get('source').children.length,1);assert.equal(get('source').value,'cs137_point_decay_v1');
assert.match(get('operating-details').textContent,/−370 V; fixed −1 wiring/);
assert.throws(()=>run("importedConfig({...config(),source:'mono_gamma_662_axis_v1',pose:'plus5mm'})"),/unavailable/);
get('detector').value='GeRC02';run('detectorChanged();');assert.match(get('operating-details').textContent,/Li50min/);
get('detector').value='AK02';run('detectorChanged();');get('source').value='mono_gamma_662_axis_v1';run('sourceChanged();');
assert.equal(get('source').children.length,2);
assert.match(html,/\.plot\{margin:0;min-width:0\}/);assert.match(html,/\.plot-grid>p,\.plot-grid>small\{grid-column:1\/-1;min-width:0;overflow-wrap:anywhere\}/);
// Open logs stay outside the recreated run cards; Results has an observed label.
get('log-text').textContent='retained UTF-16 diagnostic';get('log-view').hidden=false;
run("renderJobs({busy:false,jobs:[]});renderJobs({busy:false,jobs:[]});stageList({results:{status:'completed',elapsed_seconds:0.01}});");
assert.equal(get('log-text').textContent,'retained UTF-16 diagnostic');assert.equal(get('log-view').hidden,false);
assert.match(get('pipeline').children[4].children[1].children[0].textContent,/0.01 s observed/);
run("stageList({geometry:{status:'completed',reuse:'verified_transport_prefix',original_elapsed_seconds:7.62}});");
assert.match(get('pipeline').children[0].children[1].children[0].textContent,/Reused · originally 7.62 s/);
run("stageList({event_ledger:{status:'completed',reuse:'verified_transport_prefix',original_elapsed_seconds:null,elapsed_seconds:null,exit_code:null,finished_utc:null}});");
assert.match(get('pipeline').children[2].children[1].children[0].textContent,/saved artifacts verified; original execution time unavailable/);
assert.doesNotMatch(get('pipeline').children[2].children[1].children[0].textContent,/0\.00 s/);
run("continuationNames.set('m14a-gamma-ui-02','chosen-new-name');renderJobs({busy:true,jobs:[{id:'a',name:'m14a-gamma-ui-02',status:'dispatch_uncertain',can_continue_prefix:true,selection:{detector:'SAP22',source:'mono_gamma_662_axis_v1',primary_count:20},stages:{}}]});");
const continuation=get('runs').children[0].children.find(n=>n.tagName==='label');
assert.equal(continuation.htmlFor,'continue-name-a');assert.equal(continuation.children[0].value,'chosen-new-name');
assert.ok(get('runs').children[0].children.some(n=>n.textContent==='Continue from verified transport'));
run("renderJobs({busy:true,jobs:[{id:'b',name:'ring-ended',status:'dispatch_uncertain',can_finalize_results:true,selection:{detector:'GeRC02',source:'cs137_point_decay_v1',primary_count:500},stages:{}}]});");
assert.ok(get('runs').children[0].children.some(n=>n.textContent==='Finalize saved results'));
assert.ok(get('runs').children[0].children.some(n=>/No simulation is repeated/.test(n.textContent)));
assert.match(fs.readFileSync(__dirname+'/local_workflow.js','utf8'),/api\('\/api\/workflow\/finalize-results',\{name:job.name\}\)/);
run("renderJobs({busy:true,jobs:[{id:'b',name:'ring-ended',status:'dispatch_uncertain',can_finalize_results:false,selection:{detector:'GeRC02',source:'cs137_point_decay_v1',primary_count:500},stages:{}}]});");
assert.ok(!get('runs').children[0].children.some(n=>n.textContent==='Finalize saved results'));
run('renderJobs({busy:false,jobs:[]});');
// The read-only saved completion action remains visible beside uncertain work.
run("renderJobs({busy:true,jobs:[]});renderLegacy({gamma:{busy:true,jobs:[{id:'old',label:'old-completion',status:'verification-required',blocks_new_work:true,can_verify:true}]}});");
assert.ok(get('legacy-runs').children[0].children.some(n=>n.textContent==='Verify saved completion'));
assert.match(get('legacy-notice').textContent,/Before starting another calculation.*Verify saved completion/);
assert.equal(get('legacy-recovery').open,true);
run("renderLegacy({gamma:{jobs:[{label:'held',status:'verification-required',blocks_new_work:true,can_verify:false}]}});");
assert.match(get('legacy-notice').textContent,/currently unavailable/);
assert.ok(!get('legacy-runs').children[0].children.some(n=>n.tagName==='button'));
run("renderLegacy({gamma:{jobs:[{label:'uncertain',status:'blocked',blocks_new_work:true,can_verify:false,error:{message:'Unknown worker lifetime'}}]}});");
assert.match(get('legacy-notice').textContent,/needs verification or inspection/);
assert.equal(get('legacy-notice').hidden,false);
run("renderLegacy({gamma:{jobs:[{label:'old-ended-failure',status:'failed',blocks_new_work:false,can_verify:false,error:{message:'Historical failure retained'}},{label:'verified',status:'completed',blocks_new_work:false,can_verify:true}]}});");
assert.equal(get('legacy-notice').hidden,true);
assert.ok(get('legacy-runs').children[0].children.some(n=>n.textContent==='Historical failure retained'));
assert.ok(!get('legacy-runs').children[0].children.some(n=>/stays unavailable/.test(n.textContent)));
run("renderLegacy({gamma:{jobs:[{label:'uncertain-failed',status:'failed',blocks_new_work:true,can_verify:false}]}});");
assert.equal(get('legacy-notice').hidden,false);
assert.match(get('legacy-notice').textContent,/needs verification or inspection/);
run("renderLegacy({gamma:{jobs:[]}});");assert.equal(get('legacy-notice').hidden,true);
run('renderJobs({busy:false,jobs:[]});');
// Editing the next setup never relabels the immutable run whose stages are shown.
run("const savedJob={name:'saved-sap-gamma',configuration_sha256:'a'.repeat(64),selection:{detector:'SAP22',source:'mono_gamma_662_axis_v1',primary_count:20,electronics:{gain:21}},stages:{geometry:{status:'completed',elapsed_seconds:7.62}}};showRun(savedJob);");
get('detector').value='AK02';get('source').value='cs137_point_decay_v1';run('sourceChanged();');
assert.match(get('setup-preview').textContent,/Current setup · AK02 · Cs137/);
assert.match(get('selected').textContent,/Selected run · saved-sap-gamma · SAP22 · Gamma/);
assert.match(get('run-plan').textContent,/"gain": 21/);
run('renderJobs({busy:false,jobs:[{...savedJob,id:"saved",status:"completed"}]});');
assert.match(get('selected').textContent,/SAP22 · Gamma/);
get('source').value='mono_gamma_662_axis_v1';run('sourceChanged();');
// The native SVG namespace is supplied without changing saved attribute strings.
const rendered=run("safeSvg('<svg/>')");assert.equal(rendered.namespaceURI,svgNs);
assert.equal(rendered.children[0].points,'55,160 565,35');assert.equal(rendered.children[1].children[0].textContent,'-0.003');
assert.throws(()=>run("safeSvg('<!DOCTYPE svg><svg/>')"),/Unsupported/);
const originalTree=svgDocument.documentElement;svgDocument.documentElement=xml('script');
assert.throws(()=>run("safeSvg('<svg/>')"),/Malformed|Unsupported/);svgDocument.documentElement=originalTree;
originalTree.attributes.push({name:'onload',value:'bad',prefix:null});
assert.throws(()=>run("safeSvg('<svg/>')"),/attribute/);originalTree.attributes.pop();
originalTree.namespaceURI=svgNs;originalTree.attributes.push({name:'xmlns',value:svgNs,prefix:null});
assert.equal(run("safeSvg('<svg/>')").xmlns,svgNs);originalTree.attributes.pop();originalTree.namespaceURI=null;
originalTree.prefix='foreign';assert.throws(()=>run("safeSvg('<svg/>')"),/element/);originalTree.prefix=null;
svgDocument.doctype={};assert.throws(()=>run("safeSvg('<svg/>')"),/Malformed/);svgDocument.doctype=null;
svgDocument.getElementsByTagName=()=>[{}];assert.throws(()=>run("safeSvg('<svg/>')"),/Malformed/);svgDocument.getElementsByTagName=()=>[];
// A delayed old Check reply cannot enable Start for a changed current selection.
(async()=>{
  run("let resolveCheck;api=()=>new Promise(resolve=>resolveCheck=resolve);");
  const pending=run("$('check').onclick()");
  get('detector').value='SAP22';run("invalidate();resolveCheck({check_id:'old',resolved:{selection:{detector:'AK02'}}});");
  await pending;assert.equal(run('checked'),null);assert.equal(get('start').disabled,true);
  for(const [id,value]of [['name','changed-name'],['setting-gain','4'],['source','cs137_point_decay_v1']]){
    const old=run("$('check').onclick()");get(id).value=value;
    run(id==='source'?"sourceChanged();":"invalidate();");
    run("resolveCheck({check_id:'stale',resolved:{selection:{detector:'AK02'}}});");await old;
    assert.equal(run('checked'),null);assert.equal(get('start').disabled,true);
  }
  const current=run("$('check').onclick()");run("resolveCheck({check_id:'new',resolved:{selection:{detector:'SAP22'}}});");await current;
  assert.equal(run('checked.check_id'),'new');assert.equal(get('start').disabled,false);
  // A slow old report cannot replace a newer run; native failure stays null.
  run("let reports=[];artifact=(name,file)=>new Promise((resolve,reject)=>reports.push({name,file,resolve,reject}));const newerJob={...savedJob,name:'newer-run',configuration_sha256:'b'.repeat(64)};");
  const oldReport=run('openResult(savedJob)'),newReport=run('openResult(newerJob)');
  run("reports[2].resolve({json:async()=>({cases:[{initial_primary_id:3,event_id:3,zero_ge:false,status:'native_failed',truth_ge_edep_keV:4,final_induced_keV:null,readout:null}],artifacts:{'summary.html':'c'.repeat(64)}})});reports[3].resolve({json:async()=>({configuration_sha256:newerJob.configuration_sha256,artifacts:{'response/summary.html':{sha256:'c'.repeat(64)}}})});");
  await newReport;assert.match(get('result-heading').textContent,/newer-run/);assert.match(get('plots').children[0].textContent,/No saved waveform/);
  assert.equal(get('result-data').children[0].children[1].children[0].textContent,'Unavailable');
  run("reports[0].resolve({json:async()=>({cases:[],artifacts:{'summary.html':'c'.repeat(64)}})});reports[1].resolve({json:async()=>({configuration_sha256:savedJob.configuration_sha256,artifacts:{'response/summary.html':{sha256:'c'.repeat(64)}}})});");
  await oldReport;assert.match(get('result-heading').textContent,/newer-run/);
  // Delayed scalar/trace reads from an old Cs report are fenced too.
  const oldCs=run('openResult(savedJob)');run("reports[4].resolve({json:async()=>({artifacts:{'summary.html':'c'.repeat(64)}})});reports[5].resolve({json:async()=>({configuration_sha256:savedJob.configuration_sha256,artifacts:{'response/summary.html':{sha256:'c'.repeat(64)}}})});");
  for(let tick=0;tick<8;tick++)await Promise.resolve();assert.equal(run('reports.length'),8);
  run('showRun(newerJob);');
  run("reports[6].resolve({text:async()=>JSON.stringify({record_kind:'decay',event_id:1,pulse_count:0})});reports[7].resolve({text:async()=>''});");
  await oldCs;assert.equal(run('selectedJob'),'newer-run');assert.equal(run('result'),null);
  const staleError=run('openResult(savedJob)');run("showRun(newerJob);reports[8].reject(Error('Old result unavailable'));");
  await staleError;assert.equal(run('selectedJob'),'newer-run');assert.equal(run('result'),null);
  // Positive → zero → positive: late replies never paint under another group.
  run("let plotReplies=[];api=path=>new Promise(resolve=>plotReplies.push({path,resolve}));result={job:newerJob,summaryHash:'c'.repeat(64),records:[{initial_primary_id:2,event_id:2,zero_ge:false,readout:{trace:{}}},{initial_primary_id:0,event_id:0,zero_ge:true,readout:{trace:{}}}],traces:[]};$('event').value='2';showEvent();");
  get('event').value='0';run('showEvent();');get('event').value='2';run('showEvent();');
  assert.match(run('plotReplies[1].path'),/primary=0&group=none/);assert.match(run('plotReplies[2].path'),/primary=2&group=0/);
  run("const plotReply=(id,group)=>({name:newerJob.name,configuration_sha256:newerJob.configuration_sha256,primary_id:id,group_id:group,summary_sha256:'c'.repeat(64),figures:['Charge (fC)','Original-bin current (nA)','Analog preamp (V)','Analog shaper (V)'].map(caption=>({caption,svg:'<svg/>'})),notes:['Bounded display samples; current belongs to original intervals.']});plotReplies[2].resolve(plotReply(2,0));");
  await Promise.resolve();await Promise.resolve();assert.equal(get('plots').children.filter(n=>n.tagName==='figure').length,4);
  run('plotReplies[1].resolve(plotReply(0,null));plotReplies[0].resolve(plotReply(2,0));');
  await Promise.resolve();await Promise.resolve();assert.equal(get('plots').children.filter(n=>n.tagName==='figure').length,4);
  assert.match(get('event-identity').textContent,/Initial primary 2/);
  get('event').value='0';run('showEvent();plotReplies[3].resolve(plotReply(0,null));');
  await Promise.resolve();await Promise.resolve();assert.equal(get('plots').children.filter(n=>n.tagName==='figure').length,4);assert.match(get('event-identity').textContent,/known zero input/);
  run("showGroup();plotReplies[4].resolve(plotReply(0,0));");await Promise.resolve();await Promise.resolve();assert.match(get('plots').children[0].textContent,/identities differ/);
  run("showGroup();showRun(savedJob);plotReplies[5].resolve(plotReply(0,null));");await Promise.resolve();await Promise.resolve();assert.equal(get('plots').children.length,0);
  console.log('Browser setup/run binding, all groups/zeros/null/signs, stale Check/report/plot fencing, inline four-SVG and recovery notice contracts passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
