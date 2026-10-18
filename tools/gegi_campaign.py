"""Frozen, serial GeGI chunks with durable transport/native stores and hidden resume.

Draft and freeze are data-only operations. Launch requires a matching successful
bounded acceptance receipt, exact native cache and per-pixel calibration. Native
fields are never solved here. Completed chunks are immutable scientific records.
"""
from __future__ import annotations
import argparse
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import stat
import subprocess
import sys
import time

import scenario_workflow as W
import workflow_batches as B
from local_ui_jobs import process_identity

ROOT=Path(__file__).resolve().parents[1]
KIND='gegi_campaign_plan_v1'
DONE_KIND='gegi_campaign_chunk_done_v1'
RESPONSE_KIND='gegi_campaign_chunk_response_v1'
ACCEPTANCE_KIND='gegi_campaign_acceptance_v1'
STORAGE_KIND='gegi_campaign_storage_measurement_v1'
FIXED_CHUNK_FILES=('transport/emlow-data.json','transport/decay-data.json',
    'transport/cryostat.json','transport/model-contract.json','transport/geometry.gdml',
    'transport/geometry-report.json','transport/geometry.log','transport/geometry.mac')
DEFAULT_DISK_RESERVE_BYTES=20*1024**3
MODEL_SHA='4b6c71c178c81e68bc1fe093d491b59ab99f19aed5adaba5fc61bba74d445c04'
GAMMA='gegi_mono_gamma_v1'
UNITS={GAMMA:'emitted gamma','cs137_point_decay_v1':'initial Cs137 decays',
       'co60_point_decay_v1':'initial Co60 decays'}
SOURCES=('tools/gegi_campaign.py','tools/gegi_campaign_response.py','tools/gegi_event_store.py',
         'tools/gegi_campaign_analysis.py',
         'tools/workflow_batches.py','tools/gegi_workflow.py','tools/gegi_imaging.py',
         'tools/scenario_workflow.py','tools/local_ui_jobs.py',
         'transport/gegi_source.py','transport/gegi_geometry.py','transport/cs137.py',
         'transport/decay_source.py','tools/decay_workflow.py','scenarios/source-presets.json',
         'models/GeGI_3D.yaml','models/catalog.json','scenarios/assets/gegi_cryostat_v1.json')


def require(ok,message):
    if not ok:raise ValueError(message)


def utc():return datetime.now(timezone.utc).isoformat()
def read(path):return W.read(path)
def sha(path):return W.sha(path)
def digest(value):return W.digest(value)
def write(path,value,*,fresh=False):W.write(path,value,fresh=fresh)


def no_links(path):
    path=Path(path)
    for item in (path,*path.parents):
        if item.exists():
            info=item.lstat()
            require(not stat.S_ISLNK(info.st_mode) and not getattr(info,'st_file_attributes',0)&0x400,
                    'Linked campaign path refused')


def local(path,root=ROOT):
    """No junction/reparse traversal, including for the exact archive replacements."""
    root=Path(root).resolve();path=Path(path).absolute();base=root/'.local'
    no_links(path)
    require(path.resolve().is_relative_to(base) and path.resolve()!=base,'Campaign outputs must be below project .local')
    return path.resolve()


def reference(root,ref):
    require(type(ref) is str and ref.startswith('.local/') and '\\' not in ref and
            all(p not in ('','.','..') for p in ref.split('/')),'Expected a canonical project-local evidence reference')
    return local(Path(root)/ref,root)


def bound_file(root,value,*,local_only=True):
    require(type(value) is dict and set(value)=={'ref','sha256'},'Invalid frozen artifact binding')
    path=reference(root,value['ref']) if local_only else W.safe_path(root,value['ref'])
    require(path.is_file() and sha(path)==value['sha256'],'Frozen artifact changed: '+value['ref'])
    return path


def draft():
    """Owner-requested allocation only; this function cannot authorize execution."""
    from gegi_campaign_analysis import criteria
    groups=[]
    for name,source,count,x,seed,energies in (
        ('gamma-left',GAMMA,2000000,-40.,261017101,[662.]),
        ('gamma-right',GAMMA,2000000,40.,261017102,[662.]),
        ('cs137-left','cs137_point_decay_v1',3000000,-40.,261017103,[661.657,1173.228,1332.492]),
        ('co60-right','co60_point_decay_v1',3000000,40.,261017104,[661.657,1173.228,1332.492])):
        groups.append({'id':name,'source':source,'primary_count':count,'count_unit':UNITS[source],
                       'source_position_mm':[x,0.,40.],'gamma_energy_keV':662. if source==GAMMA else None,
                       'master_seed':seed,'partition':B.partition(count,seed),
                       'photopeak_windows':[{'line_energy_keV':e,'half_width_keV':max(5.,.02*e)} for e in energies]})
    return {'kind':KIND,'schema_version':1,'status':'draft','campaign_id':'gegi-10m-v1',
            'total_initial_primaries':10000000,'cryostat':'gegi_cryostat_v1','detector':'GeGI_3D',
            'model_sha256':MODEL_SHA,'threads':1,'groups':groups,'electronics':{},
            'raw_initial_id_base':0,
            'analysis_criteria':criteria(),
            'native_request':None,'calibration':None,'transport_context':None,'pulse_group_horizon_ns':100000.,
            'resource_budget':None,
            'archive_policy':'verified_lossless_gzip_replace_v1',
            'scope':'Initial gamma and initial isotope-nucleus denominators remain separate by source group; no activity, experimental efficiency or calibrated resolution claim.'}


def validate_plan(plan,*,frozen=False):
    require(type(plan) is dict and plan.get('kind')==KIND and plan.get('schema_version')==1,'Unsupported GeGI campaign plan')
    require(plan.get('status') in ('draft','frozen') and (not frozen or plan['status']=='frozen'),'Production requires a frozen plan')
    require(type(plan.get('campaign_id')) is str and re.fullmatch(r'[A-Za-z0-9_-]{1,48}',plan['campaign_id']), 'Invalid campaign identity')
    require((plan.get('cryostat'),plan.get('detector'),plan.get('model_sha256'))==
            ('gegi_cryostat_v1','GeGI_3D',MODEL_SHA),'Campaign detector/cryostat/model changed')
    require(type(plan.get('threads')) is int and plan['threads'] in (1,2) and type(plan.get('electronics')) is dict,
            'Invalid frozen computation/electronics settings')
    require(type(plan.get('raw_initial_id_base')) is int and plan['raw_initial_id_base']==0,
            'Original remage primary IDs must retain their verified zero-based census')
    require(type(plan.get('pulse_group_horizon_ns')) in (int,float) and plan['pulse_group_horizon_ns']==100000.,
            'Campaign must retain the existing isolated 100 us grouping policy')
    require(plan.get('archive_policy')=='verified_lossless_gzip_replace_v1','Unknown raw-data retention policy')
    groups=plan.get('groups');require(type(groups) is list and 1<=len(groups)<=4,'Invalid source-group inventory')
    seen=set();seeds=set();total=0
    from gegi_imaging import photopeak_windows
    for group in groups:
        require(type(group) is dict and set(group)=={'id','source','primary_count','count_unit','source_position_mm',
                'gamma_energy_keV','master_seed','partition','photopeak_windows'},'Unknown source-group fields')
        require(type(group['id']) is str and re.fullmatch(r'[A-Za-z0-9_-]{1,32}',group['id']) and group['id'] not in seen,
                'Duplicate or unsafe source-group identity');seen.add(group['id'])
        require(group['source'] in UNITS and group['count_unit']==UNITS[group['source']], 'Source denominator/count unit changed')
        expected=B.partition(group['primary_count'],group['master_seed'])
        require(B.typed_equal(group['partition'],expected),'Chunk partition/count/seed rules changed')
        require(type(group['gamma_energy_keV']) in (int,float) and 1<=group['gamma_energy_keV']<=10000
                if group['source']==GAMMA else group['gamma_energy_keV'] is None,'Isotope decay is not a monoenergetic gamma')
        require(B.typed_equal(photopeak_windows(group['photopeak_windows']),group['photopeak_windows']), 'Invalid fixed photopeak windows')
        if group['source']!=GAMMA:
            union=[{'line_energy_keV':e,'half_width_keV':max(5.,.02*e)} for e in (661.657,1173.228,1332.492)]
            require(B.typed_equal(group['photopeak_windows'],union),
                    'All isotope groups require the same union of observed-energy windows, without source-truth selection')
        p=group['source_position_mm']
        require(type(p) is list and len(p)==3 and all(type(v) in (int,float) and abs(v)<2499 for v in p),
                'Invalid GeGI source position in mm')
        # The same exact native source screen runs before transport preparation.
        for batch in B.iter_batches(expected):
            require(batch['radiation_seed'] not in seeds,'Radiation seed collision across source groups')
            seeds.add(batch['radiation_seed'])
        total+=group['primary_count']
    require(type(plan.get('total_initial_primaries')) is int and total==plan['total_initial_primaries'] and 1<=total<=10000000,
            'Source-group counts must sum to the frozen initial-primary denominator, at most the authorized 10M')
    if frozen:
        from gegi_campaign_analysis import criteria
        require(B.typed_equal(plan.get('analysis_criteria'),criteria()),'Frozen analysis criteria differ from the maintained implementation')
        require(type(plan.get('source_sha256')) is dict and set(SOURCES)<=set(plan['source_sha256']), 'Frozen campaign source inventory missing')
        require(type(plan.get('transport_context')) is dict and set(plan['transport_context'])=={'runtime','decay_data','emlow_sha256'},
                'Frozen transport runtime/nuclear-data context missing')
        require(plan.get('physics_sha256')==physics_sha256(plan) and type(plan.get('acceptance')) is dict,
                'Frozen physics/acceptance binding changed')
        budget=plan.get('resource_budget')
        require(type(budget) is dict and set(budget) in (
                {'projected_retained_bytes','max_chunk_temporary_bytes','reserve_bytes','evidence'},
                {'projected_retained_bytes','max_chunk_temporary_bytes','reserve_bytes','evidence','storage_measurement'})
                and all(type(budget.get(k)) is int and budget[k]>=0 for k in
                        ('projected_retained_bytes','max_chunk_temporary_bytes','reserve_bytes')),
                'Frozen measured disk resource budget missing')
    return plan


def physics_sha256(plan):
    return digest({key:plan[key] for key in ('cryostat','detector','model_sha256','electronics','native_request',
                   'calibration','pulse_group_horizon_ns','archive_policy','raw_initial_id_base','analysis_criteria')} | {
        'groups':[{key:g[key] for key in ('id','source','count_unit','source_position_mm','gamma_energy_keV','photopeak_windows')}
                  for g in plan['groups']]})


def chunks(plan):
    offset=0;index=0
    for group in plan['groups']:
        for batch in B.iter_batches(group['partition']):
            yield {'source_group':group['id'],'chunk_index':index,'batch':batch,
                   'campaign_initial_offset':offset+batch['global_initial_offset']}
            index+=1
        offset+=group['primary_count']


def chunk_path(directory,chunk):
    return Path(directory)/'chunks'/chunk['source_group']/('b%06d'%chunk['batch']['batch_index'])


def source_pins(root):
    return {ref:sha(Path(root)/ref) for ref in SOURCES}


def verify_inputs(plan,root=ROOT):
    require(sha(Path(root)/'models/GeGI_3D.yaml')==MODEL_SHA,'Frozen canonical GeGI bytes changed')
    for ref,value in plan['source_sha256'].items():
        require(type(ref) is str and '\\' not in ref and not Path(ref).is_absolute() and '..' not in Path(ref).parts,
                'Unsafe frozen source reference')
        require(sha(Path(root)/ref)==value,'Frozen source changed: '+ref)
    request=read(bound_file(root,plan['native_request']))
    require(request.get('kind')=='gegi_campaign_response_request_v1' and request.get('model_sha256')==MODEL_SHA,
            'Wrong frozen native request')
    cache=request.get('field_cache');require(type(cache) is dict and cache.get('model_sha256')==MODEL_SHA,
                                            'Production requires the exact existing native field cache')
    bound_file(root,{key:cache[key] for key in ('ref','sha256')},local_only=False)
    require(request.get('pulse_group_horizon_ns')==plan['pulse_group_horizon_ns'], 'Native pulse grouping differs from frozen transport grouping')
    require(request.get('numerics',{}).get('field_policy')=='reuse-only', 'A fresh native field solve is prohibited')
    require(all(plan['source_sha256'].get(ref)==value for ref,value in request['source_sha256'].items()),
            'Native request source pins differ from the campaign')
    calibration=read(bound_file(root,plan['calibration']))
    require(calibration.get('per_pixel_calibration') is True and calibration.get('kind')=='gegi_pixel_simulated_depth_v1',
            'Production requires the pinned per-pixel simulated depth calibration')
    return request


def verify_acceptance(plan,root=ROOT):
    if 'recovery' in plan:
        import gegi_campaign_recovery as R
        plan=R.original_plan(plan,root)
    value=read(bound_file(root,plan['acceptance']))
    return verify_acceptance_value(plan,value,root)


def verify_acceptance_value(plan,value,root=ROOT):
    require(value.get('kind')==ACCEPTANCE_KIND and value.get('status')=='passed' and
            value.get('physics_sha256')==plan['physics_sha256'],'Missing successful matching bounded acceptance')
    records=value.get('groups');require(type(records) is list and {r.get('source_group') for r in records}=={g['id'] for g in plan['groups']}
                                      and len(records)==len(plan['groups']),'Acceptance must cover every frozen source group')
    for record in records:
        require(type(record.get('initial_primaries')) is int and 1<=record['initial_primaries']<=500,'Acceptance is not bounded')
        transport_path=bound_file(root,record['transport_receipt']);transport=read(transport_path)
        response=read(bound_file(root,record['response_receipt']))
        require(transport.get('kind')=='gegi_transport_run_v1' and transport.get('status')=='complete' and
                response.get('kind')==RESPONSE_KIND and response.get('status')=='completed','Pilot transport/response did not complete cleanly')
        for receipt in (transport,response):
            count=receipt['counts']
            require(count['initial_primaries']==record['initial_primaries'] and
                    count['zero_deposit_primaries']+count['nonzero_primaries']==count['initial_primaries'],
                    'Pilot denominator census changed')
        require(response['counts'].get('pulse_groups',0)>0 and response['counts'].get('native_failed_groups')==0,
                'Pilot has no successful native pulse-group acceptance')
        require(response.get('native_request_sha256')==plan['native_request']['sha256'] and
                response.get('new_field_solve') is False,'Pilot must use the frozen reuse-only native request')
        require(response.get('electronics_replay',{}).get('status')=='verified_exact' and
                response['electronics_replay'].get('drift_executed') is False,
                'Pilot lacks an exact saved-native electronics replay')
        verify_pilot_store(bound_file(root,record['store']),response,plan)
        timing=read(bound_file(root,record['timings']))
        require(all(type(timing.get(name)) in (int,float) and 0<=timing[name]<float('inf')
                    for name in ('transport_driver_wall_s','native_response_and_store_wall_s')),
                'Pilot measured stage timings are missing')
        actual_storage=pilot_storage_bytes(transport_path.parent.parent)
        require(all(record.get(k)==v for k,v in actual_storage.items()),'Pilot measured storage bytes changed')
        require(response.get('calibration_sha256')==plan['calibration']['sha256'], 'Pilot used a different per-pixel calibration')
        group=next(g for g in plan['groups'] if g['id']==record['source_group'])
        manifest_path=transport_path.parent/'stream/manifest.json';manifest=read(manifest_path)
        source=manifest['source_contract']
        require(response.get('input_manifest_sha256')==sha(manifest_path) and manifest['model_sha256']==MODEL_SHA
                and manifest['source_id']==group['source'] and source['position_global_mm']==group['source_position_mm']
                and manifest['source_count_unit']==group['count_unit']
                and (source['energy_keV']==group['gamma_energy_keV'] if group['source']==GAMMA else 'energy_keV' not in source)
                and response.get('photopeak_windows_sha256')==digest(group['photopeak_windows']),
                'Pilot source geometry, denominator or reconstruction window differs from the frozen group')
    require(B.typed_equal(plan['transport_context'],accepted_transport_context(value,root)),
            'Frozen transport runtime/nuclear data differ from the accepted pilots')
    return value


def verify_pilot_store(path,response,plan):
    """Verify completed scalar/native pilot artifacts without dispatching physics."""
    from gegi_event_store import Store
    with closing(sqlite3.connect(Path(path).as_uri()+'?mode=ro',uri=True)) as db:
        row=db.execute('SELECT body FROM identity WHERE singleton=1').fetchone()
        require(row is not None,'Pilot Store identity missing')
        identity_value=json.loads(row[0])['identity']
    require(identity_value.get('physics_sha256')==plan['physics_sha256'] and
            identity_value.get('native_request_sha256')==plan['native_request']['sha256'] and
            identity_value.get('raw_initial_id_base')==0 and
            digest(identity_value)==response['store_identity_sha256'],'Pilot Store physics/request identity differs')
    store=Store(path,identity_value)
    try:
        require(store.db.execute('PRAGMA integrity_check').fetchone()[0]=='ok','Pilot Store integrity failed')
        completion=store.db.execute('SELECT body FROM completion WHERE singleton=1').fetchone()
        require(completion is not None and json.loads(completion[0])==response,'Pilot Store is not sealed with its response')
        count=0
        for key in store.keys():store.read(*key,with_signals=True);count+=1
        require(count==response['counts']['pulse_groups'],'Pilot Store pulse-group census differs')
    finally:store.close()


def pilot_spec(plan,source_group,initial_primaries,seed):
    """Data-only bounded driver inputs; caller explicitly starts each actual stage."""
    validate_plan(plan)
    require(type(initial_primaries) is int and 1<=initial_primaries<=500,'Pilot count must be 1–500')
    group=next((g for g in plan['groups'] if g['id']==source_group),None)
    require(group is not None,'Unknown pilot source group')
    batch=B.batch_at(B.partition(initial_primaries,seed),0)
    chunk={'source_group':source_group,'chunk_index':0,'batch':batch,'campaign_initial_offset':0}
    selection=selection_for(plan,chunk);selection['name']='pilot-'+source_group+'-'+str(seed)
    identity_value={'physics_sha256':physics_sha256(plan),'raw_initial_id_base':0,**chunk,
                    'native_request_sha256':plan['native_request']['sha256'],
                    'calibration_sha256':plan['calibration']['sha256'],
                    'photopeak_windows_sha256':digest(group['photopeak_windows']),'model_sha256':MODEL_SHA}
    return {'selection':selection,'store_identity':identity_value,'photopeak_windows':group['photopeak_windows']}


def build_acceptance(plan,pilots,output,*,root=ROOT):
    """Derive acceptance from real completed artifacts, never an asserted pass flag.

    pilots is a list of source_group, folder and timings refs below .local;
    each folder contains transport/, response.json and events.sqlite.
    """
    output=local(output,root);require(not output.exists(),'Acceptance output exists; preserve it')
    plan=json.loads(W.encoded(validate_plan(plan)))
    request=read(bound_file(root,plan['native_request']))
    plan['source_sha256']={**request['source_sha256'],**source_pins(root)}
    plan['physics_sha256']=physics_sha256(plan);verify_inputs(plan,root)
    require(type(pilots) is list,'Pilot artifact inventory must be a list')
    records=[]
    for spec in pilots:
        require(type(spec) is dict and set(spec)=={'source_group','folder','timings'},'Unsupported pilot artifact fields')
        folder=reference(root,spec['folder']);transport_path=folder/'transport/run.json'
        prepared=read(folder/'transport/prepared.json')
        verify_transport_binding(folder,prepared['selection'])
        def binding(path):return {'ref':Path(path).relative_to(root).as_posix(),'sha256':sha(path)}
        response=read(folder/'response.json');counts=read(transport_path)['counts']
        records.append({'source_group':spec['source_group'],'initial_primaries':counts['initial_primaries'],
            'transport_receipt':binding(transport_path),'response_receipt':binding(folder/'response.json'),
            'store':binding(folder/'events.sqlite'),'timings':binding(reference(root,spec['timings'])),
            'transport_counts':counts,'response_counts':response['counts'],
            **pilot_storage_bytes(folder)})
    value={'kind':ACCEPTANCE_KIND,'status':'passed','physics_sha256':plan['physics_sha256'],
           'groups':records,'generated_utc':utc(),
           'scope':'Derived from hash-checked completed bounded transport, sealed native Store, exact electronics replay and measured stage timings. Imaging counts do not gate launch.'}
    plan['transport_context']=accepted_transport_context(value,root)
    verify_acceptance_value(plan,value,root)
    write(output,value,fresh=True)
    return value


def pilot_storage_bytes(folder):
    folder=Path(folder)
    return {'raw_transport_bytes':(folder/'transport/truth.lh5').stat().st_size,
            'sparse_stream_bytes':(folder/'transport/stream/events.jsonl').stat().st_size,
            'native_store_bytes':(folder/'events.sqlite').stat().st_size,
            'retained_artifact_bytes':sum(v['bytes'] for v in file_inventory(folder).values())}


def measure_storage(plan,acceptance,output,*,root=ROOT):
    """Lossless gzip measurements in a new derivative; pilot originals stay intact."""
    output=local(output,root);require(not output.exists(),'Storage measurement output exists; preserve it')
    accepted=read(bound_file(root,acceptance))
    storage_projection(plan,accepted)  # Require the same accepted physics/source census.
    records=[];output.mkdir(parents=True)
    for pilot in accepted['groups']:
        folder=bound_file(root,pilot['transport_receipt']).parent.parent
        inventory=file_inventory(folder)
        require(sum(v['bytes'] for v in inventory.values())==pilot['retained_artifact_bytes'],
                'Accepted pilot storage inventory changed')
        require(inventory['events.sqlite']['sha256']==pilot['store']['sha256'], 'Accepted native Store changed')
        transport=read(folder/'transport/run.json');manifest=read(folder/'transport/stream/manifest.json')
        originals={'transport/truth.lh5':transport['source_lh5_sha256'],
                   'transport/stream/events.jsonl':manifest['events_sha256']}
        archives={}
        for ref,expected in originals.items():
            source=folder/ref;record=inventory[ref]
            require(record['sha256']==expected,'Accepted raw transport/stream changed')
            target=output/pilot['source_group']/(Path(ref).name+'.gz');target.parent.mkdir(exist_ok=True)
            with target.open('xb') as stream:
                with gzip.GzipFile(filename='',fileobj=stream,mode='wb',compresslevel=4,mtime=0) as packed:
                    with source.open('rb') as raw:shutil.copyfileobj(raw,packed,1024*1024)
                stream.flush();os.fsync(stream.fileno())
            verify_archive(target,expected,record['bytes'])
            require(sha(source)==expected and source.stat().st_size==record['bytes'],'Pilot changed during measurement')
            archives[ref]={'original':{'ref':source.relative_to(root).as_posix(),'sha256':expected,'bytes':record['bytes']},
                           'archive':{'ref':target.relative_to(root).as_posix(),'sha256':sha(target),'bytes':target.stat().st_size}}
        fixed={ref:inventory[ref] for ref in FIXED_CHUNK_FILES if ref in inventory}
        fixed_bytes=sum(v['bytes'] for v in fixed.values())
        other_bytes=sum(v['bytes'] for ref,v in inventory.items() if ref not in originals and ref not in fixed and ref!='events.sqlite')
        # DONE adds a response copy, artifact hashes and the frozen identity. Bound
        # this metadata from actual serialized inputs, with a 2x envelope plus 4 KiB.
        group=next(g for g in plan['groups'] if g['id']==pilot['source_group'])
        seal_allowance=2*(inventory['response.json']['bytes']+len(W.encoded(inventory))+
                          len(W.encoded(source_pins(root)))+len(W.encoded(group))+4096)
        records.append({'source_group':pilot['source_group'],'initial_primaries':pilot['initial_primaries'],
            'pilot_folder':folder.relative_to(root).as_posix(),'pilot_inventory':inventory,'archives':archives,
            'fixed_chunk_files':fixed,'fixed_chunk_bytes':fixed_bytes,'other_variable_bytes':other_bytes,
            'native_store_bytes':inventory['events.sqlite']['bytes'],'chunk_seal_allowance_bytes':seal_allowance})
        require(file_inventory(folder)==inventory,'Pilot artifacts changed during storage measurement')
    result={'kind':STORAGE_KIND,'status':'complete','physics_sha256':physics_sha256(plan),'acceptance':acceptance,
        'compression':{'format':'gzip','level':4,'mtime':0,'roundtrip_sha256_verified':True},'groups':records,
        'fixed_chunk_file_policy':list(FIXED_CHUNK_FILES),
        'scope':'Measured compressed truth/stream and complete native Store scale by initial count. Only declared geometry/material/data files scale by chunk count; all other pilot bytes remain conservatively event-scaled. Native Store page overhead is not subtracted.',
        'uncertainty':'Four bounded pilot samples; projection is not a measured production peak. A separately chosen multiplier, double temporary overlap and disk reserve still apply.'}
    write(output/'measurement.json',result,fresh=True)
    return result


def verify_storage_measurement(plan,acceptance,binding,*,root=ROOT):
    evidence=read(bound_file(root,binding));accepted=read(bound_file(root,acceptance))
    require(evidence.get('kind')==STORAGE_KIND and evidence.get('status')=='complete' and
            evidence.get('acceptance')==acceptance and evidence.get('physics_sha256')==physics_sha256(plan) and
            evidence.get('compression')=={'format':'gzip','level':4,'mtime':0,'roundtrip_sha256_verified':True} and
            evidence.get('fixed_chunk_file_policy')==list(FIXED_CHUNK_FILES),'Storage measurement binding differs')
    pilots={p['source_group']:p for p in accepted['groups']}
    require(len(evidence['groups'])==len(pilots) and {g['source_group'] for g in evidence['groups']}==set(pilots),
            'Storage measurement source census differs')
    for record in evidence['groups']:
        pilot=pilots[record['source_group']];folder=reference(root,record['pilot_folder']);inventory=file_inventory(folder)
        require(folder==bound_file(root,pilot['transport_receipt']).parent.parent and inventory==record['pilot_inventory'] and
                record['initial_primaries']==pilot['initial_primaries'] and sum(v['bytes'] for v in inventory.values())==pilot['retained_artifact_bytes'],
                'Measured pilot inputs changed')
        fixed={ref:inventory[ref] for ref in FIXED_CHUNK_FILES if ref in inventory}
        require(record['fixed_chunk_files']==fixed and record['fixed_chunk_bytes']==sum(v['bytes'] for v in fixed.values()) and
                record['native_store_bytes']==inventory['events.sqlite']['bytes'],'Measured fixed/native byte census changed')
        require(set(record['archives'])=={'transport/truth.lh5','transport/stream/events.jsonl'},'Measured archive inventory differs')
        for ref,archive_record in record['archives'].items():
            original=archive_record['original'];packed=archive_record['archive']
            require(original=={'ref':(folder/ref).relative_to(root).as_posix(),**inventory[ref]},'Measured original binding changed')
            path=bound_file(root,{k:packed[k] for k in ('ref','sha256')})
            require(path.stat().st_size==packed['bytes'],'Measured archive size changed')
            verify_archive(path,original['sha256'],original['bytes'])
        variable=sum(v['bytes'] for ref,v in inventory.items() if ref not in fixed and ref not in record['archives'] and ref!='events.sqlite')
        require(record['other_variable_bytes']==variable and type(record['chunk_seal_allowance_bytes']) is int and
                record['chunk_seal_allowance_bytes']>=2*(inventory['response.json']['bytes']+len(W.encoded(inventory))+
                len(W.encoded(source_pins(root)))+len(W.encoded(next(g for g in plan['groups'] if g['id']==record['source_group'])))+4096),
                'Measured variable/seal metadata allowance changed')
    return evidence


def storage_projection(plan,evidence,measurement=None):
    """Measured pilot bytes scaled by initial count, retaining source differences."""
    require(evidence.get('kind')==ACCEPTANCE_KIND and evidence.get('status')=='passed' and
            evidence.get('physics_sha256')==physics_sha256(plan),'Disk evidence does not match accepted pilot physics')
    records={r['source_group']:r for r in evidence['groups']}
    require(set(records)=={g['id'] for g in plan['groups']},'Disk evidence source inventory differs')
    measured={r['source_group']:r for r in measurement['groups']} if measurement is not None else None
    if measured is not None:
        require(measurement.get('kind')==STORAGE_KIND and measurement.get('physics_sha256')==physics_sha256(plan) and
                set(measured)==set(records),'Compressed storage evidence differs')
    groups={};temporary=0
    for group in plan['groups']:
        record=records[group['id']];n=record['initial_primaries']
        require(type(n) is int and 1<=n<=500 and all(type(record.get(k)) is int and record[k]>0
                for k in ('raw_transport_bytes','sparse_stream_bytes','native_store_bytes','retained_artifact_bytes')),
                'Actual pilot raw/stream/Store storage measurements are missing')
        current_bytes=sum(record[k] for k in ('raw_transport_bytes','sparse_stream_bytes','native_store_bytes'))
        chunk_count=min(B.BATCH_CAP,group['primary_count'])
        if measured is None:
            groups[group['id']]=(record['retained_artifact_bytes']*group['primary_count']+n-1)//n
            temporary=max(temporary,(current_bytes*chunk_count+n-1)//n)
        else:
            sample=measured[group['id']]
            require(sample['initial_primaries']==n,'Compressed pilot denominator changed')
            payload=sum(v['archive']['bytes'] for v in sample['archives'].values())+sample['native_store_bytes']+sample['other_variable_bytes']
            fixed=sample['fixed_chunk_bytes']+sample['chunk_seal_allowance_bytes']
            chunks_count=(group['primary_count']+B.BATCH_CAP-1)//B.BATCH_CAP
            groups[group['id']]=(payload*group['primary_count']+n-1)//n+fixed*chunks_count
            temporary=max(temporary,((current_bytes+sample['other_variable_bytes'])*chunk_count+n-1)//n+fixed)
    return groups,temporary


def budget_from_acceptance(plan,acceptance,*,multiplier,reserve_bytes=DEFAULT_DISK_RESERVE_BYTES,storage_measurement=None,root=ROOT):
    """Data-only estimate; caller chooses the conservative multiplier after pilots.

    Temporary projection doubles scaled raw+stream+Store bytes for an archive /
    transaction overlap. This is an estimate from measured data, not a peak claim.
    """
    require(type(multiplier) in (int,float) and math.isfinite(multiplier) and multiplier>=1,
            'Choose a finite conservative disk multiplier of at least one')
    require(type(reserve_bytes) is int and reserve_bytes>=0,'Invalid disk reserve bytes')
    measurement=verify_storage_measurement(plan,acceptance,storage_measurement,root=root) if storage_measurement is not None else None
    groups,temporary=storage_projection(plan,read(bound_file(root,acceptance)),measurement)
    result={'projected_retained_bytes':math.ceil(sum(groups.values())*multiplier),
            'max_chunk_temporary_bytes':math.ceil(2*temporary*multiplier),
            'reserve_bytes':reserve_bytes,'evidence':acceptance}
    if storage_measurement is not None:result['storage_measurement']=storage_measurement
    return result


def verify_resource_budget(plan,root=ROOT):
    if 'recovery' in plan:
        import gegi_campaign_recovery as R
        plan=R.original_plan(plan,root)
    budget=plan['resource_budget']
    require(budget['evidence']==plan['acceptance'],'Disk budget must bind the actual accepted pilot measurements')
    measurement=verify_storage_measurement(plan,budget['evidence'],budget['storage_measurement'],root=root) if 'storage_measurement' in budget else None
    groups,temporary=storage_projection(plan,read(bound_file(root,budget['evidence'])),measurement)
    require(budget['projected_retained_bytes']>=sum(groups.values()) and
            budget['max_chunk_temporary_bytes']>=temporary,'Frozen disk budget is below measured pilot scaling')
    return groups


def available_disk_bytes(path):
    path=Path(path)
    while not path.exists():path=path.parent
    return shutil.disk_usage(path).free


def required_launch_disk_bytes(plan,totals,*,root=ROOT):
    if 'recovery' in plan:
        import gegi_campaign_recovery as R
        plan=R.original_plan(plan,root)
    budget=plan['resource_budget']
    measurement=read(reference(root,budget['storage_measurement']['ref'])) if 'storage_measurement' in budget else None
    baseline,_=storage_projection(plan,read(reference(root,budget['evidence']['ref'])),measurement)
    remaining=0
    for group in plan['groups']:
        n=group['primary_count'];done=totals.get(group['id'],{}).get('initial_primaries',0)
        require(type(done) is int and 0<=done<=n,'Invalid completed count in disk projection')
        if measurement is None:
            remaining+=(baseline[group['id']]*(n-done)+n-1)//n
        else:
            sample=next(r for r in measurement['groups'] if r['source_group']==group['id'])
            payload=sum(v['archive']['bytes'] for v in sample['archives'].values())+sample['native_store_bytes']+sample['other_variable_bytes']
            fixed=sample['fixed_chunk_bytes']+sample['chunk_seal_allowance_bytes'];sample_n=sample['initial_primaries']
            remaining+=(payload*(n-done)+sample_n-1)//sample_n+fixed*((n-done+B.BATCH_CAP-1)//B.BATCH_CAP)
    base=sum(baseline.values())
    projected=(budget['projected_retained_bytes']*remaining+base-1)//base
    return projected+budget['max_chunk_temporary_bytes']+budget['reserve_bytes']


def require_launch_disk(directory,plan,totals,*,root=ROOT):
    needed=required_launch_disk_bytes(plan,totals,root=root);free=available_disk_bytes(directory)
    require(free>=needed,'Insufficient free disk for remaining campaign: free=%d required=%d bytes'%(free,needed))
    return needed


def accepted_transport_context(acceptance,root):
    runtime=None;data={};emlow=None
    for record in acceptance['groups']:
        transport_path=bound_file(root,record['transport_receipt'])
        receipt=read(transport_path);prepared_path=transport_path.parent/'prepared.json';prepared=read(prepared_path)
        checked_path=transport_path.parent/'checked-plan.json'
        require(receipt['prepared_sha256']==sha(prepared_path) and
                prepared['files_sha256']['checked-plan.json']==sha(checked_path), 'Accepted transport runtime evidence changed')
        checked=read(checked_path);source=checked['selection']['source']
        require(source==read(transport_path.parent/'stream/manifest.json')['source_id'], 'Accepted runtime/source binding differs')
        emlow_path=transport_path.parent/'emlow-data.json'
        require(prepared['files_sha256']['emlow-data.json']==sha(emlow_path),'Accepted EMLOW evidence changed')
        actual_emlow=emlow_digest(read(emlow_path))
        if emlow is None:emlow=actual_emlow
        require(emlow==actual_emlow,'Pilot EMLOW datasets differ')
        if runtime is None:runtime=checked['runtime']
        require(B.typed_equal(runtime,checked['runtime']),'Pilot transport runtime identities differ')
        if source in data:require(B.typed_equal(data[source],checked.get('decay_data')),'Pilot nuclear datasets differ for one source')
        data[source]=checked.get('decay_data')
    return {'runtime':runtime,'decay_data':data,'emlow_sha256':emlow}


def emlow_digest(value):
    return digest({key:item for key,item in value.items() if key!='hash_wall_s'})


def freeze(directory,plan,acceptance,*,root=ROOT):
    """Record the concrete tested configuration; never manufacture acceptance."""
    directory=local(directory,root);require(not directory.exists(),'Campaign output exists; preserve it')
    plan=json.loads(W.encoded(validate_plan(plan)));plan['status']='frozen';plan['acceptance']=acceptance
    request=read(bound_file(root,plan['native_request']))
    plan['source_sha256']={**request['source_sha256'],**source_pins(root)}
    plan['transport_context']=accepted_transport_context(read(bound_file(root,acceptance)),root)
    plan['physics_sha256']=physics_sha256(plan);validate_plan(plan,frozen=True)
    verify_inputs(plan,root);verify_acceptance(plan,root);verify_resource_budget(plan,root)
    require_launch_disk(directory,plan,{},root=root)
    directory.mkdir(parents=True);write(directory/'plan.json',plan,fresh=True)
    write(directory/'FROZEN.json',{'kind':KIND,'plan_sha256':sha(directory/'plan.json'),
                                 'physics_sha256':plan['physics_sha256'],'frozen_utc':utc()},fresh=True)
    progress(directory,plan,'prepared',{},None)
    return plan


def read_plan(directory,*,root=ROOT,verify=True):
    directory=local(directory,root);plan=validate_plan(read(directory/'plan.json'),frozen=True)
    seal=read(directory/'FROZEN.json')
    require(seal['kind']==KIND and seal['plan_sha256']==sha(directory/'plan.json') and
            seal['physics_sha256']==plan['physics_sha256'],'Frozen plan bytes changed')
    if verify:verify_inputs(plan,root);verify_acceptance(plan,root);verify_resource_budget(plan,root)
    return plan


def identity(pid):
    if os.name=='nt':return process_identity(pid)
    try:
        data=Path('/proc/%d/stat'%pid).read_text();boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        return boot+':'+data[data.rindex(')')+2:].split()[19]
    except FileNotFoundError:return None
    except (OSError,ValueError):return 'unknown'


def inactive_children(directory,*,reader=identity,root=ROOT):
    """A dead supervisor does not prove its native/WSL children have exited."""
    directory=Path(directory);records=[directory/'native-spool/worker-process.json']
    if (directory/'plan.json').exists():
        plan=read(directory/'plan.json')
        if 'recovery' in plan:
            import gegi_campaign_recovery as R
            records.extend(path/'worker-process.json' for path in R.spool_paths(directory,plan,root))
    progress_path=directory/'progress.json'
    if progress_path.exists():
        current=read(progress_path).get('current_chunk')
        if current:records.append(chunk_path(directory,current)/'active-transport.json')
    for path in records:
        if not path.exists():continue
        value=read(path)
        if value.get('status') in ('completed','failed') and value.get('returncode') is not None:continue
        require(value.get('status')!='launching' and type(value.get('pid')) is int
                and type(value.get('process_start_identity')) is str,'An interrupted child launch is unverified; inspect its process ownership')
        actual=reader(value['pid'])
        require(actual not in ('unknown',value['process_start_identity']), 'A prior native/transport child is live or its identity is unknown')


def release_owned_lock(path,owner,*,attempts=5):
    """Retry exact owned cleanup; never leave an anonymous empty lock on failure."""
    path=Path(path);owner_path=path/'owner.json';last=None
    for attempt in range(attempts):
        no_links(path);no_links(owner_path)
        require(path.is_dir() and {p.name for p in path.iterdir()}=={'owner.json'} and read(owner_path)==owner,
                'Lock ownership changed before cleanup')
        try:
            # Windows can mark an ordinary owned directory read-only. Clear only
            # that attribute on this exact lock and owner, never global permissions.
            if os.name=='nt':
                for item in (path,owner_path):
                    info=item.stat()
                    if getattr(info,'st_file_attributes',0)&stat.FILE_ATTRIBUTE_READONLY:
                        item.chmod(info.st_mode|stat.S_IWRITE)
            owner_path.unlink();path.rmdir();return
        except OSError as error:
            last=error
            if path.exists() and not owner_path.exists():
                with owner_path.open('xb') as out:
                    out.write(W.encoded(owner)+b'\n');out.flush();os.fsync(out.fileno())
            if attempt+1<attempts:time.sleep(.05*(attempt+1))
    write(path.parent/(path.name+'.cleanup-failure.json'),{'owner':owner,'error':str(last),'recorded_utc':utc()})
    raise last


@contextmanager
def locked(directory,*,resume=False,reader=identity,name='.worker.lock'):
    path=Path(directory)/name;token=secrets.token_hex(16)
    no_links(path);no_links(path/'owner.json')
    if path.exists():
        require(path.is_dir() and {p.name for p in path.iterdir()}=={'owner.json'},'Unrecognized campaign lock; inspect ownership')
        old=read(path/'owner.json');actual=reader(old['pid'])
        require(actual not in ('unknown',old['process_start_identity']),'Campaign worker is already live or its identity is unknown')
        require(resume,'Dead campaign owner preserved; explicit resume is required')
        write(Path(directory)/'recovered-lock.json',{'prior_owner':old,'observed_identity':actual,'recovered_utc':utc()})
        release_owned_lock(path,old)
    path.mkdir();owner={'pid':os.getpid(),'process_start_identity':reader(os.getpid()),'token':token,'created_utc':utc()}
    require(owner['process_start_identity'] not in (None,'unknown'),'Cannot establish worker process creation identity')
    write(path/'owner.json',owner,fresh=True)
    failed=False
    try:yield owner
    except BaseException:
        failed=True
        raise
    finally:
        if path.exists() and read(path/'owner.json').get('token')==token:
            try:release_owned_lock(path,owner)
            except OSError:
                if not failed:raise


def progress(directory,plan,status,totals,current,*,error=None):
    groups={g['id']:{'target_initial_primaries':g['primary_count'],'count_unit':g['count_unit'],
                     **totals.get(g['id'],{})} for g in plan['groups']}
    complete=sum(g.get('initial_primaries',0) for g in groups.values())
    value={'kind':KIND,'status':status,'updated_utc':utc(),'pid':os.getpid(),
           'verified_initial_primaries':complete,'target_initial_primaries':plan['total_initial_primaries'],
           'percent':100*complete/plan['total_initial_primaries'],'groups':groups,'current_chunk':current,'error':error}
    budget=plan['resource_budget']
    value['disk_free_bytes']=available_disk_bytes(directory)
    value['disk_required_before_new_chunk_bytes']=budget['max_chunk_temporary_bytes']+budget['reserve_bytes']
    write(Path(directory)/'progress.json',value);return value


def status(directory,*,root=ROOT,reader=identity):
    """Fast monitor: no native import, directory census, archive or DB hashing."""
    directory=local(directory,root);path=directory/'progress.json'
    require(path.stat().st_size<1048576,'Progress is not compact')
    value=read(path);lock=directory/'.worker.lock/owner.json'
    owner=read(lock) if lock.is_file() else None
    actual=reader(owner['pid']) if owner else None
    value['worker_live']=bool(owner and actual==owner['process_start_identity'])
    value['worker_identity_unknown']=actual=='unknown'
    value['stop_requested']=(directory/'STOP.json').exists()
    value['disk_free_bytes']=available_disk_bytes(directory)
    return value


def stop(directory,*,root=ROOT):
    directory=local(directory,root);plan=read_plan(directory,root=root,verify=False)
    marker=directory/'STOP.json'
    if not marker.exists():write(marker,{'plan_sha256':sha(directory/'plan.json'),'requested_utc':utc()},fresh=True)
    return {'status':'stop_requested','boundary':'completed chunk; current native/transport work is retained'}


def verify_archive(path,expected_sha256,expected_bytes):
    hasher=hashlib.sha256();size=0
    with gzip.open(path,'rb') as stream:
        for data in iter(lambda:stream.read(1024*1024),b''):hasher.update(data);size+=len(data)
    require(size==expected_bytes and hasher.hexdigest()==expected_sha256,'Lossless archive content changed')


def archive(path):
    path=Path(path);target=path.with_name(path.name+'.gz');expected=sha(path);size=path.stat().st_size
    if not target.exists():
        temporary=target.with_name(target.name+'.partial-'+secrets.token_hex(8))
        with temporary.open('xb') as output:
            with gzip.GzipFile(filename='',fileobj=output,mode='wb',compresslevel=4,mtime=0) as zipped:
                with path.open('rb') as source:shutil.copyfileobj(source,zipped,1024*1024)
            output.flush();os.fsync(output.fileno())
        verify_archive(temporary,expected,size);os.link(temporary,target);temporary.unlink()
    verify_archive(target,expected,size)
    return {'file':target.name,'sha256':sha(target),'bytes':target.stat().st_size,
            'original_sha256':expected,'original_bytes':size}


def file_inventory(directory,excluded=()):
    result={}
    pending=[Path(directory)]
    while pending:
        folder=pending.pop();no_links(folder)
        for entry in sorted(os.scandir(folder),key=lambda row:row.name):
            info=entry.stat(follow_symlinks=False)
            require(not stat.S_ISLNK(info.st_mode) and not getattr(info,'st_file_attributes',0)&0x400,
                    'Linked chunk artifact refused without traversal')
            path=Path(entry.path)
            if stat.S_ISDIR(info.st_mode):pending.append(path)
            elif stat.S_ISREG(info.st_mode):
                ref=path.relative_to(directory).as_posix()
                if ref not in excluded:result[ref]={'sha256':sha(path),'bytes':info.st_size}
            else:raise ValueError('Unexpected chunk artifact type')
    return result


def chunk_identity(directory,plan,chunk,*,root=ROOT):
    plan_sha=sha(Path(directory)/'plan.json')
    if 'recovery' in plan:
        import gegi_campaign_recovery as R
        plan,plan_sha=R.chunk_origin(directory,plan,chunk,root=root)
    group=next(g for g in plan['groups'] if g['id']==chunk['source_group'])
    return {'campaign_plan_sha256':plan_sha,'physics_sha256':plan['physics_sha256'],
            'raw_initial_id_base':plan['raw_initial_id_base'],
            **chunk,'native_request_sha256':plan['native_request']['sha256'],
            'calibration_sha256':plan['calibration']['sha256'], 'photopeak_windows_sha256':digest(group['photopeak_windows']),
            'model_sha256':MODEL_SHA,'source_sha256':plan['source_sha256']}


def selection_for(plan,chunk):
    group=next(g for g in plan['groups'] if g['id']==chunk['source_group'])
    return {'name':'gc-'+digest(chunk)[:20],'cryostat':plan['cryostat'],'detector':plan['detector'],
            'source':group['source'],'pose':'custom','primary_count':chunk['batch']['primary_count'],
            'seed':chunk['batch']['radiation_seed'],'threads':plan['threads'],'electronics':plan['electronics'],
            'gamma_energy_keV':group['gamma_energy_keV'],'source_position_mm':group['source_position_mm']}


def verify_transport_binding(folder,selected):
    folder=Path(folder);target=folder/'transport';manifest=read(target/'stream/manifest.json')
    receipt=read(target/'run.json');prepared=read(target/'prepared.json');source=manifest['source_contract']
    require(receipt.get('status')=='complete' and prepared['selection']==selected
            and manifest['model_sha256']==MODEL_SHA and manifest['primary_count']==selected['primary_count']
            and manifest['seed']==selected['seed'] and manifest['source_id']==selected['source']
            and manifest['source_count_unit']==UNITS[selected['source']]
            and source['position_global_mm']==selected['source_position_mm']
            and (source['energy_keV']==selected['gamma_energy_keV'] if selected['source']==GAMMA else 'energy_keV' not in source),
            'Transport identity/seed/source denominator differs from the frozen chunk')
    require(manifest['source_lh5_sha256']==receipt['source_lh5_sha256']==sha(target/'truth.lh5')
            and manifest['events_sha256']==sha(target/'stream/events.jsonl')
            and manifest['prepared_sha256']==receipt['prepared_sha256']==sha(target/'prepared.json')
            and manifest['geometry_sha256']==sha(target/'geometry.gdml') and manifest['macro_sha256']==sha(target/'run.mac'),
            'Verified transport/stream inputs changed before chunk sealing')
    return manifest


def completed_response(folder,expected):
    """Recover a sealed response/export boundary without loading fields or drifting."""
    from gegi_event_store import Store
    path=Path(folder)/'events.sqlite'
    if not path.exists():return None
    store=Store(path,expected)
    try:
        row=store.db.execute('SELECT body FROM completion WHERE singleton=1').fetchone()
        if row is None:return None
        require(store.db.execute('PRAGMA integrity_check').fetchone()[0]=='ok','Completed native store integrity failed')
        for key in store.keys():store.read(*key,with_signals=True)
        result=json.loads(row[0])
    finally:store.close()
    receipt=Path(folder)/'response.json'
    if receipt.exists():require(read(receipt)==result,'Completed response export changed')
    else:write(receipt,result,fresh=True)
    return result


def verify_done(directory,plan,chunk,*,root=ROOT):
    folder=chunk_path(directory,chunk);done=read(folder/'DONE.json')
    require(done.get('kind')==DONE_KIND and done.get('identity')==chunk_identity(directory,plan,chunk,root=root), 'Sealed chunk identity changed')
    require(done['response']['status'] in ('completed','completed_with_native_failures') and
            done['response']['counts']['initial_primaries']==chunk['batch']['primary_count'],'Sealed chunk denominator changed')
    require(done['response']==read(folder/'response.json'),'Sealed response receipt changed')
    excluded={'DONE.json',*done['archives']}
    require(done['artifacts']==file_inventory(folder,excluded), 'Sealed chunk artifact census/hash changed')
    for ref,record in done['archives'].items():
        archive_path=folder/(ref+'.gz')
        require(archive_path.is_file() and sha(archive_path)==record['sha256'],'Sealed raw archive changed')
        original=folder/ref
        if original.exists():require(sha(original)==record['original_sha256'],'Retained uncompressed raw artifact changed')
    require(done['archives']['transport/truth.lh5']['original_sha256']==read(folder/'transport/run.json')['source_lh5_sha256']
            and done['archives']['transport/stream/events.jsonl']['original_sha256']==read(folder/'transport/stream/manifest.json')['events_sha256'],
            'Lossless archives no longer match the original transport/stream receipts')
    return done


def seal_chunk(directory,plan,chunk,response,*,root=ROOT):
    folder=chunk_path(directory,chunk);require(not (folder/'DONE.json').exists(),'Completed chunk is immutable')
    expected=chunk_identity(directory,plan,chunk,root=root);counts=response['counts']
    transport=verify_transport_binding(folder,selection_for(plan,chunk))
    require(response.get('kind')==RESPONSE_KIND and response.get('status') in ('completed','completed_with_native_failures')
            and response.get('store_identity_sha256')==digest(expected)
            and response.get('input_manifest_sha256')==sha(folder/'transport/stream/manifest.json')
            and response.get('calibration_sha256')==plan['calibration']['sha256']
            and response.get('native_request_sha256')==plan['native_request']['sha256']
            and response.get('new_field_solve') is False and response.get('source_id')==transport['source_id']
            and response.get('photopeak_windows_sha256')==expected['photopeak_windows_sha256'], 'Response is not bound to this frozen chunk')
    require(counts['initial_primaries']==chunk['batch']['primary_count'] and
            counts['zero_deposit_primaries']+counts['nonzero_primaries']==counts['initial_primaries']
            and counts['zero_deposit_primaries']==transport['zero_deposit_primaries']
            and counts['nonzero_primaries']==transport['nonzero_primaries'], 'Response initial census changed')
    require(response==read(folder/'response.json'), 'Response receipt is not durably saved')
    if 'recovery' in plan:
        import gegi_campaign_recovery as R
        require(response.get('prior_recipe_provenance')==R.prior_provenance(plan,chunk,root=root),
                'Response prior-recipe lineage differs from the frozen recovery')
        require(response.get('saved_native_failure')==R.saved_failure(plan,chunk,root=root),
                'Response saved-failure admission differs from the frozen recovery')
    else:require('prior_recipe_provenance' not in response and 'saved_native_failure' not in response,'Unexpected response recovery')
    from gegi_event_store import Store,encoded
    store=Store(folder/'events.sqlite',expected)
    try:
        completion=store.db.execute('SELECT body FROM completion WHERE singleton=1').fetchone()
        require(completion is not None and completion[0]==encoded(response),'Native store is not sealed with this response receipt')
    finally:store.close()
    originals=('transport/truth.lh5','transport/stream/events.jsonl');archives={};archive_started=time.perf_counter()
    for ref in originals:archives[ref]=archive(local(folder/ref,root))
    timing_path=folder/'timings.json'
    timings=read(timing_path) if timing_path.exists() else {
        'transport_driver_wall_s':None,'native_response_and_store_wall_s':None,
        'scope':'Recovered completed science; unavailable stage timings remain null.'}
    timings['verified_archive_wall_s']=time.perf_counter()-archive_started
    write(timing_path,timings)
    done={'kind':DONE_KIND,'identity':expected,'completed_utc':utc(),'response':response,
          'archives':archives,'artifacts':file_inventory(folder,{'DONE.json',*originals})}
    write(folder/'DONE.json',done,fresh=True);verify_done(directory,plan,chunk,root=root)
    # Only these new, explicit campaign originals are replaced, after a verified
    # gzip round trip and durable DONE. Archives retain every original byte.
    for ref in originals:local(folder/ref,root).unlink()
    return done


class Transport:
    """Use the existing admitted source CLI; never infer a partial run succeeded."""
    def __init__(self,root=ROOT,context=None):self.root=Path(root);self.context=context

    def command(self,args,log,tick):
        import gegi_workflow as G
        record_path=Path(log).parent/'active-transport.json';tick()
        record={'kind':'gegi_campaign_transport_child_v1','status':'launching','started_utc':utc()}
        write(record_path,record)
        with Path(log).open('ab') as output:
            child=subprocess.Popen(G.command(self.root)+args+['--windows-root',str(self.root)],cwd=self.root,
                stdout=output,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,shell=False,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            record.update(status='running',pid=child.pid,process_start_identity=identity(child.pid));write(record_path,record)
            while child.poll() is None:tick();time.sleep(2)
        record.update(status='completed' if child.returncode==0 else 'failed',returncode=child.returncode,finished_utc=utc())
        write(record_path,record)
        require(child.returncode==0,'GeGI transport stage failed; its output/log remains preserved')

    def process(self,folder,selection,tick):
        import gegi_workflow as G
        folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
        chosen=folder/'selection.json';checked=folder/'source-checked.json'
        if chosen.exists():require(read(chosen)==selection,'Interrupted transport selection changed')
        else:write(chosen,selection,fresh=True)
        if not checked.exists():write(checked,G.query(['check','--selection-json',W.encoded(selection).decode()],self.root),fresh=True)
        actual=read(checked);require(actual.get('selection')==selection,'Checked transport selection changed')
        if self.context is not None:
            require(B.typed_equal(actual.get('runtime'),self.context['runtime']) and
                    B.typed_equal(actual.get('decay_data'),self.context['decay_data'][selection['source']]),
                    'Transport runtime or nuclear data differ from the frozen accepted context')
        target=folder/'transport';ref='../'+target.relative_to(self.root).as_posix()
        if not target.exists():
            self.command(['prepare','--selection','../'+chosen.relative_to(self.root).as_posix(),
                          '--checked','../'+checked.relative_to(self.root).as_posix(),'--output',ref],folder/'driver.log',tick)
        require((target/'prepared.json').is_file(),'Incomplete geometry preparation preserved; inspect its receipt before recovery')
        if self.context is not None:
            require(emlow_digest(read(target/'emlow-data.json'))==self.context['emlow_sha256'],
                    'EMLOW bytes differ from the frozen accepted dataset')
        if not (target/'run.json').exists():
            require(not any((target/n).exists() for n in ('truth.lh5','run.log')), 'Uncertain radiation attempt preserved; no automatic rerun')
            self.command(['run','--directory',ref],folder/'driver.log',tick)
        self.command(['verify','--directory',ref,'--stage','radiation'],folder/'driver.log',tick)
        if not (target/'stream').exists():self.command(['extract','--directory',ref],folder/'driver.log',tick)
        self.command(['verify','--directory',ref,'--stage','event_ledger'],folder/'driver.log',tick)
        return target/'stream/manifest.json'


def add_counts(totals,group,counts):
    value=totals.setdefault(group,{})
    for key,item in counts.items():
        if type(item) is int:value[key]=value.get(key,0)+item
        elif type(item) is dict:
            named=value.setdefault(key,{})
            for name,count in item.items():
                require(type(count) is int and count>=0,'Invalid named count')
                named[name]=named.get(name,0)+count


def run(directory,*,resume=False,max_chunks=0,root=ROOT,transport=None,worker_factory=None):
    directory=local(directory,root);plan=read_plan(directory,root=root)
    require(type(max_chunks) is int and max_chunks>=0,'Invalid chunk bound')
    inactive_children(directory,root=root)
    with locked(directory,resume=resume):
        if (directory/'COMPLETE.json').exists():return verify_complete(directory,plan,root=root)
        marker=directory/'STOP.json'
        if marker.exists():
            require(resume and read(marker)['plan_sha256']==sha(directory/'plan.json'),'Stop is pending; use explicit resume')
            marker.unlink()
        totals={};new=0;worker=None;current=None
        transport=transport or Transport(root,plan['transport_context'])
        if worker_factory is None:
            from gegi_campaign_response import ResidentWorker
            worker_factory=ResidentWorker
        try:
            for chunk in chunks(plan):
                folder=chunk_path(directory,chunk);current=chunk
                if (folder/'DONE.json').exists():
                    done=verify_done(directory,plan,chunk,root=root);add_counts(totals,chunk['source_group'],done['response']['counts']);continue
                if marker.exists() or max_chunks and new>=max_chunks:
                    return progress(directory,plan,'stopped',totals,None)
                budget=plan['resource_budget']
                if available_disk_bytes(directory)<budget['max_chunk_temporary_bytes']+budget['reserve_bytes']:
                    return progress(directory,plan,'stopped_low_disk',totals,None)
                for ref,value in plan['source_sha256'].items():require(sha(Path(root)/ref)==value,'Frozen source changed: '+ref)
                group=next(g for g in plan['groups'] if g['id']==chunk['source_group'])
                selected=selection_for(plan,chunk)
                response=completed_response(folder,chunk_identity(directory,plan,chunk,root=root))
                if response is not None:
                    done=seal_chunk(directory,plan,chunk,response,root=root)
                    add_counts(totals,chunk['source_group'],done['response']['counts']);new+=1
                    progress(directory,plan,'running',totals,None);continue
                if worker is None:
                    progress(directory,plan,'starting_native',totals,current)
                    if 'recovery' in plan:
                        import gegi_campaign_recovery as R
                        spool=R.spool_path(directory,plan,root)
                    else:spool=directory/'native-spool'
                    worker=worker_factory(bound_file(root,plan['native_request']),spool)
                    startup=time.perf_counter()
                    ready=worker.start()
                    require(ready.get('new_field_solve') is False and ready.get('field_cache_sha256')==
                            read(bound_file(root,plan['native_request']))['field_cache']['sha256'], 'Resident native worker must reuse the exact frozen field cache')
                    startup_path=directory/'native-startup.json'
                    startup_record=read(startup_path) if startup_path.exists() else {'sessions':[]}
                    startup_record['sessions'].append({'recorded_utc':utc(),'elapsed_seconds':time.perf_counter()-startup,
                        'scope':'Resident initialization, cache loading and possible compilation warm-up; not production drift timing.',
                        'native_request_sha256':plan['native_request']['sha256'],'field_cache_sha256':ready['field_cache_sha256']})
                    write(startup_path,startup_record)
                tick=lambda:progress(directory,plan,'running_transport',totals,current)
                transport_started=time.perf_counter()
                manifest=transport.process(folder,selected,tick)
                transport_elapsed=time.perf_counter()-transport_started
                progress(directory,plan,'running_native',totals,current)
                native_started=time.perf_counter()
                extra={}
                if 'recovery' in plan:
                    import gegi_campaign_recovery as R
                    prior=R.prior_provenance(plan,chunk,root=root)
                    if prior is not None:extra['prior_recipe_provenance']=prior
                    saved_failure=R.saved_failure(plan,chunk,root=root)
                    if saved_failure is not None:extra['saved_native_failure']=saved_failure
                response=worker.run_chunk(manifest,folder/'events.sqlite',chunk_identity(directory,plan,chunk,root=root),
                    calibration=plan['calibration'],photopeak_windows=group['photopeak_windows'],receipt_path=folder/'response.json',**extra)
                write(folder/'timings.json',{'transport_driver_wall_s':transport_elapsed,
                    'native_response_and_store_wall_s':time.perf_counter()-native_started,
                    'scope':'Measured orchestration stages. Transport driver includes checks/preparation/extraction; pure remage timing remains in transport/run.json. Native stage includes drift/readout/imaging/storage.'})
                done=seal_chunk(directory,plan,chunk,response,root=root)
                add_counts(totals,chunk['source_group'],done['response']['counts']);new+=1
                progress(directory,plan,'running',totals,None)
            require(sum(v['initial_primaries'] for v in totals.values())==plan['total_initial_primaries'],'Incomplete final campaign denominator')
            terminal='completed_with_native_failures' if any(g.get('native_failed_groups',0) for g in totals.values()) else 'completed'
            complete={'kind':KIND,'status':terminal,'plan_sha256':sha(directory/'plan.json'),
                      'physics_sha256':plan['physics_sha256'],'completed_utc':utc(),'groups':totals,
                      'initial_primaries':plan['total_initial_primaries'],
                      'native_startup_sha256':sha(directory/'native-startup.json') if (directory/'native-startup.json').exists() else None,
                      'chunks':{str(c['chunk_index']):sha(chunk_path(directory,c)/'DONE.json') for c in chunks(plan)}}
            write(directory/'COMPLETE.json',complete,fresh=True);progress(directory,plan,terminal,totals,None)
            return complete
        except BaseException as error:
            progress(directory,plan,'failed',totals,current,error=str(error));raise
        finally:
            if worker is not None:worker.close()


def verify_complete(directory,plan,*,root=ROOT):
    complete=read(Path(directory)/'COMPLETE.json');totals={};records={}
    for chunk in chunks(plan):
        done=verify_done(directory,plan,chunk,root=root);add_counts(totals,chunk['source_group'],done['response']['counts'])
        records[str(chunk['chunk_index'])]=sha(chunk_path(directory,chunk)/'DONE.json')
    require(complete['kind']==KIND and complete['status'] in ('completed','completed_with_native_failures') and complete['physics_sha256']==plan['physics_sha256']
            and complete['plan_sha256']==sha(Path(directory)/'plan.json')
            and complete['groups']==totals and complete['chunks']==records and
            complete['initial_primaries']==sum(g['initial_primaries'] for g in totals.values())==plan['total_initial_primaries'],
            'Campaign completion changed')
    if complete.get('native_startup_sha256') is not None:
        require(complete['native_startup_sha256']==sha(Path(directory)/'native-startup.json'),'Resident startup timing evidence changed')
    return complete


def launch(directory,*,resume=False,root=ROOT,spawn=subprocess.Popen,reader=identity):
    directory=local(directory,root);plan=read_plan(directory,root=root)
    with locked(directory,resume=resume,reader=reader,name='.launch.lock'):
        if (directory/'COMPLETE.json').exists():return {'status':'already_completed','completion':read(directory/'COMPLETE.json')}
        require(resume or not (directory/'STOP.json').exists(),'Stop is pending; use explicit resume')
        lock=directory/'.worker.lock/owner.json'
        if lock.exists():
            owner=read(lock);actual=reader(owner['pid'])
            if actual==owner['process_start_identity']:return {**owner,'status':'already_running'}
            require(actual!='unknown','Campaign worker identity is unknown; inspect it before launch')
        inactive_children(directory,reader=reader,root=root)
        prior=directory/'launcher.json'
        if prior.exists():
            old=read(prior)
            require(old.get('status')!='launching' and type(old.get('pid')) is int,
                    'An interrupted detached launch is unverified; inspect its process ownership')
            actual=reader(old['pid'])
            if actual==old['process_start_identity']:return {**old,'status':'already_running'}
            require(actual!='unknown','Prior launcher identity is unknown; inspect it before another launch')
        require_launch_disk(directory,plan,read(directory/'progress.json')['groups'],root=root)
        args=[sys.executable,'-u','-B','-X','utf8',str(Path(root)/'tools/gegi_campaign.py'),'run','--campaign',str(directory)]
        if resume:args.append('--resume')
        kwargs={'cwd':root,'stdin':subprocess.DEVNULL,'stderr':subprocess.STDOUT,'close_fds':True,'shell':False}
        if os.name=='nt':kwargs['creationflags']=subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP|subprocess.CREATE_NO_WINDOW
        else:kwargs['start_new_session']=True
        write(prior,{'status':'launching','started_utc':utc(),
                     'plan_sha256':sha(directory/'plan.json'),'resume':resume})
        with (directory/'worker.log').open('ab') as output:child=spawn(args,stdout=output,**kwargs)
        record={'status':'launched','pid':child.pid,'process_start_identity':reader(child.pid),'started_utc':utc(),
                'plan_sha256':sha(directory/'plan.json'),'resume':resume}
        require(record['process_start_identity'] not in (None,'unknown'),'Detached worker identity unavailable; inspect before relaunch')
        write(prior,record);return {'status':'launched',**record}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('draft','acceptance','measure-storage','freeze','launch','resume','run','status','stop'))
    parser.add_argument('--campaign',type=Path);parser.add_argument('--plan',type=Path)
    parser.add_argument('--pilots',type=Path);parser.add_argument('--output',type=Path)
    parser.add_argument('--acceptance',type=Path);parser.add_argument('--resume',action='store_true');parser.add_argument('--max-chunks',type=int,default=0)
    args=parser.parse_args(argv)
    if args.action=='draft':result=draft()
    elif args.action=='acceptance':
        require(args.plan is not None and args.pilots is not None and args.output is not None,
                'Acceptance requires --plan, --pilots and a new --output')
        result=build_acceptance(read(args.plan),read(args.pilots),args.output)
    elif args.action=='measure-storage':
        require(args.plan is not None and args.acceptance is not None and args.output is not None,
                'Storage measurement requires --plan, --acceptance and a new --output directory')
        evidence=local(args.acceptance);binding={'ref':evidence.relative_to(ROOT).as_posix(),'sha256':sha(evidence)}
        result=measure_storage(read(args.plan),binding,args.output)
    else:
        require(args.campaign is not None,'Provide --campaign')
        if args.action=='freeze':
            require(args.plan is not None and args.acceptance is not None,'Freeze requires an exact plan and bounded acceptance receipt')
            evidence=local(args.acceptance);binding={'ref':evidence.relative_to(ROOT).as_posix(),'sha256':sha(evidence)}
            result=freeze(args.campaign,read(args.plan),binding)
        elif args.action in ('launch','resume'):result=launch(args.campaign,resume=args.action=='resume')
        elif args.action=='run':result=run(args.campaign,resume=args.resume,max_chunks=args.max_chunks)
        elif args.action=='stop':result=stop(args.campaign)
        else:result=status(args.campaign)
    print(W.encoded(result).decode('utf-8'))


if __name__=='__main__':main()
