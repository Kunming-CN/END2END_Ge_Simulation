'use strict';
const $ = id => document.getElementById(id);
const token = location.hash.slice(1) || sessionStorage.getItem('ge-control-token') || '';
if (token) sessionStorage.setItem('ge-control-token', token);
history.replaceState(null, '', location.pathname);
window.addEventListener('hashchange',()=>{if(location.hash.slice(1)&&location.hash.slice(1)!==token)location.reload();});
let checked = '', busy = false, active = false, lastSnapshot = null;
const cards=new Map(), signatures=new Map();
const stateLabels = {preflight:'检查中',running:'运行中', 'stop-requested':'已请求停止 · 等待当前步骤',stop_requested:'已请求停止 · 等待当前步骤',stopped:'已停止 · 可以继续',paused:'已暂停 · 可以继续',cancelled:'已取消 · 尚未计算',blocked:'受阻',failed:'失败',completed:'完成',completed_with_native_failures:'处理完成 · 有 native 失败',queued:'等待中'};
function values(){return {name:$('name').value,detector:$('detector').value};}
function key(){return JSON.stringify(values());}
function message(text, error=false){$('notice').textContent=text;$('notice').className='message '+(error?'error':'ok');}
function controls(){ const blocked=busy||active||gammaBlocksLegacy();$('check').disabled=blocked;$('run').disabled=blocked||checked!==key();$('name').disabled=blocked;$('detector').disabled=blocked;gammaControls(); }
function resolved(){const d=$('detector').value;$('resolved').textContent=d==='AK02'?'AK02：3 个完整初级粒子，91 条原始 Ge 沉积行；固定 +500 V。':'SAP22：3 个完整初级粒子，33 条原始 Ge 沉积行（包含零能量行）；固定 +700 V。';}
async function api(path,data){const response=await fetch(path,{method:data?'POST':'GET',headers:{'X-Control-Token':token,...(data?{'Content-Type':'application/json'}:{})},...(data?{body:JSON.stringify(data)}:{}),cache:'no-store'});const result=await response.json();if(!response.ok)throw new Error(result.error||'本地操作失败');return result;}
function el(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
function btn(label,action){const b=el('button',label);b.addEventListener('click',async()=>{b.disabled=true;try{await action();await poll();}catch(e){message(e.message,true);}finally{if(b.isConnected)b.disabled=false;}});return b;}
function downloadLink(label,name,file){const a=el('a','下载'+label,'link');a.href='/api/file?'+new URLSearchParams({name,file});return a;}
function table(caption,heads,rows){const box=el('div',undefined,'table-scroll'),t=el('table');t.append(el('caption',caption));const h=el('tr');for(const name of heads)h.append(el('th',name));const head=el('thead');head.append(h);t.append(head);const body=el('tbody');for(const row of rows){const r=el('tr');for(const value of row)r.append(el('td',value==null?'未知 / 未定义':String(value)));body.append(r);}t.append(body);box.append(t);return box;}
// Fixed gamma jobs share dispatch activity, but never the preview or Cs137 identity.
const gammaFiles=['run.json','COMPLETE.json','AK02/request.json','AK02/report.json','AK02/calibration.json','AK02/truth-ledger.jsonl','AK02/signals.csv','SAP22/request.json','SAP22/report.json','SAP22/calibration.json','SAP22/truth-ledger.jsonl','SAP22/signals.csv'];
const gammaErrors={invalid_state:'Unsupported Gamma control state; preserve it for inspection.',incomplete_output:'Only existing completed Gamma receipts can be verified.',controller_failed:'Gamma action failed; inspect preserved local evidence.',unknown_job:'Unknown owned Gamma job.',invalid_threads:'Choose one or two Julia threads.',busy:'An owned calculation or input check is active. Wait before another action.',launcher_failed:'Gamma launcher failed; inspect preserved local evidence.',backend_refused:'Gamma input or receipt verification failed; inspect preserved local evidence.',uncertain_dispatch:'A prior Gamma driver has uncertain nested-worker lifetime. Preserve its output for owner inspection.',verification_required:'Verify the existing completed Gamma receipt before downloading.',download_refused:'Verified Gamma artifact is unavailable or changed.',invalid_check:'Check these fixed Gamma inputs before starting.',invalid_backend_receipt:'Gamma returned an unsupported receipt; inspect preserved local evidence.',output_exists:'The generated Gamma output already exists; no replacement was launched.'};
const gammaStatusLabels={'dispatch-uncertain':'启动状态未确定 · 等待人工检查',running:'运行中','verification-required':'完成记录待验证',completed:'完成并已验证',failed:'失败 · 保留证据',blocked:'受阻 · 等待人工检查'};
const gammaStageLabels={waiting:'等待模型记录',native_models:'native 电荷与电子学模型',verification:'完成记录核对',complete:'模型处理完成',failed:'计算失败',unknown:'阶段未确定'};
let gammaSupported=false,gammaState=null,gammaGlobalBusy=false,gammaPending=null,gammaInFlight=0,gammaGeneration=0,gammaCheck=null,pollGeneration=0;
const gammaStartedIds=new Set(),gammaVerifiedReceipts=new Map(),gammaCards=new Map();
function gammaRequire(condition){if(!condition)throw new Error('γ 响应未通过格式核对。');}
function gammaKeys(value,keys){gammaRequire(value!==null&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).sort().join('|')===[...keys].sort().join('|'));}
function gammaHex(value,length){return typeof value==='string'&&new RegExp('^[a-f0-9]{'+length+'}$').test(value);}
function gammaTime(value){return typeof value==='string'&&/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?\+00:00$/.test(value)&&Number.isFinite(Date.parse(value));}
function gammaNumber(value){return typeof value==='number'&&Number.isFinite(value)&&value>=0;}
function validateGammaJob(value){
 gammaKeys(value,['id','label','threads','status','created_at','updated_at','elapsed_seconds','progress','can_verify','verified','files','error','complete_sha256','run_sha256','calculation_seconds']);
 gammaRequire(gammaHex(value.id,32)&&value.label==='ui-gamma-'+value.id&&[1,2].includes(value.threads)&&Object.hasOwn(gammaStatusLabels,value.status)&&gammaTime(value.created_at)&&gammaTime(value.updated_at)&&gammaNumber(value.elapsed_seconds)&&typeof value.can_verify==='boolean'&&typeof value.verified==='boolean'&&(value.calculation_seconds===null||gammaNumber(value.calculation_seconds)));
 gammaKeys(value.progress,['completed_models','current_model','stage']);const progress=value.progress;
 gammaRequire(Array.isArray(progress.completed_models)&&JSON.stringify(progress.completed_models)===JSON.stringify(['AK02','SAP22'].slice(0,progress.completed_models.length))&&progress.completed_models.length<=2&&[null,'AK02','SAP22'].includes(progress.current_model)&&Object.hasOwn(gammaStageLabels,progress.stage));
 gammaRequire(Array.isArray(value.files)&&JSON.stringify(value.files)===JSON.stringify(value.verified?gammaFiles:[]));
 gammaRequire(value.verified?value.status==='completed'&&gammaHex(value.complete_sha256,64)&&gammaHex(value.run_sha256,64):value.complete_sha256===null&&value.run_sha256===null);
 let error=null;if(value.error!==null){gammaKeys(value.error,['code','message']);gammaRequire(Object.hasOwn(gammaErrors,value.error.code)&&value.error.message===gammaErrors[value.error.code]);error={code:value.error.code,message:value.error.message};}
 return {id:value.id,label:value.label,threads:value.threads,status:value.status,created_at:value.created_at,updated_at:value.updated_at,elapsed_seconds:value.elapsed_seconds,progress:{completed_models:[...progress.completed_models],current_model:progress.current_model,stage:progress.stage},can_verify:value.can_verify,verified:value.verified,files:[...value.files],error,complete_sha256:value.complete_sha256,run_sha256:value.run_sha256,calculation_seconds:value.calculation_seconds};
}
function validateGammaState(value){
 gammaKeys(value,['kind','active','jobs','checking','busy']);gammaRequire(value.kind==='gamma_local_control_state_v1'&&typeof value.checking==='boolean'&&typeof value.busy==='boolean'&&Array.isArray(value.jobs)&&value.jobs.length<=20);
 const jobs=value.jobs.map(validateGammaJob);gammaRequire(new Set(jobs.map(j=>j.id)).size===jobs.length);const current=value.active===null?null:validateGammaJob(value.active);
 gammaRequire(current===null||(['running','dispatch-uncertain'].includes(current.status)&&jobs.some(j=>JSON.stringify(j)===JSON.stringify(current))));gammaRequire(value.busy||(!current&&!value.checking));
 return {kind:value.kind,active:current,jobs,checking:value.checking,busy:value.busy};
}
function validateGammaCheck(value,threads){
 gammaKeys(value,['kind','status','threads','models','radiation_primaries','selected_primaries','unprocessed_primaries','native_calls','injection_calibrations','check_id']);
 gammaRequire(value.kind==='gamma_local_control_check_v1'&&value.status==='checked_no_execution'&&value.threads===threads&&JSON.stringify(value.models)==='["AK02","SAP22"]'&&value.radiation_primaries===40&&value.selected_primaries===6&&value.unprocessed_primaries===34&&value.native_calls===0&&value.injection_calibrations===0&&gammaHex(value.check_id,64));return {check_id:value.check_id,threads};
}
function gammaMessage(text,error=false){$('gamma-notice').textContent=text;$('gamma-notice').className='message '+(error?'error':'ok');}
function gammaThreads(){const choice=$('gamma-threads').value;return choice==='1'?1:choice==='2'?2:null;}
function gammaBlocksLegacy(){return gammaGlobalBusy||gammaInFlight>0;}
function gammaControls(){const blocked=!gammaSupported||busy||active||gammaState?.busy||gammaPending!==null;$('gamma-check').disabled=blocked;$('gamma-start').disabled=blocked||gammaInFlight>0||!gammaCheck||gammaCheck.threads!==gammaThreads();$('gamma-threads').disabled=busy||active||!!gammaState?.busy||['start','verify'].includes(gammaPending);}
function gammaReceiptKey(job){return job.complete_sha256+':'+job.run_sha256;}
function gammaCanDownload(job){return job.verified&&(gammaStartedIds.has(job.id)||gammaVerifiedReceipts.get(job.id)===gammaReceiptKey(job));}
function renderGammaJobs(){
 const box=$('gamma-jobs');if(!gammaSupported){box.textContent='新的 γ 控制状态不可用；没有可用的新结果下载。';gammaCards.clear();return;}const old=new Map(gammaCards);gammaCards.clear();box.replaceChildren();
 if(!gammaState.jobs.length){box.textContent='尚无新的 γ 计算。';return;}
 for(const job of gammaState.jobs){const card=el('article',undefined,'job'),title=el('strong','新 γ 结果 · '+job.label);title.append(el('span',gammaStatusLabels[job.status],'pill'));card.append(title);card.append(el('p','已观察模型：'+(job.progress.completed_models.join(' → ')||'尚无完成记录')+'；当前模型：'+(job.progress.current_model||'未记录')+'；阶段：'+gammaStageLabels[job.progress.stage]+'。实际经过时间 '+job.elapsed_seconds.toFixed(1)+' 秒；线程 '+job.threads+'。'));
  if(job.calculation_seconds!==null)card.append(el('p','保存的计算编排用时 '+job.calculation_seconds.toFixed(3)+' 秒；与页面开发、检查和审阅时间分别记录。'));
  if(job.error)card.append(el('p',job.error.code==='uncertain_dispatch'?'先前计算的子进程状态未确定；请保留证据并由所有者检查。':'此计算受阻或失败；本地证据已保留，请由所有者检查。','error'));
  const actions=el('div',undefined,'actions');if(job.can_verify){const verify=el('button',gammaCanDownload(job)?'重新验证此新结果':'验证此新保存结果');verify.disabled=busy||active||gammaPending!==null||gammaInFlight>0;verify.addEventListener('click',()=>verifyGamma(job.id));actions.append(verify);}card.append(actions);
  if(gammaCanDownload(job)){const downloads=el('details');downloads.open=old.get(job.id)?.querySelector('details')?.open||false;downloads.append(el('summary','已验证的新结果 · 12 个原始记录与信号下载'));downloads.append(el('p','新结果标识：'+job.label+'；完整真值与响应标记均保留。'));const links=el('div',undefined,'actions');for(const file of gammaFiles){const a=el('a','下载 '+file,'link');a.href='/api/gamma-file?'+new URLSearchParams({job_id:job.id,file});links.append(a);}downloads.append(links);downloads.append(el('p','COMPLETE SHA256：'+job.complete_sha256));downloads.append(el('p','run SHA256：'+job.run_sha256));card.append(downloads);}else if(['completed','verification-required'].includes(job.status))card.append(el('p','请明确验证此新保存结果，然后下载原始记录与信号。'));
  box.append(card);gammaCards.set(job.id,card);
 }
}
function gammaRefresh(){controls();renderGammaJobs();if(lastSnapshot)render(lastSnapshot,false);}
function receiveGammaState(value){try{gammaState=validateGammaState(value);gammaSupported=true;gammaGlobalBusy=gammaState.busy;if(gammaGlobalBusy)gammaCheck=null;}catch(e){gammaSupported=false;gammaCheck=null;gammaMessage('新的 γ 控制状态不可用或格式未获支持；请保留本地证据并检查。',true);}renderGammaJobs();}
function receiveGammaJob(job){const jobs=[job,...gammaState.jobs.filter(j=>j.id!==job.id)].slice(0,20),isActive=['running','dispatch-uncertain'].includes(job.status);gammaState={...gammaState,jobs,active:isActive?job:null,busy:gammaState.busy||isActive||jobs.some(j=>['blocked','verification-required','running','dispatch-uncertain'].includes(j.status)),checking:false};gammaGlobalBusy=gammaState.busy;gammaSupported=true;}
async function checkGamma(){
 if(!gammaSupported||busy||active||gammaState.busy||gammaPending!==null)return;const threads=gammaThreads();if(threads===null){gammaCheck=null;gammaMessage('请选择 1 或 2 个线程并重新检查。',true);gammaRefresh();return;}
 const generation=++gammaGeneration;gammaPending='check';gammaInFlight++;gammaCheck=null;gammaMessage('正在检查固定 γ 输入；不会启动计算。');gammaRefresh();
 try{const response=await api('/api/gamma-check',{threads});if(generation!==gammaGeneration)return;gammaCheck=validateGammaCheck(response,threads);gammaMessage('输入已核对：40 个真值、计划处理 6 个、34 个响应保持 null。此次检查 native 调用 0 次、注入校准 0 次；点击开始才计算。');}
 catch(e){if(generation!==gammaGeneration)return;gammaCheck=null;gammaMessage('固定 γ 输入暂不可用或未通过核对；没有启动计算，请手动重新检查。',true);}
 finally{gammaInFlight--;if(generation===gammaGeneration){gammaPending=null;gammaGeneration++;}gammaRefresh();}
}
async function startGamma(){
 if(!gammaSupported||busy||active||gammaState.busy||gammaPending!==null||gammaInFlight>0||!gammaCheck||gammaCheck.threads!==gammaThreads())return;
 const selection=gammaCheck,generation=++gammaGeneration;gammaCheck=null;gammaPending='start';gammaInFlight++;gammaMessage('正在请求开始一个新的固定 γ 计算；请等待后端确认。');gammaRefresh();
 try{const response=await api('/api/gamma-start',{check_id:selection.check_id});if(generation!==gammaGeneration)return;gammaKeys(response,['kind','job']);gammaRequire(response.kind==='gamma_local_control_start_v1');const job=validateGammaJob(response.job);gammaRequire(job.threads===selection.threads);gammaStartedIds.add(job.id);receiveGammaJob(job);gammaMessage('后端已记录新任务 '+job.label+'。仅显示已观察到的模型阶段和经过时间；此计算没有停止或继续功能。');}
 catch(e){if(generation!==gammaGeneration)return;gammaMessage('新的 γ 开始请求未获有效确认；请查看保存状态并保留证据。不会自动重试。',true);}
 finally{gammaInFlight--;if(generation===gammaGeneration){gammaPending=null;gammaGeneration++;}gammaRefresh();}
}
async function verifyGamma(id){
 const target=gammaState?.jobs.find(j=>j.id===id);if(!gammaSupported||busy||active||gammaPending!==null||gammaInFlight>0||!target?.can_verify)return;
 const generation=++gammaGeneration;gammaPending='verify';gammaInFlight++;gammaVerifiedReceipts.delete(id);gammaStartedIds.delete(id);gammaMessage('正在核对新结果 '+target.label+'；不会运行科学计算。');gammaRefresh();
 try{const response=await api('/api/gamma-verify',{job_id:id});if(generation!==gammaGeneration)return;gammaKeys(response,['kind','status','scientific_workers_launched','job']);gammaRequire(response.kind==='gamma_local_control_verify_v1'&&response.status==='verified'&&response.scientific_workers_launched===0);const job=validateGammaJob(response.job);gammaRequire(job.id===id&&job.threads===target.threads&&job.verified);receiveGammaJob(job);gammaVerifiedReceipts.set(id,gammaReceiptKey(job));gammaMessage('新结果 '+job.label+' 已通过保存记录与文件核对；科学计算调用 0 次。展开此任务的原始记录与信号下载。');}
 catch(e){if(generation!==gammaGeneration)return;gammaMessage('此新结果未通过有效核对；下载仍不可用。请保留本地证据并手动检查。',true);}
 finally{gammaInFlight--;if(generation===gammaGeneration){gammaPending=null;gammaGeneration++;}gammaRefresh();}
}
$('gamma-threads').addEventListener('change',()=>{if(['start','verify'].includes(gammaPending))return;gammaGeneration++;gammaPending=null;gammaCheck=null;gammaMessage('线程选择已更改，请重新检查固定 γ 输入。');gammaRefresh();});
$('gamma-check').addEventListener('click',checkGamma);$('gamma-start').addEventListener('click',startGamma);
// The fixed saved-gamma action is independent of preview selections and job state.
let savedGammaPending = false;
function savedGammaMessage(text,error=false){$('saved-gamma-notice').textContent=text;$('saved-gamma-notice').className='message '+(error?'error':'ok');}
function validateSavedGammaOpen(result){
 const keys=(value,expected)=>value!==null&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).sort().join('|')===[...expected].sort().join('|');
 if(!keys(result,['kind','status','science_calls','census'])||result.kind!=='saved_gamma_example_open_v1'||result.status!=='browser_open_requested'||result.science_calls!==0||!keys(result.census,['radiation_primaries','selected_primaries','unprocessed_primaries'])||result.census.radiation_primaries!==40||result.census.selected_primaries!==6||result.census.unprocessed_primaries!==34)throw new Error('保存示例打开响应未通过格式核对。');
}
async function openSavedGamma(){
 if(savedGammaPending)return;
 savedGammaPending=true;$('saved-gamma-open').disabled=true;savedGammaMessage('正在核对保存示例并请求打开；不会启动模拟。');
 try{const result=await api('/api/open-saved-gamma',{});validateSavedGammaOpen(result);savedGammaMessage('保存示例已通过核对，已请求浏览器打开。科学计算调用 0 次；浏览器是否显示尚未确认。');}
 catch(e){savedGammaMessage('保存示例暂不可用、未通过核对，或浏览器打开请求失败。请稍后手动重试；没有启动模拟。',true);}
 finally{savedGammaPending=false;$('saved-gamma-open').disabled=false;}
}
$('saved-gamma-open').addEventListener('click',openSavedGamma);
// This finite preview has no relationship to the saved-Cs137 launch state above.
const previewPresets = [
 ['m11a-ak02-cs137_point_decay_v1-nominal','AK02','cs137_point_decay_v1','nominal'],
 ['m11a-ak02-mono_gamma_662_axis_v1-plus5mm','AK02','mono_gamma_662_axis_v1','plus5mm'],
 ['m11a-sap22-cs137_point_decay_v1-nominal','SAP22','cs137_point_decay_v1','nominal'],
 ['m11a-sap22-mono_gamma_662_axis_v1-plus5mm','SAP22','mono_gamma_662_axis_v1','plus5mm']
];
let previewCatalog = null, selectedPreviewId = previewPresets[0][0], previewGeneration = 0;
function previewMessage(text,error=false){$('preview-notice').textContent=text;$('preview-notice').className='message '+(error?'error':'ok');}
function previewRequire(condition){if(!condition)throw new Error('配置预览未通过格式核对；请刷新重试。');}
function previewKeys(value,keys){previewRequire(value!==null&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).sort().join('|')===[...keys].sort().join('|'));}
function previewSame(value,expected){return JSON.stringify(value)===JSON.stringify(expected);}
function previewVector(value,expected){return Array.isArray(value)&&value.length===3&&value.every(Number.isFinite)&&previewSame(value,expected);}
function validatePreview(result){
 previewKeys(result,['kind','schema_version','configuration_status','read_only','scientific_workers_launched','scenarios']);
 previewRequire(result.kind==='finite_scenario_preview_v1'&&result.schema_version===1&&result.configuration_status==='checked'&&result.read_only===true&&result.scientific_workers_launched===0&&Array.isArray(result.scenarios)&&result.scenarios.length===4);
 const catalog=new Map(),sha=value=>typeof value==='string'&&/^[0-9a-f]{64}$/.test(value);
 for(const item of result.scenarios){
  previewKeys(item,['id','configuration_sha256','detector','cryostat','source_pose','source','planned_primary_count','seed','units','source_pose_status','model_check','stages']);
  const preset=previewPresets.find(p=>p[0]===item.id);previewRequire(!!preset&&!catalog.has(item.id)&&sha(item.configuration_sha256));
  const [,detectorId,sourceId,poseId]=preset,d=item.detector,s=item.source,ion=sourceId==='cs137_point_decay_v1';
  previewKeys(d,['id','model_sha256','temperature_K','contacts','readout_contact_id']);
  previewRequire(d.id===detectorId&&sha(d.model_sha256)&&d.temperature_K===78&&d.readout_contact_id===1&&Array.isArray(d.contacts)&&d.contacts.length===2);
  for(const contact of d.contacts)previewKeys(contact,['id','potential_V']);
  previewRequire(d.contacts[0].id===1&&d.contacts[0].potential_V===0&&d.contacts[1].id===2&&d.contacts[1].potential_V===(detectorId==='AK02'?500:700));
  previewKeys(item.cryostat,['id','capsule_axis_global']);previewRequire(item.cryostat.id==='lbnl_modular_nominal_v1'&&previewVector(item.cryostat.capsule_axis_global,[0,1,0]));
  previewKeys(item.source_pose,['id','position_global_mm']);previewRequire(item.source_pose.id===poseId&&previewVector(item.source_pose.position_global_mm,poseId==='nominal'?[0,37.073,0.290]:[0,42.073,0.290]));
  previewKeys(s,['id','particle','pdg',...(ion?['Z','A']:[]),'kinetic_energy_keV','angular_policy','direction_global','clock_policy','time_ns','normalization']);
  previewRequire(s.id===sourceId&&s.particle===(ion?'ion':'gamma')&&s.pdg===(ion?1000551370:22)&&(!ion||(s.Z===55&&s.A===137))&&s.kinetic_energy_keV===(ion?0:662)&&s.angular_policy===(ion?'radioactive_decay':'fixed_global_direction')&&(ion?s.direction_global===null:previewVector(s.direction_global,[0,-1,0]))&&s.clock_policy===(ion?'remage_initial_decay_secondaries_zero':'synthetic_primary_time_zero')&&s.time_ns===0&&s.normalization===(ion?'per initial Cs137 decay; conditional isolated windows, not activity/live time':'per one synthetic 662 keV incident gamma; no decay/activity normalization'));
  previewRequire(item.planned_primary_count===20&&item.seed===26092631);
  previewKeys(item.units,['length','time','energy','angle','potential','temperature']);
  previewRequire(item.units.length==='mm'&&item.units.time==='ns'&&item.units.energy==='keV'&&item.units.angle==='deg'&&item.units.potential==='V'&&item.units.temperature==='K');
  previewRequire(item.source_pose_status==="candidate until this preparation's native checks pass"&&item.model_check==='exact pinned bytes/reviewed metadata; independent YAML parse occurs only in prepare');
  previewKeys(item.stages,['geometry','source_macro','transport','charge','readout']);
  previewRequire(item.stages.source_macro==='not_prepared'&&['geometry','transport','charge','readout'].every(k=>item.stages[k]==='not_executed'));
  catalog.set(item.id,item);
 }
 previewRequire(previewPresets.every(p=>catalog.has(p[0])));return catalog;
}
function renderPreview(){
 const box=$('preview-fields');box.replaceChildren();const item=previewCatalog?.get(selectedPreviewId);if(!item)return;
 const ion=item.source.particle==='ion',fields=el('dl',undefined,'preview-fields');
 const rows=[
  ['探测器模型',item.detector.id+' · 78 K；接触 1：0 V（读出）；接触 2：+'+item.detector.contacts[1].potential_V+' V。此预览没有 77 K 缓存覆盖。'],
  ['源类型',ion?'Cs137 初始离子 · Z=55，A=137；初始动能 0 keV。这不表示发射辐射或沉积能量为零。':'单个合成 gamma · 初始能量 662 keV。'],
  ['源 / 胶囊中心位置','全局坐标 ['+item.source_pose.position_global_mm.join(', ')+'] mm · '+(item.source_pose.id==='nominal'?'名义位置':'相对名义位置沿 +y 移动 5 mm')+'；仍是候选位置。'],
  ['胶囊轴线','全局 ['+item.cryostat.capsule_axis_global.join(', ')+']；名义工程低温恒温器，未经实测装配确认。'],
  ['辐射方向',ion?'由放射性衰变决定；固定方向未定义。':'固定全局 ['+item.source.direction_global.join(', ')+']；与胶囊轴线分别记录。'],
  ['计划数量 / 种子','20 个初级粒子 · 种子 '+item.seed+'；仅为计划，未生成。与下方 3 个已保存初级粒子的示例不同。'],
  ['源时钟','0 ns · '+(ion?'初始衰变的次级粒子按条件窗口归零':'合成初级粒子创建时间归零')+'；源创建时间不等于载流子漂移时间。'],
  ['归一化',ion?'每个初始 Cs137 衰变；条件化的独立窗口，不表示活度或测量活时间。':'每个入射的合成 662 keV gamma；不使用衰变或活度归一化。'],
  ['单位','位置 mm · 时间 ns · 能量 keV · 角度 deg · 电势 V · 温度 K'],
  ['检查范围','仅核对模型原始字节与已审阅元数据；没有解析或求解 YAML。几何、辐射输运、电荷和读出均未执行；源宏尚未准备。此检查不构成物理精度、实验校准或完整几何执行验证。']
 ];
 for(const [label,value] of rows)fields.append(el('dt',label),el('dd',value));box.append(fields);
 const refs=el('details');refs.append(el('summary','配置与模型标识'));refs.append(el('p','配置：'+item.id));refs.append(el('p','配置 SHA256：'+item.configuration_sha256));refs.append(el('p','模型 SHA256：'+item.detector.model_sha256));box.append(refs);
}
function selectPreview(){
 const id=$('preview-select').value;
 if(!previewPresets.some(p=>p[0]===id)){previewCatalog=null;renderPreview();previewMessage('未知配置未显示；请从四个配置中选择并刷新。',true);return;}
 selectedPreviewId=id;renderPreview();
 if(previewCatalog)previewMessage('四个配置已核对。当前仅显示所选配置；没有执行任何计算。');
}
async function refreshPreview(){
 const generation=++previewGeneration;previewCatalog=null;renderPreview();previewMessage('正在核对四个配置；此前检查显示已清除。不会启动计算。');
 try{const result=await api('/api/scenarios');if(generation!==previewGeneration)return;const catalog=validatePreview(result);previewRequire(previewPresets.some(p=>p[0]===$('preview-select').value));selectedPreviewId=$('preview-select').value;previewCatalog=catalog;renderPreview();previewMessage('四个配置已核对。当前仅显示所选配置；没有执行任何计算。');}
 catch(e){if(generation!==previewGeneration)return;previewCatalog=null;renderPreview();previewMessage('配置预览暂不可用或未通过核对；请刷新重试。当前没有有效的检查显示。',true);}
}
$('preview-select').addEventListener('change',selectPreview);
$('preview-refresh').addEventListener('click',refreshPreview);
async function showEvents(job){const response=await fetch('/api/file?'+new URLSearchParams({name:job.name,file:'worker/'+job.detector+'/scalars.jsonl'}),{headers:{'X-Control-Token':token},cache:'no-store'});if(!response.ok)throw new Error((await response.json()).error);const lines=(await response.text()).trim().split('\n');const records=lines.map(line=>JSON.parse(line));const panel=el('div',undefined,'events');panel.append(el('p','全部初级粒子与全部脉冲组分别列出。Edep 是整个初级粒子的 Ge 真值沉积；Erec 属于单个读出组。两者不作为逐事件增益校准。真实零沉积没有伪造的 ADC / 波形。'));
 panel.append(table('初级粒子统计（包含真实零沉积）',['原始 ID','Ge Edep / keV','零沉积'],records.filter(r=>r.record_kind==='decay').map(r=>[r.global_decay_id,r.event.ge_energy_keV,r.zero_deposit])));
 panel.append(table('全部读出脉冲组',['原始 ID / 组','Erec / keV','状态','接受','尾部可能截断'],records.filter(r=>r.record_kind==='pulse').map(r=>[r.global_decay_id+' / '+r.group_id,r.readout?.reconstructed_energy_keV,r.status,r.accepted,r.readout?.tail_truncated_possible])));
 const details=el('details');details.append(el('summary','每条完整记录：原始沉积、时间、单位与所有标记'));for(const [index,record] of records.entries()){const d=el('details');d.append(el('summary',record.record_kind+' · ID '+record.global_decay_id+(record.group_id==null?'':' / group '+record.group_id)));d.append(el('pre',lines[index]));details.append(d);}panel.append(details);const card=cards.get(job.id);if(!card?.isConnected)return;card.querySelector('.events')?.remove();card.append(panel);
}
function render(snapshot,applyGamma=true){active=!!snapshot.active;if(applyGamma)receiveGammaState(snapshot.gamma);controls();const container=$('jobs');if(!snapshot.jobs.length){container.textContent='尚无任务。';return;}
 for(const child of [...container.childNodes])if(child.nodeType===Node.TEXT_NODE)child.remove();const present=new Set();let index=0;
 for(const job of snapshot.jobs){present.add(job.id);const signature=JSON.stringify([job,snapshot.active?.id||null,gammaBlocksLegacy()]);const old=cards.get(job.id);if(old&&signatures.get(job.id)===signature){if(container.children[index]!==old)container.insertBefore(old,container.children[index]||null);index++;continue;}
  const card=el('article',undefined,'job');const title=el('strong',job.name+' · '+(job.detector||'保存的设置'));title.append(el('span',stateLabels[job.status]||job.status,'pill'));card.append(title);
  const backend=job.backend||job.result||{};const stages=backend.stages||{};const counts=backend.completed_counts||stages.completed_counts||{};const expected=backend.expected_counts||stages.expected_counts||{};
  const progressText=['charge','calibration','electronics'].filter(k=>counts[k]!=null).map(k=>({charge:'电荷',calibration:'校准',electronics:'电子学'}[k])+': '+counts[k]+' / '+(expected[k]??'?')).join(' · ');if(progressText)card.append(el('p',progressText));
  const census=backend.selected_census;if(census)card.append(el('p','原始事件统计：'+[['initial_primaries','初级粒子'],['zero_ge_primaries','零沉积'],['nonzero_primaries','非零沉积'],['groups','脉冲组']].map(([k,label])=>label+' '+(census[k]??'未知')).join(' · ')));
  if(job.error)card.append(el('p',job.error.message||JSON.stringify(job.error),'error'));
  const actions=el('div',undefined,'actions');if(snapshot.active&&snapshot.active.id===job.id&&['preflight','running','queued'].includes(job.status))actions.append(btn('停止（当前步骤结束后）',()=>api('/api/stop',{job_id:job.id})));
  if(!snapshot.active&&job.can_resume&&['stopped','paused','failed','blocked'].includes(job.status)){const resume=btn('验证并继续此任务',()=>{if(!gammaBlocksLegacy()&&!busy&&!active)return api('/api/resume',{name:job.name});});resume.disabled=gammaBlocksLegacy();actions.append(resume);}
  if(['completed','completed_with_native_failures'].includes(job.status)){if(!job.complete_sha256){const verify=btn('验证已保存结果',()=>{if(!gammaBlocksLegacy()&&!busy&&!active)return api('/api/resume',{name:job.name});});verify.disabled=gammaBlocksLegacy();actions.append(verify);}else{actions.append(btn('查看全部事件结果',()=>showEvents(job)));for(const [label,file] of [['结果与标记','worker/'+job.detector+'/scalars.jsonl'],['完整保存波形','worker/'+job.detector+'/traces.jsonl'],['运行记录','run.json'],['设置与来源','manifest.json'],['完成凭据','COMPLETE.json']])actions.append(downloadLink(label,job.name,file));}}
  card.append(actions);const details=el('details');details.append(el('summary','记录 / 等价命令 / 输出位置'));details.append(el('p',job.output||''));if(job.runtime_choice)details.append(el('p','运行环境选择：'+job.runtime_choice.label+'；实际版本与程序字节由后端核对。'));details.append(el('pre',(job.command||[]).join(' ')));details.append(el('pre',(job.logs||[]).join('\n')||'等待后端记录。'));card.append(details);
  if(old){details.open=old.querySelector('details')?.open||false;const events=old.querySelector('.events');if(events)card.append(events);old.replaceWith(card);}else container.insertBefore(card,container.children[index]||null);cards.set(job.id,card);signatures.set(job.id,signature);index++;
 }
 for(const [id,card] of cards)if(!present.has(id)){card.remove();cards.delete(id);signatures.delete(id);}
}
async function poll(){const generation=++pollGeneration,gammaAtRequest=gammaGeneration;try{const s=await api('/api/state');if(generation!==pollGeneration)return;$('connection').textContent='已连接到本机 · 状态来自保存的后端记录';const applyGamma=gammaAtRequest===gammaGeneration&&gammaInFlight===0;if(JSON.stringify(s)!==JSON.stringify(lastSnapshot)){render(s,applyGamma);lastSnapshot=s;}else if(applyGamma){receiveGammaState(s.gamma);controls();}}catch(e){if(generation!==pollGeneration)return;$('connection').textContent=e.message+'；重开 Control.cmd 后使用新会话链接。';gammaSupported=false;gammaCheck=null;renderGammaJobs();controls();$('run').disabled=true;}}
for(const id of ['name','detector'])$(id).addEventListener('input',()=>{checked='';resolved();controls();message('设置已更改，请重新检查输入。');});
$('check').addEventListener('click',async()=>{if(busy||active||gammaBlocksLegacy())return;busy=true;controls();message('正在读取并验证输入；不会启动计算。');try{const r=await api('/api/check',values());if(!r.verification_final||r.status!=='planned')throw new Error((r.findings||[]).map(x=>x.message||JSON.stringify(x)).join('\n')||'输入未通过检查');checked=key();message('输入检查通过。点击“开始运行”才会计算；运行时还会核对软件与来源。');}catch(e){checked='';message(e.message,true);}finally{busy=false;controls();}});
$('run').addEventListener('click',async()=>{if(busy||active||gammaBlocksLegacy()||checked!==key())return;busy=true;controls();try{await api('/api/start',values());checked='';message('任务已明确启动。可以查看进度，或请求在当前步骤后停止。');await poll();}catch(e){message(e.message,true);}finally{busy=false;controls();}});
resolved();controls();poll();setInterval(poll,1000);
