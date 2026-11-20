"""Continuous GeGI readout with candidate-only permanent waveform storage.

The same all-channel ADC and trigger implementation processes every input. This
module changes retention after readout; it does not select transport deposits.
"""
from __future__ import annotations

import argparse
from bisect import bisect_left, bisect_right
from collections import Counter
from contextlib import closing
from hashlib import sha256
import gzip
import json
from pathlib import Path
import sqlite3
import time

import numpy as np

import gegi_candidate_storage as storage
import gegi_digital_readout as digital
import gegi_dual_source as dual
import gegi_exposure_stream as stream
from gegi_event_store import encoded
import gegi_source_library as library

KIND = 'gegi_candidate_acquisition_v1'
REPORT_NAME = 'candidate-acquisition.json'


def write_new(path, value):
    dual._publish_artifact(Path(path), lambda out: out.write(encoded(value) + b'\n'))


def read_summary(path):
    with closing(storage._open_readonly(path)) as db:
        row = db.execute('SELECT body FROM completion WHERE singleton=1').fetchone()
        if row is None:
            raise ValueError('Candidate acquisition is incomplete; retain its partial records')
        return json.loads(row[0])


def verify_candidates(path):
    """Verify every stored record and independently reproduce candidate readout."""
    with closing(storage._open_readonly(path)) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Candidate database integrity check failed')
        ids = [row[0] for row in db.execute('SELECT trigger_id FROM triggers ORDER BY trigger_id')]
    kept = 0
    for trigger_id in ids:
        record = storage.load_candidate(path, trigger_id)
        if record['decision'] == 'candidate':
            storage.replay_candidate(path, trigger_id)
            kept += 1
    summary = read_summary(path)
    if (len(ids), kept) != (summary['observed_coincident_rises'], summary['saved_candidates']):
        raise ValueError('Candidate and rejected trigger denominators do not close')
    return {'status': 'verified_exact', 'candidates': kept, 'ledger_rows': len(ids),
            'check': 'All saved int16 samples, record hashes and re-extracted fast/slow/timing values.'}


def acquire(components, *, channels, live_time_ns, noise_seed, output, source_statistics,
            identity, trigger_profile='standard', excluded_intervals=(), group_identities=(),
            block_samples=stream.DEFAULT_BLOCK_SAMPLES):
    """Write one continuous acquisition from chronological native components.

    Native components may represent fresh transport or explicitly labelled saved
    readout diagnostics. No source position or true multiplicity selects a row.
    """
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    if (output / REPORT_NAME).exists():
        raise FileExistsError(output / REPORT_NAME)
    begun = time.perf_counter()
    adc = stream.ADCExposure(components, live_time_ns=live_time_ns, noise_seed=noise_seed)
    neighbors = dual._strip_neighbors(channels)
    mask = tuple(excluded_intervals)
    counts = Counter()
    histograms = {name: Counter() for name in ('single_pixel', 'additional_multi_strip', 'combined')}
    groups = sorted(group_identities, key=lambda row: row['first_ge_deposit_ns'])
    onsets = [row['first_ge_deposit_ns'] for row in groups]
    group_ledger = output / 'input-groups.jsonl.gz'
    with gzip.open(group_ledger, 'xt', encoding='utf-8') as handle:
        for ordinal, row in enumerate(groups, 1):
            handle.write(json.dumps({'input_group_ordinal': ordinal, **row},
                                   separators=(',', ':'), allow_nan=False) + '\n')
    # Bind nearby truth only as diagnostic provenance, never as a selection.
    history_ns = 40 * digital._TAU
    database = output / storage.ARCHIVE_NAME
    with storage.CandidateStore(database, identity) as sink:
        def observe(event, context):
            card = dual._trigger_card(event, neighbors, geometry=channels)
            t, end = event['trigger_time_ns'], event['rise_end_ns']
            reason = context['readout_rejection_reason']
            if not 0 <= t < live_time_ns:
                reason = 'outside_acquisition'
            elif any(a <= end and b > t for a, b in mask):
                reason = 'unknown_native_history'
            if reason is None:
                counts['qualified_triggers'] += 1
                for key, field in (('single_pixel', 'single_pixel_energy_keV'),
                                   ('additional_multi_strip', 'additional_multi_strip_energy_keV')):
                    energy = card[field]
                    if energy is not None:
                        counts[key + '_energies'] += 1
                        bucket = int(np.floor(energy / dual.BIN_STEP_KEV))
                        histograms[key][bucket] += 1
                        histograms['combined'][bucket] += 1
            first = adc.sample_time_ns(context['first_sample_index'])
            last = adc.sample_time_ns(context['stop_sample_index'])
            left = bisect_left(onsets, first - history_ns)
            right = bisect_right(onsets, last)
            related = list(range(left + 1, right + 1))
            sink.observe(card, context, event=event, identities=related, rejection_reason=reason)

        readout = stream.reconstruct_exposure(adc, block_samples=block_samples,
                    trigger_profile=trigger_profile, on_readout_context=observe, retain_events=False)
        counts['qualified_energies'] = counts['single_pixel_energies'] + counts['additional_multi_strip_energies']
        counts['triggers_without_energy'] = counts['qualified_triggers'] - counts['qualified_energies']
        counts = {key: counts[key] for key in ('qualified_triggers', 'single_pixel_energies',
                   'additional_multi_strip_energies', 'qualified_energies', 'triggers_without_energy')}
        measured = {key: value for key, value in readout.items()
                    if key not in ('events', 'rejected_rises', 'acquisition_baseline_v')}
        statistics = {'source': source_statistics, 'readout': measured, 'counts': counts,
                      'live_time_ns': live_time_ns, 'excluded_intervals_ns': list(mask)}
        completion = sink.finalize(acquisition_statistics=statistics)
    verification = verify_candidates(database)
    spectra = {}
    edges = list(range(0, dual.BIN_STOP_KEV + 1, dual.BIN_STEP_KEV))
    for name, histogram in histograms.items():
        spectra[name] = {'bin_edges_keV': edges,
                        'counts': [histogram[i] for i in range(len(edges)-1)],
                        'underflow': sum(n for i, n in histogram.items() if i < 0),
                        'overflow': sum(n for i, n in histogram.items() if i >= len(edges)-1),
                        'entries': sum(histogram.values())}
    artifacts = {}
    for path in (database, group_ledger):
        with path.open('rb') as handle:
            digest = __import__('hashlib').file_digest(handle, 'sha256').hexdigest()
        artifacts[path.name] = {'bytes': path.stat().st_size, 'sha256': digest}
    report = {'kind': KIND, 'status': 'completed', 'identity': identity,
              'selection_policy': storage.POLICY, 'source': source_statistics,
              'counts': counts, 'storage_counts': {key: completion[key] for key in (
                  'observed_coincident_rises', 'saved_candidates', 'rejected_rises', 'selection_reason_counts')},
              'readout': measured, 'spectra': spectra, 'live_time_ns': live_time_ns,
              'excluded_intervals_ns': list(mask), 'verification': verification,
              'artifacts': artifacts,
              'elapsed_seconds': time.perf_counter() - begun,
              'retention': {'full_adc_stream_saved': False, 'native_inputs_saved_here': False,
                  'candidate_signals': 'All-channel exact preamp context and fast/slow/timing values; derived branches can be re-extracted.',
                  'truth_association': 'Trigger identities are one-based input-groups.jsonl.gz ordinals. Groups are stored once; nearby groups are diagnostic links, not unique parent assignments or selection inputs.',
                  'rejected_signals': 'No waveform; original trigger ID, compact measured summary and reason remain.'}}
    write_new(output / REPORT_NAME, report)
    return report


def saved_diagnostic(source_chunks, activities_bq, live_time_s, seed, output, *, block_samples=32768):
    """Exercise retention with preserved libraries; explicitly not fresh production."""
    saved = [library.load_source_library(Path(path)) for path in source_chunks]
    live_ns = live_time_s * 1e9
    schedule = library.schedule_sources(*saved, activities_bq=activities_bq,
                                        duration_ns=live_ns, seed=seed, include_prehistory=True)
    components, missing, complete = dual._native_inputs(saved, schedule)
    partial = dual._partial_deposits(schedule)
    mask = dual._history_mask(missing + partial, live_ns)
    statistics = {'initial_parents': sum(s['counts']['parents'] for s in schedule['sources'].values()),
                  'deposit_groups': len(schedule['eligible_groups']) + len(partial),
                  'native_unavailable_groups': len(missing), 'right_censored_groups': len(partial),
                  'sources': [{key: value for key, value in row.items() if key == 'counts'}
                              for row in schedule['sources'].values()]}
    identity = {'scope': 'historical source-library readout diagnostic; not fresh mixed-source generation',
                'clock_seed': seed, 'noise_seed': (seed + 100000000) % (1 << 64),
                'activities_bq': list(activities_bq), 'sources': [s.metadata for s in saved],
                'new_transport_calls': 0, 'new_drift_calls': 0}
    return acquire(components, channels=saved[0].channels, live_time_ns=live_ns,
                   noise_seed=identity['noise_seed'], output=output, identity=identity,
                   source_statistics=statistics, excluded_intervals=mask,
                   group_identities=schedule['eligible_groups'], block_samples=block_samples)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-a', type=Path, required=True)
    parser.add_argument('--source-b', type=Path, required=True)
    parser.add_argument('--activity-a-bq', type=float, default=185000)
    parser.add_argument('--activity-b-bq', type=float, default=37000)
    parser.add_argument('--live-time-s', type=float, default=.05)
    parser.add_argument('--seed', type=int, default=20261120)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = saved_diagnostic((args.source_a, args.source_b),
        (args.activity_a_bq, args.activity_b_bq), args.live_time_s, args.seed, args.output)
    print(json.dumps({'counts': report['counts'], 'storage_counts': report['storage_counts'],
                      'artifacts': report['artifacts']}))


if __name__ == '__main__':
    main()
