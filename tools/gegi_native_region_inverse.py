"""Dense saved-cell pairing search; reuse the frozen predictor and optimizer."""
from __future__ import annotations

from dataclasses import dataclass
from collections import Counter
import itertools
import json
from pathlib import Path
import time

import numpy as np

import gegi_native_pair_inverse as P

N = P.N
REGION_SUMMARY_SHA256 = '8bc72dbc95097a103e9e8336b44cc4ff212ad115169a3946d6daa2f215e39068'


def load_region(directory, request_sha256, complete_sha256):
    """Admit one sealed completed region once; retain training data only."""
    started = time.perf_counter()
    directory = Path(directory).resolve()
    results = directory/'results'
    request = N._checked(directory/'request.json', request_sha256)
    complete = N._checked(results/'COMPLETE.json', complete_sha256)
    if (request['kind'] != 'gegi_fixed_interior_native_region_request_v1'
            or complete['status'] != 'completed_fixed_interior_native_region_bank'
            or complete['request_sha256'] != request_sha256
            or len(request['points']) != 5148 or len(complete['points']) != 5148
            or request['injection_energy_keV'] != 500.):
        raise ValueError('Completed fixed5148-point interior region required')
    bindings = {(directory/'request.json').relative_to(N.ROOT).as_posix(): request_sha256,
                (results/'COMPLETE.json').relative_to(N.ROOT).as_posix(): complete_sha256}
    admitted = {}
    for binding in request['input_bindings'].values():
        admitted[binding['ref']] = N._checked(N.ROOT/binding['ref'], binding['sha256'])
        bindings[binding['ref']] = binding['sha256']
    original = admitted[request['input_bindings']['source_request']['ref']]
    if (request['input_bindings']['source_request']['sha256'] != N.REQUEST_SHA256
            or request['source_native_request_sha256'] != N.REQUEST_SHA256
            or request['field_cache'] != original['field_cache']
            or request['model_sha256'] != original['model_sha256']
            or request['numerics'] != original['numerics']):
        raise ValueError('Region/native-bank physical identity differs')
    bridge = request['source_compatibility_bridge']
    if (bridge['calibration_sha256'] != original['source_file_sha256']['simulation/gegi_response.jl']
            or bridge['native_sha256'] != request['source_file_sha256']['simulation/gegi_response.jl']
            or bridge['kind'] != 'gegi_single_pass_readout_source_bridge_v1'):
        raise ValueError('Historical native readout source bridge differs')
    helpers = {ref: original['source_file_sha256'][ref] for ref in N.HELPERS}
    for ref, digest in helpers.items():
        if N.L.W.sha(N.ROOT/ref) != digest:
            raise ValueError('Pinned waveform/time-warp helper changed: '+ref)
    for item in ({'ref': request['model_ref'], 'sha256': request['model_sha256']}, request['field_cache']):
        if N.L.W.sha(N.ROOT/item['ref']) != item['sha256']:
            raise ValueError('Original model/field bytes changed')
        bindings[item['ref']] = item['sha256']
    worker_ref = (results/'full34-worker.jl').relative_to(N.ROOT).as_posix()
    if N.L.W.sha(N.ROOT/worker_ref) != request['worker_sha256']:
        raise ValueError('Sealed region capture worker differs')
    bindings[worker_ref] = request['worker_sha256']
    preflight_ref = (results/'preflight.json').relative_to(N.ROOT).as_posix()
    preflight = N._checked(N.ROOT/preflight_ref, complete['preflight_sha256'])
    bindings[preflight_ref] = complete['preflight_sha256']
    summary_ref = (results/'summary.json').relative_to(N.ROOT).as_posix()
    summary = N._checked(N.ROOT/summary_ref, REGION_SUMMARY_SHA256)
    if summary['complete_sha256'] != complete_sha256 or summary['request_sha256'] != request_sha256:
        raise ValueError('Region numerical summary identity differs')
    bindings[summary_ref] = REGION_SUMMARY_SHA256
    source_preflight = admitted[request['input_bindings']['native_preflight']['ref']]
    if (preflight['weighting_axes_m'] != source_preflight['weighting_axes_m']
            or preflight['electric_field_axes_m'] != source_preflight['electric_field_axes_m']):
        raise ValueError('Recorded native axes differ')
    axes = preflight['weighting_axes_m']
    seals = {r['record_ref']: r for r in complete['points']}
    points = {p['record_ref']: p for p in request['points']}
    if set(seals) != set(points):
        raise ValueError('Region receipt/point census differs')
    corners = {}
    point_info = {}
    by_index = {}
    for ref, point in points.items():
        seal = seals[ref]
        path = results/ref
        record = N._checked(path, seal['record_sha256'])
        bindings[path.relative_to(N.ROOT).as_posix()] = seal['record_sha256']
        if record['identity_sha256'] != request_sha256:
            raise ValueError('Region record identity differs')
        row = record['payload']
        if (row['position_mm'] != point['position_mm'] or row['contact_ids'] != point['contact_ids']
                or row['injection_energy_keV'] != 500.):
            raise ValueError('Region point, expected pixel or fixed gain differs')
        index = tuple(point['grid_indices_zero_based'])
        if index in by_index or point['requested_grid_position_m'] != [axes[d][i] for d, i in enumerate(index)]:
            raise ValueError('Region grid point duplicated or moved')
        if 'source_record' in point:
            source = N._checked(N.ROOT/point['source_record']['ref'], point['source_record']['sha256'])
            bindings[point['source_record']['ref']] = point['source_record']['sha256']
            if (source['payload_sha256'] != point['source_payload_sha256']
                    or record['payload_sha256'] != point['source_payload_sha256']
                    or row != source['payload']):
                raise ValueError('Imported native response changed')
        reasons = []
        if row['valid'] is not True or row['status'] != 'completed':
            reasons.append('record_'+row['status'])
        endpoint_map = {e['species']: e for e in row.get('endpoints') or []}
        actual = None
        if set(endpoint_map) == {'electron', 'hole'}:
            electron = endpoint_map['electron']['contact_ids']; hole = endpoint_map['hole']['contact_ids']
            if len(electron) == len(hole) == 1:
                actual = (hole[0], electron[0])
        times = {}
        try:
            times = N.T.arrivals(row, request['numerics']['dt'])
            N.T.knots(times)
        except N.T.UnsupportedWarp as error:
            reasons.append(str(error))
        unit = np.empty((34, 0)); native_time = np.empty(0)
        if not reasons:
            values, support = N.L.waveform(row)
            if values is None:
                reasons.append(support['reason'])
            else:
                waves = [N.R._wave(s) for s in row['channel_signals']]
                native_time = waves[0][0]
                if any(not np.array_equal(t, native_time) for t, _ in waves):
                    raise ValueError('Common34-channel native time axis required')
                unit = np.asarray([q for _, q in waves])/500.
        corners[ref] = N.Corner(ref, np.asarray(point['native_position_m'])*1000.,
            native_time, unit, np.diff(unit, axis=1), times)
        point_info[ref] = {'reasons': reasons, 'actual_pixel': actual, 'status': row['status'],
                           'valid': row['valid']}
        by_index[index] = ref
    cells = []
    coverage_rows = []
    z = request['interior_z_indices_zero_based']
    if any(b != a+1 for a, b in zip(z, z[1:])):
        raise ValueError('Contiguous interior Z nodes required')
    for region in request['regions']:
        pixel = tuple(region['contact_ids'])
        for xi, yi, zi in itertools.product(region['x_interval_indices_zero_based'],
                                           region['y_interval_indices_zero_based'], z[:-1]):
            refs = [by_index[(xi+dx, yi+dy, zi+dz)] for dx, dy, dz in itertools.product((0, 1), repeat=3)]
            selected = tuple(corners[ref] for ref in refs)
            reasons = sorted({reason for ref in refs for reason in point_info[ref]['reasons']})
            if any(point_info[ref]['actual_pixel'] != pixel for ref in refs):
                reasons.append('corner_collector_pair_mismatch')
            if not reasons and len({p.arrivals_ns['electron'] < p.arrivals_ns['hole'] for p in selected}) != 1:
                reasons.append('carrier_order_flips')
            lower = np.min([p.position_mm for p in selected], axis=0)
            upper = np.max([p.position_mm for p in selected], axis=0)
            bits = np.asarray(list(itertools.product((False, True), repeat=3)), dtype=bool)
            cell_id = f'region-cell-{len(cells)+1:05}'
            cells.append(N.Cell(cell_id, pixel, selected, lower, upper, (0, 1, 2), bits,
                                ';'.join(reasons) if reasons else None))
            coverage_rows.append({'cell_id': cell_id, 'contact_ids': list(pixel), 'lower_mm': lower.tolist(),
                'upper_mm': upper.tolist(), 'grid_lower_indices_zero_based': [xi, yi, zi],
                'corner_refs': refs, 'unsupported_reasons': reasons})
    coverage = {'training_records': len(points), 'candidate_cells': len(cells),
        'supported_cells': sum(c.unsupported_reason is None for c in cells),
        'unsupported_cells': sum(c.unsupported_reason is not None for c in cells),
        'unsupported_reasons': dict(Counter(reason for c in coverage_rows for reason in c['unsupported_reasons'])),
        'point_status_counts': dict(Counter(info['status'] for info in point_info.values())),
        'point_actual_collector_pairs': {str(pair): count for pair, count in Counter(info['actual_pixel'] for info in point_info.values()).items()},
        'supported_cells_by_pixel': {str(list(r['contact_ids'])): sum(c.contact_ids == tuple(r['contact_ids']) and c.unsupported_reason is None for c in cells)
                                    for r in request['regions']},
        'pixels': [r['contact_ids'] for r in request['regions']], 'regions': request['regions'],
        'native_numerical_diagnostics': {
            'max_absolute_terminal_endpoint_algebra_error_keV': summary['max_absolute_terminal_endpoint_algebra_error_keV'],
            'max_absolute_terminal_ideal_contact_error_keV': summary['max_absolute_terminal_ideal_contact_error_keV'],
            'scope': 'Preserved native signed waveforms and fixed500keV training gain; no ideal-contact normalization or added acceptance threshold.'},
        'interior_z_indices_zero_based': z, 'cells': coverage_rows,
        'scope': 'Geometry-defined strict-interior strip-footprint grid only. Mixed/incomplete collectors and carrier-order flips remain explicitly unsupported; valid canonical records are never relabeled.'}
    return N.Bank(tuple(cells), coverage, bindings, helpers, dict(request['source_file_sha256']), time.perf_counter()-started)


@dataclass(frozen=True)
class DenseBlock:
    matching_id: str
    contact_ids: tuple
    left_indices: np.ndarray
    right_indices: np.ndarray
    cross_gram: np.ndarray


@dataclass(frozen=True)
class DenseBank:
    single: N.Bank
    cells: tuple
    center_waves: np.ndarray
    norms: np.ndarray
    blocks: tuple
    preparation_seconds: dict


def prepare_dense(single):
    started = time.perf_counter()
    cells = tuple(sorted((c for c in single.cells if c.unsupported_reason is None), key=lambda c: c.cell_id))
    waves = np.asarray([N.unit_prediction(c, np.full(len(c.active_axes), .5)) for c in cells])
    template_seconds = time.perf_counter()-started
    flat = waves.reshape(len(cells), -1)
    norms = np.sum(flat*flat, axis=1)
    pixels = sorted({c.contact_ids for c in cells})
    matchings = [(a, b) for a, b in itertools.combinations(pixels, 2) if a[0] != b[0] and a[1] != b[1]]
    blocks = []
    for number, (first, second) in enumerate(matchings, 1):
        left = np.asarray([i for i, c in enumerate(cells) if c.contact_ids == first], dtype=np.int32)
        right = np.asarray([i for i, c in enumerate(cells) if c.contact_ids == second], dtype=np.int32)
        blocks.append(DenseBlock(f'matching-{number}', (first, second), left, right, flat[left]@flat[right].T))
    return DenseBank(single, cells, waves, norms, tuple(blocks),
        {'center_templates_seconds': template_seconds,
         'gram_matrices_seconds': time.perf_counter()-started-template_seconds,
         'total_seconds': time.perf_counter()-started})


def fit_two_dense(waveform, bank):
    """Waveform-only API. Return compact alternatives and lossless coarse arrays."""
    started = time.perf_counter()
    waveform = np.asarray(waveform, dtype=float)
    if waveform.shape != (34, len(N.R.FIT_GRID_NS)) or not np.isfinite(waveform).all():
        raise ValueError('Finite signed34 waveform on FIT_GRID_NS required')
    if not np.any(waveform):
        return {'status': 'unsupported', 'reason': 'zero_observed_waveform', 'refined_hypotheses': []}, {}
    flat = bank.center_waves.reshape(len(bank.cells), -1)
    rhs = flat@waveform.ravel()
    observed_norm = float(np.sum(waveform*waveform))
    arrays = {}
    scores = []
    for block in bank.blocks:
        left, right = block.left_indices, block.right_indices
        x, y, sse, active = P.nnls2(bank.norms[left, None], block.cross_gram, bank.norms[right],
                                  rhs[left, None], rhs[right], observed_norm)
        cost = sse/waveform.size
        prefix = block.matching_id.replace('-', '_')
        arrays[prefix+'_cost_mean_square_keV2'] = cost
        arrays[prefix+'_energy_first_keV'] = x
        arrays[prefix+'_energy_second_keV'] = y
        arrays[prefix+'_energy_active_set'] = np.asarray(active, dtype=np.uint8)
        arrays[prefix+'_left_cell_indices'] = left
        arrays[prefix+'_right_cell_indices'] = right
        scores.append(cost)
    coarse_seconds = time.perf_counter()-started
    chosen = []
    for matching_index, (block, score) in enumerate(zip(bank.blocks, scores)):
        flat_score = score.ravel()
        # Stable order agrees with the old (score,matching,cellids) dictionary
        # sort; full scores remain arrays instead of millions of dictionaries.
        selected = np.argsort(flat_score, kind='stable')[:P.TOP_K_PER_MATCHING]
        for matching_rank, index in enumerate(selected, 1):
            i, j = np.unravel_index(int(index), score.shape)
            value = float(flat_score[index])
            rank = 1+sum(int(np.count_nonzero(s < value)) for s in scores)
            rank += sum(int(np.count_nonzero(s == value)) for s in scores[:matching_index])
            rank += int(np.count_nonzero(flat_score[:index] == value))
            chosen.append({'matching_id': block.matching_id,
                'cell_indices': [int(block.left_indices[i]), int(block.right_indices[j])],
                'global_rank': rank, 'matching_rank': matching_rank})
    ranking_seconds = time.perf_counter()-started-coarse_seconds
    refinements = [P._refine(waveform, bank, row) for row in chosen]
    refinements.sort(key=lambda h: (h['cost_mean_square_keV2'], h['matching_id'], [s['cell_id'] for s in h['sites']]))
    summaries = []
    for block, score in zip(bank.blocks, scores):
        refined = [r for r in refinements if r['matching_id'] == block.matching_id]
        summaries.append({'matching_id': block.matching_id, 'contact_ids': [list(p) for p in block.contact_ids],
            'coarse_shape': list(score.shape), 'coarse_count': int(score.size), 'refined_count': len(refined),
            'coarse_best_cost_mean_square_keV2': float(score.min()),
            'refined_best_cost_mean_square_keV2': refined[0]['cost_mean_square_keV2'],
            'refined_best_optimizer_status': refined[0]['optimizer_status']})
    elapsed = time.perf_counter()-started
    return {'status': 'fitted', 'reason': None, 'matchings': summaries,
        'refined_hypotheses': refinements, 'top_k_per_matching': P.TOP_K_PER_MATCHING,
        'coarse_hypothesis_count': sum(int(s.size) for s in scores),
        'new_basis_evaluations': sum(h['new_basis_evaluations'] for h in refinements),
        'timing_seconds': {'coarse_energy_profile': coarse_seconds, 'ranking': ranking_seconds,
            'refinement': elapsed-coarse_seconds-ranking_seconds, 'total': elapsed}}, arrays
