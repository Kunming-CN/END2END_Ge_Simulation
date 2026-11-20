"""Checkpointed fresh joint-source blocks; no action implicitly starts radiation.

The parent clock is independent of transport randomness. Each serial remage
block restores the preceding true CLHEP state, and preserves native daughter
delays once. The consumer owns the chronological future-deposit queue/readout.
"""
from __future__ import annotations
import argparse
import ast
from contextlib import closing
import copy
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import random
import re
import shlex
import shutil
import sqlite3
import subprocess
import time

import gegi_mixed_source as M

S = M.S
h = M.h
KIND = 'gegi_streaming_source_config_v1'
CHECKPOINT = 'gegi_streaming_source_checkpoint_v1'
BLOCK = 'gegi_streaming_source_block_v1'
RNG_SOURCE = r'''#include "RMGDefaultCli.hh"
#include "G4GenericMessenger.hh"
#include "Randomize.hh"
#include <string>
struct StateWriter {
  void Save(const std::string& name) { CLHEP::HepRandom::saveEngineStatus(name.c_str()); }
};
int main(int argc, char** argv) {
  StateWriter writer;
  G4GenericMessenger messenger(&writer, "/GeSignal/RNG/", "Exact current serial CLHEP state");
  messenger.DeclareMethod("Save", &StateWriter::Save).SetStates(G4State_Idle);
  RMGDefaultCli app;
  app.ParseCliArgs(argc, argv);
  app.SetupLoggingAndIpc();
  return app.RunSimulation(argc, argv);
}
'''


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def default_config(*, parent_count=100, duration_ns=None, seed=20261120, acquisition_id='streaming100'):
    old = M.default_config(seed=seed, acquisition_id=acquisition_id)
    return {'kind': KIND, 'acquisition_id': acquisition_id, 'seed': seed, 'clock_seed': seed,
            'stop': {'mode': 'count', 'parent_count': parent_count} if duration_ns is None else
                    {'mode': 'duration', 'duration_ns': duration_ns},
            'sources': old['sources'], 'initial_state': old['initial_state']}


def validate(config):
    h.require(type(config) is dict and set(config) == set(default_config()) and config['kind'] == KIND,
              'Unsupported streaming source configuration')
    legacy = M.default_config(primary_count=1, seed=config['seed'], acquisition_id=config['acquisition_id'])
    legacy.update({key: config[key] for key in ('clock_seed', 'sources', 'initial_state')})
    M.validate_config(legacy)
    stop = config['stop']
    h.require(type(stop) is dict, 'Specify one fixed duration or parent count')
    if stop.get('mode') == 'count':
        h.require(set(stop) == {'mode', 'parent_count'} and type(stop['parent_count']) is int and
                  1 <= stop['parent_count'] <= 100_000_000, 'Invalid total parent count')
    else:
        h.require(set(stop) == {'mode', 'duration_ns'} and stop.get('mode') == 'duration' and
                  type(stop['duration_ns']) in (int, float) and math.isfinite(stop['duration_ns']) and
                  stop['duration_ns'] > 0, 'Invalid half-open acquisition duration [0,T)')
    return config


def _tuple(value):
    return tuple(_tuple(v) for v in value) if isinstance(value, list) else value


def initialize(config):
    validate(config)
    return {'kind': CHECKPOINT, 'config_sha256': digest(config), 'acquisition_id': config['acquisition_id'],
            'next_parent_id': 0, 'last_parent_time_ns': 0., 'pending_parent': None,
            'rng_state': random.Random(config['clock_seed']).getstate(), 'finished': False,
            'safe_frontier_ns': 0., 'next_block_index': 0, 'transport_rng': None}


def _admit(config, checkpoint):
    validate(config)
    h.require(checkpoint['kind'] == CHECKPOINT and checkpoint['config_sha256'] == digest(config) and
              checkpoint['acquisition_id'] == config['acquisition_id'], 'Source checkpoint/configuration mismatch')
    h.require(type(checkpoint['next_parent_id']) is int and checkpoint['next_parent_id'] >= 0 and
              type(checkpoint['next_block_index']) is int and checkpoint['next_block_index'] >= 0,
              'Invalid immutable source checkpoint identities')


def next_block(config, checkpoint, max_parents=500):
    """Return at most 500 new parents and the exact continuation state.

    One look-ahead arrival is retained, never discarded/re-drawn at a boundary.
    A parent stream frontier permits committing only earlier physical emissions.
    """
    _admit(config, checkpoint)
    h.require(type(max_parents) is int and 1 <= max_parents <= 500, 'Use 1–500 parents per block')
    state = copy.deepcopy(checkpoint); state['rng_state'] = _tuple(state['rng_state'])
    if state['finished']: return [], state
    rng = random.Random(); rng.setstate(state['rng_state'])
    rate = math.fsum(source['activity_Bq'] for source in config['sources'])
    probability = config['sources'][0]['activity_Bq']/rate
    stop = config['stop']; parents = []
    def draw():
        clock = state['last_parent_time_ns']+rng.expovariate(rate)*1e9
        source = config['sources'][int(rng.random() >= probability)]
        preset = S.registered_preset(source['id'])
        return {'acquisition_id': config['acquisition_id'], 'parent_decay_id': state['next_parent_id'],
                'event_id': state['next_parent_id'], 'source_id': source['id'], 'isotope': preset['isotope'],
                'source_pdg': S.cs.ION if source['id'] == S.CS137 else preset['pdg'],
                'source_position_global_mm': source['position_global_mm'], 'absolute_parent_time_ns': clock}
    while len(parents) < max_parents:
        if stop['mode'] == 'count' and state['next_parent_id'] >= stop['parent_count']:
            state['finished'] = True; break
        parent = state['pending_parent'] or draw(); state['pending_parent'] = None
        if stop['mode'] == 'duration' and parent['absolute_parent_time_ns'] >= stop['duration_ns']:
            state['pending_parent'] = parent; state['finished'] = True; break
        parents.append(parent)
        state['next_parent_id'] += 1; state['last_parent_time_ns'] = parent['absolute_parent_time_ns']
    if not state['finished']:
        if stop['mode'] == 'count' and state['next_parent_id'] >= stop['parent_count']:
            state['finished'] = True
        else:
            state['pending_parent'] = draw()
            if stop['mode'] == 'duration' and state['pending_parent']['absolute_parent_time_ns'] >= stop['duration_ns']:
                state['finished'] = True
    state['rng_state'] = rng.getstate()
    state['safe_frontier_ns'] = (stop['duration_ns'] if state['finished'] and stop['mode'] == 'duration'
                                 else state['last_parent_time_ns'])
    if parents: state['next_block_index'] += 1
    return parents, state


def iter_blocks(config, checkpoint=None, max_parents=500):
    state = initialize(config) if checkpoint is None else checkpoint
    while not state['finished']:
        parents, state = next_block(config, state, max_parents)
        yield parents, state


def _binding(path):
    path = h.local_path(path)
    return {'ref': path.relative_to(h.ROOT).as_posix(), 'sha256': h.sha256(path)}


def _bound(binding):
    path = h.local_path(h.ROOT/binding['ref'])
    h.require(h.sha256(path) == binding['sha256'], 'Bound source artifact changed: '+binding['ref'])
    return path


def _pins():
    return {**S.source_pins(), 'transport/gegi_mixed_source.py': h.sha256(M.__file__),
            'transport/gegi_streaming_source.py': h.sha256(__file__)}


def build_rng_adapter(context):
    """Build only the missing Save command around installed RMGDefaultCli."""
    directory = h.local_path(context/'rng-cli'); receipt_path = directory/'build.json'
    source_sha = hashlib.sha256(RNG_SOURCE.encode()).hexdigest()
    if receipt_path.exists():
        receipt = S.load(receipt_path)
        h.require(receipt['status'] == 'complete' and receipt['source_sha256'] == source_sha and
                  h.sha256(directory/'gegi-rng-remage') == receipt['executable_sha256'], 'RNG adapter build changed')
        return directory/'gegi-rng-remage'
    h.require(not directory.exists(), 'Preserve interrupted RNG adapter build')
    directory.mkdir()
    h.write_new(directory/'main.cc', RNG_SOURCE)
    prefix = Path(S.sys.prefix)
    compiler = shutil.which(os.environ.get('CXX', 'c++'))
    h.require(compiler is not None and Path(compiler).resolve().is_relative_to(prefix.resolve()),
              'Use the existing locked transport compiler')
    flags = {name: shlex.split(subprocess.check_output(['geant4-config', name], text=True))
             for name in ('--cflags', '--libs')}
    command = [compiler, *flags['--cflags'], '-std=c++17', '-O2', '-I'+str(prefix/'include/remage'),
               str(directory/'main.cc'), '-L'+str(prefix/'lib'), '-Wl,-rpath,'+str(prefix/'lib'),
               '-lremage', *flags['--libs'], '-o', str(directory/'gegi-rng-remage')]
    receipt = {'status': 'failed', 'source_sha256': source_sha, 'command': command}
    try:
        with (directory/'build.log').open('x') as log:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=False)
        receipt['returncode'] = result.returncode
        h.require(result.returncode == 0, 'RNG adapter build failed; preserve build.log')
        receipt.update(status='complete', executable_sha256=h.sha256(directory/'gegi-rng-remage'))
        return directory/'gegi-rng-remage'
    finally:
        h.publish_json(receipt_path, receipt)


def _context(config, directory):
    context = h.local_path(directory.parent/'source-context')
    legacy = M.default_config(primary_count=1, seed=config['seed'], acquisition_id=config['acquisition_id'])
    legacy.update({key: config[key] for key in ('clock_seed', 'sources', 'initial_state')})
    if not context.exists(): M.prepare(legacy, context)  # geometry only; zero radiation calls
    meta = S.load(context/'prepared.json')
    h.require(meta['checked']['config'] == legacy, 'Shared geometry context belongs to another source configuration')
    for ref, sha in meta['files_sha256'].items():
        h.require(h.sha256(context/ref) == sha, 'Shared source context changed: '+ref)
    S.geometry_log_check(context, meta['checked'])
    return context, meta, build_rng_adapter(context)


def block_macro(plan, count, restore=False):
    legacy = copy.deepcopy(plan); legacy['config']['primary_count'] = count
    text = M.macro(legacy)
    beam = '/run/beamOn '+str(count)
    checkpoint = ('/random/resetEngineFrom rng-input.rndm\n' if restore else '')
    checkpoint += '/GeSignal/RNG/Save rng-before.rndm\n'+beam+'\n/GeSignal/RNG/Save rng-after.rndm'
    return text.replace(beam, checkpoint)


def prepare_block(config, checkpoint, output, max_parents=500):
    _admit(config, checkpoint); directory = h.local_path(output)
    if (directory/'seal.json').exists():
        verify(directory)
        saved = S.load(directory/'prepared.json')
        h.require(saved['config'] == config and saved['checkpoint_before_sha256'] == digest(checkpoint),
                  'Sealed block belongs to another checkpoint/configuration')
        return saved
    h.require(not directory.exists(), 'Preserve existing incomplete block; do not restart implicitly')
    parents, after = next_block(config, checkpoint, max_parents)
    h.require(parents, 'Source clock is exhausted; no radiation block is needed')
    transport_rng = checkpoint['transport_rng']
    if checkpoint['next_parent_id']:
        h.require(transport_rng is not None, 'Continuation requires the sealed preceding CLHEP state')
        previous = _bound(transport_rng).parent
        verify(previous)
        h.require(S.load(previous/'checkpoint-after.json') == json.loads(json.dumps(checkpoint)),
                  'Source/transport checkpoint does not match the preceding sealed block')
    context, context_meta, executable = _context(config, directory)
    directory.mkdir(parents=True)
    h.publish_json(directory/'checkpoint-before.json', checkpoint)
    h.publish_json(directory/'clock-after.json', after)
    h.write_new(directory/'parents.jsonl', M.json_lines(parents))
    M.write_primaries(directory/'primaries.lh5', parents)
    h.write_new(directory/'geometry.gdml', (context/'geometry.gdml').read_text())
    h.write_new(directory/'run.mac', block_macro(context_meta['checked'], len(parents), transport_rng is not None))
    if transport_rng is not None:
        with _bound(transport_rng).open('rb') as original, (directory/'rng-input.rndm').open('xb') as copy_to:
            shutil.copyfileobj(original, copy_to)
    meta = {'kind': BLOCK, 'status': 'prepared', 'config': config,
            'block_index': checkpoint['next_block_index'], 'primary_count': len(parents),
            'first_parent_id': parents[0]['parent_decay_id'], 'last_parent_id': parents[-1]['parent_decay_id'],
            'context': _binding(context/'prepared.json'), 'executable': _binding(executable),
            'checkpoint_before_sha256': digest(checkpoint), 'source_sha256': _pins(),
            'files_sha256': {path.name: h.sha256(path) for path in directory.iterdir() if path.is_file()}}
    h.publish_json(directory/'prepared.json', meta)
    return meta


def _prepared(directory):
    directory = h.local_path(directory); meta = S.load(directory/'prepared.json')
    h.require(meta['kind'] == BLOCK and meta['status'] == 'prepared', 'Unsupported transport block')
    compatibility = _extraction_compatibility(directory, meta)
    for ref, sha in meta['source_sha256'].items():
        actual = h.sha256(h.ROOT/ref)
        h.require(actual == sha or (compatibility.get(ref, {}).get('old_sha256') == sha and
                  compatibility[ref]['new_sha256'] == actual), 'Streaming source changed: '+ref)
    retired = _retired(directory)
    for ref, sha in meta['files_sha256'].items(): _check_artifact(directory, ref, sha, retired)
    context_meta = S.load(_bound(meta['context']))
    _bound(meta['executable'])
    before = S.load(directory/'checkpoint-before.json')
    parents, after = next_block(meta['config'], before, meta['primary_count'])
    h.require(digest(before) == meta['checkpoint_before_sha256'] and
              hashlib.sha256(M.json_lines(parents).encode()).hexdigest() == meta['files_sha256']['parents.jsonl'] and
              S.load(directory/'clock-after.json') == json.loads(json.dumps(after)) and
              (directory/'run.mac').read_text() == block_macro(context_meta['checked'], len(parents), before['transport_rng'] is not None),
              'Rehashed source block clock or macro semantics changed')
    return directory, meta, context_meta, parents


def _extraction_compatibility(directory, meta):
    path = directory/'extraction-compatibility.json'
    if not path.exists(): return {}
    record = S.load(path)
    h.require(record['kind'] == 'gegi_native_uid_extraction_repair_v1' and
              record['prepared_sha256'] == h.sha256(directory/'prepared.json') and
              record['run_sha256'] == h.sha256(directory/'run.json'), 'Extraction repair belongs to another completed block')
    allowed = {'transport/gegi_source.py', 'transport/gegi_streaming_source.py'}
    h.require(set(record['source_changes']) <= allowed, 'Extraction repair cannot change physics dependencies')
    run = S.load(directory/'run.json')
    h.require(record['source_lh5_sha256'] == run['source_lh5_sha256'] and
              record['rng_before_sha256'] == run['rng_before_sha256'] and
              record['rng_after_sha256'] == run['rng_after_sha256'] and
              record['macro_sha256'] == meta['files_sha256']['run.mac'], 'Extraction repair changed transport proof')
    for change in record['source_changes'].values(): _bound(change['original_source'])
    return record['source_changes']


def repair_extraction(directory):
    """One explicit reader repair for the preserved native empty-alias failure."""
    directory = h.local_path(directory); meta = S.load(directory/'prepared.json'); run = S.load(directory/'run.json')
    h.require(run['status'] == 'complete' and not (directory/'seal.json').exists() and
              h.sha256(directory/'truth.lh5') == run['source_lh5_sha256'], 'Repair requires original completed, unsealed transport')
    originals = {'transport/gegi_source.py': ('reader-before-extraction-repair.py', {'events'}),
                 'transport/gegi_streaming_source.py': ('source-before-extraction-repair.py',
                    {'_prepared', '_extraction_compatibility', 'repair_extraction', '_same_except', 'events', 'main'})}
    changes = {}
    for ref, (snapshot, permitted_functions) in originals.items():
        old = meta['source_sha256'][ref]
        h.require(h.sha256(directory/snapshot) == old and
                  _same_except((directory/snapshot).read_text(), (h.ROOT/ref).read_text(), permitted_functions),
                  'Extraction repair changed code outside its explicit reader/compatibility boundary')
        changes[ref] = {'old_sha256': old, 'new_sha256': h.sha256(h.ROOT/ref),
                        'original_source': _binding(directory/snapshot),
                        'permitted_functions': sorted(permitted_functions)}
    import h5py
    with h5py.File(directory/'truth.lh5') as raw:
        h.require(isinstance(raw['stp/__by_uid__'], h5py.Group) and len(raw['stp/__by_uid__']) == 0,
                  'The raw file is not the identified native empty-alias case')
    record = {'kind': 'gegi_native_uid_extraction_repair_v1', 'source_changes': changes,
              'prepared_sha256': h.sha256(directory/'prepared.json'), 'run_sha256': h.sha256(directory/'run.json'),
              'source_lh5_sha256': run['source_lh5_sha256'], 'macro_sha256': meta['files_sha256']['run.mac'],
              'rng_before_sha256': run['rng_before_sha256'], 'rng_after_sha256': run['rng_after_sha256'],
              'scope': 'Read-only native empty-UID-alias adapter; exact named tables, columns, ancestry, geometry and census remain checked. No transport or RNG execution.'}
    h.publish_json(directory/'extraction-compatibility.json', record)
    failed = h.local_path(directory/'stream')
    if failed.exists():
        h.require(not (failed/'manifest.json').exists(), 'Completed extraction cannot be replaced')
        failed.rename(h.local_path(directory/'stream-failed-uid-alias'))
    return extract(directory)


def _same_except(original, current, permitted_functions):
    """Keep source clock, geometry, macro, RNG adapter and transport code equal."""
    def filtered(text):
        syntax = ast.parse(text)
        syntax.body = [node for node in syntax.body if not (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in permitted_functions
            or isinstance(node, ast.Import) and all(alias.name == 'ast' for alias in node.names))]
        return ast.dump(syntax, include_attributes=False)
    return filtered(original) == filtered(current)


def _retired(directory):
    """Only the consumer's explicit sealed-artifact retirement permits absence."""
    path = directory/'retired-artifacts.json'
    if not path.exists(): return {}
    record = S.load(path)
    h.require(record['kind'] == 'gegi_streaming_source_retirement_v1' and
              record['seal_sha256'] == h.sha256(directory/'seal.json'), 'Retirement differs from the sealed block')
    _bound(record['consumer_receipt'])
    seal = S.load(directory/'seal.json')
    allowed = {'truth.lh5', 'primaries.lh5', 'parents.jsonl', 'stream/events.jsonl'}
    h.require(set(record['artifacts']) <= allowed and all(seal['artifacts'].get(ref) == sha
              for ref, sha in record['artifacts'].items()), 'Retirement contains an unsealed or non-scratch artifact')
    return record['artifacts']


def _check_artifact(directory, ref, sha, retired):
    path = directory/ref
    if not path.exists(): h.require(retired.get(ref) == sha, 'Missing source artifact without verified retirement: '+ref)
    else: h.require(h.sha256(path) == sha, 'Source artifact changed: '+ref)


def events(directory):
    directory, block, meta, parents = _prepared(directory)
    meta = {**meta, 'primary_count': len(parents)}
    contracts = {row['contract']['id']: row['contract'] for row in meta['checked']['sources']}
    def for_event(local):
        p = parents[local]
        return {**meta, 'source_id': p['source_id'], 'source_contract': contracts[p['source_id']],
                'source_position_global_mm': p['source_position_global_mm'],
                'primary_vertex_time_ns': p['absolute_parent_time_ns']}
    for event in S.events(directory/'truth.lh5', meta, event_metadata=for_event, native_empty_uid_aliases=True):
        local = event['event_id']
        yield _decorate(event, parents[local], local, block['block_index'])


def _decorate(event, parent, local, block_index):
    origin = parent['absolute_parent_time_ns']
    event.update(parent, transport_event_id=local, block_index=block_index,
                 global_decay_id=parent['parent_decay_id'], initial_primary_id=parent['parent_decay_id'],
                 primary_time_ns=origin, parent_clock_policy='checkpointed_pre_transport_marked_poisson_v1')
    for ordinal, step in enumerate(event['steps']):
        # LH5 row indices are file-local provenance. A semantic deposit identity
        # must remain unchanged when the same parent moves to another block.
        step.update(absolute_time_ns=origin+step['time_ns'], positive_ge_deposit_ordinal=ordinal,
                    deposit_id=[parent['acquisition_id'], parent['parent_decay_id'], ordinal])
    for photon in event['decay_photons']:
        photon.update(absolute_time_ns=origin+photon['time_ns'],
                      emission_id=[parent['acquisition_id'], parent['parent_decay_id'], photon['track_id']])
    for track in event.get('tracks', []):
        track['global_track_id'] = [parent['acquisition_id'], parent['parent_decay_id'], track['trackid']]
    event['pulse_group_use'] = 'drift partition only; no electronics reset'
    return event


def run_block(directory):
    directory, meta, _, _ = _prepared(directory)
    if (directory/'seal.json').exists(): return verify(directory)
    h.require(not any((directory/name).exists() for name in ('run.json', 'run.log', 'truth.lh5')),
              'Existing interrupted transport remains preserved; never rerun implicitly')
    command = [str(_bound(meta['executable'])), '-t', '1', '--rand-seed', str(meta['config']['seed']),
               '-o', 'truth.lh5', '-g', 'geometry.gdml', '--', 'run.mac']
    receipt = {'kind': BLOCK, 'status': 'failed', 'command': command,
               'prepared_sha256': h.sha256(directory/'prepared.json')}
    started = time.perf_counter()
    try:
        with (directory/'run.log').open('x') as log:
            child = subprocess.Popen(command, cwd=directory, stdout=log, stderr=subprocess.STDOUT)
            _, status, usage = os.wait4(child.pid, 0)
            child.returncode = os.waitstatus_to_exitcode(status)
        receipt.update(returncode=child.returncode,
                       child_max_rss_bytes=int(usage.ru_maxrss)*(1 if S.platform.system() == 'Darwin' else 1024),
                       child_resource_scope='wait4 rusage for this one serial transport child')
        h.require(child.returncode == 0 and not re.search(S.DIAGNOSTIC, (directory/'run.log').read_text(errors='replace'), re.I),
                  'Fresh block transport failed; preserve all raw evidence')
        for name in ('rng-before.rndm', 'rng-after.rndm'):
            h.require((directory/name).stat().st_size > 500, 'Missing complete native CLHEP engine state')
        if (directory/'rng-input.rndm').exists():
            h.require((directory/'rng-before.rndm').read_bytes() == (directory/'rng-input.rndm').read_bytes(),
                      'Restored CLHEP state changed before the first new decay')
        receipt.update(status='complete', source_lh5_sha256=h.sha256(directory/'truth.lh5'),
                       rng_before_sha256=h.sha256(directory/'rng-before.rndm'),
                       rng_after_sha256=h.sha256(directory/'rng-after.rndm'))
        return receipt
    except BaseException as error:
        receipt['error'] = str(error); raise
    finally:
        receipt['elapsed_seconds'] = time.perf_counter()-started
        h.publish_json(directory/'run.json', receipt)


def extract(directory):
    directory, meta, _, parents = _prepared(directory)
    if (directory/'seal.json').exists(): return verify(directory)
    receipt = S.load(directory/'run.json')
    h.require(receipt['status'] == 'complete' and receipt['source_lh5_sha256'] == h.sha256(directory/'truth.lh5'),
              'Block transport incomplete or changed')
    dest = directory/'stream'; h.require(not dest.exists(), 'Preserve incomplete derived block'); dest.mkdir()
    counts = {'initial_primaries': 0, 'zero_deposit_primaries': 0, 'nonzero_primaries': 0,
              'positive_ge_rows': 0, 'pulse_groups': 0,
              'by_source': {source['id']: {'parents': 0, 'zero': 0, 'nonzero': 0}
                            for source in meta['config']['sources']}}
    with (dest/'events.jsonl').open('x', encoding='utf-8', newline='\n') as out:
        for event in events(directory):
            counts['initial_primaries'] += 1
            counts['nonzero_primaries' if event['steps'] else 'zero_deposit_primaries'] += 1
            isotope = counts['by_source'][event['source_id']]
            isotope['parents'] += 1; isotope['nonzero' if event['steps'] else 'zero'] += 1
            counts['positive_ge_rows'] += len(event['steps']); counts['pulse_groups'] += len(event['pulse_groups'])
            if event['steps']: out.write(M.json_lines([event]))
    h.require(counts['initial_primaries'] == len(parents), 'Local block census does not close')
    after = S.load(directory/'clock-after.json'); after['transport_rng'] = _binding(directory/'rng-after.rndm')
    h.publish_json(directory/'checkpoint-after.json', after)
    manifest = {'kind': 'gegi_event_stream_v1', 'source_kind': KIND, 'status': 'complete',
                'source_contract': meta['config'], 'source_id': M.SOURCE, 'source_sha256': meta['source_sha256'],
                'source_context': meta['context'], 'transport_executable': meta['executable'],
                'block_index': meta['block_index'], 'primary_count': len(parents), 'counts': counts,
                'zero_deposit_primaries': counts['zero_deposit_primaries'], 'nonzero_primaries': counts['nonzero_primaries'],
                'model_id': S.G.MODEL, 'model_sha256': S.G.MODEL_SHA, 'coordinate_transform': S.G.TRANSFORM,
                'events_file': 'events.jsonl', 'events_sha256': h.sha256(dest/'events.jsonl'),
                'parents_sha256': h.sha256(directory/'parents.jsonl'),
                'first_parent_id': meta['first_parent_id'], 'last_parent_id': meta['last_parent_id'],
                'safe_frontier_ns': after['safe_frontier_ns'], 'source_finished': after['finished'],
                'checkpoint_after': _binding(directory/'checkpoint-after.json'),
                'clock_policy': 'Native child/step time_ns is parent-relative; absolute_time_ns adds the immutable global parent clock once.',
                'daughter_policy': 'Every native delayed emission retained; consumer queues absolute future deposits across block boundaries.',
                'source_initialization': meta['config']['initial_state']}
    h.publish_json(dest/'manifest.json', manifest)
    seal = {'kind': BLOCK, 'status': 'sealed', 'block_index': meta['block_index'],
            'config_sha256': digest(meta['config']), 'counts': counts,
            'artifacts': {p.relative_to(directory).as_posix(): h.sha256(p) for p in directory.rglob('*') if p.is_file()}}
    h.publish_json(directory/'seal.json', seal)
    verify(directory)
    return manifest


def verify(directory):
    directory, meta, _, _ = _prepared(directory)
    seal = S.load(directory/'seal.json')
    h.require(seal['kind'] == BLOCK and seal['status'] == 'sealed' and seal['config_sha256'] == digest(meta['config']),
              'Source block is not sealed')
    retired = _retired(directory)
    for ref, sha in seal['artifacts'].items(): _check_artifact(directory, ref, sha, retired)
    return {'status': 'sealed', 'block_index': meta['block_index'], 'counts': seal['counts'],
            'seal_sha256': h.sha256(directory/'seal.json'), 'checkpoint_after': _binding(directory/'checkpoint-after.json')}


def retire(directory, consumer_receipt):
    """Retire this block's four raw scratch files only after durable ingestion."""
    directory = h.local_path(directory)
    verified = verify(directory)
    consumer_receipt = h.local_path(consumer_receipt); receipt = S.load(consumer_receipt)
    h.require(receipt['kind'] == 'gegi_streaming_source_consumer_receipt_v1' and receipt['status'] == 'committed' and
              receipt['block_index'] == verified['block_index'] and
              receipt['source_manifest_sha256'] == h.sha256(directory/'stream/manifest.json') and
              receipt['checkpoint_after_sha256'] == h.sha256(directory/'checkpoint-after.json'),
              'Consumer receipt does not bind this complete source block')
    database = h.local_path(h.ROOT/receipt['database_ref'])
    with closing(sqlite3.connect(database.resolve().as_uri()+'?mode=ro', uri=True)) as db:
        row = db.execute('SELECT manifest_sha256,after_state FROM source_blocks WHERE block_index=?',
                         (verified['block_index'],)).fetchone()
        manifest = S.load(directory/'stream/manifest.json')
        h.require(row is not None and row[0] == receipt['source_manifest_sha256'] and
                  json.loads(row[1]) == S.load(directory/'checkpoint-after.json'),
                  'Candidate database has not committed the matching source checkpoint')
        groups = db.execute('SELECT count(*) FROM input_groups WHERE parent BETWEEN ? AND ?',
                            (manifest['first_parent_id'], manifest['last_parent_id'])).fetchone()[0]
        h.require(groups == verified['counts']['pulse_groups'], 'Candidate database group census does not close')
    seal = S.load(directory/'seal.json')
    refs = ('truth.lh5', 'primaries.lh5', 'parents.jsonl', 'stream/events.jsonl')
    record = {'kind': 'gegi_streaming_source_retirement_v1', 'seal_sha256': verified['seal_sha256'],
              'consumer_receipt': _binding(consumer_receipt),
              'artifacts': {ref: seal['artifacts'][ref] for ref in refs},
              'scope': 'This new sealed block only; no RNG/checkpoint/provenance/failure evidence removed.'}
    target = directory/'retired-artifacts.json'
    if target.exists(): h.require(S.load(target) == record, 'Existing source retirement differs')
    else: h.publish_json(target, record)
    retired = 0
    for ref in refs:
        path = h.local_path(directory/ref)
        if path.exists():
            h.require(path.is_file() and h.sha256(path) == record['artifacts'][ref], 'Owned scratch changed before retirement')
            retired += path.stat().st_size; path.unlink()
    verify(directory)
    return {'status': 'retired_verified_source_scratch', 'retired_now_bytes': retired, 'block_index': verified['block_index']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('init', 'initialize', 'prepare-block', 'run-block', 'extract', 'verify', 'retire', 'repair-extraction'))
    parser.add_argument('--config'); parser.add_argument('--checkpoint'); parser.add_argument('--output')
    parser.add_argument('--directory'); parser.add_argument('--max-parents', type=int, default=500)
    parser.add_argument('--consumer-receipt')
    S.P.project_root_argument(parser, required=False); args = parser.parse_args(argv)
    if args.windows_root: S.P.project_identity(args.windows_root)
    if args.action in ('init', 'initialize'):
        value = initialize(S.load(args.config))
        if args.output: h.publish_json(h.local_path(args.output), value)
    elif args.action == 'prepare-block':
        config = S.load(args.config)
        value = prepare_block(config, S.load(args.checkpoint) if args.checkpoint else initialize(config), args.output, args.max_parents)
    elif args.action == 'retire': value = retire(args.directory, args.consumer_receipt)
    elif args.action == 'repair-extraction': value = repair_extraction(args.directory)
    else: value = {'run-block': run_block, 'extract': extract, 'verify': verify}[args.action](args.directory)
    print(json.dumps(value, sort_keys=True, allow_nan=False))


if __name__ == '__main__': main()
