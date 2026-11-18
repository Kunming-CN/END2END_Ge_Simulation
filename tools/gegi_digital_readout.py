"""Replay saved signed GeGI signals through a synthetic digitized preamplifier."""

from copy import deepcopy
import math

import numpy as np

from gegi_event_store import encoded, sha


KIND = 'gegi_digital_readout_v1'
CONTACT_IDS = tuple(range(1, 35))
ELECTRON_C = 1.602176634e-19
_PROFILE = {
    'kind': 'gegi_nominal_digital_engineering_v1',
    'scope': 'Synthetic engineering electronics with a fixed electronic pulser calibration.',
    'time_reference': 'Saved native signal group origin at 0 ns.',
    'wiring': 'X +1 and Y -1.',
    'ionisation_energy_eV': 2.95,
    'feedback_capacitance_pF': 0.6,
    'feedback_tau_ns': 50_000,
    'analog_bandwidth_tau_ns': 20,
    'analog_bandwidth_model': 'First-order low-pass between the charge preamplifier and ADC, nominal engineering assumption.',
    'sample_period_ns': 20,
    'adc_bits': 16,
    'adc_half_range_V': 0.25,
    'adc_convention': 'Signed codes from round-to-nearest with ties to even. Either rail flags saturation.',
    'baseline_gate_ns': [-320, -20],
    'pole_zero': 'Matched discrete correction after pretrigger mean subtraction.',
    'slow_rise_ns': 500,
    'slow_flat_ns': 500,
    'slow_plateau_gate_ns': [880, 980],
    'slow_plateau_method': 'Mean of the sampled flat top, qualified by the peak-to-peak span of those digital samples.',
    'slow_plateau_max_absolute_span_keV': 0.25,
    'slow_plateau_max_fractional_span': 0.01,
    'slow_energy_scope': 'Prompt response relative to the trigger. Later pulses outside the flat-top gate are not represented by its energy.',
    'slow_peak_gate_ns': [0, 3000],
    'slow_threshold_keV': 1.0,
    'fast_average_ns': 40,
    'fast_area_gate_ns': [0, 240],
    'fast_area_method': 'Signed trapezoidal time integral of the trailing-average pole-zero output.',
    'calibration_pulser_energy_keV': 500.0,
    'calibration_method': 'Ideal delta charge at 0 ns through the same noiseless ADC and digital filters.',
    'optional_noise_rms_V': 15e-6,
    'optional_noise_method': 'Independent Gaussian pre-ADC sample noise with a per-contact seeded PCG64 stream.',
    'native_extension': 'Zero input current and free preamplifier decay after verified native contact endpoints.',
}
PROFILE_SHA256 = sha(encoded(_PROFILE))
_TIMING = {
    'kind': 'gegi_digitized_preamp_cfd50_v1',
    'fraction': 0.5,
    'gate_ns': [0, 480],
    'method': 'Last rising threshold crossing of baseline-subtracted preamp ADC samples, with linear interpolation.',
    'threshold': 'Half the independently calibrated slow plateau voltage. Requires valid positive slow energy.',
    'scope': 'Synthetic digitized timing observable for a settled collecting step.',
}
TIMING_SHA256 = sha(encoded(_TIMING))
_DT = _PROFILE['sample_period_ns']
_TAU = _PROFILE['feedback_tau_ns']
_BANDWIDTH_TAU = _PROFILE['analog_bandwidth_tau_ns']
_ADC_MIN = -(2 ** (_PROFILE['adc_bits'] - 1))
_ADC_MAX = -_ADC_MIN - 1
_LSB_V = _PROFILE['adc_half_range_V'] / -_ADC_MIN
_VOLTS_PER_KEV = 1000 * ELECTRON_C / (_PROFILE['ionisation_energy_eV'] * _PROFILE['feedback_capacitance_pF'] * 1e-12)
_TIME_NS = np.arange(_PROFILE['baseline_gate_ns'][0], _PROFILE['slow_peak_gate_ns'][1] + _DT, _DT)
_TRIGGER_INDEX = -_PROFILE['baseline_gate_ns'][0] // _DT
_FAST_STOP_INDEX = _TRIGGER_INDEX + _PROFILE['fast_area_gate_ns'][1] // _DT + 1
_TIMING_STOP_INDEX = _TRIGGER_INDEX + _TIMING['gate_ns'][1] // _DT + 1
_SLOW_START, _SLOW_STOP = (_TRIGGER_INDEX + time // _DT for time in _PROFILE['slow_plateau_gate_ns'])


def terminal_contacts_complete(event):
    """Check completion evidence from a standalone native checkpoint."""
    steps = event.get('steps') or []
    return event.get('status') == 'completed' and bool(steps) and all(
        len(step.get('endpoints') or []) == 2 and all(
            endpoint.get('status') == 'contact' and endpoint.get('step_limit_reached') is False
            and bool(endpoint.get('contact_ids')) for endpoint in step['endpoints']
        ) for step in steps
    )


def _rc_samples(native_time, wired_q_keV, sample_time, tau):
    """Solve one first-order response for piecewise-constant native current."""
    # Keep the single interval crossing the latest requested ADC sample. The
    # exponential accumulator is then bounded by the acquisition window.
    stop = min(len(native_time), np.searchsorted(native_time, sample_time[-1], side='right') + 1)
    t, q = native_time[:stop], wired_q_keV[:stop]
    widths = np.diff(t)
    interval_drive = _VOLTS_PER_KEV * np.diff(q) / widths * tau
    attenuation = np.exp(-t / tau)
    # Use the cumulative solution only through samples at or before the gate.
    # For a sample inside the final included interval use its partial drive.
    through = np.searchsorted(t, sample_time[-1], side='right')
    increments = interval_drive[:through-1] * -np.expm1(-widths[:through-1] / tau)
    knot_voltage = np.r_[0., attenuation[1:through] * np.cumsum(increments / attenuation[1:through])]
    post = sample_time[sample_time >= 0]
    interval = np.searchsorted(t, post, side='right') - 1
    elapsed = post - t[interval]
    drive = np.r_[interval_drive, 0.]
    voltage = knot_voltage[interval] * np.exp(-elapsed / tau) - drive[interval] * np.expm1(-elapsed / tau)
    return np.r_[np.zeros(_TRIGGER_INDEX), voltage]


def _preamplifier(native_time, wired_q_keV, sample_time):
    # Convolving the feedback exponential with a unit-gain bandwidth pole
    # gives the difference of two exponentials for identical input current.
    feedback = _rc_samples(native_time, wired_q_keV, sample_time, _TAU)
    bandwidth = _rc_samples(native_time, wired_q_keV, sample_time, _BANDWIDTH_TAU)
    return _TAU / (_TAU - _BANDWIDTH_TAU) * (feedback - bandwidth)


def _digitize(voltage):
    if not np.isfinite(voltage).all():
        raise ValueError('Nonfinite GeGI preamplifier output')
    code = np.rint(np.clip(voltage, _ADC_MIN * _LSB_V, _ADC_MAX * _LSB_V) / _LSB_V).astype(int)
    return code, code * _LSB_V


def _moving_average(voltage, n):
    padded = np.pad(voltage, (n-1, 0))
    integral = np.r_[0., np.cumsum(padded)]
    return (integral[n:] - integral[:-n]) / n


def _filters(digitized):
    baseline_V = float(digitized[:_TRIGGER_INDEX].mean())
    centered = digitized - baseline_V
    # Invert the sampled impulse response and integrate it into a corrected step.
    corrected = np.cumsum(centered - math.exp(-_DT / _TAU) * np.r_[0., centered[:-1]])
    rise = _PROFILE['slow_rise_ns'] // _DT
    gap = _PROFILE['slow_flat_ns'] // _DT
    averaged = _moving_average(corrected, rise)
    slow = averaged - np.pad(averaged, (rise + gap, 0))[:len(averaged)]
    fast = _moving_average(corrected, _PROFILE['fast_average_ns'] // _DT)
    return baseline_V, slow, fast


def _fast_area(fast):
    samples = fast[_TRIGGER_INDEX:_FAST_STOP_INDEX]
    return float(_DT * (samples[1:-1].sum() + (samples[0] + samples[-1]) / 2))


def _preamp_cfd50_ns(digitized, baseline_V, plateau_V):
    level = _TIMING['fraction'] * plateau_V
    gate = digitized[_TRIGGER_INDEX:_TIMING_STOP_INDEX] - baseline_V
    if len(gate) != _TIMING_STOP_INDEX - _TRIGGER_INDEX or gate[0] >= level or gate[-1] < level:
        return None
    left = np.flatnonzero((gate[:-1] < level) & (gate[1:] >= level))[-1]
    fraction = (level - gate[left]) / (gate[left+1] - gate[left])
    return float(_DT * (left + fraction))


def _calibrate_pulser():
    energy_keV = _PROFILE['calibration_pulser_energy_keV']
    t = np.maximum(_TIME_NS.astype(float), 0.)
    charge_step_V = _VOLTS_PER_KEV * energy_keV
    preamp = charge_step_V * _TAU / (_TAU - _BANDWIDTH_TAU) * (np.exp(-t / _TAU) - np.exp(-t / _BANDWIDTH_TAU))
    _, digitized = _digitize(preamp)
    _, slow, fast = _filters(digitized)
    slow_peak_V = float(slow[_TRIGGER_INDEX:].max())
    slow_plateau_V = float(slow[_SLOW_START:_SLOW_STOP+1].mean())
    fast_area_V_ns = _fast_area(fast)
    return {
        'pulser_energy_keV': energy_keV,
        'pulser_slow_peak_V': slow_peak_V,
        'pulser_slow_plateau_V': slow_plateau_V,
        'pulser_fast_area_V_ns': fast_area_V_ns,
        'slow_V_per_keV': slow_plateau_V / energy_keV,
        'fast_V_ns_per_keV_equiv': fast_area_V_ns / energy_keV,
        'adc_lsb_V': _LSB_V,
    }


_CALIBRATION = _calibrate_pulser()


def digital_event(native, channels, *, terminal_complete=False, noise_seed=None, include_traces=False, horizon_ns=None):
    """Extract signed fast area and positive slow energy from one saved all-34 event.

    `terminal_complete` permits electronic relaxation with zero additional input
    current. Set it from verified native endpoints. `horizon_ns` is exclusive.
    This function receives signal arrays and channel wiring, with no event truth.
    """
    expected_wiring = {cid: 1 if cid <= 17 else -1 for cid in CONTACT_IDS}
    if (len(channels) != len(CONTACT_IDS)
            or {c['id']: c['wiring_factor'] for c in channels} != expected_wiring):
        raise ValueError('Digital GeGI readout requires all 34 original contact IDs and fixed wiring')
    if type(terminal_complete) is not bool:
        raise ValueError('Terminal contact completion evidence must be boolean')
    if noise_seed is not None and (type(noise_seed) is not int or not 0 <= noise_seed < 2**64):
        raise ValueError('Use a nonnegative integer digital noise seed smaller than 2**64')
    if horizon_ns is not None and (type(horizon_ns) not in (int, float) or not math.isfinite(horizon_ns) or horizon_ns <= 0):
        raise ValueError('The digital readout horizon must be finite and positive in ns')
    result = {'kind': KIND, 'status': 'native_unavailable' if native is None else 'completed',
              'profile': deepcopy(_PROFILE), 'profile_sha256': PROFILE_SHA256, 'calibration': dict(_CALIBRATION),
              'timing': deepcopy(_TIMING), 'timing_sha256': TIMING_SHA256,
              'noise_seed': noise_seed, 'flags': [], 'window': None, 'channels': []}
    if native is None:
        result['flags'].append('native_signals_unavailable')
    else:
        if set(native) != set(CONTACT_IDS):
            raise ValueError('Digital GeGI readout requires all 34 original native signals')
        native_time = np.asarray(native[1]['time_ns'], dtype=float)
        if (native_time.ndim != 1 or len(native_time) < 2 or native_time[0] != 0
                or not np.isfinite(native_time).all() or np.any(np.diff(native_time) <= 0)):
            raise ValueError('Invalid zero-origin native GeGI time grid')
        native_stop_ns = float(native_time[-1])
        time_ns = _TIME_NS
        if not terminal_complete:
            time_ns = time_ns[time_ns <= native_stop_ns]
            result['flags'].append('native_terminal_unverified')
        if horizon_ns is not None:
            time_ns = time_ns[time_ns < horizon_ns]
        if time_ns[-1] > native_stop_ns:
            result['flags'].append('terminal_preamplifier_relaxation')
        if native_stop_ns > time_ns[-1] and native_stop_ns > _TIME_NS[-1]:
            result['flags'].append('native_support_past_acquisition')
        fast_full = len(time_ns) >= _FAST_STOP_INDEX
        slow_full = len(time_ns) > _SLOW_STOP
        peak_full = len(time_ns) == len(_TIME_NS)
        result['window'] = {'native_end_ns': native_stop_ns, 'acquired_end_ns': int(time_ns[-1]),
                            'horizon_ns_exclusive': horizon_ns, 'terminal_contacts_verified': bool(terminal_complete),
                            'fast_gate_complete': fast_full, 'slow_gate_complete': slow_full,
                            'slow_peak_gate_complete': peak_full}
        if not (fast_full and slow_full):
            result['status'] = 'partial'

    for cid, wiring in expected_wiring.items():
        row = {'contact_id': cid, 'wiring_factor': wiring, 'slow_energy_keV': None, 'slow_plateau_V': None,
               'slow_plateau_span_keV': None, 'slow_peak_V': None,
               'slow_peak_time_ns': None, 'fast_area_V_ns': None, 'fast_signal_keV_equiv': None,
               'preamp_cfd50_ns': None, 'flags': []}
        result['channels'].append(row)
        if native is None:
            row['flags'].append('native_signals_unavailable')
            continue
        signal = native[cid]
        charge = np.asarray(signal['signed_induced_keV'], dtype=float)
        if (not np.array_equal(native_time, np.asarray(signal['time_ns'], dtype=float))
                or charge.shape != native_time.shape or charge[0] != 0 or not np.isfinite(charge).all()):
            raise ValueError(f'Invalid common native time grid or signed charge for GeGI contact {cid}')
        preamp = _preamplifier(native_time, wiring * charge, time_ns)
        voltage = preamp
        if noise_seed is not None:
            rng = np.random.Generator(np.random.PCG64([noise_seed, cid]))
            voltage = preamp + rng.normal(0, _PROFILE['optional_noise_rms_V'], len(preamp))
        code, digitized = _digitize(voltage)
        saturated = (code == _ADC_MIN) | (code == _ADC_MAX)
        baseline_V, slow, fast = _filters(digitized)
        row['baseline_V'] = baseline_V

        if not fast_full:
            row['flags'].append('fast_window_truncated')
        if saturated[:_FAST_STOP_INDEX].any():
            row['flags'].append('fast_adc_saturation')
        elif fast_full:
            row['fast_area_V_ns'] = _fast_area(fast)
            row['fast_signal_keV_equiv'] = row['fast_area_V_ns'] / _CALIBRATION['fast_V_ns_per_keV_equiv']

        if peak_full and not saturated.any():
            peak = _TRIGGER_INDEX + int(np.argmax(slow[_TRIGGER_INDEX:]))
            row['slow_peak_V'] = float(slow[peak])
            row['slow_peak_time_ns'] = int(time_ns[peak])
            if peak == len(time_ns) - 1:
                row['flags'].append('slow_peak_at_window_end')
        if not slow_full:
            row['flags'].append('slow_window_truncated')
        if saturated[:_SLOW_STOP+1].any():
            row['flags'].append('slow_adc_saturation')
        elif slow_full:
            plateau = slow[_SLOW_START:_SLOW_STOP+1]
            row['slow_plateau_V'] = float(plateau.mean())
            row['slow_plateau_span_keV'] = float(np.ptp(plateau)) / _CALIBRATION['slow_V_per_keV']
            energy_keV = row['slow_plateau_V'] / _CALIBRATION['slow_V_per_keV']
            span_limit_keV = max(_PROFILE['slow_plateau_max_absolute_span_keV'],
                                 _PROFILE['slow_plateau_max_fractional_span'] * energy_keV)
            if energy_keV < _PROFILE['slow_threshold_keV']:
                row['flags'].append('slow_below_threshold')
            elif row['slow_plateau_span_keV'] > span_limit_keV:
                row['flags'].append('slow_plateau_unsettled')
            else:
                row['slow_energy_keV'] = energy_keV
                row['preamp_cfd50_ns'] = _preamp_cfd50_ns(digitized, baseline_V, row['slow_plateau_V'])
                if row['preamp_cfd50_ns'] is None:
                    row['flags'].append('preamp_cfd50_unavailable')

        if include_traces:
            row['trace'] = {'time_ns': time_ns.tolist(), 'preamp_V': preamp.tolist(),
                            'digitized_preamp_V': digitized.tolist(), 'adc_code': code.tolist(),
                            'slow_V': slow.tolist(), 'fast_V': fast.tolist()}
    return result
