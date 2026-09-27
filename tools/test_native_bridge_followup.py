"""Additional rehashed-contract checks; no radiation or native response computation."""
import json,shutil,tempfile,unittest
from pathlib import Path
import native_hdf5_bridge as B

class RehashedContracts(unittest.TestCase):
    def mutate(self,change):
        with tempfile.TemporaryDirectory(prefix='followup-',dir=B.BASE) as folder:
            target=Path(folder)/'contracts'
            shutil.copytree(B.BASE/'contracts-v3',target)
            contract=B.read(target/'AK02.json');change(contract)
            (target/'AK02.json').write_text(json.dumps(contract),encoding='utf-8')
            receipt=B.read(target/'EXPORT.json')
            receipt['contracts']['AK02']['sha256']=B.sha(target/'AK02.json')
            (target/'EXPORT.json').write_text(json.dumps(receipt),encoding='utf-8')
            with self.assertRaises(ValueError): B.verify(target)
    def test_rehashed_units(self):
        self.mutate(lambda d:d['units'].__setitem__('energy','MeV'))
    def test_rehashed_prepared_metadata(self):
        self.mutate(lambda d:d['prepared'].__setitem__('clock_policy','unverified_clock'))
    def test_rehashed_prepared_geometry(self):
        self.mutate(lambda d:d['prepared']['coordinate_transform']['translation_global_mm'].__setitem__(0,1))

if __name__=='__main__':unittest.main(verbosity=2)
