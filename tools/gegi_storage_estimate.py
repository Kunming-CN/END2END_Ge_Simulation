"""Estimate candidate archive space from a measured completed readout reference.

This is a storage model, not a fresh-production acceptance or processing-time
prediction. Source-history replay is useful for measuring the retention format;
its candidate yield and missing-history fraction are explicit model assumptions.
"""
from __future__ import annotations
import argparse
from contextlib import closing
import gzip
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import zlib

KIND = 'gegi_candidate_storage_reference_v1'
PACKAGED_REFERENCE = Path(__file__).with_name('gegi_storage_reference.json')
SHARED_FIELD_CACHE_BYTES = 857068900


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _interval_duration(intervals, live_time_ns):
    """Union before counting qualification; overlaps must never be counted twice."""
    total = 0.; end = 0.
    for left, right in sorted(intervals):
        if not all(type(v) in (int, float) and math.isfinite(v) for v in (left, right)) or right < left:
            raise ValueError('Invalid excluded acquisition interval')
        left, right = max(0., left), min(live_time_ns, right)
        if right > max(left, end): total += right-max(left, end)
        end = max(end, right)
    return total


def _safe_source(source):
    """Publish only explicit identities and scientific settings, never local refs."""
    keys = ('chunk_index', 'chunk_sha256', 'database_sha256', 'transport_sha256',
            'field_cache_sha256', 'field_calibration_sha256', 'geometry_sha256',
            'model_sha256', 'native_request_sha256', 'radiation_seed', 'isotope',
            'source_contract_id', 'source_pdg', 'source_position_mm', 'drift_dt_ns',
            'field_precision_bits', 'ionisation_energy_eV')
    return {key: source[key] for key in keys if key in source}


def reference_from_run(report_path, database_path=None):
    """Measure exact compressed BLOB/page costs; do not modify or replay the run."""
    report_path = Path(report_path)
    report = json.loads(report_path.read_text(encoding='utf-8-sig'))
    if report.get('kind') != 'gegi_candidate_acquisition_v1' or report.get('status') != 'completed':
        raise ValueError('Use a completed candidate acquisition report')
    database_path = Path(database_path) if database_path else report_path.with_name('compton-candidates.sqlite')
    artifact = report['artifacts']['compton-candidates.sqlite']
    if database_path.stat().st_size != artifact['bytes'] or sha(database_path) != artifact['sha256']:
        raise ValueError('Candidate archive differs from the completed report')
    group_artifact = report['artifacts'].get('input-groups.jsonl.gz')
    group_bytes = group_fixed = group_rows = 0
    if group_artifact is not None:
        ledger = report_path.with_name('input-groups.jsonl.gz')
        if ledger.stat().st_size != group_artifact['bytes'] or sha(ledger) != group_artifact['sha256']:
            raise ValueError('Input-group identity ledger differs from the completed report')
        packed = ledger.read_bytes(); header = 10; flags = packed[3]
        if flags & 4:
            extra = int.from_bytes(packed[header:header+2], 'little'); header += 2+extra
        for flag in (8, 16):
            if flags & flag: header = packed.index(0, header)+1
        if flags & 2: header += 2
        group_bytes, group_fixed = len(packed), header+8
        group_rows = len(gzip.decompress(packed).splitlines())
    with closing(sqlite3.connect(database_path.resolve().as_uri()+'?mode=ro', uri=True)) as db:
        metadata = json.loads(db.execute('SELECT body FROM metadata WHERE singleton=1').fetchone()[0])
        completion_row = db.execute('SELECT body FROM completion WHERE singleton=1').fetchone()
        if completion_row is None: raise ValueError('Candidate archive has no completion record')
        completion = json.loads(completion_row[0])
        sizes = {decision: {'count': count, 'compressed_record_bytes': records, 'compressed_adc_bytes': adc}
                 for decision, count, records, adc in db.execute(
                     'SELECT decision,count(*),sum(length(record)),sum(coalesce(length(adc_codes),0)) '
                     'FROM triggers GROUP BY decision')}
        page_size = db.execute('PRAGMA page_size').fetchone()[0]
        page_count = db.execute('PRAGMA page_count').fetchone()[0]
        freelist = db.execute('PRAGMA freelist_count').fetchone()[0]
        try:
            pages = {name: {'pages': count, 'allocated_bytes': size, 'payload_bytes': payload, 'unused_bytes': unused}
                     for name, count, size, payload, unused in db.execute(
                         'SELECT name,count(*),sum(pgsize),sum(payload),sum(unused) FROM dbstat GROUP BY name')}
        except sqlite3.OperationalError as error:
            raise ValueError('SQLite dbstat is required to separate measured event pages from fixed metadata') from error
        context_identity = None; uncompressed_adc = 0
        for body, adc_blob in db.execute("SELECT record,adc_codes FROM triggers WHERE decision='candidate'"):
            record = json.loads(zlib.decompress(body)); context = record['context']
            identity = {key: context[key] for key in ('digital_profile_sha256', 'digital_timing_sha256',
                        'readout_source_sha256', 'sample_period_ns', 'contact_ids')}
            if context_identity is not None and context_identity != identity:
                raise ValueError('Candidate contexts mix readout implementations or profiles')
            context_identity = identity
            uncompressed_adc += len(zlib.decompress(adc_blob))
    expected = report['storage_counts']
    if (sum(s['count'] for s in sizes.values()) != expected['observed_coincident_rises'] or
            sizes.get('candidate', {}).get('count', 0) != expected['saved_candidates'] or
            completion['saved_candidates'] != expected['saved_candidates']):
        raise ValueError('Candidate report and archive denominators differ')
    live_time = report['live_time_ns']; parents = report['source']['initial_parents']
    if not math.isfinite(live_time) or live_time <= 0 or type(parents) is not int or parents <= 0:
        raise ValueError('Reference requires positive acquisition time and parent denominator')
    excluded = _interval_duration(report['excluded_intervals_ns'], live_time)
    # The exclusion list is repeated in the report and completion JSON. Keep its
    # measured variable bytes separate from fixed configuration and histogram bins.
    interval_bytes = max(0, len(encoded(report['excluded_intervals_ns']))-2)
    if sum(p['allocated_bytes'] for p in pages.values())+freelist*page_size != database_path.stat().st_size:
        raise ValueError('SQLite page allocation does not close against archive bytes')
    compressed = sum(s['compressed_record_bytes']+s['compressed_adc_bytes'] for s in sizes.values())
    provenance = {'reference_report_sha256': sha(report_path), 'archive_sha256': artifact['sha256'],
                  'scope': report['identity'].get('scope'),
                  'sources': [_safe_source(source) for source in report['identity'].get('sources', [])],
                  'clock_seed': report['identity'].get('clock_seed'),
                  'noise_seed': report['identity'].get('noise_seed'),
                  'activities_bq': report['identity'].get('activities_bq'),
                  'readout': context_identity}
    if group_artifact is not None: provenance['input_group_ledger_sha256'] = group_artifact['sha256']
    return {'kind': KIND, 'provenance': provenance,
            'observation': {'initial_parents': parents, 'live_time_ns': live_time,
                            'excluded_time_ns': excluded, 'qualified_fraction': (live_time-excluded)/live_time,
                            'observed_coincident_rises': expected['observed_coincident_rises'],
                            'saved_candidates': expected['saved_candidates'],
                            'rejected_rises': expected['rejected_rises'],
                            'input_group_ledger_rows': group_rows,
                            'selection_reason_counts': expected['selection_reason_counts'],
                            'readout_elapsed_seconds': report['elapsed_seconds'],
                            'elapsed_use': 'Measured saved-source readout only; never extrapolated to fresh transport/drift runtime.'},
            'bytes': {'archive': database_path.stat().st_size, 'report': report_path.stat().st_size,
                      'by_decision': sizes, 'uncompressed_candidate_adc': uncompressed_adc,
                      'all_compressed_trigger_blobs': compressed,
                      'trigger_pages': pages['triggers']['allocated_bytes'],
                      'trigger_non_blob_bytes': pages['triggers']['allocated_bytes']-compressed,
                      'input_group_ledger': group_bytes, 'input_group_ledger_fixed': group_fixed,
                      'fixed_archive_pages': database_path.stat().st_size-pages['triggers']['allocated_bytes']-freelist*page_size,
                      'variable_exclusion_json_per_copy': interval_bytes,
                      'page_size': page_size, 'page_count': page_count, 'freelist_pages': freelist,
                      'page_tables': pages},
            'selection_policy': report['selection_policy'],
            'shared_field_cache_bytes': SHARED_FIELD_CACHE_BYTES,
            'assumptions': ['Same geometry, activities, readout, conservative selection and compression/record schema as the reference.',
                            'Ambiguous and multistrip candidates remain retained; candidate is not a uniquely reconstructed photon.',
                            'Event-dependent trigger pages, shared input-group ledger and exclusion-list bytes scale per original parent; fixed metadata/configuration is counted once.',
                            'The forecast covers the candidate/readout core. Additional fresh nonzero/delayed-daughter ledgers, source provenance, failures and retirement records are not measured by this historical reference.',
                            'SQLite page growth is estimated from measured allocation; the qualified-time-adjusted scenario divides event cost by the reference qualified fraction.',
                            'These are planning scenarios, not a confidence interval or guaranteed storage upper bound.']}


def load_reference(path=PACKAGED_REFERENCE):
    reference = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if reference.get('kind') != KIND: raise ValueError('Unsupported storage reference')
    return reference


def estimate(total_parents=20_000_000, activities_bq=(185000, 37000), reference=None, disk_budget_bytes=None):
    """Pure preflight: no simulation, allocation, deletion or duration-based timing fit."""
    if type(total_parents) is not int or total_parents <= 0:
        raise ValueError('Use a positive total parent count')
    if (len(activities_bq) != 2 or any(type(a) not in (int, float) or not math.isfinite(a) or a <= 0 for a in activities_bq)):
        raise ValueError('Use two finite positive activities in Bq')
    reference = load_reference() if reference is None else reference
    if reference.get('kind') != KIND: raise ValueError('Unsupported storage reference')
    expected_activities = reference['provenance'].get('activities_bq')
    if expected_activities is not None and list(activities_bq) != expected_activities:
        raise ValueError('Reference candidate yield is specific to its two activity settings; measure a matching reference')
    observation, cost = reference['observation'], reference['bytes']
    if observation['saved_candidates'] <= 0:
        raise ValueError('A zero-candidate pilot cannot estimate candidate yield; use a representative format reference')
    qualified = observation['qualified_fraction']
    if not 0 < qualified <= 1: raise ValueError('A usable reference needs positive qualified time')
    scale = total_parents/observation['initial_parents']
    intervals = cost['variable_exclusion_json_per_copy']
    fixed_db = cost['fixed_archive_pages']-intervals
    fixed_report = cost['report']-intervals
    event_db = cost['trigger_pages']+intervals
    fixed_groups = cost.get('input_group_ledger_fixed', 0)
    event_groups = cost.get('input_group_ledger', 0)-fixed_groups
    scenarios = {}
    for name, factor in (('as_observed', 1.), ('qualified_time_adjusted', 1./qualified)):
        event_scale = scale*factor
        archive = math.ceil((fixed_db+event_db*event_scale)/cost['page_size'])*cost['page_size']
        report = math.ceil(fixed_report+intervals*event_scale)
        groups = math.ceil(fixed_groups+event_groups*event_scale)
        scenarios[name] = {'candidate_core_bytes': archive+report+groups,
                           'final_output_bytes': archive+report+groups, 'candidate_archive_bytes': archive,
                           'run_summary_config_bytes': report,
                           'shared_input_group_ledger_bytes': groups,
                           'expected_candidates': observation['saved_candidates']*event_scale,
                           'expected_trigger_ledger_rows': observation['observed_coincident_rises']*event_scale,
                           'event_scale': event_scale}
    bounds = [scenarios['as_observed']['final_output_bytes'], scenarios['qualified_time_adjusted']['final_output_bytes']]
    result = {'kind': 'gegi_candidate_storage_estimate_v1', 'total_parents': total_parents,
              'activities_bq': list(activities_bq),
              'expected_duration_s': total_parents/math.fsum(activities_bq),
              'reference_parent_count': observation['initial_parents'],
              'reference_qualified_fraction': qualified, 'parent_scale': scale,
              'formula': 'event_scale=N_target/N_reference; adjusted scenario event_scale /= qualified_fraction; final=page_round(fixed_archive+event_archive*event_scale)+fixed_report+excluded_interval_bytes*event_scale+fixed_group_header+group_ledger_payload*event_scale',
              'scenarios': scenarios, 'planning_range_bytes': bounds,
              'estimated_output_scope': 'Candidate archive, shared input-group joins and readout summary/configuration only; final_output_bytes names this core, not the whole fresh run.',
              'additional_retained_fresh_data': {'status': 'not_estimated',
                  'scope': 'Nonzero parent/deposit identity and late-daughter ledgers, source geometry/configuration/logs, unique native failures and scratch-retirement inventory remain necessary and separately retained.'},
              'shared_field_cache_bytes': reference['shared_field_cache_bytes'],
              'runtime_scratch': {'status': 'not_estimated_from_this_readout_reference',
                  'scope': 'Bounded transport/deposit/drift inputs, pending daughters, current buffers, checkpoints and SQLite journals are separate from final retained candidates.',
                  'production_ready': False},
              'provenance': reference['provenance'], 'assumptions': reference['assumptions'],
              'runtime_prediction': None,
              'scope': 'Candidate-core storage planning only; full fresh final retention and peak disk are not certified. 20M fresh parents and continuous production are not tested or launched by this estimate.'}
    if disk_budget_bytes is not None:
        if type(disk_budget_bytes) is not int or disk_budget_bytes <= 0:
            raise ValueError('Use a positive disk budget in bytes')
        needed = bounds[1]+reference['shared_field_cache_bytes']
        result['disk_budget'] = {'bytes': disk_budget_bytes, 'final_upper_scenario_plus_shared_fields_bytes': needed,
            'remaining_before_unestimated_scratch_bytes': disk_budget_bytes-needed,
            'status': 'final_and_shared_fit_scratch_unbudgeted' if disk_budget_bytes >= needed else 'insufficient_for_final_and_shared',
            'shared_field_policy': 'Count once if this budget also needs to hold the existing shared field cache; do not duplicate it per run.'}
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parents', type=int, default=20_000_000)
    parser.add_argument('--reference', type=Path)
    parser.add_argument('--report', type=Path, help='Measure a new completed reference without rerunning physics')
    parser.add_argument('--database', type=Path)
    parser.add_argument('--write-reference', type=Path)
    parser.add_argument('--disk-budget-gib', type=float)
    args = parser.parse_args(argv)
    if args.reference and args.report: parser.error('Choose a packaged reference or completed report')
    reference = reference_from_run(args.report, args.database) if args.report else load_reference(args.reference or PACKAGED_REFERENCE)
    if args.write_reference:
        with args.write_reference.open('xb') as out: out.write(json.dumps(reference, indent=2, sort_keys=True).encode('utf-8')+b'\n')
    budget = None if args.disk_budget_gib is None else round(args.disk_budget_gib*1024**3)
    print(json.dumps(estimate(args.parents, reference=reference, disk_budget_bytes=budget), sort_keys=True, allow_nan=False))


if __name__ == '__main__': main()
