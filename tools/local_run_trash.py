"""Project-local recycle bin for the two run kinds listed in Control's My runs."""
import copy
import ctypes
import os
from pathlib import Path
import re
import secrets
import stat

import scenario_workflow as W

BASE = '.local/run-trash'
ID = re.compile(r'[0-9a-f]{32}\Z')
ACTIVE = ('dispatch_uncertain', 'running', 'stop_requested')


def checked_tree(path):
    """Inspect without following any link, junction or other reparse point."""
    pending, found = [Path(path)], []
    while pending:
        current = pending.pop()
        info = current.lstat()
        W.require(not stat.S_ISLNK(info.st_mode) and not
                  getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT,
                  'Linked or reparse run contents cannot be moved or removed.')
        directory = stat.S_ISDIR(info.st_mode)
        W.require(directory or stat.S_ISREG(info.st_mode), 'Unsupported run file type.')
        found.append((current, directory))
        if directory:
            with os.scandir(current) as items:
                pending.extend(Path(item.path) for item in items)
    return found


class RunTrash:
    def __init__(self, workflow):
        self.workflow = workflow
        self.root = workflow.root

    def _jobs(self, kind):
        W.require(kind in ('workflow', 'candidate'), 'Choose an ordinary run or GeGI acquisition.')
        return self.workflow._jobs if kind == 'workflow' else list(self.workflow.gegi_candidates().jobs.values())

    def _paths(self, kind, name, records):
        if kind == 'candidate':
            return [self.workflow.gegi_candidates()._directory(name).relative_to(self.root).as_posix()]
        paths = [W.run_path(name, self.root).relative_to(self.root).as_posix()]
        for row in records:
            job = row['job']
            W.require(ID.fullmatch(str(job.get('id', ''))), 'Invalid saved dispatch identity.')
            paths.extend('.local/local-control-v1/' + folder + '/' + job['id'] + suffix
                         for folder, suffix in (('workflow-launches', ''), ('workflow-plans', '.json'),
                                                ('workflow-logs', '.log')))
        return paths

    def eligibility(self, kind, name, *, busy=None):
        try:
            jobs = self._jobs(kind)
            if busy is None:
                busy = self.workflow.own_busy() or self.workflow._peer_busy()
            W.require(not busy, 'Stop running work and resolve unknown worker identities before deleting runs.')
            selected = [job for job in jobs if job['name'].casefold() == name.casefold()]
            if kind == 'workflow':
                W.require(selected, 'Unknown owned run.')
                W.require(all(job['status'] not in ACTIVE and W.identity_ended(job.get('driver'))
                              for job in selected), 'The run still has an active or unknown driver.')
                dependents = [job['name'] for job in jobs if job.get('transport_parent', '').casefold() == name.casefold()]
                saved = W.safe_path(self.root, '.local/local-control-v1/gegi-saved-jobs.json')
                if saved.is_file():
                    dependents += [job['name'] for job in W.read(saved).get('jobs', [])
                                   if job.get('source_run_name', '').casefold() == name.casefold()]
                W.require(not dependents, 'Saved analyses or continued runs still use this run: ' + ', '.join(dependents))
            else:
                control = self.workflow.gegi_candidates()
                W.require(selected or W.safe_path(control._directory(name), 'candidate-acquisition.json').is_file(),
                          'Unknown GeGI acquisition.')
                for job in selected:
                    W.require(job['status'] in ('completed', 'failed', 'stopped') and
                              W.identity_ended(job.get('driver')) and name not in control._analysis_running,
                              'The acquisition is active, interrupted or has an unknown worker.')
                    for key in ('analysis', 'range_analysis'):
                        analysis = job.get(key)
                        W.require(not analysis or (analysis['status'] != 'running' and W.identity_ended(analysis.get('driver'))),
                                  'A linked imaging or range-analysis worker is active or unknown.')
            return {'can_delete': True, 'delete_reason': ''}
        except (W.ControlError, OSError, ValueError) as error:
            return {'can_delete': False, 'delete_reason': str(error)}

    @staticmethod
    def _view(entry):
        return {key: entry[key] for key in ('id', 'kind', 'name', 'deleted_utc', 'status')} | {
            'can_restore': entry['status'] == 'trashed', 'can_empty': entry['status'] in ('trashed', 'purging')}

    def _entry(self, entry_id, *, allow_purging=False):
        W.require(type(entry_id) is str and ID.fullmatch(entry_id), 'Invalid recycle-bin entry.')
        folder = W.safe_path(self.root, BASE + '/' + entry_id)
        metadata = W.safe_path(folder, 'entry.json')
        W.require(metadata.is_file(), 'Recycle-bin entry no longer exists.')
        entry = W.read(metadata)
        W.require(entry.get('id') == entry_id and entry.get('kind') in ('workflow', 'candidate') and
                  entry.get('status') in (('trashed', 'purging') if allow_purging else ('trashed',)) and
                  type(entry.get('records')) is list and
                  type(entry.get('paths')) is list, 'Incomplete recycle-bin entry; preserve it for inspection.')
        allowed = self._paths(entry['kind'], entry['name'], entry['records'])
        W.require(len(set(entry['paths'])) == len(entry['paths']) and set(entry['paths']) <= set(allowed),
                  'Recycle-bin paths differ from the original run.')
        for row in entry['records']:
            job = row['job']
            W.require(type(row['position']) is int and row['position'] >= 0 and
                      job['name'].casefold() == entry['name'].casefold() and job['status'] not in ACTIVE and
                      W.identity_ended(job.get('driver')), 'A saved recycle-bin driver is active or unknown.')
            for key in ('analysis', 'range_analysis'):
                analysis = job.get(key)
                W.require(not analysis or (analysis['status'] != 'running' and W.identity_ended(analysis.get('driver'))),
                          'A saved recycle-bin analysis driver is active or unknown.')
        return folder, entry

    def snapshot(self):
        with self.workflow._lock:
            self.workflow.gegi_candidates()
            parent = W.safe_path(self.root, BASE)
            entries = []
            if parent.is_dir():
                for folder in parent.iterdir():
                    W.safe_path(self.root, BASE + '/' + folder.name)
                    W.require(ID.fullmatch(folder.name) and folder.is_dir(), 'Unrecognized recycle-bin contents.')
                    entry = W.read(W.safe_path(folder, 'entry.json'))
                    entries.append(self._view(entry))
            return {'entries': sorted(entries, key=lambda row: row['deleted_utc'], reverse=True),
                    'busy': self.workflow.own_busy() or self.workflow._peer_busy()}

    def _set_jobs(self, kind, jobs):
        if kind == 'workflow':
            self.workflow._jobs = jobs
            self.workflow._persist()
            self.workflow._gegi_readers.clear()
        else:
            control = self.workflow.gegi_candidates()
            control.jobs = {job['name']: job for job in jobs}
            control._persist()
            control._analysis_cache.clear()
            control._verified_stores.clear()
            control._contributors_cache = None

    def move(self, kind, name):
        with self.workflow._lock:
            self.workflow.gegi_candidates()
            self.workflow._idle()
            eligible = self.eligibility(kind, name, busy=False)
            W.require(eligible['can_delete'], eligible['delete_reason'])
            with W.execution_lease(self.root):
                W.verify_dispatch_reservations(None, self.root)
                jobs = copy.deepcopy(self._jobs(kind))
                records = [{'position': index, 'job': job} for index, job in enumerate(jobs)
                           if job['name'].casefold() == name.casefold()]
                name = records[0]['job']['name'] if records else name
                paths = [relative for relative in self._paths(kind, name, records)
                         if W.safe_path(self.root, relative).exists()]
                for relative in paths:
                    checked_tree(W.safe_path(self.root, relative))
                entry_id = secrets.token_hex(16)
                folder = W.safe_path(self.root, BASE + '/' + entry_id)
                folder.mkdir(parents=True, exist_ok=False)
                entry = {'id': entry_id, 'kind': kind, 'name': name, 'deleted_utc': W.utc(),
                         'status': 'moving', 'records': records, 'paths': paths}
                W.write(folder/'entry.json', entry, fresh=True)
                moved = []
                try:
                    for relative in paths:
                        source = W.safe_path(self.root, relative)
                        target = W.safe_path(folder, 'payload/' + relative)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        source.rename(target)
                        moved.append((source, target))
                    self._set_jobs(kind, [job for job in jobs if job['name'].casefold() != name.casefold()])
                    entry['status'] = 'trashed'
                    W.write(folder/'entry.json', entry)
                except Exception:
                    for source, target in reversed(moved):
                        W.require(not source.exists(), 'Trash rollback found a conflicting original path; all files are retained.')
                        target.rename(source)
                    self._set_jobs(kind, jobs)
                    entry['status'] = 'move_failed'
                    W.write(folder/'entry.json', entry)
                    raise
                return {'entry': self._view(entry)}

    def restore(self, entry_id):
        with self.workflow._lock:
            self.workflow.gegi_candidates()
            self.workflow._idle()
            with W.execution_lease(self.root):
                W.verify_dispatch_reservations(None, self.root)
                folder, entry = self._entry(entry_id)
                kind, name = entry['kind'], entry['name']
                jobs = copy.deepcopy(self._jobs(kind))
                W.require(not any(job['name'].casefold() == name.casefold() for job in jobs),
                          'A run with this name already exists. Move the conflicting run to the recycle bin before restoring.')
                W.require(not set(job.get('id') for job in jobs if 'id' in job).intersection(
                    row['job'].get('id') for row in entry['records'] if 'id' in row['job']),
                    'An original dispatch identity is already recorded.')
                for relative in self._paths(kind, name, entry['records']):
                    W.require(not W.safe_path(self.root, relative).exists(), 'An original run or dispatch path is already occupied.')
                for relative in entry['paths']:
                    checked_tree(W.safe_path(folder, 'payload/' + relative))
                moved = []
                try:
                    for relative in entry['paths']:
                        source = W.safe_path(folder, 'payload/' + relative)
                        target = W.safe_path(self.root, relative)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        source.rename(target)
                        moved.append((source, target))
                    restored = list(jobs)
                    for row in entry['records']:
                        restored.insert(min(row['position'], len(restored)), row['job'])
                    self._set_jobs(kind, restored)
                except Exception:
                    for source, target in reversed(moved):
                        target.rename(source)
                    self._set_jobs(kind, jobs)
                    raise
                self._remove(folder)
                return {'restored': self._view(entry)}

    def _remove(self, folder):
        W.require(folder == W.safe_path(self.root, BASE + '/' + folder.name) and ID.fullmatch(folder.name),
                  'Only an explicitly selected recycle-bin entry may be removed.')
        contents = checked_tree(folder)
        metadata = folder/'entry.json'
        saved_metadata = metadata.read_bytes() if metadata.is_file() else None

        def remove(path, directory):
            W.safe_path(self.root, path.relative_to(self.root).as_posix())
            attributes = getattr(path.lstat(), 'st_file_attributes', 0)
            changed = os.name == 'nt' and directory and attributes & stat.FILE_ATTRIBUTE_READONLY
            if changed:
                api = ctypes.WinDLL('kernel32', use_last_error=True)
                api.SetFileAttributesW.argtypes = (ctypes.c_wchar_p, ctypes.c_uint32)
                api.SetFileAttributesW.restype = ctypes.c_int
            try:
                if changed and not api.SetFileAttributesW(str(path), attributes & ~stat.FILE_ATTRIBUTE_READONLY):
                    raise ctypes.WinError(ctypes.get_last_error())
                path.rmdir() if directory else path.unlink()
            except OSError as error:
                restored = not changed or api.SetFileAttributesW(str(path), attributes)
                detail = 'Windows error ' + str(getattr(error, 'winerror', error.errno))
                if not restored:
                    detail += '; original directory attributes could not be restored'
                raise W.ControlError('Could not remove ' + path.relative_to(self.root).as_posix() +
                                     ' (' + detail + '): ' + str(error.strerror)) from error

        for path, directory in reversed(contents):
            if path not in (folder, metadata):
                remove(path, directory)
        try:
            if saved_metadata is not None:
                remove(metadata, False)
            remove(folder, True)
        except W.ControlError:
            if saved_metadata is not None and folder.is_dir() and not metadata.exists():
                W.safe_path(self.root, metadata.relative_to(self.root).as_posix()).write_bytes(saved_metadata)
            raise

    def empty(self, ids, confirmation):
        W.require(confirmation == 'DELETE' and type(ids) is list and ids and
                  all(type(value) is str and ID.fullmatch(value) for value in ids) and len(set(ids)) == len(ids),
                  'Confirm DELETE for the explicitly selected recycle-bin entries.')
        with self.workflow._lock:
            self.workflow.gegi_candidates()
            self.workflow._idle()
            with W.execution_lease(self.root):
                W.verify_dispatch_reservations(None, self.root)
                entries = [self._entry(entry_id, allow_purging=True) for entry_id in ids]
                for folder, entry in entries:
                    checked_tree(folder)
                deleted = []
                for folder, entry in entries:
                    entry['status'] = 'purging'
                    W.write(folder/'entry.json', entry)
                    try:
                        self._remove(folder)
                    except (OSError, W.ControlError) as error:
                        raise W.ControlError('Empty trash stopped; completed entries: ' + ', '.join(deleted) +
                                             '. Remaining files are preserved. ' + str(error)) from error
                    deleted.append(entry['id'])
                return {'deleted_ids': deleted}
