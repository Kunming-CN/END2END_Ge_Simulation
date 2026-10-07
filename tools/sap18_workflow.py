"""Additive SAP18 scenario connector; frozen Ge/KM producers remain unchanged."""
from pathlib import Path
import json, math, re, sys
import scenario_workflow as W
from ring_workflow import energy_sum_matches
MODEL='SAP18_ring08_scenario'
MODEL_SHA='a4078c32a0f0c357932b12dbd7a9e719ee4aa894268b76c755bf7c3dbbb5bb09'
MODEL_REF='models/'+MODEL+'.yaml'
DEPENDENCY='models/ADLChargeDriftModel/drift_velocity_config.yaml'
DEPENDENCY_SHA='642a2bd0df1dabd9da7c71d15950e8b84f491babfd4b4fb63abdb82162f97ce6'
SOURCES=('tools/sap18_workflow.py','transport/sap18_source.py','simulation/sap18_stream.jl',
         'simulation/sap18_polarity.jl','simulation/workflow_sap18_response.jl')
def canonical(root=W.ROOT):
    root=Path(root);body=(root/MODEL_REF).read_bytes()
    W.require(W.sha(root/MODEL_REF)==MODEL_SHA and W.sha(root/DEPENDENCY)==DEPENDENCY_SHA,'SAP18 model/include bytes changed.')
    entry=next(d for d in W.read(root/'models/catalog.json')['detectors'] if d['id']==MODEL)
    W.require(entry['model_sha256']==MODEL_SHA and entry['status']=='scenario; identity unresolved' and
              [(c['id'],c['potential_V']) for c in entry['contacts']]==[(1,0),(2,-380)] and
              entry['readout_contact_id']==1,'SAP18 catalog identity/qualification/contact convention changed.')
    return body
def model_contract(ref=MODEL_REF,root=W.ROOT):
    canonical(root);W.require(ref==MODEL_REF,'SAP18 uses its unchanged original model.')
    return {'kind':'sap18_effective_model_v1','model_id':MODEL,'variant_id':MODEL,
        'qualification':'scenario; identity unresolved; nominal engineering placement',
        'source_model_ref':MODEL_REF,'source_model_sha256':MODEL_SHA,
        'effective_model_ref':MODEL_REF,'effective_model_sha256':MODEL_SHA,
        'dependencies_sha256':{DEPENDENCY:DEPENDENCY_SHA},'model_delta':None,
        'geometry_unchanged':True,'stored_temperature_K':78,'runtime_temperature_K':77,
        'runtime_temperature_policy':'explicit native-consumer override; YAML bytes retain78K',
        'annealing_temperature_K':None,'annealing_time_minutes':None,
        'readout_contact_id':1,'readout_contact_width_mm':0.8,'contact_potentials_V':{'1':0,'2':-380},
        'cache_identity':'SAP18 model SHA plus 0.8mm contact, -380V, runtime temperature and solver; no KM field reuse'}
def inputs(model=MODEL):
    import yaml
    W.require(model==MODEL,'Unsupported SAP18 identity.')
    body=canonical();doc=yaml.safe_load(body)
    km=yaml.safe_load((W.ROOT/'models/KMRC01_candidate.yaml').read_bytes())
    W.require(W.sha(W.ROOT/'models/KMRC01_candidate.yaml')=='d4258a3b9f9c041b4da1998ded6b373833169ddcc76079f0a588785efe68b6b6','Frozen geometry reference changed.')
    semi=doc['detectors'][0]['semiconductor'];contacts=doc['detectors'][0]['contacts']
    W.require(semi==km['detectors'][0]['semiconductor'] and semi['temperature']==78 and
              [(c['id'],c['potential']) for c in contacts]==[(1,0),(2,-380)] and
              contacts[0]['geometry']['tube']['h']==0.8,'SAP18 original semiconductor/contact/bias inputs changed.')
    expected=json.loads(json.dumps(km));expected['name']=MODEL
    expected['detectors'][0]['contacts'][0]['geometry']['tube']['h']=0.8
    expected['detectors'][0]['contacts'][1]['potential']=-380
    W.require(doc==expected,'SAP18 differs from its exact three-token geometry reuse proof.')
    return doc,doc,body,{DEPENDENCY:DEPENDENCY_SHA}
def operating(model=MODEL):
    W.require(model==MODEL,'Unsupported SAP18 connector.')
    c=model_contract()
    return {'variant_id':MODEL,'source_model_sha256':MODEL_SHA,'effective_model_sha256':MODEL_SHA,
        'signed_bias_V':-380,'contact_potentials_V':c['contact_potentials_V'],'readout_contact_id':1,
        'readout_contact_width_mm':0.8,'wiring_factor':-1,'field_cache_used':False,
        'annealing_time_minutes':None,'qualification':c['qualification'],
        'calibration':'independent negative500keV injection through fixed-1 SAP18 wiring'}
def validate(value):
    W.require(value==model_contract(),'SAP18 effective model contract changed.')
    return value
def prepare(model,output):
    W.require(model==MODEL,'Wrong SAP18 identity.');path=Path(output)
    W.require(not path.exists(),'Preserve prior model contract output.')
    path.mkdir(parents=True);value=model_contract()
    W.write(path/'model-contract.json',value,fresh=True);return value
def source_pins(root=W.ROOT):
    canonical(root)
    pins=W.source_pins('KMRC01_candidate',root,portable=True)
    pins.update({ref:W.sha(Path(root)/ref) for ref in (*SOURCES,MODEL_REF,DEPENDENCY)})
    return pins
def _command(root=W.ROOT):
    return ['wsl.exe','--distribution','Ubuntu-24.04','--cd',str(Path(root)/'transport'),'--exec',
            'bash','./workflow.sh','python','-B','./sap18_source.py']
def query(arguments,root=W.ROOT):
    import subprocess
    result=subprocess.run(_command(root)+arguments+['--windows-root',str(Path(root).resolve())],
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=120,shell=False,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0)
    W.require(result.returncode==0,'SAP18 preflight failed: '+result.stderr.decode('utf-8',errors='replace')[-2000:])
    return W.decode_json(result.stdout.decode('utf-8-sig'))
def portable_check(config,root=W.ROOT):
    return query(['check','--request-json',W.encoded(W.portable_request(config)).decode('utf-8')],root)
def portable_stage(directory,resolved,stage,root=W.ROOT):
    checked=resolved['portable_source_plan']
    value=query(['check','--directory','../'+W.BASE+'/'+resolved['selection']['name']+'/transport','--stage',stage],root)
    W.require(value['execution_contract']==checked['execution_contract'] and
              value['portable_source_sha256']==checked['portable_source_sha256'],'SAP18 checked stage authority changed.')
    return value
def stage_commands(directory,resolved,root=W.ROOT,environment=None):
    s=resolved['selection'];t='../'+W.BASE+'/'+s['name']+'/transport';base='../'+W.BASE+'/'+s['name']
    common=_command(root);identity=['--windows-root',str(Path(root).resolve())]
    env=environment or W.child_env(s['threads'])
    return {'geometry':common+['prepare','--request',base+'/portable-request.json','--checked-plan',base+'/portable-checked-plan.json','--output',t,*identity],
        'radiation':common+['run','--directory',t,*identity],
        'event_ledger':common+['extract','--directory',t,'--chunk-size','100',*identity],
        'response':[env['JULIA_EXE'],'--startup-file=no','--threads='+str(s['threads']),'--project='+str(Path(root)/'simulation'),
            str(Path(root)/'simulation/workflow_sap18_response.jl'),'--request',str(directory/'sap18-request.json'),'--output',str(directory/'response')]}
def prepared(directory,resolved,root=W.ROOT,*,historical=False):
    t=Path(directory)/'transport';p=W.read(t/'prepared.json')
    s=resolved['selection'];W.require(s['detector']==MODEL and s['source']==W.CS,'Unsupported SAP18 source.')
    W.require(p['kind']=='sap18_cs137_prepared_v1' and p['model_id']==MODEL and p['model_contract']==model_contract() and
              p['primary_count']==s['primary_count'] and p['seed']==s['seed'] and p['source_position_global_mm']==[0,37.073,0.290],
              'SAP18 preparation differs from selected model/count/source.')
    W.require(resolved['operating_model']==operating(),'SAP18 signed operating/readout identity changed.')
    portable_stage(directory,resolved,'geometry',root);return p
def ledger(directory,resolved,root=W.ROOT,*,historical=False):
    prepared(directory,resolved,root,historical=historical);portable_stage(directory,resolved,'event_ledger',root)
    t=Path(directory)/'transport';m=W.read(t/'stream/manifest.json');events=[]
    for c in m['chunks']:
        events.extend(W.decode_json(v) for v in W.safe_path(t/'stream',c['file']).read_text(encoding='utf-8').splitlines())
    W.require([e['event_id'] for e in events]==list(range(resolved['selection']['primary_count'])),'SAP18 lost initial IDs.')
    return events
def request(directory,resolved,root=W.ROOT,*,historical=False):
    ledger(directory,resolved,root,historical=historical);base=Path(directory)
    return {'kind':'workflow_sap18_request_v1','configuration_sha256':W.digest(resolved),
        'selection':resolved['selection'],'operating_model':resolved['operating_model'],
        'profile_ref':(base/'electronics/profile.json').relative_to(root).as_posix(),
        'profile_sha256':W.sha(base/'electronics/profile.json'),
        'stream_ref':(base/'transport/stream/manifest.json').relative_to(root).as_posix(),
        'stream_sha256':W.sha(base/'transport/stream/manifest.json'),
        'source_sha256':resolved['source_sha256'],'numerics':resolved['numerics']}
def response(directory,resolved,report,root=W.ROOT,*,historical=False):
    base=Path(directory);out=base/'response';actual=W.read(base/'sap18-request.json')
    W.require(actual==request(directory,resolved,root,historical=historical),'SAP18 request differs from source authority.')
    envelope=W.read(out/'workflow-sap18-response.json')
    W.require(report['configuration_sha256']==W.digest(resolved) and report['request_sha256']==W.sha(base/'sap18-request.json') and
        report['model_contract']==model_contract() and report['signed_operating_bias_V']==-380 and report['wiring_factor']==-1 and
        report['contact_potentials_V']=={'1':0,'2':-380} and report['new_field_solution'] is True and
        report['geometry_checks']['field_cache_used'] is False and report['independent_calibration_calls']==1 and
        envelope['native_report_sha256']==W.sha(out/'run.json') and envelope['configuration_sha256']==W.digest(resolved) and
        envelope['counts']==report['counts'],'SAP18 field/wiring/calibration/envelope identity changed.')
    c=report['calibration'];inj=W.read(out/'negative-injection.json')
    W.require(c['energy_keV']==500 and c['raw_charge_C']<0 and c['charge_C']==c['electronics_input_charge_C']==-c['raw_charge_C'] and
        c['wiring_factor']==-1 and c['time_step_ns']==2 and inj['calibration']==c and inj['wiring']['model_id']==MODEL and
        inj['input_is_independent_of_event_truth'] is True and
        math.isclose(c['charge_C'],500000/c['ionisation_energy_eV']*1.602176634e-19,rel_tol=1e-12) and
        math.isclose(c['volts_per_keV'],c['peak_V']/500,rel_tol=1e-12),'SAP18 requires one independent negative injection.')
    truths=[W.decode_json(v) for v in (out/'truth.jsonl').read_text(encoding='utf-8').splitlines()]
    records=[W.decode_json(v) for v in (out/'scalars.jsonl').read_text(encoding='utf-8').splitlines()]
    primaries=[r for r in records if r['record_kind']=='decay'];pulses=[r for r in records if r['record_kind']=='pulse']
    W.require(len(primaries)==len(truths)==resolved['selection']['primary_count'],'SAP18 response census mismatch.')
    expected={(e['event_id'],g['group_id']):(e,g) for e in truths for g in e['pulse_groups']}
    W.require(len(pulses)==len(expected) and {(p['event_id'],p['group_id']) for p in pulses}==set(expected),'SAP18 group identity census changed.')
    for p,e in zip(primaries,truths):
        W.require(p['event_id']==p['global_decay_id']==e['event_id'] and p['zero_deposit']==all(v['energy_keV']==0 for v in e['steps']) and
            energy_sum_matches(p['deposited_energy_keV'],(v['energy_keV'] for v in e['steps'])) and
            p['raw_row_indices']==[v['raw_row_index'] for v in e['steps']],'SAP18 primary truth changed.')
    for p in pulses:
        e,g=expected[(p['event_id'],p['group_id'])];byrow={r['raw_row_index']:r for r in e['steps']}
        W.require(p['group']==g and p['origin_time_ns']==g['origin_time_ns'] and p['raw_row_indices']==g['row_indices'] and
            energy_sum_matches(p['deposited_energy_keV'],(byrow[i]['energy_keV'] for i in g['row_indices'])),'SAP18 pulse truth/time changed.')
        if p.get('status')=='native_transport_failed':
            W.require(p['accepted'] is False and all(p[k] is None for k in ('readout','final_induced_keV','transport_flags','charge_end_ns',
                'native_any_negative_charge','native_min_charge_keV','native_max_charge_keV','endpoints','current_nA','induced_charge_fC')),'SAP18 native failure invented quantities.')
        else:
            r=p['readout'];W.require(r['wiring']['factor']==-1 and r['wiring']['model_id']==MODEL and
                r['raw_native_final_charge_keV']==p['final_induced_keV'] and r['raw_native_min_charge_keV']==p['native_min_charge_keV'] and
                r['raw_native_max_charge_keV']==p['native_max_charge_keV'],'SAP18 scalar lost raw native signs.')
    for line in (out/'traces.jsonl').read_text(encoding='utf-8').splitlines():
        t=W.decode_json(line)['trace']
        W.require(t['raw_native_induced_charge_fC']==[-v for v in t['induced_charge_fC']] and
                  t['raw_native_current_nA']==[-v for v in t['current_nA']],'SAP18 trace signs or fixed wiring changed.')
    return report
