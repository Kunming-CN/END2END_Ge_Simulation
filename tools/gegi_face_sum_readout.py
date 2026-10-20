"""Diagnostic synthetic face-sum readout from saved34-channel waveforms.

Every signed, fixed-wiring waveform on each face, including the guard, is summed
before the existing linear circuit and fixed500keV gain/peak ADC. This requires
waveform access and is not equivalent to the original per-channel peak-ADC
hardware output. Original readout and production sources remain unchanged.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import gegi_imaging as I
import gegi_readout_checks as C
import gegi_recovery_validation as V
import gegi_signal_reconstruction as R
from gegi_saved_reconstruction import sealed_chunks

ROOT = Path(__file__).resolve().parents[1]
DEFINITION = {
    'kind': 'synthetic_all17_channel_face_sum_before_linear_electronics_v1',
    'channels': 'All17channels per face, including guards; no acceptance, terminal amplitude, truth or source selection.',
    'wiring': 'Original fixed X=+1,Y=-1; sum signed charge before linear electronics.',
    'electronics': 'Unchanged saved matched pole-zero circuit, original window, fixed500keV injection gain and floor peak ADC with midpoint energy.',
    'validity': 'Both face positive peaks must pass original threshold, saturation and end-window rules; no retuned threshold.',
    'group_energy': 'Mean of the two accepted face ADC energies; opposite faces are never added.',
    'face_screen': 'Diagnostic existing max(2keV,2%of larger face) compatibility screen; does not change energy acceptance.',
    'hardware_scope': 'Synthetic scheme requiring waveform access; cannot be recovered from independent per-channel peak ADC codes alone.',
    'truth': 'Posthoc evaluation only; never reconstruction input, gain, channel selection or threshold.',
}
SOURCES = ('tools/gegi_face_sum_readout.py', 'tools/gegi_readout_checks.py',
           'tools/gegi_signal_reconstruction.py', 'tools/gegi_recovery_validation.py', 'tools/gegi_imaging.py')


def pins():
    return {ref: V.sha(ROOT/ref) for ref in SOURCES}


def face_sum_observables(observed, recipe, horizon_ns=None):
    """Signals plus the original electronics settings only; no event truth."""
    out = {'status': 'native_response_incomplete', 'accepted': False, 'energy_keV': None,
           'faces': None, 'native_terminal_mean_keV': None, 'face_difference_keV': None,
           'face_compatible': None}
    if observed['status'] != 'completed' or observed['channels'] is None or observed['native'] is None:
        return out
    if recipe['readout_config']['calibration_energy_keV'] != 500 or recipe['electronics_calibration']['energy_keV'] != 500:
        raise ValueError('Fixed original500keV gain changed')
    if recipe['readout_config']['peak_policy'] != 'signed_input_positive_peak':
        raise ValueError('Original signed positive-peak policy changed')
    channel_map = {c['contact_id']: c for c in observed['channels']}
    if len(observed['channels']) != 34 or set(channel_map) != set(range(1, 35)) or set(observed['native']) != set(range(1, 35)):
        raise ValueError('Complete native response requires all34channels')
    faces = {}
    for name, low, high, wiring in (('X', 1, 17, 1), ('Y', 18, 34, -1)):
        reference = None; summed = None
        for cid in range(low, high+1):
            c = channel_map[cid]
            if c['wiring_factor'] != wiring:
                raise ValueError('Fixed family wiring changed')
            t, q = R._wave(observed['native'][cid], wiring)
            if reference is None:
                reference = t; summed = np.zeros_like(q)
            elif not np.array_equal(reference, t):
                raise ValueError('Face waveform grids differ')
            summed += q
        response = C.matched_response(reference, summed, recipe, horizon_ns)
        config = recipe['readout_config']; peak = response['peak_V']
        at_end = response['peak_time_ns'] == (response['sample_count']-1)*recipe['electronics_calibration']['time_step_ns']
        reason = ('saturated' if peak >= config['adc_full_scale_V'] else 'peak_at_window_end' if at_end else
                  'below_threshold' if peak < config['threshold_V'] else None)
        faces[name] = {**response, 'accepted': reason is None, 'rejection_reason': reason,
                       'energy_keV': response['adc_midpoint_energy_keV'] if reason is None else None,
                       'native_terminal_keV': float(summed[-1]),
                       'charge_clipped_at_window': horizon_ns is not None and reference[-1] >= horizon_ns}
    accepted = all(f['accepted'] for f in faces.values())
    out.update(status='completed', accepted=accepted, faces=faces,
               native_terminal_mean_keV=sum(f['native_terminal_keV'] for f in faces.values())/2)
    if accepted:
        ex, ey = (faces[f]['energy_keV'] for f in ('X', 'Y'))
        out.update(energy_keV=(ex+ey)/2, face_difference_keV=ex-ey,
                   face_compatible=abs(ex-ey) <= max(I.PAIR_ABS_KEV, I.PAIR_REL*max(ex, ey)))
    return out


def summarize(rows):
    counts = Counter(); values = {}; comparisons = Counter()
    keys = ('original_error_keV', 'synthetic_error_keV', 'native_terminal_error_keV',
            'original_minus_native_terminal_keV', 'synthetic_minus_native_terminal_keV',
            'original_face_difference_keV', 'synthetic_face_difference_keV',
            'synthetic_analog_minus_native_terminal_keV')
    for key in keys:
        valid = [r[key] for r in rows if r[key] is not None]
        values[key] = {'known': len(valid), 'unknown': len(rows)-len(valid),
                       'signed': V.describe(valid), 'absolute': V.describe([abs(v) for v in valid])}
    paired = [r for r in rows if r['original_error_keV'] is not None and r['synthetic_error_keV'] is not None]
    for r in rows:
        counts['groups'] += 1
        counts['native_failed'] += r['native_status'] == 'native_failed'
        counts['native_incomplete'] += r['native_status'] != 'completed'
        counts['original_valid'] += r['original_accepted']
        counts['synthetic_valid'] += r['synthetic_accepted']
        counts['synthetic_face_compatible'] += r['synthetic_face_compatible'] is True
    for r in paired:
        a, b = abs(r['original_error_keV']), abs(r['synthetic_error_keV'])
        comparisons['smaller_absolute_error'] += b < a-1e-9
        comparisons['larger_absolute_error'] += b > a+1e-9
        comparisons['equal_absolute_error'] += abs(b-a) <= 1e-9
    return {'counts': dict(counts), 'errors': values,
            'paired_original_and_synthetic_valid': {'groups': len(paired), **dict(comparisons),
                'original_abs_error_keV': V.describe([abs(r['original_error_keV']) for r in paired]),
                'synthetic_abs_error_keV': V.describe([abs(r['synthetic_error_keV']) for r in paired])}}


def evaluate_stage(campaign, validation, output, split):
    manifest = V.read(validation/'split-manifest.json'); V.check_disjoint(manifest['groups'])
    manifest_sha = V.sha(validation/'split-manifest.json'); frozen_sources = pins()
    if split == 'development':
        if output.exists():
            raise ValueError('Preserve existing diagnostic; development may run once')
        report = {'kind': 'gegi_frozen_synthetic_face_sum_diagnostic_v1', 'definition': DEFINITION,
                  'source_sha256': frozen_sources, 'split_manifest_sha256': manifest_sha,
                  'splits': {}, 'groups': [], 'new_physics_calls': 0, 'new_calibration_calls': 0,
                  'limitations': ['Stratified400group diagnostic sample, not efficiency or detector resolution.',
                    'Face summation removes strip positions and cannot recover interaction pairing or same-pixel multiplicity.',
                    'Native contact/weighting endpoint deficits remain upstream; no truth normalization is applied.',
                    'Original peak-ADC hardware outputs cannot implement this synthetic waveform sum retrospectively.']}
        # Persist the complete fixed definition before any truth evaluation.
        output.parent.mkdir(parents=True, exist_ok=True)
        V.write_new(output, {**report, 'status': 'definition_frozen_before_development_truth'})
    else:
        report = V.read(output)
        if (report['source_sha256'] != frozen_sources or report['definition'] != DEFINITION or
                report['split_manifest_sha256'] != manifest_sha or report['status'] != 'development_completed'):
            raise ValueError('Holdout requires the unchanged completed development definition')
    before = time.perf_counter(); _, chunks = sealed_chunks(campaign)
    chunk_map = {index: (seal, done) for index, seal, done in chunks}
    rows = []; original_bindings = {}
    for selected in manifest['groups']:
        if selected['split'] != split:
            continue
        index, pid, gid = selected['group_key']; seal, done = chunk_map[index]
        event, native, digest = R.read_saved_group(seal.parent/'events.sqlite', pid, gid)
        if digest != selected['metadata_sha256'] or event['campaign_initial_offset']+pid != selected['campaign_initial_id']:
            raise ValueError('Frozen original group identity changed')
        recipe = done['response']['readout_recipe']
        observed = R.observables(event, native, recipe['channels'])
        synthetic = face_sum_observables(observed, recipe, event['readout_horizon_ns'])
        # Only posthoc evaluation below sees deposition truth and original Erec.
        truth = sum(s['energy_keV'] for s in event['input_steps']); old = event['readout_summary']
        terminal = synthetic['native_terminal_mean_keV']; erec = synthetic['energy_keV']
        original = old['energy_keV'] if old['accepted'] else None
        analog = sum(f['analog_energy_keV'] for f in synthetic['faces'].values())/2 if synthetic['faces'] else None
        rows.append({'campaign_initial_id': selected['campaign_initial_id'], 'group_key': selected['group_key'],
            'metadata_sha256': digest, 'split': split, 'reason': selected['reason'], 'native_status': event['status'],
            'original_accepted': old['accepted'], 'synthetic_accepted': synthetic['accepted'],
            'synthetic_face_compatible': synthetic['face_compatible'], 'truth_deposition_keV': truth,
            'original_energy_keV': original, 'synthetic_energy_keV': erec,
            'original_error_keV': original-truth if original is not None else None,
            'synthetic_error_keV': erec-truth if erec is not None else None,
            'native_terminal_error_keV': terminal-truth if terminal is not None else None,
            'original_minus_native_terminal_keV': original-terminal if original is not None and terminal is not None else None,
            'synthetic_minus_native_terminal_keV': erec-terminal if erec is not None and terminal is not None else None,
            'original_face_difference_keV': old.get('face_energy_difference_keV') if old['accepted'] else None,
            'synthetic_face_difference_keV': synthetic['face_difference_keV'],
            'synthetic_analog_minus_native_terminal_keV': analog-terminal if analog is not None else None,
            'synthetic_rejection': {name: f['rejection_reason'] for name, f in synthetic['faces'].items()} if synthetic['faces'] else None})
        original_bindings[str(index)] = {'seal_sha256': V.sha(seal),
            'events_store_sha256_from_seal': done['artifacts']['events.sqlite']['sha256'],
            'readout_recipe_sha256': done['response']['readout_recipe_sha256']}
    if pins() != frozen_sources or V.sha(validation/'split-manifest.json') != manifest_sha:
        raise ValueError('Frozen implementation or split changed')
    report['splits'][split] = {'elapsed_seconds': time.perf_counter()-before, **summarize(rows),
        'by_reason': {reason: summarize([r for r in rows if r['reason'] == reason]) for reason in sorted({r['reason'] for r in rows})}}
    report['groups'].extend(rows); report.setdefault('original_bindings', {}).update(original_bindings)
    report['status'] = 'development_completed' if split == 'development' else 'development_and_holdout_completed'
    pending = output.with_suffix('.pending')
    pending.write_bytes(V.encoded(report)); pending.replace(output)
    return report['splits'][split]


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('split', choices=('development', 'holdout'))
    parser.add_argument('--campaign', type=Path, required=True)
    parser.add_argument('--validation', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = evaluate_stage(args.campaign, args.validation, args.output, args.split)
    print(json.dumps({'split': args.split, 'elapsed_seconds': result['elapsed_seconds'], 'counts': result['counts']}, indent=2))
