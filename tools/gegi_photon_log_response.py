"""Log-space factors shared by the conditional GeGI photon responses."""

import math


def gaussian_log_density_per_kev(observed_keV, deposited_keV, sigma_keV):
    """Evaluate the Gaussian density's natural log before any exponentiation."""
    if not all(math.isfinite(x) for x in (observed_keV, deposited_keV, sigma_keV)) or sigma_keV <= 0:
        raise ValueError('Finite observed/deposited energies and an explicit positive Gaussian width are required')
    z = (observed_keV-deposited_keV)/sigma_keV
    return -.5*z*z - .5*math.log(2*math.pi) - math.log(sigma_keV)


def gaussian_tail_knots(observed_keV, boundary_keV, upper_keV, sigma_keV):
    """Subdivide a steep endpoint layer at fixed changes of log Gaussian density.

    The positive root of (z+x)^2-z^2 = 2*drop gives the distance
    from the boundary in sigma units. The caller integrates the rest too.
    """
    if observed_keV == boundary_keV:
        return []
    distance = abs(observed_keV-boundary_keV)/sigma_keV
    inward = 1 if observed_keV < boundary_keV else -1
    knots = [boundary_keV + inward*sigma_keV*(2*drop/(math.hypot(distance, math.sqrt(2*drop))+distance))
             for drop in (1., 4., 16., 64.)]
    return sorted({x for x in knots if 0. < x < upper_keV})


def density_evidence(raw_density, log_density, *, supported):
    """Keep an absent physical branch distinct from numerical underflow in JSON."""
    if not supported:
        return None, 'zero_physical_channel_rate'
    if not math.isfinite(log_density):
        return None, 'density_outside_finite_log_range'
    if not math.isfinite(raw_density):
        return float(log_density), 'raw_density_overflow'
    return float(log_density), 'raw_density_underflow' if raw_density == 0 else 'positive_raw_density'
