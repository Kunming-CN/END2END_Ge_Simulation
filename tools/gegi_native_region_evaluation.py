"""Dense-search parity and one saved720929 application to the region bank."""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import sys
import time

import numpy as np

import gegi_native_region_inverse as D
import gegi_native_applicability as A

N = D.N
ROOT = N.ROOT
OLD_BANK = '.local/gegi-10m/signal-recovery-v1/calibration/native-cell-bank'
PAIR = '.local/gegi-10m/signal-recovery-v1/validation/native-inverse-pair/result.json'
PAIR_SHA = 'aeb714087bd816e59d04b540e9ff98c5f44823384ecfe46d7ffc9fb393acc903'
APP = '.local/gegi-10m/signal-recovery-v1/validation/native-inverse-applicability'
APP_SHA = 'a019a603b00c4656c4365825f01ff896f839c304877d67274a942373b9ef81d3'


def source_bindings():
    prior = N._checked(ROOT/PAIR, PAIR_SHA)
    bindings = dict(prior['source_sha256'])
    bindings.update({ref: N.L.W.sha(ROOT/ref) for ref in (
        'tools/gegi_native_region_inverse.py', 'tools/gegi_native_region_evaluation.py',
        'tools/gegi_native_applicability.py', 'tools/gegi_event_store.py', 'tools/gegi_imaging.py')})
    for ref, digest in prior['source_sha256'].items():
        if N.L.W.sha(ROOT/ref) != digest:
            raise ValueError('Completed inverse source changed: '+ref)
    return bindings


def _freeze_check(sources):
    if any(N.L.W.sha(ROOT/ref) != digest for ref, digest in sources.items()):
        raise ValueError('Dense evaluation source changed; preserve completed evidence')


def _store_arrays(path, arrays):
    started = time.perf_counter()
    np.savez_compressed(path, **arrays)
    with np.load(path) as saved:
        if set(saved.files) != set(arrays) or any(not np.array_equal(saved[key], value) for key, value in arrays.items()):
            raise ValueError('Lossless dense arrays failed exact reload')
    return {'ref': path.relative_to(ROOT).as_posix(), 'sha256': N.L.W.sha(path),
            'store_and_verify_seconds': time.perf_counter()-started, 'reload_exact': True,
            'arrays': {key: {'shape': list(value.shape), 'dtype': str(value.dtype)} for key, value in arrays.items()}}


def parity(output):
    started = time.perf_counter()
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    sources = source_bindings()
    original = N._checked(ROOT/PAIR, PAIR_SHA)
    single = N.load_bank(ROOT/OLD_BANK)
    bank = D.prepare_dense(single)
    request = N._checked(ROOT/OLD_BANK/'request.json', N.REQUEST_SHA256)
    targets = {t['reference_record_ref']: t for t in request['targets']}
    rows = []
    saved_arrays = {}
    for record in original['records']:
        waves = []
        for ref in record['source_record_refs']:
            target = targets[ref]
            payload = N._checked(ROOT/target['source_record']['ref'], target['source_record']['sha256'])['payload']
            wave, support = N.L.waveform(payload)
            if wave is None:
                raise ValueError('Frozen parity wave unavailable: '+str(support))
            waves.append(wave)
        waveform = .5*(waves[0]+waves[1])
        fitted, arrays = D.fit_two_dense(waveform, bank)
        cost_delta = energy_delta = 0.
        for old in record['fit']['coarse_hypotheses']:
            block = next(b for b in bank.blocks if b.matching_id == old['matching_id'])
            left_id, right_id = old['cell_ids']
            left = next(i for i, index in enumerate(block.left_indices) if bank.cells[index].cell_id == left_id)
            right = next(j for j, index in enumerate(block.right_indices) if bank.cells[index].cell_id == right_id)
            prefix = block.matching_id.replace('-', '_')
            cost_delta = max(cost_delta, abs(float(arrays[prefix+'_cost_mean_square_keV2'][left, right])-old['cost_mean_square_keV2']))
            energy_delta = max(energy_delta,
                abs(float(arrays[prefix+'_energy_first_keV'][left, right])-old['energy_keV'][0]),
                abs(float(arrays[prefix+'_energy_second_keV'][left, right])-old['energy_keV'][1]))
        old_best = record['fit']['refined_hypotheses'][0]
        new_best = fitted['refined_hypotheses'][0]
        best_delta = abs(old_best['cost_mean_square_keV2']-new_best['cost_mean_square_keV2'])
        if (cost_delta > 1e-8 or energy_delta > 1e-7 or best_delta > 1e-10
                or old_best['matching_id'] != new_best['matching_id']):
            raise AssertionError('Dense/old fixed-budget pairing parity failed')
        rows.append({'mixture_index': record['mixture_index'], 'coarse_count': fitted['coarse_hypothesis_count'],
            'max_coarse_cost_difference_keV2': cost_delta, 'max_coarse_energy_difference_keV': energy_delta,
            'best_refined_cost_difference_keV2': best_delta, 'best_matching': new_best['matching_id'],
            'matching_identical': True, 'fit_timing_seconds': fitted['timing_seconds']})
        saved_arrays.update({f'case_{record["mixture_index"]}_'+key: value for key, value in arrays.items()})
    evidence = _store_arrays(output/'coarse-parity.npz', saved_arrays)
    _freeze_check(sources)
    result = {'kind': 'gegi_dense_pairing_old80_parity_v1', 'status': 'passed',
        'source_sha256': sources, 'input_sha256': {**single.input_sha256, PAIR: PAIR_SHA},
        'records': rows, 'array_evidence': evidence, 'elapsed_seconds': time.perf_counter()-started,
        'new_fit_calls': 8, 'new_native_calls': 0,
        'scope': 'Implementation parity on exactly8saved mixtures, all800coarse scores/energies and fixedK8/8step refinements. Previous results retained; no recalibration or physics.'}
    A._write(output/'result.json', result)
    return result


def region_domain(truth, single):
    rows = []
    for site in truth:
        point = np.asarray(site['deposition_centroid_mm'])
        geometric = [c for c in single.cells if list(c.contact_ids) == site['cell']
                     and np.all(point >= c.lower_mm) and np.all(point <= c.upper_mm)]
        rows.append({'contact_ids': site['cell'], 'centroid_mm': point.tolist(),
            'geometric_covering_cells': [{'cell_id': c.cell_id, 'unsupported_reason': c.unsupported_reason} for c in geometric],
            'supported_covering_cells': [c.cell_id for c in geometric if c.unsupported_reason is None]})
    return rows


def event(directory, request_sha, complete_sha, parity_ref, output, max_seconds, pause_before_fit=False, resume_loader=False):
    started = time.perf_counter()
    output = Path(output).resolve()
    if output.exists() and not resume_loader:
        raise FileExistsError(output)
    if not resume_loader:
        output.mkdir(parents=True)
    else:
        failure = json.loads((output/'failure.json').read_bytes())
        if failure['new_fit_calls'] != 0 or (output/'fit.json').exists() or (output/'result.json').exists():
            raise ValueError('Concrete loader repair requires no prior event fit')
    sources = source_bindings()
    parity_path = Path(parity_ref).resolve()/'result.json'
    parity_raw = parity_path.read_bytes()
    parity_result = json.loads(parity_raw)
    parity_reuse = None
    if parity_result['status'] != 'passed':
        raise ValueError('Completed old80 dense parity required')
    if parity_result['source_sha256'] != sources:
        if not resume_loader:
            raise ValueError('Completed source-identical old80 dense parity required')
        changed = {ref for ref in sources if parity_result['source_sha256'].get(ref) != sources[ref]}
        allowed = {'tools/gegi_native_region_inverse.py', 'tools/gegi_native_region_evaluation.py'}
        if not changed <= allowed:
            raise ValueError('Loader repair changed previously checked prediction/optimizer sources')
        # Reuse the completed8-fit parity after this admission-only correction.
        # Preserve its entire source bytes and prove the actual search/parity
        # functions unchanged instead of repeating the fits for a loader fix.
        for ref, saved_name, functions in (
            ('tools/gegi_native_region_inverse.py', 'failed-loader-source.py', ('prepare_dense', 'fit_two_dense')),
            ('tools/gegi_native_region_evaluation.py', 'failed-evaluator-source.py', ('parity',))):
            saved = output/saved_name
            if N.L.W.sha(saved) != parity_result['source_sha256'][ref]:
                raise ValueError('Prior parity source evidence differs')
            old_text, new_text = saved.read_text(), (ROOT/ref).read_text()
            old_functions = {n.name: ast.get_source_segment(old_text, n) for n in ast.parse(old_text).body if isinstance(n, ast.FunctionDef)}
            new_functions = {n.name: ast.get_source_segment(new_text, n) for n in ast.parse(new_text).body if isinstance(n, ast.FunctionDef)}
            if any(old_functions[name] != new_functions[name] for name in functions):
                raise ValueError('Checked dense search/parity function changed')
        parity_reuse = {'scope': 'Import-admission-only repair; search/optimizer/parity functions exact and unchanged.',
                        'prior_sources_preserved': True, 'repeated_parity_fit_calls': 0}
    single = D.load_region(directory, request_sha, complete_sha)
    bank = D.prepare_dense(single)
    if len(bank.blocks) != 2:
        raise ValueError('Region does not support both expected X/Y matchings')
    previous = N._checked(ROOT/APP/'result.json', APP_SHA)
    old = next(r for r in previous['records'] if r['campaign_initial_id'] == 720929)
    identity = old['identity']
    store_ref = next(ref for ref in previous['input_sha256'] if ref.endswith('b000002/events.sqlite'))
    store_sha = previous['input_sha256'][store_ref]
    if N.L.W.sha(ROOT/store_ref) != store_sha:
        raise ValueError('Original DONE-bound native arrays changed')
    raw_event, native, metadata_sha = N.R.read_saved_group(ROOT/store_ref, identity['raw_primary_id'], 0)
    if metadata_sha != identity['metadata_sha256']:
        raise ValueError('Original development group metadata changed')
    waveform, support = N.L.waveform({'channel_signals': [{'contact_id': cid, **native[cid]} for cid in N.R.ALL34_IDS],
        'signal_coverage': N.R.ALL34_COVERAGE, 'status': raw_event['status'], 'valid': raw_event['status'] == 'completed'})
    if waveform is None:
        raise ValueError('Original development waveform unsupported: '+str(support))
    old_arrays = ROOT/previous['waveform_evidence']['ref']
    if N.L.W.sha(old_arrays) != previous['waveform_evidence']['sha256']:
        raise ValueError('Prior exact waveform evidence changed')
    with np.load(old_arrays) as original_arrays:
        if not np.array_equal(waveform, original_arrays['group_720929_observed']):
            raise ValueError('Observed group timing/units/interpolation changed')
    inputs = {**single.input_sha256, APP+'/result.json': APP_SHA, store_ref: store_sha,
        previous['waveform_evidence']['ref']: previous['waveform_evidence']['sha256'],
        parity_path.relative_to(ROOT).as_posix(): N.R._sha(parity_raw)}
    counts = [{'matching_id': b.matching_id, 'left_cells': len(b.left_indices), 'right_cells': len(b.right_indices),
               'coarse_pairs': int(len(b.left_indices)*len(b.right_indices))} for b in bank.blocks]
    A._write(output/'startup.json', {'source_sha256': sources, 'input_sha256': inputs,
        'campaign_initial_id': 720929, 'metadata_sha256': metadata_sha, 'max_seconds': max_seconds,
        'coverage': single.coverage, 'coarse_counts': counts, 'bank_load_seconds': single.load_seconds,
        'preparation_seconds': bank.preparation_seconds, 'observed_waveform_shape': list(waveform.shape),
        'observed_waveform_raw_sha256': N.R._sha(waveform.tobytes()),
        'fit_api': 'fit_two_dense(waveform, bank)', 'time_convention': raw_event['time_convention'],
        'parity_reuse_after_loader_repair': parity_reuse})
    if pause_before_fit:
        print(json.dumps({'stage': 'region_prepared_before_fit', 'supported_cells': single.coverage['supported_cells'],
            'unsupported_cells': single.coverage['unsupported_cells'], 'unsupported_reasons': single.coverage['unsupported_reasons'],
            'coarse_counts': counts, 'load_seconds': single.load_seconds, 'preparation_seconds': bank.preparation_seconds}), flush=True)
        # Keep the one admitted in-memory bank alive while the supervisor reports
        # its actual support counts. This is no user approval or repeated load.
        if sys.stdin.readline().strip() != 'continue':
            raise RuntimeError('Prepared region fit was not continued')
    if time.perf_counter()-started > max_seconds:
        raise TimeoutError('Region load/preparation exhausted budget before the one authorized fit')
    # One actual group fit, with no truth/position/energy/source or time alignment.
    fitted, arrays = D.fit_two_dense(waveform, bank)
    A._write(output/'fit.json', {'source_sha256': sources, 'input_sha256': inputs,
        'campaign_initial_id': 720929, 'fit': fitted})
    arrays['fit_grid_ns'] = N.R.FIT_GRID_NS
    arrays['observed_signed_keV'] = waveform
    arrays['cell_ids'] = np.asarray([c.cell_id for c in bank.cells])
    arrays['cell_contact_ids'] = np.asarray([c.contact_ids for c in bank.cells], dtype=np.int32)
    matching_residuals = {}
    for block in bank.blocks:
        hypothesis = next(h for h in fitted['refined_hypotheses'] if h['matching_id'] == block.matching_id)
        predicted = A.prediction(hypothesis, bank)
        prefix = block.matching_id.replace('-', '_')
        arrays[prefix+'_best_prediction_signed_keV'] = predicted
        arrays[prefix+'_best_residual_signed_keV'] = predicted-waveform
        matching_residuals[block.matching_id] = A.metrics(predicted-waveform)
    evidence = _store_arrays(output/'coarse-and-waveforms.npz', arrays)
    # Saved independent truth is used only after the full dense search and arrays
    # are complete. It never defines coverage or excludes a fit hypothesis.
    truth = old['posthoc']['truth_cells']
    best = fitted['refined_hypotheses'][0]
    errors = A.partial_assignment(best['sites'], truth)
    exact_support = {tuple(s['contact_ids']) for s in best['sites']} == {tuple(t['cell']) for t in truth}
    domain = region_domain(truth, single)
    _freeze_check(sources)
    elapsed = time.perf_counter()-started
    result = {'kind': 'gegi_saved_region_720929_dense_pairing_v1',
        'status': 'completed' if elapsed <= max_seconds else 'completed_over_budget',
        'source_sha256': sources, 'input_sha256': inputs, 'coverage': single.coverage,
        'campaign_initial_id': 720929, 'identity': identity, 'metadata_sha256_verified': metadata_sha,
        'fit': fitted, 'matching_residuals': matching_residuals,
        'posthoc': {'truth_cells': truth, 'matching_correct': exact_support, 'missing_true_pixel_pairs':
            [t['cell'] for t in truth if tuple(t['cell']) not in {c.contact_ids for c in bank.cells}],
            'centroid_coverage': domain, 'closest_assignment_errors': errors,
            'total_energy_error_keV': sum(s['energy_keV'] for s in best['sites'])-sum(t['energy_keV'] for t in truth),
            'site_boundary_hits': [s['boundary_axes'] for s in best['sites']],
            'photon_vertex_recovery_established': False, 'false_splitting_established': False},
        'previous_sparse_fit': {'result_sha256': APP_SHA, 'best_rms_keV': old['fit']['refined_hypotheses'][0]['rms_keV'],
            'closest_assignment_errors': old['posthoc']['closest_partial_assignment'],
            'same_observed_waveform_exact': True},
        'array_evidence': evidence, 'coarse_counts': counts,
        'timing_seconds': {'bank_load': single.load_seconds, 'preparation': bank.preparation_seconds,
            'search': fitted['timing_seconds'], 'store_and_verify': evidence['store_and_verify_seconds'], 'total': elapsed},
        'new_fit_calls': 1, 'new_native_calls': 0, 'new_field_solves': 0, 'new_transport_calls': 0,
        'parity_reuse_after_loader_repair': parity_reuse,
        'definitions': {'observed': 'Exact original native signed34 group aggregate, original relative deposit timing, existing0..250ns2ns grid and fixed500keV bank gain. No truth alignment or gain fitting.',
            'cells': 'Geometry-defined region. Every8-corner tensor cell with incomplete/canonical-invalid records, mixed collector identities or carrier-order flips remains explicitly unsupported.',
            'search': 'All supported cell cross-products in both matchings, exact two-energy NNLS; all coarse Float64 scores/energies stored losslessly. Same top8 per matching and8coordinate steps through the unchanged frozen optimizer.',
            'limits': 'Ideal-charge development diagnostic only; no hardware observable/noise/efficiency claim, no continuous global-optimum certificate, no false-splitting validation, and charge-cell centroids are not photon vertices.'}}
    A._write(output/'result.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('parity', 'event'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--region', type=Path)
    parser.add_argument('--request-sha256')
    parser.add_argument('--complete-sha256')
    parser.add_argument('--parity', type=Path)
    parser.add_argument('--max-seconds', type=float, default=120.)
    parser.add_argument('--pause-before-fit', action='store_true')
    parser.add_argument('--resume-loader', action='store_true')
    args = parser.parse_args()
    if args.mode == 'parity':
        result = parity(args.output)
    else:
        if not all((args.region, args.request_sha256, args.complete_sha256, args.parity)) or not 0 < args.max_seconds <= 120:
            raise ValueError('Event mode requires sealed region, parity receipt and positive<=120s budget')
        result = event(args.region, args.request_sha256, args.complete_sha256, args.parity, args.output, args.max_seconds, args.pause_before_fit, args.resume_loader)
    print(json.dumps({'status': result['status'], 'sha256': N.L.W.sha(args.output/'result.json'),
        'elapsed_seconds': result.get('elapsed_seconds', result.get('timing_seconds', {}).get('total')),
        'new_fit_calls': result['new_fit_calls']}, sort_keys=True))
