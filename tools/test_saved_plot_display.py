"""Saved display upgrades must preserve science and refuse rehashed alterations."""
import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import gamma_showcase as S
import saved_focus_pages as D
from gamma_publication import validate_bundle


class SavedDisplayTests(unittest.TestCase):
    def test_known_previous_upgrade_requires_exact_receipt_and_html(self):
        for family,relative in (
                ('gamma','examples/gamma-native/publication.json'),
                ('teaching','examples/pipeline-display.json')):
            manifest=json.loads((D.ROOT/'docs'/relative).read_bytes())
            if S.sha(S.canonical(manifest)) not in D.PREVIOUS_DISPLAY_RECEIPTS[family]:
                continue  # The site has already installed the current upgrade.
            self.assertFalse(D.validate_display_binding(family,manifest))
            altered=copy.deepcopy(manifest)
            altered['files'][D.DISPLAY_BASES[family]['html']]['sha256']='0'*64
            with self.assertRaisesRegex(ValueError,'Unknown saved display upgrade binding'):
                D.validate_display_binding(family,altered)

    def test_original_receipt_cannot_be_resealed_after_data_change(self):
        for family,relative in (
                ('gamma','examples/gamma-native/publication.json'),
                ('teaching','examples/pipeline-display.json')):
            manifest=json.loads((D.ROOT/'docs'/relative).read_bytes())
            if 'display_upgrade' in manifest:
                manifest.pop('display_upgrade')
                manifest['files'][D.DISPLAY_BASES[family]['html']]=D.DISPLAY_BASES[family]['stamp']
            self.assertTrue(D.historical_display(family,S.canonical(manifest)))
            manifest['display_upgrade']=dict(kind='saved_plot_display_v1',science_calls=0,
                original_receipt_sha256=D.DISPLAY_BASES[family]['receipt'],sources=D.display_sources())
            D.validate_display_binding(family,manifest)
            altered=copy.deepcopy(manifest)
            altered['files']['data.json']['sha256']='0'*64
            with self.assertRaisesRegex(ValueError,'Original scientific/export receipt changed'):
                D.validate_display_binding(family,altered)
            altered=copy.deepcopy(manifest)
            altered['display_upgrade']['sources'][D.JS]='0'*64
            with self.assertRaisesRegex(ValueError,'Unknown saved display upgrade binding'):
                D.validate_display_binding(family,altered)

    def test_upgrade_is_idempotent_and_numerical_downloads_remain_exact(self):
        with tempfile.TemporaryDirectory() as temp:
            site=Path(temp);examples=site/'examples';examples.mkdir()
            source=D.ROOT/'docs/examples'
            for name in D.FILES:shutil.copyfile(source/name,examples/name)
            shutil.copytree(source/'gamma-native',examples/'gamma-native')
            numerical={p.relative_to(site):p.read_bytes() for p in site.rglob('*')
                       if p.is_file() and (p.suffix=='.csv' or p.name=='data.json')}
            D.upgrade_displays(site)
            for name,raw in numerical.items():self.assertEqual((site/name).read_bytes(),raw)
            first={p.relative_to(site):p.read_bytes() for p in site.rglob('*') if p.is_file()}
            D.upgrade_displays(site)
            self.assertEqual(first,{p.relative_to(site):p.read_bytes() for p in site.rglob('*') if p.is_file()})
            gamma=examples/'gamma-native';manifest=S.decode((gamma/'publication.json').read_bytes())
            html=(gamma/'gamma.html').read_bytes().replace(b'Time since initial primary',b'Wrong timing axis',1)
            (gamma/'gamma.html').write_bytes(html)
            manifest['files']['gamma.html']={'bytes':len(html),'sha256':S.sha(html)}
            (gamma/'publication.json').write_bytes(S.canonical(manifest))
            with self.assertRaisesRegex(ValueError,'Exact upgraded gamma display'):
                validate_bundle(gamma)


if __name__=='__main__':unittest.main(verbosity=2)
