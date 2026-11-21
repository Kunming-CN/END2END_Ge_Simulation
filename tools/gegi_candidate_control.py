"""Protected Control jobs and bounded saved views for fresh mixed-source GeGI runs."""

import copy
from contextlib import closing
import gzip
from hashlib import sha256
import json
import math
import os
import re
import sqlite3
import threading
import traceback
import zlib

import numpy as np

import gegi_candidate_storage as storage
import gegi_digital_readout as digital
import gegi_exposure_stream as stream
import gegi_pulse_stream as pulse
from local_ui_jobs import safe_path, run_command
import scenario_workflow as W


OUTPUTS = '.local/gegi-candidate-runs'
STATE = '.local/local-control-v1/gegi-candidate-jobs.json'
KIND = 'local_gegi_candidate_control_v1'
REPORT_KIND = 'gegi_candidate_acquisition_v1'
REPORT_NAME = 'candidate-acquisition.json'
NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,47}\Z')
STARTUP_POLICY = 'new_parent_decays_empty_daughters_at_start'
STEADY_POLICY = 'secular_equilibrium_poisson_daughters_v1'
PLANE_KIND = 'gegi_continuous_measured_plane_backprojection_v1'
ANALYSIS_KIND = 'gegi_candidate_measured_imaging_v1'
PLANE_PRIORS = ('uniform-area', 'uniform-solid-angle')
MAP_NAME = re.compile(r'candidate-imaging(?:-[A-Za-z0-9_-]+)?\.json\.gz\Z')


def _name(value):
    W.require(type(value) is str and NAME.fullmatch(value), 'Use a new name of 1–48 letters, numbers, underscores or hyphens.')
    return value


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _matching_analysis(view, recipe):
    return (view['candidate_analysis']['scope'] == 'all_two_strip_candidates'
            and view['input_sha256']['calibration'] == recipe['calibration_sha256']
            and all(view['grid'][key] == recipe[arg] for key, arg in
                    (('assumed_z_mm', 'z_mm'), ('extent_mm', 'extent_mm'), ('step_mm', 'step_mm')))
            and view['model']['angular_nuisance_sigma_deg'] == recipe['sigma_deg']
            and view['model']['plane_prior'] == recipe['plane_prior'])


class CandidateControl:
    def __init__(self, workflow, *, runner=None, analysis_runner=None):
        self.workflow = workflow
        self.root = workflow.root
        self.runner = runner
        self.analysis_runner = analysis_runner or run_command
        self._analysis_cache = {}
        self._analysis_running = set()
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
                analysis = job.get('analysis')
                if analysis and analysis['status'] == 'running' and not W.identity_ended(analysis.get('driver')):
                    self.workflow._active = 'gegi-candidate-imaging-' + job['name']

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
        return {'kind': KIND, 'jobs': list(jobs.values()), 'calibrations': self._calibrations(), 'defaults': {
            'mode': 'duration', 'duration_s': 5, 'maximum_duration_s': None,
            'primary_count': 100, 'maximum_primary_count': None, 'seed': 20261120,
            'activities_bq': [185000, 37000], 'positions_mm': [[-40, 0, 40], [40, 0, 40]]},
            'new_science_calls': 0}

    def _calibrations(self):
        refs = ['.local/gegi-center-calibration.npz',
                '.local/gegi-joint-two-site/gegi-center-calibration.npz']
        imports = safe_path(self.root, '.local/gegi-saved-inputs/calibrations')
        if imports.is_dir():
            refs += [p.relative_to(self.root).as_posix() for p in sorted(imports.glob('*.npz'))]
        return [{'id': W.digest({'candidate_calibration': ref}), 'label': ref, 'ref': ref}
                for ref in refs if safe_path(self.root, ref).is_file()]

    def _analysis_view(self, path, report, digest):
        try:
            return self._checked_analysis_view(path, report, digest)
        except W.ControlError:
            raise
        except (EOFError, KeyError, OSError, OverflowError, TypeError, ValueError, zlib.error) as error:
            raise W.ControlError('The saved candidate imaging result is invalid; preserve it for inspection.') from error

    def _checked_analysis_view(self, path, report, digest):
        stamp = path.stat()
        signature = (stamp.st_size, stamp.st_mtime_ns, digest)
        cached = self._analysis_cache.get(path)
        if cached and cached[0] == signature:
            return copy.deepcopy(cached[1])
        raw = path.read_bytes()
        saved = json.loads(gzip.decompress(raw))
        analysis = saved['candidate_analysis']
        grid, model, layers, selection = (saved[key] for key in ('grid', 'model', 'layers', 'selection'))
        W.require(saved['kind'] == PLANE_KIND and analysis['kind'] == ANALYSIS_KIND
                  and saved['input_sha256']['acquisition'] == digest
                  and saved['input_sha256']['candidate_store'] == report['artifacts'][storage.ARCHIVE_NAME]['sha256']
                  and analysis['qualified_counts'] == report['counts']
                  and analysis['storage_counts'] == report['storage_counts']
                  and analysis['source_census'] == report.get('source', {})
                  and analysis['excluded_intervals_ns'] == report.get('excluded_intervals_ns', []),
                  'Saved imaging and acquisition identities or denominators differ.')
        W.require(analysis['scope'] in ('all_two_strip_candidates', 'explicit_analysis_subset')
                  and selection['qualified_triggers'] == report['counts']['qualified_triggers']
                  and selection['qualified_energies'] == report['counts']['qualified_energies']
                  and selection['two_strip_triggers'] == analysis['two_strip_candidates']
                  and len(saved['triggers']) == analysis['two_strip_candidates']
                  and all(type(row['original_trigger_id']) is int and row['original_trigger_id'] > 0 for row in saved['triggers'])
                  and saved['fit_receipt']['kind'] == 'gegi_candidate_measured_waveform_fits_v1'
                  and saved['fit_receipt']['two_strip_triggers'] == analysis['two_strip_candidates']
                  and len({row['original_trigger_id'] for row in saved['triggers']}) == len(saved['triggers']),
                  'Saved imaging trigger identities or scope differ.')
        W.require(selection['clock_live_time_ns'] == report['live_time_ns']
                  and math.isclose(selection['qualified_adc_live_time_ns'], report['live_time_ns'] -
                      math.fsum(hi-lo for lo, hi in report.get('excluded_intervals_ns', [])), abs_tol=1e-6),
                  'Saved imaging unknown-history or live-time denominator differs.')
        ids = analysis['selected_original_trigger_ids']
        W.require(all(type(tid) is int and tid > 0 for tid in ids) and len(ids) == len(set(ids))
                  and set(ids) <= {row['original_trigger_id'] for row in saved['triggers']}
                  and (analysis['scope'] != 'all_two_strip_candidates' or len(ids) == analysis['two_strip_candidates']),
                  'Saved imaging selected trigger IDs differ.')
        nx, ny = len(grid['x_mm']), len(grid['y_mm'])
        W.require(min(nx, ny) >= 2 and _finite(grid['assumed_z_mm']) and _finite(grid['step_mm'])
                  and grid['step_mm'] > 0 and model['plane_prior'] in PLANE_PRIORS,
                  'Invalid saved source-plane grid.')
        for axis in ('x_mm', 'y_mm'):
            W.require(all(_finite(v) for v in grid[axis]) and all(math.isclose(b-a, grid['step_mm'], rel_tol=1e-8)
                      for a, b in zip(grid[axis], grid[axis][1:])), 'Invalid saved source-plane axis.')
        W.require('all' in layers and 'other_energy' in layers, 'Missing saved source-plane layers.')
        for layer in layers.values():
            W.require(all(type(layer[key]) is int and layer[key] >= 0 for key in
                          ('triggers', 'triggers_with_geometry', 'allowed_hypotheses', 'hypotheses'))
                      and all(_finite(layer[key]) and layer[key] >= 0 for key in ('projected_mass', 'unresolved_mass'))
                      and len(layer['mass']) == ny and all(len(row) == nx and all(_finite(v) and v >= 0 for v in row)
                          for row in layer['mass'])
                      and math.isclose(math.fsum(v for row in layer['mass'] for v in row), layer['projected_mass'], abs_tol=1e-9)
                      and math.isclose(layer['projected_mass']+layer['unresolved_mass'], layer['triggers'], abs_tol=1e-9),
                      'Saved source-plane mass or dimensions differ.')
        W.require(layers['all']['triggers'] == analysis['two_strip_candidates'], 'Saved plane trigger denominator differs.')
        for key in ('triggers', 'triggers_with_geometry', 'allowed_hypotheses', 'hypotheses', 'projected_mass', 'unresolved_mass'):
            W.require(math.isclose(layers['all'][key], math.fsum(row[key] for label, row in layers.items() if label != 'all'), abs_tol=1e-9),
                      'Saved plane energy layers do not reconcile.')
        view = {key: saved[key] for key in ('kind', 'grid', 'model', 'layers', 'selection', 'candidate_analysis', 'input_sha256')}
        view['original_trigger_ids'] = [row['original_trigger_id'] for row in saved['triggers']]
        view.update(analysis_id=path.name, analysis_sha256=sha256(raw).hexdigest())
        self._analysis_cache[path] = (signature, view)
        return copy.deepcopy(view)

    def _analysis_maps(self, name, report, digest):
        maps = []
        active = self.jobs.get(name, {}).get('analysis')
        for path in sorted(self._directory(name).glob('candidate-imaging*.json.gz')):
            if not MAP_NAME.fullmatch(path.name):
                continue
            if (active and active['status'] == 'running' and active['analysis_id'] == path.name
                    and (name in self._analysis_running or not W.identity_ended(active.get('driver')))):
                continue
            view = self._analysis_view(safe_path(self._directory(name), path.name), report, digest)
            maps.append({key: view[key] for key in ('analysis_id', 'analysis_sha256')} | {
                'scope': view['candidate_analysis']['scope'], 'z_mm': view['grid']['assumed_z_mm'],
                'plane_prior': view['model']['plane_prior']})
        return sorted(maps, key=lambda row: (row['scope'] != 'all_two_strip_candidates', row['analysis_id']))

    def analysis_plane(self, name, report_sha256, analysis_id, analysis_sha256):
        W.require(type(analysis_id) is str and MAP_NAME.fullmatch(analysis_id), 'Choose one saved candidate imaging result.')
        _, report, digest = self._database(name, report_sha256)
        view = self._analysis_view(safe_path(self._directory(name), analysis_id), report, digest)
        W.require(view['analysis_sha256'] == analysis_sha256, 'Saved imaging changed. Reopen its saved result.')
        return dict(name=name, report_sha256=digest, **view)

    def analyze(self, name, report_sha256, calibration_id, z_mm, extent_mm=120., step_mm=4., sigma_deg=5., plane_prior='uniform-area'):
        W.require(all(_finite(v) for v in (z_mm, extent_mm, step_mm, sigma_deg))
                  and extent_mm > 0 and 0 < step_mm <= 2*extent_mm and sigma_deg > 0
                  and plane_prior in PLANE_PRIORS and (plane_prior != 'uniform-solid-angle' or z_mm != 0),
                  'Choose finite plane settings with positive extent, grid spacing and angular width.')
        directory, report, digest = self._report(name, report_sha256)
        W.require(report.get('verification', {}).get('status') == 'verified_exact',
                  'Choose a completed acquisition with exact saved-candidate verification.')
        calibration = next((row for row in self._calibrations() if row['id'] == calibration_id), None)
        W.require(calibration is not None, 'Import the separate matching GeGI calibration and refresh the input list.')
        settings = dict(z_mm=z_mm, extent_mm=extent_mm, step_mm=step_mm, sigma_deg=sigma_deg, plane_prior=plane_prior)
        recipe = dict(report_sha256=digest, calibration_sha256=W.sha(safe_path(self.root, calibration['ref'])), **settings)
        with self.workflow._lock:
            for row in self._analysis_maps(name, report, digest):
                view = self._analysis_view(safe_path(directory, row['analysis_id']), report, digest)
                if _matching_analysis(view, recipe):
                    return {'status': 'completed', 'reused': True, **row}
            self.workflow._idle()
            stem = 'candidate-imaging-' + W.digest(recipe)
            filename = stem + '.json.gz'
            attempt = 1
            while safe_path(directory, filename).exists() or safe_path(directory, filename+'.log').exists():
                attempt += 1
                filename = stem + '-attempt' + str(attempt) + '.json.gz'
            job = self.jobs.setdefault(name, {'name': name, 'status': 'completed', 'report_sha256': digest})
            analysis = dict(status='running', started_utc=W.utc(), analysis_id=filename,
                            calibration_ref=calibration['ref'], **recipe)
            job['analysis'] = analysis
            reservation = 'gegi-candidate-imaging-' + name
            self.workflow._active = reservation
            self._analysis_running.add(name)
            self._persist()
            thread = threading.Thread(target=self._analysis_work, args=(job, analysis, reservation), daemon=True, name=reservation)
            try:
                thread.start()
            except RuntimeError:
                self.workflow._active = None
                self._analysis_running.discard(name)
                analysis.update(status='failed', error='The imaging worker did not start.')
                self._persist()
                raise
            return copy.deepcopy(analysis)

    def _analysis_work(self, job, analysis, reservation):
        directory = self._directory(job['name'])
        log = safe_path(directory, analysis['analysis_id'] + '.log')
        try:
            with W.execution_lease(self.root):
                W.verify_dispatch_reservations(None, self.root)
                prefix = '../' + directory.relative_to(self.root).as_posix() + '/'
                argv = W.transport_prefix(self.root) + ['env', 'OPENBLAS_NUM_THREADS=1', 'OMP_NUM_THREADS=1',
                    'python', '-B', '../tools/gegi_candidate_imaging.py',
                    '--report', prefix+REPORT_NAME, '--calibration', '../'+analysis['calibration_ref'],
                    '--output', prefix+analysis['analysis_id']]
                for key, flag in (('z_mm','--plane-z-mm'),('extent_mm','--extent-mm'),('step_mm','--step-mm'),
                                  ('sigma_deg','--sigma-deg'),('plane_prior','--plane-prior')):
                    argv += [flag, str(analysis[key])]
                def spawned(pid, identity):
                    with self.workflow._lock:
                        analysis['driver'] = dict(pid=pid, identity=identity)
                        self._persist()
                with log.open('x', encoding='utf-8') as handle:
                    result = self.analysis_runner(argv, cwd=self.root, env=os.environ.copy(), on_output=handle.write, on_spawn=spawned)
                W.require(result['exit_code'] == 0, 'Saved-candidate imaging failed. Inspect its retained analysis log.')
                _, report, digest = self._report(job['name'], analysis['report_sha256'])
                view = self._analysis_view(safe_path(directory, analysis['analysis_id']), report, digest)
                W.require(_matching_analysis(view, analysis), 'The imaging worker changed the requested full-analysis recipe.')
                analysis.update(status='completed', analysis_sha256=view['analysis_sha256'])
        except Exception as error:
            analysis.update(status='failed', error=str(error)[:1200])
        finally:
            with self.workflow._lock:
                analysis['finished_utc'] = W.utc()
                self._persist()
                self._analysis_running.discard(job['name'])
                if self.workflow._active == reservation:
                    self.workflow._active = None

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
        reference_positions = [source.get('source_position_mm', source.get('position_global_mm'))
                               for source in reference['provenance']['sources']]
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
            job['analysis_maps'] = self._analysis_maps(name, report, digest)
            analysis = job.get('analysis')
            if (analysis and analysis['status'] == 'running' and name not in self._analysis_running
                    and W.identity_ended(analysis.get('driver'))):
                saved = next((row for row in job['analysis_maps'] if row['analysis_id'] == analysis['analysis_id']), None)
                analysis.update(status='completed' if saved else 'failed', finished_utc=W.utc())
                if saved:
                    analysis['analysis_sha256'] = saved['analysis_sha256']
                else:
                    analysis['error'] = 'The previous analysis session ended without a completed map; its evidence is preserved.'
                self.jobs[name]['analysis'] = copy.deepcopy(analysis)
                self._persist()
                if self.workflow._active == 'gegi-candidate-imaging-' + name:
                    self.workflow._active = None
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
