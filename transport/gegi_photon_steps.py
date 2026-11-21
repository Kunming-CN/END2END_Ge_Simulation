"""Build and read an optional Geant4 photon-step sidecar in the locked remage runtime."""

import argparse
import csv
import hashlib
from itertools import groupby
import json
import math
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time


KIND = 'gegi_photon_step_sidecar_v1'
ARTIFACT = 'photon-steps.csv'
SOURCE = Path(__file__).with_name('gegi_photon_step_observer.cc')
POINT = ('kinetic_keV', 'x_mm', 'y_mm', 'z_mm', 'dx', 'dy', 'dz',
         'global_ns', 'local_ns', 'volume', 'copy', 'status')
HEADER = (
    'run_id', 'event_id', 'track_id', 'parent_track_id', 'step_number',
    'process', 'process_type', 'process_subtype', 'creator_process', 'track_status',
    'step_edep_keV', 'step_nonionizing_edep_keV',
    *(f'{prefix}_{column}' for prefix in ('pre', 'post') for column in POINT),
)


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def build_observer(directory):
    """Build into a new local directory, preserving the original RNG CLI and logs."""
    directory = Path(directory).resolve()
    prefix = Path(sys.prefix).resolve()
    compiler = shutil.which(os.environ.get('CXX', 'c++'))
    if compiler is None or not Path(compiler).resolve().is_relative_to(prefix):
        raise ValueError('Run the observer build with the existing locked transport compiler')
    flags = {name: shlex.split(subprocess.check_output(['geant4-config', name], text=True))
             for name in ('--cflags', '--libs')}
    directory.mkdir(parents=True, exist_ok=False)
    source = directory/'main.cc'
    shutil.copyfile(SOURCE, source)
    executable = directory/'gegi-photon-step-remage'
    command = [compiler, *flags['--cflags'], '-std=c++17', '-O2', '-I'+str(prefix/'include/remage'),
               str(source), '-L'+str(prefix/'lib'), '-Wl,-rpath,'+str(prefix/'lib'),
               '-lremage', *flags['--libs'], '-o', str(executable)]
    begun = time.perf_counter()
    receipt = dict(kind='gegi_photon_step_observer_build_v1', status='failed', command=command, source_sha256=sha256(source))
    try:
        with (directory/'build.log').open('x', encoding='utf-8') as log:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=False)
        receipt['returncode'] = result.returncode
        if result.returncode != 0:
            raise RuntimeError('Observer build failed. See build.log.')
        receipt.update(status='complete', executable_sha256=sha256(executable))
    finally:
        receipt['elapsed_seconds'] = time.perf_counter()-begun
        with (directory/'build.json').open('x', encoding='utf-8') as stream:
            json.dump(receipt, stream, indent=2, allow_nan=False)
            stream.write('\n')
    return executable


def observer_environment(output_path, *, local_event_ids=None):
    """Set observer output for one child, with an optional filter on local event IDs."""
    environment = dict(os.environ, GEGI_PHOTON_STEP_OUTPUT=str(output_path))
    environment.pop('GEGI_PHOTON_STEP_EVENTS', None)
    if local_event_ids is not None:
        ids = list(local_event_ids)
        if not ids or any(type(value) is not int or value < 0 for value in ids):
            raise ValueError('Select at least one nonnegative integer local event ID')
        environment['GEGI_PHOTON_STEP_EVENTS'] = ','.join(map(str, sorted(set(ids))))
    return environment


def _finite(raw):
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError('Photon-step values must be finite')
    return value


def _point(row, prefix):
    def get(name):
        return row[f'{prefix}_{name}']
    return dict(
        kinetic_keV=_finite(get('kinetic_keV')),
        position_mm=[_finite(get(f'{axis}_mm')) for axis in 'xyz'],
        direction=[_finite(get(f'd{axis}')) for axis in 'xyz'],
        global_time_ns=_finite(get('global_ns')), local_time_ns=_finite(get('local_ns')),
        physical_volume=get('volume') or None, copy_number=int(get('copy')) if get('volume') else None,
        step_status_code=int(get('status')),
    )


def photon_steps(path):
    """Yield original Geant4 photon steps with explicit units and local IDs."""
    with Path(path).open(encoding='utf-8', newline='') as stream:
        if stream.readline().rstrip('\r\n') != f'# {KIND}':
            raise ValueError('Expected a versioned GeGI photon-step sidecar')
        rows = csv.DictReader(stream, strict=True)
        if tuple(rows.fieldnames or ()) != HEADER:
            raise ValueError('Unexpected photon-step sidecar columns')
        for row in rows:
            if None in row or None in row.values():
                raise ValueError(f'Incomplete photon-step row near line {rows.line_num}')
            yield dict(
                **{key: int(row[key]) for key in ('run_id', 'event_id', 'track_id', 'parent_track_id', 'step_number', 'track_status')},
                process=row['process'] or None, process_type=int(row['process_type']) if row['process'] else None,
                process_subtype=int(row['process_subtype']) if row['process'] else None,
                creator_process=row['creator_process'] or None,
                step_edep_keV=_finite(row['step_edep_keV']), step_nonionizing_edep_keV=_finite(row['step_nonionizing_edep_keV']),
                pre=_point(row, 'pre'), post=_point(row, 'post'),
            )


def photon_events(path):
    """Group a serial source block's observations without loading the whole block."""
    previous = -1
    for event_id, group in groupby(photon_steps(path), key=lambda step: step['event_id']):
        steps = list(group)
        identities = {(step['track_id'], step['step_number']) for step in steps}
        if event_id <= previous or any(step['run_id'] != 0 for step in steps) or len(identities) != len(steps):
            raise ValueError('Expected ordered, unique photon steps from one serial Geant4 run')
        previous = event_id
        yield event_id, steps


def _same_number(score, observation):
    return math.isclose(score, observation, abs_tol=max(1e-10, math.ulp(score)), rel_tol=0.)


def _same_chord(score, observation):
    pre, post = observation['pre'], observation['post']
    return (observation['parent_track_id'] == score['parent_track_id']
            and pre['physical_volume'] == 'germanium'
            and _same_number(score['time_ns'], pre['global_time_ns'])
            and _same_number(score['edep_keV'], observation['step_edep_keV'])
            and all(_same_number(a, b) for key, point in (('pre_position_mm', pre), ('post_position_mm', post))
                    for a, b in zip(score[key], point['position_mm'], strict=True)))


def observe_ge_chords(truth, event_id, photon_steps_in_event):
    """Bind each original scored Ge gamma chord to one observed Geant4 step."""
    by_track = {}
    for step in photon_steps_in_event:
        if step['event_id'] != event_id:
            raise ValueError('Photon observation belongs to a different original transport event')
        by_track.setdefault(step['track_id'], []).append(step)
    joined = []
    used = set()
    for score in truth['ge_gamma_steps']:
        track = score['track_id']
        matches = [step for step in by_track.get(track, ()) if _same_chord(score, step)]
        if len(matches) != 1:
            raise ValueError(f"Original event {event_id} Ge gamma row {score['raw_row_index']} has no unique observed step")
        observation, = matches
        identity = track, observation['step_number']
        if identity in used:
            raise ValueError(f'Original event {event_id} maps distinct Ge gamma rows to the same observed step')
        used.add(identity)
        joined.append(dict(score, observed_transport_step=observation))
    return dict(truth, ge_gamma_steps=joined, photon_step_observation_status='observed_exact')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, required=True, metavar='NEW_DIRECTORY')
    print(build_observer(parser.parse_args().build))


if __name__ == '__main__':
    main()
