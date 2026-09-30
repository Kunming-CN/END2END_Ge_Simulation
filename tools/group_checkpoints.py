"""Opt-in M5a checkpoints for NEW saved-charge electronics derivatives only."""
import csv
from contextlib import ExitStack, contextmanager, nullcontext
import hashlib
import io
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import time
import uuid

import charge_check as C
import replay_readout as R

KIND = 'saved_charge_group_replay_v1'
SOURCES = (*R.SOURCES, 'tools/group_checkpoints.py', 'simulation/replay_groups.jl')
TERMINAL = ('completed', 'completed_with_native_failures')


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)+'\n').encode('utf-8')


def digest_bytes(data):
    return hashlib.sha256(data).hexdigest()


def write_bytes(path, data):
    with path.open('xb') as stream:
        stream.write(data); stream.flush(); os.fsync(stream.fileno())


def write_json(path, value):
    data=encoded(value);C.require(len(data)<=C.MAX_JSON,'JSON document exceeds checkpoint bound','not_supported')
    write_bytes(path, data)


def status(path, value):
    # A dead writer's temporary status is retained, never reused or removed.
    pending = path.with_name(path.name+'.pending-'+uuid.uuid4().hex)
    write_json(pending, value); os.replace(pending, path)


@contextmanager
def failure_status(dest,result):
    """Publish failure while the output lease is still held."""
    try:yield
    except BaseException as error:
        result.update(status='failed',verification_final=False)
        item=C.finding(error)
        if item not in result['findings']:result['findings'].append(item)
        status(dest/'run.json',result)
        raise


def stamps(reader, names):
    result = {}
    for name in names:
        h = reader.digest(name); size, mtime = reader.stamps[name]
        result[name] = dict(sha256=h, bytes=size, mtime_ns=mtime)
    return result


def check_stamps(reader, records):
    for name, item in records.items():
        reader.digest(name, item['sha256'], item['bytes'])
        C.equal(reader.stamps[name][1], item['mtime_ns'], 'immutable mtime '+name)


def inventory(path):
    return sorted(p.relative_to(path).as_posix() for p in path.rglob('*') if p.is_file())


def witness_path(path):
    return path.parent.parent/'receipts'/path.parent.name/(path.name+'.json')


def commit(stage, destination, binding):
    """Receipt is fsynced with data before atomic directory rename; never replace.

    A crash after rename and before COMMIT rename is conservatively refused on
    resume. The bound PENDING record remains evidence, never orphan adoption.
    """
    C.require(not destination.exists(), 'Committed destination exists', 'output_exists')
    data = C.Reader(stage)
    files = inventory(stage)
    for name in files:
        with data.path(name).open('r+b') as stream: os.fsync(stream.fileno())
    receipt = dict(schema_version=1, kind='saved_charge_group_commit_v1', binding=binding,
                   artifacts=stamps(data, files))
    write_json(stage/'PENDING.json', receipt)
    destination.parent.mkdir(exist_ok=True)
    os.rename(stage, destination)
    os.rename(destination/'PENDING.json', destination/'COMMIT.json')
    witness=witness_path(destination)
    pending=witness.with_name(witness.name+'.pending-'+uuid.uuid4().hex[:12])
    write_json(pending,dict(kind='saved_charge_commit_witness_v1',binding=binding,
                           commit=stamps(C.Reader(destination),['COMMIT.json'])['COMMIT.json']))
    os.rename(pending,witness)
    return receipt


def committed(path, binding):
    witness=witness_path(path)
    C.require(witness.is_file(),'Canonical data has no separate immutable commit witness; preserve and refuse','uncommitted_boundary')
    evidence=C.Reader(witness.parent).json(witness.name)
    C.fields(evidence,('kind','binding','commit'),'commit witness')
    C.equal(evidence['kind'],'saved_charge_commit_witness_v1','witness kind')
    C.equal(evidence['binding'],binding,'witness binding')
    C.require((path/'COMMIT.json').is_file(),
              'Canonical data has no COMMIT receipt; preserve evidence and refuse: '+str(path), 'uncommitted_boundary')
    reader = C.Reader(path); receipt = reader.json('COMMIT.json')
    check_stamps(reader,{'COMMIT.json':evidence['commit']})
    C.fields(receipt, ('schema_version','kind','binding','artifacts'), 'group commit')
    C.equal(receipt['schema_version'], 1, 'commit schema')
    C.equal(receipt['kind'], 'saved_charge_group_commit_v1', 'commit kind')
    C.equal(receipt['binding'], binding, 'immutable commit binding')
    C.equal(inventory(path), sorted([*receipt['artifacts'],'COMMIT.json']), 'commit file inventory')
    check_stamps(reader, receipt['artifacts']); reader.recheck()
    return reader, receipt


def config_for(manifest, model):
    return next(d for d in manifest['detectors'] if d['model']==model)


def raw_runtime(runtime):
    return {k:v for k,v in runtime.items() if k not in ('launcher_executable','launcher_sha256','executable_sha256')}


def binding(manifest_hash, phase, key):
    return dict(manifest_sha256=manifest_hash, phase=phase, key=key)


def charge_payloads(out, detectors):
    """Rebuild exact expected groups from the full frozen ledger, never disk census."""
    for d in detectors:
        m=d['model']; rows=iter(out.csv('inputs/'+m+'/signals.csv',C.SIGNAL_COLUMNS))
        seen=set()
        for record in out.jsonl('inputs/'+m+'/scalars.jsonl'):
            if record['record_kind']=='decay': continue
            C.equal(record['record_kind'],'pulse','source scalar kind')
            ids=[C.integer(record[n],n) for n in ('event_id','global_decay_id','group_id')]
            C.require(tuple(ids) not in seen,'Duplicate expected group identity'); seen.add(tuple(ids))
            n=0 if record.get('status')=='native_transport_failed' else C.integer(record['readout']['input_sample_count'],'samples',2,500000)
            stream=io.StringIO(newline=''); writer=csv.writer(stream,lineterminator='\n'); writer.writerow(C.SIGNAL_COLUMNS)
            for k in range(n):
                row=next(rows,None); C.require(row is not None,'Missing charge sample')
                C.equal([C.csv_identity(v,'group ID') for v in row[:3]],ids,'charge-group sample identities')
                C.close(float(row[3]),k*d['dt'],'charge-group grid')
                C.number(float(row[4]),'signed charge'); writer.writerow(row)
            files={'scalars.jsonl':encoded(record),'signals.csv':stream.getvalue().encode('utf-8')}
            identity=dict(model=m,event_id=ids[0],global_decay_id=ids[1],group_id=ids[2],
                origin_time_ns=record['origin_time_ns'],group=record['group'],dt_ns=d['dt'],
                ionisation_energy_eV=d['eion'],readout_contact_id=d['readout_contact_id'],model_sha256=d['model_sha256'],
                original_input_sha256=d['input_sha256'],record_sha256=digest_bytes(files['scalars.jsonl']),
                configuration_sha256=digest_bytes(encoded(d['config'])))
            key=m+'-e'+str(ids[0])+'-d'+str(ids[1])+'-g'+str(ids[2])
            yield dict(key=key,model=m,identity=identity,identity_sha256=digest_bytes(encoded(identity)),samples=n,
                       files={name:dict(sha256=digest_bytes(data),bytes=len(data)) for name,data in files.items()}),files
        C.require(next(rows,None) is None,'Extra source charge samples')


def verify_calibration(path, d, runtime):
    reader=C.Reader(path); info=reader.json('calibration.json')
    C.fields(info,('kind','model','config','runtime','calibration','calibration_seconds'),'calibration snapshot')
    C.equal(info['kind'],'saved_charge_calibration_v1','calibration kind'); C.equal(info['model'],d['model'],'calibration model')
    C.equal(info['runtime'],raw_runtime(runtime),'calibration runtime')
    R.verify_detector_outputs(dict(d,primary_count=0),dict(info,counts=dict.fromkeys(R.COUNT_FIELDS,0)),[],[],[],[])
    reader.recheck(); return info


def verify_group(charge, result, group, d, runtime, calibration):
    out=C.Reader(result); info=out.json('result.json')
    C.fields(info,('kind','key','runtime','config','calibration_sha256','counts','electronics_seconds'),'group result')
    C.equal(info['kind'],'saved_charge_electronics_group_v1','group result kind')
    C.equal(info['key'],group['key'],'result identity'); C.equal(info['runtime'],raw_runtime(runtime),'result runtime')
    C.equal(info['calibration_sha256'],digest_bytes(encoded(calibration)),'fixed calibration binding')
    old=C.Reader(charge)
    R.verify_detector_outputs(dict(d,primary_count=0),dict(info,calibration=calibration['calibration']),
        old.jsonl('scalars.jsonl'),out.jsonl('scalars.jsonl'),out.jsonl('traces.jsonl'),old.csv('signals.csv',C.SIGNAL_COLUMNS))
    C.equal(info['counts']['groups'],1,'one group result')
    out.recheck(); old.recheck(); return info


def validate_saved(reader, dest, inspection, name, replay_name, detector):
    out=C.Reader(dest); initial=out.json('INITIAL.json')
    C.fields(initial,('schema_version','kind','manifest','inputs'),'initial receipt')
    C.equal(initial['kind'],KIND,'checkpoint kind'); C.equal(initial['schema_version'],1,'initial schema')
    check_stamps(out,{'manifest.json':initial['manifest'],**initial['inputs']})
    manifest=out.json('manifest.json'); mh=out.digest('manifest.json')
    C.equal(manifest['kind'],KIND,'manifest kind'); C.equal(manifest['schema_version'],1,'manifest schema')
    C.equal((manifest['source_name'],manifest['replay_name']),(name,replay_name),'requested source/output')
    C.equal(manifest['detector_selection'],detector,'recorded detector selection')
    C.equal(inventory(dest/'inputs'),sorted(n.removeprefix('inputs/') for n in initial['inputs']),'input snapshot inventory')
    check_stamps(reader,manifest['source_snapshot'])
    run=reader.path('.local/runs/'+name)
    C.equal(['.local/runs/'+name+'/'+n for n in inventory(run)],manifest['source_inventory'],'source-run inventory')
    lock=reader.path('.local/runs/'+name+'/run.lock').stat()
    C.equal(dict(bytes=lock.st_size,mtime_ns=lock.st_mtime_ns),manifest['source_lock_metadata'],'source lease file metadata')
    for d in manifest['detectors']:
        C.equal(out.json('inputs/'+d['model']+'/effective-profile.json'),d['profile'],'recorded copied profile')
        C.equal(out.json('inputs/'+d['model']+'/effective-config.json'),d['config'],'recorded copied configuration')
        C.equal(R.expected_config(reader,d['profile'],d['primary_count']),d['config'],'recorded copied profile/config')
        C.equal(d['primary_count'],manifest['original_parent']['events_per_model'],'primary count')
        for f,h in d['input_sha256'].items():out.digest('inputs/'+d['model']+'/'+f,h)
        original=out.json('inputs/'+d['model']+'/original-run.json')
        C.equal(d['model_sha256'],original['model_sha256'],'model provenance')
        C.equal(d['readout_contact_id'],original['readout_contact_id'],'contact provenance')
    C.equal([d['model'] for d in manifest['detectors']],[d['detector'] for d in inspection['detectors']],'selected detector set')
    payloads=charge_payloads(out,manifest['detectors']); expected=[]
    for group,files in payloads: expected.append(group)
    C.equal(expected,manifest['groups'],'full immutable expected group ledger')
    runtime=manifest['runtime']
    # No runtime lookup/probe on saved-progress inspection or completed no-op.
    for field,h in [('launcher_executable','launcher_sha256'),('executable','executable_sha256')]:
        C.equal(hashlib.sha256(Path(runtime[field]).read_bytes()).hexdigest(),runtime[h],'recorded executable hash')
    calibrations={}; done=[]
    expected_keys={g['key'] for g in expected}
    for phase in ('charge','electronics'):
        path=dest/phase
        C.require(path.is_dir(),'Missing committed inventory directory','missing_file')
        C.require(all(p.is_dir() and p.name in expected_keys for p in path.iterdir()),'Extra/unknown committed group','extra_group')
        witnesses=dest/'receipts'/phase
        C.require(witnesses.is_dir(),'Missing commit witness directory','missing_file')
        C.require(all(p.is_file() and (p.name.removesuffix('.json') in expected_keys or '.json.pending-' in p.name) for p in witnesses.iterdir()),'Extra/unknown commit witness','extra_group')
    C.require(all(p.is_dir() and p.name in {d['model'] for d in manifest['detectors']} for p in (dest/'calibration').iterdir()),'Extra calibration')
    C.require(all(p.is_file() and (p.name.removesuffix('.json') in {d['model'] for d in manifest['detectors']} or '.json.pending-' in p.name)
                  for p in (dest/'receipts/calibration').iterdir()),'Extra calibration witness')
    for d in manifest['detectors']:
        p=dest/'calibration'/d['model']
        if p.exists() or witness_path(p).exists():
            committed(p,binding(mh,'calibration',d['model']))
            calibrations[d['model']]=verify_calibration(p,d,runtime)
    for g in expected:
        charge=dest/'charge'/g['key']; result=dest/'electronics'/g['key']
        if charge.exists() or witness_path(charge).exists():
            cr,receipt=committed(charge,binding(mh,'charge',g['key']))
            C.equal(set(receipt['artifacts']),set(g['files']),'charge artifact set')
            for f,item in g['files'].items(): cr.digest(f,item['sha256'],item['bytes'])
        if result.exists() or witness_path(result).exists():
            C.require(charge.exists() and g['model'] in calibrations,'Result without bound charge/calibration')
            committed(result,binding(mh,'electronics',g['key']))
            verify_group(charge,result,g,config_for(manifest,g['model']),runtime,calibrations[g['model']]); done.append(g['key'])
    out.recheck(); reader.recheck()
    return manifest,mh,calibrations,done


def run_session(root, dest, manifest, mh, runtime, groups, attempt, callback):
    """One bounded Julia process; driver ACKs each independently checked commit."""
    request=dict(kind='saved_charge_group_session_v1',schema_version=1,root=str(dest),
                 source_sha256=manifest['source_sha256'],runtime=raw_runtime(runtime),detectors=manifest['detectors'],groups=groups,
                 calibration_bindings={d['model']:dict(file_sha256=hashlib.sha256((dest/'calibration'/d['model']/'calibration.json').read_bytes()).hexdigest(),
                     canonical_sha256=digest_bytes(encoded(C.Reader(dest/'calibration'/d['model']).json('calibration.json'))))
                     for d in manifest['detectors'] if (dest/'calibration'/d['model']/'calibration.json').is_file()})
    write_json(attempt/'session.json',request)
    argv=[runtime['launcher_executable'],'--startup-file=no','--project=simulation','--threads=2','--compiled-modules=existing',
          str(root/'simulation/replay_groups.jl'),'--session',str(attempt/'session.json')]
    env=dict(os.environ,JULIA_NUM_THREADS='2',OPENBLAS_NUM_THREADS='1',JULIA_PKG_OFFLINE='true',
             JULIA_LOAD_PATH='@;@stdlib' if os.name=='nt' else '@:@stdlib',PYTHONDONTWRITEBYTECODE='1')
    proc=subprocess.Popen(argv,cwd=root,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                          creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    messages=queue.Queue(); count=[0]; started=time.monotonic()
    def drain():
        try:
            with (attempt/'worker.log').open('xb') as log:
                while True:
                    line=proc.stdout.readline(65537)
                    if not line:break
                    count[0]+=len(line); log.write(line); log.flush()
                    if len(line)>65536 or count[0]>4*1024*1024:
                        messages.put(RuntimeError('Worker protocol/output limit')); proc.kill();break
                    messages.put(line)
        except BaseException as error:messages.put(error)
        finally:messages.put(None)
    thread=threading.Thread(target=drain,daemon=True);thread.start()
    events=[]; terminal=False
    try:
        while True:
            remaining=600-(time.monotonic()-started)
            C.require(remaining>0,'Worker time limit','child_failed')
            try: line=messages.get(timeout=remaining)
            except queue.Empty:raise C.Rejected('child_failed','Worker time limit')
            if line is None:break
            if isinstance(line,BaseException):raise line
            text=line.decode('utf-8',errors='strict').strip()
            if not text.startswith('{'):continue # bounded diagnostic text is kept in log
            event=C.decode(text); events.append(event)
            if event.get('kind')=='session_done': terminal=True;continue
            C.require(event.get('kind')=='group_ready','Unexpected worker event','invalid_worker_output')
            ack=callback(event)
            proc.stdin.write(encoded(dict(kind='committed',**(ack or {}))));proc.stdin.flush()
        code=proc.wait(timeout=max(1,600-(time.monotonic()-started)))
        C.require(code==0 and terminal,'Electronics worker failed; staged evidence retained','child_failed')
        return dict(arguments=argv,exit_code=code,wall_seconds=time.monotonic()-started,events=events)
    finally:
        if proc.poll() is None:proc.kill();proc.wait()
        thread.join(timeout=5)
        proc.stdin.close();proc.stdout.close()
        write_json(attempt/'execution.json',dict(arguments=argv,exit_code=proc.returncode,wall_seconds=time.monotonic()-started))


def aggregate(reader,dest,manifest,mh,calibrations,attempt):
    stage=attempt/'final';stage.mkdir();worker=stage/'worker';worker.mkdir()
    report=dict(kind='electronics_replay_worker_v1',status='worker_complete_untrusted',runtime=raw_runtime(manifest['runtime']),detectors={},artifacts={})
    index={(g['model'],g['identity']['event_id'],g['identity']['global_decay_id'],g['identity']['group_id']):g for g in manifest['groups']}
    for d in manifest['detectors']:
        m=d['model']; folder=worker/m;folder.mkdir();counts=dict.fromkeys(R.COUNT_FIELDS,0);seconds=0.
        with (folder/'scalars.jsonl').open('xb') as scalars, (folder/'traces.jsonl').open('xb') as traces:
            for rec in C.Reader(dest).jsonl('inputs/'+m+'/scalars.jsonl'):
                if rec['record_kind']=='decay':
                    scalars.write(encoded(rec));counts['initial_primaries']+=1;counts['zero_deposit_primaries']+=rec['zero_deposit'];continue
                g=index[(m,rec['event_id'],rec['global_decay_id'],rec['group_id'])];p=dest/'electronics'/g['key']
                info=C.Reader(p).json('result.json');seconds+=info['electronics_seconds']
                for k,v in info['counts'].items():counts[k]+=v
                scalars.write((p/'scalars.jsonl').read_bytes());traces.write((p/'traces.jsonl').read_bytes())
            for stream in (scalars,traces):stream.flush();os.fsync(stream.fileno())
        report['detectors'][m]=dict(counts=counts,config=d['config'],calibration=calibrations[m]['calibration'],electronics_seconds=seconds,
                                    calibration_seconds=calibrations[m]['calibration_seconds'])
        for n in ('scalars.jsonl','traces.jsonl'):report['artifacts'][m+'/'+n]=hashlib.sha256((folder/n).read_bytes()).hexdigest()
    write_json(worker/'report.json',report)
    # A view maps the unchanged aggregate validator to the durable input snapshot.
    class View(C.Reader):
        def path(self,relative):
            return C.Reader(dest).path(relative) if str(relative).startswith('inputs/') else super().path(relative)
    out=View(stage);R.verify_outputs(reader,out,{'detectors':manifest['detectors']},manifest['runtime'])
    reader.recheck();C.require(not (dest/'worker').exists(),'Final data without COMPLETE; conservative refusal','uncommitted_boundary')
    os.rename(worker,dest/'worker')
    return report


def replay_groups(root,name,replay_name,detector='both',electronics_profile=None,dry_run=False,resume=False,stop_after_groups=None):
    result=dict(schema_version=1,kind=KIND,status='blocked',source_name=name,replay_name=replay_name,
                verification_final=False,runtime_verified='NOT_CHECKED',dry_run=dry_run,findings=[],
                limitations=['M5a saved-charge import and electronics only; M5b native-production checkpoints remain pending.',
                             'Synthetic noiseless model; saved support is not physical collection completion.'])
    result['python_runtime']=dict(executable=sys.executable,version=sys.version)
    dest=None;attempt=None;started=time.monotonic()
    try:
        C.require(sys.version_info >= (3,10),'Existing Python 3.10+ required','unsupported_runtime')
        C.require(electronics_profile is None or isinstance(electronics_profile,str) and bool(electronics_profile),
                  'Explicit electronics profile must be nonempty','invalid_flags' if resume else 'invalid_profile')
        C.require(isinstance(replay_name,str) and __import__('re').fullmatch('[A-Za-z0-9_-]{1,80}',replay_name),'Unsafe replay name','unsafe_path')
        C.require(stop_after_groups is None or type(stop_after_groups) is int and 1<=stop_after_groups<=400,'StopAfterGroups must be 1..400','invalid_flags')
        C.require(not resume or electronics_profile is None,'All profile overrides forbidden on resume','invalid_flags')
        with C.inspection_session(root,name,detector) as (reader,inspection):
            result['inspection']=inspection
            parent,configs,source_inventory,lockstat,selection,settings_check=R.prepare_configuration(reader,inspection,name,electronics_profile)
            C.require(sum(d['counts']['groups'] for d in inspection['detectors'])<=400,'Checkpoint group budget exceeded','not_supported')
            target=reader.path('.local/replays/'+replay_name)
            if os.name=='nt':C.require(len(str(target))+90<260,'Replay name/root exceeds bounded Windows output paths','unsafe_path')
            if resume:
                C.require(target.is_dir(),'Checkpoint replay missing','missing_file')
                lease=C.existing_lock(C.Reader(target),'run.lock')
            else:
                C.require(not target.exists(),'New checkpoint replay name must not exist','output_exists')
                lease=nullcontext()
            with ExitStack() as leases:
                leases.enter_context(lease)
                if resume:
                    manifest,mh,calibrations,done=validate_saved(reader,target,inspection,name,replay_name,detector)
                    runtime=manifest['runtime']; result.update(output='.local/replays/'+replay_name,configuration=manifest['detectors'],
                        completed_groups=len(done),expected_groups=len(manifest['groups']),output_reserved=True)
                    if (target/'COMPLETE.json').exists():
                        complete=C.Reader(target).json('COMPLETE.json'); C.equal(complete['kind'],KIND,'completion kind')
                        C.equal(complete['manifest_sha256'],mh,'complete manifest');C.equal(complete['completed_keys'],[g['key'] for g in manifest['groups']],'complete group set')
                        C.equal(len(done),len(manifest['groups']),'complete committed count')
                        check_stamps(C.Reader(target),complete['artifacts'])
                        saved=C.Reader(target).json('run.json');C.require(saved['status'] in TERMINAL and saved['verification_final'],'trusted completion')
                        R.verify_outputs(reader,C.Reader(target),{'detectors':manifest['detectors']},runtime)
                        reader.recheck();result.update(status=saved['status'],verification_final=True,runtime_verified=True,detectors=saved['detectors'],
                                                      scientific_workers_launched=0,idempotent=True);return result
                    C.require(not (target/'worker').exists(),'Final data without COMPLETE; conservative refusal','uncommitted_boundary')
                    if dry_run:
                        result.update(status='paused',verification_final=True,scientific_workers_launched=0,read_only=True);return result
                else:
                    current={n:reader.digest(n) for n in SOURCES}
                    result.update(output='.local/replays/'+replay_name,configuration=configs,expected_groups=sum(d['counts']['groups'] for d in inspection['detectors']))
                    if dry_run:
                        reader.recheck();result.update(status='planned',verification_final=True,scientific_workers_launched=0,output_reserved=False);return result
                exe=R.julia_executable();argv=[exe,'--startup-file=no','--project=simulation','--threads=2','--compiled-modules=existing',str(reader.path('simulation/replay_groups.jl'))]
                probe=R.child([*argv,'--probe'],str(reader.root),timeout=60,limit=65536);result['runtime_probe']=probe
                C.require(probe['exit_code']==0 and not probe['output_limit_exceeded'],'Runtime probe failed: '+probe['output'],'unsupported_runtime')
                actual=C.decode(probe['output']);R.verify_runtime(reader,actual,inspection,exe,extra_sources=('replay_groups.jl',))
                C.equal(actual['group_process_module'],'Main','loaded group worker module')
                C.equal(actual['group_process_source'],str(reader.path('simulation/replay_groups.jl').resolve()),'loaded group worker source')
                if resume:C.equal(actual,runtime,'recorded runtime must not be rebased')
                else:runtime=actual
                reader.recheck()
                if not resume:
                    target.parent.mkdir(exist_ok=True);reader.path('.local/replays/'+replay_name);target.mkdir();dest=target
                    write_bytes(dest/'run.lock',b'M5a saved-charge replay output lease\n')
                    # Reservation prevents other new callers; acquire the persistent output lease before snapshots.
                    leases.enter_context(C.existing_lock(C.Reader(dest),'run.lock'))
                    leases.enter_context(failure_status(dest,result))
                    initialize(reader,dest,name,replay_name,detector,parent,configs,current,source_inventory,runtime,selection)
                    manifest,mh,calibrations,done=validate_saved(reader,dest,inspection,name,replay_name,detector)
                    result.update(output_reserved=True,completed_groups=0,expected_groups=len(manifest['groups']))
                dest=target;result.update(runtime_verified=True,status='running')
                if resume:leases.enter_context(failure_status(dest,result))
                attempts=dest/'attempts';attempt=attempts/uuid.uuid4().hex[:12];attempt.mkdir()
                status(dest/'run.json',result)
                out=C.Reader(dest)
                for g,files in charge_payloads(out,manifest['detectors']):
                    if (dest/'charge'/g['key']).exists():continue
                    stage=attempt/('charge-'+g['key']);stage.mkdir()
                    for f,data in files.items():write_bytes(stage/f,data)
                    commit(stage,dest/'charge'/g['key'],binding(mh,'charge',g['key']))
                missing=[g for g in manifest['groups'] if g['key'] not in done]
                selected=missing if stop_after_groups is None else missing[:stop_after_groups]
                next_event=iter(selected);active=[next(next_event,None)];seen_cal=set()
                def callback(event):
                    C.fields(event,('kind','phase','key','directory'),'worker event')
                    stage=C.Reader(attempt).path(event['directory']);phase=event['phase'];key=event['key']
                    C.require(stage.is_dir(),'Missing staged group')
                    if phase=='calibration':
                        C.require(key in {d['model'] for d in manifest['detectors']} and key not in calibrations and key not in seen_cal,'Unexpected calibration event')
                        C.equal(inventory(stage),['calibration.json'],'calibration file set')
                        info=verify_calibration(stage,config_for(manifest,key),runtime)
                        reader.recheck();commit(stage,dest/'calibration'/key,binding(mh,phase,key));calibrations[key]=info;seen_cal.add(key)
                        return dict(calibration_sha256=digest_bytes(encoded(info)))
                    else:
                        C.equal(phase,'electronics','event phase');g=active[0];C.require(g is not None and key==g['key'],'Unexpected/duplicate group completion')
                        C.equal(inventory(stage),['result.json','scalars.jsonl','traces.jsonl'],'result file set')
                        verify_group(dest/'charge'/key,stage,g,config_for(manifest,g['model']),runtime,calibrations[g['model']])
                        reader.recheck();commit(stage,dest/'electronics'/key,binding(mh,phase,key));done.append(key);active[0]=next(next_event,None)
                        result['completed_groups']=len(done);status(dest/'run.json',result)
                if selected or len(calibrations)<len(manifest['detectors']):
                    result['child']=run_session(reader.root,dest,manifest,mh,runtime,selected,attempt,callback)
                C.require(active[0] is None,'Worker omitted selected groups','child_failed')
                manifest,mh,calibrations,done=validate_saved(reader,dest,inspection,name,replay_name,detector)
                result.update(completed_groups=len(done),expected_groups=len(manifest['groups']),wall_seconds=time.monotonic()-started)
                if len(done)<len(manifest['groups']):
                    result.update(status='paused',verification_final=True);status(dest/'run.json',result);return result
                report=aggregate(reader,dest,manifest,mh,calibrations,attempt)
                check_stamps(reader,manifest['source_snapshot']);reader.recheck()
                result.update(status='completed_with_native_failures' if any(d['counts']['native_failed_groups'] for d in report['detectors'].values()) else 'completed',
                              verification_final=True,detectors=report['detectors'],completion_authority='Python driver after full manifest/census reconciliation')
                status(dest/'run.json',result)
                files=['run.json',*['worker/'+n for n in inventory(dest/'worker')],
                       *[phase+'/'+n for phase in ('charge','electronics','calibration','receipts') for n in inventory(dest/phase)]]
                write_json(dest/'COMPLETE.json',dict(kind=KIND,schema_version=1,manifest_sha256=mh,
                           completed_keys=[g['key'] for g in manifest['groups']],artifacts=stamps(C.Reader(dest),files)))
                return result
    except BaseException as error:
        result.update(status='failed' if dest else 'blocked',verification_final=False)
        if C.finding(error) not in result['findings']:result['findings'].append(C.finding(error))
        if attempt:write_json(attempt/'failure.json',dict(finding=C.finding(error),result=result))
    return result


def initialize(reader,dest,name,replay_name,detector,parent,configs,current,source_inventory,runtime,selection=None):
    inputs=dest/'inputs';inputs.mkdir();shutil.copyfile(reader.path('.local/runs/'+name+'/run.json'),inputs/'parent-run.json')
    with (inputs/'parent-run.json').open('r+b') as stream:os.fsync(stream.fileno())
    if selection:write_json(inputs/'electronics-selection.json',selection)
    for d in configs:
        base='.local/runs/'+name+'/'+d['model']+'/response/';folder=inputs/d['model'];folder.mkdir();d['input_sha256']={}
        original=reader.json(base+'run.json');d.update(model_sha256=original['model_sha256'],readout_contact_id=original['readout_contact_id'])
        for f in ('signals.csv','scalars.jsonl','run.json','profile-input.json','readout-config.json'):
            target=folder/(f if f in ('signals.csv','scalars.jsonl') else 'original-'+f)
            shutil.copyfile(reader.path(base+f),target)
            C.equal(hashlib.sha256(target.read_bytes()).hexdigest(),reader.digest(base+f),'exact original snapshot')
            with target.open('r+b') as stream:os.fsync(stream.fileno())
            if f in ('signals.csv','scalars.jsonl'):d['input_sha256'][f]=reader.digest(base+f)
        write_json(folder/'effective-profile.json',d['profile']);write_json(folder/'effective-config.json',d['config'])
    # External profile paths are provenance only after the effective profile is copied.
    # All project source dependencies and original run files remain pinned.
    external={item['path'] for item in selection['input_bindings']} | {selection['input']['path']} if selection else set()
    pins={n:dict(sha256=h,bytes=size,mtime_ns=reader.stamps[n][1]) for n,(h,size) in reader.watched.items()
          if n in SOURCES or n not in external and n.startswith(('.local/runs/'+name+'/','simulation/','models/','transport/','tools/'))}
    manifest=dict(kind=KIND,schema_version=1,source_name=name,replay_name=replay_name,detector_selection=detector,
                  detectors=configs,original_parent=parent,runtime=runtime,source_sha256=current,
                  source_snapshot=pins,source_inventory=source_inventory,
                  python_runtime=dict(executable=sys.executable,version=sys.version))
    lock=reader.path('.local/runs/'+name+'/run.lock').stat()
    manifest['source_lock_metadata']=dict(bytes=lock.st_size,mtime_ns=lock.st_mtime_ns)
    manifest['groups']=[g for g,files in charge_payloads(C.Reader(dest),configs)]
    C.require(len(manifest['groups'])<=400,'Checkpoint group budget exceeded','not_supported')
    write_json(dest/'manifest.json',manifest)
    for folder in ('charge','electronics','calibration','attempts','receipts'):(dest/folder).mkdir()
    for phase in ('charge','electronics','calibration'):(dest/'receipts'/phase).mkdir()
    out=C.Reader(dest);write_json(dest/'INITIAL.json',dict(kind=KIND,schema_version=1,manifest=stamps(out,['manifest.json'])['manifest.json'],
                                                         inputs=stamps(out,['inputs/'+n for n in inventory(inputs)])))
    status(dest/'run.json',dict(kind=KIND,schema_version=1,status='paused',verification_final=False,completed_groups=0))
