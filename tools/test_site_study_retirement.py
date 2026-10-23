"""Exact-inventory retirement, preserving compatibility anchors and local originals."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import site_study_retirement as R
import site_video_curation as V


class StudyRetirementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(R.__file__).resolve().parents[1] / '.local',
                                                prefix='study-retirement-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.stage = self.root / '.local/site-build'
        self.stage.mkdir(parents=True)
        patcher = patch.object(V, 'ROOT', self.root); patcher.start(); self.addCleanup(patcher.stop)
        inventory = {}
        for relative in R.INVENTORY:
            data = ('synthetic former public fixture ' + relative).encode()
            inventory[relative] = (len(data), hashlib.sha256(data).hexdigest())
            path = self.stage / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
        patcher = patch.object(R, 'INVENTORY', inventory); patcher.start(); self.addCleanup(patcher.stop)
        self.other = self.stage / 'examples/keep.csv'; self.other.write_bytes(b'signed science,-12.345678901234567\n')

    def snapshot(self):
        return {path.relative_to(self.stage).as_posix(): path.read_bytes()
                for path in self.stage.rglob('*') if path.is_file()}

    def test_exact_payloads_retire_to_three_small_stubs_and_one_receipt(self):
        before = self.other.read_bytes(); result = R.apply(self.stage)
        self.assertEqual(result, R.validate(self.stage))
        self.assertEqual(len(result['former_public_files']), 12)
        self.assertEqual(len(result['entry_pages']), 3)
        for entry, values in R.STUDIES.items():
            page = (self.stage / entry).read_text()
            self.assertIn('data-retired-study=', page)
            self.assertIn('separate dataset', page)
            for anchor in values[3]: self.assertIn('id="' + anchor + '"', page)
            self.assertLess(len(page), 6000)
            self.assertTrue(R.is_retired(self.stage, entry))
        self.assertEqual(self.other.read_bytes(), before)
        first = self.snapshot(); R.apply(self.stage)
        self.assertEqual(first, self.snapshot())

    def test_modified_or_unlisted_payload_fails_before_writes(self):
        path = self.stage / 'examples/data.json'; data = path.read_bytes(); path.write_bytes(data + b'changed')
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'Unapproved former'): R.apply(self.stage)
        self.assertEqual(before, self.snapshot()); path.write_bytes(data)
        (self.stage / 'examples/gegi/unknown.json').write_bytes(b'unlisted evidence')
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'Unexpected former'): R.apply(self.stage)
        self.assertEqual(before, self.snapshot())

    def test_reappearing_payload_and_mutated_stub_are_rejected(self):
        R.apply(self.stage); path = self.stage / 'examples/gamma-native/data.json'; path.write_bytes(b'reappeared')
        with self.assertRaisesRegex(ValueError, 'reappeared'): R.validate(self.stage)
        path.unlink(); (self.stage / 'examples/gegi/index.html').write_bytes(b'mutated stub')
        with self.assertRaisesRegex(ValueError, 'entry page changed'): R.validate(self.stage)


if __name__ == '__main__':
    unittest.main(verbosity=2)
