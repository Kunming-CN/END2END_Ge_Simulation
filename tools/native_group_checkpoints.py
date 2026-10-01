"""Bounded M5b NEW native charge only; see NATIVE_GROUP_CHECKPOINTS.md.

The original batch/physics and M5a implementations remain unchanged. Immutable
radiation records and a checked saved field cache are inputs, never old charge.
"""
import argparse
from contextlib import ExitStack
import hashlib
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import time
import uuid

import charge_check as C
import group_checkpoints as G
import replay_readout as R

ROOT = Path(__file__).resolve().parents[1]
BASE = '.local/native-group-checkpoint-v1/implementation/outputs'
KIND = 'native_charge_group_checkpoint_v1'
COHORT = [0, 2594, 3950]
CONTRACT = '.local/native-bridge-pilot/contracts-v3/AK02.json'
EXPORT = '.local/native-bridge-pilot/contracts-v3/EXPORT.json'
BATCH = '.local/cs137-1m-native'
NUMERICAL = tuple('simulation/'+n for n in (
    'native_checkpoint_batch.jl', 'native_bridge_pilot.jl', 'native_boundary_guard.jl',
    'native_response.jl', 'native_li_example.jl', 'native_stream.jl', 'replay.jl',
    'run.jl', 'readout.jl', 'readout_profiles.jl', 'Project.toml', 'Manifest.toml'))
SOURCES = (*NUMERICAL, 'simulation/native_groups.jl', 'tools/native_group_checkpoints.py',
           'tools/group_checkpoints.py', 'tools/charge_check.py', 'tools/replay_readout.py')
SETTINGS = dict(parcels=16, seed_family=2609261, drift_dt_ns=2,
                drift_cap_ns=10000, temperature_K=77, diffusion=True,
                end_drift_when_no_field=False, self_repulsion=False, geometry_check=True)
TERMINAL = ('completed_native_charge', 'completed_native_charge_with_failures')


def expected_groups(events, prepared):
    """Independent full-ledger check, including zeros; native validator also runs."""
    groups = []; seen = set(); total_rows = 0
    for index, event in enumerate(events):
        eid = C.integer(event['event_id'], 'event ID', high=999999)
        C.require(eid not in seen, 'Duplicate selected primary'); seen.add(eid)
        C.equal(event['namespace'], 'cs137-1m', 'cohort namespace')
        C.equal([event[k] for k in ('global_decay_id','seed_event_id')], [eid,eid], 'seed/global identity')
        C.equal(event['seed_family'], SETTINGS['seed_family'], 'native seed family')
        identity = event['identity']
        C.equal(identity['model_id'], 'AK02', 'identity model')
        for k in ('chunk_index','global_offset','local_primary_id','global_primary_id','chunk_count','radiation_seed'):
            C.integer(identity[k], k, high=2**63-1)
        C.require(0 <= identity['local_primary_id'] < identity['chunk_count'] <= 10000, 'chunk bounds')
        C.equal(identity['global_offset'], 10000*identity['chunk_index'], 'chunk offset')
        C.equal(identity['global_primary_id'], eid, 'original global ID')
        C.equal(identity['global_offset']+identity['local_primary_id'], eid, 'local/global mapping')
        C.equal(event['raw_table'], 'stp/germanium', 'raw table')
        for k in ('source_lh5_sha256','source_campaign_sha256'):
            C.require(re.fullmatch('[0-9a-f]{64}',event[k]), 'missing raw provenance')
        steps = event['steps']; total_rows += len(steps)
        rowids = [C.integer(s['raw_row_index'],'raw row') for s in steps]
        C.equal(rowids, sorted(set(rowids)), 'unique original raw rows')
        for step in steps:
            raw = step['raw']
            C.equal(raw['evtid'], identity['local_primary_id'], 'raw primary')
            for a,b in (('raw_row_index','raw_row_index'),('energy_keV','edep'),('time_ns','time'),
                        ('track_id','trackid'),('parent_track_id','parent_trackid'),('particle_pdg','particle')):
                C.equal(step[a], raw[b], 'retained raw alias '+a)
            C.require(C.number(step['energy_keV'],'deposit')>=0 and C.number(step['time_ns'],'deposition clock')>=0,'negative deposit/clock')
            rot=prepared['coordinate_transform']['rotation_local_to_global']
            shift=prepared['coordinate_transform']['translation_global_mm']
            for suffix,name in (('','position_mm'),('_pre','pre_position_mm'),('_post','post_position_mm')):
                global_m=[C.number(raw[a+suffix],'raw position') for a in ('xloc','yloc','zloc')]
                local=[sum(rot[j][i]*(1000*global_m[j]-shift[j]) for j in range(3)) for i in range(3)]
                C.equal(len(step[name]),3,'local vector')
                C.require(all(abs(C.number(x,'local position')-y)<=1e-10 for x,y in zip(step[name],local)), 'changed coordinate transform')
                if not suffix:C.equal(step['global_position_m'],global_m,'raw global position')
            C.require(all(v in ('inside','surface') for v in step['boundary_classifications'].values()),'outside source row')
        energy=sum(s['energy_keV'] for s in steps)
        C.close(event['ge_energy_keV'],energy,'truth energy')
        C.close(event['material_energy_keV']['G4_Ge'],energy,'material energy')
        C.require(type(event['zero_ge']) is bool and event['zero_ge']==(energy==0),'zero truth semantics')
        # Mirror only NativeStream's data grouping contract, never its physics.
        horizon=prepared['grouping_policy']['horizon_ns']; C.equal(horizon,100000,'isolated horizon')
        rebuilt=[]
        for step in sorted((s for s in steps if s['energy_keV']>0),key=lambda s:(s['time_ns'],s['raw_row_index'])):
            if not rebuilt or step['time_ns']-rebuilt[-1]['origin_time_ns']>=horizon:
                prev=rebuilt[-1] if rebuilt else None
                rebuilt.append(dict(group_id=len(rebuilt),origin_time_ns=step['time_ns'],horizon_ns=horizon,
                    row_indices=[],relative_times_ns=[],tail_truncated_possible=True,recovery_not_established=prev is not None,
                    boundary_split_within_horizon=prev is not None and step['time_ns']-prev['last_deposit_time_ns']<horizon,
                    electronics_state='reset_nominal_isolated_window'))
            g=rebuilt[-1];g['row_indices'].append(step['raw_row_index']);g['relative_times_ns'].append(step['time_ns']-g['origin_time_ns']);g['last_deposit_time_ns']=step['time_ns']
        C.equal(event['pulse_groups'],rebuilt,'original group/deposition clock ledger')
        C.equal(not rebuilt,event['zero_ge'],'zero group assignment')
        for g in rebuilt:
            groups.append(dict(key='AK02-e'+str(eid)+'-d'+str(eid)+'-g'+str(g['group_id']),
                event_index=index,event_id=eid,global_decay_id=eid,namespace=event['namespace'],group=g,
                event_sha256=G.digest_bytes(G.encoded(event))))
    C.require(1<=len(events)<=8 and len(groups)<=4 and total_rows<=100,'tiny native cohort bound','not_supported')
    return groups


def parse_primary_ids(value):
    """Explicit whole-primary selector: canonical decimal CSV, in request order."""
    C.require(type(value) is str and len(value)<=55 and
        re.fullmatch(r'(?:0|[1-9][0-9]{0,5})(?:,(?:0|[1-9][0-9]{0,5}))*',value),
        'PrimaryIds requires quoted canonical decimal CSV (0..999999)', 'invalid_selection')
    ids=[int(token) for token in value.split(',')]
    C.require(1<=len(ids)<=8 and len(set(ids))==len(ids),
        'PrimaryIds requires 1..8 unique primaries', 'invalid_selection')
    return ids


def load_plan(reader, policy, primary_ids=None):
    """Read existing radiation/cache provenance; never invoke legacy campaigns."""
    ids=list(COHORT) if primary_ids is None else parse_primary_ids(primary_ids)
    c=reader.json(BATCH+'/config.json')
    C.equal(reader.digest(BATCH+'/config.json'),reader.path(BATCH+'/config.sha256').read_text().strip(),'existing batch pin')
    reader.digest(BATCH+'/config.sha256')
    C.equal(c['kind'],'native_checkpoint_batch_v1','cache provenance kind')
    m=c['models']['AK02']; d=reader.json(CONTRACT); export=reader.json(EXPORT)
    C.equal(export['kind'],'selected_native_hdf5_pilot_v1','radiation exporter kind')
    C.equal(export['status'],'exported_checked_inputs','checked radiation export')
    C.equal(export['contracts']['AK02']['file'],'AK02.json','contract filename')
    reader.digest(CONTRACT,export['contracts']['AK02']['sha256'])
    C.equal((d['kind'],d['status'],d['model_id']),('selected_native_hdf5_pilot_v1','complete','AK02'),'radiation contract')
    C.equal(d['source_sha256'],export['source_sha256'],'original contract source bindings')
    C.equal(d['input_sha256'],export['input_sha256'],'original contract input bindings')
    for n,h in d['input_sha256'].items():reader.digest(n,h)
    C.equal(d['prepared'],m['prepared'],'checked cache geometry')
    C.equal(d['model_sha256'],reader.digest('models/AK02.yaml'),'canonical model')
    C.equal(d['prepared']['model_sha256'],d['model_sha256'],'prepared model')
    C.equal(d['prepared'],reader.json('.local/cs137-1m/inputs/AK02/prepared.json'),'original prepared geometry')
    for n in NUMERICAL:reader.digest(n,c['source_sha256'][n])
    C.equal(c['expected_environment']['environment_manifest_sha256'],reader.digest('simulation/Manifest.toml'),'pinned environment')
    C.equal(c['settings'],{k:SETTINGS[k] for k in c['settings']},'existing cache physics settings')
    cache=BATCH+'/'+m['cache_file'].replace('\\','/');reader.digest(cache,m['cache_sha256'])
    catalog=reader.json('models/catalog.json'); entry=next(e for e in catalog['detectors'] if e['id']=='AK02')
    for dep in entry.get('dependencies',[]):reader.digest('models/'+dep['path'],dep['sha256'])
    # Every requested ID must occur once; no fallback or failure-avoiding selection.
    events=[]
    for eid in ids:
        chosen=[e for e in d['events'] if e['namespace']=='cs137-1m' and e['event_id']==eid]
        C.equal(len(chosen),1,'declared selected primary '+str(eid));events.append(chosen[0])
    groups=expected_groups(events,d['prepared'])
    C.equal([e['event_id'] for e in events],ids,'declared cohort')
    if primary_ids is None:
        C.equal((sum(e['zero_ge'] for e in events),len(groups)),(1,2),'declared zero/group census')
    else:
        C.require(groups,'Zero-only PrimaryIds selection is not supported','not_supported')
    sources={n:reader.digest(n) for n in SOURCES}
    plan=dict(model='AK02',selected_primary_ids=ids,events=events,groups=groups,prepared=d['prepared'],
        selected_census=dict(initial_primaries=len(events),zero_ge_primaries=sum(e['zero_ge'] for e in events),
                             nonzero_primaries=sum(not e['zero_ge'] for e in events),groups=len(groups)),
        population_reference=d['input_population_reference'],nonselected_response=None,
        cache_file=cache,cache_sha256=m['cache_sha256'],expected_field_fingerprint=m['expected_field_fingerprint'],
        model_sha256=d['model_sha256'],readout_contact_id=entry['readout_contact_id'],
        expected_environment=c['expected_environment'],settings=dict(SETTINGS,native_failure_policy=policy),
        source_sha256=sources,units=dict(raw_position='m',local_position='mm',time='ns',truth_energy='keV',signed_charge='induced_equivalent_energy_keV'),
        seed_rule=d['seed_rule'],input_files=[CONTRACT,EXPORT,BATCH+'/config.json',BATCH+'/config.sha256'])
    if primary_ids is not None:plan['primary_selection_mode']='explicit'
    return plan


def python_runtime():
    return dict(executable=sys.executable,version=sys.version,sha256=hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest())


def verify_runtime(reader, actual, plan, exe):
    C.equal(actual['environment'],plan['expected_environment'],'loaded native environment')
    C.equal((actual['threads'],actual['blas_threads']),(2,1),'child thread limits')
    C.equal(actual['boundary_native_sha256'],'0358c255e37c38f62eee6f1e476c0ed48560708dfcd3d367d2688eaa022232ad','SSD drift source')
    C.equal(actual['worker_source'],str(reader.path('simulation/native_groups.jl').resolve()),'loaded worker source')
    actual.update(launcher_executable=exe,launcher_sha256=hashlib.sha256(Path(exe).read_bytes()).hexdigest(),
                  executable_sha256=hashlib.sha256(Path(actual['executable']).read_bytes()).hexdigest())


def probe_runtime(reader, plan):
    exe=R.julia_executable()
    cmd=[exe,'--startup-file=no','--project=simulation','--threads=2','--compiled-modules=existing',
         str(reader.path('simulation/native_groups.jl')),'--probe']
    probe=R.child(cmd,str(reader.root),timeout=60,limit=65536)
    C.require(probe['exit_code']==0 and not probe['output_limit_exceeded'],'Native runtime probe failed: '+probe['output'],'unsupported_runtime')
    actual=C.decode(probe['output']); verify_runtime(reader,actual,plan,exe)
    return actual,probe


def verify_charge(path, group, plan, runtime, extra_files=()):
    out=C.Reader(path); r=out.json('charge.json')
    C.equal(G.inventory(path),sorted([*extra_files,'charge.json',*(['COMMIT.json'] if (path/'COMMIT.json').exists() else [])]),'charge file set')
    C.equal(r['kind'],'native_charge_group_v1','charge kind');C.equal(r['group'],group,'complete group identity')
    C.equal(r['runtime'],G.raw_runtime(runtime),'group loaded runtime')
    for k in ('settings','cache_sha256','model_sha256','readout_contact_id','units'):
        C.equal(r[k],plan[k],'charge '+k)
    C.require(C.number(r['native_seconds'],'native calculation seconds')>=0,'negative timing')
    C.equal(r['field_solve_seconds'],0,'no field solve');C.equal(r['readout'],None,'readout pending')
    native=r['native'];error=r['error']
    if r['status']=='native_failed':
        C.equal(plan['settings']['native_failure_policy'],'record','explicit failure recording')
        C.equal((native,r['transport_flags']),(None,None),'unknown native quantities')
        C.require(isinstance(error,dict),'missing exact native error')
        if error.get('type')=='ArgumentError':
            C.require(error.get('message') in ('Noncontact endpoint outside crystal','Invalid waveform support'),'unexpected native ArgumentError')
            C.equal(error['exact_error'],'ArgumentError: '+error['message'],'exact native error')
            C.equal(error['stage'],'NativeLiExample.native_event','native failure stage')
        else:
            C.equal(error['type'],'NativeBoundaryStall','allowed boundary failure')
            C.integer(error['step'],'boundary step',1,5001)
            C.equal(error['message'],'Native floating-boundary projection exhausted; unwritten path row refused at step '+str(error['step']),'exact boundary error')
            C.equal(error['charge_unknown'],True,'unknown boundary charge')
            for k in ('start_position_m','last_valid_position_m','rejected_position_m'):
                C.equal(len(error[k]),3,'boundary vector');[C.number(x,'boundary coordinate') for x in error[k]]
    else:
        C.equal(r['status'],'native_completed','native status');C.equal(error,None,'successful error')
        C.require(isinstance(native,dict),'missing native charge')
        t=native['times'];q=native['signal'];steps=native['steps']
        C.require(2<=len(t)<=500000 and len(t)==len(q),'full charge dimensions')
        C.equal(t,[k*plan['settings']['drift_dt_ns'] for k in range(len(t))],'full native support/grid')
        [C.number(x,'signed charge') for x in q];C.equal(q[0],0,'initial charge')
        event=plan['events'][group['event_index']]; byrow={s['raw_row_index']:s for s in event['steps']}
        C.equal([s['raw_row_index'] for s in steps],group['group']['row_indices'],'native step/raw-row order')
        endpoints=[]
        for s in steps:
            source=byrow[s['raw_row_index']]
            C.equal(s['deposited_energy_keV'],source['energy_keV'],'native truth deposit')
            C.equal(s['deposition_delay_ns'],source['time_ns']-group['group']['origin_time_ns'],'native deposition delay')
            C.equal(s['parcel_weight_keV'],source['energy_keV']/plan['settings']['parcels'],'independent parcel weight')
            C.number(s['final_induced_keV'],'step signed endpoint')
            C.equal(len(s['endpoints']),2*plan['settings']['parcels'],'complete carrier parcels')
            C.equal(sorted((e['parcel_index'],e['species']) for e in s['endpoints']),
                    [(i,species) for i in range(1,plan['settings']['parcels']+1) for species in ('electron','hole')],'parcel identities')
            for ep in s['endpoints']:
                n=C.integer(ep['samples'],'drift samples',1,5001)
                C.require(type(ep['step_limit_reached']) is bool and ep['step_limit_reached']==(n>=5001),'step-limit flag')
                C.require(type(ep['inside_semiconductor']) is bool,'endpoint membership flag')
                C.require(ep['inside_semiconductor'] or ep['contact_ids'],'noncontact endpoint outside crystal')
                C.equal(len(ep['position_mm']),3,'endpoint vector');[C.number(x,'endpoint coordinate') for x in ep['position_mm']]
                C.require(ep['contact_ids']==sorted(set(ep['contact_ids'])) and all(type(v) is int and v>=1 for v in ep['contact_ids']),'contact IDs')
                C.equal(ep['status'],'contact' if ep['contact_ids'] else 'step_limit' if ep['step_limit_reached'] else 'stopped_without_contact','endpoint flag')
            endpoints.extend(s['endpoints'])
        C.close(q[-1],sum(s['final_induced_keV'] for s in steps),'summed signed endpoint')
        flags=dict(carrier_parcels=len(endpoints),geometric_contacts=sum(bool(e['contact_ids']) for e in endpoints),
                   step_limits=sum(e['step_limit_reached'] for e in endpoints),stopped_without_contact=sum(e['status']=='stopped_without_contact' for e in endpoints))
        C.equal(r['transport_flags'],flags,'independent endpoint/limit counts')
    out.recheck();return r


def initialize(reader, dest, name, plan, runtime):
    (dest/'inputs').mkdir()
    for i,n in enumerate(plan['input_files']):G.write_bytes(dest/'inputs'/str(i),reader.path(n).read_bytes())
    reader.recheck()
    manifest=dict(kind=KIND,schema_version=1,name=name,plan=plan,runtime=runtime,python_runtime=python_runtime(),
                  source_snapshot=G.stamps(reader,list(reader.watched)))
    G.write_json(dest/'manifest.json',manifest)
    for n in ('charge','attempts','receipts'):(dest/n).mkdir()
    (dest/'receipts/charge').mkdir()
    out=C.Reader(dest)
    # Progress authority must exist before INITIAL can mark initialization done.
    G.write_json(dest/'run.json',dict(kind=KIND,schema_version=1,manifest_sha256=out.digest('manifest.json'),
        status='paused',verification_final=False,expected_groups=len(plan['groups']),completed_groups=0,completed_keys=[],
        selected_census=plan['selected_census']))
    G.write_json(dest/'INITIAL.json',dict(kind=KIND,schema_version=1,
        manifest=G.stamps(out,['manifest.json'])['manifest.json'],inputs=G.stamps(out,['inputs/'+n for n in G.inventory(dest/'inputs')])))


def validate_saved(reader, dest, name, plan):
    out=C.Reader(dest);initial=out.json('INITIAL.json')
    C.equal((initial['kind'],initial['schema_version']),(KIND,1),'initial receipt')
    G.check_stamps(out,{'manifest.json':initial['manifest'],**initial['inputs']})
    C.equal(G.inventory(dest/'inputs'),sorted(n.removeprefix('inputs/') for n in initial['inputs']),'input snapshot inventory')
    m=out.json('manifest.json');mh=out.digest('manifest.json')
    C.equal((m['kind'],m['schema_version'],m['name']),(KIND,1,name),'manifest identity')
    C.equal(m['plan'],plan,'entire original expected ledger/configuration/source pins')
    C.equal(expected_groups(plan['events'],plan['prepared']),plan['groups'],'full expected census')
    C.equal(m['python_runtime'],python_runtime(),'driver runtime pin')
    G.check_stamps(reader,m['source_snapshot'])
    for i,n in enumerate(plan['input_files']):C.equal(out.digest('inputs/'+str(i)),reader.digest(n),'exact original snapshot')
    runtime=m['runtime']
    for k,h in (('launcher_executable','launcher_sha256'),('executable','executable_sha256')):
        C.equal(hashlib.sha256(Path(runtime[k]).read_bytes()).hexdigest(),runtime[h],'recorded runtime bytes')
    expected={g['key'] for g in plan['groups']};done=[]
    C.require((dest/'charge').is_dir() and (dest/'receipts/charge').is_dir(),'missing charge/witness inventory')
    C.require(all(p.is_dir() and p.name in expected for p in (dest/'charge').iterdir()),'extra native group')
    C.require(all(p.is_file() and (p.name.removesuffix('.json') in expected or re.fullmatch(r'.+\.json\.pending-[0-9a-f]{12}',p.name) and p.name.split('.json.pending-')[0] in expected)
                  for p in (dest/'receipts/charge').iterdir()),'extra native witness')
    for g in plan['groups']:
        p=dest/'charge'/g['key']
        if p.exists() or G.witness_path(p).exists():
            _,receipt=G.committed(p,G.binding(mh,'charge',g['key']))
            C.equal(set(receipt['artifacts']),{'charge.json'},'native commit file set')
            verify_charge(p,g,plan,runtime);done.append(g['key'])
    saved=out.json('run.json') # Initialized progress authority is never optional.
    C.require({'kind','schema_version','manifest_sha256','status','expected_groups','completed_groups','completed_keys'}
              <=set(C.object_value(saved,'native progress authority')),'Incomplete native progress authority','missing_commit')
    C.equal(saved['kind'],KIND,'progress kind')
    C.equal(C.integer(saved['schema_version'],'progress schema',1,1),1,'progress schema')
    C.equal(saved['manifest_sha256'],mh,'progress manifest binding')
    C.require(saved['status'] in ('paused','running','failed',*TERMINAL),'progress status')
    C.equal(C.integer(saved['expected_groups'],'progress expected count',high=4),len(plan['groups']),'progress expected census')
    reported=saved['completed_keys']
    C.require(isinstance(reported,list) and all(isinstance(k,str) and k in expected for k in reported),
              'Invalid previously reported group identities','missing_commit')
    C.require(len(set(reported))==len(reported),'Duplicate previously reported group identities','missing_commit')
    C.equal(C.integer(saved['completed_groups'],'saved committed count',high=4),len(reported),'progress count/key agreement')
    C.require(set(reported)<=set(done),'Previously reported native commit disappeared; refuse recomputation','missing_commit')
    if (dest/'COMPLETE.json').exists():
        complete=out.json('COMPLETE.json')
        C.equal((complete['kind'],complete['manifest_sha256']),(KIND,mh),'completion binding')
        C.equal(complete['completed_keys'],[g['key'] for g in plan['groups']],'complete expected ledger')
        C.equal(done,complete['completed_keys'],'complete committed set')
        G.check_stamps(out,complete['artifacts'])
        saved=out.json('run.json');C.require(saved['status'] in TERMINAL and saved['verification_final'],'driver completion')
        C.equal(saved['selected_census'],plan['selected_census'],'final zero/primary census')
        C.equal(saved['completed_groups'],len(done),'final group census')
        C.equal(saved['completed_keys'],complete['completed_keys'],'final progress group identities')
        failures=sum(C.Reader(dest/'charge'/k).json('charge.json')['status']=='native_failed' for k in done)
        C.equal(saved['native_failed_groups'],failures,'final native failure census')
        C.equal(saved['status'],TERMINAL[bool(failures)],'final native status')
    out.recheck();reader.recheck();return m,mh,done


def run_session(reader, dest, manifest, groups, attempt, callback, worker_source='simulation/native_groups.jl'):
    """One serial native worker, verified durable commit before each ACK."""
    runtime=manifest['runtime'];req=dict(kind=KIND,root=str(dest),plan=manifest['plan'],
        runtime=G.raw_runtime(runtime),groups=groups)
    G.write_json(attempt/'session.json',req)
    argv=[runtime['launcher_executable'],'--startup-file=no','--project=simulation','--threads=2','--compiled-modules=existing',
          str(reader.path(worker_source)),'--session',str(attempt/'session.json')]
    env=dict(os.environ,JULIA_NUM_THREADS='2',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',JULIA_PKG_OFFLINE='true',
             JULIA_LOAD_PATH='@;@stdlib' if os.name=='nt' else '@:@stdlib',PYTHONDONTWRITEBYTECODE='1')
    p=subprocess.Popen(argv,cwd=reader.root,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                       creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    messages=queue.Queue();started=time.monotonic();events=[];terminal=False
    def drain():
        try:
            with (attempt/'worker.log').open('xb') as log:
                total=0
                while True:
                    line=p.stdout.readline(65537)
                    if not line:break
                    total+=len(line);log.write(line);log.flush()
                    if len(line)>65536 or total>4*1024**2:raise RuntimeError('native worker output bound')
                    messages.put(line)
        except BaseException as error:messages.put(error)
        finally:messages.put(None)
    thread=threading.Thread(target=drain,daemon=True)
    try:
        G.write_json(attempt/'worker-process.json',dict(pid=p.pid,arguments=argv))
        thread.start()
        while True:
            remaining=600-(time.monotonic()-started);C.require(remaining>0,'native worker timeout','child_failed')
            try:line=messages.get(timeout=remaining)
            except queue.Empty:raise C.Rejected('child_failed','native worker timeout')
            if line is None:break
            if isinstance(line,BaseException):raise line
            text=line.decode('utf-8',errors='strict').strip()
            if not text.startswith('{'):continue
            event=C.decode(text);events.append(event)
            C.require(not terminal,'worker event after session_done')
            if event.get('kind')=='session_done':terminal=True;continue
            C.equal(event.get('kind'),'group_ready','native worker protocol')
            callback(event)
            p.stdin.write(G.encoded(dict(kind='committed',key=event['key'])));p.stdin.flush()
        code=p.wait(timeout=max(1,600-(time.monotonic()-started)))
        C.require(code==0 and terminal,'native worker failed; partial evidence retained','child_failed')
        return dict(arguments=argv,exit_code=code,wall_seconds=time.monotonic()-started,events=events)
    finally:
        if p.poll() is None:p.kill();p.wait()
        if thread.ident is not None:thread.join(timeout=5)
        p.stdin.close();p.stdout.close()
        G.write_json(attempt/'execution.json',dict(arguments=argv,exit_code=p.returncode,wall_seconds=time.monotonic()-started))


def generate(root, name, resume=False, dry_run=False, stop_after_new_groups=None, native_failure_policy=None):
    result=dict(kind=KIND,schema_version=1,status='blocked',verification_final=False,findings=[],scientific_workers_launched=0,completed_keys=[],
                limitations=['Native charge only; electronics/end-to-end M5b and physical Li CCE remain pending.'])
    dest=None;attempt=None
    try:
        C.require(os.name=='nt','bounded Windows interface','not_supported')
        C.require(re.fullmatch('[A-Za-z0-9_-]{1,32}',name or ''),'bounded safe output name','unsafe_path')
        C.require(stop_after_new_groups is None or type(stop_after_new_groups) is int and 1<=stop_after_new_groups<=4,'stop bound must be 1..4','invalid_flags')
        C.require(not resume or native_failure_policy is None,'policy overrides forbidden on resume','invalid_flags')
        C.require(native_failure_policy in (None,'abort','record'),'native failure policy','invalid_flags')
        reader=C.Reader(root);target=reader.path(BASE+'/'+name)
        C.require(len(str(target))+100<260,'bounded Windows paths including native temporary files','unsafe_path')
        C.require(target.is_dir() if resume else not target.exists(),'resume requires existing root; new name must not exist','output_exists')
        with ExitStack() as leases:
            if resume:leases.enter_context(C.existing_lock(C.Reader(target),'run.lock'))
            policy=C.Reader(target).json('manifest.json')['plan']['settings']['native_failure_policy'] if resume else native_failure_policy or 'abort'
            C.require(policy in ('abort','record'),'invalid saved native failure policy','invalid_flags')
            plan=load_plan(reader,policy)
            result.update(output=BASE+'/'+name,selected_census=plan['selected_census'],expected_groups=len(plan['groups']),completed_groups=0)
            if resume:
                manifest,mh,done=validate_saved(reader,target,name,plan)
                result.update(completed_groups=len(done),completed_keys=list(done),manifest_sha256=mh)
                if (target/'COMPLETE.json').exists():
                    saved=C.Reader(target).json('run.json');result.update(status=saved['status'],verification_final=True,
                        idempotent=True,read_only=True,native_failed_groups=saved['native_failed_groups']);return result
                C.require(C.Reader(target).json('run.json')['status'] not in TERMINAL,
                          'Terminal driver data without COMPLETE; preserve and refuse','uncommitted_boundary')
            if dry_run:
                reader.recheck();result.update(status='paused' if resume else 'planned',verification_final=True,read_only=True);return result
            actual,probe=probe_runtime(reader,plan);result['runtime_probe']=probe
            if resume:C.equal(actual,manifest['runtime'],'runtime cannot be rebased')
            reader.recheck()
            if not resume:
                target.parent.mkdir(parents=True,exist_ok=True);target.mkdir();dest=target
                G.write_bytes(dest/'run.lock',b'M5b native charge output lease\n')
                leases.enter_context(C.existing_lock(C.Reader(dest),'run.lock'))
                leases.enter_context(G.failure_status(dest,result))
                initialize(reader,dest,name,plan,actual)
                result['manifest_sha256']=C.Reader(dest).digest('manifest.json')
                manifest,mh,done=validate_saved(reader,dest,name,plan)
            else:
                dest=target;leases.enter_context(G.failure_status(dest,result))
            attempt=dest/'attempts'/uuid.uuid4().hex[:12];attempt.mkdir()
            missing=[g for g in plan['groups'] if g['key'] not in done]
            selected=missing if stop_after_new_groups is None else missing[:stop_after_new_groups]
            remaining=iter(selected);active=[next(remaining,None)]
            result.update(status='running',completed_groups=len(done),completed_keys=list(done));G.status(dest/'run.json',result)
            def callback(event):
                g=active[0];C.require(g is not None and event['key']==g['key'],'unexpected/duplicate native group')
                C.equal(event['directory'],'charge-'+g['key'],'staged native path')
                stage=C.Reader(attempt).path(event['directory'])
                verify_charge(stage,g,plan,actual);reader.recheck()
                G.commit(stage,dest/'charge'/g['key'],G.binding(mh,'charge',g['key']))
                # Independently reopen/validate after commit and before acknowledging.
                G.committed(dest/'charge'/g['key'],G.binding(mh,'charge',g['key']))
                verify_charge(dest/'charge'/g['key'],g,plan,actual)
                done.append(g['key']);active[0]=next(remaining,None)
                result.update(completed_groups=len(done),completed_keys=list(done));G.status(dest/'run.json',result)
            if selected:
                result['scientific_workers_launched']=1
                result['child']=run_session(reader,dest,manifest,selected,attempt,callback)
            C.require(active[0] is None,'worker omitted selected group','child_failed')
            manifest,mh,done=validate_saved(reader,dest,name,plan)
            failures=sum(C.Reader(dest/'charge'/k).json('charge.json')['status']=='native_failed' for k in done)
            result.update(completed_groups=len(done),completed_keys=list(done),native_failed_groups=failures,verification_final=True)
            if len(done)<len(plan['groups']):
                result['status']='paused';G.status(dest/'run.json',result);return result
            result.update(status=TERMINAL[bool(failures)],completion_authority='driver full selected primary/zero/group census reconciliation')
            reader.recheck();G.status(dest/'run.json',result)
            files=['run.json',*['charge/'+n for n in G.inventory(dest/'charge')],*['receipts/'+n for n in G.inventory(dest/'receipts')]]
            G.write_json(dest/'COMPLETE.json',dict(kind=KIND,manifest_sha256=mh,
                completed_keys=[g['key'] for g in plan['groups']],artifacts=G.stamps(C.Reader(dest),files)))
            return result
    except BaseException as error:
        result.update(status='failed' if dest else 'blocked',verification_final=False)
        if C.finding(error) not in result['findings']:result['findings'].append(C.finding(error))
        if attempt:G.write_json(attempt/'failure.json',dict(finding=C.finding(error),result=result))
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--name',required=True);p.add_argument('--resume',action='store_true');p.add_argument('--dry-run',action='store_true')
    p.add_argument('--stop-after-new-groups',type=int);p.add_argument('--native-failure-policy',choices=('abort','record'))
    a=p.parse_args(argv);result=generate(ROOT,**vars(a));print(G.encoded(result).decode(),end='')
    return 0 if result['verification_final'] else 2


if __name__=='__main__':sys.exit(main())
