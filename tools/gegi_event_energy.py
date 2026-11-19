"""Strip-face slow energy from one reconstructed GeGI ADC trigger."""

import math
from numbers import Real

from gegi_imaging import MIN_COLLECTED_KEV, PAIR_ABS_KEV, PAIR_REL


_CONTACTS = set(range(1, 35))
_GUARDS = {17, 34}
_INVALID_SLOW = {'slow_adc_saturation', 'slow_pileup', 'slow_window_truncated',
                 'slow_plateau_unsettled', 'slow_below_threshold'}
_INVALID_CENSUS = {'step_adc_saturation', 'step_window_truncated'}
_UNINVOLVED_INTERFERENCE = {'slow_adc_saturation', 'slow_pileup', 'slow_window_truncated'}

DEFINITION = {
    'kind': 'gegi_trigger_strip_face_slow_energy_v1',
    'census': 'Positive collecting candidates from the measured, settled per-electrode ADC step.',
    'minimum_collected_keV': MIN_COLLECTED_KEV,
    'channel_qualification': 'Every required strip has a measured uncontaminated slow plateau at or above the existing collection threshold.',
    'unassigned_slow_scope': 'An unassigned clean hit at or above threshold withholds a new total. An already qualified single-strip pair retains its measured energy.',
    'guard_scope': 'Guard collection in the current measured step withholds the strip-face total.',
    'closure_absolute_keV': PAIR_ABS_KEV,
    'closure_relative': PAIR_REL,
    'scope': 'Average the separate X and Y sums after closure. The result measures aggregate energy for one observed ADC trigger.',
}


def _finite(value):
    return isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value)


def estimate_event_energy(event):
    """Measure current-trigger strip energy using readout observables only."""
    step_ids = event.get('step_contact_ids') or []
    channels = event.get('channels') or []
    by_id = {row['contact_id']: row for row in channels}
    if (len(by_id) != len(channels) or not set(by_id) <= _CONTACTS
            or len(set(step_ids)) != len(step_ids) or not set(step_ids) <= _CONTACTS):
        raise ValueError('Trigger energy requires original, distinct GeGI contact IDs')
    guards = sorted(set(step_ids) & _GUARDS)
    x = sorted(cid for cid in step_ids if 1 <= cid <= 16)
    y = sorted(cid for cid in step_ids if 18 <= cid <= 33)
    required = set(x + y)

    slow, missing = {}, []
    for cid in x + y:
        row = by_id.get(cid)
        energy = None if row is None else row.get('slow_energy_keV')
        reasons = ['slow_channel_unavailable'] if row is None else sorted(_INVALID_SLOW & set(row.get('flags', [])))
        if not reasons:
            if not _finite(energy):
                reasons = ['slow_energy_unavailable']
            elif energy < MIN_COLLECTED_KEV:
                reasons = ['slow_below_collection_threshold']
        if reasons:
            missing.append({'contact_id': cid, 'reasons': reasons})
        else:
            slow[cid] = energy

    x_sum = math.fsum(slow[cid] for cid in x) if x and all(cid in slow for cid in x) else None
    y_sum = math.fsum(slow[cid] for cid in y) if y and all(cid in slow for cid in y) else None
    closure = x_sum - y_sum if x_sum is not None and y_sum is not None else None
    tolerance = max(PAIR_ABS_KEV, PAIR_REL * max(x_sum, y_sum)) if closure is not None else None
    closure_passed = abs(closure) <= tolerance if closure is not None else None
    legacy = event.get('slow_energy_keV')
    legacy_single = (len(x) == len(y) == 1 and event.get('contact_ids') == x + y
                     and closure_passed and _finite(legacy) and legacy == (x_sum + y_sum) / 2)
    stray, interference = [], []
    for cid, row in sorted(by_id.items()):
        if cid in required:
            continue
        flags = set(row.get('flags', []))
        if flags & _UNINVOLVED_INTERFERENCE:
            interference.append(cid)
        energy = row.get('slow_energy_keV')
        if cid not in guards and not flags & _INVALID_SLOW and _finite(energy) and energy >= MIN_COLLECTED_KEV:
            stray.append(cid)

    flags = sorted(set(event.get('flags') or []) & _INVALID_CENSUS)
    if guards or 'guard_collection' in (event.get('flags') or []):
        flags.append('guard_collection')
    if not x or not y:
        flags.append('missing_face_strip_census')
    if len(x) == len(y) == 1 and 'strip_energy_mismatch' in (event.get('flags') or []):
        flags.append('strip_step_energy_mismatch')
    if missing:
        flags.append('required_slow_energy_unavailable')
        flags.extend(sorted({reason for row in missing for reason in row['reasons']}))
    if closure_passed is False:
        flags.append('face_energy_mismatch')
    if stray and not legacy_single:
        flags.append('unattributed_slow_hits')

    energy = (x_sum + y_sum) / 2 if not flags else None
    return {'status': 'qualified' if energy is not None else 'unavailable',
            'flags': flags, 'energy_keV': energy, 'x_sum_keV': x_sum, 'y_sum_keV': y_sum,
            'x_contact_ids': x, 'y_contact_ids': y, 'x_count': len(x), 'y_count': len(y),
            'x_usable_count': sum(cid in slow for cid in x), 'y_usable_count': sum(cid in slow for cid in y),
            'guard_contact_ids': guards, 'x_minus_y_keV': closure, 'closure_tolerance_keV': tolerance,
            'closure_passed': closure_passed, 'missing_required_strips': missing,
            'stray_slow_contact_ids': stray, 'uninvolved_slow_interference_contact_ids': interference,
            'retains_legacy_single': bool(legacy_single and energy is not None)}
