"""Fit source depth from the sealed RSS5 measured cones without fixing a plane."""

import argparse
import gzip
import itertools
import json
import math
import os
from pathlib import Path
import platform

for _variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[_variable] = '1'

import numpy as np
import scipy
from scipy.optimize import minimize

import gegi_continuous_plane as plane
from gegi_commercial_dual_prior import CAMPAIGN, COBALT, LINES, atomic_json, digest, require
from gegi_joint_imaging import ResponseSettings, prepare_events, spectral_membership
from gegi_source_range import AngularScore, POINT_CONE_BUDGET


ROOT = Path(__file__).resolve().parents[1]
ASSEMBLY = ROOT / 'scenarios/assets/gegi_cryostat_v1.json'
SLOPE_LIMIT = 3.
MAX_DEPTH_MM = 2500.
FAR_DEPTH_MM = 1e7
EXTRA_BACKGROUND = .25
LABELS = (LINES[0], COBALT)
FIT_MODES = ((EXTRA_BACKGROUND, 'all'), (0., 'all'), (EXTRA_BACKGROUND, 'first'), (EXTRA_BACKGROUND, 'second'))


def selected_cohort(campaign, config, block_limit):
    """Return the exact acquisition prefix and its recorded identity checks."""
    if config.get('kind') == 'gegi_commercial_dual_campaign_v1':
        roster = config['blocks']
        target = len(roster)
        pins = config['implementation_sha256']
        checks = {name: dict(clock_seed=row['clock_seed'], noise_seed=row['noise_seed'],
                             input_seals={key: item['done_sha256'] for key, item in row['inputs'].items()})
                  for name, row in sorted(roster.items())}
    else:
        target = config['pairs']
        pins = config['sources_sha256']
        count = target if block_limit is None else block_limit
        require(isinstance(count, int) and 2 <= count <= target, f'Select between 2 and {target} blocks')
        progress_file = campaign / 'imaging-progress.json'
        require(progress_file.is_file(), 'The acquisition has no admitted image blocks yet')
        progress = json.loads(progress_file.read_bytes())
        require(progress['kind'] == 'gegi_fresh_simultaneous_imaging_v1' and progress['target_blocks'] == target,
                'The expected imaging admission ledger is missing')
        prefix = [f'b{index:06d}' for index in range(count)]
        admitted = progress['blocks']
        missing = next((name for name in prefix if name not in admitted), None)
        require(missing is None, f'Requested first {count} blocks but {missing} has no imaging admission yet')
        checks = {}
        for index, name in enumerate(prefix):
            admission = admitted[name]
            require(admission['clock_seed'] == config['first_clock_seed']+index, f'Admitted clock seed differs in {name}')
            checks[name] = dict(clock_seed=admission['clock_seed'], noise_seed=config['first_noise_seed']+index,
                                input_seals=admission['input_seals'], receipt_sha256=admission['receipt_sha256'],
                                radiation_seeds=admission['radiation_seeds'])
    count = target if block_limit is None else block_limit
    require(isinstance(count, int) and 2 <= count <= target, f'Select between 2 and {target} blocks')
    return dict(list(checks.items())[:count]), target, pins


def load_events(campaign, config, binding, cohort, settings):
    blocks = {}
    provenance = {}
    input_seals = set()
    for name, spec in cohort.items():
        folder = campaign / name
        seal_bytes = (folder / 'receipt.json').read_bytes()
        seal = json.loads(seal_bytes)
        seal_sha = digest(seal_bytes)
        report_bytes = (folder / 'report.json').read_bytes()
        plane_bytes = (folder / plane.PLANE_FILE).read_bytes()
        report_sha, plane_sha = digest(report_bytes), digest(plane_bytes)
        require((seal['kind'], seal['block'], seal['config_sha256']) == ('gegi_commercial_dual_shard_v1', name, binding)
                and seal_sha == spec.get('receipt_sha256', seal_sha)
                and seal['artifacts']['report.json'] == report_sha and seal['artifacts'][plane.PLANE_FILE] == plane_sha
                and seal['input_seals'] == spec['input_seals'],
                f'Measured cone inputs differ from the sealed acquisition {name}')
        report = json.loads(report_bytes)
        saved = json.loads(gzip.decompress(plane_bytes))
        require(saved['kind'] == plane.PLANE_KIND and saved['input_sha256']['acquisition'] == report_sha
                and saved['input_sha256']['adc_windows'] == seal['artifacts'][plane.ADC_WINDOWS_FILE]
                and saved['input_sha256']['calibration'] == config['calibration_sha256']
                and saved['model']['angular_nuisance_sigma_deg'] == settings.angular_nuisance_sigma_deg
                and saved['model']['strip_pitch_mm'] == settings.strip_pitch_mm, f'Cone response model differs in {name}')
        design = report['design']
        require((design['clock_seed'], design['noise_seed'], design['live_time_s']) ==
                (spec['clock_seed'], spec['noise_seed'], config['live_time_per_block_s']), f'ADC design differs in {name}')
        sources = {row['key']: row for row in report['sources']}
        indexed_seals = {key: row['original']['chunk_sha256'] for key, row in sources.items()}
        require(indexed_seals == seal['input_seals'] and sources.keys() == config['sources'].keys()
                and len(set(indexed_seals.values())) == len(sources)
                and not input_seals.intersection(indexed_seals.values()), f'Archived source seal differs or is reused in {name}')
        input_seals.update(indexed_seals.values())
        radiation_seeds = [row['original']['radiation_seed'] for row in sources.values()]
        require(radiation_seeds == spec.get('radiation_seeds', radiation_seeds)
                and all((row['original']['isotope'], row['activity_bq'], row['original']['source_position_mm']) ==
                        (config['sources'][key]['isotope'], config['sources'][key]['activity_bq'],
                         config['sources'][key]['position_mm']) for key, row in sources.items()),
                f'Nominal source or radiation seed differs in {name}')
        events = prepare_events(plane._reuse_saved_events(report, saved['triggers']), settings)
        masks = spectral_membership(events, plane.LINE_ENERGIES_KEV)
        gates = {label: [event for event, keep in zip(events, masks[label], strict=True) if keep] for label in LINES}
        for label, rows in gates.items():
            measured = saved['layers'][label]
            require((len(rows), sum(bool(e.candidates) for e in rows), sum(len(e.candidates) for e in rows)) ==
                    (measured['triggers'], measured['triggers_with_geometry'], measured['hypotheses'])
                    and math.isclose(math.fsum(e.unresolved_mass for e in rows), measured['unresolved_mass'], abs_tol=1e-10),
                    'Available cone orders and unresolved mass differ from saved accounting')
        blocks[name] = {LINES[0]: gates[LINES[0]], COBALT: sorted(gates[LINES[1]] + gates[LINES[2]], key=lambda e: e.identity)}
        provenance[name] = dict(receipt_sha256=seal_sha, report_sha256=report_sha, plane_sha256=plane_sha,
                                selected_trigger_indices={label: [e.identity[0] for e in rows] for label, rows in gates.items()},
                                measured_window_accounting={label: {key: saved['layers'][label][key] for key in
                                                         ('triggers', 'allowed_hypotheses', 'hypotheses', 'projected_mass', 'unresolved_mass')}
                                                            for label in LINES})
    return blocks, provenance



def xyz(slope, depth):
    return np.column_stack((np.atleast_2d(slope)*depth, np.full(len(np.atleast_2d(slope)), depth)))


def seeds(score, slopes, count):
    chosen = []
    for index in np.argsort(-score, kind='stable'):
        point = slopes[index]
        if all(np.linalg.norm(earlier-point) >= .6 for earlier in chosen):
            chosen.append(point)
        if len(chosen) == count:
            break
    return chosen


def optimize(score, initial, bounds):
    trials = [minimize(lambda coordinate: -score(coordinate), guess, method='L-BFGS-B', bounds=bounds,
                       options={'ftol': 1e-10, 'gtol': 1e-6, 'maxiter': 125}) for guess in initial]
    result = min(trials, key=lambda fit: fit.fun)
    require(math.isfinite(result.fun), 'Source score is nonfinite')
    return result.x, -float(result.fun), bool(result.success)


def fit(scorer, depths, slopes, grid_scores, mode, *, profile):
    bounds = [(-SLOPE_LIMIT, SLOPE_LIMIT)]*2
    fixed = []
    for depth, coarse in zip(depths, grid_scores, strict=True):
        def evaluate(points):
            return scorer.score(xyz(points, depth), mode)[:, 0]

        if profile:
            best, value, success = optimize(lambda p: evaluate(p)[0], seeds(coarse, slopes, 2), bounds)
        else:
            top = int(np.argmax(coarse))
            best, value, success = slopes[top], float(coarse[top]), None
        fixed.append(dict(depth_mm=float(depth), slopes=best.tolist(), log_score=value, optimizer_converged=success))

    interior = sorted((row for row in fixed if row['depth_mm'] <= MAX_DEPTH_MM),
                      key=lambda row: row['log_score'], reverse=True)
    start = []
    for row in interior:
        point = [*row['slopes'], math.log(row['depth_mm'])]
        if all(np.linalg.norm(np.array(point)-prior) >= .6 for prior in start):
            start.append(point)
        if len(start) == 4:
            break
    def objective(coordinate):
        return scorer.score(xyz(coordinate[:2], math.exp(coordinate[2])), mode)[0, 0]

    coordinate, value, success = optimize(objective, start, [*bounds, (math.log(depths[0]), math.log(MAX_DEPTH_MM))])
    depth = math.exp(coordinate[2])
    position = xyz(coordinate[:2], depth)[0]
    result = dict(position_mm=position.tolist(), center_distance_mm=float(np.linalg.norm(position)), log_score=value,
                  optimizer_converged=success,
                  at_depth_boundary=bool(abs(depth-depths[0]) < .01 or abs(depth-MAX_DEPTH_MM) < .01),
                  at_lateral_slope_boundary=bool(np.any(np.abs(coordinate[:2]) >= SLOPE_LIMIT-1e-4)))
    if profile:
        result['depth_profile'] = [dict(row, loss_from_bounded_optimum=value-row['log_score']) for row in fixed]
    return result


def compare_position(fit_result, position, crystal_front, outer_front):
    fitted = np.asarray(fit_result['position_mm'])
    fitted_range, nominal_range = np.linalg.norm(fitted), np.linalg.norm(position)
    return dict(expected_position_mm=position, center_distance_mm=float(nominal_range),
                position_error_mm=math.dist(fitted, position), center_range_error_mm=float(fitted_range-nominal_range),
                fitted_z_above_crystal_front_mm=float(fitted[2]-crystal_front),
                fitted_z_above_outer_front_mm=float(fitted[2]-outer_front),
                true_z_above_crystal_front_mm=position[2]-crystal_front,
                true_z_above_outer_front_mm=position[2]-outer_front,
                direction_error_deg=math.degrees(math.atan2(np.linalg.norm(np.cross(fitted, position)), np.dot(fitted, position))))


def run(campaign, block_limit=None, *, write=True):
    """Fit every eligible trigger in the selected prefix of sealed ADC blocks."""
    campaign = Path(campaign)
    data = (campaign / 'campaign.json').read_bytes()
    config, binding = json.loads(data), digest(data)
    cohort, target, pins = selected_cohort(campaign, config, block_limit)
    output = campaign / 'range.json'
    if write and output.is_file():
        previous = json.loads(output.read_bytes())
        require(previous['campaign_sha256'] == binding and len(previous['processed_blocks']) <= len(cohort),
                'The existing range report covers different inputs or more blocks')
    settings = ResponseSettings(angular_nuisance_sigma_deg=config['plane']['sigma_deg'])
    front_bytes = ASSEMBLY.read_bytes()
    front = json.loads(front_bytes)['measured_front']
    crystal = front['crystal_front_z_mm']
    outer = crystal + front['crystal_to_outer_front_mm']
    z_min = outer + .1
    depths = np.r_[np.geomspace(z_min, MAX_DEPTH_MM, 21), FAR_DEPTH_MM]
    source_dir = Path(__file__).resolve().parent
    source_hashes = {name: digest((source_dir / name).read_bytes()) for name in
                     (Path(__file__).name, 'gegi_source_range.py', 'gegi_continuous_plane.py',
                      'gegi_joint_imaging.py', 'gegi_commercial_dual_prior.py')}
    require(source_hashes['gegi_continuous_plane.py'] == pins['gegi_continuous_plane.py'],
            'The acquisition requires its frozen cone kernel')
    blocks, provenance = load_events(campaign, config, binding, cohort, settings)
    middle = len(blocks)//2
    first, second = tuple(blocks)[:middle], tuple(blocks)[middle:]
    axis = np.linspace(-SLOPE_LIMIT, SLOPE_LIMIT, 13)
    slopes = np.array(list(itertools.product(axis, repeat=2)))
    fits = {}
    for label in LABELS:
        groups = [[event for name in names for event in blocks[name][label]] for names in (first, second)]
        scorer = AngularScore(*groups, settings)
        parity = scorer.validate(z_min)
        grid_scores = np.array([scorer.score(xyz(slopes, depth), *FIT_MODES) for depth in depths])
        nominal = fit(scorer, depths, slopes, grid_scores[:, :, 0], FIT_MODES[0], profile=True)
        sensitivity = fit(scorer, depths[:-1], slopes, grid_scores[:-1, :, 1], FIT_MODES[1], profile=False)
        halves = {mode[1]: fit(scorer, depths[:-1], slopes, grid_scores[:-1, :, index], mode, profile=False)
                  for index, mode in enumerate(FIT_MODES[2:], 2)}
        lines = (label,) if label == LINES[0] else LINES[1:]
        scorer.accounting['original_allowed_hypotheses'] = sum(row['measured_window_accounting'][line]['allowed_hypotheses']
                                                              for row in provenance.values() for line in lines)
        fits[label] = dict(accounting=scorer.accounting, split_selected_triggers=[len(group) for group in groups],
                           reference_maximum_relative_response_difference=parity, primary=nominal,
                           no_extra_background=sensitivity, split=halves,
                           split_position_disagreement_mm=math.dist(*(f['position_mm'] for f in halves.values())),
                           split_center_range_disagreement_mm=abs(halves['first']['center_distance_mm']-
                                                                  halves['second']['center_distance_mm']))
        print(f'{label}: {nominal["position_mm"]}, split agreement {fits[label]["split_center_range_disagreement_mm"]:.1f} mm',
              flush=True)

    # Only now read the nominal source coordinates for scoring the frozen fits.
    sources = {source['isotope']: source['position_mm'] for source in config['sources'].values()}
    for label, isotope in zip(LABELS, ('Cs-137', 'Co-60'), strict=True):
        result = fits[label]
        for model in (result['primary'], result['no_extra_background'], *result['split'].values()):
            model['held_out_source_comparison'] = compare_position(model, sources[isotope], crystal, outer)
    result = dict(kind='gegi_simultaneous_conditional_source_range_v1', campaign_sha256=binding, assembly_sha256=digest(front_bytes),
                  cohort=dict(selected_blocks=len(blocks), planned_blocks=target, first_block=first[0], last_block=second[-1]),
                  source_sha256=source_hashes, runtime=dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__),
                  method=('Sum of per-trigger log angular density relative to uniform angle. Order weights are preserved '
                          'inside each event mixture, with uniform angle allocated to its unresolved mass and one fixed '
                          'source-independent contamination fraction tested against zero additional contamination. '
                          'An unresolved-only trigger contributes zero relative log score. A trial source is a single 3D '
                          'point in detector coordinates. The conditional model omits rate, efficiency and spatial normalization. '
                          'The profile reoptimizes x/z and y/z at each fixed z. Score differences are diagnostics, without '
                          'calibrated confidence coverage. The 10 km point is an effectively far-field geometric comparison.'),
                  settings=dict(primary_extra_uniform_angle_fraction=EXTRA_BACKGROUND, angular_nuisance_sigma_deg=settings.angular_nuisance_sigma_deg,
                                z_bounds_mm=[z_min, MAX_DEPTH_MM], x_over_z_bounds=[-SLOPE_LIMIT, SLOPE_LIMIT],
                                y_over_z_bounds=[-SLOPE_LIMIT, SLOPE_LIMIT], crystal_front_z_mm=crystal,
                                outer_cover_front_z_mm=outer, far_compare_z_mm=FAR_DEPTH_MM,
                                coarse_batch_point_cone_budget=POINT_CONE_BUDGET),
                  line_windows_keV={label: [e-max(5., .02*e), e+max(5., .02*e)]
                                    for label, e in zip(LINES, plane.LINE_ENERGIES_KEV, strict=True)},
                  split_blocks=dict(first=first, second=second), processed_blocks=provenance, fits=fits)
    if write:
        atomic_json(output, result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign', type=Path, default=CAMPAIGN)
    parser.add_argument('--blocks', type=int, help='Use the first N admitted blocks (default: full planned campaign)')
    args = parser.parse_args()
    run(args.campaign, args.blocks)
