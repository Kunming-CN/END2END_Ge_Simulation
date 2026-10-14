// Browser contract checks with a small DOM substitute; no scientific workers.
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class Element {
  constructor(tag='div'){this.tagName=tag;this.children=[];this.parentElement=null;this.rootConnected=false;this.value='';this.checked=false;this.disabled=false;this._textContent='';this.textWrites=0;this.dataset={};this.style={};this.open=false;this.selectionStart=null;this.selectionEnd=null;this.selectionDirection=null;this.focusLosses=0;this.moves=0;}
  get isConnected(){return this.rootConnected||this.parentElement?.isConnected===true;}
  get textContent(){return this._textContent;}
  set textContent(text){this.textWrites++;for(const n of [...this.children])this.removeChild(n);this._textContent=text;}
  contains(n){return n===this||this.children.some(child=>child.contains?.(n));}
  insertBefore(n,before){if(n.parentElement){n.moves++;n.parentElement.removeChild(n);}const index=before===null?this.children.length:this.children.indexOf(before);assert.ok(index>=0);this.children.splice(index,0,n);n.parentElement=this;return n;}
  removeChild(n){const index=this.children.indexOf(n);assert.ok(index>=0);if(this.isConnected&&n.contains?.(fixtureDocument.activeElement)){fixtureDocument.activeElement.focusLosses++;fixtureDocument.activeElement=fixtureDocument.body;}this.children.splice(index,1);n.parentElement=null;return n;}
  append(...nodes){for(const n of nodes)this.insertBefore(n,null);if(this.tagName==='select'&&this.children.length&&this.value==='')this.value=this.children[0].value;}
  replaceChildren(...nodes){for(const n of [...this.children])this.removeChild(n);this._textContent='';this.value='';this.append(...nodes);}
  addEventListener(name,fn){this['on'+name]=fn;}
  scrollIntoView(){}
  focus(){if(this.isConnected&&!this.disabled)fixtureDocument.activeElement=this;}
  setSelectionRange(start,end,direction='none'){this.selectionStart=start;this.selectionEnd=end;this.selectionDirection=direction;}
  click(){if(this.disabled)return;this.clicked=true;return this.onclick?.();}
  pressKey(key){if(fixtureDocument.activeElement!==this)return;if(this.tagName==='button'&&['Enter',' '].includes(key))return this.click();if(this.tagName==='summary'&&['Enter',' '].includes(key))this.parentElement.open=!this.parentElement.open;}
  setAttribute(name,value){this[name]=value;}
  removeAttribute(name){delete this[name];}
}
const svgNs='http://www.w3.org/2000/svg';
function xml(tag,attrs={},children=[]){return {nodeType:1,localName:tag,prefix:null,namespaceURI:null,attributes:Object.entries(attrs).map(([name,value])=>({name,value,prefix:null})),childNodes:children};}
const svgDocument={doctype:null,documentElement:xml('svg',{role:'img',viewBox:'0 0 600 205'},[xml('polyline',{points:'55,160 565,35',fill:'none',stroke:'currentColor','stroke-width':'1.7'}),xml('text',{x:'5',y:'35'},[{nodeType:3,nodeValue:'-0.003'}])]),getElementsByTagName:()=>[]};
class Parser{parseFromString(){return svgDocument;}}
const elements=new Map(),get=id=>{if(!elements.has(id)){const find=n=>n.id===id?n:n.children?.map(find).find(Boolean);for(const root of elements.values()){const found=find(root);if(found)return found;}const root=new Element(['cryostat','detector','source','pose','threads','event','group'].includes(id)?'select':'div');root.rootConnected=true;elements.set(id,root);}return elements.get(id);};
const fixtureDocument={getElementById:get,createElement:tag=>new Element(tag),createElementNS:(ns,tag)=>{const n=new Element(tag);n.namespaceURI=ns;return n;},createTextNode:text=>({textContent:text})};
fixtureDocument.body=new Element('body');fixtureDocument.body.rootConnected=true;fixtureDocument.activeElement=fixtureDocument.body;
const context=vm.createContext({document:fixtureDocument,DOMParser:Parser,
  location:{hash:'#fixture',pathname:'/'},sessionStorage:{getItem:()=>'',setItem:()=>{}},history:{replaceState:()=>{}},
  URL:{createObjectURL:()=> 'blob:fixture',revokeObjectURL:()=>{}},URLSearchParams,TextDecoder,Uint8Array,fetch:()=>new Promise(()=>{}),setInterval:()=>{},setTimeout:()=>{}});
vm.runInContext(fs.readFileSync(__dirname+'/focused_plots.js','utf8'),context);
vm.runInContext(fs.readFileSync(__dirname+'/local_workflow.js','utf8'),context);
function run(code){return vm.runInContext(code,context);}
run(`catalog={electronics_keys:Object.keys(labels),electronics_defaults:{},sources:[{id:'mono_gamma_662_axis_v1',label:'Gamma',pose:'plus5mm',pose_label:'+5 mm along global y',counts:[20],fixed_seed:26092631,details:'One 662 keV gamma per primary; fixed global −y beam, time zero.',count_unit:'initial gamma primaries'},{id:'cs137_point_decay_v1',label:'Cs137',pose:'nominal',pose_label:'Nominal source anchor',counts:[20,500],details:'One initial Cs137 decay per primary; isolated pulse windows retain daughter timing.',count_unit:'initial Cs137 decays',fixed_seed:null}],cryostats:[{id:'lbnl_modular_nominal_v1',available:true}],detectors:[{id:'AK02',available:true,sources:['mono_gamma_662_axis_v1','cs137_point_decay_v1']},{id:'SAP22',available:true,sources:['mono_gamma_662_axis_v1','cs137_point_decay_v1']},{id:'GeRC02',available:true,sources:['cs137_point_decay_v1'],operating_label:'Li50min +240 V'},{id:'KMRC01_candidate',available:true,sources:['cs137_point_decay_v1'],operating_label:'−370 V; fixed −1 wiring'}]};`);
run(`catalog.sources.find(s=>s.id==='cs137_point_decay_v1').source_angle={enabled:true,min_deg:-30,max_deg:30,version:'source_capsule_angular_pose_v1',convention:'Degrees from global +y toward +x around global z at x=0,y=1.473 mm; engineering placement'};
const sourcePose30={kind:'source_capsule_angular_pose_v1',schema_version:1,angle_deg:30,position_global_mm:[17.8,32.303504374726016,.290],capsule_rotation_local_to_global:[[.8660254037844387,0,.5],[-.5,0,.8660254037844387],[0,-1,0]],capsule_axis_global:[.5,.8660254037844387,0],coordinate_convention:'Degrees from global +y toward +x around global z at x=0,y=1.473 mm; engineering placement',anchors_sha256:'8'.repeat(64)};`);
get('source').value='cs137_point_decay_v1';run('angleFields()');
assert.match(get('angle-limit').textContent,/Nonzero-angle Run is unavailable/);
run("catalog.sources.find(s=>s.id==='cs137_point_decay_v1').source_angle.nonzero_execution_ready=true;angleFields()");
assert.match(get('angle-limit').textContent,/Supported source angle:.*Run uses the checked pose/);
assert.doesNotMatch(get('angle-limit').textContent,/Run is unavailable/);
run("catalog.sources.find(s=>s.id==='cs137_point_decay_v1').source_angle.nonzero_execution_ready=false");
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
// Primary hints describe loaded records without filtering, sorting, inventing
// zeros, or equating a scalar group count/readout acceptance with a waveform.
run(`const hintRows=[
 {record_kind:'decay',event_id:12,pulse_count:0,zero_deposit:true,deposited_energy_keV:0},
 {record_kind:'decay',event_id:5,pulse_count:1,deposited_energy_keV:4},
 {record_kind:'pulse',event_id:5,group_id:0,deposited_energy_keV:4,final_induced_keV:-3.9,readout:{accepted:true,reconstructed_energy_keV:4}},
 {record_kind:'pulse',event_id:7,group_id:0,deposited_energy_keV:4,status:'native_transport_failed',native_error:{exact_error:'retained'},final_induced_keV:null,accepted:false,readout:null},
 {initial_primary_id:2,event_id:91,zero_ge:true,truth_ge_edep_keV:0,readout:{accepted:false,rejection_reason:'below_threshold',trace:{}}},
 {initial_primary_id:9,event_id:92,zero_ge:false,truth_ge_edep_keV:4,status:'native_completed',readout:{accepted:false,rejection_reason:'below_threshold'}},
 {record_kind:'pulse',event_id:20,group_id:0,deposited_energy_keV:4,readout:{accepted:false,rejection_reason:'saturated',saturated:true}},
 {record_kind:'decay',event_id:14,pulse_count:2,deposited_energy_keV:4},
 {record_kind:'pulse',event_id:14,group_id:0,deposited_energy_keV:2,readout:{accepted:true}},
 {record_kind:'pulse',event_id:14,group_id:1,deposited_energy_keV:2,readout:{accepted:false,rejection_reason:'negative_input'}},
 {event_id:31,truth_ge_edep_keV:null,trace_saved:true,final_induced_keV:null,readout:null},
 {record_kind:'decay',event_id:32,pulse_count:3,deposited_energy_keV:4},
 {record_kind:'decay',event_id:33,pulse_count:0,deposited_energy_keV:0},
 {record_kind:'pulse',event_id:34,group_id:0,deposited_energy_keV:4,readout:{reconstructed_energy_keV:null}},
 {record_kind:'pulse',event_id:35,group_id:0,deposited_energy_keV:2,status:'native_failed',readout:null},
 {record_kind:'pulse',event_id:35,group_id:1,deposited_energy_keV:2,readout:{accepted:true}},
 {record_kind:'pulse',event_id:36,group_id:0,deposited_energy_keV:2,readout:{accepted:true}},
 {record_kind:'pulse',event_id:36,group_id:1,deposited_energy_keV:2,readout:{accepted:false,saturated:true}},
 {record_kind:'pulse',event_id:37,group_id:0,deposited_energy_keV:2,readout:{accepted:true}},
 {record_kind:'pulse',event_id:37,group_id:1,deposited_energy_keV:2,readout:null},
 {event_id:38,truth_ge_edep_keV:4,readout:{accepted:true,trace:{}},trace_saved:true},
 {record_kind:'pulse',event_id:39,group_id:0,deposited_energy_keV:4,readout:null}
];const hintTraces=[{event_id:5,group_id:0},{initial_primary_id:32,group_id:0}];
const hintBefore=JSON.stringify([hintRows,hintTraces]);const hintIds=[...new Set(hintRows.map(recordPrimary))];
const hintOptions=primaryOptions(hintIds,hintRows,hintTraces);options('event',hintOptions);`);
assert.deepEqual(get('event').children.map(o=>o.value),['12','5','7','2','9','20','14','31','32','33','34','35','36','37','38','39']);
assert.equal(get('event').children.length,run('hintIds.length'));
assert.ok(get('event').children.every(o=>o.disabled===false));
const hintLabels=new Map(get('event').children.map(o=>[o.value,o.textContent]));
for(const [id,label]of Object.entries({12:'zero deposition',5:'1 group · readout accepted · waveform saved',7:'1 group · native failure',2:'known zero input · readout rejected',9:'1 group · readout rejected',20:'1 group · readout saturated',14:'2 groups · mixed readout',31:'pulse status unknown · readout unavailable',32:'3 reported groups',33:'0 reported groups',34:'1 group · readout status unknown',35:'2 groups · mixed; native failure',36:'2 groups · mixed readout; saturation',37:'2 groups · readout partly unavailable',38:'pulse status unknown · readout accepted',39:'1 group · readout unavailable'}))assert.equal(hintLabels.get(id),id+' · '+label);
assert.equal(run('JSON.stringify([hintRows,hintTraces])'),run('hintBefore'));
assert.deepEqual(JSON.parse(run('JSON.stringify(firstSavedWaveform(hintRows,hintTraces))')),{id:5,groupIndex:1});
assert.equal(run('primaryHint(primaryRecords(hintRows,5),[])'),'1 group · readout accepted');
assert.equal(run("primaryHint([{initial_primary_id:40,zero_ge:false,truth_ge_edep_keV:4,status:'native_failed',readout:null}],[])"),'1 group · native failure');
assert.doesNotMatch(hintLabels.get('31')+hintLabels.get('32')+hintLabels.get('33')+hintLabels.get('38'),/waveform saved|zero deposition|known zero input/);
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
assert.match(html,/<h2>Next-run setup<\/h2>/);
assert.match(html,/Editing them clears its checked plan; the selected saved run and its events keep their recorded settings/);
assert.match(html,/<h2>Selected saved run · pipeline<\/h2>/);
assert.match(html,/Selected saved-run settings · exact recorded inputs/);
assert.match(html,/id="start"[^>]+aria-describedby="run-readiness"/);
assert.match(html,/id="run-readiness"[^>]+role="status"[^>]+aria-live="polite"/);
assert.match(html,/<details id="legacy-recovery">/);
for(const id of ['cryostat','detector','source','pose','angle-deg','count','threads','seed','name','use-peak-gate','event','group'])assert.match(html,new RegExp('<label for="'+id+'"'));
assert.match(html,/id="angle-deg" type="number" min="-30" max="30" step="any" value="0"/);
for(const [id,value]of Object.entries({name:'fixture',cryostat:'lbnl_modular_nominal_v1',detector:'AK02',source:'mono_gamma_662_axis_v1',pose:'plus5mm','angle-deg':'0',count:'20',seed:'26092631',threads:'2'}))get(id).value=value;
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
// Zero-angle export retains the exact legacy selection shape; only admitted
// decay sources can import or submit a bounded nonzero angle.
assert.equal(run("Object.hasOwn(config(),'angle_deg')"),false);
assert.equal(run("Object.hasOwn(importedConfig({...config(),angle_deg:0}),'angle_deg')"),false);
for(const bad of [true,'30',null,30,-30])assert.throws(()=>run(`importedConfig({...config(),angle_deg:${JSON.stringify(bad)}})`),/angle/);
get('source').value='cs137_point_decay_v1';run('sourceChanged();');
assert.equal(get('angle-deg').disabled,false);assert.match(get('angle-limit').textContent,/-30° to 30°.*engineering placement/);
assert.equal(get('angle-deg').value,'0');assert.equal(run("Object.hasOwn(config(),'angle_deg')"),false);
for(const angle of [30,-30]){get('angle-deg').value=String(angle);run('invalidate();');assert.equal(run('config().angle_deg'),angle);assert.equal(run('importedRequest(batchRequest(config())).angle_deg'),angle);assert.equal(get('start').disabled,true);}
for(const bad of [true,'30',null,30.0001,-30.0001])assert.throws(()=>run(`importedRequest(batchRequest({...config(),angle_deg:${JSON.stringify(bad)}}))`),/angle/);
for(const bad of ['NaN','Infinity','-Infinity'])assert.throws(()=>run(`importedRequest(batchRequest({...config(),angle_deg:${bad}}))`),/angle/);
for(const bad of ['', 'NaN','31','-31']){get('angle-deg').value=bad;assert.throws(()=>run('config()'),/angle/);}
get('angle-deg').value='30';run('invalidate();');assert.match(get('source-pose-preview').textContent,/Check plan to resolve/);
run('showPose({selection:config(),source_pose:sourcePose30,source_position_global_mm:sourcePose30.position_global_mm});');
assert.match(get('source-pose-preview').textContent,/Checked effective source pose · angle 30°.*capsule axis/);
assert.ok(get('source-pose-preview').textContent.includes(run('sourcePose30.position_global_mm.join(", ")')));
assert.deepEqual(JSON.parse(get('source-pose-identity').textContent).source_pose,JSON.parse(run('JSON.stringify(sourcePose30)')));
assert.equal(JSON.parse(get('source-pose-identity').textContent).source_pose.anchors_sha256,'8'.repeat(64));
get('angle-deg').value='-30';run('invalidate();');assert.match(get('source-pose-preview').textContent,/Check plan to resolve/);assert.equal(get('source-pose-identity').textContent,'No checked source pose.');
get('source').value='mono_gamma_662_axis_v1';run('sourceChanged();');assert.equal(get('angle-deg').value,'0');assert.equal(get('angle-deg').disabled,true);assert.equal(run("Object.hasOwn(config(),'angle_deg')"),false);
assert.equal(get('count').value,'20');assert.equal(get('seed').value,'26092631');
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
run("const launchFailure={id:'not-created',name:'not-created',status:'dispatch_uncertain',execution_contract:'serial_batches_v3',can_inspect_failure:false,can_recover_launch:true,error:'Original preparation error',selection:{detector:'AK02',source:'cs137_point_decay_v1',primary_count:500},stages:{}};renderJobs({busy:true,jobs:[launchFailure]});");
assert.ok(get('runs').children[0].children.some(n=>n.textContent==='Recover not-launched failure'));
assert.ok(!get('runs').children[0].children.some(n=>n.textContent==='Verify existing completion'||n.textContent==='Inspect denied launch'));
assert.ok(get('runs').children[0].children.some(n=>/process creation was never invoked/.test(n.textContent)));
assert.ok(get('runs').children[0].children.some(n=>n.textContent==='Original preparation error'));
run("renderJobs({busy:true,jobs:[{...launchFailure,can_recover_launch:false}]});");
assert.ok(!get('runs').children[0].children.some(n=>n.textContent==='Recover not-launched failure'));
assert.ok(get('runs').children[0].children.some(n=>n.textContent==='Verify existing completion'));
run("renderJobs({busy:false,jobs:[{...launchFailure,status:'launch_failed',can_recover_launch:false}]});");
assert.ok(get('runs').children[0].children.some(n=>/No calculation started.*new run name/.test(n.textContent)));
assert.ok(!get('runs').children[0].children.some(n=>n.textContent==='Resume saved settings'||n.textContent==='Recover not-launched failure'));
assert.match(fs.readFileSync(__dirname+'/local_workflow.js','utf8'),/api\('\/api\/workflow\/recover-launch',\{name:job.name\}\)/);
run("renderJobs({busy:true,jobs:[{...launchFailure,status:'stopped',can_recover_launch:false,can_verify_saved_execution:true}]});");
assert.ok(get('runs').children[0].children.some(n=>n.textContent==='Verify saved execution'));
assert.ok(get('runs').children[0].children.some(n=>/CLI Resume.*new sealed boundary/.test(n.textContent)));
assert.ok(get('runs').children[0].children.some(n=>n.textContent==='Resume saved settings'));
run("renderJobs({busy:false,jobs:[{...launchFailure,status:'launch_failed',can_recover_launch:false,can_verify_saved_execution:false}]});");
assert.ok(!get('runs').children[0].children.some(n=>n.textContent==='Verify saved execution'));
run('renderJobs({busy:false,jobs:[]});');
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
// STRICT-03: surviving controls retain actual node identity, keyboard focus,
// typed continuation text/caret and opened details through unchanged polls and
// meaningful updates. This substitute models removal/reinsertion focus loss;
// actual browser keyboard/timer acceptance is recorded separately.
run(`const focusJob={id:'focus-a',name:'focus-a',configuration_sha256:'9'.repeat(64),status:'stopped',can_continue_prefix:true,can_verify_saved_execution:true,selection:{detector:'AK02',source:'cs137_point_decay_v1',primary_count:500},stages:{geometry:{status:'completed',elapsed_seconds:1}}};
const otherFocusJob={...focusJob,id:'focus-b',name:'focus-b',configuration_sha256:'8'.repeat(64),can_continue_prefix:false};
const focusState={busy:false,jobs:[otherFocusJob,focusJob]};renderJobs(focusState);`);
const findButton=(card,label)=>card.children.find(n=>n.tagName==='button'&&n.textContent===label);
const focusedCard=get('runs').children[0],stagesButton=findButton(focusedCard,'Show stages');
stagesButton.focus();const unchangedMoves=stagesButton.moves;
for(let i=0;i<2;i++){
  run('renderJobs(JSON.parse(JSON.stringify(focusState)));');
  assert.equal(get('runs').children[0],focusedCard);assert.equal(findButton(focusedCard,'Show stages'),stagesButton);
  assert.equal(fixtureDocument.activeElement,stagesButton);assert.equal(stagesButton.moves,unchangedMoves);assert.equal(stagesButton.focusLosses,0);
}
const stageDetails=focusedCard.children.find(n=>n.tagName==='details'),stageSummary=stageDetails.children[0];
stageSummary.focus();stageSummary.pressKey(' ');assert.equal(stageDetails.open,true);
run('renderJobs({...focusState,jobs:[otherFocusJob,{...focusJob,error:"new diagnostic",stages:{geometry:{status:"completed",elapsed_seconds:2}}}]});');
assert.equal(fixtureDocument.activeElement,stageSummary);assert.equal(stageDetails.open,true);
assert.equal(stageDetails.children[0],stageSummary);assert.match(stageDetails.children.at(-1).textContent,/"elapsed_seconds": 2/);
const continuationInput=focusedCard.children.find(n=>n.tagName==='label').children[0];
continuationInput.value='typed-new-run';continuationInput.oninput();continuationInput.focus();continuationInput.setSelectionRange(2,8,'backward');
run('renderJobs({...focusState,busy:true,jobs:[otherFocusJob,{...focusJob,status:"dispatch_uncertain",can_recover_launch:true,error:"preparation failure"}]});');
assert.equal(fixtureDocument.activeElement,continuationInput);assert.equal(continuationInput.value,'typed-new-run');
assert.deepEqual([continuationInput.selectionStart,continuationInput.selectionEnd,continuationInput.selectionDirection],[2,8,'backward']);
assert.equal(get('continue-name-focus-a'),continuationInput);assert.equal(get('start').disabled,true);assert.equal(get('check').disabled,true);
assert.ok(findButton(focusedCard,'Recover not-launched failure'));assert.equal(findButton(focusedCard,'Resume saved settings'),undefined);
// A list reorder must restore the same surviving input if moving its card
// detaches focus. Removing an unavailable action must not focus another action.
run('renderJobs({...focusState,jobs:[focusJob,otherFocusJob]});renderJobs(focusState);');
assert.equal(get('runs').children[0],focusedCard);assert.equal(fixtureDocument.activeElement,continuationInput);
assert.deepEqual([continuationInput.selectionStart,continuationInput.selectionEnd,continuationInput.selectionDirection],[2,8,'backward']);
const removedResume=findButton(focusedCard,'Resume saved settings');removedResume.focus();
run('renderJobs({...focusState,busy:true,jobs:[otherFocusJob,{...focusJob,status:"running"}]});');
assert.equal(removedResume.isConnected,false);assert.equal(fixtureDocument.activeElement,fixtureDocument.body);
assert.ok(findButton(focusedCard,'Stop after current stage'));assert.equal(findButton(focusedCard,'Resume saved settings'),undefined);
// Polled status/receipt changes never switch the selected saved primary/group
// or manufacture values for a signed response with unavailable readout.
run(`showRun(focusJob);result={job:focusJob,records:[{record_kind:'decay',event_id:7,deposited_energy_keV:4,pulse_count:1},{record_kind:'pulse',event_id:7,group_id:3,origin_time_ns:5000,deposited_energy_keV:4,final_induced_keV:-4,readout:null}],traces:[]};$('event').value='7';showEvent(1);`);
const selectedFocusResult=run('result'),focusRecord=get('event-record').textContent;
get('event').focus();
run('renderJobs({...focusState,jobs:[otherFocusJob,{...focusJob,stages:{geometry:{status:"completed",elapsed_seconds:3}}}]});renderLegacy({gamma:{jobs:[]}});');
assert.equal(run('selectedJob'),'focus-a');assert.equal(run('result'),selectedFocusResult);
assert.equal(get('event').value,'7');assert.equal(get('group').value,'1');assert.equal(get('event-record').textContent,focusRecord);
assert.equal(fixtureDocument.activeElement,get('event'));assert.equal(get('result-data').children[0].children[1].children[0].textContent,'-4');
assert.equal(get('result-data').children[0].children[2].children[0].textContent,'Unavailable');
run("const legacyFocusState={gamma:{jobs:[{id:'legacy-focus',label:'legacy-focus',status:'verification-required',blocks_new_work:true,can_verify:true}]}};renderLegacy(legacyFocusState);");
const legacyCard=get('legacy-runs').children[0],legacyVerify=findButton(legacyCard,'Verify saved completion');legacyVerify.focus();
for(let i=0;i<2;i++){run('renderLegacy(JSON.parse(JSON.stringify(legacyFocusState)));');assert.equal(get('legacy-runs').children[0],legacyCard);assert.equal(findButton(legacyCard,'Verify saved completion'),legacyVerify);assert.equal(fixtureDocument.activeElement,legacyVerify);assert.equal(legacyVerify.moves,0);}
run('renderLegacy({gamma:{jobs:[{...legacyFocusState.gamma.jobs[0],label:"updated display label",error:{message:"new saved diagnostic"}}]}});');
assert.equal(fixtureDocument.activeElement,legacyVerify);assert.equal(findButton(legacyCard,'Verify saved completion'),legacyVerify);
assert.equal(legacyCard.children[0].textContent,'Saved gamma · updated display label');
run('renderLegacy({gamma:{jobs:[{...legacyFocusState.gamma.jobs[0],can_verify:false}]}});');
assert.equal(legacyVerify.isConnected,false);assert.equal(fixtureDocument.activeElement,fixtureDocument.body);
run('renderLegacy({gamma:{jobs:[]}});renderJobs({busy:false,jobs:[]});');
console.log('STRICT-03 unchanged renders, meaningful updates, reorder, focus/caret, details, current permission and saved primary/group contracts passed.');
// Editing the next setup never relabels the immutable run whose stages are shown.
run("const savedJob={name:'saved-sap-gamma',configuration_sha256:'a'.repeat(64),selection:{detector:'SAP22',source:'mono_gamma_662_axis_v1',primary_count:20,electronics:{gain:21}},stages:{geometry:{status:'completed',elapsed_seconds:7.62}}};showRun(savedJob);");
assert.match(get('saved-source-pose').textContent,/Selected run source pose · legacy fixed pose/);
run("const angledJob={...savedJob,name:'saved-sap-angle',configuration_sha256:'7'.repeat(64),selection:{...savedJob.selection,source:'cs137_point_decay_v1',angle_deg:30},source_pose:sourcePose30,source_position_global_mm:sourcePose30.position_global_mm};showRun(angledJob);");
const immutablePose=get('saved-source-pose').textContent,immutablePlan=get('run-plan').textContent;
assert.match(immutablePose,/angle 30°.*17.8/);assert.equal(JSON.parse(immutablePlan).source_pose.anchors_sha256,'8'.repeat(64));
get('source').value='cs137_point_decay_v1';run('sourceChanged();');get('angle-deg').value='-30';run('invalidate();');
assert.equal(get('saved-source-pose').textContent,immutablePose);assert.equal(get('run-plan').textContent,immutablePlan);
run('showRun({...angledJob,source_pose:null,source_position_global_mm:undefined});');assert.match(get('saved-source-pose').textContent,/recorded angle 30°; resolved pose unavailable/);assert.doesNotMatch(get('saved-source-pose').textContent,/legacy fixed/);
run('showRun(savedJob);');
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
  assert.deepEqual(JSON.parse(run(`JSON.stringify(primaryOptions([${global}],flatBatchRecords(batchFixture(${batch},${local})),[]))`)),[{id:String(global),label:global+' · 1 group · native failure'}]);
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
  // Two actual poll() calls, then native-like keyboard activation of the safe
  // Show stages action. API replacements below are local in-memory fixtures.
  run(`let strictState=JSON.parse(JSON.stringify(focusState)),strictLegacyState={gamma:{jobs:[]}},strictPollCalls=[];api=async(path,body)=>{strictPollCalls.push({path,body});if(path==='/api/workflow/state')return strictState;if(path==='/api/state')return strictLegacyState;throw Error('Unexpected fixture action');};renderJobs(strictState);`);
  const pollCard=get('runs').children[0],keyboardStages=findButton(pollCard,'Show stages');keyboardStages.focus();
  for(let i=0;i<2;i++){await run('poll()');assert.equal(get('runs').children[0],pollCard);assert.equal(findButton(pollCard,'Show stages'),keyboardStages);assert.equal(fixtureDocument.activeElement,keyboardStages);assert.equal(keyboardStages.moves,0);}
  assert.equal(run('strictPollCalls.length'),4);
  await keyboardStages.pressKey('Enter');assert.equal(run('selectedJob'),'focus-a');assert.equal(fixtureDocument.activeElement,keyboardStages);assert.equal(keyboardStages.disabled,false);
  assert.ok(JSON.parse(run('JSON.stringify(strictPollCalls)')).every(c=>['/api/workflow/state','/api/state'].includes(c.path)));
  run('strictState={...strictState,jobs:[otherFocusJob,{...focusJob,stages:{geometry:{status:"completed",elapsed_seconds:22}},error:"updated receipt"}]};');
  await run('poll()');await keyboardStages.pressKey(' ');
  assert.equal(run('selectedRun.stages.geometry.elapsed_seconds'),22);assert.equal(findButton(pollCard,'Show stages'),keyboardStages);
  // Pending operations cannot be repeated or revived by unrelated polls.
  // Even disappearance/reappearance of the same logical action stays pending;
  // the original removed button never transfers focus to the new action node.
  run(`let strictActionCalls=[],strictResolveAction,strictRejectAction;api=async(path,body)=>{if(path==='/api/workflow/state')return strictState;if(path==='/api/state')return strictLegacyState;strictActionCalls.push({path,body});return new Promise((resolve,reject)=>{strictResolveAction=resolve;strictRejectAction=reject;});};`);
  const pendingResume=findButton(pollCard,'Resume saved settings');pendingResume.focus();const resumeOperation=pendingResume.pressKey('Enter');
  assert.equal(pendingResume.disabled,true);assert.equal(run('strictActionCalls.length'),1);
  run('strictState={...strictState,busy:true};');await run('poll()');await pendingResume.click();
  assert.equal(pendingResume.disabled,true);assert.equal(run('strictActionCalls.length'),1);assert.equal(get('start').disabled,true);assert.equal(get('check').disabled,true);
  run('strictState={busy:true,jobs:[otherFocusJob,{...focusJob,status:"running"}]};');await run('poll()');
  assert.equal(pendingResume.isConnected,false);assert.equal(fixtureDocument.activeElement,fixtureDocument.body);
  run('strictState={busy:false,jobs:[otherFocusJob,{...focusJob,error:"new polling diagnostic"}]};');await run('poll()');
  const returnedResume=findButton(pollCard,'Resume saved settings');assert.notEqual(returnedResume,pendingResume);assert.equal(returnedResume.disabled,true);await returnedResume.click();assert.equal(run('strictActionCalls.length'),1);
  run('strictResolveAction({});');await resumeOperation;assert.equal(returnedResume.disabled,false);assert.equal(fixtureDocument.activeElement,fixtureDocument.body);
  assert.deepEqual(JSON.parse(run('JSON.stringify(strictActionCalls[0])')),{path:'/api/workflow/resume',body:{name:'focus-a'}});
  run('strictState={busy:true,jobs:[otherFocusJob,{...focusJob,status:"dispatch_uncertain",can_recover_launch:true}]};');await run('poll()');
  const pendingRecover=findButton(pollCard,'Recover not-launched failure');pendingRecover.focus();const recoverOperation=pendingRecover.pressKey('Enter');
  await run('poll()');await pendingRecover.click();assert.equal(pendingRecover.disabled,true);assert.equal(run('strictActionCalls.length'),2);
  run('strictState={busy:true,jobs:[otherFocusJob,{...focusJob,status:"dispatch_uncertain",can_recover_launch:false,can_inspect_failure:false}]};');await run('poll()');
  assert.equal(pendingRecover.isConnected,false);assert.equal(fixtureDocument.activeElement,fixtureDocument.body);assert.ok(findButton(pollCard,'Verify saved execution'));assert.equal(findButton(pollCard,'Verify existing completion'),undefined);
  run('strictState={busy:false,jobs:[otherFocusJob,{...focusJob,status:"launch_failed",can_verify_saved_execution:false,can_continue_prefix:false}]};strictResolveAction(strictState.jobs[1]);');await recoverOperation;
  assert.equal(findButton(pollCard,'Recover not-launched failure'),undefined);assert.equal(findButton(pollCard,'Resume saved settings'),undefined);assert.equal(fixtureDocument.activeElement,fixtureDocument.body);
  assert.deepEqual(JSON.parse(run('JSON.stringify(strictActionCalls[1])')),{path:'/api/workflow/recover-launch',body:{name:'focus-a'}});
  for(const [label,stateCode,expectedPath]of [
    ['Verify saved execution','{...focusJob}','/api/workflow/verify'],
    ['Verify existing completion','{...focusJob,status:"dispatch_uncertain",can_recover_launch:false,can_verify_saved_execution:false,can_inspect_failure:false}','/api/workflow/verify']
  ]){
    run(`strictState={busy:false,jobs:[otherFocusJob,${stateCode}]};`);await run('poll()');const verify=findButton(pollCard,label);assert.ok(verify);verify.focus();const verification=verify.pressKey('Enter'),count=run('strictActionCalls.length');
    await run('poll()');await run('poll()');assert.equal(findButton(pollCard,label),verify);assert.equal(verify.disabled,true);await verify.click();assert.equal(run('strictActionCalls.length'),count);
    run('strictResolveAction(strictState.jobs[1]);');await verification;assert.equal(verify.disabled,false);assert.equal(fixtureDocument.activeElement,verify);
    assert.deepEqual(JSON.parse(run(`JSON.stringify(strictActionCalls[${count-1}])`)),{path:expectedPath,body:{name:'focus-a'}});
  }
  // PHYS-01/W1/IND: both Verify presentations operate on the same endpoint and
  // run identity. They are mutually exclusive and share one pending action key.
  const verifyLabels=['Verify saved execution','Verify existing completion'];
  const onlyVerify=(card,label)=>{const present=card.children.filter(n=>n.tagName==='button'&&verifyLabels.includes(n.textContent));assert.equal(present.length,1);assert.equal(present[0].textContent,label);return present[0];};
  run('strictState={busy:false,jobs:[otherFocusJob,{...focusJob,status:"dispatch_uncertain",can_recover_launch:false,can_verify_saved_execution:true,can_inspect_failure:true}]};');await run('poll()');
  const savedVerify=onlyVerify(pollCard,'Verify saved execution'),sharedVerifyKey=savedVerify.runActionKey;assert.match(sharedVerifyKey,/\/action:workflow-verify$/);assert.ok(findButton(pollCard,'Inspect denied launch'));
  savedVerify.focus();const savedVerifyOperation=savedVerify.pressKey('Enter'),savedVerifyCount=run('strictActionCalls.length');
  for(const savedAllowed of [false,true,false]){
    run(`strictState.jobs[1]={...strictState.jobs[1],can_verify_saved_execution:${savedAllowed}};`);await run('poll()');
    const currentVerify=onlyVerify(pollCard,savedAllowed?'Verify saved execution':'Verify existing completion');assert.equal(currentVerify,savedVerify);assert.equal(currentVerify.runActionKey,sharedVerifyKey);assert.equal(currentVerify.disabled,true);
    await currentVerify.click();await currentVerify.onclick();assert.equal(run('strictActionCalls.length'),savedVerifyCount);assert.ok(findButton(pollCard,'Inspect denied launch'));
  }
  run('strictResolveAction(strictState.jobs[1]);');await savedVerifyOperation;assert.equal(onlyVerify(pollCard,'Verify existing completion'),savedVerify);assert.equal(savedVerify.disabled,false);assert.equal(run('pendingActions.size'),0);
  assert.match(get('notice').textContent,/Saved execution verified/);assert.deepEqual(JSON.parse(run('JSON.stringify(strictActionCalls.at(-1))')),{path:'/api/workflow/verify',body:{name:'focus-a'}});
  const fallbackVerify=onlyVerify(pollCard,'Verify existing completion');fallbackVerify.focus();const fallbackVerifyOperation=fallbackVerify.pressKey('Enter'),fallbackVerifyCount=run('strictActionCalls.length');
  for(const savedAllowed of [true,false,true]){
    run(`strictState.jobs[1]={...strictState.jobs[1],can_verify_saved_execution:${savedAllowed}};`);await run('poll()');
    const currentVerify=onlyVerify(pollCard,savedAllowed?'Verify saved execution':'Verify existing completion');assert.equal(currentVerify,fallbackVerify);assert.equal(currentVerify.runActionKey,sharedVerifyKey);assert.equal(currentVerify.disabled,true);await currentVerify.click();assert.equal(run('strictActionCalls.length'),fallbackVerifyCount);
  }
  run('strictRejectAction(Error("fixture shared Verify rejected"));');await fallbackVerifyOperation;
  assert.equal(onlyVerify(pollCard,'Verify saved execution'),fallbackVerify);assert.equal(fallbackVerify.disabled,false);assert.equal(run('pendingActions.size'),0);assert.match(get('notice').textContent,/fixture shared Verify rejected/);
  // Withdrawing both Verify permissions removes that action. Recovery/Inspect
  // retain their original permissions; a later Verify keeps its pending key
  // until completion and never inherits focus from the removed action node.
  fallbackVerify.focus();const revokedVerifyOperation=fallbackVerify.pressKey('Enter'),revokedVerifyCount=run('strictActionCalls.length');
  run('strictState.jobs[1]={...strictState.jobs[1],can_verify_saved_execution:false,can_recover_launch:true};');await run('poll()');
  assert.equal(pollCard.children.filter(n=>verifyLabels.includes(n.textContent)).length,0);assert.equal(fallbackVerify.isConnected,false);assert.equal(fixtureDocument.activeElement,fixtureDocument.body);assert.ok(findButton(pollCard,'Recover not-launched failure'));assert.equal(findButton(pollCard,'Inspect denied launch'),undefined);
  run('strictState.jobs[1]={...strictState.jobs[1],can_recover_launch:false,can_inspect_failure:true};');await run('poll()');
  const reappearedVerify=onlyVerify(pollCard,'Verify existing completion');assert.notEqual(reappearedVerify,fallbackVerify);assert.equal(reappearedVerify.runActionKey,sharedVerifyKey);assert.equal(reappearedVerify.disabled,true);await reappearedVerify.click();assert.equal(run('strictActionCalls.length'),revokedVerifyCount);assert.equal(fixtureDocument.activeElement,fixtureDocument.body);assert.ok(findButton(pollCard,'Inspect denied launch'));
  run('strictState.jobs[1]={...strictState.jobs[1],can_recover_launch:true};');await run('poll()');assert.equal(reappearedVerify.isConnected,false);assert.equal(reappearedVerify.disabled,true);
  run('strictResolveAction(strictState.jobs[1]);');await revokedVerifyOperation;
  assert.equal(pollCard.children.filter(n=>verifyLabels.includes(n.textContent)).length,0);assert.equal(run('pendingActions.size'),0);assert.equal(fixtureDocument.activeElement,fixtureDocument.body);assert.equal(reappearedVerify.disabled,true);assert.ok(findButton(pollCard,'Recover not-launched failure'));
  console.log('STRICT-03 shared Verify identity: exclusive presentation, both held label directions, single POST, success/rejection, revocation/reappearance and original Recover/Inspect permissions passed.');
  run('strictState={busy:false,jobs:[otherFocusJob,focusJob]};');await run('poll()');
  const disappearingCard=get('runs').children[1],disappearingResume=findButton(disappearingCard,'Resume saved settings');disappearingResume.focus();const disappearingOperation=disappearingResume.pressKey('Enter'),disappearingCount=run('strictActionCalls.length');
  run('strictState={busy:false,jobs:[focusJob]};');await run('poll()');assert.equal(disappearingCard.isConnected,false);
  run('strictState={busy:false,jobs:[otherFocusJob,focusJob]};');await run('poll()');
  const reappearingResume=findButton(get('runs').children[1],'Resume saved settings');assert.notEqual(reappearingResume,disappearingResume);assert.equal(reappearingResume.disabled,true);await reappearingResume.click();assert.equal(run('strictActionCalls.length'),disappearingCount);
  run('strictResolveAction({});');await disappearingOperation;assert.equal(reappearingResume.disabled,false);assert.equal(fixtureDocument.activeElement,fixtureDocument.body);
  run('strictState={busy:false,jobs:[otherFocusJob,focusJob]};');await run('poll()');
  const currentContinuation=pollCard.children.find(n=>n.tagName==='label').children[0];currentContinuation.focus();await run('poll()');
  currentContinuation.value='after-poll-input';currentContinuation.oninput();currentContinuation.setSelectionRange(4,9);
  const continueButton=findButton(pollCard,'Continue from verified transport');const continuationOperation=continueButton.click();
  assert.deepEqual(JSON.parse(run('JSON.stringify(strictActionCalls.at(-1))')),{path:'/api/workflow/continue-prefix',body:{name:'focus-a',new_name:'after-poll-input'}});
  run('strictResolveAction(strictState.jobs[1]);');await continuationOperation;assert.equal(fixtureDocument.activeElement,currentContinuation);assert.deepEqual([currentContinuation.selectionStart,currentContinuation.selectionEnd],[4,9]);
  currentContinuation.value='';currentContinuation.oninput();await run('poll()');assert.equal(currentContinuation.value,'');
  const emptyContinuation=continueButton.click();assert.deepEqual(JSON.parse(run('JSON.stringify(strictActionCalls.at(-1))')),{path:'/api/workflow/continue-prefix',body:{name:'focus-a',new_name:''}});
  run('strictRejectAction(Error("empty name refused by fixture"));');await emptyContinuation;assert.equal(currentContinuation.value,'');
  run('strictLegacyState=JSON.parse(JSON.stringify(legacyFocusState));');await run('poll()');const currentLegacyVerify=findButton(get('legacy-runs').children[0],'Verify saved completion');currentLegacyVerify.focus();const legacyOperation=currentLegacyVerify.pressKey('Enter'),legacyCount=run('strictActionCalls.length');
  await run('poll()');await currentLegacyVerify.click();assert.equal(currentLegacyVerify.disabled,true);assert.equal(run('strictActionCalls.length'),legacyCount);
  run('strictRejectAction(Error("fixture verification refused"));');await legacyOperation;assert.equal(currentLegacyVerify.disabled,false);assert.equal(fixtureDocument.activeElement,currentLegacyVerify);assert.match(get('notice').textContent,/fixture verification refused/);
  assert.deepEqual(JSON.parse(run('JSON.stringify(strictActionCalls.at(-1))')),{path:'/api/gamma-verify',body:{job_id:'legacy-focus'}});
  assert.equal(run('pendingActions.size'),0);
  run('renderJobs({busy:false,jobs:[]});renderLegacy({gamma:{jobs:[]}});showRun(savedJob);');
  console.log('STRICT-03 two polls, Enter/Space Show stages, pending Resume/Recover/Verify/legacy Verify, removal/reappearance, current continuation input and denied action contracts passed.');
  // Desktop feedback follows the normal Check -> edit -> recheck path. Status
  // polls preserve the latest real action error and the selected saved record.
  get('detector').value='SAP22';get('source').value='cs137_point_decay_v1';run('sourceChanged();');get('angle-deg').value='0';run('invalidate();');
  run(`const feedbackJob={...savedJob,id:'feedback-saved',status:'stopped',can_verify_saved_execution:true};
  let feedbackState={busy:false,jobs:[feedbackJob]},feedbackResolve,feedbackReject,feedbackCalls=[];
  api=(path,body)=>{feedbackCalls.push({path,body});if(path==='/api/workflow/state')return Promise.resolve(feedbackState);if(path==='/api/state')return Promise.resolve({gamma:{jobs:[]}});if(path==='/api/workflow/verify')return Promise.reject(Error('Saved verification fixture error'));return new Promise((resolve,reject)=>{feedbackResolve=resolve;feedbackReject=reject;});};
  renderJobs(feedbackState);showRun(feedbackJob);
  result={job:feedbackJob,records:[{record_kind:'decay',event_id:7,deposited_energy_keV:4,pulse_count:1},{record_kind:'pulse',event_id:7,group_id:3,origin_time_ns:5000,deposited_energy_keV:4,final_induced_keV:-4,readout:null},{record_kind:'decay',event_id:8,deposited_energy_keV:0,pulse_count:0,zero_deposit:true}],traces:[]};$('event').value='7';showEvent(1);`);
  const feedbackResult=run('result'),feedbackSaved=run('JSON.stringify(selectedRun)'),feedbackPlan=get('run-plan').textContent,feedbackRecord=get('event-record').textContent;
  const feedbackButton=get('check');feedbackButton.tagName='button';feedbackButton.focus();
  assert.equal(get('start').disabled,true);assert.match(get('run-readiness').textContent,/Run unavailable.*Check plan for the current setup/);
  const feedbackCheck=feedbackButton.pressKey('Enter');
  assert.equal(get('start').disabled,true);assert.match(get('run-readiness').textContent,/current action is pending.*Wait/);
  assert.equal(run('feedbackCalls.at(-1).path'),'/api/workflow/check-batches');assert.equal(run('feedbackCalls.at(-1).body.request.selection.detector'),'SAP22');
  const pendingFeedbackCalls=run('feedbackCalls.length');await feedbackButton.click();await run("$('start').onclick()");assert.equal(run('feedbackCalls.length'),pendingFeedbackCalls);
  // Model the browser moving focus to body when a focused button disables.
  fixtureDocument.activeElement=fixtureDocument.body;
  run("const feedbackReply=()=>({kind:'local_scenario_batch_execution_v3',schema_version:3,execution_enabled:true,check_id:'feedback-checked',resolved:{selection:config(),batching:{batch_count:1}}});feedbackResolve(feedbackReply());");await feedbackCheck;
  assert.equal(fixtureDocument.activeElement,feedbackButton);assert.equal(get('start').disabled,false);assert.match(get('run-readiness').textContent,/Ready to Run with the checked next-run configuration/);
  assert.match(get('notice').textContent,/Exact count checked.*Run uses this checked plan/);
  const readyWrites=get('run-readiness').textWrites;await run('poll()');await run('poll()');assert.equal(get('run-readiness').textWrites,readyWrites);
  get('name').value='feedback-next-edited';run('invalidate();');
  assert.equal(run('checked'),null);assert.equal(get('start').disabled,true);assert.match(get('notice').textContent,/earlier checked plan is cleared.*Check plan again/);assert.doesNotMatch(get('notice').textContent,/Run uses this checked plan/);
  assert.match(get('run-readiness').textContent,/editing settings clears any earlier check/);
  assert.equal(run('result'),feedbackResult);assert.equal(run('JSON.stringify(selectedRun)'),feedbackSaved);assert.equal(get('run-plan').textContent,feedbackPlan);assert.equal(get('event-record').textContent,feedbackRecord);assert.equal(get('event').value,'7');assert.equal(get('group').value,'1');
  assert.equal(get('result-data').children[0].children[1].children[0].textContent,'-4');assert.equal(get('result-data').children[0].children[2].children[0].textContent,'Unavailable');assert.equal(run('result.records.length'),3);assert.equal(run('result.records[2].zero_deposit'),true);
  feedbackButton.focus();const movedFocusCheck=feedbackButton.pressKey('Enter');get('event').focus();run('feedbackResolve(feedbackReply());');await movedFocusCheck;
  assert.equal(fixtureDocument.activeElement,get('event'));assert.equal(get('start').disabled,false);
  const feedbackVerify=findButton(get('runs').children[0],'Verify saved execution');await feedbackVerify.click();
  assert.match(get('notice').textContent,/Saved verification fixture error/);assert.equal(get('notice').className,'notice error');assert.ok(run('checked'));
  await run('poll()');await run('poll()');get('setting-gain').value='4';run('invalidate();');
  assert.equal(get('notice').textContent,'Saved verification fixture error');assert.equal(get('notice').className,'notice error');assert.equal(run('checked'),null);assert.equal(get('start').disabled,true);
  const failedFeedbackCheck=run("$('check').onclick()");run("feedbackReject(Error('Current Check fixture error'));");await failedFeedbackCheck;
  await run('poll()');await run('poll()');assert.equal(get('notice').textContent,'Current Check fixture error');assert.equal(get('notice').className,'notice error');assert.equal(run('checked'),null);
  const importFeedbackCheck=run("$('check').onclick()");run('feedbackResolve(feedbackReply());');await importFeedbackCheck;
  run("$('import').files=[{size:100,text:async()=>JSON.stringify({...config(),extra:true})}];");await run("$('import').onchange()");
  assert.match(get('notice').textContent,/Configuration fields do not match/);const importFailure=get('notice').textContent;assert.ok(run('checked'));
  await run('poll()');await run('poll()');get('name').value='feedback-after-import';run('invalidate();');assert.equal(get('notice').textContent,importFailure);assert.equal(get('notice').className,'notice error');assert.equal(get('start').disabled,true);
  const informationFeedbackCheck=run("$('check').onclick()");run('feedbackResolve(feedbackReply());');await informationFeedbackCheck;
  run("notice('Saved operation information retained.');");get('name').value='feedback-after-info';run('invalidate();');assert.equal(get('notice').textContent,'Saved operation information retained.');
  // W1: a recheck clears authorization before an edit. Its old owned success
  // must still clear immediately, even when the obsolete held request rejects.
  const retryBaseCheck=run("$('check').onclick()");run('feedbackResolve(feedbackReply());');await retryBaseCheck;
  assert.match(get('notice').textContent,/Exact count checked.*Run uses this checked plan/);assert.equal(run('noticeIsCheckedPlan'),true);
  feedbackButton.focus();const rejectedRetryCheck=feedbackButton.pressKey('Enter');
  assert.equal(run('checked'),null);assert.equal(run('busy'),true);assert.equal(get('start').disabled,true);assert.equal(run('noticeIsCheckedPlan'),true);
  get('name').value='feedback-held-retry-reject';get('name').focus();run('invalidate();');
  assert.equal(run('noticeIsCheckedPlan'),false);assert.match(get('notice').textContent,/earlier checked plan is cleared.*Check plan again/);assert.doesNotMatch(get('notice').textContent,/Run uses this checked plan/);assert.equal(get('start').disabled,true);
  const clearedRetryNotice=get('notice').textContent;run("feedbackReject(Error('Obsolete held Check rejection'));");await rejectedRetryCheck;await run('poll()');
  assert.equal(run('checked'),null);assert.equal(run('busy'),false);assert.equal(get('start').disabled,true);assert.equal(get('notice').textContent,clearedRetryNotice);assert.equal(fixtureDocument.activeElement,get('name'));
  assert.match(get('run-readiness').textContent,/Run unavailable.*Check plan for the current setup/);
  const successRetryBaseCheck=run("$('check').onclick()");run('feedbackResolve(feedbackReply());');await successRetryBaseCheck;
  assert.equal(get('start').disabled,false);feedbackButton.focus();const successfulRetryCheck=feedbackButton.pressKey('Enter');run('const staleFeedbackReply=feedbackReply();');
  get('name').value='feedback-held-retry-success';get('name').focus();run('invalidate();');assert.doesNotMatch(get('notice').textContent,/Run uses this checked plan/);assert.equal(run('noticeIsCheckedPlan'),false);
  run('feedbackResolve(staleFeedbackReply);');await successfulRetryCheck;await run('poll()');
  assert.equal(run('checked'),null);assert.equal(get('start').disabled,true);assert.match(get('notice').textContent,/Selection changed while Check was pending/);assert.doesNotMatch(get('notice').textContent,/Run uses this checked plan/);assert.equal(fixtureDocument.activeElement,get('name'));
  console.log('W1 repeated Check: held edit immediately clears old owned success; obsolete rejection and successful reply retain disabled Run, generation fences and current name focus; poll never revives the old notice.');
  const activeFeedbackCheck=run("$('check').onclick()");run('feedbackResolve(feedbackReply());');await activeFeedbackCheck;
  run('feedbackState={...feedbackState,busy:true};');await run('poll()');assert.equal(get('start').disabled,true);assert.match(get('run-readiness').textContent,/existing work is active or needs inspection.*Review Runs/);
  const activeFeedbackCalls=run('feedbackCalls.length');await run("$('start').onclick()");await run("$('check').onclick()");assert.equal(run('feedbackCalls.length'),activeFeedbackCalls);
  run('feedbackState={...feedbackState,busy:false};');await run('poll()');assert.equal(get('start').disabled,false);assert.match(get('run-readiness').textContent,/Ready to Run/);
  get('detector').value='large-model';run('detectorChanged();');assert.equal(get('start').disabled,true);assert.match(get('run-readiness').textContent,/View only.*Radius 40 mm.*larger cryostat.*compute-supported/);
  get('detector').value='SAP22';run('detectorChanged();');run('currentSource().available=false;controls();');assert.equal(get('start').disabled,true);assert.match(get('run-readiness').textContent,/combination is unavailable.*compute-supported/);
  run('delete currentSource().available;catalog.cryostats[0].available=false;controls();');assert.equal(get('start').disabled,true);assert.match(get('run-readiness').textContent,/combination is unavailable/);run('catalog.cryostats[0].available=true;controls();');
  // An edited view-only choice cannot receive focus when a stale Check ends.
  feedbackButton.focus();const revokedFeedbackCheck=feedbackButton.pressKey('Enter');get('detector').value='large-model';run('detectorChanged();');fixtureDocument.activeElement=fixtureDocument.body;
  run('feedbackResolve(feedbackReply());');await revokedFeedbackCheck;assert.equal(feedbackButton.disabled,true);assert.equal(fixtureDocument.activeElement,fixtureDocument.body);assert.equal(run('checked'),null);
  get('detector').value='SAP22';run('detectorChanged();');
  console.log('Desktop readiness: normal Check/Enter, edit invalidation, unchanged status writes, action/Check/import error ownership, moved/revoked focus, active/view-only/unavailable gates and exact saved settings/signs/nulls/zeros passed.');
  // Every Download requests exact bytes; viewing keeps the default route.
  run("let artifactRequests=[];fetch=async(url,options)=>{artifactRequests.push({url,options});return {ok:true,blob:async()=>({})};};");
  await run("download('fixture','response/summary.html')");
  await run("artifact('fixture','response/summary.html')");
  assert.match(run('artifactRequests[0].url'),/download=1/);
  assert.doesNotMatch(run('artifactRequests[1].url'),/download=/);
  assert.equal(run("artifactRequests[0].options.headers['X-Control-Token']"),'fixture');
  // The same checked nonzero pose reaches Start and remains attached to saved
  // Stop/Resume work when the next form changes. No real worker is launched.
  get('detector').value='SAP22';get('source').value='cs137_point_decay_v1';run('sourceChanged();');get('angle-deg').value='30';run('invalidate();');
  run("let resolveAngleCheck,angleCheckRequests=[];api=(path,body)=>{angleCheckRequests.push({path,body});return new Promise(resolve=>resolveAngleCheck=resolve);};");
  const staleAngleCheck=run("$('check').onclick()");assert.equal(run('angleCheckRequests[0].body.request.selection.angle_deg'),30);
  get('angle-deg').value='-30';run("invalidate();resolveAngleCheck({kind:'local_scenario_batch_execution_v3',schema_version:3,execution_enabled:true,check_id:'stale-angle',resolved:{selection:{angle_deg:30},source_pose:sourcePose30,batching:{batch_count:1}}});");await staleAngleCheck;
  assert.equal(run('checked'),null);assert.equal(get('start').disabled,true);assert.match(get('source-pose-preview').textContent,/Check plan to resolve/);
  get('angle-deg').value='30';run('invalidate();');
  const pendingAngle=run("$('check').onclick()");run("resolveAngleCheck({kind:'local_scenario_batch_execution_v3',schema_version:3,execution_enabled:false,resolved:{selection:config(),source_pose:sourcePose30,source_position_global_mm:sourcePose30.position_global_mm,batching:{batch_count:1}}});");await pendingAngle;
  assert.equal(get('start').disabled,true);assert.equal(run('checked.execution_enabled'),false);
  assert.match(get('run-readiness').textContent,/checked plan does not authorize execution.*nonzero-angle acceptance is pending.*Check plan again/);
  assert.match(get('notice').textContent,/Nonzero-angle execution is unavailable/);
  assert.match(get('source-pose-preview').textContent,/angle 30°/);
  const callsBeforePendingStart=run('angleCheckRequests.length');await run("$('start').onclick()");assert.equal(run('angleCheckRequests.length'),callsBeforePendingStart);
  const checkedAngle=run("$('check').onclick()");run("resolveAngleCheck({kind:'local_scenario_batch_execution_v3',schema_version:3,execution_enabled:true,check_id:'checked-angle',resolved:{selection:config(),source_pose:sourcePose30,source_position_global_mm:sourcePose30.position_global_mm,batching:{batch_count:1}}});");await checkedAngle;
  assert.equal(run('checked.resolved.selection.angle_deg'),30);assert.match(get('source-pose-preview').textContent,/Checked effective source pose · angle 30°/);
  run("let angleActionCalls=[];const angleStartedJob={...angledJob,id:'angle-job',status:'stopped',execution_contract:'serial_batches_v3',batching:{batch_count:1}};api=async(path,body)=>{angleActionCalls.push({path,body});return path==='/api/workflow/state'?{busy:false,jobs:[angleStartedJob]}:path==='/api/state'?{gamma:{jobs:[]}}:angleStartedJob;};");
  await run("$('start').onclick()");
  assert.equal(run('angleActionCalls[0].path'),'/api/workflow/start');assert.deepEqual(JSON.parse(run('JSON.stringify(angleActionCalls[0].body)')),{check_id:'checked-angle'});
  assert.match(get('saved-source-pose').textContent,/angle 30°/);get('angle-deg').value='-30';run('invalidate();');assert.match(get('saved-source-pose').textContent,/angle 30°/);
  const resumeAngle=get('runs').children[0].children.find(n=>n.textContent==='Resume saved settings');assert.ok(resumeAngle);await resumeAngle.onclick();
  assert.deepEqual(JSON.parse(run("JSON.stringify(angleActionCalls.find(c=>c.path==='/api/workflow/resume').body)")),{name:'saved-sap-angle'});assert.equal(get('angle-deg').value,'-30');assert.match(get('saved-source-pose').textContent,/angle 30°/);
  // Loading/exporting retains the optional angle; legacy explicit zero is
  // normalized without mutating the imported object or replacing a bad setup.
  run("const angleImport={...config(),angle_deg:30};$('import').files=[{size:100,text:async()=>JSON.stringify(batchRequest(angleImport))}];");
  await run("$('import').onchange()");assert.equal(get('angle-deg').value,'30');assert.equal(run('batchRequest(config()).selection.angle_deg'),30);
  run("$('import').files=[{size:100,text:async()=>JSON.stringify(batchRequest({...angleImport,angle_deg:true}))}];");await run("$('import').onchange()");assert.equal(get('angle-deg').value,'30');assert.match(get('notice').textContent,/source angle is unavailable/);
  run("const zeroImport={...angleImport,angle_deg:0};const normalizedZero=importedConfig(zeroImport,true);");assert.equal(run('zeroImport.angle_deg'),0);assert.equal(run("Object.hasOwn(normalizedZero,'angle_deg')"),false);
  get('angle-deg').value='0';run('invalidate();');
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
  run(`pageReplies[3].resolve({kind:'local_batch_waveform_v1',name:batchJob.name,configuration_sha256:batchJob.configuration_sha256,batch_index:2,batch_sha256:'e'.repeat(64),response_summary_sha256:'f'.repeat(64),ionisation_energy_eV:2.95,charge_input:{time_since_origin_ns:Array.from({length:501},(_,i)=>i*2),induced_equivalent_energy_keV:[0,-.001,...Array.from({length:499},(_,i)=>-.001-(i+1)*.002/499)]},record:{global_initial_id:20000,group_id:0,origin_time_ns:500000,trace:{time_ns:[0,2,1000],current_nA:[0,-.2,-.1],current_bin_start_ns:[0,0,998],current_bin_end_ns:[0,2,1000],preamp_V:[0,-.5,-1],shaped_V:[0,.5,1]}}});`);
  await Promise.resolve();await Promise.resolve();assert.equal(get('plots').children.filter(n=>n.tagName==='figure').length,4);
  assert.match(get('event-identity').textContent,/Initial primary 20000/);
  // Poll responses arriving out of order never restore obsolete job status.
  run("let pollReplies=[];api=path=>new Promise(resolve=>pollReplies.push({path,resolve}));");
  const oldPoll=run('poll()'),newPoll=run('poll()');
  run("pollReplies[2].resolve({busy:false,jobs:[]});pollReplies[3].resolve({jobs:[]});");await newPoll;
  run("pollReplies[0].resolve({busy:true,jobs:[]});pollReplies[1].resolve({jobs:[]});");await oldPoll;
  assert.equal(run('active'),false);
  // Both option-building paths preserve census/default, then the chosen primary,
  // group and focus when the same saved run is reopened with hints.
  run(`const hintJob={...savedJob,name:'primary-hints-saved'};const hintFocusRequests=[];
  artifact=async(name,file)=>{if(name!==hintJob.name)throw Error('Hint fixture run differs');if(file==='response/run.json')return {json:async()=>({source_id:hintJob.selection.source,artifacts:{'summary.html':'c'.repeat(64)}})};if(file==='COMPLETE.json')return {json:async()=>({configuration_sha256:hintJob.configuration_sha256,artifacts:{'response/summary.html':{sha256:'c'.repeat(64)}}})};if(file==='response/scalars.jsonl')return {text:async()=>hintRows.map(r=>JSON.stringify(r)).join('\\n')};if(file==='response/traces.jsonl')return {text:async()=>hintTraces.map(r=>JSON.stringify(r)).join('\\n')};throw Error('Unexpected hint artifact');};
  api=async path=>{hintFocusRequests.push(path);throw Error('Synthetic saved waveform intentionally unavailable');};`);
  await run('openResult(hintJob)');
  assert.deepEqual(get('event').children.map(o=>o.value),[...hintLabels.keys()]);
  for(const option of get('event').children)assert.equal(option.textContent,hintLabels.get(option.value));
  assert.equal(get('event').value,'5');assert.equal(get('group').value,'1');
  assert.equal(run('JSON.stringify([result.records,result.traces])'),run('hintBefore'));
  get('event').value='14';get('event').onchange();get('group').value='2';get('group').onchange();
  assert.match(get('analysis-selection').textContent,/initial primary ID 14.*pulse group 1/);
  const hintSelectedRecord=get('event-record').textContent;get('event').focus();
  await run('openResult(hintJob)');
  assert.equal(get('event').value,'14');assert.equal(get('group').value,'2');
  assert.equal(fixtureDocument.activeElement,get('event'));assert.equal(get('event-record').textContent,hintSelectedRecord);
  assert.equal(get('event').children.find(o=>o.value==='14').textContent,'14 · 2 groups · mixed readout');
  assert.equal(run('JSON.stringify([result.records,result.traces])'),run('hintBefore'));
  assert.ok(JSON.parse(run('JSON.stringify(hintFocusRequests)')).every(path=>/workflow-file\/focus\?/.test(path)));
  run(`const hintPage=batchFixture(1,9998,2);hintPage.records[0].primary={record_kind:'decay',event_id:9998,pulse_count:0,deposited_energy_keV:0,zero_deposit:true};hintPage.records[0].pulse_groups=[];const hintPageBefore=JSON.stringify(hintPage),hintPageRequests=[];
  api=async path=>{hintPageRequests.push(path);return JSON.parse(hintPageBefore);};`);
  // Use the existing page controls at a local/global end-of-batch boundary.
  run(`showRun(batchJob);result={job:batchJob,page:null,records:[],traces:[]};$('batch-index').value='1';$('page-offset').value='9998';`);
  await run('loadBatchPage()');
  assert.deepEqual(get('event').children.map(o=>({value:o.value,label:o.textContent})),[{value:'19998',label:'19998 · zero deposition'},{value:'19999',label:'19999 · 1 group · native failure'}]);
  get('event').value='19999';get('event').onchange();get('group').value='1';get('group').onchange();get('event').focus();
  const hintBoundaryRecord=get('event-record').textContent;
  await run('openBatchResult(batchJob)');
  assert.equal(get('batch-index').value,'1');assert.equal(get('page-offset').value,'9998');assert.equal(get('event').value,'19999');assert.equal(get('group').value,'1');
  assert.equal(fixtureDocument.activeElement,get('event'));assert.equal(get('event-record').textContent,hintBoundaryRecord);
  assert.match(get('analysis-selection').textContent,/batch 1.*global initial ID 19999.*local initial ID 9999.*pulse group 0/);
  assert.match(get('analysis-filter').textContent,/evtid = 9999 in batch 1.*global_initial_id = 19999/);
  assert.equal(run('JSON.stringify(result.page)'),run('hintPageBefore'));
  assert.ok(JSON.parse(run('JSON.stringify(hintPageRequests)')).every(path=>/workflow\/events\?.*batch=1&offset=9998&limit=100/.test(path)));
  // Saved PSD1 features remain lazy, tied to exact global/group identities and
  // source/profile/bundle hashes. Invalid/capped candidates are separate from
  // canonical null features; signed values, zeros and the census stay intact.
  assert.match(html,/<details id="feature-panel"><summary>Saved waveform features and deposition topology<\/summary>/);
  assert.match(html,/existing verified export; opening it verifies saved data without starting a simulation or export/);
  run(`const featureJob={...batchJob,name:'feature-saved',configuration_sha256:'a'.repeat(64)};
    const featureRows=[{record_kind:'decay',global_initial_id:371,event_id:121,batch_index:1,local_initial_id:121,pulse_count:1,deposited_energy_keV:4},
      {record_kind:'pulse',global_initial_id:371,event_id:121,batch_index:1,local_initial_id:121,group_id:0,origin_time_ns:42,deposited_energy_keV:4,final_induced_keV:-.003,readout:{accepted:true,reconstructed_energy_keV:3.9}},
      {record_kind:'decay',global_initial_id:372,event_id:122,batch_index:1,local_initial_id:122,pulse_count:0,deposited_energy_keV:0,zero_deposit:true}];
    const featureRowsBefore=JSON.stringify(featureRows),featureRequests=[];
    const featureGroup={global_initial_id:371,event_id:121,batch_index:1,local_initial_id:121,group_id:0,origin_time_ns:42,truth_Edep_keV:4,Erec_keV:3.9,selection:{valid:false,reasons:['native_step_limit','incomplete_endpoint']},features:{A_nA:null,A_over_E_nA_per_keV:null,charge_rise_10_90_ns:null},observed:{signed_filtered_current_peak_nA:-.003,native_signed_current_at_peak_nA:-.003,peak_time_since_origin_ns:12,signed_charge_change_keV:-.004,t10_ns:null,t90_ns:null,charge_rise_10_90_ns:null,sample_count:5001,flags:['nonpositive_signed_observed_span']},deposits:[{raw_row_index:7,energy_keV:4,position_mm:[1,2,3]}],endpoints:[{raw_row_index:7,endpoint:{step_limit_reached:true}}],saved_scalar:{transport_flags:{step_limits:1},readout:{accepted:true,reconstructed_energy_keV:3.9}},raw_row_indices:[7],topology:{cluster_count:2,nominal_threshold_mm:1,proxy_label:'multi_point_cluster_proxy',limitation:'Spatial step positions are a proxy only.',sensitivity:[{threshold_mm:.5,cluster_count:3},{threshold_mm:1,cluster_count:2},{threshold_mm:2,cluster_count:1}]}};
    const featureZero={global_initial_id:372,event_id:122,batch_index:1,local_initial_id:122,truth_Edep_keV:0,Erec_keV:null,pulse_groups:[],selection:{valid:false,reasons:['zero_deposit']}};
    function featureReply(id=371,group=0,record=featureGroup){return {kind:'local_saved_psd_features_v1',name:featureJob.name,configuration_sha256:featureJob.configuration_sha256,primary_id:id,group_id:group,available:true,profile_sha256:'b'.repeat(64),bundle_sha256:'c'.repeat(64),profile:{kind:'saved_waveform_psd_profile_v1',schema_version:1,name:'signed-current-10ns-observed-charge-v1',polarity:1,current_filter:{width_ns:10},analysis_window_ns:[0,10000]},record,counts:{primaries:500,pulse_groups:4,selected_groups:0},provenance:{profile_sha256:'b'.repeat(64),run_ref:'.local/runs/feature-saved'}};}
    api=async path=>{featureRequests.push(path);return featureReply();};
    $('feature-panel').open=false;showRun(featureJob);result={job:featureJob,records:featureRows,traces:[]};$('event').value='371';showEvent(1);`);
  assert.equal(run('featureRequests.length'),0);
  get('feature-panel').open=true;await run('loadFeatures()');
  assert.match(run('featureRequests[0]'),/workflow\/features\?name=feature-saved&primary=371&group=0$/);
  assert.match(get('feature-status').textContent,/primary 371 · group 0.*selection invalid/);
  const featureText=n=>String(n.textContent||'')+' '+n.children.map(featureText).join(' ');
  assert.match(featureText(get('feature-content')),/native_step_limit · incomplete_endpoint/);
  assert.match(featureText(get('feature-content')),/Provisional observed signed waveform measurements/);
  assert.match(featureText(get('feature-content')),/A\/E · nA\/keV Unavailable/);
  assert.match(featureText(get('feature-content')),/Filtered current peak · declared polarity · nA -0\.003/);
  assert.match(featureText(get('feature-content')),/0\.5 mm → 3 clusters · 1 mm → 2 clusters · 2 mm → 1 clusters/);
  assert.match(featureText(get('feature-content')),/position_mm.*1,.*2,.*3/s);
  assert.match(featureText(get('feature-content')),/not physical single-site\/multi-site truth/);
  assert.match(featureText(get('feature-content')),/analysis 0…10000 ns since group origin/);
  assert.equal(run('JSON.stringify(featureRows)'),run('featureRowsBefore'));
  assert.equal(get('event').value,'371');assert.equal(get('group').value,'1');
  run(`api=async path=>{featureRequests.push(path);return featureReply(372,null,featureZero);};$('event').value='372';showEvent();`);
  await Promise.resolve();await Promise.resolve();
  assert.match(run('featureRequests.at(-1)'),/primary=372$/);assert.doesNotMatch(run('featureRequests.at(-1)'),/group=/);
  assert.match(featureText(get('feature-content')),/zero_deposit.*Truth Edep · keV 0.*Saved calibrated Erec · keV Unavailable/s);
  assert.match(featureText(get('feature-content')),/no saved pulse group/);
  assert.doesNotMatch(featureText(get('feature-content')),/Filtered current peak · declared polarity/);
  run(`api=async()=>({kind:'local_saved_psd_features_v1',name:featureJob.name,configuration_sha256:featureJob.configuration_sha256,primary_id:372,group_id:null,available:false,profile_sha256:null,bundle_sha256:null,note:'Saved features are unavailable. No calculation runs.'});`);
  await run('loadFeatures()');assert.equal(get('feature-content').children.length,0);
  assert.equal(get('feature-status').textContent,'Saved features are unavailable. No calculation runs.');
  // A genuine native failure retains null observations, never a zero current.
  run(`const failedFeature={...featureGroup,selection:{valid:false,reasons:['native_transport_failed','readout_unavailable','full_signal_unavailable']},Erec_keV:null,observed:null};api=async()=>featureReply(371,0,failedFeature);$('event').value='371';showEvent(1);`);
  await Promise.resolve();await Promise.resolve();
  assert.match(featureText(get('feature-content')),/native_transport_failed.*readout_unavailable.*full_signal_unavailable/);
  assert.match(featureText(get('feature-content')),/Filtered current peak · declared polarity · nA Unavailable/);
  assert.doesNotMatch(featureText(get('feature-content')),/Filtered current peak · declared polarity · nA 0/);
  for(const mutation of ["primary_id:121","group_id:1","configuration_sha256:'d'.repeat(64)","profile_sha256:'d'.repeat(64)","bundle_sha256:'d'.repeat(64)"]){
    assert.throws(()=>run(`featureIdentity({...featureReply(),${mutation}},featureSelection())`),/differ|changed/);
  }
  for(const mutation of ["global_initial_id:121","event_id:371","batch_index:0","local_initial_id:371","origin_time_ns:43"]){
    assert.throws(()=>run(`featureIdentity(featureReply(371,0,{...featureGroup,${mutation}}),featureSelection())`),/differ/);
  }
  assert.throws(()=>run('featureIdentity(featureReply(371,0,{...featureGroup,features:{...featureGroup.features,A_nA:0}}),featureSelection())'),/Invalid saved selection/);
  // Polarity-oriented A candidates and their original signed filtered value
  // have different labels; a -1 profile never silently rectifies the signal.
  run(`const inverseReply=featureReply(371,0,{...featureGroup,observed:{...featureGroup.observed,signed_filtered_current_peak_nA:.003,native_signed_current_at_peak_nA:-.003,declared_polarity:-1}});inverseReply.profile={...inverseReply.profile,polarity:-1};$('feature-content').replaceChildren();renderFeatures(inverseReply,featureSelection());`);
  assert.match(featureText(get('feature-content')),/Filtered current peak · declared polarity · nA 0\.003/);
  assert.match(featureText(get('feature-content')),/Filtered current at peak · original sign · nA -0\.003/);
  assert.match(featureText(get('feature-content')),/signed polarity -1/);
  // An old group response cannot replace a newer zero-primary response, a
  // different run, or a panel that the student closed while GET was pending.
  run(`let featurePending=[];api=path=>new Promise(resolve=>featurePending.push({path,resolve}));`);
  const oldFeature=run('loadFeatures()');
  get('event').value='372';run('showEvent();featurePending[1].resolve(featureReply(372,null,featureZero));');
  await Promise.resolve();await Promise.resolve();
  run('featurePending[0].resolve(featureReply());');await oldFeature;
  assert.match(get('feature-status').textContent,/Saved primary 372 · primary summary/);
  const closedFeature=run('loadFeatures()');get('feature-panel').open=false;get('feature-panel').ontoggle();
  run('featurePending[2].resolve(featureReply(372,null,featureZero));');await closedFeature;
  assert.equal(get('feature-content').children.length,0);
  get('feature-panel').open=true;const anotherRunFeature=run('loadFeatures()');
  run('showRun(savedJob);featurePending[3].resolve(featureReply(372,null,featureZero));');await anotherRunFeature;
  assert.equal(get('feature-content').children.length,0);assert.equal(run('result'),null);
  get('feature-panel').open=false;get('feature-panel').ontoggle();
  console.log('Browser saved PSD1 lazy eligibility/null/sign/topology/hash/selection/stale-response contracts, full-census hints and saved refresh/focus, source-angle/legacy Gamma, exact counts, checked/saved pose, batch Stop/Resume selection, paged boundary IDs/null/signs, stale Check/report/page/poll/focus, four saved plots and recovery contracts passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
