"""Inventory original GeGI calibration evidence without running numerical work."""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import statistics

import scenario_workflow as W

ROOT = Path(__file__).resolve().parents[1]
SOURCE = '.local/gegi-10m/pixel-calibration'
OUTPUT = '.local/gegi-10m/signal-recovery-v1/calibration'
KIND = 'gegi_saved_calibration_inventory_v1'


def _binding(path, root):
    return {'ref': path.relative_to(root).as_posix(), 'sha256': W.sha(path),
            'bytes': path.stat().st_size}


def _files(path, root):
    """Inspect components before descending, including Windows junctions."""
    for child in sorted(path.iterdir()):
        child = W.safe_path(root, child.relative_to(root).as_posix())
        if child.is_dir():
            yield from _files(child, root)
        elif child.is_file():
            yield child


def inspect_checkpoint(record, identity_sha256, dt):
    W.require(record.get('kind') == 'gegi_independent_injection_checkpoint_v1' and
              record.get('identity_sha256') == identity_sha256,
              'Independent injection identity changed.')
    row = record['payload']
    W.require(W.digest(row) == record['payload_sha256'], 'Independent injection payload changed.')
    pair = row['contact_ids']
    W.require(len(pair) == 2 and 1 <= pair[0] <= 16 and 18 <= pair[1] <= 33,
              'Independent injection has unexpected contact identities.')
    channels = {}
    signals = row['signals']
    if signals is None:
        W.require(row['status'] in ('excluded_geometry', 'native_failed', 'unexpected_failure') and
                  row['valid'] is False, 'Missing signals need an explicit excluded/failed status.')
    else:
        W.require(set(signals) == {'X', 'Y'}, 'Unexpected independent injection waveform schema.')
        for face, cid in zip(('X', 'Y'), pair):
            signal = signals[face]
            W.require(set(signal) == {'time_ns', 'signed_induced_keV'}, 'Waveform schema changed.')
            t, q = signal['time_ns'], signal['signed_induced_keV']
            W.require(len(t) == len(q) >= 2 and all(type(v) in (int, float) and math.isfinite(v)
                      for values in (t, q) for v in values) and q[0] == 0 and
                      all(v == i * dt for i, v in enumerate(t)), 'Invalid signed native waveform.')
            channels[str(cid)] = len(t)
    seconds = row['execution_seconds']
    W.require(type(seconds) in (int, float) and math.isfinite(seconds) and seconds >= 0,
              'Invalid recorded injection runtime.')
    return {'payload_sha256': record['payload_sha256'], 'status': row['status'],
            'valid': row['valid'], 'position_mm': row['position_mm'], 'contact_ids': pair,
            'signal_samples_by_channel': channels, 'execution_seconds': seconds}


def _timing(values):
    return {'count': len(values), 'sum_seconds': sum(values),
            'min_seconds': min(values), 'median_seconds': statistics.median(values),
            'max_seconds': max(values)}


def inventory(root=ROOT):
    root = Path(root).absolute()
    bank = W.safe_path(root, SOURCE)
    identity = W.read(bank/'identity.json')
    identity_sha = W.sha(bank/'identity.json')
    run = W.read(bank/'run.json')
    W.require(run['status'] == 'completed' and run['identity_sha256'] == identity_sha,
              'Original independent calibration is incomplete or changed.')
    W.require([c['id'] for c in identity['channels']] == list(range(1, 35)),
              'Original 34-electrode metadata changed.')
    for ref, digest in run['artifacts'].items():
        W.require(W.sha(W.safe_path(bank, ref)) == digest, 'Original calibration artifact changed: '+ref)
    bindings, statuses, signal_counts, channel_counts = [], Counter(), Counter(), Counter()
    timing, schemas, endpoint_schemas, family = defaultdict(list), Counter(), Counter(), Counter()
    expected_refs = set()
    table = W.read(bank/'depth-calibration.json')
    diagnostics = W.read(bank/'depth-diagnostics.json')
    for pixel in table['pixels'].values():
        expected_refs.update(row['record_ref'] for row in pixel['rows'])
    expected_refs.update(row['record_ref'] for row in diagnostics['rows'])
    seen = set()
    for path in _files(bank, root):
        entry = _binding(path, root)
        relative = path.relative_to(bank).as_posix()
        if relative.startswith(('injections/', 'diagnostic-injections/')):
            record = W.read(path)
            entry.update(inspect_checkpoint(record, identity_sha, identity['numerics']['dt']))
            schemas[tuple(sorted(record['payload']))] += 1
            for endpoint in record['payload']['endpoints'] or []:
                W.require(type(endpoint['samples']) is int and len(endpoint['position_mm']) == 3,
                          'Endpoint sample count or final coordinate schema changed.')
                endpoint_schemas[tuple(sorted(endpoint))] += 1
            statuses[entry['status']] += 1
            signal_counts[len(entry['signal_samples_by_channel'])] += 1
            channel_counts.update(entry['signal_samples_by_channel'].keys())
            timing[entry['status']].append(entry['execution_seconds'])
            family[relative.split('/')[0]] += 1
            seen.add(relative)
        bindings.append(entry)
    W.require(seen == expected_refs, 'Original injection census differs from summary references.')
    W.require(len(seen) == run['new_injections'] + run['reused_injections'],
              'Original injection census differs from completed receipt.')
    # These exact producer bytes establish that unselected signals were never computed.
    source_refs = ('simulation/gegi_pixel_calibration.jl', 'simulation/gegi_response.jl',
                   'simulation/gegi_campaign_response.jl', 'tools/gegi_campaign_prepare.py',
                   'tools/gegi_campaign_response.py')
    source_evidence = []
    for ref in source_refs:
        path = W.safe_path(root, ref)
        entry = _binding(path, root)
        original = identity['source_sha256'].get(path.name)
        if original:
            entry['original_identity_sha256'] = original
            entry['matches_original_identity'] = original == entry['sha256']
        bindings.append(entry)
        source_evidence.append(entry)
    W.require(all(item.get('matches_original_identity') is True for item in source_evidence[:2]),
              'Calibration/native producer differs from original; inspect retained source first.')
    work = bank.parent
    auxiliary = [work/'preparation.json', work/'failure-protocol-v1/calibration-measurement.json']
    spool = work/'failure-protocol-v1/calibration-spool'
    spool_files = list(_files(spool, root))
    auxiliary += spool_files
    earlier = []
    for run_root in sorted((root/'.local/runs').glob('gegi-*')):
        path = W.safe_path(root, run_root.relative_to(root).as_posix()+'/response/depth-calibration.json')
        if path.is_file():
            old = W.read(path)
            W.require(old['kind'] == 'gegi_central_pixel_simulated_depth_v1' and
                      not any('signals' in row for row in old['rows']),
                      'Earlier central calibration has a different schema; inspect before concluding absence.')
            earlier.append({**_binding(path, root), 'rows': len(old['rows']),
                            'stored_waveform_channels': 0, 'schema': sorted(old['rows'][0])})
            auxiliary += [path, run_root/'response.log']
    for path in auxiliary:
        path = W.safe_path(root, path.relative_to(root).as_posix())
        bindings.append(_binding(path, root))
    prep = W.read(work/'preparation.json')
    usable = sum(n for c, n in signal_counts.items() if c)
    report = {'kind': KIND, 'status': 'complete_full34_responses_absent',
        'scope': 'Original independent calibration checkpoints, summaries, retained calibration spool/log, exact producer code and earlier central calibrations. No numerical work executed.',
        'identity_sha256': identity_sha, 'model_sha256': identity['model_sha256'],
        'field_cache': identity['field_cache'], 'environment': identity['environment'],
        'numerics': identity['numerics'], 'random_seed': identity['random_seed'],
        'injection_energy_keV': identity['injection_energy_keV'],
        'counts': {'injection_records': len(seen), 'families': dict(family), 'statuses': dict(statuses),
                   'records_by_stored_channel_count': {str(k): v for k, v in signal_counts.items()},
                   'full34_records': 0, 'stored_waveform_channels': sum(c*n for c,n in signal_counts.items()),
                   'missing_unselected_waveforms_for_nonexcluded_injections': usable*32,
                   'available_depth_pixels': run['available_pixels'], 'unavailable_depth_pixels': run['unavailable_pixels']},
        'channel_coverage': [{'id': c['id'], 'name': c['name'], 'guard': c['guard'],
                              'stored_traces': channel_counts[str(c['id'])]} for c in identity['channels']],
        'schemas': [{'payload_keys': list(keys), 'records': n} for keys,n in schemas.items()],
        'endpoint_schemas': [{'keys': list(keys), 'records': n} for keys,n in endpoint_schemas.items()],
        'saved_drift_trajectories': {'present': False,
            'basis': 'All checkpoint envelope/payload/endpoint schemas inspected; samples is a scalar count and position_mm is only the final3-vector. Original bank contains JSON only; no SSD.Event or time-coordinate path file. Calibration spool has only protocol/process/lock/log files.'},
        'waveform_schema': {'keys': ['time_ns', 'signed_induced_keV'], 'time_unit': 'ns',
                            'charge_unit': 'keV of induced ionization equivalent; signed',
                            'channels_per_record': 'X/Y map to the two contact_ids; metadata lists all34 but arrays do not.'},
        'source_evidence': source_evidence,
        'producer_trace': ['gegi_pixel_calibration.jl injection calls native_deposit with ids=(xid,yid).',
                           'gegi_response.jl native_deposit calls SSD.get_signal! only inside for id in ids.',
                           'The temporary SSD.Event and drift paths are not serialized by calibration; checkpoints save endpoints only.',
                           'Resident calibrate replies save paths/hashes/status only; the retained stderr log contains two field-load lines.'],
        'retained_calibration_spool': [_binding(p, root) for p in spool_files],
        'earlier_central_calibrations': earlier,
        'measured_existing_cost': {'per_status': {s: _timing(v) for s,v in timing.items()},
            'checkpoint_execution_seconds_sum': sum(sum(v) for v in timing.values()),
            'completed_call_elapsed_seconds': run['elapsed_seconds_this_call'],
            'pilot': prep['calibration_pilot'],
            'scope': 'Historical two-channel injection timing includes geometry checks/drift/get_signal and occasional compilation/GC. It does not measure34-channel cost; resume call excludes11 reused injections.'},
        'missing_inputs': [
            'For each independent injection position: signed native time/charge arrays for all34 electrodes, including both guards and noncollecting neighbor transients, bound to exact model/field/environment/numerics.',
            'Retained selected-pair arrays and carrier endpoints cannot determine the32 uncomputed electrode time histories; drift trajectories were not retained.',
            'Independent lateral/depth coverage and fixed held-out positions for neighbor-sharing/false-split and same-pixel limits; measured noise, crosstalk and instrument transfer data remain separate absent inputs.'],
        'bounded_proposal': {'status': 'owner_approval_required_not_started', 'new_transport': False,
            'new_field_solve': False, 'pilot_injections': 15, 'energy_keV': 500.0,
            'pixels': [[9,26],[1,26],[3,20]], 'depth_mm': [-4.5,-2.5,0.0,2.5,4.5],
            'channels_per_injection': 34, 'maximum_new_drift_calculations': 15,
            'inputs': 'Reuse exact frozen cache/model/environment and original drift settings; save to a new derivative root with input/source hashes, full signed arrays, endpoints and explicit failure/null status.',
            'acceptance': 'Preserve selected-pair parity at matching fixed coordinates; verify all34 identities, signs, time grids, endpoint/failure accounting. Measure startup and per-injection wall time and output bytes separately. This pilot is not imaging validation.',
            'cost_estimate_seconds': None,
            'cost_basis': 'Existing two-channel timings above are measured. Additional32 signal calculations/storage cost is unmeasured; no full34 duration extrapolation.',
            'stop_condition': 'Stop at15 attempted fixed injections and report measured results before expanding to the fixed175 diagnostic positions or256x11 pixel-centre grid.'}}
    return report, bindings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default=OUTPUT, help='Fresh output directory below project .local')
    args = parser.parse_args()
    out = W.safe_path(ROOT, args.output)
    W.require(out.is_relative_to(ROOT/'.local') and out != ROOT/'.local' and not (out/'inventory.json').exists(),
              'Inventory needs an unpublished derivative directory below project .local.')
    report, bindings = inventory()
    out.mkdir(parents=True, exist_ok=True)
    manifest = out/'inputs.jsonl'
    manifest_bytes = b''.join(W.encoded(item)+b'\n' for item in bindings)
    if manifest.exists():
        W.require(manifest.read_bytes() == manifest_bytes, 'Interrupted inventory input bindings changed.')
    else:
        with manifest.open('xb') as stream:
            stream.write(manifest_bytes)
    report['input_manifest'] = {**_binding(manifest, ROOT), 'entries': len(bindings)}
    report['tool'] = _binding(Path(__file__), ROOT)
    failed = list(out.glob('inventory.json.pending-*'))
    if failed:
        report['prior_failed_export'] = {'reason': 'Existing writer fresh=True hard-link publication refused by Google Drive with WinError5; original failed bytes retained.',
            'files': [_binding(p, ROOT) for p in failed],
            'source_bindings': [_binding(p, ROOT) for p in (out/'source-bindings').glob('*.py')]}
    # Exclusive creation retains no-overwrite behavior without hard links on Drive.
    with (out/'inventory.json').open('xb') as stream:
        stream.write(W.encoded(report)+b'\n')
    print(json.dumps({'status': report['status'], 'output': str(out/'inventory.json'),
                      'counts': report['counts']}))


if __name__ == '__main__':
    main()
