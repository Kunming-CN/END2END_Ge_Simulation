"""Measure persistent subthreshold strip signals in saved GeGI preamplifier samples."""

import math

import numpy as np

import gegi_digital_readout as digital
from gegi_imaging import MIN_COLLECTED_KEV
from gegi_pulse_stream import _QUIET_SAMPLES


SIGNIFICANCE = 5.
GUARDS = {17, 34}
ADC_SIGMA_V = math.hypot(digital._PROFILE['optional_noise_rms_V'], digital._LSB_V / math.sqrt(12))
TAIL_GAIN = digital._VOLTS_PER_KEV * digital._TAU / (digital._TAU - digital._BANDWIDTH_TAU)


def analyze_weak_strips(codes, times, baseline_v, rise_ns, selected):
    """Use the original late-step gates and expose every eligible strip's measurement."""
    codes, times, baseline = np.asarray(codes), np.asarray(times), np.asarray(baseline_v)
    if (codes.shape != (34, 29) or codes.dtype.kind not in 'iu'
            or np.any(codes < digital._ADC_MIN) or np.any(codes > digital._ADC_MAX)
            or not np.array_equal(times, np.arange(-80, 481, digital._DT))
            or baseline.shape != (34,) or not np.isfinite(baseline).all()
            or not math.isfinite(rise_ns) or rise_ns < 0):
        raise ValueError('Weak-strip measurement requires the original ADC window, baseline and rise end.')
    quiet = np.arange(_QUIET_SAMPLES)
    late = np.arange(len(times)-5, len(times))
    result = dict(status='insufficient_post_rise_settling', weak_strips=[], contacts=[],
                  significance=SIGNIFICANCE, collection_threshold_keV=MIN_COLLECTED_KEV)
    if times[late[0]] < rise_ns + 2*_QUIET_SAMPLES*digital._DT:
        return result
    weights = np.exp(times/digital._TAU)
    values = (codes*digital._LSB_V-baseline[:, None])*weights[None, :]/TAIL_GAIN
    sigma = ADC_SIGMA_V/TAIL_GAIN
    rms = sigma * math.hypot(np.linalg.norm(weights[quiet])/len(quiet), np.linalg.norm(weights[late])/len(late))
    edge_rms = sigma * math.hypot(np.linalg.norm(weights[late[:2]])/2, np.linalg.norm(weights[late[-2:]])/2)
    steps = values[:, late].mean(axis=1) - values[:, quiet].mean(axis=1)
    changes = values[:, late[-2:]].mean(axis=1) - values[:, late[:2]].mean(axis=1)
    threshold, limit = SIGNIFICANCE*rms, SIGNIFICANCE*edge_rms
    result.update(status='measured', sigma_keV_equiv=float(rms), threshold_keV_equiv=float(threshold),
                  late_difference_limit_keV_equiv=float(limit))
    for i, (step, drift) in enumerate(zip(steps, changes, strict=True)):
        cid = i+1
        if cid in selected or cid in GUARDS:
            continue
        saturated = bool(codes[i].min() <= digital._ADC_MIN or codes[i].max() >= digital._ADC_MAX)
        persistent = bool(abs(drift) <= limit)
        detected = bool(threshold <= step < MIN_COLLECTED_KEV and persistent and not saturated)
        row = dict(contact_id=cid, step_keV_equiv=float(step), late_difference_keV_equiv=float(drift),
                   sigma_multiple=float(step/rms))
        result['contacts'].append(dict(row, saturated=saturated, persistent=persistent, detected=detected))
        if detected:
            result['weak_strips'].append(row)
    return result
