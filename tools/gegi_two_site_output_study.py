"""Select saved two-site candidates and reuse frozen posthoc evaluations.

No optimizer, raw waveform, transport, drift or calibration calls occur here.
"""
from __future__ import annotations
import argparse
import gzip
import json
import math
from pathlib import Path
import time

import gegi_joint_imaging as G
import gegi_recovery_validation as V


ROOT = Path(__file__).resolve().parents[1]
SOURCES = ('tools/gegi_joint_imaging.py', 'tools/test_gegi_joint_imaging.py',
    'tools/gegi_recovery_validation.py', 'tools/gegi_two_site_output_study.py')
CENTERS = (661.657, 1173.228, 1332.492)


def write(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')


def compressed_rows(path, rows):
    with gzip.open(path, 'xb') as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()+b'\n')


def two_site_evaluation(row):
    candidates = [c for c in row['candidates'] if len(c['order']) == 2]
    indices = {c['hypothesis_index'] for c in candidates}
    return {**row, 'candidates': candidates,
        'hypotheses': [h for h in row['hypotheses'] if h['hypothesis_index'] in indices],
        'unsupported_hypothesis_mass': max(0., 1-math.fsum(c['prior_weight'] for c in candidates)),
        'original_conditional_candidate_count': len(row['candidates'])}


def run(reconstruction, validation, baseline_map, peak_diagnostic, output, max_seconds=120):
    started = time.perf_counter()
    if not 0 < max_seconds <= 120:
        raise ValueError('Saved-only analysis is bounded to at most120seconds')
    reconstruction, validation, baseline_map, peak_diagnostic, output = map(Path,
        (reconstruction, validation, baseline_map, peak_diagnostic, output))
    if output.exists():
        raise FileExistsError('Preserve previous evidence; use a new output directory')
    sources = {name: G._file_sha(ROOT/name) for name in SOURCES}
    inputs = {'reconstruction_complete': reconstruction/'COMPLETE.json',
        'evaluation_groups': validation/'evaluation-groups.json', 'evaluation_report': validation/'report.json',
        'split_manifest': validation/'split-manifest.json', 'baseline_map': baseline_map/'report.json',
        'baseline_map_events': baseline_map/'event_diagnostics.jsonl', 'peak_diagnostic': peak_diagnostic/'report.json'}
    pins = {name: G._file_sha(path) for name, path in inputs.items()}
    output.mkdir(parents=True)
    identity = {'kind': 'gegi_two_site_output_study_v1', 'source_sha256': sources, 'input_sha256': pins,
        'selection': 'After signal reconstruction, keep candidate.order length2; keep original priors without renormalization',
        'max_seconds': max_seconds, 'model': 'gpt-6.1-sol', 'reasoning_effort': 'ultra',
        'model_effort_evidence': 'Assigned worker session context; not external runtime attestation', 'working_root': str(ROOT),
        'new_calls': {'transport': 0, 'native_drift': 0, 'field_solve': 0, 'calibration': 0, 'waveform_fit': 0, 'map_optimizer': 0}}
    write(output/'identity.json', identity)

    def budget():
        if time.perf_counter()-started > max_seconds:
            raise TimeoutError('Saved-only analysis time limit reached; no automatic retry')

    records, accounting = G.read_reconstructed(reconstruction, two_site_only=True)
    budget()
    ledger = accounting.pop('two_site_selection')
    baseline, peak = V.read(inputs['baseline_map']), V.read(inputs['peak_diagnostic'])
    if (baseline['saved_signal_accounting']['input_sha256'] != accounting['input_sha256'] or
            peak['provenance']['saved_input_sha256'] != accounting['input_sha256'] or
            peak['provenance']['baseline_report_sha256'] != pins['baseline_map']):
        raise ValueError('Existing map/peak diagnostic refers to different saved input')
    old_events = [json.loads(line) for line in inputs['baseline_map_events'].read_text().splitlines()]
    old_keys = {(r['event_id'], r['pulse_group_id']): r['candidate_count'] for r in old_events}
    ledger_keys = {(r['campaign_initial_id'], r['pulse_group_id']): r['original_candidates']
                   for r in ledger if r['in_measured_energy_windows']}
    if (old_keys != ledger_keys or len(ledger_keys) != baseline['group_count'] or
            sum(ledger_keys.values()) != baseline['uncertainty']['candidate_count']):
        raise ValueError('Existing map selected identities/candidate counts differ')
    layers = {}
    for center in CENTERS:
        rows = [r for r in ledger if abs(r['energy_keV']-center) <= max(5., .02*center)]
        removed = sum(r['excluded_multisite_candidates'] for r in rows)
        layers[f'{center:g}_keV'] = {'original_groups': len(rows),
            'original_candidates': sum(r['original_candidates'] for r in rows),
            'retained_groups': sum(bool(r['retained_two_site_candidates']) for r in rows),
            'retained_candidates': sum(r['retained_two_site_candidates'] for r in rows),
            'excluded_candidates': removed, 'input_identical': removed == 0,
            'existing_map_result_reused': removed == 0,
            'existing_map_result_ref': str(inputs['baseline_map']) if removed == 0 else None}
        if layers[f'{center:g}_keV']['original_groups'] != baseline['spectral_layers'][f'{center:g}_keV']['group_count']:
            raise ValueError('Existing map spectral-layer group census differs')
    high = layers[f'{CENTERS[-1]:g}_keV']
    high_ids = sorted([[r['campaign_initial_id'], r['pulse_group_id']] for r in ledger
                      if abs(r['energy_keV']-CENTERS[-1]) <= max(5., .02*CENTERS[-1])])
    if (high['original_groups'] != peak['group_count'] or high['original_candidates'] != peak['candidate_count'] or
            high_ids != sorted(peak['selected_original_ids'])):
        raise ValueError('Existing1332keV diagnostic identity/candidate census differs')
    peak_reuse = {'input_identical': high['input_identical'], 'existing_result_reused': high['input_identical'],
        'existing_result_ref': str(inputs['peak_diagnostic']) if high['input_identical'] else None}
    budget()
    frozen, evaluated, old_report = map(V.read, (inputs['split_manifest'], inputs['evaluation_groups'], inputs['evaluation_report']))
    if (frozen['reconstruction_complete_sha256'] != pins['reconstruction_complete'] or
            evaluated['split_manifest_sha256'] != pins['split_manifest'] or
            old_report['evaluation_groups_sha256'] != pins['evaluation_groups']):
        raise ValueError('Existing frozen posthoc evaluation binding differs')
    V.check_disjoint(frozen['groups'])
    frozen_by_key = {tuple(r['group_key']): r for r in frozen['groups']}
    rows = evaluated['groups']
    if len(rows) != len(frozen_by_key):
        raise ValueError('Frozen evaluation group census differs')
    for row in rows:
        original = row['original_identity']
        key = original['chunk_index'], original['raw_primary_id'], original['pulse_group_id']
        expected = frozen_by_key[key]
        if (original['metadata_sha256'] != expected['metadata_sha256'] or row['split'] != expected['split'] or
                original['campaign_initial_id'] != expected['campaign_initial_id']):
            raise ValueError('Frozen evaluation original identity differs')
    selected_evaluation = [two_site_evaluation(row) for row in rows]
    metrics = {split: {'all_site_baseline': V.summarize([r for r in rows if r['split'] == split]),
        'two_site_output': V.summarize([r for r in selected_evaluation if r['split'] == split])}
        for split in ('development', 'holdout')}
    compressed_rows(output/'selected-records.jsonl.gz', records)
    compressed_rows(output/'selection-ledger.jsonl.gz', ledger)
    compressed_rows(output/'evaluation-groups.jsonl.gz', selected_evaluation)
    budget()
    if (sources != {name: G._file_sha(ROOT/name) for name in SOURCES} or
            pins != {name: G._file_sha(path) for name, path in inputs.items()}):
        raise ValueError('Frozen source or input changed during saved-data selection')
    result = {**identity, 'status': 'completed_saved_selection_and_posthoc_evaluation',
        'elapsed_seconds': time.perf_counter()-started, 'saved_signal_accounting': accounting,
        'current_map_input': {'original_groups': len(ledger_keys), 'original_candidates': sum(ledger_keys.values()),
            'retained_groups': len(records), 'retained_candidates': sum(len(r['candidates']) for r in records),
            'input_identical': all(x['input_identical'] for x in layers.values()),
            'existing_result_reused': all(x['input_identical'] for x in layers.values())},
        'spectral_layers': layers, '1332keV_peak_diagnostic': peak_reuse, 'frozen_posthoc_metrics': metrics,
        'scope': 'LegacyR3 sites are reconstructed charge cells, not necessarily distinct photon vertices or actual ImagerPro classes. Candidate/hypothesis metrics retain unknowns and original priors; no validated instrument event count is inferred. Frozen400evaluation reused without raw reads, refits or cut tuning.',
        'artifact_sha256': {name: G._file_sha(output/name) for name in
            ('selected-records.jsonl.gz', 'selection-ledger.jsonl.gz', 'evaluation-groups.jsonl.gz')}}
    write(output/'result.json', result)
    write(output/'COMPLETE.json', {'status': result['status'], 'identity_sha256': G._file_sha(output/'identity.json'),
        'result_sha256': G._file_sha(output/'result.json')})
    print(json.dumps({'elapsed_seconds': result['elapsed_seconds'], 'counts': accounting['counts'],
        'map': result['current_map_input'], 'layers': layers, 'result_sha256': G._file_sha(output/'result.json')}), flush=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('reconstruction', 'validation', 'baseline-map', 'peak-diagnostic', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--max-seconds', type=float, default=120)
    args = parser.parse_args()
    run(args.reconstruction, args.validation, args.baseline_map, args.peak_diagnostic, args.output, args.max_seconds)
