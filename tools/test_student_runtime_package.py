"""Student ZIP acceptance: isolated Control imports, dependencies and tampering.

No installations, workers, browser downloads or physical calculations are run.
The temporary unpacked directory is owned by this test and removed on exit.
"""
import ast
import copy
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

import build_student_runtime as package


class StudentRuntimePackage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest, cls.bodies, cls.metadata, cls.modes = package.source(worktree=True)

    def temporary(self):
        parent = package.ROOT / '.local/student-runtime-p1'
        parent.mkdir(parents=True, exist_ok=True)
        return tempfile.TemporaryDirectory(prefix='acceptance-', dir=parent)

    def test_repeat_build_and_exact_member_contract(self):
        with self.temporary() as directory:
            first, second = Path(directory)/'first.zip', Path(directory)/'second.zip'
            for path in (first, second):
                package.write_archive(path, self.manifest, self.bodies, self.modes)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            receipt = package.verify(first, worktree=True)
            self.assertEqual(receipt['members'], len(self.bodies))
            self.assertFalse(receipt['release_eligible'])
            with zipfile.ZipFile(first) as bundle:
                names = bundle.namelist()
                self.assertFalse(any('/docs/' in p or '/test_' in p or '/.local/' in p for p in names))
                guide = bundle.read(self.manifest['archive_root'] + '/tools/site_guide.html').decode()
                self.assertNotIn('__PAGE_NAVIGATION__', guide)
                self.assertNotIn('id="advanced-routes"', guide)
                self.assertNotIn('href="#advanced-title"', guide)
                self.assertIn('id="setup"', guide)
                self.assertIn('id="saved-analysis"', guide)

    def test_frozen_probe_and_missing_dependency_are_rejected(self):
        for ref in ('transport/geometry_probe.cc', 'transport/scenario_transport.py', 'tools/nonzero_events.py'):
            bodies = dict(self.bodies); bodies[ref] += b'\n'
            with self.assertRaisesRegex(ValueError, 'frozen runtime source'):
                package.dependencies(self.manifest, bodies)
        bodies = dict(self.bodies); del bodies['simulation/readout.jl']
        with self.assertRaisesRegex(ValueError, 'Missing Julia include'):
            package.dependencies(self.manifest, bodies)
        bodies = dict(self.bodies); del bodies['tools/scenario_workflow.py']
        with self.assertRaisesRegex(ValueError, 'Missing local/undeclared Python import'):
            package.dependencies(self.manifest, bodies)

    def test_frozen_runtime_inventory_never_executes_python(self):
        source = ast.parse(self.bodies['transport/scenario_source_portable.py'].decode())
        pins = package.frozen_sources(source, 'source_inventory')
        self.assertEqual(pins['transport/scenario_transport.py'], package.sha(self.bodies['transport/scenario_transport.py']))
        self.assertEqual(pins['tools/nonzero_events.py'], package.sha(self.bodies['tools/nonzero_events.py']))
        dynamic = ast.parse('def source_inventory():\n    return subprocess.check_output(["not-a-command"])\n')
        with self.assertRaises(ValueError):
            package.frozen_sources(dynamic, 'source_inventory')

    def test_tampered_source_and_unlisted_members_are_rejected(self):
        for extra in (False, True):
            with self.temporary() as directory:
                path = Path(directory)/'tampered.zip'
                bodies, modes = dict(self.bodies), dict(self.modes)
                if extra:
                    bodies['tools/test_fixture.py'] = b'pass\n'; modes['tools/test_fixture.py'] = 0o644
                else:
                    bodies['tools/local_ui.py'] += b'\n# altered runtime\n'
                    # A forged member digest inside PACKAGE cannot rebaseline Git bytes.
                    metadata = copy.deepcopy(self.metadata)
                    metadata['members']['tools/local_ui.py']['packaged_sha256'] = package.sha(bodies['tools/local_ui.py'])
                    bodies[package.METADATA] = package.encoded(metadata)
                package.write_archive(path, self.manifest, bodies, modes)
                with self.assertRaises(ValueError):
                    package.verify(path, worktree=True)

    def test_control_browses_from_only_the_unpacked_student_package(self):
        with self.temporary() as directory:
            parent = Path(directory)
            for relative, body in self.bodies.items():
                path = parent/self.manifest['archive_root']/relative
                path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(body)
            root = parent/self.manifest['archive_root']
            code = """
import sys
from pathlib import Path
root=Path.cwd();sys.path[:0]=[str(root/'tools'),str(root/'transport')]
import subprocess
def forbidden(*args,**kwargs):raise AssertionError('Browsing may not start a process')
subprocess.Popen=forbidden
import local_ui,scenario_workflow,catalog_workflow,saved_focus_waveforms
catalog=scenario_workflow.catalog()
assert len(catalog['detectors'])==17 and len(catalog['sources'])==6
assert all(not item['available'] and item['block_code']=='setup_required' for item in catalog['detectors'] if item['id']!='GeGI_3D')
gegi=next(item for item in catalog['detectors'] if item['id']=='GeGI_3D')
assert gegi['available'] and gegi['assemblies']==['gegi_cryostat_v1'] and gegi['sources']==['gegi_mono_gamma_v1']
summaries=catalog_workflow.local_model_summaries()
assert len(summaries)==17 and all(item['placement']['status']=='setup_required' for item in summaries)
assert not set(('site_detector_pages','site_fragments','gamma_publication','gamma_showcase','gamma_complete_showcase')) & set(sys.modules)
try:local_ui.open_saved_gamma_example()
except local_ui.SavedGammaUnavailable:pass
else:raise AssertionError('Unbundled historical example must be unavailable')
print('Isolated student Control imports and 17-model/6-source browsing passed; missing LBNL originals block that assembly; GeGI uses bundled geometry; no child process.')
"""
            arguments = [sys.executable]
            if Path(sys.executable).name.lower() == 'pvpython.exe':
                arguments += ['--no-mpi', '--disable-registry']
            result = subprocess.run(arguments + ['-B', '-c', code], cwd=root,
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
