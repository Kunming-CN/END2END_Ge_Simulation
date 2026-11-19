"""Publish the saved GeGI plane-prior comparison in the measured-plane exhibit."""

import gzip
from hashlib import sha256
import json
from math import isclose
from pathlib import Path

import gegi_cobalt_history_display as cobalt


FOLDER = Path('results/gegi-digital')
SUMMARY = FOLDER/'plane-priors.json'
IMAGE = FOLDER/'plane-priors.png'
COMMERCIAL_KEY = 'commercial_acquisition'
PRIORS = {'uniform-area': 'Uniform area', 'uniform-solid-angle': 'Uniform solid angle'}
STUDY_SHA256 = 'cd0918844b62d57709d1825fd514ffbee999ee0211120c28b27c10ef7d2fe088'
SCORE_SHA256 = '99dff8620e45d260009519fec2f0ae2a5f8b28283d03582268cdd71fc49fe081'
INTERSECTION_SHA256 = dict(image='44881ece1875d7efcc6598f2aa02896ec9f4e93aa3325e275d314fe0b4615e11',
                           influence='48e5f25bc9bfb50accb4ce67200b6017c28ae380b2b1e0dfd2605228b4dec43d')
FOOTPRINTS = ('original', 'wide')
COUNTS = ('triggers', 'triggers_with_geometry', 'allowed_hypotheses', 'hypotheses', 'projected_mass', 'unresolved_mass')


def plot(views, windows, grid, path):
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib.patches import Rectangle
    import numpy as np

    figure = Figure(figsize=(9.2, 6.4), layout='constrained')
    FigureCanvasAgg(figure)
    axes = figure.subplots(2, len(windows), sharex=True, sharey=True)
    extent, inner = grid['wide']['extent_mm'], grid['original']['extent_mm']
    for row, (prior, name) in enumerate(PRIORS.items()):
        for col, label in enumerate(windows):
            axis = axes[row, col]
            density = np.asarray(views['full']['layers'][label]['priors'][prior]['wide_mass'])
            image = axis.imshow(density/density.max(), origin='lower', cmap='viridis', vmin=0, vmax=1,
                                extent=(-extent, extent, -extent, extent), interpolation='nearest')
            axis.add_patch(Rectangle((-inner, -inner), 2*inner, 2*inner, fill=False,
                                     edgecolor='white', linewidth=.7, linestyle='--', alpha=.8))
            for half, marker, color in [('first_half', 'o', 'white'), ('second_half', '+', '#f87c65')]:
                peak = views[half]['layers'][label]['priors'][prior]['peaks']['wide'][0]
                x, y = peak['position_mm'][:2]
                axis.plot(x, y, marker, markersize=7, markerfacecolor='none', color=color,
                          markeredgewidth=1.5, clip_on=False)
            if row == 0:
                axis.set_title(f"{float(label.removesuffix('_keV')):,.0f} keV")
            if col == 0:
                axis.set_ylabel(f'{name}\nDetector Y (mm)')
            if row == 1:
                axis.set_xlabel('Detector X (mm)')
            axis.set_xticks([-200, 0, 200])
            axis.set_yticks([-200, 0, 200])
    figure.colorbar(image, ax=axes, shrink=.74, label="Fraction of panel maximum")
    figure.savefig(path, dpi=150, facecolor='white')


def attach(site, sources):
    from gegi_digital_display import MEASURED_PLANE_FILE

    raw, score_raw = (path.read_bytes() for path in sources)
    if sha256(raw).hexdigest() != STUDY_SHA256 or sha256(score_raw).hexdigest() != SCORE_SHA256:
        raise ValueError('Unexpected four-block plane-prior comparison or held-out scores')
    study = json.loads(gzip.decompress(raw))
    score = json.loads(score_raw)
    if score['prior_study_sha256'] != STUDY_SHA256:
        raise ValueError('Held-out scores belong to a different comparison')
    previous = json.loads((site/MEASURED_PLANE_FILE).read_bytes())
    if study['original_pooled_sha256'] != previous['source_sha256']['study']:
        raise ValueError('Plane-prior study belongs to a different four-block exposure')
    views, windows = study['views'], previous['windows']
    compact = {}
    for view_name, view in views.items():
        reference = previous['views'][view_name]
        if any(view['selection'][k] != v for k, v in reference['selection'].items()):
            raise ValueError('Plane-prior exposure counts disagree with the displayed acquisition')
        layers = {}
        for label, layer in view['layers'].items():
            counts = {k: v for k, v in reference['layers'][label].items() if k != 'peaks'}
            if any(layer[k] != v for k, v in counts.items()):
                raise ValueError('Plane-prior order or trigger counts disagree with the displayed acquisition')
            priors = {p: {k: v for k, v in result.items() if k not in ('original_mass', 'wide_mass')}
                      for p, result in layer['priors'].items()}
            layers[label] = dict(counts, priors=priors, shift_between_priors_mm=layer['shift_between_priors_mm'])
        compact[view_name] = dict(exposures=view['exposures'], selection=view['selection'], layers=layers)
    summary = dict(study_sha256=STUDY_SHA256, pooled_sha256=study['original_pooled_sha256'],
                   source_sha256=study['source_sha256'], image_sha256=None,
                   prior_definitions=study['prior_definitions'], checks=study['checks'],
                   heldout={k: score[k] for k in ('score_definition', 'interpretation', 'comparisons', 'pooled', 'checks',
                                                  'source_sha256')} | dict(study_sha256=SCORE_SHA256),
                   grids={k: {f: g[f] for f in ('assumed_z_mm', 'extent_mm', 'step_mm')}
                          for k, g in study['grids'].items()}, windows=windows, views=compact,
                   split_peak_separation_mm=study['split_peak_separation_mm'])
    output = site/SUMMARY
    if output.is_file():
        published = json.loads(output.read_bytes())
        diagnostic = published.get('three_intersection_diagnostic')
        if diagnostic is not None:
            from gegi_weak_strip_display import SUMMARY as WEAK_SUMMARY

            weak = json.loads((site/WEAK_SUMMARY).read_bytes())
            if (any(published[k] != v for k, v in summary.items() if k != 'image_sha256')
                    or sha256((site/IMAGE).read_bytes()).hexdigest() != published['image_sha256']
                    or diagnostic['report_sha256'] != INTERSECTION_SHA256
                    or diagnostic['input_sha256'] != diagnostic_input_digests(summary, weak)
                    or weak['plane_study_sha256'] != summary['pooled_sha256']):
                raise ValueError('Saved intersection diagnostic differs from the reattached plane-prior comparison')
            if 'cobalt_histories' in diagnostic:
                cobalt.validate_binding(diagnostic['cobalt_histories'], diagnostic, summary['windows'])
            return
        if COMMERCIAL_KEY in published:
            summary[COMMERCIAL_KEY] = published[COMMERCIAL_KEY]
    plot(views, windows, study['grids'], site/IMAGE)
    summary['image_sha256'] = sha256((site/IMAGE).read_bytes()).hexdigest()
    output.write_text(json.dumps(summary, allow_nan=False, separators=(',', ':'))+'\n', encoding='utf-8', newline='\n')


def compact_intersection_views(study, baseline):
    result = {}
    if study['views'].keys() != baseline['views'].keys():
        raise ValueError('Intersection diagnostic uses different acquisition halves')
    for view, distribution in study['views'].items():
        original = baseline['views'][view]['layers']
        if distribution['layers'].keys() != original.keys():
            raise ValueError('Intersection diagnostic uses different measured energy windows')
        result[view] = {}
        for label, layer in distribution['layers'].items():
            reference = original[label]
            counts = layer['counts']
            if any(counts['full'][k] != reference[k] or not isclose(
                    counts['subgroup'][k] + counts['remainder'][k], reference[k], rel_tol=0., abs_tol=1.e-12)
                   for k in COUNTS):
                raise ValueError(f'Intersection diagnostic changes the saved census in {view}/{label}')
            parameters = {}
            for prior in PRIORS:
                parameters[prior] = {}
                for footprint in FOOTPRINTS:
                    estimate = layer['priors'][prior][footprint]
                    old = reference['priors'][prior]['peaks'][footprint][0]
                    full = estimate['peaks']['full']
                    if full['position_mm'] != old['position_mm'] or not isclose(
                            full['value'], old['value'], rel_tol=0., abs_tol=1.e-12):
                        raise ValueError(f'Intersection diagnostic changes the saved full-map maximum in {view}/{label}')
                    parameters[prior][footprint] = {key: estimate[key] for key in (
                        'peaks', 'mass_at_peaks', 'shift_full_to_remainder_mm')}
                    if 'programmed_source' in estimate:
                        parameters[prior][footprint]['programmed_source'] = estimate['programmed_source']
            result[view][label] = dict(counts=counts, priors=parameters)
    return result


def compact_influence(study, views, windows):
    lines = study['lines']
    if tuple(lines) != tuple(windows):
        raise ValueError('Leave-two-out results use different measured energy windows')
    for label, line in lines.items():
        layer = views['full'][label]
        if any(line[k] != layer['counts']['full'][k] for k in COUNTS):
            raise ValueError(f'Leave-two-out census disagrees in {label}')
        for prior, comparison in line['priors'].items():
            result = layer['priors'][prior]['original']
            selected = comparison['selected_pair']
            if (selected['peak_after']['position_mm'] != result['peaks']['remainder']['position_mm']
                    or not isclose(selected['baseline_peak_removed_fraction'],
                                   result['mass_at_peaks']['full']['subgroup_share_of_full'], rel_tol=0., abs_tol=1.e-12)
                    or not isclose(selected['displacement_mm'], result['shift_full_to_remainder_mm'],
                                   rel_tol=0., abs_tol=1.e-12)):
                raise ValueError(f'The diagnostics disagree at the original-field maximum in {label}/{prior}')
            for scope in ('all_pairs', 'same_block_and_history_relation'):
                del comparison[scope]['displacement_histogram_mm2']
    return lines


def diagnostic_input_digests(baseline, weak):
    return {
        'independent-1s-exposure.json.gz': baseline['pooled_sha256'],
        'independent-1s-plane-priors.json.gz': baseline['study_sha256'],
        'independent-1s-weak-endpoints.json.gz': weak['reports_sha256']['native_endpoints'],
    }


def attach_intersections(site, image_path, influence_path, ancestry_path=None, cone_path=None):
    from gegi_weak_strip_display import SUMMARY as WEAK_SUMMARY

    raw_image, raw_influence = (path.read_bytes() for path in (image_path, influence_path))
    report_hashes = dict(image=sha256(raw_image).hexdigest(), influence=sha256(raw_influence).hexdigest())
    if report_hashes != INTERSECTION_SHA256:
        raise ValueError('Unexpected checksums for the saved GeGI intersection diagnostics')
    image = json.loads(gzip.decompress(raw_image))
    influence = json.loads(gzip.decompress(raw_influence))
    baseline = json.loads((site/SUMMARY).read_bytes())
    weak = json.loads((site/WEAK_SUMMARY).read_bytes())
    image_inputs = {Path(name).name: digest for name, digest in image['input_sha256'].items()}
    inputs = diagnostic_input_digests(baseline, weak)
    saved_blocks = [(block['name'], block['report_sha256'], block['plane_sha256']) for block in weak['blocks']]
    if (weak['plane_study_sha256'] != baseline['pooled_sha256'] or
            [(block['name'], block['report_sha256'], block['plane_sha256']) for block in image['inputs']] != saved_blocks or
            any(sources.get(name) != digest for sources in (image_inputs, influence['input_sha256'])
                for name, digest in inputs.items())):
        raise ValueError('Intersection diagnostics belong to different saved cones or endpoint labels')
    if any(any(image['grids'][key][field] != value for field, value in grid.items())
           for key, grid in baseline['grids'].items()):
        raise ValueError('Intersection diagnostic uses different source-plane cells')
    identity = ('block', 'trigger_index', 'two_strip_ordinal', 'trigger_time_ns', 'energy_window')
    expected = {tuple(row[k] for k in identity) for row in weak['events']
                if row['reference']['status'] == 'measured' and row['pairing_class'] != 'energy_incompatible'
                and len(row['reference']['endpoint_intersections']) == 3}
    selected = [row for row in image['events'] if row['subgroup']]
    if len(selected) != len(expected) or {tuple(row[k] for k in identity) for row in selected} != expected:
        raise ValueError('Intersection diagnostic changes the selected recorded trigger identities')
    views = compact_intersection_views(image, baseline)
    diagnostic = dict(
        report_sha256=report_hashes, input_sha256=inputs, blocks=image['inputs'],
        source_sha256={key: report['source_sha256'] for key, report in [('image', image), ('influence', influence)]},
        subgroup_definition=image['subgroup_definition'], interpretation=image['interpretation'],
        checks=image['checks'], split_peak_separation_mm=image['split_peak_separation_mm'],
        selected_triggers=[{key: row[key] for key in (*identity, 'native_group')} for row in selected],
        views=views, leave_two_out=compact_influence(influence, views, baseline['windows']))
    previous = baseline.get('three_intersection_diagnostic', {}).get('cobalt_histories')
    if ancestry_path is not None and cone_path is not None:
        diagnostic['cobalt_histories'] = cobalt.compact(ancestry_path, cone_path, diagnostic, baseline['windows'])
    elif ancestry_path is not None or cone_path is not None:
        raise ValueError('The archived Co-60 history comparison needs both saved reports')
    elif previous is not None:
        cobalt.validate_binding(previous, diagnostic, baseline['windows'])
        diagnostic['cobalt_histories'] = previous
    baseline['three_intersection_diagnostic'] = diagnostic
    (site/SUMMARY).write_text(json.dumps(baseline, allow_nan=False, separators=(',', ':'))+'\n',
                              encoding='utf-8', newline='\n')


def intersection_section(data):
    from gegi_shared_clock_display import table

    diagnostic = data['three_intersection_diagnostic']
    full = diagnostic['views']['full']
    counts = full['all']['counts']
    energy_windows = data['windows']
    row_data = []
    for label in energy_windows:
        for prior, name in PRIORS.items():
            for footprint in FOOTPRINTS:
                width = data['grids'][footprint]['extent_mm']
                result = full[label]['priors'][prior][footprint]
                peaks = result['peaks']
                locations = ['({:g}, {:g})'.format(*peaks[k]['position_mm'][:2]).replace('-', '−')
                             for k in ('full', 'remainder')]
                split = diagnostic['split_peak_separation_mm'][label][prior][footprint]
                share = result['mass_at_peaks']['full']['subgroup_share_of_full']
                share_text = '&lt;0.01%' if 0 < share < .0001 else f'{share:.2%}'
                row_data.append((f"{float(label.removesuffix('_keV')):,.0f} keV", name, f'±{width:g} mm',
                                 ' → '.join(locations), f"{result['shift_full_to_remainder_mm']:.1f}", share_text,
                                 f"{split['full']:.1f} → {split['remainder']:.1f}"))
    comparison = table(row_data, ('Energy window', 'Prior', 'Field', 'Peak X, Y', 'Peak move (mm)',
                                  'Share at original peak', 'Half-to-half distance (mm)'),
                       'Full image → with three-intersection triggers set aside. Peak coordinates in mm.')
    _, low_co, high_co = energy_windows
    low, high = [diagnostic['leave_two_out'][label]['priors']['uniform-area'] for label in (low_co, high_co)]
    low_pair, high_pair = [line['selected_pair'] for line in (low, high)]
    high_wide = full[high_co]['priors']['uniform-area']['wide']['shift_full_to_remainder_mm']
    sizes = [full[label]['counts']['full']['triggers_with_geometry'] for label in energy_windows]
    low_rank, high_rank = [f"{line['all_pairs']['displacement_counts']['equal']}/{line['all_pairs']['pair_count']}"
                           for line in (low, high)]
    if 'cobalt_histories' in diagnostic:
        histories = cobalt.section(diagnostic, energy_windows)
    else:
        histories = '''<p>Each cobalt pair consists of two occurrences of a single archived history in one acquisition block.
Each is the sole pair under that same-block, same-history comparison. Both 662 keV occurrences come from
distinct histories. Pair comparisons can share triggers and archived histories.</p>'''
    return f'''<h4 id="gegi-three-intersections">Which triggers move the line-window peaks?</h4>
<p>On the ±120 mm uniform-area image, two triggers contributed {low_pair['baseline_peak_removed_fraction']:.1%}
of the 1,173 keV maximum cell. Setting them aside moved the maximum {low_pair['displacement_mm']:.0f} mm to the opposite edge.
On the ±240 mm uniform-area image, that maximum stayed at (86, 70) mm. The 1,332 keV maximum moved
{high_pair['displacement_mm']:.1f} and {high_wide:.1f} mm on the two respective area footprints. All pooled 662 keV peaks
and all three pooled solid-angle peaks stayed in their original cells.</p>
<details><summary>Peak coordinates, half-exposure shifts and pair comparisons</summary>
<p>Three simulated charge-collection intersections label {counts['subgroup']['triggers']} trigger occurrences from
{counts['subgroup']['distinct_native_groups']} distinct archived histories. Two are in each line window, out of
{sizes[0]}, {sizes[1]} and {sizes[2]} projected triggers in energy order. The full image includes all
{counts['full']['triggers']} measured triggers, {counts['full']['hypotheses']} projected orders and
{counts['full']['unresolved_mass']:g} unresolved trigger units. The diagnostic sets aside only the labeled
contributions and keeps every other order at its original weight. <a href="#gegi-weak-strips">See the endpoint comparison</a>.</p>
{comparison}
<p>On the original uniform-area field, the cobalt pairs had the largest loss of weight at their original maximum
cells among all ways to set aside two projected triggers in each window. Their displacements tied for largest in
{low_rank} and {high_rank} pairs. The heights of the new maxima were {low_pair['maximum_reduction_fraction']:.1%}
and {high_pair['maximum_reduction_fraction']:.1%} lower than the full-image maxima. Contributions at the four cells
touching the programmed Co-60 source position were negligible on both footprints.</p>
{histories}</details>'''


def section(site):
    data = json.loads((site/SUMMARY).read_bytes())
    if sha256((site/IMAGE).read_bytes()).hexdigest() != data['image_sha256']:
        raise ValueError('Plane-prior figure differs from its public summary')
    layers = data['views']['full']['layers']
    rows = []
    for label in data['windows']:
        for prior, name in PRIORS.items():
            shifts = layers[label]['priors'][prior]['shift_from_original_mm']
            split = data['split_peak_separation_mm'][label][prior]
            rows.append(f'<tr><th scope="row">{float(label.removesuffix("_keV")):,.0f} keV</th>'
                        f'<td>{name}</td><td>{shifts["wide"]:.1f}</td><td>{shifts["wide_crop"]:.1f}</td>'
                        f'<td>{split["original"]:.1f}</td><td>{split["wide"]:.1f}</td></tr>')
    inside = [layers['all']['priors'][p]['wide_inside_mass'] for p in PRIORS]
    projected = layers['all']['projected_mass']
    scores = data['heldout']['pooled']['all']
    score_area, score_angle = [scores[p]['mean_log_ratio'] for p in PRIORS]
    angular_halves = [view['all']['uniform-solid-angle'] for view in data['heldout']['comparisons'].values()]
    crop_prior = angular_halves[0]['prior_central_crop_fraction']
    crops = [h['training_central_crop_fraction'] for h in angular_halves]
    intersection = intersection_section(data) if 'three_intersection_diagnostic' in data else ''
    return f'''<h4 id="gegi-plane-priors">How the source-plane prior changes the image</h4>
<p>Each 4 × 4 mm cell receives equal initial weight under uniform area. Under uniform solid angle,
a cell receives the angular area it subtends at the detector center (0, 0, 0) mm. A central cell at z = 40 mm
subtends a larger angle than a distant cell of the same size. Each measured cone is normalized separately
over the chosen square. The waveform fits, competing interaction orders and their weights are shared by both models.</p>
<figure style="margin:1rem 0"><a href="gegi-digital/{IMAGE.name}"><img loading="lazy"
style="width:100%;height:auto" width="1380" height="960" src="gegi-digital/{IMAGE.name}"
alt="Six pooled energy-window maps. Symbols mark the two independent half-exposure maxima on the wider field."></a>
<figcaption>The dashed square encloses the original ±120 mm field within the ±240 mm reconstruction.
The circle marks the first half-second maximum and the plus marks the second. The color scale shows the fraction
of each panel’s own maximum so the spatial shapes are visible in all three energy windows.</figcaption></figure>
<div role="region" aria-label="Peak displacements in millimeters" tabindex="0" style="overflow-x:auto">
<table><caption>Peak displacements in mm. The crop keeps only the original cells of the wider reconstruction.</caption>
<thead><tr><th scope="col">Energy window</th><th scope="col">Prior</th><th scope="col">1 s peak shift on widening</th>
<th scope="col">1 s peak shift on widening, then cropping</th><th scope="col">Half-to-half, ±120 mm</th>
<th scope="col">Half-to-half, ±240 mm</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<p>Of {projected:g} projected trigger units in the wider field, the central square retains {inside[0]:.2f} with uniform area
and {inside[1]:.2f} with uniform solid angle. The angular prior concentrates weight toward the detector axis.
The 662 keV example shows the distinction between repeatability and accuracy. The wider-field peak moves from
(−42, 2) mm to (−10, 14) mm when switching to uniform solid angle. The programmed Cs-137 position was
(−40, 0) mm, withheld from fitting. Half-to-half agreement improves even as this pooled peak moves farther from the source.</p>
{intersection}
<h4>How well does one half predict the other?</h4>
<p>Each half-second map was used to predict the other half’s measured cone angles on the ±240 mm field.
The comparison uses the same response model under the learned map and its own prior alone.
A positive mean log ratio indicates that the learned map gives the held-out cones greater average log response.
Across {scores['uniform-area']['selected_triggers']} selected triggers, the mean log ratio per trigger was
{score_area:+.3f} for uniform area and {score_angle:+.3f} for uniform solid angle, each relative to its own baseline.
The {layers['all']['unresolved_mass']:g} fully unresolved triggers contributed zero to the difference.</p>
<p>The solid-angle prior alone puts {crop_prior:.1%} of its weight in the central square. The two half-second maps
place {crops[0]:.1%} and {crops[1]:.1%} there. Both spread weight outward while improving agreement with the other half.
This checks consistency with independent simulated signals under the assumed angular response.
<a href="gegi-digital/{SUMMARY.name}">Peak coordinates, counts, comparisons and study hashes (JSON)</a>.</p>'''
