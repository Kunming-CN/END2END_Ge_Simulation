"""TEST ONLY: tiny source ZIP fixture and intercepted children, never scientific data.

Only cloned Check-Setup/Start-Process are intercepted. Production CLI dispatch,
campaign argument construction, snapshots, receipt writes and validators execute.
No Julia/WSL/Geant4/fields/electronics are executed. Synthetic ledgers deliberately
test orchestration contracts, not native numerics or experimental agreement.
"""
import hashlib
import json
from pathlib import Path
import shutil
import sys

PRODUCER = ['CMakeLists.txt', 'cryostat-source.json', 'cryostat_export.cc',
            'cryostat_nominal.json', 'cs137.py', 'handoff.py', 'pixi.lock', 'pixi.toml']
CONSUMER = ['Manifest.toml', 'Project.toml', 'native_li_example.jl', 'native_response.jl',
            'native_stream.jl', 'readout.jl', 'readout_demo.json', 'readout_profiles.jl',
            'replay.jl', 'run.jl', 'test_native_response.jl', 'test_native_stream.jl',
            'test_readout_profiles.jl', 'native_response_guarded.jl', 'native_boundary_guard.jl']
PREPARED = ['canonical.gdml', 'geometry-report.json', 'geometry.gdml', 'geometry.log',
            'parameters.txt', 'probe-points.txt', 'run.mac', 'scenario.json']
ARTIFACTS = ['endpoints.csv', 'endpoints.jsonl', 'histograms.csv', 'histograms.json',
             'input-contract.json', 'input-prepared.json', 'profile-input.json', 'profile.json',
             'readout-config.json', 'scalars.csv', 'scalars.jsonl', 'signals.csv',
             'summary.html', 'traces.jsonl', 'truth.csv', 'truth.jsonl']
TOOLS = ['scenario_cli.ps1', 'run_native_campaign.ps1', 'native_run_validation.ps1',
         'inspect_native_run.ps1', 'verify_native_pilot.ps1', 'electronics_settings.ps1',
         'electronics_execution.ps1', 'electronics_execution_fixture.py']
EXPORTER = '.local/m2a/cs137-build-v1/cryostat_export'
GROUPING = dict(activity_live_time_pileup_claim=False, horizon_ns=100000,
                interval='[origin, origin+horizon)', name='nominal_isolated_windows_v1',
                state_at_group_start='reset', tail='truncate at horizon; recovery not established')

def read(p): return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p, v):
    p=Path(p); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(v, indent=2), encoding='utf-8')
def hashes(root, names): return {n: sha(root/n) for n in names}

def clone(source, dest, python):
    files = ['Run.cmd', 'scenarios/lbnl-cs137.json', 'simulation/native_readout_profile.json',
             'models/AK02.yaml', 'models/SAP22.yaml', 'transport/Run.cmd']
    files += ['tools/'+n for n in TOOLS] + ['simulation/'+n for n in CONSUMER] + ['transport/'+n for n in PRODUCER]
    for name in files:
        p=dest/name; p.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(source/name, p)
    # Stub upstream bytes and manifest are deliberately not original science.
    p=dest/'.local/transport/LBNL/fixture.txt'; p.parent.mkdir(parents=True); p.write_text('TEST ONLY')
    save(dest/'transport/cryostat-source.json', {'files':[dict(name='fixture.txt', sha256=sha(p), bytes=p.stat().st_size)]})
    p=dest/EXPORTER; p.parent.mkdir(parents=True); p.write_text('TEST ONLY exporter')
    # Lookup succeeds on machines without Julia; Start-Process intercepts it.
    p=dest/'fixture-bin/julia.cmd'; p.parent.mkdir(); p.write_text('@exit /b 97\n')
    fixture = r'''
# TEST ONLY INTERCEPTION -- absent from production source.
function Require-Ready {
  Add-Content -LiteralPath (Join-Path $root 'runtime-probes.log') -Value 'mock readiness'
  return [pscustomobject]@{ready=$true}
}
function Get-PSDrive { param($Name) return [pscustomobject]@{Free=1TB} }
function Start-Process {
  param($FilePath,$ArgumentList,$WorkingDirectory,$WindowStyle,$RedirectStandardOutput,$RedirectStandardError,[switch]$PassThru,[switch]$Wait)
  $tokens=@([regex]::Matches($ArgumentList,'"([^"\r\n]+)"')|ForEach-Object {$_.Groups[1].Value})
  $callFile=Join-Path $root ('child-call-'+[Guid]::NewGuid().ToString('N')+'.json')
  [IO.File]::WriteAllText($callFile,(ConvertTo-Json -InputObject $tokens))
  & __PYTHON__ --no-mpi --disable-registry -B (Join-Path $root 'tools/electronics_execution_fixture.py') $root $callFile > $RedirectStandardOutput 2> $RedirectStandardError
  return [pscustomobject]@{ExitCode=$LASTEXITCODE}
}
$env:PATH=(Join-Path $root 'fixture-bin')+';'+$env:PATH
'''.replace('__PYTHON__', "'"+str(python).replace("'", "''")+"'")
    p=dest/'tools/scenario_cli.ps1'; s=p.read_text()
    anchor="if($Action -eq 'menu'){if(!(Menu)){return}}"
    assert s.count(anchor)==1
    p.write_text(s.replace(anchor, fixture+'\n'+anchor), encoding='utf-8')
    save(dest/'FIXTURE.json', {'test_only':True, 'intercepted':['Require-Ready','Start-Process','Get-PSDrive'],
                              'scientific_execution':False, 'source_files':files})

def prepare(root, path, model, events, seed, exporter):
    path.mkdir(parents=True)
    for n in PREPARED: (path/n).write_text('TEST ONLY '+n)
    meta=dict(kind='cs137_prepared_v1', source_pdg=1000551370, model_id=model,
              primary_count=events, seed=seed, files_sha256=hashes(path, PREPARED),
              source_sha256=hashes(root/'transport', PRODUCER),
              upstream_sha256=hashes(root/'.local/transport/LBNL',['fixture.txt']),
              model_sha256=sha(root/f'models/{model}.yaml'), exporter_sha256=sha(root/exporter),
              coordinate_transform={'test_only':True}, grouping_policy=GROUPING,
              clock_policy={'test_only':True}, decay_photon_line_window_keV=[660,663])
    save(path/'prepared.json', meta)

def transport(root, path):
    (path/'truth.lh5').write_text('TEST ONLY not HDF5')
    save(path/'run.json',dict(status='complete',returncode=0,prepared_sha256=sha(path/'prepared.json'), source_lh5_sha256=sha(path/'truth.lh5')))

def extract(root, path):
    m=read(path/'prepared.json'); stream=path/'stream'; stream.mkdir()
    n=m['primary_count']
    (stream/'decays-00000000.jsonl').write_text(''.join(json.dumps({'test_only':True,'id':i})+'\n' for i in range(n)))
    out=dict(kind='cs137_decay_stream_v1',status='complete',model_id=m['model_id'],primary_count=n,
             units=dict(energy='keV',length='mm',time='ns'),source_lh5='../truth.lh5',
             raw_position_unit='m',raw_track_energy_unit='MeV',source_sha256=m['source_sha256'],model_sha256=m['model_sha256'],
             global_decay_id_range=[0,n-1],chunks=[dict(file='decays-00000000.jsonl',count=n,first_global_decay_id=0,sha256=sha(stream/'decays-00000000.jsonl'))])
    for field, file in [('prepared','prepared.json'),('run','run.json'),('source_lh5','truth.lh5'),('geometry','geometry.gdml'),('macro','run.mac'),('config','scenario.json')]: out[field+'_sha256']=sha(path/file)
    for field in ['coordinate_transform','grouping_policy','clock_policy','decay_photon_line_window_keV']: out[field]=m[field]
    save(stream/'manifest.json',out)

def response(root, path, manifest, electronics):
    path.mkdir(parents=True); m=read(manifest); n=m['primary_count']; model=m['model_id']
    p=read(electronics); cfg=read(root/'simulation/readout_demo.json'); del cfg['max_total_samples']
    cfg.update(p['settings']);cfg.update(schema_version=2,expected_primary_count=n)
    # Synthetic positive integration for demo/larger, zero-census smoke regression.
    count={k:0 for k in ['accepted','analog_samples','decay_photons','groups','initial_decays','initial_primaries','line_photons','native_charge_samples','native_failed_groups','readout_rejected','rejected','saturated','zero_deposit_primaries']}
    count.update(initial_decays=n,initial_primaries=n,zero_deposit_primaries=n)
    if n>=500: count.update(groups=1,accepted=1,zero_deposit_primaries=n-1,analog_samples=50000,native_charge_samples=2)
    for file in ARTIFACTS: (path/file).write_text('TEST ONLY '+file)
    shutil.copyfile(electronics,path/'profile-input.json');save(path/'profile.json',p);save(path/'readout-config.json',cfg)
    save(path/'input-contract.json',m);save(path/'input-prepared.json',read(manifest.parent.parent/'prepared.json'))
    save(path/'histograms.json',dict(width_keV=5,normalization_denominators=count))
    sources=hashes(root/'simulation',CONSUMER)
    r=dict(test_fixture_only=True,kind='native_response_v1',input_kind=m['kind'],model_id=model,
           status='completed_provisional_native_response',counts=count,artifacts=hashes(path,ARTIFACTS),
           artifact_bytes={f:(path/f).stat().st_size for f in ARTIFACTS},source_sha256=sources,
           input_sha256=sha(manifest),source_lh5_sha256=m['source_lh5_sha256'],model_sha256=m['model_sha256'],
           parcels=16,seed_family=2609261,diffusion=True,end_drift_when_no_field=False,self_repulsion=False,
           drift_dt_ns=2,nominal_drift_cap_ns=10000,readout_contact_id=1,temperature_K=77,stored_temperature_K=78,
           native_failure_policy='record',charge_csv_policy='examples',trace_selection='first 4 pulse groups in original census order',
           bias_V=500 if model=='AK02' else 700,native_failure_allowlist=['Noncontact endpoint outside crystal','Invalid waveform support'],
           seed_rule='SHA256(seed/global_event_id/raw_row_index/parcel_index), first8 bytes big-endian UInt64; no chunk/group index',
           field_settings=dict(precision_bits=64,min_spacing_mm=0.05,max_spacing_mm=2,sor=1,potential_rechecks=4),
           units=dict(charge='fC',current='nA',voltage='V',energy='keV',time='ns'),grouping_policy=GROUPING,
           profile=p,profile_sha256=sha(electronics),config_sha256=sha(path/'readout-config.json'),
           environment=dict(environment_manifest_sha256=sources['Manifest.toml'],julia_version='1.13.0',ssd_version='0.11.8',project='simulation/Project.toml',manifest='simulation/Manifest.toml'),
           readout_environment=dict(julia_version='1.13.0',pinned_julia_version='1.13.0',json_version='1.9.0',manifest_sha256=sources['Manifest.toml'],project_sha256=sources['Project.toml']),
           boundary_guard=dict(kind='ssd_0_11_8_boundary_guard_v1',installed=True,package_files_modified=False,native_source_sha256='0358c255e37c38f62eee6f1e476c0ed48560708dfcd3d367d2688eaa022232ad'),
           guard_source_sha256=sources['native_boundary_guard.jl'],guard_wrapper_sha256=sources['native_response_guarded.jl'],
           native_drift_and_charge_seconds=0,electronics_seconds=0,solve_replay_readout_export_wall_seconds=0,process_peak_rss_bytes=0)
    save(path/'run.json',r)

def child(root, tokens):
    def val(flag, default=None): return tokens[tokens.index(flag)+1] if flag in tokens else default
    if 'simulation/native_response_guarded.jl' in tokens:
        response(root,root/val('--output'),root/val('--input'),root/val('--profile','simulation/native_readout_profile.json'));return
    assert 'cs137.py' in tokens, tokens
    action=tokens[tokens.index('cs137.py')+1]
    def local_path(flag): return (root/'transport'/val(flag)).resolve()
    if action=='prepare': prepare(root,local_path('--output'),val('--model'),int(val('--events')),int(val('--seed')),val('--exporter').removeprefix('../'))
    elif action=='run': transport(root,local_path('--directory'))
    elif action=='extract': extract(root,local_path('--directory'))
    elif action=='check-stream': assert local_path('--manifest').is_file()
    else: raise AssertionError(tokens)

if __name__=='__main__': child(Path(sys.argv[1]),read(sys.argv[2]))
