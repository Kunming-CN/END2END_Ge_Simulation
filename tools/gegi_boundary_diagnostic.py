"""Bounded saved-cone diagnostics; never selects hypotheses using source truth.

All alternative maps are diagnostic ablations, not accepted reconstruction or a
retuning of the frozen analysis. This tool reads saved inputs and writes only its
explicit derivative output folder. No Geant4, SSD, calibration or random sampling.
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import math
from pathlib import Path
import platform
import time

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SIGMA_DEG = 5.0
PLANE_Z_MM = 40.0
STEP_MM = 2.0
PITCH_MM = 4.937480624253117
_SPHERE_NODES, _SPHERE_WEIGHTS = np.polynomial.legendre.leggauss(256)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def describe(values):
    a = np.asarray(values, dtype=float)
    if not a.size:
        return {"count": 0}
    return dict(count=int(a.size), minimum=float(a.min()), p10=float(np.quantile(a, .1)),
                median=float(np.median(a)), p90=float(np.quantile(a, .9)),
                maximum=float(a.max()), mean=float(a.mean()))


def angular_residual(candidate, source, finite_vertex=True):
    ray = np.asarray(source, dtype=float)
    if finite_vertex:
        ray = ray-np.asarray(candidate['vertex_mm'])
    ray /= np.linalg.norm(ray)
    return float(np.degrees(np.arccos(np.clip(ray @ candidate['axis'], -1, 1)))
                 - candidate['half_angle_deg'])


def sphere_integral(theta_deg):
    """Full sphere angular Gaussian integral, Gauss-Legendre quadrature in theta."""
    theta = (_SPHERE_NODES+1)*math.pi/2
    return float(math.pi**2*np.sum(_SPHERE_WEIGHTS*np.sin(theta)*np.exp(
        -.5*((np.degrees(theta)-theta_deg)/SIGMA_DEG)**2)))


def peak_stats(values, ticks, truth):
    r, c = np.unravel_index(np.argmax(values), values.shape)
    peak = float(values[r, c])
    # Four cells tie in distance to the exact truth; their mean avoids one-sided sampling.
    ix = np.flatnonzero(abs(ticks-truth[0]) <= STEP_MM/2+1e-9)
    iy = np.flatnonzero(abs(ticks-truth[1]) <= STEP_MM/2+1e-9)
    truth_score = float(values[np.ix_(iy, ix)].mean())
    total = float(np.sum(values)*STEP_MM**2)
    edge = np.zeros_like(values, dtype=bool)
    edge[:5, :] = edge[-5:, :] = edge[:, :5] = edge[:, -5:] = True
    return {"peak_xy_mm": [float(ticks[c]), float(ticks[r])], "peak_score": peak,
            "peak_on_outermost_cell": bool(r in (0, len(ticks)-1) or c in (0, len(ticks)-1)),
            "truth_evaluation_only": {"mean_of_adjacent_cell_scores": truth_score,
                "score_to_peak_ratio": truth_score/peak if peak else None,
                "peak_distance_mm": math.hypot(ticks[c]-truth[0], ticks[r]-truth[1])},
            "plane_integral": total,
            "outer_10mm_score_fraction": float(values[edge].sum()/values.sum()) if total else None}


def grids(events, extent, truths, expanded=False):
    ticks = np.arange(-extent+STEP_MM/2, extent, STEP_MM)
    xx, yy = np.meshgrid(ticks, ticks)
    variants = ('finite_plane_normalized',) if expanded else (
        'finite_plane_normalized', 'raw_angular_kernel', 'full_sphere_angular_density',
        'full_sphere_projected_area_density', 'single_candidate_groups_only')
    maps = {g: {name: np.zeros_like(xx) for name in variants} for g in truths}
    candidate_metrics = []
    for event_index, event in enumerate(events):
        for candidate_index, candidate in enumerate(event['cones']):
            vertex, axis = np.asarray(candidate['vertex_mm']), np.asarray(candidate['axis'])
            dx, dy, dz = xx-vertex[0], yy-vertex[1], PLANE_Z_MM-vertex[2]
            distance = np.sqrt(dx*dx+dy*dy+dz*dz)
            angle = np.degrees(np.arccos(np.clip((dx*axis[0]+dy*axis[1]+dz*axis[2])/distance, -1, 1)))
            residual = angle-candidate['half_angle_deg']
            score = np.exp(-.5*(residual/SIGMA_DEG)**2)
            norm = float(score.sum()*STEP_MM**2)
            if norm <= 0:
                raise ValueError('Kernel underflow: retain original cone and investigate')
            weight = candidate['weight']
            target = maps[event['source_group']]
            target['finite_plane_normalized'] += weight*score/norm
            if expanded:
                continue
            full_norm = sphere_integral(candidate['half_angle_deg'])
            jacobian = abs(dz)/distance**3
            target['raw_angular_kernel'] += weight*score
            target['full_sphere_angular_density'] += weight*score/full_norm
            target['full_sphere_projected_area_density'] += weight*score/full_norm*jacobian
            if len(event['cones']) == 1:
                target['single_candidate_groups_only'] += weight*score/norm
            candidate_metrics.append({"event_index": event_index, "candidate_index": candidate_index,
                "source_group": event['source_group'], "weight": weight,
                "minimum_absolute_plane_residual_deg": float(np.min(abs(residual))),
                "maximum_raw_kernel_score": float(score.max()),
                "plane_normalizer_mm2": norm,
                "full_sphere_normalizer_sr": full_norm,
                "fraction_of_sphere_kernel_on_finite_plane": float((score*jacobian).sum()*STEP_MM**2/full_norm)})
    return ticks, maps, candidate_metrics


def contribution_at_peak(events, metrics, peak_by_source):
    values = collections.defaultdict(list)
    for metric in metrics:
        event = events[metric['event_index']]
        candidate = event['cones'][metric['candidate_index']]
        peak = peak_by_source[event['source_group']]
        point = [*peak, PLANE_Z_MM]
        residual = angular_residual(candidate, point)
        contribution = candidate['weight']*math.exp(-.5*(residual/SIGMA_DEG)**2)/metric['plane_normalizer_mm2']
        values[event['source_group']].append((contribution, metric))
    result = {}
    for group, rows in values.items():
        total = sum(x for x, _ in rows)
        dominant = []
        for contribution, metric in sorted(rows, key=lambda item: item[0], reverse=True)[:5]:
            event = events[metric['event_index']]
            candidate = event['cones'][metric['candidate_index']]
            dominant.append({"campaign_initial_id": event['campaign_initial_id'],
                "pulse_group_id": event['pulse_group_id'], "chunk_index": event['chunk_index'],
                "store_ref": event['store_ref'], "candidate_index": metric['candidate_index'],
                "candidate_count_in_group": len(event['cones']), "order": candidate['order'],
                "pairing_index": candidate['pairing_index'], "vertex_mm": candidate['vertex_mm'],
                "axis": candidate['axis'], "half_angle_deg": candidate['half_angle_deg'],
                "site_separation_mm": candidate['site_separation_mm'],
                "peak_score_fraction": contribution/total,
                "minimum_absolute_plane_residual_deg": metric['minimum_absolute_plane_residual_deg'],
                "maximum_raw_kernel_score": metric['maximum_raw_kernel_score'],
                "plane_normalizer_mm2": metric['plane_normalizer_mm2'],
                "fraction_of_sphere_kernel_on_finite_plane": metric['fraction_of_sphere_kernel_on_finite_plane']})
        result[group] = {"contribution_sum": total,
            "top_1_candidate_fraction": max(x for x, _ in rows)/total,
            "top_5_candidates_fraction": sum(sorted((x for x, _ in rows), reverse=True)[:5])/total,
            "from_minimum_plane_residual_above_15deg_fraction": sum(x for x, m in rows if m['minimum_absolute_plane_residual_deg'] > 15)/total,
            "from_minimum_plane_residual_above_25deg_fraction": sum(x for x, m in rows if m['minimum_absolute_plane_residual_deg'] > 25)/total,
            "from_sphere_support_below_1percent_fraction": sum(x for x, m in rows if m['fraction_of_sphere_kernel_on_finite_plane'] < .01)/total,
            "from_sphere_support_below_one_millionth_fraction": sum(x for x, m in rows if m['fraction_of_sphere_kernel_on_finite_plane'] < 1e-6)/total,
            "top_5_candidate_details": dominant}
    return result


def diagnose(input_dir, output_dir):
    import gegi_campaign_analysis as analysis
    started = time.perf_counter()
    inputs = [input_dir/name for name in ('summary.json', 'maps.json', 'cones.jsonl')]
    inputs += [ROOT/'tools/gegi_imaging.py', ROOT/'tools/gegi_campaign_analysis.py', Path(__file__).resolve()]
    hashes = {str(p.relative_to(ROOT)).replace('\\', '/'): sha(p) for p in inputs}
    summary = json.loads((input_dir/'summary.json').read_text(encoding='utf-8'))
    saved_maps = json.loads((input_dir/'maps.json').read_text(encoding='utf-8'))
    events = [json.loads(line) for line in (input_dir/'cones.jsonl').read_text(encoding='utf-8').splitlines()]
    truths = {k: v['truth_position_mm_for_evaluation_only'] for k, v in summary['groups'].items()}
    assert all(v[2] == PLANE_Z_MM for v in truths.values())
    assert len(events) == sum(v['counts']['imaging_accepted_groups'] for v in summary['groups'].values())
    assert all(math.isclose(sum(c['weight'] for c in e['cones']), 1, abs_tol=1e-12) for e in events)
    ticks, maps, metrics = grids(events, 120., truths)
    expanded_ticks, expanded, _ = grids(events, 240., truths, expanded=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    stats, group_rows = {}, []
    for group, truth in truths.items():
        group_events = [e for e in events if e['source_group'] == group]
        group_candidates = [c for e in group_events for c in e['cones']]
        group_metrics = [m for m in metrics if m['source_group'] == group]
        reference = np.asarray(saved_maps['groups'][group]['all']['plane']['values'])
        reconstructed = maps[group]['finite_plane_normalized']
        max_difference = float(np.max(abs(reference-reconstructed)))
        assert np.allclose(reference, reconstructed, atol=1e-14, rtol=1e-12), group
        map_stats = {name: peak_stats(a, ticks, truth) for name, a in maps[group].items()}
        map_stats['expanded_240mm_finite_plane_normalized'] = peak_stats(expanded[group]['finite_plane_normalized'], expanded_ticks, truth)
        residuals, minimums, ff_minimums, parallax, separations, z = [], [], [], [], [], []
        split = collections.defaultdict(list)
        for event in group_events:
            rs = [angular_residual(c, truth) for c in event['cones']]
            ff = [angular_residual(c, truth, False) for c in event['cones']]
            residuals.extend(rs); minimums.append(min(map(abs, rs))); ff_minimums.append(min(map(abs, ff)))
            separations.append(min(c['site_separation_mm'] for c in event['cones']))
            for c in event['cones']:
                first = np.asarray(c['vertex_mm'])
                second = first-np.asarray(c['axis'])*c['site_separation_mm']
                z.extend([first[2], second[2]])
                truth_far = np.asarray(truth)/np.linalg.norm(truth)
                truth_near = np.asarray(truth)-first; truth_near /= np.linalg.norm(truth_near)
                parallax.append(float(np.degrees(np.arccos(np.clip(truth_far @ truth_near, -1, 1)))))
            sep = separations[-1]
            split['under_10mm' if sep < 10 else '10_to_20mm' if sep < 20 else '20mm_or_more'].append(minimums[-1])
            group_rows.append({"source_group": group, "campaign_initial_id": event['campaign_initial_id'],
                "pulse_group_id": event['pulse_group_id'], "candidate_count": len(rs),
                "strip_pairing_count": len(set(c['pairing_index'] for c in event['cones'])),
                "minimum_site_separation_mm": sep,
                "nearest_candidate_absolute_finite_vertex_residual_deg_EVALUATION_ONLY": minimums[-1],
                "nearest_candidate_absolute_far_field_residual_deg_EVALUATION_ONLY": ff_minimums[-1],
                "all_candidate_signed_finite_vertex_residuals_deg_EVALUATION_ONLY": json.dumps(rs, separators=(',', ':'))})
        n = len(group_events)
        stats[group] = {"accepted_groups": n, "candidate_count": len(group_candidates),
            "candidate_count_histogram": dict(collections.Counter(len(e['cones']) for e in group_events)),
            "strip_pairing_count_histogram": dict(collections.Counter(len(set(c['pairing_index'] for c in e['cones'])) for e in group_events)),
            "baseline_maximum_absolute_difference_from_saved_map": max_difference,
            "maps": map_stats,
            "finite_plane_kernel": {"minimum_absolute_residual_deg": describe([m['minimum_absolute_plane_residual_deg'] for m in group_metrics]),
                "plane_normalizer_mm2": describe([m['plane_normalizer_mm2'] for m in group_metrics]),
                "fraction_of_full_sphere_kernel_on_plane": describe([m['fraction_of_sphere_kernel_on_finite_plane'] for m in group_metrics]),
                "candidates_minimum_residual_above_15deg": sum(m['minimum_absolute_plane_residual_deg'] > 15 for m in group_metrics),
                "candidates_sphere_support_below_one_millionth": sum(m['fraction_of_sphere_kernel_on_finite_plane'] < 1e-6 for m in group_metrics)},
            "truth_evaluation_only": {"all_candidate_signed_residual_deg": describe(residuals),
                "nearest_candidate_absolute_finite_vertex_residual_deg": describe(minimums),
                "groups_with_any_candidate_within_5deg": sum(v <= 5 for v in minimums),
                "groups_with_any_candidate_within_15deg": sum(v <= 15 for v in minimums),
                "nearest_candidate_absolute_far_field_residual_deg": describe(ff_minimums),
                "finite_vertex_vs_origin_ray_angle_deg": describe(parallax),
                "nearest_residual_by_minimum_separation": {k: describe(v) for k, v in split.items()},
                "rule": "The closest candidate is an evaluation bound only; no map selects or reweights a cone with truth."},
            "minimum_site_separation_mm_per_group": describe(separations),
            "candidate_site_depth_mm_with_repetition": describe(z),
            "strip_quantization_scale": {"pitch_mm": PITCH_MM,
                "single_site_uniform_strip_coordinate_sigma_mm": PITCH_MM/math.sqrt(12),
                "difference_of_two_independent_uniform_strip_errors_sigma_mm": PITCH_MM/math.sqrt(6),
                "transverse_axis_angle_scale_at_median_separation_deg": math.degrees(math.atan(PITCH_MM/math.sqrt(6)/np.median(separations))),
                "assumption": "Per-coordinate uniform independent within-strip uncertainty; illustrative first-order scale, not measured angular resolution or a covariance model."}}
    peaks = {g: stats[g]['maps']['finite_plane_normalized']['peak_xy_mm'] for g in truths}
    for g, values in contribution_at_peak(events, metrics, peaks).items():
        stats[g]['baseline_peak_contributors'] = values
    mixture_stats = {}
    for mixture_name, mixture in summary['mixtures'].items():
        mixture_stats[mixture_name] = {"initial_denominators": mixture['initial_denominators'],
            "normalization": mixture['normalization'], "diagnostic_maps": {}}
        for variant in maps[mixture['components'][0]]:
            value = sum(maps[g][variant]*(.5/summary['groups'][g]['initial_primary_denominator']) for g in mixture['components'])
            image = {"x_mm": ticks.tolist(), "y_mm": ticks.tolist(), "plane_z_mm": PLANE_Z_MM, "values": value.tolist()}
            detected = analysis.detect_peaks(image, 'plane', count=2)
            mixture_stats[mixture_name]['diagnostic_maps'][variant] = {
                "blind_peaks_using_frozen_detection_rule": detected,
                "no_success_or_localization_decision": True}
            if variant == 'finite_plane_normalized':
                reference = np.asarray(saved_maps['mixtures'][mixture_name]['all']['plane']['values'])
                assert np.allclose(value, reference, atol=1e-19, rtol=1e-12)
                mixture_stats[mixture_name]['maximum_absolute_difference_from_saved_map'] = float(np.max(abs(value-reference)))
    # Algebra checks use saved signal positions, energies and metadata only.
    candidates = [c for e in events for c in e['cones']]
    axis_errors = [abs(np.linalg.norm(c['axis'])-1) for c in candidates]
    energy_errors = [abs(c['cos_theta']-(1-510.99895069*(1/c['absorbed_energy_keV']-1/(c['scatter_energy_keV']+c['absorbed_energy_keV'])))) for c in candidates]
    nodes128, weights128 = np.polynomial.legendre.leggauss(128)
    theta128 = (nodes128+1)*math.pi/2
    quadrature_errors = [abs(float(math.pi**2*np.sum(weights128*np.sin(theta128)*np.exp(
        -.5*((np.degrees(theta128)-c['half_angle_deg'])/SIGMA_DEG)**2)))/sphere_integral(c['half_angle_deg'])-1) for c in candidates]
    assert max(quadrature_errors) < 1e-10
    xy_lattice_errors = []
    for c in candidates:
        v = np.asarray(c['vertex_mm']); second = v-np.asarray(c['axis'])*c['site_separation_mm']
        xy_lattice_errors.extend(abs(value/PITCH_MM-(round(value/PITCH_MM-.5)+.5)) for value in [v[0], v[1], second[0], second[1]])
    pooled_maps = {variant: sum(maps[g][variant] for g in truths) for variant in next(iter(maps.values()))}
    pooled_expanded = sum(expanded[g]['finite_plane_normalized'] for g in truths)
    pooled_results = {"accepted_groups": len(events), "candidate_count": len(candidates),
        "rule": "Anonymous concatenation of all four saved component datasets; original candidate weights sum to one per accepted group. No component/source-dependent rescaling. No calibrated activity, efficiency or physically simultaneous-source claim; photon and decay denominators remain separate.",
        "diagnostic_maps": {}}
    pooled_plot_stats = {"accepted_groups": len(events), "maps": {}}
    for variant, value in {**pooled_maps, 'expanded_240mm_finite_plane_normalized': pooled_expanded}.items():
        grid = expanded_ticks if variant.startswith('expanded') else ticks
        row, col = np.unravel_index(np.argmax(value), value.shape)
        image = {"x_mm": grid.tolist(), "y_mm": grid.tolist(), "plane_z_mm": PLANE_Z_MM, "values": value.tolist()}
        pooled_results['diagnostic_maps'][variant] = {
            "blind_peaks_using_frozen_detection_rule": analysis.detect_peaks(image, 'plane', count=2),
            "global_peak_xy_mm": [float(grid[col]), float(grid[row])],
            "no_success_or_localization_decision": True}
        pooled_plot_stats['maps'][variant] = {"peak_xy_mm": [float(grid[col]), float(grid[row])]}
    assert math.isclose(float(pooled_maps['finite_plane_normalized'].sum()*STEP_MM**2), len(events), rel_tol=1e-12)
    figure_path = output_dir/'boundary_comparison.png'
    plot({**maps, 'all-four-pooled': pooled_maps}, ticks,
         {**expanded, 'all-four-pooled': {'finite_plane_normalized': pooled_expanded}}, expanded_ticks,
         truths, {**stats, 'all-four-pooled': pooled_plot_stats}, figure_path)
    with (output_dir/'accepted_group_geometry.csv').open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(group_rows[0])); writer.writeheader(); writer.writerows(group_rows)
    report = {"kind": "gegi_saved_cone_boundary_diagnostic_v1", "input_sha256": hashes,
        "scope": f"{len(events)} saved accepted pulse groups only; no transport, native drift, recalibration, new random draws, or production mutation.",
        "findings": [
            "Per-square normalization is a demonstrated proximate cause of the three component corner maxima: same cones and weights with normalization removed yield interior maxima, while exact contributor accounting shows domination by cones with tiny square support.",
            "The separate component maxima improving does not establish source separation: neither original two-component mixture recovers both true source locations using the diagnostic raw kernel and the frozen blind peak detector. Anonymous pooling of all four components is also retained for inspection.",
            "This does not identify why those reconstructed cones are inconsistent with the source. Wrong effective two-site topology, timing depth errors, strip quantization and kinematic ambiguity require separate evidence.",
            "The unique-candidate subset still produces boundary maxima for all four components; candidate-order ambiguity alone does not explain the artifact.",
            f"{sum(len(set(c['pairing_index'] for c in e['cones'])) > 1 for e in events)} groups have multiple strip pairings; {sum(len(e['cones']) > 1 for e in events)}/{len(events)} groups retain multiple cone candidates. Equal hypotheses distribute signal weight over incompatible source loci.",
            "Far-field source rays differ from the finite-vertex source rays by median 21.5 to 26.2 degrees per component, far larger than the fixed 5-degree kernel. The finite-plane diagnostic includes vertices already, so this cannot explain its corner artifact.",
            "Alternative normalizations answer different statistical questions. The raw kernel and sphere-to-area maps are diagnostic controls, not a calibrated detector likelihood or an authorized production change."],
        "map_definitions": {
            "finite_plane_normalized": "sum w*K / integral_square(K dA); each candidate forced to contribute its full declared weight inside +/-120 mm square",
            "raw_angular_kernel": "sum w*K; isolates removal of finite-plane per-candidate normalization; arbitrary score units",
            "full_sphere_angular_density": "sum w*K / integral_sphere(K dOmega), sampled with finite vertices on z=40 mm; units weighted groups/sr",
            "full_sphere_projected_area_density": "sum w*K / integral_sphere(K dOmega) * abs(z-z_vertex)/distance^3; geometric solid-angle-to-area transform, not calibrated detector sensitivity",
            "single_candidate_groups_only": "only already unambiguous groups; no truth selection, finite-plane kernel unchanged; a different lower-count sample",
            "expanded_240mm_finite_plane_normalized": "same candidate list/kernel/2 mm bins, only square edges expanded from +/-120 to +/-240 mm"},
        "kernel_sigma_deg": SIGMA_DEG, "plane_z_mm": PLANE_Z_MM, "plane_step_mm": STEP_MM,
        "groups": stats,
        "mixtures": mixture_stats,
        "all_four_anonymous_pool": pooled_results,
        "axis_and_energy_identity_checks": {"maximum_axis_norm_error": max(axis_errors),
            "maximum_compton_cosine_identity_error": max(energy_errors),
            "maximum_strip_half_integer_lattice_error_in_pitch_units": max(xy_lattice_errors),
            "axis_convention": "axis=(r1-r2)/|r1-r2| and source ray=(source-r1)/|source-r1|. Both are negatives of the corresponding photon propagation vectors, so their angle is the physical Compton scatter angle. No 180-degree flip is required.",
            "coordinate_convention": "Cartesian x/y as stored, z=40 mm plane. Direction azimuth atan2(y,x), elevation asin(z/r). This verifies implementation consistency only; external registration requires transport geometry/truth comparison."},
        "limitations": [
            "No diagnostic variant is labeled a repaired or validated reconstruction. Scores have different units and are compared by peak position and within-map normalized displays only.",
            "Finite-plane normalization can amplify tiny nonintersecting-cone tails; raw and sphere variants isolate that effect but do not resolve interaction ordering, depth bias, Doppler broadening, calibrated noise or detector sensitivity.",
            "Candidate weights remain the frozen equal-per-group convention. Kinematically allowed alternatives are not calibrated posterior probabilities.",
            "Nearest-candidate truth residual is an optimistic evaluation bound, never a hypothesis choice in any map.",
            "Strip coordinate quantization and short separation give an expected angular sensitivity scale. Saved cones alone cannot establish the accuracy of timing-derived depth; that requires a separate saved-truth site association.",
            "The z=40 mm plane is assumed and uses finite vertices. The far-field direction map ignores vertex offset; near sources make these physically different diagnostics.",
            "Expanding field of view changes normalization and each candidate contribution. A peak on the expanded edge is evidence of domain dependence, not a distance estimate.",
            "No experimental agreement, physical angular resolution, source separation or successful localization is claimed."],
        "runtime_seconds": time.perf_counter()-started,
        "environment": {"python": platform.python_version(), "numpy": np.__version__},
        "checks": {"saved_plane_maps_reproduced": True, "all_group_weights_sum_one": True,
                   "source_truth_used_to_construct_maps": False, "input_hashes_unchanged_after_run": None,
                   "accepted_group_count": len(events), "candidate_count": len(candidates),
                   "ambiguous_group_count": sum(len(e['cones']) > 1 for e in events),
                   "multiple_strip_pairing_group_count": sum(len(set(c['pairing_index'] for c in e['cones'])) > 1 for e in events)},
        "outputs": {"comparative_figure": figure_path.name, "per_group_evaluation": "accepted_group_geometry.csv"}}
    assert hashes == {str(p.relative_to(ROOT)).replace('\\', '/'): sha(p) for p in inputs}, 'An input changed'
    report['checks']['input_hashes_unchanged_after_run'] = True
    report['checks']['maximum_relative_difference_full_sphere_quadrature_128_vs_256_nodes'] = max(quadrature_errors)
    (output_dir/'report.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps({"runtime_seconds": report['runtime_seconds'], "groups": {g: {
        "candidate_histogram": s['candidate_count_histogram'], "peaks": {k: v['peak_xy_mm'] for k, v in s['maps'].items()},
        "baseline_peak_contributors": {k: v for k, v in s['baseline_peak_contributors'].items() if k != 'top_5_candidate_details'},
        "nearest_truth_residual_median_deg": s['truth_evaluation_only']['nearest_candidate_absolute_finite_vertex_residual_deg']['median']
        } for g, s in stats.items()}}, indent=2))


def plot(maps, ticks, expanded, expanded_ticks, truths, stats, path):
    from PIL import Image, ImageDraw, ImageFont
    groups = ['gamma-left', 'gamma-right', 'cs137-left', 'co60-right', 'all-four-pooled']
    names = ['finite_plane_normalized', 'raw_angular_kernel', 'full_sphere_projected_area_density', 'expanded_240mm_finite_plane_normalized']
    titles = ['Frozen finite-square normalization', 'Same cones; raw angular kernel', 'Sphere kernel x solid angle/area', 'Frozen rule; doubled field of view']
    image = Image.new('RGB', (1880, 2445), 'white')
    draw = ImageDraw.Draw(image)
    fonts = {size: ImageFont.truetype('C:/Windows/Fonts/arial.ttf', size) for size in (18, 20, 23, 30)}
    draw.text((50, 18), 'Saved GeGI cones: boundary normalization changes peak location', fill='black', font=fonts[30])
    draw.text((50, 60), 'Four components and their anonymous pool. Cyan x: blind maximum. Green +: truth for evaluation only. z = 40 mm.', fill='black', font=fonts[23])
    draw.text((50, 96), 'Each panel is divided by its own maximum. Different columns have different score units; none is a validated repair.', fill='black', font=fonts[20])
    anchors = np.array([[0, 0, 4], [60, 15, 80], [140, 41, 129], [222, 73, 104], [254, 159, 109], [252, 253, 191]], dtype=float)
    ramp = np.linspace(0, 1, len(anchors))
    for row, group in enumerate(groups):
        for col, name in enumerate(names):
            is_expanded = name.startswith('expanded')
            a = expanded[group]['finite_plane_normalized'] if is_expanded else maps[group][name]
            extent = 240 if is_expanded else 120
            score = np.flipud(a/a.max())
            rgb = np.stack([np.interp(score, ramp, anchors[:, i]) for i in range(3)], axis=2).astype(np.uint8)
            left, top, size = 60+col*455, 205+row*435, 365
            image.paste(Image.fromarray(rgb).resize((size, size), Image.Resampling.NEAREST), (left, top))
            peak = stats[group]['maps'][name]['peak_xy_mm']
            def point(xy):
                return (left+(xy[0]+extent)/(2*extent)*size, top+(extent-xy[1])/(2*extent)*size)
            px, py = point(peak)
            draw.line((px-7, py-7, px+7, py+7), fill='cyan', width=3)
            draw.line((px-7, py+7, px+7, py-7), fill='cyan', width=3)
            markers = [truths[group][:2]] if group != 'all-four-pooled' else [list(v) for v in sorted(set(tuple(t[:2]) for t in truths.values()))]
            for marker in markers:
                tx, ty = point(marker)
                draw.line((tx-8, ty, tx+8, ty), fill='lime', width=3)
                draw.line((tx, ty-8, tx, ty+8), fill='lime', width=3)
            draw.rectangle((left, top, left+size, top+size), outline='black', width=1)
            if row == 0: draw.text((left, 154), titles[col], fill='black', font=fonts[20])
            draw.text((left, top-25), f'{group} | {stats[group]["accepted_groups"]} groups', fill='black', font=fonts[20])
            for v in (-extent, 0, extent):
                x, y = point((v, v))
                draw.text((x-17, top+size+3), str(v), fill='black', font=fonts[18])
                draw.text((left-42, y-10), str(v), fill='black', font=fonts[18])
            draw.text((left, top+size+27), f'peak ({peak[0]:.0f}, {peak[1]:.0f}) mm', fill='black', font=fonts[20])
    draw.text((60, 2395), 'Horizontal axis: x (mm). Vertical axis: y (mm). Dark = 0; pale yellow = 1 relative to panel maximum.', fill='black', font=fonts[23])
    image.save(path)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=ROOT/'.local/gegi-10m/analysis-final-v2')
    parser.add_argument('--output', type=Path, default=ROOT/'.local/gegi-10m/diagnosis-rejected-v1/boundary')
    args = parser.parse_args()
    diagnose(args.input.resolve(), args.output.resolve())
