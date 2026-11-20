"""Mock the cross-platform launcher boundary; never start transport."""
from contextlib import redirect_stdout
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import gegi_mixed_acquisition as acquisition
sys.path.insert(0, str(acquisition.ROOT/'transport'))
import gegi_mixed_source as source


class MixedTransportCLI(unittest.TestCase):
    def test_source_cli_accepts_both_launcher_root_flags(self):
        for flag, root in (('--windows-root', 'C:/student/project'), ('--project-root', '/Users/student/project')):
            with self.subTest(flag=flag), patch.object(source.S.P, 'project_identity') as identity, redirect_stdout(io.StringIO()):
                source.main(['default-config', flag, root])
                identity.assert_called_once_with(root)

    def test_transport_call_preserves_argv_for_windows_and_macos(self):
        for platform, root_flag in (('win32', '--windows-root'), ('darwin', '--project-root')):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as temp, \
                    patch.object(acquisition.W.sys, 'platform', platform), \
                    patch.object(acquisition.subprocess, 'run') as run:
                run.return_value.returncode = 0
                arguments = ['prepare', '--config', '../.local/my run/source-config.json',
                             '--output', '../.local/my run/transport']
                acquisition.transport_call(arguments, Path(temp)/'transport.log')
                command = run.call_args.args[0]
                self.assertIn('./gegi_mixed_source.py', command)
                self.assertIn('../.local/my run/source-config.json', command)
                self.assertEqual(command[-2:], [root_flag, str(acquisition.ROOT.resolve())])
                self.assertEqual(run.call_args.kwargs['shell'], False)
                if platform == 'darwin': self.assertEqual(command[:2], ['/bin/bash', '-c'])
                else: self.assertEqual(command[0], 'wsl.exe')


if __name__ == '__main__': unittest.main()
