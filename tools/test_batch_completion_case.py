"""Windows descriptor/completion regression, using the source-frozen fix consumer."""
import hashlib,importlib.util,unittest
from unittest.mock import patch
import scenario_workflow as W
import test_batch_execution as F

class CompletionCase(unittest.TestCase):
    def test_batch_descriptor_and_completion_have_distinct_names(self):
        original=W.ROOT/'tools/batch_execution.py'
        before=original.read_bytes();pending=b'BATCH.json' in before
        corrected=W.ROOT/'.local/student-batches-v1/execution-v1/corrected-controller.py' if pending else original
        fixed=corrected.read_bytes()
        self.assertEqual(fixed,before.replace(b'BATCH.json',b'batch-complete.json'))
        spec=importlib.util.spec_from_file_location('batch_completion_fix_consumer',corrected)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with patch.object(F,'E',module):
            fixture=F.Execution(methodName='test_partition_exact_defaults_and_acceptance_cap');fixture.setUp()
            try:
                def worker(stage,plan,directory,batch,root):
                    if stage=='radiation':
                        W.write(module.batch_directory(directory,batch['batch_index'])/'batch.json',batch,fresh=True)
                    return fixture.worker(stage,plan,directory,batch,root)
                receipt=fixture.execute(worker=worker)
                self.assertEqual(receipt['completed_primary_count'],3)
                for batch in module.iter_batches(fixture.plan['resolved']['batching']):
                    base=module.batch_directory(fixture.directory,batch['batch_index'])
                    self.assertEqual(W.read(base/'batch.json'),batch)
                    self.assertEqual(W.read(base/'batch-complete.json')['kind'],'batch_complete_v1')
                    self.assertNotEqual(str(base/'batch.json').casefold(),str(base/'batch-complete.json').casefold())
                    relative=(base/'batch-complete.json').relative_to(fixture.directory).as_posix()
                    self.assertEqual(module.artifact('fixture',relative,fixture.root),base/'batch-complete.json')
                module.inspect('fixture',fixture.root)
                calls=list(fixture.calls);fixture.execute(resume=True,worker=worker)
                self.assertEqual(fixture.calls,calls)
            finally:fixture.doCleanups()
        self.assertEqual(original.read_bytes(),before)
        if pending:
            receipt=W.read(W.ROOT/'.local/student-batches-v1/execution-v1/CONTROLLER-FIX.json')
            self.assertEqual(receipt['original_sha256'],hashlib.sha256(before).hexdigest())
            self.assertEqual(receipt['corrected_sha256'],hashlib.sha256(fixed).hexdigest())

if __name__=='__main__':unittest.main()
