"""Compare two source-plane priors on four bound measured GeGI cone ledgers."""

import argparse
import gzip
import json
from math import atan2, fsum, isclose, sqrt
import os
from pathlib import Path

if __name__ == '__main__':
    for variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
        os.environ[variable] = '1'

import numpy as np

from gegi_continuous_plane import LINE_ENERGIES_KEV, plane_prior_weights
from gegi_joint_imaging import ResponseSettings, blind_peaks, candidate_response, plane_grid, spectral_membership
from gegi_plane_footprint_study import ACQUISITIONS, ROOT, V1_POOL, V1_POOL_SHA, VIEWS, delta, read_events
from gegi_pool_measured_planes import LAYER_COUNTS, LAYER_MASS, digest, require


FOOTPRINT = V1_POOL.with_name('independent-1s-footprint.json.gz')
FOOTPRINT_SHA = 'e7670e7176717402a0158ce5c02f4ae48b77bed95dca134a0c38cafec2d57857'
AREA, SOLID_ANGLE = PRIORS = ('uniform-area', 'uniform-solid-angle')
MASS_TOL = 1e-12
ACCOUNTING = (*LAYER_COUNTS, *LAYER_MASS)


def read_bound(path, sha256):
    packed = path.read_bytes()
    require(digest(packed) == sha256, f'Bound input changed: {path.name}')
    return json.loads(gzip.decompress(packed))


def maximum_difference(first, second):
    return float(np.max(abs(first-np.asarray(second).ravel()), initial=0.))


def area_parity(actual, saved):
    error = maximum_difference(actual, saved)
    require(error <= MASS_TOL, f'Uniform-area map differs from the saved comparison by {error:g}')
    return error


def order_response(candidate, old_points, wide_points, inside, weights, settings, checks):
    valid_old = np.linalg.norm(old_points-candidate.vertex, axis=1) > 1e-9
    valid_wide = np.linalg.norm(wide_points-candidate.vertex, axis=1) > 1e-9
    require(np.array_equal(valid_old, valid_wide[inside]), 'Shared cells have different geometric support')
    old_raw = candidate_response(candidate, old_points[valid_old], settings)
    wide_raw = candidate_response(candidate, wide_points[valid_wide], settings)
    require(np.all(np.isfinite(wide_raw) & (wide_raw >= 0.)) and
            np.all(np.isfinite(old_raw) & (old_raw >= 0.)), 'Invalid saved-cone kernel')
    shared = inside[valid_wide]
    checks['maximum_shared_raw_kernel_abs_difference'] = max(
        checks['maximum_shared_raw_kernel_abs_difference'], maximum_difference(old_raw, wide_raw[shared]))
    results = {}
    for prior, (old_weight, wide_weight) in weights.items():
        old = old_raw*old_weight[valid_old]
        wide = wide_raw*wide_weight[valid_wide]
        check = 'maximum_shared_weighted_kernel_abs_difference'
        checks[check][prior] = max(checks[check][prior], maximum_difference(old, wide[shared]))
        original_integral, wide_integral = float(old.sum()), float(wide.sum())
        require(0. < original_integral <= wide_integral, 'Invalid available-order integral')
        inside_fraction = float(wide[shared].sum())/wide_integral
        inside_from_original = original_integral/wide_integral
        require(isclose(inside_fraction, inside_from_original, rel_tol=0., abs_tol=MASS_TOL),
                'Common-crop integral differs from the independently evaluated original grid')
        results[prior] = (candidate.prior*(old/original_integral), candidate.prior*(wide/wide_integral),
                          dict(original_integral=original_integral, wide_integral=wide_integral,
                               wide_inside_fraction=inside_fraction,
                               wide_inside_mass=candidate.prior*inside_fraction,
                               wide_outside_mass=candidate.prior*(1.-inside_fraction)))
    return valid_old, valid_wide, results


def project(plane, settings, old_points, wide_points, inside, weights, checks):
    ledger = plane['triggers']
    events = read_events(ledger, settings)
    masks = {'all': np.ones(len(events), dtype=bool), **spectral_membership(events, LINE_ENERGIES_KEV)}
    require(masks.keys() == plane['layers'].keys() and
            np.all(np.add.reduce([mask.astype(int) for key, mask in masks.items() if key != 'all']) == 1),
            'Energy gates must partition the original two-strip ledger')
    maps = {key: {prior: (np.zeros(len(old_points)), np.zeros(len(wide_points))) for prior in PRIORS} for key in masks}
    for i, (event, row) in enumerate(zip(events, ledger, strict=True)):
        pairs = row['pairings']
        orders = [order for pair in pairs for order in pair['orders']]
        projected = [order for order in orders if order['status'] == 'projected']
        without_order = fsum(pair['nominal_mass'] for pair in pairs if not pair['orders'])
        without_pairing = float(not pairs)
        unavailable = fsum(order['nominal_mass'] for order in orders if order['status'] != 'projected')
        require(event.identity[0] == row['trigger_index'] and len(orders) == row['allowed_hypotheses'] and
                event.unresolved_mass == row['unresolved_mass'] == without_pairing+without_order+unavailable,
                'Saved event identity or unavailable-order mass differs')
        row.update(unassigned_without_pairing_mass=without_pairing,
                   unassigned_without_allowed_order_mass=without_order, unassigned_without_projection_mass=unavailable)
        image = {prior: (np.zeros(len(old_points)), np.zeros(len(wide_points))) for prior in PRIORS}
        for candidate, order in zip(event.candidates, projected, strict=True):
            old_valid, wide_valid, response = order_response(candidate, old_points, wide_points, inside,
                                                            weights, settings, checks)
            order['priors'] = {}
            for prior, (old, wide, stats) in response.items():
                image[prior][0][old_valid] += old
                image[prior][1][wide_valid] += wide
                order['priors'][prior] = stats
        for label, mask in masks.items():
            if mask[i]:
                for prior in PRIORS:
                    for target, cells in zip(maps[label][prior], image[prior], strict=True):
                        target += cells
    members = {key: [row for row, included in zip(ledger, mask, strict=True) if included] for key, mask in masks.items()}
    for label, included in members.items():
        saved = plane['layers'][label]
        require(tuple(saved[key] for key in ACCOUNTING) == (
            len(included), sum(row['hypotheses'] > 0 for row in included),
            sum(row['allowed_hypotheses'] for row in included), sum(row['hypotheses'] for row in included),
            fsum(row['projected_mass'] for row in included), fsum(row['unresolved_mass'] for row in included)),
            'The energy layer differs from its saved trigger denominator')
        checks['maximum_uniform_area_original_cell_abs_difference'] = max(
            checks['maximum_uniform_area_original_cell_abs_difference'], area_parity(maps[label][AREA][0], saved['mass']))
        for old, wide in maps[label].values():
            require(all(isclose(float(cells.sum()), saved['projected_mass'], rel_tol=0., abs_tol=MASS_TOL)
                        for cells in (old, wide)), 'Block map does not close against the saved projected mass')
    return maps, members


def layer_summary(old, wide, old_points, wide_points, inside, reference, orders):
    crop = wide[inside]
    inner, outer = float(crop.sum()), float(wide[~inside].sum())
    projected = reference['projected_mass']
    require(np.isfinite(old).all() and (old >= 0.).all() and np.isfinite(wide).all() and (wide >= 0.).all() and
            isclose(float(old.sum()), projected, rel_tol=0., abs_tol=MASS_TOL) and
            isclose(inner+outer+reference['unresolved_mass'], reference['triggers'], rel_tol=0., abs_tol=MASS_TOL) and
            isclose(inner, fsum(order['wide_inside_mass'] for order in orders), rel_tol=0., abs_tol=MASS_TOL) and
            isclose(outer, fsum(order['wide_outside_mass'] for order in orders), rel_tol=0., abs_tol=MASS_TOL),
            'Projected, crop, outside and unresolved masses do not close')
    peaks = dict(original=blind_peaks(old, old_points), wide=blind_peaks(wide, wide_points),
                 wide_crop=blind_peaks(crop, old_points))
    retained = [order['wide_inside_fraction'] for order in orders]
    old_n, wide_n = round(sqrt(len(old))), round(sqrt(len(wide)))
    return dict(wide_inside_mass=inner, wide_outside_mass=outer, wide_inside_fraction=inner/projected if projected else None,
                order_inside_fraction_min=min(retained, default=None), order_inside_fraction_max=max(retained, default=None),
                peaks=peaks, shift_from_original_mm={view: delta(peaks['original'], peaks[view])
                                                     for view in ('wide', 'wide_crop')},
                original_mass=old.reshape(old_n, old_n).tolist(), wide_mass=wide.reshape(wide_n, wide_n).tolist())


def study():
    baseline = read_bound(V1_POOL, V1_POOL_SHA)
    footprint = read_bound(FOOTPRINT, FOOTPRINT_SHA)
    grid = baseline['grid']
    extent, step, z = (grid[key] for key in ('extent_mm', 'step_mm', 'assumed_z_mm'))
    require((extent, step, z) == (120., 4., 40.) and footprint['original_pooled_sha256'] == V1_POOL_SHA,
            'Unexpected saved footprint or grid')
    wide_extent = 2*extent
    old_ticks, old_points = plane_grid(extent, step, z)
    wide_ticks, wide_points = plane_grid(wide_extent, step, z)
    grids = dict(original=grid, wide=dict(grid, extent_mm=wide_extent,
                                          x_mm=wide_ticks.tolist(), y_mm=wide_ticks.tolist()))
    inside = (abs(wide_points[:, :2]) < extent).all(axis=1)
    require(old_ticks.tolist() == grid['x_mm'] == grid['y_mm'] and np.array_equal(old_points, wide_points[inside])
            and grids == footprint['grids'], 'The fixed display crop must share the original centers')
    weights = {prior: (plane_prior_weights(old_points, step, prior), plane_prior_weights(wide_points, step, prior))
               for prior in PRIORS}
    for old, wide in weights.values():
        require(np.isfinite(wide).all() and (wide > 0.).all() and np.array_equal(old, wide[inside]),
                'The same detector point must have the same finite positive prior weight across both footprints')
    totals = {}
    for name, half_width, solid_angle in zip(grids, (extent, wide_extent), weights[SOLID_ANGLE], strict=True):
        analytic = 4*atan2(half_width**2, abs(z)*sqrt(2*half_width**2+z**2))
        measured = float(solid_angle.sum())
        require(isclose(measured, analytic, rel_tol=0., abs_tol=MASS_TOL), 'Cell solid angles do not tile the square')
        totals[name] = dict(cell_solid_angles_sr=measured, analytic_rectangle_solid_angle_sr=analytic)
    checks = dict(maximum_uniform_area_original_cell_abs_difference=0., maximum_uniform_area_wide_cell_abs_difference=0.,
                  maximum_shared_raw_kernel_abs_difference=0.,
                  maximum_shared_weighted_kernel_abs_difference=dict.fromkeys(PRIORS, 0.), rectangle_solid_angles=totals)

    exposures, order_ledger = [], {}
    expected_model = None
    for item, block, frozen_input in zip(baseline['inputs'], baseline['individual'], footprint['inputs'], strict=True):
        name = item['name']
        require(all(item[key] == value for key, value in frozen_input.items()), 'The saved studies bind different blocks')
        plane = read_bound(ACQUISITIONS/name/'plane.json.gz', item['plane_sha256'])
        require(plane['grid'] == grid and plane['input_sha256'] == item['plane_inputs'] and
                plane['input_sha256']['acquisition'] == item['report_sha256'] and
                all(plane['selection'][key] == value for key, value in block['selection'].items()) and
                block['selection']['two_strip_triggers'] == len(plane['triggers']), 'Saved block identity or census differs')
        model = {key: plane['model'][key] for key in ('strip_pitch_mm', 'angular_nuisance_sigma_deg')}
        if expected_model is None:
            expected_model = model
        require(model == expected_model, 'Saved response settings differ among exposures')
        settings = ResponseSettings(**model)
        settings.validate()
        exposures.append(project(plane, settings, old_points, wide_points, inside, weights, checks))
        order_ledger[name] = plane['triggers']
    require(checks['maximum_shared_raw_kernel_abs_difference'] <= MASS_TOL and
            max(checks['maximum_shared_weighted_kernel_abs_difference'].values()) <= MASS_TOL,
            'The response differed on shared cells before normalization')

    views = {}
    for name, indices in VIEWS.items():
        saved, frozen = baseline['views'][name], footprint['views'][name]
        require(saved['exposures'] == frozen['exposures'] == [baseline['inputs'][i]['name'] for i in indices] and
                saved['selection'] == frozen['selection'], 'Saved half or pooled selection differs')
        layers = {}
        for label, reference in saved['layers'].items():
            frozen_layer = frozen['layers'][label]
            accounting = {key: reference[key] for key in ACCOUNTING}
            require(accounting == {key: frozen_layer[key] for key in ACCOUNTING}, 'Saved layer denominators differ')
            orders = [order for i in indices for row in exposures[i][1][label] for pair in row['pairings']
                      for order in pair['orders'] if order['status'] == 'projected']
            require(len(orders) == accounting['hypotheses'], 'The saved projected hypotheses changed')
            by_prior = {}
            for prior in PRIORS:
                block_maps = [exposures[i][0][label][prior] for i in indices]
                old, wide = (np.add.reduce(images) for images in zip(*block_maps, strict=True))
                by_prior[prior] = layer_summary(old, wide, old_points, wide_points, inside, reference,
                                                [order['priors'][prior] for order in orders])
                if prior == AREA:
                    for mode, cells, ref in (('original', old, reference['mass']), ('wide', wide, frozen_layer['wide_mass'])):
                        key = f'maximum_uniform_area_{mode}_cell_abs_difference'
                        checks[key] = max(checks[key], area_parity(cells, ref))
                    for mode, peaks in by_prior[AREA]['peaks'].items():
                        require([p['position_mm'] for p in peaks] == [p['position_mm'] for p in frozen_layer['peaks'][mode]],
                                'Uniform-area peak identity differs from the frozen footprint comparison')
            shift = {mode: delta(peaks, by_prior[SOLID_ANGLE]['peaks'][mode])
                     for mode, peaks in by_prior[AREA]['peaks'].items()}
            layers[label] = accounting | dict(priors=by_prior, shift_between_priors_mm=shift)
        views[name] = dict(exposures=saved['exposures'], selection=saved['selection'], layers=layers)
    first, second = (views[key]['layers'] for key in ('first_half', 'second_half'))
    split = {key: {prior: {mode: delta(peaks, second[key]['priors'][prior]['peaks'][mode])
                           for mode, peaks in first[key]['priors'][prior]['peaks'].items()} for prior in PRIORS} for key in first}
    return dict(kind='gegi_measured_plane_prior_study_v1', original_pooled_sha256=V1_POOL_SHA, footprint_sha256=FOOTPRINT_SHA,
                inputs=footprint['inputs'], grids=grids, model=expected_model, energy_windows=baseline['energy_windows'],
                prior_definitions={AREA: 'Equal physical area for the equal square cells.',
                                   SOLID_ANGLE: 'Exact solid angle of each square cell seen from detector (0, 0, 0) mm.'},
                crop_definition=footprint['crop_definition'],
                interpretation='Each projected order keeps its saved nominal mass. Its angular likelihood is weighted by the '
                               'cell prior measure and normalized on each footprint. The common crop retains the wide-map values. '
                               'Both priors are conditional on the chosen plane and footprint; neither measures detector sensitivity.',
                checks=checks, views=views, split_peak_separation_mm=split, order_ledger=order_ledger)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New private gzip JSON derivative')
    args = parser.parse_args()
    sources = [ROOT/'tools'/name for name in ('gegi_plane_prior_study.py', 'gegi_plane_footprint_study.py',
               'gegi_pool_measured_planes.py', 'gegi_joint_imaging.py', 'gegi_continuous_plane.py', 'gegi_imaging.py')]
    hashes = {path.name: digest(path.read_bytes()) for path in sources}
    result = study()
    result['source_sha256'] = hashes
    payload = json.dumps(result, allow_nan=False, separators=(',', ':')).encode('utf-8')
    compressed = gzip.compress(payload+b'\n', mtime=0)
    require(hashes == {path.name: digest(path.read_bytes()) for path in sources}, 'Study source changed during processing')
    with args.output.open('xb') as target:
        target.write(compressed)


if __name__ == '__main__':
    main()
