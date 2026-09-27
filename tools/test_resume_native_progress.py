"""Synthetic display/launcher tests. Never starts or changes a scientific job."""
import contextlib, io, json, tempfile, unittest
from pathlib import Path
from unittest.mock import Mock, patch
import resume_native_progress as R
class Tests(unittest.TestCase):
    def test_metadata_failure_still_waits(self):
        child=Mock();child.wait.return_value=0
        with patch.object(R,'display_json',side_effect=OSError(28,'disk full')),contextlib.redirect_stderr(io.StringIO()):
            code,error=R.wait_with_display(child,Path('synthetic'),{})
        self.assertEqual(code,0);self.assertIn('disk full',error);child.wait.assert_called_once()
    def test_normal_child_exit(self):
        child=Mock();child.wait.return_value=7
        with patch.object(R,'display_json',return_value=True):
            self.assertEqual(R.wait_with_display(child,Path('synthetic'),{}),(7,None))
        child.wait.assert_called_once()
    def test_bounded_display_permission_retry(self):
        error=PermissionError('sharing');error.winerror=32
        with patch.object(R.old,'save',side_effect=error) as writer,patch.object(R.time,'sleep'),contextlib.redirect_stderr(io.StringIO()):
            self.assertFalse(R.display_json(Path('synthetic'),{}))
            self.assertEqual(writer.call_count,3)
    def test_unrelated_display_error_is_not_hidden(self):
        with patch.object(R.old,'save',side_effect=ValueError('invalid JSON')):
            with self.assertRaises(ValueError):R.display_json(Path('synthetic'),{})
    def test_extension_is_immutable(self):
        base=R.ROOT/'.local/native-progress-recovery'
        with tempfile.TemporaryDirectory(dir=base,prefix='launcher-test-') as tmp:
            d=Path(tmp);(d/'config.json').write_text('{}')
            expected=R.bind(d);before=(d/'progress-recovery.json').read_bytes()
            self.assertEqual(R.bind(d),expected)
            self.assertEqual((d/'progress-recovery.json').read_bytes(),before)
            (d/'config.json').write_text('{"modified":true}')
            with self.assertRaises(ValueError):R.bind(d)
if __name__=='__main__':unittest.main(verbosity=2)
