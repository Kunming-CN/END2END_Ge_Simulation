"""Test per-pixel nominal ADC depth curves with sealed GeGI waveforms."""

import argparse
from bisect import bisect_left
from collections import Counter, defaultdict
from hashlib import sha256
import json
import math
from pathlib import Path
import platform
from time import perf_counter

import numpy as np

import gegi_digital_readout as digital
import gegi_pulse_scan as scan
import gegi_pulse_stream as stream


ROOT = scan.ROOT
FULL = scan.FULL
ORIGINAL = ROOT / '.local/gegi-10m/pixel-calibration'
ORIGINAL_RUN_SHA = '3c91e38f640f7da0d0118427b4615e739a3f988cbcab751130b8e67a24bce35e'
ACQUISITION = ROOT / '.local/gegi-dual-source/cs37k-co37k-250ms-readout/report.json'
ACQUISITION_SHA = '4da85bf8544bea4ccac1a08d4e9d7ff91ca1debd8f2ddc64a6ee9d1f382052f7'
CAPTURES = (
    ('real_pixel_holdout', ROOT / '.local/gegi-digital-v1/two-site-position/results',
     'e239be0a97e7b0b99bc85842db9ee22b200bb0f43735fe743b9c0dc3dc2c708d'),
    ('x15_y07_holdout', ROOT / '.local/gegi-position-extension/x15-y07/results',
     '9ab0cd4936381423c97f342b96d8a02c94fea89f4edf39424471ca497d5cd231'),
)
ENERGY_KEV = 500.
ONSET_NS = 1000.
NOISE_SEED = 20261119
SOURCES = ('gegi_pixel_cfd_depth_study.py', 'gegi_pulse_scan.py', 'gegi_pulse_stream.py',
           'gegi_digital_readout.py', 'gegi_native_pair_readout.py', 'gegi_signal_reconstruction.py')


def acquisition_pixels(report):
    rows = [row for row in report['triggers'] if row.get('two_strip_pairings') is not None]
    census, pixels = Counter(), Counter()
    for row in rows:
        choices = [pair for pair in row['two_strip_pairings']['pairings'] if pair['energy_compatible']]
        if len(choices) != row['two_strip_pairings']['compatible_pairing_count']:
            raise ValueError('Energy-pairing census changed')
        census[len(choices)] += 1
        sites = {(site['x_contact_id'], site['y_contact_id']) for pair in choices for site in pair['sites']}
        pixels.update(sites)
    return dict(census), pixels


def bank_manifest(inputs, complete, refs):
    path = FULL / 'validation.jsonl'
    digest, entries, count = sha256(), {}, 0
    with path.open('rb') as source:
        for line in source:
            digest.update(line)
            row = json.loads(line)
            count += 1
            if row['record_ref'] in refs:
                if row['record_ref'] in entries:
                    raise ValueError('Duplicate selected native record in sealed manifest')
                entries[row['record_ref']] = row
    if (digest.hexdigest() != complete['validation_sha256']
            or count != complete['validated_records'] or entries.keys() != refs):
        raise ValueError('Sealed native bank roster changed')
    inputs.hashes[path.relative_to(ROOT).as_posix()] = digest.hexdigest()
    return entries


def saved_inputs(inputs):
    acquisition = inputs.read(ACQUISITION, ACQUISITION_SHA)
    census, pixels = acquisition_pixels(acquisition)
    complete = inputs.read(FULL / 'COMPLETE.json', scan.FULL_COMPLETE_SHA)
    request = inputs.read(FULL / 'bound-request.json', complete['request_sha256'])
    binding = inputs.read(FULL / 'identity.json', complete['bundle_identity_sha256'])
    bank_run = inputs.read(FULL / 'bank/run.json', complete['bank_run_sha256'])
    bank_identity = inputs.read(FULL / 'bank/identity.json', bank_run['artifacts']['identity.json'])
    original_run = inputs.read(ORIGINAL / 'run.json', ORIGINAL_RUN_SHA)
    original = inputs.read(ORIGINAL / 'identity.json', original_run['artifacts']['identity.json'])
    original_table = inputs.read(ORIGINAL / 'depth-calibration.json', original_run['artifacts']['depth-calibration.json'])
    identical = ('model_sha256', 'field_cache', 'field_precision_bits', 'channels', 'depth_mm',
                 'diagnostic_pixels', 'diagnostic_depth_mm', 'diagnostic_offsets_pitch_fraction')
    field = dict(model_sha256=request['model_sha256'], field_cache_sha256=request['field_cache']['sha256'],
                 field_precision_bits=request['field_precision_bits'])
    if (complete['status'] != 'completed_original_grid_full34_bank' or complete['selected_pair_mismatches']
            or binding['calibration_identity_sha256'] != bank_run['artifacts']['identity.json']
            or any(original[key] != bank_identity[key] for key in identical)
            or any(request[key] != bank_identity[key] for key in identical[:4])
            or any(source['original'][key] != value for source in acquisition['sources'] for key, value in field.items())
            or request['injection_energy_keV'] != ENERGY_KEV):
        raise ValueError('Independent waveforms, original grid or acquisition have different model/field identities')

    holdouts = []
    for label, folder, digest in CAPTURES:
        captured = inputs.read(folder / 'COMPLETE.json', digest)
        recipe = inputs.read(folder / 'bound-request.json', captured['request_sha256'])
        if (any(recipe[key] != request[key] for key in identical[:4])
                or recipe['injection_energy_keV'] != ENERGY_KEV):
            raise ValueError('Saved off-center capture uses different physics inputs')
        holdouts.extend((row, row, folder, captured['request_sha256'], label)
                        for row in captured['records'] if row['role'] == 'holdout')

    diagnostics = [row for row in request['grid'] if row['target_ref'].startswith('diagnostic-injections/')
                   and '/centre-' not in row['target_ref']]
    selected = set(pixels) | {tuple(row['contact_ids']) for row in diagnostics}
    selected.update(tuple(point['contact_ids']) for point, *_ in holdouts)
    centers = [row for row in request['grid'] if row['target_ref'].startswith('injections/')
               and tuple(row['contact_ids']) in selected]
    geometry = {channel['id']: channel for channel in request['channels']}
    depths = defaultdict(list)
    for point in centers:
        pixel = tuple(point['contact_ids'])
        if point['position_mm'][:2] != [geometry[cid]['strip_center_mm'] for cid in pixel]:
            raise ValueError('Training point differs from its strip center')
        depths[pixel].append(point['position_mm'][2])
    if depths.keys() != selected or any(sorted(zs) != original['depth_mm'] for zs in depths.values()):
        raise ValueError('Center-depth grid is incomplete for selected pixels')
    manifest = bank_manifest(inputs, complete, {point['target_ref'] for point in centers + diagnostics})
    def wrap(point, label):
        return (point, manifest[point['target_ref']], FULL / 'bank', binding['calibration_identity_sha256'], label)
    training = [wrap(point, 'pixel_center_fit') for point in centers]
    holdouts.extend(wrap(point, 'full34_off_center') for point in diagnostics)
    coords = [point['position_mm'] for point, *_ in holdouts]
    if len({tuple(xyz) for xyz in coords}) != len(coords):
        raise ValueError('Repeated position in independent validation')
    for point, *_ in holdouts:
        center_xy = [geometry[cid]['strip_center_mm'] for cid in point['contact_ids']]
        if math.dist(point['position_mm'][:2], center_xy) <= 1e-6:
            raise ValueError('Off-center validation overlaps the center-line fit')
    inventory = dict(energy_compatible_pairing_count=census, distinct_candidate_pixels=len(pixels),
                     full34_grid_points=complete['validated_records'], full34_captured_points=complete['full34_records'],
                     original_depth_table_pixels=len(original_table['pixels']), center_depth_grid_mm=original['depth_mm'],
                     original_diagnostic_pixels=original['diagnostic_pixels'], candidate_pixels=[
                         dict(contact_ids=pair, candidate_triggers=pixels[pair]) for pair in sorted(pixels)])
    return request['channels'], field, training, holdouts, pixels, inventory


def observe(pulse, wanted, noise_seed):
    axis, adc = stream.acquire([(pulse, ONSET_NS, 1.)], phase_ns=0., noise_seed=noise_seed,
                               window_end_ns=scan.WINDOW_END_NS)
    events = stream.reconstruct(axis, adc)['events']
    row = dict(adc_triggers=len(events))
    if len(events) != 1:
        return dict(row, measurement_status='missing_or_multiple_triggers')
    event = events[0]
    pair = event['contact_ids']
    row.update(measured_contact_ids=pair, trigger_time_ns=event['trigger_time_ns'],
               slow_energy_keV=event['slow_energy_keV'], pulse_flags=event['flags'])
    if pair != wanted:
        return dict(row, measurement_status='collecting_pixel_changed')
    if event['slow_energy_keV'] is None:
        return dict(row, measurement_status='single_pixel_energy_unavailable')
    collectors = [event['channels'][cid - 1] for cid in pair]
    cfd = [collector['preamp_cfd50_ns'] for collector in collectors]
    row.update(collector_cfd50_ns=cfd, collector_flags=[collector['flags'] for collector in collectors])
    if any(t is None or not math.isfinite(t) for t in cfd):
        return dict(row, measurement_status='collector_cfd_unavailable')
    return dict(row, measurement_status='measured', cfd_x_minus_y_ns=cfd[0] - cfd[1])


def measure(inputs, sample, channels, noise_seed):
    point, manifest, folder, identity, cohort = sample
    ref = folder / manifest['record_ref']
    row = dict(source_record=ref.relative_to(ROOT).as_posix(), record_sha256=manifest['record_sha256'],
               injected_contact_ids=point['contact_ids'], injected_xyz_mm=point['position_mm'],
               cohort=cohort, native_status=manifest['status'], noise_seed=noise_seed)
    if manifest['status'] != 'completed' or manifest['valid'] is not True:
        return dict(row, measurement_status='native_record_unqualified')
    record = inputs.read(ref, manifest['record_sha256'])
    payload, _ = scan.qualify(record, point, manifest, identity, ENERGY_KEV)
    signals = {signal['contact_id']: signal for signal in payload['channel_signals']}
    pulse = stream.prepare_native(signals, channels, terminal_complete=True)
    return row | observe(pulse, point['contact_ids'], noise_seed)


def fit_curve(rows):
    # The input grid is in increasing detector z. Skip unavailable outer knots,
    # but do not bridge holes or select a favorable monotone subrange.
    usable = [(index, row) for index, row in enumerate(rows) if row['measurement_status'] == 'measured']
    if len(usable) < 3:
        return dict(status='insufficient_center_knots', usable_knots=len(usable))
    indices, values = zip(*usable)
    if indices[-1] - indices[0] + 1 != len(indices):
        return dict(status='interior_center_knots_missing', usable_knots=len(usable))
    z = [row['injected_xyz_mm'][2] for row in values]
    delta = [row['cfd_x_minus_y_ns'] for row in values]
    steps = [b - a for a, b in zip(delta, delta[1:])]
    if not (all(step > 0 for step in steps) or all(step < 0 for step in steps)):
        return dict(status='nonmonotonic_center_timing', usable_knots=len(usable),
                    increasing_steps=sum(step > 0 for step in steps), decreasing_steps=sum(step < 0 for step in steps),
                    equal_steps=sum(step == 0 for step in steps))
    return dict(status='available', z_mm=z, cfd_x_minus_y_ns=delta,
                direction=1 if steps[0] > 0 else -1, usable_knots=len(usable),
                minimum_abs_ns_per_mm=min(abs(step)/(b-a) for step, a, b in zip(steps, z, z[1:])))


def estimate_depth(curve, measurement):
    if measurement['measurement_status'] != 'measured':
        return measurement['measurement_status'], None
    if curve['status'] != 'available':
        return curve['status'], None
    direction = curve['direction']
    observed = direction * measurement['cfd_x_minus_y_ns']
    knots = [direction * value for value in curve['cfd_x_minus_y_ns']]
    if not knots[0] <= observed <= knots[-1]:
        return 'outside_calibrated_cfd_range', None
    index = bisect_left(knots, observed)
    depths = curve['z_mm']
    if knots[index] == observed:
        return 'estimated', depths[index]
    fraction = (observed - knots[index-1]) / (knots[index] - knots[index-1])
    return 'estimated', depths[index-1] + fraction * (depths[index] - depths[index-1])


def summarize(rows):
    paired = [(row['estimated_z_mm'], row['injected_xyz_mm'][2]) for row in rows if row['estimated_z_mm'] is not None]
    def rms(values):
        return math.sqrt(math.fsum(value*value for value in values)/len(values)) if values else None
    return dict(intended=len(rows), estimated=len(paired), status_counts=dict(Counter(row['estimate_status'] for row in rows)),
                paired_cfd_rms_mm=rms([value-truth for value, truth in paired]),
                paired_midplane_rms_mm=rms([truth for _, truth in paired]),
                all_midplane_rms_mm=rms([row['injected_xyz_mm'][2] for row in rows]))


def run():
    start = perf_counter()
    paths = [ROOT / 'tools' / name for name in SOURCES]
    sources = {path.relative_to(ROOT).as_posix(): scan.digest(path) for path in paths}
    inputs = scan.Inputs()
    channels, field, training, holdouts, candidates, inventory = saved_inputs(inputs)
    measured_centers = defaultdict(list)
    for sample in training:
        row = measure(inputs, sample, channels, None)
        measured_centers[tuple(row['injected_contact_ids'])].append(row)
    curves = {pair: fit_curve(sorted(rows, key=lambda row: row['injected_xyz_mm'][2]))
              for pair, rows in measured_centers.items()}
    validation = []
    for sample in holdouts:
        ref = sample[2] / sample[1]['record_ref']
        seed = int.from_bytes(sha256(f'{NOISE_SEED}:{ref.relative_to(ROOT).as_posix()}'.encode()).digest()[:8], 'big')
        row = measure(inputs, sample, channels, seed)
        curve = curves[tuple(row['measured_contact_ids'])] if row['measurement_status'] == 'measured' else None
        status, estimated = estimate_depth(curve, row)
        validation.append(dict(row, estimate_status=status, estimated_z_mm=estimated))
    prioritized = [row for row in validation if tuple(row['injected_contact_ids']) in candidates]
    if sources != {path.relative_to(ROOT).as_posix(): scan.digest(path) for path in paths}:
        raise ValueError('Readout source changed during replay')
    return dict(
        kind='gegi_saved_pixel_cfd_depth_study_v1', status='completed',
        design=dict(fit='Strict monotone linear interpolation of contiguous center-depth timing knots, with at least three '
                        'measured centers. Leading and trailing unqualified knots are omitted. Interpolation abstains outside support.',
                    evaluation='Independent off-center point injections. Compare with z=0 on the same estimated points. '
                               'All unavailable native records, changed pixels, readout failures and range abstentions remain in denominators.',
                    scope='Isolated 500 keV simulated point pulses in one nominal detector field. Simultaneous deposits '
                          'and experimental detector resolution require independent validation.',
                    injected_energy_keV=ENERGY_KEV, observable='X collector CFD50 minus Y collector CFD50',
                    adc_sample_period_ns=stream.D._DT, adc_phase_ns=0, unit='ns', depth_unit='mm',
                    validation_noise_rms_V=digital._PROFILE['optional_noise_rms_V'], fit_noise_rms_V=0,
                    validation_noise_base_seed=NOISE_SEED),
        provenance=dict(**field, input_sha256=inputs.hashes, source_sha256=sources,
                        digital_profile_sha256=digital.PROFILE_SHA256, digital_timing_sha256=digital.TIMING_SHA256,
                        python=platform.python_version(), numpy=np.__version__),
        inventory=inventory, counts=dict(center_attempts=len(training), validation_attempts=len(holdouts),
            curve_statuses=dict(Counter(curve['status'] for curve in curves.values())),
            candidate_curve_statuses=dict(Counter(curves[pair]['status'] for pair in candidates)),
            candidate_pixels_with_off_center_records=len({tuple(row['injected_contact_ids']) for row in prioritized}),
            new_transport_calls=0, new_field_solves=0, new_drift_calls=0),
        summary=dict(all=summarize(validation), two_strip_site_pixels=summarize(prioritized),
                     by_cohort={label: summarize([row for row in validation if row['cohort'] == label])
                                for label in sorted({row['cohort'] for row in validation})}),
        pixels=[dict(contact_ids=pair, in_two_strip_site_set=pair in candidates, curve=curves[pair],
                     center_measurements=measured_centers[pair],
                     validation=summarize([row for row in validation if tuple(row['injected_contact_ids']) == pair]))
                for pair in sorted(curves)],
        validation=validation, total_elapsed_s=perf_counter()-start,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    target = parser.parse_args().output.resolve()
    if not target.is_relative_to(ROOT / '.local') or target.exists():
        raise ValueError('Choose a new output path under .local')
    report = run()
    data = json.dumps(report, allow_nan=False, separators=(',', ':')) + '\n'
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('x', encoding='utf-8', newline='\n') as output:
        output.write(data)
    print(json.dumps({key: report[key] for key in ('counts', 'summary', 'total_elapsed_s')}, indent=2))


if __name__ == '__main__':
    main()
