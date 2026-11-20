"""Bounded saved-data parity of incremental readout; never launch transport/drift."""

import argparse
from bisect import bisect_left, bisect_right
from collections import Counter
from contextlib import closing
import ctypes
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import time
import zlib

import numpy as np

import gegi_candidate_storage as storage
import gegi_digital_readout as digital
import gegi_dual_source as dual
from gegi_event_store import encoded
import gegi_source_library as library
import gegi_streaming_readout as streaming


ROOT = Path(__file__).resolve().parents[1]


def _rss():
    if os.name != 'nt':
        return None

    class Counters(ctypes.Structure):
        _fields_ = [('cb', ctypes.c_ulong), ('PageFaultCount', ctypes.c_ulong),
                    *[(key, ctypes.c_size_t) for key in ('PeakWorkingSetSize', 'WorkingSetSize',
                        'QuotaPeakPagedPoolUsage', 'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage',
                        'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage')]]

    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    process = ctypes.windll.kernel32.GetCurrentProcess()
    ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(Counters), ctypes.c_ulong]
    if not ctypes.windll.psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb):
        raise OSError('Could not measure this saved-data validation process memory')
    return {'working_set_bytes': counters.WorkingSetSize, 'process_peak_working_set_bytes': counters.PeakWorkingSetSize}


def _peek(saved, row):
    """Read small terminal-status metadata before constructing the shared mask."""
    with closing(library._database(saved.database)) as db:
        body, digest = db.execute('SELECT metadata,metadata_sha256 FROM events WHERE primary_id=? AND group_id=?',
                                 (row['raw_event_id'], row['group_id'])).fetchone()
    raw = zlib.decompress(body)
    if sha256(raw).hexdigest() != digest:
        raise ValueError('Saved native status metadata changed')
    event = json.loads(raw)
    return digital.terminal_contacts_complete(event), event['status'], digest


def validate(output):
    output = Path(output).resolve()
    if not output.is_relative_to(ROOT / '.local'):
        raise ValueError('Keep developer acceptance inside this project .local folder')
    output.mkdir(parents=True, exist_ok=False)
    receipt = {'kind': 'gegi_incremental_saved_readout_acceptance_v1', 'status': 'running',
               'scope': 'Existing 50 ms historical libraries only; no fresh transport, drift or production timing.',
               'new_transport_calls': 0, 'new_drift_calls': 0}
    started = time.perf_counter()
    try:
        reference_root = ROOT / '.local/gegi-candidate-runs/storage-reference-compact'
        reference = json.loads((reference_root / 'candidate-acquisition.json').read_text(encoding='utf-8'))
        campaign = json.loads((ROOT / '.local/gegi-dual-source/rss5-simultaneous-large/campaign.json').read_text(encoding='utf-8'))
        paths = [ROOT / campaign['blocks']['b000005']['inputs'][key]['path'] for key in ('cs137-left', 'co60-right')]
        saved = [library.load_source_library(path) for path in paths]
        if [src.metadata for src in saved] != reference['identity']['sources']:
            raise ValueError('Saved reference source libraries changed')
        live = reference['live_time_ns']
        schedule = library.schedule_sources(*saved, activities_bq=reference['identity']['activities_bq'],
            duration_ns=live, seed=reference['identity']['clock_seed'], include_prehistory=True)
        by_key = dict(zip(schedule['source_keys'], saved, strict=True))
        groups = schedule['eligible_groups']
        onsets = [row['first_ge_deposit_ns'] for row in groups]
        terminal, missing = [], []
        for row in groups:
            complete, status, digest = _peek(by_key[row['source']], row)
            terminal.append(complete)
            if not complete:
                missing.append(dual._unknown_card(row, row['truth_edep_keV'], status, digest))
        partial = dual._partial_deposits(schedule)
        mask = dual._history_mask(missing+partial, live)
        if mask != reference['excluded_intervals_ns']:
            raise ValueError('Saved unknown-native qualification mask changed')
        census = {'initial_parents': sum(src['counts']['parents'] for src in schedule['sources'].values()),
            'deposit_groups': len(groups)+len(partial), 'native_unavailable_groups': len(missing),
            'right_censored_groups': len(partial),
            'sources': [{'counts': src['counts']} for src in schedule['sources'].values()]}
        if census != reference['source']:
            raise ValueError('Original source/zero/nonzero/group denominators changed')
        neighbors = dual._strip_neighbors(saved[0].channels)
        counts = Counter()
        histograms = {name: Counter() for name in ('single_pixel', 'additional_multi_strip', 'combined')}
        adc_sha = sha256()
        native_peak_bytes = 0
        max_checkpoint_bytes = 0
        restarts = []
        baseline_memory = _rss()
        database = output / storage.ARCHIVE_NAME
        identity = {**reference['identity'], 'incremental_producer_sha256': streaming.PRODUCER_SHA256}
        sink = storage.CandidateStore(database, identity)

        def observe(event, context):
            card = dual._trigger_card(event, neighbors, geometry=saved[0].channels)
            t, end = event['trigger_time_ns'], event['rise_end_ns']
            reason = context['readout_rejection_reason']
            if not 0 <= t < live:
                reason = 'outside_acquisition'
            elif any(a <= end and b > t for a, b in mask):
                reason = 'unknown_native_history'
            if reason is None:
                counts['qualified_triggers'] += 1
                for key, field in (('single_pixel', 'single_pixel_energy_keV'),
                                   ('additional_multi_strip', 'additional_multi_strip_energy_keV')):
                    energy = card[field]
                    if energy is not None:
                        counts[key+'_energies'] += 1
                        bucket = math.floor(energy/dual.BIN_STEP_KEV)
                        histograms[key][bucket] += 1
                        histograms['combined'][bucket] += 1
            first = context['first_sample_index']*20+context['adc_phase_ns']
            last = context['stop_sample_index']*20+context['adc_phase_ns']
            left, right = bisect_left(onsets, first-40*digital._TAU), bisect_right(onsets, last)
            sink.observe(card, context, event=event, identities=list(range(left+1, right+1)), rejection_reason=reason)

        out = streaming.StreamingReadout(noise_seed=reference['identity']['noise_seed'],
            max_context_samples=4096, max_active_components=128, on_readout_context=observe,
            on_adc_block=lambda first, code: adc_sha.update(np.asarray(code.T, dtype='<i2', order='C').tobytes()))
        cursor = 0
        block = 32768*20
        readout_started = time.perf_counter()
        for ordinal, until in enumerate(range(block, math.ceil(live)+block, block), 1):
            until = min(float(until), live)
            with sink.transaction():
                while cursor < len(groups) and onsets[cursor] < until:
                    if terminal[cursor]:
                        row = groups[cursor]
                        native, _, _ = library.read_native(by_key[row['source']], row)
                        if native is None:
                            raise ValueError('Native availability changed between metadata and signal reads')
                        out.push(native, row['first_ge_deposit_ns'])
                        native_peak_bytes = max(native_peak_bytes, sum(
                            item.time_ns.nbytes+item.drive_V.nbytes+item.knot_V.nbytes for _, item, _, _ in out._pulses))
                    cursor += 1
                out.advance(until)
                state = {'readout': out.checkpoint(), 'source_group_cursor': cursor,
                         'counts': dict(counts), 'histograms': {key: {str(bucket): n for bucket, n in value.items()}
                                                              for key, value in histograms.items()}}
                max_checkpoint_bytes = max(max_checkpoint_bytes, len(encoded(state)))
                sink.save_checkpoint(state)
            if ordinal in (19, 51):
                sink.close()
                sink = storage.CandidateStore(database, identity, resume=True)
                restored = sink.load_checkpoint()
                state = restored['state'] if 'state' in restored else restored
                cursor = state['source_group_cursor']
                counts = Counter(state['counts'])
                histograms = {key: Counter({int(bucket): value for bucket, value in histogram.items()})
                              for key, histogram in state['histograms'].items()}
                out = streaming.StreamingReadout.restore(state['readout'], block_samples=8192 if ordinal == 19 else 17011,
                    on_readout_context=observe,
                    on_adc_block=lambda first, code: adc_sha.update(np.asarray(code.T, dtype='<i2', order='C').tobytes()))
                restarts.append({'after_ns': until, 'source_group_cursor': cursor, 'last_trigger_id': sink.last_trigger_id})
        with sink.transaction():
            result = out.finalize(live)
            sink.save_checkpoint({'readout': out.checkpoint(), 'source_group_cursor': cursor,
                                  'counts': dict(counts), 'histograms': {key: {str(bucket): n for bucket, n in value.items()}
                                                                       for key, value in histograms.items()}})
        readout_elapsed = time.perf_counter()-readout_started
        counts['qualified_energies'] = counts['single_pixel_energies']+counts['additional_multi_strip_energies']
        counts['triggers_without_energy'] = counts['qualified_triggers']-counts['qualified_energies']
        actual_counts = {key: counts[key] for key in reference['counts']}
        if actual_counts != reference['counts'] or sink.statistics() != reference['storage_counts']:
            raise ValueError('Incremental trigger or retention denominators differ')
        for name, histogram in histograms.items():
            spectrum = reference['spectra'][name]
            for index, expected in enumerate(spectrum['counts']):
                if histogram[index] != expected:
                    raise ValueError('Incremental energy histogram differs')
            if sum(histogram.values()) != spectrum['entries']:
                raise ValueError('Incremental spectrum entry denominator differs')
        sink.finalize(acquisition_statistics={'source': census, 'counts': actual_counts,
                                              'readout': result, 'live_time_ns': live, 'excluded_intervals_ns': mask})
        sink.close()
        old = reference_root / storage.ARCHIVE_NAME
        compared = 0
        with closing(storage._open_readonly(old)) as db:
            ids = [row[0] for row in db.execute('SELECT trigger_id FROM triggers ORDER BY trigger_id')]
        for trigger in ids:
            a, b = storage.load_candidate(old, trigger), storage.load_candidate(database, trigger)
            if a['decision'] != b['decision'] or a['reason'] != b['reason'] or a['identities'] != b['identities']:
                raise ValueError('Original trigger selection or normalized source identities differ')
            if a['decision'] == 'candidate':
                if a['card'] != b['card'] or a['readout'] != b['readout']:
                    raise ValueError('Candidate scalar readout or alternative pairing record differs')
                np.testing.assert_array_equal(a['context']['adc_codes'], b['context']['adc_codes'])
                if any(a['context'][key] != b['context'][key] for key in ('first_sample_index', 'stop_sample_index')):
                    raise ValueError('Exact candidate context bounds differ')
                storage.replay_candidate(database, trigger)
                compared += 1
            elif a['summary'] != b['summary']:
                raise ValueError('Rejected-rise compact measurement changed')
        if adc_sha.hexdigest() != reference['readout']['adc_sha256']:
            raise ValueError('Full streamed ADC bytes differ from the retained reference SHA256')
        receipt.update(status='passed', source_groups=len(groups), native_complete_groups=sum(terminal),
            native_unavailable_groups=len(missing), full_adc_sha256=adc_sha.hexdigest(),
            all_saved_candidates_exact=compared, all_ledger_rows_exact=len(ids),
            source_census_exact=True, spectra_and_counts_exact=True, unknown_native_mask_exact=True,
            streaming_statistics=result, native_prepared_array_bytes_peak=native_peak_bytes,
            serialized_checkpoint_bytes_peak=max_checkpoint_bytes, memory_before_stream=baseline_memory,
            memory_after_validation=_rss(), readout_saved_input_load_and_checkpoint_seconds=readout_elapsed,
            total_validation_seconds=time.perf_counter()-started, closed_store_restores=restarts,
            resume_scope='Candidate database closed/reopened and exact readout JSON restored twice; validation SHA collector remained open.',
            reference_report_sha256=sha256((reference_root/'candidate-acquisition.json').read_bytes()).hexdigest(),
            producer_sha256=streaming.PRODUCER_SHA256, new_archive_bytes=database.stat().st_size,
            limits=['Historical source-library data only; no fresh transport/drift or production performance claim.',
                    'Validation retains its bounded 613-row reference schedule; production source streaming is separate.'])
    except BaseException as error:
        receipt.update(status='failed', error=str(error), total_validation_seconds=time.perf_counter()-started)
        raise
    finally:
        (output/'acceptance.json').write_text(json.dumps(receipt, indent=2)+'\n', encoding='utf-8')
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'.local/streaming-acquisition-v1/saved-readout')
    result = validate(parser.parse_args().output)
    print(json.dumps({key: result[key] for key in ('status', 'all_saved_candidates_exact', 'all_ledger_rows_exact',
        'native_prepared_array_bytes_peak', 'serialized_checkpoint_bytes_peak', 'total_validation_seconds')}))


if __name__ == '__main__':
    main()
