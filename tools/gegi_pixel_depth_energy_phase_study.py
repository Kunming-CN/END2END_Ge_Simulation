"""Test apparent depth across energy scales and ADC phases on sealed waveforms."""

import argparse
from itertools import product
import json
import math
from pathlib import Path
import platform
from time import perf_counter

import numpy as np

import gegi_pixel_cfd_depth_study as prior_study
import gegi_pixel_depth as depth


ROOT = prior_study.ROOT
PRIOR = ROOT / '.local/gegi-pixel-cfd-depth/study.json'
PRIOR_SHA = 'fbf5f9eb76bee6c82f256de3515c350df4c350539c8f5062a7fd0c965794a399'
CALIBRATION_SHA = 'd8f34e1a2b012deba723d92c3e1ce509e672b51770fb8b55d9e14ac645b7b80d'
ENERGIES_KEV = (35, 100, 250, 500, 662, 1250)
PHASES_NS = (0, 10)
REFERENCE = (500, 0)
SPOT_INDICES = (0, 26, 53, 80, 107, 134, 161, 187)


def assess_measurement(row, calibration, stamps):
    if row['measurement_status'] != 'measured':
        return dict(estimate_status=row['measurement_status'], estimated_z_mm=None)
    measured = depth.estimate_depth(calibration, *row['measured_contact_ids'], *row['collector_cfd50_ns'], **stamps)
    return dict(estimate_status=measured['status'], estimated_z_mm=measured['apparent_depth_mm'],
                cfd_x_minus_y_ns=measured['cfd_x_minus_y_ns'])


def measure(pulse, expected_pixel, noise_seed, energy, phase):
    stream = prior_study.stream
    axis, adc = stream.acquire([(pulse, prior_study.ONSET_NS, energy / prior_study.ENERGY_KEV)],
                               phase_ns=phase, noise_seed=noise_seed,
                               window_end_ns=prior_study.scan.WINDOW_END_NS + phase)
    events = stream.reconstruct(axis, adc)['events']
    row = dict(adc_triggers=len(events))
    if len(events) != 1:
        return dict(row, measurement_status='multiple_triggers' if events else 'missing_trigger')
    event = events[0]
    pair = event['contact_ids']
    row.update(measured_contact_ids=pair, trigger_time_ns=event['trigger_time_ns'],
               slow_energy_keV=event['slow_energy_keV'], pulse_flags=event['flags'])
    if pair is None:
        return dict(row, measurement_status='collecting_pair_unavailable')
    if pair != expected_pixel:
        return dict(row, measurement_status='collecting_pixel_changed')
    if event['slow_energy_keV'] is None:
        return dict(row, measurement_status='single_pixel_energy_unavailable')
    channels = [event['channels'][cid-1] for cid in pair]
    cfd = [channel['preamp_cfd50_ns'] for channel in channels]
    row.update(collector_cfd50_ns=cfd, collector_flags=[channel['flags'] for channel in channels])
    return dict(row, measurement_status='measured' if all(depth.finite(value) for value in cfd)
                else 'collector_cfd_unavailable')


def common_depth_difference(rows, reference):
    """Keep energy and phase comparisons on the same measurable points."""
    changes = [row['estimated_z_mm'] - baseline['estimated_z_mm']
               for row, baseline in zip(rows, reference, strict=True)
               if row['estimated_z_mm'] is not None and baseline['estimated_z_mm'] is not None]
    count = len(changes)
    return dict(common_estimates=count, rms_difference_mm=(
        math.sqrt(math.fsum(value*value for value in changes)/count) if count else None))


def run():
    start = perf_counter()
    scan = prior_study.scan
    inputs = scan.Inputs()
    prior = inputs.read(PRIOR, PRIOR_SHA)
    sources = {**prior['provenance']['source_sha256'],
               'tools/gegi_pixel_depth.py': scan.digest(ROOT/'tools/gegi_pixel_depth.py'),
               'tools/gegi_pixel_depth_energy_phase_study.py': scan.digest(Path(__file__))}
    def unchanged_sources():
        return all(scan.digest(ROOT / ref) == value for ref, value in sources.items())
    calibration = depth.load_calibration()
    if (calibration['calibration_sha256'] != CALIBRATION_SHA or not unchanged_sources()
            or calibration['provenance']['prior_adc_study_sha256'] != PRIOR_SHA):
        raise ValueError('The sealed apparent-depth table, reference replay or source code changed')
    inputs.hashes[depth.CALIBRATION_PATH.relative_to(ROOT).as_posix()] = CALIBRATION_SHA
    channels, field, _, saved_points, candidates, _ = prior_study.saved_inputs(inputs)
    stamps = dict(source_identity=field, digital_profile_sha256=prior_study.digital.PROFILE_SHA256,
                  digital_timing_sha256=prior_study.digital.TIMING_SHA256)
    archived = prior['validation']
    if len(archived) != 188 or len(saved_points) != len(archived):
        raise ValueError('Expected the original 188 independent off-center points')

    cases = {(energy, phase): [] for energy, phase in product(ENERGIES_KEV, PHASES_NS)}
    roster = []
    fresh_checks = 0
    for index, (sample, baseline) in enumerate(zip(saved_points, archived, strict=True)):
        point, manifest, folder, identity, cohort = sample
        path = folder / manifest['record_ref']
        seed = baseline['noise_seed']
        card = dict(source_record=path.relative_to(ROOT).as_posix(), record_sha256=manifest['record_sha256'],
                    injected_xyz_mm=point['position_mm'], injected_contact_ids=point['contact_ids'],
                    cohort=cohort, noise_seed=seed, native_status=manifest['status'])
        if any(baseline[key] != value for key, value in card.items()):
            raise ValueError('Independent point membership differs from the original replay')
        roster.append(card)

        reference = {key: value for key, value in baseline.items() if key not in card}
        estimate = assess_measurement(reference, calibration, stamps)
        if any(reference[key] != value for key, value in estimate.items()):
            raise ValueError('Frozen apparent-depth estimator differs from the 500 keV reference')
        if manifest['status'] == 'completed' and manifest['valid'] is True:
            checkpoint = inputs.read(path, manifest['record_sha256'])
            raw, _ = scan.qualify(checkpoint, point, manifest, identity, prior_study.ENERGY_KEV)
            signals = {signal['contact_id']: signal for signal in raw['channel_signals']}
            pulse = prior_study.stream.prepare_native(signals, channels, terminal_complete=True)
        else:
            pulse = None
        if index in SPOT_INDICES:
            check = measure(pulse, point['contact_ids'], seed, *REFERENCE)
            if any(reference[key] != value for key, value in check.items()):
                raise ValueError('Fresh 500 keV phase-zero ADC replay differs from the original measurements')
            fresh_checks += 1
        for case, rows in cases.items():
            if case == REFERENCE:
                rows.append(reference)
                continue
            measured = (measure(pulse, point['contact_ids'], seed, *case) if pulse is not None else
                        dict(measurement_status='native_record_unqualified'))
            rows.append(measured | assess_measurement(measured, calibration, stamps))
    if not unchanged_sources() or depth.load_calibration()['calibration_sha256'] != CALIBRATION_SHA:
        raise ValueError('Readout source or calibration changed during replay')

    records = []
    for (energy, phase), rows in cases.items():
        merged = [dict(row, injected_xyz_mm=point['injected_xyz_mm'])
                  for row, point in zip(rows, roster, strict=True)]
        candidate_rows = [row for row, point in zip(merged, roster, strict=True)
                          if tuple(point['injected_contact_ids']) in candidates]
        records.append(dict(energy_keV=energy, adc_phase_ns=phase, reused_measurements=(energy, phase) == REFERENCE,
                            summary=prior_study.summarize(merged), two_strip_site_pixels=prior_study.summarize(candidate_rows),
                            same_phase_relative_to_500_keV=common_depth_difference(rows, cases[(500, phase)]), rows=rows))
    summaries = {energy: common_depth_difference(cases[(energy, PHASES_NS[1])], cases[(energy, PHASES_NS[0])])
                 for energy in ENERGIES_KEV}
    return dict(
        kind='gegi_saved_apparent_depth_energy_phase_v1', status='completed',
        design=dict(energies_keV=ENERGIES_KEV, phases_ns=PHASES_NS, adc_sample_period_ns=prior_study.digital._DT,
                    injected_reference_energy_keV=prior_study.ENERGY_KEV, noise_rms_V=prior_study.digital._PROFILE['optional_noise_rms_V'],
                    scale='Scale each same-field isolated 500 keV saved pulse linearly before nominal ADC filtering and quantization.',
                    noise='Use the archived seed for each point in every case. Shifting the window end with the phase preserves '
                          'each channel’s generated noise sequence by sample index while shifting its sample times.',
                    trigger_profile='standard', reference_onset_ns=prior_study.ONSET_NS,
                    scope='Frozen center calibration and independent off-center simulated point responses. '
                          'Energy rescaling tests the readout and timing transfer for these waveforms. '
                          'Energy-dependent carrier physics and overlapping deposits require separate tests.'),
        counts=dict(off_center_points=len(roster), cases=len(cases), opportunities=len(roster)*len(cases),
                    reused_phase_zero_500_keV_measurements=len(roster), fresh_phase_zero_500_keV_spot_checks=fresh_checks,
                    new_transport_calls=0, new_field_solves=0, new_drift_calls=0),
        provenance=dict(input_sha256=inputs.hashes, source_sha256=sources, calibration_sha256=CALIBRATION_SHA,
                        python=platform.python_version(), numpy=np.__version__, **stamps),
        point_roster=roster, cases=records, common_phase_difference_by_energy=summaries,
        elapsed_s=perf_counter()-start,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    output = parser.parse_args().output.resolve()
    if not output.is_relative_to(ROOT/'.local') or output.exists():
        raise ValueError('Choose a new result file under .local')
    report = run()
    payload = json.dumps(report, allow_nan=False, separators=(',', ':')) + '\n'
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(payload)
    print(json.dumps(dict(counts=report['counts'],
                          cases=[{key: row[key] for key in ('energy_keV', 'adc_phase_ns', 'summary')}
                                 for row in report['cases']], elapsed_s=report['elapsed_s']), indent=2))


if __name__ == '__main__':
    main()
