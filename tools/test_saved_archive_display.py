"""Readable archived plots preserve every original scientific component and reject resealing."""
import copy
import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import saved_archive_display as D

class ArchiveDisplayTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=D.ROOT/'.local')
        self.addCleanup(self.temp.cleanup);self.site=Path(self.temp.name)
        original=self.site/D.ORIGINAL;original.parent.mkdir(parents=True)
        shutil.copyfile(D.ROOT/'docs'/D.ORIGINAL,original)
        self.original=original.read_bytes()

    def test_readable_layout_preserves_all_scientific_components_and_original(self):
        receipt=D.assemble(self.site);text=(self.site/D.PAGE).read_text(encoding='utf-8')
        self.assertEqual((self.site/D.ORIGINAL).read_bytes(),self.original)
        self.assertEqual(D.scientific_components(text),D.scientific_components(self.original.decode('utf-8')))
        self.assertEqual(len(receipt['components']['svg']),56)
        self.assertIn('minmax(min(100%,600px),1fr)',text)
        self.assertIn('overflow-x:auto',text)
        self.assertIn('Original archived layout',text)
        self.assertIn('provisional response',text)
        self.assertEqual(text.count('id="page-navigation"'),1)
        self.assertEqual(text.count('aria-label="Primary"'),1)
        self.assertEqual(text.count('aria-label="Breadcrumb"'),1)
        self.assertNotIn('Methods and limitations</a>',text)
        for name in ('report.json','summary.csv','signals.csv'):
            self.assertIn('../examples/native-li/'+name,text)

    def test_idempotent_and_rehashed_html_refused(self):
        D.assemble(self.site);before={p:(p.read_bytes(),p.stat().st_mtime_ns) for p in self.site.rglob('*') if p.is_file()}
        D.assemble(self.site)
        self.assertEqual(before,{p:(p.read_bytes(),p.stat().st_mtime_ns) for p in before})
        page=self.site/D.PAGE;raw=page.read_bytes().replace(b'Induced charge (fC)',b'Incorrect unit',1)
        page.write_bytes(raw);manifest=self.site/D.MANIFEST;r=json.loads(manifest.read_bytes())
        r['output'][D.PAGE]={'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
        manifest.write_text(json.dumps(r))
        with self.assertRaisesRegex(ValueError,'HTML differs'):D.validate(self.site)
        with self.assertRaisesRegex(ValueError,'HTML differs'):D.assemble(self.site)
        self.assertEqual(page.read_bytes(),raw)

    def test_original_or_source_change_refused_before_writes(self):
        with patch.dict(D.LOADED,{'tools/site_restructure.py':'0'*64}):
            with self.assertRaisesRegex(ValueError,'source changed'):D.assemble(self.site)
        self.assertFalse((self.site/D.PAGE).exists())
        (self.site/D.ORIGINAL).write_bytes(self.original+b' ')
        with self.assertRaisesRegex(ValueError,'archive changed'):D.assemble(self.site)
        self.assertFalse((self.site/D.PAGE).exists())

    def test_resealed_receipt_refused(self):
        receipt=D.assemble(self.site);changed=copy.deepcopy(receipt);changed['science_calls']=1
        (self.site/D.MANIFEST).write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError,'receipt differs'):D.validate(self.site)

    def test_exact_8ef_display_migrates_and_resealed_previous_is_refused(self):
        for name in (D.PAGE,D.MANIFEST):
            (self.site/name).parent.mkdir(parents=True,exist_ok=True)
            original=subprocess.run(['git','show','8ef88bd86500f0cf4ea5e2998cd9cd19deedf5f5:docs/'+name],
                                    cwd=D.ROOT,stdout=subprocess.PIPE,check=True).stdout
            (self.site/name).write_bytes(original)
        previous=(self.site/D.MANIFEST).read_bytes()
        self.assertIn(hashlib.sha256(previous).hexdigest(),D.PREVIOUS_RECEIPTS)
        self.assertEqual(D.validate(self.site),json.loads(previous))
        # Scientific components alone cannot admit a changed original file.
        (self.site/D.ORIGINAL).write_bytes(self.original+b' ')
        with self.assertRaisesRegex(ValueError,'archive changed'):D.validate(self.site)
        (self.site/D.ORIGINAL).write_bytes(self.original)
        D.assemble(self.site)
        self.assertNotEqual((self.site/D.MANIFEST).read_bytes(),previous)
        self.assertEqual((self.site/D.ORIGINAL).read_bytes(),self.original)
        # Even a display-only rehash cannot impersonate the accepted old receipt.
        original=subprocess.run(['git','show','8ef88bd86500f0cf4ea5e2998cd9cd19deedf5f5:docs/'+D.PAGE],
                                cwd=D.ROOT,stdout=subprocess.PIPE,check=True).stdout
        (self.site/D.PAGE).write_bytes(original)
        raw=(self.site/D.PAGE).read_bytes()+b' ';(self.site/D.PAGE).write_bytes(raw)
        old=json.loads(previous);old['output'][D.PAGE]={'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
        (self.site/D.MANIFEST).write_text(json.dumps(old),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'HTML differs'):D.validate(self.site)
        with self.assertRaisesRegex(ValueError,'HTML differs'):D.assemble(self.site)
        self.assertEqual((self.site/D.PAGE).read_bytes(),raw)

    def test_authenticated_first_local_archive_requires_exact_receipt_and_output(self):
        previous=(D.ROOT/'docs'/D.MANIFEST).read_bytes()
        if hashlib.sha256(previous).hexdigest()!='3cf2560a5ffeb398227377daed4e36bcc272379422ddb5c2b12543b363e1b723':
            self.skipTest('Authenticated first local build is no longer installed')
        for name in (D.PAGE,D.MANIFEST):
            (self.site/name).parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(D.ROOT/'docs'/name,self.site/name)
        self.assertEqual(D.validate(self.site),json.loads(previous))
        page=self.site/D.PAGE;raw=page.read_bytes()+b' ';page.write_bytes(raw)
        with self.assertRaisesRegex(ValueError,'HTML differs'):D.validate(self.site)
        receipt=json.loads(previous);receipt['output'][D.PAGE]={'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
        (self.site/D.MANIFEST).write_text(json.dumps(receipt),encoding='utf-8')
        self.assertIsNone(D.previous_receipt(self.site))


class LithiumDisplayTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=D.ROOT/'.local')
        self.addCleanup(self.temp.cleanup);self.site=Path(self.temp.name)
        shutil.copytree(D.ROOT/'docs/lithium',self.site/'lithium')
        import lithium_report as producer
        self.original=producer.render(json.loads((self.site/'lithium/summary.json').read_bytes())).encode('utf-8')
        (self.site/D.LITHIUM_PAGE).write_bytes(self.original)

    def test_shared_navigation_preserves_exact_body_and_files(self):
        from site_routes import page_navigation
        original_files={p.name:(p.read_bytes(),p.stat().st_mtime_ns)
                        for p in (self.site/'lithium').iterdir() if p.name!='lithium.html'}
        receipt=D.upgrade_lithium_display(self.site)
        raw=(self.site/D.LITHIUM_PAGE).read_bytes()
        self.assertEqual(raw.replace(page_navigation(D.LITHIUM_PAGE).encode('utf-8'),b'',1),self.original)
        self.assertEqual(receipt['components'],D.scientific_components(self.original.decode('utf-8')))
        self.assertEqual(raw.count(b'id="page-navigation"'),1)
        self.assertEqual(original_files,{p.name:(p.read_bytes(),p.stat().st_mtime_ns)
                        for p in (self.site/'lithium').iterdir() if p.name!='lithium.html'})
        self.assertEqual(D.validate_lithium_display(self.site),receipt)
        before={p:(p.read_bytes(),p.stat().st_mtime_ns) for p in self.site.rglob('*') if p.is_file()}
        D.upgrade_lithium_display(self.site)
        self.assertEqual(before,{p:(p.read_bytes(),p.stat().st_mtime_ns) for p in before})

    def test_rehashed_html_and_original_summary_change_are_refused(self):
        D.upgrade_lithium_display(self.site)
        path=self.site/D.LITHIUM_PAGE;raw=path.read_bytes()+b' ';path.write_bytes(raw)
        manifest=self.site/D.LITHIUM_MANIFEST;receipt=json.loads(manifest.read_bytes())
        receipt['output'][D.LITHIUM_PAGE]={'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
        manifest.write_text(json.dumps(receipt),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'HTML differs'):D.upgrade_lithium_display(self.site)
        self.assertEqual(path.read_bytes(),raw)
        summary=self.site/'lithium/summary.json';summary.write_bytes(summary.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError,'summary changed'):D.validate_lithium_display(self.site)

    def test_authenticated_first_local_lithium_requires_exact_files_output_and_receipt(self):
        previous=(D.ROOT/'docs'/D.LITHIUM_MANIFEST).read_bytes()
        if hashlib.sha256(previous).hexdigest() not in D.PREVIOUS_LITHIUM_RECEIPTS:
            self.skipTest('Authenticated first local build is no longer installed')
        (self.site/D.LITHIUM_MANIFEST).parent.mkdir(parents=True,exist_ok=True)
        (self.site/D.LITHIUM_MANIFEST).write_bytes(previous)
        shutil.copyfile(D.ROOT/'docs'/D.LITHIUM_PAGE,self.site/D.LITHIUM_PAGE)
        self.assertEqual(D.validate_lithium_display(self.site),json.loads(previous))
        data=self.site/'lithium/profiles.csv';original=data.read_bytes();data.write_bytes(original+b' ')
        with self.assertRaisesRegex(ValueError,'scientific file changed'):D.validate_lithium_display(self.site)
        data.write_bytes(original)
        page=self.site/D.LITHIUM_PAGE;raw=page.read_bytes()+b' ';page.write_bytes(raw)
        with self.assertRaisesRegex(ValueError,'HTML differs'):D.validate_lithium_display(self.site)
        receipt=json.loads(previous);receipt['output'][D.LITHIUM_PAGE]={'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
        (self.site/D.LITHIUM_MANIFEST).write_text(json.dumps(receipt),encoding='utf-8')
        self.assertIsNone(D.previous_lithium_receipt(self.site))

if __name__=='__main__':unittest.main(verbosity=2)
