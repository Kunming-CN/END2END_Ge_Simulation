"""Inspect and render a completed selected native pilot without solving or replaying."""
import argparse, csv, hashlib, html, json, math
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
NS=('cs137-1m','cs10000-v2-diagnostic')
def require(ok,msg):
    if not ok: raise ValueError(msg)
def read(p): return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()
def records(p):
    with p.open(encoding='utf-8') as f:
        for line in f:
            if line.strip(): yield json.loads(line)
def key(r): return (r['namespace'],r['event_id'],r.get('group_id'))
def plot(trace,field,label):
    x,y=trace['time_ns'],trace[field]
    require(len(x)==len(y)>0 and all(math.isfinite(v) for v in [*x,*y]),'Invalid display trace')
    lo,hi=min(y),max(y); span=hi-lo or 1.; duration=max(x[-1],1.)
    pts=' '.join(f'{50+500*t/duration:.3f},{160-120*(v-lo)/span:.3f}' for t,v in zip(x,y))
    return f'<figure><figcaption>{html.escape(label)}</figcaption><svg viewBox="0 0 590 205"><path d="M50 25V160H560" fill="none" stroke="#999"/><polyline points="{pts}" fill="none" stroke="currentColor"/><text x="0" y="25">{hi:.4g}</text><text x="0" y="163">{lo:.4g}</text><text x="50" y="190">0</text><text x="405" y="190">{duration:.5g} ns</text></svg></figure>'

def inspect(pilot):
    terminal=read(pilot/'run.json')
    require(terminal['status'] in ('completed_with_native_failures','completed_provisional_native_response'),'Pilot is not complete')
    summary={'status':terminal['status'],'models':{},'source_files':{},'scope':'Selected engineering pilot; not a million-event response or calibrated spectrum'}
    pulses=[]; traces={}
    for model in ('AK02','SAP22'):
        base=pilot/model; report=read(base/'run.json'); contract=read(base/'input-contract.json')
        require(report['status'] in ('completed_with_native_failures','completed_provisional_native_response'),'Model incomplete')
        require(report['counts']==terminal['models'][model]['counts'],'Terminal/model counts differ')
        for name,h in report['artifacts'].items():
            p=(base/name).resolve(); require(p.is_relative_to(base.resolve()) and sha(p)==h,'Changed pilot artifact')
        old=read(ROOT/f'.local/peak-native-delivery/cs10000-v2/{model}/response/run.json')
        require(report['field_fingerprint_before']==report['field_fingerprint_after']==old['field_fingerprint'],'Fields differ from preserved baseline')
        require(report['calibration']==old['calibration'] and report['profile_sha256']==old['profile_sha256'],'Calibration/profile changed')
        events={(e['namespace'],e['event_id']):e for e in contract['events']}
        for ns in NS:
            rr=list(records(base/ns/'scalars.jsonl')); pp=[r for r in rr if r['record_kind']=='primary']; qq=[r for r in rr if r['record_kind']=='pulse']
            require(len(pp)==report['counts'][ns]['primaries'] and len(qq)==report['counts'][ns]['groups'],'Scalar census mismatch')
            require(len({r['event_id'] for r in pp})==len(pp) and len({key(r) for r in qq})==len(qq),'Duplicate scalar identity')
            expected={i:e for (s,i),e in events.items() if s==ns}
            require({r['event_id'] for r in pp}==set(expected),'Lost selected primary')
            require({(r['event_id'],r['group_id']) for r in qq}=={(i,g['group_id']) for i,e in expected.items() for g in e['pulse_groups']},'Lost or added selected group')
            require(sum(r['zero_ge'] for r in pp)==report['counts'][ns]['zero_ge_primaries'],'Zero census mismatch')
            tt=list(records(base/ns/'traces.jsonl')); require(len({key(r) for r in tt})==len(tt),'Duplicate trace')
            for t in tt: traces[(model,*key(t))]=t
            for r in qq:
                e=expected[r['event_id']]; g=next(g for g in e['pulse_groups'] if g['group_id']==r['group_id'])
                for k in ('identity','global_decay_id','seed_event_id','seed_family','source_campaign_sha256','source_lh5_sha256'):
                    require(r[k]==e[k],'Changed response identity: '+k)
                require(r.get('group')==g and r['raw_row_indices']==g['row_indices'],'Changed group mapping')
                edep=math.fsum(s['energy_keV'] for s in e['steps'] if s['raw_row_index'] in g['row_indices'])
                require(math.isclose(edep,r['deposited_energy_keV'],rel_tol=1e-12,abs_tol=1e-10),'Changed truth energy')
                failed=r['status']=='native_transport_failed'; tr=traces.get((model,*key(r)))
                if failed:
                    require(r['readout'] is None and r['final_induced_keV'] is None and r['accepted'] is False and tr is None,'Fabricated failed response')
                else:
                    require(tr is not None and r['readout']['current_balance']['passed'],'Missing trace or charge balance')
                    require(tr['identity']==e['identity'] and tr['origin_time_ns']==g['origin_time_ns'],'Trace identity/origin')
                pulses.append({'model':model,**r})
            require(len(tt)==sum(r['status']!='native_transport_failed' for r in qq),'Unexpected trace census')
            c=report['counts'][ns]
            require(c['accepted']==sum(r['accepted'] for r in qq) and c['native_failed']==sum(r['status']=='native_transport_failed' for r in qq),'Acceptance/failure census mismatch')
            if ns=='cs10000-v2-diagnostic':
                oldcase=next(records(ROOT/f'.local/peak-native-delivery/cs10000-v2/{model}/response/native-failures.jsonl'))['pulse']
                require(len(qq)==1 and qq[0]['event_id']==oldcase['event_id'],'Historical control identity changed')
        summary['models'][model]={'counts':report['counts'],'selected_census':contract['selected_census'],'input_population_reference':contract['input_population_reference'],
            'omitted_census':contract['omitted_census'],'native_seconds':report['native_drift_and_charge_seconds'],
            'field_seconds':report['field_timings'],'calibration_and_fields_match_old':True,'artifacts_bytes':report['artifact_bytes']}
        summary['models'][model]['historical_control']={'event_id':oldcase['event_id'],'original_error':oldcase['native_error'],'new_status':qq[0]['status'],'error_reproduced':qq[0].get('native_error')==oldcase['native_error'],'accepted':qq[0]['accepted'],'interpretation':'A non-reproduced failure is not a numerical fix; original evidence remains frozen.'}
        for p in (base/'run.json',base/'input-contract.json'):
            summary['source_files'][str(p.relative_to(ROOT))]=sha(p)
    summary['source_files'][str((pilot/'run.json').relative_to(ROOT))]=sha(pilot/'run.json')
    summary['compute_export_seconds']=terminal['compute_export_seconds']
    return summary,pulses,traces

def build(pilot,output):
    pilot=pilot.resolve(); output=output.absolute()
    require(pilot.is_relative_to(ROOT/'.local') and output.parent==(ROOT/'.local/native-bridge-pilot') and not output.exists(),'New report folder required')
    from verify_native_bridge_output import verify
    verify(pilot)
    summary,pulses,traces=inspect(pilot); output.mkdir()
    page=['<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Selected HDF5 to ADC pilot</title><style>body{font:16px/1.5 system-ui;max-width:1150px;margin:auto;padding:20px;overflow-wrap:anywhere}table{border-collapse:collapse;width:100%}td,th{padding:8px;border-bottom:1px solid #ccc;white-space:nowrap}svg{width:100%}.scroll{overflow:auto}.plots{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr))}figure{margin:12px}summary{cursor:pointer}pre{white-space:pre-wrap}</style><h1>Saved HDF5 → native charge → synthetic peak ADC</h1><p>Selected pilot only. Two million source decays remain preserved; nonselected charge/ADC responses are unknown. Historical failures are separate diagnostic namespaces. Finite trajectory caps, signed signals and native failures remain visible. No calibration to event truth, no physical FWHM or measured-spectrum agreement.</p>']
    for model,info in summary['models'].items():
        control=info['historical_control']
        if not control['error_reproduced']:
            page.append('<p><strong>Historical control discrepancy:</strong> '+html.escape(model)+' primary '+str(control['event_id'])+' did not reproduce its saved native failure in this mixed pilot. This is not a fix; context reproducibility remains unresolved. Original failure evidence is preserved.</p>')
    page.append('<p><a href="report.json">Verified counts and source hashes</a> | <a href="pulses.csv">Selected pulse summary</a></p>')
    fields=['model','namespace','event_id','group_id','deposited_keV','induced_keV','reconstructed_keV','accepted','step_limited_parcels','status']
    with (output/'pulses.csv').open('x',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
        page.append('<div class="scroll"><table><tr>'+''.join('<th>'+html.escape(k)+'</th>' for k in fields)+'</tr>')
        for r in pulses:
            readout=r['readout']; flags=r.get('transport_flags'); rec={'model':r['model'],'namespace':r['namespace'],'event_id':r['event_id'],'group_id':r['group_id'],
                'deposited_keV':r['deposited_energy_keV'],'induced_keV':r['final_induced_keV'],'reconstructed_keV':None if readout is None else readout['reconstructed_energy_keV'],
                'accepted':r['accepted'],'step_limited_parcels':None if flags is None else flags['step_limits'],'status':r['status']}
            writer.writerow(rec);page.append('<tr>'+''.join('<td>'+html.escape(str(rec[k]))+'</td>' for k in fields)+'</tr>')
    page.append('</table></div>')
    for r in pulses:
        page.append(f'<details><summary>{r["model"]} · {html.escape(r["namespace"])} · primary {r["event_id"]} / group {r["group_id"]}</summary>')
        t=traces.get((r['model'],*key(r)))
        if t:
            page.append('<div class="plots">'+''.join(plot(t['trace'],k,label) for k,label in [('induced_charge_fC','Induced charge (fC)'),('current_nA','Original-bin current (nA)'),('preamp_V','Preamp (V)'),('shaped_V','Analog shaper (V)')])+'</div><p>Bounded display samples; current belongs to its original intervals. Full signed native charge remains in the pilot signals.csv. ADC output is a peak code, not a waveform digitizer.</p>')
        else: page.append('<p>Native response unavailable; no synthetic zero waveform is drawn.</p>')
        page.append('<pre>'+html.escape(json.dumps(r,indent=2))+'</pre></details>')
    (output/'comparison.html').write_text(''.join(page),encoding='utf-8')
    summary['renderer_sha256']=sha(Path(__file__));summary['artifacts']={n:sha(output/n) for n in ('comparison.html','pulses.csv')}
    with (output/'report.json').open('x',encoding='utf-8') as f:json.dump(summary,f,indent=2,allow_nan=False)
    print(json.dumps(summary))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--pilot',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();build(a.pilot,a.output)
