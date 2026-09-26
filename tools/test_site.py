"""Fast publication guard tests; no scientific environment or network required."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_site import MANIFEST, local_target, validate

class PublicationTests(unittest.TestCase):
    def setUp(self):
        local = Path(__file__).resolve().parents[1] / '.local'
        local.mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(prefix='site-test-', dir=local)
        self.site = Path(self.directory.name)
        self.addCleanup(self.directory.cleanup)
        (self.site / 'index.html').write_text('<a href="signal.csv">Data</a>', encoding='utf-8')
        (self.site / 'signal.csv').write_text('time_ns,Q\n0,0\n1,1\n', encoding='utf-8')

    def seal(self):
        report = validate(self.site, require_manifest=False)
        (self.site / MANIFEST).write_text(json.dumps(report), encoding='utf-8')
        return report

    def test_reproducible_manifest(self):
        self.assertEqual(self.seal(), validate(self.site))
        self.assertEqual(self.seal(), validate(self.site))

    def test_case_sensitive_links(self):
        (self.site / 'index.html').write_text('<img src="Signal.csv">')
        with self.assertRaisesRegex(ValueError, 'wrong-case'):
            validate(self.site, require_manifest=False)

    def test_changed_or_stale_files(self):
        self.seal()
        (self.site / 'unused.csv').write_text('x\n1\n')
        with self.assertRaisesRegex(ValueError, 'differs'):
            validate(self.site)

    def test_no_private_paths(self):
        (self.site / 'index.html').write_text(r'C:\Users\someone\model.yaml')
        with self.assertRaisesRegex(ValueError, 'Local path'):
            validate(self.site, require_manifest=False)

    def test_raw_cache_is_not_publishable(self):
        (self.site / 'fields.jls').write_bytes(b'not a web resource')
        with self.assertRaisesRegex(ValueError, 'Unapproved'):
            validate(self.site, require_manifest=False)

    def test_url_boundaries(self):
        self.assertEqual(local_target('detectors/A/index.html', '../../index.html'), 'index.html')
        self.assertIsNone(local_target('index.html', 'https://example.org/'))
        for url in ('../secret.csv', '/wrong-root.csv', 'file:///private.csv'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                local_target('index.html', url)


    def test_failed_export_preserves_previous_snapshot(self):
        from unittest.mock import patch
        import build_site
        project = self.site / 'project'
        docs = project / 'docs'
        docs.mkdir(parents=True)
        original = '<p>previous valid snapshot</p>'
        (docs / 'index.html').write_text(original)
        sealed = validate(docs, require_manifest=False)
        (docs / MANIFEST).write_text(json.dumps(sealed))
        stage = project / '.local' / 'site-build'
        def bad_export():
            stage.mkdir()
            (stage / 'index.html').write_text('<img src="missing.png">')
        with patch.multiple(build_site, ROOT=project, DESTINATION=docs, OUT=stage), patch.object(build_site, 'build_export', bad_export):
            with self.assertRaisesRegex(ValueError, 'Broken'):
                build_site.build()
        self.assertEqual((docs / 'index.html').read_text(), original)
        self.assertEqual(validate(docs), sealed)


if __name__ == '__main__':
    unittest.main(verbosity=2)
