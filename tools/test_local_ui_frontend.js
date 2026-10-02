'use strict';
// Bounded DOM fixture for independent saved-gamma opening, preview and result races.
// Mock/static checks do not establish browser/mobile/keyboard acceptance.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
  constructor(tag){this.tag=tag;this.children=[];this.parent=null;this.nodeType=1;this.className='';this._text='';this.open=false;this.handlers=new Map();}
  get textContent(){return this._text+this.children.map(n=>n.textContent).join('');}
  set textContent(text){this.replaceChildren();this._text=String(text);}
  get childNodes(){return this.children;}
  get isConnected(){return this.root===true||!!this.parent?.isConnected;}
  append(...nodes){for(const n of nodes){n.remove();n.parent=this;this.children.push(n);}}
  replaceChildren(...nodes){for(const child of [...this.children])child.remove();this._text='';this.append(...nodes);}
  remove(){if(this.parent){const a=this.parent.children;a.splice(a.indexOf(this),1);this.parent=null;}}
  insertBefore(n,before){n.remove();n.parent=this;const i=this.children.indexOf(before);this.children.splice(i<0?this.children.length:i,0,n);}
  replaceWith(n){const parent=this.parent;if(parent){parent.insertBefore(n,this);this.remove();}}
  querySelector(selector){return this.children.find(n=>selector[0]==='.'?n.className===selector.slice(1):n.tag===selector)||this.children.map(n=>n.querySelector(selector)).find(Boolean)||null;}
  addEventListener(type,handler){const handlers=this.handlers.get(type)||[];handlers.push(handler);this.handlers.set(type,handlers);}
  async dispatch(type){for(const handler of this.handlers.get(type)||[])await handler({target:this});}
}
const presets=[
 ['m11a-ak02-cs137_point_decay_v1-nominal','AK02',true,'nominal'],
 ['m11a-ak02-mono_gamma_662_axis_v1-plus5mm','AK02',false,'plus5mm'],
 ['m11a-sap22-cs137_point_decay_v1-nominal','SAP22',true,'nominal'],
 ['m11a-sap22-mono_gamma_662_axis_v1-plus5mm','SAP22',false,'plus5mm']
];
function catalog(){return {kind:'finite_scenario_preview_v1',schema_version:1,configuration_status:'checked',read_only:true,scientific_workers_launched:0,scenarios:presets.map(([id,detector,ion,pose])=>({
 id,configuration_sha256:'a'.repeat(64),
 detector:{id:detector,model_sha256:'b'.repeat(64),temperature_K:78,contacts:[{id:1,potential_V:0},{id:2,potential_V:detector==='AK02'?500:700}],readout_contact_id:1},
 cryostat:{id:'lbnl_modular_nominal_v1',capsule_axis_global:[0,1,0]},source_pose:{id:pose,position_global_mm:pose==='nominal'?[0,37.073,0.290]:[0,42.073,0.290]},
 source:{id:ion?'cs137_point_decay_v1':'mono_gamma_662_axis_v1',particle:ion?'ion':'gamma',pdg:ion?1000551370:22,...(ion?{Z:55,A:137}:{}),kinetic_energy_keV:ion?0:662,angular_policy:ion?'radioactive_decay':'fixed_global_direction',direction_global:ion?null:[0,-1,0],clock_policy:ion?'remage_initial_decay_secondaries_zero':'synthetic_primary_time_zero',time_ns:0,normalization:ion?'per initial Cs137 decay; conditional isolated windows, not activity/live time':'per one synthetic 662 keV incident gamma; no decay/activity normalization'},
 planned_primary_count:20,seed:26092631,units:{length:'mm',time:'ns',energy:'keV',angle:'deg',potential:'V',temperature:'K'},source_pose_status:"candidate until this preparation's native checks pass",model_check:'exact pinned bytes/reviewed metadata; independent YAML parse occurs only in prepare',stages:{geometry:'not_executed',source_macro:'not_prepared',transport:'not_executed',charge:'not_executed',readout:'not_executed'}
}))};}
function deferred(){let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};}
function jsonResponse(result,ok=true){return {ok,json:async()=>result};}
function savedGammaResponse(){return {kind:'saved_gamma_example_open_v1',status:'browser_open_requested',science_calls:0,census:{radiation_primaries:40,selected_primaries:6,unprocessed_primaries:34}};}
function fixture(){
  const elements=Object.fromEntries(['name','detector','notice','check','run','resolved','jobs','connection','preview-select','preview-refresh','preview-notice','preview-fields','saved-gamma-open','saved-gamma-notice'].map(k=>[k,new Element(k)]));
  for(const element of Object.values(elements))element.root=true;
  elements.detector.value='AK02';elements.name.value='fixture';elements['preview-select'].value=presets[0][0];
  const requests=[],queues=new Map(),intervals=[];
  const context=vm.createContext({document:{getElementById:id=>elements[id],createElement:tag=>new Element(tag)},
    location:{hash:'#fixture-token',pathname:'/'},sessionStorage:{getItem:()=>'',setItem(){}},history:{replaceState(){}},window:{addEventListener(){}},
    Node:{TEXT_NODE:3},URLSearchParams,fetch:(path,options)=>{requests.push({path,options});const queued=queues.get(path)?.shift();if(queued)return queued.promise;if(path==='/api/state')return Promise.resolve(jsonResponse({active:null,jobs:[]}));if(path==='/api/check')return Promise.resolve(jsonResponse({verification_final:true,status:'planned'}));if(path==='/api/start')return Promise.resolve(jsonResponse({}));throw new Error('Unqueued request: '+path);},setInterval(fn,ms){intervals.push({fn,ms});}});
  vm.runInContext(fs.readFileSync(__dirname+'/local_ui.js','utf8'),context);
  return {elements,context,requests,intervals,run:code=>vm.runInContext(code,context),queue:path=>{const pending=deferred(),queue=queues.get(path)||[];queue.push(pending);queues.set(path,queue);return pending;}};
}
async function savedResultRace(){
  const f=fixture(),{elements,context}=f;await f.run('poll()');
  const file='/api/file?name=saved&file=worker%2FAK02%2Fscalars.jsonl';
  const response=f.queue(file);
  const job={id:'same-id',name:'saved',detector:'AK02',status:'completed',complete_sha256:'verified',logs:[],backend:{selected_census:{initial_primaries:3,zero_ge_primaries:1,nonzero_primaries:2,groups:2}}};
  context.fixtureJob=job;
  vm.runInContext('render({active:null,jobs:[fixtureJob]})',context);
  const old=elements.jobs.children[0];
  const pending=vm.runInContext('showEvents(fixtureJob)',context);
  context.refreshedJob={...job,logs:['progress elsewhere changed']};
  vm.runInContext('render({active:{id:"other-job"},jobs:[refreshedJob]})',context);
  const current=elements.jobs.children[0];
  assert.notEqual(current,old);assert.equal(old.isConnected,false);
  const raw='{"record_kind":"decay","global_decay_id":9007199254740993,"event":{"ge_energy_keV":0},"zero_deposit":true}';
  response.resolve({ok:true,text:async()=>raw+'\n'});
  await pending;
  assert.equal(old.querySelector('.events'),null);
  assert.ok(current.querySelector('.events')?.isConnected);
  assert.equal(current.querySelector('.events').querySelector('pre').textContent,raw);
  assert.equal(current.querySelector('p').textContent,'原始事件统计：初级粒子 3 · 零沉积 1 · 非零沉积 2 · 脉冲组 2');
  // Removing a job while its response is pending must not attach to another job.
  const removal=f.queue(file),again=vm.runInContext('showEvents(fixtureJob)',context);
  vm.runInContext('render({active:null,jobs:[{id:"different-id",name:"other",status:"failed",logs:[]}]})',context);
  removal.resolve({ok:true,text:async()=>raw+'\n'});
  await again;
  assert.equal(elements.jobs.children[0].querySelector('.events'),null);
}
async function previewSelectionRace(){
 const f=fixture(),{elements}=f;await f.run('poll()');
 assert.equal(f.requests.filter(r=>r.path==='/api/scenarios').length,0,'preview requires manual refresh');assert.equal(f.intervals.length,1,'only existing job polling remains');
 const pending=f.queue('/api/scenarios'),refresh=elements['preview-refresh'].dispatch('click');
 assert.equal(elements['preview-fields'].children.length,0);
 elements['preview-select'].value=presets[3][0];await elements['preview-select'].dispatch('change');
 pending.resolve(jsonResponse(catalog()));await refresh;
 assert.equal(f.run('selectedPreviewId'),presets[3][0]);assert.match(elements['preview-fields'].textContent,/SAP22 · 78 K/);assert.match(elements['preview-fields'].textContent,/662 keV/);assert.match(elements['preview-fields'].textContent,/\[0, 42\.073, 0\.29\] mm/);assert.match(elements['preview-fields'].textContent,/\[0, -1, 0\]/);assert.match(elements['preview-fields'].textContent,/20 个初级粒子/);
 const old=f.queue('/api/scenarios'),oldRefresh=elements['preview-refresh'].dispatch('click');assert.equal(elements['preview-fields'].children.length,0,'old checked display clears immediately');
 const newer=f.queue('/api/scenarios'),newRefresh=elements['preview-refresh'].dispatch('click');
 elements['preview-select'].value=presets[0][0];await elements['preview-select'].dispatch('change');
 const latest=catalog();latest.scenarios[0].configuration_sha256='c'.repeat(64);newer.resolve(jsonResponse(latest));await newRefresh;
 elements['preview-select'].value=presets[2][0];await elements['preview-select'].dispatch('change');
 old.resolve(jsonResponse(catalog()));await oldRefresh;
 assert.equal(f.run('selectedPreviewId'),presets[2][0]);assert.equal(f.run('previewCatalog.get(previewPresets[0][0]).configuration_sha256'),'c'.repeat(64),'older response cannot replace newer catalog');assert.match(elements['preview-fields'].textContent,/初始动能 0 keV/);assert.match(elements['preview-fields'].textContent,/固定方向未定义/);assert.match(elements['preview-fields'].textContent,/源创建时间不等于载流子漂移时间/);
 assert.ok(f.requests.filter(r=>r.path==='/api/scenarios').every(r=>r.options.method==='GET'&&r.options.body===undefined&&r.options.headers['X-Control-Token']==='fixture-token'&&r.options.cache==='no-store'));
 assert.equal(f.requests.filter(r=>r.options.method==='POST').length,0);
}
async function previewRefusal(){
 const f=fixture(),{elements}=f;await f.run('poll()');
 async function deliver(result,ok=true){const response=f.queue('/api/scenarios'),pending=elements['preview-refresh'].dispatch('click');response.resolve(jsonResponse(result,ok));await pending;}
 await deliver(catalog());assert.ok(elements['preview-fields'].children.length);
 const response=f.queue('/api/scenarios'),pending=elements['preview-refresh'].dispatch('click');assert.equal(elements['preview-fields'].children.length,0);response.reject(new Error('private fixture path should not appear'));await pending;
 assert.equal(f.run('previewCatalog'),null);assert.doesNotMatch(elements['preview-notice'].textContent,/private fixture/);assert.match(elements['preview-notice'].textContent,/没有有效的检查显示/);
 const invalids=[
  c=>{c.scenarios.pop();},c=>{c.scenarios[1]=c.scenarios[0];},c=>{c.schema_version=2;},c=>{c.scenarios[0].id='unknown';},
  c=>{c.scenarios[1].source.Z=55;},c=>{c.scenarios[0].source.direction_global=[0,-1,0];},c=>{c.scenarios[0].detector.temperature_K=77;},
  c=>{c.scenarios[0].source_pose.position_global_mm[0]=NaN;},c=>{c.scenarios[0].stages.transport='completed';},c=>{c.scenarios[0].private_path='hidden';}
 ];
 for(const change of invalids){await deliver(catalog());const invalid=catalog();change(invalid);await deliver(invalid);assert.equal(f.run('previewCatalog'),null);assert.equal(elements['preview-fields'].children.length,0);assert.equal(elements['preview-notice'].className,'message error');}
 await deliver({error:'Scenario configuration preview is unavailable'},false);assert.equal(elements['preview-fields'].children.length,0);
 await deliver(catalog());elements['preview-select'].value='unknown';await elements['preview-select'].dispatch('change');assert.equal(f.run('previewCatalog'),null);assert.equal(elements['preview-fields'].children.length,0);assert.equal(f.run('selectedPreviewId'),presets[0][0]);
 const invalidSelection=f.queue('/api/scenarios'),invalidRefresh=elements['preview-refresh'].dispatch('click');invalidSelection.resolve(jsonResponse(catalog()));await invalidRefresh;assert.equal(f.run('previewCatalog'),null,'unknown live selection refuses response');
 // An older failure must also leave a newer checked catalog intact.
 elements['preview-select'].value=presets[0][0];await elements['preview-select'].dispatch('change');const old=f.queue('/api/scenarios'),oldRefresh=elements['preview-refresh'].dispatch('click'),latest=f.queue('/api/scenarios'),latestRefresh=elements['preview-refresh'].dispatch('click');latest.resolve(jsonResponse(catalog()));await latestRefresh;old.reject(new Error('stale failure'));await oldRefresh;assert.equal(f.run('previewCatalog.size'),4);assert.equal(elements['preview-notice'].className,'message ok');
}
async function legacyIsolation(){
 const f=fixture(),{elements}=f;await f.run('poll()');await elements.check.dispatch('click');
 const original=f.run('JSON.stringify({values:values(),checked,busy,active,runDisabled:$("run").disabled})');
 const preview=f.queue('/api/scenarios'),pending=elements['preview-refresh'].dispatch('click');elements['preview-select'].value=presets[3][0];await elements['preview-select'].dispatch('change');preview.resolve(jsonResponse(catalog()));await pending;
 assert.equal(f.run('JSON.stringify({values:values(),checked,busy,active,runDisabled:$("run").disabled})'),original,'gamma preview leaves launch identity and checked key intact');
 assert.deepEqual(f.requests.filter(r=>r.options.method==='POST').map(r=>r.path),['/api/check'],'preview selection/refresh never dispatches a legacy action');
 await elements.check.dispatch('click');await elements.run.dispatch('click');
 const posts=f.requests.filter(r=>r.options.method==='POST');assert.deepEqual(posts.map(r=>r.path),['/api/check','/api/check','/api/start']);for(const post of posts)assert.deepEqual(JSON.parse(post.options.body),{name:'fixture',detector:'AK02'});
 const html=fs.readFileSync(__dirname+'/local_ui.html','utf8'),section=html.match(/<section aria-labelledby="preview-title">([\s\S]*?)<\/section>/)[1];
 assert.deepEqual([...section.matchAll(/<option value="([^"]+)"/g)].map(m=>m[1]),presets.map(p=>p[0]));assert.equal([...section.matchAll(/<button /g)].length,1);assert.match(section,/配置预览 · 只检查，不执行/);assert.doesNotMatch(section,/id="(?:check|run|name|detector)"/);
}
async function savedGammaExplicitRequest(){
 const f=fixture(),{elements}=f;await f.run('poll()');
 for(const interval of f.intervals)await interval.fn();
 elements['preview-select'].value=presets[3][0];await elements['preview-select'].dispatch('change');
 const preview=f.queue('/api/scenarios'),refresh=elements['preview-refresh'].dispatch('click');preview.resolve(jsonResponse(catalog()));await refresh;
 assert.equal(f.requests.filter(r=>r.path==='/api/open-saved-gamma').length,0,'load, job polling, preview selection and refresh never open the saved example');
 assert.equal(f.intervals.length,1,'no new polling action');
 const response=f.queue('/api/open-saved-gamma'),pending=elements['saved-gamma-open'].dispatch('click');
 const requests=f.requests.filter(r=>r.path==='/api/open-saved-gamma');assert.equal(requests.length,1);
 assert.equal(requests[0].options.method,'POST');assert.equal(requests[0].options.body,'{}');assert.equal(requests[0].options.headers['X-Control-Token'],'fixture-token');assert.equal(requests[0].options.headers['Content-Type'],'application/json');assert.equal(requests[0].options.cache,'no-store');
 response.resolve(jsonResponse(savedGammaResponse()));await pending;
 assert.equal(elements['saved-gamma-open'].disabled,false);assert.equal(f.run('savedGammaPending'),false);assert.equal(elements['saved-gamma-notice'].className,'message ok');assert.match(elements['saved-gamma-notice'].textContent,/已请求浏览器打开/);assert.match(elements['saved-gamma-notice'].textContent,/科学计算调用 0 次/);assert.match(elements['saved-gamma-notice'].textContent,/是否显示尚未确认/);
 assert.equal(f.requests.filter(r=>r.options.method==='POST').length,1,'fixed saved action is the only POST');
 const html=fs.readFileSync(__dirname+'/local_ui.html','utf8'),section=html.match(/<section aria-labelledby="saved-gamma-title">([\s\S]*?)<\/section>/)[1];
 assert.equal([...section.matchAll(/<button /g)].length,1);assert.match(section,/id="saved-gamma-open">检查并打开保存的 γ 示例<\/button>/);assert.match(section,/id="saved-gamma-notice"[^>]*role="status" aria-live="polite"/);assert.match(section,/662 keV 合成 γ 名义工程示例/);assert.match(section,/40 个真值初级粒子.*6 个已处理.*34 个未处理且响应为空（null）/);assert.match(section,/不重新计算/);assert.match(section,/78 K.*77 K/);assert.match(section,/不是经校准的 Li 电荷收集效率或实验校准验证/);assert.doesNotMatch(section,/<(?:select|input|a|iframe|canvas)\b|(?:https?:|file:|\.local\/)|id="(?:check|run|name|detector|preview-select)"/);
}
async function savedGammaPendingIsolation(){
 const f=fixture(),{elements,context}=f;await f.run('poll()');await elements.check.dispatch('click');
 const legacyState=()=>f.run('JSON.stringify({values:values(),checked,busy,active,runDisabled:$("run").disabled,checkDisabled:$("check").disabled,notice:$("notice").textContent})');
 const original=legacyState(),response=f.queue('/api/open-saved-gamma'),pending=elements['saved-gamma-open'].dispatch('click');
 assert.equal(elements['saved-gamma-open'].disabled,true);assert.equal(f.run('savedGammaPending'),true);assert.equal(legacyState(),original,'pending only disables its own button');assert.match(elements['saved-gamma-notice'].textContent,/正在核对/);
 await elements['saved-gamma-open'].dispatch('click');assert.equal(f.requests.filter(r=>r.path==='/api/open-saved-gamma').length,1,'pending guard refuses duplicate dispatch');
 const preview=f.queue('/api/scenarios'),refresh=elements['preview-refresh'].dispatch('click');elements['preview-select'].value=presets[3][0];await elements['preview-select'].dispatch('change');preview.resolve(jsonResponse(catalog()));await refresh;
 const previewState=()=>f.run('JSON.stringify({selectedPreviewId,preview:[...previewCatalog],fields:$("preview-fields").textContent,notice:$("preview-notice").textContent})'),selected=previewState();assert.equal(legacyState(),original);
 for(const interval of f.intervals)await interval.fn();assert.equal(elements['saved-gamma-open'].disabled,true,'job polling cannot re-enable pending saved button');
 response.resolve(jsonResponse(savedGammaResponse()));await pending;assert.equal(legacyState(),original);assert.equal(previewState(),selected,'saved acknowledgement cannot reset or retarget preview');
 assert.equal(elements['saved-gamma-open'].disabled,false);assert.equal(f.run('selectedPreviewId'),presets[3][0]);
 // Active legacy jobs affect their own controls, not this completed-file action.
 context.activeSnapshot={active:{id:'working'},jobs:[]};f.run('render(activeSnapshot)');assert.equal(elements.check.disabled,true);assert.equal(elements.run.disabled,true);assert.equal(elements['saved-gamma-open'].disabled,false);
 const retry=f.queue('/api/open-saved-gamma'),opening=elements['saved-gamma-open'].dispatch('click');assert.equal(elements.check.disabled,true);retry.resolve(jsonResponse(savedGammaResponse()));await opening;assert.equal(f.run('active'),true);assert.equal(elements.check.disabled,true);assert.equal(elements['saved-gamma-open'].disabled,false);
}
async function savedGammaRefusalRecovery(){
 const f=fixture(),{elements}=f;await f.run('poll()');await elements.check.dispatch('click');
 const legacy=f.run('JSON.stringify({values:values(),checked,busy,active,runDisabled:$("run").disabled,notice:$("notice").textContent})');
 async function deliver(result,ok=true){const response=f.queue('/api/open-saved-gamma'),pending=elements['saved-gamma-open'].dispatch('click');response.resolve(jsonResponse(result,ok));await pending;}
 const invalids=[
  ()=>null,()=>[],r=>({...r,kind:'other'}),r=>({...r,status:'displayed'}),r=>({...r,science_calls:1}),r=>({...r,science_calls:'0'}),r=>({...r,census:[]} ),r=>({...r,census:{...r.census,radiation_primaries:39}}),r=>({...r,census:{...r.census,selected_primaries:'6'}}),r=>({...r,census:{...r.census,unprocessed_primaries:0}}),r=>({...r,private_uri:'file:///private-fixture'}),r=>({...r,census:{...r.census,path:'private-fixture'}}),r=>{delete r.status;return r;},r=>{delete r.census.unprocessed_primaries;return r;}
 ];
 for(const change of invalids){await deliver(savedGammaResponse());assert.equal(elements['saved-gamma-notice'].className,'message ok');await deliver(change(savedGammaResponse()));assert.equal(elements['saved-gamma-notice'].className,'message error');assert.doesNotMatch(elements['saved-gamma-notice'].textContent,/已请求浏览器打开|private-fixture|file:/);assert.equal(elements['saved-gamma-open'].disabled,false);assert.equal(f.run('savedGammaPending'),false);}
 for(const failure of ['Saved gamma example is unavailable','Saved gamma example open request failed','private fixture path should not appear']){await deliver({error:failure},false);assert.equal(elements['saved-gamma-notice'].className,'message error');assert.doesNotMatch(elements['saved-gamma-notice'].textContent,/private fixture/);assert.equal(elements['saved-gamma-open'].disabled,false);}
 const network=f.queue('/api/open-saved-gamma'),failed=elements['saved-gamma-open'].dispatch('click');network.reject(new Error('private fixture path should not appear'));await failed;assert.doesNotMatch(elements['saved-gamma-notice'].textContent,/private fixture/);assert.equal(elements['saved-gamma-open'].disabled,false);
 const parse=f.queue('/api/open-saved-gamma'),malformed=elements['saved-gamma-open'].dispatch('click');parse.resolve({ok:true,json:async()=>{throw new Error('private fixture malformed JSON');}});await malformed;assert.equal(elements['saved-gamma-notice'].className,'message error');assert.equal(elements['saved-gamma-open'].disabled,false);assert.doesNotMatch(elements['saved-gamma-notice'].textContent,/private fixture/);
 await deliver(savedGammaResponse());assert.equal(elements['saved-gamma-notice'].className,'message ok');assert.equal(f.run('JSON.stringify({values:values(),checked,busy,active,runDisabled:$("run").disabled,notice:$("notice").textContent})'),legacy,'success/failure/retry leave legacy check intact');
 assert.ok(f.requests.filter(r=>r.path==='/api/open-saved-gamma').every(r=>r.options.method==='POST'&&r.options.body==='{}'));assert.equal(f.requests.filter(r=>r.path==='/api/scenarios').length,0);assert.equal(f.requests.filter(r=>r.path==='/api/start'||r.path==='/api/resume').length,0);
}
async function savedGammaLegacyActions(){
 const f=fixture(),{elements,context}=f;await f.run('poll()');await elements.check.dispatch('click');
 const stale=f.queue('/api/scenarios'),oldRefresh=elements['preview-refresh'].dispatch('click'),latest=f.queue('/api/scenarios'),newRefresh=elements['preview-refresh'].dispatch('click');elements['preview-select'].value=presets[3][0];await elements['preview-select'].dispatch('change');latest.resolve(jsonResponse(catalog()));await newRefresh;
 const response=f.queue('/api/open-saved-gamma'),opening=elements['saved-gamma-open'].dispatch('click');elements['preview-select'].value=presets[2][0];await elements['preview-select'].dispatch('change');stale.reject(new Error('stale private preview failure'));await oldRefresh;response.resolve(jsonResponse(savedGammaResponse()));await opening;
 assert.equal(f.run('selectedPreviewId'),presets[2][0]);assert.equal(f.run('previewCatalog.size'),4);assert.equal(elements['preview-notice'].className,'message ok');assert.match(elements['preview-fields'].textContent,/SAP22 · 78 K/);
 await elements.run.dispatch('click');assert.deepEqual(f.requests.filter(r=>r.options.method==='POST').map(r=>[r.path,JSON.parse(r.options.body)]),[['/api/check',{name:'fixture',detector:'AK02'}],['/api/open-saved-gamma',{}],['/api/start',{name:'fixture',detector:'AK02'}]]);
 const paused={id:'paused-id',name:'legacy-paused',detector:'AK02',status:'paused',can_resume:true,logs:[]};context.paused=paused;f.run('render({active:null,jobs:[paused]})');const resume=f.queue('/api/resume'),resuming=elements.jobs.children[0].querySelector('button').dispatch('click');resume.resolve(jsonResponse({}));await resuming;assert.deepEqual(JSON.parse(f.requests.find(r=>r.path==='/api/resume').options.body),{name:'legacy-paused'});
 const job={id:'complete-id',name:'legacy-complete',detector:'AK02',status:'completed',complete_sha256:'verified',logs:[]};context.completed=job;f.run('render({active:null,jobs:[completed]})');const actions=elements.jobs.children[0].querySelector('.actions'),links=actions.children.filter(n=>n.tag==='a');assert.deepEqual(links.map(n=>n.href),['worker/AK02/scalars.jsonl','worker/AK02/traces.jsonl','run.json','manifest.json','COMPLETE.json'].map(file=>'/api/file?'+new URLSearchParams({name:'legacy-complete',file})));assert.equal(f.requests.filter(r=>r.path==='/api/open-saved-gamma').length,1,'legacy start/resume/download rendering never auto-opens');
}
async function main(){
 for(const [name,test] of [['saved-result races/raw records',savedResultRace],['preview selection/newest response',previewSelectionRace],['preview invalid/failure/unknown refusals',previewRefusal],['gamma/legacy isolation/static controls',legacyIsolation],['saved-gamma explicit fixed request/static copy',savedGammaExplicitRequest],['saved-gamma pending/preview/job isolation',savedGammaPendingIsolation],['saved-gamma schema/failure/manual recovery',savedGammaRefusalRecovery],['saved-gamma stale selection/legacy actions/downloads',savedGammaLegacyActions]]){await test();console.log('PASS: '+name);}
 console.log('PASS: 8 focused mock/static groups; actual browser/mobile/keyboard acceptance unperformed.');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
