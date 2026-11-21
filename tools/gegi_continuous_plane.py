"""Project measured continuous triggers onto an explicitly assumed plane."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
from pathlib import Path

if __name__ == '__main__':
    for variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
        os.environ[variable] = '1'

import numpy as np

from gegi_imaging import ELECTRON_REST_KEV, cone
from gegi_joint_imaging import ResponseSettings, candidate_response, plane_grid, prepare_events, spectral_membership


LINE_ENERGIES_KEV = (661.657, 1173.228, 1332.492)
ADC_WINDOWS_FILE = 'two-strip-adc.npz'
PLANE_FILE = 'plane.json.gz'
PLANE_KIND = 'gegi_continuous_measured_plane_backprojection_v1'
GEOMETRY_KEYS = ('vertex_mm', 'axis', 'half_angle_deg', 'site_separation_mm')
DEFAULT_PLANE_PRIOR = 'uniform-area'
PLANE_PRIORS = (DEFAULT_PLANE_PRIOR, 'uniform-solid-angle')


def _quadrant_solid_angle(x, y, width, height, z):
    """Solid angle of a rectangle in one quadrant, split into two triangles."""
    def direction(x, y):
        radius = np.hypot(np.hypot(x, y), z)
        return np.column_stack((x/radius, y/radius, z/radius)), radius

    lower_left, _ = direction(x, y)
    lower_right, right_radius = direction(x+width, y)
    upper_left, upper_radius = direction(x, y+height)
    upper_right, _ = direction(x+width, y+height)
    edge_scale = (width/right_radius)*(height/upper_radius)
    shared = 1 + (lower_right*upper_left).sum(axis=1)
    # The determinant of the three unnormalized rays has magnitude z*width*height.
    # Within one quadrant all pairwise dot products are nonnegative.
    return sum(2*np.arctan2(edge_scale*corner[:, 2], shared+((lower_right+upper_left)*corner).sum(axis=1))
               for corner in (lower_left, upper_right))


def plane_prior_weights(points, step_mm, prior):
    """Return unit area weights or exact square-cell solid angles in steradians."""
    if prior not in PLANE_PRIORS:
        raise ValueError(f'Unknown plane prior: {prior}')
    points = np.asarray(points, dtype=float)
    if (points.ndim != 2 or points.shape[1] != 3 or len(points) == 0 or not np.isfinite(points).all()
            or not math.isfinite(step_mm) or step_mm <= 0 or np.any(points[:, 2] != points[0, 2])):
        raise ValueError('Plane prior requires finite square-cell centers on one plane and a positive step')
    if prior == DEFAULT_PLANE_PRIOR:
        return np.ones(len(points), dtype=float)
    z = abs(points[0, 2])
    if z == 0:
        raise ValueError('The uniform solid-angle prior requires a plane at nonzero z relative to the detector origin')

    # Split cells that cross an axis and reflect their parts into the first quadrant.
    half = step_mm/2

    def sides(axis):
        center = np.abs(points[:, axis])
        crossing = np.maximum(half-center, 0.)
        return ((np.maximum(center-half, 0.), step_mm-crossing), (np.zeros_like(center), crossing))

    weights = np.zeros(len(points), dtype=float)
    for x, width in sides(0):
        for y, height in sides(1):
            used = (width > 0) & (height > 0)
            weights[used] += _quadrant_solid_angle(x[used], y[used], width[used], height[used], z)
    return weights


def plane_prior_metadata(prior, weights):
    """Describe the prior measure and finite normalization support in a saved map."""
    solid_angle = prior == 'uniform-solid-angle'
    return dict(plane_prior=prior, plane_prior_reference_origin_mm=[0., 0., 0.] if solid_angle else None,
                plane_prior_coverage_sr=math.fsum(weights) if solid_angle else None,
                plane_prior_support='Finite square reconstruction grid on the assumed detector-coordinate plane.')


def _two_strip_triggers(acquisition):
    return [(i, trigger) for i, trigger in enumerate(acquisition['triggers'], 1)
            if trigger.get('two_strip_pairings') is not None]


def _allowed_orders(pair):
    orders = [tuple(order['site_index_order']) for order in pair['compton_orders'] if order['kinematically_allowed']]
    if len(set(orders)) != len(orders) or set(orders) - {(0, 1), (1, 0)}:
        raise ValueError('Allowed orders must be unique orders of the two measured sites')
    return orders


def waveform_position_fit(fit, position_model):
    modes = fit['fit'].get('fits', {}).get('waveform', {})
    center = modes.get('center')
    if position_model == 'center':
        return center, 'center', None
    if position_model != 'lateral':
        raise ValueError('Unknown waveform position model')
    support = fit['lateral_calibration_support']
    if len(support) != 2 or any(type(flag) is not bool for flag in support):
        raise ValueError('Expected lateral support for each measured site')
    if not any(support):
        return center, 'center', 'no_lateral_calibration_for_either_site'
    kind = 'lateral' if all(support) else 'partial_lateral'
    corrected = modes.get(kind)
    if corrected is None:
        return center, 'center', 'no_lateral_waveform_fit'
    if not corrected['optimizer_success']:
        return center, 'center', 'lateral_optimizer_did_not_converge'
    if kind == 'partial_lateral' and (corrected['site_lateral_support'] != support or center is None or any(
            a[:2] != b[:2] for a, b, supported in zip(corrected['positions_mm'], center['positions_mm'], support, strict=True)
            if not supported)):
        raise ValueError('Partial lateral waveform fit moved an unsupported site off its strip center')
    return corrected, kind, None


def measured_events(acquisition, joint_fit):
    """Read measured energies, strip identities and the declared saved waveform positions."""
    selected = _two_strip_triggers(acquisition)
    records, accounting = [], []
    position_model = joint_fit.get('position_model', 'center')
    for ordinal, ((trigger_index, trigger), fitted) in enumerate(zip(selected, joint_fit['candidates'], strict=True), 1):
        if fitted['ordinal'] != ordinal or fitted['time_ns'] != trigger['trigger_time_ns']:
            raise ValueError('Saved waveform fits must match each measured two-strip time and ordinal')
        measured = trigger['two_strip_pairings']['pairings']
        fits = {item['index']: item for item in fitted['pairings']}
        if len(fits) != len(fitted['pairings']) or set(fits) != {item['index'] for item in measured}:
            raise ValueError('Saved waveform pairings do not match the measured pairings')
        compatible = sum(pair['energy_compatible'] for pair in measured)
        record = dict(event_id=trigger_index, energy_keV=trigger['energy_keV'], candidates=[])
        ledger = dict(trigger_index=trigger_index, two_strip_ordinal=ordinal, trigger_time_ns=trigger['trigger_time_ns'],
                      energy_keV=trigger['energy_keV'], pairings=[])
        portable = 'calibration_bundle' in joint_fit
        if portable:
            ledger['adc_window_status'] = fitted['window_status']
        for pair in measured:
            fit = fits[pair['index']]
            sites = pair['sites']
            cells = [[s['x_contact_id'], s['y_contact_id']] for s in sites]
            if cells != fit['cells'] or pair['energy_compatible'] != fit['energy_compatible']:
                raise ValueError('Saved waveform strip identities differ from the measured energy pairing')
            if not pair['energy_compatible']:
                continue
            orders = _allowed_orders(pair)
            fit_result = fit['fit']
            waveform, used_model, fallback = waveform_position_fit(fit, position_model)
            pair_ledger = dict(index=pair['index'], cells=cells, site_energies_keV=[s['energy_keV'] for s in sites],
                               nominal_mass=1/compatible, orders=[])
            if portable:
                status = fit_result['status']
                if waveform is None and status == 'fitted':
                    status = 'no_waveform_fit'
                elif waveform is not None and not waveform['optimizer_success']:
                    status = 'optimizer_did_not_converge'
                pair_ledger['waveform_fit_status'] = status
            if position_model == 'lateral':
                pair_ledger.update(waveform_position_model=used_model if waveform and waveform['optimizer_success'] else None,
                                   lateral_calibration_support=fit['lateral_calibration_support'], lateral_fallback_reason=fallback)
            ledger['pairings'].append(pair_ledger)
            fitted_sites = None
            if waveform is not None and waveform['optimizer_success']:
                positions = np.asarray(waveform['positions_mm'], dtype=float)
                if positions.shape != (2, 3) or not np.isfinite(positions).all():
                    raise ValueError('A successful waveform fit must carry two finite XYZ positions in mm')
                fitted_sites = [dict(energy_keV=s['energy_keV'], position_mm=xyz.tolist())
                                for s, xyz in zip(sites, positions, strict=True)]
            for order in orders:
                geometry = cone(*(fitted_sites[i] for i in order)) if fitted_sites is not None else None
                item = dict(order=order, nominal_mass=1/(compatible*len(orders)),
                            status='no_waveform_fit' if fitted_sites is None else 'no_usable_cone')
                if geometry is not None:
                    item.update(status='available', **{key: geometry[key] for key in GEOMETRY_KEYS})
                    record['candidates'].append(dict(geometry, prior_weight=item['nominal_mass']))
                pair_ledger['orders'].append(item)
        records.append(record)
        accounting.append(ledger)
    return records, accounting


def _reuse_saved_events(acquisition, accounting):
    """Recover measured cones from a freshly loaded ledger and reset their projection status."""
    selected = _two_strip_triggers(acquisition)
    records = []
    for ordinal, ((index, trigger), row) in enumerate(zip(selected, accounting, strict=True), 1):
        energy = trigger['energy_keV']
        if (row['trigger_index'], row['two_strip_ordinal'], row['trigger_time_ns'], row['energy_keV']) != (
                index, ordinal, trigger['trigger_time_ns'], energy):
            raise ValueError('Saved plane trigger identities, times and energies must match the acquisition')
        measured = [pair for pair in trigger['two_strip_pairings']['pairings'] if pair['energy_compatible']]
        candidates = []
        for pair, saved in zip(measured, row['pairings'], strict=True):
            sites = pair['sites']
            cells = [[site['x_contact_id'], site['y_contact_id']] for site in sites]
            energies = [site['energy_keV'] for site in sites]
            expected_orders = _allowed_orders(pair)
            if (saved['index'], saved['cells'], saved['site_energies_keV'], saved['nominal_mass']) != (
                    pair['index'], cells, energies, 1/len(measured)) or [
                    tuple(order['order']) for order in saved['orders']] != expected_orders:
                raise ValueError('Saved plane pairings and allowed orders must match the acquisition')
            for kept in saved['orders']:
                prior = kept['nominal_mass']
                if prior != 1/(len(measured)*len(expected_orders)):
                    raise ValueError('Saved plane order weights must match the measured alternatives')
                status = kept['status']
                if status in ('no_waveform_fit', 'no_usable_cone'):
                    continue
                if status not in ('projected', 'no_plane_response'):
                    raise ValueError(f'Unrecognized saved cone status: {status}')
                e1, e2 = (energies[i] for i in kept['order'])
                if not all(math.isfinite(energy) and energy > 0 for energy in (e1, e2)):
                    raise ValueError('Saved cone requires two positive finite site energies')
                # Recompute the exact original cosine from the saved slow energies.
                cosine = 1-ELECTRON_REST_KEV*(1/e2-1/(e1+e2))
                candidates.append({key: kept[key] for key in GEOMETRY_KEYS} | dict(
                    cos_theta=cosine, scatter_energy_keV=e1, absorbed_energy_keV=e2, prior_weight=prior))
                kept['status'] = 'available'
        records.append(dict(event_id=index, energy_keV=energy, candidates=candidates))
    return records


def reconstruct(acquisition, joint_fit, *, z_mm, extent_mm=120., step_mm=4., sigma_deg=5.,
                plane_prior=DEFAULT_PLANE_PRIOR):
    records, accounting = measured_events(acquisition, joint_fit)
    result = _project(acquisition, records, accounting, joint_fit['two_strip_triggers'], z_mm=z_mm,
                      extent_mm=extent_mm, step_mm=step_mm, sigma_deg=sigma_deg, plane_prior=plane_prior)
    if joint_fit.get('position_model') == 'lateral':
        result['model']['geometry'] = ('Measured waveform positions use the calibrated lateral grid at each supported site. '
                                      'Unsupported sites retain strip-center XY. Failed lateral fits fall back to available center fits.')
    return result


def _project(acquisition, records, accounting, two_strip_count, *, z_mm, extent_mm, step_mm, sigma_deg, plane_prior):
    settings = ResponseSettings(angular_nuisance_sigma_deg=sigma_deg)
    settings.validate()
    ticks, points = plane_grid(extent_mm, step_mm, z_mm)
    prior_weights = plane_prior_weights(points, step_mm, plane_prior)
    events = prepare_events(records, settings)
    masks = {'all': np.ones(len(events), dtype=bool)}
    if events:
        masks.update(spectral_membership(events, LINE_ENERGIES_KEV))
    else:
        masks.update((label, masks['all']) for label in (*[f'{e:g}_keV' for e in LINE_ENERGIES_KEV], 'other_energy'))
    maps = {key: np.zeros(len(points), dtype=float) for key in masks}
    for index, (event, ledger) in enumerate(zip(events, accounting, strict=True)):
        image = np.zeros(len(points), dtype=float)
        orders = [order for pair in ledger['pairings'] for order in pair['orders']]
        projected = []
        for candidate, order in zip(event.candidates, (o for o in orders if o['status'] == 'available'), strict=True):
            valid = np.linalg.norm(points-candidate.vertex, axis=1) > 1e-9
            kernel = candidate_response(candidate, points[valid], settings)
            if plane_prior != DEFAULT_PLANE_PRIOR:
                kernel *= prior_weights[valid]
            norm = float(kernel.sum())
            if norm > 0:
                image[valid] += candidate.prior*(kernel/norm)
                projected.append(candidate.prior)
                order['status'] = 'projected'
            else:
                order['status'] = 'no_plane_response'
        for label, mask in masks.items():
            if mask[index]:
                maps[label] += image
        mass = math.fsum(projected)
        ledger.update(allowed_hypotheses=len(orders), hypotheses=len(projected), projected_mass=mass,
                      unresolved_mass=max(0., 1-mass))

    shape = (len(ticks), len(ticks))
    layers = {}
    for label, mask in masks.items():
        members = [row for row, included in zip(accounting, mask, strict=True) if included]
        mass = math.fsum(row['projected_mass'] for row in members)
        if not math.isclose(maps[label].sum(), mass, abs_tol=1e-12):
            raise ValueError('The image does not close against the projected trigger mass')
        layers[label] = dict(mass=maps[label].reshape(shape).tolist(), triggers=len(members),
                             triggers_with_geometry=sum(row['hypotheses'] > 0 for row in members),
                             allowed_hypotheses=sum(row['allowed_hypotheses'] for row in members),
                             hypotheses=sum(row['hypotheses'] for row in members), projected_mass=mass,
                             unresolved_mass=math.fsum(row['unresolved_mass'] for row in members))
    total = len(acquisition['triggers'])
    energied = sum(t['energy_keV'] is not None for t in acquisition['triggers'])
    without_pairing = sum(not row['pairings'] for row in accounting)
    if (total != acquisition['counts']['qualified_triggers'] or energied != acquisition['counts']['qualified_energies']
            or len(events) != two_strip_count):
        raise ValueError('Measured event selection totals do not close')
    prior_measure = ('uniform planar prior' if plane_prior == DEFAULT_PLANE_PRIOR else
                     'uniform solid-angle prior at the detector origin (0, 0, 0) mm using each cell’s solid angle')
    return dict(
        kind=PLANE_KIND,
        grid=dict(x_mm=ticks.tolist(), y_mm=ticks.tolist(), assumed_z_mm=z_mm, step_mm=step_mm, extent_mm=extent_mm,
                  array_order='rows increase in y, columns increase in x; positions refer to cell centers'),
        selection=dict(qualified_triggers=total, qualified_energies=energied, triggers_without_energy=total-energied,
                       two_strip_triggers=len(events), two_strip_triggers_without_compatible_pairing=without_pairing,
                       two_strip_triggers_with_two_compatible_pairings=sum(len(row['pairings']) == 2 for row in accounting),
                       clock_live_time_ns=acquisition['exposure']['clock_live_time_ns'],
                       qualified_adc_live_time_ns=acquisition['exposure']['qualified_adc_live_time_ns'],
                       energy_windows='Existing fixed measured line-energy windows, half-width max(5 keV, 2% of center).'),
        model=dict(geometry='Two fitted depths with strip-center XY from the saved measured waveform fits.',
                   angular_nuisance_sigma_deg=sigma_deg, strip_pitch_mm=settings.strip_pitch_mm,
                   ambiguity='One nominal unit per measured two-strip trigger. Equal split among energy-compatible '
                             'pairings, then among each pairing’s kinematically allowed orders. Unresolved weight '
                             'remains outside the map, including compatible pairings with no allowed order.',
                   normalization='Finite-vertex angular likelihood with first-order strip-center uncertainty. Each '
                                 f'cone is normalized over the reconstruction grid cells under a {prior_measure} '
                                 'before multiplying by its nominal mass. Values are nominal trigger units per cell.',
                   limits='Sparse conditional backprojection. Changing the assumed plane or displayed footprint changes '
                          'the map. Energy and depth resolution, Doppler response and detector sensitivity are uncalibrated. '
                          'Peaks cannot establish emission activity, source count, or distance.',
                   **plane_prior_metadata(plane_prior, prior_weights)),
        layers=layers, triggers=accounting)


def run(acquisition_path, fit_path, **settings):
    acquisition_bytes, fit_bytes = acquisition_path.read_bytes(), fit_path.read_bytes()
    acquisition_sha256 = hashlib.sha256(acquisition_bytes).hexdigest()
    acquisition, joint_fit = json.loads(acquisition_bytes), json.loads(fit_bytes)
    bound = joint_fit.get('acquisition_sha256')
    if bound is None:
        # The predecessor stores an input seal under the acquisition report path.
        matches = [digest for key, digest in joint_fit['input_sha256'].items()
                   if key.startswith('.local/gegi-dual-source/') and key.endswith('/report.json')]
        bound = matches[0] if len(matches) == 1 else None
    if bound != acquisition_sha256:
        raise ValueError('The saved joint fit is not bound to this acquisition')
    result = reconstruct(acquisition, joint_fit, **settings)
    result['input_sha256'] = dict(acquisition=acquisition_sha256, waveform_fit=hashlib.sha256(fit_bytes).hexdigest())
    return result


def run_from_adc(acquisition_path, windows_path, calibration_path, **settings):
    """Project an acquisition directly from its matched ADC windows and external calibration."""
    try:
        from gegi_joint_calibration import fit_portable_acquisition
    except ModuleNotFoundError as error:
        if error.name != 'scipy':
            raise
        raise ValueError('Waveform fitting requires SciPy. Run this command in the prepared Pixi environment in the guide.') from error
    raw = acquisition_path.read_bytes()
    acquisition = json.loads(raw)
    acquisition_sha256 = hashlib.sha256(raw).hexdigest()
    joint_fit = fit_portable_acquisition(acquisition, acquisition_sha256, windows_path, calibration_path)
    result = reconstruct(acquisition, joint_fit, **settings)
    bundle = joint_fit['calibration_bundle']
    result['input_sha256'] = dict(acquisition=acquisition_sha256, adc_windows=joint_fit['adc_windows_sha256'],
                                  calibration=bundle['archive_sha256'])
    result['calibration_bundle'] = bundle
    result['fit_source_sha256'] = joint_fit['source_sha256']
    requested = len(bundle['requested_cells'])
    if requested:
        covered = len(bundle['calibrated_cells'])
        result['model']['geometry'] += f' The external waveform calibration covers {covered} of {requested} pixels in compatible pairings.'
    return result


def run_from_plane(acquisition_path, plane_path, **overrides):
    """Reproject the available orders in an earlier map without performing waveform fits."""
    raw = acquisition_path.read_bytes()
    packed = plane_path.read_bytes()
    acquisition = json.loads(raw)
    saved = json.loads(gzip.decompress(packed))
    if not isinstance(saved, dict) or saved.get('kind') != PLANE_KIND:
        raise ValueError('Expected a saved measured Compton plane')
    try:
        inputs = saved['input_sha256']
        if inputs['acquisition'] != hashlib.sha256(raw).hexdigest():
            raise ValueError('The saved plane is not bound to this acquisition')
        grid, model = saved['grid'], saved['model']
        if model['strip_pitch_mm'] != ResponseSettings().strip_pitch_mm:
            raise ValueError('The saved plane uses a different strip pitch')
        settings = dict(z_mm=grid['assumed_z_mm'], extent_mm=grid['extent_mm'], step_mm=grid['step_mm'],
                        sigma_deg=model['angular_nuisance_sigma_deg'],
                        plane_prior=model.get('plane_prior', DEFAULT_PLANE_PRIOR))
        settings.update(overrides)
        accounting = saved['triggers']
        selection = saved['selection']
        two_strip_count = selection['two_strip_triggers']
        geometry = model['geometry']
        records = _reuse_saved_events(acquisition, accounting)
    except (KeyError, TypeError, IndexError) as error:
        raise ValueError('Saved measured plane does not contain a valid trigger ledger and model') from error
    result = _project(acquisition, records, accounting, two_strip_count, **settings)
    if result['selection'] != selection:
        raise ValueError('The saved plane selection does not match the acquisition')
    result['model']['geometry'] = geometry
    result['input_sha256'] = dict(inputs, parent_plane=hashlib.sha256(packed).hexdigest())
    for key in ('calibration_bundle', 'fit_source_sha256'):
        if key in saved:
            result[key] = saved[key]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--acquisition', type=Path, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--calibration', type=Path, help='External center-waveform calibration archive (NPZ)')
    source.add_argument('--joint-fit', type=Path, help='Previously saved matching joint waveform fit (JSON)')
    source.add_argument('--from-plane', type=Path, help='Reuse measured cones and settings from a matching saved plane (JSON.gz)')
    parser.add_argument('--adc-windows', type=Path, help=f'ADC windows for --calibration, defaults to sibling {ADC_WINDOWS_FILE}')
    parser.add_argument('--output', type=Path, help=f'New compressed JSON map, defaults to sibling {PLANE_FILE} with --calibration')
    parser.add_argument('--plane-z-mm', type=float, help='Assumed plane in detector coordinates, required for a new fit')
    parser.add_argument('--extent-mm', type=float, help='Plane half-width in X and Y (new fit default: 120 mm)')
    parser.add_argument('--step-mm', type=float, help='Square-cell size (new fit default: 4 mm)')
    parser.add_argument('--sigma-deg', type=float, help='Nominal angular nuisance width (new fit default: 5 degrees)')
    parser.add_argument('--plane-prior', choices=PLANE_PRIORS,
                        help=f'Per-cell geometric prior on the finite plane grid (new fit default: {DEFAULT_PLANE_PRIOR})')
    args = parser.parse_args()
    if args.adc_windows and not args.calibration:
        parser.error('--adc-windows requires --calibration')
    if not args.output and args.joint_fit:
        parser.error('--output is required with --joint-fit')
    if not args.output and args.from_plane:
        parser.error('--output is required with --from-plane')
    if args.plane_z_mm is None and not args.from_plane:
        parser.error('--plane-z-mm is required with --joint-fit or --calibration')
    output = args.output or args.acquisition.with_name(PLANE_FILE)
    if output.exists():
        parser.error(f'Output already exists. Choose a new --output path or keep the existing result: {output}')
    settings = dict(z_mm=args.plane_z_mm, extent_mm=args.extent_mm, step_mm=args.step_mm, sigma_deg=args.sigma_deg,
                    plane_prior=args.plane_prior)
    settings = {key: value for key, value in settings.items() if value is not None}
    try:
        if args.from_plane:
            result = run_from_plane(args.acquisition, args.from_plane, **settings)
        elif args.calibration:
            windows = args.adc_windows or args.acquisition.with_name(ADC_WINDOWS_FILE)
            if not windows.is_file():
                raise ValueError(f'ADC windows unavailable: {windows}. Capture them in the acquisition or export them from its saved libraries.')
            result = run_from_adc(args.acquisition, windows, args.calibration, **settings)
        else:
            result = run(args.acquisition, args.joint_fit, **settings)
        encoded = json.dumps(result, allow_nan=False, separators=(',', ':')).encode('utf-8')
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open('xb') as target:
            target.write(gzip.compress(encoded+b'\n', mtime=0))
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(f'Saved plane result to {output}')
    print(json.dumps({key: {k: v for k, v in layer.items() if k != 'mass'} for key, layer in result['layers'].items()}))


if __name__ == '__main__':
    main()
