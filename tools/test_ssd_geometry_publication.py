import tempfile,unittest
from pathlib import Path
import ssd_geometry_publication as P
class GeometryPublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.site=Path(self.tmp.name)
        for m in P.MODELS:
            d=self.site/'detectors'/m; (d/'runs/20260922_suite_v3').mkdir(parents=True)
            (d/'index.html').write_text('<html><main><h1>'+m+'</h1></main></html>',encoding='utf-8')
            (d/'runs/20260922_suite_v3/01_geometry.png').write_bytes(b'poster')
        self.source=P.ROOT/'.local/ssd-geometry-v1'
    def test_publish_and_validate(self):
        rows=P.assemble(self.source,self.site); checked=P.validate_site(self.site)
        self.assertEqual(set(rows),set(P.MODELS));self.assertEqual(checked,{m:rows[m]['asset_id'] for m in P.MODELS})
        for m in P.MODELS:
            page=(self.site/'detectors'/m/'index.html').read_text()
            viewer=(self.site/'detectors'/m/'geometry.html').read_text()
            active=P.read(self.site/'detectors'/m/'geometry-active.json')
            scene=P.read(self.site/'detectors'/m/'geometry'/active['asset_id']/'scene.json')
            self.assertEqual(P.canonical_scene_id(scene),active['asset_id'])
            self.assertEqual(page.count('id="ssd-interactive-geometry"'),1)
            self.assertIn('Enable drag rotation',viewer);self.assertIn('target="_top"',viewer);self.assertNotIn('__MODEL__',viewer)
    def test_scene_mutation_is_rejected(self):
        P.assemble(self.source,self.site)
        m='AK02';root=self.site/'detectors'/m/'geometry';asset=next(root.iterdir())
        scene=asset/'scene.json';scene.write_bytes(scene.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError,'scene hash'):P.validate_site(self.site)
    def test_repeat_publication_reuses_content_addressed_assets(self):
        first=P.assemble(self.source,self.site); second=P.assemble(self.source,self.site)
        self.assertEqual(first,second); self.assertEqual(P.validate_site(self.site),{m:first[m]['asset_id'] for m in P.MODELS})
        for m in P.MODELS:self.assertEqual(len([p for p in (self.site/'detectors'/m/'geometry').iterdir() if p.is_dir()]),1)
if __name__=='__main__':unittest.main(verbosity=2)
