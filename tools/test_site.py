"""Fast publication guard tests; no scientific environment or network required."""
import json
import io
import stat
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_site import MANIFEST, local_target, validate
import export_models as models

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


class ModelTests(unittest.TestCase):
    def setUp(self):
        local = Path(__file__).resolve().parents[1] / '.local'
        local.mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(prefix='model-test-', dir=local)
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def fixture(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def test_exact_bytes_and_include_closure(self):
        original = b'name: example\r\nconfig:\r\n  include: shared/drift.yaml\r\n'
        source = self.fixture('source/model.yaml', original)
        dependency = b'model: ADLChargeDriftModel\r\n'
        self.fixture('source/shared/drift.yaml', dependency)
        files = {}
        self.assertEqual(models.collect_model(source, source.parent, 'example.yaml', files),
                         ['shared/drift.yaml'])
        destination = self.root / 'output'
        models.write_new_or_identical(destination, files)
        models.write_new_or_identical(destination, files)
        self.assertEqual((destination / 'example.yaml').read_bytes(), original)
        self.assertEqual((destination / 'shared/drift.yaml').read_bytes(), dependency)
        packed = models.archive_bytes(files)
        models.validate_archive(packed, files)
        with zipfile.ZipFile(io.BytesIO(packed)) as archive:
            self.assertEqual(archive.read('example.yaml'), original)

    def test_unsupported_and_unsafe_includes(self):
        cases = ['include: ../escape.yaml', 'include: /absolute.yaml',
                 'include: C:/private.yaml', 'include: shared\\file.yaml',
                 'include: [a.yaml]', 'include: {path: a.yaml}',
                 'include: "a.yaml"', "'include': a.yaml", 'include: |\n  a.yaml',
                 'include:\n  - a.yaml', 'include: !file a.yaml',
                 'include: &ref a.yaml', 'include: *ref',
                 '"in\\u0063lude": a.yaml', '? include\n: a.yaml',
                 'config: {include: a.yaml}', 'include: a.yaml\n  continued',
                 'include: a.yaml\n---\ninclude: b.yaml', 'include: CON.yaml']
        for text in cases:
            with self.subTest(text=text), self.assertRaises(ValueError):
                models.includes(text.encode())

    def test_cycles_conflicts_and_missing_dependencies(self):
        source = self.fixture('source/a.yaml', b'include: b.yaml\n')
        self.fixture('source/b.yaml', b'include: a.yaml\n')
        with self.assertRaisesRegex(ValueError, 'cycle'):
            models.collect_model(source, source.parent, 'a.yaml', {})
        source.write_bytes(b'include: missing.yaml\n')
        with self.assertRaises(FileNotFoundError):
            models.collect_model(source, source.parent, 'a.yaml', {})
        source.write_bytes(b'model: test\n')
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            models.collect_model(source, source.parent, 'a.yaml', {'a.yaml': b'other'})
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            models.collect_model(source, source.parent, 'a.yaml', {'A.yaml': source.read_bytes()})
        with self.assertRaisesRegex(ValueError, 'approved model root'):
            models.collect_model(source, self.root / 'elsewhere', 'a.yaml', {})

    def test_symlinks_are_rejected(self):
        # Mock the filesystem predicate so this guard runs without Windows
        # symlink privileges. No permissions or developer-mode changes needed.
        source = self.fixture('a.yaml', b'model: test\n')
        with patch.object(Path, 'is_symlink', return_value=True):
            with self.assertRaisesRegex(ValueError, 'Symlink'):
                models.collect_model(source, source.parent, 'a.yaml', {})

    def test_existing_edits_fail_before_writing(self):
        destination = self.root / 'output'
        self.fixture('output/z.yaml', b'user edit')
        with self.assertRaisesRegex(ValueError, 'differs'):
            models.write_new_or_identical(destination, {'a.yaml': b'new', 'z.yaml': b'original'})
        self.assertFalse((destination / 'a.yaml').exists())
        self.assertEqual((destination / 'z.yaml').read_bytes(), b'user edit')

    def test_changed_source_hash(self):
        # A synthetic local catalog exercises import's pre-copy hash guard;
        # tests never need the external GeGI input or ignored original workspace.
        folder = self.root / 'Additional_Simulations/models'
        folder.mkdir(parents=True)
        (folder / 'AK01.yaml').write_bytes(b'name: changed\n')
        items = [{'id': name, 'group': 'thesis', 'model': str(folder / (name + '.yaml')),
                  'model_sha256': sha} for name, sha in models.ORIGINAL_HASHES.items()]
        catalog = self.fixture('catalog.json', models.json_bytes({'detectors': items}))
        with patch.multiple(models, ROOT=self.root, SOURCE_CATALOG=catalog):
            with self.assertRaisesRegex(ValueError, 'Changed original source hash'):
                models.source_snapshot()
            (folder / 'AK01.yaml').write_bytes((models.MODELS / 'AK01.yaml').read_bytes())
            next(item for item in items if item['id'] == 'AK01')['model_sha256'] = '0' * 64
            catalog.write_bytes(models.json_bytes({'detectors': items}))
            with self.assertRaisesRegex(ValueError, 'Changed original source hash'):
                models.source_snapshot()

    def test_archive_paths_and_metadata(self):
        for name in ('../x.yaml', '/x.yaml', 'C:/x.yaml', 'a\\x.yaml',
                     'a/./x.yaml', 'a//x.yaml', 'NUL.yaml', 'a./x.yaml'):
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, 'w') as archive:
                archive.writestr(name, b'model: test\n')
            # Windows ZipInfo normalizes backslashes when writing. Restore the
            # malicious name in both headers to test the reader's real boundary.
            packed = stream.getvalue().replace(name.replace('\\', '/').encode(), name.encode())
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'Unsafe path'):
                models.validate_archive(packed, {name: b'model: test\n'})
        for mode in (stat.S_IFLNK, stat.S_IFDIR):
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, 'w') as archive:
                info = zipfile.ZipInfo('a.yaml', (1980, 1, 1, 0, 0, 0))
                info.external_attr = (mode | 0o777) << 16
                archive.writestr(info, b'target')
            with self.assertRaisesRegex(ValueError, 'Unsafe'):
                models.validate_archive(stream.getvalue(), {'a.yaml': b'target'})
        with self.assertRaisesRegex(ValueError, 'inventory'):
            models.validate_archive(models.archive_bytes({'a.yaml': b'x'}), {'a.yaml': b'x', 'b.yaml': b'y'})
        for data in (b'C:\\Users\\private\\file', b'-----BEGIN PRIVATE KEY-----'):
            with self.assertRaisesRegex(ValueError, 'Private path'):
                models.validate_archive(models.archive_bytes({'a.yaml': data}), {'a.yaml': data})
        hidden = br'{"source": "C:\u005cUsers\u005cprivate"}'
        with self.assertRaisesRegex(ValueError, 'Private path'):
            models.public_text(hidden, 'catalog.json')
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            models.archive_bytes({'a.yaml': b'x', 'A.yaml': b'x'})

    def test_distribution_archives_reproducible_and_complete(self):
        files = models.read_distribution(models.MODELS)
        downloads = models.download_files(files)
        self.assertEqual(downloads, models.download_files(dict(reversed(list(files.items())))))
        self.assertEqual(len(downloads), 38)  # 20 distribution files + 18 ZIPs
        catalog = json.loads(files['catalog.json'])
        self.assertEqual(sum(bool(d['dependencies']) for d in catalog['detectors']), 9)
        models.validate_archive(downloads['downloads/all-models.zip'], files)
        for detector in catalog['detectors']:
            data = downloads['downloads/' + detector['id'] + '.zip']
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                self.assertEqual(set(archive.namelist()),
                                 {detector['model'], *detector['dependencies'], 'catalog.json', 'README.md'})
                self.assertEqual(archive.read(detector['model']), files[detector['model']])
                self.assertEqual(json.loads(archive.read('catalog.json'))['detectors'], [detector])
        changed = dict(files, **{'AK01.yaml': files['AK01.yaml'] + b'\n'})
        with self.assertRaisesRegex(ValueError, 'Changed original hash'):
            models.validate_files(changed)

    def model_site(self):
        from build_site import adapt
        files = models.download_files(models.read_distribution(models.MODELS))
        files['index.html'] = adapt('<main></main>', Path('index.html')).encode()
        files['guide.html'] = b'<a href="downloads/all-models.zip">All models</a>'
        for detector in models.ORIGINAL_HASHES:
            page = f'detectors/{detector}/index.html'
            files[page] = adapt('<main></main>', Path(page)).encode()
            if detector != 'GeGI_3D':
                # Bounded fixture for the new full-size illustration link.
                files[f'detectors/{detector}/runs/20260922_suite_v3/01_geometry.png'] = b'\x89PNG\r\n\x1a\n'
        # Existing homepage/GeGI links need only bounded placeholder pages.
        for name in ('strip_explorer.html', 'supplement.html', 'octagon_geometry.png'):
            files['detectors/GeGI_3D/' + name] = b''
        models.write_new_or_identical(self.root, files)
        return files

    def test_bounded_download_site_and_missing_dependencies(self):
        self.model_site()
        report = validate(self.root, require_manifest=False, require_models=True)
        (self.root / MANIFEST).write_bytes(models.json_bytes(report))
        self.assertEqual(validate(self.root), report)
        dependency = self.root / 'models/ADLChargeDriftModel/drift_velocity_config.yaml'
        dependency.unlink()
        with self.assertRaisesRegex(ValueError, 'Missing model downloads'):
            validate(self.root, require_manifest=False)

    def test_site_rejects_changed_download_and_missing_links(self):
        files = self.model_site()
        archive = self.root / 'downloads/AK01.zip'
        archive.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'differs'):
            validate(self.root, require_manifest=False)
        archive.write_bytes(files['downloads/AK01.zip'])
        (self.root / 'detectors/AK01/index.html').write_text('<main></main>')
        with self.assertRaisesRegex(ValueError, 'Missing model download links'):
            validate(self.root, require_manifest=False)

    def test_live_check_requests_every_model_download(self):
        from check_site import verify_live
        from urllib.parse import unquote, urlsplit
        files = self.model_site()
        report = validate(self.root, require_manifest=False)
        files[MANIFEST] = models.json_bytes(report)
        requested = set()

        def fake_open(request, timeout):
            name = unquote(urlsplit(request.full_url).path).removeprefix('/site/')
            requested.add(name)
            return io.BytesIO(files[name])

        # Exercise the normal network path using an in-memory transport, even
        # under ParaView Python without SSL. This is not a live deployment test.
        with patch.dict(sys.modules, {'ssl': object()}), patch('urllib.request.urlopen', fake_open):
            verify_live('https://example.org/site/', report)
        expected = {name for name in files if name.startswith(('models/', 'downloads/'))}
        self.assertTrue(expected <= requested)


if __name__ == '__main__':
    unittest.main(verbosity=2)
