"""Source-blind selection, mass accounting, and plane conventions."""

from copy import deepcopy
from contextlib import redirect_stdout
import gzip
import io
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from gegi_continuous_plane import main, reconstruct
from gegi_imaging import ELECTRON_REST_KEV


def sample(pairs):
    measured, fitted = [], []
    for index, (cells, energies, orders, positions) in enumerate(pairs):
        sites = [dict(x_contact_id=x, y_contact_id=y, energy_keV=energy)
                 for (x, y), energy in zip(cells, energies, strict=True)]
        measured.append(dict(index=index, energy_compatible=True, sites=sites,
                             compton_orders=[dict(site_index_order=order, kinematically_allowed=True)
                                             for order in orders]))
        fit = {'fits': {'waveform': {'center': {'positions_mm': positions, 'optimizer_success': True}}}} if positions else {}
        fitted.append(dict(index=index, cells=cells, energy_compatible=True, fit=fit))
    trigger = dict(trigger_time_ns=120., energy_keV=sum(pairs[0][1]), two_strip_pairings=dict(pairings=measured))
    exposure = dict(clock_live_time_ns=250_000_000., qualified_adc_live_time_ns=228_000_000.)
    acquisition = dict(counts=dict(qualified_triggers=2, qualified_energies=1), exposure=exposure,
                       triggers=[dict(energy_keV=None, trigger_time_ns=40.), trigger])
    fit = dict(two_strip_triggers=1, candidates=[dict(ordinal=1, time_ns=120., pairings=fitted)])
    return acquisition, fit


class ContinuousPlaneTests(unittest.TestCase):
    def test_extra_source_and_truth_fields_do_not_change_image_or_ledger(self):
        acquisitions = sample([
            ([[10, 26], [11, 27]], [417., 245.], [[0, 1], [1, 0]], [[-7., 7., 1.], [1., 14., 2.]]),
            ([[10, 27], [11, 26]], [407., 255.], [[0, 1], [1, 0]], None),
        ])
        first = reconstruct(*acquisitions, z_mm=40., extent_mm=24., step_mm=4.)
        acquisition, fit = deepcopy(acquisitions)
        acquisition['sources'] = [dict(key='unused', original=dict(source_position_mm=[-1000., 100., 2.]))]
        acquisition['triggers'][1].update(truth_order=[1, 0], source_mm=[90., 0., 90.])
        fit['summary'] = {'target_source_peak': [12., -5.]}
        row = fit['candidates'][0]
        row.update(reference_groups=[{'source': 'elsewhere'}], truth_order=[1, 0])
        for pair in row['pairings']:
            pair['score'] = {'closest_source_order': [1, 0], 'angle_error_deg': 999.}
            pair['compton_orders'] = [{'site_index_order': [1, 0], 'kinematically_allowed': False}]
            pair['fit'].get('fits', {}).get('waveform', {}).get('center', {})['weighted_residual_rms'] = 900.
        second = reconstruct(acquisition, fit, z_mm=40., extent_mm=24., step_mm=4.)
        self.assertEqual(first, second)
        layer = first['layers']['661.657_keV']
        self.assertEqual((layer['triggers'], layer['allowed_hypotheses'], layer['hypotheses']), (1, 4, 2))
        self.assertEqual((layer['projected_mass'], layer['unresolved_mass']), (.5, .5))
        self.assertAlmostEqual(np.sum(layer['mass']), .5)
        self.assertEqual(first['layers']['all']['mass'], layer['mass'])
        orders = [order for pair in first['triggers'][0]['pairings'] for order in pair['orders']]
        self.assertEqual([o['status'] for o in orders], ['projected', 'projected', 'no_waveform_fit', 'no_waveform_fit'])
        self.assertEqual([o['nominal_mass'] for o in orders], [.25]*4)

    def test_plane_orientation_and_mass_on_positive_z(self):
        total = 300.
        absorbed = 1/(1/total + (1-math.cos(math.pi/4))/ELECTRON_REST_KEV)
        acquisition, fit = sample([
            ([[10, 26], [11, 27]], [total-absorbed, absorbed], [[0, 1]], [[3., 1., 0.], [3., 1., -12.]]),
        ])
        result = reconstruct(acquisition, fit, z_mm=10., extent_mm=24., step_mm=2.)
        grid = result['grid']
        self.assertEqual((grid['assumed_z_mm'], grid['x_mm'][0], grid['y_mm'][-1]), (10., -23., 23.))
        order, = result['triggers'][0]['pairings'][0]['orders']
        self.assertEqual(order['axis'], [0., 0., 1.])
        self.assertAlmostEqual(order['half_angle_deg'], 45.)
        mass = np.asarray(result['layers']['other_energy']['mass'])
        self.assertEqual(mass.shape, (24, 24))
        at = lambda x, y: mass[grid['y_mm'].index(y), grid['x_mm'].index(x)]
        self.assertAlmostEqual(at(3., 11.), at(3., -9.))
        self.assertGreater(at(3., 11.), at(3., 1.))
        self.assertGreater(at(3., 11.), at(11., 3.))
        self.assertAlmostEqual(mass.sum(), 1.)

    def test_empty_two_strip_selection_has_empty_layers(self):
        exposure = dict(clock_live_time_ns=250_000_000., qualified_adc_live_time_ns=228_000_000.)
        acquisition = dict(counts=dict(qualified_triggers=1, qualified_energies=0), exposure=exposure,
                           triggers=[dict(energy_keV=None)])
        result = reconstruct(acquisition, dict(two_strip_triggers=0, candidates=[]), z_mm=40., extent_mm=4., step_mm=4.)
        self.assertEqual(result['selection']['qualified_triggers'], 1)
        self.assertEqual(result['triggers'], [])
        for layer in result['layers'].values():
            self.assertEqual(layer['triggers'], 0)
            self.assertEqual(layer['mass'], [[0., 0.], [0., 0.]])

    def test_portable_invocation_uses_and_writes_siblings(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            report, windows, calibration, output = (folder/name for name in
                ('report.json', 'two-strip-adc.npz', 'gegi-center-calibration.npz', 'plane.json.gz'))
            windows.touch()
            result = dict(layers={'all': dict(triggers=1, hypotheses=1, mass=[[1.]])})
            argv = ['gegi_continuous_plane.py', '--acquisition', str(report), '--calibration', str(calibration),
                    '--plane-z-mm', '40']
            with patch('sys.argv', argv), redirect_stdout(io.StringIO()), \
                    patch('gegi_continuous_plane.run_from_adc', return_value=result) as run:
                main()
            run.assert_called_once_with(report, windows, calibration, z_mm=40., extent_mm=120., step_mm=4., sigma_deg=5.)
            self.assertEqual(json.loads(gzip.decompress(output.read_bytes())), result)


if __name__ == '__main__':
    unittest.main()
