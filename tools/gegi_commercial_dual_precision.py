"""Sampling variation across complete, independent common-clock acquisition blocks."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.stats import beta

import gegi_commercial_dual_prior as priors


def ratio(by_block, draws):
    counts = np.asarray(by_block, dtype=int)
    num, den = counts.sum(axis=0)
    sampled = draws @ counts
    valid = sampled[:, 1] > 0
    rates = sampled[valid, 0] / sampled[valid, 1]
    return dict(numerator=int(num), denominator=int(den), estimate=float(num/den) if den else None,
                percentile_95=np.quantile(rates, [.025, .975]).tolist() if len(rates) else None,
                resamples_with_denominator=int(valid.sum()))


def image_variation(maps, draws, grid, position):
    data = np.asarray(maps)
    yy, xx = np.meshgrid(grid['y_mm'], grid['x_mm'], indexing='ij')
    x, y = xx.ravel(), yy.ravel()
    distances, on_edge, same_side = [], [], []
    for start in range(0, len(draws), 100):
        pool = draws[start:start+100] @ data.reshape(len(data), -1)
        # A zero image carries no peak coordinate.
        idx = pool[pool.max(axis=1) > 0].argmax(axis=1)
        distances.extend(np.hypot(x[idx]-position[0], y[idx]-position[1]))
        on_edge.extend((abs(x[idx]) == abs(x[0])) | (abs(y[idx]) == abs(y[0])))
        same_side.extend(x[idx]*position[0] > 0)
    if not distances:
        return dict(nonempty_resamples=0)
    return dict(nonempty_resamples=len(distances),
                peak_offset_mm_p025_median_p975=np.quantile(distances, [.025, .5, .975]).tolist(),
                fraction_maximum_on_source_side=float(np.mean(same_side)),
                fraction_maximum_at_boundary=float(np.mean(on_edge)))


def history_order_rate(ordering, draws):
    summary = ratio(ordering, draws)
    k, n = summary['numerator'], summary['denominator']
    summary['exact_binomial_95_if_independent_histories'] = [
        float(beta.ppf(.025, k, n-k+1)) if k else 0.,
        float(beta.ppf(.975, k+1, n-k)) if k < n else 1.,
    ] if n else None
    return summary


def cobalt_view(layers, grid):
    """Pool measured disjoint energy windows at their original projected mass."""
    names = sorted(key for key, layer in layers.items()
                   if layer.get('held_out_position_comparison', {}).get('source') == 'co60-right')
    if len(names) != 2:
        raise ValueError('Expected the two distinct cobalt line windows')
    first, second = (layers[name] for name in names)
    mass = np.asarray(first['mass']) + np.asarray(second['mass'])
    position = first['held_out_position_comparison']['source_position_mm']
    peak, offset = None, None
    if mass.max() > 0:
        iy, ix = np.unravel_index(np.argmax(mass), mass.shape)
        peak = [grid['x_mm'][ix], grid['y_mm'][iy], grid['assumed_z_mm']]
        offset = float(np.linalg.norm(np.subtract(peak, position)))
    return dict(line_windows=names, source_position_mm=position, peak_position_mm=peak, peak_offset_mm=offset,
                **{key: first[key]+second[key] for key in ('triggers', 'triggers_with_geometry',
                                                           'projected_mass', 'unresolved_mass')}), mass


def summarize(campaign, seed=20261119, replicas=2000):
    original = (campaign/'results.json').read_bytes()
    result = json.loads(original)
    names = list(result['completed_blocks'])
    clock = result['clock_reference']['blocks']
    if names != result['planned_blocks'] or set(names) != set(clock):
        raise ValueError('Sampling intervals require the complete measured and clock-reference cohort')
    rng = np.random.default_rng(seed)
    draws = rng.multinomial(len(names), np.full(len(names), 1/len(names)), size=replicas)
    layers = result['imaging']['layers']
    lines = {name: [] for name in layers if name.endswith('_keV')}
    alternate_lines = {line: [] for line in lines}
    alternate_bytes = (campaign/'alternate-prior.json').read_bytes()
    alternate = json.loads(alternate_bytes)
    config_bytes = (campaign/'campaign.json').read_bytes()
    binding = hashlib.sha256(config_bytes).hexdigest()
    if (alternate['status'] != 'completed' or set(alternate['processed_blocks']) != set(names)
            or alternate['campaign_sha256'] != binding or result['configuration_sha256'] != binding):
        raise ValueError('Both prior comparisons must refer to the same complete campaign')
    config = json.loads(config_bytes)
    grid = result['imaging']['grid']
    shape = (len(grid['y_mm']), len(grid['x_mm']))
    for name in names:
        _, maps = priors.load_shard(campaign/name, config, binding, shape)
        for line in lines:
            lines[line].append(maps[priors.AREA][line][1])
            alternate_lines[line].append(maps[priors.SOLID][line][1])
    for prior, samples in ((priors.AREA, lines), (priors.SOLID, alternate_lines)):
        for line, maps in samples.items():
            np.testing.assert_allclose(np.sum(maps, axis=0), alternate['pooled'][prior][line]['mass_trigger_units'],
                                       rtol=1e-12, atol=1e-12)
    output = {}
    for line, maps in lines.items():
        heldout = layers[line]['held_out_position_comparison']
        source, position = heldout['source'], heldout['source_position_mm']
        counts, ordering = [], []
        for name in names:
            cell = result['blocks'][name]['imaging'][line]
            counts.append((cell['triggers_with_geometry'], cell['triggers']))
            orders = clock[name]['history_orders'].get(source, {}).get(line, {}).get(
                'full_energy_globally_allowed_orders_by_original_parent', {})
            correct = orders.get('only_order_agrees', 0)
            sole = correct + orders.get('only_order_reversed', 0) + orders.get('only_order_wrong_pair', 0)
            ordering.append((correct, sole))
        output[line] = dict(projected_fraction_of_two_strip_window=ratio(counts, draws),
                            source_history_sole_order_correct_fraction=history_order_rate(ordering, draws),
                            blind_peak=image_variation(maps, draws, grid, position),
                            solid_angle_blind_peak=image_variation(alternate_lines[line], draws, grid, position))
    overlap = [clock[name]['overlap_counts']['all_qualified'] for name in names]
    cobalt, _ = cobalt_view(layers, result['imaging']['grid'])
    first, second = cobalt['line_windows']
    combined = np.asarray(lines[first]) + np.asarray(lines[second])
    cobalt['blind_peak'] = image_variation(combined, draws, grid, cobalt['source_position_mm'])
    solid_combined = np.asarray(alternate_lines[first]) + np.asarray(alternate_lines[second])
    cobalt['solid_angle_blind_peak'] = image_variation(solid_combined, draws, grid, cobalt['source_position_mm'])
    return dict(kind='gegi_simultaneous_block_sampling_v1', completed_blocks=names, seed=seed,
                resamples=replicas, results_sha256=hashlib.sha256(original).hexdigest(),
                alternate_prior_sha256=hashlib.sha256(alternate_bytes).hexdigest(), lines=output, combined_cobalt=cobalt,
                mixed_rise_fraction=ratio([(b['mixed_source_merged_timing_graph'], b['qualified_triggers'])
                                           for b in overlap], draws),
                method='Draw complete 250-ms exposures with replacement, preserving signal overlap and repeated '
                       'source histories within each block. All input source chunks are disjoint across blocks. '
                       'Percentiles describe sampling variation under this simulated acquisition. The order fraction '
                       'is conditional on a full-energy two-significant-interaction reference of the expected isotope '
                       'and one consistently allowed order. Other classes retain their counts in results.json. '
                       'Paired image maxima use both cell priors on the same stored cones and original order weights; source positions '
                       'are used only for evaluation. Model and instrument systematics are outside this interval.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('campaign', type=Path)
    args = parser.parse_args()
    result = summarize(args.campaign)
    out = args.campaign/'sampling-intervals.json'
    temporary = out.with_suffix('.tmp')
    temporary.write_text(json.dumps(result, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    temporary.replace(out)
