'use strict';
const $=id=>document.getElementById(id);
const token=location.hash.slice(1)||sessionStorage.getItem('ge-control-token')||'';
if(token)sessionStorage.setItem('ge-control-token',token);history.replaceState(null,'',location.pathname);
let catalog=null,checked=null,noticeIsCheckedPlan=false,busy=false,active=false,selectedJob=null,selectedRun=null,result=null,selectionVersion=0,resultGeneration=0,plotGeneration=0;
let modelPreviewGeneration=0,modelPreviewUrl=null,importGeneration=0,pageGeneration=0,pollGeneration=0,featureGeneration=0,acquisitionGeneration=0,resultOptionsGeneration=0,spectrumGeneration=0;
let gegiResult=null,gegiGeneration=0,gegiJourney=null,gegiEventGeneration=0,gegiImagingGeneration=0,gegiDigitalGeneration=0;
let savedGeGIOptions=null,savedGeGIJob=null,savedGeGIBusy=false,savedGeGIGeneration=0;
let dualLibraries=[],dualJob=null,dualBusy=false,dualGeneration=0;
let candidateJob=null,candidateBusy=false,candidateGeneration=0,candidateEventGeneration=0,candidateOffset=0,candidatePage=null;
let candidateEstimateGeneration=0;
let candidatePlaneGeneration=0,candidateRangeRefresh=null;
let knownRuns=[],currentPage='new',currentTask='standard',runDetailKind='standard',resultTab='overview',waveformStage='charge',eventFindGeneration=0;
let runStatusNotice=null;
const continuationNames=new Map();
const pendingActions=new Map();
const stageNames={native_preparation:'Fields and injection calibration',geometry:'Geometry and source',radiation:'Radiation transport',event_ledger:'Event ledger',response:'Fields, charge, calibration and readout',results:'Verified results'};
const stateNames={dispatch_uncertain:'Inspection required',running:'Running',stop_requested:'Stop requested',stopped:'Stopped at stage boundary',completed:'Completed',completed_with_native_failures:'Completed with native failures',inspected_failure:'Inspected failure · preserved',verified_transport:'Verified transport · original failure preserved',launch_failed:'Not-launched failure · preserved'};
const labels={shaping_tau_us:['Shaping time','µs'],gain:['Shaper gain','V/V'],threshold_V:['Peak threshold','V'],adc_bits:['Peak ADC bits','bits'],adc_full_scale_V:['Peak ADC full scale','V'],feedback_capacitance_pF:['Feedback capacitance','pF'],feedback_tau_us:['Feedback decay','µs'],pole_zero_tau_us:['Pole-zero time','µs'],peak_policy:['Peak policy',''],peak_gate_start_ns:['Peak gate start','ns; blank = none'],peak_gate_end_ns:['Peak gate end','ns; blank = none']};
async function api(path,data){const r=await fetch(path,{method:data?'POST':'GET',headers:{'X-Control-Token':token,...(data?{'Content-Type':'application/json'}:{})},...(data?{body:JSON.stringify(data)}:{}),cache:'no-store'});const v=await r.json();if(!r.ok)throw Error(v.error||'Local action failed.');return v;}
function node(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
function showPage(page){
  currentPage=page;
  for(const panel of document.querySelectorAll('[data-page]'))panel.hidden=panel.dataset.page!==page;
  for(const button of document.querySelectorAll('[data-nav]'))button.setAttribute('aria-current',button.dataset.nav===page?'page':'false');
}
function showTask(task){
  currentTask=task;
  for(const panel of document.querySelectorAll('[data-task-panel]'))panel.hidden=panel.dataset.taskPanel!==task;
  for(const button of document.querySelectorAll('[data-task-choice]'))button.setAttribute('aria-pressed',String(button.dataset.taskChoice===task));
}
function openRunList(){
  showPage('runs');
  $('run-list-panel').hidden=false;
  $('run-detail').hidden=true;
  $('saved-analysis').hidden=true;
}
function openRunDetail(kind='standard'){
  runDetailKind=kind;
  showPage('runs');
  $('run-list-panel').hidden=true;
  $('run-detail').hidden=false;
  $('saved-analysis').hidden=true;
  $('standard-run-detail').hidden=kind!=='standard';
  $('gegi-acquisition-detail').hidden=kind!=='gegi';
  $('result').hidden=kind!=='standard'||result?.job.name!==selectedJob||result?.job.configuration_sha256!==selectedRun?.configuration_sha256;
  $('gegi-result').hidden=kind!=='standard'||gegiResult?.job.name!==selectedJob||gegiResult?.job.configuration_sha256!==selectedRun?.configuration_sha256;
}
function selectRun(job){
  showRun(job);
  renderJobs({busy:active,jobs:knownRuns});
  openRunDetail();
}
function uniqueRunName(base='simulation'){
  const stem=base.replace(/[^A-Za-z0-9_-]/g,'-').slice(0,40)||'simulation';
  const used=new Set(knownRuns.map(job=>job.name.toLowerCase()));
  let name=stem+'-01',suffix=1;
  while(used.has(name.toLowerCase()))name=stem+'-'+String(++suffix).padStart(2,'0');
  return name;
}
function initialCountLabel(selection){
  return ['mono_gamma_662_axis_v1','gegi_mono_gamma_v1'].includes(selection?.source)?'Incident photons':'Initial decays';
}
function showResultSummary(counts=result?.summaryCounts||result?.report?.counts||result?.job?.counts||{}){
  const selection=result?.job.selection||selectedRun?.selection;
  if(!selection)return;
  const initial=counts.initial_primaries??counts.initial_decays??selection.primary_count;
  const zero=counts.zero_deposit_primaries;
  const items=[
    [initialCountLabel(selection),initial],
    ['Zero deposition',zero],
    ['Nonzero deposition',counts.nonzero_primaries??(zero===undefined?undefined:initial-zero)],
    ['Pulse groups',counts.groups??counts.pulse_groups],
    ['Accepted readout',counts.accepted??counts.accepted_groups],
    ['Native failures',counts.native_failed_groups],
    ['Readout rejected',counts.readout_rejected],
    ['Saturated',counts.saturated??counts.saturated_groups]
  ];
  $('result-summary').replaceChildren(...featureMetrics(items.filter(([,value])=>value!==undefined)).children);
  $('event-find-status').textContent='Original event IDs: 0–'+(selection.primary_count-1)+'. Find opens the saved nonzero record, including other completed batches.';
}
function showResultTab(tab){
  resultTab=tab;
  for(const panel of document.querySelectorAll('[data-result-panel]'))panel.hidden=panel.dataset.resultPanel!==tab;
  for(const button of document.querySelectorAll('[data-result-tab]')){
    const selected=button.dataset.resultTab===tab;
    button.setAttribute('aria-selected',String(selected));
    button.tabIndex=selected?0:-1;
  }
  if(tab==='overview'&&result?.spectrum&&!$('spectrum-panel').hidden&&!$('spectrum-panel').open)$('spectrum-panel').open=true;
}
function showWaveformStage(stage=waveformStage){
  waveformStage=stage;
  let index=0;
  for(const figure of $('plots').children){
    if(figure.tagName.toLowerCase()!=='figure')continue;
    figure.dataset.waveformStage=['charge','current','preamp','shaper'][index++];
    figure.hidden=stage!=='all'&&figure.dataset.waveformStage!==stage;
  }
  for(const button of document.querySelectorAll('[data-waveform-stage]'))button.setAttribute('aria-pressed',String(button.dataset.waveformStage===stage));
}
function notice(text,error=false,checkedPlan=false){runStatusNotice=null;noticeIsCheckedPlan=checkedPlan;$('notice').textContent=text;$('notice').className='notice '+(error?'error':'okay');}
function showRunStatusNotice(job){
  notice('Run '+job.name+': '+(stateNames[job.status]||job.status)+'.');
  runStatusNotice={name:job.name,configuration_sha256:job.configuration_sha256,status:job.status};
}
function options(id,items,inspection=false){const s=$(id);s.replaceChildren();for(const item of items){const suffix=inspection?(item.available?' · Compute supported':item.block_code==='setup_required'?' · Setup required':item.block_code==='cryostat_size'?' · Needs larger cryostat':' · View only'):item.available===false?' · '+item.reason:'';const o=node('option',item.label+suffix);o.value=item.id;o.disabled=!inspection&&item.available===false;s.append(o);}}
function detectorFits(d,cryostat=$('cryostat').value){return !d?.assemblies?.length?cryostat!=='gegi_cryostat_v1':d.assemblies.includes(cryostat);}
function setupRequired(detector=currentDetector()){
  return detector?.block_code==='setup_required'&&detectorFits(detector);
}
function showSetupGuidance(detector){
  $('setup-required').hidden=!setupRequired(detector);
  if(catalog.setup_guide){
    $('guide').href=catalog.setup_guide;
    $('setup-required-guide').href=catalog.setup_guide;
  }
}
function detectorItems(){
  const items=catalog.detectors.map(detector=>detectorFits(detector)?detector:{
    ...detector,available:false,block_code:'cryostat_mismatch',reason:'Choose a compatible cryostat for this detector.'
  });
  if(!$('browse-catalog').checked){
    const ready=items.filter(detector=>detector.available===true);
    return ready.length?ready:items.filter(setupRequired);
  }
  return [...items.filter(detector=>detector.available===true),...items.filter(detector=>detector.available!==true)];
}
function sharedModelSelection(){return currentDetector()?.workflow_kind==='local_catalog_workflow_v1';}
function gegiSelection(){return currentDetector()?.workflow_kind==='local_gegi_workflow_v1';}
function selectDetector(preferred=$('detector').value){
  const items=detectorItems();
  options('detector',items,true);
  const choice=items.find(detector=>detector.id===preferred)||items[0];
  $('detector').value=choice?.id||'';
  detectorChanged();
}
function cryostatChanged(){selectDetector();}
function showModelRequirements(d){const list=$('model-parameters');list.replaceChildren();if(!d.parameter_summary?.length&&d.operating_label)list.append(node('li',d.operating_label));for(const p of d.parameter_summary||[]){const row=node('li',p.label+': '+String(p.value)+(p.unit?' '+p.unit:''));list.append(row);}const checks=$('model-checks');checks.replaceChildren();for(const c of d.checks||[]){checks.append(node('li',c.label+' · '+c.status+(c.detail?' · '+c.detail:'')));}$('model-requirements').hidden=!list.children.length&&!checks.children.length;}
function currentDetector(){return catalog?.detectors.find(d=>d.id===$('detector').value);}
function currentSource(){return catalog?.sources.find(s=>s.id===$('source').value);}
function executableSelection(){const d=currentDetector();return d?.available===true&&detectorFits(d)&&currentSource()?.available!==false&&d.sources.includes($('source').value)&&catalog.cryostats.some(c=>c.id===$('cryostat').value&&c.available===true);}
function batchSelection(){return !gegiSelection()&&currentSource()?.id!=='mono_gamma_662_axis_v1';}
function gammaCapability(source=currentSource()){const c=source?.gamma_controls;return source?.id==='mono_gamma_662_axis_v1'&&source.available!==false&&c?.enabled===true&&Number.isFinite(c.energy_keV?.default)&&c.energy_keV.default>0&&c.energy_keV.minimum_exclusive===0&&Array.isArray(c.source_poses)&&c.source_poses.includes(source.pose)&&c.source_poses.every(p=>['nominal','plus5mm'].includes(p))&&Array.isArray(c.direction_global)&&c.direction_global.length===3&&c.direction_global.every(Number.isFinite)&&c.time_ns===0?c:null;}
function gammaEnergy(){const text=$('gamma-energy-keV').value;if(typeof text!=='string'||text.trim()===''||!Number.isFinite(Number(text))||Number(text)<=0)throw Error('Gamma energy must be a finite positive number in keV.');return Number(text);}
function savedGammaEnergy(selection){return selection.gamma_energy_keV??662;}
function gammaFields(){const c=gammaCapability(),gegi=gegiSelection();$('gamma-controls').hidden=!c&&!gegi;$('gegi-source-controls').hidden=!gegi;$('gamma-energy-keV').disabled=!executableSelection()||!c&&!gegi;if(c&&!$('gamma-energy-keV').value)$('gamma-energy-keV').value=String(c.energy_keV.default);$('gamma-limit').textContent=gegi?'Enter gamma energy from 1 to 10000 keV. The GeGI plan records the source position in detector coordinates.':c?'Enter a finite positive energy in keV. Run uses the checked energy and existing source anchor; the global beam direction ['+c.direction_global.join(', ')+'] and creation time '+c.time_ns+' ns stay fixed.':'';}
function angleCapability(source=currentSource()){const c=source?.source_angle;return source?.id!=='mono_gamma_662_axis_v1'&&source?.available!==false&&c?.enabled===true&&Number.isFinite(c.min_deg)&&Number.isFinite(c.max_deg)?c:null;}
function sourceAngle(){if(gegiSelection())return 0;const text=$('angle-deg').value;if(typeof text!=='string'||text.trim()===''||!Number.isFinite(Number(text)))throw Error('Source angle must be a finite number of degrees.');const angle=Number(text),c=angleCapability();if(c?angle<c.min_deg||angle>c.max_deg:angle!==0)throw Error(c?'Source angle must be between '+c.min_deg+' and '+c.max_deg+' degrees.':'This source keeps its fixed position; source angle must be zero.');return angle;}
function angleFields(){const c=gegiSelection()?null:angleCapability();if(!c)$('angle-deg').value='0';else if(!$('angle-deg').value)$('angle-deg').value='0';$('angle-deg').min=c?.min_deg??0;$('angle-deg').max=c?.max_deg??0;$('angle-limit').textContent=c?(c.nonzero_execution_ready?'Supported source angle: ':'Geometry preview range: ')+c.min_deg+'° to '+c.max_deg+'°. '+c.convention+'. Check plan resolves the pose. '+(c.nonzero_execution_ready?'Run uses the checked pose. Geometry support across this range is not an experimental efficiency validation.':'Nonzero-angle Run is unavailable pending end-to-end acceptance.'):gammaCapability()?'Gamma uses the selected source anchor and fixed beam direction. Source angle is zero.':'This source keeps its legacy fixed position and direction. Source angle is zero.';}
function poseText(resolved,label){const s=resolved.selection||{};if(s.cryostat==='gegi_cryostat_v1')return label+' · '+(s.source==='gegi_mono_gamma_v1'?s.gamma_energy_keV+' keV':sourceLabel(s.source))+' · source detector xyz ['+(s.source_position_mm||[]).join(', ')+'] mm';const p=resolved.source_pose,g=resolved.gamma_source_configuration,position=g?.position_global_mm||p?.position_global_mm||resolved.source_position_global_mm;if(s.source==='mono_gamma_662_axis_v1')return label+' · '+(g?.energy_keV??savedGammaEnergy(s))+' keV · '+(g?.source_pose??s.pose??'legacy source')+' anchor'+(position?' · global ['+position.join(', ')+'] mm':' · saved position unavailable')+' · beam ['+(g?.direction_global||[0,-1,0]).join(', ')+'] · creation time '+(g?.time_ns??0)+' ns';return label+' · '+(p?'angle '+p.angle_deg+'°':s.angle_deg?'recorded angle '+s.angle_deg+'°; resolved pose unavailable':'legacy fixed pose')+(position?' · global ['+position.join(', ')+'] mm':' · saved position unavailable')+(p?.capsule_axis_global?' · capsule axis ['+p.capsule_axis_global.join(', ')+']':'')+(p?.coordinate_convention?' · '+p.coordinate_convention:'');}
function showPose(resolved=null){$('source-pose-preview').textContent=resolved?poseText(resolved,'Checked effective source pose'):executableSelection()?'Start simulation checks the source energy, angle and position.':'No executable source pose for this catalog model.';$('source-pose-identity').textContent=resolved?JSON.stringify({source_pose:resolved.source_pose||null,source_position_global_mm:resolved.source_position_global_mm,...(resolved.selection?.cryostat==='gegi_cryostat_v1'?{source_position_mm:resolved.selection.source_position_mm,gamma_energy_keV:resolved.selection.gamma_energy_keV}:{}),...(resolved.gamma_source_configuration?{gamma_source_configuration:resolved.gamma_source_configuration}:{})},null,2):'No checked source pose.';}
function exactInteger(text,label,positive=true){if(typeof text!=='string'||! /^[0-9]+$/.test(text))throw Error(label+' must be a decimal integer.');const n=Number(text);if(!Number.isSafeInteger(n)||n<(positive?1:0))throw Error(label+' is outside the exact safe-integer range.');return n;}
function batchRequest(selection){return {kind:'local_scenario_batch_request_v2',schema_version:2,selection};}
function sourcePosition(){return ['x','y','z'].map(axis=>{const text=$('gegi-source-'+axis).value;if(typeof text!=='string'||text.trim()===''||!Number.isFinite(Number(text)))throw Error('GeGI source coordinates must be finite values in mm.');return Number(text);});}
function config(){const electronics={};for(const key of catalog.electronics_keys){const value=$('setting-'+key).value;electronics[key]=key.startsWith('peak_gate_')&&!$('use-peak-gate').checked?null:key==='peak_policy'?value:value===''?null:Number(value);}const selection={name:$('name').value,cryostat:$('cryostat').value,detector:$('detector').value,source:$('source').value,pose:$('pose').value,primary_count:exactInteger($('count').value,'Initial count'),seed:Number($('seed').value),threads:Number($('threads').value),electronics},angle=sourceAngle();if(angle!==0)selection.angle_deg=angle;if(gammaCapability()||gegiSelection())selection.gamma_energy_keV=gammaEnergy();if(gegiSelection())selection.source_position_mm=sourcePosition();return selection;}
function invalidate(){
  selectionVersion++;
  checked=null;
  $('checked-plan').textContent=executableSelection()?'Settings will be checked before the simulation starts.':
    'No run plan for this setup. '+(currentDetector()?.reason||'Read the selected model’s configuration requirements.');
  if(noticeIsCheckedPlan)notice('Settings changed. Start simulation will check the current setup.');
  showSelection();showPose();controls();
}
function controls(){
  const runnable=executableSelection(),blocked=busy||active||!runnable||checked?.execution_enabled===false;
  for(const id of ['check','save'])$(id).disabled=busy||active||!runnable;
  $('load').disabled=busy||active;
  $('start').disabled=blocked;
  let readiness;
  if(busy)readiness='Checking or starting the simulation…';
  else if(active)readiness='Existing work is active or needs inspection. Open My runs for progress and available actions.';
  else if(setupRequired())readiness='Complete setup on this computer before starting a simulation.';
  else if(!runnable)readiness='Simulation unavailable. '+(currentDetector()?.available!==true?
    'View only · '+(currentDetector()?.reason||'No computation connector is available for this model.'):
    'This detector, source or cryostat combination is unavailable.')+' Choose a supported setup.';
  else if(checked?.execution_enabled===false)readiness='This setup cannot run yet: nonzero-angle acceptance is pending. Choose an admitted zero-angle setup.';
  else readiness='Start simulation checks the environment and settings, then starts this run.';
  if($('run-readiness').textContent!==readiness)$('run-readiness').textContent=readiness;
  for(const id of ['source','pose','count','threads','name','use-peak-gate'])$(id).disabled=!runnable;
  $('cryostat').disabled=busy||active;
  $('angle-deg').disabled=!runnable||!angleCapability()||gegiSelection();
  $('gamma-energy-keV').disabled=!runnable||!gammaCapability()&&!gegiSelection();
  for(const axis of ['x','y','z'])$('gegi-source-'+axis).disabled=!runnable||!gegiSelection();
  $('seed').disabled=!runnable||!batchSelection()&&currentSource()?.fixed_seed!=null;
  for(const key of catalog?.electronics_keys||[])$('setting-'+key).disabled=!runnable||key.startsWith('peak_gate_')&&!$('use-peak-gate').checked;
  savedGeGIControls();dualControls();candidateControls();
}
function sourceLabel(id){return id==='mono_gamma_662_axis_v1'?'Monoenergetic gamma beam':catalog?.sources.find(s=>s.id===id)?.label||id;}
function savedSourceLabel(selection){return sourceLabel(selection.source)+(['mono_gamma_662_axis_v1','gegi_mono_gamma_v1'].includes(selection.source)?' · '+savedGammaEnergy(selection)+' keV':'');}
function detectorChanged(){
  const previous=$('source').value,original=currentDetector();
  $('model-panel').hidden=!original;
  showSetupGuidance(original);
  if(!original){
    options('source',[]);options('pose',[]);
    $('model-capability').textContent='No compatible detector is available in this cryostat. Choose another cryostat or browse the full catalog.';
    invalidate();return;
  }
  const d=detectorFits(original)?original:{...original,available:false,sources:[],reason:'This detector requires a different cryostat. Select a compatible cryostat.'};
  const sources=catalog.sources.filter(source=>d.sources.includes(source.id)).map(source=>({...source,label:sourceLabel(source.id)}));
  options('source',sources.length?sources:setupRequired(d)?[{id:'',label:'Available after setup'}]:[]);
  $('source').value=sources.some(source=>source.id===previous)?previous:sources[0]?.id||'';
  if(gegiSelection()&&previous!=='gegi_mono_gamma_v1'){$('count').value='100';$('seed').value='26101701';}
  $('operating-details').textContent=d.operating_label||'';
  $('numerics').textContent=gegiSelection()?'GeGI numerical, seed and field-cache settings are recorded in the checked plan. Each native drift realization supplies all 34 contact signals.':catalog.numerics||'';
  showModel(d);sourceChanged();
}
function showModel(d){const m=d.model||{},count=catalog.detectors.filter(x=>x.available===true).length;
$('catalog-counts').textContent=catalog.detectors.length+' catalog models can be inspected; '+count+' have supported local computation connectors. The public website shows saved results.';
$('model-capability').textContent=d.available?'Ready for simulation in this cryostat.':setupRequired(d)?'Setup required on this computer.':'View only · '+(d.reason||'No executable configuration is available for this setup.');$('model-capability-details').textContent=d.reason||d.operating_label||'';
$('model-title').textContent=d.id;$('model-summary').textContent=[d.type_label,m.group,m.status,m.coordinate_system?m.coordinate_system+' coordinates':''].filter(Boolean).join(' · ');
$('model-contact-summary').textContent=(m.contacts||[]).length+' contacts · catalog readout contact '+(m.readout_contact_id??'unavailable');if($('model-contact-list').dataset.model!==d.id){$('model-contact-list').open=false;$('model-contact-list').dataset.model=d.id;}$('model-contacts').replaceChildren();$('model-contacts').tabIndex=(m.contacts||[]).length>8?0:-1;for(const c of m.contacts||[])$('model-contacts').append(node('li','Contact '+c.id+' · '+c.name+' · '+(c.potential_V>0?'+':'')+c.potential_V+' V'+(c.id===m.readout_contact_id?' · catalog readout':'')));
$('model-assumptions').textContent=(m.assumptions||[]).join(' ');$('model-variant').textContent=d.id==='GeRC02'?'Preview: frozen catalog Ge30min base. Computation: separate Li50min variant at 553.15 K; stored 78 K, runtime 77 K; fresh fields.':'';
showModelRequirements(d);$('model-identity').textContent=JSON.stringify(m,null,2);$('model-view').href=d.geometry_url||'';$('model-view').hidden=!d.geometry_url;loadModelPreview(d);}
async function loadModelPreview(detector){
  const generation=++modelPreviewGeneration;
  $('model-preview-fallback').hidden=true;
  $('model-preview-facts').replaceChildren();
  for(const item of (detector.parameter_summary||[]).slice(0,4)){
    $('model-preview-facts').append(node('p',item.label+': '+item.value+(item.unit?' '+item.unit:'')));
  }
  $('model-preview-facts').append(node('p',(detector.model?.contacts||[]).length+' electrical contacts'));
  if(modelPreviewUrl){URL.revokeObjectURL(modelPreviewUrl);modelPreviewUrl=null;}
  $('model-preview-box').hidden=true;
  $('model-preview').removeAttribute('src');
  $('model-preview-status').textContent='Loading saved catalog geometry…';
  try{
    const response=await fetch('/api/model-preview?'+new URLSearchParams({model:detector.id}),{headers:{'X-Control-Token':token},cache:'no-store'});
    if(!response.ok)throw Error('Saved preview unavailable.');
    const blob=await response.blob();
    if(generation!==modelPreviewGeneration||currentDetector()?.id!==detector.id)return;
    modelPreviewUrl=URL.createObjectURL(blob);
    $('model-preview').src=modelPreviewUrl;
    $('model-preview').alt=detector.id+' saved catalog geometry';
    $('model-preview-box').hidden=false;
    $('model-preview-status').textContent='';
  }catch(e){
    if(generation===modelPreviewGeneration){
      $('model-preview-fallback').hidden=false;
      $('model-preview-status').textContent='Saved geometry preview is unavailable in this package. The model parameters remain available.';
    }
  }
}
function showSelection(){if(!catalog)return;$('count-label').textContent=initialCountLabel({source:$('source').value});$('setup-preview').textContent=executableSelection()?'Current setup · '+$('detector').value+' · '+sourceLabel($('source').value)+(currentSource()?.id==='mono_gamma_662_axis_v1'?' · '+(gammaCapability()?$('gamma-energy-keV').value:662)+' keV · '+$('pose').value+' anchor':'')+' · '+$('count').value+' '+initialCountLabel({source:$('source').value}).toLowerCase()+' · '+$('threads').value+' Julia threads'+(angleCapability()?' · '+$('angle-deg').value+'° source angle':''):'Inspecting catalog model · '+$('detector').value+' · view only; no source or computation selected';}
function showRun(job){const changed=selectedJob!==job.name||selectedRun?.configuration_sha256!==job.configuration_sha256;if(changed){$('run-stage-details').open=['running','stop_requested'].includes(job.status);eventFindGeneration++;$('event-find-button').disabled=false;resultGeneration++;plotGeneration++;result=null;resetResultOptions();resetGeGIResult();$('result').hidden=true;$('plots').replaceChildren();clearSavedSelection();$('saved-artifacts').replaceChildren();}selectedJob=job.name;selectedRun=job;$('selected').textContent='Selected run · '+job.name+' · '+job.selection.detector+' · '+savedSourceLabel(job.selection)+' · '+job.selection.primary_count+' initial primaries';$('saved-source-pose').textContent=poseText(job,'Selected run source pose');$('run-plan').textContent=JSON.stringify({configuration_sha256:job.configuration_sha256,selection:job.selection,source_pose:job.source_pose||null,source_position_global_mm:job.source_position_global_mm,...(job.gamma_source_configuration?{gamma_source_configuration:job.gamma_source_configuration}:{})},null,2);stageList(job.stages,job.execution_contract==='serial_batches_v3');responseProgress(job);batchProgress(job);}
function sourceChanged(){const s=currentSource();gammaFields();angleFields();if(!s){options('pose',setupRequired()?[{id:'',label:'Available after setup'}]:[]);if(!$('count').value)$('count').value='500';$('source-details').textContent=setupRequired()?'Complete the setup guide to enable sources for this detector.':'A source cannot be selected until this detector has a checked computation connector.';$('source-identity').textContent='';invalidate();return;}if(gegiSelection()){options('pose',[{id:'custom',label:'Custom detector-coordinate position'}]);$('pose').value='custom';$('count').readOnly=false;$('count-limit').textContent='GeGI accepts 1–10000 initial gamma primaries per run. Start with 100; runtime and storage depend on the selected settings.';$('seed').disabled=false;$('angle-limit').textContent='GeGI uses the three recorded source coordinates. Capsule rotation does not apply.';$('source-details').textContent='Isotropic monoenergetic gamma point source. The count includes every emitted gamma, including misses. Use the two-source acquisition panel for fresh Cs-137 and Co-60 decays on one continuous readout clock.';$('source-identity').textContent=JSON.stringify({source_id:s.id,count_unit:'emitted gamma primaries',coordinate_system:'detector_xyz',position_unit:'mm',energy_unit:'keV',source_contract:s.source_contract},null,2);invalidate();return;}const gamma=gammaCapability(s);options('pose',gamma?gamma.source_poses.map(id=>({id,label:id==='nominal'?'Nominal source anchor':'+5 mm along global y'})):[{id:s.pose,label:s.pose_label||s.pose}]);$('pose').value=s.pose;const batching=batchSelection();$('count').readOnly=!batching;if(!batching)$('count').value=String(s.counts[0]);else if(!$('count').value)$('count').value='500';$('count-limit').textContent=batching?'Enter a positive integer.':'This gamma connector uses 20 photons and a fixed radiation seed.';$('seed').disabled=!batching&&s.fixed_seed!=null;if($('seed').disabled)$('seed').value=String(s.fixed_seed);$('source-details').textContent=[s.details||s.reason,s.count_unit?'Count unit: '+s.count_unit+'.':null,s.position_global_mm?(gamma?'Catalog default anchor':'Catalog fixed or zero-angle position')+' ['+s.position_global_mm.join(', ')+'] mm in the global frame.':null].filter(Boolean).join(' ');$('source-identity').textContent=JSON.stringify({source_id:s.id,count_unit:s.count_unit,position_global_mm:s.position_global_mm,source_angle:s.source_angle,gamma_controls:s.gamma_controls,source_contract:s.source_contract,acceptance:s.acceptance},null,2);invalidate();}

function electronics(){for(const key of catalog.electronics_keys){const [name,unit]=labels[key],label=node('label',name+(unit?' · '+unit:''));let input;if(key==='peak_policy'){input=node('select');for(const [value,text] of [['signed_input_positive_peak','Signed input, positive peak'],['legacy_reject_negative_input','Reject negative input']]){const o=node('option',text);o.value=value;input.append(o);}}else{input=node('input');input.type='number';input.step=key==='adc_bits'?'1':'any';}input.id='setting-'+key;label.htmlFor=input.id;input.value=catalog.electronics_defaults[key]??'';input.addEventListener('input',invalidate);label.append(input);$('electronics').append(label);}gateFields();}
function gateFields(){for(const key of ['peak_gate_start_ns','peak_gate_end_ns'])$('setting-'+key).disabled=!$('use-peak-gate').checked;}
$('use-peak-gate').onchange=()=>{gateFields();invalidate();};
function stageList(stages={},batched=false){$('pipeline').replaceChildren();const entries=batched?Object.keys(stages).map(key=>[key,stageNames[key]||key.replaceAll('_',' ')]):Object.entries(stageNames).filter(([key])=>key!=='native_preparation');for(const [key,title] of entries){const r=stages[key],row=node('div',undefined,'stage '+(r?.status||''));row.append(node('span',undefined,'dot'));const titleBox=node('div',title,'stage-title');titleBox.append(node('small',r?.reuse?(typeof r.original_elapsed_seconds==='number'?'Reused · originally '+r.original_elapsed_seconds.toFixed(2)+' s':'Reused · saved artifacts verified; original execution time unavailable'):typeof r?.elapsed_seconds==='number'?r.elapsed_seconds.toFixed(2)+' s observed':r?.status==='completed'?'Completed · saved receipt':'Waiting for execution'));row.append(titleBox,node('span',r?.reuse?'Reused':r?.status==='completed'?'Completed':r?.status?.replaceAll('_',' ')||'Pending','pill'));$('pipeline').append(row);}}
function batchProgress(job){const p=job.batch_progress;$('batch-progress').textContent=job.execution_contract==='serial_batches_v3'?(p?'Completed '+(p.completed_batch_count??0)+'/'+(p.batch_count??job.batching?.batch_count)+' batches · '+(p.completed_primary_count??0)+'/'+job.selection.primary_count+' initial primaries'+(Number.isInteger(p.active_batch_index)?' · active batch '+p.active_batch_index:'')+(p.active_stage?' · '+p.active_stage.replaceAll('_',' '):''):'Checked serial plan · '+job.batching?.batch_count+' batches · '+job.selection.primary_count+' initial primaries · awaiting the first receipt'):'';}
function responseProgress(job){const p=job.response_progress;$('response-progress').textContent=p?'Native stage: '+p.stage.replaceAll('_',' ')+' · '+p.status+(p.expected_primary_count!==null?' · '+p.completed_primary_count+'/'+p.expected_primary_count+' original primaries':'')+' · '+p.elapsed_seconds.toFixed(2)+' s observed':'';}
function action(label,fn,key=label){const b=node('button',label);b.dataset.renderKey='action:'+key;b.runAction=fn;b.onclick=async()=>{const actionKey=b.runActionKey||b;if(b.disabled||pendingActions.has(actionKey))return;const focused=document.activeElement===b;pendingActions.set(actionKey,b);b.disabled=true;try{await b.runAction();await poll();}catch(e){notice(e.message,true);}finally{const current=pendingActions.get(actionKey);pendingActions.delete(actionKey);if(current?.isConnected){current.disabled=false;if(current===b&&focused&&document.activeElement===document.body)current.focus({preventScroll:true});}}};return b;}
// Reconcile only these polled lists. Keep surviving controls in place; merely
// appending an existing focused node again would also lose browser focus.
function runKey(n,key){n.dataset.renderKey=key;return n;}
function visitRunNodes(n,fn){fn(n);for(const child of n.children)visitRunNodes(child,fn);}
function bindRunActions(card){visitRunNodes(card,n=>{if(n.runAction){n.runActionKey=card.dataset.renderKey+'/'+n.dataset.renderKey;n.disabled=pendingActions.has(n.runActionKey);}});}
function syncRunNode(current,next){
  if(current.className!==next.className)current.className=next.className;
  if(next.runAction){current.runAction=next.runAction;current.runActionKey=next.runActionKey;current.disabled=pendingActions.has(current.runActionKey);if(current.disabled)pendingActions.set(current.runActionKey,current);}
  if(next.tagName.toLowerCase()==='input'){current.id=next.id;current.maxLength=next.maxLength;current.oninput=next.oninput;return;}
  if(next.tagName.toLowerCase()==='label')current.htmlFor=next.htmlFor;
  if(!next.children.length){if(current.textContent!==next.textContent)current.textContent=next.textContent;return;}
  syncRunChildren(current,next);
}
function syncRunChildren(current,next){
  const old=[...current.children],keyed=new Map(old.filter(n=>n.dataset.renderKey).map(n=>[n.dataset.renderKey,n]));
  if(!old.length)current.textContent='';
  const desired=[...next.children].map((n,index)=>{const previous=n.dataset.renderKey?keyed.get(n.dataset.renderKey):old[index]?.dataset.renderKey?null:old[index];if(previous&&previous.tagName===n.tagName){syncRunNode(previous,n);return previous;}if(n.runAction&&pendingActions.has(n.runActionKey))pendingActions.set(n.runActionKey,n);return n;});
  for(const [index,n]of desired.entries())if(current.children[index]!==n)current.insertBefore(n,current.children[index]||null);
  for(const n of [...current.children])if(!desired.includes(n))current.removeChild(n);
}
function syncRunList(container,cards,emptyText=''){
  const focused=document.activeElement,inside=focused&&container.contains(focused),caret=inside&&Number.isInteger(focused.selectionStart)?[focused.selectionStart,focused.selectionEnd,focused.selectionDirection]:null;
  const next=node('div');next.append(...cards);syncRunChildren(container,next);if(!cards.length&&container.textContent!==emptyText)container.textContent=emptyText;
  visitRunNodes(container,n=>{if(n.runAction&&pendingActions.has(n.runActionKey))pendingActions.set(n.runActionKey,n);});
  // Reordering may require a DOM move. Restore only the same surviving control,
  // never an unavailable action or another run's similarly labelled button.
  if(inside&&focused.isConnected&&!focused.disabled&&document.activeElement!==focused){focused.focus({preventScroll:true});if(caret)focused.setSelectionRange(...caret);}
}
async function artifact(name,file,rawDownload=false){const r=await fetch('/api/workflow-file?'+new URLSearchParams({name,file,...(rawDownload?{download:'1'}:{})}),{headers:{'X-Control-Token':token},cache:'no-store'});if(!r.ok){const e=await r.json();throw Error(e.error||'Artifact unavailable.');}return r;}
async function download(name,file){const r=await artifact(name,file,true),blob=await r.blob(),url=URL.createObjectURL(blob),a=node('a');a.href=url;a.download=name+'-'+file.replaceAll('/','-');a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
async function openLogFile(name,file,label){const response=await artifact(name,file),bytes=new Uint8Array(await response.arrayBuffer());const text=new TextDecoder(bytes[1]===0||bytes[0]===255&&bytes[1]===254?'utf-16le':'utf-8').decode(bytes);$('log-title').textContent=name+' · '+label;$('log-text').textContent=text;$('log-view').hidden=false;$('log-view').scrollIntoView({behavior:'smooth'});}
async function openLog(name,stage){return openLogFile(name,stage+'.log',stageNames[stage]||stage);}
function renderLegacy(state){const cards=[],held=(state.gamma?.jobs||[]).filter(j=>j.blocks_new_work===true);$('legacy-notice').hidden=!held.length;if(held.length){$('legacy-notice').textContent=held.some(j=>j.can_verify)?'Before starting another calculation, choose Verify saved completion in Previous saved jobs and recovery. This reads existing results only.':'Saved Gamma work needs verification or inspection before a new calculation. Verify saved completion is currently unavailable because its activity or uncertainty is unresolved, or its terminal files are incomplete. Open Help → Research tools for the saved job and recorded error.';}for(const job of state.gamma?.jobs||[]){const row=runKey(node('div',undefined,'run'),'gamma:'+JSON.stringify(job.id??job.label));row.append(node('strong','Saved gamma · '+job.label),node('p',job.status));if(job.error)row.append(node('p',job.error.message,'muted'));if(job.can_verify)row.append(action('Verify saved completion',()=>api('/api/gamma-verify',{job_id:job.id})));else if(job.blocks_new_work===true)row.append(node('p','Verify saved completion reads terminal results only. It stays unavailable while this saved job’s activity, uncertainty or incomplete output is unresolved.','muted'));bindRunActions(row);cards.push(row);}for(const job of state.jobs||[]){const row=runKey(node('div',undefined,'run'),'native:'+job.name);row.append(node('strong','Saved native example · '+job.name),node('p',job.status+' · retained history'));cards.push(row);}syncRunList($('legacy-runs'),cards);$('legacy-recovery').hidden=!cards.length;if(!cards.length)$('legacy-recovery').open=false;}
function renderJobs(state){
  active=state.busy;
  if(runStatusNotice){
    const job=state.jobs.find(job=>job.name===runStatusNotice.name&&job.configuration_sha256===runStatusNotice.configuration_sha256);
    if(job&&job.status!==runStatusNotice.status)showRunStatusNotice(job);
  }
  knownRuns=state.jobs;if(!knownRuns.some(job=>job.name===selectedJob))selectedJob=knownRuns.at(-1)?.name??null;
  const cards=[],detailCards=[];
  for(const job of [...state.jobs].reverse()){
    const card=runKey(node('div',undefined,'run'),'workflow:'+JSON.stringify([job.name,job.configuration_sha256]));
    card.append(node('strong',job.name+' · '+job.selection.detector),node('p',savedSourceLabel(job.selection)+' · '+job.selection.primary_count+' primaries · '+(stateNames[job.status]||job.status)));
    if(job.error)card.append(node('p',job.error,'error'));
    card.append(action('View stages',()=>{$('run-stage-details').open=true;showRun(job);}),action('Copy as new run',()=>copyAsNewRun(job)));
    if(['running','stop_requested'].includes(job.status))card.append(action(job.execution_contract==='serial_batches_v3'?'Stop at next boundary':'Stop after current stage',()=>api('/api/workflow/stop',{name:job.name})));
    if(job.status==='stopped')card.append(action('Resume saved settings',()=>api('/api/workflow/resume',{name:job.name})));
    if(job.can_verify_saved_execution)card.append(node('p','After a CLI Resume finishes or stops at a new sealed boundary, verify its saved execution here. This checks existing results and preserves the original failed launch evidence.','muted'),action('Verify saved execution',async()=>{const next=await api('/api/workflow/verify',{name:job.name});showRun(next);notice('Saved execution verified. The original failed launch evidence is preserved.');},'workflow-verify'));
    if(['completed','completed_with_native_failures'].includes(job.status)||job.execution_contract==='serial_batches_v3'&&job.status==='stopped'&&job.batch_progress?.completed_batch_count>0){const open=action('Open results',()=>openResult(job));open.className='primary';card.append(open,action('Download settings',()=>download(job.name,'resolved-config.json')),action('Download run receipt',()=>download(job.name,'run.json')));}
    if(job.status==='dispatch_uncertain'){
      if(job.can_recover_launch)card.append(node('p','The saved launch record proves process creation was never invoked. Recovery checks the evidence and preserves its plan, error and logs. A failed new run needs a new name; a failed Resume returns to its unchanged sealed boundary.','muted'),action('Recover not-launched failure',async()=>{const next=await api('/api/workflow/recover-launch',{name:job.name});showRun(next);notice(next.status==='stopped'?'The unchanged sealed boundary is available for Resume. The failed launch evidence stays saved.':'Failed launch evidence preserved. Check a new run name to continue.');}));
      else{if(!job.can_verify_saved_execution)card.append(action('Verify existing completion',()=>api('/api/workflow/verify',{name:job.name}),'workflow-verify'));if(job.can_inspect_failure!==false)card.append(action('Inspect denied launch',()=>api('/api/workflow/inspect-failure',{name:job.name})));}
    }
    if(job.status==='launch_failed')card.append(node('p','No calculation started. Original launch evidence is preserved; Check a new run name to continue.','muted'));
    if(job.can_finalize_results)card.append(node('p','The response worker finished. Finalize saved results verifies existing science, preserves the original failed receipt and creates the results page. No simulation is repeated.','muted'),action('Finalize saved results',async()=>{const next=await api('/api/workflow/finalize-results',{name:job.name});showRun(next);notice('Saved results verified and finalized. Original science and compute timings were preserved.');}));
    if(job.can_continue_prefix){
      const label=runKey(node('label','New run name for '+job.name),'continuation-name'),input=runKey(node('input'),'continuation-input');
      input.id='continue-name-'+job.id;label.htmlFor=input.id;input.maxLength=48;
      input.value=continuationNames.get(job.name)??job.name+'-continued';
      input.oninput=function(){continuationNames.set(job.name,this.value);};label.append(input);
      card.append(node('p','Keep this run’s detector, source and electronics settings. Reuse verified transport; calculate charge and readout in a new run.','muted'),label,
        action('Continue from verified transport',async()=>{const next=await api('/api/workflow/continue-prefix',{name:job.name,new_name:$(input.id).value});showRun(next);notice('Reserved '+next.name+'. Verified transport is reused; response and results will run.');}));
    }
    const details=runKey(node('details'),'stage-details'),summary=runKey(node('summary','Stage receipts and logs'),'stage-summary');details.dataset.run=job.name;details.append(summary);
    for(const [stage,r]of Object.entries(job.stages)){details.append(node('p',(stageNames[stage]||stage.replaceAll('_',' '))+' · '+r.status));if(stage!=='results'&&job.execution_contract!=='serial_batches_v3')details.append(action('Open '+stage+' log',()=>openLog(job.name,stage),'stage-log:'+stage));}for(const log of job.logs||[])details.append(action('Open '+log.label+' log',()=>openLogFile(job.name,log.file,log.label),'saved-log:'+log.file));if(job.batch_progress)details.append(node('pre',JSON.stringify(job.batch_progress,null,2)));
    details.append(node('pre',JSON.stringify(job.stages,null,2)));card.append(details);bindRunActions(card);
    const row=runKey(node('div',undefined,'run run-row'),'workflow:'+JSON.stringify([job.name,job.configuration_sha256]));
    row.append(
      node('strong',job.name),
      node('p',job.selection.detector+' · '+savedSourceLabel(job.selection)+' · '+job.selection.primary_count+' '+initialCountLabel(job.selection).toLowerCase()),
      node('small',job.created_utc||'Saved creation time unavailable'),
      node('span',stateNames[job.status]||job.status,'pill'),
      action('Open run',()=>selectRun(job))
    );
    bindRunActions(row);cards.push(row);
    if(selectedJob===job.name)detailCards.push(card);
    if(selectedJob===job.name)showRun(job);
  }
  syncRunList($('runs'),cards,'No runs created in this application.');syncRunList($('run-detail-content'),detailCards);controls();
}
async function poll(){const generation=++pollGeneration;try{const [state,legacy]=await Promise.all([api('/api/workflow/state'),api('/api/state')]);if(generation!==pollGeneration)return;renderJobs(state);renderLegacy(legacy);if(savedGeGIJob)void pollSavedGeGI();if(dualJob?.status==='running')void inspectDualJob(dualJob.name);if(['running','stop_requested'].includes(candidateJob?.status)||candidateJob?.analysis?.status==='running'||candidateJob?.range_analysis?.status==='running')void inspectCandidateJob(candidateJob.name);}catch(e){if(generation===pollGeneration)notice(e.message,true);}}

function savedGeGIControls(){
  const hasInput=!!savedGeGIOptions?.campaigns?.some(c=>c.id===$('gegi-saved-campaign').value),status=savedGeGIJob?.status;
  $('gegi-saved-start').disabled=savedGeGIBusy||busy||active||!hasInput;
  $('gegi-saved-resume').disabled=savedGeGIBusy||busy||active||savedGeGIJob?.input_kind==='standalone'||savedGeGIJob?.resume_supported===false||!['interrupted','failed','stopped_saved_reconstruction'].includes(status);
  $('gegi-saved-stop').disabled=savedGeGIBusy||savedGeGIJob?.input_kind==='standalone'||savedGeGIJob?.stop_supported===false||status!=='running';
  $('gegi-saved-refresh').disabled=savedGeGIBusy;
}
function showSavedGeGI(job){
  savedGeGIJob=job;const progress=job.progress||{},counts=job.summary?.counts||progress.counts||{};
  $('gegi-saved-status').className='notice '+(job.status==='failed'?'error':'');
  $('gegi-saved-status').textContent=job.name+' · '+job.status.replaceAll('_',' ')+(progress.chunks!==undefined?' · '+progress.chunks+' completed chunks':'')+(counts.initial_primaries!==undefined?' · '+counts.initial_primaries+' initial primaries':'')+(counts.zero_deposit_primaries!==undefined?' · '+counts.zero_deposit_primaries+' zero-deposit':'')+(counts.nonzero_primaries!==undefined?' · '+counts.nonzero_primaries+' original nonzero primaries':'')+(counts.pulse_groups!==undefined?' · '+counts.pulse_groups+' original pulse groups':'')+(counts.conditional_candidate_groups!==undefined?' · '+counts.conditional_candidate_groups+' conditional candidate groups':'')+(counts.validated_recovered_groups!==undefined?' · '+counts.validated_recovered_groups+' validated recovered groups':'')+(job.capability_note?' · '+job.capability_note:'')+(job.error?' · '+job.error:'');
  $('gegi-saved-path').textContent='Saved derivative folder: '+job.output_path+'. '+(job.input_kind==='standalone'?'Original signals and stage files remain in .local/runs/'+job.source_run_name+'/. Original nonzero IDs, counts and failure records are retained.':'Chunk files retain original nonzero IDs; original campaign counts and failures remain in the summary.');
  $('gegi-saved-record').textContent=JSON.stringify(job,null,2);$('gegi-saved-files').replaceChildren();
  for(const file of (job.files||['identity.json','progress.json',...(job.summary?['summary.json','COMPLETE.json']:[])]).filter(file=>file!=='results.json')){
    const b=node('button','Open '+file);b.onclick=async()=>{try{const value=await api('/api/workflow/gegi-saved/file?'+new URLSearchParams({name:job.name,file}));if(savedGeGIJob?.name===job.name)$('gegi-saved-record').textContent=JSON.stringify(value,null,2);}catch(e){$('gegi-saved-status').textContent=e.message;}};$('gegi-saved-files').append(b);
  }
  if(job.input_kind==='standalone'&&job.status==='completed_conditional_reconstruction'){
    const b=node('button','Open reconstructed results');b.onclick=()=>openSavedGeGIResult(job);$('gegi-saved-files').append(b);
  }
  savedGeGIControls();
}
async function openSavedGeGIResult(job){
  resetGeGIResult();let generation=gegiGeneration;
  try{
    const [state,data]=await Promise.all([api('/api/workflow/state'),api('/api/workflow/gegi-summary?'+new URLSearchParams({name:job.source_run_name,derivative:job.name}))]);
    if(generation!==gegiGeneration||savedGeGIJob?.name!==job.name)return;
    const source=state.jobs.find(j=>j.name===job.source_run_name&&j.workflow_kind==='local_gegi_workflow_v1');
    if(!source)throw Error('The original owned GeGI run is unavailable. Refresh saved inputs.');
    if(data.saved_derivative_name!==job.name)throw Error('Saved GeGI reconstruction and selected derivative identities differ.');
    knownRuns=state.jobs;selectRun(source);const opening=openGeGIResult(source,data,job.name);generation=gegiGeneration;await opening;
  }catch(e){if(generation===gegiGeneration&&savedGeGIJob?.name===job.name)$('gegi-saved-status').textContent=e.message;}
}
async function pollSavedGeGI(){
  if(!savedGeGIJob)return;const name=savedGeGIJob.name,generation=++savedGeGIGeneration;
  try{const job=await api('/api/workflow/gegi-saved/state?'+new URLSearchParams({name}));if(generation===savedGeGIGeneration&&savedGeGIJob?.name===name)showSavedGeGI(job);}
  catch(e){if(generation===savedGeGIGeneration)$('gegi-saved-status').textContent=e.message;}
}
async function refreshSavedGeGI(){
  savedGeGIBusy=true;savedGeGIControls();
  try{
    const value=await api('/api/workflow/gegi-saved/options');if(value.kind!=='gegi_saved_options_v1'||!Array.isArray(value.campaigns)||!Array.isArray(value.calibrations)||!Array.isArray(value.jobs))throw Error('Unsupported saved GeGI inventory.');
    savedGeGIOptions=value;const selectedCampaign=$('gegi-saved-campaign').value,selectedCalibration=$('gegi-saved-calibration').value,selectedJob=savedGeGIJob?.name;
    options('gegi-saved-campaign',value.campaigns);options('gegi-saved-calibration',[{id:'',label:'None · unsupported depth remains unknown'},...value.calibrations]);
    if(value.campaigns.some(c=>c.id===selectedCampaign))$('gegi-saved-campaign').value=selectedCampaign;
    if(value.calibrations.some(c=>c.id===selectedCalibration))$('gegi-saved-calibration').value=selectedCalibration;
    options('gegi-saved-job',[{id:'',label:'Choose a saved derivative'},...value.jobs.map(j=>({id:j.name,label:j.name+' · '+j.status.replaceAll('_',' ')}))]);
    if(selectedJob&&value.jobs.some(j=>j.name===selectedJob))$('gegi-saved-job').value=selectedJob;
    if(!savedGeGIJob)$('gegi-saved-status').textContent=value.campaigns.filter(c=>c.input_kind==='standalone').length+' completed standalone runs, '+value.campaigns.filter(c=>c.input_kind!=='standalone').length+' completed sealed campaigns and '+value.calibrations.length+' saved template folders available. '+(value.campaigns.length?'Choose inputs and a new derivative name.':'Complete a GeGI run in Control or import saved campaign stores; no example data are bundled.');
  }catch(e){$('gegi-saved-status').textContent=e.message;}
  finally{savedGeGIBusy=false;savedGeGIControls();}
}
async function reprocessSavedGeGI(resume=false){
  if(resume&&(savedGeGIJob?.input_kind==='standalone'||savedGeGIJob?.resume_supported===false)){$('gegi-saved-status').textContent=savedGeGIJob.capability_note||'This saved reconstruction has no resume boundary.';return;}
  savedGeGIBusy=true;savedGeGIControls();
  try{
    const request=resume?{campaign_id:savedGeGIJob.campaign_id,calibration_id:savedGeGIJob.calibration_id,name:savedGeGIJob.name,resume:true}:{campaign_id:$('gegi-saved-campaign').value,calibration_id:$('gegi-saved-calibration').value,name:$('gegi-saved-name').value,resume:false};
    const job=await api('/api/workflow/gegi-saved/reprocess',request);showSavedGeGI(job);await poll();await refreshSavedGeGI();
  }catch(e){$('gegi-saved-status').textContent=e.message;}
  finally{savedGeGIBusy=false;savedGeGIControls();}
}
$('gegi-saved-refresh').onclick=refreshSavedGeGI;
$('gegi-saved-campaign').onchange=$('gegi-saved-calibration').onchange=savedGeGIControls;
$('gegi-saved-start').onclick=()=>reprocessSavedGeGI(false);$('gegi-saved-resume').onclick=()=>reprocessSavedGeGI(true);
$('gegi-saved-stop').onclick=async()=>{if(savedGeGIJob?.input_kind==='standalone'||savedGeGIJob?.stop_supported===false){$('gegi-saved-status').textContent=savedGeGIJob.capability_note||'This saved reconstruction has no stop boundary.';return;}savedGeGIBusy=true;savedGeGIControls();try{showSavedGeGI(await api('/api/workflow/gegi-saved/stop',{name:savedGeGIJob.name}));}catch(e){$('gegi-saved-status').textContent=e.message;}finally{savedGeGIBusy=false;savedGeGIControls();}};
$('gegi-saved-job').onchange=()=>{const job=savedGeGIOptions?.jobs.find(j=>j.name===$('gegi-saved-job').value);++savedGeGIGeneration;if(job){showSavedGeGI(job);void pollSavedGeGI();}else{savedGeGIJob=null;$('gegi-saved-record').textContent='No derivative selected.';$('gegi-saved-files').replaceChildren();$('gegi-saved-path').textContent='';savedGeGIControls();}};

function dualSourceIds(){return ['a','b'].map(side=>$('gegi-dual-source-'+side).value);}
function dualControls(){
  $('gegi-dual-start').disabled=dualBusy||busy||active||dualJob?.status==='running'||
    !dualSourceIds().every(id=>dualLibraries.some(library=>library.id===id));
  $('gegi-dual-refresh').disabled=dualBusy;
  $('gegi-dual-job').disabled=dualBusy;
}
function dualStatus(text,error=false){const target=$('gegi-dual-status');target.textContent=text;target.className='notice '+(error?'error':'okay');}
function setDualOptions(value,name){
  dualLibraries=value.libraries;
  const libraries=dualLibraries.map(item=>({id:item.id,label:item.isotope+' · ['+item.source_position_mm.join(', ')+'] mm · '+item.label}));
  for(const suffix of ['a','b']){
    const id='gegi-dual-source-'+suffix,prior=$(id).value;
    options(id,[{id:'',label:'Choose a library'},...libraries]);
    if(libraries.some(item=>item.id===prior))$(id).value=prior;
  }
  options('gegi-dual-job',[{id:'',label:'Choose an acquisition'},...value.jobs.map(job=>({id:job.name,label:job.name+' · '+job.status}))]);
  if(value.jobs.some(job=>job.name===name))$('gegi-dual-job').value=name;
}
async function refreshDualSources(){
  dualBusy=true;dualControls();
  try{
    const value=await api('/api/workflow/gegi-dual/options');setDualOptions(value,dualJob?.name);
    const rejected=value.rejected.map(item=>item.label+' — '+item.error).join(' ');
    const libraryCount=dualLibraries.length,jobCount=value.jobs.length;
    let message=libraryCount+' saved source '+(libraryCount===1?'library':'libraries')+' · '+jobCount+' saved acquisition'+(jobCount===1?'':'s')+'.';
    if(dualLibraries.length)message+=' Library coordinates are recorded global x, y, z in millimetres.';
    else if(!value.jobs.length)message+=' Copy a sealed source chunk into the import folder above.';
    dualStatus(message+(rejected?' '+rejected:''),!!rejected);
  }catch(e){dualStatus(e.message,true);}finally{dualBusy=false;dualControls();}
}
function dualSpectrum(histogram,denominator,{title='Combined slow-energy spectrum',stage='gegi_dual_event_energy',
    denominatorUnit='qualified triggers',color='#007d8a'}={}){
  const edges=histogram.bin_edges_keV,counts=histogram.counts,width=edges[1]-edges[0];
  const inside=counts.reduce((a,b)=>a+b,0),total=inside+histogram.underflow+histogram.overflow;
  return histogramFigure({title,stage,color,domain:[edges[0],edges.at(-1),width],denominator,denominatorUnit,inside,
    underflow:histogram.underflow, overflow:histogram.overflow, notSelected:denominator-total,
    bins:new Map(counts.map((count,index)=>[index,count]))});
}
function dualStripLabel(face,id){return face+String(face==='X'?id:id-17).padStart(2,'0');}
function dualReportReason(reason){
  const reasons={no_qualified_adc_samples:'No ADC samples qualified.',report_missing:'The saved report is missing.',
    report_changed:'The saved report differs from its completion receipt.',
    report_unverified:'The saved report could not be verified.',invalid_report:'The saved report has invalid trigger records.'};
  return reasons[reason]||'The saved report could not be read.';
}
function dualPixelGrid(axes,inspect){
  const scroll=node('div',undefined,'dual-pixel-scroll');
  scroll.tabIndex=0;
  scroll.setAttribute('role','region');
  scroll.setAttribute('aria-label','Scrollable detector pixel grid');
  const table=node('table',undefined,'dual-pixel-table'),header=node('thead'),top=node('tr'),body=node('tbody');
  table.setAttribute('aria-label','Selected trigger counts by detector strip intersection');
  const xLabels=axes.x_contact_ids.map(id=>dualStripLabel('X',id)),yLabels=axes.y_contact_ids.map(id=>dualStripLabel('Y',id));
  const cells=yLabels.map(()=>[]);
  const arrows={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowDown:[0,-1],ArrowUp:[0,1]};
  let tabStop;
  function setTabStop(button){
    if(tabStop)tabStop.tabIndex=-1;
    tabStop=button;
    button.tabIndex=0;
  }
  top.append(node('th','Y / X'));
  for(const label of xLabels){
    const heading=node('th',label);heading.setAttribute('scope','col');top.append(heading);
  }
  header.append(top);
  for(let y=yLabels.length-1;y>=0;y--){
    const row=node('tr'),heading=node('th',yLabels[y]);heading.setAttribute('scope','row');row.append(heading);
    for(let x=0;x<xLabels.length;x++){
      const cell=node('td'),button=node('button');
      button.type='button';button.tabIndex=-1;
      if(!tabStop)setTabStop(button);
      button.onclick=()=>{setTabStop(button);return inspect({x:x+1,y:y+1});};
      button.onkeydown=event=>{
        const delta=arrows[event.key];
        if(!delta)return;
        event.preventDefault();
        const target=cells[y+delta[1]]?.[x+delta[0]]?.button;
        if(target){setTabStop(target);target.focus();}
      };
      cell.append(button);
      cells[y].push({cell,button});
      row.append(cell);
    }
    body.append(row);
  }
  table.append(header,body);scroll.append(table);
  function paint(counts,pixel){
    const maximum=Math.max(1,...counts.flat()),palette=['#eef3f5','#dceff1','#a9d8df','#246d80','#00485a'];
    for(const [y,row] of counts.entries())for(const [x,count] of row.entries()){
      const {cell,button}=cells[y][x],shade=Math.ceil(4*Math.sqrt(count/maximum));
      const label=xLabels[x]+' / '+yLabels[y]+' · '+count+' selected '+(count===1?'trigger':'triggers');
      cell.style.backgroundColor=palette[shade];cell.style.color=shade>=3?'#fff':'';
      cell.title=label;
      button.textContent=String(count);
      button.setAttribute('aria-label',label+' · Open pixel spectrum');
      button.setAttribute('aria-pressed',String(pixel?.x===x+1&&pixel?.y===y+1));
    }
  }
  return {scroll,paint};
}
function dualPixelMap(job){
  const {pixel_map:initialMap,counts}=job.result;
  const figure=node('div',undefined,'plot dual-pixel-map');
  figure.append(node('h3','Detector pixel counts'));
  if(!initialMap||!['available','empty'].includes(initialMap.status)){
    const reason=initialMap?.reason??(counts.qualified_triggers===null?'no_qualified_adc_samples':'report_unverified');
    figure.append(node('p','Pixel counts unavailable. '+dualReportReason(reason),'muted'));
    return figure;
  }
  const summary=node('p'),caption=node('p',undefined,'muted');
  const controls=node('div',undefined,'horizontal'),actions=node('div',undefined,'actions');
  const bounds=['Lower bound (keV, included)','Upper bound (keV, excluded)'].map(text=>{
    const label=node('label',text),input=node('input');
    input.type='number';input.step='any';
    label.append(input);controls.append(label);
    return input;
  });
  const apply=node('button','Apply energy interval'),reset=node('button','Show all energies');
  actions.append(apply,reset);
  const status=node('p',undefined,'muted'),spectrum=node('div');
  status.setAttribute('role','status');
  const grid=dualPixelGrid(initialMap.axes,pixel=>readSelection({window:requested.window,pixel}));
  figure.append(summary,controls,actions,status,grid.scroll,caption,spectrum);

  const all={window:null,pixel:null};
  let shown=all,requested=all,generation=0;
  function render(map,selection,pixelSpectrum,{pixel,window:range}){
    const {totals}=map,mapped=totals.mapped_single_pixel_triggers;
    const hitCount=totals.occupied_pixels+' of 256 pixels hit.';
    summary.textContent=range?selection.selected_single_pixel_triggers+' of '+selection.available_single_pixel_triggers+
      ' qualified single-pixel triggers in '+range[0]+' ≤ E < '+range[1]+' keV · '+hitCount:
      mapped+' of '+totals.qualified_triggers+' qualified triggers mapped · '+hitCount+
      ' The map counts one X–Y strip intersection per qualified single-pixel energy.';
    caption.textContent='X01 to X16 from left to right. Y16 to Y01 from top to bottom. '+
      (mapped?'Darker fill marks higher counts. ':'Every cell has zero selected triggers. ')+
      'Select a pixel for its full measured spectrum. Use arrow keys to move between pixels.';
    grid.paint(map.counts,pixel);
    spectrum.replaceChildren();
    if(pixelSpectrum){
      const title=dualStripLabel('X',pixel.x)+' / '+dualStripLabel('Y',pixel.y+17)+' slow-energy spectrum';
      const histogram=pixelSpectrum.spectrum;
      const total=histogram.entries;
      spectrum.append(node('p',total+' qualified single-pixel '+(total===1?'trigger':'triggers')+
        ' in the full spectrum. Current map count '+pixelSpectrum.selected_entries+'.'),dualSpectrum(histogram,total,
        {title,stage:'gegi_dual_pixel_energy',denominatorUnit:'qualified single-pixel triggers in this pixel',color:'#72529a'}));
    }
  }
  async function readSelection(wanted){
    const ticket=++generation;
    requested=wanted;
    if(!wanted.window&&!wanted.pixel){shown=all;render(initialMap,null,null,all);status.textContent='';return;}
    status.textContent='Reading the saved pixel counts and spectrum…';
    try{
      const query=new URLSearchParams({name:job.name,report_sha256:job.report_sha256});
      if(wanted.window){query.set('min_kev',wanted.window[0]);query.set('max_kev',wanted.window[1]);}
      if(wanted.pixel){query.set('x',wanted.pixel.x);query.set('y',wanted.pixel.y);}
      const reply=await api('/api/workflow/gegi-dual/pixel-energy?'+query);
      if(ticket!==generation||!figure.isConnected)return;
      const {selection,pixel_map:map,pixel_spectrum:pixel}=reply;
      if(reply.name!==job.name||reply.report_sha256!==job.report_sha256||
          selection?.min_keV!==(wanted.window?.[0]??null)||selection?.max_keV!==(wanted.window?.[1]??null)||
          (wanted.pixel?(pixel?.x_strip!==wanted.pixel.x||pixel?.y_strip!==wanted.pixel.y):pixel!==null)){
        throw Error('The saved result differs from the selected acquisition, interval or pixel. Reopen the acquisition.');
      }
      render(map,selection,pixel,wanted);
      shown=wanted;
      status.textContent='';
    }catch(e){
      if(ticket!==generation||!figure.isConnected)return;
      requested=shown;
      status.textContent=e.message;
    }
  }
  apply.onclick=()=>{
    const values=bounds.map(input=>input.value.trim()),window=values.map(Number);
    if(values.some(text=>!text)||!window.every(Number.isFinite)||window[0]>=window[1]){
      status.textContent='Enter two finite energies with the lower bound below the upper bound.';
      return;
    }
    return readSelection({window,pixel:requested.pixel});
  };
  for(const input of bounds)input.onkeydown=event=>{
    if(event.key==='Enter'){event.preventDefault();return apply.onclick();}
  };
  reset.onclick=()=>{for(const input of bounds)input.value='';return readSelection({window:null,pixel:requested.pixel});};
  render(initialMap,null,null,all);
  return figure;
}
function dualFeatureValue(value,unit='',signed=false){
  if(value===null)return 'Unavailable';
  const shown=Number(value.toPrecision(7));
  return (signed&&shown>0?'+':'')+shown+(unit?' '+unit:'');
}
function dualFeatureFace(axis,face){
  const contact=id=>dualStripLabel(axis,id)+' (contact '+id+')';
  const card=node('div',undefined,'plot');
  card.append(node('h3',contact(face.contact_id)),node('p','Collecting strip, slow · '+dualFeatureValue(face.slow_energy_keV,'keV')));
  if(Object.hasOwn(face,'preamp_cfd50_ns')){
    card.append(node('p','Preamplifier 50% constant-fraction time · '+
      (face.preamp_cfd50_ns===null?'Unavailable':dualFeatureValue(face.preamp_cfd50_ns,'ns',true)+' relative to trigger')));
  }
  for(const [label,neighbor] of [['Lower neighbor',face.low],['Higher neighbor',face.high]]){
    if(neighbor===null){card.append(node('p',label+' · Detector edge'));continue;}
    const flagLabels={fast_adc_saturation:'ADC saturation',fast_pileup:'Pileup',fast_window_truncated:'Fast window truncated'};
    const flags=neighbor.flags.map(flag=>flagLabels[flag]||flag.replaceAll('_',' '));
    card.append(node('p',label+' '+contact(neighbor.contact_id)+' · '+dualFeatureValue(neighbor.fast_keV_equiv,'keV-equivalent',true)
      +(flags.length?' · '+flags.join(', '):'')));
  }
  card.append(node('p','Fast ratio · '+dualFeatureValue(face.fast_ratio,'',true)));
  return card;
}
function dualNominalPosition(position){
  const panel=node('div');
  const descriptions={estimated:'All three detector coordinates were estimated.',partial:'Only some detector coordinates were estimated.',
    unavailable:'The calibration returned no coordinates for this trigger.',
    uncalibrated_pixel:'This X–Y pixel has no nominal position calibration.',
    unconfirmed_field:'The saved detector fields could not be matched to the position calibration.'};
  panel.append(node('h3','Nominal detector position'),node('p',descriptions[position.status]));
  const methods={direct_strip_calibration:'Direct strip calibration',family_template_transfer:'Strip-family template transfer'};
  const energies=position.tested_energies_keV??[250,662];
  const low=Math.min(...energies),high=Math.max(...energies);
  const support=!energies.length?'':low===high?'Tested at '+low+' keV.':'Tested range '+low+'–'+high+' keV.';
  if(position.method)panel.append(node('p',methods[position.method]+'. '+support,'muted'));
  if(position.axes){
    const reasons={ratio_outside_calibration:'fast ratio outside calibration',cfd_difference_outside_calibration:'timing difference outside calibration',
      depth_condition_unavailable:'depth estimate unavailable',collector_cfd_unavailable:'collector timing unavailable',
      neighbor_or_collector_signal_unavailable:'neighbor or collector signal unavailable'};
    const list=node('ul');
    for(const [axis,label] of [['x','X'],['y','Y'],['z','Z (depth)']]){
      const value=position.axes[axis];
      const measurement=value.position_mm===null?'Unavailable · '+(reasons[value.status]||value.status.replaceAll('_',' ')):
        value.position_mm.toFixed(3)+' mm';
      list.append(node('li',label+' · '+measurement));
    }
    panel.append(list);
  }
  if(position.energy_scope==='outside_tested_range'){
    const extrapolated=['estimated','partial'].includes(position.status);
    const scope=!energies.length?'Trigger energy is outside the tested energy support.':low===high
      ?'Trigger energy differs from the single tested '+low+' keV scale.'
      :'Trigger energy is outside the tested '+low+'–'+high+' keV range.';
    panel.append(node('p',scope+
      (extrapolated?' The displayed coordinates are extrapolations.':''),'muted'));
  }
  return panel;
}
function dualApparentDepth(depth){
  const reasons={outside_calibrated_cfd_range:'timing difference outside the calibrated range',
    collector_cfd_unavailable:'collector timing unavailable',unconfirmed_field:'detector field unconfirmed',
    readout_profile_mismatch:'readout profile differs from the calibration',
    insufficient_center_knots:'too few calibrated center depths',
    interior_center_knots_missing:'calibration has a gap between center depths',
    nonmonotonic_center_timing:'center timing does not give a unique depth',invalid_pixel:'invalid detector pixel'};
  const evidence={local_independent_off_center_check:'Independent off-center simulation check for this pixel',
    center_calibration_only:'Pixel-center simulation calibration only'};
  const value=depth.apparent_depth_mm===null?'Unavailable · '+reasons[depth.status]:
    dualFeatureValue(depth.apparent_depth_mm,'mm',true);
  const cfd=depth.cfd_x_minus_y_ns===null?'':' · CFD X − Y '+dualFeatureValue(depth.cfd_x_minus_y_ns,'ns',true);
  return 'Apparent CFD depth · '+value+cfd+(depth.evidence_level?' · '+evidence[depth.evidence_level]:'');
}
function dualTriggerPanel(job,view,{mode,title,description,showReadings}){
  const panel=node('details'),first=view.trigger,count=view.count;
  panel.append(node('summary',title),node('p',description,'muted'));
  const numberLabel={'single-pixel':'Single-pixel','two-strip':'Two-strip','acquisition-trigger':'Recorded'};
  const label=node('label',numberLabel[mode]+' trigger number (1–'+count+')');
  const input=node('input');
  input.type='number';input.min='1';input.max=String(count);input.step='1';input.value=String(first.ordinal);
  label.append(input);
  const calibrated=new Set(view.calibrated_ordinals||[]);
  let shortcut;
  if(calibrated.size){
    const fields=node('div',undefined,'horizontal'),pickLabel=node('label','Position estimate or attempt');
    shortcut=node('select');
    const empty=node('option','Choose a trigger number');empty.value='';
    shortcut.append(empty);
    for(const number of calibrated){const choice=node('option',String(number));choice.value=String(number);shortcut.append(choice);}
    shortcut.onchange=()=>{if(shortcut.value)return select(Number(shortcut.value));};
    pickLabel.append(shortcut);fields.append(label,pickLabel);panel.append(fields);
  }else panel.append(label);
  const navigation=node('div',undefined,'actions');
  const previous=node('button','Previous trigger'),next=node('button','Next trigger');
  navigation.append(previous,next);
  const status=node('p',undefined,'muted'), readings=node('div');
  status.setAttribute('role','status');
  panel.append(navigation,status,readings);
  let ordinal=first.ordinal,generation=0;
  function render(trigger){
    status.textContent='Trigger '+trigger.ordinal+' of '+count+' · '+trigger.trigger_time_ns+' ns after recording start · Slow energy '
      +dualFeatureValue(trigger.single_pixel_energy_keV??trigger.energy_keV,'keV');
    readings.replaceChildren();
    showReadings(readings,trigger);
  }
  function navigationState(){
    previous.disabled=ordinal===1;next.disabled=ordinal===count;
    if(shortcut)shortcut.value=calibrated.has(ordinal)?String(ordinal):'';
  }
  async function select(wanted){
    if(!Number.isSafeInteger(wanted)||wanted<1||wanted>count){
      input.value=String(ordinal);
      status.textContent='Enter a '+numberLabel[mode].toLowerCase()+' trigger number from 1 through '+count+'.';
      return;
    }
    ordinal=wanted;input.value=String(wanted);navigationState();
    const ticket=++generation;
    if(wanted===first.ordinal){render(first);return;}
    readings.replaceChildren();status.textContent='Reading trigger '+wanted+'…';
    try{
      const query=new URLSearchParams({name:job.name,report_sha256:job.report_sha256,ordinal:wanted});
      const reply=await api('/api/workflow/gegi-dual/'+mode+'?'+query);
      if(ticket!==generation||!panel.isConnected)return;
      if(reply.name!==job.name||reply.report_sha256!==job.report_sha256||reply.trigger?.ordinal!==wanted){
        throw Error('The selected acquisition or trigger changed. Reopen the acquisition.');
      }
      render(reply.trigger);
    }catch(e){if(ticket===generation&&panel.isConnected)status.textContent=e.message;}
  }
  previous.onclick=()=>select(ordinal-1);
  next.onclick=()=>select(ordinal+1);
  input.onchange=()=>select(Number(input.value));
  input.onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();return select(Number(input.value));}};
  render(first);navigationState();
  return panel;
}
function dualAcquisitionTriggerPanel(job){
  const view=job.result.acquisition_triggers;
  if(!view)return null;
  if(view.status!=='available')return node('p','Detailed recorded trigger outcomes are unavailable in this report.','muted');
  return dualTriggerPanel(job,view,{mode:'acquisition-trigger',title:'Inspect any recorded trigger',
    description:'Use the trigger number in the original acquisition, including triggers without an accepted energy.',
    showReadings:(target,trigger)=>{
      for(const face of ['X','Y']){
        const key=face.toLowerCase(),strips=trigger[key+'_collecting_strips'].map(id=>dualStripLabel(face,id));
        target.append(node('p',face+' collecting strips · '+(strips.join(', ')||'None')+' · Slow strip sum '+
          dualFeatureValue(trigger[key+'_sum_keV'],'keV')));
      }
      const guards=trigger.guard_contact_ids.map(id=>id===17?'X guard':'Y guard');
      target.append(node('p','Collecting guards · '+(guards.join(', ')||'None')+' · Rise ended '+
        (trigger.rise_end_ns-trigger.trigger_time_ns)+' ns after trigger'));
      for(const [label,flags] of [['Trigger',trigger.flags],['Event energy',trigger.event_energy_flags]]){
        if(flags.length)target.append(node('p',label+' flags · '+flags.map(f=>f.replaceAll('_',' ')).join(' · ')));
      }
    }});
}
function dualSinglePixelPanel(job){
  const features=job.result.single_pixel_features;
  if(features?.status!=='available'){
    const reasons={not_captured:'This saved acquisition predates capture of the fast neighbor readings.',
      no_qualified_single_pixel_energies:'This acquisition has no qualified single-pixel energies.',
      invalid_features:'The saved report has invalid fast and slow measurements.'};
    const reason=features?.reason??'report_unverified';
    return node('p','Single-pixel trigger measurements unavailable. '+(reasons[reason]||dualReportReason(reason)),'muted');
  }
  const [gateStart,gateEnd]=features.fast_area_gate_ns;
  return dualTriggerPanel(job,features,{mode:'single-pixel',title:'Inspect single-pixel trigger measurements',
    description:'Fast readings are signed integrals from '+gateStart+' to '+gateEnd+' ns relative to the trigger, in keV-equivalent. The dimensionless ratio divides (lower − higher) by the trigger’s slow energy.',
    showReadings:(target,trigger)=>{
      const faces=node('div',undefined,'dual-feature-faces');
      faces.append(dualFeatureFace('X',trigger.x),dualFeatureFace('Y',trigger.y));
      target.append(faces);
      if(trigger.nominal_position)target.append(dualNominalPosition(trigger.nominal_position));
      if(trigger.pixel_depth)target.append(node('p',dualApparentDepth(trigger.pixel_depth)),
        node('p','The estimate uses the detector midplane as zero and a timing table fit to isolated 500 keV simulated deposits.','muted'));
    }});
}
function dualFaceActivity(data){
  const time=data.time_ns,x=data.x_change_keV,y=data.y_change_keV,threshold=data.coincidence_threshold_keV;
  if(!Array.isArray(time)||time.length!==27||time.some((t,i)=>t!==-40+20*i)||
      ![x,y].every(face=>Array.isArray(face)&&face.length===time.length&&face.every(Number.isFinite))||
      !Number.isFinite(threshold)||!Array.isArray(data.groups))throw Error('Invalid saved-clock trigger response.');
  const content=node('div'),unit='keV per '+data.sample_period_ns+' ns sample';
  content.append(gegiTracePlot({time_ns:time,change:x},'change','Two-face trigger response',unit,{
    neighbor:{time_ns:time,change:y},names:['X face','Y face'],digital:true,triggerRelative:true,threshold,
    sampleCaption:'X face (solid) and Y face (dashed), including the guard on each face. Both responses must reach the dotted '+
      threshold+' '+unit+' threshold on the same sample. These curves are derived from the 34 sampled preamp voltages.'}));
  const rises=data.groups.filter(group=>group.coincident);
  for(const group of rises){
    const boundary=group.right_quiet_visible?'':' The window ends before a full quiet interval is visible.';
    content.append(node('p','Coincident rise · first visible active sample '+group.first_active_ns+' ns · both faces reach threshold at '+
      group.first_coincident_ns+' ns · last visible active sample '+group.last_active_ns+' ns.'+boundary,'muted'));
  }
  if(!rises.length)content.append(node('p','No simultaneous threshold crossing in the available samples.','muted'));
  content.append(node('p','The trigger groups nearby active samples into one rise. A separate rise needs '+
    data.quiet_samples+' consecutive samples with response magnitude at or below '+data.quiet_threshold_keV+' '+unit+
    ' on both faces. Several deposits can contribute to one rise.','muted'));
  if(data.saturated_contact_ids.length)content.append(node('p','The ADC reached its voltage limit on contacts '+
    data.saturated_contact_ids.join(', ')+'. The affected signals are clipped.','notice'));
  return content;
}
function dualADCPanel(job,trigger){
  const panel=node('details'),label=node('label','ADC signal to inspect');
  const selection=node('select'),status=node('p',undefined,'muted'),target=node('div');
  status.setAttribute('role','status');
  const name=id=>dualStripLabel(id<=16?'X':'Y',id);
  for(const {contact_id:id,collecting} of trigger.adc_contacts){
    const option=node('option',name(id)+' · '+(collecting?'Collector':'Neighbor'));
    option.value=String(id);selection.append(option);
  }
  const faces=node('option','Trigger response on both faces');faces.value='faces';selection.append(faces);
  selection.value=String(trigger.adc_contacts.find(row=>row.collecting).contact_id);
  label.append(selection);panel.append(node('summary','Inspect simulated ADC samples'),label,status,target);
  const messages={not_captured:'This acquisition has no saved ADC windows.',
    excluded_history:'This window overlaps time excluded for uncertain signal history.',
    outside_live_time:'This window extends beyond the recorded ADC samples.',
    unverified:'The saved ADC window could not be verified for this acquisition.'};
  let generation=0;
  async function load(){
    const ticket=++generation;
    if(!panel.open)return;
    const faceView=selection.value==='faces',contact=faceView?null:Number(selection.value);
    status.textContent=faceView?'Reading both detector faces…':'Reading '+name(contact)+' ADC samples…';target.replaceChildren();
    try{
      const query=new URLSearchParams({name:job.name,report_sha256:job.report_sha256,ordinal:trigger.ordinal});
      if(!faceView)query.set('contact_id',contact);
      const route=faceView?'two-strip-activity':'two-strip-adc';
      const reply=await api('/api/workflow/gegi-dual/'+route+'?'+query);
      if(ticket!==generation||!panel.isConnected||!panel.open)return;
      if(reply.name!==job.name||reply.report_sha256!==job.report_sha256||reply.ordinal!==trigger.ordinal||
          (!faceView&&reply.contact_id!==contact)||reply.trigger_time_ns!==trigger.trigger_time_ns){
        throw Error('The saved ADC window does not match the current trigger and strip.');
      }
      if(reply.status!=='captured'){
        status.textContent=messages[reply.status]||'Saved ADC samples are unavailable.';
        return;
      }
      if(faceView){
        target.append(dualFaceActivity(reply.face_activity));status.textContent='';return;
      }
      const time=reply.relative_time_ns,volts=reply.preamp_V;
      if(!Array.isArray(time)||time.length!==29||time.some((sample,i)=>sample!==-80+20*i)||
          !Array.isArray(volts)||volts.length!==time.length||!volts.every(Number.isFinite))throw Error(messages.unverified);
      status.textContent='';
      target.append(gegiTracePlot({time_ns:time,preamp_V:volts},'preamp_V',name(contact)+' sampled preamplifier','V',
        {digital:true,triggerRelative:true,sampleCaption:time.length+' saved ADC samples. Markers show the decoded voltages.'}));
    }catch(error){if(ticket===generation&&panel.isConnected&&panel.open)status.textContent=error.message;}
  }
  selection.onchange=load;panel.ontoggle=load;
  return panel;
}
function dualTwoStripPanel(job){
  const view=job.result.two_strip_pairings;
  if(!view)return null;
  if(view.status==='empty')return node('p','No qualified triggers recorded two collecting strips on each face.','muted');
  if(view.status!=='available')return node('p','The saved two-strip pairings could not be read.','muted');
  return dualTriggerPanel(job,view,{mode:'two-strip',title:'Inspect two-strip trigger pairings ('+view.count+')',
    description:'These triggers have two collecting strips on each face and a qualified slow energy. Pileup can produce the same strip pattern.',
    showReadings:(target,trigger)=>{
      const pairs=trigger.two_strip_pairings;
      const status=['incompatible_energies','unique_energy_pairing','ambiguous_energy_pairing'][pairs.compatible_pairing_count];
      renderGeGIDigitalPairs(null,target,{...pairs,status,compton_order_scope:true},true);
      if(pairs.pairings.some(pairing=>pairing.pixel_depths)){
        const overlapping=pairs.flags.some(flag=>flag==='overlapping_x_neighborhoods'||flag==='overlapping_y_neighborhoods');
        target.append(node('p','Each apparent depth uses the displayed X–Y assignment and a timing table for isolated 500 keV simulated deposits.','muted'));
        if(overlapping)target.append(node('p','The strip neighborhoods overlap. In the simultaneous-deposit simulation, depth RMS error was 0.660 mm for 32 nearby sites and 0.074 mm for 36 sites with separate neighborhoods.','muted'));
      }
      if(pairs.flags.length)target.append(node('p','Fast-neighbor geometry · '+pairs.flags.map(flag=>flag.replaceAll('_',' ')).join(' · '),'muted'));
      if(trigger.adc_contacts?.length)target.append(dualADCPanel(job,trigger));
    }});
}
function dualPlaneMap(grid, layer, crop){
  const {x_mm:savedX,y_mm:savedY,step_mm:step,assumed_z_mm:z}=grid;
  const inset=length=>crop?Math.min(Math.round(length/4),Math.floor((length-1)/2)):0;
  const left=inset(savedX.length),right=savedX.length-left,bottom=inset(savedY.length),top=savedY.length-bottom;
  const x=savedX.slice(left,right),y=savedY.slice(bottom,top);
  const figure=node('figure',undefined,'plot dual-plane-figure');
  const axes=node('div',undefined,'dual-plane-axes'),plot=node('canvas');
  const format=value=>Number(value.toPrecision(5)).toString();
  const edges=values=>[values[0]-step/2,values.at(-1)+step/2];
  const footprint=(xs,ys)=>'X '+edges(xs).map(format).join(' to ')+' mm · Y '+edges(ys).map(format).join(' to ')+' mm';
  function ticks(values,vertical){
    const [low,high]=edges(values);
    const labels=[low,(low+high)/2,high].map(value=>node('span',format(value)));
    const axis=node('div',undefined,vertical?'dual-plane-y':'dual-plane-x');
    axis.setAttribute('aria-hidden','true');axis.append(...(vertical?labels.reverse():labels));
    return axis;
  }
  plot.width=x.length;plot.height=y.length;
  plot.setAttribute('role','img');
  plot.setAttribute('aria-label','Backprojection '+(crop?'crop ':'')+'at z = '+z+' mm. X increases right from '+
    edges(x).map(format).join(' to ')+' mm. Y increases up from '+edges(y).map(format).join(' to ')+' mm.');
  const context=plot.getContext('2d'),image=context.createImageData(x.length,y.length);
  let maximum=0,peakX=0,peakY=0,inside=0,outside=0;
  const visible=(i,j)=>i>=left&&i<right&&j>=bottom&&j<top;
  for(const [j,row] of layer.mass.entries())for(const [i,mass] of row.entries()){
    if(mass>maximum){maximum=mass;peakX=i;peakY=j;}
    if(visible(i,j))inside+=mass;
    else outside+=mass;
  }
  for(let j=bottom;j<top;j++)for(let i=left;i<right;i++){
    const fraction=maximum?layer.mass[j][i]/maximum:0, offset=((top-1-j)*x.length+i-left)*4;
    image.data.set([242-230*fraction,247-156*fraction,249-129*fraction,255],offset);
  }
  context.putImageData(image,0,0);
  const yLabel=node('span','Y (mm)','dual-plane-y-label'),xLabel=node('span','X (mm)','dual-plane-x-label');
  axes.append(yLabel,ticks(y,true),plot,ticks(x,false),xLabel);figure.append(axes);
  const caption=node('figcaption',undefined,'muted');
  const shown=crop?' Showing '+footprint(x,y)+' (whole saved cells).':'';
  caption.append(node('div','Saved footprint '+footprint(savedX,savedY)+'.'+shown+
    ' Grid spacing '+format(step)+' × '+format(step)+' mm.'));
  caption.append(node('div','Projected weight in nominal trigger units · '+format(layer.projected_mass)+' total · '+
    format(inside)+' inside view · '+format(outside)+' outside view.'));
  if(crop)caption.append(node('div','The crop keeps the saved cell weights. Outside-view weight comes from saved cells hidden by the crop.'));
  if(maximum){
    const edge=peakX===0||peakX===savedX.length-1||peakY===0||peakY===savedY.length-1;
    caption.append(node('div','Brightest saved cell ('+format(savedX[peakX])+', '+format(savedY[peakY])+') mm'+
      (edge?' · saved image edge':'')+(visible(peakX,peakY)?'':' · outside crop')+'.'));
  }
  caption.append(node('div',maximum?'Shared full-view color scale from 0 to '+format(maximum)+' nominal trigger units per cell.':
    'This window has no projected trigger mass.'));
  figure.append(caption);
  return figure;
}
function dualPlanePanel(job){
  if(job.result.measured_plane?.status!=='saved')return null;
  const details=node('details'),body=node('div'),status=node('p','','notice');
  const labels={saved:'Primary saved map','uniform-area':'Uniform area','uniform-solid-angle':'Uniform solid angle'};
  const variants=job.result.measured_plane.variants??['saved'];
  const priorChoice=node('select');
  for(const variant of variants){
    const option=node('option',labels[variant]);option.value=variant;priorChoice.append(option);
  }
  priorChoice.value=variants[0];
  status.setAttribute('role','status');
  details.append(node('summary','Measured Compton backprojection on a plane'));
  if(variants.length>1){
    const priorLabel=node('label','Saved plane map');priorLabel.append(priorChoice);details.append(priorLabel);
  }
  details.append(status,body);
  let request=0,opened=false,selectedWindow='all',selectedView='full';
  details.ontoggle=()=>{if(details.open&&!opened)return load();};
  priorChoice.onchange=load;
  async function load(){
    const generation=++request,variant=priorChoice.value;
    const current=()=>dualJob===job&&request===generation;
    opened=true;status.textContent='Opening the saved plane…';body.replaceChildren();
    try{
      const query=new URLSearchParams({name:job.name,report_sha256:job.report_sha256});
      if(variant!=='saved')query.set('prior',variant);
      const reply=await api('/api/workflow/gegi-dual/plane?'+query);
      if(!current())return;
      if(reply.name!==job.name||reply.report_sha256!==job.report_sha256)throw Error('The plane does not match the opened acquisition.');
      const {grid,selection,layers,model}=reply;
      if(variant!=='saved'&&model.plane_prior!==variant)throw Error('The plane does not match the selected prior.');
      if(variant==='saved')priorChoice.children[0].textContent=labels.saved+' · '+labels[model.plane_prior];
      const origin=model.plane_prior_reference_origin_mm;
      const prior=origin?'Uniform solid angle from detector origin ('+origin.join(', ')+') mm.':
        'Uniform area (equal weight per unit area).';
      const coverage=origin?', which subtends '+Number(model.plane_prior_coverage_sr.toPrecision(5))+' sr at that origin.':'.';
      const controls=node('div',undefined,'dual-feature-faces');
      const label=node('label','Measured energy window'),windowChoice=node('select'),plot=node('div');
      const viewLabel=node('label','Map view'),viewChoice=node('select');
      const full=node('option','Full saved footprint'),crop=node('option','Center half-width crop');
      full.value='full';crop.value='crop';crop.disabled=Math.max(grid.x_mm.length,grid.y_mm.length)===2;
      viewChoice.append(full,crop);viewChoice.value=crop.disabled?'full':selectedView;viewLabel.append(viewChoice);controls.append(label,viewLabel);
      const summary=node('p','','notice');summary.setAttribute('role','status');
      const keys=Object.keys(layers).filter(key=>key!=='all'&&key!=='other_energy').sort((a,b)=>parseFloat(a)-parseFloat(b));
      for(const key of ['all',...keys,'other_energy']){
        const text=key==='all'?'All measured energies':key==='other_energy'?'Outside the line windows':'Around '+parseFloat(key)+' keV';
        const option=node('option',text);option.value=key;windowChoice.append(option);
      }
      windowChoice.value=Object.hasOwn(layers,selectedWindow)?selectedWindow:'all';label.append(windowChoice);
      body.append(node('p','Assumed plane z = '+grid.assumed_z_mm+' mm in detector coordinates. '+
        selection.two_strip_triggers+' two-strip triggers among '+selection.qualified_energies+' measured energies and '+
        selection.qualified_triggers+' qualified triggers.'),
        node('p','Saved plane prior · '+prior+' Each cone was normalized over the full saved footprint'+coverage),
        controls,node('p',selection.energy_windows,'muted'),summary,plot,
        node('p',model.geometry+' '+model.ambiguity.replace('Unresolved weight remains outside the map',
          'Unresolved weight is recorded separately'),'muted'),
        node('p',model.limits.replace('displayed footprint','reconstruction footprint'),'muted'));
      function paint(){
        selectedWindow=windowChoice.value;selectedView=viewChoice.value;
        const layer=layers[selectedWindow];
        const mass=value=>Number(value.toPrecision(5));
        summary.textContent=layer.triggers+' triggers in this window · '+layer.triggers_with_geometry+
          ' with projected geometry · '+layer.hypotheses+' of '+layer.allowed_hypotheses+' allowed alternatives projected. '+
          'Nominal trigger units: '+mass(layer.projected_mass)+' projected, '+mass(layer.unresolved_mass)+' unresolved.';
        plot.replaceChildren(dualPlaneMap(grid,layer,selectedView==='crop'));
      }
      windowChoice.onchange=paint;viewChoice.onchange=paint;paint();status.textContent='';
    }catch(error){if(current()){opened=false;body.replaceChildren();status.textContent=error.message;}}
  }
  return details;
}
function showDualJob(job){
  dualJob=job;
  const {result,...receipt}=job;
  $('gegi-dual-receipt').textContent=JSON.stringify({...receipt,...(result?{counts:result.counts,exposure:result.exposure,
    trigger_profile_settings:result.trigger_profile}:{})},null,2);
  const content=$('gegi-dual-results');content.replaceChildren();
  const option=Array.from($('gegi-dual-job').children).find(item=>item.value===job.name);
  if(option)option.textContent=job.name+' · '+job.status;
  dualStatus(job.name+' · '+(job.status==='running'?'replaying the saved acquisition…':job.status)+(job.error?' · '+job.error:''),!!job.error);
  if(result){
    const c=result.counts,t=result.exposure;
    content.append(node('p',job.output,'muted'));
    content.append(node('p',c.initial_parents_in_live_time+' initial parents in live time · '+c.deposit_groups+' Ge deposit groups · '+c.right_censored_deposit_groups+' extend beyond the recording · '+c.native_unavailable_groups+' lacked native response · '+c.prehistory_unqualified_groups+' had unqualified signal history.'));
    const sources=node('ul');
    for(const [index,source] of result.sources.entries()){
      const library=job.sources[index];
      sources.append(node('li',library.isotope+' · ['+library.source_position_mm.join(', ')+'] mm · '+job.activities_bq[index]+' Bq · '+source.parents+' parents ('+source.zero_parents+' zero-deposit library marks) · '+source.deposit_groups+' Ge groups starting in the exposure.'));
    }
    content.append(sources);
    content.append(node('p',metricValue(t.qualified_adc_live_time_ns/1e9)+' s of '+metricValue(t.clock_live_time_ns/1e9)+' s qualified for ADC analysis.'));
    const trigger=result.trigger_profile;
    if(trigger)content.append(node('p',(trigger.id==='low-energy'?'Low-energy':'Standard')+' trigger · '+
      trigger.coincidence_threshold_keV_per_sample+' keV-equivalent per '+trigger.sample_period_ns+' ns ADC sample on both faces · '+
      'Quiet threshold '+trigger.quiet_threshold_keV_per_sample+' keV-equivalent per sample.'));
    if(c.qualified_triggers===null){content.append(node('p','Trigger and energy totals are unknown because no ADC samples qualified.','muted'));}
    else{
      content.append(node('p',c.qualified_triggers+' qualified triggers · '+c.single_pixel_energies+' single-pixel energies · '+c.additional_multi_strip_energies+' additional multi-strip energies · '+c.triggers_without_energy+' without an energy.'));
      if(result.spectra?.combined)content.append(dualSpectrum(result.spectra.combined,c.qualified_triggers));
    }
    const recorded=dualAcquisitionTriggerPanel(job);
    if(recorded)content.append(recorded);
    content.append(dualSinglePixelPanel(job));
    const twoStrip=dualTwoStripPanel(job);
    if(twoStrip)content.append(twoStrip);
    const plane=dualPlanePanel(job);
    if(plane)content.append(plane);
    else if(result.two_strip_pairings?.status==='available'){
      const instructions=node('a','Create a measured plane map');
      instructions.href='https://kunming-cn.github.io/END2END_Ge_Simulation/guide.html#gegi-plane-reconstruction';
      instructions.target='_blank';instructions.rel='noreferrer';
      const hint=node('p');hint.append(instructions);content.append(hint);
    }
    content.append(dualPixelMap(job));
  }
  dualControls();
}
async function inspectDualJob(name){
  const generation=++dualGeneration;
  try{
    const job=await api('/api/workflow/gegi-dual/state?'+new URLSearchParams({name}));
    if(generation===dualGeneration&&job.name===name)showDualJob(job);
  }catch(e){if(generation===dualGeneration)dualStatus(e.message,true);}
}
function dualSetting(id,label,min,exclusive=false){
  const raw=$(id).value.trim(),value=Number(raw);
  if(!raw||!Number.isFinite(value)||(exclusive?value<=min:value<min))throw Error(label);
  return value;
}
async function startDualAcquisition(){
  dualBusy=true;dualControls();
  try{
    const activities_bq=['a','b'].map(side=>dualSetting('gegi-dual-activity-'+side,'Enter a nonnegative activity in Bq for each library.',0));
    const live_time_s=dualSetting('gegi-dual-duration','Enter a positive duration in seconds.',0,true),seed=$('gegi-dual-seed').value.trim();
    if(!/^[0-9]{1,20}$/.test(seed)||BigInt(seed)>18446744073709551615n)throw Error('Enter an integer seed from 0 through 18446744073709551615.');
    ++dualGeneration;
    const job=await api('/api/workflow/gegi-dual/start',{source_ids:dualSourceIds(),activities_bq,live_time_s,seed,
      name:$('gegi-dual-name').value.trim(),trigger_profile:$('gegi-dual-trigger-profile').value});
    showDualJob(job);
    const selection=$('gegi-dual-job');
    const option=node('option',job.name+' · '+job.status);option.value=job.name;selection.append(option);selection.value=job.name;
  }catch(e){dualStatus(e.message,true);}finally{dualBusy=false;dualControls();}
}
$('gegi-dual-refresh').onclick=refreshDualSources;
$('gegi-dual-source-a').onchange=$('gegi-dual-source-b').onchange=dualControls;
$('gegi-dual-start').onclick=startDualAcquisition;
$('gegi-dual-job').onchange=()=>{
  ++dualGeneration;dualJob=null;$('gegi-dual-receipt').textContent='No acquisition selected.';$('gegi-dual-results').replaceChildren();
  const name=$('gegi-dual-job').value;
  if(name){dualStatus('Reading the saved acquisition…');return inspectDualJob(name);}
  dualStatus('Choose an acquisition to view its saved result.');
};

function candidateStatus(text,error=false){$('gegi-candidate-status').textContent=text;$('gegi-candidate-status').className='notice '+(error?'error':'');}
function candidateModeFields(){
  const duration=$('gegi-candidate-mode').value!=='count';
  $('gegi-candidate-duration-field').hidden=!duration;
  $('gegi-candidate-count-field').hidden=duration;
  $('gegi-candidate-scope').textContent=duration?
    'Choose a positive physical duration; the default is 5 seconds. Radioactive daughter populations use the source equilibrium model; electronics start quiet with zero signal history.':
    'Choose a positive integer number of new parent decays; the default is 100. There are no pre-existing radioactive daughters at acquisition start.';
}
function candidateRunDefaults(){return 'Defaults are 100 new parent decays or 5 physical seconds; runtime and storage depend on the requested acquisition.';}
function invalidateCandidateEstimate(){
  ++candidateEstimateGeneration;$('gegi-candidate-estimate').disabled=false;
  $('gegi-candidate-storage').textContent='Source or planning count changed. Estimate storage again for the current settings. '+candidateRunDefaults();
}
async function estimateCandidateStorage(){
  const generation=++candidateEstimateGeneration,button=$('gegi-candidate-estimate'),target=$('gegi-candidate-storage');
  button.disabled=true;target.textContent='Reading the saved storage reference…';
  try{
    const total_parents=exactInteger($('gegi-candidate-estimate-count').value.trim(),'Storage planning count');
    const fields={total_parents:String(total_parents)};
    for(const source of ['a','b']){
      fields['activity_'+source+'_bq']=$('gegi-candidate-activity-'+source).value.trim();
      for(const axis of ['x','y','z'])fields[source+'_'+axis]=$('gegi-candidate-'+source+'-'+axis).value.trim();
    }
    if(Object.values(fields).some(value=>value===''||!Number.isFinite(Number(value))))throw Error('Enter finite source activities and coordinates.');
    const estimate=await api('/api/workflow/gegi-candidates/estimate?'+new URLSearchParams(fields));
    if(generation!==candidateEstimateGeneration)return;
    const gib=bytes=>(bytes/1024**3).toFixed(2),range=estimate.planning_range_bytes;
    let text=estimate.total_parents.toLocaleString('en-US')+' total source decays: saved candidate core '+gib(range[0])+'–'+gib(range[1])+' GiB. Shared field cache '+gib(estimate.shared_field_cache_bytes)+' GiB, counted once. ';
    const whole=estimate.whole_retained_planning_range_bytes,shared=estimate.whole_retained_with_shared_planning_range_bytes;
    if(whole&&shared)text+='Conditional whole retained run '+gib(whole[0])+'–'+gib(whole[1])+' GiB; including the shared cache and existing external evidence once: '+gib(shared[0])+'–'+gib(shared[1])+' GiB. ';
    else text+='Additional fresh-run records have not been measured. ';
    const pipeline=estimate.complete_pipeline_with_shared_planning_range_bytes;
    if(pipeline)text+='With optional source-plane imaging: '+gib(pipeline[0])+'–'+gib(pipeline[1])+' GiB including the shared waveform calibration once ('+gib(estimate.analysis_extension.shared_calibration_once_bytes)+' GiB). ';
    const runtime=estimate.runtime_prediction?.planning_range_seconds;
    if(runtime)text+='Conditional active processing '+(runtime[0]/3600).toFixed(1)+'–'+(runtime[1]/3600).toFixed(1)+' hours at the measured reference rates. ';
    const pipelineRuntime=estimate.complete_pipeline_runtime_prediction?.planning_range_seconds;
    if(pipelineRuntime)text+='Including optional imaging: '+(pipelineRuntime[0]/3600).toFixed(1)+'–'+(pipelineRuntime[1]/3600).toFixed(1)+' active hours under the same conditional scaling. ';
    text+='Future peak temporary storage has not been forecast. These planning scenarios are not a guaranteed upper bound. '+candidateRunDefaults();
    target.textContent=text;
  }catch(e){if(generation===candidateEstimateGeneration)target.textContent='Storage estimate unavailable: '+e.message+' Future peak temporary storage has not been forecast. '+candidateRunDefaults();}
  finally{if(generation===candidateEstimateGeneration)button.disabled=false;}
}
function candidateControls(){
  const running=['running','stop_requested'].includes(candidateJob?.status);
  const analyzing=candidateJob?.analysis?.status==='running'||candidateJob?.range_analysis?.status==='running';
  $('gegi-candidate-start').disabled=candidateBusy||busy||active||running;
  $('gegi-candidate-stop').disabled=candidateBusy||candidateJob?.status!=='running';
  $('gegi-candidate-resume').disabled=candidateBusy||busy||active||!candidateJob?.resumable;
  $('gegi-candidate-refresh').disabled=candidateBusy;
  $('gegi-candidate-previous').disabled=candidateBusy||candidateOffset===0;
  $('gegi-candidate-next').disabled=candidateBusy||!candidatePage||candidateOffset+candidatePage.items.length>=candidatePage.total;
  $('gegi-candidate-analyze').disabled=candidateBusy||busy||active||analyzing||candidateJob?.status!=='completed'||!$('gegi-candidate-calibration').value;
  $('gegi-candidate-open-map').disabled=candidateBusy||!$('gegi-candidate-map').value;
  candidateRangeRefresh?.(candidateJob);
}
async function refreshCandidateRuns(){
  candidateBusy=true;candidateControls();
  try{const reply=await api('/api/workflow/gegi-candidates/options'),prior=$('gegi-candidate-job').value;
    options('gegi-candidate-job',[{id:'',label:'Choose an acquisition'},...reply.jobs.map(job=>({id:job.name,label:job.name+' · '+job.status}))]);
    if(reply.jobs.some(job=>job.name===prior))$('gegi-candidate-job').value=prior;
    const calibration=$('gegi-candidate-calibration').value;
    options('gegi-candidate-calibration',[{id:'',label:'Choose an imported calibration'},...(reply.calibrations||[])]);
    if((reply.calibrations||[]).some(row=>row.id===calibration))$('gegi-candidate-calibration').value=calibration;
    else if(reply.calibrations?.length)$('gegi-candidate-calibration').value=reply.calibrations[0].id;
    const lateral=$('gegi-candidate-lateral-calibration').value,lateralOptions=(reply.lateral_calibrations||[])
      .map(row=>({...row,label:'Lateral where calibrated · '+row.label}));
    options('gegi-candidate-lateral-calibration',[{id:'',label:'Center templates'},...lateralOptions]);
    $('gegi-candidate-lateral-calibration').value=lateralOptions.some(row=>row.id===lateral)?lateral:'';
    candidateStatus(reply.jobs.length+' saved acquisitions. Select one to inspect its statistics and candidates.');
  }catch(e){candidateStatus(e.message,true);}finally{candidateBusy=false;candidateControls();}
}
function showCandidateJob(job){
  const changed=candidateJob?.name!==job.name||candidateJob?.report_sha256!==job.report_sha256;
  candidateJob=job;const report=job.result,summary=$('gegi-candidate-summary');summary.replaceChildren();
  $('gegi-candidate-imaging').hidden=!report;
  if(changed){++candidatePlaneGeneration;$('gegi-candidate-map-view').replaceChildren();}
  const priorMap=$('gegi-candidate-map').value,maps=job.analysis_maps||[];
  options('gegi-candidate-map',[{id:'',label:'Choose a saved map'},...maps.map(row=>({id:row.analysis_id,
    label:(row.scope==='all_two_strip_candidates'?'Full analysis':'Partial analysis')+' · z = '+row.z_mm+' mm · '+row.plane_prior+
      (row.include_shared_strip?' · shared-strip map':'')+
      (row.position_model==='lateral'?' · Lateral where calibrated':'')+
      (row.compatibility?' · All-electrode fit residuals':'')}))]);
  $('gegi-candidate-map').value=maps.some(row=>row.analysis_id===priorMap)?priorMap:maps[0]?.analysis_id||'';
  const analysis=job.analysis;
  $('gegi-candidate-analysis-status').textContent=analysis?.status==='running'?'Analyzing saved candidates in the installed transport environment…':
    analysis?.status==='failed'?'Analysis failed: '+analysis.error:maps.length?'Saved maps are available. Opening a map does not repeat the fit.':
    'Choose the separate matching calibration and plane settings, then analyze all two-strip candidates.';
  const entry=Array.from($('gegi-candidate-job').children).find(option=>option.value===job.name);
  if(entry)entry.textContent=job.name+' · '+job.status.replaceAll('_',' ');
  candidateStatus(job.name+' · '+job.status.replaceAll('_',' ')+(job.error?' · '+job.error:'')+
    (job.status==='running'&&job.progress?' · '+(job.progress.stage||job.progress.status||'processing'):'')+
    (job.status==='stop_requested'?' · Saving progress before stopping.':'')+
    (job.status==='stopped'?' · Saved. Resume continues with the original sources and acquisition clock.':''),job.status==='failed');
  $('gegi-candidate-receipt').textContent=JSON.stringify(report||job,null,2);
  if(!report){
    const progress=job.progress||{},duration=job.duration_s??progress.duration_s;
    if(Number.isFinite(progress.acquisition_time_ns)){
      const seconds=progress.acquisition_time_ns/1e9;
      summary.append(node('p','Physical acquisition time: '+metricValue(seconds)+(Number.isFinite(duration)?' / '+metricValue(duration):'')+' s.'));
      if(Number.isFinite(duration)&&duration>0){const bar=node('progress');bar.max=duration;bar.value=Math.max(0,Math.min(seconds,duration));bar.setAttribute('aria-label','Physical acquisition progress');summary.append(bar);}
    }
    const census=[['New parent decays',progress.new_parent_decays??progress.initial_parents],['Initial-daughter decays',progress.initial_daughter_decays]].filter(([,value])=>Number.isFinite(value));
    if(census.length)summary.append(node('p',census.map(([label,value])=>label+': '+value).join(' · '),'muted'));
  }
  if(report){
    const counts=report.storage_counts,metrics=node('div',undefined,'metrics');
    for(const [label,value]of [['Qualified triggers',report.counts.qualified_triggers],['Saved candidates',counts.saved_candidates],['Rejected rises',counts.rejected_rises],['Candidate store · bytes',report.artifacts['compton-candidates.sqlite'].bytes]]){
      const item=node('span',label);item.append(node('strong',String(value)));metrics.append(item);
    }
    summary.append(metrics,node('p',(report.identity?.scope?.includes('historical')?'Historical saved-library readout diagnostic. ':'')+
      'Acquisition '+metricValue(report.live_time_ns/1e9)+' s · all 34 channels processed; one all-electrode context saved per candidate.','muted'));
    const source=report.source||{},census=[['New parent decays',source.initial_parents],['Initial-daughter decays',source.initial_daughter_decays],['Transported roots',source.transport_primaries],['New parents without Ge deposits',source.zero_deposit_parents],['New parents with Ge deposits',source.nonzero_parents],['Initial daughters without Ge deposits',source.zero_deposit_initial_daughters],['Initial daughters with Ge deposits',source.nonzero_initial_daughters],['Native groups unavailable',source.unavailable_native_groups??source.native_unavailable_groups]].filter(([,value])=>value!==undefined);
    if(census.length)summary.append(node('p',census.map(([label,value])=>label+': '+value).join(' · '),'muted'));
    const initial=report.identity?.source_config?.initial_state;
    if(initial?.policy==='new_parent_decays_empty_daughters_at_start')summary.append(node('p','Startup source state: no pre-existing daughters at t = 0. Delayed deposit groups beyond this acquisition: '+(source.delayed_groups_after_acquisition===undefined?'not recorded':source.delayed_groups_after_acquisition)+'.','muted'));
    if(initial?.policy==='secular_equilibrium_poisson_daughters_v1')summary.append(node('p','Radioactive daughter populations use the source equilibrium model. Electronics start quiet with zero signal history.','muted'));
    const mean=initial?.initial_daughter_mean_population??source.initial_daughter_mean_population;
    if(Number.isFinite(mean))summary.append(node('p','Mean initial daughter population: '+metricValue(mean)+' (a statistical mean, separate from executed decay counts).','muted'));
    if(changed)void loadCandidatePage(0);
  }else if(changed){$('gegi-candidate-view').hidden=true;$('gegi-candidate-plots').replaceChildren();candidatePage=null;}
  candidateControls();
}
async function inspectCandidateJob(name,open=false){
  const generation=candidateGeneration;
  try{const job=await api('/api/workflow/gegi-candidates/state?'+new URLSearchParams({name}));
    if(generation===candidateGeneration&&$('gegi-candidate-job').value===name){showCandidateJob(job);if(open)openRunDetail('gegi');}
  }catch(e){if(generation===candidateGeneration)candidateStatus(e.message,true);}
}
async function startCandidateRun(){
  candidateBusy=true;candidateControls();
  try{
    const value=id=>{const text=$(id).value.trim();if(!text||!Number.isFinite(Number(text)))throw Error('Enter finite source activities and coordinates.');return Number(text);};
    const mode=$('gegi-candidate-mode').value,seed=exactInteger($('gegi-candidate-seed').value.trim(),'Seed');
    if(!['count','duration'].includes(mode))throw Error('Choose a startup count or physical acquisition duration.');
    const request={name:$('gegi-candidate-name').value.trim(),seed,
      activities_bq:['a','b'].map(source=>value('gegi-candidate-activity-'+source)),
      positions_mm:['a','b'].map(source=>['x','y','z'].map(axis=>value('gegi-candidate-'+source+'-'+axis)))};
    if(mode==='duration'){
      request.duration_s=value('gegi-candidate-duration');
      if(request.duration_s<=0)throw Error('Choose a finite positive physical acquisition duration in seconds.');
    }else{
      request.primary_count=exactInteger($('gegi-candidate-count').value.trim(),'New parent decays');
    }
    ++candidateGeneration;++candidateEventGeneration;
    const job=await api('/api/workflow/gegi-candidates/start',request),select=$('gegi-candidate-job');
    const entry=node('option',job.name+' · '+job.status);entry.value=job.name;select.append(entry);select.value=job.name;showCandidateJob(job);openRunDetail('gegi');
  }catch(e){candidateStatus(e.message,true);}finally{candidateBusy=false;candidateControls();}
}
async function manageCandidateRun(action){
  const job=candidateJob;
  if(!job)return;
  const generation=++candidateGeneration;++candidateEventGeneration;
  candidateBusy=true;candidateControls();
  try{
    const reply=await api('/api/workflow/gegi-candidates/'+action,{name:job.name});
    if(generation===candidateGeneration&&$('gegi-candidate-job').value===job.name)showCandidateJob(reply);
  }catch(e){if(generation===candidateGeneration)candidateStatus(e.message,true);}
  finally{candidateBusy=false;candidateControls();}
}
async function analyzeCandidateRun(){
  const job=candidateJob,generation=candidateGeneration;
  if(!job?.report_sha256)return;
  candidateBusy=true;candidateControls();
  try{
    const request={name:job.name,report_sha256:job.report_sha256,calibration_id:$('gegi-candidate-calibration').value,
      plane_prior:$('gegi-candidate-plane-prior').value};
    if($('gegi-candidate-compatibility').checked)request.compatibility=true;
    if($('gegi-candidate-shared-strip').checked)request.include_shared_strip=true;
    const lateral=$('gegi-candidate-lateral-calibration').value;
    if(lateral)request.lateral_calibration_id=lateral;
    for(const [key,id]of [['z_mm','z'],['extent_mm','extent'],['step_mm','step'],['sigma_deg','sigma']]){
      const text=$('gegi-candidate-plane-'+id).value.trim();request[key]=Number(text);
      if(!text||!Number.isFinite(request[key]))throw Error('Enter finite plane settings.');
    }
    const reply=await api('/api/workflow/gegi-candidates/analyze',request);
    if(generation!==candidateGeneration||candidateJob?.name!==job.name)return;
    await inspectCandidateJob(job.name);
    if(reply.reused){$('gegi-candidate-map').value=reply.analysis_id;await openCandidatePlane();}
  }catch(error){if(generation===candidateGeneration)$('gegi-candidate-analysis-status').textContent=error.message;}
  finally{candidateBusy=false;candidateControls();}
}
async function openCandidatePlane(){
  const job=candidateJob,selected=(job?.analysis_maps||[]).find(row=>row.analysis_id===$('gegi-candidate-map').value);
  if(!selected)return;
  const generation=++candidatePlaneGeneration,target=$('gegi-candidate-map-view'),status=$('gegi-candidate-analysis-status');
  const current=()=>generation===candidatePlaneGeneration&&candidateJob?.name===job.name&&candidateJob?.report_sha256===job.report_sha256&&
    $('gegi-candidate-map').value===selected.analysis_id&&(candidateJob.analysis_maps||[]).some(row=>row.analysis_id===selected.analysis_id&&row.analysis_sha256===selected.analysis_sha256);
  candidateRangeRefresh=null;target.replaceChildren();status.textContent='Opening the saved source-plane map…';
  try{
    const reply=await api('/api/workflow/gegi-candidates/plane?'+new URLSearchParams({name:job.name,
      report_sha256:job.report_sha256,analysis_id:selected.analysis_id,analysis_sha256:selected.analysis_sha256}));
    if(!current())return;
    if(reply.name!==job.name||reply.report_sha256!==job.report_sha256||reply.analysis_id!==selected.analysis_id||
      reply.analysis_sha256!==selected.analysis_sha256||reply.kind!=='gegi_continuous_measured_plane_backprojection_v1')throw Error('Saved imaging and selected acquisition identities differ.');
    const {grid,layers,model,selection,candidate_analysis:analysis,shared_strip_plane:shared}=reply,partial=analysis.scope!=='all_two_strip_candidates';
    status.textContent=(partial?'Partial analysis':'Full analysis')+' · '+analysis.selected_original_trigger_ids.length+' of '+analysis.two_strip_candidates+' two-strip candidates selected.';
    const source=analysis.source_census,layerChoice=node('select'),plot=node('div'),summary=node('p','','notice');
    const inspect=node('button','Inspect peak contributors'),contributors=node('div');
    const geometryNote=node('p',model.geometry+' '+model.ambiguity+' '+model.limits,'muted');
    const mapChoice=shared?node('select'):null, mapLabel=shared?node('label','Candidate groups'):null;
    let sharedDetails=null;
    let contributorGeneration=0;
    for(const key of Object.keys(layers)){const option=node('option',key==='all'?'All measured energies':key==='other_energy'?'Outside line windows':parseFloat(key)+' keV');option.value=key;layerChoice.append(option);}
    layerChoice.value='all';const label=node('label','Measured energy window');label.append(layerChoice);
    target.append(node('h4',partial?'Partial source-plane analysis':'Source-plane analysis'),
      node('p',selection.qualified_triggers+' qualified triggers · '+selection.qualified_energies+' measured energies · '+selection.two_strip_triggers+' two-strip candidates. '+
        selection.qualified_adc_live_time_ns/1e9+' of '+selection.clock_live_time_ns/1e9+' s qualified after unknown-history exclusion.'),
      node('p','Original source census: '+source.initial_parents+' new parents · '+source.initial_daughter_decays+' initial-daughter decays. Native groups unavailable: '+source.unavailable_native_groups+'.'),
      node('p','Assumed plane z = '+grid.assumed_z_mm+' mm; saved prior '+model.plane_prior+'. '+model.normalization),
      ...(mapLabel?[mapLabel]:[]),label,summary,plot,inspect,contributors,
      geometryNote,
      featureDetails('Original IDs, full census and analysis provenance',{analysis_sha256:reply.analysis_sha256,input_sha256:reply.input_sha256,original_trigger_ids:reply.original_trigger_ids,candidate_analysis:analysis}));
    if(shared){
      for(const [value,text] of [['two-by-two','Two collecting strips on each face'],['shared','Shared strip on one face']]){
        const option=node('option',text);option.value=value;mapChoice.append(option);
      }
      mapChoice.value='two-by-two';
      mapLabel.append(mapChoice);
      sharedDetails=featureDetails('Shared-strip trigger IDs and fit counts',{original_trigger_ids:shared.original_trigger_ids,
        complete_population:shared.population,fit_status_counts:shared.fit_status_counts,
        omitted_original_trigger_count:shared.omitted_original_trigger_count});
      target.append(sharedDetails);
      mapChoice.onchange=paint;
    }
    if(analysis.position_model==='lateral'){
      const support=analysis.position_calibration_support_pair_counts,used=analysis.position_pair_counts;
      const fallback=Object.entries(analysis.position_fallback_counts).map(([reason,count])=>count+' '+lateralFallbackText(reason));
      status.textContent+=' Lateral positions requested.';
      target.append(node('p','Lateral calibration covers '+analysis.lateral_calibration.coverage_cells.length+' pixels. Across captured, energy-compatible pairs, ' +
        (support['2']||0)+' have two supported sites, '+(support['1']||0)+' have one, and '+(support['0']||0)+' have zero. Successful positions used '+
        (used.lateral||0)+' two-site lateral fits, '+(used.partial_lateral||0)+' one-site lateral fits, and '+(used.center||0)+' center fits.','notice'));
      if(fallback.length)target.append(node('p','Lateral fallback · '+fallback.join(' · '),'muted'));
    }
    const range=!partial?candidateRangePanel(reply,current):null;
    if(range)target.append(range);
    function paint(){
      const showingShared=mapChoice?.value==='shared';
      const active=showingShared?shared:reply,layer=active.layers[layerChoice.value];
      ++contributorGeneration;contributors.replaceChildren();inspect.disabled=layer.projected_mass<=0||showingShared;
      inspect.hidden=showingShared;
      if(range)range.hidden=showingShared;
      if(sharedDetails)sharedDetails.hidden=!showingShared;
      geometryNote.textContent=active.model.geometry+' '+active.model.ambiguity+' '+active.model.limits;
      summary.textContent=layer.triggers+' triggers · '+layer.triggers_with_geometry+' with geometry · '+
        metricValue(layer.projected_mass)+' projected and '+metricValue(layer.unresolved_mass)+' unresolved nominal trigger units.';
      if(showingShared&&shared.omitted_original_trigger_count)summary.textContent+=' '+shared.omitted_original_trigger_count+' shared-strip triggers outside this analysis subset.';
      plot.replaceChildren(dualPlaneMap(grid,layer,false));
    }
    async function openContributors(offset=0){
      const layer=layerChoice.value,requestGeneration=++contributorGeneration,message=node('p','Reading saved pair fits and order contributions…','notice');
      const stillCurrent=()=>current()&&requestGeneration===contributorGeneration&&layerChoice.value===layer;
      message.setAttribute('role','status');contributors.replaceChildren(message);inspect.disabled=true;
      try{
        const result=await api('/api/workflow/gegi-candidates/contributors?'+new URLSearchParams({name:job.name,
          report_sha256:job.report_sha256,analysis_id:selected.analysis_id,analysis_sha256:selected.analysis_sha256,layer,offset:String(offset)}));
        if(!stillCurrent())return;
        if(result.name!==job.name||result.report_sha256!==job.report_sha256||result.analysis_id!==selected.analysis_id||
          result.analysis_sha256!==selected.analysis_sha256||result.layer!==layer||result.offset!==offset)throw Error('Peak contributions belong to a different saved map or energy window.');
        if(!result.peak){message.textContent='This layer has no projected contribution.';return;}
        message.textContent='Brightest cell ('+result.peak.position_mm.join(', ')+') mm'+(result.peak.on_image_edge?' · image edge':'')+
          ' · '+metricValue(result.peak.mass)+' nominal trigger units. Contributors '+(offset+1)+'–'+(offset+result.items.length)+' of '+result.total+'.';
        const list=node('ol');list.start=offset+1;
        for(const row of result.items){
          const trigger=node('li'),button=node('button','Open trigger '+row.original_trigger_id+' waveforms');
          button.onclick=()=>stillCurrent()?openCandidateWaveforms(row):undefined;
          trigger.append(node('strong','Trigger '+row.original_trigger_id+' · '+metricValue(row.energy_keV)+' keV · '+
            metricValue(100*row.peak_cell_share)+'% of peak cell'));
          for(const pair of row.pairings){
            const usedModel=pair.waveform_position_model;
            const waveform=pair.lateral_fit_diagnostics?.[usedModel]??pair.center_fit_diagnostics.waveform;
            const cellText=pair.cells.map(cell=>'('+cell.join(', ')+')').join(' and ');
            const orders=pair.orders.map(order=>'order '+order.order.map(i=>i+1).join(' → ')+' · '+
              metricValue(100*order.peak_cell_mass/result.peak.mass)+'% of peak cell');
            trigger.append(node('p','Pair '+pair.index+' · electrodes '+cellText+' · '+
              (waveform?'waveform residual RMS '+metricValue(waveform.weighted_residual_rms)+' in noise-scale units':pair.waveform_fit_status.replaceAll('_',' '))+
              (orders.length?' · '+orders.join(' · '):''),'muted'));
            if(pair.lateral_calibration_support){
              const used={lateral:'Two-site lateral fit',partial_lateral:'One-site lateral fit',center:'Center fit'}[usedModel]||'Waveform position unavailable';
              const support=pair.lateral_calibration_support.map((supported,index)=>'site '+(index+1)+' '+(supported?'has a lateral grid':'has no lateral grid'));
              const fallback=pair.lateral_fallback_reason?' · '+lateralFallbackText(pair.lateral_fallback_reason):'';
              trigger.append(node('p',used+' · '+support.join(' · ')+fallback,'muted'));
            }
            if(waveform?.compatibility)trigger.append(candidateCompatibilityDetails(waveform));
          }
          trigger.append(featureDetails('Fit positions, order weights and original IDs',row),button);list.append(trigger);
        }
        const previous=node('button','Previous contributors'),next=node('button','Next contributors'),navigation=node('div',undefined,'actions');
        previous.disabled=offset===0;previous.onclick=()=>openContributors(Math.max(0,offset-result.page_size));
        next.disabled=offset+result.page_size>=result.total;next.onclick=()=>openContributors(offset+result.page_size);
        navigation.append(previous,next);contributors.append(list,navigation);
      }catch(error){if(stillCurrent())message.textContent=error.message;}
      finally{if(stillCurrent())inspect.disabled=false;}
    }
    inspect.onclick=()=>openContributors();
    layerChoice.onchange=paint;paint();
  }catch(error){if(current()){target.replaceChildren();status.textContent=error.message;}}
}
function candidateRangePanel(map,current){
  const region=node('section'),message=node('p','','notice'),output=node('div'),choices=node('select');
  const rangeOptions=new Map((map.range_options||[]).map(row=>[row.range_id,row]));
  const min=node('input'),max=node('input'),nuisance=node('input'),run=node('button','Run 3D range analysis'),open=node('button','Open saved range analysis');
  const binding={name:map.name,report_sha256:map.report_sha256,analysis_id:map.analysis_id,analysis_sha256:map.analysis_sha256};
  let loading=false,viewGeneration=0,lastStatus=null;
  message.setAttribute('role','status');message.setAttribute('aria-live','polite');
  for(const [input,value] of [[min,'20'],[max,'10000']]){input.type='number';input.step='any';input.min='0';input.value=value;}
  nuisance.type='checkbox';nuisance.style.cssText='display:inline;width:auto;min-height:0;margin-right:8px';
  const fields=node('div',undefined,'horizontal');
  for(const [text,input] of [['Minimum search distance · mm',min],['Maximum search distance · mm',max]]){
    const label=node('label',text);label.append(input);fields.append(label);
  }
  const nuisanceLabel=node('label');nuisanceLabel.append(nuisance,node('span','Also fit the uniform-angle background fraction'));
  const saved=node('label','Saved 3D range results');saved.append(choices);
  const actions=node('div',undefined,'actions');actions.append(open,run);
  region.append(node('h4','Three-dimensional source range'),node('p','Fit directions on the full sphere and scan distance from detector origin (0, 0, 0) mm. The score profiles are uncalibrated.'),
    saved,fields,nuisanceLabel,actions,message,output);
  function refreshChoices(){
    const selected=choices.value;
    choices.replaceChildren();
    for(const row of rangeOptions.values()){
      const text=row.file+' · '+row.radial_search_mm.join('–')+' mm'+(row.profile_background?' · Profiled background':'')+
        (row.current_solver?'':' · Archived solver');
      const option=node('option',text);option.value=row.range_id;choices.append(option);
    }
    if(!rangeOptions.size){const option=node('option','No saved range results');option.value='';choices.append(option);}
    choices.value=rangeOptions.has(selected)?selected:rangeOptions.keys().next().value||'';
    open.disabled=!choices.value;
  }
  refreshChoices();
  async function openResult(entry){
    const generation=++viewGeneration;output.replaceChildren();message.textContent='Opening the saved range analysis…';
    try{
      const reply=await api('/api/workflow/gegi-candidates/range?'+new URLSearchParams({...binding,range_id:entry.range_id,range_sha256:entry.range_sha256}));
      if(!current()||generation!==viewGeneration)return;
      if(Object.keys(binding).some(key=>reply[key]!==binding[key])||reply.range_result.range_sha256!==entry.range_sha256||
        reply.range_result.range_id!==entry.range_id||reply.result.input_sha256!==map.analysis_sha256)throw Error('The range result belongs to a different saved map.');
      message.textContent=entry.current_solver?'Saved range analysis opened.':'Archived range analysis opened with its recorded solver version.';
      output.append(renderCandidateRange(reply.result));
    }catch(error){if(current()&&generation===viewGeneration)message.textContent=error.message;}
  }
  choices.onchange=()=>{++viewGeneration;output.replaceChildren();open.disabled=!choices.value;};
  open.onclick=()=>openResult(rangeOptions.get(choices.value));
  run.onclick=async()=>{
    const low=Number(min.value),high=Number(max.value);
    if(!Number.isFinite(low)||!Number.isFinite(high)||low<=0||high<=low){message.textContent='Choose a positive increasing distance search.';return;}
    loading=true;run.disabled=true;message.textContent='Preparing range analysis from saved fits…';
    try{
      const reply=await api('/api/workflow/gegi-candidates/range',{...binding,radius_min_mm:low,radius_max_mm:high,profile_background:nuisance.checked===true});
      if(!current())return;
      if(reply.reused){rangeOptions.set(reply.range_id,reply);refreshChoices();choices.value=reply.range_id;await openResult(reply);}
      else await inspectCandidateJob(map.name);
    }catch(error){if(current())message.textContent=error.message;}
    finally{loading=false;candidateRangeRefresh?.(candidateJob);}
  };
  candidateRangeRefresh=job=>{
    if(!current())return;
    const range=job?.range_analysis;
    run.disabled=loading||busy||active||job?.analysis?.status==='running'||range?.status==='running';
    if(range?.analysis_sha256!==map.analysis_sha256||range.status===lastStatus)return;
    lastStatus=range.status;
    if(range.status==='running')message.textContent='Analyzing three-dimensional range from saved candidates…';
    if(range.status==='failed')message.textContent=range.error;
    if(range.status==='completed'&&range.range_result){
      const entry=range.range_result;
      rangeOptions.set(entry.range_id,entry);refreshChoices();choices.value=entry.range_id;
      message.textContent='Range analysis complete. Open the saved result.';
    }
  };
  candidateRangeRefresh(candidateJob);
  return region;
}
function renderCandidateRange(result){
  const region=node('div'),view=node('div'),window=node('select'),label=node('label','Measured energy window');
  const names={'661.657_keV':'661.657 keV','1173.23_keV':'1173.23 keV','1332.49_keV':'1332.49 keV',cobalt_both_lines:'Co-60 line windows combined'};
  const fitNames={primary:'Fixed background',no_extra_background:'No extra background',first_clock_half:'First clock half',
    second_clock_half:'Second clock half',profiled_background:'Profiled background'};
  for(const key of Object.keys(result.fits)){const option=node('option',names[key]);option.value=key;window.append(option);}
  window.value='661.657_keV';label.append(window);region.append(label,view);
  const value=number=>Number.isFinite(number)?number.toFixed(2):'Unavailable';
  function paint(){
    const row=result.fits[window.value];view.replaceChildren();
    if(row.status!=='conditional_scores_computed'){
      view.append(node('p',row.selected_triggers+' measured triggers. At least one clock half has no usable cone geometry.','notice'));return;
    }
    const account=row.accounting,table=node('table'),body=node('tbody'),head=node('thead'),labels=node('tr');
    for(const text of ['Model','X, Y, Z (mm)','Center distance (mm)','Range score support','Gain over infinite distance']){
      const cell=node('th',text);cell.scope='col';labels.append(cell);
    }
    head.append(labels);table.append(head,body);
    for(const [key,fit] of Object.entries(row.fits)){
      const cells=node('tr'),profile=fit.profile_diagnostic;
      const status=profile.far_field_supported?'Infinite distance within score drop':profile.lower_open||profile.upper_open?
        'Open at search '+(profile.lower_open&&profile.upper_open?'bounds':profile.lower_open?'minimum':'maximum'):'Closed on sampled range';
      for(const text of [fitNames[key],fit.position_mm.map(value).join(', '),value(fit.center_distance_mm),status,value(fit.score_gain_over_far_field)])cells.append(node('td',text));
      body.append(cells);
    }
    const profiled=row.fits.profiled_background,primary=row.fits.primary,scroll=node('div',undefined,'dual-pixel-scroll');scroll.append(table);
    const profileDifference=profiled?' · Profiled versus fixed background '+value(Math.hypot(...profiled.position_mm.map((v,i)=>v-primary.position_mm[i])))+' mm.':'.';
    view.append(node('p',account.selected_triggers+' original triggers · '+account.triggers_with_geometry+' with geometry · '+
      account.allowed_saved_geometry_orders+' saved orders · '+value(account.projected_trigger_mass)+' projected and '+
      value(account.unresolved_trigger_mass)+' unresolved trigger units. Clock halves '+row.split_trigger_counts.join(' / ')+'.'),
      scroll,node('p','Position disagreement · Clock halves '+value(row.split_position_difference_mm)+' mm · Removing extra background '+
        value(row.background_position_difference_mm)+' mm'+profileDifference,'notice'),
      candidateRangePlot(row.fits,fitNames,result.model.radial_search_mm),
      featureDetails('Original selected trigger IDs and solver provenance',{selected_original_trigger_ids:row.selected_original_trigger_ids,
        source_sha256:result.source_sha256,input_bindings:result.input_bindings,software:result.software,model:result.model}));
  }
  window.onchange=paint;paint();return region;
}
function candidateRangePlot(fits,names,bounds){
  const wrapper=node('figure'),canvas=node('canvas'),caption=node('figcaption');
  canvas.width=680;canvas.height=250;canvas.style.maxWidth='100%';canvas.setAttribute('role','img');
  canvas.setAttribute('aria-label','Radial profile score loss versus center distance in millimeters on a logarithmic axis');
  const ctx=canvas.getContext('2d'),colors=['#12539c','#a12f26','#287444','#74429a','#8d5e0d'];
  const series=Object.entries(fits),drop=fits.primary.profile_diagnostic.score_drop;
  const x=distance=>54+(Math.log(distance/bounds[0])/Math.log(bounds[1]/bounds[0]))*595;
  const maxLoss=Math.max(drop*1.2,...series.flatMap(([,fit])=>fit.radial_profile.map(row=>row.loss_from_best_score)));
  const y=loss=>210-(Math.log1p(loss)/Math.log1p(maxLoss))*178;
  const line=(x0,y0,x1,y1)=>{ctx.beginPath();ctx.moveTo(x0,y0);ctx.lineTo(x1,y1);ctx.stroke();};
  ctx.strokeStyle='#657585';ctx.fillStyle='#354457';ctx.font='13px sans-serif';
  line(54,32,54,210);line(54,210,649,210);line(54,y(drop),649,y(drop));
  ctx.fillText('Score loss (log(1 + loss) scale)',8,20);
  for(const tick of [0,drop,10,50,maxLoss].filter((v,i,a)=>v<=maxLoss&&a.indexOf(v)===i)){
    ctx.fillText(tick===maxLoss?tick.toPrecision(3):String(tick),8,y(tick)+4);
  }
  ctx.fillText(String(bounds[0]),54,229);ctx.fillText(String(bounds[1]),610,229);ctx.fillText('Center distance (mm, log scale)',260,245);
  series.forEach(([key,fit],i)=>{
    const color=colors[i],profile=fit.radial_profile;ctx.strokeStyle=color;ctx.lineWidth=1.8;ctx.beginPath();
    profile.forEach((row,index)=>{const method=index?'lineTo':'moveTo';ctx[method](x(row.center_distance_mm),y(row.loss_from_best_score));});
    ctx.stroke();const legend=node('span',names[key]+(i===series.length-1?'':' · '));legend.style.color=color;caption.append(legend);
  });
  wrapper.append(canvas,caption,node('p','The line at score loss '+drop+' is a descriptive comparison threshold. Profiles and coordinate estimates are uncalibrated.','muted'));
  return wrapper;
}
function lateralFallbackText(reason){
  return {no_lateral_calibration_for_either_site:'without a lateral grid at either site',
    no_lateral_waveform_fit:'without a lateral waveform fit',
    lateral_optimizer_did_not_converge:'with a failed lateral optimizer'}[reason]||reason.replaceAll('_',' ');
}
function candidateCompatibilityDetails(fit){
  const details=node('details'),compatibility=fit.compatibility,table=node('table');
  details.append(node('summary','Residuals across all 34 electrodes'),
    node('p','ADC residuals are measured minus modeled after quiet-tail subtraction. The waveform fit used the marked electrodes.','muted'));
  const boundaries=Object.entries(fit.parameter_boundaries||{}).filter(([,value])=>value).map(([key,value])=>key+' '+value);
  if(boundaries.length)details.append(node('p','Fit parameters at a bound · '+boundaries.join(' · '),'muted'));
  const head=node('thead'),labels=node('tr'),body=node('tbody');
  for(const text of ['Electrode','Fit role','RMS (ADC codes)','Signed peak (ADC codes)','Peak time (ns)']){
    const cell=node('th',text);cell.scope='col';labels.append(cell);
  }
  head.append(labels);table.append(head,body);
  for(const [index,id] of compatibility.contact_ids.entries()){
    const row=node('tr');
    for(const value of [id,compatibility.fitted_contact_ids.includes(id)?'Fit electrode':'Other electrode',
      metricValue(compatibility.adc_rms_codes[index]),metricValue(compatibility.adc_peak_codes[index]),
      metricValue(compatibility.adc_peak_time_ns[index])])row.append(node('td',String(value)));
    body.append(row);
  }
  details.append(table);return details;
}
async function loadCandidatePage(offset){
  const job=candidateJob,generation=++candidateEventGeneration;
  if(!job?.report_sha256)return;
  candidateBusy=true;candidateControls();$('gegi-candidate-view').hidden=true;
  try{const reply=await api('/api/workflow/gegi-candidates/list?'+new URLSearchParams({name:job.name,report_sha256:job.report_sha256,offset:String(offset)}));
    if(job!==candidateJob||generation!==candidateEventGeneration)return;
    candidatePage=reply;candidateOffset=offset;
    options('gegi-candidate-trigger',reply.items.map(item=>({id:String(item.trigger_id),label:'Trigger '+item.trigger_id+' · '+metricValue(item.card.energy_keV)+' keV · '+item.reason.replaceAll('_',' ')})));
    candidateContactOptions();
    $('gegi-candidate-page').textContent=reply.total?'Candidates '+(offset+1)+'–'+(offset+reply.items.length)+' of '+reply.total:'No imaging candidates in this acquisition. The full statistics remain above.';
    $('gegi-candidate-view').hidden=false;
    $('gegi-candidate-trigger').disabled=$('gegi-candidate-contact').disabled=!reply.items.length;
    if(reply.items.length){const collecting=[...reply.items[0].card.x_collecting_strips,...reply.items[0].card.y_collecting_strips];if(collecting.length)$('gegi-candidate-contact').value=String(collecting[0]);void loadCandidateEvent();}
    else{$('gegi-candidate-features').replaceChildren();$('gegi-candidate-plots').replaceChildren();$('gegi-candidate-record').textContent='';$('gegi-candidate-event-status').textContent='No candidate waveform was saved.';}
  }catch(e){if(job===candidateJob)candidateStatus(e.message,true);}finally{candidateBusy=false;candidateControls();}
}
function candidateContactOptions(){
  options('gegi-candidate-contact',Array.from({length:34},(_,i)=>({id:String(i+1),label:'Electrode '+(i+1)+(i===16||i===33?' · guard':'')})));
}
async function openCandidateWaveforms(row){
  const trigger=$('gegi-candidate-trigger'),contact=$('gegi-candidate-contact'),view=$('gegi-candidate-view');
  const id=String(row.original_trigger_id);
  if(!Array.from(trigger.children).some(option=>option.value===id)){
    const option=node('option','Trigger '+id+' · '+metricValue(row.energy_keV)+' keV · peak contributor');option.value=id;trigger.append(option);
  }
  trigger.value=id;candidateContactOptions();
  contact.value=String(row.pairings.find(pair=>pair.orders.some(order=>order.peak_cell_mass>0))?.cells[0][0]??1);
  trigger.disabled=contact.disabled=false;view.hidden=false;
  if(!candidatePage)$('gegi-candidate-page').textContent='Original trigger selected from the saved image.';
  view.focus?.({preventScroll:true});view.scrollIntoView?.({behavior:'smooth'});
  await loadCandidateEvent();
}
async function loadCandidateEvent(){
  const job=candidateJob,trigger_id=$('gegi-candidate-trigger').value,contact_id=$('gegi-candidate-contact').value,generation=++candidateEventGeneration;
  if(!job?.report_sha256||!trigger_id||!contact_id)return;
  $('gegi-candidate-event-status').textContent='Reading original trigger '+trigger_id+' · electrode '+contact_id+'…';
  $('gegi-candidate-plots').replaceChildren();$('gegi-candidate-features').replaceChildren();
  $('gegi-candidate-record').textContent='';
  try{const reply=await api('/api/workflow/gegi-candidates/event?'+new URLSearchParams({name:job.name,report_sha256:job.report_sha256,trigger_id,contact_id}));
    if(job!==candidateJob||generation!==candidateEventGeneration||String(reply.trigger_id)!==trigger_id||String(reply.contact_id)!==contact_id)return;
    const channel=reply.channel,metrics=node('div',undefined,'metrics');
    for(const [label,key]of [['Fast area · keV-equivalent','fast_signal_keV_equiv'],['Slow energy · keV','slow_energy_keV'],['Preamp CFD50 · ns','preamp_cfd50_ns']]){const item=node('span',label);item.append(node('strong',metricValue(channel[key])));metrics.append(item);}
    $('gegi-candidate-features').append(metrics,node('p','Channel flags: '+(channel.flags.join(', ')||'none')+'. Fast area: 0–240 ns; slow energy: 880–980 ns.','muted'));
    $('gegi-candidate-event-status').textContent='Original trigger '+trigger_id+' · electrode '+contact_id+' · '+reply.trace.time_ns.length+' saved ADC samples at '+reply.sample_period_ns+' ns intervals.';
    for(const [key,label,unit]of [['preamp_V','Preamplifier ADC','V'],['fast_V','Fast filter','V'],['slow_keV','Slow filter','keV']])$('gegi-candidate-plots').append(gegiTracePlot(reply.trace,key,label,unit,{digital:true,triggerRelative:true,sampleCaption:reply.filter_scope}));
    $('gegi-candidate-record').textContent=JSON.stringify({trigger_id:reply.trigger_id,card:reply.card,identities:reply.identities,channel:reply.channel,event_flags:reply.event_flags},null,2);
  }catch(e){if(job===candidateJob&&generation===candidateEventGeneration)$('gegi-candidate-event-status').textContent=e.message;}
}
$('gegi-candidate-refresh').onclick=refreshCandidateRuns;
$('gegi-candidate-start').onclick=startCandidateRun;
$('gegi-candidate-stop').onclick=()=>manageCandidateRun('stop');
$('gegi-candidate-resume').onclick=()=>manageCandidateRun('resume');
$('gegi-candidate-mode').onchange=candidateModeFields;
candidateModeFields();
$('gegi-candidate-job').onchange=()=>{++candidateGeneration;++candidateEventGeneration;++candidatePlaneGeneration;candidateJob=null;candidatePage=null;$('gegi-candidate-view').hidden=true;$('gegi-candidate-imaging').hidden=true;$('gegi-candidate-map-view').replaceChildren();$('gegi-candidate-map').value='';$('gegi-candidate-summary').replaceChildren();const name=$('gegi-candidate-job').value;if(name)void inspectCandidateJob(name,true);else candidateStatus('Choose a saved acquisition.');candidateControls();};
$('gegi-candidate-trigger').onchange=$('gegi-candidate-contact').onchange=loadCandidateEvent;
$('gegi-candidate-previous').onclick=()=>loadCandidatePage(Math.max(0,candidateOffset-100));
$('gegi-candidate-next').onclick=()=>loadCandidatePage(candidateOffset+100);
$('gegi-candidate-estimate').onclick=estimateCandidateStorage;
$('gegi-candidate-analyze').onclick=analyzeCandidateRun;
$('gegi-candidate-open-map').onclick=openCandidatePlane;
$('gegi-candidate-calibration').onchange=candidateControls;
$('gegi-candidate-map').onchange=()=>{++candidatePlaneGeneration;$('gegi-candidate-map-view').replaceChildren();candidateControls();};
for(const id of ['gegi-candidate-estimate-count',...['a','b'].flatMap(source=>['gegi-candidate-activity-'+source,...['x','y','z'].map(axis=>'gegi-candidate-'+source+'-'+axis)])])$(id).addEventListener('input',invalidateCandidateEstimate);

function importedGeGIConfig(c,batched){
  const fields=['name','cryostat','detector','source','pose','primary_count','seed','threads','electronics','gamma_energy_keV','source_position_mm'];
  const detector=catalog.detectors.find(d=>d.id===c.detector),source=catalog.sources.find(s=>s.id===c.source);
  if(batched||Object.keys(c).sort().join()!==fields.sort().join()||c.cryostat!=='gegi_cryostat_v1'||c.detector!=='GeGI_3D'||c.source!=='gegi_mono_gamma_v1'||c.pose!=='custom'||!detector?.available||!detectorFits(detector,c.cryostat)||!source?.available||!detector.sources.includes(c.source)||!catalog.cryostats.some(x=>x.id===c.cryostat&&x.available)||!Number.isSafeInteger(c.primary_count)||c.primary_count<1||c.primary_count>10000||!Number.isInteger(c.seed)||c.seed<1||c.seed>2147483646||![1,2].includes(c.threads)||typeof c.name!=='string'||!Number.isFinite(c.gamma_energy_keV)||c.gamma_energy_keV<1||c.gamma_energy_keV>10000||!Array.isArray(c.source_position_mm)||c.source_position_mm.length!==3||!c.source_position_mm.every(Number.isFinite))throw Error('The imported GeGI setup is unavailable. No selection was replaced.');
  if(!c.electronics||Object.keys(c.electronics).sort().join()!==[...catalog.electronics_keys].sort().join())throw Error('Imported electronics fields do not match this application.');
  for(const key of catalog.electronics_keys){const value=c.electronics[key];if(key==='peak_policy'?typeof value!=='string':key.startsWith('peak_gate_')?value!==null&&!Number.isFinite(value):!Number.isFinite(value))throw Error('Imported electronics values have invalid types.');}
  if((c.electronics.peak_gate_start_ns===null)!==(c.electronics.peak_gate_end_ns===null))throw Error('A peak gate requires both boundaries.');
  return {...c,source_position_mm:[...c.source_position_mm],electronics:{...c.electronics}};
}
function resetGeGIResult(){gegiGeneration++;gegiEventGeneration++;gegiImagingGeneration++;if(gegiResult){gegiResult.event=null;gegiResult.imaging=null;}resetGeGIDigital();gegiResult=null;gegiJourney?.destroy?.();gegiJourney=null;$('gegi-result').hidden=true;$('gegi-plots').replaceChildren();$('gegi-journey').replaceChildren();$('gegi-digital-panel').open=false;$('gegi-imaging-panel').open=false;$('gegi-imaging').replaceChildren();$('gegi-imaging-status').textContent='';$('gegi-cones').textContent='';$('gegi-event-record').textContent='';$('gegi-truth-record').textContent='';$('gegi-event-filter').textContent='';$('gegi-event-files').replaceChildren();}
function gegiIdentity(reply,job,derivative=null){
  if(reply?.kind!=='gegi_multichannel_summary_v1'||reply.name!==job.name||reply.configuration_sha256!==job.configuration_sha256||reply.saved_derivative_name!==derivative||typeof reply.results_sha256!=='string'||!/^[a-f0-9]{64}$/.test(reply.results_sha256)||!reply.counts||reply.counts.initial_primaries!==job.selection.primary_count||!Array.isArray(reply.channels)||reply.channels.length!==34||!Array.isArray(reply.event_index)||typeof reply.imaging_available!=='boolean'||Object.hasOwn(reply,'events')||Object.hasOwn(reply,'imaging'))throw Error('Saved GeGI summary and selected run identities differ.');
  const ids=reply.event_index.map(e=>e.event_id);if(ids.some(id=>!Number.isSafeInteger(id)||id<0)||new Set(ids).size!==ids.length||reply.event_index.some(e=>!Number.isFinite(e.truth_edep_keV)||e.truth_edep_keV<=0||Object.keys(e).some(key=>!['event_id','status','truth_edep_keV'].includes(key))))throw Error('Saved GeGI nonzero event census is invalid.');
  if(reply.counts.nonzero_primaries!==undefined&&reply.counts.nonzero_primaries!==ids.length)throw Error('Saved GeGI event count differs from its complete census.');
  if(reply.channels.some((c,i)=>c.id!==i+1)||reply.counts.zero_deposit_primaries+ids.length!==reply.counts.initial_primaries)throw Error('Saved GeGI electrode identities or initial census changed.');
  return reply;
}
function gegiPartIdentity(reply,context,kind){
  const data=context.data;
  if(reply?.kind!==kind||reply.name!==data.name||reply.configuration_sha256!==data.configuration_sha256||reply.saved_derivative_name!==data.saved_derivative_name||reply.results_sha256!==data.results_sha256)throw Error('Saved GeGI response differs from the opened run, derivative or sealed result. Reopen the results.');
  return reply;
}
function gegiPartQuery(context,extra={}){
  return new URLSearchParams({name:context.job.name,results_sha256:context.data.results_sha256,...(context.data.saved_derivative_name?{derivative:context.data.saved_derivative_name}:{}),...extra});
}
function gegiEventIdentity(reply,context,id){
  gegiPartIdentity(reply,context,'gegi_multichannel_event_v1');const event=reply.event,index=context.data.event_index.find(e=>e.event_id===id);
  if(reply.event_id!==id||!event||event.event_id!==id||!index||event.status!==index.status||event.truth_edep_keV!==index.truth_edep_keV||!(Array.isArray(event.channels)&&event.channels.length===34&&event.channels.every((c,i)=>c.contact_id===i+1)||event.channels===null&&event.status==='native_failed'))throw Error('Saved GeGI nonzero event census or channel identities differ from the selected event.');
  return event;
}
function gegiArtifactEntry(job,file,stamp=null){
  const row=node('div');row.append(action('Download '+file,()=>download(job.name,file)));
  row.append(node('small',stamp?stamp.bytes+' bytes · SHA256 '+stamp.sha256:'Exact saved run file; COMPLETE.json binds its saved identity.','muted'));return row;
}
function gegiSavedFiles(job){
  const target=$('gegi-files');target.replaceChildren(node('h3','Actual saved stage data'));
  target.append(node('p','These protected links retrieve original saved files. No simulation starts. Files remain in .local/runs/'+job.name+'/.','muted'));
  const settings=node('details');settings.append(node('summary','Settings, complete channel data and completion'));
  for(const file of ['resolved-config.json','run.json','COMPLETE.json','response/results.json'])settings.append(gegiArtifactEntry(job,file,file.startsWith('response/')?job.stages?.response?.artifacts?.[file.slice(9)]:null));
  settings.append(savedIdentity('Run configuration identity','SHA256 '+job.configuration_sha256+' · radiation seed '+job.selection.seed));target.append(settings);
  const stages=[['geometry','transport/','Geometry and source','Geometry, source coordinates, material assumptions and original commands.'],['radiation','transport/','Radiation transport','Original LH5 transport data; deposits and particle birth times are separate from carrier drift.'],['event_ledger','transport/stream/','Event ledger','Normalized nonzero deposits retain original primary IDs, row references and full-count denominators.'],['response','response/','Charge, readout and reconstruction','Independent timing/calibration, all-channel results and signal-derived candidate cones. Event-specific native files appear above.']];
  for(const [key,base,label,purpose]of stages){const entries=Object.entries(job.stages?.[key]?.artifacts||{}).filter(([ref])=>key!=='response'||!ref.startsWith('events/')&&ref!=='results.json');if(!entries.length)continue;const detail=node('details');detail.append(node('summary',label),node('p',purpose,'muted'));for(const [ref,stamp]of entries)detail.append(gegiArtifactEntry(job,base+ref,stamp));target.append(detail);}
}
function gegiEventFiles(context,event){
  const target=$('gegi-event-files');target.replaceChildren();if(!event)return;
  const original=context.job.stages?.response?.artifacts||{},prefix='events/'+event.event_id;
  for(const [ref,stamp]of Object.entries(original))if(ref===prefix+'.json'||ref===prefix+'.json.sha256'||ref===prefix+'-signals.csv')target.append(gegiArtifactEntry(context.job,'response/'+ref,stamp));
  if(!target.children.length)target.append(node('p','Use response/results.json in the saved stage files for this event’s retained channel and reconstruction records.','muted'));
}
function gegiSignalJourney(context,event){
  gegiJourney?.destroy?.();gegiJourney=null;const target=$('gegi-journey');target.replaceChildren();
  const shared=globalThis.GeGISignalJourney;$('gegi-plots').hidden=!!shared?.mount;$('gegi-channel-control').hidden=!!shared?.mount;
  if(!event||!shared?.mount)return;
  const representative={event_id:event.event_id,group_id:event.group_id??null,status:event.status,channels:event.channels,reconstruction:event.reconstruction??null,native_error:event.native_error??null,original_identity:{run_name:context.job.name,event_id:event.event_id,configuration_sha256:context.job.configuration_sha256},selection_rule:'Selected original nonzero primary ID; candidate display uses saved signal reconstruction.',channel_metadata:context.data.channels};
  const group={representative,initial_primary_denominator:context.data.counts.initial_primaries,counts:context.data.counts};
  gegiJourney=shared.mount(target,{groups:{'Selected saved event':group}},{scope:'student',selectedContactId:Number($('gegi-channel').value),onChannelChange:id=>{$('gegi-channel').value=String(id);showGeGIEvent(true);}});
}
async function openGeGIResult(job,savedSummary=null,derivative=null){
  $('run-stage-details').open=false;openRunDetail();
  const prior=gegiResult?.job.name===job.name?{event:$('gegi-event').value,channel:$('gegi-channel').value}:null;
  showRun(job);resetGeGIResult();const generation=gegiGeneration;resultGeneration++;plotGeneration++;result=null;resetResultOptions();$('result').hidden=true;
  let reply;try{reply=savedSummary??await api('/api/workflow/gegi-summary?'+new URLSearchParams({name:job.name,...(derivative?{derivative}:{})}));}catch(e){if(generation!==gegiGeneration||selectedJob!==job.name)return;throw e;}
  if(generation!==gegiGeneration||selectedJob!==job.name)return;
  const data=gegiIdentity(reply,job,derivative);
  gegiResult={job,data,event:null,imaging:null};$('gegi-result-heading').textContent=job.name+(data.saved_derivative_name?' · reconstruction '+data.saved_derivative_name:'')+' · '+savedSourceLabel(job.selection)+' · source detector xyz ['+job.selection.source_position_mm.join(', ')+'] mm';
  const c=data.counts;$('gegi-counts').textContent=c.initial_primaries+(job.selection.source==='gegi_mono_gamma_v1'?' initial gamma primaries':' initial isotope nuclei')+' · '+c.zero_deposit_primaries+' zero-deposit · '+data.event_index.length+' stored nonzero events · '+metricValue(c.native_failed_groups)+' native failures'+(c.accepted_nonzero_primaries!==undefined?' · '+c.accepted_nonzero_primaries+' readout accepted · '+c.rejected_nonzero_primaries+' readout rejected':'')+'. Initial primaries remain the efficiency denominator.';
  $('gegi-limitations').textContent=(data.reconstruction_algorithm?.kind==='gegi_standalone_saved_reconstruction_v3'?'Shared signed-waveform reconstruction. Depth and imaging require compatible independent waveform templates. Conditional candidates are not validated recovered events. ':'Historical saved reconstruction; displayed maps remain experimental legacy results. ')+(data.limitations||[]).join(' ');
  options('gegi-event',data.event_index.map(e=>({id:String(e.event_id),label:'Primary '+e.event_id+' · '+e.truth_edep_keV+' keV deposited'})));
  options('gegi-channel',data.channels.map(c=>({id:String(c.id),label:c.name+' · contact '+c.id+' · '+c.potential_V+' V'})));
  if(prior&&data.event_index.some(e=>String(e.event_id)===prior.event))$('gegi-event').value=prior.event;
  if(prior&&data.channels.some(c=>String(c.id)===prior.channel))$('gegi-channel').value=prior.channel;
  gegiSavedFiles(job);
  $('gegi-result').hidden=runDetailKind!=='standard';$('gegi-result').scrollIntoView({behavior:'smooth'});await loadGeGIEvent();
}
function clearGeGIEvent(message){
  if(gegiResult)gegiResult.event=null;resetGeGIDigital();gegiSignalJourney(gegiResult,null);$('gegi-plots').replaceChildren();$('gegi-event-files').replaceChildren();$('gegi-event-record').textContent='';$('gegi-truth-record').textContent='';$('gegi-event-filter').textContent='';$('gegi-cones').textContent='';$('gegi-event-summary').textContent=message;
}
async function loadGeGIEvent(){
  const context=gegiResult;if(!context)return;const id=Number($('gegi-event').value),generation=++gegiEventGeneration;
  clearGeGIEvent(context.data.event_index.length?'Loading saved primary '+id+'…':'No nonzero deposits in this run. Counts and the original denominator remain above.');
  if(!context.data.event_index.length)return;
  if(!context.data.event_index.some(e=>e.event_id===id)){$('gegi-event-summary').textContent='Select an offered original primary ID.';return;}
  try{
    const reply=await api('/api/workflow/gegi-event?'+gegiPartQuery(context,{event:String(id)}));
    if(context!==gegiResult||generation!==gegiEventGeneration||Number($('gegi-event').value)!==id)return;
    context.event=gegiEventIdentity(reply,context,id);showGeGIEvent();showGeGIDigital();
  }catch(e){if(context===gegiResult&&generation===gegiEventGeneration)$('gegi-event-summary').textContent='Cannot load saved primary '+id+': '+e.message+' Select another event or reopen results to retry.';}
}
function gegiTracePlot(trace,key,label,unit,{neighbor=null,names=null,digital=false,triggerRelative=false,sampleCaption=null,threshold=null}={}){
  const figure=node('figure',undefined,'plot');figure.append(node('h3',label+' · '+unit));
  const series=[trace,neighbor].map(item=>({times:item?.time_ns,values:item?.[key]}));
  const valid=({times,values})=>Array.isArray(times)&&Array.isArray(values)&&times.length===values.length&&times.length&&times.every(Number.isFinite)&&values.every(Number.isFinite);
  if(!valid(series[0])){figure.append(node('p',(digital?'No digital ':'No saved ')+label.toLowerCase()+' waveform for this channel.','muted'));return figure;}
  if(!valid(series[1]))series.pop();
  let ymin=0,ymax=threshold??0,xmin=Infinity,xmax=-Infinity;
  for(const {times,values} of series){for(const v of values){ymin=Math.min(ymin,v);ymax=Math.max(ymax,v);}xmin=Math.min(xmin,times[0]);xmax=Math.max(xmax,times.at(-1));}
  const span=ymax-ymin||1,xspan=xmax-xmin||1;
  const x=t=>55+620*(t-xmin)/xspan,y=v=>180-145*(v-ymin)/span;
  const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 720 220');svg.setAttribute('role','img');svg.setAttribute('aria-label',label+' against time '+(triggerRelative?'relative to trigger ':'')+'in ns, '+unit);
  if(threshold!==null){
    const line=document.createElementNS(ns,'line');
    for(const [key,value] of Object.entries({x1:x(xmin),x2:x(xmax),y1:y(threshold),y2:y(threshold),stroke:'#645742','stroke-dasharray':'2 4'}))line.setAttribute(key,value);
    svg.append(line);
  }
  series.forEach(({times,values},index)=>{const line=document.createElementNS(ns,'polyline');line.setAttribute('points',values.map((v,i)=>x(times[i])+','+y(v)).join(' '));line.setAttribute('fill','none');line.setAttribute('stroke',index?'#774597':'#007d8a');line.setAttribute('stroke-width',digital?'2':'1.4');if(index)line.setAttribute('stroke-dasharray','5 3');svg.append(line);});
  if(triggerRelative)series.forEach(({times,values},index)=>times.forEach((t,i)=>{
    const value=values[i],mark=document.createElementNS(ns,'circle'),detail=document.createElementNS(ns,'title');
    mark.setAttribute('cx',x(t));mark.setAttribute('cy',y(value));mark.setAttribute('r',2.5);mark.setAttribute('fill',index?'#774597':'#007d8a');
    detail.textContent=(names?names[index]+' · ':'')+t+' ns · '+value+' '+unit;mark.append(detail);svg.append(mark);
  }));
  const tick=v=>digital?String(Number(v.toPrecision(4))):String(v);
  for(const [x,y,text]of [[4,25,tick(ymax)],[4,185,tick(ymin)],[55,207,String(xmin)+' ns'],[555,207,String(xmax)+' ns']]){const t=document.createElementNS(ns,'text');t.setAttribute('x',x);t.setAttribute('y',y);t.textContent=text;svg.append(t);}
  if(triggerRelative){const t=document.createElementNS(ns,'text');t.setAttribute('x',365);t.setAttribute('y',207);
    t.setAttribute('text-anchor','middle');t.textContent='Time relative to trigger';svg.append(t);}
  const caption=sampleCaption||(digital?names[0]+' (solid)'+(series.length===2?' · '+names[1]+' (dashed)':'')+' · '+series[0].times.length+' modeled samples.':'Saved signed samples; '+series[0].times.length+' original analog time points.');
  figure.append(svg,node('figcaption',caption,'muted'));return figure;
}

function resetGeGIDigital(){
  ++gegiDigitalGeneration;if(gegiResult)gegiResult.digital=null;
  $('gegi-digital-status').textContent='Select an original primary to inspect its digital readout.';
  $('gegi-digital-content').hidden=true;
  for(const id of ['gegi-digital-position','gegi-digital-measurements','gegi-digital-plots','gegi-digital-strip','gegi-digital-neighbor'])$(id).replaceChildren();
}
async function showGeGIDigital(){
  const context=gegiResult,event=context?.event;
  if(!$('gegi-digital-panel').open){++gegiDigitalGeneration;return;}
  if(!event||context.digital)return;
  const generation=++gegiDigitalGeneration,status=$('gegi-digital-status');
  status.textContent='Modeling digital readout for original primary '+event.event_id+'…';
  try{
    const reply=await api('/api/workflow/gegi-digital?'+gegiPartQuery(context,{event:String(event.event_id)}));
    if(context!==gegiResult||event!==context.event||generation!==gegiDigitalGeneration||!$('gegi-digital-panel').open)return;
    gegiPartIdentity(reply,context,'gegi_multichannel_digital_v1');
    const digital=reply.digital,channels=digital?.readout?.channels;
    if(reply.event_id!==event.event_id||!(digital?.status==='unavailable'||digital?.status==='available'&&Array.isArray(channels)&&channels.length===34&&channels.every((c,i)=>c.contact_id===context.data.channels[i].id)))throw Error('Digital response differs from the selected primary or electrode census.');
    context.digital=digital;
    if(digital.status==='unavailable'){status.textContent=digital.reason;return;}
    const {readout,topology,position,pairs}=digital,{profile,calibration}=readout;
    status.textContent='Original primary '+event.event_id+' · '+profile.sample_period_ns+' ns samples · signed '+profile.adc_bits+'-bit ADC.'+(readout.status==='partial'?' Incomplete acquisition window.':'');
    $('gegi-digital-calibration').textContent='Synthetic electronics · independent '+calibration.pulser_energy_keV+' keV pulser · slow flat top calibrated in keV and signed fast area in V·ns (also shown in pulser-equivalent keV). Noise '+(readout.noise_seed===null?'disabled.':'seed '+readout.noise_seed+'.');
    renderGeGIDigitalPosition(context,topology,position,pairs,digital.trigger_energies);
    options('gegi-digital-strip',context.data.channels.map(c=>({id:String(c.id),label:c.name+' · contact '+c.id})));
    const first=topology.x_contact_id??topology.collecting_contact_ids[0];
    if(first!==undefined)$('gegi-digital-strip').value=String(first);
    $('gegi-digital-content').hidden=false;gegiDigitalNeighbors();
  }catch(e){if(context===gegiResult&&event===context.event&&generation===gegiDigitalGeneration&&$('gegi-digital-panel').open){context.digital=null;status.textContent='Cannot load digital readout. '+e.message+' Close and reopen this panel to retry.';}}
}
function gegiDigitalValue(value,unit=''){return Number.isFinite(value)?String(Number(value.toPrecision(6)))+(unit?' '+unit:''):'Unavailable';}
function gegiDigitalNeighborNames(context,ids){return (ids||[]).map(id=>context.data.channels.find(c=>c.id===id)?.name||'contact '+id).join(', ');}
function renderGeGIDigitalPosition(context,topology,position,pairs,triggerEnergies){
  const target=$('gegi-digital-position');target.replaceChildren();
  if(Array.isArray(triggerEnergies)){
    target.append(node('h3','Energy per ADC trigger'));
    if(!triggerEnergies.length)target.append(node('p','No two-face trigger in the sampled waveform.'));
    for(const trigger of triggerEnergies){
      const time=gegiDigitalValue(trigger.trigger_time_ns,'ns');
      const reason=trigger.flags.map(flag=>flag.replaceAll('_',' ')).join(', ');
      const energy=Number.isFinite(trigger.energy_keV)?gegiDigitalValue(trigger.energy_keV,'keV'):'Unavailable'+(reason?' · '+reason:'');
      target.append(node('p',time+' · '+energy+' · X sum '+gegiDigitalValue(trigger.x_sum_keV,'keV')+' · Y sum '+gegiDigitalValue(trigger.y_sum_keV,'keV')));
    }
  }
  const collectors=gegiDigitalNeighborNames(context,topology.collecting_contact_ids)||'none';
  target.append(node('p','Strips and guards above '+topology.threshold_keV+' keV · '+collectors+'.'));
  if(topology.status!=='conditional_single_pixel'){
    if(pairs?.pairings?.length)renderGeGIDigitalPairs(context,target,pairs);
    else target.append(node('p','Position unavailable. '+topology.reason,'muted'));
    return;
  }
  target.append(node('p','Conditional single-pixel candidate · '+gegiDigitalValue(topology.energy_keV,'keV')+' averaged across the two faces. Signals on the same pixel can overlap.'));
  if(!position){target.append(node('p','Sub-strip position calibration is unavailable.','muted'));return;}
  const scope={matching_saved_fields:'matching saved simulation fields',nominal_transfer:'nominal transfer to a different field solution',source_identity_mismatch:'incompatible model or field identity'}[position.calibration_source_status];
  const hasEstimate=position.status!=='unavailable'||position.depth?.status==='estimated';
  const coverage=hasEstimate&&position.calibration_pair_coverage==='unverified_cross_strip_transfer'?' · unverified transfer across strip pairs':'';
  target.append(node('p','Sub-strip calibration · '+position.calibration_reference_energy_keV+' keV simulated injections'+(scope?' · '+scope:'')+coverage+'.'+(position.mode==='cfd_conditioned'?' The XY slot tables use the estimated depth.':''),'muted'));
  const list=node('ul');
  for(const family of ['x','y']){
    const axis=position[family];if(!axis)continue;
    const name=gegiDigitalNeighborNames(context,[axis.contact_id]);
    const neighbors=gegiDigitalNeighborNames(context,axis.neighbor_contact_ids);
    const result=Number.isFinite(axis.position_mm)?'slot '+axis.slot+' (0–8) · '+gegiDigitalValue(axis.position_mm,'mm'):'unavailable · '+String(axis.reason||axis.status).replaceAll('_',' ');
    const center=Number.isFinite(axis.position_mm)?' strip center ':' strip-center fallback ';
    list.append(node('li',family.toUpperCase()+' · '+name+center+gegiDigitalValue(axis.strip_center_mm,'mm')+(neighbors?' · neighbors '+neighbors:'')+' · signed ratio '+gegiDigitalValue(axis.ratio)+' · '+result));
  }
  if(position.depth){
    const depth=position.depth,z=Number.isFinite(depth.position_mm)?gegiDigitalValue(depth.position_mm,'mm from detector midplane'):'unavailable · '+depth.status.replaceAll('_',' ');
    list.append(node('li','Z · preamp 50% crossing difference (X − Y) '+gegiDigitalValue(depth.cfd_difference_ns,'ns')+' · '+z));
  }
  target.append(list,node('p','The signed ratio is the higher-coordinate neighbor’s fast signal minus the lower-coordinate neighbor’s fast signal, divided by the collecting strip’s slow energy.','muted'));
  if(position.pooled_axes){
    const compare=node('details'),axes=node('ul');
    compare.append(node('summary','Pooled XY calibration comparison'),node('p','Uses one ratio table per strip across the modeled depths.','muted'));
    for(const family of ['x','y']){
      const axis=position.pooled_axes[family],estimate=Number.isFinite(axis.position_mm)?'slot '+axis.slot+' (0–8) · '+gegiDigitalValue(axis.position_mm,'mm'):'unavailable · '+axis.status.replaceAll('_',' ');
      axes.append(node('li',family.toUpperCase()+' · '+estimate));
    }
    compare.append(axes);target.append(compare);
  }
  if(position.calibration_sha256)target.append(savedIdentity('Sub-strip calibration identity',position.calibration_kind+' · SHA256 '+position.calibration_sha256));
}
function renderGeGIDigitalPairs(context,target,pairs,energyOnly=false){
  const status={unique_energy_pairing:'One energy-compatible pairing',ambiguous_energy_pairing:'Both pairings are energy-compatible',incompatible_energies:'Neither pairing passes the energy tolerance'}[pairs.status]||'Pairing unresolved';
  target.append(node('h3','Two-site strip pairings'),node('p',status+'.'));
  if(pairs.source_line){
    const {energy_keV,measured_minus_line_keV}=pairs.source_line;
    target.append(node('p','Configured photon energy '+gegiDigitalValue(energy_keV,'keV')+' · measured X/Y average '+gegiDigitalValue(pairs.energy_keV,'keV')+' · measured minus configured '+(measured_minus_line_keV>0?'+':'')+gegiDigitalValue(measured_minus_line_keV,'keV')+'.','muted'));
  }
  if(pairs.compton_order_scope&&pairs.compatible_pairing_count>0)target.append(node('p','Compton scatter angles use the measured energy at both sites and assume one fully absorbed photon whose first scatter is on a free electron at rest.','muted'));
  if(pairs.reason)target.append(node('p',pairs.reason.replaceAll('_',' '),'muted'));
  const list=node('ol',undefined,'gegi-pairings');
  for(const pairing of pairs.pairings){
    const row=node('li'),sites=node('ul');
    row.append(node('strong',pairing.energy_compatible?'Energy-compatible':'Energy-incompatible'));
    for(const [index,site] of pairing.sites.entries()){
      const x=energyOnly?dualStripLabel('X',site.x_contact_id):gegiDigitalNeighborNames(context,[site.x_contact_id]);
      const y=energyOnly?dualStripLabel('Y',site.y_contact_id):gegiDigitalNeighborNames(context,[site.y_contact_id]);
      let text='Site '+(index+1)+' · '+x+' '+gegiDigitalValue(site.x_energy_keV,'keV')+' ↔ '+y+' '+gegiDigitalValue(site.y_energy_keV,'keV');
      if(energyOnly?pairing.energy_compatible:site.energy_compatible)text+=' · pair energy '+gegiDigitalValue(site.energy_keV,'keV');
      if(site.position_mm?.length===3&&site.position_mm.every(Number.isFinite))text+=' · modeled XYZ ('+site.position_mm.map(v=>gegiDigitalValue(v)).join(', ')+') mm';
      const cfd=site.position?.depth?.cfd_difference_ns;
      if(Number.isFinite(cfd))text+=' · X − Y timing '+gegiDigitalValue(cfd,'ns');
      const item=node('li',text);
      if(energyOnly&&pairing.pixel_depths?.[index])item.append(node('p',dualApparentDepth(pairing.pixel_depths[index])));
      sites.append(item);
    }
    row.append(sites);
    if(pairing.energy_compatible){
      if(pairing.compton_orders?.length){
        const orders=node('ul');
        for(const order of pairing.compton_orders){
          const [first,second]=order.site_index_order.map(i=>'Site '+(i+1));
          const outcome=order.kinematically_allowed
            ?'allowed by energy model · scatter angle '+gegiDigitalValue(order.half_angle_deg)+'°'
            :'excluded by energy model';
          orders.append(node('li',first+' → '+second+' · '+outcome));
        }
        const allowed=pairing.compton_orders.filter(order=>order.kinematically_allowed).length;
        row.append(node('p',energyOnly?allowed+' of '+pairing.compton_orders.length+' interaction orders allowed by energy':
          'Candidate interaction orders from energy'),orders);
      }else row.append(node('p','Energy-based interaction orders are unavailable in this record.','muted'));
      if(!energyOnly){
        const coneCount=pairing.cones?.length||0;
        const missingPosition=pairing.sites.some(site=>site.position_mm?.length!==3||!site.position_mm.every(Number.isFinite));
        const spatial=coneCount?coneCount+' conditional spatial cone'+(coneCount===1?'':'s')+'.'
          :missingPosition?'Spatial cone unavailable. Both sites need modeled XYZ positions.'
          :'Spatial cone unavailable for this pairing.';
        row.append(node('p',spatial,'muted'));
      }
    }
    if(pairing.flags?.length)row.append(node('p',pairing.flags.map(f=>f.replaceAll('_',' ')).join(' · '),'muted'));
    list.append(row);
  }
  target.append(list);
}
function gegiDigitalNeighbors(){
  const context=gegiResult;if(!context?.digital)return;
  const strip=context.data.channels.find(c=>c.id===Number($('gegi-digital-strip').value));
  const neighbors=strip&&!strip.guard?context.data.channels.filter(c=>!c.guard&&c.family===strip.family&&Math.abs(c.strip_index-strip.strip_index)===1):[];
  options('gegi-digital-neighbor',neighbors.length?neighbors.map(c=>({id:String(c.id),label:c.name+' · contact '+c.id})):[{id:'',label:'No adjacent strip'}]);
  $('gegi-digital-neighbor').disabled=!neighbors.length;renderGeGIDigitalPlots();
}
function renderGeGIDigitalPlots(){
  const context=gegiResult,readout=context?.digital?.readout;if(!readout)return;
  const ids=['gegi-digital-strip','gegi-digital-neighbor'].map(id=>Number($(id).value));
  const channels=ids.map(id=>readout.channels.find(c=>c.contact_id===id)),names=ids.map(id=>gegiDigitalNeighborNames(context,[id]));
  const target=$('gegi-digital-measurements');target.replaceChildren();
  channels.forEach((c,i)=>{if(c)target.append(node('p',names[i]+' · slow '+gegiDigitalValue(c.slow_energy_keV,'keV')+' · signed fast '+gegiDigitalValue(c.fast_area_V_ns,'V·ns')+' · '+gegiDigitalValue(c.fast_signal_keV_equiv,'keV equivalent')+' · preamp 50% timing '+gegiDigitalValue(c.preamp_cfd50_ns,'ns')+(c.flags.length?' · '+c.flags.map(f=>f.replaceAll('_',' ')).join(', '):''),'muted'));});
  const plots=$('gegi-digital-plots');plots.replaceChildren();
  for(const [key,label,unit] of [['adc_code','Preamplifier ADC','signed code'],['fast_V','Fast shaped signal','V'],['slow_V','Slow trapezoid','V']]){
    plots.append(gegiTracePlot(channels[0]?.trace,key,label,unit,{neighbor:channels[1]?.trace,names,digital:true}));
  }
}
function showGeGIEvent(preserveJourney=false){
  const context=gegiResult;if(!context||!context.event)return;const event=context.event,id=Number($('gegi-channel').value),meta=context.data.channels.find(c=>c.id===id);$('gegi-plots').replaceChildren();
  if(!preserveJourney)gegiSignalJourney(context,event);gegiEventFiles(context,event);
  const channel=(event.channels||[]).find(c=>c.contact_id===id);$('gegi-event-summary').textContent='Original primary '+event.event_id+' · truth Edep '+event.truth_edep_keV+' keV · '+(event.status||'recorded')+' · '+(meta?.name||'channel '+id)+' reconstructed energy '+metricValue(channel?.reconstructed_energy_keV)+' keV'+(channel?.rejection_reason?' · '+channel.rejection_reason:'')+'. Each strip family measures the same deposited energy; X and Y energies are not added together.';
  const use=event.reconstruction?.signal_use;
  if(use){const spectrum=use.spectroscopy;$('gegi-event-summary').textContent+=' Pulse-group energy: '+(spectrum.accepted?metricValue(spectrum.energy_keV)+' keV (fixed-gain X/Y average, including collecting guards)':'unavailable · '+spectrum.reason.replaceAll('_',' '))+'. Imaging: '+(use.conditional_candidate_count?use.conditional_candidate_count+' conditional candidates':'no supported candidate')+'.';if(use.guard.collecting_ids.length)$('gegi-event-summary').textContent+=' Guard collection contributes energy without a strip position.';if(use.adjacent_strip_pairs.length)$('gegi-event-summary').textContent+=' Adjacent strips are retained separately; charge sharing and interaction count remain unresolved.';}
  else if(event.reconstruction?.kind==='gegi_saved_signal_hypotheses_v3')$('gegi-event-summary').textContent+=' Reconstruction: '+(event.reconstruction.reason||event.reconstruction.status).replaceAll('_',' ')+'.';
  $('gegi-event-filter').textContent=context.job.name+(context.data.saved_derivative_name?' · reconstruction derivative '+context.data.saved_derivative_name:'')+' · original primary '+event.event_id+' · contact '+id+'. Raw LH5: evtid = '+event.event_id+'; normalized transport/stream/events.jsonl and response/results.json: event_id = '+event.event_id+'. Channel records: contact_id = '+id+'. Transport deposits use detector position_mm (mm), energy_keV (keV) and time_ns (ns); charge/readout plots use their saved local time origin in ns.'+(context.data.saved_derivative_name?' Signal and stage files remain in the original run; reconstruction records come from this derivative’s results.json.':'');
  $('gegi-event-record').textContent=JSON.stringify({event_id:event.event_id,status:event.status,reconstruction:event.reconstruction??null,channel:channel||null},null,2);
  $('gegi-truth-record').textContent=JSON.stringify({purpose:'Transport truth for evaluation only; not used to select a reconstructed strip pairing or scatter order.',event_id:event.event_id,truth_edep_keV:event.truth_edep_keV,primary_time_ns:event.primary_time_ns??null,steps:event.steps??null,transport_flags:event.transport_flags??null},null,2);
  if(!$('gegi-plots').hidden){if(channel?.trace)for(const [key,label,unit]of [['charge_fC','Induced charge','fC'],['current_nA','Induced current','nA'],['preamp_V','Preamplifier','V'],['shaped_V','Shaped signal','V']])$('gegi-plots').append(gegiTracePlot(channel.trace,key,label,unit));else $('gegi-plots').append(node('p','No saved native/readout waveform for this event and channel. Failed quantities remain unknown.','muted'));}
  showGeGICones();
}
function showGeGICones(){
  const context=gegiResult,event=context?.event;if(!event){$('gegi-cones').textContent='No selected event loaded.';return;}
  if(!context.imaging){$('gegi-cones').textContent='Open this panel to load the saved run image and selected-event cone records.';return;}
  const cones=(context.imaging.cones||[]).filter(c=>c.event_id===event.event_id);$('gegi-cones').textContent=cones.length?JSON.stringify(cones,null,2):'No accepted Compton cone for this event. '+(event.reconstruction?.reason||event.rejection_reason||'Read the saved candidate and ambiguity counts.');
}
async function showGeGIImaging(){
  const context=gegiResult;if(!context||!$('gegi-imaging-panel').open){++gegiImagingGeneration;return;}
  if(context.imaging){renderGeGIImaging();showGeGICones();return;}
  if(!context.data.imaging_available){$('gegi-imaging-status').textContent='No saved run imaging is available.';return;}
  const generation=++gegiImagingGeneration;$('gegi-imaging').replaceChildren();$('gegi-imaging-status').textContent='Loading saved run imaging…';
  try{
    const reply=gegiPartIdentity(await api('/api/workflow/gegi-imaging?'+gegiPartQuery(context)),context,'gegi_multichannel_imaging_v1');
    if(context!==gegiResult||generation!==gegiImagingGeneration||!$('gegi-imaging-panel').open)return;
    if(!reply.imaging||typeof reply.imaging!=='object')throw Error('Saved GeGI imaging data are unavailable.');
    context.imaging=reply.imaging;renderGeGIImaging();showGeGICones();
  }catch(e){if(context===gegiResult&&generation===gegiImagingGeneration&&$('gegi-imaging-panel').open)$('gegi-imaging-status').textContent='Cannot load saved run imaging: '+e.message+' Close and reopen this panel to retry.';}
}
function renderGeGIImaging(){
  const image=gegiResult?.imaging;if(!image||!$('gegi-imaging-panel').open)return;const target=$('gegi-imaging');target.replaceChildren();
  if(image.method==='gegi_standalone_saved_reconstruction_v3'){
    $('gegi-imaging-status').textContent=metricValue(image.conditional_candidate_groups)+' groups with conditional imaging candidates · '+metricValue(image.validated_recovered_groups)+' validated recovered groups. Pulse energy remains available when both faces have accepted readout, even if imaging is unresolved. Open an event to inspect its energy and saved signals.';
    target.append(node('p','No source map is created from unsupported depth or unvalidated conditional hypotheses. Fixed energy readout, all electrode signals and the exact saved reconstruction reason remain available.','muted'));return;
  }
  $('gegi-imaging-status').textContent='Saved legacy map · experimental reconstruction. '+(image.method||'Recorded Compton reconstruction')+' · '+metricValue(image.accepted_events)+' accepted events · '+metricValue(image.rejected_events)+' rejected · '+metricValue(image.ambiguous_events)+' ambiguous. '+(image.limitations||[]).join(' ');
  const x=image.azimuth_deg,y=image.elevation_deg,values=image.values;if(!Array.isArray(x)||!x.length||!Array.isArray(y)||!y.length||!Array.isArray(values)||values.length!==y.length||!x.every(Number.isFinite)||!y.every(Number.isFinite)||values.some(row=>!Array.isArray(row)||row.length!==x.length||!row.every(v=>Number.isFinite(v)&&v>=0))){target.append(node('p','No saved direction map is available. Candidate counts and cone records are retained.','muted'));return;}
  let maximum=0;for(const row of values)for(const v of row)maximum=Math.max(maximum,v);
  const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 720 380');svg.setAttribute('role','img');svg.setAttribute('aria-label','Compton backprojection, azimuth and elevation in detector coordinates');
  for(let j=0;j<y.length;j++)for(let i=0;i<x.length;i++){const rect=document.createElementNS(ns,'rect'),fraction=maximum?values[j][i]/maximum:0;rect.setAttribute('x',55+620*i/x.length);rect.setAttribute('y',20+300*(y.length-j-1)/y.length);rect.setAttribute('width',620/x.length+.1);rect.setAttribute('height',300/y.length+.1);rect.setAttribute('fill','rgb('+Math.round(242-225*fraction)+','+Math.round(247-115*fraction)+','+Math.round(249-105*fraction)+')');svg.append(rect);}
  for(const [px,py,text]of [[55,345,'Azimuth '+x[0]+'°'],[525,345,String(x[x.length-1])+'°'],[4,25,String(y[y.length-1])+'°'],[4,320,String(y[0])+'°'],[55,372,'Elevation increases upward; detector +z is +90°.']]){const label=document.createElementNS(ns,'text');label.setAttribute('x',px);label.setAttribute('y',py);label.textContent=text;svg.append(label);}target.append(svg,node('p','Saved backprojection values; maximum '+maximum+'. This image uses reconstructed channel information. Truth deposit positions remain separate.','muted'));
}
$('gegi-event').onchange=loadGeGIEvent;$('gegi-channel').onchange=()=>showGeGIEvent();$('gegi-imaging-panel').ontoggle=showGeGIImaging;
$('gegi-digital-panel').ontoggle=showGeGIDigital;$('gegi-digital-strip').onchange=gegiDigitalNeighbors;$('gegi-digital-neighbor').onchange=renderGeGIDigitalPlots;
async function openResult(job){$('run-stage-details').open=false;openRunDetail();showResultTab('overview');if(job.workflow_kind==='local_gegi_workflow_v1')return openGeGIResult(job);if(job.execution_contract==='serial_batches_v3')return openBatchResult(job);const prior=result?.job.name===job.name&&result?.job.configuration_sha256===job.configuration_sha256?{id:Number($('event').value),groupIndex:Number($('group').value)}:null;showRun(job);resetResultOptions();const generation=++resultGeneration;plotGeneration++;result=null;$('plots').replaceChildren();$('result').hidden=true;try{const responses=await Promise.all([artifact(job.name,'response/run.json'),artifact(job.name,'COMPLETE.json')]);const [report,complete]=await Promise.all(responses.map(r=>r.json()));if(generation!==resultGeneration||selectedJob!==job.name)return;const summaryHash=complete.artifacts?.['response/summary.html']?.sha256;if(complete.configuration_sha256!==job.configuration_sha256||!summaryHash||report.artifacts?.['summary.html']!==summaryHash||report.source_id!==undefined&&report.source_id!==job.selection.source)throw Error('Saved result and selected run identities differ.');let records=[],traces=[];if(report.cases){records=report.cases;}else{const files=await Promise.all([artifact(job.name,'response/scalars.jsonl'),artifact(job.name,'response/traces.jsonl')]);const texts=await Promise.all(files.map(r=>r.text()));if(generation!==resultGeneration||selectedJob!==job.name)return;[records,traces]=texts.map(s=>s.trim().split('\n').filter(Boolean).map(JSON.parse));}if(generation!==resultGeneration||selectedJob!==job.name)return;result={job,report,records,traces,summaryHash};showResultSummary();loadResultOptions(result);$('batch-navigation').hidden=true;savedArtifacts(job,complete);$('result').hidden=runDetailKind!=='standard';$('result-heading').textContent=job.name+' · '+job.selection.detector+' · '+savedSourceLabel(job.selection)+' · '+job.selection.primary_count+' original primaries';const ids=selectablePrimaryIds(records);options('event',primaryOptions(ids,result.records,result.traces));const choice=prior&&ids.includes(prior.id)?prior:firstSavedWaveform(records,traces);if(choice)$('event').value=String(choice.id);if(ids.length)showEvent(choice?.groupIndex);else clearSavedSelection('No nonzero deposits in this run. Initial counts and denominator are retained.');$('result').scrollIntoView({behavior:'smooth'});}catch(e){if(generation===resultGeneration&&selectedJob===job.name)throw e;}}
function resetSpectrum(){spectrumGeneration++;if(result)result.spectrum=null;$('spectrum-panel').hidden=true;$('spectrum-panel').open=false;$('spectrum-status').textContent='';$('spectrum-content').replaceChildren();}
function resetResultOptions(){resultOptionsGeneration++;if(result)result.options=null;for(const id of ['feature-panel','acquisition-panel']){$(id).hidden=true;$(id).open=false;}resetFeatures();resetAcquisition();resetSpectrum();$('result-options-status').textContent='';}
function resultOptionsIdentity(reply,job){if(reply.kind!=='local_saved_result_options_v1'||reply.name!==job.name||reply.configuration_sha256!==job.configuration_sha256||typeof reply.feature_export_present!=='boolean'||typeof reply.acquisition_export_present!=='boolean'||!(reply.spectrum_file===null&&reply.spectrum_scope===null||['results/histograms.json','response/histograms.json'].includes(reply.spectrum_file)&&reply.spectrum_scope==='full_run'))throw Error('Saved result options and selected run identities differ.');return reply;}
async function resultOptionsRequest(job){return api('/api/workflow/result-options?'+new URLSearchParams({name:job.name}));}
function configureSpectrum(context){
  resetSpectrum();if(context!==result||!context.options)return;
  showResultSummary();
  const options=context.options,page=context.page;
  if(options.spectrum_file)context.spectrum={file:options.spectrum_file,scope:'full_run',initial:context.job.selection.primary_count};
  else if(page){const saved=page.artifacts?.find(a=>/^batches\/b[0-9]{10}\/response\/histograms\.json$/.test(a.file));if(saved)context.spectrum={file:saved.file,scope:'selected_batch',batch:page.batch_index,batch_sha256:page.batch_sha256,initial:page.batch_primary_count};}
  if(!context.spectrum){const note=node('p','No energy spectrum was saved for this run. Open Events & waveforms or Data files to inspect its saved results.','muted');note.dataset.spectrumNote='true';$('result-summary').append(note);return;}
  $('spectrum-panel').hidden=false;$('spectrum-status').textContent=(context.spectrum.scope==='full_run'?'Full saved run':'Selected sealed batch '+context.spectrum.batch)+' · original raw-count histograms.';if(resultTab==='overview')$('spectrum-panel').open=true;
}
async function loadResultOptions(context){
  if(context!==result)return;resetResultOptions();const generation=resultOptionsGeneration,runGeneration=resultGeneration;let received=false;
  try{const raw=await resultOptionsRequest(context.job);received=true;const reply=resultOptionsIdentity(raw,context.job);if(generation!==resultOptionsGeneration||runGeneration!==resultGeneration||context!==result||selectedJob!==context.job.name)return;context.options=reply;$('feature-panel').hidden=!reply.feature_export_present;$('acquisition-panel').hidden=!reply.acquisition_export_present;configureSpectrum(context);if(context.page)batchArtifacts(context.job,context.page);}
  catch(e){if(generation===resultOptionsGeneration&&runGeneration===resultGeneration&&context===result){if(!received){context.options={spectrum_file:null};configureSpectrum(context);}$('result-options-status').textContent='Saved analysis availability could not be checked. Reopen Control to retry. '+e.message;}}
}
function histogramData(histogram,expectedInitial){
  const counts=histogram?.normalization_denominators,integer=n=>Number.isSafeInteger(n)&&n>=0;
  if(histogram?.width_keV!==5||!Array.isArray(histogram.bins)||!counts||!integer(counts.initial_primaries)||counts.initial_primaries<1||counts.initial_primaries!==expectedInitial||!integer(counts.zero_deposit_primaries)||counts.zero_deposit_primaries>counts.initial_primaries||!integer(counts.groups)||!integer(counts.accepted)||counts.accepted>counts.groups||counts.nonzero_primaries!==undefined&&counts.nonzero_primaries!==counts.initial_primaries-counts.zero_deposit_primaries)throw Error('Saved spectrum initial census or pulse counts differ.');
  const allowed=['deposited_per_decay','deposited_per_group','native_terminal_charge','window_charge','preamp_charge_equivalent','analog_shaped_equivalent','accepted_peak_ADC'],seen=new Set(),stages=new Map(allowed.map(s=>[s,new Map()]));
  for(const row of histogram.bins){const key=row.stage+':'+row.bin;if(!stages.has(row.stage)||!integer(row.count)||row.count===0||!Number.isInteger(row.bin)||row.bin< -1||row.bin>1000||seen.has(key)||row.lower_keV!==(row.bin===-1?null:-1000+5*row.bin)||row.upper_keV!==(row.bin===1000?null:-1000+5*(row.bin+1)))throw Error('Saved spectrum contains invalid or repeated bins.');seen.add(key);stages.get(row.stage).set(row.bin,row.count);}
  const series=[{stage:'deposited_per_decay',title:'Truth deposited energy Edep · per initial primary',denominator:counts.initial_primaries,color:'#007d8a'},{stage:'accepted_peak_ADC',title:'Readout equivalent energy · accepted pulse groups',denominator:counts.groups,color:'#b56c15'}].map(item=>({...item,bins:stages.get(item.stage)}));
  for(const item of series){item.total=[...item.bins.values()].reduce((a,b)=>a+b,0);item.underflow=item.bins.get(-1)||0;item.overflow=item.bins.get(1000)||0;item.inside=item.total-item.underflow-item.overflow;item.notSelected=item.denominator-item.total;if(!Number.isSafeInteger(item.total)||item.total!==(item.stage==='deposited_per_decay'?counts.initial_primaries:counts.accepted))throw Error('Saved spectrum totals differ from its complete census.');}
  return {counts,series,width_keV:histogram.width_keV};
}
function histogramFigure(series){
  const figure=node('figure',undefined,'plot');figure.append(node('h3',series.title));
  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg'),add=(tag,attributes,text)=>{const child=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [key,value]of Object.entries(attributes))child.setAttribute(key,String(value));if(text!==undefined)child.textContent=String(text);svg.append(child);return child;};
  const [low,high,width]=series.domain??[-1000,4000,5],binCount=(high-low)/width;
  svg.setAttribute('viewBox','0 0 640 220');svg.setAttribute('role','img');svg.setAttribute('aria-label',series.title+'; energy in keV, raw counts per '+width+' keV bin');
  const left=60,right=620,top=18,bottom=167,maximum=Math.max(1,...[...series.bins.entries()].filter(([bin])=>bin>=0&&bin<binCount).map(([,n])=>n)),x=energy=>left+(energy-low)/(high-low)*(right-left),y=count=>bottom-count/maximum*(bottom-top);
  add('path',{d:'M'+left+','+top+'V'+bottom+'H'+right,fill:'none',stroke:'#69818c'});
  for(let i=0;i<=5;i++){const energy=low+(high-low)*i/5;add('path',{d:'M'+x(energy)+','+bottom+'v5',stroke:'#69818c'});add('text',{x:x(energy),y:bottom+20,'text-anchor':'middle'},energy);}
  add('text',{x:left-8,y:bottom,'text-anchor':'end'},0);add('text',{x:left-8,y:top+4,'text-anchor':'end'},maximum);add('text',{x:10,y:14},'Counts');add('text',{x:(left+right)/2,y:212,'text-anchor':'middle'},'Energy · keV ('+width+' keV bins)');
  // Missing stored bins are zero counts; step back to baseline across every gap.
  let path='M'+x(low)+','+y(0);for(let bin=0;bin<binCount;bin++){const count=series.bins.get(bin)||0;path+='V'+y(count)+'H'+x(low+width*(bin+1));}path+='V'+y(0);
  const curve=add('path',{d:path,fill:'none',stroke:series.color,'stroke-width':1.5});curve.setAttribute('data-series',series.stage);
  const unit=series.denominatorUnit??(series.stage==='deposited_per_decay'?'initial primaries':'pulse groups');
  figure.append(svg,node('figcaption','In range: '+series.inside+' · underflow (< '+String(low).replace('-','−')+' keV): '+series.underflow+' · overflow (≥ '+high+' keV): '+series.overflow+' · not selected: '+series.notSelected+' of '+series.denominator+' '+unit+'.','muted'));return figure;
}
async function loadSpectrum(){
  const context=result,descriptor=context?.spectrum,generation=++spectrumGeneration;if(!descriptor||$('spectrum-panel').hidden||!$('spectrum-panel').open)return;$('spectrum-content').replaceChildren();$('spectrum-status').textContent='Reading saved spectrum…';
  try{const response=await artifact(context.job.name,descriptor.file),histogram=await response.json();if(generation!==spectrumGeneration||context!==result||context.spectrum!==descriptor||selectedJob!==context.job.name||!$('spectrum-panel').open)return;const data=histogramData(histogram,descriptor.initial),counts=data.counts;if(descriptor.scope==='full_run'){context.summaryCounts=counts;showResultSummary(counts);}$('spectrum-status').textContent=(descriptor.scope==='full_run'?'Full saved run':'Selected sealed batch '+descriptor.batch)+' · '+counts.initial_primaries+' initial primaries (efficiency denominator) · '+counts.zero_deposit_primaries+' zero-deposit · '+(counts.initial_primaries-counts.zero_deposit_primaries)+' nonzero-deposit · '+counts.groups+' pulse groups · '+counts.accepted+' accepted.';const content=$('spectrum-content');content.append(node('p','Native failed groups: '+metricValue(counts.native_failed_groups)+' · readout rejected: '+metricValue(counts.readout_rejected)+' · saturated: '+metricValue(counts.saturated)+'. Counts are saved totals, not efficiencies or physical resolution. No fit, normalization or energy rescaling is applied.','muted'));const plots=node('div',undefined,'plot-grid');for(const series of data.series)plots.append(histogramFigure(series));content.append(plots,node('p','Truth includes the zero-deposit initial primaries. Reconstructed energy includes accepted pulse groups only; one primary may create several groups. This spectrum reads '+descriptor.file+' independently of the event page.','muted'));}
  catch(e){if(generation===spectrumGeneration&&context===result&&context.spectrum===descriptor&&$('spectrum-panel').open)$('spectrum-status').textContent='Saved spectrum unavailable. '+e.message;}
}
$('spectrum-panel').ontoggle=()=>{if($('spectrum-panel').open&&!$('spectrum-panel').hidden)loadSpectrum();else{spectrumGeneration++;$('spectrum-content').replaceChildren();}};
const savedFileGroups=[
  ['Settings and completion','resolved-config.json stores the exact saved setup. run.json and stage receipts record execution and inputs; COMPLETE.json records completed files. Use this run’s settings, independent of the next-run form.'],
  ['Raw radiation and geometry','transport/truth.lh5 contains the original radiation tables. run.mac records radiation commands and transport/run.json records execution. Geometry and source receipts describe the world and source. Radiation deposits and particle birth records do not describe carrier drift or complete particle trajectories.'],
  ['Event ledger and initial census','New nonzero-only decays/events JSONL chunks retain original nonzero IDs, daughter timing and raw-row references. Historical dense chunks may include zero deposits. manifest.json retains the complete initial/zero/nonzero census, each column’s units, coordinate transforms; transport/truth.lh5 retains the complete original radiation data. raw_row_index/raw_row_indices are zero-based within the referenced original table.'],
  ['Charge response and endpoints','response/truth.jsonl retains normalized deposits and identities used for charge response. signals.csv retains signed induced-equivalent charge samples in keV and time_since_origin_ns in ns. endpoints.jsonl/csv retains carrier endpoint, contact and cap flags; a small remaining signal does not establish complete collection.'],
  ['Readout and independent calibration','scalars.jsonl/csv retains primary summaries and pulse-group results, including peak ADC, reconstructed energy and rejection flags. traces.jsonl contains retained current samples with original-bin edges and analog preamp/shaper samples when saved; previews may be unavailable. response/run.json, readout-config.json and profile.json record readout settings and independent injection calibration; separate calibration files are listed when present. Truth Edep and reconstructed Erec remain different quantities.']
];
function savedFileGroup(file){if(/(^|\/)transport\/stream\//.test(file))return 2;if(/(^|\/)transport\//.test(file))return 1;if(/(^|\/)response\/(truth\.jsonl|signals\.csv|endpoints\.(jsonl|csv))$/.test(file))return 3;if(/(^|\/)(response|electronics)\//.test(file)||file==='results/histograms.json')return 4;return 0;}
function savedIdentity(title,text){const detail=node('details');detail.append(node('summary',title),node('small',text));return detail;}
function artifactSections(job,entries){const list=$('saved-artifacts');list.replaceChildren();for(const [index,[title,purpose]]of savedFileGroups.entries()){const present=entries.filter(e=>savedFileGroup(e.file)===index);if(!present.length)continue;const row=node('div');row.append(node('strong',title),node('p',purpose,'muted'));const identity=node('details');identity.append(node('summary','File sizes and exact identities'));for(const {file,stamp}of present){row.append(action('Download '+file,()=>download(job.name,file)));identity.append(node('small',file+' · '+(stamp?stamp.bytes+' bytes · SHA256 '+stamp.sha256:file==='COMPLETE.json'?'Completion inventory · binds every saved artifact':'Exact saved run file')));}row.append(identity);list.append(row);}}
function savedArtifacts(job,complete){const files=[
  'resolved-config.json','run.json','COMPLETE.json','decay-request.json',
  'transport/prepared.json','transport/geometry-report.json','transport/run.mac','transport/run.json','transport/truth.lh5',
  'transport/stream/manifest.json',...Object.keys(complete.artifacts).filter(f=>/^transport\/stream\/[^/]+\.jsonl$/.test(f)),
  'response/run.json','response/truth.jsonl','response/signals.csv','response/endpoints.jsonl','response/endpoints.csv','response/scalars.jsonl','response/scalars.csv','response/traces.jsonl',
  'electronics/profile.json','response/profile.json','response/readout-config.json','response/calibration.json','response/negative-injection.json','response/histograms.json','response/histograms.csv','response/summary.html'
];artifactSections(job,files.filter(f=>f==='COMPLETE.json'||complete.artifacts[f]).map(file=>({file,stamp:complete.artifacts[file]})));}
function flatBatchRecords(page){return page.records.flatMap(item=>[item.primary,...item.pulse_groups].filter(Boolean).map(record=>({...record,global_initial_id:item.global_initial_id,local_initial_id:item.local_initial_id,batch_index:item.batch_index,raw_truth:item.truth})));}
function pageIdentity(reply,job,batch,offset){if(reply.kind!=='local_batch_event_page_v1'||reply.name!==job.name||reply.configuration_sha256!==job.configuration_sha256||reply.batch_index!==batch||reply.offset!==offset||reply.limit!==100||!Array.isArray(reply.records)||reply.records.length>100||!Array.isArray(reply.traces)||typeof reply.batch_sha256!=='string'||! /^[0-9a-f]{64}$/.test(reply.batch_sha256))throw Error('Saved event page and selected run identities differ.');const sparse=reply.pagination_kind==='stored_nonzero_events_v1';if(sparse){const n=reply.batch_primary_count,z=reply.counts?.zero_deposit_primaries,a=reply.available_record_count;if(!Number.isSafeInteger(n)||n<1||!Number.isSafeInteger(z)||z<0||z>n||!Number.isSafeInteger(a)||a!==n-z||reply.nonzero_record_count!==a||reply.efficiency_denominator!==n||reply.counts?.initial_primaries!==n||offset>a||reply.records.length!==Math.min(100,a-offset)||reply.next_offset!==(offset+reply.records.length<a?offset+reply.records.length:null))throw Error('Saved nonzero page changed its initial census or denominator.');}let previous=-1;for(const [i,row]of reply.records.entries()){if(row.batch_index!==batch||!Number.isSafeInteger(row.local_initial_id)||row.local_initial_id<0||row.global_initial_id!==reply.batch_offset+row.local_initial_id||!Array.isArray(row.pulse_groups)||!row.primary||!row.truth||(sparse?(row.local_initial_id<=previous||row.local_initial_id>=reply.batch_primary_count||row.primary.zero_deposit!==false||!Array.isArray(row.truth.steps)||!row.truth.steps.some(step=>Number.isFinite(step.energy_keV)&&step.energy_keV!==0)):row.local_initial_id!==offset+i))throw Error('Incomplete saved primary identity.');previous=row.local_initial_id;}return reply;}
function selectablePrimaryIds(records){const zeros=new Set(records.filter(r=>r.zero_deposit===true||r.zero_ge===true).map(r=>r.initial_primary_id??r.event_id));return [...new Set(records.map(r=>r.initial_primary_id??r.event_id))].filter(id=>!zeros.has(id));}
async function openBatchResult(job){const prior=result?.job.name===job.name&&result?.job.configuration_sha256===job.configuration_sha256&&result?.page?{batch:result.page.batch_index,offset:result.page.offset,id:Number($('event').value),groupIndex:Number($('group').value)}:null;showRun(job);resultGeneration++;plotGeneration++;pageGeneration++;result={job,page:null,records:[],traces:[]};showResultSummary();loadResultOptions(result);clearSavedSelection('Saved page not loaded.');$('result').hidden=runDetailKind!=='standard';$('batch-navigation').hidden=false;$('result-heading').textContent=job.name+' · '+job.selection.detector+' · '+savedSourceLabel(job.selection)+' · '+job.selection.primary_count+' original primaries';$('batch-index').value=String(prior?.batch??0);$('page-offset').value=String(prior?.offset??0);$('saved-artifacts').replaceChildren();$('plots').replaceChildren();await loadBatchPage(prior);$('result').scrollIntoView({behavior:'smooth'});}
async function loadBatchPage(prior,savedPage=null){if(!result||result.job.execution_contract!=='serial_batches_v3')return;const context=result,job=context.job,batch=exactInteger($('batch-index').value,'Saved batch index',false),offset=exactInteger($('page-offset').value,'Nonzero event offset',false),generation=++pageGeneration,runGeneration=resultGeneration;plotGeneration++;resetSpectrum();context.page=null;context.records=[];context.traces=[];context.summaryHash=null;clearSavedSelection('Saved page not loaded.');$('saved-artifacts').replaceChildren();$('plots').replaceChildren();$('previous-page').disabled=true;$('next-page').disabled=true;$('page-status').textContent='Checking saved batch '+batch+'…';try{const reply=pageIdentity(savedPage||await api('/api/workflow/events?'+new URLSearchParams({name:job.name,batch:String(batch),offset:String(offset),limit:'100'})),job,batch,offset);if(generation!==pageGeneration||runGeneration!==resultGeneration||context!==result||selectedJob!==job.name)return;context.page=reply;context.records=flatBatchRecords(reply);context.traces=reply.traces;context.summaryHash=reply.response_summary_sha256;const ids=reply.records.map(r=>r.global_initial_id);options('event',primaryOptions(ids,result.records,result.traces));$('page-status').textContent='Batch '+batch+(reply.pagination_kind==='stored_nonzero_events_v1'?' · '+reply.available_record_count+' nonzero-deposit events · '+reply.counts.zero_deposit_primaries+' zero-deposit inputs omitted':ids.length?' · local IDs '+ids.map(id=>id-reply.batch_offset).join(', '):' · no records on this page')+' · '+reply.batch_primary_count+' initial primaries; efficiency denominator unchanged.';$('previous-page').disabled=offset===0&&batch===0;const completed=job.batch_progress?.completed_batch_count??job.batching.batch_count;$('next-page').disabled=reply.next_offset===null&&batch+1>=completed;const choice=prior&&ids.includes(prior.id)?prior:firstSavedWaveform(context.records,context.traces);if(choice)$('event').value=String(choice.id);if(ids.length)showEvent(choice?.groupIndex);else clearSavedSelection('No nonzero deposits on this page. Initial counts and denominator are retained.');eventNavigation();batchArtifacts(job,reply);showResultSummary();if(context.options)configureSpectrum(context);}catch(e){if(generation===pageGeneration&&context===result){$('page-status').textContent=e.message;throw e;}}}
function batchArtifacts(job,page){const entries=['resolved-config.json','run.json',...(['completed','completed_with_native_failures'].includes(job.status)?['COMPLETE.json']:[])].map(file=>({file,stamp:null}));if(job.status?.startsWith('completed')&&result?.job.name===job.name&&result.options?.spectrum_file)entries.push({file:result.options.spectrum_file,stamp:null});for(const stamp of page.artifacts||[])entries.push({file:stamp.file,stamp});artifactSections(job,entries);$('saved-artifacts').append(savedIdentity('Sealed batch identity','SHA256 · '+page.batch_sha256+' · complete raw radiation and original saved traces remain in this batch.'));
}
async function loadBatchPlots(context,id,group,generation){try{const batch=context.page.batch_index,reply=await api('/api/workflow/batch-waveforms?'+new URLSearchParams({name:context.job.name,batch:String(batch),primary:String(id),group:group===null?'none':String(group)}));if(generation!==plotGeneration||context!==result||selectedJob!==context.job.name)return;const original=reply.record,record=primaryRecords(context.records,id).find(r=>savedGroup(r)?.id===group);if(reply.kind!=='local_batch_waveform_v1'||reply.name!==context.job.name||reply.configuration_sha256!==context.job.configuration_sha256||reply.batch_index!==batch||reply.batch_sha256!==context.page.batch_sha256||reply.response_summary_sha256!==context.summaryHash||recordPrimary(original)!==id||original.group_id!==group||original.origin_time_ns!==record?.origin_time_ns||!record?.readout)throw Error('Saved batch waveform and current selection identities differ.');const trace=original.trace,rd=record.readout,charge=reply.charge_input,peak={t:rd.peak_time_ns,v:rd.peak_V};if(!charge||!Array.isArray(charge.time_since_origin_ns)||!Array.isArray(charge.induced_equivalent_energy_keV))throw Error('Exact saved charge samples are unavailable.');const t=charge.time_since_origin_ns,q=charge.induced_equivalent_energy_keV,end=Math.min(rd.readout_end_ns,SavedFocusPlots.focusEnd(t,q));const originalDt=trace.current_bin_end_ns.map((stop,i)=>stop-trace.current_bin_start_ns[i]).find(width=>width>0);const panels=[{title:'Signed native charge · induced equivalent keV',time_ns:t,values:q,full_end_ns:t.at(-1),focus_end_ns:Math.min(t.at(-1),end),note:'Every saved signed native charge sample is retained. The camera focus does not prove complete collection; endpoint and cap flags remain.'},{title:'Original-bin current · nA',time_ns:trace.time_ns,values:trace.raw_native_current_nA||trace.current_nA,bin_start_ns:trace.current_bin_start_ns,bin_end_ns:trace.current_bin_end_ns,full_end_ns:rd.readout_end_ns,focus_end_ns:end,current_from_charge:{time_ns:t,values:q,ionisation_energy_eV:reply.ionisation_energy_eV,time_step_ns:originalDt,readout_end_ns:rd.readout_end_ns},note:'Signed current on every original numerical interval from the complete saved native charge. No smoothing or polarity change; ADC and energy remain unchanged.'},{title:'Analog preamp · V',time_ns:trace.time_ns,values:trace.preamp_V,full_end_ns:rd.readout_end_ns,focus_end_ns:end,note:'Original retained samples; omitted analog samples remain unavailable.'},{title:'Analog shaper · V',time_ns:trace.time_ns,values:trace.shaped_V,full_end_ns:rd.readout_end_ns,focus_end_ns:SavedFocusPlots.shaperEnd(trace.time_ns,trace.shaped_V,peak,rd.readout_end_ns),peak,note:'Gold marker is the exact saved sampled peak. ADC, reconstructed energy and flags remain unchanged.'}];SavedFocusPlots.draw($('plots'),panels,'Time since pulse-group origin · ns');showWaveformStage();$('plots').append(savedIdentity('Saved waveform identity','Sealed batch SHA256 · '+reply.batch_sha256));}catch(e){if(generation===plotGeneration&&context===result)$('plots').replaceChildren(node('p',e.message,'error'));}}
$('load-page').onclick=()=>loadBatchPage().catch(e=>notice(e.message,true));
$('previous-page').onclick=()=>moveSavedPage(-1).catch(e=>notice(e.message,true));
$('next-page').onclick=()=>moveSavedPage(1).catch(e=>notice(e.message,true));
function recordPrimary(r){return r.global_initial_id??r.initial_primary_id??r.event_id;}
function primaryRecords(records,id){return records.filter(r=>recordPrimary(r)===id);}
function primaryOptions(ids,records,traces){return ids.map(id=>({id:String(id),label:String(id)+' · '+primaryHint(primaryRecords(records,id),traces)}));}
function primaryHint(rs,traces){
  // A group row is evidence of a recorded group, never of validated collection
  // or a saved waveform. Unknown/null results must remain distinct from zeros.
  const groups=rs.filter(r=>savedGroup(r)?.id!=null),summary=rs.find(r=>['decay','primary'].includes(r.record_kind));
  const count=new Set(groups.map(r=>savedGroup(r).id)).size;
  if(rs.some(r=>r.zero_deposit===true)&&!count)return 'zero deposition';
  const zero=rs.some(r=>r.zero_ge===true),reported=summary?.pulse_count;
  const parts=[zero?'known zero input':count?count+' group'+(count===1?'':'s'):Number.isInteger(reported)&&reported>=0?reported+' reported group'+(reported===1?'':'s'):'pulse status unknown'];
  const statuses=new Set((count?groups:rs.filter(r=>!['decay','primary'].includes(r.record_kind))).map(r=>{
    if(r.native_error||/native.*fail/.test(r.status||''))return 'native failure';
    const rd=r.readout;
    if(!rd)return 'readout unavailable';
    if(rd.saturated===true||rd.rejection_reason==='saturated')return 'readout saturated';
    if(rd.accepted===false||typeof rd.rejection_reason==='string'&&rd.rejection_reason.length)return 'readout rejected';
    if(rd.accepted===true)return 'readout accepted';
    return 'readout status unknown';
  }));
  if(statuses.size===1)parts.push([...statuses][0]);
  else if(statuses.size>1)parts.push(statuses.has('native failure')?'mixed; native failure':statuses.has('readout saturated')?'mixed readout; saturation':statuses.has('readout unavailable')||statuses.has('readout status unknown')?'readout partly unavailable':'mixed readout');
  if(count&&statuses.size===1&&firstSavedWaveform(rs,traces))parts.push('waveform saved');
  return parts.join(' · ');
}
function firstSavedWaveform(records,traces){const r=records.find(r=>(r.truth_ge_edep_keV??r.deposited_energy_keV)>0&&r.readout&&(r.readout.trace||traces.some(t=>recordPrimary(t)===recordPrimary(r)&&t.group_id===r.group_id)));if(!r)return null;const id=recordPrimary(r);return {id,groupIndex:primaryRecords(records,id).indexOf(r)};}
function metricValue(value){return value==null?'Unavailable':String(value);}
function analysisSelection(r){
  const context=result,job=context?.job;
  if(!r){$('analysis-selection').textContent=job?'Saved run '+job.name+' · no primary selected.':'No saved primary selected.';$('analysis-filter').textContent='Load a saved result page and choose an initial primary to see the matching file filters.';$('analysis-state').textContent='No pulse or readout is inferred without a selected saved record.';return;}
  const global=recordPrimary(r),local=r.local_initial_id??r.event_id??r.initial_primary_id,batch=r.batch_index??context.page?.batch_index,hasGlobal=!!context.page||r.global_initial_id!==undefined,group=savedGroup(r),summary=['decay','primary'].includes(r.record_kind);
  const groupLabel=summary?'primary summary':group?.id===null?'known zero input':group?'pulse group '+group.id:'saved record';
  $('analysis-selection').textContent='Saved run '+job.name+(Number.isInteger(batch)?' · batch '+batch:'')+' · '+(hasGlobal?'global initial ID ':'initial primary ID ')+global+' · local initial ID '+metricValue(local)+' · '+groupLabel+(r.record_kind==='pulse'&&r.origin_time_ns!=null?' · origin '+r.origin_time_ns+' ns':'');
  const idFilter=hasGlobal?'global_initial_id = '+global:Number.isInteger(r.event_id)?'event_id = '+r.event_id+(r.initial_primary_id!==undefined?' (initial_primary_id = '+r.initial_primary_id+' in gamma cases)':''):'initial_primary_id = '+r.initial_primary_id;
  const groupFilter=summary||group?.id===null?'Primary summary or known zero input: group_id is null in scalars; pulse-group files may have no summary row.':group?'In signals/scalars/traces/endpoints rows that carry group_id, filter group_id = '+group.id+'.':'Use the recorded group identity.';
  const rawFilter=Number.isInteger(local)?'Raw LH5: filter evtid = '+local+(Number.isInteger(batch)?' in batch '+batch+'’s transport/truth.lh5':' in transport/truth.lh5')+'. '+(hasGlobal?'Do not use global initial ID '+global+' as raw evtid. ':''):'Raw LH5 local evtid is unavailable for this record. ';
  $('analysis-filter').textContent=rawFilter+'Derived JSONL/CSV: filter '+idFilter+'. '+(context.page?'In scalars.csv and endpoints.csv, decode record_json to read global_initial_id, or use their JSONL versions; signals.csv has this identity column directly. ':'')+groupFilter+' Ledger and response/truth rows represent whole primaries and have no top-level group_id. The raw radiation tables have no charge pulse-group filter. Keep all deposits belonging to the selected primary.';
  $('analysis-state').textContent=r.zero_deposit?'Zero deposition: this primary has no pulse group. No deposition waveform or reconstructed energy is inferred.':r.zero_ge?'Known zero input: only an explicitly saved zero-input response can be shown; no deposition pulse is inferred.':r.native_error||/native.*fail/.test(r.status||'')?'Native transport failed. Truth and identity remain saved; null charge, endpoint or readout values are unknown. Keep any recorded signal sign and the exact failure.':summary?'This is the initial-primary summary. Choose a pulse group to inspect its charge and readout; a summary does not create a pulse.':!r.readout?'Readout is unavailable for this record. Keep null results as unknown and retain signed charge and endpoint flags.':'Use the saved signed signals and readout values. Reconstructed energy uses the independent calibration recorded for this run; it is not the truth deposit energy.';
}
function clearSavedSelection(message='No saved primary selected.'){options('event',[]);options('group',[]);$('event-identity').textContent='';$('event-record').textContent=message;$('result-data').replaceChildren();analysisSelection();resetFeatures();resetAcquisition();}
function showEvent(groupIndex=0){if(!result)return;eventNavigation();$('event-find').value=$('event').value;const id=Number($('event').value),rs=primaryRecords(result.records,id);$('event-record').textContent=JSON.stringify(rs,null,2);options('group',rs.map((r,index)=>({id:String(index),label:r.record_kind==='pulse'?'Pulse group '+r.group_id+' · origin '+r.origin_time_ns+' ns':r.record_kind==='decay'||r.record_kind==='primary'?'Primary summary':r.zero_ge?'Known zero input':'Gamma response · group 0'})));if(Number.isInteger(groupIndex)&&groupIndex>=0&&groupIndex<rs.length)$('group').value=String(groupIndex);showGroup();}
function savedGroup(r){if(r.record_kind==='pulse'&&Number.isInteger(r.group_id))return {id:r.group_id};if(!r.record_kind&&Number.isInteger(r.initial_primary_id)&&typeof r.zero_ge==='boolean')return {id:r.zero_ge?null:0};return null;}
function featureSelection(){
  if(!result)return null;
  const id=Number($('event').value),row=primaryRecords(result.records,id)[Number($('group').value)];
  return row?{context:result,id,group:savedGroup(row)?.id??null,row}:null;
}
function resetFeatures(){featureGeneration++;$('feature-status').textContent='Open this panel to inspect the selected primary’s saved features. No simulation or export starts.';$('feature-content').replaceChildren();}
function featureIdentity(reply,selection){
  const {context,id,group,row}=selection,hash=value=>typeof value==='string'&&/^[0-9a-f]{64}$/.test(value);
  if(reply.kind!=='local_saved_psd_features_v1'||reply.name!==context.job.name||reply.configuration_sha256!==context.job.configuration_sha256||reply.primary_id!==id||reply.group_id!==group||typeof reply.available!=='boolean')throw Error('Saved feature and current selection identities differ.');
  if(!reply.available){if(reply.profile_sha256!==null||reply.bundle_sha256!==null)throw Error('Unavailable feature bundle has an unexpected identity.');return reply;}
  const record=reply.record;
  if(!hash(reply.profile_sha256)||!hash(reply.bundle_sha256)||reply.provenance?.profile_sha256!==reply.profile_sha256||reply.profile?.kind!=='saved_waveform_psd_profile_v1'||reply.profile?.schema_version!==1||record?.global_initial_id!==id||group!==null&&record.group_id!==group||group===null&&!Array.isArray(record.pulse_groups)||typeof record.selection?.valid!=='boolean'||!Array.isArray(record.selection?.reasons))throw Error('Saved feature bundle or original primary/group identity differs.');
  for(const key of ['batch_index','local_initial_id','event_id'])if(row[key]!==undefined&&record[key]!==row[key])throw Error('Saved feature batch or local identity differs.');
  if(group!==null&&row.origin_time_ns!==undefined&&record.origin_time_ns!==row.origin_time_ns)throw Error('Saved feature pulse-group origin differs.');
  if(group!==null&&(!record.features||!record.selection.valid&&Object.values(record.features).some(value=>value!==null)))throw Error('Invalid saved selection contains canonical feature values.');
  const identity=reply.profile_sha256+':'+reply.bundle_sha256;
  if(context.featureBundleIdentity&&context.featureBundleIdentity!==identity)throw Error('Saved feature bundle changed. Reopen the saved result to inspect its verified version.');
  context.featureBundleIdentity=identity;return reply;
}
function featureMetrics(items){const metrics=node('div',undefined,'metrics');for(const [label,value]of items){const span=node('span',label);span.append(node('strong',metricValue(value)));metrics.append(span);}return metrics;}
function featureDetails(label,value){const details=node('details');details.append(node('summary',label),node('pre',JSON.stringify(value,null,2)));return details;}
function renderFeatures(reply,selection){
  const record=reply.record,profile=reply.profile,content=$('feature-content'),valid=record.selection.valid;
  $('feature-status').textContent='Saved primary '+selection.id+(selection.group===null?' · primary summary':' · group '+selection.group)+' · '+(valid?'feature selection valid':'feature selection invalid')+'. Every original primary and selection reason remains saved.';
  content.append(node('p','Selection reasons: '+(record.selection.reasons.length?record.selection.reasons.join(' · '):'none')+'. Readout acceptance does not establish complete collection.','notice'));
  content.append(featureMetrics([['Truth Edep · keV',record.truth_Edep_keV],['Saved calibrated Erec · keV',record.Erec_keV]]));
  if(selection.group===null){
    content.append(node('p',record.pulse_groups.length?'Choose a pulse group above to inspect its A/E, signed current peak, rise crossings and linked deposits. Primary Erec is populated only for one group; energies from multiple groups are not summed.':'This primary has no saved pulse group. Charge features remain unavailable; zero deposits do not create a waveform.','muted'));
  }else{
    const features=record.features,observed=record.observed,topology=record.topology;
    content.append(node('h3','Valid waveform features'),featureMetrics([['A · nA',features.A_nA],['A/E · nA/keV',features.A_over_E_nA_per_keV],['Charge rise 10–90% · ns',features.charge_rise_10_90_ns]]));
    content.append(node('h3',valid?'Observed signed waveform measurements':'Provisional observed signed waveform measurements'),node('p',valid?'These measurements use the saved full-resolution charge waveform.':'These observed candidates describe the saved waveform despite an invalid selection. They do not establish completed collection, calibrated charge-collection efficiency or physical resolution.','muted'));
    content.append(featureMetrics([['Filtered current peak · declared polarity · nA',observed?.signed_filtered_current_peak_nA],['Filtered current at peak · original sign · nA',observed?.native_signed_current_at_peak_nA],['Peak since group origin · ns',observed?.peak_time_since_origin_ns],['Signed observed charge change · keV',observed?.signed_charge_change_keV],['Observed rise 10–90% · ns',observed?.charge_rise_10_90_ns]]));
    content.append(node('p','Observed crossings: t10 '+metricValue(observed?.t10_ns)+' ns · t90 '+metricValue(observed?.t90_ns)+' ns · '+metricValue(observed?.sample_count)+' full-resolution samples. Flags: '+(observed===null?'unavailable':observed?.flags?.join(' · ')||'none recorded')+'.','muted'));
    if(topology){content.append(node('h3','Spatial deposition-point proxy'),node('p',metricValue(topology.cluster_count)+' clusters at '+topology.nominal_threshold_mm+' mm · '+topology.proxy_label+'. Sensitivity: '+topology.sensitivity.map(item=>item.threshold_mm+' mm → '+item.cluster_count+' clusters').join(' · ')+'.','notice'),node('p',topology.limitation+' Positive-energy detector-local position_mm points use inclusive Euclidean single-link clustering. This is a spatial-point proxy, not physical single-site/multi-site truth.','muted'));}
    content.append(featureDetails('Linked original deposits · raw rows, energies and positions',record.deposits),featureDetails('Saved endpoint and readout flags',{raw_row_indices:record.raw_row_indices,transport_flags:record.saved_scalar?.transport_flags,endpoints:record.endpoints,readout:record.saved_scalar?.readout,observed}));
  }
  content.append(node('p','Profile '+profile.name+' · signed polarity '+(profile.polarity>0?'+':'')+profile.polarity+' · '+profile.current_filter.width_ns+' ns centered current box average with complete support · analysis '+profile.analysis_window_ns.join('…')+' ns since group origin. Rise uses the first linear upward 10% and 90% crossings of the signed observed charge span in this window. A/E uses the separate-injection calibrated Erec; truth Edep is separate. Display previews are not feature inputs.','muted'));
  content.append(node('p','Saved engineering features only. No acquisition waveform ADC, classifier, experimental agreement or numerical/charge-collection convergence is established.','muted'),featureDetails('Feature profile, exact input/source hashes and recorded settings',{configuration_sha256:reply.configuration_sha256,profile_sha256:reply.profile_sha256,bundle_sha256:reply.bundle_sha256,counts:reply.counts,profile,provenance:reply.provenance}));
}
async function loadFeatures(){
  if($('feature-panel').hidden||!$('feature-panel').open)return;
  const selection=featureSelection(),generation=++featureGeneration;
  $('feature-content').replaceChildren();
  if(!selection){$('feature-status').textContent='No saved primary selected.';return;}
  const {context,id,group}=selection;
  $('feature-status').textContent='Checking saved features for primary '+id+(group===null?' summary':' · group '+group)+'…';
  try{
    const reply=await api('/api/workflow/features?'+new URLSearchParams({name:context.job.name,primary:String(id),...(group===null?{}:{group:String(group)})}));
    if(generation!==featureGeneration||context!==result||selectedJob!==context.job.name||!$('feature-panel').open)return;
    featureIdentity(reply,selection);
    if(!reply.available){$('feature-status').textContent=reply.note;$('feature-panel').hidden=true;$('feature-panel').open=false;$('result-options-status').textContent=reply.note;return;}
    renderFeatures(reply,selection);
  }catch(e){if(generation===featureGeneration&&context===result&&$('feature-panel').open)$('feature-status').textContent=e.message;}
}
$('feature-panel').ontoggle=()=>{if($('feature-panel').open&&!$('feature-panel').hidden)loadFeatures();else resetFeatures();};
function resetAcquisition(){acquisitionGeneration++;$('acquisition-status').textContent='Open this panel to inspect the selected primary’s saved synthetic acquisition. No simulation or export starts.';$('acquisition-content').replaceChildren();}
function acquisitionIdentity(reply,selection){
  const {context,id,group,row}=selection,hash=value=>typeof value==='string'&&/^[0-9a-f]{64}$/.test(value);
  if(reply.kind!=='local_saved_waveform_acquisition_v1'||reply.name!==context.job.name||reply.configuration_sha256!==context.job.configuration_sha256||reply.primary_id!==id||reply.group_id!==group||typeof reply.available!=='boolean')throw Error('Saved acquisition and current selection identities differ.');
  const pins=['profile_sha256','bundle_sha256','source_features_manifest_sha256','source_profile_sha256'];
  if(!reply.available){if(pins.some(key=>reply[key]!==null))throw Error('Unavailable acquisition bundle has an unexpected identity.');return reply;}
  const record=reply.record,profile=reply.profile,provenance=reply.provenance;
  if(!pins.every(key=>hash(reply[key]))||!provenance||['profile_sha256','source_features_manifest_sha256','source_profile_sha256'].some(key=>provenance[key]!==reply[key])||provenance.run_ref!=='.local/runs/'+context.job.name||provenance.source_features_ref!=='.local/psd-features/'+context.job.configuration_sha256+'/bundle'||profile?.kind!=='synthetic_waveform_acquisition_profile_v1'||profile.schema_version!==1||!Array.isArray(reply.calibrations)||record?.global_initial_id!==id||group!==null&&record.group_id!==group||group===null&&!Array.isArray(record.pulse_groups))throw Error('Saved acquisition bundle or source identity differs.');
  if(!Number.isFinite(profile.sampling_rate_Hz)||profile.sampling_rate_Hz<=0||!Number.isInteger(profile.adc?.bits)||profile.adc.bits<1||profile.adc.bits>24||!Number.isFinite(profile.adc.minimum_V)||!Number.isFinite(profile.adc.maximum_V)||profile.adc.minimum_V>=0||profile.adc.maximum_V<=0||!Array.isArray(profile.record_window_ns)||profile.record_window_ns.length!==2||!profile.record_window_ns.every(Number.isFinite)||profile.record_window_ns[1]<=profile.record_window_ns[0]||!Number.isFinite(profile.trigger?.offset_ns)||profile.measurement_polarity!==-1)throw Error('Saved acquisition profile differs from the declared signed bipolar model.');
  for(const key of ['batch_index','local_initial_id','event_id','global_decay_id'])if(row[key]!==undefined&&record[key]!==row[key])throw Error('Saved acquisition batch or local identity differs.');
  if(group!==null&&row.origin_time_ns!==undefined&&record.origin_time_ns!==row.origin_time_ns)throw Error('Saved acquisition pulse-group origin differs.');
  const acquired=group===null?{selection:record.acquisition_selection,acquisition_energy_keV:record.acquisition_energy_keV}:record.acquisition;
  if(!acquired||typeof acquired.selection?.valid!=='boolean'||!Array.isArray(acquired.selection.reasons)||!acquired.selection.valid&&acquired.acquisition_energy_keV!==null||record.selection?.valid===false&&acquired.selection.valid)throw Error('Invalid saved acquisition selection or canonical energy.');
  if(group!==null){
    if(acquired.trace!==null){
      const trace=acquired.trace,keys=['signed_preamp_V','bandwidth_limited_preamp_V','noise_V','noisy_voltage_V','adc_code','adc_center_V'],time=trace?.time_since_origin_ns,maxCode=2**profile.adc?.bits-1;
      if(!Array.isArray(time)||!time.length||!keys.every(key=>Array.isArray(trace[key])&&trace[key].length===time.length))throw Error('Invalid saved acquisition sample arrays.');
      const step=1e9/profile.sampling_rate_Hz;
      for(let i=0;i<time.length;i++)if(!Number.isFinite(time[i])||(i&&Math.abs(time[i]-time[i-1]-step)>Math.max(1e-8,step*1e-8))||!keys.every(key=>Number.isFinite(trace[key][i]))||!Number.isInteger(trace.adc_code[i])||trace.adc_code[i]<0||trace.adc_code[i]>maxCode)throw Error('Invalid saved acquisition sample or ADC code.');
      if(time[0]!==profile.record_window_ns[0]+profile.trigger.offset_ns||time.at(-1)>profile.record_window_ns[1]+profile.trigger.offset_ns||time.at(-1)>acquired.metadata.native_window_end_ns||acquired.metadata.trigger_origin_time_ns!==record.origin_time_ns||acquired.metadata.measurement_polarity!==profile.measurement_polarity)throw Error('Saved acquisition timing or polarity differs.');
    }
    if(!acquired.flags||typeof acquired.flags!=='object'||Array.isArray(acquired.flags)||!Object.values(acquired.flags).every(value=>typeof value==='boolean'))throw Error('Saved acquisition flags are unavailable.');
  }
  const identity=pins.map(key=>reply[key]).join(':');
  if(context.acquisitionBundleIdentity&&context.acquisitionBundleIdentity!==identity)throw Error('Saved acquisition bundle changed. Reopen the saved result to inspect its verified version.');
  if(context.featureBundleIdentity&&context.featureBundleIdentity.split(':')[0]!==reply.source_profile_sha256)throw Error('Saved acquisition source profile differs from the viewed features.');
  context.acquisitionBundleIdentity=identity;return reply;
}
function acquisitionPlot(trace){
  const ns='http://www.w3.org/2000/svg',svg=(tag,attrs={},text)=>{const n=document.createElementNS(ns,tag);for(const [key,value]of Object.entries(attrs))n.setAttribute(key,String(value));if(text!==undefined)n.textContent=text;return n;},time=trace.time_since_origin_ns;
  const series=[['Bandwidth-limited preamp',trace.bandwidth_limited_preamp_V,'#365ca1'],['Noisy ADC input',trace.noisy_voltage_V,'#a26017'],['ADC decoded center · original sign',trace.adc_center_V,'#007b80']];
  let low=0,high=0;for(const[,values]of series)for(const value of values){low=Math.min(low,value);high=Math.max(high,value);}const pad=(high-low)*.08||.001;low-=pad;high+=pad;
  const start=time[0],end=time.at(-1),span=end-start||1,x=v=>82+(v-start)/span*460,y=v=>214-(v-low)/(high-low)*188,figure=node('figure',undefined,'plot'),plot=svg('svg',{viewBox:'0 0 560 260',role:'img','aria-label':'Saved synthetic acquisition signed voltage versus time since pulse-group origin in ns'});
  figure.append(node('figcaption','Saved synthetic waveform ADC · signed voltage in V'),plot);
  for(let k=0;k<=4;k++){const voltage=low+(high-low)*k/4,t=start+span*k/4;plot.append(svg('line',{x1:82,x2:542,y1:y(voltage),y2:y(voltage),stroke:'#d7e3e5'}),svg('text',{x:76,y:y(voltage)+4,'text-anchor':'end'},voltage.toPrecision(3)),svg('text',{x:x(t),y:235,'text-anchor':'middle'},t.toPrecision(3)));}
  plot.append(svg('path',{d:'M82,26V214H542',stroke:'#405963',fill:'none'}),svg('line',{x1:82,x2:542,y1:y(0),y2:y(0),stroke:'#657c83'}),svg('text',{x:312,y:257,'text-anchor':'middle'},'Time since pulse-group origin · ns'),svg('text',{transform:'translate(14 120) rotate(-90)','text-anchor':'middle'},'Signed voltage · V'));
  const legend=node('p',undefined,'muted');
  for(const[label,values,color]of series){const path=svg('path',{d:values.map((v,i)=>(i?'L':'M')+x(time[i])+','+y(v)).join(' '),stroke:color,'stroke-width':1.4,fill:'none','data-series':label});path.append(svg('title',{},label+' · '+values.length+' saved samples'));plot.append(path);const item=node('span','● '+label+'  ');item.style.color=color;legend.append(item);}
  figure.append(legend,node('p',time.length+' saved samples · '+start+'…'+end+' ns. All samples are drawn; lines guide the eye. ADC center voltage retains the original preamp sign.','muted'));return figure;
}
function renderAcquisition(reply,selection){
  const record=reply.record,profile=reply.profile,content=$('acquisition-content'),acquired=selection.group===null?{selection:record.acquisition_selection,acquisition_energy_keV:record.acquisition_energy_keV}:record.acquisition,valid=acquired.selection.valid;
  $('acquisition-status').textContent='Saved primary '+selection.id+(selection.group===null?' · primary summary':' · group '+selection.group)+' · '+(valid?'acquisition selection valid':'acquisition selection invalid')+'. Original event and readout records remain saved.';
  content.append(node('p','Acquisition selection reasons: '+(acquired.selection.reasons.join(' · ')||'none')+'. Original feature selection reasons: '+(record.selection?.reasons?.join(' · ')||'none')+'.','notice'),featureMetrics([['Truth Edep · keV',record.truth_Edep_keV],['Original peak-ADC Erec · keV',record.Erec_keV],['Waveform acquisition energy · keV',acquired.acquisition_energy_keV]]));
  if(selection.group===null){content.append(node('p',record.pulse_groups.length?'Choose a pulse group above to inspect its signed sampled ADC waveform. Multiple group energies are not summed.':'This primary has no pulse group. No acquisition waveform is fabricated; the original zero or failure record remains available.','muted'));}
  else{
    if(acquired.trace===null)content.append(node('p','Acquisition waveform is unavailable. Unknown samples and energies remain null.','muted'));
    else content.append(acquisitionPlot(acquired.trace));
    content.append(node('h3',valid?'Observed acquisition measurements':'Provisional observed acquisition measurements'),node('p',valid?'Observed measurements use the declared waveform acquisition and separate injection calibration.':'These candidates describe the saved sampled signal despite an invalid selection. They do not establish completed collection, calibrated charge-collection efficiency or physical energy resolution.','muted'),featureMetrics([['Observed candidate energy · keV',acquired.observed?.acquisition_energy_keV],['Baseline-subtracted peak · fixed polarity · V',acquired.observed?.peak_adc_excursion_V],['Observed peak since group origin · ns',acquired.observed?.peak_time_since_origin_ns]]),node('p','Acquisition flags: '+(Object.keys(acquired.flags).filter(key=>acquired.flags[key]).join(' · ')||'none')+'. '+(acquired.metadata?'Derived noise seed '+acquired.metadata.derived_noise_seed_uint64+' · calibration batch '+acquired.metadata.calibration_id+'.':'Acquisition seed and calibration are unavailable for this signal.'),'muted'));
    if(acquired.uncertainty)content.append(node('p','Numerical acquisition bounds, conditional on no clipping: quantization excursion ≤ '+metricValue(acquired.uncertainty.quantization_excursion_bound_keV)+' keV; single-sample noise σ '+metricValue(acquired.uncertainty.single_sample_noise_sigma_energy_keV)+' keV; simultaneous '+100*acquired.uncertainty.simultaneous_noise_confidence+'% noise bound '+metricValue(acquired.uncertainty.simultaneous_noise_bound_keV)+' keV. Peak selection may introduce noise winner bias. These are numerical bounds, not physical energy resolution.','muted'));
    content.append(featureDetails('Observed candidates, acquisition flags and source endpoint/readout flags',{observed:acquired.observed,flags:acquired.flags,metadata:acquired.metadata,uncertainty:acquired.uncertainty,endpoints:record.endpoints,original_saved_scalar:record.saved_scalar}),featureDetails('All saved acquisition samples · raw ADC codes and signed voltages',acquired.trace));
  }
  const adc=profile.adc,noise=profile.noise;
  content.append(node('p','Profile '+profile.name+' · '+profile.sampling_rate_Hz/1e6+' MHz sampling ('+1e9/profile.sampling_rate_Hz+' ns) · bipolar ADC '+adc.minimum_V+'…'+adc.maximum_V+' V, '+adc.bits+' bits · '+profile.record_window_ns.join('…')+' ns since group origin, trigger offset '+profile.trigger.offset_ns+' ns. Measurement polarity '+profile.measurement_polarity+' is fixed for this profile; stored voltages retain their original sign. Positive saved charge gives a negative preamp voltage; the fixed polarity converts its baseline-subtracted excursion to the peak estimator.','muted'),node('p','External trigger at the saved pulse-group origin; isolated reset-zero prehistory before that origin is an assumption. Bandwidth is a causal single-pole low-pass approximation at '+profile.bandwidth.cutoff_Hz/1e6+' MHz. Post-filter independent Gaussian voltage noise RMS '+noise.rms_V+' V · root seed '+noise.root_seed_uint64+'. Independent '+profile.calibration.energy_keV+' keV charge injection sets the new gain; event truth Edep never sets gain.','muted'),node('p','Saved synthetic engineering acquisition only. Opening this panel verifies existing data without starting simulation or export. No measured hardware, classifier, experimental agreement or numerical/charge-collection convergence is established.','muted'),featureDetails('Acquisition profile, independent calibrations and exact source hashes',{configuration_sha256:reply.configuration_sha256,profile_sha256:reply.profile_sha256,bundle_sha256:reply.bundle_sha256,source_features_manifest_sha256:reply.source_features_manifest_sha256,source_profile_sha256:reply.source_profile_sha256,counts:reply.counts,profile,calibrations:reply.calibrations,provenance:reply.provenance}));
}
async function loadAcquisition(){
  if($('acquisition-panel').hidden||!$('acquisition-panel').open)return;
  const selection=featureSelection(),generation=++acquisitionGeneration;$('acquisition-content').replaceChildren();
  if(!selection){$('acquisition-status').textContent='No saved primary selected.';return;}
  const {context,id,group}=selection;
  $('acquisition-status').textContent='Checking saved acquisition for primary '+id+(group===null?' summary':' · group '+group)+'…';
  try{
    const reply=await api('/api/workflow/acquisition?'+new URLSearchParams({name:context.job.name,primary:String(id),...(group===null?{}:{group:String(group)})}));
    if(generation!==acquisitionGeneration||context!==result||selectedJob!==context.job.name||!$('acquisition-panel').open)return;
    acquisitionIdentity(reply,selection);if(!reply.available){$('acquisition-status').textContent=reply.note;$('acquisition-panel').hidden=true;$('acquisition-panel').open=false;$('result-options-status').textContent=reply.note;return;}renderAcquisition(reply,selection);
  }catch(e){if(generation===acquisitionGeneration&&context===result&&$('acquisition-panel').open)$('acquisition-status').textContent=e.message;}
}
$('acquisition-panel').ontoggle=()=>{if($('acquisition-panel').open&&!$('acquisition-panel').hidden)loadAcquisition();else resetAcquisition();};
function safeSvg(fragment){if(typeof fragment!=='string'||fragment.includes('<!')||fragment.includes('<?'))throw Error('Unsupported saved SVG.');const parsed=new DOMParser().parseFromString(fragment,'image/svg+xml');if(parsed.doctype||parsed.getElementsByTagName('parsererror').length||parsed.documentElement.localName!=='svg')throw Error('Malformed saved SVG.');const ns='http://www.w3.org/2000/svg',allowed={svg:['role','aria-label','viewbox','xmlns'],path:['d','fill','stroke'],polyline:['points','fill','stroke','stroke-width'],text:['x','y']};function copy(element){const tag=element.localName;if(element.prefix||!allowed[tag]||element.namespaceURI&&element.namespaceURI!==ns)throw Error('Unsupported saved SVG element.');const output=document.createElementNS(ns,tag);for(const a of element.attributes){if(a.prefix||!allowed[tag].includes(a.name.toLowerCase())||a.name==='xmlns'&&a.value!==ns)throw Error('Unsupported saved SVG attribute.');output.setAttribute(a.name,a.value);}for(const child of element.childNodes){if(child.nodeType===1)output.append(copy(child));else if(child.nodeType===3)output.append(document.createTextNode(child.nodeValue));else throw Error('Unsupported saved SVG node.');}return output;}return copy(parsed.documentElement);}
async function loadPlots(context,id,group,generation){
  if(context.page)return loadBatchPlots(context,id,group,generation);
  try{
    const reply=await api('/api/workflow-file/focus?'+new URLSearchParams({name:context.job.name,primary:String(id),group:group===null?'none':String(group)}));
    if(generation!==plotGeneration||context!==result||selectedJob!==context.job.name)return;
    if(reply.kind!=='saved_focus_projection_v1'||reply.name!==context.job.name||reply.configuration_sha256!==context.job.configuration_sha256||reply.primary_id!==id||reply.group_id!==group||reply.summary_sha256!==context.summaryHash||reply.panels?.length!==4)throw Error('Saved waveform and current selection identities differ.');
    const record=primaryRecords(context.records,id).find(r=>savedGroup(r)?.id===group);
    if(record?.record_kind==='pulse'&&(reply.global_decay_id!==record.global_decay_id||reply.origin_time_ns!==record.origin_time_ns))throw Error('Saved pulse-group origin differs.');
    const hashes=[reply.sidecar_manifest_sha256,reply.sidecar_data_sha256];
    if(!hashes.every(h=>h===null)&&!hashes.every(h=>typeof h==='string'&&/^[0-9a-f]{64}$/.test(h)))throw Error('Incomplete display derivative binding.');
    const peak=reply.panels[3].peak;if(!peak||!Object.is(peak.t,record.readout.peak_time_ns)||!Object.is(peak.v,record.readout.peak_V))throw Error('Original sampled peak changed.');
    SavedFocusPlots.draw($('plots'),reply.panels,reply.clock);showWaveformStage();
    const original=node('button','Download original saved plots');original.onclick=()=>download(context.job.name,'response/summary.html').catch(e=>notice(e.message,true));
    $('plots').append(original,node('p',reply.notes.join(' '),'muted'),savedIdentity('Saved waveform identity','Original artifact SHA256 · '+reply.summary_sha256+(hashes[0]?' · display derivative '+hashes[0]:'')));
  }catch(e){if(generation===plotGeneration&&context===result)$('plots').replaceChildren(node('p',e.message,'error'));}
}
function showGroup(){const generation=++plotGeneration,id=Number($('event').value),rs=result?primaryRecords(result.records,id):[],r=rs[Number($('group').value)],primary=rs.find(r=>['decay','primary'].includes(r.record_kind));if(!r){clearSavedSelection('No records for this primary.');$('plots').replaceChildren();return;}analysisSelection(r);$('event-identity').textContent='Initial primary '+id+(r.record_kind==='pulse'?' · pulse group '+r.group_id+' · origin '+r.origin_time_ns+' ns':primary?' · primary summary · '+primary.pulse_count+' pulse groups':r.zero_ge?' · known zero input':' · gamma response group 0');$('result-data').replaceChildren();const edep=r.truth_ge_edep_keV??r.deposited_energy_keV,charge=r.final_induced_keV??(r.zero_deposit?0:null),rec=r.readout?.reconstructed_energy_keV,metrics=node('div',undefined,'metrics');for(const [label,value]of [['Truth Edep · keV',edep],['Induced equivalent · keV',charge],['Readout equivalent energy · keV',rec]]){const span=node('span',label);span.append(node('strong',metricValue(value)));metrics.append(span);} $('result-data').append(metrics,node('p',r.status||r.rejection_reason||(r.zero_deposit?'True zero deposition · no pulse group':r.record_kind==='pulse'?'Recorded pulse group':'Recorded primary')));const group=savedGroup(r),hasTrace=group&&r.readout&&(r.readout.trace||result.traces.some(t=>(t.global_initial_id??t.event_id)===id&&t.group_id===group.id));$('plots').replaceChildren(node('p',hasTrace?'Loading original saved waveforms…':r.zero_deposit?'No pulse waveform for this zero-deposit primary.':'No saved waveform for this record. Pulse groups retain their scalar results.','muted'));if(hasTrace)loadPlots(result,id,group.id,generation);resetFeatures();if($('feature-panel').open&&!$('feature-panel').hidden)loadFeatures();resetAcquisition();if($('acquisition-panel').open&&!$('acquisition-panel').hidden)loadAcquisition();}
function eventNavigation(){
  const ids=[...$('event').children].map(option=>Number(option.value));
  const index=ids.indexOf(Number($('event').value)),page=result?.page;
  const completed=result?.job.batch_progress?.completed_batch_count??result?.job.batching?.batch_count??0;
  const priorPage=page&&(page.offset>0||page.batch_index>0);
  const laterPage=page&&(page.next_offset!==null||page.batch_index+1<completed);
  $('event-previous').disabled=index<=0&&!priorPage;
  $('event-next').disabled=(index<0||index===ids.length-1)&&!laterPage;
}
async function findSavedEvent(){
  const context=result,generation=++eventFindGeneration;
  if(!context)return;
  let id;
  try{id=exactInteger($('event-find').value.trim(),'Original event ID',false);}
  catch(e){$('event-find-status').textContent=e.message;return;}
  if(id>=context.job.selection.primary_count){
    $('event-find-status').textContent='Event IDs for this run range from 0 to '+(context.job.selection.primary_count-1)+'.';
    return;
  }
  $('event-find-button').disabled=true;
  $('event-find-status').textContent='Finding original event '+id+'…';
  try{
    if(!primaryRecords(context.records,id).length&&context.job.execution_contract==='serial_batches_v3'){
      const batch=Math.floor(id/context.job.batching.batch_cap);
      const completed=context.job.batch_progress?.completed_batch_count??context.job.batching.batch_count;
      if(batch>=completed)throw Error('This event belongs to a batch that is not complete. Open a completed event or resume the run.');
      let low=0,high=null;
      while(high===null||low<=high){
        const page=high===null?0:Math.floor((low+high)/2),offset=page*100;
        const response=await api('/api/workflow/events?'+new URLSearchParams({
          name:context.job.name,batch:String(batch),offset:String(offset),limit:'100'
        }));
        const reply=pageIdentity(response,context.job,batch,offset);
        if(generation!==eventFindGeneration||context!==result||selectedJob!==context.job.name)return;
        const ids=reply.records.map(row=>row.global_initial_id);
        if(ids.includes(id)){
          $('batch-index').value=String(batch);
          $('page-offset').value=String(offset);
          await loadBatchPage({id,groupIndex:0},reply);
          break;
        }
        if(!ids.length||id>=ids[0]&&id<=ids.at(-1))break;
        if(high===null)high=Math.ceil(reply.available_record_count/100)-1;
        if(id>ids.at(-1))low=page+1;
        else high=page-1;
      }
    }
    if(generation!==eventFindGeneration||context!==result||selectedJob!==context.job.name)return;
    const records=primaryRecords(context.records,id);
    if(!records.length||records.some(record=>record.zero_deposit===true||record.zero_ge===true)){
      throw Error('Event '+id+' has no saved nonzero-deposit record. Initial and zero-deposition counts remain in Overview.');
    }
    $('event').value=String(id);
    const choice=firstSavedWaveform(records,context.traces);
    showEvent(choice?.groupIndex??0);
    showResultTab('events');
    $('event-find-status').textContent='Showing original event '+id+'.';
  }catch(e){
    if(generation===eventFindGeneration&&context===result)$('event-find-status').textContent=e.message;
  }finally{
    if(generation===eventFindGeneration)$('event-find-button').disabled=false;
  }
}
async function moveSavedPage(direction){
  ++eventFindGeneration;
  $('event-find-button').disabled=false;
  const context=result;
  if(!context?.page)return;
  const page=context.page,crossedBack=direction<0&&page.offset===0;
  let batch=page.batch_index,offset=direction<0?Math.max(0,page.offset-100):page.next_offset;
  if(crossedBack){batch--;offset=0;}
  else if(direction>0&&offset===null){batch++;offset=0;}
  const completed=context.job.batch_progress?.completed_batch_count??context.job.batching.batch_count;
  while(batch>=0&&batch<completed){
    $('batch-index').value=String(batch);
    $('page-offset').value=String(offset);
    await loadBatchPage();
    if(context!==result)return;
    if(crossedBack&&offset===0&&context.page.available_record_count>100){
      offset=Math.floor((context.page.available_record_count-1)/100)*100;
      $('page-offset').value=String(offset);
      await loadBatchPage();
      if(context!==result)return;
    }
    if(context.page.records.length)return;
    batch+=direction;offset=0;
  }
}
async function moveSavedEvent(direction){
  ++eventFindGeneration;
  $('event-find-button').disabled=false;
  const context=result;
  if(!context)return;
  const ids=[...$('event').children].map(option=>Number(option.value));
  const index=ids.indexOf(Number($('event').value)),next=ids[index+direction];
  if(next!==undefined){
    $('event').value=String(next);
    showEvent(firstSavedWaveform(primaryRecords(context.records,next),context.traces)?.groupIndex??0);
    return;
  }
  await moveSavedPage(direction);
  if(context!==result)return;
  const available=[...$('event').children];
  if(available.length){
    $('event').value=available[direction<0?available.length-1:0].value;
    const id=Number($('event').value);
    showEvent(firstSavedWaveform(primaryRecords(context.records,id),context.traces)?.groupIndex??0);
  }
}
$('event').onchange=()=>{++eventFindGeneration;$('event-find-button').disabled=false;showEvent();};
$('event-find-button').onclick=()=>findSavedEvent();
$('event-find').onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();void findSavedEvent();}};
$('event-previous').onclick=()=>moveSavedEvent(-1).catch(e=>notice(e.message,true));
$('event-next').onclick=()=>moveSavedEvent(1).catch(e=>notice(e.message,true));
$('group').onchange=showGroup;
$('setup').onclick=async()=>{try{const r=await api('/api/workflow/setup');$('setup-notice').textContent=r.checks.map(c=>(c.available?'✓ ':'Missing: ')+c.label).join(' · ')+' '+r.note;}catch(e){$('setup-notice').textContent=e.message;}};
$('check').onclick=async()=>{if(busy||active||!executableSelection())return;const version=selectionVersion,button=$('check'),focused=document.activeElement===button;busy=true;checked=null;showPose();controls();try{const submitted=config(),serialized=JSON.stringify(submitted),batched=batchSelection(),gegi=gegiSelection();const reply=await api(gegi?'/api/workflow/check-gegi':batched?'/api/workflow/check-batches':'/api/workflow/check',batched?{request:batchRequest(submitted)}:{config:submitted});if(version!==selectionVersion||JSON.stringify(config())!==serialized){notice('Selection changed while Check was pending. Check the current setup.');return;}if(gegi&&(reply.kind!=='local_gegi_workflow_v1'||reply.status!=='checked_configuration'||typeof reply.check_id!=='string'))throw Error('Check did not authorize this GeGI configuration.');const pendingAngle=batched&&submitted.angle_deg!==undefined&&submitted.angle_deg!==0&&reply.execution_enabled===false&&reply.resolved?.source_pose;if(batched&&(reply.kind!=='local_scenario_batch_execution_v3'||reply.schema_version!==3||(!pendingAngle&&(reply.execution_enabled!==true||typeof reply.check_id!=='string'))))throw Error('Check did not authorize batch execution.');checked=reply;$('checked-plan').textContent=JSON.stringify(checked.resolved,null,2);showPose(checked.resolved);notice(gegi?'GeGI configuration checked. Run records the selected source, all readout channels and signal-based imaging.':pendingAngle?'Angle and geometry inputs checked. Nonzero-angle execution is unavailable: the fixed pilot failed source-position identity; end-to-end acceptance is pending.':batched?'Exact count checked: '+submitted.primary_count+' initial primaries in '+checked.resolved.batching.batch_count+' serial batches. Run uses this checked plan.':'Gamma configuration checked. Run uses its checked energy, source anchor and 20-primary settings.',false,true);}catch(e){if(version===selectionVersion){checked=null;notice(e.message,true);}}finally{busy=false;controls();if(focused&&button.isConnected&&!button.disabled&&document.activeElement===document.body)button.focus({preventScroll:true});}};
$('start').onclick=async()=>{
  if(busy||active||!executableSelection())return;
  const version=selectionVersion;
  if(!checked)await $('check').onclick();
  if(version!==selectionVersion||busy||active||!checked||checked.execution_enabled===false||!executableSelection())return;
  busy=true;controls();
  try{
    const job=await api('/api/workflow/start',{check_id:checked.check_id});
    showRun(job);
    checked=null;
    openRunDetail();
    showRunStatusNotice(job);
    await poll();
    if($('name').value===job.name){$('name').value=uniqueRunName();invalidate();}
  }catch(e){
    checked=null;notice(e.message,true);
  }finally{
    busy=false;controls();
  }
};
$('save').onclick=()=>{if(busy||active||!executableSelection())return;try{const blob=new Blob([JSON.stringify(batchSelection()?batchRequest(config()):config(),null,2)+'\n'],{type:'application/json'}),url=URL.createObjectURL(blob),a=node('a');a.href=url;a.download='gesignal-configuration.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(e){notice(e.message,true);}};
function importedConfig(c,batched=false){if(c?.source==='gegi_mono_gamma_v1'||c?.cryostat==='gegi_cryostat_v1'||c?.detector==='GeGI_3D')return importedGeGIConfig(c,batched);const fields=['name','cryostat','detector','source','pose','primary_count','seed','threads','electronics'];for(const key of ['angle_deg','gamma_energy_keV'])if(c&&Object.hasOwn(c,key))fields.push(key);if(!c||Array.isArray(c)||Object.keys(c).sort().join()!=fields.sort().join()||!c.electronics||Object.keys(c.electronics).sort().join()!=[...catalog.electronics_keys].sort().join())throw Error('Configuration fields do not match this application.');const source=catalog.sources.find(s=>s.id===c.source),detector=catalog.detectors.find(d=>d.id===c.detector),gamma=gammaCapability(source);if(!source||source.available===false||!catalog.cryostats.some(x=>x.id===c.cryostat&&x.available)||!detector?.available||!detectorFits(detector,c.cryostat)||detector.sources&&!detector.sources.includes(c.source)||!(gamma?gamma.source_poses.includes(c.pose):source.pose===c.pose)||(batched?!Number.isSafeInteger(c.primary_count)||c.primary_count<1||source.id==='mono_gamma_662_axis_v1':!source.counts.includes(c.primary_count))||![1,2].includes(c.threads)||!Number.isInteger(c.seed)||c.seed<1||c.seed>2147483646||typeof c.name!=='string'||(!batched&&source.fixed_seed!=null&&c.seed!==source.fixed_seed))throw Error('The imported setup is unavailable. No selection was replaced.');const hasGammaEnergy=Object.hasOwn(c,'gamma_energy_keV'),energy=hasGammaEnergy?c.gamma_energy_keV:gamma?.energy_keV.default;if(hasGammaEnergy&&(!gamma||batched)||gamma&&(typeof energy!=='number'||!Number.isFinite(energy)||energy<=0))throw Error('The imported gamma energy is unavailable. Use a finite positive number in keV for a supported gamma source. No selection was replaced.');const angle=Object.hasOwn(c,'angle_deg')?c.angle_deg:0,capability=angleCapability(source);if(typeof angle!=='number'||!Number.isFinite(angle)||(capability?angle<capability.min_deg||angle>capability.max_deg:angle!==0))throw Error('The imported source angle is unavailable. No selection was replaced.');for(const key of catalog.electronics_keys){const value=c.electronics[key];if(key==='peak_policy'?typeof value!=='string':key.startsWith('peak_gate_')?value!==null&&(typeof value!=='number'||!Number.isFinite(value)):typeof value!=='number'||!Number.isFinite(value))throw Error('Imported electronics values have invalid types.');}if((c.electronics.peak_gate_start_ns===null)!==(c.electronics.peak_gate_end_ns===null))throw Error('A peak gate requires both boundaries.');const normalized={...c};if(angle===0)delete normalized.angle_deg;if(gamma)normalized.gamma_energy_keV=energy;return normalized;}
function importedRequest(value){if(value?.kind==='local_scenario_batch_request_v2'){if(Object.keys(value).sort().join()!=='kind,schema_version,selection'||value.schema_version!==2)throw Error('Batch request fields do not match this application.');return importedConfig(value.selection,true);}return importedConfig(value);}
function applyConfiguration(selection){
  $('cryostat').value=selection.cryostat;
  options('detector',detectorItems(),true);
  $('detector').value=selection.detector;
  $('source').value=selection.source;
  detectorChanged();
  for(const id of ['name','threads','seed'])$(id).value=String(selection[id]);
  $('count').value=String(selection.primary_count);
  $('pose').value=selection.pose;
  $('angle-deg').value=String(selection.angle_deg??0);
  $('gamma-energy-keV').value=String(selection.gamma_energy_keV??662);
  if(selection.source_position_mm){
    for(const [index,axis]of ['x','y','z'].entries())$('gegi-source-'+axis).value=String(selection.source_position_mm[index]);
  }
  for(const key of catalog.electronics_keys)$('setting-'+key).value=selection.electronics[key]??'';
  $('use-peak-gate').checked=selection.electronics.peak_gate_start_ns!==null;
  gateFields();invalidate();
}
function copyAsNewRun(job){
  const selection=importedConfig(job.selection,job.execution_contract==='serial_batches_v3');
  applyConfiguration({...selection,name:uniqueRunName(job.name+'-copy')});
  showTask('standard');showPage('new');
  notice('Copied '+job.name+' with its saved source, seed and electronics. Review the new name and settings, then Start simulation.');
}
$('load').onclick=()=>{if(!busy&&!active)$('import').click();};
$('import').onchange=async()=>{
  const generation=++importGeneration,version=selectionVersion;
  try{
    if(busy||active)throw Error('Wait for the current action before loading a configuration.');
    const file=$('import').files[0];
    if(!file||file.size>65536)throw Error('Choose a configuration JSON under 64 KiB.');
    const selection=importedRequest(JSON.parse(await file.text()));
    if(generation!==importGeneration||version!==selectionVersion||busy||active){
      throw Error('Selection or activity changed while loading. Choose the configuration file again.');
    }
    applyConfiguration(selection);
    showTask('standard');showPage('new');
    notice('Configuration loaded. Review the settings, then Start simulation.');
  }catch(e){
    if(generation===importGeneration)notice(e.message,true);
  }finally{
    if(generation===importGeneration)$('import').value='';
  }
};
for(const button of document.querySelectorAll('[data-nav]')){
  button.onclick=()=>{
    if($('notice').className!=='notice error')notice('');
    if(button.dataset.nav==='runs'){openRunList();void refreshCandidateRuns();}
    else showPage(button.dataset.nav);
  };
}
for(const button of document.querySelectorAll('[data-task-choice]')){
  button.onclick=()=>{
    if($('notice').className!=='notice error')notice('');
    showTask(button.dataset.taskChoice);
  };
}
for(const button of document.querySelectorAll('[data-result-tab]')){
  button.onclick=()=>showResultTab(button.dataset.resultTab);
  button.onkeydown=event=>{
    const tabs=[...document.querySelectorAll('[data-result-tab]')],index=tabs.indexOf(button);
    let next;
    if(event.key==='ArrowRight')next=(index+1)%tabs.length;
    else if(event.key==='ArrowLeft')next=(index+tabs.length-1)%tabs.length;
    else if(event.key==='Home')next=0;
    else if(event.key==='End')next=tabs.length-1;
    else return;
    event.preventDefault();
    showResultTab(tabs[next].dataset.resultTab);
    tabs[next].focus();
  };
}
for(const button of document.querySelectorAll('[data-waveform-stage]'))button.onclick=()=>showWaveformStage(button.dataset.waveformStage);
$('browse-catalog').onchange=cryostatChanged;
$('setup-required-help').onclick=()=>{
  showPage('help');
  $('setup').focus();
  return $('setup').onclick();
};
$('run-list-back').onclick=openRunList;
$('open-saved-analysis').onclick=()=>{
  showPage('runs');
  $('run-list-panel').hidden=true;
  $('run-detail').hidden=true;
  $('saved-analysis').hidden=false;
  void refreshSavedGeGI();
};
$('saved-analysis-back').onclick=openRunList;
showPage('new');showTask('standard');showResultTab('overview');showWaveformStage();
(async()=>{try{catalog=await api('/api/workflow/catalog');options('cryostat',catalog.cryostats);electronics();$('numerics').textContent=catalog.numerics;$('setup-limit').textContent=catalog.setup_limit||'';selectDetector('AK02');stageList();for(const id of ['pose','angle-deg','gamma-energy-keV','gegi-source-x','gegi-source-y','gegi-source-z','count','seed','threads','name'])$(id).addEventListener('input',invalidate);$('cryostat').onchange=cryostatChanged;$('detector').onchange=detectorChanged;$('source').onchange=sourceChanged;await poll();$('name').value=uniqueRunName();invalidate();void estimateCandidateStorage();setInterval(poll,2500);}catch(e){notice(e.message,true);$('check').disabled=true;}})();
