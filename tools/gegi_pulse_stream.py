"""Nominal GeGI continuous ADC replay and waveform-only pulse finding."""

from dataclasses import dataclass
import math

import numpy as np

import gegi_digital_readout as D
from gegi_imaging import MIN_COLLECTED_KEV, PAIR_ABS_KEV, PAIR_REL
from gegi_substrip import infer_position


_IDS = D.CONTACT_IDS
_WIRING = {cid: 1 if cid <= 17 else -1 for cid in _IDS}
_FACES = (slice(0, 17), slice(17, 34))
_GUARDS = {17, 34}
_TAUS = np.array([D._TAU, D._BANDWIDTH_TAU])[:, None, None]
_FAST_NS = D._PROFILE['fast_area_gate_ns'][1]
_SLOW_NS = D._PROFILE['slow_plateau_gate_ns']
_FAST_SAMPLES = D._PROFILE['fast_average_ns'] // D._DT
_SLOW_RISE = D._PROFILE['slow_rise_ns'] // D._DT
_SLOW_GAP = D._PROFILE['slow_flat_ns'] // D._DT
_SLOW_LOOKBACK = 2 * _SLOW_RISE + _SLOW_GAP - 1
_CFD_NS = D._TIMING['gate_ns'][1]
_TRIGGER_KEV = 5.
_QUIET_KEV = 3.
_QUIET_SAMPLES = 3
_LOCAL_INTERFERENCE_KEV = D._PROFILE['slow_threshold_keV']
_SLOW_GAIN = D._CALIBRATION['slow_V_per_keV']
_FAST_GAIN = D._CALIBRATION['fast_V_ns_per_keV_equiv']

DEFINITION = {
    'kind': 'gegi_nominal_adc_pulse_stream_v1',
    'digital_profile_sha256': D.PROFILE_SHA256,
    'timing_sha256': D.TIMING_SHA256,
    'phase': 'Common ADC phase in ns, 0 <= phase < one sample period, relative to acquisition time zero.',
    'analog': 'Sum exact two-pole responses to signed piecewise-constant native currents. Verified endpoints allow free decay.',
    'adc': 'Add nominal independent noise once per complete sampled channel if seeded, then quantize once.',
    'trigger': 'Coincident positive increments of both signed all-contact face sums from the continuous fast branch.',
    'trigger_change_keV_per_sample': _TRIGGER_KEV,
    'quiet_absolute_change_keV_per_sample': _QUIET_KEV,
    'quiet_samples': _QUIET_SAMPLES,
    'trigger_reference': 'Last sample before coincident rise activity, following at least three quiet increments to rearm.',
    'strip_assignment': 'Positive net step on one strip per face after trigger settling, with fixed GeGI strip-pair compatibility.',
    'step_settling_samples': 2 * _QUIET_SAMPLES,
    'unresolved_scope': 'One observed rise may contain multiple interactions. Its measured amplitude does not resolve that multiplicity.',
    'slow_scope': 'Continuous nominal trapezoid and fixed pulser gain. Report the mean of an independently qualified X/Y pair.',
    'fast_scope': 'Nominal signed 240 ns area with subtraction of the recent quiet fast level. Position is a nominal calibration transfer to the ADC trigger reference.',
    'local_interference': 'For each other observed rise, project its measured pole-zero activity and settled charge step into this electrode’s slow trapezoid and locally referenced fast and timing gates. Screen affected observables without subtracting predicted interference.',
    'local_interference_threshold_keV_equiv': _LOCAL_INTERFERENCE_KEV,
}


@dataclass(frozen=True)
class NativePulse:
    time_ns: np.ndarray
    drive_V: np.ndarray
    knot_V: np.ndarray


@dataclass(frozen=True)
class _Activity:
    start: int
    last: int
    coincident: bool
    steps_keV: np.ndarray | None
    usable: np.ndarray
    fast_V: np.ndarray
    slow_V: np.ndarray


def prepare_native(native, channels, *, terminal_complete):
    """Bind all signed waveforms to the nominal linear analog response."""
    if terminal_complete is not True:
        raise ValueError('Pulse replay requires verified terminal native contacts')
    if len(channels) != len(_IDS) or {c['id']: c['wiring_factor'] for c in channels} != _WIRING:
        raise ValueError('Pulse replay requires all 34 contact IDs and fixed wiring')
    if set(native) != set(_IDS):
        raise ValueError('Pulse replay requires all 34 signed native signals')
    time_ns = np.array(native[1]['time_ns'], dtype=float)
    widths = np.diff(time_ns) if time_ns.ndim == 1 else np.array([])
    if not len(widths) or time_ns[0] != 0 or not np.isfinite(time_ns).all() or np.any(widths <= 0):
        raise ValueError('Invalid zero-origin native GeGI time grid')
    charge = []
    for cid, wiring in _WIRING.items():
        row = native[cid]
        q = np.asarray(row['signed_induced_keV'], dtype=float)
        if (not np.array_equal(time_ns, row['time_ns']) or q.shape != time_ns.shape
                or q[0] != 0 or not np.isfinite(q).all()):
            raise ValueError(f'Invalid common native grid or signed charge for GeGI contact {cid}')
        charge.append(wiring * q)

    # The two pole states evolve with the same interval current. Propagating
    # from one knot at a time keeps long native support numerically bounded.
    drive = _TAUS * D._VOLTS_PER_KEV * (np.diff(charge) / widths)
    drive = np.pad(drive, ((0, 0), (0, 0), (0, 1)))
    decay = np.exp(-widths / _TAUS)
    increment = drive[..., :-1] * -np.expm1(-widths / _TAUS)
    knot = np.zeros_like(drive)
    for i in range(len(widths)):
        knot[..., i + 1] = knot[..., i] * decay[..., i] + increment[..., i]
    return NativePulse(time_ns, drive, knot)


def _sample_pulse(pulse, time_ns):
    """Evaluate at arbitrary nonnegative times including the free-decay tail."""
    i = np.searchsorted(pulse.time_ns, time_ns, side='right') - 1
    elapsed = (time_ns - pulse.time_ns[i]) / _TAUS
    voltage = pulse.knot_V[..., i] * np.exp(-elapsed) - pulse.drive_V[..., i] * np.expm1(-elapsed)
    return D._TAU / (D._TAU - D._BANDWIDTH_TAU) * (voltage[0] - voltage[1])


def _analog_stream(components, phase_ns, window_end_ns):
    if not math.isfinite(phase_ns) or not 0 <= phase_ns < D._DT:
        raise ValueError(f'ADC phase must be in [0, {D._DT}) ns')
    components = tuple(components)
    if any(not isinstance(pulse, NativePulse) or not math.isfinite(onset) or onset < 0
           or not math.isfinite(scale) or scale <= 0 for pulse, onset, scale in components):
        raise ValueError('Pulse replay requires prepared pulses, nonnegative onsets and positive scales')
    if window_end_ns is None:
        window_end_ns = max((onset + max(pulse.time_ns[-1], D._TIME_NS[-1])
                             for pulse, onset, _ in components), default=D._TIME_NS[-1])
    if not math.isfinite(window_end_ns) or window_end_ns < phase_ns:
        raise ValueError('ADC acquisition must contain a sample at or after time zero')
    last = math.floor((window_end_ns - phase_ns) / D._DT)
    time_ns = np.arange(-D._TRIGGER_INDEX, last + 1) * D._DT + phase_ns
    preamp = np.zeros((len(_IDS), len(time_ns)))
    for pulse, onset, scale in components:
        start = time_ns.searchsorted(onset)
        preamp[:, start:] += scale * _sample_pulse(pulse, time_ns[start:] - onset)
    return time_ns, preamp


def acquire(components, *, phase_ns=0., noise_seed=None, window_end_ns=None):
    """Return sample times and (34, n) ADC codes from delayed scaled components."""
    if noise_seed is not None and (type(noise_seed) is not int or not 0 <= noise_seed < 2**64):
        raise ValueError('Use a nonnegative integer digital noise seed smaller than 2**64')
    time_ns, voltage = _analog_stream(components, phase_ns, window_end_ns)
    if noise_seed is not None:
        for i, cid in enumerate(_IDS):
            rng = np.random.Generator(np.random.PCG64([noise_seed, cid]))
            voltage[i] += rng.normal(0, D._PROFILE['optional_noise_rms_V'], len(time_ns))
    adc_code, _ = D._digitize(voltage)
    return time_ns, adc_code


def _activities(fast):
    # A coincident first difference of the corrected face sums suppresses
    # channel induction transients and retains charge increments on a tail.
    face = np.array([fast[s].sum(axis=0) for s in _FACES]) / _SLOW_GAIN
    change = np.diff(face, axis=1, prepend=face[:, :1])
    change = change[:, D._TRIGGER_INDEX:]
    indices = np.flatnonzero(np.max(np.abs(change), axis=0) > _QUIET_KEV)
    if not len(indices):
        return []
    groups = np.split(indices, np.flatnonzero(np.diff(indices) > _QUIET_SAMPLES) + 1)
    coincidence = np.min(change, axis=0) >= _TRIGGER_KEV
    return [(g[0] + D._TRIGGER_INDEX - 1, g[-1] + D._TRIGGER_INDEX,
             bool(coincidence[g[0]:g[-1]+1].any())) for g in groups]


def _assign_strip_pair(steps_keV, usable):
    hits = [cid for cid, step, valid in zip(_IDS, steps_keV, usable)
            if valid and step >= MIN_COLLECTED_KEV]
    xs, ys = ([cid for cid in hits if cid <= 17], [cid for cid in hits if cid > 17])
    if _GUARDS.intersection(hits):
        return hits, None, 'guard_collection'
    if not usable.all():
        return hits, None, 'step_adc_saturation'
    if len(xs) != 1 or len(ys) != 1:
        return hits, None, 'unresolved_strip_multiplicity'
    x, y = steps_keV[[xs[0]-1, ys[0]-1]]
    if abs(x-y) > max(PAIR_ABS_KEV, PAIR_REL*max(x, y)):
        return hits, None, 'strip_energy_mismatch'
    return hits, [xs[0], ys[0]], None


def _local_activity(start, last, coincident, next_start, corrected, fast, rail):
    """Estimate each electrode's excursion without changing its acquired trace."""
    pre = start + 1 - _QUIET_SAMPLES
    # The face sums can settle before bipolar strip transients return. Use
    # another quiet block when available, stopping at the next observed rise.
    settled = min(last + 2 * _QUIET_SAMPLES, next_start, fast.shape[1] - 1)
    left = slice(pre, start+1)
    right = slice(settled+1-_QUIET_SAMPLES, settled+1)
    usable = ~rail[:, pre-1:settled+1].any(axis=1)
    steps = None
    if settled >= last + _QUIET_SAMPLES:
        steps = (fast[:, right].mean(axis=1) - fast[:, left].mean(axis=1)) / _SLOW_GAIN
    local = np.zeros_like(corrected)
    local[:, start+1:settled+1] = corrected[:, start+1:settled+1] - corrected[:, left].mean(axis=1)[:, None]
    if steps is not None:
        local[:, settled+1:] = local[:, right].mean(axis=1)[:, None]
    local_fast = np.array([D._moving_average(row, _FAST_SAMPLES) for row in local])
    averaged = np.array([D._moving_average(row, _SLOW_RISE) for row in local])
    local_slow = averaged - np.pad(averaged, ((0, 0), (_SLOW_RISE + _SLOW_GAP, 0)))[:, :fast.shape[1]]
    return _Activity(start, last, coincident, steps, usable, local_fast, local_slow)


def _local_overlap(activities, pre, start, fast_stop, slow_start, slow_stop, cfd_stop):
    fast_risk, slow_risk, cfd_risk = np.zeros((3, len(_IDS)))
    for other in activities:
        reference = other.fast_V[:, pre:start+1].mean(axis=1)[:, None]
        fast_risk += np.max(np.abs(other.fast_V[:, pre:fast_stop+1] - reference), axis=1)
        cfd_risk += np.max(np.abs(other.fast_V[:, pre:cfd_stop+1] - reference), axis=1)
        slow_gate = other.slow_V[:, slow_start:slow_stop+1]
        if slow_gate.size:
            slow_risk += np.max(np.abs(slow_gate), axis=1)
    cutoff = _LOCAL_INTERFERENCE_KEV * _SLOW_GAIN
    return fast_risk >= cutoff, slow_risk >= cutoff, cfd_risk >= cutoff


def _pulse_features(activity, time_ns, rail, centered, slow, fast, other_activities):
    flags = []
    n = len(time_ns)
    start, end = activity.start, activity.last
    pre = start + 1 - _QUIET_SAMPLES
    step_base = fast[:, pre:start+1].mean(axis=1)
    hits, pair = [], None
    face_step = None
    if activity.steps_keV is not None:
        hits, pair, issue = _assign_strip_pair(activity.steps_keV, activity.usable)
        if activity.usable.all():
            face_step = [float(activity.steps_keV[s].sum()) for s in _FACES]
        if issue:
            flags.append(issue)
    else:
        flags.append('step_window_truncated')

    fast_stop = start + _FAST_NS // D._DT
    slow_start, slow_stop = (start + ns // D._DT for ns in _SLOW_NS)
    cfd_stop = start + _CFD_NS // D._DT
    quiet_lo = pre - _FAST_SAMPLES
    slow_lo = max(0, slow_start - _SLOW_LOOKBACK - 1)
    fast_overlap, slow_overlap, cfd_overlap = _local_overlap(
        other_activities, pre, start, fast_stop, slow_start, slow_stop, cfd_stop)
    for label, stop in (('fast', fast_stop), ('slow', slow_stop)):
        if stop >= n:
            flags.append(label + '_window_truncated')
    neighbors = {cid-1 for cid in hits}
    for cid in hits:
        for neighbor in (cid-1, cid+1):
            if (neighbor in _WIRING and _WIRING[neighbor] == _WIRING[cid] and neighbor not in _GUARDS):
                neighbors.add(neighbor-1)
    if any(fast_overlap[i] for i in neighbors):
        flags.append('fast_pileup')
    if any(slow_overlap[cid-1] for cid in hits):
        flags.append('slow_pileup')

    rows = []
    for i, cid in enumerate(_IDS):
        row = {'contact_id': cid, 'wiring_factor': _WIRING[cid], 'flags': [],
               'slow_energy_keV': None, 'slow_plateau_span_keV': None,
               'fast_signal_keV_equiv': None, 'fast_area_V_ns': None, 'preamp_cfd50_ns': None}
        rows.append(row)
        for label, overlap, stop in (('fast', fast_overlap[i], fast_stop), ('slow', slow_overlap[i], slow_stop)):
            if overlap:
                row['flags'].append(label + '_pileup')
            if stop >= n:
                row['flags'].append(label + '_window_truncated')
        if rail[i, max(0, quiet_lo):fast_stop+1].any():
            row['flags'].append('fast_adc_saturation')
        elif fast_stop < n and not fast_overlap[i]:
            gate = fast[i, start:fast_stop+1] - step_base[i]
            area = float(D._DT * (gate[1:-1].sum() + (gate[0] + gate[-1]) / 2))
            row.update(fast_area_V_ns=area, fast_signal_keV_equiv=area/_FAST_GAIN)
        if rail[i, slow_lo:slow_stop+1].any():
            row['flags'].append('slow_adc_saturation')
        elif slow_stop < n and not slow_overlap[i]:
            plateau = slow[i, slow_start:slow_stop+1] / _SLOW_GAIN
            energy, span = float(plateau.mean()), float(np.ptp(plateau))
            row['slow_plateau_span_keV'] = span
            limit = max(D._PROFILE['slow_plateau_max_absolute_span_keV'],
                        D._PROFILE['slow_plateau_max_fractional_span'] * energy)
            if energy < D._PROFILE['slow_threshold_keV']:
                row['flags'].append('slow_below_threshold')
            elif span > limit:
                row['flags'].append('slow_plateau_unsettled')
            else:
                row['slow_energy_keV'] = energy
                if cfd_overlap[i]:
                    row['flags'].append('preamp_cfd_pileup')
                if cfd_stop < n and not cfd_overlap[i] and not rail[i, pre:cfd_stop+1].any():
                    ref = np.arange(pre, start + 1)
                    prior = np.mean(centered[i, ref] * np.exp((ref - start) * D._DT / D._TAU))
                    trace = centered[i, start:cfd_stop+1] - prior * np.exp(
                        -np.arange(cfd_stop - start + 1) * D._DT / D._TAU)
                    # Reuse the nominal CFD convention on the local ADC gate.
                    trace = np.pad(trace, (D._TRIGGER_INDEX, 0))
                    row['preamp_cfd50_ns'] = D._preamp_cfd50_ns(trace, 0., energy * _SLOW_GAIN)
                if row['preamp_cfd50_ns'] is None:
                    row['flags'].append('preamp_cfd50_unavailable')

    energy = None
    if pair is not None:
        other_hits = {cid for other in other_activities if other.coincident and other.steps_keV is not None
                      for cid, step, usable in zip(_IDS, other.steps_keV, other.usable)
                      if usable and step >= MIN_COLLECTED_KEV}
        extra_hits = {row['contact_id'] for row in rows if row['slow_energy_keV'] is not None
                      and row['slow_energy_keV'] >= MIN_COLLECTED_KEV} - set(pair) - other_hits
        x, y = [rows[cid-1]['slow_energy_keV'] for cid in pair]
        if (not extra_hits and x is not None and y is not None and min(x, y) >= MIN_COLLECTED_KEV
                and abs(x-y) <= max(PAIR_ABS_KEV, PAIR_REL * max(x, y))):
            energy = (x + y) / 2
        else:
            flags.append('unqualified_slow_energy')
    return {'trigger_time_ns': float(time_ns[start]), 'rise_end_ns': float(time_ns[end]),
            'face_step_keV': face_step, 'contact_ids': pair, 'step_contact_ids': hits,
            'slow_energy_keV': energy, 'channels': rows, 'flags': flags,
            'profile_sha256': D.PROFILE_SHA256, 'timing_sha256': D.TIMING_SHA256,
            'position': None, 'position_mm': None}


def reconstruct(time_ns, adc_code, *, channels=None, calibration=None, source_identity=None):
    """Find pulses using only ADC samples and the fixed GeGI channel layout."""
    time_ns = np.asarray(time_ns, dtype=float)
    code = np.asarray(adc_code)
    if (time_ns.ndim != 1 or len(time_ns) <= D._TRIGGER_INDEX
            or not np.isfinite(time_ns).all()
            or not np.allclose(np.diff(time_ns), D._DT, rtol=0, atol=1e-8)
            or code.shape != (len(_IDS), len(time_ns)) or not np.issubdtype(code.dtype, np.integer)
            or np.any(code < D._ADC_MIN) or np.any(code > D._ADC_MAX)):
        raise ValueError('Expected a common nominal ADC time grid and 34 rows of signed ADC codes')
    if calibration is not None and channels is None:
        raise ValueError('Position calibration requires GeGI channel geometry')
    voltage = code * D._LSB_V
    baseline, slow, fast = zip(*(D._filters(row) for row in voltage))
    slow, fast = np.array(slow), np.array(fast)
    centered = voltage - np.asarray(baseline)[:, None]
    rail = (code == D._ADC_MIN) | (code == D._ADC_MAX)
    delayed = np.pad(centered[:, :-1], ((0, 0), (1, 0)))
    corrected = np.cumsum(centered - np.exp(-D._DT / D._TAU) * delayed, axis=1)
    groups = _activities(fast)
    next_starts = [group[0] for group in groups[1:]] + [len(time_ns)]
    activities = [_local_activity(*group, following, corrected, fast, rail)
                  for group, following in zip(groups, next_starts)]
    events, rejected = [], []
    for i, activity in enumerate(activities):
        if not activity.coincident:
            continue
        pulse = _pulse_features(activity, time_ns, rail, centered, slow, fast,
                                activities[:i] + activities[i+1:])
        step = pulse['face_step_keV']
        if step is not None and min(step) < MIN_COLLECTED_KEV:
            rejected.append({'trigger_time_ns': pulse['trigger_time_ns'], 'face_step_keV': step,
                             'reason': 'no_persistent_coincident_charge_step'})
            continue
        if calibration is not None and pulse['slow_energy_keV'] is not None:
            position = infer_position(calibration, *pulse['contact_ids'], pulse, channels,
                                      source_identity=source_identity, mode='cfd_conditioned')
            pulse['position'] = position
            if (position['calibration_source_status'] == 'matching_saved_fields'
                    and position['calibration_pair_coverage'] == 'simulated_pair'):
                axes = [position[key] for key in ('x', 'y', 'depth')]
                if all(axis['status'] == 'estimated' for axis in axes):
                    pulse['position_mm'] = [axis['position_mm'] for axis in axes]
        events.append(pulse)
    flags = []
    rail_contacts = [cid for cid, hit in zip(_IDS, rail.any(axis=1)) if hit]
    if rail_contacts:
        flags.append('adc_saturation')
    if not events:
        flags.append('no_coincident_trigger')
    return {'events': events, 'flags': flags, 'saturated_contact_ids': rail_contacts,
            'rejected_rises': rejected,
            'unconfirmed_activity_count': sum(not a.coincident for a in activities)}
