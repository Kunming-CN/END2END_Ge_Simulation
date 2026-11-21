"""Summarize sealed GeGI native repair and bounded drift probes for the exhibit."""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
from statistics import median


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def load(path):
    return json.loads(path.read_bytes())


def require(condition, message):
    if not condition:
        raise ValueError(message)


def cause_rows(rows, direction):
    return [dict(status=status, domain_error=error, groups=count)
            for (status, error), count in Counter(
                (r[f'{direction}_status'], r[f'{direction}_domain_error']) for r in rows).items()]


def census(recovery, reconciliation, rows):
    identity, history = recovery['identity'], recovery['conditional_history']
    unique = {(r['event_id'], r['group_id']) for r in rows}
    require(len(unique) == len({r['ordinal'] for r in rows}) == len(rows) == reconciliation['groups']
            == identity['group_count'] == history['processed_groups'], 'Original unavailable-group identities do not close')
    original = Counter(r['original_status'] for r in rows)
    resolved = Counter(r['new_status'] for r in rows)
    complete = sum(r['complete'] for r in rows)
    require(resolved == recovery['counts'] == reconciliation['counts']
            and complete == resolved['completed'] == reconciliation['complete_native_groups']
            == history['recovered_complete_groups']
            and all(r['complete'] == (r['new_status'] == 'completed') for r in rows),
            'Sealed native outcomes do not close')
    rebuilt = defaultdict(Counter)
    old_aggregate, old_detail = Counter(), Counter()
    measured, inherited = [], []
    for row in rows:
        status, error = row['original_status'], row['original_domain_error']
        new = row['new_status']
        rebuilt[(status, error)][new] += 1
        old_aggregate[f'{status} -> {new}'] += 1
        old_detail[f'{error or status} -> {new}'] += 1
        if row['timing_status'] == 'inherited_exact_prior_native':
            require(row['complete'] and row['elapsed_seconds'] is None and row['native_recovery_inherited'],
                    'Inherited response must be complete and carry its prior provenance')
            inherited.append(row)
        else:
            require(row['timing_status'] == 'measured' and row['native_recovery_inherited'] is None
                    and math.isfinite(row['elapsed_seconds']) and row['elapsed_seconds'] >= 0.,
                    'Expected a measured time for every newly processed group')
            measured.append(row)
    timing = {'inherited_exact_prior_native': len(inherited), 'measured': len(measured)}
    times = [r['elapsed_seconds'] for r in measured]
    require(old_aggregate == recovery['transitions'] and old_detail == reconciliation['transitions']
            and timing == reconciliation['timing_counts']
            and len(measured) == recovery['new_groups_this_activation']
            and math.isclose(math.fsum(times), recovery['new_native_seconds'], abs_tol=1e-9, rel_tol=0.),
            'Sealed native transitions or timing totals do not close')
    inherited_causes = Counter((r['original_status'], r['original_domain_error']) for r in inherited)
    transitions = [dict(original_status=status, original_domain_error=error, groups=sum(outcomes.values()),
                        outcomes=dict(outcomes), inherited_complete_groups=inherited_causes[(status, error)],
                        measured_complete_groups=outcomes['completed']-inherited_causes[(status, error)])
                   for (status, error), outcomes in rebuilt.items()]
    return dict(original_unavailable_groups=len(rows), original_status_counts=original, final_status_counts=resolved,
                cause_transitions=transitions, final_causes=cause_rows(rows, 'new'), complete_groups=complete,
                remaining_unavailable_groups=len(rows)-complete, inheritance_and_measurement=timing,
                measured_outcomes=Counter(r['new_status'] for r in measured)), times


def conditional_mask(acquisition, recovery):
    history = recovery['conditional_history']
    before, after = history['old_unavailable_union'], history['remaining_unknown_union']
    live = acquisition['live_time_ns']
    old, current = acquisition['excluded_intervals_ns'], history['remaining_intervals_ns']
    for intervals, summary in ((old, before), (current, after)):
        require(all(0 <= start < stop <= live for start, stop in intervals)
                and all(a[1] < b[0] for a, b in zip(intervals, intervals[1:]))
                and len(intervals) == summary['merged_excluded_intervals']
                and math.fsum(stop-start for start, stop in intervals) == summary['excluded_time_ns'],
                'Conditional unavailable-history interval union does not close')
    outer = iter(old)
    enclosing = next(outer, None)
    for start, stop in current:
        while enclosing is not None and start >= enclosing[1]:
            enclosing = next(outer, None)
        require(enclosing is not None and enclosing[0] <= start < stop <= enclosing[1],
                'A remaining conditional interval falls outside the original mask')
    def receipt(summary):
        time = summary['excluded_time_ns']
        return dict(excluded_time_ns=time, excluded_seconds=time/1e9, share_of_original_exposure=time/live,
                    merged_excluded_intervals=summary['merged_excluded_intervals'], unavailable_groups=summary['failure_count'])
    return dict(original_exposure_seconds=live/1e9, original=receipt(before), remaining=receipt(after),
                difference_seconds=(before['excluded_time_ns']-after['excluded_time_ns'])/1e9,
                scope='Conditional model of unknown native history. The original shared ADC, triggers, accepted exposure and images are unchanged.')


def probe_outcomes(diagnosis, plan):
    """Ensure every requested fixed deposit subset has exactly one observed condition."""
    planned = {row['ordinal']: row for row in plan}
    rows = diagnosis['results']
    require(diagnosis['drift_only'] is True and len(planned) == len(plan) == len(rows)
            and {r['ordinal'] for r in rows} == set(planned), 'Configured drift-probe conditions do not close')
    keys, groups = set(), defaultdict(list)
    status = Counter()
    for row in rows:
        spec = planned[row['ordinal']]
        require(row['event_id'] == spec['group']['event_id']
                and row['requested_drift_cap_ns'] == spec['drift_cap_ns']
                and [d['raw_row_index'] for d in row['deposits']] == spec['selected_raw_rows'],
                'A drift condition changed its saved event, deposited rows or requested horizon')
        groups[spec['selection']].append(row)
        for deposit in row['deposits']:
            keys.add((row['event_id'], spec['group']['group_id'], deposit['raw_row_index']))
            status[deposit['status']] += 1
    return rows, keys, groups, status


def cap_series(rows):
    series = []
    for row in rows:
        deposit, = row['deposits']
        tracks = {end['species']: dict(status=end['status'], final_time_ns=path['time_ns'][-1],
                  stationary_last_step=path['stationary_last_step'],
                  projected_candidate_equals_endpoint=(path['terminal_trial'] or {}).get('projected_candidate_equals_endpoint'))
                  for end, path in zip(deposit['endpoints'], deposit['terminal_paths'], strict=True)
                  if end['species'] == path['species']}
        require(len(tracks) == 2, 'Missing carrier identity in the drift-cap control')
        series.append(dict(requested_drift_cap_ns=row['requested_drift_cap_ns'],
                           native_support_ns=row['configured_native_support_ns'],
                           original_event_id=row['event_id'], original_ge_row=deposit['raw_row_index'],
                           deposit_status=deposit['status'], carriers=tracks))
    return series


def projection_case(row):
    deposit, = row['deposits']
    geometry = deposit['projected_segment_geometry']
    return dict(original_event_id=row['event_id'], original_ge_row=deposit['raw_row_index'],
                outcome=deposit['status'], boundary_reason=deposit['boundary_failure']['reason'],
                charge_unknown=deposit['boundary_failure']['charge_unknown'],
                segment_length_m=geometry['segment_length_m'], crossing_is_endpoint=geometry['crossing_equals_endpoint'],
                normal_dot_segment_m=geometry['normal_dot_segment_m'],
                normal_projection_to_length=geometry['normal_dot_segment_m']/geometry['segment_length_m'])


def drift_probes(diagnosis, plan):
    rows, keys, groups, status = probe_outcomes(diagnosis, plan)
    moving = cap_series(groups['limit-electron-z-'])
    fixed = cap_series(groups['limit-electron-z+'])
    control = cap_series(groups['previous_exact34-channel_success_control'])
    tangent, = groups['no_positive_projected_motion']
    corner, = groups['no_positive_projected_motion_at_uncontacted_face_intersection']
    stopped = groups['stopped']
    stops = [d for row in stopped for d in row['deposits']]
    return dict(configured_conditions=len(rows), unique_original_deposit_rows=len(keys),
                evaluated_deposit_rows_including_repeated_horizons=sum(status.values()), deposit_status_counts=status,
                drift_precision_bits=diagnosis['drift_precision_bits'], drift_dt_ns=diagnosis['drift_dt_ns'],
                analytic_semiconductor_boundary=diagnosis['analytic_semiconductor_boundary'],
                configured_native_support_ns=sorted({r['configured_native_support_ns'] for r in rows}),
                slow_drift=dict(series=moving, observation='The carriers were still moving at the original cap and both reached contacts with longer support.'),
                projected_fixed_point=dict(series=fixed, observation='At the two longer horizons the projected electron position became stationary without contact at the same time.'),
                stationary_electron_stops=dict(group_conditions=len(stopped), deposited_rows=len(stops), carriers=cause_stop_counts(stops),
                    observation='Short-horizon probes on the remaining stopped groups resolved the hole contacts and retained contact-free electron terminals.'),
                tangential_projection_roundoff=dict(**projection_case(tangent),
                    observation='The nominally tangential projected trial ended on the boundary with a normal component at roundoff scale.'),
                uncontacted_corner_projection=dict(**projection_case(corner),
                    observation='At the uncontacted face intersection the rejected segment had a finite outward component. Charge availability remains unknown.'),
                stable_contact_control=dict(series=control, observation='The control reached the same carrier endpoints at all three configured horizons.'),
                scope='The same selected deposited rows were evaluated at fixed horizons. These drift-only conditions do not measure group charge recovery or the prevalence of each mechanism.')


def cause_stop_counts(deposits):
    counts = Counter((p['species'], e['status'], p['stationary_last_step'])
                     for d in deposits for e, p in zip(d['endpoints'], d['terminal_paths'], strict=True)
                     if p['species'] == e['species'])
    require(sum(counts.values()) == 2*len(deposits), 'Stopped-probe carrier identities do not close')
    return [dict(species=species, status=status, stationary_last_step=stationary, rows=n)
            for (species, status, stationary), n in counts.items()]


def sampled_resources(resource):
    return {key: resource[key] for key in ('active_elapsed_seconds', 'process_peak_resident_bytes',
            'sampled_combined_resident_peak_bytes', 'run_logical_bytes_peak', 'sampling_interval_seconds')}


def run(recovery_root, probe_root, acquisition_path, probe_input_path):
    refs = dict(recovery=recovery_root/'recovery.json', reconciled_status_summary=recovery_root/'recovery-status-summary.json',
                reconciled_status_ledger=recovery_root/'recovery-status.jsonl', original_acquisition=acquisition_path,
                recovery_request=recovery_root/'native-request.json', drift_diagnosis=probe_root/'diagnosis.json',
                drift_probe_input=probe_input_path, drift_probe_request=probe_root/'request.json',
                drift_probe_resources=probe_root/'resources.json', drift_probe_completion=probe_root/'active-worker.json')
    digests = {name: sha(path) for name, path in refs.items()}
    recovery = load(refs['recovery'])
    reconciliation, diagnosis = load(refs['reconciled_status_summary']), load(refs['drift_diagnosis'])
    completion = load(refs['drift_probe_completion'])
    acquisition, request = load(acquisition_path), load(refs['recovery_request'])
    source_sha = acquisition['artifacts']['compton-candidates.sqlite']['sha256']
    require(recovery['kind'] == 'gegi_retained_native_recovery_v1' and recovery['status'] == 'completed'
            and reconciliation['kind'] == 'gegi_reconciled_native_recovery_ledger_v1'
            and diagnosis['kind'] == 'gegi_retained_native_diagnosis_v1'
            and acquisition['status'] == 'completed'
            and recovery['identity']['source_sha256'] == source_sha
            and recovery['identity']['request_sha256'] == digests['recovery_request']
            and reconciliation['status_ledger_sha256'] == digests['reconciled_status_ledger']
            and diagnosis['inputs_sha256'] == completion['inputs_sha256'] == digests['drift_probe_input']
            and diagnosis['request_sha256'] == completion['request_sha256'] == digests['drift_probe_request']
            and completion['status'] == 'completed' and completion['returncode'] == 0,
            'Completed repair, acquisition and probe evidence do not bind')
    require(request['field_cache']['sha256'] == diagnosis['field_sha256'], 'Recovery and drift probes used different field caches')
    with refs['reconciled_status_ledger'].open(encoding='utf-8') as ledger:
        rows = [json.loads(line) for line in ledger]
    counts, times = census(recovery, reconciliation, rows)
    masks = conditional_mask(acquisition, recovery)
    require(counts['original_unavailable_groups'] == acquisition['source']['unavailable_native_groups'] == masks['original']['unavailable_groups']
            and counts['remaining_unavailable_groups'] == masks['remaining']['unavailable_groups'], 'Masked group totals do not close')
    return dict(kind='gegi_native_response_repair_summary_v1', input_sha256=digests, exporter_sha256=sha(Path(__file__)),
                original_candidate_archive_sha256=source_sha,
                recovery_model=dict(model_sha256=request['model_sha256'], field_sha256=diagnosis['field_sha256'],
                                    **{key: request['numerics'][key] for key in ('drift_dt_ns', 'drift_cap_ns',
                                        'cached_drift_precision_bits', 'analytic_semiconductor_boundary', 'diffusion', 'self_repulsion')}),
                census=counts, conditional_mask=masks,
                resources=dict(recovery=dict(**sampled_resources(recovery['resources']), activation_seconds=recovery['activation_seconds'],
                                measured_group_processing_seconds=math.fsum(times), median_measured_group_seconds=median(times),
                                maximum_measured_group_seconds=max(times)),
                               drift_probes=sampled_resources(load(refs['drift_probe_resources'])),
                               scope='Resident memory and logical file bytes are sampled. Per-process peaks need not occur at the same instant.'),
                drift_probes=drift_probes(diagnosis, load(probe_input_path)),
                scope='Original unavailable native groups of the completed five-second acquisition. Terminal-complete native signals were verified. ADC and trigger recovery require a continuous readout replay and were not performed.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recovery', type=Path, required=True)
    parser.add_argument('--probe', type=Path, required=True)
    parser.add_argument('--acquisition', type=Path, required=True)
    parser.add_argument('--probe-input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = run(args.recovery, args.probe, args.acquisition, args.probe_input)
    with args.output.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
    print(args.output, sha(args.output))


if __name__ == '__main__':
    main()
