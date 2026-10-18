"""One saved Co60 transport-reader repair after 700k sealed campaign initials.

prepare and revalidate write only a separate transaction directory. The latter
uses the existing locked transport Python, without invoking Geant4 or SSD.
apply installs four derived metadata files and a new source-bound plan. All raw
transport and all sealed chunks retain their original bytes and timestamps.
"""
from __future__ import annotations
import argparse
import copy
import os
from pathlib import Path
import sys

import gegi_campaign as C
import gegi_campaign_quota as Q
import gegi_campaign_recovery as R

KIND='gegi_campaign_transport_revision_v1'
HELPER='tools/gegi_campaign_transport_recovery.py'
READERS={'transport/gegi_source.py','transport/decay_source.py'}
ALLOWED_SOURCES=READERS|{HELPER,'tools/gegi_campaign.py','tools/gegi_campaign_analysis.py','tools/gegi_campaign_quota.py'}
ERROR='Unexpected descendant nuclear family'
METADATA=('source-checked.json','transport/checked-plan.json','transport/prepared.json','transport/run.json')
require=C.require
equal=C.B.typed_equal


def _record(plan,root):
    value=C.read(C.bound_file(root,plan['transport_revision']))
    require(value.get('kind')==KIND and value.get('status')=='staged','Unsupported transport revision')
    return value


def _evidence(binding,root):
    path=C.bound_file(root,binding);value=C.read(path)
    require(value.get('kind')=='gegi_transport_recoil_failure_preservation_v1' and value.get('status')=='preserved'
            and value.get('error')==ERROR and value.get('chunk_index')==70 and value.get('source_group')=='co60-right'
            and value.get('formal_sealed_initial_primaries')==700000
            and value.get('completed_radiation_initial_decays_in_unsealed_chunk')==10000
            and value.get('radiation_rerun') is False and value.get('supervisor_and_children_exited') is True,
            'Only the preserved first Co60 reader failure is admitted')
    old=C.validate_plan(C.read(path.parent/'plan.json'),frozen=True)
    frozen=C.read(path.parent/'FROZEN.json')
    require('transport_revision' not in old and 'quota_amendment' in old and old['total_initial_primaries']==1000000
            and frozen['plan_sha256']==C.sha(path.parent/'plan.json') and frozen['physics_sha256']==old['physics_sha256'],
            'Preserved predecessor plan identity changed')
    for ref,info in value['files'].items():
        item=C.W.safe_path(path.parent/'chunk',ref);C.no_links(item)
        require(item.stat().st_size==info['bytes'] and C.sha(item)==info['sha256'],'Saved transport failure bytes changed: '+ref)
    require(value['raw_sha256']==value['files']['transport/truth.lh5']['sha256'],'Saved raw binding changed')
    require(set(value['source_sha256'])==ALLOWED_SOURCES-{HELPER},'Incomplete original source snapshots')
    for ref,digest in value['source_sha256'].items():
        item=C.W.safe_path(path.parent/'sources',ref);C.no_links(item)
        require(old['source_sha256'].get(ref)==digest==C.sha(item),'Original producer source snapshot changed: '+ref)
    run=C.read(path.parent/'chunk/transport/run.json')
    require(run.get('kind')=='gegi_transport_run_v1' and run.get('status')=='failed' and run.get('returncode')==0
            and run.get('error')==ERROR and run.get('source_lh5_sha256')==value['raw_sha256']
            and run.get('prepared_sha256')==value['files']['transport/prepared.json']['sha256'],
            'Failure is not a completed radiation run rejected only by the reader')
    return path,value,old


def _inactive(directory,root,reader):
    R._inactive(directory,reader,root)
    require(not any((directory/name).exists() for name in ('.worker.lock','.launch.lock','.recovery.lock','.quota.lock')),
            'A campaign worker or transaction lock remains')
    require(not (directory/'COMPLETE.json').exists() and C.read(directory/'progress.json').get('status')=='failed',
            'Transport repair requires the stopped failed campaign')


def _failed_files(directory,record,root,*,allow_derived=False):
    folder=C.chunk_path(directory,record['chunk']);evidence=C.read(C.bound_file(root,record['failure_evidence']))
    require(not any((folder/name).exists() for name in ('DONE.json','events.sqlite','response.json','transport/stream')),
            'Transport repair cannot rewrite sealed, extracted, or native results')
    require(set(C.file_inventory(folder))==set(evidence['files']),'Failed chunk file census changed')
    for ref,info in evidence['files'].items():
        path=folder/ref;actual={'sha256':C.sha(path),'bytes':path.stat().st_size,'mtime_ns':path.stat().st_mtime_ns}
        if allow_derived and ref in METADATA and actual['sha256']==record['derived_metadata'][ref]['sha256']:continue
        require(actual==info,'Original failed chunk bytes or timestamp changed: '+ref)


def _source_change(old,revised):
    changes=R._changes(old['source_sha256'],revised['source_sha256'])
    require(set(changes)<=ALLOWED_SOURCES and READERS|{HELPER}<=set(changes)
            and all(v['new_sha256'] is not None and (v['old_sha256'] is not None or k==HELPER) for k,v in changes.items()),
            'Transport revision changed sources outside the explicit reader/maintainer allowlist')
    return changes


def _request_change(old,revised,root):
    before=C.read(C.bound_file(root,old['native_request']));after=C.read(C.bound_file(root,revised['native_request']))
    require(equal({k:v for k,v in before.items() if k!='source_sha256'},
                  {k:v for k,v in after.items() if k!='source_sha256'}), 'Native request changed beyond source pins')
    changes=R._changes(before['source_sha256'],after['source_sha256'])
    ref='transport/gegi_source.py'
    require(changes=={ref:{'old_sha256':old['source_sha256'][ref],'new_sha256':revised['source_sha256'][ref]}}
            and all(revised['source_sha256'].get(k)==v for k,v in after['source_sha256'].items()),
            'Native request must change only the exact GeGI reader source pin')


def _derivation(record,root):
    evidence_path=C.bound_file(root,record['failure_evidence']);original=evidence_path.parent/'chunk'
    body=C.read(C.bound_file(root,record['derivation']))
    require(body.get('kind')==KIND and body.get('radiation_replayed') is False and body.get('native_replayed') is False
            and body.get('failure_evidence')==record['failure_evidence'] and body.get('metadata')==record['derived_metadata']
            and body.get('source_changes')=={k:v for k,v in record['source_changes'].items() if k in READERS},
            'Transport derivation provenance changed')
    require(set(record['derived_metadata'])==set(METADATA),'Unexpected derived transport files')
    derived={k:C.read(C.bound_file(root,v)) for k,v in record['derived_metadata'].items()}
    checked=C.read(original/'transport/checked-plan.json');expected=copy.deepcopy(checked)
    for ref,change in body['source_changes'].items():
        require(checked['source_sha256'].get(ref)==change['old_sha256'],'Original checked reader pin differs')
        expected['source_sha256'][ref]=change['new_sha256']
    require(equal(derived['transport/checked-plan.json'],expected) and equal(derived['source-checked.json'],expected),
            'Reader derivation changed checked physics/runtime inputs')
    require(equal(C.read(original/'source-checked.json'),checked),'Original checked copies differ')
    meta=C.read(original/'transport/prepared.json');expected=copy.deepcopy(meta)
    expected['source_sha256']=derived['transport/checked-plan.json']['source_sha256']
    expected['files_sha256']['checked-plan.json']=record['derived_metadata']['transport/checked-plan.json']['sha256']
    lineage={'kind':KIND,'failure_evidence':record['failure_evidence'],
        'original_prepared':R.binding(original/'transport/prepared.json',root),
        'original_failed_run':R.binding(original/'transport/run.json',root),
        'original_raw_sha256':C.read(original/'transport/run.json')['source_lh5_sha256'],
        'source_changes':body['source_changes'],'radiation_replayed':False,'native_replayed':False}
    expected['transport_reader_revision']=lineage
    require(equal(derived['transport/prepared.json'],expected),'Reader derivation changed prepared physics or artifact pins')
    run=C.read(original/'transport/run.json');expected=copy.deepcopy(run);expected.pop('error')
    counts=body['counts']
    require(type(counts.get('initial_primaries')) is int and counts['initial_primaries']==10000
            and counts.get('initial_decays')==10000 and counts['zero_deposit_primaries']+counts['nonzero_primaries']==10000
            and len(counts['nonzero_event_ids'])==counts['nonzero_primaries']
            and counts['nonzero_event_ids']==sorted(set(counts['nonzero_event_ids']))
            and all(type(i) is int and 0<=i<10000 for i in counts['nonzero_event_ids']), 'Derived full decay census is invalid')
    expected.update(status='complete',counts=counts,prepared_sha256=record['derived_metadata']['transport/prepared.json']['sha256'],
                    transport_reader_revision=lineage)
    require(equal(derived['transport/run.json'],expected),'Reader derivation changed original radiation execution evidence')


def original_plan(plan,root=C.ROOT,*,require_applied=True,_audit_current=True):
    """Validate one explicit reader edge, then the immutable quota/native edges."""
    root=Path(root);record=_record(plan,root)
    evidence_path,evidence,old=_evidence(record['failure_evidence'],root)
    require(record['predecessor_plan']==R.binding(evidence_path.parent/'plan.json',root)
            and record['predecessor_frozen']==R.binding(evidence_path.parent/'FROZEN.json',root)
            and record['predecessor_progress']==R.binding(evidence_path.parent/'progress.json',root),
            'Transport predecessor bindings changed')
    ignored={'source_sha256','native_request','physics_sha256','transport_revision'}
    require(equal({k:v for k,v in plan.items() if k not in ignored},{k:v for k,v in old.items() if k not in ignored}),
            'Transport revision changed physics inputs, quota, criteria, seeds, calibration or resources')
    require(_source_change(old,plan)==record['source_changes'],'Transport source changes differ from admission')
    _request_change(old,plan,root)
    require(plan['physics_sha256']==record['new_physics_sha256']==C.physics_sha256(plan)
            and record['new_native_request']==plan['native_request'],'Revised source/request identity changed')
    chunks=list(C.chunks(old));entries=record['sealed_chunks']
    require(len(chunks)==100 and len(entries)==70 and [e['chunk'] for e in entries]==chunks[:70]
            and record['chunk']==chunks[70] and chunks[70]['source_group']=='co60-right', 'Transport revision retained prefix changed')
    require(type(record.get('reason')) is str and record['reason'].strip(),'Transport revision reason missing')
    require(record.get('predecessor_quota_application')==R.binding(C.reference(root,Q._record(old,root)['application_ref']),root),
            'Predecessor quota application changed')
    baseline=Q.original_plan(old,root,_audit_current=False,_plan_sha256=record['predecessor_plan']['sha256'])
    _derivation(record,root)
    if _audit_current:R.audit_sources(plan,root)
    if require_applied:
        applied=C.read(C.reference(root,record['application_ref']))
        require(applied.get('status')=='complete' and applied.get('transport_revision')==plan['transport_revision']
                and applied.get('new_plan_sha256')==C.sha(C.reference(root,record['campaign_ref'])/'plan.json'),
                'Transport revision transaction is not complete')
    return baseline


def chunk_origin(directory,plan,chunk,*,root=C.ROOT):
    record=_record(plan,root);matches=[e for e in record['sealed_chunks'] if e['chunk']['chunk_index']==chunk['chunk_index']]
    if not matches:return plan,C.sha(Path(directory)/'plan.json')
    require(len(matches)==1 and matches[0]['chunk']==chunk and
            C.sha(C.chunk_path(directory,chunk)/'DONE.json')==matches[0]['done_sha256'], 'Retained transport predecessor seal changed')
    old=C.read(C.bound_file(root,record['predecessor_plan']))
    origin,digest=Q.chunk_origin(directory,old,chunk,root=root)
    if origin is old:digest=record['predecessor_plan']['sha256']
    return origin,digest


def spool_path(directory,plan,root=C.ROOT):
    record=_record(plan,root);path=C.reference(root,record['new_spool_ref'])
    require(path.parent==Path(directory) and path.name=='native-spool-transport-'+plan['native_request']['sha256'][:12],
            'Unsafe transport revision spool')
    return path


def prepare(directory,evidence,output,*,reason,root=C.ROOT,reader=C.identity,source_commit=None):
    root=Path(root);directory=C.local(directory,root);output=C.local(output,root)
    require(not output.exists(),'Transport revision directory exists; preserve it');_inactive(directory,root,reader)
    evidence_path,evidence_value,old=_evidence(evidence,root)
    require(equal(C.read_plan(directory,root=root,verify=False),old) and
            C.sha(directory/'plan.json')==C.sha(evidence_path.parent/'plan.json')
            and C.sha(directory/'FROZEN.json')==C.sha(evidence_path.parent/'FROZEN.json')
            and C.sha(directory/'progress.json')==C.sha(evidence_path.parent/'progress.json'), 'Active failed campaign differs from snapshot')
    Q.original_plan(old,root,_audit_current=False)
    revised=copy.deepcopy(old);revised['source_sha256']={k:C.sha(root/k) for k in old['source_sha256']}
    revised['source_sha256'][HELPER]=C.sha(root/HELPER);changes=_source_change(old,revised)
    chunks=list(C.chunks(old));sealed=[]
    for chunk in chunks[:70]:
        C.verify_done(directory,old,chunk,root=root);sealed.append(R.sealed_inventory(directory,chunk))
    for chunk in chunks[71:]:
        folder=C.chunk_path(directory,chunk)
        require(not folder.exists() or not any(folder.iterdir()),'Unexpected data beyond the failed Co60 chunk')
    require(source_commit is None or C.re.fullmatch('[0-9a-f]{40}',source_commit),'Invalid transport revision source commit')
    if source_commit is None:
        result=C.subprocess.run(['git','rev-parse','HEAD'],cwd=root,stdout=C.subprocess.PIPE,stderr=C.subprocess.PIPE,
            shell=False,creationflags=C.subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        require(result.returncode==0,'Cannot identify transport revision source commit');source_commit=result.stdout.decode().strip()
    record={'kind':KIND,'status':'staging','reason':reason,'source_commit':source_commit,'source_changes':changes,
        'campaign_ref':directory.relative_to(root).as_posix(),'failure_evidence':evidence,'chunk':chunks[70],
        'predecessor_plan':R.binding(evidence_path.parent/'plan.json',root),
        'predecessor_frozen':R.binding(evidence_path.parent/'FROZEN.json',root),
        'predecessor_progress':R.binding(evidence_path.parent/'progress.json',root),
        'predecessor_quota_application':R.binding(C.reference(root,Q._record(old,root)['application_ref']),root),
        'sealed_chunks':sealed,'application_ref':(output/'application.json').relative_to(root).as_posix(),
        'scope':'Reader-only repair. Native request changes only its GeGI reader source SHA, so request/physics identity hashes change; all numerical physics values remain exactly identical. No radiation, drift or field rerun.'}
    _failed_files(directory,record,root)
    output.mkdir(parents=True)
    request=copy.deepcopy(C.read(C.bound_file(root,old['native_request'])))
    request['source_sha256']['transport/gegi_source.py']=revised['source_sha256']['transport/gegi_source.py']
    C.write(output/'native-request.json',request,fresh=True);revised['native_request']=R.binding(output/'native-request.json',root)
    revised['physics_sha256']=C.physics_sha256(revised);_request_change(old,revised,root);C.verify_inputs(revised,root)
    record.update(new_native_request=revised['native_request'],new_physics_sha256=revised['physics_sha256'],
        new_spool_ref=(directory/('native-spool-transport-'+revised['native_request']['sha256'][:12])).relative_to(root).as_posix())
    require(not C.reference(root,record['new_spool_ref']).exists(),'New transport revision spool already exists')
    C.write(output/'candidate-plan.json',revised,fresh=True);C.write(output/'staging.json',record,fresh=True)
    return {'status':'awaiting_saved_transport_revalidation','staging':R.binding(output/'staging.json',root)}


def revalidate_saved_transport(output,*,root=C.ROOT,transport=None,windows_root=None):
    """Read preserved LH5 once in locked WSL; never call prepare/run/Geant4/SSD."""
    root=Path(root);output=C.local(output,root);record=C.read(output/'staging.json')
    require(not (output/'prepared.json').exists(),'Derived transport transaction is already prepared')
    evidence_path,evidence,old=_evidence(record['failure_evidence'],root)
    revised=C.read(output/'candidate-plan.json');require(_source_change(old,revised)==record['source_changes'],'Staged sources changed')
    C.verify_inputs(revised,root)
    directory=C.reference(root,record['campaign_ref']);_failed_files(directory,record,root)
    if transport is None:
        sys.path.insert(0,str(root/'transport'))
        import gegi_source as transport
    if windows_root is not None:transport.P.project_identity(windows_root)
    folder=C.chunk_path(directory,record['chunk']);saved=evidence_path.parent/'chunk'
    checked=transport.check(C.read(saved/'selection.json'));old_checked=C.read(saved/'transport/checked-plan.json')
    expected=copy.deepcopy(old_checked)
    for ref in READERS:expected['source_sha256'][ref]=revised['source_sha256'][ref]
    require(equal(checked,expected),'Revalidation changed checked physics/runtime inputs beyond the two reader pins')
    meta=C.read(saved/'transport/prepared.json')
    for ref,digest in meta['files_sha256'].items():
        require(C.sha(C.W.safe_path(folder/'transport',ref))==digest,'Original preparation artifact changed')
    require((folder/'transport/geometry.gdml').read_text()==transport.G.gdml_text(checked['model_contract'],checked['cryostat_contract'])
            and (folder/'transport/run.mac').read_text()==transport.macro(checked)
            and (folder/'transport/geometry.mac').read_text()==transport.macro(checked,True), 'Revalidation changed geometry or radiation macro')
    original_run=C.read(saved/'transport/run.json');receipt=C.read(saved/'transport/prepare-receipt.json')
    require(equal(original_run['command'],transport.command(checked)) and receipt['status']=='complete' and receipt['returncode']==0
            and equal(receipt['command'],transport.command(checked,True)), 'Original execution commands differ')
    transport.geometry_log_check(folder/'transport',checked)
    require(not C.re.search(transport.DIAGNOSTIC,(folder/'transport/run.log').read_text(errors='replace'),C.re.I),'Original radiation log failed')
    dataset=C.read(folder/'transport/emlow-data.json');actual=transport.T.emlow_manifest(dataset['directory'],dataset['package_metadata'])
    require(equal({k:v for k,v in dataset.items() if k!='hash_wall_s'},{k:v for k,v in actual.items() if k!='hash_wall_s'}),
            'Original EMLOW dataset changed')
    counts=transport.census(folder/'transport/truth.lh5',meta)
    _failed_files(directory,record,root);R.audit_sources(revised,root)
    derived=output/'derived';(derived/'transport').mkdir(parents=True)
    C.write(derived/'source-checked.json',checked,fresh=True);C.write(derived/'transport/checked-plan.json',checked,fresh=True)
    reader_changes={k:v for k,v in record['source_changes'].items() if k in READERS}
    lineage={'kind':KIND,'failure_evidence':record['failure_evidence'],'original_prepared':R.binding(saved/'transport/prepared.json',root),
        'original_failed_run':R.binding(saved/'transport/run.json',root),'original_raw_sha256':evidence['raw_sha256'],
        'source_changes':reader_changes,'radiation_replayed':False,'native_replayed':False}
    meta['source_sha256']=checked['source_sha256'];meta['files_sha256']['checked-plan.json']=C.sha(derived/'transport/checked-plan.json')
    meta['transport_reader_revision']=lineage;C.write(derived/'transport/prepared.json',meta,fresh=True)
    run=copy.deepcopy(original_run);run.pop('error');run.update(status='complete',counts=counts,
        prepared_sha256=C.sha(derived/'transport/prepared.json'),transport_reader_revision=lineage)
    C.write(derived/'transport/run.json',run,fresh=True)
    record['derived_metadata']={ref:R.binding(derived/ref,root) for ref in METADATA}
    C.write(output/'transport-derivation.json',{'kind':KIND,'failure_evidence':record['failure_evidence'],
        'source_changes':reader_changes,'metadata':record['derived_metadata'],'counts':counts,
        'radiation_replayed':False,'native_replayed':False},fresh=True)
    record.update(status='staged',derivation=R.binding(output/'transport-derivation.json',root))
    C.write(output/'revision.json',record,fresh=True);revised['transport_revision']=R.binding(output/'revision.json',root)
    baseline=original_plan(revised,root,require_applied=False)
    C.verify_acceptance_value(baseline,C.read(C.bound_file(root,baseline['acceptance'])),root);C.verify_resource_budget(baseline,root)
    C.write(output/'plan.json',revised,fresh=True)
    C.write(output/'FROZEN.json',{'kind':C.KIND,'plan_sha256':C.sha(output/'plan.json'),'physics_sha256':revised['physics_sha256'],
        'frozen_utc':C.utc(),'transport_revision':revised['transport_revision']},fresh=True)
    result={'kind':KIND,'status':'prepared','plan':R.binding(output/'plan.json',root),'frozen':R.binding(output/'FROZEN.json',root),
        'transport_revision':revised['transport_revision']}
    C.write(output/'prepared.json',result,fresh=True);return result


def apply(output,*,root=C.ROOT,reader=C.identity):
    root=Path(root);output=C.local(output,root);prepared=C.read(output/'prepared.json')
    plan=C.read(C.bound_file(root,prepared['plan']));C.bound_file(root,prepared['frozen'])
    original_plan(plan,root,require_applied=False);C.verify_inputs(plan,root);record=_record(plan,root)
    directory=C.reference(root,record['campaign_ref']);_inactive(directory,root,reader)
    require(not spool_path(directory,plan,root).exists(),'New native spool exists before transport apply')
    R.verify_sealed_prefix(directory,record);_failed_files(directory,record,root,allow_derived=True)
    with C.locked(directory,name='.transport-revision.lock',reader=reader):
        for name,before,after in (('plan.json','predecessor_plan','plan'),('FROZEN.json','predecessor_frozen','frozen')):
            require(C.sha(directory/name) in (record[before]['sha256'],prepared[after]['sha256']),'Active plan differs from both transaction states')
        application={'kind':KIND,'status':'applying','transport_revision':plan['transport_revision'],'new_plan_sha256':prepared['plan']['sha256']}
        C.write(output/'application.json',application)
        folder=C.chunk_path(directory,record['chunk'])
        for ref,binding in record['derived_metadata'].items():
            if C.sha(folder/ref)!=binding['sha256']:R._replace(C.bound_file(root,binding),folder/ref)
        for name in ('plan.json','FROZEN.json'):R._replace(output/name,directory/name)
        R.verify_sealed_prefix(directory,record);_failed_files(directory,record,root,allow_derived=True)
        application.update(status='complete',completed_utc=C.utc(),retained_chunks=70,retained_initial_primaries=700000,
            radiation_replayed=False,native_replayed=False,raw_sha256=C.sha(folder/'transport/truth.lh5'),new_spool_ref=record['new_spool_ref'])
        C.write(output/'application.json',application);C.read_plan(directory,root=root)
    return application


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=('prepare','revalidate','apply'))
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--campaign',type=Path)
    parser.add_argument('--evidence',type=Path);parser.add_argument('--reason');parser.add_argument('--windows-root');args=parser.parse_args()
    if args.action=='prepare':
        require(args.campaign is not None and args.evidence is not None and args.reason,'Campaign, preserved evidence and reason required')
        result=prepare(args.campaign,R.binding(args.evidence,C.ROOT),args.output,reason=args.reason)
    elif args.action=='revalidate':
        require(args.windows_root is not None,'The locked WSL revalidation requires the launcher Windows root')
        result=revalidate_saved_transport(args.output,windows_root=args.windows_root)
    else:result=apply(args.output)
    print(C.W.encoded(result).decode())


if __name__=='__main__':main()
