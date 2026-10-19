"""Export finished GeGI saved-data corrections; never run physics or analysis.

Only completion seals, aggregate reports and already-public teaching traces are
read. The old 708-group reconstruction remains an explicitly separate control.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import html
import json
import math
from pathlib import Path
import re
import shutil
from PIL import Image, ImageDraw, ImageFont, __version__ as PILLOW_VERSION
from site_routes import page_navigation

ROOT = Path(__file__).resolve().parents[1]
KIND = 'gegi_saved_publication_v3'
ROUTE = 'results/gegi-campaign/index.html'
PREVIOUS_MANIFEST = '67aee794d57c7d0f34ea8715af684421a1a5a0ef11b05a975907230501dd1c12'
MAX_BUNDLE_BYTES = 8_000_000
SOURCE_FILES = ('tools/gegi_saved_publication.py', 'tools/gegi_signal_journey.js')
PRIVATE = re.compile(r'[A-Za-z]:[\\/]+Users[\\/]|/mnt/[a-z]/|/home/[^/\s]+/|file:///|\.local[\\/]', re.I)
TEXT_NAMES = {'index.html', 'summary.json', 'configuration.json', 'representatives.json',
              'source-assessment.json', 'gegi_signal_journey.js', 'imaging-summary.json'}
OPTIONAL_TEXT_NAMES = {'evaluation-summary.json'}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def ordinary(path):
    path = Path(path)
    for parent in (path, *path.parents):
        require(not parent.is_symlink() and not (hasattr(parent, 'is_junction') and parent.is_junction()),
                'Linked publication input or destination')
    require(path.is_file(), 'Missing saved artifact: '+path.name)
    return path


def sha(path):
    with ordinary(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path):
    return json.loads(ordinary(path).read_bytes())


def encoded(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def public(body):
    text = body.decode('utf-8')
    require(not PRIVATE.search(text), 'Private path in public artifact')
    require(not re.search(r'BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY|gh[pousr]_[A-Za-z0-9]{25,}', text),
            'Credential-like public artifact')
    return body


def _report_path(path):
    path = Path(path)
    return path/'report.json' if path.is_dir() else path


def _source_pins(root):
    return {name: sha(Path(root)/name) for name in SOURCE_FILES}


def _previous(previous_public, expected=None):
    previous_public = Path(previous_public)
    manifest = read(previous_public/'publication.json')
    require(sha(previous_public/'publication.json') == (PREVIOUS_MANIFEST if expected is None else expected), 'Previous public manifest changed')
    require(manifest.get('status') == 'complete' and manifest.get('route') == ROUTE,
            'Previous public bundle is incomplete')
    needed = ('index.html', 'representatives.json', 'source-assessment.json', 'spectra.png', 'configuration.json')
    for name in needed:
        record = manifest['artifacts'][name]; path = ordinary(previous_public/name)
        require(sha(path) == record['sha256'] and path.stat().st_size == record['bytes'],
                'Previous teaching artifact changed: '+name)
        if path.suffix in ('.html', '.json'):
            public(path.read_bytes())
    return manifest


def _saved_inputs(reconstruction, imaging, legacy_control, previous_public):
    reconstruction = Path(reconstruction)
    complete = read(reconstruction/'COMPLETE.json'); summary = read(reconstruction/'summary.json')
    require(complete.get('kind') == summary.get('kind') == 'gegi_saved_reconstruction_v3'
            and complete.get('status') == summary.get('status') == 'completed_conditional_reconstruction',
            'Only completed saved reconstruction may be exported')
    require(complete['summary_sha256'] == sha(reconstruction/'summary.json')
            and complete['identity_sha256'] == sha(reconstruction/'identity.json'),
            'Saved reconstruction completion binding changed')
    require(all(summary.get(k) == 0 for k in
                ('new_radiation_calls', 'new_native_calls', 'new_field_calls', 'new_calibration_calls')),
            'Publication requires saved-data-only reconstruction')
    counts = summary['counts']
    require(counts['pulse_groups'] == 57613 and sum(summary['reasons'].values()) == 57613,
            'Incomplete or inconsistent 57,613-group reason partition')
    require(counts['validated_recovered_groups'] == 0, 'Conditional reconstruction must not claim validated recovery')
    denominator = summary['original_initial_denominators']
    require(len(denominator) == 4 and sum(v['initial_primaries'] for v in denominator.values()) == 1_000_000,
            'Original initial-record denominator changed')
    previous = _previous(previous_public)
    require(summary['campaign_complete_sha256'] == previous['input_sha256']['campaign_complete_sha256'],
            'Reconstruction belongs to a different campaign')
    image_path, control_path = _report_path(imaging), _report_path(legacy_control)
    image, control = read(image_path), read(control_path)
    require(image.get('kind') == control.get('kind') == 'gegi_joint_conditional_imaging_v3',
            'Unexpected completed imaging report')
    accounting = image['saved_signal_accounting']; bindings = accounting['input_sha256']
    require(bindings['COMPLETE.json'] == sha(reconstruction/'COMPLETE.json')
            and bindings['summary.json'] == complete['summary_sha256']
            and bindings['identity.json'] == complete['identity_sha256'],
            'Imaging report does not bind the completed reconstruction')
    # The imaging reader already verified every derived data byte. Check its
    # complete binding inventory and small receipts, without rereading science.
    seen = set(); receipt_counts = Counter(); receipt_reasons = Counter()
    for chunk in complete['chunks']:
        index = chunk['chunk_index']; require(index not in seen, 'Duplicate reconstruction chunk'); seen.add(index)
        rname, dname = f'chunks/{index:03d}.json', f'chunks/{index:03d}.jsonl.gz'
        require(bindings[rname] == chunk['receipt_sha256'] == sha(reconstruction/rname)
                and bindings[dname] == chunk['data_sha256'], 'Imaging input chunk binding changed')
        receipt = read(reconstruction/rname)
        require(receipt['sha256'] == chunk['data_sha256'] and receipt['source_sha256'] == summary['source_sha256'],
                'Derived chunk recipe differs from completed summary')
        receipt_counts.update(receipt['counts']); receipt_reasons.update(receipt['reasons'])
    require(len(seen) == 100 and dict(receipt_counts) == counts and dict(receipt_reasons) == summary['reasons'],
            'Derived chunk accounting does not match completed summary')
    require(accounting['counts']['nonzero_pulse_groups'] == counts['pulse_groups']
            and accounting['counts']['groups_with_conditional_candidates'] == counts['conditional_candidate_groups']
            and image['group_count'] == accounting['counts'].get('selected_conditional_groups', 0),
            'Joint imaging selection census changed')
    require(control.get('group_count') == 708 and
            control['provenance']['input_sha256'] == previous['input_sha256']['cones.jsonl_sha256'],
            'Legacy control must use the exact original 708-group cone input')
    for report in (image, control):
        require(report['provenance'].get('truth_used_for_reconstruction') is False,
                'Truth must not select imaging hypotheses')
        require(report['provenance'].get('source_group_labels_used', False) is False,
                'Acquisition labels must not select pooled imaging hypotheses')
        require(report.get('source_distance_mm') is None and report.get('activity_bq') is None,
                'Uncalibrated model must retain unknown range and activity')
    inputs = {'reconstruction_complete_sha256': sha(reconstruction/'COMPLETE.json'),
        'reconstruction_summary_sha256': complete['summary_sha256'], 'reconstruction_identity_sha256': complete['identity_sha256'],
        'joint_imaging_report_sha256': sha(image_path), 'legacy_control_report_sha256': sha(control_path),
        'legacy_control_input_sha256': control['provenance']['input_sha256'],
        'previous_public_manifest_sha256': sha(Path(previous_public)/'publication.json')}
    return summary, image, control, previous, inputs


def _font(size):
    for name in ('DejaVuSans.ttf', 'arial.ttf'):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


def map_figure(report, path, title, *, values=None, units='conditional source mass / grid cell'):
    """Draw saved numeric values only. Linear colour scale, no truth overlays."""
    grid = report['grid']; xs, ys = grid['x_mm'], grid['y_mm']
    data = report['source_mass'] if values is None else values
    require(len(xs) >= 2 and len(ys) >= 2 and len(data) == len(ys)
            and all(len(row) == len(xs) for row in data), 'Map/grid dimensions differ')
    require(all(math.isfinite(float(v)) and v >= 0 for row in data for v in row), 'Invalid saved map values')
    maximum = max(max(row) for row in data)
    require(maximum > 0, 'An empty map must not be drawn as a source peak')
    anchors = ((9,18,40), (20,63,107), (9,154,184), (132,216,139), (255,229,88))
    def colour(f):
        f = max(0., min(1., f)); p = f*(len(anchors)-1); i = min(int(p), len(anchors)-2); w = p-i
        return tuple(round(a*(1-w)+b*w) for a,b in zip(anchors[i],anchors[i+1]))
    field = Image.new('RGB', (len(xs), len(ys)))
    field.putdata([colour(float(v)/maximum) for row in reversed(data) for v in row])
    canvas = Image.new('RGB', (960, 720), (9,18,33)); draw = ImageDraw.Draw(canvas)
    left, top, width, height = 95, 100, 620, 530
    canvas.paste(field.resize((width,height), Image.Resampling.NEAREST), (left,top))
    white, muted = '#f1f7ff', '#b2c8da'; normal, small = _font(18), _font(15)
    draw.text((36,20), title, fill=white, font=_font(23))
    draw.text((36,55), f"{report['group_count']:,} observed groups; imposed z = {grid['assumed_z_mm']:g} mm", fill=muted,font=normal)
    step = grid['step_mm']; x0,x1 = xs[0]-step/2,xs[-1]+step/2; y0,y1 = ys[0]-step/2,ys[-1]+step/2
    draw.rectangle((left,top,left+width,top+height), outline=muted)
    for fraction in (0,.25,.5,.75,1):
        x=left+fraction*width; y=top+(1-fraction)*height
        draw.line((x,top+height,x,top+height+6),fill=muted)
        draw.text((x,top+height+10),f'{x0+(x1-x0)*fraction:g}',fill=white,font=small,anchor='mt')
        draw.line((left-6,y,left,y),fill=muted)
        draw.text((left-12,y),f'{y0+(y1-y0)*fraction:g}',fill=white,font=small,anchor='rm')
    draw.text((left+width/2,top+height+40),'x (mm)',fill=white,font=normal,anchor='mt')
    draw.text((24,top+height/2),'y (mm)',fill=white,font=normal)
    barx,bary,bh=760,top,400
    for i in range(bh):
        draw.line((barx,bary+i,barx+28,bary+i),fill=colour(1-i/(bh-1)))
    for fraction in (0,.25,.5,.75,1):
        y=bary+(1-fraction)*bh
        draw.text((barx+38,y),f'{maximum*fraction:.3g}',fill=white,font=small,anchor='lm')
    draw.text((746,535),'Linear scale',fill=white,font=small)
    for i,line in enumerate(units.split(' / ')):
        draw.text((746,560+i*22),line if i==0 else '/ '+line,fill=muted,font=small)
    draw.text((36,687),'Conditional model output; no source-truth overlay or inferred distance.',fill=muted,font=small)
    canvas.save(path, format='PNG', optimize=True)


def _compact_imaging(report):
    keys = ('kind','group_count','pooling','background_fraction','blind_peaks','backprojection_blind_peaks',
            'source_distance_mm','distance_status','localization_status','peak_count_is_inferred_source_count',
            'activity_bq','sensitivity_calibrated','uncertainty','range_profile','references',
            'field_of_view_overlap_max_absolute_response_difference','provenance')
    out = {k:report[k] for k in keys if k in report}
    out['spectral_layers'] = {k:{name:v[name] for name in ('group_count','background_fraction','blind_peaks') if name in v}
                              for k,v in report.get('spectral_layers',{}).items()}
    return out


def _readout_summary(path):
    report = read(path); checks = [c for r in report['results'] for c in r['checks']]
    require(all(report[k] == 0 for k in ('new_transport_calls','new_native_calls','new_calibration_calls')),
            'Readout evidence must be a saved-only check')
    require(all(c['adc_code_equal'] and c['energy_gain_equal'] for c in checks), 'Readout identity check failed')
    return {'kind':report['kind'], 'scope':report['scope'], 'groups':len(report['results']),
        'channels_checked':len(checks), 'adc_codes_equal':True, 'fixed_gain_equal':True,
        'maximum_peak_absolute_error_V':max(c['peak_absolute_error_V'] for c in checks),
        'evidence_sha256':sha(path)}


def _evaluation_summary(path, imaging, reconstruction, image):
    report=read(path); bindings=report['bindings']; image_path=_report_path(imaging)
    require(report.get('kind')=='gegi_joint_signal_posthoc_truth_evaluation_v1'
            and report.get('selection_unchanged') is True and report.get('truth_used_in_imaging') is False,
            'Evaluation must be posthoc with the selected imaging sample unchanged')
    require(bindings['imaging_report_sha256']==sha(image_path)
            and bindings['saved_signal_complete_sha256']==sha(Path(reconstruction)/'COMPLETE.json')
            and bindings['imaging_event_diagnostics_sha256']==sha(image_path.parent/'event_diagnostics.jsonl')
            and bindings['imaging_source_sha256']==image['provenance']['source_sha256'],
            'Posthoc evaluation input binding changed')
    require(report['group_count']==image['group_count']==len(report['selected_ids'])
            and report['candidate_count']==image['saved_signal_accounting']['counts']['selected_candidates'],
            'Evaluation selected-group or candidate census changed')
    require(report.get('distance_mm') is None and report.get('activity_bq') is None
            and report.get('range_identified') is False, 'Unsupported range or activity in evaluation')
    # Retain aggregate numerical evidence; per-event truth rows remain local.
    return {k:report[k] for k in ('kind','scope','bindings','selected_id_census_sha256','selection_unchanged',
        'truth_used_in_imaging','group_count','candidate_count','weighting','residual_definition','groups','pooled',
        'energy_layers','distance_mm','activity_bq','range_identified','interpretation')}


def _journey(previous_public):
    old = ordinary(Path(previous_public)/'index.html').read_text(encoding='utf-8')
    match = re.search(r'<script type="application/json" id="gegi-journey-data">(.*?)</script>',old,re.S)
    require(match is not None, 'Previous exact 34-channel teaching payload is missing')
    payload = json.loads(match.group(1))
    require(len(payload.get('groups',{})) == 4, 'Teaching acquisition inventory changed')
    for group in payload['groups'].values():
        rep = group['representative']
        require(len(rep['channels']) == 34, 'Teaching payload must preserve all 34 channels')
        # The selected old event and its traces are unchanged. No source truth is
        # carried into the refreshed interactive wrapper or displayed by default.
        group.pop('truth_position_mm_for_evaluation_only',None)
    return payload


def _render(summary, imaging, control, figures, journey):
    esc = lambda value: html.escape(str(value),quote=True)
    n = summary['counts']; selected = imaging['group_count']
    htmlparts = ['<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
        '<title>GeGI · saved signal reconstruction · GeSignal</title><style>body{font:16px/1.55 system-ui;color:#172e43;background:#f6f9fc;max-width:1120px;margin:auto;padding:20px}h1{font-size:2.3rem;line-height:1.15}h2{margin-top:2rem}a{color:#075e9b}img{display:block;width:100%;height:auto;border-radius:10px}section{margin:28px 0}.note{background:#e7f2f6;border-left:4px solid #087f91;padding:16px}.limits{background:#fff3dc;border-left:4px solid #c48b20;padding:16px}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}.card{padding:16px;background:white;border:1px solid #d3e0e9;border-radius:10px}.card strong{display:block;font-size:1.7rem}details{background:white;padding:12px 18px;border:1px solid #d3e0e9;border-radius:8px;margin:16px 0}summary{cursor:pointer;font-weight:650}table{border-collapse:collapse;width:100%}th,td{text-align:left;border-bottom:1px solid #d3e0e9;padding:8px}pre{white-space:pre-wrap;overflow-wrap:anywhere}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,360px),1fr));gap:18px}.caption{color:#455f73;font-size:.94rem}.tag{text-transform:uppercase;font-size:.78rem;letter-spacing:.12em;color:#29667d}nav.local{display:flex;flex-wrap:wrap;gap:18px}code{overflow-wrap:anywhere}</style></head><body>',
        page_navigation(ROUTE),'<p class="tag">Saved data · new signal reconstruction</p><h1>What the GeGI signals support</h1>',
        '<p>All four independent acquisitions enter one anonymous pool, without equalizing their yields. These are two real nuclides (Cs-137 and Co-60) plus two 662-keV monoenergetic photon controls at two source positions—not four real nuclides or simultaneous source pileup.</p>',
        '<p class="caption">Nominal simulation setup only: source-to-crystal-center distance 56.57 mm and front clearance 26.4 mm. These supplied geometry values are not inferred range measurements.</p>',
        '<div class="cards">'+''.join('<div class="card"><strong>'+esc(f'{value:,}')+'</strong>'+label+'</div>' for value,label in (
            (1_000_000,'original initial records'),(n['pulse_groups'],'saved nonzero pulse groups'),
            (n['conditional_candidate_groups'],'groups with conditional signal hypotheses'),(0,'validated recovered groups')) )+'</div>',
        '<p class="limits">Processing is complete; source localization is not experimentally validated. Range and activity remain unknown. The saved calibration covers selected X/Y pairs, not the full 34-channel response to each injection; unexplained induction and charge sharing remain explicit.</p>',
        '<nav class="local"><a href="#new-map">New pooled result</a><a href="#control">Original 708 control</a><a href="#spectra">Spectra</a><a href="#journey">Signals to a cone</a><a href="#accounting">Accounting</a></nav>',
        '<section id="new-map"><h2>New pooled result</h2>']
    if selected:
        evaluation=summary['posthoc_evaluation']
        same_energy=evaluation['energy_layers'].get('661.657_keV',{})
        misses_right=any(item['truth_position_mm_for_evaluation_only'][0]>0 and not item['has_mode_within_predeclared_15mm']
                         for item in same_energy.get('truth_comparison_after_imaging',[]))
        outcome='Same-energy source separation still fails.' if misses_right else 'Localization remains conditional.'
        energy_limits=''
        for label,layer in evaluation['energy_layers'].items():
            if any(p.get('on_image_edge') for p in layer.get('blind_peaks',[])):
                energy_limits+=esc(label.replace('_',' '))+' retains an edge mode. '
            if layer['selected_groups']<20:
                energy_limits+=esc(label.replace('_',' '))+' has only '+str(layer['selected_groups'])+' groups. '
        htmlparts += [f'<p>{selected:,} groups supply conditional candidates inside the fixed readout-energy windows. Every surviving sequence and its unresolved weight is retained. A map maximum is a conditional hypothesis, not an inferred source count or a validated position.</p>',
                      '<div class="limits" id="accuracy-outcome"><strong>'+outcome+'</strong> '+('The pooled peaks look close to the supplied source positions, but the 661.657-keV layer still misses the right-hand source. ' if misses_right else '')+energy_limits+'Pooled modal offsets are not detector resolution or validated localization.</div>',
                      '<img src="map-new-pooled.png" alt="New anonymous pooled conditional source mass on an imposed plane">',
                      '<p class="caption">Finite vertices and uncertainty enter the event response. No candidate is normalized over the displayed square. The plane depth is imposed.</p>']
        if evaluation:
            residual=evaluation['pooled']['finite_vertex']; median=residual['candidate_conditional_absolute_residual_quantiles_deg']['0.5']
            fraction=residual['angular_compatibility']['within_15_deg']['fraction_of_all_selected_group_mass_lower']
            htmlparts += ['<p>The posthoc check leaves the sample and candidate weights unchanged: weighted median absolute cone residual <strong>'+f'{median:.3f}°'+'</strong> among supported candidates; known compatible mass within 15° is <strong>'+f'{100*fraction:.2f}%'+'</strong> of all selected-group weight. Unresolved weight is '+f"{residual['unresolved_mass']:.6g}/{evaluation['group_count']}"+'. These are compatibility diagnostics, not confidence coverage or detection efficiency.</p>',
                '<details><summary>Posthoc accuracy evidence · evaluated after reconstruction</summary><p>The 661.657-keV layer acquisition counts, used only after imaging, are '+esc(', '.join(k+': '+str(v) for k,v in same_energy.get('acquisition_counts_for_evaluation_only',{}).items()))+'. Its blind plane modes are '+esc(', '.join('('+', '.join(f'{v:g}' for v in p['position_mm'][:2])+')' for p in same_energy.get('blind_peaks',[])))+' mm; the plane depth is imposed.</p><p>The old 708-group control and new signal-selected sample have different populations. Their maps do not establish a controlled improvement in efficiency, accuracy or hardware performance.</p><p><a href="evaluation-summary.json">Exact aggregate posthoc evaluation, input hashes and limitations</a></p></details>']
    else:
        htmlparts += ['<p class="note" id="no-new-map"><strong>No supported new pooled map.</strong> No conditional group passed the saved signal and readout-energy selection. No source peak, blank heatmap, or replacement depth has been fabricated.</p>']
    layers = [item for item in figures if item['family']=='new' and item['layer']!='pooled']
    if layers:
        htmlparts += ['<details><summary>Readout-energy layers · same anonymous pool</summary><div class="grid">']
        for item in layers:
            htmlparts += ['<figure><img src="'+esc(item['file'])+'" alt="Conditional energy layer '+esc(item['layer'])+'"><figcaption>'+esc(item['layer'])+' · '+str(item['groups'])+' groups. Energy label, not isotope identification.</figcaption></figure>']
        htmlparts += ['</div></details>']
    htmlparts += ['</section><section id="control"><p class="tag">Separate control · original reconstruction</p><h2>Original 708 groups with corrected finite-vertex imaging</h2><details><summary>Inspect the separate original-reconstruction control</summary>',
        '<p>The same 708 previously accepted groups are pooled using all their original cone alternatives. This control changes the image response; it does not repair their old strip/depth reconstruction or count them as newly recovered events.</p>',
        '<img src="map-legacy-control.png" alt="Separate control: original 708 groups with finite-vertex conditional imaging">',
        '<p class="caption">All four acquisitions, no acquisition equalization, no truth overlay. Conditional source mass per grid cell; neither calibrated activity nor a probability of a true source location.</p>',
        '<details><summary>Why the boundary peaks changed</summary><p>The previous finite-square normalization forced each cone to contribute the same integral inside the displayed area. A cone whose main support lay outside could therefore promote its small tail into a bright boundary. The new event response is defined before choosing the field of view and includes unresolved hypotheses and an outlier component.</p><p>Maximum response difference at identical points after expanding the field: <strong>'+esc(control.get('field_of_view_overlap_max_absolute_response_difference','not recorded'))+'</strong>. This checks event-response invariance; fitted map masses can still change when model support changes.</p><img src="map-legacy-backprojection.png" alt="Original 708 control angular backprojection"><p>Saved angular backprojection before the conditional mixture fit. Both are model diagnostics; neither validates the original signal-derived vertices.</p></details></details></section>',
    ]
    control_layers = [item for item in figures if item['family']=='control' and item['layer']!='pooled']
    if control_layers:
        htmlparts += ['<details><summary>Original 708 control · energy layers</summary><div class="grid">']
        for item in control_layers:
            htmlparts += ['<figure><img src="'+esc(item['file'])+'" alt="Legacy control energy layer '+esc(item['layer'])+'"><figcaption>'+esc(item['layer'])+' · '+str(item['groups'])+' old groups; conditional control only.</figcaption></figure>']
        htmlparts += ['</div></details>']
    htmlparts += ['<section id="spectra"><h2>What the energies identify</h2><img src="spectra.png" alt="Unchanged fixed-calibration saved energy spectra"><p>The saved spectrum-only assessment supports a Co-60-compatible doublet. A single line near 661.7 keV remains ambiguous. These spectral statements do not assign an isotope to an incorrectly localized peak. Distance remains null.</p><p><a href="source-assessment.json">Exact previous spectrum-only evidence</a> · <a href="imaging-summary.json">New conditional imaging and range-profile limits</a></p></section>',
        '<section id="journey"><h2>Follow a saved signal to a cone</h2><ol><li>Signed electrode charge is passed through the fixed gain and electronics. Opposite faces measure the same energy; they are not added as separate deposits.</li><li>Strip energy constraints propose X/Y charge-pixel allocations. Joint signed waveform templates test depth; an aggregate half-height crossing alone cannot establish it.</li><li>Keep multiple pairings and Compton sequences, with unknown or unsupported alternatives. A charge pixel is not automatically one photon interaction.</li><li>Combine conditional event responses using the measured energies and finite vertices; retain unresolved probability and background.</li></ol>',
        '<details><summary>Interactive historical teaching events · all 34 channels</summary><p class="limits">These four exact previously published representatives teach the signal→site→cone steps. Their sites, cones and miniature accumulation displays use the legacy reconstruction. They are not new recovered events, and their illustrative maps are not the pooled results above.</p><div id="gegi-signal-journey"></div><noscript>The interactive examples need JavaScript. Their identities and hashes remain in representatives.json.</noscript></details>',
        '<p><a href="../../assemblies/gegi/index.html">Inspect the cryostat and actual saved radiation step segments</a>. The assembly display retains 214 scored segments from four saved events; they are not complete trajectories through unscored material.</p></section>',
        '<details id="accounting"><summary>Scientific accounting, failures and reproducibility</summary>',
        '<p>Original strict two-strip-per-face rejections: 39,683. The earlier truth-assisted diagnostic identified 4,184 potential candidates; that number is not a recovered yield. '+str(summary.get('legacy_candidate_transitions',{}).get('requires_two_resolved_strips_per_face',0))+' of the 39,683 strict rejections now supply conditional hypotheses; this is not validated recovery. New validated recovered groups remain zero. Initial photon and initial nuclear-decay denominators remain separate.</p><table><tr><th>New outcome</th><th>Pulse groups</th></tr>']
    htmlparts += ['<tr><td>'+esc(reason.replace('_',' '))+'</td><td>'+f'{count:,}'+'</td></tr>' for reason,count in sorted(summary['reasons'].items())]
    htmlparts += ['</table><p>Native failures retain null signal quantities. Original IDs, raw scientific files, seeds and zero-deposit totals remain preserved. The software release contains no precomputed campaign demonstration.</p>',
        '<p><a href="summary.json">Exact counts, denominators and method limits</a> · <a href="configuration.json">Preserved settings and seeds</a> · <a href="representatives.json">Legacy representative identities</a> · <a href="publication.json">SHA256 artifact manifest</a> · <a href="../../guide.html">Run the student software</a></p>']
    if summary.get('readout_check'):
        r=summary['readout_check']; htmlparts += ['<p>The independent saved readout check covered '+str(r['channels_checked'])+' channels in '+str(r['groups'])+' saved groups: ADC codes and fixed gain agree; maximum peak-voltage difference '+f"{r['maximum_peak_absolute_error_V']:.3g}"+' V. This is a software identity check, not GeGI hardware calibration.</p>']
    htmlparts += ['</details><details><summary>Methods, references and remaining limits</summary><p>The electronics model is the project’s declared circuit, not a verified implementation of proprietary GeGI electronics. COSI references inform calibration and ambiguity handling; their hardware settings are not copied into GeGI.</p><ul>',
        '<li><a href="https://arxiv.org/html/1911.02992v1">COSI detector response and reconstruction</a>: energy calibration, pairing and timing-depth limitations.</li>',
        '<li><a href="https://arxiv.org/html/2602.02442v1">Per-pixel germanium depth calibration</a>: detector-specific timing response and independent validation.</li>',
        '<li><a href="https://escholarship.org/uc/item/2k139571">Finite-vertex Compton response modelling</a>: uncertainty and alternative sequences.</li>',
        '<li><a href="https://doi.org/10.1038/s41598-021-99588-z">Quantitative gamma-ray imaging</a>: detector response, sensitivity and background requirements.</li></ul><p>The present conditional model lacks a calibrated detector sensitivity, full cross-induction templates and laboratory resolution. The imposed-plane profile is not a confidence interval for distance. Peaks do not establish the number of sources.</p></details>']
    payload = json.dumps(journey,separators=(',',':'),ensure_ascii=True,allow_nan=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    htmlparts += ['<script type="application/json" id="gegi-journey-data">'+payload+'</script><script src="gegi_signal_journey.js"></script>',
        '<script>GeGISignalJourney.mount(document.getElementById("gegi-signal-journey"),JSON.parse(document.getElementById("gegi-journey-data").textContent),{scope:"student"});</script></body></html>']
    return ''.join(htmlparts).encode('utf-8')


def export_saved(reconstruction, imaging, legacy_control, previous_public, output, *, root=ROOT, readout_checks=None, evaluation=None):
    output = Path(output).resolve(); root = Path(root).resolve()
    require(not output.exists(), 'Preserve existing publication; use a new explicit output')
    pins = _source_pins(root)
    summary, image, control, previous, inputs = _saved_inputs(reconstruction,imaging,legacy_control,previous_public)
    selected = image['group_count']
    require((image.get('source_mass') is not None) == (selected > 0), 'Empty imaging selection must not have a source map')
    require(control.get('source_mass') is not None, 'Missing legacy control map')
    if evaluation is None and (_report_path(imaging).parent/'evaluation.json').is_file():
        evaluation=_report_path(imaging).parent/'evaluation.json'
    require(not selected or evaluation is not None, 'Selected conditional imaging requires the finished posthoc evaluation')
    accuracy=_evaluation_summary(evaluation,imaging,reconstruction,image) if evaluation is not None else None
    if accuracy is not None:
        inputs['posthoc_evaluation_sha256']=sha(evaluation)
    target = output/'public'; target.mkdir(parents=True)
    figures = []
    for family, report, filename in (('new',image,'map-new-pooled.png'),('control',control,'map-legacy-control.png')):
        if not report['group_count']:
            continue
        title = 'New conditional signal hypotheses' if family=='new' else 'CONTROL: original 708 groups'
        map_figure(report,target/filename,title)
        figures.append({'family':family,'layer':'pooled','file':filename,'groups':report['group_count']})
        if family=='control':
            map_figure(report,target/'map-legacy-backprojection.png','CONTROL: angular backprojection',
                       values=report['angular_backprojection_per_rad'],units='angular likelihood / rad')
        for number,(label,layer) in enumerate(sorted(report.get('spectral_layers',{}).items())):
            require(layer['group_count'] > 0, 'Empty energy layer must not have a map')
            name=f'map-{family}-energy-{number}.png'
            map_figure({**report,'group_count':layer['group_count']},target/name,title+' | '+label,values=layer['source_mass'])
            figures.append({'family':family,'layer':label,'file':name,'groups':layer['group_count']})
    public_summary = {'kind':KIND,'status':'complete','initial_records':1_000_000,'counts':summary['counts'],
        'reasons':summary['reasons'],'original_initial_denominators':summary['original_initial_denominators'],
        'strict_rejections_before_repair':39683,'truth_diagnostic_potential_candidates_not_recovery':4184,
        'legacy_candidate_transitions':summary.get('legacy_candidate_transitions',{}),
        'selected_conditional_imaging_groups':selected,'validated_recovered_groups':0,
        'new_map_available':selected > 0,'legacy_control_groups':708,'source_distance_mm':None,
        'pooling':'All four independent acquisitions; anonymous, no equalization or simultaneous pileup.',
        'source_composition':'Two real nuclides (Cs137/Co60) plus two662keVmonoenergetic controls at two positions.',
        'independent_diagnostic_envelope':summary.get('independent_diagnostic_envelope'),
        'limitations':summary['limitations'],'input_sha256':inputs,'figures':figures}
    if accuracy is not None:
        public_summary['posthoc_evaluation']=accuracy
    if readout_checks is not None:
        public_summary['readout_check']=_readout_summary(readout_checks)
        inputs['readout_check_sha256']=sha(readout_checks)
    journey = _journey(previous_public)
    bodies={'summary.json':encoded(public_summary),'imaging-summary.json':encoded({'new':_compact_imaging(image),'legacy_control':_compact_imaging(control)}),
        'index.html':_render(public_summary,image,control,figures,journey),
        'gegi_signal_journey.js':ordinary(root/SOURCE_FILES[1]).read_bytes()}
    if accuracy is not None:
        bodies['evaluation-summary.json']=encoded(accuracy)
    for name in ('configuration.json','representatives.json','source-assessment.json'):
        bodies[name]=ordinary(Path(previous_public)/name).read_bytes()
    for name,body in bodies.items():
        (target/name).write_bytes(public(body))
    shutil.copyfile(ordinary(Path(previous_public)/'spectra.png'),target/'spectra.png')
    require(pins==_source_pins(root), 'Exporter or journey source changed during export')
    # Recheck completed inputs after generation. Hash-bound raw science is never opened.
    require(sha(Path(reconstruction)/'COMPLETE.json')==inputs['reconstruction_complete_sha256']
            and sha(_report_path(imaging))==inputs['joint_imaging_report_sha256']
            and sha(_report_path(legacy_control))==inputs['legacy_control_report_sha256'], 'Saved input changed during export')
    if accuracy is not None:
        require(sha(evaluation)==inputs['posthoc_evaluation_sha256'], 'Posthoc evaluation changed during export')
    manifest={'kind':KIND,'status':'complete','route':ROUTE,'initial_records':1_000_000,
        'replaces_public_manifest_sha256':PREVIOUS_MANIFEST,'input_sha256':inputs,
        'source_sha256':pins,'exporter_sha256':pins[SOURCE_FILES[0]],'pillow_version':PILLOW_VERSION,
        'radiation_calls':0,'native_drift_calls':0,'field_solves':0,'electronics_replays':0,'reconstruction_calls':0,
        'artifact_scope':'Saved aggregate maps plus unchanged historical34channel teaching signals; no raw science or private slides.',
        'artifacts':{p.name:{'bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted(target.iterdir())}}
    (target/'publication.json').write_bytes(public(encoded(manifest)))
    validate_public(target,root=root)
    (output/'COMPLETE.json').write_bytes(encoded({'kind':KIND,'status':'complete','public_manifest_sha256':sha(target/'publication.json'),
                                                'input_sha256':inputs,'source_sha256':pins}))
    return manifest


def validate_public(directory, *, root=ROOT):
    directory=Path(directory); manifest=read(directory/'publication.json')
    require(manifest.get('kind')==KIND and manifest.get('status')=='complete' and manifest.get('route')==ROUTE,
            'Incomplete or unsupported saved publication')
    require(manifest.get('initial_records')==1_000_000 and manifest.get('replaces_public_manifest_sha256')==PREVIOUS_MANIFEST,
            'Wrong campaign denominator or replacement binding')
    require(all(manifest.get(k)==0 for k in ('radiation_calls','native_drift_calls','field_solves','electronics_replays','reconstruction_calls')),
            'Publication must not execute simulation or analysis')
    require(manifest['source_sha256']==_source_pins(root) and manifest['exporter_sha256']==manifest['source_sha256'][SOURCE_FILES[0]],
            'Saved publication source pins changed')
    names=set(manifest['artifacts']); actual={p.name for p in directory.iterdir()}
    require(TEXT_NAMES <= names and {'spectra.png','map-legacy-control.png','map-legacy-backprojection.png'} <= names
            and actual==names|{'publication.json'}, 'Unexpected or missing public artifact')
    total=(directory/'publication.json').stat().st_size
    for name,record in manifest['artifacts'].items():
        require(name in TEXT_NAMES|OPTIONAL_TEXT_NAMES or re.fullmatch(r'(?:spectra|map-[a-z0-9-]+)\.png',name), 'Unsafe public artifact name')
        p=ordinary(directory/name);total+=p.stat().st_size
        require(p.stat().st_size==record['bytes'] and sha(p)==record['sha256'], 'Public artifact hash changed: '+name)
        if name in TEXT_NAMES|OPTIONAL_TEXT_NAMES:
            public(p.read_bytes())
    require(total<=MAX_BUNDLE_BYTES, 'Saved publication exceeds8MB')
    summary=read(directory/'summary.json')
    require(summary['status']=='complete' and summary['initial_records']==1_000_000
            and summary['counts']['pulse_groups']==sum(summary['reasons'].values())==57613
            and summary['validated_recovered_groups']==0, 'Public reconstruction accounting changed')
    require(summary['input_sha256']==manifest['input_sha256'], 'Public input hashes differ')
    require(('map-new-pooled.png' in names)==summary['new_map_available']==(summary['selected_conditional_imaging_groups']>0),
            'Unsupported new map appeared or supported map vanished')
    if summary['new_map_available']:
        require('evaluation-summary.json' in names and summary['posthoc_evaluation']==read(directory/'evaluation-summary.json')
                and summary['posthoc_evaluation']['bindings']['imaging_report_sha256']==manifest['input_sha256']['joint_imaging_report_sha256'],
                'Published accuracy evidence is missing or changed')
    public((directory/'publication.json').read_bytes())
    return manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('reconstruction','imaging','legacy-control','previous-public','output'):
        parser.add_argument('--'+name,required=True)
    parser.add_argument('--readout-checks')
    parser.add_argument('--evaluation')
    args=parser.parse_args()
    export_saved(args.reconstruction,args.imaging,args.legacy_control,args.previous_public,args.output,readout_checks=args.readout_checks,evaluation=args.evaluation)
