"""Test single-point GeGI signed neighbor features around the two event-2950 gaps."""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from scipy import __version__ as scipy_version
from scipy.spatial import Delaunay, QhullError

import gegi_digital_readout as digital
from gegi_digital_pairs import slow_collectors
from gegi_imaging import MIN_COLLECTED_KEV, PAIR_ABS_KEV, PAIR_REL
from gegi_substrip import RATIO_DEFINITION, substrip_axis_features


ROOT = Path(__file__).resolve().parents[1]
AREA = ROOT / '.local/gegi-edge-position'
OLD = ROOT / '.local/gegi-digital-v1/two-site-position'
EVENT_SHA = 'f36b0af5dafec19e9897808ad2e67c980e6fbb4b97a847ee88411cc129814b1f'
OLD_DONE_SHA = 'e239be0a97e7b0b99bc85842db9ee22b200bb0f43735fe743b9c0dc3dc2c708d'
CAPTURE_DONE_SHA = '742770a24d0756b58fa075adedf05882c8d141c4bcce9e79c0a7576686f255a3'
PLANS = (
    {'edge_id': '6-27', 'site': 'A', 'original_pair_ids': [6, 27], 'neighbor_pair_ids': [6, 28], 'axis': 1,
     'direction': 1},
    {'edge_id': '8-28', 'site': 'B', 'original_pair_ids': [8, 28], 'neighbor_pair_ids': [7, 28], 'axis': 0,
     'direction': -1},
)
WIDTH_MM, PITCH_MM = 4.687480624253117, 4.937480624253117
INNER_METAL_EDGE = WIDTH_MM / (2 * PITCH_MM)
OUTER_METAL_EDGE = 1 - INNER_METAL_EDGE
FIT_DEPTHS = (-5, 0, 5)
FIT_OFFSETS = (.45, INNER_METAL_EDGE, .49, .50, .51, OUTER_METAL_EDGE, .55)
HOLDOUT_DEPTHS = (-2.5, 2.5)
HOLDOUT_OFFSETS = (.425, .462, .486, .506, .519, .539)
SCALE = np.asarray((.10, 20.))
EPSILON = 1e-12
METHODS = ('measured_strip_center', 'gap_midpoint_prior', 'frozen_inner', 'extended_fast', 'extended_cfd_only')


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encoded(data):
    return json.dumps(data, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


class Inputs:
    def __init__(self):
        self.hashes = {}

    def read(self, path, expected=None):
        path = path.resolve()
        raw = path.read_bytes()
        actual = digest(raw)
        ref = path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path.as_posix()
        require(expected is None or actual == expected, 'Saved byte identity changed: ' + ref)
        self.hashes[ref] = actual
        return json.loads(raw)

    def payload(self, folder, item, identity):
        path = folder / item['record_ref']
        require(path.resolve().is_relative_to(folder.resolve()), 'Saved point reference escaped its capture')
        record = self.read(path, item['record_sha256'])
        require(record['identity_sha256'] == identity and record['payload']['position_mm'] == item['position_mm'],
                'Incompatible checkpoint or saved injection coordinate')
        return record['payload']


def edge_geometry(channels):
    geometry = {c['id']: c for c in channels}
    out = {}
    for source in PLANS:
        edge = dict(source)
        original, neighbor = edge['original_pair_ids'], edge['neighbor_pair_ids']
        axis, direction = edge['axis'], edge['direction']
        centers = [geometry[c]['strip_center_mm'] for c in original]
        nc = geometry[neighbor[axis]]['strip_center_mm']
        require(math.isclose(nc - centers[axis], direction * PITCH_MM, abs_tol=1e-12, rel_tol=0)
                and original[1-axis] == neighbor[1-axis], 'Targeted strip gap geometry changed')
        edge.update(original_strip_centers_mm=centers, neighbor_center_mm=nc,
                    pitch_mm=PITCH_MM, strip_width_mm=WIDTH_MM, modeled_gap_mm=PITCH_MM-WIDTH_MM,
                    gap_midpoint_mm=(centers[axis]+nc)/2,
                    original_metal_to_gap_offset_pitch_fraction=INNER_METAL_EDGE,
                    gap_to_neighbor_metal_offset_pitch_fraction=OUTER_METAL_EDGE,
                    original_metal_edge_mm=centers[axis] + direction * WIDTH_MM / 2,
                    neighbor_metal_edge_mm=nc - direction * WIDTH_MM / 2,
                    fixed_other_coordinate_mm=centers[1-axis],
                    axis_name='xy'[axis], original_strips=[geometry[x]['name'] for x in original],
                    neighbor_strips=[geometry[x]['name'] for x in neighbor])
        out[edge['edge_id']] = edge
    return out


def check_capture(request, done, edges):
    expected = {(edge, role, offset, z)
                for edge in edges for role, offsets, depths in
                (('fit', FIT_OFFSETS, FIT_DEPTHS), ('holdout', HOLDOUT_OFFSETS, HOLDOUT_DEPTHS))
                for offset in offsets for z in depths}
    actual = []
    for item in request['points']:
        edge = edges[item['edge_id']]
        u = item['offset_pitch_fraction_toward_neighbor']
        axis, direction = edge['axis'], edge['direction']
        xyz = item['position_mm']
        require(item['contact_ids'] == edge['original_pair_ids']
                and abs(xyz[axis] - edge['original_strip_centers_mm'][axis] - direction * u * PITCH_MM) < 1e-10
                and abs(xyz[1-axis] - edge['fixed_other_coordinate_mm']) < 1e-10,
                'Capture moved from the prescribed edge geometry')
        actual.append((item['edge_id'], item['role'], u, xyz[2]))
    require(len(actual) == len(expected) == len(done['records'])
            and all(any(a[:2] == b[:2] and abs(a[2]-b[2]) < 1e-10 and a[3] == b[3] for b in expected) for a in actual)
            and len({tuple(p['position_mm']) for p in request['points']}) == len(actual),
            'Capture fit or holdout roster differs from the frozen design')
    for a, b in zip(request['points'], done['records'], strict=True):
        require(all(a[k] == b[k] for k in ('edge_id', 'role', 'position_mm', 'contact_ids',
                                          'offset_pitch_fraction_toward_neighbor')),
                'Checkpoint order or training role changed')


def frozen_inner(inputs, request, old, old_done, old_request, edges):
    expected = {(edge, u, z) for edge in edges for u in (0., .4) for z in FIT_DEPTHS}
    seen = set()
    records = sorted(request['reused_reference_records'],
                     key=lambda r: (r['edge_id'], r['position_mm'][2], r['offset_pitch_fraction_toward_neighbor']))
    for row in records:
        edge = edges[row['edge_id']]
        axis, direction = edge['axis'], edge['direction']
        u, position = row['offset_pitch_fraction_toward_neighbor'], row['position_mm']
        key = edge['edge_id'], u, position[2]
        binding = row['reference']
        ref, sha = binding['ref'], binding['sha256']
        path = (ROOT / ref).resolve()
        identity = old_request['source_bank_identity']['sha256'] if u == 0 else old_done['request_sha256']
        require(key in expected and key not in seen and row['role'] == 'fit'
                and row['contact_ids'] == edge['original_pair_ids'] and row['record_identity_sha256'] == identity
                and position[1-axis] == edge['fixed_other_coordinate_mm']
                and abs(position[axis] - edge['original_strip_centers_mm'][axis] - direction * u * PITCH_MM) < 1e-10
                and path.is_relative_to(ROOT) and old['input_reference_hashes'][ref] == sha,
                'Reused inner node differs from the frozen same-field fit roster')
        record = inputs.read(path, sha)
        payload = record['payload']
        require(record['identity_sha256'] == identity and payload['position_mm'] == position
                and payload['contact_ids'] == row['contact_ids'], 'Inner waveform checkpoint identity changed')
        seen.add(key)
        yield edge, ref, payload
    require(seen == expected, 'Missing prescribed frozen inner fit nodes')


def endpoint_census(payload, geometry, edge, energy):
    endpoints = payload.get('endpoints') or []
    complete = len(endpoints) == 2 and all(e['status'] == 'contact' and e['step_limit_reached'] is False
                                             and e['contact_ids'] for e in endpoints)
    ids = sorted({contact for endpoint in endpoints for contact in endpoint.get('contact_ids', [])})
    waveforms = payload.get('channel_signals')
    endpoint = {'terminal_complete': complete, 'terminal_contact_ids': ids, 'status': payload['status'],
                'carrier_terminal': [{k: e[k] for k in ('species', 'status', 'contact_ids', 'step_limit_reached')}
                                     for e in endpoints], 'verified_shared_charge': None,
                'terminal_contact_status': 'excluded_geometry' if payload['status'] == 'excluded_geometry'
                else 'incomplete_collection'}
    if not complete:
        return endpoint
    if any(len(e['contact_ids']) != 1 for e in endpoints):
        endpoint['terminal_contact_status'] = 'ambiguous_terminal_contact'
    elif any(geometry[c]['guard'] for c in ids):
        endpoint['terminal_contact_status'] = 'guard_collection'
    elif ids == edge['original_pair_ids']:
        endpoint['terminal_contact_status'] = 'retained_original_pair'
    elif ids == edge['neighbor_pair_ids']:
        endpoint['terminal_contact_status'] = 'migrated_to_target_neighbor'
    else:
        endpoint['terminal_contact_status'] = 'other_terminal_pair'
    if waveforms:
        charges = {s['contact_id']: s['signed_induced_keV'][-1] * geometry[s['contact_id']]['wiring_factor']
                   for s in waveforms}
        faces = [[charges[c] for c in charges if geometry[c]['family'] == face] for face in 'XY']
        # For these fixed single-cloud start points, complete terminal samples only.
        conserved = all(math.isclose(math.fsum(face), energy, abs_tol=.001, rel_tol=0) for face in faces)
        endpoint['terminal_charge_face_conserved'] = conserved
        endpoint['terminal_positive_strips'] = [[c for c, q in charges.items()
                                                if geometry[c]['family'] == face and not geometry[c]['guard']
                                                and q >= MIN_COLLECTED_KEV] for face in 'XY']
        if conserved and not any(len(e['contact_ids']) != 1 for e in endpoints):
            endpoint['verified_shared_charge'] = any(len(strip) >= 2 for strip in endpoint['terminal_positive_strips'])
    return endpoint


def measure(payload, channels, geometry, edge, energy):
    endpoint = endpoint_census(payload, geometry, edge, energy)
    measured = {'readout_status': 'native_signals_unavailable', 'measured_pair_ids': None,
                'strip_centers_mm': [None, None], 'slow_collecting_ids': [], 'guard_slow_ids': [],
                'invalid_slow_ids': [], 'normalized_toward_fast_ratio': None, 'cfd_x_minus_y_ns': None,
                'calibrated_capture_support': False}
    signals = payload.get('channel_signals')
    if not signals:
        return endpoint, measured
    require(len(signals) == 34 and payload['injection_energy_keV'] == energy, 'Native signal coverage or energy changed')
    replay = digital.digital_event({s['contact_id']: s for s in signals}, channels,
                                   terminal_complete=endpoint['terminal_complete'])
    hits, invalid = slow_collectors(replay)
    measured.update(slow_collecting_ids=sorted(hits), invalid_slow_ids=invalid,
                    guard_slow_ids=sorted(cid for cid in hits if geometry[cid]['guard']),
                    calibrated_capture_support=bool(replay['window']['terminal_contacts_verified']))
    face_hits = [sorted(c for c in hits if geometry[c]['family'] == face and not geometry[c]['guard']) for face in 'XY']
    for ax, ids in enumerate(face_hits):
        fam = 'XY'[ax]
        if len(ids) == 1 and not any(geometry[c]['family'] == fam
                                     for c in measured['guard_slow_ids'] + invalid):
            measured['strip_centers_mm'][ax] = geometry[ids[0]]['strip_center_mm']
    if measured['guard_slow_ids']:
        measured['readout_status'] = 'guard_slow_collection'
    elif invalid:
        measured['readout_status'] = 'unknown_slow_channels'
    elif not all(len(ids) == 1 for ids in face_hits):
        measured['readout_status'] = ('multiple_positive_slow_strips' if any(len(ids) > 1 for ids in face_hits)
                                      else 'missing_slow_collecting_face')
    else:
        pair = [ids[0] for ids in face_hits]
        if abs(hits[pair[0]] - hits[pair[1]]) > max(PAIR_ABS_KEV, PAIR_REL * max(hits[c] for c in pair)):
            measured['readout_status'] = 'slow_face_energy_mismatch'
        else:
            measured.update(readout_status='single_slow_strip_per_face', measured_pair_ids=pair,
                            slow_energy_per_face_keV=[hits[i] for i in pair])
    # Features are chosen using the observed pair, never the requested capture pixel.
    return endpoint, {**measured, '_features': {r['contact_id']: r for r in replay['channels']}}


def extract_features(observation, geometry, edge_by_pair):
    measured = observation.copy()
    rows = measured.pop('_features', {})
    pair = tuple(measured['measured_pair_ids'] or ())
    edge = edge_by_pair.get(pair)
    if edge is None:
        return measured, None
    axis, direction = edge['axis'], edge['direction']
    ratio = substrip_axis_features(pair[axis], 'XY'[axis], rows, geometry)
    cfd = [rows[c]['preamp_cfd50_ns'] for c in pair]
    measured['selected_edge_id'] = edge['edge_id']
    measured['signed_fast_neighbor_contact_ids'] = ratio['neighbor_contact_ids']
    if ratio['neighbor_contact_ids'] is not None:
        measured['signed_fast_neighbors_low_high_keV_equiv'] = [rows[c]['fast_signal_keV_equiv']
                                                                 for c in ratio['neighbor_contact_ids']]
    measured['normalized_toward_fast_ratio'] = None if ratio['ratio'] is None else direction * ratio['ratio']
    measured['cfd_x_minus_y_ns'] = cfd[0]-cfd[1] if None not in cfd else None
    return measured, pair


def feature_vector(measured):
    values = (measured['normalized_toward_fast_ratio'], measured['cfd_x_minus_y_ns'])
    return np.asarray(values) / SCALE if None not in values else None


def training_points(rows):
    groups = defaultdict(list)
    for row in rows:
        if row['usable_for_fit']:
            groups[tuple(row['readout']['measured_pair_ids'])].append(row)
    return groups


def build_fit(rows):
    fits = {}
    diagnostics = {}
    for pair, group in sorted(training_points(rows).items()):
        positions = defaultdict(list)
        for row in group:
            positions[tuple(feature_vector(row['readout']))].append(row['true_target_mm'])
        conflicting = sum(max(v)-min(v) > 1e-10 for v in positions.values())
        usable = [(x, v[0]) for x, v in sorted(positions.items()) if max(v)-min(v) <= 1e-10]
        points = np.asarray([x for x, _ in usable], dtype=float)
        outputs = np.asarray([y for _, y in usable], dtype=float)
        timing = np.array([r['readout']['cfd_x_minus_y_ns'] for r in group])
        values = np.array([r['true_target_mm'] for r in group])
        cfd = None
        if len(timing) >= 2 and np.ptp(timing) > EPSILON:
            centered = timing - timing.mean()
            slope = np.dot(centered, values-values.mean()) / np.dot(centered, centered)
            cfd = {'minimum_ns': float(timing.min()), 'maximum_ns': float(timing.max()),
                   'center_ns': float(timing.mean()), 'intercept_mm_at_center': float(values.mean()),
                   'slope_mm_per_ns': float(slope)}
        fit = None
        if len(usable) >= 3 and np.linalg.matrix_rank(points-points.mean(axis=0)) == 2:
            try:
                fit = Delaunay(points)
            except QhullError:
                pass
        fits[pair] = (fit, outputs, cfd)
        key = '-'.join(map(str, pair))
        diagnostics[key] = {'measured_pair_ids': pair, 'admitted_training_points': len(group),
                            'nonconflicting_feature_nodes': len(usable), 'conflicting_feature_nodes': conflicting,
                            'feature_nodes_scaled': points.tolist(), 'target_coordinates_mm': outputs.tolist(),
                            'inverse_triangles': fit.simplices.tolist() if fit is not None else [],
                            'timing_only': cfd}
    return fits, diagnostics


def estimate(pair, observation, models, *, timing_only=False):
    if pair is None or pair not in models:
        return {'position_mm': None, 'status': 'measured_pair_unsupported'}
    if not observation['calibrated_capture_support']:
        return {'position_mm': None, 'status': 'native_collection_unverified'}
    fit, outputs, timing = models[pair]
    if timing_only:
        cfd = observation['cfd_x_minus_y_ns']
        if timing is None or cfd is None or not timing['minimum_ns'] <= cfd <= timing['maximum_ns']:
            return {'position_mm': None, 'status': 'cfd_outside_calibrated_support'}
        position = timing['intercept_mm_at_center'] + timing['slope_mm_per_ns'] * (cfd-timing['center_ns'])
        # A timing-only linear trend is also constrained to the training physical interval.
        if len(outputs) and not outputs.min()-EPSILON <= position <= outputs.max()+EPSILON:
            return {'position_mm': None, 'status': 'timing_prediction_outside_trained_position_interval'}
        return {'position_mm': position, 'status': 'estimated'}
    features = feature_vector(observation)
    if fit is None or features is None:
        return {'position_mm': None, 'status': 'fast_or_cfd_unavailable'}
    index = int(fit.find_simplex(features, tol=EPSILON))
    if index < 0:
        return {'position_mm': None, 'status': 'outside_measured_feature_hull'}
    transformation = fit.transform[index]
    weights = transformation[:2] @ (features-transformation[2])
    weights = np.r_[weights, 1-weights.sum()]
    if min(weights) < -EPSILON:
        return {'position_mm': None, 'status': 'outside_measured_feature_hull'}
    weights = np.clip(weights, 0, None)
    nodes = fit.simplices[index]
    values = outputs[nodes]
    gradient = ((values[:2]-values[2]) @ transformation[:2]) / SCALE
    return {'position_mm': float((weights @ values)/weights.sum()), 'status': 'estimated',
            'prediction_gradient_mm_per_ratio_and_ns': gradient.tolist(),
            'local_normalized_condition_number': float(np.linalg.cond(transformation[:2])),
            'nearest_training_feature_distance_scaled': float(np.min(np.linalg.norm(fit.points-features, axis=1)))}


def observe(payload, ref, role, edge, channels, geometry, edge_by_pair, energy):
    endpoints, observation = measure(payload, channels, geometry, edge, energy)
    measured, pair = extract_features(observation, geometry, edge_by_pair)
    xyz = payload['position_mm']
    axis = edge['axis']
    offsets = [(v-c)/PITCH_MM for v, c in zip(xyz, edge['original_strip_centers_mm'])]
    u = edge['direction'] * offsets[axis]
    region = ('original_metal_projection' if u < INNER_METAL_EDGE else
              'neighbor_metal_projection' if u > OUTER_METAL_EDGE else 'projected_gap')
    return {
        'record_ref': ref, 'role': role, 'edge_id': edge['edge_id'], 'site': edge['site'], 'target_axis': edge['axis_name'],
        'position_mm': xyz, 'true_target_mm': xyz[axis], 'signed_xy_offsets_from_original_centers_pitch': offsets,
        'offset_pitch_fraction_toward_neighbor': u, 'projected_geometry': region, 'endpoints': endpoints,
        'readout': measured,
        'usable_for_fit': bool(endpoints['terminal_complete'] and pair is not None
                              and measured['selected_edge_id'] == edge['edge_id'] and feature_vector(measured) is not None),
    }, pair


def errors(rows, method):
    vals = [r['predictions'][method]['position_mm']-r['true_target_mm'] for r in rows
            if r['predictions'][method]['position_mm'] is not None]
    n = len(vals)
    return {'evaluated': n, 'denominator': len(rows), 'abstained': len(rows)-n,
            'rms_mm': math.sqrt(math.fsum(a*a for a in vals)/n) if n else None,
            'mae_mm': math.fsum(abs(a) for a in vals)/n if n else None,
            'bias_mm': math.fsum(vals)/n if n else None,
            'max_abs_mm': max(map(abs, vals)) if n else None}


def summarize(rows):
    result = []
    for site in ('all', 'A', 'B'):
        group = [r for r in rows if site == 'all' or r['site'] == site]
        common = [r for r in group if all(r['predictions'][m]['position_mm'] is not None
                                          for m in ('frozen_inner', 'extended_fast', 'measured_strip_center'))]
        paired = [r for r in group if all(r['predictions'][m]['position_mm'] is not None
                                          for m in ('extended_fast', 'extended_cfd_only', 'measured_strip_center'))]
        extended = [r for r in group if r['predictions']['extended_fast']['position_mm'] is not None]
        result.append({
            'site': site, 'n': len(group),
            'endpoint_counts': dict(Counter(r['endpoints']['terminal_contact_status'] for r in group)),
            'readout_counts': dict(Counter(r['readout']['readout_status'] for r in group)),
            'projected_geometry_counts': dict(Counter(r['projected_geometry'] for r in group)),
            'sharing_counts': dict(Counter(str(r['endpoints']['verified_shared_charge']).lower() for r in group)),
            'methods': {m: errors(group, m) for m in METHODS},
            'fallback': {m: errors(group, m) for m in ('inner_or_measured_center', 'extended_or_measured_center')},
            'inner_extended_common_support': {m: errors(common, m) for m in METHODS if m != 'extended_cfd_only'},
            'extended_fast_cfd_common_support': {m: errors(paired, m) for m in
                                                 ('extended_fast', 'extended_cfd_only', 'measured_strip_center', 'gap_midpoint_prior')},
            'extended_support_comparators': {m: errors(extended, m) for m in
                                             ('extended_fast', 'measured_strip_center', 'gap_midpoint_prior')},
            'predictor_status_counts': {m: dict(Counter(r['predictions'][m]['status'] for r in group))
                                        for m in ('frozen_inner', 'extended_fast', 'extended_cfd_only')},
        })
    return result


def site_context(previous, edges):
    event = previous['events']['2950']
    out = []
    for index, edge in enumerate(edges.values()):
        require(event['pixels'][index] == edge['original_pair_ids'], 'Frozen event-2950 site binding changed')
        xyz = event['simulation_truth_energy_centroids_mm'][index]
        offsets = [(q-c)/PITCH_MM for q, c in zip(xyz, edge['original_strip_centers_mm'])]
        out.append({'site': edge['site'], 'edge_id': edge['edge_id'], 'truth_energy_centroid_mm': xyz,
                    'truth_centroid_signed_xy_offsets_pitch': offsets,
                    'truth_centroid_offset_toward_neighbor_pitch': offsets[edge['axis']]*edge['direction'],
                    'old_waveform_fit_mm': event['fits']['lateral']['positions_mm'][index],
                    'old_waveform_fit_xyz_error_mm': event['errors_after_fitting']['lateral']['xyz_error_mm'][index],
                    'new_event_fit_mm': None})
    return {'event_id': 2950, 'old_waveform_fit_status': event['status'], 'sites': out}


def results_directory(path):
    path = Path(path).resolve()
    return path / 'results' if (path / 'results/COMPLETE.json').is_file() else path


def run(capture=AREA):
    inputs = Inputs()
    source_before = Path(__file__).read_bytes()
    results = results_directory(capture)
    previous = inputs.read(OLD / 'position-study.json', EVENT_SHA)
    old_done = inputs.read(OLD / 'results/COMPLETE.json', OLD_DONE_SHA)
    old_request = inputs.read(OLD / 'results/bound-request.json', old_done['request_sha256'])
    done = inputs.read(results / 'COMPLETE.json', CAPTURE_DONE_SHA if results == AREA / 'results' else None)
    request = inputs.read(results / 'bound-request.json', done['request_sha256'])
    require(all(request[k] == old_request[k] for k in ('model_sha256', 'field_cache', 'field_precision_bits',
                                                      'injection_energy_keV', 'channels', 'numerics'))
            and request['field_cache']['sha256'] == previous['field_cache_sha256']
            and old_request['injection_energy_keV'] == 500 and digital.PROFILE_SHA256 == previous['digital_profile_sha256']
            and done['new_field_solves'] == done['new_transport_calls'] == 0,
            'Field, channel, injection, numerical, or readout identity changed')
    channels = request['channels']
    geometry = {c['id']: c for c in channels}
    edges = edge_geometry(channels)
    check_capture(request, done, edges)
    edge_by_pair = {tuple(e[k]): e for e in edges.values() for k in ('original_pair_ids', 'neighbor_pair_ids')}
    old_training = [observe(payload, ref, 'frozen_inner', edge, channels, geometry, edge_by_pair, 500)[0]
                    for edge, ref, payload in frozen_inner(inputs, request, previous, old_done, old_request, edges)]
    expected_old_refs = {row['reference']['ref']: row['reference']['sha256'] for row in request['reused_reference_records']}
    require(len(old_training) == 12 and all(r['usable_for_fit'] for r in old_training)
            and {r['record_ref']: inputs.hashes[r['record_ref']] for r in old_training} == expected_old_refs,
            'Frozen inner controls differ from the sealed capture request')
    fit_receipts = [item for item in done['records'] if item['role'] == 'fit']
    training = [observe(inputs.payload(results, p, done['request_sha256']), p['record_ref'], 'fit',
                        edges[p['edge_id']], channels, geometry, edge_by_pair, 500)[0] for p in fit_receipts]
    holdout_receipts = [item for item in done['records'] if item['role'] == 'holdout']
    fit_xyz = {tuple(r['position_mm']) for r in old_training + training}
    require(not any(tuple(p['position_mm']) in fit_xyz for p in holdout_receipts),
            'Independent holdout has a training coordinate')
    fit_inner, inner_diagnostics = build_fit(old_training)
    fit_extended, extended_diagnostics = build_fit(old_training + training)
    calibrations = {'frozen_inner': inner_diagnostics, 'extended': extended_diagnostics}
    frozen_calibration_sha = digest(encoded(calibrations))
    holdout = []
    # Neither holdout signals nor holdout errors enter the fitted calibration.
    for item in holdout_receipts:
        edge = edges[item['edge_id']]
        row, pair = observe(inputs.payload(results, item, done['request_sha256']), item['record_ref'],
                            'holdout', edge, channels, geometry, edge_by_pair, 500)
        readout = row['readout']
        measured = readout['strip_centers_mm'][edge['axis']]
        result = {'measured_strip_center': {'position_mm': measured,
                                            'status': 'estimated' if measured is not None else 'no_unique_measured_axis_strip'},
                  'gap_midpoint_prior': {'position_mm': edge['gap_midpoint_mm'], 'status': 'known_study_design_only'},
                  'frozen_inner': estimate(pair, readout, fit_inner),
                  'extended_fast': estimate(pair, readout, fit_extended),
                  'extended_cfd_only': estimate(pair, readout, fit_extended, timing_only=True)}
        # Only estimate the axis belonging to the measured family. Preserve any unrelated collection as abstention.
        if readout.get('selected_edge_id') not in (None, edge['edge_id']):
            for key in ('frozen_inner', 'extended_fast', 'extended_cfd_only'):
                result[key] = {'position_mm': None, 'status': 'measured_pixel_maps_to_other_studied_edge'}
        for method, key in (('frozen_inner', 'inner_or_measured_center'), ('extended_fast', 'extended_or_measured_center')):
            result[key] = result[method] if result[method]['position_mm'] is not None else result['measured_strip_center']
        holdout.append({**row, 'predictions': result})
    require(len(holdout) == 24 and sum(r['site'] == 'A' for r in holdout) == 12
            and frozen_calibration_sha == digest(encoded(calibrations)) and source_before == Path(__file__).read_bytes(),
            'Holdout, fit coefficients or source changed while evaluating')
    software = ('gegi_digital_readout.py', 'gegi_digital_pairs.py', 'gegi_substrip.py', 'gegi_imaging.py')
    return {
        'kind': 'gegi_edge_position_single_group_study_v1', 'status': 'completed',
        'provenance': {'capture_request_sha256': done['request_sha256'],
                       'calibrations_sha256_before_holdout': frozen_calibration_sha,
                       'model_sha256': request['model_sha256'], 'field_cache_sha256': request['field_cache']['sha256'],
                       'field_precision_bits': request['field_precision_bits'],
                       'numpy_version': np.__version__, 'scipy_version': scipy_version,
                       'digital_profile_sha256': digital.PROFILE_SHA256, 'timing_sha256': digital.TIMING_SHA256,
                       'input_sha256': inputs.hashes,
                       'source_sha256': {f'tools/{name}': digest((ROOT/'tools'/name).read_bytes()) for name in software}
                       | {'tools/gegi_edge_position_study.py': digest(source_before)}},
        'design': {'fit_depths_mm': FIT_DEPTHS, 'fit_offsets_pitch': FIT_OFFSETS, 'holdout_depths_mm': HOLDOUT_DEPTHS,
                   'holdout_offsets_pitch': HOLDOUT_OFFSETS, 'injection_energy_keV': 500,
                   'signed_fast_observable': 'Sign along the scanned direction × ' + RATIO_DEFINITION,
                   'timing_observable': 'Measured preamp CFD50 X minus Y, ns.',
                   'feature_scales_ratio_and_ns': SCALE.tolist(),
                   'fit': 'Within each observed two-strip pixel, linearly interpolate the target-axis coordinate '
                          'within a 2D triangulation of measured signed fast ratio and measured CFD. Fit only the '
                          'bound old inner controls and prescribed new fit placements. Outside the measured '
                          'hull, abstain. Apply no truth depth, orthogonal coordinate, or deposited energy at inference.',
                   'timing_only_comparator': 'Linear regression on measured CFD for the same training nodes, '
                                             'bounded by their CFD and physical target-coordinate ranges.',
                   'gap_prior': 'Fixed geometric midpoint uses the known targeted gap from the study design. '
                                'It is a favorable reference for the narrow band and is not a reconstruction.',
                   'transfer_scope': 'One isolated 500 keV point at nominal sample phase and no added noise. '
                                     'The orthogonal coordinate is held on its strip center at each site; '
                                     'carrier diffusion and self-repulsion are disabled. Geometry projections '
                                     'and measured slow multiplicity are separate from terminal charge sharing. '
                                     'No new two-site fit, depth reconstruction, calibrated Compton cone, '
                                     'or event-2950 position is inferred.'},
        'edges': list(edges.values()), 'event_2950_context': site_context(previous, edges),
        'counts': {'old_fit': len(old_training), 'new_fit': len(training), 'holdout': len(holdout),
                   'analysis_drift_calls': 0, 'analysis_transport_calls': 0},
        'calibrations': calibrations, 'summary': summarize(holdout),
        'training': old_training + training, 'holdout': holdout,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', type=Path, default=AREA, help='Capture root or sealed results directory')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    results = results_directory(args.capture)
    require(not any(output.is_relative_to(path) for path in (results, OLD)) and not output.exists(),
            'Write a fresh study result outside the sealed capture results')
    report = run(results)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as out:
        out.write(encoded(report) + b'\n')
    print(json.dumps({'counts': report['counts'], 'summary': report['summary']}, indent=2))


if __name__ == '__main__':
    main()
