"""Center-template ADC fits for alternate two-by-two GeGI strip-energy allocations."""

from itertools import product
import math

import numpy as np

import gegi_imaging as imaging
import gegi_joint_two_site as joint
from gegi_signal_reconstruction import energy_flows


NEAR_TIE_ADC_CODES = joint.NEAR_TIE_RMS_INCREMENT * joint.NOISE_RMS_V / joint.digital._LSB_V


def matching_marginals(collectors):
    """Keep original energies and find the nearest matching face totals within strip tolerances."""
    xs = sorted((row['contact_id'], row['slow_energy_keV']) for row in collectors if 1 <= row['contact_id'] <= 16)
    ys = sorted((row['contact_id'], row['slow_energy_keV']) for row in collectors if 18 <= row['contact_id'] <= 33)
    ordered = xs + ys
    if len(xs) != 2 or len(ys) != 2 or len({cid for cid, _ in ordered}) != 4 or len(collectors) != 4:
        raise ValueError('Topology diagnostics require four original distinct collecting strip measurements')
    measured = np.asarray([energy for _, energy in ordered], dtype=float)
    if not np.isfinite(measured).all() or np.any(measured < imaging.MIN_COLLECTED_KEV):
        raise ValueError('Topology diagnostics require qualified original collecting strip energies')
    faces = [[{'contact_id': cid, 'reconstructed_energy_keV': energy} for cid, energy in face] for face in (xs, ys)]
    flows, ledger = energy_flows(*faces)
    tolerance = np.maximum(imaging.PAIR_ABS_KEV, imaging.PAIR_REL * measured)
    contrast = np.array([1., 1., -1., -1.])
    weight = tolerance**2
    matching = measured - weight * contrast * (contrast @ measured) / weight.sum()
    if (ledger.get('reason') == 'face_energy_mismatch' or np.any(matching < 0.)
            or np.any(np.abs(matching - measured) > tolerance + 1e-9)):
        matching = None
    cells = tuple(product((cid for cid, _ in xs), (cid for cid, _ in ys)))
    return cells, flows, ledger, measured, tolerance, matching


def energy_family(values):
    """Parameterize the nonnegative 2×2 continuum by the first corner energy in keV."""
    x1, x2, y1, _ = values
    bounds = max(0., y1 - x2), min(x1, y1)

    def allocate(first):
        return np.maximum([first, x1-first, y1-first, x2-y1+first], 0.)

    return bounds, allocate


def fit_flow(cells, templates, volts, *, energies=None, family=None):
    """Fit one shared onset and a depth per corner, with one extra energy parameter for the cycle."""
    if any(cell not in templates for cell in cells):
        return {'status': 'missing_center_template', 'cells': cells,
                'missing_cells': [cell for cell in cells if cell not in templates]}
    n = len(cells)
    centers = joint._interpolators([templates[cell] for cell in cells], slice(None), (False,) * n)
    observed = joint.remove_quiet_tail(volts)
    depth_lo, depth_hi = float(joint.DEPTH_MM[0]), float(joint.DEPTH_MM[-1])
    bounds = ([depth_lo] * n + [joint.SHIFT_LIMIT_NS[0]], [depth_hi] * n + [joint.SHIFT_LIMIT_NS[1]])
    scales = [5.] * n + [20.]
    energy_seeds = [()]
    if family is not None:
        (low, high), allocate = family
        if not high > low:
            return {'status': 'continuum_had_no_free_width', 'cells': cells}
        width = high-low
        bounds[0].append(low)
        bounds[1].append(high)
        scales.append(width)
        energy_seeds = [(low + width*f,) for f in (.05, .5, .95)]

    def energy_values(point):
        return allocate(point[-1]) if family is not None else energies

    def residual(point):
        analog = sum(energy * center([z])[0] for z, energy, (center, _) in
                     zip(point[:n], energy_values(point), centers, strict=True))
        samples = joint.shifted_samples(analog, point[n])
        return ((joint.remove_quiet_tail(samples) - observed) / joint.NOISE_RMS_V).ravel()

    grid = ((*z, onset, *e) for z, onset, e in product(product((-4., 0., 4.), repeat=n), (-15., 5.), energy_seeds))
    starts = sorted((np.asarray(point) for point in grid), key=lambda point: np.linalg.norm(residual(point)))[:3]
    best, alternatives, diagnostics = joint._best_refinement(residual, starts, bounds, np.asarray(scales))

    def details(result):
        depth = result.x[:n]
        site_energies = list(energy_values(result.x))
        return {'site_energies_keV': site_energies, 'modeled_total_energy_keV': math.fsum(site_energies),
                'site_positions_mm': [[*templates[cell].origin_mm, z] for cell, z in zip(cells, depth, strict=True)],
                'onset_relative_to_trigger_ns': float(result.x[n]),
                'weighted_residual_rms': math.sqrt(2 * result.cost / len(result.fun)),
                'optimizer_success': bool(result.success),
                'depth_boundary_sites': [i for i, z in enumerate(depth)
                                         if min(z-depth_lo, depth_hi-z) <= joint.BOUNDARY_TOLERANCE],
                'onset_at_boundary': bool(min(result.x[n]-bounds[0][n], bounds[1][n]-result.x[n])
                                         <= joint.BOUNDARY_TOLERANCE),
                'allocation_at_boundary': bool(family is not None and
                                               min(result.x[-1]-low, high-result.x[-1]) <= 1e-4)}

    rms = np.sqrt(np.mean(best.fun.reshape(volts.shape)**2, axis=1)) * joint.NOISE_RMS_V / joint.digital._LSB_V
    return {'status': 'scored' if best.success else 'optimizer_unconverged', 'cells': cells,
            'global_adc_rms_codes': float(np.sqrt(np.mean(rms**2))), 'per_contact_adc_rms_codes': rms.tolist(),
            'fit': details(best), 'optimizer': diagnostics,
            'sampled_near_ties': [details(row) for row in alternatives if row is not best]}


def scan_allocations(collectors, volts, templates):
    """Return each sparse, weak-endpoint and continuous allocation independently."""
    joint._check_adc(volts)
    cells, flows, ledger, measured, tolerances, matching = matching_marginals(collectors)
    result = {'collector_contact_ids': sorted({cid for cell in cells for cid in cell}),
              'measured_strip_energies_keV': measured.tolist(), 'strip_tolerances_keV': tolerances.tolist(),
              'face_balanced_strip_energies_keV': None, 'continuous_energy_bounds_keV': None,
              'sparse_flow_bookkeeping': ledger, 'hypotheses': []}
    for flow in flows:
        selected, energies = zip(*[((x, y), energy) for x, y, energy in flow], strict=True)
        fit = fit_flow(selected, templates, volts, energies=energies)
        result['hypotheses'].append(dict(fit, kind=f'{len(flow)}_corner_sparse'))
    if matching is not None:
        bounds, allocate = energy_family(matching)
        result.update(face_balanced_strip_energies_keV=matching.tolist(), continuous_energy_bounds_keV=bounds)
        for side, first in zip(('lower', 'upper'), bounds, strict=True):
            endpoint = [(cell, float(energy)) for cell, energy in zip(cells, allocate(first), strict=True) if energy > 1e-9]
            if len(endpoint) == 3 and any(energy < imaging.MIN_COLLECTED_KEV for _, energy in endpoint):
                selected, energies = zip(*endpoint, strict=True)
                fit = fit_flow(selected, templates, volts, energies=energies)
                result['hypotheses'].append(dict(fit, kind=f'3_corner_weak_endpoint_{side}'))
        result['hypotheses'].append(dict(fit_flow(cells, templates, volts, family=(bounds, allocate)), kind='4_corner_continuum'))
    return result
