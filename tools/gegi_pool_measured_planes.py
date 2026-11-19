"""Add four independent measured GeGI plane blocks without reweighting events."""

import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path

import numpy as np

from gegi_joint_imaging import blind_peaks


RECEIPT_KEYS = ('digital_profile_sha256', 'digital_timing_sha256', 'known_component_adc_sha256')
LAYER_COUNTS = ('triggers', 'triggers_with_geometry', 'allowed_hypotheses', 'hypotheses')
LAYER_MASS = ('projected_mass', 'unresolved_mass')
LIVE_KEYS = ('clock_live_time_ns', 'qualified_adc_live_time_ns')
SELECTION_COUNTS = ('qualified_triggers', 'qualified_energies', 'triggers_without_energy', 'two_strip_triggers',
                    'two_strip_triggers_without_compatible_pairing', 'two_strip_triggers_with_two_compatible_pairings')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def block(folder):
    raw, packed = (folder/'report.json').read_bytes(), (folder/'plane.json.gz').read_bytes()
    report, plane = json.loads(raw), json.loads(gzip.decompress(packed))
    require(report['kind'] == 'gegi_dual_source_acquisition_v1' and report['status'] == 'completed'
            and plane['kind'] == 'gegi_continuous_measured_plane_backprojection_v1'
            and plane['input_sha256']['acquisition'] == digest(raw), 'Plane and acquisition do not match')
    counts, exposure, receipt = report['counts'], report['exposure'], report['receipt']
    require(all(plane['selection'][k] == counts[k] for k in SELECTION_COUNTS[:3])
            and all(plane['selection'][k] == exposure[k] for k in LIVE_KEYS)
            and 0 < exposure['qualified_adc_live_time_ns'] <= exposure['clock_live_time_ns'],
            'Plane and acquisition census differ')
    sources = []
    for source in report['sources']:
        original = source['original']
        sources.append(dict(activity_bq=source['activity_bq'], scheduled_parent_seed=source['scheduled_parent_seed'],
                            **{key: original[key] for key in ('source_group', 'source_position_mm', 'chunk_index',
                               'chunk_sha256', 'transport_sha256', 'radiation_seed', 'field_cache_sha256')}))
    design = report['design']
    provenance = dict(name=folder.name, clock_seed=design['clock_seed'], noise_seed=design['noise_seed'],
                      trigger_profile=design['trigger_profile'], report_sha256=digest(raw), plane_sha256=digest(packed),
                      sources=sources, **{key: receipt[key] for key in RECEIPT_KEYS}, plane_inputs=plane['input_sha256'])
    with np.load(folder/'two-strip-adc.npz', allow_pickle=False) as adc:
        require(adc['report_sha256'].item() == provenance['report_sha256']
                and all(adc[key].item() == receipt[key] for key in RECEIPT_KEYS), 'ADC and acquisition do not match')
    adc_sha = digest((folder/'two-strip-adc.npz').read_bytes())
    require(plane['input_sha256'].get('adc_windows', adc_sha) == adc_sha, 'Plane and ADC do not match')
    provenance['adc_windows_sha256'] = adc_sha
    return provenance, plane


def compatible(blocks):
    records = [record for record, _ in blocks]
    for key in ('clock_seed', 'noise_seed', 'known_component_adc_sha256'):
        require(len({r[key] for r in records}) == len(records), f'Shared {key} among exposures')
    require(len({source['chunk_sha256'] for r in records for source in r['sources']}) == 2*len(records)
            and len({source['transport_sha256'] for r in records for source in r['sources']}) == 2*len(records)
            and len({source['radiation_seed'] for r in records for source in r['sources']}) == 2*len(records),
            'A transport history or radiation seed is reused')
    first, baseline = blocks[0]
    source_keys = ('activity_bq', 'source_group', 'source_position_mm', 'field_cache_sha256')
    for record, plane in blocks[1:]:
        require(all(record[key] == first[key] for key in ('trigger_profile', *RECEIPT_KEYS[:2]))
                and all(all(a[key] == b[key] for key in source_keys) for a, b in
                        zip(record['sources'], first['sources'], strict=True)), 'Acquisition designs differ')
        require(plane['grid'] == baseline['grid'] and plane['layers'].keys() == baseline['layers'].keys()
                and plane['selection']['energy_windows'] == baseline['selection']['energy_windows'], 'Plane grids or gates differ')
        require({k: v for k, v in plane['model'].items() if k != 'geometry'} ==
                {k: v for k, v in baseline['model'].items() if k != 'geometry'} and
                plane['model']['geometry'].partition(' The external waveform calibration')[0] ==
                baseline['model']['geometry'].partition(' The external waveform calibration')[0],
                'Plane response models differ')
    calibrations = {plane['input_sha256']['calibration'] for _, plane in blocks if 'calibration' in plane['input_sha256']}
    require(len(calibrations) <= 1, 'Portable center calibration archives differ')


def add_layers(planes, *, include_map):
    grid = planes[0]['grid']
    xx, yy = np.meshgrid(grid['x_mm'], grid['y_mm'])
    xyz = np.column_stack((xx.ravel(), yy.ravel(), np.full(xx.size, grid['assumed_z_mm'])))
    shape = (len(grid['y_mm']), len(grid['x_mm']))
    result = {}
    for key in planes[0]['layers']:
        layers = [plane['layers'][key] for plane in planes]
        maps = [np.asarray(layer['mass'], dtype=float) for layer in layers]
        for layer, cells in zip(layers, maps, strict=True):
            require(cells.shape == shape and np.isfinite(cells).all() and np.all(cells >= 0)
                    and math.isclose(float(cells.sum()), layer['projected_mass'], abs_tol=1e-9)
                    and math.isclose(sum(layer[k] for k in LAYER_MASS), layer['triggers'], abs_tol=1e-9),
                    f'Invalid cell weight or trigger accounting in {key}')
        image = np.add.reduce(maps)
        summary = {k: sum(layer[k] for layer in layers) for k in (*LAYER_COUNTS, *LAYER_MASS)}
        summary['peaks'] = blind_peaks(image.ravel(), xyz)
        if include_map:
            summary['mass'] = image.tolist()
        result[key] = summary
    for key in (*LAYER_COUNTS, *LAYER_MASS):
        require(math.isclose(result['all'][key], sum(layer[key] for label, layer in result.items() if label != 'all'),
                             abs_tol=1e-9), 'Energy gates do not partition the two-strip denominator')
    return result


def view(blocks, *, include_map):
    records, planes = zip(*blocks, strict=True)
    layers = add_layers(planes, include_map=include_map)
    selection = {key: math.fsum(plane['selection'][key] for plane in planes) for key in LIVE_KEYS}
    selection.update({key: sum(plane['selection'][key] for plane in planes) for key in SELECTION_COUNTS})
    require(selection['two_strip_triggers'] == layers['all']['triggers'], 'Two-strip totals differ')
    return dict(exposures=[record['name'] for record in records], selection=selection, layers=layers)


def compare(folders):
    blocks = [block(folder) for folder in folders]
    require(len(blocks) == 4, 'Supply four independent exposure folders in chronological accumulation order')
    compatible(blocks)
    first, second, full = (view(subset, include_map=True) for subset in (blocks[:2], blocks[2:], blocks))
    separation = {}
    for key, a in first['layers'].items():
        b = second['layers'][key]
        separation[key] = (math.dist(a['peaks'][0]['position_mm'], b['peaks'][0]['position_mm'])
                           if a['peaks'] and b['peaks'] else None)
    return dict(kind='gegi_independent_measured_plane_exposure_comparison_v1', grid=blocks[0][1]['grid'],
                energy_windows=blocks[0][1]['selection']['energy_windows'],
                weighting='Direct sum in nominal trigger units per cell. Unresolved trigger mass is retained.',
                inputs=[record for record, _ in blocks], individual=[view([b], include_map=False) for b in blocks],
                views=dict(first_half=first, second_half=second, full=full), split_peak_separation_mm=separation)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folders', type=Path, nargs=4)
    parser.add_argument('--output', type=Path, required=True, help='New compressed comparison JSON')
    args = parser.parse_args()
    result = compare(args.folders)
    result['source_sha256'] = digest(Path(__file__).read_bytes())
    payload = json.dumps(result, allow_nan=False, separators=(',', ':')).encode('utf-8')
    with args.output.open('xb') as target:
        target.write(gzip.compress(payload+b'\n', mtime=0))


if __name__ == '__main__':
    main()
