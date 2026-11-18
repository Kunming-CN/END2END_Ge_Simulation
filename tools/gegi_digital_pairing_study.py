"""Compare digital fast area and CFD pairing evidence on the sealed GeGI fixed eight."""

import argparse
from collections import Counter
import hashlib
from itertools import product
import json
from pathlib import Path
import platform

import numpy as np
from scipy import __version__ as scipy_version
from scipy.optimize import least_squares

import gegi_digital_pairs as P
import gegi_digital_readout as D
from gegi_native_pair_readout import complete_native


ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / '.local/gegi-digital-v1'
NATIVE = ROOT / '.local/gegi-10m/signal-recovery-v1'
LATERAL = NATIVE / 'calibration/full34-lateral-pilot/results'
CONTROL = NATIVE / 'calibration/native-region-bank/results'
LEGACY = NATIVE / 'validation/native-pair-readout'
PIXELS = tuple(product((11, 12), (24, 26)))
COLLECTORS = (11, 12, 24, 26)
NEIGHBORHOOD = (10, 11, 12, 13, 23, 24, 25, 26, 27)
MODES = ('pair_cfd', 'centered_cfd', 'fast', 'fast_and_centered_cfd')
SHAPE = np.array([3, 3, 11])
GRID = np.array(list(np.ndindex(*SHAPE)))
BITS = np.array(list(np.ndindex(2, 2, 2)))
START_COUNT = 6
CFD_SLICE = slice(D._TRIGGER_INDEX, D._TIMING_STOP_INDEX)
CFD_COUNT = CFD_SLICE.stop - CFD_SLICE.start
SUPPORT_DESCRIPTIONS = {
    'pair_cfd': 'Two candidate X minus Y CFD differences, in ns.',
    'centered_cfd': 'Four collector CFD times minus their event mean, in ns.',
    'fast': 'Nine signed fast areas, in keV-equivalent, from collectors and the union of their nearest neighbors.',
    'fast_and_centered_cfd': 'Fast area and centered CFD, with equal group contribution after scaling by their independent-control RMS.',
}


class Inputs:
    def __init__(self):
        self.hashes = {}

    def read(self, path, expected):
        ref = path.relative_to(ROOT).as_posix()
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != expected:
            raise ValueError(f'Sealed pairing input changed: {ref}')
        self.hashes[ref] = digest
        return json.loads(raw)

    def record(self, directory, item, identity):
        ref = item['record_ref']
        record = self.read(directory / ref, item['record_sha256'])
        row = record['payload']
        if (record['identity_sha256'] != identity or row['injection_energy_keV'] != 500.
                or not item['valid'] or not row['valid']
                or len(row['endpoints']) != 2
                or {tuple(e['contact_ids']) for e in row['endpoints']} != {(cid,) for cid in row['contact_ids']}):
            raise ValueError(f'Unexpected reference identity or collecting endpoints: {ref}')
        return row


def grid_coordinates(offsets, z):
    return np.array([1 + offsets[0] / .4, 1 + offsets[1] / .4, z + 5])


def physical_coordinates(index):
    return [(float(index[i]) - 1) * .4 for i in range(2)] + [float(index[2]) - 5]


def analog_template(row, channels):
    complete_native(row)
    time = np.asarray(row['channel_signals'][0]['time_ns'])
    relevant = set(NEIGHBORHOOD)
    fast, cfd, plateaus = [], [], []
    for signal, channel in zip(row['channel_signals'], channels):
        cid = signal['contact_id']
        if cid not in relevant:
            continue
        if cid != channel['id']:
            raise ValueError('Reference signal order differs from its wiring metadata')
        charge = np.asarray(signal['signed_induced_keV']) * channel['wiring_factor']
        volts = D._preamplifier(time, charge, D._TIME_NS)
        _, slow, fast_trace = D._filters(volts)
        fast.append(D._fast_area(fast_trace) / D._CALIBRATION['fast_V_ns_per_keV_equiv'])
        if cid in COLLECTORS:
            cfd.extend(volts[CFD_SLICE])
            plateaus.append(slow[D._SLOW_START:D._SLOW_STOP+1].mean())
    return np.array(fast + cfd + plateaus) / row['injection_energy_keV']


def interpolate(model, index):
    low = np.minimum(np.floor(index).astype(int), SHAPE - 2)
    where = low + BITS
    fractions = index - low
    weights = np.prod(np.where(BITS, fractions, 1 - fractions), axis=1)
    return weights @ model[tuple(where.T)]


def analog_observation(prediction):
    fast = prediction[..., :len(NEIGHBORHOOD)]
    cfd = prediction[..., len(NEIGHBORHOOD):-len(COLLECTORS)]
    cfd = cfd.reshape(*prediction.shape[:-1], len(COLLECTORS), CFD_COUNT)
    level = D._TIMING['fraction'] * prediction[..., -len(COLLECTORS):, None]
    cross = (cfd[..., :-1] < level) & (cfd[..., 1:] >= level)
    if not np.all((cfd[..., :1] < level) & (cfd[..., -1:] >= level)) or not np.all(cross.any(axis=-1)):
        raise ValueError('Missing modeled CFD crossing in the qualified four-strip domain')
    left = CFD_COUNT - 2 - np.argmax(cross[..., ::-1], axis=-1)
    a = np.take_along_axis(cfd, left[..., None], axis=-1)[..., 0]
    b = np.take_along_axis(cfd, left[..., None] + 1, axis=-1)[..., 0]
    return fast, D._DT * (left + (level[..., 0] - a) / (b - a))


def digital_mix(components, channels, weights, archived=None):
    # Fixed prompt components share a 1 ns zero-origin native grid. Only
    # complete contact endpoints permit holding a component's last charge.
    ends = [complete_native(c) for c in components]
    time = np.arange(max(c['sample_count'] for c in ends), dtype=float)
    native = {}
    for cid in D.CONTACT_IDS:
        signals = [c['channel_signals'][cid-1] for c in components]
        if any(not np.array_equal(s['time_ns'], time[:len(s['time_ns'])]) for s in signals):
            raise ValueError('Fixed prompt mixture requires exact shared 1 ns support')
        summed = sum(w * np.pad(np.asarray(s['signed_induced_keV']), (0, len(time) - len(s['time_ns'])),
                                mode='edge') for s, w in zip(signals, weights))
        if archived is not None:
            old = archived['channels'][cid-1]
            actual = [cid, len(time), time[-1], summed[-1], summed.min(), summed.max()]
            keys = ('contact_id', 'native_sample_count', 'native_end_ns', 'final_induced_keV',
                    'native_signed_min_keV', 'native_signed_max_keV')
            if not np.allclose(actual, [old[k] for k in keys], rtol=0, atol=1e-12):
                raise ValueError(f'Archived native mixture differs on contact {cid}')
        native[cid] = {'time_ns': time, 'signed_induced_keV': summed}
    digital = D.digital_event(native, channels, terminal_complete=True)
    features = {row['contact_id']: row for row in digital['channels']}
    observations = (np.array([features[cid]['fast_signal_keV_equiv'] for cid in NEIGHBORHOOD], dtype=float),
                    np.array([features[cid]['preamp_cfd50_ns'] for cid in COLLECTORS], dtype=float))
    if not all(np.isfinite(group).all() for group in observations):
        raise ValueError('Required digital pairing features are unavailable')
    return digital, observations


def residual_groups(observation, prediction, pixels):
    fast = prediction[0] - observation[0]
    timing = prediction[1] - observation[1]
    x, y = np.array([[COLLECTORS.index(cid) for cid in pixel] for pixel in pixels]).T
    return {'fast': fast, 'centered_cfd': timing - timing.mean(axis=-1, keepdims=True),
            'pair_cfd': timing[..., x] - timing[..., y]}


def rms(array):
    return np.sqrt(np.mean(array * array, axis=-1))


def residual(mode, groups, scales):
    if mode == 'fast_and_centered_cfd':
        return np.concatenate([groups[k] / (scales[k] * np.sqrt(groups[k].shape[-1]))
                               for k in ('fast', 'centered_cfd')], axis=-1) / np.sqrt(2)
    group = groups[mode]
    return group / (scales[mode] * np.sqrt(group.shape[-1]))


def fit(observation, models, pixels, energies, scales):
    left, right = [models[pixel] for pixel in pixels]
    ea, eb = energies
    coarse = ea * left.reshape(len(GRID), -1)[:, None] + eb * right.reshape(len(GRID), -1)[None, :]
    coarse_groups = residual_groups(observation, analog_observation(coarse), pixels)
    del coarse
    out = {}
    for mode in MODES:
        def objective(index):
            prediction = analog_observation(ea * interpolate(left, index[:3]) + eb * interpolate(right, index[3:]))
            return residual(mode, residual_groups(observation, prediction, pixels), scales)

        coarse_scores = np.linalg.norm(residual(mode, coarse_groups, scales), axis=-1)
        seeds = []
        bounds = np.tile(SHAPE - 1, 2)
        for index in np.argsort(coarse_scores.ravel(), kind='stable'):
            i, j = np.unravel_index(index, coarse_scores.shape)
            candidate = np.r_[GRID[i], GRID[j]]
            if all(np.linalg.norm((candidate - start) / bounds) >= .25 for start in seeds):
                seeds.append(candidate)
            if len(seeds) >= START_COUNT:
                break
        refinements = [least_squares(objective, seed, bounds=(0, bounds), x_scale=bounds,
                                     max_nfev=70, ftol=1e-7, xtol=1e-7, gtol=1e-7) for seed in seeds]
        best = min(refinements, key=lambda result: result.cost)
        out[mode] = {'score': float(np.linalg.norm(best.fun)),
                     'best_grid_score': float(coarse_scores.min()),
                     'fit_offsets_pitch_fraction_and_z_mm': [physical_coordinates(best.x[:3]),
                                                              physical_coordinates(best.x[3:])],
                     'starts': len(refinements), 'best_optimizer_status': int(best.status),
                     'budget_exhausted_starts': sum(r.status == 0 for r in refinements)}
        if out[mode]['score'] > out[mode]['best_grid_score'] + 1e-8:
            raise ValueError('Refinement lost the best scanned grid point')
    return out


def run():
    inputs = Inputs()
    prior = inputs.read(STUDY / 'two-site-readout-check.json',
                        '6834913b365564ff320af0876ea7b58898995d92949d43f7530676dd0f5eddd4')
    validation = inputs.read(STUDY / 'calibration/conditioned-validation.json',
                             '6756fb372c754224bbd97f7c7b267f0ac93a1f9e7da30c5a3bd7099bbf4a8b75')
    if prior['digital_profile_sha256'] != D.PROFILE_SHA256 or validation['digital_profile_sha256'] != D.PROFILE_SHA256:
        raise ValueError('Digital electronics profile differs from the sealed diagnostics')
    lateral = inputs.read(LATERAL / 'COMPLETE.json', validation['source_completion_sha256'])
    identity = inputs.read(LATERAL / 'identity.json', lateral['identity_sha256'])
    independent = inputs.read(CONTROL / 'COMPLETE.json', validation['additional_completion_sha256'])
    control_request = inputs.read(CONTROL / 'bound-request.json', independent['request_sha256'])
    channels = identity['channels']
    if (control_request['channels'] != channels or control_request['field_precision_bits'] != 32
            or control_request['model_sha256'] != identity['model_sha256']
            or control_request['field_cache'] != identity['field_cache']
            or identity['injection_energy_keV'] != 500.):
        raise ValueError('Regular training and independent control reference models differ')
    legacy = [inputs.read(LEGACY / name, prior['source_and_input_sha256'][(LEGACY / name).relative_to(ROOT).as_posix()])
              for name in ('request.json', 'result.json')]
    cases, archived = [item['cases'] for item in legacy]
    matchings = (((11, 24), (12, 26)), ((11, 26), (12, 24)))
    if not (len(cases) == len(archived) == len(prior['cases']) == 8):
        raise ValueError('Expected eight sealed fixed prompt mixtures')

    slots = {}
    for item in lateral['training_records']:
        row = inputs.record(LATERAL, item, lateral['identity_sha256'])
        offset = row['lateral_offset_pitch_fraction']
        if (row['position_mm'] != item['position_mm'] or row['contact_ids'] != item['contact_ids']
                or offset != item['lateral_offset_pitch_fraction']):
            raise ValueError('Training waveform coordinates changed')
        idx = tuple(grid_coordinates(offset, row['position_mm'][2]).astype(int))
        key = tuple(row['contact_ids']), idx
        if key in slots:
            raise ValueError('Duplicate training site')
        slots[key] = analog_template(row, channels)
    if set(slots) != {(pixel, tuple(idx)) for pixel in PIXELS for idx in GRID}:
        raise ValueError('Expected a complete symmetric regular training bank')
    models = {pixel: np.array([slots[pixel, tuple(idx)] for idx in GRID]).reshape(*SHAPE, -1)
              for pixel in PIXELS}

    selected = validation['paired_comparisons']['independent_native_grid']['cfd_conditioned']['validation']
    control_items = {item['record_ref']: item for item in independent['points']}
    controls = {pixel: [] for pixel in PIXELS}
    for item in selected:
        ref = item['record_ref']
        binding = control_items[ref]
        if binding['reused_source']:
            raise ValueError('Control references must be independent native-grid captures')
        row = inputs.record(CONTROL, binding, independent['request_sha256'])
        pixel = tuple(item['contact_ids'])
        if row['position_mm'] != item['position_mm'] or row['contact_ids'] != list(pixel):
            raise ValueError('Control coordinates changed')
        index = grid_coordinates(item['offsets_pitch_fraction'], row['position_mm'][2])
        if np.any(index < 0) or np.any(index > SHAPE - 1):
            raise ValueError('Control point lies outside the common calibration domain')
        controls[pixel].append((ref, row, interpolate(models[pixel], index)))
    if {len(rows) for rows in controls.values()} != {20}:
        raise ValueError('Expected 20 independently captured controls per pixel')
    control_errors = []
    for left, right in matchings:
        for i, (ref_a, a, model_a) in enumerate(controls[left]):
            ref_b, b, model_b = controls[right][(7*i + 3) % 20]
            _, obs = digital_mix((a, b), channels, (.5, .5))
            pred = analog_observation(250 * (model_a + model_b))
            err = residual_groups(obs, pred, (left, right))
            control_errors.append({'record_refs': [ref_a, ref_b], 'errors': {k: v.tolist() for k, v in err.items()}})
    scales = {mode: float(rms(np.array([e['errors'][mode] for e in control_errors]).ravel()))
              for mode in ('fast', 'centered_cfd', 'pair_cfd')}
    if min(scales.values()) <= 0:
        raise ValueError('Could not establish a positive control error scale')
    limits = {mode: max(float(np.linalg.norm(residual(mode, {k: np.array(v) for k, v in c['errors'].items()}, scales)))
                        for c in control_errors) for mode in MODES}

    outputs = []
    for case, previous, baseline in zip(cases, archived, prior['cases']):
        index = case['mixture_index']
        refs = [item['ref'] for item in case['components']]
        expected_hashes = prior['source_and_input_sha256']
        if (index != previous['mixture_index'] or index != baseline['mixture_index']
                or case['mixing_weights'] != [.5, .5] or case['time_offsets_ns'] != [0., 0.]
                or any(expected_hashes[ref] != item['sha256'] or ref in inputs.hashes
                       for ref, item in zip(refs, case['components']))):
            raise ValueError('Fixed observation is changed or overlaps the references')
        components = [inputs.read(ROOT / ref, expected_hashes[ref])['payload'] for ref in refs]
        dig, obs = digital_mix(components, channels, case['mixing_weights'], previous)
        candidates = P.two_site_pairings(dig, channels)
        observed_energy, _ = P.slow_collectors(dig)
        if (candidates['compatible_pairing_count'] != 2 or observed_energy !=
                {int(k): v for k, v in baseline['detected_collectors_keV'].items()}):
            raise ValueError('Digital replay no longer reproduces both archived energy-compatible hypotheses')
        hypotheses = []
        for candidate in candidates['pairings']:
            pixels = tuple((s['x_contact_id'], s['y_contact_id']) for s in candidate['sites'])
            energies = [s['energy_keV'] for s in candidate['sites']]
            evidence = fit(obs, models, pixels, energies, scales)
            hypotheses.append({'pixels': pixels, 'energies_from_slow_keV': energies, 'fit': evidence})

        # Attach original component assignments only after fitting both alternatives.
        truth = sorted(tuple(c['contact_ids']) for c in components)
        correct = next(i for i, h in enumerate(hypotheses) if list(h['pixels']) == truth)
        comparison = {}
        for mode in MODES:
            scores = [h['fit'][mode]['score'] for h in hypotheses]
            within = [i for i, score in enumerate(scores) if score <= limits[mode]]
            difference = scores[1-correct] - scores[correct]
            comparison[mode] = {'truth_index': correct, 'wrong_minus_true_score': difference,
                                'raw_preference': 'tie' if abs(difference) < 1e-7 else
                                ('true' if difference > 0 else 'wrong'),
                                'indices_within_control_scale': within,
                                'control_scale_outcome': ('neither' if not within else 'both' if len(within) == 2
                                                          else 'true_only' if within[0] == correct else 'wrong_only')}
        outputs.append({'mixture_index': index, 'input_component_refs': refs,
                        'fast_keV_equiv': obs[0].tolist(), 'collector_cfd_ns': obs[1].tolist(),
                        'energy_pairing_status': candidates['status'], 'overlap_flags': candidates['flags'],
                        'hypotheses': hypotheses, 'comparison': comparison,
                        'pairing_decision': 'unresolved'})

    summary = {mode: {field: dict(Counter(r['comparison'][mode][field] for r in outputs))
                      for field in ('raw_preference', 'control_scale_outcome')} for mode in MODES}
    sources = ('tools/gegi_digital_pairing_study.py', 'tools/gegi_digital_readout.py',
               'tools/gegi_digital_pairs.py', 'tools/gegi_native_pair_readout.py',
               'tools/gegi_signal_reconstruction.py', 'tools/gegi_imaging.py')
    return {'kind': 'gegi_saved_fixed8_digital_pairing_study_v1', 'cases': outputs, 'summary': summary,
            'counts': {'energy_ambiguous_cases': len(outputs), 'unresolved_cases': len(outputs),
                       'regular_training_injections': len(slots), 'independent_control_mixtures': len(control_errors),
                       'archived_mixture_channels_matched': len(outputs)*34, 'new_physics_calls': 0},
            'method': {'observables': SUPPORT_DESCRIPTIONS, 'fast_contact_order': NEIGHBORHOOD,
                       'cfd_contact_order': COLLECTORS, 'fixed_site_weights': 'Mean of observed matched X/Y slow energies',
                       'positions': 'Free x/y in ±0.4 pitch and z in [-5, 5] mm per site, on both hypotheses.',
                       'forward': 'Trilinearly interpolate the regular saved bank per site, then sum the same-prompt analog preamp responses before evaluating CFD. Fast area and plateau are linear before ADC. The observed waves use the actual digital ADC, while predictions omit ADC rounding.',
                       'search': 'All 99 × 99 grid pairs per hypothesis plus six separated local bounded refinements per observable. The same search is used for both assignments.',
                       'scoring': 'L2 errors, scaled by pooled known-coordinate independent-control RMS per observable group. The control-scale limit is the largest known-coordinate control score for that mode, not a confidence interval.',
                       'control_mix': '40 disjoint equal-energy prompt mixtures of 80 different prior native-grid control injections. Only control interpolation errors set scales, without fitting control positions.',
                       'timing': 'Centering and X minus Y remove a common additive time shift. Prompt mixing, a fixed acquisition gate and sample phase are assumed.'},
            'scope': ['Eight fixed equal-energy mixtures from four simulated pixels with overlapping neighborhoods. No calibrated noise, crosstalk, detector data, or independent two-site validation dataset.',
                      'A raw score ranking or a margin against the empirical controls is descriptive. It does not certify the optimizer global minimum, a false-pair rate, or a production assignment.',
                      'No photon sequence inference. All energy-compatible alternatives stay unresolved in software.'],
            'controls': {'group_rms_scales': scales, 'maximum_control_score': limits, 'mixtures': control_errors},
            'input_sha256': inputs.hashes,
            'source_sha256': {ref: hashlib.sha256((ROOT / ref).read_bytes()).hexdigest() for ref in sources},
            'digital_profile_sha256': D.PROFILE_SHA256, 'digital_timing_sha256': D.TIMING_SHA256,
            'python': platform.python_version(), 'numpy': np.__version__, 'scipy': scipy_version}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    result = run()
    with args.output.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'counts': result['counts'], 'summary': result['summary']}, indent=2))


if __name__ == '__main__':
    main()
