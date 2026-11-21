"""Original measured triggers, fitted interactions and projected order support."""

from contextlib import closing
import json
import zlib

import numpy as np

import gegi_candidate_storage as storage
import gegi_continuous_plane as PLANE
import gegi_joint_imaging as J

ANALYSIS_KIND = 'gegi_candidate_measured_imaging_v1'


def saved_events(saved, archive, *, require_full_scope=True):
    """Join saved fits to immutable trigger IDs and the archive's measured strip data."""
    old_rows = saved['triggers']
    receipt = saved['fit_receipt']
    analysis = saved['candidate_analysis']
    qualified = saved['selection']['qualified_triggers']
    acquired = [{} for _ in range(qualified)]
    joins = []
    ids = [row['original_trigger_id'] for row in old_rows]
    indices = [row['trigger_index'] for row in old_rows]
    scope, selected = analysis['scope'], analysis['selected_original_trigger_ids']
    if (scope not in ('all_two_strip_candidates', 'explicit_analysis_subset') or analysis['kind'] != ANALYSIS_KIND
            or require_full_scope and scope != 'all_two_strip_candidates'
            or scope == 'all_two_strip_candidates' and ids != selected
            or not set(selected) <= set(ids) or sorted(set(selected)) != selected or sorted(set(ids)) != ids
            or sorted(set(indices)) != indices or any(i < 1 or i > qualified for i in indices)
            or len(ids) != receipt['two_strip_triggers']
            or len(ids) != saved['selection']['two_strip_triggers']):
        raise ValueError('Expected the complete measured fit scope with unique original trigger IDs')
    with closing(storage._open_readonly(archive)) as db:
        for prior in old_rows:
            trigger_id = prior['original_trigger_id']
            stored = db.execute('SELECT record, adc_sha256, record_sha256 FROM triggers WHERE trigger_id=?',
                                (trigger_id,)).fetchone()
            if stored is None:
                raise ValueError(f'Original trigger {trigger_id} is missing from the candidate archive')
            body, adc_sha, record_sha = stored
            record = json.loads(zlib.decompress(body))
            if (storage._record_digest(record, adc_sha) != record_sha
                    or record['decision'] != 'candidate' or record['trigger_id'] != trigger_id
                    or record['trigger_time_ns'] != prior['trigger_time_ns']
                    or record['card']['energy_keV'] != prior['energy_keV']
                    or record['identities'] != prior['diagnostic_input_group_ordinals']):
                raise ValueError(f'Saved candidate differs from its archive record at trigger {trigger_id}')
            card = record['card']
            acquired[prior['trigger_index']-1] = card
            joins.append(dict(original_trigger_id=trigger_id, archive_record_sha256=record_sha,
                              archive_adc_sha256=adc_sha, input_group_ordinals=record['identities']))
    records, rows = PLANE.measured_events({'triggers': acquired}, receipt)
    for record, row, old, fit, join in zip(records, rows, old_rows, receipt['candidates'], joins, strict=True):
        # Rebuild only the cones, from saved measured energies and saved fitted XYZ.
        cones = iter(record['candidates'])
        for pair, previous in zip(row['pairings'], old['pairings'], strict=True):
            if any(pair.get(key) != previous.get(key) for key in ('index', 'cells', 'site_energies_keV', 'nominal_mass',
                    'waveform_fit_status', 'waveform_position_model', 'lateral_calibration_support', 'lateral_fallback_reason')):
                raise ValueError('Saved backprojection pairing does not reproduce from the archived measurements')
            for order, original in zip(pair['orders'], previous['orders'], strict=True):
                expected_status = 'available' if original['status'] in ('projected', 'no_plane_response') else original['status']
                if (order['status'] != expected_status or order['order'] != tuple(original['order'])
                        or order['nominal_mass'] != original['nominal_mass']):
                    raise ValueError(f"Saved order status or identity differs at trigger {join['original_trigger_id']}")
                if order['status'] == 'available':
                    geometry = {key: original[key] for key in PLANE.GEOMETRY_KEYS}
                    if not all(np.allclose(value, order[key], rtol=0., atol=1e-12) for key, value in geometry.items()):
                        raise ValueError(f"Saved geometry differs from its fit at trigger {join['original_trigger_id']}")
                    # Preserve the original coordinates to remove cross-platform libm roundoff.
                    order.update(geometry)
                    next(cones).update(geometry)
        record['event_id'] = join['original_trigger_id']
        row.update(join, fit_flags=fit['flags'], saved_projected_mass=old['projected_mass'])
        measured_pairs = acquired[row['trigger_index']-1]['two_strip_pairings']['pairings']
        for pair in row['pairings']:
            fitted = next(p['fit'] for p in fit['pairings'] if p['index'] == pair['index'])
            measured = next(p for p in measured_pairs if p['index'] == pair['index'])
            pair['strip_energy_residuals_keV'] = [site['x_minus_y_energy_keV'] for site in measured['sites']]
            pair['fit_contacts'] = fitted.get('contacts')
            pair['center_fit_diagnostics'] = {kind: models['center'] for kind, models in fitted.get('fits', {}).items()}
            if 'lateral_calibration_support' in pair:
                pair['lateral_fit_diagnostics'] = {kind: value for kind, value in fitted.get('fits', {}).get('waveform', {}).items()
                                                   if kind != 'center'}
    return records, rows


def events_from_saved(saved, archive, settings=None, *, require_full_scope=True):
    """Return prepared events with original trigger IDs and their measured ledgers."""
    model = saved['model']
    settings = settings or J.ResponseSettings(angular_nuisance_sigma_deg=model['angular_nuisance_sigma_deg'])
    settings.validate()
    if settings.strip_pitch_mm != model['strip_pitch_mm']:
        raise ValueError('The saved plane used a different detector strip pitch')
    records, rows = saved_events(saved, archive, require_full_scope=require_full_scope)
    return J.prepare_events(records, settings), rows


def projected_order(candidate, points, settings, prior_weights):
    """Return the original normalized available-order contribution on this grid."""
    valid = np.linalg.norm(points-candidate.vertex, axis=1) > 1e-9
    kernel = J.candidate_response(candidate, points[valid], settings)
    if prior_weights is not None:
        kernel *= prior_weights[valid]
    norm = float(kernel.sum())
    if norm <= 0:
        return valid, kernel
    return valid, candidate.prior*(kernel/norm)


def peak_cell_contributors(saved, archive, label):
    """Attribute the saved maximum to measured triggers and fitted orders."""
    grid, model = saved['grid'], saved['model']
    layer = saved['layers'][label]
    peak_index = int(np.argmax(layer['mass']))
    peak_mass = float(np.asarray(layer['mass']).ravel()[peak_index])
    if peak_mass <= 0:
        return dict(peak=None, contributors=[])
    ticks, points = J.plane_grid(grid['extent_mm'], grid['step_mm'], grid['assumed_z_mm'])
    if grid['x_mm'] != ticks.tolist() or grid['y_mm'] != ticks.tolist():
        raise ValueError('Saved map grid differs from its source-plane settings')
    settings = J.ResponseSettings(angular_nuisance_sigma_deg=model['angular_nuisance_sigma_deg'])
    events, rows = events_from_saved(saved, archive, settings, require_full_scope=False)
    mask = np.ones(len(events), dtype=bool) if label == 'all' else J.spectral_membership(events, PLANE.LINE_ENERGIES_KEV)[label]
    if int(mask.sum()) != layer['triggers']:
        raise ValueError('Saved measured-energy window membership differs from its trigger census')
    prior = model['plane_prior']
    weights = None if prior == PLANE.DEFAULT_PLANE_PRIOR else PLANE.plane_prior_weights(points, grid['step_mm'], prior)
    contributions = []
    for index in np.flatnonzero(mask):
        event, row = events[index], rows[index]
        candidates = iter(event.candidates)
        pairs = []
        for pair in row['pairings']:
            orders = []
            for order in pair['orders']:
                mass = 0.
                if order['status'] == 'available':
                    valid, values = projected_order(next(candidates), points, settings, weights)
                    if valid[peak_index]:
                        mass = float(values[np.count_nonzero(valid[:peak_index])])
                orders.append(dict(order, peak_cell_mass=mass))
            pairs.append(dict(pair, orders=orders))
        mass = sum(order['peak_cell_mass'] for pair in pairs for order in pair['orders'])
        if mass > 0:
            contributions.append(dict(row, pairings=pairs, peak_cell_mass=mass, peak_cell_share=mass/peak_mass))
    if not np.isclose(sum(row['peak_cell_mass'] for row in contributions), peak_mass, rtol=0., atol=1e-12):
        raise ValueError('Order contributions do not reproduce the saved brightest cell')
    contributions.sort(key=lambda row: (-row['peak_cell_mass'], row['original_trigger_id']))
    xy = points[peak_index].tolist()
    return dict(peak=dict(position_mm=xy, mass=peak_mass,
                          on_image_edge=bool(abs(xy[0]) == ticks[-1] or abs(xy[1]) == ticks[-1])),
                contributors=contributions)
