"""Explicit, staged identity recovery for one unsealed GeGI contact failure.

No transport, drift, calibration or fields are executed. Prepare writes a new
recovery generation only; apply is a separate operator-coordinated transaction.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import zlib

import gegi_campaign as C
import gegi_event_store as S

KIND='gegi_campaign_source_recovery_v1'
HELPER='tools/gegi_campaign_recovery.py'
WRAPPER='simulation/gegi_campaign_response.jl'
ALLOWED_SOURCES={WRAPPER,HELPER,'tools/gegi_campaign.py','tools/gegi_campaign_response.py','tools/gegi_campaign_analysis.py'}
ERROR='ArgumentError: Deposit starts on a GeGI contact'
require=C.require


def binding(path,root):
    path=C.local(path,root)
    return {'ref':path.relative_to(root).as_posix(),'sha256':C.sha(path)}


def _changes(old,new):
    return {k:{'old_sha256':old.get(k),'new_sha256':new.get(k)} for k in sorted(set(old)|set(new)) if old.get(k)!=new.get(k)}


def audit_sources(plan,root):
    for ref,digest in plan['source_sha256'].items():
        path=C.W.safe_path(root,ref);C.no_links(path)
        require(C.sha(path)==digest,'Recovery source audit failed: '+ref)


def _revision(plan,root):
    record=C.read(C.bound_file(root,plan['recovery']))
    require(record.get('kind')==KIND and record.get('status')=='staged','Unsupported source recovery')
    return record


def original_plan(plan,root=C.ROOT,*,require_applied=True):
    """Prove narrow equivalence before reusing original acceptance and budgets."""
    root=Path(root);record=_revision(plan,root)
    old=C.validate_plan(C.read(C.bound_file(root,record['original_plan'])),frozen=True)
    seal=C.read(C.bound_file(root,record['original_frozen']))
    require('recovery' not in old and seal['plan_sha256']==record['original_plan']['sha256'] and
            seal['physics_sha256']==old['physics_sha256'],'Original frozen plan binding changed')
    ignored={'source_sha256','native_request','physics_sha256','recovery'}
    require({k:v for k,v in plan.items() if k not in ignored}=={k:v for k,v in old.items() if k not in ignored},
            'Recovery changed physics inputs, criteria, allocation, seeds, or resource budget')
    changes=_changes(old['source_sha256'],plan['source_sha256'])
    require(changes==record['source_changes'] and set(changes)==set(record['allowed_sources']) and
            set(changes)<=ALLOWED_SOURCES and WRAPPER in changes and HELPER in plan['source_sha256'] and
            all(change['new_sha256'] is not None for change in changes.values()) and
            all(change['old_sha256'] is not None or ref==HELPER for ref,change in changes.items()),
            'Recovery changed a source outside its explicit narrow allowlist')
    before=C.read(C.bound_file(root,old['native_request']));after=C.read(C.bound_file(root,plan['native_request']))
    require(set(before['source_sha256'])==set(after['source_sha256']) and
            {k:v for k,v in before.items() if k!='source_sha256'}=={k:v for k,v in after.items() if k!='source_sha256'},
            'Recovery native request changed beyond source pins')
    require(all(after['source_sha256'][k]==plan['source_sha256'].get(k) for k in after['source_sha256']) and
            set(_changes(before['source_sha256'],after['source_sha256']))<=set(changes), 'Recovery request source lineage differs')
    require(record['new_native_request']==plan['native_request'] and record['new_physics_sha256']==C.physics_sha256(plan)==plan['physics_sha256'],
            'Revised request/physics identity changed')
    backup=store_snapshot(C.bound_file(root,record['original_store']))
    ledger=C.read(C.bound_file(root,record['prior_recipe_ledger']))
    require(backup['tables']==record['original_store_tables'] and backup['identity']==record['original_store_identity'] and
            backup['events']==ledger['events'] and ledger['original_store_sha256']==record['original_store']['sha256'],
            'Original Store backup or prior-version ledger changed')
    require(ledger['wrapper_source_change']=={'name':'gegi_campaign_response.jl',**changes[WRAPPER]},'Prior wrapper source lineage changed')
    evidence=C.read(C.bound_file(root,record['failure_evidence']))
    require(evidence.get('kind')=='gegi_contact_failure_preservation_v1' and evidence.get('status')=='preserved' and
            evidence.get('error')==ERROR and evidence.get('old_plan_sha256')==record['original_plan']['sha256'],
            'Original contact-failure evidence differs')
    require(type(record.get('reason')) is str and record['reason'].strip(), 'Recovery reason is missing')
    audit_sources(plan,root)  # Always precedes any admission of old acceptance.
    if require_applied:
        applied=C.read(C.reference(root,record['application_ref']))
        require(applied.get('status')=='complete' and applied.get('revision')==plan['recovery'] and
                applied.get('new_plan_sha256')==C.sha(C.reference(root,record['campaign_ref'])/'plan.json'),
                'Recovery identity transaction is not complete')
    return old


def spool_path(directory,plan,root=C.ROOT):
    if 'recovery' not in plan:return Path(directory)/'native-spool'
    record=_revision(plan,root);path=C.reference(root,record['new_spool_ref'])
    require(path.parent==Path(directory) and path.name.startswith('native-spool-recovery-'), 'Unsafe recovery spool')
    return path


def prior_provenance(plan,chunk,*,root=C.ROOT):
    if 'recovery' not in plan:return None
    record=_revision(plan,root)
    if chunk!=record['chunk']:return None
    value=C.read(C.bound_file(root,record['prior_recipe_ledger']))
    return {**value,'revision':plan['recovery']}


def store_snapshot(path):
    """Hash exact stored blobs, not regenerated signals or reserialized metadata."""
    path=Path(path);C.no_links(path)
    require(not Path(str(path)+'-wal').exists() and not Path(str(path)+'-journal').exists(),'Live/uncommitted Store refused')
    db=sqlite3.connect(path.as_uri()+'?mode=ro&immutable=1',uri=True)
    try:
        require(db.execute('PRAGMA integrity_check').fetchone()[0]=='ok','Partial Store integrity failed')
        require(db.execute('SELECT COUNT(*) FROM completion').fetchone()[0]==0,'Completed Store cannot be rebound')
        body=db.execute('SELECT body FROM identity WHERE singleton=1').fetchone()[0]
        fingerprints={};events=[]
        for table,query in (('events','SELECT primary_id,group_id,input_sha256,metadata,metadata_sha256 FROM events ORDER BY primary_id,group_id'),
                            ('arrays','SELECT digest,count,value FROM arrays ORDER BY digest')):
            digest=hashlib.sha256();count=0
            for row in db.execute(query):
                for item in row:
                    value=item if isinstance(item,bytes) else S.encoded(item)
                    digest.update(len(value).to_bytes(8,'big'));digest.update(value)
                count+=1
                if table=='events':
                    raw=zlib.decompress(row[3]);require(S.sha(raw)==row[4],'Saved metadata digest changed')
                    event=json.loads(raw)
                    events.append({'event_id':row[0],'group_id':row[1],'input_sha256':row[2],
                                   'metadata_sha256':row[4],'readout_recipe_sha256':event['readout_recipe_sha256']})
            fingerprints[table]={'count':count,'sha256':digest.hexdigest()}
        return {'identity':json.loads(body)['identity'],'tables':fingerprints,'events':events}
    finally:db.close()


def _inactive(directory,reader,root):
    C.inactive_children(directory,reader=reader,root=root)
    launcher=Path(directory)/'launcher.json'
    if launcher.exists():
        value=C.read(launcher)
        require(value.get('status')!='launching' and type(value.get('pid')) is int and
                reader(value['pid']) not in ('unknown',value.get('process_start_identity')),'Campaign launcher is live or unverified')


def prepare(directory,new_request,failure_evidence,output,*,reason,allowed_sources,root=C.ROOT,reader=C.identity,
            recovery_source_commit=None):
    """Create backups/staged metadata only. Never alter the active campaign."""
    root=Path(root);directory=C.local(directory,root);output=C.local(output,root)
    require(not output.exists(),'Recovery generation exists; preserve it')
    old=C.read_plan(directory,root=root,verify=False)
    require('recovery' not in old,'This bounded recovery supports only the first explicit revision')
    _inactive(directory,reader,root)
    require(not (directory/'COMPLETE.json').exists(),'Completed campaign cannot be rebound')
    existing=[]
    for chunk in C.chunks(old):
        folder=C.chunk_path(directory,chunk)
        require(not (folder/'DONE.json').exists(),'This bounded recovery cannot alter sealed chunks')
        if (folder/'events.sqlite').exists():existing.append((chunk,folder))
    require(len(existing)==1,'Recovery requires exactly one unsealed partial Store')
    chunk,folder=existing[0];store=folder/'events.sqlite';snapshot=store_snapshot(store)
    require(snapshot['identity']==C.chunk_identity(directory,old,chunk) and snapshot['events'],'Original partial Store identity/census differs')
    C.verify_transport_binding(folder,C.selection_for(old,chunk))
    evidence=C.read(C.bound_file(root,failure_evidence))
    require(evidence.get('old_plan_sha256')==C.sha(directory/'plan.json') and
            evidence['files'][store.relative_to(root).as_posix()]['sha256']==C.sha(store),'Failure backup does not bind this partial Store')
    revised=copy.deepcopy(old);revised['native_request']=new_request
    revised['source_sha256']={ref:C.sha(C.W.safe_path(root,ref)) for ref in old['source_sha256']}
    revised['source_sha256'][HELPER]=C.sha(root/HELPER)
    revised['physics_sha256']=C.physics_sha256(revised)
    changes=_changes(old['source_sha256'],revised['source_sha256'])
    require(type(allowed_sources) is list and set(allowed_sources)==set(changes) and set(changes)<=ALLOWED_SOURCES,
            'Declare exactly the changed source allowlist; no implicit admission')
    if recovery_source_commit is None:
        result=C.subprocess.run(['git','rev-parse','HEAD'],cwd=root,stdout=C.subprocess.PIPE,stderr=C.subprocess.PIPE,
            shell=False,creationflags=C.subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        require(result.returncode==0,'Cannot record the recovery source commit')
        recovery_source_commit=result.stdout.decode('ascii').strip()
    require(type(recovery_source_commit) is str and C.re.fullmatch('[0-9a-f]{40}',recovery_source_commit),
            'Recovery source commit must be an exact Git commit hash')
    output.mkdir(parents=True)
    for name in ('plan.json','FROZEN.json'):shutil.copy2(directory/name,output/('original-'+name))
    shutil.copy2(store,output/'original-events.sqlite')
    require(C.sha(output/'original-events.sqlite')==C.sha(store),'Partial Store backup differs')
    recipes={}
    for pilot in C.read(C.bound_file(root,old['acceptance']))['groups']:
        response=C.read(C.bound_file(root,pilot['response_receipt']));recipe=response['readout_recipe']
        require(S.sha(S.encoded(recipe))==response['readout_recipe_sha256'],'Accepted recipe hash changed')
        recipes[response['readout_recipe_sha256']]=recipe
    wanted={e['readout_recipe_sha256'] for e in snapshot['events']}
    require(wanted<=set(recipes),'Preserved group recipe is not bound by original pilot acceptance')
    ledger={'kind':'gegi_prior_recipe_provenance_v1','original_store_sha256':C.sha(store),
        'recipes':{key:recipes[key] for key in sorted(wanted)},'events':snapshot['events'],
        'wrapper_source_change':{'name':'gegi_campaign_response.jl',**changes[WRAPPER]}}
    C.write(output/'prior-recipes.json',ledger,fresh=True)
    transport={ref:{**value,'mtime_ns':(folder/'transport'/ref).stat().st_mtime_ns}
               for ref,value in C.file_inventory(folder/'transport').items()}
    record={'kind':KIND,'status':'staged','reason':reason,'allowed_sources':sorted(allowed_sources),'source_changes':changes,
        'original_producer_commit':old.get('source_commit'),'recovery_source_commit':recovery_source_commit,
        'campaign_ref':directory.relative_to(root).as_posix(),'original_plan':binding(output/'original-plan.json',root),
        'original_frozen':binding(output/'original-FROZEN.json',root),'original_store':binding(output/'original-events.sqlite',root),
        'original_store_tables':snapshot['tables'],'original_store_identity':snapshot['identity'],
        'new_native_request':new_request,'new_physics_sha256':revised['physics_sha256'],'failure_evidence':failure_evidence,
        'chunk':chunk,'transport_files':transport,'prior_recipe_ledger':binding(output/'prior-recipes.json',root),
        'new_spool_ref':(directory/('native-spool-recovery-'+C.digest(changes)[:12])).relative_to(root).as_posix(),
        'application_ref':(output/'application.json').relative_to(root).as_posix(),
        'equivalence':'Only declared source revisions and request/plan identity hashes change; physics inputs, source/group IDs, seeds, cuts, calibration, fields, old Store blobs, original acceptance and disk budgets remain exact.'}
    C.write(output/'revision.json',record,fresh=True);revised['recovery']=binding(output/'revision.json',root)
    original_plan(revised,root,require_applied=False)
    C.verify_inputs(revised,root)
    C.verify_acceptance_value(old,C.read(C.bound_file(root,old['acceptance'])),root)
    C.verify_resource_budget(old,root)
    C.write(output/'plan.json',revised,fresh=True)
    C.write(output/'FROZEN.json',{'kind':C.KIND,'plan_sha256':C.sha(output/'plan.json'),
        'physics_sha256':revised['physics_sha256'],'frozen_utc':C.utc(),'recovery':revised['recovery']},fresh=True)
    result={'kind':KIND,'status':'prepared','plan':binding(output/'plan.json',root),
            'frozen':binding(output/'FROZEN.json',root),'revision':revised['recovery']}
    C.write(output/'prepared.json',result,fresh=True)
    return result


def _replace(source,target):
    temporary=target.with_name(target.name+'.recovery-pending')
    if temporary.exists():require(C.sha(temporary)==C.sha(source),'Unrecognized recovery pending file')
    else:
        with temporary.open('xb') as out,source.open('rb') as inp:
            shutil.copyfileobj(inp,out);out.flush();os.fsync(out.fileno())
    os.replace(temporary,target)


def apply(output,*,root=C.ROOT,reader=C.identity):
    """Explicit resumable apply; active science is never rerun or rewritten."""
    root=Path(root);output=C.local(output,root);prepared=C.read(output/'prepared.json')
    plan=C.read(C.bound_file(root,prepared['plan']));C.bound_file(root,prepared['frozen'])
    old=original_plan(plan,root,require_applied=False);record=_revision(plan,root)
    directory=C.reference(root,record['campaign_ref']);_inactive(directory,reader,root)
    require(not (directory/'.worker.lock').exists() and not (directory/'.launch.lock').exists(),
            'Worker/launch lock remains; inspect and resolve exact ownership before recovery')
    require(not spool_path(directory,plan,root).exists(),'New recovery spool must not exist before apply')
    chunk=record['chunk'];folder=C.chunk_path(directory,chunk);store=folder/'events.sqlite'
    require(not (folder/'DONE.json').exists() and not (folder/'response.json').exists(),'Completed partial chunk cannot be rebound')
    for ref,value in record['transport_files'].items():
        path=folder/'transport'/ref
        require(C.sha(path)==value['sha256'] and path.stat().st_mtime_ns==value['mtime_ns'],'Saved transport changed before recovery')
    new_identity=C.chunk_identity(output,plan,chunk)
    with C.locked(directory,name='.recovery.lock',reader=reader):
        current=store_snapshot(store)
        require(current['tables']==record['original_store_tables'] and
                current['identity'] in (record['original_store_identity'],new_identity),'Partial Store rows/arrays/identity changed')
        require(C.sha(directory/'plan.json') in (record['original_plan']['sha256'],prepared['plan']['sha256']) and
                C.sha(directory/'FROZEN.json') in (record['original_frozen']['sha256'],prepared['frozen']['sha256']),
                'Active plan/seal differs from both recovery transaction states')
        application={'kind':KIND,'status':'applying','revision':plan['recovery'],'new_plan_sha256':prepared['plan']['sha256']}
        C.write(output/'application.json',application)
        if current['identity']!=new_identity:
            db=sqlite3.connect(store)
            try:
                db.execute('BEGIN IMMEDIATE')
                require(db.execute('SELECT COUNT(*) FROM completion').fetchone()[0]==0,'Store became sealed')
                actual=db.execute('SELECT body FROM identity WHERE singleton=1').fetchone()[0]
                require(actual==S.encoded({'kind':S.KIND,'identity':record['original_store_identity']}),'Store identity changed during rebind')
                db.execute('UPDATE identity SET body=? WHERE singleton=1',(S.encoded({'kind':S.KIND,'identity':new_identity}),))
                db.commit()
            finally:db.close()
        checked=store_snapshot(store)
        require(checked['tables']==record['original_store_tables'] and checked['identity']==new_identity,
                'Identity-only rebind altered saved event/array bytes')
        _replace(output/'plan.json',directory/'plan.json');_replace(output/'FROZEN.json',directory/'FROZEN.json')
        application.update(status='complete',original_store_sha256=record['original_store']['sha256'],
                           rebound_store_sha256=C.sha(store),unchanged_tables=checked['tables'],completed_utc=C.utc())
        C.write(output/'application.json',application)
        C.read_plan(directory,root=root)
    return application


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('prepare','apply'));parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--campaign',type=Path);parser.add_argument('--request',type=Path);parser.add_argument('--evidence',type=Path)
    parser.add_argument('--reason');parser.add_argument('--allow-source',action='append',default=[])
    args=parser.parse_args()
    if args.action=='prepare':
        require(args.campaign is not None and args.request is not None and args.evidence is not None and args.reason,'Missing explicit recovery inputs')
        result=prepare(args.campaign,binding(args.request,C.ROOT),binding(args.evidence,C.ROOT),args.output,
                       reason=args.reason,allowed_sources=args.allow_source)
    else:result=apply(args.output)
    print(C.W.encoded(result).decode())


if __name__=='__main__':main()
