"""Signal-derived two-site Compton backprojection, without truth ordering/positions.

The central-pixel depth table is an independent SSD timing approximation. A sky
map identifies direction, not source distance; angular smoothing is a display
kernel, not a measured resolution. Ambiguities and rejected nonzero events remain.
"""
from __future__ import annotations
import itertools
import math

ELECTRON_REST_KEV = 510.99895069
PITCH_MM = 4.937480624253117
MIN_COLLECTED_KEV = 5.0
PAIR_ABS_KEV = 2.0
PAIR_REL = 0.02
KERNEL_SIGMA_DEG = 5.0


def finite(x):
    return type(x) in (int, float) and math.isfinite(x)


def norm(v):
    return math.sqrt(sum(x*x for x in v))


def cone(first, second):
    """Axis points from second site toward first, toward possible source directions."""
    e1, e2 = first['energy_keV'], second['energy_keV']
    if not all(finite(e) and e > 0 for e in (e1, e2)):
        return None
    c = 1-ELECTRON_REST_KEV*(1/e2-1/(e1+e2))
    if not -1 <= c <= 1:
        return None
    axis = [a-b for a, b in zip(first['position_mm'], second['position_mm'])]
    distance = norm(axis)
    if not finite(distance) or distance < 1.0:
        return None
    return {'vertex_mm': first['position_mm'], 'axis': [x/distance for x in axis],
            'half_angle_deg': math.degrees(math.acos(c)), 'cos_theta': c,
            'scatter_energy_keV': e1, 'absorbed_energy_keV': e2,
            'site_separation_mm': distance}


def depth_from_timing(delta_ns, table):
    if not finite(delta_ns) or not isinstance(table, dict):
        return None
    depths, times = table.get('depth_mm'), table.get('ctd_ns')
    if not isinstance(depths, list) or not isinstance(times, list) or len(times) != len(depths) or len(times) < 3:
        return None
    if not all(finite(x) for x in depths+times):
        return None
    diffs = [b-a for a, b in zip(times, times[1:])]
    if not (all(d > 0 for d in diffs) or all(d < 0 for d in diffs)):
        return None
    pairs = sorted(zip(times, depths))
    if not pairs[0][0] <= delta_ns <= pairs[-1][0]:
        return None
    for (t0, z0), (t1, z1) in zip(pairs, pairs[1:]):
        if t0 <= delta_ns <= t1:
            return z0+(z1-z0)*(delta_ns-t0)/(t1-t0)
    return None


def collected(channel, wiring):
    final = channel.get('final_induced_keV')
    energy = channel.get('reconstructed_energy_keV')
    return (channel.get('accepted') is True and channel.get('collection_candidate') is True
            and finite(final) and final*wiring >= MIN_COLLECTED_KEV
            and finite(energy) and energy >= MIN_COLLECTED_KEV)


def reconstruct_event(event, channels, table, emission_energy_keV):
    """Never reads event.truth_edep_keV, original hit positions, or known source pose."""
    result = {'event_id': event['event_id'], 'status': 'rejected', 'reason': None, 'sites': [], 'cones': []}
    if event.get('status') != 'completed' or not isinstance(event.get('channels'), list):
        result['reason'] = 'native_response_incomplete'
        return result
    meta = {c['id']: c for c in channels}
    hits = [c for c in event['channels'] if c.get('contact_id') in meta
            and collected(c, meta[c['contact_id']]['wiring_factor'])]
    if any(c['contact_id'] in (17, 34) for c in hits):
        result['reason'] = 'guard_collection'
        return result
    xs = sorted((c for c in hits if 1 <= c['contact_id'] <= 16), key=lambda c: c['contact_id'])
    ys = sorted((c for c in hits if 18 <= c['contact_id'] <= 33), key=lambda c: c['contact_id'])
    if len(xs) != 2 or len(ys) != 2:
        result['reason'] = 'requires_two_resolved_strips_per_face'
        return result
    assignments = []
    for permutation in itertools.permutations(ys):
        if all(abs(x['reconstructed_energy_keV']-y['reconstructed_energy_keV']) <=
               max(PAIR_ABS_KEV, PAIR_REL*max(x['reconstructed_energy_keV'], y['reconstructed_energy_keV']))
               for x, y in zip(xs, permutation)):
            assignments.append(permutation)
    if len(assignments) != 1:
        result['reason'] = 'ambiguous_strip_pairing' if assignments else 'strip_energy_mismatch'
        return result
    sites = []
    for x, y in zip(xs, assignments[0]):
        tx, ty = x.get('t50_ns'), y.get('t50_ns')
        z = depth_from_timing(tx-ty if finite(tx) and finite(ty) else None, table)
        if z is None:
            result['reason'] = 'timing_outside_depth_calibration'
            return result
        # Each face measures the same deposited energy. Average matched faces;
        # summing faces would double count the event.
        energy = (x['reconstructed_energy_keV']+y['reconstructed_energy_keV'])/2
        sites.append({'position_mm': [(x['contact_id']-8.5)*PITCH_MM,
                                      (y['contact_id']-25.5)*PITCH_MM, z],
                      'energy_keV': energy, 'x_contact': x['contact_id'], 'y_contact': y['contact_id'],
                      'ctd_ns': tx-ty, 'method': 'strip_centres_and_independent_central_pixel_timing'})
    result['sites'] = sites
    total = sum(s['energy_keV'] for s in sites)
    if abs(total-emission_energy_keV) > max(5.0, 0.02*emission_energy_keV):
        result['reason'] = 'outside_configured_photopeak_window'
        return result
    candidates = []
    for order in ((0, 1), (1, 0)):
        value = cone(sites[order[0]], sites[order[1]])
        if value is not None:
            value.update(event_id=event['event_id'], order=list(order))
            candidates.append(value)
    if not candidates:
        result['reason'] = 'no_kinematically_valid_order'
        return result
    for candidate in candidates:
        candidate['weight'] = 1/len(candidates)
    result.update(status='accepted', reason=None, cones=candidates, ordering_ambiguous=len(candidates)>1)
    return result


def backproject(cones, *, step_deg=5, sigma_deg=KERNEL_SIGMA_DEG):
    """Equal probability per candidate; normalize over actual solid angle."""
    if step_deg <= 0 or sigma_deg <= 0:
        raise ValueError('Positive angular bin and kernel required')
    azimuth = [float(i) for i in range(-180, 180, step_deg)]
    elevation = [float(i)+step_deg/2 for i in range(-90, 90, step_deg)]
    values = [[0.0 for _ in azimuth] for _ in elevation]
    vectors = []
    areas = []
    for el in elevation:
        r = math.radians(el)
        vectors.append([(math.cos(r)*math.cos(math.radians(az)), math.cos(r)*math.sin(math.radians(az)), math.sin(r)) for az in azimuth])
        areas.append(math.radians(step_deg)*(math.sin(math.radians(el+step_deg/2))-math.sin(math.radians(el-step_deg/2))))
    for candidate in cones:
        rows = []
        for row in vectors:
            rows.append([math.exp(-0.5*((math.degrees(math.acos(max(-1., min(1., sum(a*b for a, b in zip(v, candidate['axis']))))))-candidate['half_angle_deg'])/sigma_deg)**2) for v in row])
        normalizer = sum(sum(row)*area for row, area in zip(rows, areas))
        if normalizer <= 0:
            continue
        for j, row in enumerate(rows):
            for i, value in enumerate(row):
                values[j][i] += candidate['weight']*value/normalizer
    return {'azimuth_deg': azimuth, 'elevation_deg': elevation, 'values': values,
            'solid_angle_per_cell_sr_by_row': areas, 'value_units': 'weighted accepted events per steradian',
            'kernel_sigma_deg': sigma_deg, 'bin_width_deg': step_deg}


def analyze(payload, selection):
    table = payload.get('depth_calibration')
    reconstructed = [reconstruct_event(e, payload['channels'], table, selection['gamma_energy_keV']) for e in payload['events']]
    cones = [c for event in reconstructed for c in event['cones']]
    rejected = {}
    for event, derived in zip(payload['events'], reconstructed):
        event['reconstruction'] = derived
        if derived['status'] == 'rejected':
            rejected[derived['reason']] = rejected.get(derived['reason'], 0)+1
    accepted = sum(e['status'] == 'accepted' for e in reconstructed)
    image = backproject(cones)
    image.update(method='signal_derived_two_site_compton_backprojection_v1',
                 coordinate_system='detector_xyz; +z front; azimuth atan2(y,x); elevation asin(z)',
                 cones=cones, accepted_events=accepted, rejected_events=len(reconstructed)-accepted,
                 ambiguous_events=sum(e.get('ordering_ambiguous', False) for e in reconstructed),
                 rejection_counts=rejected, initial_primaries=payload['counts']['initial_primaries'],
                 selection={'minimum_collected_energy_keV': MIN_COLLECTED_KEV, 'strip_pair_absolute_tolerance_keV': PAIR_ABS_KEV,
                            'strip_pair_relative_tolerance': PAIR_REL, 'photopeak_half_width_keV': max(5., .02*selection['gamma_energy_keV'])},
                 limitations=['Simulation-derived central-pixel timing-to-depth table; no per-pixel laboratory depth calibration.',
                              'Strip-centre transverse positions; charge sharing, unresolved same-strip sites and ambiguous strip pairs are excluded.',
                              'Only two resolved interactions and configured-line photopeak events are imaged; failed and rejected events remain in results.',
                              'Both valid orders are retained with equal weights, without selecting by the known source direction.',
                              'Directional backprojection only; source distance and activity are not reconstructed.',
                              '5-degree smoothing is an explicit imaging kernel, not a measured angular resolution; Doppler broadening and measured electronics noise are not modeled.'])
    payload['imaging'] = image
    return payload
