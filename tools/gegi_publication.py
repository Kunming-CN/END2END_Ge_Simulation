"""Render checked GeGI runs and an optional two-source comparison; never run science."""
from __future__ import annotations
import hashlib
import html
import json
import math
import copy
from collections import Counter
from pathlib import Path
import re

import scenario_workflow as W
import gegi_workflow as G

KIND='gegi_saved_publication_v1'
COMPARISON_KIND='gegi_saved_source_comparison_v1'
ASSET='scenarios/assets/gegi_cryostat_v1.json'
FILES=('index.html','summary.json','selected-channel.json')
PRIVATE=re.compile(r'[A-Za-z]:[\\/]+Users[\\/]|/mnt/[a-z]/|/home/[^/\s]+/|file:///|\.local[\\/]',re.I)


def require(ok,message):
    if not ok:raise ValueError(message)


def encoded(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf-8')+b'\n'


def sha(path):return W.sha(path)


def public(body):
    text=body.decode('utf-8')
    require(PRIVATE.search(text) is None,'Private paths cannot enter the GeGI publication.')
    require(not re.search(r'BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY|gh[pousr]_[A-Za-z0-9]{25,}|sk-proj-[A-Za-z0-9_-]{25,}',text),'Credential-like data cannot enter the GeGI publication.')
    return body


def saved_inputs(source,root=W.ROOT):
    root=Path(root).resolve();source=Path(source).resolve()
    require(source==W.run_path(source.name,root),'Publish a completed run in the project run directory.')
    receipt=G.inspect(source.name,root)
    require(receipt['status'] in W.TERMINAL and receipt.get('verification')=='terminal_artifacts_verified','Only verified completed GeGI results can be published.')
    plan=W.read(source/'resolved-config.json');complete=W.read(source/'COMPLETE.json')
    resolved=plan['resolved'];selection=resolved['selection'];configuration=W.digest(resolved)
    require(plan['kind']==complete['kind']==G.KIND and configuration==plan['configuration_sha256']==complete['configuration_sha256']==receipt['configuration_sha256'],'GeGI publication configuration identity changed.')
    for ref in ('resolved-config.json','response/results.json','response/run.json'):
        stamp=complete['artifacts'][ref];path=W.safe_path(source,ref)
        require(sha(path)==stamp['sha256'] and path.stat().st_size==stamp['bytes'],'Completed GeGI publication input changed: '+ref)
    payload=W.read(source/'response/results.json');response=W.read(source/'response/run.json')
    require(payload['kind']=='gegi_multichannel_results_v1' and payload['configuration_sha256']==response['configuration_sha256']==configuration,'Saved multichannel results differ from their configuration.')
    require(payload['counts']==response['counts'] and payload['counts']['initial_primaries']==selection['primary_count'],'GeGI publication primary census changed.')
    require(resolved['source_sha256'][ASSET]==sha(root/ASSET),'Cryostat source differs from the completed GeGI run.')
    return source,plan,payload,W.read(root/ASSET),complete


def selected_channel(payload):
    for event in sorted(payload['events'],key=lambda e:e['event_id']):
        channels=[c for c in (event.get('channels') or []) if c.get('trace') is not None]
        if channels:
            channel=max(channels,key=lambda c:abs(c.get('final_induced_keV') or 0))
            meta=next(c for c in payload['channels'] if c['id']==channel['contact_id'])
            return {'event_id':event['event_id'],'truth_edep_keV':event['truth_edep_keV'],
                    'contact':meta,'channel':channel,
                    'selection_rule':'Lowest original event ID with saved signals; channel with largest absolute terminal induced charge. Full-run counts are unchanged.'}
    return {'event_id':None,'contact':None,'channel':None,
            'selection_rule':'No stored event has a saved native/readout waveform. No zero waveform is fabricated.'}


def finite(value):
    require(type(value) in (int,float) and math.isfinite(value),'Publication geometry/plot contains a nonfinite value.')
    return value


def cryostat_svg(asset,source_position):
    measured=asset['measured_front'];nominal=asset['nominal_enclosure']
    front=finite(measured['crystal_front_z_mm']);outer_front=front+finite(measured['crystal_to_outer_front_mm'])
    inner_front=front+finite(nominal['crystal_to_inner_shield_gap_mm'])+finite(measured['inner_shield_thickness_mm'])
    rear=finite(nominal['outer_rear_z_mm']);radius=finite(nominal['outer_radius_mm'])
    hi=max(outer_front+12,finite(source_position[2])+8);lo=rear-8
    sx=lambda z:55+650*(z-lo)/(hi-lo)
    sy=lambda r:140-105*r/radius
    items=['<svg viewBox="0 0 760 320" role="img" aria-label="GeGI cryostat central cross section; measured front and nominal side and rear dimensions">']
    def box(z0,z1,r0,r1,color,dashed=False):
        items.append(f'<rect x="{sx(z0):.8g}" y="{sy(r1):.8g}" width="{sx(z1)-sx(z0):.8g}" height="{sy(r0)-sy(r1):.8g}" fill="{color}" stroke="#526575"'+(' stroke-dasharray="4 3"' if dashed else '')+'/>')
    def enclosure(z0,z1,r,t,rear_t,front_t):
        box(z0,z1,r-t,r,'#d9e2e8',True);box(z0,z1,-r,-r+t,'#d9e2e8',True)
        box(z0,z0+rear_t,-r+t,r-t,'#d9e2e8',True);box(z1-front_t,z1,-r+t,r-t,'#efb35c')
    enclosure(rear,outer_front,radius,finite(nominal['outer_side_thickness_mm']),finite(nominal['outer_rear_thickness_mm']),finite(measured['outer_cover_thickness_mm']))
    enclosure(finite(nominal['inner_shield_rear_z_mm']),inner_front,finite(nominal['inner_shield_radius_mm']),finite(nominal['inner_shield_side_thickness_mm']),finite(measured['rear_shield_thickness_mm']),finite(measured['inner_shield_thickness_mm']))
    box(-5.5,5.5,-45,45,'#80bdc7')
    items.append(f'<circle cx="{sx(source_position[2]):.8g}" cy="{sy(source_position[0]):.8g}" r="4" fill="#b52d38"/>')
    for x,y,text in ((55,22,'Central x–z section; z increases toward the front'),(55,275,'Blue: canonical Ge crystal; orange: measured front thicknesses.'),(55,296,'Dashed grey: nominal side/rear geometry; source x–z projection shown in red.')):
        items.append(f'<text x="{x}" y="{y}">{html.escape(text)}</text>')
    items.append('</svg>');return ''.join(items)


def trace_svg(trace,key,label,unit):
    times,values=trace['time_ns'],trace[key]
    require(len(times)==len(values) and len(times)>0,'Saved GeGI trace lengths changed.')
    for value in (*times,*values):finite(value)
    require(all(b>a for a,b in zip(times,times[1:])),'Saved GeGI trace times must increase.')
    xmin,xmax=times[0],times[-1];ymin,ymax=min(0,min(values)),max(0,max(values));dx=xmax-xmin or 1;dy=ymax-ymin or 1
    points=' '.join(f'{55+620*(t-xmin)/dx:.9g},{180-145*(v-ymin)/dy:.9g}' for t,v in zip(times,values))
    return (f'<figure><h3>{html.escape(label)} · {unit}</h3><svg viewBox="0 0 720 220" role="img" aria-label="{html.escape(label)} against time in ns">'
            f'<polyline fill="none" stroke="#007d8a" stroke-width="1.5" points="{points}"/>'
            f'<text x="4" y="25">{ymax:.8g}</text><text x="4" y="185">{ymin:.8g}</text>'
            f'<text x="55" y="210">{xmin:.8g} ns</text><text x="550" y="210">{xmax:.8g} ns</text></svg>'
            f'<figcaption>{len(times)} original signed analog samples. Exact values are in the selected-channel JSON.</figcaption></figure>')


def image_svg(image,*,color_max=None):
    x,y,values=image['azimuth_deg'],image['elevation_deg'],image['values']
    require(x and y and len(values)==len(y) and all(len(row)==len(x) for row in values),'GeGI direction image dimensions changed.')
    for value in (*x,*y,*(v for row in values for v in row)):finite(value)
    require(all(v>=0 for row in values for v in row),'Negative GeGI backprojection weight.')
    maximum=max(v for row in values for v in row)
    scale=maximum if color_max is None else finite(color_max)
    require(scale>=maximum,'Direction image color scale cannot clip a saved value.')
    parts=['<svg viewBox="0 0 760 390" role="img" aria-label="Saved Compton backprojection in detector azimuth and elevation">']
    for j,row in enumerate(values):
        for i,value in enumerate(row):
            f=value/scale if scale else 0;color=f'rgb({round(242-225*f)},{round(247-115*f)},{round(249-105*f)})'
            parts.append(f'<rect x="{55+650*i/len(x):.7g}" y="{25+300*(len(y)-j-1)/len(y):.7g}" width="{650/len(x)+.1:.7g}" height="{300/len(y)+.1:.7g}" fill="{color}"/>')
    parts.append(f'<text x="55" y="350">Azimuth {x[0]:g}°</text><text x="620" y="350">{x[-1]:g}°</text><text x="4" y="30">{y[-1]:g}°</text><text x="4" y="325">{y[0]:g}°</text><text x="55" y="378">Elevation increases upward; +z is the detector front. Maximum saved weight: {maximum:.9g}.</text></svg>')
    return ''.join(parts)


def planar_backproject(cones,plane_z_mm):
    """Saved cone vertices only; source coordinates never enter this calculation."""
    z=finite(plane_z_mm);ticks=[-100.+2.5*i for i in range(81)]
    values=[[0. for _ in ticks] for _ in ticks];unmapped=[];area=2.5**2
    for candidate in cones:
        vertex=candidate['vertex_mm'];axis=candidate['axis'];theta=finite(candidate['half_angle_deg']);weight=finite(candidate['weight'])
        require(len(vertex)==len(axis)==3 and 0<=theta<=180 and weight>0,'Invalid saved cone for planar backprojection.')
        for value in (*vertex,*axis):finite(value)
        require(math.isclose(sum(v*v for v in axis),1.,rel_tol=1e-6,abs_tol=1e-9),'Saved cone axis is not normalized.')
        rows=[]
        for y in ticks:
            row=[]
            for x in ticks:
                delta=(x-vertex[0],y-vertex[1],z-vertex[2]);distance=math.sqrt(sum(v*v for v in delta))
                if distance==0:row.append(0.);continue
                angle=math.degrees(math.acos(max(-1.,min(1.,sum(a*b for a,b in zip(delta,axis))/distance))))
                row.append(math.exp(-.5*((angle-theta)/5.)**2))
            rows.append(row)
        normalizer=math.fsum(v for row in rows for v in row)*area
        if normalizer<=0:
            unmapped.append({'event_id':candidate['event_id'],'order':candidate.get('order'),'weight':weight});continue
        for j,row in enumerate(rows):
            for i,value in enumerate(row):values[j][i]+=weight*value/normalizer
    return {'method':'finite_plane_saved_cone_backprojection_v1','plane_z_mm':z,
        'x_mm':ticks,'y_mm':ticks,'grid_step_mm':2.5,'kernel_sigma_deg':5.,'values':values,
        'value_units':'weighted accepted events per square millimetre','unmapped_cones':unmapped,
        'normalization':'Each recorded cone weight integrates over this finite grid using 6.25 mm^2 per cell; recorded valid-order weights sum to one per accepted event.',
        'limitations':['The search plane is an explicit input assumption, not an estimated source depth or range.',
            'Finite-plane cone backprojection is a display score, not an activity or source-count likelihood.',
            'The 5-degree kernel is a fixed display regularizer, not a measured spatial or angular resolution.',
            'No source positions, source labels, truth deposits or source-direction choices enter this projection.']}


def planar_svg(image,*,color_max=None,truth_markers=()):
    x,y,values=image['x_mm'],image['y_mm'],image['values'];maximum=max(v for row in values for v in row)
    scale=maximum if color_max is None else finite(color_max);require(scale>=maximum,'Plane image color scale cannot clip values.')
    parts=['<svg viewBox="0 0 760 490" role="img" aria-label="Saved cone backprojection onto the assumed source plane; input source positions are truth-only crosses">']
    for j,row in enumerate(values):
        for i,value in enumerate(row):
            f=value/scale if scale else 0;color=f'rgb({round(242-225*f)},{round(247-115*f)},{round(249-105*f)})'
            parts.append(f'<rect x="{75+580*i/len(x):.7g}" y="{25+390*(len(y)-j-1)/len(y):.7g}" width="{580/len(x)+.1:.7g}" height="{390/len(y)+.1:.7g}" fill="{color}"/>')
    for marker in truth_markers:
        px,py,pz=marker['position_mm']
        if not math.isclose(pz,image['plane_z_mm'],rel_tol=0,abs_tol=1e-9) or not -100<=px<=100 or not -100<=py<=100:continue
        sx=75+580*((px+100)/2.5+.5)/len(x);sy=25+390*((100-py)/2.5+.5)/len(y)
        parts.append(f'<path d="M{sx-6:.7g},{sy:.7g}h12 M{sx:.7g},{sy-6:.7g}v12" stroke="#b52338" stroke-width="2"/><text x="{sx+8:.7g}" y="{sy-7:.7g}">{html.escape(marker["source_run_key"])} truth</text>')
    parts.append(f'<text x="75" y="442">x: −100 to +100 mm</text><text x="5" y="28">y +100</text><text x="5" y="414">y −100</text><text x="75" y="468">Assumed z = {image["plane_z_mm"]:g} mm; crosses are input positions, not fitted peaks.</text></svg>')
    return ''.join(parts)


def render(summary,selected,asset):
    s=summary['selection'];counts=summary['counts'];image=summary['imaging'];measured=asset['measured_front']
    paragraphs=['<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>GeGI cryostat, multichannel signals and Compton image</title><style>body{font:16px/1.6 system-ui;max-width:1120px;margin:auto;padding:24px;color:#173047;background:#f6f8fa}section,figure{background:white;border:1px solid #d7e0e7;border-radius:10px;padding:20px;margin:18px 0}h1{line-height:1.15}a{color:#075e9b}svg{width:100%;height:auto;font-size:12px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}.grid figure{margin:0;min-width:0}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:.8rem}table{border-collapse:collapse;width:100%}td,th{padding:8px;text-align:left;border-bottom:1px solid #dce3e8}small,figcaption{color:#526575}@media(max-width:760px){.grid{grid-template-columns:1fr}}</style></head><body><nav><a href="../../index.html">GeSignal</a> · <a href="../../detectors/GeGI_3D/index.html">GeGI model and saved studies</a></nav><h1>GeGI cryostat, multichannel signals and Compton image</h1>',
        f'<p>Saved software acceptance: {s["primary_count"]} emitted {s["gamma_energy_keV"]:g} keV gamma rays, radiation seed {s["seed"]}. Isotropic point source at detector xyz {html.escape(str(s["source_position_mm"]))} mm. Original 92.3 K and −879 V / 0 V detector inputs are retained.</p>',
        '<section><h2>Cryostat geometry and its limits</h2>'+cryostat_svg(asset,s['source_position_mm']),
        f'<p>The crystal front is at z = {measured["crystal_front_z_mm"]:g} mm. The drawing specifies {measured["crystal_to_outer_front_mm"]:g} mm from crystal front to outer front, a {measured["outer_cover_thickness_mm"]:g} mm outer aluminium cover and a {measured["inner_shield_thickness_mm"]:g} mm inner aluminium shield. Side/rear dimensions and the split of the vacuum gap are explicit nominal modelling choices.</p>',
        '<p>Both named aluminium alloys use Geant4 pure aluminium. Internal holders, thermal links and instrument-body details are omitted. The cross section illustrates the selected geometry; it does not establish experimental efficiency.</p></section>',
        '<section><h2>Full event census and selection</h2><table><thead><tr><th>Saved quantity</th><th>Count</th></tr></thead><tbody>']
    for key,value in counts.items():
        if type(value) in (int,float):paragraphs.append(f'<tr><td>{html.escape(key.replace("_"," "))}</td><td>{value}</td></tr>')
    paragraphs.extend(['</tbody></table><p>All emitted primaries remain the efficiency denominator. Stored event rows contain the original nonzero IDs; native failures and readout rejections remain separate. X and Y strip families measure the same deposited energy and are never added together as independent deposits.</p>',
                       '<h3>Imaging cuts</h3><pre>'+html.escape(json.dumps(image.get('selection',{}),indent=2))+'</pre></section>',
                       '<section><h2>One actual saved channel</h2><p>'+html.escape(selected['selection_rule'])+'</p>'])
    if selected['channel'] is None:paragraphs.append('<p>No native/readout waveform is available in this run.</p>')
    else:
        c=selected['channel'];meta=selected['contact']
        paragraphs.append(f'<p>Original primary {selected["event_id"]}; {html.escape(meta["name"])} / contact {meta["id"]}. Truth Edep: {selected["truth_edep_keV"]:g} keV. Reconstructed channel energy: {html.escape(str(c.get("reconstructed_energy_keV")))} keV. Calibration comes from a separate charge injection.</p><div class="grid">')
        for key,label,unit in (('charge_fC','Induced charge','fC'),('current_nA','Induced current','nA'),('preamp_V','Preamplifier','V'),('shaped_V','Shaped signal','V')):
            paragraphs.append(trace_svg(c['trace'],key,label,unit))
        paragraphs.append('</div><p>Charge retains the native signed electrode signal. Current, preamplifier and shaped traces use fixed X = +1 / Y = −1 readout wiring; the signed native current remains in the channel JSON.</p>')
    paragraphs.extend(['<p><a href="selected-channel.json">Exact selected channel values and identity</a></p></section><section><h2>Signal-derived Compton direction image</h2>',
        f'<p>{html.escape(image["method"])}. Accepted events: {image["accepted_events"]}; rejected: {image["rejected_events"]}; ambiguous: {image["ambiguous_events"]}.</p>',
        image_svg(image),'<p>The reconstruction uses calibrated strip energies and timing. Truth positions and the known source direction do not choose the interaction order. A blank image or zero accepted cones is a retained result.</p><ul>'])
    for limitation in [*summary.get('limitations',[]),*image.get('limitations',[])]:paragraphs.append('<li>'+html.escape(limitation)+'</li>')
    paragraphs.extend(['</ul></section><section><h2>Traceability</h2><p><a href="summary.json">Counts, settings, image values and input hashes</a> · <a href="publication.json">Public artifact hashes</a></p><pre>'+html.escape(json.dumps(summary['input_sha256'],indent=2))+'</pre><p>The student software computes new results through Control. This website displays the saved acceptance run; it is not an experimental validation.</p></section></body></html>'])
    return public(''.join(paragraphs).encode('utf-8'))


def validate_bundle(directory):
    directory=Path(directory);record=W.read(directory/'publication.json')
    require(record['kind']==KIND and set(record['artifacts'])==set(FILES),'Unsupported GeGI publication inventory.')
    require({p.name for p in directory.iterdir()}==set(FILES)|{'publication.json'},'Unexpected GeGI publication files.')
    for name,digest in record['artifacts'].items():
        path=directory/name;require(not path.is_symlink() and path.is_file() and sha(path)==digest,'Saved GeGI publication changed: '+name);public(path.read_bytes())
    return record


def link_current(site):
    site=Path(site)
    if not (site/'examples/gegi/publication.json').is_file():return
    validate_bundle(site/'examples/gegi')
    path=site/'detectors/GeGI_3D/index.html'
    if not path.exists():return
    text=path.read_text(encoding='utf-8');text=re.sub(r'<section id="gegi-control-results">.*?</section>','',text,flags=re.S)
    section='<section id="gegi-control-results"><h2>GeGI cryostat and multichannel software run</h2><p><a href="../../examples/gegi/index.html">Inspect the actual saved acceptance run: cryostat layers, electrode signals and signal-derived Compton imaging</a>. Full emitted counts, original nonzero IDs, cuts and modelling limits remain explicit.</p></section>'
    require('<main' in text,'GeGI detector page lacks its main content.')
    text=re.sub(r'(<main\b[^>]*>)',lambda m:m[1]+section,text,count=1)
    path.write_text(text,encoding='utf-8',newline='\n')


def compact_source(source,root):
    """Release each full multichannel payload before reading another run."""
    source,plan,payload,asset,complete=saved_inputs(source,root);resolved=plan['resolved'];selected=selected_channel(payload)
    summary={'kind':KIND,'configuration_sha256':plan['configuration_sha256'],
             'selection':resolved['selection'],'counts':payload['counts'],
             'cryostat':{'id':asset['id'],'coordinate_convention':asset['coordinate_convention'],
                 'measured_front':{key:value for key,value in asset['measured_front'].items() if key!='source'},
                 'nominal_enclosure':asset['nominal_enclosure'],'radiation_material':asset['radiation_material'],
                 'omitted':asset['omitted']},
             'stored_nonzero_ids':[e['event_id'] for e in payload['events']],
             'channels':payload['channels'],'imaging':payload['imaging'],'limitations':payload.get('limitations',[]),
             'numerics':resolved['numerics'],'actual_fields':payload.get('fields'),
             'input_sha256':{'configuration':plan['configuration_sha256'],'resolved_config_bytes':sha(source/'resolved-config.json'),
                 'response_results':sha(source/'response/results.json'),'response_receipt':sha(source/'response/run.json'),
                 'completion':sha(source/'COMPLETE.json'),'cryostat_asset':sha(Path(root)/ASSET),
                 'model':resolved['model_sha256'],'publication_source':sha(Path(__file__))},
             'public_source_sha256':{ref:digest for ref,digest in resolved['source_sha256'].items() if ref.startswith(('tools/','transport/','simulation/','models/','scenarios/'))}}
    summary['depth_calibration_sha256']=W.digest(payload['depth_calibration']) if payload.get('depth_calibration') is not None else None
    summary['event_census']=[{'event_id':e['event_id'],'native_status':e.get('status'),
        'reconstruction_status':e.get('reconstruction',{}).get('status'),
        'rejection_reason':e.get('reconstruction',{}).get('reason'),
        'candidate_cone_count':len(e.get('reconstruction',{}).get('cones',[]))} for e in payload['events']]
    return summary,selected,asset


def combine_sources(sources,plane_z_mm):
    require(len(sources)==2,'A source comparison requires exactly two completed runs.')
    first,second=sources
    require(first['configuration_sha256']!=second['configuration_sha256'],'The same run cannot supply two sources.')
    for key in ('cryostat','detector','source','pose','gamma_energy_keV','electronics'):
        require(first['selection'][key]==second['selection'][key],'Source comparison requires unchanged '+key+'.')
    require(first['selection']['source_position_mm']!=second['selection']['source_position_mm'],'Source comparison requires different input positions.')
    for key in ('channels','numerics','depth_calibration_sha256'):
        require(first[key]==second[key],'Source comparison requires unchanged '+key+'.')
    for key in ('mode','cache_sha256','precision_bits'):
        require((first.get('actual_fields') or {}).get(key)==(second.get('actual_fields') or {}).get(key),
                'Source comparison field state differs: '+key)
    require(first['input_sha256']['model']==second['input_sha256']['model'] and first['input_sha256']['cryostat_asset']==second['input_sha256']['cryostat_asset'],'Source comparison model or cryostat changed.')
    for ref in ('simulation/gegi_response.jl','simulation/gegi_signal_helpers.jl','tools/gegi_imaging.py'):
        require(first['public_source_sha256'].get(ref)==second['public_source_sha256'].get(ref),'Source comparison response/imaging implementation changed.')
    image_keys=('method','coordinate_system','azimuth_deg','elevation_deg','solid_angle_per_cell_sr_by_row','value_units','kernel_sigma_deg','bin_width_deg','selection')
    for key in image_keys:
        require(first['imaging'].get(key)==second['imaging'].get(key),'Source comparison imaging contract differs: '+key)
    require(set(first['counts'])==set(second['counts']) and all(type(v) is int for s in sources for v in s['counts'].values()),'Source comparison requires matching complete integer census fields.')
    counts={key:sum(s['counts'][key] for s in sources) for key in first['counts']}
    cones=[];event_keys=[];event_census=[];planes=[]
    for source in sources:
        key=source['source_run_key'];ids=set(source['stored_nonzero_ids']);weights={}
        require(len(ids)==source['counts']['nonzero_primaries'],'Source nonzero census differs from saved IDs.')
        for candidate in source['imaging']['cones']:
            require(candidate['event_id'] in ids,'Saved cone has no original source-run event ID.')
            weights.setdefault(candidate['event_id'],[]).append(finite(candidate['weight']))
            cones.append(dict(candidate,source_run_key=key))
        require(len(weights)==source['imaging']['accepted_events'] and all(math.isclose(math.fsum(v),1.,rel_tol=1e-12,abs_tol=1e-12) for v in weights.values()),'Saved valid-order weights must sum to one per accepted event.')
        event_keys.extend({'source_run_key':key,'event_id':i} for i in source['stored_nonzero_ids'])
        event_census.extend(dict(e,source_run_key=key) for e in source['event_census'])
        plane=planar_backproject(source['imaging']['cones'],plane_z_mm)
        source['planar_imaging']=plane;planes.append(plane)
    image=copy.deepcopy(first['imaging'])
    image.update(values=[[math.fsum(s['imaging']['values'][j][i] for s in sources) for i in range(len(image['azimuth_deg']))] for j in range(len(image['elevation_deg']))],
        cones=cones,initial_primaries=counts['initial_primaries'],
        **{key:sum(s['imaging'][key] for s in sources) for key in ('accepted_events','rejected_events','ambiguous_events')})
    rejections=Counter()
    for source in sources:rejections.update(source['imaging'].get('rejection_counts',{}))
    image['rejection_counts']=dict(rejections)
    plane=copy.deepcopy(planes[0]);plane.update(values=[[math.fsum(p['values'][j][i] for p in planes) for i in range(81)] for j in range(81)],
        unmapped_cones=[dict(c,source_run_key=s['source_run_key']) for s in sources for c in s['planar_imaging']['unmapped_cones']])
    configuration={'kind':COMPARISON_KIND,'input_configurations':{s['source_run_key']:s['configuration_sha256'] for s in sources},
        'combination':'Raw sum of saved source-independent cone scores; no source balancing or source-direction selection.',
        'plane_z_mm':finite(plane_z_mm),'plane_xy_bounds_mm':[-100.,100.],'plane_step_mm':2.5,'plane_kernel_sigma_deg':5.}
    return {'kind':COMPARISON_KIND,'configuration_sha256':W.digest(configuration),'configuration':configuration,
        'sources':sources,'counts':counts,'stored_event_keys':event_keys,'event_census':event_census,
        'imaging':image,'planar_imaging':plane,'input_sha256':{s['source_run_key']:s['input_sha256'] for s in sources},
        'limitations':['Two separately simulated isolated-event datasets are combined; simultaneous-source pileup is not modeled.',
            'Source run keys preserve provenance but do not select interaction orders or modify cone weights.',
            'Raw accepted-event contributions and all initial denominators are summed without equalizing source intensities.',
            'Sparse or overlapping scores do not establish two resolved sources, a spatial resolution, source range or source activity.']}


def render_comparison(summary,selected,assets):
    sources=summary['sources'];plane=summary['planar_imaging'];image=summary['imaging']
    # Retain the existing self-contained presentation and wired-signal styling.
    head=render(sources[0],selected[0],assets[0]).decode('utf-8').split('<body>',1)[0]
    head=head.replace('<title>GeGI cryostat, multichannel signals and Compton image</title>','<title>GeGI spatial source comparison and blind mixture</title>')
    scale=max(v for row in plane['values'] for v in row);sky_scale=max(v for row in image['values'] for v in row)
    markers=[{'source_run_key':s['source_run_key'],'position_mm':s['selection']['source_position_mm']} for s in sources]
    parts=[head,'<body><nav><a href="../../index.html">GeSignal</a> · <a href="../../detectors/GeGI_3D/index.html">GeGI model</a></nav><h1>GeGI spatial source comparison and blind mixture</h1>',
        '<p>Two saved runs use the same gamma energy, detector, electronics, reconstruction cuts and cone weights. The mixture combines isolated events without using their source positions to reconstruct them. Original IDs are qualified by source run key.</p>',
        f'<p>Both input lines are {sources[0]["selection"]["gamma_energy_keV"]:g} keV. The known search-plane assumption is z = {plane["plane_z_mm"]:g} mm; this page does not infer depth, range or a three-dimensional source location.</p><table><tr><th>Input run key</th><th>Input position xyz · mm</th><th>Initial / zero / nonzero</th><th>Imaging accepted / ambiguous</th><th>Radiation seed</th></tr>']
    for source in sources:
        c=source['counts'];s=source['selection'];im=source['imaging'];key=source['source_run_key']
        parts.append(f'<tr><td><a href="#{key}">{key}</a></td><td>{html.escape(str(s["source_position_mm"]))}</td><td>{c["initial_primaries"]} / {c["zero_deposit_primaries"]} / {c["nonzero_primaries"]}</td><td>{im["accepted_events"]} / {im["ambiguous_events"]}</td><td>{s["seed"]}</td></tr>')
    parts.extend(['</table><p><strong>Separation assessment: inconclusive.</strong> This bounded comparison does not establish two resolved sources. Peaks in these scores are not fitted source locations.</p><section><h2>Blind mixture on the assumed source plane</h2>',
        f'<p>{summary["counts"]["initial_primaries"]} total emitted primaries remain the denominator; {image["accepted_events"]} accepted imaging events, {image["rejected_events"]} rejected nonzero events and {image["ambiguous_events"]} ambiguous accepted events. All plane panels share the same color scale, 0 to {scale:.9g} weighted accepted events/mm².</p>',
        planar_svg(plane,color_max=scale,truth_markers=markers),
        '<p>Red crosses show input-source truth only. Their separation does not demonstrate two reconstructed peaks. The fixed 5° kernel is a display regularizer, not a measured resolution. Each candidate retains its recorded valid-order weight; each accepted event integrates to total weight one across candidates on this finite plane.</p><h3>Full summed census</h3><pre>'+html.escape(json.dumps(summary['counts'],indent=2))+'</pre><h3>Common cuts</h3><pre>'+html.escape(json.dumps(image.get('selection',{}),indent=2))+'</pre></section>'])
    for source,choice,asset in zip(sources,selected,assets):
        key=source['source_run_key'];parts.extend([f'<section id="{key}"><h2>{key} · individual saved run</h2>',
            '<p>Input position '+html.escape(str(source['selection']['source_position_mm']))+' mm. Original nonzero event IDs: '+html.escape(', '.join(map(str,source['stored_nonzero_ids'])))+'.</p>',
            planar_svg(source['planar_imaging'],color_max=scale,truth_markers=[m for m in markers if m['source_run_key']==key]),
            '<details><summary>Counts, reconstruction rejections and cryostat</summary><pre>'+html.escape(json.dumps({'counts':source['counts'],'rejection_counts':source['imaging'].get('rejection_counts',{})},indent=2))+'</pre>'+cryostat_svg(asset,source['selection']['source_position_mm'])+'<p>Front-layer thicknesses come from the measured drawing; side/rear geometry and vacuum-gap split remain nominal. Aluminium alloys are represented by pure aluminium.</p></details>',
            '<details><summary>One actual saved electrode signal</summary><p>'+html.escape(choice['selection_rule'])+'</p>'])
        if choice['channel'] is not None:
            parts.append(f'<p>{key}, original primary {choice["event_id"]}, contact {choice["contact"]["id"]}. Truth Edep and calibrated readout energy remain separate in selected-channel.json.</p><div class="grid">')
            for trace_key,label,unit in (('charge_fC','Induced charge','fC'),('current_nA','Induced current','nA'),('preamp_V','Preamplifier','V'),('shaped_V','Shaped signal','V')):parts.append(trace_svg(choice['channel']['trace'],trace_key,label,unit))
            parts.append('</div><p>Charge retains the native signed electrode signal. Current, preamplifier and shaped traces use fixed X = +1 / Y = −1 readout wiring; the signed native current remains in the channel JSON.</p>')
        parts.append('</details></section>')
    parts.extend(['<details><summary>Supplemental direction maps · far-field approximation</summary><p>At these nearby source positions, the detector extent is not negligible. Direction-only maps cannot establish spatial source separation. The vertex-aware plane maps above use the declared plane assumption.</p><h2>Mixture directions</h2>',image_svg(image,color_max=sky_scale)])
    for source in sources:parts.extend(['<h3>'+source['source_run_key']+'</h3>',image_svg(source['imaging'],color_max=sky_scale)])
    parts.extend(['</details><section><h2>Limits and traceability</h2><ul>'])
    for limitation in [*summary['limitations'],*plane['limitations'],*image.get('limitations',[])]:parts.append('<li>'+html.escape(limitation)+'</li>')
    parts.extend(['</ul><p><a href="summary.json">Individual and mixture values, run-qualified IDs, cuts and hashes</a> · <a href="selected-channel.json">Exact selected channel from each input</a> · <a href="publication.json">Public artifact hashes</a></p><pre>'+html.escape(json.dumps(summary['input_sha256'],indent=2))+'</pre></section></body></html>'])
    return public(''.join(parts).encode('utf-8'))


def assemble(source,site,root=W.ROOT,*,plane_z_mm=None):
    inputs=list(source) if isinstance(source,(list,tuple)) else [source]
    require(len(inputs) in (1,2),'Publish one run or a comparison of exactly two runs.')
    require((len(inputs)==2)==(plane_z_mm is not None),'A two-source comparison requires an explicit assumed plane z; single-run publication stays direction-only.')
    summaries=[];selected=[];assets=[]
    for index,path in enumerate(inputs,1):
        # This call returns only compact records; its full JSON payload is freed
        # before the next source is opened, including large waveform arrays.
        item,choice,asset=compact_source(path,root)
        item['source_run_key']='source_'+str(index);choice['source_run_key']=item['source_run_key']
        summaries.append(item);selected.append(choice);assets.append(asset)
    if len(inputs)==1:
        summary=summaries[0];channel_document=selected[0];page=render(summary,channel_document,assets[0])
    else:
        summary=combine_sources(summaries,plane_z_mm)
        channel_document={'kind':COMPARISON_KIND,'sources':selected};page=render_comparison(summary,selected,assets)
    target=Path(site)/'examples/gegi'
    if target.exists():validate_bundle(target)
    bodies={'index.html':page,'summary.json':public(encoded(summary)),
            'selected-channel.json':public(encoded(channel_document))}
    target.mkdir(parents=True,exist_ok=True)
    for name,body in bodies.items():(target/name).write_bytes(body)
    (target/'publication.json').write_bytes(encoded({'kind':KIND,'configuration_sha256':summary['configuration_sha256'],
        'artifacts':{name:hashlib.sha256(body).hexdigest() for name,body in bodies.items()},'input_sha256':summary['input_sha256']}))
    validate_bundle(target);link_current(site)
    return target
