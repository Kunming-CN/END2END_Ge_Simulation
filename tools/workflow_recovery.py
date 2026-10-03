"""Two sealed pre-response interruptions through one prefix-copy lifecycle.

No failed-stage retry or general prefix recovery. Original bytes remain immutable.
Distinct literal bootstrap/publication authorities admit only a new derivative
that copies checked radiation inputs and executes response/results only.
"""
import copy
import os
from pathlib import Path
import shutil
import time

import scenario_workflow as W
import workflow_inspection as I

AUTHORITY='.local/product-delivery-v1/implementation/M14a1-COLD-ENTRY-FAILED-PREFIX.json'
AUTHORITY_SHA='8c3d2cefd3e20c1181783768ec085e1ef8ccd2a61382d006517514fd07ae085b'
PARENT='m14a-gamma-ui-02'
PARENT_DISPATCH='a83b61161325bac67e1fae597262f0d6'
PATCHED_BOOTSTRAP='b742766ff91cd94adad81f96bb4ac5a4d6764c5a48e53ae3aa6c43fdf576f0dd'
PREFIX=W.STAGES[:3]
STATE='.local/local-control-v1'
KM_PARENT='m14a2-km-ui-01'
KM_AUTHORITY='.local/product-delivery-v1/implementation/M14a2-KM-DISPATCH-FAILURE-BASIS.json'
KM_AUTHORITY_SHA='276bb5970a6222f274aace1fe8a7bc08639e3bca5d011e6c531b14900c253016'
KM_DISPATCH='18d696f97407757205581716d2790f4f'
KM_PENDING='run.json.pending-10972'


def eligible_name(name):return name in (PARENT,KM_PARENT)


def preserved_inventory(directory):
    """Only the sealed failure checker includes unsuccessful pending evidence."""
    files=W.inventory(directory)
    for current,folders,names in os.walk(directory,followlinks=False):
        for name in names:
            if '.pending-' in name:
                ref=(Path(current)/name).relative_to(directory).as_posix();path=W.safe_path(directory,ref)
                files[ref]={'sha256':W.sha(path),'bytes':path.stat().st_size}
    return files


def km_parent(root=W.ROOT,*,historical=False):
    """The literal reviewed interruption only, never arbitrary partial recovery."""
    path=W.safe_path(root,KM_AUTHORITY);W.require(W.sha(path)==KM_AUTHORITY_SHA,'Unrecognized KM publication-failure authority.')
    authority=W.read(path);directory=W.run_path(KM_PARENT,root)
    W.require(authority['kind']=='m14a2_km_completed_ledger_dispatch_interruption_v1' and authority['name']==KM_PARENT and
              authority['dispatch_id']==KM_DISPATCH and authority['original_run_sha256']==W.sha(directory/'run.json') and
              authority['original_pending_sha256']==W.sha(directory/KM_PENDING) and
              W.encoded(preserved_inventory(directory))==W.encoded(authority['original_inventory_including_pending']) and
              W.sha(W.safe_path(root,authority['driver_log']))==authority['driver_log_sha256'] and
              W.sha(W.safe_path(path.parent,authority['source_archive']))==authority['source_archive_sha256'],
              'Original KM canonical/pending/log/source or complete inventory changed.')
    receipt=W.read(directory/'run.json');pending=W.read(directory/KM_PENDING);plan=W.read(directory/'resolved-config.json');W.saved_plan(plan)
    W.require(receipt['kind']==W.KIND and receipt['status']=='running' and set(receipt['stages'])==set(PREFIX) and
              receipt['configuration_sha256']==plan['configuration_sha256'] and W.encoded(receipt['resolved'])==W.encoded(plan['resolved']) and
              plan['resolved']['selection']['name']==KM_PARENT and plan['resolved']['selection']['detector']=='KMRC01_candidate' and
              plan['resolved']['selection']['source']==W.CS and not (directory/'response').exists() and not (directory/'ring-request.json').exists(),
              'Not the original KM pre-response publication interruption.')
    stage=receipt['stages']['event_ledger'];child=pending['stages']['event_ledger']
    W.require(stage['status']=='dispatch_intent' and set(child)==set(stage)|{'pid','process_identity'} and child['status']=='running' and
              type(child['pid']) is int and child['pid']>0 and type(child['process_identity']) is str and child['process_identity']!='unknown',
              'Pending ledger does not identify the exact dispatched child.')
    compare=copy.deepcopy(pending);compare['stages']['event_ledger']=copy.deepcopy(stage)
    W.require(W.encoded(compare)==W.encoded(receipt) and all(child[k]==stage[k] for k in stage if k!='status'),
              'Pending receipt changed beyond the committed ledger child identity.')
    log=W.safe_path(root,authority['driver_log']).read_text(encoding='utf-8')
    W.require('PermissionError: [WinError 5]' in log and 'FileExistsError:' in log and KM_PENDING in log and
              W.encoded(W.read(directory/'event_ledger.log'))==W.encoded(W.read(directory/'transport/stream/manifest.json')) and
              authority['event_ledger_process_exit_code'] is None and authority['event_ledger_elapsed_seconds'] is None,
              'Publication interruption/terminal ledger evidence is inconsistent.')
    if not historical:
        for ref,h in receipt['resolved']['source_sha256'].items():
            if ref not in ('tools/scenario_workflow.py','tools/workflow_recovery.py'):
                W.require(W.sha(W.safe_path(root,ref))==h,'Original KM numerical producer/input changed: '+ref)
        W.require(W.runtime_identity(plan['resolved']['selection']['threads'])==plan['resolved']['runtime_identity'],'Original KM runtime bytes changed.')
        commands=W.stage_commands(directory,receipt['resolved'],root,{'JULIA_EXE':receipt['runtime']['julia']})
    for key in PREFIX:
        record=receipt['stages'][key]
        W.require(historical or record['arguments']==commands[key],'Original KM dispatch arguments changed.')
        if key!='event_ledger':W.require(record['status']=='completed' and record['exit_code']==0,'Original geometry/radiation is incomplete.')
        actual=W.validate_stage(directory,key,receipt['resolved'],root,historical=historical)
        W.require(W.encoded(actual)==W.encoded(authority['verified_stage_artifacts'][key]) and
                  (key=='event_ledger' or W.encoded(actual)==W.encoded(record['artifacts'])),'Original KM prefix semantics/inventory differ.')
    # An inspected view of original evidence, never written over the original.
    receipt=copy.deepcopy(receipt);receipt['stages']['event_ledger']=dict(child,
        exit_code=None,elapsed_seconds=None,finished_utc=None,artifacts=authority['verified_stage_artifacts']['event_ledger'],
        completion_basis='verified terminal saved ledger artifacts; process exit/time unobserved')
    authority=dict(authority,original_inventory=authority['original_inventory_including_pending'])
    return authority,receipt,plan


def parent(root=W.ROOT,*,historical=False):
    authority_path=W.safe_path(root,AUTHORITY)
    W.require(W.sha(authority_path)==AUTHORITY_SHA,'Unrecognized preserved transport-prefix authority.')
    authority=W.read(authority_path);directory=W.run_path(PARENT,root)
    W.require(authority['kind']=='m14a1_cold_entry_failed_prefix_authority_v1' and authority['original_name']==PARENT and
              authority['completed_prefix']==list(PREFIX) and W.sha(directory/'run.json')==authority['run_sha256'] and
              W.sha(directory/'response.log')==authority['bootstrap_log_sha256'] and
              W.encoded(W.inventory(directory))==W.encoded(authority['original_inventory']),
              'Preserved failed-prefix bytes or authority changed.')
    frozen=W.read(W.safe_path(root,authority['source_freeze']))
    W.require(W.sha(W.safe_path(root,authority['source_freeze']))==authority['source_freeze_sha256'],
              'Original source freeze changed.')
    receipt=W.read(directory/'run.json');plan=W.read(directory/'resolved-config.json');W.saved_plan(plan)
    W.require(receipt['kind']==W.KIND and receipt['status']=='failed' and set(receipt['stages'])==set((*PREFIX,'response')) and
              receipt['configuration_sha256']==plan['configuration_sha256'] and W.encoded(receipt['resolved'])==W.encoded(plan['resolved']) and
              plan['resolved']['selection']['name']==PARENT and plan['resolved']['selection']['detector']=='SAP22' and
              plan['resolved']['selection']['source']==W.GAMMA and plan['resolved']['selection']['electronics']['gain']==21 and
              not (directory/'response').exists(),
              'Only the exact SAP22 gamma bootstrap failure without response output is admitted.')
    for name,stamp in frozen['source_records'].items():
        if name in receipt['resolved']['source_sha256']:
            W.require(receipt['resolved']['source_sha256'][name]==stamp['sha256'],'Original producer attribution differs from its freeze.')
    # The pinned authority binds every original dispatch argument. Historical
    # retirement must not reconstruct those arguments with an upgraded producer.
    # New inspection/transfer still reconstruct and check current dispatch rules.
    commands=None if historical else W.stage_commands(directory,receipt['resolved'],root,{'JULIA_EXE':receipt['runtime']['julia']})
    failed=receipt['stages']['response'];text=(directory/'response.log').read_text(encoding='utf-8')
    W.require(failed['status']=='command_exited' and failed['exit_code']==1 and (historical or failed['arguments']==commands['response']) and
              'UndefVarError: `JSON` not defined in `Main`' in text and 'scenario_response.jl:210' in text,
              'Response failure is not the proved pre-entrypoint serialization error.')
    for stage in PREFIX:
        record=receipt['stages'][stage]
        W.require(record['status']=='completed' and record['exit_code']==0 and (historical or record['arguments']==commands[stage]),
                  'Original completed-prefix dispatch differs.')
        actual=W.validate_stage(directory,stage,receipt['resolved'],root,historical=historical)
        W.require(W.encoded(actual)==W.encoded(record['artifacts']),'Original completed-prefix inventory or semantics changed.')
    # The old request is evidence only. Rebuild it from the copied ledger for new work.
    W.require(W.encoded(W.read(directory/'gamma-request.json'))==W.encoded(W.gamma_request(directory,receipt['resolved'],root,historical=historical)),
              'Original request changed its complete transport ledger or settings.')
    transport=W.read(directory/'transport/run.json')
    W.require(transport['runtime']['emlow_manifest_sha256']==W.sha(directory/'emlow-data.json') and
              transport['runtime']['emlow_manifest'].replace('\\','/').endswith('/'+PARENT+'/emlow-data.json'),
              'Original radiation runtime attribution changed.')
    return authority,receipt,plan


def compatible(old,new):
    W.require(new['selection']['name']!=old['selection']['name'],'Choose a different unused derivative name.')
    prior=copy.deepcopy(old);prior['selection']['name']=new['selection']['name']
    old_pins=prior.pop('source_sha256');current=copy.deepcopy(new);new_pins=current.pop('source_sha256')
    W.require(W.encoded(prior)==W.encoded(current),'Derivative physical/electronics/numerics/runtime settings differ from its parent.')
    changed={name for name in old_pins if old_pins[name]!=new_pins.get(name)}
    if old['selection']['detector']=='KMRC01_candidate':
        allowed={'tools/scenario_workflow.py','tools/workflow_recovery.py'}
        W.require(set(new_pins)==set(old_pins) and changed==allowed and
                  all(new_pins[ref]==W.sha(W.ROOT/ref) for ref in allowed),
                  'Only the reviewed KM publication/coordinated-prefix source delta is permitted.')
        return sorted(changed)
    W.require(set(new_pins)-set(old_pins)=={'tools/workflow_recovery.py'} and not set(old_pins)-set(new_pins) and
              changed=={'simulation/scenario_response.jl','tools/scenario_workflow.py'} and
              new_pins['simulation/scenario_response.jl']==PATCHED_BOOTSTRAP,
              'Only the reviewed bootstrap and workflow-coordination source delta is permitted.')
    return sorted(changed|{'tools/workflow_recovery.py'})


def inspect_parent(job,root=W.ROOT,probe=None):
    is_km=job['name']==KM_PARENT;name=KM_PARENT if is_km else PARENT
    authority,receipt,plan=km_parent(root) if is_km else parent(root)
    authority_sha=KM_AUTHORITY_SHA if is_km else AUTHORITY_SHA
    W.require(job['id']==(KM_DISPATCH if is_km else PARENT_DISPATCH) and job['name']==name and W.encoded(job['plan'])==W.encoded(plan) and
              job['driver']==receipt['supervisor'],'Owned original dispatch/plan identity differs.')
    identities=[job['driver']]+[{'pid':r['pid'],'identity':r['process_identity']} for r in receipt['stages'].values()]
    W.require(all(W.identity_ended(d) for d in identities),'Original driver/stage is live or its lifetime is unknown.')
    quiet=(probe or I.inventories)(root)
    W.require(quiet['windows_succeeded'] and quiet['linux_succeeded'] and not quiet['relevant_windows_workers'] and not quiet['relevant_linux_workers'],
              'Successful fresh Windows/WSL quiescence is required.')
    observed=preserved_inventory(W.run_path(name,root)) if is_km else W.inventory(W.run_path(name,root))
    W.require(W.encoded(observed)==W.encoded(authority['original_inventory']),
              'Parent bytes changed during inspection.')
    return {'kind':'workflow_verified_transport_prefix_v1','parent_name':name,'parent_dispatch_id':job['id'],
            'parent_authority_sha256':authority_sha,'parent_configuration_sha256':plan['configuration_sha256'],
            'original_inventory':authority['original_inventory'],'ended_identities':identities,'quiescence':quiet,
            'original_source_sha256':receipt['resolved']['source_sha256'],'original_runtime':receipt['runtime'],
            'inspected_utc':W.utc(),'new_radiation_calls':0,'response_entrypoint_calls':0}


def release(job,plan,inspection,root=W.ROOT):
    W.require(eligible_name(job['name']) and inspection['parent_name']==job['name'] and inspection['parent_dispatch_id']==job['id'],
              'The sealed prefix inspection differs from its owned parent.')
    _,receipt,_=km_parent(root) if job['name']==KM_PARENT else parent(root);delta=compatible(receipt['resolved'],plan['resolved'])
    value=dict(inspection,derivative_name=plan['resolved']['selection']['name'],derivative_configuration_sha256=plan['configuration_sha256'],
               reviewed_changed_sources=delta,action='New derivative only; original failed root cannot resume or overwrite.')
    path=W.safe_path(root,STATE+'/verified-prefixes/'+job['name']+'.json');W.write(path,value,fresh=True)
    return W.sha(path)


def retirement(root=W.ROOT,*,name=PARENT):
    W.require(eligible_name(name),'Unrecognized historical transport prefix.')
    is_km=name==KM_PARENT;path=W.safe_path(root,STATE+'/verified-prefixes/'+name+'.json')
    if not path.exists():return None
    jobs=W.read(W.safe_path(root,STATE+'/workflow-jobs.json'))['jobs'];job=next((j for j in jobs if j['name']==name),None)
    W.require(job and job['status']=='verified_transport' and job.get('prefix_authority_sha256')==W.sha(path),
              'Verified-prefix retirement is not bound to the owned reservation.')
    value=W.read(path);authority,receipt,plan=km_parent(root,historical=True) if is_km else parent(root,historical=True)
    dispatch=KM_DISPATCH if is_km else PARENT_DISPATCH;authority_sha=KM_AUTHORITY_SHA if is_km else AUTHORITY_SHA
    identities=[receipt['supervisor']]+[{'pid':r['pid'],'identity':r['process_identity']} for r in receipt['stages'].values()]
    W.require(value['kind']=='workflow_verified_transport_prefix_v1' and value['parent_dispatch_id']==dispatch and
              value['parent_authority_sha256']==authority_sha and value['parent_configuration_sha256']==plan['configuration_sha256'] and
              W.encoded(value['original_inventory'])==W.encoded(authority['original_inventory']) and
              job['id']==dispatch and W.encoded(job['plan'])==W.encoded(plan) and job['driver']==receipt['supervisor'] and
              value['ended_identities']==identities and all(W.identity_ended(d) for d in identities) and
              value['quiescence']['windows_succeeded'] and value['quiescence']['linux_succeeded'] and
              not value['quiescence']['relevant_windows_workers'] and not value['quiescence']['relevant_linux_workers'],
              'Original prefix retirement or process identities changed.')
    return value


def verified_retirement(directory,root=W.ROOT):
    return eligible_name(directory.name) and directory==W.run_path(directory.name,root) and retirement(root,name=directory.name) is not None


def transfer(directory,plan,receipt,root=W.ROOT,probe=None):
    start=time.perf_counter();started=W.utc();name=KM_PARENT if plan['resolved']['selection']['detector']=='KMRC01_candidate' else PARENT
    is_km=name==KM_PARENT;value=retirement(root,name=name)
    W.require(value and value['derivative_name']==directory.name and value['derivative_configuration_sha256']==plan['configuration_sha256'],
              'No preserved authority permits this derivative.')
    _,original,_=km_parent(root) if is_km else parent(root);delta=compatible(original['resolved'],plan['resolved'])
    quiet=(probe or I.inventories)(root)
    W.require(quiet['windows_succeeded'] and quiet['linux_succeeded'] and not quiet['relevant_windows_workers'] and not quiet['relevant_linux_workers'],
              'Derivative dispatch quiescence did not pass.')
    source=W.run_path(name,root)
    names=[n for n in value['original_inventory'] if n.startswith('transport/') or n in ('geometry.log','radiation.log','event_ledger.log','emlow-data.json')]
    for ref in names:
        origin=W.safe_path(source,ref);target=W.safe_path(directory,ref);target.parent.mkdir(parents=True,exist_ok=True)
        with origin.open('rb') as incoming,target.open('xb') as outgoing:
            shutil.copyfileobj(incoming,outgoing);outgoing.flush();os.fsync(outgoing.fileno())
    W.verify_inventory(directory,{n:value['original_inventory'][n] for n in names})
    observed=preserved_inventory(source) if is_km else W.inventory(source)
    W.require(W.encoded(observed)==W.encoded(value['original_inventory']),'Parent changed during lossless transfer.')
    for stage in PREFIX:
        before=time.perf_counter();record=original['stages'][stage]
        actual=W.validate_stage(directory,stage,plan['resolved'],root)
        W.require(W.encoded(actual)==W.encoded(record['artifacts']),'Transferred prefix lost its stage semantics/inventory.')
        receipt['stages'][stage]={'status':'completed','reuse':'verified_transport_prefix','artifacts':actual,
                                'parent_name':name,'parent_run_sha256':value['original_inventory']['run.json']['sha256'],
                                'inherited_stage_receipt':record,'original_elapsed_seconds':record['elapsed_seconds'],
                                'fresh_validation_seconds':time.perf_counter()-before}
        if is_km and stage=='event_ledger':receipt['stages'][stage].update(exit_code=None,elapsed_seconds=None,finished_utc=None,
            completion_basis=record['completion_basis'],original_pending_ref=KM_PENDING,
            original_canonical_stage_receipt=W.read(source/'run.json')['stages'][stage],
            original_pending_stage_receipt=W.read(source/KM_PENDING)['stages'][stage])
    receipt['transport_reuse']={'parent_name':name,'authority_sha256':W.sha(W.safe_path(root,STATE+'/verified-prefixes/'+name+'.json')),
        'original_source_sha256':value['original_source_sha256'],'original_runtime':value['original_runtime'],
        'reviewed_changed_sources':delta,'transferred_artifacts':{n:value['original_inventory'][n] for n in names},
        'started_utc':started,'finished_utc':W.utc(),'transfer_and_validation_seconds':time.perf_counter()-start,
        'new_geometry_calls':0,'new_radiation_calls':0,'new_ledger_calls':0,
        'runtime_attribution':('Copied transport receipts retain original producer/runtime attribution. Ledger process exit/time was not observed.' if is_km else
            'Copied transport/run.json retains its original EMlow manifest path. Copied emlow-data.json is immutable supporting evidence, not a new transport runtime.')}
    if is_km:receipt['transport_reuse'].update(original_canonical_ref=W.BASE+'/'+name+'/run.json',
        original_pending_ref=W.BASE+'/'+name+'/'+KM_PENDING,original_pending_sha256=value['original_inventory'][KM_PENDING]['sha256'])

