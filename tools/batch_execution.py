"""One versioned parent for exact-count serial transport, SSD and readout.

Stage receipts are scientific completion authorities. Driver and export recovery
reuse their sealed bytes; uncertain unsealed attempts are retained and refused.
"""
from __future__ import annotations
import copy, csv, hashlib, html, itertools, json, math, os, re, subprocess, sys, time
from pathlib import Path
import scenario_workflow as W
import workflow_batches as B
import histogram_normalization as H
from local_ui_jobs import ControlError, process_identity, safe_path

CHECKED_KIND='local_scenario_batch_execution_v3'
KIND=CHECKED_KIND
VERSION=3
# The corrected fixed SAP22/Cs137/+30deg acceptance completed all 500 primaries.
# This admits the shared engineering route, not physical angular validation.
ANGULAR_EXECUTION_READY=True
ANGLE_PRECISION_SELECTION_SHA256='0635f393d8780a8bfe43cb7240f2a917e60b60f5cab94a367466363d64c06ef9'
TERMINAL=W.TERMINAL
STAGES=('geometry','native_preparation','radiation','event_ledger','response','results')
SHARED=('geometry','native_preparation')
BATCH_STAGES=('radiation','event_ledger','response')
NEW_SOURCES=('tools/batch_execution.py','tools/workflow_batches.py','tools/histogram_normalization.py','tools/catalog_result_validation.py','transport/batch_source.py','simulation/batch_native_response.jl','simulation/batch_decay_stream.jl','simulation/batch_native_contract.jl','simulation/catalog_native_model.jl','simulation/catalog_decay_stream.jl','simulation/catalog_native_response.jl')
RULES={'contract':'exact_count_serial_parent_v3','native_seed_rule':'SHA256(seed/global_initial_id/raw_row_index/parcel_index); native temporary event_id only',
    'geometry_preparations':1,'field_solutions':1,'independent_calibrations':1,
    'stop_rule':'sealed_stage_or_batch_boundary','resume_rule':'fully_checked_terminal_stage_receipts_only',
    'raw_identity_rule':'preserve_raw_local_add_global_v1','histogram_rule':'unchanged_bins_integer_addition_v1'}

def require(ok,message):
    if not ok:raise ControlError(message,'batch_execution_refused')

def partition(count,seed,cap=B.BATCH_CAP):
    B.primary_count(count);B.exact_integer(seed,1,B.SEED_MAX,'Radiation seed');B.exact_integer(cap,1,B.BATCH_CAP,'Batch cap')
    n=(count+cap-1)//cap;require(n<=B.SEED_MAX,'Unique radiation seed capacity exceeded.')
    return {'schema_version':3,'primary_count':count,'batch_cap':cap,'batch_count':n,'last_batch_count':count-(n-1)*cap,
        'master_seed':seed,'seed_rule':B.SEED_RULE,'seed_stride':B.SEED_STRIDE,'seed_max':B.SEED_MAX,
        'identity_rule':B.IDENTITY_RULE,'radiation_threads':1,'models_serial':True,'batches_serial':True}

def validate_partition(d):
    require(type(d) is dict and B.typed_equal(d,partition(d.get('primary_count'),d.get('master_seed'),d.get('batch_cap'))),'Execution partition differs from exact count/seed rules.')
    return d

def batch_at(d,index):
    validate_partition(d);B.exact_integer(index,0,d['batch_count']-1,'Batch index');off=index*d['batch_cap'];n=min(d['batch_cap'],d['primary_count']-off)
    return {'batch_index':index,'global_initial_offset':off,'primary_count':n,
        'local_initial_primary_id_range':[0,n-1],'global_initial_primary_id_range':[off,off+n-1],
        'radiation_seed':1+(d['master_seed']-1+index*B.SEED_STRIDE)%B.SEED_MAX}

def iter_batches(d):
    validate_partition(d)
    for index in range(d['batch_count']):yield batch_at(d,index)

def batch_directory(directory,index):return Path(directory)/'batches'/f'b{index:010d}'

def transport_command(root=W.ROOT):
    return ['wsl.exe','--distribution','Ubuntu-24.04','--cd',str(Path(root)/'transport'),'--exec','bash','./workflow.sh','python','-B','./batch_source.py']

def transport_check(selection,root=W.ROOT):
    command=transport_command(root)+['check','--request-json',W.encoded(selection).decode('utf-8'),'--windows-root',str(Path(root).resolve())]
    result=subprocess.run(command,cwd=root,stdout=subprocess.PIPE,stderr=subprocess.PIPE,shell=False,timeout=120,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    require(result.returncode==0,'Batch transport readiness failed: '+result.stderr.decode('utf-8',errors='replace')[-2000:])
    return W.decode_json(result.stdout.decode('utf-8-sig'))

def pose_module():
    """Pure shared geometry resolver; no worker or runtime probe."""
    transport=str(W.ROOT/'transport')
    if transport not in sys.path:sys.path.insert(0,transport)
    import source_pose
    return source_pose

def selection_angle(selection):
    return pose_module().angle(selection) if 'angle_deg' in selection else 0

def angle_acceptance(selection,bootstrap_angle=False):
    """Literal CLI-process authority for one new precision acceptance only."""
    require(type(bootstrap_angle) is bool,'Angular bootstrap must be an explicit Boolean process keyword.')
    if not bootstrap_angle:return None
    require(type(selection) is dict and W.digest(selection)==ANGLE_PRECISION_SELECTION_SHA256,
        'Angular bootstrap requires the unchanged SAP22 Cs137 +30deg/500/seed26092631 selection named source-angle-sap22-cs137-precise-v1.')
    return {'kind':'fixed_source_angle_precision_acceptance_v1','selection_sha256':ANGLE_PRECISION_SELECTION_SHA256,
        'prior_failed_parent_ref':'.local/runs/source-angle-sap22-cs137-v1',
        'prior_failed_acceptance_ref':'.local/source-angle-v1/FAILED-ACCEPTANCE.json'}

def validate_source_pose(resolved,root=W.ROOT):
    """Reconstruct new angular authority, including deliberately rehashed edits.

    Legacy receipts have no angular marker and retain their existing checks.
    """
    selection=resolved['selection'];transport=resolved['transport_plan']
    marked=('angle_deg' in selection or 'source_pose' in resolved or 'source_pose' in transport or
        'angle_geometry_plan' in transport or 'transport/source_pose.py' in resolved['source_sha256'])
    if not marked:return
    require(type(selection) is dict and set(selection) in (W.FIELDS,W.FIELDS|{'angle_deg'}),
        'Saved angular selection fields changed.')
    angle=selection_angle(selection)
    require(B.typed_equal(transport.get('selection'),selection),'Saved source pose selection changed.')
    if angle==0:
        require('source_pose' not in resolved and 'source_pose' not in transport and 'angle_geometry_plan' not in transport and
            'transport/source_pose.py' not in resolved['source_sha256'],
            'Zero angle must retain the exact legacy physical pose.')
        require(B.typed_equal(resolved.get('source_position_global_mm'),[0,37.073,.290]),
            'Zero-angle source position differs from its legacy nominal anchor.')
        return
    require(selection['source']!=W.GAMMA and selection['pose']=='nominal','Angular source requires an admitted nominal decay source.')
    expected=pose_module().resolve(angle,root)
    require(B.typed_equal(resolved.get('source_pose'),expected) and
        B.typed_equal(transport.get('source_pose'),expected) and
        B.typed_equal(resolved.get('source_position_global_mm'),expected['position_global_mm']),
        'Saved source angle, position or orientation differs from the resolved anchor pose.')
    angular=transport.get('angle_geometry_plan')
    bounded=copy.deepcopy(selection);bounded['primary_count']=20
    require(type(angular) is dict and B.typed_equal(angular.get('source_pose'),expected) and
        B.typed_equal(angular.get('selection'),bounded),'Angular geometry plan changed its bounded source selection or pose.')
    hashes=angular.get('source_sha256')
    require(type(hashes) is dict and hashes and
        all(B.typed_equal(resolved['source_sha256'].get(ref),digest) for ref,digest in hashes.items()),
        'Angular geometry source hashes differ from the parent plan.')

def check(config,*,root=W.ROOT,allow_existing=False,acceptance=None,bootstrap_angle=False,transport_reader=transport_check,
          validate_settings=W.settings_check,pin_reader=None,runtime_reader=W.runtime_identity):
    """Fresh executable v3 check. Saved v2 preview bytes are never upgraded."""
    require(type(config) is dict and set(config) in (W.FIELDS,W.FIELDS|{'angle_deg'}),'Unsupported batch configuration fields.')
    angular_acceptance=angle_acceptance(config,bootstrap_angle)
    require(angular_acceptance is None or acceptance is None,'Angular precision acceptance retains the original exact-count partition.')
    angle=selection_angle(config)
    W.run_path(config['name'],root);require(allow_existing or not W.run_path(config['name'],root).exists(),'Output exists; choose a new name.')
    require(config['source']!=W.GAMMA,'Gamma uses its preserved v1 20-primary route; arbitrary-count gamma native consumption is not admitted.')
    cap=B.BATCH_CAP
    if acceptance is not None:
        require(type(acceptance) is dict and set(acceptance)=={'kind','batch_cap','primary_count','selection_sha256'} and
            acceptance['kind']=='bounded_batch_acceptance_v1' and config['primary_count']<=500 and
            acceptance['primary_count']==config['primary_count'] and acceptance['selection_sha256']==W.digest(config),
            'Acceptance-only batch cap requires its immutable <=500-primary selection binding.')
        cap=B.exact_integer(acceptance['batch_cap'],1,B.BATCH_CAP-1,'Acceptance-only batch cap')
    batching=partition(config['primary_count'],config['seed'],cap)
    transport=transport_reader(config,root)
    require(type(transport) is dict and transport.get('kind')=='batch_transport_checked_v1' and
        B.typed_equal(transport.get('selection'),config) and transport.get('geometry_preparation_count')==20,
        'Batch readiness changed its selection or geometry-only surrogate.')
    bounded=copy.deepcopy(config);bounded.pop('angle_deg',None);bounded['primary_count']=20
    if config['detector'] in W.MODELS:
        old=W.check(bounded,root=root,validate_settings=validate_settings,pin_reader=pin_reader,
            runtime_reader=runtime_reader,portable_reader=lambda c,r:transport['legacy_geometry_plan'],allow_existing=True)
    else:
        from catalog_workflow import check as catalog_check
        old=catalog_check(bounded,root=root,validate_settings=validate_settings,pin_reader=pin_reader,
            runtime_reader=runtime_reader,transport_reader=lambda c,r:transport['legacy_geometry_plan'],allow_existing=True)
    resolved=copy.deepcopy(old['resolved']);resolved['selection']=copy.deepcopy(config)
    resolved.pop('portable_source_plan',None)
    if config['detector'] not in W.MODELS:
        resolved['operating_model']=catalog_operating(resolved['model_contract'])
    elif 'operating_model' not in resolved:
        from decay_workflow import operating
        resolved['operating_model']=operating(config['detector'],root)
    resolved.update(batching=batching,execution_rules=copy.deepcopy(RULES),transport_plan=transport,acceptance_only=acceptance)
    if angular_acceptance is not None:resolved['angle_acceptance_only']=angular_acceptance
    if angle!=0:
        expected=pose_module().resolve(angle,root)
        require(B.typed_equal(transport.get('source_pose'),expected),'Batch readiness changed its effective source pose.')
        resolved['source_pose']=copy.deepcopy(expected)
        resolved['source_position_global_mm']=copy.deepcopy(expected['position_global_mm'])
        angular=transport.get('angle_geometry_plan')
        require(type(angular) is dict and type(angular.get('source_sha256')) is dict and angular['source_sha256'],
            'Angular geometry readiness has no source hash authority.')
        resolved['source_sha256'].update(angular['source_sha256'])
    if pin_reader is None:
        if config['detector'] in W.MODELS:
            from decay_workflow import source_pins
            resolved['source_sha256'].update(source_pins(config['detector'],root))
        resolved['source_sha256'].update({name:W.sha(Path(root)/name) for name in NEW_SOURCES})
    validate_source_pose(resolved,root)
    # A saved marker alone cannot unlock angular execution: admission must
    # receive the explicit process keyword again while ordinary Run is closed.
    return {'kind':KIND,'schema_version':VERSION,'status':'checked_configuration','science_calls':0,'execution_enabled':angle==0 or ANGULAR_EXECUTION_READY or bootstrap_angle,
        'resolved':resolved,'configuration_sha256':W.digest(resolved)}

def admit(plan,root=W.ROOT,*,resume=False,bootstrap_angle=False,**readers):
    require(type(plan) is dict and type(plan.get('resolved')) is dict and type(plan['resolved'].get('selection')) is dict,
        'Unsupported executable batch plan.')
    angle_acceptance(plan['resolved']['selection'],bootstrap_angle)
    require(selection_angle(plan['resolved']['selection'])==0 or ANGULAR_EXECUTION_READY or bootstrap_angle,
        'Nonzero-angle execution is unavailable: the fixed pilot failed source-position identity; end-to-end acceptance is pending.')
    require(type(plan) is dict and set(plan)=={'kind','schema_version','status','science_calls','execution_enabled','resolved','configuration_sha256'} and
        plan['kind']==KIND and type(plan['schema_version']) is int and plan['schema_version']==VERSION and plan['status']=='checked_configuration' and
        type(plan['science_calls']) is int and plan['science_calls']==0 and plan['execution_enabled'] is True,'Unsupported executable batch plan; preview is not a Start token.')
    actual=check(plan['resolved']['selection'],root=root,allow_existing=resume,acceptance=plan['resolved'].get('acceptance_only'),bootstrap_angle=bootstrap_angle,**readers)
    require(B.typed_equal(actual,plan),'Checked batch plan does not reconstruct; rehashed settings/rules/runtime edits are refused.')
    return actual

def catalog_operating(mc):
    return {'variant_id':mc['model_id'],'source_model_sha256':mc['model_sha256'],'effective_model_sha256':mc['model_sha256'],
        'signed_bias_V':mc['wiring_factor']*mc['bias_span_V'],'contact_potentials_V':mc['contact_potentials_V'],
        'readout_contact_id':mc['readout_contact_id'],'wiring_factor':mc['wiring_factor'],'field_cache_used':False,
        'annealing_time_minutes':None,'qualification':mc['qualification'],
        'calibration':'independent 500 keV injection through recorded fixed wiring'}

def saved_plan(plan,root=W.ROOT):
    require(plan['kind']==KIND and plan['schema_version']==VERSION and plan['execution_enabled'] is True and
        W.digest(plan['resolved'])==plan['configuration_sha256'],'Saved executable plan changed.')
    r=plan['resolved'];validate_partition(r['batching']);require(B.typed_equal(r['execution_rules'],RULES),'Saved execution rules changed.')
    require(r['selection']['primary_count']==r['batching']['primary_count'] and r['selection']['seed']==r['batching']['master_seed'],'Saved count/seed binding changed.')
    if 'angle_acceptance_only' in r:
        require(B.typed_equal(r['angle_acceptance_only'],angle_acceptance(r['selection'],True)),
            'Saved angular precision acceptance binding changed.')
        require(r.get('acceptance_only') is None,'Saved angular precision acceptance partition changed.')
    validate_source_pose(r,root)

def stage_base(directory,stage,batch=None):
    if stage=='geometry':return Path(directory)/'shared/transport'
    if stage=='native_preparation':return Path(directory)/'shared/native'
    if stage=='results':return Path(directory)/'results'
    base=batch_directory(directory,batch['batch_index'])
    return base/('response' if stage=='response' else 'transport/stream' if stage=='event_ledger' else 'transport')

def stage_receipt(directory,stage,batch=None):
    base=Path(directory) if batch is None else batch_directory(directory,batch['batch_index'])
    return base/'receipts'/(stage+'.json')

def rel(path,root):return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()

def native_request(plan,directory,root,batch=None):
    r=plan['resolved'];shared=Path(directory)/'shared/transport/prepared.json';profile=Path(directory)/'electronics/profile.json'
    request={'kind':'batch_native_request_v1','parent_configuration_sha256':plan['configuration_sha256'],
        'selection':r['selection'],'operating_model':r['operating_model'],'numerics':r['numerics'],'source_sha256':r['source_sha256'],
        'shared_prepared_ref':rel(shared,root),'shared_prepared_sha256':W.sha(shared),'profile_ref':rel(profile,root),'profile_sha256':W.sha(profile)}
    if r['selection']['detector'] not in W.MODELS:request['model_contract']=r['model_contract']
    if batch is not None:
        stream=batch_directory(directory,batch['batch_index'])/'transport/stream/manifest.json';prep=Path(directory)/'shared/native/preparation.json'
        request.update(batch=batch,stream_ref=rel(stream,root),stream_sha256=W.sha(stream),native_preparation_ref=rel(prep,root),native_preparation_sha256=W.sha(prep))
    return request

def invoke(argv,directory,stage,root,threads):
    logs=Path(directory)/'logs';logs.mkdir(parents=True,exist_ok=True);path=logs/(stage+'.log')
    require(not path.exists(),'Prior unsealed stage log exists; inspect preserved attempt.')
    identity_path=logs/(stage+'-worker.json')
    record={'kind':'batch_worker_identity_v1','stage':stage,'argv':argv,'status':'dispatch_uncertain','created_utc':W.utc(),'process':None}
    W.write(identity_path,record,fresh=True)
    with path.open('xb') as out:
        call=subprocess.Popen(argv,cwd=root,env=W.child_env(threads),stdout=out,stderr=subprocess.STDOUT,shell=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        record.update(status='running',process={'pid':call.pid,'identity':process_identity(call.pid)})
        W.write(identity_path,record);code=call.wait()
    record.update(status='completed' if code==0 else 'failed',returncode=code,finished_utc=W.utc());W.write(identity_path,record)
    require(code==0,'Batch stage failed; retained log: '+rel(path,root))

def worker(stage,plan,directory,batch=None,root=W.ROOT):
    directory=Path(directory);s=plan['resolved']['selection'];base=stage_base(directory,stage,batch);command=transport_command(root)
    common=['--windows-root',str(Path(root).resolve())]
    if stage=='geometry':
        argv=command+['prepare','--request','../'+rel(directory/'selection.json',root),'--checked','../'+rel(directory/'transport-checked.json',root),'--output','../'+rel(base,root),*common]
    elif stage=='native_preparation':
        request=directory/'native-prepare-request.json';W.write(request,native_request(plan,directory,root),fresh=True)
        argv=[W.child_env(s['threads'])['JULIA_EXE'],'--startup-file=no','--threads='+str(s['threads']),'--project='+str(Path(root)/'simulation'),str(Path(root)/'simulation/batch_native_response.jl'),'--request',str(request),'--prepare',str(base)]
    elif stage=='radiation':
        request=batch_directory(directory,batch['batch_index'])/'batch.json';W.write(request,batch,fresh=True)
        argv=command+['run','--shared','../'+rel(directory/'shared/transport/prepared.json',root),'--batch','../'+rel(request,root),'--output','../'+rel(base,root),*common]
    elif stage=='event_ledger':argv=command+['extract','--directory','../'+rel(base.parent,root),*common]
    elif stage=='response':
        request=batch_directory(directory,batch['batch_index'])/'native-request.json';W.write(request,native_request(plan,directory,root,batch),fresh=True)
        argv=[W.child_env(s['threads'])['JULIA_EXE'],'--startup-file=no','--threads='+str(s['threads']),'--project='+str(Path(root)/'simulation'),str(Path(root)/'simulation/batch_native_response.jl'),'--request',str(request),'--respond',str(base)]
    else:
        return export_results(plan,directory)
    invoke(argv,directory if batch is None else batch_directory(directory,batch['batch_index']),stage,root,s['threads'])
    if stage=='native_preparation':return W.read(base/'preparation.json')
    if stage=='response':return W.read(base/'run.json')
    if stage=='radiation':return W.read(base/'run.json')
    if stage=='event_ledger':return W.read(base/'manifest.json')
    return W.read(base/'prepared.json')

def stream_jsonl(path):
    with Path(path).open(encoding='utf-8') as stream:
        for line in stream:yield W.decode_json(line)

def validate_output(stage,plan,directory,batch,result):
    base=stage_base(directory,stage,batch)
    require(type(result) is dict,'Stage result must be an object.')
    if stage=='geometry':
        require(result.get('kind')=='batch_shared_transport_prepared_v1' and result.get('status')=='complete' and
            B.typed_equal(result.get('checked_transport'),plan['resolved']['transport_plan']),'Shared geometry does not bind its checked selection.')
        if 'source_pose' in plan['resolved']:
            require(B.typed_equal(result.get('source_pose'),plan['resolved']['source_pose']) and
                B.typed_equal(result.get('source_position_global_mm'),plan['resolved']['source_position_global_mm']),
                'Shared geometry changed its effective source position or orientation.')
        for ref,digest in result['files_sha256'].items():require(W.sha(safe_path(directory.parents[2],ref))==digest,'Shared geometry bytes changed.')
    if stage in ('native_preparation','response'):
        root=directory.parents[2]
        request_path=directory/'native-prepare-request.json' if batch is None else batch_directory(directory,batch['batch_index'])/'native-request.json'
        request=W.read(request_path);expected=native_request(plan,directory,root,batch)
        require(B.typed_equal(request,expected) and result.get('request_sha256')==W.sha(request_path),'Native request differs from the exact checked inputs.')
        for key in ('parent_configuration_sha256','shared_prepared_sha256','profile_sha256','source_sha256','numerics','operating_model'):
            require(B.typed_equal(result.get(key),request[key]),'Native result changed '+key+'.')
        shared=W.read(directory/'shared/transport/prepared.json')
        require(B.typed_equal(result.get('model_contract'),shared['model_contract']),'Native result changed its exact model/variant.')
        require(type(result.get('artifacts')) is dict and result['artifacts'],'Native result has no exact artifact authority.')
        for ref,digest in result['artifacts'].items():require(W.sha(safe_path(base,ref))==digest,'Native artifact changed: '+ref)
    if stage=='native_preparation':
        require(result.get('status')=='complete' and result.get('independent_calibration_calls')==1 and result.get('state_sha256')==W.sha(base/'state.bin'),'Shared native state must bind one independent calibration and exact saved fields.')
    if stage=='radiation':
        require(result.get('status')=='complete' and result.get('number_of_simulated_events')==batch['primary_count'] and result.get('initial_ledger_count')==batch['primary_count'],'Raw radiation count/ledger mismatch.')
        commands=[line.split('#',1)[0].strip() for line in (base/'run.mac').read_text().splitlines()]
        active=[line for line in commands if line and line.split()[0]=='/run/beamOn']
        require(active==['/run/beamOn '+str(batch['primary_count'])],'Effective macro must contain exactly one literal planned beamOn.')
    if stage=='event_ledger':
        require(result.get('batch')==batch and result.get('primary_count')==batch['primary_count'],'Batch stream census mismatch.')
        count=0
        for chunk in result['chunks']:
            require(chunk['first_global_decay_id']==count and Path(chunk['file']).name==chunk['file'],'Stream chunk identity changed.')
            path=base/chunk['file'];require(W.sha(path)==chunk['sha256'],'Stream chunk bytes changed.');n=0
            for row in stream_jsonl(path):
                require(type(row.get('local_initial_id')) is int and row['event_id']==row['global_decay_id']==row['local_initial_id']==count and row['global_initial_id']==batch['global_initial_offset']+count and row['batch_index']==batch['batch_index'],'Complete initial ledger has missing/changed raw/global IDs.')
                count+=1;n+=1
            require(n==chunk['count'],'Chunk row census changed.')
        require(count==batch['primary_count'],'Initial ledger is incomplete; zeros/failures must remain.')
    if stage=='response':
        require(result.get('status') in ('completed_provisional_native_response','completed_with_native_failures'),'Native response is not terminal.')
        counts=result['counts'];require(counts['initial_primaries']==batch['primary_count'] and counts['accepted']+counts['rejected']==counts['groups'] and counts['rejected']==counts['native_failed_groups']+counts['readout_rejected'],'Native/readout census mismatch.')
        prep=W.read(directory/'shared/native/preparation.json')
        require(B.typed_equal(result.get('batch'),batch) and result.get('native_preparation_sha256')==W.sha(directory/'shared/native/preparation.json') and
            result.get('independent_calibration_calls')==0 and result.get('calibration_calls')==0 and result.get('new_field_solution') is False and
            result.get('calibration')==prep['calibration'] and result.get('field_fingerprint')==prep['field_fingerprint'],
            'Batch response repeated or changed shared fields/calibration.')
        actual=W.read(base/'readout-config.json');expected=copy.deepcopy(plan['resolved']['electronics_configuration']);expected['expected_primary_count']=batch['primary_count']
        require(actual==expected,'Readout config differs beyond expected_primary_count; rehashed gain/threshold edits are refused.')
        from catalog_result_validation import response_census
        bounded=copy.deepcopy(plan['resolved']);bounded['selection']['primary_count']=batch['primary_count']
        response_census(batch_directory(directory,batch['batch_index']),bounded,result)
        source,contract=histogram_source(plan)
        if source!=W.CS:
            require(result.get('source_id')==source and B.typed_equal(result.get('source_contract'),contract),
                'Batch response histogram source differs from the selected source.')
            H.validate(W.read(base/'histograms.json'),counts,source,contract,result['source_sha256'],csv_path=base/'histograms.csv')
        for file in ('truth.jsonl','scalars.jsonl','traces.jsonl','endpoints.jsonl'):
            for row in stream_jsonl(base/file):
                local=row.get('local_initial_id')
                require(type(local) is int and 0<=local<batch['primary_count'] and row.get('event_id')==row.get('global_decay_id')==local and
                    row.get('global_initial_id')==batch['global_initial_offset']+local and row.get('batch_index')==batch['batch_index'],
                    'Response lost raw local or global initial identity: '+file)
    if stage=='results':
        require(result.get('kind')=='batch_parent_results_v1' and result.get('status')=='complete' and
            result.get('configuration_sha256')==plan['configuration_sha256'],'Results do not bind this parent.')
        prefix=checked_prefix(plan,directory)
        for key,value in prefix.items():require(result.get(key)==value,'Result count/chain changed.')
        for ref,digest in result['artifacts'].items():require(W.sha(safe_path(base,ref))==digest,'Result artifact changed.')
        h=W.read(base/'histograms.json');source,contract=histogram_source(plan)
        interpreted=H.validate(h,prefix['counts'],source,contract,plan['resolved']['source_sha256'],merged=True,csv_path=base/'histograms.csv')
        legacy=source!=W.CS and interpreted['histogram_schema_version']==1
        require(B.typed_equal(h,aggregate_histograms(plan,directory,prefix['counts'],legacy_output=legacy)),
            'Merged histogram changed its fixed bins or accounting.')

def completed_result(stage,plan,directory,batch,root):
    """Recover a worker's checked terminal bytes after controller interruption."""
    logs=(Path(directory) if batch is None else batch_directory(directory,batch['batch_index']))/'logs'
    identity=logs/(stage+'-worker.json')
    if identity.exists():
        record=W.read(identity)
        require(record.get('kind')=='batch_worker_identity_v1' and record.get('stage')==stage and
            record.get('process') and W.identity_ended(record['process']),'Prior stage worker is active or its dispatch is uncertain.')
    base=stage_base(directory,stage,batch)
    filename={'geometry':'prepared.json','native_preparation':'preparation.json','radiation':'run.json','event_ledger':'manifest.json','response':'run.json','results':'results.json'}[stage]
    require((base/filename).is_file(),'An unsealed '+stage+' attempt exists; inspect its preserved output instead of repeating science.')
    result=W.read(base/filename);validate_output(stage,plan,directory,batch,result)
    if stage in ('geometry','radiation','event_ledger'):
        args=['verify','--stage',stage]
        args+=['--shared','../'+rel(base/'prepared.json',root)] if stage=='geometry' else ['--directory','../'+rel(base if stage=='radiation' else base.parent,root)]
        call=subprocess.run(transport_command(root)+args+['--windows-root',str(Path(root).resolve())],cwd=root,stdout=subprocess.PIPE,stderr=subprocess.PIPE,shell=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        require(call.returncode==0,'Retained terminal transport validation failed: '+call.stderr.decode('utf-8',errors='replace')[-2000:])
        require(B.typed_equal(result,W.decode_json(call.stdout.decode('utf-8-sig'))),'Retained terminal worker receipt changed.')
    return result

def seal_stage(stage,plan,directory,batch,result,started,elapsed):
    validate_output(stage,plan,directory,batch,result)
    base=stage_base(directory,stage,batch);stamp={'kind':'batch_stage_receipt_v1','stage':stage,'status':'completed',
        'configuration_sha256':plan['configuration_sha256'],'batch':batch,'started_utc':started,'elapsed_seconds':elapsed,'finished_utc':W.utc(),
        'base':base.relative_to(directory).as_posix(),'artifacts':W.inventory(base),'result':result}
    W.write(stage_receipt(directory,stage,batch),stamp,fresh=True);return stamp

def verify_stage(stage,plan,directory,batch):
    path=stage_receipt(directory,stage,batch);stamp=W.read(path)
    require(stamp['kind']=='batch_stage_receipt_v1' and stamp['stage']==stage and stamp['status']=='completed' and stamp['configuration_sha256']==plan['configuration_sha256'] and B.typed_equal(stamp['batch'],batch),'Stage receipt binding changed.')
    base=stage_base(directory,stage,batch);require(stamp['base']==base.relative_to(directory).as_posix(),'Stage artifact base changed.')
    W.verify_inventory(base,stamp['artifacts']);validate_output(stage,plan,directory,batch,stamp['result']);return stamp

def add_counts(total,counts):
    for key,value in counts.items():
        if type(value) is int:total[key]=total.get(key,0)+value
        elif type(value) is dict:total.setdefault(key,{});add_counts(total[key],value)
        else:require(value is None,'Noninteger batch count cannot be aggregated.');total.setdefault(key,None)

def checked_prefix(plan,directory):
    """Stream batch receipts. Memory stays independent of batch/primary count."""
    counts={};chain=W.digest([]);completed=0;primaries=0
    for batch in iter_batches(plan['resolved']['batching']):
        base=batch_directory(directory,batch['batch_index']);path=base/'batch-complete.json'
        if not path.exists():break
        sealed=W.read(path);require(sealed['kind']=='batch_complete_v1' and B.typed_equal(sealed['batch'],batch) and sealed['configuration_sha256']==plan['configuration_sha256'],'Batch terminal identity changed.')
        for stage in BATCH_STAGES:
            record=verify_stage(stage,plan,directory,batch)
            require(sealed['stage_receipt_sha256'][stage]==W.sha(stage_receipt(directory,stage,batch)),'Batch stage receipt changed.')
        response=record['result'];require(sealed['counts']==response['counts'],'Batch aggregate changed.');add_counts(counts,sealed['counts'])
        chain=W.digest({'previous':chain,'batch_index':batch['batch_index'],'batch_sha256':W.sha(path)});completed+=1;primaries+=batch['primary_count']
    return {'completed_batch_count':completed,'completed_primary_count':primaries,'counts':counts,'batch_receipt_chain_sha256':chain}

HISTOGRAM_STAGES=H.STAGES
HISTOGRAM_NOTE=H.NOTE
def histogram_row(stage,bin,count,counts,value_key=H.LEGACY_KEY):
    return H.row(stage,bin,count,counts,value_key)

def histogram_source(plan):
    r=plan['resolved'];source=r['selection']['source']
    if source==W.CS:return source,None
    contract=r.get('decay_source_contract',r.get('source_contract'))
    require(contract is not None,'Generic histogram has no selected source contract.')
    return source,contract

def aggregate_histograms(plan,directory,counts,*,legacy_output=False):
    source,contract=histogram_source(plan);normal=H.descriptor(source,contract)
    require(not legacy_output or H.legacy_authority(plan['resolved']['source_sha256'],merged=True),
        'Historical merge interpretation requires its known original exporter.')
    value_key=H.DIAGNOSTIC_KEY if normal is not None and not legacy_output else H.LEGACY_KEY
    totals={}
    for batch in iter_batches(plan['resolved']['batching']):
        base=batch_directory(directory,batch['batch_index']);require((base/'batch-complete.json').is_file(),'Histogram merge requires every terminal batch.')
        report=W.read(base/'response/run.json');h=W.read(base/'response/histograms.json')
        require(report.get('source_id',source)==source and
            (normal is None or B.typed_equal(report.get('source_contract'),contract)),
            'Batch histogram source differs from the selected source.')
        H.validate(h,report['counts'],source,contract,report.get('source_sha256'),
            csv_path=base/'response/histograms.csv' if normal is not None or (base/'response/histograms.csv').exists() else None)
        for row in h['bins']:
            stage,bin,n=row['stage'],row['bin'],row['count'];key=(stage,bin)
            totals[key]=totals.get(key,0)+n
    result={'bins':[histogram_row(stage,bin,n,counts,value_key) for (stage,bin),n in sorted(totals.items())],
        'width_keV':5,'normalization_denominators':counts,'note':HISTOGRAM_NOTE}
    H.attach(result,None if legacy_output else normal)
    H.validate(result,counts,source,contract,plan['resolved']['source_sha256'],merged=True)
    return result

def export_results(plan,directory):
    prefix=checked_prefix(plan,directory);s=plan['resolved']['selection'];base=Path(directory)/'results';base.mkdir(exist_ok=False)
    merged=aggregate_histograms(plan,directory,prefix['counts']);W.write(base/'histograms.json',merged,fresh=True)
    fields=H.fields(merged.get('normalization',{}).get('value_key',H.LEGACY_KEY))
    with (base/'histograms.csv').open('x',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(merged['bins'])
    photon_note='' if 'normalization' not in merged else '<p>Photon normalization uses the sum of counts in the selected source\'s closed diagnostic windows, not a decay branching intensity or efficiency. <a href="histograms.json">Source and exact windows (JSON)</a>.</p>'
    (base/'index.html').write_text('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Batch results</title><h1>'+html.escape(s['detector'])+' · '+html.escape(s['source'])+'</h1><p>'+str(s['primary_count'])+' original primaries retained, including zeros and failures. Native signed signals and independent injection calibration remain separate from radiation truth.</p><p>Engineering example; no physical resolution, calibrated CCE or experimental fit.</p><p><a href="results.json">Settings and counts</a> · <a href="histograms.csv">Merged stage histograms</a></p>'+photon_note+'<p>Original complete event ledgers and signed signals remain in each sealed batch folder.</p></html>',encoding='utf-8')
    result={'kind':'batch_parent_results_v1','status':'complete','configuration_sha256':plan['configuration_sha256'],**prefix,
        'artifacts':{name:W.sha(base/name) for name in ('histograms.json','histograms.csv','index.html')}}
    W.write(base/'results.json',result,fresh=True);return result

def execute(plan,*,root=W.ROOT,resume=False,dispatch_id=None,bootstrap_angle=False,executor=worker,admitter=admit,lease=W.execution_lease,after_seal=None,recoverer=completed_result):
    require(type(bootstrap_angle) is bool,'Angular bootstrap must be an explicit Boolean process keyword.')
    # Preserve injected legacy admitter signatures when the keyword is unused.
    authority={'bootstrap_angle':True} if bootstrap_angle else {}
    plan=admitter(plan,root,resume=resume,**authority);directory=W.run_path(plan['resolved']['selection']['name'],root)
    with lease(root):
        W.verify_dispatch_reservations(plan,root,dispatch_id)
        if resume:
            require(directory.is_dir(),'No saved batch parent to resume.');saved=W.read(directory/'resolved-config.json');require(B.typed_equal(saved,plan),'Resume uses exact saved checked settings.')
            receipt=W.read(directory/'run.json');require(W.identity_ended(receipt.get('supervisor')),'Prior driver is still active or uncertain.')
            if (directory/'COMPLETE.json').exists():return inspect(directory.name,root)
            receipt.setdefault('resumes',[]).append({'requested_utc':W.utc(),'prior_status':receipt['status']});(directory/'STOP.json').unlink(missing_ok=True)
        else:
            directory.mkdir(parents=True,exist_ok=False);W.write(directory/'resolved-config.json',plan,fresh=True);W.write(directory/'selection.json',plan['resolved']['selection'],fresh=True)
            W.write(directory/'transport-checked.json',plan['resolved']['transport_plan'],fresh=True);W.write(directory/'electronics/profile.json',plan['resolved']['profile'],fresh=True)
            receipt={'kind':KIND,'schema_version':VERSION,'resolved':plan['resolved'],'configuration_sha256':plan['configuration_sha256'],'created_utc':W.utc(),'stages':{},'batch_count':plan['resolved']['batching']['batch_count']}
        receipt.update(status='running',supervisor={'pid':os.getpid(),'identity':process_identity(os.getpid())},resume_allowed=False)
        receipt.update(checked_prefix(plan,directory));W.write(directory/'run.json',receipt)
        def stop():
            if (directory/'STOP.json').exists():receipt.update(status='stopped',resume_allowed=True,stopped_utc=W.utc());W.write(directory/'run.json',receipt);return True
            return False
        def stage_run(stage,batch=None):
            path=stage_receipt(directory,stage,batch)
            if path.exists():
                stamp=verify_stage(stage,plan,directory,batch)
                return dict(stamp,reuse='verified_sealed_stage',original_elapsed_seconds=stamp['elapsed_seconds'])
            base=stage_base(directory,stage,batch)
            if stop():return None
            W.verify_pins(plan['resolved'],root);started=W.utc();t=time.perf_counter()
            receipt['active_stage']=stage
            if batch is None:receipt.pop('active_batch_index',None)
            else:receipt['active_batch_index']=batch['batch_index']
            W.write(directory/'run.json',receipt)
            if base.exists():
                result=recoverer(stage,plan,directory,batch,root)
                stamp=seal_stage(stage,plan,directory,batch,result,started,None)
                stamp['recovered_terminal_worker']=True;W.write(path,stamp)
            else:
                result=executor(stage,plan,directory,batch,root)
                stamp=seal_stage(stage,plan,directory,batch,result,started,time.perf_counter()-t)
            if after_seal:after_seal(stage,batch,stamp)
            return stamp
        try:
            for stage in SHARED:
                stamp=stage_run(stage)
                if stamp is None:return receipt
                receipt['stages'][stage]={'status':'completed','receipt_sha256':W.sha(stage_receipt(directory,stage)),'elapsed_seconds':stamp['elapsed_seconds'],
                    **{k:stamp[k] for k in ('reuse','original_elapsed_seconds') if k in stamp}};W.write(directory/'run.json',receipt)
            for batch in iter_batches(plan['resolved']['batching']):
                if batch['batch_index']<receipt['completed_batch_count']:continue
                if stop():return receipt
                base=batch_directory(directory,batch['batch_index']);base.mkdir(parents=True,exist_ok=True)
                for stage in BATCH_STAGES:
                    stamp=stage_run(stage,batch)
                    if stamp is None:return receipt
                    receipt['active_batch_index']=batch['batch_index'];receipt['active_stage']=stage;W.write(directory/'run.json',receipt)
                complete={'kind':'batch_complete_v1','status':'completed_with_native_failures' if stamp['result']['counts']['native_failed_groups'] else 'completed',
                    'configuration_sha256':plan['configuration_sha256'],'batch':batch,'counts':stamp['result']['counts'],
                    'stage_receipt_sha256':{s:W.sha(stage_receipt(directory,s,batch)) for s in BATCH_STAGES}}
                W.write(base/'batch-complete.json',complete,fresh=True)
                add_counts(receipt['counts'],complete['counts']);receipt['completed_batch_count']+=1;receipt['completed_primary_count']+=batch['primary_count']
                receipt['batch_receipt_chain_sha256']=W.digest({'previous':receipt['batch_receipt_chain_sha256'],'batch_index':batch['batch_index'],'batch_sha256':W.sha(base/'batch-complete.json')})
                W.write(directory/'run.json',receipt)
                if after_seal:after_seal('batch',batch,complete)
            if stop():return receipt
            stamp=stage_run('results')
            if stamp is None:return receipt
            receipt['stages']['results']={'status':'completed','receipt_sha256':W.sha(stage_receipt(directory,'results')),'elapsed_seconds':stamp['elapsed_seconds']}
            receipt.update(status='completed_with_native_failures' if receipt['counts'].get('native_failed_groups',0) else 'completed',finished_utc=W.utc(),resume_allowed=False)
            receipt.pop('active_batch_index',None);receipt.pop('active_stage',None);W.write(directory/'run.json',receipt)
            summary={'kind':'batch_parent_complete_v1','status':receipt['status'],'configuration_sha256':plan['configuration_sha256'],
                **{k:receipt[k] for k in ('completed_batch_count','completed_primary_count','counts','batch_receipt_chain_sha256')},
                'fixed_artifacts':{relfile:stamp for relfile,stamp in W.inventory(directory).items() if not relfile.startswith('batches/') and relfile not in ('COMPLETE.json','STOP.json')}}
            W.write(directory/'COMPLETE.json',summary,fresh=True);return receipt
        except BaseException as error:
            receipt.update(status='failed',error=str(error),failed_utc=W.utc(),resume_allowed=False);W.write(directory/'run.json',receipt);raise

def inspect(name,root=W.ROOT):
    directory=W.run_path(name,root);plan=W.read(directory/'resolved-config.json');saved_plan(plan,root);receipt=W.read(directory/'run.json')
    require(receipt['kind']==KIND and receipt['configuration_sha256']==plan['configuration_sha256'] and B.typed_equal(receipt['resolved'],plan['resolved']),'Saved parent settings changed.')
    for stage in SHARED:
        if stage_receipt(directory,stage).exists():verify_stage(stage,plan,directory,None)
    prefix=checked_prefix(plan,directory)
    if (directory/'COMPLETE.json').exists():
        complete=W.read(directory/'COMPLETE.json');require(complete['kind']=='batch_parent_complete_v1' and complete['configuration_sha256']==plan['configuration_sha256'] and complete['status']==receipt['status'] and receipt['status'] in TERMINAL,'Parent completion binding changed.')
        for key,value in prefix.items():require(complete[key]==receipt[key]==value,'Parent complete census/chain changed.')
        require(prefix['completed_batch_count']==plan['resolved']['batching']['batch_count'] and prefix['completed_primary_count']==plan['resolved']['selection']['primary_count'],'Incomplete parent count.')
        W.verify_inventory(directory,complete['fixed_artifacts']);verify_stage('results',plan,directory,None);receipt['verification']='terminal_artifacts_verified'
    else:receipt['verification']='sealed_prefix_verified';receipt.update(prefix)
    if stage_receipt(directory,'results').exists() and plan['resolved']['selection']['source']!=W.CS:
        source,contract=histogram_source(plan)
        receipt['histogram_normalization_interpretation']=H.validate(W.read(directory/'results/histograms.json'),prefix['counts'],
            source,contract,plan['resolved']['source_sha256'],merged=True,csv_path=directory/'results/histograms.csv')
    return receipt

def request_stop(name,root=W.ROOT):
    directory=W.run_path(name,root);receipt=W.read(directory/'run.json');require(receipt['kind']==KIND and receipt['status']=='running','Batch parent is not active.')
    W.write(directory/'STOP.json',{'requested_utc':W.utc()},fresh=True);return {'status':'stop_requested'}

def event_page(name,batch_index,offset=0,limit=50,root=W.ROOT):
    directory=W.run_path(name,root);plan=W.read(directory/'resolved-config.json');saved_plan(plan,root);batch=batch_at(plan['resolved']['batching'],batch_index)
    B.exact_integer(offset,0,batch['primary_count']-1,'Page offset');B.exact_integer(limit,1,100,'Page limit')
    base=batch_directory(directory,batch_index);require((base/'batch-complete.json').is_file(),'Only sealed terminal batches have event pages.')
    response=verify_stage('response',plan,directory,batch);require(W.read(base/'batch-complete.json')['stage_receipt_sha256']['response']==W.sha(stage_receipt(directory,'response',batch)),'Batch response receipt changed.')
    end=min(batch['primary_count'],offset+limit);scalars=iter(stream_jsonl(base/'response/scalars.jsonl'));pending=next(scalars,None);records=[]
    for truth in stream_jsonl(base/'response/truth.jsonl'):
        local=truth['local_initial_id'];parts=[];primary=None
        while pending is not None and pending['local_initial_id']==local:
            if pending.get('group_id') is None:primary=pending
            else:parts.append(pending)
            pending=next(scalars,None)
        if offset<=local<end:records.append({'global_initial_id':truth['global_initial_id'],'local_initial_id':local,'batch_index':batch_index,'truth':truth,'primary':primary,'pulse_groups':parts})
        if local>=end-1:break
    traces=[]
    for trace in stream_jsonl(base/'response/traces.jsonl'):
        if offset<=trace['local_initial_id']<end:traces.append({k:v for k,v in trace.items() if k!='trace'})
    return {'kind':'local_batch_event_page_v1','name':name,'configuration_sha256':plan['configuration_sha256'],'batch_index':batch_index,
        'batch_offset':batch['global_initial_offset'],'batch_primary_count':batch['primary_count'],'offset':offset,'limit':limit,
        'next_offset':end if end<batch['primary_count'] else None,'complete':end==batch['primary_count'],'records':records,'traces':traces,
        'batch_sha256':W.sha(base/'batch-complete.json'),'response_summary_sha256':W.sha(base/'response/run.json'),
        'artifacts':[{'file':record['base']+'/'+ref,**stamp} for stage in BATCH_STAGES
            for record in (verify_stage(stage,plan,directory,batch),) for ref,stamp in record['artifacts'].items()]}

def focused_waveforms(name,batch_index,global_primary_id,group_id,root=W.ROOT):
    directory=W.run_path(name,root);plan=W.read(directory/'resolved-config.json');saved_plan(plan,root);batch=batch_at(plan['resolved']['batching'],batch_index)
    B.exact_integer(global_primary_id,batch['global_initial_offset'],batch['global_initial_offset']+batch['primary_count']-1,'Global primary ID');B.exact_integer(group_id,0,B.MAX_SAFE_INTEGER,'Group ID')
    verified=verify_stage('response',plan,directory,batch);base=batch_directory(directory,batch_index);require((base/'batch-complete.json').is_file(),'Only sealed batches have focused waveforms.')
    require(W.read(base/'batch-complete.json')['stage_receipt_sha256']['response']==W.sha(stage_receipt(directory,'response',batch)),'Batch response receipt changed.')
    for trace in stream_jsonl(base/'response/traces.jsonl'):
        if trace['global_initial_id']==global_primary_id and trace['group_id']==group_id:
            charge={'time_since_origin_ns':[],'induced_equivalent_energy_keV':[]}
            with (base/'response/signals.csv').open(encoding='utf-8',newline='') as stream:
                for row in csv.DictReader(stream):
                    if int(row['global_initial_id'])==global_primary_id and int(row['group_id'])==group_id:
                        for key in charge:
                            value=float(row[key]);require(math.isfinite(value),'Nonfinite saved native signal.');charge[key].append(value)
            require(charge['time_since_origin_ns'],'Selected retained trace has no exact native charge samples.')
            return {'kind':'local_batch_waveform_v1','name':name,'configuration_sha256':plan['configuration_sha256'],'batch_index':batch_index,
                'batch_sha256':W.sha(base/'batch-complete.json'),'response_summary_sha256':W.sha(base/'response/run.json'),'record':trace,
                'charge_input':charge,'ionisation_energy_eV':verified['result']['ionisation_energy_eV']}
    raise ControlError('This pulse has no retained display trace; full signed signals remain in its sealed artifacts.','batch_waveform_unavailable')

def artifact(name,file,root=W.ROOT):
    directory=W.run_path(name,root);plan=W.read(directory/'resolved-config.json');saved_plan(plan,root);path=safe_path(directory,file)
    require(type(file) is str and '.pending-' not in file,'Unsafe artifact path.')
    matched=False
    pattern=re.fullmatch(r'batches/b([0-9]{10})/(.+)',file)
    if pattern:
        batch=batch_at(plan['resolved']['batching'],int(pattern[1]));base=batch_directory(directory,batch['batch_index']);require((base/'batch-complete.json').exists(),'Only sealed batch artifacts are available.')
        for stage in BATCH_STAGES:
            record=verify_stage(stage,plan,directory,batch);prefix=record['base']+'/'
            if file.startswith(prefix) and file[len(prefix):] in record['artifacts']:matched=True
        if pattern[2]=='batch-complete.json':matched=True
    elif file in ('resolved-config.json','run.json'):
        inspect(name,root);matched=True
    else:
        complete=W.read(directory/'COMPLETE.json');inspect(name,root);matched=file in complete['fixed_artifacts'] or file=='COMPLETE.json'
    require(matched,'Artifact is not in a sealed stage inventory.');return path
