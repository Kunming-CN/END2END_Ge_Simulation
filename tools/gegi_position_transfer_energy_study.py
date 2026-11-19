"""Check low-energy ADC transfer using only the validated hotspot waveforms."""

import argparse
from itertools import product
import json
from pathlib import Path

import gegi_capture_position_target as target
import gegi_continuous_position_study as continuous
import gegi_position_transfer_study as transfer
import gegi_pulse_scan as scan
import gegi_substrip as substrip


ENERGIES_KEV = (35, 64, 150, 350, 600)
SPARSE_ENERGIES_KEV = (64, 150, 350, 600)
SOURCES = (*transfer.SOURCES, 'gegi_capture_position_target.py', 'gegi_position_transfer_energy_study.py')


def run(sparse=False):
    inputs = scan.Inputs()
    source_hashes = {f'tools/{name}': scan.digest(scan.ROOT / 'tools' / name) for name in SOURCES}
    calibration = substrip.load_calibration()
    saved = inputs.read(target.SAVED, target.SAVED_SHA256)
    points, channels, identity = transfer.load_points(inputs, calibration)
    if sparse:
        points = [p for p in points if p['group'] == 'cross_pixel_holdout']
        energies = SPARSE_ENERGIES_KEV
    else:
        points = [p for p in points if p['group'] == 'x09_y09_off_center']
        energies = ENERGIES_KEV
        folder = target.OUT/'results'
        complete = inputs.read(folder/'COMPLETE.json', scan.digest(folder/'COMPLETE.json'))
        request = inputs.read(folder/'bound-request.json', complete['request_sha256'])
        if (complete['status'] != target.STATUS or complete['native_injection_attempts'] != 16
                or transfer.identity_of(request) != identity or request['channels'] != channels
                or request['injection_energy_keV'] != transfer.ENERGY_KEV):
            raise ValueError('The completed hotspot capture differs from the frozen transfer scope')
        points.extend(transfer.load_record(inputs, folder, row, row, complete['request_sha256'], channels,
                                           'x15_y07_holdout') for row in complete['records'])
    cases = []
    for energy, offset, seed in product(energies, continuous.ONSET_OFFSETS_NS, (None, continuous.NOMINAL_SEED)):
        onsets = [continuous.FIRST_ONSET_NS + i * continuous.SPACING_NS + offset for i in range(len(points))]
        result = continuous.replay([(p['native'], t, energy / transfer.ENERGY_KEV)
                                    for p, t in zip(points, onsets, strict=True)], seed)
        indices, extra = continuous.match_windows(onsets, result['events'])
        rows = []
        for p, window in zip(points, indices, strict=True):
            baseline = continuous.evaluate_point(p, window, result['events'], calibration, channels, identity)
            rows.append({k: v for k, v in p.items() if k != 'native'} | transfer.predict(saved['template'], p, baseline))
        cases.append({'energy_keV': energy, 'offset_ns': offset, 'noise_seed': seed,
                      'trigger_count': len(result['events']), 'extra_trigger_indices': extra,
                      'adc_sha256': result['adc_sha256'],
                      'by_group': {g: transfer.summarize([r for r in rows if r['group'] == g])
                                   for g in sorted({r['group'] for r in rows})},
                      'by_pair': {f'{x}:{y}': transfer.summarize(
                          [r for r in rows if r['truth_contact_ids'] == [x, y]])
                          for x, y in sorted({tuple(r['truth_contact_ids']) for r in rows})},
                      'rows': rows})
    if source_hashes != {ref: scan.digest(scan.ROOT / ref) for ref in source_hashes}:
        raise RuntimeError('Scaled transfer source changed during replay')
    return {
        'kind': 'gegi_hotspot_position_transfer_energy_v1', 'injection_energies_keV': energies,
        'scope': 'Existing 500 keV same-field native waveforms linearly scaled before digitization. The measured '
                 'energies in the dual-source reports motivated the fixed electronic test points. Transfer '
                 'templates, trigger thresholds and feature qualification are unchanged.',
        'field_identity': identity, 'template_report_sha256': target.SAVED_SHA256,
        'input_sha256': inputs.hashes, 'source_sha256': source_hashes,
        'native_records': len(points), 'new_transport_calls': 0, 'new_drift_calls': 0, 'new_field_solves': 0,
        'cases': cases,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--sparse', action='store_true', help='Score the seven extra four-point pixel holdouts')
    args = parser.parse_args()
    path = args.output
    if path.exists():
        raise FileExistsError(path)
    result = run(args.sparse)
    with path.open('x', encoding='utf-8', newline='\n') as output:
        json.dump(result, output, allow_nan=False, separators=(',', ':'))
        output.write('\n')


if __name__ == '__main__':
    main()
