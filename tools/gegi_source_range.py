"""Batched finite-vertex event angular scores shared by source-range workflows."""
import math
import numpy as np
from gegi_joint_imaging import _erf, event_response, geometric_angle_and_variance

POINT_CONE_BUDGET = 65_536

def profiled_background(log_response):
    """Maximize the concave uniform-angle mixture score on its physical [0,1].

    The response is relative to the uniform component. Endpoint solutions are
    retained, including a completely uninformative all-background solution.
    """
    response = np.exp(log_response)
    difference = 1.-response
    with np.errstate(divide='ignore', over='ignore'):
        at_zero = np.sum(difference/response, axis=1)
    at_one = difference.sum(axis=1)
    lo = np.zeros(len(response)); hi = np.ones(len(response))
    interior = (at_zero > 0) & (at_one < 0)
    # Bisection in the sole concave nuisance parameter, to float precision.
    for _ in range(42):
        mid = (lo+hi)/2
        slope = np.sum(difference/(response+mid[:, None]*difference), axis=1)
        lo = np.where(slope > 0, mid, lo)
        hi = np.where(slope > 0, hi, mid)
    fraction = np.where(interior, (lo+hi)/2, np.where(at_zero <= 0, 0., 1.))
    with np.errstate(divide='ignore'):
        value = np.logaddexp(np.log1p(-fraction[:, None])+log_response,
                             np.log(fraction[:, None])).sum(axis=1)
    return value, fraction

def require(ok, message):
    if not ok:
        raise ValueError(message)


class AngularScore:
    """Batch the existing angular response, including declared site/energy errors."""

    def __init__(self, first, second, settings, *, require_both_splits=True):
        events = first + second
        informative = [event for event in events if event.candidates]
        self.first_informative = sum(bool(event.candidates) for event in first)
        self.unknown = np.array([event.unresolved_mass for event in informative])
        self.starts = np.cumsum([0] + [len(event.candidates) for event in informative[:-1]])
        self.candidates = [cone for event in informative for cone in event.candidates]
        if require_both_splits:
            require(0 < self.first_informative < len(informative), 'Both splits need measured cone geometry')
        else:
            require(bool(informative), 'The pooled score needs measured cone geometry')
        self.vertex = np.array([c.vertex for c in self.candidates])
        self.axis = np.array([c.axis for c in self.candidates])
        self.theta = np.array([c.theta for c in self.candidates])
        self.length = np.array([c.separation for c in self.candidates])
        self.mass = np.array([c.prior for c in self.candidates])
        self.settings = settings
        self.position_covariance = np.array([c.position_covariance for c in self.candidates])
        self.energy_angle_variance = np.array([c.energy_angle_variance for c in self.candidates])
        self.nuisance_var = math.radians(settings.angular_nuisance_sigma_deg)**2
        self.informative = informative
        self.points_per_batch = max(1, POINT_CONE_BUDGET//len(self.candidates))
        self.accounting = dict(selected_triggers=len(events), triggers_with_geometry=len(informative),
                               allowed_saved_geometry_orders=len(self.candidates), projected_trigger_mass=math.fsum(self.mass),
                               unresolved_trigger_mass=math.fsum(event.unresolved_mass for event in events))
        require(math.isclose(self.accounting['projected_trigger_mass'] + self.accounting['unresolved_trigger_mass'],
                             len(events), abs_tol=1e-10), 'Selected trigger weights do not close')

    def angular_log_density(self, points, *, far_field=False):
        if far_field:
            unit = np.broadcast_to(np.asarray(points)[:, None, :],
                                   (len(points), len(self.candidates), 3))
            distance = np.full(unit.shape[:2], np.inf)
        else:
            ray = np.asarray(points)[:, None, :] - self.vertex
            distance = np.linalg.norm(ray, axis=2)
            unit = ray / distance[:, :, None]
        cosine = np.clip(np.einsum('pni,ni->pn', unit, self.axis), -1., 1.)
        alpha = np.arccos(cosine)
        sine = np.sqrt(np.maximum(0., 1-cosine*cosine))
        denominator = np.maximum(sine, 1e-8)[:, :, None]
        qa = (unit-cosine[:, :, None]*self.axis) / denominator
        qu = (self.axis-cosine[:, :, None]*unit) / denominator
        g2 = qa / self.length[None, :, None]
        g1 = -g2 + qu / distance[:, :, None]
        variance = (np.einsum('pni,nij,pnj->pn', g1, self.position_covariance[:, 0], g1)
                    + np.einsum('pni,nij,pnj->pn', g2, self.position_covariance[:, 1], g2))
        sigma = np.sqrt(np.maximum(variance, 0.) + self.energy_angle_variance + self.nuisance_var)
        # At the pole use the reference implementation's analytic tangent-plane limit.
        for point_index, cone_index in np.argwhere(sine < 1e-7):
            if far_field:
                axis = self.axis[cone_index]
                tangent = (np.eye(3)-np.outer(axis, axis))/self.length[cone_index]
                positional = .5*np.trace(tangent @ self.position_covariance[cone_index].sum(axis=0) @ tangent.T)
            else:
                _, values = geometric_angle_and_variance(
                    self.candidates[cone_index], points[point_index:point_index+1])
                positional = values[0]
            sigma[point_index, cone_index] = math.sqrt(positional+self.energy_angle_variance[cone_index]+self.nuisance_var)
        width = math.sqrt(2.)*sigma
        normalizer = .5*(_erf((math.pi-alpha)/width)+_erf(alpha/width))
        density = -.5*((self.theta-alpha)/sigma)**2-np.log(math.sqrt(2.*math.pi)*sigma*normalizer)
        return np.where(sigma > 1e4, -math.log(math.pi), density)

    def relative_log_response(self, points, *, far_field=False):
        # Log-space mixture retains tiny nonzero tails without inventing a floor.
        with np.errstate(divide='ignore'):
            candidate_logs = self.angular_log_density(points, far_field=far_field)+np.log(self.mass*math.pi)
            unknown_logs = np.log(self.unknown)
        return np.logaddexp(np.logaddexp.reduceat(candidate_logs, self.starts, axis=1), unknown_logs)

    def relative_response(self, points):
        return np.exp(self.relative_log_response(points))

    def validate(self, z_min):
        points = np.array([[0., 0., z_min], [22., -11., 79.], [-120., 181., 1500.]])
        reference = math.pi*np.column_stack([event_response(event, points, self.settings) for event in self.informative])
        actual = np.concatenate([self.relative_response(part) for part in self.batches(points)])
        difference = float(np.max(np.abs(actual-reference)))
        require(np.allclose(actual, reference, rtol=1e-10, atol=1e-11), 'Batched score disagrees with the angular kernel')
        return difference

    def batches(self, points):
        for start in range(0, len(points), self.points_per_batch):
            yield points[start:start+self.points_per_batch]

    def score(self, points, *modes, far_field=False):
        slices = {'first': slice(None, self.first_informative), 'second': slice(self.first_informative, None),
                  'all': slice(None)}
        scores = []
        for part in self.batches(points):
            response = self.relative_log_response(part, far_field=far_field)
            columns = []
            for background, split in modes:
                if background is None:
                    columns.append(profiled_background(response[:, slices[split]])[0])
                    continue
                if not 0 <= background < 1:
                    raise ValueError('Uniform-angle mixture fraction must be in [0,1)')
                log_background = math.log(background) if background else -np.inf
                columns.append(np.logaddexp(math.log1p(-background)+response[:, slices[split]],
                                             log_background).sum(axis=1))
            scores.append(np.column_stack(columns))
        return np.concatenate(scores)
