"""Trace the two saved Co-60 line histories from parent tracks to collection cells."""

import argparse
from collections import defaultdict
from contextlib import closing
import gzip
import hashlib
import json
from math import fsum, isclose, isfinite
from pathlib import Path
import zlib

import gegi_event_store as store
from gegi_digital_readout import terminal_contacts_complete
from gegi_merged_native_charge import endpoint_collections
from gegi_parent_gamma_reference import ancestry
from gegi_rejection_diagnostic import pos as birth_position_mm
import gegi_source_library as library
from gegi_weak_strip_endpoints import ACQUISITIONS, CLOCK, CLOCK_SHA, IDENTITY, LOCAL, ROOT, bound_json


SELECTION = LOCAL / 'independent-1s-intersection-influence.json.gz'
SELECTION_SHA = '48e5f25bc9bfb50accb4ce67200b6017c28ae380b2b1e0dfd2605228b4dec43d'
ENDPOINTS = LOCAL / 'independent-1s-weak-endpoints.json.gz'
ENDPOINTS_SHA = '40ade04dfccdf33cf2d8593f255b2cc462a7194e73e957b6b4cc235d8da69319'
OUTPUT = LOCAL / 'cobalt-history-ancestry.json'
TARGETS = ((1173.23, 3, 73, 1418, (349, 414)), (1332.49, 2, 72, 7284, (6, 982)))
SOURCE = 'co60-right'
REQUIRE = store.require


def relative(path):
    return path.relative_to(ROOT).as_posix()


def close(left, right):
    return isclose(left, right, rel_tol=0., abs_tol=1e-7)


def frozen_sources():
    names = ('cobalt_history_study', 'cobalt_photon_steps', 'digital_readout', 'event_store',
             'merged_native_charge', 'parent_gamma_reference', 'rejection_diagnostic',
             'source_library', 'two_site_geometry_reference', 'weak_strip_endpoints')
    paths = [ROOT / f'tools/gegi_{name}.py' for name in names]
    return {relative(path): library._hash(path) for path in paths}


def original_parent(folder, done, manifest, ref, raw_id, hashes):
    path = library._bound(folder, done['artifacts'], ref)
    archive = done['archives'][library._STREAM]
    REQUIRE(ref.endswith('.gz') and archive['sha256'] == done['artifacts'][ref]['sha256'],
            'Original transport archive seal changed')
    hashes[relative(path)] = archive['sha256']
    digest, size, matches = hashlib.sha256(), 0, []
    with gzip.open(path, 'rb') as stream:
        for line in stream:
            digest.update(line)
            size += len(line)
            event = json.loads(line)
            if event['initial_primary_id'] == raw_id:
                matches.append((event, store.sha(line)))
    REQUIRE(digest.hexdigest() == archive['original_sha256'] == manifest['events_sha256']
            and size == archive['original_bytes'] and len(matches) == 1,
            'Original parent stream, row count or selected primary changed')
    return matches[0]


def bind_occurrences(selected, endpoints, clock, report, block, layer, raw_id, trigger_ids):
    REQUIRE(selected['selected_pair_same_history'] and tuple(row['trigger_index'] for row in
            selected['selected_pair_triggers']) == trigger_ids, 'Preselected imaging pair changed')
    clock_rows = {row['trigger_index']: row for row in clock['events']}
    occurrences, groups = [], []
    for expected in selected['selected_pair_triggers']:
        trigger_id = expected['trigger_index']
        endpoint = endpoints[block, trigger_id]
        reference = clock_rows[trigger_id]
        trigger = report['triggers'][trigger_id-1]
        anchor = reference['timing_anchor_group_index']
        REQUIRE(anchor is not None and reference['plausible_group_indices'] == [anchor]
                and reference['timing_association'] == 'unique_matched'
                and reference['native_current_adc'] == 'absent'
                and not reference['unavailable_native_group_indices']
                and [row['group_index'] for row in reference['native_current_components']] == [anchor],
                'Original occurrence no longer uniquely associated on its ADC window')
        group = clock['group_ledger'][anchor]
        REQUIRE(group == endpoint['native_group'] and group['trigger_index'] == trigger_id-1
                and group['raw_event_id'] == raw_id and group['group_id'] == 0
                and group['source'] == SOURCE and endpoint['block'] == expected['block'] == block
                and endpoint['energy_window'] == reference['energy_window'] == layer
                and all(group[key] == value for key, value in expected['native_group'].items())
                and all(endpoint[key] == reference[key] == expected[key] for key in
                        ('trigger_index', 'trigger_time_ns', 'two_strip_ordinal', 'energy_keV'))
                and all(trigger[key] == endpoint[key] for key in ('trigger_time_ns', 'energy_keV', 'rise_end_ns'))
                and trigger['two_strip_pairings'] == endpoint['measured_pairings']
                and endpoint['native_status'] == 'measured' and endpoint['endpoint_collection_cell_count'] == 3
                and endpoint['projected_mass'] == 1. and endpoint['unresolved_mass'] == 0.,
                'Saved selection, readout, clock or endpoint occurrence differs')
        groups.append(group)
        occurrences.append({key: endpoint[key] for key in IDENTITY} | dict(
            occurrence_id=group['occurrence_id'], parent_decay_time_ns=group['parent_decay_time_ns'],
            first_ge_deposit_ns=group['first_ge_deposit_ns'], last_ge_deposit_ns=group['last_ge_deposit_ns'],
            rise_end_ns=trigger['rise_end_ns'], adc_detected_contact_ids=endpoint['adc_detected_contact_ids'],
            collector_contact_ids=endpoint['collector_contact_ids'], measured_pairings=endpoint['measured_pairings'],
            projection_pairings=endpoint['projection_pairings']))
    REQUIRE(len({row['occurrence_id'] for row in groups}) == 2
            and len({row['metadata_sha256'] for row in groups}) == 1, 'Expected two uses of a single native history')
    return occurrences, groups


def native_event(folder, db, done, parent, mark, groups):
    library._bound(folder, done['artifacts'], 'events.sqlite')
    with closing(library._database(db)) as conn:
        blob, digest = conn.execute('SELECT metadata,metadata_sha256 FROM events WHERE primary_id=? AND group_id=0',
                                    (mark['raw_event_id'],)).fetchone()
    data = zlib.decompress(blob)
    event = json.loads(data)
    original_group = event['input_group']
    original_rows = {row['raw_row_index']: row for row in parent['steps']}
    group_rows = [original_rows[row_id] for row_id in mark['groups'][0]['raw_row_indices']]
    REQUIRE(store.sha(data) == digest == groups[0]['metadata_sha256']
            and store.sha(store.encoded(original_group)) == event['input_event_sha256']
            and original_group['parent_event_metadata'] == {k: v for k, v in parent.items()
                                                           if k not in ('steps', 'pulse_groups')}
            and original_group['pulse_group'] == event['pulse_group'] == parent['pulse_groups'][0]
            and original_group['steps'] == event['input_steps'] == group_rows
            and len(parent['pulse_groups']) == len(mark['groups']) == 1
            and event['event_id'] == event['initial_primary_id'] == event['global_decay_id'] == mark['raw_event_id']
            and event['campaign_initial_offset'] + mark['ordinal'] == mark['campaign_initial_id']
            and event['source_id'] == parent['source_id'] and event['source_group'] == SOURCE
            and event['chunk_index'] == done['identity']['chunk_index'] and event['group_id'] == 0
            and event['parent_primary_time_ns'] == parent['vertex']['time'] == 0.
            and event['group_origin_time_ns'] == mark['groups'][0]['first_deposit_since_parent_ns']
            and event['status'] == 'completed' and terminal_contacts_complete(event),
            'Original parent rows and native group metadata are not in exact agreement')
    for group in groups:
        REQUIRE(group['campaign_initial_id'] == mark['campaign_initial_id']
                and close(group['first_ge_deposit_ns'] - group['parent_decay_time_ns'], event['group_origin_time_ns'])
                and close(group['last_ge_deposit_ns'] - group['parent_decay_time_ns'],
                          event['pulse_group']['last_deposit_time_ns'])
                and close(group['truth_edep_keV'], event['truth_edep_keV']),
                'Acquisition clock disagrees with the original decay-relative group')
    return event


def cell_shares(rows, channels):
    cells = defaultdict(list)
    for row in rows:
        cells[tuple(row['collection_cell'])].append(row)
    return [dict(x_contact_id=x, y_contact_id=y, x_strip=channels[x]['name'], y_strip=channels[y]['name'],
                 deposited_energy_keV=fsum(row['energy_keV'] for row in members),
                 raw_row_indices=[row['raw_row_index'] for row in members])
            for (x, y), members in sorted(cells.items())]


def trace_deposition(parent, event, channels, manifest):
    tracks = {track['trackid']: track for track in parent['tracks']}
    names = {row['procid']: row['name'] for row in manifest['processes']}
    units = manifest['raw_tables']['tracks']['columns']
    REQUIRE(len(tracks) == len(parent['tracks']) and len(names) == len(manifest['processes'])
            and all(track['evtid'] == parent['event_id'] for track in tracks.values())
            and units['ekin']['units'] == 'MeV' and units['time']['units'] == 'ns'
            and all(units[axis]['units'] == 'm' for axis in ('xloc', 'yloc', 'zloc'))
            and manifest['coordinate_transform']['rotation_local_to_global'] == [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
            and manifest['coordinate_transform']['translation_global_mm'] == [0, 0, 0],
            'Track identity, birth units or detector coordinate convention changed')
    collections = endpoint_collections(event, channels)
    row_cell = {index: (cell['x_contact_id'], cell['y_contact_id'])
                for cell in collections for index in cell['raw_row_indices']}
    native_by_row = {row['raw_row_index']: row for row in event['steps']}
    rows, anchored = [], defaultdict(list)
    for step in event['input_steps']:
        row_id, tid = step['raw_row_index'], step['track_id']
        track = tracks[tid]
        root, _, reason = ancestry(tid, tracks)
        REQUIRE(step['raw_table'] == 'stp/germanium'
                and track['particle'] == step['particle_pdg'] == step['pdg']
                and track['parent_trackid'] == step['parent_track_id']
                and 0. < step['energy_keV'] < float('inf')
                and track['time'] <= step['time_ns'] + 1e-12
                and reason in (None, 'no_gamma_ancestor'), 'Deposit or ancestral track identity differs')
        chain = [tid]
        while tracks[chain[-1]]['parent_trackid']:
            chain.append(tracks[chain[-1]]['parent_trackid'])
        nearest = next((i for i, t in enumerate(chain) if tracks[t]['particle'] == 22), None)
        photon = chain[nearest] if nearest is not None else None
        child = tracks[chain[nearest-1]] if nearest else None
        row = step | dict(track_chain_to_primary=chain, gamma_root_track_id=root, photon_track_id=photon,
                          immediate_child_track_id=child['trackid'] if child else None,
                          collection_cell=list(row_cell[row_id]), native_step=native_by_row[row_id])
        if child and abs(child['particle']) == 11:
            key = (root, photon, child['time'], birth_position_mm(child), child['procid'])
            anchored[key].append(row)
        else:
            row['interaction_index'] = None
            row['unassigned_interaction_reason'] = (reason or ('direct_gamma_deposit' if child is None else
                                                                'unsupported_immediate_child_particle'))
        rows.append(row)

    interactions = []
    for index, (key, members) in enumerate(sorted(anchored.items(), key=lambda item: item[0][2]), 1):
        root, photon, time, position, process = key
        for row in members:
            row['interaction_index'] = index
        cells = cell_shares(members, channels)
        shares = fsum(cell['deposited_energy_keV'] for cell in cells)
        energy = fsum(row['energy_keV'] for row in members)
        REQUIRE(close(shares, energy), 'Birth-anchor energy does not close by endpoint collection')
        interactions.append(dict(interaction_index=index, gamma_root_track_id=root, photon_track_id=photon,
                                 birth_process=names[process], birth_process_id=process, birth_time_ns=time,
                                 birth_global_mm=list(position), birth_local_mm=list(position),
                                 birth_position_mm=list(position), deposited_energy_keV=energy,
                                 charged_child_track_ids=sorted({row['immediate_child_track_id'] for row in members}),
                                 collection_cells=cells, raw_row_indices=[row['raw_row_index'] for row in members]))

    roots = []
    for tid, track in sorted(tracks.items()):
        if track['particle'] != 22 or ancestry(tid, tracks) != (tid, None, None):
            continue
        members = [row for row in rows if row['gamma_root_track_id'] == tid]
        unassigned = [row for row in members if row['interaction_index'] is None]
        energy, birth = fsum(row['energy_keV'] for row in members), track['ekin'] * 1000.
        assigned_energy = fsum(row['deposited_energy_keV'] for row in interactions if row['gamma_root_track_id'] == tid)
        unassigned_energy = fsum(row['energy_keV'] for row in unassigned)
        process = names[track['procid']]
        line_names = [line['name'] for line in manifest['source_contract']['diagnostic_lines']
                      if process == 'RadioactiveDecay' and line['window_keV'][0] <= birth <= line['window_keV'][1]]
        REQUIRE(isfinite(birth) and birth > 0 and close(assigned_energy + unassigned_energy, energy),
                'Gamma-family birth or deposit partition changed')
        roots.append(dict(track_id=tid, raw_track_row_index=track['raw_row_index'],
                          parent_track_id=track['parent_trackid'], parent_particle_pdg=tracks[track['parent_trackid']]['particle'],
                          birth_process=process, birth_global_mm=list(birth_position_mm(track)), birth_time_ns=track['time'],
                          birth_energy_keV=birth, matched_source_lines=line_names, deposited_energy_keV=energy,
                          assigned_interaction_energy_keV=assigned_energy, unassigned_interaction_energy_keV=unassigned_energy,
                          birth_minus_ge_deposition_keV=birth-energy, collection_cells=cell_shares(members, channels)))

    assigned = fsum(row['deposited_energy_keV'] for row in interactions)
    unassigned_rows = [row for row in rows if row['interaction_index'] is None]
    unknown = fsum(row['energy_keV'] for row in unassigned_rows)
    unrooted = fsum(row['energy_keV'] for row in rows if row['gamma_root_track_id'] is None)
    rooted = fsum(root['deposited_energy_keV'] for root in roots)
    total = fsum(row['energy_keV'] for row in rows)
    endpoint_total = fsum(cell['deposit_keV'] for cell in collections)
    REQUIRE(all(close(value, total) for value in (assigned+unknown, rooted+unrooted, endpoint_total,
                event['truth_edep_keV'], parent['truth_edep_keV'], parent['material_energy_keV']['G4_Ge'])),
            'Separate birth-anchor, gamma-family, endpoint and original transport ledgers do not close')
    checks = dict(assigned_plus_unassigned_minus_total_keV=assigned+unknown-total,
                  rooted_plus_unrooted_minus_total_keV=rooted+unrooted-total,
                  endpoints_minus_total_keV=endpoint_total-total, raw_ge_material_minus_total_keV=
                  parent['material_energy_keV']['G4_Ge']-total)
    cells = [cell | {'deposit_centroid_local_mm': old['deposit_centroid_local_mm']}
             for cell, old in zip(cell_shares(rows, channels), collections, strict=True)]
    return dict(deposited_energy_keV=total, gamma_roots=roots, interactions=interactions, collection_cells=cells,
                assigned_interaction_energy_keV=assigned, unassigned_interaction_energy_keV=unknown,
                unassigned_interaction_collection_cells=cell_shares(unassigned_rows, channels),
                unrooted_gamma_energy_keV=unrooted, closure=checks, rows=rows, tracks=parent['tracks']), collections


def run():
    from gegi_cobalt_photon_steps import photon_path

    sources, hashes, histories = frozen_sources(), {}, []
    selection = bound_json(SELECTION, SELECTION_SHA, hashes)
    endpoint_input = bound_json(ENDPOINTS, ENDPOINTS_SHA, hashes)
    clock_input = bound_json(CLOCK, CLOCK_SHA, hashes)
    endpoints = {(row['block'], row['trigger_index']): row for row in endpoint_input['events']}
    clock_hashes = clock_input['input_sha256']
    for line, block_index, chunk_index, raw_id, trigger_ids in TARGETS:
        layer, block = f'{line:g}_keV', f'independent-b{block_index:06d}-250ms'
        clock = clock_input['blocks'][block_index-1]
        provenance = clock['provenance']
        report_path = ACQUISITIONS / block / 'report.json'
        REQUIRE(provenance['name'] == block and provenance['report_sha256'] == clock_hashes[relative(report_path)],
                'Clock and acquisition receipts disagree')
        report = bound_json(report_path, provenance['report_sha256'], hashes)
        occurrences, groups = bind_occurrences(selection['lines'][layer], endpoints, clock, report, block, layer,
                                              raw_id, trigger_ids)
        source, = (row for row in report['sources'] if row['key'] == SOURCE)
        chunk = (report_path.parent / source['input_directory']['relative_to_report_directory']).resolve()
        REQUIRE(chunk.is_relative_to(ROOT / '.local'), 'Acquisition source escaped the original archive root')
        folder, db, done, manifest, ref, metadata, channels = library._source_inputs(chunk)
        REQUIRE(metadata | {'raw_initial_id_base': done['identity']['raw_initial_id_base']} == source['original']
                and metadata['chunk_index'] == chunk_index and metadata['source_position_mm'] == [40., 0., 40.] and
                metadata['source_group'] == SOURCE, 'Sealed source chunk differs from the original cobalt acquisition')
        for file, digest in (('DONE.json', metadata['chunk_sha256']), ('events.sqlite', metadata['database_sha256']),
                             (library._MANIFEST, done['artifacts'][library._MANIFEST]['sha256']),
                             (ref, done['artifacts'][ref]['sha256'])):
            key = relative(folder/file)
            REQUIRE(clock_hashes[key] == digest, f'Original clock source hash changed for {file}')
            hashes[key] = digest
        for file in ('source-checked.json', 'transport/geometry.gdml', 'transport/run.mac'):
            hashes[relative(folder/file)] = done['artifacts'][file]['sha256']
        complete = folder.parent.parent.parent / 'COMPLETE.json'
        hashes[relative(complete)] = library._hash(complete)
        parent, parent_hash = original_parent(folder, done, manifest, ref, raw_id, hashes)
        process, = (row['procid'] for row in manifest['processes'] if row['name'] == 'RadioactiveDecay')
        mark = library._validate_mark(parent, metadata, process, done['identity'])
        event = native_event(folder, db, done, parent, mark, groups)
        channels = {row['id']: row for row in channels}
        analysis, collections = trace_deposition(parent, event, channels, manifest)
        REQUIRE(all(endpoints[block, t]['endpoint_collections'] == collections
                    and endpoints[block, t]['native_input_group_sha256'] == event['input_event_sha256']
                    for t in trigger_ids), 'Rebuilt native collection cells disagree with the four saved endpoints')
        depositing, = (row for row in analysis['gamma_roots'] if row['deposited_energy_keV'] > 0.)
        REQUIRE(len(analysis['gamma_roots']) == 2 and len(depositing['matched_source_lines']) == 1
                and abs(depositing['birth_energy_keV']-line) < 0.02
                and close(depositing['birth_energy_keV'], analysis['deposited_energy_keV'])
                and analysis['unrooted_gamma_energy_keV'] == 0., 'Target full-line energy attribution differs')
        gamma_id = depositing['track_id']
        anchors = [row for row in analysis['interactions'] if row['photon_track_id'] == gamma_id]
        path = photon_path(folder, done, raw_id, gamma_id, anchors, hashes,
                           source_position_mm=metadata['source_position_mm'])
        direct_rows = {row['raw_row_index']: row for row in analysis['rows'] if row['track_id'] == gamma_id}
        REQUIRE(path['all_vertices_match_birth_order'] and set(direct_rows) ==
                {step['raw_row_index'] for step in path['steps'] if step['deposited_energy_keV'] > 0.}
                and close(fsum(row['energy_keV'] for row in direct_rows.values()), path['direct_scored_step_edep_keV']),
                'Scored root photon STEP rows and the positive remage energy ledger differ')
        for step in path['steps']:
            anchor_index, = step['matching_anchor_indices']
            step['birth_anchor_interaction_index'] = anchors[anchor_index]['interaction_index']
            if step['raw_row_index'] in direct_rows:
                row = direct_rows[step['raw_row_index']]
                REQUIRE(row['energy_keV'] == step['deposited_energy_keV'] and row['time_ns'] == step['pre_time_ns']
                        and row['pre_position_mm'] == step['pre_position_mm'] and
                        row['post_position_mm'] == step['post_position_mm'] and row['interaction_index'] is None,
                        'Photon chord position, time or direct deposition changed')
                row['matching_scored_birth_interaction_index'] = step['birth_anchor_interaction_index']
        identity = dict(source=SOURCE, raw_event_id=raw_id, campaign_initial_id=mark['campaign_initial_id'],
                        chunk_index=chunk_index, group_id=0, initial_primary_id=mark['initial_primary_id'],
                        global_decay_id=mark['global_decay_id'])
        histories.append(dict(line_center_keV=line, identity=identity, occurrences=occurrences,
                              source_position_global_mm=metadata['source_position_mm'], source_contract_id=metadata['source_contract_id'],
                              source_pdg=metadata['source_pdg'], transport_seed=metadata['radiation_seed'],
                              clock_seed=provenance['clock_seed'], clock_policy=manifest['clock_policy'],
                              original_parent_line_sha256=parent_hash, native_metadata_sha256=groups[0]['metadata_sha256'],
                              native_input_group_sha256=event['input_event_sha256'],
                              parent_material_energy_keV=parent['material_energy_keV'], depositing_gamma_track_id=gamma_id,
                              photon_path=path, **analysis))
    REQUIRE(sources == frozen_sources(), 'Study source changed while tracing the original rows')
    return dict(kind='gegi_cobalt_history_ancestry_v1', status='completed', input_sha256=hashes, source_sha256=sources,
                distinct_history_count=len(histories), occurrence_count=sum(len(h['occurrences']) for h in histories),
                scope=dict(new_transport_runs=0, new_drift_runs=0, new_adc_replays=0,
                           birth_anchor='Same nearest photon and exact charged-child birth position, decay-relative time and process.',
                           direct_gamma_deposits='Keep the photon ancestry and collection cell. Leave child-birth attribution unassigned.',
                           photon_birth_energy='Radioactive-decay track birth. The root-family Ge sum tests accounting against birth energy.',
                           collection_energy='Sum Ge input rows by native terminal electron and hole contacts in the same row.',
                           absence_of_ge_deposition='A sibling root with zero Ge deposition has no inferred escape or scatter path.'),
                histories=histories)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default=OUTPUT, type=Path)
    output = parser.parse_args().output.resolve()
    REQUIRE(output.is_relative_to(LOCAL) and not output.exists(), 'Use a new receipt path inside the existing private study')
    result = run()
    payload = store.encoded(result) + b'\n'
    with output.open('xb') as stream:
        stream.write(payload)
    print(f"{result['distinct_history_count']} distinct histories; {result['occurrence_count']} trigger occurrences; {store.sha(payload)}")


if __name__ == '__main__':
    main()
