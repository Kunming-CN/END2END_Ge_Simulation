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
TEXT_FILES={'index.html','summary.json','configuration.json','representatives.json'}
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
        require(done['identity']==C.chunk_identity(campaign,plan,chunk) and
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
        **{name+'_sha256':manifest['files'][name]['sha256'] for name in ('summary.json','maps.json','cones.jsonl')}}


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
    record['trace_conventions']=result['channels'][0].get('trace_conventions')
    record['display_channel_rule']='Two contacts per face with largest absolute terminal induced charge; all 34 channels are replayed and hash-verified.'
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
    left,top,right,bottom=box
    ys=[v for values in series.values() for v in values]
    require(xs and all(A.finite(v) for v in xs+ys),'Nonfinite saved plot sample')
    lo,hi=min(0.,min(ys,default=0.)),max(ys,default=0.)
    if hi==lo:hi=lo+1.
    xmin,xmax=min(xs),max(xs)
    if xmin==xmax:xmax=xmin+1.
    draw.rectangle(box,outline='black');palette=['#0068a0','#d14c16','#218641','#8a41a8','#a97c00','#146e72']
    for index,(name,values) in enumerate(series.items()):
        require(len(xs)==len(values),'Saved waveform/spectrum length differs')
        points=[(left+(x-xmin)/(xmax-xmin)*(right-left),bottom-(y-lo)/(hi-lo)*(bottom-top)) for x,y in zip(xs,values)]
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
        first=selected[0]['trace']['time_ns']
        require(all(c['trace']['time_ns']==first for c in selected),'Representative channels use distinct display grids')
        plot_lines(draw,(x,y,x+500,y+245),first,{'contact '+str(c['contact_id']):c['trace'][field] for c in selected},
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


def render(summary,figures,reps):
    esc=lambda v:html.escape(str(v))
    parts=['<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
        '<title>GeGI formal campaign · GeSignal</title><style>body{font:16px/1.55 system-ui;color:#173047;margin:auto;max-width:1160px;padding:20px}img{width:100%;height:auto}table{border-collapse:collapse;width:100%;display:block;overflow:auto}th,td{padding:8px;border:1px solid #ccd6de;text-align:left}section{margin:28px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere}a{color:#075e9b}</style><body>',
        page_navigation(ROUTE),'<h1>GeGI · completed formal campaign</h1>',
        '<p>Saved radiation → 34-electrode native charge → fixed-calibration electronics → signal-derived Compton reconstruction. This page contains aggregate figures and a few checked real pulse groups.</p>',
        '<p>'+esc(f'{summary["processed_initial_records"]:,} completed initial records; emitted-gamma and initial-decay units remain separate below.')+'</p>',
        '<p><a href="configuration.json">Frozen configuration, seeds and units</a> · <a href="summary.json">Exact aggregate counts, spectra and metrics</a> · <a href="representatives.json">Representative identities and 34-channel hashes</a> · <a href="publication.json">Artifact provenance</a></p>',
        '<h2>Denominators and outcomes</h2><table><tr><th>Source group</th><th>Initial denominator / unit</th><th>Zero / nonzero primaries</th><th>Pulse groups / native failures</th><th>Readout accepted / rejected groups</th><th>Imaging accepted / rejected groups</th></tr>']
    for key,g in summary['groups'].items():
        c=g['counts'];parts.append('<tr>'+''.join('<td>'+esc(v)+'</td>' for v in (key,
            f"{g['initial_primary_denominator']:,} {g['count_unit']}",f"{c['zero_deposit_primaries']:,} / {c['nonzero_primaries']:,}",
            f"{c['pulse_groups']:,} / {c['native_failed_groups']:,}",f"{c['readout_accepted_groups']:,} / {c['readout_rejected_groups']:,}",
            f"{c['imaging_accepted_groups']:,} / {c['imaging_rejected_groups']:,}"))+'</tr>')
    parts+=['</table><p>'+esc(summary['count_scope'])+'</p>',
        '<p>Isotope source denominators count initial nuclei, not emitted line photons. Delayed daughter times and original primary/group IDs remain in the raw data and Store. Isolated 100 µs reset windows are not an activity or pileup model.</p>',
        '<figure><img loading="lazy" src="spectra.png" alt="Fixed-gain readout spectra for each separate source group"><figcaption>Observed fixed-gain energy; exact 2-keV bin counts and under/overflow remain in summary.json. Unknown/rejected energies are not fabricated as zero-energy events.</figcaption></figure>']
    for key,g in summary['groups'].items():
        parts+=['<section><h2>'+esc(key)+'</h2><p>Transport photon/decay diagnostics: '+esc(json.dumps(g['transport_denominators'],sort_keys=True))+'</p>',
            '<p>Native statuses: '+esc(json.dumps(g['native_status_counts'],sort_keys=True))+'</p>',
            '<p>Readout rejection reasons: '+esc(json.dumps(g['readout_rejection_reasons'],sort_keys=True))+'</p>',
            '<p>Imaging rejection reasons: '+esc(json.dumps(g['rejection_reasons'],sort_keys=True))+'</p>',
            '<p>Fixed single-source metric conclusions: '+esc(json.dumps(g['evaluations'],sort_keys=True))+'</p>']
        if reps.get(key):
            parts+=['<p>Representative original IDs: '+esc(reps[key]['original_identity'])+'. '+esc(reps[key]['selection_rule'])+'</p>',
                    '<p>'+esc(reps[key]['display_channel_rule'])+' Charge is raw signed SSD charge; current and voltages retain their fixed-wiring conventions. No event-specific energy gain is fitted.</p>',
                    '<img loading="lazy" src="signals-'+esc(key)+'.png" alt="Verified representative charge, current, preamp and shaper signals">']
        else:parts+=['<p>No accepted representative exists. No zero waveform is fabricated.</p>']
        parts+=['</section>']
    parts+=['<h2>Blind direction and assumed source-plane maps</h2><p>Every candidate cone retains its saved weight. Peaks are detected without source truth; only the reported evaluation compares the detected peaks with the known source setup. The z=40 mm plane is assumed, not a recovered distance or a true 3D image.</p>']
    for family,key,window,name in figures:
        label=key+' · '+('all imaging-accepted groups' if window=='all' else window+' keV observed-energy window')
        parts+=['<details'+(' open' if window=='all' else '')+'><summary>'+esc(label)+'</summary><figure><img loading="lazy" src="'+name+'" alt="'+esc(label)+' direction and z=40 mm plane maps"><figcaption>Linear density colour with panel-specific maximum; plotted grid cell centers. Exact map arrays remain in the hash-bound local analysis, not a per-event browser payload.</figcaption></figure></details>']
    parts+=['<h2>Independent-source mixtures</h2><p>The same three windows (661.657, 1173.228 and 1332.492 keV; half width max(5 keV, 2%)) are applied to both isotope sources using observed energy. Cross-isotope continuum contributions remain. Mixtures use equal initial-source yields, not separate unit-area renormalization.</p>']
    for key,pair in summary['mixtures'].items():
        parts+=['<section><h3>'+esc(key)+'</h3><p>'+esc(pair.get('normalization',pair.get('reason')))+' '+esc(pair.get('independence',''))+'</p><pre>'+esc(json.dumps(pair.get('evaluations',{}),indent=2))+'</pre></section>']
    parts+=['<h2>Limits and reproducibility</h2><ul>']+['<li>'+esc(v)+'</li>' for v in summary['limitations']]
    parts+=['</ul><p>The fixed 20 accepted-groups criterion controls final metric conclusions; low counts remain inconclusive. It does not turn a functioning engineering pipeline into experimental validation.</p>',
        '<p><a href="../../examples/gegi/index.html">Earlier separate 10k gamma/two-position result</a> · <a href="../../assemblies/gegi/index.html">GeGI cryostat</a> · <a href="../../detectors/GeGI_3D/index.html">GeGI detector</a></p></body></html>']
    return public(('\n'.join(parts)+'\n').encode('utf-8'))


def export(campaign,analysis,output,*,exporter_sha256,root=ROOT,replayer=replay_only):
    import gegi_campaign as C
    from PIL import __version__ as pillow_version
    require(exporter_sha256==sha(__file__),'Freeze the exporter source and provide its exact SHA256 before export')
    campaign,plan,summary,maps,inputs=saved_inputs(campaign,analysis,root=root)
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
    bodies={'summary.json':encoded(selected),'configuration.json':encoded(configuration(plan,root)),
            'representatives.json':encoded(reps),'index.html':render(selected,figures,reps)}
    for name,body in bodies.items():(target/name).write_bytes(public(body))
    require(sha(__file__)==exporter_sha256,'Exporter changed while producing the saved bundle')
    record={'kind':KIND,'status':'complete','route':ROUTE,'campaign_id':summary['campaign_id'],
        'initial_records':summary['processed_initial_records'],'plan_sha256':summary['plan_sha256'],
        'physics_sha256':summary['physics_sha256'],'input_sha256':inputs,
        'analysis_revision':summary['analysis_revision'],
        'exporter_sha256':exporter_sha256,'pillow_version':pillow_version,
        'source_sha256':{name:sha(Path(root)/name) for name in ('tools/gegi_campaign_publication.py','tools/site_routes.py','tools/gegi_campaign_response.py')},
        'radiation_calls':0,'field_solves':0,'native_drift_calls':0,'electronics_replays':sum(v is not None for v in reps.values()),
        'map_display_policy':'PNG colour figures only; exact map arrays and all original native/readout inputs remain in the checked local derivative.',
        'artifacts':{p.name:{'sha256':sha(p),'bytes':p.stat().st_size} for p in target.iterdir()}}
    (target/'publication.json').write_bytes(public(encoded(record)));validate_bundle(target)
    W.write(output/'COMPLETE.json',{'kind':KIND,'status':'complete','public_manifest_sha256':sha(target/'publication.json'),
        'exporter_sha256':exporter_sha256,'input_sha256':inputs},fresh=True)
    return target


def validate_bundle(directory):
    directory=Path(directory);ordinary(directory/'publication.json');record=read(directory/'publication.json')
    require(record.get('kind')==KIND and record.get('status')=='complete' and record.get('route')==ROUTE and
            record.get('radiation_calls')==record.get('field_solves')==record.get('native_drift_calls')==0,
            'Incomplete or unsupported campaign publication')
    names=set(record['artifacts'])
    require(TEXT_FILES<=names and {p.name for p in directory.iterdir()}==names|{'publication.json'} and
            all(name in TEXT_FILES or re.fullmatch(r'(?:map-[A-Za-z0-9_.-]+|signals-[A-Za-z0-9_-]+|spectra)\.png',name)
                for name in names),'Unexpected campaign public payload')
    total=(directory/'publication.json').stat().st_size
    for name,expected in record['artifacts'].items():
        path=ordinary(directory/name);total+=path.stat().st_size
        require(path.stat().st_size==expected['bytes'] and sha(path)==expected['sha256'],'Campaign public artifact changed: '+name)
        if name in TEXT_FILES:public(path.read_bytes())
    require(total<=MAX_BUNDLE_BYTES,'Compact campaign bundle exceeds its 8 MB publication allowance')
    require(read(directory/'summary.json')['status']=='complete' and
            read(directory/'summary.json')['plan_sha256']==record['plan_sha256'] and
            read(directory/'summary.json')['analysis_revision']==record['analysis_revision'],'Published summary identity changed')
    public((directory/'publication.json').read_bytes())
    return record


def install_bundle(bundle,site):
    record=validate_bundle(bundle);target=Path(site)/Path(ROUTE).parent
    if target.exists():
        validate_bundle(target)
        require(sha(target/'publication.json')==sha(Path(bundle)/'publication.json'),'Preserve a different existing formal campaign bundle')
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
            'blind direction and assumed-plane maps, failures and fixed metric conclusions.</p><p><a href="'+href+
            '">Open the completed formal campaign →</a>. The earlier 10k gamma result remains a separate dataset.</p></section>')
        text=re.sub(r'<section id="gegi-formal-campaign">.*?</section>','',path.read_text(encoding='utf-8'),flags=re.S)
        require('</main>' in text or '</body>' in text,'Maintained page has no insertion boundary')
        marker='</main>' if '</main>' in text else '</body>'
        path.write_bytes((text.replace(marker,section+marker,1)).encode('utf-8'))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign',type=Path,required=True);parser.add_argument('--analysis',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--exporter-sha256',required=True)
    args=parser.parse_args()
    print(export(args.campaign,args.analysis,args.output,exporter_sha256=args.exporter_sha256))
