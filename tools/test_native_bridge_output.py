"""Mutation tests on disposable copies of the completed pilot; no recomputation."""
import json,shutil,tempfile,unittest
from pathlib import Path
import verify_native_bridge_output as V
R=V.R
class OutputChecks(unittest.TestCase):
    def clone(self):
        temp=tempfile.TemporaryDirectory(prefix='output-test-',dir=R.ROOT/'.local/native-bridge-pilot')
        self.addCleanup(temp.cleanup); target=Path(temp.name)/'pilot'
        shutil.copytree(R.ROOT/'.local/native-bridge-pilot/pilot-v2',target)
        return target
    def test_actual_completed_inventory(self):
        self.assertEqual(V.verify(R.ROOT/'.local/native-bridge-pilot/pilot-v2')['status'],'passed')
    def test_missing_manifest_entry_rejected(self):
        target=self.clone(); f=target/'AK02/run.json'; report=R.read(f)
        del report['artifacts']['input-contract.json'];f.write_text(json.dumps(report))
        with self.assertRaisesRegex(ValueError,'inventory'):V.verify(target)
    def test_rehashed_failure_truth_rejected(self):
        target=self.clone(); base=target/'AK02'; f=base/'cs10000-v2-diagnostic/native-failures.jsonl'
        row=next(R.records(f));row['original_event']['ge_energy_keV']+=1
        f.write_text(json.dumps(row)+'\n');report=R.read(base/'run.json')
        name=next(n for n in report['artifacts'] if Path(n).as_posix()=='cs10000-v2-diagnostic/native-failures.jsonl')
        report['artifacts'][name]=R.sha(f);(base/'run.json').write_text(json.dumps(report))
        with self.assertRaisesRegex(ValueError,'truth'):V.verify(target)
    def test_contract_binding_rejected(self):
        target=self.clone(); f=target/'input-export.json'; receipt=R.read(f)
        receipt['contracts']['AK02']['sha256']='0'*64;f.write_text(json.dumps(receipt))
        with self.assertRaisesRegex(ValueError,'binding'):V.verify(target)
if __name__=='__main__':unittest.main(verbosity=2)
