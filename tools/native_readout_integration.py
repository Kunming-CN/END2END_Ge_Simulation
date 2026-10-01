"""Bounded AK02/SAP22 NEW native charge -> existing calibrated electronics recovery.

Run.cmd native-readout owns one root. This composes the existing workers and
transactions; it does not change native or readout numerical functions.
"""
import argparse
from contextlib import ExitStack, contextmanager
import csv
import hashlib
import io
import os
from pathlib import Path
import re
import sys
import uuid

import charge_check as C
import group_checkpoints as G
import native_group_checkpoints as N
import replay_readout as R

ROOT=N.ROOT
BASE='.local/native-readout-integration-v1/implementation/outputs'
KIND='native_charge_readout_integration_v1'
PROFILE='simulation/native_readout_profile.json'
WORKER='simulation/native_readout_groups.jl'
SOURCES=tuple(sorted(set((*N.SOURCES,*G.SOURCES,*C.ES_SOURCES,WORKER,
    'tools/native_readout_integration.py','tools/native_readout_integration.ps1','Run.cmd'))))
PHASES=('charge','calibration','electronics')
TERMINAL=('completed','completed_with_native_failures')


def load_plan(reader, primary_ids=None, detector=None):
    # The recorded cache has five settings; validate the complete schema here,
    # independently of the legacy producer's present-key comparison.
    expected_settings=dict(drift_cap_ns=10000,drift_dt_ns=2,parcels=16,seed_family=2609261,temperature_K=77)
    settings=reader.json(N.BATCH+'/config.json').get('settings')
    C.require(type(settings) is dict and set(settings)==set(expected_settings),'exact recorded cache settings keys')
    C.require(all(type(settings[k]) is int and settings[k]==v for k,v in expected_settings.items()),'exact recorded cache settings values')
    if detector is None:
        plan=N.load_plan(reader,'abort') if primary_ids is None else N.load_plan(reader,'abort',primary_ids)
    else:plan=N.load_plan(reader,'abort',primary_ids,detector=detector)
    plan['source_sha256']={n:reader.digest(n) for n in SOURCES}
    selection,_=R.resolve_profile(reader,PROFILE)
    C.equal(reader.digest(PROFILE),C.ES_DEFAULTS[PROFILE],'frozen integration profile')
    config=R.expected_config(reader,selection['profile'],len(plan['events']))
    C.equal(selection['configuration'],dict(config,expected_primary_count=None),'independent profile/config gate')
    d=dict(model=plan['model'],profile=selection['profile'],config=config,dt=2,eion=2.95,
        primary_count=len(plan['events']),model_sha256=plan['model_sha256'],readout_contact_id=plan['readout_contact_id'])
    return plan,d,selection


def probe_readout(reader):
    exe=R.julia_executable()
    call=R.child([exe,'--startup-file=no','--project=simulation','--threads=2','--compiled-modules=existing',
        str(reader.path('simulation/replay_groups.jl')),'--probe'],str(reader.root),timeout=60,limit=65536)
    C.require(call['exit_code']==0 and not call['output_limit_exceeded'],'Readout runtime probe failed: '+call['output'],'unsupported_runtime')
    runtime=C.decode(call['output'])
    # No old charge is an input. Pin actual package/source bytes at this initial
    # probe, then require exact loaded-runtime equality on every resumed stage.
    R.verify_runtime(reader,runtime,{'detectors':[]},exe,extra_sources=('replay_groups.jl',))
    C.equal(runtime['group_process_module'],'Main','loaded group worker module')
    C.equal(runtime['group_process_source'],str(reader.path('simulation/replay_groups.jl').resolve()),'loaded group worker source')
    return runtime,call


def adapter(record,plan,g):
    """Lossless signed numerical bridge; no truth gain or waveform invention."""
    e=plan['events'][g['event_index']];native=record['native'];failed=native is None
    ids=dict(event_id=e['event_id'],global_decay_id=e['global_decay_id'],group_id=g['group']['group_id'],origin_time_ns=g['group']['origin_time_ns'])
    scalar=dict(record_kind='pulse',**ids,event=e,group=g['group'],status='native_transport_failed' if failed else 'native_completed',
        native_steps=None if failed else native['steps'],transport_flags=record['transport_flags'],error=record['error'],
        charge_end_ns=None if failed else native['times'][-1],final_induced_keV=None if failed else native['signal'][-1],
        readout=None if failed else dict(input_sample_count=len(native['times'])),accepted=False if failed else None,
        rejection_reason='native_transport_failed' if failed else None,trace_saved=False)
    stream=io.StringIO(newline='');writer=csv.writer(stream,lineterminator='\n');writer.writerow(C.SIGNAL_COLUMNS)
    if not failed:
        for t,q in zip(native['times'],native['signal']):writer.writerow([ids[k] for k in ('event_id','global_decay_id','group_id')]+[t,q])
    files={'scalars.jsonl':G.encoded(scalar),'signals.csv':stream.getvalue().encode('utf-8')}
    group=dict(key=g['key'],model=plan['model'],identity=ids,samples=0 if failed else len(native['times']),
        files={n:dict(sha256=G.digest_bytes(b),bytes=len(b)) for n,b in files.items()})
    return group,files


def verify_charge(path,g,plan,runtime):
    record=N.verify_charge(path,g,plan,runtime,extra_files=('scalars.jsonl','signals.csv'))
    group,files=adapter(record,plan,g)
    for n,data in files.items():C.equal((path/n).read_bytes(),data,'exact native/readout bridge '+n)
    return group


def expected(plan):
    keys=[g['key'] for g in plan['groups']]
    return dict(charge=keys,calibration=[plan['model']],electronics=keys)


def progress(result,mh,plan,done,status,final=False):
    result.update(kind=KIND,schema_version=1,manifest_sha256=mh,status=status,verification_final=final,
        selected_census=plan['selected_census'],stages={p:dict(expected_keys=keys,completed_keys=[k for k in keys if k in done[p]],
            expected_count=len(keys),completed_count=len(done[p])) for p,keys in expected(plan).items()})


def initialize(reader,dest,name,plan,d,selection,native_runtime,runtime):
    inputs=dest/'inputs';inputs.mkdir()
    for i,n in enumerate(plan['input_files']):G.write_bytes(inputs/str(i),reader.path(n).read_bytes())
    G.write_json(inputs/'effective-profile.json',d['profile']);G.write_json(inputs/'effective-config.json',d['config'])
    G.write_json(inputs/'electronics-selection.json',selection)
    m=dict(kind=KIND,schema_version=1,name=name,plan=plan,detectors=[d],selection=selection,native_runtime=native_runtime,runtime=runtime,
        source_sha256=plan['source_sha256'],python_runtime=N.python_runtime(),source_snapshot=G.stamps(reader,list(reader.watched)))
    reader.recheck();G.write_json(dest/'manifest.json',m)
    for n in (*PHASES,'receipts','attempts'):(dest/n).mkdir()
    for p in PHASES:(dest/'receipts'/p).mkdir()
    out=C.Reader(dest);mh=out.digest('manifest.json');r={}
    progress(r,mh,plan,{p:[] for p in PHASES},'paused');G.write_json(dest/'run.json',r)
    G.write_json(dest/'INITIAL.json',dict(kind=KIND,schema_version=1,manifest=G.stamps(out,['manifest.json'])['manifest.json'],
        inputs=G.stamps(out,['inputs/'+n for n in G.inventory(inputs)])))


def ledger(dest,plan):
    for index,e in enumerate(plan['events']):
        yield dict(record_kind='decay',event_id=e['event_id'],global_decay_id=e['global_decay_id'],zero_deposit=e['zero_ge'],event=e)
        for g in plan['groups']:
            if g['event_index']==index:yield C.Reader(dest/'charge'/g['key']).jsonl('scalars.jsonl').__next__()


def signals(dest,plan):
    for g in plan['groups']:yield from C.Reader(dest/'charge'/g['key']).csv('signals.csv',C.SIGNAL_COLUMNS)


def verify_final(dest,m):
    out=C.Reader(dest);report=out.json('worker/report.json');d=m['detectors'][0];model=m['plan']['model']
    C.equal(G.inventory(dest/'worker'),[model+'/scalars.jsonl',model+'/traces.jsonl','report.json'],'final artifact inventory')
    C.equal(report['kind'],'electronics_replay_worker_v1','final worker kind')
    C.equal(report['status'],'worker_complete_untrusted','final worker status')
    C.equal(report['runtime'],G.raw_runtime(m['runtime']),'final runtime')
    C.equal(set(report['detectors']),{model},'final detector census')
    C.equal(set(report['artifacts']),{model+'/scalars.jsonl',model+'/traces.jsonl'},'final hashes inventory')
    for n,h in report['artifacts'].items():out.digest('worker/'+n,h)
    R.verify_detector_outputs(d,report['detectors'][model],ledger(dest,m['plan']),out.jsonl('worker/'+model+'/scalars.jsonl'),
        out.jsonl('worker/'+model+'/traces.jsonl'),signals(dest,m['plan']))
    out.recheck();return report


def validate_saved(reader,dest,name,plan,d,selection):
    """All refusal gates precede probes, attempts, status writes and workers."""
    out=C.Reader(dest);initial=out.json('INITIAL.json')
    C.equal((initial['kind'],initial['schema_version']),(KIND,1),'initial identity')
    G.check_stamps(out,{'manifest.json':initial['manifest'],**initial['inputs']})
    C.equal(G.inventory(dest/'inputs'),sorted(n.removeprefix('inputs/') for n in initial['inputs']),'input snapshot inventory')
    m=out.json('manifest.json');mh=out.digest('manifest.json')
    C.equal((m['kind'],m['schema_version'],m['name']),(KIND,1,name),'manifest identity')
    C.equal(m['plan'],plan,'native input/source/cache/settings/primary ledger')
    C.equal(N.expected_groups(plan['events'],plan['prepared'],plan['model']),plan['groups'],'expected full group census')
    C.equal(m['detectors'],[d],'independent resolved detector/profile/config gate')
    C.equal(m['selection'],selection,'independent profile selection gate')
    C.equal(out.json('inputs/effective-config.json'),R.expected_config(reader,d['profile'],len(plan['events'])),'copied config independent gate')
    C.equal(out.json('inputs/effective-profile.json'),d['profile'],'copied profile')
    C.equal(out.json('inputs/electronics-selection.json'),selection,'copied selection')
    C.equal(m['source_sha256'],plan['source_sha256'],'all integration source pins')
    C.equal(m['python_runtime'],N.python_runtime(),'driver bytes/version')
    G.check_stamps(reader,m['source_snapshot'])
    for i,n in enumerate(plan['input_files']):C.equal(out.digest('inputs/'+str(i)),reader.digest(n),'original input snapshot')
    for runtime in (m['native_runtime'],m['runtime']):
        for k,h in (('launcher_executable','launcher_sha256'),('executable','executable_sha256')):
            C.equal(hashlib.sha256(Path(runtime[k]).read_bytes()).hexdigest(),runtime[h],'saved runtime bytes')
    keys=expected(plan);done={p:[] for p in PHASES};groups=[];cals={};model=plan['model']
    for phase in PHASES:
        path=dest/phase;witnesses=dest/'receipts'/phase
        C.require(path.is_dir() and witnesses.is_dir(),'missing stage/witness inventory','missing_commit')
        C.require(all(p.is_dir() and p.name in keys[phase] for p in path.iterdir()),'extra stage identity')
        C.require(all(p.is_file() and (p.name.removesuffix('.json') in keys[phase] or re.fullmatch(r'.+\.json\.pending-[0-9a-f]{12}',p.name) and p.name.split('.json.pending-')[0] in keys[phase]) for p in witnesses.iterdir()),'extra witness identity')
    for g in plan['groups']:
        p=dest/'charge'/g['key']
        if p.exists() or G.witness_path(p).exists():
            _,receipt=G.committed(p,G.binding(mh,'charge',g['key']))
            C.equal(set(receipt['artifacts']),{'charge.json','scalars.jsonl','signals.csv'},'charge artifact set')
            groups.append(verify_charge(p,g,plan,m['native_runtime']));done['charge'].append(g['key'])
    p=dest/'calibration'/model
    if p.exists() or G.witness_path(p).exists():
        C.equal(done['charge'],keys['charge'],'calibration requires full charge stage')
        _,receipt=G.committed(p,G.binding(mh,'calibration',model))
        C.equal(set(receipt['artifacts']),{'calibration.json'},'calibration artifact set')
        cals[model]=G.verify_calibration(p,d,m['runtime']);done['calibration'].append(model)
    for key in keys['electronics']:
        p=dest/'electronics'/key
        if p.exists() or G.witness_path(p).exists():
            C.require(key in done['charge'] and model in cals,'electronics without charge/calibration')
            _,receipt=G.committed(p,G.binding(mh,'electronics',key))
            C.equal(set(receipt['artifacts']),{'result.json','scalars.jsonl','traces.jsonl'},'electronics artifact set')
            g=next(g for g in groups if g['key']==key)
            G.verify_group(dest/'charge'/key,p,g,d,m['runtime'],cals[model]);done['electronics'].append(key)
    saved=out.json('run.json')
    C.require({'kind','schema_version','manifest_sha256','status','stages','selected_census'}<=set(saved),'missing progress identity authority','missing_commit')
    C.equal((saved['kind'],saved['schema_version'],saved['manifest_sha256']),(KIND,1,mh),'progress identity')
    C.require(saved['status'] in ('paused','running','failed',*TERMINAL),'progress status')
    C.equal(saved['selected_census'],plan['selected_census'],'progress primary/zero census')
    C.equal(set(saved['stages']),set(PHASES),'mandatory stage identity schema')
    for phase in PHASES:
        item=saved['stages'][phase]
        C.fields(item,('expected_keys','completed_keys','expected_count','completed_count'),'stage progress')
        C.equal(item['expected_keys'],keys[phase],'bound expected identities')
        C.equal(C.integer(item['expected_count'],'expected stage count',high=4),len(keys[phase]),'expected stage count')
        reported=item['completed_keys']
        C.require(isinstance(reported,list) and all(isinstance(k,str) and k in keys[phase] for k in reported) and len(set(reported))==len(reported),'invalid reported stage identities','missing_commit')
        C.equal(C.integer(item['completed_count'],'completed stage count',high=4),len(reported),'count/identity agreement')
        C.require(set(reported)<=set(done[phase]),'previously reported commit disappeared; refuse recomputation','missing_commit')
    if (dest/'COMPLETE.json').exists():
        complete=out.json('COMPLETE.json');C.equal((complete['kind'],complete['manifest_sha256']),(KIND,mh),'complete binding')
        C.equal(complete['completed_keys'],keys,'complete stage identity ledger');C.equal(done,keys,'every stage completed')
        G.check_stamps(out,complete['artifacts']);report=verify_final(dest,m)
        failures=report['detectors'][model]['counts']['native_failed_groups']
        C.equal(saved['status'],TERMINAL[bool(failures)],'complete status');C.equal(saved['verification_final'],True,'verified complete')
        for p in PHASES:C.equal(saved['stages'][p]['completed_keys'],keys[p],'final progress')
    else:
        C.require(saved['status'] not in TERMINAL and not (dest/'worker').exists(),'terminal data without COMPLETE; preserve/refuse','uncommitted_boundary')
    out.recheck();reader.recheck();return m,mh,done,groups,cals


def aggregate(reader,dest,m,groups,cals,attempt):
    model=m['plan']['model'];worker=attempt/'final';worker.mkdir();folder=worker/model;folder.mkdir();counts=dict.fromkeys(R.COUNT_FIELDS,0);seconds=0.
    with (folder/'scalars.jsonl').open('xb') as scalars,(folder/'traces.jsonl').open('xb') as traces:
        for rec in ledger(dest,m['plan']):
            if rec['record_kind']=='decay':
                scalars.write(G.encoded(rec));counts['initial_primaries']+=1;counts['zero_deposit_primaries']+=rec['zero_deposit'];continue
            key=model+'-e'+str(rec['event_id'])+'-d'+str(rec['global_decay_id'])+'-g'+str(rec['group_id']);p=dest/'electronics'/key
            info=C.Reader(p).json('result.json');seconds+=info['electronics_seconds']
            for k,v in info['counts'].items():counts[k]+=v
            scalars.write((p/'scalars.jsonl').read_bytes());traces.write((p/'traces.jsonl').read_bytes())
        for stream in (scalars,traces):stream.flush();os.fsync(stream.fileno())
    cal=cals[model];report=dict(kind='electronics_replay_worker_v1',status='worker_complete_untrusted',runtime=G.raw_runtime(m['runtime']),
        detectors={model:dict(counts=counts,config=m['detectors'][0]['config'],calibration=cal['calibration'],
            calibration_seconds=cal['calibration_seconds'],electronics_seconds=seconds)},
        artifacts={model+'/'+n:G.digest_bytes((folder/n).read_bytes()) for n in ('scalars.jsonl','traces.jsonl')})
    R.verify_detector_outputs(m['detectors'][0],report['detectors'][model],ledger(dest,m['plan']),C.Reader(folder).jsonl('scalars.jsonl'),C.Reader(folder).jsonl('traces.jsonl'),signals(dest,m['plan']))
    G.write_json(worker/'report.json',report);reader.recheck();os.rename(worker,dest/'worker');return report


def saved_manifest(dest,name):
    """No detector or primary selector is trusted before its INITIAL binding."""
    out=C.Reader(dest);initial=out.json('INITIAL.json')
    C.equal((initial['kind'],initial['schema_version']),(KIND,1),'initial identity')
    G.check_stamps(out,{'manifest.json':initial['manifest'],**initial['inputs']})
    m=out.json('manifest.json')
    C.equal((m['kind'],m['schema_version'],m['name']),(KIND,1,name),'manifest identity')
    out.recheck();return m


def saved_detector(dest,name):
    plan=saved_manifest(dest,name)['plan']
    if 'detector_selection_mode' not in plan:
        C.equal(plan['model'],'AK02','saved legacy detector')
        C.require('detector_settings' not in plan,'unexpected legacy detector settings');return None
    C.equal(plan['detector_selection_mode'],'explicit','saved detector mode')
    N.integration_detector(plan['model'])
    C.equal(plan['detector_settings'],N.detector_settings(plan['model']),'saved detector metadata')
    return plan['model']


def saved_primary_ids(dest,name):
    """Read selection only after the immutable INITIAL/manifest binding passes."""
    plan=saved_manifest(dest,name)['plan']
    if 'primary_selection_mode' not in plan:
        cohort=N.COHORT if 'detector_selection_mode' not in plan else N.integration_detector(plan['model'])['cohort']
        C.equal(plan['selected_primary_ids'],cohort,'saved default cohort');return None
    C.equal(plan['primary_selection_mode'],'explicit','saved primary selection mode')
    ids=plan['selected_primary_ids']
    C.require(type(ids) is list and 1<=len(ids)<=8 and all(type(x) is int for x in ids),
        'Invalid saved PrimaryIds','invalid_selection')
    value=','.join(str(x) for x in ids);C.equal(N.parse_primary_ids(value),ids,'saved PrimaryIds')
    return value


def integrate(root,name,resume=False,dry_run=False,stop_after_groups=None,primary_ids=None,detector=None):
    result=dict(kind=KIND,schema_version=1,status='blocked',verification_final=False,findings=[],scientific_workers_launched=0,
        limitations=['Bounded selected engineering cohort; synthetic noiseless injection calibration; no calibrated CCE or experimental spectrum claim.'])
    dest=None;attempt=None
    try:
        C.require(os.name=='nt','bounded Windows interface','not_supported')
        C.require(re.fullmatch('[A-Za-z0-9_-]{1,24}',name or ''),'bounded safe name','unsafe_path')
        C.require(stop_after_groups is None or type(stop_after_groups) is int and 1<=stop_after_groups<=2,'StopAfterGroups must be 1..2','invalid_flags')
        C.require(not resume or primary_ids is None,'PrimaryIds override is forbidden on Resume','invalid_flags')
        C.require(not resume or detector is None,'Detector override is forbidden on Resume','invalid_flags')
        if detector is not None:N.integration_detector(detector)
        if primary_ids is not None:N.parse_primary_ids(primary_ids)
        reader=C.Reader(root);target=reader.path(BASE+'/'+name)
        C.require(len(str(target))+95<260,'bounded Windows output path','unsafe_path')
        C.require(target.is_dir() if resume else not target.exists(),'resume requires root; new name must not exist','output_exists')
        with ExitStack() as leases:
            if resume:leases.enter_context(C.existing_lock(C.Reader(target),'run.lock'))
            effective=saved_primary_ids(target,name) if resume else primary_ids
            selected_detector=saved_detector(target,name) if resume else detector
            if selected_detector is None:plan,d,selection=load_plan(reader) if effective is None else load_plan(reader,effective)
            else:plan,d,selection=load_plan(reader,effective,selected_detector)
            model=plan['model']
            result['output']=BASE+'/'+name
            if resume:
                m,mh,done,groups,cals=validate_saved(reader,target,name,plan,d,selection)
                progress(result,mh,plan,done,'paused')
                if (target/'COMPLETE.json').exists():
                    saved=C.Reader(target).json('run.json');result.update(status=saved['status'],verification_final=True,idempotent=True,read_only=True);return result
            if dry_run:
                reader.recheck();result.update(status='paused' if resume else 'planned',verification_final=True,read_only=True,selected_census=plan['selected_census']);return result
            if not resume:
                nr,np=N.probe_runtime(reader,plan);runtime,rp=probe_readout(reader);result['runtime_probes']={'native':np,'readout':rp}
                reader.recheck();target.parent.mkdir(parents=True,exist_ok=True);target.mkdir();dest=target
                G.write_bytes(dest/'run.lock',b'Native/readout integration lease\n');leases.enter_context(C.existing_lock(C.Reader(dest),'run.lock'))
                # Establish progress authority before failure-status may publish.
                initialize(reader,dest,name,plan,d,selection,nr,runtime)
                m,mh,done,groups,cals=validate_saved(reader,dest,name,plan,d,selection)
            @contextmanager
            def failure_receipts():
                try:
                    with G.failure_status(dest,result):yield
                except BaseException as error:
                    if attempt:G.write_json(attempt/'failure.json',dict(finding=C.finding(error),result=result))
                    raise
            dest=target;progress(result,mh,plan,done,'running');leases.enter_context(failure_receipts())
            missing=[g for g in plan['groups'] if g['key'] not in done['charge']]
            if missing:
                if resume:
                    nr,np=N.probe_runtime(reader,plan);C.equal(nr,m['native_runtime'],'native runtime cannot rebase')
                attempt=dest/'attempts'/uuid.uuid4().hex[:12];attempt.mkdir();G.status(dest/'run.json',result)
                remaining=iter(missing);active=[next(remaining,None)]
                def native_ready(event):
                    g=active[0];C.require(g is not None and event['key']==g['key'],'unexpected/duplicate native group')
                    C.equal(event['directory'],'charge-'+g['key'],'native staged path');stage=C.Reader(attempt).path(event['directory'])
                    record=N.verify_charge(stage,g,plan,m['native_runtime']);group,files=adapter(record,plan,g)
                    for n,b in files.items():G.write_bytes(stage/n,b)
                    verify_charge(stage,g,plan,m['native_runtime']);reader.recheck();G.commit(stage,dest/'charge'/g['key'],G.binding(mh,'charge',g['key']))
                    G.committed(dest/'charge'/g['key'],G.binding(mh,'charge',g['key']));verify_charge(dest/'charge'/g['key'],g,plan,m['native_runtime'])
                    done['charge'].append(g['key']);groups.append(group);active[0]=next(remaining,None)
                    progress(result,mh,plan,done,'running');G.status(dest/'run.json',result)
                result['scientific_workers_launched']+=1
                N.run_session(reader,dest,dict(plan=plan,runtime=m['native_runtime']),missing,attempt,native_ready,worker_source=WORKER)
                C.require(active[0] is None,'native worker omitted group','child_failed')
            m,mh,done,groups,cals=validate_saved(reader,dest,name,plan,d,selection)
            selected=[g for g in groups if g['key'] not in done['electronics']]
            if stop_after_groups is not None:selected=selected[:stop_after_groups]
            if selected or not cals:
                if resume:
                    actual,rp=probe_readout(reader);C.equal(actual,m['runtime'],'readout runtime cannot rebase')
                attempt=dest/'attempts'/uuid.uuid4().hex[:12];attempt.mkdir();remaining=iter(selected);active=[next(remaining,None)]
                progress(result,mh,plan,done,'running');G.status(dest/'run.json',result)
                def electronic_ready(event):
                    phase=event['phase'];key=event['key'];C.equal(event['directory'],phase+'-'+key,'readout staged path')
                    stage=C.Reader(attempt).path(event['directory'])
                    if phase=='calibration':
                        C.require(key==model and key not in cals,'unexpected/duplicate calibration')
                        C.equal(G.inventory(stage),['calibration.json'],'calibration stage inventory');info=G.verify_calibration(stage,d,m['runtime'])
                    else:
                        C.equal(phase,'electronics','phase');g=active[0];C.require(g is not None and key==g['key'],'unexpected/duplicate electronics')
                        C.equal(G.inventory(stage),['result.json','scalars.jsonl','traces.jsonl'],'electronics stage inventory')
                        G.verify_group(dest/'charge'/key,stage,g,d,m['runtime'],cals[model])
                    reader.recheck();G.commit(stage,dest/phase/key,G.binding(mh,phase,key));G.committed(dest/phase/key,G.binding(mh,phase,key))
                    if phase=='calibration':cals[key]=info
                    else:active[0]=next(remaining,None)
                    done[phase].append(key);progress(result,mh,plan,done,'running');G.status(dest/'run.json',result)
                    return dict(calibration_sha256=G.digest_bytes(G.encoded(info))) if phase=='calibration' else None
                result['scientific_workers_launched']+=1
                G.run_session(reader.root,dest,dict(m,groups=groups),mh,m['runtime'],selected,attempt,electronic_ready)
                C.require(active[0] is None,'readout worker omitted group','child_failed')
            m,mh,done,groups,cals=validate_saved(reader,dest,name,plan,d,selection)
            if done!=expected(plan):
                progress(result,mh,plan,done,'paused',True);G.status(dest/'run.json',result);return result
            if attempt is None:attempt=dest/'attempts'/uuid.uuid4().hex[:12];attempt.mkdir()
            report=aggregate(reader,dest,m,groups,cals,attempt);G.check_stamps(reader,m['source_snapshot']);reader.recheck()
            status=TERMINAL[bool(report['detectors'][model]['counts']['native_failed_groups'])]
            progress(result,mh,plan,done,status,True);result['detectors']=report['detectors'];G.status(dest/'run.json',result)
            files=['run.json',*['worker/'+n for n in G.inventory(dest/'worker')],*[p+'/'+n for p in (*PHASES,'receipts') for n in G.inventory(dest/p)]]
            G.write_json(dest/'COMPLETE.json',dict(kind=KIND,schema_version=1,manifest_sha256=mh,completed_keys=expected(plan),artifacts=G.stamps(C.Reader(dest),files)))
            return result
    except BaseException as error:
        result.update(status='failed' if dest else 'blocked',verification_final=False)
        if C.finding(error) not in result['findings']:result['findings'].append(C.finding(error))
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--name',required=True)
    p.add_argument('--resume',action='store_true');p.add_argument('--dry-run',action='store_true');p.add_argument('--stop-after-groups',type=int)
    p.add_argument('--primary-ids',help='Quoted canonical CSV of 1..8 checked selected-detector cs137-1m primaries; new output only')
    p.add_argument('--detector',help='Opt-in AK02 or SAP22; omitted retains AK02; new output only')
    a=p.parse_args(argv);r=integrate(ROOT,**vars(a));print(G.encoded(r).decode(),end='');return 0 if r['verification_final'] else 2


if __name__=='__main__':sys.exit(main())
