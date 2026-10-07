"""Shared catalog semiconductor transport in the unchanged nominal cryostat.

Original producers stay byte intact. New shapes reuse their raw row readers
through one explicit geometry-membership hook, without changing event physics.
"""
from __future__ import annotations
import argparse, copy, itertools, json, re, subprocess, sys, time
from pathlib import Path
import handoff as h
import cs137 as cs
import decay_source as D
import scenario_source_portable as P
import catalog_geometry as G
import catalog_exporter_setup as X
sys.path.insert(0,str(h.ROOT/'tools'))
import scenario_workflow as W
import decay_workflow as DW

KIND='catalog_decay_stream_v1'
PREPARED_KIND='catalog_source_prepared_v1'
ADAPTER='catalog_source_v1'
EXPORTER_REF='.local/m2a/catalog-source-build-v1/cryostat_catalog_export'
WINDOWS_ROOT=None

def source_preset(source):
    matches=[p for p in DW.presets(h.ROOT) if p['id']==source]
    h.require(len(matches)==1,'Unknown source');p=matches[0]
    h.require(source==W.CS or DW.capability(p,h.ROOT) is not None,'Source acceptance is withheld; original policy is retained')
    return p

def models():
    catalog=json.loads((h.ROOT/'models/catalog.json').read_text())
    return [G.load_model(d['id']) for d in catalog['detectors']]

def pins(model):
    refs=('transport/catalog_source.py','transport/catalog_geometry.py','transport/cryostat_catalog_export.cc','transport/catalog_exporter/CMakeLists.txt',
        'transport/handoff.py','transport/cs137.py','transport/decay_source.py','transport/scenario_source_portable.py',
        'transport/pixi.toml','transport/pixi.lock','transport/cryostat-source.json','transport/cryostat_nominal.json','models/catalog.json',
        DW.REGISTRY,DW.ANCHORS,'scenarios/detector-capabilities.json',EXPORTER_REF,'transport/catalog_exporter_setup.py',X.RECEIPT_REF)
    values={ref:h.sha256(h.ROOT/ref) for ref in refs}
    values.update(model['dependencies_sha256']);values[model['model_ref']]=model['model_sha256']
    values.update({'.local/transport/LBNL/'+name:digest for name,digest in cs.upstream_hashes().items()})
    return values

def check(selection):
    h.require(type(selection) is dict and set(selection)==W.FIELDS,'Unsupported catalog selection fields')
    h.require(cs.load(h.ROOT/'scenarios/detector-capabilities.json').get('catalog_adapter')==G.CATALOG_POLICY,'Common catalog capability policy changed')
    W.run_path(selection['name'],h.ROOT)
    h.require(selection['cryostat']==W.CRYOSTAT and selection['pose']=='nominal' and type(selection['primary_count']) is int and
        selection['primary_count'] in (20,500) and type(selection['seed']) is int and 0<selection['seed']<2147483647 and
        type(selection['threads']) is int and selection['threads'] in (1,2),'Unsupported catalog cryostat/source/count/runtime')
    model=G.load_model(selection['detector']);h.require(not model['placement']['blocking_reasons'],' '.join(model['placement']['blocking_reasons']))
    h.require(selection['detector'] not in G.OLD_MODELS,'Existing five detectors retain their original producers')
    p=source_preset(selection['source']);build=P.read_build_receipt(WINDOWS_ROOT)
    exporter=X.read(WINDOWS_ROOT)
    h.require(exporter['exporter']['ref']==EXPORTER_REF,'Shared catalog exporter reference changed')
    mode='cs137_legacy' if selection['source']==W.CS else 'registered_decay'
    data=None if mode=='cs137_legacy' else D.installed_data(p,build['runtime'])
    return {'kind':'catalog_source_checked_v1','schema_version':1,'selection':selection,'model_contract':model,'source_contract':p,
        'source_mode':mode,'source_position_global_mm':DW.anchors(h.ROOT)['source_pose']['position_global_mm'],
        'runtime':build['runtime'],'decay_data':data,'source_sha256':pins(model),'exporter_ref':EXPORTER_REF,'exporter_sha256':h.sha256(h.ROOT/EXPORTER_REF)}

def macro(meta):
    report=cs.load(meta['geometry_report_path']) if 'geometry_report_path' in meta else meta['geometry_checks']
    return cs.macro_text(report,meta['primary_count'],meta['source_position_global_mm']) if meta['source_mode']=='cs137_legacy' else D.macro_text(report,meta['primary_count'],meta['source_contract'],meta['source_position_global_mm'])

def source_pdg(source,mode):
    return cs.ION if mode=='cs137_legacy' else source['pdg']

def validate_report(report,model,probes):
    h.require(report['overlaps_passed'] is True and report['source_inside_fill'] is True,'Native catalog geometry overlap/source check failed')
    ge=next(v for v in report['volumes'] if v['name']=='germanium');tr=model['cavity']['coordinate_transform']
    h.require(h.np.allclose(ge['translation_global_mm'],tr['translation_global_mm'],rtol=0,atol=1e-10) and
        h.np.allclose(ge['rotation_local_to_global'],tr['rotation_local_to_global'],rtol=0,atol=1e-12),'Native model placement changed')
    h.require(len(probes)==len(report['probes']) and all(actual['index']==i and actual['classification']==probe['expected'] for i,(actual,probe) in enumerate(zip(report['probes'],probes))),'Native/YAML solid membership mismatch')

def prepare(selection,output,checked):
    h.require(check(selection)==checked,'Checked catalog inputs changed before preparation')
    output=h.local_path(output);h.require(not output.exists(),'Existing output is retained');output.mkdir(parents=True)
    model=checked['model_contract'];p=checked['source_contract'];a=DW.anchors(h.ROOT);mount=cs.load(h.ROOT/'transport/cryostat_nominal.json');probes=G.probes(model['geometry'])
    status={'kind':'catalog_geometry_receipt_v1','status':'failed','model_id':model['model_id']}
    try:
        h.publish_json(output/'checked-plan.json',checked);h.publish_json(output/'model-contract.json',model)
        P.runtime_data(output,checked['runtime'],P.CS137 if checked['source_mode']=='cs137_legacy' else P.GAMMA)
        if checked['decay_data'] is not None:h.publish_json(output/'runtime/decay-data.json',checked['decay_data'])
        h.write_new(output/'canonical.gdml',G.gdml_text(model['geometry']));h.write_new(output/'probe-points.txt',P.probe_text(probes));h.publish_json(output/'scenario.json',mount)
        h.write_new(output/'parameters.txt',P.parameter_text(mount,checked['source_position_global_mm'],False))
        command=[str(h.ROOT/EXPORTER_REF),str(h.ROOT/'.local/transport/LBNL/stage.tg'),*(str(output/name) for name in ('canonical.gdml','probe-points.txt','parameters.txt','geometry.gdml','geometry-report.json'))]
        t=time.perf_counter()
        with (output/'geometry.log').open('x',encoding='utf-8') as log:result=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=False)
        status.update(command=command,returncode=result.returncode,native_geometry_wall_s=time.perf_counter()-t)
        h.require(result.returncode==0 and not re.search(P.DIAGNOSTIC,(output/'geometry.log').read_text(errors='replace'),re.I),'Native geometry failed; retain report/log')
        report=cs.load(output/'geometry-report.json');validate_report(report,model,probes)
        meta={'kind':PREPARED_KIND,'schema_version':1,'producer_adapter':ADAPTER,'status':'complete','selection':selection,
            'model_id':model['model_id'],'model_sha256':model['model_sha256'],'model_contract':model,
            'source_id':p['id'],'source_contract':p,'source_mode':checked['source_mode'],'source_pdg':source_pdg(p,checked['source_mode']),
            'primary_count':selection['primary_count'],'seed':selection['seed'],'source_position_global_mm':checked['source_position_global_mm'],
            'clock_policy':'remage_initial_decay_secondaries_zero','daughter_lifetime_limit_ns':-1 if checked['source_mode']=='cs137_legacy' else 100000,
            'coordinate_transform':a['coordinate_transform'],'grouping_policy':dict(cs.POLICY),'geometry_checks':report,'probes':probes,
            'native_geometry_wall_s':status['native_geometry_wall_s'],'native_volume_mm3':report['crystal_volume_mm3'],
            'native_volume_scope':'Native solid volume; Boolean/MultiUnion estimates are diagnostic, not an exact-volume gate',
            'mass_geometry':model['geometry'],'contour_rz_mm':{'catalog_geometry':model['geometry']},
            'material_tables':{'stp/'+v['name']:v['material'] for v in report['volumes'] if v['name']!='ledger_0_PV'},
            'unscored_volumes':[{'name':'ledger_0_PV','material':'G4_AIR','reason':'unscored world; no full energy closure claim'}],
            'source_sha256':checked['source_sha256'],'upstream_sha256':cs.upstream_hashes(),'decay_photon_line_window_keV':cs.LINE,
            'files_sha256':{f.relative_to(output).as_posix():h.sha256(f) for f in output.rglob('*') if f.is_file()}}
        h.write_new(output/'run.mac',macro(meta));meta['files_sha256']['run.mac']=h.sha256(output/'run.mac')
        h.require(check(selection)==checked,'Checked runtime/model changed during native geometry');h.publish_json(output/'prepared.json',meta)
        status['status']='complete';return meta
    except BaseException as error:status['error']=str(error);raise
    finally:h.publish_json(output/'prepare-receipt.json',status)

def read_prepared(directory):
    d=h.local_path(directory);m=cs.load(d/'prepared.json');checked=cs.load(d/'checked-plan.json')
    h.require(m['kind']==PREPARED_KIND and m['status']=='complete' and check(m['selection'])==checked and m['model_contract']==checked['model_contract'] and m['source_contract']==checked['source_contract'],'Catalog preparation no longer reconstructs')
    for ref,digest in m['files_sha256'].items():h.require(h.sha256(P.safe_path(d,ref,True))==digest,'Prepared artifact changed: '+ref)
    model=checked['model_contract'];source=checked['source_contract'];selection=checked['selection'];report=cs.load(d/'geometry-report.json')
    authority={'schema_version':1,'producer_adapter':ADAPTER,'selection':selection,'model_id':model['model_id'],
        'model_sha256':model['model_sha256'],'source_id':source['id'],'source_mode':checked['source_mode'],'source_pdg':source_pdg(source,checked['source_mode']),
        'primary_count':selection['primary_count'],'seed':selection['seed'],'source_position_global_mm':checked['source_position_global_mm'],
        'clock_policy':'remage_initial_decay_secondaries_zero','daughter_lifetime_limit_ns':-1 if checked['source_mode']=='cs137_legacy' else 100000,
        'coordinate_transform':DW.anchors(h.ROOT)['coordinate_transform'],'grouping_policy':dict(cs.POLICY),
        'geometry_checks':report,'probes':G.probes(model['geometry']),'mass_geometry':model['geometry'],
        'contour_rz_mm':{'catalog_geometry':model['geometry']},'source_sha256':checked['source_sha256'],
        'upstream_sha256':cs.upstream_hashes(),'decay_photon_line_window_keV':cs.LINE,
        'material_tables':{'stp/'+v['name']:v['material'] for v in report['volumes'] if v['name']!='ledger_0_PV'},
        'unscored_volumes':[{'name':'ledger_0_PV','material':'G4_AIR','reason':'unscored world; no full energy closure claim'}]}
    h.require(all(m.get(key)==value for key,value in authority.items()),'Rehashed preparation source/geometry/identity policy edits are refused')
    validate_report(report,model,m['probes'])
    mount=cs.load(h.ROOT/'transport/cryostat_nominal.json')
    h.require(cs.load(d/'scenario.json')==mount and (d/'parameters.txt').read_text()==P.parameter_text(mount,checked['source_position_global_mm'],False)
        and (d/'canonical.gdml').read_text()==G.gdml_text(model['geometry']) and (d/'probe-points.txt').read_text()==P.probe_text(m['probes'])
        and (d/'run.mac').read_text()==macro(m),'Rehashed geometry/probes/source macro edits are refused')
    runtime=cs.load(d/'runtime/runtime.json');h.require(runtime['identity']==checked['runtime'],'Prepared runtime identity differs from checked authority')
    P.recheck_runtime_data(runtime,P.CS137 if checked['source_mode']=='cs137_legacy' else P.GAMMA)
    if checked['decay_data'] is not None:h.require(cs.load(d/'runtime/decay-data.json')==checked['decay_data'],'Prepared nuclear data binding changed')
    return d,m,checked

def events(path,meta):
    """Reuse the exact original row/track/time/unit readers, with CSG membership.

    This synchronous new worker injects only the validator's geometry dispatch.
    All list contours retain the original function; raw rows are never changed.
    """
    original=h.membership
    def selected_membership(shape,point,tolerance=h.BOUNDARY_MM):
        return G.membership(shape['catalog_geometry'],point,tolerance) if type(shape) is dict and set(shape)=={'catalog_geometry'} else original(shape,point,tolerance)
    h.membership=selected_membership
    try:
        reader=cs.iter_decays if meta['source_mode']=='cs137_legacy' else D.iter_decays
        for event in reader(path,meta):yield event
    finally:h.membership=original

def run(directory):
    d,m,checked=read_prepared(directory);h.require(not (d/'run.json').exists() and not (d/'truth.lh5').exists(),'Prior radiation is retained')
    command=['remage','--flat-output','-t','1','--rand-seed',str(m['seed']),'-o','truth.lh5','-g','geometry.gdml','--','run.mac']
    receipt={'kind':'catalog_transport_run_v1','status':'failed','command':command,'prepared_sha256':h.sha256(d/'prepared.json'),'versions':h.python_versions()}
    start=time.perf_counter()
    try:
        with (d/'run.log').open('x',encoding='utf-8') as log:
            for program,version in (('remage','1.1.0'),('geant4-config','11.3.2')):
                actual=subprocess.run([program,'--version'],text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,check=True).stdout.strip();h.require(actual==version,'Pinned runtime changed');receipt['versions'][program]=actual
            t=time.perf_counter();r=subprocess.run(command,cwd=d,stdout=log,stderr=subprocess.STDOUT,check=False);receipt.update(returncode=r.returncode,remage_wall_s=time.perf_counter()-t)
        h.require(r.returncode==0 and not re.search(P.DIAGNOSTIC,(d/'run.log').read_text(errors='replace'),re.I),'Radiation failed; preserve evidence')
        count=0;zeros=0
        for event in events(d/'truth.lh5',m):count+=1;zeros+=not any(step['energy_keV']>0 for step in event['steps'])
        h.require(count==m['primary_count'],'Complete raw primary ledger mismatch');read_prepared(d)
        receipt.update(status='complete',source_lh5_sha256=h.sha256(d/'truth.lh5'),number_of_simulated_events=count,zero_deposit_primaries=zeros)
    except BaseException as error:receipt['error']=str(error);raise
    finally:receipt['total_wall_s']=time.perf_counter()-start;h.publish_json(d/'run.json',receipt)
    return receipt

def extract(directory):
    import h5py
    d,m,checked=read_prepared(directory);run=cs.load(d/'run.json');h.require(run['status']=='complete' and run['source_lh5_sha256']==h.sha256(d/'truth.lh5'),'Original radiation receipt/hash changed')
    chunks,count=cs.write_chunks(events(d/'truth.lh5',m),d/'stream',100)
    with h5py.File(d/'truth.lh5','r') as raw:
        processes=list(cs.table_rows(raw['processes']));aliases=cs.step_aliases(raw,m['material_tables'])
        tables={key:{'rows':len(next(iter(raw[key].values()))),'columns':{name:{'dtype':str(ds.dtype),'units':cs.scalar(ds.attrs.get('units',''))} for name,ds in raw[key].items()}} for key in ('vtx','particles','tracks','processes',*m['material_tables'])}
    stream={key:m[key] for key in ('model_id','model_sha256','model_contract','primary_count','source_id','source_contract','source_mode','coordinate_transform','grouping_policy','clock_policy','source_sha256','unscored_volumes','decay_photon_line_window_keV')}
    stream.update(kind=KIND,producer_adapter=ADAPTER,status='complete',global_decay_id_range=[0,count-1],
        source_lh5='../truth.lh5',source_lh5_sha256=run['source_lh5_sha256'],prepared_sha256=h.sha256(d/'prepared.json'),run_sha256=h.sha256(d/'run.json'),
        config_sha256=h.sha256(d/'scenario.json'),geometry_sha256=h.sha256(d/'geometry.gdml'),macro_sha256=h.sha256(d/'run.mac'),
        units={'energy':'keV','length':'mm','time':'ns'},processes=processes,chunks=chunks,raw_tables=tables,uid_aliases=aliases,raw_track_energy_unit='MeV',raw_position_unit='m',
        ledger={'kind':'recorded-only','full_energy_closure':None,'missing_closure':['world-air deposition','terminal escape energy','neutrino escape balance','complete decay/recoil accounting'],'passive_raw_rows':'hashed truth.lh5; complete material rows/sums in JSONL'})
    h.publish_json(d/'stream/manifest.json',stream);verify(d);return stream

def stream_events(path):
    path=h.local_path(path);m=cs.load(path);count=0
    for chunk in m['chunks']:
        h.require(Path(chunk['file']).name==chunk['file'] and chunk['first_global_decay_id']==count,'Unsafe/reordered stream chunk');file=path.parent/chunk['file'];h.require(h.sha256(file)==chunk['sha256'],'Stream chunk changed');n=0
        with file.open(encoding='utf-8') as rows:
            for line in rows:
                event=W.decode_json(line);h.require(event['event_id']==event['global_decay_id']==count,'Missing/foreign original primary');count+=1;n+=1;yield event
        h.require(n==chunk['count'],'Chunk census changed')
    h.require(count==m['primary_count'],'Stream primary census changed')

def verify(directory,stage='event_ledger'):
    d,m,checked=read_prepared(directory)
    if stage=='geometry':return checked
    run=cs.load(d/'run.json');h.require(run['status']=='complete' and run['prepared_sha256']==h.sha256(d/'prepared.json') and run['source_lh5_sha256']==h.sha256(d/'truth.lh5'),'Original radiation changed')
    if stage=='radiation':
        h.require(sum(1 for _ in events(d/'truth.lh5',m))==m['primary_count'],'Raw independent initial census changed');return checked
    stream=cs.load(d/'stream/manifest.json');h.require(stream['kind']==KIND and stream['model_contract']==m['model_contract'] and stream['prepared_sha256']==h.sha256(d/'prepared.json') and stream['run_sha256']==h.sha256(d/'run.json') and stream['source_lh5_sha256']==h.sha256(d/'truth.lh5'),'Stream binding changed')
    authority={key:m[key] for key in ('model_id','model_sha256','model_contract','primary_count','source_id','source_contract','source_mode','coordinate_transform','grouping_policy','clock_policy','source_sha256','unscored_volumes','decay_photon_line_window_keV')}
    authority.update(producer_adapter=ADAPTER,status='complete',global_decay_id_range=[0,m['primary_count']-1],source_lh5='../truth.lh5',
        config_sha256=h.sha256(d/'scenario.json'),geometry_sha256=h.sha256(d/'geometry.gdml'),macro_sha256=h.sha256(d/'run.mac'),
        units={'energy':'keV','length':'mm','time':'ns'},raw_track_energy_unit='MeV',raw_position_unit='m',
        ledger={'kind':'recorded-only','full_energy_closure':None,'missing_closure':['world-air deposition','terminal escape energy','neutrino escape balance','complete decay/recoil accounting'],'passive_raw_rows':'hashed truth.lh5; complete material rows/sums in JSONL'})
    h.require(all(stream.get(key)==value for key,value in authority.items()),'Rehashed stream coordinate/source/unit/ledger policy edits are refused')
    for raw,record in itertools.zip_longest(events(d/'truth.lh5',m),stream_events(d/'stream/manifest.json')):h.require(raw==record,'Stream changed original radiation rows')
    return checked

def main(argv=None):
    global WINDOWS_ROOT
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=('models','check','prepare','run','extract','verify'));p.add_argument('--selection-json');p.add_argument('--selection');p.add_argument('--checked');p.add_argument('--output');p.add_argument('--directory');p.add_argument('--stage',choices=('geometry','radiation','event_ledger'),default='event_ledger');p.add_argument('--windows-root',required=True);a=p.parse_args(argv);WINDOWS_ROOT=a.windows_root
    if a.action=='models':value=models()
    elif a.action=='check':value=check(W.decode_json(a.selection_json) if a.selection_json else cs.load(a.selection))
    elif a.action=='prepare':value=prepare(cs.load(a.selection),a.output,cs.load(a.checked))
    elif a.action=='run':value=run(a.directory)
    elif a.action=='extract':value=extract(a.directory)
    else:value=verify(a.directory,a.stage)
    print(json.dumps(value,sort_keys=True,allow_nan=False))
if __name__=='__main__':main()
