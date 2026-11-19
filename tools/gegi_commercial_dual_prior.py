"""Compare geometric priors on sealed simultaneous RSS5 measured cone ledgers."""

import argparse
from collections import Counter
import gzip
import json
import math
import os
from pathlib import Path
import tempfile
from time import sleep
from types import SimpleNamespace

for _variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[_variable] = '1'

import numpy as np

import gegi_continuous_plane as plane
from gegi_joint_imaging import ResponseSettings, blind_peaks, plane_grid, spectral_membership
from gegi_pool_measured_planes import LAYER_COUNTS, LAYER_MASS, digest, require


CAMPAIGN = Path(__file__).resolve().parents[1] / '.local/gegi-dual-source/rss5-simultaneous-large'
KIND = 'gegi_commercial_simultaneous_prior_comparison_v1'
AREA, SOLID = PRIORS = plane.PLANE_PRIORS
LINES = tuple(f'{energy:g}_keV' for energy in plane.LINE_ENERGIES_KEV)
COBALT = 'pooled_1173_and_1332_keV'
BASE_LAYERS = ('all', *LINES, 'other_energy')
MISSING = ('no_waveform_fit', 'no_usable_cone', 'no_plane_response')
ACQUISITION_KIND = 'gegi_dual_source_acquisition_v1'
ABS_TOL = 1e-9  # nominal trigger units


def check_closure(accounting, image):
    a = accounting
    close = lambda first, second: math.isclose(first, second, rel_tol=0., abs_tol=ABS_TOL)
    require(close(a['triggers'], a['allowed_order_mass'] + a['no_pairing_mass'] + a['no_allowed_order_mass'])
            and close(a['allowed_order_mass'], a['projected_mass'] + sum(a[s + '_mass'] for s in MISSING))
            and close(a['triggers'], a['projected_mass'] + a['unresolved_mass'])
            and close(a['projected_mass'], float(image.sum())), 'Nominal trigger or cone weight does not close')


def measures(projected, masks):
    rows = projected['triggers']
    by_event = []
    for row in rows:
        pairs = row['pairings']
        orders = [order for pair in pairs for order in pair['orders']]
        mass = Counter()
        for order in orders:
            mass[order['status']] += order['nominal_mass']
        row_weights = dict(allowed_order_mass=math.fsum(mass.values()), no_pairing_mass=int(not pairs),
                           no_allowed_order_mass=math.fsum(p['nominal_mass'] for p in pairs if not p['orders']))
        row_weights.update((s + '_mass', mass[s]) for s in MISSING)
        by_event.append(row_weights)
        require(math.isclose(mass['projected'], row['projected_mass'], rel_tol=0., abs_tol=ABS_TOL),
                'Projected ledger order weights disagree')
    view = {}
    for label, mask in masks.items():
        layer = projected['layers'][label]
        accounted = {key: layer[key] for key in (*LAYER_COUNTS, *LAYER_MASS)}
        require(np.count_nonzero(mask) == accounted['triggers'], 'Measured-energy membership changed')
        for key in ('allowed_order_mass', 'no_pairing_mass', 'no_allowed_order_mass', *(s + '_mass' for s in MISSING)):
            accounted[key] = math.fsum(w[key] for w, included in zip(by_event, mask, strict=True) if included)
        image = np.asarray(layer['mass'], dtype=float)
        require(np.isfinite(image).all() and np.all(image >= 0.), 'Image has invalid cell weights')
        check_closure(accounted, image)
        view[label] = (accounted, image)
    for key in view['all'][0]:
        require(math.isclose(view['all'][0][key], sum(view[label][0][key] for label in BASE_LAYERS[1:]),
                             rel_tol=0., abs_tol=ABS_TOL), 'Disjoint windows do not partition all selected triggers')
    return view


def load_shard(folder, config, binding, shape):
    seal_bytes = (folder / 'receipt.json').read_bytes()
    seal = json.loads(seal_bytes)
    spec = config['blocks'][folder.name]
    report_bytes = (folder / 'report.json').read_bytes()
    plane_bytes = (folder / plane.PLANE_FILE).read_bytes()
    report_sha, plane_sha = digest(report_bytes), digest(plane_bytes)
    require((seal['kind'], seal['block'], seal['config_sha256']) ==
            ('gegi_commercial_dual_shard_v1', folder.name, binding)
            and seal['artifacts']['report.json'] == report_sha and seal['artifacts'][plane.PLANE_FILE] == plane_sha
            and seal['input_seals'] == {key: item['done_sha256'] for key, item in spec['inputs'].items()},
            f'Shard seal mismatch in {folder.name}')
    report = json.loads(report_bytes)
    saved = json.loads(gzip.decompress(plane_bytes))
    require((report['kind'], report['status'], report['design']['clock_seed'], report['design']['noise_seed']) ==
            (ACQUISITION_KIND, 'completed', spec['clock_seed'], spec['noise_seed'])
            and report['design']['live_time_s'] == config['live_time_per_block_s'], 'Acquisition design differs')
    sources = {source['key']: source for source in report['sources']}
    require(set(sources) == config['sources'].keys(), 'Acquisition source keys differ')
    for key, source in sources.items():
        original, expected, nominal = source['original'], spec['inputs'][key], config['sources'][key]
        require((source['activity_bq'], original['isotope'], original['source_position_mm'], original['chunk_sha256'],
                 original['database_sha256'], original['radiation_seed']) ==
                (nominal['activity_bq'], nominal['isotope'], nominal['position_mm'], expected['done_sha256'],
                 expected['database_sha256'], expected['radiation_seed']), f'Acquisition source binding differs for {key}')
    inputs, grid, model = saved['input_sha256'], saved['grid'], saved['model']
    settings = dict(z_mm=grid['assumed_z_mm'], extent_mm=grid['extent_mm'], step_mm=grid['step_mm'],
                    sigma_deg=model['angular_nuisance_sigma_deg'], plane_prior=model['plane_prior'])
    require(saved['kind'] == plane.PLANE_KIND and inputs['acquisition'] == report_sha
            and inputs['adc_windows'] == seal['artifacts'][plane.ADC_WINDOWS_FILE]
            and inputs['calibration'] == config['calibration_sha256'] and settings == config['plane']
            and model['strip_pitch_mm'] == ResponseSettings().strip_pitch_mm,
            f'Saved plane recipe or input binding differs in {folder.name}')

    rows = saved['triggers']
    events = [SimpleNamespace(energy_keV=row['energy_keV']) for row in rows]
    masks = {'all': np.ones(len(rows), dtype=bool), **spectral_membership(events, plane.LINE_ENERGIES_KEV)}
    baseline = measures(saved, masks)
    orders = [order for row in rows for pair in row['pairings'] for order in pair['orders']]
    saved_statuses = [order['status'] for order in orders]
    # The existing --from-plane path performs these same two operations after input binding.
    records = plane._reuse_saved_events(report, rows)
    alternate = plane._project(report, records, rows, saved['selection']['two_strip_triggers'],
                               **(settings | {'plane_prior': SOLID}))
    require(alternate['selection'] == saved['selection'] and alternate['grid'] == grid
            and [order['status'] for order in orders] == saved_statuses,
            'Changing the positive cell prior altered the selection, grid or order availability')
    result = {AREA: baseline, SOLID: measures(alternate, masks)}
    require(all(result[AREA][label][0] == result[SOLID][label][0]
                and all(result[prior][label][1].shape == shape for prior in PRIORS) for label in BASE_LAYERS),
            'Prior comparison changed the nominal accounting or map shape')
    provenance = dict(seal_sha256=digest(seal_bytes), report_sha256=report_sha,
                      acquisition_plane_sha256=plane_sha, input_seals=seal['input_seals'],
                      clock_seed=spec['clock_seed'], noise_seed=spec['noise_seed'],
                      clock_live_time_ns=saved['selection']['clock_live_time_ns'],
                      qualified_adc_live_time_ns=saved['selection']['qualified_adc_live_time_ns'],
                      accounting={label: baseline[label][0] for label in BASE_LAYERS})
    return provenance, result


def add_layers(target, incoming):
    for prior in PRIORS:
        layers = target.setdefault(prior, {})
        for label, (accounting, cells) in incoming[prior].items():
            if label in layers:
                counts, total = layers[label]
                counts.update(accounting)
                total += cells
            else:
                layers[label] = (Counter(accounting), cells.copy())
    return target


def pooled_cobalt(layers):
    first, second = (layers[label] for label in LINES[1:])
    return {key: first[0][key] + second[0][key] for key in first[0]}, first[1] + second[1]


def describe(layers, points, scored_sources, *, full):
    result = {}
    for prior, maps in layers.items():
        by_label = result.setdefault(prior, {})
        for label, (accounting, image) in (maps | {COBALT: pooled_cobalt(maps)}).items():
            check_closure(accounting, image)
            peaks = blind_peaks(image.ravel(), points)
            summary = dict(accounting=dict(accounting), blind_peaks=peaks)
            if label in scored_sources:
                source_key, expected = scored_sources[label]
                offsets = []
                for peak in peaks:
                    position = np.asarray(peak['position_mm'])
                    angle = math.degrees(math.atan2(np.linalg.norm(np.cross(expected, position)), np.dot(expected, position)))
                    offsets.append(dict(distance_mm=math.dist(expected, position), offset_xyz_mm=(position-expected).tolist(),
                                        direction_error_deg=angle))
                summary['held_out_comparison'] = dict(source=source_key, expected_position_mm=expected, peak_offsets=offsets)
            if full:
                summary['mass_trigger_units'] = image.tolist()
            by_label[label] = summary
    return result


def atomic_json(path, result):
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as target:
        pending = Path(target.name)
        json.dump(result, target, allow_nan=False, separators=(',', ':'))
        target.write('\n')
    pending.replace(path)


def run(campaign, follow):
    raw = (campaign / 'campaign.json').read_bytes()
    config = json.loads(raw)
    source_dir = Path(__file__).resolve().parent
    implementation = {key: digest((source_dir / key).read_bytes()) for key in
                      (Path(__file__).name, 'gegi_continuous_plane.py', 'gegi_joint_imaging.py')}
    require(config['kind'] == 'gegi_commercial_dual_campaign_v1'
            and implementation['gegi_continuous_plane.py'] == config['implementation_sha256']['gegi_continuous_plane.py'],
            'Campaign or its saved-plane implementation has changed')
    blocks, settings = tuple(sorted(config['blocks'])), config['plane']
    require((len(blocks), settings['z_mm'], settings['extent_mm'], settings['step_mm'], settings['plane_prior']) ==
            (25, 40, 120, 4, AREA), 'Expected the 25-block RSS5 acquisition on its original area grid')
    ticks, points = plane_grid(settings['extent_mm'], settings['step_mm'], settings['z_mm'])
    shape = (len(ticks), len(ticks))
    views = [blocks[:len(blocks)//2], blocks[len(blocks)//2:]]
    source_by_isotope = {spec['isotope']: (key, spec['position_mm']) for key, spec in config['sources'].items()}
    scored_sources = {label: source_by_isotope['Cs-137' if label == LINES[0] else 'Co-60'] for label in (*LINES, COBALT)}
    require(all(xyz[2] == settings['z_mm'] for _, xyz in scored_sources.values()), 'Scored source lies outside the plane')

    output = campaign / 'alternate-prior.json'
    bindings = dict(kind=KIND, campaign_sha256=digest(raw), implementation_sha256=implementation)
    data, sums = {}, [{}, {}]
    if output.exists():
        previous = json.loads(output.read_bytes())
        require(all(previous[key] == value for key, value in bindings.items()), 'Previous prior comparison has other inputs')
        data = previous['processed_blocks']
        require(all(digest((campaign / key / 'receipt.json').read_bytes()) == prior['seal_sha256']
                    for key, prior in data.items()), 'A processed block receipt changed')
        if previous['status'] == 'completed':
            return previous
        sums = [{prior: {label: (Counter(accounting), np.asarray(cells, dtype=float))
                         for label, (accounting, cells) in layers.items()} for prior, layers in half.items()}
                for half in previous['checkpoint_split_sums']]

    while True:
        updated = False
        for name in blocks:
            folder = campaign / name
            if name not in data and (folder / 'receipt.json').is_file():
                provenance, layers = load_shard(folder, config, bindings['campaign_sha256'], shape)
                add_layers(sums[int(name in views[1])], layers)
                data[name] = provenance
                updated = True
        if updated:
            completed = len(data) == len(blocks)
            totals = {}
            for half in sums:
                if half:
                    add_layers(totals, half)
            halves = [describe(half, points, scored_sources, full=False) for half in sums]
            separation = {}
            if all(halves):
                for prior in PRIORS:
                    separation[prior] = {}
                    for label in (*BASE_LAYERS, COBALT):
                        top = [part[prior][label]['blind_peaks'][:1] for part in halves]
                        separation[prior][label] = math.dist(*(a[0]['position_mm'] for a in top)) if all(top) else None
            result = bindings | dict(
                status='completed' if completed else 'partial', planned_blocks=list(blocks), processed_blocks=data,
                sources=config['sources'], grid=settings | dict(x_mm=ticks.tolist(), y_mm=ticks.tolist()),
                exposure_s=sum(item['clock_live_time_ns'] for item in data.values()) / 1e9,
                qualified_adc_exposure_s=sum(item['qualified_adc_live_time_ns'] for item in data.values()) / 1e9,
                solid_angle_prior=plane.plane_prior_metadata(SOLID, plane.plane_prior_weights(points, settings['step_mm'], SOLID)),
                method=('Saved uniform-area baseline and the same measured cone orders normalized individually with the '
                        'uniform-solid-angle cell measure. Cobalt pooling sums the two disjoint measured-energy windows. '
                        'Blind peaks are scored after reconstruction. Angular errors use rays from detector (0, 0, 0) mm. '
                        'This tests localization under two geometric priors on a fixed plane without a detector sensitivity model.'),
                line_windows_keV={label: [e-max(5., .02*e), e+max(5., .02*e)]
                                  for label, e in zip(LINES, plane.LINE_ENERGIES_KEV, strict=True)},
                pooled=describe(totals, points, scored_sources, full=True),
                split=[dict(completed_blocks=[name for name in who if name in data], priors=part)
                       for who, part in zip(views, halves, strict=True)], split_primary_peak_separation_mm=separation,
            )
            if not completed:
                result['checkpoint_split_sums'] = [{prior: {label: [counts, cells.tolist()]
                                                            for label, (counts, cells) in layers.items()}
                                                    for prior, layers in half.items()} for half in sums]
            atomic_json(output, result)
            print(f'{len(data)}/{len(blocks)} blocks: {output}', flush=True)
            previous = result
        if len(data) == len(blocks) or not follow:
            require(bool(data), 'No sealed acquisition blocks are available')
            return previous
        sleep(15)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign', type=Path, default=CAMPAIGN)
    parser.add_argument('--follow', action='store_true', help='Process new seals until all planned blocks contribute')
    args = parser.parse_args()
    run(args.campaign, args.follow)


if __name__ == '__main__':
    main()
