"""Compare the measured GeGI image with its three-endpoint-intersection subgroup."""

import argparse
import gzip
import json
from math import dist, fsum, isclose
import os
from pathlib import Path

if __name__ == '__main__':
    for variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
        os.environ[variable] = '1'

import numpy as np

from gegi_continuous_plane import LINE_ENERGIES_KEV, plane_prior_weights
from gegi_joint_imaging import ResponseSettings, blind_peaks, candidate_response, plane_grid, spectral_membership
from gegi_plane_footprint_study import ACQUISITIONS, ROOT, V1_POOL, V1_POOL_SHA, VIEWS, read_events
from gegi_plane_prior_study import ACCOUNTING, AREA, MASS_TOL, PRIORS, maximum_difference, read_bound
from gegi_pool_measured_planes import digest, require


LOCAL = ROOT / '.local/gegi-joint-two-site'
ENDPOINTS = LOCAL / 'independent-1s-weak-endpoints.json.gz'
ENDPOINTS_SHA = '40ade04dfccdf33cf2d8593f255b2cc462a7194e73e957b6b4cc235d8da69319'
PRIOR_STUDY = LOCAL / 'independent-1s-plane-priors.json.gz'
PRIOR_STUDY_SHA = 'cd0918844b62d57709d1825fd514ffbee999ee0211120c28b27c10ef7d2fe088'
OUTPUT = LOCAL / 'independent-1s-intersection-image.json.gz'
FOOTPRINTS = {'original': 120., 'wide': 240.}
GROUPS = ('full', 'subgroup', 'remainder')
UNASSIGNED = ('unassigned_without_pairing_mass', 'unassigned_without_allowed_order_mass',
              'unassigned_without_projection_mass')
PEAK_RTOL = 1e-12
IDENTITY = ('trigger_index', 'two_strip_ordinal', 'trigger_time_ns', 'energy_keV')
WEIGHTS = ('allowed_hypotheses', 'hypotheses', 'projected_mass', 'unresolved_mass')
NATIVE_ID = ('source', 'campaign_initial_id', 'group_id')
SOURCE_POSITIONS = {'cs137-left': [-40., 0., 40.], 'co60-right': [40., 0., 40.]}
LINE_SOURCES = {f'{line:g}_keV': source for line, source in zip(
    LINE_ENERGIES_KEV, ('cs137-left', 'co60-right', 'co60-right'), strict=True)}


def is_subgroup(row):
    return (row['native_status'] == 'measured' and row['endpoint_collection_cell_count'] == 3
            and row['measured_pairings']['compatible_pairing_count'] > 0)


def project_events(rows, settings, points, footprint='original'):
    """One flattened image per input row, indexed by the fixed plane priors."""
    events = read_events(rows, settings)
    weights = {prior: plane_prior_weights(points, 4., prior) for prior in PRIORS}
    images = {prior: np.zeros((len(rows), len(points))) for prior in PRIORS}
    for i, (event, row) in enumerate(zip(events, rows, strict=True)):
        orders = [order for pair in row['pairings'] for order in pair['orders'] if order['status'] == 'projected']
        for candidate, order in zip(event.candidates, orders, strict=True):
            valid = np.linalg.norm(points-candidate.vertex, axis=1) > 1e-9
            raw = candidate_response(candidate, points[valid], settings)
            require(np.all(np.isfinite(raw) & (raw >= 0.)), 'Invalid measured-cone response')
            for prior in PRIORS:
                weighted = raw*weights[prior][valid]
                integral = float(weighted.sum())
                fixed = order['priors'][prior][f'{footprint}_integral']
                require(integral > 0. and isclose(integral, fixed, rel_tol=MASS_TOL, abs_tol=0.),
                        'Measured-cone integral differs from the saved prior study')
                images[prior][i, valid] += candidate.prior*(weighted/integral)
        require(all(isclose(float(image[i].sum()), row['projected_mass'], rel_tol=0., abs_tol=MASS_TOL)
                    for image in images.values()), 'Trigger image does not close against its saved projected mass')
    return images


def strip_order_prior(row):
    pairs = [pair | dict(orders=[{k: v for k, v in order.items() if k != 'priors'}
                                  for order in pair['orders']]) for pair in row['pairings']]
    return {key: value for key, value in row.items() if key not in UNASSIGNED} | dict(pairings=pairs)


def joined_row(name, saved, measured, endpoint, layer):
    require(strip_order_prior(saved) == measured and
            all(saved[key] == endpoint[key] for key in (*IDENTITY, *WEIGHTS, *UNASSIGNED)) and
            endpoint['energy_window'] == layer and endpoint['native_status'] == 'measured',
            f'Trigger identity, cone ledger or endpoint data differ in {name}')
    endpoint_pairings = [
        {key: pair[key] for key in ('index', 'cells', 'nominal_mass')} | dict(orders=[
            {key: order[key] for key in ('order', 'nominal_mass', 'status')} for order in pair['orders']])
        for pair in saved['pairings']]
    compatible = endpoint['measured_pairings']['compatible_pairing_count']
    require(endpoint_pairings == endpoint['projection_pairings'] and compatible == len(saved['pairings']) and
            len(endpoint['endpoint_collections']) == endpoint['endpoint_collection_cell_count'] and
            isclose(fsum(saved[key] for key in UNASSIGNED), saved['unresolved_mass'], rel_tol=0., abs_tol=MASS_TOL),
            f'Measured pairings, order weights or endpoint label differ in {name}')
    return {key: saved[key] for key in (*IDENTITY, *WEIGHTS, *UNASSIGNED)} | dict(
        block=name, energy_window=layer, subgroup=is_subgroup(endpoint),
        native_group={key: endpoint['native_group'][key] for key in NATIVE_ID},
        endpoint_collection_cell_count=endpoint['endpoint_collection_cell_count'], pairing_class=endpoint['pairing_class'],
    )


def counts(rows):
    return dict(triggers=len(rows), triggers_with_geometry=sum(row['hypotheses'] > 0 for row in rows),
                **{key: sum(row[key] for row in rows) for key in WEIGHTS[:2]},
                **{key: fsum(row[key] for row in rows) for key in (*WEIGHTS[2:], *UNASSIGNED)},
                distinct_native_groups=len({tuple(row['native_group'].values()) for row in rows}),
                sources={source: sum(row['native_group']['source'] == source for row in rows)
                         for source in SOURCE_POSITIONS})


def peak(values, points):
    maximum = float(values.max())
    spread = float(np.ptp(values))
    near_tied = int(np.count_nonzero(maximum-values <= PEAK_RTOL*maximum))
    exact_tied = int(np.count_nonzero(values == maximum))
    stats = dict(value=maximum, near_tied_cells=near_tied, exactly_equal_maximum_cells=exact_tied)
    if maximum == 0. or spread <= PEAK_RTOL*maximum:
        return None, stats | dict(status='empty' if maximum == 0. else 'flat', position_mm=None, on_image_edge=None)
    index = int(np.argmax(values))
    edge = bool((np.abs(points[index, :2]) == np.max(np.abs(points[:, :2]))).any())
    return index, stats | dict(position_mm=points[index].tolist(), on_image_edge=edge,
                               status='tied' if near_tied > 1 else 'unique')


def share(mass):
    return mass | dict(subgroup_share_of_full=mass['subgroup']/mass['full'] if mass['full'] else None)


def peak_distance(first, second):
    return dist(first, second) if first is not None and second is not None else None


def source_neighborhood(images, points, source, peaks):
    origin = SOURCE_POSITIONS[source]
    adjacent = ((abs(points[:, :2]-origin[:2]) == 2.).all(axis=1)) & (points[:, 2] == origin[2])
    require(np.count_nonzero(adjacent) == 4, 'Programmed source is not at the shared corner of four cells')
    mass = {group: float(values[adjacent].sum()) for group, values in images.items()}
    return dict(source=source, position_mm=origin, cell_centers_mm=points[adjacent].tolist(), mass=share(mass),
                distance_from_peak_mm={group: peak_distance(origin, item['position_mm']) for group, item in peaks.items()})


def image_summary(images, points, fixed, accounting, source, checks, context):
    errors = dict(saved=maximum_difference(images['full'], fixed),
                  split=maximum_difference(images['full'], images['subgroup']+images['remainder']),
                  total=max(abs(float(values.sum())-accounting[group]['projected_mass'])
                            for group, values in images.items()))
    require(max(errors.values()) <= MASS_TOL and
            all(np.all(np.isfinite(values) & (values >= 0.)) for values in images.values()),
            f'Cell or integrated map mass failed to close for {context}: {errors}')
    for key, error in errors.items():
        checks[key] = max(checks[key], error)
    peaks = {}
    mass_at_peaks = {}
    for group, values in images.items():
        index, peaks[group] = peak(values, points)
        mass_at_peaks[group] = None if index is None else share({name: float(image[index]) for name, image in images.items()})
    saved_peak = blind_peaks(np.asarray(fixed).ravel(), points, maximum=1)
    require(peaks['full']['position_mm'] == (saved_peak[0]['position_mm'] if saved_peak else None),
            f'Saved maximum changed for {context}')
    full = peaks['full']['position_mm']
    n = len(fixed)
    result = dict(peaks=peaks, mass_at_peaks=mass_at_peaks,
                  shift_full_to_remainder_mm=peak_distance(full, peaks['remainder']['position_mm']),
                  shift_full_to_subgroup_mm=peak_distance(full, peaks['subgroup']['position_mm']),
                  subgroup_mass=images['subgroup'].reshape(n, n).tolist())
    if source is not None:
        result['programmed_source'] = source_neighborhood(images, points, source, peaks)
    return result


def study():
    input_sha256 = {}
    for path, sha in ((ENDPOINTS, ENDPOINTS_SHA), (PRIOR_STUDY, PRIOR_STUDY_SHA), (V1_POOL, V1_POOL_SHA)):
        input_sha256[path.relative_to(ROOT).as_posix()] = sha
    endpoint_data = read_bound(ENDPOINTS, ENDPOINTS_SHA)
    prior_study = read_bound(PRIOR_STUDY, PRIOR_STUDY_SHA)
    pooled_v1 = read_bound(V1_POOL, V1_POOL_SHA)
    require(endpoint_data['kind'] == 'gegi_independent_weak_strip_endpoints_v1' and endpoint_data['status'] == 'completed'
            and prior_study['kind'] == 'gegi_measured_plane_prior_study_v1'
            and prior_study['original_pooled_sha256'] == V1_POOL_SHA and
            prior_study['energy_windows'] == pooled_v1['energy_windows'], 'Unexpected saved study design')
    grids = prior_study['grids']
    points = {}
    for key, extent in FOOTPRINTS.items():
        grid = grids[key]
        ticks, points[key] = plane_grid(extent, 4., 40.)
        require((grid['extent_mm'], grid['step_mm'], grid['assumed_z_mm']) == (extent, 4., 40.) and
                grid['x_mm'] == grid['y_mm'] == ticks.tolist(), 'Unexpected footprint or cell coordinates')
    settings = ResponseSettings(**prior_study['model'])
    settings.validate()
    endpoint_rows = {(row['block'], row['trigger_index']): row for row in endpoint_data['events']}
    require(len(endpoint_rows) == len(endpoint_data['events']) == 324, 'Endpoint roster is not the 324 original triggers')

    block_rows = []
    block_images = []
    block_sizes = (79, 105, 73, 67)
    block_names = list(prior_study['order_ledger'])
    block_area_error = 0.
    for name, item, original, size in zip(block_names, prior_study['inputs'], pooled_v1['inputs'], block_sizes, strict=True):
        folder = ACQUISITIONS / name
        report_key = (folder/'report.json').relative_to(ROOT).as_posix()
        require(name == item['name'] and all(item[key] == original[key] for key in item) and
                endpoint_data['input_sha256'][report_key] == item['report_sha256'] and
                {source['source_group']: source['source_position_mm'] for source in original['sources']} == SOURCE_POSITIONS,
                f'Acquisition identities or programmed source positions differ in {name}')
        path = folder / 'plane.json.gz'
        plane = read_bound(path, item['plane_sha256'])
        input_sha256[path.relative_to(ROOT).as_posix()] = item['plane_sha256']
        saved_rows = prior_study['order_ledger'][name]
        require(len(saved_rows) == len(plane['triggers']) == size and plane['input_sha256'] == item['plane_inputs'] and
                plane['grid'] == grids['original'] and all(plane['model'][k] == v for k, v in prior_study['model'].items()),
                f'Saved block ledger or projection settings changed in {name}')
        events = read_events(saved_rows, settings)
        gates = spectral_membership(events, LINE_ENERGIES_KEV)
        require(set(plane['layers']) == {'all', *gates}, f'Saved energy gates changed in {name}')
        layers = [next(label for label, mask in gates.items() if mask[i]) for i in range(size)]
        rows = [joined_row(name, saved, measured, endpoint_rows.pop((name, saved['trigger_index'])), layer)
                for saved, measured, layer in zip(saved_rows, plane['triggers'], layers, strict=True)]
        images = {key: project_events(saved_rows, settings, xyz, key) for key, xyz in points.items()}
        for label, mask in {'all': np.ones(size, dtype=bool), **gates}.items():
            full = images['original'][AREA][mask].sum(axis=0)
            block_area_error = max(block_area_error, maximum_difference(full, plane['layers'][label]['mass']))
        block_rows.append(rows)
        block_images.append(images)
    require(not endpoint_rows and block_area_error <= MASS_TOL, 'Original blocks did not reproduce the saved area maps')

    events = [row for rows in block_rows for row in rows]
    subgroup = [row for row in events if row['subgroup']]
    full_counts = counts(events)
    require(full_counts['projected_mass'] == 254. and full_counts['unresolved_mass'] == 70. and
            full_counts['allowed_hypotheses'] == 374 and full_counts['hypotheses'] == 371 and len(subgroup) == 15 and
            all(row['projected_mass'] == 1. and row['unresolved_mass'] == 0. for row in subgroup) and
            [sum(row['energy_window'] == label for row in subgroup) for label in (*LINE_SOURCES, 'other_energy')]
            == [2, 2, 2, 9], 'Measured denominators or the projected subgroup differ from the frozen study')
    checks = dict(saved=0., split=0., total=0.)
    views = {}
    for name, indices in VIEWS.items():
        saved = prior_study['views'][name]
        require(saved['exposures'] == [block_names[i] for i in indices], 'The original split halves changed')
        rows = [row for i in indices for row in block_rows[i]]
        maps = {key: {prior: np.concatenate([block_images[i][key][prior] for i in indices]) for prior in PRIORS}
                for key in points}
        layers = {}
        for label, layer in saved['layers'].items():
            includes = np.array([label == 'all' or row['energy_window'] == label for row in rows], dtype=bool)
            members = np.array([row['subgroup'] for row in rows], dtype=bool)
            masks = {'full': includes, 'subgroup': includes & members, 'remainder': includes & ~members}
            accounting = {group: counts([row for row, included in zip(rows, mask, strict=True) if included])
                          for group, mask in masks.items()}
            require(all(accounting['full'][key] == layer[key] for key in ACCOUNTING) and
                    all(isclose(rec['projected_mass']+rec['unresolved_mass'], rec['triggers'], rel_tol=0., abs_tol=MASS_TOL)
                        for rec in accounting.values()) and
                    all(isclose(accounting['subgroup'][key]+accounting['remainder'][key], accounting['full'][key],
                                rel_tol=0., abs_tol=MASS_TOL) for key in (*ACCOUNTING, *UNASSIGNED)),
                    f'Saved layer or partition accounting changed for {name}/{label}')
            by_prior = {}
            for prior in PRIORS:
                by_prior[prior] = {}
                for footprint, xyz in points.items():
                    images = {group: maps[footprint][prior][mask].sum(axis=0) for group, mask in masks.items()}
                    by_prior[prior][footprint] = image_summary(images, xyz, layer['priors'][prior][f'{footprint}_mass'],
                                                               accounting, LINE_SOURCES.get(label), checks,
                                                               (name, label, prior, footprint))
            layers[label] = dict(counts=accounting, priors=by_prior)
        views[name] = dict(exposures=saved['exposures'], selection=saved['selection'], layers=layers)
    split_separation = {}
    first, second = (views[name]['layers'] for name in ('first_half', 'second_half'))
    for label in first:
        split_separation[label] = {prior: {key: {
            group: peak_distance(*(layers[label]['priors'][prior][key]['peaks'][group]['position_mm']
                                   for layers in (first, second))) for group in GROUPS} for key in points} for prior in PRIORS}
    return dict(kind='gegi_measured_intersection_image_study_v1', status='completed', input_sha256=input_sha256,
                inputs=prior_study['inputs'], grids=grids, energy_windows=prior_study['energy_windows'],
                prior_definitions=prior_study['prior_definitions'], programmed_source_positions_mm=SOURCE_POSITIONS,
                subgroup_definition='Energy-compatible measured trigger with exactly three saved native endpoint intersections.',
                interpretation='The labels use simulated endpoints. The measured cone geometry and saved order masses are fixed. '
                               'Each order uses the original prior normalization on the entire selected footprint. '
                               'Diagnostic maps keep those weights without renormalizing by group. The bound prior study '
                               'contains the full grids; subtract subgroup_mass to recover the remainder.',
                peak_rule=f'Positive, nonflat global maximum. First row-major cell for exact ties. '
                          f'Near ties lie within {PEAK_RTOL:g} of the maximum relative to its value.',
                checks=dict(combined_cells=3*5*len(PRIORS)*sum(len(xyz) for xyz in points.values()),
                            maximum_saved_map_cell_abs_difference=checks['saved'],
                            maximum_subgroup_plus_remainder_cell_abs_difference=checks['split'],
                            maximum_map_projected_mass_abs_difference=checks['total'],
                            maximum_original_block_area_cell_abs_difference=block_area_error,
                            new_transport_runs=0, new_drift_runs=0, new_waveform_fits=0),
                events=events, views=views, split_peak_separation_mm=split_separation)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=OUTPUT, help='New private gzip JSON derivative')
    output = parser.parse_args().output.resolve()
    require(output.is_relative_to(LOCAL) and not output.exists(), 'Use a new path below the private analysis directory')
    sources = [ROOT/'tools'/name for name in (Path(__file__).name, 'gegi_plane_prior_study.py',
               'gegi_plane_footprint_study.py', 'gegi_pool_measured_planes.py', 'gegi_joint_imaging.py',
               'gegi_continuous_plane.py', 'gegi_imaging.py')]
    source_sha256 = {path.relative_to(ROOT).as_posix(): digest(path.read_bytes()) for path in sources}
    result = study() | dict(source_sha256=source_sha256)
    payload = gzip.compress(json.dumps(result, allow_nan=False, separators=(',', ':')).encode()+b'\n', mtime=0)
    require(all(digest((ROOT/path).read_bytes()) == sha for path, sha in source_sha256.items()),
            'Analysis implementation changed during processing')
    with output.open('xb') as target:
        target.write(payload)
    print(json.dumps(result['checks'], indent=2))
    print(digest(payload))


if __name__ == '__main__':
    main()
