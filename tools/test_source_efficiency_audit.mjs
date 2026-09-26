import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const hash=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
const save=(p,v)=>fs.writeFileSync(p,JSON.stringify(v));
function fixture(){
 const dir=fs.mkdtempSync(path.join(root,'.local','efficiency-unit-'));
 const run={events_per_model:10000,status:'completed_with_native_failures',models:{}};
 for(const model of ['AK02','SAP22']){
  const folder=path.join(dir,model); fs.mkdirSync(path.join(folder,'transport'),{recursive:true}); fs.mkdirSync(path.join(folder,'response'));
  save(path.join(folder,'transport/scenario.json'),{source:{position_global_mm:[0,37.073,.29]},coordinate_transform:{rotation_local_to_global:[[1,0,0],[0,0,1],[0,-1,0]],translation_global_mm:[0,1.45,.29]}});
  save(path.join(folder,'transport/geometry-report.json'),{crystal_volume_mm3:Math.PI*12.65**2*9.4});
  fs.writeFileSync(path.join(folder,'transport/canonical.gdml'),'<rzpoint r="12.65" z="0"/><rzpoint r="0" z="9.4"/>');
  const rows=Array.from({length:10000},(_,i)=>({record_kind:'decay',event_id:i,global_decay_id:i,line_photon_count:1,deposited_energy_keV:i%100===0?10:0}));
  fs.writeFileSync(path.join(folder,'response/scalars.jsonl'),rows.map(JSON.stringify).join('\n'));
  save(path.join(folder,'response/run.json'),{artifacts:{'scalars.jsonl':hash(path.join(folder,'response/scalars.jsonl'))}});
  run.models[model]={response_report_sha256:hash(path.join(folder,'response/run.json'))};
 }
 save(path.join(dir,'run.json'),run); return dir;
}
const invoke=(d,o=path.join(d,'result.json'))=>spawnSync(process.execPath,[path.join(root,'tools/source_efficiency_audit.mjs'),d,o],{encoding:'utf8'});
const remove=d=>{assert.ok(path.basename(d).startsWith('efficiency-unit-'));fs.rmSync(d,{recursive:true});};
test('saved-census calculation and no overwrite',()=>{const d=fixture();try{
 const before=hash(path.join(d,'AK02/response/scalars.jsonl')); const r=invoke(d);assert.equal(r.status,0,r.stderr);
 const m=JSON.parse(fs.readFileSync(path.join(d,'result.json'))).models[0];
 assert.equal(m.Ge_positive_decays,100);assert.equal(m.Ge_positive_fraction,.01);assert.equal(m.source_to_top_mm,26.223);
 assert.equal(m.mean_energy_given_Ge_deposit_keV,10);assert.ok(m.approximate_line_only_interacting_fraction>0);
 assert.equal(hash(path.join(d,'AK02/response/scalars.jsonl')),before);assert.notEqual(invoke(d).status,0);
}finally{remove(d);}});
test('corrupted scalar artifact rejected',()=>{const d=fixture();try{
 fs.appendFileSync(path.join(d,'AK02/response/scalars.jsonl'),'\n');assert.notEqual(invoke(d).status,0);assert.ok(!fs.existsSync(path.join(d,'result.json')));
}finally{remove(d);}});
test('rehashed duplicate event rejected',()=>{const d=fixture();try{
 const p=path.join(d,'AK02/response/scalars.jsonl');const rows=fs.readFileSync(p,'utf8').split('\n');rows[1]=rows[0];fs.writeFileSync(p,rows.join('\n'));
 save(path.join(d,'AK02/response/run.json'),{artifacts:{'scalars.jsonl':hash(p)}});
 const r=JSON.parse(fs.readFileSync(path.join(d,'run.json')));r.models.AK02.response_report_sha256=hash(path.join(d,'AK02/response/run.json'));save(path.join(d,'run.json'),r);
 assert.notEqual(invoke(d).status,0);
}finally{remove(d);}});
test('outside output rejected',()=>{const d=fixture();try{
 assert.notEqual(invoke(d,path.join(root,'efficiency-result-not-created.json')).status,0);
 assert.ok(!fs.existsSync(path.join(root,'efficiency-result-not-created.json')));
}finally{remove(d);}});
