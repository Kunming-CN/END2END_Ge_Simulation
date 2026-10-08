"""Discovery boundaries, including independently rehashed invalid publications."""
import hashlib
import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path

import check_site
import site_discovery as D


class DiscoveryTests(unittest.TestCase):
    def test_exact_previous_snapshot_migrates_but_rehashed_stale_text_fails(self):
        old=next(iter(D.HISTORICAL_DESCRIPTIONS.values()))
        for path in old:
            p=self.site/path;p.parent.mkdir(parents=True,exist_ok=True)
            p.write_text('<html><head><title>Saved</title></head><body>Saved</body></html>')
        with mock.patch.dict(D.LANDINGS,old):
            D.assemble(self.site);self.seal()
        old_digest=json.loads((self.site/check_site.MANIFEST).read_bytes())['build_id']
        # Isolated small fixture stands in for the exact pinned previous digest.
        with mock.patch.dict(D.HISTORICAL_DESCRIPTIONS,{old_digest:old}):
            check_site.validate(self.site)
            p=self.site/'results/cs137-10k/index.html';original=p.read_text()
            p.write_text(original.replace('Saved</body>','Changed</body>'))
            self.rehash_without_semantic_validation()
            with self.assertRaisesRegex(ValueError,'metadata differs'):
                check_site.validate(self.site)
            p.write_text(original)
            # An unsealed staging copy must carry current descriptions.
            (self.site/check_site.MANIFEST).unlink()
            with self.assertRaisesRegex(ValueError,'metadata differs'):
                D.validate(self.site)
            D.assemble(self.site);D.validate(self.site)
            for path in old:
                parser=D.Metadata();parser.feed((self.site/path).read_text())
                self.assertEqual(parser.descriptions,[D.LANDINGS[path]])
    def test_four_case_metadata_and_legacy_control_boundary(self):
        description=D.LANDINGS['results/cs137-10k/index.html']
        for name in ('AK02','SAP22','GeRC02 Li50min','KMRC01 candidate'):self.assertIn(name,description)
        self.assertNotIn('Earlier',description)
        scenario=D.LANDINGS['scenarios/lbnl-cs137/index.html']
        self.assertIn('shared Cs137, Am241 and Ba133 local workflows',scenario)
        self.assertIn('Legacy AK02/SAP22 CLI support',scenario)
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / '.local')
        self.addCleanup(self.temp.cleanup)
        self.site = Path(self.temp.name)
        for path in ('index.html', 'guide.html', 'results/index.html'):
            page = self.site / path
            page.parent.mkdir(parents=True, exist_ok=True)
            page.write_text('<html><head><title>END2END Ge Simulation</title></head><body>Saved</body></html>')
        (self.site / 'examples').mkdir()
        (self.site / 'examples/frozen.html').write_bytes(b'<html>unchanged saved bytes\r\n</html>')

    def seal(self):
        report = check_site.validate(self.site, require_manifest=False)
        (self.site / check_site.MANIFEST).write_text(json.dumps(report))

    def rehash_without_semantic_validation(self):
        """Rebind every edited byte; metadata refusal must not rely on old hashes."""
        path = self.site / check_site.MANIFEST
        report = json.loads(path.read_text())
        report['files'] = [row for row in report['files'] if (self.site / row['path']).is_file()]
        for row in report['files']:
            data = (self.site / row['path']).read_bytes()
            row.update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        report['total_bytes'] = sum(row['bytes'] for row in report['files'])
        encoded = json.dumps(report['files'], sort_keys=True, separators=(',', ':')).encode()
        report['build_id'] = hashlib.sha256(encoded).hexdigest()
        path.write_text(json.dumps(report))

    def test_repeat_export_preserves_science_and_selects_only_existing_landings(self):
        frozen = (self.site / 'examples/frozen.html').read_bytes()
        D.assemble(self.site)
        first = {p.relative_to(self.site): p.read_bytes() for p in self.site.rglob('*') if p.is_file()}
        D.assemble(self.site)
        self.assertEqual(first, {p.relative_to(self.site): p.read_bytes() for p in self.site.rglob('*') if p.is_file()})
        self.assertEqual((self.site / 'examples/frozen.html').read_bytes(), frozen)
        raw = (self.site / D.SITEMAP).read_text()
        self.assertNotIn('frozen.html', raw)
        self.assertNotIn('lastmod', raw)
        self.assertIn('<loc>' + D.SITE_URL + '</loc>', raw)
        self.assertNotIn(D.SITE_URL + 'index.html', raw)
        self.assertEqual(len(D.landing_descriptions(self.site)), 3)
        D.validate(self.site)

    def test_rehashed_foreign_duplicate_or_missing_sitemap_urls_are_refused(self):
        D.assemble(self.site)
        self.seal()
        valid = (self.site / D.SITEMAP).read_bytes()
        mutations = (
            valid.replace(D.SITE_URL.encode(), b'https://foreign.invalid/'),
            valid.replace(b'</urlset>', b'<url><loc>' + D.SITE_URL.encode() + b'</loc></url></urlset>'),
            valid.replace(b'guide.html', b'missing.html'),
        )
        for bad in mutations:
            with self.subTest(bad=bad):
                (self.site / D.SITEMAP).write_bytes(bad)
                self.rehash_without_semantic_validation()
                with self.assertRaisesRegex(ValueError, 'sitemap differs'):
                    check_site.validate(self.site)

    def test_rehashed_wrong_canonical_and_duplicate_description_are_refused(self):
        D.assemble(self.site)
        self.seal()
        p = self.site / 'index.html'
        original = p.read_text()
        for bad in (original.replace('rel="canonical" href="' + D.SITE_URL, 'rel="canonical" href="https://foreign.invalid/'),
                    original.replace('<title>', '<meta name="description" content="Invented calibrated result"><title>')):
            p.write_text(bad)
            self.rehash_without_semantic_validation()
            with self.assertRaisesRegex(ValueError, 'metadata differs'):
                check_site.validate(self.site)

    def test_arbitrary_xml_is_not_publication_eligible(self):
        (self.site / 'unreviewed.xml').write_text('<private/>')
        with self.assertRaisesRegex(ValueError, 'Unapproved public file'):
            check_site.validate(self.site, require_manifest=False)

    def test_exact_sitemap_is_manifest_bound(self):
        D.assemble(self.site)
        report = check_site.validate(self.site, require_manifest=False)
        (self.site / check_site.MANIFEST).write_text(json.dumps(report))
        self.assertEqual(report, check_site.validate(self.site))
        self.assertIn(D.SITEMAP, [row['path'] for row in report['files']])

    def test_rehashed_ownership_and_license_changes_are_refused(self):
        D.assemble(self.site)
        self.seal()
        p = self.site / 'index.html'
        original = p.read_text()
        tag = f'<meta name="google-site-verification" content="{D.GOOGLE_VERIFICATION}">'
        for bad in (original.replace(tag, ''), original.replace(D.GOOGLE_VERIFICATION, 'wrong'),
                    original.replace(tag, tag + tag)):
            p.write_text(bad)
            self.rehash_without_semantic_validation()
            with self.assertRaisesRegex(ValueError, 'ownership metadata differs'):
                check_site.validate(self.site)
        p.write_text(original)
        (self.site / 'LICENSE').write_text('An invented grant')
        self.rehash_without_semantic_validation()
        with self.assertRaisesRegex(ValueError, 'LICENSE differs'):
            check_site.validate(self.site)

    def test_only_exact_root_software_license_is_admitted(self):
        D.assemble(self.site)
        root = self.site / 'LICENSE'
        root.write_bytes(D.SOFTWARE_LICENSE.read_bytes())
        check_site.validate(self.site, require_manifest=False)
        root.write_text('Invented grant without a sitemap')
        with self.assertRaisesRegex(ValueError, 'LICENSE differs'):
            check_site.validate(self.site, require_manifest=False)
        root.write_bytes(D.SOFTWARE_LICENSE.read_bytes())
        (self.site / 'examples/LICENSE').write_bytes(root.read_bytes())
        with self.assertRaisesRegex(ValueError, 'Unapproved public file'):
            check_site.validate(self.site, require_manifest=False)

    def test_rehashed_missing_sitemap_cannot_skip_ownership_validation(self):
        D.assemble(self.site)
        self.seal()
        (self.site / D.SITEMAP).unlink()
        p = self.site / 'index.html'
        p.write_text(p.read_text().replace(
            f'<meta name="google-site-verification" content="{D.GOOGLE_VERIFICATION}">', ''))
        self.rehash_without_semantic_validation()
        with self.assertRaisesRegex(ValueError, 'sitemap is missing'):
            check_site.validate(self.site)

    def test_rehashed_ownership_body_placement_is_refused(self):
        D.assemble(self.site)
        self.seal()
        p = self.site / 'index.html'
        original = p.read_text()
        tag = f'<meta name="google-site-verification" content="{D.GOOGLE_VERIFICATION}">'
        for bad in (original.replace(tag, '').replace('</body>', tag + '</body>'),
                    original.replace(tag, '').replace('</head>', '</head>' + tag),
                    original.replace(tag, '').replace('<body>', '<body><p>Content</p>' + tag)):
            p.write_text(bad)
            self.rehash_without_semantic_validation()
            with self.assertRaisesRegex(ValueError, 'outside the head'):
                check_site.validate(self.site)

    def test_implicit_home_head_is_repaired_and_rehashed_implicit_is_refused(self):
        p = self.site / 'index.html'
        p.write_text(p.read_text().replace('<head>', '').replace('</head>', ''))
        D.assemble(self.site)
        explicit = p.read_text()
        self.assertIn('<html><head>', explicit)
        self.assertIn('</head><body>', explicit)
        self.seal()
        p.write_text(explicit.replace('<head>', '').replace('</head>', ''))
        self.rehash_without_semantic_validation()
        digest = json.loads((self.site / check_site.MANIFEST).read_bytes())['build_id']
        with self.assertRaisesRegex(ValueError, 'outside the head'):
            check_site.validate(self.site)
        # Only an exact historical digest may pass before repair, not a rehash.
        with mock.patch.object(D, 'LEGACY_IMPLICIT_HEAD', {digest}):
            check_site.validate(self.site)
            p.write_text(p.read_text().replace('Saved</body>', 'Edited</body>'))
            self.rehash_without_semantic_validation()
            with self.assertRaisesRegex(ValueError, 'outside the head'):
                check_site.validate(self.site)
            D.assemble(self.site)
            D.validate(self.site)

    def test_full_unsealed_site_cannot_drop_both_support_markers(self):
        D.assemble(self.site)
        (self.site / 'models').mkdir()
        (self.site / 'models/catalog.json').write_text('{"detectors": []}')
        (self.site / 'LICENSE').unlink()
        p = self.site / 'index.html'
        p.write_text(p.read_text().replace(
            f'<meta name="google-site-verification" content="{D.GOOGLE_VERIFICATION}">', ''))
        with self.assertRaisesRegex(ValueError, 'LICENSE is missing'):
            D.validate(self.site)


if __name__ == '__main__':
    unittest.main()
