"""Batch the frozen positive energy quadrature for the observed escape term."""

import math

import numpy as np
from scipy.special import logsumexp, roots_legendre

import gegi_photon_continuation as photon
from gegi_photon_log_response import gaussian_log_density_per_kev, gaussian_tail_knots, density_evidence
from gegi_photon_observed_energy import gaussian_density_per_kev


def checked_evaluator(model, crystal, rate_at, outgoing_total, azimuth_samples):
    first, second = (np.asarray(model[k]) for k in ('first_fitted_mm', 'second_fitted_mm'))
    length = float(np.linalg.norm(second-first))
    axis = (second-first)/length
    transverse = np.cross(axis, np.eye(3)[np.argmin(np.abs(axis))])
    transverse /= np.linalg.norm(transverse)
    phase = np.arange(azimuth_samples)*2*math.pi/azimuth_samples
    ring = np.cos(phase)[:, None]*transverse+np.sin(phase)[:, None]*np.cross(axis, transverse)
    observed, sigma = model['measured_second_site_keV'], model['sigma_second_keV']

    def at(intermediate_keV, energy_order):
        rates = rate_at(intermediate_keV)
        photon.continuation(crystal, first, second, intermediate_keV, rates)
        minimum, spectrum = photon.outgoing_energy_model(intermediate_keV)
        endpoint = intermediate_keV-minimum
        stops = [observed+j*sigma for j in (-8, -4, 0, 4, 8) if 0. < observed+j*sigma < endpoint]
        nearest = min(endpoint, max(0., observed))
        if gaussian_density_per_kev(observed, nearest, sigma) == 0.:
            stops.extend(gaussian_tail_knots(observed, nearest, endpoint, sigma))
        boundaries = [0., *sorted(set(stops)), endpoint]
        log_path = math.log(rates.compton_per_mm)-rates.total_per_mm*length

        def integrate(order):
            x, weights = roots_legendre(order)
            integration = []
            for a,b in zip(boundaries[:-1], boundaries[1:], strict=True):
                half = (b-a)/2
                deposit = a+half*(1+x)
                out = np.clip(intermediate_keV-deposit, minimum, intermediate_keV)
                terms = []
                for chunk in np.array_split(np.arange(len(out)), math.ceil(len(out)/64)):
                    e = out[chunk]
                    c = np.maximum(-1., 1-photon.ELECTRON_REST_KEV*(1/e-1/intermediate_keV))
                    rays = c[:, None, None]*axis + np.sqrt(1-c*c)[:, None, None]*ring
                    distances = photon.exit_distance_mm(crystal, second, rays)
                    rate = np.array([outgoing_total(v) for v in e])
                    survival = logsumexp(-rate[:, None]*distances, axis=1)-math.log(azimuth_samples)
                    kn = np.log([spectrum(v) for v in e])
                    gauss = [gaussian_log_density_per_kev(observed, d, sigma) for d in deposit[chunk]]
                    terms.extend(survival+kn+gauss+log_path)
                integration.append(math.log(half)+float(logsumexp(terms, b=weights)))
            return float(logsumexp(integration))

        low, high = integrate(energy_order//2), integrate(energy_order)
        raw = math.exp(high)
        value, status = density_evidence(raw, high, supported=True)
        return dict(intermediate_keV=float(intermediate_keV), log_escape_density=value, raw_escape_density=raw,
                    density_status=status, log_quadrature_difference=abs(high-low), energy_order=energy_order)
    return at
