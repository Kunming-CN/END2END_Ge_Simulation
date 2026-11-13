"""Exercise the packaged macOS Control, with one fixed 100-primary science run."""

import argparse
from contextlib import contextmanager
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import platform
import signal
import stat
import subprocess
import sys
import time
from urllib.parse import urlencode, urlsplit


NAME = 'macos-student-acceptance'
PRIMARY_COUNT = 100
RADIATION_SEED = 26092631
NATIVE_SEED = 2609261
CONTROL = '.local/local-control-v1'
TERMINAL = ('completed', 'completed_with_native_failures')


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify_package(student):
    metadata = read(student / 'PACKAGE.json')
    members = metadata['members']
    launchers = ('Control.command', 'Setup.command')
    require(metadata['kind'] == 'student_runtime_package_v1' and all(name in members for name in launchers),
            'Student package is missing its macOS launchers or member metadata')
    for name, stamp in members.items():
        path = student / name
        require(path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(student)
                and path.stat().st_size == stamp['packaged_bytes'] and sha(path) == stamp['packaged_sha256'],
                'Student package member changed after setup: ' + name)
    for name in launchers:
        require((student / name).stat().st_mode & stat.S_IXUSR,
                'Student launcher is not executable after extraction: ' + name)
    return len(members)


def until(probe, deadline, label):
    while time.monotonic() < deadline:
        value = probe()
        if value:
            return value
        time.sleep(0.2)
    raise TimeoutError('Timed out waiting for ' + label)


class Control:
    def __init__(self, receipt):
        url = urlsplit(receipt['url'])
        require(url.scheme == 'http' and url.hostname == '127.0.0.1' and url.port and url.fragment,
                'Control did not publish a protected loopback session')
        self.port = url.port
        self.origin = f'http://127.0.0.1:{self.port}'
        self.token = url.fragment

    def fetch(self, route, body=None, *, authenticated=True, status=200):
        headers = {'X-Control-Token': self.token} if authenticated else {}
        if body is not None:
            headers.update({'Origin': self.origin, 'Content-Type': 'application/json'})
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=130)
        try:
            connection.request('GET' if body is None else 'POST', route,
                               None if body is None else json.dumps(body), headers)
            response = connection.getresponse()
            result = response.read()
            if response.status != status:
                raise RuntimeError(f'{route} returned HTTP {response.status}: {result[:2000].decode(errors="replace")}')
            return result
        finally:
            connection.close()

    def api(self, endpoint, body=None, **query):
        route = '/api/workflow/' + endpoint
        return json.loads(self.fetch(route + ('?' + urlencode(query) if query else ''), body))


@contextmanager
def control_session(student, evidence):
    state = student / CONTROL / 'server.json'
    require(not state.exists(), 'Use an extracted student package without an active Control session')
    with (evidence / 'control.log').open('xb') as log:
        process = subprocess.Popen(['/bin/bash', './Control.command', '--no-browser'], cwd=student,
                                   stdout=log, stderr=subprocess.STDOUT, start_new_session=True)

        def session():
            require(process.poll() is None, 'Control closed before startup (see control.log)')
            try:
                return read(state)
            except (FileNotFoundError, json.JSONDecodeError):
                return None  # The server publishes this receipt once the socket is bound.

        try:
            info = until(session, time.monotonic() + 90, 'Control startup')
            require(os.getpgid(info['pid']) == process.pid, 'Control receipt came from a different process group')
            yield Control(info)
        finally:
            # Only the process group created above is signaled. This also closes its workers on timeout.
            try:
                os.killpg(process.pid, signal.SIGINT)
                process.wait(timeout=8)
            except ProcessLookupError:
                process.wait()
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()


def run_once(control, run, evidence, deadline):
    require(b'id="result"' in control.fetch('/', authenticated=False), 'Packaged Control page did not open')
    control.fetch('/api/workflow/state', authenticated=False, status=403)
    setup = control.api('setup')
    save(evidence / 'setup-readiness.json', setup)
    require(setup['ready_for_config_check'] and setup['angular_source_file_ready'], 'Student setup is incomplete')
    defaults = control.api('catalog')['electronics_defaults']
    # Same selection as the saved positive SAP22 100-primary student baseline, with a fresh run name.
    selection = {'name': NAME, 'cryostat': 'lbnl_modular_nominal_v1', 'detector': 'SAP22',
                 'source': 'cs137_point_decay_v1', 'pose': 'nominal', 'angle_deg': 30,
                 'primary_count': PRIMARY_COUNT, 'seed': RADIATION_SEED, 'threads': 1, 'electronics': defaults}
    checked = control.api('check-batches', {'request': {'kind': 'local_scenario_batch_request_v2',
                                                       'schema_version': 2, 'selection': selection}})
    token = checked.pop('check_id')
    save(evidence / 'checked-plan.json', checked)
    require(checked['execution_enabled'] and checked['resolved']['selection'] == selection
            and checked['science_calls'] == 0 and checked['resolved']['batching']['batch_count'] == 1,
            'Control changed the selected configuration or requested more than one batch')
    control.api('start', {'check_id': token})
    observed = None

    def job_when(predicate):
        nonlocal observed
        state = control.api('state')
        require(len(state['jobs']) == 1, 'Acceptance launched an unexpected number of runs')
        job = state['jobs'][0]
        require(job['name'] == NAME and job['configuration_sha256'] == checked['configuration_sha256'],
                'Control changed the owned run identity')
        progress = job.get('batch_progress', {})
        marker = (job['status'], progress.get('active_stage'))
        if marker != observed:
            print(f'Control status {marker[0]}, stage {marker[1]}', flush=True)
            save(evidence / 'last-control-state.json', state)
            observed = marker
        require(progress.get('status') != 'failed' and not job['error'],
                'Driver or stage failed (see the saved run and Control logs)')
        return job if predicate(job, state) else None

    # Wait for real committed work. Normally Stop lands after geometry; a fast geometry
    # stage may already have started native preparation, which can also be reused.
    def active_geometry(job, state):
        stage = job.get('batch_progress', {}).get('active_stage')
        require(job['status'] not in TERMINAL and stage in (None, 'geometry', 'native_preparation'),
                'Missed the pre-radiation Stop window')
        return job['status'] == 'running' and stage is not None

    until(lambda: job_when(active_geometry), deadline, 'a committed geometry or native preparation stage')
    control.api('stop', {'name': NAME})
    until(lambda: job_when(lambda job, state: job['status'] == 'stopped' and not state['busy']),
          deadline, 'sealed Stop boundary')
    stopped = read(run / 'run.json')
    require(stopped['resume_allowed'] is True and stopped['completed_primary_count'] == 0
            and 'geometry' in stopped['stages'] and not (run / 'batches').exists(),
            'Stop did not retain a pre-radiation geometry checkpoint')
    boundary = {stage: sha(run / 'receipts' / (stage + '.json')) for stage in stopped['stages']}
    save(evidence / 'stopped.json', stopped)
    control.api('resume', {'name': NAME})
    until(lambda: job_when(lambda job, state: job['status'] in TERMINAL and not state['busy']),
          deadline, 'verified terminal run')
    verified = control.api('verify', {'name': NAME})
    receipt = read(run / 'run.json')
    require(verified['status'] == receipt['status'] and receipt['status'] in TERMINAL
            and len(receipt['resumes']) == 1 and receipt['resumes'][0]['prior_status'] == 'stopped',
            'Run did not complete through the single owned Resume')
    for stage, digest in boundary.items():
        require(receipt['stages'][stage]['reuse'] == 'verified_sealed_stage'
                and sha(run / 'receipts' / (stage + '.json')) == digest,
                'Resume changed the sealed ' + stage + ' result')
    return selection, receipt, boundary


def verify_outputs(student, run, receipt, evidence):
    batch = run / 'batches/b0000000000'
    transport = batch / 'transport'
    # Production reader checks the LH5 scalar, all raw initial IDs and exact ledger values.
    # This is a read-only check and never calls remage to simulate again.
    verify = ['/bin/bash', './macos/workflow.sh', 'python', '-B', './batch_source.py', 'verify',
              '--stage', 'event_ledger', '--directory', '../' + batch.relative_to(student).as_posix(),
              '--project-root', str(student)]
    with (evidence / 'raw-ledger-verification.json').open('xb') as output, \
            (evidence / 'raw-ledger-verification.log').open('xb') as log:
        subprocess.run(verify, cwd=student / 'transport', stdout=output, stderr=log, check=True, timeout=150)
    ledger = read(transport / 'stream/manifest.json')
    require(ledger == read(evidence / 'raw-ledger-verification.json'), 'Raw ledger verification differs from the sealed ledger')
    radiation = read(transport / 'run.json')
    counts = receipt['counts']
    complete = read(run / 'COMPLETE.json')
    response = read(batch / 'response/run.json')
    prep = read(run / 'shared/native/preparation.json')
    require(complete['completed_batch_count'] == 1 and complete['completed_primary_count'] == PRIMARY_COUNT
            and counts == complete['counts'] == response['counts']
            and counts['initial_primaries'] == counts['initial_decays'] == PRIMARY_COUNT
            and counts['zero_deposit_primaries'] + counts['nonzero_primaries'] == PRIMARY_COUNT
            and counts['accepted'] + counts['rejected'] == counts['groups']
            and counts['rejected'] == counts['native_failed_groups'] + counts['readout_rejected'],
            'The completed census changed across transport, response or results')
    require(radiation['number_of_simulated_events'] == radiation['initial_ledger_count'] == PRIMARY_COUNT
            and radiation['batch']['radiation_seed'] == RADIATION_SEED
            and radiation['command'][:6] == ['remage', '--flat-output', '-t', '1', '--rand-seed', str(RADIATION_SEED)]
            and ledger['units'] == {'energy': 'keV', 'length': 'mm', 'time': 'ns'}
            and ledger['raw_track_energy_unit'] == 'MeV' and ledger['raw_position_unit'] == 'm',
            'Raw radiation count, seed, threading or declared units changed')
    macro = {line.strip() for line in (transport / 'run.mac').read_text().splitlines()}
    require({'/gps/particle ion', '/gps/ion 55 137', f'/run/beamOn {PRIMARY_COUNT}'} <= macro,
            'Radiation macro did not use the expected Cs137 ion or primary count')
    require(radiation['versions']['remage'] == '1.1.0' and radiation['versions']['geant4-config'] == '11.3.2'
            and response['environment']['julia_version'] == '1.13.0'
            and response['environment']['ssd_version'] == '0.11.8', 'Pinned simulation software versions changed')
    require(prep['field_solution_calls'] == prep['independent_calibration_calls'] == 1
            and response['field_solution_calls'] == response['independent_calibration_calls'] == 0
            and prep['state_sha256'] == response['state_sha256']
            and prep['calibration'] == response['calibration'] and response['calibration']['energy_keV'] == 500
            and response['seed_family'] == NATIVE_SEED and response['native_failure_policy'] == 'record'
            and response['units'] == {'charge': 'fC', 'current': 'nA', 'voltage': 'V', 'energy': 'keV', 'time': 'ns'},
            'The field state, independent calibration, native seed, failure policy or signal units changed')
    return ledger, counts, radiation['versions'], response['environment']


def verify_view(control, run, receipt, ledger, counts, evidence):
    config = receipt['configuration_sha256']
    spectrum = control.api('result-options', name=NAME)
    require(spectrum['configuration_sha256'] == config and spectrum['spectrum_file'] == 'results/histograms.json',
            'Control did not expose the verified spectrum')
    path = '/api/workflow-file?' + urlencode({'name': NAME, 'file': 'results/index.html'})
    control.fetch(path, authenticated=False, status=403)
    summary = control.fetch(path).decode('utf-8')
    require('SAP22' in summary and f'{PRIMARY_COUNT} initial primaries' in summary and '/api/workflow-file?' in summary,
            'Browser-facing verified result summary is missing the run or navigation')
    page = control.api('events', name=NAME, batch=0, offset=0, limit=PRIMARY_COUNT)
    save(evidence / 'viewer-events.json', page)
    require(page['configuration_sha256'] == config and page['batch_primary_count'] == PRIMARY_COUNT
            and page['efficiency_denominator'] == PRIMARY_COUNT and page['counts'] == counts
            and page['event_storage'] == ledger['event_storage'] and page['complete'] is True
            and len(page['records']) == page['stored_record_count'] == counts['nonzero_primaries'] > 0,
            'The viewer changed the initial denominator or nonzero event population')
    base = run / 'batches/b0000000000/transport/stream'
    source = [json.loads(line) for chunk in ledger['chunks']
              for line in (base / chunk['file']).read_text(encoding='utf-8').splitlines()]
    require([row['truth'] for row in page['records']] == source, 'The viewer lost original transport events')
    failed = []
    selected = None
    ids = []
    for row in page['records']:
        primary = row['global_initial_id']
        ids.append(primary)
        require(row['local_initial_id'] == row['truth']['event_id'] == row['primary']['event_id'] == primary
                and any(step['energy_keV'] > 0 for step in row['truth']['steps']),
                'The viewer changed event identity or displayed a zero-input event')
        for pulse in row['pulse_groups']:
            require(pulse['global_initial_id'] == primary, 'Pulse does not belong to its original primary')
            if pulse.get('status') == 'native_transport_failed':
                failed.append([primary, pulse['group_id']])
                require(pulse['accepted'] is False and pulse['readout'] is None and pulse['final_induced_keV'] is None,
                        'The viewer fabricated readout for a failed native group')
            elif selected is None and pulse['accepted'] is True and pulse['trace_saved']:
                selected = pulse
    require(ids == sorted(set(ids)) and all(0 <= primary < PRIMARY_COUNT for primary in ids)
            and len(failed) == counts['native_failed_groups'], 'Viewer identity or native failure census changed')
    require(selected is not None, 'Run did not produce any accepted pulse with a stored waveform')
    primary, group = selected['global_initial_id'], selected['group_id']
    waveform = control.api('batch-waveforms', name=NAME, batch=0, primary=primary, group=group)
    save(evidence / 'viewer-waveform.json', waveform)
    charge = waveform['charge_input']['induced_equivalent_energy_keV']
    trace = waveform['record']['trace']
    readout = selected['readout']
    require(waveform['configuration_sha256'] == config and waveform['batch_sha256'] == page['batch_sha256']
            and waveform['record']['global_initial_id'] == primary and waveform['record']['group_id'] == group
            and any(charge) and all(math.isfinite(value) for value in charge)
            and len(charge) == len(waveform['charge_input']['time_since_origin_ns']) > 1
            and all(len(trace[key]) == len(trace['time_ns']) > 1 and any(trace[key])
                    and all(math.isfinite(value) for value in trace[key]) for key in ('current_nA', 'preamp_V', 'shaped_V'))
            and readout['current_balance']['passed'] is True and math.isfinite(readout['reconstructed_energy_keV'])
            and readout['reconstructed_energy_keV'] > 0 and type(readout['adc_code']) is int,
            'The saved charge, current, analog or ADC result is missing or invalid')
    return {'nonzero_primary_ids': ids, 'failed_primary_group_ids': failed, 'viewed_primary': primary,
            'viewed_group': group, 'viewed_reconstructed_energy_keV': readout['reconstructed_energy_keV']}


def verify_process_identity(student):
    probe = '''
import subprocess
import sys
from local_ui_jobs import process_identity

with subprocess.Popen([sys.executable, '-c', 'import sys; sys.stdin.read()'], stdin=subprocess.PIPE) as child:
    identity = process_identity(child.pid)
    if not identity or not identity.startswith('mac:') or process_identity(child.pid) != identity:
        raise RuntimeError('Could not verify the lifetime of a live macOS process')
    child.communicate(timeout=5)
    if process_identity(child.pid) is not None:
        raise RuntimeError('Exited macOS process still has an active or unknown lifetime')
'''
    subprocess.run([sys.executable, '-B', '-c', probe], cwd=student / 'tools', check=True, timeout=15)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('student', type=Path, help='Clean extracted student package after Setup.command')
    parser.add_argument('evidence', type=Path, help='Separate run evidence directory')
    args = parser.parse_args()
    student = args.student.resolve(strict=True)
    evidence = args.evidence.resolve()
    require(platform.system() == 'Darwin', 'Run this acceptance on a real macOS host')
    expected = {'ARM64': 'arm64', 'X64': 'x86_64'}.get(os.environ.get('RUNNER_ARCH'))
    require(expected is None or platform.machine() == expected, 'Python process did not use the hosted runner architecture')
    require(not (student / '.git').exists(), 'Acceptance must launch the extracted student package')
    run = student / '.local/runs' / NAME
    require(not run.exists(), 'Preserve the existing run. Use a fresh extracted student package.')
    evidence.mkdir(parents=True, exist_ok=True)
    package_members = verify_package(student)
    print(f'Verified {package_members} original package files and both launcher modes after setup.', flush=True)
    verify_process_identity(student)
    deadline = time.monotonic() + 18 * 60
    with control_session(student, evidence) as control:
        selection, receipt, boundary = run_once(control, run, evidence, deadline)
        ledger, counts, transport_versions, native_versions = verify_outputs(student, run, receipt, evidence)
        view = verify_view(control, run, receipt, ledger, counts, evidence)
    save(evidence / 'acceptance.json', {'status': 'passed', 'terminal_run_status': receipt['status'],
         'scope': 'Packaged macOS Control and one bounded functional simulation', 'architecture': platform.machine(),
         'package_members_verified_after_setup': package_members,
         'process_identity': 'live creation identity and exited process verified',
         'selection': selection, 'native_seed_family': NATIVE_SEED, 'transport_versions': transport_versions,
         'native_versions': native_versions, 'configuration_sha256': receipt['configuration_sha256'],
         'reused_stage_receipts': boundary, 'counts': counts, **view})
    print('Verified 100 initial primaries, sealed Stop/Resume, radiation, SSD, readout and viewable results.')


if __name__ == '__main__':
    main()
