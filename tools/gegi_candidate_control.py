"""Protected Control jobs and bounded saved views for fresh mixed-source GeGI runs."""

import copy
from contextlib import closing
from hashlib import sha256
import json
import math
import re
import sqlite3
import threading
import traceback

import numpy as np

import gegi_candidate_storage as storage
import gegi_digital_readout as digital
import gegi_exposure_stream as stream
import gegi_pulse_stream as pulse
from local_ui_jobs import safe_path
import scenario_workflow as W


OUTPUTS = '.local/gegi-candidate-runs'
STATE = '.local/local-control-v1/gegi-candidate-jobs.json'
KIND = 'local_gegi_candidate_control_v1'
REPORT_KIND = 'gegi_candidate_acquisition_v1'
REPORT_NAME = 'candidate-acquisition.json'
NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,47}\Z')
STARTUP_POLICY = 'new_parent_decays_empty_daughters_at_start'
STEADY_POLICY = 'secular_equilibrium_poisson_daughters_v1'


def _name(value):
    W.require(type(value) is str and NAME.fullmatch(value), 'Use a new name of 1–48 letters, numbers, underscores or hyphens.')
    return value


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


class CandidateControl:
    def __init__(self, workflow, *, runner=None):
        self.workflow = workflow
        self.root = workflow.root
        self.runner = runner
        self.jobs = {}
        self._stop_events = {}
        self._verified_stores = {}
        self.state_path = safe_path(self.root, STATE)
        if self.state_path.is_file():
            state = W.read(self.state_path)
            W.require(state.get('kind') == KIND and type(state.get('jobs')) is list,
                      'Saved mixed-source Control state needs inspection.')
            for original in state['jobs']:
                job = copy.deepcopy(original)
                _name(job['name'])
                if job['status'] in ('running', 'stop_requested'):
                    job.update(status='interrupted', error='The previous Control session ended. Saved partial files are preserved.')
                self.jobs[job['name']] = job

    def _directory(self, name):
        return safe_path(self.root, OUTPUTS + '/' + _name(name))

    def _persist(self):
        W.write(self.state_path, {'kind': KIND, 'jobs': list(self.jobs.values())})

    def _resumable(self, directory):
        path = safe_path(directory, storage.ARCHIVE_NAME)
        if not path.is_file() or safe_path(directory, REPORT_NAME).exists():
            return False
        try:
            with closing(storage._open_readonly(path)) as db:
                checkpoint = db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='checkpoint'").fetchone()
                return bool(checkpoint and db.execute('SELECT 1 FROM checkpoint WHERE singleton=1').fetchone())
        except sqlite3.DatabaseError:
            return False

    def _report(self, name, expected=None):
        directory = self._directory(name)
        path = safe_path(directory, REPORT_NAME)
        raw = path.read_bytes()
        digest = sha256(raw).hexdigest()
        W.require(expected is None or expected == digest, 'The opened acquisition report changed. Reopen the saved run.')
        report = json.loads(raw)
        W.require(report.get('kind') == REPORT_KIND and report.get('status') == 'completed',
                  'Choose a completed candidate acquisition; partial files remain available for inspection.')
        return directory, report, digest

    def _database(self, name, expected):
        directory, report, digest = self._report(name, expected)
        path = safe_path(directory, storage.ARCHIVE_NAME)
        artifact = report['artifacts'][storage.ARCHIVE_NAME]
        stat = path.stat()
        signature = (stat.st_size, stat.st_mtime_ns, artifact['sha256'])
        if self._verified_stores.get(name) != signature:
            W.require(stat.st_size == artifact['bytes'] and W.sha(path) == artifact['sha256'],
                      'Saved candidate signals differ from the completed acquisition.')
            summary = storage.store_summary(path)
            W.require(summary['status'] == 'completed', 'The candidate signal store is incomplete.')
            self._verified_stores[name] = signature
        return path, report, digest

    def options(self):
        """Read only immediate result folders; discovery starts no acquisition."""
        with self.workflow._lock:
            jobs = {name: {'name': name, 'status': job['status']} for name, job in self.jobs.items()}
        parent = safe_path(self.root, OUTPUTS)
        if parent.is_dir():
            for child in sorted(parent.iterdir(), key=lambda p: p.name.casefold()):
                if not NAME.fullmatch(child.name):
                    continue
                directory = self._directory(child.name)
                if safe_path(directory, REPORT_NAME).is_file():
                    jobs[child.name] = {'name': child.name, 'status': 'completed'}
        return {'kind': KIND, 'jobs': list(jobs.values()), 'defaults': {
            'mode': 'duration', 'duration_s': 5, 'maximum_duration_s': None,
            'primary_count': 100, 'maximum_primary_count': None, 'seed': 20261120,
            'activities_bq': [185000, 37000], 'positions_mm': [[-40, 0, 40], [40, 0, 40]]},
            'new_science_calls': 0}

    def estimate(self, total_parents, activities_bq, positions_mm):
        """Use the small public format reference; never inspect or launch science."""
        W.require(type(total_parents) is int and 1 <= total_parents <= 9007199254740991,
                  'Use a positive exact total decay count no larger than 9007199254740991.')
        W.require(type(activities_bq) in (list, tuple) and len(activities_bq) == 2
                  and all(_finite(v) and v > 0 for v in activities_bq),
                  'Enter finite positive Cs-137 and Co-60 activities in Bq.')
        W.require(type(positions_mm) in (list, tuple) and len(positions_mm) == 2
                  and all(type(p) in (list, tuple) and len(p) == 3 and all(_finite(v) for v in p)
                          for p in positions_mm), 'Enter two finite detector-coordinate positions in mm.')
        import gegi_storage_estimate as estimate
        reference = estimate.load_reference()
        reference_positions = [source['source_position_mm'] for source in reference['provenance']['sources']]
        W.require([list(p) for p in positions_mm] == reference_positions,
                  'This storage reference uses Cs-137 at (−40, 0, 40) mm and Co-60 at (40, 0, 40) mm. '
                  'A changed source position needs a matching measured reference.')
        return {**estimate.estimate(total_parents, activities_bq, reference=reference),
                'execution_primary_limit': None, 'execution_duration_limit_s': None,
                'new_science_calls': 0}

    def state(self, name):
        directory = self._directory(name)
        with self.workflow._lock:
            job = copy.deepcopy(self.jobs.get(name, {'name': name, 'status': 'saved'}))
            active = self.workflow._active == 'gegi-candidates-' + name
        progress = safe_path(directory, 'progress.json')
        if progress.is_file() and not active:
            job['progress'] = W.read(progress)
            if job['progress'].get('status') == 'failed':
                job.update(status='failed', error=job['progress'].get('error', 'Inspect the preserved acquisition failure.'))
        if safe_path(directory, REPORT_NAME).is_file():
            _, report, digest = self._report(name, job.get('report_sha256'))
            status = job['status'] if active else 'failed' if job['status'] == 'failed' else 'completed'
            job.update(status=status, report_sha256=digest, result=report,
                       output=OUTPUTS + '/' + name, results_available=True)
            if status == 'completed':
                job.pop('error', None)
        else:
            W.require(name in self.jobs, 'Unknown mixed-source acquisition.')
        job['resumable'] = (not active and job['status'] in ('stopped', 'interrupted', 'failed')
                            and self._resumable(directory))
        return job

    def candidates(self, name, report_sha256, offset=0):
        W.require(type(offset) is int and offset >= 0, 'Choose a nonnegative candidate page offset.')
        path, report, digest = self._database(name, report_sha256)
        items = storage.list_candidates(path, offset=offset, limit=100)
        return {'kind': KIND, 'name': name, 'report_sha256': digest, 'offset': offset,
                'total': report['storage_counts']['saved_candidates'],
                'items': [{key: item[key] for key in ('trigger_id', 'trigger_time_ns', 'reason', 'card')}
                          for item in items]}

    def event(self, name, report_sha256, trigger_id, contact_id):
        W.require(type(trigger_id) is int and trigger_id > 0 and type(contact_id) is int
                  and contact_id in digital.CONTACT_IDS, 'Choose an original candidate trigger and electrode 1–34.')
        path, _, digest = self._database(name, report_sha256)
        record = storage.load_candidate(path, trigger_id)
        W.require(record['decision'] == 'candidate', 'This rejected trigger has no saved signal context.')
        context = record['context']
        event = stream.replay_readout_context(context)
        W.require(record['readout'] == event, 'Saved fast/slow measurements differ from the exact ADC context.')
        i = contact_id - 1
        codes = context['adc_codes'][i]
        centered = codes * digital._LSB_V - context['acquisition_baseline_v'][i]
        corrected = np.cumsum(centered - stream._ALPHA * np.pad(centered[:-1], (1, 0)))
        fast = digital._moving_average(corrected, pulse._FAST_SAMPLES)
        averaged = digital._moving_average(corrected, pulse._SLOW_RISE)
        slow = averaged - np.pad(averaged, (pulse._SLOW_RISE + pulse._SLOW_GAP, 0))[:len(codes)]
        times = (np.arange(context['first_sample_index'], context['stop_sample_index']) * stream.SAMPLE_PERIOD_NS
                 + context['adc_phase_ns'] - event['trigger_time_ns'])
        return {'kind': KIND, 'name': name, 'report_sha256': digest, 'trigger_id': trigger_id,
                'contact_id': contact_id, 'card': record['card'], 'identities': record['identities'],
                'channel': event['channels'][i], 'event_flags': event['flags'],
                'gates_ns': {'fast_area': digital._PROFILE['fast_area_gate_ns'],
                             'slow_energy': digital._PROFILE['slow_plateau_gate_ns']},
                'trace': {'time_ns': times.tolist(), 'adc_codes': codes.tolist(),
                          'preamp_V': (codes * digital._LSB_V).tolist(),
                          'fast_V': fast.tolist(), 'slow_keV': (slow / pulse._SLOW_GAIN).tolist()},
                'sample_period_ns': stream.SAMPLE_PERIOD_NS,
                'filter_scope': 'Fast voltage uses the saved local pole-zero reference; fast area subtracts its '
                                'recent quiet level. Slow energy uses the 880–980 ns gate and fixed pulser gain.'}

    def start(self, name, primary_count=100, seed=20261120, activities_bq=(185000, 37000),
              positions_mm=((-40, 0, 40), (40, 0, 40)), *, duration_s=None):
        directory = self._directory(name)
        if duration_s is None:
            W.require(type(primary_count) is int and primary_count > 0,
                      'Choose a positive integer number of new parent decays.')
        else:
            W.require(_finite(duration_s) and duration_s > 0,
                      'Choose a finite positive physical acquisition duration in seconds.')
        W.require(type(seed) is int and 1 <= seed <= 2147483646, 'Use an integer seed from 1 through 2147483646.')
        W.require(type(activities_bq) in (list, tuple) and len(activities_bq) == 2
                  and all(_finite(v) and v > 0 for v in activities_bq), 'Enter positive Cs-137 and Co-60 activities in Bq.')
        W.require(type(positions_mm) in (list, tuple) and len(positions_mm) == 2
                  and all(type(p) in (list, tuple) and len(p) == 3 and all(_finite(v) for v in p)
                          for p in positions_mm), 'Enter each source position as three finite detector coordinates in mm.')
        with self.workflow._lock:
            self.workflow._idle()
            W.require(name not in self.jobs and not directory.exists(), 'Choose a fresh acquisition name; existing data are preserved.')
            directory.mkdir(parents=True, exist_ok=False)
            job = {'name': name, 'status': 'running', 'primary_count': primary_count if duration_s is None else None,
                   'duration_s': duration_s, 'mode': 'count' if duration_s is None else 'duration',
                   'initial_state_policy': STARTUP_POLICY if duration_s is None else STEADY_POLICY, 'seed': seed,
                   'activities_bq': list(activities_bq), 'positions_mm': [list(p) for p in positions_mm],
                   'started_utc': W.utc(), 'output': OUTPUTS + '/' + name}
            self.jobs[name] = job
            return self._launch(job, resume=False)

    def _launch(self, job, *, resume):
        reservation = 'gegi-candidates-' + job['name']
        stop = threading.Event()
        self._stop_events[job['name']] = stop
        job.update(status='running', resumable=False,
                   progress={'status': 'running', 'stage': 'Resuming the saved acquisition' if resume
                             else 'Initializing the shared source acquisition'})
        job.pop('error', None)
        job.pop('finished_utc', None)
        if resume:
            job['resumed_utc'] = W.utc()
        self._persist()
        self.workflow._active = reservation
        thread = threading.Thread(target=self._work, args=(job, reservation, resume, stop),
                                  name=reservation, daemon=True)
        try:
            thread.start()
        except RuntimeError:
            self.workflow._active = None
            self._stop_events.pop(job['name'], None)
            job.update(status='failed', error='The acquisition worker did not start.', finished_utc=W.utc())
            self._persist()
            raise
        return copy.deepcopy(job)

    def stop(self, name):
        self._directory(name)
        with self.workflow._lock:
            job = self.jobs.get(name)
            W.require(job is not None and job['status'] in ('running', 'stop_requested')
                      and self.workflow._active == 'gegi-candidates-' + name,
                      'Choose the running fresh-source acquisition to stop.')
            self._stop_events[name].set()
            job['status'] = 'stop_requested'
            self._persist()
            return copy.deepcopy(job)

    def resume(self, name):
        directory = self._directory(name)
        with self.workflow._lock:
            self.workflow._idle()
            job = self.jobs.get(name)
            W.require(job is not None and job['status'] in ('stopped', 'interrupted', 'failed')
                      and not safe_path(directory, REPORT_NAME).exists() and self._resumable(directory),
                      'Choose an incomplete acquisition with a saved checkpoint to resume.')
            return self._launch(job, resume=True)

    def _work(self, job, reservation, resume, stop):
        directory = self._directory(job['name'])
        try:
            with W.execution_lease(self.root):
                W.verify_dispatch_reservations(None, self.root)
                runner = self.runner
                settings = {}
                if job.get('duration_s') is None:
                    settings['primary_count'] = job['primary_count']
                else:
                    settings['duration_s'] = job['duration_s']
                if runner is None:
                    from gegi_streaming_acquisition import run
                    runner = run
                    settings.update(resume=resume, stop_requested=stop.is_set,
                                    block_parents=10000 if job.get('duration_s') is not None else 50,
                                    initial_state_policy=job.get('initial_state_policy', STARTUP_POLICY))

                def progress(value):
                    with self.workflow._lock:
                        job['progress'] = {'stage': value} if isinstance(value, str) else value

                result = runner(directory, seed=job['seed'],
                                activities_bq=job['activities_bq'], positions_mm=job['positions_mm'],
                                on_progress=progress, **settings)
                if isinstance(result, dict) and result.get('status') == 'stopped':
                    W.require(result.get('resumable') is True and self._resumable(directory),
                              'The acquisition stopped without a durable checkpoint. Its files are preserved.')
                    outcome = {'status': 'stopped', 'resumable': True, 'results_available': False}
                else:
                    _, _, digest = self._report(job['name'])
                    outcome = {'status': 'completed', 'resumable': False,
                               'report_sha256': digest, 'results_available': True}
        except Exception as error:
            ordinal = 1
            filename = 'worker-error.log'
            while safe_path(directory, filename).exists():
                ordinal += 1
                filename = f'worker-error-{ordinal}.log'
            with safe_path(directory, filename).open('x', encoding='utf-8') as handle:
                handle.write(traceback.format_exc())
            outcome = {'status': 'failed', 'error': str(error)[:1200], 'error_log': filename}
        with self.workflow._lock:
            job.update(finished_utc=W.utc(), **outcome)
            try:
                self._persist()
            finally:
                self._stop_events.pop(job['name'], None)
                if self.workflow._active == reservation:
                    self.workflow._active = None
