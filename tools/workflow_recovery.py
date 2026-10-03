"""One reviewed derivative of the preserved Main.JSON bootstrap failure.

No failed-stage retry or general prefix recovery. Original bytes remain immutable.
The new run copies checked radiation inputs and executes response/results only.
"""
import copy
import os
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


def parent(root=W.ROOT):
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
    commands=W.stage_commands(directory,receipt['resolved'],root,{'JULIA_EXE':receipt['runtime']['julia']})
    failed=receipt['stages']['response'];text=(directory/'response.log').read_text(encoding='utf-8')
    W.require(failed['status']=='command_exited' and failed['exit_code']==1 and failed['arguments']==commands['response'] and
              'UndefVarError: `JSON` not defined in `Main`' in text and 'scenario_response.jl:210' in text,
              'Response failure is not the proved pre-entrypoint serialization error.')
    for stage in PREFIX:
        record=receipt['stages'][stage]
        W.require(record['status']=='completed' and record['exit_code']==0 and record['arguments']==commands[stage],
                  'Original completed-prefix dispatch differs.')
        actual=W.validate_stage(directory,stage,receipt['resolved'],root)
        W.require(W.encoded(actual)==W.encoded(record['artifacts']),'Original completed-prefix inventory or semantics changed.')
    # The old request is evidence only. Rebuild it from the copied ledger for new work.
    W.require(W.encoded(W.read(directory/'gamma-request.json'))==W.encoded(W.gamma_request(directory,receipt['resolved'],root)),
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
    W.require(set(new_pins)-set(old_pins)=={'tools/workflow_recovery.py'} and not set(old_pins)-set(new_pins) and
              changed=={'simulation/scenario_response.jl','tools/scenario_workflow.py'} and
              new_pins['simulation/scenario_response.jl']==PATCHED_BOOTSTRAP,
              'Only the reviewed bootstrap and workflow-coordination source delta is permitted.')
    return sorted(changed|{'tools/workflow_recovery.py'})


def inspect_parent(job,root=W.ROOT,probe=None):
    authority,receipt,plan=parent(root)
    W.require(job['id']==PARENT_DISPATCH and job['name']==PARENT and W.encoded(job['plan'])==W.encoded(plan) and
              job['driver']==receipt['supervisor'],'Owned original dispatch/plan identity differs.')
    identities=[job['driver']]+[{'pid':r['pid'],'identity':r['process_identity']} for r in receipt['stages'].values()]
    W.require(all(W.identity_ended(d) for d in identities),'Original driver/stage is live or its lifetime is unknown.')
    quiet=(probe or I.inventories)(root)
    W.require(quiet['windows_succeeded'] and quiet['linux_succeeded'] and not quiet['relevant_windows_workers'] and not quiet['relevant_linux_workers'],
              'Successful fresh Windows/WSL quiescence is required.')
    W.require(W.encoded(W.inventory(W.run_path(PARENT,root)))==W.encoded(authority['original_inventory']),
              'Parent bytes changed during inspection.')
    return {'kind':'workflow_verified_transport_prefix_v1','parent_name':PARENT,'parent_dispatch_id':job['id'],
            'parent_authority_sha256':AUTHORITY_SHA,'parent_configuration_sha256':plan['configuration_sha256'],
            'original_inventory':authority['original_inventory'],'ended_identities':identities,'quiescence':quiet,
            'original_source_sha256':receipt['resolved']['source_sha256'],'original_runtime':receipt['runtime'],
            'inspected_utc':W.utc(),'new_radiation_calls':0,'response_entrypoint_calls':0}


def release(job,plan,inspection,root=W.ROOT):
    _,receipt,_=parent(root);delta=compatible(receipt['resolved'],plan['resolved'])
    value=dict(inspection,derivative_name=plan['resolved']['selection']['name'],derivative_configuration_sha256=plan['configuration_sha256'],
               reviewed_changed_sources=delta,action='New derivative only; original failed root cannot resume or overwrite.')
    path=W.safe_path(root,STATE+'/verified-prefixes/'+PARENT+'.json');W.write(path,value,fresh=True)
    return W.sha(path)


def retirement(root=W.ROOT):
    path=W.safe_path(root,STATE+'/verified-prefixes/'+PARENT+'.json')
    if not path.exists():return None
    jobs=W.read(W.safe_path(root,STATE+'/workflow-jobs.json'))['jobs'];job=next((j for j in jobs if j['name']==PARENT),None)
    W.require(job and job['status']=='verified_transport' and job.get('prefix_authority_sha256')==W.sha(path),
              'Verified-prefix retirement is not bound to the owned reservation.')
    value=W.read(path);authority,receipt,plan=parent(root)
    identities=[receipt['supervisor']]+[{'pid':r['pid'],'identity':r['process_identity']} for r in receipt['stages'].values()]
    W.require(value['kind']=='workflow_verified_transport_prefix_v1' and value['parent_dispatch_id']==PARENT_DISPATCH and
              value['parent_authority_sha256']==AUTHORITY_SHA and value['parent_configuration_sha256']==plan['configuration_sha256'] and
              W.encoded(value['original_inventory'])==W.encoded(authority['original_inventory']) and
              job['id']==PARENT_DISPATCH and W.encoded(job['plan'])==W.encoded(plan) and job['driver']==receipt['supervisor'] and
              value['ended_identities']==identities and all(W.identity_ended(d) for d in identities) and
              value['quiescence']['windows_succeeded'] and value['quiescence']['linux_succeeded'] and
              not value['quiescence']['relevant_windows_workers'] and not value['quiescence']['relevant_linux_workers'],
              'Original prefix retirement or process identities changed.')
    return value


def verified_retirement(directory,root=W.ROOT):
    return directory==W.run_path(PARENT,root) and retirement(root) is not None


def transfer(directory,plan,receipt,root=W.ROOT,probe=None):
    start=time.perf_counter();started=W.utc();value=retirement(root)
    W.require(value and value['derivative_name']==directory.name and value['derivative_configuration_sha256']==plan['configuration_sha256'],
              'No preserved authority permits this derivative.')
    _,original,_=parent(root);delta=compatible(original['resolved'],plan['resolved'])
    quiet=(probe or I.inventories)(root)
    W.require(quiet['windows_succeeded'] and quiet['linux_succeeded'] and not quiet['relevant_windows_workers'] and not quiet['relevant_linux_workers'],
              'Derivative dispatch quiescence did not pass.')
    source=W.run_path(PARENT,root)
    names=[n for n in value['original_inventory'] if n.startswith('transport/') or n in ('geometry.log','radiation.log','event_ledger.log','emlow-data.json')]
    for name in names:
        origin=W.safe_path(source,name);target=W.safe_path(directory,name);target.parent.mkdir(parents=True,exist_ok=True)
        with origin.open('rb') as incoming,target.open('xb') as outgoing:
            shutil.copyfileobj(incoming,outgoing);outgoing.flush();os.fsync(outgoing.fileno())
    W.verify_inventory(directory,{n:value['original_inventory'][n] for n in names})
    W.require(W.encoded(W.inventory(source))==W.encoded(value['original_inventory']),'Parent changed during lossless transfer.')
    for stage in PREFIX:
        before=time.perf_counter();record=original['stages'][stage]
        actual=W.validate_stage(directory,stage,plan['resolved'],root)
        W.require(W.encoded(actual)==W.encoded(record['artifacts']),'Transferred prefix lost its stage semantics/inventory.')
        receipt['stages'][stage]={'status':'completed','reuse':'verified_transport_prefix','artifacts':actual,
                                'parent_name':PARENT,'parent_run_sha256':value['original_inventory']['run.json']['sha256'],
                                'inherited_stage_receipt':record,'original_elapsed_seconds':record['elapsed_seconds'],
                                'fresh_validation_seconds':time.perf_counter()-before}
    receipt['transport_reuse']={'parent_name':PARENT,'authority_sha256':W.sha(W.safe_path(root,STATE+'/verified-prefixes/'+PARENT+'.json')),
        'original_source_sha256':value['original_source_sha256'],'original_runtime':value['original_runtime'],
        'reviewed_changed_sources':delta,'transferred_artifacts':{n:value['original_inventory'][n] for n in names},
        'started_utc':started,'finished_utc':W.utc(),'transfer_and_validation_seconds':time.perf_counter()-start,
        'new_geometry_calls':0,'new_radiation_calls':0,'new_ledger_calls':0,
        'runtime_attribution':'Copied transport/run.json retains its original EMlow manifest path. Copied emlow-data.json is immutable supporting evidence, not a new transport runtime.'}

