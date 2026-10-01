'use strict';
// Bounded DOM fixture for an in-flight results response during a status refresh.
// This is a mocked race test, not browser/mobile/download acceptance.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
  constructor(tag){this.tag=tag;this.children=[];this.parent=null;this.nodeType=1;this.className='';this.textContent='';this.open=false;}
  get childNodes(){return this.children;}
  get isConnected(){return this.root===true||!!this.parent?.isConnected;}
  append(...nodes){for(const n of nodes){n.remove();n.parent=this;this.children.push(n);}}
  remove(){if(this.parent){const a=this.parent.children;a.splice(a.indexOf(this),1);this.parent=null;}}
  insertBefore(n,before){n.remove();n.parent=this;const i=this.children.indexOf(before);this.children.splice(i<0?this.children.length:i,0,n);}
  replaceWith(n){const parent=this.parent;if(parent){parent.insertBefore(n,this);this.remove();}}
  querySelector(selector){return this.children.find(n=>selector[0]==='.'?n.className===selector.slice(1):n.tag===selector)||this.children.map(n=>n.querySelector(selector)).find(Boolean)||null;}
  addEventListener(){}
}
async function main(){
  const elements=Object.fromEntries(['name','detector','notice','check','run','resolved','jobs','connection'].map(k=>[k,new Element(k)]));
  elements.jobs.root=true;elements.detector.value='AK02';elements.name.value='fixture';
  let deliver;
  const response=new Promise(resolve=>{deliver=resolve;});
  const context=vm.createContext({document:{getElementById:id=>elements[id],createElement:tag=>new Element(tag)},
    location:{hash:'',pathname:'/'},sessionStorage:{getItem:()=>'',setItem(){}},history:{replaceState(){}},window:{addEventListener(){}},
    Node:{TEXT_NODE:3},URLSearchParams,fetch:path=>path.startsWith('/api/file')?response:new Promise(()=>{}),setInterval(){}});
  vm.runInContext(fs.readFileSync(__dirname+'/local_ui.js','utf8'),context);
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
  deliver({ok:true,text:async()=>raw+'\n'});
  await pending;
  assert.equal(old.querySelector('.events'),null);
  assert.ok(current.querySelector('.events')?.isConnected);
  assert.equal(current.querySelector('.events').querySelector('pre').textContent,raw);
  assert.equal(current.querySelector('p').textContent,'原始事件统计：初级粒子 3 · 零沉积 1 · 非零沉积 2 · 脉冲组 2');
  // Removing a job while its response is pending must not attach to another job.
  const again=vm.runInContext('showEvents(fixtureJob)',context);
  vm.runInContext('render({active:null,jobs:[{id:"different-id",name:"other",status:"failed",logs:[]}]})',context);
  await again;
  assert.equal(elements.jobs.children[0].querySelector('.events'),null);
  console.log('PASS: delayed response uses current job identity; raw record bytes retained; removed job is not retargeted.');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
