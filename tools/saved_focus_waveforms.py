"""Project verified numerical saved traces; external Ge prefix sidecars stay separate."""
import argparse
import csv
import io
import json
import math
from pathlib import Path
import re

import gamma_complete_example as G
import gamma_showcase as S
import scenario_workflow as W
from local_ui_jobs import safe_path

SIDECARS='.local/product-delivery-v1/display-derived'
SOURCES=('simulation/saved_control_edge.jl','simulation/saved_collection_edge.jl','simulation/readout.jl',
    'simulation/readout_profiles.jl','simulation/readout_demo.json','simulation/Project.toml','simulation/Manifest.toml',
    'tools/saved_focus_waveforms.py')

def rows(path,raw=None):return [W.decode_json(line) for line in (path.read_bytes() if raw is None else raw).decode('utf-8-sig').splitlines() if line.strip()]
def key(r):return (r['event_id'],r['global_decay_id'],r['group_id'])

def ring_charge(directory,records,raw=None):
    actual={};header='event_id global_decay_id group_id time_since_origin_ns induced_equivalent_energy_keV'.split()
    with io.StringIO((directory/'response/signals.csv').read_text(encoding='utf-8') if raw is None else raw.decode('utf-8-sig'),newline='') as f:
        reader=csv.DictReader(f);W.require(reader.fieldnames==header,'Exact saved full-charge CSV columns')
        for row in reader:
            k=tuple(int(row[n]) for n in header[:3]);t,q=actual.setdefault(k,([],[]))
            t.append(float(row[header[3]]));q.append(float(row[header[4]]))
    known={key(r):r for r in records if r['record_kind']=='pulse' and r['readout'] is not None}
    W.require(set(actual)==set(known),'Complete saved charge/group census')
    for k,(t,q) in actual.items():
        r=known[k];rd=r['readout'];W.require(len(t)==len(q)==rd['input_sample_count'] and t[0]==q[0]==0 and all(b-a==2 for a,b in zip(t,t[1:])),'Original contiguous signed group grid')
        W.require(all(math.isfinite(v) for v in (*t,*q)) and t[-1]==rd['untruncated_charge_end_ns'] and q[-1]==r['final_induced_keV'],'Original signed endpoints/count')
    return actual

def sidecar(name,root,complete_hash,config_hash):
    directory=safe_path(root,SIDECARS+'/'+name)
    if not directory.exists():return None
    manifest=W.read(directory/'COMPLETE.json')
    W.require(manifest['kind']=='saved_control_edge_sidecar_v1' and manifest['status']=='completed' and manifest['name']==name and
        manifest['complete_sha256']==complete_hash and manifest['configuration_sha256']==config_hash,'External sidecar original authority changed')
    W.require(W.encoded(W.inventory(directory,exclude=('COMPLETE.json',)))==W.encoded(manifest['artifacts']),'External sidecar exact inventory/content')
    request=W.read(directory/'request.json')
    for n,h in request['input_pins'].items():W.require(W.sha(safe_path(root,n))==h,'External sidecar input bytes changed')
    data=W.read(directory/'traces.json');W.require(data['request_sha256']==W.sha(directory/'request.json') and data['complete_sha256']==complete_hash and data['configuration_sha256']==config_hash,'External dense trace request binding')
    return data,W.sha(directory/'COMPLETE.json'),W.sha(directory/'traces.json')

def project(directory,name,configuration_sha256,primary_id,group_id,root=W.ROOT):
    directory=Path(directory);reader=S.Reader(directory);complete=reader.json('COMPLETE.json');complete_hash=reader.seen['COMPLETE.json']
    W.require(complete['configuration_sha256']==configuration_sha256,'Exact saved configuration identity')
    def raw(n):
        stamp=complete['artifacts'][n];return reader.raw(n,stamp['sha256'],stamp['bytes'])
    raw('response/summary.html');summary_hash=reader.seen['response/summary.html']
    report=S.decode(raw('response/run.json'));reply={'kind':'saved_focus_projection_v1','name':name,'configuration_sha256':configuration_sha256,
        'primary_id':primary_id,'group_id':group_id,'summary_sha256':summary_hash,'complete_sha256':complete_hash,'panels':[],
        'sidecar_manifest_sha256':None,'sidecar_data_sha256':None,'clock':'Time since initial primary · ns'}
    if 'cases' in report:
        chosen=[r for r in report['cases'] if r['initial_primary_id']==primary_id]
        W.require(len(chosen)==1 and group_id==(None if chosen[0]['zero_ge'] else 0),'Exact gamma selection')
        case=chosen[0]
        if case['readout'] is None:return dict(reply,status='native_failed_unknown_charge',notes=['Exact native failure; charge/readout remain null.'])
        rd=case['readout'];trace=rd['trace'];q=case['charge_input']['induced_equivalent_energy_keV'];t=case['charge_input']['time_since_initial_primary_ns']
        charge=q;charge_title='Charge · induced equivalent keV';current=trace['current_nA'];edge=None
    else:
        records=rows(directory/'response/scalars.jsonl',raw('response/scalars.jsonl'));chosen=[r for r in records if r['event_id']==primary_id and r['record_kind']=='pulse' and r['group_id']==group_id]
        W.require(len(chosen)==1,'Exact original primary/group selection');case=chosen[0]
        if case['readout'] is None:return dict(reply,status='native_failed_unknown_charge',notes=['Native failure retains exact error/null output.'])
        rd=case['readout'];known=[r for r in rows(directory/'response/traces.jsonl',raw('response/traces.jsonl')) if key(r)==key(case)]
        if not known:return dict(reply,status='original_trace_not_saved',notes=['No original saved waveform for this group; scalar results remain available.'])
        W.require(len(known)==1 and known[0]['origin_time_ns']==case['origin_time_ns'],'Full saved pulse identity/origin')
        trace=known[0]['trace'];t,q=ring_charge(directory,records,raw('response/signals.csv'))[key(case)]
        # Same exact display conversion as the unchanged Readout charge factor.
        factor=1.0*1000/report['ionisation_energy_eV']*1.602176634e-19
        charge=[v*factor*1e15 for v in q];charge_title='Raw native charge · fC';current=trace.get('raw_native_current_nA',trace['current_nA']);edge=None
        reply['clock']='Time since pulse-group origin · ns';reply['global_decay_id']=case['global_decay_id'];reply['origin_time_ns']=case['origin_time_ns']
        saved=sidecar(name,root,complete_hash,configuration_sha256)
        if saved:
            data,manifest_hash,data_hash=saved;matches=[e for e in data['edges'] if e['identity']==dict(event_id=primary_id,global_decay_id=case['global_decay_id'],group_id=group_id,origin_time_ns=case['origin_time_ns'])]
            W.require(len(matches)==1,'External derivative exact group binding');edge=matches[0]
            W.require(edge['retained_original_parity']['passed'] is True,'Saved retained preamp parity')
            reply['sidecar_manifest_sha256']=manifest_hash;reply['sidecar_data_sha256']=data_hash
    focus=min(rd['readout_end_ns'],G.focus_end(t,q));peak={'t':rd['peak_time_ns'],'v':rd['peak_V']}
    shaped=trace['shaped_V'];last=max([peak['t'],*[time for time,v in zip(trace['time_ns'],shaped) if abs(v)>=abs(peak['v'])*.01]]) if peak['v'] else 1000
    shaper=min(rd['readout_end_ns'],2*math.ceil((last+max(100,last*.06))/2))
    reply['panels']=[
        dict(title=charge_title,time_ns=t,values=charge,full_end_ns=t[-1],focus_end_ns=min(t[-1],focus),note='Full signed input remains available. Sampled-variation focus does not prove complete collection; original endpoint/cap flags remain.'),
        dict(title='Raw original-bin current · nA',time_ns=trace['time_ns'],values=current,bin_start_ns=trace['current_bin_start_ns'],bin_end_ns=trace['current_bin_end_ns'],full_end_ns=rd['readout_end_ns'],focus_end_ns=focus,note='Original (start, end] bins and omitted-bin gaps retained.'),
        dict(title='Analog preamp · V',time_ns=trace['time_ns'],values=trace['preamp_V'],full_end_ns=rd['readout_end_ns'],focus_end_ns=edge['captured_stop_ns'] if edge else focus,focus_series=None if edge is None else {'time_ns':edge['time_ns'],'values':edge['preamp_V']},note='Electronics-only dense replay from full saved signed charge; full window is the original sparse trace.' if edge else 'Original retained samples, including the saved early head. Omitted analog samples remain unavailable.'),
        dict(title='Analog shaper · V',time_ns=trace['time_ns'],values=shaped,full_end_ns=rd['readout_end_ns'],focus_end_ns=shaper,peak=peak,note='Gold marker is the unchanged exact sampled peak. ADC/Erec/flags remain unchanged.')]
    reply.update(status='verified_saved_numeric_projection',notes=['Camera controls affect only this selected saved record.'],charge_source_sha256=reader.seen['response/signals.csv' if 'cases' not in report else 'response/run.json'],trace_source_sha256=reader.seen['response/traces.jsonl' if 'cases' not in report else 'response/run.json'])
    reader.recheck()
    return reply

def build(name,root=W.ROOT):
    W.require(re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,47}',name) is not None,'Closed saved run name')
    receipt=W.inspect(name,root);directory=W.run_path(name,root);report=W.read(directory/'response/run.json')
    W.require(report['model_id']=='GeRC02' and report['charge_csv_policy']=='all' and report['wiring_factor']==1.0,'Separately checked saved Ge context only')
    complete_hash=W.sha(directory/'COMPLETE.json');config_hash=receipt['configuration_sha256']
    target=safe_path(root,SIDECARS+'/'+name);W.require(not target.exists(),'Preserve previous derivative evidence')
    records=rows(directory/'response/scalars.jsonl');traces={key(r):r for r in rows(directory/'response/traces.jsonl')};charges=ring_charge(directory,records)
    relative='.local/runs/'+name+'/'
    names=('COMPLETE.json','run.json','resolved-config.json','electronics/profile.json','response/run.json','response/workflow-ring-response.json',
        'response/readout-config.json','response/scalars.jsonl','response/traces.jsonl','response/signals.csv','response/summary.html')
    input_pins={relative+n:W.sha(directory/n) for n in names};source_pins={n:W.sha(safe_path(root,n)) for n in SOURCES}
    groups=[]
    for r in records:
        if r['record_kind']!='pulse' or r['readout'] is None:continue
        t,q=charges[key(r)];trace=traces.get(key(r));stop=G.focus_end(t,q)
        W.require(stop<=20000 and stop<=r['readout']['readout_end_ns'],'Dense camera exceeds explicit bound; preserve sparse view')
        groups.append(dict(identity={k:r[k] for k in ('event_id','global_decay_id','group_id','origin_time_ns')},raw_row_indices=r['raw_row_indices'],
            time_ns=t,charge_keV=q,readout=r['readout'],stop_ns=stop,original_trace=None if trace is None else trace['trace']))
    request=dict(kind='saved_control_edge_request_v1',name=name,model_id=report['model_id'],wiring_factor=report['wiring_factor'],primary_count=receipt['resolved']['selection']['primary_count'],
        configuration_sha256=config_hash,complete_sha256=complete_hash,profile=W.read(directory/'electronics/profile.json'),config=W.read(directory/'response/readout-config.json'),
        calibration=report['calibration'],ionisation_energy_eV=report['ionisation_energy_eV'],groups=groups,input_pins=input_pins,source_pins=source_pins)
    frozen=W.read(Path(root)/'.local/product-delivery-v1/implementation/m14b/SOURCE-FREEZE.json')
    W.require(frozen['status']=='frozen_after_writer_exit' and all(frozen['files'][n]['sha256']==h for n,h in source_pins.items()),'Display sources must be frozen before replay')
    target.mkdir(parents=True);W.write(target/'request.json',request,fresh=True)
    exe=G.G.julia_executable();args=[exe,'--startup-file=no','--project='+str(Path(root)/'simulation'),'--threads=1','--compiled-modules=existing',str(Path(root)/'simulation/saved_control_edge.jl'),'--request',str(target/'request.json'),'--output',str(target/'traces.json')]
    call=G.G.child(args,str(root),1);(target/'worker.log').write_text(call.pop('output'),encoding='utf-8');W.write(target/'child.json',call,fresh=True)
    W.require(call['exit_code']==0,'Saved electronics derivative failed; evidence retained')
    W.inspect(name,root);W.write(target/'COMPLETE.json',dict(kind='saved_control_edge_sidecar_v1',status='completed',name=name,configuration_sha256=config_hash,
        complete_sha256=complete_hash,artifacts=W.inventory(target),source_pins=source_pins),fresh=True)
    sidecar(name,root,complete_hash,config_hash);return {'status':'completed_external_display','name':name,'groups':len(groups),'native_calls':0}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=('build',));p.add_argument('--name',required=True);a=p.parse_args();print(json.dumps(build(a.name),sort_keys=True))
