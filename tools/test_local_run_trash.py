"""Owned text fixtures only: no scientific runs, source data or services."""
import copy
import ctypes
import json
import os
from pathlib import Path
import subprocess
import stat
import tempfile
import unittest
from unittest.mock import patch

import local_ui_workflow_jobs as J
import local_run_trash as T
import scenario_workflow as W


class TrashTests(unittest.TestCase):
    def setUp(self):
        parent = W.ROOT/'.local/student-ui-v1/trash-tests'
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workflow = J.WorkflowController(self.root)
        self.trash = self.workflow.run_trash()

    def workflow_run(self, name='UI-test-disposable-run', ids=(1, 2)):
        jobs = []
        for ordinal in ids:
            selection = {'name': name, 'detector': 'SAP22', 'source': W.CS, 'primary_count': 100}
            job = {'id': f'{ordinal:032x}', 'name': name, 'status': 'inspected_failure',
                   'driver': None, 'mode': 'run' if not jobs else 'resume', 'created_utc': W.utc(),
                   'plan': {'kind': W.KIND, 'resolved': {'selection': selection}, 'configuration_sha256': 'a'*64}}
            jobs.append(job)
            for relative, data in ((f'workflow-launches/{job["id"]}/fixture.json', b'{"test":true}\r\n'),
                                   (f'workflow-plans/{job["id"]}.json', b'original plan bytes\r\n'),
                                   (f'workflow-logs/{job["id"]}.log', b'original log bytes\x00\xff')):
                path = self.root/'.local/local-control-v1'/relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
        self.workflow._jobs.extend(jobs)
        self.workflow._persist()
        directory = W.run_path(name, self.root)
        directory.mkdir(parents=True, exist_ok=True)
        (directory/'fixture.txt').write_bytes(b'UI-test-disposable: original bytes\r\n\x00\xff')
        return jobs, directory

    def candidate_run(self, name='UI-test-disposable-candidate'):
        control = self.workflow.gegi_candidates()
        directory = control._directory(name)
        directory.mkdir(parents=True)
        (directory/'fixture.txt').write_bytes(b'UI-test-disposable candidate\r\n\xff')
        (directory/'candidate-imaging-fixture.json.gz').write_bytes(b'UI-test-disposable map bytes')
        job = {'name': name, 'status': 'failed', 'driver': None, 'started_utc': W.utc(),
               'analysis': {'status': 'completed', 'driver': None, 'calibration_ref': '.local/shared-calibration.npz'}}
        control.jobs[name] = job
        control._persist()
        shared = self.root/'.local/shared-calibration.npz'
        shared.write_bytes(b'UI-test-disposable external calibration; never move')
        return control, job, directory, shared

    def inventory(self, directory):
        return {path.relative_to(directory).as_posix(): path.read_bytes()
                for path, is_dir in T.checked_tree(directory) if not is_dir}

    def test_workflow_moves_all_same_name_dispatches_and_restores_exact_bytes(self):
        jobs, directory = self.workflow_run()
        before = self.inventory(directory)
        originals = {relative: self.inventory(self.root/relative) if (self.root/relative).is_dir()
                     else (self.root/relative).read_bytes()
                     for relative in self.trash._paths('workflow', jobs[0]['name'],
                         [{'position': index, 'job': job} for index, job in enumerate(jobs)])}
        self.assertTrue(self.workflow.snapshot()['jobs'][0]['can_delete'])
        entry = self.trash.move('workflow', jobs[0]['name'])['entry']
        self.assertFalse(directory.exists())
        self.assertEqual(self.workflow._jobs, [])
        self.assertTrue(entry['can_restore'])
        self.assertEqual(self.trash.snapshot()['entries'], [entry])
        reopened = J.WorkflowController(self.root)
        self.assertEqual(reopened.snapshot()['jobs'], [])
        reopened.run_trash().restore(entry['id'])
        self.assertEqual(reopened._jobs, jobs)
        self.assertEqual(self.inventory(directory), before)
        for relative, original in originals.items():
            actual = self.inventory(self.root/relative) if (self.root/relative).is_dir() else (self.root/relative).read_bytes()
            self.assertEqual(actual, original)
        self.assertEqual(reopened.run_trash().snapshot()['entries'], [])

    def test_candidate_moves_its_analysis_but_never_external_calibration(self):
        control, job, directory, shared = self.candidate_run()
        before, original_job, calibration = self.inventory(directory), copy.deepcopy(job), shared.read_bytes()
        self.assertTrue(control.options()['jobs'][0]['can_delete'])
        self.assertTrue(control.state(job['name'])['can_delete'])
        entry = self.trash.move('candidate', job['name'])['entry']
        self.assertFalse(directory.exists()); self.assertNotIn(job['name'], control.jobs)
        self.assertEqual(shared.read_bytes(), calibration)
        self.trash.restore(entry['id'])
        self.assertEqual(control.jobs[job['name']], original_job)
        self.assertEqual(self.inventory(directory), before)
        self.assertEqual(shared.read_bytes(), calibration)

    def test_restore_refuses_name_and_dispatch_collisions_without_overwrite(self):
        jobs, directory = self.workflow_run()
        original = self.inventory(directory)
        entry = self.trash.move('workflow', jobs[0]['name'])['entry']
        new_jobs, new_directory = self.workflow_run(ids=(3,))
        with self.assertRaisesRegex(W.ControlError, 'conflicting run'):
            self.trash.restore(entry['id'])
        self.assertEqual(self.workflow._jobs, new_jobs)
        self.assertTrue(new_directory.exists())
        second = self.trash.move('workflow', new_jobs[0]['name'])['entry']
        self.trash.restore(entry['id'])
        self.assertEqual(self.workflow._jobs, jobs)
        self.assertEqual(self.inventory(directory), original)
        self.assertEqual([row['id'] for row in self.trash.snapshot()['entries']], [second['id']])

    def test_empty_requires_explicit_ids_confirmation_and_preserves_other_entries(self):
        jobs, directory = self.workflow_run()
        first = self.trash.move('workflow', jobs[0]['name'])['entry']
        control, job, candidate, shared = self.candidate_run()
        second = self.trash.move('candidate', job['name'])['entry']
        for ids, confirmation in (([first['id']], 'delete'), ([], 'DELETE'),
                                  ([first['id'], first['id']], 'DELETE'),
                                  ([first['id'], 'f'*32], 'DELETE'), (['../runs'], 'DELETE')):
            with self.subTest(ids=ids, confirmation=confirmation), self.assertRaises((W.ControlError, OSError)):
                self.trash.empty(ids, confirmation)
            self.assertEqual(len(self.trash.snapshot()['entries']), 2)
        self.assertEqual(self.trash.empty([first['id']], 'DELETE'), {'deleted_ids': [first['id']]})
        self.assertEqual([row['id'] for row in self.trash.snapshot()['entries']], [second['id']])
        self.assertTrue(shared.is_file())
        self.trash.restore(second['id'])
        self.assertTrue(candidate.is_dir())

    def test_active_unknown_peer_and_execution_lease_block_moves(self):
        jobs, directory = self.workflow_run()
        original = self.inventory(directory)
        for status, driver in (('running', None), ('dispatch_uncertain', None),
                               ('inspected_failure', {'pid': 999999, 'identity': 'old'})):
            jobs[0].update(status=status, driver=driver)
            with patch.object(W, 'process_identity', return_value='unknown'):
                self.assertFalse(self.trash.eligibility('workflow', jobs[0]['name'])['can_delete'])
                with self.assertRaises(W.ControlError):self.trash.move('workflow', jobs[0]['name'])
            self.assertEqual(self.inventory(directory), original)
        jobs[0].update(status='inspected_failure', driver=None)
        with W.execution_lease(self.root):
            with self.assertRaises(W.ControlError):self.trash.move('workflow', jobs[0]['name'])
        self.workflow.set_peer_busy(lambda: True)
        with self.assertRaises(W.ControlError):self.trash.move('workflow', jobs[0]['name'])

    def test_candidate_analysis_unknown_and_shared_source_dependency_block_moves(self):
        control, job, directory, shared = self.candidate_run()
        job['range_analysis'] = {'status': 'completed', 'driver': {'pid': 999999, 'identity': 'old'}}
        with patch.object(W, 'process_identity', return_value='unknown'):
            self.assertFalse(self.trash.eligibility('candidate', job['name'])['can_delete'])
            with self.assertRaises(W.ControlError):self.trash.move('candidate', job['name'])
        jobs, ordinary = self.workflow_run()
        W.write(self.root/'.local/local-control-v1/gegi-saved-jobs.json',
                {'kind': 'gegi_saved_control_v1', 'jobs': [{'name': 'dependent-analysis', 'source_run_name': jobs[0]['name']}]})
        eligible = self.trash.eligibility('workflow', jobs[0]['name'])
        self.assertFalse(eligible['can_delete']); self.assertIn('dependent-analysis', eligible['delete_reason'])
        with self.assertRaises(W.ControlError):self.trash.move('workflow', jobs[0]['name'])
        self.assertTrue(ordinary.is_dir()); self.assertTrue(shared.is_file())

    def test_failed_state_publication_rolls_back_files_and_job_records(self):
        jobs, directory = self.workflow_run()
        original, saved = self.inventory(directory), self.workflow._state_path.read_bytes()
        with patch.object(self.workflow, '_persist', side_effect=[OSError('Fixture state write failed'), None]):
            with self.assertRaisesRegex(OSError, 'Fixture state write failed'):
                self.trash.move('workflow', jobs[0]['name'])
        self.assertEqual(self.inventory(directory), original)
        self.assertEqual(self.workflow._jobs, jobs)
        self.assertEqual(self.workflow._state_path.read_bytes(), saved)
        entry = self.trash.snapshot()['entries'][0]
        self.assertEqual(entry['status'], 'move_failed'); self.assertFalse(entry['can_restore'])

    def test_recycle_metadata_cannot_redirect_restoration_outside_known_run_roots(self):
        jobs, directory = self.workflow_run()
        entry = self.trash.move('workflow', jobs[0]['name'])['entry']
        metadata = self.root/T.BASE/entry['id']/'entry.json'
        saved = W.read(metadata)
        for relative in ('../protected', '.local/shared-calibration.npz', '.local/runs/other'):
            changed = copy.deepcopy(saved); changed['paths'].append(relative); W.write(metadata, changed)
            with self.assertRaises(W.ControlError):self.trash.restore(entry['id'])
            with self.assertRaises(W.ControlError):self.trash.empty([entry['id']], 'DELETE')
        W.write(metadata, saved)
        self.trash.restore(entry['id'])
        self.assertTrue(directory.is_dir())

    @unittest.skipUnless(os.name == 'nt', 'Windows directory ReadOnly attribute')
    def test_empty_handles_readonly_directories_without_touching_parent_attributes(self):
        jobs, directory = self.workflow_run()
        entry = self.trash.move('workflow', jobs[0]['name'])['entry']
        folder = self.root/T.BASE/entry['id']
        parent_attributes = folder.parent.lstat().st_file_attributes
        api = ctypes.WinDLL('kernel32', use_last_error=True)
        api.SetFileAttributesW.argtypes = (ctypes.c_wchar_p, ctypes.c_uint32)
        for path, is_dir in T.checked_tree(folder):
            if is_dir:
                self.assertTrue(api.SetFileAttributesW(str(path), path.lstat().st_file_attributes | stat.FILE_ATTRIBUTE_READONLY))
        self.trash.empty([entry['id']], 'DELETE')
        self.assertFalse(folder.exists())
        self.assertEqual(folder.parent.lstat().st_file_attributes, parent_attributes)

    @unittest.skipUnless(os.name == 'nt', 'Windows failed deletion attribute restoration')
    def test_partial_empty_preserves_metadata_restores_attributes_and_can_retry(self):
        jobs, directory = self.workflow_run()
        entry = self.trash.move('workflow', jobs[0]['name'])['entry']
        folder = self.root/T.BASE/entry['id']
        blocked = folder/'payload/.local/runs'/jobs[0]['name']
        api = ctypes.WinDLL('kernel32', use_last_error=True)
        api.SetFileAttributesW.argtypes = (ctypes.c_wchar_p, ctypes.c_uint32)
        attributes = blocked.lstat().st_file_attributes | stat.FILE_ATTRIBUTE_READONLY
        self.assertTrue(api.SetFileAttributesW(str(blocked), attributes))
        original_rmdir = Path.rmdir
        def fail_selected(path, *args, **kwargs):
            if path == blocked:
                raise PermissionError(13, 'Fixture directory in use', str(path))
            return original_rmdir(path, *args, **kwargs)
        with patch.object(Path, 'rmdir', new=fail_selected):
            with self.assertRaisesRegex(W.ControlError, 'Fixture directory in use'):
                self.trash.empty([entry['id']], 'DELETE')
        self.assertEqual(blocked.lstat().st_file_attributes, attributes)
        self.assertTrue((folder/'entry.json').is_file())
        public = self.trash.snapshot()['entries'][0]
        self.assertEqual(public['status'], 'purging')
        self.assertFalse(public['can_restore']); self.assertTrue(public['can_empty'])
        with self.assertRaises(W.ControlError):self.trash.restore(entry['id'])
        self.trash.empty([entry['id']], 'DELETE')
        self.assertFalse(folder.exists())

    @unittest.skipUnless(os.name == 'nt', 'Windows junction rejection')
    def test_junction_is_never_traversed_on_move_or_empty(self):
        jobs, directory = self.workflow_run()
        external = self.root/'outside-known-run-root'; external.mkdir()
        (external/'keep.txt').write_bytes(b'external fixture must survive')
        link = directory/'junction'
        result = subprocess.run(['cmd.exe', '/c', 'mklink', '/J', str(link), str(external)],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        try:
            with self.assertRaises(W.ControlError):self.trash.move('workflow', jobs[0]['name'])
            self.assertEqual((external/'keep.txt').read_bytes(), b'external fixture must survive')
        finally:
            link.rmdir()
        entry = self.trash.move('workflow', jobs[0]['name'])['entry']
        payload = self.root/T.BASE/entry['id']/'payload'/'.local/runs'/jobs[0]['name']
        link = payload/'junction'
        result = subprocess.run(['cmd.exe', '/c', 'mklink', '/J', str(link), str(external)],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        try:
            with self.assertRaises(W.ControlError):self.trash.empty([entry['id']], 'DELETE')
            self.assertEqual((external/'keep.txt').read_bytes(), b'external fixture must survive')
        finally:
            link.rmdir()


if __name__ == '__main__':
    unittest.main()
