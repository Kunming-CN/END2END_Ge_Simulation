"""Saved-only independent single-site evaluation of gegi_native_inverse."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import platform
import time

import numpy as np

import gegi_native_inverse as N

ROOT = N.ROOT


def _write(path, value):
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, sort_keys=True, separators=(',', ':'), allow_nan=False)
        stream.write('\n')


def source_bindings(bank):
    return {**bank.helper_sha256, **{ref: N.L.W.sha(ROOT/ref) for ref in
        ('tools/gegi_native_inverse.py', 'tools/gegi_native_inverse_evaluation.py')}}


def summarize(rows):
    fitted = [r for r in rows if r['status'] == 'evaluated']
    return {'total': len(rows), 'evaluated': len(fitted),
        'unsupported_reasons': dict(Counter(r['reason'] for r in rows if r['status'] != 'evaluated')),
        'pixel_correct': sum(r['evaluation']['pixel_correct'] for r in fitted),
        'pixel_wrong': sum(not r['evaluation']['pixel_correct'] for r in fitted),
        'absolute_position_errors_mm': {axis: N.L.describe([abs(r['evaluation']['position_error_mm'][i])
            for r in fitted]) for i, axis in enumerate('XYZ')},
        'position_error_3d_mm': N.L.describe([r['evaluation']['position_error_3d_mm'] for r in fitted]),
        'absolute_energy_error_keV': N.L.describe([abs(r['evaluation']['energy_error_keV']) for r in fitted]),
        'signed_energy_error_keV': {'mean': float(np.mean([r['evaluation']['energy_error_keV'] for r in fitted])),
            'min': min((r['evaluation']['energy_error_keV'] for r in fitted), default=None),
            'max': max((r['evaluation']['energy_error_keV'] for r in fitted), default=None)} if fitted else {},
        'rms_keV': N.L.describe([r['fit']['hypotheses'][0]['rms_keV'] for r in fitted]),
        'max_channel_rms_keV': N.L.describe([r['evaluation']['max_channel_rms_keV'] for r in fitted]),
        'max_absolute_residual_keV': N.L.describe([r['evaluation']['max_absolute_residual_keV'] for r in fitted]),
        'boundary_hit_count': sum(bool(r['fit']['hypotheses'][0]['boundary_axes']) for r in fitted),
        'boundary_axes': dict(Counter(a for r in fitted for a in r['fit']['hypotheses'][0]['boundary_axes'])),
        'optimizer_statuses': dict(Counter(r['fit']['hypotheses'][0]['optimizer_status'] for r in fitted)),
        'model_evaluations': sum(h['model_evaluations'] for r in fitted for h in r['fit']['hypotheses']),
        'fit_seconds': N.L.describe([r['fit_seconds'] for r in fitted])}


def evaluate(directory, output, indices, max_seconds, reuse=None):
    started = time.perf_counter()
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError('Preserve previous evaluation: '+str(output))
    output.mkdir(parents=True)
    bank = N.load_bank(directory)
    sources = source_bindings(bank)
    request = N._checked(Path(directory)/'request.json', N.REQUEST_SHA256)
    targets = request['targets']
    if len(targets) != 80 or len(set(indices)) != len(indices) or any(i < 0 or i >= 80 for i in indices):
        raise ValueError('Unique indices in fixed80 target list required')
    checks = N.self_checks(bank)
    reused = {}
    reuse_bindings = None
    if reuse:
        raw = (Path(reuse)/'result.json').read_bytes()
        previous = json.loads(raw)
        if (previous['status'] != 'completed' or previous['source_sha256'] != sources
                or previous['input_sha256'] != bank.input_sha256):
            raise ValueError('Reuse requires completed source/input-identical results')
        reused = {r['target_index']: r for r in previous['records']}
        reuse_bindings = {'ref': (Path(reuse)/'result.json').resolve().relative_to(ROOT).as_posix(),
                          'sha256': N.R._sha(raw)}
    _write(output/'startup.json', {'kind': 'gegi_native_inverse_single_site_evaluation_v1',
        'source_sha256': sources, 'input_sha256': bank.input_sha256,
        'native_producer_sha256_at_capture': bank.native_producer_sha256,
        'target_indices': indices, 'max_seconds': max_seconds, 'reuse': reuse_bindings,
        'optimizer': {'start': 'all fractional coordinates0.5 in every cell',
            'steps': N.STEPS, 'energy': 'nonnegative least-squares scalar profiled from observed waveform and fixed training gain',
            'objective': 'equal weight mean squared residual over all34 signed channels and126 samples'},
        'environment': {'python': platform.python_version(), 'numpy': np.__version__, 'platform': platform.platform()},
        'model': 'gpt-6.1-sol', 'reasoning_effort': 'ultra', 'self_checks': checks,
        'bank_load_seconds': bank.load_seconds, 'coverage': bank.coverage})
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
                target = targets[index]
                reference = N._checked(ROOT/target['source_record']['ref'], target['source_record']['sha256'])['payload']
                waveform, support = N.L.waveform(reference)
                record = {'target_index': index, 'reference_record_ref': target['reference_record_ref'],
                          'reference_sha256': target['source_record']['sha256']}
                if waveform is None:
                    record.update(status='unsupported', reason=support['reason'], reference_support=support)
                else:
                    fit_started = time.perf_counter()
                    # The ONLY fitting inputs. No truth/pixel/cell/energy metadata.
                    fitted = N.fit_single(waveform, bank)
                    fits += 1
                    record.update(fit=fitted, fit_seconds=time.perf_counter()-fit_started)
                    if fitted['status'] != 'fitted':
                        record.update(status='unsupported', reason=fitted['reason'])
                    else:
                        best = fitted['hypotheses'][0]
                        cell = next(c for c in bank.cells if c.cell_id == best['cell_id'])
                        predicted = N.unit_prediction(cell, best['fractional_coordinates'])*best['energy_keV']
                        residual = predicted-waveform
                        # Independent truth is opened here, after all80 global
                        # cell hypotheses and their estimated energies are fixed.
                        truth_mm = np.asarray(target['native_position_m'])*1000.
                        error = np.asarray(best['position_mm'])-truth_mm
                        record.update(status='evaluated', evaluation={
                            'true_contact_ids': target['contact_ids'], 'true_native_position_mm': truth_mm.tolist(),
                            'nominal_requested_position_mm': target['position_mm'], 'support_kind': target['support_kind'],
                            'true_injection_energy_keV': reference['injection_energy_keV'],
                            'pixel_correct': best['contact_ids'] == target['contact_ids'],
                            'position_error_mm': error.tolist(), 'position_error_3d_mm': float(np.linalg.norm(error)),
                            'energy_error_keV': best['energy_keV']-reference['injection_energy_keV'],
                            'max_channel_rms_keV': float(np.sqrt(np.mean(residual*residual, axis=1)).max()),
                            'max_absolute_residual_keV': float(np.abs(residual).max()),
                            'wrong_pixel_hypotheses_retained': sum(h['contact_ids'] != target['contact_ids']
                                for h in fitted['hypotheses'])})
            rows.append(record)
            ledger.write(json.dumps(record, sort_keys=True, separators=(',', ':'), allow_nan=False)+'\n')
            ledger.flush()
    if any(N.L.W.sha(ROOT/ref) != digest for ref, digest in sources.items()):
        raise ValueError('Inverse source changed during evaluation; partial ledger preserved')
    result = {'kind': 'gegi_native_inverse_single_site_evaluation_v1', 'status': status,
        'source_sha256': sources, 'input_sha256': bank.input_sha256,
        'native_producer_sha256_at_capture': bank.native_producer_sha256,
        'summary': summarize(rows), 'by_pixel': {str(pixel): summarize([r for r in rows
            if r.get('evaluation', {}).get('true_contact_ids') == pixel]) for pixel in bank.coverage['pixels']},
        'by_depth_mm': {str(z): summarize([r for r in rows if r.get('evaluation', {})
            .get('nominal_requested_position_mm', [None]*3)[2] == z]) for z in N.L.VALIDATION_AXES[2]},
        'coverage': bank.coverage, 'target_indices': indices, 'completed_indices': [r['target_index'] for r in rows],
        'new_fit_calls': fits, 'reused_fit_calls': len(rows)-fits, 'reuse': reuse_bindings,
        'new_native_calls': 0, 'new_field_solves': 0, 'new_transport_calls': 0,
        'self_checks': checks, 'records': rows, 'elapsed_seconds': time.perf_counter()-started,
        'definitions': {'inputs': 'Only saved34-channel native signed keV on fixed0..250ns2ns grid. No electronics/hardware noise.',
            'search': 'All80 available candidate cells searched for every observation. Cells derived only as unique frozen training-corner sets; target weights/coordinates never enter fitting.',
            'energy': 'One global fixed500keV training gain. Unknown nonnegative scalar energy estimated separately for each waveform from the residual objective; no true-energy constraint or normalization.',
            'position_error': 'Estimated XYZ minus independently saved actual native injection coordinates in mm; nominal requested coordinates retained separately.',
            'optimizer': 'Deterministic single centre start and8shrinking coordinate steps0.5..1/256. A completed fixed budget is not a global-optimum certificate or uncertainty estimate.',
            'warp': 'Existing carrier landmarks from training endpoints only; order flips explicitly unsupported with no fallback. Zero-weight boundary corners dropped, unit-sum correction only within roundoff.',
            'scope': 'Independent single-site calibration injections only. Sparse4-pixel supported domain; no holdout/native real events, two-site recovery, detector performance, or imaging claim.'}}
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
    result = evaluate(args.bank, args.output, list(range(80)) if args.indices is None else args.indices,
                      args.max_seconds, args.reuse)
    print(json.dumps({'status': result['status'], 'elapsed_seconds': result['elapsed_seconds'],
        'new_fit_calls': result['new_fit_calls'], 'reused_fit_calls': result['reused_fit_calls'],
        'summary': result['summary'], 'result_sha256': N.L.W.sha(args.output/'result.json')}, sort_keys=True))
