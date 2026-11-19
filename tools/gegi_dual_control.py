"""Protected Control jobs for ADC replay from two imported GeGI source libraries."""

import copy
from hashlib import sha256
import math
import re
from sys import float_info
import threading

from gegi_pixel_map import project_pixel_map, read_pixel_map, unavailable
import scenario_workflow as W
from local_ui_jobs import ControlError, decode_json, safe_path


IMPORTS = '.local/gegi-saved-inputs/source-libraries'
OUTPUTS = '.local/gegi-dual-source'
STATE = '.local/local-control-v1/gegi-dual-source-jobs.json'
KIND = 'local_gegi_dual_source_jobs_v1'
REPORT_KIND = 'gegi_dual_source_acquisition_v1'
SOURCE_COUNTS = ('initial_parents_in_live_time', 'deposit_groups', 'complete_deposit_groups',
                 'right_censored_deposit_groups', 'native_unavailable_groups', 'prehistory_unqualified_groups')
ADC_COUNTS = ('qualified_triggers', 'single_pixel_energies', 'additional_multi_strip_energies',
              'qualified_energies', 'triggers_without_energy')
EXPOSURE = ('clock_live_time_ns', 'qualified_adc_live_time_ns', 'masked_live_time_ns',
            'total_live_adc_samples', 'qualified_live_adc_samples')


def number(value):
    return type(value) in (float, int) and abs(value) <= float_info.max and math.isfinite(value)


def discover(root, describe):
    """Offer verified immediate imports, using opaque IDs for run requests."""
    folder = safe_path(root, IMPORTS)
    libraries, rejected = {}, []
    if folder.is_dir():
        for child in sorted(folder.iterdir(), key=lambda item: item.name.casefold()):
            ref = f'{IMPORTS}/{child.name}'
            try:
                path = safe_path(root, ref)
                if not path.is_dir():
                    continue
                meta = describe(path)
                position = meta['source_position_mm']
                W.require(type(meta['isotope']) is str and len(position) == 3 and all(number(v) for v in position),
                          'Library has no verified isotope and source coordinates.')
                key = W.digest({'gegi_dual_source_import': ref, 'chunk_sha256': meta['chunk_sha256']})
                libraries[key] = (ref, {'id': key, 'label': child.name, 'isotope': meta['isotope'],
                                        'source_position_mm': position, 'original': meta['original'],
                                        'chunk_sha256': meta['chunk_sha256']})
            except (OSError, ValueError, TypeError, KeyError, ControlError) as error:
                rejected.append({'label': child.name, 'error': str(error)})
    return libraries, rejected


def report_ref(name):
    return f'{OUTPUTS}/{name}/report.json'


def discover_reports(root, recorded):
    """List direct report folders while leaving full validation to selection."""
    folder = safe_path(root, OUTPUTS)
    if not folder.is_dir():
        return []
    discovered = []
    for child in sorted(folder.iterdir(), key=lambda item: item.name.casefold()):
        name = child.name
        if name in recorded:
            continue
        try:
            W.run_path(name, root)
            if safe_path(root, report_ref(name)).is_file():
                discovered.append({'name': name, 'status': 'completed', 'archived_report': True})
        except (ControlError, OSError):
            continue
    return discovered


def spectrum_entries(spectrum):
    edges, counts = spectrum['bin_edges_keV'], spectrum['counts']
    W.require(len(edges) == len(counts) + 1 and len(counts) > 0 and all(type(x) is int for x in edges)
              and edges[1] > edges[0] and all(b-a == edges[1]-edges[0] for a, b in zip(edges, edges[1:]))
              and all(type(n) is int and n >= 0 for n in (*counts, spectrum['underflow'], spectrum['overflow']))
              and sum(counts) + spectrum['underflow'] + spectrum['overflow'] == spectrum['entries'],
              'Saved dual-source energy histogram has an invalid bin census.')
    return spectrum['entries']


def compact_report(report, job):
    """Keep the recorded census and spectra, leaving event arrays in the report."""
    W.require(report.get('kind') == REPORT_KIND and report.get('status') == 'completed',
              'The worker did not produce a completed dual-source acquisition.')
    counts = {key: report['counts'][key] for key in (*SOURCE_COUNTS, *ADC_COUNTS)}
    exposure = {key: report['exposure'][key] for key in EXPOSURE}
    design = report['design']
    originals = report['sources']
    W.require(design['clock_seed'] == int(job['seed']) and design['live_time_s'] == job['live_time_s']
              and len(originals) == 2 and all(r['activity_bq'] == activity
                  and r['original']['chunk_sha256'] == lib['chunk_sha256']
                  for r, activity, lib in zip(originals, job['activities_bq'], job['sources'], strict=True)),
              'The completed receipt differs from the selected saved sources or acquisition settings.')
    sources = [dict(parents=row['counts']['parents'], zero_parents=row['counts']['marked_zero_parents'],
                    deposit_groups=row['counts']['group_onsets_in_live_time']) for row in originals]
    W.require(sum(source['parents'] for source in sources) == counts['initial_parents_in_live_time']
              and counts['complete_deposit_groups'] + counts['right_censored_deposit_groups'] == counts['deposit_groups'],
              'Recorded parent and Ge deposit group counts do not close.')
    measured = exposure['qualified_live_adc_samples'] > 0
    spectra = report['spectra']
    if measured:
        W.require(counts['qualified_energies'] == counts['single_pixel_energies'] + counts['additional_multi_strip_energies']
                  and counts['qualified_triggers'] == counts['qualified_energies'] + counts['triggers_without_energy']
                  and spectrum_entries(spectra['single_pixel']) == counts['single_pixel_energies']
                  and spectrum_entries(spectra['additional_multi_strip']) == counts['additional_multi_strip_energies']
                  and spectrum_entries(spectra['combined']) == counts['qualified_energies'],
                  'Recorded trigger counts and spectrum population differ.')
    else:
        W.require(spectra is None and all(counts[key] is None for key in ADC_COUNTS),
                  'An exposure without qualified ADC time must retain unknown trigger counts.')
    return {'counts': counts, 'exposure': exposure, 'sources': sources, 'spectra': spectra}


def archived_report(root, name):
    """Read a stand-alone v1 report through the same view contract as a completed job."""
    reference = report_ref(name)
    try:
        body = safe_path(root, reference).read_bytes()
        report = decode_json(body.decode('utf-8-sig'))
        design, sources = report['design'], report['sources']
        W.require(type(design['clock_seed']) is int and 0 <= design['clock_seed'] < 2**64
                  and number(design['live_time_s']) and design['live_time_s'] > 0,
                  'Saved acquisition settings are invalid.')
        settings, activities = [], []
        for row in sources:
            activity, original = row['activity_bq'], row['original']
            isotope, location = original['isotope'], original['source_position_mm']
            W.require(number(activity) and activity >= 0 and type(isotope) is str
                      and len(location) == 3 and all(number(v) for v in location),
                      'Saved report is missing valid source measurements.')
            activities.append(activity)
            settings.append({'isotope': isotope, 'source_position_mm': location,
                             'chunk_sha256': original['chunk_sha256']})
        job = dict(name=name, status='completed', archived_report=True, output=reference,
                   report_sha256=sha256(body).hexdigest(), seed=str(design['clock_seed']),
                   live_time_s=design['live_time_s'], activities_bq=activities, sources=settings)
        job['result'] = compact_report(report, job)
        job['result']['pixel_map'] = project_pixel_map(report)
        return job
    except (AttributeError, ControlError, OSError, ValueError, TypeError, KeyError):
        raise ControlError('The saved acquisition report is unavailable or invalid.', 'invalid_gegi_dual_report') from None


class DualSourceControl:
    def __init__(self, workflow, *, describe=None, runner=None):
        self.workflow = workflow
        self.root = workflow.root
        self.describe = describe
        self.runner = runner
        self.state_path = safe_path(self.root, STATE)
        self.jobs = {}
        if self.state_path.is_file():
            state = W.read(self.state_path)
            W.require(state.get('kind') == KIND and type(state.get('jobs')) is list,
                      'Saved dual-source Control state is unsupported.')
            for job in state['jobs']:
                W.run_path(job['name'], self.root)
                if job['status'] == 'running':
                    try:
                        job.update(self._result(job))
                    except (OSError, ValueError, TypeError, KeyError, ControlError):
                        job.update(status='interrupted', error='The previous Control session ended. Inspect the saved attempt.')
                self.jobs[job['name']] = job

    def _imports(self):
        describe = self.describe
        if describe is None:
            from gegi_source_library import describe_source_library
            describe = describe_source_library
        return discover(self.root, describe)

    def options(self):
        libraries, rejected = self._imports()
        with self.workflow._lock:
            jobs = {j['name']: {'name': j['name'], 'status': j['status']} for j in self.jobs.values()}
        return {'kind': 'local_gegi_dual_source_options_v1', 'libraries': [item[1] for item in libraries.values()],
                'rejected': rejected, 'jobs': [*jobs.values(), *discover_reports(self.root, jobs)]}

    def _persist(self):
        W.write(self.state_path, {'kind': KIND, 'jobs': list(self.jobs.values())})

    def _result(self, job):
        output = safe_path(self.root, report_ref(job['name']))
        body = output.read_bytes()
        report = compact_report(decode_json(body.decode('utf-8-sig')), job)
        return dict(status='completed', result=report, report_sha256=sha256(body).hexdigest())

    def state(self, name):
        W.run_path(name, self.root)
        with self.workflow._lock:
            job = copy.deepcopy(self.jobs.get(name))
        if job is None:
            return archived_report(self.root, name)
        if job['status'] == 'completed':
            # Older completed jobs already retain their verified compact spectra.
            # Derive the map separately, without rewriting the report or job state.
            expected = job.get('report_sha256')
            pixel_map = unavailable('report_unverified')
            if type(expected) is str and re.fullmatch(r'[0-9a-f]{64}', expected):
                try:
                    output = safe_path(self.root, report_ref(name))
                except ControlError:
                    pass
                else:
                    pixel_map = read_pixel_map(output, expected_sha256=expected)
            job['result']['pixel_map'] = pixel_map
        return job

    def start(self, source_ids, activities_bq, live_time_s, seed, name):
        W.run_path(name, self.root)
        W.require(type(source_ids) is list and len(source_ids) == 2 and all(type(v) is str for v in source_ids),
                  'Choose two offered saved source libraries.')
        W.require(type(activities_bq) is list and len(activities_bq) == 2
                  and all(number(v) and v >= 0 for v in activities_bq), 'Enter two finite nonnegative activities in Bq.')
        W.require(number(live_time_s) and live_time_s > 0 and number(live_time_s*1e9),
                  'Enter a finite positive acquisition duration in seconds.')
        W.require(type(seed) is str and re.fullmatch(r'[0-9]{1,20}', seed) and int(seed) < 2**64,
                  'Enter an integer seed from 0 through 18446744073709551615.')
        libraries, _ = self._imports()
        W.require(all(key in libraries for key in source_ids), 'Choose two offered saved source libraries.')
        paths = [libraries[key][0] for key in source_ids]
        source_metadata = [libraries[key][1] for key in source_ids]
        output = safe_path(self.root, f'{OUTPUTS}/{name}')
        with self.workflow._lock:
            self.workflow._idle()
            W.require(name not in self.jobs and not output.exists(), 'Choose a fresh name. Existing acquisitions are preserved.')
            output.mkdir(parents=True, exist_ok=False)
            reservation = 'gegi-dual-' + name
            job = dict(name=name, status='running', sources=source_metadata, activities_bq=activities_bq,
                       live_time_s=live_time_s, seed=str(int(seed)), output=report_ref(name),
                       started_utc=W.utc())
            self.jobs[name] = job
            try:
                self._persist()
            except OSError:
                del self.jobs[name]
                raise
            self.workflow._active = reservation
            thread = threading.Thread(target=self._work, args=(job, paths, reservation), name=reservation, daemon=True)
            try:
                thread.start()
            except RuntimeError:
                self.workflow._active = None
                job.update(status='failed', error='Acquisition worker did not start.', finished_utc=W.utc())
                self._persist()
                raise
            return copy.deepcopy(job)

    def _work(self, job, paths, reservation):
        try:
            with W.execution_lease(self.root):
                W.verify_dispatch_reservations(None, self.root)
                runner = self.runner
                if runner is None:
                    from gegi_dual_source import run
                    runner = run
                sources = [safe_path(self.root, ref) for ref in paths]
                output = safe_path(self.root, job['output'])
                runner(sources, job['activities_bq'], job['live_time_s'], int(job['seed']), output)
                result = self._result(job)
        except Exception as error:
            result = dict(status='failed', error=str(error)[:1200])
        with self.workflow._lock:
            job.update(finished_utc=W.utc(), **result)
            try:
                self._persist()
            finally:
                if self.workflow._active == reservation:
                    self.workflow._active = None
