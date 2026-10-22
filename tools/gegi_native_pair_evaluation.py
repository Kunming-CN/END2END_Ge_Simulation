"""Eight fixed saved-waveform prompt mixtures; two-site fit receives only their sum."""
from __future__ import annotations

import argparse
from collections import Counter
import itertools
import json
from pathlib import Path
import platform
import time

import numpy as np

import gegi_native_pair_inverse as P

N = P.N
ROOT = N.ROOT
SUPPORTS = (((11, 24), (12, 26)), ((11, 26), (12, 24)))
FIXED_PAIRS = (((1, 1), (4, 5)), ((4, 5), (1, 1)),
               ((2, 2), (3, 4)), ((1, 3), (4, 3)))
CASES = tuple((support, pair) for support in SUPPORTS for pair in FIXED_PAIRS)


def _write(path, value):
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, sort_keys=True, separators=(',', ':'), allow_nan=False)
        stream.write('\n')


def sources(bank):
    return {**bank.helper_sha256, **{ref: N.L.W.sha(ROOT/ref) for ref in
        ('tools/gegi_native_inverse.py', 'tools/gegi_native_pair_inverse.py',
         'tools/gegi_native_pair_evaluation.py')}}


def assignment_errors(sites, truth):
    choices = []
    for assignment in itertools.permutations(range(2)):
        errors = [np.asarray(s['position_mm'])-np.asarray(truth[t]['native_position_mm'])
                  for s, t in zip(sites, assignment)]
        choices.append((sum(float(e@e) for e in errors), assignment, errors))
    squared, assignment, errors = min(choices, key=lambda item: (item[0], item[1]))
    return {'truth_assignment': list(assignment), 'position_sum_square_mm2': squared,
        'site_errors': [{'fit_site': i, 'truth_site': t, 'position_error_mm': error.tolist(),
            'position_error_3d_mm': float(np.linalg.norm(error)),
            'energy_error_keV': sites[i]['energy_keV']-truth[t]['energy_keV'],
            'pixel_correct': sites[i]['contact_ids'] == truth[t]['contact_ids']}
            for i, (t, error) in enumerate(zip(assignment, errors))]}


def summarize(rows):
    fitted = [r for r in rows if r['status'] == 'evaluated']
    sites = [s for r in fitted for s in r['evaluation']['assignment_min_errors']['site_errors']]
    return {'total': len(rows), 'evaluated': len(fitted),
        'unsupported_reasons': dict(Counter(r['reason'] for r in rows if r['status'] != 'evaluated')),
        'matching_correct': sum(r['evaluation']['matching_correct'] for r in fitted),
        'matching_wrong': sum(not r['evaluation']['matching_correct'] for r in fitted),
        'true_cell_pairs_refined': sum(r['evaluation']['true_cell_pair_refined'] for r in fitted),
        'true_cell_coarse_global_rank': N.L.describe([r['evaluation']['true_cell_coarse_global_rank'] for r in fitted]),
        'true_cell_coarse_matching_rank': N.L.describe([r['evaluation']['true_cell_coarse_matching_rank'] for r in fitted]),
        'site_position_error_3d_mm': N.L.describe([s['position_error_3d_mm'] for s in sites]),
        'site_absolute_energy_error_keV': N.L.describe([abs(s['energy_error_keV']) for s in sites]),
        'site_absolute_position_errors_mm': {axis: N.L.describe([abs(s['position_error_mm'][i]) for s in sites])
                                             for i, axis in enumerate('XYZ')},
        'total_absolute_energy_error_keV': N.L.describe([abs(r['evaluation']['total_energy_error_keV']) for r in fitted]),
        'rms_keV': N.L.describe([r['fit']['refined_hypotheses'][0]['rms_keV'] for r in fitted]),
        'max_channel_rms_keV': N.L.describe([r['evaluation']['max_channel_rms_keV'] for r in fitted]),
        'max_absolute_residual_keV': N.L.describe([r['evaluation']['max_absolute_residual_keV'] for r in fitted]),
        'best_boundary_site_count': sum(bool(s['boundary_axes']) for r in fitted
                                        for s in r['fit']['refined_hypotheses'][0]['sites']),
        'optimizer_statuses': dict(Counter(r['fit']['refined_hypotheses'][0]['optimizer_status'] for r in fitted)),
        'energy_active_sets': dict(Counter(r['fit']['refined_hypotheses'][0]['energy_active_set'] for r in fitted)),
        'fit_seconds': N.L.describe([r['fit_seconds'] for r in fitted]),
        'new_basis_evaluations': sum(r['fit']['new_basis_evaluations'] for r in fitted)}


def evaluate(directory, output, indices, max_seconds, reuse=None):
    started = time.perf_counter()
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError('Preserve previous paired evaluation: '+str(output))
    output.mkdir(parents=True)
    single = N.load_bank(directory)
    bank = P.prepare_bank(single)
    source_sha = sources(single)
    if len(bank.pairs) != 800 or len(bank.matchings) != 2 or P.TOP_K_PER_MATCHING != 8:
        raise ValueError('Fixed800-pair/two-matching/K8 experiment required')
    if len(set(indices)) != len(indices) or any(i < 0 or i >= 8 for i in indices):
        raise ValueError('Unique fixed mixture indices0..7 required')
    request = N._checked(Path(directory)/'request.json', N.REQUEST_SHA256)
    targets = {t['reference_record_ref']: t for t in request['targets']}
    reuse_binding = None
    reused = {}
    if reuse:
        raw = (Path(reuse)/'result.json').read_bytes()
        prior = json.loads(raw)
        if (prior['status'] != 'completed' or prior['source_sha256'] != source_sha
                or prior['input_sha256'] != single.input_sha256):
            raise ValueError('Reuse requires completed source/input-identical paired results')
        reused = {r['mixture_index']: r for r in prior['records']}
        reuse_binding = {'ref': (Path(reuse)/'result.json').resolve().relative_to(ROOT).as_posix(),
                         'sha256': N.R._sha(raw)}
    _write(output/'startup.json', {'kind': 'gegi_fixed_prompt_two_site_saved_mixtures_v1',
        'source_sha256': source_sha, 'input_sha256': single.input_sha256,
        'native_producer_sha256_at_capture': single.native_producer_sha256,
        'coverage': single.coverage, 'mixture_indices': indices, 'max_seconds': max_seconds,
        'fixed_supports': SUPPORTS, 'fixed_pairs_xy_z_indices': FIXED_PAIRS,
        'mixing_weights': [.5, .5], 'time_offsets_ns': [0., 0.],
        'optimizer': {'coarse_cell_pairs': 800, 'top_k_per_matching': 8,
            'refinements': 16, 'starts': 'cell centers', 'coordinate_steps': N.STEPS,
            'energy': 'exact two-variable nonnegative least squares with unconstrained energies'},
        'reuse': reuse_binding, 'model': 'gpt-6.1-sol', 'reasoning_effort': 'ultra',
        'environment': {'python': platform.python_version(), 'numpy': np.__version__, 'platform': platform.platform()}})
    rows = []
    fits = 0
    status = 'completed'
    with (output/'records.jsonl').open('x', encoding='utf-8', newline='\n') as ledger:
        for index in indices:
            if time.perf_counter()-started > max_seconds:
                status = 'time_budget_exhausted'
                break
            if index in reused:
                record = reused[index]
            else:
                support, pair = CASES[index]
                refs = [f'validation/{pixel[0]}-{pixel[1]}/xy{point[0]}-z{point[1]}.json'
                        for pixel, point in zip(support, pair)]
                payloads = [N._checked(ROOT/targets[ref]['source_record']['ref'],
                                      targets[ref]['source_record']['sha256'])['payload'] for ref in refs]
                observed = [N.L.waveform(payload) for payload in payloads]
                record = {'mixture_index': index, 'source_record_refs': refs,
                    'source_record_sha256': [targets[ref]['source_record']['sha256'] for ref in refs],
                    'mixing_weights': [.5, .5], 'time_offsets_ns': [0., 0.]}
                if any(wave is None for wave, _ in observed):
                    record.update(status='unsupported', reason='mixture_source_unavailable',
                                  source_support=[support for _, support in observed])
                else:
                    waveform = .5*observed[0][0]+.5*observed[1][0]
                    fit_started = time.perf_counter()
                    # No case/support/source/position/cell/energy label is passed.
                    fitted = P.fit_two(waveform, bank)
                    fits += 1
                    record.update(fit=fitted, fit_seconds=time.perf_counter()-fit_started)
                    if fitted['status'] != 'fitted':
                        record.update(status='unsupported', reason=fitted['reason'])
                    else:
                        best = fitted['refined_hypotheses'][0]
                        cells = {c.cell_id: c for c in bank.cells}
                        prediction = sum(s['energy_keV']*N.unit_prediction(cells[s['cell_id']], s['fractional_coordinates'])
                                         for s in best['sites'])
                        residual = prediction-waveform
                        # Truth and true-cell metadata enter only after all800
                        # coarse costs and16 continuous refinements are complete.
                        truth = [{'contact_ids': targets[ref]['contact_ids'],
                            'native_position_mm': (np.asarray(targets[ref]['native_position_m'])*1000.).tolist(),
                            'energy_keV': .5*payload['injection_energy_keV']}
                            for ref, payload in zip(refs, payloads)]
                        true_refs = [frozenset(w['record_ref'] for w in targets[ref]['training_weights']) for ref in refs]
                        true_ids = [next(c.cell_id for c in bank.cells if frozenset(p.ref for p in c.corners) == corner_refs)
                                    for corner_refs in true_refs]
                        true_coarse = next(h for h in fitted['coarse_hypotheses'] if set(h['cell_ids']) == set(true_ids))
                        true_matching = next(m['matching_id'] for m in fitted['matchings']
                            if {tuple(p) for p in m['contact_ids']} == {tuple(t['contact_ids']) for t in truth})
                        record.update(status='evaluated', evaluation={
                            'truth_sites': truth, 'true_cell_ids': true_ids, 'true_matching_id': true_matching,
                            'matching_correct': best['matching_id'] == true_matching,
                            'true_cell_coarse_global_rank': true_coarse['global_rank'],
                            'true_cell_coarse_matching_rank': true_coarse['matching_rank'],
                            'true_cell_pair_refined': true_coarse['matching_rank'] <= P.TOP_K_PER_MATCHING,
                            'assignment_min_errors': assignment_errors(best['sites'], truth),
                            'total_energy_error_keV': sum(s['energy_keV'] for s in best['sites'])-sum(t['energy_keV'] for t in truth),
                            'max_channel_rms_keV': float(np.sqrt(np.mean(residual*residual, axis=1)).max()),
                            'max_absolute_residual_keV': float(np.abs(residual).max())})
            rows.append(record)
            ledger.write(json.dumps(record, sort_keys=True, separators=(',', ':'), allow_nan=False)+'\n')
            ledger.flush()
    if any(N.L.W.sha(ROOT/ref) != digest for ref, digest in source_sha.items()):
        raise ValueError('Paired source changed during evaluation; partial ledger preserved')
    result = {'kind': 'gegi_fixed_prompt_two_site_saved_mixtures_v1', 'status': status,
        'source_sha256': source_sha, 'input_sha256': single.input_sha256,
        'native_producer_sha256_at_capture': single.native_producer_sha256,
        'coverage': single.coverage, 'summary': summarize(rows),
        'by_true_matching': {f'matching-{i+1}': summarize([r for r in rows
            if r.get('evaluation', {}).get('true_matching_id') == f'matching-{i+1}']) for i in range(2)},
        'records': rows, 'mixture_indices': indices, 'completed_indices': [r['mixture_index'] for r in rows],
        'new_fit_calls': fits, 'reused_fit_calls': len(rows)-fits, 'reuse': reuse_binding,
        'new_native_calls': 0, 'new_field_solves': 0, 'new_transport_calls': 0,
        'elapsed_seconds': time.perf_counter()-started,
        'definitions': {'mixtures': 'Eight fixed prompt sums, each0.5times two independent saved500keV calibration waveforms; total500keV under the linear point-charge response model. Equal site energies are evaluation metadata only.',
            'search': 'Both disjoint-X/Y matchings derived from the4training pixels. All400cellpairs per matching receive coarse center cost and exact nonnegative two-energy profile. No truecell/pixel/source/energy pruning.',
            'refinement': 'Fixed best8coarse candidates per matching,16total, one center start each and unchanged8coordinate steps0.5..1/256. Both energies reprofiled at each trial. All800coarse hypotheses and16refinements retained.',
            'limits': 'Coarse pruning and fixed coordinate budget provide no global continuous optimum certificate. True-cell coarse ranks are posthoc diagnostics and never alter candidate selection.',
            'errors': 'Site assignment minimizes the sum of squared3Dposition errors over both permutations after fitting; positions compare actual native injection coordinates, energies compare250keV scaled injections.',
            'scope': 'Sparse four-pixel native calibration model; ideal signed waveforms, no hardware noise, time offsets, holdout/native real-event or imaging validation. Restricted two-site model does not test false splits.'}}
    _write(output/'result.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bank', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--indices', type=int, nargs='+')
    parser.add_argument('--max-seconds', type=float, required=True)
    parser.add_argument('--reuse', type=Path)
    args = parser.parse_args()
    result = evaluate(args.bank, args.output, list(range(8)) if args.indices is None else args.indices,
                      args.max_seconds, args.reuse)
    print(json.dumps({'status': result['status'], 'elapsed_seconds': result['elapsed_seconds'],
        'new_fit_calls': result['new_fit_calls'], 'reused_fit_calls': result['reused_fit_calls'],
        'summary': result['summary'], 'result_sha256': N.L.W.sha(args.output/'result.json')}, sort_keys=True))
