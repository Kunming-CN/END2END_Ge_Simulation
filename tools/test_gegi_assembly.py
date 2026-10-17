"""Targeted saved-geometry export checks; no transport or field solver calls."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import gegi_assembly as G


class SavedGeGIAssembly(unittest.TestCase):
    def test_native_inspector_only_changes_confined_roots(self):
        G.source_hashes()
        source = (G.ROOT/'tools/gegi_scene.cc').read_text()
        self.assertIn('G4VERSION_NUMBER==1132', source)
        self.assertIn('O_EXCL', source)
        self.assertNotIn('G4RunManager', source)

    def test_public_paths_and_credentials_are_rejected(self):
        for value in (b'{"path":"C:/Users/private/input"}', b'/mnt/c/private', b'.local/runs/a',
                      b'ghp_'+b'a'*32):
            with self.assertRaises(ValueError):
                G.public(value)
        self.assertEqual(G.public(b'{"length_mm":8.1,"source":"geometry.gdml"}'),
                         b'{"length_mm":8.1,"source":"geometry.gdml"}')

    def test_native_section_is_interpolated_in_millimetres(self):
        volume = {'vertices_global_mm': [[0, -2, 0], [4, 2, 0], [0, 2, 4]], 'triangles': [[0, 1, 2]]}
        section = G.section_y0(volume)
        self.assertEqual(len(section), 1)
        self.assertEqual({tuple(v) for v in section[0]}, {(2., 0., 0.), (0., 0., 2.)})

    def test_half_line_clips_plane_endpoint_without_positive_side_rays(self):
        for a, b in (([0, 0, 0], [0, 10, 0]), ([0, 10, 0], [0, 0, 0]),
                     ([0, -2, 0], [4, 2, 0])):
            clipped = G.clip_half_line(a, b)
            self.assertTrue(all(p[1] <= 0 for p in clipped))
        self.assertIsNone(G.clip_half_line([0, 1e-12, 0], [0, 10, 0]))
        self.assertEqual(G.clip_half_line([0, -2, 0], [4, 2, 0]), ([0, -2, 0], [2., 0., 0.]))

    def test_output_path_must_stay_inside_its_derivative_root(self):
        G.WORK.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=G.WORK) as temp:
            base = Path(temp)
            self.assertEqual(G.checked(base/'assembly', base, new=True), base/'assembly')
            for path in (base, base/'..'/'escape'):
                with self.assertRaises(ValueError):
                    G.checked(path, base)

    @unittest.skipUnless(G.NATIVE.is_file(), 'Saved native GeGI scene is local-only')
    def test_actual_native_scene_and_physical_change_rejection(self):
        p, report, _, _ = G.inputs()
        native = G.read(G.NATIVE)
        G.validate_scene(native, report, p)
        for field, value in (('translation_global_mm', [0, 1.45, .29]),
                             ('material', 'G4_Al'), ('parent', 0)):
            changed = copy.deepcopy(native)
            ge = next(v for v in changed['volumes'] if v['name'] == 'germanium')
            ge[field] = value
            with self.assertRaises(ValueError):
                G.validate_scene(changed, report, p)
        changed = copy.deepcopy(native)
        changed['volumes'].pop()
        with self.assertRaises(ValueError):
            G.validate_scene(changed, report, p)

    @unittest.skipUnless((G.BUNDLE/'manifest.json').is_file(), 'Saved GeGI assembly bundle is local-only')
    def test_checked_bundle_and_copied_byte_tampering(self):
        manifest = G.validate_bundle()
        self.assertEqual(manifest['assembly_volume_count'], 8)
        with tempfile.TemporaryDirectory(dir=G.WORK) as temp:
            site = Path(temp)
            G.publish(site)
            page = site/'assemblies/gegi/scene.json'
            page.write_bytes(page.read_bytes()+b' ')
            with self.assertRaises(ValueError):
                G.validate_bundle(page.parent)

    @unittest.skipUnless((G.BUNDLE/'manifest.json').is_file(), 'Saved GeGI assembly bundle is local-only')
    def test_clean_clone_reuses_public_bundle_without_private_geometry(self):
        with tempfile.TemporaryDirectory(dir=G.WORK) as temp:
            site = Path(temp)
            expected = G.publish(site)
            target = site/'assemblies/gegi'
            before = {p.name: p.read_bytes() for p in target.iterdir() if p.is_file()}
            with mock.patch.object(G, 'BUNDLE', site/'missing-private-bundle'), \
                 mock.patch.object(G, 'saved_native', side_effect=AssertionError('Private native read')), \
                 mock.patch.object(G, 'inputs', side_effect=AssertionError('Private geometry read')):
                self.assertEqual(G.publish(site), expected)
                self.assertEqual(before, {p.name: p.read_bytes() for p in target.iterdir() if p.is_file()})
                with self.assertRaises(FileNotFoundError):
                    G.publish(site, bundle=site/'explicit-missing-bundle')


if __name__ == '__main__':
    unittest.main()
