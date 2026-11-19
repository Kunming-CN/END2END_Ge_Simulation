"""Regenerate portable apparent-depth curves from sealed GeGI ADC waveform inputs."""

import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import platform
from time import perf_counter

import numpy as np

import gegi_pixel_cfd_depth_study as study
import gegi_pixel_depth as depth


ROOT = study.ROOT
PRIOR = ROOT / '.local/gegi-pixel-cfd-depth/study.json'
PRIOR_SHA = 'fbf5f9eb76bee6c82f256de3515c350df4c350539c8f5062a7fd0c965794a399'
ALL_PIXELS = {(x, y) for x in depth.X_IDS for y in depth.Y_IDS}


def json_bytes(data):
    return (json.dumps(data, allow_nan=False, sort_keys=True, separators=(',', ':')) + '\n').encode('utf-8')


def frozen_curves(prior):
    curves = {}
    for entry in prior['pixels']:
        pixel = tuple(entry['contact_ids'])
        if pixel in curves or pixel not in ALL_PIXELS:
            raise ValueError('Invalid saved center-curve census')
        curve = dict(entry['curve'])
        if entry['validation']['intended']:
            curve['off_center_check'] = entry['validation']
        curves[pixel] = curve
    return curves


def new_center_measurements(inputs, complete, binding, request, pixels):
    channels = request['channels']
    geometry = {channel['id']: channel for channel in channels}
    points = [point for point in request['grid'] if point['target_ref'].startswith('injections/')
              and tuple(point['contact_ids']) in pixels]
    manifest = study.bank_manifest(inputs, complete, {point['target_ref'] for point in points})
    rows = defaultdict(list)
    for point in points:
        pixel = tuple(point['contact_ids'])
        if point['position_mm'][:2] != [geometry[cid]['strip_center_mm'] for cid in pixel]:
            raise ValueError('Saved center coordinate differs from its collector strips')
        sample = (point, manifest[point['target_ref']], study.FULL / 'bank',
                  binding['calibration_identity_sha256'], 'pixel_center_fit')
        rows[pixel].append(study.measure(inputs, sample, channels, None))
    return rows


def regenerate():
    started = perf_counter()
    inputs = study.scan.Inputs()
    prior = inputs.read(PRIOR, PRIOR_SHA)
    sources = dict(prior['provenance']['source_sha256'])
    sources.update({f'tools/{name}': study.scan.digest(ROOT / 'tools' / name) for name in
                    ('gegi_build_pixel_depth_calibration.py', 'gegi_pixel_depth.py')})
    def sources_unchanged():
        return all(study.scan.digest(ROOT / name) == expected for name, expected in sources.items())
    if not sources_unchanged():
        raise ValueError('Nominal ADC center-curve implementation differs from the verified replay')

    complete = inputs.read(study.FULL / 'COMPLETE.json', study.scan.FULL_COMPLETE_SHA)
    request = inputs.read(study.FULL / 'bound-request.json', complete['request_sha256'])
    binding = inputs.read(study.FULL / 'identity.json', complete['bundle_identity_sha256'])
    field = dict(model_sha256=request['model_sha256'], field_cache_sha256=request['field_cache']['sha256'],
                 field_precision_bits=request['field_precision_bits'])
    if (any(prior['provenance'][key] != value for key, value in field.items())
            or prior['provenance']['digital_profile_sha256'] != study.digital.PROFILE_SHA256
            or prior['provenance']['digital_timing_sha256'] != study.digital.TIMING_SHA256
            or request['injection_energy_keV'] != study.ENERGY_KEV or complete['selected_pair_mismatches']):
        raise ValueError('Sealed bank and original apparent-depth study identities differ')

    curves = frozen_curves(prior)
    reused = len(curves)
    centers = new_center_measurements(inputs, complete, binding, request, ALL_PIXELS - curves.keys())
    grid = prior['inventory']['center_depth_grid_mm']
    for pixel, rows in centers.items():
        rows.sort(key=lambda row: row['injected_xyz_mm'][2])
        if [row['injected_xyz_mm'][2] for row in rows] != grid:
            raise ValueError('Center-depth grid is incomplete for pixel ' + str(pixel))
        curves[pixel] = study.fit_curve(rows)
    if not sources_unchanged():
        raise ValueError('Nominal ADC implementation changed during replay')

    status = dict(Counter(curve['status'] for curve in curves.values()))
    validation = {**prior['summary']['all'], 'pixels_checked': sum('off_center_check' in c for c in curves.values()),
                  'candidate_pixels': prior['summary']['two_strip_site_pixels']}
    calibration = dict(
        kind=depth.KIND, **field, digital_profile_sha256=study.digital.PROFILE_SHA256,
        digital_timing_sha256=study.digital.TIMING_SHA256, cfd_definition=depth.CFD_DEFINITION,
        difference_unit='ns', depth_unit='mm', center_depth_grid_mm=grid, reference_energy_keV=study.ENERGY_KEV,
        adc_sample_period_ns=study.digital._DT, fit_adc_phase_ns=0, fit_noise_rms_V=0,
        off_center_validation=validation, curve_status_counts=status,
        scope='Apparent depth from isolated, simulated 500 keV waveform centers in one detector field. '
              'The saved off-center checks cover the listed pixels. Overlapping deposits and measured detector response need separate calibration.',
        pixels={f'{x}:{y}': curves[x, y] for x, y in sorted(curves)},
        provenance=dict(full34_bank_complete_sha256=study.scan.FULL_COMPLETE_SHA,
                        full34_bank_validation_sha256=complete['validation_sha256'],
                        prior_adc_study_sha256=PRIOR_SHA, source_sha256=sources),
    )
    depth.validate_calibration(calibration)
    report = dict(
        kind='gegi_all_pixel_cfd_depth_build_v1', calibration_sha256=sha256(json_bytes(calibration)).hexdigest(),
        counts=dict(reused_pixel_curves=reused, reused_center_points=prior['counts']['center_attempts'],
                    new_center_points=sum(len(rows) for rows in centers.values()), curve_statuses=status,
                    new_transport_calls=0, new_field_solves=0, new_drift_calls=0),
        extended_pixels=[dict(contact_ids=pixel, curve_status=curves[pixel]['status'], center_measurements=centers[pixel])
                         for pixel in sorted(centers)],
        off_center_validation=validation, input_sha256=inputs.hashes, source_sha256=sources,
        python=platform.python_version(), numpy=np.__version__, elapsed_s=perf_counter() - started,
    )
    return calibration, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    output, evidence = args.output.resolve(), args.evidence.resolve()
    if (not output.is_relative_to(ROOT) or not evidence.is_relative_to(ROOT / '.local')
            or output == evidence or output.exists() or evidence.exists()):
        raise ValueError('Choose a new table path in the project and a new evidence path under .local')
    calibration, report = regenerate()
    for path, value in ((evidence, report), (output, calibration)):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as file:
            file.write(json_bytes(value))
    print(json.dumps({key: report[key] for key in ('counts', 'calibration_sha256', 'elapsed_s')}, indent=2))


if __name__ == '__main__':
    main()
