"""Stream sealed GeGI scalar stores into predeclared spectra and cone maps.

No reconstruction, transport, native signal replay or field solve is launched.
Source truth enters only the peak evaluation, after blind peak detection.
"""
from __future__ import annotations
import argparse
from collections import Counter
from contextlib import contextmanager
import copy
import hashlib
import itertools
import json
import math
from pathlib import Path
import random
import sqlite3
import time

import gegi_imaging as I
import gegi_event_store as S

KIND = 'gegi_campaign_analysis_v1'
LINES = (661.657, 1173.228, 1332.492)
SOURCE_REFS = ('tools/gegi_campaign_analysis.py', 'tools/gegi_imaging.py', 'tools/gegi_event_store.py')
ANALYSIS_REF = 'tools/gegi_campaign_analysis.py'
COUNT_FIELDS = ('initial_primaries', 'zero_deposit_primaries', 'nonzero_primaries', 'pulse_groups',
                'native_failed_groups', 'native_flagged_groups', 'readout_accepted_groups', 'readout_rejected_groups',
                'imaging_accepted_groups', 'imaging_rejected_groups', 'native_failed_primaries',
                'native_flagged_primaries', 'readout_accepted_primaries', 'readout_rejected_primaries',
                'imaging_accepted_primaries', 'imaging_rejected_primaries')


def require(ok, message):
    if not ok:
        raise ValueError(message)


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def encoded(value):
    return S.encoded(value)+b'\n'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def criteria():
    """Freeze this exact dictionary in the campaign plan before production."""
    require(I.KERNEL_SIGMA_DEG == 5.0, 'The agreed imaging kernel changed')
    return {'kind': 'gegi_campaign_metrics_v1', 'angular_bin_deg': 5, 'kernel_sigma_deg': 5.,
            'plane_z_mm': 40., 'plane_xy_edges_mm': [-120., 120.], 'plane_bin_mm': 2.,
            'minimum_accepted_groups_per_component': 20,
            'minimum_direction_peak_separation_deg': 20., 'minimum_plane_peak_separation_mm': 20.,
            'maximum_valley_fraction_of_lower_peak': .8,
            'direction_localization_tolerance_deg': 15., 'plane_localization_tolerance_mm': 15.,
            'peak_rule': '8-neighbor local maxima; equal plateaus merged; highest first, then highest outside fixed separation',
            'valley_rule': 'minimum bilinear score on the interior short great-circle or plane segment; samples at quarter-bin spacing',
            'truth_rule': 'detect peaks without truth, then minimum-total-distance one-to-one matching',
            'isotope_windows': [{'line_energy_keV': e, 'half_width_keV': max(5., .02*e)} for e in LINES],
            'isotope_window_selection_rule': 'apply every window to every source using observed fixed-gain readout energy; retain cross-isotope contributions',
            'spectrum_edges_keV': [0., 4000.], 'spectrum_bin_keV': 2.,
            'representative_rule': 'first accepted unambiguous pulse group per source component in original ID order; otherwise first accepted; all 34 channels by hash/reference',
            'mixture_rule': 'equal initial source yields: 0.5*map_a/N_a + 0.5*map_b/N_b; no unit-area source renormalization',
            'bootstrap': {'automatic': False, 'resamples': 200, 'seed': 261017201,
                          'maximum_accepted_groups': 20000,
                          'method': 'primary-cluster Poisson(1) event bootstrap preserving all pulse groups and cone hypotheses',
                          'scope': 'finite-sample peak variation only; no model, calibration or hardware uncertainty'}}


def line_key(energy):
    return format(energy, '.3f')


def vector(azimuth, elevation):
    az, el = math.radians(azimuth), math.radians(elevation)
    return [math.cos(el)*math.cos(az), math.cos(el)*math.sin(az), math.sin(el)]


def angle(a, b):
    return math.degrees(math.acos(max(-1., min(1., sum(x*y for x, y in zip(a, b))))))


def truth_direction(position):
    require(isinstance(position, list) and len(position) == 3 and all(finite(v) for v in position), 'Invalid evaluation source position')
    length = math.sqrt(sum(v*v for v in position))
    require(length > 0, 'Source at detector origin has no defined truth direction')
    return [v/length for v in position]


def validate_cones(cones):
    require(type(cones) is list and 1 <= len(cones) <= 4, 'Expected all one-to-four GeGI candidate cones')
    for c in cones:
        require(all(type(c.get(k)) is list and len(c[k]) == 3 and all(finite(v) for v in c[k])
                    for k in ('axis', 'vertex_mm')), 'Invalid signal-derived cone coordinates')
        require(math.isclose(sum(v*v for v in c['axis']), 1., abs_tol=1e-8)
                and finite(c.get('half_angle_deg')) and 0 <= c['half_angle_deg'] <= 180
                and finite(c.get('weight')) and math.isclose(c['weight'], 1/len(cones), abs_tol=1e-12),
                'All candidate hypotheses must retain their equal weights')
    require(math.isclose(sum(c['weight'] for c in cones), 1., abs_tol=1e-12), 'Pulse-group cone weights must sum to one')


def plane_backproject(cones, *, ticks=None, plane_z_mm=40., step_mm=2., sigma_deg=5.):
    """Same vertex-aware finite-plane kernel/normalization as gegi_publication.

    The declared campaign grid uses true 2-mm bins with edges ±120 mm and
    centers ±119 mm. Vectorization changes evaluation cost, not cone weights.
    """
    import numpy as np
    ticks = list(ticks) if ticks is not None else [-119.+2*i for i in range(120)]
    require(ticks and all(finite(v) for v in ticks) and finite(step_mm) and step_mm > 0
            and finite(sigma_deg) and sigma_deg > 0, 'Invalid fixed plane grid')
    xx, yy = np.meshgrid(np.asarray(ticks, dtype=np.float64), np.asarray(ticks, dtype=np.float64))
    values = np.zeros_like(xx); unmapped = []
    for candidate in cones:
        v, axis = candidate['vertex_mm'], candidate['axis']
        dx, dy, dz = xx-v[0], yy-v[1], plane_z_mm-v[2]
        distance = np.sqrt(dx*dx+dy*dy+dz*dz)
        cosine = np.divide(dx*axis[0]+dy*axis[1]+dz*axis[2], distance,
                           out=np.zeros_like(distance), where=distance != 0)
        angles = np.degrees(np.arccos(np.clip(cosine, -1., 1.)))
        scores = np.exp(-.5*((angles-candidate['half_angle_deg'])/sigma_deg)**2)
        scores[distance == 0] = 0
        normalizer = math.fsum(float(v) for v in scores.flat)*step_mm**2
        if normalizer <= 0:
            unmapped.append({'event_id': candidate.get('event_id'), 'order': candidate.get('order'), 'weight': candidate['weight']})
        else:
            values += candidate['weight']*scores/normalizer
    return {'method': 'finite_plane_saved_cone_backprojection_v1', 'plane_z_mm': plane_z_mm,
            'x_mm': ticks, 'y_mm': ticks, 'grid_step_mm': step_mm, 'kernel_sigma_deg': sigma_deg,
            'values': values.tolist(), 'unmapped_cones': unmapped,
            'value_units': 'weighted accepted pulse groups per square millimetre'}


def _neighbors(row, col, height, width, periodic):
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr == dc == 0 or not 0 <= row+dr < height:
                continue
            c = (col+dc) % width if periodic else col+dc
            if 0 <= c < width:
                yield row+dr, c


def local_peaks(image, kind):
    """Blind deterministic maxima; connected equal-value plateaus count once."""
    values = image['values']; height, width = len(values), len(values[0]); seen = set(); peaks = []
    require(kind in ('direction', 'plane'), 'Unknown peak metric geometry')
    for row in range(height):
        for col in range(width):
            if (row, col) in seen or values[row][col] <= 0:
                continue
            height_value = values[row][col]
            if any(values[r][c] > height_value for r, c in _neighbors(row, col, height, width, kind == 'direction')):
                continue
            plateau, pending, boundary = [], [(row, col)], []
            while pending:
                p = pending.pop()
                if p in seen:
                    continue
                seen.add(p); plateau.append(p)
                for r, c in _neighbors(*p, height, width, kind == 'direction'):
                    if values[r][c] == height_value:
                        if (r, c) not in seen:
                            pending.append((r, c))
                    else:
                        boundary.append(values[r][c])
            if not boundary or max(boundary) > height_value:
                continue
            r, c = min(plateau)
            peak = {'row': r, 'column': c, 'score': height_value, 'plateau_cells': len(plateau)}
            if kind == 'direction':
                peak.update(azimuth_deg=image['azimuth_deg'][c], elevation_deg=image['elevation_deg'][r])
                peak['unit_vector'] = vector(peak['azimuth_deg'], peak['elevation_deg'])
            else:
                peak.update(x_mm=image['x_mm'][c], y_mm=image['y_mm'][r], z_mm=image['plane_z_mm'])
            peaks.append(peak)
    return sorted(peaks, key=lambda p: (-p['score'], p['row'], p['column']))


def peak_distance(a, b, kind):
    return angle(a['unit_vector'], b['unit_vector']) if kind == 'direction' else math.hypot(a['x_mm']-b['x_mm'], a['y_mm']-b['y_mm'])


def detect_peaks(image, kind, count=2):
    key = 'minimum_direction_peak_separation_deg' if kind == 'direction' else 'minimum_plane_peak_separation_mm'
    chosen = []
    for peak in local_peaks(image, kind):
        if all(peak_distance(peak, p, kind) >= criteria()[key] for p in chosen):
            chosen.append(peak)
            if len(chosen) == count:
                break
    return chosen


def _sample(image, x, y, kind):
    xs = image['azimuth_deg'] if kind == 'direction' else image['x_mm']
    ys = image['elevation_deg'] if kind == 'direction' else image['y_mm']
    dx, dy = xs[1]-xs[0], ys[1]-ys[0]
    fx = ((x-xs[0])/dx) % len(xs) if kind == 'direction' else max(0., min(len(xs)-1., (x-xs[0])/dx))
    fy = max(0., min(len(ys)-1., (y-ys[0])/dy))
    i, j = int(math.floor(fx)), int(math.floor(fy)); tx, ty = fx-i, fy-j
    ni = (i+1) % len(xs) if kind == 'direction' else min(i+1, len(xs)-1)
    nj = min(j+1, len(ys)-1); v = image['values']
    return (1-ty)*((1-tx)*v[j][i]+tx*v[j][ni])+ty*((1-tx)*v[nj][i]+tx*v[nj][ni])


def valley(image, peaks, kind):
    if len(peaks) != 2:
        return None
    a, b = peaks; distance = peak_distance(a, b, kind)
    width = criteria()['angular_bin_deg' if kind == 'direction' else 'plane_bin_mm']
    samples = max(3, math.ceil(distance/(width/4)))
    scores = []
    for i in range(1, samples):
        t = i/samples
        if kind == 'direction':
            av, bv = a['unit_vector'], b['unit_vector']; omega = math.radians(distance)
            if abs(math.sin(omega)) < 1e-10:
                basis = [1., 0., 0.] if abs(av[0]) < .8 else [0., 1., 0.]
                dot = sum(x*y for x, y in zip(av, basis)); ortho = [x-dot*y for x, y in zip(basis, av)]
                length = math.sqrt(sum(x*x for x in ortho)); ortho = [x/length for x in ortho]
                v = [math.cos(t*omega)*x+math.sin(t*omega)*y for x, y in zip(av, ortho)]
            else:
                v = [(math.sin((1-t)*omega)*x+math.sin(t*omega)*y)/math.sin(omega) for x, y in zip(av, bv)]
            x, y = math.degrees(math.atan2(v[1], v[0])), math.degrees(math.asin(max(-1., min(1., v[2]))))
        else:
            x, y = a['x_mm']+t*(b['x_mm']-a['x_mm']), a['y_mm']+t*(b['y_mm']-a['y_mm'])
        scores.append(_sample(image, x, y, kind))
    low = min(a['score'], b['score'])
    return {'minimum_score': min(scores), 'lower_peak_score': low,
            'fraction_of_lower_peak': min(scores)/low, 'interior_sample_count': len(scores)}


def evaluate(image, truths, accepted, kind):
    """Truth is applied strictly AFTER blind top-two peak detection."""
    peaks = detect_peaks(image, kind, 2 if len(truths) == 2 else 1)
    result = {'peaks': peaks, 'accepted_groups_per_component': accepted,
              'minimum_accepted_groups_per_component': criteria()['minimum_accepted_groups_per_component']}
    enough = all(n >= criteria()['minimum_accepted_groups_per_component'] for n in accepted)
    if len(truths) == 1:
        target = truths[0]
        bias = None if not peaks else (angle(peaks[0]['unit_vector'], truth_direction(target)) if kind == 'direction'
                                      else math.hypot(peaks[0]['x_mm']-target[0], peaks[0]['y_mm']-target[1]))
        valid_plane = kind == 'direction' or math.isclose(target[2], criteria()['plane_z_mm'], abs_tol=1e-9)
        result.update(global_peak_bias=bias if valid_plane else None, bias_units='deg' if kind == 'direction' else 'mm',
                      status='measured' if enough and peaks and valid_plane else 'inconclusive',
                      reason=None if enough and peaks and valid_plane else 'low_accepted_count_or_no_peak_or_truth_off_assumed_plane')
        return result
    require(len(truths) == len(accepted) == 2, 'Mixture evaluation requires exactly two independent components')
    trough = valley(image, peaks, kind)
    resolved = len(peaks) == 2 and trough['fraction_of_lower_peak'] <= criteria()['maximum_valley_fraction_of_lower_peak']
    assignments = []
    if len(peaks) == 2:
        for order in itertools.permutations(range(2)):
            biases = [angle(peaks[p]['unit_vector'], truth_direction(truths[i])) if kind == 'direction' else
                      math.hypot(peaks[p]['x_mm']-truths[i][0], peaks[p]['y_mm']-truths[i][1]) for i, p in enumerate(order)]
            assignments.append((sum(biases), order, biases))
    match = min(assignments) if assignments else None
    tol = criteria()['direction_localization_tolerance_deg' if kind == 'direction' else 'plane_localization_tolerance_mm']
    valid_plane = kind == 'direction' or all(math.isclose(p[2], criteria()['plane_z_mm'], abs_tol=1e-9) for p in truths)
    localized = bool(match and valid_plane and all(b <= tol for b in match[2]))
    reasons = []
    if not enough: reasons.append('fewer_than_20_accepted_groups_in_a_component')
    if len(peaks) != 2: reasons.append('no_second_local_peak_at_fixed_minimum_separation')
    elif not resolved: reasons.append('connecting_valley_exceeds_0.8_of_lower_peak')
    if not localized: reasons.append('matched_peaks_outside_declared_tolerance_or_missing')
    if not valid_plane: reasons.append('source_truth_off_assumed_plane')
    result.update(valley=trough, peak_separation=peak_distance(*peaks, kind) if len(peaks) == 2 else None,
                  two_peak_resolution_status='inconclusive' if not enough else 'pass' if resolved else 'fail',
                  truth_matching=None if match is None else {'peak_indices_by_component': list(match[1]), 'biases': match[2]},
                  localization_tolerance=tol, localization_units='deg' if kind == 'direction' else 'mm',
                  localization_within_declared_tolerance=localized if enough and valid_plane else None,
                  source_separation_demonstrated=None if not enough or not valid_plane else bool(resolved and localized),
                  status='inconclusive' if not enough or not valid_plane else 'pass' if resolved and localized else 'fail', reasons=reasons)
    return result


@contextmanager
def scalar_store(path, identity, completion):
    """Use the existing scalar decoder through an immutable, read-only connection."""
    path = Path(path).absolute()
    require(path.is_file() and path == path.resolve() and not path.is_symlink(), 'Missing or linked sealed Store')
    require(not Path(str(path)+'-wal').exists(), 'Sealed analysis refuses a live SQLite WAL')
    store = S.Store.__new__(S.Store)
    store.path = path
    store.db = sqlite3.connect(path.as_uri()+'?mode=ro&immutable=1', uri=True)
    try:
        stored = store.db.execute('SELECT body FROM identity WHERE singleton=1').fetchone()
        seal = store.db.execute('SELECT body FROM completion WHERE singleton=1').fetchone()
        require(stored is not None and stored[0] == S.encoded({'kind': S.KIND, 'identity': identity}), 'Sealed Store identity differs')
        require(seal is not None and seal[0] == S.encoded(completion), 'Sealed Store completion differs')
        yield store
    finally:
        store.close()


def blank_maps():
    plane = plane_backproject([]); plane.pop('unmapped_cones'); plane['unmapped_cone_weight'] = 0.
    return {'direction': I.backproject([], step_deg=5, sigma_deg=5.), 'plane': plane}


def add_maps(target, source, factor=1.):
    import numpy as np
    for kind in ('direction', 'plane'):
        target[kind]['values'] = np.asarray(target[kind]['values'], dtype=np.float64)+factor*np.asarray(source[kind]['values'], dtype=np.float64)
    plane = source['plane']
    target['plane']['unmapped_cone_weight'] += factor*(sum(c['weight'] for c in plane['unmapped_cones'])
        if 'unmapped_cones' in plane else plane['unmapped_cone_weight'])


def serializable_maps(value):
    result = copy.deepcopy(value)
    for image in result.values():
        if hasattr(image['values'], 'tolist'):
            image['values'] = image['values'].tolist()
    return result


def outcome(event):
    require(event.get('status') in ('completed', 'step_limit', 'stopped_without_contact', 'native_failed'), 'Unknown native pulse-group status')
    readout, reco = event.get('readout_summary'), event.get('reconstruction')
    require(type(readout) is dict and type(readout.get('accepted')) is bool, 'Missing fixed-gain readout summary')
    require(type(reco) is dict and reco.get('status') in ('accepted', 'rejected'), 'Missing saved signal-derived reconstruction')
    energy = readout.get('energy_keV')
    require(energy is None or finite(energy), 'Unknown energy must be null, never nonfinite')
    require(not readout['accepted'] or energy is not None, 'Accepted readout lacks fixed-gain energy')
    failed = event['status'] == 'native_failed'
    if failed:
        require(event.get('channels') is None and event.get('native_signals') is None and energy is None
                and not readout['accepted'] and reco['status'] == 'rejected', 'Native failure was fabricated as known signal/energy')
    cones = reco.get('cones')
    if reco['status'] == 'accepted':
        require(readout['accepted'] and not failed, 'Imaging accepted a failed/rejected readout')
        validate_cones(cones)
    else:
        require(cones == [], 'Rejected pulse group contains selected candidate cones')
    return {'native_failed': failed, 'native_flagged': event['status'] in ('step_limit', 'stopped_without_contact'),
            'readout_accepted': readout['accepted'], 'readout_rejected': not readout['accepted'],
            'imaging_accepted': reco['status'] == 'accepted', 'imaging_rejected': reco['status'] != 'accepted'}


def representative(event, identity, store_ref, store_sha256):
    channels = event.get('channels')
    require(type(channels) is list and len(channels) == 34 and {c['contact_id'] for c in channels} == set(range(1, 35)),
            'Representative must reference all 34 real channels')
    references = event.get('native_signals')
    require(type(references) is dict and set(references) == {str(i) for i in range(1, 35)}, 'Representative native channel references differ')
    return {**identity, 'store_ref': store_ref, 'store_sha256': store_sha256,
            'selection_rule': 'first accepted unambiguous pulse group in original ID order; otherwise first accepted',
            'readout_energy_keV': event['readout_summary']['energy_keV'],
            'unambiguous': not (event['reconstruction'].get('ordering_ambiguous') or event['reconstruction'].get('pairing_ambiguous')),
            'channels': [{'contact_id': c['contact_id'], 'accepted': c['accepted'],
                          'reconstructed_energy_keV': c.get('reconstructed_energy_keV'),
                          'derived_trace_sha256': c['derived_trace_sha256'], 'native_signals': references[str(c['contact_id'])]}
                         for c in sorted(channels, key=lambda c: c['contact_id'])],
            'calibration_sha256': event['calibration_sha256'], 'readout_recipe_sha256': event['readout_recipe_sha256'],
            'trace_policy': 'References only. Recover native Float64 arrays and replay frozen readout; verify the stored trace hashes.'}


class Accumulator:
    def __init__(self, groups):
        self.groups = {g['id']: g for g in groups}
        require(len(self.groups) == len(groups), 'Repeated source-group identity')
        self.data = {}
        for g in groups:
            self.data[g['id']] = {'counts': Counter(), 'native_status_counts': Counter(), 'rejection_reasons': Counter(),
                'readout_rejection_reasons': Counter(), 'ambiguous_groups': 0, 'candidate_cones': 0,
                'unknown_readout_energy_groups': 0, 'plane_unmapped_weight': 0., 'representative': None, 'transport_denominators': {},
                'spectrum': {'edges_keV': [2.*i for i in range(2001)], 'counts': [0]*2000,
                             'underflow': 0, 'overflow': 0, 'selected_readout_groups': 0},
                'line_counts': {line_key(e): Counter({key: 0 for key in ('readout_selected_groups', 'readout_selected_primaries',
                    'imaging_accepted_groups', 'imaging_rejected_groups')}) for e in LINES},
                'maps': {'all': blank_maps(), **{line_key(e): blank_maps() for e in LINES}}}

    def consume(self, group_id, records, *, declared_counts, identity, store_ref, store_sha256, ledger=None):
        data = self.data[group_id]; observed = Counter(); primary_sets = {k: set() for k in
            ('nonzero', 'native_failed', 'native_flagged', 'readout_accepted', 'readout_rejected', 'imaging_accepted', 'imaging_rejected')}
        line_sets = {line_key(e): set() for e in LINES}; previous = None
        base = identity.get('raw_initial_id_base', 0)
        require(type(base) is int and base == 0, 'Store retains the proven zero-based raw primary census')
        for primary_id, pulse_id, event in records:
            require(type(primary_id) is int and type(pulse_id) is int and pulse_id >= 0
                    and base <= primary_id < base+identity['batch']['primary_count'], 'Original primary/group ID outside chunk')
            key = (primary_id, pulse_id)
            require(previous is None or key > previous, 'Store scalar rows are duplicated or not ordered'); previous = key
            require(event['event_id'] == primary_id and event['group_id'] == pulse_id, 'Scalar identity changed')
            require(event.get('calibration_sha256') == identity['calibration_sha256'] and
                    event.get('photopeak_windows_sha256') == identity['photopeak_windows_sha256'], 'Scalar calibration/selection identity changed')
            flags = outcome(event); observed['pulse_groups'] += 1; primary_sets['nonzero'].add(primary_id)
            data['native_status_counts'][event['status']] += 1
            for name, flag in flags.items():
                if flag:
                    observed[name+'_groups'] += 1; primary_sets[name].add(primary_id)
            readout, reco = event['readout_summary'], event['reconstruction']; energy = readout['energy_keV']
            if energy is None:
                data['unknown_readout_energy_groups'] += 1
            if not readout['accepted']:
                data['readout_rejection_reasons'][readout.get('reason') or 'unspecified_saved_reason'] += 1
            if reco['status'] == 'rejected':
                data['rejection_reasons'][reco.get('reason') or 'unspecified_saved_reason'] += 1
            matches = [line_key(e) for e in LINES if readout['accepted'] and abs(energy-e) <= max(5., .02*e)]
            if readout['accepted']:
                spec = data['spectrum']; spec['selected_readout_groups'] += 1
                if energy < 0: spec['underflow'] += 1
                elif energy >= 4000: spec['overflow'] += 1
                else: spec['counts'][int(energy//2)] += 1
            for line in matches:
                data['line_counts'][line]['readout_selected_groups'] += 1; line_sets[line].add(primary_id)
                data['line_counts'][line]['imaging_'+reco['status']+'_groups'] += 1
            if reco['status'] != 'accepted':
                continue
            cones = reco['cones']; ambiguous = bool(reco.get('ordering_ambiguous') or reco.get('pairing_ambiguous'))
            data['ambiguous_groups'] += int(ambiguous); data['candidate_cones'] += len(cones)
            group_maps = {'direction': I.backproject(cones, step_deg=5, sigma_deg=5.), 'plane': plane_backproject(cones)}
            add_maps(data['maps']['all'], group_maps)
            for line in matches:
                add_maps(data['maps'][line], group_maps)
            unmapped = group_maps['plane']['unmapped_cones']
            data['plane_unmapped_weight'] += sum(c['weight'] for c in unmapped)
            group_identity = {'source_group': group_id, 'chunk_index': identity['chunk_index'],
                'raw_primary_id': primary_id, 'pulse_group_id': pulse_id,
                'source_global_initial_id': identity['batch']['global_initial_offset']+primary_id-base,
                'campaign_initial_id': identity['campaign_initial_offset']+primary_id-base}
            if ledger is not None:
                ledger.write(encoded({**group_identity, 'store_ref': store_ref, 'readout_energy_keV': energy,
                    'analysis_line_windows_keV': [float(x) for x in matches], 'ambiguous': ambiguous,
                    'cones': cones, 'plane_unmapped_cones': unmapped}))
            current = data['representative']
            if current is None or current['unambiguous'] is False and not ambiguous:
                data['representative'] = representative(event, group_identity, store_ref, store_sha256)
        observed.update({name+'_primaries': len(ids) for name, ids in primary_sets.items()})
        require(set(COUNT_FIELDS) <= set(declared_counts), 'Sealed stage counters are incomplete')
        require(declared_counts['initial_primaries'] == identity['batch']['primary_count'] and
                declared_counts['zero_deposit_primaries']+declared_counts['nonzero_primaries'] == declared_counts['initial_primaries'],
                'Initial/zero/nonzero denominator differs')
        for name in COUNT_FIELDS:
            value = declared_counts[name]
            require(type(value) is int and value >= 0, 'Invalid sealed stage counter')
            if name not in ('initial_primaries', 'zero_deposit_primaries'):
                require(observed[name] == value, 'Scalar rows disagree with sealed stage count: '+name)
            data['counts'][name] += value
        for line, ids in line_sets.items():
            data['line_counts'][line]['readout_selected_primaries'] += len(ids)
        for name in ('initial_decays', 'decay_photons', 'line_photons', 'line_photon_counts'):
            if name in declared_counts:
                _sum_counts(data['transport_denominators'], {name: declared_counts[name]})

    def results(self):
        maps, groups = {}, {}
        for key, data in self.data.items():
            g = self.groups[key]; maps[key] = {name: serializable_maps(value) for name, value in data['maps'].items()}
            groups[key] = {name: dict(value) if isinstance(value, Counter) else value for name, value in data.items() if name != 'maps'}
            groups[key]['line_counts'] = {k: dict(v) for k, v in data['line_counts'].items()}
            groups[key].update(source=g['source'], count_unit=g['count_unit'], planned_initial_primaries=g['primary_count'],
                initial_primary_denominator=data['counts']['initial_primaries'],
                truth_position_mm_for_evaluation_only=g['source_position_mm'],
                line_denominator_policy='Each window retains the full source-group initial denominator. No claim of photons emitted in that line; unknown energies are unassigned.',
                evaluations={kind: evaluate(maps[key]['all'][kind], [g['source_position_mm']],
                    [data['counts']['imaging_accepted_groups']], kind) for kind in ('direction', 'plane')})
        return groups, maps


def mixtures(groups, source_maps):
    """All declared pairs in the same source family; keep photon/decay units distinct."""
    result, maps = {}, {}
    families = {}
    for key, g in groups.items():
        family = 'emitted_gamma' if g['source'] == 'gegi_mono_gamma_v1' else 'initial_decay'
        families.setdefault(family, []).append(key)
    for family, ids in families.items():
        for a, b in itertools.combinations(ids, 2):
            key = a+'__'+b; denominators = [groups[k]['initial_primary_denominator'] for k in (a, b)]
            if not all(denominators):
                result[key] = {'status': 'inconclusive', 'reason': 'a_component_has_no_sealed_initial_primaries', 'components': [a, b]}
                continue
            maps[key] = {}
            for window in ('all', *(line_key(e) for e in LINES)):
                combined = blank_maps()
                for component, denominator in zip((a, b), denominators):
                    add_maps(combined, source_maps[component][window], .5/denominator)
                maps[key][window] = serializable_maps(combined)
                maps[key][window]['direction']['value_units'] = 'weighted accepted pulse groups per equally allocated initial primary per steradian'
                maps[key][window]['plane']['value_units'] = 'weighted accepted pulse groups per equally allocated initial primary per square millimetre'
            accepted = [groups[k]['counts']['imaging_accepted_groups'] for k in (a, b)]
            truths = [groups[k]['truth_position_mm_for_evaluation_only'] for k in (a, b)]
            result[key] = {'components': [a, b], 'family': family,
                'initial_denominators': [{'source_group': k, 'count': groups[k]['initial_primary_denominator'],
                                         'unit': groups[k]['count_unit'], 'map_scale': .5/groups[k]['initial_primary_denominator']} for k in (a, b)],
                'normalization': criteria()['mixture_rule'],
                'independence': 'Independent source data, linearly combined; no inter-source pileup, coincidence or activity model.',
                'evaluations': {kind: evaluate(maps[key]['all'][kind], truths, accepted, kind) for kind in ('direction', 'plane')}}
    return result, maps


def _sum_counts(target, values):
    for name, value in values.items():
        if type(value) is dict:
            _sum_counts(target.setdefault(name, {}), value)
        else:
            require(type(value) is int and value >= 0, 'Transport denominator must remain an exact nonnegative count')
            target[name] = target.get(name, 0)+value


def source_hashes(root):
    return {ref: sha(Path(root)/ref) for ref in SOURCE_REFS}


def response_recipe_for_event(response, event):
    """Select a recorded recipe without rewriting a preserved pre-recovery row."""
    recipe = response['readout_recipe']; current = S.sha(S.encoded(recipe))
    require(response['readout_recipe_sha256'] == current, 'Current readout recipe hash changed')
    wanted = event['readout_recipe_sha256']
    if wanted == current:
        return recipe
    prior = response.get('prior_recipe_provenance')
    require(type(prior) is dict and prior.get('kind') == 'gegi_prior_recipe_provenance_v1', 'Unadmitted prior readout recipe')
    old = prior.get('recipes', {}).get(wanted)
    require(type(old) is dict and S.sha(S.encoded(old)) == wanted, 'Prior readout recipe hash changed')
    change = prior['wrapper_source_change']; name = change['name']
    require(name == 'gegi_campaign_response.jl' and old['source_code_sha256'].get(name) == change['old_sha256']
            and recipe['source_code_sha256'].get(name) == change['new_sha256'], 'Prior recipe wrapper lineage differs')
    expected = copy.deepcopy(old); expected['source_code_sha256'][name] = change['new_sha256']
    require(expected == recipe, 'Recovery changed readout physics/configuration or other source pins')
    matches = [r for r in prior['events'] if (r['event_id'], r['group_id']) == (event['event_id'], event['group_id'])]
    require(len(matches) == 1 and matches[0]['readout_recipe_sha256'] == wanted and
            matches[0]['metadata_sha256'] == S.sha(S.encoded(event)), 'Prior event metadata/version binding changed')
    return old


def validate_analysis_revision(plan, *, root=None, allow_analysis_revision=False):
    """Admit only an explicitly requested consumer revision; producer pins stay exact."""
    import gegi_campaign as C
    root = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    require(type(allow_analysis_revision) is bool, 'Analysis revision opt-in must be boolean')
    require(plan.get('analysis_criteria') == criteria(), 'Campaign criteria changed after freeze')
    frozen = plan.get('source_sha256')
    require(type(frozen) is dict and set(C.SOURCES).union(SOURCE_REFS) <= set(frozen),
            'Frozen analysis/producer source inventory is incomplete')
    current = {}
    for ref, expected in frozen.items():
        require(type(expected) is str and len(expected) == 64 and all(c in '0123456789abcdef' for c in expected),
                'Invalid frozen source hash')
        path = C.W.safe_path(root, ref); C.no_links(path)
        current[ref] = sha(path)
        if ref != ANALYSIS_REF:
            require(current[ref] == expected, 'Frozen producer source changed: '+ref)
    changed = current[ANALYSIS_REF] != frozen[ANALYSIS_REF]
    require(not changed or allow_analysis_revision,
            'Analysis source differs from the frozen campaign; explicit --allow-analysis-revision is required')
    if 'quota_amendment' in plan:
        import gegi_campaign_quota as Q
        Q.original_plan(plan,root,_audit_current=False)
    elif 'recovery' in plan:
        import gegi_campaign_recovery as R
        # Current producer pins were checked above, including explicit consumer revision.
        # Verify every historical edge without comparing old pins to today's files.
        R.original_plan(plan,root,_audit_current=False)
    producers = {ref: value for ref, value in frozen.items() if ref != ANALYSIS_REF}
    return {'kind': 'gegi_analysis_revision_v1', 'allowed': allow_analysis_revision, 'applied': changed,
            'permitted_source_ref': ANALYSIS_REF, 'original_analysis_sha256': frozen[ANALYSIS_REF],
            'current_analysis_sha256': current[ANALYSIS_REF], 'producer_source_pin_count': len(producers),
            'producer_source_sha256_digest': S.sha(S.encoded(producers)),
            'policy': 'Only the analysis consumer file may differ with explicit opt-in; every producer source hash and frozen analysis criterion remains exact. Frozen plans and saved science are never rewritten.'}


def _stamp(path):
    stat = Path(path).stat()
    return stat.st_size, stat.st_mtime_ns


def sealed_chunks(directory, plan, *, allow_partial=False, root=None):
    """Verify only the scalar subset needed here; do not rescan large raw archives."""
    import gegi_campaign as C
    directory = Path(directory); complete_path = directory/'COMPLETE.json'
    complete = read(complete_path) if complete_path.exists() else None
    require(allow_partial or complete is not None, 'Full analysis requires campaign COMPLETE; use explicit partial analysis for sealed chunks only')
    if complete is not None:
        require(complete.get('kind') == C.KIND and complete.get('status') in ('completed', 'completed_with_native_failures')
                and complete.get('plan_sha256') == sha(directory/'plan.json')
                and complete.get('physics_sha256') == plan['physics_sha256']
                and complete.get('initial_primaries') == plan['total_initial_primaries'], 'Campaign completion identity differs')
        require(set(complete['chunks']) == {str(c['chunk_index']) for c in C.chunks(plan)}, 'Completed chunk census differs')
    for chunk in C.chunks(plan):
        folder = C.chunk_path(directory, chunk); done_path = folder/'DONE.json'
        if not done_path.exists():
            require(allow_partial and complete is None, 'Completed campaign has an unsealed chunk')
            continue
        done_hash = sha(done_path); done = read(done_path); identity = C.chunk_identity(directory, plan, chunk,
            root=Path(root) if root is not None else Path(__file__).resolve().parents[1])
        require(done.get('kind') == C.DONE_KIND and done.get('identity') == identity, 'Sealed chunk identity changed')
        if complete is not None:
            require(complete['chunks'][str(chunk['chunk_index'])] == done_hash, 'Completed chunk seal changed')
        response = read(folder/'response.json')
        require(done['response'] == response and response.get('status') in ('completed', 'completed_with_native_failures')
                and response['store_identity_sha256'] == S.sha(S.encoded(identity)), 'Sealed response identity changed')
        if 'recovery' in plan:
            import gegi_campaign_recovery as R
            require(response.get('prior_recipe_provenance') == R.prior_provenance(plan, chunk,
                    root=Path(root) if root is not None else Path(__file__).resolve().parents[1]),
                    'Recovered response recipe ledger differs from frozen revision')
            require(response.get('saved_native_failure') == R.saved_failure(plan, chunk,
                    root=Path(root) if root is not None else Path(__file__).resolve().parents[1]),
                    'Recovered saved-failure admission differs from frozen revision')
        else:
            require('prior_recipe_provenance' not in response and 'saved_native_failure' not in response, 'Unexpected response recovery provenance')
        for name in ('events.sqlite', 'response.json'):
            path = folder/name; record = done['artifacts'][name]
            require(path.is_file() and path == path.resolve() and path.stat().st_size == record['bytes'] and sha(path) == record['sha256'],
                    'Sealed scalar artifact changed: '+name)
        yield chunk, folder, done, done_hash


def measure_bootstrap_cost(accepted_groups, *, root=None):
    """Explicit small timing check only; does not automatically enable bootstrap."""
    import numpy as np
    require(type(accepted_groups) is int and 1 <= accepted_groups <= criteria()['bootstrap']['maximum_accepted_groups'],
            'Bootstrap accepted-group bound exceeded')
    root = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    cone = {'vertex_mm': [0., 0., 0.], 'axis': [0., 0., 1.], 'half_angle_deg': 60., 'weight': 1.}
    n = criteria()['bootstrap']['resamples']; began = time.perf_counter()
    sample = {'direction': I.backproject([cone]), 'plane': plane_backproject([cone])}
    arrays = {k: np.zeros((n, len(v['values']), len(v['values'][0])), dtype=np.float64) for k, v in sample.items()}
    for values, grid in zip(arrays.values(), sample.values()):
        for index in range(n):
            values[index] += np.asarray(grid['values'])
    elapsed = time.perf_counter()-began
    return {'kind': 'gegi_bootstrap_cost_v1', 'criteria': criteria(), 'source_sha256': source_hashes(root),
            'accepted_groups': accepted_groups, 'resamples': n, 'sample_groups': 1, 'sample_seconds': elapsed,
            'estimated_seconds': elapsed*accepted_groups, 'numpy_version': np.__version__,
            'maximum_accumulator_bytes_four_components': sum(v.nbytes for v in arrays.values())*4,
            'uncertainty': 'One cold synthetic-cone sample; linear extrapolation is a screening estimate, not a runtime guarantee.'}


def _poisson_one(rng):
    product, k = 1., 0
    while product > math.exp(-1):
        product *= rng.random(); k += 1
    return k-1


def bootstrap_peaks(ledger_path, groups, *, cost_receipt, budget_seconds, root=None):
    """Bounded opt-in accepted-primary cluster bootstrap; no waveform reads."""
    import numpy as np
    root = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    policy = criteria()['bootstrap']; cost = read(cost_receipt); count = sum(g['counts']['imaging_accepted_groups'] for g in groups.values())
    require(0 < count <= policy['maximum_accepted_groups'] and len(groups) <= 4, 'Bootstrap exceeds the frozen bounded support')
    require(cost.get('kind') == 'gegi_bootstrap_cost_v1' and cost.get('criteria') == criteria()
            and cost.get('source_sha256') == source_hashes(root) and cost.get('accepted_groups') == count
            and cost.get('resamples') == policy['resamples'] and cost.get('numpy_version') == np.__version__,
            'Bootstrap requires a matching explicit measured cost check')
    require(finite(budget_seconds) and budget_seconds > 0 and finite(cost.get('estimated_seconds'))
            and cost['estimated_seconds'] <= budget_seconds, 'Measured bootstrap estimate exceeds the explicit compute budget')
    templates = blank_maps(); n = policy['resamples']; rng = random.Random(policy['seed'])
    arrays = {key: {kind: np.zeros((n, len(image['values']), len(image['values'][0])), dtype=np.float64)
                    for kind, image in templates.items()} for key in groups}
    counts = {key: [0]*n for key in groups}; previous = None; weights = None; processed = 0; began = time.perf_counter()
    with Path(ledger_path).open(encoding='utf-8') as stream:
        for line in stream:
            event = json.loads(line); key = event['source_group']
            primary = (key, event['chunk_index'], event['raw_primary_id'])
            if primary != previous:
                weights = [_poisson_one(rng) for _ in range(n)]; previous = primary
            validate_cones(event['cones'])
            sample = {'direction': I.backproject(event['cones']), 'plane': plane_backproject(event['cones'])}
            for index, weight in enumerate(weights):
                counts[key][index] += weight
                if weight:
                    for kind in templates:
                        arrays[key][kind][index] += weight*np.asarray(sample[kind]['values'])
            processed += 1
            require(time.perf_counter()-began <= budget_seconds, 'Bootstrap stopped at the explicit compute budget; original analysis remains complete')
    require(processed == count, 'Bootstrap cone ledger census changed')
    samples = {key: {kind: [] for kind in templates} for key in groups}
    for key, g in groups.items():
        for index in range(n):
            for kind in templates:
                image = {**templates[kind], 'values': arrays[key][kind][index].tolist()}
                evaluation = evaluate(image, [g['truth_position_mm_for_evaluation_only']], [counts[key][index]], kind)
                samples[key][kind].append({'replicate': index, 'accepted_groups': counts[key][index],
                    'peak': evaluation['peaks'][0] if evaluation['peaks'] else None, 'bias': evaluation['global_peak_bias']})
            require(time.perf_counter()-began <= budget_seconds, 'Bootstrap stopped at the explicit compute budget; original analysis remains complete')
    return {'kind': 'gegi_campaign_bootstrap_v1', 'policy': policy, 'cost_receipt_sha256': sha(cost_receipt),
            'runtime_seconds': time.perf_counter()-began, 'groups': samples,
            'limitations': ['Conditional resampling of accepted primary clusters only; not an efficiency uncertainty or independent hardware validation.',
                           'All accepted pulse groups from a primary share a multiplier; all candidate cones retain their original relative weights.',
                           'No claim of a measured detector resolution or calibration uncertainty.']}


def analyze(campaign, output, *, root=None, allow_partial=False, allow_analysis_revision=False, bootstrap=False,
            bootstrap_cost_receipt=None, bootstrap_budget_seconds=None):
    import gegi_campaign as C
    import numpy as np
    root = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    campaign = C.local(campaign, root); output = C.local(output, root)
    require(output != campaign and not output.is_relative_to(campaign/'chunks') and not output.exists(),
            'Analysis needs a new derivative directory outside immutable chunks')
    plan = C.read_plan(campaign, root=root, verify=False)
    revision = validate_analysis_revision(plan, root=root, allow_analysis_revision=allow_analysis_revision)
    pins = source_hashes(root)
    require(not bootstrap or bootstrap_cost_receipt is not None and bootstrap_budget_seconds is not None,
            'Bootstrap is opt-in and requires a measured cost receipt plus explicit seconds budget')
    accumulator = Accumulator(plan['groups']); input_records = []; output.mkdir(parents=True)
    ledger_path = output/'cones.jsonl'
    with ledger_path.open('xb') as ledger:
        for chunk, folder, done, done_hash in sealed_chunks(campaign, plan, allow_partial=allow_partial, root=root):
            database = folder/'events.sqlite'; before = _stamp(database); identity = done['identity']
            store_ref = database.relative_to(campaign).as_posix(); response = done['response']
            require(response['calibration_sha256'] == identity['calibration_sha256']
                    and response['photopeak_windows_sha256'] == identity['photopeak_windows_sha256'], 'Response calibration/windows changed')
            with scalar_store(database, identity, response) as store:
                def records():
                    for primary_id, pulse_id in store.keys():
                        event, signals = store.read(primary_id, pulse_id, with_signals=False)
                        require(signals is None, 'Unexpected signal load')
                        if event['readout_recipe_sha256'] != response['readout_recipe_sha256']:
                            response_recipe_for_event(response, event)
                        yield primary_id, pulse_id, event
                accumulator.consume(chunk['source_group'], records(), declared_counts=response['counts'], identity=identity,
                    store_ref=store_ref, store_sha256=done['artifacts']['events.sqlite']['sha256'], ledger=ledger)
            require(_stamp(database) == before and sha(folder/'DONE.json') == done_hash, 'Sealed scalar input changed during analysis')
            input_records.append({'source_group': chunk['source_group'], 'chunk_index': chunk['chunk_index'],
                'done_ref': (folder/'DONE.json').relative_to(campaign).as_posix(), 'done_sha256': done_hash,
                'store_ref': store_ref, 'store_sha256': done['artifacts']['events.sqlite']['sha256'],
                'initial_primaries': response['counts']['initial_primaries'], 'radiation_seed': chunk['batch']['radiation_seed']})
    groups, maps = accumulator.results(); pairs, pair_maps = mixtures(groups, maps)
    processed = sum(g['initial_primary_denominator'] for g in groups.values())
    complete = (campaign/'COMPLETE.json').is_file() and processed == plan['total_initial_primaries']
    require(complete or allow_partial, 'Analysis is incomplete')
    if complete:
        declared = read(campaign/'COMPLETE.json')['groups']
        require(set(declared) == set(groups) and all(all(declared[key][name] == value for name, value in g['counts'].items())
                and all(declared[key][name] == value for name, value in g['transport_denominators'].items()) for key, g in groups.items()),
                'Aggregated scalar census differs from campaign COMPLETE')
    denominators = {}
    for g in groups.values():
        denominators[g['count_unit']] = denominators.get(g['count_unit'], 0)+g['initial_primary_denominator']
    summary = {'kind': KIND, 'status': 'complete' if complete else 'partial_sealed_chunks',
        'campaign_id': plan['campaign_id'], 'plan_sha256': sha(campaign/'plan.json'), 'physics_sha256': plan['physics_sha256'],
        'criteria': criteria(), 'source_sha256': pins, 'analysis_revision': revision,
        'source_recovery_sha256': plan.get('recovery', {}).get('sha256'),
        'quota_amendment_sha256': plan.get('quota_amendment', {}).get('sha256'),
        'numpy_version': np.__version__, 'inputs': input_records,
        'initial_denominators_by_unit': denominators, 'processed_initial_records': processed,
        'planned_initial_records': plan['total_initial_primaries'], 'groups': groups, 'mixtures': pairs,
        'count_scope': 'Group accepted/rejected counts partition every nonzero pulse group; primary outcome sets can overlap when a primary has multiple groups. Zeros remain in initial denominators only.',
        'failure_record_policy': 'Original native errors and unknown null channel/readout fields remain in the sealed scalar Store, addressed by unchanged primary and pulse-group IDs; no zero waveform is generated.',
        'validation_scope': 'Frozen plan, DONE identities, full Store/response hashes and sealed scalar completion; raw radiation archives are not decompressed or rescanned.',
        'limitations': ['Nominal cryostat and simulated pixel timing calibration; no experimental localization, range, activity or efficiency validation.',
            '5-degree kernel and 15-degree/15-mm truth-matching tolerances are fixed engineering analysis settings, not measured detector resolution.',
            'The z=40 mm plane is assumed; direction maps neglect vertex offset and are a far-field diagnostic at these nearby sources.',
            'Line membership uses fixed-gain readout energy only. Unknown failed/rejected energies are not assigned to isotope windows.',
            'Every isotope contributes to every observed-energy window when selected; source labels never remove continuum contamination.',
            'All candidate cones are preserved with equal weights per accepted pulse group; source truth never chooses a candidate.',
            'For an explicit source recovery, preserved groups keep their original wrapper/readout recipe hashes; exact event metadata selects the bound prior recipe.',
            'Mixtures combine independent equal-initial-source yields without inter-source pileup; photon and isotope-decay denominators remain separate.'],
        'bootstrap': {'requested': bootstrap, 'status': 'pending_explicit_run' if bootstrap else 'not_requested'}}
    require(source_hashes(root) == pins, 'Analysis source changed while processing')
    require(validate_analysis_revision(plan, root=root, allow_analysis_revision=allow_analysis_revision) == revision,
            'Analysis/producer source changed while processing')
    bodies = {'summary.json': summary, 'maps.json': {'kind': KIND, 'criteria': criteria(), 'groups': maps, 'mixtures': pair_maps}}
    for name, value in bodies.items():
        with (output/name).open('xb') as stream: stream.write(encoded(value))
    def seal_output():
        manifest = {'kind': KIND, 'status': summary['status'], 'plan_sha256': summary['plan_sha256'],
                    'source_sha256': pins, 'analysis_revision': revision,
                    'source_recovery_sha256': summary['source_recovery_sha256'], 'radiation_calls': 0, 'field_solves': 0,
                    'quota_amendment_sha256': summary['quota_amendment_sha256'],
                    'files': {p.name: {'sha256': sha(p), 'bytes': p.stat().st_size} for p in sorted(output.iterdir())
                              if p.is_file() and p.name != 'manifest.json'}}
        (output/'manifest.json').write_bytes(encoded(manifest))
    seal_output()
    # Optional bootstrap is a separate checked derivative. A budget stop never
    # deletes or invalidates the completed main summary/maps/cone ledger.
    if bootstrap:
        try:
            result = bootstrap_peaks(ledger_path, groups, cost_receipt=bootstrap_cost_receipt,
                                     budget_seconds=bootstrap_budget_seconds, root=root)
            with (output/'bootstrap.json').open('xb') as stream: stream.write(encoded(result))
            summary['bootstrap'].update(status='complete', output='bootstrap.json')
        except (ValueError, OSError) as error:
            summary['bootstrap'].update(status='failed', error=str(error), result=None)
        (output/'summary.json').write_bytes(encoded(summary)); seal_output()
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('criteria', 'analyze', 'bootstrap-cost'))
    parser.add_argument('--campaign', type=Path); parser.add_argument('--output', type=Path)
    parser.add_argument('--allow-partial', action='store_true'); parser.add_argument('--bootstrap', action='store_true')
    parser.add_argument('--allow-analysis-revision', action='store_true',
                        help='Admit only a changed analysis consumer; record both hashes and keep all producer/criteria pins exact')
    parser.add_argument('--bootstrap-cost-receipt', type=Path); parser.add_argument('--bootstrap-budget-seconds', type=float)
    parser.add_argument('--accepted-groups', type=int)
    args = parser.parse_args()
    if args.action == 'criteria':
        print(json.dumps(criteria(), indent=2))
    elif args.action == 'bootstrap-cost':
        require(args.output is not None, 'Choose a new local cost-receipt file')
        import gegi_campaign as C
        target = C.local(args.output); require(not target.exists(), 'Cost receipt already exists')
        value = measure_bootstrap_cost(args.accepted_groups); target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream: stream.write(encoded(value))
        print(json.dumps(value, indent=2))
    else:
        require(args.campaign is not None and args.output is not None, 'Campaign and new derivative output directory are required')
        summary = analyze(args.campaign, args.output, allow_partial=args.allow_partial, bootstrap=args.bootstrap,
            allow_analysis_revision=args.allow_analysis_revision,
            bootstrap_cost_receipt=args.bootstrap_cost_receipt, bootstrap_budget_seconds=args.bootstrap_budget_seconds)
        print(json.dumps({'kind': KIND, 'status': summary['status'], 'processed_initial_records': summary['processed_initial_records']}))
