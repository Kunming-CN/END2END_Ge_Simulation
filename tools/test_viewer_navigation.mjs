import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const code=fs.readFileSync('tools/viewer_navigation.js','utf8');
const c=vm.createContext({URLSearchParams});vm.runInContext(code,c);
const plain=x=>JSON.parse(JSON.stringify(x));
let queryCases=0,aliasCases=0,historyCases=0;
const query=(s,options={})=>{queryCases++;return plain(c.parseViewerQuery(s,options));};
const alias=(s,view)=>{aliasCases++;return plain(c.legacyViewerTarget(s,view));};
const target=(identity,pathname,search)=>{historyCases++;return plain(c.viewerHistoryTarget(identity,pathname,search));};
assert.deepEqual(query(''),{model:'AK02',event:null,group:null,view:'assembly',invalid:''});
assert.deepEqual(query('?model=SAP22&event=0&group=0&view=positive'),{model:'SAP22',event:0,group:0,view:'positive',invalid:''});
assert.equal(query('?event=9999').event,9999);
for(const s of ['?event=','?event=-1','?event=10000','?event=1e2','?event=01','?event=1.5','?event=%2B1','?event=%201',
  '?event=0&event=1','?model=unknown','?model=AK02&model=SAP22','?foo=1','?group=0','?event=213&group=9007199254740992',
  '?event=213&group=-1','?event=213&group=00','?event=213&group=0&group=1','?view=','?view=combined','?view=assembly&view=positive'])assert.ok(query(s).invalid,s);
for(const s of ['?model=AK02&event=213&group=0','?model=SAP22&event=5930','?event=0','?event=213&group=9007199254740991','?view=positive'])assert.equal(query(s).invalid,'',s);
const positive=alias('?model=AK02&event=213&group=0','positive');
assert.equal(positive.target,'events.html?model=AK02&event=213&group=0&view=positive');
assert.equal(positive.requested.group,0);
const assembly=alias('?model=SAP22&event=5930','assembly');
assert.equal(assembly.target,'events.html?model=SAP22&event=5930&view=assembly');
assert.equal(assembly.requested.group,null);
assert.equal(alias('?model=SAP22&event=0&group=0','assembly').target,'events.html?model=SAP22&event=0&group=0&view=assembly');
assert.equal(alias('?event=213&group=999','assembly').requested.group,999); // Return context is not a group-existence check.
assert.equal(alias('','positive').target,'events.html?model=AK02&view=positive');
for(const s of ['?view=assembly','?event=213&view=positive','?event=0&event=1','?event=10000','?unknown=0','?group=0'])assert.equal(alias(s,'positive').target,null,s);
assert.equal(alias('?event=213','unknown').target,null);
const identity={model:'AK02',event:213,group:0,view:'positive',invalid:''};
const canonical=c.canonicalViewerQuery(identity);
assert.equal(canonical,'model=AK02&event=213&group=0&view=positive');
assert.deepEqual(query('?'+canonical),identity);
assert.equal(c.canonicalViewerQuery(query('?event=0&group=0')),'model=AK02&event=0&group=0&view=assembly');
assert.throws(()=>c.canonicalViewerQuery({...identity,invalid:'unavailable'}),/unavailable/);
assert.throws(()=>c.canonicalViewerQuery({...identity,model:'GeRC02'}),/model/);
assert.throws(()=>c.canonicalViewerQuery({...identity,event:null}),/requires/);
assert.throws(()=>c.canonicalViewerQuery({...identity,view:'unknown'}),/view/);
assert.equal(target(identity,'/viewers/events.html','?'+canonical).changed,false);
assert.equal(target({...identity,event:0},'/viewers/events.html','?'+canonical).changed,true);
assert.equal(target(identity,'/viewers/events.html','').target,'/viewers/events.html?'+canonical);
assert.equal(target({...identity,view:'assembly'},'/viewers/events.html','?'+canonical).changed,true);
assert.equal(target(identity,'/viewers/events.html','?view=positive&event=213&model=AK02&group=0').target,'/viewers/events.html?'+canonical);
let value=null,clears=0,gateRequests=0;
const gate=c.selectionGate(()=>{value=null;clears++;});
const runGate=(...args)=>{gateRequests++;return gate.run(...args);};
let resolveOld,rejectOld;
const old=runGate(()=>new Promise(r=>resolveOld=r),v=>value=v,e=>value=e.message);
await runGate(async()=>213,v=>value=v,e=>value=e.message);resolveOld(0);assert.equal(await old,false);assert.equal(value,213);
const failed=runGate(()=>new Promise((r,j)=>rejectOld=j),v=>value=v,e=>value=e.message);
await runGate(async()=>9999,v=>value=v,e=>value=e.message);rejectOld(Error('old failure'));assert.equal(await failed,false);assert.equal(value,9999);
let resolveInvalidated;
const pending=runGate(()=>new Promise(r=>resolveInvalidated=r),v=>value=v,e=>value=e.message);
gate.invalidate();resolveInvalidated(213);assert.equal(await pending,false);assert.equal(value,null);
assert.equal(await runGate(async()=>0,v=>value=v,e=>value=e.message),true);assert.equal(value,0);
assert.equal(await runGate(async()=>{throw Error('current failure');},v=>value=v,e=>value=e.message),false);assert.equal(value,'current failure');
assert.equal(clears,8);
const controller=fs.readFileSync('tools/unified_event_viewer.js','utf8');
const formatter=controller.slice(controller.indexOf('function exactJSON('),controller.indexOf('function requireViewer('));
const f=vm.createContext({});vm.runInContext(formatter,f);
function exactValues(actual,expected){
  if(expected===null||typeof expected!=='object'){assert.ok(Object.is(actual,expected));return;}
  assert.deepEqual(Object.keys(actual),Object.keys(expected));
  for(const key of Object.keys(expected))exactValues(actual[key],expected[key]);
}
let formatterCases=0;
for(const input of [-0,0,Number.MIN_VALUE,-Number.MIN_VALUE,Number.MAX_VALUE,-Number.MAX_VALUE,Number.EPSILON,
  1e-200,-1e200,0.1,348.72971054736263,'literal -0, "quoted", slash \\, newline\n, unicode γ',null,true,false,
  {'quoted"key':[-0,0,1.25,'-0'],nested:{negative:-0,ordinary:62.86589960084667}},[],{}]){
  exactValues(JSON.parse(f.exactJSON(input)),input);formatterCases++;
}
assert.equal(f.exactJSON(-0),'-0');assert.equal(f.exactJSON(0),'0');
assert.equal(f.exactJSON('literal -0'),JSON.stringify('literal -0'));
assert.deepEqual(JSON.parse(f.exactJSON({omitted:undefined,rows:[undefined,,2]})),JSON.parse(JSON.stringify({omitted:undefined,rows:[undefined,,2]})));
formatterCases++;
console.log(JSON.stringify({status:'passed',actual:{query_cases:queryCases,alias_cases:aliasCases,history_cases:historyCases,gate_requests:gateRequests,gate_invalidations:1,formatter_cases:formatterCases},
  late_success_and_failure:true,invalidated_pending_ignored:true,zero_preserved:true,legacy_keys:3,canonical_keys:4,science:0}));
