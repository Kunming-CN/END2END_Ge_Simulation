"""Continuous nominal GeGI ADC exposure with sparse readout feature windows."""

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
import hashlib
import math

import numpy as np

import gegi_digital_readout as digital
from gegi_imaging import MIN_COLLECTED_KEV
import gegi_pulse_stream as pulse


SAMPLE_PERIOD_NS = digital._DT
PREAMBLE_SAMPLES = digital._TRIGGER_INDEX
DEFAULT_BLOCK_SAMPLES = 32768
_IDS = digital.CONTACT_IDS
_ALPHA = math.exp(-SAMPLE_PERIOD_NS / digital._TAU)
_TAUS = np.array([digital._TAU, digital._BANDWIDTH_TAU])[:, None]
_POLE_GAIN = digital._TAU / (digital._TAU - digital._BANDWIDTH_TAU)


class ADCExposure:
    """Generate known native components on one clock with zero state at t=0.

    Every iteration starts a fresh copy of the same ADC exposure. The initial
    quiet preamble and all live samples use one uninterrupted RNG per channel.
    The source ledger is responsible for qualifying unknown input intervals.
    """

    def __init__(self, components, *, live_time_ns, phase_ns=0., noise_seed=None):
        if not math.isfinite(phase_ns) or not 0 <= phase_ns < SAMPLE_PERIOD_NS:
            raise ValueError('ADC phase must be in one nominal sample period')
        if not math.isfinite(live_time_ns) or live_time_ns <= phase_ns:
            raise ValueError('Live interval must contain at least one ADC sample')
        if noise_seed is not None and (type(noise_seed) is not int or not 0 <= noise_seed < 2**64):
            raise ValueError('Use a digital noise seed smaller than 2**64')
        components = tuple(components)
        if any(not isinstance(native, pulse.NativePulse) or not math.isfinite(t) or not 0 <= t < live_time_ns
               or not math.isfinite(scale) or scale <= 0 for native, t, scale in components):
            raise ValueError('Use prepared native waveforms with in-exposure onsets and positive scales')
        self.phase_ns = float(phase_ns)
        self.live_time_ns = float(live_time_ns)
        self.live_samples = math.ceil((live_time_ns - phase_ns) / SAMPLE_PERIOD_NS)
        self.noise_seed = noise_seed
        self._components = sorted(components, key=lambda item: item[1])
        self._onsets = np.array([t for _, t, _ in self._components])
        self._ends = np.array([t + n.time_ns[-1] for n, t, _ in self._components])

        # Accumulate free-tail pole states at exact native endpoints, independent
        # of how the ADC stream is partitioned. Contributions still in native
        # support are evaluated separately only at the ADC samples they affect.
        order = np.argsort(self._ends, kind='stable')
        self._stops = self._ends[order]
        self._tails = np.zeros((len(order), 2, len(_IDS)))
        carry = np.zeros((2, len(_IDS)))
        prior = 0.
        for i, slot in enumerate(order):
            native, _, scale = self._components[slot]
            end = self._stops[i]
            carry = carry * np.exp(-(end - prior) / _TAUS) + scale * native.knot_V[..., -1]
            self._tails[i] = carry
            prior = end

    def sample_time_ns(self, index):
        return np.asarray(index) * SAMPLE_PERIOD_NS + self.phase_ns

    def _analog(self, time):
        voltage = np.zeros((len(_IDS), len(time)))
        first = int(self._stops.searchsorted(time[0], side='right')) - 1
        final = int(self._stops.searchsorted(time[-1], side='right'))
        boundaries = np.r_[0, time.searchsorted(self._stops[first+1:final]), len(time)]
        for tail_index, lo, hi in zip(range(first, final), boundaries[:-1], boundaries[1:]):
            if tail_index < 0 or lo == hi:
                continue
            decay = np.exp(-(time[lo:hi] - self._stops[tail_index]) / _TAUS)
            amplitudes = self._tails[tail_index]
            voltage[:, lo:hi] = _POLE_GAIN * (amplitudes[0, :, None] * decay[0]
                                              - amplitudes[1, :, None] * decay[1])
        for slot in np.flatnonzero((self._onsets <= time[-1]) & (self._ends > time[0])):
            native, onset, scale = self._components[slot]
            lo, hi = time.searchsorted([onset, self._ends[slot]])
            voltage[:, lo:hi] += scale * pulse._sample_pulse(native, time[lo:hi] - onset)
        return voltage

    def blocks(self, block_samples=DEFAULT_BLOCK_SAMPLES):
        """Yield (first absolute index, signed int16 codes[34, n]) in order."""
        if type(block_samples) is not int or block_samples <= 0:
            raise ValueError('ADC block size must be a positive integer')
        rngs = () if self.noise_seed is None else tuple(
            np.random.Generator(np.random.PCG64([self.noise_seed, cid])) for cid in _IDS)

        def digitize(voltage):
            for values, rng in zip(voltage, rngs):
                values += rng.normal(0., digital._PROFILE['optional_noise_rms_V'], values.size)
            return digital._digitize(voltage)[0].astype(np.int16)

        yield -PREAMBLE_SAMPLES, digitize(np.zeros((len(_IDS), PREAMBLE_SAMPLES)))
        for start in range(0, self.live_samples, block_samples):
            time = self.sample_time_ns(np.arange(start, min(start + block_samples, self.live_samples)))
            yield start, digitize(self._analog(time))


def _rail(code):
    return (code == digital._ADC_MIN) | (code == digital._ADC_MAX)


def _face_voltages(code):
    return np.array([code[face].sum(axis=0) for face in pulse._FACES]) * digital._LSB_V


def _register_groups(groups, start, change):
    indices = np.flatnonzero(np.max(np.abs(change), axis=0) > pulse._QUIET_KEV)
    if not indices.size:
        return
    values = np.min(change, axis=0) >= pulse._TRIGGER_KEV
    for group in np.split(indices, np.flatnonzero(np.diff(indices) > pulse._QUIET_SAMPLES) + 1):
        begin, end = int(group[0]) + start - 1, int(group[-1]) + start
        coincidence = bool(values[group[0]:group[-1]+1].any())
        if groups and begin + 1 - groups[-1][1] <= pulse._QUIET_SAMPLES:
            first, _, prior_coincidence = groups.pop()
            groups.append((first, end, prior_coincidence or coincidence))
        else:
            groups.append((begin, end, coincidence))


def _find_activity(exposure, block_samples):
    blocks = exposure.blocks(block_samples)
    first, preamble = next(blocks)
    baseline = (preamble * digital._LSB_V).mean(axis=1)
    face_baseline = np.array([baseline[face].sum() for face in pulse._FACES])[:, None]
    previous = _face_voltages(preamble[:, -pulse._FAST_SAMPLES:]) - face_baseline
    digest = hashlib.sha256(np.asarray(preamble.T, dtype='<i2', order='C').tobytes())
    groups = []
    rail_by_contact = _rail(preamble).sum(axis=1, dtype=np.int64)
    for start, code in blocks:
        digest.update(np.asarray(code.T, dtype='<i2', order='C').tobytes())
        rail_by_contact += _rail(code).sum(axis=1, dtype=np.int64)
        face = np.concatenate((previous, _face_voltages(code) - face_baseline), axis=1)
        previous = face[:, -pulse._FAST_SAMPLES:]
        # A first difference of a trailing average of the corrected level is
        # the mean of its last two pole-zero increments. Only the most recent
        # two ADC samples are needed across block boundaries.
        increments = face[:, 1:] - _ALPHA * face[:, :-1]
        change = (increments[:, 1:] + increments[:, :-1]) / (pulse._FAST_SAMPLES * pulse._SLOW_GAIN)
        _register_groups(groups, start, change)
    return baseline, groups, rail_by_contact, digest.hexdigest()


@dataclass
class _Context:
    lo: int
    hi: int
    pivot: int
    neighboring: range
    codes: np.ndarray | None = None


def _contexts(exposure, groups):
    starts, ends = [row[0] for row in groups], [row[1] for row in groups]
    contexts = []
    slow_start, slow_stop = (v // SAMPLE_PERIOD_NS for v in pulse._SLOW_NS)
    for i, (start, _, coincident) in enumerate(groups):
        if not coincident:
            continue
        support_lo = start + slow_start - pulse._SLOW_LOOKBACK - 1
        settle = 2 * pulse._QUIET_SAMPLES
        # An earlier activity settled before the first slow support contributes
        # a common level. A later activity starting beyond the final slow sample
        # cannot influence any of the fixed fast, slow or CFD supports.
        left = bisect_left(ends, support_lo - settle)
        right = bisect_right(starts, start + slow_stop)
        baseline_margin = pulse._QUIET_SAMPLES + pulse._FAST_SAMPLES + 2
        lo = max(-PREAMBLE_SAMPLES, min(support_lo, starts[left] - baseline_margin))
        hi = min(exposure.live_samples, max(start + slow_stop, ends[right-1] + settle) + 1)
        contexts.append(_Context(lo, hi, i, range(left, right)))
    return contexts


def _context_readout(context, exposure, groups, baseline):
    code = context.codes
    rail = _rail(code)
    centered = code * digital._LSB_V - baseline[:, None]
    delayed = np.pad(centered[:, :-1], ((0, 0), (1, 0)))
    corrected = np.cumsum(centered - _ALPHA * delayed, axis=1)
    # The previous pole-zero accumulator would add one constant per electrode.
    # Every requested gate is within this context, so the differences of local
    # corrected levels exactly cancel that constant.
    fast = np.array([digital._moving_average(row, pulse._FAST_SAMPLES) for row in corrected])
    average = np.array([digital._moving_average(row, pulse._SLOW_RISE) for row in corrected])
    slow = average - np.pad(average, ((0, 0), (pulse._SLOW_RISE + pulse._SLOW_GAP, 0)))[:, :code.shape[1]]
    activities = []
    for group in context.neighboring:
        start, end, coincident = groups[group]
        following = groups[group+1][0] if group+1 < len(groups) else exposure.live_samples
        activities.append(pulse._local_activity(start-context.lo, end-context.lo, coincident,
                                               following-context.lo, corrected, fast, rail))
    i = context.pivot - context.neighboring.start
    time_ns = exposure.sample_time_ns(np.arange(context.lo, context.hi))
    return pulse._pulse_features(activities[i], time_ns, rail, centered, slow, fast,
                                 activities[:i] + activities[i+1:])


def _feature_contexts(exposure, block_samples, groups, baseline, contexts):
    pending = iter(contexts)
    current, active = next(pending, None), []
    for offset, code in exposure.blocks(block_samples):
        end = offset + code.shape[1]
        while current is not None and current.lo < end:
            current.codes = np.empty((len(_IDS), current.hi-current.lo), dtype=np.int16)
            active.append(current)
            current = next(pending, None)
        remaining = []
        for context in active:
            lo, hi = max(offset, context.lo), min(end, context.hi)
            context.codes[:, lo-context.lo:hi-context.lo] = code[:, lo-offset:hi-offset]
            if context.hi <= end:
                yield _context_readout(context, exposure, groups, baseline)
                context.codes = None
            else:
                remaining.append(context)
        active = remaining
        if current is None and not active:
            break


def reconstruct_exposure(exposure, *, block_samples=DEFAULT_BLOCK_SAMPLES):
    """Reconstruct a complete clock from deterministic ADC blocks, without truth."""
    baseline, groups, rail, adc_sha = _find_activity(exposure, block_samples)
    contexts = _contexts(exposure, groups)
    events, rejected = [], []
    if contexts:
        candidates = _feature_contexts(exposure, block_samples, groups, baseline, contexts)
        for event in candidates:
            steps = event['face_step_keV']
            if steps is not None and min(steps) < MIN_COLLECTED_KEV:
                rejected.append({'trigger_time_ns': event['trigger_time_ns'], 'face_step_keV': steps,
                                 'reason': 'no_persistent_coincident_charge_step'})
            else:
                events.append(event)
    events.sort(key=lambda event: event['trigger_time_ns'])
    flags = []
    if rail.any():
        flags.append('adc_saturation')
    if not events:
        flags.append('no_coincident_trigger')
    return {'events': events, 'flags': flags, 'rejected_rises': rejected,
            'activity_count': len(groups), 'maximum_context_samples': max((c.hi-c.lo for c in contexts), default=0),
            'unconfirmed_activity_count': sum(not row[2] for row in groups),
            'saturated_contact_ids': [cid for cid, n in zip(_IDS, rail) if n],
            'saturated_adc_codes': int(rail.sum()), 'adc_sha256': adc_sha,
            'adc_samples_per_channel': exposure.live_samples,
            'preamble_samples_per_channel': PREAMBLE_SAMPLES}
