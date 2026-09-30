"""Bounded, read-only native_campaign_v1 saved-charge inspection (stdlib only).

inspect_run is the shared API. It never launches a process or writes a file.
Storage integrity, source compatibility and replay capability are independent.
See CHARGE_REUSE.md for the deliberately narrow policy and resource limits.
"""
import argparse
from contextlib import contextmanager
import csv
import ctypes
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import re
import stat
import sys

MAX_FILE = 128 * 1024 * 1024
MAX_TOTAL = 512 * 1024 * 1024
MAX_JSON = 4 * 1024 * 1024
MAX_LINE = 2 * 1024 * 1024
MAX_ROWS = 2_000_000
ARTIFACTS = set('endpoints.csv endpoints.jsonl histograms.csv histograms.json input-contract.json input-prepared.json profile-input.json profile.json readout-config.json scalars.csv scalars.jsonl signals.csv summary.html traces.jsonl truth.csv truth.jsonl'.split())
SOURCES = set('Manifest.toml Project.toml native_boundary_guard.jl native_li_example.jl native_response.jl native_response_guarded.jl native_stream.jl readout.jl readout_demo.json readout_profiles.jl replay.jl run.jl test_native_response.jl test_native_stream.jl test_readout_profiles.jl'.split())
STREAM_SOURCES = set('CMakeLists.txt cryostat-source.json cryostat_export.cc cryostat_nominal.json cs137.py handoff.py pixi.lock pixi.toml'.split())
GROUPING = dict(activity_live_time_pileup_claim=False, horizon_ns=100000,
                interval='[origin, origin+horizon)', name='nominal_isolated_windows_v1',
                state_at_group_start='reset', tail='truncate at horizon; recovery not established')
UNITS = dict(charge='fC', current='nA', voltage='V', energy='keV', time='ns')
SIGNAL_COLUMNS = ['event_id', 'global_decay_id', 'group_id', 'time_since_origin_ns', 'induced_equivalent_energy_keV']
COUNT_KEYS = set('accepted analog_samples decay_photons groups initial_decays initial_primaries line_photons native_charge_samples native_failed_groups readout_rejected rejected saturated zero_deposit_primaries'.split())
IDENTITY_FIELDS = set('event_id global_decay_id group_id raw_row_index parcel_index readout_contact_id evtid track_id parent_track_id trackid parent_trackid vertexid n_part schema_version seed_family parcels primary_count events_per_model pulse_count input_sample_count original_sample_count samples'.split())
IDENTITY_LISTS = {'row_indices', 'raw_row_indices', 'global_decay_id_range', 'contact_ids'}
# Existing Get-ESSources contract, including its two frozen default inputs.
ES_SOURCES = set('tools/electronics_settings.ps1 tools/native_run_validation.ps1 tools/scenario_cli.ps1 simulation/readout_profiles.jl simulation/readout.jl simulation/Project.toml simulation/Manifest.toml simulation/readout_demo.json simulation/native_readout_profile.json'.split())
ES_DEFAULTS = {'simulation/readout_demo.json': '33eb64724736c78852795ea001889759152ffefc22de9c4db6815fd1aaf8ee9e',
               'simulation/native_readout_profile.json': '7556e6e77d6c21e76e1a4eabb69b2b26875517252c083c88b6eb6a80502ef6e6'}


class Rejected(Exception):
    def __init__(self, code, detail):
        self.code, self.detail = code, str(detail)
        super().__init__(self.detail)


def require(value, detail, code='inconsistent_saved_data'):
    if not value:
        raise Rejected(code, detail)


def object_value(value, label):
    require(isinstance(value, dict), label + ': JSON object required', 'invalid_json')
    return value


def fields(value, keys, label):
    equal(set(object_value(value, label)), set(keys), label + ' keys')


def array_value(value, label):
    require(isinstance(value, list), label + ': JSON array required', 'invalid_json')
    return value


def integer(value, label, low=0, high=MAX_ROWS):
    require(type(value) is int and low <= value <= high, label + ': strict integer out of range')
    return value


def number(value, label):
    finite = False
    if type(value) in (int, float):
        try:
            finite = math.isfinite(value)
        except OverflowError:
            pass
    require(finite, label + ': finite number required')
    return value


def close(a, b, label, absolute=1e-9):
    number(a, label)
    number(b, label)
    # Large absolute decay clocks must not turn relative tolerance into a
    # sub-nanosecond origin override. Permit two representable float steps only.
    tolerance = 2 * max(math.ulp(float(a)), math.ulp(float(b))) if absolute == 0 else absolute
    require(math.isclose(a, b, rel_tol=0 if absolute == 0 else 1e-12, abs_tol=tolerance), label + ': numerical mismatch')


def equal(a, b, label):
    # Python bool == 1 is unsuitable for JSON contracts. Float spelling is not identity.
    if isinstance(a, dict) and isinstance(b, dict):
        require(a.keys() == b.keys(), label + ': field inventory mismatch')
        for k in a:
            equal(a[k], b[k], label + '.' + k)
    elif isinstance(a, list) and isinstance(b, list):
        require(len(a) == len(b), label + ': length mismatch')
        for x, y in zip(a, b):
            equal(x, y, label)
    else:
        require((type(a) is type(b) or type(a) in (int, float) and type(b) in (int, float)) and a == b, label + ': mismatch')


def pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, 'duplicate JSON key: ' + key, 'invalid_json')
        # Input raw_tables.columns also uses ID names for schema descriptors,
        # not values. Actual consumed IDs still pass contextual integer checks.
        column_schema = (isinstance(value, dict) and set(value) == {'dtype', 'units'} and
                         isinstance(value['dtype'], str) and isinstance(value['units'], str))
        if key in IDENTITY_FIELDS and value is not None and not column_schema:
            require(type(value) is int, 'strict integer JSON field: ' + key, 'invalid_json')
        if key in IDENTITY_LISTS:
            require(isinstance(value, list) and all(type(v) is int for v in value),
                    'strict integer JSON identity list: ' + key, 'invalid_json')
        result[key] = value
    return result


def decode(text):
    def constant(value):
        raise Rejected('invalid_json', 'nonfinite JSON token: ' + value)
    def floating(value):
        result = float(value)
        require(math.isfinite(result), 'nonfinite JSON number: ' + value, 'invalid_json')
        return result
    return json.loads(text, object_pairs_hook=pairs, parse_constant=constant, parse_float=floating)


class Reader:
    def __init__(self, root):
        self.root = Path(os.path.abspath(root))
        self.watched = {}
        self.total = 0

    def path(self, relative):
        relative = str(relative).replace('\\', '/')
        require(relative and not relative.startswith('/') and ':' not in relative and
                all(p not in ('', '.', '..') for p in relative.split('/')), 'unsafe relative path: ' + relative, 'unsafe_path')
        path = self.root.joinpath(*relative.split('/'))
        for item in [self.root, *list(path.parents)[:len(path.parts)-len(self.root.parts)-1], path]:
            try:
                info = item.lstat()
            except FileNotFoundError:
                continue
            require(not stat.S_ISLNK(info.st_mode) and not (getattr(info, 'st_file_attributes', 0) & 0x400), 'linked/reparse path refused: ' + relative, 'unsafe_path')
        return path

    def digest(self, relative, expected=None, size=None):
        path = self.path(relative)
        require(path.is_file(), 'missing file: ' + str(relative), 'missing_file')
        n = path.stat().st_size
        require(n <= MAX_FILE, 'file exceeds bounded reader: ' + str(relative), 'not_supported')
        if str(relative) not in self.watched:
            self.total += n
            require(self.total <= MAX_TOTAL, 'total input exceeds bounded reader', 'not_supported')
        if size is not None:
            integer(size, 'artifact size', high=MAX_FILE)
            require(n == size, 'size mismatch: ' + str(relative), 'artifact_size_mismatch')
        h = hashlib.sha256()
        consumed = 0
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                consumed += len(chunk)
                require(consumed <= MAX_FILE, 'growing file exceeds reader cap', 'not_supported')
                h.update(chunk)
        require(consumed == n, 'file size changed during hash: ' + str(relative), 'changed_during_read')
        value = h.hexdigest()
        if expected is not None:
            require(isinstance(expected, str) and re.fullmatch('[0-9a-f]{64}', expected), 'invalid SHA256: ' + str(relative))
            require(value == expected, 'hash mismatch: ' + str(relative), 'artifact_hash_mismatch')
        if str(relative) in self.watched:
            require(self.watched[str(relative)] == (value, n), 'file changed during inspection: ' + str(relative), 'changed_during_read')
        self.watched[str(relative)] = (value, n)
        return value

    def json(self, relative):
        self.digest(relative)
        require(self.path(relative).stat().st_size <= MAX_JSON, 'JSON exceeds bounded reader: ' + str(relative), 'not_supported')
        return object_value(decode(self.path(relative).read_text(encoding='utf-8-sig')), str(relative))

    def lines(self, relative):
        self.digest(relative)
        with self.path(relative).open(encoding='utf-8-sig', newline='') as stream:
            for i in range(MAX_ROWS + 1):
                line = stream.readline(MAX_LINE + 1)
                if not line:
                    return
                require(i < MAX_ROWS and len(line) <= MAX_LINE, 'line/row cap: ' + str(relative), 'not_supported')
                yield line

    def jsonl(self, relative):
        for line in self.lines(relative):
            record = decode(line)
            require(isinstance(record, dict), 'JSONL object required: ' + str(relative))
            yield record

    def csv(self, relative, columns):
        csv.field_size_limit(MAX_LINE)
        rows = csv.reader(self.lines(relative), strict=True)
        equal(next(rows, None), columns, 'CSV schema ' + str(relative))
        for row in rows:
            require(len(row) == len(columns), 'CSV column count: ' + str(relative))
            yield row

    def recheck(self):
        for path in list(self.watched):
            self.digest(path)


@contextmanager
def existing_lock(reader, relative):
    path = reader.path(relative)
    require(path.is_file(), 'existing run.lock required; never created', 'missing_lock')
    if os.name == 'nt':
        from ctypes import wintypes
        api = ctypes.WinDLL('kernel32', use_last_error=True)
        api.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        api.CreateFileW.restype = wintypes.HANDLE
        api.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = api.CreateFileW(str(path), 0x80000000, 0, None, 3, 0x80, None)  # READ, share none, OPEN_EXISTING
        require(handle != ctypes.c_void_p(-1).value, 'run.lock held or inaccessible', 'held_or_inaccessible_lock')
        try:
            yield
        finally:
            api.CloseHandle(handle)
    else:
        import fcntl
        with path.open('rb') as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise Rejected('held_or_inaccessible_lock', 'run.lock held or inaccessible')
            yield


def source_inventory(reader, original, prefix, expected=None):
    require(isinstance(original, dict) and original, 'missing original source inventory')
    if expected is not None:
        equal(sorted(original), sorted(expected), 'producer source inventory')
    comparisons = []
    for name, saved in original.items():
        path = prefix + name
        require(isinstance(saved, str) and re.fullmatch('[0-9a-f]{64}', saved), 'invalid source hash: ' + name)
        current = reader.digest(path) if reader.path(path).is_file() else None
        comparisons.append(dict(path=path, recorded_sha256=saved, current_sha256=current, matches=current == saved))
    return comparisons


def profile_settings(profile):
    fields(profile, {'schema_version', 'kind', 'name', 'settings'}, 'profile')
    integer(profile['schema_version'], 'profile version', 2, 2)
    equal(profile['kind'], 'native_readout_profile_v1', 'profile kind')
    require(isinstance(profile['name'], str) and re.fullmatch('[A-Za-z0-9_.-]{1,80}', profile['name']), 'profile name')
    settings = profile['settings']
    keys = set('feedback_capacitance_pF feedback_tau_us pole_zero_tau_us shaping_tau_us gain adc_bits adc_full_scale_V threshold_V peak_policy peak_gate_start_ns peak_gate_end_ns'.split())
    fields(settings, keys, 'profile settings')
    gates = {'peak_gate_start_ns', 'peak_gate_end_ns'}
    for k in keys - {'peak_policy'} - gates:
        number(settings[k], 'profile.' + k)
    integer(settings['adc_bits'], 'ADC bits', 2, 24)
    require(all(settings[k] > 0 for k in keys - {'peak_policy'} - gates), 'profile positive settings')
    if any(settings[k] is not None for k in gates):
        for k in gates:
            number(settings[k], 'profile.' + k)
        require(0 <= settings['peak_gate_start_ns'] < settings['peak_gate_end_ns'] <= 99998, 'profile gate support')
    require(settings['threshold_V'] < settings['adc_full_scale_V'], 'profile threshold')
    require(settings['peak_policy'] in ('legacy_reject_negative_input', 'signed_input_positive_peak'), 'profile peak policy')
    return settings


def settings_physics_hash(config):
    """Flat ES configuration canonicalization: Windows PowerShell 5/.NET R.

    R uses 15 significant digits if they round-trip, otherwise 17. No archived
    script or runtime is executed; fixed ASCII keys/enums need no culture sort.
    """
    parts = []
    for key in sorted(config):
        value = config[key]
        if type(value) is float:
            number(value, 'configuration.' + key)
            text = format(value, '.15g')
            if float(text) != value:
                text = format(value, '.17g')
            text = '0' if value == 0 else text.upper()
        else:
            require(value is None or type(value) in (str, bool, int), 'unsupported configuration value', 'not_supported')
            text = json.dumps(value, ensure_ascii=True, separators=(',', ':'))
        parts.append(json.dumps(key) + ':' + text)
    return hashlib.sha256(('{' + ','.join(parts) + '}').encode('utf-8')).hexdigest()


def check_electronics_lineage(reader, run, saved, parent_sources):
    """Reconstruct the ES/EE mirror closure from data, never execute its code."""
    fields(saved, 'schema_version kind input inputs_root copies_sha256 sources_sha256 profile_path profile_sha256 configuration physics_sha256 feasibility'.split(), 'electronics binding')
    integer(saved['schema_version'], 'electronics binding schema', 1, 1)
    equal(saved['kind'], 'saved_electronics_execution_v1', 'electronics binding kind')
    mirror = run + '/electronics/inputs'
    equal(saved['inputs_root'], mirror, 'saved input copies root')
    sources = saved['sources_sha256']
    fields(sources, ES_SOURCES, 'settings source inventory')
    for path, digest in sources.items():
        equal(digest, parent_sources[path], 'original parent/settings source ' + path)
        reader.digest(mirror + '/' + path, digest)
    for path, digest in ES_DEFAULTS.items():
        equal(sources[path], digest, 'frozen settings default ' + path)
    defaults = reader.json(mirror + '/simulation/readout_demo.json')
    profile_settings(reader.json(mirror + '/simulation/native_readout_profile.json'))
    wanted, ancestry, seen = dict(sources), [], set()

    def selected(descriptor, depth=0):
        require(depth < 16, 'settings provenance exceeds 16 input files', 'not_supported')
        fields(descriptor, ('path', 'sha256', 'schema_version', 'kind'), 'input descriptor')
        path = descriptor['path']
        require(isinstance(path, str) and re.fullmatch(r'[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)*', path), 'unsafe settings path', 'unsafe_path')
        require(all(p not in ('.', '..') and not p.endswith('.') and not re.match(r'(?i)^(CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])($|\.)', p) for p in path.split('/')), 'unsafe settings path component', 'unsafe_path')
        require(path.lower() not in seen, 'cyclic settings provenance')
        seen.add(path.lower())
        integer(descriptor['schema_version'], 'input descriptor schema', 1)
        require(isinstance(descriptor['kind'], str) and
                (descriptor['kind'], descriptor['schema_version']) in {('electronics_settings_bundle_v1', 1), ('native_readout_profile_v1', 2)},
                'compatible_reader_required: unsupported electronics input schema', 'not_supported')
        require(reader.path(mirror + '/' + path).stat().st_size <= 131072, 'settings input exceeds 128 KiB', 'not_supported')
        reader.digest(mirror + '/' + path, descriptor['sha256'])
        data = reader.json(mirror + '/' + path)
        equal(data['kind'], descriptor['kind'], 'input descriptor kind')
        equal(data['schema_version'], descriptor['schema_version'], 'input descriptor version')
        if path in wanted:
            equal(wanted[path], descriptor['sha256'], 'overlapping source/input binding')
        wanted[path] = descriptor['sha256']
        ancestry.append(dict(descriptor))
        if data['kind'] == 'electronics_settings_bundle_v1':
            fields(data, 'schema_version kind revision profile configuration physics_sha256 provenance'.split(), 'settings bundle')
            integer(data['schema_version'], 'bundle schema', 1, 1)
            integer(data['revision'], 'bundle revision', 1, 1)
            provenance = data['provenance']
            fields(provenance, ('input', 'defaults', 'sources_sha256'), 'bundle provenance')
            equal(provenance['sources_sha256'], sources, 'bundle source bindings')
            equal(provenance['defaults'], dict(path='simulation/readout_demo.json', sha256=ES_DEFAULTS['simulation/readout_demo.json'], schema_version=1), 'bundle default binding')
            selected(provenance['input'], depth + 1)
            profile = data['profile']
        else:
            require(data['kind'] == 'native_readout_profile_v1', 'compatible_reader_required: unsupported electronics input format', 'not_supported')
            profile = data
        settings = profile_settings(profile)
        config = {k: v for k, v in defaults.items() if k != 'max_total_samples'}
        config.update(schema_version=2, expected_primary_count=None, **settings)
        digest = settings_physics_hash(config)
        if data['kind'] == 'electronics_settings_bundle_v1':
            object_value(data['configuration'], 'bundle configuration')
            for key in ('schema_version', 'adc_bits', 'max_samples_per_event', 'trace_max_points'):
                integer(data['configuration'][key], 'bundle configuration.' + key, 1)
            equal(data['configuration'], config, 'independent bundle configuration')
            equal(data['physics_sha256'], digest, 'independent bundle physics hash')
        return profile, config, digest

    object_value(saved['input'], 'execution input descriptor')
    require(isinstance(saved['input'].get('path'), str) and re.fullmatch(r'\.local/electronics-profiles/[A-Za-z0-9_-]{1,64}\.json', saved['input']['path']), 'execution requires saved bundle path')
    equal(saved['input']['kind'], 'electronics_settings_bundle_v1', 'execution requires saved bundle')
    profile, config, digest = selected(saved['input'])
    equal(saved['copies_sha256'], wanted, 'exact derived electronics copy inventory')
    # Bound the tiny mirror walk; reject unlisted copies and path redirection.
    actual, pending, entries = set(), [''], 0
    while pending:
        prefix = pending.pop()
        with os.scandir(reader.path(mirror + ('/' + prefix if prefix else ''))) as directory:
            for entry in directory:
                entries += 1
                require(entries <= 256, 'electronics mirror inventory cap', 'not_supported')
                path = prefix + '/' + entry.name if prefix else entry.name
                safe = reader.path(mirror + '/' + path)
                if safe.is_dir():
                    pending.append(path)
                else:
                    require(safe.is_file(), 'non-file in electronics mirror')
                    actual.add(path)
    equal(actual, set(wanted), 'actual electronics mirror inventory')
    equal(saved['configuration'], config, 'independent execution configuration')
    equal(saved['physics_sha256'], digest, 'independent execution physics hash')
    calibration_samples = math.ceil(number(10000 * config['shaping_tau_us'], 'calibration support')) + 1
    require(3 <= calibration_samples <= config['max_samples_per_event'] and (calibration_samples-1)*2 <= config['max_window_ns'], 'calibration feasibility')
    if config['peak_gate_start_ns'] is not None:
        require(math.floor(config['peak_gate_end_ns']/2) > math.ceil(config['peak_gate_start_ns']/2), 'peak gate requires two samples')
    equal(saved['feasibility'], dict(time_step_ns=2, isolated_horizon_ns=100000, last_sample_ns=99998,
                                   calibration_samples=calibration_samples,
                                   scope='Arithmetic sample/window feasibility; numerical injection calibration remains part of native execution, not experimental validation'), 'execution feasibility')
    return profile, dict(input_ancestry=ancestry, required_copies_sha256=wanted, physics_sha256=digest)


def check_profile(reader, base, parent, report, events):
    profile = reader.json(base + '/profile-input.json')
    equal(profile, report['profile'], 'original profile')
    equal(profile, reader.json(base + '/profile.json'), 'normalized profile')
    reader.digest(base + '/profile-input.json', report['profile_sha256'])
    settings = profile_settings(profile)
    equal(settings['peak_policy'], 'signed_input_positive_peak', 'peak policy')
    config = reader.json(base + '/readout-config.json')
    reader.digest(base + '/readout-config.json', report['config_sha256'])
    expected = dict(schema_version=2, calibration_energy_keV=500.0, expected_primary_count=events,
                    max_samples_per_event=500000, max_window_ns=1e6, require_all_events=True,
                    tail_shaping_constants=20.0, trace_max_points=600, **settings)
    equal(config, expected, 'independently resolved configuration')
    integer(config['expected_primary_count'], 'configuration primary count', events, events)
    run = base.rsplit('/', 2)[0]
    if 'electronics' in parent:
        saved = parent['electronics']
        selected_profile, lineage = check_electronics_lineage(reader, run, saved, parent['source_sha256'])
        equal(selected_profile, profile, 'saved bundle/response profile')
        equal(saved['profile_path'], run + '/electronics/profile.json', 'saved profile path')
        reader.digest(saved['profile_path'], report['profile_sha256'])
        equal(reader.json(saved['profile_path']), profile, 'parent profile')
        equal(saved['profile_sha256'], report['profile_sha256'], 'parent profile binding')
        expected['expected_primary_count'] = None
        equal(saved['configuration'], expected, 'parent independent configuration')
        return lineage
    else:
        require(not reader.path(run + '/electronics').exists() and 'simulation/readout_demo.json' not in parent['source_sha256'], 'custom electronics evidence lacks parent binding')
        equal(parent['source_sha256']['simulation/native_readout_profile.json'], report['profile_sha256'], 'original canonical profile binding')


def check_inputs(reader, base, report, model, events):
    transport = base.rsplit('/', 1)[0] + '/transport'
    manifest = reader.json(transport + '/stream/manifest.json')
    reader.digest(transport + '/stream/manifest.json', report['input_sha256'])
    equal(reader.json(base + '/input-contract.json'), manifest, 'copied input manifest')
    prepared = reader.json(transport + '/prepared.json')
    equal(reader.json(base + '/input-prepared.json'), prepared, 'copied prepared input')
    reader.digest(transport + '/prepared.json', manifest['prepared_sha256'])
    tr = reader.json(transport + '/run.json')
    reader.digest(transport + '/run.json', manifest['run_sha256'])
    equal(tr['status'], 'complete', 'transport terminal status')
    integer(tr['returncode'], 'transport return code', 0, 0)
    equal(tr['prepared_sha256'], manifest['prepared_sha256'], 'transport preparation binding')
    for item in (manifest, prepared):
        equal(item['model_id'], model, 'input model')
        equal(item['model_sha256'], report['model_sha256'], 'input model hash')
        integer(item['primary_count'], 'input primaries', events, events)
        equal(item['grouping_policy'], GROUPING, 'input grouping')
        equal(item['clock_policy'], 'remage_initial_decay_secondaries_zero', 'input clock')
    equal(manifest['coordinate_transform'], prepared['coordinate_transform'], 'coordinate transform')
    equal(manifest['kind'], 'cs137_decay_stream_v1', 'stream kind')
    equal(manifest['status'], 'complete', 'stream status')
    equal(manifest['global_decay_id_range'], [0, events - 1], 'global census range')
    equal(manifest['units'], dict(energy='keV', length='mm', time='ns'), 'stream units')
    equal(manifest['raw_position_unit'], 'm', 'raw position unit')
    equal(manifest['raw_track_energy_unit'], 'MeV', 'raw track energy unit')
    equal(manifest['source_lh5_sha256'], report['source_lh5_sha256'], 'raw source binding')
    equal(tr['source_lh5_sha256'], report['source_lh5_sha256'], 'transport raw source binding')
    reader.digest(transport + '/truth.lh5', report['source_lh5_sha256'])  # bytes only; no HDF5 runtime
    for path, value in object_value(prepared['files_sha256'], 'prepared file inventory').items():
        reader.digest(transport + '/' + path, value)
    for key, file in [('config_sha256', 'scenario.json'), ('geometry_sha256', 'geometry.gdml'), ('macro_sha256', 'run.mac')]:
        reader.digest(transport + '/' + file, manifest[key])
    equal(manifest['source_sha256'], prepared['source_sha256'], 'original transport sources')
    return manifest, source_inventory(reader, manifest['source_sha256'], 'transport/', STREAM_SOURCES)


def csv_identity(text, label):
    require(re.fullmatch('0|[1-9][0-9]*', text) is not None, label + ': integer CSV required')
    return integer(int(text), label)


def check_csv_mirror(reader, base, name, columns):
    for obj, row in itertools.zip_longest(reader.jsonl(base + '/' + name + '.jsonl'), reader.csv(base + '/' + name + '.csv', columns)):
        require(obj is not None and row is not None, name + ': CSV/JSONL row count')
        equal(decode(row[-1]), obj, name + ': record_json')
        for key, value in zip(columns[:-1], row[:-1]):
            expected = obj.get(key)
            if expected is None:
                equal(value, '', name + '.' + key)
            elif type(expected) is bool:
                equal(value, str(expected).lower(), name + '.' + key)
            elif type(expected) is int:
                integer(expected, name + '.' + key)
                equal(csv_identity(value, key), expected, name + '.' + key)
            elif type(expected) is float:
                close(float(value), expected, name + '.' + key)
            else:
                equal(value, expected, name + '.' + key)


def input_events(reader, base, manifest):
    stream = base.rsplit('/', 1)[0] + '/transport/stream/'
    start = 0
    names = set()
    for chunk in array_value(manifest['chunks'], 'input chunks'):
        object_value(chunk, 'input chunk')
        equal(set(chunk), {'file', 'count', 'first_global_decay_id', 'sha256'}, 'chunk fields')
        count = integer(chunk['count'], 'chunk count', 1, 10000)
        integer(chunk['first_global_decay_id'], 'chunk start', start, start)
        require(re.fullmatch(r'decays-[0-9]{8}\.jsonl', chunk['file']) and chunk['file'] not in names, 'chunk name/duplicate')
        names.add(chunk['file'])
        reader.digest(stream + chunk['file'], chunk['sha256'])
        actual = 0
        for event in reader.jsonl(stream + chunk['file']):
            integer(event['event_id'], 'input event ID', start + actual, start + actual)
            integer(event['global_decay_id'], 'input global ID', start + actual, start + actual)
            actual += 1
            yield event
        equal(actual, count, 'chunk count')
        start += count
    equal(start, manifest['primary_count'], 'chunk census')


def check_ledgers(reader, base, report, manifest):
    scalars = iter(reader.jsonl(base + '/scalars.jsonl'))
    pulses, failures, steps_by_key = [], [], {}
    count = dict.fromkeys(COUNT_KEYS, 0)
    raw_ids = set()
    for index, (original, truth) in enumerate(itertools.zip_longest(input_events(reader, base, manifest), reader.jsonl(base + '/truth.jsonl'))):
        require(original is not None and truth is not None, 'truth/input census mismatch')
        equal(truth, original, 'truth/input original record')
        integer(truth['event_id'], 'event ID', index, index)
        integer(truth['global_decay_id'], 'global ID', index, index)
        scalar = next(scalars, None)
        require(scalar is not None, 'missing primary scalar')
        count['initial_primaries'] += 1
        count['initial_decays'] += 1
        steps = array_value(truth['steps'], 'truth steps')
        byrow = {}
        for step in steps:
            object_value(step, 'truth step')
            object_value(step['raw'], 'original raw step')
            row = integer(step['raw_row_index'], 'raw row')
            require(row not in raw_ids, 'duplicate raw step row')
            raw_ids.add(row)
            byrow[row] = step
            number(step['time_ns'], 'deposition time')
            require(number(step['energy_keV'], 'deposit energy') >= 0, 'negative truth deposit')
            equal(step['raw']['evtid'], index, 'raw event ID')
            integer(step['raw']['evtid'], 'raw event integer', index, index)
            equal(step['raw']['raw_row_index'], row, 'raw row identity')
            close(step['raw']['time'], step['time_ns'], 'raw time', absolute=0)
            close(step['raw']['edep'], step['energy_keV'], 'raw energy')
        energy = sum(s['energy_keV'] for s in steps)
        groups = array_value(truth['pulse_groups'], 'truth groups')
        expected = dict(record_kind='decay', event_id=index, global_decay_id=index, group_id=None,
                        deposited_energy_keV=energy, pulse_count=len(groups), zero_deposit=energy == 0,
                        raw_row_indices=[s['raw_row_index'] for s in steps],
                        line_photon_count=truth['line_photon_count'], decay_photon_count=truth['decay_photon_count'],
                        material_energy_keV=truth['material_energy_keV'], full_energy_closure=None)
        for k in ('event_id', 'global_decay_id', 'pulse_count', 'line_photon_count', 'decay_photon_count'):
            integer(scalar[k], 'primary ' + k)
        for row in scalar['raw_row_indices']:
            integer(row, 'primary raw row ID')
        close(scalar['deposited_energy_keV'], energy, 'primary Edep')
        expected['deposited_energy_keV'] = scalar['deposited_energy_keV']
        equal(scalar, expected, 'primary scalar')
        count['zero_deposit_primaries'] += energy == 0
        for key in ('line_photons', 'decay_photons'):
            count[key] += integer(truth[key[:-1] + '_count'], key)
        positive = sorted((s for s in steps if s['energy_keV'] > 0), key=lambda s: (s['time_ns'], s['raw_row_index']))
        assigned = []
        for gid, group in enumerate(groups):
            object_value(group, 'truth group')
            integer(group['group_id'], 'group ID', gid, gid)
            equal(group['horizon_ns'], GROUPING['horizon_ns'], 'group horizon')
            equal(group['electronics_state'], 'reset_nominal_isolated_window', 'group state')
            rows = group['row_indices']
            require(rows and len(rows) == len(set(rows)), 'empty/duplicate group rows')
            for row in rows:
                integer(row, 'group row ID')
                require(row in byrow and byrow[row]['energy_keV'] > 0, 'unknown/nonpositive group row')
            selected = [byrow[row] for row in rows]
            origin = number(group['origin_time_ns'], 'group origin')
            close(origin, selected[0]['time_ns'], 'first deposit/origin', absolute=0)
            close(group['last_deposit_time_ns'], selected[-1]['time_ns'], 'last deposit', absolute=0)
            require(len(group['relative_times_ns']) == len(rows), 'relative time count')
            for s, delay in zip(selected, group['relative_times_ns']):
                close(delay, s['time_ns'] - origin, 'relative deposition delay')
                require(0 <= delay < group['horizon_ns'], 'deposit outside group horizon')
            if assigned:
                require(origin >= groups[gid-1]['origin_time_ns'] + GROUPING['horizon_ns'], 'group split inside horizon')
            assigned.extend(rows)
            pulse = next(scalars, None)
            require(pulse is not None, 'missing pulse scalar')
            for k, v in [('event_id', index), ('global_decay_id', index), ('group_id', gid)]:
                integer(pulse[k], 'pulse ' + k, v, v)
            equal(pulse['record_kind'], 'pulse', 'pulse record kind')
            equal(pulse['group'], group, 'pulse original group')
            equal(pulse['raw_row_indices'], rows, 'pulse raw rows')
            close(pulse['origin_time_ns'], origin, 'pulse origin', absolute=0)
            close(pulse['deposited_energy_keV'], sum(s['energy_keV'] for s in selected), 'group Edep')
            integer(pulse['parcels'], 'pulse parcels', report['parcels'], report['parcels'])
            integer(pulse['seed_family'], 'pulse seed', report['seed_family'], report['seed_family'])
            key = (index, index, gid)
            steps_by_key[key] = selected
            count['groups'] += 1
            if pulse.get('status') == 'native_transport_failed':
                for k in ('final_induced_keV', 'charge_end_ns', 'native_any_negative_charge', 'native_min_charge_keV', 'native_max_charge_keV', 'transport_flags', 'endpoints', 'readout', 'current_nA', 'induced_charge_fC'):
                    require(k in pulse and pulse[k] is None, 'failed group unknown must remain null: ' + k)
                equal(pulse['accepted'], False, 'failed acceptance')
                equal(pulse['trace_saved'], False, 'failed trace')
                equal(pulse['rejection_reason'], 'native_transport_failed', 'failure rejection')
                equal(pulse['source_lh5_sha256'], report['source_lh5_sha256'], 'failure raw source')
                equal(pulse['raw_table'], 'stp/germanium', 'failure raw table')
                require(len(pulse['deposition_delays_ns']) == len(selected), 'failed delay count')
                for delay, step in zip(pulse['deposition_delays_ns'], selected):
                    close(delay, step['time_ns'] - origin, 'failed original delay')
                require(pulse['native_error']['message'] in report['native_failure_allowlist'], 'unknown native failure')
                equal(pulse['native_error']['type'], 'ArgumentError', 'failure exception type')
                equal(pulse['native_error']['stage'], 'NativeLiExample.native_event', 'failure stage')
                equal(pulse['native_error']['exact_error'], 'ArgumentError: ' + pulse['native_error']['message'], 'exact failure')
                failures.append((pulse, truth, selected))
                count['native_failed_groups'] += 1
                count['rejected'] += 1
            else:
                require('status' not in pulse, 'unsupported pulse status', 'not_supported')
                object_value(pulse['readout'], 'pulse readout')
                require(type(pulse['accepted']) is bool and type(pulse['readout']['saturated']) is bool, 'pulse boolean flags')
                count['accepted'] += pulse['accepted']
                count['rejected'] += not pulse['accepted']
                count['readout_rejected'] += not pulse['accepted']
                count['saturated'] += pulse['readout']['saturated']
                count['analog_samples'] += integer(pulse['readout']['original_sample_count'], 'analog sample count')
                count['native_charge_samples'] += integer(pulse['readout']['input_sample_count'], 'charge sample count', 2)
            pulses.append(pulse)
        equal(assigned, [s['raw_row_index'] for s in positive], 'complete ordered positive-deposit grouping')
    require(next(scalars, None) is None, 'extra scalar row')
    equal(count, report['counts'], 'reconciled entire primary/group census')
    if failures:
        records = reader.jsonl(base + '/native-failures.jsonl')
        for expected, diagnostic in itertools.zip_longest(failures, records):
            require(expected is not None and diagnostic is not None, 'failure diagnostic census')
            pulse, truth, selected = expected
            equal(diagnostic['record_kind'], 'native_failure_diagnostic', 'failure kind')
            for k, value in [('pulse', pulse), ('original_event', truth), ('original_group', pulse['group']), ('original_steps', selected)]:
                equal(diagnostic[k], value, 'native diagnostic ' + k)
            for k, value in object_value(diagnostic['settings'], 'failure settings').items():
                equal(value, report[k], 'failure settings ' + k)
    return pulses, steps_by_key


def check_endpoints(reader, base, report, pulses, steps):
    records = iter(reader.jsonl(base + '/endpoints.jsonl'))
    for pulse in pulses:
        if pulse.get('status') == 'native_transport_failed':
            continue
        key = tuple(pulse[k] for k in ('event_id', 'global_decay_id', 'group_id'))
        flags = dict(carrier_parcels=0, geometric_contacts=0, step_limits=0, stopped_without_contact=0)
        final = 0
        for step in steps[key]:
            step_charge = None
            for parcel in range(1, report['parcels'] + 1):
                for species in ('electron', 'hole'):
                    ep = next(records, None)
                    require(ep is not None, 'missing endpoint')
                    for name, value in zip(('event_id', 'global_decay_id', 'group_id'), key):
                        integer(ep[name], 'endpoint ' + name, value, value)
                    integer(ep['raw_row_index'], 'endpoint row', step['raw_row_index'], step['raw_row_index'])
                    integer(ep['parcel_index'], 'endpoint parcel', parcel, parcel)
                    equal(ep['raw_table'], 'stp/germanium', 'endpoint raw table')
                    equal(ep['source_lh5_sha256'], report['source_lh5_sha256'], 'endpoint raw source')
                    close(ep['original_time_ns'], step['time_ns'], 'endpoint original time', absolute=0)
                    close(ep['origin_time_ns'], pulse['origin_time_ns'], 'endpoint origin', absolute=0)
                    close(ep['deposition_delay_ns'], step['time_ns'] - pulse['origin_time_ns'], 'endpoint delay')
                    close(ep['deposited_energy_keV'], step['energy_keV'], 'endpoint Edep')
                    close(ep['parcel_weight_keV'], step['energy_keV'] / report['parcels'], 'parcel weight')
                    seed_text = f"{report['seed_family']}/{key[0]}/{step['raw_row_index']}/{parcel}"
                    seed = int.from_bytes(hashlib.sha256(seed_text.encode()).digest()[:8], 'big')
                    equal(ep['seed_uint64'], str(seed), 'endpoint original seed')
                    q = number(ep['step_final_induced_keV'], 'step final charge')
                    if step_charge is None:
                        step_charge = q
                    close(q, step_charge, 'duplicate step final charge')
                    endpoint = object_value(ep['endpoint'], 'endpoint')
                    integer(endpoint['parcel_index'], 'nested parcel', parcel, parcel)
                    equal(endpoint['species'], species, 'endpoint species/order')
                    integer(endpoint['samples'], 'endpoint samples', 1)
                    require(type(endpoint['step_limit_reached']) is bool and type(endpoint['inside_semiconductor']) is bool, 'endpoint flags')
                    require(endpoint['status'] in ('contact', 'step_limit', 'stopped_without_contact'), 'endpoint status')
                    require(len(array_value(endpoint['position_mm'], 'endpoint position')) == 3, 'endpoint position')
                    for v in endpoint['position_mm']:
                        number(v, 'endpoint coordinate')
                    for v in endpoint['contact_ids']:
                        integer(v, 'endpoint contact', 1, 2)
                    flags['carrier_parcels'] += 1
                    flags['geometric_contacts'] += bool(endpoint['contact_ids'])
                    flags['step_limits'] += endpoint['step_limit_reached']
                    flags['stopped_without_contact'] += endpoint['status'] == 'stopped_without_contact'
            final += step_charge
        close(final, pulse['final_induced_keV'], 'endpoint/group final charge', absolute=1e-8)
        equal(flags, pulse['transport_flags'], 'retained endpoint flags')
    require(next(records, None) is None, 'extra/failed-group endpoint')


def check_signals(reader, base, report, pulses):
    rows = iter(reader.csv(base + '/signals.csv', SIGNAL_COLUMNS))
    row = next(rows, None)
    summaries, missing = [], []
    total = 0
    for pulse in pulses:
        key = tuple(pulse[k] for k in ('event_id', 'global_decay_id', 'group_id'))
        if pulse.get('status') == 'native_transport_failed':
            summaries.append(dict(key=[report['model_id'], *key], status='native_transport_failed', samples=None,
                                  final_induced_keV=None, transport_flags=None, native_error=pulse['native_error']))
            continue
        expected = pulse['readout']['input_sample_count']
        lo, hi, last, n = math.inf, -math.inf, None, 0
        while row is not None:
            ids = tuple(csv_identity(v, 'signal identity') for v in row[:3])
            if ids != key:
                break
            time, charge = float(row[3]), float(row[4])
            number(charge, 'signed signal')
            close(time, n * report['drift_dt_ns'], 'uniform relative sample grid')
            if n == 0:
                close(charge, 0, 'initial charge', absolute=0)
            lo, hi, last = min(lo, charge), max(hi, charge), charge
            n += 1
            require(n <= expected, 'extra charge rows for group', 'extra_samples')
            row = next(rows, None)
        if n != expected:
            missing.append(dict(key=[report['model_id'], *key], expected=expected, observed=n,
                                reason='missing_group' if n == 0 else 'truncated_group'))
        else:
            close((n-1) * report['drift_dt_ns'], pulse['charge_end_ns'], 'charge end/support')
            close(last, pulse['final_induced_keV'], 'stored final charge')
            close(lo, pulse['native_min_charge_keV'], 'stored minimum charge')
            close(hi, pulse['native_max_charge_keV'], 'stored maximum charge')
            equal(lo < 0, pulse['native_any_negative_charge'], 'signed negative charge flag')
            close(pulse['readout']['untruncated_final_charge_keV'], last, 'readout original final charge')
            close(pulse['readout']['untruncated_charge_end_ns'], pulse['charge_end_ns'], 'readout original support')
            if pulse['readout'].get('charge_clipped_at_window') is False:
                close(pulse['readout']['final_charge_C'], last * 1000 / report['ionisation_energy_eV'] * 1.602176634e-19,
                      'charge conversion C', absolute=1e-25)
        summaries.append(dict(key=[report['model_id'], *key], samples=n, expected_samples=expected,
                              status='stored' if n == expected else 'missing_or_partial',
                              origin_time_ns=pulse['origin_time_ns'], time_start_ns=0 if n else None,
                              time_end_ns=(n-1)*report['drift_dt_ns'] if n else None,
                              final_induced_keV=last, minimum_induced_keV=lo if n else None,
                              maximum_induced_keV=hi if n else None, nonzero_negative_samples_present=lo < 0 if n else None,
                              transport_flags=pulse['transport_flags']))
        total += n
    require(row is None, 'extra, duplicate, reordered or mismatched-ID signal rows', 'unexpected_signal_row')
    return summaries, missing, total


def inspect_detector(reader, run, parent, model, result):
    base = run + '/' + model + '/response'
    if reader.path(base).is_dir():
        require(not any(p.suffix == '.jls' or p.name.startswith('checkpoint') for p in reader.path(base).iterdir()),
                'compatible_reader_required: serialized/checkpoint charge is not supported', 'not_supported')
    report = reader.json(base + '/run.json')
    require(report.get('kind') == 'native_response_v1', 'compatible_reader_required: unsupported response kind', 'not_supported')
    reader.digest(base + '/run.json', parent['models'][model]['response_report_sha256'])
    equal(parent['models'][model]['status'], report['status'], 'parent/final guarded child status')
    equal(parent['models'][model]['counts'], report['counts'], 'parent/child counts')
    equal(report['model_id'], model, 'response model')
    equal(report['input_kind'], 'cs137_decay_stream_v1', 'response input format')
    fields(report['counts'], COUNT_KEYS, 'counts schema')
    for key, value in object_value(report['counts'], 'response counts').items():
        integer(value, 'counts.' + key)
        integer(parent['models'][model]['counts'][key], 'parent counts.' + key)
    failures = report['counts']['native_failed_groups']
    equal(report['status'], 'completed_with_native_failures' if failures else 'completed_provisional_native_response', 'native status')
    expected = ARTIFACTS | ({'native-failures.jsonl'} if failures else set())
    equal(set(report['artifacts']), expected, 'artifact inventory')
    equal(set(report['artifact_bytes']), expected, 'artifact sizes inventory')
    actual = {p.name for p in reader.path(base).iterdir()}
    require(actual == expected | {'run.json'},
            'response directory inventory; missing=' + repr(sorted((expected | {'run.json'}) - actual)) +
            '; extra=' + repr(sorted(actual - expected - {'run.json'})), 'artifact_inventory_mismatch')
    for name in sorted(expected):
        reader.digest(base + '/' + name, report['artifacts'][name], report['artifact_bytes'][name])
    equal(report['boundary_guard']['kind'], 'ssd_0_11_8_boundary_guard_v1', 'guard kind')
    equal(report['boundary_guard']['installed'], True, 'guard installed')
    equal(report['boundary_guard']['package_files_modified'], False, 'guard package files')
    equal(report['boundary_guard']['native_source_sha256'], '0358c255e37c38f62eee6f1e476c0ed48560708dfcd3d367d2688eaa022232ad', 'recorded native guard source')
    for key, name in [('guard_source_sha256', 'native_boundary_guard.jl'), ('guard_wrapper_sha256', 'native_response_guarded.jl')]:
        equal(report[key], report['source_sha256'][name], 'guard source receipt')
    settings = dict(parcels=16, seed_family=2609261, diffusion=True, end_drift_when_no_field=False,
                    self_repulsion=False, drift_dt_ns=2, nominal_drift_cap_ns=10000,
                    readout_contact_id=1, temperature_K=77, stored_temperature_K=78,
                    bias_V=500 if model == 'AK02' else 700, ionisation_energy_eV=2.95)
    for key, value in settings.items():
        equal(report[key], value, 'supported native setting ' + key)
    for key in ('parcels', 'seed_family', 'readout_contact_id'):
        integer(report[key], key, settings[key], settings[key])
    equal(report['units'], UNITS, 'original/current response units')
    equal(report['grouping_policy'], GROUPING, 'grouping policy')
    require(report['native_failure_policy'] in ('record', 'abort'), 'native failure policy')
    require(not failures or report['native_failure_policy'] == 'record', 'failures under abort policy')
    equal(report['native_failure_allowlist'], ['Noncontact endpoint outside crystal', 'Invalid waveform support'], 'native failure allowlist')
    require(report['charge_csv_policy'] in ('all', 'examples', 'none'), 'CSV policy')
    equal(report['field_settings'], dict(precision_bits=64, min_spacing_mm=0.05, max_spacing_mm=2, sor=1, potential_rechecks=4), 'field settings')
    equal(report['seed_rule'], 'SHA256(seed/global_event_id/raw_row_index/parcel_index), first8 bytes big-endian UInt64; no chunk/group index', 'seed rule')
    reader.digest('models/' + model + '.yaml', report['model_sha256'])
    catalog = reader.json('models/catalog.json')
    entries = [d for d in catalog['detectors'] if d['id'] == model]
    require(len(entries) == 1, 'model catalog identity')
    equal(entries[0]['model_sha256'], report['model_sha256'], 'catalog model binding')
    integer(entries[0]['readout_contact_id'], 'catalog readout contact', report['readout_contact_id'], report['readout_contact_id'])
    result['provenance'] = dict(original_child_sources=report['source_sha256'], recorded_environment=report['environment'],
                                recorded_readout_environment=report['readout_environment'], boundary_guard=report['boundary_guard'],
                                model_sha256=report['model_sha256'], input_sha256=report['input_sha256'],
                                original_source_lh5_sha256=report['source_lh5_sha256'], profile_sha256=report['profile_sha256'])
    comparisons = source_inventory(reader, report['source_sha256'], 'simulation/', SOURCES)
    manifest, transport_sources = check_inputs(reader, base, report, model, parent['events_per_model'])
    result['provenance']['original_transport_sources'] = manifest['source_sha256']
    comparisons += transport_sources
    for name, value in report['source_sha256'].items():
        if 'simulation/' + name in parent['source_sha256']:
            equal(value, parent['source_sha256']['simulation/' + name], 'parent/child original producer source')
    result['provenance']['electronics_lineage'] = check_profile(reader, base, parent, report, parent['events_per_model'])
    equal(report['environment']['environment_manifest_sha256'], report['source_sha256']['Manifest.toml'], 'recorded environment binding')
    equal(report['readout_environment']['manifest_sha256'], report['source_sha256']['Manifest.toml'], 'readout environment binding')
    equal(report['readout_environment']['project_sha256'], report['source_sha256']['Project.toml'], 'readout project binding')
    runtime_record_supported = (report['environment']['julia_version'] == '1.13.0' and
                                report['environment']['ssd_version'] == '0.11.8' and
                                report['readout_environment']['json_version'] == '1.9.0' and
                                report['readout_environment']['julia_version'] == '1.13.0' and
                                report['readout_environment']['pinned_julia_version'] == '1.13.0')
    result['producer_compatible'] = runtime_record_supported and all(c['matches'] for c in comparisons)
    result['source_comparisons'] = comparisons
    if not result['producer_compatible']:
        result['findings'].append(dict(code='producer_incompatible', detail='Original complete producer inventory differs from current sources or recorded version contract. No historical source whitelist or reduced dependency pass. Storage is checked separately.'))
    check_csv_mirror(reader, base, 'scalars', ['record_kind','event_id','global_decay_id','group_id','origin_time_ns','deposited_energy_keV','final_induced_keV','accepted','rejection_reason','record_json'])
    check_csv_mirror(reader, base, 'truth', ['event_id','global_decay_id','record_json'])
    check_csv_mirror(reader, base, 'endpoints', ['event_id','global_decay_id','group_id','raw_row_index','parcel_index','seed_uint64','record_json'])
    pulses, steps = check_ledgers(reader, base, report, manifest)
    check_endpoints(reader, base, report, pulses, steps)
    summaries, missing, total = check_signals(reader, base, report, pulses)
    result.update(groups=summaries, missing_samples=missing, stored_samples=total,
                  counts=report['counts'], charge_csv_policy=report['charge_csv_policy'],
                  trace_selection=report['trace_selection'], storage_complete=not missing,
                  coverage='complete_native_success_groups' if not missing else 'partial_or_missing',
                  signal_contract=dict(value='signed induced_equivalent_energy_keV', time='ns since group origin',
                                       conversion='Q_C = value_keV * 1000 / ionisation_energy_eV * 1.602176634e-19',
                                       time_step_ns=report['drift_dt_ns'], contact_id=report['readout_contact_id'],
                                       grouping_policy=report['grouping_policy']))
    if missing:
        result['findings'].append(dict(code='missing_charge_samples', detail='CSV coverage is not complete; display-decimated traces.jsonl is not a replacement.'))
    if failures:
        result['findings'].append(dict(code='native_failures_retained', detail='Failed groups have null charge and no endpoint/sample substitution.'))
    return result


def inspect_run(root, name, detector='both'):
    result = dict(schema_version=1, kind='saved_charge_eligibility_v1', inspection_status='completed',
                  name=name, detector_selection=detector, eligible=False, storage_complete=False,
                  producer_compatible=False, runtime_verified='NOT_CHECKED', replay_supported='NOT_IMPLEMENTED',
                  lock_observation='not_checked', detectors=[], findings=[],
                  verification_final=False,
                  scope='M4a stored-charge inspection; complete storage is not complete physical collection or permission to replay.',
                  compatibility_policy='Full recorded child/transport source inventory must match current files and supported recorded versions. Parent control-source differences are reported separately; no resume guard changes.',
                  processes_launched=0, files_written=0)
    reader = Reader(root)
    try:
        require(isinstance(name, str) and re.fullmatch('[A-Za-z0-9_-]+', name), 'unsafe run name', 'unsafe_path')
        require(detector in ('AK02', 'SAP22', 'both'), 'unsupported detector', 'invalid_selection')
        run = '.local/runs/' + name
        with existing_lock(reader, run + '/run.lock'):
            result['lock_observation'] = 'existing_lock_exclusively_opened_read_only'
            parent = reader.json(run + '/run.json')
            require(parent.get('kind') == 'native_campaign_v1', 'compatible_reader_required: only native_campaign_v1 CSV is supported; serialized .jls/checkpoint/archives are not deserialized', 'not_supported')
            integer(parent['events_per_model'], 'bounded primaries', 1, 10000)
            require(parent['status'] in ('completed_provisional_native_campaign', 'completed_with_native_failures'), 'nonterminal parent')
            parent_models = object_value(parent['models'], 'parent models')
            for child in parent_models.values():
                object_value(child, 'parent model receipt')
                object_value(child['counts'], 'parent model counts')
            models = array_value(parent.get('detectors', list(parent_models)), 'parent detectors')
            require(models and len(models) == len(set(models)) and all(x in ('AK02','SAP22') for x in models), 'saved detector inventory')
            equal(set(models), set(parent['models']), 'parent model inventory')
            selected = models if detector == 'both' else [detector]
            require(all(x in models for x in selected), 'requested detector absent; no other-run fallback', 'missing_detector')
            result['original_parent_sources'] = parent['source_sha256']
            result['parent_source_comparisons'] = source_inventory(reader, parent['source_sha256'], '')
            result['original_electronics_provenance'] = parent.get('electronics')
            if any(not c['matches'] for c in result['parent_source_comparisons']):
                result['findings'].append(dict(code='parent_source_differences', detail='Original launcher/control provenance retained. Current differences do not establish stored-charge corruption; strict resume validators remain unchanged.'))
            for model in selected:
                child = dict(detector=model, storage_complete=False, producer_compatible=False,
                             runtime_verified='NOT_CHECKED', replay_supported='NOT_IMPLEMENTED', eligible=False, findings=[],
                             verification_final=False, observations_status='nonfinal')
                result['detectors'].append(child)
                try:
                    inspect_detector(reader, run, parent, model, child)
                except (Rejected, KeyError, TypeError, ValueError, OSError, csv.Error, RecursionError) as error:
                    child['findings'].append(finding(error))
            reader.recheck()
            result['verification_final'] = True
            for child in result['detectors']:
                child.update(verification_final=True, observations_status='final')
            result['storage_complete'] = all(d['storage_complete'] for d in result['detectors'])
            result['producer_compatible'] = all(d['producer_compatible'] for d in result['detectors'])
            result['verified_file_count'] = len(reader.watched)
    except (Rejected, KeyError, TypeError, ValueError, OSError, csv.Error, RecursionError) as error:
        result['inspection_status'] = 'blocked'
        result.update(storage_complete=False, producer_compatible=False, verification_final=False)
        for child in result['detectors']:
            child.update(storage_complete=False, producer_compatible=False, verification_final=False, observations_status='nonfinal')
            child['findings'].append(dict(code='verification_invalidated', detail='Inspection did not finish with stable input hashes; retained diagnostics and provenance are nonfinal observations.'))
        result['findings'].append(finding(error))
        if isinstance(error, Rejected) and error.code in ('missing_lock', 'held_or_inaccessible_lock'):
            result['lock_observation'] = error.code
    result['eligibility_status'] = 'not_eligible'
    return result


def finding(error):
    return dict(code=error.code if isinstance(error, Rejected) else 'invalid_or_unreadable_input', detail=str(error))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--name', required=True)
    parser.add_argument('--detector', choices=('AK02', 'SAP22', 'both'), default='both')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    result = inspect_run(Path(__file__).resolve().parents[1], args.name, args.detector)
    if args.json:
        print(json.dumps(result, allow_nan=False, separators=(',', ':')))
    else:
        print('Saved charge: ' + result['inspection_status'] + '; eligibility: ' + result['eligibility_status'])
        for d in result['detectors']:
            print(f"{d['detector']}: storage_complete={d['storage_complete']}; producer_compatible={d['producer_compatible']}; observations={d['observations_status']}; runtime=NOT_CHECKED; replay=NOT_IMPLEMENTED")
            for f in d['findings']:
                print(f"  {f['code']}: {f['detail']}")
        for f in result['findings']:
            print(f"{f['code']}: {f['detail']}")
        print(result['scope'])
    return 0 if result['inspection_status'] == 'completed' else 2


if __name__ == '__main__':
    sys.exit(main())
