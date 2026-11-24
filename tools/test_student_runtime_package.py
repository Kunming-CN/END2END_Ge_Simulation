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
                self.assertIn('gegi_continuous_plane.py --acquisition', guide)
                self.assertIn('gegi-center-calibration.npz', guide)
                self.assertIn('--incident-energy-keV ENERGY', guide)
                self.assertIn('gegi_candidate_kinematics.py --saved-plane', guide)
                self.assertIn('gegi_incident_geometry.py', guide)
                self.assertIn('gegi_candidate_cone_spread.py --center-map', guide)
                self.assertIn('--escape-incident-energy-keV ENERGY', guide)
                self.assertIn('--retain-photon-kinematics', guide)
                for tool in ('gegi_continuous_plane.py', 'gegi_joint_calibration.py', 'gegi_joint_two_site.py',
                             'gegi_candidate_topology.py', 'gegi_candidate_kinematics.py', 'gegi_incident_hypotheses.py',
                             'gegi_incident_geometry.py', 'gegi_candidate_cone_spread.py', 'gegi_cone_spread_geometry.py'):
                    self.assertIn(f'{self.manifest["archive_root"]}/tools/{tool}', names)
                self.assertFalse(any(p.endswith(('/gegi_joint_acquisition_study.py', '/gegi-center-calibration.npz',
                                                 '/gegi_position_cone_spread.py', '/gegi_joint_two_site_study.py'))
                                     for p in names))

    def test_frozen_probe_and_missing_dependency_are_rejected(self):
        for ref in ('transport/geometry_probe.cc', 'transport/scenario_transport.py', 'tools/nonzero_events.py'):
            bodies = dict(self.bodies); bodies[ref] += b'\n'
            with self.assertRaisesRegex(ValueError, 'frozen runtime source'):
                package.dependencies(self.manifest, bodies)
        bodies = dict(self.bodies); del bodies['simulation/readout.jl']
        with self.assertRaisesRegex(ValueError, 'Missing Julia include'):
            package.dependencies(self.manifest, bodies)
        bodies = dict(self.bodies); del bodies['tools/scenario_workflow.py']
        with self.assertRaisesRegex(ValueError, r'Missing (?:local/undeclared Python import|runtime dependency): .+ -> (?:tools/)?scenario_workflow(?:\.py)?'):
            package.dependencies(self.manifest, bodies)

    def test_frozen_runtime_inventory_never_executes_python(self):
        source = ast.parse(self.bodies['transport/scenario_source_portable.py'].decode())
        pins = package.frozen_sources(source, 'source_inventory')
        self.assertEqual(pins['transport/scenario_transport.py'], package.sha(self.bodies['transport/scenario_transport.py']))
        self.assertEqual(pins['tools/nonzero_events.py'], package.sha(self.bodies['tools/nonzero_events.py']))
        dynamic = ast.parse('def source_inventory():\n    return subprocess.check_output(["not-a-command"])\n')
        with self.assertRaises(ValueError):
            package.frozen_sources(dynamic, 'source_inventory')

    def test_streaming_runtime_closure_and_embedded_transport_rng_adapter(self):
        runtime = ('tools/gegi_streaming_acquisition.py', 'tools/gegi_streaming_readout.py',
                   'tools/gegi_resource_monitor.py', 'transport/gegi_streaming_source.py',
                   'tools/gegi_candidate_imaging.py', 'transport/gegi_photon_steps.py',
                   'transport/gegi_photon_step_observer.cc')
        for ref in runtime:
            self.assertIn(ref, self.bodies)
            missing = dict(self.bodies)
            del missing[ref]
            with self.assertRaisesRegex(ValueError, 'Missing runtime dependency'):
                package.dependencies(self.manifest, missing)
        syntax = ast.parse(self.bodies['transport/gegi_streaming_source.py'].decode())
        adapter = next(ast.literal_eval(node.value) for node in syntax.body if isinstance(node, ast.Assign)
                       and any(isinstance(target, ast.Name) and target.id == 'RNG_SOURCE' for target in node.targets))
        self.assertIn('#include "RMGDefaultCli.hh"', adapter)
        self.assertIn('CLHEP::HepRandom::saveEngineStatus', adapter)
        self.assertIn('/GeSignal/RNG/', adapter)
        guide = self.bodies['tools/site_guide.html'].decode()
        self.assertIn('Resume saved acquisition', guide)
        self.assertIn('Geant4 random-number state', guide)
        self.assertIn('819 MB', guide)
        self.assertIn('924,676 new Cs-137 parents, 185,199 new Co-60 parents', guide)
        self.assertIn('Analyze all two-strip candidates', guide)
        self.assertIn('releases/latest/download/END2END-Ge-Student.zip', guide)
        self.assertNotIn('acquisitions up to five physical seconds', guide)
        self.assertNotIn('tools/validate_gegi_streaming_readout.py', self.bodies)

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
import gegi_digital_readout,gegi_digital_saved,gegi_substrip,gegi_digital_spectra,gegi_digital_pairs
import gegi_streaming_acquisition,gegi_streaming_readout,gegi_resource_monitor,gegi_streaming_source
import gegi_incident_hypotheses
assert gegi_incident_hypotheses.configuration([661.657])['incident_energies_keV']==[661.657]
assert 'CLHEP::HepRandom::saveEngineStatus' in gegi_streaming_source.RNG_SOURCE
assert gegi_substrip.load_calibration(gegi_digital_saved.CALIBRATION)['digital_profile_sha256']==gegi_digital_readout.PROFILE_SHA256
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
            for tool in ('gegi_candidate_topology.py', 'gegi_candidate_kinematics.py', 'gegi_incident_geometry.py'):
                result = subprocess.run(arguments + ['-B', f'tools/{tool}', '--help'], cwd=root,
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('--incident-energy-keV', result.stdout)
            result = subprocess.run(arguments + ['-B', 'tools/gegi_candidate_cone_spread.py', '--help'], cwd=root,
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('[--compatibility COMPATIBILITY]', result.stdout)
            result = subprocess.run(arguments + ['-B', 'tools/gegi_candidate_range.py', '--help'], cwd=root,
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('--escape-incident-energy-keV ENERGY', result.stdout)

    def test_clean_zip_control_http_check_and_start_without_science(self):
        """Real unpacked HTTP/controllers; prerequisite and launch seams run no science."""
        with self.temporary() as directory:
            parent = Path(directory)
            archive = parent/'student.zip'
            package.write_archive(archive, self.manifest, self.bodies, self.modes)
            with zipfile.ZipFile(archive) as bundle:
                for member in bundle.namelist():
                    self.assertFalse({'.local', '.git', 'docs'} & set(Path(member).parts))
                bundle.extractall(parent)
            root = parent/self.manifest['archive_root']
            self.assertFalse((root/'.local').exists())
            code = """
import copy
import http.client
import json
from pathlib import Path
import subprocess
import sys
import threading
from unittest.mock import patch

root=Path.cwd()
assert not (root/'.local').exists() and not (root/'.git').exists()
sys.path[:0]=[str(root/'tools'),str(root/'transport')]
def forbidden(*args,**kwargs):raise AssertionError('Clean-package protocol test may not start a worker')
subprocess.Popen=forbidden
import local_ui as U
import local_ui_workflow_jobs as J
import scenario_workflow as W
import scenario_source_portable as portable
for module in (U,J,W,portable):
    assert Path(module.__file__).resolve().is_relative_to(root)
assert U.ROOT==W.ROOT==root

coordination=threading.RLock()
controller=U.Controller(root,coordination_lock=coordination)
gamma=U.GammaController(root,coordination_lock=coordination,peer_busy=controller.own_busy)
configured=J.WorkflowController(root,coordination_lock=coordination,
    peer_busy=lambda:controller.own_busy() or gamma.own_busy())
controller.set_peer_busy(lambda:gamma.own_busy() or configured.own_busy())
gamma.set_peer_busy(lambda:controller.own_busy() or configured.own_busy())
server=U.Server(0,controller,token='unpacked-package-session',
    gamma_controller=gamma,workflow_controller=configured)
thread=threading.Thread(target=server.serve_forever,daemon=True)
thread.start()

def request(route,body=None,token=server.token):
    headers={'Host':'127.0.0.1:'+str(server.server_port),'X-Control-Token':token}
    method='GET' if body is None else 'POST'
    if body is not None:
        headers.update({'Origin':server.origin,'Content-Type':'application/json'})
        body=json.dumps(body)
    connection=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=3)
    try:
        connection.request(method,route,body=body,headers=headers)
        response=connection.getresponse()
        data=response.read()
        return response.status,(json.loads(data) if route.startswith('/api/') else data.decode())
    finally:connection.close()

try:
    status,page=request('/')
    assert status==200
    for label in ('New simulation','My runs','Help','Start simulation'):
        assert label in page
    status,script=request('/local_workflow.js')
    assert status==200 and '/api/workflow/check-batches' in script and '/api/workflow/start' in script
    status,state=request('/api/state')
    assert status==200 and state['active'] is None and state['jobs']==[]
    assert state['gamma']['active'] is None and state['gamma']['jobs']==[]
    status,state=request('/api/workflow/state')
    assert status==200 and state['busy'] is False and state['jobs']==[]
    status,catalog=request('/api/workflow/catalog')
    assert status==200 and len(catalog['detectors'])==17 and len(catalog['sources'])==6
    lbnl=[item for item in catalog['detectors'] if item['id']!='GeGI_3D']
    assert all(not item['available'] and item['block_code']=='setup_required' for item in lbnl)
    assert all(item['reason'] for item in lbnl)
    selection={'name':'clean-package-protocol','cryostat':W.CRYOSTAT,'detector':'SAP22',
        'source':W.CS,'pose':'nominal','primary_count':100,'seed':26092631,'threads':1,
        'electronics':catalog['electronics_defaults'],'angle_deg':30}
    submitted={'request':{'kind':'local_scenario_batch_request_v2','schema_version':2,'selection':selection}}

    # No Setup has run. Use the production file-readiness helper at the existing
    # transport-reader seam, without invoking WSL, Julia or a geometry worker.
    def missing_setup(config,root):
        return J.B.check(config,root=root,transport_reader=lambda config,root:portable.file_readiness(root))
    configured._batch_resolver=missing_setup
    status,denied=request('/api/workflow/check-batches',submitted)
    assert status==400 and denied.get('error')=='missing file: '+portable.BUILD_RECEIPT_REF,(status,denied)
    assert configured.snapshot()=={'kind':'local_workflow_state_v1','busy':False,'jobs':[]}
    assert not configured._checks and not W.run_path(selection['name'],root).exists()

    # This fixture supplies dependency readiness only for the protocol path.
    # Count/seed partitioning, HTTP authorization, plan recheck and the durable
    # launch reservation are real; the scientific launch boundary is intercepted.
    resolver_calls=[]
    def ready_protocol_plan(config,root):
        assert config==selection and root==W.ROOT
        resolver_calls.append(copy.deepcopy(config))
        resolved={'selection':copy.deepcopy(config),'batching':J.B.partition(config['primary_count'],config['seed'])}
        return {'kind':J.B.CHECKED_KIND,'schema_version':3,'status':'checked_configuration',
            'science_calls':0,'execution_enabled':True,'resolved':resolved,'configuration_sha256':W.digest(resolved)}
    configured._batch_resolver=ready_protocol_plan
    status,denied=request('/api/workflow/check-batches',submitted,token='wrong-session')
    assert status==403 and resolver_calls==[]
    status,checked=request('/api/workflow/check-batches',submitted)
    assert status==200 and checked['science_calls']==0 and checked['execution_enabled'] is True
    assert checked['resolved']['selection']==selection and len(resolver_calls)==1
    assert configured.snapshot()['busy'] is False
    assert not W.run_path(selection['name'],root).exists()
    with patch.object(configured,'_launch',side_effect=configured._view) as launch:
        status,started=request('/api/workflow/start',{'check_id':checked['check_id']})
        assert status==200 and started['name']==selection['name'] and started['selection']==selection
        assert started['execution_contract']=='serial_batches_v3' and len(resolver_calls)==2
        assert launch.call_count==1
        status,replayed=request('/api/workflow/start',{'check_id':checked['check_id']})
        assert status==400 and launch.call_count==1
    saved=W.read(root/J.STATE/'workflow-jobs.json')
    assert len(saved['jobs'])==1 and saved['jobs'][0]['name']==selection['name']
    assert saved['jobs'][0]['plan']['resolved']['selection']==selection
    assert saved['jobs'][0]['driver'] is None
    assert not W.run_path(selection['name'],root).exists()
    print('Clean ZIP Control HTTP: empty idle state, configurable catalog, explicit missing-setup refusal, authorized batch Check/Start and one durable dispatch; dependency readiness injected, scientific launch intercepted, no workers or science.')
finally:
    server.shutdown()
    server.server_close()
    thread.join()
"""
            arguments = [sys.executable]
            if Path(sys.executable).name.lower() == 'pvpython.exe':
                arguments += ['--no-mpi', '--disable-registry']
            result = subprocess.run(arguments + ['-B', '-c', code], cwd=root,
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
