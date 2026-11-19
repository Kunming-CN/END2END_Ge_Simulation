"""Fit two local GeGI charge templates to measured collector and neighbor signals."""

from dataclasses import dataclass
from itertools import product
import math

import numpy as np
from scipy.interpolate import RegularGridInterpolator
from scipy.optimize import least_squares

import gegi_digital_readout as digital
import gegi_pulse_stream as pulse


TRIGGER_INDEX = 4
SAMPLE_NS = np.arange(-TRIGGER_INDEX, digital._TIMING['gate_ns'][1] // digital._DT + 1) * digital._DT
VOLTAGE_NS = np.arange(0., SAMPLE_NS[-1] + 42.)
DEPTH_MM = np.arange(-5., 6.)
LATERAL_FRACTION = (-.4, 0., .4)
LATERAL_DEPTH_MM = (-5., 0., 5.)
SHIFT_LIMIT_NS = (-40., 20.)
FAST_SAMPLES = pulse._FAST_NS // digital._DT + 1
POLE = math.exp(-digital._DT / digital._TAU)
QUIET = slice(TRIGGER_INDEX + 1 - pulse._QUIET_SAMPLES, TRIGGER_INDEX + 1)
PRIOR_WEIGHT = np.exp(SAMPLE_NS[QUIET] / digital._TAU)
CFD_FREE_DECAY = np.exp(-SAMPLE_NS[TRIGGER_INDEX:] / digital._TAU)
FAST_INTEGRAL_WEIGHT = np.array([.5, *([1.] * (FAST_SAMPLES - 2)), .5]) * digital._DT / pulse._FAST_GAIN
TAIL_QUIET = slice(0,3)
TAIL_WEIGHT = np.exp(SAMPLE_NS[TAIL_QUIET] / digital._TAU)
TAIL_DECAY = np.exp(-SAMPLE_NS / digital._TAU)


@dataclass(frozen=True)
class Template:
    cell: tuple
    origin_mm: tuple
    pitch_mm: float
    center_v_per_keV: np.ndarray
    lateral_correction_v_per_keV: np.ndarray | None = None


def analog_template(payload, channels):
    """Evaluate the saved single-site analog response on a 1 ns model grid."""
    raw = {row['contact_id']: row for row in payload['channel_signals']}
    native = pulse.prepare_native(raw, channels, terminal_complete=True)
    return pulse._sample_pulse(native, VOLTAGE_NS) / payload['injection_energy_keV']


def feature_measurement(collectors):
    """Read measured CFDs and each distinct available signed fast neighbor once."""
    slow, timing, fast = {}, {}, {}
    for row in collectors:
        cid = row['contact_id']
        slow[cid], timing[cid] = row['slow_energy_keV'], row['preamp_cfd50_ns']
        for side in ('low', 'high'):
            neighbor = row[side]
            if neighbor is None or neighbor['fast_keV_equiv'] is None or neighbor['flags']:
                continue
            contact, value = neighbor['contact_id'], neighbor['fast_keV_equiv']
            if contact in fast and fast[contact] != value:
                raise ValueError('Duplicate measured neighbor readings differ')
            fast[contact] = value
    return slow, timing, fast


def modeled_features(voltage, collector_rows, slow_keV):
    """Reproduce the local fast integral and collector CFD gates before ADC rounding."""
    increments = voltage.copy()
    increments[:, 1:] -= POLE * voltage[:, :-1]
    corrected = np.cumsum(increments, axis=1)
    fast = corrected.copy()
    fast[:, 1:] = (corrected[:, 1:] + corrected[:, :-1]) / 2
    gate = fast[:, TRIGGER_INDEX:TRIGGER_INDEX + FAST_SAMPLES] - fast[:, QUIET].mean(axis=1, keepdims=True)
    fast_equiv = gate @ FAST_INTEGRAL_WEIGHT

    trace = voltage[collector_rows]
    baseline = np.mean(trace[:, QUIET] * PRIOR_WEIGHT, axis=1, keepdims=True)
    trace = trace[:, TRIGGER_INDEX:] - baseline * CFD_FREE_DECAY
    level = digital._TIMING['fraction'] * pulse._SLOW_GAIN * slow_keV
    crossings = (trace[:, :-1] < level[:, None]) & (trace[:, 1:] >= level[:, None])
    valid = (trace[:, 0] < level) & (trace[:, -1] >= level) & crossings.any(axis=1)
    left = crossings.shape[1] - 1 - np.argmax(crossings[:, ::-1], axis=1)
    ridx = np.arange(len(collector_rows))
    a, b = trace[ridx, left], trace[ridx, left + 1]
    fraction = np.divide(level - a, b - a, out=np.zeros_like(a), where=valid)
    # Penalize provisional models without a valid crossing; they cannot become fitted outputs.
    time = np.where(valid, digital._DT * (left + fraction), np.where(trace[:, 0] >= level, -20., SAMPLE_NS[-1] + 20.))
    return fast_equiv, time, valid


def shifted_samples(analog, offset_ns):
    time = SAMPLE_NS - offset_ns
    left = np.maximum(np.floor(time).astype(int), 0)
    fraction = np.maximum(time, 0) - left
    return (analog[:, left] * (1 - fraction) + analog[:, left+1] * fraction) * (time >= 0)


def remove_quiet_tail(volts):
    """Subtract a per-contact free-decay tail measured in the first three quiet samples."""
    amplitude = np.mean(volts[:, TAIL_QUIET] * TAIL_WEIGHT, axis=1, keepdims=True)
    return volts-amplitude*TAIL_DECAY


def _interpolators(templates, channel_indices, use_lateral):
    result = []
    for site in templates:
        center = RegularGridInterpolator((DEPTH_MM,), site.center_v_per_keV[:, channel_indices, :])
        lateral = None
        if use_lateral:
            lateral = RegularGridInterpolator((LATERAL_FRACTION, LATERAL_FRACTION, LATERAL_DEPTH_MM),
                                              site.lateral_correction_v_per_keV[:, :, :, channel_indices, :])
        result.append((center, lateral))
    return result


def _best_refinement(objective, starts, bounds, scales):
    fits = [least_squares(objective, start, bounds=bounds, x_scale=scales,
                         max_nfev=55, ftol=1e-7, xtol=1e-7, gtol=1e-7) for start in starts]
    best = min(fits, key=lambda result: result.cost)
    sv = np.linalg.svd(best.jac * scales, compute_uv=False)
    rms = math.sqrt(2 * best.cost / len(best.fun))
    best_available = [row for row in fits if math.sqrt(2 * row.cost / len(row.fun)) <= rms + .25]
    return best, {'weighted_residual_rms': rms, 'optimizer_success': bool(best.success),
                  'starts': len(fits), 'optimizer_exhausted_starts': sum(not row.success for row in fits),
                  'scaled_jacobian_singular_values': sv.tolist(),
                  'sampled_near_tie_spread': np.ptp(np.array([row.x for row in best_available]), axis=0).tolist()}


def fit_pairing(pairing, collectors, templates, scales, *, local_adc_volts=None):
    """Fit an energy-compatible production pairing from receipt fields or optional local raw volts.

    Volts, when supplied, have 34 contact rows and columns at SAMPLE_NS from the
    measured trigger. The fit removes the estimated quiet tail in that window.
    The caller supplies templates bound to the same field and electronics.
    """
    if not pairing['energy_compatible']:
        return {'status': 'energy_incompatible'}
    cells = [(site['x_contact_id'], site['y_contact_id']) for site in pairing['sites']]
    if any(cell not in templates for cell in cells):
        return {'status': 'no_center_template_for_pixel'}
    model_sites = [templates[cell] for cell in cells]
    energies = [site['energy_keV'] for site in pairing['sites']]
    slow, cfd, fast = feature_measurement(collectors)
    if len(cfd) != 4 or any(t is None for t in cfd.values()) or len(fast) < 4:
        return {'status': 'insufficient_collector_cfd_or_fast_data'}
    contacts = sorted(set(cfd) | set(fast))
    channel_indices = np.asarray(contacts) - 1
    fit_rows = [contacts.index(cid) for cid in cfd]
    fast_rows = [contacts.index(cid) for cid in fast]
    slow_keV = np.array(list(slow.values()))
    fast_expected, cfd_expected = np.array(list(fast.values())), np.array(list(cfd.values()))
    waveform = None
    if local_adc_volts is not None:
        if local_adc_volts.shape != (len(digital.CONTACT_IDS), len(SAMPLE_NS)) or not np.isfinite(local_adc_volts).all():
            raise ValueError('Expected a finite local ADC voltage window on all 34 contacts')
        waveform = remove_quiet_tail(local_adc_volts[channel_indices])

    def objective_factory(mode, use_lateral):
        models = _interpolators(model_sites, channel_indices, use_lateral)

        def predict(point):
            xyz = point[:-1].reshape(2, 3) if use_lateral else [[0., 0., z] for z in point[:-1]]
            voltage = sum(energy * (center([z])[0] + (correction((x,y,z)) if use_lateral else 0.))
                          for (x,y,z), energy, (center, correction) in zip(xyz, energies, models, strict=True))
            return shifted_samples(voltage, point[-1])

        def residual(point):
            volts = predict(point)
            if mode == 'waveform':
                return ((remove_quiet_tail(volts) - waveform) / digital._PROFILE['optional_noise_rms_V']).ravel()
            predicted_fast, predicted_cfd, _ = modeled_features(volts, fit_rows, slow_keV)
            fast_residual = (predicted_fast[fast_rows] - fast_expected) / (scales['fast'] * math.sqrt(len(fast_rows)))
            cfd_residual = (predicted_cfd - cfd_expected) / (scales['centered_cfd'] * math.sqrt(len(fit_rows)))
            return np.r_[fast_residual, cfd_residual] * math.sqrt((len(fit_rows)+len(fast_rows))/2)

        return residual, predict

    def format_fit(fit, diagnostics, lateral, predict):
        xyz = fit.x[:-1].reshape(2, 3) if lateral else [[0., 0., z] for z in fit.x[:-1]]
        positions = [[ox + x*site.pitch_mm, oy + y*site.pitch_mm, z]
                     for (x,y,z), site in zip(xyz, model_sites, strict=True) for ox,oy in [site.origin_mm]]
        _, _, cfd_valid = modeled_features(predict(fit.x), fit_rows, slow_keV)
        return dict(diagnostics, positions_mm=positions, parameters=fit.x.tolist(), modeled_cfd_available=bool(cfd_valid.all()),
                    onset_relative_to_trigger_ns=float(fit.x[-1]))

    fits = {}
    for mode in ('features', 'waveform') if waveform is not None else ('features',):
        objective, predict = objective_factory(mode, False)
        grid = (np.array((z1,z2,tau)) for z1,z2,tau in product((-4., 0., 4.), (-4., 0., 4.), (-15., 5.)))
        starts = sorted(grid, key=lambda point: np.linalg.norm(objective(point)))[:3]
        best, diagnostics = _best_refinement(objective, starts, ([-5., -5., SHIFT_LIMIT_NS[0]], [5., 5., SHIFT_LIMIT_NS[1]]),
                                             np.array([5., 5., 20.]))
        modes = {'center': format_fit(best, diagnostics, False, predict)}
        if all(site.lateral_correction_v_per_keV is not None for site in model_sites):
            objective, predict = objective_factory(mode, True)
            z1, z2, tau = best.x
            starts = [np.array([x, y, z1, q*x, q*y, z2, tau]) for x,y,q in
                      ((0.,0.,1), (.24,.24,1), (-.24,-.24,1), (.24,-.24,1), (-.24,.24,1),
                       (.24,.24,-1), (-.24,-.24,-1), (.24,-.24,-1), (-.24,.24,-1))]
            bounds = ([-.4, -.4, -5., -.4, -.4, -5., SHIFT_LIMIT_NS[0]], [.4, .4, 5., .4, .4, 5., SHIFT_LIMIT_NS[1]])
            best, diagnostics = _best_refinement(objective, starts, bounds, np.array([.4,.4,5.,.4,.4,5.,20.]))
            modes['lateral'] = format_fit(best, diagnostics, True, predict)
        fits[mode] = modes
    return {'status': 'fitted', 'contacts': contacts, 'fits': fits}
