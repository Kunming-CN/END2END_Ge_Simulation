import copy
from contextlib import closing, redirect_stdout
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zlib

import gegi_campaign_response as C
import gegi_dual_source as dual
import gegi_event_store as S
import gegi_native_failure_recovery as recovery
from gegi_native_failure_recovery import inherit_complete
from test_gegi_native_signal_only import native_payload


class RecoveryInheritanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='native-recovery-', dir=C.ROOT/'.local')
        self.addCleanup(self.temp.cleanup); root = Path(self.temp.name)
        self.prior = S.Store(root/'prior.sqlite', {'producer': 'original'}, create=True)
        self.current = S.Store(root/'current.sqlite', {'producer': 'corrected'}, create=True)
        self.addCleanup(self.prior.close); self.addCleanup(self.current.close)
        self.event, self.signals = native_payload()
        self.group = {'event_id': 27, 'group_id': 0, 'steps': [{'raw_row_index': 4, 'energy_keV': 4.}]}
        self.event['input_group'] = self.group
        self.event['input_steps'] = self.group['steps']
        self.event['steps'][0]['endpoints'] = [
            {'status': 'contact', 'step_limit_reached': False, 'contact_ids': [3]},
            {'status': 'contact', 'step_limit_reached': False, 'contact_ids': [24]}]
        self.digest = S.sha(S.encoded(self.group))
        self.binding = {'ref': 'prior', 'request_sha256': 'a'*64, 'producer_archive_sha256': 'b'*64}

    def test_exact_complete_inheritance_keeps_signed_bits_and_actual_producer(self):
        self.prior.append(27, 0, self.event, self.signals, self.digest)
        old = self.prior.read(27, 0, with_signals=True)
        result = inherit_complete(self.prior, self.binding, self.group, self.current)
        saved, signals = self.current.read(27, 0, with_signals=True)
        self.assertEqual(signals, self.signals)
        self.assertEqual(signals[2]['signed_induced_keV'], [0., .25, 0.])
        self.assertEqual(saved['native_recovery_inherited']['request_sha256'], 'a'*64)
        self.assertEqual(saved['native_recovery_inherited']['event_metadata_sha256'],
                         self.prior.db.execute('SELECT metadata_sha256 FROM events').fetchone()[0])
        self.assertEqual(result, saved)
        self.assertEqual(self.prior.read(27, 0, with_signals=True), old)

    def test_unfinished_prior_carrier_is_recomputed_and_changed_input_rejected(self):
        event = copy.deepcopy(self.event); event['status'] = 'step_limit'
        event['steps'][0]['endpoints'][0].update(status='step_limit', step_limit_reached=True, contact_ids=[])
        self.prior.append(27, 0, event, self.signals, self.digest)
        self.assertIsNone(inherit_complete(self.prior, self.binding, self.group, self.current))
        self.assertEqual(list(self.current.keys()), [])
        changed = copy.deepcopy(self.group); changed['steps'][0]['energy_keV'] = 5.
        with self.assertRaisesRegex(ValueError, 'input changed'):
            inherit_complete(self.prior, self.binding, changed, self.current)


class CapOnlyExtensionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='native-cap-extension-', dir=C.ROOT/'.local')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source, self.parent = self.root/'source', self.root/'parent'
        self.source.mkdir(); self.parent.mkdir()
        self.request = dict(model_sha256='a'*64, field_cache={'sha256': 'b'*64}, source_sha256={},
                            response_mode=S.NATIVE_SIGNAL_ONLY, numerics={'drift_dt_ns': 1., 'drift_cap_ns': 1000.})
        self.live = 5e6
        self.outcomes = {2590: 'step_limit', 25: 'step_limit', 26: 'native_failed',
                         27: 'stopped_without_contact', 28: 'completed'}
        self.groups = {tid: dict(event_id=tid, group_id=0, group_origin_time_ns=1000000.+11000.*index,
                                 steps=[dict(raw_row_index=index, energy_keV=4., time_ns=1000000.+11000.*index)])
                       for index, tid in enumerate(self.outcomes)}
        archive = self.source/'compton-candidates.sqlite'
        with closing(sqlite3.connect(archive)) as db, db:
            db.executescript('CREATE TABLE native_failures(ordinal INTEGER, record BLOB);'
                             'CREATE TABLE input_groups(ordinal INTEGER, onset_ns REAL)')
            for ordinal, group in enumerate(self.groups.values(), 1):
                db.execute('INSERT INTO native_failures VALUES(?,?)', (ordinal,
                    zlib.compress(S.encoded({'event': {'status': 'step_limit'}, 'group': group}))))
                db.execute('INSERT INTO input_groups VALUES(?,?)', (ordinal, group['group_origin_time_ns']))
        C.write(self.parent/'native-request.json', self.request)
        identity = {'kind': recovery.KIND, 'source_ref': str(self.source.relative_to(C.ROOT)),
                    'source_sha256': C.file_sha(archive), 'group_count': len(self.groups),
                    'request_sha256': C.file_sha(self.parent/'native-request.json')}
        C.write(self.parent/'identity.json', identity)
        C.write(self.parent/'native-ready.json', self.ready(self.parent/'native-request.json'))
        C.write(self.parent/'active-worker.json', {'status': 'closed'})
        (self.parent/'producer-source.zip').write_bytes(b'fixture parent producer snapshot')
        rows = []
        with closing(S.Store(self.parent/'native.sqlite', identity, create=True)) as native:
            for ordinal, (tid, group) in enumerate(self.groups.items(), 1):
                event, signals = self.payload(group, self.outcomes[tid])
                digest = S.sha(S.encoded(group))
                native.append(tid, 0, event, signals, digest)
                rows.append(dict(ordinal=ordinal, event_id=tid, group_id=0, input_sha256=digest,
                    new_status=event['status'], complete=event['status'] == 'completed'))
            history = recovery.conditional_history(self.source, native, self.live, 1001.)
            receipt = dict(status='completed', identity=identity,
                           counts={'completed': 1, 'step_limit': 2, 'native_failed': 1, 'stopped_without_contact': 1},
                           conditional_history=history)
            native.seal(receipt)
        C.write(self.parent/'recovery.json', receipt)
        ledger = self.parent/'recovery-status.jsonl'
        ledger.write_bytes(b''.join(S.encoded(row)+b'\n' for row in rows))
        C.write(self.parent/'recovery-status-summary.json',
                dict(groups=len(rows), counts=receipt['counts'], status_ledger_sha256=C.file_sha(ledger)))
        C.write(self.source/'candidate-acquisition.json',
                dict(live_time_ns=self.live, excluded_intervals_ns=self.reference_mask(self.groups)))
        self.parent_store_sha = C.file_sha(self.parent/'native.sqlite')
        self.calls = []

    def ready(self, request_path, *, steps=None):
        request = C.read(request_path)
        return dict(request_sha256=C.file_sha(request_path), drift_dt_ns=1.,
                    drift_numerics={'max_steps': steps or int(recovery.native_support_ns(request['numerics']))},
                    model_sha256=request['model_sha256'], field_cache_sha256=request['field_cache']['sha256'])

    def payload(self, group, status):
        event, signals = native_payload()
        event.update(event_id=group['event_id'], group_id=group['group_id'], input_group=group,
                     input_steps=group['steps'], status=status)
        event['steps'][0]['endpoints'] = [
            {'status': 'contact', 'step_limit_reached': False, 'contact_ids': [3]},
            {'status': 'contact', 'step_limit_reached': False, 'contact_ids': [24]}]
        if status == 'native_failed':
            event.update(channels=None, error='fixture boundary failure', readout_status='native_unavailable')
            signals = None
        elif status != 'completed':
            event['steps'][0]['endpoints'][0].update(
                status=status, step_limit_reached=status == 'step_limit', contact_ids=[])
        return event, signals

    def worker(self, request, spool, *, forced_steps=None):
        def process(group, target):
            tid = group['event_id']
            self.calls.append(tid)
            event, signals = self.payload(group, 'completed' if tid == 2590 else 'step_limit')
            target.append(tid, group['group_id'], event, signals, S.sha(S.encoded(group)))
            return target.read(tid, group['group_id'])[0]
        return SimpleNamespace(process=SimpleNamespace(pid=os.getpid()), start=lambda: self.ready(request, steps=forced_steps),
                               close=lambda: None, process_group=process)

    def reference_mask(self, ids, *, extended=()):
        rows = []
        for tid in ids:
            group = self.groups[tid]
            # The unchanged legacy helper adds 1001 ns. On these integer,
            # exactly represented clocks, shifting the input horizon by 4000 ns
            # independently exercises the mixed summation and clipping.
            time = group['group_origin_time_ns']
            rows.append(dict(first_ge_deposit_ns=time, last_ge_deposit_ns=time+(4000. if tid in extended else 0.),
                             positive_ge_energy_keV=group['steps'][0]['energy_keV']))
        return dual._history_mask(rows, self.live)

    def test_pilot_then_all_limits_reuse_complete_and_preserve_deferred_support(self):
        pilot, extended = self.root/'pilot', self.root/'all-limits'
        with patch.object(C, 'ResidentWorker', side_effect=self.worker), redirect_stdout(io.StringIO()):
            identity = recovery.prepare_extension(self.parent, pilot, 5000., event_ids=[2590])
            self.assertEqual(identity['group_count'], 5)
            self.assertEqual(identity['cap_extension']['selected_ordinals'], [1])
            self.assertEqual(recovery.run(pilot, stop_after_new=0)['status'], 'stopped')
            self.assertEqual(self.calls, [])
            first = recovery.run(pilot)
            self.assertEqual(first['conditional_history']['deferred_unavailable_counts'],
                             {'step_limit': 1, 'native_failed': 1, 'stopped_without_contact': 1})
            self.assertEqual(first['conditional_history']['remaining_intervals_ns'], self.reference_mask((25, 26, 27)))
            recovery.prepare_extension(self.parent, extended, 5000., prior_recovery=pilot)
            final = recovery.run(extended)
            self.assertEqual(recovery.run(extended), final)
        self.assertEqual(self.calls, [2590, 25])
        self.assertEqual(C.file_sha(self.parent/'native.sqlite'), self.parent_store_sha)
        history = final['conditional_history']
        self.assertEqual(final['new_groups_this_activation'], 1)
        self.assertEqual(history['effective_counts'],
                         {'completed': 2, 'step_limit': 1, 'native_failed': 1, 'stopped_without_contact': 1})
        self.assertEqual(history['provenance_counts'],
                         {'selected_extended': 2, 'retained_parent_complete': 1, 'unselected_parent_unavailable': 2})
        self.assertEqual(history['remaining_intervals_ns'], self.reference_mask((25, 26, 27), extended=(25,)))
        self.assertNotEqual(history['remaining_intervals_ns'], self.reference_mask((25, 26, 27)))
        self.assertNotEqual(history['remaining_intervals_ns'], self.reference_mask((25, 26, 27), extended=(25, 26, 27)))
        self.assertEqual(history['remaining_unknown_union']['failure_count'], 3)
        self.assertEqual(final['identity']['cap_extension']['parent_native_support_ns'], 1001.)
        self.assertEqual(history['extended_native_support_ns'], 5001.)
        with closing(S.Store(extended/'native.sqlite', final['identity'])) as native:
            self.assertEqual(list(native.keys()), [(25, 0), (2590, 0)])
            inherited, signal = native.read(2590, 0, with_signals=True)
            self.assertEqual(signal[2]['signed_induced_keV'], [0., .25, 0.])
            self.assertEqual(inherited['native_recovery_inherited']['request_sha256'], first['identity']['request_sha256'])

    def test_nonlimits_and_unchanged_effective_cap_are_not_admitted(self):
        with self.assertRaisesRegex(ValueError, 'sealed step-limit'):
            recovery.prepare_extension(self.parent, self.root/'wrong-id', 5000., event_ids=[26, 2590])
        with self.assertRaisesRegex(ValueError, 'extend native signal support'):
            recovery.prepare_extension(self.parent, self.root/'old-cap', 1000.)

    def test_ready_with_shorter_support_stops_before_any_group(self):
        output = self.root/'ready-mismatch'
        recovery.prepare_extension(self.parent, output, 5000., event_ids=[2590])
        with patch.object(C, 'ResidentWorker', side_effect=lambda *args: self.worker(*args, forced_steps=1001)):
            with self.assertRaisesRegex(ValueError, 'configured drift support'):
                recovery.run(output)
        self.assertEqual(self.calls, [])
        self.assertFalse((output/'recovery.json').exists())

    def test_mask_overlap_includes_growth_outside_previous_union(self):
        result = recovery.mask_overlap([[0., 8.], [10., 17.]], [[2., 4.], [7., 15.], [20., 22.]])
        self.assertEqual(result, {'overlap_ns': 8., 'before_only_ns': 7., 'after_only_ns': 4., 'union_ns': 19.})


if __name__ == '__main__':
    unittest.main()
