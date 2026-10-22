"""The saved 1M archive names its independent 10K links without changing science."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

import native_response_publication as P


class ResponseArchiveNavigationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=P.ROOT/'.local')
        self.addCleanup(self.temp.cleanup);self.folder=Path(self.temp.name)/'response'
        shutil.copytree(P.ROOT/'docs/examples/cs137-1m-response',self.folder)

    def test_exact_predecessor_migrates_with_explicit_study_identity(self):
        original=(self.folder/'report.html').read_bytes()
        science={name:(self.folder/name).read_bytes() for name in P.COPY if name!='report.html'}
        receipt=P.upgrade_archive_navigation(self.folder)
        raw=(self.folder/'report.html').read_bytes();text=raw.decode('utf-8')
        self.assertIn('Independent Cs137 10K study · 3D examples</a>',text)
        self.assertIn('not part of this 1M-per-detector study',text)
        self.assertIn('../../results/cs137-1m/index.html',text)
        self.assertNotIn('>3D Ge-hit examples</a>',text)
        self.assertEqual(raw.split(b'<h1>',1)[1],original.split(b'<h1>',1)[1])
        self.assertEqual(science,{name:(self.folder/name).read_bytes() for name in science})
        self.assertEqual(receipt,P.validate(self.folder))
        before={p:(p.read_bytes(),p.stat().st_mtime_ns) for p in self.folder.iterdir()}
        P.upgrade_archive_navigation(self.folder)
        self.assertEqual(before,{p:(p.read_bytes(),p.stat().st_mtime_ns) for p in self.folder.iterdir()})

    def test_rehashed_science_or_report_edits_are_refused(self):
        P.upgrade_archive_navigation(self.folder)
        manifest_path=self.folder/'publication.json';receipt=json.loads(manifest_path.read_bytes())
        for name in ('report.html','histograms.json'):
            with self.subTest(name=name):
                path=self.folder/name;original=path.read_bytes();changed=original+b' '
                path.write_bytes(changed);edited=copy.deepcopy(receipt)
                edited['files'][name]={'sha256':hashlib.sha256(changed).hexdigest(),'bytes':len(changed)}
                manifest_path.write_text(json.dumps(edited,indent=2)+'\n',encoding='utf-8')
                with self.assertRaisesRegex(ValueError,'Original response (archive|publication binding)'):
                    P.validate(self.folder)
                with self.assertRaises(ValueError):P.upgrade_archive_navigation(self.folder)
                self.assertEqual(path.read_bytes(),changed)
                path.write_bytes(original)
        manifest_path.write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
        P.validate(self.folder)

    def test_current_publisher_still_requires_the_exact_original_report(self):
        page=self.folder/'report.html';page.write_bytes(P.archive_report(page.read_bytes()))
        path=self.folder/'publication.json';receipt=json.loads(path.read_bytes())
        receipt['publisher_sha256']=P.sha(P.__file__)
        receipt['files']['report.html']={'sha256':P.sha(page),'bytes':page.stat().st_size}
        path.write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
        P.validate(self.folder)
        receipt['source_summary_sha256']='0'*64
        path.write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'Original response publication binding changed'):
            P.validate(self.folder)

    def test_existing_truth_extension_tracks_display_migration_and_preserves_original_pointer(self):
        truth=self.folder.parent/'cs137-1m';truth.mkdir()
        path=truth/'publication.json'
        shutil.copyfile(P.ROOT/'docs/examples/cs137-1m/publication.json',path)
        original=json.loads(path.read_bytes())
        P.upgrade_archive_navigation(self.folder)
        current=json.loads(path.read_bytes())
        self.assertEqual(current['files'],original['files'])
        self.assertEqual(current['native_response_extension'],{
            'publication_sha256':P.sha(self.folder/'publication.json'),
            'original_truth_artifacts_modified':False,
            'original_response_publication_sha256':P.ARCHIVE_PUBLICATION_SHA})
        P.response_extension_pointer(self.folder)
        current['native_response_extension']['publication_sha256']='0'*64
        path.write_text(json.dumps(current,indent=2)+'\n',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'publication pointer'):
            P.response_extension_pointer(self.folder)
        with self.assertRaisesRegex(ValueError,'publication pointer'):
            P.upgrade_archive_navigation(self.folder)


if __name__=='__main__':unittest.main()
