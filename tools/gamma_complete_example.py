"""Complete the original40 saved gamma primaries; no radiation or field solve."""
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys
import time

import gamma_native_example as G
import gamma_showcase as S
import charge_check as C
import replay_readout as R

ROOT=G.ROOT
BASE='.local/gamma-complete-v1'
KIND='saved_gamma_complete_v1'
WORKER='simulation/gamma_complete_example.jl'
NEW_NATIVE={'AK02':[8,11,13,14],'SAP22':[8,9,12]}
CODE=(WORKER,'simulation/saved_collection_edge.jl','simulation/gamma_saved_replay.jl',
      'tools/gamma_complete_example.py','tools/test_gamma_complete_example.py')
RECOVERY='.local/product-delivery-v1/implementation/m14b/recovery'
RECOVERY_BEFORE_SHA='4c516c921a97f8cbbbeed089e92b8ea6df82ed792c427c6153015a8253491582'
ORIGINAL_FREEZE_SHA='79dfd3be2f2a28432fc88d804ddfc839890176c7c6e81feba4bdeb6f2ee2fd27'
MAINTENANCE_SOURCES=CODE[-2:]
MAX_COMPLETE_REPORT=16*1024*1024

class CompletionReader(G.Reader):
    """Only the two aggregate completion reports have a larger JSON budget."""
    def report(self,relative):
        path=self.path(relative)
        C.require(path.name=='report.json' and path.parent.name in NEW_NATIVE,
            'Only a named completion report may use the16MiB JSON budget')
        digest=self.digest(relative)
        C.require(path.stat().st_size<=MAX_COMPLETE_REPORT,'Completion report exceeds16MiB bound')
        with path.open('rb') as stream:raw=stream.read(MAX_COMPLETE_REPORT+1)
        C.require(len(raw)<=MAX_COMPLETE_REPORT,'Growing completion report exceeds16MiB bound')
        C.equal(hashlib.sha256(raw).hexdigest(),digest,'Completion report parsed/hash bytes')
        return C.object_value(G.decode(raw.decode('utf-8-sig')),str(relative))

def all_inventory(directory):
    """Hash every owned file, including the failed parent, refusing linked paths."""
    directory=Path(directory);reader=G.Reader(directory);result={}
    for path in sorted(directory.rglob('*')):
        relative=path.relative_to(directory).as_posix();reader.path(relative)
        if path.is_file():result[relative]=dict(sha256=reader.digest(relative),bytes=path.stat().st_size)
    reader.recheck();return result

def maintenance_delta(before,current,frozen):
    """Closed Python-only maintenance, never a scientific-source exception."""
    C.equal([before['kind'],before['status'],before['original_source_freeze_sha256'],
        before['original_error'],before['threads'],before['native_failure_policy']],
        ['m14b_size_recovery_before_v1','immutable_original_failed_parent_successful_ak_worker',
         ORIGINAL_FREEZE_SHA,'gamma JSON exceeds bounded reader',2,'record'],'Exact admitted failure')
    C.equal(before['mutable_source_names'],list(MAINTENANCE_SOURCES),'Closed maintenance roles')
    old=before['original_source_pins'];C.equal(set(current),set(old),'Complete original input/source inventory')
    changed={name for name in old if old[name]!=current[name]}
    C.equal(changed,set(MAINTENANCE_SOURCES),'Only the two approved Python maintenance files change')
    C.equal(frozen['status'],'frozen_after_writer_exit','Post-maintenance writer exit freeze')
    for name in CODE:C.equal(frozen['files'][name]['sha256'],current[name],'Current frozen completion source')
    return {name:dict(before=old[name],after=current[name]) for name in MAINTENANCE_SOURCES}

def recovery_authority(root,current):
    reader=G.Reader(root);reader.digest(RECOVERY+'/BEFORE.json',RECOVERY_BEFORE_SHA)
    before=reader.json(RECOVERY+'/BEFORE.json')
    reader.digest(RECOVERY+'/ORIGINAL-SOURCE-FREEZE.json',ORIGINAL_FREEZE_SHA)
    original_freeze=reader.json(RECOVERY+'/ORIGINAL-SOURCE-FREEZE.json')
    for name in CODE:C.equal(original_freeze['files'][name]['sha256'],before['original_source_pins'][name],'Original producer freeze')
    for name in MAINTENANCE_SOURCES:
        reader.digest(RECOVERY+'/original-sources/'+Path(name).name,before['original_source_pins'][name])
    snapshot=Path(root)/RECOVERY/'original-example'
    C.equal(all_inventory(snapshot),before['artifact_inventory'],'Immutable original failure/terminal snapshot')
    failed=reader.json(RECOVERY+'/original-example/run.json')
    C.equal([failed['kind'],failed['status'],failed['error'],failed['threads'],failed['native_failure_policy'],failed['source_pins'],failed['stages']],
        [KIND,'failed',before['original_error'],2,'record',before['original_source_pins'],before['stages']],'Original failed parent authority')
    C.equal(before['stages'][0]['model_id'],'AK02','Only AK02 was executed')
    C.require(len(before['stages'])==1 and before['stages'][0]['exit_code']==0,'One successful original worker')
    freeze_name='.local/product-delivery-v1/implementation/m14b/SOURCE-FREEZE.json'
    freeze_hash=reader.digest(freeze_name);frozen=reader.json(freeze_name)
    delta=maintenance_delta(before,current,frozen);reader.recheck()
    return before,dict(kind='m14b_python_size_recovery_v1',before_sha256=RECOVERY_BEFORE_SHA,
        original_source_freeze_sha256=ORIGINAL_FREEZE_SHA,validation_source_freeze_sha256=freeze_hash,
        source_delta=delta,original_failed_run_sha256=before['original_run_sha256'])

def verify_stage(directory,plan,threads,pins,stage,root=ROOT):
    """A terminal worker is admitted before any derivative or further dispatch."""
    out=CompletionReader(directory);report=out.report('report.json');verify_report(report,plan,threads)
    C.equal(report['native_failure_policy'],plan['native_failure_policy'],'Worker failure policy')
    C.equal(report['request_sha256'],out.digest('request.json'),'Consumed request bytes')
    request=out.json('request.json');G.exact(request,dict(plan,pins=pins,threads=threads,julia_executable_sha256=G.JULIA_SHA),'Full stage request authority')
    child=out.json('child.json');C.equal(child,{k:v for k,v in stage.items() if k!='model_id'},'Original child/stage identity')
    C.equal(child['exit_code'],0,'Actual terminal worker exit')
    C.equal(child['arguments'][1:],['--startup-file=no','--project='+str(Path(root)/'simulation'),
        '--threads='+str(threads),'--compiled-modules=existing',str(Path(root)/WORKER),
        '--request',str(Path(directory)/'request.json'),'--output',str(directory)],'Exact saved-only dispatch')
    C.equal(hashlib.sha256(Path(child['arguments'][0]).read_bytes()).hexdigest(),G.JULIA_SHA,'Original worker executable')
    expected={'request.json','report.json','child.json','worker.log'}
    for case in report['cases']:
        eid=case['initial_primary_id'];name='event-'+str(eid)+'.json';expected.add(name)
        G.exact(out.json(name),case,'Event/report identity')
        if str(eid) in plan['reused_records']:C.equal(out.digest(name),plan['reused_records'][str(eid)]['sha256'],'Old6 exact response bytes')
        edge_name='collection-edge-'+str(eid)+'.json'
        if case['charge_input'] is None:C.require(not out.path(edge_name).exists(),'No invented failed derivative');continue
        expected.add(edge_name);edge=out.json(edge_name);wave=case['charge_input'];trace=case['readout']['trace']
        C.equal([edge['kind'],edge['schema_version'],edge['case_sha256'],edge['request_sha256'],edge['original_readout_source_sha256']],
            ['saved_collection_edge_display_v1',1,out.digest(name),report['request_sha256'],pins['simulation/readout.jl']],'Dense derivative provenance')
        G.exact(edge['identity'],dict(model_id=plan['model_id'],initial_primary_id=eid,group_id=None if case['zero_ge'] else 0),'Dense derivative identity')
        C.integer(edge['captured_sample_count'],'Dense sample count',2,10001)
        C.equal(edge['time_ns'],[float(i*2) for i in range(edge['captured_sample_count'])],'Complete dense2ns grid')
        C.equal([len(edge['preamp_V']),edge['captured_start_ns'],edge['captured_stop_ns'],edge['input_sample_count'],edge['input_charge_end_ns'],edge['natural_readout_end_ns']],
            [edge['captured_sample_count'],0.0,edge['time_ns'][-1],len(wave['time_since_initial_primary_ns']),case['charge_end_ns'],case['readout']['readout_end_ns']],'Dense/full-window context')
        C.require(all(math.isfinite(v) for v in edge['preamp_V']),'Finite signed dense preamp')
        retained=[(int(t/2),v) for t,v in zip(trace['time_ns'],trace['preamp_V']) if t<=edge['captured_stop_ns']]
        for index,value in retained:G.exact(edge['preamp_V'][index],value,'Independent retained preamp binary64 parity')
        C.equal(edge['retained_original_parity'],dict(comparison='binary64_bits_including_signed_zero',matched_points=len(retained),
            matched_negative_zero_points=sum(v==0 and math.copysign(1,v)<0 for _,v in retained),passed=True),'Independent retained parity census')
    actual={path.relative_to(directory).as_posix() for path in Path(directory).rglob('*') if path.is_file()}
    products={'truth-ledger.jsonl','signals.csv','calibration.json'}
    C.require(not any(path.is_dir() for path in Path(directory).iterdir()),'No unexpected terminal-stage directories')
    C.require(actual==expected or actual==expected|products,'Exact terminal stage inventory; partial/extra files refused')
    out.recheck();return report

def admit_resume(reader,plans,threads,policy,root=ROOT):
    """One recorded report-size failure only; never adopt a partial worker."""
    pins={n:v[0] for n,v in reader.watched.items()};before,maintenance=recovery_authority(root,pins)
    C.equal([threads,policy],[before['threads'],before['native_failure_policy']],'Explicit original recovery choices')
    dest=Path(root)/BASE/'example'
    C.equal(all_inventory(dest),before['artifact_inventory'],'Exact captured failed parent/AK terminal inventory')
    C.equal({p.name for p in dest.iterdir()},{'run.json','AK02'},'Only the captured AK stage exists; SAP not started')
    plan=next(p for p in plans if p['model_id']=='AK02');plan['native_failure_policy']=policy
    verify_stage(dest/'AK02',plan,threads,before['original_source_pins'],before['stages'][0],root)
    reader.recheck();receipt=G.Reader(dest).json('run.json')
    receipt.update(status='running',validation_pins=pins,stage_source_pins={'AK02':before['original_source_pins']},
        source_maintenance=maintenance,recovery_origin=dict(status='failed',error=receipt.pop('error'),
        orchestration_seconds=receipt.pop('orchestration_seconds'),run_sha256=before['original_run_sha256']))
    return dest,receipt,pins

def focus_end(t,q):
    """A sampled-variation camera, never a full-collection assertion."""
    differences=[abs(b-a) for a,b in zip(q,q[1:])];total=sum(differences)
    index=1;accumulated=0.0
    if total:
        for index,difference in enumerate(differences,1):
            accumulated+=difference
            if accumulated>=.995*total:break
    edge=t[index];return 2*math.ceil((edge+max(10.,.2*edge))/2)

def load_inputs(root=ROOT):
    reader,plans=G.load_inputs(root)
    original,_,old_reader=S.read_saved_science(root)
    for name in CODE:reader.digest(name)
    complete=reader.json(G.BASE+'/example/COMPLETE.json')
    reader.digest(G.BASE+'/example/COMPLETE.json',S.PINS['example/COMPLETE.json'])
    for plan,model in zip(plans,original['models']):
        ident=plan['model_id'];plan.update(kind=KIND,selected_ids=list(range(20)),
            readout_config=R.expected_config(reader,reader.json(G.PROFILE),20),remaining_native_ids=NEW_NATIVE[ident],reused_records={})
        for old_id in G.DETECTORS[ident]['ids']:
            relative=ident+'/event-'+str(old_id)+'.json';name=G.BASE+'/example/'+relative;stamp=complete['artifacts'][relative]
            reader.digest(name,stamp['sha256']);case=reader.json(name)
            S.exact(case,next(c for c in model['report']['cases'] if c['initial_primary_id']==old_id),'old response authority')
            plan['reused_records'][str(old_id)]={'path':name,**stamp}
        name=G.BASE+'/example/'+ident+'/calibration.json';reader.digest(name,complete['artifacts'][ident+'/calibration.json']['sha256'])
        calibration=reader.json(name);S.exact(calibration['calibration'],plan['expected_calibration'],'old injection authority')
    C.equal(sum(len(e['steps']) for p in plans for e in p['events'] if e['event_id'] in NEW_NATIVE[p['model_id']]),118,'whole added Ge-row census including zero-energy rows')
    C.equal(sum(sum(s['energy_keV']>0 for s in e['steps']) for p in plans for e in p['events'] if e['event_id'] in NEW_NATIVE[p['model_id']]),105,'positive-row parcel census')
    reader.recheck();old_reader.recheck();return reader,plans

def validate_case(case,event,plan):
    C.equal([case['initial_primary_id'],case['event_id'],case['zero_ge'],case['primary_time_ns'],case['clock_policy']],
        [event['initial_primary_id'],event['event_id'],event['zero_ge'],0.0,'synthetic_primary_time_zero'],'complete primary identity/clock')
    G.exact(case['truth_ge_edep_keV'],event['truth_ge_edep_keV'],'truth Edep')
    C.equal(case['raw_row_indices'],[s['raw_row_index'] for s in event['steps']],'all original raw rows')
    G.exact(case['deposition_delays_ns'],[s['time_ns'] for s in event['steps']],'all row delays')
    seeds=[dict(raw_row_index=s['raw_row_index'],parcels=[dict(parcel_index=i,
        seed_uint64_decimal=str(int.from_bytes(hashlib.sha256(f"2609261/{event['event_id']}/{s['raw_row_index']}/{i}".encode()).digest()[:8],'big')))
        for i in range(1,17)]) for s in event['steps'] if s['energy_keV']>0]
    C.equal(case['parcel_seeds'],seeds,'frozen independent parcel seeds')
    if case['status']=='native_failed':
        C.require(not event['zero_ge'] and plan['native_failure_policy']=='record','Explicit native failure policy')
        error=case['error'];C.require(error['type']=='ArgumentError' and error['message'] in G.FAILURES and
            error['exact_error']=='ArgumentError: '+error['message'] and error['stage']=='NativeLiExample.native_event','Exact allowed native failure')
        for name in ('native','transport_flags','charge_input','final_induced_keV','charge_end_ns','readout'):C.require(case[name] is None,'Unknown native/readout must remain null')
        return
    C.require(case['error'] is None and case['charge_input'] is not None and case['readout'] is not None,'Known response')
    wave=case['charge_input'];t=wave['time_since_initial_primary_ns'];q=wave['induced_equivalent_energy_keV'];r=case['readout']
    C.require(len(t)==len(q)>=2 and t[0]==q[0]==0 and all(math.isfinite(v) for v in (*t,*q)) and
        all(b-a==2 for a,b in zip(t,t[1:])),'Original signed full2ns input')
    G.exact([case['charge_end_ns'],case['final_induced_keV']],[t[-1],q[-1]],'Original charge endpoint')
    if event['zero_ge']:
        C.require(case['status']=='native_not_applicable_true_zero' and case['native'] is None and case['transport_flags'] is None,'Known zero bypass')
        G.exact([t,q],[[0.0,2.0],[0.0,0.0]],'Two-point explicit zero input')
    else:
        C.equal(case['status'],'native_completed','Positive status')
        G.exact([case['native']['times'],case['native']['signal']],[t,q],'Native signed charge')
        native=case['native']['steps'];positive=[s for s in event['steps'] if s['energy_keV']>0]
        C.equal([s['raw_row_index'] for s in native],[s['raw_row_index'] for s in positive],'Every positive raw row')
        endpoints=[]
        for s,raw in zip(native,positive):
            G.exact([s['deposited_energy_keV'],s['deposition_delay_ns'],s['parcel_weight_keV']],
                [raw['energy_keV'],raw['time_ns'],raw['energy_keV']/16],'Native row weight/delay')
            endpoints.extend(s['endpoints'])
            C.require(all(type(e['parcel_index']) is int and 1<=e['parcel_index']<=16 for e in s['endpoints']),'Parcel identity')
        C.equal(case['transport_flags'],dict(carrier_parcels=len(endpoints),geometric_contacts=sum(bool(e['contact_ids']) for e in endpoints),
            step_limits=sum(e['step_limit_reached'] for e in endpoints),stopped_without_contact=sum(e['status']=='stopped_without_contact' for e in endpoints)),'Independent endpoint flags')
    C.require(type(r['accepted']) is bool and r['current_balance']['passed'] is True,'Readout validity/balance')
    C.equal([r['negative_input'],r['input_sample_count']],[any(v<0 for v in q),len(t)],'Signs/full sample count')
    cal=plan['expected_calibration'];C.close(r['analog_energy_keV'],r['peak_V']/cal['volts_per_keV'],'Fixed injection slope')
    C.integer(r['adc_code'],'Peak ADC code',0,2**plan['readout_config']['adc_bits']-1)
    c=plan['readout_config'];code=0 if r['peak_V']<=0 else 2**c['adc_bits']-1 if r['peak_V']>=c['adc_full_scale_V'] else math.floor(r['peak_V']/cal['adc_lsb_V'])
    C.equal(r['adc_code'],code,'Diagnostic ADC code')
    if r['accepted']:C.close(r['reconstructed_energy_keV'],(code+.5)*cal['adc_lsb_V']/cal['volts_per_keV'],'Fixed ADC Erec')
    else:C.require(r['reconstructed_energy_keV'] is None,'Rejected Erec remains null')

def verify_report(report,plan,threads):
    C.equal([report['kind'],report['schema_version'],report['model_id'],report['selected_ids']],
        [KIND,1,plan['model_id'],list(range(20))],'Complete report identity')
    C.require(report['status'] in ('completed','completed_with_native_failures'),'Terminal response')
    G.exact(report['readout_config'],plan['readout_config'],'Only expected_primary_count20 config change')
    G.exact(report['calibration'],plan['expected_calibration'],'Independent fixed injection')
    C.equal([report['settings'],report['calibration_calls'],report['native_calls'],report['field_solve_seconds']],
        [G.SETTINGS,1,len(NEW_NATIVE[plan['model_id']]),0.0],'Bounded actual work')
    C.equal(report['calibration_verification_calls'],1,'One separate checked display-context injection')
    C.equal([report['field_fingerprint_before'],report['field_fingerprint_after']], [plan['expected_field_fingerprint']]*2,'Saved fields unchanged')
    runtime=report['runtime'];C.equal([runtime['threads'],runtime['blas_threads'],runtime['executable_sha256'],runtime['ssd_loaded']], [threads,1,G.JULIA_SHA,True],'Recorded existing runtime')
    C.equal([runtime['environment']['julia_version'],runtime['environment']['ssd_version'],runtime['readout_environment']['json_version']],['1.13.0','0.11.8','1.9.0'],'Versions')
    C.require(report['guard']['installed'] is True and report['guard']['package_files_modified'] is False,'Process-local native guard')
    C.equal([c['initial_primary_id'] for c in report['cases']],list(range(20)),'No success filtering')
    for case,event in zip(report['cases'],plan['events']):validate_case(case,event,plan)
    failed=sum(c['status']=='native_failed' for c in report['cases']);positive=sum(not e['zero_ge'] for e in plan['events'])
    accepted=sum(c['readout'] is not None and c['readout']['accepted'] for c in report['cases'])
    C.equal(report['counts'],dict(radiation_primaries=20,selected_primaries=20,unprocessed_primaries=0,selected_true_zeros=20-positive,
        native_calls=len(NEW_NATIVE[plan['model_id']]),native_reused=2,native_failed=failed,native_completed=positive-failed,
        readout_completed=20-failed,readout_accepted=accepted,zero_input_readouts=20-positive,
        readout_not_accepted=20-failed-accepted,electronics_rejected=sum(not c['zero_ge'] and c['readout'] is not None and not c['readout']['accepted'] for c in report['cases'])),'Full response census')
    C.equal(report['status'],'completed_with_native_failures' if failed else 'completed','Failure accounting')

def verify(directory,root=ROOT,require_complete=True):
    reader,plans=load_inputs(root);directory=Path(directory).resolve();out=CompletionReader(directory)
    C.require(directory==(Path(root)/BASE/'example').resolve(),'Fixed completion root')
    run=out.json('run.json');C.require(run['kind']==KIND and run['status'] in ('completed','completed_with_native_failures'),'Complete orchestration')
    C.equal({p.name for p in directory.iterdir()},{'AK02','SAP22','run.json'}|({'COMPLETE.json'} if require_complete else set()),'Exact completion root inventory')
    pins={n:v[0] for n,v in reader.watched.items()}
    if 'source_maintenance' in run:
        before,maintenance=recovery_authority(root,pins)
        G.exact(run['source_maintenance'],maintenance,'Exact recorded maintenance authority')
        C.equal(run['source_pins'],before['original_source_pins'],'Original parent producer pins retained')
        C.equal(run['validation_pins'],pins,'Current post-maintenance validation pins')
        C.equal(run['stage_source_pins'],{'AK02':before['original_source_pins'],'SAP22':pins},'Per-worker producer pins')
        C.equal(run['stages'][0],before['stages'][0],'Original successful AK worker receipt retained')
        for name,stamp in before['artifact_inventory'].items():
            if name.startswith('AK02/'):out.digest(name,stamp['sha256'],stamp['bytes'])
    else:C.equal(run['source_pins'],pins,'Recorded frozen inputs/sources')
    C.equal([s['model_id'] for s in run['stages']],['AK02','SAP22'],'Both serial terminal stages')
    if require_complete:
        complete=out.json('COMPLETE.json');C.equal(complete['artifacts'],G.inventory(directory),'Exact completed inventory')
        C.equal(complete['run_sha256'],out.digest('run.json'),'Complete run binding')
        C.equal([complete['kind'],complete['status'],complete['counts']],[KIND,run['status'],dict(radiation_primaries=40,processed_primaries=40,
            unprocessed_primaries=0,known_zero_primaries=29,native_positive_primaries=11,additional_native_calls=7,additional_known_zero_readouts=27,
            injection_calibrations=2,calibration_verification_injections=2)],'Complete authority census/calls')
    for plan in plans:
        model=plan['model_id'];plan['native_failure_policy']=run['native_failure_policy']
        stage=next(s for s in run['stages'] if s['model_id']==model)
        stage_pins=run.get('stage_source_pins',{}).get(model,pins)
        report=verify_stage(directory/model,plan,run['threads'],stage_pins,stage,root)
        calibration=out.json(model+'/calibration.json');G.exact(calibration['config'],plan['readout_config'],'Rehashed resolved calibration config')
        G.exact(calibration['calibration'],report['calibration'],'Fixed independent calibration file')
        G.exact(list(out.jsonl(model+'/truth-ledger.jsonl')),G.truth_ledger(plan,report['cases']),'All original truth/processed IDs')
        expected=[[case['initial_primary_id'],t,q] for case in report['cases'] if case['charge_input'] is not None
            for t,q in zip(case['charge_input']['time_since_initial_primary_ns'],case['charge_input']['induced_equivalent_energy_keV'])]
        actual=[[int(r[0]),float(r[1]),float(r[2])] for r in out.csv(model+'/signals.csv',G.SIGNAL_COLUMNS)]
        G.exact(actual,expected,'Every full signed input CSV sample')
    reader.recheck();out.recheck();return {'kind':KIND,'status':run['status'],'radiation_primaries':40,'unprocessed_primaries':0}

def run(threads=2,policy='abort',root=ROOT,resume=False):
    C.require(type(threads) is int and threads in (1,2) and policy in ('abort','record'),'Bounded execution choice')
    reader,plans=load_inputs(root);dest=Path(root)/BASE/'example'
    frozen=S.decode((Path(root)/'.local/product-delivery-v1/implementation/m14b/SOURCE-FREEZE.json').read_bytes())
    C.require(frozen['status']=='frozen_after_writer_exit','Completion sources must be frozen after writer exit')
    for name in CODE:C.equal(frozen['files'][name]['sha256'],reader.digest(name),'Frozen completion source')
    exe=G.julia_executable();reader.recheck();pins={n:v[0] for n,v in reader.watched.items()}
    if resume:dest,receipt,pins=admit_resume(reader,plans,threads,policy,root)
    else:
        C.require(not dest.exists(),'Preserve existing completion evidence; known failure needs explicit --resume')
        dest.mkdir(parents=True)
        receipt=dict(kind=KIND,status='running',threads=threads,native_failure_policy=policy,source_pins=pins,stages=[],
            additional_radiation_calls=0,field_solve_seconds=0.0,limitations=G.LIMITATIONS[1:])
    G.save(dest/'run.json',receipt,replace=resume);started=time.perf_counter();reports=[]
    try:
        for plan in plans:
            plan['native_failure_policy']=policy;model=plan['model_id'];directory=dest/model
            if resume and model=='AK02':stage=receipt['stages'][0];stage_pins=receipt['stage_source_pins'][model]
            else:
                C.require(not directory.exists(),'Never adopt partial/unexpected model output');directory.mkdir()
                for eid,item in plan['reused_records'].items():shutil.copyfile(reader.path(item['path']),directory/('event-'+eid+'.json'))
                request=dict(plan,pins=pins,threads=threads,julia_executable_sha256=G.JULIA_SHA);G.save(directory/'request.json',request)
                args=[exe,'--startup-file=no','--project='+str(Path(root)/'simulation'),'--threads='+str(threads),'--compiled-modules=existing',
                    str(reader.path(WORKER)),'--request',str(directory/'request.json'),'--output',str(directory)]
                call=G.child(args,str(root),threads);(directory/'worker.log').write_text(call.pop('output'),encoding='utf-8')
                G.save(directory/'child.json',call);stage=dict(model_id=model,**call);receipt['stages'].append(stage)
                if resume:receipt['stage_source_pins'][model]=pins
                reader.recheck();C.equal(call['exit_code'],0,'Completion worker; retained failure evidence');stage_pins=pins
            report=verify_stage(directory,plan,threads,stage_pins,stage,root);reports.append(report)
            G.write_products(directory,plan,report)
            calibration=G.Reader(directory).json('calibration.json')
            calibration['method_scope']='one separate delta-charge injection for this detector, fixed across all20 original primaries; old6 response bytes reused'
            G.save(directory/'calibration.json',calibration,replace=True)
            G.save(dest/'run.json',receipt,replace=True)
        receipt['status']='completed_with_native_failures' if any(r['status']=='completed_with_native_failures' for r in reports) else 'completed'
        receipt['orchestration_seconds']=time.perf_counter()-started;G.save(dest/'run.json',receipt,replace=True)
        verify(dest,root,require_complete=False);G.save(dest/'COMPLETE.json',dict(kind=KIND,status=receipt['status'],artifacts=G.inventory(dest),
            run_sha256=hashlib.sha256((dest/'run.json').read_bytes()).hexdigest(),counts=dict(radiation_primaries=40,processed_primaries=40,
                unprocessed_primaries=0,known_zero_primaries=29,native_positive_primaries=11,additional_native_calls=7,additional_known_zero_readouts=27,
                injection_calibrations=2,calibration_verification_injections=2)))
        return verify(dest,root)
    except BaseException as error:
        receipt.update(status='failed',error=str(error),orchestration_seconds=time.perf_counter()-started);G.save(dest/'run.json',receipt,replace=True);raise

def prepare_replay(root=ROOT):
    reader,plans=load_inputs(root);dest=Path(root)/BASE/'old6-replay-request.json';C.require(not dest.exists(),'Preserve replay request')
    models={}
    for plan in plans:
        ident=plan['model_id'];events=[]
        for item in plan['reused_records'].values():
            rec=reader.json(item['path']);w=rec['charge_input'];events.append(dict(item,stop_ns=focus_end(w['time_since_initial_primary_ns'],w['induced_equivalent_energy_keV'])))
        models[ident]={'calibration_path':G.BASE+'/example/'+ident+'/calibration.json','events':events}
    dest.parent.mkdir(parents=True,exist_ok=True)
    G.save(dest,dict(kind='old_six_gamma_replay_v1',models=models,pins={n:v[0] for n,v in reader.watched.items()}))
    return {'request':str(dest),'science_calls':0}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=('check','check-resume','prepare-replay','run','verify'));p.add_argument('--threads',type=int,choices=(1,2),default=2);p.add_argument('--native-failure-policy',choices=('abort','record'),default='abort');p.add_argument('--resume',action='store_true',help='Reuse only the captured successful AK worker after the recorded report-size failure');args=p.parse_args()
    C.require(not args.resume or args.mode=='run','--resume is an explicit run action')
    if args.mode=='check-resume':
        reader,plans=load_inputs();admit_resume(reader,plans,args.threads,args.native_failure_policy);result={'status':'checked_exact_terminal_ak_recovery','science_calls':0}
    else:result=run(args.threads,args.native_failure_policy,resume=args.resume) if args.mode=='run' else verify(ROOT/BASE/'example') if args.mode=='verify' else prepare_replay() if args.mode=='prepare-replay' else (load_inputs() and {'status':'checked_saved_inputs','science_calls':0})
    print(json.dumps(result,sort_keys=True))
