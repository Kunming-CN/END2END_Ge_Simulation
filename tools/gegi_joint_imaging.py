"""Saved-signal, finite-vertex Compton localization with event-level ambiguity.

This is an *approximate conditional angular-error model*, not a calibrated
detector system matrix. It conditions on the reconstructed interaction geometry
and models the inferred Compton angle on [0, pi]. Its mixture fractions describe
the selected detected groups, never source activity. No source labels, true
vertices, known source positions, or truth-selected sequences enter this module.

For candidate h of event i and source point x:
    alpha = acos(a . (x-r1)/|x-r1|), a=(r1-r2)/|r1-r2|
    L_ih(x) = truncated_Normal(theta_h; alpha, sigma_ih(x))
    L_i(x) = sum_h q_ih L_ih(x) + (1-sum_h q_ih)/pi.
Unresolved hypothesis mass stays uninformative instead of being redistributed to
surviving candidates. A separate uniform-angle component models outliers. No
candidate is normalized over a displayed square, sphere, or observed event list.

The nominal angular nuisance width is not measured GeGI resolution. First-order
position/energy propagation includes the shared r1 error in the axis and ray;
very short lever arms and large errors remain approximation limits. Sensitivity,
attenuation, Doppler/charge-sharing response and real electronics calibration
are absent. Full Poisson activity MLEM is deliberately not exposed.

References informing the design (not claims of implementing their full models):
LBNL-2001559 (2024), sec VI eq70, Appendix A and F:
https://escholarship.org/uc/item/2k139571
Vavrek et al. (2021), response/sensitivity/background likelihood:
https://doi.org/10.1038/s41598-021-99588-z
Private Ge-STAR presentation, Reichenbacher/Belmechri, 14 July 2026: fixed-plane
and 3D Gaussian backprojection, MRP-EM; its truth-selected two-site simulation
and supplied measured source distances are not signal-derived validation here.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, dataclass
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import time

if __name__ == '__main__':
    # Child-only limits; no machine settings or user's running processes change.
    for _name in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
        os.environ[_name] = '1'
import numpy as np

ELECTRON_REST_KEV = 510.99895069
PITCH_MM = 4.937480624253117
BACKGROUND_PER_RAD = 1.0 / math.pi
REFERENCES = [
    {'title': 'Modeling the Compton Camera Response for Extended Voxel Sources',
     'url': 'https://escholarship.org/uc/item/2k139571',
     'used_for': 'finite-distance geometry, uncertainty, summed sequences and sensitivity requirements'},
    {'title': 'Free-moving Quantitative Gamma-ray Imaging',
     'url': 'https://doi.org/10.1038/s41598-021-99588-z',
     'used_for': 'distinction between event response, sensitivity and background'},
]


@dataclass(frozen=True)
class ResponseSettings:
    strip_pitch_mm: float = PITCH_MM
    angular_nuisance_sigma_deg: float = 5.0
    # Unknown depth/energy uncertainties are NOT claimed to be zero resolution.
    # These defaults propagate only known strip quantization plus the explicitly
    # nominal angular nuisance. Explicit covariance overrides the position default.
    fallback_depth_sigma_mm: float = 0.0
    maximum_matrix_bytes: int = 512 * 1024 * 1024

    def validate(self):
        for name in ('strip_pitch_mm', 'angular_nuisance_sigma_deg', 'fallback_depth_sigma_mm'):
            x = getattr(self, name)
            if not math.isfinite(x) or x < 0:
                raise ValueError(f'Invalid {name}')
        if self.angular_nuisance_sigma_deg <= 0 or self.maximum_matrix_bytes <= 0:
            raise ValueError('Positive nuisance width and memory budget required')


@dataclass(frozen=True)
class Candidate:
    vertex: np.ndarray
    axis: np.ndarray
    separation: float
    theta: float
    prior: float
    position_covariance: np.ndarray
    energy_angle_variance: float
    position_uncertainty_declared: bool
    energy_uncertainty_declared: bool


@dataclass(frozen=True)
class Event:
    identity: tuple
    energy_keV: float | None
    candidates: tuple[Candidate, ...]
    unresolved_mass: float


def _finite_array(value, shape, name):
    a = np.asarray(value, dtype=np.float64)
    if a.shape != shape or not np.isfinite(a).all():
        raise ValueError(f'Invalid {name}: expected finite shape {shape}')
    return a


def _covariance(value, shape, name):
    a = _finite_array(value, shape, name)
    if not np.allclose(a, np.swapaxes(a, -1, -2), atol=1e-12, rtol=1e-12):
        raise ValueError(f'Non-symmetric {name}')
    if np.min(np.linalg.eigvalsh(a)) < -1e-12:
        raise ValueError(f'Non-positive-semidefinite {name}')
    return a


def prepare_candidate(raw, settings=ResponseSettings()):
    """Accept the v3 API or a saved v2 cone; reject inconsistent units/geometry."""
    settings.validate()
    first = _finite_array(raw['vertex_mm'], (3,), 'vertex_mm')
    axis = _finite_array(raw['axis'], (3,), 'axis')
    if not np.isclose(np.linalg.norm(axis), 1., atol=1e-8, rtol=0):
        raise ValueError('Cone axis must be unit length, pointing second-to-first')
    distance = float(raw.get('site_separation_mm', raw.get('separation_mm', 0)))
    if 'second_vertex_mm' in raw:
        second = _finite_array(raw['second_vertex_mm'], (3,), 'second_vertex_mm')
        inferred = float(np.linalg.norm(first-second))
        if distance == 0:
            distance = inferred
        if not np.isclose(inferred, distance, atol=1e-8, rtol=1e-8):
            raise ValueError('Second vertex disagrees with separation')
        if inferred <= 0 or not np.allclose((first-second)/inferred, axis, atol=1e-8, rtol=0):
            raise ValueError('Second vertex disagrees with source-facing cone axis')
    if not math.isfinite(distance) or distance <= 0:
        raise ValueError('Positive site separation required for position uncertainty')
    if 'cos_theta' in raw:
        cosine = float(raw['cos_theta'])
        if not math.isfinite(cosine) or not -1 <= cosine <= 1:
            raise ValueError('Unphysical Compton cosine; never clamp input energies')
        theta = math.acos(cosine)
    elif 'theta_rad' in raw:
        theta = float(raw['theta_rad'])
    else:
        theta = math.radians(float(raw['half_angle_deg']))
    if not math.isfinite(theta) or not 0 <= theta <= math.pi:
        raise ValueError('Invalid Compton angle')
    if 'half_angle_deg' in raw and not math.isclose(theta, math.radians(raw['half_angle_deg']), abs_tol=1e-8):
        raise ValueError('Conflicting angle/cosine')
    prior = float(raw.get('prior_weight', raw.get('weight', 1.)))
    if not math.isfinite(prior) or not 0 <= prior <= 1:
        raise ValueError('Candidate prior must lie in [0,1]')
    supplied_position = raw.get('position_covariance_mm2') is not None
    if supplied_position:
        covariance = _covariance(raw['position_covariance_mm2'], (2, 3, 3), 'position_covariance_mm2')
    else:
        xy_var = settings.strip_pitch_mm**2/12.  # uniform strip quantization
        covariance = np.array([np.diag([xy_var, xy_var, settings.fallback_depth_sigma_mm**2])]*2)
    # Energies are checked even when uncertainty is unavailable.
    e1, e2 = raw.get('scatter_energy_keV'), raw.get('absorbed_energy_keV')
    if e1 is not None or e2 is not None:
        if e1 is None or e2 is None or not all(math.isfinite(e) and e > 0 for e in (e1, e2)):
            raise ValueError('Both positive scatter and remaining energies required')
        energy_cos = 1-ELECTRON_REST_KEV*(1/e2-1/(e1+e2))
        if not math.isclose(energy_cos, math.cos(theta), abs_tol=1e-7, rel_tol=1e-7):
            raise ValueError('Energies disagree with Compton angle')
    supplied_energy = raw.get('energy_sigma_keV') is not None or raw.get('energy_covariance_keV2') is not None
    variance = 0.
    if supplied_energy:
        if e1 is None or e2 is None:
            raise ValueError('Energy uncertainty requires both site energies')
        if raw.get('energy_covariance_keV2') is not None:
            ecov = _covariance(raw['energy_covariance_keV2'], (2, 2), 'energy_covariance_keV2')
        else:
            sig = np.asarray(raw['energy_sigma_keV'], dtype=float)
            if sig.ndim == 0:
                sig = np.repeat(sig, 2)
            sig = _finite_array(sig, (2,), 'energy_sigma_keV')
            if np.any(sig < 0):
                raise ValueError('Negative energy uncertainty')
            ecov = np.diag(sig*sig)
        # The derivative becomes ill-conditioned at 0/pi; the resulting broad
        # distribution tends to uniform, never artificially precise there.
        dc = np.array([-ELECTRON_REST_KEV/(e1+e2)**2,
                       ELECTRON_REST_KEV/e2**2-ELECTRON_REST_KEV/(e1+e2)**2])
        variance = max(0., float(dc @ ecov @ dc))/max(math.sin(theta)**2, 1e-16)
    return Candidate(first, axis, distance, theta, prior, covariance, variance,
                     supplied_position, supplied_energy)


def prepare_events(records, settings=ResponseSettings()):
    """Source-blind projection: unknown/truth/group fields are never inspected."""
    events, identities = [], set()
    for index, raw in enumerate(records):
        event_id = raw.get('campaign_initial_id', raw.get('event_id', index))
        identity = (event_id, raw.get('pulse_group_id', 0))
        if identity in identities:
            raise ValueError(f'Duplicate event/group identity: {identity}')
        identities.add(identity)
        energy = raw.get('energy_keV', raw.get('readout_energy_keV'))
        if energy is not None:
            energy = float(energy)
            if not math.isfinite(energy) or energy <= 0:
                raise ValueError('Event energy must be positive or null')
        candidates = tuple(prepare_candidate(c, settings) for c in raw.get('candidates', raw.get('cones', ())))
        prior_sum = math.fsum(c.prior for c in candidates)
        if prior_sum > 1+1e-10:
            raise ValueError('Candidate weights exceed one event; do not count alternatives as events')
        events.append(Event(identity, energy, candidates, max(0., 1-prior_sum)))
    return events


def geometric_angle_and_variance(candidate, points):
    """Analytic covariance of angle, including r1's ray/axis cross-term.

    For c=a.u: dc/dr1=(u-ca)/L-(a-cu)/R, dc/dr2=-(u-ca)/L.
    This accounts for independent site errors. Cross-site covariance, charge
    sharing and non-Gaussian multisite reconstruction remain outside this model.
    """
    points = np.asarray(points, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 3 or not np.isfinite(points).all():
        raise ValueError('Finite source points with shape (n,3) required')
    ray = points-candidate.vertex
    distance = np.linalg.norm(ray, axis=1)
    if np.any(distance <= 1e-9):
        raise ValueError('A source point coincides with a reconstructed interaction')
    unit = ray/distance[:, None]
    cosine = np.clip(unit @ candidate.axis, -1., 1.)
    alpha = np.arccos(cosine)
    sine = np.sqrt(np.maximum(0., 1-cosine*cosine))
    qa = (unit-cosine[:, None]*candidate.axis)/np.maximum(sine[:, None], 1e-8)
    qu = (candidate.axis-cosine[:, None]*unit)/np.maximum(sine[:, None], 1e-8)
    g1 = -qa/candidate.separation+qu/distance[:, None]
    g2 = qa/candidate.separation
    cov1, cov2 = candidate.position_covariance
    variance = np.einsum('ni,ij,nj->n', g1, cov1, g1)+np.einsum('ni,ij,nj->n', g2, cov2, g2)
    # At a cone pole the derivative direction is undefined. Use the average
    # tangent-plane variance (isotropic RMS), rather than the erroneous zero.
    pole = sine < 1e-7
    if pole.any():
        pa = np.eye(3)-np.outer(candidate.axis, candidate.axis)
        for i in np.flatnonzero(pole):
            pu = np.eye(3)-np.outer(unit[i], unit[i])
            # Opposite directions have the opposite relative-angle perturbation.
            m1 = pa/candidate.separation+np.sign(cosine[i])*pu/distance[i]
            m2 = -pa/candidate.separation
            variance[i] = .5*np.trace(m1 @ cov1 @ m1.T+m2 @ cov2 @ m2.T)
    return alpha, np.maximum(variance, 0.)


def _erf(x):
    """Vectorized A&S 7.1.26; maximum absolute approximation error <1.5e-7."""
    sign = np.sign(x)
    y = np.abs(x)
    t = 1/(1+.3275911*y)
    p = (((((1.061405429*t-1.453152027)*t)+1.421413741)*t-.284496736)*t+.254829592)*t
    return sign*(1-p*np.exp(-y*y))


def angular_density(theta, alpha, sigma):
    """Normalized density in observed angle [0,pi], in rad^-1.

    The normalizer is an analytic angular observation-domain integral, never an
    integral over a chosen image window. Broad uncertainties become uniform.
    """
    alpha, sigma = np.broadcast_arrays(np.asarray(alpha, float), np.asarray(sigma, float))
    if not math.isfinite(theta) or not 0 <= theta <= math.pi:
        raise ValueError('Observed angle outside [0,pi]')
    if not np.isfinite(alpha).all() or not np.isfinite(sigma).all() or np.any(sigma <= 0):
        raise ValueError('Finite positive angular uncertainty required')
    normalizer = .5*(_erf((math.pi-alpha)/(math.sqrt(2)*sigma))+_erf(alpha/(math.sqrt(2)*sigma)))
    value = np.exp(-.5*((theta-alpha)/sigma)**2)/(math.sqrt(2*math.pi)*sigma*np.maximum(normalizer, 1e-300))
    return np.where(sigma > 1e4, BACKGROUND_PER_RAD, value)


def candidate_response(candidate, points, settings=ResponseSettings()):
    alpha, positional = geometric_angle_and_variance(candidate, points)
    sigma = np.sqrt(positional+candidate.energy_angle_variance+math.radians(settings.angular_nuisance_sigma_deg)**2)
    return angular_density(candidate.theta, alpha, sigma)


def event_response(event, points, settings=ResponseSettings()):
    result = np.full(len(points), event.unresolved_mass*BACKGROUND_PER_RAD, dtype=np.float64)
    for candidate in event.candidates:
        result += candidate.prior*candidate_response(candidate, points, settings)
    return result


def response_matrix(events, points, settings=ResponseSettings()):
    """Bound allocation to one events-by-points matrix, never events x xyz x energy."""
    settings.validate()
    needed = len(events)*len(points)*8
    if needed > settings.maximum_matrix_bytes:
        raise ValueError(f'Response matrix needs {needed} bytes, exceeds {settings.maximum_matrix_bytes}; reduce grid')
    result = np.empty((len(events), len(points)), dtype=np.float64)
    for i, event in enumerate(events):
        result[i] = event_response(event, points, settings)
    return result


def fit_conditional_mixture(response, iterations=40, initial_background=.25, tolerance=1e-8,
                            initial_source_mass=None):
    """EM for sum_i log[b/pi + sum_j f_j L_ij], b+sum_j f_j=1.

    This is a specified conditional localization model with a uniform-angle
    outlier component. f_j is selected-event mixture mass, NOT activity or flux.
    No fabricated detection sensitivity or observed-row sensitivity estimate.
    The finite grid is a support assumption; extending it can change fitted
    mixture masses even though every response L_ij remains exactly invariant.
    """
    a = np.asarray(response, dtype=np.float64)
    if a.ndim != 2 or not a.shape[0] or not a.shape[1] or not np.isfinite(a).all() or np.any(a < 0):
        raise ValueError('Nonempty finite nonnegative response matrix required')
    if not 0 < initial_background < 1 or iterations < 1:
        raise ValueError('Interior initial background and positive iterations required')
    if initial_source_mass is None:
        mass = np.full(a.shape[1], (1-initial_background)/a.shape[1])
    else:
        mass = _finite_array(initial_source_mass, (a.shape[1],), 'initial_source_mass').copy()
        if np.any(mass < 0) or not math.isclose(mass.sum(), 1-initial_background, abs_tol=1e-10):
            raise ValueError('Initial source and background masses must sum to one')
    background = initial_background
    history = []
    for step in range(iterations+1):
        predicted = a @ mass+background*BACKGROUND_PER_RAD
        if np.any(predicted <= 0):
            raise ValueError('Zero mixture likelihood')
        objective = float(np.log(predicted).sum())
        history.append(objective)
        if len(history) > 1:
            if objective < history[-2]-1e-9*max(1., abs(history[-2])):
                raise ArithmeticError('Conditional EM objective decreased')
            if objective-history[-2] <= tolerance*max(1., abs(history[-2])):
                break
        if step == iterations:
            break
        inverse = 1/predicted
        mass *= (a.T @ inverse)/a.shape[0]
        background *= float(inverse.mean())*BACKGROUND_PER_RAD
        # Roundoff only: this identity follows exactly from EM responsibilities.
        norm = float(mass.sum()+background)
        mass /= norm
        background /= norm
    outlier = background*BACKGROUND_PER_RAD/predicted
    return {'source_mass': mass, 'background_fraction': float(background),
            'event_outlier_probability': outlier, 'log_likelihood': history,
            'iterations': len(history)-1, 'likelihood_kind': 'approximate_conditional_angular_error',
            'activity_bq': None, 'sensitivity_calibrated': False}


def plane_grid(extent_mm=120., step_mm=4., z_mm=40.):
    if not all(math.isfinite(v) for v in (extent_mm, step_mm, z_mm)) or extent_mm <= 0 or step_mm <= 0:
        raise ValueError('Invalid plane grid')
    n = round(2*extent_mm/step_mm)
    if n < 2 or not math.isclose(n*step_mm, 2*extent_mm, rel_tol=1e-10):
        raise ValueError('Plane width must be an integer multiple of step')
    ticks = np.arange(n, dtype=float)*step_mm-extent_mm+step_mm/2
    xx, yy = np.meshgrid(ticks, ticks)
    return ticks, np.column_stack((xx.ravel(), yy.ravel(), np.full(xx.size, z_mm)))


def blind_peaks(values, points, minimum_separation_mm=20., maximum=2):
    """At most two separated local modes; flat maps and shoulders are not peaks.

    The cap is a display bound, not an inferred number of sources. On a regular
    plane, accept a second mode only with a connecting valley <=80% of its height
    (the previously declared engineering valley rule). Edge modes remain flagged.
    """
    a = np.asarray(values)
    if a.size == 0 or a.max() <= 0 or np.ptp(a) <= 1e-12*a.max():
        return []
    xs, ys, zs = (np.unique(points[:, i]) for i in range(3))
    rectangular = len(zs) == 1 and len(xs)*len(ys) == len(points)
    candidates = np.ones(len(a), dtype=bool)
    if rectangular:
        indexed = np.full((len(ys), len(xs)), -1, dtype=int)
        indexed[np.searchsorted(ys, points[:, 1]), np.searchsorted(xs, points[:, 0])] = np.arange(len(a))
        field = a[indexed]
        padded = np.pad(field, 1, constant_values=-np.inf)
        is_peak = np.ones_like(field, dtype=bool)
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                if di or dj:
                    is_peak &= field >= padded[1+di:1+di+len(ys), 1+dj:1+dj+len(xs)]
        candidates[indexed.ravel()] = is_peak.ravel()
    selected = []
    for index in np.argsort(-a, kind='stable'):
        if not candidates[index] or a[index] <= 0:
            continue
        if any(np.linalg.norm(points[index]-points[j]) < minimum_separation_mm for j in selected):
            continue
        if rectangular and selected:
            path = np.linspace(points[selected[0]], points[index], 101)
            ci = np.clip(np.rint((path[:, 0]-xs[0])/(xs[1]-xs[0])).astype(int), 0, len(xs)-1)
            ri = np.clip(np.rint((path[:, 1]-ys[0])/(ys[1]-ys[0])).astype(int), 0, len(ys)-1)
            if np.min(field[ri, ci]) > .8*min(a[index], a[selected[0]]):
                continue
        selected.append(int(index))
        if len(selected) == maximum:
            break
    return [{'position_mm': points[i].tolist(), 'value': float(a[i]),
             'on_image_edge': bool(rectangular and (points[i, 0] in (xs[0], xs[-1]) or points[i, 1] in (ys[0], ys[-1])))}
            for i in selected]


def spectral_membership(events, centers_keV=(661.657, 1173.228, 1332.492)):
    """Identical source-blind measured-energy windows for every acquisition.

    Labels are line energies, not inferred nuclide identities. Other detected
    energies remain in the pooled map and an 'other' layer. No equal-component
    normalization is applied when pooling independent acquisitions.
    """
    memberships = {}
    selected = np.zeros(len(events), dtype=bool)
    for center in centers_keV:
        halfwidth = max(5., .02*center)
        mask = np.array([e.energy_keV is not None and abs(e.energy_keV-center) <= halfwidth for e in events])
        if np.any(selected & mask):
            raise ValueError('Overlapping spectral windows would duplicate groups')
        memberships[f'{center:g}_keV'] = mask
        selected |= mask
    memberships['other_energy'] = ~selected
    return memberships


def uncertainty_summary(events, settings):
    candidates = [c for e in events for c in e.candidates]
    return {'settings': asdict(settings), 'candidate_count': len(candidates),
            'explicit_position_covariance_candidates': sum(c.position_uncertainty_declared for c in candidates),
            'explicit_energy_uncertainty_candidates': sum(c.energy_uncertainty_declared for c in candidates),
            'unknown_energy_uncertainty_candidates': sum(not c.energy_uncertainty_declared for c in candidates),
            'calibrated_energy_resolution_keV': None,
            'calibrated_depth_resolution_mm': None,
            'unresolved_hypothesis_mass_sum': math.fsum(e.unresolved_mass for e in events),
            'uniform_strip_sigma_mm': settings.strip_pitch_mm/math.sqrt(12),
            'nominal_width_is_measured_resolution': False,
            'limits': ['First-order Gaussian error propagation; not a full detector response.',
                       'Unknown depth/energy errors are not zero measured uncertainty; missing contributions remain a limitation.',
                       'Nominal angular width includes no validated Doppler or waveform model.',
                       'Selected detected-group fractions are not source activity or emission efficiency.']}


def reconstruct_plane(events, settings=ResponseSettings(), extent_mm=120., step_mm=4., z_mm=40., iterations=40):
    started = time.perf_counter()
    ticks, points = plane_grid(extent_mm, step_mm, z_mm)
    response = response_matrix(events, points, settings)
    build_seconds = time.perf_counter()-started
    fit = fit_conditional_mixture(response, iterations=iterations)
    shape = (len(ticks), len(ticks))
    backprojection = response.sum(axis=0)
    layers = {}
    for label, mask in spectral_membership(events).items():
        if mask.any():
            # These source-blind energy layers use the same response and fitting
            # settings; they are not source-labelled or equalized acquisitions.
            layer_fit = fit_conditional_mixture(response[mask], iterations=iterations)
            layers[label] = {'group_count': int(mask.sum()),
                             'source_mass': layer_fit['source_mass'].reshape(shape).tolist(),
                             'angular_backprojection_per_rad': response[mask].sum(axis=0).reshape(shape).tolist(),
                             'background_fraction': layer_fit['background_fraction'],
                             'blind_peaks': blind_peaks(layer_fit['source_mass'], points)}
    report = {'kind': 'gegi_joint_conditional_imaging_v3', 'group_count': len(events),
              'pooling': 'all supplied independent acquisitions, anonymous event pool; no acquisition equalization or simultaneous pileup',
              'grid': {'x_mm': ticks.tolist(), 'y_mm': ticks.tolist(), 'assumed_z_mm': z_mm,
                       'step_mm': step_mm, 'extent_mm': extent_mm},
              'angular_backprojection_per_rad': backprojection.reshape(shape).tolist(),
              'source_mass': fit['source_mass'].reshape(shape).tolist(),
              'background_fraction': fit['background_fraction'],
              'conditional_log_likelihood': fit['log_likelihood'],
              'em_iterations': fit['iterations'], 'activity_bq': None,
              'localization_status': 'conditional_hypotheses_not_validated_source_locations',
              'peak_count_is_inferred_source_count': False,
              'sensitivity_calibrated': False, 'source_distance_mm': None,
              'distance_status': 'unknown; z is an imposed plane, not a range measurement',
              'blind_peaks': blind_peaks(fit['source_mass'], points),
              'backprojection_blind_peaks': blind_peaks(backprojection, points),
              'spectral_layers': layers, 'uncertainty': uncertainty_summary(events, settings),
              'response_matrix_bytes': response.nbytes, 'response_build_seconds': build_seconds,
              'elapsed_seconds': time.perf_counter()-started, 'references': REFERENCES}
    rows = [{'event_id': e.identity[0], 'pulse_group_id': e.identity[1], 'energy_keV': e.energy_keV,
             'candidate_count': len(e.candidates), 'unresolved_hypothesis_mass': e.unresolved_mass,
             'candidates_with_unknown_energy_uncertainty': sum(not c.energy_uncertainty_declared for c in e.candidates),
             'conditional_outlier_probability': float(fit['event_outlier_probability'][i]),
             'maximum_angular_likelihood_per_rad': float(response[i].max())}
            for i, e in enumerate(events)]
    return report, rows


def profile_planes(events, settings=ResponseSettings(), z_values_mm=(20., 40., 80., 120., 200.),
                   extent_mm=120., step_mm=8., iterations=40):
    """Profile assumed common plane depth with one bounded 2-D matrix at a time.

    Report the conditional objective, never a measured distance or confidence
    interval. Uncalibrated response, common-plane and field-of-view assumptions
    prevent a claimed range result from this diagnostic alone.
    """
    started = time.perf_counter()
    rows = []
    for z in z_values_mm:
        ticks, points = plane_grid(extent_mm, step_mm, float(z))
        response = response_matrix(events, points, settings)
        fit = fit_conditional_mixture(response, iterations=iterations)
        rows.append({'assumed_z_mm': float(z), 'conditional_log_likelihood': fit['log_likelihood'][-1],
                     'background_fraction': fit['background_fraction'],
                     'blind_peaks': blind_peaks(fit['source_mass'], points),
                     'iterations': fit['iterations'], 'matrix_bytes': response.nbytes})
        del response
    maximum = max(row['conditional_log_likelihood'] for row in rows)
    for row in rows:
        row['twice_delta_conditional_log_likelihood'] = 2*(maximum-row['conditional_log_likelihood'])
    return {'kind': 'assumed_common_plane_profile', 'planes': rows,
            'source_distance_mm': None, 'range_identified': False,
            'reason': 'Diagnostic conditional-model profile only; no calibrated range-coverage test or full response/sensitivity.',
            'confidence_interval_mm': None, 'elapsed_seconds': time.perf_counter()-started,
            'extent_mm': extent_mm, 'step_mm': step_mm,
            'limits': ['All candidate sources forced onto one common plane at each step.',
                       'Likelihood differences are not calibrated chi-square intervals for nonparametric mixtures.',
                       'Fixed finite x/y support changes angular coverage with depth; inspect peaks/edges before interpretation.']}


def _reconstruct_with_checks(events, settings, extent_mm, step_mm, z_mm, iterations, profile):
    if not events:
        raise ValueError('No event records')
    started = time.perf_counter()
    report, rows = reconstruct_plane(events, settings, extent_mm, step_mm, z_mm, iterations)
    if profile:
        report['range_profile'] = profile_planes(events, settings, extent_mm=extent_mm, step_mm=step_mm*2, iterations=iterations)
    # Verify mathematical overlap invariance using exactly the same evaluation
    # points in a larger field. Fit masses are not asserted invariant: support
    # enlargement is legitimately a different mixture-model assumption.
    ticks, points = plane_grid(extent_mm, step_mm, z_mm)
    expanded_ticks, expanded = plane_grid(extent_mm*2, step_mm, z_mm)
    overlap = (np.abs(expanded[:, 0]) < extent_mm) & (np.abs(expanded[:, 1]) < extent_mm)
    if not np.array_equal(points, expanded[overlap]):
        raise AssertionError('FOV test grid alignment')
    max_difference = 0.
    for event in events:
        difference = np.max(abs(event_response(event, points, settings)-event_response(event, expanded, settings)[overlap]))
        max_difference = max(max_difference, float(difference))
    report['field_of_view_overlap_max_absolute_response_difference'] = max_difference
    report['provenance'] = {'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                            'python': platform.python_version(), 'numpy': np.__version__,
                            'random_draws': 0, 'new_transport_or_drift': False,
                            'input_records': len(events), 'elapsed_seconds_total': time.perf_counter()-started,
                            'truth_used_for_reconstruction': False, 'source_group_labels_used': False}
    return report, rows


def _save_report(output_dir, report, rows):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir/'report.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    (output_dir/'event_diagnostics.jsonl').write_text(''.join(json.dumps(r, separators=(',', ':'), allow_nan=False)+'\n' for r in rows), encoding='utf-8')
    return report


def run_saved(input_path, output_dir, settings=ResponseSettings(), extent_mm=120., step_mm=4.,
              z_mm=40., iterations=40, profile=True):
    input_path, output_dir = Path(input_path), Path(output_dir)
    if output_dir.exists():
        raise FileExistsError('Use a new derivative directory; never overwrite a scientific result')
    raw_bytes = input_path.read_bytes()
    records = [json.loads(line) for line in raw_bytes.decode('utf-8').splitlines() if line.strip()]
    events = prepare_events(records, settings)
    report, rows = _reconstruct_with_checks(events, settings, extent_mm, step_mm, z_mm, iterations, profile)
    report['provenance']['input_sha256'] = hashlib.sha256(raw_bytes).hexdigest()
    if hashlib.sha256(input_path.read_bytes()).hexdigest() != report['provenance']['input_sha256']:
        raise RuntimeError('Saved input changed during reconstruction')
    return _save_report(output_dir, report, rows)


def _file_sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read_reconstructed(input_dir, centers_keV=(661.657, 1173.228, 1332.492), *, two_site_only=False):
    """Verify/stream the completed saved-signal derivative and select by energy.

    Identity/denominators are retained separately. source_group, truth positions,
    old rejection reasons and native ancestry never enter the selection rule.
    Non-photopeak hypotheses remain intact in the immutable input derivative.
    Optional two-site selection uses reconstructed candidate order length only;
    original priors stay unchanged. These charge cells need not be photon vertices.
    """
    input_dir = Path(input_dir).resolve()
    complete_path, summary_path = input_dir/'COMPLETE.json', input_dir/'summary.json'
    complete = json.loads(complete_path.read_bytes())
    summary = json.loads(summary_path.read_bytes())
    if complete.get('status') != 'completed_conditional_reconstruction':
        raise ValueError('Saved-signal reconstruction is not complete')
    if (_file_sha(summary_path) != complete['summary_sha256']
            or _file_sha(input_dir/'identity.json') != complete['identity_sha256']):
        raise ValueError('Changed saved-signal summary or identity')
    selected, counts, seen = [], Counter(), set()
    site_selection = []
    bindings = {'COMPLETE.json': _file_sha(complete_path), 'summary.json': complete['summary_sha256'],
                'identity.json': complete['identity_sha256']}
    for chunk in complete['chunks']:
        index = chunk['chunk_index']
        if index in seen:
            raise ValueError('Duplicate saved-signal chunk')
        seen.add(index)
        rel = f'chunks/{index:03d}.jsonl.gz'
        receipt_rel = f'chunks/{index:03d}.json'
        path, receipt_path = input_dir/rel, input_dir/receipt_rel
        if path.is_symlink() or not path.resolve().is_relative_to(input_dir):
            raise ValueError('Linked or escaped derivative chunk')
        if _file_sha(path) != chunk['data_sha256'] or _file_sha(receipt_path) != chunk['receipt_sha256']:
            raise ValueError('Changed saved-signal chunk')
        receipt = json.loads(receipt_path.read_bytes())
        if receipt['sha256'] != chunk['data_sha256']:
            raise ValueError('Chunk receipt disagrees with manifest')
        bindings[rel], bindings[receipt_rel] = chunk['data_sha256'], chunk['receipt_sha256']
        before = path.stat()
        groups_in_chunk = 0
        with gzip.open(path, 'rt', encoding='utf-8') as stream:
            for line in stream:
                original = json.loads(line)
                reconstruction, identity = original['reconstruction'], original['original_identity']
                counts['nonzero_pulse_groups'] += 1
                groups_in_chunk += 1
                energy, candidates = reconstruction.get('energy_keV'), reconstruction.get('candidates', [])
                counts['native_failed_groups'] += original.get('native_status') == 'native_failed'
                if original.get('native_status') == 'native_failed' and candidates:
                    raise ValueError('Native failure cannot supply signal-derived candidates')
                if two_site_only:
                    counts['native_incomplete_groups'] += original.get('native_status') != 'completed'
                    single = sum(h.get('status') == 'conditional_fit' and len(h.get('sites', [])) == 1
                                 for h in reconstruction.get('hypotheses', []))
                    counts['single_site_conditional_fit_groups'] += bool(single)
                    counts['single_site_conditional_fit_hypotheses'] += single
                if not candidates:
                    counts['without_supported_candidates'] += 1
                    continue
                counts['groups_with_conditional_candidates'] += 1
                if energy is None or not math.isfinite(energy) or energy <= 0:
                    raise ValueError('Candidate-bearing group lacks positive fixed-readout energy')
                in_window = any(abs(energy-center) <= max(5., .02*center) for center in centers_keV)
                if two_site_only:
                    if any(len(c['order']) < 2 for c in candidates):
                        raise ValueError('A Compton candidate must have at least two reconstructed sites')
                    kept = [c for c in candidates if len(c['order']) == 2]
                    excluded = [c for c in candidates if len(c['order']) > 2]
                    counts['original_conditional_candidates'] += len(candidates)
                    counts['two_site_candidates'] += len(kept)
                    counts['excluded_multisite_candidates'] += len(excluded)
                    counts['mixed_candidate_groups'] += bool(kept and excluded)
                    counts['all_candidates_excluded_groups'] += not kept
                    if in_window:
                        counts['selected_original_conditional_groups'] += 1
                        counts['selected_original_candidates'] += len(candidates)
                        counts['selected_excluded_multisite_candidates'] += len(excluded)
                        counts['selected_mixed_candidate_groups'] += bool(kept and excluded)
                        counts['selected_all_candidates_excluded_groups'] += not kept
                    site_selection.append({'campaign_initial_id': identity['campaign_initial_id'],
                        'pulse_group_id': identity['pulse_group_id'], 'energy_keV': energy,
                        'in_measured_energy_windows': in_window, 'original_candidates': len(candidates),
                        'retained_two_site_candidates': len(kept), 'excluded_multisite_candidates': len(excluded),
                        'retained_prior_mass': math.fsum(c['prior_weight'] for c in kept),
                        'excluded_prior_mass': math.fsum(c['prior_weight'] for c in excluded)})
                    candidates = kept
                if not in_window:
                    counts['candidate_groups_outside_measured_energy_windows'] += 1
                    continue
                if not candidates:
                    continue
                counts['selected_conditional_groups'] += 1
                counts['selected_candidates'] += len(candidates)
                selected.append({'campaign_initial_id': identity['campaign_initial_id'],
                                 'pulse_group_id': identity['pulse_group_id'], 'energy_keV': energy,
                                 'candidates': candidates})
        if groups_in_chunk != receipt['counts']['pulse_groups']:
            raise ValueError('Chunk group census differs from receipt')
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError('Saved-signal chunk changed during read')
    if counts['nonzero_pulse_groups'] != summary['counts']['pulse_groups']:
        raise ValueError('Full saved-signal group census differs from summary')
    if two_site_only:
        counts.setdefault('selected_conditional_groups', 0)
        counts.setdefault('selected_candidates', 0)
    accounting = {'counts': dict(counts), 'input_sha256': bindings,
                      'original_initial_denominators': summary['original_initial_denominators'],
                      'selection': {'kind': 'fixed_readout_energy_windows_and_supported_conditional_hypotheses',
                                    'centers_keV': list(centers_keV), 'halfwidth_rule': 'max(5 keV, 2% of center)',
                                    'source_labels_used': False, 'truth_used': False,
                                    'outside_window_candidates': 'Retained in hash-bound saved-signal input; not treated as fully absorbed line events.',
                                    'selected_groups_are_validated_recovered_events': False},
                      'limits': summary.get('limitations', [])}
    if two_site_only:
        accounting['selection']['two_site_only'] = True
        accounting['selection']['candidate_rule'] = 'len(candidate.order)==2 after signal reconstruction'
        accounting['selection']['candidate_priors_renormalized'] = False
        accounting['two_site_selection'] = site_selection
    return selected, accounting


def run_reconstructed(input_dir, output_dir, settings=ResponseSettings(), extent_mm=120., step_mm=4.,
                      z_mm=40., iterations=40, profile=True, *, two_site_only=False):
    """Publication/student adapter for completed v3 saved-signal chunks."""
    if Path(output_dir).exists():
        raise FileExistsError('Preserve existing derivative')
    source_sha = _file_sha(__file__)
    records, accounting = read_reconstructed(input_dir, two_site_only=two_site_only)
    events = prepare_events(records, settings)
    if not events:
        report = {'kind': 'gegi_joint_conditional_imaging_v3', 'group_count': 0,
                  'localization_status': 'unavailable_no_selected_conditional_hypotheses',
                  'source_mass': None, 'source_distance_mm': None, 'activity_bq': None,
                  'provenance': {'source_sha256': source_sha, 'truth_used_for_reconstruction': False}}
        rows = []
    else:
        report, rows = _reconstruct_with_checks(events, settings, extent_mm, step_mm, z_mm, iterations, profile)
    report['saved_signal_accounting'] = accounting
    # Every binding was already checked while streaming; the completion seal
    # must remain unchanged until the derived report is written.
    if (_file_sha(Path(input_dir)/'COMPLETE.json') != accounting['input_sha256']['COMPLETE.json']
            or _file_sha(__file__) != source_sha):
        raise RuntimeError('Input completion seal or imaging source changed during derivation')
    return _save_report(output_dir, report, rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--step-mm', type=float, default=4.)
    parser.add_argument('--extent-mm', type=float, default=120.)
    parser.add_argument('--plane-z-mm', type=float, default=40.)
    parser.add_argument('--iterations', type=int, default=40)
    parser.add_argument('--no-profile', action='store_true')
    parser.add_argument('--reconstructed-directory', action='store_true',
                        help='Input is a completed saved-signal directory; apply source-blind fixed energy windows')
    parser.add_argument('--two-site-only', action='store_true',
                        help='Keep only reconstructed two-site candidates, preserving original priors; requires --reconstructed-directory')
    args = parser.parse_args()
    if args.two_site_only and not args.reconstructed_directory:
        parser.error('--two-site-only requires --reconstructed-directory')
    runner = run_reconstructed if args.reconstructed_directory else run_saved
    selection = {'two_site_only': args.two_site_only} if args.reconstructed_directory else {}
    report = runner(args.input, args.output, extent_mm=args.extent_mm, step_mm=args.step_mm,
                       z_mm=args.plane_z_mm, iterations=args.iterations, profile=not args.no_profile, **selection)
    print(json.dumps({k: report.get(k) for k in ('group_count', 'background_fraction', 'blind_peaks', 'elapsed_seconds', 'provenance')}, indent=2))


if __name__ == '__main__':
    main()
