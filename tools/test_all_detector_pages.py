"""Geometry/catalog/workspace regressions; no radiation or field calculations."""
import copy
import json
import tempfile
import os
import subprocess
import unittest
from pathlib import Path
import geometry_catalog as G
import ssd_geometry_publication as P
import build_local_dashboard as W
from site_fragments import remove_sections, ids, prepend_main
ROOT=Path(__file__).resolve().parents[1]
EXPORT=ROOT/'.local/all-detector-pages-v1/scenes-v3'

class AllDetectorTests(unittest.TestCase):
    def assets(self):
        if (EXPORT/'export.json').is_file():
            return {r['model']:EXPORT/r['model']/r['asset_id'] for r in P.read(EXPORT/'export.json')['models']}
        result={}
        for model in G.catalog():
            active=ROOT/'docs/detectors'/model/'geometry-active.json'
            if active.is_file():
                result[model]=active.parent/'geometry'/P.read(active)['asset_id']
        return result
    def test_complete_model_contact_coverage(self):
        assets=self.assets()
        self.assertEqual(set(assets),set(G.catalog()))
        self.assertEqual(len(assets),17)
        contacts=0
        for model,path in assets.items():
            manifest,scene=P.validate_asset(path,model)
            self.assertEqual(len(scene['layers']),len(G.catalog()[model]['contacts'])+1)
            contacts+=len(scene['layers'])-1
        self.assertEqual(contacts,66)
    def test_saved_mesh_vertices_and_faces_are_exact(self):
        try:
            import export_ssd_geometry as E
        except ImportError:
            self.skipTest('Original-mesh comparison requires the maintainer VTK environment')
        for model,path in self.assets().items():
            scene=P.read(path/'scene.json')
            source=ROOT/'Additional_Simulations/Visualization_3D/detectors'/model/'runs'/E.RUN
            if not source.is_dir():
                self.skipTest('Original saved meshes are local maintainer evidence')
            for layer in scene['layers']:
                points,faces=E.read_poly(source/layer['source']['file'])
                self.assertEqual(points,layer['vertices_mm'])
                self.assertEqual(faces,layer['faces'])
    def test_invalid_layer_content_is_rejected(self):
        path=self.assets()['GeGI_3D']
        manifest,scene=P.validate_asset(path,'GeGI_3D')
        mutations=[]
        changed=copy.deepcopy(scene);changed['layers'].pop();mutations.append(changed)
        changed=copy.deepcopy(scene);changed['layers'][1]['contact']['potential_V']+=1;mutations.append(changed)
        changed=copy.deepcopy(scene);changed['layers'][1]['contact']=copy.deepcopy(changed['layers'][2]['contact']);mutations.append(changed)
        changed=copy.deepcopy(scene);changed['layers'][1]['style']['opacity']=2;mutations.append(changed)
        changed=copy.deepcopy(scene);changed['layers'][0]['faces'][0][0]=-1;mutations.append(changed)
        changed=copy.deepcopy(scene);changed['layers'][0]['vertices_mm'][0][0]=float('nan');mutations.append(changed)
        for changed in mutations:
            with self.assertRaises(ValueError):G.validate_layers(changed,manifest)
    def test_historical_two_model_assets_still_validate(self):
        base=ROOT/'.local/ssd-geometry-v1'
        if not (base/'export.json').is_file():
            self.skipTest('Historical maintainer export unavailable')
        for row in P.read(base/'export.json')['models']:
            P.validate_asset(base/row['model']/row['asset_id'],row['model'])
    def test_balanced_managed_section_removal(self):
        text='<main class="wrap"><section class="panel" id="managed"><section><p>nested</p></section></section><section id=\'managed\'>again</section><p id="keep">ok</p></main>'
        result=remove_sections(text,{'managed'})
        self.assertEqual(result,'<main class="wrap"><p id="keep">ok</p></main>')
        self.assertEqual(ids(result),['keep'])
        self.assertEqual(remove_sections(result,{'managed'}),result)
        self.assertIn('<main class="wrap"><p>new</p>',prepend_main(result,'<p>new</p>'))
    def test_capabilities_do_not_enable_unintegrated_models(self):
        cap=P.read(ROOT/'scenarios/detector-capabilities.json')
        self.assertEqual({r['model_id'] for r in cap['detectors']},set(G.catalog()))
        enabled={r['model_id'] for r in cap['detectors'] if r['lbnl_execution_implemented']}
        self.assertEqual(enabled,set(P.read(ROOT/'scenarios/lbnl-cs137.json')['detectors']))
        self.assertEqual(enabled,{'AK02','SAP22'})
        for row in cap['detectors']:
            self.assertEqual(row['model_sha256'],G.catalog()[row['model_id']]['model_sha256'])
            self.assertEqual(row['positive_uninstrumented_launcher'],'not_validated')
    def test_workspace_is_repeatable_and_preserves_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);science=root/'.local/cs137-1m';science.mkdir(parents=True)
            data=science/'unchanged.bin';data.write_bytes(b'protected scientific bytes')
            before=(data.read_bytes(),data.stat().st_mtime_ns)
            first=W.build(root)
            index=root/'.local/workspace/index.html';saved=index.read_bytes()
            second=W.build(root)
            self.assertEqual(first,second)
            self.assertEqual(saved,index.read_bytes())
            self.assertEqual(before,(data.read_bytes(),data.stat().st_mtime_ns))
            self.assertEqual(first['files_moved'],0)
            self.assertEqual(first['files_deleted'],0)
            self.assertNotIn(str(root),index.read_text(encoding='utf-8'))
    def test_viewer_has_static_key_and_arbitrary_contact_selection(self):
        row=P.read(EXPORT/'export.json')['models'][0] if (EXPORT/'export.json').is_file() else None
        asset=row['asset_id'] if row else '0'*64
        html=P.viewer_html('GeGI_3D',asset)
        self.assertIn('Static contact key',html)
        self.assertIn('data-readout="9"',html)
        self.assertIn('Isolate selected contact',html)
        self.assertIn('X_guard',html)
        self.assertIn('Y_guard',html)
        self.assertNotIn('__CONTACT_KEY__',html)

    def test_script_entries_are_not_actionable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);local=root/'.local';local.mkdir()
            (local/'example.cmd').write_text('echo not executed')
            W.build(root)
            html=(local/'workspace/index.html').read_text(encoding='utf-8')
            self.assertIn('example.cmd (non-actionable file)',html)
            self.assertNotIn('href="../example.cmd"',html)
    @unittest.skipUnless(os.name=='nt','Windows junction regression')
    def test_windows_junction_output_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);root=base/'project';outside=base/'outside'
            (root/'.local').mkdir(parents=True);outside.mkdir()
            junction=root/'.local/workspace'
            result=subprocess.run(['cmd','/c','mklink','/J',str(junction),str(outside)],capture_output=True)
            if result.returncode:
                self.skipTest('Junction creation unavailable')
            try:
                with self.assertRaises(ValueError):W.build(root)
                self.assertEqual(list(outside.iterdir()),[])
            finally:
                os.rmdir(junction)

if __name__=='__main__':
    unittest.main(verbosity=2)
