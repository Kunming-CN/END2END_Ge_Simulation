"""One shared at-rest decay transport for registered isotopes and five detector contracts."""
import argparse, itertools, json, math, os, re, shutil, subprocess, sys, time
from pathlib import Path
import cs137 as cs
import handoff as h
import scenario_prepare as assembly
import scenario_source_portable as P
import ring_cs137 as rings
sys.path.insert(0,str(h.ROOT/'tools'))
import decay_workflow as D
import scenario_workflow as W
KIND='radioactive_decay_stream_v1'
ADAPTER='shared_decay_source_v1'
PREPARED_KIND='decay_source_prepared_v1'
WINDOWS_ROOT=None
def generic_source_hashes():
    refs=(D.REGISTRY,D.ANCHORS,'transport/decay_source.py','tools/decay_workflow.py',
          'tools/ring_workflow.py','tools/ring_model_contract.py','tools/sap18_workflow.py',
          'transport/ring_cs137.py','transport/sap18_source.py','transport/scenario_prepare.py')
    return {r:h.sha256(h.ROOT/r) for r in refs}
def detector(request):
    return 'GeRC02' if request['detector']=='GeRC02_Li50min' else request['detector']
def geometry_contract(model):
    if model in W.RINGS:
        points=rings.contour(model);probes=rings.probes(model,points);volume=rings.reference_volume(model)
    elif model==W.SAP18:
        import sap18_source as sap
        points=sap.contour(model);probes=sap.probes(model,points);volume=sap.reference_volume(model)
    else:
        _,points=h.load_model(model);probes=h.probe_points(points);volume=h.reference_volume(model)
    return points,probes,volume
def scenario(source_id):
    a=D.anchors(h.ROOT);p=D.preset(source_id,h.ROOT)
    # Geometry has a single source point/material anchor. Only isotope metadata differs.
    return {'schema_version':1,'scenario':'shared-LBNL-nominal-decay-v1','status':a['status'],
        'coordinate_transform':a['coordinate_transform'],'expected_vacuum_global_translation_mm':a['expected_vacuum_global_translation_mm'],
        'crystal_in_vacuum_translation_mm':a['crystal_in_vacuum_translation_mm'],'spacer':a['spacer'],'capsule':a['capsule'],
        'source':{'Z':p['Z'],'A':p['A'],'kinetic_energy_eV':0,'position_global_mm':a['source_pose']['position_global_mm'],'distribution':'point','activity_Bq':None},
        'overlap_samples':a['overlap_samples'],'mounting_contract':{'kind':'shared_nominal_mounting_v1','placement_contract':a}}
def validate_geometry(report,model,mounting,probes):
    if model in W.RINGS or model==W.SAP18:
        rings.validate_report(report,'KMRC01_candidate' if model==W.SAP18 else model,mounting,probes)
    else:
        assembly.validate_report(report,{'assets':{'detector':{'id':model}},'coordinate_transform':mounting['coordinate_transform'],
            'source_position_global_mm':mounting['source']['position_global_mm']},probes)
def installed_data(p,runtime):
    prefix=Path(runtime['prefix']).resolve()
    packages={'G4RADIOACTIVEDATA':'geant4-data-radioactivedecay','G4LEVELGAMMADATA':'geant4-data-photonevaporation','G4ENSDFSTATEDATA':'geant4-data-ensdfstate'}
    result={'source_id':p['id'],'required_files':{},'datasets':{}}
    for variable,files in p['required_data_sha256'].items():
        h.require(variable in os.environ,'Missing installed dataset '+variable)
        directory=Path(os.environ[variable]).resolve()
        h.require(directory.is_dir() and directory.is_relative_to(prefix),'Dataset outside locked runtime prefix')
        actual={name:h.sha256(directory/name) for name in files}
        h.require(actual==files,'Installed required isotope data changed')
        result['required_files'][variable]={'directory_name':directory.name,'files_sha256':actual}
        result['datasets'][variable]={'directory':str(directory),'package':runtime['packages'][packages[variable]]}
    header=prefix/'include/remage/RMGSteppingAction.hh'
    text=header.read_text()
    h.require('SetDaughterKillLifetime' in text and 'ground-state nuclei' in text,'Missing installed ground-secondary lifetime API')
    result['ground_secondary_lifetime_api']={'ref':header.relative_to(prefix).as_posix(),'sha256':h.sha256(header),
        'semantics':'installed remage ground-state secondary nucleus lifetime cap; prompt excited daughter emissions retained'}
    return result
def check_request(request):
    h.require(type(request) is dict and set(request)=={'detector','source_mode','source_pose','primary_count','seed'},'Unsupported shared source request keys')
    model=detector(request);p=D.preset(request['source_mode'],h.ROOT);a=D.anchors(h.ROOT)
    h.require(model in W.MODELS and request['source_pose']=='nominal' and type(request['primary_count']) is int and request['primary_count'] in p['counts'] and
        type(request['seed']) is int and 0<request['seed']<2147483647,'Unsupported shared source tuple')
    build=P.read_build_receipt(WINDOWS_ROOT);geometry_contract(model);data=installed_data(p,build['runtime'])
    marker={'kind':'shared_decay_source_execution_v1','adapter_ref':'transport/decay_source.py',
        'adapter_sha256':h.sha256(Path(__file__)),'source_id':p['id'],'build_receipt_ref':P.BUILD_RECEIPT_REF,
        'build_receipt_sha256':h.sha256(h.ROOT/P.BUILD_RECEIPT_REF),'exporter_ref':P.EXPORTER_REF,
        'exporter_sha256':build['exporter']['sha256'],'exporter_bytes':build['exporter']['bytes']}
    pins={**generic_source_hashes(),P.BUILD_RECEIPT_REF:marker['build_receipt_sha256'],P.EXPORTER_REF:marker['exporter_sha256']}
    return {'kind':'decay_source_checked_plan_v1','schema_version':1,'request':request,
        'execution_contract':marker,'portable_source_sha256':pins,'canonical_source_sha256':P.canonical_sources(),
        'upstream_sha256':cs.upstream_hashes(),'runtime':build['runtime'],'source_contract':p,'placement_contract':a,'decay_data':data}
def macro_text(report,count,p,source):
    """Generate commands from the source record; never rewrite a Cs/gamma macro."""
    D.validate_source(p)
    lines=['# At-rest initial nucleus; conditional clock, not activity clock.']
    for i,v in enumerate(report['volumes']):
        if v['name']=='ledger_0_PV':continue
        h.require(type(v['copy_number']) is int,'Missing physical-volume copy number')
        scheme='Germanium' if v['name']=='germanium' else 'Scintillator'
        lines.append(f'/RMG/Geometry/RegisterDetector {scheme} {v["name"]} {i+1} {v["copy_number"]}')
    lines+=['/RMG/Output/NtupleUseVolumeName true','/RMG/Output/NtuplePerDetector true',
        '/RMG/Output/ActivateOutputScheme Track','/RMG/Processes/LowEnergyEMPhysics Livermore',
        '/RMG/Processes/HadronicPhysics None','/RMG/Processes/OpticalPhysics false','/run/initialize',
        '/process/had/rdm/thresholdForVeryLongDecayTime 1e27 ns',
        '/RMG/Processes/Stepping/ResetInitialDecayTime true',
        '/RMG/Processes/Stepping/DaughterNucleusMaxLifetime 100000 ns',
        '/RMG/Processes/Stepping/LargeGlobalTimeUncertaintyWarning 0.001 ns',
        '/RMG/Processes/DefaultProductionCut 0.1 mm','/RMG/Processes/SensitiveProductionCut 0.01 mm']
    for scheme in ('Germanium','Scintillator'):
        lines += [f'/RMG/Output/{scheme}/StoreSinglePrecisionEnergy false',f'/RMG/Output/{scheme}/StoreSinglePrecisionPosition false',
            f'/RMG/Output/{scheme}/StoreTrackID true',f'/RMG/Output/{scheme}/StepPositionMode Both',
            f'/RMG/Output/{scheme}/Cluster/PreClusterOutputs false',f'/RMG/Output/{scheme}/DiscardZeroEnergyHits false']
    lines += ['/RMG/Output/Track/StoreSinglePrecisionPosition false','/RMG/Output/Track/StoreSinglePrecisionEnergy false',
        '/RMG/Output/Track/StoreAlways true','/RMG/Output/Vertex/SkipPrimaryVertexOutput false',
        '/RMG/Output/Vertex/StoreSinglePrecisionPosition false','/RMG/Output/Vertex/StoreSinglePrecisionEnergy false',
        '/RMG/Output/Vertex/StorePrimaryParticleInformation true','/RMG/Generator/Select GPS','/gps/particle ion',
        f'/gps/ion {p["Z"]} {p["A"]}','/gps/energy 0 eV','/gps/pos/type Point',
        '/gps/pos/centre '+' '.join(format(v,'.17g') for v in source)+' mm','/gps/time 0 ns','/gps/number 1',f'/run/beamOn {count}']
    return '\n'.join(lines)+'\n'
def prepare(request,output,checked):
    h.require(check_request(request)==checked,'Checked source changed before preparation')
    output=h.local_path(output);h.require(not output.exists(),'Preserve prior preparation')
    model=detector(request);p=checked['source_contract'];mount=scenario(p['id']);points,probes,volume=geometry_contract(model)
    output.mkdir(parents=True);status={'status':'failed','stage':'prepare','model_id':model,'source_id':p['id']}
    try:
        h.publish_json(output/'portable-plan.json',checked)
        # Existing EMLOW verifier is source-neutral. Its legacy selector disables only Cs-specific data handling.
        P.runtime_data(output,checked['runtime'],P.GAMMA)
        h.publish_json(output/'runtime/decay-data.json',checked['decay_data'])
        c=D.prepare_model(model,output/'effective-model')
        h.write_new(output/'canonical.gdml',h.gdml_text(points));h.write_new(output/'probe-points.txt',P.probe_text(probes))
        h.publish_json(output/'scenario.json',mount)
        h.write_new(output/'parameters.txt',P.parameter_text(mount,mount['source']['position_global_mm'],False))
        inputs={f.relative_to(output).as_posix():h.sha256(f) for f in output.rglob('*') if f.is_file()}
        command=P.geometry_command(output);start=time.perf_counter()
        with (output/'geometry.log').open('x') as log:
            result=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=False)
        status.update(command=command,returncode=result.returncode,native_geometry_wall_s=time.perf_counter()-start)
        h.require(result.returncode==0,'Native geometry failed; preserve evidence')
        h.require(not re.search(r'\*\*\*\s*(Error|Fatal)|Overlap is detected|cannot open|failed to read|cryostat_export:',(output/'geometry.log').read_text(errors='replace'),re.I),'Geometry diagnostic failure')
        report=cs.load(output/'geometry-report.json');validate_geometry(report,model,mount,probes)
        h.require(check_request(request)==checked and all(h.sha256(output/r)==v for r,v in inputs.items()),'Inputs changed during geometry')
        h.write_new(output/'run.mac',macro_text(report,request['primary_count'],p,mount['source']['position_global_mm']))
        meta={'kind':PREPARED_KIND,'producer_adapter':ADAPTER,'source_id':p['id'],'source_contract':p,'placement_contract':checked['placement_contract'],
            'model_id':model,'model_sha256':c['source_model_sha256'],'model_contract':c,'primary_count':request['primary_count'],'seed':request['seed'],
            'source_pdg':p['pdg'],'source_position_global_mm':mount['source']['position_global_mm'],
            'clock_policy':'remage_initial_decay_secondaries_zero','daughter_lifetime_limit_ns':100000,'nuclear_policy':p['nuclear_policy'],
            'coordinate_transform':mount['coordinate_transform'],'contour_rz_mm':points,'grouping_policy':dict(cs.POLICY),
            'source_sha256':cs.source_hashes(),'generic_source_sha256':generic_source_hashes(),'upstream_sha256':cs.upstream_hashes(),
            'exporter_sha256':checked['execution_contract']['exporter_sha256'],'probes':probes,'analytic_volume_mm3':volume,
            'native_geometry_wall_s':status['native_geometry_wall_s'],'mounting_contract':mount['mounting_contract'],
            'material_tables':{'stp/'+v['name']:v['material'] for v in report['volumes'] if v['name']!='ledger_0_PV'},
            'unscored_volumes':[{'name':'ledger_0_PV','material':'G4_AIR','reason':'unscored default world; no full energy closure claim'}],
            'execution_contract':checked['execution_contract'],'portable_source_sha256':checked['portable_source_sha256'],
            'files_sha256':{f.relative_to(output).as_posix():h.sha256(f) for f in output.rglob('*') if f.is_file()}}
        h.publish_json(output/'prepared.json',meta);status['status']='complete';return meta
    except Exception as e:status['error']=str(e);raise
    finally:h.publish_json(output/'prepare-receipt.json',status)
def read_prepared(directory):
    d=h.local_path(directory);m=cs.load(d/'prepared.json');s=m['source_contract']
    request={'detector':m['model_contract']['variant_id'],'source_mode':s['id'],'source_pose':'nominal','primary_count':m['primary_count'],'seed':m['seed']}
    checked=check_request(request)
    h.require(m['kind']==PREPARED_KIND and m['producer_adapter']==ADAPTER and cs.load(d/'portable-plan.json')==checked and
        m['source_contract']==checked['source_contract'] and m['placement_contract']==checked['placement_contract'] and
        m['execution_contract']==checked['execution_contract'] and m['portable_source_sha256']==checked['portable_source_sha256'],
        'Shared preparation source/build/runtime authority changed')
    P.recheck_runtime_data(cs.load(d/'runtime/runtime.json'),P.GAMMA)
    h.require(cs.load(d/'runtime/decay-data.json')==checked['decay_data'],'Installed decay data/API changed')
    h.require(m['source_sha256']==cs.source_hashes() and m['generic_source_sha256']==generic_source_hashes() and m['upstream_sha256']==cs.upstream_hashes(),
        'Producer/original inputs changed')
    ref=(d/'effective-model/GeRC02.yaml').relative_to(h.ROOT).as_posix() if m['model_id']=='GeRC02' else None
    h.require(m['model_contract']==D.model_contract(m['model_id'],ref,h.ROOT) and
        cs.load(d/'effective-model/model-contract.json')==m['model_contract'] and m['model_sha256']==m['model_contract']['source_model_sha256'],
        'Effective model contract changed')
    if m['model_id']=='GeRC02':
        from ring_workflow import canonical_bytes
        h.require((d/'effective-model/GeRC02.yaml').read_bytes()==canonical_bytes('GeRC02')[0],'Effective Li model delta changed')
    points,probes,volume=geometry_contract(m['model_id']);mount=scenario(s['id'])
    h.require(m['source_pdg']==s['pdg'] and m['nuclear_policy']==D.POLICY and m['daughter_lifetime_limit_ns']==100000 and
        m['clock_policy']=='remage_initial_decay_secondaries_zero' and m['grouping_policy']==cs.POLICY and
        m['contour_rz_mm']==[list(v) for v in points] and m['probes']==probes and m['analytic_volume_mm3']==volume and
        cs.load(d/'scenario.json')==mount and m['coordinate_transform']==mount['coordinate_transform'] and
        m['mounting_contract']==mount['mounting_contract'] and m['source_position_global_mm']==mount['source']['position_global_mm'],
        'Preparation geometry/clock policy changed')
    for ref,digest in m['files_sha256'].items():
        h.require(type(ref) is str and '\\' not in ref and not Path(ref).is_absolute() and '..' not in Path(ref).parts and
            h.sha256(h.local_path(d/ref))==digest,'Prepared input changed or unsafe ref')
    report=cs.load(d/'geometry-report.json');validate_geometry(report,m['model_id'],mount,probes)
    h.require((d/'run.mac').read_text()==macro_text(report,m['primary_count'],s,m['source_position_global_mm']),'Exact source macro changed')
    return d,m,checked
def validate_tracks(tracks,process_names,p):
    byid={}
    for t in tracks:
        h.require(type(t['trackid']) is int and t['trackid']>0 and t['trackid'] not in byid and
            type(t['parent_trackid']) is int and t['parent_trackid']>=0 and t['time']>=0 and t['ekin']>=0 and
            (t['parent_trackid']==0 or t['procid'] in process_names),'Invalid/duplicate track or process')
        byid[t['trackid']]=t
    roots=[t for t in tracks if t['parent_trackid']==0]
    h.require(len(roots)==1 and roots[0]['particle']==p['pdg'] and roots[0]['ekin']==0,'Wrong registered ion root')
    root=roots[0];children=[t for t in tracks if t['parent_trackid']==root['trackid']]
    h.require(children and all(t['time']==0 for t in children),'Initial children not reset to zero')
    h.require(any(t['particle']//10==p['ground_daughter_pdg']//10 for t in children),'Missing intended initial daughter')
    families={p['pdg']//10,p['ground_daughter_pdg']//10};allowed=p['allowed_light_nuclear_pdgs']
    for t in tracks:
        parent=t['parent_trackid'];visited={t['trackid']}
        while parent:
            h.require(parent in byid and parent not in visited,'Missing/cyclic ancestry')
            visited.add(parent);parent=byid[parent]['parent_trackid']
        parent=t['parent_trackid']
        h.require(parent==0 or parent==root['trackid'] or t['time']>=byid[parent]['time'],'Child precedes parent')
        if abs(t['particle'])>=1000000000:
            h.require(t['particle']//10 in families or t['particle'] in allowed,'Unexpected descendant nuclear family')
        if parent and byid[parent]['particle']==p['ground_daughter_pdg'] and 'radioactivedecay' in process_names[t['procid']].lower():
            h.require(t['time']<=p['nuclear_policy']['ground_secondary_lifetime_cap_ns'],'Delayed ground-daughter chain escaped cap')
    return byid


def iter_decays(path,meta):
    """One flat serial LH5; retain raw row/unit/UID and all initial-zero identities."""
    import h5py
    count=meta['primary_count'];p=meta['source_contract']
    with h5py.File(path,'r') as raw:
        census=raw['number_of_simulated_events']
        h.require(census.shape==() and census.dtype.kind in 'iu' and int(census[()])==count,'Initial-primary census mismatch')
        processes=list(cs.table_rows(raw['processes']));names={v['procid']:v['name'] for v in processes}
        h.require(len(names)==len(processes),'Duplicate process ID')
        h.require(all(k in raw for k in ('vtx','particles','tracks','stp/germanium')),'Missing required table')
        for key in ('vtx','particles','tracks'):cs.field(raw[key],'evtid',integer=True)
        for key in ('particles','tracks'):
            cs.field(raw[key],'particle',integer=True)
            for name in ('ekin','px','py','pz'):cs.field(raw[key],name,'MeV')
        cs.field(raw['particles'],'vertexid',integer=True);cs.field(raw['vtx'],'n_part',integer=True)
        for key in ('vtx','tracks'):
            cs.field(raw[key],'time','ns')
            for axis in ('xloc','yloc','zloc'):cs.field(raw[key],axis,'m')
        for name in ('trackid','parent_trackid','procid'):cs.field(raw['tracks'],name,integer=True)
        materials=meta['material_tables'];cs.step_aliases(raw,materials)
        h.require({'stp/'+k for k in raw['stp'] if k!='__by_uid__'}==set(materials),'Material table missing; missing output is not zero')
        for key in materials:
            cs.field(raw[key],'evtid',integer=True)
            for name in ('trackid','parent_trackid','particle'):cs.field(raw[key],name,integer=True)
            cs.field(raw[key],'edep','keV');cs.field(raw[key],'time','ns')
            for suffix in ('','_pre','_post'):
                for axis in ('xloc','yloc','zloc'):cs.field(raw[key],axis+suffix,'m')
        cursors={key:cs.Cursor(raw[key],count) for key in ('vtx','particles','tracks',*materials)}
        for eid in range(count):
            rows={key:c.take(eid) for key,c in cursors.items()}
            vtx,particles,tracks=rows['vtx'],rows['particles'],rows['tracks']
            h.require(len(vtx)==len(particles)==1 and vtx[0]['n_part']==1,'Missing/duplicate initial vertex or particle')
            first=particles[0]
            h.require(first['particle']==p['pdg'] and first['vertexid']==0 and first['ekin']==0 and
                all(first[a]==0 for a in ('px','py','pz')) and vtx[0]['time']==0,'Wrong source ion/initial GPS clock')
            h.require(h.np.allclose([vtx[0][a]*1000 for a in ('xloc','yloc','zloc')],meta['source_position_global_mm'],rtol=0,atol=1e-10),'Wrong source position')
            byid=validate_tracks(tracks,names,p);values={}
            for table,material in materials.items():
                for r in rows[table]:
                    t=byid.get(r['trackid'])
                    h.require(r['edep']>=0 and r['time']>=0 and t is not None and
                        (t['particle'],t['parent_trackid'])==(r['particle'],r['parent_trackid']) and r['time']>=t['time'],
                        'Invalid material deposit/track/time link')
                    values.setdefault(material,[]).append(r['edep'])
                values.setdefault(material,[])
            steps=[]
            for r in rows['stp/germanium']:
                coords={s:[r[a+s] for a in ('xloc','yloc','zloc')] for s in ('','_pre','_post')}
                local={s:h.to_local(c,meta['coordinate_transform']).tolist() for s,c in coords.items()}
                labels={s or 'deposit':h.membership(meta['contour_rz_mm'],v) for s,v in local.items()}
                h.require('outside' not in labels.values(),'Ge row outside canonical contour')
                steps.append({'raw_row_index':r['raw_row_index'],'raw':r,'energy_keV':r['edep'],'time_ns':r['time'],
                    'track_id':r['trackid'],'parent_track_id':r['parent_trackid'],'particle_pdg':r['particle'],
                    'global_position_m':coords[''],'position_mm':local[''],'pre_position_mm':local['_pre'],
                    'post_position_mm':local['_post'],'boundary_classifications':labels})
            photons=[{'raw_row_index':t['raw_row_index'],'track_id':t['trackid'],'parent_track_id':t['parent_trackid'],
                'time_ns':t['time'],'energy_keV':t['ekin']*1000,'creation_process':names[t['procid']]} for t in tracks
                if t['particle']==22 and t['parent_trackid']!=0]
            lines={v['name']:sum(v['window_keV'][0]<=g['energy_keV']<=v['window_keV'][1] for g in photons) for v in p['diagnostic_lines']}
            yield {'global_decay_id':eid,'event_id':eid,'source_id':p['id'],'vtx':vtx,'particles':particles,'tracks':tracks,
                'steps':steps,'material_energy_keV':{m:math.fsum(v) for m,v in values.items()},'decay_photons':photons,
                'decay_photon_count':len(photons),'line_photon_counts':lines,'line_photon_count':sum(lines.values()),
                'pulse_groups':cs.group_deposits(steps,meta['grouping_policy']['horizon_ns'])}
        h.require(all(c.next is None for c in cursors.values()),'Unconsumed raw rows')
def actual_probe(path,meta):
    summary={'initial_primaries':0,'zero_ge_primaries':0,'source_descendant_photons':0,
        'line_photon_counts':{v['name']:0 for v in meta['source_contract']['diagnostic_lines']},'ge_rows':0,
        'intended_daughter_pdg_codes':[],'initial_decay_children_zero_time_verified':True,
        'nuclear_family_and_lifetime_cap_verified':True,'metastable_identity':'raw PDGs/ancestry/times retained; suffix alone is not excitation validation'}
    pdgs=set();family=meta['source_contract']['ground_daughter_pdg']//10
    for e in iter_decays(path,meta):
        summary['initial_primaries']+=1;summary['ge_rows']+=len(e['steps'])
        summary['zero_ge_primaries']+=not any(s['energy_keV']>0 for s in e['steps'])
        summary['source_descendant_photons']+=e['decay_photon_count']
        for name,value in e['line_photon_counts'].items():summary['line_photon_counts'][name]+=value
        pdgs.update(t['particle'] for t in e['tracks'] if t['particle']//10==family)
    summary['intended_daughter_pdg_codes']=sorted(pdgs)
    return summary
def run(directory):
    d,m,checked=read_prepared(directory)
    h.require({p.relative_to(d).as_posix() for p in d.rglob('*') if p.is_file()}=={*m['files_sha256'],'prepared.json','prepare-receipt.json'},'Radiation requires fresh preparation')
    command=['remage','--flat-output','-t','1','--rand-seed',str(m['seed']),'-o','truth.lh5','-g','geometry.gdml','--','run.mac']
    receipt={'status':'failed','command':command,'prepared_sha256':h.sha256(d/'prepared.json'),'versions':h.python_versions(),
        'source_id':m['source_id'],'source_contract':m['source_contract'],'data':checked['decay_data']}
    start=time.perf_counter()
    try:
        with (d/'run.log').open('x',encoding='utf-8') as log:
            for name,cmd,version in (('remage',['remage','--version'],'1.1.0'),('geant4',['geant4-config','--version'],'11.3.2')):
                result=subprocess.run(cmd,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,check=True)
                h.require(result.stdout.strip()==version,'Pinned runtime version changed')
                receipt['versions'][name]=result.stdout.strip();log.write(result.stdout)
                executable=shutil.which(cmd[0]);h.require(executable is not None,'Missing executable')
                receipt.setdefault('software_executable_sha256',{})[cmd[0]]=h.sha256(executable)
            log.flush();production=time.perf_counter()
            result=subprocess.run(command,cwd=d,stdout=log,stderr=subprocess.STDOUT,check=False)
            receipt.update(returncode=result.returncode,remage_wall_s=time.perf_counter()-production)
        h.require(result.returncode==0,'remage failed; retain run.log')
        h.require(not re.search(r'COMMAND NOT FOUND|illegal application state|command refused|parameter out of range|macro.*(failed|error)|\*\*\*\s*(Error|Fatal)|Overlap is detected',(d/'run.log').read_text(errors='replace'),re.I),'Macro/geometry failure')
        read_prepared(d);receipt['source_lh5_sha256']=h.sha256(d/'truth.lh5')
        receipt['validation']=actual_probe(d/'truth.lh5',m);receipt['status']='complete'
    except Exception as e:receipt['error']=str(e);raise
    finally:
        receipt['total_wall_s']=time.perf_counter()-start;h.publish_json(d/'run.json',receipt)
    return receipt
def extract(directory,chunk_size=100):
    import h5py
    d,m,checked=read_prepared(directory);run=cs.load(d/'run.json')
    h.require(run['status']=='complete' and run['prepared_sha256']==h.sha256(d/'prepared.json') and
        run['source_lh5_sha256']==h.sha256(d/'truth.lh5'),'Incomplete/changed original radiation')
    chunks,count=cs.write_chunks(iter_decays(d/'truth.lh5',m),d/'stream',chunk_size)
    h.require(count==m['primary_count'],'Incomplete extraction')
    with h5py.File(d/'truth.lh5','r') as raw:
        processes=list(cs.table_rows(raw['processes']));aliases=cs.step_aliases(raw,m['material_tables'])
        tables={key:{'rows':len(next(iter(raw[key].values()))),'columns':{name:{'dtype':str(ds.dtype),'units':cs.scalar(ds.attrs.get('units',''))}
            for name,ds in raw[key].items()}} for key in ('vtx','particles','tracks','processes',*m['material_tables'])}
    manifest={key:m[key] for key in ('model_id','model_sha256','model_contract','primary_count','source_id','source_contract',
        'coordinate_transform','grouping_policy','clock_policy','source_sha256','mounting_contract','placement_contract',
        'nuclear_policy','unscored_volumes','execution_contract','portable_source_sha256')}
    manifest.update(kind=KIND,producer_adapter=ADAPTER,status='complete',global_decay_id_range=[0,count-1],
        source_lh5='../truth.lh5',source_lh5_sha256=run['source_lh5_sha256'],prepared_sha256=h.sha256(d/'prepared.json'),
        run_sha256=h.sha256(d/'run.json'),decay_source_sha256=m['generic_source_sha256'],
        config_sha256=m['files_sha256']['scenario.json'],geometry_sha256=m['files_sha256']['geometry.gdml'],
        macro_sha256=m['files_sha256']['run.mac'],units={'energy':'keV','length':'mm','time':'ns'},processes=processes,
        chunks=chunks,raw_tables=tables,uid_aliases=aliases,raw_track_energy_unit='MeV',raw_position_unit='m',
        ledger={'kind':'recorded-only','full_energy_closure':None,'missing_closure':['world-air deposition','terminal escape energy',
            'neutrino escape balance','complete decay/recoil accounting'],'passive_raw_rows':'hashed truth.lh5; event material sums in JSONL'})
    h.publish_json(d/'stream/manifest.json',manifest);return manifest
def chunk_events(path):
    path=h.local_path(path);m=cs.load(path)
    h.require(m['kind']==KIND and m['producer_adapter']==ADAPTER and m['status']=='complete','Wrong/uncompleted stream')
    expected=0
    for c in m['chunks']:
        h.require(Path(c['file']).name==c['file'] and type(c['count']) is int and 1<=c['count']<=100 and
            c['first_global_decay_id']==expected,'Invalid chunk mapping')
        f=h.local_path(path.parent/c['file']);h.require(h.sha256(f)==c['sha256'],'Changed chunk')
        n=0
        for line in f.read_text().splitlines():
            e=W.decode_json(line);h.require(e['event_id']==e['global_decay_id']==expected and e['source_id']==m['source_id'],'Missing/foreign primary')
            cs.validate_group_map(e['steps'],e['pulse_groups'],m['grouping_policy']['horizon_ns'])
            expected+=1;n+=1;yield e
        h.require(n==c['count'],'Truncated chunk')
    h.require(expected==m['primary_count'] and m['global_decay_id_range']==[0,expected-1],'Incomplete primary census')
def check_stage(directory,stage):
    d,m,checked=read_prepared(directory)
    if stage in ('radiation','event_ledger'):
        r=cs.load(d/'run.json');h.require(r['status']=='complete' and r['returncode']==0 and
            r['prepared_sha256']==h.sha256(d/'prepared.json') and r['source_lh5_sha256']==h.sha256(d/'truth.lh5'),
            'Radiation receipt binding changed')
        h.require(r['source_contract']==m['source_contract'] and r['data']==checked['decay_data'],'Source radiation data binding changed')
        h.require(actual_probe(d/'truth.lh5',m)==r['validation'],'Original source census changed')
    if stage=='event_ledger':
        stream=cs.load(d/'stream/manifest.json')
        for key in ('source_id','source_contract','placement_contract','model_contract','nuclear_policy','model_id','model_sha256',
            'primary_count','coordinate_transform','clock_policy','grouping_policy','mounting_contract','source_sha256',
            'execution_contract','portable_source_sha256'):
            h.require(stream[key]==m[key],'Stream/prepared binding mismatch '+key)
        h.require(stream['decay_source_sha256']==m['generic_source_sha256'] and stream['prepared_sha256']==h.sha256(d/'prepared.json') and
            stream['run_sha256']==h.sha256(d/'run.json') and stream['source_lh5_sha256']==h.sha256(d/'truth.lh5') and
            stream['config_sha256']==h.sha256(d/'scenario.json') and stream['geometry_sha256']==h.sha256(d/'geometry.gdml') and
            stream['macro_sha256']==h.sha256(d/'run.mac'),'Stream artifact/source binding changed')
        count=0
        for a,b in itertools.zip_longest(iter_decays(d/'truth.lh5',m),chunk_events(d/'stream/manifest.json')):
            h.require(a==b,'Stream altered original LH5 row data');count+=1
        h.require(count==m['primary_count'],'Original streamed census changed')
    return checked
def main():
    global WINDOWS_ROOT
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('check');p.add_argument('--request-json');p.add_argument('--directory')
    p.add_argument('--stage',choices=('geometry','radiation','event_ledger'));p.add_argument('--windows-root',required=True)
    p=sub.add_parser('prepare');p.add_argument('--request',required=True);p.add_argument('--checked-plan',required=True)
    p.add_argument('--output',required=True);p.add_argument('--windows-root',required=True)
    for name in ('run','extract'):
        p=sub.add_parser(name);p.add_argument('--directory',required=True);p.add_argument('--windows-root',required=True)
        if name=='extract':p.add_argument('--chunk-size',type=int,default=100)
    args=parser.parse_args();WINDOWS_ROOT=args.windows_root
    if args.command=='check':
        h.require(bool(args.request_json)!=bool(args.directory),'Choose request or saved stage')
        result=check_request(W.decode_json(args.request_json)) if args.request_json else check_stage(args.directory,args.stage)
    elif args.command=='prepare':
        result=prepare(cs.load(h.local_path(args.request)),args.output,cs.load(h.local_path(args.checked_plan)))
    elif args.command=='run':result=run(args.directory)
    else:result=extract(args.directory,args.chunk_size)
    print(h.json_text(result))
if __name__=='__main__':main()
