"""One explicit streamed-ID repair; caller holds the lease and has no worker.

The nominal primary count and all physics stay unchanged. Phase 2 changes only
the native worker's ID validation policy, retaining phase 0/1 evidence and the
original candidate-store identity. One subsequent transport-link repair reuses
that namespace. No processing or store mutation occurs here.
"""
from contextlib import closing
import base64
import hashlib
import json
import os
from pathlib import Path
import zipfile
import zlib

import gegi_native_continuation as C
import scenario_workflow as W

KIND = 'gegi_stream_id_continuation_v1'
POLICY = 'streaming_transport_driver_v1'
MODULE = 'tools/gegi_stream_id_continuation.py'
NAMESPACE = 'stream-id-repair'
RECEIPT = 'stream-id-continuation.json'
FAILURE_STAGE = 'Resident worker failed: ArgumentError: Invalid original primary ID'
TRANSPORT_KIND = 'gegi_transport_link_continuation_v1'
TRANSPORT_NAMESPACE = 'transport-link-repair'
TRANSPORT_RECEIPT = 'transport-link-continuation.json'
TRANSPORT_FAILURE_STAGE = 'Source block did not complete. Its inputs, RNG state and error log are preserved.'
ROOT_CHANGES = {'tools/gegi_streaming_acquisition.py', 'tools/gegi_mixed_acquisition.py',
                'transport/gegi_streaming_source.py'}
WORKER_CHANGES = {'simulation/gegi_response.jl', 'simulation/gegi_campaign_response.jl',
                  'tools/gegi_campaign_response.py', 'tools/gegi_mixed_acquisition.py',
                  'transport/gegi_streaming_source.py'}


def _contracts(old_identity, new_identity, old, new):
    W.require(set(old_identity) == set(new_identity) and
              {k:v for k,v in old_identity.items() if k not in ('source_sha256','native_request_sha256')} ==
              {k:v for k,v in new_identity.items() if k not in ('source_sha256','native_request_sha256')},
              'Acquisition physics/config identity changed')
    C._changes(old_identity['source_sha256'], new_identity['source_sha256'], ROOT_CHANGES | {MODULE}, additions=True)
    W.require(set(new_identity['source_sha256'])-set(old_identity['source_sha256']) == {MODULE},
              'Only the stream-ID continuation producer may be added')
    W.require(old.get('response_mode') == new.get('response_mode') == 'native_signals_only_v1' and
              old.get('event_id_policy','finite_primary_count_v1') == 'finite_primary_count_v1' and
              new.get('event_id_policy') == POLICY and
              {k:v for k,v in old.items() if k not in ('source_sha256','event_id_policy')} ==
              {k:v for k,v in new.items() if k not in ('source_sha256','event_id_policy')},
              'Only the streamed original-ID policy may change')
    C._changes(old['source_sha256'],new['source_sha256'],WORKER_CHANGES)
    count=old['selection']['primary_count']
    W.require(type(count) is int and count > 0,'Retain the original positive nominal primary count')


def _package_check(path, identity, request):
    pins=dict(request['source_sha256'])
    for ref,value in identity['source_sha256'].items():
        W.require(ref not in pins or pins[ref] == value,'Conflicting prior producer pins: '+ref)
        pins[ref]=value
    with zipfile.ZipFile(path) as package:
        for ref,value in pins.items():
            W.require(hashlib.sha256(package.read('END2END-Ge-Student/'+ref)).hexdigest() == value,
                      'Prior producer package mismatch: '+ref)


def _state(snapshot):
    return json.loads(base64.b64decode(snapshot['state_base64'],validate=True))


def _provenance(state, identity, phase, receipt_path, receipt_sha):
    W.require(state.get('execution_provenance') == {
        'active_producer_identity':identity,'native_processing_phase':phase,
        'continuation_receipt':{'path':receipt_path,'sha256':receipt_sha}},
        'Checkpoint continuation phase/provenance changed')


def _failed_input(db, count, progress):
    W.require(progress.get('status') == 'failed' and progress.get('stage') == FAILURE_STAGE and
              progress.get('resumable') is True and progress.get('partial_data_retained') is True,
              'Repair requires the preserved original-ID worker failure')
    row=db.execute("SELECT ordinal,parent,group_id,onset_ns,last_ns,pending,input_sha256 FROM input_groups WHERE status='pending' ORDER BY onset_ns,ordinal LIMIT 1").fetchone()
    W.require(row is not None,'Repair requires the next original queued group')
    ordinal,event_id,group_id,onset,last,packed,input_sha=row
    W.require(type(event_id) is int and event_id >= count,'Next queued original ID does not cross the old finite-ID bound')
    body=zlib.decompress(packed)
    W.require(hashlib.sha256(body).hexdigest() == input_sha,'Failed queued native input changed')
    group=json.loads(body)
    W.require(group['event_id'] == event_id and group['group_id'] == group_id and
              group['group_origin_time_ns'] == onset and max(s['time_ns'] for s in group['steps']) == last,
              'Failed queued original identity/time changed')
    return {'ordinal':ordinal,'event_id':event_id,'group_id':group_id,'onset_ns':onset,'last_ns':last,
            'input_sha256':input_sha,'old_nominal_primary_count':count},body


def _copy_fresh(target, source):
    with Path(source).open('rb') as reader, Path(target).open('xb') as writer:
        writer.write(reader.read());writer.flush();os.fsync(writer.fileno())


def _json_fresh(path, value):
    # The caller's lease excludes concurrent preparation. Exclusive creation
    # preserves any partial evidence without requiring filesystem hard links.
    with Path(path).open('xb') as handle:
        handle.write(W.encoded(value));handle.flush();os.fsync(handle.fileno())


def prepare(output, new_identity, request, producer_package):
    """Preflight a failed phase-1 checkpoint, then preserve an explicit phase 2."""
    output,request,producer_package=map(C._owned,(output,request,producer_package))
    namespace=output/NAMESPACE
    W.require(not namespace.exists() and not (output/RECEIPT).exists(),'Stream-ID continuation already exists; preserve it')
    phase1_receipt=output/'native-only-continuation.json'
    old_identity=W.read(phase1_receipt)['new_identity']
    active=C.admit(output,old_identity)
    W.require(active is not None,'Stream-ID repair requires the admitted native-only phase')
    old_request=Path(active['active_request']);old,new=W.read(old_request),W.read(request)
    W.require(W.sha(old_request) == old_identity['native_request_sha256'] and
              W.sha(request) == new_identity['native_request_sha256'],'Request/producer identity mismatch')
    _contracts(old_identity,new_identity,old,new)
    W.require(W.read(output/'source-config.json') == old_identity['source_config'],'Original source physics/config changed')
    with closing(C._ro(output/'compton-candidates.sqlite')) as db:
        db.execute('BEGIN')
        W.require(not db.execute('SELECT 1 FROM completion').fetchone(),'Completed acquisition cannot repair IDs')
        prior=C._checkpoint(db,active['original_identity'])
        _provenance(_state(prior),old_identity,1,'native-only-continuation.json',W.sha(phase1_receipt))
        failed,body=_failed_input(db,old['selection']['primary_count'],W.read(output/'progress.json'))
    with closing(C._ro(active['active_store'])) as db:
        W.require(json.loads(db.execute('SELECT body FROM identity').fetchone()[0])['identity']['request_sha256'] ==
                  old_identity['native_request_sha256'],'Prior phase-1 native store identity changed')
    _package_check(producer_package,old_identity,old)
    namespace.mkdir()
    _copy_fresh(namespace/'native-request.json',request)
    _copy_fresh(namespace/'failure-progress.json',output/'progress.json')
    with (namespace/'failed-pending-group.json').open('xb') as handle:
        handle.write(body);handle.flush();os.fsync(handle.fileno())
    _json_fresh(namespace/'prior-checkpoint.json',prior)
    receipt={'kind':KIND,'old_identity':old_identity,'new_identity':new_identity,
        'original_identity':active['original_identity'],'native_phase':2,'failed_input':failed,
        'old_checkpoint_sha256':prior['checkpoint_sha256'],
        'prior_checkpoint_binding':C._binding(namespace/'prior-checkpoint.json'),
        'failed_progress_binding':C._binding(namespace/'failure-progress.json'),
        'failed_input_binding':C._binding(namespace/'failed-pending-group.json'),
        'new_request_binding':C._binding(namespace/'native-request.json'),
        'phase1_receipt_binding':C._binding(phase1_receipt),
        'phase1_request_binding':C._binding(old_request),
        'phase1_native_store_binding':C._binding(active['active_store']),
        'phase1_producer_package_binding':C._binding(producer_package)}
    _json_fresh(output/RECEIPT,receipt)
    return receipt


def _admit_phase2(output, current_identity, *, bridge=None):
    """Read-only admission of the same original acquisition and phase-2 namespace."""
    output=Path(output)
    if not (output/RECEIPT).exists():
        W.require(not (output/NAMESPACE).exists(),'Partial stream-ID continuation; preserve its evidence')
        return None
    output=C._owned(output)
    receipt=W.read(output/RECEIPT)
    W.require(receipt['kind'] == KIND and receipt['native_phase'] == 2 and
              receipt['new_identity'] == current_identity,'Stream-ID continuation producer identity changed')
    paths={key:C._bound(value) for key,value in receipt.items() if key.endswith('_binding')}
    active=C.admit(output,receipt['old_identity'])
    W.require(active is not None and active['original_identity'] == receipt['original_identity'] and
              paths['phase1_receipt_binding'] == output/'native-only-continuation.json' and
              paths['phase1_request_binding'] == Path(active['active_request']) and
              paths['phase1_native_store_binding'] == Path(active['active_store']) and
              paths['new_request_binding'] == output/NAMESPACE/'native-request.json',
              'Stream-ID continuation paths/original identity changed')
    old,new=W.read(paths['phase1_request_binding']),W.read(paths['new_request_binding'])
    W.require(W.sha(paths['phase1_request_binding']) == receipt['old_identity']['native_request_sha256'] and
              W.sha(paths['new_request_binding']) == current_identity['native_request_sha256'],'Stream-ID request identity changed')
    _contracts(receipt['old_identity'],current_identity,old,new)
    _package_check(paths['phase1_producer_package_binding'],receipt['old_identity'],old)
    prior=W.read(paths['prior_checkpoint_binding']);C._snapshot_check(prior,receipt['original_identity'])
    W.require(prior['checkpoint_sha256'] == receipt['old_checkpoint_sha256'],'Prior checkpoint binding changed')
    _provenance(_state(prior),receipt['old_identity'],1,'native-only-continuation.json',W.sha(paths['phase1_receipt_binding']))
    failed=receipt['failed_input'];group=W.read(paths['failed_input_binding'])
    W.require(W.sha(paths['failed_input_binding']) == failed['input_sha256'] and
              group['event_id'] == failed['event_id'] and group['group_id'] == failed['group_id'] and
              failed['event_id'] >= old['selection']['primary_count'],'Preserved failed original input changed')
    progress=W.read(paths['failed_progress_binding'])
    W.require(progress.get('status') == 'failed' and progress.get('stage') == FAILURE_STAGE,'Preserved ID-failure progress changed')
    with closing(C._ro(output/'compton-candidates.sqlite')) as db:
        db.execute('BEGIN')
        current=C._checkpoint(db,receipt['original_identity'])
        W.require(current['last_trigger_id'] >= prior['last_trigger_id'],'Acquisition checkpoint regressed')
        row=db.execute('SELECT parent,group_id,input_sha256 FROM input_groups WHERE ordinal=?',(failed['ordinal'],)).fetchone()
        W.require(row == (failed['event_id'],failed['group_id'],failed['input_sha256']),'Original failed-group ledger association changed')
    checked=current
    if bridge is not None:
        C._snapshot_check(bridge,receipt['original_identity'])
        W.require(current['last_trigger_id'] >= bridge['last_trigger_id'] >= prior['last_trigger_id'],
                  'Transport bridge/acquisition checkpoint regressed')
        checked=bridge
    if checked != prior:
        _provenance(_state(checked),current_identity,2,RECEIPT,W.sha(output/RECEIPT))
    return {'active_request':str(paths['new_request_binding']),
            'active_store':str(C._owned(output/NAMESPACE/'native-scratch.sqlite')),
            'active_spool':str(C._owned(output/NAMESPACE/'native-spool')),
            'original_identity':receipt['original_identity'],'native_phase':2,
            'receipt_path':RECEIPT,'receipt':receipt}


def _transport_contracts(old_identity,new_identity):
    W.require(set(old_identity) == set(new_identity) and
              {k:v for k,v in old_identity.items() if k != 'source_sha256'} ==
              {k:v for k,v in new_identity.items() if k != 'source_sha256'},
              'Transport-link repair cannot change request/physics/config identity')
    C._changes(old_identity['source_sha256'],new_identity['source_sha256'],
               {MODULE,'transport/gegi_streaming_source.py'})
    W.require(old_identity['source_sha256']['transport/gegi_streaming_source.py'] !=
              new_identity['source_sha256']['transport/gegi_streaming_source.py'],
              'Transport-link repair requires its explicit source compatibility change')


def _transport_failure(progress):
    W.require(progress.get('status') == 'failed' and progress.get('stage') == TRANSPORT_FAILURE_STAGE and
              progress.get('resumable') is True and progress.get('partial_data_retained') is True,
              'Transport-link repair requires the preserved source-block failure')


def prepare_transport(output,new_identity,producer_package):
    """Bind the failed phase-2 bridge; keep its native store/request/spool intact."""
    output,producer_package=map(C._owned,(output,producer_package))
    namespace=output/TRANSPORT_NAMESPACE
    W.require(not namespace.exists() and not (output/TRANSPORT_RECEIPT).exists(),
              'Transport-link continuation already exists; preserve it')
    old_identity=W.read(output/RECEIPT)['new_identity']
    active=_admit_phase2(output,old_identity)
    W.require(active is not None,'Transport-link repair requires the admitted streamed-ID phase')
    _transport_contracts(old_identity,new_identity)
    W.require(W.read(output/'source-config.json') == old_identity['source_config'],'Original source physics/config changed')
    _transport_failure(W.read(output/'progress.json'))
    with closing(C._ro(output/'compton-candidates.sqlite')) as db:
        db.execute('BEGIN')
        W.require(not db.execute('SELECT 1 FROM completion').fetchone(),'Completed acquisition cannot repair transport links')
        bridge=C._checkpoint(db,active['original_identity'])
    _provenance(_state(bridge),old_identity,2,RECEIPT,W.sha(output/RECEIPT))
    index=_state(bridge)['source_checkpoint']['next_block_index']
    W.require(type(index) is int and index > 0 and
              not C._owned(output/'transport'/f'b{index:06d}').exists(),
              'Transport-link repair requires failure before the next source block exists')
    _package_check(producer_package,old_identity,W.read(active['active_request']))
    namespace.mkdir()
    _json_fresh(namespace/'bridge-checkpoint.json',bridge)
    _copy_fresh(namespace/'failure-progress.json',output/'progress.json')
    receipt={'kind':TRANSPORT_KIND,'old_identity':old_identity,'new_identity':new_identity,
        'original_identity':active['original_identity'],'native_phase':3,'next_block_index':index,
        'bridge_checkpoint_sha256':bridge['checkpoint_sha256'],
        'bridge_checkpoint_binding':C._binding(namespace/'bridge-checkpoint.json'),
        'failed_progress_binding':C._binding(namespace/'failure-progress.json'),
        'phase2_receipt_binding':C._binding(output/RECEIPT),
        'phase2_producer_package_binding':C._binding(producer_package)}
    _json_fresh(output/TRANSPORT_RECEIPT,receipt)
    return receipt


def admit(output,current_identity):
    """Select the latest explicit repair while checking every preserved phase."""
    output=Path(output)
    if not (output/TRANSPORT_RECEIPT).exists():
        W.require(not (output/TRANSPORT_NAMESPACE).exists(),'Partial transport-link continuation; preserve its evidence')
        return _admit_phase2(output,current_identity)
    output=C._owned(output);receipt=W.read(output/TRANSPORT_RECEIPT)
    W.require(receipt['kind'] == TRANSPORT_KIND and receipt['native_phase'] == 3 and
              receipt['new_identity'] == current_identity,'Transport-link continuation producer identity changed')
    paths={key:C._bound(value) for key,value in receipt.items() if key.endswith('_binding')}
    W.require(paths['phase2_receipt_binding'] == output/RECEIPT and
              paths['bridge_checkpoint_binding'] == output/TRANSPORT_NAMESPACE/'bridge-checkpoint.json' and
              paths['failed_progress_binding'] == output/TRANSPORT_NAMESPACE/'failure-progress.json',
              'Transport-link continuation paths changed')
    bridge=W.read(paths['bridge_checkpoint_binding'])
    C._snapshot_check(bridge,receipt['original_identity'])
    W.require(bridge['checkpoint_sha256'] == receipt['bridge_checkpoint_sha256'] and
              _state(bridge)['source_checkpoint']['next_block_index'] == receipt['next_block_index'],
              'Transport bridge checkpoint changed')
    active=_admit_phase2(output,receipt['old_identity'],bridge=bridge)
    W.require(active is not None and active['original_identity'] == receipt['original_identity'],
              'Transport-link original acquisition identity changed')
    _provenance(_state(bridge),receipt['old_identity'],2,RECEIPT,W.sha(paths['phase2_receipt_binding']))
    _transport_contracts(receipt['old_identity'],current_identity)
    _package_check(paths['phase2_producer_package_binding'],receipt['old_identity'],W.read(active['active_request']))
    _transport_failure(W.read(paths['failed_progress_binding']))
    with closing(C._ro(output/'compton-candidates.sqlite')) as db:
        current=C._checkpoint(db,receipt['original_identity'])
    if current != bridge:
        _provenance(_state(current),current_identity,3,TRANSPORT_RECEIPT,W.sha(output/TRANSPORT_RECEIPT))
    return {**active,'native_phase':3,'receipt_path':TRANSPORT_RECEIPT,'receipt':receipt}
