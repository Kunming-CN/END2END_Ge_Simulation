"""Lossless saved40 publication adapter; this entry never runs a producer."""
import argparse
import copy
import json
from pathlib import Path
import shutil

import gamma_complete_example as F
import gamma_showcase as S

ROOT=F.ROOT
BASE=F.BASE
KIND='saved_gamma_complete_publication_v1'
TEMPLATE='tools/gamma_complete_showcase.html'
JAVASCRIPT='tools/focused_plots.js'
FREEZE='.local/product-delivery-v1/implementation/m14b/SOURCE-FREEZE.json'
SOURCE_FILES=(*F.CODE,TEMPLATE,JAVASCRIPT,'tools/gamma_complete_showcase.py',
    'tools/test_gamma_complete_showcase.py','tools/gamma_showcase.py','tools/gamma_publication.py',
    'tools/build_site.py','tools/site_restructure.py','tools/check_site.py')
FILES=S.FILES

def sources():
    return {n:{'sha256':S.sha((ROOT/n).read_bytes()),'bytes':(ROOT/n).stat().st_size} for n in SOURCE_FILES}

def freeze():
    frozen=S.decode((ROOT/FREEZE).read_bytes())
    S.require(frozen['status']=='frozen_after_writer_exit','Export sources are not frozen after writer exit')
    exit_path=ROOT/frozen['writer_exit_path'];exited=S.decode(exit_path.read_bytes())
    S.require(exited['status']=='exited' and S.sha(exit_path.read_bytes())==frozen['writer_exit_sha256'],'Writer exit binding')
    current=sources()
    for n,v in current.items():S.exact(frozen['files'][n],v,'Frozen exporter source')
    return current

def portable(run,report):
    r=copy.deepcopy(run);p=copy.deepcopy(report)
    for stage in r['stages']:
        a=stage['arguments'];S.require(len(a)==10 and Path(a[5]).name=='gamma_complete_example.jl','Known completion command')
        a[0]='{JULIA_EXECUTABLE}';a[2]='--project=simulation';a[5]='simulation/gamma_complete_example.jl'
        a[7]='{SAVED_COMPLETION}/'+stage['model_id']+'/request.json';a[9]='{SAVED_COMPLETION}/'+stage['model_id']
    runtime=p['runtime'];runtime['executable']='{JULIA_EXECUTABLE}'
    for key in ('native_source','readout_source','worker_source','completion_worker_source'):
        runtime[key]='simulation/'+Path(runtime[key]).name
    return r,p

def validate_data(data):
    S.require(data['kind']=='saved_gamma_complete_showcase_v1' and data['schema_version']==1,'Completed public schema')
    science=data['science'];S.require(data['science_sha256']==S.typed_digest(science),'Exact serialized scientific values')
    S.exact(science['source']['original_receipt_pins'],S.PINS,'Old6 authority preserved')
    S.require([m['model_id'] for m in science['models']]==list(S.MODELS),'Two original detector models')
    total_zeros=total_positive=total_failed=0
    for model in science['models']:
        report=model['report'];cal=model['calibration'];ident=model['model_id']
        S.exact(report['readout_config'],dict(S.CONFIG,expected_primary_count=20),'Only authorized census change')
        S.exact(cal['config'],report['readout_config'],'Actual calibrated configuration')
        S.exact(cal['calibration'],report['calibration'],'Independent injection calibration')
        cases=report['cases'];ledger=model['truth_ledger']
        S.require([c['initial_primary_id'] for c in cases]==list(range(20)) and [e['initial_primary_id'] for e in ledger]==list(range(20)),'Full40 IDs')
        plan={'readout_config':report['readout_config'],'expected_calibration':report['calibration'],'native_failure_policy':report['native_failure_policy']}
        for index,(row,case) in enumerate(zip(ledger,cases)):
            S.require(row['response_index']==index and row['selected'] is True and row['processing_status']==case['status'],'Lossless response reference')
            F.validate_case(case,row['source_truth'],plan)
            total_zeros+=case['zero_ge'];total_positive+=not case['zero_ge'];total_failed+=case['status']=='native_failed'
            edge=model['display_edges'].get(str(index))
            if case['charge_input'] is None:S.require(edge is None,'Failed charge has no invented dense output')
            else:
                S.require(edge is not None and edge['origin']=='same_electronics_replay_from_saved_signed_charge','Dense replay origin')
                S.require(edge['identity']=={'model_id':ident,'initial_primary_id':index,'group_id':None if case['zero_ge'] else 0},'Dense event identity')
                S.require(edge['case_sha256']==science['source']['artifacts'][ident+'/event-'+str(index)+'.json']['sha256'],'Dense full response binding')
                S.require(edge['retained_original_parity']['passed'] is True and len(edge['time_ns'])==len(edge['preamp_V'])==edge['captured_sample_count'],'Dense parity/count')
                S.require(edge['time_ns']==[float(i*2) for i in range(edge['captured_sample_count'])] and edge['captured_stop_ns']==edge['time_ns'][-1],'Dense exact analog grid')
                S.require(edge['original_readout_source_sha256']=='dfc0bfcdafd2b26bf5b73135d372dde15d2509bd8d3c4b83fefdc2bf9a1ab3c0','Frozen electronics source')
    S.require(total_zeros==29 and total_positive==11,'Known zero/positive census')
    S.require(science['run']['additional_radiation_calls']==0 and science['run']['field_solve_seconds']==0.0,'No radiation/field reprocessing')
    S.public_safe(data)

def render(data):
    template=(ROOT/TEMPLATE).read_text(encoding='utf-8');javascript=(ROOT/JAVASCRIPT).read_text(encoding='utf-8')
    S.require(template.count(S.TOKEN)==1 and template.count('__FOCUSED_PLOTS_JS__')==1,'Template token census')
    return template.replace(S.TOKEN,S.embedded_data(data)).replace('__FOCUSED_PLOTS_JS__',javascript).encode('utf-8')

def export():
    current=freeze();directory=ROOT/BASE/'example';F.verify(directory)
    complete=S.decode((directory/'COMPLETE.json').read_bytes());run=S.decode((directory/'run.json').read_bytes())
    science={'source':{'original_receipt_pins':S.PINS,'complete_sha256':S.sha((directory/'COMPLETE.json').read_bytes()),
        'run_sha256':S.sha((directory/'run.json').read_bytes()),'artifacts':complete['artifacts'],'counts':complete['counts'],
        'source_pins':run['source_pins']},'run':None,'models':[]};csv_files={}
    for ident in S.MODELS:
        base=directory/ident;report=S.decode((base/'report.json').read_bytes());public_run,public_report=portable(run,report)
        science['run']=public_run
        original=S.decode((base/'request.json').read_bytes());ledger=[S.decode(line) for line in (base/'truth-ledger.jsonl').read_bytes().splitlines()]
        # Each response is serialized once. The indexed reference reconstructs
        # the complete truth ledger exactly, retaining every duplicate value.
        for i,row in enumerate(ledger):
            S.exact(row.pop('response'),report['cases'][i],'Lossless ledger/report equivalence');row['response_index']=i
        edges={str(c['initial_primary_id']):S.decode((base/('collection-edge-'+str(c['initial_primary_id'])+'.json')).read_bytes()) for c in report['cases'] if c['charge_input'] is not None}
        science['models'].append(dict(model_id=ident,report=public_report,truth_ledger=ledger,display_edges=edges,
            calibration=S.decode((base/'calibration.json').read_bytes()),source_manifest=original['source_manifest'],prepared_metadata=original['prepared']))
        csv_files[ident+'-signals.csv']=(base/'signals.csv').read_bytes()
    limitations=list(run['limitations'])+[
        'All40 original primaries are processed:29 known zero inputs and11 positive primaries; native failures keep exact errors and null unknown charge/readout.',
        'Old6 response files remain byte exact. Seven additional positive events use saved fields and radiation:118 whole Ge rows,105 positive-energy native rows,3360 planned carrier parcel endpoints; native failures preserve unknown endpoints as null.',
        'Collection-edge focus is a sampled-variation camera. Small late changes and10000ns caps remain available in Full saved window.',
        'Dense early preamp points are separately labeled same-electronics replay from full saved signed charge, not recovery of unsaved original analog arrays.',
        'Public truth-ledger response_index references the single complete report case losslessly; all events, values, deposits, identities and flags remain present.']
    data=dict(kind='saved_gamma_complete_showcase_v1',schema_version=1,science=science,science_sha256=S.typed_digest(science),
        units=S.UNITS,limitations=limitations,presentation=dict(encoding=S.ENCODING,template_sha256=current[TEMPLATE]['sha256'],
            javascript_sha256=current[JAVASCRIPT]['sha256'],exporter_sha256=current['tools/gamma_complete_showcase.py']['sha256'],current_sources=current))
    validate_data(data);payload=dict(csv_files,**{'data.json':S.canonical(data),'gamma.html':render(data)})
    output=S.no_links(ROOT/BASE/'bundle');S.require(not output.exists(),'Preserve prior derived bundle');output.mkdir()
    for name,raw in payload.items():(output/name).write_bytes(raw)
    F.verify(directory);freeze()
    manifest=dict(kind=KIND,status='completed',science_sha256=data['science_sha256'],source=science['source'],presentation=data['presentation'],
        files={n:{'sha256':S.sha(raw),'bytes':len(raw)} for n,raw in payload.items()})
    (output/'publication.json').write_bytes(S.canonical(manifest));validate_bundle(output)
    return {'status':'completed_saved_export','events':40,'additional_native_calls':7,'bytes':sum(p.stat().st_size for p in output.iterdir())}

def validate_bundle(directory):
    directory=S.no_links(directory);S.require({p.name for p in directory.iterdir()}==set(FILES)|{'publication.json'},'Exact completed publication inventory')
    manifest=S.decode((directory/'publication.json').read_bytes());S.require(manifest['kind']==KIND and manifest['status']=='completed','Completed publication authority')
    S.require(set(manifest['files'])==set(FILES),'Bounded file census')
    payload={}
    for name,stamp in manifest['files'].items():
        raw=(directory/name).read_bytes();S.require(S.sha(raw)==stamp['sha256'] and len(raw)==stamp['bytes'],'Changed public artifact');payload[name]=raw
    data=S.decode(payload['data.json']);validate_data(data)
    S.require(payload['data.json']==S.canonical(data),'Exact scientific serialization')
    from saved_focus_pages import historical_display, validate_display_binding, display_render
    if 'display_upgrade' in manifest:
        if validate_display_binding('gamma',manifest):
            S.require(payload['gamma.html']==display_render('gamma',data),'Exact upgraded gamma display')
    elif not historical_display('gamma',(directory/'publication.json').read_bytes()):
        S.require(payload['gamma.html']==render(data),'Exact serialization/template')
    S.exact(manifest['source'],data['science']['source'],'Source authority');S.exact(manifest['presentation'],data['presentation'],'Presentation hashes')
    S.require(manifest['science_sha256']==data['science_sha256'],'Science hash binding')
    for model in data['science']['models']:
        raw=payload[model['model_id']+'-signals.csv'];stamp=manifest['source']['artifacts'][model['model_id']+'/signals.csv']
        S.require(S.sha(raw)==stamp['sha256'] and len(raw)==stamp['bytes'],'Full signed CSV bytes')
    return data

def assemble(source,target,replace=False):
    source=S.no_links(source);target=S.no_links(target);validate_bundle(source)
    if target.exists():
        S.require(replace and target==S.no_links(ROOT/'.local/site-build/examples/gamma-native'),'Only checked staged replacement')
        from gamma_publication import validate_bundle as checked
        checked(target)
    else:target.mkdir(parents=True)
    for n in (*FILES,'publication.json'):shutil.copyfile(source/n,target/n)
    validate_bundle(target)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=('export','validate'));p.add_argument('bundle',nargs='?',type=Path);a=p.parse_args()
    print(json.dumps(export() if a.mode=='export' else (validate_bundle(a.bundle) and {'status':'verified_completed_bundle','science_calls':0}),sort_keys=True))
