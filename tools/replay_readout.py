"""M4b bounded electronics replay. Shared replay_run API for CLI/future GUI."""
import argparse
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

import charge_check as C

SOURCES = ('tools/replay_readout.py', 'tools/charge_check.py', 'tools/replay_readout.ps1',
           'tools/replay_profile.ps1', 'tools/scenario_cli.ps1',
           'simulation/replay_readout.jl', 'simulation/readout.jl',
           'simulation/readout_profiles.jl', 'simulation/readout_demo.json',
           'simulation/Project.toml', 'simulation/Manifest.toml')
V_ATOL, RTOL = 1e-11, 1e-10
MAX_ANALOG = 20_000_000
READOUT_FIELDS = set('accepted adc_code adc_lower_clipped adc_midpoint_V analog_above_adc_range analog_below_adc_range analog_energy_keV below_threshold charge_clipped_at_window charge_end_ns current_balance electronics_state explicit_peak_gate final_charge_C gate_limited input_activity_outside_peak_gate input_sample_count isolated_horizon_ns negative_input nonpositive_peak original_sample_count peak_V peak_gate_end_ns peak_gate_start_ns peak_policy peak_time_ns preamp_max_V preamp_min_V preamp_peak_charge_equivalent_keV readout_end_ns reconstructed_energy_keV rejection_reason saturated tail_truncated_possible tail_window_ns trace_preserves_all_current_runs untruncated_charge_end_ns untruncated_final_charge_keV window_limited'.split())
COUNT_FIELDS = set('initial_primaries zero_deposit_primaries groups native_failed_groups readout_rejected accepted rejected saturated native_charge_samples analog_samples'.split())


def save(path, value):
    # Only driver-owned status is replaced within this newly reserved root.
    temporary=path.with_name(path.name+'.pending')
    with temporary.open('x',encoding='utf-8') as stream:
        stream.write(json.dumps(value,indent=2,allow_nan=False)+'\n')
        stream.flush();os.fsync(stream.fileno())
    temporary.replace(path)


def child(argv, cwd, timeout=600, limit=4*1024*1024):
    """Structured args; bounded joined output, time and child-only thread settings."""
    env = dict(os.environ, JULIA_NUM_THREADS='2', OPENBLAS_NUM_THREADS='1',
               JULIA_PKG_OFFLINE='true', JULIA_LOAD_PATH='@;@stdlib' if os.name=='nt' else '@:@stdlib',
               PYTHONDONTWRITEBYTECODE='1')
    p = subprocess.Popen(argv, cwd=cwd, env=env, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT,
                         creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    data = bytearray(); overflow = threading.Event()
    def drain():
        while True:
            block = p.stdout.read(4096)
            if not block:
                break
            if len(data) + len(block) > limit:
                overflow.set(); p.kill(); break
            data.extend(block)
    t = threading.Thread(target=drain, daemon=True); t.start()
    started = time.monotonic()
    try:
        code = p.wait(timeout=timeout)
    except BaseException as error:
        p.kill(); p.wait(); t.join(); p.stdout.close()
        error.child_receipt = dict(arguments=argv,exit_code=p.returncode,wall_seconds=time.monotonic()-started,
                                   output=data.decode('utf-8',errors='replace'),interrupted_or_timed_out=True)
        raise
    t.join(); p.stdout.close()
    return dict(arguments=argv, exit_code=code, wall_seconds=time.monotonic()-started,
                output=data.decode('utf-8', errors='replace'), output_limit_exceeded=overflow.is_set())


def julia_executable():
    explicit = os.environ.get('JULIA_EXE')
    selected = explicit or shutil.which('julia')
    if not selected:
        selected = str(Path(os.environ.get('USERPROFILE', '')) / '.julia/juliaup/julia-1.13.0+0.x64.w64.mingw32/bin/julia.exe')
    C.require(Path(selected).is_file(), 'Existing Julia not found; set JULIA_EXE. No installation/fallback from explicit path.', 'unsupported_runtime')
    return str(Path(selected).resolve())


def resolve_profile(reader, relative):
    # Use ES/EE's existing strict bundle/ancestry/default contract, never rebase.
    reader.digest(relative)
    watched = {n: reader.digest(n) for n in C.ES_SOURCES | {'tools/replay_profile.ps1', 'tools/electronics_settings.ps1', 'tools/native_run_validation.ps1'}}
    call = child(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                  str(reader.path('tools/replay_profile.ps1')), '-Profile', relative], str(reader.root), timeout=60, limit=1024*1024)
    C.require(call['exit_code'] == 0 and not call['output_limit_exceeded'], 'Settings contract rejected input: '+call['output'], 'invalid_profile')
    result = C.decode(call['output']); selected = result['selection']
    C.equal(result['sources_sha256'], {n: watched[n] for n in C.ES_SOURCES}, 'ES sources')
    for binding in selected['input_bindings']:
        reader.digest(binding['path'], binding['sha256'])
    C.equal(selected['input']['sha256'], reader.digest(relative), 'selected input')
    return selected, call


def expected_config(reader, profile, n):
    settings = C.profile_settings(profile)
    C.require(settings['peak_policy'] == 'signed_input_positive_peak', 'Replay supports the recorded signed-input policy only', 'not_supported')
    c = reader.json('simulation/readout_demo.json')
    C.equal(reader.digest('simulation/readout_demo.json'), C.ES_DEFAULTS['simulation/readout_demo.json'], 'frozen defaults')
    c.pop('max_total_samples'); c.update(settings, schema_version=2, expected_primary_count=n)
    # Fail resource-heavy profiles before worker/calibration, rather than fitting.
    samples = math.ceil(20000*settings['shaping_tau_us']/2)+1
    C.require(3 <= samples <= c['max_samples_per_event'] and (samples-1)*2 <= c['max_window_ns'], 'Injection calibration exceeds supported bounds', 'not_supported')
    if settings["peak_gate_end_ns"] is not None:
        C.require(math.ceil(settings["peak_gate_start_ns"]/2) < math.floor(settings["peak_gate_end_ns"]/2),
                  "Peak gate must contain at least two 2 ns samples", "not_supported")
    return c


def verify_runtime(reader, runtime, inspection, executable):
    C.equal(runtime['julia_version'], '1.13.0', 'actual Julia')
    C.equal(runtime['pinned_julia_version'], '1.13.0', 'manifest Julia')
    C.equal(runtime['json_version'], '1.9.0', 'loaded JSON')
    C.equal(runtime['ssd_loaded'], False, 'SSD load forbidden')
    C.equal(runtime['threads'], 2, 'child thread count')
    C.equal(runtime['active_project'], str(reader.path('simulation/Project.toml').resolve()), 'active project')
    C.equal(runtime['process_source'], str(reader.path('simulation/readout_profiles.jl').resolve()), 'loaded process source')
    C.equal(runtime['readout_module'], 'Main.ReadoutProfiles', 'loaded module identity')
    C.require(Path(runtime['executable']).is_file(), 'Actual Julia executable unavailable', 'unsupported_runtime')
    C.equal(set(runtime['source_sha256']),set(('readout.jl','readout_profiles.jl','readout_demo.json','replay_readout.jl')),'loaded readout source inventory')
    for name, value in runtime['source_sha256'].items():
        reader.digest('simulation/'+name, value)
    for name in ('Project.toml', 'Manifest.toml'):
        reader.digest('simulation/'+name, runtime['project_sha256' if name == 'Project.toml' else 'manifest_sha256'])
    for d in inspection['detectors']:
        C.equal(runtime['json_source_sha256'], d['provenance']['recorded_readout_environment']['json_source_sha256'], 'loaded JSON source identity')
    runtime['launcher_executable'] = executable
    runtime['launcher_sha256'] = hashlib.sha256(Path(executable).read_bytes()).hexdigest()
    runtime['executable_sha256'] = hashlib.sha256(Path(runtime['executable']).read_bytes()).hexdigest()


def near(a, b, label, atol=V_ATOL):
    C.number(a, label); C.number(b, label)
    C.require(math.isclose(a, b, rel_tol=RTOL, abs_tol=atol), label+': tolerance exceeded', 'invalid_worker_output')


def finite_tree(value):
    if type(value) in (int, float):
        C.number(value, 'worker value')
    elif isinstance(value, dict):
        for v in value.values(): finite_tree(v)
    elif isinstance(value, list):
        for v in value: finite_tree(v)


def verify_outputs(reader, out, request, runtime):
    """Independent primary/group reconciliation, identity/flags, ADC and trace checks."""
    report = out.json('worker/report.json')
    C.equal(report['status'], 'worker_complete_untrusted', 'worker terminal status')
    C.equal(report['kind'], 'electronics_replay_worker_v1', 'worker receipt kind')
    # Probe and worker both independently assert the actual loaded runtime.
    C.equal(report['runtime'], {k:v for k,v in runtime.items() if k not in ('launcher_executable','launcher_sha256','executable_sha256')}, 'probe/worker runtime')
    expected = {d['model']+'/'+n for d in request['detectors'] for n in ('scalars.jsonl','traces.jsonl')}
    C.equal(set(report['artifacts']), expected, 'worker artifact inventory')
    actual = {p.relative_to(out.path('worker')).as_posix() for p in out.path('worker').rglob('*') if p.is_file()}
    C.equal(actual, expected | {'report.json'}, 'actual worker files')
    C.equal(set(report['detectors']), {d['model'] for d in request['detectors']}, 'worker detectors')
    for name,h in report['artifacts'].items(): out.digest('worker/'+name,h)
    for d in request['detectors']:
        m=d['model']; info=report['detectors'][m]; c=d['config']; cal=info['calibration']
        C.equal(set(info['counts']),COUNT_FIELDS,'counts fields')
        C.equal(info['config'], c, 'resolved worker config')
        finite_tree(info)
        C.equal(cal['method'], 'single delta-charge injection at t=0; sampled analog peak; fixed across events', 'fixed injection calibration')
        near(cal['charge_C'], c['calibration_energy_keV']*1000/d['eion']*1.602176634e-19, 'injection charge', atol=1e-25)
        near(cal['volts_per_keV'], cal['peak_V']/c['calibration_energy_keV'], 'fixed slope')
        C.require(cal['volts_per_keV']>0, 'Positive injection slope required')
        C.equal(cal['energy_keV'], c['calibration_energy_keV'], 'injection energy')
        C.equal(cal['ionisation_energy_eV'], d['eion'], 'injection eion')
        C.equal(cal['time_step_ns'], d['dt'], 'injection grid')
        lsb=c['adc_full_scale_V']/2**c['adc_bits']; C.equal(cal['adc_lsb_V'],lsb,'ADC LSB')
        traces=iter(out.jsonl('worker/'+m+'/traces.jsonl'))
        signals=iter(out.csv('inputs/'+m+'/signals.csv', C.SIGNAL_COLUMNS))
        counts=dict.fromkeys(info['counts'],0)
        for old, new in itertools.zip_longest(out.jsonl('inputs/'+m+'/scalars.jsonl'), out.jsonl('worker/'+m+'/scalars.jsonl')):
            C.require(old is not None and new is not None, 'Incomplete/extra scalar ledger', 'invalid_worker_output')
            finite_tree(new)
            if old['record_kind']=='decay':
                C.equal(new,old,'primary ledger'); counts['initial_primaries']+=1; counts['zero_deposit_primaries']+=old['zero_deposit']; continue
            counts['groups']+=1
            if old.get('status')=='native_transport_failed':
                C.equal(new,old,'native failure nulls/reason'); counts['native_failed_groups']+=1; counts['rejected']+=1; continue
            C.equal({k:v for k,v in new.items() if k not in ('readout','accepted','rejection_reason','trace_saved')},
                    {k:v for k,v in old.items() if k not in ('readout','accepted','rejection_reason','trace_saved')}, 'original pulse metadata/endpoint flags')
            r=new['readout']; C.equal(set(r),READOUT_FIELDS,'readout fields')
            n=old['readout']['input_sample_count']; q=[]
            for k in range(n):
                row=next(signals,None); C.require(row is not None,'Missing snapshot charge')
                C.equal([C.csv_identity(x,'signal ID') for x in row[:3]],[old['event_id'],old['global_decay_id'],old['group_id']], 'snapshot signal IDs')
                C.close(float(row[3]),k*d['dt'],'snapshot grid'); q.append(C.number(float(row[4]),'signed charge'))
            C.equal(r['input_sample_count'],n,'complete charge count'); C.equal(r['original_sample_count'],50000,'half-open analog samples')
            for k,v in dict(readout_end_ns=99998,charge_end_ns=(n-1)*2,isolated_horizon_ns=100000,
                            electronics_state='reset_nominal_isolated_window',charge_clipped_at_window=False,
                            tail_truncated_possible=True,untruncated_charge_end_ns=(n-1)*2,untruncated_final_charge_keV=q[-1]).items(): C.equal(r[k],v,k)
            C.equal(r['current_balance']['passed'],True,'balance'); factor=1000/d['eion']*1.602176634e-19
            near(r['final_charge_C'],q[-1]*factor,'signed final C',atol=1e-25)
            peak=r['peak_V']; code=0 if peak<=0 else 2**c['adc_bits']-1 if peak>=c['adc_full_scale_V'] else math.floor(peak/lsb)
            reason='saturated' if peak>=c['adc_full_scale_V'] else 'peak_at_window_end' if r['window_limited'] else 'peak_at_gate_boundary' if r['gate_limited'] else 'below_threshold' if peak<c['threshold_V'] else None
            C.equal(r['peak_policy'],c['peak_policy'],'policy'); C.equal(r['negative_input'],any(v<0 for v in q),'signed flag')
            C.equal(r['adc_code'],code,'independent peak ADC'); C.equal(r['accepted'],reason is None,'independent selection')
            C.equal(r['adc_midpoint_V'],(code+.5)*lsb,'ADC midpoint')
            for key,value in dict(saturated=peak>=c['adc_full_scale_V'],below_threshold=peak<c['threshold_V'],
                                  nonpositive_peak=peak<=0,adc_lower_clipped=peak<0,window_limited=r['peak_time_ns']==99998,
                                  explicit_peak_gate=c['peak_gate_end_ns'] is not None).items():C.equal(r[key],value,key)
            lo=c['peak_gate_start_ns'] if c['peak_gate_end_ns'] is not None else 0
            hi=c['peak_gate_end_ns'] if c['peak_gate_end_ns'] is not None else 99998
            C.require(lo<=r['peak_time_ns']<=hi,'Peak outside gate')
            C.equal(r['gate_limited'],peak>0 and c['peak_gate_end_ns'] is not None and r['peak_time_ns'] in (math.ceil(lo/2)*2,math.floor(hi/2)*2),'gate boundary')
            C.equal(r['peak_gate_start_ns'],math.ceil(lo/2)*2,'effective gate start')
            C.equal(r['peak_gate_end_ns'],math.floor(hi/2)*2,'effective gate end')
            C.equal(r['rejection_reason'],reason,'independent reason'); C.equal(new['accepted'],r['accepted'],'outer acceptance')
            C.equal(new['rejection_reason'],reason,'outer reason'); C.equal(new['trace_saved'],True,'complete trace selection')
            near(r['analog_energy_keV'],peak/cal['volts_per_keV'],'analog energy')
            C.equal(r['reconstructed_energy_keV'],None,'rejected Erec') if reason else near(r['reconstructed_energy_keV'],(code+.5)*lsb/cal['volts_per_keV'],'ADC Erec')
            tr=next(traces,None); C.require(tr is not None,'Missing output trace')
            finite_tree(tr)
            C.equal({k:v for k,v in tr.items() if k!='trace'}, {k:old[k] for k in ('event_id','global_decay_id','group_id','origin_time_ns')},'trace clock/identity')
            t=tr['trace']; C.equal(set(t),set('time_ns induced_charge_fC current_bin_start_ns current_bin_end_ns current_nA preamp_V shaped_V'.split()),'trace fields')
            length=len(t['time_ns']); C.require(2<=length<=c['trace_max_points'] and all(len(v)==length for v in t.values()),'Trace bounds')
            C.equal(t['time_ns'][0],0,'trace start'); C.equal(t['time_ns'][-1],99998,'trace half-open end')
            previous=-1
            for j,tick in enumerate(t['time_ns']):
                k=round(tick/2); C.equal(tick,k*2,'trace grid'); C.require(previous<k<50000,'Trace order'); previous=k
                near(t['induced_charge_fC'][j],q[min(k,n-1)]*factor*1e15,'trace signed charge',atol=1e-10)
                current=(q[k]-q[k-1])*factor/2*1e18 if 0<k<n else 0
                near(t['current_nA'][j],current,'original-bin current',atol=1e-10)
                C.equal(t['current_bin_start_ns'][j],max(0,k-1)*2,'current bin start'); C.equal(t['current_bin_end_ns'][j],tick,'current bin end')
            C.require(r['peak_time_ns'] in t['time_ns'],'Trace must retain peak')
            near(t['shaped_V'][t['time_ns'].index(r['peak_time_ns'])],peak,'sampled peak V')
            counts['accepted']+=r['accepted']; counts['rejected']+=not r['accepted']; counts['readout_rejected']+=not r['accepted']
            counts['saturated']+=r['saturated']; counts['native_charge_samples']+=n; counts['analog_samples']+=50000
        C.require(next(signals,None) is None and next(traces,None) is None,'Extra charge/trace rows')
        C.equal(counts,info['counts'],'independent counts'); C.equal(counts['initial_primaries'],d['primary_count'],'all primary denominator')
    out.recheck()
    return report


def replay_run(root, name, replay_name, detector='both', electronics_profile=None, dry_run=False):
    """Single shared backend. Failures never promote a child receipt to completion."""
    result=dict(schema_version=1,kind='electronics_replay_v1',status='blocked',source_name=name,
                replay_name=replay_name,verification_final=False,runtime_verified='NOT_CHECKED',
                dry_run=dry_run, findings=[], limitations=[
                    'Synthetic noiseless electronics; software reuse, not experimental collection validation.',
                    'Constant terminal charge/zero tail current is the original assumption, not recovered missing charge.',
                    'Native endpoint/step-limit flags and failures retained; all zero primaries remain.',
                    'Analog numerical grid and peak ADC, not waveform acquisition. M3 hardware/noise and M5 recovery deferred.'])
    dest=None; started=time.monotonic()
    try:
        C.require(sys.version_info >= (3,10),'Existing Python 3.10+ required','unsupported_runtime')
        result['python_runtime']=dict(executable=sys.executable,version=sys.version)
        C.require(isinstance(replay_name,str) and __import__('re').fullmatch('[A-Za-z0-9_-]{1,80}',replay_name),'Unsafe replay name','unsafe_path')
        C.require(electronics_profile is None or isinstance(electronics_profile,str) and bool(electronics_profile),
                  'Explicit electronics profile must be a nonempty relative path','invalid_profile')
        with C.inspection_session(root,name,detector) as (reader,inspection):
            result['inspection']=inspection
            C.require(inspection['storage_complete'] and inspection['producer_compatible'], 'Complete compatible charge required; see inspection findings', 'source_ineligible')
            C.require(sum(d['stored_samples'] for d in inspection['detectors'])<=2_000_000,
                      'Replay total charge sample budget exceeded','not_supported')
            run='.local/runs/'+name
            inventory=sorted(p.relative_to(reader.root).as_posix() for p in reader.path(run).rglob('*') if p.is_file())
            lockstat=reader.path(run+'/run.lock').stat()
            for n in inventory:
                if n!=run+'/run.lock': reader.digest(n)
            current={n:reader.digest(n) for n in SOURCES}
            selected=None
            if electronics_profile:
                selected,call=resolve_profile(reader,electronics_profile); result['settings_check']=call
            parent=reader.json(run+'/run.json'); configs=[]
            for d in inspection['detectors']:
                m=d['detector']; original=reader.json(run+'/'+m+'/response/run.json')
                profile=selected['profile'] if selected else original['profile']
                config=expected_config(reader,profile,parent['events_per_model'])
                if selected: C.equal(selected['configuration'],dict(config,expected_primary_count=None),'independent ES config')
                configs.append(dict(model=m,profile=profile,config=config,eion=original['ionisation_energy_eV'],dt=original['drift_dt_ns'],primary_count=parent['events_per_model']))
            C.require(sum(d['counts']['groups']-d['counts']['native_failed_groups'] for d in inspection['detectors'])*50000<=MAX_ANALOG,'Replay analog sample budget exceeded','not_supported')
            target=reader.path('.local/replays/'+replay_name)
            C.require(not target.exists(),'Replay destination already exists; no overwrite/resume','output_exists')
            result.update(output=target.relative_to(reader.root).as_posix(),configuration=configs,new_source_sha256=current,
                          electronics_selection=selected,original_parent=parent)
            if dry_run:
                reader.recheck(); result.update(status='planned',verification_final=True,scientific_workers_launched=0,output_reserved=False)
                return result
            exe=julia_executable()
            argv=[exe,'--startup-file=no','--project=simulation','--threads=2','--compiled-modules=existing',str(reader.path('simulation/replay_readout.jl'))]
            probe=child([*argv,'--probe'],str(reader.root),timeout=60,limit=65536); result['runtime_probe']=probe
            C.require(probe['exit_code']==0 and not probe['output_limit_exceeded'],'Runtime probe failed: '+probe['output'],'unsupported_runtime')
            runtime=C.decode(probe['output']); verify_runtime(reader,runtime,inspection,exe)
            result.update(runtime=runtime,runtime_verified=True)
            reader.recheck()
            target.parent.mkdir(exist_ok=True); reader.path('.local/replays/'+replay_name) # reject linked parent after creation
            target.mkdir(); dest=target; result.update(status='running',output_reserved=True)
            save(dest/'run.json',result)
            (dest/'inputs').mkdir()
            shutil.copyfile(reader.path(run+'/run.json'),dest/'inputs/parent-run.json')
            for d in configs:
                folder=dest/'inputs'/d['model']; folder.mkdir(parents=True)
                d['input_sha256']={}
                for n in ('signals.csv','scalars.jsonl'):
                    source=run+'/'+d['model']+'/response/'+n
                    shutil.copyfile(reader.path(source),folder/n)
                    C.equal(hashlib.sha256((folder/n).read_bytes()).hexdigest(),reader.digest(source),'extracted exact input')
                    d['input_sha256'][n]=reader.digest(source)
                for n in ('run.json','profile-input.json','readout-config.json'):
                    shutil.copyfile(reader.path(run+'/'+d['model']+'/response/'+n),folder/('original-'+n))
            request=dict(schema_version=1,kind='electronics_replay_request_v1',source_sha256=current,detectors=configs)
            save(dest/'request.json',request)
            out=C.Reader(dest)
            out.digest('request.json')
            for copied in (dest/'inputs').rglob('*'):
                if copied.is_file(): out.digest(copied.relative_to(dest).as_posix())
            for d in configs:
                for n,h in d['input_sha256'].items():out.digest('inputs/'+d['model']+'/'+n,h)
            execution=child([*argv,'--request',str(dest/'request.json')],str(reader.root)); result['child']=execution
            (dest/'worker.log').write_text(execution['output'],encoding='utf-8')
            C.require(execution['exit_code']==0 and not execution['output_limit_exceeded'],'Electronics child failed; partial evidence retained','child_failed')
            worker=verify_outputs(reader,out,request,runtime)
            # Last source and derived-input checks remain inside the original lease.
            reader.recheck(); out.digest('worker.log'); out.recheck()
            C.equal(sorted(p.relative_to(reader.root).as_posix() for p in reader.path(run).rglob('*') if p.is_file()),inventory,'source file inventory')
            now=reader.path(run+'/run.lock').stat(); C.equal((now.st_size,now.st_mtime_ns),(lockstat.st_size,lockstat.st_mtime_ns),'source lock metadata')
            C.equal(hashlib.sha256(Path(exe).read_bytes()).hexdigest(),runtime['launcher_sha256'],'launcher freeze')
            C.equal(hashlib.sha256(Path(runtime['executable']).read_bytes()).hexdigest(),runtime['executable_sha256'],'runtime executable freeze')
            result.update(status='completed_with_native_failures' if any(v['counts']['native_failed_groups'] for v in worker['detectors'].values()) else 'completed',
                          verification_final=True,detectors=worker['detectors'],
                          verified_artifacts={n:dict(sha256=h,bytes=size,mtime_ns=out.stamps[n][1]) for n,(h,size) in out.watched.items()},
                          source_snapshot={n:dict(sha256=h,bytes=size,mtime_ns=reader.stamps[n][1]) for n,(h,size) in reader.watched.items()},
                          wall_seconds=time.monotonic()-started,completion_authority='Python driver after independent verification under source lease')
            save(dest/'run.json',result)
    except BaseException as error:
        if isinstance(error,(SystemExit,KeyboardInterrupt)) and dest is None: raise
        result.update(status='failed' if dest else 'blocked',verification_final=False,runtime_verified=False)
        result['findings'].append(C.finding(error))
        if hasattr(error,'child_receipt'):
            result['interrupted_child']=error.child_receipt
            if dest:(dest/'worker.log').write_text(error.child_receipt['output'],encoding='utf-8')
        if 'inspection' in result:
            result['inspection'].update(verification_final=False,storage_complete=False,producer_compatible=False)
            for d in result['inspection']['detectors']: d.update(verification_final=False,storage_complete=False,producer_compatible=False,observations_status='nonfinal')
        if dest: save(dest/'run.json',result)
    return result


def summary(result):
    keys=('schema_version','kind','status','source_name','replay_name','output','dry_run',
          'runtime_verified','verification_final','output_reserved','scientific_workers_launched',
          'configuration','detectors','findings','limitations','wall_seconds')
    brief={k:result[k] for k in keys if k in result}
    if 'inspection' in result:
        brief['source_inspection']={k:result['inspection'][k] for k in ('storage_complete','producer_compatible','verification_final')}
    if result.get('output_reserved'):brief['receipt']=result['output']+'/run.json'
    return brief


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    p.add_argument('--name',required=True); p.add_argument('--replay-name',required=True)
    p.add_argument('--detector',choices=('AK02','SAP22','both'),default='both')
    p.add_argument('--electronics-profile'); p.add_argument('--dry-run',action='store_true'); p.add_argument('--json',action='store_true')
    a=p.parse_args(argv)
    result=replay_run(Path(__file__).resolve().parents[1],a.name,a.replay_name,a.detector,a.electronics_profile,a.dry_run)
    if a.json: print(json.dumps(summary(result),allow_nan=False,separators=(',',':')))
    else:
        print('Electronics replay: '+result['status']+'; '+result.get('output','no output reserved'))
        for d,v in result.get('detectors',{}).items():print(d+': '+json.dumps(v['counts'],sort_keys=True))
        for f in result['findings']:print(f['code']+': '+f['detail'])
    return 0 if result['status'] in ('planned','completed','completed_with_native_failures') else 2


if __name__=='__main__': sys.exit(main())
