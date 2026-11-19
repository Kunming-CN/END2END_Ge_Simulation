"""Score each saved GeGI half-second map against the other half's measured cones."""

import argparse
from dataclasses import asdict, replace
import json
import math
import os
from pathlib import Path
import sys

if __name__ == '__main__':
    for variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
        os.environ[variable] = '1'

import numpy as np

from gegi_continuous_plane import LINE_ENERGIES_KEV, plane_prior_weights
from gegi_joint_imaging import BACKGROUND_PER_RAD, ResponseSettings, event_response, plane_grid, spectral_membership
from gegi_plane_footprint_study import ACQUISITIONS, ROOT, V1_POOL, read_events
from gegi_plane_prior_study import PRIORS, read_bound
from gegi_pool_measured_planes import digest, require


PRIOR_STUDY = V1_POOL.with_name('independent-1s-plane-priors.json.gz')
PRIOR_STUDY_SHA = 'cd0918844b62d57709d1825fd514ffbee999ee0211120c28b27c10ef7d2fe088'
HALVES = ('first_half', 'second_half')


def normalize(cells, size):
    mass = np.asarray(cells, dtype=float).ravel()
    integral = float(mass.sum())
    require(len(mass) == size and np.isfinite(mass).all() and (mass >= 0.).all() and 0. < integral < math.inf,
            'Expected a finite, nonnegative mass on the saved wide grid')
    return mass/integral


def mean_response(response, distribution, floor):
    # A normalized spatial distribution integrates the constant unresolved term to itself.
    return float((response-floor) @ distribution)+floor


def log_ratio(response, training, reference, floor):
    prediction, baseline = (mean_response(response, distribution, floor) for distribution in (training, reference))
    require(0. < prediction < math.inf and 0. < baseline < math.inf, 'Nonpositive or nonfinite angular mean')
    return math.log(prediction)-math.log(baseline)


def summary(values, informative):
    total = math.fsum(values)
    return dict(selected_triggers=len(values), informative_triggers=informative, sum_log_ratio=total,
                mean_log_ratio=total/len(values), wins=sum(v > 0. for v in values),
                losses=sum(v < 0. for v in values), ties=sum(v == 0. for v in values))


def direction(frozen, training_half, heldout_half, events, points, prior_only, settings):
    train_layers = frozen['views'][training_half]['layers']
    test_layers = frozen['views'][heldout_half]['layers']
    masks = {'all': np.ones(len(events), dtype=bool), **spectral_membership(events, LINE_ENERGIES_KEV)}
    require(masks.keys() == train_layers.keys() == test_layers.keys(), 'Saved energy layers differ')
    images = {label: {prior: normalize(train_layers[label]['priors'][prior]['wide_mass'], len(points)) for prior in PRIORS}
              for label in masks}
    values = {label: {prior: [] for prior in PRIORS} for label in masks}
    for i, event in enumerate(events):
        floor = event.unresolved_mass*BACKGROUND_PER_RAD
        response = event_response(event, points, settings)
        for label, mask in masks.items():
            if mask[i]:
                for prior in PRIORS:
                    value = log_ratio(response, images[label][prior], prior_only[prior], floor)
                    require(event.candidates or value == 0., 'Unresolved-only trigger has spatial information')
                    values[label][prior].append(value)
    crop = (abs(points[:, :2]) < frozen['grids']['original']['extent_mm']).all(axis=1)
    radius_squared = np.sum(points[:, :2]**2, axis=1)
    result = {}
    for label, mask in masks.items():
        selected = [event for event, included in zip(events, mask, strict=True) if included]
        informative = sum(bool(event.candidates) for event in selected)
        saved = test_layers[label]
        require(len(selected) == saved['triggers'] and informative == saved['triggers_with_geometry'] and
                sum(len(event.candidates) for event in selected) == saved['hypotheses'] and
                math.fsum(event.unresolved_mass for event in selected) == saved['unresolved_mass'],
                'The held-out trigger denominator or saved hypotheses changed')
        result[label] = {}
        for prior in PRIORS:
            image, reference = images[label][prior], prior_only[prior]
            result[label][prior] = summary(values[label][prior], informative) | dict(
                training_triggers=train_layers[label]['triggers'],
                training_informative_triggers=train_layers[label]['triggers_with_geometry'],
                training_central_crop_fraction=float(image[crop].sum()), prior_central_crop_fraction=float(reference[crop].sum()),
                training_rms_radius_mm=math.sqrt(float(image @ radius_squared)),
                prior_rms_radius_mm=math.sqrt(float(reference @ radius_squared)))
    return result


def run():
    frozen = read_bound(PRIOR_STUDY, PRIOR_STUDY_SHA)
    grid = frozen['grids']['wide']
    extent, step, z = (grid[key] for key in ('extent_mm', 'step_mm', 'assumed_z_mm'))
    ticks, points = plane_grid(extent, step, z)
    require((extent, step, z) == (240., 4., 40.) and ticks.tolist() == grid['x_mm'] == grid['y_mm'],
            'Unexpected saved wide grid')
    settings = ResponseSettings(**frozen['model'])
    settings.validate()
    prior_only = {prior: normalize(plane_prior_weights(points, step, prior), len(points)) for prior in PRIORS}
    events_by_block = {}
    for item in frozen['inputs']:
        name = item['name']
        ledger = read_bound(ACQUISITIONS/name/'plane.json.gz', item['plane_sha256'])
        require(ledger['grid'] == frozen['grids']['original'] and ledger['input_sha256'] == item['plane_inputs'],
                'Saved block geometry or provenance differs')
        events_by_block[name] = read_events(ledger['triggers'], settings)
    names = {half: frozen['views'][half]['exposures'] for half in HALVES}
    require(len(set(names['first_half']+names['second_half'])) == 4 and all(len(blocks) == 2 for blocks in names.values()),
            'Each test direction needs two disjoint acquisition blocks')
    events = {half: [event for name in names[half] for event in events_by_block[name]] for half in HALVES}
    comparisons = {f'{train}_to_{test}': direction(frozen, train, test, events[test], points, prior_only, settings)
                   for train, test in (HALVES, HALVES[::-1])}

    # A control with one of the saved cones and a declared half-unit of unresolved mass.
    example = next(event for event in events[HALVES[0]] if event.candidates)
    partial = replace(example, candidates=(replace(example.candidates[0], prior=.5),), unresolved_mass=.5)
    full_response = event_response(partial, points, settings)
    geometry_only = event_response(replace(partial, unresolved_mass=0.), points, settings)
    floor = partial.unresolved_mass*BACKGROUND_PER_RAD
    identical = max(abs(log_ratio(full_response, prior, prior, floor)) for prior in prior_only.values())
    floor_error = max(abs(mean_response(full_response, prior, floor)-mean_response(geometry_only, prior, 0.)-floor)
                      for prior in prior_only.values())
    require(identical == 0. and floor_error <= 1e-12, 'The identical-map or partial-unresolved score control failed')

    pooled = {}
    first, second = comparisons.values()
    for label, arms in first.items():
        pooled[label] = {}
        for prior, a in arms.items():
            b = second[label][prior]
            totals = {key: a[key]+b[key] for key in ('selected_triggers', 'informative_triggers', 'sum_log_ratio',
                                                    'wins', 'losses', 'ties')}
            totals['mean_log_ratio'] = totals['sum_log_ratio']/totals['selected_triggers']
            pooled[label][prior] = totals
    return dict(kind='gegi_measured_plane_heldout_score_v1', prior_study_sha256=PRIOR_STUDY_SHA,
                inputs=frozen['inputs'], halves=names, grid=grid, response_settings=asdict(settings),
                background_per_rad=BACKGROUND_PER_RAD, energy_windows=frozen['energy_windows'],
                score_definition='For every held-out trigger, compare the natural logs of the existing event angular '
                                 'response averaged under the matching training map and the prior alone. The distributions '
                                 'span the whole wide grid, and each average includes the same unresolved response term.',
                interpretation='Positive values indicate better average held-out angular agreement than the matching prior. '
                               'The score is conditional on the saved response model and does not measure localization accuracy '
                               'or a calibrated likelihood of the detector data.',
                checks=dict(identical_map_max_abs_log_ratio=identical, partial_unresolved_max_abs_floor_error=floor_error,
                            unresolved_only_log_ratio=0.), comparisons=comparisons, pooled=pooled)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New private JSON derivative')
    args = parser.parse_args()
    names = ('gegi_plane_heldout_score.py', 'gegi_plane_prior_study.py', 'gegi_plane_footprint_study.py',
             'gegi_pool_measured_planes.py', 'gegi_joint_imaging.py', 'gegi_continuous_plane.py', 'gegi_imaging.py')
    sources = {name: ROOT/'tools'/name for name in names}
    hashes = {name: digest(path.read_bytes()) for name, path in sources.items()}
    result = run()
    result.update(source_sha256=hashes, runtime=dict(python=sys.version.split()[0], numpy=np.__version__))
    payload = json.dumps(result, allow_nan=False, indent=2).encode('utf-8')+b'\n'
    require(hashes == {name: digest(path.read_bytes()) for name, path in sources.items()}, 'Score source changed during processing')
    with args.output.open('xb') as target:
        target.write(payload)


if __name__ == '__main__':
    main()
