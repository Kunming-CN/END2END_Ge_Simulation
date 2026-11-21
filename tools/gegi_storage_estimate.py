"""Plan storage and conditional work rates from measured completed references.

Historical format references remain supported. A measured fresh acquisition can
also supply whole-retained and optional offline-analysis costs. These scenarios
do not certify future daughter mix, runtime, peak resources or detector accuracy.
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
EVENT_TABLES = {'triggers', 'input_groups', 'source_blocks', 'native_failures', 'native_processing_phases'}
FIXED_TABLES = {'sqlite_schema', 'sqlite_master', 'metadata', 'completion', 'checkpoint'}


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
            'field_precision_bits', 'ionisation_energy_eV', 'id', 'activity_Bq', 'position_global_mm')
    return {key: source[key] for key in keys if key in source}


def _group_ledger_size(path):
    """Count gzip rows incrementally, retaining its one-member envelope cost."""
    with Path(path).open('rb') as stream:
        header = stream.read(10)
        if len(header) != 10 or header[:3] != b'\x1f\x8b\x08':
            raise ValueError('Invalid input-group gzip header')
        flags, size = header[3], 10
        if flags & 4:
            extra = stream.read(2)
            if len(extra) != 2: raise ValueError('Truncated input-group gzip header')
            count = int.from_bytes(extra, 'little')
            if len(stream.read(count)) != count: raise ValueError('Truncated input-group gzip header')
            size += 2+count
        for flag in (8, 16):
            if flags & flag:
                while True:
                    byte = stream.read(1)
                    if not byte: raise ValueError('Truncated input-group gzip header')
                    size += 1
                    if byte == b'\0': break
        if flags & 2:
            if len(stream.read(2)) != 2: raise ValueError('Truncated input-group gzip header')
            size += 2
    with gzip.open(path, 'rb') as stream:
        rows = sum(1 for _ in stream)
    return Path(path).stat().st_size, size+8, rows


def _page_classes(db, pages):
    """Indexes grow with their owning event table, including SQLite autoindexes."""
    owners = {name: table for name, table in db.execute(
        "SELECT name,tbl_name FROM sqlite_schema WHERE type IN ('table','index')")}
    result = {}
    for name in pages:
        owner = owners.get(name, name)
        if owner in EVENT_TABLES: category = 'event'
        elif owner in FIXED_TABLES: category = 'fixed_metadata'
        else: raise ValueError('Unclassified candidate archive page object: '+name)
        result[name] = {'table': owner, 'class': category}
    return result


def _variable_intervals(value):
    return max(0, len(encoded(value))-2) if isinstance(value, list) else 0


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
        group_bytes, group_fixed, group_rows = _group_ledger_size(ledger)
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
        classes = _page_classes(db, pages)
        event_pages = sum(pages[name]['allocated_bytes'] for name, row in classes.items() if row['class'] == 'event')
        checkpoint = {}
        if 'checkpoint' in pages:
            row = db.execute('SELECT state FROM checkpoint WHERE singleton=1').fetchone()
            if row is not None: checkpoint = json.loads(row[0])
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
    daughters, roots = report['source'].get('initial_daughter_decays'), report['source'].get('transport_primaries')
    invalid_roots = roots is not None and (type(roots) is not int or roots < parents)
    invalid_daughters = daughters is not None and (type(daughters) is not int or daughters < 0 or
                                                  (roots is not None and roots != parents+daughters))
    if invalid_roots or invalid_daughters:
        raise ValueError('New-parent and initial-daughter denominators do not close')
    excluded = _interval_duration(report['excluded_intervals_ns'], live_time)
    # The exclusion list is repeated in the report and completion JSON. Keep its
    # measured variable bytes separate from fixed configuration and histogram bins.
    interval_bytes = max(0, len(encoded(report['excluded_intervals_ns']))-2)
    archive_intervals = sum(_variable_intervals(value) for value in (
        completion.get('acquisition_statistics', {}).get('excluded_intervals_ns'),
        checkpoint.get('excluded_intervals_ns'),
        (checkpoint.get('missing_history') or {}).get('excluded_intervals_ns')))
    if sum(p['allocated_bytes'] for p in pages.values())+freelist*page_size != database_path.stat().st_size:
        raise ValueError('SQLite page allocation does not close against archive bytes')
    compressed = sum(s['compressed_record_bytes']+s['compressed_adc_bytes'] for s in sizes.values())
    identity = report['identity']; config = identity.get('source_config')
    sources = config['sources'] if config is not None else identity.get('sources', [])
    activities = [source['activity_Bq'] for source in sources] if config is not None else identity.get('activities_bq')
    provenance = {'reference_report_sha256': sha(report_path), 'archive_sha256': artifact['sha256'],
                  'scope': report['identity'].get('scope'),
                  'sources': [_safe_source(source) for source in sources],
                  'clock_seed': config.get('clock_seed') if config is not None else identity.get('clock_seed'),
                  'noise_seed': identity.get('noise_seed', (checkpoint.get('readout') or {}).get('settings', {}).get('noise_seed')),
                  'activities_bq': activities,
                  'readout': context_identity}
    if config is not None:
        provenance['source_config_sha256'] = hashlib.sha256(encoded(config)).hexdigest()
        provenance['source_config'] = {key: config[key] for key in ('kind','seed','clock_seed','stop') if key in config}
        provenance['source_config']['sources'] = [_safe_source(source) for source in sources]
        provenance['source_config']['initial_state'] = {key: config['initial_state'][key] for key in (
            'policy','acquisition_start_ns','initial_daughter_populations','pre_acquisition_history','scope') if key in config.get('initial_state', {})}
        provenance['producer_identity_sha256'] = hashlib.sha256(encoded(identity)).hexdigest()
        if 'source_initial_state' in report:
            provenance['source_initial_state_sha256'] = hashlib.sha256(encoded(report['source_initial_state'])).hexdigest()
    stages = report.get('stage_timings')
    readout_elapsed = ((stages or {}).get('stages', {}).get('readout', {}).get('total_seconds')
                       if config is not None else report.get('elapsed_seconds'))
    if group_artifact is not None: provenance['input_group_ledger_sha256'] = group_artifact['sha256']
    return {'kind': KIND, 'provenance': provenance,
            'observation': {'initial_parents': parents, 'live_time_ns': live_time,
                            'initial_daughter_decays': daughters, 'transport_primaries': roots,
                            'parent_denominator': 'New source parents; initial daughters are counted separately.',
                            'excluded_time_ns': excluded, 'qualified_fraction': (live_time-excluded)/live_time,
                            'observed_coincident_rises': expected['observed_coincident_rises'],
                            'saved_candidates': expected['saved_candidates'],
                            'rejected_rises': expected['rejected_rises'],
                            'input_group_ledger_rows': group_rows,
                            'selection_reason_counts': expected['selection_reason_counts'],
                            'readout_elapsed_seconds': readout_elapsed,
                            'stage_timings': stages,
                            'stage_timing_baselines_by_native_phase': report.get('stage_timing_baselines_by_native_phase'),
                            'first_native_group_seconds_per_session': report.get('first_native_group_seconds_per_session'),
                            'elapsed_use': ('Fresh measured stage totals are retained, may overlap, and are never extrapolated. Readout time uses only the recorded readout stage, never full active elapsed.'
                                            if config is not None else 'Measured saved-source acquisition/readout/archive processing; never extrapolated to fresh transport/drift runtime.')},
            'bytes': {'archive': database_path.stat().st_size, 'report': report_path.stat().st_size,
                      'by_decision': sizes, 'uncompressed_candidate_adc': uncompressed_adc,
                      'all_compressed_trigger_blobs': compressed,
                      'trigger_pages': pages['triggers']['allocated_bytes'],
                      'event_archive_pages': event_pages,
                      'event_auxiliary_pages': event_pages-pages['triggers']['allocated_bytes'],
                      'trigger_non_blob_bytes': pages['triggers']['allocated_bytes']-compressed,
                      'input_group_ledger': group_bytes, 'input_group_ledger_fixed': group_fixed,
                      'fixed_archive_pages': database_path.stat().st_size-event_pages-freelist*page_size,
                      'freelist_reserved_bytes': freelist*page_size,
                      'variable_exclusion_json_per_copy': interval_bytes,
                      'variable_archive_json_bytes': archive_intervals,
                      'variable_report_json_bytes': interval_bytes,
                      'page_size': page_size, 'page_count': page_count, 'freelist_pages': freelist,
                      'page_tables': pages, 'page_object_classification': classes},
            'selection_policy': report['selection_policy'],
            'shared_field_cache_bytes': SHARED_FIELD_CACHE_BYTES,
            'assumptions': ['Same geometry, activities, readout, conservative selection and compression/record schema as the reference.',
                            'Ambiguous and multistrip candidates remain retained; candidate is not a uniquely reconstructed photon.',
                            'Measured event-table/index pages, shared input-group ledger and serialized exclusion lists scale per new parent; bounded metadata/filter state is counted once.',
                            'Streaming input-group, source-block, native-failure and processing-phase tables/indexes are included when present. External run directories, producer/provenance archives, logs and retirement records remain additional.',
                            'Measured SQLite freelist pages are reserved once; future transient/free-page growth is unmeasured.',
                            'Daughter/group/failure rates per new parent assume the reference source-state mix; another duration does not independently solve its daughter inventory.',
                            'SQLite page growth is estimated from measured allocation; the qualified-time-adjusted scenario divides event cost by the reference qualified fraction.',
                            'These are planning scenarios, not a confidence interval or guaranteed storage upper bound.']}


def load_reference(path=PACKAGED_REFERENCE):
    reference = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if reference.get('kind') != KIND: raise ValueError('Unsupported storage reference')
    return reference


def estimate(total_parents=20_000_000, activities_bq=(185000, 37000), reference=None, disk_budget_bytes=None):
    """Pure planning from saved measurements; no simulation or execution gate."""
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
    intervals = cost.get('variable_report_json_bytes', cost['variable_exclusion_json_per_copy'])
    archive_intervals = cost.get('variable_archive_json_bytes', cost['variable_exclusion_json_per_copy'])
    event_pages = cost.get('event_archive_pages', cost['trigger_pages'])
    fixed_db = cost['fixed_archive_pages']+cost.get('freelist_reserved_bytes', cost.get('freelist_pages', 0)*cost['page_size'])-archive_intervals
    fixed_report = cost['report']-intervals
    event_db = event_pages+archive_intervals
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
                           'scaled_event_auxiliary_bytes': math.ceil(cost.get('event_auxiliary_pages', 0)*event_scale),
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
                  'scope': 'External run directories, native/producer archives, source geometry/configuration/logs and scratch-retirement inventory remain additional; event data already inside the measured candidate database and shared group ledger are included.'},
              'shared_field_cache_bytes': reference['shared_field_cache_bytes'],
              'runtime_scratch': {'status': 'not_estimated_from_this_readout_reference',
                  'future_peak_disk_bytes': None, 'future_peak_resident_bytes': None,
                  'scope': 'Bounded transport/deposit/drift inputs, pending daughters, current buffers, checkpoints and SQLite journals are separate from final retained candidates.'},
              'provenance': reference['provenance'], 'assumptions': reference['assumptions'],
              'runtime_prediction': None,
              'scope': 'Candidate-core storage planning only; full fresh final retention and peak disk are not certified. 20M fresh parents and continuous production are not tested or launched by this estimate.'}
    basis = reference.get('whole_run_basis')
    if basis is not None:
        retained, measured_time = basis['retained'], basis['time']
        if (basis['new_parent_count'] != observation['initial_parents'] or
                retained['candidate_core_bytes'] != cost['archive']+cost['report']+cost.get('input_group_ledger', 0) or
                retained['run_bytes'] != retained['candidate_core_bytes']+retained['variable_external_records_bytes']+retained['fixed_run_preservation_bytes']):
            raise ValueError('Measured whole-run new-parent denominator or retained costs do not close')
        whole = {}
        for name, scenario in scenarios.items():
            variable = math.ceil(retained['variable_external_records_bytes']*scenario['event_scale'])
            run_bytes = scenario['candidate_core_bytes']+variable+retained['fixed_run_preservation_bytes']
            whole[name] = {'candidate_core_bytes': scenario['candidate_core_bytes'],
                           'scaled_external_event_records_bytes': variable,
                           'fixed_run_preservation_bytes': retained['fixed_run_preservation_bytes'],
                           'run_retained_bytes': run_bytes,
                           'shared_field_cache_once_bytes': reference['shared_field_cache_bytes'],
                           'existing_external_evidence_once_bytes': retained['existing_external_evidence_once_bytes'],
                           'run_plus_cache_and_existing_evidence_bytes': run_bytes+reference['shared_field_cache_bytes']+retained['existing_external_evidence_once_bytes']}
        loads = measured_time['native_worker_load']
        segment = measured_time['phase3_bridge_segment']
        time_scenarios = {'observed_active_rate': measured_time['active_elapsed_seconds']*scale,
                          'one_native_load_adjusted': (measured_time['active_elapsed_seconds']-loads['total_seconds'])*scale+loads['total_seconds']/loads['count'],
                          'phase3_bridge_rate': segment['active_seconds']*total_parents/segment['new_parent_count']}
        result.update(whole_retained_scenarios=whole,
                      whole_retained_planning_range_bytes=[row['run_retained_bytes'] for row in whole.values()],
                      whole_retained_with_shared_planning_range_bytes=[row['run_plus_cache_and_existing_evidence_bytes'] for row in whole.values()],
                      measured_reference_resources={'live_time_ns': observation['live_time_ns'],
                          'new_parent_count': observation['initial_parents'], 'initial_daughter_decays': observation['initial_daughter_decays'],
                          'active_elapsed_seconds': measured_time['active_elapsed_seconds'], 'run_retained_bytes': retained['run_bytes'],
                          **basis['peaks'], 'runtime_scope': basis['runtime_scope']},
                      runtime_prediction={'status': 'conditional_measured_rate_scenarios',
                          'planning_range_seconds': [min(time_scenarios.values()), max(time_scenarios.values())],
                          'scenarios_seconds': time_scenarios,
                          'scope': 'Same-runtime measured work-rate scenarios, not a confidence interval or guarantee. One-load case counts a measured mean worker load once; other startup/JIT overhead remains. The phase-3 segment includes startup and possibly a failed-phase tail. Small runs need a separate startup-latency model. Nested transport_run is never added to transport_cli or active wall.'},
                      additional_retained_fresh_data={'status': 'measured_reference_rates_used',
                          'scope': 'Observed failure spools, transport block lineage and logs scale per new parent. Original prefix/repair evidence and one shared field cache are fixed once. Unmeasured analysis outputs and changed retention policies remain additional.'},
                      runtime_scratch={'status': 'measured_reference_only_future_peak_unbounded',
                          'measured_reference_run_peak_bytes': basis['peaks']['run_logical_bytes_peak'],
                          'future_peak_disk_bytes': None, 'future_peak_resident_bytes': None,
                          'scope': 'The saved five-second peak is measured, not extrapolated. Future scratch/journals, daughter mix, checkpoint growth and compute contention are not bounded.'},
                      scope='Conditional whole-retained and active-time planning from one measured five-second acquisition. Future daughter mix, peak resources, detector accuracy and production readiness are not certified; no larger run is launched.')
        analysis = reference.get('analysis_extension_basis')
        if analysis is not None:
            if analysis['new_parent_count'] != observation['initial_parents']:
                raise ValueError('Measured analysis new-parent denominator differs')
            pipeline = {}
            for name, row in whole.items():
                derivative = math.ceil(analysis['derivative_bytes']*scenarios[name]['event_scale'])
                pipeline[name] = {'acquisition_run_retained_bytes': row['run_retained_bytes'],
                                  'analysis_derivative_bytes': derivative,
                                  'run_retained_bytes': row['run_retained_bytes']+derivative,
                                  'shared_field_cache_once_bytes': reference['shared_field_cache_bytes'],
                                  'shared_calibration_once_bytes': analysis['shared_calibration_bytes'],
                                  'existing_external_evidence_once_bytes': retained['existing_external_evidence_once_bytes'],
                                  'run_plus_cache_calibration_and_evidence_bytes': row['run_plus_cache_and_existing_evidence_bytes']+derivative+analysis['shared_calibration_bytes'],
                                  'analysis_processing_seconds': analysis['processing_seconds']*scenarios[name]['event_scale']}
            result.update(analysis_extension={'status': 'measured_offline_analysis_extension',
                              'reference_derivative_bytes': analysis['derivative_bytes'],
                              'derivative_sha256': analysis['derivative_sha256'],
                              'reference_processing_seconds': analysis['processing_seconds'],
                              'processing_time_precision': analysis['processing_time_precision'],
                              'reference_process_peak_resident_bytes': analysis['process_peak_resident_bytes'],
                              'shared_calibration_once_bytes': analysis['shared_calibration_bytes'],
                              'scope': 'Optional offline imaging: derivative scales at the observed rate; its separate shared calibration is counted once. Acquisition baseline and its measured peak are unchanged.'},
                          complete_pipeline_scenarios=pipeline,
                          complete_pipeline_with_shared_planning_range_bytes=[row['run_plus_cache_calibration_and_evidence_bytes'] for row in pipeline.values()],
                          complete_pipeline_runtime_prediction={'status': 'conditional_measured_rate_scenarios',
                              'planning_range_seconds': [min(time_scenarios.values())+pipeline['as_observed']['analysis_processing_seconds'],
                                                         max(time_scenarios.values())+pipeline['qualified_time_adjusted']['analysis_processing_seconds']],
                              'scope': 'Sequential acquisition plus the measured offline-analysis rate. Analysis time is rounded; future peak RAM/disk and changed candidate yield are not bounded. Separate process peaks are not summed.'})
    if disk_budget_bytes is not None:
        if type(disk_budget_bytes) is not int or disk_budget_bytes <= 0:
            raise ValueError('Use a positive disk budget in bytes')
        needed = (result['complete_pipeline_with_shared_planning_range_bytes'][1] if 'complete_pipeline_scenarios' in result else
                  result['whole_retained_with_shared_planning_range_bytes'][1] if basis is not None else
                  bounds[1]+reference['shared_field_cache_bytes'])
        result['disk_budget'] = {'bytes': disk_budget_bytes, 'final_upper_scenario_plus_shared_fields_bytes': needed,
            'basis': 'complete_pipeline_with_optional_shared_calibration' if 'complete_pipeline_scenarios' in result else 'acquisition_with_shared_fields' if basis is not None else 'candidate_core_with_shared_fields',
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
