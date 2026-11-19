"""Reduce sealed simultaneous Cs-137/Co-60 acquisitions without replaying ADC."""

import argparse
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import tempfile
from time import sleep

import numpy as np

from gegi_continuous_plane import LINE_ENERGIES_KEV
from gegi_dual_source import NATIVE_DRIFT_CAP_NS
import gegi_pool_measured_planes as pool


ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN = ROOT / '.local/gegi-dual-source/rss5-simultaneous-large'
BLOCKS = tuple(f'b{i:06d}' for i in range(5, 30))
SOURCE_KEYS = ('cs137-left', 'co60-right')
LINES = {f'{energy:g}_keV': (energy, source) for energy, source in
         zip(LINE_ENERGIES_KEV, (SOURCE_KEYS[0], SOURCE_KEYS[1], SOURCE_KEYS[1]), strict=True)}
KIND = 'gegi_commercial_simultaneous_results_v1'
ARTIFACTS = {'report.json': 'report_sha256', 'plane.json.gz': 'plane_sha256',
             'two-strip-adc.npz': 'adc_windows_sha256'}
REQUIRE = pool.require


def energy_layer(energy):
    return next((label for label, (center, _) in LINES.items()
                 if energy is not None and abs(energy-center) <= max(5., .02*center)), 'other_energy')


def measured_block(folder, configuration_sha):
    receipt_bytes = (folder/'receipt.json').read_bytes()
    receipt = json.loads(receipt_bytes)
    provenance, plane = pool.block(folder)
    REQUIRE(receipt['kind'] == 'gegi_commercial_dual_shard_v1' and receipt['block'] == folder.name
            and receipt['config_sha256'] == configuration_sha
            and receipt['artifacts'] == {file: provenance[key] for file, key in ARTIFACTS.items()},
            f'Acquisition seal differs for {folder.name}')
    report_bytes = (folder/'report.json').read_bytes()
    REQUIRE(pool.digest(report_bytes) == provenance['report_sha256'], 'Report changed during reduction')
    report = json.loads(report_bytes)
    triggers = report['triggers']
    by_source = {source['key']: source for source in report['sources']}
    REQUIRE(tuple(by_source) == SOURCE_KEYS
            and receipt['input_seals'] == {key: src['original']['chunk_sha256'] for key, src in by_source.items()},
            f'Source libraries differ for {folder.name}')
    seconds = report['exposure']['clock_live_time_ns'] / 1e9
    sources = {}
    for key, src in by_source.items():
        counts, original = src['counts'], src['original']
        REQUIRE(counts['parents'] == counts['marked_zero_parents'] + counts['marked_nonzero_parents'],
                'Sampled source parent counts do not close')
        sources[key] = dict(
            activity_bq=src['activity_bq'], position_mm=original['source_position_mm'],
            expected_live_parents=src['activity_bq']*seconds,
            sampled_live_parents=counts['parents'],
            sampled_live_zero_marks=counts['marked_zero_parents'],
            sampled_live_nonzero_marks=counts['marked_nonzero_parents'],
            in_exposure_ge_group_onsets=counts['group_onsets_in_live_time'],
            archived_initial_histories=original['original']['initial_primaries'],
            archived_nonzero_histories=original['original']['nonzero_primaries'],
        )
    REQUIRE(sum(s['sampled_live_parents'] for s in sources.values()) == report['counts']['initial_parents_in_live_time']
            and sum(s['in_exposure_ge_group_onsets'] for s in sources.values()) == report['counts']['deposit_groups'],
            'Pooled source counts do not close')
    measured = [(i, trigger) for i, trigger in enumerate(triggers, 1) if trigger.get('two_strip_pairings') is not None]
    REQUIRE(len(measured) == len(plane['triggers']) == plane['selection']['two_strip_triggers']
            and all(candidate['trigger_index'] == i and candidate['two_strip_ordinal'] == ordinal
                    and trigger['trigger_time_ns'] == candidate['trigger_time_ns']
                    and trigger['energy_keV'] == candidate['energy_keV']
                    for ordinal, ((i, trigger), candidate) in enumerate(zip(measured, plane['triggers'], strict=True), 1)),
            'Original trigger identities differ')
    index = {row['trigger_time_ns']: row for row in plane['triggers']}
    energies = [trigger['energy_keV'] for trigger in triggers if trigger['energy_keV'] is not None]
    windows = Counter(energy_layer(energy) for energy in energies)
    two_strip_windows = Counter(energy_layer(trigger['energy_keV']) for trigger in index.values())
    REQUIRE(len(triggers) == report['counts']['qualified_triggers']
            and len(energies) == report['counts']['qualified_energies']
            and all(plane['layers'][label]['triggers'] == two_strip_windows[label]
                    for label in plane['layers'] if label != 'all'),
            'Measured line and two-strip counts do not close')
    for spectrum in report['spectra'].values():
        REQUIRE(sum(spectrum['counts']) + spectrum['underflow'] + spectrum['overflow'] == spectrum['entries'],
                'Recorded energy histogram does not close')
    REQUIRE(report['spectra']['combined']['entries'] == len(energies), 'Combined spectrum count differs')
    details = dict(provenance=provenance, receipt_sha256=pool.digest(receipt_bytes),
                   counts=report['counts'], spectrum_entries=len(energies),
                   measured_energy_window_counts={label: windows[label] for label in (*LINES, 'other_energy')},
                   sources=sources, imaging={label: {key: layer[key] for key in (*pool.LAYER_COUNTS, *pool.LAYER_MASS)}
                                            for label, layer in plane['layers'].items()})
    return provenance, plane, details, report['spectra']


def add_spectra(shards):
    spectra = {}
    for label, first in shards[0].items():
        peers = [spectra[label] for spectra in shards]
        sums = {key: sum(peer[key] for peer in peers) for key in ('entries', 'underflow', 'overflow', 'exact_zero')}
        REQUIRE(all(peer['bin_edges_keV'] == first['bin_edges_keV']
                    and peer['lower_inclusive_upper_exclusive'] == first['lower_inclusive_upper_exclusive']
                    for peer in peers), 'Acquisition histogram bins differ')
        spectra[label] = {**first, **sums, 'counts': np.sum([peer['counts'] for peer in peers], axis=0).tolist()}
    return spectra


def measured_results(configuration_sha, shards):
    done = [name for name in BLOCKS if name in shards]
    REQUIRE(done, 'No completed acquisitions have a shard receipt yet')
    provenance, planes, blocks, spectra = zip(*(shards[name] for name in done), strict=True)
    pool.compatible(list(zip(provenance, planes, strict=True)))
    pooled = pool.add_layers(planes, include_map=True)
    sources = {}
    for source in SOURCE_KEYS:
        first = blocks[0]['sources'][source]
        sources[source] = {key: (first[key] if key in ('activity_bq', 'position_mm') else
                                 sum(block['sources'][source][key] for block in blocks)) for key in first}
    for label, (energy, source) in LINES.items():
        layer = pooled[label]
        known = sources[source]['position_mm']
        REQUIRE(known[2] == planes[0]['grid']['assumed_z_mm'], 'Expected source is outside the assumed plane')
        width = max(5., .02*energy)
        layer['held_out_position_comparison'] = dict(
            source=source, source_position_mm=known, measured_window_keV=[energy-width, energy+width],
            primary_peak_distance_mm=math.dist(layer['peaks'][0]['position_mm'], known) if layer['peaks'] else None,
        )
    if len(planes) > 1:
        midpoint = len(planes)//2
        left, right = [pool.add_layers(part, include_map=False) for part in (planes[:midpoint], planes[midpoint:])]
        split = {'blocks': [done[:midpoint], done[midpoint:]], 'layers': {}}
        for label in pooled:
            peaks = [i[label]['peaks'][0] if i[label]['peaks'] else None for i in (left, right)]
            split['layers'][label] = {'primary_peaks': peaks,
                                      'separation_mm': math.dist(*(p['position_mm'] for p in peaks))
                                      if all(peaks) else None}
    else:
        split = None
    counts = {key: sum(block['counts'][key] for block in blocks) for key in blocks[0]['counts']}
    exposure = {key: math.fsum(plane['selection'][key] for plane in planes) for key in pool.LIVE_KEYS}
    exposure['masked_live_time_ns'] = exposure['clock_live_time_ns'] - exposure['qualified_adc_live_time_ns']
    exposure['qualified_trigger_rate_per_s'] = counts['qualified_triggers']*1e9/exposure['qualified_adc_live_time_ns']
    exposure['qualified_energy_rate_per_s'] = counts['qualified_energies']*1e9/exposure['qualified_adc_live_time_ns']
    windows = {label: sum(block['measured_energy_window_counts'][label] for block in blocks)
               for label in (*LINES, 'other_energy')}
    REQUIRE(sum(windows.values()) == counts['qualified_energies'], 'Pooled energy windows do not partition the spectrum')
    return dict(kind=KIND, status='completed' if tuple(done) == BLOCKS else 'partial',
                configuration_sha256=configuration_sha, planned_blocks=list(BLOCKS), completed_blocks=done,
                acquisition=dict(counts=counts, sources=sources, exposure=exposure, spectra=add_spectra(spectra),
                                 measured_energy_window_counts=windows),
                imaging=dict(grid=planes[0]['grid'], model=planes[0]['model'], layers=pooled, split_blocks=split),
                blocks={name: block for name, block in zip(done, blocks, strict=True)})


def overlaps(report, plane, rows, links, packs):
    import gegi_source_exposure as association
    import gegi_source_library as library

    onsets = [row['first_ge_deposit_ns'] for row in rows]
    max_span = max((row['last_ge_deposit_ns'] - row['first_ge_deposit_ns'] for row in rows), default=0)
    image = {record['trigger_time_ns']: record for record in plane['triggers']}
    cache = {}
    counts = defaultdict(Counter)
    examples = {}
    for index, (trigger, link) in enumerate(zip(report['triggers'], links, strict=True)):
        start, end = trigger['trigger_time_ns'], trigger['rise_end_ns']
        onset_indices = range(bisect_left(onsets, start-association.MATCH_NS),
                              bisect_right(onsets, end+association.MATCH_NS))
        possible = {rows[i]['source'] for i in onset_indices if association.overlaps_activity(onsets[i], trigger)}
        unavailable = any(not rows[i]['native_available'] for i in onset_indices)
        merged_rows = [rows[i] for i in link['group_indices'] if rows[i]['classification'] == 'merged']
        merged_sources = {row['source'] for row in merged_rows}
        mixed_graph = link['association'] == 'merged' and len(merged_sources) == 2
        first = bisect_left(onsets, start-max_span-NATIVE_DRIFT_CAP_NS-1)
        overlap_rows = [row for row in rows[first:bisect_left(onsets, end)]
                        if row['last_ge_deposit_ns']+NATIVE_DRIFT_CAP_NS+1 > start]
        drives = defaultdict(list)
        if len({row['source'] for row in overlap_rows}) == 2 and end > start:
            collectors = [c-1 for c in trigger['x_collecting_strips']+trigger['y_collecting_strips']]
            for row in overlap_rows:
                unavailable |= not row['native_available']
                if not row['native_available']:
                    continue
                native, status, digest = library.read_native(packs[row['source']], row, cache)
                REQUIRE(native is not None and status == row['native_status'] and digest == row['metadata_sha256'],
                        'Saved detector component differs from its sealed metadata')
                knots = native.time_ns + row['first_ge_deposit_ns']
                # Nonzero current on a measured strip from each source at a shared instant.
                enabled = np.any(native.drive_V[0, collectors, :-1] != 0, axis=0)
                relevant = enabled & (knots[:-1] < end) & (knots[1:] > start)
                drives[row['source']].extend((max(start, lo), min(end, hi)) for lo, hi in
                                            zip(knots[:-1][relevant], knots[1:][relevant], strict=True))
        left, right = (sorted(drives[key]) for key in SOURCE_KEYS)
        i = j = 0
        current_overlap = False
        while i < len(left) and j < len(right):
            a, b = left[i], right[j]
            if max(a[0], b[0]) < min(a[1], b[1]):
                current_overlap = True
                break
            if a[1] < b[1]:
                i += 1
            else:
                j += 1
        reference_unknown = unavailable or link['association'] in ('ambiguous', 'history_boundary_unknown')
        outcome = {'qualified_triggers': 1, 'both_source_ge_onsets_in_rise_with_tolerance': int(len(possible) == 2),
                   'mixed_source_merged_timing_graph': int(mixed_graph),
                   'mixed_graph_with_accepted_energy': int(mixed_graph and trigger['energy_keV'] is not None),
                   'mixed_graph_without_accepted_energy': int(mixed_graph and trigger['energy_keV'] is None),
                   'both_source_simultaneous_native_current_on_measured_strips': int(current_overlap),
                   'current_overlap_with_accepted_energy': int(current_overlap and trigger['energy_keV'] is not None),
                   'current_overlap_without_accepted_energy': int(current_overlap and trigger['energy_keV'] is None),
                   'reference_ambiguous_or_unavailable': int(reference_unknown)}
        counts['all_qualified'].update(outcome)
        if start in image:
            outcome['mixed_graph_projected_mass'] = image[start]['projected_mass'] if mixed_graph else 0.
            outcome['current_overlap_projected_mass'] = image[start]['projected_mass'] if current_overlap else 0.
            counts['all_two_strip'].update(outcome)
            counts[energy_layer(trigger['energy_keV'])].update(outcome)
        if mixed_graph and len(merged_rows) == 2 and len(possible) == 2:
            key = ('mixed_graph_with_simultaneous_current' if current_overlap else
                   'mixed_graph_with_accepted_energy' if trigger['energy_keV'] is not None else
                   'mixed_graph_without_accepted_energy')
            labels = [key] + (['mixed_graph_two_strip'] if start in image else [])
            if any(label not in examples for label in labels):
                example = dict(
                    trigger_number=index+1, trigger_time_ns=start, rise_end_ns=end, energy_keV=trigger['energy_keV'],
                    x_collecting_strips=trigger['x_collecting_strips'], y_collecting_strips=trigger['y_collecting_strips'],
                    guard_contact_ids=trigger['guard_contact_ids'],
                    groups=[{k: row[k] for k in ('source', 'campaign_initial_id', 'raw_event_id', 'occurrence_id',
                                                'group_id', 'first_ge_deposit_ns', 'last_ge_deposit_ns',
                                                'truth_edep_keV', 'metadata_sha256')} for row in merged_rows],
                )
                for label in labels:
                    examples.setdefault(label, example)
    return counts, examples


def history_summary(rows, candidates):
    sources = {}
    for key in SOURCE_KEYS:
        groups = [row for row in rows if row['source'] == key]
        parents = {(r['campaign_initial_id'], r['occurrence_id']) for r in groups}
        histories = {r['campaign_initial_id'] for r in groups}
        input_groups = {(r['campaign_initial_id'], r['group_id']) for r in groups}
        sources[key] = dict(in_exposure_ge_group_occurrences=len(groups), distinct_original_ge_groups=len(input_groups),
                            distinct_original_parent_histories_with_ge_onset=len(histories),
                            clock_parent_occurrences_with_ge_onset=len(parents),
                            repeated_ge_groups=len(groups)-len(input_groups),
                            group_onsets_from_parents_before_exposure=sum(r['parent_precedes_live_time'] for r in groups))
    outcomes = defaultdict(Counter)
    histories = defaultdict(lambda: defaultdict(lambda: defaultdict(set)))
    for item in candidates.values():
        if item['reference'] is None:
            continue
        row, = item['deposit_groups']
        reference, comparison = item['reference'], item['comparison']
        identifier = (row['campaign_initial_id'], row['group_id'])
        ancestry = reference.get('unknown_reason') or reference['status']
        significant = reference.get('significant_interaction_count')
        full = reference.get('containment') == 'full_energy_at_photon_birth'
        classification = 'exact_two_significant_interaction_cells' if comparison else ancestry
        if comparison is None and significant is not None and significant > 2:
            classification = 'more_than_two_significant_interactions'
        for label in ('all_two_strip', energy_layer(item['energy_keV'])):
            key = (row['source'], label)
            outcomes[key]['isolated_clock_occurrences'] += 1
            histories[key]['all'][identifier].add('isolated_rise_time_match')
            histories[key]['reference_classification'][identifier].add(classification)
            if comparison and full:
                verdict = comparison['full_energy_order_outcome']
                outcomes[key][verdict] += 1
                histories[key]['full_energy_order'][identifier].add(verdict)
                allowed = sum(order['kinematically_allowed'] for pairing in item['two_strip_pairings']['pairings']
                              for order in pairing['compton_orders'])
                if allowed == 1:
                    global_verdict = {'only_true_order': 'only_order_agrees',
                                      'only_reverse_order': 'only_order_reversed'}.get(verdict, 'only_order_wrong_pair')
                elif allowed == 0:
                    global_verdict = 'no_allowed_orders'
                else:
                    global_verdict = {'both_allowed': 'multiple_orders_both_true_pair_orders',
                                      'only_true_order': 'multiple_orders_include_true_order'}.get(
                                          verdict, 'multiple_orders_exclude_true_order')
                histories[key]['globally_allowed_order'][identifier].add(global_verdict)
                if reference['unassigned_energy_keV'] > 0:
                    histories[key]['full_energy_with_small_unassigned_energy'][identifier].add('full_energy')
            if comparison and not full:
                histories[key]['containment_of_two_significant_interactions'][identifier].add(reference['containment'])
            if significant is not None and significant > 2 and full:
                histories[key]['full_energy_with_more_than_two_significant_interactions'][identifier].add('full_energy')

    def unique_outcomes(results):
        return dict(Counter(next(iter(verdicts)) if len(verdicts) == 1 else 'clock_occurrences_disagree'
                            for verdicts in results.values()))

    def parent_outcomes(results):
        parents = defaultdict(set)
        for (parent, _), verdicts in results.items():
            parents[parent].update(verdicts)
        return unique_outcomes(parents)

    return sources, {source: {label: {
        'isolated_matched_clock_occurrences': outcomes[source, label]['isolated_clock_occurrences'],
        'distinct_original_parent_histories': len({i[0] for i in buckets['all']}),
        'distinct_original_groups': len(buckets['all']),
        'reference_classification_by_original_group': unique_outcomes(buckets['reference_classification']),
        'full_energy_order_by_original_group': unique_outcomes(buckets['full_energy_order']),
        'full_energy_order_by_clock_occurrence': {verdict: count for verdict, count in outcomes[source, label].items()
                                                  if verdict != 'isolated_clock_occurrences'},
        'full_energy_globally_allowed_orders_by_original_parent': parent_outcomes(buckets['globally_allowed_order']),
        'full_energy_two_significant_groups_with_small_unassigned_energy': len(buckets['full_energy_with_small_unassigned_energy']),
        'full_energy_multiscatter_original_groups': len(buckets['full_energy_with_more_than_two_significant_interactions']),
        'other_containment_by_original_group': unique_outcomes(buckets['containment_of_two_significant_interactions']),
    } for (key, label), buckets in histories.items() if key == source} for source in SOURCE_KEYS}


def clock_reference(folder, block):
    import gzip

    import gegi_heldout_pairing_study as heldout
    from gegi_event_store import encoded, sha

    raw = (folder/'report.json').read_bytes()
    packed = (folder/'plane.json.gz').read_bytes()
    provenance = block['provenance']
    REQUIRE(pool.digest(raw) == provenance['report_sha256'] and pool.digest(packed) == provenance['plane_sha256'],
            'Saved report or plane changed before clock matching')
    report, plane = json.loads(raw), json.loads(gzip.decompress(packed))
    sources = [(folder / source['input_directory']['relative_to_report_directory']).resolve() for source in report['sources']]
    observed = dict(counts=report['counts'], spectra=report['spectra'], triggers=report['triggers'],
                    mask=report['exposure']['excluded_intervals_ns'])
    REQUIRE(sha(encoded(observed)) == report['receipt']['observed_result_sha256'], 'Recorded measured quantities changed')
    hashes = {}
    rows, packs, mask, frozen = heldout.scheduled_inputs(report, sources, hashes)
    links = heldout.link_groups(rows, report['triggers'], mask)
    # Use the sealed measured order decisions already bound to the plane by timestamp.
    candidates = {i: {key: row[key] for key in ('energy_keV', 'two_strip_pairings')}
                  for i, row in enumerate(report['triggers']) if row.get('two_strip_pairings') is not None}
    heldout.attach_truth(candidates, rows, links, packs, frozen, hashes)
    onsets, examples = overlaps(report, plane, rows, links, packs)
    source_histories, history_orders = history_summary(rows, candidates)
    return dict(shard_receipt_sha256=block['receipt_sha256'], truth_input_sha256=hashes,
                all_trigger_associations=dict(Counter(link['association'] for link in links)),
                two_strip_truth_link_scope=dict(Counter(item['truth_link_scope'] for item in candidates.values())),
                overlap_counts=onsets, overlap_examples=examples, source_histories=source_histories,
                history_orders=history_orders)


def add_diagnostics(*summaries):
    pooled = {}
    for summary in summaries:
        for key, value in summary.items():
            if isinstance(value, dict):
                pooled[key] = add_diagnostics(pooled.get(key, {}), value)
            else:
                pooled[key] = pooled.get(key, 0) + value
    return pooled


def diagnostic_result(completed, cache):
    keys = ('all_trigger_associations', 'two_strip_truth_link_scope', 'overlap_counts', 'source_histories', 'history_orders')
    return dict(
        status='completed' if list(cache) == completed else 'partial', completed_blocks=list(cache),
        scope=(
            'Timing references use replayed clock marks and archived Ge onsets. Rise onset support uses the established '
            '60 ns tolerance. Merged timing groups are candidates for the same measured trigger. Simultaneous native '
            'current requires a positive-duration overlap inside the actual rise interval with nonzero stored current '
            'from each source on at least one measured X or Y strip. This can include induced neighbor current and has '
            'no amplitude cutoff. Pulse removal and a causal change of trigger acceptance are unmeasured. A supported '
            'overlap and an unknown association can coexist.'
        ),
        history_scope=(
            'Archive parent and group tallies deduplicate clocks within each sealed independent source shard. '
            'Order scoring uses isolated timing matches, two distinct endpoint cells each corresponding to a separate '
            'interaction of at least 5 keV, and the recorded root photon birth energy for the full-energy subset. '
            'Additional interactions or unassigned energy below threshold can occur. Globally allowed orders count '
            'all measured permutations, including a compatible permutation that misses the true cells. '
            'Original-history outcomes disagree when separate '
            'clock occurrences yield different energy-based orders. Results describe these archived histories.'
        ),
        pooled={key: add_diagnostics(*(block[key] for block in cache.values())) for key in keys}, blocks=cache,
    )


def write_result(output, result):
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=output.parent, delete=False) as handle:
        scratch = Path(handle.name)
        json.dump(result, handle, allow_nan=False, separators=(',', ':'))
        handle.write('\n')
    try:
        scratch.replace(output)
    finally:
        scratch.unlink(missing_ok=True)


def run(campaign, *, diagnostics, follow=False):
    configuration_sha = pool.digest((campaign/'campaign.json').read_bytes())
    output = campaign/'results.json'
    prior = json.loads(output.read_bytes()) if output.is_file() else {}
    names = (Path(__file__).name, 'gegi_heldout_pairing_study.py', 'gegi_source_exposure.py',
             'gegi_source_library.py', 'gegi_continuous_pairing_study.py', 'gegi_parent_gamma_reference.py',
             'gegi_digital_pairs.py', 'gegi_dual_source.py', 'gegi_pulse_stream.py', 'gegi_event_store.py',
             'gegi_continuous_plane.py', 'gegi_pool_measured_planes.py', 'gegi_joint_imaging.py')
    implementation = {name: pool.digest((ROOT/'tools'/name).read_bytes()) for name in names}
    saved = (prior.get('clock_reference', {}).get('blocks', {}) if prior.get('kind') == KIND
             and prior.get('analysis_source_sha256') == implementation else {})
    shards, cache = {}, {}
    while True:
        new = [name for name in BLOCKS if name not in shards and (campaign/name/'receipt.json').is_file()]
        if new:
            for name in new:
                shards[name] = measured_block(campaign/name, configuration_sha)
            result = measured_results(configuration_sha, shards)
            blocks = result['completed_blocks']
            for name in new:
                if name in saved and saved[name]['shard_receipt_sha256'] == result['blocks'][name]['receipt_sha256']:
                    cache[name] = saved[name]
            result['analysis_source_sha256'] = implementation
            result['clock_reference'] = diagnostic_result(blocks, {k: cache[k] for k in blocks if k in cache})
            write_result(output, result)
            if diagnostics:
                for name in blocks:
                    if name not in cache:
                        cache[name] = clock_reference(campaign/name, result['blocks'][name])
                        result['clock_reference'] = diagnostic_result(blocks, {k: cache[k] for k in blocks if k in cache})
                        write_result(output, result)
            print(json.dumps(dict(status=result['status'], completed_blocks=blocks,
                                  counts=result['acquisition']['counts'],
                                  diagnostics_blocks=result['clock_reference']['completed_blocks'])), flush=True)
        if not follow or len(shards) == len(BLOCKS):
            REQUIRE(shards, 'No completed acquisitions have a shard receipt yet')
            return
        status_path = campaign/'status.json'
        if status_path.is_file():
            runner = json.loads(status_path.read_bytes())
            REQUIRE(runner['status'] != 'failed', 'The campaign supervisor reported a failure; partial results are saved')
        sleep(15)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign', type=Path, default=CAMPAIGN)
    parser.add_argument('--diagnostics', action='store_true', help='Also match the saved source clocks and original histories')
    parser.add_argument('--follow', action='store_true', help='Include subsequent sealed blocks as they finish')
    args = parser.parse_args()
    run(args.campaign.resolve(), diagnostics=args.diagnostics, follow=args.follow)


if __name__ == '__main__':
    main()
