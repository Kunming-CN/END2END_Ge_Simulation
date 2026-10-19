"""Posthoc, spectrum-only source compatibility and saved-map range assessment.

Consumes checked saved analysis; never runs transport, drift or reconstruction.
The classifier takes only a histogram, never source labels or truth positions.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path

KIND = 'gegi_source_inference_v1'
LINES = (661.657, 1173.228, 1332.492)
REFERENCES = [
    {'id': 'lnhb_cs137', 'title': 'LNE-LNHB Table de Radionucleides: Cs-137, section 5.2 Gamma Emissions',
     'url': 'https://www.lnhb.fr/nuclides/Cs-137_tables.pdf', 'page': 4,
     'evaluation': 'S. Leblond, 02/12/2021 - 18/07/2023', 'accessed': '2026-10-19',
     'photon_energy_keV': [661.655], 'standard_uncertainty_keV': [.003],
     'note': 'The frozen campaign uses the 661.657-keV level/transition anchor; the 0.002-keV recoil difference is far below its 2-keV bins. No frozen value is changed.'},
    {'id': 'lnhb_co60', 'title': 'LNE-LNHB Table de Radionucleides: Co-60, section 5.2 Gamma Emissions',
     'url': 'https://www.lnhb.fr/nuclides/Co-60_tables.pdf', 'page': 4,
     'evaluation': 'R. G. Helmer, 03/02/1998 - 1/3/2010', 'accessed': '2026-10-19',
     'photon_energy_keV': [1173.228, 1332.492], 'standard_uncertainty_keV': [.003, .004]}]


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)+'\n').encode('utf-8')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def policy():
    return {'scope': 'Posthoc compatibility screening of three specified gamma lines; not an unrestricted isotope identification or calibrated discovery test.',
        'classifier_inputs': ['spectrum.edges_keV', 'spectrum.counts'],
        'signal_half_width_keV': 6., 'sideband_inner_offset_keV': 12., 'sideband_outer_offset_keV': 30.,
        'maximum_peak_bin_offset_keV': 4., 'spectrum_familywise_screen_alpha': .01,
        'single_comparison_alpha': .01/6,
        'selection': 'Whole bins selected by their centers. Both left and right sideband comparisons must pass; no rebinning, gain fitting or energy shift.',
        'continuum': 'Report the larger sideband count density scaled to the signal width. Require an excess over each side separately to avoid a one-sided continuum edge masquerading as a line.',
        'screen_model': 'For each sideband, independent equal-rate Poisson signal/side counts imply a conditional Binomial(N, signal_width/(signal_width+side_width)) upper tail. Six comparisons cover three lines and two sidebands.',
        'statistics_limit': 'Pulse groups from one initial decay may be correlated. Local continuum may be curved or contain other lines. These count-model probabilities are screening diagnostics, not calibrated physical discovery probabilities or isotope posterior probabilities.',
        'range_rule': 'Direction has no radial coordinate; the finite plane fixes z rather than fitting it. No source range is identified by these saved maps.'}


def log_binomial_upper_tail(k, n, p):
    """Natural log of P[X >= k], computed without tiny-probability underflow."""
    require(type(n) is int and type(k) is int and 0 <= k <= n and 0 < p < 1, 'Invalid binomial arguments')
    if k == 0:
        return 0.
    logs = [math.lgamma(n+1)-math.lgamma(i+1)-math.lgamma(n-i+1)+i*math.log(p)+(n-i)*math.log1p(-p)
            for i in range(k, n+1)]
    maximum = max(logs)
    return min(0., maximum+math.log(math.fsum(math.exp(v-maximum) for v in logs)))


def checked_histogram(spectrum):
    edges, counts = spectrum.get('edges_keV'), spectrum.get('counts')
    require(type(edges) is list and type(counts) is list and len(edges) == len(counts)+1 and len(counts) > 0,
            'Histogram edges/counts differ')
    require(all(type(x) in (int, float) and math.isfinite(x) for x in edges)
            and all(type(n) is int and n >= 0 for n in counts), 'Invalid histogram values')
    widths = [b-a for a, b in zip(edges, edges[1:])]
    require(all(w > 0 and math.isclose(w, widths[0], rel_tol=0, abs_tol=1e-9) for w in widths),
            'This bounded diagnostic requires uniform positive-width bins')
    require(widths[0] <= 2., 'Bins are too broad for this diagnostic policy')
    return edges, counts, [(a+b)/2 for a, b in zip(edges, edges[1:])], widths[0]


def line_evidence(spectrum, energy):
    edges, counts, centers, width = checked_histogram(spectrum); rules = policy()
    require(edges[0] <= energy-30 and edges[-1] >= energy+30, 'Required line sidebands are outside the saved spectrum')
    selected = {
        'signal': [i for i, c in enumerate(centers) if abs(c-energy) <= rules['signal_half_width_keV']],
        'left': [i for i, c in enumerate(centers) if 12 <= energy-c <= 30],
        'right': [i for i, c in enumerate(centers) if 12 <= c-energy <= 30]}
    require(all(selected.values()), 'Empty signal/sideband bins')
    regions = {key: {'counts': sum(counts[i] for i in ids), 'width_keV': len(ids)*width,
                     'edges_keV': [edges[ids[0]], edges[ids[-1]+1]]} for key, ids in selected.items()}
    signal = regions['signal']; comparisons = {}
    for side in ('left', 'right'):
        band = regions[side]; probability = signal['width_keV']/(signal['width_keV']+band['width_keV'])
        logp = log_binomial_upper_tail(signal['counts'], signal['counts']+band['counts'], probability)
        comparisons[side] = {'log10_count_model_p': logp/math.log(10),
                             'passes_screen': logp <= math.log(rules['single_comparison_alpha'])}
    density = max(regions[s]['counts']/regions[s]['width_keV'] for s in ('left', 'right'))
    background = density*signal['width_keV']; excess = signal['counts']-background
    maximum = max(counts[i] for i in selected['signal'])
    peak_bins = [i for i in selected['signal'] if counts[i] == maximum] if maximum else []
    peak = min(peak_bins, key=lambda i: (abs(centers[i]-energy), i)) if peak_bins else None
    close = peak is not None and abs(centers[peak]-energy) <= rules['maximum_peak_bin_offset_keV']
    supported = excess > 0 and close and all(c['passes_screen'] for c in comparisons.values())
    weights = [(centers[i], max(0., counts[i]-density*width)) for i in selected['signal']]
    weight = math.fsum(w for _, w in weights)
    return {'line_energy_keV': energy, 'reference_photon_energy_keV': 661.655 if energy == 661.657 else energy,
        'supported': supported, 'status': 'local_peak_supported' if supported else 'not_supported',
        'bin_width_keV': width, 'peak_bin_center_keV': centers[peak] if peak is not None else None,
        'peak_bin_edges_keV': [edges[peak], edges[peak+1]] if peak is not None else None,
        'excess_weighted_centroid_keV': math.fsum(c*w for c, w in weights)/weight if weight else None,
        'centroid_scope': 'Descriptive binned centroid, not sub-bin calibration accuracy or measured resolution.',
        'signal_counts': signal['counts'], 'continuum_estimate_counts': background, 'net_excess_counts': excess,
        'regions': regions, 'sideband_comparisons': comparisons, 'peak_matches_line': close}


def infer_spectrum(spectrum):
    """Source labels, truth energy/positions and event identity never enter here."""
    lines = [line_evidence(spectrum, e) for e in LINES]
    single = lines[0]['supported']; doublet = lines[1]['supported'] and lines[2]['supported']
    candidates = []
    if single:
        candidates.append({'id': 'line_661_7_compatible', 'label': '661.7-keV-compatible component',
            'evidence_line_energies_keV': [661.657], 'status': 'ambiguous',
            'alternatives': ['Cs-137/Ba-137m-compatible radiation', 'Monoenergetic photons near 662 keV',
                             'Other source or mixture with a coincident line'],
            'reason': 'One gamma line cannot uniquely identify the parent isotope; source labels are not evidence.'})
    if doublet:
        candidates.append({'id': 'co60_compatible', 'label': 'Co-60-compatible doublet',
            'evidence_line_energies_keV': [1173.228, 1332.492], 'status': 'supported_compatibility',
            'alternatives': ['Other isotope/mixture with coincident lines'],
            'reason': 'Both independently tested gamma lines are supported; no full-library exclusion or calibrated isotope probability is claimed.'})
    if doublet and single:
        status, interpretation = 'mixed_line_compatibility', 'Co-60-compatible doublet plus an ambiguous 661.7-keV-compatible component.'
    elif doublet:
        status, interpretation = 'doublet_compatibility', 'The spectrum supports a Co-60-compatible doublet.'
    elif single:
        status, interpretation = 'single_line_ambiguous', 'A 661.7-keV-compatible line is supported; Cs-137 and monoenergetic 662-keV photons remain indistinguishable in this diagnostic.'
    else:
        status, interpretation = 'inconclusive', 'No complete signature in this limited three-line library is supported.'
    return {'status': status, 'interpretation': interpretation, 'candidate_components': candidates, 'line_evidence': lines,
        'limitations': ['No measured background or experimental detector response is supplied.',
            'The limited library is not an exhaustive radionuclide identification; absence of support does not prove absence.',
            'No efficiency-corrected line ratio, activity, coincidence signature or isotope probability is inferred.',
            'Spectral evidence alone does not associate a component with a particular map peak.',
            'Counts are fixed-gain accepted pulse groups; rejected and unknown-energy groups remain in the original census.']}


def distance_assessment(evaluations, plane):
    peaks = evaluations.get('plane', {}).get('peaks', [])
    boundary = any(p['row'] in (0, len(plane['y_mm'])-1) or p['column'] in (0, len(plane['x_mm'])-1) for p in peaks)
    return {'status': 'not_identified_by_saved_analysis', 'distance_mm': None,
        'assumed_plane_z_mm': plane['plane_z_mm'], 'plane_peak_boundary': boundary,
        'reason': 'The direction map has no radial parameter, and z was fixed for the finite-plane map rather than inferred. A plane-coordinate norm would be an imposed-geometry distance, not measured range.',
        'required_for_range_inference': ['A source-blind near-field model using the saved cone vertices across multiple candidate depths.',
            'A justified likelihood/response and rejection model with nuisance parameters and independent calibration checks.',
            'Finite-sample range uncertainty and demonstrated interior localization; multiple viewpoints or independent distance information may be necessary.'],
        'qualification': 'The raw cones can contain near-field information; this report does not prove fundamental impossibility or claim an unperformed 3D fit.'}


def pooled_spectrum(spectra):
    require(len(spectra) >= 1, 'Missing spectra')
    edges = spectra[0]['edges_keV']
    for spectrum in spectra:
        checked_histogram(spectrum)
        require(spectrum['edges_keV'] == edges, 'Cannot pool different energy bins')
    return {'edges_keV': edges, 'counts': [sum(s['counts'][i] for s in spectra) for i in range(len(edges)-1)]}


def build_report(analysis, plan_path, output):
    analysis, plan_path, output = Path(analysis).resolve(), Path(plan_path).resolve(), Path(output).absolute()
    require(not output.exists() and output != analysis and not output.is_relative_to(analysis),
            'Use a new derivative directory outside the immutable analysis bundle')
    manifest_path = analysis/'manifest.json'; manifest = read(manifest_path)
    require(manifest.get('kind') == 'gegi_campaign_analysis_v1' and manifest.get('status') == 'complete', 'Expected a complete saved analysis')
    inputs = {}
    for name in ('summary.json', 'maps.json', 'cones.jsonl'):
        path = analysis/name; binding = manifest['files'][name]
        require(path.is_file() and not path.is_symlink() and path.stat().st_size == binding['bytes'] and sha(path) == binding['sha256'],
                'Saved analysis hash mismatch: '+name)
        inputs[name] = dict(binding)
    summary, maps, plan = read(analysis/'summary.json'), read(analysis/'maps.json'), read(plan_path)
    plan_sha = sha(plan_path)
    require(plan_sha == manifest['plan_sha256'] == summary['plan_sha256'], 'Frozen plan binding differs')
    require(summary['criteria'] == maps['criteria'] == plan['analysis_criteria'], 'Saved analysis criteria differ')
    provenance = {'analysis_manifest_sha256': sha(manifest_path), 'summary_sha256': inputs['summary.json']['sha256'],
        'maps_sha256': inputs['maps.json']['sha256'], 'cones_sha256': inputs['cones.jsonl']['sha256'], 'plan_sha256': plan_sha,
        'validation_scope': 'Exact saved manifest, summary/maps/cone bytes and frozen plan; no raw/native replay and no changes to the existing analysis.'}
    report = {'kind': KIND, 'status': 'complete_posthoc_diagnostic', 'provenance': provenance,
        'source_sha256': {'tools/gegi_source_inference.py': sha(__file__)}, 'policy': policy(), 'references': REFERENCES,
        'group_label_policy': 'Dataset keys identify provenance only. infer_spectrum receives only the histogram and never labels, source configuration, truth energies or positions.',
        'groups': {}, 'mixtures': {}, 'radiation_calls': 0, 'native_calls': 0, 'reconstruction_calls': 0}
    for key, group in summary['groups'].items():
        report['groups'][key] = {'spectral_inference': infer_spectrum(group['spectrum']),
            'distance': distance_assessment(group['evaluations'], maps['groups'][key]['all']['plane']),
            'imaging_evaluation': group['evaluations'], 'census': group['counts'],
            'spectrum_scope': 'All saved fixed-gain accepted readout pulse groups; no truth or imaging selection.'}
    for key, mixture in summary['mixtures'].items():
        components = mixture['components']
        spectrum = pooled_spectrum([summary['groups'][name]['spectrum'] for name in components])
        report['mixtures'][key] = {'spectral_inference': infer_spectrum(spectrum),
            'distance': distance_assessment(mixture['evaluations'], maps['mixtures'][key]['all']['plane']),
            'imaging_evaluation': mixture['evaluations'], 'components': components,
            'spectrum_scope': 'Unweighted pooled counts from independent acquisitions; this spectral screen does not alter the separately frozen equal-initial-yield imaging mixture.',
            'initial_denominators': mixture['initial_denominators']}
    require(sha(manifest_path) == provenance['analysis_manifest_sha256'] and sha(plan_path) == plan_sha
            and all(sha(analysis/name) == binding['sha256'] for name, binding in inputs.items()), 'Saved inputs changed during diagnostic')
    require(sha(__file__) == report['source_sha256']['tools/gegi_source_inference.py'], 'Diagnostic source changed while processing')
    output.mkdir(parents=True)
    (output/'report.json').write_bytes(encoded(report))
    seal = {'kind': KIND, 'status': report['status'], 'provenance': provenance, 'source_sha256': report['source_sha256'],
            'files': {'report.json': {'sha256': sha(output/'report.json'), 'bytes': (output/'report.json').stat().st_size}},
            'radiation_calls': 0, 'native_calls': 0, 'reconstruction_calls': 0}
    (output/'manifest.json').write_bytes(encoded(seal))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--analysis', required=True, type=Path)
    parser.add_argument('--plan', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = build_report(args.analysis, args.plan, args.output)
    print(json.dumps({'status': result['status'], 'groups': {k: v['spectral_inference']['status'] for k, v in result['groups'].items()},
                      'distance_status': 'not_identified_by_saved_analysis'}, indent=2))
