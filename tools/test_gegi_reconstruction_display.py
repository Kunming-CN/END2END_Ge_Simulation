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
            self.assertNotIn('local_replay', public['photon_origins'])
            origin = public['photon_origins']['windows']['1173.23_keV']['triggers'][0]
            self.assertEqual(origin['original_trigger_id'], 12841)
            self.assertEqual([round(g['emitted_keV']) for g in origin['photon_truth']['emitted_gammas']
                              if g['ge_deposited_keV'] > 0.], [1332])
            self.assertIn('46.50%', page)
            self.assertIn('9.32', page)
            self.assertIn('5.65', page)
            self.assertEqual(public['raw_angular_response']['triggers'][0]['original_trigger_id'], 12841)
            self.assertTrue(public['conditional_escape_geometry']['reconstruction_preserves_original_rows'])
            exact = public['exact_photon_controls']
            self.assertEqual(len(exact['rows']), 21)
            self.assertEqual(sum(row['score_status'] == 'matched_energy_and_positions' for row in exact['rows']), 8)
            self.assertEqual(exact['status_counts']['verified_exact_photon_kinetic_steps'], 10)
            self.assertNotIn('response_coverage_trigger_12271', exact)
            self.assertIn('0.44–16.59°', page)
            self.assertIn('Doppler broadening', page)
            repair = public['native_response_repair']
            self.assertEqual(sum(repair['census']['final_status_counts'].values()), 1971)
            self.assertEqual(repair['census']['complete_groups'], 849)
            self.assertEqual(repair['conditional_mask']['remaining']['excluded_time_ns'], 560239440.0)
            self.assertIn('0.560239440 s', page)
            boundary = public['local_boundary_response']
            self.assertEqual(boundary['original_trigger_id'], 12271)
            self.assertEqual((boundary['original_projected_mass'], boundary['original_unresolved_mass']), (0., 1.))
            self.assertEqual(len(boundary['native_points']), 10)
            self.assertEqual(len(boundary['independent_holdouts']), 3)
            self.assertTrue(all('record_ref' not in point for point in boundary['native_points']))
            self.assertIn('5.01 with eleven depths', page)
            grid = public['measured_boundary_grid']
            self.assertEqual(grid['measured_scope']['original_unresolved_mass'], 1.)
            self.assertEqual(len(grid['captured_points']), 81)
            self.assertEqual(len(grid['independent_single_pulse_controls']), 9)
            self.assertEqual(len(grid['independent_overlap_controls']), 2)
            self.assertTrue(all('record_ref' not in point for point in grid['captured_points']))
            self.assertIn('three of six component', page)
            cause = public['boundary_grid_causes']
            self.assertEqual(cause['input_sha256']['original_comparison'], display.SOURCES['boundary_grid'][1])
            self.assertEqual(len(cause['controls']), 11)
            self.assertIn('25.07 and 27.20 ADC codes RMS', page)
            depth = public['boundary_depth_refinement']
            self.assertEqual(depth['capture_counts'], {'new_points': 198, 'reused_center_points': 33, 'reused_fit_points': 72})
            self.assertEqual(depth['coarse_fitter_parity']['maximum_absolute_serialized_numeric_delta'], 0.)
            self.assertEqual(len(depth['independent_fresh_interior_controls']), 6)
            self.assertIn('two of six component positions worsen', page)
            overlap = public['boundary_overlap_validation']
            self.assertEqual(len(overlap['conditions']), 24)
            self.assertEqual(overlap['design']['physical_layout_count'], 2)
            self.assertEqual(overlap['fit_status_by_method']['coarse_three_depth'],
                             {'optimizer_unconverged': 1, 'scored': 23})
            self.assertEqual(overlap['fit_status_by_method']['refined_eleven_depth'], {'scored': 24})
            self.assertIsNone(overlap['source_position_mm'])
            self.assertIn('10 of 69 component positions worsen', page)
            self.assertNotIn('specified but have not run', page)
            self.assertTrue((site / display.ENERGY_IMAGE).is_file())
            ids = re.findall(r'id="(trigger-[0-9]+)"', page)
            self.assertEqual(len(ids), len(set(ids)))
            self.assertIn('trigger-12841', ids)
            self.assertTrue(set(re.findall(r'href="#(trigger-[0-9]+)"', page)) <= set(ids))
            self.assertTrue((site / display.IMAGE).is_file())


if __name__ == '__main__':
    unittest.main()
