"""Explicit one-time native-only upgrade; caller holds execution lease/no worker.

Original candidate/native stores retain their identities and bytes. This is only
the exact paired-validated isolated-electronics omission, not a source migration.
"""
from contextlib import closing
import base64
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import struct
import zipfile

import gegi_event_store as E
import scenario_workflow as W

KIND = 'gegi_native_only_continuation_v1'
ROOT_CHANGES = {'tools/gegi_streaming_acquisition.py', 'tools/gegi_mixed_acquisition.py', 'tools/gegi_native_continuation.py'}
WORKER_CHANGES = {'simulation/gegi_response.jl', 'simulation/gegi_campaign_response.jl',
                  'tools/gegi_campaign_response.py', 'tools/gegi_event_store.py', 'tools/gegi_mixed_acquisition.py'}
FIELDS = ('identity_sha256', 'last_trigger_id', 'last_candidate_trigger_id', 'last_record_sha256', 'state', 'checkpoint_sha256')


def native_array_digest(signals):
    """cid uint32LE; fixed time/charge fields: length uint64LE + Float64LE bytes."""
    W.require(set(signals) == set(range(1, 35)), 'Exact comparison requires all 34 electrodes')
    digest = hashlib.sha256(b'gegi-native-f64-v1\0')
    for cid in range(1, 35):
        W.require(set(signals[cid]) == {'time_ns', 'signed_induced_keV'}, 'Unexpected native fields')
        digest.update(struct.pack('<I', cid))
        for field in ('time_ns', 'signed_induced_keV'):
            values = signals[cid][field]
            digest.update(struct.pack('<Q', len(values)))
            digest.update(struct.pack('<' + 'd' * len(values), *values))
    return digest.hexdigest()


def endpoints_digest(event):
    return W.digest(event['steps'])


def _owned(path):
    path = Path(path).absolute()
    relative = path.relative_to(W.ROOT).as_posix()
    W.require(relative.startswith('.local/'), 'Continuation evidence belongs under project .local')
    return W.safe_path(W.ROOT, relative)


def _binding(path):
    path = _owned(path)
    return {'ref': path.relative_to(W.ROOT).as_posix(), 'sha256': W.sha(path)}


def _bound(binding):
    path = _owned(W.ROOT / binding['ref'])
    W.require(W.sha(path) == binding['sha256'], 'Continuation evidence changed: ' + binding['ref'])
    return path


def _ro(path):
    return sqlite3.connect(_owned(path).as_uri() + '?mode=ro', uri=True)


def _snapshot_check(snapshot, identity):
    body = base64.b64decode(snapshot['state_base64'], validate=True)
    check = {key: snapshot[key] for key in FIELDS[:4]}
    check.update(kind='gegi_compton_candidate_checkpoint_v1', state_sha256=hashlib.sha256(body).hexdigest())
    W.require(snapshot['identity_sha256'] == W.digest(identity) and
              W.digest(check) == snapshot['checkpoint_sha256'] and isinstance(json.loads(body), dict), 'Invalid prior checkpoint')


def _checkpoint(db, identity):
    W.require(json.loads(db.execute('SELECT body FROM metadata').fetchone()[0])['identity'] == identity, 'Original candidate identity changed')
    row = db.execute('SELECT ' + ','.join(FIELDS) + ' FROM checkpoint WHERE singleton=1').fetchone()
    W.require(row is not None, 'Upgrade requires a saved acquisition checkpoint')
    snapshot = dict(zip(FIELDS, row)); snapshot['state_base64'] = base64.b64encode(snapshot.pop('state')).decode('ascii')
    _snapshot_check(snapshot, identity)
    last = db.execute('SELECT trigger_id,record_sha256 FROM triggers ORDER BY trigger_id DESC LIMIT 1').fetchone()
    candidate = db.execute("SELECT trigger_id FROM triggers WHERE decision='candidate' ORDER BY trigger_id DESC LIMIT 1").fetchone()
    W.require((snapshot['last_trigger_id'], snapshot['last_record_sha256']) == (last or (0, None)) and
              snapshot['last_candidate_trigger_id'] == (candidate[0] if candidate else 0), 'Checkpoint trigger boundary changed')
    return snapshot


def _changes(old, new, allowed, *, additions=False):
    W.require((set(old) <= set(new) if additions else set(old) == set(new)) and
              all(key in allowed or old.get(key) == value for key, value in new.items()), 'Undeclared producer changes')


def _contracts(old_identity, new_identity, old, new):
    W.require(set(old_identity) == set(new_identity) and
              {k: v for k, v in old_identity.items() if k not in ('source_sha256', 'native_request_sha256')} ==
              {k: v for k, v in new_identity.items() if k not in ('source_sha256', 'native_request_sha256')}, 'Acquisition physics/config identity changed')
    _changes(old_identity['source_sha256'], new_identity['source_sha256'], ROOT_CHANGES, additions=True)
    W.require(set(new_identity['source_sha256']) - set(old_identity['source_sha256']) <= {'tools/gegi_native_continuation.py'}, 'Unexpected new root producer')
    W.require('response_mode' not in old and new.get('response_mode') == E.NATIVE_SIGNAL_ONLY and
              {k: v for k, v in old.items() if k != 'source_sha256'} ==
              {k: v for k, v in new.items() if k not in ('source_sha256', 'response_mode')}, 'Only native-only response mode may change')
    _changes(old['source_sha256'], new['source_sha256'], WORKER_CHANGES)


def _proof(output, proof, old_sha, new_sha):
    W.require(proof['kind'] == 'gegi_native_signals_only_equivalence_v1' and proof['status'] == 'passed_exact' and
              proof['original_request_sha256'] == old_sha and proof['new_request_sha256'] == new_sha and
              proof['contact_ids'] == list(range(1, 35)) and all(proof[key] is True for key in
              ('all34_float64_native_equal', 'endpoint_records_equal', 'status_equal', 'truth_edep_equal')), 'Exact paired proof required')
    key = (proof['event_id'], proof['group_id'])
    with closing(_ro(output / 'native-scratch.sqlite')) as db:
        W.require(json.loads(db.execute('SELECT body FROM identity').fetchone()[0])['identity']['request_sha256'] == old_sha, 'Original native identity changed')
        W.require(db.execute('SELECT input_sha256 FROM events WHERE primary_id=? AND group_id=?', key).fetchone() == (proof['input_group_sha256'],), 'Original group input changed')
        store = object.__new__(E.Store); store.db = db
        event, signals = store.read(*key, with_signals=True)
    for field, actual in (('native_arrays_sha256', native_array_digest(signals)), ('endpoints_sha256', endpoints_digest(event))):
        W.require(proof[field] == {'original': actual, 'native_only': actual}, 'Saved original native data differ from paired proof')
    W.require(proof['original_status'] == proof['native_only_status'] == event['status'] and
              proof['original_truth_edep_keV'] == proof['native_only_truth_edep_keV'] == event['truth_edep_keV'], 'Saved native status/truth changed')
    with closing(_ro(output / 'compton-candidates.sqlite')) as db:
        W.require(db.execute('SELECT input_sha256 FROM input_groups WHERE parent=? AND group_id=?', key).fetchone() == (proof['input_group_sha256'],), 'Proof is not a saved acquisition group')


def prepare(output, new_identity, request, proof_path, producer_package):
    """Explicit upgrade only, under caller's execution lease with workers stopped."""
    output, request, proof_path, producer_package = map(_owned, (output, request, proof_path, producer_package))
    W.require(not (output / 'native-only-continuation.json').exists() and not (output / 'native-only').exists(), 'Continuation already exists; preserve it')
    with closing(_ro(output / 'compton-candidates.sqlite')) as db:
        old_identity = json.loads(db.execute('SELECT body FROM metadata').fetchone()[0])['identity']
        W.require(not db.execute('SELECT 1 FROM completion').fetchone(), 'Completed acquisition cannot upgrade')
        prior = _checkpoint(db, old_identity)
    old_request = output / 'native-request.json'; old, new = W.read(old_request), W.read(request)
    W.require(W.sha(old_request) == old_identity['native_request_sha256'] and W.sha(request) == new_identity['native_request_sha256'], 'Request/producer identity mismatch')
    _contracts(old_identity, new_identity, old, new)
    _proof(output, W.read(proof_path), W.sha(old_request), W.sha(request))
    with zipfile.ZipFile(producer_package) as package:
        for ref, digest in (old['source_sha256'] | old_identity['source_sha256']).items():
            W.require(hashlib.sha256(package.read('END2END-Ge-Student/' + ref)).hexdigest() == digest, 'Original producer package mismatch: ' + ref)
    namespace = output / 'native-only'; namespace.mkdir()
    for target, source in (('native-request.json', request), ('equivalence-proof.json', proof_path)):
        with (namespace / target).open('xb') as handle: handle.write(source.read_bytes()); handle.flush(); os.fsync(handle.fileno())
    W.write(namespace / 'prior-checkpoint.json', prior, fresh=True)
    receipt = {'kind': KIND, 'old_identity': old_identity, 'new_identity': new_identity,
        'old_checkpoint_sha256': prior['checkpoint_sha256'], 'prior_checkpoint_binding': _binding(namespace / 'prior-checkpoint.json'),
        'proof_binding': _binding(namespace / 'equivalence-proof.json'), 'new_request_binding': _binding(namespace / 'native-request.json'),
        'original_request_binding': _binding(old_request), 'original_native_store_binding': _binding(output / 'native-scratch.sqlite'),
        'original_producer_package_binding': _binding(producer_package)}
    W.write(output / 'native-only-continuation.json', receipt, fresh=True)
    return receipt


def admit(output, current_identity):
    """Return the original identity and active namespace, or None without receipt."""
    if not (Path(output) / 'native-only-continuation.json').exists(): return None
    output = _owned(output); receipt = W.read(output / 'native-only-continuation.json')
    W.require(receipt['kind'] == KIND and current_identity == receipt['new_identity'], 'Continuation producer identity changed')
    paths = {key: _bound(value) for key, value in receipt.items() if key.endswith('_binding')}
    old, new = W.read(paths['original_request_binding']), W.read(paths['new_request_binding'])
    W.require(paths['original_request_binding'] == output / 'native-request.json' and
              paths['original_native_store_binding'] == output / 'native-scratch.sqlite' and
              paths['new_request_binding'] == output / 'native-only/native-request.json', 'Continuation paths changed')
    W.require(W.sha(paths['original_request_binding']) == receipt['old_identity']['native_request_sha256'] and
              W.sha(paths['new_request_binding']) == current_identity['native_request_sha256'], 'Continuation request identity changed')
    _contracts(receipt['old_identity'], current_identity, old, new)
    prior = W.read(paths['prior_checkpoint_binding']); _snapshot_check(prior, receipt['old_identity'])
    W.require(prior['checkpoint_sha256'] == receipt['old_checkpoint_sha256'], 'Prior checkpoint binding changed')
    with closing(_ro(output / 'compton-candidates.sqlite')) as db:
        current = _checkpoint(db, receipt['old_identity'])
        W.require(current['last_trigger_id'] >= prior['last_trigger_id'], 'Acquisition checkpoint regressed')
    _proof(output, W.read(paths['proof_binding']), W.sha(paths['original_request_binding']), W.sha(paths['new_request_binding']))
    return {'original_identity': receipt['old_identity'], 'active_request': str(paths['new_request_binding']),
        'active_spool': str(_owned(output / 'native-only/native-spool')),
        'active_store': str(_owned(output / 'native-only/native-scratch.sqlite')), 'receipt': receipt}
