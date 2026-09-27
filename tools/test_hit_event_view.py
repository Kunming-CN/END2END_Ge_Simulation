"""No solver/package dependencies. Run with pvpython --disable-registry --no-mpi -B."""
import copy
import gzip
import json
import math
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import hit_event_view as v

PROCESSES = {1: 'RadioactiveDecay', 2: 'compt', 3: 'phot', 4: 'eIoni'}


def track(tid, parent, particle, proc, energy=0, time=10, x=0):
    return dict(trackid=tid, parent_trackid=parent, particle=particle, procid=proc,
                ekin=energy, time=time, xloc=x, yloc=0, zloc=0, raw_row_index=tid, evtid=0)


def step(tid, parent, particle, energy, index=0, time=11, x=0):
    r = dict(trackid=tid, parent_trackid=parent, particle=particle, edep=energy,
             raw_row_index=index, time=time, xloc=x, yloc=0, zloc=0, evtid=0)
    for suffix in ('_pre', '_post'):
        for key in ('xloc', 'yloc', 'zloc'):
            r[key+suffix] = r[key]
    return r


def fixture():
    return {'event_id': 0, 'tables': {
        'tracks': [track(1, 0, 1000551370, -1), track(2, 1, 22, 1, .5),
                   track(3, 2, 11, 3, .5, time=11)],
        'stp/germanium': [step(2, 1, 22, 0), step(3, 2, 11, 500, 1)],
        'stp/passive': [], 'vtx': [], 'particles': []}}


def first(event):
    return v.classify(event, PROCESSES)['groups'][0]


class ClassificationTests(unittest.TestCase):
    def test_photon_energy_not_cs_decay_budget(self):
        e = fixture(); g = first(e)
        self.assertEqual(g['source_photon_energy_keV'], 500)
        self.assertEqual(g['categories'], ['full', 'compact'])
        e['tables']['stp/germanium'][1]['edep'] = 661.657
        self.assertEqual(first(e)['categories'], ['unknown'])

    def test_energy_boundaries(self):
        for photon in (31.818, 500, 661.657283, 1e6):
            tol = v.energy_tolerance(photon)
            for sign in (-1, 1):
                self.assertEqual(v.energy_class(photon+sign*tol*.999, photon), 'full')
                self.assertEqual(v.energy_class(photon+sign*tol*1.001, photon), 'partial' if sign < 0 else 'unknown')
        # Exactly representable relative to this tolerance: both inclusive boundaries.
        self.assertEqual(v.energy_class(0, 1e-5), 'full')
        self.assertEqual(v.energy_class(2e-5, 1e-5), 'full')
        self.assertEqual(v.energy_class(math.nextafter(2e-5, math.inf), 1e-5), 'unknown')
        self.assertEqual(v.energy_class(-1e-20, 1e-5), 'partial')

    def test_missing_ancestor(self):
        e = fixture(); e['tables']['tracks'][1]['parent_trackid'] = 99
        self.assertEqual(first(e)['categories'], ['unknown'])
        self.assertTrue(v.classify(e, PROCESSES)['graph_errors'])

    def test_cycle_and_unused_cycle(self):
        for connect in (True, False):
            e = fixture()
            if connect:
                e['tables']['tracks'][0]['parent_trackid'] = 3
            else:
                e['tables']['tracks'] += [track(7, 8, 11, 4), track(8, 7, 11, 4)]
            self.assertEqual(first(e)['categories'], ['unknown'])
            self.assertTrue(any('cycle' in s for s in v.classify(e, PROCESSES)['graph_errors']))

    def test_duplicate_track(self):
        e = fixture(); e['tables']['tracks'].append(copy.deepcopy(e['tables']['tracks'][-1]))
        self.assertEqual(first(e)['categories'], ['unknown'])

    def test_mixed_photons_same_window(self):
        e = fixture(); e['tables']['tracks'].append(track(4, 1, 22, 1, .1))
        e['tables']['stp/germanium'].append(step(4, 1, 22, 100, 2))
        g = first(e)
        self.assertEqual(g['categories'], ['unknown']); self.assertEqual(g['source_photon_track_ids'], [2, 4])

    def test_photon_plus_beta_is_unknown(self):
        e = fixture(); e['tables']['tracks'].append(track(4, 1, 11, 1, .1))
        e['tables']['stp/germanium'].append(step(4, 1, 11, 100, 2))
        self.assertEqual(first(e)['categories'], ['unknown'])

    def test_wrong_creation_process_is_not_source_photon(self):
        e = fixture(); e['tables']['tracks'][1]['procid'] = 4
        self.assertEqual(first(e)['categories'], ['unknown'])

    def test_wrong_ion_parent_unknown(self):
        e = fixture(); e['tables']['tracks'][0]['particle'] = 11
        self.assertEqual(first(e)['categories'], ['unknown'])

    def test_step_identity_mismatch(self):
        e = fixture(); e['tables']['stp/germanium'][1]['parent_trackid'] = 1
        self.assertEqual(first(e)['categories'], ['unknown'])

    def test_temporally_separate_emissions_never_merge(self):
        e = fixture(); e['tables']['tracks'].append(track(4, 1, 22, 1, .1, time=60e9))
        e['tables']['stp/germanium'].append(step(4, 1, 22, 100, 2, time=60e9+1))
        groups = v.classify(e, PROCESSES)['groups']
        self.assertEqual(len(groups), 2)
        self.assertEqual([g['ge_energy_keV'] for g in groups], [500, 100])
        self.assertTrue(all('full' in g['categories'] for g in groups))
        self.assertEqual(groups[1]['origin_time_ns'], 60e9+1)
        self.assertEqual(groups[1]['relative_delays_ns'], [0])

    def test_fixed_window_not_sliding_merge(self):
        rows = [step(3, 2, 11, 1, i, time=t) for i, t in enumerate((0, 99999, 100000, 199999, 200000))]
        self.assertEqual([len(g) for g in v.pulse_groups(rows, 100000)], [2, 2, 1])

    def test_containment_per_group_not_total(self):
        e = fixture(); e['tables']['stp/germanium'][1]['edep'] = 250
        e['tables']['stp/germanium'].append(step(3, 2, 11, 250, 2, time=100011))
        groups = v.classify(e, PROCESSES)['groups']
        self.assertEqual([g['categories'] for g in groups], [['partial'], ['partial']])
        self.assertEqual([g['root_other_group_ge_energy_keV'] for g in groups], [250, 250])

    def test_multiple_electron_steps_are_one_compton_site(self):
        e = fixture(); e['tables']['tracks'][2]['procid'] = 2
        e['tables']['stp/germanium'] = [step(2, 1, 22, 0)] + [step(3, 2, 11, 100, i+1) for i in range(5)]
        g = first(e)
        self.assertEqual(g['observed_compton_site_count'], 1)
        self.assertNotIn('compton1', g['categories'])  # No observed photoelectric absorption.

    def test_same_vertex_electrons_share_site(self):
        e = fixture(); e['tables']['tracks'][2]['procid'] = 2
        e['tables']['tracks'].append(track(4, 2, 11, 2, .001, time=11))
        g = first(e)
        self.assertEqual(g['observed_compton_site_count'], 1)
        self.assertEqual(g['sites'][0]['electron_track_ids'], [3, 4])

    def test_one_and_two_observed_compton_plus_photoelectric(self):
        for count in (1, 2):
            e = fixture(); e['tables']['tracks'][2]['procid'] = 2
            if count == 2:
                e['tables']['tracks'].append(track(4, 2, 11, 2, .1, time=12, x=.002))
                e['tables']['stp/germanium'].append(step(2, 1, 22, 0, 2, time=12, x=.002))
            e['tables']['tracks'].append(track(5, 2, 11, 3, .1, time=13, x=.003))
            e['tables']['stp/germanium'].append(step(2, 1, 22, 0, 3, time=13, x=.003))
            self.assertIn('compton'+str(count), first(e)['categories'])
            # A site with no recorded Ge vertex must not be called a Ge Compton candidate.
            e['tables']['tracks'][2]['xloc'] = .1
            self.assertNotIn('compton'+str(count), first(e)['categories'])

    def test_ionization_secondary_not_compton(self):
        e = fixture(); e['tables']['tracks'].append(track(4, 3, 11, 4, .1, time=11))
        self.assertEqual(first(e)['observed_compton_site_count'], 0)

    def test_diameter_and_compact_boundary(self):
        e = fixture(); e['tables']['stp/germanium'][1]['edep'] = 250
        e['tables']['stp/germanium'].append(step(3, 2, 11, 250, 2, x=.001))
        self.assertIn('compact', first(e)['categories']); self.assertEqual(first(e)['deposit_diameter_mm'], 1)
        e['tables']['stp/germanium'][-1]['xloc'] = .001001
        self.assertNotIn('compact', first(e)['categories'])

    def test_recorded_nonge_loss_not_escape_invention(self):
        e = fixture(); e['tables']['stp/germanium'][1]['edep'] = 400
        self.assertIn('unresolved', first(e)['reason'])
        e['tables']['stp/passive'] = [step(3, 2, 11, 100)]
        g = first(e)
        self.assertEqual(g['categories'], ['partial']); self.assertEqual(g['root_non_ge_energy_keV'], 100)
        self.assertEqual(g['root_non_ge_rows'], [{'table': 'stp/passive', 'raw_row_index': 0}])
        e['tables']['stp/germanium'][1]['edep'] = 500
        self.assertEqual(first(e)['categories'], ['unknown'])


class SavedDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payloads, cls.manifest, cls.campaign, cls.receipts = v.analyze()

    def test_complete_selected_census(self):
        for model, expected in v.COUNTS.items():
            p = self.payloads[model]
            scene = v.read(v.SOURCE / model / 'scene.json')
            self.assertEqual(len(p['events']), expected)
            self.assertEqual(p['event_ids'], scene['event_index']['ge_hit_ids'])
            self.assertEqual(len(set(p['event_ids'])), expected)

    def test_every_selected_original_record_round_trip(self):
        for model, p in self.payloads.items():
            original = {}
            for path in (v.SOURCE / model).glob('events-*.json'):
                for event in v.read(path)['events']:
                    if event['event_id'] in p['event_ids']:
                        original[event['event_id']] = event
            encoded = gzip.compress(v.encoded(p), mtime=0)
            decoded = json.loads(gzip.decompress(encoded))
            for event in decoded['events']:
                self.assertEqual(v.unpack(event, p['columns']), original[event['event_id']])

    def test_frozen_scene_source_hashes_and_receipts(self):
        self.assertEqual(v.digest(v.SOURCE / 'manifest.json'), v.PINS['geometry_manifest'])
        self.assertEqual(v.digest(v.SAVED / 'run.json'), v.PINS['campaign_run'])
        self.assertEqual(len(self.campaign['source_sha256']), 17)
        for model in v.COUNTS:
            path = f'{model}/scene.json'
            self.assertEqual(v.digest(v.SOURCE / path), self.manifest['files'][path]['sha256'])
            self.assertEqual(v.read(v.SOURCE / path)['originals_sha256']['run.json'], self.receipts[f'{model}/transport/run.json'])

    def test_full_groups_bound_to_photons_and_original_delays(self):
        for model, p in self.payloads.items():
            events = {e['event_id']: v.unpack(e, p['columns']) for e in p['events']}
            for e in p['evidence']:
                raw = events[e['event_id']]; tracks = {t['trackid']: t for t in raw['tables']['tracks']}
                ge = {r['raw_row_index']: r for r in raw['tables']['stp/germanium']}
                for g in e['groups']:
                    self.assertEqual(g['relative_delays_ns'], [ge[i]['time']-g['origin_time_ns'] for i in g['ge_raw_row_indices']])
                    if 'full' in g['categories']:
                        self.assertEqual(len(g['source_photon_track_ids']), 1)
                        root = tracks[g['source_photon_track_ids'][0]]
                        self.assertEqual(root['ekin']*1000, g['source_photon_energy_keV'])
                        self.assertLessEqual(abs(g['ge_energy_keV']-root['ekin']*1000), v.energy_tolerance(root['ekin']*1000))

    def test_representatives_are_real_and_empty_stays_empty(self):
        for model, p in self.payloads.items():
            self.assertIsNone(p['representatives']['unknown'])
            for category, representative in p['representatives'].items():
                if representative:
                    self.assertIn(representative, p['categories'][category])
            compact = p['representatives']['compact']
            group = next(e for e in p['evidence'] if e['event_id'] == compact['event_id'])['groups'][compact['group_id']]
            self.assertGreater(group['source_photon_energy_keV'], 600)
        sap = self.payloads['SAP22']; rep = sap['representatives']['compton1']
        group = next(e for e in sap['evidence'] if e['event_id'] == rep['event_id'])['groups'][rep['group_id']]
        self.assertLess(group['source_photon_energy_keV'], 40)  # Honest low-energy candidate.


class SafetyTests(unittest.TestCase):
    def test_nooverwrite_and_path_safety(self):
        v.WORK.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='viewer-tests-', dir=v.WORK) as directory:
            base = Path(directory); existing = base/'existing.json'; existing.write_bytes(b'original')
            with self.assertRaisesRegex(ValueError, 'overwrite'):
                v.safe(existing, base, new=True)
            for path in (base, base/'..'/'escape', v.ROOT/'tools'/'escape.json'):
                with self.assertRaises(ValueError): v.safe(path, base)
            self.assertEqual(existing.read_bytes(), b'original')
            with self.assertRaises(ValueError): v.build(base/'another', base/'freeze.json')

    def test_hash_and_source_freeze_reject_changes(self):
        with tempfile.TemporaryDirectory(prefix='viewer-tests-', dir=v.WORK) as directory:
            path = Path(directory)/'viewer-freeze.json'
            v.freeze(path)
            with self.assertRaises(ValueError): v.freeze(path)
            with self.assertRaises(ValueError): v.verify(path, '0'*64)
            with patch.object(v, 'source_hashes', return_value={'changed': 'sha'}), patch.object(v, 'OUTPUT', Path(directory)/'hit-view'):
                # Before build reserves an output, the source freeze must fail.
                with self.assertRaisesRegex(ValueError, 'sources not frozen'): v.build(v.OUTPUT, path)
            self.assertFalse((Path(directory)/'hit-view').exists())

    def test_existing_bundle_if_present(self):
        if not (v.OUTPUT/'manifest.json').exists():
            self.skipTest('Bundle deliberately not generated until source freeze')
        v.validate(v.OUTPUT)
        with self.assertRaisesRegex(ValueError, 'overwrite'):
            v.build(v.OUTPUT, v.WORK/'viewer-freeze.json')


class FrontendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (v.ROOT/'tools/hit_event_view.html').read_text(encoding='utf-8')
        cls.scripts = re.findall(r'<script[^>]*>(.*?)</script>', cls.html, re.S)

    def node(self, script, *args):
        result = subprocess.run(['node', *args], input=script, text=True, capture_output=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stdout+'\n'+result.stderr)

    def test_javascript_syntax_no_dependencies(self):
        self.assertEqual(len(self.scripts), 2)
        for script in self.scripts:
            self.node(script, '--check')
        self.assertNotIn('<script src=', self.html)
        self.assertNotIn('https://cdn', self.html)

    def test_generation_gate_late_success_failure_and_clear(self):
        self.node(self.scripts[0] + r'''
const assert=require('node:assert/strict');
async function test(){let view=null,errors=[],clears=0;const gate=selectionGate(()=>{view=null;clears++;});
 let oldResolve,newResolve,oldReject;
 const old=gate.run(()=>new Promise(r=>oldResolve=r),v=>view=v,e=>errors.push(e));
 const current=gate.run(()=>new Promise(r=>newResolve=r),v=>view=v,e=>errors.push(e));
 newResolve('SAP22 selected');await current;oldResolve('AK02 stale');await old;assert.equal(view,'SAP22 selected');
 const bad=gate.run(()=>new Promise((r,j)=>oldReject=j),v=>view=v,e=>errors.push(e));
 const good=gate.run(async()=>'latest group',v=>view=v,e=>errors.push(e));await good;oldReject(Error('late'));await bad;
 assert.equal(view,'latest group');assert.deepEqual(errors,[]);
 let resolve;const pending=gate.run(()=>new Promise(r=>resolve=r),v=>view=v,e=>errors.push(e));
 gate.invalidate();resolve('cancelled');await pending;assert.equal(view,null);assert.ok(clears>=6);
 const a=gate.run(async()=>'event 1',v=>view=v,e=>errors.push(e));const b=gate.run(async()=>'event 2',v=>view=v,e=>errors.push(e));
 await Promise.all([a,b]);assert.equal(view,'event 2');
 const packed={event_id:7,tables:{tracks:[[8,11,1.2345678901234567]]}};
 assert.deepEqual(unpackEvent(packed,{tracks:['trackid','particle','time'],'stp/germanium':['edep']}),
 {event_id:7,tables:{tracks:[{trackid:8,particle:11,time:1.2345678901234567}],'stp/germanium':[]}});
}
test().catch(e=>{console.error(e);process.exitCode=1;});
''')

    def test_native_gzip_decode_and_hash_rejection(self):
        loader = re.search(r'async function fetchJSON\(.*?\n}', self.scripts[1], re.S).group()
        self.node(loader + r'''
const assert=require('node:assert/strict'),zlib=require('node:zlib'),crypto=require('node:crypto').webcrypto;
const raw=JSON.stringify({event_id:8432,time:325801375576.26227,energy:31.818831554318052});
const compressed=zlib.gzipSync(raw);globalThis.crypto=crypto;
globalThis.fetch=async()=>new Response(compressed,{status:200});
async function test(){const sha=require('node:crypto').createHash('sha256').update(compressed).digest('hex');
 assert.deepEqual(await fetchJSON('selected.json.gz',sha),JSON.parse(raw));
 await assert.rejects(fetchJSON('selected.json.gz','0'.repeat(64)),/Hash mismatch/);
}
test().catch(e=>{console.error(e);process.exitCode=1;});
''')

    def test_actual_frontend_model_event_category_race(self):
        # Run the real page scripts against a minimal DOM; control model fetch completion.
        harness = r'''
const vm=require('node:vm'),assert=require('node:assert/strict');
class Element {constructor(){this.value='';this.checked=false;this.open=false;this.children=[];this.style={};this.clientWidth=600;this.clientHeight=400;}
 append(...v){this.children.push(...v);} replaceChildren(...v){this.children=v;} setAttribute(){} addEventListener(){} setPointerCapture(){}
 getContext(){return new Proxy({},{get:()=>()=>{}});}}
const elements=new Map();function element(id){if(!elements.has(id))elements.set(id,new Element());return elements.get(id);}
element('model').value='AK02';element('category').value='all';element('overlay').checked=true;element('photons').checked=true;
const context={document:{getElementById:element,createElement:()=>new Element(),querySelectorAll:()=>[]},
 console,TextDecoder,Blob,Response,DecompressionStream,crypto:require('node:crypto').webcrypto,fetch:()=>new Promise(()=>{}),
 ResizeObserver:class{observe(){}},setTimeout};vm.createContext(context);
'''
        harness += '\nvm.runInContext('+json.dumps('\n'.join(self.scripts))+',context);\n'
        harness += r'''
async function test(){
 vm.runInContext(`
 const pending=new Map();fetchJSON=path=>new Promise((resolve,reject)=>pending.set(path,{resolve,reject}));
 manifest={models:{AK02:{scene:'A-scene',selected:'A-data',selected_count:1},SAP22:{scene:'S-scene',selected:'S-data',selected_count:1}},
 files:{'A-scene':{},'A-data':{},'S-scene':{},'S-data':{}},category_labels:{compact:'Compact',compton1:'One',compton2:'Two',partial:'Partial'}};
 function fixture(model,id){const group={group_id:0,ge_raw_row_indices:[],categories:['partial'],source_photon_track_ids:[2],
 ge_energy_keV:1,source_photon_energy_keV:2,origin_time_ns:0,relative_delays_ns:[0],deposit_diameter_mm:0,observed_compton_site_count:0,reason:'test'};
 return {schema_version:1,model,event_ids:[id],columns:{tracks:[], 'stp/germanium':[]},events:[{event_id:id,tables:{}}],
 evidence:[{event_id:id,groups:[group],relevant_photon_track_ids:[],graph_errors:[],ge_step_count:0}],
 categories:{compact:[],compton1:[],compton2:[],partial:[{event_id:id,group_id:0}]},representatives:{compact:null,compton1:null,compton2:null,partial:{event_id:id,group_id:0}}};}
 const mesh=model=>({model,volumes:[{name:'germanium',vertices_global_mm:[[0,0,0],[1,1,1]],triangles:[],wireframe:[]}],source_position_global_mm:[0,3,0]});
 globalThis.oldModel=selectModel('AK02');globalThis.newModel=selectModel('SAP22');
 $('category').value='partial';filterCategory(); // A category click during loading must not cancel the model.
 pending.get('S-scene').resolve(mesh('SAP22'));pending.get('S-data').resolve(fixture('SAP22',8413));
 `,context);
 await context.newModel;await new Promise(r=>setTimeout(r,0));
 assert.equal(vm.runInContext('selected.event_id',context),8413);
 vm.runInContext(`pending.get('A-scene').resolve(mesh('AK02'));pending.get('A-data').resolve(fixture('AK02',8432));`,context);
 await context.oldModel;assert.equal(vm.runInContext('selected.event_id',context),8413);assert.equal(vm.runInContext('scene.model',context),'SAP22');
 element('rawPanel').open=true;vm.runInContext('refreshDetails()',context);assert.ok(element('raw').textContent.includes('8413'));
 vm.runInContext(`globalThis.pendingEvent=selectEvent(8413);$('category').value='compact';filterCategory();`,context);
 await context.pendingEvent;assert.equal(vm.runInContext('selected',context),null);assert.equal(element('raw').textContent,'');
 assert.ok(element('status').textContent.includes('zero'));assert.equal(vm.runInContext('events.size',context),1);
 element('category').value='all';vm.runInContext('filterCategory()',context);await new Promise(r=>setTimeout(r,0));
 assert.equal(vm.runInContext('selected.event_id',context),8413);assert.ok(element('raw').textContent.includes('8413'));
}
test().catch(e=>{console.error(e);process.exitCode=1;});
'''
        self.node(harness)


if __name__ == '__main__':
    unittest.main(verbosity=2)
