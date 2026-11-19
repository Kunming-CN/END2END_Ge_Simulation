"""Summarize native charge and saved carrier endpoints for two merged GeGI triggers."""

import argparse
from collections import defaultdict
from contextlib import closing
import json
import math
from pathlib import Path
import zlib

import gegi_digital_readout as digital
import gegi_event_store as store
from gegi_imaging import MIN_COLLECTED_KEV
import gegi_source_library as library


ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / '.local/gegi-joint-two-site'
WINDOWS = LOCAL / 'merged-trigger-windows.json'
WINDOWS_SHA = '67b6cae7d4d1c3d48945c2f77c413dcc74024f9d1f8d521d4bb6e8350494cfdf'
OUTPUT = LOCAL / 'merged-native-charge.json'
TARGETS = {'independent-b000001-250ms': 683, 'independent-b000004-250ms': 598}
IDENTITY = ('source', 'occurrence_id', 'group_id', 'raw_event_id', 'campaign_initial_id',
            'truth_edep_keV', 'metadata_sha256', 'native_current_relative_ns')
FINAL = 'wired_final_induced_keV_equiv'
REQUIRE = store.require


def bound_json(path, expected, hashes):
    data = path.read_bytes()
    REQUIRE(store.sha(data) == expected, f'Saved input changed: {path.name}')
    hashes[path.relative_to(ROOT).as_posix()] = expected
    return json.loads(data)


def endpoint_collections(event, contacts):
    """Associate original detector-local deposition rows with their saved model contacts."""
    groups = defaultdict(list)
    for step in event['steps']:
        original = event['input_steps'][step['input_step_index'] - 1]
        REQUIRE(all(step[k] == original[k] for k in ('raw_row_index', 'position_mm', 'energy_keV')),
                'Drift input and saved Ge deposition disagree')
        endpoints = {row['species']: row['contact_ids'] for row in step['endpoints']}
        electron, = endpoints['electron']
        hole, = endpoints['hole']
        REQUIRE(contacts[electron]['family'] == 'Y' and contacts[hole]['family'] == 'X',
                'Saved carrier endpoints differ from the expected face assignment')
        groups[hole, electron].append(step)
    result = []
    for (x, y), rows in sorted(groups.items()):
        energy = math.fsum(row['energy_keV'] for row in rows)
        centroid = [math.fsum(row['energy_keV'] * row['position_mm'][j] for row in rows) / energy
                    for j in range(3)]
        result.append(dict(x_contact_id=x, y_contact_id=y, deposit_keV=energy,
                           deposit_centroid_local_mm=centroid,
                           raw_row_indices=[row['raw_row_index'] for row in rows]))
    row_ids = {row_id for group in result for row_id in group['raw_row_indices']}
    REQUIRE(len(row_ids) == len(event['steps']) and row_ids == set(event['pulse_group']['row_indices'])
            and math.isclose(math.fsum(g['deposit_keV'] for g in result), event['truth_edep_keV'],
                             rel_tol=0., abs_tol=1e-7), 'Endpoint deposit groups do not close')
    return result


def threshold_summary(electrodes, contacts):
    faces = {}
    guards = []
    for family in ('X', 'Y'):
        face = [row for row in electrodes if contacts[row['contact_id']]['family'] == family]
        strips = [row for row in face if not contacts[row['contact_id']]['guard']]
        selected = [row for row in strips if row[FINAL] >= MIN_COLLECTED_KEV]
        guards.extend(row['contact_id'] for row in face if contacts[row['contact_id']]['guard']
                      and row[FINAL] >= MIN_COLLECTED_KEV)
        faces[family] = dict(all_contact_keV_equiv=math.fsum(row[FINAL] for row in face),
                             strip_signed_keV_equiv=math.fsum(row[FINAL] for row in strips),
                             above_threshold_strip_contact_ids=[row['contact_id'] for row in selected],
                             above_threshold_strip_keV_equiv=math.fsum(row[FINAL] for row in selected))
    return dict(faces=faces, above_threshold_guard_contact_ids=guards)


def read_component(conn, component, contacts, original, fc_per_kev, trigger_time):
    body, digest = conn.execute('SELECT metadata,metadata_sha256 FROM events WHERE primary_id=? AND group_id=?',
                                (component['raw_event_id'], component['group_id'])).fetchone()
    body = zlib.decompress(body)
    REQUIRE(store.sha(body) == digest == component['metadata_sha256'], 'Saved native metadata changed')
    event = json.loads(body)
    REQUIRE(event['event_id'] == component['raw_event_id'] and event['group_id'] == component['group_id']
            and event['source_group'] == component['source'] == original['source_group']
            and event['source_id'] == original['source_contract_id']
            and (event['campaign_initial_offset'] + event['event_id'] - original['raw_initial_id_base']
                 == component['campaign_initial_id'])
            and math.isclose(event['truth_edep_keV'], component['truth_edep_keV'], rel_tol=0., abs_tol=1e-7)
            and digital.terminal_contacts_complete(event), 'The original native group identity or completion differs')
    refs = event['native_signals']
    saved = {row['contact_id']: row for row in event['channels']}
    REQUIRE(event['storage']['native_dtype'] == '<f8'
            and event['storage']['native_units'] == {'time': 'ns', 'charge': 'keV'}
            and set(map(int, refs)) == set(saved) == set(contacts), 'Native units or channel census changed')

    def load_array(ref):
        row = conn.execute('SELECT count,value FROM arrays WHERE digest=?', (ref['sha256'],)).fetchone()
        REQUIRE(row and row[0] == ref['count'], 'Native waveform array is missing or changed')
        return store.unpack_array(ref['sha256'], *row)

    common_time = refs['1']['time_ns']
    time = load_array(common_time)
    widths = [b - a for a, b in zip(time, time[1:])]
    REQUIRE(time[0] == 0. and widths and all(math.isfinite(d) and d > 0. for d in widths),
            'Invalid native time grid')
    endpoint_rows = endpoint_collections(event, contacts)
    active_intervals = set()
    electrodes = []
    for cid, contact in contacts.items():
        ref = refs[str(cid)]
        q = load_array(ref['signed_induced_keV'])
        REQUIRE(ref['time_ns'] == common_time and len(q) == len(time) and q[0] == 0.
                and all(map(math.isfinite, q)), f'Invalid native charge for contact {cid}')
        deltas = [b - a for a, b in zip(q, q[1:])]
        active_intervals.update(i for i, delta in enumerate(deltas) if delta != 0.)
        integral = math.fsum(delta / width * width for delta, width in zip(deltas, widths, strict=True))
        wiring = contact['wiring_factor']
        wired = q[-1] * wiring
        REQUIRE(math.isclose(integral, q[-1], rel_tol=0., abs_tol=1e-10)
                and saved[cid]['wiring_factor'] == wiring
                and saved[cid]['untruncated_final_charge_keV'] == saved[cid]['final_wired_induced_keV'] == wired
                and saved[cid]['final_induced_keV'] == q[-1]
                and math.isclose(saved[cid]['final_charge_C'] * 1e15, wired * fc_per_kev,
                                 rel_tol=1e-14, abs_tol=1e-15), f'Signed native charge does not close for contact {cid}')
        samples = [wiring * value for value in q]
        electrodes.append(dict(contact_id=cid, signed_final_induced_keV_equiv=q[-1],
                               signed_current_integral_keV_equiv=integral,
                               wired_final_induced_keV_equiv=wired, wired_final_induced_fC=wired * fc_per_kev,
                               wired_min_induced_keV_equiv=min(samples), wired_max_induced_keV_equiv=max(samples),
                               endpoint_deposit_keV=math.fsum(row['deposit_keV'] for row in endpoint_rows
                                                             if cid in (row['x_contact_id'], row['y_contact_id']))))
    offset = component['first_ge_deposit_ns'] - trigger_time
    REQUIRE(active_intervals and component['native_current_relative_ns']
            == [time[min(active_intervals)] + offset, time[max(active_intervals) + 1] + offset],
            'Original native current timing differs from the recovered merged window')
    return {key: component[key] for key in IDENTITY} | dict(
        electrodes=electrodes, endpoint_collections=endpoint_rows, threshold_summary=threshold_summary(electrodes, contacts))


def run():
    source_paths = [Path(__file__).resolve(), *(ROOT / 'tools' / name for name in (
        'gegi_digital_readout.py', 'gegi_event_store.py', 'gegi_imaging.py', 'gegi_source_library.py'))]
    source_hashes = {p.relative_to(ROOT).as_posix(): library._hash(p) for p in source_paths}
    hashes = {}
    windows = bound_json(WINDOWS, WINDOWS_SHA, hashes)
    examples = []
    contacts = {}
    fc_per_kev = None
    for example in windows['examples']:
        name, index = example['block'], example['trigger_index']
        REQUIRE(TARGETS.get(name) == index and len(example['components']) == 2, 'Unexpected merged trigger or group count')
        folder = ROOT / '.local/gegi-dual-source' / name
        report = bound_json(folder / 'report.json', example['report_sha256'], hashes)
        trigger = report['triggers'][index - 1]
        REQUIRE(trigger == example['original_trigger'] and trigger['trigger_time_ns'] == example['trigger_time_ns']
                and report['receipt']['digital_profile_sha256'] == digital.PROFILE_SHA256,
                'Original trigger or nominal electronics profile differs')
        sources = {row['key']: row for row in report['sources']}
        components = []
        for component in example['components']:
            source = sources[component['source']]
            path = (folder / source['input_directory']['relative_to_report_directory']).resolve()
            REQUIRE(path.is_relative_to(ROOT / '.local'), 'The selected native chunk is outside the project data')
            original = source['original']
            database = path / 'events.sqlite'
            if database.relative_to(ROOT).as_posix() not in hashes:
                _, _, done, _, _, metadata, channels = library._source_inputs(path)
                REQUIRE(metadata | {'raw_initial_id_base': done['identity']['raw_initial_id_base']} == original,
                        'Source chunk differs from the original acquisition')
                library._bound(path, done['artifacts'], 'events.sqlite')
                hashes[database.relative_to(ROOT).as_posix()] = original['database_sha256']
                hashes[(path / 'DONE.json').relative_to(ROOT).as_posix()] = original['chunk_sha256']
                channel_map = {row['id']: row for row in channels}
                REQUIRE(not contacts or channel_map == contacts, 'Native electrode mapping changed between groups')
                contacts = channel_map
                eion = original['ionisation_energy_eV']
                gain = 1e18 * digital.ELECTRON_C / eion
                REQUIRE(fc_per_kev in (None, gain), 'Native charge conversion differs between groups')
                fc_per_kev = gain
            with closing(library._database(database)) as conn:
                components.append(read_component(conn, component, contacts, original, fc_per_kev, trigger['trigger_time_ns']))
        combined = [dict(contact_id=cid, wired_final_induced_keV_equiv=math.fsum(row[FINAL] for row in pair))
                    for cid, pair in zip(contacts, zip(*(c['electrodes'] for c in components), strict=True), strict=True)]
        examples.append(dict(block=name, trigger_index=index, trigger_time_ns=trigger['trigger_time_ns'],
                             components=components, combined=dict(electrodes=combined,
                                 threshold_summary=threshold_summary(combined, contacts))))
    REQUIRE(len(examples) == len(TARGETS) and {e['block'] for e in examples} == set(TARGETS)
            and all(library._hash(p) == source_hashes[p.relative_to(ROOT).as_posix()] for p in source_paths),
            'Merged trigger list or analysis source changed')
    return dict(kind='gegi_merged_native_charge_v1', status='completed', examples=examples,
                contacts=list(contacts.values()), input_sha256=hashes, source_sha256=source_hashes,
                design=dict(group_count=4, native_terminal_threshold_keV_equiv=MIN_COLLECTED_KEV,
                            ionisation_energy_eV=eion, fC_per_keV_equiv=fc_per_kev,
                            nominal_ideal_preamp_V_per_keV_equiv=digital._VOLTS_PER_KEV,
                            threshold='Apply the inclusive positive cut to each final wired electrode value after summing when combined.',
                            stage='Signed native current integrated over the original intervals. Values are induced-charge equivalents, separate from the slow ADC energy.',
                            endpoints='Deposit rows grouped by saved SSD carrier contact membership. Local centroids use deposited-energy weights. Terminal induced signals can also occur on electrodes without assigned carrier endpoints.',
                            transport_runs=0, drift_runs=0, adc_passes=0))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    output = parser.parse_args().output.resolve()
    REQUIRE(output.is_relative_to(LOCAL) and not output.exists(), 'Use a new local study output')
    result = run()
    with output.open('xb') as target:
        target.write(store.encoded(result) + b'\n')


if __name__ == '__main__':
    main()
