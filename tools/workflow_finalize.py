"""Explicit saved-results phase for a terminal ring reduction-validation failure.

No dispatch, retry, resume, calibration or scientific processing exists here.
The original failed receipt is preserved before updating derived outer status.
"""
import copy
from pathlib import Path
import time

import scenario_workflow as W
import workflow_inspection as I

ERROR='Ring pulse changed truth, grouping, origin or raw-row identity.'
STATE='.local/local-control-v1/results-finalization'
RUN_NAME='m14a2-ge-ui-01'
BASIS='.local/product-delivery-v1/implementation/M14a2-GE-FAILED-VALIDATION-BASIS.json'
BASIS_SHA='49532eeb97b0cda95ffaab286696872be81d6398a45483da33e3944c0da1d726'
VALIDATORS=('tools/ring_workflow.py','tools/scenario_workflow.py','tools/workflow_finalize.py','tools/workflow_inspection.py')
UPGRADED_VALIDATORS=('tools/ring_workflow.py','tools/scenario_workflow.py')


def candidate(directory):
    r=W.read(Path(directory)/'run.json')
    return (Path(directory).name==RUN_NAME and r.get('kind')==W.KIND and r.get('status')=='failed' and r.get('error')==ERROR and
            r.get('resolved',{}).get('selection',{}).get('detector') in W.RINGS and
            set(r.get('stages',{}))==set(W.STAGES[:-1]) and
            all(r['stages'][s].get('status')=='completed' for s in W.STAGES[:3]) and
            r['stages']['response'].get('status')=='command_exited' and
            type(r['stages']['response'].get('exit_code')) is int and r['stages']['response']['exit_code']==0)


def owned(name,root):
    state=W.read(W.safe_path(root,'.local/local-control-v1/workflow-jobs.json'))
    W.require(state['kind']=='local_workflow_jobs_v1' and type(state['jobs']) is list,'Saved control state requires inspection.')
    matches=[j for j in state['jobs'] if j.get('name')==name]
    W.require(len(matches)==1 and matches[0]['status']=='dispatch_uncertain','Only an owned uncertain terminal-response failure can finalize saved results.')
    job=matches[0]
    for other in state['jobs']:
        W.require(W.identity_ended(other.get('driver')) and (other is job or other['status'] not in ('dispatch_uncertain','running','stop_requested')),
                  'Other active, unknown or uncertain work prevents saved-results finalization.')
    # Keep the existing durable legacy guards, without bypassing this owned job.
    for filename in ('jobs.json','gamma-jobs.json'):
        path=W.safe_path(root,'.local/local-control-v1/'+filename)
        if path.exists():
            for old in W.read(path)['jobs']:
                W.require(not old.get('uncertain') and old.get('status') not in ('running','dispatch-uncertain','verification-required','preflight') and
                          W.identity_ended(old.get('child')),'Existing saved work must be verified before finalizing results.')
    return state,job


def validate(name,root=W.ROOT,*,probe=I.inventories):
    """Read-only admission; current numerical producers remain strict."""
    directory=W.run_path(name,root);W.require(candidate(directory),'Not the recognized terminal ring aggregation-validation failure.')
    basis_path=W.safe_path(root,BASIS);W.require(W.sha(basis_path)==BASIS_SHA,'Immutable original Ge failure authority changed or is unavailable.')
    basis=W.read(basis_path)
    W.require(basis['kind']=='m14a2_ge_completed_science_validation_failure_basis_v1' and basis['run']==W.BASE+'/'+name and
              basis['original_run_sha256']==W.sha(directory/'run.json') and
              basis['science_report_sha256']==W.sha(directory/'response/run.json') and
              W.encoded(basis['original_inventory'])==W.encoded(W.inventory(directory)),
              'Original Ge failed receipt or complete scientific inventory changed.')
    W.require(not (directory/'index.html').exists() and not (directory/'COMPLETE.json').exists(),'Derived results already exist; inspect them without overwriting.')
    state,job=owned(name,root);r=W.read(directory/'run.json');plan=W.read(directory/'resolved-config.json');W.saved_plan(plan)
    W.require(W.encoded(plan)==W.encoded(job['plan']) and W.encoded(r['resolved'])==W.encoded(plan['resolved']) and
              r['configuration_sha256']==plan['configuration_sha256'] and job['driver']==r['supervisor'],
              'Original checked plan, driver or failed receipt changed.')
    W.require(W.identity_ended(r['supervisor']) and all(W.identity_ended({'pid':s['pid'],'identity':s['process_identity']}) for s in r['stages'].values()),
              'Original driver/stage activity is live or unknown.')
    for ref,h in r['resolved']['source_sha256'].items():
        if ref not in UPGRADED_VALIDATORS:W.require(W.sha(W.safe_path(root,ref))==h,'Original numerical producer/input changed: '+ref)
    W.require(W.runtime_identity(r['resolved']['selection']['threads'])==r['resolved']['runtime_identity'],'Original runtime bytes changed.')
    commands=W.stage_commands(directory,r['resolved'],root,{'JULIA_EXE':r['runtime']['julia']})
    for stage in W.STAGES[:-1]:
        W.require(r['stages'][stage]['arguments']==commands[stage] and r['stages'][stage]['exit_code']==0,'Original stage dispatch/exit authority changed.')
    before=W.inventory(directory);artifacts={}
    for stage in W.STAGES[:-1]:
        artifacts[stage]=W.validate_stage(directory,stage,r['resolved'],root,historical=True)
        if stage!='response':W.require(W.encoded(artifacts[stage])==W.encoded(r['stages'][stage]['artifacts']),'Original completed prefix inventory changed.')
    report=W.read(directory/'response/run.json')
    W.require(report['status'] in ('completed_provisional_native_response','completed_with_native_failures') and
              all(h==r['resolved']['source_sha256']['simulation/'+ref] for ref,h in report['source_sha256'].items()),
              'Original scientific worker attribution is inconsistent.')
    quiet=probe(root)
    W.require(quiet.get('windows_succeeded') is True and quiet.get('linux_succeeded') is True and
              quiet.get('relevant_windows_workers')==[] and quiet.get('relevant_linux_workers')==[],
              'Fresh complete process inventories do not establish quiescence.')
    W.require(W.encoded(before)==W.encoded(W.inventory(directory)),'Saved artifacts changed during validation.')
    W.require(W.identity_ended(r['supervisor']) and all(W.identity_ended({'pid':s['pid'],'identity':s['process_identity']}) for s in r['stages'].values()),
              'Original process identity became uncertain during validation.')
    return state,job,r,{'kind':'workflow_saved_results_validation_v1','name':name,'original_run_sha256':W.sha(directory/'run.json'),
        'immutable_failure_basis_ref':BASIS,'immutable_failure_basis_sha256':BASIS_SHA,
        'original_artifacts':before,'configuration_sha256':plan['configuration_sha256'],'science_report_sha256':W.sha(directory/'response/run.json'),
        'validator_sha256':{ref:W.sha(W.safe_path(root,ref)) for ref in VALIDATORS},'quiescence':quiet,
        'validated_stage_artifacts':artifacts,'science_calls':0,'validated_utc':W.utc()}


def finalize(name,root=W.ROOT,*,probe=I.inventories):
    with W.execution_lease(root):
        started=W.utc();clock=time.perf_counter();state,job,original,evidence=validate(name,root,probe=probe)
        directory=W.run_path(name,root);authority=W.safe_path(root,STATE+'/'+name)
        W.require(not authority.exists(),'A saved-results finalization record already exists; retain it for inspection.')
        authority.mkdir(parents=True,exist_ok=False)
        # Exact historical bytes and full pre-write inventory, outside the run.
        original_body=(directory/'run.json').read_bytes();(authority/'original-run.json').write_bytes(original_body)
        W.require(W.sha(authority/'original-run.json')==evidence['original_run_sha256'],'Original failure preservation failed.')
        W.write(authority/'validation.json',evidence,fresh=True)
        receipt=copy.deepcopy(original)
        receipt['stages']['response'].update(status='completed',artifacts=evidence['validated_stage_artifacts']['response'],
            validation='saved terminal response; no numerical replay')
        W.result_page(directory,receipt)
        receipt['stages']['results']={'status':'completed','started_utc':started,'finished_utc':W.utc(),'elapsed_seconds':time.perf_counter()-clock,
            'mode':'explicit_saved_results_only','science_calls':0,
            'artifacts':{'index.html':{'sha256':W.sha(directory/'index.html'),'bytes':(directory/'index.html').stat().st_size}}}
        report=W.read(directory/'response/run.json');receipt.update(counts=report['counts'],
            status='completed_with_native_failures' if report['counts']['native_failed_groups'] else 'completed',finished_utc=W.utc())
        receipt.pop('error',None);receipt.pop('failed_utc',None)
        receipt['saved_results_finalization']={'original_failed_run_sha256':evidence['original_run_sha256'],
            'authority_ref':str((authority/'validation.json').relative_to(root)).replace('\\','/'),
            'authority_sha256':W.sha(authority/'validation.json'),'validator_sha256':evidence['validator_sha256'],
            'original_science_timings_preserved':True,'science_calls':0}
        # No original scientific artifact may change even during result export.
        W.verify_inventory(directory,{k:v for k,v in evidence['original_artifacts'].items() if k!='run.json'})
        W.write(directory/'run.json',receipt)
        W.write(directory/'COMPLETE.json',{'kind':W.KIND,'status':receipt['status'],'configuration_sha256':receipt['configuration_sha256'],
                'artifacts':W.inventory(directory,exclude=('COMPLETE.json','STOP.json'))},fresh=True)
        checked=W.inspect(name,root)
        job['status']=checked['status'];job.pop('error',None)
        W.write(W.safe_path(root,'.local/local-control-v1/workflow-jobs.json'),state)
        return checked


def verify_finalization(directory,receipt,root):
    """Historical authority remains verifiable after future validator upgrades."""
    meta=receipt['saved_results_finalization'];authority=W.safe_path(root,STATE+'/'+directory.name)
    W.require(meta['authority_ref']==(authority/'validation.json').relative_to(root).as_posix() and
              W.sha(authority/'validation.json')==meta['authority_sha256'] and
              W.sha(authority/'original-run.json')==meta['original_failed_run_sha256'],
              'Preserved failed results authority changed.')
    evidence=W.read(authority/'validation.json');original=W.read(authority/'original-run.json')
    W.require(evidence['immutable_failure_basis_ref']==BASIS and evidence['immutable_failure_basis_sha256']==BASIS_SHA and
              W.sha(W.safe_path(root,BASIS))==BASIS_SHA,'Historical immutable failure basis changed.')
    basis=W.read(W.safe_path(root,BASIS))
    W.require(evidence['kind']=='workflow_saved_results_validation_v1' and evidence['name']==directory.name and
              evidence['original_run_sha256']==meta['original_failed_run_sha256'] and evidence['configuration_sha256']==receipt['configuration_sha256'] and
              evidence['validator_sha256']==meta['validator_sha256'] and evidence['science_calls']==meta['science_calls']==0 and
              W.encoded(original['resolved'])==W.encoded(receipt['resolved']) and original['status']=='failed' and original['error']==ERROR and
              evidence['original_artifacts']['run.json']['sha256']==meta['original_failed_run_sha256'] and
              W.encoded(evidence['original_artifacts'])==W.encoded(basis['original_inventory']) and
              evidence['science_report_sha256']==W.sha(directory/'response/run.json') and
              all(original['stages'][s]['elapsed_seconds']==receipt['stages'][s]['elapsed_seconds'] for s in W.STAGES[:-1]),
              'Historical failed receipt/science/source timing authority differs.')
    W.verify_inventory(directory,{k:v for k,v in evidence['original_artifacts'].items() if k!='run.json'})
