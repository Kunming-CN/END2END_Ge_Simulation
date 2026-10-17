"""Exact published59f9 display admission; no generated site or science writes."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

import saved_focus_pages as F
import saved_archive_display as D
import spectrum_display as S
import teaching_examples as T
import viewer_navigation as V

ROOT=F.ROOT
SITE=ROOT/'docs'
REF='59f9d008c4ae6f02251e773bf5bc7a81d46dcec4'
RECEIPTS={
    'examples/gamma-native/publication.json':'24c179ff81b51472d8d05e2df4e6759b87de3112a03276716181e4b735cf89b2',
    'methods/native-li-display.json':'af0d6a3ece0a5ee5079112adb4854bdd6a598b1e8e543d1eb402e5459f26d011',
    'methods/lithium-display.json':'565303ade2090462d7b00717fb9c60c64254f6340adc7c6a65d1fbb7ca7669fd',
    'spectra/manifest.json':'946b5c71657183f51251a0436d5c42d941bc60fd6e870556293cdfc5df3fb877',
    'spectra/teaching-examples.json':'3292448d1e0f4fbe57db7b9ca475e176bf8a0467677fcf80a242a91d3c6ca185',
    'spectra/pipeline.html':'6531f87cbac6507352d6a6e20fc32e983fef85e849086ce56a9a37faddcfa4da',
    'viewers/manifest.json':'d44b2095341d3ed08eccd8e89320fe82cfb361d8d077ef8c30ab48599e68b3ee',
}


class PublishedPredecessor(unittest.TestCase):
    def test_trusted_receipts_are_exact_committed_and_current_published_bytes(self):
        for name,digest in RECEIPTS.items():
            with self.subTest(name=name):
                committed=subprocess.check_output(['git','show',REF+':docs/'+name],cwd=ROOT)
                self.assertEqual(hashlib.sha256(committed).hexdigest(),digest)
                self.assertEqual((SITE/name).read_bytes(),committed)
        self.assertIn(RECEIPTS['examples/gamma-native/publication.json'],F.PREVIOUS_DISPLAY_RECEIPTS['gamma'])
        self.assertIn(RECEIPTS['methods/native-li-display.json'],D.PREVIOUS_RECEIPTS)
        self.assertIn(RECEIPTS['methods/lithium-display.json'],D.PREVIOUS_LITHIUM_RECEIPTS)
        self.assertIn(RECEIPTS['spectra/manifest.json'],S.TRUSTED_PREVIOUS_MANIFESTS)
        self.assertIn((RECEIPTS[T.DATA],RECEIPTS[T.PAGE]),T.PUBLISHED_PREVIOUS_DISPLAYS)
        self.assertIn(RECEIPTS['viewers/manifest.json'],V.TRUSTED_PREVIOUS_UNIFIED_MANIFESTS)

    def test_gamma_receipt_reconstructs_original_science_and_rehashed_changes_fail(self):
        import gamma_complete_showcase as G
        manifest=json.loads((SITE/'examples/gamma-native/publication.json').read_bytes())
        self.assertFalse(F.validate_display_binding('gamma',manifest))
        G.validate_bundle(SITE/'examples/gamma-native')
        changed=copy.deepcopy(manifest);changed['source']['counts']['radiation_primaries']+=1
        with self.assertRaisesRegex(ValueError,'Unknown saved display upgrade binding'):
            F.validate_display_binding('gamma',changed)
        with patch.dict(F.PREVIOUS_DISPLAY_RECEIPTS,{'gamma':frozenset({F.S.sha(F.S.canonical(changed))})}):
            with self.assertRaisesRegex(ValueError,'Original scientific/export receipt changed'):
                F.validate_display_binding('gamma',changed)

    def test_archive_and_lithium_validate_original_components_and_every_saved_file(self):
        self.assertEqual(D.validate(SITE),json.loads((SITE/D.MANIFEST).read_bytes()))
        self.assertEqual(D.validate_lithium_display(SITE),json.loads((SITE/D.LITHIUM_MANIFEST).read_bytes()))
        original_read=Path.read_bytes
        target=SITE/'lithium/summary.json'
        def altered(path):return b'{}' if path==target else original_read(path)
        with patch.object(Path,'read_bytes',altered),self.assertRaisesRegex(ValueError,'scientific file changed'):
            D.validate_lithium_display(SITE)

    def test_teaching_previous_pair_still_reconstructs_all_selected_scientific_values(self):
        T.validate(SITE)
        raw=(SITE/T.DATA).read_bytes();page=(SITE/T.PAGE).read_bytes();changed=json.loads(raw)
        changed['cases'][0]['saved_trace']['trace']['preamp_V'][1]+=.001
        body=T.canonical(changed).encode();pair=(hashlib.sha256(body).hexdigest(),hashlib.sha256(page).hexdigest())
        original_read=Path.read_bytes
        def altered(path):return body if path==SITE/T.DATA else original_read(path)
        # Even an accidentally admitted rehash must fail independent science reconstruction.
        with patch.object(Path,'read_bytes',altered),patch.object(T,'PUBLISHED_PREVIOUS_DISPLAYS',frozenset({pair})):
            with self.assertRaisesRegex(ValueError,'Previous teaching scientific content changed'):T.validate(SITE)

    def test_spectrum_predecessor_is_read_only_and_still_binds_saved_bins(self):
        S.validate(SITE)
        with self.assertRaisesRegex(ValueError,'generator binding'):
            S.validate(SITE,require_current_generators=True)

    def test_viewer_predecessor_checks_saved_ring_and_response_file_bindings(self):
        manifest=V.read(SITE/'viewers/manifest.json')
        with patch.object(V,'origins',return_value=manifest['original_files']):
            V.validate(SITE)
            with patch.object(V,'response_records',return_value={}):
                with self.assertRaisesRegex(ValueError,'Saved response file binding mismatch'):V.validate(SITE)
            with patch.object(V,'ring_records',return_value={}):
                with self.assertRaisesRegex(ValueError,'Saved ring file binding mismatch'):V.validate(SITE)


if __name__=='__main__':unittest.main()
