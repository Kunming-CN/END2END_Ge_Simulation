"""Build final saved native-response report by joining checked scalar output to saved Geant4 truth."""
import csv,gzip,hashlib,json,math,statistics
from pathlib import Path
from html import escape
ROOT=Path(__file__).resolve().parents[1]
NATIVE=ROOT/'.local/native-final-analysis-v3'
TRUTH=ROOT/'.local/million-analysis/analysis-results'
MODELS=('AK02','SAP22')
def require(ok,msg):
    if not ok: raise ValueError(msg)
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def write(p,x):
    with Path(p).open('x',encoding='utf-8',newline='\n') as f:
        json.dump(x,f,indent=2,allow_nan=False);f.write('\n')
def num(v):
    return None if v in ('',None) else float(v)
def integer(v):
    return None if v in ('',None) else int(v)
def boolean(v):
    return None if v in ('',None) else v.lower()=='true'
def quantiles(values):
    if not values:return None
    s=sorted(values); n=len(s)
    def q(p):
        x=p*(n-1); a=int(math.floor(x)); b=min(a+1,n-1); t=x-a
        return s[a]*(1-t)+s[b]*t
    return {'n':n,'p05':q(.05),'median':q(.5),'p95':q(.95),'min':s[0],'max':s[-1]}
def load_native():
    complete=read(NATIVE/'COMPLETE.json'); summary=read(NATIVE/'summary.json')
    require(complete['status']=='verified_native_scalar_analysis','Native scalar analysis incomplete')
    require(complete['summary_sha256']==sha(NATIVE/'summary.json'),'Native summary hash')
    require(complete['groups_csv_sha256']==sha(NATIVE/'groups.csv'),'Native ledger hash')
    rows={}
    with (NATIVE/'groups.csv').open(encoding='utf-8',newline='') as f:
        for r in csv.DictReader(f):
            key=(r['model'],int(r['event_id']),int(r['group_id']))
            require(key not in rows,'Duplicate native scalar key')
            rows[key]=dict(r,accepted=boolean(r['accepted']),deposited_keV=float(r['deposited_keV']),
                induced_keV=num(r['induced_keV']),analog_keV=num(r['analog_keV']),
                reconstructed_keV=num(r['reconstructed_keV']),adc_code=integer(r['adc_code']),
                step_limits=integer(r['step_limits']),stopped_without_contact=integer(r['stopped_without_contact']),
                negative_input=boolean(r['negative_input']),below_threshold=boolean(r['below_threshold']),
                saturated=boolean(r['saturated']),gate_limited=boolean(r['gate_limited']),
                window_limited=boolean(r['window_limited']),
                contact_start_energy_keV=num(r['contact_start_energy_keV']))
    require(len(rows)==summary['totals']['groups']==23693,'Native scalar census')
    return complete,summary,rows
def load_truth():
    complete=read(TRUTH/'COMPLETE.json'); summary=read(TRUTH/'summary.json')
    require(complete['status']=='verified_saved_data_analysis','Truth analysis incomplete')
    require(complete['summary_sha256']==sha(TRUTH/'summary.json'),'Truth summary hash')
    require(summary['files']['positive-groups.csv.gz']['sha256']==sha(TRUTH/'positive-groups.csv.gz'),
            'Truth classification ledger hash')
    rows={}
    with gzip.open(TRUTH/'positive-groups.csv.gz','rt',encoding='utf-8',newline='') as f:
        for r in csv.DictReader(f):
            key=(r['model'],int(r['global_decay_id']),int(r['group_id']))
            require(key not in rows,'Duplicate truth group')
            cats=r['categories'].split('|')
            energy_class=next((x for x in ('full','partial','unknown') if x in cats),None)
            require(energy_class is not None,'Missing truth energy class')
            rows[key]={'truth_class':energy_class,'categories':r['categories'],
                'source_photon_energy_keV':num(r['source_photon_energy_keV']),
                'classifier_status':r['classifier_status'],'ge_energy_keV':float(r['ge_energy_keV'])}
    require(len(rows)==sum(summary['models'][m]['isolated_groups'] for m in MODELS),'Truth group census')
    return complete,summary,rows
def hist(values,lo=0.0,hi=1000.0,width=1.0):
    n=int(round((hi-lo)/width)); counts=[0]*n; under=over=0
    for v in values:
        if v is None:continue
        if v<lo:under+=1
        elif v>=hi:over+=1
        else:counts[min(n-1,int((v-lo)//width))]+=1
    return {'lower_keV':lo,'upper_keV':hi,'width_keV':width,'counts':counts,
            'underflow':under,'overflow':over,'total':len(values)}
def svg_overlay(truth,response,x0,x1,width=760,height=260):
    bw=1.0; start=int(x0); end=int(x1); n=end-start
    tv=[0]*n; rv=[0]*n
    for v in truth:
        if start<=v<end:tv[int(v)-start]+=1
    for v in response:
        if start<=v<end:rv[int(v)-start]+=1
    ymax=max(tv+rv+[1]); left=52; right=12; top=16; bottom=35
    W=width-left-right; H=height-top-bottom
    def pts(vals):
        return ' '.join(f'{left+(i+.5)*W/n:.2f},{top+H-v*H/ymax:.2f}' for i,v in enumerate(vals))
    ticks=''.join(f'<text x="{left+(x-start)*W/n:.1f}" y="{height-10}" text-anchor="middle">{x}</text>'
                  for x in range(start,end+1,max(1,(end-start)//5)))
    return (f'<svg viewBox="0 0 {width} {height}" role="img"><rect x="{left}" y="{top}" width="{W}" height="{H}" fill="none" stroke="#999"/>'
        f'<polyline points="{pts(tv)}" fill="none" stroke="#406090" stroke-width="1.4"/>'
        f'<polyline points="{pts(rv)}" fill="none" stroke="#b05040" stroke-width="1.4"/>'
        f'{ticks}<text x="8" y="{top+12}">{ymax}</text><text x="8" y="{top+H}">0</text></svg>')
def main(out):
    out=Path(out).resolve();require(out.is_relative_to((ROOT/'.local').resolve()),'Output outside .local')
    require(not out.exists(),'Use new report output');out.mkdir()
    ncomplete,nsummary,native=load_native();tcomplete,tsummary,truth=load_truth()
    require(set(native)==set(truth),'Native/truth group identity mismatch')
    joined=[];models={}
    for m in MODELS:
        models[m]={'response':{'groups':0,'native_completed':0,'native_failed':0,'accepted':0,'readout_rejected':0,
            'failure_classes':{},'rejection_reasons':{}},'truth_classes':{},'line_full':{},
            'engineering_ratios':{},'bands':{}}
    for key,n in native.items():
        t=truth[key];require(math.isclose(n['deposited_keV'],t['ge_energy_keV'],rel_tol=1e-12,abs_tol=1e-9),'Truth/native energy mismatch')
        m=key[0];s=models[m]['response'];s['groups']+=1
        s['native_completed']+=n['status']=='native_completed';s['native_failed']+=n['status']=='native_failed'
        s['accepted']+=n['accepted'] is True
        if n['status']=='native_completed' and not n['accepted']:s['readout_rejected']+=1
        if n['status']=='native_failed':
            fc=n['failure_class'] or 'unknown_native_failure';s['failure_classes'][fc]=s['failure_classes'].get(fc,0)+1
        elif not n['accepted']:
            rr=n['rejection_reason'] or 'unknown';s['rejection_reasons'][rr]=s['rejection_reasons'].get(rr,0)+1
        models[m]['truth_classes'][t['truth_class']]=models[m]['truth_classes'].get(t['truth_class'],0)+1
        joined.append({**n,'truth_class':t['truth_class'],'categories':t['categories'],
            'source_photon_energy_keV':t['source_photon_energy_keV'],'classifier_status':t['classifier_status']})
    require(sum(models[m]['response']['native_failed'] for m in MODELS)==nsummary['totals']['native_failed'],'Failure count mismatch')
    fieldnames=['model','event_id','group_id','truth_class','categories','source_photon_energy_keV',
        'classifier_status','status','failure_class','accepted','rejection_reason','deposited_keV',
        'induced_keV','analog_keV','reconstructed_keV','adc_code','carrier_parcels','geometric_contacts',
        'step_limits','stopped_without_contact','negative_input','below_threshold','saturated',
        'gate_limited','window_limited','contact_start_energy_keV','error_type','error_message','result_key']
    with gzip.open(out/'groups.csv.gz','wt',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fieldnames);w.writeheader()
        for r in sorted(joined,key=lambda x:(x['model'],int(x['event_id']),int(x['group_id']))):
            w.writerow({k:r.get(k) for k in fieldnames})
    histograms={}
    for m in MODELS:
        rows=[r for r in joined if r['model']==m]
        deposited=[r['deposited_keV'] for r in rows]
        induced=[r['induced_keV'] for r in rows if r['induced_keV'] is not None]
        analog=[r['analog_keV'] for r in rows if r['analog_keV'] is not None]
        reconstructed=[r['reconstructed_keV'] for r in rows if r['accepted'] and r['reconstructed_keV'] is not None]
        line=[r for r in rows if r['truth_class']=='full' and r['source_photon_energy_keV'] is not None and 660<=r['source_photon_energy_keV']<=663]
        models[m]['line_full']={'truth_groups':len(line),'native_failed':sum(r['status']=='native_failed' for r in line),
            'readout_rejected':sum(r['status']=='native_completed' and not r['accepted'] for r in line),
            'accepted':sum(r['accepted'] is True for r in line),
            'accepted_reco_650_670':sum(r['accepted'] and r['reconstructed_keV'] is not None and 650<=r['reconstructed_keV']<670 for r in line)}
        models[m]['bands']={'truth_groups_650_670':sum(650<=v<670 for v in deposited),
            'accepted_reco_650_670':sum(650<=v<670 for v in reconstructed)}
        ratios=[r['induced_keV']/r['deposited_keV'] for r in rows if r['induced_keV'] is not None and r['deposited_keV']>0]
        line_reco=[r['reconstructed_keV'] for r in line if r['accepted'] and r['reconstructed_keV'] is not None]
        models[m]['engineering_ratios']={'induced_over_deposit':quantiles(ratios),
            'line_full_accepted_reconstructed_keV':quantiles(line_reco)}
        histograms[m]={'deposited_truth':hist(deposited),'native_induced':hist(induced),
            'analog_shaped':hist(analog),'reconstructed_accepted':hist(reconstructed)}
    public_summary={'kind':'million_native_response_summary_v1','status':'completed_response_comparison',
        'native_scalar_summary_sha256':sha(NATIVE/'summary.json'),'truth_summary_sha256':sha(TRUTH/'summary.json'),
        'models':{},'totals':nsummary['totals'],
        'scope':'One million initial Cs137 decays per detector. Saved Geant4 truth joined to completed native SSD and synthetic peak-ADC response; no calculation rerun.',
        'limitations':nsummary['limitations']+[
            'Accepted reconstructed spectra omit native failures and electronics rejections; denominators are shown explicitly.',
            'No added Fano/noise model or measured-spectrum fit; histogram width is not physical detector FWHM.',
            'Induced/deposited ratios are engineering diagnostics, not calibrated charge-collection efficiency.'
        ]}
    for m in MODELS:
        tm=tsummary['models'][m]; public_summary['models'][m]={**models[m],
            'initial_decays':tm['initial_decays'],'zero_ge_decays':tm['zero_ge_decays'],
            'positive_ge_decays':tm['positive_ge_decays'],'isolated_groups':tm['isolated_groups'],
            'line_photons_660_663':tm['emitted_line_photons']}
    write(out/'summary.json',public_summary);write(out/'histograms.json',histograms)
    with (out/'histograms.csv').open('x',encoding='utf-8',newline='') as f:
        w=csv.writer(f);w.writerow(['model','stage','kind','bin_lower_keV','bin_upper_keV','count','per_initial_decay'])
        for m in MODELS:
            initial=public_summary['models'][m]['initial_decays']
            for stage,h in histograms[m].items():
                emitted=0
                for i,c in enumerate(h['counts']):
                    lo=h['lower_keV']+i*h['width_keV'];w.writerow([m,stage,'bin',lo,lo+h['width_keV'],c,c/initial]);emitted+=c
                for kind in ('underflow','overflow'):
                    c=h[kind];w.writerow([m,stage,kind,'','',c,c/initial]);emitted+=c
                require(emitted==h['total'],'Histogram CSV omits entries: '+m+'/'+stage)
    css='''body{font:16px/1.5 system-ui;max-width:1150px;margin:auto;padding:22px;color:#16283a}table{border-collapse:collapse;width:100%}th,td{padding:7px 9px;border-bottom:1px solid #ccd;text-align:right}th:first-child,td:first-child{text-align:left}.note{background:#f3f6f8;padding:14px;margin:14px 0}.plots{display:grid;grid-template-columns:1fr;gap:15px}svg{width:100%;height:auto}code{overflow-wrap:anywhere}.legend span{display:inline-block;width:1em;height:.2em;margin:0 .35em} @media(max-width:600px){body{padding:12px;font-size:15px}table{font-size:12px}.scroll{overflow:auto}}'''
    html=['<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
          '<title>1M Cs137 native SSD response</title>',f'<style>{css}</style><h1>1M Cs137: Geant4 truth → native SSD → peak ADC</h1>',
          '<p class="note">Completed engineering response from the saved one-million-decay-per-detector campaign. Native/input-domain failures remain unknown; electronics rejects remain separate. Synthetic electronics only—no measured-spectrum fit, physical FWHM or calibrated CCE claim.</p>',
          '<p>Counts below are isolated pulse groups from <strong>1,000,000 initial Cs137 decays per detector</strong> in the nominal uncollimated cryostat geometry. They are not efficiencies or counts of unique detected decays. The saved grouping uses reset 100 µs half-open windows; no activity/live-time/pileup model is claimed.</p>']
    html.append('<div class="scroll"><table><tr><th>Quantity</th><th>AK02</th><th>SAP22</th></tr>')
    rowspec=[('Initial Cs137 decays','initial_decays'),('Positive Ge groups','isolated_groups')]
    for label,key in rowspec:html.append(f'<tr><td>{label}</td>'+''.join(f'<td>{public_summary["models"][m][key]:,}</td>' for m in MODELS)+'</tr>')
    for label,key in [('Native completed','native_completed'),('Native/input failures','native_failed'),('ADC accepted','accepted'),('Readout rejected','readout_rejected')]:
        html.append(f'<tr><td>{label}</td>'+''.join(f'<td>{public_summary["models"][m]["response"][key]:,}</td>' for m in MODELS)+'</tr>')
    html.append('</table></div>')
    html.append('<h2>Failure accounting</h2><div class="scroll"><table><tr><th>Model</th><th>Boundary numerical</th><th>Input/contact domain</th><th>Below threshold</th></tr>')
    for m in MODELS:
        rr=public_summary['models'][m]['response']
        html.append(f'<tr><td>{m}</td><td>{rr["failure_classes"].get("boundary_stall",0):,}</td><td>{rr["failure_classes"].get("input_domain_compatibility",0):,}</td><td>{rr["rejection_reasons"].get("below_threshold",0):,}</td></tr>')
    html.append('</table></div><p>Boundary/input failures have truth but no charge or ADC result. Below-threshold groups completed native transport but were rejected by electronics.</p>')
    html.append('<h2>662 keV line-photon full-energy candidates</h2><div class="scroll"><table><tr><th>Model</th><th>Truth candidates</th><th>Native failed</th><th>Readout rejected</th><th>Accepted</th><th>Accepted in 650–670 keV</th></tr>')
    for m in MODELS:
        x=public_summary['models'][m]['line_full']
        html.append(f'<tr><td>{m}</td><td>{x["truth_groups"]:,}</td><td>{x["native_failed"]:,}</td><td>{x["readout_rejected"]:,}</td><td>{x["accepted"]:,}</td><td>{x["accepted_reco_650_670"]:,}</td></tr>')
    html.append('</table></div><p>Line-full means the saved full-containment candidate classification associated with a 660–663 keV source photon. The [650,670) keV values are broad-window reconstructed counts, not fitted photopeak areas or efficiencies.</p>')
    html.append('<h2>Spectrum comparison</h2><p class="legend"><span style="background:#406090"></span>Geant4 deposited-energy truth &nbsp; <span style="background:#b05040"></span>accepted peak-ADC reconstructed energy. Both are raw counts from the same one-million initial decays/model; zero-deposit decays are not plotted.</p>')
    for m in MODELS:
        rows=[r for r in joined if r['model']==m];dep=[r['deposited_keV'] for r in rows];rec=[r['reconstructed_keV'] for r in rows if r['accepted'] and r['reconstructed_keV'] is not None]
        html.append(f'<h3>{m}: 0–750 keV</h3>'+svg_overlay(dep,rec,0,750))
        html.append(f'<h3>{m}: 620–680 keV zoom</h3>'+svg_overlay(dep,rec,620,680))
    html.append('<h2>Transport diagnostics retained</h2><div class="scroll"><table><tr><th>Model</th><th>Groups with step limits</th><th>Stopped-without-contact groups</th><th>Negative-input groups</th></tr>')
    for m in MODELS:
        r=nsummary['models'][m]
        html.append(f'<tr><td>{m}</td><td>{r["groups_with_step_limits"]:,}</td><td>{r["groups_stopped_without_contact"]:,}</td><td>{r["negative_input_groups"]:,}</td></tr>')
    html.append('</table></div><p>These flags cover native-completed groups and remain diagnostics. <code>negative_input</code> means at least one negative cumulative-charge sample (including tiny excursions); the signed-positive-peak policy does not rectify the signal and may still accept a valid positive peak. Step-limit and stopped-without-contact flags are not cleared by ADC acceptance and do not prove complete collection. The earlier two-event 10→20 µs cap check is not a campaign-wide convergence claim.</p><p>Induced/deposited quantiles in summary.json are group-weighted over native-completed positive groups, including readout rejects and excluding unknown native failures. They are engineering diagnostics, not calibrated CCE.</p>')
    html.append('<p><a href="summary.json">Summary JSON</a> · <a href="histograms.csv">1 keV histograms</a> · <a href="groups.csv.gz">All 23,693 group scalar records + truth classes</a></p>')
    (out/'report.html').write_text(''.join(html),encoding='utf-8',newline='\n')
    files={}
    for p in sorted(out.iterdir()):
        if p.name=='COMPLETE.json':continue
        files[p.name]={'sha256':sha(p),'bytes':p.stat().st_size}
    completion={'status':'verified_native_response_report','kind':'million_native_response_report_v1',
        'native_complete_sha256':nsummary['campaign_complete_sha256'],
        'truth_complete_sha256':sha(TRUTH/'COMPLETE.json'),'files':files}
    write(out/'COMPLETE.json',completion)
    print(json.dumps({'status':completion['status'],'models':public_summary['models'],'totals':public_summary['totals'],
        'files':files},indent=2))
if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();main(a.output)
