"""Draw one shared outgoing-energy atom from the empirical joint measure."""

import math

import numpy as np

from gegi_empirical_compton_joint import joint_nodes
from gegi_photon_continuation import ELECTRON_REST_KEV


def sample_conditional_atom(kernel, incident_keV, cosine, unit, model=None):
    """Use one uniform coordinate on [0, 1) to draw E' at the supplied cosine.

    Pass the same E' to both the second-path rates and subsequent scatter or
    absorption. The angle is a conditioning variable here, so the returned
    angular density per steradian still multiplies a uniform-ray integrand.
    An existing angular model may be reused for the same kernel and line.
    """
    if not math.isfinite(unit) or not 0. <= unit < 1.:
        raise ValueError('The conditional atom coordinate must lie in [0, 1)')
    prediction = joint_nodes(kernel, incident_keV, cosine, model)
    weights = prediction['weights']
    angular = prediction['angular_density_per_sr']
    result = dict(status=prediction['status'], outgoing_keV=None, angular_density_per_sr=angular,
                  native_first_scatter_electron_rest_keV=kernel['native_metadata']['native_electron_rest_keV'],
                  free_second_scatter_electron_rest_keV=ELECTRON_REST_KEV)
    if weights is None:
        return result
    energies = prediction['outgoing_energies_keV']
    mass = math.fsum(weights)
    if (not math.isfinite(angular) or angular <= 0 or not np.isfinite(energies).all()
            or np.any((energies <= 0) | (energies > incident_keV))
            or not np.isfinite(weights).all() or np.any(weights <= 0)
            or not math.isclose(mass, 1., rel_tol=0., abs_tol=8*np.finfo(float).eps)):
        raise ValueError('Require physical atom energies and positive, normalized conditional mass')
    cumulative = np.cumsum(weights)/mass
    cumulative[-1] = 1.
    index = int(np.searchsorted(cumulative, unit, side='right'))
    return result | dict(status='sampled', outgoing_keV=float(energies[index]), atom_index=index,
                         conditional_atom_mass=float(weights[index]), conditional_mass=mass)
