"""Synthetic stores only: exact admission, preserved prefix, and narrow upgrade."""
import copy
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import zipfile

import gegi_event_store as E
import gegi_native_continuation as C
import scenario_workflow as W


class ContinuationTests(unittest.TestCase):
    def setUp(self):
        base = W.ROOT / '.local/steady-acquisition-v1'; base.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix='continuation-unit-', dir=base)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name); self.output = self.root / 'run'; self.output.mkdir()
        refs = C.WORKER_CHANGES | {'models/GeGI_3D.yaml', 'transport/gegi_streaming_source.py',
            'transport/gegi_source_inventory.py', 'tools/gegi_streaming_readout.py', 'tools/gegi_candidate_storage.py',
            'tools/gegi_candidate_run.py', 'tools/gegi_missing_history.py', 'tools/gegi_resource_monitor.py',
            'tools/gegi_streaming_acquisition.py'}
        sources = {ref: ref.encode() for ref in refs}; hashes = {ref: hashlib.sha256(body).hexdigest() for ref, body in sources.items()}
        self.old_request = {'kind': 'request', 'model_sha256': 'model', 'field_cache': {'sha256': 'fields'},
            'numerics': {'native_seed': 9, 'drift_cap_ns': 1000}, 'profile_sha256': 'profile',
            'source_sha256': {ref: hashes[ref] for ref in C.WORKER_CHANGES | {'models/GeGI_3D.yaml'}}}
        W.write(self.output / 'native-request.json', self.old_request)
        self.old_identity = {'kind': 'run', 'source_config': {'seed': 9}, 'environment': {'sqlite': 'test'},
            'native_request_sha256': W.sha(self.output / 'native-request.json'),
            'source_sha256': {ref: digest for ref, digest in hashes.items() if ref not in C.WORKER_CHANGES or ref == 'tools/gegi_mixed_acquisition.py'}}
        self.new_request = copy.deepcopy(self.old_request); self.new_request['response_mode'] = E.NATIVE_SIGNAL_ONLY
        self.new_request['source_sha256']['tools/gegi_event_store.py'] = 'a' * 64
        self.request = self.root / 'new-request.json'; W.write(self.request, self.new_request)
        self.new_identity = copy.deepcopy(self.old_identity); self.new_identity['native_request_sha256'] = W.sha(self.request)
        self.new_identity['source_sha256']['tools/gegi_streaming_acquisition.py'] = 'b' * 64
        self.new_identity['source_sha256']['tools/gegi_native_continuation.py'] = 'c' * 64
        self.input_sha = W.digest({'event_id': 3, 'group_id': 0, 'steps': ['synthetic']})
        self.database = self.output / 'compton-candidates.sqlite'
        with closing(sqlite3.connect(self.database)) as db, db:
            db.executescript('CREATE TABLE metadata(body BLOB); CREATE TABLE completion(body BLOB); '
                'CREATE TABLE checkpoint(singleton INTEGER,identity_sha256 TEXT,last_trigger_id INTEGER,'
                'last_candidate_trigger_id INTEGER,last_record_sha256 TEXT,state BLOB,checkpoint_sha256 TEXT); '
                'CREATE TABLE triggers(trigger_id INTEGER,record_sha256 TEXT,decision TEXT); '
                'CREATE TABLE input_groups(parent INTEGER,group_id INTEGER,input_sha256 TEXT);')
            db.execute('INSERT INTO metadata VALUES (?)', (W.encoded({'identity': self.old_identity}),))
            db.execute('INSERT INTO input_groups VALUES (3,0,?)', (self.input_sha,))
        self.save_checkpoint({'source': 'original'})
        self.signals = {cid: {'time_ns': [0., 1.], 'signed_induced_keV': [0., cid / 34]} for cid in range(1, 35)}
        self.event = {'event_id': 3, 'status': 'completed', 'truth_edep_keV': 4.,
            'steps': [{'original_endpoint_mm': [1., 2., 3.], 'energy_keV': 4.}],
            'channels': [{'contact_id': cid, 'trace': []} for cid in range(1, 35)]}
        store = E.Store(self.output / 'native-scratch.sqlite', {'request_sha256': self.old_identity['native_request_sha256']}, create=True)
        store.append(3, 0, self.event, self.signals, self.input_sha); store.close()
        self.proof = {'kind': 'gegi_native_signals_only_equivalence_v1', 'status': 'passed_exact', 'event_id': 3, 'group_id': 0,
            'original_request_sha256': self.old_identity['native_request_sha256'], 'new_request_sha256': W.sha(self.request),
            'input_group_sha256': self.input_sha, 'contact_ids': list(range(1, 35)), 'all34_float64_native_equal': True,
            'endpoint_records_equal': True, 'status_equal': True, 'truth_edep_equal': True,
            'original_status': 'completed', 'native_only_status': 'completed', 'original_truth_edep_keV': 4., 'native_only_truth_edep_keV': 4.,
            'native_arrays_sha256': dict.fromkeys(('original', 'native_only'), C.native_array_digest(self.signals)),
            'endpoints_sha256': dict.fromkeys(('original', 'native_only'), C.endpoints_digest(self.event))}
        self.proof_path = self.root / 'proof.json'; W.write(self.proof_path, self.proof)
        self.package = self.root / 'prefix.zip'
        with zipfile.ZipFile(self.package, 'w') as archive:
            for ref, body in sources.items(): archive.writestr('END2END-Ge-Student/' + ref, body)

    def save_checkpoint(self, state):
        body = W.encoded(state); identity_sha = W.digest(self.old_identity)
        digest = W.digest({'kind': 'gegi_compton_candidate_checkpoint_v1', 'identity_sha256': identity_sha,
            'last_trigger_id': 0, 'last_candidate_trigger_id': 0, 'last_record_sha256': None,
            'state_sha256': hashlib.sha256(body).hexdigest()})
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute('DELETE FROM checkpoint')
            db.execute('INSERT INTO checkpoint VALUES (1,?,0,0,NULL,?,?)', (identity_sha, body, digest))

    def prepare(self):
        return C.prepare(self.output, self.new_identity, self.request, self.proof_path, self.package)

    def test_preserves_originals_and_admits_advancing_checkpoint(self):
        paths = [self.output / name for name in ('native-request.json', 'native-scratch.sqlite')]
        original = [path.read_bytes() for path in paths]
        receipt = self.prepare(); self.save_checkpoint({'source': 'advanced'})
        active = C.admit(self.output, self.new_identity)
        self.assertEqual(active['original_identity'], self.old_identity)
        self.assertEqual(Path(active['active_request']).read_bytes(), self.request.read_bytes())
        self.assertEqual(Path(active['active_store']), self.output / 'native-only/native-scratch.sqlite')
        self.assertEqual([path.read_bytes() for path in paths], original)
        prior = W.read(W.ROOT / receipt['prior_checkpoint_binding']['ref'])
        self.assertEqual(json.loads(__import__('base64').b64decode(prior['state_base64'])), {'source': 'original'})
        with self.assertRaises(W.ControlError): self.prepare()

    def test_no_receipt_returns_none_without_opening_database(self):
        self.assertIsNone(C.admit(self.root / 'absent', {'anything': True}))

    def test_physics_and_frozen_producers_cannot_change(self):
        for edit in ('numerics', 'source_key', 'frozen_root'):
            with self.subTest(edit=edit):
                new = copy.deepcopy(self.new_request); identity = copy.deepcopy(self.new_identity)
                if edit == 'numerics': new['numerics']['native_seed'] = 10
                if edit == 'source_key': new['source_sha256'].pop('models/GeGI_3D.yaml')
                if edit == 'frozen_root': identity['source_sha256']['tools/gegi_streaming_readout.py'] = 'd' * 64
                with self.assertRaises(W.ControlError): C._contracts(self.old_identity, identity, self.old_request, new)

    def test_false_or_unsaved_original_proof_is_rejected(self):
        for key, value in (('endpoint_records_equal', False), ('event_id', 4), ('original_truth_edep_keV', 5.)):
            proof = copy.deepcopy(self.proof); proof[key] = value
            with self.subTest(key=key), self.assertRaises(W.ControlError):
                C._proof(self.output, proof, self.old_identity['native_request_sha256'], W.sha(self.request))

    def test_wrong_identity_and_tamper_rejected(self):
        self.prepare()
        wrong = copy.deepcopy(self.new_identity); wrong['source_config']['seed'] = 99
        with self.assertRaises(W.ControlError): C.admit(self.output, wrong)
        with (self.output / 'native-only/equivalence-proof.json').open('ab') as handle: handle.write(b' ')
        with self.assertRaises(W.ControlError): C.admit(self.output, self.new_identity)

    def test_original_package_and_checkpoint_must_match(self):
        with zipfile.ZipFile(self.package, 'w') as archive: archive.writestr('bad', b'bad')
        with self.assertRaises((W.ControlError, KeyError)): self.prepare()
        self.assertFalse((self.output / 'native-only').exists())
        with closing(sqlite3.connect(self.database)) as db, db: db.execute("UPDATE checkpoint SET checkpoint_sha256='changed'")
        with self.assertRaises(W.ControlError): self.prepare()

    def test_digest_includes_every_channel_field_and_float64_bits(self):
        altered = copy.deepcopy(self.signals); altered[34]['signed_induced_keV'][0] = -0.
        self.assertNotEqual(C.native_array_digest(altered), C.native_array_digest(self.signals))
        altered = copy.deepcopy(self.event); altered['steps'][0]['original_endpoint_mm'][0] += 1e-12
        self.assertNotEqual(C.endpoints_digest(altered), C.endpoints_digest(self.event))


if __name__ == '__main__': unittest.main()
