"""Compare the two three-intersection triggers in each line with every same-count removal."""

import argparse
from collections import Counter
import gzip
from itertools import combinations
import json
from math import comb, sqrt
import os
from pathlib import Path

if __name__ == '__main__':
    for variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
        os.environ[variable] = '1'

import numpy as np

from gegi_continuous_plane import LINE_ENERGIES_KEV
from gegi_intersection_image_study import (ENDPOINTS, ENDPOINTS_SHA, PRIOR_STUDY, PRIOR_STUDY_SHA,
                                           is_subgroup, project_events)
from gegi_joint_imaging import ResponseSettings, plane_grid
from gegi_plane_prior_study import ACCOUNTING, AREA, MASS_TOL, PRIORS, maximum_difference, read_bound
from gegi_plane_footprint_study import ROOT, V1_POOL, V1_POOL_SHA
from gegi_pool_measured_planes import digest, require


IDENTITY = ('trigger_index', 'two_strip_ordinal', 'trigger_time_ns', 'energy_keV')
NATIVE_KEY = ('source', 'campaign_initial_id', 'group_id')


def native_key(endpoint):
    require(endpoint['native_status'] == 'measured', 'Reference trigger lacks a measured endpoint identity')
    return tuple(endpoint['native_group'][key] for key in NATIVE_KEY)


def summarize(outcomes, selected):
    histogram = Counter(row['displacement_mm2'] for row in outcomes)
    below = sum(count for distance, count in histogram.items() if distance < selected['displacement_mm2'])
    equal = histogram[selected['displacement_mm2']]
    above = sum(count for distance, count in histogram.items() if distance > selected['displacement_mm2'])
    require(equal > 0 and below + equal + above == len(outcomes), 'The selected pair must be in its reference')
    fractions = {}
    for metric in ('baseline_peak_removed_fraction', 'maximum_reduction_fraction'):
        values = np.array([row[metric] for row in outcomes])
        less = int(np.count_nonzero(values < selected[metric]))
        ties = int(np.count_nonzero(values == selected[metric]))
        greater = int(np.count_nonzero(values > selected[metric]))
        require(ties > 0 and less + ties + greater == len(outcomes), 'Inconsistent peak-height reference counts')
        fractions[metric] = dict(minimum=float(values.min()), median=float(np.median(values)),
                                 maximum=float(values.max()), below=less, equal=ties, above=greater,
                                 at_least=ties+greater)
    return dict(pair_count=len(outcomes), changed_peak_count=len(outcomes)-histogram[0],
                displacement_counts=dict(below=below, equal=equal, above=above, at_least=equal+above),
                displacement_histogram_mm2=sorted(histogram.items()), **fractions)


def compare_pairs(stacked, baseline, saved_peak, points, endpoint_rows):
    summation_error = maximum_difference(stacked.sum(axis=0), baseline)
    require(summation_error <= MASS_TOL, 'Projected trigger maps do not reproduce the saved baseline')
    peak = int(np.argmax(baseline))
    require(saved_peak['position_mm'] == points[peak].tolist() and saved_peak['value'] == baseline[peak],
            'Stored maximum disagrees with the original cell map')
    grid_xy = points[:, :2].astype(int)
    require(np.array_equal(grid_xy, points[:, :2]), 'Exact displacement ranks require integral grid coordinates')
    chosen = tuple(i for i, row in enumerate(endpoint_rows) if is_subgroup(row))
    require(len(chosen) == 2, 'Expected two three-intersection triggers per measured line')
    blocks = [row['block'] for row in endpoint_rows]
    histories = [native_key(row) for row in endpoint_rows]
    first, second = chosen
    require(blocks[first] == blocks[second], 'Selected pair no longer comes from a single block')
    same_history = histories[first] == histories[second]
    block_history_counts = Counter(history for block, history in zip(blocks, histories, strict=True)
                                   if block == blocks[first])
    block_pairs = comb(block_history_counts.total(), 2)
    block_same_history_pairs = sum(comb(count, 2) for count in block_history_counts.values())
    expected_matched = block_same_history_pairs if same_history else block_pairs-block_same_history_pairs
    records = {}
    matched = []
    for i, j in combinations(range(len(endpoint_rows)), 2):
        omitted = stacked[i]+stacked[j]
        cells = baseline-omitted
        require(cells.min() >= -MASS_TOL and abs(float(cells.sum())-(len(endpoint_rows)-2)) <= MASS_TOL,
                'Leave-two-out image did not remove exactly two projected trigger units')
        peak_after = int(np.argmax(cells))
        offset = grid_xy[peak_after]-grid_xy[peak]
        displacement_mm2 = int(offset@offset)
        result = dict(peak_after=dict(position_mm=points[peak_after].tolist(), value=float(cells[peak_after])),
                      displacement_mm2=displacement_mm2, displacement_mm=sqrt(displacement_mm2),
                      baseline_peak_removed_fraction=float(omitted[peak]/baseline[peak]),
                      maximum_reduction_fraction=float(1.-cells[peak_after]/baseline[peak]))
        records[i, j] = result
        if blocks[i] == blocks[j] == blocks[first] and (histories[i] == histories[j]) == same_history:
            matched.append(result)
    selected = records[chosen]
    retained = stacked[[i for i in range(len(stacked)) if i not in chosen]].sum(axis=0)
    direct_sum_error = maximum_difference(retained, baseline-stacked[first]-stacked[second])
    require(direct_sum_error <= MASS_TOL and points[np.argmax(retained)].tolist() == selected['peak_after']['position_mm'],
            'Direct retained-map maximum differs from baseline subtraction')
    require(len(records) == comb(len(endpoint_rows), 2) and len(matched) == expected_matched
            and any(row is selected for row in matched),
            'Pair comparison did not enumerate the required reference')
    return dict(baseline_peak=saved_peak, selected_pair=selected,
                maximum_baseline_cell_difference=summation_error,
                maximum_selected_direct_sum_cell_difference=direct_sum_error,
                all_pairs=summarize(list(records.values()), selected),
                same_block_and_history_relation=summarize(matched, selected))


def study():
    original = read_bound(V1_POOL, V1_POOL_SHA)
    prior = read_bound(PRIOR_STUDY, PRIOR_STUDY_SHA)
    endpoint_root = read_bound(ENDPOINTS, ENDPOINTS_SHA)
    endpoints = {(row['block'], row['trigger_index']): row for row in endpoint_root['events']}
    blocks = prior['views']['full']['exposures']
    require(prior['original_pooled_sha256'] == V1_POOL_SHA and endpoint_root['status'] == 'completed'
            and blocks == original['views']['full']['exposures'] == list(prior['order_ledger'])
            and len(endpoints) == len(endpoint_root['events']) == 324, 'Input population changed')
    grid = prior['grids']['original']
    extent, step, z = (grid[key] for key in ('extent_mm', 'step_mm', 'assumed_z_mm'))
    ticks, points = plane_grid(extent, step, z)
    require(grid == original['grid'] and (extent, step, z) == (120., 4., 40.)
            and ticks.tolist() == grid['x_mm'] == grid['y_mm'], 'Original prior grid changed')
    settings = ResponseSettings(**prior['model'])
    settings.validate()
    lines = {}
    for center in LINE_ENERGIES_KEV:
        layer = f'{center:g}_keV'
        original_line = original['views']['full']['layers'][layer]
        prior_line = prior['views']['full']['layers'][layer]
        line_rows, line_endpoints = [], []
        for block in blocks:
            for row in prior['order_ledger'][block]:
                endpoint = endpoints[block, row['trigger_index']]
                in_line = row['energy_keV'] is not None and abs(row['energy_keV']-center) <= max(5., .02*center)
                require(in_line == (endpoint['energy_window'] == layer)
                        and all(row[key] == endpoint[key] for key in (*IDENTITY, *ACCOUNTING[2:])),
                        'Endpoint descriptor, line membership or measured trigger accounting changed')
                if in_line:
                    line_rows.append(row)
                    line_endpoints.append(endpoint)
        projected = [i for i, row in enumerate(line_rows) if row['projected_mass'] > 0.]
        require(all(line_rows[i]['projected_mass'] == 1. for i in projected)
                and len(line_rows) == prior_line['triggers']
                and len(projected) == prior_line['triggers_with_geometry'] == prior_line['projected_mass']
                and len(line_rows)-len(projected) == prior_line['unresolved_mass']
                and all(original_line[key] == prior_line[key] for key in ACCOUNTING), 'Line denominators changed')
        labelled = [row for row in line_endpoints if is_subgroup(row)]
        require(len(labelled) == 2 and all(row['projected_mass'] == 1. for row in labelled), 'Line labels changed')
        # Trigger numbers identify occurrences within a block and can repeat across blocks.
        projected_by_block = [[i for i in projected if line_endpoints[i]['block'] == block] for block in blocks]
        require(projected == [i for block in projected_by_block for i in block], 'Projected block order changed')
        block_maps = [project_events([line_rows[i] for i in indices], settings, points)
                      for indices in projected_by_block if indices]
        line_endpoints = [line_endpoints[i] for i in projected]
        by_prior = {}
        for name in PRIORS:
            report = prior_line['priors'][name]
            baseline = np.asarray(report['original_mass']).ravel()
            if name == AREA:
                require(np.array_equal(baseline, np.asarray(original_line['mass']).ravel())
                        and report['peaks']['original'] == original_line['peaks'],
                        'Previously saved area baselines differ')
            stacked = np.concatenate([maps[name] for maps in block_maps])
            by_prior[name] = compare_pairs(stacked, baseline, report['peaks']['original'][0],
                                           points, line_endpoints)
        lines[layer] = dict(line_center_keV=center, **{key: prior_line[key] for key in ACCOUNTING},
                            distinct_projected_histories=len({native_key(row) for row in line_endpoints}),
                            selected_pair_same_history=native_key(labelled[0]) == native_key(labelled[1]),
                            selected_pair_triggers=[{key: row[key] for key in ('block', *IDENTITY)} |
                                                    dict(native_group=dict(zip(NATIVE_KEY, native_key(row), strict=True)))
                                                    for row in labelled], priors=by_prior)
    return dict(kind='gegi_intersection_influence_v1', status='completed', grid=grid, lines=lines,
                input_sha256={path.name: sha for path, sha in ((V1_POOL, V1_POOL_SHA),
                              (PRIOR_STUDY, PRIOR_STUDY_SHA), (ENDPOINTS, ENDPOINTS_SHA))},
                interpretation='Every unordered pair of projected trigger occurrences in each measured-energy line '
                               'loses the same two units of projected mass. Each retained trigger keeps its nominal '
                               'pairing and order mixture, prior, footprint and original mass. All unresolved weight '
                               'remains on the baseline ledger. The matched reference is restricted to the selected '
                               'pair’s block and same-versus-distinct original carrier history relationship. Triggers '
                               'can reuse the same history, and tested pairs can share triggers. These finite ranks '
                               'describe the saved maps; they have no inferential p-value.',
                metrics=dict(displacement='Euclidean distance from the full-map maximum, ranked on exact squared mm.',
                             baseline_peak_removed_fraction='Fraction of full-map mass removed at its maximum cell.',
                             maximum_reduction_fraction='Fractional change from the old maximum height to the new '
                                                        'maximum height, using unrenormalized mass per cell.'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New private gzip JSON derivative')
    args = parser.parse_args()
    sources = [ROOT/'tools'/f'gegi_{name}.py' for name in ('intersection_influence', 'intersection_image_study',
               'plane_prior_study', 'plane_footprint_study', 'pool_measured_planes',
               'joint_imaging', 'continuous_plane', 'imaging')]
    hashes = {path.name: digest(path.read_bytes()) for path in sources}
    result = study()
    result['source_sha256'] = hashes
    payload = json.dumps(result, allow_nan=False, separators=(',', ':')).encode('utf-8')
    require(hashes == {path.name: digest(path.read_bytes()) for path in sources}, 'Study source changed during processing')
    with args.output.open('xb') as target:
        target.write(gzip.compress(payload+b'\n', mtime=0))


if __name__ == '__main__':
    main()
