"""Replay two saved GeGI source chunks on a shared nominal acquisition clock."""

import argparse
from collections import Counter
import json
import math
import os
from pathlib import Path
import platform
import tempfile

import numpy as np

import gegi_digital_readout as digital
import gegi_digital_pairs as digital_pairs
import gegi_event_energy as event_energy
from gegi_event_store import encoded, sha
import gegi_exposure_stream as stream
import gegi_pulse_stream
import gegi_source_library as library
import gegi_substrip as substrip


KIND = 'gegi_dual_source_acquisition_v1'
DEFAULT_ACTIVITY_BQ = 37_000
DEFAULT_LIVE_TIME_S = .25
DEFAULT_SEED = 20261118
SEED_LIMIT = 1 << 64
REPORT_NAME = 'dual-source-acquisition.json'
PHASE_NS = 0
SAMPLE_PERIOD_NS = stream.SAMPLE_PERIOD_NS
PRE_NS, POST_NS = 6000, 4000
NATIVE_DRIFT_CAP_NS = 1000
MAX_UNSEEN_LSB = .25
BIN_STEP_KEV, BIN_STOP_KEV = 20, 3000


def _seed(value, label):
    if type(value) is not int or not 0 <= value < SEED_LIMIT:
        raise ValueError(f'{label} must be a nonnegative integer smaller than 2**64')
    return value


def _positive_input(value, label, *, allow_zero=False):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or (not allow_zero and value == 0):
        condition = 'nonnegative' if allow_zero else 'positive'
        raise ValueError(f'{label} must be a finite {condition} number')
    return value


def _report_path(output):
    path = Path(output).expanduser().resolve()
    if path.is_dir() or not path.exists() and not path.suffix:
        return path / REPORT_NAME
    if path.suffix.lower() != '.json':
        raise ValueError('Choose a .json report file or a directory')
    return path


def _publish(report, path):
    """Publish a fully written report without replacing a previous receipt."""
    data = encoded(report) + b'\n'
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f'.{path.stem}-', suffix='.tmp', delete=False) as out:
            temporary = Path(out.name)
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        # A hard link publishes the complete file while exclusively claiming the final name.
        try:
            os.link(temporary, path)
        except FileExistsError:
            raise
        except OSError:
            # Some removable/network filesystems lack links. Preserve the same no-replace rule.
            with path.open('xb') as out:
                out.write(data)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _tail_bound_lsb(energy_keV, elapsed_ns):
    # For ideal Ramo weights in [0,1], |Q| <= 2 Edep. Integration by parts
    # bounds each pole by twice that excursion before free decay.
    gain = digital._TAU / (digital._TAU - digital._BANDWIDTH_TAU)
    return 4 * energy_keV * digital._VOLTS_PER_KEV * gain / digital._LSB_V * (
        math.exp(-elapsed_ns / digital._TAU) + math.exp(-elapsed_ns / digital._BANDWIDTH_TAU))


def _history_mask(missing, live_ns):
    """Conservatively qualify the sum of all unobserved feedback and bandwidth tails."""
    period = SAMPLE_PERIOD_NS
    intervals = [(0, PRE_NS), (live_ns - POST_NS, live_ns)]
    active = []
    missing = sorted(missing, key=lambda row: row['first_ge_deposit_ns'])
    for i, row in enumerate(missing):
        start = row['first_ge_deposit_ns']
        horizon = row['last_ge_deposit_ns'] + NATIVE_DRIFT_CAP_NS + 1
        active.append((horizon, row['positive_ge_energy_keV']))
        following = missing[i+1]['first_ge_deposit_ns'] if i + 1 < len(missing) else live_ns
        lo = math.ceil(max(end for end, _ in active) / period)
        hi = math.ceil(following / period)
        # Between onsets, after known nominal input horizons, the sum decreases.
        if lo < hi:
            while lo < hi:
                mid = (lo+hi)//2
                voltage = math.fsum(_tail_bound_lsb(energy, mid * period - end) for end, energy in active)
                if voltage > MAX_UNSEEN_LSB:
                    lo = mid + 1
                else:
                    hi = mid
            finish = min(following, lo * period)
        else:
            finish = following
        intervals.append((start - POST_NS, finish + PRE_NS))
    merged = []
    for start, stop in sorted(intervals):
        start = max(0, math.floor(start / period) * period)
        stop = min(live_ns, math.ceil(stop / period) * period)
        if start >= stop:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], stop)
        else:
            merged.append([start, stop])
    return merged


def _spectrum(values):
    edges = list(range(0, BIN_STOP_KEV + 1, BIN_STEP_KEV))
    counts = Counter(math.floor(value / BIN_STEP_KEV) for value in values)
    return {'bin_edges_keV': edges, 'lower_inclusive_upper_exclusive': True,
            'counts': [counts[i] for i in range(len(edges)-1)], 'entries': len(values),
            'underflow': sum(n for i, n in counts.items() if i < 0),
            'overflow': sum(n for i, n in counts.items() if i >= len(edges)-1),
            'exact_zero': sum(value == 0 for value in values)}


def _strip_neighbors(channels):
    neighbors = {}
    for family in ('X', 'Y'):
        ordered = sorted((row for row in channels if row['family'] == family and not row['guard']),
                         key=lambda row: row['strip_center_mm'])
        strips = [row['id'] for row in ordered]
        for i, cid in enumerate(strips):
            low = strips[i-1] if i > 0 else None
            high = strips[i+1] if i+1 < len(strips) else None
            neighbors[cid] = (low, high)
    return neighbors


def _fast_neighbor(cid, channels):
    if cid is None:
        return None
    channel = channels.get(cid, {})
    flags = [flag for flag in channel.get('flags', []) if flag.startswith('fast_')]
    return {'contact_id': cid, 'fast_keV_equiv': None if flags else channel.get('fast_signal_keV_equiv'),
            'flags': flags}


def _collector_features(cid, channels, neighbors):
    low, high = (_fast_neighbor(neighbor, channels) for neighbor in neighbors[cid])
    return {'contact_id': cid, 'slow_energy_keV': channels[cid]['slow_energy_keV'],
            'preamp_cfd50_ns': channels[cid].get('preamp_cfd50_ns'), 'low': low, 'high': high}


def _single_pixel_features(pulse, neighbors):
    channels = {row['contact_id']: row for row in pulse['channels']}
    axes = {}
    for axis, cid in zip(('x', 'y'), pulse['contact_ids'], strict=True):
        face = _collector_features(cid, channels, neighbors)
        low, high = face['low'], face['high']
        ratio = None
        if low is not None and high is not None:
            fast_low, fast_high = low['fast_keV_equiv'], high['fast_keV_equiv']
            if fast_low is not None and fast_high is not None:
                ratio = (fast_low - fast_high) / pulse['slow_energy_keV']
        axes[axis] = dict(face, fast_ratio=ratio)
    return axes


def position_field_identity(calibration, source_metadata):
    reference = {key: calibration[key] for key in ('model_sha256', 'field_cache_sha256', 'field_precision_bits')}
    return reference if all(all(src.get(k) == v for k, v in reference.items()) for src in source_metadata) else None


def _continuous_position(pulse, calibration, geometry, field_identity, family_transfer=None):
    energy = pulse['slow_energy_keV']
    if not field_identity:
        return {'status': 'unconfirmed_field', 'energy_scope': 'not_applicable'}
    pair = pulse['contact_ids']
    if list(pair) in calibration['sampled_contact_pairs']:
        estimate = substrip.infer_position(calibration, *pair, pulse, geometry,
                                           source_identity=field_identity, mode='cfd_conditioned')
        result = dict(method='direct_strip_calibration', tested_energies_keV=[250, 500, 662])
    else:
        evidence = substrip._family_transfer_evidence(tuple(pair))
        if family_transfer is None or evidence is None:
            return {'status': 'uncalibrated_pixel', 'energy_scope': 'not_applicable'}
        estimate = substrip.infer_family_transfer(calibration, family_transfer, *pair, pulse, geometry,
                                                 source_identity=field_identity, single_pixel_energy_keV=energy)
        result = dict(method='family_template_transfer', tested_energies_keV=evidence['tested_injection_energies_keV'],
                      transfer_status=estimate['transfer_status'], validation=evidence['scope'])
    energies = result['tested_energies_keV']
    result['energy_scope'] = 'within_tested_range' if energies[0] <= energy <= energies[-1] else 'outside_tested_range'
    axes = {}
    for axis, key in (('x', 'x'), ('y', 'y'), ('z', 'depth')):
        measured = estimate[key]
        axes[axis] = {'status': measured['status'], 'position_mm': measured['position_mm']}
        if axis != 'z':
            axes[axis]['slot'] = measured['slot']
    values = [axes[axis]['position_mm'] for axis in ('x', 'y', 'z')]
    full = None not in values
    status = 'estimated' if full else 'partial' if any(v is not None for v in values) else 'unavailable'
    return dict(result, status=status, axes=axes, position_mm=values if full else None)


def _trigger_card(pulse, neighbors, *, calibration=None, geometry=None, field_identity=None, family_transfer=None):
    measured = event_energy.estimate_event_energy(pulse)
    single = pulse['slow_energy_keV']
    multiple = measured['x_count'] > 1 or measured['y_count'] > 1
    added = measured['energy_keV'] if single is None and multiple else None
    card = {'trigger_time_ns': pulse['trigger_time_ns'], 'rise_end_ns': pulse['rise_end_ns'],
            'single_pixel_energy_keV': single, 'additional_multi_strip_energy_keV': added,
            'single_pixel_features': _single_pixel_features(pulse, neighbors) if measured['retains_legacy_single'] else None,
            'energy_keV': single if single is not None else added,
            'x_sum_keV': measured['x_sum_keV'], 'y_sum_keV': measured['y_sum_keV'],
            'x_collecting_strips': measured['x_contact_ids'], 'y_collecting_strips': measured['y_contact_ids'],
            'guard_contact_ids': measured['guard_contact_ids'], 'flags': pulse['flags'],
            'event_energy_flags': measured['flags']}
    if calibration is not None and measured['retains_legacy_single']:
        card['nominal_position'] = _continuous_position(pulse, calibration, geometry, field_identity, family_transfer)
    if geometry is not None and added is not None and measured['x_count'] == measured['y_count'] == 2:
        xs, ys = measured['x_contact_ids'], measured['y_contact_ids']
        channels = {r['contact_id']: r for r in pulse['channels']}
        hits = {cid: channels[cid]['slow_energy_keV'] for cid in xs + ys}
        pairings = list(digital_pairs.energy_pairings(xs, ys, hits))
        for pairing in pairings:
            pairing['compton_orders'] = digital_pairs.compton_orders(pairing['sites']) if pairing['energy_compatible'] else []
        flags = digital_pairs._neighborhood_flags(xs, ys, geometry)
        card['two_strip_pairings'] = dict(compatible_pairing_count=sum(p['energy_compatible'] for p in pairings),
                                          pairings=pairings, flags=flags,
                                          collectors=[_collector_features(cid, channels, neighbors) for cid in xs + ys])
    return card


def _relative_input(path, destination):
    try:
        return Path(os.path.relpath(path, destination)).as_posix()
    except ValueError:  # Different Windows volumes.
        return None


def _portable_sources(libraries, schedule, activities, output):
    result = []
    for saved, key, activity in zip(libraries, schedule['source_keys'], activities, strict=True):
        source = schedule['sources'][key]
        result.append({
            'key': key, 'activity_bq': activity, 'original': saved.metadata,
            'input_directory': {'absolute': str(saved.directory), 'relative_to_report_directory':
                                _relative_input(saved.directory, output.parent)},
            'scheduled_parent_seed': source['clock']['seed_uint64'],
            'clock_layers': source['clock'].get('clock_layers', 1),
            'counts': source['counts'],
        })
    return result


def _unknown_card(row, energy, status, digest=None):
    return {key: row[key] for key in ('source', 'occurrence_id', 'raw_event_id', 'campaign_initial_id',
                                      'group_id', 'first_ge_deposit_ns', 'last_ge_deposit_ns')} | {
        'positive_ge_energy_keV': energy, 'native_status': status, 'native_metadata_sha256': digest,
    }


def _native_inputs(libraries, schedule):
    by_key = dict(zip(schedule['source_keys'], libraries, strict=True))
    cache_by_key = {key: {} for key in by_key}
    components, missing = [], []
    complete_by_key = Counter()
    for row in schedule['eligible_groups']:
        key = row['source']
        saved = by_key[key]
        native, status, digest = library.read_native(saved, row, cache_by_key[key])
        if native is not None:
            components.append((native, row['first_ge_deposit_ns'], 1.))
            complete_by_key[key] += 1
        else:
            missing.append(_unknown_card(row, row['truth_edep_keV'], status, digest))
    return components, missing, complete_by_key


def _partial_deposits(schedule):
    """An in-window onset with deposits extending past the boundary carries unknown current."""
    return [_unknown_card(row, row['truth_edep_keV'], 'deposits_extend_past_exposure')
            for row in schedule['censored_groups']]


def _implementation_hashes():
    paths = {'digital_readout_sha256': digital.__file__, 'estimator_sha256': event_energy.__file__,
             'runner_sha256': __file__, 'library_sha256': library.__file__,
             'adc_stream_sha256': stream.__file__, 'pulse_stream_sha256': gegi_pulse_stream.__file__,
             'position_estimator_sha256': substrip.__file__, 'pairing_sha256': digital_pairs.__file__}
    return {label: sha(Path(path).read_bytes()) for label, path in paths.items()}


def run(source_chunks, activities_bq, live_time_s, seed, output, *, noise_seed=None, trigger_profile='standard'):
    """Read two verified source chunks and write a portable result JSON file."""
    profile = gegi_pulse_stream.trigger_profile_definition(trigger_profile)
    source_chunks, activities = tuple(source_chunks), tuple(activities_bq)
    if len(source_chunks) != 2 or len(activities) != 2:
        raise ValueError('Provide two source chunks and their two activities')
    activities = tuple(_positive_input(v, 'Activity in Bq', allow_zero=True) for v in activities)
    live_ns = _positive_input(live_time_s, 'Live time in seconds') * 1e9
    _positive_input(live_ns, 'Live time in nanoseconds')
    seed = _seed(seed, 'Clock seed')
    noise_seed = (seed + 100000000) % SEED_LIMIT if noise_seed is None else _seed(noise_seed, 'ADC noise seed')
    output = _report_path(output)
    if output.exists():
        raise FileExistsError(output)
    implementation = _implementation_hashes()
    libraries = tuple(library.load_source_library(path) for path in source_chunks)
    calibration = substrip.load_calibration()
    family_transfer = substrip.prepare_family_transfer(calibration, libraries[0].channels)
    field_identity = position_field_identity(calibration, [src.metadata for src in libraries])
    if any(output.is_relative_to(saved.directory) for saved in libraries):
        raise ValueError('Write the result outside the two saved source chunks')
    scheduling = library.schedule_sources(*libraries, activities_bq=activities, duration_ns=live_ns,
                                          seed=seed, include_prehistory=True)
    sources = _portable_sources(libraries, scheduling, activities, output)
    components, missing, complete_by_key = _native_inputs(libraries, scheduling)
    partial = _partial_deposits(scheduling)
    mask = _history_mask(missing + partial, live_ns)
    masked_ns = math.fsum(hi-lo for lo, hi in mask)
    qualified_ns = live_ns - masked_ns
    total_samples = math.ceil(live_ns / SAMPLE_PERIOD_NS)
    qualified_samples = total_samples - sum(math.ceil(hi/SAMPLE_PERIOD_NS)-math.ceil(lo/SAMPLE_PERIOD_NS)
                                            for lo, hi in mask)
    present = qualified_samples > 0
    readout = None
    occurred = None
    if present:
        adc = stream.ADCExposure(components, live_time_ns=live_ns, phase_ns=PHASE_NS, noise_seed=noise_seed)
        readout = stream.reconstruct_exposure(adc, block_samples=stream.DEFAULT_BLOCK_SAMPLES,
                                              trigger_profile=trigger_profile)
        neighbors = _strip_neighbors(libraries[0].channels)
        occurred = [_trigger_card(pulse, neighbors, calibration=calibration, geometry=libraries[0].channels,
                                  field_identity=field_identity, family_transfer=family_transfer) for pulse in readout['events']
                    if 0 <= pulse['trigger_time_ns'] < live_ns
                    and not any(a <= pulse['rise_end_ns'] and b > pulse['trigger_time_ns'] for a, b in mask)]
    qualified_set = occurred if present else []
    single = [t['single_pixel_energy_keV'] for t in qualified_set if t['single_pixel_energy_keV'] is not None]
    additional = [t['additional_multi_strip_energy_keV'] for t in qualified_set if t['additional_multi_strip_energy_keV'] is not None]
    missing_ids = {(row['source'], row['occurrence_id'], row['group_id']) for row in missing}
    history_by_key = Counter(row['source'] for row in scheduling['eligible_groups']
                             if (row['source'], row['occurrence_id'], row['group_id']) not in missing_ids
                             and any(lo <= row['first_ge_deposit_ns'] < hi for lo, hi in mask))
    for source in sources:
        key = source['key']
        source['native_availability'] = {'complete_groups': complete_by_key[key],
                                         'unavailable_groups': sum(row['source'] == key for row in missing),
                                         'prehistory_unqualified_groups': history_by_key[key]}
    counts = {
        'initial_parents_in_live_time': sum(s['counts']['parents'] for s in sources),
        'deposit_groups': len(scheduling['eligible_groups'])+len(partial),
        'complete_deposit_groups': len(scheduling['eligible_groups']),
        'right_censored_deposit_groups': len(partial),
        'native_unavailable_groups': len(missing),
        'prehistory_unqualified_groups': sum(history_by_key.values()),
        'qualified_triggers': len(qualified_set) if present else None,
        'single_pixel_energies': len(single) if present else None,
        'additional_multi_strip_energies': len(additional) if present else None,
        'qualified_energies': len(single)+len(additional) if present else None,
        'triggers_without_energy': len(qualified_set)-len(single)-len(additional) if present else None,
    }
    spectra = {'single_pixel': _spectrum(single), 'additional_multi_strip': _spectrum(additional),
               'combined': _spectrum(single+additional)} if present else None
    report = {
        'kind': KIND, 'status': 'completed',
        'design': {'live_time_s': live_time_s, 'clock_seed': seed, 'noise_seed': noise_seed,
                   'adc_phase_ns': PHASE_NS, 'sample_period_ns': SAMPLE_PERIOD_NS,
                   'trigger_profile': profile,
                   'adc_noise_rms_v': digital._PROFILE['optional_noise_rms_V'],
                   'clock_scope': 'Independent homogeneous parent clocks on the empirical saved source libraries. '
                                  'Delayed groups from earlier parents can enter the live interval. Reset nominal '
                                  'electronics and admit Ge groups whose onset is in the interval.',
                   'history_scope': 'A missing or incomplete native pulse is unknown. The analysis masks the '
                                    'unknown nominal charge interval and its exponentially decaying analog bound, '
                                    'plus digital feature support. The nominal input cap is last Ge deposition '
                                    '+1000 ns +1 native bin. Qualification uses a summed 0.25 ADC LSB bound.',
                   'energy_scope': 'Emit at most one energy per ADC trigger. Retain the legacy pixel energy or, '
                                   'when two non-guard face sums close, a multi-strip trigger total. Sources '
                                   'and photon/site identities are unassigned for all measured triggers.',
                   'generalization_scope': 'Rates describe only qualified ADC time. Missing history prevents '
                                           'extending observed counts to a whole-exposure efficiency.',
                   'event_energy': event_energy.DEFINITION,
                   'two_strip_pairings': {'selection': 'Qualified multi-strip total with two collecting strips on each face.',
                                          'order_scope': 'Energy constraints for one fully absorbed photon. A trigger may contain more than one photon.'},
                   'nominal_position': {'calibration_sha256': calibration['calibration_sha256'],
                                        'matching_fields': field_identity is not None, 'mode': 'cfd_conditioned',
                                        'sampled_contact_pairs': calibration['sampled_contact_pairs'],
                                        'channel_geometry': [{key: channel[key] for key in
                                                              ('id', 'family', 'guard', 'strip_center_mm')}
                                                             for channel in libraries[0].channels],
                                        'tested_energies_keV': [250, 500, 662],
                                        'lateral_transfer': substrip.FAMILY_TRANSFER_KIND,
                                        'ratio_definition': calibration['ratio_definition'],
                                        'coordinate_unit': 'mm',
                                        'scope': 'Point estimate for a measured single pixel. Multiple deposits can share a pixel.'},
                   'single_pixel_features': {
                       'fast_area_gate_ns': digital._PROFILE['fast_area_gate_ns'],
                       'fast_unit': 'keV-equivalent',
                       'fast_signal': 'Signed area relative to the recent quiet fast level.',
                       'neighbor_order': 'Lower and higher strip-center coordinates on the same face.',
                       'ratio_definition': '(low.fast_keV_equiv - high.fast_keV_equiv) / single_pixel_energy_keV',
                   }},
        'exposure': {'clock_live_time_ns': live_ns, 'qualified_adc_live_time_ns': qualified_ns,
                     'masked_live_time_ns': masked_ns, 'total_live_adc_samples': total_samples,
                     'qualified_live_adc_samples': qualified_samples, 'excluded_intervals_ns': mask,
                     'qualified_trigger_rate_per_s': len(qualified_set)*1e9/qualified_ns if present else None,
                     'qualified_energy_rate_per_s': (len(single)+len(additional))*1e9/qualified_ns if present else None,
                     'absolute_whole_exposure_efficiency': None},
        'sources': sources, 'counts': counts, 'spectra': spectra,
        'unknown_groups': missing + partial, 'triggers': occurred,
        'receipt': {'python': platform.python_version(), 'numpy': np.__version__,
                    'digital_profile_sha256': digital.PROFILE_SHA256, 'digital_timing_sha256': digital.TIMING_SHA256,
                    'trigger_profile': profile,
                    **implementation,
                    'known_component_adc_sha256': None if readout is None else readout['adc_sha256'],
                    'observed_result_sha256': sha(encoded({'counts': counts, 'spectra': spectra, 'triggers': occurred,
                                                            'mask': mask})),
                    'new_transport_calls': 0, 'new_drift_calls': 0},
    }
    if implementation != _implementation_hashes():
        raise RuntimeError('Replay source changed during acquisition')
    _publish(report, output)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-a', type=Path, required=True, help='First saved GeGI source chunk directory')
    parser.add_argument('--source-b', type=Path, required=True, help='Second saved GeGI source chunk directory')
    parser.add_argument('--activity-a-bq', type=float, default=DEFAULT_ACTIVITY_BQ)
    parser.add_argument('--activity-b-bq', type=float, default=DEFAULT_ACTIVITY_BQ)
    parser.add_argument('--live-time-s', type=float, default=DEFAULT_LIVE_TIME_S)
    parser.add_argument('--seed', type=int, default=DEFAULT_SEED)
    parser.add_argument('--noise-seed', type=int, help='Default: (clock seed + 100000000) modulo 2**64')
    parser.add_argument('--trigger-profile', choices=gegi_pulse_stream.TRIGGER_PROFILES, default='standard',
                        help='Face coincidence threshold per 20 ns sample: standard 5 keV, low-energy 4 keV')
    parser.add_argument('--output', type=Path, required=True, help='New JSON file or directory')
    args = parser.parse_args()
    try:
        result = run((args.source_a, args.source_b), (args.activity_a_bq, args.activity_b_bq),
                     args.live_time_s, args.seed, args.output, noise_seed=args.noise_seed,
                     trigger_profile=args.trigger_profile)
    except (OSError, ValueError) as error:
        parser.exit(2, f'Error: {error}\n')
    print(json.dumps({'output': str(_report_path(args.output)), 'counts': result['counts'],
                      'trigger_profile': result['design']['trigger_profile'],
                      'qualified_adc_live_time_ns': result['exposure']['qualified_adc_live_time_ns'],
                      'observed_result_sha256': result['receipt']['observed_result_sha256']}))


if __name__ == '__main__':
    main()
