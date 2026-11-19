"""Recover two original merged-trigger ADC windows without rerunning trigger selection."""

import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
from time import perf_counter

import numpy as np

import gegi_digital_readout as digital
import gegi_dual_source as dual
from gegi_event_store import encoded, sha
from gegi_exposure_stream import ADCExposure
import gegi_overlap_clock_reference as reference
import gegi_pulse_stream as pulse
import gegi_source_library as library
from gegi_trigger_windows import RELATIVE_NS, capture, is_two_strip
from gegi_window_activity import analyze_window


ROOT = reference.ROOT
OUTPUT = reference.LOCAL / 'merged-trigger-windows.json'
TARGETS = {'independent-b000001-250ms': 683, 'independent-b000004-250ms': 598}
REQUIRE = reference.REQUIRE


def identity(row):
    return tuple(row[key] for key in ('source', 'occurrence_id', 'group_id'))


def component_cards(components, rows, trigger_time_ns):
    result = []
    for row, (native, onset, scale) in zip(rows, components, strict=True):
        REQUIRE(onset == row['first_ge_deposit_ns'] and scale == 1., 'Native component clock or gain changed')
        offset = onset - trigger_time_ns
        active = np.flatnonzero(np.any(native.drive_V[0, :, :-1] != 0, axis=0))
        analog = np.zeros((len(digital.CONTACT_IDS), len(RELATIVE_NS)))
        present = RELATIVE_NS >= offset
        analog[:, present] = pulse._sample_pulse(native, RELATIVE_NS[present] - offset)
        fields = ('source', 'occurrence_id', 'group_id', 'raw_event_id', 'campaign_initial_id', 'truth_edep_keV',
                  'first_ge_deposit_ns', 'last_ge_deposit_ns', 'metadata_sha256', 'parent_decay_time_ns')
        result.append({k: row[k] for k in fields} | dict(
            ge_deposit_relative_ns=[row[k] - trigger_time_ns for k in
                                    ('first_ge_deposit_ns', 'last_ge_deposit_ns')],
            native_current_relative_ns=[float(native.time_ns[active[0]] + offset),
                                        float(native.time_ns[active[-1]+1] + offset)],
            isolated_nominal_preamp_v=analog.tolist(),
        ))
    return result


def recover(block, trigger_id, hashes):
    name = block['provenance']['name']
    folder = reference.ACQUISITIONS / name
    observed = json.loads(reference.bound(folder / 'report.json', hashes, block['provenance']['report_sha256']))
    receipt, design, exposure = (observed[k] for k in ('receipt', 'design', 'exposure'))
    mask = exposure['excluded_intervals_ns']
    trigger = observed['triggers'][trigger_id-1]
    trigger_time = trigger['trigger_time_ns']
    REQUIRE(observed['kind'] == dual.KIND and observed['status'] == 'completed'
            and not is_two_strip(trigger)
            and receipt['digital_profile_sha256'] == digital.PROFILE_SHA256
            and receipt['digital_timing_sha256'] == digital.TIMING_SHA256
            and receipt['known_component_adc_sha256'] == block['provenance']['known_component_adc_sha256']
            and sha(encoded(dict(counts=observed['counts'], spectra=observed['spectra'],
                                 triggers=observed['triggers'], mask=mask))) == receipt['observed_result_sha256'],
            'Saved merged-trigger record or ADC receipt changed')

    source_records = observed['sources']
    packs = [library.load_source_library(folder / r['input_directory']['relative_to_report_directory'])
             for r in source_records]
    REQUIRE(all(p.metadata == r['original'] for p, r in zip(packs, source_records, strict=True)),
            'Selected libraries differ from those of the bound original block')
    for pack in packs:
        original, directory = pack.metadata, pack.directory
        for filename, key in (('DONE.json', 'chunk_sha256'), ('events.sqlite', 'database_sha256')):
            hashes[(directory / filename).relative_to(ROOT).as_posix()] = original[key]
        _, _, done, _, archive, _, _ = library._source_inputs(directory)
        for filename in (archive, 'transport/stream/manifest.json'):
            hashes[(directory / filename).relative_to(ROOT).as_posix()] = done['artifacts'][filename]['sha256']

    schedule = library.schedule_sources(*packs, activities_bq=[s['activity_bq'] for s in source_records],
                                        duration_ns=exposure['clock_live_time_ns'], seed=design['clock_seed'],
                                        include_prehistory=True)
    for source in source_records:
        clock = schedule['sources'][source['key']]
        REQUIRE(clock['counts'] == source['counts'] and clock['clock']['seed_uint64'] == source['scheduled_parent_seed'],
                'Original parent clock binding changed')
    all_groups = sorted(schedule['eligible_groups'] + schedule['censored_groups'],
                        key=lambda row: row['first_ge_deposit_ns'])
    compare = ('first_ge_deposit_ns', 'last_ge_deposit_ns', 'raw_event_id', 'campaign_initial_id')
    REQUIRE(all(identity(a) == identity(b) and all(a[k] == b[k] for k in compare)
                for a, b in zip(all_groups, block['group_ledger'], strict=True)),
            'Absolute deposit times differ from independent reference')

    linked = reference.heldout.link_groups(
        [dict(row, isolated_triggers=[], classification=(
            'awaiting_match' if row['native_available'] and
            not reference.association.in_regions(row['first_ge_deposit_ns'], mask) else row['classification']))
         for row in block['group_ledger']], observed['triggers'], mask)[trigger_id-1]
    REQUIRE(linked['association'] == 'merged' and len(linked['group_indices']) == 2,
            'The timing graph must bind two saved Ge groups to the original measured rise')
    groups = [block['group_ledger'][i] for i in linked['group_indices']]
    components, missing, _ = dual._native_inputs(packs, schedule)
    unknown = missing + dual._partial_deposits(schedule)
    REQUIRE({identity(r): r for r in unknown} == {identity(r): r for r in observed['unknown_groups']}
            and dual._history_mask(unknown, exposure['clock_live_time_ns']) == mask,
            'Original native availability or ADC history exclusions changed')
    absent = {identity(r) for r in missing}
    known = [r for r in schedule['eligible_groups'] if identity(r) not in absent]
    REQUIRE(all(r['first_ge_deposit_ns'] == p[1] for r, p in zip(known, components, strict=True)),
            'Native components differ from the source schedule')
    by_id = {identity(r): p for r, p in zip(known, components, strict=True)}
    example_components = component_cards([by_id[identity(r)] for r in groups], groups, trigger_time)
    latest_current = example_components[0]['native_current_relative_ns'][1]
    following_current = example_components[1]['native_current_relative_ns'][0]
    del by_id
    adc = ADCExposure(components, live_time_ns=exposure['clock_live_time_ns'],
                      phase_ns=design['adc_phase_ns'], noise_seed=design['noise_seed'])
    capture_started = perf_counter()
    window = capture(adc, [trigger_time], mask)
    capture_elapsed = perf_counter() - capture_started
    REQUIRE(window['known_component_adc_sha256'] == receipt['known_component_adc_sha256']
            and window['window_status'].tolist() == ['captured']
            and window['trigger_time_ns'].tolist() == [trigger_time],
            'Rebuilt ADC stream or requested sample window differs from the original')
    codes, baseline = window['adc_codes'][0], window['acquisition_baseline_v']
    waveform = analyze_window(codes, baseline, RELATIVE_NS, design['trigger_profile']['id'])
    rises = [row for row in waveform['groups'] if row['coincident']]
    REQUIRE(len(rises) == 1 and rises[0]['trigger_reference_ns'] == 0
            and rises[0]['last_active_ns'] == trigger['rise_end_ns'] - trigger_time,
            'Recovered ADC rise disagrees with the original trigger bounds')
    return dict(block=name, trigger_index=trigger_id, trigger_time_ns=trigger_time, rise_end_ns=trigger['rise_end_ns'],
                report_sha256=block['provenance']['report_sha256'],
                known_component_adc_sha256=window['known_component_adc_sha256'],
                original_trigger=trigger, clock_seed=design['clock_seed'], noise_seed=design['noise_seed'],
                scheduled_parent_seeds={s['key']: s['scheduled_parent_seed'] for s in source_records},
                source_chunks=[pack.metadata['chunk_sha256'] for pack in packs],
                adc_codes=codes.tolist(), baseline_v=baseline.tolist(), relative_time_ns=RELATIVE_NS.tolist(),
                contact_ids=list(digital.CONTACT_IDS), volts_per_code=digital._LSB_V, waveform=waveform,
                component_scope='Isolated nominal preamplifier responses sampled from the two sealed native currents. '
                                'The rebuilt ADC window includes all scheduled components, history and seeded noise.',
                native_current_gap_ns=max(0., following_current-latest_current), components=example_components,
                full_adc_pass_s=capture_elapsed)


def run():
    names = (Path(__file__).name, 'gegi_source_library.py', 'gegi_dual_source.py', 'gegi_pulse_stream.py',
             'gegi_digital_readout.py', 'gegi_trigger_windows.py', 'gegi_window_activity.py',
             'gegi_exposure_stream.py', 'gegi_overlap_clock_reference.py',
             'gegi_heldout_pairing_study.py', 'gegi_source_exposure.py')

    def source_hashes():
        return {f'tools/{name}': library._hash(ROOT / 'tools' / name) for name in names}

    hashes = {}
    sources = source_hashes()
    prior = json.loads(gzip.decompress(reference.bound(reference.OUTPUT, hashes)))
    REQUIRE(all(prior['source_sha256'][f'tools/{name}'] == sources[f'tools/{name}']
                for name in ('gegi_source_library.py', 'gegi_pulse_stream.py', 'gegi_overlap_clock_reference.py')),
            'Independent clock analysis source has changed')
    examples = []
    for block in prior['blocks']:
        name = block['provenance']['name']
        if name in TARGETS:
            print(f'Recovering {name} trigger {TARGETS[name]}', flush=True)
            result = recover(block, TARGETS[name], hashes)
            examples.append(result)
            print(f'ADC hash matched after {result["full_adc_pass_s"]:.2f} s; local rise matches', flush=True)
    REQUIRE(Counter(r['block'] for r in examples) == Counter(TARGETS.keys()) and source_hashes() == sources,
            'The requested blocks or analysis source changed')
    return dict(kind='gegi_merged_trigger_windows_v1', status='completed',
                design=dict(transport_runs=0, drift_runs=0, trigger_scans=0, full_adc_passes=len(examples),
                            slow_readout='Energy, strip multiplicity and quality flags are from the original bound '
                                         'continuous readout; the 29 samples reproduce the local rise bounds.'),
                input_sha256=hashes, source_sha256=sources, examples=examples)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    output = parser.parse_args().output.resolve()
    REQUIRE(output.is_relative_to(reference.LOCAL) and not output.exists(), 'Use a new local study output')
    result = run()
    with output.open('xb') as target:
        target.write(encoded(result) + b'\n')


if __name__ == '__main__':
    main()
