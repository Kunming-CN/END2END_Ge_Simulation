"""Closed fresh-Control ring bindings; historical campaign APIs stay unchanged."""
import importlib
import math
from pathlib import Path
import re
import sys

import scenario_workflow as W
import ring_model_contract as M

MODELS=tuple(M.PINS)
LABELS={'GeRC02':'GeRC02 · single ring · Li50min · +240 V',
        'KMRC01_candidate':'KMRC01 candidate · single ring · −370 V · fixed −1 wiring'}


def energy_sum_matches(actual,values):
    """Aggregation rounding only; raw deposit values remain exactly bound."""
    values=list(values)
    W.require(type(actual) in (int,float) and math.isfinite(actual) and actual>=0 and
              all(type(v) in (int,float) and math.isfinite(v) and v>=0 for v in values),
              'Invalid finite nonnegative deposited-energy aggregate.')
    target=math.fsum(values)
    W.require(math.isfinite(target),'Deposited-energy aggregate overflow.')
    # Nonnegative n-term reductions can differ across Julia/Python reduction
    # orders. This is a row-count ULP budget, not a physical energy tolerance.
    return actual==0 if target==0 else abs(actual-target)<=max(1,len(values))*math.ulp(target)


def canonical_bytes(model):
    # The existing Windows UI Python has no YAML dependency. This reader admits
    # only the exact two frozen snapshots, not arbitrary YAML/model changes.
    W.require(model in MODELS,'Unsupported fresh ring model.')
    catalog=W.read(W.ROOT/'models/catalog.json');entry=next(d for d in catalog['detectors'] if d['id']==model)
    body=(W.ROOT/('models/'+model+'.yaml')).read_bytes()
    W.require(M.digest(body)==entry['model_sha256']==M.PINS[model] and entry['model']==model+'.yaml','Frozen ring model bytes changed.')
    deps={'models/'+ref:next(d['sha256'] for d in catalog['dependencies'] if d['path']==ref) for ref in entry['dependencies']}
    W.require(all(W.sha(W.safe_path(W.ROOT,ref))==h for ref,h in deps.items()),'Ring model dependency changed.')
    if model=='GeRC02':
        W.require(body.count(M.DELTA_FROM)==1 and M.DELTA_TO not in body,'Li-time delta is not unique.')
        body=body.replace(M.DELTA_FROM,M.DELTA_TO,1)
    return body,deps


def model_contract(model,ref):
    body,deps=canonical_bytes(model)
    return {'kind':'ring_effective_model_v1','model_id':model,'variant_id':'GeRC02_Li50min' if model=='GeRC02' else model,
        'qualification':'nominal engineering example; not calibrated Li CCE' if model=='GeRC02' else 'candidate; ring-width match',
        'source_model_ref':'models/'+model+'.yaml','source_model_sha256':M.PINS[model],
        'effective_model_ref':ref,'effective_model_sha256':M.digest(body),'dependencies_sha256':deps,
        'model_delta':{'path':'detectors[0].semiconductor.impurity_density.lithium_annealing_time','from':'30minute','to':'50minute'} if model=='GeRC02' else None,
        'geometry_unchanged':True,'stored_temperature_K':78,'runtime_temperature_K':77,
        'runtime_temperature_policy':'explicit native-consumer override; YAML bytes retain 78 K',
        'annealing_temperature_K':553.15 if model=='GeRC02' else None,'annealing_time_minutes':50 if model=='GeRC02' else None,
        'readout_contact_id':1,'contact_potentials_V':{'1':0,'2':240 if model=='GeRC02' else -370},
        'cache_identity':'effective-model SHA256 plus runtime temperature/solver settings; never 30min-field reuse'}


def contour(model,adapter):
    # Strict projection of the SHA-bound snapshots' first semiconductor cone.
    # Transport and SSD independently load full YAML with their existing loaders.
    body,_=canonical_bytes(model)
    match=re.search(r'    geometry:\r?\n      polycone:\r?\n        r:\r?\n((?:        - [^\r\n]+\r?\n)+)        z:\r?\n((?:        - [^\r\n]+\r?\n)+)',body.decode('utf-8'))
    W.require(match is not None,'Frozen ring contour formatting changed.')
    axes=[[float(line.strip()[2:]) for line in match[i].splitlines()] for i in (1,2)]
    W.require(len(axes[0])==len(axes[1]),'Frozen ring contour axes differ.')
    points=list(zip(*axes));adapter.validate_contour(points)
    W.require(math.isclose(adapter.h.revolved_volume(points),adapter.reference_volume(model),rel_tol=1e-12),'Frozen ring volume differs from independent reference.')
    return points


def operating(model):
    W.require(model in MODELS,'Unsupported fresh ring model.')
    body,_=canonical_bytes(model)
    signed=240 if model=='GeRC02' else -370
    return {'variant_id':'GeRC02_Li50min' if model=='GeRC02' else model,
            'source_model_sha256':M.PINS[model],'effective_model_sha256':M.digest(body),
            'signed_bias_V':signed,'contact_potentials_V':{'1':0,'2':signed},
            'readout_contact_id':1,'wiring_factor':1 if model=='GeRC02' else -1,
            'field_cache_used':False,'annealing_time_minutes':50 if model=='GeRC02' else None,
            'calibration':'independent positive 500 keV injection' if model=='GeRC02' else 'independent negative 500 keV injection through fixed −1 wiring'}


def producers():
    transport=str(W.ROOT/'transport')
    if transport not in sys.path:sys.path.insert(0,transport)
    return importlib.import_module('ring_cs137')


def prepared(directory,resolved,root=W.ROOT,*,historical=False):
    """Validate selected model/mount independently of rehashed caller records."""
    s=resolved['selection'];model=s['detector'];t=Path(directory)/'transport'
    W.require(model in MODELS and s['source']==W.CS and s['pose']=='nominal' and s['primary_count'] in (20,500),
              'Unsupported ring source/count tuple.')
    W.require(W.encoded(resolved['operating_model'])==W.encoded(operating(model)),
              'Selected ring signed bias, wiring or effective-model identity changed.')
    p=W.read(t/'prepared.json');adapter=producers();mount=adapter.scenario()
    W.require(p['kind']=='ring_cs137_prepared_v1' and p['producer_adapter']=='ring_cs137_v1' and
              p['model_id']==model and p['model_sha256']==M.PINS[model] and p['source_pdg']==1000551370 and
              p['primary_count']==s['primary_count'] and p['seed']==s['seed'], 'Ring preparation differs from selected source/model/count/seed.')
    ref=W.BASE+'/'+s['name']+'/transport/effective-model/GeRC02.yaml' if model=='GeRC02' else 'models/KMRC01_candidate.yaml'
    contract=model_contract(model,ref)
    W.require(W.encoded(p['model_contract'])==W.encoded(contract),'Ring effective-model contract differs from its single authorized delta.')
    if model=='GeRC02':
        W.require((t/'effective-model/GeRC02.yaml').read_bytes()==canonical_bytes(model)[0], 'Li50 derivative changed beyond the one annealing-time token.')
    W.require(W.encoded(W.read(t/'effective-model/model-contract.json'))==W.encoded(contract), 'Per-run effective-model receipt differs.')
    W.require(p['coordinate_transform']==mount['coordinate_transform'] and p['mounting_contract']==mount['mounting_contract'] and
              p['source_position_global_mm']==resolved['source_position_global_mm']==mount['source']['position_global_mm'] and
              W.encoded(W.read(t/'scenario.json'))==W.encoded(mount), 'Ring source/mount transform changed.')
    W.require(p['clock_policy']=='remage_initial_decay_secondaries_zero' and p['daughter_lifetime_limit_ns']==-1 and
              p['grouping_policy']==adapter.cs.POLICY and p['decay_photon_line_window_keV']==[660,663], 'Ring decay clock/group policy changed.')
    points=contour(model,adapter);probes=adapter.probes(model,points)
    W.require(p['contour_rz_mm']==[list(v) for v in points] and p['probes']==probes and p['analytic_volume_mm3']==adapter.reference_volume(model),
              'Ring contour, probes or independent volume changed.')
    adapter.validate_report(W.read(t/'geometry-report.json'),model,mount,probes)
    W.require((t/'run.mac').read_text(encoding='utf-8')==adapter.cs.macro_text(W.read(t/'geometry-report.json'),s['primary_count'],p['source_position_global_mm']),
              'Ring radiation macro differs from the selected exact count.')
    for key,prefix,expected in (('source_sha256','transport/',adapter.source_hashes()),('ring_source_sha256','',adapter.ring_source_hashes())):
        recorded=p[key]
        W.require(set(recorded)==set(expected) and all(recorded[n]==resolved['source_sha256'][prefix+n] for n in recorded),
                  'Ring producer attribution differs from its checked plan.')
        if not historical:W.require(recorded==expected,'Ring producer changed before fresh execution.')
    return p


def ledger(directory,resolved,root=W.ROOT,*,historical=False):
    p=prepared(directory,resolved,root,historical=historical);t=Path(directory)/'transport';m=W.read(t/'stream/manifest.json')
    W.require(m['kind']=='cs137_decay_stream_v1' and m['producer_adapter']=='ring_cs137_v1' and m['status']=='complete', 'Not a complete ring decay stream.')
    for key in ('model_id','model_sha256','model_contract','primary_count','coordinate_transform','grouping_policy','clock_policy','source_sha256','ring_source_sha256','mounting_contract'):
        W.require(W.encoded(m[key])==W.encoded(p[key]),'Ring ledger/prepared mismatch: '+key)
    W.require(m['units']=={'energy':'keV','length':'mm','time':'ns'} and m['source_lh5']=='../truth.lh5' and
              m['raw_track_energy_unit']=='MeV' and m['raw_position_unit']=='m' and m['ledger']['full_energy_closure'] is None,
              'Ring ledger units/clock or energy accounting changed.')
    for file,key in (('prepared.json','prepared_sha256'),('run.json','run_sha256'),('truth.lh5','source_lh5_sha256'),
                     ('scenario.json','config_sha256'),('geometry.gdml','geometry_sha256'),('run.mac','macro_sha256')):
        W.require(W.sha(W.safe_path(t,file))==m[key],'Ring ledger binding changed: '+file)
    # Existing iterator retains every initial ID and checks raw-row pulse grouping.
    events=[e for chunk in producers().cs.iter_decay_chunks(t/'stream/manifest.json') for e in chunk]
    W.require(len(events)==resolved['selection']['primary_count'],'Ring ledger lost original primaries.')
    return events


def request(directory,resolved,root=W.ROOT,*,historical=False):
    ledger(directory,resolved,root,historical=historical)
    profile=Path(directory)/'electronics/profile.json';stream=Path(directory)/'transport/stream/manifest.json'
    return {'kind':'workflow_ring_request_v1','configuration_sha256':W.digest(resolved),
            'selection':resolved['selection'],'operating_model':resolved['operating_model'],
            'profile_ref':profile.relative_to(root).as_posix(),'profile_sha256':W.sha(profile),
            'stream_ref':stream.relative_to(root).as_posix(),'stream_sha256':W.sha(stream),
            'source_sha256':resolved['source_sha256'],'numerics':resolved['numerics']}


def response(directory,resolved,report,root=W.ROOT,*,historical=False):
    s=resolved['selection'];out=Path(directory)/'response';op=operating(s['detector'])
    actual=W.read(Path(directory)/'ring-request.json')
    W.require(W.encoded(actual)==W.encoded(request(directory,resolved,root,historical=historical)), 'Ring request lost selected settings or complete transport bindings.')
    envelope=W.read(out/'workflow-ring-response.json')
    W.require(report['kind']=='workflow_ring_native_response_v1' and report['configuration_sha256']==W.digest(resolved) and
              report['request_sha256']==W.sha(Path(directory)/'ring-request.json') and envelope['kind']=='workflow_ring_response_v1' and
              envelope['native_report_sha256']==W.sha(out/'run.json') and envelope['request_sha256']==report['request_sha256'] and
              envelope['configuration_sha256']==report['configuration_sha256'] and envelope['counts']==report['counts'] and envelope['status']==report['status'],
              'Fresh ring envelope/report authority mismatch.')
    p=W.read(Path(directory)/'transport/prepared.json')
    W.require(report['model_contract']==envelope['model_contract']==p['model_contract'] and
              envelope['source_sha256']==resolved['source_sha256'] and
              report['signed_operating_bias_V']==envelope['signed_operating_bias_V']==op['signed_bias_V'] and
              report['contact_potentials_V']==op['contact_potentials_V'] and report['wiring_factor']==envelope['wiring_factor']==op['wiring_factor'] and
              report['new_field_solution'] is True and envelope['new_field_solution'] is True and report['geometry_checks']['field_cache_used'] is False and
              report['independent_calibration_calls']==envelope['independent_calibration_calls']==1, 'Ring field/bias/wiring/calibration convention changed.')
    cal=report['calibration'];c=resolved['electronics_configuration']
    W.require(cal==envelope['calibration'] and cal['energy_keV']==500 and cal['time_step_ns']==2 and
              all(type(cal[k]) in (int,float) and math.isfinite(cal[k]) and cal[k]>0 for k in ('ionisation_energy_eV','charge_C','peak_V','peak_time_ns','volts_per_keV','adc_lsb_V')) and
              math.isclose(cal['volts_per_keV'],cal['peak_V']/500,rel_tol=1e-12) and cal['adc_lsb_V']==c['adc_full_scale_V']/2**c['adc_bits'],
              'Independent selected-profile injection calibration is invalid.')
    W.require(math.isclose(cal['charge_C'],500000/cal['ionisation_energy_eV']*1.602176634e-19,rel_tol=1e-12),
              'Injection charge differs from recorded pair energy and 500 keV input.')
    if s['detector']=='KMRC01_candidate':
        injection=W.read(out/'negative-injection.json')
        W.require(cal['raw_charge_C']<0 and cal['electronics_input_charge_C']==-cal['raw_charge_C']==cal['charge_C'] and cal['wiring_factor']==-1 and
                  injection['kind']=='independent_negative_charge_injection_v1' and injection['calibration']==cal and
                  injection['raw_delta_charge_C']==cal['raw_charge_C'] and injection['electronics_input_delta_charge_C']==cal['charge_C'] and
                  injection['wiring']['factor']==-1 and injection['input_is_independent_of_event_truth'] is True,
                  'KM requires an independent negative injection through fixed -1 wiring.')
    else:
        W.require(cal['method']=='single delta-charge injection at t=0; sampled analog peak; fixed across events' and not (out/'negative-injection.json').exists(),
                  'Ge ring requires the original independent positive calibration.')
    records=[W.decode_json(line) for line in (out/'scalars.jsonl').read_text(encoding='utf-8').splitlines()]
    pulses=[r for r in records if r['record_kind']=='pulse']
    truths=[W.decode_json(line) for line in (out/'truth.jsonl').read_text(encoding='utf-8').splitlines()]
    primaries=[r for r in records if r['record_kind']=='decay']
    W.require(len(records)==len(primaries)+len(pulses) and len(primaries)==len(truths)==s['primary_count'] and
              [r['event_id'] for r in primaries]==[e['event_id'] for e in truths]==list(range(s['primary_count'])),
              'Ring primary summary census differs from original truth.')
    for primary,event in zip(primaries,truths):
        W.require(type(primary['event_id']) is int and type(primary['global_decay_id']) is int and type(primary['pulse_count']) is int and
                  primary['global_decay_id']==event['global_decay_id'] and primary['group_id'] is None and
                  energy_sum_matches(primary['deposited_energy_keV'],(v['energy_keV'] for v in event['steps'])) and
                  type(primary['zero_deposit']) is bool and primary['zero_deposit']==all(v['energy_keV']==0 for v in event['steps']) and
                  primary['pulse_count']==len(event['pulse_groups']) and W.encoded(primary['raw_row_indices'])==W.encoded([v['raw_row_index'] for v in event['steps']]) and
                  all(primary[k]==event[k] for k in ('line_photon_count','decay_photon_count','material_energy_keV')) and
                  primary['full_energy_closure'] is None,'Ring primary summary differs from original truth.')
    expected={(e['event_id'],g['group_id']):(e,g) for e in truths for g in e['pulse_groups']}
    W.require(len(pulses)==len(expected) and len({(r['event_id'],r['group_id']) for r in pulses})==len(pulses), 'Ring pulse identity census differs from original groups.')
    counts=report['counts'];failed=sum(r.get('status')=='native_transport_failed' for r in pulses)
    W.require(all(type(counts[k]) is int and counts[k]>=0 for k in ('initial_primaries','initial_decays','zero_deposit_primaries','line_photons',
              'decay_photons','groups','accepted','rejected','native_failed_groups','readout_rejected')),'Ring census values must be nonnegative integer counts.')
    W.require([counts[k] for k in ('initial_primaries','initial_decays','zero_deposit_primaries','line_photons','decay_photons')]==
              [len(truths),len(truths),sum(all(v['energy_keV']==0 for v in e['steps']) for e in truths),
               sum(e['line_photon_count'] for e in truths),sum(e['decay_photon_count'] for e in truths)],
              'Ring primary/zero/photon aggregate census differs from truth.')
    accepted=sum(r['accepted'] is True for r in pulses);rejected=len(pulses)-accepted
    W.require([counts[k] for k in ('groups','accepted','rejected','native_failed_groups','readout_rejected')]==
              [len(pulses),accepted,rejected,failed,rejected-failed], 'Ring scalar failure/readout rejection census differs from its receipt.')
    for pulse in pulses:
        key=(pulse['event_id'],pulse['group_id']);W.require(key in expected,'Ring pulse has no original group.')
        event,group=expected[key];byrow={row['raw_row_index']:row for row in event['steps']}
        W.require(all(type(pulse[k]) is int for k in ('event_id','group_id','global_decay_id')) and type(pulse['accepted']) is bool and
                  pulse.get('status') in (None,'native_transport_failed') and
                  pulse['global_decay_id']==event['global_decay_id'] and W.encoded(pulse['group'])==W.encoded(group) and
                  type(pulse['origin_time_ns']) in (int,float) and pulse['origin_time_ns']==group['origin_time_ns'] and
                  W.encoded(pulse['raw_row_indices'])==W.encoded(group['row_indices']) and
                  energy_sum_matches(pulse['deposited_energy_keV'],(byrow[i]['energy_keV'] for i in group['row_indices'])),
                  'Ring pulse changed truth, grouping, origin or raw-row identity.')
        if pulse.get('status')=='native_transport_failed':
            W.require(all(k in pulse and pulse[k] is None for k in ('readout','final_induced_keV','transport_flags','charge_end_ns',
                      'native_any_negative_charge','native_min_charge_keV','native_max_charge_keV','endpoints','current_nA','induced_charge_fC')) and
                      pulse['accepted'] is False and pulse['rejection_reason']=='native_transport_failed' and pulse['trace_saved'] is False,
                      'Native failure must retain null response quantities.')
            error=pulse['native_error']
            W.require(set(error)=={'type','message','exact_error','stage'} and error['type']=='ArgumentError' and
                      error['message'] in ('Noncontact endpoint outside crystal','Invalid waveform support') and
                      error['exact_error']=='ArgumentError: '+error['message'] and error['stage']=='NativeLiExample.native_event' and
                      pulse['deposition_delays_ns']==[byrow[i]['time_ns']-group['origin_time_ns'] for i in group['row_indices']] and
                      pulse['source_lh5_sha256']==report['source_lh5_sha256'] and pulse['raw_table']=='stp/germanium' and
                      pulse['parcels']==16 and pulse['seed_family']==2609261 and pulse['endpoint_details_note']==
                      'Strict NativeLiExample.native_event does not expose rejected endpoint details; private supervisor diagnostics are separate.',
                      'Native failure diagnostic/provenance differs from original group.')
        elif s['detector']=='KMRC01_candidate':
            r=pulse['readout'];W.require(r['wiring']['factor']==-1 and r['wiring']['model_id']==s['detector'] and
                r['raw_native_final_charge_keV']==pulse['final_induced_keV'] and r['raw_native_min_charge_keV']==pulse['native_min_charge_keV'] and
                r['raw_native_max_charge_keV']==pulse['native_max_charge_keV'], 'KM scalar lost original native signs or fixed wiring.')
    failure_path=out/'native-failures.jsonl'
    diagnostics=[W.decode_json(v) for v in failure_path.read_text(encoding='utf-8').splitlines()] if failure_path.exists() else []
    failed_pulses={(p['event_id'],p['group_id']):p for p in pulses if p.get('status')=='native_transport_failed'}
    seen_failures=set()
    for diagnostic in diagnostics:
        p=diagnostic['pulse'];key=(p['event_id'],p['group_id'])
        W.require(key in failed_pulses and key not in seen_failures and W.encoded(p)==W.encoded(failed_pulses[key]),'Native failure diagnostic identity differs.')
        event,group=expected[key];byrow={row['raw_row_index']:row for row in event['steps']}
        W.require(diagnostic['record_kind']=='native_failure_diagnostic' and diagnostic['original_event']==event and
                  diagnostic['original_group']==group and diagnostic['original_steps']==[byrow[i] for i in group['row_indices']] and
                  all(diagnostic['settings'][k]==report[k] for k in diagnostic['settings']) and
                  set(diagnostic['settings'])=={'model_id','model_sha256','input_sha256','source_sha256','temperature_K','bias_V','parcels',
                    'seed_family','seed_rule','diffusion','end_drift_when_no_field','self_repulsion','drift_dt_ns','nominal_drift_cap_ns',
                    'readout_contact_id','field_settings','field_fingerprint','profile_sha256','config_sha256','calibration','native_failure_policy'},
                  'Native failure diagnostic changed original truth/settings.')
        seen_failures.add(key)
    W.require(seen_failures==set(failed_pulses),'Native failure diagnostics are incomplete.')
    bypulse={(p['event_id'],p['group_id']):p for p in pulses};seen_traces=set()
    expected_traces={(p['event_id'],p['group_id']) for i,p in enumerate(pulses) if i<16 and p.get('status')!='native_transport_failed'}
    for p in pulses:
        W.require(type(p['trace_saved']) is bool and p['trace_saved']==((p['event_id'],p['group_id']) in expected_traces),
                  'Ring trace_saved differs from original first-16 group selection.')
    for line in (out/'traces.jsonl').read_text(encoding='utf-8').splitlines():
        value=W.decode_json(line);key=(value['event_id'],value['group_id'])
        W.require(all(type(value[k]) is int for k in ('event_id','group_id','global_decay_id')) and type(value['origin_time_ns']) in (int,float) and
                  key in expected_traces and key not in seen_traces and value['global_decay_id']==bypulse[key]['global_decay_id'] and
                  value['origin_time_ns']==bypulse[key]['origin_time_ns'],'Ring saved trace identity differs from its completed original group.')
        seen_traces.add(key);trace=value['trace']
        if s['detector']=='KMRC01_candidate':
            for key in ('induced_charge_fC','current_nA'):
                W.require(trace['raw_native_'+key]==[-x for x in trace[key]], 'KM trace lost its raw signed input.')
    W.require(seen_traces==expected_traces,'Ring saved trace census is incomplete.')
