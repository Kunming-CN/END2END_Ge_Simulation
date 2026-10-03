"""Shared, finite local GUI/CLI workflow. Existing transport and SSD own science.

Check resolves data only. Run starts new radiation; Stop waits for the current
stage. Failed/uncertain partial stages are retained, never silently repeated.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import html
import json
import math
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time

from local_ui_jobs import (ControlError, decode_json, existing_julia_environment,
                           process_identity, safe_path)

ROOT = Path(__file__).resolve().parents[1]
BASE = '.local/runs'
NAME = re.compile(r'[A-Za-z0-9_-]{1,48}\Z')
KIND = 'local_scenario_workflow_v1'
SETTINGS = ('shaping_tau_us', 'gain', 'threshold_V', 'adc_bits', 'adc_full_scale_V',
            'feedback_capacitance_pF', 'feedback_tau_us', 'pole_zero_tau_us',
            'peak_policy', 'peak_gate_start_ns', 'peak_gate_end_ns')
FIELDS = {'name','cryostat','detector','source','pose','primary_count','seed','threads','electronics'}
CRYOSTAT = 'lbnl_modular_nominal_v1'
CS = 'cs137_point_decay_v1'
GAMMA = 'mono_gamma_662_axis_v1'
RINGS = ('GeRC02','KMRC01_candidate')
MODELS = ('AK02','SAP22',*RINGS)
STAGES = ('geometry', 'radiation', 'event_ledger', 'response', 'results')
TERMINAL = ('completed', 'completed_with_native_failures')
EXPORTER = '.local/m2a/cs137-build-v1/cryostat_export'
PORTABLE_ADAPTER = 'transport/scenario_source_portable.py'
PORTABLE_BUILD = '.local/m2a/scenario-source-portable-build-v1'


def require(ok, message):
    if not ok:
        raise ControlError(message, 'workflow_refused')


def utc():
    return datetime.now(timezone.utc).isoformat()


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(',', ':')).encode('utf-8')


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def read(path):
    return decode_json(Path(path).read_text(encoding='utf-8-sig'))


def write(path, value, *, fresh=False):
    path = Path(path)
    require(not fresh or not path.exists(), 'Output exists; choose a new name.')
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.pending-' + str(os.getpid())+'-'+secrets.token_hex(12))
    with temporary.open('xb') as stream:
        stream.write(encoded(value)+b'\n'); stream.flush(); os.fsync(stream.fileno())
    if fresh:
        # Hard-link publication refuses overwrite, including another writer.
        os.link(temporary, path); temporary.unlink()
    else:
        # The error alone does not identify a reader/sync/antivirus cause.
        # Preserve atomic replacement and failed pending evidence. Only these
        # Windows access/sharing/lock errors receive a finite publication retry.
        delays=(.01,.02,.04,.08,.16,.32)
        for attempt in range(len(delays)+1):
            try:
                os.replace(temporary, path);break
            except PermissionError as error:
                if os.name!='nt' or getattr(error,'winerror',None) not in (5,32,33) or attempt==len(delays):raise
                time.sleep(delays[attempt])


def run_path(name, root=ROOT):
    require(type(name) is str and NAME.fullmatch(name), 'Use 1–48 letters, numbers, hyphens or underscores for the run name.')
    require(not re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])',name),'This reserved Windows name cannot identify a run.')
    return safe_path(root, BASE+'/'+name)


def child_env(threads):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', OPENBLAS_NUM_THREADS='1',
               OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', JULIA_PKG_OFFLINE='true',
               JULIA_NUM_THREADS=str(threads))
    existing_julia_environment(env)
    return env


def settings_check(settings, root=ROOT):
    require(type(settings) is dict and set(settings) == set(SETTINGS), 'All eleven electronics settings are required.')
    # Input is stdin data, not PowerShell source or an interpolated command.
    environment=dict(os.environ,PYTHONDONTWRITEBYTECODE='1')
    if os.name=='nt':
        system_root=environment.get('SYSTEMROOT') or environment.get('SystemRoot') or environment.get('WINDIR')
        require(bool(system_root),'Existing Windows PowerShell modules are unavailable.')
        for key in list(environment):
            if key.casefold()=='psmodulepath':del environment[key]
        environment['PSModulePath']=str(Path(system_root)/'System32/WindowsPowerShell/v1.0/Modules')
    call = subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass',
                           '-File',str(Path(root)/'tools/workflow_settings.ps1')],
                          input=encoded(settings), stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, cwd=root, env=environment, shell=False,
                          creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    require(call.returncode == 0, 'Electronics settings are invalid; check positive values, ADC bits, threshold and paired peak gates.')
    value = decode_json(call.stdout.decode('utf-8-sig'))
    require(value['status'] == 'valid_configuration_only', 'Settings authority returned an unsupported result.')
    return value


def electronics_feasibility(c,dt=2):
    demand=20000*c['shaping_tau_us']/dt
    require(math.isfinite(demand),'Shaping time cannot fit the inherited calibration limits.')
    n=math.ceil(demand)+1
    require(3<=n<=c['max_samples_per_event'] and (n-1)*dt<=c['max_window_ns'],
            'Shaping time exceeds the inherited calibration sample/window limits.')
    start,end=c['peak_gate_start_ns'],c['peak_gate_end_ns']
    require((start is None)==(end is None),'A peak gate requires both boundaries.')
    if start is not None:
        lo=math.ceil(start/dt)+1;hi=math.floor(end/dt)+1
        require(1<=lo<hi<=c['max_samples_per_event'] and end<=c['max_window_ns'],
                'Peak gate must contain at least two analog samples within the inherited limits.')


def source_pins(detector, root=ROOT, *, portable=False):
    root = Path(root)
    catalog = read(safe_path(root, 'models/catalog.json'))
    entry = next(x for x in catalog['detectors'] if x['id'] == detector)
    names = {'models/catalog.json', 'models/'+entry['model'],
             'transport/cryostat_nominal.json', 'transport/cryostat-source.json',
             'transport/pixi.toml', 'transport/pixi.lock', 'transport/CMakeLists.txt',
             EXPORTER, 'tools/scenario_workflow.py', 'tools/workflow_settings.ps1',
             'tools/workflow_inspection.py',
             'tools/workflow_recovery.py',
             'tools/electronics_settings.ps1', 'tools/electronics_execution.ps1',
             'tools/native_run_validation.ps1', 'tools/local_ui_jobs.py',
             'tools/gamma_native_example.py','tools/charge_check.py','tools/replay_readout.py'}
    names.update('models/'+x for x in entry['dependencies'])
    names.update('simulation/'+n for n in (
        'run.jl','replay.jl','readout.jl','readout_profiles.jl','native_li_example.jl',
        'native_stream.jl','native_response.jl','native_response_guarded.jl','native_boundary_guard.jl',
        'gamma_native_example.jl','scenario_response.jl','test_native_response.jl',
        'test_native_stream.jl','test_readout_profiles.jl','test_gamma_native_example.jl'))
    names.update(('simulation/Project.toml','simulation/Manifest.toml',
                  'simulation/native_readout_profile.json','simulation/readout_demo.json'))
    names.update('transport/'+n for n in ('cs137.py','handoff.py','scenario_prepare.py',
                                          'scenario_transport.py','cryostat_export.cc',
                                          'run.sh','workflow.sh','prepare.sh','gamma.sh'))
    names.add('scenarios/detector-capabilities.json')
    names.update('scenarios/assets/'+n+'.json' for n in (CRYOSTAT,CS))
    if portable:
        from importlib import import_module
        sys.path.insert(0,str(ROOT/'transport')) if str(ROOT/'transport') not in sys.path else None
        adapter=import_module('scenario_source_portable')
        adapter.recheck_map(adapter.PINNED,root)
        names.discard(EXPORTER)
        names.update((PORTABLE_ADAPTER,PORTABLE_BUILD+'/exporter-build.json',PORTABLE_BUILD+'/cryostat_export',PORTABLE_BUILD+'/build-attempt.json'))
        receipt_path=safe_path(root,PORTABLE_BUILD+'/exporter-build.json')
        require(receipt_path.is_file(),'Portable source exporter is not set up. Run.cmd setup -BuildPortableSourceExporter is the explicit build action.')
        receipt=read(receipt_path)
        names.update(receipt['build']['evidence_sha256'])
    if detector in RINGS:
        names.update(('tools/ring_workflow.py','tools/ring_model_contract.py','transport/ring_cs137.py'))
        names.update('simulation/'+n for n in ('ring_stream.jl','ring_response.jl','ring_polarity.jl','workflow_ring_response.jl'))
        names.difference_update(('simulation/scenario_response.jl','simulation/gamma_native_example.jl','simulation/test_gamma_native_example.jl'))
    else:
        names.update('scenarios/assets/'+n+'.json' for n in (detector,GAMMA))
        names.add('scenarios/m11a-'+detector.lower()+'-mono_gamma_662_axis_v1-plus5mm.json')
    manifest = read(root/'transport/cryostat-source.json')
    for item in manifest['files']:
        name = '.local/transport/LBNL/'+item['name']
        require(sha(safe_path(root,name)) == item['sha256'], 'Pinned cryostat input is missing or changed; use the setup guide.')
        names.add(name)
    pins = {name: sha(safe_path(root,name)) for name in sorted(names)}
    require(pins['models/'+entry['model']] == entry['model_sha256'], 'Canonical detector bytes changed.')
    return pins


def runtime_identity(threads):
    env=child_env(threads)
    return {'python_executable':sys.executable,'python_sha256':sha(sys.executable),
            'julia_executable':env['JULIA_EXE'],'julia_sha256':sha(env['JULIA_EXE'])}


def portable_request(selection):
    return {'detector':'GeRC02_Li50min' if selection['detector']=='GeRC02' else selection['detector'],
            'source_mode':selection['source'],'source_pose':selection['pose'],
            'primary_count':selection['primary_count'],'seed':selection['seed']}


def portable_command(root=ROOT):
    return ['wsl.exe','--distribution','Ubuntu-24.04','--cd',str(Path(root)/'transport'),'--exec',
            'bash','./workflow.sh','python','-B','./scenario_source_portable.py']


def portable_query(arguments, root=ROOT, *, runner=subprocess.run):
    result=runner(portable_command(root)+arguments+['--windows-root',str(Path(root).resolve())],
                  stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=120,shell=False,
                  creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    require(result.returncode==0,'Portable source setup/check failed: '+result.stderr.decode('utf-8',errors='replace')[-2000:])
    return decode_json(result.stdout.decode('utf-8-sig'))


def portable_check(config,root=ROOT):
    return portable_query(['check','--request-json',encoded(portable_request(config)).decode('utf-8')],root)


def portable_stage(directory,resolved,stage,root=ROOT):
    checked=resolved.get('portable_source_plan')
    if checked is None:return
    request=portable_request(resolved['selection'])
    require(checked['request']==request,'Portable checked source tuple changed.')
    # After extraction, the stronger ledger reader verifies both the original
    # radiation files and the exact derived stream. The pre-extraction reader
    # deliberately refuses those additional files.
    directory=run_path(resolved['selection']['name'],root)/'transport'
    checked_stage='event_ledger' if stage=='radiation' and (directory/'stream/manifest.json').is_file() else stage
    value=portable_query(['check','--directory','../'+BASE+'/'+resolved['selection']['name']+'/transport','--stage',checked_stage],root)
    for key in ('execution_contract','portable_source_sha256'):
        require(encoded(value.get(key))==encoded(checked[key]),'Portable stage differs from Check: '+key)
    return value


def check(config, *, root=ROOT, validate_settings=settings_check, pin_reader=None,
          runtime_reader=runtime_identity, portable_reader=portable_check, allow_existing=False):
    require(type(config) is dict and set(config)==FIELDS, 'Unsupported or missing configuration fields.')
    run_path(config['name'],root)
    require(config['cryostat']==CRYOSTAT, 'This cryostat has no executable adapter yet.')
    require(config['detector'] in MODELS, 'This detector has no selectable new-run connector yet.')
    require(config['source'] in (CS,GAMMA), 'This source has no executable adapter yet.')
    require(config['detector'] not in RINGS or config['source']==CS,'Ring connectors currently support Cs137 only; select its nominal source.')
    require(type(config['threads']) is int and config['threads'] in (1,2), 'Choose one or two Julia threads.')
    require(type(config['seed']) is int and 0<config['seed']<2147483647, 'Seed must be an integer between 1 and 2147483646.')
    require(type(config['primary_count']) is int, 'Primary count must be an integer.')
    if config['source']==GAMMA:
        require(config['pose']=='plus5mm' and config['primary_count']==20 and config['seed']==26092631,
                'This gamma adapter uses +5 mm, 20 primaries and radiation seed 26092631.')
    else:
        require(config['pose']=='nominal' and config['primary_count'] in (20,500),
                'Cs137 supports nominal pose and 20 or 500 initial decays here; larger runs need a matching pilot connector.')
    require(allow_existing or not run_path(config['name'],root).exists(), 'This output name already exists; choose a new name.')
    validated = validate_settings(config['electronics'],root)
    electronics_feasibility(validated['configuration'])
    if config['source']==CS:
        gate=validated['configuration']['peak_gate_end_ns']
        require(gate is None or gate<=99998,'Cs137 peak gate must end within its half-open 100000 ns pulse window (last analog sample 99998 ns).')
    else:
        c=validated['configuration'];zero_samples=2+math.ceil(20000*c['shaping_tau_us']/2)
        require(zero_samples<=c['max_samples_per_event'] and (zero_samples-1)*2<=c['max_window_ns'],
                'The gamma known-zero two-sample input plus shaping tail exceeds the inherited limits.')
    resolved = {'selection':config, 'profile':validated['profile'],
                'electronics_configuration':validated['configuration'],
                'electronics_physics_sha256':validated['physics_sha256'],
                'source_position_global_mm':[0,42.073,0.290] if config['source']==GAMMA else [0,37.073,0.290],
                'source_kind':'synthetic_gamma' if config['source']==GAMMA else 'radioactive_decay',
                'source_count_unit':'initial gamma primaries' if config['source']==GAMMA else 'initial Cs137 decays',
                'numerics':{'parcels':16,'native_seed_family':2609261,'drift_dt_ns':2,
                            'drift_cap_ns':10000,'stored_temperature_K':78,'runtime_temperature_K':77,
                            'bias_V':{'AK02':500,'SAP22':700,'GeRC02':240,'KMRC01_candidate':370}[config['detector']],
                            'native_failure_policy':'record','models_serial':True,'stages_serial':True},
                'source_sha256':(pin_reader(config['detector'],root) if pin_reader else source_pins(config['detector'],root,portable=True)),
                'runtime_identity':runtime_reader(config['threads'])}
    portable=portable_reader(config,root)
    if portable is not None:
        require(portable['kind']=='portable_source_checked_plan_v1' and portable['schema_version']==1 and
                portable['request']==portable_request(config),'Portable source Check returned an unsupported tuple.')
        resolved['portable_source_plan']=portable
        resolved['source_sha256'].update(portable['portable_source_sha256'])
    if config['detector'] in RINGS:
        from ring_workflow import operating
        resolved['operating_model']=operating(config['detector'])
    return {'kind':KIND,'status':'checked_configuration','science_calls':0,
            'resolved':resolved,'configuration_sha256':digest(resolved)}


def admit(plan,root=ROOT,*,resume=False):
    require(type(plan) is dict and set(plan)=={'kind','status','science_calls','resolved','configuration_sha256'}
            and plan['kind']==KIND and plan['status']=='checked_configuration' and plan['science_calls']==0,
            'Unsupported checked plan.')
    if resume:
        require(plan['resolved'].get('portable_source_plan') is not None,
                'This legacy checked configuration cannot resume under the current portable source contract. Inspect its preserved saved results.')
    actual=check(plan['resolved']['selection'],root=root,allow_existing=resume)
    require(encoded(actual)==encoded(plan),'Checked plan changed or does not reconstruct from current admitted inputs.')
    return actual


def catalog(root=ROOT):
    default=read(Path(root)/'simulation/native_readout_profile.json')['settings']
    registry=read(Path(root)/'scenarios/detector-capabilities.json')
    capabilities={d['model_id']:d for d in registry['detectors']}
    from ring_workflow import LABELS
    detectors=[]
    for model in read(Path(root)/'models/catalog.json')['detectors']:
        id=model['id'];ring=registry.get('control_adapters',{}).get(id)
        available=id in MODELS and (capabilities[id]['lbnl_execution_implemented'] is True or
            id in RINGS and ring=={'adapter':'fresh_ring_control_v1','sources':[CS],'counts':[20,500],
                                 'variant':'GeRC02_Li50min' if id=='GeRC02' else id})
        detectors.append({'id':id,'label':LABELS.get(id,{'AK02':'AK02 · ICPC · +500 V','SAP22':'SAP22 · ICPC · +700 V'}.get(id,id)),
            'available':available,'reason':None if available else 'Selectable new-run connector is pending.',
            'sources':[CS] if id in RINGS else [CS,GAMMA] if id in ('AK02','SAP22') else [],
            'operating_label':'Stored 78 K; runtime 77 K; '+('Li50min at 553.15 K; contacts 1: 0 V, 2: +240 V; fresh fields.' if id=='GeRC02' else
                'Original candidate; contacts 1: 0 V, 2: −370 V; native bias magnitude 370 V; fixed −1 readout wiring; negative injection calibration.' if id=='KMRC01_candidate' else
                'Contact 1 readout; operating bias '+str(500 if id=='AK02' else 700)+' V; fresh fields.' if id in ('AK02','SAP22') else
                'Model viewer only; no Control execution adapter.')})
    # Registry values are the execution dispatch table, not user-supplied commands.
    return {'kind':KIND,'cryostats':[{'id':CRYOSTAT,'label':'LBNL modular cryostat','available':True},
            {'id':'lbnl_monolithic_candidate','label':'LBNL monolithic cryostat','available':False,'reason':'Transport and charge adapters are pending.'}],
            'detectors':detectors,
            'sources':[{'id':CS,'label':'Cs137 point decay','pose':'nominal','counts':[20,500]},
                       {'id':GAMMA,'label':'662 keV gamma beam','pose':'plus5mm','counts':[20]}],
            'electronics_defaults':default,'electronics_keys':list(SETTINGS),
            'numerics':'16 parcels; native seed 2609261; 2 ns grid; 10,000 ns cap; CPU; one or two Julia threads.',
            'setup_limit':'Fresh runs require the explicit portable source-exporter build in the existing locked environment. Fresh-clone and second-computer acceptance remain deferred.',
            'setup_guide':'https://kunming-cn.github.io/END2END_Ge_Simulation/guide.html#setup'}


def verify_pins(resolved, root=ROOT):
    for name,value in resolved['source_sha256'].items():
        require(sha(safe_path(root,name))==value, 'Input or source changed after Check: '+name)


def verify_dispatch_reservations(plan,root=ROOT,dispatch_id=None):
    """A dead outer process does not release an uncertain GUI dispatch."""
    state=safe_path(root,'.local/local-control-v1/workflow-jobs.json')
    matching=False
    if state.exists():
        saved=read(state)
        require(saved.get('kind')=='local_workflow_jobs_v1' and type(saved.get('jobs')) is list,
                'Saved workflow reservations need inspection.')
        for job in saved['jobs']:
            if job.get('status') not in ('dispatch_uncertain','running','stop_requested'):
                require(identity_ended(job.get('driver')),'A saved workflow driver is active or its lifetime is unknown.')
            if job.get('status') in ('dispatch_uncertain','running','stop_requested'):
                require(dispatch_id is not None and job.get('id')==dispatch_id and
                        encoded(job.get('plan'))==encoded(plan),
                        'An active or uncertain GUI reservation prevents a second dispatch.')
                driver=job.get('driver')
                deadline=time.monotonic()+5
                while driver is None and time.monotonic()<deadline:
                    # Popen returns before the parent can persist its creation identity.
                    # No scientific dispatch occurs while this handshake is pending.
                    time.sleep(.05)
                    current=read(state)
                    job=next((j for j in current['jobs'] if j.get('id')==dispatch_id),{})
                    require(job.get('status') in ('dispatch_uncertain','running','stop_requested') and
                            encoded(job.get('plan'))==encoded(plan),'The GUI reservation changed before dispatch.')
                    driver=job.get('driver')
                require(driver and driver.get('pid')==os.getpid() and
                        driver.get('identity') not in (None,'unknown') and
                        process_identity(os.getpid())==driver['identity'],
                        'The GUI driver identity is not committed or cannot be verified.')
                matching=True
    require(dispatch_id is None or matching,'The GUI dispatch has no matching durable reservation.')
    for filename in ('jobs.json','gamma-jobs.json'):
        path=safe_path(root,'.local/local-control-v1/'+filename)
        if not path.exists():continue
        saved=read(path);require(type(saved.get('jobs')) is list,'Legacy control state needs inspection.')
        for job in saved['jobs']:
            require(not job.get('uncertain') and job.get('status') not in
                    ('running','dispatch-uncertain','verification-required','preflight'),
                    'A prior control calculation or uncertain dispatch needs inspection.')
            driver=job.get('child')
            if driver:
                now=process_identity(driver['pid'])
                require(now!='unknown' and (now is None or (driver.get('identity') not in (None,'unknown') and now!=driver['identity'])),
                        'A prior control driver is still active or its lifetime is unknown.')


def identity_ended(driver):
    if not driver:return True
    now=process_identity(driver['pid'])
    return now is None or (now!='unknown' and driver.get('identity') not in (None,'unknown') and now!=driver['identity'])


def lease_busy(root=ROOT):
    try:
        with execution_lease(root):return False
    except (ControlError,OSError):return True


@contextmanager
def execution_lease(root=ROOT):
    folder=safe_path(root,'.local/local-control-v1'); folder.mkdir(parents=True,exist_ok=True)
    with (folder/'workflow.lock').open('a+b') as stream:
        stream.seek(0,2)
        if stream.tell()==0: stream.write(b'0');stream.flush()
        stream.seek(0)
        if os.name=='nt':
            import msvcrt
            try: msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
            except OSError as e: raise ControlError('Another workflow owns the execution lease.','busy') from e
        else:
            import fcntl
            fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        try: yield
        finally:
            stream.seek(0)
            if os.name=='nt': msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            else: fcntl.flock(stream.fileno(),fcntl.LOCK_UN)


def inventory(directory, *, exclude=()):
    directory=Path(directory)
    files={}
    for current,folders,names in os.walk(directory,followlinks=False):
        # Refuse a junction before walking into it or reading its target bytes.
        for name in folders:safe_path(directory,(Path(current)/name).relative_to(directory).as_posix())
        for name in sorted(names):
            relative=(Path(current)/name).relative_to(directory).as_posix()
            path=safe_path(directory,relative)
            if relative not in exclude and '.pending-' not in name:
                files[relative]={'sha256':sha(path),'bytes':path.stat().st_size}
    return files


def verify_inventory(directory, files):
    for name,stamp in files.items():
        path=safe_path(directory,name)
        require(path.stat().st_size==stamp['bytes'] and sha(path)==stamp['sha256'], 'Saved artifact changed: '+name)


def gamma_request(directory, resolved, root=ROOT,*,historical=False):
    from gamma_native_example import validate_events
    transport=directory/'transport'; m=read(transport/'stream/manifest.json')
    prepared=read(transport/'prepared.json'); run=read(transport/'run.json')
    if resolved.get('portable_source_plan') is not None:
        portable_stage(directory,resolved,'event_ledger',root)
    require(m['kind']=='scenario_gamma_event_stream_v1' and m['status']=='complete'
            and m['model_id']==resolved['selection']['detector'] and m['primary_count']==20,
            'Gamma stream does not match the selected model and complete census.')
    require(sha(transport/'prepared.json')==m['prepared_sha256'] and
            sha(transport/'run.json')==m['run_sha256'] and sha(transport/'truth.lh5')==m['source_lh5_sha256'],
            'Gamma radiation/geometry bindings changed.')
    require(run['status']=='complete' and run['returncode']==0 and m['assets']==prepared['assets']
            and m['coordinate_transform']==prepared['coordinate_transform'], 'Gamma prepared/run identity changed.')
    require(m['assets']['source']['id']==GAMMA and m['source_position_global_mm']==resolved['source_position_global_mm'],
            'Gamma source differs from selected tuple.')
    if not historical:
        for mapping in (m['prepared_source_sha256'],m['transport_source_sha256']):
            for name,value in mapping.items(): require(sha(safe_path(root,name))==value,'Gamma producer changed: '+name)
    chunks=m['chunks'];require(len(chunks)==1 and chunks[0]['count']==20,'Unsupported gamma chunks.')
    chunk=safe_path(transport/'stream',chunks[0]['file'])
    require(sha(chunk)==chunks[0]['sha256'],'Gamma chunk changed.')
    events=[decode_json(line) for line in chunk.read_text(encoding='utf-8').splitlines()]
    validate_events(events,m,prepared)
    profile=resolved['profile']; config=dict(resolved['electronics_configuration'],expected_primary_count=20)
    relative=lambda p: p.relative_to(Path(root)).as_posix()
    bindings={relative(transport/'prepared.json'):sha(transport/'prepared.json'),
              relative(transport/'run.json'):sha(transport/'run.json'),
              relative(transport/'truth.lh5'):m['source_lh5_sha256'],
              relative(transport/'stream/manifest.json'):sha(transport/'stream/manifest.json'),
              relative(chunk):sha(chunk), relative(directory/'electronics/profile.json'):sha(directory/'electronics/profile.json')}
    if resolved.get('portable_source_plan') is not None:
        bindings.update({relative(transport/'portable-plan.json'):sha(transport/'portable-plan.json'),
                         relative(transport/'runtime/runtime.json'):sha(transport/'runtime/runtime.json')})
    return {'kind':'local_scenario_gamma_request_v1','model_id':m['model_id'],'source_manifest':m,
            'prepared':prepared,'events':events,'readout_config':config,'profile':profile,
            'configuration_sha256':digest(resolved),'threads':resolved['selection']['threads'],
            'pins':{**resolved['source_sha256'],**bindings}}


def stage_commands(directory,resolved,root=ROOT,environment=None):
    s=resolved['selection']; env=environment or child_env(s['threads']); transport=BASE+'/'+s['name']+'/transport'
    wsl=['wsl.exe','--distribution','Ubuntu-24.04','--cd',str(Path(root)/'transport'),'--','bash','./workflow.sh']
    julia=[env['JULIA_EXE'],'--startup-file=no','--threads='+str(s['threads']),
           '--project='+str(Path(root)/'simulation')]
    if s['source']==CS:
        producer='./ring_cs137.py' if s['detector'] in RINGS else './cs137.py'
        prepare=wsl+['python','-B',producer,'prepare','--model',s['detector'],'--output','../'+transport,
                     '--exporter','../'+EXPORTER,'--events',str(s['primary_count']),'--seed',str(s['seed'])]
        radiation=wsl+['python','-B',producer,'run','--directory','../'+transport]
        extract=wsl+['python','-B',producer,'extract','--directory','../'+transport,'--chunk-size','100']
        response=julia+[str(Path(root)/'simulation/native_response_guarded.jl'),'--input',transport+'/stream/manifest.json',
                 '--output',BASE+'/'+s['name']+'/response','--profile',BASE+'/'+s['name']+'/electronics/profile.json',
                 '--parcels','16','--seed','2609261','--trace-examples','16','--charge-csv','all','--native-failure-policy','record']
        if s['detector'] in RINGS:
            response=julia+[str(Path(root)/'simulation/workflow_ring_response.jl'),'--request',str(directory/'ring-request.json'),'--output',str(directory/'response')]
    else:
        prepare=wsl+['python','-B','./scenario_prepare.py','prepare','--config',
                    '../scenarios/m11a-'+s['detector'].lower()+'-mono_gamma_662_axis_v1-plus5mm.json',
                    '--output','../'+transport,'--exporter','../'+EXPORTER]
        radiation=wsl+['python','-B','./scenario_transport.py','run','--prepared','../'+transport]
        extract=wsl+['python','-B','./scenario_transport.py','extract','--prepared','../'+transport]
        response=julia+[str(Path(root)/'simulation/scenario_response.jl'),'--request',str(directory/'gamma-request.json'),
                         '--output',str(directory/'response')]
    if resolved.get('portable_source_plan') is not None:
        shared=portable_command(root)
        identity=['--windows-root',str(Path(root).resolve())]
        prepare=shared+['prepare','--request',BASE+'/'+s['name']+'/portable-request.json',
                        '--checked-plan','../'+BASE+'/'+s['name']+'/portable-checked-plan.json',
                        '--output','../'+transport,*identity]
        radiation=shared+['run','--directory','../'+transport,*identity]
        extract=shared+['extract','--directory','../'+transport,*identity]
    return {'geometry':prepare,'radiation':radiation,'event_ledger':extract,'response':response}


def command(argv,directory,stage,receipt,environment,root=ROOT):
    log=directory/(stage+'.log');require(not log.exists(),'Stage log already exists; incomplete attempts are retained.')
    receipt['stages'][stage]={'status':'dispatch_intent','arguments':argv,'started_utc':utc(),
                             'nested_worker_lifetime':'unknown_until_terminal_receipt'}
    write(directory/'run.json',receipt)
    start=time.perf_counter()
    with log.open('xb') as stream:
        process=subprocess.Popen(argv,cwd=root,env=environment,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,
                                 shell=False,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        receipt['stages'][stage].update(status='running',pid=process.pid,process_identity=process_identity(process.pid))
        write(directory/'run.json',receipt)
        code=process.wait()
    receipt['stages'][stage].update(exit_code=code,elapsed_seconds=time.perf_counter()-start,
                                  finished_utc=utc(),status='command_exited')
    write(directory/'run.json',receipt)
    require(code==0,'Stage '+stage+' failed; preserve its log and partial output.')


def validate_stage(directory,stage,resolved,root=ROOT,*,historical=False):
    s=resolved['selection']; t=directory/'transport'
    if (stage in ('geometry','radiation') or stage=='event_ledger' and s['source']==CS and s['detector'] not in RINGS) and resolved.get('portable_source_plan') is not None:
        portable_stage(directory,resolved,stage,root)
    if stage=='geometry':
        p=read(t/'prepared.json');r=read(t/'prepare-receipt.json')
        instance=p['instance'] if s['source']==GAMMA else p
        require(p['model_id']==s['detector'] and instance['primary_count']==s['primary_count'] and r['status']=='complete',
                'Prepared model/count/receipt mismatch.')
        report=read(t/'geometry-report.json')
        require(report['overlaps_passed'] is True and report['source_inside_fill'] is True,'Geometry native checks failed.')
        require(instance['seed']==s['seed'] and p['source_position_global_mm']==resolved['source_position_global_mm'],
                'Prepared source pose or radiation seed differs from selected settings.')
        files={**p['files_sha256'],**p.get('portable_files_sha256',{})}
        for name,value in files.items():require(sha(safe_path(t,name))==value,'Prepared artifact changed.')
        if s['detector'] in RINGS:
            from ring_workflow import prepared
            prepared(directory,resolved,root,historical=historical)
        # Later stages add their own transport files; geometry owns its saved inputs.
        names=set(files)|{'prepared.json','prepare-receipt.json'}
        return {n:{'sha256':sha(safe_path(t,n)),'bytes':safe_path(t,n).stat().st_size} for n in sorted(names)}
    if stage=='radiation':
        r=read(t/'run.json');require(r['status']=='complete' and r['returncode']==0 and
        r['prepared_sha256']==sha(t/'prepared.json') and r['source_lh5_sha256']==sha(t/'truth.lh5'), 'Radiation receipt is incomplete or changed.')
        return {n:{'sha256':sha(t/n),'bytes':(t/n).stat().st_size} for n in ('run.json','truth.lh5','run.log')}
    if stage=='event_ledger':
        m=read(t/'stream/manifest.json');require(m['status']=='complete' and m['primary_count']==s['primary_count'] and m['model_id']==s['detector'], 'Extracted event census mismatch.')
        require(sum(c['count'] for c in m['chunks'])==s['primary_count'],'Incomplete event chunks.')
        for c in m['chunks']: require(sha(safe_path(t/'stream',c['file']))==c['sha256'],'Changed event chunk.')
        require(m['prepared_sha256']==sha(t/'prepared.json') and m['run_sha256']==sha(t/'run.json') and m['source_lh5_sha256']==sha(t/'truth.lh5'),'Ledger source bindings changed.')
        if s['source']==GAMMA: gamma_request(directory,resolved,root,historical=historical)
        elif s['detector'] in RINGS:
            from ring_workflow import ledger
            ledger(directory,resolved,root,historical=historical)
        return inventory(t/'stream')
    if stage=='response':
        r=read(directory/'response/run.json')
        require(r['status'] in ('completed_provisional_native_response',*TERMINAL), 'Response is not terminal.')
        require(r['model_id']==s['detector'] and r['counts']['initial_primaries']==s['primary_count'], 'Response detector/census mismatch.')
        c=r['counts'];require(c['accepted']+c['rejected']==c['groups'] and c['rejected']==c['native_failed_groups']+c['readout_rejected'],'Response accounting mismatch.')
        require(r['stored_temperature_K']==78 and r['temperature_K']==77 and r['bias_V']==resolved['numerics']['bias_V']
                and r['parcels']==16 and r['seed_family']==2609261,'Response operating settings differ from selection.')
        if s['source']==GAMMA:
            require(r['request_sha256']==sha(directory/'gamma-request.json') and
                    r['configuration_sha256']==digest(resolved),'Gamma request/configuration binding mismatch.')
            request=gamma_request(directory,resolved,root,historical=historical)
            require(len(r['cases'])==s['primary_count'],'Gamma result lost original primaries.')
            for event,case in zip(request['events'],r['cases']):
                require(case['event_id']==event['event_id'] and case['initial_primary_id']==event['initial_primary_id']
                        and case['truth_ge_edep_keV']==event['truth_ge_edep_keV'] and case['zero_ge']==event['zero_ge']
                        and case['raw_row_indices']==[step['raw_row_index'] for step in event['steps']],
                        'Gamma response changed truth or row identity.')
        else:
            require(r['input_sha256']==sha(t/'stream/manifest.json') and
                    r['profile_sha256']==sha(directory/'electronics/profile.json'), 'Cs137 response input/profile binding mismatch.')
            records=[decode_json(line) for line in (directory/'response/scalars.jsonl').read_text(encoding='utf-8').splitlines()]
            primaries=[e for e in records if e['record_kind']=='decay'];pulses=[e for e in records if e['record_kind']=='pulse']
            require([e['event_id'] for e in primaries]==list(range(s['primary_count'])) and len(pulses)==c['groups'],'Cs137 original primary/group ledger mismatch.')
            truths=[decode_json(line) for line in (directory/'response/truth.jsonl').read_text(encoding='utf-8').splitlines()]
            source=[]
            for chunk in read(t/'stream/manifest.json')['chunks']:
                source.extend(decode_json(line) for line in safe_path(t/'stream',chunk['file']).read_text(encoding='utf-8').splitlines())
            require(encoded(source)==encoded(truths),'Cs137 response changed original truth records.')
            if s['detector'] in RINGS:
                from ring_workflow import response
                response(directory,resolved,r,root,historical=historical)
        actual=read(directory/'response/readout-config.json')
        expected=dict(resolved['electronics_configuration'],expected_primary_count=s['primary_count'])
        # Julia's declared Float64 constants serialize as e.g. 500.0 while the
        # checked PowerShell JSON can contain 500. Only these three real-valued
        # constants allow that spelling difference; every value remains exact.
        comparable=dict(actual);comparison=dict(expected)
        for key in ('calibration_energy_keV','max_window_ns','tail_shaping_constants'):
            require(type(actual[key]) in (int,float) and math.isfinite(actual[key]),'Invalid real-valued readout constant.')
            comparable[key]=float(actual[key]);comparison[key]=float(expected[key])
        require(encoded(comparable)==encoded(comparison),'Readout configuration differs from selected settings.')
        for name,value in r['artifacts'].items(): require(sha(safe_path(directory/'response',name))==value,'Response artifact changed: '+name)
        return inventory(directory/'response')
    return {}


def saved_plan(plan):
    require(set(plan)=={'kind','status','science_calls','resolved','configuration_sha256'} and plan['kind']==KIND and plan['status']=='checked_configuration' and plan['science_calls']==0 and
            digest(plan['resolved'])==plan['configuration_sha256'],'Saved plan authority changed.')
    r=plan['resolved'];s=r['selection'];run_path(s['name'])
    require(set(s)==FIELDS and s['detector'] in MODELS and s['cryostat']==CRYOSTAT and s['source'] in (CS,GAMMA) and
            (s['detector'] not in RINGS or s['source']==CS),'Saved tuple is unsupported.')
    require(type(s['threads']) is int and s['threads'] in (1,2) and type(s['seed']) is int and 0<s['seed']<2147483647 and type(s['primary_count']) is int and
            (s['source']==GAMMA and [s['pose'],s['primary_count'],s['seed']]==['plus5mm',20,26092631] or s['source']==CS and s['pose']=='nominal' and s['primary_count'] in (20,500)),
            'Saved source/count/runtime selection is unsupported.')
    expected_numerics={'parcels':16,'native_seed_family':2609261,'drift_dt_ns':2,'drift_cap_ns':10000,'stored_temperature_K':78,
        'runtime_temperature_K':77,'bias_V':{'AK02':500,'SAP22':700,'GeRC02':240,'KMRC01_candidate':370}[s['detector']],'native_failure_policy':'record','models_serial':True,'stages_serial':True}
    if s['detector'] in RINGS:
        from ring_workflow import operating
        require(encoded(r.get('operating_model'))==encoded(operating(s['detector'])),'Saved ring operating variant/wiring changed.')
    require(encoded(r['numerics'])==encoded(expected_numerics) and r['source_position_global_mm']==([0,42.073,.290] if s['source']==GAMMA else [0,37.073,.290]) and
            r['source_kind']==('synthetic_gamma' if s['source']==GAMMA else 'radioactive_decay'),'Saved source/operating settings changed.')
    require(set(s['electronics'])==set(SETTINGS) and s['electronics']['peak_policy'] in ('signed_input_positive_peak','legacy_reject_negative_input') and
            all(type(v) in (int,float) and math.isfinite(v) for k,v in s['electronics'].items() if k!='peak_policy' and v is not None),
            'Saved electronics values are invalid.')
    e=s['electronics'];profile=r['profile']
    require(set(profile)=={'schema_version','kind','name','settings'} and profile['schema_version']==2 and
            profile['kind']=='native_readout_profile_v1' and type(profile['name']) is str and re.fullmatch('[A-Za-z0-9_.-]{1,80}',profile['name']) and
            all(e[k] is not None and e[k]>0 for k in ('shaping_tau_us','gain','adc_full_scale_V','feedback_capacitance_pF','feedback_tau_us','pole_zero_tau_us')) and
            type(e['adc_bits']) is int and 2<=e['adc_bits']<=24 and e['threshold_V'] is not None and 0<e['threshold_V']<e['adc_full_scale_V'],
            'Saved profile violates its original typed constraints.')
    # PowerShell serializes integral doubles as integers. Compare their numeric
    # values while preserving the original saved bytes and attribution.
    require(r['profile']['settings']==s['electronics'] and
            all(type(v) in (int,float) and math.isfinite(v) for k,v in r['profile']['settings'].items() if k!='peak_policy' and v is not None),
            'Saved profile differs from selected settings.')
    c=r['electronics_configuration']
    require(set(c)==set(SETTINGS)|{'schema_version','calibration_energy_keV','expected_primary_count','max_samples_per_event','max_window_ns','require_all_events','tail_shaping_constants','trace_max_points'} and
            all(c[k]==s['electronics'][k] for k in SETTINGS) and
            [c[k] for k in ('schema_version','calibration_energy_keV','expected_primary_count','max_samples_per_event','max_window_ns','require_all_events','tail_shaping_constants','trace_max_points')]==[2,500,None,500000,1000000,True,20,600],
            'Saved effective electronics configuration changed.')
    electronics_feasibility(c)
    require(bool(r['source_sha256']) and all(type(h) is str and re.fullmatch('[0-9a-f]{64}',h) for h in r['source_sha256'].values()) and
            all(re.fullmatch('[0-9a-f]{64}',r['runtime_identity'][k]) for k in ('python_sha256','julia_sha256')),'Saved source/runtime attribution is incomplete.')


def stopped_checkpoint(directory,receipt,root=ROOT):
    identity=secrets.token_hex(16);receipt['checkpoint_id']=identity
    write(directory/'run.json',receipt)
    path=safe_path(root,'.local/local-control-v1/checkpoints/'+identity+'.json')
    write(path,{'kind':'workflow_stopped_checkpoint_v1','run_name':directory.name,
                'configuration_sha256':receipt['configuration_sha256'],'run_sha256':sha(directory/'run.json'),
                'artifacts':inventory(directory,exclude=('STOP.json',))},fresh=True)


def verify_checkpoint(directory,receipt,root=ROOT):
    identity=receipt.get('checkpoint_id');require(type(identity) is str and re.fullmatch('[0-9a-f]{32}',identity),'Stopped run has no preserved checkpoint authority.')
    checkpoint=read(safe_path(root,'.local/local-control-v1/checkpoints/'+identity+'.json'))
    require(checkpoint['kind']=='workflow_stopped_checkpoint_v1' and checkpoint['run_name']==directory.name and
            checkpoint['configuration_sha256']==receipt['configuration_sha256'] and checkpoint['run_sha256']==sha(directory/'run.json'),
            'Stopped checkpoint receipt changed.')
    require(encoded(checkpoint['artifacts'])==encoded(inventory(directory,exclude=('STOP.json',))),'Stopped checkpoint inventory changed.')


def result_page(directory,receipt):
    r=read(directory/'response/run.json'); s=receipt['resolved']['selection']
    body='<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>GeSignal local results</title><style>body{font:16px/1.6 system-ui;max-width:960px;margin:30px auto;padding:20px;color:#17364a}pre{white-space:pre-wrap;overflow-wrap:anywhere}a{color:#007d8f}details{padding:12px;border:1px solid #ccd;border-radius:10px;margin:12px 0}</style><h1>'+html.escape(s['detector'])+' · '+html.escape(s['source'])+'</h1><p>Original primary count: '+str(s['primary_count'])+'. Every original ID, zero and recorded failure is retained.</p><pre>'+html.escape(json.dumps(r['counts'],indent=2))+'</pre><p>Truth Edep, induced charge and reconstructed energy remain separate. Calibration uses an independent 500 keV charge injection.</p><details><summary>Settings and stage evidence</summary><pre>'+html.escape(json.dumps(receipt['resolved']['selection'],indent=2))+'</pre></details><p>Run data and stage logs are available in the application. Synthetic isolated readout; engineering example.</p></html>'
    body=body.replace('</html>','<p><a href="response/summary.html">Open saved event waveforms</a> · <a href="response/scalars.csv">All event scalars</a> · <a href="response/truth.jsonl">Original radiation truth</a> · <a href="resolved-config.json">Exact checked settings</a> · <a href="run.json">Stage receipts</a></p></html>')
    (directory/'index.html').write_text(body,encoding='utf-8')


def execute(plan, *, root=ROOT, resume=False, executor=command,dispatch_id=None,continuation=False):
    require(not (resume and continuation),'A derivative is a new root, not failed-stage Resume.')
    plan=admit(plan,root,resume=resume)
    resolved=plan['resolved'];s=resolved['selection'];directory=run_path(s['name'],root)
    with execution_lease(root):
        verify_dispatch_reservations(plan,root,dispatch_id)
        # A lost outer lease cannot establish that a nested WSL/Julia child ended.
        for previous in (Path(root)/BASE).glob('*/run.json'):
            prior=read(previous)
            if prior.get('kind')==KIND and previous.parent!=directory:
                from workflow_inspection import verified_retirement
                retired=verified_retirement(previous.parent,root)
                if not retired:
                    from workflow_recovery import verified_retirement as verified_prefix
                    retired=verified_prefix(previous.parent,root)
                require(retired or (prior['status'] not in ('running','dispatch_uncertain') and
                        all(x['status']=='completed' for x in prior['stages'].values())),
                        'A previous workflow has an uncertain or incomplete stage; inspect its retained output before a new run.')
        verify_pins(resolved,root); environment=child_env(s['threads'])
        if resume:
            receipt=read(directory/'run.json')
            require(receipt['kind']==KIND and receipt['configuration_sha256']==plan['configuration_sha256'], 'Resume uses saved settings only.')
            require(receipt['status']=='stopped','Only a stage-boundary stopped run can resume; partial or uncertain runs need inspection.')
            verify_checkpoint(directory,receipt,root)
            require(set(receipt['stages'])==set(STAGES[:len(receipt['stages'])]),'Stopped stages do not form a completed prefix.')
            for stage,record in receipt['stages'].items(): require(record['status']=='completed','Incomplete stage must be inspected; it cannot be repeated.')
            for stage,record in receipt['stages'].items():
                base=directory/'response' if stage=='response' else directory/'transport/stream' if stage=='event_ledger' else directory/'transport'
                verify_inventory(base,record['artifacts'])
                actual=validate_stage(directory,stage,resolved,root)
                require(encoded(actual)==encoded(record['artifacts']),'Completed-stage inventory is not authoritative.')
            receipt.setdefault('resumes',[]).append({'requested_utc':utc(),'prior_stop':read(directory/'STOP.json') if (directory/'STOP.json').exists() else None})
            receipt['supervisor']={'pid':os.getpid(),'identity':process_identity(os.getpid())}
            (directory/'STOP.json').unlink(missing_ok=True)
        else:
            directory.mkdir(parents=True,exist_ok=False)
            receipt={'kind':KIND,'status':'running','configuration_sha256':plan['configuration_sha256'],
                     'resolved':resolved,'created_utc':utc(),'stages':{},'supervisor':{'pid':os.getpid(),'identity':process_identity(os.getpid())},
                     'runtime':{'python':sys.executable,'python_sha256':sha(sys.executable),'julia':environment['JULIA_EXE'],'julia_sha256':sha(environment['JULIA_EXE'])}}
            write(directory/'resolved-config.json',plan,fresh=True)
            write(directory/'electronics/profile.json',resolved['profile'],fresh=True)
            if resolved.get('portable_source_plan') is not None:
                write(directory/'portable-request.json',portable_request(s),fresh=True)
                write(directory/'portable-checked-plan.json',resolved['portable_source_plan'],fresh=True)
        write(directory/'run.json',receipt)
        try:
            if continuation:
                from workflow_recovery import transfer
                transfer(directory,plan,receipt,root);write(directory/'run.json',receipt)
            commands=stage_commands(directory,resolved,root,environment)
            for stage in STAGES:
                verify_pins(resolved,root)
                if stage in receipt['stages']:
                    base=directory/'response' if stage=='response' else directory/'transport/stream' if stage=='event_ledger' else directory/'transport'
                    verify_inventory(base,receipt['stages'][stage]['artifacts']);continue
                if (directory/'STOP.json').exists():
                    receipt['status']='stopped';stopped_checkpoint(directory,receipt,root);return receipt
                if stage=='results':
                    observed=time.perf_counter();started=utc();result_page(directory,receipt)
                    require((directory/'index.html').stat().st_size>0,'Results page was not created.')
                    receipt['stages'][stage]={'status':'completed','started_utc':started,'elapsed_seconds':time.perf_counter()-observed,
                        'artifacts':{'index.html':{'sha256':sha(directory/'index.html'),'bytes':(directory/'index.html').stat().st_size}},'finished_utc':utc()};continue
                if stage=='response' and s['source']==GAMMA:
                    write(directory/'gamma-request.json',gamma_request(directory,resolved,root),fresh=True)
                elif stage=='response' and s['detector'] in RINGS:
                    from ring_workflow import request
                    write(directory/'ring-request.json',request(directory,resolved,root),fresh=True)
                executor(commands[stage],directory,stage,receipt,environment,root)
                artifacts=validate_stage(directory,stage,resolved,root)
                receipt['stages'][stage].update(status='completed',artifacts=artifacts)
                write(directory/'run.json',receipt)
            verify_pins(resolved,root);r=read(directory/'response/run.json')
            receipt['counts']=r['counts'];receipt['status']='completed_with_native_failures' if r['counts']['native_failed_groups'] else 'completed'
            receipt['finished_utc']=utc();write(directory/'run.json',receipt)
            write(directory/'COMPLETE.json',{'kind':KIND,'status':receipt['status'],'configuration_sha256':plan['configuration_sha256'],
                   'artifacts':inventory(directory,exclude=('COMPLETE.json','STOP.json'))},fresh=True)
            return receipt
        except BaseException as error:
            receipt.update(status='failed',error=str(error),failed_utc=utc(),resume_allowed=False)
            try:write(directory/'run.json',receipt)
            except Exception as publication_error:
                # A second publication failure must not mask the first cause.
                error.add_note('Failure receipt could not be published; preserved pending evidence: '+repr(publication_error))
            raise


def inspect(name,root=ROOT):
    directory=run_path(name,root);receipt=read(directory/'run.json')
    require(receipt['kind']==KIND and receipt['configuration_sha256']==digest(receipt['resolved']), 'Saved configuration changed.')
    plan=read(directory/'resolved-config.json')
    if receipt['status'] in TERMINAL:saved_plan(plan)
    else:admit(plan,root,resume=True)
    require(encoded(receipt['resolved'])==encoded(plan['resolved']),'Run settings differ from saved checked authority.')
    if receipt['status'] in TERMINAL:
        require(set(receipt['stages'])==set(STAGES) and all(v['status']=='completed' for v in receipt['stages'].values()),'Terminal stage census is incomplete.')
        complete=read(directory/'COMPLETE.json');require(complete['kind']==KIND and complete['status']==receipt['status'] and complete['configuration_sha256']==receipt['configuration_sha256'],'Complete binding mismatch.')
        verify_inventory(directory,complete['artifacts'])
        require(encoded(complete['artifacts'])==encoded(inventory(directory,exclude=('COMPLETE.json','STOP.json'))),'Completed artifact inventory is incomplete.')
        for stage in STAGES[:-1]:validate_stage(directory,stage,receipt['resolved'],root,historical=True)
        verify_inventory(directory,receipt['stages']['results']['artifacts'])
        if 'saved_results_finalization' in receipt:
            from workflow_finalize import verify_finalization
            verify_finalization(directory,receipt,root)
    else:
        complete=None
    receipt['verification']='terminal_artifacts_verified' if complete else 'nonterminal_preserved'
    return receipt


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=('catalog','check','run','continue','resume','inspect','stop','finalize-results'))
    p.add_argument('--config');p.add_argument('--plan');p.add_argument('--name');p.add_argument('--dispatch-id',help=argparse.SUPPRESS);a=p.parse_args(argv)
    if a.action=='catalog': value=catalog()
    elif a.action=='check': require(a.config,'--config is required.');value=check(read(Path(a.config)))
    elif a.action=='run': require(a.plan,'--plan from Check is required.');value=execute(read(Path(a.plan)),dispatch_id=a.dispatch_id)
    elif a.action=='continue': require(a.plan,'--plan from verified prefix is required.');value=execute(read(Path(a.plan)),dispatch_id=a.dispatch_id,continuation=True)
    elif a.action=='resume':
        require(a.name,'--name is required.');d=run_path(a.name);value=execute(read(d/'resolved-config.json'),resume=True,dispatch_id=a.dispatch_id)
    elif a.action=='inspect': require(a.name,'--name is required.');value=inspect(a.name)
    elif a.action=='finalize-results':
        require(a.name,'--name is required.')
        from workflow_finalize import finalize
        value=finalize(a.name)
    else:
        require(a.name,'--name is required.');d=run_path(a.name);r=read(d/'run.json');require(r['status']=='running','Run is not active.');write(d/'STOP.json',{'requested_utc':utc()},fresh=True);value={'status':'stop_requested'}
    print(json.dumps(value,allow_nan=False,ensure_ascii=False))


if __name__=='__main__': main()
