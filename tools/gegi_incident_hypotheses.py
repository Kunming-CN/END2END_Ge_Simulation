"""Nominal Compton energy checks on two measured cell energies."""

import math

from gegi_imaging import ELECTRON_REST_KEV, finite


ORDERS = ((0, 1), (1, 0))


def configuration(incident_energies_keV):
    energies = list(incident_energies_keV)
    if any(not finite(value) or value <= 0 for value in energies) or len(set(energies)) != len(energies):
        raise ValueError('Supply distinct, finite, positive incident energies in keV')
    return {
        'kind': 'gegi_two_cell_incident_line_kinematics_v1',
        'incident_energies_keV': energies,
        'electron_rest_energy_keV': ELECTRON_REST_KEV,
        'observed_sum_full_absorption': 'One Compton scatter followed by full absorption. Incident energy is the sum of the two cells.',
        'incident_line_closure': 'The signed difference is measured cell sum minus the specified incident energy. No tolerance or line assignment is applied.',
        'two_resolved_scatter_escape': 'At each cell a single scatter deposits its measured energy. Escaping photon energy must stay positive.',
        'assumptions': 'Free stationary electrons and nominal cell energies. Uncertainties, charge loss, prior scatters, merged scatters '
                       'and mixed photons are outside these point-hypothesis calculations. The angles are conditional kinematics.',
        'references_doi': ['10.1109/TNS.2020.3005834', '10.1016/j.astropartphys.2022.102765', '10.1088/1361-6560/adaacc'],
    }


def scatter(incoming, deposit, outgoing):
    """Keep signed margins and raw cosines for failed nominal hypotheses."""
    cosine = 1 - (ELECTRON_REST_KEV / incoming) * (deposit / outgoing) if incoming > 0 and outgoing > 0 else None
    admissible = cosine is not None and -1 <= cosine <= 1
    backscatter_limit = incoming * (incoming / (incoming + ELECTRON_REST_KEV/2)) if incoming > 0 else None
    return {'incoming_photon_keV': incoming, 'deposited_keV': deposit, 'outgoing_photon_keV': outgoing,
            'positive_outgoing_photon_energy': outgoing > 0,
            'raw_cosine': cosine,
            'backscatter_energy_margin_keV': backscatter_limit - deposit if backscatter_limit is not None else None,
            'nominally_admissible': admissible,
            'scatter_angle_deg': math.degrees(math.acos(cosine)) if admissible else None}


def minimum_incoming(deposit):
    """Invert the maximum recoil energy in a 180 degree scatter."""
    half = deposit/2
    return half + math.sqrt(half) * math.sqrt(half + ELECTRON_REST_KEV)


def two_scatter_escape(energies, order, incident_energy, escape_energy):
    first, second = (energies[i] for i in order)
    after_first = incident_energy - first
    scatters = [scatter(incident_energy, first, after_first), scatter(after_first, second, escape_energy)]
    minimum_energy = max(minimum_incoming(first), first + minimum_incoming(second))
    return {'site_index_order': order, 'scatters': scatters,
            'minimum_incident_energy_keV': minimum_energy,
            'incident_minus_minimum_keV': incident_energy - minimum_energy,
            'nominally_admissible': all(step['nominally_admissible'] for step in scatters)}


def evaluate(energies, incident_energies_keV, *, unavailable=None):
    """Evaluate both cell orders without using positions, sequence truth, or weights."""
    result = {'status': unavailable or 'evaluated',
              'unresolved_or_mixed': {'direction': None, 'status': 'physical_sequence_unidentified'}}
    if unavailable is not None:
        return result
    if len(energies) != 2 or any(not finite(value) or value <= 0 for value in energies):
        raise ValueError('Exactly two finite, positive measured cell energies are required')
    total = math.fsum(energies)
    result['measured_cell_sum_keV'] = total
    result['observed_sum_full_absorption_orders'] = [
        {'site_index_order': order, 'absorbed_keV': energies[order[1]],
         'first_scatter': scatter(total, energies[order[0]], energies[order[1]])}
        for order in ORDERS]
    lines = []
    for energy in incident_energies_keV:
        remaining = math.fsum((energy, -energies[0], -energies[1]))
        lines.append({
            'incident_energy_keV': energy, 'observed_sum_minus_incident_keV': -remaining,
            'escape_photon_energy_keV': remaining, 'positive_escape_photon_energy': remaining > 0,
            'two_resolved_scatter_escape_orders': [two_scatter_escape(energies, order, energy, remaining) for order in ORDERS],
        })
    result['incident_line_hypotheses'] = lines
    return result
