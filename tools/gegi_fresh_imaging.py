"""Accumulate measured images as each independent dual-source exposure completes."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

import numpy as np

import gegi_commercial_dual_results as measured
from gegi_commercial_dual_prior import AREA, SOLID, PRIORS, LINES, atomic_json
import gegi_continuous_plane as plane
import gegi_pool_measured_planes as pool


def accumulate(previous, new_plane):
    planes = [new_plane] if previous is None else [
        {'grid': new_plane['grid'], 'layers': previous}, new_plane]
    return pool.add_layers(planes, include_map=True)


def source_design(provenance, block, image):
    return dict(sources={key: {k: row[k] for k in ('activity_bq', 'position_mm')}
                         for key, row in block['sources'].items()},
                grid=image['grid'], calibration_sha256=image['input_sha256']['calibration'],
                trigger_profile=provenance['trigger_profile'],
                digital_profile_sha256=provenance['digital_profile_sha256'],
                digital_timing_sha256=provenance['digital_timing_sha256'],
                angular_sigma_deg=image['model']['angular_nuisance_sigma_deg'],
                energy_windows=image['selection']['energy_windows'])


def add_block(state, folder, receipt, receipt_sha):
    provenance, baseline, event, spectrum = measured.measured_block(folder, receipt['config_sha256'])
    design = source_design(provenance, event, baseline)
    if state.setdefault('design', design) != design or baseline['model']['plane_prior'] != AREA:
        raise ValueError('Acquisition or source-plane settings changed across exposures')
    previous_seeds = {s for row in state['blocks'].values() for s in row['radiation_seeds']}
    radiation_seeds = [s['radiation_seed'] for s in provenance['sources']]
    if len(set(radiation_seeds)) != len(radiation_seeds) or previous_seeds.intersection(radiation_seeds):
        raise ValueError('Incoming exposure reuses a radiation seed')
    clock_seeds = {row['clock_seed'] for row in state['blocks'].values()}
    if provenance['clock_seed'] in clock_seeds:
        raise ValueError('Incoming exposure reuses a source clock')
    other = plane.run_from_plane(folder/'report.json', folder/'plane.json.gz', plane_prior=SOLID)
    for label, layer in baseline['layers'].items():
        for key in (*pool.LAYER_COUNTS, *pool.LAYER_MASS):
            if not np.isclose(layer[key], other['layers'][label][key], rtol=0., atol=1.e-9):
                raise ValueError('Spatial weighting changed the event accounting')
    for prior, image in ((AREA, baseline), (SOLID, other)):
        state['images'][prior] = accumulate(state['images'].get(prior), image)
    state['spectra'] = measured.add_spectra([state['spectra'], spectrum]) if 'spectra' in state else spectrum
    for key, values in (('events', event['counts']), ('measured_energy_windows', event['measured_energy_window_counts']),
                        ('time_ns', {key: baseline['selection'][key] for key in pool.LIVE_KEYS})):
        counts = Counter(state.get(key, {}))
        counts.update(values)
        state[key] = dict(counts)
    for key, src in event['sources'].items():
        previous = Counter(state['source_counts'].get(key, {}))
        previous.update({k: v for k, v in src.items() if k not in ('activity_bq', 'position_mm')})
        state['source_counts'][key] = dict(previous)
    state['blocks'][folder.name] = dict(receipt_sha256=receipt_sha, clock_seed=provenance['clock_seed'],
                                        radiation_seeds=radiation_seeds,
                                        input_seals=receipt['input_seals'])


def render_image(state, out):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    grid = state['design']['grid']
    limit = grid['extent_mm']
    fig, axes = plt.subplots(2, 2, figsize=(9, 8), layout='constrained', sharex=True, sharey=True)
    for column, prior in enumerate(PRIORS):
        layer = state['images'][prior]
        for ax, lines, isotope in zip(axes[:, column], (LINES[:1], LINES[1:]), ('Cs-137', 'Co-60'), strict=True):
            weights = np.sum([layer[line]['mass'] for line in lines], axis=0)
            peak = float(weights.max())
            drawing = ax.imshow(weights / peak if peak else weights, origin='lower', cmap='magma', vmin=0, vmax=1,
                                extent=(-limit, limit, -limit, limit), interpolation='nearest')
            if peak:
                iy, ix = np.unravel_index(weights.argmax(), weights.shape)
                ax.plot(grid['x_mm'][ix], grid['y_mm'][iy], 'wo', markerfacecolor='none', clip_on=False)
            count = sum(layer[line]['triggers_with_geometry'] for line in lines)
            ax.set_title(f"{isotope} | {prior.replace('-', ' ')}\n{count:,} projected triggers")
    fig.supxlabel('Detector X (mm)')
    fig.supylabel('Detector Y (mm)')
    fig.colorbar(drawing, ax=axes, shrink=.75, label='Cell weight relative to panel maximum')
    fig.suptitle(f"Shared-clock exposures: {state['completed_blocks']} of {state['target_blocks']}"
                 f"  |  plane z = {grid['assumed_z_mm']:g} mm")
    temporary = out.with_suffix('.tmp')
    fig.savefig(temporary, format='png', dpi=120,
                metadata={'ExposureCount': str(state['completed_blocks'])})
    plt.close(fig)
    temporary.replace(out)


def update(readout_root, target_blocks=230):
    root = Path(readout_root)
    out = root/'imaging-progress.json'
    state = json.loads(out.read_bytes()) if out.exists() else dict(
        kind='gegi_fresh_simultaneous_imaging_v1', target_blocks=target_blocks, blocks={}, images={}, source_counts={})
    if state['target_blocks'] != target_blocks or state['kind'] != 'gegi_fresh_simultaneous_imaging_v1':
        raise ValueError('Image checkpoint belongs to another production target')
    paths = sorted(root.glob('b[0-9][0-9][0-9][0-9][0-9][0-9]/receipt.json'))
    if len(paths) > target_blocks:
        raise ValueError('More sealed exposures than the planned imaging cohort')
    seals = {p.parent.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    if any(seals.get(name) != record['receipt_sha256'] for name, record in state['blocks'].items()):
        raise ValueError('An archived exposure is missing or has changed')
    added = False
    for path in paths:
        if path.parent.name in state['blocks']:
            continue
        add_block(state, path.parent, json.loads(path.read_bytes()), seals[path.parent.name])
        state['completed_blocks'] = len(state['blocks'])
        state['status'] = 'completed' if state['completed_blocks'] == target_blocks else 'collecting'
        area = state['images'][AREA]
        state['projected_cobalt_triggers'] = sum(area[line]['triggers_with_geometry'] for line in LINES[1:])
        state['projected_cesium_triggers'] = area[LINES[0]]['triggers_with_geometry']
        atomic_json(out, state)
        added = True
    if state['blocks']:
        from PIL import Image
        figure = root/'source-images.png'
        refresh = added or not figure.is_file()
        if not refresh:
            with Image.open(figure) as image:
                refresh = image.info.get('ExposureCount') != str(state['completed_blocks'])
        if refresh:
            render_image(state, figure)
    return state


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('readout_root', type=Path)
    parser.add_argument('--target-blocks', type=int, default=230)
    args = parser.parse_args()
    result = update(args.readout_root, args.target_blocks)
    print(json.dumps({k: result.get(k) for k in ('status', 'completed_blocks', 'projected_cobalt_triggers')}))
