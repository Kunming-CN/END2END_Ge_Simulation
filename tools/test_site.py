"""Fast publication guard tests; no scientific environment or network required."""
import json
import hashlib
import io
import os
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_site import MANIFEST, local_target, validate
import export_models as models

class PublicationTests(unittest.TestCase):
    def test_staged_recovery_requires_validated_snapshot_and_stage(self):
        import build_site as builder
        project=self.site/'recovery'; docs=project/'docs'; stage=project/'.local/site-build'
        docs.mkdir(parents=True); (docs/MANIFEST).write_bytes(b'{}\n')
        with patch.multiple(builder,ROOT=project,DESTINATION=docs,OUT=stage), patch.object(builder,'validate') as gate:
            with self.assertRaisesRegex(ValueError,'real generated stage'):builder.finish_staged()
            stage.mkdir(parents=True); (stage/'index.html').write_bytes(b'generated\n')
            backup=project/'.local/site-previous'; backup.mkdir()
            with self.assertRaisesRegex(ValueError,'pending atomic swap'):builder.finish_staged()
            backup.rmdir()
            before={p.relative_to(project):p.read_bytes() for p in project.rglob('*') if p.is_file()}
            def reject_stage(folder,**kwargs):
                if folder==docs:return {'build_id':'old'}
                self.assertEqual(kwargs,{'require_manifest':False,'require_models':True})
                raise ValueError('invalid source-bound staged payload')
            gate.side_effect=reject_stage
            with self.assertRaisesRegex(ValueError,'invalid source-bound'):builder.finish_staged()
            self.assertEqual(before,{p.relative_to(project):p.read_bytes() for p in project.rglob('*') if p.is_file()})

    def test_staged_recovery_shares_atomic_install_without_generation(self):
        import build_site as builder
        project=self.site/'recovery-success'; docs=project/'docs'; stage=project/'.local/site-build'
        docs.mkdir(parents=True); (docs/MANIFEST).write_bytes(b'{}\n'); (docs/'index.html').write_bytes(b'old\n')
        stage.mkdir(parents=True); (stage/'index.html').write_bytes(b'new\n')
        def checked(folder,**kwargs):return {'build_id':'old' if folder==docs else 'new','files':[]}
        printed=io.StringIO()
        with patch.multiple(builder,ROOT=project,DESTINATION=docs,OUT=stage), patch.object(builder,'validate',side_effect=checked) as gate, patch.object(builder,'build',side_effect=AssertionError('must not regenerate')), redirect_stdout(printed):
            summary=builder.finish_staged()
            self.assertEqual(gate.call_args_list,[unittest.mock.call(docs),unittest.mock.call(stage,require_manifest=False,require_models=True),unittest.mock.call(stage)])
        self.assertEqual(summary,{'build_id':'new'})
        self.assertEqual(json.loads(printed.getvalue().split('\n',1)[1]),summary)
        self.assertEqual((docs/'index.html').read_bytes(),b'new\n')
        self.assertFalse(stage.exists()); self.assertFalse((project/'.local/site-previous').exists())

    def test_staged_recovery_is_exclusive_with_generation_mode(self):
        script=Path(__file__).with_name('build_site.py')
        result=subprocess.run([sys.executable,'-B',str(script),'--finish-staged','--restructure'],capture_output=True,text=True)
        self.assertEqual(result.returncode,2)
        self.assertIn('Select one publication mode',result.stderr)

    def test_staged_recovery_refuses_junctions_and_linked_ancestors(self):
        import build_site as builder
        project=self.site/'recovery-links'; docs=project/'docs'; stage=project/'.local/site-build'
        docs.mkdir(parents=True); (docs/MANIFEST).write_bytes(b'{}\n'); stage.mkdir(parents=True)
        before={p.relative_to(project):p.read_bytes() for p in project.rglob('*') if p.is_file()}
        for linked in (stage, stage.parent, docs, project):
            with self.subTest(linked=linked), patch.multiple(builder,ROOT=project,DESTINATION=docs,OUT=stage), patch.object(Path,'is_junction',lambda path:path==linked,create=True), patch.object(builder,'validate') as gate, patch.object(builder,'install_snapshot') as installer:
                with self.assertRaisesRegex(ValueError,'real generated stage'):builder.finish_staged()
                gate.assert_not_called(); installer.assert_not_called()
        self.assertEqual(before,{p.relative_to(project):p.read_bytes() for p in project.rglob('*') if p.is_file()})

    def test_hash_bound_ring_text_keeps_exact_line_endings(self):
        import build_site as builder
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / '.local') as temporary:
            folder = Path(temporary)
            ring = folder / 'examples/cs137-10k-rings/KMRC01_candidate/response/summary.html'
            ring.parent.mkdir(parents=True)
            body = b'<html>saved byte-exact result</html>\r\n'
            ring.write_bytes(body)
            builder.normalize_text_outputs(folder)
            self.assertEqual(ring.read_bytes(), body)

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

    def test_host_size_limits_refuse_before_publication_without_large_fixture(self):
        import check_site as checker
        # Lower only the operational limits; real file sizes and hashes stay real.
        with patch.object(checker, 'MAX_PUBLIC_FILE_BYTES', 1):
            with self.assertRaisesRegex(ValueError, 'publication size limit'):
                validate(self.site, require_manifest=False)

    def test_host_size_budget_includes_existing_and_generated_manifest(self):
        import check_site as checker
        report=self.seal(); payload=report['total_bytes']; manifest=self.site/MANIFEST
        with patch.object(checker,'MAX_PUBLIC_SITE_BYTES',payload+manifest.stat().st_size-1):
            with self.assertRaisesRegex(ValueError,'including the site manifest'):validate(self.site)
        generated=len((json.dumps(report,indent=2)+'\n').encode('utf-8'))
        self.assertLess(manifest.stat().st_size,generated)
        # Re-sealing replaces a valid compact manifest with the generated pretty
        # serialization; its old on-disk size must not underestimate that write.
        with patch.object(checker,'MAX_PUBLIC_SITE_BYTES',payload+generated-1):
            with self.assertRaisesRegex(ValueError,'including the site manifest'):validate(self.site,require_manifest=False)
        manifest.unlink()
        with patch.object(checker,'MAX_PUBLIC_SITE_BYTES',payload+generated-1):
            with self.assertRaisesRegex(ValueError,'including the site manifest'):validate(self.site,require_manifest=False)
        with patch.object(checker,'MAX_PUBLIC_SITE_BYTES',payload+generated):
            self.assertEqual(validate(self.site,require_manifest=False),report)
        with patch.object(checker, 'MAX_PUBLIC_SITE_BYTES', 1):
            with self.assertRaisesRegex(ValueError, 'publication size limit'):
                validate(self.site, require_manifest=False)

    def test_gamma_explicit_mode_copies_checked_bytes_without_export(self):
        import build_site as builder
        import gamma_showcase
        project = self.site / 'gamma-mode-fixture'; docs = project / 'docs'
        docs.mkdir(parents=True); (docs / 'index.html').write_bytes(b'old saved snapshot\n')
        sealed = validate(docs, require_manifest=False)
        (docs / MANIFEST).write_text(json.dumps(sealed))
        original = {p.name: p.read_bytes() for p in docs.iterdir()}
        bundle = project / 'synthetic-bundle'; bundle.mkdir()
        for name in (*gamma_showcase.FILES, 'publication.json'):
            (bundle / name).write_bytes(b'synthetic fixture\r\n')
        stage = project / '.local' / 'site-build'
        with patch.multiple(builder, DESTINATION=docs, OUT=stage), \
             patch.object(gamma_showcase, 'ROOT', project), \
             patch('gamma_showcase.validate_bundle') as checked, \
             patch('gamma_showcase.export_saved', side_effect=AssertionError('Export forbidden')):
            builder.build_gamma_export(bundle)
        self.assertEqual(checked.call_count, 2)
        self.assertEqual(original, {p.name: p.read_bytes() for p in docs.iterdir()})
        for name in (*gamma_showcase.FILES, 'publication.json'):
            self.assertEqual((stage / 'examples/gamma-native' / name).read_bytes(), (bundle / name).read_bytes())
        builder.normalize_text_outputs(stage)
        self.assertEqual((stage / 'examples/gamma-native/gamma.html').read_bytes(), b'synthetic fixture\r\n')

    def test_explicit_gamma_mode_reconciles_only_staged_saved_files(self):
        import build_site as builder
        import gamma_showcase
        project = self.site / 'gamma-update-fixture'; docs = project / 'docs'
        old_gamma = docs / 'examples/gamma-native'; old_gamma.mkdir(parents=True)
        (docs / 'index.html').write_bytes(b'old saved snapshot\n')
        for name in (*gamma_showcase.FILES, 'publication.json'): (old_gamma / name).write_bytes(b'old fixture\n')
        bundle = project / 'new-bundle'; bundle.mkdir()
        for name in (*gamma_showcase.FILES, 'publication.json'): (bundle / name).write_bytes(b'new fixture\n')
        stage = project / '.local/site-build'
        before = {p.relative_to(docs).as_posix(): p.read_bytes() for p in docs.rglob('*') if p.is_file()}
        (docs / MANIFEST).write_text('{}')
        with patch.multiple(builder, DESTINATION=docs, OUT=stage), \
             patch.object(builder, 'validate'), patch.object(gamma_showcase, 'ROOT', project), \
             patch('gamma_showcase.validate_bundle') as checked, \
             patch('gamma_showcase.export_saved', side_effect=AssertionError('Export forbidden')):
            builder.build_gamma_export(bundle)
        self.assertEqual(checked.call_count, 3)
        for name, raw in before.items(): self.assertEqual((docs / name).read_bytes(), raw)
        self.assertEqual((stage / 'index.html').read_bytes(), before['index.html'])
        for name in (*gamma_showcase.FILES, 'publication.json'):
            self.assertEqual((stage / 'examples/gamma-native' / name).read_bytes(), (bundle / name).read_bytes())

    def test_site_validator_refuses_partial_gamma_bundle(self):
        (self.site / 'examples/gamma-native').mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, 'public inventory'):
            validate(self.site, require_manifest=False)

    def test_normal_restructure_preserves_saved_gamma_bundle_without_export(self):
        import build_site as builder
        import gamma_showcase
        project=self.site/'gamma-preservation-fixture';docs=project/'docs'
        gamma=docs/'examples/gamma-native';gamma.mkdir(parents=True)
        (docs/'index.html').write_bytes(b'<a href="examples/gamma-native/gamma.html">Saved example</a>\n')
        for name in (*gamma_showcase.FILES,'publication.json'):
            (gamma/name).write_bytes(b'{}\n' if name.endswith('.json') else b'synthetic saved bytes\r\n')
        with patch('gamma_showcase.validate_bundle'):
            sealed=validate(docs,require_manifest=False)
        (docs/MANIFEST).write_text(json.dumps(sealed))
        before={p.relative_to(docs).as_posix():(p.read_bytes(),p.stat().st_mtime_ns) for p in docs.rglob('*') if p.is_file()}
        def fixture_validate(folder,**kwargs):
            return validate(folder,require_manifest=kwargs.get('require_manifest',True))
        with patch.multiple(builder,ROOT=project,DESTINATION=docs,OUT=project/'.local/site-build'), \
             patch.object(builder,'validate',fixture_validate),patch('viewer_navigation.assemble'), \
             patch('gamma_showcase.validate_bundle'), \
             patch('gamma_showcase.export_saved',side_effect=AssertionError('Export forbidden')), \
             patch.object(builder,'build_export',side_effect=AssertionError('Legacy export forbidden')):
            builder.build(restructure=True)
        after={p.relative_to(docs).as_posix():(p.read_bytes(),p.stat().st_mtime_ns) for p in docs.rglob('*') if p.is_file()}
        self.assertEqual(before,after)

    def test_native_example_export_guard(self):
        import hashlib
        import build_site as builder
        directory = self.site / '.local' / 'native-li-example'
        directory.mkdir(parents=True)
        source = self.site / 'simulation'; source.mkdir()
        names = ('run.jl', 'replay.jl', 'readout.jl', 'native_li_example.jl', 'test_native_li_example.jl', 'readout_demo.json')
        hashes = {}
        for name in names:
            (source / name).write_bytes(b'fixture')
            hashes[name] = hashlib.sha256(b'fixture').hexdigest()
        artifacts = {}
        for name in ('comparison.html', 'summary.csv', 'signals.csv'):
            (directory / name).write_bytes(b'fixture')
            artifacts[name] = hashlib.sha256(b'fixture').hexdigest()
        report = dict(status='completed_provisional_native_example', selected_event_ids=[0,2,41,78], source_primary_count=100,
                      unprocessed_event_ids=[i for i in range(100) if i not in (0,2,41,78)], cases=[{}]*14,
                      source_code_sha256=hashes, artifacts=artifacts)
        def save(): (directory / 'report.json').write_text(json.dumps(report))
        save()
        with patch.object(builder, 'ROOT', self.site):
            self.assertEqual(len(builder.native_example_files()[1]), 4)
            (directory / 'summary.csv').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'output changed'): builder.native_example_files()
            (directory / 'summary.csv').write_bytes(b'fixture')
            report['cases'].pop(); save()
            with self.assertRaisesRegex(ValueError, 'census'): builder.native_example_files()

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

    def test_jsonl_requires_ring_prefix_and_bundle_validation(self):
        ring=self.site/'examples/cs137-10k-rings/GeRC02/response/scalars.jsonl'
        ring.parent.mkdir(parents=True)
        ring.write_bytes(b'{"signed":-0.0,"unknown":null}\n')
        # Only the file-policy boundary is synthetic here. Full scientific
        # validation has its own real bundle and mutation regression.
        with patch('ring_publication.validate_bundle',return_value={}) as check_ring:
            validate(self.site,require_manifest=False)
            check_ring.assert_called_once_with(self.site/'examples/cs137-10k-rings')
        (self.site/'scalars.jsonl').write_bytes(ring.read_bytes())
        with self.assertRaisesRegex(ValueError,'Unapproved public file'):
            validate(self.site,require_manifest=False)

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

    @unittest.skipUnless(os.name == 'nt', 'Windows read-only directory regression')
    def test_unchanged_export_cleans_readonly_stage_without_rewriting_docs(self):
        import build_site
        project = self.site / 'unchanged-project'
        docs = project / 'docs'
        nested = docs / 'assets' / 'nested'
        nested.mkdir(parents=True)
        (docs / 'index.html').write_text('<a href="assets/nested/data.csv">Data</a>')
        (nested / 'data.csv').write_text('x\n1\n')
        sealed = validate(docs, require_manifest=False)
        (docs / MANIFEST).write_text(json.dumps(sealed))
        before = {p.relative_to(docs).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
                  for p in docs.rglob('*') if p.is_file()}
        stage = project / '.local' / 'site-build'
        def identical_export():
            build_site.shutil.copytree(docs, stage)
            (stage / MANIFEST).unlink()
            os.chmod(stage / 'assets' / 'nested', stat.S_IREAD)
        def fixture_validate(folder, **kwargs):
            return validate(folder, require_manifest=kwargs.get('require_manifest', True))
        # Bounded saved-byte fixture omits model/gallery/readers; real publication
        # remains separately checked against the complete preserved snapshot.
        with patch.multiple(build_site, ROOT=project, DESTINATION=docs, OUT=stage), \
             patch.object(build_site, 'build_export', identical_export), \
             patch.object(build_site, 'validate', fixture_validate), \
             patch('viewer_navigation.assemble'):
            try:
                build_site.build()
                self.assertFalse(stage.exists())
            finally:
                if stage.exists():
                    build_site.remove_generated(stage)
        after = {p.relative_to(docs).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
                 for p in docs.rglob('*') if p.is_file()}
        self.assertEqual(before, after)
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
        from site_discovery import assemble
        page_html = '<html><head><title>Models</title></head><body><main></main></body></html>'
        files = models.download_files(models.read_distribution(models.MODELS))
        files['index.html'] = adapt(page_html, Path('index.html')).encode()
        files['guide.html'] = b'<html><head><title>Guide</title></head><body><a href="downloads/all-models.zip">All models</a></body></html>'
        files['examples/pipeline.html'] = b'<a href="data.json">Example data</a>'
        files['examples/data.json'] = b'{}'
        files['examples/native-li/comparison.html'] = b'Native demonstration fixture'
        files['lithium/lithium.html'] = b'<a href="../index.html">Library</a>'
        for detector in models.ORIGINAL_HASHES:
            page = f'detectors/{detector}/index.html'
            files[page] = adapt(page_html, Path(page)).encode()
            if detector != 'GeGI_3D':
                # Bounded fixture for the new full-size illustration link.
                files[f'detectors/{detector}/runs/20260922_suite_v3/01_geometry.png'] = b'\x89PNG\r\n\x1a\n'
        # Existing homepage/GeGI links need only bounded placeholder pages.
        for name in ('strip_explorer.html', 'supplement.html', 'octagon_geometry.png'):
            files['detectors/GeGI_3D/' + name] = b''
        models.write_new_or_identical(self.root, files)
        assemble(self.root)
        return {p.relative_to(self.root).as_posix(): p.read_bytes()
                for p in self.root.rglob('*') if p.is_file()}

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

    def test_live_check_requests_every_model_and_ring_download(self):
        from check_site import verify_live
        from urllib.parse import unquote, urlsplit
        files = self.model_site()
        report = validate(self.root, require_manifest=False)
        # Synthetic network fixtures exercise complete ring-prefix selection;
        # this test does not claim they are valid saved scientific artifacts.
        for name, data in {
            'examples/cs137-10k-rings/GeRC02/raw/events-000.json.gz': b'gzip-fixture',
            'examples/cs137-10k-rings/KMRC01_candidate/response/ledgers.zip': b'zip-fixture',
            'examples/cs137-10k-rings/packaging-source-manifest.json': b'manifest-fixture',
        }.items():
            files[name] = data
            report['files'].append(dict(path=name, bytes=len(data), sha256=hashlib.sha256(data).hexdigest()))
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
        expected = {name for name in files if name.startswith(('models/', 'downloads/', 'examples/cs137-10k-rings/'))}
        expected.update({'LICENSE', 'sitemap.xml'})
        self.assertTrue(expected <= requested)


if __name__ == '__main__':
    unittest.main(verbosity=2)
