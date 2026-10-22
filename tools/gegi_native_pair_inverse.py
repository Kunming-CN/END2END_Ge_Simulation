"""Fixed-budget two-site waveform search using the saved native-cell predictor."""
from __future__ import annotations

from dataclasses import dataclass
import itertools

import numpy as np

import gegi_native_inverse as N

TOP_K_PER_MATCHING = 8
SINGLE_SOURCE_SHA256 = '28c77afa687d0168dcd9663717f93c243b128efa2933dfafabc686710892d4e6'


@dataclass(frozen=True)
class PairBank:
    single: N.Bank
    cells: tuple
    center_waves: np.ndarray
    gram: np.ndarray
    pairs: tuple
    matchings: tuple


def prepare_bank(single):
    if N.L.W.sha(N.ROOT/'tools/gegi_native_inverse.py') != SINGLE_SOURCE_SHA256:
        raise ValueError('Use the frozen single-site predictor')
    cells = tuple(c for c in single.cells if c.unsupported_reason is None)
    waves = np.asarray([N.unit_prediction(c, np.full(len(c.active_axes), .5)) for c in cells])
    flat = waves.reshape(len(cells), -1)
    pixels = sorted({c.contact_ids for c in cells})
    matchings = tuple((first, second) for first, second in itertools.combinations(pixels, 2)
                      if first[0] != second[0] and first[1] != second[1])
    pairs = tuple((matching, i, j) for matching, (first, second) in enumerate(matchings)
                  for i, left in enumerate(cells) if left.contact_ids == first
                  for j, right in enumerate(cells) if right.contact_ids == second)
    return PairBank(single, cells, waves, flat@flat.T, pairs, matchings)


def nnls2(a, b, c, d, e, observed_norm):
    """Exact two-column NNLS from Gram[[a,b],[b,c]], rhs[d,e].

    Supports scalar or array inputs. Compare the nonnegative interior solution,
    each one-column boundary and zero. Degenerate columns use the boundaries.
    Returned cost is the residual sum of squares, before sample normalization.
    """
    a, b, c, d, e, norm = np.broadcast_arrays(a, b, c, d, e, observed_norm)
    determinant = a*c-b*b
    independent = determinant > np.finfo(float).eps*np.maximum(a*c, 1.)
    x = np.divide(d*c-e*b, determinant, out=np.zeros_like(d, dtype=float), where=independent)
    y = np.divide(e*a-d*b, determinant, out=np.zeros_like(e, dtype=float), where=independent)
    interior = independent & (x >= 0.) & (y >= 0.)
    boundary_x = np.maximum(0., np.divide(d, a, out=np.zeros_like(d, dtype=float), where=a > 0.))
    boundary_y = np.maximum(0., np.divide(e, c, out=np.zeros_like(e, dtype=float), where=c > 0.))
    candidates_x = np.stack([x, boundary_x, np.zeros_like(x), np.zeros_like(x)])
    candidates_y = np.stack([y, np.zeros_like(y), boundary_y, np.zeros_like(y)])
    costs = (norm-2.*(candidates_x*d+candidates_y*e)+a*candidates_x**2
             +2.*b*candidates_x*candidates_y+c*candidates_y**2)
    costs[0] = np.where(interior, costs[0], np.inf)
    choice = np.argmin(costs, axis=0)
    take = np.expand_dims(choice, 0)
    return (np.take_along_axis(candidates_x, take, axis=0)[0],
            np.take_along_axis(candidates_y, take, axis=0)[0],
            np.maximum(0., np.take_along_axis(costs, take, axis=0)[0]), choice)


def _profile(waveform, first, second):
    a = float(np.sum(first*first)); b = float(np.sum(first*second)); c = float(np.sum(second*second))
    d = float(np.sum(waveform*first)); e = float(np.sum(waveform*second))
    x, y, _, boundary = nnls2(a, b, c, d, e, float(np.sum(waveform*waveform)))
    # Direct residual avoids cancellation in the near-perfect fitted cases.
    residual = waveform-float(x)*first-float(y)*second
    return float(np.mean(residual*residual)), [float(x), float(y)], int(boundary)


def _refine(waveform, bank, coarse):
    indices = coarse['cell_indices']
    cells = [bank.cells[i] for i in indices]
    fractions = [np.full(len(c.active_axes), .5) for c in cells]
    bases = [bank.center_waves[i] for i in indices]
    cost, energies, active_set = _profile(waveform, *bases)
    evaluations = 0
    for step in N.STEPS:
        for site in (0, 1):
            for axis in range(len(fractions[site])):
                start = fractions[site][axis]
                chosen = start
                chosen_basis = bases[site]
                for candidate in (max(0., start-step), min(1., start+step)):
                    if candidate == start:
                        continue
                    trial = fractions[site].copy(); trial[axis] = candidate
                    basis = N.unit_prediction(cells[site], trial)
                    evaluations += 1
                    pair = [basis, bases[1]] if site == 0 else [bases[0], basis]
                    trial_cost, trial_energies, trial_active_set = _profile(waveform, *pair)
                    if trial_cost < cost:
                        cost, energies, active_set = trial_cost, trial_energies, trial_active_set
                        chosen, chosen_basis = candidate, basis
                fractions[site][axis] = chosen
                bases[site] = chosen_basis
    sites = []
    for cell, fraction, energy in zip(cells, fractions, energies):
        position = cell.lower_mm.copy()
        position[list(cell.active_axes)] += fraction*(cell.upper_mm-cell.lower_mm)[list(cell.active_axes)]
        sites.append({'cell_id': cell.cell_id, 'contact_ids': list(cell.contact_ids),
            'fractional_coordinates': fraction.tolist(), 'position_mm': position.tolist(),
            'energy_keV': energy, 'boundary_axes': ['XYZ'[i] for i, f in zip(cell.active_axes, fraction)
                                                 if f == 0. or f == 1.]})
    return {'matching_id': coarse['matching_id'], 'sites': sites,
        'coarse_global_rank': coarse['global_rank'], 'coarse_matching_rank': coarse['matching_rank'],
        'cost_mean_square_keV2': cost, 'rms_keV': float(np.sqrt(cost)),
        'optimizer_status': 'fixed_coordinate_budget_completed', 'new_basis_evaluations': evaluations,
        'energy_active_set': ['interior', 'first_only', 'second_only', 'zero'][active_set]}


def fit_two(waveform, bank):
    """Only the observed summed signed34 waveform and a saved training bank enter."""
    waveform = np.asarray(waveform, dtype=float)
    if waveform.shape != (34, len(N.R.FIT_GRID_NS)) or not np.isfinite(waveform).all():
        raise ValueError('Finite signed34 waveform on FIT_GRID_NS required')
    if not np.any(waveform):
        return {'status': 'unsupported', 'reason': 'zero_observed_waveform', 'coarse_hypotheses': [],
                'refined_hypotheses': []}
    flat = bank.center_waves.reshape(len(bank.cells), -1)
    rhs = flat@waveform.ravel()
    left = np.array([i for _, i, _ in bank.pairs]); right = np.array([j for _, _, j in bank.pairs])
    x, y, costs, active = nnls2(bank.gram[left, left], bank.gram[left, right], bank.gram[right, right],
                              rhs[left], rhs[right], float(np.sum(waveform*waveform)))
    rows = [{'matching_id': f'matching-{m+1}', 'cell_indices': [i, j],
        'cell_ids': [bank.cells[i].cell_id, bank.cells[j].cell_id],
        'contact_ids': [list(bank.cells[i].contact_ids), list(bank.cells[j].contact_ids)],
        'energy_keV': [float(x[k]), float(y[k])], 'cost_mean_square_keV2': float(costs[k]/waveform.size),
        'energy_active_set': ['interior', 'first_only', 'second_only', 'zero'][int(active[k])]}
        for k, (m, i, j) in enumerate(bank.pairs)]
    rows.sort(key=lambda r: (r['cost_mean_square_keV2'], r['matching_id'], r['cell_ids']))
    counts = {}
    for rank, row in enumerate(rows, 1):
        key = row['matching_id']; counts[key] = counts.get(key, 0)+1
        row.update(global_rank=rank, matching_rank=counts[key])
    chosen = [r for r in rows if r['matching_rank'] <= TOP_K_PER_MATCHING]
    refinements = [_refine(waveform, bank, row) for row in chosen]
    refinements.sort(key=lambda r: (r['cost_mean_square_keV2'], r['matching_id'],
                                    [s['cell_id'] for s in r['sites']]))
    matchings = []
    for index, pixel_pair in enumerate(bank.matchings, 1):
        key = f'matching-{index}'
        coarse = [r for r in rows if r['matching_id'] == key]
        refined = [r for r in refinements if r['matching_id'] == key]
        matchings.append({'matching_id': key, 'contact_ids': [list(p) for p in pixel_pair],
            'coarse_count': len(coarse), 'refined_count': len(refined),
            'coarse_best_cost_mean_square_keV2': coarse[0]['cost_mean_square_keV2'],
            'refined_best_cost_mean_square_keV2': refined[0]['cost_mean_square_keV2'],
            'refined_best_optimizer_status': refined[0]['optimizer_status']})
    return {'status': 'fitted', 'reason': None, 'coarse_hypotheses': rows,
        'refined_hypotheses': refinements, 'matchings': matchings,
        'top_k_per_matching': TOP_K_PER_MATCHING,
        'new_basis_evaluations': sum(r['new_basis_evaluations'] for r in refinements)}
