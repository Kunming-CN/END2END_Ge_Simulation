"""Hash-bound PSD1 features from completed saved full-resolution signed signals.

No detector, transport, drift, electronics or calibration execution occurs here.
CLI: python tools/psd_features.py --run .local/runs/NAME
Default output: .local/psd-features/<configuration SHA256>/bundle.
The output directory must not exist; failed derivatives are retained. Reader API:
load_bundle(path, expected_config_sha256=None, root=None) and
get_record(bundle, primary_id, group_id=None). All primaries remain in records.
"""
from __future__ import annotations

import argparse
import bisect
import copy
import csv
import hashlib
import json
import math
from pathlib import Path
import platform
import re
import sys

import scenario_workflow as W
from local_ui_jobs import ControlError, safe_path

KIND = 'saved_waveform_psd_features_v1'
PROFILE_KIND = 'saved_waveform_psd_profile_v1'
SCHEMA_VERSION = 1
DEFAULT_PROFILE = Path(__file__).with_name('psd_feature_profile.json')
ELEMENTARY_CHARGE_C = 1.602176634e-19  # exact SI elementary charge
SIGNAL_COLUMNS = ['event_id', 'global_decay_id', 'batch_index', 'local_initial_id',
                  'global_initial_id', 'group_id', 'time_since_origin_ns',
                  'induced_equivalent_energy_keV']
CSV_COLUMNS = ['global_initial_id', 'batch_index', 'local_initial_id', 'event_id',
               'global_decay_id', 'truth_Edep_keV', 'Erec_keV', 'selection_valid',
               'selection_reasons_json', 'pulse_count', 'record_json']
SOURCE_REFS = ['tools/psd_features.py', 'tools/scenario_workflow.py',
               'tools/batch_execution.py', 'tools/workflow_batches.py',
               'tools/catalog_result_validation.py', 'tools/local_ui_jobs.py']
DEFINITIONS = {
    'kind': KIND, 'schema_version': SCHEMA_VERSION,
    'scope': 'Saved engineering observables; no calibrated CCE, physical resolution, acquisition waveform ADC, classifier or experimental validation.',
    'census': 'One record per original primary, in original global order; no event selection removes a record. Every original truth step, scalar, pulse group and endpoint is retained.',
    'A': 'Signed current from adjacent full-resolution native charge differences on [t_i,t_i+1), in nA. A is max(polarity * centered physical-width box average), evaluated at original interval midpoints with complete support inside the declared analysis window. No absolute value, edge padding, shrinking or display traces.',
    'charge_conversion': 'Q_C = induced_equivalent_energy_keV * 1000 / ionisation_energy_eV * elementary_charge_C; I_nA = (delta Q_C / delta t_ns) * 1e18.',
    'E': 'Original readout.reconstructed_energy_keV from separate synthetic injection calibration, unchanged. Edep is truth only and never an A/E denominator. No event-specific gain.',
    'rise': 'Relative to saved pulse-group origin. Interpolate signed observed charge linearly at fixed analysis window endpoints. Use polarity*(Q(t)-Q(start)), with positive signed endpoint span. First linear upward crossings of 10% and 90% of that observed span; t90-t10. This does not infer complete collection.',
    'selection': 'Canonical A, A/E and rise are null for any invalid/unavailable selection; mathematically computable observed values remain separately marked provisional when selection is invalid. Missing charge/readout remains null, never zero.',
    'topology': 'Positive-energy original Geant4 step positions in detector-local mm, inclusive Euclidean single-link clustering at declared nominal and sensitivity radii. Spatial-step proxies are not single-site/multi-site truth or complete trajectories; scoring/step/geometry resolution limits remain.',
    'csv': 'One original primary per row. Numeric scalars use round-trip JSON spelling; unavailable values are literal null, booleans true/false. record_json contains the complete matching JSON record without numeric precision reduction.',
    'primary_energy': 'Erec_keV is populated only for exactly one pulse group, using that original group readout value; multiple groups are not silently summed.',
    'elementary_charge_C': ELEMENTARY_CHARGE_C,
    'csv_columns': CSV_COLUMNS,
}


def require(condition, message):
    if not condition:
        raise ControlError(message, 'psd_features_invalid')


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                      allow_nan=False).encode('utf-8') + b'\n'


def read_json(path):
    return W.read(Path(path))


def sha(path):
    return W.sha(Path(path))


def stamp(path):
    return {'sha256': sha(path), 'bytes': Path(path).stat().st_size}


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def exact_id(value, label):
    require(type(value) is int and 0 <= value <= 9007199254740991, label + ' is not an exact nonnegative ID.')
    return value


def validate_profile(profile):
    require(type(profile) is dict and set(profile) == {'kind', 'schema_version', 'name', 'polarity',
            'analysis_window_ns', 'current_filter', 'rise_fractions', 'topology'}, 'Unexpected feature profile fields.')
    require(profile['kind'] == PROFILE_KIND and type(profile['schema_version']) is int and
            profile['schema_version'] == 1 and type(profile['name']) is str and profile['name'], 'Unsupported feature profile.')
    require(type(profile['polarity']) is int and profile['polarity'] in (-1, 1), 'Feature polarity must be explicitly +1 or -1.')
    window = profile['analysis_window_ns']; filt = profile['current_filter']; top = profile['topology']
    require(type(window) is list and len(window) == 2 and all(finite(x) for x in window) and
            window[0] == 0 and window[1] > 0, 'Analysis window must start at group origin and have positive length.')
    require(type(filt) is dict and set(filt) == {'kind', 'width_ns'} and
            filt['kind'] == 'centered_boxcar_complete_support' and finite(filt['width_ns']) and
            0 < filt['width_ns'] <= window[1], 'Unsupported current filter.')
    require(profile['rise_fractions'] == [0.1, 0.9], 'PSD1 defines observed 10–90% crossings only.')
    require(type(top) is dict and set(top) == {'point_rule', 'coordinate_system', 'energy_rule',
            'cluster_rule', 'nominal_threshold_mm', 'sensitivity_thresholds_mm'} and
            top['point_rule'] == 'position_mm' and top['coordinate_system'] == 'detector_local_mm' and
            top['energy_rule'] == 'energy_keV > 0' and top['cluster_rule'] == 'single_link_euclidean_inclusive',
            'Unsupported topology point, coordinate, energy or clustering rule.')
    radii = top['sensitivity_thresholds_mm']; nominal = top['nominal_threshold_mm']
    require(finite(nominal) and nominal > 0 and type(radii) is list and len(radii) >= 3 and
            all(finite(x) and x > 0 for x in radii) and radii == sorted(set(radii)) and
            nominal in radii and radii[0] < nominal < radii[-1], 'Topology requires distinct lower/nominal/upper sensitivity radii.')
    return profile


def interpolate(times, values, time):
    require(times[0] <= time <= times[-1], 'Interpolation may not extrapolate saved charge.')
    index = bisect.bisect_left(times, time)
    if times[index] == time:
        return values[index]
    left = index - 1
    return values[left] + (values[index] - values[left]) * (time - times[left]) / (times[index] - times[left])


def first_upcrossing(times, values, threshold):
    for index in range(len(times) - 1):
        lo, hi = values[index:index + 2]
        if lo <= threshold <= hi and hi > lo:
            return times[index] + (threshold - lo) / (hi - lo) * (times[index + 1] - times[index])
    return None


def waveform_observables(times, charge_keV, ionisation_energy_eV, profile):
    """Return signed original/filtered current and observed-span crossing values."""
    validate_profile(profile)
    require(finite(ionisation_energy_eV) and ionisation_energy_eV > 0, 'Invalid saved ionisation energy.')
    require(len(times) == len(charge_keV) and len(times) >= 2 and all(finite(x) for x in times + charge_keV)
            and all(b > a for a, b in zip(times, times[1:])), 'Full native signal must be finite with strictly increasing time.')
    require(times[0] == 0, 'Saved signal time must start at the recorded group origin.')
    factor_C = 1000 / ionisation_energy_eV * ELEMENTARY_CHARGE_C
    midpoints = [(a + b) / 2 for a, b in zip(times, times[1:])]
    current = [(b - a) / (tb - ta) * factor_C * 1e18
               for ta, tb, a, b in zip(times, times[1:], charge_keV, charge_keV[1:])]
    signal = {'time_since_origin_ns': times, 'induced_equivalent_energy_keV': charge_keV,
              'signed_charge_fC': [x * factor_C * 1e15 for x in charge_keV],
              'interval_midpoint_ns': midpoints, 'signed_current_nA': current,
              'filtered_midpoint_ns': [], 'filtered_signed_current_nA': []}
    start, end = profile['analysis_window_ns']; width = profile['current_filter']['width_ns']
    polarity = profile['polarity']; flags = []
    for time in midpoints:
        left, right = time - width / 2, time + width / 2
        if max(start, times[0]) <= left and right <= min(end, times[-1]):
            signal['filtered_midpoint_ns'].append(time)
            signal['filtered_signed_current_nA'].append(
                (interpolate(times, charge_keV, right) - interpolate(times, charge_keV, left)) / width * factor_C * 1e18)
    values = signal['filtered_signed_current_nA']; ftimes = signal['filtered_midpoint_ns']
    peak = peak_time = raw_peak = None
    if values:
        peak_index = max(range(len(values)), key=lambda i: polarity * values[i])
        raw_peak = values[peak_index]
        peak, peak_time = polarity * raw_peak, ftimes[peak_index]
        if peak <= 0:
            flags.append('nonpositive_filtered_current_peak')
    else:
        flags.append('no_complete_filter_support')
    change = t10 = t90 = rise = None
    if times[-1] < end:
        flags.append('trace_does_not_cover_analysis_window')
    else:
        q0 = interpolate(times, charge_keV, start); qend = interpolate(times, charge_keV, end)
        change = qend - q0
        selected_times = [start] + [t for t in times if start < t < end] + [end]
        selected_charge = [polarity * (interpolate(times, charge_keV, t) - q0) for t in selected_times]
        if any(b < a for a, b in zip(selected_charge, selected_charge[1:])):
            flags.append('nonmonotonic_signed_observed_charge')
        span = polarity * change
        if span > 0:
            t10 = first_upcrossing(selected_times, selected_charge, 0.1 * span)
            t90 = first_upcrossing(selected_times, selected_charge, 0.9 * span)
            if t10 is not None and t90 is not None and t90 >= t10:
                rise = t90 - t10
            else:
                flags.append('observed_crossings_unavailable')
        else:
            flags.append('nonpositive_signed_observed_span')
    observed = {'signed_filtered_current_peak_nA': peak, 'native_signed_current_at_peak_nA': raw_peak,
                'declared_polarity': polarity, 'peak_time_since_origin_ns': peak_time,
                'signed_charge_change_keV': change, 'raw_final_induced_keV': charge_keV[-1],
                'raw_charge_end_ns': times[-1], 't10_ns': t10, 't90_ns': t90,
                'charge_rise_10_90_ns': rise, 'sample_count': len(times), 'flags': flags}
    return signal, observed


def topology(steps, profile):
    """Connected components of spatial step points, with declared radius sensitivity."""
    rule = profile['topology']; points = []; rows = []
    for step in steps:
        energy = step.get('energy_keV')
        require(finite(energy) and energy >= 0, 'Topology requires finite nonnegative original deposition energy.')
        if energy > 0:
            point = step.get(rule['point_rule'])
            require(type(point) is list and len(point) == 3 and all(finite(x) for x in point), 'Positive-energy topology point is unavailable.')
            points.append(point); rows.append(step['raw_row_index'])
    results = []
    for radius in rule['sensitivity_thresholds_mm']:
        parents = list(range(len(points)))
        def find(index):
            while parents[index] != index:
                parents[index] = parents[parents[index]]; index = parents[index]
            return index
        for i in range(len(points)):
            for j in range(i):
                if math.dist(points[i], points[j]) <= radius:
                    parents[find(i)] = find(j)
        components = {}
        for i, row in enumerate(rows):
            components.setdefault(find(i), []).append(row)
        clusters = list(components.values())
        results.append({'threshold_mm': radius, 'cluster_count': len(clusters), 'clusters_raw_row_indices': clusters})
    nominal = next(x for x in results if x['threshold_mm'] == rule['nominal_threshold_mm'])
    count = nominal['cluster_count']
    return {**copy.deepcopy(rule), 'positive_energy_point_count': len(points),
            'cluster_count': count, 'clusters_raw_row_indices': nominal['clusters_raw_row_indices'],
            'proxy_label': 'zero_positive_deposit' if count == 0 else 'one_spatial_cluster_proxy' if count == 1 else 'multiple_spatial_clusters_proxy',
            'sensitivity': results, 'threshold_sensitive': len({x['cluster_count'] for x in results}) > 1,
            'limitation': 'Step-position proxy with single-link chaining; affected by scoring, transport step and geometry resolution. No independently established single-site/multi-site label.'}


def selection_reasons(scalar, endpoints, observed):
    reasons = []
    readout = scalar.get('readout'); flags = scalar.get('transport_flags')
    if scalar.get('status') == 'native_transport_failed':
        reasons.append('native_transport_failed')
    else:
        if not endpoints or not isinstance(flags, dict):
            reasons.append('endpoint_status_unavailable')
        if isinstance(flags, dict):
            if flags.get('step_limits', 0) > 0 or any(e.get('endpoint', {}).get('step_limit_reached') is True for e in endpoints):
                reasons.append('native_step_limit')
            if flags.get('stopped_without_contact', 0) > 0 or any(not e.get('endpoint', {}).get('contact_ids') for e in endpoints):
                reasons.append('incomplete_endpoint')
    if not isinstance(readout, dict):
        reasons.append('readout_unavailable')
    else:
        if readout.get('accepted') is not True:
            reasons.append('readout_rejected')
        if readout.get('saturated') is True:
            reasons.append('readout_saturated')
        for key in ('charge_clipped_at_window', 'window_limited', 'gate_limited', 'tail_truncated_possible'):
            if readout.get(key) is True:
                reasons.append(key)
        energy = readout.get('reconstructed_energy_keV')
        if not finite(energy) or energy <= 0:
            reasons.append('invalid_reconstructed_energy')
    group = scalar.get('group', {})
    for key in ('boundary_split_within_horizon', 'recovery_not_established'):
        if group.get(key) is True:
            reasons.append(key)
    if observed is None:
        reasons.append('full_signal_unavailable')
    else:
        for key in ('no_complete_filter_support', 'trace_does_not_cover_analysis_window',
                    'nonpositive_filtered_current_peak', 'nonpositive_signed_observed_span', 'observed_crossings_unavailable'):
            if key in observed['flags']:
                reasons.append(key)
    return reasons


def group_record(scalar, truth, endpoints, samples, eion, profile):
    byrow = {x['raw_row_index']: x for x in truth['steps']}
    rows = scalar['raw_row_indices']
    require(len(set(rows)) == len(rows) and all(row in byrow for row in rows), 'Group contains missing or repeated original raw row IDs.')
    deposits = [byrow[row] for row in rows]
    require(all(e['raw_row_index'] in rows for e in endpoints), 'Endpoint belongs to another deposit group.')
    signal = observed = None
    if samples is not None:
        signal, observed = waveform_observables(samples[0], samples[1], eion, profile)
        require(scalar.get('status') != 'native_transport_failed', 'Native failure must not contain invented signal samples.')
    reasons = selection_reasons(scalar, endpoints, observed); valid = not reasons
    if observed is not None:
        observed['selection_valid'] = valid
        observed['interpretation'] = 'observed_saved_waveform' if valid else 'provisional_observed_saved_waveform_selection_invalid'
    readout = scalar.get('readout') or {}; energy = readout.get('reconstructed_energy_keV')
    return {'group_id': scalar['group_id'], 'global_initial_id': identity(scalar),
            'batch_index': scalar.get('batch_index'), 'local_initial_id': scalar.get('local_initial_id', scalar['event_id']),
            'event_id': scalar['event_id'], 'global_decay_id': scalar['global_decay_id'],
            'origin_time_ns': scalar['origin_time_ns'], 'raw_row_indices': rows,
            'truth_Edep_keV': scalar['deposited_energy_keV'], 'Erec_keV': energy,
            'saved_scalar': scalar, 'endpoints': endpoints, 'deposits': deposits,
            'selection': {'valid': valid, 'reasons': reasons},
            'features': {'A_nA': observed['signed_filtered_current_peak_nA'] if valid else None,
                         'A_over_E_nA_per_keV': observed['signed_filtered_current_peak_nA'] / energy if valid else None,
                         'charge_rise_10_90_ns': observed['charge_rise_10_90_ns'] if valid else None},
            'observed': observed, 'signal': signal, 'topology': topology(deposits, profile)}


def identity(row):
    return exact_id(row.get('global_initial_id', row.get('global_decay_id')), 'Global original primary ID')


def json_lines(path):
    from catalog_result_validation import json_lines as shared_reader
    return list(shared_reader(path))


def inspect_saved_run(run_dir, root):
    """Use existing completion/inventory/census authorities; never execute a stage."""
    import batch_execution as E
    directory = Path(run_dir).resolve(); root = Path(root).resolve()
    require(directory == W.run_path(directory.name, root).resolve(), 'Input must be an existing .local/runs saved workflow root.')
    original = read_json(directory / 'run.json'); kind = original.get('kind')
    if kind == E.KIND:
        verified = E.inspect(directory.name, root=root)
    else:
        import catalog_workflow as C
        if kind == C.KIND:
            verified = C.inspect(directory.name, root=root)
        elif kind == W.KIND:
            verified = W.inspect(directory.name, root=root)
        else:
            raise ControlError('Unsupported saved workflow kind; PSD1 needs the shared full-census JSONL/signals contract.', 'psd_saved_schema_unavailable')
    require(verified.get('verification') == 'terminal_artifacts_verified' and original.get('status') in E.TERMINAL,
            'Only a hash-checked completed saved case can be derived.')
    return original


def response_directories(directory, receipt):
    if 'batching' in receipt['resolved']:
        import batch_execution as E
        return [E.batch_directory(directory, batch['batch_index']) / 'response'
                for batch in E.iter_batches(receipt['resolved']['batching'])]
    return [directory / 'response']


def read_signals(path, group_keys):
    samples = {}
    with path.open(encoding='utf-8', newline='') as stream:
        reader = csv.DictReader(stream)
        require(reader.fieldnames is not None and len(set(reader.fieldnames)) == len(reader.fieldnames) and
                {'event_id', 'global_decay_id', 'group_id', 'time_since_origin_ns', 'induced_equivalent_energy_keV'} <= set(reader.fieldnames),
                'Full saved native signal columns are unavailable.')
        for row in reader:
            require(None not in row and all(v is not None for v in row.values()), 'Malformed native signal CSV row.')
            ids = {key: int(row[key]) for key in ('event_id', 'global_decay_id', 'group_id', 'global_initial_id', 'batch_index', 'local_initial_id') if key in row}
            require(all(str(value) == row[key] for key, value in ids.items()), 'Signal identity is not an exact integer spelling.')
            key = (identity(ids), exact_id(ids['group_id'], 'Pulse group ID'))
            require(key in group_keys, 'Native signal references an unknown original pulse group.')
            expected = group_keys[key]
            require(all(expected.get(k) == v for k, v in ids.items()), 'Native signal raw/global identity differs from the original group.')
            t, q = float(row['time_since_origin_ns']), float(row['induced_equivalent_energy_keV'])
            require(finite(t) and finite(q), 'Native signal contains nonfinite values.')
            pair = samples.setdefault(key, ([], [])); pair[0].append(t); pair[1].append(q)
    return samples


def build_records(directory, receipt, profile):
    records = []; summaries = []; consumed = set()
    for response in response_directories(directory, receipt):
        for name in ('run.json', 'truth.jsonl', 'scalars.jsonl', 'endpoints.jsonl', 'signals.csv', 'readout-config.json', 'profile.json'):
            path = response / name
            require(path.is_file(), 'Unsupported saved response schema: required ' + name + ' is unavailable.')
            consumed.add(path)
        report = read_json(response / 'run.json'); summaries.append(report)
        wiring = report.get('operating_model', receipt['resolved'].get('operating_model', {})).get('wiring_factor')
        if wiring is not None:
            require(profile['polarity'] == wiring, 'Explicit feature polarity differs from the saved fixed readout wiring.')
        eion = report['ionisation_energy_eV']; calibration = report['calibration']
        require(calibration.get('method', '').startswith('single delta-charge injection') and
                finite(calibration.get('volts_per_keV')) and calibration['volts_per_keV'] > 0,
                'Features require recorded independent injection calibration.')
        truths = json_lines(response / 'truth.jsonl'); scalars = json_lines(response / 'scalars.jsonl')
        primary_scalars = {}; pulses = {}
        for scalar in scalars:
            pid = identity(scalar)
            if scalar.get('record_kind') == 'decay' and scalar.get('group_id') is None:
                require(pid not in primary_scalars, 'Duplicate original primary scalar.')
                primary_scalars[pid] = scalar
            elif scalar.get('record_kind') == 'pulse':
                key = (pid, exact_id(scalar['group_id'], 'Pulse group ID'))
                require(key not in pulses, 'Duplicate original pulse group.')
                pulses[key] = scalar
            else:
                require(False, 'Unsupported saved scalar record kind.')
        endpoints = {}
        for endpoint in json_lines(response / 'endpoints.jsonl'):
            key = (identity(endpoint), exact_id(endpoint['group_id'], 'Endpoint group ID'))
            require(key in pulses, 'Endpoint references an unknown pulse group.')
            require(all(endpoint.get(k) == pulses[key].get(k) for k in ('event_id', 'global_decay_id', 'batch_index', 'local_initial_id', 'global_initial_id') if k in endpoint), 'Endpoint identity differs from group.')
            endpoints.setdefault(key, []).append(endpoint)
        samples = read_signals(response / 'signals.csv', pulses)
        for truth in truths:
            pid = identity(truth); require(pid in primary_scalars, 'Original truth primary has no retained scalar.')
            primary = primary_scalars.pop(pid)
            require(primary['raw_row_indices'] == [s['raw_row_index'] for s in truth['steps']], 'Original primary raw row census differs.')
            groups = []
            for group in truth['pulse_groups']:
                key = (pid, group['group_id']); require(key in pulses, 'Truth pulse group has no retained scalar.')
                scalar = pulses.pop(key)
                require(scalar['group'] == group and scalar['raw_row_indices'] == group['row_indices'], 'Original pulse group rows or settings changed.')
                groups.append(group_record(scalar, truth, endpoints.pop(key, []), samples.pop(key, None), eion, profile))
            reasons = ['zero_deposit'] if primary['zero_deposit'] else []
            if not groups and not reasons: reasons.append('no_pulse_groups')
            for group in groups:
                reasons.extend('group_' + str(group['group_id']) + ':' + reason for reason in group['selection']['reasons'])
            records.append({'global_initial_id': pid, 'event_id': primary['event_id'], 'global_decay_id': primary['global_decay_id'],
                            'batch_index': primary.get('batch_index'), 'local_initial_id': primary.get('local_initial_id', primary['event_id']),
                            'truth_Edep_keV': primary['deposited_energy_keV'],
                            'Erec_keV': groups[0]['Erec_keV'] if len(groups) == 1 else None,
                            'truth': truth, 'primary': primary, 'pulse_groups': groups,
                            'selection': {'valid': bool(groups) and not reasons, 'reasons': reasons}})
        require(not primary_scalars and not pulses and not endpoints and not samples, 'Response contains unmatched scalar, endpoint or signal identities.')
    count = receipt['resolved']['selection']['primary_count']
    require([r['global_initial_id'] for r in records] == list(range(count)), 'Full-census original primary order is incomplete.')
    return records, summaries, consumed


def csv_bytes(records):
    import io
    stream = io.StringIO(newline=''); writer = csv.DictWriter(stream, fieldnames=CSV_COLUMNS, lineterminator='\n')
    writer.writeheader()
    for record in records:
        row = {key: encoded(record[key]).decode('utf-8').rstrip('\n') for key in CSV_COLUMNS[:7]}
        row.update(selection_valid=json.dumps(record['selection']['valid']),
                   selection_reasons_json=encoded(record['selection']['reasons']).decode('utf-8').rstrip('\n'),
                   pulse_count=str(len(record['pulse_groups'])), record_json=encoded(record).decode('utf-8').rstrip('\n'))
        writer.writerow(row)
    return stream.getvalue().encode('utf-8')


def default_bundle_dir(root, config_sha256):
    require(type(config_sha256) is str and re.fullmatch('[0-9a-f]{64}', config_sha256), 'Invalid configuration SHA256.')
    return safe_path(root, '.local/psd-features/' + config_sha256 + '/bundle')


def export_bundle(run_dir, out_dir, profile_path=None, *, root=None):
    """Create one full-census bundle; never overwrite a prior or failed derivative."""
    directory = Path(run_dir).resolve(); root = Path(root or directory.parents[2]).resolve()
    out = Path(out_dir).absolute()
    require(out.is_relative_to(root / '.local') and not out.is_relative_to(directory), 'Derived output must stay under project .local outside original science root.')
    out = safe_path(root, out.relative_to(root).as_posix())
    require(not out.exists(), 'Derived output already exists; preserve it and select a fresh derivative root.')
    source_pins = {ref: stamp(safe_path(root, ref)) for ref in SOURCE_REFS}
    profile_path = Path(profile_path or DEFAULT_PROFILE)
    profile_bytes = profile_path.read_bytes(); profile = validate_profile(W.decode_json(profile_bytes.decode('utf-8')))
    receipt = inspect_saved_run(directory, root)
    records, summaries, consumed = build_records(directory, receipt, profile)
    consumed.update(directory / name for name in ('run.json', 'resolved-config.json', 'COMPLETE.json'))
    consumed.update(path for path in (directory / 'shared/native/preparation.json',) if path.is_file())
    input_pins = {path.relative_to(root).as_posix(): stamp(path) for path in sorted(consumed)}
    definitions = encoded(DEFINITIONS)
    dataset = {'kind': KIND, 'schema_version': SCHEMA_VERSION, 'configuration_sha256': receipt['configuration_sha256'],
               'profile': profile, 'records': records,
               'counts': {'primaries': len(records), 'zero_deposit_primaries': sum(r['primary']['zero_deposit'] for r in records),
                          'pulse_groups': sum(len(r['pulse_groups']) for r in records),
                          'selected_groups': sum(g['selection']['valid'] for r in records for g in r['pulse_groups'])},
               'provenance': {'run_ref': directory.relative_to(root).as_posix(), 'run_kind': receipt['kind'], 'run_status': receipt['status'],
                              'resolved_configuration': receipt['resolved'], 'response_summaries': summaries,
                              'input_artifacts': input_pins, 'extractor_sources': source_pins,
                              'profile_sha256': hashlib.sha256(profile_bytes).hexdigest(),
                              'schema_template_sha256': hashlib.sha256(definitions).hexdigest(),
                              'python_version': platform.python_version(), 'science_calls': 0, 'calibration_calls': 0}}
    blobs = {'features.json': encoded(dataset), 'features.csv': csv_bytes(records),
             'profile.json': profile_bytes, 'schema.json': definitions}
    # Check readers/writers and original bytes before any bound derivative write.
    require(source_pins == {ref: stamp(safe_path(root, ref)) for ref in SOURCE_REFS}, 'Feature source changed during derivation; wait for source freeze.')
    require(input_pins == {ref: stamp(safe_path(root, ref)) for ref in input_pins}, 'Saved input changed during derivation.')
    require(profile_path.read_bytes() == profile_bytes, 'Feature profile changed during derivation.')
    out.mkdir(parents=True, exist_ok=False)
    manifest = {'kind': KIND, 'schema_version': SCHEMA_VERSION, 'status': 'complete',
                'configuration_sha256': receipt['configuration_sha256'], 'run_ref': dataset['provenance']['run_ref'],
                'counts': dataset['counts'], 'input_artifacts': input_pins, 'extractor_sources': source_pins,
                'profile_sha256': dataset['provenance']['profile_sha256'],
                'schema_template_sha256': dataset['provenance']['schema_template_sha256'],
                'artifacts': {name: {'sha256': hashlib.sha256(blob).hexdigest(), 'bytes': len(blob)} for name, blob in blobs.items()}}
    for name, blob in blobs.items():
        with (out / name).open('xb') as stream: stream.write(blob)
    with (out / 'manifest.json').open('xb') as stream: stream.write(encoded(manifest))
    complete = {'kind': KIND, 'status': 'complete', 'schema_version': SCHEMA_VERSION,
                'configuration_sha256': manifest['configuration_sha256'], 'manifest_sha256': sha(out / 'manifest.json')}
    with (out / 'COMPLETE.json').open('xb') as stream: stream.write(encoded(complete))
    load_bundle(out, expected_config_sha256=manifest['configuration_sha256'], root=root)
    return manifest


def load_bundle(bundle_dir, expected_config_sha256=None, *, root=None, verify_inputs=True):
    """Validate derivative hashes, required schema, original identity and raw bindings.

    root defaults to this installed project, never a path supplied by the manifest.
    verify_inputs=False only skips original disk hashes; structural/schema/source
    integrity and the COMPLETE/manifest binding are always checked.
    """
    root = Path(root or W.ROOT).resolve(); directory = Path(bundle_dir).absolute()
    require(directory.is_relative_to(root / '.local'), 'Feature bundle must stay in this project .local root.')
    directory = safe_path(root, directory.relative_to(root).as_posix())
    complete = read_json(directory / 'COMPLETE.json'); manifest = read_json(directory / 'manifest.json')
    require(complete.get('kind') == manifest.get('kind') == KIND and complete.get('status') == manifest.get('status') == 'complete'
            and type(complete.get('schema_version')) is int and complete['schema_version'] == manifest.get('schema_version') == SCHEMA_VERSION
            and complete.get('manifest_sha256') == sha(directory / 'manifest.json')
            and complete.get('configuration_sha256') == manifest.get('configuration_sha256'), 'Feature completion/manifest binding changed.')
    if expected_config_sha256 is not None:
        require(manifest['configuration_sha256'] == expected_config_sha256, 'Feature bundle belongs to another selected saved configuration.')
    require(set(manifest['artifacts']) == {'features.json', 'features.csv', 'profile.json', 'schema.json'}, 'Feature artifact census changed.')
    for name, expected in manifest['artifacts'].items():
        require(stamp(safe_path(directory, name)) == expected, 'Feature artifact bytes changed: ' + name)
    require((directory / 'schema.json').read_bytes() == encoded(DEFINITIONS) and
            manifest['schema_template_sha256'] == sha(directory / 'schema.json'), 'Feature schema definitions differ from this required reader version.')
    profile = validate_profile(read_json(directory / 'profile.json'))
    require(manifest['profile_sha256'] == sha(directory / 'profile.json'), 'Feature profile binding changed.')
    require(set(manifest['extractor_sources']) == set(SOURCE_REFS), 'Feature source provenance is incomplete.')
    for ref, expected in manifest['extractor_sources'].items():
        require(stamp(safe_path(root, ref)) == expected, 'Current feature reader/source differs from exported source: ' + ref)
    data = read_json(directory / 'features.json'); provenance = data['provenance']
    require(data.get('kind') == KIND and type(data.get('schema_version')) is int and data['schema_version'] == SCHEMA_VERSION
            and data['configuration_sha256'] == manifest['configuration_sha256'] and data['profile'] == profile
            and data['counts'] == manifest['counts'], 'Feature required dataset schema/configuration/counts changed.')
    for key in ('input_artifacts', 'extractor_sources', 'profile_sha256', 'schema_template_sha256', 'run_ref'):
        require(provenance.get(key) == manifest.get(key), 'Feature provenance binding changed: ' + key)
    require(provenance.get('science_calls') == 0 and provenance.get('calibration_calls') == 0, 'Saved-only derivation provenance changed.')
    run = safe_path(root, provenance['run_ref']); require(run == W.run_path(run.name, root), 'Invalid saved input root identity.')
    require(all(ref.startswith(provenance['run_ref'] + '/') for ref in manifest['input_artifacts']), 'Input artifact is outside selected saved run.')
    require({provenance['run_ref'] + '/' + n for n in ('run.json', 'resolved-config.json', 'COMPLETE.json')} <= set(manifest['input_artifacts']), 'Saved run authority pins are incomplete.')
    if verify_inputs:
        for ref, expected in manifest['input_artifacts'].items():
            require(stamp(safe_path(root, ref)) == expected, 'Original saved input bytes changed: ' + ref)
        original = read_json(run / 'run.json'); plan = read_json(run / 'resolved-config.json')
        require(original['configuration_sha256'] == plan['configuration_sha256'] == manifest['configuration_sha256']
                and original['resolved'] == plan['resolved'] == provenance['resolved_configuration'], 'Original selected saved configuration identity changed.')
        rebuilt_records, rebuilt_summaries, consumed = build_records(run, original, profile)
        require(data['records'] == rebuilt_records and provenance['response_summaries'] == rebuilt_summaries,
                'Feature raw values/flags/census differ from original full-resolution saved inputs.')
        require(all(path.relative_to(root).as_posix() in manifest['input_artifacts'] for path in consumed),
                'Feature consumed input inventory is incomplete.')
    records = data['records']; expected_count = provenance['resolved_configuration']['selection']['primary_count']
    require(type(records) is list and [r['global_initial_id'] for r in records] == list(range(expected_count)), 'Feature export removed, reordered or duplicated original primaries.')
    counts = {'primaries': len(records), 'zero_deposit_primaries': sum(r['primary']['zero_deposit'] for r in records),
              'pulse_groups': sum(len(r['pulse_groups']) for r in records),
              'selected_groups': sum(g['selection']['valid'] for r in records for g in r['pulse_groups'])}
    require(counts == manifest['counts'], 'Feature primary/group selection census changed.')
    for record in records:
        require(identity(record['truth']) == identity(record['primary']) == record['global_initial_id']
                and record['truth_Edep_keV'] == record['primary']['deposited_energy_keV']
                and record['primary']['raw_row_indices'] == [s['raw_row_index'] for s in record['truth']['steps']], 'Feature original primary identity/truth changed.')
        expected_groups = record['truth']['pulse_groups']; groups = record['pulse_groups']
        require(len(groups) == len(expected_groups), 'Feature lost an original pulse group.')
        for group, original_group in zip(groups, expected_groups):
            scalar = group['saved_scalar']; require(group['group_id'] == original_group['group_id'] == scalar['group_id']
                and group['global_initial_id'] == record['global_initial_id'] and group['raw_row_indices'] == original_group['row_indices']
                and scalar['group'] == original_group and group['Erec_keV'] == (scalar.get('readout') or {}).get('reconstructed_energy_keV')
                and group['truth_Edep_keV'] == scalar['deposited_energy_keV'], 'Feature pulse/deposit/readout identity changed.')
            signal = group['signal']; samples = (signal['time_since_origin_ns'], signal['induced_equivalent_energy_keV']) if signal else None
            summary = next(s for s in provenance['response_summaries'] if s.get('batch', {}).get('batch_index') == group['batch_index'])
            rebuilt = group_record(scalar, record['truth'], group['endpoints'], samples, summary['ionisation_energy_eV'], profile)
            require(group == rebuilt, 'Feature selection/observables/topology differ from declared profile.')
        expected_energy = groups[0]['Erec_keV'] if len(groups) == 1 else None
        require(record['Erec_keV'] == expected_energy, 'Primary Erec was fabricated or silently summed.')
        reasons = ['zero_deposit'] if record['primary']['zero_deposit'] else []
        if not groups and not reasons: reasons.append('no_pulse_groups')
        for group in groups:
            reasons.extend('group_' + str(group['group_id']) + ':' + reason for reason in group['selection']['reasons'])
        require(record['selection'] == {'valid': bool(groups) and not reasons, 'reasons': reasons},
                'Primary selection reasons differ from retained groups/zero status.')
    require((directory / 'features.csv').read_bytes() == csv_bytes(records), 'CSV does not losslessly match full JSON primary records.')
    return data


def get_record(bundle, primary_id, group_id=None):
    pid = exact_id(primary_id, 'Selected primary ID')
    require(pid < len(bundle['records']) and bundle['records'][pid]['global_initial_id'] == pid, 'Selected original primary is unavailable.')
    primary = bundle['records'][pid]
    if group_id is None:
        return primary
    gid = exact_id(group_id, 'Selected pulse group ID')
    for group in primary['pulse_groups']:
        if group['group_id'] == gid:
            return group
    raise ControlError('Selected original pulse group has no saved feature record.', 'psd_group_unavailable')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, type=Path); parser.add_argument('--output', type=Path)
    parser.add_argument('--profile', type=Path)
    args = parser.parse_args(argv)
    try:
        run = args.run.resolve()
        output = args.output or default_bundle_dir(run.parents[2], read_json(run / 'run.json')['configuration_sha256'])
        value = export_bundle(run, output, args.profile)
        print(json.dumps({'kind': KIND, 'status': value['status'], 'configuration_sha256': value['configuration_sha256'],
                          'counts': value['counts'], 'output': str(output)}, sort_keys=True))
        return 0
    except (ControlError, OSError, ValueError, KeyError, TypeError) as error:
        print(str(error), file=sys.stderr); return 1


if __name__ == '__main__':
    raise SystemExit(main())
