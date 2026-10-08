// Browser contract checks with a small DOM substitute; no scientific workers.
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class Element {
  constructor(tag='div'){this.tagName=tag;this.children=[];this.value='';this.checked=false;this.disabled=false;this.textContent='';this.isConnected=true;this.dataset={};this.style={};this.open=false;}
  append(...nodes){this.children.push(...nodes);if(this.tagName==='select'&&this.children.length&&this.value==='')this.value=this.children[0].value;}
  replaceChildren(...nodes){this.children=[];this.value='';this.append(...nodes);}
  addEventListener(name,fn){this['on'+name]=fn;}
  scrollIntoView(){}
  click(){this.clicked=true;}
  setAttribute(name,value){this[name]=value;}
  removeAttribute(name){delete this[name];}
}
const svgNs='http://www.w3.org/2000/svg';
function xml(tag,attrs={},children=[]){return {nodeType:1,localName:tag,prefix:null,namespaceURI:null,attributes:Object.entries(attrs).map(([name,value])=>({name,value,prefix:null})),childNodes:children};}
const svgDocument={doctype:null,documentElement:xml('svg',{role:'img',viewBox:'0 0 600 205'},[xml('polyline',{points:'55,160 565,35',fill:'none',stroke:'currentColor','stroke-width':'1.7'}),xml('text',{x:'5',y:'35'},[{nodeType:3,nodeValue:'-0.003'}])]),getElementsByTagName:()=>[]};
class Parser{parseFromString(){return svgDocument;}}
const elements=new Map(),get=id=>{if(!elements.has(id))elements.set(id,new Element(['cryostat','detector','source','pose','threads','event','group'].includes(id)?'select':'div'));return elements.get(id);};
const context=vm.createContext({document:{getElementById:get,createElement:tag=>new Element(tag),createElementNS:(ns,tag)=>{const n=new Element(tag);n.namespaceURI=ns;return n;},createTextNode:text=>({textContent:text})},DOMParser:Parser,
  location:{hash:'#fixture',pathname:'/'},sessionStorage:{getItem:()=>'',setItem:()=>{}},history:{replaceState:()=>{}},
  URL:{createObjectURL:()=> 'blob:fixture',revokeObjectURL:()=>{}},URLSearchParams,TextDecoder,Uint8Array,fetch:()=>new Promise(()=>{}),setInterval:()=>{},setTimeout:()=>{}});
vm.runInContext(fs.readFileSync(__dirname+'/focused_plots.js','utf8'),context);
vm.runInContext(fs.readFileSync(__dirname+'/local_workflow.js','utf8'),context);
function run(code){return vm.runInContext(code,context);}
run(`catalog={electronics_keys:Object.keys(labels),electronics_defaults:{},sources:[{id:'mono_gamma_662_axis_v1',label:'Gamma',pose:'plus5mm',pose_label:'+5 mm along global y',counts:[20],fixed_seed:26092631,details:'One 662 keV gamma per primary; fixed global −y beam, time zero.',count_unit:'initial gamma primaries'},{id:'cs137_point_decay_v1',label:'Cs137',pose:'nominal',pose_label:'Nominal source anchor',counts:[20,500],details:'One initial Cs137 decay per primary; isolated pulse windows retain daughter timing.',count_unit:'initial Cs137 decays',fixed_seed:null}],cryostats:[{id:'lbnl_modular_nominal_v1',available:true}],detectors:[{id:'AK02',available:true,sources:['mono_gamma_662_axis_v1','cs137_point_decay_v1']},{id:'SAP22',available:true,sources:['mono_gamma_662_axis_v1','cs137_point_decay_v1']},{id:'GeRC02',available:true,sources:['cs137_point_decay_v1'],operating_label:'Li50min +240 V'},{id:'KMRC01_candidate',available:true,sources:['cs137_point_decay_v1'],operating_label:'−370 V; fixed −1 wiring'}]};`);
// A primary's delayed groups and zero primaries are all independently selectable.
run(`result={job:{name:'fixture'},records:[
 {record_kind:'decay',event_id:7,deposited_energy_keV:4,pulse_count:2,zero_deposit:false},
 {record_kind:'pulse',event_id:7,group_id:0,origin_time_ns:10,deposited_energy_keV:1,final_induced_keV:-0.003,readout:{reconstructed_energy_keV:null}},
 {record_kind:'pulse',event_id:7,group_id:1,origin_time_ns:500000,deposited_energy_keV:3,final_induced_keV:1e-12,readout:{reconstructed_energy_keV:2.5}},
 {record_kind:'decay',event_id:8,deposited_energy_keV:0,pulse_count:0,zero_deposit:true}],traces:[]};$('event').value='7';showEvent();`);
assert.equal(get('group').children.length,3);
get('group').value='1';run('showGroup()');
assert.match(get('event-identity').textContent,/primary 7 · pulse group 0 · origin 10 ns/);
assert.match(get('analysis-selection').textContent,/Saved run fixture.*initial primary ID 7.*local initial ID 7.*pulse group 0.*origin 10 ns/);
assert.match(get('analysis-filter').textContent,/Raw LH5: filter evtid = 7.*Derived JSONL\/CSV: filter event_id = 7.*rows that carry group_id, filter group_id = 0/);
assert.equal(get('result-data').children[0].children[1].children[0].textContent,'-0.003');
get('group').value='2';run('showGroup()');
assert.match(get('analysis-filter').textContent,/group_id = 1/);
assert.equal(get('result-data').children[0].children[1].children[0].textContent,'1e-12');
assert.equal(get('result-data').children[0].children[2].children[0].textContent,'2.5');
assert.match(get('event-record').textContent,/500000/);
get('event').value='8';run('showEvent()');
assert.equal(get('group').children.length,1);
assert.equal(get('result-data').children[0].children[0].children[0].textContent,'0');
assert.equal(get('result-data').children[0].children[1].children[0].textContent,'0');
assert.match(get('analysis-filter').textContent,/evtid = 8.*group_id is null/);
assert.match(get('analysis-state').textContent,/Zero deposition.*no pulse group.*No deposition waveform or reconstructed energy is inferred/);
get('event').value='999';run('showEvent()');
assert.equal(get('event-identity').textContent,'');assert.equal(get('result-data').children.length,0);
assert.match(get('analysis-selection').textContent,/no primary selected/);assert.doesNotMatch(get('analysis-filter').textContent,/evtid = 8/);
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
assert.match(html,/position_mm in mm and global_position_m in m/);
assert.match(html,/raw LH5, position columns use m, step edep uses keV and time uses ns; track and particle ekin use MeV/);
assert.match(html,/raw_tables.*columns; those units are authoritative/);
assert.match(html,/Deposition time, particle creation time and carrier drift time describe different stages/);
assert.doesNotMatch(html,/Energy uses keV; positions use mm/);
assert.match(html,/Check environment inspects installed files\. Check plan validates the selected source, runtime and settings/);
assert.match(html,/<details id="legacy-recovery">/);
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
// Every catalog model is selectable for inspection, while unsupported selections
// cannot Check, Start or export. The immutable selected run stays independent.
run("const currentModels=catalog.detectors;catalog.detectors=[...currentModels,...Array.from({length:13},(_,i)=>({id:'view-'+i,label:'Reference '+i,available:false,reason:'No checked connector',sources:[],model:{group:'reference',status:'reference only',assumptions:['No physical identity claim'],contacts:[{id:1,name:'readout',potential_V:0},{id:2,name:'outer',potential_V:-380}],readout_contact_id:1},geometry_url:'https://example.test/geometry'}))];options('detector',catalog.detectors,true);");
assert.equal(get('detector').children.length,17);
assert.ok(get('detector').children.every(n=>!n.disabled));
for(let i=0;i<13;i++){
  get('detector').value='view-'+i;run('detectorChanged();');
  assert.equal(get('source').children.length,0);assert.equal(get('count').children.length,0);
  assert.match(get('model-capability').textContent,/View only.*No checked connector/);
  assert.match(get('setup-preview').textContent,/view only; no source/);
  assert.equal(get('model-contacts').children[1].textContent,'Contact 2 · outer · -380 V');
  for(const id of ['check','start','save','source','count'])assert.equal(get(id).disabled,true,id);
  assert.equal(get('load').disabled,false);
  assert.throws(()=>run('importedConfig({...config(),source:"cs137_point_decay_v1",pose:"nominal",primary_count:20})'),/unavailable/);
}
run("catalog.detectors.push({id:'GeGI_3D',available:false,sources:[],model:{contacts:Array.from({length:34},(_,i)=>({id:i+1,name:'strip '+(i+1),potential_V:i<17?-879:0})),readout_contact_id:9}});");get('detector').value='GeGI_3D';run('detectorChanged();');
assert.equal(get('model-contacts').children.length,34);assert.equal(get('model-contact-list').open,false);assert.match(get('model-contact-summary').textContent,/34 contacts.*readout contact 9/);
assert.equal(get('model-contacts').children[8].textContent,'Contact 9 · strip 9 · -879 V · catalog readout');
run('catalog.detectors=currentModels;');get('detector').value='AK02';run('detectorChanged();');
// The common model entry is selected by its checked contract, not detector IDs.
run("catalog.detectors.push({id:'AK01',available:true,workflow_kind:'local_catalog_workflow_v1',sources:['cs137_point_decay_v1'],operating_label:'Original 78 K; readout contact 1; contact 2 +700 V',parameter_summary:[{label:'Model temperature',value:78,unit:'K'},{label:'Readout contact',value:1}],checks:[{label:'Cryostat fit',status:'supported',detail:'Fits the selected LBNL cavity'}]},{id:'large-model',available:false,block_code:'cryostat_size',reason:'Radius 40 mm exceeds cryostat half-width 20.574 mm; a larger cryostat is needed.',sources:[],operating_label:'Original 92.3 K; readout contact 9'});options('detector',detectorItems(),true);");
assert.ok(get('detector').children.slice(0,5).every(n=>!n.textContent.includes('larger cryostat')));
get('detector').value='AK01';run('detectorChanged();');
assert.equal(run('sharedModelSelection()'),true);assert.equal(get('check').disabled,false);
assert.match(get('model-capability').textContent,/Available in the current cryostat.*Check plan/);
assert.equal(get('model-parameters').children[0].textContent,'Model temperature: 78 K');
assert.equal(get('model-parameters').children[1].textContent,'Readout contact: 1');
get('detector').value='large-model';run('detectorChanged();');
assert.match(get('model-capability').textContent,/Radius 40 mm.*20.574 mm.*larger cryostat/);
assert.doesNotMatch(get('model-capability').textContent,/pending|missing input/i);
assert.equal(get('check').disabled,true);assert.equal(get('model-parameters').children[0].textContent,'Original 92.3 K; readout contact 9');
assert.ok(get('detector').children.find(n=>n.value==='large-model').textContent.endsWith('Needs larger cryostat'));
get('detector').value='AK02';run('detectorChanged();');
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
assert.equal(get('legacy-recovery').open,false);
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
get('legacy-recovery').open=true;
run("renderLegacy({gamma:{jobs:[]}});");assert.equal(get('legacy-recovery').open,true);
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
// Source policy is catalog data; no isotope description is inferred in the UI.
run(`catalog.sources.push({id:'am241_point_decay_v1',label:'Am241 point decay',pose:'nominal',pose_label:'Shared nominal anchor',counts:[20,500],available:false,reason:'Acceptance pending',details:'One initial Am241 decay per primary; daughter timing remains recorded.',count_unit:'initial Am241 decays',position_global_mm:[0,37.073,.290],source_contract:{isotope:{Z:95,A:241}},acceptance:{status:'pending'}});catalog.detectors.forEach(d=>{if(d.available)d.sources.push('am241_point_decay_v1');});`);
get('detector').value='SAP22';run('detectorChanged();');
assert.equal(get('source').children.find(o=>o.value==='am241_point_decay_v1').disabled,true);
assert.throws(()=>run(`importedConfig({...config(),source:'am241_point_decay_v1',pose:'nominal',primary_count:500,seed:17})`),/unavailable/);
run("catalog.sources.find(s=>s.id==='am241_point_decay_v1').available=true;");get('source').value='am241_point_decay_v1';run('sourceChanged();');
assert.match(get('source-details').textContent,/Am241.*daughter timing/);assert.doesNotMatch(get('source-details').textContent,/Cs137/);
assert.match(get('source-identity').textContent,/95/);assert.equal(get('seed').disabled,false);
assert.equal(run("importedConfig({...config(),seed:17}).seed"),17);
for(const bad of [true,500.0+0.5,'500'])assert.throws(()=>run(`importedConfig({...config(),primary_count:${JSON.stringify(bad)}})`),/unavailable/);
run("showRun(savedJob);");assert.match(get('selected').textContent,/saved-sap-gamma.*Gamma/);
run(`savedArtifacts(savedJob,{artifacts:{'resolved-config.json':{sha256:'1'.repeat(64),bytes:101},'transport/truth.lh5':{sha256:'2'.repeat(64),bytes:202},'transport/stream/events-00000.jsonl':{sha256:'3'.repeat(64),bytes:303},'response/scalars.jsonl':{sha256:'4'.repeat(64),bytes:404},'response/calibration.json':{sha256:'5'.repeat(64),bytes:505},'unrelated.json':{sha256:'6'.repeat(64),bytes:606}}});`);
const artifactButtons=get('saved-artifacts').children.flatMap(row=>row.children).filter(n=>n.tagName==='button').map(n=>n.textContent);
for(const name of ['COMPLETE.json','transport/truth.lh5','transport/stream/events-00000.jsonl','response/scalars.jsonl','response/calibration.json'])assert.ok(artifactButtons.includes('Download '+name),name);
assert.ok(!artifactButtons.includes('Download unrelated.json'));
assert.ok(get('saved-artifacts').children.flatMap(row=>row.children).some(n=>/202 bytes.*SHA256/.test(n.textContent)));
get('source').value='mono_gamma_662_axis_v1';run('sourceChanged();');
// Exact decimal input rejects coercion and preserves the legacy Gamma contract.
assert.match(html,/<input id="count" type="text" inputmode="numeric"/);
for(const text of ['0','-1','1.5','1e3',' 500','500 ','9007199254740992','true',''])assert.throws(()=>run(`exactInteger(${JSON.stringify(text)},'Initial primaries')`),/integer|range/);
for(const n of [1,499,500,9999,10000,10001,25001])assert.equal(run(`exactInteger('${n}','Initial primaries')`),n);
assert.equal(get('count').readOnly,true);assert.equal(get('count').value,'20');
get('source').value='cs137_point_decay_v1';run('sourceChanged();');get('count').value='25001';
assert.equal(get('count').readOnly,false);assert.equal(run('config().primary_count'),25001);
assert.equal(run('importedRequest(batchRequest(config())).primary_count'),25001);
assert.throws(()=>run('importedConfig(config())'),/unavailable/);
for(const bad of [true,500.5,'500',0,9007199254740992])assert.throws(()=>run(`importedRequest(batchRequest({...config(),primary_count:${JSON.stringify(bad)}}))`),/unavailable/);
assert.throws(()=>run('importedRequest({...batchRequest(config()),extra:true})'),/fields/);
get('count').value='500';get('source').value='mono_gamma_662_axis_v1';run('sourceChanged();');
// Per-batch pages retain boundary identities, signs, raw deposits and null failures.
run(`const batchJob={name:'batch-saved',configuration_sha256:'d'.repeat(64),execution_contract:'serial_batches_v3',status:'completed',selection:{detector:'AK01',source:'cs137_point_decay_v1',primary_count:25001},batching:{batch_count:3},stages:{}};
function batchFixture(batch,offset,count=1){const globalOffset=batch*10000;return {kind:'local_batch_event_page_v1',name:batchJob.name,configuration_sha256:batchJob.configuration_sha256,batch_index:batch,batch_offset:globalOffset,batch_primary_count:10000,offset,limit:100,next_offset:offset+count<10000?offset+count:null,batch_sha256:'e'.repeat(64),response_summary_sha256:'f'.repeat(64),traces:[],artifacts:[{file:'batches/b'+String(batch).padStart(10,'0')+'/response/scalars.jsonl',bytes:404,sha256:'4'.repeat(64)}],records:Array.from({length:count},(_,i)=>({batch_index:batch,global_initial_id:globalOffset+offset+i,local_initial_id:offset+i,truth:{steps:[{energy_keV:4,time_ns:500000,raw_row_index:12}]},primary:{record_kind:'decay',event_id:offset+i,pulse_count:1,deposited_energy_keV:4},pulse_groups:[{record_kind:'pulse',event_id:offset+i,group_id:0,origin_time_ns:500000,final_induced_keV:-.003,deposited_energy_keV:4,readout:null,status:'native_transport_failed'}]}))};}
`);
for(const [batch,local,global]of [[0,9999,9999],[1,0,10000],[1,9999,19999],[2,0,20000]]){
  assert.equal(run(`flatBatchRecords(pageIdentity(batchFixture(${batch},${local}),batchJob,${batch},${local}))[1].global_initial_id`),global);
}
assert.throws(()=>run('pageIdentity({...batchFixture(1,0),name:"wrong"},batchJob,1,0)'),/identities/);
assert.throws(()=>run('pageIdentity({...batchFixture(1,0),batch_index:2},batchJob,1,0)'),/identities/);
run(`showRun(batchJob);result={job:batchJob,records:flatBatchRecords(batchFixture(1,0)),traces:[]};$('event').value='10000';showEvent(1);`);
assert.equal(get('result-data').children[0].children[1].children[0].textContent,'-0.003');
assert.equal(get('result-data').children[0].children[2].children[0].textContent,'Unavailable');
assert.match(get('event-record').textContent,/500000/);assert.match(get('event-record').textContent,/raw_row_index/);
assert.match(get('analysis-selection').textContent,/batch 1.*global initial ID 10000.*local initial ID 0.*pulse group 0/);
assert.match(get('analysis-filter').textContent,/evtid = 0 in batch 1.*Do not use global initial ID 10000 as raw evtid.*global_initial_id = 10000.*filter group_id = 0/);
assert.match(get('analysis-filter').textContent,/Ledger and response\/truth rows represent whole primaries and have no top-level group_id/);
assert.match(get('analysis-state').textContent,/Native transport failed.*null charge, endpoint or readout values are unknown/);
run(`result.records[1].final_induced_keV=null;result.traces=[{global_initial_id:10000,group_id:0}];showGroup();`);
assert.equal(get('result-data').children[0].children[1].children[0].textContent,'Unavailable');
assert.match(get('plots').children[0].textContent,/No saved waveform/);
run(`showEvent(0);`);assert.match(get('analysis-filter').textContent,/global_initial_id = 10000.*group_id is null in scalars/);
// Grouped file explanations preserve every supplied artifact reference and stamp.
run(`const inventoryPage=batchFixture(1,0);inventoryPage.artifacts=['transport/truth.lh5','transport/run.mac','transport/run.json','transport/stream/manifest.json','transport/stream/decays-00000000.jsonl','response/truth.jsonl','response/signals.csv','response/endpoints.jsonl','response/scalars.jsonl','response/traces.jsonl','response/run.json','response/readout-config.json','response/profile.json','receipts/response.json','other-saved-stage.json'].map((ref,i)=>({file:'batches/b0000000001/'+ref,bytes:100+i,sha256:String(i%10).repeat(64)}));const inventoryBefore=JSON.stringify(inventoryPage);batchArtifacts(batchJob,inventoryPage);`);
const allArtifactNodes=get('saved-artifacts').children.flatMap(row=>row.children||[]),allArtifactButtons=allArtifactNodes.filter(n=>n.tagName==='button');
const inventory=JSON.parse(run('JSON.stringify(inventoryPage.artifacts)'));
assert.equal(allArtifactButtons.length,inventory.length+3);
for(const stamp of inventory){assert.equal(allArtifactButtons.filter(n=>n.textContent==='Download '+stamp.file).length,1);assert.ok(allArtifactNodes.some(n=>n.textContent===stamp.bytes+' bytes · SHA256 '+stamp.sha256));}
assert.equal(run('JSON.stringify(inventoryPage)'),run('inventoryBefore'));
assert.ok(allArtifactNodes.some(n=>/independent injection calibration/.test(n.textContent)));
assert.ok(allArtifactNodes.some(n=>/each column’s units, coordinate transforms/.test(n.textContent)));
assert.ok(allArtifactNodes.some(n=>/signed induced-equivalent charge samples/.test(n.textContent)));
assert.ok(!allArtifactButtons.some(n=>n.clicked));
const savedAnalysisIdentity=get('analysis-selection').textContent,savedAnalysisFilter=get('analysis-filter').textContent;
get('name').value='next-run-name';run('invalidate();');
assert.equal(get('analysis-selection').textContent,savedAnalysisIdentity);assert.equal(get('analysis-filter').textContent,savedAnalysisFilter);
// Optional local acceptance uses retained science as read-only inputs; no workers.
if(process.env.GESIGNAL_TEST_SAVED_ROOT){
  const path=require('node:path'),crypto=require('node:crypto'),savedRoot=process.env.GESIGNAL_TEST_SAVED_ROOT;
  const read=file=>JSON.parse(fs.readFileSync(path.join(savedRoot,file),'utf8'));
  const rows=file=>fs.readFileSync(path.join(savedRoot,file),'utf8').trim().split('\n').filter(Boolean).map(JSON.parse);
  const plan=read('resolved-config.json'),job={name:path.basename(savedRoot),configuration_sha256:plan.configuration_sha256,execution_contract:'serial_batches_v3',status:'completed',selection:plan.resolved.selection,stages:{}};
  for(const [batch,local,global,groupIndex]of [[0,0,0,0],[0,188,188,1],[1,0,250,0]]){
    const base='batches/b'+String(batch).padStart(10,'0'),truth=rows(base+'/response/truth.jsonl').find(r=>r.local_initial_id===local),parts=rows(base+'/response/scalars.jsonl').filter(r=>r.local_initial_id===local),stamps=['radiation','event_ledger','response'].flatMap(stage=>{const receipt=read(base+'/receipts/'+stage+'.json');return Object.entries(receipt.artifacts).map(([ref,stamp])=>({file:receipt.base+'/'+ref,...stamp}));});
    const page={kind:'local_batch_event_page_v1',name:job.name,configuration_sha256:job.configuration_sha256,batch_index:batch,batch_offset:global-local,batch_primary_count:250,offset:local,limit:100,next_offset:null,batch_sha256:crypto.createHash('sha256').update(fs.readFileSync(path.join(savedRoot,base,'batch-complete.json'))).digest('hex'),response_summary_sha256:'f'.repeat(64),traces:[],artifacts:stamps,records:[{batch_index:batch,local_initial_id:local,global_initial_id:global,truth,primary:parts.find(r=>r.group_id===null),pulse_groups:parts.filter(r=>r.group_id!==null)}]};
    run(`showRun(${JSON.stringify(job)});result={job:${JSON.stringify(job)},page:pageIdentity(${JSON.stringify(page)},${JSON.stringify(job)},${batch},${local}),records:flatBatchRecords(${JSON.stringify(page)}),traces:[]};$('event').value='${global}';showEvent(${groupIndex});batchArtifacts(result.job,result.page);`);
    assert.match(get('analysis-selection').textContent,new RegExp('batch '+batch+'.*global initial ID '+global+'.*local initial ID '+local));
    assert.match(get('analysis-filter').textContent,new RegExp('evtid = '+local+'.*global_initial_id = '+global));
    assert.equal(get('result-data').children[0].children[0].children[0].textContent,global===188?'297.89953951910127':'0');
    if(global===188){assert.equal(get('result-data').children[0].children[1].children[0].textContent,'295.65372418710035');assert.match(get('analysis-filter').textContent,/group_id = 0/);}
    else{assert.match(get('analysis-filter').textContent,/group_id is null/);assert.match(get('analysis-state').textContent,/Zero deposition/);assert.equal(get('result-data').children[0].children[2].children[0].textContent,'Unavailable');}
    const nodes=get('saved-artifacts').children.flatMap(n=>n.children||[]),buttons=nodes.filter(n=>n.tagName==='button');assert.equal(buttons.length,stamps.length+3);
    const header=file=>fs.readFileSync(path.join(savedRoot,base,'response',file),'utf8').split(/\r?\n/,1)[0].split(',');
    const signalColumns=header('signals.csv');assert.ok(signalColumns.includes('global_initial_id'));assert.ok(signalColumns.includes('induced_equivalent_energy_keV'));assert.ok(!signalColumns.includes('current_nA'));
    for(const file of ['scalars.csv','endpoints.csv']){const columns=header(file);assert.ok(!columns.includes('global_initial_id'));assert.ok(columns.includes('record_json'));}
    assert.match(get('analysis-filter').textContent,/decode record_json to read global_initial_id/);
    const descriptions=nodes.filter(n=>n.tagName==='p').map(n=>n.textContent).join(' ');assert.doesNotMatch(descriptions,/signals\.csv[^.]*current/);assert.match(descriptions,/traces\.jsonl[^.]*current/);
    for(const stamp of stamps){assert.equal(buttons.filter(n=>n.textContent==='Download '+stamp.file).length,1);assert.ok(nodes.some(n=>n.textContent===stamp.bytes+' bytes · SHA256 '+stamp.sha256));}
    assert.equal(JSON.parse(get('event-record').textContent)[0].raw_truth.global_initial_id,global);
  }
  console.log('Retained AK01/Cs137500 zero0, positive188/group0 and batch1 global250/local0 saved-analysis contracts passed.');
}
run("showRun(savedJob);");
assert.equal(get('analysis-selection').textContent,'No saved primary selected.');

// A delayed old Check reply cannot enable Start for a changed current selection.
(async()=>{
  // Every Download requests exact bytes; viewing keeps the default route.
  run("let artifactRequests=[];fetch=async(url,options)=>{artifactRequests.push({url,options});return {ok:true,blob:async()=>({})};};");
  await run("download('fixture','response/summary.html')");
  await run("artifact('fixture','response/summary.html')");
  assert.match(run('artifactRequests[0].url'),/download=1/);
  assert.doesNotMatch(run('artifactRequests[1].url'),/download=/);
  assert.equal(run("artifactRequests[0].options.headers['X-Control-Token']"),'fixture');
  run("let resolveCheck;api=()=>new Promise(resolve=>resolveCheck=resolve);");
  const pending=run("$('check').onclick()");
  get('detector').value='SAP22';run("invalidate();resolveCheck({check_id:'old',resolved:{selection:{detector:'AK02'}}});");
  await pending;assert.equal(run('checked'),null);assert.equal(get('start').disabled,true);
  for(const [id,value]of [['name','changed-name'],['setting-gain','4'],['source','am241_point_decay_v1']]){
    const old=run("$('check').onclick()");get(id).value=value;
    run(id==='source'?"sourceChanged();":"invalidate();");
    run("resolveCheck({check_id:'stale',resolved:{selection:{detector:'AK02'}}});");await old;
    assert.equal(run('checked'),null);assert.equal(get('start').disabled,true);
  }
  const current=run("$('check').onclick()");run("resolveCheck({kind:'local_scenario_batch_execution_v3',schema_version:3,execution_enabled:true,check_id:'new',resolved:{selection:{detector:'SAP22'},batching:{batch_count:1}}});");await current;
  assert.equal(run('checked.check_id'),'new');assert.equal(get('start').disabled,false);
  let requestedRoute;
  run("let catalogChecks=[];api=(path,body)=>{catalogChecks.push({path,body});return new Promise(resolve=>resolveCheck=resolve);};");
  get('detector').value='AK01';run('detectorChanged();');
  const catalogPending=run("$('check').onclick()");
  assert.equal(run('catalogChecks[0].path'),'/api/workflow/check-batches');assert.equal(run('catalogChecks[0].body.request.schema_version'),2);assert.equal(run('catalogChecks[0].body.request.selection.detector'),'AK01');
  run("resolveCheck({kind:'local_scenario_batch_execution_v3',schema_version:3,execution_enabled:true,check_id:'shared-new',resolved:{selection:{detector:'AK01'},batching:{batch_count:1}}});");
  await catalogPending;assert.equal(run('checked.check_id'),'shared-new');
  get('detector').value='large-model';run('detectorChanged();');
  assert.equal(run('checked'),null);assert.equal(get('start').disabled,true);
  get('detector').value='SAP22';run('detectorChanged();');
  run("api=()=>new Promise(resolve=>resolveCheck=resolve);");
  // View-only selection while Check is pending refuses even an otherwise valid reply.
  run("catalog.detectors.push({id:'view-only',available:false,sources:[],reason:'Pending connector'});");
  const pendingView=run("$('check').onclick()");get('detector').value='view-only';run('detectorChanged();resolveCheck({check_id:"stale-view",resolved:{}});');
  await pendingView;assert.equal(run('checked'),null);assert.equal(get('check').disabled,true);assert.equal(get('start').disabled,true);
  run("let actionCalls=0;api=async()=>{actionCalls++;return {};};");
  await run("$('check').onclick()");await run("$('start').onclick()");run("$('save').onclick()");
  assert.equal(run('actionCalls'),0);
  get('detector').value='SAP22';run('detectorChanged();');assert.equal(get('check').disabled,false);
  // Slow imports never overwrite an edited setup or launch during active work.
  run("let resolveImport;const importText=JSON.stringify(config());$('import').files=[{size:100,text:()=>new Promise(resolve=>resolveImport=resolve)}];");
  const oldImport=run("$('import').onchange()");get('name').value='name-edited';run('invalidate();resolveImport(importText);');await oldImport;
  assert.equal(get('name').value,'name-edited');assert.match(get('notice').textContent,/changed while loading/);
  const activeImport=run("$('import').onchange()");run('active=true;resolveImport(importText);');await activeImport;
  assert.equal(get('name').value,'name-edited');assert.equal(run('checked'),null);run('active=false;controls();');
  // Preview replies are fenced by model identity; unavailable saved bytes stay explicit.
  run("let previewReplies=[];fetch=()=>new Promise(resolve=>previewReplies.push(resolve));");
  const oldPreview=run("loadModelPreview(catalog.detectors[0])");
  get('detector').value='GeRC02';run('detectorChanged();');
  run("previewReplies[1]({ok:true,blob:async()=>({})});");
  await Promise.resolve();await Promise.resolve();assert.equal(get('model-preview').alt,'GeRC02 saved catalog geometry');
  assert.match(get('model-variant').textContent,/frozen catalog Ge30min base.*Li50min/);
  run("previewReplies[0]({ok:true,blob:async()=>({})});");await oldPreview;
  assert.equal(get('model-preview').alt,'GeRC02 saved catalog geometry');
  const failedPreview=run("loadModelPreview(currentDetector())");run("previewReplies[2]({ok:false});");await failedPreview;
  assert.equal(get('model-preview-box').hidden,true);assert.match(get('model-preview-status').textContent,/public website/);
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
  run("let plotReplies=[];api=path=>new Promise(resolve=>plotReplies.push({path,resolve}));result={job:newerJob,summaryHash:'c'.repeat(64),records:[{initial_primary_id:2,event_id:2,zero_ge:false,readout:{trace:{},peak_time_ns:1000,peak_V:1}},{initial_primary_id:0,event_id:0,zero_ge:true,readout:{trace:{},peak_time_ns:1000,peak_V:1}}],traces:[]};$('event').value='2';showEvent();");
  get('event').value='0';run('showEvent();');get('event').value='2';run('showEvent();');
  assert.match(run('plotReplies[1].path'),/primary=0&group=none/);assert.match(run('plotReplies[2].path'),/primary=2&group=0/);
  run("const plotReply=(id,group)=>({kind:'saved_focus_projection_v1',name:newerJob.name,configuration_sha256:newerJob.configuration_sha256,primary_id:id,group_id:group,summary_sha256:'c'.repeat(64),sidecar_manifest_sha256:null,sidecar_data_sha256:null,panels:['Charge','Current','Preamp','Shaper'].map(title=>({title,time_ns:[0,2,1000],values:[0,-0,-1],full_end_ns:1000,focus_end_ns:12,peak:{t:1000,v:1},note:'Original saved points'})),notes:['Bounded display samples; current belongs to original intervals.']});plotReplies[2].resolve(plotReply(2,0));");
  await Promise.resolve();await Promise.resolve();assert.equal(get('plots').children.filter(n=>n.tagName==='figure').length,4);
  run('plotReplies[1].resolve(plotReply(0,null));plotReplies[0].resolve(plotReply(2,0));');
  await Promise.resolve();await Promise.resolve();assert.equal(get('plots').children.filter(n=>n.tagName==='figure').length,4);
  assert.match(get('event-identity').textContent,/Initial primary 2/);
  get('event').value='0';run('showEvent();plotReplies[3].resolve(plotReply(0,null));');
  await Promise.resolve();await Promise.resolve();assert.equal(get('plots').children.filter(n=>n.tagName==='figure').length,4);assert.match(get('event-identity').textContent,/known zero input/);
  run("showGroup();plotReplies[4].resolve(plotReply(0,0));");await Promise.resolve();await Promise.resolve();assert.match(get('plots').children[0].textContent,/identities differ/);
  run("showGroup();showRun(savedJob);plotReplies[5].resolve(plotReply(0,null));");await Promise.resolve();await Promise.resolve();assert.equal(get('plots').children.length,0);
  // Slow saved pages cannot replace a newer batch or reopen another selected run.
  run("let pageReplies=[];api=path=>new Promise(resolve=>pageReplies.push({path,resolve}));");
  const openingBatch=run('openBatchResult(batchJob)');
  assert.match(get('analysis-selection').textContent,/batch-saved · no primary selected/);assert.equal(get('group').children.length,0);assert.equal(get('saved-artifacts').children.length,0);
  get('batch-index').value='1';get('page-offset').value='0';const newerPage=run('loadBatchPage()');
  run('pageReplies[1].resolve(batchFixture(1,0));');await newerPage;
  assert.equal(get('event').value,'10000');assert.match(get('page-status').textContent,/Batch 1/);
  assert.match(get('analysis-selection').textContent,/batch 1.*global initial ID 10000.*local initial ID 0/);
  run('pageReplies[0].resolve(batchFixture(0,0));');await openingBatch;
  assert.equal(get('event').value,'10000');assert.equal(run('result.page.batch_index'),1);
  assert.match(get('analysis-filter').textContent,/evtid = 0 in batch 1/);assert.doesNotMatch(get('analysis-filter').textContent,/in batch 0/);
  const stalePage=run('loadBatchPage()');run('showRun(savedJob);pageReplies[2].resolve(batchFixture(1,0));');await stalePage;
  assert.equal(run('result'),null);assert.match(get('selected').textContent,/saved-sap-gamma/);
  assert.equal(get('analysis-selection').textContent,'No saved primary selected.');assert.equal(get('saved-artifacts').children.length,0);
  // Four saved panels use exact selected charge and analog samples only.
  run(`const successfulPage=batchFixture(2,0);successfulPage.records[0].pulse_groups[0].readout={readout_end_ns:1000,peak_time_ns:1000,peak_V:1};successfulPage.traces=[{global_initial_id:20000,group_id:0}];showRun(batchJob);result={job:batchJob,page:successfulPage,records:flatBatchRecords(successfulPage),traces:successfulPage.traces,summaryHash:'f'.repeat(64)};$('event').value='20000';showEvent(1);`);
  assert.match(run('pageReplies[3].path'),/batch=2&primary=20000&group=0/);
  run(`pageReplies[3].resolve({kind:'local_batch_waveform_v1',name:batchJob.name,configuration_sha256:batchJob.configuration_sha256,batch_index:2,batch_sha256:'e'.repeat(64),response_summary_sha256:'f'.repeat(64),charge_input:{time_since_origin_ns:[0,2,1000],induced_equivalent_energy_keV:[0,-.001,-.003]},record:{global_initial_id:20000,group_id:0,origin_time_ns:500000,trace:{time_ns:[0,2,1000],current_nA:[0,-.2,-.1],current_bin_start_ns:[0,0,998],current_bin_end_ns:[0,2,1000],preamp_V:[0,-.5,-1],shaped_V:[0,.5,1]}}});`);
  await Promise.resolve();await Promise.resolve();assert.equal(get('plots').children.filter(n=>n.tagName==='figure').length,4);
  assert.match(get('event-identity').textContent,/Initial primary 20000/);
  // Poll responses arriving out of order never restore obsolete job status.
  run("let pollReplies=[];api=path=>new Promise(resolve=>pollReplies.push({path,resolve}));");
  const oldPoll=run('poll()'),newPoll=run('poll()');
  run("pollReplies[2].resolve({busy:false,jobs:[]});pollReplies[3].resolve({jobs:[]});");await newPoll;
  run("pollReplies[0].resolve({busy:true,jobs:[]});pollReplies[1].resolve({jobs:[]});");await oldPoll;
  assert.equal(run('active'),false);
  console.log('Browser exact count/Gamma, batch Stop/Resume selection, paged boundary IDs/null/signs, stale Check/report/page/poll/focus, four saved plots and recovery contracts passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
