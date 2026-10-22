"""Prepare, compile, or run the one fixed native Compton diagnostic.

Use transport/workflow.sh (locked/no-install). Preparation never compiles or
samples. Each build attempt and the one sampling directory are preserved.
"""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import shlex
import statistics
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT/'.local/gegi-10m/signal-recovery-v1/validation/bound-electron-response/native-sampler'
AVAILABILITY = ROOT/'.local/gegi-10m/signal-recovery-v1/validation/geant4-doppler-data/availability.json'
EXPECTED_AVAILABILITY = '4998a6d481879da6ac585a63f7c18c819f84351bf7b30a4bf33cfaa8c33d087d'
SOURCES = ('tools/gegi_native_compton_sampler.cc', 'tools/gegi_native_compton_sampler.py')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False)+'\n')


def pins():
    return {p: sha(ROOT/p) for p in SOURCES}


def prepare():
    assert sha(AVAILABILITY) == EXPECTED_AVAILABILITY
    available = json.loads(AVAILABILITY.read_bytes())
    tools = available['build_entrypoint_read_only_check']
    compiler = tools['executables']['c++']['path']
    prefix = Path(available['runtime']['prefix'])
    assert Path(compiler).is_file() and Path(os.environ['G4LEDATA']).is_dir()
    flags = {q['argv'][-1]: shlex.split(q['stdout']) for q in tools['geant4_config_queries']
        if q['argv'][-1] in ('--cflags', '--libs')}
    OUTPUT.mkdir(parents=True, exist_ok=True)
    if (OUTPUT/'results').exists():
        raise FileExistsError('Sampling already exists: preserve it; no automatic resampling')
    data = {item['path']: item['sha256'] for item in available['data_files']}
    for path, digest in data.items():
        assert sha(path) == digest
    for folder in ('livermore', 'epics2017'):
        path = Path(os.environ['G4LEDATA'])/folder/'comp/ce-cs-32.dat'
        if path.is_file():
            data[str(path)] = sha(path)
    header_names = ('G4Version.hh', 'G4LivermoreComptonModel.hh',
        'G4KleinNishinaCompton.hh', 'G4VEmModel.hh', 'G4ParticleChangeForGamma.hh')
    request = {'kind': 'geant4_native_compton_request_v1', 'status': 'prepared_not_started',
        'model': 'gpt-6.1-sol', 'reasoning_effort': 'ultra', 'working_root': str(ROOT),
        'source_sha256': pins(), 'availability_sha256': EXPECTED_AVAILABILITY,
        'compiler': compiler, 'cflags': flags['--cflags'], 'libs': flags['--libs'],
        'build_argv': [compiler, *flags['--cflags'], '-O2', str(ROOT/SOURCES[0]),
            '-o', str(OUTPUT/'build-01/native-compton-sampler'), *flags['--libs']],
        'runtime_prefix': str(prefix), 'dataset': available['runtime']['dataset_name'],
        'dataset_version': available['runtime']['dataset_version'], 'data_sha256': data,
        'native_header_sha256': {n: sha(prefix/'include/Geant4'/n) for n in header_names},
        'native_process_library_sha256': sha(prefix/'lib/libG4processes.so'),
        'models': ['G4LivermoreComptonModel', 'G4KleinNishinaCompton'],
        'energies_keV': [662., 1173.228, 1332.492], 'samples_per_energy': [10000, 1000],
        'seeds': [[261022662, 261023173, 261023332], [261024662, 261025173, 261025332]],
        'maximum_samples': 33000, 'maximum_sampling_seconds': 120, 'threads': 1,
        'energy_closure_tolerance_keV': 1e-9, 'free_control_cos_tolerance': 1e-12,
        'initialization': 'G4_Ge single element; gamma/electron definitions; manual material-cuts couple index0; empty global geometry/PCT; Initialise and SetCurrentCouple; fresh InitializeForPostStep for each sample.',
        'atomic_deexcitation': False, 'binding_energy': 'Native local deposition; not equivalent to campaign atomic-relaxation initialization.',
        'mass_policy': 'Core inversion/control uses native electron_mass_c2. Project510.99895069keV and rounded511keV inversions are also retained independently.',
        'scope': 'Single native SampleSecondaries call, ideal local full absorption E1=E0-Eout/E2=Eout; no detector efficiency, transport, truth-assisted reconstruction or event replay.',
        'upstream_initialization_references': [
            'https://raw.githubusercontent.com/Geant4/geant4/v11.3.2/source/processes/electromagnetic/lowenergy/src/G4LivermoreComptonModel.cc',
            'https://raw.githubusercontent.com/Geant4/geant4/v11.3.2/source/processes/electromagnetic/standard/src/G4KleinNishinaCompton.cc']}
    write(OUTPUT/'request.json', request)
    return request


def request():
    value = json.loads((OUTPUT/'request.json').read_bytes())
    assert value['source_sha256'] == pins(), 'Sampler source changed after preparation'
    assert sha(AVAILABILITY) == value['availability_sha256']
    return value


def build(attempt):
    r = request()
    directory = OUTPUT/f'build-{attempt:02d}'
    directory.mkdir()
    executable = directory/'native-compton-sampler'
    argv = [r['compiler'], *r['cflags'], '-O2', str(ROOT/SOURCES[0]),
        '-o', str(executable), *r['libs']]
    started = time.perf_counter()
    with (directory/'stdout.log').open('w') as out, (directory/'stderr.log').open('w') as err:
        result = subprocess.run(argv, cwd=ROOT, stdout=out, stderr=err, timeout=120)
    receipt = {'status': 'compiled' if result.returncode == 0 else 'compile_failed',
        'argv': argv, 'source_sha256': pins(), 'returncode': result.returncode,
        'compile_seconds': time.perf_counter()-started,
        'executable_sha256': sha(executable) if executable.exists() else None}
    write(directory/'BUILD.json', receipt)
    if result.returncode:
        raise RuntimeError('Compile failed; preserved attempt. No samples executed.')
    return receipt


def describe(values):
    if not values:
        return None
    values = sorted(values)
    def percentile(q):
        index = q*(len(values)-1)
        low = int(index); high = min(low+1, len(values)-1)
        return values[low]+(values[high]-values[low])*(index-low)
    return {'count': len(values), 'min': values[0], 'median': statistics.median(values),
        'q68': percentile(.68), 'q95': percentile(.95),
        'max': values[-1], 'rms': math.sqrt(statistics.fmean(x*x for x in values))}


def summarize(path):
    groups = defaultdict(lambda: {'status': Counter(), 'cos': [], 'angle': [],
        'closure': [], 'cos_error': [], 'eout': [], 'below_native': 0,
        'above_native': 0, 'below_project': 0, 'below_511': 0, 'nonfinite_secondary_direction_samples': 0})
    with path.open(newline='') as stream:
        for row in csv.DictReader(stream):
            key = (int(row['model_id']), int(row['energy_index']))
            g = groups[key]; g['status'][row['status']] += 1
            g['closure'].append(abs(float(row['closure_keV'])))
            g['eout'].append(float(row['Eout_keV']))
            g['nonfinite_secondary_direction_samples'] += int(row['secondary_nonfinite_direction_count']) > 0
            if row['cos_free_native_mass']:
                c, true = float(row['cos_free_native_mass']), float(row['cos_true'])
                g['cos'].append(c); g['cos_error'].append(abs(c-true))
                g['below_native'] += c < -1; g['above_native'] += c > 1
                g['below_project'] += float(row['cos_free_project_mass']) < -1
                g['below_511'] += float(row['cos_free_511']) < -1
            if row['angle_error_rad']:
                g['angle'].append(abs(math.degrees(float(row['angle_error_rad']))))
    result = []
    for (model, energy), g in sorted(groups.items()):
        count = sum(g['status'].values()); below = g['below_native']
        fraction = (below+g['above_native'])/count
        result.append({'model_id': model, 'energy_index': energy,
            'sample_count': count, 'status': dict(g['status']),
            'absorbed_count': g['status'].get('absorbed', 0),
            'no_change_count': g['status'].get('unchanged', 0),
            'below_minus_one_native_mass': below, 'above_plus_one_native_mass': g['above_native'],
            'below_minus_one_project_mass': g['below_project'], 'below_minus_one_511_keV': g['below_511'],
            'out_of_range_fraction': fraction,
            'binomial_sampling_se': math.sqrt(fraction*(1-fraction)/count),
            'Eout_keV': describe(g['eout']), 'cos_free_native_mass': describe(g['cos']),
            'abs_angle_error_deg_when_inverse_valid': describe(g['angle']),
            'abs_cos_error': describe(g['cos_error']), 'abs_energy_closure_keV': describe(g['closure']),
            'nonfinite_secondary_direction_samples': g['nonfinite_secondary_direction_samples']})
    return result


def run(attempt):
    r = request(); directory = OUTPUT/f'build-{attempt:02d}'
    built = json.loads((directory/'BUILD.json').read_bytes()); executable = directory/'native-compton-sampler'
    assert built['status'] == 'compiled' and built['source_sha256'] == pins()
    assert sha(executable) == built['executable_sha256']
    for path, digest in r['data_sha256'].items():
        assert sha(path) == digest
    destination = OUTPUT/'results'; destination.mkdir()
    argv = [str(executable), str(destination)]; started = time.perf_counter()
    code, failure = None, None
    try:
        with (destination/'stdout.log').open('w') as out, (destination/'stderr.log').open('w') as err:
            code = subprocess.run(argv, cwd=ROOT, stdout=out, stderr=err, timeout=120).returncode
    except subprocess.TimeoutExpired:
        failure = '120second sampling deadline; process stopped, partial data preserved; no retry'
    elapsed = time.perf_counter()-started
    rows = summarize(destination/'samples.csv') if (destination/'samples.csv').exists() else []
    count_ok = len(rows) == 6 and all(g['sample_count'] == (10000 if g['model_id'] == 0 else 1000) for g in rows)
    energy_ok = bool(rows) and all(g['abs_energy_closure_keV']['max'] <= 1e-9 for g in rows)
    control_ok = bool(rows) and all(g['abs_cos_error']['max'] <= 1e-12 and
        g['below_minus_one_native_mass'] == g['above_plus_one_native_mass'] == 0
        for g in rows if g['model_id'] == 1)
    passed = code == 0 and count_ok and energy_ok and control_ok
    receipt = {'kind': 'geant4_native_compton_sampling_v1', 'status': 'complete' if passed else 'sampling_failed',
        'returncode': code, 'failure': failure, 'argv': argv, 'sampling_wall_seconds': elapsed,
        'compile_seconds': built['compile_seconds'], 'source_sha256': pins(),
        'request_sha256': sha(OUTPUT/'request.json'), 'build_sha256': sha(directory/'BUILD.json'),
        'checks': {'fixed_sample_counts': count_ok, 'energy_closure': energy_ok, 'free_electron_control': control_ok},
        'groups': rows, 'artifacts': {p.name: {'bytes': p.stat().st_size, 'sha256': sha(p)}
            for p in destination.iterdir() if p.is_file()}, 'automatic_sampling_retry': False,
        'scope': r['scope'], 'initialization_limit': r['binding_energy']}
    write(OUTPUT/('COMPLETE.json' if passed else 'FAILED.json'), receipt)
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'build', 'run'))
    parser.add_argument('--attempt', type=int, default=1)
    args = parser.parse_args()
    assert 1 <= args.attempt <= 9
    result = prepare() if args.action == 'prepare' else build(args.attempt) if args.action == 'build' else run(args.attempt)
    print(json.dumps(result, sort_keys=True, indent=2, allow_nan=False))
