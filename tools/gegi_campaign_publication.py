"""Compact saved GeGI campaign figures; no transport, drift, fields or analysis.

Export once after this source is frozen. Only the checked public/ child is copied
by build_site. Exact representative native inputs and electronics replay remain
in the local derivative; public plots never carry a full event/waveform ledger.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import html
import io
import json
import math
from pathlib import Path
import re
import shutil
import subprocess

import scenario_workflow as W
import gegi_campaign_analysis as A
import gegi_campaign_response as R
from site_routes import page_navigation

ROOT=Path(__file__).resolve().parents[1]
KIND='gegi_campaign_publication_v1'
ROUTE='results/gegi-campaign/index.html'
MAX_BUNDLE_BYTES=8_000_000
TEXT_FILES={'index.html','summary.json','configuration.json','representatives.json','gegi_signal_journey.js'}
OPTIONAL_TEXT_FILES={'bootstrap-summary.json','source-assessment.json'}
DISPLAY_SOURCE='tools/gegi_signal_journey.js'
PRIVATE=re.compile(r'[A-Za-z]:[\\/]+Users[\\/]|/mnt/[a-z]/|/home/[^/\s]+/|file:///|\.local[\\/]',re.I)
require=A.require
read=W.read
sha=W.sha
encoded=A.encoded


def public(body):
    text=body.decode('utf-8')
    require(not PRIVATE.search(text),'Private path in campaign publication')
    require(not re.search(r'BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY|gh[pousr]_[A-Za-z0-9]{25,}',text),
            'Credential-like publication content')
    return body


def ordinary(path):
    import gegi_campaign as C
    C.no_links(path)
    require(Path(path).is_file(),'Missing saved campaign artifact')
    return Path(path)


def saved_inputs(campaign,analysis,*,root=ROOT):
    """Check completed derived data and immutable chunk seals, without raw scans."""
    import gegi_campaign as C
    campaign=C.local(campaign,root);analysis=C.local(analysis,root)
    plan=C.read_plan(campaign,root=root,verify=False)
    complete=read(ordinary(campaign/'COMPLETE.json'))
    summary=read(ordinary(analysis/'summary.json'));manifest=read(ordinary(analysis/'manifest.json'))
    require(summary.get('kind')==manifest.get('kind')==A.KIND and summary.get('status')==manifest.get('status')=='complete',
            'Only complete campaign analysis may be published')
    require(complete.get('status') in ('completed','completed_with_native_failures') and
            complete.get('plan_sha256')==summary.get('plan_sha256')==sha(campaign/'plan.json') and
            complete.get('physics_sha256')==summary.get('physics_sha256')==plan['physics_sha256'],
            'Completed campaign/analysis identity changed')
    require(manifest['plan_sha256']==summary['plan_sha256'] and manifest['radiation_calls']==manifest['field_solves']==0,
            'Analysis manifest identity differs')
    names=set(manifest['files'])
    require({'summary.json','maps.json','cones.jsonl'}<=names<= {'summary.json','maps.json','cones.jsonl','bootstrap.json'} and
            {p.name for p in analysis.iterdir()}==names|{'manifest.json'},'Unexpected analysis artifact inventory')
    for name,record in manifest['files'].items():
        path=ordinary(analysis/name)
        require(path.stat().st_size==record['bytes'] and sha(path)==record['sha256'],'Analysis artifact changed: '+name)
    maps=read(analysis/'maps.json');pins=A.source_hashes(root)
    require(summary['criteria']==maps['criteria']==plan['analysis_criteria']==A.criteria() and
            summary['source_sha256']==manifest['source_sha256']==pins,'Frozen analysis source or criteria changed')
    revision=summary.get('analysis_revision')
    require(type(revision) is dict and manifest.get('analysis_revision')==revision and type(revision.get('allowed')) is bool,
            'Explicit matching analysis revision metadata is required')
    verified=A.validate_analysis_revision(plan,root=root,allow_analysis_revision=revision['allowed'])
    require(revision==verified,'Analysis revision metadata differs from verified producer/source pins')
    require(summary['processed_initial_records']==summary['planned_initial_records']==complete['initial_primaries']==plan['total_initial_primaries'],
            'Formal campaign initial denominator incomplete')
    groups={g['id']:g for g in plan['groups']}
    require(set(groups)==set(summary['groups'])==set(maps['groups']) and set(summary['mixtures'])==set(maps['mixtures']),
            'Campaign source/map inventory changed')
    chunks={c['chunk_index']:c for c in C.chunks(plan)}
    require(len(summary['inputs'])==len(chunks) and set(complete['chunks'])=={str(i) for i in chunks},'Completed chunk census changed')
    seen=set()
    for record in summary['inputs']:
        index=record['chunk_index'];require(index in chunks and index not in seen,'Duplicate or unknown analysis chunk');seen.add(index)
        chunk=chunks[index];folder=C.chunk_path(campaign,chunk)
        require(record['source_group']==chunk['source_group'] and record['initial_primaries']==chunk['batch']['primary_count'] and
                record['radiation_seed']==chunk['batch']['radiation_seed'] and
                sha(ordinary(folder/'DONE.json'))==record['done_sha256']==complete['chunks'][str(index)],'Analysis input chunk seal changed')
        done=read(folder/'DONE.json')
        require(done['identity']==C.chunk_identity(campaign,plan,chunk,root=root) and
                done['artifacts']['events.sqlite']['sha256']==record['store_sha256'] and
                record['store_ref']==(folder/'events.sqlite').relative_to(campaign).as_posix(),'Analysis Store reference changed')
    for key,group in summary['groups'].items():
        require(group['initial_primary_denominator']==groups[key]['primary_count'] and group['source']==groups[key]['source'] and
                group['count_unit']==groups[key]['count_unit'] and
                all(complete['groups'][key][k]==v for k,v in group['counts'].items()) and
                all(complete['groups'][key][k]==v for k,v in group['transport_denominators'].items()),'Published stage or photon/decay census changed')
        require((group['representative'] is None)==(group['counts']['imaging_accepted_groups']==0),
                'Representative/accepted-group census differs')
    return campaign,plan,summary,maps,{'campaign_complete_sha256':sha(campaign/'COMPLETE.json'),
        'analysis_manifest_sha256':sha(analysis/'manifest.json'),
        **{name+'_sha256':manifest['files'][name]['sha256'] for name in
           ('summary.json','maps.json','cones.jsonl','bootstrap.json') if name in manifest['files']}}


def replay_only(request_path,output_path,log_path,*,root=ROOT):
    """Existing standalone electronics branch: never initialize native fields."""
    env=W.child_env(1)
    with Path(log_path).open('xb') as log:
        call=subprocess.run([env['JULIA_EXE'],'--startup-file=no','--threads=1','--project='+str(Path(root)/'simulation'),
            str(Path(root)/'simulation/gegi_campaign_response.jl'),'--replay-only',str(request_path),'--output',str(output_path)],
            cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if __import__('os').name=='nt' else 0)
    require(call.returncode==0,'Representative electronics replay failed; preserve its log and inputs')
    return read(output_path)


def representative(campaign,group,output,*,root=ROOT,replayer=replay_only):
    """Read exactly the analysis-selected real group and verify all 34 channels."""
    rep=group['representative']
    if rep is None:return None,None
    ref=Path(rep['store_ref']);require(not ref.is_absolute() and '..' not in ref.parts,'Unsafe representative Store reference')
    database=ordinary(Path(campaign)/ref)
    require(sha(database)==rep['store_sha256'],'Representative Store changed')
    done=read(ordinary(database.parent/'DONE.json'));response=done['response']
    require(done['artifacts']['events.sqlite']['sha256']==rep['store_sha256'],'Representative chunk differs')
    with A.scalar_store(database,done['identity'],response) as store:
        event,native=store.read(rep['raw_primary_id'],rep['pulse_group_id'],with_signals=True)
    require(event['event_id']==rep['raw_primary_id'] and event['group_id']==rep['pulse_group_id'] and
            event['reconstruction']['status']=='accepted' and event['calibration_sha256']==rep['calibration_sha256'] and
            event['readout_recipe_sha256']==rep['readout_recipe_sha256'] and native is not None and len(native)==34,
            'Representative original identity/selection changed')
    require(event['native_signals']=={str(c['contact_id']):c['native_signals'] for c in rep['channels']},
            'Representative native channel references changed')
    output=Path(output);output.mkdir(parents=True)
    recipe=A.response_recipe_for_event(response,event)
    request={**recipe,'native_signals':native,'horizon_ns':event.get('readout_horizon_ns')}
    request_path=output/'input.json';result_path=output/'output.json'
    W.write(request_path,request,fresh=True)
    result=replayer(request_path,result_path,output/'replay.log',root=root)
    check=R.verify_replayed_channels(event,result)
    require(check['channels']==34,'Representative replay lost channels')
    record={'original_identity':{k:rep[k] for k in ('source_group','chunk_index','raw_primary_id','pulse_group_id',
              'source_global_initial_id','campaign_initial_id')},'selection_rule':rep['selection_rule'],
            'unambiguous':rep['unambiguous'],'readout_energy_keV':rep['readout_energy_keV'],
            'native_reference_channels':rep['channels'],'replay':check,
            'readout_recipe_sha256':event['readout_recipe_sha256'],
            'readout_source_code_sha256':recipe['source_code_sha256'],
            'replay_input_sha256':sha(request_path),'replay_output_sha256':sha(result_path),
            'primary_time_ns':event['input_group']['primary_time_ns'],
            'group_origin_time_ns':event['input_group']['group_origin_time_ns'],
            'readout_horizon_ns':event.get('readout_horizon_ns')}
    # Four deterministic real representatives only, never a whole waveform ledger.
    # Every displayed value is copied exactly after complete replay verification;
    # the full trace identity (including omitted duplicate-wiring arrays) remains
    # bound by native_reference_channels and replay receipts.
    record['status']=event['status']
    record['reconstruction']=copy.deepcopy(event['reconstruction'])
    record['channel_metadata']=copy.deepcopy(recipe['channels'])
    record['channels']=[{**{name:channel.get(name) for name in ('contact_id','accepted','reconstructed_energy_keV',
        'final_induced_keV','final_wired_induced_keV','collection_candidate','t50_ns','t90_ns','timing_method',
        'rejection_reason','wiring_factor')},
        'trace':{name:copy.deepcopy(channel['trace'][name]) for name in
                 ('time_ns','charge_fC','current_nA','preamp_V','shaped_V')}} for channel in result['channels']]
    record['trace_conventions']=result['channels'][0].get('trace_conventions')
    record['display_channel_rule']='All 34 hash-verified channels are selectable; the walkthrough starts on the largest absolute terminal induced response. The static overview shows two contacts per face with largest absolute terminal induced charge.'
    record['display_trace_policy']='Exact retained display samples, without new rounding, resampling or peak fitting. Full native inputs and complete replay stay local.'
    W.write(output/'receipt.json',record,fresh=True)
    return record,result


def canvas(size):
    from PIL import Image,ImageDraw,ImageFont
    image=Image.new('RGB',size,'white');draw=ImageDraw.Draw(image)
    return image,draw,ImageFont.load_default(size=16)


def colour(value):
    # Fixed linear blue/yellow scale. The exact map values stay hash-bound locally.
    t=max(0.,min(1.,value));return (int(20+235*t),int(35+190*t),int(95-45*t))


def map_figure(pair,path,title):
    from PIL import Image
    image,draw,font=canvas((1160,490));draw.text((20,12),title,fill='black',font=font)
    for offset,(kind,grid) in zip((30,610),pair.items()):
        values=grid['values'];require(values and values[0] and all(len(r)==len(values[0]) for r in values),'Invalid map grid')
        require(all(A.finite(v) and v>=0 for row in values for v in row),'Invalid map density')
        maximum=max(max(r) for r in values);scale=maximum or 1.
        pixels=Image.new('RGB',(len(values[0]),len(values)))
        pixels.putdata([colour(v/scale) for row in reversed(values) for v in row])
        image.paste(pixels.resize((500,300),Image.Resampling.NEAREST),(offset,65))
        draw.rectangle((offset,65,offset+500,365),outline='black')
        xs=grid['azimuth_deg'] if kind=='direction' else grid['x_mm']
        ys=grid['elevation_deg'] if kind=='direction' else grid['y_mm']
        xlabel='azimuth (deg)' if kind=='direction' else 'x (mm); assumed z=40 mm'
        ylabel='elevation (deg)' if kind=='direction' else 'y (mm)'
        draw.text((offset,40),('Direction' if kind=='direction' else 'Source-plane projection')+'; '+ylabel,fill='black',font=font)
        draw.text((offset,370),f'{xs[0]:g}',fill='black',font=font)
        draw.text((offset+440,370),f'{xs[-1]:g}',fill='black',font=font)
        draw.text((offset+100,392),xlabel,fill='black',font=font)
        draw.text((offset,423),f'Linear colour: 0 to {maximum:.6g}; y centers {ys[0]:g} to {ys[-1]:g}',fill='black',font=font)
        units='weighted pulse groups / sr' if kind=='direction' else 'weighted pulse groups / mm^2'
        if 'equally allocated initial primary' in grid.get('value_units',''):units+=' / equal initial yield'
        draw.text((offset,450),units,fill='black',font=font)
        if maximum==0:draw.text((offset+75,200),'No mapped accepted groups; zero density',fill='white',font=font)
    image.save(path,optimize=True)


def plot_lines(draw,box,xs,series,font,xlabel,ylabel):
    return plot_series(draw,box,[(name,xs,values) for name,values in series.items()],font,xlabel,ylabel)


def plot_series(draw,box,series,font,xlabel,ylabel):
    left,top,right,bottom=box
    xs=[v for _,times,_ in series for v in times];ys=[v for _,_,values in series for v in values]
    require(xs and all(A.finite(v) for v in xs+ys),'Nonfinite saved plot sample')
    lo,hi=min(0.,min(ys,default=0.)),max(ys,default=0.)
    if hi==lo:hi=lo+1.
    xmin,xmax=min(xs),max(xs)
    if xmin==xmax:xmax=xmin+1.
    draw.rectangle(box,outline='black');palette=['#0068a0','#d14c16','#218641','#8a41a8','#a97c00','#146e72']
    for index,(name,times,values) in enumerate(series):
        require(len(times)==len(values),'Saved waveform/spectrum length differs')
        points=[(left+(x-xmin)/(xmax-xmin)*(right-left),bottom-(y-lo)/(hi-lo)*(bottom-top)) for x,y in zip(times,values)]
        if len(points)>=2:draw.line(points,fill=palette[index%len(palette)],width=2)
        draw.text((left+index%3*150,top-22-(index//3)*20),name,fill=palette[index%len(palette)],font=font)
    draw.text((left,bottom+3),f'{xmin:g}',fill='black',font=font)
    draw.text((right-65,bottom+3),f'{xmax:g}',fill='black',font=font)
    draw.text((left+100,bottom+23),xlabel,fill='black',font=font)
    draw.text((left,top-42),f'{ylabel}; range {lo:.5g} to {hi:.5g}',fill='black',font=font)


def spectra_figure(groups,path):
    image,draw,font=canvas((1200,820))
    for index,(key,group) in enumerate(groups.items()):
        x=55+(index%2)*600;y=85+(index//2)*400
        spec=group['spectrum'];edges=spec['edges_keV'];counts=spec['counts']
        require(len(edges)==len(counts)+1 and sum(counts)+spec['underflow']+spec['overflow']==spec['selected_readout_groups'],
                'Saved spectrum census changed')
        plot_lines(draw,(x,y,x+500,y+265),[(a+b)/2 for a,b in zip(edges,edges[1:])],{key:counts},font,
                   'fixed-gain readout energy (keV)','pulse groups per 2 keV bin')
    image.save(path,optimize=True)


def signal_figure(replay,path,title):
    channels=replay['channels']
    selected=[]
    for a,b in ((1,17),(18,34)):
        selected.extend(sorted((c for c in channels if a<=c['contact_id']<=b),
            key=lambda c:-abs(c.get('final_induced_keV') or 0))[:2])
    image,draw,font=canvas((1200,820));draw.text((15,5),title+'; 4 displayed channels / 34 verified',fill='black',font=font)
    for index,(field,unit) in enumerate((('charge_fC','raw signed charge (fC)'),('current_nA','fixed-wiring current (nA)'),('preamp_V','preamp (V)'),('shaped_V','shaper (V)'))):
        x=55+(index%2)*600;y=105+(index//2)*390
        plot_series(draw,(x,y,x+500,y+245),[('contact '+str(c['contact_id']),c['trace']['time_ns'],c['trace'][field]) for c in selected],
                   font,'group-relative time (ns)',unit)
    image.save(path,optimize=True)


def configuration(plan,root):
    request=read(W.safe_path(root,plan['native_request']['ref']))
    require(sha(W.safe_path(root,plan['native_request']['ref']))==plan['native_request']['sha256'],'Frozen native request changed')
    return {'campaign_id':plan['campaign_id'],'cryostat':plan['cryostat'],'detector':plan['detector'],
        'model_sha256':plan['model_sha256'],'total_initial_records':plan['total_initial_primaries'],'threads':plan['threads'],
        'groups':plan['groups'],'raw_initial_id_base':plan['raw_initial_id_base'],
        'pulse_group_horizon_ns':plan['pulse_group_horizon_ns'],'numerics':request['numerics'],
        'native_request_sha256':plan['native_request']['sha256'],'calibration_sha256':plan['calibration']['sha256'],
        'field_cache_sha256':request['field_cache']['sha256'],'profile_sha256':request['profile_sha256'],
        'transport_context_sha256':W.digest(plan['transport_context']),
        'coordinate_scope':'Crystal center at origin; +z is front. Source positions are known setup/evaluation truth, never reconstruction inputs.',
        'source_scope':'Mono gamma is exactly its stated energy; registered Cs137/Co60 are full nuclear decays. All isotope groups share the same three observed-energy windows.'}


def bootstrap_report(summary,analysis,inputs):
    """Compact descriptive quantiles of the checked, already-computed bootstrap."""
    digest=inputs.get('bootstrap.json_sha256')
    if digest is None:return None
    path=ordinary(Path(analysis)/'bootstrap.json')
    require(sha(path)==digest,'Saved bootstrap changed before publication')
    saved=read(path);policy=summary['criteria']['bootstrap'];count=policy['resamples']
    require(saved.get('kind')=='gegi_campaign_bootstrap_v1' and saved.get('policy')==policy and
            set(saved.get('groups',{}))==set(summary['groups']) and
            summary.get('bootstrap',{}).get('status')=='complete','Saved bootstrap identity or completion changed')
    def quantile(values,p):
        if not values:return None
        values=sorted(values);index=(len(values)-1)*p;low=math.floor(index);high=math.ceil(index)
        return values[low]+(values[high]-values[low])*(index-low)
    groups={}
    for key,kinds in saved['groups'].items():
        groups[key]={}
        require(set(kinds)=={'direction','plane'},'Unexpected bootstrap projection')
        for kind,rows in kinds.items():
            require(len(rows)==count and [r['replicate'] for r in rows]==list(range(count)) and
                    all(r['bias'] is None or A.finite(r['bias']) and r['bias']>=0 for r in rows),
                    'Bootstrap replicate census or peak offsets changed')
            biases=[r['bias'] for r in rows if r['bias'] is not None]
            tol=summary['criteria']['direction_localization_tolerance_deg' if kind=='direction' else 'plane_localization_tolerance_mm']
            groups[key][kind]={'replicates':count,'valid_peak_replicates':len(biases),'no_peak_replicates':count-len(biases),
                'peak_offset_units':'deg' if kind=='direction' else 'mm on assumed z=40 mm plane',
                'peak_offset_percentiles':{'p2_5':quantile(biases,.025),'p50':quantile(biases,.5),'p97_5':quantile(biases,.975)},
                'within_fixed_localization_tolerance_replicates':sum(v<=tol for v in biases),
                'localization_tolerance':tol,
                'finite_plane_boundary_peak_replicates':sum(r.get('peak') is not None and
                    (abs(r['peak']['x_mm'])>=119 or abs(r['peak']['y_mm'])>=119) for r in rows) if kind=='plane' else None}
    return {'kind':'gegi_campaign_bootstrap_display_v1','source_bootstrap_sha256':digest,'policy':policy,
        'runtime_seconds':saved['runtime_seconds'],'groups':groups,'limitations':saved['limitations'],
        'percentile_rule':'Linear interpolation at (n−1)p; 2.5th, 50th and 97.5th empirical percentiles of non-null resampled peak offsets.',
        'interpretation':'Conditional finite-sample variation of the single-source global peak. These are not confidence bounds on a true source location, detector resolution, efficiency, calibration or model/hardware accuracy. No resampled mixture-separation probability was computed.'}


def source_report(path,summary,inputs,*,root=ROOT):
    """Admit only a hash-bound saved-spectrum diagnostic of this exact analysis."""
    if path is None:return None,{}
    import gegi_campaign as C
    path=ordinary(C.local(path,root));manifest_path=ordinary(path.parent/'manifest.json')
    saved=read(path);manifest=read(manifest_path);record=manifest.get('files',{}).get(path.name,{})
    expected={'analysis_manifest_sha256':inputs['analysis_manifest_sha256'],
        'summary_sha256':inputs['summary.json_sha256'],'maps_sha256':inputs['maps.json_sha256'],
        'cones_sha256':inputs['cones.jsonl_sha256'],'plan_sha256':summary['plan_sha256']}
    require(saved.get('kind')=='gegi_source_inference_v1' and manifest.get('kind')==saved['kind'] and
            manifest.get('status') in ('complete','complete_posthoc_diagnostic') and
            saved.get('provenance')==manifest.get('provenance') and
            all(saved['provenance'].get(k)==v for k,v in expected.items()) and
            record.get('sha256')==sha(path) and record.get('bytes')==path.stat().st_size,
            'Source diagnostic is incomplete or belongs to a different saved analysis')
    require(type(manifest.get('source_sha256')) is dict and manifest['source_sha256'],
            'Source diagnostic implementation provenance is missing')
    for name,digest in manifest.get('source_sha256',{}).items():
        require(sha(ordinary(W.safe_path(root,name)))==digest,'Source diagnostic implementation changed')
    require(set(saved.get('groups',{}))==set(summary['groups']) and
            set(saved.get('mixtures',{}))==set(summary['mixtures']),'Source diagnostic component inventory differs')
    for family in ('groups','mixtures'):
        for key,item in saved[family].items():
            require(item['imaging_evaluation']==summary[family][key]['evaluations'],
                    'Source diagnostic changed frozen imaging conclusions')
            require(item['distance']['status']=='not_identified_by_saved_analysis' and item['distance']['distance_mm'] is None and
                    item['distance']['assumed_plane_z_mm']==summary['criteria']['plane_z_mm'],
                    'An assumed plane is not a recovered source distance')
    return saved,{'source_assessment_report_sha256':sha(path),'source_assessment_manifest_sha256':sha(manifest_path)}


def metric_text(metric,kind):
    """Readable numerical conclusions; raw exact values remain downloadable."""
    units='degrees' if kind=='direction' else 'mm on the assumed plane'
    peaks=metric.get('peaks',[])
    peak_note=''
    if peaks and kind=='plane':
        peak_note=' Blind plane peak'+('s' if len(peaks)>1 else '')+': '+', '.join(f'({p["x_mm"]:g}, {p["y_mm"]:g})' for p in peaks)+' mm.'
        if any(abs(p['x_mm'])>=119 or abs(p['y_mm'])>=119 for p in peaks):
            peak_note+=' A selected peak lies on the finite map boundary (±119 mm cell centres).'
    if 'source_separation_demonstrated' in metric:
        result=metric['source_separation_demonstrated']
        main=('Two-source separation meets the frozen criteria.' if result is True else
              'Two-source separation does not meet the frozen criteria.' if result is False else
              'Two-source separation is inconclusive under the frozen criteria.')
        if 'two_peak_resolution_status' in metric:main+=' Two-peak / valley test: '+metric['two_peak_resolution_status']+'.'
        match=metric.get('truth_matching')
        if match:main+=' Matched peak offsets: '+', '.join(f'{v:.4g}' for v in match['biases'])+' '+units+'.'
        trough=metric.get('valley')
        if trough:main+=f' Connecting valley / lower peak = {trough["fraction_of_lower_peak"]:.4g} (required ≤ 0.8).'
        reasons=metric.get('reasons',[])
        if reasons:main+=' Recorded limits: '+', '.join(r.replace('_',' ') for r in reasons)+'.'
        return main+peak_note
    bias=metric.get('global_peak_bias')
    status='computed' if metric.get('status')=='measured' else str(metric.get('status','unavailable'))
    if bias is not None:return f'Blind numerical peak offset from known source setup: {bias:.4g} {units}. Metric status: '+status+'.'+peak_note
    return 'Numerical peak result is '+str(metric.get('status','unavailable'))+'; '+str(metric.get('reason','no accepted peak conclusion')).replace('_',' ')+'.'


def render(summary,figures,reps,*,bootstrap=None,source_assessment=None):
    esc=lambda v:html.escape(str(v))
    native_failures=sum(g['counts']['native_failed_groups'] for g in summary['groups'].values())
    accepted=sum(g['counts']['imaging_accepted_groups'] for g in summary['groups'].values())
    journey={'criteria':summary['criteria'],'groups':{key:{'representative':reps.get(key),
        'initial_primary_denominator':g['initial_primary_denominator'],'counts':g['counts'],
        'truth_position_mm_for_evaluation_only':g['truth_position_mm_for_evaluation_only']} for key,g in summary['groups'].items()}}
    journey_json=json.dumps(journey,separators=(',',':'),ensure_ascii=False,allow_nan=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    parts=['<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
        '<title>GeGI · signals to Compton images · GeSignal</title><style>body{font:16px/1.55 system-ui;color:#173047;margin:auto;max-width:1160px;padding:20px}img{width:100%;height:auto}table{border-collapse:collapse;width:100%;display:block;overflow:auto}th,td{padding:8px;border:1px solid #ccd6de;text-align:left}section{margin:28px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere}a{color:#075e9b}summary{cursor:pointer;font-weight:600;padding:10px 0}.campaign-note{background:#edf5f8;padding:15px;border-left:4px solid #007b90}.campaign-nav{display:flex;gap:18px;flex-wrap:wrap;margin:20px 0}.campaign-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,340px),1fr));gap:18px}.campaign-grid section{border:1px solid #cad9df;border-radius:8px;padding:16px;margin:8px 0}</style><body>',
        page_navigation(ROUTE),'<h1>GeGI · from electrode signals to Compton images</h1>',
        '<p>Saved radiation → 34-electrode native charge → fixed-calibration electronics → signal-derived Compton reconstruction. Explore actual events, then compare the complete source maps.</p>',
        '<p class="campaign-note">'+esc(f'{summary["processed_initial_records"]:,} formal initial records completed; {accepted:,} pulse groups accepted for imaging; {native_failures:,} native-failed groups retained.')+' Processing completion is not experimental validation. Photon and initial-decay denominators remain separate.</p>',
        '<nav class="campaign-nav" aria-label="Campaign sections"><a href="#event-journey">Explore a real event</a><a href="#campaign-outcomes">Counts and failures</a><a href="#campaign-spectra">Energy spectra</a><a href="#campaign-maps">Full campaign maps</a><a href="#campaign-limits">Limits and provenance</a></nav>',
        '<p><a href="configuration.json">Frozen configuration, seeds and units</a> · <a href="summary.json">Exact aggregate counts, spectra and metrics</a> · <a href="representatives.json">Representative identities, reconstruction and 34-channel hashes</a> · <a href="publication.json">Artifact provenance</a></p>',
        '<h2>What the full campaign establishes</h2><p>Each source image uses every accepted group with all valid candidate cones. Peaks are found without source truth. Two peaks alone do not establish source localization: the frozen combined test also requires their positions to agree with the known source setup within 15° or 15 mm. The offsets below evaluate that agreement afterward. A computed metric (stored status “measured”) is a numerical result, not an experimental measurement.</p><div class="campaign-grid">']
    for key,pair in summary['mixtures'].items():
        parts+=['<section><h3>'+esc(key.replace('__',' + '))+'</h3>']
        for kind,metric in pair.get('evaluations',{}).items():
            parts+=['<p><strong>'+('Direction' if kind=='direction' else 'Assumed z = 40 mm plane')+':</strong> '+esc(metric_text(metric,kind))+'</p>']
        parts+=['</section>']
    parts+=['</div>']
    if source_assessment is not None:
        parts+=['<h2>Source species and distance · usable conclusions</h2><p>The spectrum-only diagnostic excludes acquisition labels and source positions. The labels below identify saved datasets; they are not classifier inputs. A single 662-keV line remains ambiguous; a supported Co60 doublet supplies stronger species evidence within the limited candidate library.</p><p class="campaign-note">Distance remains unidentified for every source and mixture. The assumed z = 40 mm plane is not a range measurement, and species candidates cannot be assigned to incorrectly located image peaks.</p><table><tr><th>Saved acquisition</th><th>Spectrum-only interpretation</th></tr>']
        for family in ('groups','mixtures'):
            for key,item in source_assessment[family].items():
                parts+=['<tr><td>'+esc(key.replace('__',' + '))+'</td><td>'+esc(item['spectral_inference']['interpretation'])+'</td></tr>']
        parts+=['</table><p><a href="#campaign-source-evidence">Inspect line / continuum evidence and range-identifiability limits</a>.</p>']
    parts+=['<section id="event-journey"><h2>Explore one real event: signals → interactions → cone → image</h2><p>One deterministic representative per source: first accepted unambiguous pulse group in original ID order; otherwise first accepted. This teaching selection does not change the aggregate maps or the event census.</p><div id="gegi-signal-journey"></div><noscript>The interactive walkthrough needs JavaScript. The exact identities and static signal/map figures remain available below.</noscript></section>',
        '<script type="application/json" id="gegi-journey-data">'+journey_json+'</script><script src="gegi_signal_journey.js"></script><script>GeGISignalJourney.mount(document.getElementById("gegi-signal-journey"),JSON.parse(document.getElementById("gegi-journey-data").textContent));</script>',
        '<h2 id="campaign-outcomes">Denominators and outcomes</h2><table><tr><th>Source group</th><th>Initial denominator / unit</th><th>Zero / nonzero primaries</th><th>Pulse groups / native failures</th><th>Readout accepted / rejected groups</th><th>Imaging accepted / rejected groups</th></tr>']
    for key,g in summary['groups'].items():
        c=g['counts'];parts.append('<tr>'+''.join('<td>'+esc(v)+'</td>' for v in (key,
            f"{g['initial_primary_denominator']:,} {g['count_unit']}",f"{c['zero_deposit_primaries']:,} / {c['nonzero_primaries']:,}",
            f"{c['pulse_groups']:,} / {c['native_failed_groups']:,}",f"{c['readout_accepted_groups']:,} / {c['readout_rejected_groups']:,}",
            f"{c['imaging_accepted_groups']:,} / {c['imaging_rejected_groups']:,}"))+'</tr>')
    parts+=['</table><p>'+esc(summary['count_scope'])+'</p><p>'+esc(summary.get('stage_accounting_policy','Native failures and readout/imaging rejections are not independent populations.'))+'</p>',
        '<p>Isotope source denominators count initial nuclei, not emitted line photons. Delayed daughter times and original primary/group IDs remain in the raw data and Store. Isolated 100 µs reset windows are not an activity or pileup model.</p>',
        '<h2 id="campaign-spectra">Fixed-gain observed-energy spectra</h2>',
        '<figure><img loading="lazy" src="spectra.png" alt="Fixed-gain readout spectra for each separate source group"><figcaption>Observed fixed-gain energy; exact 2-keV bin counts and under/overflow remain in summary.json. Unknown/rejected energies are not fabricated as zero-energy events.</figcaption></figure>']
    for key,g in summary['groups'].items():
        c=g['counts'];n=g['initial_primary_denominator'];imaged=c['imaging_accepted_primaries']
        parts+=['<section><h3>'+esc(key)+' · acceptance and retained failures</h3>',
            '<p>'+esc(f'{imaged:,} initial primaries produced at least one accepted imaging group out of {n:,} initials ({100*imaged/n:.5g}%).')+' This retains zero-deposit initials in the denominator.</p>']
        for title,field in (('First unsuccessful stage / accepted outcome (exclusive)','exclusive_stage_counts'),
                            ('Native statuses','native_status_counts'),('Exact saved native error','native_error_counts'),
                            ('Readout rejection reason (includes upstream failures)','readout_rejection_reasons'),
                            ('Imaging rejection reason (includes upstream failures)','rejection_reasons')):
            values=g.get(field,{})
            if values:parts+=['<details><summary>'+esc(title)+'</summary><table><tr><th>Recorded outcome</th><th>Pulse groups</th></tr>']+['<tr><td>'+esc(reason.replace('_',' ') if field!='native_error_counts' else reason)+'</td><td>'+esc(f'{count:,}')+'</td></tr>' for reason,count in sorted(values.items())]+['</table></details>']
        if g['transport_denominators']:parts+=['<details><summary>Transport photon / decay diagnostics</summary><pre>'+esc(json.dumps(g['transport_denominators'],indent=2,sort_keys=True))+'</pre></details>']
        for kind,metric in g['evaluations'].items():parts+=['<p>'+('Direction' if kind=='direction' else 'Assumed plane')+': '+esc(metric_text(metric,kind))+'</p>']
        if reps.get(key):
            parts+=['<details><summary>Static representative signal overview and identity</summary><p>Representative original IDs: '+esc(reps[key]['original_identity'])+'. '+esc(reps[key]['selection_rule'])+'</p>',
                    '<p>'+esc(reps[key]['display_channel_rule'])+' Charge is raw signed SSD charge; current and voltages retain their fixed-wiring conventions. No event-specific energy gain is fitted.</p>',
                    '<img loading="lazy" src="signals-'+esc(key)+'.png" alt="Verified representative charge, current, preamp and shaper signals"></details>']
        else:parts+=['<p>No accepted representative exists. No zero waveform is fabricated.</p>']
        parts+=['</section>']
    parts+=['<h2 id="campaign-maps">Full campaign · blind direction and assumed source-plane maps</h2><p>Every candidate cone retains its saved weight. Peaks are detected without source truth; only the reported evaluation compares the detected peaks with the known source setup. The z=40 mm plane is assumed, not a recovered distance or a true 3D image. Direction maps neglect the cone vertex offset, so they are a far-field diagnostic at these nearby sources; the plane calculation uses each reconstructed vertex.</p>']
    for family,key,window,name in figures:
        label=key+' · '+('all imaging-accepted groups' if window=='all' else window+' keV observed-energy window')
        parts+=['<details'+(' open' if window=='all' else '')+'><summary>'+esc(label)+'</summary><figure><img loading="lazy" src="'+name+'" alt="'+esc(label)+' direction and z=40 mm plane maps"><figcaption>Linear density colour with panel-specific maximum; plotted grid cell centers. Exact map arrays remain in the hash-bound local analysis, not a per-event browser payload.</figcaption></figure></details>']
    parts+=['<h2>Independent-source mixtures</h2><p>The same three windows (661.657, 1173.228 and 1332.492 keV; half width max(5 keV, 2%)) are applied to both isotope sources using observed energy. Cross-isotope continuum contributions remain. Mixtures use equal initial-source yields, not separate unit-area renormalization.</p>']
    for key,pair in summary['mixtures'].items():
        parts+=['<section><h3>'+esc(key.replace('__',' + '))+'</h3><p>'+esc(pair.get('normalization',pair.get('reason')))+' '+esc(pair.get('independence',''))+'</p>']
        for kind,metric in pair.get('evaluations',{}).items():parts+=['<p>'+('Direction' if kind=='direction' else 'Assumed plane')+': '+esc(metric_text(metric,kind))+'</p>']
        parts+=['<details><summary>Exact frozen numerical metrics</summary><pre>'+esc(json.dumps(pair.get('evaluations',{}),indent=2))+'</pre></details></section>']
    if source_assessment is not None:
        parts+=['<h2 id="campaign-source-evidence">Line evidence and distance identifiability</h2><p>Source labels and known positions are excluded from the spectrum classifier. It checks fixed line candidates against neighbouring side bands in the observed fixed-gain spectrum. These are evidence-limited candidate identifications, not an exhaustive nuclide search or a calibrated significance test.</p><p class="campaign-note">No source distance is identified by this saved analysis. The z = 40 mm display plane is imposed; it must not be reported as a measured range. A spectral candidate is not assigned to an image peak whose location fails the frozen localization criteria.</p>']
        for family in ('groups','mixtures'):
            for key,item in source_assessment[family].items():
                spec=item['spectral_inference'];distance=item['distance']
                parts+=['<section><h3>'+esc(key.replace('__',' + '))+'</h3><p><strong>Species evidence:</strong> '+esc(spec['interpretation'])+'</p>']
                for candidate in spec.get('candidate_components',[]):
                    parts+=['<p>'+esc(candidate['label'])+' · '+esc(candidate['status'].replace('_',' '))+'. '+esc(candidate.get('reason',''))]
                    if candidate.get('alternatives'):parts+=[' Alternatives: '+esc('; '.join(candidate['alternatives']))+'.']
                    parts+=['</p>']
                parts+=['<p><strong>Range:</strong> '+esc(distance['reason'])+'</p><details><summary>Observed line and side-band evidence</summary><table><tr><th>Line candidate (keV)</th><th>Peak-bin centre (keV)</th><th>Signal / estimated continuum</th><th>Net excess</th><th>Evidence screen</th></tr>']
                for line in spec.get('line_evidence',[]):
                    f=lambda v:'unknown' if v is None else f'{v:.6g}'
                    parts+=['<tr>'+''.join('<td>'+esc(v)+'</td>' for v in (f(line['line_energy_keV']),f(line.get('peak_bin_center_keV')),
                        f(line['signal_counts'])+' / '+f(line['continuum_estimate_counts']),f(line['net_excess_counts']),
                        line['status'].replace('_',' ')))+'</tr>']
                parts+=['</table><p>Side-band count-model screening is post hoc and does not include a measured background, independent pulse-group counts, response-template fitting or a complete isotope library. The compact report retains exact region counts, both side-band comparisons and qualifications.</p>']
                for limit in spec.get('limitations',[]):parts+=['<p>'+esc(limit)+'</p>']
                parts+=['</details></section>']
        parts+=['<p><a href="source-assessment.json">Exact source-candidate, line-evidence and distance-identifiability report</a>.</p>']
        references=source_assessment.get('references',[])
        if isinstance(references,dict):references=list(references.values())
        for reference in references:
            if isinstance(reference,dict) and str(reference.get('url','')).startswith('https://'):
                parts+=['<p><a href="'+esc(reference['url'])+'">'+esc(reference.get('label',reference.get('title','Primary nuclear-data reference')))+'</a></p>']
    if bootstrap is not None:
        parts+=['<h2>Conditional finite-sample peak variation</h2><p>'+esc(f'{bootstrap["policy"]["resamples"]} primary-cluster Poisson(1) resamples; seed {bootstrap["policy"]["seed"]}; saved calculation took {bootstrap["runtime_seconds"]:.3f} s.')+' Each accepted primary keeps its pulse groups and original relative cone weights together. No radiation or native drift was repeated.</p>',
            '<p class="campaign-note">'+esc(bootstrap['interpretation'])+'</p><p>The range below spans the 2.5th to 97.5th empirical percentiles; it describes resampled peak offsets from the known source setup. A narrow range around a large bias still indicates a misplaced peak. Plane boundary switches can make this distribution multimodal.</p><table><tr><th>Source / map</th><th>Median peak offset</th><th>2.5–97.5% resampled range</th><th>Within fixed 15° / 15 mm tolerance</th><th>Boundary peaks</th></tr>']
        for key,kinds in bootstrap['groups'].items():
            for kind,values in kinds.items():
                q=values['peak_offset_percentiles'];f=lambda v:'unknown' if v is None else f'{v:.5g}'
                parts+=['<tr>'+''.join('<td>'+esc(v)+'</td>' for v in (key+' / '+kind,
                    f(q['p50'])+' '+values['peak_offset_units'],f(q['p2_5'])+' to '+f(q['p97_5']),
                    str(values['within_fixed_localization_tolerance_replicates'])+' / '+str(values['replicates']),
                    'not applicable' if kind=='direction' else str(values['finite_plane_boundary_peak_replicates'])+' / '+str(values['replicates'])))+'</tr>']
        parts+=['</table><p><a href="bootstrap-summary.json">Exact compact bootstrap summary, percentile rule and saved input hash</a>. '+esc(bootstrap['percentile_rule'])+'</p>']
    parts+=['<h2 id="campaign-limits">Limits and reproducibility</h2><p>The owner reduced the administrative quota from 10M to 1M before completion. The formal dataset contains 200k mono-gamma photons per position and 300k initial Cs137 / Co60 decays per isotope position; preparation and pilots are excluded. All completed original science and native failures are retained.</p><ul>']+['<li>'+esc(v)+'</li>' for v in summary['limitations']]
    parts+=['</ul><p>The fixed 20 accepted-groups criterion controls final metric conclusions; low counts remain inconclusive. It does not turn a functioning engineering pipeline into experimental validation.</p>',
        '<p><a href="../../assemblies/gegi/index.html">GeGI cryostat</a> · <a href="../../detectors/GeGI_3D/index.html">GeGI detector</a></p></body></html>']
    return public(('\n'.join(parts)+'\n').encode('utf-8'))


def export(campaign,analysis,output,*,exporter_sha256,root=ROOT,replayer=replay_only,source_assessment=None):
    import gegi_campaign as C
    from PIL import __version__ as pillow_version
    require(exporter_sha256==sha(__file__),'Freeze the exporter source and provide its exact SHA256 before export')
    source_names=('tools/gegi_campaign_publication.py','tools/site_routes.py','tools/gegi_campaign_response.py',DISPLAY_SOURCE)
    source_pins={name:sha(Path(root)/name) for name in source_names}
    campaign,plan,summary,maps,inputs=saved_inputs(campaign,analysis,root=root)
    bootstrap=bootstrap_report(summary,analysis,inputs)
    assessment,assessment_inputs=source_report(source_assessment,summary,inputs,root=root)
    inputs.update(assessment_inputs)
    output=C.local(output,root);require(not output.exists(),'Preserve existing publication derivatives; select a new output')
    output.mkdir(parents=True);target=output/'public';target.mkdir()
    # Keep only aggregate input identities; local Store paths are not public links.
    selected=copy.deepcopy(summary)
    selected['inputs']=[{k:r[k] for k in ('source_group','chunk_index','done_sha256','store_sha256','initial_primaries','radiation_seed')} for r in summary['inputs']]
    reps={};figures=[]
    for key,group in summary['groups'].items():
        require(re.fullmatch(r'[A-Za-z0-9_-]+',key),'Unsafe source-group figure name')
        reps[key],replay=representative(campaign,group,output/'representative-replay'/key,root=root,replayer=replayer)
        if replay is not None:signal_figure(replay,target/('signals-'+key+'.png'),key)
    spectra_figure(summary['groups'],target/'spectra.png')
    for family in ('groups','mixtures'):
        for index,(key,windows) in enumerate(maps[family].items()):
            for window,pair in windows.items():
                name=f'map-{family}-{index}-{window}.png';require(re.fullmatch(r'[A-Za-z0-9_.-]+',name),'Unsafe map figure name')
                map_figure({k:pair[k] for k in ('direction','plane')},target/name,key+' / '+window)
                figures.append((family,key,window,name))
    # Embed the few real display traces once, so the HTML also works offline.
    # The separate JSON keeps identities/reconstruction/hashes without duplicating
    # every waveform sample within the 8 MB public allowance.
    compact_reps={key:None if rep is None else {k:v for k,v in rep.items() if k!='channels'} for key,rep in reps.items()}
    for rep in compact_reps.values():
        if rep is not None:rep['display_samples_ref']='index.html#gegi-journey-data'
    bodies={'summary.json':encoded(selected),'configuration.json':encoded(configuration(plan,root)),
            'representatives.json':encoded(compact_reps),'index.html':render(selected,figures,reps,bootstrap=bootstrap,source_assessment=assessment),
            'gegi_signal_journey.js':(Path(root)/DISPLAY_SOURCE).read_bytes()}
    if bootstrap is not None:bodies['bootstrap-summary.json']=encoded(bootstrap)
    if assessment is not None:bodies['source-assessment.json']=encoded(assessment)
    for name,body in bodies.items():(target/name).write_bytes(public(body))
    require(sha(__file__)==exporter_sha256,'Exporter changed while producing the saved bundle')
    require(source_pins=={name:sha(Path(root)/name) for name in source_names},'Publication display source changed during export')
    record={'kind':KIND,'status':'complete','route':ROUTE,'campaign_id':summary['campaign_id'],
        'initial_records':summary['processed_initial_records'],'plan_sha256':summary['plan_sha256'],
        'physics_sha256':summary['physics_sha256'],'input_sha256':inputs,
        'analysis_revision':summary['analysis_revision'],
        'exporter_sha256':exporter_sha256,'pillow_version':pillow_version,
        'source_sha256':source_pins,
        'radiation_calls':0,'field_solves':0,'native_drift_calls':0,'electronics_replays':sum(v is not None for v in reps.values()),
        'map_display_policy':'PNG colour figures only; exact map arrays and all original native/readout inputs remain in the checked local derivative.',
        'event_display_policy':'One deterministic real representative per source; all 34 verified channel display traces and all saved reconstruction hypotheses. Illustrative event maps are recomputed in the shared display; full campaign maps are unchanged saved figures.',
        'artifacts':{p.name:{'sha256':sha(p),'bytes':p.stat().st_size} for p in target.iterdir()}}
    (target/'publication.json').write_bytes(public(encoded(record)));validate_bundle(target)
    W.write(output/'COMPLETE.json',{'kind':KIND,'status':'complete','public_manifest_sha256':sha(target/'publication.json'),
        'exporter_sha256':exporter_sha256,'input_sha256':inputs},fresh=True)
    return target


def validate_bundle(directory, *, allow_historical_sources=False):
    directory=Path(directory);ordinary(directory/'publication.json');record=read(directory/'publication.json')
    if record.get('kind')=='gegi_saved_publication_v3':
        from gegi_saved_publication import validate_public
        return validate_public(directory,allow_historical_sources=allow_historical_sources)
    require(record.get('kind')==KIND and record.get('status')=='complete' and record.get('route')==ROUTE and
            record.get('radiation_calls')==record.get('field_solves')==record.get('native_drift_calls')==0,
            'Incomplete or unsupported campaign publication')
    names=set(record['artifacts'])
    require(TEXT_FILES<=names and {p.name for p in directory.iterdir()}==names|{'publication.json'} and
            all(name in TEXT_FILES|OPTIONAL_TEXT_FILES or re.fullmatch(r'(?:map-[A-Za-z0-9_.-]+|signals-[A-Za-z0-9_-]+|spectra)\.png',name)
                for name in names),'Unexpected campaign public payload')
    total=(directory/'publication.json').stat().st_size
    for name,expected in record['artifacts'].items():
        path=ordinary(directory/name);total+=path.stat().st_size
        require(path.stat().st_size==expected['bytes'] and sha(path)==expected['sha256'],'Campaign public artifact changed: '+name)
        if name in TEXT_FILES|OPTIONAL_TEXT_FILES:public(path.read_bytes())
    require(total<=MAX_BUNDLE_BYTES,'Compact campaign bundle exceeds its 8 MB publication allowance')
    require(read(directory/'summary.json')['status']=='complete' and
            read(directory/'summary.json')['plan_sha256']==record['plan_sha256'] and
            read(directory/'summary.json')['analysis_revision']==record['analysis_revision'],'Published summary identity changed')
    public((directory/'publication.json').read_bytes())
    return record


def install_bundle(bundle,site):
    record=validate_bundle(bundle);target=Path(site)/Path(ROUTE).parent
    if target.exists():
        previous=validate_bundle(target,allow_historical_sources=True)
        previous_sha=sha(target/'publication.json')
        if previous_sha==sha(Path(bundle)/'publication.json'):
            return target
        require(record.get('kind')=='gegi_saved_publication_v3' and
                record.get('replaces_public_manifest_sha256')==previous_sha,
                'Preserve a different existing formal campaign bundle without an explicit replacement binding')
        # Only the validated generated-site inventory is replaced. The original
        # scientific publication bundle remains untouched at its saved location.
        for name in previous['artifacts']:
            path=ordinary(target/name)
            require(path.resolve().parent==target.resolve(),'Escaped generated publication member')
            if name not in record['artifacts']:
                path.unlink()
        for name in record['artifacts']:
            shutil.copyfile(Path(bundle)/name,target/name)
        shutil.copyfile(Path(bundle)/'publication.json',target/'publication.json')
        validate_bundle(target)
        return target
    target.parent.mkdir(parents=True,exist_ok=True);shutil.copytree(bundle,target);validate_bundle(target)
    return target


def link_current(site):
    site=Path(site);target=site/Path(ROUTE).parent
    if not (target/'publication.json').exists():return
    record=validate_bundle(target)
    for relative in ('index.html','results/index.html','detectors/GeGI_3D/index.html','detectors/GeGI_3D/technical.html'):
        path=site/relative
        if not path.is_file():continue
        import posixpath
        href=posixpath.relpath(ROUTE,posixpath.dirname(relative) or '.')
        section=('<section id="gegi-formal-campaign"><h2>GeGI formal campaign</h2><p>'+
            f'{record["initial_records"]:,} completed initial records; source-specific photon/decay denominators, fixed-gain spectra, '+
            'saved signal processing, joint conditional maps and explicit unresolved cases.</p><p><a href="'+href+
            '">Explore signals, Compton cones and the completed campaign →</a>.</p></section>')
        text=re.sub(r'<section id="gegi-formal-campaign">.*?</section>','',path.read_text(encoding='utf-8'),flags=re.S)
        require('</main>' in text or '</body>' in text,'Maintained page has no insertion boundary')
        marker='</main>' if '</main>' in text else '</body>'
        path.write_bytes((text.replace(marker,section+marker,1)).encode('utf-8'))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign',type=Path,required=True);parser.add_argument('--analysis',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--exporter-sha256',required=True)
    parser.add_argument('--source-assessment',type=Path)
    args=parser.parse_args()
    print(export(args.campaign,args.analysis,args.output,exporter_sha256=args.exporter_sha256,source_assessment=args.source_assessment))
