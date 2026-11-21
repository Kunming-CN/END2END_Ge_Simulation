"""Check five-second display links and exact saved map/census bindings."""

import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest

import gegi_reconstruction_display as display
import site_restructure as structure
import site_routes as routes


class ReconstructionDisplayTests(unittest.TestCase):
    def test_fresh_exhibit_is_first_and_has_a_results_breadcrumb(self):
        home = structure.homepage(commercial=True, reconstruction=True)
        self.assertIn(f'id="main-result-link" href="{display.PAGE.as_posix()}"', home)
        self.assertNotIn('25 × 250 ms', home)
        self.assertEqual(routes.page_record(display.PAGE.as_posix())['parent_id'], 'results/index.html')
        self.assertIn('results/gegi-shared-readout/index.html', structure.homepage(commercial=True))

    def test_exact_saved_data_render_through_the_normal_display_entry(self):
        directory = display.ROOT / '.local/gegi-reconstruction-v1'
        if not (directory / display.SOURCES['range'][0]).is_file():
            self.skipTest('Five-second local scientific evidence is absent from this checkout')
        with TemporaryDirectory(dir=directory) as staging:
            site = Path(staging)
            display.attach(site, directory)
            display.render(site)
            public = json.loads((site / display.DATA).read_bytes())
            self.assertEqual(public['selection']['two_strip_triggers'], 3822)
            self.assertEqual(public['position']['coverage'], {'0': 2832, '1': 143, '2': 8})
            self.assertEqual(public['historical_truth_control']['full_energy_occurrences'], 2)
            for matrices in public['maps']['mass_by_window_and_prior'].values():
                self.assertEqual(set(matrices), set(display.PRIORS))
                for grid in matrices.values():
                    self.assertEqual((len(grid), len(grid[0])), (60, 60))
            self.assertNotIn(str(display.ROOT), json.dumps(public))
            page = (site / display.PAGE).read_text(encoding='utf-8')
            self.assertIn('24.79%', page)
            self.assertIn('41.08', page)
            self.assertIn('1,971 unavailable response groups', page)
            self.assertIn('10/12', page)
            self.assertIn('66.6%', page)
            self.assertEqual(public['uncertainty_controls']['negative_conditions'], 12)
            ids = re.findall(r'id="(trigger-[0-9]+)"', page)
            self.assertEqual(len(ids), len(set(ids)))
            self.assertIn('trigger-12841', ids)
            self.assertTrue(set(re.findall(r'href="#(trigger-[0-9]+)"', page)) <= set(ids))
            self.assertTrue((site / display.IMAGE).is_file())


if __name__ == '__main__':
    unittest.main()
