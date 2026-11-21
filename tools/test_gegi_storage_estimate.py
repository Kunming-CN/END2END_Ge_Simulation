from contextlib import closing
import copy
import gzip
import json
import math
import re
from pathlib import Path
import sqlite3
import tempfile
import unittest
import zlib
from unittest.mock import patch

import gegi_storage_estimate as E


class StorageEstimateTests(unittest.TestCase):
    def fixture(self, root):
        database = root/'compton-candidates.sqlite'
        with closing(sqlite3.connect(database)) as db, db:
            db.executescript('CREATE TABLE metadata(singleton INTEGER PRIMARY KEY,body BLOB);'
                             'CREATE TABLE completion(singleton INTEGER PRIMARY KEY,body BLOB);'
                             'CREATE TABLE triggers(trigger_id INTEGER PRIMARY KEY,decision TEXT,record BLOB,adc_codes BLOB);')
            db.execute('INSERT INTO metadata VALUES(1,?)', (E.encoded({'kind': 'fixture'}),))
            db.execute('INSERT INTO completion VALUES(1,?)', (E.encoded({'saved_candidates': 1}),))
            context = {'digital_profile_sha256': 'profile', 'digital_timing_sha256': 'timing',
                       'readout_source_sha256': {'reader': 'sha'}, 'sample_period_ns': 20, 'contact_ids': [1]}
            db.execute('INSERT INTO triggers VALUES(1,?,?,?)', ('candidate',
                       zlib.compress(E.encoded({'context': context})), zlib.compress(b'\0\0\1\0')))
            db.execute('INSERT INTO triggers VALUES(2,?,?,NULL)', ('rejected', zlib.compress(b'{"reason":"single"}')))
        groups = root/'input-groups.jsonl.gz'
        groups.write_bytes(gzip.compress(b'{"input_group_ordinal":1}\n', mtime=0))
        report = {'kind': 'gegi_candidate_acquisition_v1', 'status': 'completed',
                  'artifacts': {p.name: {'bytes': p.stat().st_size, 'sha256': E.sha(p)} for p in (database, groups)},
                  'storage_counts': {'observed_coincident_rises': 2, 'saved_candidates': 1,
                                     'rejected_rises': 1, 'selection_reason_counts': {'candidate': 1, 'single': 1}},
                  'live_time_ns': 100., 'excluded_intervals_ns': [[0, 20], [10, 25]],
                  'source': {'initial_parents': 10}, 'elapsed_seconds': .5,
                  'identity': {'activities_bq': [185000, 37000], 'sources': [
                      {'chunk_index': 45, 'chunk_sha256': 'sha', 'private_path': 'C:/private/path'}]},
                  'selection_policy': {'ambiguity': 'keep'}}
        target = root/'candidate-acquisition.json'; target.write_bytes(E.encoded(report)+b'\n')
        return target, report

    def fresh_fixture(self, root):
        target, report = self.fixture(root)
        database = root/'compton-candidates.sqlite'
        with closing(sqlite3.connect(database)) as db, db:
            db.executescript('CREATE TABLE input_groups(ordinal INTEGER PRIMARY KEY,parent INTEGER,group_id INTEGER,status TEXT,metadata BLOB,UNIQUE(parent,group_id));'
                             'CREATE INDEX pending_time ON input_groups(status,ordinal);'
                             'CREATE INDEX group_time ON input_groups(ordinal);'
                             'CREATE INDEX trigger_decision ON triggers(decision);'
                             'CREATE TABLE source_blocks(block_index INTEGER PRIMARY KEY,manifest BLOB);'
                             'CREATE TABLE native_failures(ordinal INTEGER PRIMARY KEY,record BLOB);'
                             'CREATE TABLE native_processing_phases(ordinal INTEGER PRIMARY KEY,phase INTEGER);'
                             'CREATE TABLE checkpoint(singleton INTEGER PRIMARY KEY,state BLOB);')
            for i in range(30):
                db.execute('INSERT INTO input_groups VALUES(?,?,?,?,?)',
                           (i+1,i//2+1,i%2,'completed',E.encoded({'raw_row_indices':list(range(200))})))
                db.execute('INSERT INTO native_processing_phases VALUES(?,2)',(i+1,))
            db.execute('INSERT INTO source_blocks VALUES(0,?)',(E.encoded({'source_census':'fixture'*800}),))
            db.execute('INSERT INTO native_failures VALUES(1,?)',(zlib.compress(b'preserved native failure fixture'),))
            db.execute('UPDATE completion SET body=?',(E.encoded({'saved_candidates':1,'acquisition_statistics':{
                'excluded_intervals_ns':report['excluded_intervals_ns']}}),))
            db.execute('INSERT INTO checkpoint VALUES(1,?)',(E.encoded({
                'excluded_intervals_ns':report['excluded_intervals_ns'],
                'missing_history':{'excluded_intervals_ns':[[10,25]]},
                'readout':{'settings':{'noise_seed':120261120}}}),))
            # Freed overflow pages belong to the measured physical archive;
            # they must not disappear from a reference-sized forecast.
            db.execute('CREATE TABLE disposable(value BLOB)')
            db.execute('INSERT INTO disposable VALUES(?)',(b'x'*100000,))
            db.execute('DROP TABLE disposable')
        groups=root/'input-groups.jsonl.gz'
        groups.write_bytes(gzip.compress(b''.join(E.encoded({'input_group_ordinal':i+1})+b'\n' for i in range(30)),mtime=0))
        report.pop('elapsed_seconds')
        report['identity']={'kind':'gegi_streaming_acquisition_v1','scope':'Fresh shared-clock fixture',
            'source_config':{'kind':'gegi_streaming_source_config_v1','seed':20261120,'clock_seed':20261120,
                'stop':{'mode':'duration','duration_ns':100.},
                'initial_state':{'policy':'secular_equilibrium_poisson_daughters_v1','acquisition_start_ns':0},
                'sources':[{'id':'cs137_point_decay_v1','activity_Bq':185000,'position_global_mm':[-40,0,40],
                            'private_path':'C:/private/input'},
                           {'id':'co60_point_decay_v1','activity_Bq':37000,'position_global_mm':[40,0,40]}]}}
        report['source'].update(initial_daughter_decays=7,transport_primaries=17,deposit_groups=30)
        report['source_initial_state']={'policy':'secular_equilibrium_poisson_daughters_v1','inventory_seed':3}
        report['resources']={'active_elapsed_seconds':999.}
        report['stage_timings']={'unit':'seconds','stages':{
            'native_group':{'count':30,'total_seconds':40.},'readout':{'count':30,'total_seconds':1.25}}}
        report['stage_timing_baselines_by_native_phase']={'2':{'readout_total_seconds':.5}}
        report['first_native_group_seconds_per_session']=[3.5,2.75]
        report['artifacts']={p.name:{'bytes':p.stat().st_size,'sha256':E.sha(p)} for p in (database,groups)}
        target.write_bytes(E.encoded(report)+b'\n')
        return target,report

    def test_fresh_report_preserves_source_settings_and_measured_stage_times(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path,report=self.fresh_fixture(root)
            reference=E.reference_from_run(path)
            self.assertEqual(reference['provenance']['activities_bq'],[185000,37000])
            self.assertEqual(reference['provenance']['sources'][0]['position_global_mm'],[-40,0,40])
            self.assertEqual(reference['provenance']['clock_seed'],20261120)
            self.assertEqual(reference['provenance']['noise_seed'],120261120)
            self.assertNotIn('C:/private',json.dumps(reference))
            self.assertEqual(reference['observation']['readout_elapsed_seconds'],1.25)
            self.assertEqual(reference['observation']['stage_timings'],report['stage_timings'])
            self.assertEqual(reference['observation']['stage_timing_baselines_by_native_phase'],report['stage_timing_baselines_by_native_phase'])
            self.assertEqual(reference['observation']['first_native_group_seconds_per_session'],[3.5,2.75])
            report.pop('stage_timings');path.write_bytes(E.encoded(report))
            self.assertIsNone(E.reference_from_run(path)['observation']['readout_elapsed_seconds'])

    def test_fresh_event_tables_indexes_and_exclusion_copies_scale_per_new_parent(self):
        with tempfile.TemporaryDirectory() as temp:
            path,report=self.fresh_fixture(Path(temp));reference=E.reference_from_run(path)
            cost=reference['bytes'];classes=cost['page_object_classification']
            for name in ('input_groups','source_blocks','native_failures','native_processing_phases',
                         'pending_time','group_time','sqlite_autoindex_input_groups_1','trigger_decision'):
                self.assertEqual(classes[name]['class'],'event',name)
            self.assertEqual(classes['pending_time']['table'],'input_groups')
            self.assertEqual(classes['checkpoint']['class'],'fixed_metadata')
            self.assertGreater(cost['event_auxiliary_pages'],0)
            self.assertEqual(cost['fixed_archive_pages']+cost['event_archive_pages']+cost['freelist_reserved_bytes'],cost['archive'])
            self.assertGreater(cost['freelist_reserved_bytes'],0)
            self.assertEqual(cost['variable_archive_json_bytes'],
                             2*cost['variable_exclusion_json_per_copy']+len(E.encoded([[10,25]]))-2)
            same=E.estimate(10,reference=reference)['scenarios']['as_observed']
            value=E.estimate(20,reference=reference);twice=value['scenarios']['as_observed']
            self.assertEqual(same['candidate_archive_bytes'],cost['archive'])
            self.assertEqual(value['parent_scale'],2.)
            self.assertEqual(value['reference_parent_count'],10)
            self.assertEqual(reference['observation']['initial_daughter_decays'],7)
            self.assertEqual(reference['observation']['transport_primaries'],17)
            self.assertEqual(twice['scaled_event_auxiliary_bytes'],2*cost['event_auxiliary_pages'])
            expected=math.ceil((cost['archive']+cost['event_archive_pages']+cost['variable_archive_json_bytes'])/cost['page_size'])*cost['page_size']
            self.assertEqual(twice['candidate_archive_bytes'],expected)
            self.assertEqual(twice['expected_candidates'],2.)
            self.assertEqual(value['additional_retained_fresh_data']['status'],'not_estimated')

    def test_packaged_fresh_whole_run_denominator_and_shared_costs(self):
        reference=E.load_reference();n=reference['observation']['initial_parents']
        self.assertEqual(n,1109875)
        self.assertEqual(reference['observation']['initial_daughter_decays'],867305)
        self.assertEqual(reference['observation']['transport_primaries'],1977180)
        self.assertEqual(reference['observation']['actual_new_parents_by_isotope']['co60_point_decay_v1']['parents'],185199)
        same=E.estimate(n,reference=reference)
        twice=E.estimate(2*n,reference=reference)
        row=same['whole_retained_scenarios']['as_observed'];double=twice['whole_retained_scenarios']['as_observed']
        self.assertEqual(row['run_retained_bytes'],819359442)
        self.assertEqual(row['run_plus_cache_and_existing_evidence_bytes'],1681267223)
        self.assertEqual(double['fixed_run_preservation_bytes'],row['fixed_run_preservation_bytes'])
        self.assertEqual(double['shared_field_cache_once_bytes'],857068900)
        self.assertEqual(double['existing_external_evidence_once_bytes'],4838881)
        self.assertEqual(double['scaled_external_event_records_bytes'],2*row['scaled_external_event_records_bytes'])
        self.assertEqual(twice['parent_scale'],2.)
        self.assertEqual(same['measured_reference_resources'],twice['measured_reference_resources'])
        self.assertEqual(same['measured_reference_resources']['run_logical_bytes_peak'],1019254940)
        self.assertEqual(same['runtime_scratch']['status'],'measured_reference_only_future_peak_unbounded')
        self.assertIsNone(same['runtime_scratch']['future_peak_disk_bytes'])
        broken=copy.deepcopy(reference);broken['whole_run_basis']['new_parent_count']=1977180
        with self.assertRaisesRegex(ValueError,'denominator'):
            E.estimate(n,reference=broken)

    def test_fresh_time_uses_active_wall_with_one_load_and_no_nested_double_count(self):
        reference=E.load_reference();n=reference['observation']['initial_parents']
        same=E.estimate(n,reference=reference);twice=E.estimate(2*n,reference=reference)
        time=same['runtime_prediction'];double=twice['runtime_prediction'];basis=reference['whole_run_basis']['time']
        self.assertEqual(time['scenarios_seconds']['observed_active_rate'],24595.746192)
        self.assertEqual(double['scenarios_seconds']['observed_active_rate'],2*24595.746192)
        loads=basis['native_worker_load'];fixed_load=loads['total_seconds']/loads['count']
        expected=2*(basis['active_elapsed_seconds']-loads['total_seconds'])+fixed_load
        self.assertEqual(double['scenarios_seconds']['one_native_load_adjusted'],expected)
        changed=copy.deepcopy(reference)
        changed['whole_run_basis']['time']['nested_transport_run_seconds']=99999999.
        self.assertEqual(E.estimate(n,reference=changed)['runtime_prediction'],time)
        self.assertEqual(time['planning_range_seconds'],[min(time['scenarios_seconds'].values()),max(time['scenarios_seconds'].values())])

    def test_analysis_derivative_and_optional_shared_calibration_are_separate(self):
        reference=E.load_reference();n=reference['observation']['initial_parents']
        same=E.estimate(n,reference=reference);twice=E.estimate(2*n,reference=reference)
        acquisition=same['whole_retained_scenarios']['as_observed'];pipeline=same['complete_pipeline_scenarios']['as_observed']
        double=twice['complete_pipeline_scenarios']['as_observed']
        self.assertEqual(acquisition['run_retained_bytes'],819359442)
        self.assertEqual(pipeline['analysis_derivative_bytes'],1901334)
        self.assertEqual(pipeline['run_retained_bytes'],819359442+1901334)
        self.assertEqual(pipeline['run_plus_cache_calibration_and_evidence_bytes'],1681267223+1901334+303891603)
        self.assertEqual(double['analysis_derivative_bytes'],2*1901334)
        self.assertEqual(double['shared_calibration_once_bytes'],303891603)
        self.assertEqual(pipeline['shared_field_cache_once_bytes'],857068900)
        self.assertEqual(pipeline['analysis_processing_seconds'],229.959389909)
        budget=E.estimate(n,reference=reference,disk_budget_bytes=100*1024**3)
        self.assertEqual(budget['disk_budget']['final_upper_scenario_plus_shared_fields_bytes'],budget['complete_pipeline_with_shared_planning_range_bytes'][1])
        self.assertEqual(budget['disk_budget']['basis'],'complete_pipeline_with_optional_shared_calibration')
        self.assertEqual(same['analysis_extension']['reference_process_peak_resident_bytes'],551071744)
        self.assertIsNone(same['runtime_scratch']['future_peak_resident_bytes'])

    def test_packaged_reference_is_public_settings_and_measurements_only(self):
        text=E.PACKAGED_REFERENCE.read_text(encoding='utf-8');reference=json.loads(text)
        self.assertIsNone(re.search(r'[A-Za-z]:[\\/]|/mnt/[a-z]/|/home/[^/\s]+|file://|My Drive|/Users/',text))
        self.assertNotIn('input_steps',text)
        self.assertNotIn('raw_row_indices',text)
        self.assertNotIn('adc_codes',text)
        self.assertEqual(reference['provenance']['sources'][0]['position_global_mm'],[-40,0,40])
        self.assertEqual(reference['provenance']['sources'][1]['position_global_mm'],[40,0,40])
        self.assertEqual(reference['analysis_extension_basis']['input_report_sha256'],reference['provenance']['reference_report_sha256'])

    def test_group_ledger_is_counted_without_whole_gzip_decompression(self):
        with tempfile.TemporaryDirectory() as temp:
            path,_=self.fresh_fixture(Path(temp))
            with patch.object(gzip,'decompress',side_effect=AssertionError('whole gzip decompression forbidden')):
                reference=E.reference_from_run(path)
            self.assertEqual(reference['observation']['input_group_ledger_rows'],30)

    def test_fresh_parent_and_initial_daughter_census_must_close(self):
        with tempfile.TemporaryDirectory() as temp:
            path,report=self.fresh_fixture(Path(temp))
            report['source']['transport_primaries']=18
            path.write_bytes(E.encoded(report))
            with self.assertRaisesRegex(ValueError,'denominators do not close'):
                E.reference_from_run(path)

    def test_exact_byte_measurement_and_public_provenance(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); path, report = self.fixture(root)
            reference = E.reference_from_run(path)
            self.assertEqual(reference['observation']['qualified_fraction'], .75)
            self.assertEqual(reference['bytes']['uncompressed_candidate_adc'], 4)
            self.assertEqual(reference['bytes']['input_group_ledger'], report['artifacts']['input-groups.jsonl.gz']['bytes'])
            self.assertEqual(reference['observation']['input_group_ledger_rows'], 1)
            self.assertNotIn('private_path', json.dumps(reference))
            blobs = reference['bytes']['all_compressed_trigger_blobs']
            self.assertGreater(reference['bytes']['trigger_pages'], blobs)
            self.assertEqual(reference['bytes']['fixed_archive_pages']+reference['bytes']['trigger_pages'],
                             report['artifacts']['compton-candidates.sqlite']['bytes'])

    def test_scenarios_scale_variable_cost_but_keep_configuration_once(self):
        with tempfile.TemporaryDirectory() as temp:
            reference = E.reference_from_run(self.fixture(Path(temp))[0])
            value = E.estimate(10, reference=reference)
            observed = value['scenarios']['as_observed']
            self.assertEqual(observed['candidate_archive_bytes'], reference['bytes']['archive'])
            self.assertEqual(observed['run_summary_config_bytes'], reference['bytes']['report'])
            self.assertEqual(observed['shared_input_group_ledger_bytes'], reference['bytes']['input_group_ledger'])
            self.assertGreater(value['planning_range_bytes'][1], value['planning_range_bytes'][0])
            self.assertIsNone(value['runtime_prediction'])
            self.assertIsNone(value['runtime_scratch']['future_peak_disk_bytes'])
            self.assertIsNone(value['runtime_scratch']['future_peak_resident_bytes'])

    def test_budget_does_not_pretend_to_bound_unmeasured_scratch(self):
        value = E.estimate(disk_budget_bytes=100*1024**3)
        self.assertEqual(value['disk_budget']['status'], 'final_and_shared_fit_scratch_unbudgeted')
        self.assertEqual(E.estimate(disk_budget_bytes=1)['disk_budget']['status'], 'insufficient_for_final_and_shared')
        self.assertAlmostEqual(value['expected_duration_s'], 20_000_000/222000)

    def test_no_silent_activity_transfer_or_changed_artifact(self):
        with self.assertRaises(ValueError): E.estimate(activities_bq=(37000, 37000))
        with tempfile.TemporaryDirectory() as temp:
            path, _ = self.fixture(Path(temp))
            with path.with_name('compton-candidates.sqlite').open('ab') as out: out.write(b'changed')
            with self.assertRaisesRegex(ValueError, 'differs'): E.reference_from_run(path)

    def test_zero_candidate_pilot_cannot_supply_a_zero_storage_forecast(self):
        reference = E.load_reference()
        reference['observation']['saved_candidates'] = 0
        with self.assertRaisesRegex(ValueError, 'zero-candidate'): E.estimate(reference=reference)


if __name__ == '__main__': unittest.main()
