"""Score saved continuous GeGI strip pairings against sealed photon ancestry."""

import argparse
from collections import Counter
from contextlib import closing
import gzip
import json
import math
from pathlib import Path
import sqlite3
import time
import zlib

import gegi_digital_pairs as digital
from gegi_event_store import encoded, sha
import gegi_parent_gamma_reference as parent
import gegi_source_exposure as association
from gegi_source_clock import CAMPAIGN, ROOT, bound_bytes, require
from gegi_source_library import _hash
from gegi_two_source_order_check import FULL_DEPOSIT_ABS_TOL_KEV


LOCAL = ROOT / '.local/gegi-continuous-pairing'
ACQUISITION = ROOT / '.local/gegi-dual-source/cs37k-co37k-250ms-readout/report.json'
ACQUISITION_SHA = '4da85bf8544bea4ccac1a08d4e9d7ff91ca1debd8f2ddc64a6ee9d1f382052f7'
EXPOSURE = association.LOCAL / 'exposure.json'
EXPOSURE_SHA = 'adbe09e801d3ee8cd395e1fe4e4ad7cf84b0e285314752692a769a71b64c4664'
ENERGY = association.LOCAL / 'event-energy.json'
ENERGY_SHA = '6cd120a22a26a206bc9f1f5ea29033bccb53aa13c59eaed20ab1017defd4a2e4'
ORDER_OUTCOMES = ('only_true_order', 'only_reverse_order', 'both_allowed', 'neither_allowed', 'truth_pair_excluded')


def read_inputs(hashes):
    acquisition, exposure, energy = (json.loads(bound_bytes(path, hashes, digest)) for path, digest in
                                    ((ACQUISITION, ACQUISITION_SHA), (EXPOSURE, EXPOSURE_SHA), (ENERGY, ENERGY_SHA)))
    require(energy['binding']['exposure_sha256'] == EXPOSURE_SHA
            and energy['binding']['input_sha256'] == exposure['input_sha256']
            and energy['baseline_parity']['known_component_adc_sha256'] == acquisition['receipt']['known_component_adc_sha256']
            and energy['baseline_parity']['trigger_identities_matched'] == len(exposure['triggers'])
            and all(acquisition['exposure'][key] == exposure['exposure'][key] for key in
                    ('clock_live_time_ns', 'qualified_adc_live_time_ns', 'excluded_intervals_ns')),
            'The measured ADC report and original association ledger refer to different exposures')
    return acquisition, exposure


def measured_candidates(acquisition, exposure):
    candidates = {}
    require(len(acquisition['triggers']) == acquisition['counts']['qualified_triggers'], 'Trigger count differs from the receipt')
    for index, (trigger, old) in enumerate(zip(acquisition['triggers'], exposure['triggers'], strict=True)):
        x, y, guards = (trigger[key] for key in ('x_collecting_strips', 'y_collecting_strips', 'guard_contact_ids'))
        require(all(trigger[key] == old[key] for key in ('trigger_time_ns', 'rise_end_ns', 'flags'))
                and trigger['single_pixel_energy_keV'] == old['slow_energy_keV']
                and sorted(x + y + guards) == old['step_contact_ids'], 'Continuous trigger identity differs from the frozen associations')
        card = trigger.get('two_strip_pairings')
        eligible = len(x) == len(y) == 2 and not guards and trigger['additional_multi_strip_energy_keV'] is not None
        require((card is not None) == eligible, 'Saved two-strip case differs from its measured eligibility')
        if not eligible:
            continue
        hits = {row['contact_id']: row['slow_energy_keV'] for row in card['collectors']}
        require(sorted(hits) == x + y and len(card['collectors']) == 4, 'Saved collector census changed')
        expected = list(digital.energy_pairings(x, y, hits))
        for pairing in expected:
            pairing['compton_orders'] = digital.compton_orders(pairing['sites']) if pairing['energy_compatible'] else []
        require(card['pairings'] == expected and card['compatible_pairing_count'] == sum(p['energy_compatible'] for p in expected),
                'Saved digital pairing or Compton order differs on the measured energies')
        candidates[index] = {'trigger_index': index, 'trigger_time_ns': trigger['trigger_time_ns'],
                             'rise_end_ns': trigger['rise_end_ns'], 'energy_keV': trigger['energy_keV'],
                             'two_strip_pairings': card, 'association': old['association']}
    return candidates


def matched_deposits(exposure):
    """Use the frozen one-to-one links and reproduce the merged members with its relation rule."""
    deposits = exposure['deposits']
    associated, used_merged = {}, []
    merged = [i for i, row in enumerate(deposits) if row['classification'] == 'merged']
    for index, trigger in enumerate(exposure['triggers']):
        if trigger['association'] == 'unique_matched':
            deposit = trigger['deposit_index']
            require(deposits[deposit]['trigger_index'] == index and deposits[deposit]['classification'] == 'unique_matched',
                    'The saved one-to-one association is inconsistent')
            associated[index] = [deposit]
        elif trigger['association'] == 'merged':
            stamp = trigger['trigger_time_ns']
            members = [i for i in merged if
                       deposits[i]['first_ge_deposit_ns'] - association.PRE_NS <= stamp <=
                       deposits[i]['first_ge_deposit_ns'] + association.SEARCH_END_NS + association.MATCH_NS
                       and association.related(deposits[i]['first_ge_deposit_ns'], deposits[i], trigger)]
            require(len(members) > 1, 'Could not identify saved merged group membership')
            associated[index] = members
            used_merged.extend(members)
    require(sorted(used_merged) == merged, 'Archived merged membership is missing or ambiguous')
    return associated


def native_metadata(db, row):
    record = db.execute('SELECT metadata, metadata_sha256 FROM events WHERE primary_id=? AND group_id=?',
                        (row['raw_event_id'], row['group_id'])).fetchone()
    if record is None:
        return None
    blob, digest = record
    raw = zlib.decompress(blob)
    require(digest == row['metadata_sha256'] == sha(raw), 'Native metadata digest differs from the frozen exposure')
    return json.loads(raw)


def extra_groups(raw, selected_group, root_id):
    tracks = {track['trackid']: track for track in raw['tracks']}
    steps = {step['raw_row_index']: step for step in raw['steps']}
    others = []
    for group in raw['pulse_groups']:
        if group['group_id'] == selected_group:
            continue
        rows = [steps[i] for i in group['row_indices']]
        same_root = [step for step in rows if root_id is not None and parent.ancestry(step['track_id'], tracks)[0] == root_id]
        others.append({'group_id': group['group_id'], 'ge_deposit_keV': math.fsum(step['energy_keV'] for step in rows),
                       'same_root_gamma_deposit_keV': math.fsum(step['energy_keV'] for step in same_root) if root_id is not None else None})
    return others


def containment(roots, total, other_groups):
    if len(roots) != 1:
        return 'multiple_depositing_photons' if roots else 'no_photon_ancestor'
    birth = roots[0]['birth_kinetic_energy_keV']
    rooted = roots[0]['group_germanium_descendant_deposition_keV']
    if birth is None or birth <= 0:
        return 'missing_photon_birth_energy'
    close = lambda value: math.isclose(value, birth, rel_tol=0, abs_tol=FULL_DEPOSIT_ABS_TOL_KEV)
    if close(rooted) and close(total) and not any(row['same_root_gamma_deposit_keV'] > FULL_DEPOSIT_ABS_TOL_KEV
                                                 for row in other_groups):
        return 'full_energy_at_photon_birth'
    if rooted < birth and not close(rooted):
        return 'incomplete_energy_at_photon_birth'
    return 'extra_or_inconsistent_energy'


def original_reference(row, raw, raw_digest, native, processes):
    if raw is None or native is None:
        return {'status': 'missing_transport_or_native_metadata'}
    group, = [group for group in raw['pulse_groups'] if group['group_id'] == row['group_id']]
    by_row = {step['raw_row_index']: step for step in raw['steps']}
    steps = [by_row[i] for i in group['row_indices']]
    native_group = native['input_group']
    require(raw['event_id'] == row['raw_event_id'] == native['event_id']
            and raw['source_id'] == native['source_id'] and native['source_group'] == row['source']
            and native['event_id'] + native['campaign_initial_offset'] == row['campaign_initial_id']
            and native['group_id'] == row['group_id'] and native['status'] == row['native_status']
            and group == native_group['pulse_group'] and steps == native_group['steps'] == native['input_steps']
            and native_group['parent_event_metadata'] == {k: v for k, v in raw.items() if k not in ('steps', 'pulse_groups')}
            and native['input_event_sha256'] == sha(encoded(native_group))
            and math.isclose(native['truth_edep_keV'], row['truth_edep_keV'], rel_tol=0, abs_tol=FULL_DEPOSIT_ABS_TOL_KEV),
            'Sealed transport rows and native group endpoints refer to different inputs')
    scored = parent.evaluate(native, processes, {'spatial_diagnostics': [], 'candidates': []})
    ref = scored['references']['ge5keV']
    roots = scored['root_gammas']
    others = extra_groups(raw, row['group_id'], roots[0]['trackid'] if len(roots) == 1 else None)
    interactions = {tuple(interaction['interaction_key']): interaction for interaction in scored['parent_interactions']}
    truth_sites = []
    for cell, key in zip(ref['reference_cells_in_birth_order'] or [], ref['reference_interaction_keys_in_birth_order'] or [], strict=True):
        site = interactions[tuple(key)]
        rows = [by_row[i] for i in site['raw_row_indices']]
        total = math.fsum(step['energy_keV'] for step in rows)
        centroid = [math.fsum(step['position_mm'][axis] * step['energy_keV'] for step in rows) / total for axis in range(3)]
        truth_sites.append({'cell': cell, 'birth_process': site['birth_process'], 'birth_time_ns': site['birth_time_ns'],
                            'birth_position_mm': site['birth_position_mm'], 'deposit_centroid_mm': centroid,
                            'deposited_energy_keV': total, 'raw_row_indices': site['raw_row_indices']})
    return {'status': ref['status'], 'unknown_reason': ref['unknown_reason'], 'transport_event_sha256': raw_digest,
            'native_metadata_sha256': row['metadata_sha256'], 'native_input_group_sha256': native['input_event_sha256'],
            'significant_interaction_count': ref['significant_interaction_count'], 'unassigned_energy_keV': ref['unassigned_energy_keV'],
            'groups_in_same_original_decay': len(raw['pulse_groups']), 'other_groups': others,
            'emitted_decay_photons': raw['decay_photon_count'], 'depositing_root_gammas': roots,
            'containment': containment(roots, scored['input_deposited_energy_keV'], others),
            'sites_in_birth_order': truth_sites or None}


def pairing_score(pairings, reference):
    sites = reference.get('sites_in_birth_order')
    if sites is None:
        return None
    truth = [site['cell'] for site in sites]
    matching = []
    for row in pairings:
        cells = [[site['x_contact_id'], site['y_contact_id']] for site in row['sites']]
        if sorted(cells) == sorted(truth):
            matching.append((row, [cells.index(cell) for cell in truth]))
    require(len(matching) <= 1, 'More than one X/Y permutation has the same distinct truth cells')
    order_outcome = None
    if not matching:
        comparison = {'pair_outcome': 'truth_cells_absent_from_both_permutations'}
    else:
        (row, true_order), = matching
        compatible = row['energy_compatible']
        allowed = [order['site_index_order'] for order in row['compton_orders'] if order['kinematically_allowed']]
        measured = [row['sites'][i]['energy_keV'] for i in true_order]
        comparison = {'pair_outcome': 'truth_pair_energy_compatible' if compatible else 'truth_pair_energy_incompatible',
                      'truth_pairing_index': row['index'], 'truth_site_index_order': true_order,
                      'allowed_orders_for_truth_pair': allowed,
                      'measured_site_energies_in_birth_order_keV': measured,
                      'energy_minus_deposit_in_birth_order_keV': [e - site['deposited_energy_keV'] for e, site in zip(measured, sites)]}
        if compatible:
            order_outcome = ('both_allowed' if len(allowed) == 2 else 'neither_allowed' if not allowed else
                             'only_true_order' if allowed[0] == true_order else 'only_reverse_order')
    if reference['containment'] == 'full_energy_at_photon_birth':
        comparison['full_energy_order_outcome'] = order_outcome or 'truth_pair_excluded'
    return comparison


def source_references(source, deposits, frozen, hashes, *, source_folder=None):
    folder = CAMPAIGN / 'chunks' / source / 'b000000' if source_folder is None else Path(source_folder).resolve()

    def data(ref):
        path = folder / ref
        return bound_bytes(path, hashes, frozen[path.relative_to(ROOT).as_posix()])

    done = json.loads(data('DONE.json'))
    manifest = json.loads(data('transport/stream/manifest.json'))
    columns = manifest['raw_tables']['tracks']['columns']
    transform = manifest['coordinate_transform']
    require(columns['ekin']['units'] == 'MeV' and columns['time']['units'] == 'ns'
            and all(columns[k]['units'] == 'm' for k in ('xloc', 'yloc', 'zloc'))
            and transform['rotation_local_to_global'] == [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
            and transform['translation_global_mm'] == [0, 0, 0], 'Photon birth energy or coordinate convention differs')
    processes = {row['procid']: row['name'] for row in manifest['processes']}
    archive = 'transport/stream/events.jsonl'
    compressed = (folder / (archive + '.gz')).is_file()
    stream = gzip.decompress(data(archive + '.gz')) if compressed else data(archive)
    sealed = done['archives'][archive]['original_sha256'] if compressed else done['artifacts'][archive]['sha256']
    require(sha(stream) == manifest['events_sha256'] == sealed,
            'Uncompressed transport bytes differ from the original stream')
    wanted = {row['raw_event_id'] for row in deposits}
    transport = {}
    for line in stream.splitlines():
        raw = json.loads(line)
        if raw['event_id'] in wanted:
            require(raw['event_id'] not in transport, 'Duplicate original event ID in the sealed stream')
            transport[raw['event_id']] = raw, sha(line)
    database = folder / 'events.sqlite'
    ref = database.relative_to(ROOT).as_posix()
    hashes[ref] = _hash(database)
    require(hashes[ref] == frozen[ref] == done['artifacts']['events.sqlite']['sha256'], 'Native store differs from the original source')
    records = {}
    with closing(sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        for row in deposits:
            key = row['raw_event_id'], row['group_id']
            if key not in records:
                raw, digest = transport.get(row['raw_event_id'], (None, None))
                records[key] = original_reference(row, raw, digest, native_metadata(db, row), processes)
    return records


def summarize(candidates):
    energy_counts, order_counts, order_per_pair = Counter(), Counter(), Counter()
    for candidate in candidates:
        card = candidate['two_strip_pairings']
        energy_counts[card['compatible_pairing_count']] += 1
        allowed = [sum(order['kinematically_allowed'] for order in row['compton_orders'])
                   for row in card['pairings'] if row['energy_compatible']]
        order_counts[sum(allowed)] += 1
        order_per_pair.update(allowed)

    truth = [row['reference'] for row in candidates if row['reference'] is not None]
    comparisons = [row['comparison'] for row in candidates if row['comparison'] is not None]
    full = Counter(row['full_energy_order_outcome'] for row in comparisons if 'full_energy_order_outcome' in row)
    return {'digital': {'two_by_two_triggers': len(candidates), 'permutations_evaluated': sum(len(row['two_strip_pairings']['pairings']) for row in candidates),
                        'triggers_by_energy_compatible_pairing_count': dict(energy_counts),
                        'triggers_by_total_allowed_order_count': dict(order_counts),
                        'compatible_pairings_by_allowed_order_count': dict(order_per_pair)},
            'truth': {'association_counts': dict(Counter(row['association'] for row in candidates)),
                      'unique_association_sources': dict(Counter(row['deposit_groups'][0]['source'] for row in candidates if row['association'] == 'unique_matched')),
                      'merged_triggers_with_mixed_sources': sum(row['association'] == 'merged' and len({g['source'] for g in row['deposit_groups']}) > 1 for row in candidates),
                      'unique_matches_with_close_arrivals': sum(row['association'] == 'unique_matched' and row['deposit_groups'][0]['arrival_class'] == 'close' for row in candidates),
                      'unique_matches_with_other_original_groups': sum(bool(row.get('other_groups')) for row in truth),
                      'unique_original_groups': len({(row['deposit_groups'][0]['source'], row['deposit_groups'][0]['raw_event_id'],
                                                       row['deposit_groups'][0]['group_id']) for row in candidates if row['association'] == 'unique_matched'}),
                      'reference_status_counts': dict(Counter(row.get('unknown_reason') or row['status'] for row in truth)),
                      'deposition_scope_counts': dict(Counter(row.get('containment', 'unknown') for row in truth)),
                      'exact_two_interaction_cell_references': len(comparisons),
                      'pair_outcomes': dict(Counter(row['pair_outcome'] for row in comparisons)),
                      'full_energy_reference_count': sum(full.values()), 'full_energy_truth_in_allowed': full['only_true_order'] + full['both_allowed'],
                      'full_energy_order_outcomes': {key: full[key] for key in ORDER_OUTCOMES}}}


def study():
    started = time.perf_counter()
    names = (Path(__file__).name, 'gegi_digital_pairs.py', 'gegi_imaging.py', 'gegi_parent_gamma_reference.py',
             'gegi_source_exposure.py', 'gegi_source_clock.py', 'gegi_rejection_diagnostic.py', 'gegi_two_source_order_check.py',
             'gegi_source_library.py', 'gegi_event_store.py')

    def source_hashes():
        return {f'tools/{name}': _hash(ROOT/'tools'/name) for name in names}

    sources = source_hashes()
    hashes = {}
    acquisition, exposure = read_inputs(hashes)
    candidates = measured_candidates(acquisition, exposure)
    associations = matched_deposits(exposure)
    deposits = exposure['deposits']
    selected = sorted({i for index in candidates for i in associations.get(index, [])})
    require(len(candidates) == 76, 'Expected the original 76 measured two-by-two triggers')
    complete = CAMPAIGN/'COMPLETE.json'
    completion = json.loads(bound_bytes(complete, hashes, exposure['input_sha256'][complete.relative_to(ROOT).as_posix()]))
    saved_sources = {source['original']['source_group']: source['original'] for source in acquisition['sources']}
    references = {}
    for source, metadata in saved_sources.items():
        require(completion['chunks'][str(metadata['chunk_index'])] == metadata['chunk_sha256'], 'Acquisition names a different source seal')
        chosen = [deposits[i] for i in selected if deposits[i]['source'] == source]
        references[source] = source_references(source, chosen, exposure['input_sha256'], hashes)

    identity_keys = ('source', 'occurrence_id', 'campaign_initial_id', 'raw_event_id', 'group_id', 'arrival_class',
                     'native_status', 'truth_edep_keV', 'first_ge_deposit_ns', 'last_ge_deposit_ns')
    for index, candidate in candidates.items():
        groups = [deposits[i] for i in associations.get(index, [])]
        candidate['deposit_groups'] = [{key: row[key] for key in identity_keys} for row in groups]
        reference = None
        if candidate['association'] == 'unique_matched':
            group, = groups
            reference = references[group['source']][group['raw_event_id'], group['group_id']]
        candidate['reference'] = reference
        candidate['comparison'] = pairing_score(candidate['two_strip_pairings']['pairings'], reference) if reference else None

    require(sources == source_hashes(), 'Scoring sources changed during the study')
    rows = list(candidates.values())
    return {'kind': 'gegi_continuous_two_strip_pairing_study_v1', 'status': 'completed',
            'design': {'scoring': 'Recompute both strip permutations and all energy-admissible orders from measured ADC energies before reading truth.',
                       'association': 'Use the sealed original unique trigger links and its relation rule for the original merged members. Merged triggers get no individual photon reference.',
                       'reference': 'At least 5 keV per significant parent interaction, exactly two in distinct exact native endpoint cells, ordered by original child birth time. The oldest depositing gamma ancestor must be unique.',
                       'order_scope': 'Score only one-photon groups with all birth kinetic energy deposited to 1e-7 keV and an exact two-cell reference. Birth energy precedes any upstream material losses. No Compton angle accuracy or spatial estimate is inferred.',
                       'reference_coordinates': 'Original track births and energy-weighted Ge deposit centroids in detector mm. True coordinates are used only after candidate enumeration.',
                       'new_transport_calls': 0, 'new_drift_calls': 0, 'new_adc_replays': 0},
            'adc_sha256': acquisition['receipt']['known_component_adc_sha256'],
            'qualified_trigger_denominator': acquisition['counts']['qualified_triggers'],
            'input_sha256': hashes, 'source_sha256': sources, 'summary': summarize(rows), 'candidates': rows,
            'wall_s': time.perf_counter() - started}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    output = parser.parse_args().output.resolve()
    require(output.is_relative_to(LOCAL) and not output.exists(), 'Use a new report path under .local/gegi-continuous-pairing')
    result = study()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as target:
        target.write(encoded(result) + b'\n')
    print(json.dumps(result['summary'], indent=2))


if __name__ == '__main__':
    main()
