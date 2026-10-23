"""Bounded synthetic losslessness and source-authority checks; no physics."""
import gzip
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import geometry_web_delivery as D


class GeometryDelivery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory(
            dir=Path(__file__).resolve().parents[1] / '.local', prefix='geometry-delivery-')
        cls.root = Path(cls.scratch.name)
        cls.source = cls.root / 'source'
        cls.source.mkdir()
        source = {'schema_version': 1, 'status': 'complete', 'models': {}, 'files': {}}

        def save(name, body):
            path = cls.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
            source['files'][name] = D.stamp(body)

        for model in D.MODELS:
            chunks = []
            ge_row = 0
            for first in range(0, 10000, 100):
                events = []
                for eid in range(first, first + 100):
                    base = {'evtid': eid, 'raw_row_index': eid}
                    ge = []
                    if eid in (13, 9999):
                        ge = [dict(base, raw_row_index=ge_row, trackid=1,
                                   parent_trackid=0, particle=22,
                                   edep=1.0000000000000002)]
                        ge_row += 1
                    event = {'event_id': eid, 'negative_zero': 0,
                             'tiny': 1e-300, 'tables': {
                                 'vtx': [dict(base)], 'particles': [dict(base)],
                                 'tracks': [dict(base, trackid=1, parent_trackid=0, particle=22)],
                                 'stp/germanium': ge}}
                    # Arbitrary saved flags/nulls must also survive byte-for-byte;
                    # these are fixture markers, not real detector failures.
                    if eid == 13:
                        event['saved_marker'] = {'status': 'failed', 'charge': None}
                    events.append(event)
                name = model + f'/events-{first:05d}.json'
                body = D.encoded({'model': model, 'first': first, 'events': events})
                body = body.replace(b'"negative_zero":0', b'"negative_zero":-0')
                save(name, body)
                chunks.append({'file': name.split('/')[1], 'first': first, 'count': 100,
                               'sha256': D.stamp(body)['sha256']})
            rows = {'vtx': 10000, 'particles': 10000, 'tracks': 10000, 'stp/germanium': 2}
            raw_hash = ('a' if model == 'AK02' else 'b') * 64
            scene = {'model': model, 'raw_lh5_sha256': raw_hash, 'negative_zero': -0.0,
                     'event_index': {'event_count': 10000, 'chunks': chunks,
                                     'ge_hit_ids': [13, 9999], 'zero_ge_primaries': 9998,
                                     'raw_rows': rows}}
            save(model + '/scene.json', D.encoded(scene))
            save(model + '/originals.zip', b'original fixture input bytes')
            source['models'][model] = {'scene': model + '/scene.json',
                                      'originals': model + '/originals.zip',
                                      'event_count': 10000, 'raw_rows': rows,
                                      'raw_lh5_sha256': raw_hash, 'ge_hit_count': 2}
        save('geometry.html', b'<!doctype html><title>Original fixed renderer</title>')
        save('README.txt', b'Original provenance\n')
        raw = D.encoded(source)
        (cls.source / 'manifest.json').write_bytes(raw)
        cls.original = source
        cls.pin = patch.object(D, 'SOURCE_MANIFEST_SHA256', D.stamp(raw)['sha256'])
        cls.pin.start()
        cls.output = cls.root / 'delivery'
        # Test this adapter independently of synthetic mesh construction. The
        # production operation must call the unchanged full original validator.
        with patch.object(D.original, 'validate_bundle', return_value=source) as check:
            cls.receipt = D.assemble(cls.source, cls.output)
            check.assert_called_once_with(cls.source)

    @classmethod
    def tearDownClass(cls):
        cls.pin.stop()
        cls.scratch.cleanup()

    def working_copy(self, name):
        target = self.root / name
        shutil.copytree(self.output, target)
        return target

    def rehash(self, folder, name):
        manifest = json.loads((folder / 'manifest.json').read_bytes())
        manifest['files'][name] = D.stamp((folder / name).read_bytes())
        (folder / 'manifest.json').write_bytes(D.encoded(manifest))

    def test_complete_byte_preservation_and_census(self):
        manifest = D.validate(self.output)
        self.assertEqual(manifest['models'], self.original['models'])
        self.assertEqual((self.output / 'original-manifest.json').read_bytes(),
                         (self.source / 'manifest.json').read_bytes())
        chunks = 0
        for name in self.original['files']:
            target = self.output / D.delivery_name(name)
            delivered = gzip.decompress(target.read_bytes()) if target.suffix == '.gz' else target.read_bytes()
            self.assertEqual(delivered, (self.source / name).read_bytes(), name)
            chunks += bool(D.CHUNK.fullmatch(name))
        self.assertEqual(chunks, 200)
        raw = gzip.decompress((self.output / 'AK02/events-00000.json.gz').read_bytes())
        self.assertIn(b'"negative_zero":-0', raw)
        events = json.loads(raw)['events']
        self.assertEqual(events[0]['event_id'], 0)
        self.assertEqual(events[0]['tables']['stp/germanium'], [])
        self.assertEqual(events[13]['saved_marker'], {'status': 'failed', 'charge': None})

    def test_deterministic_generation_and_unchanged_source(self):
        before = {p.relative_to(self.source).as_posix(): D.stamp(p.read_bytes())
                  for p in self.source.rglob('*') if p.is_file()}
        second = self.root / 'second'
        with patch.object(D.original, 'validate_bundle', return_value=self.original):
            self.assertEqual(D.assemble(self.source, second), self.receipt)
        for name in D.inventory(self.output):
            self.assertEqual((self.output / name).read_bytes(), (second / name).read_bytes())
        self.assertEqual(before, {p.relative_to(self.source).as_posix(): D.stamp(p.read_bytes())
                                  for p in self.source.rglob('*') if p.is_file()})

    def test_rehashed_wrong_decompressed_content_is_rejected(self):
        folder = self.working_copy('wrong-event')
        name = 'AK02/events-00000.json.gz'
        data = gzip.decompress((folder / name).read_bytes()).replace(b'"event_id":0,', b'"event_id":1,', 1)
        (folder / name).write_bytes(gzip.compress(data, mtime=0))
        self.rehash(folder, name)
        with self.assertRaisesRegex(ValueError, 'Decompressed original differs'):
            D.validate(folder)

    def test_rehashed_truncated_or_oversize_chunk_is_rejected(self):
        for suffix, transform in [('truncated', lambda b: b[:-1]),
                                  ('oversize', lambda b: b + b'\n' * 1000000)]:
            folder = self.working_copy(suffix)
            name = 'SAP22/events-09900.json.gz'
            body = gzip.decompress((folder / name).read_bytes())
            (folder / name).write_bytes(gzip.compress(transform(body), mtime=0))
            self.rehash(folder, name)
            with self.assertRaisesRegex(ValueError, 'Decompressed original differs'):
                D.validate(folder)

    def test_rehashed_scene_or_source_manifest_is_not_authority(self):
        folder = self.working_copy('changed-scene')
        name = 'SAP22/scene.json'
        (folder / name).write_bytes((folder / name).read_bytes() + b'\n')
        self.rehash(folder, name)
        with self.assertRaisesRegex(ValueError, 'Original geometry asset changed'):
            D.validate(folder)
        folder = self.working_copy('changed-source')
        name = 'original-manifest.json'
        (folder / name).write_bytes((folder / name).read_bytes() + b'\n')
        self.rehash(folder, name)
        with self.assertRaisesRegex(ValueError, 'Unknown original geometry manifest'):
            D.validate(folder)

    def test_extra_raw_chunk_missing_file_and_changed_redirect_are_rejected(self):
        folder = self.working_copy('extra-raw')
        (folder / 'AK02/events-00000.json').write_bytes(b'{}')
        with self.assertRaisesRegex(ValueError, 'file inventory'):
            D.validate(folder)
        folder = self.working_copy('missing-chunk')
        (folder / 'AK02/events-00000.json.gz').unlink()
        with self.assertRaisesRegex(ValueError, 'file inventory'):
            D.validate(folder)
        folder = self.working_copy('changed-redirect')
        (folder / 'geometry.html').write_bytes(b'<script>fetch("events-00000.json")</script>')
        self.rehash(folder, 'geometry.html')
        with self.assertRaisesRegex(ValueError, 'redirect changed'):
            D.validate(folder)

    def test_source_gate_and_no_overwrite(self):
        with patch.object(D.original, 'validate_bundle', side_effect=ValueError('original invalid')):
            target = self.root / 'invalid-source'
            with self.assertRaisesRegex(ValueError, 'original invalid'):
                D.assemble(self.source, target)
            self.assertFalse(target.exists())
        with patch.object(D.original, 'validate_bundle') as check:
            with self.assertRaisesRegex(ValueError, 'Do not overwrite'):
                D.assemble(self.source, self.output)
            check.assert_not_called()

    def test_failure_keeps_partial_evidence_without_terminal_receipt(self):
        changed = self.root / 'source-changed'
        shutil.copytree(self.source, changed)
        (changed / 'AK02/events-00000.json').write_bytes(b'changed after original check')
        target = self.root / 'failed-output'
        with patch.object(D.original, 'validate_bundle', return_value=self.original):
            with self.assertRaisesRegex(ValueError, 'Original changed during compression'):
                D.assemble(changed, target)
        self.assertTrue(target.is_dir())
        self.assertTrue((target / 'AK02/events-00000.json.gz').is_file())
        self.assertFalse((target / 'manifest.json').exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
