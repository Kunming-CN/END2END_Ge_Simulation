"""Reference handling and ADC binding for the two-strip waveform-fit runner."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

import gegi_digital_readout as digital
import gegi_joint_calibration as calibration
import gegi_joint_acquisition_study as study
import gegi_joint_two_site_study as design
import gegi_two_site_cfd_study as checks
from gegi_joint_two_site import Template


IDENTITY = {'model_sha256': 'a' * 64, 'field_cache_sha256': 'b' * 64, 'field_precision_bits': 32,
            'digital_profile_sha256': digital.PROFILE_SHA256, 'digital_timing_sha256': digital.TIMING_SHA256}
CHANNELS = [{'id': cid, 'family': 'X' if cid <= 17 else 'Y', 'guard': cid in (17, 34),
             'strip_center_mm': 5. * ((cid - 1) % 17) if cid not in (17, 34) else None}
            for cid in digital.CONTACT_IDS]
SCALES = {'fast': 1.6, 'centered_cfd': 2.2, 'pair_cfd': 3.3}


class AcquisitionFitTests(unittest.TestCase):
    def setUp(self):
        folder = Path(self.enterContext(tempfile.TemporaryDirectory(dir=Path(__file__).parent)))
        self.report = folder / 'report.json'
        self.windows = folder / 'two-strip-adc.npz'
        self.report_sha = self.write(self.report, {
            'counts': {'qualified_triggers': 1}, 'sources': [{'original': IDENTITY}],
            'receipt': {**IDENTITY, 'known_component_adc_sha256': 'clock'},
            'triggers': [{'trigger_time_ns': 120., 'two_strip_pairings': {
                'flags': [], 'collectors': [], 'pairings': [{
                    'index': 0, 'energy_compatible': True, 'compton_orders': [],
                    'sites': [{'x_contact_id': 1, 'y_contact_id': 18}, {'x_contact_id': 2, 'y_contact_id': 19}],
                }],
            }}],
        })
        self.write_windows('clock')
        self.reference = folder / 'reference.json'
        self.truth = {'adc_sha256': 'clock', 'qualified_trigger_denominator': 1,
                      'candidates': [{'trigger_time_ns': 120., 'deposit_groups': ['sealed_group'], 'comparison': None}]}
        self.truth_sha = self.write(self.reference, self.truth)

        inputs = self.enterContext(patch.object(checks.scan, 'Inputs')).return_value
        inputs.hashes = {}
        banks = {
            checks.CURVES: {'provenance': IDENTITY},
            design.SCALES: {'controls': {'group_rms_scales': SCALES}},
            checks.scan.FULL / 'COMPLETE.json': {'request_sha256': 'bank'},
            checks.scan.FULL / 'bound-request.json': {'channels': CHANNELS},
            self.reference: self.truth,
        }

        def read(path, digest):
            inputs.hashes[path.name] = digest
            return banks[path]

        inputs.read.side_effect = read
        self.read = inputs.read
        self.enterContext(patch.object(design, 'load_templates', return_value={}))
        self.fit = self.enterContext(patch.object(calibration, 'fit_pairing', return_value={'status': 'fitted'}))

    @staticmethod
    def write(path, result):
        data = study.encoded(result)
        path.write_bytes(data)
        return study.sha(data)

    def write_windows(self, adc_sha):
        np.savez(self.windows, report_sha256=self.report_sha, known_component_adc_sha256=adc_sha,
                 relative_time_ns=calibration.SAMPLE_NS, contact_ids=digital.CONTACT_IDS, trigger_time_ns=[120.],
                 two_strip_ordinal=[1], adc_codes=np.full((1, 34, len(calibration.SAMPLE_NS)), 3, dtype=np.int16),
                 volts_per_code=digital._LSB_V, window_status=['captured'],
                 digital_profile_sha256=digital.PROFILE_SHA256, digital_timing_sha256=digital.TIMING_SHA256)

    def test_same_fit_without_reading_transport_reference(self):
        result = study.run(report_path=self.report, windows_path=self.windows, reference_path=None)
        self.assertNotIn(self.reference, [call.args[0] for call in self.read.call_args_list])
        self.assertEqual(result['summary'], {})
        self.assertEqual(result['qualified_triggers'], 1)
        self.assertEqual(result['acquisition_sha256'], self.report_sha)
        self.assertEqual(result['adc_windows_sha256'], study.sha(self.windows.read_bytes()))
        np.testing.assert_array_equal(self.fit.call_args.kwargs['local_adc_volts'],
                                      np.full((34, len(calibration.SAMPLE_NS)), 3 * digital._LSB_V))
        candidate, = result['candidates']
        self.assertNotIn('reference_groups', candidate)
        self.assertNotIn('score', candidate['pairings'][0])

        scored = study.run(report_path=self.report, windows_path=self.windows, reference_path=self.reference)
        self.read.assert_any_call(self.reference, self.truth_sha)
        reference, = scored['candidates']
        self.assertEqual(reference['reference_groups'], ['sealed_group'])
        self.assertIsNone(reference['pairings'][0]['score'])
        self.assertEqual(candidate['pairings'][0]['fit'], reference['pairings'][0]['fit'])

    def test_windows_must_belong_to_the_report_in_measured_mode(self):
        self.write_windows('other_acquisition')
        with self.assertRaisesRegex(ValueError, 'ADC windows, channel order, or acquisition identity differ'):
            study.run(report_path=self.report, windows_path=self.windows, reference_path=None)
        self.fit.assert_not_called()

    def make_calibration(self, identity=IDENTITY):
        path = self.report.with_name('calibration.npz')
        centers = np.linspace(-1e-5, 1e-5, np.prod(calibration.TEMPLATE_SHAPE)).reshape(calibration.TEMPLATE_SHAPE)
        template = Template((1, 18), (0., 0.), 5., centers)
        _, content_sha = calibration.save(path, identity=identity, channels=CHANNELS, scales=SCALES,
                                          requested={(1, 18), (2, 19)}, templates={(1, 18): template}, provenance={})
        return path, content_sha, centers

    def test_portable_fit_uses_bundle_only_and_retains_uncovered_cells(self):
        path, content_sha, centers = self.make_calibration()
        self.read.side_effect = AssertionError('Portable fit cannot open the research bank')
        result = study.run(report_path=self.report, windows_path=self.windows, reference_path=None, calibration_path=path)
        self.read.assert_not_called()
        templates, scales = self.fit.call_args.args[-2:]
        self.assertEqual(scales, SCALES)
        np.testing.assert_array_equal(templates[1, 18].center_v_per_keV, centers)
        bundle = result['calibration_bundle']
        self.assertEqual(bundle['archive_sha256'], study.sha(path.read_bytes()))
        self.assertEqual(bundle['content_sha256'], content_sha)
        self.assertEqual(bundle['calibrated_cells'], [(1, 18)])
        self.assertEqual(bundle['missing_cells'], [(2, 19)])

    def test_portable_fit_rejects_a_different_field(self):
        path, _, _ = self.make_calibration({**IDENTITY, 'field_precision_bits': 64})
        with self.assertRaisesRegex(ValueError, 'must share detector fields'):
            study.run(report_path=self.report, windows_path=self.windows, reference_path=None, calibration_path=path)
        self.fit.assert_not_called()

    def test_center_bytes_are_bound_to_the_bundle_manifest(self):
        path, _, _ = self.make_calibration()
        with np.load(path, allow_pickle=False) as archive:
            manifest = archive['manifest_utf8']
            volts = archive['center_v_per_keV']
        volts[0, 0, 0, 0] = 0.
        np.savez_compressed(path, manifest_utf8=manifest, center_v_per_keV=volts)
        with self.assertRaisesRegex(ValueError, 'template samples or their hash differ'):
            calibration.load(path)


if __name__ == '__main__':
    unittest.main()
