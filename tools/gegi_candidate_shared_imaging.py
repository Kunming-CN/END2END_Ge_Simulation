"""Conditional 1×2 and 2×1 backprojection from the existing shared-strip fit."""

import gegi_candidate_shared_topology as shared
import gegi_continuous_plane as plane
import gegi_digital_pairs as pairs


KIND = 'gegi_candidate_shared_strip_plane_v1'


def measured_events(triggers):
    records, accounting = [], []
    for row in triggers:
        trigger_id = row['original_trigger_id']
        energy = row['original_measured_energy_keV']
        fit = row['fit']
        allocation = row['conditional_energy_allocation']
        record = dict(event_id=trigger_id, energy_keV=energy, candidates=[])
        ledger = dict(original_trigger_id=trigger_id, trigger_time_ns=row['trigger_time_ns'],
                      energy_keV=energy, adc_window_status=row['adc_window_status'], fit_status=fit['status'],
                      archive_record_sha256=row['archive_record_sha256'], archive_adc_sha256=row['archive_adc_sha256'],
                      x_collecting_strips=row['original_x_collecting_strips'],
                      y_collecting_strips=row['original_y_collecting_strips'], pairings=[])
        records.append(record)
        accounting.append(ledger)
        if allocation['status'] != 'energy_qualified':
            continue

        energies = allocation['site_energies_keV']
        kinematics = pairs.compton_orders([{'energy_keV': value} for value in energies])
        allowed = sum(order['kinematically_allowed'] for order in kinematics)
        solutions = {tuple(order['site_index_order']): order['conditional_cone']
                     for order in fit.get('conditional_orders', ())}
        pairing = dict(cells=allocation['cells'], site_energies_keV=energies, nominal_mass=1.,
                       kinematic_orders=kinematics, orders=[])
        if fit['status'] == 'scored':
            pairing.update(site_positions_mm=fit['fit']['site_positions_mm'],
                           global_adc_rms_codes=fit['global_adc_rms_codes'],
                           depth_boundary_sites=fit['fit']['depth_boundary_sites'],
                           onset_at_boundary=fit['fit']['onset_at_boundary'])
        ledger['pairings'].append(pairing)
        for item in kinematics:
            if not item['kinematically_allowed']:
                continue
            order = item['site_index_order']
            geometry = solutions.get(tuple(order))
            entry = dict(order=order, nominal_mass=1/allowed, status='no_waveform_fit')
            if fit['status'] == 'scored':
                entry['status'] = 'no_usable_cone'
            if geometry is not None:
                entry.update(status='available', **{key: geometry[key] for key in plane.GEOMETRY_KEYS})
                record['candidates'].append(dict(geometry, prior_weight=entry['nominal_mass']))
            pairing['orders'].append(entry)
    return records, accounting


def project(acquisition, result, **settings):
    """Project existing fit results without reopening waveform or calibration arrays."""
    records, ledger = measured_events(result['triggers'])
    projected = plane._project(acquisition, records, ledger, len(records), **settings)
    omitted = result['omitted_original_trigger_count']
    return {
        'kind': KIND,
        'scope': 'explicit_shared_strip_subset' if omitted else 'all_shared_strip_candidates',
        'population': result['complete_saved_candidate_population'],
        'omitted_original_trigger_count': omitted,
        'fit_status_counts': result['fit_status_counts'],
        'model': projected['model'] | {
            'geometry': 'The two separate strips divide the measured face-average energy. The original all-electrode '
                        'waveform fits two strip-center positions in depth with a common onset.',
            'ambiguity': 'One nominal unit per shared-strip trigger. Share it equally among kinematically allowed '
                         'orders of the conditional two-site full-absorption model. Unavailable mass stays unresolved. '
                         'Charge sharing and additional interactions can produce the same collecting-strip pattern.',
        },
        'layers': projected['layers'],
        'triggers': projected['triggers'],
    }


def reconstruct(acquisition, report, database, manifest, templates, trigger_ids, **settings):
    fits = shared.run(report, database, manifest, templates, trigger_ids)
    return project(acquisition, fits, **settings)
