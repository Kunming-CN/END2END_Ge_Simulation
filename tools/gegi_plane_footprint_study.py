"""Compare two footprints on the same saved GeGI measured cone geometry."""

import argparse
import gzip
import json
from math import dist, fsum, isclose
from pathlib import Path

import numpy as np

from gegi_continuous_plane import LINE_ENERGIES_KEV
from gegi_imaging import ELECTRON_REST_KEV
from gegi_joint_imaging import (ResponseSettings, blind_peaks, candidate_response, plane_grid,
                                prepare_events, spectral_membership)
from gegi_pool_measured_planes import digest, require


ROOT = Path(__file__).resolve().parents[1]
V1_POOL = ROOT/'.local/gegi-joint-two-site/independent-1s-exposure.json.gz'
V1_POOL_SHA = '4306d85b53f6d28ddd0fcb9bfea23cf0af658a05646bbed82b7be7478d127727'
ACQUISITIONS = ROOT/'.local/gegi-dual-source'
VIEWS = {'first_half': (0, 1), 'second_half': (2, 3), 'full': (0, 1, 2, 3)}
GEOMETRY = ('vertex_mm', 'axis', 'half_angle_deg', 'site_separation_mm')


def read_events(ledger, settings):
    records = []
    for row in ledger:
        candidates = []
        for pair in row['pairings']:
            for order in pair['orders']:
                if order['status'] != 'projected':
                    continue
                e1, e2 = (pair['site_energies_keV'][i] for i in order['order'])
                # Recover the exact preparation angle used by the v1 producer from the saved slow energies.
                cosine = 1-ELECTRON_REST_KEV*(1/e2-1/(e1+e2))
                candidates.append({key: order[key] for key in GEOMETRY} | dict(
                    cos_theta=cosine, scatter_energy_keV=e1, absorbed_energy_keV=e2,
                    prior_weight=order['nominal_mass']))
        require(len(candidates) == row['hypotheses'] and
                isclose(fsum(c['prior_weight'] for c in candidates), row['projected_mass'], abs_tol=1e-12) and
                isclose(row['projected_mass']+row['unresolved_mass'], 1., abs_tol=1e-12), 'V1 order accounting differs')
        records.append(dict(event_id=row['trigger_index'], energy_keV=row['energy_keV'], candidates=candidates))
    return prepare_events(records, settings)


def project(events, settings, old_points, wide_points, inside):
    masks = {'all': np.ones(len(events), dtype=bool), **spectral_membership(events, LINE_ENERGIES_KEV)}
    old = {key: np.zeros(len(old_points)) for key in masks}
    wide = {key: np.zeros(len(wide_points)) for key in masks}
    fractions = {key: [] for key in masks}
    raw_delta = 0.
    for i, event in enumerate(events):
        image_old, image_wide = np.zeros(len(old_points)), np.zeros(len(wide_points))
        retention = []
        for candidate in event.candidates:
            valid_old = np.linalg.norm(old_points-candidate.vertex, axis=1) > 1e-9
            valid_wide = np.linalg.norm(wide_points-candidate.vertex, axis=1) > 1e-9
            raw_old = candidate_response(candidate, old_points[valid_old], settings)
            raw_wide = candidate_response(candidate, wide_points[valid_wide], settings)
            raw_delta = max(raw_delta, float(np.max(abs(raw_old-raw_wide[inside[valid_wide]]))))
            norm_old, norm_wide = float(raw_old.sum()), float(raw_wide.sum())
            require(norm_old > 0 and norm_wide > 0 and norm_old <= norm_wide, 'Invalid frozen-order footprint integral')
            image_old[valid_old] += candidate.prior*(raw_old/norm_old)
            image_wide[valid_wide] += candidate.prior*(raw_wide/norm_wide)
            retention.append((candidate.prior, norm_old/norm_wide))
        for label, mask in masks.items():
            if mask[i]:
                old[label] += image_old
                wide[label] += image_wide
                fractions[label].extend(retention)
    return old, wide, fractions, raw_delta


def parity(actual, saved):
    before = np.asarray(saved).ravel()
    error = float(np.max(abs(actual-before)))
    require(error <= 1e-12, f'Original footprint does not reproduce the maintained v1 map (max delta {error:g})')
    return error


def delta(first, second):
    return dist(first[0]['position_mm'], second[0]['position_mm']) if first and second else None


def run():
    packed = V1_POOL.read_bytes()
    require(digest(packed) == V1_POOL_SHA, 'Expected the sealed four-block v1 pooled study')
    baseline = json.loads(gzip.decompress(packed))
    grid = baseline['grid']
    require((grid['extent_mm'], grid['step_mm'], grid['assumed_z_mm']) == (120., 4., 40.), 'Unexpected v1 grid')
    old_ticks, old_points = plane_grid(120., 4., 40.)
    wide_ticks, wide_points = plane_grid(240., 4., 40.)
    inside = (abs(wide_points[:, :2]) < 120.).all(axis=1)
    require(np.array_equal(old_points, wide_points[inside]), 'Crop centers must coincide exactly with the original grid')
    old_maps, wide_maps, order_fractions = [], [], []
    parity_max, kernel_delta = 0., 0.
    frozen_model = None
    for item, block in zip(baseline['inputs'], baseline['individual'], strict=True):
        packed = (ACQUISITIONS/item['name']/'plane.json.gz').read_bytes()
        require(digest(packed) == item['plane_sha256'], 'A bound measured v1 trigger ledger changed')
        plane = json.loads(gzip.decompress(packed))
        require(plane['grid'] == grid and plane['input_sha256']['acquisition'] == item['report_sha256'] and
                plane['selection']['two_strip_triggers'] == len(plane['triggers']) and
                set(plane['layers']) == set(block['layers']), 'V1 ledger identity or grid differs')
        settings = ResponseSettings(strip_pitch_mm=plane['model']['strip_pitch_mm'],
                                    angular_nuisance_sigma_deg=plane['model']['angular_nuisance_sigma_deg'])
        settings.validate()
        if frozen_model is None:
            frozen_model = settings
        require(settings == frozen_model, 'Response settings differ among saved blocks')
        events = read_events(plane['triggers'], settings)
        old, wide, fractions, raw_delta = project(events, settings, old_points, wide_points, inside)
        kernel_delta = max(kernel_delta, raw_delta)
        for key, image in old.items():
            ref = plane['layers'][key]
            parity_max = max(parity_max, parity(image, ref['mass']))
            require(isclose(float(wide[key].sum()), ref['projected_mass'], abs_tol=1e-12), 'Wide-map weight changed')
        old_maps.append(old)
        wide_maps.append(wide)
        order_fractions.append(fractions)

    views = {}
    for name, indices in VIEWS.items():
        saved = baseline['views'][name]
        layers = {}
        require(saved['exposures'] == [baseline['inputs'][i]['name'] for i in indices], 'Original split changed')
        for label, ref in saved['layers'].items():
            old = np.add.reduce([old_maps[i][label] for i in indices])
            wide = np.add.reduce([wide_maps[i][label] for i in indices])
            crop = wide[inside]
            parity_max = max(parity_max, parity(old, ref['mass']))
            inner_mass, outside_mass = float(crop.sum()), float(wide[~inside].sum())
            weights = [pair for i in indices for pair in order_fractions[i][label]]
            require(isclose(inner_mass+outside_mass, ref['projected_mass'], abs_tol=1e-12) and
                    isclose(inner_mass, fsum(w*r for w, r in weights), abs_tol=1e-12), 'Wide-plane mass does not close')
            peaks = {'original': blind_peaks(old, old_points), 'wide': blind_peaks(wide, wide_points),
                     'wide_crop': blind_peaks(crop, old_points)}
            retained = [r for _, r in weights]
            layers[label] = {k: v for k, v in ref.items() if k not in ('mass', 'peaks')} | dict(
                wide_inside_mass=inner_mass, wide_outside_mass=outside_mass,
                wide_inside_fraction=inner_mass/ref['projected_mass'] if ref['projected_mass'] else None,
                order_inside_fraction_min=min(retained, default=None),
                order_inside_fraction_max=max(retained, default=None), peaks=peaks,
                shift_from_original_mm={key: delta(peaks['original'], peaks[key]) for key in ('wide', 'wide_crop')},
                wide_mass=wide.reshape(len(wide_ticks), len(wide_ticks)).tolist())
        views[name] = dict(exposures=saved['exposures'], selection=saved['selection'], layers=layers)
    first, second = (views[k]['layers'] for k in ('first_half', 'second_half'))
    split = {key: {view: delta(first[key]['peaks'][view], second[key]['peaks'][view])
                   for view in first[key]['peaks']} for key in first}
    inputs = [{key: row[key] for key in ('name', 'report_sha256', 'plane_sha256', 'clock_seed', 'noise_seed', 'plane_inputs')}
              for row in baseline['inputs']]
    return dict(kind='gegi_measured_plane_footprint_study_v1', original_pooled_sha256=V1_POOL_SHA,
                inputs=inputs, grids=dict(original=grid, wide=dict(grid, extent_mm=240.,
                            x_mm=wide_ticks.tolist(), y_mm=wide_ticks.tolist())),
                energy_windows=baseline['energy_windows'], angular_nuisance_sigma_deg=frozen_model.angular_nuisance_sigma_deg,
                maximum_original_cell_abs_difference=parity_max, maximum_shared_raw_kernel_abs_difference=kernel_delta,
                crop_definition='The central ±120 mm cells of the ±240 mm normalized map, retaining their original wide-map values.',
                interpretation='On shared cells each order has the same angular kernel. The crop scales each order’s original '
                               'weight by its original-to-wide kernel integral ratio, so their sum can peak elsewhere. '
                               'The outside mass is conditional on the wider assumed plane and its uniform planar prior.',
                views=views, split_peak_separation_mm=split)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New private gzip JSON derivative')
    args = parser.parse_args()
    sources = [Path(__file__).resolve(), ROOT/'tools/gegi_joint_imaging.py', ROOT/'tools/gegi_continuous_plane.py']
    hashes = {path.name: digest(path.read_bytes()) for path in sources}
    result = run()
    require(hashes == {path.name: digest(path.read_bytes()) for path in sources}, 'Study source changed during processing')
    result['source_sha256'] = hashes
    payload = json.dumps(result, allow_nan=False, separators=(',', ':')).encode('utf-8')
    with args.output.open('xb') as target:
        target.write(gzip.compress(payload+b'\n', mtime=0))


if __name__ == '__main__':
    main()
