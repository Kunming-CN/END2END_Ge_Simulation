"""Nominal GeGI single-site X/Y position from signed adjacent-strip induction.

The neighbor-difference observable and nine-slot convention follow Johnson et al.
(https://pmc.ncbi.nlm.nih.gov/articles/PMC3178965/). The GeGI coefficients come
from known-position simulated injections over the measured scan interval. The
paper used a flood histogram on a different detector to establish its boundaries.
"""
from __future__ import annotations

from bisect import bisect_right
import hashlib
import json
import math
from pathlib import Path
import re


CALIBRATION_KIND = 'gegi_simulated_substrip_calibration_v1'
CALIBRATION_PATH = Path(__file__).with_name('gegi_substrip_calibration.json')
RATIO_DEFINITION = '(higher_coordinate_neighbor_fast_keV_equiv - lower_coordinate_neighbor_fast_keV_equiv) / collector_slow_keV'
CFD_DIFFERENCE_DEFINITION = 'x_collector_preamp_cfd50_ns - y_collector_preamp_cfd50_ns'
SLOT_COUNT = 9


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _increasing(values):
    return all(_finite(v) for v in values) and all(a < b for a, b in zip(values, values[1:]))


def _lookup_slot(value, edges):
    if edges[0] <= value <= edges[-1]:
        return min(bisect_right(edges, value) - 1, len(edges) - 2)
    return None


def _direction(values):
    if _increasing(values):
        return 1
    if _increasing(values[::-1]):
        return -1
    return None


def _bracket(value, knots):
    right = bisect_right(knots, value)
    if right and knots[right - 1] == value:
        return right - 1, right - 1, 0.
    if right == 0 or right == len(knots):
        return None
    left = right - 1
    return left, right, (value - knots[left]) / (knots[right] - knots[left])


def _lerp(a, b, fraction):
    return a + fraction * (b - a)


def encode_ratio(ratio, *, scale, offset):
    """Signed scalar encoding with a caller-supplied scale and integer offset.

    Truncation toward zero acts on the scaled signed ratio before the offset.
    """
    if not _finite(ratio) or not _finite(scale) or scale <= 0 or type(offset) is not int:
        raise ValueError('A finite ratio, positive scale and integer offset are required')
    scaled = scale * ratio
    if not _finite(scaled):
        raise ValueError('Scaled ratio is outside the finite range')
    return math.trunc(scaled) + offset


def lookup_encoded_slot(encoded, edges):
    """Zero-based lookup in ordered integer edges, including the final upper edge."""
    if (type(encoded) is not int or len(edges) != SLOT_COUNT + 1
            or any(type(edge) is not int for edge in edges) or not _increasing(edges)):
        raise ValueError('An integer ratio code and ten increasing integer edges are required')
    return _lookup_slot(encoded, edges)


def validate_calibration(calibration):
    """Validate the on-disk unit, ordering, and provenance contract once."""
    if (not isinstance(calibration, dict) or calibration.get('kind') != CALIBRATION_KIND
            or calibration.get('ratio_definition') != RATIO_DEFINITION
            or calibration.get('position_unit') != 'mm' or calibration.get('slot_count') != SLOT_COUNT):
        raise ValueError('Unsupported GeGI substrip calibration definition')
    for key in ('model_sha256', 'field_cache_sha256', 'digital_profile_sha256'):
        if not re.fullmatch('[0-9a-f]{64}', str(calibration.get(key))):
            raise ValueError('Invalid GeGI substrip calibration identity for ' + key)
    energy = calibration.get('reference_energy_keV')
    if not _finite(energy) or energy <= 0 or calibration.get('field_precision_bits') not in (32, 64):
        raise ValueError('Invalid GeGI substrip injection energy or field precision')
    pairs = calibration.get('sampled_contact_pairs')
    if not isinstance(pairs, list) or not pairs or any(
            not isinstance(p, list) or len(p) != 2 or any(type(cid) is not int or cid <= 0 for cid in p) for p in pairs):
        raise ValueError('Invalid GeGI substrip sampled strip pairs')
    tables = calibration.get('strips')
    if not isinstance(tables, dict) or set(tables) != {str(cid) for pair in pairs for cid in pair}:
        raise ValueError('GeGI substrip tables must match the sampled strip pairs')
    for contact, table in tables.items():
        if not isinstance(table, dict):
            raise ValueError('Invalid GeGI substrip table for contact ' + contact)
        sign = table.get('ratio_direction')
        edges = table.get('oriented_ratio_edges')
        positions = table.get('slot_position_mm')
        center = table.get('strip_center_mm')
        neighbors = table.get('neighbor_contact_ids')
        pitch = table.get('strip_pitch_mm')
        if (type(sign) is not int or sign not in (-1, 1) or not isinstance(edges, list)
                or len(edges) != SLOT_COUNT + 1 or not _increasing(edges)
                or not isinstance(positions, list) or len(positions) != SLOT_COUNT or not _increasing(positions)
                or not _finite(center) or center != positions[SLOT_COUNT // 2]
                or not _finite(pitch) or pitch <= 0 or not isinstance(neighbors, list) or len(neighbors) != 2
                or any(type(cid) is not int or cid <= 0 or cid == int(contact) for cid in neighbors)
                or neighbors[0] == neighbors[1]):
            raise ValueError('Invalid GeGI substrip table for contact ' + contact)
    depth = calibration.get('depth_cfd')
    if depth is not None:
        _validate_depth(depth, tables)
    return calibration


def _validate_depth(depth, tables):
    if (not isinstance(depth, dict) or depth.get('definition') != CFD_DIFFERENCE_DEFINITION
            or depth.get('difference_unit') != 'ns' or depth.get('depth_unit') != 'mm'
            or not re.fullmatch('[0-9a-f]{64}', str(depth.get('timing_sha256')))
            or type(depth.get('cfd_direction')) is not int or depth['cfd_direction'] not in (-1, 1)):
        raise ValueError('Unsupported GeGI CFD depth definition')
    knots, timing, strips = (depth.get(k) for k in ('depth_knots_mm', 'oriented_cfd_knots_ns', 'ratio_edges_by_strip'))
    if (not isinstance(knots, list) or not isinstance(timing, list) or len(knots) < 2
            or len(knots) != len(timing) or not _increasing(knots) or not _increasing(timing)
            or not isinstance(strips, dict) or strips.keys() != tables.keys()):
        raise ValueError('Invalid GeGI CFD depth knots or strips')
    for contact, families in strips.items():
        if not isinstance(families, list) or len(families) != len(knots) or any(
                not isinstance(edges, list) or len(edges) != SLOT_COUNT + 1 or _direction(edges) is None
                for edges in families):
            raise ValueError('Invalid GeGI depth-conditioned table for contact ' + contact)


def load_calibration(path=CALIBRATION_PATH):
    raw = Path(path).read_bytes()
    calibration = validate_calibration(json.loads(raw))
    calibration['calibration_sha256'] = hashlib.sha256(raw).hexdigest()
    return calibration


def _source_status(calibration, source_identity):
    if not source_identity or source_identity.get('model_sha256') != calibration['model_sha256']:
        return 'source_identity_mismatch'
    if all(source_identity.get(k) == calibration[k] for k in ('field_cache_sha256', 'field_precision_bits')):
        return 'matching_saved_fields'
    return 'nominal_transfer'


def compatible_source(calibration, source_identity):
    """The same canonical model is required. Other field states are nominal transfers."""
    return _source_status(calibration, source_identity) != 'source_identity_mismatch'


def substrip_axis_features(collector_id, family, features, geometry):
    """Geometry and signed ratio from readout features only, with nulls for missing inputs."""
    row = {'status': 'collector_unavailable', 'contact_id': collector_id, 'neighbor_contact_ids': None,
           'strip_center_mm': None, 'strip_pitch_mm': None, 'ratio': None, 'slot': None, 'position_mm': None}
    collector = geometry.get(collector_id)
    if (not collector or collector.get('family') != family or collector.get('guard') is not False
            or not _finite(collector.get('strip_center_mm'))):
        return row
    ordered = sorted((c['strip_center_mm'], cid) for cid, c in geometry.items()
                     if c.get('family') == family and c.get('guard') is False and _finite(c.get('strip_center_mm')))
    center = collector['strip_center_mm']
    index = ordered.index((center, collector_id))
    row.update(strip_center_mm=center, status='missing_adjacent_strip')
    if index == 0 or index == len(ordered) - 1:
        return row
    lower, higher = ordered[index - 1], ordered[index + 1]
    if not lower[0] < center < higher[0] or {lower[1], higher[1]} != {collector_id - 1, collector_id + 1}:
        return row
    row.update(neighbor_contact_ids=[lower[1], higher[1]], strip_pitch_mm=(higher[0] - lower[0]) / 2,
               status='neighbor_or_collector_signal_unavailable')
    fast_left = features.get(lower[1], {}).get('fast_signal_keV_equiv')
    fast_right = features.get(higher[1], {}).get('fast_signal_keV_equiv')
    slow = features.get(collector_id, {}).get('slow_energy_keV')
    if all(_finite(v) for v in (fast_left, fast_right, slow)) and slow > 0:
        ratio = (fast_right - fast_left) / slow
        if _finite(ratio):
            row.update(ratio=ratio, status='features_available')
    return row


def _depth_estimate(calibration, pair, features, digital_result, source_status, profile_matches):
    x, y = (features.get(cid, {}).get('preamp_cfd50_ns') for cid in pair)
    x, y = (value if _finite(value) else None for value in (x, y))
    delta = x - y if x is not None and y is not None else None
    result = {'status': 'collector_cfd_unavailable', 'cfd_x_ns': x, 'cfd_y_ns': y,
              'cfd_difference_ns': delta, 'position_mm': None}
    definition = calibration.get('depth_cfd')
    if delta is None:
        return result
    if definition is None:
        result['status'] = 'depth_calibration_unavailable'
    elif source_status == 'source_identity_mismatch':
        result['status'] = source_status
    elif not profile_matches or digital_result.get('timing_sha256') != definition['timing_sha256']:
        result['status'] = 'digital_timing_profile_mismatch'
    else:
        match = _bracket(delta * definition['cfd_direction'], definition['oriented_cfd_knots_ns'])
        if match is None:
            result['status'] = 'cfd_difference_outside_calibration'
        else:
            lo, hi, fraction = match
            knots = definition['depth_knots_mm']
            result.update(status='estimated', position_mm=_lerp(knots[lo], knots[hi], fraction))
    return result


def _apply_table(row, table, source_status, profile_matches, conditioned):
    if row['status'] != 'features_available':
        return row
    if table is None:
        row['status'] = 'uncalibrated_strip'
    elif source_status == 'source_identity_mismatch':
        row['status'] = source_status
    elif not profile_matches:
        row['status'] = 'digital_profile_mismatch'
    elif (table['neighbor_contact_ids'] != row['neighbor_contact_ids']
          or not math.isclose(table['strip_center_mm'], row['strip_center_mm'], abs_tol=1e-6, rel_tol=0)
          or not math.isclose(table['strip_pitch_mm'], row['strip_pitch_mm'], abs_tol=1e-6, rel_tol=0)):
        row['status'] = 'strip_geometry_mismatch'
    else:
        edges, direction = table['oriented_ratio_edges'], table['ratio_direction']
        if conditioned is not None:
            depth, definition = conditioned
            if depth['status'] != 'estimated':
                row['status'] = 'depth_condition_unavailable'
                return row
            match = _bracket(depth['position_mm'], definition['depth_knots_mm'])
            lo, hi, fraction = match
            families = definition['ratio_edges_by_strip'][str(row['contact_id'])]
            direction = _direction(families[lo])
            if direction != _direction(families[hi]):
                row['status'] = 'ambiguous_depth_polarity'
                return row
            edges = [direction * _lerp(a, b, fraction) for a, b in zip(families[lo], families[hi])]
        slot = _lookup_slot(direction * row['ratio'], edges)
        if slot is None:
            row['status'] = 'ratio_outside_calibration'
        else:
            row.update(status='estimated', slot=slot, position_mm=table['slot_position_mm'][slot])
    return row


def infer_position(calibration, x_contact_id, y_contact_id, digital_result, channel_geometry, *,
                   source_identity=None, mode='pooled'):
    """Estimate axes using pooled tables or tables conditioned on measured preamp CFD."""
    if mode not in ('pooled', 'cfd_conditioned'):
        raise ValueError('Choose pooled or cfd_conditioned GeGI substrip position')
    geometry = {c['id']: c for c in channel_geometry}
    features = {c['contact_id']: c for c in (digital_result.get('channels') or [])}
    source_status = _source_status(calibration, source_identity)
    profile_matches = digital_result.get('profile_sha256') == calibration['digital_profile_sha256']
    pair = [x_contact_id, y_contact_id]
    rows = {axis: substrip_axis_features(collector, axis.upper(), features, geometry)
            for collector, axis in zip(pair, ('x', 'y'))}
    depth_pair = [r['contact_id'] if r['strip_center_mm'] is not None else None for r in rows.values()]
    depth = _depth_estimate(calibration, depth_pair, features, digital_result, source_status, profile_matches)
    conditioned = (depth, calibration.get('depth_cfd')) if mode == 'cfd_conditioned' else None
    result = {'calibration_kind': calibration['kind'], 'calibration_sha256': calibration.get('calibration_sha256'),
              'calibration_reference_energy_keV': calibration['reference_energy_keV'],
              'mode': mode, 'depth': depth,
              'calibration_source_status': source_status,
              'calibration_pair_coverage': ('simulated_pair' if pair in calibration['sampled_contact_pairs']
                                            else 'unverified_cross_strip_transfer' if None not in pair else None)}
    for axis, row in rows.items():
        table = calibration['strips'].get(str(row['contact_id']))
        result[axis] = _apply_table(row, table, source_status, profile_matches, conditioned)
    count = sum(result[axis]['status'] == 'estimated' for axis in ('x', 'y'))
    result['status'] = ('unavailable', 'partial', 'estimated')[count]
    return result
