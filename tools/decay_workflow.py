"""Shared new-isotope Control contract; original Cs/gamma producers stay unchanged."""
from pathlib import Path
import math, re, subprocess, sys
import scenario_workflow as W
from ring_workflow import energy_sum_matches
REGISTRY='scenarios/source-presets.json'
ANCHORS='scenarios/placement-anchors.json'
ADAPTER='shared_decay_source_v1'
SOURCES=(REGISTRY,ANCHORS,'tools/decay_workflow.py','transport/decay_source.py',
         'simulation/decay_stream.jl','simulation/workflow_decay_response.jl')
POLICY={'primary_threshold_ns':1e27,'reset_initial_children_to_zero':True,
        'ground_secondary_lifetime_cap_ns':100000,'nucleus_limits':'unrestricted_default',
        'initial_nucleus_count_per_event':1}
HEX=re.compile('[0-9a-f]{64}\\Z')
def presets(root=W.ROOT):
    value=W.read(Path(root)/REGISTRY)
    W.require(set(value)=={'kind','schema_version','presets'} and value['kind']=='radioactive_source_presets_v1' and
              value['schema_version']==1 and type(value['presets']) is list,'Unsupported source registry.')
    items=value['presets'];W.require(len({p['id'] for p in items})==len(items),'Duplicate source preset.')
    for p in items:
        if p['adapter']==ADAPTER:validate_source(p)
    return items
def is_source(source_id,root=W.ROOT):
    return any(p['id']==source_id and p['adapter']==ADAPTER for p in presets(root))
def preset(source_id,root=W.ROOT):
    value=next((p for p in presets(root) if p['id']==source_id and p['adapter']==ADAPTER),None)
    W.require(value is not None,'No shared decay source preset.');return value
def validate_source(p):
    for key in ('Z','A','daughter_Z','daughter_A'):
        W.require(type(p[key]) is int and p[key]>0,'Invalid isotope identity.')
    W.require(p['pdg']==1000000000+p['Z']*10000+p['A']*10 and
        p['ground_daughter_pdg']==1000000000+p['daughter_Z']*10000+p['daughter_A']*10 and
        p['nuclear_policy']==POLICY and p['generator']=='GPS_ion_at_rest' and
        p['primary_excitation_keV']==p['kinetic_energy_keV']==0 and p['direction_global'] is None and
        p['pose']=='nominal' and p['counts']==[20,500] and p['position_global_mm']==[0,37.073,.290] and
        p['units']=={'energy':'keV','length':'mm','time':'ns'},'Shared source physics/pose policy changed.')
    W.require(p['decay_mode'] in ('alpha','beta_minus','electron_capture') and
        p['allowed_light_nuclear_pdgs']==([1000020040] if p['decay_mode']=='alpha' else []),
        'Unsupported nuclear decay/product policy.')
    lines=p['diagnostic_lines']
    W.require(type(lines) is list and lines and len({x['name'] for x in lines})==len(lines) and
        all(set(x)=={'name','window_keV'} and len(x['window_keV'])==2 and
            all(type(v) in (int,float) and math.isfinite(v) for v in x['window_keV']) and
            0<x['window_keV'][0]<x['window_keV'][1] for x in lines),'Invalid photon diagnostic windows.')
    files=p['required_data_sha256']
    W.require(set(files)=={'G4RADIOACTIVEDATA','G4LEVELGAMMADATA','G4ENSDFSTATEDATA'} and
        all(v and all(type(n) is str and Path(n).name==n and HEX.fullmatch(h) for n,h in v.items()) for v in files.values()),
        'Missing source dataset bindings.')
    return p
def anchors(root=W.ROOT):
    root=Path(root);a=W.read(root/ANCHORS);original=W.read(root/a['original_geometry_ref'])
    W.require(a['kind']=='nominal_placement_anchors_v1' and a['schema_version']==1 and a['cryostat_id']==W.CRYOSTAT and
        a['original_geometry_ref']=='transport/cryostat_nominal.json' and W.sha(root/a['original_geometry_ref'])==a['original_geometry_sha256'] and
        a['upstream_manifest_ref']=='transport/cryostat-source.json' and W.sha(root/a['upstream_manifest_ref'])==a['upstream_manifest_sha256'],
        'Shared anchor original binding changed.')
    keys=('coordinate_transform','expected_vacuum_global_translation_mm','crystal_in_vacuum_translation_mm',
          'spacer','capsule','upstream_chain','upstream_entry','overlap_samples')
    W.require(all(a[k]==original[k] for k in keys) and a['source_pose']['position_global_mm']==original['source']['position_global_mm'] and
        a['source_pose']['id']=='nominal' and a['source_pose']['distribution']=='point' and a['capsule']['axis_global']==[0,1,0],
        'Anchor dimensions/placement/materials differ from supported frozen exporter.')
    return a
def model_contract(model,ref=None,root=W.ROOT):
    W.require(model in W.MODELS,'Unsupported shared detector.')
    if model==W.SAP18:
        from sap18_workflow import model_contract as contract
        return contract(root=root)
    if model in W.RINGS:
        from ring_workflow import model_contract as contract
        W.require(ref is not None or model!='GeRC02','GeRC requires its per-run effective model ref.')
        return contract(model,ref or 'models/'+model+'.yaml')
    root=Path(root);entry=next(d for d in W.read(root/'models/catalog.json')['detectors'] if d['id']==model)
    source_ref='models/'+entry['model'];deps={'models/'+r:next(d['sha256'] for d in W.read(root/'models/catalog.json')['dependencies'] if d['path']==r) for r in entry['dependencies']}
    W.require(W.sha(root/source_ref)==entry['model_sha256'] and all(W.sha(root/r)==h for r,h in deps.items()),'Canonical detector/include changed.')
    signed={'AK02':500,'SAP22':700}[model]
    return {'kind':'canonical_effective_model_v1','model_id':model,'variant_id':model,
        'qualification':entry['status']+'; nominal engineering placement',
        'source_model_ref':source_ref,'source_model_sha256':entry['model_sha256'],
        'effective_model_ref':source_ref,'effective_model_sha256':entry['model_sha256'],
        'dependencies_sha256':deps,'model_delta':None,'geometry_unchanged':True,
        'stored_temperature_K':78,'runtime_temperature_K':77,
        'runtime_temperature_policy':'explicit native-consumer override; YAML bytes retain78K',
        'annealing_temperature_K':None,'annealing_time_minutes':None,'readout_contact_id':1,
        'readout_contact_width_mm':None,'contact_potentials_V':{'1':0,'2':signed},
        'cache_identity':'canonical-model SHA plus runtime temperature, bias and solver; fresh own fields'}
def operating(model,root=W.ROOT):
    if model==W.SAP18:
        from sap18_workflow import operating as op
        return op()
    if model in W.RINGS:
        from ring_workflow import operating as op
        return op(model)
    c=model_contract(model,root=root)
    return {'variant_id':model,'source_model_sha256':c['source_model_sha256'],
        'effective_model_sha256':c['effective_model_sha256'],'signed_bias_V':c['contact_potentials_V']['2'],
        'contact_potentials_V':c['contact_potentials_V'],'readout_contact_id':1,'wiring_factor':1,
        'field_cache_used':False,'annealing_time_minutes':None,'qualification':c['qualification'],
        'calibration':'independent positive500keV injection'}
def prepare_model(model,output):
    if model in W.RINGS:
        from ring_model_contract import prepare
        return prepare(model,output)
    path=Path(output);W.require(not path.exists(),'Model contract output exists.');path.mkdir(parents=True)
    c=model_contract(model);W.write(path/'model-contract.json',c,fresh=True);return c
def expected_acceptance(p,value):
    keys={'status','detector','primary_count','seed','accepted_groups','native_failed_groups','readout_rejected',
          'saturated_groups','configuration_sha256','complete_sha256','source_contract_sha256','run_ref'}
    return (type(value) is dict and set(value)==keys and value['status']=='accepted' and
        value['detector']=='SAP22' and type(value['primary_count']) is int and value['primary_count']==500 and
        type(value['seed']) is int and value['seed']==26092631 and type(value['accepted_groups']) is int and value['accepted_groups']>0 and
        all(type(value[k]) is int and value[k]==0 for k in ('native_failed_groups','readout_rejected','saturated_groups')) and
        all(type(value[k]) is str and HEX.fullmatch(value[k]) for k in ('configuration_sha256','complete_sha256','source_contract_sha256')) and
        value['source_contract_sha256']==W.digest(p) and value['run_ref']==W.BASE+'/source-'+p['isotope'].lower()+'-500-v1')
def capability(p,root=W.ROOT):
    v=W.read(Path(root)/'scenarios/detector-capabilities.json').get('source_adapters',{}).get(p['id'])
    if v is None:return None
    W.require(type(v) is dict and set(v)=={'adapter','detectors','counts','pose','acceptance'} and v['adapter']==ADAPTER and
        v['detectors']==list(W.MODELS) and v['counts']==p['counts'] and v['pose']==p['pose'] and
        expected_acceptance(p,v['acceptance']),'Source capability lacks genuine bounded acceptance metadata.')
    return v
def source_catalog(root=W.ROOT):
    result=[]
    for p in presets(root):
        c=capability(p,root) if p['adapter']==ADAPTER else None
        available=p['adapter']!=ADAPTER or c is not None
        result.append({k:p[k] for k in ('id','label','pose','pose_label','counts','count_unit','position_global_mm','fixed_seed','details')} |
          {'available':available,'reason':None if available else 'Source-specific 500-primary acceptance is pending.',
           'source_contract':p,'acceptance':None if c is None else c['acceptance']})
    return result
def numerics(model):
    return {'parcels':16,'native_seed_family':2609261,'drift_dt_ns':2,'drift_cap_ns':10000,
        'stored_temperature_K':78,'runtime_temperature_K':77,
        'bias_V':{'AK02':500,'SAP22':700,'GeRC02':240,'KMRC01_candidate':370,W.SAP18:380}[model],
        'native_failure_policy':'record','models_serial':True,'stages_serial':True}
def source_pins(detector,root=W.ROOT):
    pins=W.source_pins(detector,root,portable=True)
    names=(*SOURCES,'tools/ring_workflow.py','tools/ring_model_contract.py','tools/sap18_workflow.py',
        'transport/ring_cs137.py','transport/sap18_source.py','simulation/workflow_ring_response.jl',
        'simulation/ring_stream.jl','simulation/ring_response.jl','simulation/ring_polarity.jl',
        'simulation/sap18_stream.jl','simulation/sap18_polarity.jl')
    pins.update({r:W.sha(Path(root)/r) for r in names});return pins
def _command(root=W.ROOT):
    return ['wsl.exe','--distribution','Ubuntu-24.04','--cd',str(Path(root)/'transport'),'--exec',
            'bash','./workflow.sh','python','-B','./decay_source.py']
def query(args,root=W.ROOT):
    r=subprocess.run(_command(root)+args+['--windows-root',str(Path(root).resolve())],
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=120,shell=False,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0)
    W.require(r.returncode==0,'Shared decay source check failed: '+r.stderr.decode('utf-8',errors='replace')[-2000:])
    return W.decode_json(r.stdout.decode('utf-8-sig'))
def portable_check(config,root=W.ROOT):
    return query(['check','--request-json',W.encoded(W.portable_request(config)).decode('utf-8')],root)
def check(config,*,root=W.ROOT,validate_settings=W.settings_check,pin_reader=None,runtime_reader=W.runtime_identity,
          portable_reader=None,allow_existing=False,bootstrap_source=False):
    W.require(type(config) is dict and set(config)==W.FIELDS,'Unsupported configuration fields.')
    W.run_path(config['name'],root)
    W.require(config['cryostat']==W.CRYOSTAT and config['detector'] in W.MODELS,'Unsupported detector/cryostat.')
    p=preset(config['source'],root);a=anchors(root);c=capability(p,root)
    W.require(c is not None or bootstrap_source is True,'This source has not passed its acceptance yet.')
    W.require(config['pose']=='nominal' and type(config['primary_count']) is int and config['primary_count'] in p['counts'] and
        type(config['threads']) is int and config['threads'] in (1,2) and type(config['seed']) is int and
        0<config['seed']<2147483647,'Unsupported source pose/count/seed/thread selection.')
    W.require(allow_existing or not W.run_path(config['name'],root).exists(),'Output exists; choose a new name.')
    v=validate_settings(config['electronics'],root);W.electronics_feasibility(v['configuration'])
    gate=v['configuration']['peak_gate_end_ns'];W.require(gate is None or gate<=99998,'Peak gate exceeds half-open100us window.')
    r={'selection':config,'profile':v['profile'],'electronics_configuration':v['configuration'],
       'electronics_physics_sha256':v['physics_sha256'],'source_position_global_mm':a['source_pose']['position_global_mm'],
       'source_kind':'radioactive_decay','source_count_unit':p['count_unit'],'decay_source_contract':p,
       'placement_contract':a,'operating_model':operating(config['detector'],root),'numerics':numerics(config['detector']),
       'source_sha256':pin_reader(config['detector'],root) if pin_reader else source_pins(config['detector'],root),
       'runtime_identity':runtime_reader(config['threads'])}
    portable=(portable_reader or portable_check)(config,root)
    W.require(type(portable) is dict and portable['kind']=='decay_source_checked_plan_v1' and portable['schema_version']==1 and
        portable['request']==W.portable_request(config) and portable['source_contract']==p and portable['placement_contract']==a,
        'Shared portable Check identity changed.')
    r['portable_source_plan']=portable;r['source_sha256'].update(portable['portable_source_sha256'])
    return {'kind':W.KIND,'status':'checked_configuration','science_calls':0,'resolved':r,'configuration_sha256':W.digest(r)}
def saved_plan(plan,root=W.ROOT):
    W.require(type(plan) is dict and set(plan)=={'kind','status','science_calls','resolved','configuration_sha256'} and
        plan['kind']==W.KIND and plan['status']=='checked_configuration' and type(plan['science_calls']) is int and
        plan['science_calls']==0 and W.digest(plan['resolved'])==plan['configuration_sha256'],'Saved decay plan authority changed.')
    r=plan['resolved'];s=r['selection'];W.run_path(s['name'],root);p=preset(s['source'],root)
    W.require(set(s)==W.FIELDS and s['detector'] in W.MODELS and s['cryostat']==W.CRYOSTAT and
        s['pose']=='nominal' and type(s['primary_count']) is int and s['primary_count'] in p['counts'] and
        type(s['threads']) is int and s['threads'] in (1,2) and type(s['seed']) is int and 0<s['seed']<2147483647 and
        r['decay_source_contract']==p and r['placement_contract']==anchors(root) and r['operating_model']==operating(s['detector'],root) and
        r['source_kind']=='radioactive_decay' and r['source_count_unit']==p['count_unit'] and
        r['source_position_global_mm']==p['position_global_mm'] and r['numerics']==numerics(s['detector']),
        'Saved isotope/model/pose/numerics changed.')
    e=s['electronics'];profile=r['profile'];c=r['electronics_configuration']
    W.require(set(e)==set(W.SETTINGS) and profile=={'schema_version':2,'kind':'native_readout_profile_v1','name':profile['name'],'settings':e} and
        type(profile['name']) is str and re.fullmatch('[A-Za-z0-9_.-]{1,80}',profile['name']) and
        e['peak_policy'] in ('signed_input_positive_peak','legacy_reject_negative_input') and
        all(type(v) in (int,float) and math.isfinite(v) for k,v in e.items() if k!='peak_policy' and v is not None) and
        all(e[k] is not None and e[k]>0 for k in ('shaping_tau_us','gain','adc_full_scale_V','feedback_capacitance_pF','feedback_tau_us','pole_zero_tau_us')) and
        type(e['adc_bits']) is int and 2<=e['adc_bits']<=24 and e['threshold_V'] is not None and 0<e['threshold_V']<e['adc_full_scale_V'],
        'Saved electronics profile invalid.')
    fixed={'schema_version':2,'calibration_energy_keV':500,'expected_primary_count':None,'max_samples_per_event':500000,
           'max_window_ns':1000000,'require_all_events':True,'tail_shaping_constants':20,'trace_max_points':600}
    W.require(set(c)==set(W.SETTINGS)|set(fixed) and all(c[k]==e[k] for k in W.SETTINGS) and
        all(c[k]==v for k,v in fixed.items()),'Saved electronics configuration changed.')
    W.electronics_feasibility(c)
    gate=c['peak_gate_end_ns'];W.require(gate is None or gate<=99998,'Saved peak gate exceeds horizon.')
    W.require(r['source_sha256'] and all(type(h) is str and HEX.fullmatch(h) for h in r['source_sha256'].values()) and
        all(type(r['runtime_identity'][k]) is str and HEX.fullmatch(r['runtime_identity'][k]) for k in ('python_sha256','julia_sha256')),
        'Saved source/runtime identity incomplete.')
    portable=r['portable_source_plan'];W.require(portable['kind']=='decay_source_checked_plan_v1' and
        portable['request']==W.portable_request(s) and portable['source_contract']==p and portable['placement_contract']==r['placement_contract'],
        'Saved portable source tuple changed.')
    return plan
def admit(plan,root=W.ROOT,*,resume=False,bootstrap_source=False):
    saved_plan(plan,root);actual=check(plan['resolved']['selection'],root=root,allow_existing=resume,bootstrap_source=bootstrap_source)
    W.require(W.encoded(actual)==W.encoded(plan),'Checked decay plan no longer reconstructs.');return actual
def portable_stage(directory,resolved,stage,root=W.ROOT):
    checked=resolved['portable_source_plan'];t=Path(directory)/'transport'
    if stage=='radiation' and (t/'stream/manifest.json').is_file():stage='event_ledger'
    value=query(['check','--directory','../'+W.BASE+'/'+resolved['selection']['name']+'/transport','--stage',stage],root)
    for k in ('execution_contract','portable_source_sha256','source_contract','placement_contract'):
        W.require(value[k]==checked[k],'Shared checked stage changed: '+k)
    return value
def stage_commands(directory,resolved,root=W.ROOT,environment=None):
    s=resolved['selection'];base='../'+W.BASE+'/'+s['name'];t=base+'/transport';common=_command(root)
    identity=['--windows-root',str(Path(root).resolve())];env=environment or W.child_env(s['threads'])
    return {'geometry':common+['prepare','--request',base+'/portable-request.json','--checked-plan',base+'/portable-checked-plan.json','--output',t,*identity],
        'radiation':common+['run','--directory',t,*identity],
        'event_ledger':common+['extract','--directory',t,'--chunk-size','100',*identity],
        'response':[env['JULIA_EXE'],'--startup-file=no','--threads='+str(s['threads']),'--project='+str(Path(root)/'simulation'),
            str(Path(root)/'simulation/workflow_decay_response.jl'),'--request',str(Path(directory)/'decay-request.json'),'--output',str(Path(directory)/'response')]}
def prepared(directory,resolved,root=W.ROOT,*,historical=False):
    portable_stage(directory,resolved,'geometry',root);t=Path(directory)/'transport';p=W.read(t/'prepared.json');s=resolved['selection']
    ref=W.BASE+'/'+s['name']+'/transport/effective-model/GeRC02.yaml' if s['detector']=='GeRC02' else None
    W.require(p['kind']=='decay_source_prepared_v1' and p['producer_adapter']==ADAPTER and
        p['model_id']==s['detector'] and p['model_contract']==model_contract(s['detector'],ref,root) and
        p['source_contract']==resolved['decay_source_contract'] and p['placement_contract']==resolved['placement_contract'] and
        p['primary_count']==s['primary_count'] and p['seed']==s['seed'] and p['source_position_global_mm']==resolved['source_position_global_mm'],
        'Prepared isotope/model/count/seed/pose changed.')
    W.require(W.read(t/'prepare-receipt.json')['status']=='complete','Preparation did not complete.')
    return p
def ledger(directory,resolved,root=W.ROOT,*,historical=False):
    portable_stage(directory,resolved,'event_ledger',root);t=Path(directory)/'transport';m=W.read(t/'stream/manifest.json')
    W.require(m['kind']=='radioactive_decay_stream_v1' and m['producer_adapter']==ADAPTER and
        m['source_contract']==resolved['decay_source_contract'],'Wrong decay ledger.')
    events=[]
    for c in m['chunks']:
        W.require(W.sha(W.safe_path(t/'stream',c['file']))==c['sha256'],'Changed source chunk.')
        rows=[W.decode_json(v) for v in W.safe_path(t/'stream',c['file']).read_text(encoding='utf-8').splitlines()]
        W.require(len(rows)==c['count'],'Truncated source chunk.');events.extend(rows)
    W.require([e['event_id'] for e in events]==list(range(resolved['selection']['primary_count'])),'Lost initial primary IDs.')
    return events
def request(directory,resolved,root=W.ROOT,*,historical=False):
    ledger(directory,resolved,root,historical=historical);base=Path(directory)
    return {'kind':'workflow_decay_request_v1','configuration_sha256':W.digest(resolved),'selection':resolved['selection'],
        'operating_model':resolved['operating_model'],'source_id':resolved['selection']['source'],'source_contract':resolved['decay_source_contract'],
        'profile_ref':(base/'electronics/profile.json').relative_to(root).as_posix(),'profile_sha256':W.sha(base/'electronics/profile.json'),
        'stream_ref':(base/'transport/stream/manifest.json').relative_to(root).as_posix(),'stream_sha256':W.sha(base/'transport/stream/manifest.json'),
        'source_sha256':resolved['source_sha256'],'numerics':resolved['numerics']}
def response(directory,resolved,report,root=W.ROOT,*,historical=False):
    base=Path(directory);out=base/'response';actual=W.read(base/'decay-request.json')
    W.require(actual==request(directory,resolved,root,historical=historical),'Response request authority changed.')
    env=W.read(out/'workflow-decay-response.json');p=W.read(base/'transport/prepared.json');op=resolved['operating_model']
    W.require(report['kind']=='workflow_decay_native_response_v1' and report['configuration_sha256']==W.digest(resolved) and
        report['request_sha256']==W.sha(base/'decay-request.json') and env['kind']=='workflow_decay_response_v1' and
        env['native_report_sha256']==W.sha(out/'run.json') and env['counts']==report['counts'] and
        env['configuration_sha256']==W.digest(resolved) and env['request_sha256']==report['request_sha256'] and
        env['source_sha256']==actual['source_sha256'] and env['source_contract']==report['source_contract']==resolved['decay_source_contract'] and
        env['source_id']==report['source_id']==resolved['selection']['source'] and
        env['model_contract']==report['model_contract']==p['model_contract'],'Shared response source/model envelope changed.')
    W.require(report['signed_operating_bias_V']==env['signed_operating_bias_V']==op['signed_bias_V'] and
        report['wiring_factor']==env['wiring_factor']==op['wiring_factor'] and report['contact_potentials_V']==op['contact_potentials_V'] and
        report['new_field_solution'] is env['new_field_solution'] is True and report['geometry_checks']['field_cache_used'] is False and
        report['independent_calibration_calls']==env['independent_calibration_calls']==1,'Own fields/wiring/calibration policy changed.')
    cal=report['calibration'];W.require(cal==env['calibration'] and cal['energy_keV']==500 and cal['time_step_ns']==2 and
        all(type(cal[k]) in (int,float) and math.isfinite(cal[k]) and cal[k]>0 for k in ('ionisation_energy_eV','charge_C','peak_V','volts_per_keV')) and
        math.isclose(cal['charge_C'],500000/cal['ionisation_energy_eV']*1.602176634e-19,rel_tol=1e-12) and
        math.isclose(cal['volts_per_keV'],cal['peak_V']/500,rel_tol=1e-12),'Independent injection invalid.')
    if op['wiring_factor']==-1:
        inj=W.read(out/'negative-injection.json')
        W.require(cal['raw_charge_C']<0 and cal['electronics_input_charge_C']==cal['charge_C']==-cal['raw_charge_C'] and
            cal['wiring_factor']==-1 and inj['calibration']==cal and inj['input_is_independent_of_event_truth'] is True,
            'Negative wiring lost independent signed injection.')
    else:W.require(not (out/'negative-injection.json').exists(),'Positive detector has unexpected negative injection.')
    source=ledger(directory,resolved,root,historical=historical)
    truths=[W.decode_json(v) for v in (out/'truth.jsonl').read_text(encoding='utf-8').splitlines()]
    W.require(source==truths,'Native response changed source truth.')
    rows=[W.decode_json(v) for v in (out/'scalars.jsonl').read_text(encoding='utf-8').splitlines()]
    primaries=[v for v in rows if v['record_kind']=='decay'];pulses=[v for v in rows if v['record_kind']=='pulse']
    W.require([v['event_id'] for v in primaries]==list(range(len(source))) and len(primaries)==resolved['selection']['primary_count'],
        'Response lost zero or nonzero primaries.')
    expected={(e['event_id'],g['group_id']):(e,g) for e in source for g in e['pulse_groups']}
    W.require(len(pulses)==len(expected) and {(v['event_id'],v['group_id']) for v in pulses}==set(expected),'Pulse identity changed.')
    for v,e in zip(primaries,source):
        W.require(v['global_decay_id']==e['global_decay_id'] and v['zero_deposit']==all(s['energy_keV']==0 for s in e['steps']) and
            energy_sum_matches(v['deposited_energy_keV'],(s['energy_keV'] for s in e['steps'])) and
            v['raw_row_indices']==[s['raw_row_index'] for s in e['steps']] and v['pulse_count']==len(e['pulse_groups']),
            'Response primary truth changed.')
    for v in pulses:
        e,g=expected[(v['event_id'],v['group_id'])];byrow={s['raw_row_index']:s for s in e['steps']}
        W.require(v['group']==g and v['origin_time_ns']==g['origin_time_ns'] and v['raw_row_indices']==g['row_indices'] and
            energy_sum_matches(v['deposited_energy_keV'],(byrow[i]['energy_keV'] for i in g['row_indices'])),'Pulse truth/time changed.')
        if v['status']=='native_transport_failed':
            W.require(v['accepted'] is False and all(v[k] is None for k in ('readout','final_induced_keV','transport_flags','charge_end_ns',
                'native_any_negative_charge','native_min_charge_keV','native_max_charge_keV','endpoints','current_nA','induced_charge_fC')),
                'Native failure invented charge/readout quantities.')
        elif op['wiring_factor']==-1:
            r=v['readout'];W.require(r['wiring']['factor']==-1 and r['wiring']['model_id']==resolved['selection']['detector'] and
                r['raw_native_final_charge_keV']==v['final_induced_keV'],'Negative readout lost native signed signal.')
    if op['wiring_factor']==-1:
        for line in (out/'traces.jsonl').read_text(encoding='utf-8').splitlines():
            t=W.decode_json(line)['trace'];W.require(t['raw_native_induced_charge_fC']==[-v for v in t['induced_charge_fC']] and
                t['raw_native_current_nA']==[-v for v in t['current_nA']],'Native trace signs changed.')
    return report
