"""Trace the excluded held-out Cs strip pairing and test a fixed ADC diagnostic."""

import argparse
from collections import Counter
from contextlib import ExitStack, closing
from hashlib import sha256
import json
import math
from pathlib import Path
import sqlite3

import numpy as np

import gegi_continuous_pairing_study as truth
import gegi_digital_readout as digital
from gegi_imaging import MIN_COLLECTED_KEV
from gegi_pulse_stream import _QUIET_SAMPLES


ROOT = truth.ROOT
ACQUISITION = ROOT/'.local/gegi-dual-source/independent-b000001-250ms'
REFERENCE = truth.LOCAL/'independent-b000001-250ms.json'
REPORT_SHA = '03be930ed71ff033429f9c4c9bd933f76e3a849a81b748df531f9e0cad0af752'
WINDOW_SHA = 'aff2175bf26eb0cd635e35bb793cf11f736f59c4142de16b9d3ad3233753fc67'
REFERENCE_SHA = 'ff19878efc36724d98560c190e600b4cd6a75024719e6bb30c27109d44d3b8f4'
TARGET_ORDINAL = 55
SIGNIFICANCE = 5.
GUARDS = {17, 34}
ADC_SIGMA_V = math.hypot(digital._PROFILE['optional_noise_rms_V'], digital._LSB_V / math.sqrt(12))
TAIL_GAIN = digital._VOLTS_PER_KEV * digital._TAU / (digital._TAU - digital._BANDWIDTH_TAU)


def late_step(codes, times, baseline_v, rise_ns, selected):
    """Measure a persistent, subthreshold preamp step on the other strips."""
    quiet = np.arange(_QUIET_SAMPLES)
    late = np.arange(len(times)-5, len(times))
    if times[late[0]] < rise_ns + 2*_QUIET_SAMPLES*digital._DT:
        return {'status': 'insufficient_post_rise_settling', 'weak_strips': []}
    weights = np.exp(times/digital._TAU)
    values = (codes*digital._LSB_V-baseline_v[:, None])*weights[None, :]/TAIL_GAIN
    sigma = ADC_SIGMA_V/TAIL_GAIN
    rms = sigma * math.hypot(np.linalg.norm(weights[quiet]) / len(quiet), np.linalg.norm(weights[late]) / len(late))
    edge_rms = sigma * math.hypot(np.linalg.norm(weights[late[:2]]) / 2, np.linalg.norm(weights[late[-2:]]) / 2)
    amplitude = values[:, late].mean(axis=1) - values[:, quiet].mean(axis=1)
    persistence = values[:, late[-2:]].mean(axis=1) - values[:, late[:2]].mean(axis=1)
    strips = []
    for i, (step, drift) in enumerate(zip(amplitude, persistence, strict=True)):
        cid = i+1
        if (cid not in selected and cid not in GUARDS
                and SIGNIFICANCE*rms <= step < MIN_COLLECTED_KEV and abs(drift) <= SIGNIFICANCE*edge_rms
                and codes[i].min() > digital._ADC_MIN and codes[i].max() < digital._ADC_MAX):
            strips.append(dict(contact_id=cid, step_keV_equiv=float(step), late_difference_keV_equiv=float(drift),
                               sigma_multiple=float(step/rms)))
    return {'status': 'measured', 'sigma_keV_equiv': float(rms), 'weak_strips': strips}


def native_support(candidate, database, processes):
    group, = candidate['deposit_groups']
    reference = candidate['reference']
    native = truth.native_metadata(database, dict(group, metadata_sha256=reference['native_metadata_sha256']))
    truth.require(native['input_event_sha256'] == reference['native_input_group_sha256']
                  and digital.terminal_contacts_complete(native), 'Held-out native radiation group changed')
    scored = truth.parent.evaluate(native, processes, {'spatial_diagnostics': [], 'candidates': []})
    cells, charges = Counter(), Counter()
    for row in scored['row_assignment_ledger']:
        if row['collector_pair']:
            cell = tuple(row['collector_pair'])
            cells[cell] += row['energy_keV']
            for cid in cell:
                charges[cid] += row['energy_keV']
    missing = native['truth_edep_keV'] - math.fsum(cells.values())
    return dict(
        cells=[dict(contact_ids=cell, deposited_keV=energy) for cell, energy in sorted(cells.items())],
        collected_input_keV=dict(charges), energy_without_two_endpoints_keV=missing,
        root_gammas=scored['root_gammas'], unassigned_energy_keV=scored['unassigned_interaction_energy_keV'],
        interactions=sorted([dict(birth_time_ns=row['birth_time_ns'], birth_process=row['birth_process'],
                                  birth_position_mm=row['birth_position_mm'], deposited_energy_keV=row['deposited_energy_keV'],
                                  collector_cells=row['collector_cells'], raw_row_indices=row['raw_row_indices'])
                             for row in scored['parent_interactions']], key=lambda row: row['birth_time_ns']),
    )


def run():
    hashes = {}
    measured = json.loads(truth.bound_bytes(ACQUISITION/'report.json', hashes, REPORT_SHA))
    reference = json.loads(truth.bound_bytes(REFERENCE, hashes, REFERENCE_SHA))
    adc_path = ACQUISITION/'two-strip-adc.npz'
    truth.require(truth._hash(adc_path) == WINDOW_SHA, 'Saved ADC windows changed')
    hashes[adc_path.relative_to(ROOT).as_posix()] = WINDOW_SHA
    candidates = reference['candidates']
    truth.require(len(candidates) == 79, 'The original held-out roster must contain 79 two-strip triggers')
    weak_rows, endpoint_cache, databases = [], {}, {}
    with np.load(adc_path, allow_pickle=False) as adc, ExitStack() as stack:
        truth.require(adc['known_component_adc_sha256'].item() == measured['receipt']['known_component_adc_sha256'] ==
                      reference['adc_sha256'] and adc['report_sha256'].item() == REPORT_SHA
                      and adc['digital_profile_sha256'].item() == digital.PROFILE_SHA256
                      and adc['digital_timing_sha256'].item() == digital.TIMING_SHA256
                      and adc['contact_ids'].tolist() == list(range(1, 35))
                      and adc['volts_per_code'].item() == digital._LSB_V
                      and adc['two_strip_ordinal'].tolist() == list(range(1, len(candidates)+1))
                      and adc['window_status'].tolist() == ['captured']*len(candidates),
                      'ADC profile, eligibility, units or roster changed')
        codes, times, baseline = adc['adc_codes'], adc['relative_time_ns'], adc['acquisition_baseline_v']
        truth.require(codes.shape == (len(candidates), 34, 29)
                      and times.tolist() == list(range(-80, 481, digital._DT)),
                      'Expected 34-electrode local ADC windows')
        for ordinal, candidate in enumerate(candidates, 1):
            trigger = measured['triggers'][candidate['trigger_index']]
            truth.require(trigger['trigger_time_ns'] == candidate['trigger_time_ns'] == adc['trigger_time_ns'][ordinal-1]
                          and trigger['two_strip_pairings'] == candidate['two_strip_pairings'],
                          'Held-out ADC window identity differs from the measured event')
            collectors = {row['contact_id'] for row in trigger['two_strip_pairings']['collectors']}
            scope = late_step(codes[ordinal-1], times, baseline,
                              trigger['rise_end_ns'] - trigger['trigger_time_ns'], collectors)
            support = None
            if candidate['truth_link_scope'] == 'isolated_rise_time_match':
                group, = candidate['deposit_groups']
                source = group['source']
                if source not in databases:
                    folder = truth.CAMPAIGN/'chunks'/source/'b000001'
                    path = folder/'events.sqlite'
                    rel = path.relative_to(ROOT).as_posix()
                    truth.require(truth._hash(path) == reference['input_sha256'][rel], 'Native group database changed')
                    hashes[rel] = reference['input_sha256'][rel]
                    path_manifest = folder/'transport/stream/manifest.json'
                    manifest = json.loads(truth.bound_bytes(path_manifest, hashes,
                        reference['input_sha256'][path_manifest.relative_to(ROOT).as_posix()]))
                    db = stack.enter_context(closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True)))
                    databases[source] = db, {proc['procid']: proc['name'] for proc in manifest['processes']}
                key = source, group['raw_event_id'], group['group_id']
                if key not in endpoint_cache:
                    endpoint_cache[key] = native_support(candidate, *databases[source])
                support = endpoint_cache[key]
            charges = support['collected_input_keV'] if support else None
            observed = scope['weak_strips']
            if charges is not None and scope['status'] == 'measured':
                expected = {cid for cid, energy in charges.items() if cid not in collectors and cid not in GUARDS
                            and SIGNIFICANCE*scope['sigma_keV_equiv'] <= energy < MIN_COLLECTED_KEV}
                found = {row['contact_id'] for row in observed}
                scope.update(expected_weak_native_contact_ids=sorted(expected),
                             confirmed_contact_ids=sorted(expected & found),
                             unmatched_adc_contact_ids=sorted(found - expected),
                             missed_native_contact_ids=sorted(expected - found))
                for strip in observed:
                    strip['native_collected_input_keV'] = charges.get(strip['contact_id'], 0)
            weak_rows.append(dict(ordinal=ordinal, trigger_index=candidate['trigger_index'],
                                  trigger_time_ns=trigger['trigger_time_ns'], adc_diagnostic=scope))
            if ordinal == TARGET_ORDINAL:
                target_support, target, target_trigger = support, candidate, trigger
                target_codes = codes[ordinal-1].tolist()

    group, = target['deposit_groups']
    neighbors = sorted((abs(row['first_ge_deposit_ns'] - group['first_ge_deposit_ns']), row)
                       for row in reference['deposit_ledger'] if
                       (row['source'], row['occurrence_id']) != (group['source'], group['occurrence_id']))
    first = neighbors[0][1]
    exact_pair = target_trigger['two_strip_pairings']['pairings'][target['comparison']['truth_pairing_index']]
    diagnostics = [row['adc_diagnostic'] for row in weak_rows]
    scored = [entry for entry in diagnostics if 'expected_weak_native_contact_ids' in entry]
    sha = lambda path: sha256(path.read_bytes()).hexdigest()
    return dict(
        kind='gegi_heldout_pairing_loss_study_v1', status='completed',
        design=dict(adc='On every saved window, subtract a short quiet baseline from the last five samples after '
                        'multiplying each by the nominal free-decay factor exp(t/feedback_tau). '
                        'Use nominal pulser preamplifier gain, feedback pole and independently specified ADC noise.',
                    selection='Other non-guard strips with a persistent step at least five modeled standard deviations '
                              'and below the existing 5 keV collection threshold. Preserve the current pairing.',
                    independence='Count native endpoint matches only for isolated, uniquely associated groups. '
                                 'ADC steps diagnose additional charge and can occur in different physical topologies.',
                    new_transport_calls=0, new_drift_calls=0, new_adc_replays=0),
        input_sha256=hashes, source_sha256={name: sha(ROOT/name) for name in (
        'tools/gegi_heldout_pairing_loss_study.py', 'tools/gegi_continuous_pairing_study.py',
        'tools/gegi_parent_gamma_reference.py', 'tools/gegi_digital_readout.py', 'tools/gegi_pulse_stream.py')},
        target=dict(ordinal=TARGET_ORDINAL, trigger=target_trigger, transport_group=group, native_support=target_support,
                    exact_pairing=exact_pair, original_reference=target['reference'],
                    nearest_other_group={key: first[key] for key in ('source', 'occurrence_id', 'first_ge_deposit_ns', 'truth_edep_keV')},
                    nearest_other_group_onset_offset_ns=first['first_ge_deposit_ns']-group['first_ge_deposit_ns'],
                    adc=dict(relative_time_ns=times.tolist(), contact_ids=list(range(1, 35)), codes=target_codes,
                             baseline_v=baseline.tolist(), volts_per_code=digital._LSB_V), diagnostic=diagnostics[TARGET_ORDINAL-1]),
        summary=dict(rows=len(weak_rows), adc_status=dict(Counter(entry['status'] for entry in diagnostics)),
                     rows_with_weak_strips=sum(bool(entry['weak_strips']) for entry in diagnostics),
                     isolated_rows_with_native_comparison=len(scored),
                     expected_weak_channels=sum(len(entry['expected_weak_native_contact_ids']) for entry in scored),
                     confirmed_weak_channels=sum(len(entry['confirmed_contact_ids']) for entry in scored),
                     missed_weak_channels=sum(len(entry['missed_native_contact_ids']) for entry in scored),
                     unmatched_adc_channels=sum(len(entry['unmatched_adc_contact_ids']) for entry in scored)),
        roster=weak_rows,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    output = parser.parse_args().output.resolve()
    truth.require(output.is_relative_to(truth.LOCAL) and not output.exists(), 'Use a new derivative path in the held-out study')
    report = run()
    with output.open('xb') as stream:
        stream.write(truth.encoded(report) + b'\n')
    print(json.dumps({'summary': report['summary'], 'target': report['target']['diagnostic']}, indent=2))


if __name__ == '__main__':
    main()
