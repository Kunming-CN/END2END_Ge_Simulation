"""Conditional cone geometry for retained joint position samples."""

from itertools import combinations
import math

import numpy as np

import gegi_imaging as imaging
import gegi_joint_imaging as response


RADII_MM = (50., 100., 300., 1000.)
DIRECTIONS = 96
SIGMA_DEG = response.ResponseSettings().angular_nuisance_sigma_deg


def solutions(model):
    return [{'fit_role': 'best' if i == 0 else 'sampled_alternate',
             'positions_mm': row['positions_mm'], 'weighted_residual_rms': row['weighted_residual_rms'],
             'onset_relative_to_trigger_ns': row['parameters'][-1],
             'optimizer_success': row['optimizer_success'], 'parameter_boundaries': row['parameter_boundaries'],
             'site_separation_mm': math.dist(*row['positions_mm'])}
            for i, row in enumerate((model, *model['sampled_alternates']))]


def axis_angle(a, b):
    return math.degrees(math.atan2(np.linalg.norm(np.cross(a, b)), np.dot(a, b)))


def response_spread(candidates, points, radii):
    # Positions already vary explicitly through the joint samples. The fixed
    # kernel isolates this geometry comparison from any extra uncertainty term.
    alpha = np.array([response.geometric_angle_and_variance(candidate, points)[0] for candidate in candidates])
    density = np.array([response.angular_density(candidate.theta, angles, math.radians(SIGMA_DEG))
                        for candidate, angles in zip(candidates, alpha, strict=True)])
    angle = np.degrees(np.ptp(alpha, axis=0)).reshape(len(radii), -1)
    span = np.ptp(density, axis=0).reshape(angle.shape)
    return [{'radius_mm': radius, 'geometric_angle_span_rms_deg': float(np.sqrt(np.mean(a*a))),
             'geometric_angle_span_max_deg': float(np.max(a)),
             'fixed_kernel_response_span_rms_per_rad': float(np.sqrt(np.mean(d*d))),
             'fixed_kernel_response_span_max_per_rad': float(np.max(d))}
            for radius, a, d in zip(radii, angle, span, strict=True)]


def order_geometry(samples, energies, order, points, radii):
    """Retain joint positions and optimizer status without assigning sample mass."""
    i, j = order['site_index_order']
    rows = []
    for index, sample in enumerate(samples):
        positions = sample['positions_mm']
        first, second = (dict(position_mm=positions[k], energy_keV=energies[k]) for k in (i, j))
        candidate = None
        if not order['kinematically_allowed']:
            status = 'energy_order_inadmissible'
        else:
            candidate = imaging.cone(first, second)
            status = 'available_geometry' if candidate is not None else 'geometry_below_existing_separation_support'
        if candidate is not None and (not math.isclose(candidate['half_angle_deg'], order['half_angle_deg'],
                                                       rel_tol=0., abs_tol=1e-9)):
            raise ValueError('Angle from measured energies differs from the original order')
        rows.append({'solution_index': index, 'geometry_status': status, 'cone': candidate})
    # Convergence is recorded per sample. Any finite saved alternative can
    # describe conditional geometry; its optimizer status remains visible.
    cones = [row['cone'] for row in rows if row['cone'] is not None]
    result = {'status': 'available_geometry' if cones else (rows[0]['geometry_status'] if rows else 'no_saved_fit'),
              'solutions': rows, 'geometry_count': len(cones), 'axis_pairwise_span_max_deg': None,
              'converged_geometry_count': sum(row['cone'] is not None and sample['optimizer_success']
                                              for row, sample in zip(rows, samples, strict=True)),
              'site_separation_range_mm': None, 'finite_vertex_response_by_radius': []}
    if cones:
        axes = [c['axis'] for c in cones]
        distances = [c['site_separation_mm'] for c in cones]
        settings = response.ResponseSettings()
        candidates = [response.prepare_candidate(c | {'position_covariance_mm2': np.zeros((2, 3, 3))}, settings)
                      for c in cones]
        result.update(axis_pairwise_span_max_deg=max((axis_angle(a, b) for a, b in combinations(axes, 2)), default=0.),
                      site_separation_range_mm=[min(distances), max(distances)],
                      finite_vertex_response_by_radius=response_spread(candidates, points, radii))
    return result
