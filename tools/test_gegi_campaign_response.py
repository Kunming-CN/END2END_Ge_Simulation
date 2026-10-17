"""Sparse grouping, lossless ingestion, recovery and replay checks without physics."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import gegi_campaign_response as C
import gegi_event_store as S


def step(row, time):
    return {'raw_row_index': row, 'time_ns': time, 'energy_keV': 1.,
            'position_mm': [0., 0., 0.], 'track_id': row+1, 'parent_track_id': 0}


def channel(contact=1):
    return {'contact_id': contact, 'wiring_factor': 1, 'accepted': True,
            'reconstructed_energy_keV': 1., 'collection_candidate': True,
            'trace': {'time_ns': [0., 1.], 'charge_fC': [-0., 1.]}}


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='gegi-response-test-', dir=C.ROOT/'.local')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.worker = object.__new__(C.ResidentWorker)
        self.worker.spool = self.root/'spool';self.worker.spool.mkdir()
        self.worker.ready = {'channels': [], 'readout_config': {}, 'electronics_calibration': {},
            'ionisation_energy_eV': 3., 'drift_dt_ns': 1., 'source_code_sha256': {}, 'model_sha256': 'm'*64,
            'field_cache_sha256': 'f'*64, 'drift_numerics': {'dt': 1.}}
        self.worker.request_sha256 = 'r'*64

    def event(self):
        event = {'event_id': 2, 'global_decay_id': 2, 'initial_primary_id': 2,
                 'steps': [step(4, 10.), step(8, 100009.), step(10, 100010.)],
                 'tracks': [{'track_id': 1, 'time_ns': 10.}], 'primary_time_ns': 0.}
        # Load the actual transport policy through the consumer, then retain its map.
        import sys
        sys.path.insert(0, str(C.ROOT/'transport')) if str(C.ROOT/'transport') not in sys.path else None
        import cs137
        event['pulse_groups'] = cs137.group_deposits(event['steps'])
        return event

    def group(self):
        return next(C.pulse_groups(self.event(), 'cs137', {'source_group': 's', 'chunk_index': 0,
                                                       'campaign_initial_offset': 0}))

    def test_exact_anchored_groups_preserve_absolute_rows(self):
        event = self.event()
        groups = list(C.pulse_groups(event, 'cs137', {}))
        self.assertEqual([g['group_origin_time_ns'] for g in groups], [10., 100010.])
        self.assertEqual(groups[0]['steps'], event['steps'][:2])
        self.assertEqual(groups[1]['pulse_group'], event['pulse_groups'][1])
        self.assertTrue(groups[1]['pulse_group']['boundary_split_within_horizon'])
        self.assertEqual(groups[0]['parent_event_metadata']['tracks'], event['tracks'])
        bad = copy.deepcopy(event);bad['pulse_groups'][0]['row_indices'].pop()
        with self.assertRaisesRegex(ValueError, 'group assignment'):
            list(C.pulse_groups(bad, 'cs137', {}))
        del bad['pulse_groups']
        with self.assertRaisesRegex(ValueError, 'missing its original pulse grouping'):
            list(C.pulse_groups(bad, 'cs137', {}))

    def test_gamma_is_one_nonzero_group_without_decay_window(self):
        event = {'event_id': 3, 'vertex': {'time': 0.}, 'steps': [step(5, 7.), step(9, 8.)]}
        groups = list(C.pulse_groups(event, 'gamma', {}))
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]['group_origin_time_ns'], 7.)
        self.assertIsNone(groups[0]['horizon_ns'])

    def spool_receipt(self, group, failed=False):
        digest = S.sha(S.encoded(group));stem = 'g-'+digest
        event = {'event_id': group['event_id'], 'group_id': group['group_id'],
            'status': 'native_failed' if failed else 'completed', 'input_group': group,
            'input_event_sha256': digest, 'channels': None if failed else [channel()],
            'input_steps': group['steps']}
        paths = {'event_path': self.worker.spool/(stem+'.json'),
                 'input_path': self.worker.spool/(stem+'-input.json'),
                 'receipt_path': self.worker.spool/(stem+'-receipt.json'),
                 'signals_path': self.worker.spool/(stem+'-signals.csv')}
        C.write(paths['event_path'], event);C.write(paths['input_path'], group)
        paths['signals_path'].write_text('contact_id,time_ns,signed_induced_keV,wired_induced_keV\n1,0,-0,-0\n1,1,1,1\n')
        receipt = {k: str(v) for k, v in paths.items()}
        receipt.update(input_sha256=digest, event_id=group['event_id'], group_id=group['group_id'],
            event_sha256=C.file_sha(paths['event_path']), signals_sha256=C.file_sha(paths['signals_path']))
        if failed:
            receipt.update(signals_path=None, signals_sha256=None)
        C.write(paths['receipt_path'], receipt)
        self.worker.command = lambda *a, **kw: receipt
        return paths

    def test_success_deletes_only_owned_spool_after_durable_roundtrip(self):
        group = self.group();paths = self.spool_receipt(group)
        store = S.Store(self.root/'events.sqlite', {}, create=True);self.addCleanup(store.close)
        result = self.worker.process_group(group, store)
        self.assertEqual(result['event_id'], 2)
        self.assertTrue(all(not p.exists() for p in paths.values()))
        saved, native = store.read(2, 0, with_signals=True)
        self.assertEqual(saved['input_steps'], group['steps'])
        self.assertEqual(native[1]['signed_induced_keV'], [-0., 1.])
        self.worker.command = lambda *a, **kw: self.fail('Committed group was rerun')
        self.assertEqual(self.worker.process_group(group, store), saved)

    def test_failed_native_signals_stay_unknown_and_evidence_is_retained(self):
        group = self.group();paths = self.spool_receipt(group, failed=True)
        store = S.Store(self.root/'events.sqlite', {}, create=True);self.addCleanup(store.close)
        result = self.worker.process_group(group, store)
        self.assertIsNone(result['channels']);self.assertIsNone(result['native_signals'])
        self.assertIsNone(result['readout_summary']['energy_keV'])
        self.assertTrue(all(p.exists() for p in paths.values()))

    def test_failed_transaction_retains_spool_and_path_escape_refused(self):
        group = self.group();paths = self.spool_receipt(group)
        store = S.Store(self.root/'events.sqlite', {}, create=True);self.addCleanup(store.close)
        with patch.object(store, 'append', side_effect=ValueError('transaction failed')):
            with self.assertRaisesRegex(ValueError, 'transaction failed'):
                self.worker.process_group(group, store)
        self.assertEqual(list(store.keys()), [])
        self.assertTrue(all(p.exists() for p in paths.values()))
        receipt = C.read(paths['receipt_path']);receipt['input_path'] = str(self.root/'elsewhere.json')
        with self.assertRaisesRegex(ValueError, 'Unowned'):
            self.worker._spool_paths(receipt, receipt['input_sha256'])

    def test_live_unknown_and_unresolved_launch_block_resume(self):
        owner = self.worker.spool/'worker-process.json'
        C.write(owner, {'status': 'launching'})
        with self.assertRaisesRegex(ValueError, 'Unresolved'):
            self.worker._check_previous_process()
        C.write(owner, {'status': 'running', 'pid': 123, 'process_start_identity': 'old'})
        for current in ('old', 'unknown'):
            with patch.object(C, 'process_identity', return_value=current):
                with self.assertRaisesRegex(ValueError, 'live or unknown'):
                    self.worker._check_previous_process()
        for current in (None, 'new-pid-identity'):
            with patch.object(C, 'process_identity', return_value=current):
                self.worker._check_previous_process()

    def test_replay_requires_exact_traces_and_scalars(self):
        original = channel();saved = copy.deepcopy(original)
        saved['derived_trace_sha256'] = S.trace_hash(saved.pop('trace'))
        replay = {'drift_executed': False, 'channels': [original]}
        self.assertEqual(C.verify_replayed_channels({'channels': [saved]}, replay)['status'], 'verified_exact')
        bad = copy.deepcopy(replay);bad['channels'][0]['trace']['charge_fC'][1] += .001
        with self.assertRaisesRegex(ValueError, 'trace mismatch'):
            C.verify_replayed_channels({'channels': [saved]}, bad)
        bad = copy.deepcopy(replay);bad['channels'][0]['accepted'] = False
        with self.assertRaisesRegex(ValueError, 'scalar mismatch'):
            C.verify_replayed_channels({'channels': [saved]}, bad)

    def test_prior_recipe_is_sealed_without_reprocessing_or_rewriting_old_group(self):
        import gegi_campaign_analysis as A
        self.worker.ready['source_code_sha256']={'gegi_campaign_response.jl':'b'*64}
        old_recipe=copy.deepcopy(self.worker.recipe());old_recipe['source_code_sha256']['gegi_campaign_response.jl']='a'*64
        raw={'event_id':2,'vertex':{'time':0.},'steps':[step(4,10.)]};stream=self.root/'events.jsonl';stream.write_bytes(S.encoded(raw)+b'\n')
        C.write(self.root/'manifest.json',{'kind':'gegi_event_stream_v1','events_file':'events.jsonl','events_sha256':C.file_sha(stream),
            'model_sha256':'m'*64,'source_id':'gamma','primary_count':5,'zero_deposit_primaries':4,'nonzero_primaries':1})
        table={'kind':'gegi_pixel_simulated_depth_v1','per_pixel_calibration':True,'model_sha256':'m'*64,
            'field_cache_sha256':'f'*64,'drift_numerics':{'dt':1.},'calibration_source_sha256':{}}
        C.write(self.root/'calibration.json',table)
        calibration={'ref':str(self.root/'calibration.json'),'sha256':C.file_sha(self.root/'calibration.json')}
        windows=[{'line_energy_keV':662.,'half_width_keV':13.24}]
        identity={'source_group':'gamma','chunk_index':0,'campaign_initial_offset':0,'native_request_sha256':'r'*64,
            'calibration_sha256':calibration['sha256'],'photopeak_windows_sha256':S.sha(S.encoded(windows))}
        context={k:identity[k] for k in ('source_group','chunk_index','campaign_initial_offset')}
        context['root']=str(self.root.relative_to(C.ROOT)).replace('\\','/')
        group=next(C.pulse_groups(raw,'gamma',context));input_sha=S.sha(S.encoded(group))
        event={'event_id':2,'group_id':0,'status':'native_failed','channels':None,
            'readout_recipe_sha256':S.sha(S.encoded(old_recipe)),'readout_summary':{'accepted':False,'energy_keV':None},
            'reconstruction':{'status':'rejected','cones':[]}}
        store=S.Store(self.root/'events.sqlite',identity,create=True)
        store.append(2,0,event,None,input_sha);saved,_=store.read(2,0)
        original=store.db.execute('SELECT metadata FROM events').fetchone()[0];store.close()
        prior={'kind':'gegi_prior_recipe_provenance_v1','revision':{'ref':'.local/synthetic/revision.json','sha256':'c'*64},
            'original_store_sha256':C.file_sha(self.root/'events.sqlite'),
            'recipes':{event['readout_recipe_sha256']:old_recipe},
            'events':[{'event_id':2,'group_id':0,'input_sha256':input_sha,'metadata_sha256':S.sha(S.encoded(saved)),
                       'readout_recipe_sha256':event['readout_recipe_sha256']}],
            'wrapper_source_change':{'name':'gegi_campaign_response.jl','old_sha256':'a'*64,'new_sha256':'b'*64}}
        self.worker.command=lambda *a,**kw:self.fail('Preserved group must not execute drift')
        result=self.worker.run_chunk(self.root/'manifest.json',self.root/'events.sqlite',identity,
            calibration=calibration,photopeak_windows=windows,receipt_path=self.root/'response.json',prior_recipe_provenance=prior)
        self.assertEqual(result['prior_recipe_provenance'],prior)
        self.assertEqual(A.response_recipe_for_event(result,saved),old_recipe)
        store=S.Store(self.root/'events.sqlite',identity)
        try:
            self.assertEqual(store.db.execute('SELECT metadata FROM events').fetchone()[0],original)
            self.assertEqual(json.loads(store.db.execute('SELECT body FROM completion').fetchone()[0]),result)
        finally:store.close()
        changed=copy.deepcopy(result);changed['readout_recipe']['readout_config']['gain']=9
        changed['readout_recipe_sha256']=S.sha(S.encoded(changed['readout_recipe']))
        with self.assertRaisesRegex(ValueError,'physics/configuration'):A.response_recipe_for_event(changed,saved)

    def test_sparse_chunk_counts_groups_and_unique_primaries_and_seals(self):
        event = self.event();stream = self.root/'events.jsonl'
        stream.write_bytes(S.encoded(event)+b'\n')
        manifest = {'kind': 'gegi_event_stream_v1', 'events_file': 'events.jsonl', 'events_sha256': C.file_sha(stream),
            'model_sha256': 'm'*64, 'source_id': 'cs137', 'primary_count': 5, 'zero_deposit_primaries': 4,
            'nonzero_primaries': 1, 'counts': {'initial_decays': 5, 'decay_photons': 6, 'line_photons': 4,
                                           'line_photon_counts': {'661.657': 4}}}
        C.write(self.root/'manifest.json', manifest)
        table = {'kind': 'gegi_pixel_simulated_depth_v1', 'per_pixel_calibration': True, 'pixels': {},
                 'model_sha256': 'm'*64, 'field_cache_sha256': 'f'*64, 'drift_numerics': {'dt': 1.},
                 'calibration_source_sha256': {}}
        C.write(self.root/'calibration.json', table)
        calibration = {'ref': str(self.root/'calibration.json'), 'sha256': C.file_sha(self.root/'calibration.json')}
        windows = [{'line_energy_keV': 661.657, 'half_width_keV': 25.}]
        identity = {'source_group': 'cs137', 'chunk_index': 0, 'campaign_initial_offset': 100,
                    'native_request_sha256': 'r'*64, 'calibration_sha256': calibration['sha256'],
                    'photopeak_windows_sha256': S.sha(S.encoded(windows))}
        def process(group, store, **kw):
            value = {'event_id': group['event_id'], 'group_id': group['group_id'], 'status': 'native_failed',
                     'channels': None, 'input_group': group, 'readout_summary': {'accepted': False},
                     'reconstruction': {'status': 'rejected'}}
            store.append(group['event_id'], group['group_id'], value, None, S.sha(S.encoded(group)))
            return value
        self.worker.process_group = process
        args = (self.root/'manifest.json', self.root/'events.sqlite', identity)
        kwargs = {'calibration': calibration, 'photopeak_windows': windows, 'receipt_path': self.root/'response.json'}
        result = self.worker.run_chunk(*args, **kwargs)
        self.assertEqual(result['counts']['initial_primaries'], 5)
        self.assertEqual(result['counts']['pulse_groups'], 2)
        self.assertEqual(result['counts']['native_failed_groups'], 2)
        self.assertEqual(result['counts']['native_failed_primaries'], 1)
        self.assertEqual(result['counts']['line_photon_counts'], {'661.657': 4})
        self.assertEqual(result['status'], 'completed_with_native_failures')
        store = S.Store(self.root/'events.sqlite', identity)
        self.assertEqual(list(store.keys()), [(2, 0), (2, 1)])
        self.assertEqual(store.db.execute('SELECT body FROM completion').fetchone()[0], S.encoded(result))
        store.close()
        self.worker.process_group = lambda *a, **kw: self.fail('Sealed batch was rerun')
        self.assertEqual(self.worker.run_chunk(*args, **kwargs), result)


if __name__ == '__main__':
    unittest.main()
