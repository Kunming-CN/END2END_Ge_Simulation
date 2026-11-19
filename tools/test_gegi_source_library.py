import gzip
import json
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

import gegi_event_store as store
import gegi_source_clock as research
import gegi_source_library as portable


def make_chunk(directory, name, position, *, compressed=True, calibration='a'*64, failed=False,
               model='b'*64, request_sha256=None, native_request=None):
    directory = Path(directory)
    pdg, digest = 1000110220, model
    sidecars = {}

    def write(ref, data):
        if isinstance(data, dict):
            data = store.encoded(data)
        path = directory/ref
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        sidecars[ref] = {'bytes': len(data), 'sha256': store.sha(data)}

    coordinate = {'rotation_local_to_global': [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                  'translation_global_mm': [0, 0, 0]}
    contract = {'id': 'na22_fixture_v1', 'pdg': pdg, 'particle': 'ion',
                'initial_nuclei_per_primary': 1, 'kinetic_energy_keV': 0, 'A': 22, 'Z': 11,
                'position_global_mm': position, 'clock_policy': portable._CLOCK,
                'time_ns': 0, 'count_unit': 'initial Na22 decays'}
    counts = {'initial_decays': 2, 'initial_primaries': 2, 'nonzero_primaries': 1,
              'zero_deposit_primaries': 1, 'nonzero_event_ids': [1], 'pulse_groups': 1, 'positive_ge_rows': 1}
    group = {'group_id': 0, 'origin_time_ns': 42., 'last_deposit_time_ns': 42.,
             'relative_times_ns': [0.], 'row_indices': [8]}
    transport = {'initial_primary_id': 1, 'event_id': 1, 'global_decay_id': 1, 'source_id': contract['id'],
                 'vertex': {**dict(zip(('xloc', 'yloc', 'zloc'), (v/1000 for v in position))), 'time': 0},
                 'primary': {'particle': pdg}, 'steps': [{'raw_row_index': 8, 'time_ns': 42., 'energy_keV': 100.}],
                 'pulse_groups': [group], 'tracks': [{'trackid': 1, 'parent_trackid': 0, 'particle': pdg, 'time': 0},
                                                   {'trackid': 2, 'parent_trackid': 1, 'time': 0, 'procid': 7}]}
    stream = store.encoded(transport) + b'\n'
    stream_ref = portable._STREAM
    archive = {}
    if compressed:
        write(stream_ref + '.gz', gzip.compress(stream))
        archive[stream_ref] = {**sidecars[stream_ref + '.gz'],
                               'original_bytes': len(stream), 'original_sha256': store.sha(stream)}
    else:
        write(stream_ref, stream)
    write('transport/geometry.gdml', b'<gdml>fixture</gdml>')
    write('transport/run.mac', b'/gps/time 0 ns\n/RMG/Processes/Stepping/ResetInitialDecayTime true\n')
    write('source-checked.json', {'source_contract': contract, 'coordinate_transform': coordinate,
                                 'selection': {'detector': 'GeGI_3D', 'cryostat': 'fixture', 'source': contract['id'],
                                               'source_position_mm': position, 'seed': 23, 'primary_count': 2}})
    manifest = {'kind': 'gegi_event_stream_v1', 'model_id': 'GeGI_3D', 'model_sha256': digest,
                'geometry_sha256': sidecars['transport/geometry.gdml']['sha256'],
                'model_contract': {'model_sha256': digest}, 'cryostat_contract': {'id': 'fixture'},
                'coordinate_transform': coordinate, 'primary_count': 2, 'seed': 23, 'source_contract': contract,
                'source_id': contract['id'], 'source_pdg': pdg, 'counts': counts,
                'event_storage': {'kind': 'nonzero_deposit_v1', 'efficiency_denominator': 2},
                'events_file': 'events.jsonl', 'events_sha256': store.sha(stream),
                'clock_policy': portable._CLOCK, 'grouping_policy': {'horizon_ns': 100000},
                'units': {'energy': 'keV', 'length': 'mm', 'time': 'ns'},
                'processes': [{'name': 'RadioactiveDecay', 'procid': 7}],
                'raw_tables': {table: {'columns': {**{axis: {'units': 'm'} for axis in ('xloc', 'yloc', 'zloc')},
                                                   'time': {'units': 'ns'}}}
                               for table in ('vtx', 'tracks', 'stp/germanium')}}
    write(portable._MANIFEST, manifest)
    if native_request is not None:
        raw = store.encoded(native_request)
        (directory/'native-request.json').write_bytes(raw)
        request_sha256 = store.sha(raw)
    identity = {'source_group': name, 'model_sha256': digest, 'calibration_sha256': calibration,
                'raw_initial_id_base': 0, 'campaign_initial_offset': 40, 'chunk_index': 9,
                'batch': {'primary_count': 2, 'local_initial_primary_id_range': [0, 1], 'radiation_seed': 23}}
    if request_sha256 is not None:
        identity['native_request_sha256'] = request_sha256
    channels = [{'id': cid, 'family': 'X' if cid <= 17 else 'Y', 'guard': cid in (17, 34),
                 'wiring_factor': 1 if cid <= 17 else -1} for cid in range(1, 35)]
    recipe = {'channels': channels, 'drift_dt_ns': 1., 'ionisation_energy_eV': 2.95}
    response = {'source_id': contract['id'], 'status': 'completed_with_native_failures' if failed else 'completed',
                'input_manifest_sha256': sidecars[portable._MANIFEST]['sha256'],
                'store_identity_sha256': store.sha(store.encoded(identity)),
                'calibration_sha256': calibration, 'readout_recipe': recipe, 'new_field_solve': False,
                'readout_recipe_sha256': store.sha(store.encoded(recipe)), 'counts': counts}
    if request_sha256 is not None:
        response['native_request_sha256'] = request_sha256
    database = store.Store(directory/'events.sqlite', identity, create=True)
    try:
        endpoint = {'status': 'contact', 'step_limit_reached': False, 'contact_ids': [4]}
        event = {'event_id': 1, 'group_id': 0, 'source_id': contract['id'], 'source_group': name,
                 'campaign_initial_offset': 40, 'parent_primary_time_ns': 0, 'group_origin_time_ns': 42.,
                 'pulse_group': group, 'truth_edep_keV': 100., 'status': 'native_failed' if failed else 'completed',
                 'steps': [{'endpoints': [endpoint, {**endpoint, 'contact_ids': [20]}]}],
                 'channels': None if failed else [{'contact_id': c['id'], 'trace': {}} for c in channels]}
        native = None if failed else {c['id']: {'time_ns': [0., 1., 2.],
                  'signed_induced_keV': [0., 20.*c['wiring_factor'] if c['id'] in (4, 20) else 0., 0.]}
                  for c in channels}
        database.append(1, 0, event, native, 'fixture')
        database.seal(response)
    finally:
        database.close()
    path = directory/'events.sqlite'
    sidecars['events.sqlite'] = {'bytes': path.stat().st_size, 'sha256': portable._hash(path)}
    write('DONE.json', {'kind': 'gegi_campaign_chunk_done_v1', 'identity': identity, 'response': response,
                       'artifacts': sidecars, 'archives': archive})
    return directory


class PortableSourceLibraryTest(unittest.TestCase):
    def test_relocated_chunk_metadata_readout_and_unknown_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            left = make_chunk(Path(tmp)/'renamed saved input', 'new-source', [-20., 3., 30.])
            right = make_chunk(Path(tmp)/'elsewhere', 'next-source', [25., 0., 31.],
                               compressed=False, failed=True)
            self.assertEqual(portable.describe_source_library(left)['isotope'], 'Na-22')
            self.assertEqual(portable.describe_source_library(left/'events.sqlite')['source_position_mm'], [-20., 3., 30.])
            a, b = map(portable.load_source_library, (left, right))
            portable.validate_compatible(a, b)
            self.assertIsNone(a.metadata['native_request_sha256'])
            self.assertIsNone(a.metadata['field_cache_sha256'])
            self.assertIsNone(a.metadata['field_precision_bits'])
            row = {'raw_event_id': 1, 'group_id': 0, 'campaign_initial_id': 41}
            pulse, status, _ = portable.read_native(a, row)
            self.assertEqual(status, 'completed')
            self.assertEqual(len(pulse.time_ns), 3)
            missing, status, _ = portable.read_native(b, row)
            self.assertIsNone(missing)
            self.assertEqual(status, 'native_failed')
            with (left/'transport/run.mac').open('ab') as handle:
                handle.write(b'# extra')
            with self.assertRaisesRegex(ValueError, 'Sealed chunk file changed'):
                portable.load_source_library(left)

    def test_admitted_field_identity_survives_a_relocated_chunk(self):
        with tempfile.TemporaryDirectory() as tmp:
            model = portable._ADMITTED_MODEL_SHA256
            request = 'ae476cdc9349bddec75c36c87fb9538224cfdf8b848618d393aea983b663db29'
            depth = portable._ADMITTED_DEPTH_SHA256
            sealed = make_chunk(Path(tmp)/'relocated', 'a', [1., 2., 3.], model=model,
                                calibration=depth, request_sha256=request)
            fields = portable.load_source_library(sealed).metadata
            self.assertEqual(fields['native_request_sha256'], request)
            self.assertEqual(fields['field_cache_sha256'], portable._ADMITTED_CACHE_SHA256)
            self.assertEqual(fields['field_precision_bits'], 32)
            unknown = make_chunk(Path(tmp)/'unadmitted', 'b', [1., 2., 3.], model=model, request_sha256=request)
            self.assertIsNone(portable.describe_source_library(unknown)['field_cache_sha256'])

    def test_matching_request_sidecar_binds_cache_without_fresh_solve_precision(self):
        with tempfile.TemporaryDirectory() as tmp:
            request = {'kind': 'gegi_campaign_response_request_v1', 'model_sha256': 'b'*64,
                       'field_cache': {'model_sha256': 'b'*64, 'sha256': 'd'*64},
                       'numerics': {'field_policy': 'reuse-only', 'precision_bits': 64}}
            folder = make_chunk(Path(tmp)/'relocated', 'a', [1., 2., 3.], native_request=request)
            metadata = portable.load_source_library(folder).metadata
            self.assertEqual(metadata['native_request_sha256'], store.sha(store.encoded(request)))
            self.assertEqual(metadata['field_cache_sha256'], 'd'*64)
            self.assertIsNone(metadata['field_precision_bits'])
            (folder/'native-request.json').write_bytes(store.encoded({**request, 'other': 'changed'}))
            unknown = portable.load_source_library(folder).metadata
            self.assertEqual(unknown['native_request_sha256'], metadata['native_request_sha256'])
            self.assertIsNone(unknown['field_cache_sha256'])
            self.assertIsNone(unknown['field_precision_bits'])

    def test_exact_clock_parity_at_ordinary_mean_and_zero_activity(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = portable.load_source_library(make_chunk(Path(tmp)/'a', 'a', [1., 2., 3.]))
            b = replace(a, metadata={**a.metadata, 'source_group': 'b'})
            settings = {'activities_bq': (18., 0.), 'duration_ns': 250000000, 'seed': 20261118}
            actual = portable.schedule_sources(a, b, **settings)
            expected = research.simulate('a', {'original': a.metadata['original'], 'marked_nonzero_events': a.marks},
                                         20261118, 250000000, 18.)
            self.assertEqual(actual['sources']['a']['clock'], expected)
            self.assertEqual(actual['sources']['b']['counts']['parents'], 0)
            self.assertEqual(actual['sources']['b']['eligible_groups'], [])
            self.assertEqual(actual, portable.schedule_sources(a, b, **settings))
            differing = replace(b, metadata={**b.metadata, 'field_calibration_sha256': 'c'*64})
            with self.assertRaisesRegex(ValueError, 'field_calibration_sha256'):
                portable.schedule_sources(a, differing, **settings)

    def test_high_mark_mean_has_no_underflow_or_poisson_census_loss(self):
        metadata = {key: 'fixture' for key in portable._FIELD_KEYS}
        metadata.update(source_group='same-label', original={'initial_primaries': 1})
        a = portable.SourceLibrary(Path('.'), Path('events.sqlite'), metadata, [], {})
        actual = portable.schedule_sources(a, a, activities_bq=(1000., 0.), duration_ns=1e9, seed=93)
        first, second = actual['source_keys']
        self.assertNotEqual(first, second)
        self.assertEqual(actual['sources'][first]['clock']['clock_layers'], 2)
        count = actual['sources'][first]['counts']
        self.assertGreater(count['parents'], 850)
        self.assertLess(count['parents'], 1150)
        self.assertEqual(count['parents'], count['marked_zero_parents'])
        self.assertEqual(actual['sources'][second]['counts']['parents'], 0)

    def test_incomplete_right_edge_remains_censored(self):
        mark = {'raw_event_id': 0, 'campaign_initial_id': 4,
                'groups': [{'group_id': 0, 'positive_ge_energy_keV': 50.,
                            'first_deposit_since_parent_ns': 44., 'last_deposit_since_parent_ns': 64.}]}
        library = portable.SourceLibrary(Path('.'), Path('events.sqlite'), {'raw_initial_id_base': 0}, [], {0: mark})
        clock = {'live_parent_census': {}, 'nonzero_mark_occurrences': [
            {'occurrence_id': '0.0.0', 'mark_ordinal': 0, 'parent_in_live_time': False, 'groups': [
                {'group_id': 0, 'first_ge_deposit_ns': 98., 'last_ge_deposit_ns': 118.,
                 'onset_in_live_time': True, 'complete_deposits_in_live_time': False}]}]}
        eligible, censored, counts = portable._clock_groups('a', library, clock, 100., True)
        self.assertEqual(eligible, [])
        self.assertEqual(counts['group_onsets_inside_with_last_deposit_censored'], 1)
        self.assertEqual([censored[0]['truth_edep_keV'], censored[0]['original_deposit_span_ns']], [50., 20.])
        _, censored, _ = portable._clock_groups('a', library, clock, 100., False)
        self.assertEqual(censored, [])


if __name__ == '__main__':
    unittest.main()
