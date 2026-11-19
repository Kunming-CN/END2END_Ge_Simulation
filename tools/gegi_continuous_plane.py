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

from gegi_imaging import cone
from gegi_joint_imaging import ResponseSettings, candidate_response, plane_grid, prepare_events, spectral_membership


LINE_ENERGIES_KEV = (661.657, 1173.228, 1332.492)


def measured_events(acquisition, joint_fit):
    """Read measured energies, strip identities, and successful center waveform positions."""
    triggers = acquisition['triggers']
    selected = [(i, trigger) for i, trigger in enumerate(triggers, 1) if trigger.get('two_strip_pairings') is not None]
    records, accounting = [], []
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
        for pair in measured:
            fit = fits[pair['index']]
            sites = pair['sites']
            cells = [[s['x_contact_id'], s['y_contact_id']] for s in sites]
            if cells != fit['cells'] or pair['energy_compatible'] != fit['energy_compatible']:
                raise ValueError('Saved waveform strip identities differ from the measured energy pairing')
            if not pair['energy_compatible']:
                continue
            orders = [tuple(order['site_index_order']) for order in pair['compton_orders']
                      if order['kinematically_allowed']]
            if len(set(orders)) != len(orders) or set(orders) - {(0, 1), (1, 0)}:
                raise ValueError('Allowed orders must be unique orders of the two measured sites')
            waveform = fit['fit'].get('fits', {}).get('waveform', {}).get('center')
            pair_ledger = dict(index=pair['index'], cells=cells, site_energies_keV=[s['energy_keV'] for s in sites],
                               nominal_mass=1/compatible, orders=[])
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
                    item.update(status='available', **{key: geometry[key] for key in
                                ('vertex_mm', 'axis', 'half_angle_deg', 'site_separation_mm')})
                    record['candidates'].append(dict(geometry, prior_weight=item['nominal_mass']))
                pair_ledger['orders'].append(item)
        records.append(record)
        accounting.append(ledger)
    return records, accounting


def reconstruct(acquisition, joint_fit, *, z_mm, extent_mm=120., step_mm=4., sigma_deg=5.):
    settings = ResponseSettings(angular_nuisance_sigma_deg=sigma_deg)
    settings.validate()
    ticks, points = plane_grid(extent_mm, step_mm, z_mm)
    records, accounting = measured_events(acquisition, joint_fit)
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
            or len(events) != joint_fit['two_strip_triggers']):
        raise ValueError('Measured event selection totals do not close')
    return dict(
        kind='gegi_continuous_measured_plane_backprojection_v1',
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
                                 'cone is normalized over the displayed plane cells under a uniform planar prior '
                                 'before multiplying by its nominal mass. Values are nominal trigger units per cell.',
                   limits='Sparse conditional backprojection. Changing the assumed plane or displayed footprint changes '
                          'the map. Energy and depth resolution, Doppler response and detector sensitivity are uncalibrated. '
                          'Peaks cannot establish emission activity, source count, or distance.'),
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--acquisition', type=Path, required=True)
    parser.add_argument('--joint-fit', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='New compressed JSON plane map and trigger ledger')
    parser.add_argument('--plane-z-mm', type=float, required=True, help='Assumed plane in detector coordinates')
    parser.add_argument('--extent-mm', type=float, default=120., help='Plane half-width in each of X and Y')
    parser.add_argument('--step-mm', type=float, default=4., help='Square-cell size in mm')
    parser.add_argument('--sigma-deg', type=float, default=5., help='Nominal angular nuisance width')
    args = parser.parse_args()
    result = run(args.acquisition, args.joint_fit, z_mm=args.plane_z_mm, extent_mm=args.extent_mm,
                 step_mm=args.step_mm, sigma_deg=args.sigma_deg)
    encoded = json.dumps(result, allow_nan=False, separators=(',', ':')).encode('utf-8')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('xb') as target:
        target.write(gzip.compress(encoded+b'\n', mtime=0))
    print(json.dumps({key: {k: v for k, v in layer.items() if k != 'mass'} for key, layer in result['layers'].items()}))


if __name__ == '__main__':
    main()
