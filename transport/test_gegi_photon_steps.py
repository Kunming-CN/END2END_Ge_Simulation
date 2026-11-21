"""Check the versioned optional observer format and child-only selection."""

import csv
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import gegi_photon_steps as observer


class PhotonStepSidecarTests(unittest.TestCase):
    def test_preserves_explicit_kinetics_and_nullable_volume(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'steps.csv'
            pre = [1332.4980931528798, -3.1, 1.1, 2., 1., 0., 0., .1234, .12, 'Ge,"active"', 2, 7]
            post = [645.0490483119831, -2.1, 1.1, 2., 0., 1., 0., .1267, .123, '', -1, 4]
            with path.open('w', newline='', encoding='utf-8') as stream:
                stream.write(f'# {observer.KIND}\n')
                writer = csv.writer(stream)
                writer.writerow(observer.HEADER)
                writer.writerow([0, 5318, 6, 1, 2, 'compt', 2, 13, 'RadioactiveDecay', 0, 0., 0., *pre, *post])
            step, = observer.photon_steps(path)
        self.assertEqual((step['run_id'], step['event_id'], step['track_id'], step['step_number']), (0, 5318, 6, 2))
        self.assertEqual(step['process'], 'compt')
        self.assertEqual(step['pre']['kinetic_keV'], pre[0])
        self.assertEqual(step['post']['kinetic_keV'], post[0])
        self.assertEqual(step['pre']['physical_volume'], pre[9])
        self.assertEqual(step['pre']['copy_number'], 2)
        self.assertIsNone(step['post']['physical_volume'])
        self.assertIsNone(step['post']['copy_number'])
        self.assertEqual(step['post']['direction'], [0., 1., 0.])

    def test_rejects_incomplete_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'steps.csv'
            content = f'# {observer.KIND}\n' + ','.join(observer.HEADER) + '\n0,12,3\n'
            path.write_text(content, encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Incomplete photon-step row'):
                list(observer.photon_steps(path))

    def test_configuration_of_child_output(self):
        with patch.dict(observer.os.environ, {'GEGI_PHOTON_STEP_EVENTS': '8'}):
            regular = observer.observer_environment('steps.csv')
            selected = observer.observer_environment('steps.csv', local_event_ids=[5, 2, 5])
            self.assertEqual(observer.os.environ['GEGI_PHOTON_STEP_EVENTS'], '8')
        self.assertEqual(regular['GEGI_PHOTON_STEP_OUTPUT'], 'steps.csv')
        self.assertNotIn('GEGI_PHOTON_STEP_EVENTS', regular)
        self.assertEqual(selected['GEGI_PHOTON_STEP_EVENTS'], '2,5')

    def test_original_chords_bind_time_parent_and_transport_identity(self):
        position = [0., 1., 2.]
        scored = dict(raw_row_index=9, track_id=4, parent_track_id=2, time_ns=3., edep_keV=0.,
                      pre_position_mm=position, post_position_mm=position)
        truth = dict(ge_gamma_steps=[scored], track_births=[])
        one = dict(run_id=0, event_id=5, track_id=4, parent_track_id=2, step_number=3, step_edep_keV=0.,
                   process='compt', pre={'global_time_ns': 3., 'position_mm': position, 'physical_volume': 'germanium'},
                   post={'position_mm': position, 'kinetic_keV': 350.})
        other = dict(one, step_number=4, pre=dict(one['pre'], global_time_ns=3.1))
        result = observer.observe_ge_chords(truth, 5, [one, other])
        self.assertEqual(result['photon_step_observation_status'], 'observed_exact')
        self.assertEqual(result['ge_gamma_steps'], [dict(scored, observed_transport_step=one)])
        self.assertEqual(truth['ge_gamma_steps'], [scored])
        with self.assertRaisesRegex(ValueError, 'no unique observed step'):
            observer.observe_ge_chords(truth, 5, [other])
        with self.assertRaisesRegex(ValueError, 'different original transport event'):
            observer.observe_ge_chords(truth, 6, [one])


if __name__ == '__main__':
    unittest.main()
