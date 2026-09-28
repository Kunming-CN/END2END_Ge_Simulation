"""Shared catalog checks for saved detector geometry; never executes a solver."""
import hashlib
import json
import math
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def catalog():
    data = json.loads((ROOT/'models/catalog.json').read_text(encoding='utf-8'))
    return {m['id']: m for m in data['detectors']}

def require(ok, message):
    if not ok:
        raise ValueError(message)

def mesh_names(item):
    ids = [c['id'] for c in item['contacts']]
    require(ids and all(type(i) is int and i > 0 for i in ids), 'Invalid contact IDs')
    require(len(ids) == len(set(ids)), 'Duplicate contact IDs')
    return ('crystal.vtp',) + tuple(f'contact_{i:02d}.vtp' for i in ids)

def display_metadata(state, run, item, renderer):
    if len(item['contacts']) == 2:
        return renderer.style_state(state.read_bytes(), run, item)[1]
    identity = {'Scale':[1,1,1], 'Translation':[0,0,0],
                'Orientation':[0,0,0], 'Origin':[0,0,0]}
    return {'display_transforms':{n:dict(identity) for n in mesh_names(item)}}

def layer_style(name, item, contact, renderer):
    if name == 'crystal.vtp' or len(item['contacts']) == 2:
        return renderer.STYLE[name]
    family = 'X' if contact['name'].startswith('X') else 'Y'
    return {'rgb':[0.85,0.27,0.12] if family == 'X' else [0.04,0.58,0.72],
            'opacity':0.85, 'color':family+' contact family'}

def validate_layers(scene, manifest):
    item = catalog().get(scene['model_id'])
    require(item is not None, 'Unknown scene detector')
    require(scene['model_sha256'] == manifest['model_sha256'] == item['model_sha256'],
            'Scene canonical model binding')
    names = mesh_names(item)
    expected = ['crystal'] + [f"contact:{c['id']}" for c in item['contacts']]
    require([x['id'] for x in scene['layers']] == expected, 'Scene layer IDs')
    require(set(manifest['source_mesh_sha256']) == set(names), 'Source mesh inventory')
    for layer, name in zip(scene['layers'], names):
        points, faces = layer['vertices_mm'], layer['faces']
        require(points and faces, 'Empty scene layer')
        require(all(len(p)==3 and all(type(v) in (int,float) and math.isfinite(v)
                    for v in p) for p in points), 'Nonfinite/malformed scene vertices')
        require(all(len(f)>=3 and all(type(i) is int and 0<=i<len(points) for i in f)
                    for f in faces), 'Invalid scene face index')
        src = layer['source']
        require(src['file']==name and src['sha256']==manifest['source_mesh_sha256'][name],
                'Layer source binding')
        require(src['points']==len(points) and src['faces']==len(faces), 'Layer census')
        style=layer['style']
        require(len(style['rgb'])==3 and all(type(v) in (int,float) and math.isfinite(v) and 0<=v<=1 for v in style['rgb']), 'Invalid layer color')
        require(type(style['opacity']) in (int,float) and math.isfinite(style['opacity']) and 0<=style['opacity']<=1, 'Invalid layer opacity')
        transform = layer['display_transform']
        require(transform['kind']=='display_only_antiflicker', 'Display transform semantics')
        for key in ('scale','translation_mm','orientation_deg','origin_mm'):
            require(len(transform[key])==3 and all(math.isfinite(v) for v in transform[key]),
                    'Invalid display transform')
        require(transform['orientation_deg']==[0,0,0] and transform['origin_mm']==[0,0,0],
                'Unsupported display rotation/origin')
        require(all(v>0 for v in transform['scale']), 'Invalid display scale')
        if layer['id']!='crystal':
            c = next(c for c in item['contacts'] if layer['id']==f"contact:{c['id']}")
            require(layer['role']=='contact' and layer['contact']['id']==c['id'], 'Layer/contact identity mismatch')
            require(layer['label']==f"Contact {c['id']}: {c['name']} ({c['potential_V']:g} V)", 'Contact label mismatch')
            require(layer['contact']=={k:c[k] for k in ('id','name','potential_V')},
                    'Canonical contact metadata mismatch')
        else:
            require(layer['role']=='semiconductor' and layer['contact'] is None,
                    'Semiconductor layer identity')
    all_points = [p for layer in scene['layers'] for p in layer['vertices_mm']]
    expected_bounds = [min(p[i] for p in all_points) for i in range(3)]
    expected_bounds += [max(p[i] for p in all_points) for i in range(3)]
    require(scene['bounds_mm']==expected_bounds, 'Physical scene bounds mismatch')

def multichannel_crystal_style(state_file, renderer):
    """Read only an existing crystal actor; never evaluate saved source programs."""
    import xml.etree.ElementTree as ET
    state = ET.fromstring(state_file.read_bytes()).find('ServerManagerState')
    require(state is not None and state.get('version')=='6.1.1', 'Saved scene version')
    proxies = {p.get('id'):p for p in state.findall('Proxy')}
    readers = [p for p in proxies.values() if p.get('type')=='XMLPolyDataReader'
               and any(v.replace('\\','/').endswith('/crystal.vtp')
                       for v in renderer.values(p,'FileName'))]
    require(len(readers)==1, 'Expected one saved crystal reader')
    reader_id = readers[0].get('id')
    actors = [p for p in proxies.values() if p.get('type')=='GeometryRepresentation'
              and p.find(f"Property[@name='Input']/Proxy[@value='{reader_id}']") is not None]
    require(len(actors)==1, 'Expected one saved crystal actor')
    actor = actors[0]
    transform = {k:[float(v) for v in renderer.values(actor,k)]
                 for k in ('Scale','Translation','Orientation','Origin')}
    require(transform['Orientation']==[0,0,0] and transform['Origin']==[0,0,0],
            'Unsupported saved crystal rotation')
    style = {'rgb':[float(v) for v in renderer.values(actor,'DiffuseColor')],
             'opacity':float(renderer.values(actor,'Opacity')[0]),
             'color':'saved crystal actor'}
    return transform, style
