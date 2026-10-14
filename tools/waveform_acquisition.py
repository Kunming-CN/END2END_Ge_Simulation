"""Hash-bound PSD2 synthetic waveform acquisition from a completed PSD1 bundle.

CLI: python tools/waveform_acquisition.py --run .local/runs/NAME [--julia EXE]
This runs bounded electronics and independent injection only, never detector,
field, SSD or radiation calculations. Canonical PSD1 is required and unchanged.
Output defaults to .local/waveform-acquisition/<configurationSHA>/bundle and must
not exist. Reader load_bundle/get_record joins all original PSD1 records without
Julia or execution. The new acquisition_energy_keV never replaces original Erec.
"""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time

import psd_features as P
from local_ui_jobs import ControlError, safe_path

KIND = 'saved_waveform_acquisition_v1'
PROFILE_KIND = 'synthetic_waveform_acquisition_profile_v1'
SCHEMA_VERSION = 1
DEFAULT_PROFILE = Path(__file__).with_name('waveform_acquisition_profile.json')
SOURCE_REFS = P.SOURCE_REFS + ['tools/waveform_acquisition.py', 'simulation/waveform_acquisition.jl',
    'simulation/readout.jl', 'simulation/readout_profiles.jl', 'simulation/readout_demo.json',
    'simulation/Project.toml', 'simulation/Manifest.toml']
PROFILE_KEYS = {'kind', 'schema_version', 'name', 'sampling_rate_Hz', 'adc', 'record_window_ns',
                'trigger', 'bandwidth', 'noise', 'measurement_polarity', 'calibration'}
CSV_COLUMNS = ['global_initial_id', 'zero_deposit', 'acquisition_energy_keV', 'selection_valid', 'record_json']
NOISE_PREFIX = 'waveform-acquisition-noise-v1'
encoded = P.encoded
read_json = P.read_json
sha = P.sha
stamp = P.stamp
finite = P.finite
DEFINITIONS = {
    'kind': KIND, 'schema_version': 1,
    'scope': 'Synthetic teaching/engineering acquisition; no measured hardware, physical noise/resolution, Li CCE or experimental validation.',
    'census': 'Every original primary and group is retained. Exact PSD1 manifest/artifacts and per-record hashes bind lossless original truth, scalars, endpoints, full charge, settings and calibration; reader joins them without execution.',
    'input': 'Complete signed native charge in keV-equivalent, not bounded display arrays. Convert charge with original ionisation energy and exact SI elementary charge. Original peak ADC, Erec, preamp display, calibration and settings are immutable.',
    'frontend': 'Reuse Readout.transition on original native grid with constant current from each adjacent charge increment. Signed preamp is negative for positive induced charge. Acquisition first-order RC pole has exact within-bin forcing by that CSA exponential; no tail beyond finite native charge support.',
    'sampling': 'Uniform ADC times relative to original group origin, inclusive declared endpoints when supported. ADC interval is an integer multiple of the native grid. A declared external trigger resets isolated electronics at group origin; negative-time pretrigger is assumed zero analog prehistory with sampled noise, not recorded physical prehistory or pileup.',
    'bandwidth': 'One causal lowpass pole at stated -3dB cutoff, before ADC sampling. Response 1/(1+j*f/fc); finite attenuation is not ideal anti-alias suppression. Native constant-current discretization and residual aliasing remain explicit limitations.',
    'adc': 'Bipolar floor((V-min)/LSB), clamped codes; code centre min+(code+0.5)*LSB. Lower clip V<min; upper clip V>=max. Signed preamp/decoded samples are retained without rectification. Fixed -1 measurement polarity is applied only to peak measurement.',
    'energy': 'A separate noiseless delta-charge injection into the unchanged original CSA passes through the acquisition pole and sampling. Sampled analog injection peak defines one fixed volts/keV per frontend. Event energy uses baseline_code_center(0)-minimum(posttrigger ADC centres); truth Edep never sets gain. Original Erec stays separate.',
    'selection': 'Original PSD1 invalid reasons plus new clipping/native-support/window/edge/nonpositive reasons force canonical acquisition_energy_keV to null. Computable ADC peak/energy remain observed provisional. Native failures have null acquisition trace/energy; zero primaries have no invented pulse.',
    'threshold': 'External group-origin trigger has no new voltage/amplitude threshold. Original readout/PSD1 rejection reasons remain mandatory; the additional waveform energy requires positive fixed-polarity ADC excursion, no clipping and complete declared support.',
    'noise': 'Postfilter sampled iid Gaussian voltage at ADC input only; default RMS=0. SHA256 counter Box-Muller normals keyed by declared root seed and original global primary/group/sample index, independent of iteration order. This is an assumed discrete noise model, not bandwidth-filtered analog noise or parcel/hardware resolution.',
    'uncertainty': 'Quantization excursion bound includes deterministic zero-code centre offset. Nonzero noise reports single-sample sigma and 99% simultaneous Gaussian union bound across record samples, conditional on no clipping; peak winner bias possible. These are model bounds, not measured energy resolution.',
    'serialization': 'UTF-8 sorted-key compact round-trip JSON, no NaN, one trailing LF; lossless CSV record_json mirrors each compact census record. Required source/schema/profile hashes and exact original PSD1 bindings are validated independently of rehashed derived manifests.',
    'csv_columns': CSV_COLUMNS,
}


def require(condition, message):
    if not condition:
        raise ControlError(message, 'waveform_acquisition_invalid')


def validate_profile(p):
    require(type(p) is dict and set(p) == PROFILE_KEYS and p['kind'] == PROFILE_KIND and type(p['schema_version']) is int and p['schema_version'] == 1, 'Unsupported acquisition profile fields/version.')
    require(type(p['name']) is str and re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', p['name']), 'Invalid acquisition profile name.')
    rate = p['sampling_rate_Hz']; require(finite(rate) and 1e5 <= rate <= 1e9, 'Sampling rate outside bounded example.')
    adc = p['adc']; require(type(adc) is dict and set(adc) == {'bits', 'minimum_V', 'maximum_V'} and type(adc['bits']) is int and 2 <= adc['bits'] <= 24
        and finite(adc['minimum_V']) and finite(adc['maximum_V']) and adc['minimum_V'] < 0 < adc['maximum_V'], 'Invalid bipolar waveform ADC.')
    bw = p['bandwidth']; require(type(bw) is dict and set(bw) == {'kind', 'cutoff_Hz'} and bw['kind'] == 'causal_single_pole_lowpass'
        and finite(bw['cutoff_Hz']) and 0 < bw['cutoff_Hz'] < rate/2, 'Causal cutoff must be below Nyquist; no ideal alias-free guarantee.')
    window = p['record_window_ns']; step = 1e9/rate
    require(type(window) is list and len(window) == 2 and all(finite(x) for x in window) and -1e6 <= window[0] <= 0 < window[1] <= 1e6
        and all(math.isclose(x/step, round(x/step), rel_tol=0, abs_tol=1e-8) for x in window) and (window[1]-window[0])/step+1 <= 200000, 'Record window must align to bounded uniform ADC grid.')
    require(p['trigger'] == {'kind': 'external_group_origin', 'offset_ns': 0.0, 'prehistory': 'isolated_reset_zero_before_group_origin'}, 'Only external group-origin reset trigger is supported.')
    noise = p['noise']; require(type(noise) is dict and set(noise) == {'kind', 'rms_V', 'root_seed_uint64'} and noise['kind'] == 'postfilter_sampled_iid_gaussian_voltage'
        and finite(noise['rms_V']) and 0 <= noise['rms_V'] <= (adc['maximum_V']-adc['minimum_V'])/10 and type(noise['root_seed_uint64']) is str
        and re.fullmatch(r'(0|[1-9]\d{0,19})', noise['root_seed_uint64']) and int(noise['root_seed_uint64']) < 2**64, 'Invalid assumed noise model or seed.')
    require(type(p['measurement_polarity']) is int and p['measurement_polarity'] == -1, 'Require fixed -1 preamp measurement polarity.')
    cal = p['calibration']; require(type(cal) is dict and set(cal) == {'kind', 'energy_keV'} and cal['kind'] == 'independent_delta_charge_injection'
        and finite(cal['energy_keV']) and cal['energy_keV'] > 0, 'Invalid independent acquisition injection.')
    return p


def noise_seed(profile, pid, gid):
    return str(int(hashlib.sha256(f"{NOISE_PREFIX}/{profile['noise']['root_seed_uint64']}/{pid}/{gid}".encode()).hexdigest()[:16], 16))


def normal(seed_string, index):
    digest = hashlib.sha256(f'{NOISE_PREFIX}/{seed_string}/{index}'.encode()).hexdigest()
    a = int(digest[:16], 16) >> 11; b = int(digest[16:32], 16) >> 11
    u = (a+0.5)/2**53; v = (b+0.5)/2**53
    return math.sqrt(-2*math.log(u))*math.cos(2*math.pi*v)


def digitize(v, adc):
    lsb = (adc['maximum_V']-adc['minimum_V'])/2**adc['bits']
    lastcode = 2**adc['bits']-1
    code = 0 if v < adc['minimum_V'] else lastcode if v >= adc['maximum_V'] else min(lastcode, max(0, math.floor((v-adc['minimum_V'])/lsb)))
    return code, adc['minimum_V']+(code+0.5)*lsb, v < adc['minimum_V'], v >= adc['maximum_V']


def reference_frontend(times, charges, config, eion, cutoff, initial_preamp=0.0):
    """Independent scalar closed-form integrity check, never production export.

    Production uses the existing five-state matrix propagator; this verifier
    checks only its analytical CSA and added RC pole against original raw charge.
    """
    require(len(times) == len(charges) >= 2 and all(finite(x) for x in times+charges) and times[0] == charges[0] == 0, 'Invalid native acquisition input.')
    dt = times[1]-times[0]; require(dt > 0 and all(math.isclose(t, i*dt, rel_tol=0, abs_tol=max(1e-9, dt*1e-8)) for i, t in enumerate(times)), 'Native acquisition grid is not uniform/causal.')
    require(len(times) <= config['max_samples_per_event'] and times[-1] <= config['max_window_ns'] and finite(eion) and eion > 0, 'Invalid bounded frontend input.')
    tf = config['feedback_tau_us']*1000; tb = 1e9/(2*math.pi*cutoff)
    ef = math.exp(-dt/tf); eb = math.exp(-dt/tb); cf = config['feedback_capacitance_pF']*1e-12
    factor = 1000/eion*P.ELEMENTARY_CHARGE_C
    kernel = dt/tb*eb if tf == tb else (ef-eb)/(1-tb/tf)
    pre = [initial_preamp]; filt = [0.0]
    for q0, q1 in zip(charges, charges[1:]):
        u = (q1-q0)*factor/dt/cf; steady = -u*tf
        filt.append(filt[-1]*eb + steady*(-math.expm1(-dt/tb)) + (pre[-1]-steady)*kernel)
        pre.append(pre[-1]*ef + u*tf*math.expm1(-dt/tf))
    return pre, filt


def reference_sample(times, pre, filt, profile, derived_seed, noise_rms=None):
    dt = times[1]-times[0]; step = 1e9/profile['sampling_rate_Hz']; window = profile['record_window_ns']
    require(step >= dt and math.isclose(step/dt, round(step/dt), rel_tol=0, abs_tol=1e-8), 'ADC interval must be an integer multiple of native grid.')
    stop = min(window[1], math.floor(times[-1]/step)*step); count = round((stop-window[0])/step)+1
    rms = profile['noise']['rms_V'] if noise_rms is None else noise_rms
    trace = {key: [] for key in ('time_since_origin_ns', 'signed_preamp_V', 'bandwidth_limited_preamp_V', 'noise_V', 'noisy_voltage_V', 'adc_code', 'adc_center_V')}
    lower = upper = False
    for i in range(count):
        t = window[0]+i*step; k = None if t < 0 else round(t/dt)
        pv = 0.0 if k is None else pre[k]; fv = 0.0 if k is None else filt[k]
        nv = 0.0 if rms == 0 else rms*normal(derived_seed, i); value = fv+nv
        code, center, lo, hi = digitize(value, profile['adc']); lower |= lo; upper |= hi
        for key, value in zip(trace, (t, pv, fv, nv, value, code, center)): trace[key].append(value)
    flags = {'adc_lower_clipped': lower, 'adc_upper_clipped': upper, 'record_exceeds_native_support': window[1] > times[-1],
             'record_truncates_native_window': window[1] < times[-1], 'pretrigger_is_assumed_reset_zero': window[0] < 0,
             'finite_native_support': True, 'residual_aliasing_possible': True}
    return trace, flags


def reference_calibration(config, eion, dt, profile):
    energy = profile['calibration']['energy_keV']; charge = energy*1000/eion*P.ELEMENTARY_CHARGE_C
    stop = profile['record_window_ns'][1]; require(math.isclose(stop/dt, round(stop/dt), rel_tol=0, abs_tol=1e-8), 'Injection window must align to native grid.')
    times = [i*dt for i in range(round(stop/dt)+1)]; charges = [0.0]*len(times)
    pre, filt = reference_frontend(times, charges, config, eion, profile['bandwidth']['cutoff_Hz'], -charge/(config['feedback_capacitance_pF']*1e-12))
    trace, flags = reference_sample(times, pre, filt, profile, '0', 0.0)
    post = [i for i, t in enumerate(trace['time_since_origin_ns']) if t >= 0]; peak = max(-trace['bandwidth_limited_preamp_V'][i] for i in post)
    index = next(i for i in post if -trace['bandwidth_limited_preamp_V'][i] == peak)
    require(peak > 0 and index not in (post[0], post[-1]) and not flags['adc_lower_clipped'] and not flags['adc_upper_clipped'], 'Independent injection calibration window/range invalid.')
    lsb = (profile['adc']['maximum_V']-profile['adc']['minimum_V'])/2**profile['adc']['bits']
    return {'method': 'independent delta-charge injection into reset original CSA at group origin; noiseless acquisition-filter sampled analog peak; one fixed gain per frontend',
        'energy_keV': energy, 'charge_C': charge, 'ionisation_energy_eV': eion, 'volts_per_keV': peak/energy, 'peak_V': peak,
        'peak_time_ns': trace['time_since_origin_ns'][index], 'noise_rms_V': 0.0, 'adc_lsb_V': lsb,
        'quantization_half_lsb_energy_keV': lsb/(2*peak/energy), 'hardware_calibrated': False}


def uncertainty(profile, calibration, count):
    sigma = profile['noise']['rms_V']; slope = calibration['volts_per_keV']
    return {'quantization_excursion_bound_keV': calibration['adc_lsb_V']/slope,
        'single_sample_noise_sigma_energy_keV': sigma/slope,
        'simultaneous_noise_confidence': 0.99,
        'simultaneous_noise_bound_keV': sigma*math.sqrt(2*math.log(2*count/0.01))/slope,
        'peak_noise_winner_bias_possible': sigma > 0,
        'conditional_on_no_clipping': True, 'physical_energy_resolution': False}


def reference_acquire(group, config, eion, profile, calibration):
    sig = group['signal']; times = sig['time_since_origin_ns']; charges = sig['induced_equivalent_energy_keV']
    pre, filt = reference_frontend(times, charges, config, eion, profile['bandwidth']['cutoff_Hz'])
    seed = noise_seed(profile, group['global_initial_id'], group['group_id']); trace, flags = reference_sample(times, pre, filt, profile, seed)
    baseline = digitize(0.0, profile['adc'])[1]; post = [i for i, t in enumerate(trace['time_since_origin_ns']) if t >= 0]
    peak = max(baseline-trace['adc_center_V'][i] for i in post); index = next(i for i in post if baseline-trace['adc_center_V'][i] == peak)
    flags['peak_at_record_boundary'] = index in (post[0], post[-1]); reasons = list(group['selection']['reasons'])
    reasons += [key for key in ('adc_lower_clipped', 'adc_upper_clipped', 'record_exceeds_native_support', 'record_truncates_native_window', 'peak_at_record_boundary') if flags[key]]
    if peak <= 0: reasons.append('nonpositive_acquisition_peak')
    reasons = list(dict.fromkeys(reasons)); energy = peak/calibration['volts_per_keV']
    return {'status': 'acquired', 'trace': trace, 'flags': flags, 'selection': {'valid': not reasons, 'reasons': reasons},
        'acquisition_energy_keV': None if reasons else energy,
        'observed': {'provisional': bool(reasons), 'peak_adc_excursion_V': peak, 'peak_time_since_origin_ns': trace['time_since_origin_ns'][index],
                     'acquisition_energy_keV': energy, 'baseline_adc_center_V': baseline},
        'metadata': {'native_time_step_ns': times[1]-times[0], 'native_window_end_ns': times[-1], 'input_sample_count': len(times),
                     'input_final_charge_keV': charges[-1], 'trigger_origin_time_ns': group['origin_time_ns'], 'derived_noise_seed_uint64': seed,
                     'measurement_polarity': -1, 'calibration_id': group['batch_index']}}


def numerical_equal(actual, expected, path='numerical'):
    if type(expected) is dict:
        require(type(actual) is dict and set(actual) == set(expected), 'Acquisition required fields changed: '+path)
        for key in expected: numerical_equal(actual[key], expected[key], path+'.'+key)
    elif type(expected) is list:
        require(type(actual) is list and len(actual) == len(expected), 'Acquisition sample census changed: '+path)
        for i, (a, e) in enumerate(zip(actual, expected)): numerical_equal(a, e, path+'.'+str(i))
    elif type(expected) is float:
        require(finite(actual) and math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-12), 'Acquisition numeric value differs from original input/reference: '+path)
    else:
        require(type(actual) is type(expected) and actual == expected, 'Acquisition value/identity changed: '+path)


def source_bundle(root, config_sha):
    path = P.default_bundle_dir(root, config_sha)
    data = P.load_bundle(path, expected_config_sha256=config_sha, root=root)
    pins = {name: stamp(path/name) for name in ('features.json', 'features.csv', 'profile.json', 'schema.json', 'manifest.json', 'COMPLETE.json')}
    return path, data, pins


def build_request(source, root, profile):
    run = safe_path(root, source['provenance']['run_ref']); receipt = read_json(run/'run.json')
    batches = []
    for index, response in enumerate(P.response_directories(run, receipt)):
        summary = source['provenance']['response_summaries'][index]; batch = summary.get('batch', {}).get('batch_index')
        groups = [g for r in source['records'] for g in r['pulse_groups'] if g['batch_index'] == batch and g['signal'] is not None]
        dt = summary['calibration']['time_step_ns']
        require(all(g['signal']['time_since_origin_ns'][1]-g['signal']['time_since_origin_ns'][0] == dt for g in groups), 'Saved native and calibration grids disagree.')
        config = read_json(response/'readout-config.json'); original_profile = read_json(response/'profile.json')
        # Compare to the separately recorded original profile, not rehashed c alone.
        baseline = read_json(root/'simulation/readout_demo.json'); baseline.update(original_profile['settings'])
        baseline['schema_version'] = 2; baseline['expected_primary_count'] = config['expected_primary_count']; baseline.pop('max_total_samples')
        require(config == baseline, 'Original frontend config differs from its independent frozen profile.')
        batches.append({'batch_index': batch, 'frontend_config': config, 'original_frontend_profile': original_profile,
            'ionisation_energy_eV': summary['ionisation_energy_eV'], 'native_time_step_ns': dt,
            'groups': [{'global_initial_id': g['global_initial_id'], 'group_id': g['group_id'], 'batch_index': g['batch_index'],
                        'origin_time_ns': g['origin_time_ns'], 'source_selection_reasons': g['selection']['reasons'],
                        'time_since_origin_ns': g['signal']['time_since_origin_ns'], 'induced_equivalent_energy_keV': g['signal']['induced_equivalent_energy_keV']} for g in groups]})
    return {'profile': profile, 'batches': batches}


def existing_julia(explicit=None):
    selected = explicit or os.environ.get('JULIA_EXE')
    if selected is None:
        # Recorded installed project runtime; WindowsApps execution alias is not a runtime.
        selected = Path(os.environ.get('USERPROFILE', ''))/'.julia/juliaup/julia-1.13.0+0.x64.w64.mingw32/bin/julia.exe'
    path = Path(selected).resolve(); require(path.is_file(), 'Existing pinned Julia unavailable; provide --julia/JULIA_EXE. No installation or explicit-path fallback.')
    return path


def run_numerical(request, output, root, julia_executable=None):
    executable = existing_julia(julia_executable); request_path = output/'request.json'; result_path = output/'numerical.json'
    request_path.write_bytes(encoded(request)); env = dict(os.environ, JULIA_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', JULIA_PKG_OFFLINE='true')
    argv = [str(executable), '--startup-file=no', '--threads=1', '--project='+str(root/'simulation'), str(root/'simulation/waveform_acquisition.jl'), '--request', str(request_path), '--output', str(result_path)]
    started = time.perf_counter()
    with (output/'julia.log').open('xb') as log:
        completed = subprocess.run(argv, cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=240)
    elapsed = time.perf_counter()-started
    require(completed.returncode == 0 and result_path.is_file(), 'Bounded acquisition Julia failed; preserve request/log/output evidence.')
    result = read_json(result_path)
    return result, {'julia_executable_sha256': sha(executable), 'julia_executable_name': executable.name,
        'child_environment': {'JULIA_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1', 'JULIA_PKG_OFFLINE': 'true'},
        'wall_seconds': elapsed, 'exit_code': completed.returncode, 'software': result['software'],
        'request_sha256': sha(request_path), 'numerical_sha256': sha(result_path), 'log_sha256': sha(output/'julia.log'),
        'detector_calls': 0, 'transport_calls': 0, 'field_calls': 0, 'native_drift_calls': 0,
        'frontend_calls': len(result['groups']), 'calibration_calls': len(result['calibrations'])}


def compact_records(source, numerical, profile):
    results = {(g['global_initial_id'], g['group_id']): g['acquisition'] for g in numerical['groups']}
    require(len(results) == len(numerical['groups']), 'Duplicate acquisition group output.')
    calibrations = {c['batch_index']: c['calibration'] for c in numerical['calibrations']}; records = []
    for original in source['records']:
        groups = []
        for group in original['pulse_groups']:
            key = (group['global_initial_id'], group['group_id'])
            if group['signal'] is None:
                require(key not in results, 'Unavailable native input acquired a fabricated trace.')
                acquisition = {'status': 'native_transport_failed' if group['saved_scalar'].get('status') == 'native_transport_failed' else 'native_signal_unavailable',
                    'trace': None, 'flags': {}, 'selection': {'valid': False, 'reasons': group['selection']['reasons']},
                    'observed': None, 'metadata': None, 'acquisition_energy_keV': None, 'uncertainty': None}
            else:
                require(key in results, 'Original native group has no acquisition output.'); acquisition = copy.deepcopy(results.pop(key))
                acquisition['uncertainty'] = uncertainty(profile, calibrations[group['batch_index']], len(acquisition['trace']['adc_code']))
            groups.append({'group_id': group['group_id'], 'source_group_sha256': hashlib.sha256(encoded(group)).hexdigest(), 'acquisition': acquisition})
        reasons = ['zero_deposit'] if original['primary']['zero_deposit'] else []
        if not groups and not reasons: reasons.append('no_pulse_groups')
        reasons += ['group_'+str(g['group_id'])+':'+reason for g in groups for reason in g['acquisition']['selection']['reasons']]
        records.append({'global_initial_id': original['global_initial_id'], 'source_record_sha256': hashlib.sha256(encoded(original)).hexdigest(),
            'zero_deposit': original['primary']['zero_deposit'], 'pulse_groups': groups,
            'acquisition_energy_keV': groups[0]['acquisition']['acquisition_energy_keV'] if len(groups) == 1 else None,
            'selection': {'valid': bool(groups) and not reasons, 'reasons': reasons}})
    require(not results, 'Acquisition output contains nonoriginal groups.')
    return records


def counts(records):
    return {'primaries': len(records), 'zero_deposit_primaries': sum(r['zero_deposit'] for r in records),
        'pulse_groups': sum(len(r['pulse_groups']) for r in records),
        'acquired_groups': sum(g['acquisition']['trace'] is not None for r in records for g in r['pulse_groups']),
        'selected_groups': sum(g['acquisition']['selection']['valid'] for r in records for g in r['pulse_groups'])}


def csv_bytes(records):
    stream = io.StringIO(newline=''); writer = csv.DictWriter(stream, fieldnames=CSV_COLUMNS, lineterminator='\n'); writer.writeheader()
    for record in records:
        writer.writerow({'global_initial_id': record['global_initial_id'], 'zero_deposit': json.dumps(record['zero_deposit']),
            'acquisition_energy_keV': encoded(record['acquisition_energy_keV']).decode().strip(), 'selection_valid': json.dumps(record['selection']['valid']),
            'record_json': encoded(record).decode().rstrip('\n')})
    return stream.getvalue().encode('utf-8')


def default_bundle_dir(root, config_sha256):
    require(type(config_sha256) is str and re.fullmatch('[0-9a-f]{64}', config_sha256), 'Invalid configuration SHA256.')
    return safe_path(root, '.local/waveform-acquisition/'+config_sha256+'/bundle')


def export_bundle(run_dir, out_dir=None, profile_path=None, *, root=None, julia_executable=None):
    directory = Path(run_dir).resolve(); root = Path(root or directory.parents[2]).resolve()
    require(directory == P.W.run_path(directory.name, root).resolve(), 'Input must be selected saved .local/runs root.')
    receipt = read_json(directory/'run.json'); config_sha = receipt['configuration_sha256']
    source_path, source, source_pins = source_bundle(root, config_sha)
    require(source['provenance']['run_ref'] == directory.relative_to(root).as_posix(), 'PSD1 belongs to another original saved run.')
    out = Path(out_dir or default_bundle_dir(root, config_sha)).absolute()
    require(out.is_relative_to(root/'.local') and not out.is_relative_to(directory) and not out.is_relative_to(source_path), 'Acquisition output must stay under project .local outside original science/PSD1.')
    out = safe_path(root, out.relative_to(root).as_posix()); require(not out.exists(), 'Acquisition output exists; preserve it and use a fresh derivative root.')
    profile_path = Path(profile_path or DEFAULT_PROFILE); profile_bytes = profile_path.read_bytes(); profile = validate_profile(P.W.decode_json(profile_bytes.decode('utf-8')))
    source_refs = {ref: stamp(safe_path(root, ref)) for ref in SOURCE_REFS}; input_pins = source['provenance']['input_artifacts']
    request = build_request(source, root, profile)
    out.mkdir(parents=True, exist_ok=False)
    try:
        numerical, execution = run_numerical(request, out, root, julia_executable)
        numerical_equal(numerical['profile'], profile); records = compact_records(source, numerical, profile)
        schema = encoded(DEFINITIONS)
        provenance = {'run_ref': source['provenance']['run_ref'], 'source_features_ref': source_path.relative_to(root).as_posix(),
            'source_features_manifest_sha256': source_pins['manifest.json']['sha256'], 'source_features_artifacts': source_pins,
            'source_profile_sha256': source['provenance']['profile_sha256'], 'input_artifacts': input_pins, 'extractor_sources': source_refs,
            'profile_sha256': hashlib.sha256(profile_bytes).hexdigest(), 'schema_template_sha256': hashlib.sha256(schema).hexdigest(),
            'python_version': platform.python_version(), 'execution': execution}
        data = {'kind': KIND, 'schema_version': 1, 'configuration_sha256': config_sha, 'profile': profile, 'counts': counts(records),
            'calibrations': numerical['calibrations'], 'records': records, 'provenance': provenance}
        require(source_refs == {ref: stamp(safe_path(root, ref)) for ref in SOURCE_REFS}, 'Acquisition source changed during export; preserve derivative and retry only after source freeze.')
        require(source_pins == {name: stamp(source_path/name) for name in source_pins} and input_pins == {ref: stamp(safe_path(root, ref)) for ref in input_pins}, 'Original saved input/PSD1 changed during export.')
        require(profile_path.read_bytes() == profile_bytes, 'Acquisition profile changed during export.')
        blobs = {'acquisition.json': encoded(data), 'acquisition.csv': csv_bytes(records), 'profile.json': profile_bytes, 'schema.json': schema, 'execution.json': encoded(execution)}
        manifest = {'kind': KIND, 'schema_version': 1, 'status': 'complete', 'configuration_sha256': config_sha, 'counts': data['counts'],
            **{k: provenance[k] for k in ('run_ref', 'source_features_ref', 'source_features_manifest_sha256', 'source_features_artifacts', 'source_profile_sha256', 'input_artifacts', 'extractor_sources', 'profile_sha256', 'schema_template_sha256')},
            'artifacts': {name: {'sha256': hashlib.sha256(blob).hexdigest(), 'bytes': len(blob)} for name, blob in blobs.items()},
            'numerical_artifacts': {name: stamp(out/name) for name in ('request.json', 'numerical.json', 'julia.log')}}
        for name, blob in blobs.items():
            with (out/name).open('xb') as stream: stream.write(blob)
        with (out/'manifest.json').open('xb') as stream: stream.write(encoded(manifest))
        with (out/'COMPLETE.json').open('xb') as stream: stream.write(encoded({'kind': KIND, 'schema_version': 1, 'status': 'complete', 'configuration_sha256': config_sha, 'manifest_sha256': sha(out/'manifest.json')}))
        load_bundle(out, config_sha, root=root)
        return manifest
    except BaseException as error:
        if not (out/'FAILED.json').exists():
            (out/'FAILED.json').write_bytes(encoded({'kind': KIND, 'status': 'failed', 'exception': type(error).__name__, 'message': str(error)}))
        raise


def load_bundle(bundle_dir, expected_config_sha256=None, *, root=None, verify_inputs=True):
    """Strict saved-only reader. Original PSD1 is always checked and joined.

    verify_inputs=False is retained for API symmetry; it never disables PSD1/raw
    verification because deliberate rehashes must not certify altered originals.
    """
    root = Path(root or P.W.ROOT).resolve(); directory = Path(bundle_dir).absolute()
    require(directory.is_relative_to(root/'.local'), 'Acquisition bundle must stay under project .local.')
    directory = safe_path(root, directory.relative_to(root).as_posix())
    complete = read_json(directory/'COMPLETE.json'); manifest = read_json(directory/'manifest.json')
    require(complete.get('kind') == manifest.get('kind') == KIND and complete.get('status') == manifest.get('status') == 'complete'
        and type(complete.get('schema_version')) is int and complete['schema_version'] == manifest.get('schema_version') == 1
        and complete.get('manifest_sha256') == sha(directory/'manifest.json') and complete.get('configuration_sha256') == manifest.get('configuration_sha256'), 'Acquisition completion/manifest identity changed.')
    config_sha = manifest['configuration_sha256']
    if expected_config_sha256 is not None: require(config_sha == expected_config_sha256, 'Acquisition belongs to another selected configuration.')
    require(set(manifest['artifacts']) == {'acquisition.json', 'acquisition.csv', 'profile.json', 'schema.json', 'execution.json'}
        and set(manifest['numerical_artifacts']) == {'request.json', 'numerical.json', 'julia.log'}, 'Acquisition artifact census changed.')
    for name, pin in {**manifest['artifacts'], **manifest['numerical_artifacts']}.items(): require(stamp(directory/name) == pin, 'Acquisition artifact bytes changed: '+name)
    require((directory/'schema.json').read_bytes() == encoded(DEFINITIONS) and manifest['schema_template_sha256'] == sha(directory/'schema.json'), 'Acquisition required schema/template changed.')
    profile = validate_profile(read_json(directory/'profile.json')); require(manifest['profile_sha256'] == sha(directory/'profile.json'), 'Acquisition profile binding changed.')
    require(set(manifest['extractor_sources']) == set(SOURCE_REFS), 'Acquisition source provenance incomplete.')
    for ref, pin in manifest['extractor_sources'].items(): require(stamp(safe_path(root, ref)) == pin, 'Current acquisition source differs from export: '+ref)
    source_path, source, source_pins = source_bundle(root, config_sha)
    require(manifest['source_features_ref'] == source_path.relative_to(root).as_posix() and manifest['source_features_artifacts'] == source_pins
        and manifest['source_features_manifest_sha256'] == source_pins['manifest.json']['sha256'] and manifest['source_profile_sha256'] == source['provenance']['profile_sha256']
        and manifest['run_ref'] == source['provenance']['run_ref'] and manifest['input_artifacts'] == source['provenance']['input_artifacts'], 'Original PSD1/run/profile/raw binding changed.')
    data = read_json(directory/'acquisition.json'); provenance = data['provenance']
    require(set(data) == {'kind', 'schema_version', 'configuration_sha256', 'profile', 'counts', 'calibrations', 'records', 'provenance'}
        and (directory/'acquisition.json').read_bytes() == encoded(data), 'Acquisition required schema/serialization changed.')
    require(data.get('kind') == KIND and type(data.get('schema_version')) is int and data['schema_version'] == 1 and data['configuration_sha256'] == config_sha
        and data['profile'] == profile and data['counts'] == manifest['counts'], 'Acquisition required dataset fields changed.')
    for key in ('run_ref', 'source_features_ref', 'source_features_manifest_sha256', 'source_features_artifacts', 'source_profile_sha256', 'input_artifacts', 'extractor_sources', 'profile_sha256', 'schema_template_sha256'):
        require(provenance.get(key) == manifest.get(key), 'Acquisition provenance binding changed: '+key)
    request = build_request(source, root, profile); require(read_json(directory/'request.json') == request, 'Numerical request differs from original full native inputs/settings.')
    numerical = read_json(directory/'numerical.json'); execution = read_json(directory/'execution.json')
    require(set(numerical) == {'kind', 'schema_version', 'profile', 'calibrations', 'groups', 'software'} and provenance['execution'] == execution
        and numerical['profile'] == profile and numerical['kind'] == KIND and numerical['schema_version'] == 1, 'Acquisition numerical/execution identity changed.')
    software = execution['software']; original_env = source['provenance']['response_summaries'][0].get('readout_environment', {})
    require(numerical['software'] == software and software['julia_version'].startswith('1.13.') and software['json_version'] == '1.9.0'
        and software['julia_threads'] == software['blas_threads'] == 1 and software['project_sha256'] == sha(root/'simulation/Project.toml')
        and software['manifest_sha256'] == sha(root/'simulation/Manifest.toml') and software['frontend_source_sha256'] == sha(root/'simulation/readout.jl')
        and software['acquisition_source_sha256'] == sha(root/'simulation/waveform_acquisition.jl'), 'Pinned acquisition software/environment changed.')
    if original_env: require(software['json_source_sha256'] == original_env['json_source_sha256'], 'Original/new JSON runtime source differs.')
    require(execution['exit_code'] == 0 and all(execution[k] == 0 for k in ('detector_calls', 'transport_calls', 'field_calls', 'native_drift_calls'))
        and execution['calibration_calls'] == len(request['batches']) and execution['frontend_calls'] == len(numerical['groups'])
        and execution['child_environment'] == {'JULIA_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1', 'JULIA_PKG_OFFLINE': 'true'}
        and execution['request_sha256'] == sha(directory/'request.json') and execution['numerical_sha256'] == sha(directory/'numerical.json')
        and execution['log_sha256'] == sha(directory/'julia.log'), 'Acquisition execution/call/hash contract changed.')
    require(data['calibrations'] == numerical['calibrations'] and len(data['calibrations']) == len(request['batches']), 'Acquisition calibration census changed.')
    group_results = {(g['global_initial_id'], g['group_id']): g['acquisition'] for g in numerical['groups']}
    for batch, cal in zip(request['batches'], data['calibrations']):
        require(set(cal) == {'batch_index', 'frontend_config', 'original_frontend_profile', 'ionisation_energy_eV', 'time_step_ns', 'calibration'}
            and {k: cal[k] for k in ('batch_index', 'frontend_config', 'original_frontend_profile', 'ionisation_energy_eV')} == {k: batch[k] for k in ('batch_index', 'frontend_config', 'original_frontend_profile', 'ionisation_energy_eV')}
            and cal['time_step_ns'] == batch['native_time_step_ns'], 'Independent calibration frontend/settings changed.')
        expected_cal = reference_calibration(batch['frontend_config'], batch['ionisation_energy_eV'], batch['native_time_step_ns'], profile)
        numerical_equal(cal['calibration'], expected_cal, 'calibration')
        for g in batch['groups']:
            original = P.get_record(source, g['global_initial_id'], g['group_id'])
            require((g['global_initial_id'], g['group_id']) in group_results, 'Acquisition original group lost.')
            numerical_equal(group_results[(g['global_initial_id'], g['group_id'])], reference_acquire(original, batch['frontend_config'], batch['ionisation_energy_eV'], profile, cal['calibration']), 'group')
    expected_records = compact_records(source, numerical, profile)
    require(data['records'] == expected_records and counts(expected_records) == manifest['counts'], 'Acquisition raw identities/census/flags/selection changed.')
    require((directory/'acquisition.csv').read_bytes() == csv_bytes(expected_records), 'Acquisition CSV differs from full-precision JSON records.')
    # Enrich only the returned view. Saved compact records remain bound joins.
    joined = copy.deepcopy(source['records'])
    for original, derived in zip(joined, expected_records):
        original['acquisition_energy_keV'] = derived['acquisition_energy_keV']; original['acquisition_selection'] = derived['selection']
        for old_group, new_group in zip(original['pulse_groups'], derived['pulse_groups']): old_group['acquisition'] = new_group['acquisition']
    data['records'] = joined
    return data


def get_record(bundle, primary_id, group_id=None):
    return P.get_record(bundle, primary_id, group_id)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--run', required=True, type=Path)
    parser.add_argument('--output', type=Path); parser.add_argument('--profile', type=Path); parser.add_argument('--julia', type=Path)
    args = parser.parse_args(argv)
    try:
        result = export_bundle(args.run, args.output, args.profile, julia_executable=args.julia)
        print(json.dumps({'kind': KIND, 'status': result['status'], 'configuration_sha256': result['configuration_sha256'], 'counts': result['counts']}, sort_keys=True)); return 0
    except (ControlError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr); return 1


if __name__ == '__main__':
    raise SystemExit(main())
