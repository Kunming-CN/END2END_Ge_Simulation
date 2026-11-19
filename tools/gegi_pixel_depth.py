"""Apparent GeGI depth from measured ADC collector timing and same-field tables."""

from bisect import bisect_left
from hashlib import sha256
import json
import math
from pathlib import Path
import re
from sys import float_info


KIND = 'gegi_pixel_cfd_depth_calibration_v1'
CALIBRATION_PATH = Path(__file__).with_name('gegi_pixel_depth_calibration.json')
CFD_DEFINITION = 'x_collector_preamp_cfd50_ns - y_collector_preamp_cfd50_ns'
FIELD_KEYS = ('model_sha256', 'field_cache_sha256', 'field_precision_bits')
X_IDS, Y_IDS = range(1, 17), range(18, 34)
UNAVAILABLE = ('insufficient_center_knots', 'interior_center_knots_missing', 'nonmonotonic_center_timing')


def finite(value):
    return type(value) in (int, float) and abs(value) <= float_info.max and math.isfinite(value)


def validate_calibration(calibration):
    """Check the timing convention, pixel census and invertible domains once."""
    if (calibration.get('kind') != KIND or calibration.get('cfd_definition') != CFD_DEFINITION
            or calibration.get('difference_unit') != 'ns' or calibration.get('depth_unit') != 'mm'
            or calibration.get('field_precision_bits') not in (32, 64)):
        raise ValueError('Unsupported GeGI apparent-depth calibration definition')
    for key in (*FIELD_KEYS[:2], 'digital_profile_sha256', 'digital_timing_sha256'):
        if not re.fullmatch('[0-9a-f]{64}', str(calibration.get(key))):
            raise ValueError('Invalid GeGI apparent-depth calibration identity for ' + key)
    depth = calibration['center_depth_grid_mm']
    if (type(depth) is not list or len(depth) < 3 or not all(finite(z) for z in depth)
            or not all(a < b for a, b in zip(depth, depth[1:]))):
        raise ValueError('Invalid GeGI center-depth sampling grid')
    pixels = calibration['pixels']
    if set(pixels) != {f'{x}:{y}' for x in X_IDS for y in Y_IDS}:
        raise ValueError('Apparent-depth calibration must account for all 256 GeGI pixels')
    counted, estimated, local = 0, 0, 0
    for key, raw in pixels.items():
        status, used = raw['status'], raw['usable_knots']
        if type(used) is not int or not 0 <= used <= len(depth):
            raise ValueError('Invalid center-knot census for pixel ' + key)
        if status == 'available':
            z, cfd, direction = (raw[name] for name in ('z_mm', 'cfd_x_minus_y_ns', 'direction'))
            if (len(z) != used or len(cfd) != used or used < 3
                    or not any(z == depth[i:i+used] for i in range(len(depth) - used + 1))
                    or type(direction) is not int or direction not in (-1, 1)
                    or not all(finite(value) for value in cfd)
                    or not all(direction * a < direction * b for a, b in zip(cfd, cfd[1:]))):
                raise ValueError('Invalid strictly monotonic CFD knots for pixel ' + key)
        elif status not in UNAVAILABLE:
            raise ValueError('Invalid apparent-depth status for pixel ' + key)
        evidence = raw.get('off_center_check')
        if evidence is not None:
            n, accepted = evidence['intended'], evidence['estimated']
            if type(n) is not int or type(accepted) is not int or not 0 <= accepted <= n or not n:
                raise ValueError('Invalid apparent-depth off-center census for pixel ' + key)
            counted += n
            estimated += accepted
            local += 1
    validation = calibration['off_center_validation']
    if (counted, estimated, local) != (validation['intended'], validation['estimated'], validation['pixels_checked']):
        raise ValueError('Apparent-depth validation populations do not close')
    return calibration


def load_calibration(path=CALIBRATION_PATH):
    raw = Path(path).read_bytes()
    calibration = validate_calibration(json.loads(raw))
    calibration['calibration_sha256'] = sha256(raw).hexdigest()
    return calibration


def estimate_depth(calibration, x_contact_id, y_contact_id, x_cfd50_ns, y_cfd50_ns, *,
                   source_identity, digital_profile_sha256, digital_timing_sha256):
    """Interpret measured X/Y collector timing as an apparent depth in mm."""
    result = dict(apparent_depth_mm=None, cfd_x_minus_y_ns=None, evidence_level=None)
    if (type(x_contact_id) is not int or x_contact_id not in X_IDS
            or type(y_contact_id) is not int or y_contact_id not in Y_IDS):
        return dict(result, status='invalid_pixel')
    if (digital_profile_sha256 != calibration['digital_profile_sha256']
            or digital_timing_sha256 != calibration['digital_timing_sha256']):
        return dict(result, status='readout_profile_mismatch')
    if not source_identity or any(source_identity.get(key) != calibration[key] for key in FIELD_KEYS):
        return dict(result, status='unconfirmed_field')
    pixel = calibration['pixels'][f'{x_contact_id}:{y_contact_id}']
    if pixel['status'] != 'available':
        return dict(result, status=pixel['status'])
    result['evidence_level'] = ('local_independent_off_center_check' if 'off_center_check' in pixel else
                                'center_calibration_only')
    if not (finite(x_cfd50_ns) and finite(y_cfd50_ns)):
        return dict(result, status='collector_cfd_unavailable')
    difference = x_cfd50_ns - y_cfd50_ns
    if not finite(difference):
        return dict(result, status='collector_cfd_unavailable')
    result['cfd_x_minus_y_ns'] = difference
    direction = pixel['direction']
    observed = direction * difference
    knots = [direction * t for t in pixel['cfd_x_minus_y_ns']]
    if not knots[0] <= observed <= knots[-1]:
        return dict(result, status='outside_calibrated_cfd_range')
    right = bisect_left(knots, observed)
    z = pixel['z_mm']
    if knots[right] == observed:
        estimate = z[right]
    else:
        fraction = (observed - knots[right-1]) / (knots[right] - knots[right-1])
        estimate = z[right-1] + fraction * (z[right] - z[right-1])
    return dict(result, status='estimated', apparent_depth_mm=estimate)
