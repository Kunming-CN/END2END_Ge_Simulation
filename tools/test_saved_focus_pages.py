"""Read-only teaching source and focused template checks; never exports."""
import copy
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import pipeline_demo as P
import saved_focus_pages as F
import gamma_showcase as S

class TeachingFocusTests(unittest.TestCase):
    def test_installed_gamma_receipt_is_an_authenticated_current_or_previous_display(self):
        raw=(F.ROOT/'docs/examples/gamma-native/publication.json').read_bytes()
        manifest=S.decode(raw)
        current=F.validate_display_binding('gamma',manifest)
        if not current:self.assertIn(S.sha(raw),F.PREVIOUS_DISPLAY_RECEIPTS['gamma'])
        self.assertEqual(S.canonical(manifest),raw)

    def test_historical_gamma_display_requires_exact_receipt_and_original_science(self):
        manifest=S.decode((F.ROOT/'docs/examples/gamma-native/publication.json').read_bytes())
        # Derive from the saved scientific receipt, independently of the latest
        # display writer hashes, so this check remains valid after a rebuild.
        base=F.DISPLAY_BASES['gamma']
        original=copy.deepcopy(manifest);original.pop('display_upgrade')
        original['files'][base['html']]=copy.deepcopy(base['stamp'])
        self.assertEqual(S.sha(S.canonical(original)),base['receipt'])
        manifest['display_upgrade']=dict(kind='saved_plot_display_v1',science_calls=0,
            original_receipt_sha256=base['receipt'],sources={'tools/pipeline_demo.py':'0'*64})
        receipt=S.canonical(manifest)
        with patch.object(F,'display_sources',return_value={}),patch.dict(
                F.PREVIOUS_DISPLAY_RECEIPTS,{'gamma':frozenset({S.sha(receipt)})}):
            self.assertFalse(F.validate_display_binding('gamma',manifest))
            self.assertEqual(S.canonical(manifest),receipt)
            altered=copy.deepcopy(manifest)
            altered['display_upgrade']['sources']['tools/pipeline_demo.py']='1'*64
            with self.assertRaisesRegex(ValueError,'Unknown saved display upgrade binding'):
                F.validate_display_binding('gamma',altered)
            altered=copy.deepcopy(manifest)
            altered['source']['counts']['radiation_primaries']+=1
            with self.assertRaisesRegex(ValueError,'Unknown saved display upgrade binding'):
                F.validate_display_binding('gamma',altered)
            # Even a trusted display checksum cannot replace the original
            # scientific/export receipt with rehashed scientific metadata.
            with patch.dict(F.PREVIOUS_DISPLAY_RECEIPTS,
                    {'gamma':frozenset({S.sha(S.canonical(altered))})}):
                with self.assertRaisesRegex(ValueError,'Original scientific/export receipt changed'):
                    F.validate_display_binding('gamma',altered)

    def test_checked_original_data_and_offline_renderer(self):
        source=P.ROOT/'.local/pipeline-showcase'
        original=(source/'data.json').read_bytes();data=P.validate_export(source)
        html=F.render(data).decode('utf-8')
        self.assertEqual(original,(source/'data.json').read_bytes())
        self.assertNotIn('__FOCUSED_PLOTS_JS__',html)
        self.assertIn('SavedFocusPlots',html);self.assertIn('Full saved window',html)
        self.assertNotIn('src="http',html)
        S.exact(S.decode(original),data,'Every original teaching value')

class TeachingArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=F.ROOT/'.local')
        self.addCleanup(self.temp.cleanup);self.site=Path(self.temp.name)
        directory=self.site/'examples';directory.mkdir()
        for name in F.FILES:shutil.copyfile(F.ROOT/'docs/examples'/name,directory/name)
        self.directory=directory

    def test_historical_identity_and_cross_study_links_preserve_all_saved_values(self):
        original=(self.directory/'pipeline.html').read_bytes()
        data=(self.directory/'data.json').read_bytes()
        F.upgrade_displays(self.site)
        raw=(self.directory/'pipeline.html').read_bytes();text=raw.decode('utf-8')
        self.assertIn('Historical bare-detector teaching study · 200 initial gamma primaries',text)
        self.assertNotIn('Main teaching example',text)
        self.assertNotIn('>Waveforms and spectrum</a>',text)
        self.assertIn('Independent Cs137 10K study · selected signals</a>',text)
        self.assertIn('Independent Cs137 10K study · signal explanation</a>',text)
        self.assertEqual(F.teaching_archive_original(raw),F.teaching_archive_original(original))
        self.assertEqual((self.directory/'data.json').read_bytes(),data)
        F.validate(self.directory)
        receipt=(self.directory/'pipeline-display.json').read_bytes()
        F.upgrade_displays(self.site)
        self.assertEqual((self.directory/'pipeline.html').read_bytes(),raw)
        self.assertEqual((self.directory/'pipeline-display.json').read_bytes(),receipt)

    def test_rehashed_changes_cannot_replace_the_frozen_teaching_archive(self):
        F.upgrade_displays(self.site)
        page=self.directory/'pipeline.html';raw=page.read_bytes()+b' '
        page.write_bytes(raw)
        path=self.directory/'pipeline-display.json';manifest=S.decode(path.read_bytes())
        manifest['files']['pipeline.html']={'bytes':len(raw),'sha256':S.sha(raw)}
        path.write_bytes(S.canonical(manifest))
        with self.assertRaisesRegex(ValueError,'Original teaching reader differs'):
            F.validate(self.directory)
        with self.assertRaisesRegex(ValueError,'Original teaching reader differs'):
            F.upgrade_displays(self.site)
        self.assertEqual(page.read_bytes(),raw)

if __name__=='__main__':unittest.main()
