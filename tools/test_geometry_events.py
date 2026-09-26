"""Fixture tests; --bundle additionally compares EVERY exported row to raw LH5.

Full check: transport/run.sh python -B tools/test_geometry_events.py --bundle
"""
from collections import Counter
import copy
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

import geometry_events as ge

BUNDLE = '--bundle' in sys.argv
if BUNDLE:
    sys.argv.remove('--bundle')


def fixture_scene():
    # Deliberately synthetic TEST-only tetrahedra, never an exported scene.
    report = ge.read(ge.SAVED/'AK02/transport/geometry-report.json')
    meta = ge.read(ge.SAVED/'AK02/transport/prepared.json')
    volumes = copy.deepcopy(report['volumes'])
    paths = [v['original_path'] for v in volumes]
    for i, v in enumerate(volumes):
        v.update(parent=-1 if not i else paths.index(v['original_path'].rsplit('/', 1)[0]),
                 vertices_global_mm=[[0, 0, 0], [1, 0, 0], [0, 1, 0]],
                 triangles=[[0, 1, 2]], wireframe=[[0, 1], [1, 2], [2, 0]])
    return {'generator': 'G4GDMLParser/G4Polyhedron', 'units': 'mm',
            'geant4_version_number': 1132, 'volumes': volumes}, report, meta


def fixture_event(eid=0, index=0):
    identity = {'evtid': eid, 'raw_row_index': index}
    track = {**identity, 'trackid': 1, 'parent_trackid': 0, 'particle': 22}
    return {'event_id': eid, 'tables': {'vtx': [identity.copy()], 'particles': [identity.copy()],
            'tracks': [track.copy()], 'stp/germanium': [{**track, 'edep': .12345678901234567}]}}


class Guards(unittest.TestCase):
    def test_geometry_and_material_report(self):
        ge.validate_scene(*fixture_scene())

    def test_scene_rejects_mutations(self):
        mutations = [lambda s: s.update(geant4_version_number=1131),
                     lambda s: s['volumes'][2].update(material='G4_Ge'),
                     lambda s: s['volumes'][2]['translation_global_mm'].__setitem__(1, 900),
                     lambda s: s['volumes'][2].update(parent=19),
                     lambda s: s['volumes'][2].update(parent=1),
                     lambda s: s['volumes'][2]['vertices_global_mm'][0].__setitem__(0, float('nan')),
                     lambda s: s['volumes'][2]['vertices_global_mm'][0].__setitem__(0, float('inf')),
                     lambda s: s['volumes'][2]['vertices_global_mm'][0].__setitem__(0, 'bad'),
                     lambda s: s['volumes'][2]['triangles'][0].__setitem__(0, 900),
                     lambda s: s['volumes'].pop(),
                     lambda s: s['volumes'][18]['translation_global_mm'].__setitem__(1, 37.5)]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                scene, report, meta = fixture_scene(); mutate(scene)
                with self.assertRaises(ValueError):
                    ge.validate_scene(scene, report, meta)

    def test_source_and_ge_transform(self):
        for model in ge.MODELS:
            _, meta, _, scenario = ge.inputs(model)
            self.assertEqual(meta['source_position_global_mm'], [0, 37.073, .29])
            self.assertEqual([row[2] for row in meta['coordinate_transform']['rotation_local_to_global']], [0, 1, 0])
            self.assertIn('curved', scenario['top_assumption'])

    def test_event_census_and_rows(self):
        offsets = Counter()
        for eid in range(10000):
            event = fixture_event(eid, eid)
            # zero-Ge is still an event; no hit selection reduces the census.
            event['tables']['stp/germanium'] = []
            ge.validate_event(event, eid, offsets)
        self.assertEqual(offsets['vtx'], 10000)
        self.assertEqual(offsets['stp/germanium'], 0)

    def test_event_mutations(self):
        mutations = [lambda e: e.update(event_id=1),
                     lambda e: e['tables']['vtx'].clear(),
                     lambda e: e['tables']['tracks'][0].update(raw_row_index=1),
                     lambda e: e['tables']['tracks'][0].update(evtid=1),
                     lambda e: e['tables']['stp/germanium'][0].update(particle=11),
                     lambda e: e['tables']['tracks'][0].update(parent_trackid=99),
                     lambda e: e['tables']['stp/germanium'][0].update(xloc_pre=float('nan'))]
        for mutate in mutations:
            event = fixture_event(); mutate(event)
            with self.assertRaises(ValueError):
                ge.validate_event(event, 0, Counter())

    def test_hash_and_no_overwrite(self):
        (ge.WORK/'logs').mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ge.WORK/'logs') as temp:
            path = Path(temp)/'test.json'
            ge.write_json(path, {'value': -.12345678901234567, 'zero': -0.0})
            ge.verified(path, ge.digest(path))
            for bad in (None, '', '0'*64):
                with self.assertRaises(ValueError):
                    ge.verified(path, bad)
            with self.assertRaises(ValueError):
                ge.verified(path.with_name('missing'), ge.digest(path))
            with self.assertRaises(FileExistsError):
                ge.write_json(path, {})
            with self.assertRaises(ValueError):
                ge.checked(path, ge.WORK, new=True)
            self.assertEqual(ge.read(path)['value'], -.12345678901234567)

    def test_path_escape(self):
        for path in (ge.ROOT/'docs/x.json', ge.WORK/'bundle/../../escape.json', ge.WORK):
            with self.assertRaises(ValueError):
                ge.checked(path, ge.WORK)

    def test_linked_parent_guard(self):
        # Exercise symlink resolution without Windows symlink-creation privilege.
        from unittest.mock import patch
        path = ge.WORK/'logs'
        resolve = Path.resolve
        def redirected(p, *args, **kwargs):
            if p == path:
                return ge.ROOT/'outside-owned-output'
            return resolve(p, *args, **kwargs)
        with patch.object(Path, 'resolve', redirected):
            with self.assertRaises(ValueError):
                ge.checked(path, ge.WORK)

    def test_dependencies_unchanged(self):
        self.assertEqual(len(ge.dependencies()['source_sha256']), 17)

    def test_flat_lh5_fixture_export(self):
        import h5py
        import numpy as np
        (ge.WORK/'logs').mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ge.WORK/'logs') as temp:
            temp = Path(temp); target = temp/'output'; target.mkdir()
            count = 100
            with h5py.File(temp/'truth.lh5', 'w') as raw:
                raw['number_of_simulated_events'] = count
                proc = raw.create_group('processes'); proc['procid'] = [1]; proc['name'] = [b'RadioactiveDecay']
                def table(name, rows):
                    group = raw.create_group(name)
                    for column in rows[0]:
                        values = [r[column] for r in rows]
                        ds = group.create_dataset(column, data=np.array(values))
                        ds.attrs['units'] = ('m' if column.startswith(('xloc', 'yloc', 'zloc')) else
                                             'ns' if column == 'time' else 'keV' if column == 'edep' else '')
                vertices, particles, tracks, steps = [], [], [], []
                for eid in range(count):
                    pos = dict(xloc=0., yloc=.037073, zloc=.00029, time=0.)
                    vertices.append(dict(evtid=eid, n_part=1, **pos))
                    particles.append(dict(evtid=eid, particle=1000551370))
                    tracks.extend([dict(evtid=eid, trackid=1, parent_trackid=0, particle=1000551370,
                                        procid=-1, ekin=0., **pos),
                                   dict(evtid=eid, trackid=2, parent_trackid=1, particle=11,
                                        procid=1, ekin=.1, **pos)])
                    if eid == 42:
                        steps.append(dict(evtid=eid, trackid=2, parent_trackid=1, particle=11,
                                          edep=.12345678901234567, **pos,
                                          **{axis+suffix: -.0 for suffix in ('_pre', '_post')
                                             for axis in ('xloc', 'yloc', 'zloc')}))
                for name, rows in [('vtx', vertices), ('particles', particles), ('tracks', tracks), ('stp/germanium', steps)]:
                    table(name, rows)
            index = ge.export_raw(temp, {'primary_count': count, 'model_id': 'fixture',
                                         'material_tables': {'stp/germanium': 'G4_Ge'}}, target)
            self.assertEqual(index['ge_hit_ids'], [42]); self.assertEqual(index['zero_ge_primaries'], 99)
            chunk = ge.read(target/'events-00000.json')
            self.assertEqual([e['event_id'] for e in chunk['events']], list(range(count)))
            row = chunk['events'][42]['tables']['stp/germanium'][0]
            self.assertEqual(row['edep'], .12345678901234567)
            self.assertEqual(np.float64(row['xloc_pre']).tobytes(), np.float64(-0.).tobytes())
            self.assertEqual(index['raw_rows']['tracks'], 200)

    def test_viewer_syntax_and_stale_load(self):
        node = shutil.which('node') or 'C:/Program Files/nodejs/node.exe'
        html = (ge.ROOT/'tools/geometry_events.html').read_text(encoding='utf-8')
        scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.S)
        check = subprocess.run([node, '--check'], input='\n'.join(scripts), text=True, capture_output=True)
        self.assertEqual(check.returncode, 0, check.stderr)
        test = scripts[0] + r'''
const assert=require('node:assert/strict');
(async()=>{
 let shown=null,errors=[],clears=0;
 const gate=selectionGate(()=>{shown=null;clears++;});
 let resolveOld,rejectOld;
 const old=gate.run(()=>new Promise(r=>resolveOld=r),v=>shown=v,e=>errors.push(e));
 const current=gate.run(()=>Promise.resolve('SAP22:next'),v=>shown=v,e=>errors.push(e));
 await current;resolveOld('AK02:old');await old;assert.equal(shown,'SAP22:next');
 const failed=gate.run(()=>new Promise((r,j)=>rejectOld=j),v=>shown=v,e=>errors.push(e));
 await gate.run(()=>Promise.resolve('AK02:8432'),v=>shown=v,e=>errors.push(e));
 rejectOld(Error('late old request'));await failed;assert.equal(shown,'AK02:8432');assert.equal(errors.length,0);
 const invalidated=gate.run(()=>new Promise(r=>resolveOld=r),v=>shown=v,e=>errors.push(e));
 gate.invalidate();resolveOld('old model');await invalidated;assert.equal(shown,null);
 await gate.run(()=>Promise.reject(Error('current failure')),v=>shown=v,e=>errors.push(e));
 assert.equal(errors.length,1);assert.ok(clears>=7);console.log('selection gate races passed');
})().catch(e=>{console.error(e);process.exitCode=1});
'''
        result = subprocess.run([node], input=test, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_viewer_event_click_during_model_load(self):
        node = shutil.which('node') or 'C:/Program Files/nodejs/node.exe'
        html = (ge.ROOT/'tools/geometry_events.html').read_text(encoding='utf-8')
        scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.S)
        # Execute the actual controller, not a duplicate selection implementation.
        test = r'''
const vm=require('node:vm'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const elements=new Map();
function element(id){if(!elements.has(id))elements.set(id,{value:id==='model'?'AK02':'0',checked:true,open:false,
 textContent:'',style:{},clientWidth:800,clientHeight:500,width:800,height:500,append(){},replaceChildren(){},removeAttribute(){},
 addEventListener(){},setPointerCapture(){},getContext(){return new Proxy({},{get:(o,k)=>o[k]||(()=>{}),set:(o,k,v)=>(o[k]=v,true)});}});return elements.get(id);}
const encoded=o=>new TextEncoder().encode(JSON.stringify(o));
const hash=o=>crypto.createHash('sha256').update(encoded(o)).digest('hex');
const chunk={model:'AK02',first:0,events:Array.from({length:100},(_,event_id)=>({event_id,tables:{'stp/germanium':[],tracks:[]}}))};
const scene={model:'AK02',volumes:[{name:'germanium',material:'G4_Ge',original_path:'/Ge',solid_type:'fixture',vertices_global_mm:[[0,0,0],[1,0,0],[0,1,0]],triangles:[[0,1,2]],wireframe:[[0,1]]}],
 source_position_global_mm:[0,37.073,.29],event_index:{event_count:10000,ge_hit_ids:[42],zero_ge_primaries:9999,chunks:[{first:0,count:100,file:'events-00000.json',sha256:hash(chunk)}]}};
const manifest={models:{AK02:{scene:'AK02/scene.json',originals:'AK02/originals.zip'}},files:{'AK02/scene.json':{sha256:hash(scene)}}};
let finishScene,chunkRequests=0;
const response=o=>({ok:true,arrayBuffer:async()=>encoded(o).buffer});
const context=vm.createContext({console,TextDecoder,crypto:crypto.webcrypto,devicePixelRatio:1,
 document:{getElementById:element,createElement:()=>element('created'+Math.random()),querySelectorAll:()=>[]},
 ResizeObserver:class{observe(){}},fetch:async path=>{
  if(path==='manifest.json')return response(manifest);
  if(path==='AK02/scene.json')return new Promise(r=>finishScene=()=>r(response(scene)));
  if(path==='AK02/events-00000.json'){chunkRequests++;return response(chunk);}throw Error(path);
 }});
const until=async predicate=>{for(let n=0;n<200;n++){if(predicate())return;await new Promise(r=>setTimeout(r,5));}throw Error('controller timeout');};
(async()=>{
 vm.runInContext(SOURCE,context);
 await until(()=>finishScene);
 element('show').onclick(); // Must not invalidate the pending model request.
 finishScene();await until(()=>chunkRequests===1);await until(()=>element('status').textContent.includes('primary 42 ·'));
 assert.equal(vm.runInContext('selected.event_id',context),42);
 assert.equal(element('eid').value,42);
 console.log('model-loading interaction passed');
})().catch(e=>{console.error(e);process.exitCode=1});
'''.replace('SOURCE', json.dumps('\n'.join(scripts)))
        result = subprocess.run([node], input=test, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)


@unittest.skipUnless(BUNDLE, 'requires completed native bundle; run with --bundle')
class FullSavedExport(unittest.TestCase):
    def test_bundle_and_every_raw_scalar(self):
        import h5py
        import numpy as np
        bundle = ge.WORK/'bundle'
        ge.validate_bundle(bundle)
        for model in ge.MODELS:
            scene = ge.read(bundle/model/'scene.json')
            offsets = Counter()
            with h5py.File(ge.SAVED/model/'transport/truth.lh5', 'r') as raw:
                for part in scene['event_index']['chunks']:
                    chunk = ge.read(bundle/model/part['file'])
                    for table in scene['event_index']['raw_rows']:
                        rows = [r for event in chunk['events'] for r in event['tables'][table]]
                        first = offsets[table]; last = first + len(rows)
                        self.assertEqual([r['raw_row_index'] for r in rows], list(range(first,last)))
                        if rows:
                            self.assertEqual(set(rows[0]), {*raw[table], 'raw_row_index'})
                        for name, ds in raw[table].items():
                            actual = np.array([r[name] for r in rows], dtype=ds.dtype)
                            # Byte comparison verifies float64, including signed zero.
                            self.assertEqual(actual.tobytes(), ds[first:last].tobytes(), (model,table,name,first))
                        offsets[table] = last
                self.assertEqual(dict(offsets), scene['event_index']['raw_rows'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
