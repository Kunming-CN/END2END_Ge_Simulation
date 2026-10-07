"""Exact catalog YAML -> shared GDML/placement contract; no model whitelist.

The frozen LBNL position is retained. Cavity admission is only a necessary size
screen; the native exporter still checks all assembly overlaps and probe points.
"""
from __future__ import annotations
import ast, hashlib, json, math, re
from pathlib import Path
import xml.etree.ElementTree as ET
import handoff as h

KIND='catalog_detector_contract_v1'
SUPPORTED={'polycone','tube','box','union','intersection'}
OLD_MODELS={'AK02','SAP22','GeRC02','KMRC01_candidate','SAP18_ring08_scenario'}
CATALOG_POLICY={'workflow_kind':'local_catalog_workflow_v1','producer_adapter':'catalog_source_v1',
    'descriptor_kind':KIND,'cryostat':'lbnl_modular_nominal_v1','pose':'nominal','counts':[20,500],
    'model_rule':'Canonical complete model outside preserved legacy five; independently checked geometry and fixed cavity placement.',
    'source_rule':'Legacy Cs137 or an unchanged registered source with positive acceptance; gamma retains its legacy adapter.',
    'temperature_rule':'Original canonical YAML temperature; no legacy runtime override.',
    'readout_rule':'Original selected contact and voltages; signed native signal with fixed polarity inferred from contact levels.',
    'qualification':'Nominal engineering assembly; no experimental detector qualification or numerical convergence claim.'}

def scalar(value):
    h.require(type(value) in (int,float) and math.isfinite(value),'Finite numeric geometry value required')
    return float(value)

def origin(value):
    if value is None:return [0.,0.,0.]
    if type(value) is dict:
        h.require(set(value)<=set('xyz'),'Unknown geometry origin component')
        return [scalar(value.get(k,0)) for k in 'xyz']
    h.require(type(value) is list and len(value)==3,'Origin needs three coordinates')
    return list(map(scalar,value))

def yaw(value):
    h.require(value is None or type(value) is dict and set(value)<= {'Z'},'Only declared Z rotations are supported')
    return 0. if value is None else scalar(value.get('Z',0))

def validate_geometry(g):
    h.require(type(g) is dict and len(g)==1,'Geometry needs one declared primitive/operator')
    kind=next(iter(g));h.require(kind in SUPPORTED,'Unsupported semiconductor geometry: '+kind);v=g[kind]
    if kind in ('union','intersection'):
        h.require(type(v) is list and len(v)>=2,'Boolean geometry needs at least two children')
        for child in v:validate_geometry(child)
    elif kind=='polycone':
        h.require(type(v) is dict and set(v)=={'r','z'} and len(v['r'])==len(v['z'])>=4,'Invalid r/z polycone')
        points=[(scalar(r),scalar(z)) for r,z in zip(v['r'],v['z'])]
        h.require(points[0]==points[-1] and all(r>=0 for r,z in points) and h.revolved_volume(points)>0,'Invalid closed polycone')
    elif kind=='tube':
        h.require(type(v) is dict and set(v)<= {'r','h','origin','rotate'} and {'r','h'}<=set(v),'Unknown tube parameters')
        radii=v['r'];lo,hi=(scalar(radii['from']),scalar(radii['to'])) if type(radii) is dict and set(radii)=={'from','to'} else (0.,scalar(radii))
        h.require(0<=lo<hi and scalar(v['h'])>0,'Mass tube must have positive radius/height')
        origin(v.get('origin'));yaw(v.get('rotate'))
    else:
        h.require(type(v) is dict and set(v)<= {'widths','origin','rotate'} and 'widths' in v and len(v['widths'])==3,'Unknown box parameters')
        h.require(all(scalar(w)>0 for w in v['widths']),'Mass box widths must be positive')
        origin(v.get('origin'));yaw(v.get('rotate'))
    return g

def transform(point,translation,angle,inverse=False):
    a=math.radians(angle);c,s=math.cos(a),math.sin(a)
    if inverse:
        x,y,z=(point[i]-translation[i] for i in range(3));return [c*x+s*y,-s*x+c*y,z]
    x,y,z=point;return [c*x-s*y+translation[0],s*x+c*y+translation[1],z+translation[2]]

def _membership(g,point,tolerance=1e-6):
    kind=next(iter(g));v=g[kind]
    if kind in ('union','intersection'):
        values=[_membership(x,point,tolerance) for x in v]
        if kind=='union':return 'inside' if 'inside' in values else 'surface' if 'surface' in values else 'outside'
        return 'outside' if 'outside' in values else 'surface' if 'surface' in values else 'inside'
    if kind=='polycone':return h.membership(list(zip(v['r'],v['z'])),point,tolerance)
    x,y,z=transform(point,origin(v.get('origin')),yaw(v.get('rotate')),True)
    if kind=='box':margins=[scalar(w)/2-abs(c) for w,c in zip(v['widths'],(x,y,z))]
    else:
        r=math.hypot(x,y);rs=v['r'];lo,hi=(rs['from'],rs['to']) if type(rs) is dict else (0,rs)
        margins=[hi-r,scalar(v['h'])/2-abs(z)]
        if lo>0:margins.append(r-lo)
    return 'outside' if min(margins)<-tolerance else 'surface' if min(margins)<=tolerance else 'inside'

def membership(g,point,tolerance=1e-6):
    result=_membership(g,point,tolerance)
    if result=='surface' and next(iter(g)) in ('union','intersection'):
        # Touching primitive faces inside a Boolean union are not physical
        # crystal surfaces. Nearby directions distinguish internal interfaces.
        eps=max(10*tolerance,1e-5);near=[]
        for axis in range(3):
            for sign in (-1,1):
                probe=list(point);probe[axis]+=sign*eps;near.append(_membership(g,probe,tolerance/10))
        if 'outside' not in near:return 'inside'
    return result

def bounds(g):
    kind=next(iter(g));v=g[kind]
    if kind in ('union','intersection'):
        children=[bounds(x) for x in v];lo=min if kind=='union' else max;hi=max if kind=='union' else min
        return [fn(c[i] for c in children) for i,fn in enumerate((lo,hi,lo,hi,lo,hi))]
    if kind=='polycone':r=max(v['r']);return [-r,r,-r,r,min(v['z']),max(v['z'])]
    o=origin(v.get('origin'));a=math.radians(yaw(v.get('rotate')))
    if kind=='tube':r=v['r']['to'] if type(v['r']) is dict else v['r'];widths=[2*r,2*r,v['h']]
    else:widths=v['widths']
    dx=(abs(math.cos(a))*widths[0]+abs(math.sin(a))*widths[1])/2;dy=(abs(math.sin(a))*widths[0]+abs(math.cos(a))*widths[1])/2;dz=widths[2]/2
    return [o[0]-dx,o[0]+dx,o[1]-dy,o[1]+dy,o[2]-dz,o[2]+dz]

def simple_parameters(path):
    values={}
    def evaluate(node):
        if isinstance(node,ast.Constant):return scalar(node.value)
        if isinstance(node,ast.Name):return values[node.id]
        if isinstance(node,ast.UnaryOp) and isinstance(node.op,ast.USub):return -evaluate(node.operand)
        if isinstance(node,ast.BinOp):
            a,b=evaluate(node.left),evaluate(node.right)
            if isinstance(node.op,ast.Add):return a+b
            if isinstance(node.op,ast.Sub):return a-b
            if isinstance(node.op,ast.Mult):return a*b
            if isinstance(node.op,ast.Div):return a/b
        raise ValueError('Unsupported frozen geometry parameter expression')
    for file in (path/'chamber.tg',path/'shield.tg'):
        for line in file.read_text().splitlines():
            match=re.fullmatch(r':p\s+(\w+)\s+(.+)',line.strip())
            if match:
                name='inch' if match[1]=='in' else match[1]
                expression=re.sub(r'\bin\b','inch',match[2].replace('$',''))
                values[name]=evaluate(ast.parse(expression,mode='eval').body)
    return values

def cavity_contract(root=h.ROOT):
    root=Path(root);p=simple_parameters(root/'.local/transport/LBNL');nominal=json.loads((root/'transport/cryostat_nominal.json').read_text())
    halfx=p['Wir']/2-p['Tsd'];halfy=p['Hvc']/2;halfz=p['Lvc']/2
    return {'kind':'unchanged_lbnl_cavity_screen_v1','scope':'necessary envelope screen; native full overlap/probes remain required',
        'large_box_bounds_vacuum_mm':[-halfx,halfx,-halfy,halfy,-halfz,halfz],
        'maximum_front_z_mm':halfz+p['Rcr'],'crystal_in_vacuum_translation_mm':nominal['crystal_in_vacuum_translation_mm'],
        'coordinate_transform':nominal['coordinate_transform'],
        'upstream_sha256':{name:h.sha256(root/'.local/transport/LBNL'/name) for name in ('chamber.tg','shield.tg','stage.tg')},
        'nominal_sha256':h.sha256(root/'transport/cryostat_nominal.json')}

def placement_screen(local_bounds,cavity):
    x0,x1,y0,y1,z0,z1=local_bounds;t=cavity['crystal_in_vacuum_translation_mm']
    occupied=[x0+t[0],x1+t[0],z0+t[1],z1+t[1],-y1+t[2],-y0+t[2]]
    envelope=cavity['large_box_bounds_vacuum_mm'];reasons=[]
    for label,i in (('transverse x',0),('axial y',2)):
        if occupied[i]<envelope[i]-1e-9 or occupied[i+1]>envelope[i+1]+1e-9:
            reasons.append(f'Fixed LBNL {label} occupancy [{occupied[i]:g}, {occupied[i+1]:g}] mm exceeds cavity [{envelope[i]:g}, {envelope[i+1]:g}] mm.')
    if occupied[4]<envelope[4]-1e-9 or occupied[5]>cavity['maximum_front_z_mm']+1e-9:
        reasons.append('Fixed LBNL transverse z occupancy exceeds the cavity and front-corner envelope.')
    if z0<0:reasons.append(f'Original local z minimum {z0:g} mm extends below the unchanged support plane; holder overlap requires a different placement.')
    return {'occupied_bounds_vacuum_mm':occupied,'fits_large_box_envelope':all(occupied[i]>=envelope[i]-1e-9 and occupied[i+1]<=envelope[i+1]+1e-9 for i in (0,2,4)),
        'blocking_reasons':reasons,'status':'blocked_by_fixed_dimensions' if reasons else 'native_overlap_check_required'}

def load_model(model,root=h.ROOT):
    import yaml
    root=Path(root);catalog=json.loads((root/'models/catalog.json').read_text());matches=[m for m in catalog['detectors'] if m['id']==model]
    h.require(len(matches)==1,'Unknown/duplicate catalog model');entry=matches[0];file=root/'models'/entry['model']
    h.require(h.sha256(file)==entry['model_sha256'],'Frozen model bytes changed');doc=yaml.safe_load(file.read_bytes())
    h.require(doc['name']==model and doc['units']=={'length':'mm','angle':'deg','potential':'V','temperature':'K'} and len(doc['detectors'])==1,'Unsupported model identity/units')
    detector=doc['detectors'][0];sc=detector['semiconductor'];h.require(sc['material']=='HPGe' and doc['medium']=='vacuum','Unsupported semiconductor/medium')
    geometry=validate_geometry(sc['geometry']);b=bounds(geometry)
    # The intersection bound from child boxes is conservative. Catalog bound is
    # the established exact overall bound and is checked by native solid probes.
    if next(iter(geometry))!='intersection':h.require(all(math.isclose(a,c,abs_tol=1e-9,rel_tol=0) for a,c in zip(b,entry['bounds_mm'])),'YAML/catalog mass bounds differ')
    contacts={str(c['id']):scalar(c['potential']) for c in detector['contacts']};expected={str(c['id']):scalar(c['potential_V']) for c in entry['contacts']}
    h.require(contacts==expected and str(entry['readout_contact_id']) in contacts,'YAML/catalog contact or selected readout mismatch')
    readout=contacts[str(entry['readout_contact_id'])];others=[v for k,v in contacts.items() if k!=str(entry['readout_contact_id']) and v!=readout]
    h.require(others and (all(v>readout for v in others) or all(v<readout for v in others)),'Readout wiring cannot be inferred from a mixed-polarity contact set')
    deps={}
    for name in entry['dependencies']:
        file=(root/'models'/name).resolve();h.require(file.is_relative_to(root/'models'),'Model include escapes snapshots')
        expected=next(x['sha256'] for x in catalog['dependencies'] if x['path']==name);h.require(h.sha256(file)==expected,'Model dependency changed');deps['models/'+name]=expected
    cavity=cavity_contract(root);screen=placement_screen(entry['bounds_mm'],cavity)
    return {'kind':KIND,'schema_version':1,'model_id':model,'model_ref':'models/'+entry['model'],'model_sha256':entry['model_sha256'],
        'dependencies_sha256':deps,'catalog_sha256':h.sha256(root/'models/catalog.json'),'coordinate_system':doc['grid']['coordinates'],
        'geometry':geometry,'bounds_mm':entry['bounds_mm'],'contact_potentials_V':contacts,'readout_contact_id':entry['readout_contact_id'],
        'wiring_factor':1 if others[0]>readout else -1,'bias_span_V':max(contacts.values())-min(contacts.values()),
        'stored_temperature_K':scalar(sc['temperature']),'runtime_temperature_K':scalar(sc['temperature']),
        'temperature_policy':'original YAML temperature retained','qualification':entry['status'],'assumptions':entry['assumptions'],
        'cavity':cavity,'placement':screen,'scope':'unchanged nominal LBNL engineering placement; no experimental detector identity, CCE or resolution claim'}

def gdml_text(geometry):
    validate_geometry(geometry);root=ET.Element('gdml');ET.SubElement(root,'define');ET.SubElement(root,'materials');solids=ET.SubElement(root,'solids');serial=0
    def number(v):return format(float(v),'.17g')
    def compile(g):
        nonlocal serial
        serial+=1;name=f'catalog_solid_{serial}';kind=next(iter(g));v=g[kind]
        if kind in ('union','intersection'):
            first=compile(v[0])
            for child in v[1:]:
                second=compile(child);serial+=1;name=f'catalog_solid_{serial}';node=ET.SubElement(solids,kind,name=name)
                ET.SubElement(node,'first',ref=first);ET.SubElement(node,'second',ref=second)
                ET.SubElement(node,'position',name=name+'_position',unit='mm',x='0',y='0',z='0')
                ET.SubElement(node,'rotation',name=name+'_rotation',unit='deg',x='0',y='0',z='0');first=name
            return first
        if kind=='polycone':
            node=ET.SubElement(solids,'genericPolycone',name=name,startphi='0',deltaphi='360',aunit='deg',lunit='mm')
            for r,z in zip(v['r'][:-1],v['z'][:-1]):ET.SubElement(node,'rzpoint',r=number(r),z=number(z))
            return name
        if kind=='tube':
            r=v['r'];lo,hi=(r['from'],r['to']) if type(r) is dict else (0,r)
            ET.SubElement(solids,'tube',name=name,rmin=number(lo),rmax=number(hi),z=number(v['h']),startphi='0',deltaphi='360',aunit='deg',lunit='mm')
        else:ET.SubElement(solids,'box',name=name,lunit='mm',**dict(zip('xyz',map(number,v['widths']))))
        # The exporter consumes the germanium logical solid, rather than its
        # world placement. A native single-node MultiUnion therefore retains
        # each primitive's original model origin/rotation inside the solid.
        serial+=1;placed=f'catalog_solid_{serial}';multi=ET.SubElement(solids,'multiUnion',name=placed);node=ET.SubElement(multi,'multiUnionNode',name=placed+'_node')
        ET.SubElement(node,'solid',ref=name);ET.SubElement(node,'position',name=placed+'_position',unit='mm',**dict(zip('xyz',map(number,origin(v.get('origin'))))))
        ET.SubElement(node,'rotation',name=placed+'_rotation',unit='deg',x='0',y='0',z=number(yaw(v.get('rotate'))))
        return placed
    name=compile(geometry);ET.SubElement(solids,'box',name='world_solid',x='400',y='400',z='400',lunit='mm')
    structure=ET.SubElement(root,'structure');ge=ET.SubElement(structure,'volume',name='germanium');ET.SubElement(ge,'materialref',ref='G4_Ge');ET.SubElement(ge,'solidref',ref=name)
    world=ET.SubElement(structure,'volume',name='world');ET.SubElement(world,'materialref',ref='G4_Galactic');ET.SubElement(world,'solidref',ref='world_solid');pv=ET.SubElement(world,'physvol',name='germanium',copynumber='0');ET.SubElement(pv,'volumeref',ref='germanium')
    ET.SubElement(pv,'position',name='catalog_position',unit='mm',x='0',y='0',z='0')
    ET.SubElement(pv,'rotation',name='catalog_rotation',unit='deg',x='0',y='0',z='0')
    setup=ET.SubElement(root,'setup',name='Default',version='1.0');ET.SubElement(setup,'world',ref='world');ET.indent(root)
    return '<?xml version="1.0" encoding="UTF-8"?>\n'+ET.tostring(root,encoding='unicode')+'\n'

def probes(geometry):
    b=bounds(geometry);candidates=[]
    # Fixed lattice of representative interior/exterior points supplements exact
    # primitive surface/normal points. No shape is perturbed for an admission.
    for x in (b[0]-1,b[0],(b[0]+b[1])/2,b[1],b[1]+1):
        for y in (b[2]-1,b[2],(b[2]+b[3])/2,b[3],b[3]+1):
            for z in (b[4]-1,b[4],(b[4]+b[5])/2,b[5],b[5]+1):candidates.append([x,y,z])
    def visit(g):
        kind=next(iter(g));v=g[kind]
        if kind in ('union','intersection'):
            for child in v:visit(child)
        elif kind=='polycone':
            for (ra,za),(rb,zb) in zip(zip(v['r'],v['z']),zip(v['r'][1:],v['z'][1:])):
                length=math.hypot(rb-ra,zb-za)
                if length==0 or ra==rb==0:continue
                r,z=(ra+rb)/2,(za+zb)/2;nr,nz=-(zb-za)/length,(rb-ra)/length
                for eps in (-1e-5,0,1e-5):candidates.append([r+eps*nr,0,z+eps*nz])
        else:
            o=origin(v.get('origin'));a=yaw(v.get('rotate'))
            if kind=='box':
                w=v['widths']
                for axis in range(3):
                    for sign in (-1,1):
                        for eps in (-1e-5,0,1e-5):
                            p=[0.,0.,0.];p[axis]=sign*(w[axis]/2+eps);candidates.append(transform(p,o,a))
            else:
                r=v['r'];lo,hi=(r['from'],r['to']) if type(r) is dict else (0,r)
                for radius in (lo,hi):
                    if radius>0:
                        for eps in (-1e-5,0,1e-5):candidates.append(transform([radius+eps,0,0],o,a))
                for sign in (-1,1):
                    for eps in (-1e-5,0,1e-5):candidates.append(transform([(lo+hi)/2,0,sign*(v['h']/2+eps)],o,a))
    visit(geometry);unique={tuple(p):p for p in candidates}
    return [{'name':f'catalog_probe_{i}','position_mm':p,'expected':membership(geometry,p)} for i,p in enumerate(unique.values())]
