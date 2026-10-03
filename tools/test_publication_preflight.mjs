// Sandboxed dispatch fixtures only; no publisher, science, network or Git calls.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawnSync} from 'node:child_process';
import {preflight,FIXTURE_CHECKS,PRIVATE_REGRESSIONS,JAVASCRIPT_CHECKS,PRIVATE_BUNDLE_CHECKS} from './publication_preflight.mjs';
const project=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const parent=path.join(project,'.local');fs.mkdirSync(parent,{recursive:true});
const root=fs.mkdtempSync(path.join(parent,'publication-dispatch-test-'));
assert.ok(path.resolve(root).startsWith(path.resolve(parent)+path.sep));
try {
  const calls=[],messages=[];
  const invoke=()=>preflight({root,python:'fixture-python',node:'fixture-node',run:(exe,args)=>calls.push({exe,args}),log:text=>messages.push(text)});
  const names=()=>calls.map(call=>call.args.find(arg=>arg.endsWith('.py')||arg.endsWith('.js')||arg.endsWith('.mjs'))).map(file=>path.relative(root,file).replaceAll('\\','/'));
  invoke();
  for (const {test} of PRIVATE_REGRESSIONS) assert.ok(!names().includes(test));
  assert.equal(messages.length,PRIVATE_REGRESSIONS.length);
  for (const test of [...FIXTURE_CHECKS,...JAVASCRIPT_CHECKS,'tools/export_models.py','tools/check_site.py']) assert.ok(names().includes(test),test);
  assert.ok(messages.every(text=>text.startsWith('SKIP private saved-data regression:')));
  assert.ok(!calls.some(call=>call.args.includes('run')||call.args.includes('--gamma-showcase')||call.args.includes('--ring-results')));
  assert.ok(!calls.some(call=>call.args.includes('validate')));

  // Presence, not a completion marker, admits the direct closed validator.
  const check=PRIVATE_BUNDLE_CHECKS[0];
  const partial=path.join(root,check.bundle);
  fs.mkdirSync(partial,{recursive:true});
  fs.writeFileSync(path.join(partial,'data.json'),'corrupt partial data');
  assert.ok(!fs.existsSync(path.join(partial,'publication.json')));
  let direct=0;
  assert.throws(()=>preflight({root,python:'fixture-python',node:'fixture-node',log:()=>{},run:(exe,args)=>{
    if(args.includes('validate')) {direct++;assert.equal(args.at(-1),partial);throw new Error('markerless private bundle');}
  }}),/markerless private bundle/);
  assert.equal(direct,1);
  // Exercise the unchanged real validator, not only a dispatch spy. It reads
  // this exact newly-created malformed leaf and never exports or runs science.
  const python=process.env.SITE_PYTHON||(process.platform==='win32'?'C:/Program Files/ParaView 6.1.1/bin/pvpython.exe':'python3');
  const flags=path.basename(python).toLowerCase()==='pvpython.exe'?['--no-mpi','--disable-registry']:[];
  const rejectedBundle=spawnSync(python,[...flags,'-B',path.join(project,check.validator),'validate',partial],{cwd:project,encoding:'utf8'});
  if(rejectedBundle.error) throw rejectedBundle.error;
  assert.notEqual(rejectedBundle.status,0);
  assert.match(rejectedBundle.stderr+rejectedBundle.stdout,/Exact completed publication inventory/);
  // Remove only the already-resolved leaf created by this fixture.
  fs.rmSync(path.join(root,check.root),{recursive:true,force:false});

  // A single incomplete input root still dispatches the full strict regression.
  fs.mkdirSync(path.join(root,PRIVATE_REGRESSIONS[2].roots[0]),{recursive:true});
  let rejected=false;
  assert.throws(()=>preflight({root,python:'fixture-python',node:'fixture-node',log:()=>{},run:(exe,args)=>{
    if (args.some(arg=>arg.endsWith('test_saved_focus_waveforms.py'))) {rejected=true;throw new Error('partial saved inputs');}
  }}),/partial saved inputs/);
  assert.equal(rejected,true);
  for (const {roots} of PRIVATE_REGRESSIONS) for (const relative of roots) fs.mkdirSync(path.join(root,relative),{recursive:true});
  calls.length=0;messages.length=0;invoke();
  for (const {test} of PRIVATE_REGRESSIONS) assert.ok(names().includes(test),test);
  assert.ok(calls.some(call=>call.args.includes('validate')&&call.args.at(-1)===path.join(root,check.bundle)));
  assert.equal(messages.length,0);
  for (const test of [...FIXTURE_CHECKS,...JAVASCRIPT_CHECKS,'tools/export_models.py','tools/check_site.py']) assert.ok(names().includes(test),test);
  // A corrupt public snapshot must fail in either private-data state.
  assert.throws(()=>preflight({root,python:'fixture-python',node:'fixture-node',log:()=>{},run:(exe,args)=>{
    if (args.some(arg=>arg.endsWith('check_site.py'))) throw new Error('public artifact hash differs');
  }}),/public artifact hash differs/);
  const publisher=fs.readFileSync(path.join(project,'tools/publish.mjs'),'utf8');
  assert.match(publisher,/preflight\(\{root,python,node:process\.execPath,run\}\)/);
  assert.match(publisher,/existingSnapshot.*\nif \(!existingSnapshot\) throw/);
  assert.match(publisher,/tools\/check_site\.py/);
  assert.ok(!publisher.includes('test_local_ui_frontend.js'));
  console.log('Publication dispatch: public/fixture checks always run; absent private data skips explicitly; partial/corrupt data fails.');
} finally {
  // Only the exact freshly created fixture within this project's .local tree.
  assert.ok(path.resolve(root).startsWith(path.resolve(parent)+path.sep));
  fs.rmSync(root,{recursive:true,force:false});
}
