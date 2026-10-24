"""GeGI-only assembly and multichannel workflow on the shared stage lifecycle."""
from __future__ import annotations
import argparse
import copy
import html
import json
import math
import os
from pathlib import Path
import subprocess
import sys

import scenario_workflow as W

KIND = 'local_gegi_workflow_v1'
CRYOSTAT = 'gegi_cryostat_v1'
DETECTOR = 'GeGI_3D'
SOURCE = 'gegi_mono_gamma_v1'
CS137 = 'cs137_point_decay_v1'
CO60 = 'co60_point_decay_v1'
DECAY_SOURCES = (CS137, CO60)
REQUEST_FILE = 'gegi-request.json'
STAGES = W.STAGES
MODEL_SHA = '4b6c71c178c81e68bc1fe093d491b59ab99f19aed5adaba5fc61bba74d445c04'
FIELDS = W.FIELDS | {'gamma_energy_keV', 'source_position_mm'}
CACHE_BASE = 'Additional_Simulations/Visualization_3D/detectors/GeGI_3D/runs/20260922_suite_v3'
SOURCES = ('tools/gegi_workflow.py', 'tools/gegi_response.py', 'tools/gegi_imaging.py',
           'tools/gegi_standalone_reconstruction.py', 'tools/gegi_signal_reconstruction.py', 'tools/gegi_signal_recovery.py', 'tools/gegi_event_store.py',
           'tools/gegi_calibration_admission.py',
           'tools/scenario_workflow.py', 'tools/local_ui_jobs.py',
           'simulation/gegi_response.jl', 'simulation/gegi_signal_helpers.jl',
           'simulation/run.jl', 'simulation/replay.jl', 'simulation/readout.jl', 'simulation/readout_profiles.jl',
           'simulation/readout_demo.json', 'simulation/native_readout_profile.json',
           'simulation/Project.toml', 'simulation/Manifest.toml', 'models/GeGI_3D.yaml',
           'models/catalog.json', 'transport/pixi.toml', 'transport/pixi.lock',
           'scenarios/assets/gegi_cryostat_v1.json')


def catalog_entries(root=W.ROOT):
    return {
        'cryostat': {'id': CRYOSTAT, 'label': 'GeGI cryostat', 'available': True},
        'source': {'id': SOURCE, 'label': 'GeGI point gamma source', 'available': True,
                   'source_contract': {'adapter': 'gegi_source_v1', 'count_unit': 'emitted gamma'},
                   'source_angle': {'enabled': False},
                   'scope': 'Isotropic monoenergetic point source; position in GeGI detector coordinates.'},
        'detector': {'id': DETECTOR, 'label': 'GeGI · 32 strips + 2 guards', 'available': True,
                     'reason': None, 'block_code': None, 'setup_required': False,
                     'workflow_kind': KIND, 'assemblies': [CRYOSTAT], 'sources': [SOURCE],
                     'operating_label': 'Original 92.3 K, −879 V / 0 V. Native signed signals on all 34 electrodes. Dedicated GeGI cryostat only.',
                     'parameter_summary': [{'label': 'Readout strips', 'value': 32},
                                           {'label': 'Guard electrodes', 'value': 2}],
                     'checks': [{'label': 'Dedicated cryostat', 'status': 'compatible_envelope',
                                 'detail': 'Measured front layers; explicitly nominal side/rear envelope. Each run checks native geometry.'}]}}


def command(root=W.ROOT):
    return ['wsl.exe', '--distribution', 'Ubuntu-24.04', '--cd', str(Path(root)/'transport'),
            '--exec', 'bash', './workflow.sh', 'python', '-B', './gegi_source.py']


def query(args, root=W.ROOT, runner=subprocess.run):
    p = runner(command(root)+args+['--windows-root', str(Path(root).resolve())], cwd=root,
               stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180, shell=False,
               creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    W.require(p.returncode == 0, 'GeGI transport check failed: '+p.stderr.decode('utf-8', errors='replace')[-3000:])
    return W.decode_json(p.stdout.decode('utf-8-sig'))


def validate_selection(selection):
    W.require(type(selection) is dict and (set(selection)==FIELDS or
              selection.get('source') in DECAY_SOURCES and set(selection)==FIELDS-{'gamma_energy_keV'}),
              'Unsupported GeGI configuration fields.')
    W.require(selection['cryostat'] == CRYOSTAT and selection['detector'] == DETECTOR,
              'The GeGI cryostat accepts only the GeGI detector.')
    W.require(selection['source'] in (SOURCE,*DECAY_SOURCES) and selection['pose'] == 'custom',
              'Choose the GeGI gamma, registered Cs137 or registered Co60 point source.')
    W.require(type(selection['primary_count']) is int and 1 <= selection['primary_count'] <= 10000,
              'Each GeGI batch accepts 1–10000 emitted gammas or initial isotope nuclei.')
    W.require(type(selection['seed']) is int and 0 < selection['seed'] < 2147483647, 'Invalid radiation seed.')
    W.require(type(selection['threads']) is int and selection['threads'] in (1, 2), 'Use one or two Julia threads.')
    energy = selection.get('gamma_energy_keV')
    if selection['source']==SOURCE:
        W.require(type(energy) in (int, float) and math.isfinite(energy) and 1 <= energy <= 10000,
                  'GeGI gamma energy must be between 1 and 10000 keV.')
    else:
        W.require(energy is None, 'Isotope decay energies come from the registered nuclear data, not a mono-gamma energy.')
    p = selection['source_position_mm']
    W.require(type(p) is list and len(p) == 3 and all(type(x) in (int, float) and math.isfinite(x) for x in p),
              'Source position needs three finite coordinates in mm.')
    return selection


def field_cache(root=W.ROOT):
    """Optional local reuse, never a packaged runtime requirement."""
    root = Path(root)
    path = W.safe_path(root, CACHE_BASE+'/solved_fields.jls')
    marker = W.safe_path(root, CACHE_BASE+'/solved_fields.model.sha256')
    if not path.exists():
        return None
    W.require(marker.is_file() and marker.read_text().strip() == MODEL_SHA,
              'Existing GeGI native field cache has a different model identity.')
    return {'ref': CACHE_BASE+'/solved_fields.jls', 'sha256': W.sha(path),
            'model_sha256': MODEL_SHA, 'scope': 'Existing native 34-electrode SSD state; no display-grid substitution.'}


def check(selection, *, root=W.ROOT, allow_existing=False, validate_settings=W.settings_check,
          runtime_reader=W.runtime_identity, transport_reader=query, pin_reader=None, cache_reader=field_cache):
    validate_selection(selection)
    directory = W.run_path(selection['name'], root)
    W.require(allow_existing or not directory.exists(), 'Output exists; choose a new run name.')
    W.require(W.sha(Path(root)/'models/GeGI_3D.yaml') == MODEL_SHA, 'Frozen GeGI model changed.')
    settings = validate_settings(selection['electronics'], root)
    W.electronics_feasibility(settings['configuration'])
    transport = transport_reader(['check', '--selection-json', W.encoded(selection).decode('utf-8')], root)
    W.require(transport['kind'] == 'gegi_source_checked_v1' and transport['selection'] == selection,
              'GeGI source/cryostat check changed the selected settings.')
    pins = dict(transport['source_sha256'])
    pins.update(pin_reader(root) if pin_reader else {p: W.sha(W.safe_path(root, p)) for p in SOURCES})
    numerics = {'drift_dt_ns': 1.0, 'drift_cap_ns': 1000.0, 'native_seed': 26101702,
                'precision_bits': 64, 'diffusion': False, 'self_repulsion': False,
                'field_policy': 'reuse exact native 34-electrode state or solve sequentially',
                'depth_calibration': 'independent SSD central-pixel timing calibration',
                'scope': 'Deterministic engineering response; no measured noise or detector-resolution validation.'}
    resolved = {'selection': copy.deepcopy(selection), 'profile': settings['profile'],
                'electronics_configuration': settings['configuration'],
                'electronics_physics_sha256': settings['physics_sha256'],
                'model_ref': 'models/GeGI_3D.yaml', 'model_sha256': MODEL_SHA,
                'transport_plan': transport, 'source_sha256': pins, 'numerics': numerics,
                'field_cache': cache_reader(root), 'runtime_identity': runtime_reader(selection['threads'])}
    return {'kind': KIND, 'status': 'checked_configuration', 'science_calls': 0,
            'resolved': resolved, 'configuration_sha256': W.digest(resolved)}


def admit(plan, root=W.ROOT, *, resume=False):
    W.require(type(plan) is dict and set(plan) == {'kind', 'status', 'science_calls', 'resolved', 'configuration_sha256'}
              and plan['kind'] == KIND and plan['status'] == 'checked_configuration' and plan['science_calls'] == 0,
              'Unsupported GeGI checked plan.')
    actual = check(plan['resolved']['selection'], root=root, allow_existing=resume)
    W.require(actual == plan, 'GeGI checked settings, source, runtime or cache changed; check again.')
    return actual


def native_request(directory, resolved, root=W.ROOT):
    base = W.BASE+'/'+Path(directory).name
    profile = base+'/electronics/profile.json'
    stream = base+'/transport/stream/manifest.json'
    return {'kind': 'gegi_native_request_v1', 'configuration_sha256': W.digest(resolved),
            'selection': resolved['selection'], 'profile_ref': profile, 'profile_sha256': W.sha(Path(root)/profile),
            'stream_ref': stream, 'stream_sha256': W.sha(Path(root)/stream),
            'source_sha256': resolved['source_sha256'], 'numerics': resolved['numerics'],
            'model_ref': resolved['model_ref'], 'model_sha256': resolved['model_sha256'],
            'field_cache': resolved['field_cache']}


def stage_commands(directory, resolved, root=W.ROOT):
    base = '../'+W.BASE+'/'+Path(directory).name
    common = command(root)
    tail = ['--windows-root', str(Path(root).resolve())]
    return {
        'geometry': common+['prepare', '--selection', base+'/selection.json', '--checked', base+'/source-checked.json', '--output', base+'/transport', *tail],
        'radiation': common+['run', '--directory', base+'/transport', *tail],
        'event_ledger': common+['extract', '--directory', base+'/transport', *tail],
        'response': [sys.executable, '-B', '-X', 'utf8', str(Path(root)/'tools/gegi_response.py'),
                     '--request', str(Path(directory)/REQUEST_FILE), '--output', str(Path(directory)/'response')]}


def validate_stage(directory, stage, resolved, root=W.ROOT):
    directory = Path(directory)
    if stage in ('geometry', 'radiation', 'event_ledger'):
        query(['verify', '--directory', '../'+W.BASE+'/'+directory.name+'/transport', '--stage', stage], root)
        if stage == 'event_ledger':
            return W.inventory(directory/'transport/stream')
        if stage == 'radiation':
            return {p: {'sha256': W.sha(directory/'transport'/p), 'bytes': (directory/'transport'/p).stat().st_size}
                    for p in ('run.json', 'run.log', 'truth.lh5')}
        prepared = W.read(directory/'transport/prepared.json')
        return {p: {'sha256': W.sha(directory/'transport'/p), 'bytes': (directory/'transport'/p).stat().st_size}
                for p in (*prepared['files_sha256'], 'prepared.json', 'prepare-receipt.json')}
    if stage == 'response':
        r = W.read(directory/'response/run.json')
        value = W.read(directory/'response/results.json')
        W.require(r['kind'] == 'gegi_native_response_v1' and r['status'] in W.TERMINAL,
                  'GeGI native response is incomplete.')
        W.require(r['configuration_sha256'] == W.digest(resolved) == value['configuration_sha256'],
                  'GeGI response configuration mismatch.')
        W.require(r['request_sha256'] == W.sha(directory/REQUEST_FILE), 'GeGI request bytes changed.')
        counts = value['counts']
        W.require(counts == r['counts'] and counts['initial_primaries'] == resolved['selection']['primary_count']
                  and counts['zero_deposit_primaries']+counts['nonzero_primaries'] == counts['initial_primaries'],
                  'GeGI initial/zero/nonzero census changed.')
        events = value['events']
        W.require(len(events) == counts['nonzero_primaries'] and len({e['event_id'] for e in events}) == len(events),
                  'GeGI nonzero identity census changed.')
        W.require([c['id'] for c in value['channels']] == list(range(1, 35)), 'GeGI electrode identities changed.')
        for ref, digest in r['artifacts'].items():
            W.require(W.sha(W.safe_path(directory/'response', ref)) == digest, 'GeGI response artifact changed: '+ref)
        return W.inventory(directory/'response')
    return {}


def execute(plan, *, root=W.ROOT, resume=False, dispatch_id=None, executor=W.command):
    return W.execute(plan, root=root, resume=resume, dispatch_id=dispatch_id,
                     executor=executor, workflow=sys.modules[__name__])


def inspect(name, root=W.ROOT):
    directory = W.run_path(name, root)
    plan, r = W.read(directory/'resolved-config.json'), W.read(directory/'run.json')
    W.require(plan['kind'] == r['kind'] == KIND and plan['resolved'] == r['resolved']
              and W.digest(r['resolved']) == plan['configuration_sha256'] == r['configuration_sha256'],
              'Saved GeGI settings changed.')
    validate_selection(r['resolved']['selection'])
    if r['status'] in W.TERMINAL:
        complete = W.read(directory/'COMPLETE.json')
        W.require(complete['kind'] == KIND and complete['status'] == r['status']
                  and complete['configuration_sha256'] == r['configuration_sha256'], 'GeGI completion binding changed.')
        W.require(set(r['stages']) == set(STAGES) and all(s['status'] == 'completed' for s in r['stages'].values()),
                  'GeGI terminal stages are incomplete.')
        W.verify_inventory(directory, complete['artifacts'])
        W.require(complete['artifacts'] == W.inventory(directory, exclude=('COMPLETE.json', 'STOP.json')),
                  'GeGI completed artifact census changed.')
        r['verification'] = 'terminal_artifacts_verified'
    else:
        r['verification'] = 'nonterminal_preserved'
    return r


def result_view(name, root=W.ROOT):
    r = inspect(name, root)
    W.require(r['status'] in W.TERMINAL, 'GeGI results are available after the run completes.')
    value = W.read(W.run_path(name, root)/'response/results.json')
    W.require(value['kind'] == 'gegi_multichannel_results_v1'
              and value['configuration_sha256'] == r['configuration_sha256'], 'GeGI result identity changed.')
    return value


def result_reader(name, root=W.ROOT):
    """Verify the original run once, then index exact bounded result ranges."""
    from gegi_result_reader import Reader
    receipt=inspect(name,root)
    W.require(receipt['status'] in W.TERMINAL,'GeGI results are available after the run completes.')
    directory=W.run_path(name,root);complete=W.read(W.safe_path(directory,'COMPLETE.json'))
    return Reader(W.safe_path(directory,'response/results.json'),
        complete['artifacts']['response/results.json']['sha256'],name=name,
        configuration_sha256=receipt['configuration_sha256'],
        seal_paths=[W.safe_path(directory,ref) for ref in
                    ('COMPLETE.json','run.json','resolved-config.json','gegi-request.json','response/run.json')])


def request_stop(name, root=W.ROOT):
    directory = W.run_path(name, root)
    r = W.read(directory/'run.json')
    W.require(r['kind'] == KIND and r['status'] == 'running', 'GeGI run is not active.')
    W.write(directory/'STOP.json', {'requested_utc': W.utc()}, fresh=True)
    return {'status': 'stop_requested'}


def result_page(directory, receipt):
    value = W.read(Path(directory)/'response/results.json')
    body = '<!doctype html><html lang="en"><meta charset="utf-8"><title>GeGI results</title><style>body{font:16px/1.6 system-ui;max-width:960px;margin:40px auto;color:#193c50}pre{white-space:pre-wrap}a{color:#006a83}</style><h1>GeGI multichannel results</h1>'
    body += '<p>Open this run in GeSignal Control for individual electrode signals and the saved reconstruction status.</p><pre>'+html.escape(json.dumps(value['counts'], indent=2))+'</pre>'
    body += '<p>32 strips and 2 guards retain signed signals. Zero-deposit primaries remain in the total denominator. New standalone runs require a compatible independent saved waveform calibration for depth; no source map is created from the historical timing estimator. Fixed energy readout and original timing diagnostics remain available.</p>'
    for label, path in [('Channel results and reconstructed cones', 'response/results.json'), ('Run evidence', 'run.json'),
                        ('Checked settings', 'resolved-config.json'), ('Original radiation', 'transport/truth.lh5')]:
        body += '<p><a href="'+path+'">'+label+'</a></p>'
    (Path(directory)/'index.html').write_text(body+'</html>', encoding='utf-8')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('check', 'run', 'resume', 'inspect', 'stop'))
    p.add_argument('--config'); p.add_argument('--plan'); p.add_argument('--name'); p.add_argument('--dispatch-id')
    a = p.parse_args()
    if a.action == 'check': result = check(W.read(a.config))
    elif a.action in ('run', 'resume'): result = execute(W.read(a.plan), resume=a.action == 'resume', dispatch_id=a.dispatch_id)
    elif a.action == 'stop': result = request_stop(a.name)
    else: result = inspect(a.name)
    print(W.encoded(result).decode('utf-8'))


if __name__ == '__main__':
    main()
