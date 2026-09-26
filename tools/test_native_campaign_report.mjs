import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const digest=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
const save=(p,x)=>fs.writeFileSync(p,JSON.stringify(x));
const read=p=>JSON.parse(fs.readFileSync(p,'utf8'));
const rows=p=>fs.readFileSync(p,'utf8').trim().split('\n').filter(Boolean).map(JSON.parse);
const jsonl=(p,rs)=>fs.writeFileSync(p,rs.map(r=>JSON.stringify(r)).join('\n')+(rs.length?'\n':''));
const changeJSON=(folder,file,f)=>{const value=read(path.join(folder,file));f(value);save(path.join(folder,file),value);};
const changeRows=(folder,file,f)=>{const value=rows(path.join(folder,file));f(value);jsonl(path.join(folder,file),value);};
function fixture({failed=false,empty=false}={}){
  const dir=fs.mkdtempSync(path.join(root,'.local','native-report-unit-'));
  const campaign={kind:'native_campaign_v1',status:failed?'completed_with_native_failures':'completed_provisional_native_campaign',events_per_model:2,seed:123,models:{}};
  for(const model of ['AK02','SAP22']){
    const folder=path.join(dir,model,'response'); fs.mkdirSync(folder,{recursive:true});
    const scalars=[{record_kind:'decay',event_id:0,global_decay_id:0,pulse_count:empty?0:failed?2:1},
      {record_kind:'pulse',event_id:0,global_decay_id:0,group_id:0,accepted:true,native_any_negative_charge:true,transport_flags:{step_limits:1,stopped_without_contact:0},readout:{negative_input:true,current_balance:{passed:true}}},
      {record_kind:'decay',event_id:1,global_decay_id:1,pulse_count:0}];
    if(empty)scalars.splice(1,1);
    const bins=(empty?[]:['deposited_per_decay','deposited_per_group','native_terminal_charge','window_charge','preamp_charge_equivalent','analog_shaped_equivalent','accepted_peak_ADC']).map(stage=>({stage,bin:202,lower_keV:10,upper_keV:15,count:failed&&stage==='deposited_per_group'?2:1}));
    bins.push({stage:'deposited_per_decay',bin:200,lower_keV:0,upper_keV:5,count:empty?2:1});
    const counts={initial_primaries:2,initial_decays:2,line_photons:2,zero_deposit_primaries:empty?2:1,groups:empty?0:failed?2:1,accepted:empty?0:1,rejected:failed?1:0,readout_rejected:0,native_failed_groups:failed?1:0,saturated:0};
    const run={status:failed?'completed_with_native_failures':'completed_provisional_native_response',counts,
      model_id:model,model_sha256:'model-hash',input_sha256:'input-hash',source_lh5_sha256:'raw-hash',source_sha256:{'native_li_example.jl':'strict-helper-hash'},
      temperature_K:77,bias_V:model==='AK02'?500:700,parcels:16,seed_family:2609261,seed_rule:'recorded seed rule',diffusion:true,end_drift_when_no_field:false,self_repulsion:false,
      drift_dt_ns:2,nominal_drift_cap_ns:10000,readout_contact_id:1,field_settings:{precision_bits:64},field_fingerprint:{E:{data_sha256:'field-hash'}},profile_sha256:'profile-hash',config_sha256:'config-hash',calibration:{volts_per_keV:0.001},native_failure_policy:'record'};
    const artifacts=['scalars.jsonl','histograms.json'];
    if(failed){
      const group={group_id:1,origin_time_ns:100,row_indices:[12],horizon_ns:10000};
      const steps=[{raw_row_index:11,time_ns:0,energy_keV:10,raw:{trackid:3}},{raw_row_index:12,time_ns:105,energy_keV:7,raw:{trackid:4}}];
      const original={event_id:0,global_decay_id:0,primary_time_ns:0,steps,pulse_groups:[{group_id:0,origin_time_ns:0,row_indices:[11],horizon_ns:10000},group]};
      const pulse={record_kind:'pulse',status:'native_transport_failed',event_id:0,global_decay_id:0,group_id:1,origin_time_ns:100,group,raw_row_indices:[12],deposition_delays_ns:[5],deposited_energy_keV:7,source_lh5_sha256:'raw-hash',raw_table:'stp/germanium',parcels:16,seed_family:2609261,
        accepted:false,rejection_reason:'native_transport_failed',trace_saved:false,native_error:{type:'ArgumentError',message:'Noncontact endpoint outside crystal',exact_error:'ArgumentError: Noncontact endpoint outside crystal',stage:'NativeLiExample.native_event'},
        endpoint_details_note:'Strict NativeLiExample.native_event does not expose rejected endpoint details; private supervisor diagnostics are separate.'};
      for(const key of ['final_induced_keV','charge_end_ns','native_any_negative_charge','native_min_charge_keV','native_max_charge_keV','transport_flags','endpoints','readout','current_nA','induced_charge_fC'])pulse[key]=null;
      scalars.splice(2,0,pulse);
      jsonl(path.join(folder,'native-failures.jsonl'),[{record_kind:'native_failure_diagnostic',pulse,original_event:original,original_group:group,original_steps:[steps[1]],settings:{...run}}]);
      jsonl(path.join(folder,'truth.jsonl'),[original,{event_id:1,global_decay_id:1,primary_time_ns:0,steps:[],pulse_groups:[]}]);
      jsonl(path.join(folder,'endpoints.jsonl'),[]); jsonl(path.join(folder,'traces.jsonl'),[]);
      fs.writeFileSync(path.join(folder,'signals.csv'),'event_id,global_decay_id,group_id,time_since_origin_ns,induced_equivalent_energy_keV\n');
      artifacts.push('native-failures.jsonl','truth.jsonl','endpoints.jsonl','traces.jsonl','signals.csv');
    }
    jsonl(path.join(folder,'scalars.jsonl'),scalars);
    save(path.join(folder,'histograms.json'),{bins,normalization_denominators:counts});
    run.artifacts=Object.fromEntries(artifacts.map(f=>[f,digest(path.join(folder,f))]));
    save(path.join(folder,'run.json'),run); campaign.models[model]={response_report_sha256:digest(path.join(folder,'run.json'))};
  }
  save(path.join(dir,'run.json'),campaign); return dir;
}
const run=dir=>spawnSync(process.execPath,[path.join(root,'tools/native_campaign_report.mjs'),dir],{cwd:root,encoding:'utf8'});
const clean=dir=>{assert.ok(path.basename(dir).startsWith('native-report-unit-'));fs.rmSync(dir,{recursive:true});};
// Rehash only disposable synthetic fixtures to challenge semantic validation.
function rebindFixture(dir,model='AK02'){
  assert.ok(path.basename(dir).startsWith('native-report-unit-'));
  const folder=path.join(dir,model,'response'), meta=read(path.join(folder,'run.json'));
  for(const file of Object.keys(meta.artifacts))meta.artifacts[file]=digest(path.join(folder,file));
  save(path.join(folder,'run.json'),meta);
  const campaign=read(path.join(dir,'run.json')); campaign.models[model].response_report_sha256=digest(path.join(folder,'run.json')); save(path.join(dir,'run.json'),campaign);
}
test('completed counts, signed flags and no-overwrite',()=>{
  const dir=fixture(); try{
    const result=run(dir); assert.equal(result.status,0,result.stderr);
    const receipt=JSON.parse(fs.readFileSync(path.join(dir,'comparison.json')));
    assert.equal(receipt.models[0].flags.negative_native,1); assert.equal(receipt.models[0].flags.step_limited,1);
    assert.equal(receipt.status,'validated'); assert.equal(receipt.models[0].counts.native_failed_groups,0);
    assert.equal(fs.existsSync(path.join(dir,'AK02/response/native-failures.jsonl')),false);
    const before=digest(path.join(dir,'comparison.html')); assert.notEqual(run(dir).status,0);
    assert.equal(digest(path.join(dir,'comparison.html')),before);
  }finally{clean(dir);}
});
test('explicit native failures preserve truth census, nulls and original hashes',()=>{
  const dir=fixture({failed:true}); try{
    const folder=path.join(dir,'AK02/response'), meta=read(path.join(folder,'run.json'));
    const before=Object.fromEntries(['run.json','truth.jsonl','native-failures.jsonl',...Object.keys(meta.artifacts)].map(f=>[f,digest(path.join(folder,f))]));
    const result=run(dir); assert.equal(result.status,0,result.stderr);
    const receipt=read(path.join(dir,'comparison.json')), counts=receipt.models[0].counts;
    assert.equal(receipt.status,'completed_with_native_failures');
    assert.equal(counts.initial_decays,2); assert.equal(counts.groups,2); assert.equal(counts.native_failed_groups,1); assert.equal(counts.readout_rejected,0);
    assert.equal(receipt.models[0].flags.negative_native,1);
    const html=fs.readFileSync(path.join(dir,'comparison.html'),'utf8');
    assert.match(html,/completed_with_native_failures/); assert.match(html,/Electronics rejected/); assert.match(html,/anomaly remains unresolved/);
    for(const [f,h] of Object.entries(before))assert.equal(digest(path.join(folder,f)),h);
    assert.deepEqual(read(path.join(folder,'run.json')).calibration,meta.calibration);
    assert.deepEqual(read(path.join(folder,'run.json')).field_fingerprint,meta.field_fingerprint);
  }finally{clean(dir);}
});
test('empty positive-group census stays clean without synthetic failure flags',()=>{
  const dir=fixture({empty:true}); try{
    const result=run(dir); assert.equal(result.status,0,result.stderr);
    const receipt=read(path.join(dir,'comparison.json'));
    assert.equal(receipt.status,'validated'); assert.equal(receipt.models[0].counts.groups,0);
    assert.equal(receipt.models[0].flags.negative_native,0);
  }finally{clean(dir);}
});
test('electronics rejection remains separate from native failure',()=>{
  const dir=fixture({failed:true}); try{
    for(const model of ['AK02','SAP22']){
      const folder=path.join(dir,model,'response');
      changeRows(folder,'scalars.jsonl',r=>{r[1].accepted=false;r[1].rejection_reason='below_threshold';});
      const meta=read(path.join(folder,'run.json'));
      meta.counts.accepted=0; meta.counts.rejected=2; meta.counts.readout_rejected=1;
      const hist=read(path.join(folder,'histograms.json'));
      hist.bins=hist.bins.filter(b=>b.stage!=='accepted_peak_ADC'); hist.normalization_denominators=meta.counts;
      save(path.join(folder,'histograms.json'),hist); save(path.join(folder,'run.json'),meta); rebindFixture(dir,model);
    }
    const result=run(dir); assert.equal(result.status,0,result.stderr);
    const counts=read(path.join(dir,'comparison.json')).models[0].counts;
    assert.equal(counts.native_failed_groups,1); assert.equal(counts.readout_rejected,1); assert.equal(counts.accepted,0);
  }finally{clean(dir);}
});
test('historical clean counts remain exportable without rebasing receipts',()=>{
  const dir=fixture(); try{
    for(const model of ['AK02','SAP22']){
      const folder=path.join(dir,model,'response'), meta=read(path.join(folder,'run.json'));
      delete meta.counts.native_failed_groups; delete meta.counts.readout_rejected;
      const hist=read(path.join(folder,'histograms.json')); hist.normalization_denominators=meta.counts;
      save(path.join(folder,'histograms.json'),hist); save(path.join(folder,'run.json'),meta); rebindFixture(dir,model);
    }
    const result=run(dir); assert.equal(result.status,0,result.stderr);
  }finally{clean(dir);}
});
const mutations=[
  ['clean response status with failure',f=>changeJSON(f,'run.json',r=>{r.status='completed_provisional_native_response';})],
  ['abort policy with failure',f=>changeJSON(f,'run.json',r=>{r.native_failure_policy='abort';})],
  ['failed group count',f=>changeJSON(f,'run.json',r=>{r.counts.native_failed_groups=0;})],
  ['readout rejection conflation',f=>changeJSON(f,'run.json',r=>{r.counts.readout_rejected=1;})],
  ['accepted failed group',f=>changeRows(f,'scalars.jsonl',r=>{r[2].accepted=true;})],
  ['missing failed status',f=>changeRows(f,'scalars.jsonl',r=>{delete r[2].status;})],
  ['unknown native exception',f=>changeRows(f,'scalars.jsonl',r=>{r[2].native_error.message='other error';})],
  ['diagnostic omitted',f=>jsonl(path.join(f,'native-failures.jsonl'),[])],
  ['diagnostic duplicated',f=>changeRows(f,'native-failures.jsonl',r=>{r.push(r[0]);})],
  ['original raw row',f=>changeRows(f,'native-failures.jsonl',r=>{r[0].original_steps[0].raw.trackid=99;})],
  ['original event identity',f=>changeRows(f,'native-failures.jsonl',r=>{r[0].original_event.global_decay_id=99;})],
  ['field hash',f=>changeRows(f,'native-failures.jsonl',r=>{r[0].settings.field_fingerprint.E.data_sha256='changed';})],
  ['calibration',f=>changeRows(f,'native-failures.jsonl',r=>{r[0].settings.calibration.volts_per_keV=2;})],
  ['truth census omitted',f=>changeRows(f,'truth.jsonl',r=>{r.pop();})],
  ['failure diagnostic unbound',f=>changeJSON(f,'run.json',r=>{delete r.artifacts['native-failures.jsonl'];})],
  ['native histogram includes failed group',f=>changeJSON(f,'histograms.json',r=>{r.bins.find(b=>b.stage==='native_terminal_charge').count++;})],
  ['deposited histogram omits failed group',f=>changeJSON(f,'histograms.json',r=>{r.bins.find(b=>b.stage==='deposited_per_group').count--;})],
  ['normalization omits initial decay',f=>changeJSON(f,'histograms.json',r=>{r.normalization_denominators.initial_decays--;})],
  ['fabricated endpoint',f=>jsonl(path.join(f,'endpoints.jsonl'),[{event_id:0,global_decay_id:0,group_id:1}])],
  ['fabricated trace',f=>jsonl(path.join(f,'traces.jsonl'),[{event_id:0,global_decay_id:0,group_id:1,trace:{}}])],
  ['fabricated zero signal',f=>fs.appendFileSync(path.join(f,'signals.csv'),'"0","0","1","0","0"\n')],
];
for(const field of ['final_induced_keV','charge_end_ns','native_any_negative_charge','native_min_charge_keV','native_max_charge_keV','transport_flags','endpoints','readout','current_nA','induced_charge_fC']){
  mutations.push(['non-null '+field,f=>changeRows(f,'scalars.jsonl',r=>{r[2][field]=0;})]);
}
// Mutate both copies to ensure the truth comparison, not just duplicate-record equality, rejects them.
for(const [name,edit] of [['delay',s=>{s.deposition_delays_ns=[0];}],['energy',s=>{s.deposited_energy_keV=8;}],['row identity',s=>{s.raw_row_indices=[99];}],['seed',s=>{s.seed_family=42;}]]){
  mutations.push([name,f=>{changeRows(f,'scalars.jsonl',r=>edit(r[2]));changeRows(f,'native-failures.jsonl',r=>edit(r[0].pulse));}]);
}
for(const [name,mutate] of mutations)test('deliberately rehashed failure mutation rejected: '+name,()=>{
  const dir=fixture({failed:true}); try{
    mutate(path.join(dir,'AK02/response')); rebindFixture(dir);
    assert.notEqual(run(dir).status,0); assert.equal(fs.existsSync(path.join(dir,'comparison.html')),false);
  }finally{clean(dir);}
});
test('campaign cannot hide response native failures behind clean status',()=>{
  const dir=fixture({failed:true}); try{
    changeJSON(dir,'run.json',r=>{r.status='completed_provisional_native_campaign';});
    assert.notEqual(run(dir).status,0); assert.equal(fs.existsSync(path.join(dir,'comparison.html')),false);
  }finally{clean(dir);}
});
test('corrupt artifact fails without a rendered success page',()=>{
  const dir=fixture(); try{
    fs.appendFileSync(path.join(dir,'AK02/response/scalars.jsonl'),'\n'); assert.notEqual(run(dir).status,0);
    assert.equal(fs.existsSync(path.join(dir,'comparison.html')),false);
  }finally{clean(dir);}
});
test('deliberately rehashed duplicate decay fails semantic census',()=>{
  const dir=fixture(); try{
    const folder=path.join(dir,'AK02/response'), scalar=path.join(folder,'scalars.jsonl');
    const rows=fs.readFileSync(scalar,'utf8').trim().split('\n').map(JSON.parse); rows[2].event_id=0;
    fs.writeFileSync(scalar,rows.map(r=>JSON.stringify(r)).join('\n')+'\n');
    const meta=JSON.parse(fs.readFileSync(path.join(folder,'run.json'))); meta.artifacts['scalars.jsonl']=digest(scalar); save(path.join(folder,'run.json'),meta);
    const campaign=JSON.parse(fs.readFileSync(path.join(dir,'run.json'))); campaign.models.AK02.response_report_sha256=digest(path.join(folder,'run.json')); save(path.join(dir,'run.json'),campaign);
    assert.notEqual(run(dir).status,0); assert.equal(fs.existsSync(path.join(dir,'comparison.html')),false);
  }finally{clean(dir);}
});

test('verify-only validates existing artifacts without writing or rerunning anything',()=>{
  const dir=fixture({failed:true}); try{
    const command=()=>spawnSync(process.execPath,[path.join(root,'tools/native_campaign_report.mjs'),dir,'--verify-only'],{cwd:root,encoding:'utf8'});
    const first=command(); assert.equal(first.status,0,first.stderr);
    assert.equal(JSON.parse(first.stdout).status,'completed_with_native_failures');
    assert.equal(fs.existsSync(path.join(dir,'comparison.html')),false);
    assert.equal(run(dir).status,0);
    const before=digest(path.join(dir,'comparison.html')), receipt=digest(path.join(dir,'comparison.json'));
    assert.equal(command().status,0);
    assert.equal(digest(path.join(dir,'comparison.html')),before);
    assert.equal(digest(path.join(dir,'comparison.json')),receipt);
    fs.appendFileSync(path.join(dir,'AK02/response/scalars.jsonl'),'{}\n');
    assert.notEqual(command().status,0);
    assert.equal(digest(path.join(dir,'comparison.html')),before);
  }finally{clean(dir);}
});
