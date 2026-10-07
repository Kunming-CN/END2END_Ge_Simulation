"""Shared Control/CLI workflow for catalog models in the unchanged LBNL assembly.

This explicit contract leaves all five previous scientific producers/contracts
intact. New eligibility derives from exact model inputs and actual cavity size.
"""
from __future__ import annotations
import copy, json, os, re, subprocess, sys, time
from pathlib import Path
import scenario_workflow as W
from local_ui_jobs import process_identity, safe_path
from catalog_result_validation import response_census

KIND='local_catalog_workflow_v1'
STAGES=W.STAGES
EXPORTER_REF='.local/m2a/catalog-source-build-v1/cryostat_catalog_export'
BUILD_REF='.local/m2a/catalog-source-build-v1/exporter-build.json'
SOURCES=('tools/catalog_workflow.py','tools/catalog_result_validation.py','transport/catalog_geometry.py','transport/catalog_source.py','transport/cryostat_catalog_export.cc',
    'transport/catalog_exporter/CMakeLists.txt','transport/catalog_exporter_setup.py','simulation/catalog_native_model.jl','simulation/catalog_native_response.jl','simulation/catalog_decay_stream.jl')
_MODEL_CACHE={}

def command(root=W.ROOT):
    return ['wsl.exe','--distribution','Ubuntu-24.04','--cd',str(Path(root)/'transport'),'--exec','bash','./workflow.sh','python','-B','./catalog_source.py']

def query(args,root=W.ROOT,runner=subprocess.run):
    result=runner(command(root)+args+['--windows-root',str(Path(root).resolve())],cwd=root,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=120,shell=False,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    W.require(result.returncode==0,'Catalog source input/readiness check failed: '+result.stderr.decode('utf-8',errors='replace')[-2000:])
    return W.decode_json(result.stdout.decode('utf-8-sig'))

def model_contracts(root=W.ROOT):
    root=Path(root);catalog=W.read(root/'models/catalog.json')
    refs=['models/catalog.json','transport/catalog_geometry.py','transport/handoff.py','transport/cryostat_nominal.json',
        *('models/'+m['model'] for m in catalog['detectors']),*('models/'+d['path'] for d in catalog['dependencies']),
        *('.local/transport/LBNL/'+n for n in ('chamber.tg','shield.tg','stage.tg'))]
    key=(str(root.resolve()),tuple((ref,W.sha(root/ref)) for ref in refs))
    if key not in _MODEL_CACHE:
        _MODEL_CACHE.clear();_MODEL_CACHE[key]=query(['models'],root)
    return copy.deepcopy(_MODEL_CACHE[key])

def local_model_summaries(root=W.ROOT):
    """Browse exact local input metadata without launching WSL or a worker."""
    root=Path(root);catalog=W.read(root/'models/catalog.json');nominal=W.read(root/'transport/cryostat_nominal.json')
    # The same pure source parser owns cavity arithmetic. No YAML parser or
    # remage/Julia environment is needed to browse the existing Control form.
    transport=str(root/'transport')
    if transport not in sys.path:sys.path.insert(0,transport)
    from catalog_geometry import cavity_contract,placement_screen
    cavity=cavity_contract(root);result=[]
    for entry in catalog['detectors']:
        path=root/'models'/entry['model'];W.require(W.sha(path)==entry['model_sha256'],'Canonical browse model bytes changed.')
        match=re.search(r'^\s+temperature:\s*([0-9]+(?:\.[0-9]+)?)\s*$',path.read_text(encoding='utf-8'),re.M)
        W.require(match is not None,'Original model temperature is absent.');temperature=float(match[1])
        contacts={str(c['id']):c['potential_V'] for c in entry['contacts']};selected=contacts[str(entry['readout_contact_id'])]
        deltas=[v-selected for k,v in contacts.items() if k!=str(entry['readout_contact_id']) and v!=selected]
        W.require(deltas and (all(v>0 for v in deltas) or all(v<0 for v in deltas)),'Mixed bias levels require explicit readout wiring.')
        result.append({'model_id':entry['id'],'placement':placement_screen(entry['bounds_mm'],cavity),
            'contact_potentials_V':contacts,'readout_contact_id':entry['readout_contact_id'],'stored_temperature_K':temperature,
            'runtime_temperature_K':temperature,'bias_span_V':max(contacts.values())-min(contacts.values()),'wiring_factor':1 if deltas[0]>0 else -1})
    return result

def catalog_capabilities(root=W.ROOT,reader=local_model_summaries):
    entries=reader(root);ready=(Path(root)/EXPORTER_REF).is_file() and (Path(root)/BUILD_REF).is_file();result={}
    setup_reason='The common catalog geometry exporter must be built using the installed project runtime.'
    if ready:
        try:
            build=W.read(Path(root)/BUILD_REF);artifact=build['exporter']
            W.require(build['kind']=='catalog_exporter_build_v1' and build['status']=='complete' and artifact['ref']==EXPORTER_REF
                and artifact['sha256']==W.sha(Path(root)/EXPORTER_REF) and artifact['bytes']==(Path(root)/EXPORTER_REF).stat().st_size
                and all(W.sha(safe_path(root,ref))==digest for ref,digest in build['source_sha256'].items()),'Common exporter bytes or source build receipt changed.')
        except (W.ControlError,OSError,KeyError,ValueError) as error:
            ready=False;setup_reason='The common catalog geometry build needs repair: '+str(error)
    registry=Path(root)/'scenarios/detector-capabilities.json'
    if registry.exists():
        from catalog_geometry import CATALOG_POLICY
        W.require(W.read(registry).get('catalog_adapter')==CATALOG_POLICY,'Common catalog capability policy changed.')
    for model in entries:
        id=model['model_id'];placement=model['placement'];blocked=placement['blocking_reasons'];old=id in W.MODELS
        reasons=list(blocked)
        if not old and not reasons and not ready:reasons.append(setup_reason)
        contacts=model['contact_potentials_V'];readout=model['readout_contact_id']
        result[id]={'workflow_kind':W.KIND if old else KIND,'available':not reasons,'reason':' '.join(reasons) if reasons else None,
            'block_code':'cryostat_size' if blocked else 'setup_required' if reasons else None,'assemblies':[W.CRYOSTAT],
            'operating_label':f"Original {model['stored_temperature_K']:g} K; readout contact {readout}; bias span {model['bias_span_V']:g} V; native signed signal and fixed {model['wiring_factor']:+d} input wiring. Exact canonical model; unchanged nominal cryostat placement.",
            'parameter_summary':[{'label':'Original model temperature','value':model['stored_temperature_K'],'unit':'K'},
                {'label':'Readout contact','value':readout},{'label':'Readout contact potential','value':contacts[str(readout)],'unit':'V'},
                {'label':'Contact count','value':len(contacts)},{'label':'Bias span','value':model['bias_span_V'],'unit':'V'}],
            'checks':[{'label':'Canonical model inputs','status':'complete','detail':'Geometry, carrier model, temperature, contact voltages and selected readout are present.'},
                {'label':'Original cryostat dimensions','status':'blocked' if blocked else 'compatible_envelope','detail':' '.join(blocked) if blocked else 'Fits the fixed cavity envelope; native full overlap and shape checks are required by every run.'}]}
    return result

def check(selection,*,root=W.ROOT,allow_existing=False,validate_settings=W.settings_check,
          runtime_reader=W.runtime_identity,transport_reader=None,pin_reader=None):
    W.require(type(selection) is dict and set(selection)==W.FIELDS,'Unsupported catalog workflow configuration fields.')
    W.run_path(selection['name'],root);W.require(allow_existing or not W.run_path(selection['name'],root).exists(),'Output exists; choose a new name.')
    W.require(selection['detector'] not in W.MODELS,'This detector retains its original Control workflow.')
    W.require(selection['cryostat']==W.CRYOSTAT and selection['pose']=='nominal' and type(selection['primary_count']) is int and selection['primary_count'] in (20,500)
        and type(selection['threads']) is int and selection['threads'] in (1,2) and type(selection['seed']) is int and 0<selection['seed']<2147483647,
        'Catalog workflow uses the original nominal cryostat,20/500 initial primaries and one/two Julia threads.')
    from decay_workflow import presets,capability
    source=next((p for p in presets(root) if p['id']==selection['source']),None)
    W.require(source is not None,'Unknown source preset.')
    W.require(selection['source']==W.CS or capability(source,root) is not None,'This source retains its withheld qualification.')
    settings=validate_settings(selection['electronics'],root);W.electronics_feasibility(settings['configuration'])
    gate=settings['configuration']['peak_gate_end_ns'];W.require(gate is None or gate<=99998,'Peak gate exceeds the half-open100000 ns isolated pulse window.')
    transport=(transport_reader or (lambda config,r:query(['check','--selection-json',W.encoded(config).decode('utf-8')],r)))(selection,root)
    model=transport['model_contract'];W.require(transport['kind']=='catalog_source_checked_v1' and transport['selection']==selection and model['model_id']==selection['detector'] and not model['placement']['blocking_reasons'],'Catalog source/geometry admission mismatch.')
    pins=dict(transport['source_sha256'])
    if pin_reader:pins.update(pin_reader(selection['detector'],root))
    else:
        from decay_workflow import source_pins as scientific_sources
        pins.update(scientific_sources('SAP22',root))
        # Preserve the exact scientific helper closure already reviewed in the
        # source pipeline. Adding a model adds its exact model/include bytes.
        pins.update({name:W.sha(Path(root)/name) for name in SOURCES})
        pins[model['model_ref']]=model['model_sha256'];pins.update(model['dependencies_sha256'])
    numerics={'parcels':16,'native_seed_family':2609261,'drift_dt_ns':2,'drift_cap_ns':10000,
        'stored_temperature_K':model['stored_temperature_K'],'runtime_temperature_K':model['runtime_temperature_K'],'bias_V':model['bias_span_V'],
        'native_failure_policy':'record','models_serial':True,'stages_serial':True,'precision_bits':64,
        'min_spacing_mm':0.25,'max_spacing_mm':2,'refinement_limits':[0.2,0.1,0.05],
        'max_iterations_per_refinement':50000,'sor':1,'potential_rechecks':4}
    resolved={'selection':copy.deepcopy(selection),'profile':settings['profile'],'electronics_configuration':settings['configuration'],
        'electronics_physics_sha256':settings['physics_sha256'],'model_contract':model,'transport_plan':transport,'numerics':numerics,
        'source_position_global_mm':transport['source_position_global_mm'],'source_kind':'radioactive_decay','source_count_unit':source['count_unit'],
        'source_contract':source,'source_sha256':pins,'runtime_identity':runtime_reader(selection['threads'])}
    return {'kind':KIND,'status':'checked_configuration','science_calls':0,'resolved':resolved,'configuration_sha256':W.digest(resolved)}

def admit(plan,root=W.ROOT,*,resume=False,**readers):
    W.require(type(plan) is dict and set(plan)=={'kind','status','science_calls','resolved','configuration_sha256'} and plan['kind']==KIND and plan['status']=='checked_configuration' and type(plan['science_calls']) is int and plan['science_calls']==0,'Unsupported catalog checked plan.')
    actual=check(plan['resolved']['selection'],root=root,allow_existing=resume,**readers)
    W.require(W.encoded(plan)==W.encoded(actual),'Catalog checked plan no longer reconstructs; edited/rehashed settings or model rules are refused.')
    return actual

def source_stage(directory,stage,root=W.ROOT):
    return query(['verify','--directory','../'+W.BASE+'/'+Path(directory).name+'/transport','--stage',stage],root)

def native_request(directory,resolved,root=W.ROOT):
    base=W.BASE+'/'+Path(directory).name;profile=Path(directory)/'electronics/profile.json';stream=Path(directory)/'transport/stream/manifest.json'
    return {'kind':'catalog_native_request_v1','configuration_sha256':W.digest(resolved),'selection':resolved['selection'],'model_contract':resolved['model_contract'],
        'profile_ref':base+'/electronics/profile.json','profile_sha256':W.sha(profile),'stream_ref':base+'/transport/stream/manifest.json','stream_sha256':W.sha(stream),
        'source_sha256':resolved['source_sha256'],'numerics':resolved['numerics']}

def stage_commands(directory,resolved,root=W.ROOT):
    base='../'+W.BASE+'/'+Path(directory).name;common=command(root);identity=['--windows-root',str(Path(root).resolve())];env=W.child_env(resolved['selection']['threads'])
    return {'geometry':common+['prepare','--selection',base+'/selection.json','--checked',base+'/source-checked.json','--output',base+'/transport',*identity],
        'radiation':common+['run','--directory',base+'/transport',*identity],
        'event_ledger':common+['extract','--directory',base+'/transport',*identity],
        'response':[env['JULIA_EXE'],'--startup-file=no','--threads='+str(resolved['selection']['threads']),'--project='+str(Path(root)/'simulation'),str(Path(root)/'simulation/catalog_native_response.jl'),
            '--request',str(Path(directory)/'catalog-request.json'),'--output',str(Path(directory)/'response')]}

def validate_stage(directory,stage,resolved,root=W.ROOT,*,semantic=True):
    directory=Path(directory);s=resolved['selection'];t=directory/'transport'
    if stage in ('geometry','radiation','event_ledger'):
        if semantic:source_stage(directory,stage,root)
        prepared=W.read(t/'prepared.json');W.require(prepared['model_contract']==resolved['model_contract'] and prepared['selection']==s,'Prepared model/source selection changed.')
        if stage=='geometry':
            W.require(W.read(t/'prepare-receipt.json')['status']=='complete','Native geometry is incomplete.')
            return {n:{'sha256':W.sha(safe_path(t,n)),'bytes':safe_path(t,n).stat().st_size} for n in (*prepared['files_sha256'],'prepared.json','prepare-receipt.json')}
        run=W.read(t/'run.json');W.require(run['status']=='complete' and run['returncode']==0 and run['prepared_sha256']==W.sha(t/'prepared.json') and run['source_lh5_sha256']==W.sha(t/'truth.lh5'),'Original radiation receipt changed.')
        if stage=='radiation':return {n:{'sha256':W.sha(t/n),'bytes':(t/n).stat().st_size} for n in ('run.json','run.log','truth.lh5')}
        stream=W.read(t/'stream/manifest.json');W.require(stream['kind']=='catalog_decay_stream_v1' and stream['model_contract']==resolved['model_contract'] and stream['primary_count']==s['primary_count'],'Stream identity/census changed.')
        return W.inventory(t/'stream')
    if stage=='response':
        r=W.read(directory/'response/run.json');m=resolved['model_contract'];counts=r['counts']
        W.require(r['status'] in ('completed_provisional_native_response',*W.TERMINAL) and r['model_id']==s['detector'] and counts['initial_primaries']==s['primary_count'] and counts['accepted']+counts['rejected']==counts['groups'] and counts['rejected']==counts['native_failed_groups']+counts['readout_rejected'],'Native/readout terminal census changed.')
        W.require(r['stored_temperature_K']==m['stored_temperature_K'] and r['temperature_K']==m['runtime_temperature_K'] and r['bias_V']==m['bias_span_V'] and r['readout_contact_id']==m['readout_contact_id'] and r['calibration_calls']==1,'Native original model/readout/calibration settings changed.')
        n=resolved['numerics']
        W.require(r['numerics']==n and r['parcels']==n['parcels'] and r['seed_family']==n['native_seed_family']
            and r['drift_dt_ns']==n['drift_dt_ns'] and r['nominal_drift_cap_ns']==n['drift_cap_ns']
            and r['native_failure_policy']==n['native_failure_policy'] and r['diffusion'] is True
            and r['self_repulsion'] is False and r['end_drift_when_no_field'] is False,
            'Saved native numerical/seed/drift/failure/transport settings differ from the checked contract.')
        request=native_request(directory,resolved,root)
        W.require(r['kind']=='catalog_native_response_v1' and r['configuration_sha256']==request['configuration_sha256']
            and r['source_id']==s['source'] and r['source_contract']==resolved['source_contract'] and r['model_contract']==m
            and r['source_sha256']==resolved['source_sha256'] and r['profile_sha256']==request['profile_sha256']
            and r['input_sha256']==request['stream_sha256'] and r['source_lh5_sha256']==W.sha(t/'truth.lh5')
            and r['request_sha256']==W.sha(directory/'catalog-request.json') and W.read(directory/'catalog-request.json')==request,
            'Native response request/source/profile/stream binding changed.')
        W.require(r['contact_potentials_V']==m['contact_potentials_V'] and r['wiring_factor']==m['wiring_factor']
            and r['independent_calibration_calls']==1 and r['new_field_solution'] is True
            and counts['initial_decays']==s['primary_count'] and 0<=counts['zero_deposit_primaries']<=s['primary_count'],
            'Original contact wiring or complete initial decay/calibration census changed.')
        expected=copy.deepcopy(resolved['electronics_configuration']);expected['expected_primary_count']=s['primary_count']
        W.require(W.read(directory/'response/readout-config.json')==expected,'Generated readout config differs beyond expected_primary_count; rehashed edits are refused.')
        for name,digest in r['artifacts'].items():W.require(W.sha(safe_path(directory/'response',name))==digest,'Native response artifact changed.')
        if semantic:response_census(directory,resolved,r)
        return W.inventory(directory/'response')
    return W.inventory(directory,exclude=('run.json','COMPLETE.json','STOP.json')) if stage=='results' else {}

def execute(plan,*,root=W.ROOT,resume=False,dispatch_id=None,executor=W.command):
    return W.execute(plan,root=root,resume=resume,dispatch_id=dispatch_id,executor=executor,workflow=sys.modules[__name__])


def inspect(name,root=W.ROOT):
    directory=W.run_path(name,root);plan=W.read(directory/'resolved-config.json');receipt=W.read(directory/'run.json')
    W.require(plan['kind']==KIND and receipt['kind']==KIND and W.digest(plan['resolved'])==plan['configuration_sha256']==receipt['configuration_sha256'] and receipt['resolved']==plan['resolved'],'Saved catalog settings changed.')
    s=plan['resolved']['selection'];models={m['model_id']:m for m in model_contracts(root)};W.require(plan['resolved']['model_contract']==models[s['detector']],'Saved exact model/placement contract changed.')
    if receipt['status'] in W.TERMINAL:
        W.require(set(receipt['stages'])==set(STAGES) and all(x['status']=='completed' for x in receipt['stages'].values()),'Terminal stage census is incomplete.')
        complete=W.read(directory/'COMPLETE.json');W.require(complete['kind']==KIND and complete['status']==receipt['status'] and complete['configuration_sha256']==plan['configuration_sha256'],'Catalog completion binding changed.')
        W.verify_inventory(directory,complete['artifacts']);W.require(complete['artifacts']==W.inventory(directory,exclude=('COMPLETE.json','STOP.json')),'Completed exact artifact census changed.')
        for stage in STAGES[:-1]:validate_stage(directory,stage,plan['resolved'],root)
        receipt['verification']='terminal_artifacts_verified'
    else:receipt['verification']='nonterminal_preserved'
    return receipt

def request_stop(name,root=W.ROOT):
    directory=W.run_path(name,root);receipt=W.read(directory/'run.json');W.require(receipt['kind']==KIND and receipt['status']=='running','Catalog run is not active.')
    W.write(directory/'STOP.json',{'requested_utc':W.utc()},fresh=True);return {'status':'stop_requested'}
