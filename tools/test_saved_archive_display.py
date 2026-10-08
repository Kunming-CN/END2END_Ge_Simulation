"""Readable archived plots preserve every original scientific component and reject resealing."""
import copy
import hashlib
import json
import shutil
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

if __name__=='__main__':unittest.main(verbosity=2)
