"""Compare saved GeGI weak-strip diagnostics with the original carrier endpoints."""

import argparse
from collections import Counter, defaultdict
from contextlib import ExitStack, closing
import gzip
import json
import math
from pathlib import Path
import zlib

import numpy as np

import gegi_digital_readout as digital
import gegi_event_store as store
from gegi_imaging import MIN_COLLECTED_KEV
from gegi_merged_native_charge import endpoint_collections
from gegi_pulse_stream import _QUIET_SAMPLES
import gegi_source_library as library
from gegi_trigger_windows import RELATIVE_NS
from gegi_weak_strip import ADC_SIGMA_V, GUARDS, SIGNIFICANCE, TAIL_GAIN


ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / '.local/gegi-joint-two-site'
ACQUISITIONS = ROOT / '.local/gegi-dual-source'
CLOCK = LOCAL / 'independent-1s-overlap-reference.json.gz'
CLOCK_SHA = '6cae1651ccc51c20eeef390ba945128584ac35220d8243b05457e3c869d2ce6f'
MEASURED = LOCAL / 'independent-1s-measured-overlap.json'
MEASURED_SHA = 'ddea3349304ada26bf6c7fed54b7ebfdc84781a3e79eeb7e81d191c4cf5aa9e1'
ADC = LOCAL / 'independent-1s-weak-strips.json.gz'
OUTPUT = LOCAL / 'independent-1s-weak-endpoints.json.gz'
REQUIRE = store.require
IDENTITY = ('block', 'trigger_index', 'trigger_time_ns', 'two_strip_ordinal', 'energy_keV', 'energy_window')
PROJECTION = ('allowed_hypotheses', 'hypotheses', 'projected_mass', 'unresolved_mass')
WEIGHTS = ('allowed_order_mass', 'unassigned_without_pairing_mass',
           'unassigned_without_allowed_order_mass', 'unassigned_without_projection_mass')
PAIRING_CLASSES = ('energy_incompatible', 'energy_compatible_unique', 'energy_compatible_ambiguous')
FALSE_POSITIVE = {
    'no_landing': 'false_positive_no_landing',
    'below_sensitivity': 'false_positive_below_endpoint_sensitivity',
    'at_or_above_collection_threshold': 'false_positive_at_or_above_endpoint_band',
}
QUIET = slice(0, _QUIET_SAMPLES)
LATE = slice(-5, None)


def bound_json(path, digest, hashes):
    raw = path.read_bytes()
    REQUIRE(store.sha(raw) == digest, f'Saved input changed: {path.name}')
    hashes[path.relative_to(ROOT).as_posix()] = digest
    return json.loads(gzip.decompress(raw) if path.suffix == '.gz' else raw)


def open_original(stack, folder, source, reference_hashes, hashes):
    chunk = (folder / source['input_directory']['relative_to_report_directory']).resolve()
    REQUIRE(chunk.is_relative_to(ROOT / '.local'), 'Selected source is outside the project archives')
    original = source['original']
    _, db, done, _, _, metadata, channels = library._source_inputs(chunk)
    REQUIRE(metadata | {'raw_initial_id_base': done['identity']['raw_initial_id_base']} == original,
            'Sealed native source differs from the original acquisition')
    db_key, seal_key = (p.relative_to(ROOT).as_posix() for p in (db, chunk / 'DONE.json'))
    REQUIRE(reference_hashes[db_key] == original['database_sha256']
            and reference_hashes[seal_key] == original['chunk_sha256'], 'Native source differs from the clock ledger')
    library._bound(chunk, done['artifacts'], 'events.sqlite')
    hashes.update({db_key: original['database_sha256'], seal_key: original['chunk_sha256']})
    return stack.enter_context(closing(library._database(db))), original, {row['id']: row for row in channels}


def native_group(conn, original, channel_map, group, trigger_time, candidate_ids):
    primary, group_id = group['raw_event_id'], group['group_id']
    stored = conn.execute('SELECT metadata,metadata_sha256 FROM events WHERE primary_id=? AND group_id=?',
                          (primary, group_id)).fetchone()
    if stored is None:
        return 'missing_native_metadata', None
    body = zlib.decompress(stored[0])
    REQUIRE(store.sha(body) == stored[1] == group['metadata_sha256'], 'Native event metadata hash changed')
    event = json.loads(body)
    onset = group['first_ge_deposit_ns']
    origin = group['parent_decay_time_ns']
    REQUIRE(event['event_id'] == primary and event['group_id'] == group_id
            and event['source_id'] == original['source_contract_id']
            and event['source_group'] == original['source_group'] == group['source']
            and event['chunk_index'] == original['chunk_index']
            and event['campaign_initial_offset'] + primary - original['raw_initial_id_base']
            == group['campaign_initial_id']
            and event['parent_primary_time_ns'] == 0.
            and math.isclose(event['group_origin_time_ns'], onset - origin, abs_tol=1e-7, rel_tol=0.)
            and math.isclose(event['pulse_group']['last_deposit_time_ns'],
                             group['last_ge_deposit_ns'] - origin, abs_tol=1e-7, rel_tol=0.)
            and math.isclose(event['truth_edep_keV'], group['truth_edep_keV'], abs_tol=1e-7, rel_tol=0.)
            and event['status'] == group['native_status'], 'Native group identity differs from the clock ledger')
    if not digital.terminal_contacts_complete(event):
        return 'incomplete_native_endpoints', None
    if any(len(endpoint['contact_ids']) != 1 for step in event['steps'] for endpoint in step['endpoints']):
        return 'ambiguous_native_endpoint_assignment', None
    if not group['native_available'] or event['native_signals'] is None:
        return 'unavailable_native_signals', None

    cells = endpoint_collections(event, channel_map)
    by_contact = defaultdict(list)
    for cell in cells:
        for contact in (cell['x_contact_id'], cell['y_contact_id']):
            by_contact[contact].append(cell)
    refs = event['native_signals']
    channels = {row['contact_id']: row for row in event['channels']}
    REQUIRE(event['storage']['native_dtype'] == '<f8'
            and event['storage']['native_units'] == {'time': 'ns', 'charge': 'keV'}
            and set(map(int, refs)) == set(channels) == set(channel_map), 'Native waveform schema changed')

    def load_array(ref):
        found = conn.execute('SELECT count,value FROM arrays WHERE digest=?', (ref['sha256'],)).fetchone()
        REQUIRE(found and found[0] == ref['count'], 'Original native current array missing')
        return np.asarray(store.unpack_array(ref['sha256'], *found))

    time_ref = refs['1']['time_ns']
    time = load_array(time_ref)
    REQUIRE(len(time) > 1 and time[0] == 0. and np.isfinite(time).all() and np.all(np.diff(time) > 0.),
            'Invalid native trace grid')
    adc_times = RELATIVE_NS - (onset - trigger_time)
    electrodes = {}
    for cid in candidate_ids:
        ref, saved = refs[str(cid)], channels[cid]
        signal = load_array(ref['signed_induced_keV'])
        wiring = channel_map[cid]['wiring_factor']
        wired = signal * wiring
        final = float(wired[-1])
        REQUIRE(ref['time_ns'] == time_ref and len(signal) == len(time) and signal[0] == 0.
                and np.isfinite(signal).all() and saved['wiring_factor'] == wiring
                and saved['final_induced_keV'] == signal[-1]
                and saved['untruncated_final_charge_keV'] == saved['final_wired_induced_keV'] == final
                and saved['untruncated_charge_end_ns'] == time[-1], 'Native charge or terminal scalar changed')
        samples = np.interp(adc_times, time, wired, left=0., right=final)
        late = samples[LATE]
        rows = by_contact[cid]
        endpoint_energy = math.fsum(row['deposit_keV'] for row in rows)
        electrodes[cid] = dict(
            endpoint_input_keV=endpoint_energy,
            endpoint_row_count=sum(len(row['raw_row_indices']) for row in rows),
            native_terminal_wired_keV_equiv=final,
            native_terminal_residual_keV_equiv=final - endpoint_energy,
            native_max_abs_wired_excursion_keV_equiv=float(np.max(np.abs(wired))),
            native_late_wired_step_keV_equiv=float(np.mean(late) - np.mean(samples[QUIET])),
            native_late_wired_delta_keV_equiv=float(np.mean(late[-2:]) - np.mean(late[:2])),
            native_late_wired_range_keV_equiv=[float(np.min(late)), float(np.max(late))],
        )
    return 'measured', dict(cells=cells, electrodes=electrodes, native_input_group_sha256=event['input_event_sha256'],
                            native_trace_end_ns_relative_to_trigger=float(time[-1] + onset - trigger_time))


def compare_contact(adc, native, floor, sigma):
    saturated = adc.get('adc_saturated')
    if adc['status'] == 'unevaluable':
        REQUIRE(adc.get('step_keV_equiv') is None, 'Unevaluable ADC strip has a late-step measurement')
    evaluable = adc['status'] != 'unevaluable' and saturated is False
    detected = adc['status'] == 'weak_strip'
    REQUIRE(not detected or evaluable, 'Unevaluable ADC strip was marked as detected')
    row = dict(contact_id=adc['contact_id'], adc_status=adc['status'],
               adc_saturated=saturated, adc_evaluable=evaluable, adc_detected=detected,
               adc_step_keV_equiv=adc.get('step_keV_equiv'),
               adc_late_difference_keV_equiv=adc.get('late_difference_keV_equiv'))
    if native is None:
        return row | dict(endpoint_input_keV=None, endpoint_input_band=None, endpoint_row_count=None,
                          native_class=None, near_sensitivity=None, comparison='unavailable_native')
    energy, terminal = native['endpoint_input_keV'], native['native_terminal_wired_keV_equiv']
    if energy > 0.:
        band = ('below_sensitivity' if energy < floor else
                'weak' if energy < MIN_COLLECTED_KEV else 'at_or_above_collection_threshold')
        attribution = ('collection_with_terminal_residual'
                       if abs(native['native_terminal_residual_keV_equiv']) >= floor else 'collection')
    else:
        band = 'no_landing'
        if abs(terminal) >= floor:
            attribution = 'induced_only_terminal'
        elif native['native_max_abs_wired_excursion_keV_equiv'] >= floor:
            attribution = 'induced_only_transient'
        else:
            attribution = 'no_resolved_native_signal'
    if not evaluable:
        comparison = 'unevaluable_adc'
    elif band == 'weak':
        comparison = 'true_positive' if detected else 'false_negative'
    else:
        comparison = FALSE_POSITIVE[band] if detected else 'true_negative'
    return row | native | dict(endpoint_input_band=band, native_class=attribution, comparison=comparison,
                               near_sensitivity=abs(energy - floor) <= sigma or abs(terminal - floor) <= sigma)


def inspect_event(adc, measured, clock, ledger, sources, trigger, floor, sigma):
    REQUIRE(all(adc[key] == measured[key] == clock[key] for key in (*IDENTITY, *PROJECTION))
            and all(adc[key] == measured[key] for key in WEIGHTS)
            and adc['rise_end_ns'] == measured['rise_end_ns'] == trigger['rise_end_ns']
            and adc['trigger_time_ns'] == trigger['trigger_time_ns']
            and adc['two_strip_pairings'] == trigger['two_strip_pairings'],
            'ADC diagnostic, clock, projection and original trigger identities differ')
    count = trigger['two_strip_pairings']['compatible_pairing_count']
    REQUIRE(count <= 2 and adc['pairing_class'] == PAIRING_CLASSES[count], 'Saved pairing class differs')
    collectors = set(trigger['x_collecting_strips'] + trigger['y_collecting_strips'])
    REQUIRE(len(collectors) == 4 and collectors == set(adc['collectors']), 'The recorded collector scope changed')
    candidate_ids = sorted(set(digital.CONTACT_IDS) - collectors - GUARDS)
    diagnostic = adc['adc_diagnostic']
    adc_contacts = {c['contact_id']: c for c in diagnostic['contacts']}
    REQUIRE(len(adc_contacts) == len(diagnostic['contacts']) and set(adc_contacts) == set(candidate_ids),
            'ADC and native contact scopes differ')
    adc_sigma = diagnostic.get('sigma_keV_equiv')
    REQUIRE(diagnostic['status'] != 'measured' or
            (adc_sigma == sigma and diagnostic['threshold_keV_equiv'] == floor),
            'The recorded ADC modeled sensitivity differs from the fixed diagnostic')
    hits = {row['contact_id'] for row in diagnostic['weak_strips']}
    REQUIRE(hits == {cid for cid, row in adc_contacts.items() if row['status'] == 'weak_strip'},
            'The fixed ADC detections changed')

    anchor = clock['timing_anchor_group_index']
    group = ledger[anchor] if anchor is not None else None
    REQUIRE(all(adc[key] == clock[key] for key in
                ('timing_association', 'timing_link_scope', 'timing_anchor_group_index', 'plausible_group_indices'))
            and adc['pairings'] == measured['pairings'], 'The ADC clock anchor or projection pairings changed')
    status, native = 'unavailable_clock_assignment', None
    if (clock['timing_association'] == 'unique_matched' and group is not None
            and clock['plausible_group_indices'] == [anchor]):
        if (clock['native_current_adc'] == 'absent' and not clock['unavailable_native_group_indices']
                and [c['group_index'] for c in clock['native_current_components']] == [anchor]):
            status, native = native_group(*sources[group['source']], group, adc['trigger_time_ns'], candidate_ids)
        else:
            status = 'unresolved_additional_native_current'
    contacts = [compare_contact(adc_contacts[cid], native['electrodes'][cid] if native else None, floor, sigma)
                for cid in candidate_ids]
    comparable = [c for c in contacts if c['adc_evaluable'] and c['endpoint_input_band'] is not None]
    expected = any(c['endpoint_input_band'] == 'weak' for c in comparable)
    detected = any(c['adc_detected'] for c in comparable)
    trigger_class = 'unevaluable'
    if comparable:
        if expected:
            trigger_class = 'true_positive' if detected else 'false_negative'
        else:
            trigger_class = 'false_positive' if detected else 'true_negative'
    return {key: adc[key] for key in (*IDENTITY, *PROJECTION, *WEIGHTS, 'rise_end_ns', 'pairing_class')} | dict(
        measured_pairings=adc['two_strip_pairings'], projection_pairings=measured['pairings'],
        collector_contact_ids=sorted(collectors), adc_status=diagnostic['status'], adc_sigma_keV_equiv=adc_sigma,
        adc_detected_contact_ids=sorted(hits), trigger_comparison=trigger_class,
        timing_anchor_group_index=anchor, timing_link_scope=clock['timing_link_scope'],
        nearest_other_group=clock['nearest_other_group'], native_group=group,
        native_status=status, endpoint_collections=native['cells'] if native else None,
        endpoint_collection_cell_count=len(native['cells']) if native else None,
        native_input_group_sha256=native['native_input_group_sha256'] if native else None,
        native_trace_end_ns_relative_to_trigger=native['native_trace_end_ns_relative_to_trigger'] if native else None,
        contacts=contacts,
    )


def summarize(rows):
    contacts = [c for row in rows for c in row['contacts']]
    expected = [c for c in contacts if c['endpoint_input_band'] == 'weak']
    counts = Counter(c['comparison'] for c in contacts)
    comparable = [c for c in contacts if c['adc_evaluable'] and c['native_class'] is not None]
    contact_flags = [set(c['comparison'] for c in row['contacts']) for row in rows]
    false_positives = set(FALSE_POSITIVE.values())
    native_keys = [(r, (r['native_group']['source'], r['native_group']['campaign_initial_id'],
                       r['native_group']['group_id'])) for r in rows if r['native_status'] == 'measured']
    return dict(
        triggers=len(rows),
        adc_status=Counter(row['adc_status'] for row in rows),
        native_status=Counter(row['native_status'] for row in rows),
        timing_link_scope=Counter(row['timing_link_scope'] for row in rows),
        distinct_native_groups=len({key for _, key in native_keys}),
        distinct_native_groups_with_adc_detection=len({key for row, key in native_keys
                                                     if row['adc_detected_contact_ids']}),
        distinct_native_group_contact_detections=len({(*key, cid) for row, key in native_keys
                                                     for cid in row['adc_detected_contact_ids']}),
        endpoint_collection_cell_counts=Counter(str(row['endpoint_collection_cell_count'])
                                                 for row, _ in native_keys),
        **{key: math.fsum(row[key] for row in rows) for key in (*PROJECTION, *WEIGHTS)},
        scoped_contacts=len(contacts),
        adc_evaluable_contacts=sum(c['adc_evaluable'] for c in contacts),
        adc_saturated_contacts=sum(c['adc_saturated'] is True for c in contacts),
        compared_contacts=len(comparable),
        expected_weak_contacts=len(expected),
        expected_weak_evaluable_contacts=sum(c['adc_evaluable'] for c in expected),
        expected_weak_unevaluable_contacts=sum(not c['adc_evaluable'] for c in expected),
        adc_detected_contacts=sum(c['adc_detected'] for c in contacts),
        contact_comparison=counts,
        trigger_comparison=Counter(row['trigger_comparison'] for row in rows),
        adc_positive_with_native_classes=Counter(c['native_class'] for c in comparable if c['adc_detected']),
        triggers_with_adc_detection=sum(bool(row['adc_detected_contact_ids']) for row in rows),
        triggers_with_endpoint_weak=sum(any(c['endpoint_input_band'] == 'weak' for c in row['contacts']) for row in rows),
        triggers_with_matched_contact=sum('true_positive' in flags for flags in contact_flags),
        triggers_with_missed_contact=sum('false_negative' in flags for flags in contact_flags),
        triggers_with_false_positive_contact=sum(bool(false_positives & flags) for flags in contact_flags),
    )


def populations(rows):
    return {'all': summarize(rows),
            'energy_compatible': summarize([r for r in rows if r['pairing_class'] != PAIRING_CLASSES[0]]),
            **{label: summarize([r for r in rows if r['pairing_class'] == label]) for label in PAIRING_CLASSES}}


def run(adc_path, adc_sha):
    implementation = [Path(__file__).resolve(), *(ROOT / 'tools' / name for name in (
        'gegi_digital_readout.py', 'gegi_event_store.py', 'gegi_imaging.py', 'gegi_merged_native_charge.py',
        'gegi_pulse_stream.py', 'gegi_source_library.py', 'gegi_trigger_windows.py', 'gegi_weak_strip.py'))]
    source_hashes = {p.relative_to(ROOT).as_posix(): library._hash(p) for p in implementation}
    hashes = {}
    clock = bound_json(CLOCK, CLOCK_SHA, hashes)
    measured = bound_json(MEASURED, MEASURED_SHA, hashes)
    adc = bound_json(adc_path, adc_sha, hashes)
    REQUIRE(clock['kind'] == 'gegi_independent_clock_overlap_reference_v1'
            and adc['kind'] == 'gegi_independent_weak_strip_study_v1'
            and clock['design']['supports_ns']['adc'] == [int(RELATIVE_NS[0]), int(RELATIVE_NS[-1])]
            and len(clock['blocks']) == 4
            and [len(b['events']) for b in clock['blocks']] == [79, 105, 73, 67],
            'The original four-block weak-strip scope differs')
    REQUIRE(clock['input_sha256'][MEASURED.relative_to(ROOT).as_posix()] == MEASURED_SHA
            and adc['input_sha256'][CLOCK.relative_to(ROOT).as_posix()] == CLOCK_SHA
            and adc['input_sha256'][MEASURED.relative_to(ROOT).as_posix()] == MEASURED_SHA,
            'The endpoint comparison and ADC diagnostics bind different saved clocks')
    adc_rows = {(row['block'], row['trigger_index']): row for row in adc['events']}
    measured_rows = {(row['block'], row['trigger_index']): row for row in measured['events']}
    REQUIRE(len(adc_rows) == len(adc['events']) == len(measured_rows) == len(measured['events']) == 324
            and adc_rows.keys() == measured_rows.keys(), 'The ADC and measured trigger rosters differ')
    weights = np.exp(RELATIVE_NS / digital._TAU)
    sigma = ADC_SIGMA_V / TAIL_GAIN * math.hypot(np.linalg.norm(weights[QUIET]) / _QUIET_SAMPLES,
                                               np.linalg.norm(weights[LATE]) / 5)
    floor = SIGNIFICANCE * sigma
    blocks = {}
    for block in clock['blocks']:
        prov = block['provenance']
        name = prov['name']
        folder = ACQUISITIONS / name
        report = bound_json(folder / 'report.json', prov['report_sha256'], hashes)
        REQUIRE(report['receipt']['digital_profile_sha256'] == digital.PROFILE_SHA256
                and report['receipt']['digital_timing_sha256'] == digital.TIMING_SHA256
                and report['receipt']['known_component_adc_sha256'] == prov['known_component_adc_sha256'],
                'Frozen digital electronics profiles differ')
        with ExitStack() as stack:
            sources = {s['key']: open_original(stack, folder, s, clock['input_sha256'], hashes)
                       for s in report['sources']}
            blocks[name] = [inspect_event(adc_rows[(name, row['trigger_index'])],
                                          measured_rows[(name, row['trigger_index'])], row, block['group_ledger'],
                                          sources, report['triggers'][row['trigger_index'] - 1], floor, sigma)
                            for row in block['events']]
    first, second, third, fourth = blocks.values()
    events = first + second + third + fourth
    totals = populations(events)
    REQUIRE({(row['block'], row['trigger_index']) for row in events} == adc_rows.keys()
            and totals['energy_incompatible']['triggers'] == 59
            and totals['energy_compatible']['triggers'] == 265
            and totals['all']['projected_mass'] == 254.
            and totals['all']['unresolved_mass'] == 70., 'The frozen pairing or projection denominator changed')
    REQUIRE(all(library._hash(ROOT / rel) == digest for rel, digest in source_hashes.items()),
            'Endpoint comparison implementation changed during the run')
    return dict(
        kind='gegi_independent_weak_strip_endpoints_v1', status='completed', input_sha256=hashes,
        source_sha256=source_hashes,
        design=dict(
            adc_sigma_keV_equiv=sigma, minimum_weak_step_keV_equiv=floor,
            collection_threshold_keV=MIN_COLLECTED_KEV, significance=SIGNIFICANCE,
            positive_scope='Other non-guard, noncollector strips; ADC saturation and unavailable settling are withheld.',
            endpoint_reference='Match each saved carrier endpoint to its contact. Sum original deposited energy once '
                               'per face as charge-equivalent input using the nominal ionization model. A weak '
                               'endpoint lies in the inclusive lower and exclusive upper fixed ADC amplitude band.',
            induced_reference='Use signed wired native charge, linearly sampled at the original window times, '
                              'without the preamplifier or noise. The terminal residual is native wire charge minus '
                              'endpoint-assigned input. It may contain weighting-field and endpoint effects. Its '
                              'magnitude at or above the 5-sigma amplitude scale flags a contribution worth separating.',
            near_sensitivity='Positive endpoint input or terminal wired signal lies within one modeled sigma of '
                             'the fixed 5-sigma lower boundary.',
            clock_scope='Require one unique clock group and no additional native current on the ADC support. '
                         'Preserve proximity labels, including prior analog history outside the native-current test.',
            trigger_comparison='Any ADC positive versus any weak endpoint among comparable strips in the trigger. '
                               'Matched-contact, missed-contact and false-positive-contact trigger counts separately '
                               'retain mismatches when a trigger has positives on both sides.',
            new_transport_runs=0, new_drift_runs=0, new_adc_replays=0,
        ),
        views={'full': totals, 'first_half': populations(first + second), 'second_half': populations(third + fourth)},
        blocks={name: populations(rows) for name, rows in blocks.items()}, events=events,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adc', type=Path, default=ADC)
    parser.add_argument('--adc-sha256', required=True)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    args = parser.parse_args()
    output = args.output.resolve()
    REQUIRE(output.is_relative_to(LOCAL) and not output.exists(), 'Use a new derivative endpoint report path')
    result = run(args.adc.resolve(), args.adc_sha256)
    with output.open('xb') as stream:
        stream.write(gzip.compress(store.encoded(result) + b'\n', mtime=0))
    print(json.dumps(result['views']['full'], indent=2))


if __name__ == '__main__':
    main()
