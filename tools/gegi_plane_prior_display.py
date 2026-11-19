"""Publish the saved GeGI plane-prior comparison in the measured-plane exhibit."""

import gzip
from hashlib import sha256
import json
from pathlib import Path


FOLDER = Path('results/gegi-digital')
SUMMARY = FOLDER/'plane-priors.json'
IMAGE = FOLDER/'plane-priors.png'
PRIORS = {'uniform-area': 'Uniform area', 'uniform-solid-angle': 'Uniform solid angle'}
STUDY_SHA256 = 'cd0918844b62d57709d1825fd514ffbee999ee0211120c28b27c10ef7d2fe088'
SCORE_SHA256 = '99dff8620e45d260009519fec2f0ae2a5f8b28283d03582268cdd71fc49fe081'


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
    plot(views, windows, study['grids'], site/IMAGE)
    summary = dict(study_sha256=STUDY_SHA256, pooled_sha256=study['original_pooled_sha256'],
                   source_sha256=study['source_sha256'], image_sha256=sha256((site/IMAGE).read_bytes()).hexdigest(),
                   prior_definitions=study['prior_definitions'], checks=study['checks'],
                   heldout={k: score[k] for k in ('score_definition', 'interpretation', 'comparisons', 'pooled', 'checks',
                                                  'source_sha256')} | dict(study_sha256=SCORE_SHA256),
                   grids={k: {f: g[f] for f in ('assumed_z_mm', 'extent_mm', 'step_mm')}
                          for k, g in study['grids'].items()}, windows=windows, views=compact,
                   split_peak_separation_mm=study['split_peak_separation_mm'])
    (site/SUMMARY).write_text(json.dumps(summary, allow_nan=False, separators=(',', ':'))+'\n', encoding='utf-8', newline='\n')


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
<a href="gegi-digital/{SUMMARY.name}">Peak coordinates, counts, scores by energy and study hashes (JSON)</a>.</p>'''
