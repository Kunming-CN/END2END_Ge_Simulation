"""Conditional two-site response for an explicit trial point and incident line.

See Yoneda et al., https://arxiv.org/html/2107.01846, Eqs. 8–17 and 20, 23.
The propagation directions are source to r1 and r1 to r2. Their dot product
sets the free-electron Compton energy E' after r1. The first observation is
Gaussian about E0-E'. Multiply its density (keV^-1), normalized first
Klein–Nishina density (sr^-1), and the measured second-site response
(mm^-1 keV^-1). At fixed r1, dV2 = L12^2 dL12 dOmega, so divide by L12^2
to obtain both branches in mm^-3 keV^-2, with solid angle dimensionless.

This conditions on a first Compton interaction at the given r1. It omits
the first-vertex flux/rate and entrance or passive-material attenuation,
the candidate-selection normalizer, positional uncertainty and Doppler
broadening. The accepted second-site model includes Ge survival and exit.
The energy widths are explicit analytic inputs. These densities do not
normalize a selected acquisition or assign probabilities to event models.
"""

import math

import numpy as np

import gegi_photon_continuation as photon
from gegi_photon_log_response import density_evidence, gaussian_log_density_per_kev
from gegi_photon_observed_energy import gaussian_density_per_kev, observed_continuation


def first_compton_state(source_mm, first_mm, second_mm, incident_keV):
    """Find the intermediate energy from trial geometry, without measured energies."""
    points = np.asarray([source_mm, first_mm, second_mm], dtype=float)
    if points.shape != (3, 3) or not np.isfinite(points).all():
        raise ValueError('Supply three finite XYZ positions in millimeters')
    if not math.isfinite(incident_keV) or incident_keV <= 0:
        raise ValueError('Supply a positive finite incident energy in keV')
    source, first, second = points
    incoming = first-source
    outgoing = second-first
    to_first = math.hypot(*incoming)
    separation = math.hypot(*outgoing)
    if not all(math.isfinite(d) and d > 0 for d in (to_first, separation)):
        raise ValueError('Require distinct source and first positions and distinct interaction vertices')
    # Roundoff in the unit-vector dot product can slightly exceed +/- 1.
    cosine = float(np.clip((incoming/to_first) @ (outgoing/separation), -1., 1.))
    recoil = (incident_keV/photon.ELECTRON_REST_KEV)*(1-cosine)
    factor = 1+recoil
    return dict(first_scatter_cosine=cosine, intermediate_keV=incident_keV/factor,
                expected_first_deposit_keV=incident_keV*(recoil/factor), site_separation_mm=separation)


def point_source_response(crystal, source_mm, first_mm, second_mm, incident_keV, observed_first_keV,
                          observed_second_keV, rates_at, outgoing_total, *, sigma_first_keV, sigma_second_keV,
                          azimuth_samples=256, energy_order=256, include_log=False):
    """Return branch densities with rates_at(E) in PhotonRates and outgoing_total(E) in inverse mm.

    For tabulated rates, pass the existing total_rate_interpolator to
    outgoing_total. The caller supplies the intermediate rate components
    on their verified domain. Unsupported table lookups propagate unchanged.
    Set include_log to retain finite natural logs when raw densities underflow.
    """
    state = first_compton_state(source_mm, first_mm, second_mm, incident_keV)
    intermediate = state['intermediate_keV']
    first_density = gaussian_density_per_kev(observed_first_keV, state['expected_first_deposit_keV'], sigma_first_keV)
    gaussian_density_per_kev(observed_second_keV, intermediate, sigma_second_keV)
    if type(azimuth_samples) is not int or azimuth_samples < 1:
        raise ValueError('Use a positive integer azimuth quadrature size')
    first_kn = photon.solid_angle_density_per_sr(incident_keV, state['first_scatter_cosine'])
    inverse_area = (1/state['site_separation_mm'])**2
    second_response = observed_continuation(crystal, first_mm, second_mm, intermediate, rates_at(intermediate),
                                            outgoing_total, [observed_second_keV], sigma_keV=sigma_second_keV,
                                            azimuth_samples=azimuth_samples, energy_order=energy_order, include_log=include_log)
    second = second_response['observations'][0]
    factor = first_kn*inverse_area*first_density
    result = dict(state, incident_keV=incident_keV, observed_first_keV=observed_first_keV,
                observed_second_keV=observed_second_keV, sigma_first_keV=sigma_first_keV, sigma_second_keV=sigma_second_keV,
                first_kn_density_per_sr=first_kn, inverse_intersite_area_per_mm2=inverse_area,
                first_measurement_density_per_keV=first_density,
                absorption_per_mm3_observed_keV2=factor*second['absorption_per_mm_observed_keV'],
                escape_per_mm3_observed_keV2=factor*second['escape_per_mm_observed_keV'],
                energy_integrated_branch_density_per_mm3={
                    branch: first_kn*inverse_area*mass
                    for branch, mass in second_response['observed_integrated_mass_per_mm'].items()},
                second_site_response=second_response)
    if include_log:
        log_first = gaussian_log_density_per_kev(observed_first_keV, state['expected_first_deposit_keV'], sigma_first_keV)
        log_spatial = math.log(first_kn)-2*math.log(state['site_separation_mm'])
        result['log_first_measurement_density_per_keV'], result['first_measurement_density_status'] = density_evidence(
            first_density, log_first, supported=True)
        integrated = second_response['log_observed_integrated_mass_per_mm']
        result['log_energy_integrated_branch_density_per_mm3'] = {
            branch: log_spatial+mass if mass is not None else None for branch, mass in integrated.items()}
        for branch in ('absorption', 'escape'):
            name = branch+'_per_mm3_observed_keV2'
            second_log = second['log_'+branch+'_per_mm_observed_keV']
            if second_log is None:
                result['log_'+name], result[branch+'_density_status'] = None, second[branch+'_density_status']
            else:
                result['log_'+name], result[branch+'_density_status'] = density_evidence(
                    result[name], log_spatial+log_first+second_log, supported=True)
    return result
