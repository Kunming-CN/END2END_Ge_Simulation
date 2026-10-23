"""Targeted ZIP omission, source authority and exact teaching-data contracts."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import result_web_delivery as D
import teaching_examples as teaching


class ResultDeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Read the accepted saved payload; this does not reconstruct or run any
        # physics. Changing only current generator pins leaves its science exact.
        cls.accepted_payload = json.loads((teaching.ROOT / 'docs' / teaching.DATA).read_bytes())
        cls.accepted_payload['provenance']['generator_sha256'] = {
            name: teaching.sha(teaching.ROOT / name) for name in teaching.GENERATORS}

    def setUp(self):
        owned = teaching.ROOT / '.local/publication-cleanup'
        owned.mkdir(parents=True, exist_ok=True)
        self.scratch = tempfile.TemporaryDirectory(prefix='result-delivery-', dir=owned)
        self.root = Path(self.scratch.name)
        self.assertTrue(self.root.resolve().is_relative_to(owned.resolve()))
        def cleanup():
            self.assertTrue(self.root.resolve().is_relative_to(owned.resolve()))
            D.directory(self.root)
            self.scratch.cleanup()
        self.addCleanup(cleanup)
        self.site = self.root / '.local/site-build'
        self.folder = self.site / D.PREFIX
        self.folder.mkdir(parents=True)
        self.local = self.root / '.local/ring-publication-v1/web-bundle'
        self.source = {'kind': 'ring_saved_publication_v1', 'schema_version': 1,
                       'status': 'complete', 'models': {'GeRC02': {}, 'KMRC01_candidate': {}}, 'files': {}}
        self.science = b'{"event_id":9999,"zero":-0.0,"charge":null,"failure":"native"}\n'
        self.summary = ('<!doctype html><h1>Saved result</h1><nav>'
                        '<a href="ledgers.zip">Complete archive</a><a href="signals.csv">Signed signals</a>'
                        '</nav><svg><path d="M 1 2 L 3 4"/></svg>'
                        '<script type="application/json">{"value":1.0000000000000002,"unit":"keV"}</script>')
        for model in ('GeRC02', 'KMRC01_candidate'):
            self.save(model + '/response/ledgers.zip', (model + ' exact ZIP fixture').encode())
            self.save(model + '/response/summary.html', self.summary.encode())
            self.save(model + '/response/signals.csv', b'time_ns,charge_fC\n0,-0.0\n1,-1.0000000000000002\n')
            self.save(model + '/response/scalars.jsonl', self.science)
            self.save(model + '/scene.json', self.science)
        self.save('KMRC01_candidate/response/original-native/summary.html',
                  b'<h1>0/231 original groups accepted</h1><a href="../ledgers.zip">Original ZIP</a>')
        body = D.encoded(self.source)
        (self.folder / 'manifest.json').write_bytes(body)
        shutil.copytree(self.folder, self.local)
        self.start_patch(patch.object(D, 'ROOT', self.root))
        self.start_patch(patch.object(D, 'SOURCE_MANIFEST_SHA256', D.stamp(body)['sha256']))
        self.start_patch(patch.object(D, 'OMITTED_BYTES', sum(self.source['files'][name]['bytes'] for name in D.OMITTED)))
        self.original_check = self.start_patch(patch.object(D.original, 'validate_bundle', return_value=self.source))
        payload = copy.deepcopy(self.accepted_payload)
        for name, body in ((teaching.DATA, teaching.canonical(payload).encode()),
                           (teaching.PAGE, teaching.render(payload).encode())):
            path = self.site / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)

    def start_patch(self, manager):
        result = manager.start()
        self.addCleanup(manager.stop)
        return result

    def save(self, name, body):
        path = self.folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        self.source['files'][name] = D.stamp(body)

    def receipt(self):
        return json.loads((self.folder / D.MARKER).read_bytes())

    def write_receipt(self, value):
        (self.folder / D.MARKER).write_bytes(D.encoded(value))

    def test_finalize_omits_only_two_archives_and_preserves_all_science(self):
        before = {name: (self.folder / name).read_bytes() for name in self.source['files']}
        manifest = (self.folder / 'manifest.json').read_bytes()
        receipt = D.finalize(self.site)
        self.original_check.assert_called_once_with(self.folder)
        self.assertEqual(set(receipt['omitted_downloads']), D.OMITTED)
        self.assertEqual((self.folder / 'manifest.json').read_bytes(), manifest)
        self.assertEqual(D.validate_bundle(self.folder), receipt)
        for name, body in before.items():
            if name in D.OMITTED:
                self.assertFalse((self.folder / name).exists())
            elif name.endswith('.html'):
                actual = (self.folder / name).read_text(encoding='utf-8')
                self.assertEqual(actual, D.strip_archive_links(body.decode(), D.PREFIX + '/' + name))
                for content in ('<svg>', '1.0000000000000002', 'keV', '0/231'):
                    if content in body.decode():
                        self.assertIn(content, actual)
            else:
                self.assertEqual((self.folder / name).read_bytes(), body)
        self.assertEqual(D.finalize(self.site), receipt)

    def test_portable_validation_does_not_read_local_originals(self):
        D.finalize(self.site)
        shutil.rmtree(self.local)
        D.validate_bundle(self.folder)

    def test_scientific_change_cannot_be_rehashed_into_derivative(self):
        D.finalize(self.site)
        name = 'GeRC02/response/scalars.jsonl'
        (self.folder / name).write_bytes(self.science.replace(b'9999', b'9998'))
        with self.assertRaisesRegex(ValueError, 'Retained scientific'):
            D.validate_bundle(self.folder)

    def test_report_value_change_fails_even_with_new_delivered_hash(self):
        D.finalize(self.site)
        name = 'GeRC02/response/summary.html'
        path = self.folder / name
        path.write_bytes(path.read_bytes().replace(b'1.0000000000000002', b'9.0000000000000002'))
        receipt = self.receipt()
        receipt['html_rewrites'][name]['delivered'] = D.stamp(path.read_bytes())
        self.write_receipt(receipt)
        with self.assertRaisesRegex(ValueError, 'Original report content'):
            D.validate_bundle(self.folder)

    def test_omission_and_extra_inventory_are_fixed(self):
        D.finalize(self.site)
        receipt = self.receipt()
        receipt['omitted_downloads']['GeRC02/response/scalars.jsonl'] = self.source['files']['GeRC02/response/scalars.jsonl']
        self.write_receipt(receipt)
        with self.assertRaisesRegex(ValueError, 'two registered'):
            D.validate_bundle(self.folder)
        self.write_receipt({**receipt, 'omitted_downloads': {name: self.source['files'][name] for name in D.OMITTED}})
        (self.folder / 'unexpected.json').write_bytes(b'{}')
        with self.assertRaisesRegex(ValueError, 'inventory'):
            D.validate_bundle(self.folder)

    def test_changed_original_manifest_cannot_be_resealed(self):
        D.finalize(self.site)
        changed = copy.deepcopy(self.source)
        changed['models']['GeRC02']['event_count'] = 9999
        body = D.encoded(changed)
        (self.folder / 'manifest.json').write_bytes(body)
        receipt = self.receipt()
        receipt['original_manifest_sha256'] = D.stamp(body)['sha256']
        self.write_receipt(receipt)
        with self.assertRaisesRegex(ValueError, 'Unknown original ring'):
            D.validate_bundle(self.folder)

    def test_only_canonical_stage_can_be_mutated(self):
        public = self.root / 'docs'
        shutil.copytree(self.site, public)
        for function in (D.finalize, D.materialize_for_build):
            with self.assertRaisesRegex(ValueError, 'restricted to'):
                function(public)
        for name in D.OMITTED:
            self.assertTrue((public / D.PREFIX / name).is_file())

    def test_materialize_restores_exact_build_inputs_and_source_summary(self):
        D.finalize(self.site)
        D.materialize_for_build(self.site)
        self.assertFalse((self.folder / D.MARKER).exists())
        for name, meta in self.source['files'].items():
            self.assertEqual(D.file_stamp(self.folder / name), meta)
        D.finalize(self.site)
        D.validate_bundle(self.folder)

    def test_changed_preserved_archive_stops_before_writing_stage(self):
        D.finalize(self.site)
        name = sorted(D.OMITTED)[0]
        (self.local / name).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'Permanent original archive changed'):
            D.materialize_for_build(self.site)
        self.assertTrue((self.folder / D.MARKER).is_file())
        self.assertTrue(all(not (self.folder / n).exists() for n in D.OMITTED))

    def test_anchor_transform_preserves_content_and_unrelated_downloads(self):
        page = 'spectra/cs137-10k.html'
        text = ('<p><a href="../examples/cs137-10k-rings/GeRC02/response/ledgers.zip">'
                '<strong>ZIP</strong></a><a href="../examples/cs137-10k/AK02/response/ledgers.zip">Keep</a>'
                '<a href="https://example.test/ledgers.zip">External</a></p>')
        actual = D.strip_archive_links(text, page)
        self.assertIn('<p><strong>ZIP</strong><a href=', actual)
        self.assertIn('AK02/response/ledgers.zip', actual)
        self.assertIn('https://example.test/ledgers.zip', actual)
        delivered, edits = D._rewrite(text, page)
        self.assertEqual(D._restore(delivered, edits), text)

    def test_linked_member_is_rejected(self):
        D.finalize(self.site)
        target = self.folder / 'GeRC02/scene.json'
        target.unlink()
        try:
            target.symlink_to(self.local / 'GeRC02/scene.json')
        except OSError as error:
            self.skipTest('Host does not allow fixture symlinks: ' + str(error))
        with self.assertRaisesRegex(ValueError, 'Linked delivery member'):
            D.validate_bundle(self.folder)

    def test_teaching_science_fingerprint_rejects_rehashed_value_change(self):
        D.finalize(self.site)
        payload = copy.deepcopy(self.accepted_payload)
        payload['cases'][0]['saved_trace']['trace']['time_ns'][1] += 0.25
        (self.site / teaching.DATA).write_bytes(teaching.canonical(payload).encode())
        (self.site / teaching.PAGE).write_bytes(teaching.render(payload).encode())
        with self.assertRaisesRegex(ValueError, 'scientific payload changed'):
            D._teaching_payload(self.site)

    def test_teaching_generator_hashes_remain_current(self):
        D.finalize(self.site)
        payload = copy.deepcopy(self.accepted_payload)
        payload['provenance']['generator_sha256']['tools/teaching_examples.py'] = '0' * 64
        (self.site / teaching.DATA).write_bytes(teaching.canonical(payload).encode())
        with self.assertRaisesRegex(ValueError, 'generator binding changed'):
            D._teaching_payload(self.site)

    def test_teaching_validate_dispatches_only_for_explicit_marker(self):
        with patch.object(D, 'validate_teaching', return_value={'status': 'checked'}) as gate:
            D.finalize(self.site)
            self.assertEqual(teaching.validate(self.site), {'status': 'checked'})
            gate.assert_called_once_with(self.site)

    def test_portable_teaching_accepts_exact_science_and_requires_exact_render(self):
        D.finalize(self.site)
        # Separate this test's tiny synthetic ring inventory from the real,
        # immutable teaching-source map. Production checks the complete map.
        with patch.object(teaching, 'SOURCE_SHA256', {}):
            result = D.validate_teaching(self.site)
            self.assertEqual(result['selection'], [[m, e, g] for m, e, g, _, _ in teaching.SELECTION])
            path = self.site / teaching.PAGE
            path.write_bytes(path.read_bytes().replace(b'<title>', b'<title>Altered '))
            with self.assertRaisesRegex(ValueError, 'Teaching rendering changed'):
                D.validate_teaching(self.site)


if __name__ == '__main__':
    unittest.main()
