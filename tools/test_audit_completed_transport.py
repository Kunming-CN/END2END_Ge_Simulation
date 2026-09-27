"""Integrity guards on disposable fixtures, no simulation."""
import gzip, hashlib, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import h5py
import audit_completed_transport as a
import long_transport as lt
from test_long_transport import raw_fixture, fake_events
class AuditTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory(dir=lt.ROOT/'.local/million-analysis',prefix='audit-test-'); self.d=Path(self.t.name)
    def tearDown(self): self.t.cleanup()
    def fixture(self):
        raw=self.d/'raw.lh5'; meta=raw_fixture(raw); out=self.d/'compact.h5'
        with patch.object(lt.cs,'iter_decays',fake_events): counts=lt.compact(raw,meta,out,100)
        return out,counts,dict(model='AK02',count=2,start=100)
    def test_archive_roundtrip_and_corruption(self):
        body=b'original-transport-data'*100; p=self.d/'raw.gz'; p.write_bytes(gzip.compress(body))
        before=a.fingerprint(p); h=hashlib.sha256(body).hexdigest()
        self.assertEqual(a.archive_check(p,h,len(body)),len(body)); self.assertEqual(a.fingerprint(p),before)
        with self.assertRaises(ValueError): a.archive_check(p,'0'*64,len(body))
        p.write_bytes(p.read_bytes()[:-8])
        with self.assertRaises((EOFError,OSError)): a.archive_check(p,h,len(body))
    def test_compact_valid_and_bad_id(self):
        out,c,r=self.fixture(); self.assertEqual(a.compact_check(out,r,c)[0],1)
        with h5py.File(out,'r+') as f:f['events/global_decay_id'][1]=100
        with self.assertRaisesRegex(ValueError,'Global'):a.compact_check(out,r,c)
    def test_energy_sum_and_zero_census(self):
        out,c,r=self.fixture()
        with h5py.File(out,'r+') as f:f['events/ge_energy_keV'][0]=11
        with self.assertRaisesRegex(ValueError,'Step/scalar'):a.compact_check(out,r,c)
    def test_no_overwrite_and_escape(self):
        with self.assertRaisesRegex(ValueError,'exists'):a.audit(lt.ROOT/'.local/cs137-1m',self.d)
        with self.assertRaisesRegex(ValueError,'below project'):a.audit(lt.ROOT/'.local/cs137-1m',lt.ROOT/'bad-output')
if __name__=='__main__': unittest.main(verbosity=2)
