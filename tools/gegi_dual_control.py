"""Protected Control jobs for ADC replay from two imported GeGI source libraries."""

import copy
from hashlib import sha256
from itertools import islice
import math
import re
from sys import float_info
import threading

from gegi_pixel_map import X_IDS, Y_IDS, project_pixel_energy, project_pixel_map, unavailable
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
TRIGGER_THRESHOLDS = {'standard': 5.0, 'low-energy': 4.0}
CALIBRATED_POSITION_STATUSES = ('estimated', 'partial', 'unavailable')


def number(value):
    return type(value) in (float, int) and abs(value) <= float_info.max and math.isfinite(value)


def trigger_settings(profile):
    W.require(type(profile) is str and profile in TRIGGER_THRESHOLDS,
              'Choose the Standard or Low-energy trigger profile.')
    return dict(id=profile, coincidence_threshold_keV_per_sample=TRIGGER_THRESHOLDS[profile],
                quiet_threshold_keV_per_sample=3.0, sample_period_ns=20)


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
    trigger = design.get('trigger_profile', trigger_settings('standard'))
    W.require(type(trigger) is dict and trigger == trigger_settings(trigger.get('id'))
              and report.get('receipt', {}).get('trigger_profile', trigger) == trigger
              and design.get('sample_period_ns', trigger['sample_period_ns']) == trigger['sample_period_ns'],
              'The saved trigger profile and thresholds disagree.')
    W.require(job.get('archived_report') or trigger['id'] == job.get('trigger_profile', 'standard'),
              'The completed receipt used a different trigger profile from the selected acquisition.')
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
    return {'counts': counts, 'exposure': exposure, 'sources': sources, 'spectra': spectra, 'trigger_profile': trigger}


def load_report(root, name, expected_sha256=None):
    """Read once and verify the same bytes used for every displayed derivative."""
    try:
        body = safe_path(root, report_ref(name)).read_bytes()
    except ControlError:
        raise ControlError('The saved report could not be verified.', 'report_unverified') from None
    except OSError:
        raise ControlError('The saved report is missing.', 'report_missing') from None
    digest = sha256(body).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise ControlError('The saved report differs from its completion receipt.', 'report_changed')
    try:
        report = decode_json(body.decode('utf-8-sig'))
        if type(report) is not dict:
            raise ValueError('Expected a JSON object')
    except ValueError:
        raise ControlError('The saved acquisition report is invalid.', 'invalid_report') from None
    return report, digest


def trigger_face(face, collecting, contact_ids):
    contact, slow, ratio = (face[key] for key in ('contact_id', 'slow_energy_keV', 'fast_ratio'))
    W.require(collecting == [contact] and type(contact) is int and contact in contact_ids
              and number(slow) and slow > 0 and (ratio is None or number(ratio)),
              'Invalid collecting-strip measurement.')
    result = dict(contact_id=contact, slow_energy_keV=slow, fast_ratio=ratio)
    if 'preamp_cfd50_ns' in face:
        cfd = face['preamp_cfd50_ns']
        W.require(cfd is None or number(cfd), 'Invalid collector preamplifier timing.')
        result['preamp_cfd50_ns'] = cfd
    for side, adjacent in (('low', contact - 1), ('high', contact + 1)):
        neighbor = face[side]
        if adjacent not in contact_ids:
            W.require(neighbor is None, 'A strip edge has no physical neighbor on this side.')
            result[side] = None
            continue
        value, flags = neighbor['fast_keV_equiv'], neighbor['flags']
        W.require(type(neighbor['contact_id']) is int and neighbor['contact_id'] == adjacent
                  and (value is None or number(value)) and type(flags) is list
                  and all(isinstance(flag, str) for flag in flags),
                  'Invalid neighboring-strip measurement.')
        result[side] = dict(contact_id=adjacent, fast_keV_equiv=value, flags=flags)
    return result


def nominal_position_record(position):
    status, energy_scope = position['status'], position['energy_scope']
    W.require(status in (*CALIBRATED_POSITION_STATUSES, 'uncalibrated_pixel', 'unconfirmed_field')
              and (energy_scope in ('within_tested_range', 'outside_tested_range')
                   or energy_scope == 'not_applicable' and status in ('uncalibrated_pixel', 'unconfirmed_field')),
              'Invalid nominal position status.')
    result = dict(status=status, energy_scope=energy_scope)
    if 'method' in position:
        method = position['method']
        W.require(method in ('direct_strip_calibration', 'family_template_transfer'), 'Invalid nominal position method.')
        result['method'] = method
    if 'tested_energies_keV' in position:
        energies = position['tested_energies_keV']
        W.require(type(energies) is list and all(number(energy) and energy > 0 for energy in energies),
                  'Invalid tested energies for nominal position.')
        result['tested_energies_keV'] = energies
    if status in CALIBRATED_POSITION_STATUSES:
        coordinates = position['position_mm']
        W.require(coordinates is None or (type(coordinates) is list and len(coordinates) == 3
                  and all(number(value) for value in coordinates)), 'Invalid nominal position coordinates.')
        axes = {}
        for key in ('x', 'y', 'z'):
            axis = position['axes'][key]
            value, reason = axis['position_mm'], axis['status']
            W.require(type(reason) is str and (value is None or number(value)), 'Invalid nominal position axis.')
            axes[key] = dict(position_mm=value, status=reason)
            if 'slot' in axis:
                slot = axis['slot']
                W.require(slot is None or (type(slot) is int and slot >= 0), 'Invalid nominal position table index.')
                axes[key]['slot'] = slot
        result.update(position_mm=coordinates, axes=axes)
    return result


def single_pixel_rows(report):
    return (row for row in report['triggers'] if row['single_pixel_energy_keV'] is not None)


def single_pixel_record(report, ordinal):
    """Select one hit in ledger order, leaving all other rows in the report."""
    row = next(islice(single_pixel_rows(report), ordinal - 1, ordinal), None)
    W.require(row is not None, 'The selected single-pixel trigger is missing.')
    if 'single_pixel_features' not in row:
        return None
    features = row['single_pixel_features']
    time, energy = row['trigger_time_ns'], row['single_pixel_energy_keV']
    W.require(number(time) and time >= 0 and number(energy) and energy > 0
              and row['additional_multi_strip_energy_keV'] is None and not row['guard_contact_ids'],
              'Invalid single-pixel trigger measurement.')
    result = dict(ordinal=ordinal, trigger_time_ns=time, single_pixel_energy_keV=energy,
                  x=trigger_face(features['x'], row['x_collecting_strips'], X_IDS),
                  y=trigger_face(features['y'], row['y_collecting_strips'], Y_IDS))
    if 'nominal_position' in row:
        result['nominal_position'] = nominal_position_record(row['nominal_position'])
    return result


def two_strip_rows(report):
    return (row for row in report['triggers'] if row.get('two_strip_pairings') is not None)


def two_strip_record(row, ordinal):
    time, energy = row['trigger_time_ns'], row['additional_multi_strip_energy_keV']
    xs, ys = row['x_collecting_strips'], row['y_collecting_strips']
    W.require(number(time) and time >= 0 and number(energy) and energy > 0
              and row['single_pixel_energy_keV'] is None and not row['guard_contact_ids']
              and len(xs) == len(set(xs)) == 2 and all(type(cid) is int and cid in X_IDS for cid in xs)
              and len(ys) == len(set(ys)) == 2 and all(type(cid) is int and cid in Y_IDS for cid in ys),
              'Invalid two-strip trigger measurement.')
    raw = row['two_strip_pairings']
    pairings, flags = [], raw['flags']
    W.require(type(flags) is list and all(type(flag) is str for flag in flags)
              and [pair['index'] for pair in raw['pairings']] == [0, 1],
              'Invalid two-strip pairing alternatives.')
    site_fields = ('x_contact_id', 'y_contact_id', 'x_energy_keV', 'y_energy_keV', 'energy_keV')
    order_fields = ('site_index_order', 'kinematically_allowed', 'half_angle_deg', 'cos_theta')
    for pair, y_order in zip(raw['pairings'], (ys, ys[::-1]), strict=True):
        sites = [{key: site[key] for key in site_fields} for site in pair['sites']]
        compatible = pair['energy_compatible']
        orders = [{key: order[key] for key in order_fields} for order in pair['compton_orders']]
        W.require(type(compatible) is bool and [site['x_contact_id'] for site in sites] == xs
                  and [site['y_contact_id'] for site in sites] == y_order
                  and all(number(s[key]) and s[key] > 0 for s in sites for key in site_fields[2:])
                  and [order['site_index_order'] for order in orders] == ([[0, 1], [1, 0]] if compatible else []),
                  'Invalid two-strip pairing measurements.')
        for order in orders:
            allowed, angle = order['kinematically_allowed'], order['half_angle_deg']
            W.require(type(allowed) is bool and number(order['cos_theta'])
                      and (number(angle) and 0 <= angle <= 180 if allowed else angle is None),
                      'Invalid measured-energy Compton order.')
        pairings.append(dict(index=pair['index'], energy_compatible=compatible, sites=sites, compton_orders=orders))
    count = sum(pair['energy_compatible'] for pair in pairings)
    W.require(raw['compatible_pairing_count'] == count, 'Two-strip pairing count disagrees with its alternatives.')
    return dict(ordinal=ordinal, trigger_time_ns=time, energy_keV=energy,
                two_strip_pairings=dict(compatible_pairing_count=count, pairings=pairings, flags=flags))


def report_views(report=None, *, reason=None):
    pixels = unavailable(reason) if reason else project_pixel_map(report)
    features = dict(status='unavailable', reason=pixels['reason'])
    if pixels['status'] == 'available':
        try:
            trigger = single_pixel_record(report, 1)
            if trigger is None and not report['design'].get('single_pixel_features'):
                features['reason'] = 'not_captured'
            else:
                gate = report['design']['single_pixel_features']['fast_area_gate_ns']
                W.require(trigger is not None and type(gate) is list and len(gate) == 2
                          and all(number(bound) for bound in gate) and gate[0] < gate[1],
                          'Invalid fast-area gate.')
                features = dict(status='available', count=pixels['totals']['mapped_single_pixel_triggers'],
                                fast_area_gate_ns=gate, trigger=trigger)
                calibrated_ordinals = []
                for ordinal, row in enumerate(single_pixel_rows(report), 1):
                    position = row.get('nominal_position')
                    if type(position) is dict and position.get('status') in CALIBRATED_POSITION_STATUSES and 'axes' in position:
                        calibrated_ordinals.append(ordinal)
                if calibrated_ordinals:
                    features['calibrated_ordinals'] = calibrated_ordinals
        except (ControlError, KeyError, TypeError):
            features['reason'] = 'invalid_features'
    views = dict(pixel_map=pixels, single_pixel_features=features)
    if pixels['status'] in ('available', 'empty') and 'two_strip_pairings' in report['design']:
        try:
            rows = two_strip_rows(report)
            first = next(rows, None)
            views['two_strip_pairings'] = (dict(status='empty', count=0) if first is None else
                                          dict(status='available', count=1 + sum(1 for _ in rows),
                                               trigger=two_strip_record(first, 1)))
        except (ControlError, KeyError, TypeError):
            views['two_strip_pairings'] = dict(status='unavailable')
    return views


def archived_report(root, name):
    """Read a stand-alone v1 report through the same view contract as a completed job."""
    reference = report_ref(name)
    try:
        report, digest = load_report(root, name)
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
                   report_sha256=digest, seed=str(design['clock_seed']),
                   live_time_s=design['live_time_s'], activities_bq=activities, sources=settings)
        job['result'] = compact_report(report, job)
        job['trigger_profile'] = job['result']['trigger_profile']['id']
        job['result'].update(report_views(report))
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
        report, digest = load_report(self.root, job['name'])
        return dict(status='completed', result=compact_report(report, job), report_sha256=digest)

    def state(self, name):
        W.run_path(name, self.root)
        with self.workflow._lock:
            job = copy.deepcopy(self.jobs.get(name))
        if job is None:
            return archived_report(self.root, name)
        profile = job.setdefault('trigger_profile', 'standard')
        if job['status'] == 'completed':
            job['result'].setdefault('trigger_profile', trigger_settings(profile))
            # Older completed jobs already retain their verified compact spectra.
            # Project the views from the report without rewriting the job state.
            expected = job.get('report_sha256')
            views = None
            if type(expected) is str and re.fullmatch(r'[0-9a-f]{64}', expected):
                try:
                    report, _ = load_report(self.root, name, expected)
                except ControlError as error:
                    views = report_views(reason=error.code)
                else:
                    views = report_views(report)
            job['result'].update(views if views is not None else report_views(reason='report_unverified'))
        return job

    def _opened_report(self, name, expected_sha256):
        W.run_path(name, self.root)
        W.require(re.fullmatch(r'[0-9a-f]{64}', expected_sha256), 'Reopen the saved acquisition.')
        with self.workflow._lock:
            job = self.jobs.get(name)
            W.require(job is None or (job['status'] == 'completed' and job.get('report_sha256') == expected_sha256),
                      'The selected acquisition differs from the completed job. Reopen it.')
        return load_report(self.root, name, expected_sha256)

    def pixel_energy(self, name, expected_sha256, window, pixel):
        report, digest = self._opened_report(name, expected_sha256)
        return dict(name=name, report_sha256=digest, **project_pixel_energy(report, window, pixel))

    def single_pixel(self, name, expected_sha256, ordinal):
        return self.selected_trigger(name, expected_sha256, ordinal, 'single-pixel')

    def selected_trigger(self, name, expected_sha256, ordinal, mode):
        W.require(re.fullmatch(r'[1-9][0-9]{0,15}', ordinal),
                  'Choose one trigger from the opened acquisition.')
        ordinal = int(ordinal)
        report, digest = self._opened_report(name, expected_sha256)
        try:
            W.require(report['kind'] == REPORT_KIND and report['status'] == 'completed',
                      'Choose a completed saved acquisition.')
            if mode == 'single-pixel':
                count = report['counts']['single_pixel_energies']
                W.require(type(count) is int and ordinal <= count,
                          'Choose a single-pixel trigger number in the saved acquisition.')
                trigger = single_pixel_record(report, ordinal)
                W.require(trigger is not None, 'This report predates capture of single-pixel fast readings.')
            else:
                W.require(mode == 'two-strip' and 'two_strip_pairings' in report['design'],
                          'This report has no recorded two-strip pairings.')
                row = next(islice(two_strip_rows(report), ordinal - 1, ordinal), None)
                W.require(row is not None, 'Choose a two-strip trigger number in the saved acquisition.')
                trigger = two_strip_record(row, ordinal)
        except (KeyError, TypeError):
            raise ControlError('The saved trigger measurement is invalid.', 'invalid_features') from None
        return dict(name=name, report_sha256=digest, trigger=trigger)

    def start(self, source_ids, activities_bq, live_time_s, seed, name, trigger_profile='standard'):
        W.run_path(name, self.root)
        trigger_settings(trigger_profile)
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
                       live_time_s=live_time_s, seed=str(int(seed)), trigger_profile=trigger_profile, output=report_ref(name),
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
                runner(sources, job['activities_bq'], job['live_time_s'], int(job['seed']), output,
                       trigger_profile=job['trigger_profile'])
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
