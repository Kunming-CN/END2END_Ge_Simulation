import json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import native_response_launcher as L
class Child:
    pid=1234
    def __init__(self,code):self.code=code
    def wait(self):return self.code
class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='launcher-unit-',dir=L.ROOT/'.local/native-response-fix')
        self.path=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def test_exclusive_lock(self):
        file=self.path/'lock';handle=L.take_lock(file)
        try:
            with self.assertRaises(RuntimeError):L.take_lock(file)
        finally:L.release(handle)
        handle=L.take_lock(file);L.release(handle)
    def test_worker_numeric_receipt(self):
        L.save(self.path/'progress.json',{'status':'paused'})
        with patch.object(L.subprocess,'Popen',return_value=Child(0)),patch.object(L,'reconcile') as finalizer:
            self.assertEqual(L.worker(self.path,1),0)
            finalizer.assert_called_once_with(self.path,'paused',0)
        receipt=json.loads(next((self.path/'logs').glob('*.exit.json')).read_text())
        self.assertEqual(receipt['exit_code'],0)
        self.assertEqual(receipt['status'],'paused')
    def test_missing_terminal_not_success(self):
        with patch.object(L.subprocess,'Popen',return_value=Child(0)),patch.object(L,'reconcile'):
            self.assertEqual(L.worker(self.path,None),1)
    def test_child_failure_retained(self):
        with patch.object(L.subprocess,'Popen',return_value=Child(2)),patch.object(L,'reconcile'):
            self.assertEqual(L.worker(self.path,None),2)
    def test_complete_start_does_not_launch(self):
        L.save(self.path/'COMPLETE.json',{'status':'completed'})
        with patch.object(L.subprocess,'Popen') as child:
            L.start(self.path);child.assert_not_called()
    def test_unprepared_path_rejected(self):
        with self.assertRaises(ValueError):L.checked(self.path)
if __name__=='__main__':unittest.main(verbosity=2)
