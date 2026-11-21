"""Positive escape quadrature in the truncated Gaussian probability variable.

Integrate the same Ge survival and free-electron spectrum over the physical
deposit interval. On each side of the Gaussian center, reflect to a lower
normal tail and use an affine probability coordinate on [0, 1]. Keep the
exact interval mass in log space. A positive Gauss–Legendre rule integrates
the remaining spectrum at inverse log-CDF nodes without a Gaussian cutoff.
"""

from functools import lru_cache
import math

import numpy as np
from scipy.special import log_ndtr, logsumexp, ndtri_exp, roots_legendre

import gegi_photon_continuation as photon
from gegi_photon_log_response import density_evidence


@lru_cache
def unit_rule(order):
    if type(order) is not int or order < 1:
        raise ValueError('Use a positive integer quadrature order')
    nodes, weights = roots_legendre(order)
    return (1+nodes)/2, weights/2


def gaussian_segments(lower, upper, observation, sigma, order):
    """Yield positive normalized node weights and log interval masses."""
    if not all(map(math.isfinite, (lower, upper, observation, sigma))) or not (lower < upper and sigma > 0):
        raise ValueError('Require finite ordered deposit limits and a positive Gaussian width')
    u, weights = unit_rule(order)
    stops = (lower, observation, upper) if lower < observation < upper else (lower, upper)
    for left, right in zip(stops[:-1], stops[1:], strict=True):
        # Both z bounds are in the lower Gaussian half, even for deposits
        # above the observation. Then the CDF difference is well conditioned.
        reflect = left >= observation
        a, b = (((observation-right)/sigma, (observation-left)/sigma) if reflect else
                ((left-observation)/sigma, (right-observation)/sigma))
        low, high = float(log_ndtr(a)), float(log_ndtr(b))
        if not math.isfinite(high) or low >= high:
            raise ValueError('Gaussian probability interval is outside finite log resolution')
        log_mass = high+math.log(-math.expm1(low-high))
        quantiles = ndtri_exp(np.logaddexp(low, np.log(u)+log_mass))
        deposits = observation+(-sigma if reflect else sigma)*quantiles
        # Roundoff in the inverse transform can land on an interval edge.
        yield np.clip(deposits, left, right), weights, log_mass


def integrate_log_spectrum(log_spectrum, lower, upper, observation, sigma, order):
    values, masses, count = [], [], 0
    for deposits, weights, log_mass in gaussian_segments(lower, upper, observation, sigma, order):
        spectrum = [log_spectrum(float(e)) for e in deposits]
        values.append(log_mass+float(logsumexp(spectrum, b=weights)))
        masses.append(log_mass)
        count += len(deposits)
    return float(logsumexp(values)), float(logsumexp(masses)), count


def observed_escape(crystal, first_mm, second_mm, intermediate_keV, rates, outgoing_total, observed_keV,
                    *, sigma_keV, azimuth_samples=256, energy_order=16):
    """Return the escape factor per intersite path-mm per observed keV."""
    between = photon.continuation(crystal, first_mm, second_mm, intermediate_keV, rates)
    if not rates.compton_per_mm:
        return dict(log_escape_per_mm_observed_keV=None, escape_per_mm_observed_keV=0.,
                    escape_density_status='zero_physical_channel_rate', spectrum_evaluations=0,
                    log_gaussian_interval_mass=None)
    minimum, energy_density = photon.outgoing_energy_model(intermediate_keV)
    max_deposit = intermediate_keV-minimum
    length = between['internal_path_mm']
    axis = (np.asarray(second_mm)-first_mm)/length
    log_path = math.log(rates.compton_per_mm)-rates.total_per_mm*length

    def log_spectrum(deposit):
        outgoing = min(intermediate_keV, max(minimum, intermediate_keV-deposit))
        cosine = photon._outgoing_cosine(intermediate_keV, outgoing)
        _, log_survival = photon.azimuth_survival(crystal, second_mm, axis, cosine, outgoing_total(outgoing),
                                                 samples=azimuth_samples, include_log=True)
        return log_path+math.log(energy_density(outgoing))+log_survival

    value, log_mass, count = integrate_log_spectrum(log_spectrum, 0., max_deposit, observed_keV, sigma_keV, energy_order)
    raw = math.exp(value)
    log_density, status = density_evidence(raw, value, supported=True)
    return dict(log_escape_per_mm_observed_keV=log_density, escape_per_mm_observed_keV=raw,
                escape_density_status=status, spectrum_evaluations=count, log_gaussian_interval_mass=log_mass,
                true_escape_deposit_support_keV=[0., max_deposit])
