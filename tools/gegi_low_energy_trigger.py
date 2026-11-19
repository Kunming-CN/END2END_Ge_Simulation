"""Compare one GeGI coincidence threshold using sealed ADC inputs and empty windows."""

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import platform
import time

import numpy as np
from scipy.optimize import linear_sum_assignment
from scipy.stats import chi2

import gegi_event_energy as energy
from gegi_event_energy_study import compare_card, prepare
from gegi_event_store import encoded, sha
import gegi_exposure_stream as adc
import gegi_pulse_stream as pulse
import gegi_source_exposure as exposure
from gegi_source_pileup import pulse_card


LOCAL = exposure.ROOT / '.local/gegi-low-energy-trigger'
DT_NS = adc.SAMPLE_PERIOD_NS
NOMINAL = pulse._TRIGGER_KEV
ALTERNATIVE = 4.0
REFERENCE_ADC = '9c799bc14d9782b70bd1093c412da3a1416e7cc2d15561aa6bd1e81e9e88dae5'
MAX_CONTROL_DELTA_KEV = 10.0
EMPTY_NS = 50_000_000
EMPTY_SEEDS = (2026112001, 2026112002, 2026112003, 2026112004)
REQUIRE = exposure.REQUIRE


def waveform_id(row):
    return row['source'], row['raw_event_id'], row['group_id']


def partition(row):
    # All occurrences and pulse groups from an original simulated parent stay together.
    digest = hashlib.sha256(encoded(('gegi-trigger-v1', *waveform_id(row)[:2]))).digest()
    return 'development' if int.from_bytes(digest[:8], 'big') % 3 == 0 else 'held_out'


def matched_controls(misses, detected):
    """Match different original parents within source, split and an energy caliper."""
    missed_parents = {waveform_id(row)[:2] for _, row in misses}
    pairs = {}
    for source in exposure.SOURCES:
        for subset in ('development', 'held_out'):
            left = [(i, row) for i, row in misses if row['source'] == source and partition(row) == subset]
            right = {}
            for i, row in detected:
                parent = waveform_id(row)[:2]
                if row['source'] == source and partition(row) == subset and parent not in missed_parents:
                    right.setdefault(parent, (i, row))
            right = list(right.values())
            if not left or not right:
                continue
            l_energy = np.array([row['truth_edep_keV'] for _, row in left])
            r_energy = np.array([row['truth_edep_keV'] for _, row in right])
            delta = np.abs(l_energy[:, None] - r_energy[None, :])
            # Withhold a match beyond the caliper. Prefer more valid pairs, then smaller differences.
            penalty = MAX_CONTROL_DELTA_KEV * (len(left) + 1)
            scores = np.where(delta <= MAX_CONTROL_DELTA_KEV, delta, penalty * 2)
            scores = np.column_stack((scores, np.full((len(left), len(left)), penalty)))
            for a, b in zip(*linear_sum_assignment(scores)):
                if b < len(right) and delta[a, b] <= MAX_CONTROL_DELTA_KEV:
                    pairs[left[a][0]] = right[b][0]
    return pairs


def register_changes(groups, start, change):
    """Keep the peak of the smaller signed face increment per nominal quiet group."""
    indices = np.flatnonzero(np.max(np.abs(change), axis=0) > pulse._QUIET_KEV)
    if not indices.size:
        return
    coincident = np.min(change, axis=0)
    for group in np.split(indices, np.flatnonzero(np.diff(indices) > pulse._QUIET_SAMPLES) + 1):
        begin, end = int(group[0]) + start - 1, int(group[-1]) + start
        peak = float(coincident[group[0]:group[-1]+1].max())
        if groups and begin + 1 - groups[-1][1] <= pulse._QUIET_SAMPLES:
            begin, _, prior_peak = groups.pop()
            peak = max(peak, prior_peak)
        groups.append((begin, end, peak))


def scan(acquisition, block_samples):
    """Compute the nominal 40 ns average's first difference from the shared ADC codes."""
    REQUIRE(pulse._FAST_SAMPLES == 2 and pulse._QUIET_KEV < ALTERNATIVE < NOMINAL,
            'Study requires the nominal two-sample fast filter and fixed threshold order')
    blocks = acquisition.blocks(block_samples)
    _, preamble = next(blocks)
    baseline = (preamble * pulse.D._LSB_V).mean(axis=1)
    face_baseline = np.array([baseline[face].sum() for face in pulse._FACES])[:, None]
    previous = adc._face_voltages(preamble[:, -pulse._FAST_SAMPLES:]) - face_baseline
    digest = hashlib.sha256(np.asarray(preamble.T, dtype='<i2', order='C').tobytes())
    groups = []
    for start, code in blocks:
        digest.update(np.asarray(code.T, dtype='<i2', order='C').tobytes())
        face = np.concatenate((previous, adc._face_voltages(code) - face_baseline), axis=1)
        previous = face[:, -pulse._FAST_SAMPLES:]
        increments = face[:, 1:] - adc._ALPHA * face[:, :-1]
        change = (increments[:, 1:] + increments[:, :-1]) / (pulse._FAST_SAMPLES * pulse._SLOW_GAIN)
        register_changes(groups, start, change)
    return baseline, groups, digest.hexdigest()


def reconstruct(acquisition, block_samples, baseline, peaks, threshold):
    """Use production feature gates and the existing persistent face-step threshold."""
    groups = [(start, end, peak >= threshold) for start, end, peak in peaks]
    contexts = adc._contexts(acquisition, groups)
    accepted, rejected = [], []
    if contexts:
        for event in adc._feature_contexts(acquisition, block_samples, groups, baseline, contexts):
            steps = event['face_step_keV']
            if steps is not None and min(steps) < energy.MIN_COLLECTED_KEV:
                rejected.append(event)
            else:
                accepted.append(event)
    return accepted, rejected


def qualified(events, live_ns, mask):
    return [event for event in events if 0 <= event['trigger_time_ns'] < live_ns
            and not any(a <= event['rise_end_ns'] and b > event['trigger_time_ns'] for a, b in mask)]


def associate(saved, events):
    rows = [dict(row, classification=row['classification'] if row['classification'] in
                 ('history_unqualified', 'native_unavailable') else 'awaiting_match') for row in saved['deposits']]
    triggers = [{**pulse_card(event), 'rise_end_ns': event['rise_end_ns'], 'association': 'unmatched'}
                for event in events]
    exposure.assign(rows, triggers, saved['exposure']['excluded_intervals_ns'])
    return rows, triggers


def energy_availability(events):
    return sum(energy.estimate_event_energy(event)['energy_keV'] is not None for event in events)


def evaluate_exposure(saved, components):
    design, report = saved['design'], saved['exposure']
    acquisition = adc.ADCExposure(components, live_time_ns=report['clock_live_time_ns'],
                                  phase_ns=design['adc_phase_ns'], noise_seed=design['noise_seed'])
    block = design['block_samples']
    baseline, peaks, digest = scan(acquisition, block)
    REQUIRE(digest == REFERENCE_ADC and acquisition.live_samples == report['total_live_adc_samples'],
            'ADC hash or sample count differs from the sealed exposure')
    results, cards = {}, {}
    for name, threshold in (('nominal', NOMINAL), ('alternative', ALTERNATIVE)):
        accepted, rejected = reconstruct(acquisition, block, baseline, peaks, threshold)
        observed = qualified(accepted, acquisition.live_time_ns, report['excluded_intervals_ns'])
        rows, triggers = associate(saved, observed)
        results[name] = rows, triggers, accepted, rejected
        cards[name] = {'deposits_by_class': dict(Counter(row['classification'] for row in rows)),
                       'triggers_by_association': dict(Counter(row['association'] for row in triggers)),
                       'qualified_triggers': len(observed), 'qualified_trigger_energies': energy_availability(observed)}
        if name == 'nominal':
            parity = [compare_card(old, new) for old, new in zip(saved['triggers'], observed, strict=True)]
            original = [row['classification'] for row in saved['deposits']]
            REQUIRE([row['classification'] for row in rows] == original
                    and all(row['association'] == old['association'] for row, old in zip(triggers, saved['triggers'])),
                    'Nominal replay changed frozen associations')
            cards[name]['baseline_max_delta_keV'] = max(parity)
    return results, cards, peaks, digest


def isolated(row, native, *, noise_seed=None):
    onset = row['first_ge_deposit_ns']
    zero = math.floor(onset / DT_NS) * DT_NS
    arrival = onset - zero
    end = math.floor((arrival + max(native.time_ns[-1], pulse.D._TIME_NS[-1])) / DT_NS) * DT_NS + DT_NS
    acquisition = adc.ADCExposure([(native, arrival, 1.)], live_time_ns=end, noise_seed=noise_seed)
    baseline, peaks, _ = scan(acquisition, adc.DEFAULT_BLOCK_SAMPLES)
    result = {'maximum_coincident_increment_keV_per_sample': max((peak for _, _, peak in peaks), default=None)}
    for name, threshold in (('nominal', NOMINAL), ('alternative', ALTERNATIVE)):
        events, rejected = reconstruct(acquisition, adc.DEFAULT_BLOCK_SAMPLES, baseline, peaks, threshold)
        if noise_seed is None and name == 'nominal':
            for old, new in zip(row['isolated_triggers'], events, strict=True):
                compare_card(old, new, absolute_offset=zero)
        result[name] = {'coincident_activities': sum(peak >= threshold for _, _, peak in peaks),
                        'persistent_step_rejections': len(rejected), 'triggers': len(events),
                        'qualified_energies': energy_availability(events)}
    return result


def associated_activities(row, peaks, phase_ns):
    onset = row['first_ge_deposit_ns']
    return [(start * DT_NS + phase_ns, peak) for start, end, peak in peaks
            if onset - exposure.PRE_NS <= start * DT_NS + phase_ns <= onset + exposure.SEARCH_END_NS + exposure.MATCH_NS
            and exposure.related(onset, row, {'trigger_time_ns': start * DT_NS + phase_ns,
                                               'rise_end_ns': end * DT_NS + phase_ns})]


def missed_reason(activities, accepted, rejected):
    starts = {start for start, peak in activities if peak >= NOMINAL}
    if not activities:
        return 'no_quiet_group_in_association_window'
    if not starts:
        return 'below_coincident_increment_threshold'
    if starts <= rejected:
        return 'persistent_face_step_rejected'
    if starts & accepted:
        return 'accepted_activity_unmatched_or_excluded'
    return 'unresolved_coincident_activity'


def case_replay(saved, cache, misses, pairs, results, peaks):
    lookup = saved['deposits']
    _, _, accepted, rejected = results['nominal']
    accepted = {event['trigger_time_ns'] for event in accepted}
    rejected = {event['trigger_time_ns'] for event in rejected}
    cases = []
    for missed, control in [(index, None) for index, _ in misses] + [(b, a) for a, b in pairs.items()]:
        row = lookup[missed]
        key = waveform_id(row)
        native, _, metadata_hash = cache[key]
        REQUIRE(native is not None and metadata_hash == row['metadata_sha256'], 'Selected native waveform changed')
        seed = int.from_bytes(hashlib.sha256(encoded(('gegi-trigger-noise-v1', *key, row['occurrence_id']))).digest()[:8], 'big')
        activities = associated_activities(row, peaks, saved['design']['adc_phase_ns'])
        cases.append({'deposit_index': missed, 'waveform_id': list(key), 'occurrence_id': row['occurrence_id'],
                      'partition': partition(row), 'campaign_initial_id': row['campaign_initial_id'],
                      'truth_edep_keV': row['truth_edep_keV'], 'metadata_sha256': metadata_hash,
                      'first_ge_deposit_ns': row['first_ge_deposit_ns'], 'classification': row['classification'],
                      'matched_deposit_index': pairs.get(missed) if control is None else control,
                      'nominal_miss_mechanism': missed_reason(activities, accepted, rejected) if control is None else None,
                      'nominal_max_continuous_coincident_increment_keV_per_sample': max((peak for _, peak in activities), default=None),
                      'continuous_alternative_classification': results['alternative'][0][missed]['classification'],
                      'isolated_noiseless': isolated(row, native), 'isolated_noise_seed': seed,
                      'isolated_nominal_noise': isolated(row, native, noise_seed=seed)})
    return cases


def upper_rate(count, seconds):
    return float(chi2.ppf(.95, 2 * (count + 1)) / (2 * seconds))


def empty_control():
    windows = []
    for phase_ns, seed in zip((0, 5, 10, 15), EMPTY_SEEDS, strict=True):
        acquisition = adc.ADCExposure([], live_time_ns=EMPTY_NS, phase_ns=phase_ns, noise_seed=seed)
        baseline, peaks, digest = scan(acquisition, adc.DEFAULT_BLOCK_SAMPLES)
        window = {'phase_ns': phase_ns, 'noise_seed': seed, 'adc_sha256': digest,
                  'live_samples': acquisition.live_samples, 'live_time_s': acquisition.live_samples * DT_NS / 1e9}
        for name, threshold in (('nominal', NOMINAL), ('alternative', ALTERNATIVE)):
            accepted, rejected = reconstruct(acquisition, adc.DEFAULT_BLOCK_SAMPLES, baseline, peaks, threshold)
            window[name] = {'coincident_activities': sum(peak >= threshold for _, _, peak in peaks),
                            'triggers': len(qualified(accepted, acquisition.live_time_ns, [])),
                            'persistent_step_rejections': len(rejected)}
        windows.append(window)
    seconds = sum(row['live_time_s'] for row in windows)
    total = {}
    for name in ('nominal', 'alternative'):
        count = sum(row[name]['triggers'] for row in windows)
        total[name] = {'triggers': count, 'observed_rate_per_s': count / seconds,
                       'poisson_one_sided_95_percent_upper_per_s': upper_rate(count, seconds)}
    return {'windows': windows, 'live_time_s': seconds, 'poisson_count_model': total}


def cohort_summary(rows, results):
    bounds = (0, 10, 20, 30, 35, 50, math.inf)
    output = {}
    for split in ('development', 'held_out'):
        cells = []
        for lo, hi in zip(bounds, bounds[1:]):
            indices = [i for i, row in enumerate(rows) if partition(row) == split and row['arrival_class'] == 'isolated'
                       and row['classification'] in ('missed', 'unique_matched') and lo <= row['truth_edep_keV'] < hi]
            cells.append({'deposited_energy_lower_inclusive_keV': lo,
                          'deposited_energy_upper_exclusive_keV': hi if math.isfinite(hi) else None,
                          'qualified_isolated_occurrences': len(indices),
                          'unique_original_waveforms': len({waveform_id(rows[i]) for i in indices}),
                          **{name + '_unique_matched': sum(results[name][0][i]['classification'] == 'unique_matched'
                                                           for i in indices) for name in ('nominal', 'alternative')}})
        output[split] = cells
    return output


def run():
    started = time.perf_counter()
    implementation = sha(Path(__file__).read_bytes())
    saved, components, cache, _, hashes = prepare()
    rows = saved['deposits']
    misses = [(i, row) for i, row in enumerate(rows) if row['classification'] == 'missed']
    REQUIRE(len(misses) == 45 and all(row['arrival_class'] == 'isolated' for _, row in misses),
            'Expected the sealed 45 isolated missed occurrences')
    detected = [(i, row) for i, row in enumerate(rows)
                if row['classification'] == 'unique_matched' and row['arrival_class'] == 'isolated']
    pairs = matched_controls(misses, detected)
    results, continuous, peaks, digest = evaluate_exposure(saved, components)
    cases = case_replay(saved, cache, misses, pairs, results, peaks)
    empty = empty_control()
    REQUIRE(implementation == sha(Path(__file__).read_bytes()), 'Study source changed during replay')
    return {'kind': 'gegi_saved_low_energy_trigger_study_v1', 'status': 'completed',
            'design': {'coincident_increment_keV_per_20_ns': {'nominal': NOMINAL, 'alternative': ALTERNATIVE},
                       'quiet_discriminator_keV_per_sample': pulse._QUIET_KEV,
                       'persistent_face_step_minimum_keV': energy.MIN_COLLECTED_KEV,
                       'sample_period_ns': DT_NS, 'fast_average_ns': pulse._FAST_SAMPLES * DT_NS,
                       'noise_rms_V': saved['design']['nominal_noise_rms_v'],
                       'threshold_scope': 'The fixed one-keV reduction tests marginal coincident rises while keeping the quiet criterion, all feature gates and calibration fixed.',
                       'held_out_scope': 'SHA-256 partition by original source and parent ID. Each partition includes all repeats of its original waveforms. The one alternative was fixed before new replay.',
                       'matched_control_scope': 'Within each source and partition, maximize one-to-one matches within 10 keV deposited energy, minimize absolute energy differences, exclude original missed parents and keep one occurrence per control parent.',
                       'continuous_scope': 'Reuse the sealed components, ADC clock, noise, exposure mask, and original association rules. Counts describe these empirical qualified windows.',
                       'isolated_scope': 'Use original fractional phase and unscaled verified native waveforms, with identical ADC samples across trigger thresholds and a fresh per-occurrence seed in the noisy condition.',
                       'empty_scope': 'Independent Gaussian ADC noise in four reset windows. The Poisson upper rate is conditional on this nominal noise model and sampled live time.',
                       'new_transport_calls': 0, 'new_drift_calls': 0, 'new_field_solves': 0},
            'continuous': {'clock_live_time_ns': saved['exposure']['clock_live_time_ns'],
                           'qualified_live_time_ns': saved['exposure']['qualified_adc_live_time_ns'],
                           'evaluated_deposit_occurrences': saved['summary'][0]['qualified_deposits'],
                           'adc_sha256': digest, 'counts': continuous,
                           'isolated_match_counts_by_energy_and_partition': cohort_summary(rows, results)},
            'missed_cases': {'original_miss_occurrences': len(misses), 'matched_control_occurrences': len(pairs),
                             'nominal_miss_mechanisms': dict(Counter(row['nominal_miss_mechanism'] for row in cases
                                                                    if row['nominal_miss_mechanism'] is not None)),
                             'rows': cases},
            'empty_control': empty, 'input_sha256': saved['input_sha256'] | hashes,
            'source_sha256': {**saved['source_sha256'], f'tools/{Path(__file__).name}': implementation,
                              'tools/gegi_event_energy.py': sha(Path(energy.__file__).read_bytes()),
                              'tools/gegi_event_energy_study.py': sha((exposure.ROOT / 'tools/gegi_event_energy_study.py').read_bytes())},
            'resources': {'wall_s': time.perf_counter() - started, 'python': platform.python_version(),
                          'numpy': np.__version__}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    output = parser.parse_args().output.resolve()
    REQUIRE(output.is_relative_to(LOCAL) and not output.exists(), 'Use a new report path under .local/gegi-low-energy-trigger')
    report = run()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as handle:
        handle.write(encoded(report) + b'\n')
    print(json.dumps({'output': str(output), 'continuous': report['continuous']['counts'],
                      'missed': report['missed_cases']['nominal_miss_mechanisms'],
                      'empty': report['empty_control']['poisson_count_model'],
                      'wall_s': report['resources']['wall_s']}, indent=2))


if __name__ == '__main__':
    main()
