import json
from pathlib import Path
import tempfile
import unittest

import gegi_candidate_run as run
import gegi_candidate_storage as storage
import gegi_digital_readout as digital
import gegi_exposure_stream as stream
import gegi_mixed_acquisition as mixed
from test_gegi_pulse_stream import prepare, pulse


class CandidateAcquisitionTest(unittest.TestCase):
    def test_retention_does_not_change_continuous_adc_or_energy_census(self):
        components = [(prepare(pulse((3, 24), energy=190.)), 2017., 1.),
                      (prepare(pulse((11, 26), energy=470.)), 2017., 1.),
                      (prepare(pulse((3, 24), energy=662.)), 6500., 1.)]
        # Geometry only supplies measured strip adjacency, not a true interaction.
        channels = [{'id': cid, 'family': 'X' if cid <= 17 else 'Y',
                     'guard': cid in (17, 34), 'strip_center_mm': float(cid % 17)}
                    for cid in digital.CONTACT_IDS]
        reference = stream.reconstruct_exposure(stream.ADCExposure(
            components, live_time_ns=12000., noise_seed=23), block_samples=11)
        with tempfile.TemporaryDirectory() as work:
            report = run.acquire(components, channels=channels, live_time_ns=12000., noise_seed=23,
                output=work, source_statistics={'initial_parents': 3}, identity={'scope': 'synthetic test'},
                block_samples=41)
            self.assertEqual(report['readout']['adc_sha256'], reference['adc_sha256'])
            self.assertEqual(report['counts']['qualified_triggers'], len(reference['events']))
            self.assertGreater(report['storage_counts']['saved_candidates'], 0)
            self.assertGreater(report['storage_counts']['rejected_rises'], 0)
            self.assertEqual(report['verification']['status'], 'verified_exact')
            self.assertEqual(run.read_summary(Path(work) / storage.ARCHIVE_NAME)
                             ['acquisition_statistics']['source']['initial_parents'], 3)
            self.assertFalse(report['retention']['full_adc_stream_saved'])
            self.assertEqual(sum(report['spectra']['combined']['counts']), report['counts']['qualified_energies'])

    def test_parent_and_daughter_times_rebased_once(self):
        source = {'absolute_parent_time_ns': 100., 'primary_time_ns': 100.,
                  'steps': [{'time_ns': 5., 'absolute_time_ns': 105.},
                            {'time_ns': 200000., 'absolute_time_ns': 200100.}],
                  'pulse_groups': [{'origin_time_ns': 5.}, {'origin_time_ns': 200000.}]}
        result = mixed.absolute_event(source)
        self.assertEqual([row['time_ns'] for row in result['steps']], [105., 200100.])
        self.assertEqual([row['origin_time_ns'] for row in result['pulse_groups']], [105., 200100.])
        self.assertEqual(source['steps'][0]['time_ns'], 5.)
        source['steps'][0]['absolute_time_ns'] = 106.
        with self.assertRaisesRegex(ValueError, 'absolute time'):
            mixed.absolute_event(source)

    def test_scratch_retirement_rejects_an_original_outside_new_run(self):
        with tempfile.TemporaryDirectory() as parent:
            parent = Path(parent)
            original = parent / 'original.dat'
            original.write_bytes(b'original scientific data')
            output = parent / 'new-run'
            output.mkdir()
            with self.assertRaisesRegex(ValueError, 'escaped'):
                mixed._retire_success_scratch(output, [original])
            self.assertEqual(original.read_bytes(), b'original scientific data')
            scratch = output / 'scratch.dat'
            scratch.write_bytes(b'temporary')
            self.assertEqual(mixed._retire_success_scratch(output, [scratch]), 9)
            self.assertFalse(scratch.exists())
            receipt = json.loads((output / 'scratch-retirement.json').read_text(encoding='utf-8'))
            self.assertEqual(receipt['bytes'], 9)


if __name__ == '__main__':
    unittest.main()
