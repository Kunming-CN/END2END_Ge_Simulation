"""Focused tests for byte/inventory tamper after successful saved inspection."""
import json
from pathlib import Path
import tempfile
import unittest
import scenario_workflow as W
from saved_terminal import Verifier

class SavedTerminalTests(unittest.TestCase):
    def test_reuse_and_tamper(self):
        with tempfile.TemporaryDirectory() as root:
            directory=Path(root)/'.local/runs/example';directory.mkdir(parents=True)
            W.write(directory/'resolved-config.json',{'configuration':'original'},fresh=True)
            W.write(directory/'run.json',{'status':'completed'},fresh=True)
            W.write(directory/'result.json',{'value':-0.0},fresh=True)
            W.write(directory/'COMPLETE.json',{'artifacts':W.inventory(directory)},fresh=True)
            calls=[]
            def inspect(name,base):
                calls.append(name);return {'status':'completed','verification':'terminal_artifacts_verified','original_source':'old'}
            verifier=Verifier(root,inspect)
            self.assertEqual(verifier.inspect('example')['original_source'],'old')
            self.assertEqual(verifier.inspect('example')['original_source'],'old')
            self.assertEqual(len(calls),1)
            W.write(directory/'result.json',{'value':0.0})
            with self.assertRaises(Exception):verifier.inspect('example')
            W.write(directory/'COMPLETE.json',{'artifacts':W.inventory(directory,exclude=('COMPLETE.json',))})
            with self.assertRaises(Exception):verifier.inspect('example')
            self.assertEqual(len(calls),1)

    def test_new_file_and_deleted_file_refused(self):
        for mode in ('new','deleted'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as root:
                directory=Path(root)/'.local/runs/example';directory.mkdir(parents=True)
                for name in ('resolved-config.json','run.json'):W.write(directory/name,{'v':1},fresh=True)
                W.write(directory/'COMPLETE.json',{'artifacts':W.inventory(directory)},fresh=True)
                v=Verifier(root,lambda *_:{'status':'completed','verification':'terminal_artifacts_verified'})
                v.inspect('example')
                if mode=='new':(directory/'extra').write_bytes(b'new')
                else:(directory/'run.json').unlink()
                with self.assertRaises(Exception):v.inspect('example')

if __name__=='__main__':unittest.main()
