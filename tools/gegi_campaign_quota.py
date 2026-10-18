"""One explicit owner-requested 10M to 1M quota amendment; no science reruns.

The existing directory and native request remain in place. Sealed chunks keep
their original plan identities, including both prior native recovery versions.
"""
from __future__ import annotations
import argparse
import copy
import os
from pathlib import Path
import shutil

import gegi_campaign as C
import gegi_campaign_recovery as R

KIND='gegi_campaign_quota_amendment_v1'
HELPER='tools/gegi_campaign_quota.py'
ALLOWED_SOURCES={HELPER,'tools/gegi_campaign.py','tools/gegi_campaign_analysis.py'}
QUOTAS={'gamma-left':200000,'gamma-right':200000,'cs137-left':300000,'co60-right':300000}
require=C.require


def _record(plan,root):
    record=C.read(C.bound_file(root,plan['quota_amendment']))
    require(record.get('kind')==KIND and record.get('status')=='staged','Unsupported quota amendment')
    return record


def effective_plan(old):
    require('quota_amendment' not in old and old['total_initial_primaries']==10000000 and
            [g['id'] for g in old['groups']]==list(QUOTAS), 'Only the declared original 10M allocation may be amended')
    result=copy.deepcopy(old)
    result.update(campaign_id='gegi-1m-v1',total_initial_primaries=1000000)
    for group in result['groups']:
        require(group['primary_count']==10*QUOTAS[group['id']], 'Original proportional allocation differs')
        group['primary_count']=QUOTAS[group['id']]
        group['partition']=C.B.partition(group['primary_count'],group['master_seed'])
    require(len(list(C.chunks(result)))==100 and C.physics_sha256(result)==old['physics_sha256'],
            'Quota amendment changed physics or the declared 100-chunk census')
    return result


def original_plan(plan,root=C.ROOT,*,require_applied=True,_audit_current=True):
    """Prove the exact subset and return the original acceptance/budget basis."""
    root=Path(root);record=_record(plan,root)
    old=C.validate_plan(C.read(C.bound_file(root,record['predecessor_plan'])),frozen=True)
    frozen=C.read(C.bound_file(root,record['predecessor_frozen']))
    require(frozen['plan_sha256']==record['predecessor_plan']['sha256'] and
            frozen['physics_sha256']==old['physics_sha256'],'Predecessor frozen identity changed')
    expected=effective_plan(old)
    require(record.get('quotas')==QUOTAS,'Declared quota amendment counts changed')
    ignored={'source_sha256','quota_amendment'}
    require({k:v for k,v in plan.items() if k not in ignored}=={k:v for k,v in expected.items() if k not in ignored},
            'Quota amendment changed request, physics, criteria, seeds, calibration, budget or undeclared fields')
    changes=R._changes(old['source_sha256'],plan['source_sha256'])
    require(changes==record['source_changes'] and set(changes)<=ALLOWED_SOURCES and HELPER in changes and
            all(v['new_sha256'] is not None and (v['old_sha256'] is not None or k==HELPER) for k,v in changes.items()),
            'Quota amendment changed a producer outside the maintainer-only allowlist')
    require('recovery' in old and R._revision(old,root).get('generation')==2,
            'Quota amendment requires the two verified predecessor recoveries')
    application=C.bound_file(root,record['predecessor_application'])
    require(application==C.reference(root,R._revision(old,root)['application_ref']), 'Predecessor recovery application changed')
    baseline=R.original_plan(old,root,_audit_current=False,_plan_sha256=record['predecessor_plan']['sha256'])
    entries=record['sealed_chunks'];planned=list(C.chunks(plan))
    require(type(entries) is list and entries and len(entries)<=20 and
            [e['chunk'] for e in entries]==planned[:len(entries)] and
            all(e['chunk']['source_group']=='gamma-left' for e in entries),
            'Sealed prefix exceeds the reduced gamma-left quota or has different effective offsets')
    require(type(record.get('reason')) is str and record['reason'].strip(),'Quota amendment reason missing')
    stop=C.read(C.bound_file(root,record['predecessor_stop']))
    require(stop['plan_sha256']==record['predecessor_plan']['sha256'],'Original boundary stop identity changed')
    if _audit_current:R.audit_sources(plan,root)
    if require_applied:
        applied=C.read(C.reference(root,record['application_ref']))
        require(applied.get('status')=='complete' and applied.get('quota_amendment')==plan['quota_amendment'] and
                applied.get('new_plan_sha256')==C.sha(C.reference(root,record['campaign_ref'])/'plan.json'),
                'Quota amendment transaction is not complete')
    return baseline


def chunk_origin(directory,plan,chunk,*,root=C.ROOT):
    record=_record(plan,root)
    matches=[e for e in record['sealed_chunks'] if e['chunk']['chunk_index']==chunk['chunk_index']]
    if not matches:return plan,C.sha(Path(directory)/'plan.json')
    require(len(matches)==1 and matches[0]['chunk']==chunk,'Retained quota chunk descriptor changed')
    saved=matches[0];done=C.chunk_path(directory,chunk)/'DONE.json'
    require(C.sha(done)==saved['done_sha256'],'Retained quota DONE changed')
    old=C.read(C.bound_file(root,record['predecessor_plan']))
    origin,digest=R.chunk_origin(directory,old,chunk,root=root)
    # R's fallback uses the active directory. Override only that fallback with
    # the preserved predecessor SHA; first-generation seals keep R's older SHA.
    if origin is old:digest=record['predecessor_plan']['sha256']
    return origin,digest


def _stopped(directory,root,reader):
    R._inactive(directory,reader,root)
    require(not any((directory/name).exists() for name in ('.worker.lock','.launch.lock','.recovery.lock')),
            'A worker/launch/recovery lock remains')
    require(C.read(directory/'progress.json').get('status')=='stopped' and (directory/'STOP.json').is_file(),
            'Quota amendment requires a verified boundary stop')
    require(not (directory/'COMPLETE.json').exists(),'Completed campaign cannot be amended')


def prepare(directory,output,*,reason,root=C.ROOT,reader=C.identity,source_commit=None):
    root=Path(root);directory=C.local(directory,root);output=C.local(output,root)
    require(not output.exists(),'Quota amendment output exists; preserve it')
    _stopped(directory,root,reader)
    old=C.read_plan(directory,root=root,verify=False);revised=effective_plan(old)
    require(C.read(directory/'STOP.json')['plan_sha256']==C.sha(directory/'plan.json'),'Boundary stop belongs to another plan')
    R.original_plan(old,root,_audit_current=False)
    sealed=[];prefix=True
    for chunk in C.chunks(old):
        folder=C.chunk_path(directory,chunk)
        if (folder/'DONE.json').exists():
            require(prefix and chunk['source_group']=='gamma-left' and len(sealed)<20,
                    'Sealed data exceed the reduced left-source quota; preserve excess separately, never silently include it')
            C.verify_done(directory,old,chunk,root=root)
            sealed.append(R.sealed_inventory(directory,chunk))
        else:
            prefix=False
            require(not folder.exists() or not any(folder.iterdir()),'Unsealed chunk data remain; finish the boundary stop before amending')
    require(sealed,'No sealed prefix was found for this concrete amendment')
    revised['source_sha256']={ref:C.sha(root/ref) for ref in old['source_sha256']}
    revised['source_sha256'][HELPER]=C.sha(root/HELPER)
    changes=R._changes(old['source_sha256'],revised['source_sha256'])
    require(set(changes)<=ALLOWED_SOURCES and HELPER in changes,'Quota amendment changed non-maintainer producer sources')
    if source_commit is None:
        result=C.subprocess.run(['git','rev-parse','HEAD'],cwd=root,stdout=C.subprocess.PIPE,stderr=C.subprocess.PIPE,
            shell=False,creationflags=C.subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        require(result.returncode==0,'Cannot record quota amendment source commit');source_commit=result.stdout.decode('ascii').strip()
    require(type(source_commit) is str and C.re.fullmatch('[0-9a-f]{40}',source_commit),'Invalid quota source commit')
    output.mkdir(parents=True)
    for name in ('plan.json','FROZEN.json','STOP.json','progress.json'):
        shutil.copy2(directory/name,output/('predecessor-'+name))
    record={'kind':KIND,'status':'staged','reason':reason,'source_commit':source_commit,'source_changes':changes,
        'campaign_ref':directory.relative_to(root).as_posix(),'predecessor_plan':R.binding(output/'predecessor-plan.json',root),
        'predecessor_frozen':R.binding(output/'predecessor-FROZEN.json',root),
        'predecessor_stop':R.binding(output/'predecessor-STOP.json',root),
        'predecessor_progress':R.binding(output/'predecessor-progress.json',root),
        'predecessor_application':R.binding(C.reference(root,R._revision(old,root)['application_ref']),root),
        'sealed_chunks':sealed,'quotas':QUOTAS,'application_ref':(output/'application.json').relative_to(root).as_posix(),
        'scope':'Owner-requested proportional initial-count subset. Completed chunks retain exact original identities and bytes. Native request, response adapter, fields, calibration, seeds, cuts and measured resource allowance remain unchanged.'}
    C.write(output/'amendment.json',record,fresh=True);revised['quota_amendment']=R.binding(output/'amendment.json',root)
    baseline=original_plan(revised,root,require_applied=False)
    C.verify_inputs(revised,root);C.verify_acceptance_value(baseline,C.read(C.bound_file(root,baseline['acceptance'])),root)
    C.verify_resource_budget(baseline,root)
    C.write(output/'plan.json',revised,fresh=True)
    C.write(output/'FROZEN.json',{'kind':C.KIND,'plan_sha256':C.sha(output/'plan.json'),
        'physics_sha256':revised['physics_sha256'],'frozen_utc':C.utc(),'quota_amendment':revised['quota_amendment']},fresh=True)
    C.write(output/'STOP.json',{**C.read(directory/'STOP.json'),'plan_sha256':C.sha(output/'plan.json'),
        'quota_amendment':revised['quota_amendment']},fresh=True)
    result={'kind':KIND,'status':'prepared','plan':R.binding(output/'plan.json',root),
        'frozen':R.binding(output/'FROZEN.json',root),'stop':R.binding(output/'STOP.json',root),'quota_amendment':revised['quota_amendment']}
    C.write(output/'prepared.json',result,fresh=True);return result


def apply(output,*,root=C.ROOT,reader=C.identity):
    root=Path(root);output=C.local(output,root);prepared=C.read(output/'prepared.json')
    plan=C.read(C.bound_file(root,prepared['plan']));C.bound_file(root,prepared['frozen']);C.bound_file(root,prepared['stop'])
    original_plan(plan,root,require_applied=False);record=_record(plan,root)
    directory=C.reference(root,record['campaign_ref']);_stopped(directory,root,reader)
    R.verify_sealed_prefix(directory,record)
    with C.locked(directory,name='.quota.lock',reader=reader):
        for name,before,after in (('plan.json','predecessor_plan','plan'),('FROZEN.json','predecessor_frozen','frozen'),
                                  ('STOP.json','predecessor_stop','stop')):
            require(C.sha(directory/name) in (record[before]['sha256'],prepared[after]['sha256']),
                    'Active quota metadata differ from both transaction states')
        application={'kind':KIND,'status':'applying','quota_amendment':plan['quota_amendment'],
            'new_plan_sha256':prepared['plan']['sha256']}
        C.write(output/'application.json',application)
        for name in ('plan.json','FROZEN.json','STOP.json'):R._replace(output/name,directory/name)
        R.verify_sealed_prefix(directory,record)
        application.update(status='complete',completed_utc=C.utc(),retained_chunks=len(record['sealed_chunks']),
            retained_initial_primaries=sum(e['chunk']['batch']['primary_count'] for e in record['sealed_chunks']),
            effective_initial_primaries=1000000,effective_chunks=100)
        C.write(output/'application.json',application);C.read_plan(directory,root=root)
    return application


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('prepare','apply'));parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--campaign',type=Path);parser.add_argument('--reason');args=parser.parse_args()
    if args.action=='prepare':
        require(args.campaign is not None and args.reason,'Explicit campaign and owner-requested amendment reason required')
        result=prepare(args.campaign,args.output,reason=args.reason)
    else:result=apply(args.output)
    print(C.W.encoded(result).decode())


if __name__=='__main__':main()
