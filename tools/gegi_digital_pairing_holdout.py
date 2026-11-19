"""Evaluate frozen GeGI digital pairing on 16 separately selected saved mixtures."""

import argparse
from collections import Counter
import json
from pathlib import Path

import numpy as np

import gegi_digital_pairing_study as S


FROZEN = S.STUDY / 'two-site-pairing-study.json'
FROZEN_SHA = '61a09e18a72a33fdda849b208e6bc3e5587d3c8a5f0f789082dba60469e66ad5'
MATCHINGS = (((11, 24), (12, 26)), ((11, 26), (12, 24)))
MIN_DISTANCE_MM = 1e-5
# Same eight geometric targets for each true matching. Include separated,
# nearby and same-depth pairs, lateral signs and center/edge offsets.
TARGETS = (
    ((-.30, -.30, -3.75), (.30, .30, 3.75)),
    ((.30, -.30, 3.75), (-.30, .30, -3.75)),
    ((-.15, .30, -2.00), (.30, -.15, 2.00)),
    ((.15, -.30, 2.00), (-.30, .15, -2.00)),
    ((-.30, .15, -.75), (.15, -.30, .75)),
    ((.30, .15, .75), (-.15, -.30, -.75)),
    ((-.30, -.15, 0.), (.30, .15, 0.)),
    ((.15, .30, 3.00), (-.15, -.30, 3.00)),
)


def load_selection():
    inputs = S.Inputs()
    frozen = inputs.read(FROZEN, FROZEN_SHA)
    old_hashes = frozen['input_sha256']
    if (frozen['digital_profile_sha256'] != S.D.PROFILE_SHA256
            or frozen['digital_timing_sha256'] != S.D.TIMING_SHA256):
        raise ValueError('Digital readout differs from the frozen eight-mixture model')
    for source, digest in frozen['source_sha256'].items():
        data = (S.ROOT / source).read_bytes()
        if source == 'tools/gegi_imaging.py':
            # This frozen input digest was recorded from a CRLF working copy.
            data = data.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
        if S.hashlib.sha256(data).hexdigest() != digest:
            raise ValueError(f'Frozen source changed: {source}')

    def original(path):
        return inputs.read(path, old_hashes[path.relative_to(S.ROOT).as_posix()])

    lateral = original(S.LATERAL / 'COMPLETE.json')
    identity = original(S.LATERAL / 'identity.json')
    lateral_request = inputs.read(S.LATERAL / 'bound-request.json', lateral['request_sha256'])
    prior_points = {point['record_ref']: point for point in lateral_request['points']}
    region = original(S.CONTROL / 'COMPLETE.json')
    request = original(S.CONTROL / 'bound-request.json')
    if (region['request_sha256'] != old_hashes[(S.CONTROL / 'bound-request.json').relative_to(S.ROOT).as_posix()]
            or region['status'] != 'completed_fixed_interior_native_region_bank'
            or request['injection_energy_keV'] != 500.
            or any(request[k] != identity[k] for k in ('channels', 'field_cache', 'model_sha256'))):
        raise ValueError('Saved holdout geometries differ from the frozen model')
    region_points = {p['record_ref']: p for p in request['points']}
    control_refs = {ref for row in frozen['controls']['mixtures'] for ref in row['record_refs']}
    fixed_refs = {str((S.ROOT / ref).relative_to(S.LATERAL).as_posix())
                  for row in frozen['cases'] for ref in row['input_component_refs']}
    excluded_sets = {
        'training': [p['position_mm'] for p in lateral['training_records']],
        'threshold_control': [region_points[ref]['position_mm'] for ref in sorted(control_refs)],
        'fixed_eight': [prior_points[ref]['position_mm'] for ref in sorted(fixed_refs)],
    }
    if [len(points) for points in excluded_sets.values()] != [396, 80, 16]:
        raise ValueError('Excluded coordinate counts differ from the frozen study')
    excluded = np.array([p for points in excluded_sets.values() for p in points])

    nominal_channels = {c['id']: c for c in identity['channels']}
    centers = {cid: nominal_channels[cid]['strip_center_mm'] for cid in S.COLLECTORS}
    pitches = {cid: nominal_channels[cid+1]['strip_center_mm'] - centers[cid] for cid in centers}
    used_hashes = set(old_hashes.values())
    by_pixel = {pixel: {} for pixel in S.PIXELS}
    census = Counter()
    for item in region['points']:
        ref = item['record_ref']
        point = region_points[ref]
        pixel = tuple(point['contact_ids'])
        coords = np.array(point['position_mm'])
        if item['status'] != 'completed' or not item['valid']:
            census['invalid_or_incomplete'] += 1
        elif pixel not in by_pixel or point['expected_pixel_bindings'] != [list(pixel)]:
            census['unsupported_or_multiple_pixels'] += 1
        else:
            dx, dy = [(v - centers[cid]) / pitches[cid] for v, cid in zip(coords, pixel)]
            normalized = np.array([dx, dy, coords[2]])
            if np.any(np.abs(normalized) > [.4, .4, 5.]):
                census['outside_frozen_calibration_volume'] += 1
            elif ref in control_refs or item['record_sha256'] in used_hashes:
                census['prior_record_identity'] += 1
            elif np.any(np.linalg.norm(excluded - coords, axis=1) <= MIN_DISTANCE_MM):
                census['prior_physical_coordinate'] += 1
            elif item['reused_source']:
                census['imported_record'] += 1
            else:
                by_pixel[pixel][ref] = (normalized, coords, item)
                census['eligible'] += 1

    eligible = {f'{p[0]}-{p[1]}': len(rows) for p, rows in by_pixel.items()}
    selected = []
    used = []
    if min(eligible.values()) >= len(TARGETS):
        for matching in MATCHINGS:
            for target in TARGETS:
                group = []
                for pixel, aim in zip(matching, target):
                    eligible_refs = (ref for ref, (_, xyz, _) in by_pixel[pixel].items()
                                     if all(np.linalg.norm(xyz - prior) > MIN_DISTANCE_MM for prior in used))
                    def distance(ref):
                        difference = (by_pixel[pixel][ref][0] - aim) / [.4, .4, 5.]
                        return float(difference @ difference), ref
                    ref = min(eligible_refs, key=distance, default=None)
                    if ref is None:
                        raise ValueError('Coordinate-distinct references exhausted during selection')
                    norm, xyz, item = by_pixel[pixel].pop(ref)
                    used.append(xyz)
                    group.append((norm, xyz, item))
                selected.append(group)
    metadata = {'region_records': len(region['points']), 'exclusion_order_counts': dict(census),
                'eligible_per_pixel': eligible, 'prior_coordinates_per_set': {k: len(v) for k, v in excluded_sets.items()},
                'selected_mixtures': len(selected), 'selected_components': 2 * len(selected),
                'position_independence_mm': MIN_DISTANCE_MM, 'target_design_offsets_pitch_fraction_and_z_mm': TARGETS,
                'rule': 'Before reading waveforms, choose nearest eligible unused point for each target in its designated pixel. Distance is Euclidean in units of 0.4 pitch, 0.4 pitch and 5 mm, with lexical reference ties. Exclude prior coordinates and records, reused records, incomplete records and points outside the frozen scan.'}
    return inputs, frozen, lateral, identity, region, metadata, selected


def run():
    inputs, frozen, lateral, identity, region, selection, selected = load_selection()
    channels = identity['channels']
    cases = []
    if selected:
        models = {p: {} for p in S.PIXELS}
        for item in lateral['training_records']:
            row = inputs.record(S.LATERAL, item, lateral['identity_sha256'])
            ref = (S.LATERAL / item['record_ref']).relative_to(S.ROOT).as_posix()
            if inputs.hashes[ref] != frozen['input_sha256'][ref]:
                raise ValueError('Training reference differs from frozen eight-mixture model')
            key = tuple(S.grid_coordinates(row['lateral_offset_pitch_fraction'], row['position_mm'][2]).astype(int))
            models[tuple(row['contact_ids'])][key] = S.analog_template(row, channels)
        models = {p: np.array([samples[tuple(idx)] for idx in S.GRID]).reshape(*S.SHAPE, -1)
                  for p, samples in models.items()}
        scales = frozen['controls']['group_rms_scales']
        limits = frozen['controls']['maximum_control_score']
        for index, group in enumerate(selected):
            components = [inputs.record(S.CONTROL, item, region['request_sha256']) for _, _, item in group]
            dig, observation = S.digital_mix(components, channels, (.5, .5))
            candidates = S.P.two_site_pairings(dig, channels)
            if candidates['compatible_pairing_count'] != 2:
                raise ValueError('A selected holdout mixture lacks two energy-compatible assignments')
            hypotheses = []
            for candidate in candidates['pairings']:
                pixels = tuple((site['x_contact_id'], site['y_contact_id']) for site in candidate['sites'])
                energies = [site['energy_keV'] for site in candidate['sites']]
                fits = S.fit(observation, models, pixels, energies, scales)
                hypotheses.append({'pixels': pixels, 'score': {mode: f['score'] for mode, f in fits.items()},
                                   'optimizer_status': {mode: f['best_optimizer_status'] for mode, f in fits.items()}})

            # Actual verified endpoint identities are attached after both fits.
            truth = sorted(tuple(row['contact_ids']) for row in components)
            correct = next(i for i, h in enumerate(hypotheses) if list(h['pixels']) == truth)
            comparison = {}
            for mode in S.MODES:
                a, b = [hypotheses[i]['score'][mode] for i in (correct, 1-correct)]
                outcome = ('both' if b <= limits[mode] else 'true_only') if a <= limits[mode] else (
                    'wrong_only' if b <= limits[mode] else 'neither')
                ranking = 'tie' if abs(b-a) < 1e-7 else ('true' if b > a else 'wrong')
                comparison[mode] = {'raw_preference': ranking, 'control_scale_outcome': outcome,
                                    'wrong_minus_true_score': b-a}
            cases.append({'mixture_index': index, 'true_hypothesis_index': correct,
                          'components': [{'record_ref': item['record_ref'], 'sha256': item['record_sha256'],
                                          'position_mm': xyz.tolist(), 'offsets_pitch_fraction': norm[:2].tolist()}
                                         for norm, xyz, item in group],
                          'hypotheses': hypotheses, 'comparison': comparison, 'pairing_decision': 'unresolved'})

    summary = {}
    for mode in S.MODES:
        summary[mode] = {}
        for field, labels in (('raw_preference', ('true', 'wrong', 'tie')),
                              ('control_scale_outcome', ('true_only', 'wrong_only', 'both', 'neither'))):
            counts = Counter(row['comparison'][mode][field] for row in cases)
            summary[mode][field] = {label: counts[label] for label in labels}
    return {'kind': 'gegi_saved_digital_pairing_holdout_v1',
            'status': 'completed' if cases else 'insufficient_independent_points', 'selection': selection,
            'counts': {'cases': len(cases), 'energy_ambiguous_cases': len(cases), 'unresolved_cases': len(cases),
                       'new_physics_calls': 0},
            'frozen_study_sha256': FROZEN_SHA, 'fixed_control_scales': frozen['controls']['group_rms_scales'],
            'fixed_control_limits': frozen['controls']['maximum_control_score'],
            'summary': summary, 'cases': cases,
            'parent_selection_sha256': {path: digest for path, digest in inputs.hashes.items()
                                        if path.endswith(('COMPLETE.json', 'bound-request.json', 'identity.json'))},
            'source_sha256': S.hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'scope': 'Separate saved coordinates and native records, selected by geometry in the same four-pixel bank. Same simulation, electronics, prompt equal-energy assumptions and frozen search. The region bank targeted this four-pixel footprint and is not an independent detector, physics model, or experimental acquisition.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    result = run()
    with args.output.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({k: result[k] for k in ('status', 'counts', 'summary')}, indent=2))
