"""Attribute fresh GeGI backprojection peaks to unchanged saved waveform fits."""

from __future__ import annotations

import argparse
from collections import Counter
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import time

if __name__ == '__main__':
    for variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
        os.environ[variable] = '1'

import numpy as np

import gegi_candidate_imaging as I
import gegi_candidate_records as record_support
from gegi_candidate_records import saved_events, events_from_saved
import gegi_joint_imaging as J
import gegi_peak_diagnostic as peaks


PLANE = I.plane
BLOCK_NS = 1_000_000_000
REGION_RADIUS_MM = 20.
SOURCE_IDS = ('cs137_point_decay_v1', 'co60_point_decay_v1', 'co60_point_decay_v1')
MASS_ATOL = 1e-12


def order_matrix(events, rows, points, settings, prior, step_mm):
    """Apply the existing finite-grid normalization to each original available order."""
    order_count = sum(len(event.candidates) for event in events)
    images = np.zeros((order_count, len(points)))
    weights = None if prior == PLANE.DEFAULT_PLANE_PRIOR else PLANE.plane_prior_weights(points, step_mm, prior)
    slices, index = [], 0
    for event, row in zip(events, rows, strict=True):
        start = index
        orders = [order for pair in row['pairings'] for order in pair['orders'] if order['status'] == 'available']
        for candidate, _ in zip(event.candidates, orders, strict=True):
            valid, values = record_support.projected_order(candidate, points, settings, weights)
            images[index, valid] = values
            index += 1
        slices.append(slice(start, index))
    return images, slices


def brightest(image, points, edge):
    index = int(np.argmax(image))
    if image[index] <= 0:
        return None
    return dict(position_mm=points[index].tolist(), mass=float(image[index]), on_image_edge=bool(edge[index]))


def sum_support(image, masks, peak_index):
    return dict(peak_cell=float(image[peak_index]), **{key: float(image[mask].sum()) for key, mask in masks.items()})


def perturbation(image, points, edge, masks, peak_index):
    peak = brightest(image, points, edge)
    return dict(peak=peak, shift_mm=None if peak is None else math.dist(peak['position_mm'], points[peak_index]),
                support=sum_support(image, masks, peak_index))


def evaluate(events, rows, settings, *, z_mm, extent_mm, step_mm, prior, saved_extent_mm,
             source_mm, live_time_ns, excluded_intervals, original_layer=None):
    ticks, points = J.plane_grid(extent_mm, step_mm, z_mm)
    images, slices = order_matrix(events, rows, points, settings, prior, step_mm)
    order_mass = images.sum(axis=1)
    image = np.zeros(len(points))
    for sl in slices:
        image += images[sl].sum(axis=0)
    projected = np.array([order_mass[sl].sum() for sl in slices])
    allowed = sum(len(pair['orders']) for row in rows for pair in row['pairings'])
    census = dict(triggers=len(rows), triggers_with_geometry=int(np.count_nonzero(projected)),
                  allowed_hypotheses=allowed, hypotheses=int(np.count_nonzero(order_mass)),
                  projected_mass=float(image.sum()), unresolved_mass=float(len(rows)-image.sum()))
    if original_layer is not None:
        original = np.asarray(original_layer['mass']).ravel()
        delta = float(np.max(np.abs(image-original)))
        if (delta > MASS_ATOL or any(not math.isclose(count, original_layer[key], abs_tol=MASS_ATOL, rel_tol=0)
                                     for key, count in census.items())
                or any(not math.isclose(value, row['saved_projected_mass'], abs_tol=MASS_ATOL, rel_tol=0)
                       for value, row in zip(projected, rows, strict=True))):
            raise ValueError('Reprojection differs from the saved layer or individual trigger census')
    else:
        delta = None

    peak_index = int(np.argmax(image))
    edge_radius = np.abs(points[:, :2]).max(axis=1)
    edge = edge_radius == ticks[-1]
    peak = brightest(image, points, edge)
    if peak is None:
        raise ValueError('No projected order in the requested measured-energy window')

    # Every map and maximum already exists before the programmed source is scored.
    near_source = np.linalg.norm(points[:, :2]-source_mm[:2], axis=1) <= REGION_RADIUS_MM
    masks = dict(peak_near=np.linalg.norm(points[:, :2]-points[peak_index, :2], axis=1) <= REGION_RADIUS_MM,
                 source_near=near_source, edge_cells=edge, edge_band=edge_radius >= extent_mm-REGION_RADIUS_MM,
                 outside_saved_grid=edge_radius > saved_extent_mm)
    support = sum_support(image, masks, peak_index)
    source_peak = brightest(np.where(near_source, image, 0.), points, edge)
    modes = J.blind_peaks(image, points)
    n_blocks = math.ceil(live_time_ns/BLOCK_NS)
    block_images = np.zeros((n_blocks, len(points)))
    block_ids = [[] for _ in range(n_blocks)]
    contributions = []
    for row, sl in zip(rows, slices, strict=True):
        trigger_id = row['original_trigger_id']
        trigger_time_ns = row['trigger_time_ns']
        if not 0 <= trigger_time_ns <= live_time_ns:
            raise ValueError('Original trigger time is outside the saved acquisition clock')
        block_index = min(n_blocks-1, int(trigger_time_ns//BLOCK_NS))
        trigger_image = images[sl].sum(axis=0)
        block_images[block_index] += trigger_image
        block_ids[block_index].append(trigger_id)
        order_support = iter(images[sl])
        orders = [dict(pair_index=pair['index'], order=order['order'],
                       **sum_support(next(order_support), masks, peak_index))
                  for pair in row['pairings'] for order in pair['orders'] if order['status'] == 'available']
        contribution = sum_support(trigger_image, masks, peak_index)
        for key, value in contribution.items():
            if not math.isclose(math.fsum(order[key] for order in orders), value, abs_tol=MASS_ATOL, rel_tol=0.):
                raise ValueError('Order contributions do not close against the original trigger')
        contributions.append(dict(original_trigger_id=trigger_id, support=contribution, orders=orders,
                                  without_trigger=perturbation(image-trigger_image, points, edge, masks, peak_index)))
    if (not np.allclose(block_images.sum(axis=0), image, rtol=0., atol=MASS_ATOL)
            or any(not math.isclose(math.fsum(r['support'][key] for r in contributions), value, abs_tol=MASS_ATOL, rel_tol=0.)
                   for key, value in support.items())):
        raise ValueError('Trigger and time-block contributions do not close against the complete map')

    blocks = []
    for index, (block_image, ids) in enumerate(zip(block_images, block_ids, strict=True)):
        low, high = index*BLOCK_NS, min((index+1)*BLOCK_NS, live_time_ns)
        excluded_ns = math.fsum(max(0., min(end, high)-max(start, low)) for start, end in excluded_intervals)
        blocks.append(dict(interval_ns=[low, high], qualified_adc_live_time_ns=high-low-excluded_ns,
                           selected_trigger_ids=ids, projected_mass=float(block_image.sum()),
                           block_only=perturbation(block_image, points, edge, masks, peak_index),
                           without_block=perturbation(image-block_image, points, edge, masks, peak_index)))
    ranked = sorted(contributions, key=lambda row: (-row['support']['peak_cell'], row['original_trigger_id']))
    nonzero = [row['support']['peak_cell'] for row in ranked if row['support']['peak_cell'] > 0]
    changed = [row for row in contributions if row['without_trigger']['shift_mm'] != 0.]
    maximum_shift = max((row['without_trigger']['shift_mm'] for row in changed
                         if row['without_trigger']['shift_mm'] is not None), default=0.)
    source_fraction = support['source_near']/census['projected_mass']
    return dict(plane=dict(assumed_z_mm=z_mm, extent_mm=extent_mm, step_mm=step_mm, prior=prior), census=census,
                reproduction_maximum_absolute_pixel_error=delta, peak=peak, blind_peaks=modes,
                source_score=dict(position_mm=source_mm, peak_distance_mm=math.dist(source_mm, peak['position_mm']),
                                  source_near_peak=source_peak, source_near_peak_relative_height=
                                  source_peak['mass']/peak['mass'] if source_peak else None,
                                  source_near_projected_fraction=source_fraction),
                support=support, trigger_concentration=dict(
                    nonzero_peak_cell_triggers=len(nonzero),
                    equivalent_peak_cell_contributors=support['peak_cell']**2/math.fsum(v*v for v in nonzero),
                    largest_peak_cell_share=nonzero[0]/support['peak_cell'],
                    largest_five_peak_cell_share=math.fsum(nonzero[:5])/support['peak_cell'],
                    ranked_top_trigger_ids=[row['original_trigger_id'] for row in ranked[:10]],
                    leave_one_out_changed_maximum_count=len(changed), leave_one_out_maximum_shift_mm=maximum_shift,
                    leave_one_out_changed_trigger_ids=[row['original_trigger_id'] for row in changed]),
                time_blocks=blocks, trigger_contributions=contributions)


def fit_context(rows):
    statuses = Counter(pair['waveform_fit_status'] for row in rows for pair in row['pairings'])
    fits = [pair['center_fit_diagnostics']['waveform'] for row in rows for pair in row['pairings']
            if 'waveform' in pair['center_fit_diagnostics']]
    residuals = [fit['weighted_residual_rms'] for fit in fits if fit['optimizer_success']]
    return dict(compatible_pair_waveform_statuses=dict(statuses), successful_waveform_fits=len(residuals),
                weighted_waveform_residual_rms_quantiles=dict(zip(
                    ('min', 'q25', 'median', 'q75', 'maximum'), np.quantile(residuals, [0, .25, .5, .75, 1]).tolist()))
                if residuals else None)


def run(saved_path, acquisition_path):
    begun = time.perf_counter()
    packed = saved_path.read_bytes()
    saved = json.loads(gzip.decompress(packed))
    acquisition_bytes = acquisition_path.read_bytes()
    acquisition = json.loads(acquisition_bytes)
    archive = acquisition_path.parent / I.storage.ARCHIVE_NAME
    hashes = dict(saved_plane=hashlib.sha256(packed).hexdigest(),
                  acquisition=hashlib.sha256(acquisition_bytes).hexdigest(), candidate_store=peaks.digest(archive),
                  calibration=saved['input_sha256']['calibration'])
    if (saved['kind'] != PLANE.PLANE_KIND or acquisition['status'] != 'completed'
            or acquisition['verification']['status'] != 'verified_exact'
            or any(hashes[key] != saved['input_sha256'][key] for key in ('acquisition', 'candidate_store'))
            or acquisition['artifacts'][archive.name]['sha256'] != hashes['candidate_store']):
        raise ValueError('Saved plane is not bound to this verified completed candidate acquisition')
    model, grid = saved['model'], saved['grid']
    settings = J.ResponseSettings(angular_nuisance_sigma_deg=model['angular_nuisance_sigma_deg'])
    events, rows = events_from_saved(saved, archive, settings)
    all_windows = J.spectral_membership(events, PLANE.LINE_ENERGIES_KEV)
    # Use programmed global positions as fixed scores on the common coordinate plane.
    score_positions = {r['id']: r['position_global_mm'] for r in acquisition['identity']['source_config']['sources']}
    duration = acquisition['live_time_ns']
    excluded = acquisition['excluded_intervals_ns']
    windows = {}
    for center, source_id in zip(PLANE.LINE_ENERGIES_KEV, SOURCE_IDS, strict=True):
        label = f'{center:g}_keV'
        members = np.flatnonzero(all_windows[label])
        selected_events = [events[i] for i in members]
        selected_rows = [rows[i] for i in members]
        cases = {}
        for extent in (grid['extent_mm'], 2*grid['extent_mm']):
            for prior in PLANE.PLANE_PRIORS:
                baseline = extent == grid['extent_mm'] and prior == model['plane_prior']
                cases[f'{extent:g}_mm_{prior}'] = evaluate(
                    selected_events, selected_rows, settings, z_mm=grid['assumed_z_mm'], extent_mm=extent,
                    step_mm=grid['step_mm'], prior=prior, saved_extent_mm=grid['extent_mm'],
                    source_mm=score_positions[source_id], live_time_ns=duration, excluded_intervals=excluded,
                    original_layer=saved['layers'][label] if baseline else None)
        baseline = cases[f"{grid['extent_mm']:g}_mm_{model['plane_prior']}"]
        for case in cases.values():
            case['peak_tracking'] = peaks.peak_tracking(case['blind_peaks'], [baseline['peak']['position_mm']])
        windows[label] = dict(center_keV=center, half_width_keV=max(5., .02*center), scoring_source_id=source_id,
                              fit_context=fit_context(selected_rows), cases=cases, original_triggers=selected_rows)
    modules = (__file__, I.__file__, I.storage.__file__, PLANE.__file__, J.__file__, peaks.__file__, record_support.__file__)
    return dict(kind='gegi_five_second_candidate_peak_attribution_v1', input_sha256=hashes,
                source_sha256={Path(file).name: peaks.digest(file) for file in modules},
                saved_selection=saved['selection'], saved_source_census=acquisition['source'], windows=windows,
                methods=dict(
                    reconstruction='Existing measured fits, pairing/order weights, angular kernel and per-cone finite-grid normalization.',
                    support='Nominal trigger units. Near-peak and near-source are closed 20 mm XY disks. Edge cells are the outer row/column, edge band is the outer 20 mm, and outside-saved-grid uses the original footprint. Regions can overlap.',
                    localization_score='Fixed programmed source position is used only for scoring. Energy-window membership does not establish isotope or photon identity.',
                    perturbations='Each leave-one-out removes the entire original trigger including all alternatives. Time blocks are deterministic 1 s acquisition-clock intervals, with the final interval including the endpoint. Blocks are descriptive and may share parent histories. No bootstrap or confidence intervals.',
                    fit_residual='Saved center waveform residual RMS is scaled by the existing optional output-noise RMS. Successful optimizers can still produce large waveform mismatch.',
                    peak_cell_concentration='Inverse sum of squared original trigger shares. Descriptive concentration, independent sample size unavailable.',
                    photon_truth='Input group ordinals are original archive joins and can cover many groups. No photon interaction histories or per-order truth labels were used. No transport, fields, drift, calibration or waveform fits were re-run.'),
                software=dict(python=platform.python_version(), numpy=np.__version__), elapsed_seconds=time.perf_counter()-begun)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--saved-plane', type=Path, required=True)
    parser.add_argument('--acquisition', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    result = run(args.saved_plane, args.acquisition)
    payload = gzip.compress((json.dumps(result, allow_nan=False, separators=(',', ':'))+'\n').encode(), mtime=0)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('xb') as stream:
        stream.write(payload)
    print(json.dumps({label: {key: case['peak'] for key, case in window['cases'].items()}
                      for label, window in result['windows'].items()}, indent=2))


if __name__ == '__main__':
    main()
