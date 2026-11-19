"""Recover nominal trigger activity from one saved all-contact GeGI ADC window."""

import numpy as np

import gegi_digital_readout as digital
import gegi_exposure_stream as stream
import gegi_pulse_stream as pulse


def analyze_window(adc_codes, baseline_v, relative_time_ns, trigger_profile):
    """Evaluate original face thresholds where the full filter input is saved.

    An activity group can touch a window boundary. The rearm and trailing
    quiet indicators count only quiet increments visible within these samples.
    A coincident group is activity evidence, before persistent-step acceptance.
    """
    codes = np.asarray(adc_codes)
    times = np.asarray(relative_time_ns, dtype=float)
    baseline = np.asarray(baseline_v, dtype=float)
    period, average = stream.SAMPLE_PERIOD_NS, pulse._FAST_SAMPLES
    threshold = pulse.trigger_threshold(trigger_profile)
    n_contacts = len(digital.CONTACT_IDS)
    if (times.ndim != 1 or times.size <= average or not np.isfinite(times).all()
            or not np.all(np.diff(times) == period)):
        raise ValueError('ADC window times must follow the saved sample clock')
    if (codes.shape != (n_contacts, len(times)) or codes.dtype.kind not in 'iu'
            or np.any(codes < digital._ADC_MIN) or np.any(codes > digital._ADC_MAX)):
        raise ValueError('ADC window must contain 34 ordered rows of valid integer codes')
    if baseline.shape != (n_contacts,) or not np.isfinite(baseline).all():
        raise ValueError('ADC window requires the original all-contact voltage baseline')

    face_baseline = np.array([baseline[face].sum() for face in pulse._FACES])[:, None]
    face_voltage = stream._face_voltages(codes) - face_baseline
    # Same two increments as the continuous trigger finder. The first two
    # positions in the sidecar lack a full three-sample ADC input.
    increments = face_voltage[:, 1:] - stream._ALPHA*face_voltage[:, :-1]
    change = (increments[:, 1:] + increments[:, :-1]) / (average*pulse._SLOW_GAIN)
    groups = []
    stream._register_groups(groups, average, change, threshold)
    quiet_count, quiet_threshold = pulse._QUIET_SAMPLES, pulse._QUIET_KEV
    quiet = np.max(np.abs(change), axis=0) <= quiet_threshold
    coincidence = np.min(change, axis=0) >= threshold
    records = []
    for start, last, confirmed in groups:
        first_active = start + 1
        first, stop = first_active - average, last - average + 1
        crossings = np.flatnonzero(coincidence[first:stop]) + first_active
        records.append(dict(
            trigger_reference_ns=float(times[start]), first_active_ns=float(times[first_active]),
            last_active_ns=float(times[last]), coincident=confirmed,
            first_coincident_ns=float(times[crossings[0]]) if confirmed else None,
            rearm_visible=bool(first >= quiet_count and quiet[first-quiet_count:first].all()),
            right_quiet_visible=bool(stop+quiet_count <= quiet.size and quiet[stop:stop+quiet_count].all()),
        ))
    return dict(
        time_ns=times[average:].tolist(), x_change_keV=change[0].tolist(), y_change_keV=change[1].tolist(),
        coincidence_threshold_keV=threshold, quiet_threshold_keV=quiet_threshold, quiet_samples=quiet_count,
        sample_period_ns=period, fast_support_samples=average+1,
        saturated_contact_ids=[cid for cid, saturated in zip(digital.CONTACT_IDS, stream._rail(codes).any(axis=1),
                                                              strict=True) if saturated], groups=records,
    )
