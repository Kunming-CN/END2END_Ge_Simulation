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
import nonzero_events as NZ

KIND='radioactive_decay_batch_stream_v1'
ADAPTER='shared_decay_batch_source_v1'
PREPARED_KIND='batch_shared_transport_prepared_v1'
WINDOWS_ROOT=None

def selection_request(selection):
    return {'detector':'GeRC02_Li50min' if selection['detector']=='GeRC02' else selection['detector'],
        'source_mode':selection['source'],'source_pose':selection['pose'],'primary_count':20,'seed':selection['seed']}

def legacy_check(selection):
    selection={k:v for k,v in selection.items() if k!='angle_deg'}
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
    h.require(type(selection) is dict and set(selection) in (W.FIELDS,W.FIELDS|{'angle_deg'}) and
        selection['cryostat']==W.CRYOSTAT and selection['pose']=='nominal' and
        type(selection['threads']) is int and selection['threads'] in (1,2) and
        (selection['source']==W.CS or (DW.is_source(selection['source'],h.ROOT) and DW.capability(DW.preset(selection['source'],h.ROOT),h.ROOT) is not None)),
        'Batch source/detector has no admitted nominal connector')
    B.partition(selection['primary_count'],selection['seed'])
    angle=selected_angle(selection)
    legacy=legacy_check(selection)
    checked={'kind':'batch_transport_checked_v1','schema_version':1,'selection':selection,
        'geometry_preparation_count':20,'legacy_geometry_plan':legacy,
        'adapter_sha256':h.sha256(Path(__file__)),'runtime':legacy['runtime']}
    if angle:
        import source_angle as A
        A.WINDOWS_ROOT=WINDOWS_ROOT
        bounded=copy.deepcopy(selection);bounded['primary_count']=20
        checked['angle_geometry_plan']=A.check(bounded)
        checked['source_pose']=checked['angle_geometry_plan']['source_pose']
    return checked


def selected_angle(selection):
    if 'angle_deg' not in selection:return 0
    import source_pose as Pose
    return Pose.angle(selection)

def prepare(selection,output,checked):
    h.require(check(selection)==checked,'Transport checked plan changed')
    out=h.local_path(output);h.require(not out.exists(),'Preserve existing shared preparation')
    out.mkdir(parents=True);legacy=out/'legacy';request=selection_request(selection)
    original=checked['legacy_geometry_plan']
    if selected_angle(selection):
        import source_angle as A
        A.WINDOWS_ROOT=WINDOWS_ROOT
        meta=A.prepare(checked['angle_geometry_plan']['selection'],legacy,checked['angle_geometry_plan'])
    elif selection['detector'] not in W.MODELS:
        C.WINDOWS_ROOT=WINDOWS_ROOT
        bounded={k:copy.deepcopy(v) for k,v in selection.items() if k!='angle_deg'};bounded['primary_count']=20
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
    if selected_angle(s):
        import source_angle as A
        A.WINDOWS_ROOT=WINDOWS_ROOT
        meta=A.read_prepared(legacy)[1]
    elif s['detector'] not in W.MODELS:
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
    text=cs.macro_text(report,batch['primary_count'],shared['source_position_global_mm']) if shared['source_mode']=='cs137_legacy' else D.macro_text(report,batch['primary_count'],shared['source_contract'],shared['source_position_global_mm'])
    if 'source_pose' in shared:
        import source_angle as A
        h.require(shared['gps_precision_contract']==A.GPS_PRECISION_CONTRACT,'Angular GPS precision contract changed')
        return A.precise_gps_macro(text)
    return text

def raw_events(path,shared,batch):
    meta=copy.deepcopy(shared);meta.update(primary_count=batch['primary_count'],seed=batch['radiation_seed'])
    if 'source_pose' in shared:
        import source_angle as A
        reader=A.events
    else:reader=C.events if shared['model_id'] not in W.MODELS else cs.iter_decays if shared['source_mode']=='cs137_legacy' else D.iter_decays
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
    path=h.local_path(path);m=cs.load(path);expected=0;previous=-1;stored=0
    h.require(m['kind']==KIND and m['status']=='complete','Wrong stream')
    policy=NZ.storage(m,initial_primaries=m['primary_count'])
    if policy is not None:NZ.initial_summary(m)
    for chunk in m['chunks']:
        first=chunk['first_global_decay_id']
        h.require(Path(chunk['file']).name==chunk['file'] and type(first) is int and
            (first==expected if policy is None else previous<first<m['primary_count']), 'Unsafe/reordered stream chunk')
        h.require(type(chunk['count']) is int and 1<=chunk['count']<=100,'Invalid stream chunk count')
        f=path.parent/chunk['file'];h.require(h.sha256(f)==chunk['sha256'],'Stream chunk changed');n=0
        with f.open(encoding='utf-8') as stream:
            for line in stream:
                e=W.decode_json(line);eid=e['event_id']
                h.require(type(eid) is int and previous<eid<m['primary_count'] and
                    all(type(e[k]) is int for k in ('global_decay_id','local_initial_id','global_initial_id','batch_index')) and
                    eid==e['global_decay_id']==e['local_initial_id'] and
                    e['global_initial_id']==m['batch']['global_initial_offset']+eid and e['batch_index']==m['batch']['batch_index'],'Stream identity changed')
                h.require((eid==expected) if policy is None else NZ.has_nonzero_deposit(e),'Historical census changed or sparse stream retained zero deposition')
                if n==0:h.require(eid==first,'Chunk first identity changed')
                previous=eid;expected+=1;stored+=1;n+=1;yield e
        h.require(n==chunk['count'],'Chunk count changed')
    h.require(stored==(m['primary_count'] if policy is None else policy['nonzero_primaries']),'Incomplete stream census')

def empty_initial_summary(shared):
    summary={k:0 for k in ('initial_primaries','initial_decays','zero_deposit_primaries','nonzero_primaries','line_photons','decay_photons')}
    if shared['source_mode']=='registered_decay':
        summary['line_photon_counts']={x['name']:0 for x in shared['source_contract']['diagnostic_lines']}
    return summary

def summarize_initial(summary,event):
    nonzero=NZ.has_nonzero_deposit(event)
    summary['initial_primaries']+=1;summary['initial_decays']+=1
    summary['zero_deposit_primaries']+=not nonzero;summary['nonzero_primaries']+=nonzero
    summary['line_photons']+=event['line_photon_count'];summary['decay_photons']+=event['decay_photon_count']
    if 'line_photon_counts' in summary:
        h.require(set(event['line_photon_counts'])==set(summary['line_photon_counts']),'Named photon census changed')
        for name,value in event['line_photon_counts'].items():summary['line_photon_counts'][name]+=value
    return nonzero

def write_nonzero_chunks(events,destination,shared,chunk_size=100):
    """Keep nonzero original records; retain omitted initial events only as counts."""
    h.require(type(chunk_size) is int and 1<=chunk_size<=100,'Chunk size must be 1..100')
    destination=h.local_path(destination);h.require(not destination.exists(),'Stream output exists');destination.mkdir()
    chunks=[];summary=empty_initial_summary(shared);stream=None;part=None
    def seal():
        stream.flush();os.fsync(stream.fileno());stream.close()
        final=part.with_suffix('');os.link(part,final);part.unlink();chunks[-1]['sha256']=h.sha256(final)
    try:
        for e in events:
            eid=e['event_id']
            h.require(eid==e['global_decay_id']==summary['initial_primaries'],'Duplicate/missing raw initial identity')
            if not summarize_initial(summary,e):continue
            if stream is None or chunks[-1]['count']==chunk_size:
                if stream is not None:seal()
                name=f'decays-{eid:08d}.jsonl';part=destination/(name+'.partial');stream=part.open('x',encoding='utf-8',newline='\n')
                chunks.append({'file':name,'first_global_decay_id':eid,'count':0})
            stream.write(json.dumps(e,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n');chunks[-1]['count']+=1
        if stream is not None:seal()
    finally:
        if stream is not None and not stream.closed:stream.close()
    return chunks,summary

def extract(directory):
    import h5py
    d,p,shared,batch=read_batch(directory);run=cs.load(d/'run.json')
    h.require(run['status']=='complete' and run['source_lh5_sha256']==h.sha256(d/'truth.lh5') and run['prepared_sha256']==h.sha256(d/'batch-prepared.json'),'Unsealed radiation')
    chunks,summary=write_nonzero_chunks(raw_events(d/'truth.lh5',shared,batch),d/'stream',shared)
    count=summary['initial_primaries'];h.require(count==batch['primary_count'],'Incomplete raw initial census')
    with h5py.File(d/'truth.lh5','r') as raw:
        processes=list(cs.table_rows(raw['processes']));aliases=cs.step_aliases(raw,shared['material_tables'])
        tables={key:{'rows':len(next(iter(raw[key].values()))),'columns':{name:{'dtype':str(ds.dtype),'units':cs.scalar(ds.attrs.get('units',''))} for name,ds in raw[key].items()}} for key in ('vtx','particles','tracks','processes',*shared['material_tables'])}
    m={key:shared[key] for key in ('model_id','model_sha256','model_contract','source_id','source_contract','source_mode','coordinate_transform','grouping_policy','clock_policy','source_sha256','unscored_volumes')}
    if 'source_pose' in shared:
        m.update(source_pose=shared['source_pose'],source_position_global_mm=shared['source_position_global_mm'])
    if shared['source_mode']=='cs137_legacy':m['decay_photon_line_window_keV']=shared['decay_photon_line_window_keV']
    m.update(kind=KIND,status='complete',producer_adapter=ADAPTER,primary_count=count,batch=batch,
        event_storage=NZ.descriptor(count,summary['zero_deposit_primaries']),initial_summary=summary,
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
    if 'source_pose' in shared:
        expected.update(source_pose=shared['source_pose'],source_position_global_mm=shared['source_position_global_mm'])
    else:h.require('source_pose' not in m,'Legacy fixed stream cannot carry an angular pose')
    if shared['source_mode']=='cs137_legacy':expected['decay_photon_line_window_keV']=shared['decay_photon_line_window_keV']
    expected.update(kind=KIND,status='complete',producer_adapter=ADAPTER,primary_count=batch['primary_count'],batch=batch,
        global_decay_id_range=[0,batch['primary_count']-1],global_initial_id_range=batch['global_initial_primary_id_range'],
        shared_prepared_ref=p['shared_prepared_ref'],shared_prepared_sha256=p['shared_prepared_sha256'],source_lh5='../truth.lh5',
        run_ref=(d/'run.json').relative_to(h.ROOT).as_posix(),macro_ref=(d/'run.mac').relative_to(h.ROOT).as_posix(),
        macro_sha256=h.sha256(d/'run.mac'),units={'energy':'keV','length':'mm','time':'ns'},raw_track_energy_unit='MeV',raw_position_unit='m')
    h.require(all(B.typed_equal(m.get(key),value) for key,value in expected.items()) and m['run_sha256']==h.sha256(d/'run.json') and m['source_lh5_sha256']==h.sha256(d/'truth.lh5'),'Rehashed stream binding/policy changed')
    policy=NZ.storage(m,initial_primaries=batch['primary_count'])
    summary=empty_initial_summary(shared)
    def expected_events():
        for event in raw_events(d/'truth.lh5',shared,batch):
            nonzero=summarize_initial(summary,event)
            if policy is None or nonzero:yield event
    for a,b in itertools.zip_longest(expected_events(),iter_stream(d/'stream/manifest.json')):
        h.require(B.typed_equal(a,b),'Stream changed original nonzero raw rows')
    if policy is not None:
        NZ.initial_summary(m)
        h.require(B.typed_equal(policy,NZ.descriptor(summary['initial_primaries'],summary['zero_deposit_primaries'])) and
            B.typed_equal(m['initial_summary'],summary),'Rehashed sparse counts/photon denominators changed')
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
