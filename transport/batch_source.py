"""Versioned serial batch transport; original producers remain unchanged.

Geometry is prepared once through its original bounded preparer. Each batch
uses that exact GDML by reference and a fresh literal beamOn macro/raw ledger.
"""
from __future__ import annotations
import argparse, copy, itertools, json, os, re, shutil, subprocess, sys, time
from pathlib import Path
import cs137 as cs
import handoff as h
import scenario_source_portable as P
import decay_source as D
import catalog_source as C
sys.path.insert(0,str(h.ROOT/'tools'))
import scenario_workflow as W
import workflow_batches as B
import decay_workflow as DW

KIND='radioactive_decay_batch_stream_v1'
ADAPTER='shared_decay_batch_source_v1'
PREPARED_KIND='batch_shared_transport_prepared_v1'
WINDOWS_ROOT=None

def selection_request(selection):
    return {'detector':'GeRC02_Li50min' if selection['detector']=='GeRC02' else selection['detector'],
        'source_mode':selection['source'],'source_pose':selection['pose'],'primary_count':20,'seed':selection['seed']}

def legacy_check(selection):
    if selection['detector'] not in W.MODELS:
        C.WINDOWS_ROOT=WINDOWS_ROOT
        bounded=copy.deepcopy(selection);bounded['primary_count']=20
        return C.check(bounded)
    request=selection_request(selection)
    if selection['source']!=W.CS:
        D.WINDOWS_ROOT=WINDOWS_ROOT
        return D.check_request(request)
    if selection['detector']==W.SAP18:
        import sap18_source as S
        S.WINDOWS_ROOT=WINDOWS_ROOT
        return S.check_request(request)
    return P.check(request,WINDOWS_ROOT)

def check(selection):
    h.require(type(selection) is dict and set(selection)==W.FIELDS and
        selection['cryostat']==W.CRYOSTAT and selection['pose']=='nominal' and
        type(selection['threads']) is int and selection['threads'] in (1,2) and
        (selection['source']==W.CS or (DW.is_source(selection['source'],h.ROOT) and DW.capability(DW.preset(selection['source'],h.ROOT),h.ROOT) is not None)),
        'Batch source/detector has no admitted nominal connector')
    B.partition(selection['primary_count'],selection['seed'])
    legacy=legacy_check(selection)
    return {'kind':'batch_transport_checked_v1','schema_version':1,'selection':selection,
        'geometry_preparation_count':20,'legacy_geometry_plan':legacy,
        'adapter_sha256':h.sha256(Path(__file__)),'runtime':legacy['runtime']}

def prepare(selection,output,checked):
    h.require(check(selection)==checked,'Transport checked plan changed')
    out=h.local_path(output);h.require(not out.exists(),'Preserve existing shared preparation')
    out.mkdir(parents=True);legacy=out/'legacy';request=selection_request(selection)
    original=checked['legacy_geometry_plan']
    if selection['detector'] not in W.MODELS:
        C.WINDOWS_ROOT=WINDOWS_ROOT
        bounded=copy.deepcopy(selection);bounded['primary_count']=20
        meta=C.prepare(bounded,legacy,original)
    elif selection['source']!=W.CS:
        meta=D.prepare(request,legacy,original)
    elif selection['detector']==W.SAP18:
        import sap18_source as S
        S.WINDOWS_ROOT=WINDOWS_ROOT
        meta=S.prepare_cs137(W.SAP18,legacy,h.ROOT/P.EXPORTER_REF,20,selection['seed'])
    else:
        meta=P.prepare(request,legacy,WINDOWS_ROOT,original)
    shared=shared_document(meta,checked,legacy)
    h.publish_json(out/'prepared.json',shared)
    return shared

def shared_document(meta,checked,legacy):
    selection=checked['selection']
    c=meta.get('model_contract') or DW.model_contract(selection['detector'],root=h.ROOT)
    shared=copy.deepcopy(meta)
    source=next(p for p in DW.presets(h.ROOT) if p['id']==selection['source'])
    shared.update(kind=PREPARED_KIND,schema_version=1,status='complete',producer_adapter=ADAPTER,
        source_id=selection['source'],source_contract=source,
        source_mode='cs137_legacy' if selection['source']==W.CS else 'registered_decay',model_contract=c,
        legacy_prepared_ref=(legacy/'prepared.json').relative_to(h.ROOT).as_posix(),
        legacy_prepared_sha256=h.sha256(legacy/'prepared.json'),
        geometry_ref=(legacy/'geometry.gdml').relative_to(h.ROOT).as_posix(),
        geometry_report_ref=(legacy/'geometry-report.json').relative_to(h.ROOT).as_posix(),
        scenario_ref=(legacy/'scenario.json').relative_to(h.ROOT).as_posix(),
        checked_transport=checked,
        files_sha256={p.relative_to(h.ROOT).as_posix():h.sha256(p) for p in legacy.rglob('*') if p.is_file()})
    return shared

def read_shared(path):
    path=h.local_path(path);m=cs.load(path)
    h.require(m['kind']==PREPARED_KIND and m['status']=='complete' and m['producer_adapter']==ADAPTER,'Wrong shared preparation')
    checked=check(m['checked_transport']['selection'])
    h.require(B.typed_equal(checked,m['checked_transport']),'Shared runtime/source authority changed')
    legacy=P.safe_path(h.ROOT,m['legacy_prepared_ref'],True).parent
    s=checked['selection']
    if s['detector'] not in W.MODELS:
        C.WINDOWS_ROOT=WINDOWS_ROOT;meta=C.read_prepared(legacy)[1]
    elif s['source']!=W.CS:
        D.WINDOWS_ROOT=WINDOWS_ROOT;meta=D.read_prepared(legacy)[1]
    elif s['detector']==W.SAP18:
        import sap18_source as S
        S.WINDOWS_ROOT=WINDOWS_ROOT;meta=S.read_prepared(legacy)[1]
    else:meta=P.read_prepared(legacy,WINDOWS_ROOT)[1]
    h.require(B.typed_equal(m,shared_document(meta,checked,legacy)),
        'Rehashed shared source/geometry/model/unit/clock edits are refused')
    return m

def validate_batch(batch):
    h.require(type(batch) is dict and set(batch)=={'batch_index','global_initial_offset','primary_count','local_initial_primary_id_range','global_initial_primary_id_range','radiation_seed'},'Wrong batch fields')
    for name,lo,hi in (('batch_index',0,B.SEED_MAX-1),('global_initial_offset',0,B.MAX_SAFE_INTEGER),('primary_count',1,B.BATCH_CAP),('radiation_seed',1,B.SEED_MAX)):
        B.exact_integer(batch[name],lo,hi,name)
    n=batch['primary_count'];off=batch['global_initial_offset']
    h.require(off+n<=B.MAX_SAFE_INTEGER and B.typed_equal(batch['local_initial_primary_id_range'],[0,n-1]) and B.typed_equal(batch['global_initial_primary_id_range'],[off,off+n-1]),'Wrong batch ranges')
    return batch

def macro(shared,batch):
    report=cs.load(P.safe_path(h.ROOT,shared['geometry_report_ref'],True))
    return cs.macro_text(report,batch['primary_count'],shared['source_position_global_mm']) if shared['source_mode']=='cs137_legacy' else D.macro_text(report,batch['primary_count'],shared['source_contract'],shared['source_position_global_mm'])

def raw_events(path,shared,batch):
    meta=copy.deepcopy(shared);meta.update(primary_count=batch['primary_count'],seed=batch['radiation_seed'])
    reader=C.events if shared['model_id'] not in W.MODELS else cs.iter_decays if shared['source_mode']=='cs137_legacy' else D.iter_decays
    for event in reader(path,meta):
        local=event['event_id'];h.require(local==event['global_decay_id'],'Changed raw local identity')
        event.update(batch_index=batch['batch_index'],local_initial_id=local,global_initial_id=batch['global_initial_offset']+local)
        yield event

def read_batch(directory):
    d=h.local_path(directory);p=cs.load(d/'batch-prepared.json');batch=validate_batch(p['batch'])
    shared=read_shared(P.safe_path(h.ROOT,p['shared_prepared_ref'],True))
    h.require(p['kind']=='batch_transport_prepared_v1' and p['shared_prepared_sha256']==h.sha256(h.ROOT/p['shared_prepared_ref']) and
        p['macro_sha256']==h.sha256(d/'run.mac') and (d/'run.mac').read_text()==macro(shared,batch),'Batch preparation or literal macro changed')
    return d,p,shared,batch

def run(shared_path,batch,output):
    shared=read_shared(shared_path);batch=validate_batch(batch);d=h.local_path(output)
    h.require(not d.exists(),'Preserve prior radiation attempt');d.mkdir(parents=True)
    text=macro(shared,batch);h.write_new(d/'run.mac',text)
    prepared={'kind':'batch_transport_prepared_v1','batch':batch,'shared_prepared_ref':Path(shared_path).resolve().relative_to(h.ROOT).as_posix(),'shared_prepared_sha256':h.sha256(shared_path),'macro_sha256':h.sha256(d/'run.mac')}
    h.publish_json(d/'batch-prepared.json',prepared)
    cmd=['remage','--flat-output','-t','1','--rand-seed',str(batch['radiation_seed']),'-o','truth.lh5','-g',str(h.ROOT/shared['geometry_ref']),'--','run.mac']
    receipt={'kind':'batch_transport_run_v1','status':'failed','batch':batch,'prepared_sha256':h.sha256(d/'batch-prepared.json'),'shared_prepared_sha256':prepared['shared_prepared_sha256'],'command':cmd,'versions':h.python_versions()}
    start=time.perf_counter()
    try:
        with (d/'run.log').open('x',encoding='utf-8') as log:
            for name,version in (('remage','1.1.0'),('geant4-config','11.3.2')):
                actual=subprocess.run([name,'--version'],text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,check=True).stdout.strip()
                h.require(actual==version,'Pinned runtime changed');receipt['versions'][name]=actual
            t=time.perf_counter();result=subprocess.run(cmd,cwd=d,stdout=log,stderr=subprocess.STDOUT,check=False)
            receipt.update(returncode=result.returncode,remage_wall_s=time.perf_counter()-t)
        h.require(result.returncode==0 and not re.search(P.DIAGNOSTIC,(d/'run.log').read_text(errors='replace'),re.I),'Radiation failed; preserve log')
        import h5py
        with h5py.File(d/'truth.lh5','r') as raw:
            count=raw['number_of_simulated_events'];h.require(count.shape==() and count.dtype.kind in 'iu','Raw primary count is not scalar integer')
            raw_count=int(count[()])
        # Both independent raw count and complete checked vtx/particle stream matter.
        n=0
        for e in raw_events(d/'truth.lh5',shared,batch):h.require(e['local_initial_id']==n,'Raw primary ledger changed');n+=1
        h.require(raw_count==n==batch['primary_count'],'Raw initial-primary census mismatch')
        read_shared(shared_path);receipt.update(status='complete',source_lh5_sha256=h.sha256(d/'truth.lh5'),number_of_simulated_events=raw_count,initial_ledger_count=n)
    except BaseException as err:receipt['error']=str(err);raise
    finally:receipt['total_wall_s']=time.perf_counter()-start;h.publish_json(d/'run.json',receipt)
    return receipt

def iter_stream(path):
    path=h.local_path(path);m=cs.load(path);expected=0
    h.require(m['kind']==KIND and m['status']=='complete','Wrong stream')
    for chunk in m['chunks']:
        h.require(Path(chunk['file']).name==chunk['file'] and chunk['first_global_decay_id']==expected,'Unsafe/reordered stream chunk')
        f=path.parent/chunk['file'];h.require(h.sha256(f)==chunk['sha256'],'Stream chunk changed');n=0
        with f.open(encoding='utf-8') as stream:
            for line in stream:
                e=W.decode_json(line);h.require(e['event_id']==e['global_decay_id']==e['local_initial_id']==expected and e['global_initial_id']==m['batch']['global_initial_offset']+expected and e['batch_index']==m['batch']['batch_index'],'Stream identity changed')
                expected+=1;n+=1;yield e
        h.require(n==chunk['count'],'Chunk count changed')
    h.require(expected==m['primary_count'],'Incomplete stream census')

def extract(directory):
    import h5py
    d,p,shared,batch=read_batch(directory);run=cs.load(d/'run.json')
    h.require(run['status']=='complete' and run['source_lh5_sha256']==h.sha256(d/'truth.lh5') and run['prepared_sha256']==h.sha256(d/'batch-prepared.json'),'Unsealed radiation')
    chunks,count=cs.write_chunks(raw_events(d/'truth.lh5',shared,batch),d/'stream',100)
    with h5py.File(d/'truth.lh5','r') as raw:
        processes=list(cs.table_rows(raw['processes']));aliases=cs.step_aliases(raw,shared['material_tables'])
        tables={key:{'rows':len(next(iter(raw[key].values()))),'columns':{name:{'dtype':str(ds.dtype),'units':cs.scalar(ds.attrs.get('units',''))} for name,ds in raw[key].items()}} for key in ('vtx','particles','tracks','processes',*shared['material_tables'])}
    m={key:shared[key] for key in ('model_id','model_sha256','model_contract','source_id','source_contract','source_mode','coordinate_transform','grouping_policy','clock_policy','source_sha256','unscored_volumes')}
    if shared['source_mode']=='cs137_legacy':m['decay_photon_line_window_keV']=shared['decay_photon_line_window_keV']
    m.update(kind=KIND,status='complete',producer_adapter=ADAPTER,primary_count=count,batch=batch,
        global_decay_id_range=[0,count-1],global_initial_id_range=batch['global_initial_primary_id_range'],
        shared_prepared_ref=p['shared_prepared_ref'],shared_prepared_sha256=p['shared_prepared_sha256'],
        source_lh5='../truth.lh5',source_lh5_sha256=run['source_lh5_sha256'],run_ref=(d/'run.json').relative_to(h.ROOT).as_posix(),run_sha256=h.sha256(d/'run.json'),
        macro_ref=(d/'run.mac').relative_to(h.ROOT).as_posix(),macro_sha256=h.sha256(d/'run.mac'),
        raw_tables=tables,processes=processes,chunks=chunks,uid_aliases=aliases,
        units={'energy':'keV','length':'mm','time':'ns'},raw_track_energy_unit='MeV',raw_position_unit='m',
        ledger={'kind':'recorded-only','full_energy_closure':None,'missing_closure':['world-air deposition','terminal escape energy','neutrino escape balance','complete decay/recoil accounting'],'passive_raw_rows':'hashed truth.lh5; event material sums in JSONL'})
    h.publish_json(d/'stream/manifest.json',m);verify_stream(d);return m

def verify_radiation(directory):
    import h5py
    d,p,shared,batch=read_batch(directory);run=cs.load(d/'run.json')
    command=['remage','--flat-output','-t','1','--rand-seed',str(batch['radiation_seed']),'-o','truth.lh5','-g',str(h.ROOT/shared['geometry_ref']),'--','run.mac']
    h.require(run['kind']=='batch_transport_run_v1' and run['status']=='complete' and run['returncode']==0 and
        B.typed_equal(run['batch'],batch) and run['command']==command and
        run['prepared_sha256']==h.sha256(d/'batch-prepared.json') and
        run['shared_prepared_sha256']==p['shared_prepared_sha256'] and
        run['source_lh5_sha256']==h.sha256(d/'truth.lh5'),'Radiation binding changed')
    with h5py.File(d/'truth.lh5','r') as raw:
        count=raw['number_of_simulated_events'];h.require(count.shape==() and count.dtype.kind in 'iu','Raw primary count is not scalar integer');raw_count=int(count[()])
    ledger=sum(1 for _ in raw_events(d/'truth.lh5',shared,batch))
    h.require(raw_count==ledger==batch['primary_count']==run['number_of_simulated_events']==run['initial_ledger_count'],'Independent raw/initial census changed')
    return run

def verify_stream(directory):
    d,p,shared,batch=read_batch(directory);m=cs.load(d/'stream/manifest.json');run=cs.load(d/'run.json')
    verify_radiation(d)
    expected={key:shared[key] for key in ('model_id','model_sha256','model_contract','source_id','source_contract','source_mode','coordinate_transform','grouping_policy','clock_policy','source_sha256','unscored_volumes')}
    if shared['source_mode']=='cs137_legacy':expected['decay_photon_line_window_keV']=shared['decay_photon_line_window_keV']
    expected.update(kind=KIND,status='complete',producer_adapter=ADAPTER,primary_count=batch['primary_count'],batch=batch,
        global_decay_id_range=[0,batch['primary_count']-1],global_initial_id_range=batch['global_initial_primary_id_range'],
        shared_prepared_ref=p['shared_prepared_ref'],shared_prepared_sha256=p['shared_prepared_sha256'],source_lh5='../truth.lh5',
        run_ref=(d/'run.json').relative_to(h.ROOT).as_posix(),macro_ref=(d/'run.mac').relative_to(h.ROOT).as_posix(),
        macro_sha256=h.sha256(d/'run.mac'),units={'energy':'keV','length':'mm','time':'ns'},raw_track_energy_unit='MeV',raw_position_unit='m')
    h.require(all(B.typed_equal(m.get(key),value) for key,value in expected.items()) and m['run_sha256']==h.sha256(d/'run.json') and m['source_lh5_sha256']==h.sha256(d/'truth.lh5'),'Rehashed stream binding/policy changed')
    for a,b in itertools.zip_longest(raw_events(d/'truth.lh5',shared,batch),iter_stream(d/'stream/manifest.json')):h.require(a==b,'Stream changed original raw rows')
    return m

def main(argv=None):
    global WINDOWS_ROOT
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=('check','prepare','run','extract','verify'));parser.add_argument('--request');parser.add_argument('--request-json');parser.add_argument('--checked');parser.add_argument('--shared');parser.add_argument('--batch');parser.add_argument('--output');parser.add_argument('--directory');parser.add_argument('--stage',choices=('geometry','radiation','event_ledger'),default='event_ledger');parser.add_argument('--windows-root',required=True);a=parser.parse_args(argv)
    WINDOWS_ROOT=a.windows_root
    if a.action=='check':
        h.require(bool(a.request)!=bool(a.request_json),'Provide one request input')
        value=check(W.decode_json(a.request_json) if a.request_json else cs.load(a.request))
    elif a.action=='prepare':value=prepare(cs.load(a.request),a.output,cs.load(a.checked))
    elif a.action=='run':value=run(a.shared,cs.load(a.batch),a.output)
    elif a.action=='extract':value=extract(a.directory)
    elif a.stage=='geometry':value=read_shared(a.shared)
    elif a.stage=='radiation':value=verify_radiation(a.directory)
    else:value=verify_stream(a.directory)
    print(json.dumps(value,allow_nan=False))
if __name__=='__main__':main()
