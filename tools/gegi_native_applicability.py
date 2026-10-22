"""Saved development-group applicability and fixed z0 pairing-separation checks."""
from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path
import re
import time

import numpy as np

import gegi_native_pair_inverse as P

N = P.N
ROOT = N.ROOT
CAL = '.local/gegi-10m/signal-recovery-v1/calibration/native-cell-bank'
DEV = '.local/gegi-10m/signal-recovery-v1/validation/full34-development-v3'
CHUNK = '.local/gegi-10m/campaign/chunks/co60-right/b000002'
PAIR = '.local/gegi-10m/signal-recovery-v1/validation/native-inverse-pair/result.json'
SEALED = {
    DEV+'/support-diagnostic.json': 'aa92b097cd60b649bc261de14971ab2ab9aeaa5d62def8fd919291dbdf2bdb0c',
    DEV+'/support-cell-detail.json': 'f1c6acb350d3ba00dde2d940fe38e31910bb14893ffc5cdc8535a21a2c077dd9',
    DEV+'/evaluation-groups.json': '588bb1661b76b53d253a4fc8f3458e076f8c678ea33e35f40259895781ab2259',
    DEV+'/report.json': 'fbded1454223b5ba79eb4300b68ea63d3f6bbff0d2970e44eddff32d2b4c0568',
    '.local/gegi-10m/signal-recovery-v1/validation/split-manifest.json': 'e055daaddef152a34341120c5f618b525c4d3336bddd7a7be9951f57352a3ed4',
    CHUNK+'/DONE.json': '24e0fa0df39424a3e8dcdc473a0bf15d7f1a2cbb0367c1b6fcf84bf5eb9d3e3e',
    CHUNK+'/transport/stream/manifest.json': 'd0ad54859c5d6813a6d5ae8aa8892983df2e0f2ff6b272f78785efe44baa95b5',
    PAIR: 'aeb714087bd816e59d04b540e9ff98c5f44823384ecfe46d7ffc9fb393acc903',
}


def _write(path, value):
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, sort_keys=True, separators=(',', ':'), allow_nan=False)
        stream.write('\n')


def metrics(delta):
    rms = np.sqrt(np.mean(delta*delta, axis=1))
    return {'rms_keV': float(np.sqrt(np.mean(delta*delta))),
        'max_channel_rms_keV': float(rms.max()), 'max_absolute_keV': float(np.abs(delta).max()),
        'max_absolute_terminal_keV': float(np.abs(delta[:, -1]).max()),
        'channel_rms_keV': rms.tolist()}


def prediction(hypothesis, bank):
    cells = {c.cell_id: c for c in bank.cells}
    return sum(s['energy_keV']*N.unit_prediction(cells[s['cell_id']], s['fractional_coordinates'])
               for s in hypothesis['sites'])


def partial_assignment(sites, truth):
    options = []
    for assignment in itertools.permutations(range(len(truth)), len(sites)):
        errors = [np.asarray(site['position_mm'])-np.asarray(truth[t]['deposition_centroid_mm'])
                  for site, t in zip(sites, assignment)]
        options.append((sum(float(e@e) for e in errors), assignment, errors))
    squared, assignment, errors = min(options, key=lambda row: (row[0], row[1]))
    unmatched = [i for i in range(len(truth)) if i not in assignment]
    return {'scope': 'Posthoc closest partial assignment only; not recovery of a multi-site event.',
        'truth_assignment': list(assignment), 'position_sum_square_mm2': squared,
        'sites': [{'fit_site': i, 'truth_site': t, 'position_error_mm': error.tolist(),
            'position_error_3d_mm': float(np.linalg.norm(error)),
            'energy_error_keV': site['energy_keV']-truth[t]['energy_keV'],
            'pixel_correct': site['contact_ids'] == truth[t]['cell']}
            for i, (site, t, error) in enumerate(zip(sites, assignment, errors))],
        'unmatched_truth_indices': unmatched,
        'unmatched_truth_energy_keV': sum(truth[i]['energy_keV'] for i in unmatched)}


def posthoc_domain(truth, bank):
    rows = []
    for site in truth:
        point = np.asarray(site['deposition_centroid_mm'])
        cells = [c for c in bank.cells if list(c.contact_ids) == site['cell']]
        covering = [c.cell_id for c in cells if np.all(point >= c.lower_mm) and np.all(point <= c.upper_mm)]
        distances = [float(np.linalg.norm(np.maximum(np.maximum(c.lower_mm-point, point-c.upper_mm), 0.)))
                     for c in cells]
        rows.append({'contact_ids': site['cell'], 'centroid_mm': point.tolist(),
            'pixel_available': bool(cells), 'covering_cells': covering,
            'nearest_same_pixel_cell_distance_mm': min(distances) if distances else None})
    return {'centroids': rows, 'all_centroids_covered': all(r['covering_cells'] for r in rows),
        'scope': 'Truth-based applicability diagnosis after fitting; centroid coverage does not establish point-like deposition.'}


def coverage_count(positive_ids, request, preflight, model_text):
    """Geometry/grid-only candidate count; no event positions or new drift."""
    channels = {c['id']: c for c in request['channels']}
    selected = [cid for cid in positive_ids if cid not in (17, 34)]
    windows = {}
    blocks = model_text.split('\n  - name: ')[1:]
    for cid in selected:
        block = next(b for b in blocks if re.search(r'\n    id: '+str(cid)+r'\n', b))
        boxes = re.findall(r'widths:\n\s+- ([\d.]+)\n\s+- ([\d.]+)\n\s+- ([\d.]+)', block)
        if not boxes:
            raise ValueError('No rectangular strip footprint in pinned model')
        family = channels[cid]['family']
        axis = 0 if family == 'X' else 1
        width = float(boxes[-1][axis])
        center = channels[cid]['strip_center_mm']
        windows[cid] = (center-width/2, center+width/2)
    axes = [np.asarray(a)*1000. for a in preflight['weighting_axes_m']]
    node_indices = {}
    intervals = {}
    for cid, (low, high) in windows.items():
        axis = 0 if channels[cid]['family'] == 'X' else 1
        ticks = axes[axis]
        selected_intervals = np.flatnonzero((ticks[:-1] < high) & (ticks[1:] > low))
        intervals[cid] = selected_intervals.tolist()
        node_indices[cid] = sorted(set(selected_intervals.tolist()+list(selected_intervals+1)))
    # Native Float32 detector faces are actual saved ticks. Full planning includes
    # the face nodes, while a second count removes contact-face starts explicitly.
    face = float(np.float32(np.float32(5.5)/np.float32(1000.)))*1000.
    full_z = np.flatnonzero((axes[2] >= -face) & (axes[2] <= face)).tolist()
    interior_z = [i for i in full_z if -face < axes[2][i] < face]
    pixels = list(itertools.product([i for i in selected if i <= 16], [i for i in selected if i >= 18]))
    full_nodes = set(); interior_nodes = set(); cell_union = set(); per_pixel = []
    for x, y in pixels:
        xy = list(itertools.product(node_indices[x], node_indices[y]))
        full_nodes.update((i, j, k) for i, j in xy for k in full_z)
        interior_nodes.update((i, j, k) for i, j in xy for k in interior_z)
        cells = set(itertools.product(intervals[x], intervals[y], full_z[:-1]))
        cell_union.update(cells)
        per_pixel.append({'contact_ids': [x, y], 'strip_footprint_x_mm': windows[x],
            'strip_footprint_y_mm': windows[y], 'xy_grid_interval_counts': [len(intervals[x]), len(intervals[y])],
            'full_z_intervals': len(full_z)-1, 'candidate_cells': len(cells),
            'candidate_corners_before_cross_pixel_deduplication': len(xy)*len(full_z)})
    def actual_position(index):
        return tuple(float(np.float32(np.float32(axes[d][i])/np.float32(1000.))) for d, i in enumerate(index))
    candidates = {actual_position(i) for i in full_nodes}
    interior = {actual_position(i) for i in interior_nodes}
    imported = {tuple(p['native_position_m']) for p in request['points']}
    return {'selection': 'All X/Y cross-pixels from observed strictly positive wired native terminal strips; no event centroid or true pair enters.',
        'positive_terminal_strip_ids': selected, 'field_grid_shape': [len(a) for a in axes],
        'strip_windows_from': 'Pinned model final rectangular metal-strip footprints; complete grid intervals intersecting each footprint.',
        'by_pixel': per_pixel, 'union_candidate_cells': len(cell_union),
        'corner_occurrences_before_cross_pixel_deduplication': sum(r['candidate_corners_before_cross_pixel_deduplication'] for r in per_pixel),
        'unique_candidate_corners': len(candidates), 'unique_strict_interior_corners': len(interior),
        'contact_face_candidate_corners': len(candidates-interior),
        'duplicate_imports_from_sealed_native_bank': len(candidates & imported),
        'new_candidate_corners_after_existing_imports': len(candidates-imported),
        'new_strict_interior_corners_after_existing_imports': len(interior-imported),
        'scope': 'Count only, no calibration launch or geometry acceptance. Bracketing nodes can cross metal-strip edges; contact-face nodes cannot be assumed valid interior injection starts. Existing imports counted only from the sealed378-record native bank.'}


def forward_prediction(target, bank):
    by_ref = {p.ref: p for cell in bank.cells for p in cell.corners}
    weights = [w['weight'] for w in target['training_weights']]
    if sum(weights) != 1.:
        if abs(sum(weights)-1.) > len(weights)*np.finfo(float).eps:
            raise ValueError('Frozen forward weights do not close within roundoff')
        weights[-1] = 1.-sum(weights[:-1])
    rows = []
    for item in target['training_weights']:
        corner = by_ref[item['record_ref']]
        rows.append({'signal_coverage': N.R.ALL34_COVERAGE,
            'channel_signals': [{'contact_id': cid, 'time_ns': corner.times_ns,
                'signed_induced_keV': corner.unit_wave[cid-1]*500.} for cid in N.R.ALL34_IDS],
            'endpoints': [{'species': species, 'samples': corner.arrivals_ns[species]+1.,
                'step_limit_reached': False, 'status': 'contact'} for species in ('electron', 'hole')]})
    return N.T.predict(rows, weights, 1.)[0]


def capture_scaling(coverage, inputs):
    """Reuse per-record measured costs; startup/first capture stay separate."""
    complete = N._checked(ROOT/CAL/'results/COMPLETE.json', N.COMPLETE_SHA256)
    runtime_ref = CAL+'/results/runtime.json'
    startup_ref = CAL+'/results/startup.json'
    for ref in (runtime_ref, startup_ref):
        inputs[ref] = N.L.W.sha(ROOT/ref)
    runtime = N._checked(ROOT/runtime_ref, inputs[runtime_ref])
    startup = N._checked(ROOT/startup_ref, inputs[startup_ref])
    if runtime['request_sha256'] != N.REQUEST_SHA256 or runtime['status'] != complete['status']:
        raise ValueError('Saved timing request/status differs')
    rows = []
    for record in complete['points']:
        ref = CAL+'/results/'+record['diagnostic_ref']
        diagnostic = N._checked(ROOT/ref, record['diagnostic_sha256'])
        inputs[ref] = record['diagnostic_sha256']
        if not record['reused_source']:
            rows.append({'record_ref': record['record_ref'],
                'native_injection_seconds': diagnostic['native_injection_seconds_this_attempt'],
                'capture_and_store_seconds': diagnostic['capture_and_store_seconds']})
    def describe(values):
        return {**N.L.describe(values), 'mean': float(np.mean(values)), 'sum': float(np.sum(values))}
    warm = rows[1:]
    capture = [r['capture_and_store_seconds'] for r in warm]
    native = [r['native_injection_seconds'] for r in warm]
    count = coverage['new_strict_interior_corners_after_existing_imports']
    return {'saved_total_process_seconds': runtime['elapsed_seconds'],
        'saved_startup_seconds_including_imports': startup['startup_seconds_including_worker_imports'],
        'saved_field_load_seconds': startup['field_load_seconds'],
        'first_new_capture_separate': rows[0], 'new_capture_count': len(rows),
        'remaining_after_first_native_injection_seconds': describe(native),
        'remaining_after_first_capture_and_store_seconds': describe(capture),
        'remaining_after_first_capture_minus_native_seconds': describe([r['capture_and_store_seconds']-r['native_injection_seconds'] for r in warm]),
        'strict_interior_count_only_scaling': {'new_corners': count,
            'capture_seconds_at_saved_median_per_record': count*float(np.median(capture)),
            'capture_seconds_at_saved_mean_per_record': count*float(np.mean(capture)),
            'capture_seconds_at_saved_p90_per_record': count*float(np.percentile(capture, 90))},
        'scope': 'Measured saved378-record bank:374new captures,4imports. First new capture kept separate because it includes first-call work. Capture timer covers injection, checkpoint serialization and endpoint diagnostics, not pure I/O; diagnostic-write/hash/other loop overhead is outside it. Scaling excludes startup/first-call/other overhead and geometry failures; not a runtime guarantee or authorization to launch.'}


def run(output, max_seconds, resume_first_group=False):
    started = time.perf_counter()
    output = Path(output).resolve()
    if output.exists() and not resume_first_group:
        raise FileExistsError('Preserve previous applicability evidence: '+str(output))
    if not resume_first_group:
        output.mkdir(parents=True)
    loaded = {ref: N._checked(ROOT/ref, digest) for ref, digest in SEALED.items()}
    single = N.load_bank(ROOT/CAL)
    bank = P.prepare_bank(single)
    pair_report = loaded[PAIR]
    for ref, digest in pair_report['source_sha256'].items():
        if N.L.W.sha(ROOT/ref) != digest:
            raise ValueError('Frozen paired fitter source changed: '+ref)
    source_sha = dict(pair_report['source_sha256'])
    source_sha['tools/gegi_native_applicability.py'] = N.L.W.sha(Path(__file__))
    # read_saved_group additionally verifies metadata and every native array hash.
    for ref in ('tools/gegi_event_store.py', 'tools/gegi_imaging.py'):
        source_sha[ref] = N.L.W.sha(ROOT/ref)
    done = loaded[CHUNK+'/DONE.json']
    store_ref = CHUNK+'/events.sqlite'
    store_sha = done['artifacts']['events.sqlite']['sha256']
    if N.L.W.sha(ROOT/store_ref) != store_sha:
        raise ValueError('DONE-bound native store changed')
    inputs = {**single.input_sha256, **SEALED, store_ref: store_sha}
    diagnostic = {r['original_identity']['campaign_initial_id']: r for r in loaded[DEV+'/support-diagnostic.json']['records']}
    details = {r['original_identity']['campaign_initial_id']: r for r in loaded[DEV+'/support-cell-detail.json']['records']}
    selected = loaded[DEV+'/evaluation-groups.json']['selection']['groups']
    if any(not any(r['campaign_initial_id'] == initial and r['split'] == 'development' for r in selected)
           for initial in (720929, 727922, 752677)):
        raise ValueError('Fixed development membership changed')
    reuse = None
    reused_record = None
    if resume_first_group:
        failure = json.loads((output/'failure.json').read_bytes())
        first_raw = (output/'records.jsonl').read_bytes()
        reused_record = json.loads(first_raw)
        old_startup = json.loads((output/'startup.json').read_bytes())
        if (N.R._sha(first_raw) != failure['completed_record_sha256']
                or reused_record['campaign_initial_id'] != 720929
                or N.L.W.sha(output/'failed-source.py') != failure['failed_source_sha256']
                or old_startup['input_sha256'] != inputs
                or any(source_sha.get(ref) != digest for ref, digest in old_startup['source_sha256'].items()
                       if ref != 'tools/gegi_native_applicability.py')):
            raise ValueError('First-group reuse pins changed')
        reuse = {'campaign_initial_id': 720929, 'completed_record_sha256': failure['completed_record_sha256'],
            'failed_source_sha256': failure['failed_source_sha256'],
            'initial_exec_wall_seconds': failure['initial_exec_wall_seconds'],
            'reused_fit_seconds': reused_record['fit_seconds'],
            'basis': 'Exact first record and unchanged native-store, waveform reader, bank and frozen fitter pins. Only downstream YAML reading was repaired.'}
    _write(output/('resume-startup.json' if resume_first_group else 'startup.json'), {'source_sha256': source_sha, 'input_sha256': inputs,
        'max_seconds': max_seconds, 'fit_groups': [720929, 727922], 'unfitted_limitation_group': 752677,
        'fit_api': 'P.fit_two(signed34_waveform, bank)', 'coverage': single.coverage,
        'original_deposit_timing_preserved': True, 'new_physics_calls': 0, 'first_group_reuse': reuse})
    arrays = {'fit_grid_ns': N.R.FIT_GRID_NS}
    records = [] if reused_record is None else [reused_record]
    coverage = None
    if reused_record is not None:
        # Concrete recovery of the one saved fit. Rebuild derived waveform arrays
        # and the downstream count only; never call fit_two for720929 again.
        identity = reused_record['identity']
        event, native, metadata_sha = N.R.read_saved_group(ROOT/store_ref, identity['raw_primary_id'], 0)
        if metadata_sha != reused_record['metadata_sha256_verified']:
            raise ValueError('Reused group metadata changed')
        waveform, support = N.L.waveform({'channel_signals': [{'contact_id': cid, **native[cid]}
            for cid in N.R.ALL34_IDS], 'signal_coverage': N.R.ALL34_COVERAGE,
            'status': event['status'], 'valid': event['status'] == 'completed'})
        if waveform is None:
            raise ValueError('Reused waveform unavailable: '+str(support))
        arrays['group_720929_observed'] = waveform
        for matching in reused_record['fit']['matchings']:
            key = matching['matching_id']
            candidate = next(h for h in reused_record['fit']['refined_hypotheses'] if h['matching_id'] == key)
            predicted = prediction(candidate, bank)
            arrays[f'group_720929_{key}_prediction'] = predicted
            arrays[f'group_720929_{key}_residual'] = predicted-waveform
        request = N._checked(ROOT/CAL/'request.json', N.REQUEST_SHA256)
        preflight_ref = CAL+'/results/preflight.json'
        preflight = N._checked(ROOT/preflight_ref, single.input_sha256[preflight_ref])
        model_ref = request['model_ref']
        if N.L.W.sha(ROOT/model_ref) != request['model_sha256']:
            raise ValueError('Pinned strip geometry changed')
        inputs[model_ref] = request['model_sha256']
        coverage = coverage_count(reused_record['observable_mismatch']['positive_wired_terminal_strips'],
                                  request, preflight, (ROOT/model_ref).read_text())
    with (output/'records.jsonl').open('a' if resume_first_group else 'x', encoding='utf-8', newline='\n') as ledger:
        for initial in ((727922,) if resume_first_group else (720929, 727922)):
            if time.perf_counter()-started >= max_seconds:
                raise TimeoutError('Applicability budget exhausted; partial records preserved')
            identity = diagnostic[initial]['original_identity']
            event, native, metadata_sha = N.R.read_saved_group(ROOT/store_ref, identity['raw_primary_id'], 0)
            if metadata_sha != identity['metadata_sha256'] or set(native) != set(N.R.ALL34_IDS):
                raise ValueError('Fixed group metadata or native coverage changed')
            channel_signals = [{'contact_id': cid, **native[cid]} for cid in N.R.ALL34_IDS]
            waveform, support = N.L.waveform({'channel_signals': channel_signals,
                'signal_coverage': N.R.ALL34_COVERAGE, 'status': event['status'], 'valid': event['status'] == 'completed'})
            if waveform is None:
                raise ValueError('Original aggregate waveform unsupported: '+str(support))
            fit_started = time.perf_counter()
            fitted = P.fit_two(waveform, bank)
            fit_seconds = time.perf_counter()-fit_started
            # All following truth/coverage/assignment information is diagnostic;
            # it did not select cells, matching, energies, timing or eligibility.
            truth = diagnostic[initial]['significant_endpoint_cells']
            best = fitted['refined_hypotheses'][0]
            wired_terminal = np.asarray([float(native[cid]['signed_induced_keV'][-1])*(1 if cid <= 17 else -1)
                                         for cid in N.R.ALL34_IDS])
            positive = [cid for cid, charge in zip(N.R.ALL34_IDS, wired_terminal) if charge > 0.]
            modeled_collectors = {cid for c in bank.cells for cid in c.contact_ids}
            best_per_matching = [next(h for h in fitted['refined_hypotheses'] if h['matching_id'] == m['matching_id'])
                                 for m in fitted['matchings']]
            residual_metrics = {}
            arrays[f'group_{initial}_observed'] = waveform
            for candidate in best_per_matching:
                key = candidate['matching_id']
                predicted = prediction(candidate, bank)
                arrays[f'group_{initial}_{key}_prediction'] = predicted
                arrays[f'group_{initial}_{key}_residual'] = predicted-waveform
                residual_metrics[key] = metrics(predicted-waveform)
            native_time = np.asarray(native[1]['time_ns'])
            delays = [s['deposition_delay_ns'] for s in event['steps']]
            assignment = partial_assignment(best['sites'], truth)
            exact_support = {tuple(s['contact_ids']) for s in best['sites']} == {tuple(t['cell']) for t in truth}
            record = {'campaign_initial_id': initial, 'status': 'diagnostic_fit_not_applicable',
                'identity': identity, 'metadata_sha256_verified': metadata_sha,
                'native_wave_shape': [34, len(native_time)], 'native_time_range_ns': [float(native_time[0]), float(native_time[-1])],
                'native_time_steps_ns': np.unique(np.diff(native_time)).tolist(), 'fit_wave_shape': list(waveform.shape),
                'time_convention': event['time_convention'], 'group_origin_time_ns': event['group_origin_time_ns'],
                'deposition_delay_range_ns': [min(delays), max(delays)],
                'fit': fitted, 'fit_seconds': fit_seconds, 'matching_residuals': residual_metrics,
                'observable_mismatch': {'positive_wired_terminal_strips': positive,
                    'unmodeled_positive_terminal_strips': [cid for cid in positive if cid not in modeled_collectors],
                    'wired_terminal_keV': wired_terminal.tolist(),
                    'scope': 'Strictly positive native terminal charge after fixed X+1/Y-1 wiring; no added selection threshold.'},
                'posthoc': {'truth_cells': truth, 'truth_cell_count': len(truth), 'model_site_count': 2,
                    'site_count_compatible': len(truth) == 2, 'exact_endpoint_support_match': exact_support,
                    'matching_error': None if len(truth) != 2 else not exact_support,
                    'matching_comparison_scope': 'Undefined as a two-pairing error when true support has more than two cells.',
                    'domain': posthoc_domain(truth, bank), 'closest_partial_assignment': assignment,
                    'total_energy_error_keV': sum(s['energy_keV'] for s in best['sites'])-diagnostic[initial]['input_deposition_keV'],
                    'deposition_extent': details[initial]['cells'],
                    'recovered_event': False, 'false_splitting_established': False}}
            records.append(record)
            ledger.write(json.dumps(record, sort_keys=True, separators=(',', ':'), allow_nan=False)+'\n'); ledger.flush()
            if initial == 720929:
                request = N._checked(ROOT/CAL/'request.json', N.REQUEST_SHA256)
                preflight_ref = CAL+'/results/preflight.json'
                preflight = N._checked(ROOT/preflight_ref, single.input_sha256[preflight_ref])
                model_ref = request['model_ref']
                model_bytes = (ROOT/model_ref).read_bytes()
                if N.R._sha(model_bytes) != request['model_sha256']:
                    raise ValueError('Pinned strip geometry changed')
                inputs[model_ref] = request['model_sha256']
                coverage = coverage_count(positive, request, preflight, (ROOT/model_ref).read_text())
    # Unfitted case: retain the existing five-cell/rank-four evidence directly.
    limitation = {'campaign_initial_id': 752677, 'status': 'not_fitted',
        'reason': 'five_endpoint_cells_outside_four_pixel_bank_and_two_site_model',
        'identity': diagnostic[752677]['original_identity'],
        'truth_cells': diagnostic[752677]['significant_endpoint_cells'],
        'prior_site_count_and_rank_evidence': diagnostic[752677]['no_matching_support_bookkeeping'],
        'posthoc_domain': posthoc_domain(diagnostic[752677]['significant_endpoint_cells'], bank),
        'new_fit_calls': 0, 'recovered_event': False}
    request = N._checked(ROOT/CAL/'request.json', N.REQUEST_SHA256)
    targets = {t['reference_record_ref']: t for t in request['targets']}
    timing = N._checked(ROOT/CAL/'results/timing-comparison.json', N.TIMING_SHA256)
    timing_rows = {r['reference_record_ref']: r for r in timing['records']}
    separations = []
    for index in (3, 7):
        original = next(r for r in pair_report['records'] if r['mixture_index'] == index)
        refs = original['source_record_refs']
        observed = []
        forwards = []
        saved_metrics = []
        for ref in refs:
            target = targets[ref]
            row = N._checked(ROOT/target['source_record']['ref'], target['source_record']['sha256'])['payload']
            waveform, support = N.L.waveform(row)
            if waveform is None:
                raise ValueError('Frozen z0 reference unavailable')
            forward = forward_prediction(target, single)
            measured = metrics(forward-waveform)
            saved = timing_rows[ref]['metrics']['native_timewarp']
            if abs(measured['max_channel_rms_keV']-saved['max_channel_rms_keV']) > 1e-9:
                raise ValueError('Saved forward residual did not reproduce')
            observed.append(waveform); forwards.append(forward); saved_metrics.append(saved)
        observed_sum = .5*(observed[0]+observed[1])
        forward_sum = .5*(forwards[0]+forwards[1])
        bests = [next(h for h in original['fit']['refined_hypotheses'] if h['matching_id'] == f'matching-{i}')
                 for i in (1, 2)]
        predicted = [prediction(h, bank) for h in bests]
        separation = metrics(predicted[0]-predicted[1])
        interpolation = metrics(forward_sum-observed_sum)
        arrays[f'z0_mixture_{index}_observed'] = observed_sum
        arrays[f'z0_mixture_{index}_forward_interpolation'] = forward_sum
        arrays[f'z0_mixture_{index}_matching_1_prediction'] = predicted[0]
        arrays[f'z0_mixture_{index}_matching_2_prediction'] = predicted[1]
        arrays[f'z0_mixture_{index}_opposite_matching_difference'] = predicted[0]-predicted[1]
        separations.append({'mixture_index': index, 'source_record_refs': refs,
            'opposite_matching_waveform_separation': separation,
            'saved_forward_interpolation_mixture_residual': interpolation,
            'saved_individual_forward_metrics': saved_metrics,
            'separation_to_interpolation_residual_ratio': {key: separation[key]/interpolation[key]
                for key in ('rms_keV', 'max_channel_rms_keV', 'max_absolute_keV') if interpolation[key] > 0.},
            'matching_residuals': {h['matching_id']: metrics(p-observed_sum) for h, p in zip(bests, predicted)},
            'best_hypotheses_reused': bests, 'new_fit_calls': 0,
            'interpretation': 'Deterministic separation compared with saved interpolation discrepancy only; not a noise scale, statistical significance, acceptance gate or global optimization certificate.'})
    capture_times = capture_scaling(coverage, inputs)
    array_path = output/'waveforms.npz'
    np.savez_compressed(array_path, **arrays)
    with np.load(array_path) as saved:
        if set(saved.files) != set(arrays) or any(not np.array_equal(saved[k], v) for k, v in arrays.items()):
            raise ValueError('Lossless waveform evidence reload failed')
    if any(N.L.W.sha(ROOT/ref) != digest for ref, digest in source_sha.items()):
        raise ValueError('Applicability source changed; partial evidence preserved')
    elapsed = time.perf_counter()-started
    result = {'kind': 'gegi_saved_native_inverse_applicability_v1',
        'status': 'completed' if elapsed <= max_seconds else 'completed_over_budget',
        'source_sha256': source_sha, 'input_sha256': inputs, 'elapsed_seconds': elapsed,
        'max_seconds': max_seconds, 'new_fit_calls': 1 if resume_first_group else 2,
        'completed_total_fit_calls': 2, 'reused_first_group_fit': reuse, 'reused_pair_fit_cases': [3, 7],
        'new_native_calls': 0, 'new_field_solves': 0, 'new_transport_calls': 0,
        'records': records, 'unfitted_limitation': limitation, 'z0_separation': separations,
        'next_coverage_count': coverage, 'saved_capture_scaling': capture_times,
        'waveform_evidence': {'ref': array_path.relative_to(ROOT).as_posix(), 'sha256': N.L.W.sha(array_path),
            'arrays': {key: {'shape': list(value.shape), 'dtype': str(value.dtype)} for key, value in arrays.items()},
            'reload_exact': True, 'time_unit': 'ns', 'signal_unit': 'native_signed_keV'},
        'definitions': {'observed_waveform': 'Exact DONE-bound native34-channel aggregate, linearly interpolated to the existing0..250ns2ns grid, left0/right original terminal. Native group-relative time/deposit delays remain intact; no true alignment, energy renormalization or per-event gain.',
            'fits': 'Unchanged waveform-only two-site fitter searches both matchings/all800coarse cellpairs and16fixed refinements. Raw alternatives retained even for out-of-domain observations.',
            'truth': 'Saved development diagnostic/detail enters only after each fit. Charge-cell centroids/energies and partial assignments are diagnostics, not identified photon vertices or recovered multi-site events.',
            'scope': 'Applicability failure evidence, no holdout or production promotion. Restricted two-site model cannot establish false splitting. No invented noise model or tuned selection threshold.'}}
    _write(output/'result.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--max-seconds', type=float, default=120.)
    parser.add_argument('--resume-first-group', action='store_true',
                        help='Reuse the exact720929 record from the preserved downstream parsing failure')
    args = parser.parse_args()
    if args.max_seconds <= 0 or args.max_seconds > 120:
        raise ValueError('Use a positive budget capped at120seconds')
    result = run(args.output, args.max_seconds, args.resume_first_group)
    print(json.dumps({'status': result['status'], 'elapsed_seconds': result['elapsed_seconds'],
        'result_sha256': N.L.W.sha(args.output/'result.json'),
        'groups': [{'id': r['campaign_initial_id'], 'best_rms_keV': r['fit']['refined_hypotheses'][0]['rms_keV'],
            'unmodeled_positive_terminal_strips': r['observable_mismatch']['unmodeled_positive_terminal_strips'],
            'all_centroids_covered': r['posthoc']['domain']['all_centroids_covered'],
            'total_energy_error_keV': r['posthoc']['total_energy_error_keV']} for r in result['records']],
        'coverage_count': result['next_coverage_count'],
        'z0_separation': [{'mixture_index': r['mixture_index'],
            'separation': r['opposite_matching_waveform_separation'],
            'interpolation_residual': r['saved_forward_interpolation_mixture_residual'],
            'ratio': r['separation_to_interpolation_residual_ratio']} for r in result['z0_separation']]}, sort_keys=True))
