"""Two-site energy assignments from GeGI digital strip observables."""

import gegi_imaging as I
from gegi_substrip import infer_position


KIND = 'gegi_digital_two_site_pairings_v1'


def slow_collectors(digital):
    """Return the shared collecting-strip census and unknown slow channels."""
    hits, invalid = {}, []
    for row in digital['channels']:
        cid, energy = row['contact_id'], row.get('slow_energy_keV')
        if I.finite(energy):
            if energy >= I.MIN_COLLECTED_KEV:
                hits[cid] = energy
        elif energy is not None or 'slow_below_threshold' not in row.get('flags', []):
            invalid.append(cid)
    return hits, sorted(invalid)


def _neighborhood_flags(xs, ys, metadata):
    flags = []
    for family, contacts in (('X', xs), ('Y', ys)):
        strips = {row['id'] for row in metadata if row['family'] == family and not row['guard']}
        a, b = ({cid - 1, cid, cid + 1} & strips for cid in contacts)
        if a & b:
            flags.append(f'overlapping_{family.lower()}_neighborhoods')
        if len(a) != 3 or len(b) != 3:
            flags.append(f'incomplete_{family.lower()}_neighborhood')
    return flags


def _site(x, y, hits):
    ex, ey = hits[x], hits[y]
    difference = ex - ey
    tolerance = max(I.PAIR_ABS_KEV, I.PAIR_REL * max(ex, ey))
    return {'x_contact_id': x, 'y_contact_id': y, 'x_energy_keV': ex, 'y_energy_keV': ey,
            'x_minus_y_energy_keV': difference, 'energy_tolerance_keV': tolerance,
            'energy_compatible': abs(difference) <= tolerance, 'energy_keV': (ex + ey) / 2,
            'position_mm': None, 'position': None}


def _positions(sites, digital, metadata, calibration, source_identity, flags):
    if flags:
        return
    if calibration is None:
        flags.extend(('position_calibration_unavailable', 'missing_z'))
        return
    evaluation = calibration.get('evaluation') or {}
    if (evaluation.get('kind'), evaluation.get('mode')) != (
            'independent_same_model_saved_injection_check', 'cfd_conditioned'):
        flags.extend(('position_calibration_not_evaluated', 'missing_z'))
        return
    for site in sites:
        position = infer_position(calibration, site['x_contact_id'], site['y_contact_id'], digital, metadata,
                                  source_identity=source_identity, mode='cfd_conditioned')
        site['position'] = position
        axes = [position[axis] for axis in ('x', 'y', 'depth')]
        x_ok, y_ok, z_ok = (a['status'] == 'estimated' and I.finite(a['position_mm']) for a in axes)
        if not z_ok:
            flags.append('missing_z')
        if not (x_ok and y_ok):
            flags.append('missing_xy')
        if position['calibration_source_status'] != 'matching_saved_fields':
            flags.append('position_calibration_fields_not_exact')
        elif position['calibration_pair_coverage'] != 'simulated_pair':
            flags.append('position_calibration_pair_not_sampled')
        elif x_ok and y_ok and z_ok:
            site['position_mm'] = [axis['position_mm'] for axis in axes]


def two_site_pairings(digital, channel_metadata, *, calibration=None, source_identity=None):
    """Keep both permutations for a two-strip-per-face digital pulse."""
    hits, invalid = slow_collectors(digital)
    result = {'kind': KIND, 'status': 'unresolved', 'reason': None, 'flags': [],
              'threshold_keV': I.MIN_COLLECTED_KEV, 'collecting_contact_ids': sorted(hits),
              'invalid_slow_contact_ids': invalid, 'x_contact_ids': [], 'y_contact_ids': [],
              'energy_keV': None, 'compatible_pairing_count': 0, 'pairings': [],
              'cone_scope': 'Conditional on one fully absorbed photon and isolated pulse neighborhoods. Both orders are checked.'}
    xs, ys = (sorted(c['id'] for c in channel_metadata if c['family'] == family and not c['guard']
                     and c['id'] in hits) for family in ('X', 'Y'))
    result.update(x_contact_ids=xs, y_contact_ids=ys)
    if any(c['guard'] and c['id'] in hits for c in channel_metadata):
        result['reason'] = 'guard_collection'
    elif invalid:
        result['reason'] = 'invalid_slow_channels'
    elif len(xs) != 2 or len(ys) != 2:
        result['reason'] = 'requires_two_resolved_strips_per_face'
    if result['reason']:
        return result

    overlap = _neighborhood_flags(xs, ys, channel_metadata)
    result['energy_keV'] = sum(hits[cid] for cid in xs + ys) / 2
    for index, permutation in enumerate((ys, ys[::-1])):
        sites = [_site(x, y, hits) for x, y in zip(xs, permutation)]
        compatible = all(site['energy_compatible'] for site in sites)
        pairing = {'index': index, 'energy_compatible': compatible, 'flags': list(overlap),
                   'sites': sites, 'cones': [], 'rejected_orders': []}
        result['pairings'].append(pairing)
        if not compatible:
            pairing['flags'].append('strip_energy_mismatch')
            continue
        result['compatible_pairing_count'] += 1
        _positions(sites, digital, channel_metadata, calibration, source_identity, pairing['flags'])
        pairing['flags'] = list(dict.fromkeys(pairing['flags']))
        if any(site['position_mm'] is None for site in sites):
            continue
        for order in ((0, 1), (1, 0)):
            cone = I.cone(*(sites[i] for i in order))
            if cone is None:
                pairing['rejected_orders'].append({'site_index_order': list(order),
                                                   'reason': 'invalid_compton_kinematics_or_separation'})
            else:
                pairing['cones'].append(dict(cone, site_index_order=list(order)))

    count = result['compatible_pairing_count']
    result['status'] = ('incompatible_energies', 'unique_energy_pairing', 'ambiguous_energy_pairing')[count]
    result['flags'] = list(dict.fromkeys(overlap + [flag for row in result['pairings'] if row['energy_compatible']
                                                   for flag in row['flags']]))
    if not count:
        result['reason'] = 'strip_energy_mismatch'
    return result
