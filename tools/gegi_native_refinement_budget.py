"""Continue the saved720929 optimization with a fixed1024-pair budget per matching."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import numpy as np

import gegi_native_region_inverse as D
import gegi_native_applicability as A

N = D.N
P = D.P
ROOT = N.ROOT
REGION = '.local/gegi-10m/signal-recovery-v1/calibration/native-region-bank'
REGION_REQUEST = 'c171684efb416b618a00c761fbd06058b6438c194c93b9c282ac7444c143b0a5'
REGION_COMPLETE = '2a6f723eb9c93a92e4029bbc7112c15bae7c05e80e9109ddd6c6bdbebdf3fab1'
ORIGINAL = '.local/gegi-10m/signal-recovery-v1/validation/native-region-720929/result.json'
ORIGINAL_SHA = '02716a816be3c70cfb0bf27fcf9a5f3dc81d6efe93841a841542e3418837e0ac'
K = 1024
NEW_REFINEMENT_CAP = 2032
MAX_SECONDS = 120.


class CenterTemplates:
    """Only the unchanged optimizer's needed center waveforms; no Gram matrix."""
    def __init__(self, cells):
        self.cells = cells
        self.values = {}

    def __getitem__(self, index):
        if index not in self.values:
            cell = self.cells[index]
            self.values[index] = N.unit_prediction(cell, np.full(len(cell.active_axes), .5))
        return self.values[index]


def run(output, resume_admission=False):
    started = time.perf_counter()
    output = Path(output).resolve()
    if output.exists() and not resume_admission:
        raise FileExistsError('Preserve prior optimization continuation: '+str(output))
    if not resume_admission:
        output.mkdir(parents=True)
    else:
        failure = json.loads((output/'failure.json').read_bytes())
        if failure['new_refinements'] != 0 or (output/'refinements.jsonl').exists() or (output/'result.json').exists():
            raise ValueError('Count repair requires the preserved pre-refinement admission failure')
        if N.L.W.sha(output/'failed-source.py') != failure['source_sha256']:
            raise ValueError('Preserved failed admission source differs')
    lock = threading.Lock()
    state = {'stage': 'admission', 'new_refinements': 0, 'reused_refinements': 0,
             'completed_by_matching': {}, 'best_by_matching': {}}
    def hard_stop():
        # The normal loop reserves four seconds for finalization. This guard
        # still retains the last flushed candidate and best if admission or I/O
        # unexpectedly consumes the whole bound. It never restarts the worker.
        with lock:
            receipt = {**state, 'status': 'hard_budget_stop', 'elapsed_seconds': time.perf_counter()-started}
            A._write(output/'PARTIAL.json', receipt)
        os._exit(124)
    watchdog = threading.Timer(MAX_SECONDS-.5, hard_stop)
    watchdog.daemon = True
    watchdog.start()
    try:
        original = N._checked(ROOT/ORIGINAL, ORIGINAL_SHA)
        sources = dict(original['source_sha256'])
        for ref, digest in sources.items():
            if N.L.W.sha(ROOT/ref) != digest:
                raise ValueError('Completed predictor/optimizer source changed: '+ref)
        sources['tools/gegi_native_refinement_budget.py'] = N.L.W.sha(Path(__file__))
        evidence_ref = original['array_evidence']['ref']
        evidence_sha = original['array_evidence']['sha256']
        if N.L.W.sha(ROOT/evidence_ref) != evidence_sha:
            raise ValueError('Saved complete coarse arrays changed')
        with np.load(ROOT/evidence_ref) as arrays:
            waveform = arrays['observed_signed_keV']
            cell_ids = arrays['cell_ids'].tolist()
            scores = [arrays[f'matching_{i}_cost_mean_square_keV2'] for i in (1, 2)]
            left = [arrays[f'matching_{i}_left_cell_indices'] for i in (1, 2)]
            right = [arrays[f'matching_{i}_right_cell_indices'] for i in (1, 2)]
        single = D.load_region(ROOT/REGION, REGION_REQUEST, REGION_COMPLETE)
        if any(original['input_sha256'].get(ref) != digest for ref, digest in single.input_sha256.items()):
            raise ValueError('Region input pins differ from the completed K8 fit')
        cells = tuple(sorted((c for c in single.cells if c.unsupported_reason is None), key=lambda c: c.cell_id))
        if [c.cell_id for c in cells] != cell_ids:
            raise ValueError('Saved coarse cell-index mapping changed')
        bank = SimpleNamespace(cells=cells, center_waves=CenterTemplates(cells))
        imported = original['fit']['refined_hypotheses']
        if len(imported) != 16:
            raise ValueError('Exactly16 completed K8 refinements required')
        imported_pairs = {(h['matching_id'], tuple(s['cell_id'] for s in h['sites'])) for h in imported}
        # One numerical reuse check; prediction and cost evaluation only, no fit.
        old_best = imported[0]
        predicted = A.prediction(old_best, bank)
        reused_cost = float(np.mean((predicted-waveform)**2))
        reuse_difference = abs(reused_cost-old_best['cost_mean_square_keV2'])
        if reuse_difference > 1e-9:
            raise ValueError('Imported best-refinement objective did not reproduce')
        rank_started = time.perf_counter()
        combined = np.concatenate([score.ravel() for score in scores])
        global_order = np.argsort(combined, kind='stable')
        global_ranks = np.empty(len(combined), dtype=np.int32)
        global_ranks[global_order] = np.arange(1, len(combined)+1, dtype=np.int32)
        offsets = [0, scores[0].size]
        candidates = []
        for m, score in enumerate(scores):
            selected = np.argsort(score.ravel(), kind='stable')[:K]
            for matching_rank, index in enumerate(selected, 1):
                i, j = np.unravel_index(int(index), score.shape)
                indices = [int(left[m][i]), int(right[m][j])]
                ids = tuple(cells[k].cell_id for k in indices)
                if (f'matching-{m+1}', ids) not in imported_pairs:
                    candidates.append({'matching_id': f'matching-{m+1}', 'cell_indices': indices,
                        'global_rank': int(global_ranks[offsets[m]+index]), 'matching_rank': matching_rank})
        if len(candidates) != 2*K-len(imported):
            raise ValueError('Fixed matching budget/import accounting differs')
        # Interleave the two fixed coarse rankings so a partial run reports
        # balanced actual search coverage, without using event truth.
        candidates.sort(key=lambda row: (row['matching_rank'], row['matching_id']))
        planned_new_candidates = len(candidates)
        candidates = candidates[:NEW_REFINEMENT_CAP]
        ranking_seconds = time.perf_counter()-rank_started
        inputs = {**single.input_sha256, ORIGINAL: ORIGINAL_SHA, evidence_ref: evidence_sha}
        A._write(output/'startup.json', {'kind': 'gegi_saved_720929_fixed_refinement_budget_v1',
            'source_sha256': sources, 'input_sha256': inputs, 'campaign_initial_id': 720929,
            'budget_per_matching': K, 'max_total_worker_seconds': MAX_SECONDS,
            'coarse_pairs_reused': sum(int(s.size) for s in scores),
            'imported_refinements': 16, 'selected_new_candidates': planned_new_candidates,
            'new_refinement_cap': NEW_REFINEMENT_CAP, 'scheduled_new_refinements': len(candidates),
            'reuse_check': {'prediction_cost_difference_keV2': reuse_difference, 'refit_calls': 0},
            'bank_load_seconds': single.load_seconds, 'ranking_seconds': ranking_seconds,
            'scope': 'Optimization budget correction using the development observation, not new physical validation.'})
        all_refinements = list(imported)
        state.update(stage='refining', reused_refinements=16,
                     completed_by_matching={f'matching-{m}': 8 for m in (1, 2)},
                     best_by_matching={f'matching-{m}': next(h for h in imported if h['matching_id'] == f'matching-{m}') for m in (1, 2)})
        optimization_started = time.perf_counter()
        new_times = []
        status = 'completed' if len(candidates) == planned_new_candidates else 'completed_refinement_cap'
        with (output/'refinements.jsonl').open('x', encoding='utf-8', newline='\n') as ledger:
            for hypothesis in imported:
                ledger.write(json.dumps({'origin': 'reused_pinned_K8', 'hypothesis': hypothesis,
                    'refinement_seconds': None}, sort_keys=True, separators=(',', ':'), allow_nan=False)+'\n')
            ledger.flush()
            for number, candidate in enumerate(candidates, 1):
                if time.perf_counter()-started >= MAX_SECONDS-4.:
                    status = 'partial_budget_stop'
                    break
                tick = time.perf_counter()
                hypothesis = P._refine(waveform, bank, candidate)
                elapsed = time.perf_counter()-tick
                new_times.append(elapsed)
                entry = {'origin': 'new_fixed1024_budget', 'hypothesis': hypothesis,
                         'refinement_seconds': elapsed}
                with lock:
                    ledger.write(json.dumps(entry, sort_keys=True, separators=(',', ':'), allow_nan=False)+'\n')
                    ledger.flush()
                    all_refinements.append(hypothesis)
                    state['new_refinements'] = number
                    key = hypothesis['matching_id']
                    state['completed_by_matching'][key] += 1
                    if hypothesis['cost_mean_square_keV2'] < state['best_by_matching'][key]['cost_mean_square_keV2']:
                        state['best_by_matching'][key] = hypothesis
                if number % 256 == 0:
                    print(json.dumps({'stage': 'refining', 'new_refinements': number,
                        'elapsed_seconds': time.perf_counter()-started,
                        'best_rms_keV': min(h['rms_keV'] for h in state['best_by_matching'].values())}), flush=True)
        optimization_seconds = time.perf_counter()-optimization_started
        all_refinements.sort(key=lambda h: (h['cost_mean_square_keV2'], h['matching_id'], [s['cell_id'] for s in h['sites']]))
        best = all_refinements[0]
        bests = [next(h for h in all_refinements if h['matching_id'] == f'matching-{m}') for m in (1, 2)]
        waveform_arrays = {'fit_grid_ns': N.R.FIT_GRID_NS, 'observed_signed_keV': waveform}
        matching_metrics = {}
        for hypothesis in bests:
            predicted = A.prediction(hypothesis, bank)
            key = hypothesis['matching_id']
            waveform_arrays[key+'_best_prediction_signed_keV'] = predicted
            waveform_arrays[key+'_best_residual_signed_keV'] = predicted-waveform
            matching_metrics[key] = A.metrics(predicted-waveform)
        store_started = time.perf_counter()
        wave_path = output/'best-waveforms.npz'
        np.savez_compressed(wave_path, **waveform_arrays)
        with np.load(wave_path) as saved:
            if any(not np.array_equal(saved[key], value) for key, value in waveform_arrays.items()):
                raise ValueError('Best waveform evidence did not reload exactly')
        # Truth is posthoc only, after the fixed candidate schedule has stopped.
        truth = original['posthoc']['truth_cells']
        errors = A.partial_assignment(best['sites'], truth)
        centroid_ids = tuple(row['supported_covering_cells'][0] for row in original['posthoc']['centroid_coverage'])
        centroid_refined = any(tuple(s['cell_id'] for s in h['sites']) == centroid_ids for h in all_refinements)
        if any(N.L.W.sha(ROOT/ref) != digest for ref, digest in sources.items()):
            raise ValueError('Frozen refinement source changed; ledger preserved')
        result = {'kind': 'gegi_saved_720929_fixed_refinement_budget_v1', 'status': status,
            'source_sha256': sources, 'input_sha256': inputs, 'campaign_initial_id': 720929,
            'budget_per_matching': K, 'coarse_pairs_reused': sum(int(s.size) for s in scores),
            'reused_refinements': 16, 'new_refinements': len(new_times), 'completed_refinements': len(all_refinements),
            'selected_new_candidates': planned_new_candidates, 'new_refinement_cap': NEW_REFINEMENT_CAP,
            'selected_candidates_not_refined': planned_new_candidates-len(new_times),
            'completed_by_matching': state['completed_by_matching'], 'best_by_matching': bests,
            'best': best, 'matching_residuals': matching_metrics,
            'posthoc': {'truth_cells': truth, 'matching_correct': {tuple(s['contact_ids']) for s in best['sites']} == {tuple(t['cell']) for t in truth},
                'closest_assignment_errors': errors, 'centroid_cell_pair_refined': centroid_refined,
                'centroid_cell_ids': centroid_ids, 'site_boundary_hits': [s['boundary_axes'] for s in best['sites']],
                'total_energy_error_keV': sum(s['energy_keV'] for s in best['sites'])-sum(t['energy_keV'] for t in truth),
                'false_splitting_established': False, 'photon_vertex_recovery_established': False},
            'comparison_K8': {'best_cost_mean_square_keV2': old_best['cost_mean_square_keV2'],
                'best_rms_keV': old_best['rms_keV'], 'new_minus_K8_cost_keV2': best['cost_mean_square_keV2']-old_best['cost_mean_square_keV2'],
                'prediction_cost_reuse_difference_keV2': reuse_difference},
            'actual_coverage': {'candidate_cells': single.coverage['candidate_cells'],
                'supported_cells': single.coverage['supported_cells'], 'unsupported_cells': single.coverage['unsupported_cells'],
                'unsupported_reasons': single.coverage['unsupported_reasons'],
                'completed_matching_rank_max': {f'matching-{m}': max(h['coarse_matching_rank'] for h in all_refinements if h['matching_id'] == f'matching-{m}') for m in (1, 2)}},
            'evidence': {'refinement_ledger_ref': (output/'refinements.jsonl').relative_to(ROOT).as_posix(),
                'refinement_ledger_sha256': N.L.W.sha(output/'refinements.jsonl'),
                'best_waveforms_ref': wave_path.relative_to(ROOT).as_posix(), 'best_waveforms_sha256': N.L.W.sha(wave_path),
                'waveforms_reload_exact': True, 'all_coarse_arrays_reused_ref': evidence_ref},
            'timing_seconds': {'bank_load': single.load_seconds, 'saved_ranking': ranking_seconds,
                'optimization_and_checkpoint': optimization_seconds, 'new_refinement': N.L.describe(new_times),
                'store_and_verify': time.perf_counter()-store_started, 'total': time.perf_counter()-started},
            'lazy_center_template_count': len(bank.center_waves.values),
            'new_optimization_continuations': 1, 'new_native_calls': 0, 'new_field_solves': 0, 'new_transport_calls': 0,
            'definitions': {'selection': 'Fixed top1024 per matching from saved center cost and stable cell order; interleaved matching ranks. No true cell, position, energy, source or time alignment enters selection/refinement.',
                'optimizer': 'Unchanged P._refine, exact two-energy NNLS, N.unit_prediction and8coordinate steps. All16completed refinements retained; no Gram recomputation or repeated parity fits.',
                'interpretation': 'Development-driven optimization-budget correction only. Charge-cell centroid errors are posthoc, not photon-vertex or hardware precision/efficiency validation. No false-splitting claim.'}}
        A._write(output/'result.json', result)
        return result
    finally:
        watchdog.cancel()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--resume-admission', action='store_true')
    args = parser.parse_args()
    result = run(args.output, args.resume_admission)
    print(json.dumps({'status': result['status'], 'new_refinements': result['new_refinements'],
        'completed_refinements': result['completed_refinements'], 'best_rms_keV': result['best']['rms_keV'],
        'elapsed_seconds': result['timing_seconds']['total']}, sort_keys=True))
