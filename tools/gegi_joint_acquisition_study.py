"""Fit real simulated two-strip acquisition windows, then score against saved transport."""

import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
from time import perf_counter

import numpy as np

from gegi_event_store import encoded, sha
from gegi_joint_two_site import SAMPLE_NS, fit_pairing
import gegi_joint_two_site_study as design
import gegi_two_site_cfd_study as checks


ROOT = design.ROOT
REPORT = ROOT / '.local/gegi-dual-source/cs37k-co37k-250ms-depth/report.json'
WINDOWS = design.LOCAL / 'cs37k-co37k-250ms-adc.npz'
REFERENCE = ROOT / '.local/gegi-continuous-pairing/study.json'
REFERENCE_SHA = '62c56967d2ea05984d0f94dff818acd0fd71361aa950086eea748167e0352735'


def compare(positions, targets):
    return dict(depth_errors_mm=[a[2] - b[2] for a, b in zip(positions, targets, strict=True)],
                transverse_errors_mm=[math.dist(a[:2], b[:2]) for a, b in zip(positions, targets, strict=True)],
                axis_error_deg=checks.angle_error(checks.axis_between(*positions), checks.axis_between(*targets)))


def scores(fitted, reference, geometry):
    match = reference['comparison']
    if match is None or fitted['index'] != match.get('truth_pairing_index'):
        return None
    sites = {tuple(s['cell']): s for s in reference['reference']['sites_in_birth_order']}
    cells = fitted['cells']
    centers = [[geometry[x]['strip_center_mm'], geometry[y]['strip_center_mm'], 0.] for x, y in cells]
    predictions = {'strip_centers_z0': centers}
    depths = fitted['apparent_depths_mm']
    if all(z is not None for z in depths):
        predictions['strip_centers_cfd'] = [xy[:2] + [z] for xy, z in zip(centers, depths)]
    for mode, models in fitted['fit'].get('fits', {}).items():
        for name, model in models.items():
            if model['optimizer_success']:
                predictions[f'{mode}_{name}'] = model['positions_mm']
    return {label: {method: compare(pos, [sites[tuple(cell)][coordinate] for cell in cells])
                    for method, pos in predictions.items()}
            for label, coordinate in [('charge_centroid', 'deposit_centroid_mm'), ('interaction_birth', 'birth_position_mm')]}


def summarize(rows):
    grouped = defaultdict(list)
    for row in rows:
        for pairing in row['pairings']:
            for target, methods in (pairing.get('score') or {}).items():
                for method, errors in methods.items():
                    grouped[target, method].append(errors)
    out = {}
    for (target, method), records in grouped.items():
        metrics = {}
        for k in ('axis_error_deg', 'depth_errors_mm', 'transverse_errors_mm'):
            values = [v for row in records for v in (row[k] if isinstance(row[k], list) else [row[k]]) if v is not None]
            metrics[k] = dict(n=len(values), rms=math.sqrt(math.fsum(v*v for v in values) / len(values)) if values else None)
        out.setdefault(target, {})[method] = metrics
    return out


def run():
    started = perf_counter()
    inputs = checks.scan.Inputs()
    acquisition = inputs.read(REPORT, '0c5111b47ab7f84f1ddf0514b04484c8a86e167cf179111f79bb0d0d8fed453a')
    report_sha = inputs.hashes[REPORT.relative_to(ROOT).as_posix()]
    receipt = acquisition['receipt']
    calibration = inputs.read(checks.CURVES, checks.CURVES_SHA)['provenance']
    scales = inputs.read(design.SCALES, design.SCALES_SHA)['controls']['group_rms_scales']
    bank = inputs.read(checks.scan.FULL/'COMPLETE.json', checks.scan.FULL_COMPLETE_SHA)
    channels = inputs.read(checks.scan.FULL/'bound-request.json', bank['request_sha256'])['channels']
    records = [r for r in acquisition['triggers'] if 'two_strip_pairings' in r]
    cells = { (s['x_contact_id'], s['y_contact_id']) for r in records for p in r['two_strip_pairings']['pairings']
             if p['energy_compatible'] for s in p['sites']}
    templates = design.load_templates(inputs, cells, calibration, channels, set())
    hashes = {p.name: sha(p.read_bytes()) for p in (Path(__file__), Path(design.__file__),
              Path(design.__file__).with_name('gegi_joint_two_site.py'))}
    fits = []
    with np.load(WINDOWS, allow_pickle=False) as data:
        if (str(data['report_sha256']) != report_sha or str(data['known_component_adc_sha256']) != receipt['known_component_adc_sha256']
                or not np.array_equal(data['relative_time_ns'], SAMPLE_NS)
                or not np.array_equal(data['contact_ids'], [c['id'] for c in channels])
                or not np.array_equal(data['trigger_time_ns'], [r['trigger_time_ns'] for r in records])):
            raise ValueError('ADC windows, channel order, or acquisition identity differ')
        windows = dict(zip(data['two_strip_ordinal'].tolist(), data['adc_codes'] * float(data['volts_per_code']), strict=True))
        statuses = data['window_status'].tolist()
    for ordinal, record in enumerate(records, 1):
        event = record['two_strip_pairings']
        row = dict(ordinal=ordinal, time_ns=record['trigger_time_ns'], window_status=statuses[ordinal-1],
                   flags=event['flags'], pairings=[])
        for pairing in event['pairings']:
            fit = fit_pairing(pairing, event['collectors'], templates, scales, local_adc_volts=windows.get(ordinal))
            row['pairings'].append(dict(index=pairing['index'], energy_compatible=pairing['energy_compatible'],
                cells=[[s['x_contact_id'], s['y_contact_id']] for s in pairing['sites']],
                apparent_depths_mm=[s['apparent_depth_mm'] for s in pairing.get('pixel_depths', [])],
                compton_orders=pairing['compton_orders'], fit=fit))
        fits.append(row)
    # Open the history only after every measured fit has been made.
    truth = inputs.read(REFERENCE, REFERENCE_SHA)
    if truth['adc_sha256'] != receipt['known_component_adc_sha256']:
        raise ValueError('Truth association belongs to another acquisition')
    geometry = {c['id']: c for c in channels}
    for row, reference in zip(fits, truth['candidates'], strict=True):
        if row['time_ns'] != reference['trigger_time_ns']:
            raise ValueError('Truth association does not match the measured trigger')
        row['reference_groups'] = reference['deposit_groups']
        for pairing in row['pairings']:
            pairing['score'] = scores(pairing, reference, geometry)
    return dict(kind='gegi_joint_continuous_acquisition_study_v1', qualified_triggers=truth['qualified_trigger_denominator'],
                two_strip_triggers=len(records), fitted_status_counts=Counter(p['fit']['status'] for r in fits for p in r['pairings']),
                score_scope='Repeated source-library occurrences. Both orders retained. Comparisons use the same X/Y cell ordering.',
                timing_scope='Simultaneous templates at a shared onset, measured slow energies and local voltage tails.',
                input_sha256=inputs.hashes, adc_windows_sha256=sha(WINDOWS.read_bytes()), source_sha256=hashes,
                elapsed_s=perf_counter()-started, summary=summarize(fits), candidates=fits)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    result = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('xb') as target:
        target.write(encoded(result) + b'\n')
    print(json.dumps({key: result[key] for key in ('two_strip_triggers', 'fitted_status_counts', 'elapsed_s', 'summary')}))


if __name__ == '__main__':
    main()
