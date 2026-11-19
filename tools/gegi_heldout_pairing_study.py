"""Associate a saved two-source acquisition with its exact archived inputs, without ADC replay."""

import argparse
from bisect import bisect_left, bisect_right
from collections import Counter
from contextlib import closing
import json
import math
from pathlib import Path
from time import perf_counter
import zlib

import gegi_continuous_pairing_study as truth
import gegi_digital_pairs as pairs
import gegi_digital_readout as digital
import gegi_dual_source as dual
from gegi_event_store import encoded, sha
import gegi_source_exposure as association
import gegi_source_library as library


ROOT = truth.ROOT
LOCAL = ROOT / '.local/gegi-continuous-pairing'
REQUIRE = truth.require
IDS = ('source', 'occurrence_id', 'group_id')


def occurrence(row):
    return tuple(row[key] for key in IDS)


def measured_candidates(report):
    triggers = report['triggers']
    counts = report['counts']
    times = [row['trigger_time_ns'] for row in triggers]
    REQUIRE(len(times) == counts['qualified_triggers'] and times == sorted(set(times)),
            'Saved report trigger times are missing, duplicated or unordered')
    result = {}
    for i, row in enumerate(triggers):
        xs, ys = row['x_collecting_strips'], row['y_collecting_strips']
        card = row.get('two_strip_pairings')
        eligible = len(xs) == len(ys) == 2 and not row['guard_contact_ids'] and row['additional_multi_strip_energy_keV'] is not None
        REQUIRE((card is not None) == eligible, 'Measured two-strip selection changed')
        if not eligible:
            continue
        slow = {channel['contact_id']: channel['slow_energy_keV'] for channel in card['collectors']}
        REQUIRE(len(slow) == len(card['collectors']) == 4 and sorted(slow) == xs+ys, 'Measured collector identities changed')
        expected = list(pairs.energy_pairings(xs, ys, slow))
        for saved, derived in zip(card['pairings'], expected, strict=True):
            derived['compton_orders'] = pairs.compton_orders(derived['sites']) if derived['energy_compatible'] else []
            REQUIRE(all(saved[key] == value for key, value in derived.items()), 'Measured energy pairing or order changed')
        REQUIRE(card['compatible_pairing_count'] == sum(p['energy_compatible'] for p in expected), 'Measured pairing census changed')
        result[i] = {key: row[key] for key in ('trigger_time_ns', 'rise_end_ns', 'energy_keV', 'two_strip_pairings')}
        result[i]['trigger_index'] = i
    return result


def group_status(saved, rows):
    """Validate the sealed endpoint metadata and avoid decoding any waveform arrays."""
    statuses = {}
    with closing(library._database(saved.database)) as conn:
        for row in rows:
            key = row['raw_event_id'], row['group_id']
            if key in statuses:
                continue
            raw, digest = conn.execute('SELECT metadata, metadata_sha256 FROM events WHERE primary_id=? AND group_id=?', key).fetchone()
            content = zlib.decompress(raw)
            event = json.loads(content)
            group = library._group(saved, row)
            REQUIRE(sha(content) == digest and (event['event_id'], event['group_id']) == key
                    and event['source_group'] == saved.metadata['source_group']
                    and event['group_origin_time_ns'] == group['first_deposit_since_parent_ns']
                    and event['pulse_group']['row_indices'] == group['raw_row_indices']
                    and math.isclose(event['truth_edep_keV'], row['truth_edep_keV'], rel_tol=0, abs_tol=1e-7),
                    'The selected source database does not bind the scheduled raw group')
            statuses[key] = digital.terminal_contacts_complete(event), event['status'], digest
    return statuses


def scheduled_inputs(report, sources, hashes):
    packs = tuple(library.load_source_library(path) for path in sources)
    exposure, design = report['exposure'], report['design']
    schedule = library.schedule_sources(*packs, activities_bq=[source['activity_bq'] for source in report['sources']],
                                        duration_ns=exposure['clock_live_time_ns'], seed=design['clock_seed'], include_prehistory=True)
    rows, unavailable, inputs, by_key = [], [], {}, {}
    for pack, key, card in zip(packs, schedule['source_keys'], report['sources'], strict=True):
        frozen = card['original']
        metadata = pack.metadata
        REQUIRE(key == card['key'] and all(metadata[name] == frozen[name] for name in
                ('chunk_sha256', 'database_sha256', 'transport_sha256', 'source_group', 'source_contract_id', 'radiation_seed')),
                'Supply the report’s exact source chunks in acquisition order')
        parent = schedule['sources'][key]
        REQUIRE(parent['counts'] == card['counts'] and parent['clock']['seed_uint64'] == card['scheduled_parent_seed']
                and parent['clock'].get('clock_layers', 1) == card['clock_layers'], 'Scheduled clock marks differ from the acquisition')
        folder, _, done, _, stream_ref, _, _ = library._source_inputs(pack.directory)
        stamps = {'DONE.json': metadata['chunk_sha256']}
        for ref in (stream_ref, library._MANIFEST, 'events.sqlite'):
            stamps[ref] = done['artifacts'][ref]['sha256']
        for ref, digest in stamps.items():
            inputs[(folder/ref).relative_to(ROOT).as_posix()] = digest
        by_key[key] = pack
        statuses = group_status(pack, parent['eligible_groups'])
        for entry in parent['eligible_groups']:
            complete, status, digest = statuses[entry['raw_event_id'], entry['group_id']]
            row = dict(entry, native_available=complete, native_status=status, metadata_sha256=digest, isolated_triggers=[])
            rows.append(row)
            if not complete:
                unavailable.append(dual._unknown_card(row, row['truth_edep_keV'], status, digest))
        for entry in parent['censored_groups']:
            rows.append(dict(entry, native_available=False, native_status='deposits_extend_past_exposure', metadata_sha256=None,
                             isolated_triggers=[]))
    mask_inputs = unavailable + dual._partial_deposits(schedule)
    frozen_unknown = report['unknown_groups']
    REQUIRE(len(mask_inputs) == len(frozen_unknown) and {occurrence(row): row for row in mask_inputs} ==
            {occurrence(row): row for row in frozen_unknown}, 'Native completeness or the original excluded groups changed')
    mask = dual._history_mask(mask_inputs, exposure['clock_live_time_ns'])
    REQUIRE(mask == exposure['excluded_intervals_ns'], 'Saved acquisition and rederived history exclusions disagree')
    rows.sort(key=lambda row: row['first_ge_deposit_ns'])
    REQUIRE(len({occurrence(row) for row in rows}) == len(rows), 'Duplicate scheduled group identity')
    previous = -math.inf
    for i, row in enumerate(rows):
        onset, last = row['first_ge_deposit_ns'], row['last_ge_deposit_ns']
        following = rows[i+1]['first_ge_deposit_ns'] if i+1 < len(rows) else math.inf
        row['arrival_class'] = 'close' if min(onset-previous, following-last) <= association.NEAR_NS else 'isolated'
        row['classification'] = ('right_censored' if row['native_status'] == 'deposits_extend_past_exposure' else
                                 'native_unavailable' if not row['native_available'] else
                                 'history_unqualified' if association.in_regions(onset, mask) else 'awaiting_match')
        previous = max(previous, last)
    counts = report['counts']
    REQUIRE(len(rows) == counts['deposit_groups'] and len(unavailable) == counts['native_unavailable_groups']
            and sum(r['classification'] == 'history_unqualified' for r in rows) == counts['prehistory_unqualified_groups']
            and len(schedule['censored_groups']) == counts['right_censored_deposit_groups']
            and sum(source['counts']['parents'] for source in report['sources']) == counts['initial_parents_in_live_time'],
            'The parent or deposit group denominator changed')
    hashes.update(inputs)
    return rows, by_key, mask, inputs


def link_groups(rows, measured, mask):
    triggers = [{'trigger_time_ns': row['trigger_time_ns'], 'rise_end_ns': row['rise_end_ns'], 'association': 'unmatched',
                 'step_contact_ids': sorted(row['x_collecting_strips']+row['y_collecting_strips']+row['guard_contact_ids'])} for row in measured]
    association.assign(rows, triggers, mask)
    onsets = [d['first_ge_deposit_ns'] for d in rows]
    for i, trigger in enumerate(triggers):
        stamp = trigger['trigger_time_ns']
        lo = bisect_left(onsets, stamp-association.SEARCH_END_NS-association.MATCH_NS)
        hi = bisect_right(onsets, stamp+association.PRE_NS)
        plausible = [j for j in range(lo, hi) if association.related(onsets[j], rows[j], trigger)]
        state = trigger['association']
        if state == 'unique_matched':
            j = trigger['deposit_index']
            REQUIRE(rows[j]['trigger_index'] == i and j in plausible, 'A unique timing link is inconsistent')
            trigger['group_indices'] = [j]
            if rows[j]['arrival_class'] == 'close':
                scope = 'near_another_scheduled_ge_group'
            elif not association.overlaps_activity(onsets[j], trigger):
                scope = 'no_rise_onset_overlap_within_60ns'
            elif len(plausible) != 1:
                scope = 'multiple_groups_in_timing_window'
            else:
                scope = 'isolated_rise_time_match'
        else:
            trigger['group_indices'] = plausible
            scope = state
        trigger['truth_link_scope'] = scope
    return triggers


def attach_truth(candidates, rows, links, packs, frozen, hashes):
    grade = 'isolated_rise_time_match'
    chosen = [rows[links[i]['group_indices'][0]] for i in candidates if links[i]['truth_link_scope'] == grade]
    references = {}
    for key, pack in packs.items():
        if subset := [dict(row, source=pack.metadata['source_group']) for row in chosen if row['source'] == key]:
            references[key] = truth.source_references(pack.metadata['source_group'], subset, frozen, hashes, source_folder=pack.directory)
    for index, candidate in candidates.items():
        link = links[index]
        groups = [rows[j] for j in link['group_indices']]
        candidate['association'] = link['association']
        candidate['truth_link_scope'] = link['truth_link_scope']
        candidate['deposit_groups'] = [{key: row[key] for key in (*IDS, 'raw_event_id', 'campaign_initial_id', 'native_status',
                                        'first_ge_deposit_ns', 'last_ge_deposit_ns', 'truth_edep_keV', 'arrival_class')} for row in groups]
        reference = None
        if link['truth_link_scope'] == grade:
            row, = groups
            reference = references[row['source']][row['raw_event_id'], row['group_id']]
        candidate['reference'] = reference
        candidate['comparison'] = truth.pairing_score(candidate['two_strip_pairings']['pairings'], reference) if reference else None


def run(report_path, sources, expected_sha256=None):
    start = perf_counter()
    hashes = {}
    names = (Path(__file__).name, 'gegi_continuous_pairing_study.py', 'gegi_parent_gamma_reference.py',
             'gegi_source_library.py', 'gegi_source_exposure.py', 'gegi_dual_source.py', 'gegi_digital_pairs.py',
             'gegi_digital_readout.py', 'gegi_imaging.py', 'gegi_event_store.py')

    def source_hashes():
        return {f'tools/{name}': library._hash(ROOT/'tools'/name) for name in names}

    implementation = source_hashes()
    report = json.loads(truth.bound_bytes(report_path, hashes, expected_sha256))
    receipt = report['receipt']
    observed = dict(counts=report['counts'], spectra=report['spectra'], triggers=report['triggers'],
                    mask=report['exposure']['excluded_intervals_ns'])
    REQUIRE(report['kind'] == dual.KIND and report['status'] == 'completed' and receipt['known_component_adc_sha256']
            and sha(encoded(observed)) == receipt['observed_result_sha256']
            and (receipt['digital_profile_sha256'], receipt['digital_timing_sha256']) == (digital.PROFILE_SHA256, digital.TIMING_SHA256),
            'Select an intact measured GeGI acquisition with qualified ADC time')
    candidates = measured_candidates(report)
    rows, packs, mask, frozen = scheduled_inputs(report, sources, hashes)
    links = link_groups(rows, report['triggers'], mask)
    attach_truth(candidates, rows, links, packs, frozen, hashes)
    REQUIRE(implementation == source_hashes(), 'Inputs or scoring sources changed during generation')
    result = list(candidates.values())
    return {'kind': 'gegi_continuous_two_strip_pairing_study_v1', 'status': 'completed',
            'design': {'selection': 'Freeze both measured strip permutations and their energy-only orders before accessing transport.',
                       'association': 'Apply the established timing graph with no isolated waveform or strip ranking evidence. A unique graph link is distinct from a scored reference.',
                       'scoring': 'Require one unique timing link, one plausible Ge group, its first deposit within the rise envelope with 60 ns tolerance, and more than 6 µs from neighboring scheduled deposit intervals.',
                       'reference': 'The established at-least-5-keV exact two-interaction endpoint reference. Require full birth energy for order scoring; partial deposits may still score cell pairing.',
                       'zero_new_transport_drift_adc_calls': True},
            'adc_sha256': receipt['known_component_adc_sha256'], 'qualified_trigger_denominator': len(report['triggers']),
            'acquisition_counts': report['counts'], 'qualified_adc_time_ns': report['exposure']['qualified_adc_live_time_ns'],
            'input_sha256': hashes, 'source_sha256': implementation, 'summary': truth.summarize(result), 'candidates': result,
            'association_census': {'all_triggers': dict(Counter(row['association'] for row in links)),
                                   'all_scheduled_groups': dict(Counter(row['classification'] for row in rows)),
                                   'candidate_truth_link_scope': dict(Counter(row['truth_link_scope'] for row in result))},
            'trigger_ledger': links,
            'deposit_ledger': [{k: v for k, v in row.items() if k != 'isolated_triggers'} for row in rows],
            'source_chunks': [pack.metadata for pack in packs.values()], 'wall_s': perf_counter()-start}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    parser.add_argument('--source-a', type=Path, required=True)
    parser.add_argument('--source-b', type=Path, required=True)
    parser.add_argument('--report-sha256')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report, a, b, output = [path.resolve() for path in (args.report, args.source_a, args.source_b, args.output)]
    REQUIRE(all(path.is_relative_to(ROOT) for path in (report, a, b)) and output.is_relative_to(LOCAL) and not output.exists(),
            'Use the original project inputs and a new study path')
    result = run(report, (a, b), args.report_sha256)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as target:
        target.write(encoded(result) + b'\n')
    print(json.dumps({key: result[key] for key in ('qualified_trigger_denominator', 'summary', 'association_census', 'wall_s')}, indent=2))


if __name__ == '__main__':
    main()
