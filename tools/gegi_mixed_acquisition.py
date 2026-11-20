"""Bounded fresh mixed-source GeGI acquisition with candidate-only retention.

Both isotopes share one geometry, a predeclared parent clock and one readout.
This is the small startup acceptance route, not a long equilibrium campaign.
"""
from __future__ import annotations

import argparse
from collections import Counter
import copy
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import gegi_candidate_run as candidates
import gegi_campaign_response as response
import gegi_digital_readout as digital
import gegi_dual_source as dual
import gegi_event_store as native_store
import gegi_pulse_stream as pulse
import gegi_workflow as workflow
import scenario_workflow as W

ROOT = Path(__file__).resolve().parents[1]
MAX_PARENTS = 500
READOUT_TAIL_NS = 10_000.


def file_sha(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def transport_call(arguments, log):
    command = W.transport_prefix(ROOT) + ['python', '-B', './gegi_mixed_source.py', *arguments]
    command += W.transport_root_args(ROOT)
    with Path(log).open('ab') as target:
        result = subprocess.run(command, cwd=ROOT, stdout=target, stderr=subprocess.STDOUT,
                     shell=False, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    if result.returncode:
        raise RuntimeError('Fresh mixed-source transport failed; its original log and partial output are retained.')


def field_cache():
    """Reuse a model-bound cache from this workspace or a completed student run."""
    existing = workflow.field_cache(ROOT)
    if existing:
        return existing
    base = ROOT / '.local/runs'
    if base.is_dir():
        for directory in sorted(base.iterdir()):
            if directory.is_symlink() or not directory.is_dir():
                continue
            receipt = directory / 'response/fields.json'
            cache = directory / 'response/fields.jls'
            if receipt.is_file() and cache.is_file() and not cache.is_symlink():
                record = W.read(receipt)
                if record.get('model_sha256') == workflow.MODEL_SHA and record.get('sha256') == file_sha(cache):
                    return {'ref': cache.relative_to(ROOT).as_posix(), 'sha256': record['sha256'],
                            'model_sha256': workflow.MODEL_SHA, 'scope': 'Existing model-bound native field state.'}
    raise ValueError('Initialize the GeGI detector with an ordinary small GeGI run first; this acquisition reuses its saved fields.')


def native_request(output, count):
    cache = field_cache()
    refs = set(workflow.SOURCES) | {'simulation/gegi_campaign_response.jl',
            'simulation/gegi_pixel_calibration.jl', 'tools/gegi_campaign_response.py',
            'tools/gegi_event_store.py'}
    request = {'kind': 'gegi_campaign_response_request_v1',
        'selection': {'threads': 1, 'primary_count': count}, 'pulse_group_horizon_ns': 100000,
        'model_ref': 'models/GeGI_3D.yaml', 'model_sha256': workflow.MODEL_SHA,
        'profile_ref': 'simulation/native_readout_profile.json',
        'profile_sha256': file_sha(ROOT / 'simulation/native_readout_profile.json'), 'field_cache': cache,
        'numerics': {'drift_dt_ns': 1., 'drift_cap_ns': 1000., 'native_seed': 26101702,
                     'precision_bits': 64, 'diffusion': False, 'self_repulsion': False,
                     'field_policy': 'reuse-only', 'scope': 'Deterministic engineering response; no measured resolution claim.'},
        'source_sha256': {ref: file_sha(ROOT / ref) for ref in sorted(refs)}}
    path = output / 'native-request.json'
    candidates.write_new(path, request)
    return path


def absolute_event(event):
    """Use the explicit parent-relative transport contract without losing raw times."""
    row = copy.deepcopy(event)
    parent = row['absolute_parent_time_ns']
    row['primary_time_ns'] = parent
    for step in row['steps']:
        if step['absolute_time_ns'] != parent + step['time_ns']:
            raise ValueError('Mixed-source deposit absolute time does not close')
        step['parent_relative_time_ns'] = step['time_ns']
        step['time_ns'] = step['absolute_time_ns']
    for group in row['pulse_groups']:
        group['parent_relative_origin_time_ns'] = group['origin_time_ns']
        group['origin_time_ns'] += parent
    return row


def native_groups(event):
    """Adapt already verified transport groups without re-grouping on rounded clocks."""
    rows = {row['raw_row_index']: row for row in event['steps']}
    for original in event['pulse_groups']:
        steps = [rows[index] for index in original['row_indices']]
        yield {'event_id': event['event_id'], 'group_id': original['group_id'],
               'primary_time_ns': event['absolute_parent_time_ns'],
               'group_origin_time_ns': min(row['time_ns'] for row in steps),
               'horizon_ns': 100000, 'steps': steps, 'source_id': event['source_id'],
               'global_decay_id': event['event_id'], 'initial_primary_id': event['event_id'],
               'pulse_group': {'group_id': original['group_id'], 'row_indices': original['row_indices'],
                               'use': 'drift partition only; shared continuous electronics'},
               'parent_event_metadata': {key: event[key] for key in (
                   'acquisition_id', 'parent_decay_id', 'isotope', 'absolute_parent_time_ns',
                   'source_position_global_mm')}}


def _retire_success_scratch(output, paths):
    """Retire only this new run's declared, verified, regular temporary files."""
    output = output.resolve()
    records = []
    for path in paths:
        path = Path(path)
        if not path.exists():
            continue
        resolved = path.resolve()
        if not resolved.is_relative_to(output) or resolved == output or path.is_symlink():
            raise ValueError('Temporary retention path escaped its newly owned run')
        if any(p.is_symlink() for p in (path, *path.parents) if p.is_relative_to(output)):
            raise ValueError('Linked temporary data cannot be retired')
        records.append({'path': path.relative_to(output).as_posix(), 'bytes': path.stat().st_size,
                        'sha256': file_sha(path)})
    candidates.write_new(output / 'scratch-retirement.json', {
        'kind': 'candidate_run_owned_scratch_retirement_v1', 'scope': 'New run only; no old scientific data.',
        'candidate_verification': 'all candidate ADC and fast/slow records verified before retirement',
        'files': records, 'bytes': sum(row['bytes'] for row in records)})
    for record in records:
        path = output / record['path']
        if path.is_symlink() or file_sha(path) != record['sha256']:
            raise ValueError('Owned temporary file changed before retirement')
        path.unlink()
    return sum(row['bytes'] for row in records)


def run(output, primary_count=100, seed=20261120, activities_bq=(185000, 37000),
        positions_mm=((-40, 0, 40), (40, 0, 40)), on_progress=None, *, transport_directory=None,
        retain_validation_inputs=False):
    output = Path(output).resolve()
    if not output.is_relative_to((ROOT / '.local').resolve()):
        raise ValueError('Use a new output directory inside this workspace .local folder')
    if type(primary_count) is not int or not 1 <= primary_count <= MAX_PARENTS:
        raise ValueError('This fresh startup validation supports 1–500 initial parents; it is not long-run production.')
    if output.exists() and any(output.iterdir()):
        raise FileExistsError('Choose a new acquisition directory; existing data are preserved')
    output.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    def progress(stage):
        W.write(output / 'progress.json', {'status': 'running', 'stage': stage, 'started_seed': seed})
        if on_progress:
            on_progress(stage)
    try:
        # Source validation runs in its existing remage environment, never installs.
        config = {'kind': 'gegi_fresh_mixed_source_v1', 'acquisition_id': output.name,
            'primary_count': primary_count, 'seed': seed, 'clock_seed': seed,
            'initial_state': {'policy': 'new_parent_decays_empty_daughters_at_start',
                'acquisition_start_ns': 0, 'initial_daughter_populations': {},
                'pre_acquisition_history': 'none', 'scope': 'startup acceptance, not secular equilibrium'},
            'sources': [{'id': sid, 'activity_Bq': rate, 'position_global_mm': list(position)}
                        for sid, rate, position in zip((workflow.CS137, workflow.CO60),
                                                     activities_bq, positions_mm, strict=True)]}
        request = native_request(output, primary_count)
        candidates.write_new(output / 'source-config.json', config)
        scratch = output / 'transport'
        if transport_directory is None:
            progress('Generating fresh decays from both sources in one geometry')
            relative = lambda path: '../' + Path(path).relative_to(ROOT).as_posix()
            transport_call(['prepare', '--config', relative(output / 'source-config.json'),
                            '--output', relative(scratch)], output / 'transport.log')
            for stage in ('run', 'extract', 'verify'):
                transport_call([stage, '--directory', relative(scratch)], output / 'transport.log')
        else:
            # Validation can consume the already completed authorised source once.
            scratch = Path(transport_directory).resolve()
            if not scratch.is_relative_to((ROOT / '.local').resolve()):
                raise ValueError('The prepared transport must remain in this project')
        manifest_path = scratch / 'stream/manifest.json'
        manifest = W.read(manifest_path)
        if manifest['primary_count'] != primary_count or manifest['source_kind'] != config['kind']:
            raise ValueError('Prepared mixed transport differs from the requested initial census')
        if file_sha(manifest_path.parent / manifest['events_file']) != manifest['events_sha256']:
            raise ValueError('Prepared mixed-source deposit stream changed')
        source_config = manifest['source_contract']
        if any(source_config[key] != config[key] for key in ('primary_count', 'seed', 'clock_seed', 'initial_state', 'sources')):
            raise ValueError('Prepared mixed-source configuration differs from the requested settings')
        config = source_config
        duration = manifest['transport_duration_ns'] + READOUT_TAIL_NS
        progress('Drifting nonzero deposits through the shared detector')
        worker = response.ResidentWorker(request, output / 'native-spool')
        store = native_store.Store(output / 'native-scratch.sqlite', {'request_sha256': file_sha(request)}, create=True)
        components, identities, unavailable = [], [], []
        census = Counter(initial_parents=primary_count, nonzero_parents=manifest['nonzero_primaries'],
                         zero_deposit_parents=manifest['zero_deposit_primaries'])
        ledger = output / 'nonzero-identities.jsonl.gz'
        failures = output / 'native-failures.jsonl.gz'
        try:
            ready = worker.start()
            with (manifest_path.parent / manifest['events_file']).open(encoding='utf-8') as rows, \
                    gzip.open(ledger, 'xt', encoding='utf-8') as identities_out, \
                    gzip.open(failures, 'xt', encoding='utf-8') as failures_out:
                for line in rows:
                    original = json.loads(line)
                    event = absolute_event(original)
                    for group in native_groups(event):
                        onset = group['group_origin_time_ns']
                        last = max(row['time_ns'] for row in group['steps'])
                        meta = {'parent_decay_id': event['event_id'], 'source_id': event['source_id'],
                            'group_id': group['group_id'], 'first_ge_deposit_ns': onset,
                            'last_ge_deposit_ns': last, 'positive_ge_energy_keV': sum(s['energy_keV'] for s in group['steps']),
                            'raw_row_indices': [s['raw_row_index'] for s in group['steps']]}
                        census['deposit_groups'] += 1
                        if onset >= duration:
                            meta['status'] = 'daughter_deposits_after_acquisition'
                            census['delayed_groups_after_acquisition'] += 1
                        else:
                            saved = worker.process_group(group, store)
                            _, native = store.read(event['event_id'], group['group_id'], with_signals=True)
                            meta['status'] = saved['status']
                            identities.append(meta)
                            if digital.terminal_contacts_complete(saved):
                                components.append((pulse.prepare_native(native, ready['channels'], terminal_complete=True), onset, 1.))
                                census['complete_native_groups'] += 1
                            else:
                                unavailable.append(meta)
                                census['unavailable_native_groups'] += 1
                                failures_out.write(json.dumps({'identity': meta, 'event': saved, 'native': native}) + '\n')
                        identities_out.write(json.dumps(meta, separators=(',', ':')) + '\n')
        finally:
            store.close()
            worker.close()
        if census['zero_deposit_parents'] + census['nonzero_parents'] != primary_count:
            raise ValueError('Original parent denominator changed')
        progress('Processing continuous ADC and saving candidate fast/slow information')
        mask = dual._history_mask(unavailable, duration)
        identity = {'scope': 'fresh mixed-source startup acquisition', 'source_config': config,
                    'source_manifest_sha256': file_sha(manifest_path), 'native_request_sha256': file_sha(request),
                    'readout_tail_ns': READOUT_TAIL_NS,
                    'source_stop': 'Finite acceptance stops new parents after the recorded Nth arrival.',
                    'new_transport_calls': 1 if transport_directory is None else 0,
                    'new_drift_groups': census['complete_native_groups'] + census['unavailable_native_groups']}
        report = candidates.acquire(components, channels=ready['channels'], live_time_ns=duration,
            noise_seed=seed + 100000000, output=output, identity=identity, source_statistics=dict(census),
            excluded_intervals=mask, group_identities=identities)
        temporary = [output / 'native-scratch.sqlite']
        if transport_directory is None:
            temporary += [scratch / ref for ref in ('truth.lh5', 'primaries.lh5', 'parents.jsonl', 'stream/events.jsonl')]
        retired = 0 if retain_validation_inputs else _retire_success_scratch(output, temporary)
        W.write(output / 'progress.json', {'status': 'completed', 'stage': 'Completed candidate acquisition',
            'elapsed_seconds': time.perf_counter() - started, 'temporary_bytes_retired': retired,
            'retained_validation_inputs': retain_validation_inputs})
        return report
    except BaseException as error:
        W.write(output / 'progress.json', {'status': 'failed', 'error': str(error),
            'elapsed_seconds': time.perf_counter() - started, 'partial_data_retained': True})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--parents', type=int, default=100)
    parser.add_argument('--seed', type=int, default=20261120)
    parser.add_argument('--transport-directory', type=Path)
    parser.add_argument('--retain-validation-inputs', action='store_true')
    args = parser.parse_args()
    result = run(args.output, args.parents, args.seed, transport_directory=args.transport_directory,
                 retain_validation_inputs=args.retain_validation_inputs)
    print(json.dumps({'counts': result['counts'], 'storage_counts': result['storage_counts']}))


if __name__ == '__main__':
    main()
