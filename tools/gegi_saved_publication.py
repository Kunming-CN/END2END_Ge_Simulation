"""Export finished GeGI saved-data corrections; never run physics or analysis.

Only completion seals, aggregate reports and already-public teaching traces are
read. The old 708-group reconstruction remains an explicitly separate control.
"""
from __future__ import annotations
import argparse
from collections import Counter
import gzip
import hashlib
import html
import json
import math
from pathlib import Path
import re
import shutil
import numpy as np
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
OPTIONAL_TEXT_NAMES = {'evaluation-summary.json', 'recovery-summary.json', 'cone-display.json'}


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


def _saved_inputs(reconstruction, imaging, legacy_control, previous_public, *, population=None, map_records=None):
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
    migration = None
    if population is not None:
        migration = _population_inputs(population, map_records, reconstruction, image_path, image)
        bindings = None
    else:
        require(map_records is None, 'Map records require an explicit order-prior population')
        accounting = image['saved_signal_accounting']; bindings = accounting['input_sha256']
    require(bindings is None or (bindings['COMPLETE.json'] == sha(reconstruction/'COMPLETE.json')
            and bindings['summary.json'] == complete['summary_sha256']
            and bindings['identity.json'] == complete['identity_sha256']),
            'Imaging report does not bind the completed reconstruction')
    # The imaging reader already verified every derived data byte. Check its
    # complete binding inventory and small receipts, without rereading science.
    seen = set(); receipt_counts = Counter(); receipt_reasons = Counter()
    for chunk in complete['chunks']:
        index = chunk['chunk_index']; require(index not in seen, 'Duplicate reconstruction chunk'); seen.add(index)
        rname, dname = f'chunks/{index:03d}.json', f'chunks/{index:03d}.jsonl.gz'
        require(chunk['receipt_sha256'] == sha(reconstruction/rname)
                and (bindings is None or (bindings[rname] == chunk['receipt_sha256']
                     and bindings[dname] == chunk['data_sha256'])), 'Imaging input chunk binding changed')
        receipt = read(reconstruction/rname)
        require(receipt['sha256'] == chunk['data_sha256'] and receipt['source_sha256'] == summary['source_sha256'],
                'Derived chunk recipe differs from completed summary')
        receipt_counts.update(receipt['counts']); receipt_reasons.update(receipt['reasons'])
    require(len(seen) == 100 and dict(receipt_counts) == counts and dict(receipt_reasons) == summary['reasons'],
            'Derived chunk accounting does not match completed summary')
    require((migration is not None and migration['population']['original_saved_reconstruction_counts'] == counts
                and migration['population']['counts']['all_saved_nonzero_groups'] == counts['pulse_groups']
                and migration['population']['counts']['candidate_bearing_groups'] == counts['conditional_candidate_groups']
                and migration['population']['counts']['candidates'] == counts['conditional_candidates'])
            or (migration is None and accounting['counts']['nonzero_pulse_groups'] == counts['pulse_groups']
                and accounting['counts']['groups_with_conditional_candidates'] == counts['conditional_candidate_groups']
                and image['group_count'] == accounting['counts'].get('selected_conditional_groups', 0)),
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
    if migration is not None:
        inputs.update(migration['bindings'])
    return summary, image, control, previous, inputs, migration


def _population_inputs(population, map_records, reconstruction, image_path, image):
    """Explicit derivative boundary; the original saved-reconstruction gate stays strict."""
    population = Path(population)
    require(map_records is not None, 'Order-prior publication requires the exact selected map records')
    seal, report = read(population/'COMPLETE.json'), read(population/'result.json')
    require(seal.get('status') == 'completed_sparse_population_and_one_map'
            and report.get('kind') == 'gegi_order_prior_population_v1'
            and seal['result_sha256'] == sha(population/'result.json')
            and seal['identity_sha256'] == sha(population/'identity.json'), 'Population completion binding changed')
    digest = sha(map_records)
    require(report['input_sha256']['reconstruction_complete'] == sha(Path(reconstruction)/'COMPLETE.json')
            and report['artifact_sha256']['imaging/report.json'] == sha(image_path)
            and report['artifact_sha256']['imaging/event_diagnostics.jsonl'] == sha(image_path.parent/'event_diagnostics.jsonl')
            and report['input_sha256']['map_records'] == image['provenance']['map_input_sha256'] == digest
            and image['provenance']['population_identity_sha256'] == seal['identity_sha256'],
            'Order-prior population or map-selection binding changed')
    require(report['verification']['map153_287_matches_population_exactly'] is True
            and report['verification']['all434_nonweight_records_exactly_equal'] is True,
            'Unverified order-prior population')
    with gzip.open(ordinary(map_records), 'rt', encoding='utf-8') as stream:
        records = [json.loads(line) for line in stream]
    identities = [(r['campaign_initial_id'], r['pulse_group_id']) for r in records]
    census = [json.loads(line) for line in ordinary(image_path.parent/'event_diagnostics.jsonl').read_text().splitlines()]
    require(len(records) == image['group_count'] == 153 and len(set(identities)) == len(records)
            and sum(len(r['candidates']) for r in records) == 287
            and [(r['campaign_initial_id'], r['pulse_group_id'], len(r['candidates'])) for r in records]
                == [(r['event_id'], r['pulse_group_id'], r['candidate_count']) for r in census],
            'Selected map record census changed')
    require(all(len(c['order']) == 2 and math.isfinite(c['prior_weight']) and 0 < c['prior_weight'] <= 1
                for r in records for c in r['candidates']), 'Invalid two-site candidate or prior')
    require(all(sum(c['prior_weight'] for c in r['candidates']) <= 1+1e-12 for r in records),
            'Candidate priors exceed original group mass')
    return {'population': report, 'records': records, 'map_records_path': Path(map_records),
        'bindings': {'order_prior_population_result_sha256': sha(population/'result.json'),
            'order_prior_population_identity_sha256': seal['identity_sha256'],
            'order_prior_population_complete_sha256': sha(population/'COMPLETE.json'),
            'selected_map_records_sha256': digest,
            'original_map_selection_sha256': report['input_sha256']['old_map_records']}}


def _font(size):
    for name in ('DejaVuSans.ttf', 'arial.ttf'):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


def map_figure(report, path, title, *, values=None, units='conditional source mass / grid cell', equal_aspect=False):
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
    if equal_aspect:
        width = height
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
            and report['candidate_count']==(image['saved_signal_accounting']['counts']['selected_candidates']
                if 'saved_signal_accounting' in image else sum(row['candidate_count'] for row in
                    map(json.loads, ordinary(image_path.parent/'event_diagnostics.jsonl').read_text().splitlines()))),
            'Evaluation selected-group or candidate census changed')
    require(report.get('distance_mm') is None and report.get('activity_bq') is None
            and report.get('range_identified') is False, 'Unsupported range or activity in evaluation')
    # Retain aggregate numerical evidence; per-event truth rows remain local.
    result = {k:report[k] for k in ('kind','scope','bindings','selected_id_census_sha256','selection_unchanged',
        'truth_used_in_imaging','group_count','candidate_count','weighting','residual_definition','groups','pooled',
        'energy_layers','distance_mm','activity_bq','range_identified','interpretation')}
    if 'angular_metrics_unavailable_reason' in report:
        result['angular_metrics_unavailable_reason'] = report['angular_metrics_unavailable_reason']
    return result


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


def _recovery_summary(directory, reconstruction, imaging, summary, inputs):
    """Admit finished evidence; publish only named aggregate fields, never rows/paths."""
    directory = Path(directory); reconstruction = Path(reconstruction)
    names = ('validation/report.json', 'validation/split-manifest.json', 'validation/evaluation-groups.json',
             'peak-diagnostic/report.json', 'peak-diagnostic/COMPLETE.json', 'calibration/inventory.json',
             'calibration/inputs.jsonl', 'signal-use-v2/summary.json', 'signal-use-v2/identity.json',
             'signal-use-v2/COMPLETE.json', 'validation/readout-diagnosis.json', 'validation/endpoint-weights.json')
    bindings = {name: sha(directory/name) for name in names}
    validation, split = [read(directory/name) for name in names[:2]]
    groups = read(directory/'validation/evaluation-groups.json')
    rec_complete, rec_summary = inputs['reconstruction_complete_sha256'], inputs['reconstruction_summary_sha256']
    require(validation.get('kind') == split.get('kind') == 'gegi_saved_recovery_validation_v1'
            and validation.get('stage') == 'posthoc_evaluation_completed'
            and split.get('stage') == 'frozen_before_truth_evaluation', 'Recovery validation is unfinished')
    require(split['reconstruction_complete_sha256'] == rec_complete and split['reconstruction_summary_sha256'] == rec_summary
            and validation['split_manifest_sha256'] == bindings['validation/split-manifest.json']
            and validation['evaluation_groups_sha256'] == bindings['validation/evaluation-groups.json']
            and groups['split_manifest_sha256'] == bindings['validation/split-manifest.json'],
            'Recovery validation does not bind the frozen reconstruction/split')
    require(all(validation[k] == 0 for k in ('new_calibration_calls','new_fit_calls','new_physics_calls'))
            and split['selection_truth_used'] is False and split['selection_source_labels_used'] is False,
            'Recovery evidence must retain saved-only, truth-blind selection')
    require(validation['counts'] == {'events':400,'groups':400} and split['counts'] ==
            {'events':400,'groups':400,'groups_by_split':{'development':200,'holdout':200}}
            and len(groups['groups']) == len(split['groups']) == len(split['assignments']) == 400,
            'Recovery frozen400-group census changed')
    assignments = {r['campaign_initial_id']: r['split'] for r in split['assignments']}
    require(len(assignments) == 400 and Counter(assignments.values()) == {'development':200,'holdout':200}
            and all(assignments[r['campaign_initial_id']] == r['split'] for r in split['groups']),
            'Recovery split leaks or duplicates original events')
    sample = {}
    for name in ('development','holdout'):
        row = validation['by_split'][name]; counts = row['counts']
        require(counts['groups'] == counts['original_spectroscopy_exact_match_groups'] == 200
                and counts['classified_imaging_supported_groups'] == 0,
                'Recovery sample changed original energy or promoted unsupported imaging')
        sample[name] = {'groups':200, 'original_energy_exact_matches':200,
            'conditional_hypotheses': {k:row['conditional_hypothesis_counts'][k] for k in
                ('conditional_hypotheses','pairing_mismatches','pairing_known','false_splitting','splitting_known')},
            'sequence_candidates': {k:row['sequence'][k] for k in ('correct','wrong','unknown')},
            'conditional_cell_abs_depth_mm': {k:row['errors']['abs_depth_mm'][k] for k in ('n','median','p90','max')}}
    use = read(directory/'signal-use-v2/summary.json'); complete = read(directory/'signal-use-v2/COMPLETE.json')
    identity = read(directory/'signal-use-v2/identity.json')
    require(use.get('kind') == identity.get('kind') == complete.get('kind') == 'gegi_saved_signal_use_v1'
            and use.get('status') == complete.get('status') == 'completed_signal_use_classification'
            and complete['summary_sha256'] == bindings['signal-use-v2/summary.json']
            and complete['identity_sha256'] == bindings['signal-use-v2/identity.json'], 'Signal-use completion binding changed')
    require(use['campaign_complete_sha256'] == identity['campaign_complete_sha256'] == summary['campaign_complete_sha256']
            and use['reconstruction_complete_sha256'] == identity['reconstruction_complete_sha256'] == rec_complete
            and use['reconstruction_summary_sha256'] == identity['reconstruction_summary_sha256'] == rec_summary,
            'Signal-use evidence belongs to a different campaign/reconstruction')
    require(all(use[k] == 0 for k in ('new_calibration_calls','new_field_calls','new_native_calls','new_radiation_calls',
            'repeated_waveform_fits','new_energy_reconstructions','new_validated_imaging_recoveries'))
            and use['spectroscopy_matches_original_readout'] is True, 'Signal-use evidence altered saved reconstruction')
    categories = {k:use['categories'][k] for k in
                  ('spectroscopy_only','ambiguous_imaging','failed_or_incomplete','unresolved_signal')}
    require(set(use['categories']) == set(categories) and sum(categories.values()) == use['counts']['pulse_groups'] == 57613
            and use['counts']['conditional_candidate_groups'] == summary['counts']['conditional_candidate_groups'],
            'Signal-use classification census or conditional candidates changed')
    totals = Counter(); indexes = set()
    for chunk in complete['chunks']:
        require(chunk['chunk_index'] not in indexes, 'Duplicate signal-use chunk')
        indexes.add(chunk['chunk_index']); totals.update(chunk['counts'])
    require(len(indexes) == 100 and dict(totals) == use['counts'], 'Signal-use chunk totals differ from summary')
    calibration = read(directory/'calibration/inventory.json')
    require(calibration.get('status') == 'complete_full34_responses_absent'
            and calibration['counts']['injection_records'] == 2991 and calibration['counts']['full34_records'] == 0
            and calibration['saved_drift_trajectories']['present'] is False
            and calibration['input_manifest']['sha256'] == bindings['calibration/inputs.jsonl'],
            'Calibration inventory is incomplete or changed')
    bank = [json.loads(line) for line in ordinary(directory/'calibration/inputs.jsonl').read_bytes().splitlines()]
    require(any(r['ref'].endswith('/pixel-calibration/depth-calibration.json') and
                r['sha256'] == read(reconstruction/'identity.json')['calibration_sha256'] for r in bank),
            'Calibration inventory does not describe the reconstruction bank')
    peak = read(directory/'peak-diagnostic/report.json'); peak_complete = read(directory/'peak-diagnostic/COMPLETE.json')
    provenance = peak['provenance']; saved = provenance['saved_input_sha256']
    require(peak.get('kind') == 'gegi_saved_peak_diagnostic_v1' and peak['group_count'] == 19
            and len(peak['selected_original_ids']) == 19 and peak['candidate_count'] == 58
            and peak_complete['files']['report.json'] == bindings['peak-diagnostic/report.json']
            and provenance['baseline_report_sha256'] == inputs['joint_imaging_report_sha256']
            and saved['COMPLETE.json'] == rec_complete and saved['summary.json'] == rec_summary
            and provenance['truth_used'] is False and provenance['source_labels_used'] is False
            and provenance['new_transport_drift_fields_or_calibration'] == 0,
            'Peak diagnostic does not bind the unchanged saved map')
    require(imaging['spectral_layers']['1332.49_keV']['group_count'] == 19,
            'Peak diagnostic energy-layer census changed')
    diagnosis = read(directory/'validation/readout-diagnosis.json')
    require(diagnosis.get('kind') == 'gegi_frozen_development_saved_readout_diagnosis_v1'
            and diagnosis['evaluation_report_sha256'] == bindings['validation/report.json']
            and diagnosis['split_manifest_sha256'] == bindings['validation/split-manifest.json']
            and diagnosis['evaluation_groups_sha256'] == bindings['validation/evaluation-groups.json']
            and all(diagnosis[k] == 0 for k in ('new_calibration_calls','new_fit_calls','new_native_calls','new_transport_calls')),
            'Readout diagnosis does not bind frozen saved-only development evidence')
    checked = [r['independent_circuit_check'] for r in diagnosis['selected_groups']]
    require(len(checked) == 3 and all(r['split'] == 'development' for r in diagnosis['selected_groups'])
            and sum(r['channels_checked'] for r in checked) == 102
            and all(r['all_ADC_codes_equal'] and r['all_fixed_energy_gains_equal'] for r in checked),
            'Development circuit identity check failed')
    endpoint = read(directory/'validation/endpoint-weights.json')
    endpoint_diagnosis = diagnosis['saved_field_endpoint_diagnosis']; accepted = endpoint_diagnosis['acceptance']
    guard_identity = diagnosis['selected_groups'][2]['original_identity']
    require(endpoint_diagnosis['endpoint_result_sha256'] == bindings['validation/endpoint-weights.json']
            and endpoint.get('kind') == 'gegi_saved_endpoint_weight_result_v1'
            and endpoint['original_bindings']['metadata_sha256'] == guard_identity['metadata_sha256']
            and all(guard_identity[k] == v for k,v in endpoint['original_identity'].items())
            and accepted['all_contact_mappings_identical'] is True
            and accepted['contact_endpoint_mappings_compared'] == 86
            and accepted['saved_native_terminal_values_compared'] == 34
            and accepted['max_abs_prediction_error_keV'] == endpoint['max_abs_prediction_error_keV'] == 0
            and endpoint['native_precision_bits'] == 32
            and all(endpoint[k] == 0 for k in ('new_calibration_calls','new_drift_calls','new_field_solves'))
            and all(accepted[k] == 0 for k in ('new_drift_calls','new_field_solves','new_injection_calls')),
            'Saved endpoint diagnosis identity, terminal agreement or no-new-physics binding changed')
    transient, _, guard = diagnosis['findings']
    result = {'kind':'gegi_public_saved_recovery_evidence_v1', 'input_sha256':bindings,
        'campaign_complete_sha256':summary['campaign_complete_sha256'],
        'reconstruction_complete_sha256':rec_complete, 'reconstruction_summary_sha256':rec_summary,
        'classification': {'groups':57613,'categories':categories,
            'overlapping_signal_features': {k:use['counts'][k] for k in
                ('spectroscopy_groups','guard_collection_groups','guard_transient_groups','adjacent_strip_groups','native_failed_groups')},
            'new_energy_reconstructions':0,'new_validated_imaging_recoveries':0},
        'frozen_stratified_sample':sample,
        'calibration': {'injections':2991,'full34_responses':0,
            'records_by_stored_channel_count':calibration['counts']['records_by_stored_channel_count'],
            'saved_drift_trajectories_present':calibration['saved_drift_trajectories']['present']},
        'peak_diagnostic': {'energy_keV':peak['energy_center_keV'],'groups':19,'candidates':58,'grid':peak['grid'],
            'baseline_peaks':[{k:p[k] for k in ('position_mm','on_image_edge')} for p in peak['baseline']['blind_peaks']],
            'leave_one_group_out':[{k:p[k] for k in ('position_mm','omissions_with_displayed_mode_within_8_mm',
                'nearest_displayed_mode_distance_mm_min_max')} for p in peak['leave_one_group_out_summary']],
            'grid_iteration_cases':len(peak['grid_iteration_sensitivity'])},
        'readout_diagnosis': {'development_groups':3,'channels_checked':102,'ADC_codes_equal':True,'fixed_gains_equal':True,
            'maximum_peak_absolute_error_V':max(r['max_peak_absolute_error_V'] for r in checked),
            'collecting_strip_transient':{k:transient['evidence'][k] for k in
                ('mean_ADC_minus_terminal_keV','X_strip_9_terminal_keV','X_strip_9_charge_transient_max_keV','X_strip_9_analog_peak_energy_keV')},
            'guard_terminal':{k:guard['evidence'][k] for k in ('mean_native_terminal_deficit_keV','deposition_keV')},
            'guard_contact_endpoints':sum(diagnosis['selected_groups'][2]['endpoint_status_counts'].values()),
            'saved_field_endpoint_diagnosis': {'contact_mappings_identical':True,'contact_endpoints':86,
                'native_terminal_values_compared':34,'max_abs_prediction_error_keV':0.0,'native_precision_bits':32,
                'own_guard_weighting_potential_bounds':{k:endpoint_diagnosis['bounds'][k] for k in
                    ('electron_guard34_own_phi_min','electron_guard34_own_phi_max','hole_guard17_own_phi_min','hole_guard17_own_phi_max')},
                'new_drift_calls':0,'new_field_solves':0,'new_injection_calls':0}}}
    public(encoded(result))
    return result, {directory/name:digest for name,digest in bindings.items()}


def _recovery_html(evidence):
    if evidence is None:
        return ''
    c = evidence['classification']; n = c['categories']; sample = evidence['frozen_stratified_sample']
    parts = ['<section id="saved-evidence"><h2>What the saved-data checks establish</h2>',
        f'<p>All {c["groups"]:,} saved groups now have a use category: <strong>{n["spectroscopy_only"]:,} spectroscopy only</strong>, '
        f'{n["ambiguous_imaging"]:,} with ambiguous imaging hypotheses, {n["failed_or_incomplete"]:,} failed or incomplete, '
        f'and {n["unresolved_signal"]:,} unresolved. Original readout energies are retained. No new validated imaging recovery is claimed.</p>',
        '<p>A frozen stratified sample of 400 original events was divided before truth evaluation into 200 development and 200 holdout events. '
        'All 400 original energy records match exactly. This diagnostic sample does not estimate campaign efficiency.</p>',
        '<details><summary>Pairing, splitting and sequence checks</summary><table><tr><th>Posthoc check</th><th>Development</th><th>Holdout</th></tr>']
    features = c['overlapping_signal_features']
    parts.insert(2, '<details><summary>Guard and adjacent-strip signal features</summary>'
        f'<p>Spectroscopy is usable in {features["spectroscopy_groups"]:,} groups, including the ambiguous imaging category. '
        f'Terminal guard collection appears in {features["guard_collection_groups"]:,} groups, guard transients in {features["guard_transient_groups"]:,}, '
        f'and adjacent strips in {features["adjacent_strip_groups"]:,}. These feature counts overlap and must not be added to the use categories.</p></details>')
    def row(label, values):
        return '<tr><td>'+label+'</td>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in values)+'</tr>'
    parts.append(row('Pairing mismatches / checked conditional hypotheses', [f'{r["conditional_hypotheses"]["pairing_mismatches"]}/{r["conditional_hypotheses"]["pairing_known"]}' for r in sample.values()]))
    parts.append(row('False splits / checked conditional hypotheses', [f'{r["conditional_hypotheses"]["false_splitting"]}/{r["conditional_hypotheses"]["splitting_known"]}' for r in sample.values()]))
    parts.append(row('Sequence candidates: correct / wrong / unknown', [' / '.join(str(r['sequence_candidates'][k]) for k in ('correct','wrong','unknown')) for r in sample.values()]))
    parts.append(row('Matched conditional cells; median / 90th-percentile absolute depth error (mm)', [f'{r["conditional_cell_abs_depth_mm"]["n"]}; {r["conditional_cell_abs_depth_mm"]["median"]:.3f} / {r["conditional_cell_abs_depth_mm"]["p90"]:.3f}' for r in sample.values()]))
    parts += ['</table><p>Hypotheses and sequence candidates are not independent events. Pairing compares native endpoint cells; sequence correctness is known only for uniquely traceable single-photon anchors. '
        'Depth errors apply only to matched conditional cells, not all events or experimental resolution. Unknown sequence cases stay unknown.</p></details>']
    p = evidence['peak_diagnostic']; keep = p['leave_one_group_out']
    parts += [f'<details><summary>The 1332.492-keV layer: {p["groups"]} groups, {p["candidates"]} conditional candidates</summary>'
        '<p>The two maxima near (38, −2) and (46, 18) mm use the imposed z = 40 mm plane. '
        f'After omitting each group in turn, a displayed mode stays within 8 mm of these positions in {keep[0]["omissions_with_displayed_mode_within_8_mm"]}/19 and {keep[1]["omissions_with_displayed_mode_within_8_mm"]}/19 cases. '
        f'{p["grid_iteration_cases"]} saved grid/iteration cases test numerical sensitivity. These maxima do not identify two Co-60 sources or establish resolution.</p></details>']
    d = evidence['readout_diagnosis']; t = d['collecting_strip_transient']; g = d['guard_terminal']
    endpoint = d['saved_field_endpoint_diagnosis']; phi = endpoint['own_guard_weighting_potential_bounds']
    parts += ['<details><summary>Where the energy interpretation needs work</summary>'
        f'<p>An independent analytic check reproduces all {d["channels_checked"]} channel ADC codes and fixed gains in three development groups. '
        f'In the transient case, a strip ends at {t["X_strip_9_terminal_keV"]:.3f} keV charge-equivalent after a {t["X_strip_9_charge_transient_max_keV"]:.3f} keV transient; '
        f'its shaped positive peak is {t["X_strip_9_analog_peak_energy_keV"]:.3f} keV-equivalent. The mean-face ADC sum exceeds terminal charge by {t["mean_ADC_minus_terminal_keV"]:.3f} keV. '
        'Separately timed strip maxima therefore cannot automatically be interpreted as collected pixel energies.</p>'
        f'<p>The guard case has {d["guard_contact_endpoints"]} contact endpoints but a {abs(g["mean_native_terminal_deficit_keV"]):.3f} keV mean terminal deficit. '
        'The saved-field check establishes the cause for this event: Cartesian interpolation mixes contact and neighboring noncontact grid nodes. '
        'The contact nodes have own-electrode weighting potential 1, but the continuous endpoints interpolate below 1: '
        f'electron guard {phi["electron_guard34_own_phi_min"]:.5f}–{phi["electron_guard34_own_phi_max"]:.5f}; '
        f'hole guard {phi["hole_guard17_own_phi_min"]:.5f}–{phi["hole_guard17_own_phi_max"]:.5f} (dimensionless). '
        f'All {endpoint["contact_endpoints"]} contact identities agree, and the original Float32 endpoint algebra reproduces all '
        f'{endpoint["native_terminal_values_compared"]} saved terminal values with exactly 0.0 keV error. '
        'This diagnoses one development event without new drift, field solves or injections. A waveform correction remains unvalidated; do not force final charge to deposited energy.</p></details>',
        '<p><strong>Next operation:</strong> use the forward response of charge transport and the declared circuit to constrain the inverse signal model, including induced transients. '
        'The original 2,991 calibration records contain selected X/Y signals and no complete 34-channel response basis or saved drift trajectories. '
        'A supported inverse model needs that missing response information; original energies, maps and uncertainty remain intact.</p>'
        '<p><a href="recovery-summary.json">Aggregate evidence and exact input hashes</a></p></section>']
    return ''.join(parts)


def _clipped_paths(points, valid, extent):
    """Reuse the saved cone-overlay renderer's segment clipping at asymptotes."""
    indexes = np.flatnonzero(valid[:-1] & valid[1:])
    if not len(indexes):
        return []
    p, q = points[indexes], points[indexes+1]
    delta = q-p
    lower, upper = np.zeros(len(p)), np.ones(len(p))
    keep = np.ones(len(p), dtype=bool)
    for dim in (0, 1):
        parallel = np.abs(delta[:, dim]) < 1e-20
        keep &= ~(parallel & (np.abs(p[:, dim]) > extent))
        left = np.divide(-extent-p[:, dim], delta[:, dim], out=np.full(len(p), -np.inf), where=~parallel)
        right = np.divide(extent-p[:, dim], delta[:, dim], out=np.full(len(p), np.inf), where=~parallel)
        lower = np.maximum(lower, np.minimum(left, right))
        upper = np.minimum(upper, np.maximum(left, right))
    keep &= lower <= upper
    ids = indexes[keep]
    starts, ends = p[keep]+lower[keep, None]*delta[keep], p[keep]+upper[keep, None]*delta[keep]
    if not len(ids):
        return []
    breaks = np.flatnonzero((np.diff(ids) != 1) | (np.linalg.norm(starts[1:]-ends[:-1], axis=1) > 1e-7))+1
    return [np.vstack((starts[group[0]], ends[group])) for group in np.split(np.arange(len(ids)), breaks)]


def _cone_paths(candidate, z, extent):
    axis, vertex = np.asarray(candidate['axis'], dtype=float), np.asarray(candidate['vertex_mm'], dtype=float)
    theta = math.radians(candidate['half_angle_deg'])
    require(axis.shape == vertex.shape == (3,) and np.isfinite(axis).all() and np.isfinite(vertex).all()
            and abs(np.linalg.norm(axis)-1) < 1e-9 and 0 < theta < math.pi
            and abs(math.cos(theta)-candidate['cos_theta']) < 1e-12,
            'Invalid saved cone geometry')
    helper = np.eye(3)[int(np.argmin(np.abs(axis)))]; u = np.cross(axis, helper); u /= np.linalg.norm(u)
    v = np.cross(axis, u); phi = np.linspace(0, 2*np.pi, 16385)
    directions = math.cos(theta)*axis[None, :]+math.sin(theta)*(
        np.cos(phi)[:, None]*u+np.sin(phi)[:, None]*v)
    distances = np.divide(z-vertex[2], directions[:, 2], out=np.full(len(phi), np.nan),
        where=np.abs(directions[:, 2]) > 1e-14)
    valid = np.isfinite(distances) & (distances > 0)
    xy = vertex[:2]+distances[:, None]*directions[:, :2]
    inside = valid & (np.abs(xy).max(axis=1) <= extent)
    residual = 0.
    if inside.any():
        rays = np.column_stack((xy[inside], np.full(inside.sum(), z)))-vertex
        residual = float(np.max(np.abs((rays @ axis)/np.linalg.norm(rays, axis=1)-math.cos(theta))))
    require(residual < 1e-10, 'Cone-plane sampled points do not satisfy saved cone')
    return _clipped_paths(xy, valid, extent), residual


def _cone_figure(records, report, path, title):
    z, extent = report['grid']['assumed_z_mm'], report['grid']['extent_mm']
    canvas = Image.new('RGB', (960,720), '#091221'); draw = ImageDraw.Draw(canvas, 'RGBA')
    left, top, side = 95, 100, 530
    white, muted = '#f1f7ff', '#b2c8da'
    draw.text((36,20), title, fill=white, font=_font(23))
    draw.text((36,55), f'{len(records):,} observed groups; imposed z = {z:g} mm', fill=muted, font=_font(18))
    for fraction in (0,.25,.5,.75,1):
        px, py = left+fraction*side, top+(1-fraction)*side
        value = -extent+2*extent*fraction
        draw.line((px,top,px,top+side), fill=(126,160,185,35))
        draw.line((left,py,left+side,py), fill=(126,160,185,35))
        draw.text((px,top+side+10),f'{value:g}',fill=white,font=_font(15),anchor='mt')
        draw.text((left-12,py),f'{value:g}',fill=white,font=_font(15),anchor='rm')
    palette = ((85,214,237),(255,184,107),(183,160,255),(101,223,178),(241,141,183),(241,223,130))
    visible, max_residual = 0, 0.
    for i, record in enumerate(records):
        for candidate in record['candidates']:
            paths, residual = _cone_paths(candidate,z,extent); max_residual=max(max_residual,residual)
            visible += bool(paths)
            # One shared display scale; never renormalize surviving orders/events.
            colour = (*palette[i%len(palette)], round(255*.58*candidate['prior_weight']))
            for points in paths:
                pixels = [(left+(x+extent)*side/(2*extent),top+(extent-y)*side/(2*extent)) for x,y in points]
                draw.line(pixels, fill=colour, width=1)
    draw.rectangle((left,top,left+side,top+side),outline=muted)
    draw.text((left+side/2,top+side+40),'x (mm)',fill=white,font=_font(18),anchor='mt')
    draw.text((24,top+side/2),'y (mm)',fill=white,font=_font(18))
    for i, line in enumerate(('Colour: group','Opacity: saved prior',f'{visible} candidates in view','No fitted intensity')):
        draw.text((675,150+32*i),line,fill=muted,font=_font(16))
    canvas.save(path,format='PNG',optimize=True)
    return {'visible_candidates':visible,'maximum_sampled_cone_cosine_residual':max_residual}


def _cone_display(target, image, migration):
    records = migration['records']; layers = []
    specifications = [('pooled', 'All selected energies', records, image)]
    for label, layer in image['spectral_layers'].items():
        center = float(label.removesuffix('_keV'))
        subset = [r for r in records if abs(r['energy_keV']-center) <= max(5., .02*center)]
        require(len(subset)==layer['group_count'], 'Cone display energy-layer census changed')
        specifications.append((label,label.replace('_',' '),subset,{**image,**layer}))
    for number, (label,title,subset,report) in enumerate(specifications):
        filenames = {name:f'map-cone-{number}-{name}.png' for name in ('overlay','density','conditional')}
        if number == 0:
            filenames['conditional'] = 'map-new-pooled.png'
        geometry = _cone_figure(subset,report,target/filenames['overlay'],'Cone-plane intersections')
        map_figure(report,target/filenames['density'],'Summed angular response',
            values=report['angular_backprojection_per_rad'],units='angular likelihood / rad',equal_aspect=True)
        map_figure(report,target/filenames['conditional'],'Saved conditional image',equal_aspect=True)
        layers.append({'id':f'cone-layer-{number}','label':label,'title':title,'groups':len(subset),
            'candidates':sum(len(r['candidates']) for r in subset),'files':filenames,
            'candidate_prior_mass':sum(c['prior_weight'] for r in subset for c in r['candidates']),**geometry})
    return {'kind':'gegi_saved_cone_plane_display_v1','layers':layers,
        'default_layer':next(l['id'] for l in layers if l['label'].startswith('1332.')),
        'plane_z_mm':image['grid']['assumed_z_mm'],'extent_mm':image['grid']['extent_mm'],
        'em_iterations':image['em_iterations'],'stop_status':'iteration_budget_reached',
        'input_sha256':migration['bindings'],'phi_segments_per_cone':16384,
        'overlay_weighting':'Opacity=0.58*original candidate prior; no per-event renormalization.',
        'density':'Saved angular_backprojection_per_rad, linear colour scale; no new smoothing or optimizer.',
        'truth_or_source_markers':False}


def _render_cone_page(summary, imaging, control, journey=None):
    esc = lambda v:html.escape(str(v),quote=True)
    display = summary['cone_plane_display']; default = display['default_layer']
    parts = ['<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
        '<title>GeGI Compton imaging · GeSignal</title><style>body{font:16px/1.55 system-ui;color:#172e43;background:#f6f9fc;max-width:1180px;margin:auto;padding:20px}h1{font-size:2.4rem;line-height:1.15}a{color:#075e9b}select{font:inherit;padding:8px 12px;border:1px solid #7797ac;border-radius:6px;background:white}.plots{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,330px),1fr));gap:16px}figure{margin:0;background:white;border:1px solid #d3e0e9;border-radius:10px;overflow:hidden}img{display:block;width:100%;height:auto}figcaption{padding:12px}details{background:white;padding:14px 18px;border:1px solid #d3e0e9;border-radius:8px;margin:22px 0}summary{cursor:pointer;font-weight:650}.caption{color:#455f73}.status{padding:12px 16px;border-left:4px solid #087f91;background:#e7f2f6}[hidden]{display:none!important}code{overflow-wrap:anywhere}</style></head><body>',
        page_navigation(ROUTE),'<h1>GeGI Compton imaging</h1>',
        '<p>Follow the signal-derived candidate cones from their intersections with a fixed plane to the summed angular response and saved conditional image.</p>',
        '<nav class="local"><a href="#new-map">Compton images</a> · <a href="#spectra">Historical control</a> · <a href="#journey">Teaching events</a></nav>',
        '<section id="new-map"><label for="cone-energy">Readout energy </label><select id="cone-energy">']
    for layer in display['layers']:
        parts.append('<option value="'+layer['id']+'"'+(' selected' if layer['id']==default else '')+'>'+esc(layer['title'])+'</option>')
    parts += ['</select>',f'<p class="status">Fixed plane z = {display["plane_z_mm"]:g} mm; x and y in mm.</p>']
    captions = {'overlay':('Cone-plane intersections','Curves are sampled from the saved cones. Colour identifies a group; opacity follows its candidate prior.'),
        'density':('Summed angular response','Saved candidate responses added with their priors. Linear colour scale, angular likelihood per radian.'),
        'conditional':('Saved conditional image','Conditional source mass per grid cell, using the same selected candidates and retained unresolved weight.')}
    for layer in display['layers']:
        sample_note = ' Small sample; limited statistics.' if layer['label'].startswith('1332.') else ''
        parts.append('<article class="cone-layer" id="'+layer['id']+'"'+(' hidden' if layer['id']!=default else '')+'><h2>'+esc(layer['title'])+'</h2><p><strong>'+str(layer['groups'])+' groups · '+str(layer['candidates'])+' candidate cones</strong>.'+sample_note+' '+str(layer['visible_candidates'])+' candidate intersections enter the displayed square.</p><div class="plots">')
        for name,(title,caption) in captions.items():
            filename=layer['files'][name]
            parts.append('<figure><a href="'+filename+'"><img loading="lazy" src="'+filename+'" alt="'+esc(title+' for '+layer['title'])+'"></a><figcaption><strong>'+title+'</strong><br>'+caption+' <a href="'+filename+'">Full size</a></figcaption></figure>')
        parts.append('</div></article>')
    parts += ['<p class="caption">Curves show cone-plane intersections on the fixed plane.</p>',
        '<noscript><p>Choose the other energy layers with JavaScript enabled, or open <a href="cone-display.json">the figure list</a>.</p></noscript>',
        '<details id="accounting"><summary>Selection, uncertainty and saved evidence</summary><p>All '+str(imaging['group_count'])+' selected groups contribute '+str(sum(l['candidates'] for l in display['layers'][:1]))+' candidates. The original acquisition retains 1,000,000 initial records and 57,613 nonzero pulse groups. Unsupported site orders retain unresolved weight; surviving candidates are not renormalized to a full event.</p>',
        '<p>The saved conditional fit stopped at '+str(display['em_iterations'])+' iterations; convergence has not been established. Its finite angular response uses the saved position/discrepancy model. Source distance and source count remain unidentified; event recovery and laboratory resolution are not validated by these figures.</p>',
        '<p><a href="evaluation-summary.json">Posthoc evaluation</a> · <a href="cone-display.json">Plot settings and input bindings</a> · <a href="imaging-summary.json">Imaging summary</a> · <a href="summary.json">Original denominators and accounting</a> · <a href="publication.json">Artifact hashes</a></p></details>',
        '</section><section id="spectra"><details><summary>Historical 708-group control and spectrum</summary><p>The control retains its previous reconstruction and input. Its population differs from the current signal-selected groups.</p><img loading="lazy" src="map-legacy-control.png" alt="Historical 708-group conditional control"><img loading="lazy" src="spectra.png" alt="Saved original spectra"></details></section>']
    if journey is not None:
        payload = json.dumps(journey,separators=(',',':'),ensure_ascii=True,allow_nan=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
        parts += ['<section id="journey"><details id="historical-journey"><summary>Historical teaching events · all 34 channels</summary><p>Four saved events illustrate the signal-to-cone steps using their original reconstruction.</p><div id="gegi-signal-journey"></div></details></section>',
            '<script type="application/json" id="gegi-journey-data">'+payload+'</script><script src="gegi_signal_journey.js"></script>',
            '<script>GeGISignalJourney.mount(document.getElementById("gegi-signal-journey"),JSON.parse(document.getElementById("gegi-journey-data").textContent),{scope:"student"});</script>']
    parts.append('<script>const s=document.getElementById("cone-energy");s.addEventListener("change",()=>{document.querySelectorAll(".cone-layer").forEach(p=>{p.hidden=p.id!==s.value;});});</script></body></html>')
    return ''.join(parts).encode('utf-8')


def _render(summary, imaging, control, figures, journey):
    if 'cone_plane_display' in summary:
        return _render_cone_page(summary,imaging,control,journey)
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
        '<nav class="local"><a href="#new-map">New pooled result</a>'+('<a href="#saved-evidence">Saved-data checks</a>' if summary.get('saved_recovery_evidence') else '')+'<a href="#control">Original 708 control</a><a href="#spectra">Spectra</a><a href="#journey">Signals to a cone</a><a href="#accounting">Accounting</a></nav>',
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
    htmlparts += ['</section>', _recovery_html(summary.get('saved_recovery_evidence')),
        '<section id="control"><p class="tag">Separate control · original reconstruction</p><h2>Original 708 groups with corrected finite-vertex imaging</h2><details><summary>Inspect the separate original-reconstruction control</summary>',
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


def export_saved(reconstruction, imaging, legacy_control, previous_public, output, *, root=ROOT, readout_checks=None, evaluation=None, recovery_evidence=None, replace_public_manifest_sha256=None, order_prior_population=None, map_records=None):
    output = Path(output).resolve(); root = Path(root).resolve()
    require(not output.exists(), 'Preserve existing publication; use a new explicit output')
    pins = _source_pins(root)
    replacement = PREVIOUS_MANIFEST if replace_public_manifest_sha256 is None else replace_public_manifest_sha256
    require(isinstance(replacement,str) and re.fullmatch(r'[0-9a-f]{64}',replacement), 'Invalid explicit public replacement hash')
    summary, image, control, previous, inputs, migration = _saved_inputs(reconstruction,imaging,legacy_control,previous_public,
        population=order_prior_population,map_records=map_records)
    selected = image['group_count']
    require((image.get('source_mass') is not None) == (selected > 0), 'Empty imaging selection must not have a source map')
    require(control.get('source_mass') is not None, 'Missing legacy control map')
    if evaluation is None and (_report_path(imaging).parent/'evaluation.json').is_file():
        evaluation=_report_path(imaging).parent/'evaluation.json'
    require(not selected or evaluation is not None, 'Selected conditional imaging requires the finished posthoc evaluation')
    accuracy=_evaluation_summary(evaluation,imaging,reconstruction,image) if evaluation is not None else None
    if accuracy is not None:
        inputs['posthoc_evaluation_sha256']=sha(evaluation)
    recovery, recovery_bindings = None, {}
    if recovery_evidence is not None:
        recovery, recovery_bindings = _recovery_summary(recovery_evidence,reconstruction,image,summary,inputs)
        inputs['saved_recovery_evidence_sha256'] = hashlib.sha256(encoded(recovery)).hexdigest()
    target = output/'public'; target.mkdir(parents=True)
    figures = []
    display = _cone_display(target,image,migration) if migration is not None else None
    if display is not None:
        figures.extend({'family':'new','layer':layer['label'],'file':layer['files']['conditional'],
            'groups':layer['groups']} for layer in display['layers'])
    for family, report, filename in (('new',image,'map-new-pooled.png'),('control',control,'map-legacy-control.png')):
        if family == 'new' and display is not None:
            continue
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
    if display is not None:
        public_summary['cone_plane_display']=display
    if recovery is not None:
        public_summary['saved_recovery_evidence']=recovery
    if readout_checks is not None:
        public_summary['readout_check']=_readout_summary(readout_checks)
        inputs['readout_check_sha256']=sha(readout_checks)
    journey = _journey(previous_public)
    bodies={'summary.json':encoded(public_summary),'imaging-summary.json':encoded({'new':_compact_imaging(image),'legacy_control':_compact_imaging(control)}),
        'index.html':_render(public_summary,image,control,figures,journey),
        'gegi_signal_journey.js':ordinary(root/SOURCE_FILES[1]).read_bytes()}
    if accuracy is not None:
        bodies['evaluation-summary.json']=encoded(accuracy)
    if display is not None:
        bodies['cone-display.json']=encoded(display)
    if recovery is not None:
        bodies['recovery-summary.json']=encoded(recovery)
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
    if migration is not None:
        require(sha(Path(order_prior_population)/'result.json')==inputs['order_prior_population_result_sha256']
                and sha(map_records)==inputs['selected_map_records_sha256'], 'Order-prior display inputs changed during export')
    require(all(sha(path)==digest for path,digest in recovery_bindings.items()), 'Recovery evidence changed during export')
    manifest={'kind':KIND,'status':'complete','route':ROUTE,'initial_records':1_000_000,
        'replaces_public_manifest_sha256':replacement,'input_sha256':inputs,
        'source_sha256':pins,'exporter_sha256':pins[SOURCE_FILES[0]],'pillow_version':PILLOW_VERSION,'numpy_version':np.__version__,
        'radiation_calls':0,'native_drift_calls':0,'field_solves':0,'electronics_replays':0,'reconstruction_calls':0,
        'artifact_scope':'Saved aggregate maps plus unchanged historical34channel teaching signals; no raw science or private slides.',
        'artifacts':{p.name:{'bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted(target.iterdir())}}
    (target/'publication.json').write_bytes(public(encoded(manifest)))
    validate_public(target,root=root)
    (output/'COMPLETE.json').write_bytes(encoded({'kind':KIND,'status':'complete','public_manifest_sha256':sha(target/'publication.json'),
                                                'input_sha256':inputs,'source_sha256':pins}))
    return manifest


def validate_public(directory, *, root=ROOT, allow_historical_sources=False):
    directory=Path(directory); manifest=read(directory/'publication.json')
    require(manifest.get('kind')==KIND and manifest.get('status')=='complete' and manifest.get('route')==ROUTE,
            'Incomplete or unsupported saved publication')
    require(manifest.get('initial_records')==1_000_000
            and isinstance(manifest.get('replaces_public_manifest_sha256'),str)
            and re.fullmatch(r'[0-9a-f]{64}',manifest['replaces_public_manifest_sha256'])
            and manifest['input_sha256'].get('previous_public_manifest_sha256')==PREVIOUS_MANIFEST,
            'Wrong campaign denominator or replacement binding')
    require(all(manifest.get(k)==0 for k in ('radiation_calls','native_drift_calls','field_solves','electronics_replays','reconstruction_calls')),
            'Publication must not execute simulation or analysis')
    pins=manifest['source_sha256']
    require(set(pins)==set(SOURCE_FILES) and all(isinstance(v,str) and re.fullmatch(r'[0-9a-f]{64}',v) for v in pins.values())
            and manifest['exporter_sha256']==pins[SOURCE_FILES[0]], 'Saved publication source provenance changed')
    # An installed predecessor keeps its original recorded source identity. New
    # exports and candidates always require the currently frozen implementation.
    if not allow_historical_sources:
        require(pins==_source_pins(root), 'Saved publication source pins changed')
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
    if 'saved_recovery_evidence' in summary:
        require('recovery-summary.json' in names and summary['saved_recovery_evidence']==read(directory/'recovery-summary.json')
                and sha(directory/'recovery-summary.json')==manifest['input_sha256']['saved_recovery_evidence_sha256'],
                'Published saved recovery evidence is missing or changed')
    if 'cone_plane_display' in summary:
        display=summary['cone_plane_display']
        require('cone-display.json' in names and display==read(directory/'cone-display.json')
                and all(manifest['input_sha256'].get(k)==v for k,v in display['input_sha256'].items())
                and display['layers'][0]['groups']==summary['selected_conditional_imaging_groups']==153
                and display['layers'][0]['candidates']==287
                and display['truth_or_source_markers'] is False, 'Cone display selection or input binding changed')
        require(all(file in names for layer in display['layers'] for file in layer['files'].values()),
                'Missing cone comparison figure')
    public((directory/'publication.json').read_bytes())
    return manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('reconstruction','imaging','legacy-control','previous-public','output'):
        parser.add_argument('--'+name,required=True)
    parser.add_argument('--readout-checks')
    parser.add_argument('--evaluation')
    parser.add_argument('--recovery-evidence', help='Finished saved-data recovery evidence directory; aggregate export only')
    parser.add_argument('--replace-public-manifest-sha256', help='Exact installed public manifest to replace; teaching inputs remain independently bound')
    parser.add_argument('--order-prior-population', help='Completed explicit prior-weight population derivative')
    parser.add_argument('--map-records', help='Exact hash-bound selected153group candidate records')
    args=parser.parse_args()
    export_saved(args.reconstruction,args.imaging,args.legacy_control,args.previous_public,args.output,readout_checks=args.readout_checks,evaluation=args.evaluation,recovery_evidence=args.recovery_evidence,replace_public_manifest_sha256=args.replace_public_manifest_sha256,order_prior_population=args.order_prior_population,map_records=args.map_records)
