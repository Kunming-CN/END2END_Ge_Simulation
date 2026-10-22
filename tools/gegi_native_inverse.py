"""Bounded single-site inversion of the sealed saved GeGI native-cell bank.

The fitting API takes only a signed34 waveform and a training bank. It never
receives a source, true pixel, true position, deposition energy or target row.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
import time

import numpy as np

import gegi_lateral_forward_comparison as L
import gegi_lateral_timing_comparison as T
import gegi_signal_reconstruction as R

ROOT = Path(__file__).resolve().parents[1]
REQUEST_SHA256 = 'c1ae221e7486007f8d79fec748bdabeb771707c02b5accd0be1401f2a8e831fd'
COMPLETE_SHA256 = '9558d3533446380a82667cd8ad6dfec0fe0d12442553d97e42e8201ee787de73'
TIMING_SHA256 = '953a45ade227f2d2fa290c66de282fd05ed2290a41590cdd3a7bc204f1ef787c'
HELPERS = ('tools/gegi_lateral_forward_comparison.py',
           'tools/gegi_lateral_timing_comparison.py',
           'tools/gegi_signal_reconstruction.py', 'tools/scenario_workflow.py')
STEPS = tuple(2.**-i for i in range(1, 9))


@dataclass(frozen=True)
class Corner:
    ref: str
    position_mm: np.ndarray
    times_ns: np.ndarray
    unit_wave: np.ndarray
    unit_delta: np.ndarray
    arrivals_ns: dict


@dataclass(frozen=True)
class Cell:
    cell_id: str
    contact_ids: tuple
    corners: tuple
    lower_mm: np.ndarray
    upper_mm: np.ndarray
    active_axes: tuple
    bits: np.ndarray
    unsupported_reason: str | None


@dataclass(frozen=True)
class Bank:
    cells: tuple
    coverage: dict
    input_sha256: dict
    helper_sha256: dict
    native_producer_sha256: dict
    load_seconds: float


def _checked(path, expected):
    raw = Path(path).read_bytes()
    if R._sha(raw) != expected:
        raise ValueError('Sealed saved input changed: '+str(path))
    return json.loads(raw)


def load_bank(directory):
    """Check exact saved bytes once, retaining training data and no target truth.

    Native producer hashes describe the historical capture. Current Julia source
    is deliberately not compared: this tool cannot execute native simulation.
    Current Python waveform/time-warp helpers must match the saved source seal.
    """
    started = time.perf_counter()
    directory = Path(directory).resolve()
    results = directory/'results'
    request = _checked(directory/'request.json', REQUEST_SHA256)
    complete = _checked(results/'COMPLETE.json', COMPLETE_SHA256)
    timing = _checked(results/'timing-comparison.json', TIMING_SHA256)
    if (complete['request_sha256'] != REQUEST_SHA256
            or complete['status'] != 'completed_fixed80_native_grid_near_bank'
            or len(complete['points']) != 378 or request['injection_energy_keV'] != 500.):
        raise ValueError('Completed fixed native-cell bank required')
    helper_sha = {ref: request['source_file_sha256'][ref] for ref in HELPERS}
    for ref, expected in helper_sha.items():
        if L.W.sha(ROOT/ref) != expected:
            raise ValueError('Pinned Python helper changed: '+ref)
    bindings = dict(timing['input_sha256'])
    bindings[(directory/'request.json').relative_to(ROOT).as_posix()] = REQUEST_SHA256
    bindings[(results/'COMPLETE.json').relative_to(ROOT).as_posix()] = COMPLETE_SHA256
    bindings[(results/'timing-comparison.json').relative_to(ROOT).as_posix()] = TIMING_SHA256
    points = {p['record_ref']: p for p in request['points']}
    seals = {p['record_ref']: p['record_sha256'] for p in complete['points']}
    if set(points) != set(seals):
        raise ValueError('Training point/receipt census differs')
    needed = {(results/ref).relative_to(ROOT).as_posix(): ref for ref in points}
    payloads = {}
    for ref, expected in bindings.items():
        raw = (ROOT/ref).read_bytes()
        if R._sha(raw) != expected:
            raise ValueError('Sealed saved input changed: '+ref)
        if ref in needed:
            record_ref = needed[ref]
            if expected != seals[record_ref]:
                raise ValueError('Training record seal differs from COMPLETE')
            payloads[record_ref] = json.loads(raw)['payload']
    if len(payloads) != 378:
        raise ValueError('Missing sealed training records')
    corners = {}
    dt = request['numerics']['dt']
    for ref, row in payloads.items():
        values, support = L.waveform(row)
        if values is None:
            raise ValueError('Incomplete admitted training record: '+ref+': '+str(support))
        waves = [R._wave(s) for s in row['channel_signals']]
        times = waves[0][0]
        if any(not np.array_equal(t, times) for t, _ in waves):
            raise ValueError('Common native time axis required')
        energy = row['injection_energy_keV']
        if energy != 500.:
            raise ValueError('Fixed training gain required')
        unit = np.asarray([q for _, q in waves])/energy
        corners[ref] = Corner(ref, np.asarray(points[ref]['native_position_m'])*1000.,
            times, unit, np.diff(unit, axis=1), T.arrivals(row, dt))
    # Only the unique training-corner sets are retained from the frozen request.
    # No target position, pixel, weight, energy or endpoint reaches the Bank.
    sets = sorted({tuple(sorted(w['record_ref'] for w in t['training_weights']))
                   for t in request['targets']})
    cells = []
    for index, refs in enumerate(sets, 1):
        selected = tuple(corners[ref] for ref in refs)
        positions = np.asarray([c.position_mm for c in selected])
        lower, upper = positions.min(axis=0), positions.max(axis=0)
        active = tuple(int(i) for i in np.flatnonzero(upper > lower))
        bits = np.asarray([[int(c.position_mm[i] == upper[i]) for i in active]
                           for c in selected], dtype=bool)
        if (len(selected) != 2**len(active)
                or len({tuple(b) for b in bits}) != len(selected)
                or any(not np.isin(positions[:, i], [lower[i], upper[i]]).all() for i in active)):
            raise ValueError('Training records are not a complete tensor cell')
        pixels = {tuple(points[ref]['contact_ids']) for ref in refs}
        if len(pixels) != 1:
            raise ValueError('Cell mixes training pixel identities')
        reason = None
        try:
            for c in selected:
                T.knots(c.arrivals_ns)
            if len({c.arrivals_ns['electron'] < c.arrivals_ns['hole'] for c in selected}) != 1:
                raise T.UnsupportedWarp('carrier_order_flips')
        except T.UnsupportedWarp as error:
            reason = str(error)
        cells.append(Cell(f'cell-{index:03}', next(iter(pixels)), selected,
                          lower, upper, active, bits, reason))
    coverage = {'training_records': len(corners), 'candidate_cells': len(cells),
        'supported_cells': sum(c.unsupported_reason is None for c in cells),
        'unsupported_reasons': dict(Counter(c.unsupported_reason for c in cells if c.unsupported_reason)),
        'pixels': [list(p) for p in sorted({c.contact_ids for c in cells})],
        'dimensions': dict(Counter(str(len(c.active_axes)) for c in cells)),
        'cells': [{'cell_id': c.cell_id, 'contact_ids': list(c.contact_ids),
                   'lower_mm': c.lower_mm.tolist(), 'upper_mm': c.upper_mm.tolist(),
                   'free_axes': ['XYZ'[i] for i in c.active_axes],
                   'corner_refs': [p.ref for p in c.corners],
                   'unsupported_reason': c.unsupported_reason} for c in cells],
        'scope': 'Union of these80 native cells in4pixels only; intervening gaps and the rest of the detector are not covered.'}
    return Bank(tuple(cells), coverage, bindings, helper_sha,
                dict(request['source_file_sha256']), time.perf_counter()-started)


def weights_for(cell, fractions):
    fractions = np.asarray(fractions, dtype=float)
    weights = np.prod(np.where(cell.bits, fractions, 1.-fractions), axis=1)
    keep = np.flatnonzero(weights > 0)
    selected = weights[keep].tolist()
    total = sum(selected)
    if total != 1.:
        if abs(total-1.) > len(selected)*np.finfo(float).eps:
            raise ValueError('Spatial weights do not close within roundoff')
        selected[-1] = 1.-sum(selected[:-1])
    return keep, selected


def unit_prediction(cell, fractions):
    """T.predict's common carrier warp, vectorized over the34 common-time waves."""
    if cell.unsupported_reason:
        raise T.UnsupportedWarp(cell.unsupported_reason)
    keep, weights = weights_for(cell, fractions)
    corners = [cell.corners[i] for i in keep]
    target = {s: sum(w*c.arrivals_ns[s] for w, c in zip(weights, corners))
              for s in ('electron', 'hole')}
    prediction = np.zeros((34, len(R.FIT_GRID_NS)))
    for corner, weight in zip(corners, weights):
        query = T.mapped_times(target, corner.arrivals_ns, R.FIT_GRID_NS)
        index = np.searchsorted(corner.times_ns, query, side='right')-1
        index = np.clip(index, 0, len(corner.times_ns)-2)
        fraction = np.clip((query-corner.times_ns[index])/
                           (corner.times_ns[index+1]-corner.times_ns[index]), 0., 1.)
        prediction += weight*(corner.unit_wave[:, index]+corner.unit_delta[:, index]*fraction)
    return prediction


def _profile(waveform, prediction):
    norm = float(np.sum(prediction*prediction))
    energy = max(0., float(np.sum(waveform*prediction))/norm) if norm > 0 else 0.
    residual = waveform-energy*prediction
    return float(np.mean(residual*residual)), energy


def _fit_cell(waveform, cell):
    fractions = np.full(len(cell.active_axes), .5)
    cost, energy = _profile(waveform, unit_prediction(cell, fractions))
    evaluations = 1
    # One fixed centre start; all coordinates search the whole closed cell.
    # Eight deterministic shrinking steps are a bounded search, not a claim of
    # derivative convergence or a statistical confidence region.
    for step in STEPS:
        for axis in range(len(fractions)):
            best_fraction = fractions[axis]
            for candidate in (max(0., fractions[axis]-step), min(1., fractions[axis]+step)):
                if candidate == fractions[axis]:
                    continue
                trial = fractions.copy(); trial[axis] = candidate
                trial_cost, trial_energy = _profile(waveform, unit_prediction(cell, trial))
                evaluations += 1
                if trial_cost < cost:
                    cost, energy, best_fraction = trial_cost, trial_energy, candidate
            fractions[axis] = best_fraction
    position = cell.lower_mm.copy()
    position[list(cell.active_axes)] += fractions*(cell.upper_mm-cell.lower_mm)[list(cell.active_axes)]
    return {'cell_id': cell.cell_id, 'contact_ids': list(cell.contact_ids),
        'position_mm': position.tolist(), 'energy_keV': energy,
        'fractional_coordinates': fractions.tolist(), 'cost_mean_square_keV2': cost,
        'rms_keV': float(np.sqrt(cost)), 'boundary_axes': ['XYZ'[axis] for axis, value in
            zip(cell.active_axes, fractions) if value == 0. or value == 1.],
        'optimizer_status': 'fixed_coordinate_budget_completed', 'model_evaluations': evaluations}


def fit_single(waveform, bank):
    """Search every admitted cell using only observed native signed keV samples."""
    waveform = np.asarray(waveform, dtype=float)
    if waveform.shape != (34, len(R.FIT_GRID_NS)) or not np.isfinite(waveform).all():
        raise ValueError('Finite signed34 waveform on FIT_GRID_NS required')
    if not np.any(waveform):
        return {'status': 'unsupported', 'reason': 'zero_observed_waveform', 'hypotheses': []}
    hypotheses = [_fit_cell(waveform, c) for c in bank.cells if c.unsupported_reason is None]
    hypotheses.sort(key=lambda h: (h['cost_mean_square_keV2'], h['cell_id']))
    return {'status': 'fitted' if hypotheses else 'unsupported',
        'reason': None if hypotheses else 'no_supported_candidate_cells',
        'searched_cells': len(hypotheses), 'hypotheses': hypotheses,
        'unsupported_cells': [{'cell_id': c.cell_id, 'reason': c.unsupported_reason}
                              for c in bank.cells if c.unsupported_reason]}


def self_checks(bank):
    """One-time affine/corner and saved T.predict equivalence checks."""
    affine_max = equivalence_max = 0.
    # Reconstruct the fields needed by the unmodified reference helper from
    # admitted training arrays; this does not reopen any target record.
    for cell in bank.cells:
        for fractions in (np.zeros(len(cell.active_axes)), np.ones(len(cell.active_axes)),
                          np.full(len(cell.active_axes), .37)):
            keep, weights = weights_for(cell, fractions)
            expected = cell.lower_mm.copy()
            expected[list(cell.active_axes)] += fractions*(cell.upper_mm-cell.lower_mm)[list(cell.active_axes)]
            actual = sum(w*cell.corners[i].position_mm for i, w in zip(keep, weights))
            affine_max = max(affine_max, float(np.max(np.abs(actual-expected))))
        if cell.unsupported_reason:
            continue
        fractions = np.full(len(cell.active_axes), .37)
        keep, weights = weights_for(cell, fractions)
        rows = []
        for i in keep:
            corner = cell.corners[i]
            # Recreate only the reference helper's required training fields.
            rows.append({'signal_coverage': R.ALL34_COVERAGE,
                'channel_signals': [{'contact_id': cid, 'time_ns': corner.times_ns,
                    'signed_induced_keV': corner.unit_wave[cid-1]*500.} for cid in R.ALL34_IDS],
                'endpoints': [{'species': s, 'samples': corner.arrivals_ns[s]+1,
                    'step_limit_reached': False, 'status': 'contact'} for s in ('electron', 'hole')]})
        reference, _, _ = T.predict(rows, weights, 1.)
        equivalence_max = max(equivalence_max, float(np.max(np.abs(reference/500.-unit_prediction(cell, fractions)))))
    if affine_max > 1e-12 or equivalence_max > 2e-15:
        raise AssertionError('Affine/reference predictor equivalence failed')
    # A synthetic observation from one corner has no target metadata and its
    # independently scaled energy must be recovered by the global search.
    cell = next(c for c in bank.cells if c.unsupported_reason is None)
    corner_fraction = np.zeros(len(cell.active_axes))
    observed = unit_prediction(cell, corner_fraction)*317.
    fitted = fit_single(observed, bank)
    best = fitted['hypotheses'][0]
    corner_error = float(np.linalg.norm(np.asarray(best['position_mm'])-cell.lower_mm))
    if corner_error > 1e-10 or abs(best['energy_keV']-317.) > 1e-9 or best['rms_keV'] > 1e-10:
        raise AssertionError('Global corner/independent amplitude recovery failed')
    try:
        fit_single(observed, bank, true_position_mm=cell.lower_mm)
    except TypeError:
        truth_rejected = True
    else:
        raise AssertionError('Fit accepted true-position metadata')
    return {'max_affine_position_error_mm': affine_max,
        'max_unit_wave_difference_vs_T_predict': equivalence_max,
        'corner_position_error_mm': corner_error, 'corner_energy_error_keV': best['energy_keV']-317.,
        'corner_rms_keV': best['rms_keV'], 'truth_argument_rejected': truth_rejected,
        'fit_signature': '(waveform, bank)', 'bank_retains_target_truth': False}
