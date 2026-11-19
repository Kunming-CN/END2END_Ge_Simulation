import json
from pathlib import Path
import tempfile
import unittest

from gegi_event_store import encoded, sha
import gegi_refit_positions as positions


class RefitTests(unittest.TestCase):
    def test_unconfirmed_field_preserves_measurements_and_source_file(self):
        geometry = [dict(id=i, family='X' if i <= 17 else 'Y', guard=i in (17, 34),
                         strip_center_mm=None if i in (17, 34) else 5. * ((i-1) % 17 - 7.5))
                    for i in range(1, 35)]
        faces = {axis: dict(contact_id=cid, slow_energy_keV=35., preamp_cfd50_ns=None, low=None, high=None)
                 for axis, cid in [('x', 1), ('y', 18)]}
        row = dict(single_pixel_energy_keV=35., single_pixel_features=faces, trigger_time_ns=200.)
        report = dict(kind=positions.acquisition.KIND, status='completed', sources=[
            dict(original={'model_sha256': 'unknown', 'geometry_sha256': 'test'},
                 input_directory={'relative_to_report_directory': None})],
                      counts={'single_pixel_energies': 1}, spectra={}, triggers=[row],
                      exposure={'excluded_intervals_ns': []}, design={'nominal_position': {}},
                      receipt={'digital_profile_sha256': 'profile', 'digital_timing_sha256': 'timing'})
        report['receipt']['observed_result_sha256'] = sha(encoded(dict(counts=report['counts'], spectra={},
                                                                       triggers=[row], mask=[])))
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            src, out, donor = (folder/name for name in ('original.json', 'new.json', 'geometry.json'))
            src.write_bytes(encoded(report))
            donor.write_bytes(encoded(dict(sources=report['sources'], design={'nominal_position': {'channel_geometry': geometry}})))
            original = src.read_bytes()
            derived = positions.refit(src, out, geometry_report=donor)
            self.assertEqual(src.read_bytes(), original)
            self.assertEqual(json.loads(out.read_bytes()), derived)
            self.assertEqual(derived['triggers'][0]['nominal_position']['status'], 'unconfirmed_field')
            self.assertEqual(derived['triggers'][0]['single_pixel_features'], faces)
            receipt = derived['receipt']['position_reprocessing']
            self.assertEqual(receipt['source_report_sha256'], sha(original))
            self.assertEqual(receipt['geometry_source_report_sha256'], sha(donor.read_bytes()))
            self.assertEqual(receipt['new_adc_samples'], 0)
            with self.assertRaises(FileExistsError):
                positions.refit(src, out, geometry_report=donor)


if __name__ == '__main__':
    unittest.main()
