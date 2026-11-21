"""Compare a sealed native repair against the original continuous readout history."""

import argparse
import base64
from collections import Counter
from contextlib import closing
from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
import json
import math
from pathlib import Path
import platform
import sqlite3
from tempfile import TemporaryDirectory
import time
from zipfile import ZipFile
import zlib

import numpy as np

import gegi_candidate_storage as storage
import gegi_dual_source as dual
import gegi_pulse_stream as pulse
import gegi_streaming_readout as stream
from gegi_event_store import Store, encoded
from gegi_missing_history import MissingHistory, PRODUCER_SHA256 as MIXED_HISTORY_SHA256, native_support_ns
from gegi_native_continuation import _snapshot_check, native_array_digest
from gegi_native_failure_recovery import mask_overlap
import scenario_workflow as W


TRIGGER_SQL = ('SELECT trigger_id,trigger_time_ns,decision,reason,adc_sha256,record_sha256 '
               'FROM triggers WHERE trigger_time_ns>=? AND trigger_time_ns<? ORDER BY trigger_id')
TRIGGER_FIELDS = ('trigger_id', 'time_ns', 'decision', 'reason', 'candidate_adc_sha256', 'record_sha256')


def binding(path):
    return {'ref': str(path), 'sha256': W.sha(path), 'bytes': path.stat().st_size}


def bound(receipt):
    path = W.ROOT / receipt['ref']
    W.require(path.stat().st_size == receipt['bytes'] and W.sha(path) == receipt['sha256'],
              f'Input binding differs: {path}')
    return path


def readonly(path):
    return sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)


def legacy_history(checkpoint):
    """Load the exact history policy bound to this checkpoint from its producer archive."""
    original = bound(checkpoint['producer_archive'])
    with ZipFile(original) as package, TemporaryDirectory() as temporary:
        entry = 'END2END-Ge-Student/tools/gegi_missing_history.py'
        body = package.read(entry)
        path = Path(temporary) / 'gegi_missing_history.py'
        W.require(sha256(body).hexdigest() == checkpoint['source_sha256']['gegi_missing_history'],
                  'Original missing-history producer changed')
        path.write_bytes(body)
        spec = spec_from_file_location('_original_missing_history', path)
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
    return module.MissingHistory


def check_readout_sources(checkpoint, state, original_identity):
    modules = (stream, pulse, dual, stream.digital, stream.legacy, storage)
    state_pins = state['readout']['readout_source_sha256']
    pins = {**checkpoint['source_sha256'], 'gegi_candidate_storage':
            original_identity['source_sha256']['tools/gegi_candidate_storage.py']}
    pins[stream.legacy.__name__] = state_pins['exposure_stream']
    for module in modules:
        W.require(W.sha(Path(module.__file__)) == pins[module.__name__],
                  f'Original readout producer changed: {module.__name__}')


def response(store, row):
    ident = (row['event_id'], row['group_id'])
    meta, arrays = store.read(*ident, with_signals=True)
    W.require(meta['input_event_sha256'] == row['input_sha256'] and
              sha256(encoded(meta['input_group'])).hexdigest() == row['input_sha256'] and
              stream.digital.terminal_contacts_complete(meta) and set(arrays) == set(range(1, 35)),
              f'Expected one original terminal-complete all-electrode response: {ident}')
    return arrays


def response_store(path, stack, rows, recipe_sha256, channels):
    """Require the exact regenerated phase and census before exposing its pulse arrays."""
    completion_path = path.with_name('completion.json')
    ready_path = path.with_name('native-ready.json')
    completion, ready = W.read(completion_path), W.read(ready_path)
    with closing(readonly(path)) as db:
        store = Store.__new__(Store)
        store.path, store.db = path, db
        identity = json.loads(db.execute('SELECT body FROM identity').fetchone()[0])['identity']
        W.require(identity['request_sha256'] == ready['request_sha256'] == stack['request']['sha256'] and
                  identity['recipe_sha256'] == recipe_sha256 and
                  identity['original_producer_archive_sha256'] == stack['producer_archive']['sha256'],
                  'Regenerated response request differs from the original phase')
        sealed = db.execute('SELECT body FROM completion').fetchone()
        W.require(sealed is not None and json.loads(sealed[0]) == completion and
                  completion['status'] == 'completed' and completion['counts'] == {'completed': len(rows)},
                  'Regenerated native response store does not have its exact completion receipt')
        W.require(W.sha(ready_path) == completion['ready_sha256'] and
                  ready['field_cache_sha256'] == stack['field_cache']['sha256'] and not ready['new_field_solve'],
                  'Regenerated responses did not use the original verified field cache')
        W.require(set(store.keys()) == {(row['event_id'], row['group_id']) for row in rows},
                  'Regenerated native response census differs from the acceptance input')
        pulses = {row['ordinal']: pulse.prepare_native(response(store, row), channels, terminal_complete=True)
                  for row in rows}
    return pulses, dict(store=binding(path), completion=binding(completion_path), native_ready=binding(ready_path),
                        field_cache_precision_bits=ready['fields']['precision_bits'],
                        drift_precision_bits=stack['numerics']['precision_bits'])


def actual_repair(target):
    provenance = target['repaired_native']
    path = bound(provenance['store'])
    with closing(readonly(path)) as db:
        store = Store.__new__(Store)
        store.path, store.db = path, db
        row = target['identity']
        expected = db.execute('SELECT metadata_sha256 FROM events WHERE primary_id=? AND group_id=?',
                              (row['event_id'], row['group_id'])).fetchone()
        W.require(expected == (provenance['metadata_sha256'],), 'Repaired group metadata differs')
        arrays = response(store, row)
    W.require(native_array_digest(arrays) == provenance['signed_native_arrays_sha256'],
              'Repaired signed native signals differ')
    return arrays


def block_repairs(recipe, channels):
    """Use complete responses and configured horizons from the frozen per-group ledger."""
    available, unknown = {}, {}
    for phase, provenance in recipe['repair_sources'].items():
        identity = W.read(bound(provenance['identity']))
        request = W.read(bound(provenance['request']))
        bound(provenance['producer_archive'])
        prefix = provenance['ledger_prefix']
        with (W.ROOT / prefix['ref']).open('rb') as ledger:
            raw = ledger.read(prefix['bytes'])
        W.require(sha256(raw).hexdigest() == prefix['sha256'], 'Frozen repair ledger prefix differs')
        receipts = {row['ordinal']: row for line in raw.splitlines() if (row := json.loads(line))}
        support = native_support_ns(request['numerics'])
        numerics = provenance['readiness_drift_numerics']
        W.require(support == provenance['configured_native_support_ns'] == numerics['dt']*numerics['max_steps'],
                  'Configured native repair support differs')
        path = (bound(provenance['sealed_store']) if 'sealed_store' in provenance else
                W.ROOT / provenance['store_ref'])
        with closing(readonly(path)) as db:
            store = Store.__new__(Store)
            store.path, store.db = path, db
            W.require(json.loads(db.execute('SELECT body FROM identity').fetchone()[0])['identity'] == identity,
                      'Repair store identity differs')
            for target in recipe['repair_targets']:
                row, current = target['identity'], target['current_native']
                if current['phase'] != phase:
                    continue
                ordinal = row['ordinal']
                group = (row['event_id'], row['group_id'])
                entry = receipts[ordinal]
                completion = current['terminal_complete']
                info, arrays = store.read(*group, with_signals=completion)
                observed = db.execute('SELECT input_sha256,metadata_sha256 FROM events WHERE primary_id=? AND group_id=?',
                                      group).fetchone()
                W.require(entry['input_sha256'] == row['input_sha256'] and entry['complete'] == completion and
                          info['status'] == entry['new_status'] == current['status'] and
                          observed == (row['input_sha256'], current['metadata_sha256']) and
                          stream.digital.terminal_contacts_complete(info) == completion and
                          support == current['configured_native_support_ns'], f'Repair status or binding differs: {group}')
                if completion:
                    W.require(native_array_digest(arrays) == current['signed_native_arrays_sha256'],
                              f'Repaired signed native signals differ: {group}')
                    available[ordinal] = pulse.prepare_native(arrays, channels, terminal_complete=True)
                else:
                    unknown[ordinal] = support
    W.require(len(available) + len(unknown) == len(recipe['repair_targets']), 'Repair availability census does not close')
    return available, unknown


def run_branch(name, output, state, History, original_db, history, pulses, interval, identity, unknown_support=None):
    """Drive the original pulse, readout, and candidate stages on one saved clock."""
    start, stop = interval
    channels = state['channels']
    neighbors = dual._strip_neighbors(channels)
    history_state = state['missing_history']
    if unknown_support is None:
        missing = History.restore(history_state)
    else:
        W.require(history_state['failure_count'] == 0, 'Mixed support requires this empty original history anchor')
        missing = MissingHistory(history_state['live_time_ns'], max_active_failures=history_state['max_active_failures'])
    trigger_contexts = {}
    period = dual.SAMPLE_PERIOD_NS
    phase = state['readout']['settings']['phase_ns']
    first_index = state['readout']['next_sample_index']
    stop_index = math.ceil((stop-phase)/period)
    adc = np.empty((34, stop_index-first_index), dtype=np.int16)
    next_index = first_index
    database = output / (name + '.sqlite')

    def on_context(event, context):
        card = dual._trigger_card(event, neighbors, geometry=channels)
        reason = context['readout_rejection_reason']
        if missing.contains(event['rise_end_ns'], trigger_time_ns=event['trigger_time_ns']):
            reason = 'unknown_native_history'
        index0, index1 = (context[key] for key in ('first_sample_index', 'stop_sample_index'))
        first = index0 * dual.SAMPLE_PERIOD_NS + context['adc_phase_ns'] - 40 * stream.digital._TAU
        last = index1 * dual.SAMPLE_PERIOD_NS + context['adc_phase_ns']
        related = [row[0] for row in original_db.execute(
            'SELECT ordinal FROM input_groups WHERE onset_ns BETWEEN ? AND ? ORDER BY onset_ns,ordinal', (first, last))]
        observed = sink.observe(card, context, event=event, identities=related, rejection_reason=reason)
        trigger_contexts[observed['trigger_id']] = dict(
            rise_end_ns=event['rise_end_ns'], context_sample_indexes=[index0, index1], group_ordinals=related,
            all34_context_adc_sha256=sha256(np.asarray(context['adc_codes'], dtype='<i2', order='C').tobytes()).hexdigest())

    def on_adc(first, codes):
        nonlocal next_index
        end = first + codes.shape[1]
        W.require(first == next_index and end <= stop_index, 'Saved ADC frames do not cover the fixed clock interval')
        adc[:, first-first_index:end-first_index] = codes
        next_index = end

    with storage.CandidateStore(database, {**identity, 'branch': name}) as sink:
        readout = stream.StreamingReadout.restore(state['readout'], on_readout_context=on_context, on_adc_block=on_adc)
        # The original loop consumed what remained of its preceding source block before ingesting the next one.
        frontier = state['source_checkpoint']['safe_frontier_ns'] - dual.POST_NS
        first_input_guard = history[0]['onset_ns'] - dual.POST_NS if history else stop
        if start < frontier < min(stop, first_input_guard):
            readout.advance(frontier)
        for group in history:
            onset = group['onset_ns']
            native = pulses.get(group['ordinal'])
            if native is None:
                W.require(group['original_status'] != 'completed', 'A completed native pulse is missing')
                if unknown_support is not None:
                    # The same union method as cap recovery: each missing group adds its own absolute horizon.
                    missing.native_support_ns = unknown_support[group['ordinal']]
                missing.add(onset, group['last_deposit_ns'], group['positive_ge_energy_keV'])
            readout.advance(max(0., onset - dual.POST_NS))
            if native is not None:
                readout.push(native, onset)
        readout.advance(stop)
        saved = readout.checkpoint()
        mask = missing.checkpoint()
        sink.save_checkpoint({'readout': saved, 'missing_history': mask})
        rows = sink.db.execute(TRIGGER_SQL, interval).fetchall()
        ledger = [dict(zip(TRIGGER_FIELDS, row), **trigger_contexts[row[0]]) for row in rows]

    W.require(saved['next_sample_index'] == stop_index == next_index, 'Regenerated ADC frame census differs')
    clipped = [[max(lo, start), min(hi, stop)] for lo, hi in missing.intervals() if lo < stop and hi > start]
    masked_samples = sum(math.ceil((hi-phase)/period) - math.ceil((lo-phase)/period) for lo, hi in clipped)
    pending = [dict(coincidence_sample=a, end_sample=b) for a, b, pair in saved['groups']
               if pair and a > saved['emitted_through']]
    summary = dict(store=binding(database), triggers=ledger, decision_counts=dict(Counter(r['decision'] for r in ledger)),
                   adc_sample_indexes=[first_index, stop_index], adc_sha256=sha256(adc.astype('<i2', copy=False)).hexdigest(),
                   observed_unknown_native_groups=mask['failure_count'], mask_intervals_clipped_ns=clipped,
                   mask_union_clipped_ns=sum(hi-lo for lo, hi in clipped), masked_adc_frames=masked_samples,
                   pending_confirmed_rises_at_guard=pending)
    return summary, adc


def baseline_mismatches(expected, actual):
    old = {row[0]: dict(zip(TRIGGER_FIELDS, row)) for row in expected}
    new = {row['trigger_id']: row for row in actual}
    missing = sorted(old.keys()-new.keys())
    extra = sorted(new.keys()-old.keys())
    changed = [{'original_trigger_id': key, 'fields': {name: [value, new[key][name]]
                for name, value in old[key].items() if value != new[key][name]}}
               for key in sorted(old.keys() & new.keys())]
    return dict(missing_original_trigger_ids=missing, extra_replayed_trigger_ids=extra,
                changed=[row for row in changed if row['fields']])


def compare_ledgers(before, after):
    """Associate only equal trigger times. Record unresolved shifts or overlap explicitly."""
    by_time = {row['time_ns']: row for row in before}
    after_times = {row['time_ns'] for row in after}
    fields = ('decision', 'reason', 'rise_end_ns', 'context_sample_indexes', 'group_ordinals', 'all34_context_adc_sha256')
    matches, unmatched = [], []
    for row in after:
        prior = by_time.get(row['time_ns'])
        if prior is None:
            overlap = [old['trigger_id'] for old in before if old['time_ns'] <= row['rise_end_ns'] and
                       old['rise_end_ns'] >= row['time_ns']]
            unmatched.append(dict(counterfactual_trigger_id=row['trigger_id'], time_ns=row['time_ns'],
                                  original_trigger_ids_with_overlapping_rise=overlap))
        else:
            matches.append(dict(original_trigger_id=prior['trigger_id'], counterfactual_trigger_id=row['trigger_id'],
                                time_ns=row['time_ns'], changed_fields=[key for key in fields if row[key] != prior[key]]))
    return dict(equal_time_associations=matches, counterfactual_without_equal_time_baseline=unmatched,
                baseline_without_equal_time_counterfactual=[row['trigger_id'] for row in before if row['time_ns'] not in after_times])


def compare_adc(before, after, first_index, block_samples):
    W.require(before.shape == after.shape, 'The acquisition ADC clock must match between branches')
    frames = values = maximum = 0
    limits = None
    for start in range(0, before.shape[1], block_samples):
        take = slice(start, start+block_samples)
        delta = np.subtract(after[:, take], before[:, take], dtype=np.int32)
        changed = np.flatnonzero(np.any(delta != 0, axis=0))
        if changed.size:
            frames += int(changed.size)
            values += int(np.count_nonzero(delta))
            maximum = max(maximum, int(np.abs(delta).max()))
            if limits is None:
                limits = [first_index+start+int(changed[0]), None]
            limits[1] = first_index+start+int(changed[-1])
    return dict(frames=frames, values=values, maximum_absolute_adc_codes=maximum,
                first_and_last_changed_sample_indexes=limits)


def run(recipe_path, response_path, output):
    started = time.perf_counter()
    recipe = W.read(recipe_path)
    recipe_binding = binding(recipe_path)
    checkpoint = recipe['original_readout']
    acquisition = W.read(bound(recipe['original_acquisition']))
    snapshot = W.read(bound(checkpoint))
    archive = bound(recipe['original_archive'])
    _snapshot_check(snapshot, acquisition['identity'])
    state = json.loads(base64.b64decode(snapshot['state_base64'], validate=True))
    W.require(snapshot['checkpoint_sha256'] == checkpoint['checkpoint_sha256'] and
              state['readout']['input_watermark_ns'] == recipe['interval_ns'][0], 'Original readout anchor differs')
    check_readout_sources(checkpoint, state, acquisition['identity'])
    History = legacy_history(checkpoint)
    rows = recipe['missing_original_responses']
    interval = recipe['interval_ns']
    block_recipe = 'repair_targets' in recipe
    if block_recipe:
        targets = recipe['repair_targets']
        frontier = W.read(bound(recipe['end_source_checkpoint']))['safe_frontier_ns']
        W.require(frontier == recipe['source_safe_frontier_ns'] and interval[1] == frontier-dual.POST_NS,
                  'The original source block and ADC guard differ')
    else:
        targets = [recipe['repair_target']]
    pulses, native_provenance = response_store(response_path, recipe['original_native_phase'], rows,
                                                recipe_binding['sha256'], state['channels'])
    history = sorted([*rows, *(target['identity'] for target in targets)], key=lambda row: (row['onset_ns'], row['ordinal']))
    identity = dict(kind='gegi_native_readout_counterfactual_v1', original_checkpoint_sha256=snapshot['checkpoint_sha256'],
                    original_archive_sha256=recipe['original_archive']['sha256'], interval_ns=interval)
    output.mkdir(parents=True, exist_ok=False)
    result = dict(**identity, recipe=recipe_binding, source_sha256=W.sha(Path(__file__)),
                  original_phase_request_sha256=recipe['original_native_phase']['request']['sha256'],
                  original_field_cache_sha256=recipe['original_native_phase']['field_cache']['sha256'],
                  regenerated_responses=native_provenance, original_acquisition_counts=acquisition['counts'],
                  original_readout_runtime=checkpoint['runtime'], actual_runtime=dict(python=platform.python_version(),
                    numpy=np.__version__, sqlite=sqlite3.sqlite_version), readout_settings=checkpoint['settings'],
                  interpretation='A saved-input counterfactual over one clock interval. Trigger IDs are branch-local. '
                  'Equal sample times support comparison; unmatched crossings are retained without inferring physical event identity.')
    if block_recipe:
        result.update(source_safe_frontier_ns=frontier, original_block_groups=recipe['original_groups'], repair_targets=targets,
                      treatment_native_counts=recipe['treatment_native_counts'], missing_history_model_sha256=MIXED_HISTORY_SHA256)
    else:
        result['target_original_input'] = targets[0]['identity']
    with closing(readonly(archive)) as original_db:
        for target in targets:
            row = target['identity']
            old = original_db.execute('SELECT record FROM native_failures WHERE ordinal=?', (row['ordinal'],)).fetchone()
            W.require(old is not None and sha256(old[0]).hexdigest() == target['original_native']['record_zlib_sha256'],
                      'Original unavailable response differs')
            original_failure = json.loads(zlib.decompress(old[0]))
            W.require(sha256(encoded(original_failure['group'])).hexdigest() == row['input_sha256'] and
                      not stream.digital.terminal_contacts_complete(original_failure['event']), 'Original unavailable group differs')
        reference = original_db.execute(TRIGGER_SQL, interval).fetchall()
        compact = [(a, b, c, e, f) for a, b, c, _, e, f in reference]
        expected = recipe['original_trigger_ledger']['sha256_of_ordered_id_time_decision_adc_and_record_hash_rows']
        W.require(sha256(encoded(compact)).hexdigest() == expected, 'Original trigger ledger differs from the recipe')
        before, original_adc = run_branch('baseline', output, state, History, original_db, history, pulses, interval, identity)
        mismatches = baseline_mismatches(reference, before['triggers'])
        result.update(baseline=before, baseline_mismatches=mismatches, status='baseline_mismatch')
        if not any(mismatches.values()):
            if block_recipe:
                repaired, unknown_support = block_repairs(recipe, state['channels'])
            else:
                replacement = pulse.prepare_native(actual_repair(targets[0]), state['channels'], terminal_complete=True)
                repaired, unknown_support = {targets[0]['identity']['ordinal']: replacement}, None
            after, new_adc = run_branch('repaired', output, state, History, original_db, history,
                                         {**pulses, **repaired}, interval, identity, unknown_support=unknown_support)
            changed = compare_adc(original_adc, new_adc, before['adc_sample_indexes'][0], checkpoint['settings']['block_samples'])
            if changed['frames']:
                first_change = (changed['first_and_last_changed_sample_indexes'][0] * dual.SAMPLE_PERIOD_NS +
                                checkpoint['settings']['phase_ns'])
                earliest_repair = min(row['onset_ns'] for row in history if row['ordinal'] in repaired)
                W.require(first_change >= earliest_repair, 'ADC changed before the first substituted response started')
            result.update(status='baseline_verified_and_substitution_measured', repaired=after,
                          trigger_comparison=compare_ledgers(before['triggers'], after['triggers']),
                          changed_adc=changed,
                          conditional_mask_overlap=mask_overlap(before['mask_intervals_clipped_ns'], after['mask_intervals_clipped_ns']))
    result['wall_seconds'] = time.perf_counter() - started
    W.write(output / 'comparison.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recipe', required=True, type=Path)
    parser.add_argument('--native-responses', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = run(args.recipe, args.native_responses, args.output)
    print(result['status'])
    return int(result['status'] == 'baseline_mismatch')


if __name__ == '__main__':
    raise SystemExit(main())
