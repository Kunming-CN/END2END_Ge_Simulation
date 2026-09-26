// Offline, hash-checked view of a completed campaign; never runs simulations.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import readline from 'node:readline';
import {isDeepStrictEqual as same} from 'node:util';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const check=(ok,msg)=>{if(!ok)throw new Error(msg);};
const arg=process.argv[2], verifyOnly=process.argv[3]==='--verify-only';
check(arg&&(process.argv.length===3||(process.argv.length===4&&verifyOnly)),'Usage: node tools/native_campaign_report.mjs .local/CAMPAIGN [--verify-only]');
const dir=fs.realpathSync(path.resolve(arg)), local=fs.realpathSync(path.join(root,'.local'));
check(dir.startsWith(local+path.sep),'Campaign must be below project .local');
const json=p=>JSON.parse(fs.readFileSync(p,'utf8').replace(/^\uFEFF/,''));
const sha=async p=>{const h=crypto.createHash('sha256');for await(const b of fs.createReadStream(p))h.update(b);return h.digest('hex');};
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const output=path.join(dir,'comparison.html'), receipt=path.join(dir,'comparison.json');
if(!verifyOnly)check(!fs.existsSync(output)&&!fs.existsSync(receipt),'Report exists; no overwrite');
const campaign=json(path.join(dir,'run.json'));
const complete=(status,clean)=>status===clean||status==='completed_with_native_failures';
const failureMessages=['Noncontact endpoint outside crystal','Invalid waveform support'];
const unavailable=['final_induced_keV','charge_end_ns','native_any_negative_charge','native_min_charge_keV','native_max_charge_keV','transport_flags','endpoints','readout','current_nA','induced_charge_fC'];
async function* records(file){
  const lines=readline.createInterface({input:fs.createReadStream(file),crlfDelay:Infinity});
  try{for await(const line of lines)yield JSON.parse(line);}finally{lines.close();}
}
check(campaign.kind==='native_campaign_v1'&&complete(campaign.status,'completed_provisional_native_campaign'),'Campaign is not complete');
const verified=[];
for(const model of ['AK02','SAP22']){
  const folder=path.join(dir,model,'response'), run=json(path.join(folder,'run.json'));
  check(await sha(path.join(folder,'run.json'))===campaign.models[model].response_report_sha256,'Response receipt mismatch');
  check(complete(run.status,'completed_provisional_native_response')&&run.counts.initial_decays===campaign.events_per_model,'Response census/status mismatch');
  for(const file of ['scalars.jsonl','histograms.json'])check(Object.hasOwn(run.artifacts,file),'Missing artifact binding: '+file);
  for(const [file,h] of Object.entries(run.artifacts)){
    check(path.basename(file)===file,'Unsafe artifact path');
    check(await sha(path.join(folder,file))===h,'Artifact mismatch: '+model+'/'+file);
  }
  const flags={negative_native:0,negative_window:0,transport_flagged:0,step_limited:0,stopped_without_contact:0,current_balance_failed:0};
  let decay=0,pulses=0,accepted=0,readoutRejected=0,lastId=-1,inGroup=0,expectedGroups=0;
  const failures=new Map(), key=s=>`${s.event_id}/${s.group_id}`;
  for await(const s of records(path.join(folder,'scalars.jsonl'))){
    if(s.record_kind==='decay'){
      check(inGroup===expectedGroups&&s.event_id===decay&&s.global_decay_id===decay,'Scalar decay/group census mismatch');
      lastId=decay++; inGroup=0; expectedGroups=s.pulse_count;
    }else{
      check(s.record_kind==='pulse'&&s.event_id===lastId&&s.global_decay_id===lastId&&s.group_id===inGroup++,'Scalar pulse identity mismatch');
      check(typeof s.accepted==='boolean','Missing pulse acceptance');
      pulses++; accepted+=Number(s.accepted);
      if(s.status==='native_transport_failed'){
        check(s.accepted===false&&s.rejection_reason==='native_transport_failed'&&s.trace_saved===false,'Failed native acceptance/trace mismatch');
        check(unavailable.every(k=>s[k]===null),'Failed native output must be null');
        check(s.native_error?.type==='ArgumentError'&&failureMessages.includes(s.native_error.message)&&s.native_error.exact_error==='ArgumentError: '+s.native_error.message&&s.native_error.stage==='NativeLiExample.native_event','Unrecognized native error');
        check(s.endpoint_details_note==='Strict NativeLiExample.native_event does not expose rejected endpoint details; private supervisor diagnostics are separate.','Missing endpoint limitation');
        check(s.parcels===run.parcels&&s.seed_family===run.seed_family&&s.source_lh5_sha256===run.source_lh5_sha256&&s.raw_table==='stp/germanium','Failed native settings/provenance mismatch');
        failures.set(key(s),s); continue;
      }
      check(s.rejection_reason!=='native_transport_failed','Missing failed native status');
      readoutRejected+=Number(!s.accepted);
      flags.negative_native+=Number(s.native_any_negative_charge); flags.negative_window+=Number(s.readout.negative_input);
      flags.step_limited+=Number(s.transport_flags.step_limits>0); flags.stopped_without_contact+=Number(s.transport_flags.stopped_without_contact>0);
      flags.transport_flagged+=Number(s.transport_flags.step_limits>0||s.transport_flags.stopped_without_contact>0);
      flags.current_balance_failed+=Number(s.readout.current_balance.passed!==true);
    }
  }
  check(inGroup===expectedGroups&&decay===run.counts.initial_decays&&pulses===run.counts.groups&&accepted===run.counts.accepted,'Final scalar census mismatch');
  const failed=failures.size, successful=pulses-failed;
  check((run.status==='completed_with_native_failures')===(failed>0),'Response native failure status mismatch');
  check((run.counts.native_failed_groups??0)===failed&&(run.counts.readout_rejected??run.counts.rejected)===readoutRejected&&run.counts.rejected===failed+readoutRejected&&accepted+readoutRejected===successful,'Native/readout rejection census mismatch');
  if(campaign.models[model].status!==undefined)check(campaign.models[model].status===run.status,'Campaign model status mismatch');
  if(campaign.models[model].counts!==undefined)check(same(campaign.models[model].counts,run.counts),'Campaign model counts mismatch');
  if(failed){
    check(run.native_failure_policy==='record'&&run.counts.initial_primaries===decay,'Failure policy/primary census mismatch');
    for(const file of ['native-failures.jsonl','truth.jsonl','endpoints.jsonl','traces.jsonl','signals.csv'])check(Object.hasOwn(run.artifacts,file),'Missing failure artifact binding: '+file);
    const diagnostics=new Map();
    for await(const diag of records(path.join(folder,'native-failures.jsonl'))){
      const s=diag.pulse,k=key(s);
      check(diag.record_kind==='native_failure_diagnostic'&&failures.has(k)&&!diagnostics.has(k)&&same(s,failures.get(k)),'Failure diagnostic pulse mismatch');
      for(const field of ['model_id','model_sha256','input_sha256','source_sha256','temperature_K','bias_V','parcels','seed_family','seed_rule','diffusion','end_drift_when_no_field','self_repulsion','drift_dt_ns','nominal_drift_cap_ns','readout_contact_id','field_settings','field_fingerprint','profile_sha256','config_sha256','calibration','native_failure_policy']){
        check(Object.hasOwn(run,field)&&same(diag.settings[field],run[field]),'Failure diagnostic settings mismatch: '+field);
      }
      diagnostics.set(k,diag);
    }
    check(diagnostics.size===failed,'Failure diagnostic census mismatch');
    let truthCount=0,matched=0;
    for await(const e of records(path.join(folder,'truth.jsonl'))){
      check(e.event_id===truthCount&&e.global_decay_id===truthCount++,'Failure truth census mismatch');
      for(const g of e.pulse_groups){
        const k=`${e.event_id}/${g.group_id}`; if(!failures.has(k))continue;
        const s=failures.get(k), diag=diagnostics.get(k), byrow=new Map(e.steps.map(row=>[row.raw_row_index,row])), steps=g.row_indices.map(i=>byrow.get(i));
        check(steps.length>0&&steps.every(Boolean)&&new Set(g.row_indices).size===steps.length,'Failure raw rows missing/duplicated');
        check(same(diag.original_event,e)&&same(diag.original_group,g)&&same(diag.original_steps,steps)&&same(s.group,g)&&same(s.raw_row_indices,g.row_indices)&&s.origin_time_ns===g.origin_time_ns,'Failure original group/row mismatch');
        check(same(s.deposition_delays_ns,steps.map(row=>row.time_ns-g.origin_time_ns)),'Failure deposition delay mismatch');
        const edep=steps.reduce((n,row)=>n+row.energy_keV,0);
        check(Number.isFinite(s.deposited_energy_keV)&&edep>0&&Math.abs(s.deposited_energy_keV-edep)<=1e-12*Math.max(1,edep),'Failure truth energy mismatch');
        matched++;
      }
    }
    check(truthCount===decay&&matched===failed,'Failure truth group census mismatch');
    for(const file of ['endpoints.jsonl','traces.jsonl'])for await(const s of records(path.join(folder,file)))check(!failures.has(key(s)),'Fabricated failed native endpoint/trace');
    const signals=readline.createInterface({input:fs.createReadStream(path.join(folder,'signals.csv')),crlfDelay:Infinity});
    try{for await(const line of signals){
      const [id,,group]=line.split(',').slice(0,3).map(s=>s.replaceAll('"',''));
      check(!failures.has(`${id}/${group}`),'Fabricated failed native signal');
    }}finally{signals.close();}
  }else if(Object.hasOwn(run.artifacts,'native-failures.jsonl')){
    check(fs.readFileSync(path.join(folder,'native-failures.jsonl'),'utf8').trim()==='','Unexpected native failure diagnostics');
  }
  check(flags.current_balance_failed===0,'Current/charge balance failure');
  const hist=json(path.join(folder,'histograms.json'));
  check(same(hist.normalization_denominators,run.counts),'Histogram denominators mismatch');
  check(hist.bins.every(b=>Number.isInteger(b.count)&&b.count>0),'Invalid histogram count');
  for(const [stage,n] of [['deposited_per_decay',decay],['deposited_per_group',pulses],['native_terminal_charge',successful],['window_charge',successful],['preamp_charge_equivalent',successful],['analog_shaped_equivalent',successful],['accepted_peak_ADC',accepted]]){
    check(hist.bins.filter(b=>b.stage===stage).reduce((a,b)=>a+b.count,0)===n,'Histogram accounting mismatch: '+stage);
  }
  verified.push({model,run,hist,flags});
}
const totalFailed=verified.reduce((n,v)=>n+(v.run.counts.native_failed_groups??0),0);
check((campaign.status==='completed_with_native_failures')===(totalFailed>0),'Campaign native failure status mismatch');
if(campaign.native_failed_groups!==undefined)check(campaign.native_failed_groups===totalFailed,'Campaign native failure count mismatch');
if(campaign.readout_rejected!==undefined)check(campaign.readout_rejected===verified.reduce((n,v)=>n+(v.run.counts.readout_rejected??v.run.counts.rejected),0),'Campaign readout rejection count mismatch');
const stages=[['deposited_per_decay','Deposited energy / initial decay (includes zeroes)'],['deposited_per_group','Deposited energy / all groups (includes native failures)'],['native_terminal_charge','Native signed terminal charge / successful native group'],['analog_shaped_equivalent','Analog shaped peak / successful native group'],['accepted_peak_ADC','Accepted peak-ADC energy / pulse']];
function plot(hist,stage,label){
  const bins=hist.bins.filter(b=>b.stage===stage), finite=bins.filter(b=>b.lower_keV!==null&&b.upper_keV!==null);
  const lo=Math.min(0,...finite.map(b=>b.lower_keV)), hi=Math.max(10,...finite.map(b=>b.upper_keV));
  const max=Math.max(1,...bins.map(b=>b.count)), x=v=>58+530*(v-lo)/(hi-lo), y=n=>200-160*Math.log1p(n)/Math.log1p(max);
  const map=new Map(finite.map(b=>[b.lower_keV,b.count])); let d='';
  for(let v=lo;v<hi;v+=5){const yy=y(map.get(v)||0); d+=(d?' L':'M')+x(v)+','+yy+' L'+x(v+5)+','+yy;}
  let ticks=''; for(let i=0;i<=4;i++){const v=lo+(hi-lo)*i/4;ticks+=`<text x="${x(v)}" y="221" text-anchor="middle">${v.toFixed(0)}</text>`;}
  for(const n of [0,1,10,100,1000,10000])if(n<=max){ticks+=`<text x="50" y="${y(n)+4}" text-anchor="end">${n}</text>`;}
  const outside=bins.filter(b=>b.lower_keV===null||b.upper_keV===null).reduce((a,b)=>a+b.count,0);
  return `<figure><figcaption>${esc(label)}</figcaption><svg viewBox="0 0 610 248" role="img" aria-label="${esc(label)}"><path d="M58 30 V200 H588" stroke="currentColor" fill="none"/><path d="${d}" stroke="currentColor" fill="none" stroke-width="1.2"/>${ticks}<text x="275" y="242">Energy / keV-equivalent</text></svg><small>5 keV bins; count axis log(1+count). Under/overflow records: ${outside}.</small></figure>`;
}
let html=`<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Nominal Cs137 native campaign</title><style>body{font:16px/1.5 system-ui;max-width:1180px;margin:auto;padding:22px;color:#17334b}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}th,td{padding:8px;text-align:right;border-bottom:1px solid #ccd}th:first-child{text-align:left}.scroll{overflow:auto}.plots{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,420px),1fr))}figure{margin:12px 8px}svg{width:100%;font-size:11px}small{color:#536777}.note{padding:14px;background:#fff3df}a{color:inherit}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style><h1>Nominal Cs137 → native SSD → peak ADC</h1><p>${campaign.events_per_model.toLocaleString('en-US')} initial decays per detector; seed ${campaign.seed}. Real radioactive decays and delayed daughter emissions, not a monoenergetic substitution.</p><p class="note">Engineering scenario only. LBNL cryostat, capsule and detector pose include explicit nominal assumptions. AK02 and SAP22 have different geometry and transport models: this is not a matched Li/no-Li control. No measured hardware fit, physical FWHM, activity, live-time or absolute experimental-efficiency claim. Every initial decay, including zero deposits, remains in the saved ledger.</p><div class="scroll"><table><tr><th>Accounting</th><th>AK02</th><th>SAP22</th></tr>`;
for(const [key,label] of [['initial_decays','Initial decays'],['line_photons','Emitted 660–663 keV RDM photons'],['zero_deposit_primaries','Zero-Ge-deposit decays'],['groups','Isolated pulse groups'],['accepted','Accepted peak ADC'],['native_failed_groups','Native transport failed (no charge/readout)'],['readout_rejected','Electronics rejected'],['rejected','Total rejected groups'],['saturated','Saturated pulses']])html+=`<tr><th>${label}</th>${verified.map(v=>`<td>${v.run.counts[key]??(key==='readout_rejected'?v.run.counts.rejected:0)}</td>`).join('')}</tr>`;
html+='</table></div><p>These are different denominators. Stage CSVs additionally provide per-initial-decay, per-emitted-line-photon and per-accepted-pulse normalizations. Acceptance never removes decay records or clears transport flags.</p>';
if(totalFailed)html+=`<p class="note"><strong>completed_with_native_failures: ${totalFailed} native groups have no usable response.</strong> Their deposited energy remains in the truth/group histograms. Charge and analog stages contain successful native groups only; ADC contains accepted pulses only. No zero signals are substituted. Strict native_event does not expose rejected endpoint details; private supervisor diagnostics are separate. The native numerical anomaly remains unresolved.</p>`;
for(const v of verified){
  if(v.run.counts.native_failed_groups)html+=`<p><a href="${v.model}/response/native-failures.jsonl">${v.model}: original failed groups, rows, settings and exact errors</a></p>`;
  html+=`<h2>${v.model}</h2><p><a href="${v.model}/response/summary.html">Selected charge/current/preamp/shaper traces</a> · <a href="${v.model}/response/scalars.csv">Complete scalar ledger</a> · <a href="${v.model}/response/histograms.csv">Stage spectra</a> · <a href="${v.model}/response/run.json">Settings and numerical flags</a> · <a href="${v.model}/transport/stream/manifest.json">Raw transport provenance</a></p><pre>${esc(JSON.stringify(v.flags,null,2))}</pre><div class="plots">`;
  for(const [stage,label] of stages)html+=plot(v.hist,stage,label);
  html+='</div>';
}
html+='<p class="note">Signed charge is never rectified or calibrated against per-event deposited energy. One independent synthetic injection calibrates each fixed electronics profile. Native diffusion, finite trajectory caps and unresolved Li/grid sensitivity remain visible. Electronics reset for each finite isolated group; boundary splits, recovery uncertainty and possible tail loss are recorded. This is not a continuous acquisition simulation. Material deposition is recorded-only: unscored world-air, escape and neutrino terms prevent full energy closure.</p><p><a href="run.json">Campaign receipt</a> · <a href="comparison.json">Export checks and source hash</a></p></html>';
const evidence={kind:'native_campaign_report_v1',status:totalFailed?'completed_with_native_failures':'validated',campaign_status:campaign.status,campaign_sha256:await sha(path.join(dir,'run.json')),exporter_sha256:await sha(fileURLToPath(import.meta.url)),models:verified.map(v=>({model:v.model,counts:v.run.counts,flags:v.flags})),figure_policy:'Exact saved 5-keV histogram counts; log1p count display only; no fitting, smoothing, truth normalization or physical resolution inference'};
if(verifyOnly){
  console.log(JSON.stringify(evidence));
}else{
fs.writeFileSync(output,html,{flag:'wx'}); evidence.html_sha256=await sha(output);
fs.writeFileSync(receipt,JSON.stringify(evidence,null,2)+'\n',{flag:'wx'});
console.log(JSON.stringify({status:evidence.status,html:path.relative(root,output),counts:verified.map(v=>({model:v.model,...v.run.counts}))}));
}
