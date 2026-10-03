'use strict';
const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const context=vm.createContext({});vm.runInContext(fs.readFileSync(__dirname+'/focused_plots.js','utf8'),context);
const api=context.SavedFocusPlots;
const t=Array.from({length:5002},(_,i)=>i*2),q=[0,100,...Array.from({length:5000},(_,i)=>100+i*1e-9)];
const before=JSON.stringify([t,q]);assert.equal(api.focusEnd(t,q),12);assert.equal(JSON.stringify([t,q]),before);assert.equal(t.at(-1),10002);
assert.equal(api.shaperEnd([0,1000,4900,8000],[0,1,.01,.001],{t:1000,v:1},10000),5194);
// A later retained lobe extends the shaper camera; zero and negative signs are untouched.
assert.equal(api.shaperEnd([0,1000,4900,8000],[0,1,.01,-.02],{t:1000,v:1},10000),8480);
console.log('Focused sampled-variation/shaper camera checks passed.');
