"""Signal-derived two-site Compton backprojection, without truth ordering/positions.

Independent SSD depth tables remain simulated timing approximations. A sky
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
    if not all(b > a for a, b in zip(depths, depths[1:])):
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


def pixel_depth_table(table, x, y):
    """Resolve a declared pixel calibration without using interaction truth.

    Pixel schema v1 has ``pixels['X_ID:Y_ID']`` entries containing contact_ids,
    depth_mm, ctd_ns and status. Its timing_method is inherited by each entry.
    A missing/invalid pixel never falls back to a central-pixel table.
    """
    if not isinstance(table, dict):
        return None, None, 'depth_calibration_unavailable'
    pixel_mode = (table.get('per_pixel_calibration') is True or 'pixels' in table
                  or table.get('kind') == 'gegi_pixel_simulated_depth_v1')
    selected = table
    if pixel_mode:
        if table.get('kind') != 'gegi_pixel_simulated_depth_v1' or table.get('per_pixel_calibration') is not True:
            return None, None, 'invalid_pixel_depth_calibration'
        pixels = table.get('pixels')
        key = f"{x['contact_id']}:{y['contact_id']}"
        selected = pixels.get(key) if isinstance(pixels, dict) else None
        if not isinstance(selected, dict):
            return None, None, 'pixel_depth_calibration_missing'
        if (selected.get('contact_ids') != [x['contact_id'], y['contact_id']]
                or selected.get('status') != 'available_model_approximation'):
            return None, None, 'invalid_pixel_depth_calibration'
    elif table.get('status', 'available_model_approximation') != 'available_model_approximation':
        return None, None, 'depth_calibration_unavailable'
    timing = selected.get('timing_method', table.get('timing_method'))
    if (pixel_mode and not isinstance(timing, str)) or (timing is not None and
            (x.get('timing_method') != timing or y.get('timing_method') != timing)):
        return None, None, 'depth_timing_method_mismatch'
    # Validate the entire relation, independently of the observed event timing.
    times = selected.get('ctd_ns')
    if not isinstance(times, list) or not times or depth_from_timing(times[0], selected) is None:
        return None, None, 'invalid_pixel_depth_calibration' if pixel_mode else 'depth_calibration_unavailable'
    method = ('strip_centres_and_independent_pixel_timing' if pixel_mode else
              'strip_centres_and_independent_central_pixel_timing')
    return selected, method, None


def photopeak_windows(energy_or_windows):
    """Fixed line hypotheses; never infer a line from emitted/deposited truth."""
    if finite(energy_or_windows) and energy_or_windows > 0:
        return [{'line_energy_keV': energy_or_windows,
                 'half_width_keV': max(5.0, 0.02*energy_or_windows)}]
    if not isinstance(energy_or_windows, list) or not energy_or_windows:
        raise ValueError('Provide a positive gamma energy or explicit photopeak windows')
    result = []
    for window in energy_or_windows:
        if (not isinstance(window, dict) or set(window) != {'line_energy_keV', 'half_width_keV'}
                or not finite(window['line_energy_keV']) or window['line_energy_keV'] <= 0
                or not finite(window['half_width_keV']) or not 0 < window['half_width_keV'] < window['line_energy_keV']):
            raise ValueError('Invalid fixed photopeak window')
        result.append(dict(window))
    return result


def terminal_collection(channel, wiring):
    final = channel.get('final_induced_keV')
    return (channel.get('collection_candidate') is True
            and finite(final) and final*wiring >= MIN_COLLECTED_KEV)


def collected(channel, wiring):
    energy = channel.get('reconstructed_energy_keV')
    return (channel.get('accepted') is True and terminal_collection(channel, wiring)
            and finite(energy) and energy >= MIN_COLLECTED_KEV)


def reconstruct_event(event, channels, table, emission_energy_keV):
    """Never reads event.truth_edep_keV, original hit positions, or known source pose."""
    windows = photopeak_windows(emission_energy_keV)
    result = {'event_id': event['event_id'], 'status': 'rejected', 'reason': None, 'sites': [], 'cones': []}
    if event.get('status') != 'completed' or not isinstance(event.get('channels'), list):
        result['reason'] = 'native_response_incomplete'
        return result
    meta = {c['id']: c for c in channels}
    collectors = [c for c in event['channels'] if c.get('contact_id') in meta
                  and terminal_collection(c, meta[c['contact_id']]['wiring_factor'])]
    hits = [c for c in event['channels'] if c.get('contact_id') in meta
            and collected(c, meta[c['contact_id']]['wiring_factor'])]
    if any(c['contact_id'] in (17, 34) for c in collectors):
        result['reason'] = 'guard_collection'
        return result
    if any(not collected(c, meta[c['contact_id']]['wiring_factor']) for c in collectors):
        result['reason'] = 'collecting_strip_readout_rejected'
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
    if not assignments:
        result['reason'] = 'strip_energy_mismatch'
        return result
    # Each face measures the same event energy. Never sum the two faces.
    total = sum(c['reconstructed_energy_keV'] for c in xs+ys)/2
    matches = [w['line_energy_keV'] for w in windows if abs(total-w['line_energy_keV']) <= w['half_width_keV']]
    if not matches:
        result['reason'] = 'outside_configured_photopeak_window'
        return result
    candidates, hypotheses, rejected_pairings = [], [], []
    for index, assignment in enumerate(assignments):
        sites, reason = [], None
        for x, y in zip(xs, assignment):
            relation, method, reason = pixel_depth_table(table, x, y)
            if reason:
                break
            tx, ty = x.get('t50_ns'), y.get('t50_ns')
            z = depth_from_timing(tx-ty if finite(tx) and finite(ty) else None, relation)
            if z is None:
                reason = 'timing_outside_depth_calibration'
                break
            # Strip coordinates come from the versioned detector metadata.
            # The fallback preserves legacy records that predate those fields.
            px = meta[x['contact_id']].get('strip_center_mm', (x['contact_id']-8.5)*PITCH_MM)
            py = meta[y['contact_id']].get('strip_center_mm', (y['contact_id']-25.5)*PITCH_MM)
            if not finite(px) or not finite(py):
                reason = 'invalid_strip_coordinates'
                break
            sites.append({'position_mm': [px, py, z],
                          'energy_keV': (x['reconstructed_energy_keV']+y['reconstructed_energy_keV'])/2,
                          'x_contact': x['contact_id'], 'y_contact': y['contact_id'],
                          'ctd_ns': tx-ty, 'method': method})
        pair_cones = []
        if reason is None:
            for order in ((0, 1), (1, 0)):
                value = cone(sites[order[0]], sites[order[1]])
                if value is not None:
                    value.update(event_id=event['event_id'], pairing_index=index, order=list(order))
                    pair_cones.append(value)
            if not pair_cones:
                reason = 'no_kinematically_valid_order'
        if reason:
            rejected_pairings.append({'pairing_index': index, 'reason': reason,
                                      'contact_pairs': [[x['contact_id'], y['contact_id']] for x, y in zip(xs, assignment)]})
        else:
            hypotheses.append({'pairing_index': index, 'sites': sites, 'valid_order_count': len(pair_cones)})
            candidates.extend(pair_cones)
    result['rejected_pairings'] = rejected_pairings
    calibration_failures = [p for p in rejected_pairings if p['reason'] != 'no_kinematically_valid_order']
    if calibration_failures:
        # Missing support is not evidence that an alternative pairing is right.
        # Do not manufacture a unique solution by dropping an uncalibrated one.
        reasons = {p['reason'] for p in calibration_failures}
        result['reason'] = next(iter(reasons)) if len(reasons) == 1 else 'incomplete_strip_pairing_calibration'
        return result
    if not candidates:
        reasons = {p['reason'] for p in rejected_pairings}
        result['reason'] = next(iter(reasons)) if len(reasons) == 1 else 'no_valid_strip_pairing_hypothesis'
        return result
    # Uniform hypothesis weights are a declared convention, not a calibrated
    # posterior probability. No source direction or truth ordering breaks ties.
    for candidate in candidates:
        candidate['weight'] = 1/len(candidates)
    result.update(status='accepted', reason=None, cones=candidates,
                  sites=hypotheses[0]['sites'] if len(hypotheses) == 1 else [],
                  paired_site_hypotheses=hypotheses, pairing_ambiguous=len(hypotheses)>1,
                  photopeak_matches_keV=matches,
                  ordering_ambiguous=any(p['valid_order_count'] > 1 for p in hypotheses))
    return result


def backproject(cones, *, step_deg=5, sigma_deg=KERNEL_SIGMA_DEG):
    """Declared candidate weights; normalize over actual solid angle."""
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
    windows = photopeak_windows(selection.get('photopeak_windows', selection.get('gamma_energy_keV')))
    reconstructed = [reconstruct_event(e, payload['channels'], table, windows) for e in payload['events']]
    cones = [c for event in reconstructed for c in event['cones']]
    rejected = {}
    for event, derived in zip(payload['events'], reconstructed):
        event['reconstruction'] = derived
        if derived['status'] == 'rejected':
            rejected[derived['reason']] = rejected.get(derived['reason'], 0)+1
    accepted = sum(e['status'] == 'accepted' for e in reconstructed)
    image = backproject(cones)
    image.update(method='signal_derived_two_site_compton_backprojection_v2',
                 coordinate_system='detector_xyz; +z front; azimuth atan2(y,x); elevation asin(z)',
                 cones=cones, accepted_events=accepted, rejected_events=len(reconstructed)-accepted,
                 ambiguous_events=sum(e.get('ordering_ambiguous', False) or e.get('pairing_ambiguous', False) for e in reconstructed),
                 ordering_ambiguous_events=sum(e.get('ordering_ambiguous', False) for e in reconstructed),
                 pairing_ambiguous_events=sum(e.get('pairing_ambiguous', False) for e in reconstructed),
                 rejection_counts=rejected, initial_primaries=payload['counts']['initial_primaries'],
                 selection={'minimum_collected_energy_keV': MIN_COLLECTED_KEV, 'strip_pair_absolute_tolerance_keV': PAIR_ABS_KEV,
                            'strip_pair_relative_tolerance': PAIR_REL, 'photopeak_windows': windows,
                            'photopeak_half_width_keV': windows[0]['half_width_keV'] if len(windows) == 1 else None},
                 limitations=['Simulation-derived timing-to-depth tables; per-pixel tables are used only when explicitly supplied, otherwise the legacy central-pixel approximation applies. No laboratory depth calibration.',
                              'Strip-centre transverse positions; unresolved same-strip sites and charge-sharing decompositions are excluded.',
                              'Only two resolved interactions and fixed configured-line photopeak windows are imaged; failed and rejected events remain in results.',
                              'All valid strip-pair/order hypotheses are retained with equal cone weights summing to one per event; weights are not calibrated probabilities.',
                              'No hypothesis is selected using source direction, true interaction positions, ordering or emitted energy.',
                              'Directional backprojection only; source distance and activity are not reconstructed.',
                              '5-degree smoothing is an explicit imaging kernel, not a measured angular resolution; Doppler broadening and measured electronics noise are not modeled.'])
    payload['imaging'] = image
    return payload
