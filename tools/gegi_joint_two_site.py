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
NEAR_TIE_RMS_INCREMENT = .25
BOUNDARY_TOLERANCE = 1e-4
NOISE_RMS_V = digital._PROFILE['optional_noise_rms_V']
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


def _interpolators(templates, channel_indices, lateral_support):
    result = []
    for site, supported in zip(templates, lateral_support, strict=True):
        center = RegularGridInterpolator((DEPTH_MM,), site.center_v_per_keV[:, channel_indices, :])
        lateral = None
        if supported:
            lateral = RegularGridInterpolator((LATERAL_FRACTION, LATERAL_FRACTION, LATERAL_DEPTH_MM),
                                              site.lateral_correction_v_per_keV[:, :, :, channel_indices, :])
        result.append((center, lateral))
    return result


def _coordinates(point, lateral_support):
    if lateral_support == (False, False):
        return ((0., 0., point[0]), (0., 0., point[1]))
    if lateral_support == (True, True):
        return point[:-1].reshape(2, 3)
    if lateral_support[0]:
        return (point[:3], (0., 0., point[3]))
    return ((0., 0., point[0]), point[1:4])


def _predictor(templates, energies, channel_indices, lateral_support):
    models = _interpolators(templates, channel_indices, lateral_support)

    def predict(point):
        xyz = _coordinates(point, lateral_support)
        voltage = sum(energy * (center([z])[0] + (correction((x, y, z)) if correction is not None else 0.))
                      for (x, y, z), energy, (center, correction) in zip(xyz, energies, models, strict=True))
        return shifted_samples(voltage, point[-1])

    return predict


def _fit_limits(lateral_support):
    depth = (float(DEPTH_MM[0]), float(DEPTH_MM[-1]))
    fraction = (LATERAL_FRACTION[0], LATERAL_FRACTION[-1])
    limits = [limit for lateral in lateral_support
              for limit in ((fraction, fraction, depth) if lateral else (depth,))]
    return tuple(zip(*limits, SHIFT_LIMIT_NS))


def _parameter_boundaries(point, lateral_support):
    lo, hi = _fit_limits(lateral_support)
    names = [f'{axis}{site}_{unit}' for site, lateral in enumerate(lateral_support, 1)
             for axis, unit in (('x', 'pitch'), ('y', 'pitch'), ('z', 'mm')) if lateral or axis == 'z']
    return {name: ('lower' if x - a <= BOUNDARY_TOLERANCE else
                   'upper' if b - x <= BOUNDARY_TOLERANCE else None)
            for name, x, a, b in zip((*names, 'onset_ns'), point, lo, hi, strict=True)}


def _check_adc(volts):
    if volts.shape != (len(digital.CONTACT_IDS), len(SAMPLE_NS)) or not np.isfinite(volts).all():
        raise ValueError('Expected a finite local ADC voltage window on all 34 contacts')


def _compatibility(volts, prediction, fitted_contacts, slow, cfd, fast):
    measured = remove_quiet_tail(volts)
    predicted = remove_quiet_tail(prediction)
    residual = (measured - predicted) / digital._LSB_V
    peak = np.abs(residual).argmax(axis=1)
    collector_rows = [cid - 1 for cid in cfd]
    slow_keV = np.array(list(slow.values()))
    measured_fast, _, _ = modeled_features(measured, collector_rows, slow_keV)
    predicted_fast, _, _ = modeled_features(predicted, collector_rows, slow_keV)
    _, predicted_cfd, valid = modeled_features(prediction, collector_rows, slow_keV)
    return {
        'fitted_contact_ids': list(fitted_contacts),
        'measured_fast_feature_contact_ids': list(fast),
        'contact_ids': list(digital.CONTACT_IDS),
        'adc_rms_codes': np.sqrt(np.mean(residual**2, axis=1)).tolist(),
        'adc_mean_codes': np.mean(residual, axis=1).tolist(),
        'adc_peak_codes': residual[np.arange(len(peak)), peak].tolist(),
        'adc_peak_time_ns': SAMPLE_NS[peak].tolist(),
        'measured_window_fast_keV_equiv': measured_fast.tolist(),
        'modeled_window_fast_keV_equiv': predicted_fast.tolist(),
        'collector_timing': [
            {'contact_id': cid, 'measured_cfd_ns': time, 'modeled_cfd_ns': float(model) if ok else None,
             'modeled_crossing_valid': bool(ok), 'measured_minus_modeled_ns': float(time - model) if ok else None}
            for (cid, time), model, ok in zip(cfd.items(), predicted_cfd, valid, strict=True)],
    }


def evaluate_waveform_compatibility(pairing, collectors, templates, fit, fitted_contact_ids, *, local_adc_volts):
    """Compare a retained position fit with all 34 channels of its original ADC window.

    The data and prediction each have their three-sample free-decay tail removed.
    Residuals are measured minus modeled in ADC codes. Signed fast integrals
    share the same window and tail treatment. Both guards are included.
    """
    _check_adc(local_adc_volts)
    sites = [templates[site['x_contact_id'], site['y_contact_id']] for site in pairing['sites']]
    energies = [site['energy_keV'] for site in pairing['sites']]
    point = np.asarray(fit['parameters'])
    support = tuple(fit.get('site_lateral_support', (len(point) == 7,) * 2))
    predict = _predictor(sites, energies, slice(None), support)
    return dict(_compatibility(local_adc_volts, predict(point), fitted_contact_ids,
                               *feature_measurement(collectors)),
                parameter_boundaries=_parameter_boundaries(point, support))


def _best_refinement(objective, starts, bounds, scales):
    fits = [least_squares(objective, start, bounds=bounds, x_scale=scales,
                         max_nfev=55, ftol=1e-7, xtol=1e-7, gtol=1e-7) for start in starts]
    best = min(fits, key=lambda result: result.cost)
    sv = np.linalg.svd(best.jac * scales, compute_uv=False)
    rms = math.sqrt(2 * best.cost / len(best.fun))
    best_available = [row for row in fits if math.sqrt(2 * row.cost / len(row.fun)) <= rms + NEAR_TIE_RMS_INCREMENT]
    return best, best_available, {'weighted_residual_rms': rms, 'optimizer_success': bool(best.success),
                  'starts': len(fits), 'optimizer_exhausted_starts': sum(not row.success for row in fits),
                  'scaled_jacobian_singular_values': sv.tolist(),
                  'sampled_near_tie_spread': np.ptp(np.array([row.x for row in best_available]), axis=0).tolist()}


def fit_pairing(pairing, collectors, templates, scales, *, local_adc_volts=None,
                compatibility=False, include_all_channels=False, include_partial_lateral=False):
    """Fit an energy-compatible production pairing from receipt fields or optional local raw volts.

    Volts, when supplied, have 34 contact rows and columns at SAMPLE_NS from the
    measured trigger. The fit removes the estimated quiet tail in that window.
    The caller supplies templates bound to the same field and electronics.
    Compatibility adds all-contact residuals, parameter boundaries and the
    near-ties from sampled starts. The optional waveform_all objective fits
    all contacts in addition to the unchanged local waveform (and feature) fits.
    A partial lateral fit uses an archived grid for one site and keeps the
    other site's x/y at its strip center. It is returned only when requested.
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
    slow_keV = np.array(list(slow.values()))
    fast_expected, cfd_expected = np.array(list(fast.values())), np.array(list(cfd.values()))
    if local_adc_volts is not None:
        _check_adc(local_adc_volts)

    def objective_factory(mode, lateral_support, indices, fit_rows, fast_rows):
        predict = _predictor(model_sites, energies, indices, lateral_support)
        waveform = remove_quiet_tail(local_adc_volts[indices]) if mode != 'features' else None

        def residual(point):
            volts = predict(point)
            if waveform is not None:
                return ((remove_quiet_tail(volts) - waveform) / NOISE_RMS_V).ravel()
            predicted_fast, predicted_cfd, _ = modeled_features(volts, fit_rows, slow_keV)
            fast_residual = (predicted_fast[fast_rows] - fast_expected) / (scales['fast'] * math.sqrt(len(fast_rows)))
            cfd_residual = (predicted_cfd - cfd_expected) / (scales['centered_cfd'] * math.sqrt(len(fit_rows)))
            return np.r_[fast_residual, cfd_residual] * math.sqrt((len(fit_rows)+len(fast_rows))/2)

        return residual, predict

    def positions(point, lateral_support):
        xyz = _coordinates(point, lateral_support)
        return [[ox + x*site.pitch_mm, oy + y*site.pitch_mm, z]
                for (x, y, z), site in zip(xyz, model_sites, strict=True) for ox, oy in [site.origin_mm]]

    def format_fit(fit, near, diagnostics, lateral_support, predict, fit_rows, fitted_contacts):
        _, _, cfd_valid = modeled_features(predict(fit.x), fit_rows, slow_keV)
        output = dict(diagnostics, positions_mm=positions(fit.x, lateral_support), parameters=fit.x.tolist(),
                      modeled_cfd_available=bool(cfd_valid.all()), onset_relative_to_trigger_ns=float(fit.x[-1]))
        if sum(lateral_support) == 1:
            output['site_lateral_support'] = list(lateral_support)
        if compatibility:
            output['parameter_boundaries'] = _parameter_boundaries(fit.x, lateral_support)
            output['sampled_near_tie_rms_increment'] = NEAR_TIE_RMS_INCREMENT
            output['sampled_alternates'] = [
                dict(parameters=row.x.tolist(), positions_mm=positions(row.x, lateral_support),
                     weighted_residual_rms=math.sqrt(2 * row.cost / len(row.fun)),
                     optimizer_success=bool(row.success), parameter_boundaries=_parameter_boundaries(row.x, lateral_support))
                for row in sorted(near, key=lambda result: result.cost) if row is not fit]
            if local_adc_volts is not None:
                predict_all = _predictor(model_sites, energies, slice(None), lateral_support)
                output['compatibility'] = _compatibility(local_adc_volts, predict_all(fit.x), fitted_contacts, slow, cfd, fast)
        return output

    fits = {}
    modes_to_fit = ['features']
    if local_adc_volts is not None:
        modes_to_fit.append('waveform')
        if include_all_channels:
            modes_to_fit.append('waveform_all')
    center_support = (False, False)
    lateral_support = tuple(site.lateral_correction_v_per_keV is not None for site in model_sites)
    for mode in modes_to_fit:
        fitted_contacts = list(digital.CONTACT_IDS) if mode == 'waveform_all' else contacts
        indices = slice(None) if mode == 'waveform_all' else channel_indices
        fit_rows = [fitted_contacts.index(cid) for cid in cfd]
        fast_rows = [fitted_contacts.index(cid) for cid in fast]
        objective, predict = objective_factory(mode, center_support, indices, fit_rows, fast_rows)
        grid = (np.array((z1,z2,tau)) for z1,z2,tau in product((-4., 0., 4.), (-4., 0., 4.), (-15., 5.)))
        starts = sorted(grid, key=lambda point: np.linalg.norm(objective(point)))[:3]
        best, near, diagnostics = _best_refinement(objective, starts, _fit_limits(center_support), np.array([5., 5., 20.]))
        modes = {'center': format_fit(best, near, diagnostics, center_support, predict, fit_rows, fitted_contacts)}
        if all(lateral_support) or (include_partial_lateral and any(lateral_support)):
            objective, predict = objective_factory(mode, lateral_support, indices, fit_rows, fast_rows)
            z1, z2, tau = best.x
            offsets = ((0., 0.), (.24, .24), (-.24, -.24), (.24, -.24), (-.24, .24))
            if all(lateral_support):
                starts = [np.array([x, y, z1, q*x, q*y, z2, tau]) for x, y, q in
                          (*[(x, y, 1) for x, y in offsets], *[(x, y, -1) for x, y in offsets[1:]])]
                scales_fit = np.array([.4, .4, 5., .4, .4, 5., 20.])
                name = 'lateral'
            else:
                starts = [np.array([x, y, z1, z2, tau] if lateral_support[0] else [z1, x, y, z2, tau])
                          for x, y in offsets]
                scales_fit = np.array([.4, .4, 5., 5., 20.] if lateral_support[0] else [5., .4, .4, 5., 20.])
                name = 'partial_lateral'
            best, near, diagnostics = _best_refinement(objective, starts, _fit_limits(lateral_support), scales_fit)
            modes[name] = format_fit(best, near, diagnostics, lateral_support, predict, fit_rows, fitted_contacts)
        fits[mode] = modes
    return {'status': 'fitted', 'contacts': contacts, 'fits': fits}
