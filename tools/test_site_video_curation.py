"""Guarded public-video curation using small, explicitly synthetic stage files."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import site_video_curation as V


class VideoCurationTests(unittest.TestCase):
    def setUp(self):
        parent = Path(V.__file__).resolve().parents[1] / '.local'
        self.temp = tempfile.TemporaryDirectory(dir=parent, prefix='video-curation-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.stage = self.root / '.local/site-build'
        self.stage.mkdir(parents=True)
        self.patch = patch.object(V, 'ROOT', self.root); self.patch.start(); self.addCleanup(self.patch.stop)
        self.put('models/catalog.json', json.dumps({'detectors': [{'id': model} for model in V.MODELS]}))
        for model in V.MODELS:
            base = f'detectors/{model}/runs/{V.RUN}/presentation/'
            for name in V.ALL:
                data = ('synthetic saved clip ' + model + '/' + name).encode()
                self.put(base + name, data)
                original = self.root / 'Additional_Simulations/Visualization_3D' / (base + name)
                original.parent.mkdir(parents=True, exist_ok=True); original.write_bytes(data)
            cards = ''
            for stem in V.STEMS:
                cards += ('<section id="card-' + stem + '"><h3>' + stem + '</h3>'
                    '<video id="video-' + stem + '" controls poster="preview.png">'
                    '<source src="runs/' + V.RUN + '/presentation/' + stem + '.webm" type="video/webm">'
                    '<source src="runs/' + V.RUN + '/presentation/' + stem + '.mp4" type="video/mp4"></video>'
                    '<a name="download-' + stem + '" href="runs/' + V.RUN + '/presentation/' + stem + '.mp4">MP4</a></section>')
            self.put(f'detectors/{model}/gallery.html', '<html><body><section id="science"><img src="preview.png">'
                '<a href="channels.csv">Signed channels</a></section>' + cards + '</body></html>')
            self.put(f'detectors/{model}/channels.csv', b'time_ns,charge_fC\n0,-1.2345678901234567\n')

    def put(self, relative, data):
        path = self.stage / relative; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data.encode() if isinstance(data, str) else data)
        return path

    def snapshot(self):
        return {path.relative_to(self.stage).as_posix(): path.read_bytes()
                for path in self.stage.rglob('*') if path.is_file()}

    def test_two_mp4_clips_per_model_preserve_originals_data_and_anchors(self):
        before = self.snapshot()
        originals = {path: path.read_bytes() for path in
                     (self.root / 'Additional_Simulations').rglob('*') if path.is_file()}
        result = V.apply(self.stage)
        self.assertEqual(len(result['removed']), 102)
        self.assertEqual(len(result['retained']), 34)
        self.assertEqual(V.validate(self.stage)['retained'], result['retained'])
        self.assertEqual(result['removed_bytes'], sum(len(before[row['path']]) for row in result['removed']))
        for model in V.MODELS:
            rel = f'detectors/{model}/gallery.html'; text = (self.stage / rel).read_text()
            self.assertEqual(text.count('<video'), 2); self.assertNotIn('.webm', text)
            self.assertEqual(V.references(before[rel].decode()).anchors, V.references(text).anchors)
            self.assertIn('<section id="science"><img src="preview.png"><a href="channels.csv">Signed channels</a></section>', text)
            self.assertEqual((self.stage / f'detectors/{model}/channels.csv').read_bytes(),
                             before[f'detectors/{model}/channels.csv'])
        self.assertEqual(originals, {path: path.read_bytes() for path in originals})
        current = self.snapshot(); second = V.apply(self.stage)
        self.assertEqual(second['removed'], []); self.assertEqual(current, self.snapshot())

    def test_unlisted_movie_or_external_reference_fails_before_writes(self):
        extra = self.put(f'detectors/AK01/runs/{V.RUN}/presentation/unknown.mp4', b'unknown')
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'movie inventory'): V.apply(self.stage)
        self.assertEqual(before, self.snapshot()); extra.unlink()
        self.put('other.html', '<a href="detectors/AK01/runs/' + V.RUN + '/presentation/04_three_sites.mp4">Old movie</a>')
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'still references'): V.apply(self.stage)
        self.assertEqual(before, self.snapshot())

    def test_changed_local_original_and_wrong_stage_are_refused(self):
        original = self.root / f'Additional_Simulations/Visualization_3D/detectors/AK01/runs/{V.RUN}/presentation/02_charge_cloud.mp4'
        original.write_bytes(b'changed original'); before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'original differs'): V.apply(self.stage)
        self.assertEqual(before, self.snapshot())
        with self.assertRaisesRegex(ValueError, 'generated .local/site-build'): V.apply(self.root / 'docs')

    def test_reparse_candidate_is_refused_before_writes(self):
        target = self.stage / f'detectors/AK01/runs/{V.RUN}/presentation/04_three_sites.webm'
        original = Path.lstat; before = self.snapshot()
        def marked(path, *args, **kwargs):
            value = original(path, *args, **kwargs)
            return SimpleNamespace(st_mode=value.st_mode, st_file_attributes=0x400) if path == target else value
        with patch.object(Path, 'lstat', marked):
            with self.assertRaisesRegex(ValueError, 'Reparse point'): V.apply(self.stage)
        self.assertEqual(before, self.snapshot())


if __name__ == '__main__':
    unittest.main(verbosity=2)
