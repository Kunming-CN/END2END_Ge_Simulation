"""Export existing saved SSD VTP geometry into a small browser scene.

Run with ParaView pvpython. No fields, detector physics, or meshes are recomputed.
"""
import argparse,hashlib,json,re,sys
from pathlib import Path
from vtkmodules.vtkIOXML import vtkXMLPolyDataReader
from vtkmodules.vtkCommonCore import vtkIdList
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import render_contacts as RC

MODELS=('AK02','SAP22')
RUN='20260922_suite_v3'
MESHES=('crystal.vtp','contact_01.vtp','contact_02.vtp')
def require(ok,msg):
    if not ok:raise ValueError(msg)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump_bytes(x):return (json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False)+'\n').encode()
def read_poly(path):
    reader=vtkXMLPolyDataReader();reader.SetFileName(str(path));reader.Update()
    poly=reader.GetOutput();require(poly is not None and poly.GetNumberOfPoints()>0,'Empty VTP '+path.name)
    points=[[float(v) for v in poly.GetPoint(i)] for i in range(poly.GetNumberOfPoints())]
    faces=[];cells=poly.GetPolys();ids=vtkIdList();cells.InitTraversal()
    while cells.GetNextCell(ids):
        face=[int(ids.GetId(i)) for i in range(ids.GetNumberOfIds())]
        require(len(face)>=3 and max(face)<len(points),'Invalid face '+path.name);faces.append(face)
    require(faces,'No polygon faces '+path.name)
    return points,faces
def f3(values):
    require(len(values)==3,'Expected 3-vector');return [float(x) for x in values]
def bounds(layers):
    pts=[p for layer in layers for p in layer['vertices_mm']]
    return [min(p[i] for p in pts) for i in range(3)]+[max(p[i] for p in pts) for i in range(3)]
def export_model(model,out,catalog):
    require(model in MODELS,'Only reviewed AK02/SAP22 v1 scenes are supported')
    item=catalog[model];run=(ROOT/'Additional_Simulations/Visualization_3D/detectors'/model/'runs'/RUN).resolve()
    require(run.is_dir(),'Missing saved detector run')
    state=run/'01_geometry.pvsm'
    _,meta=RC.style_state(state.read_bytes(),run,item)
    layers=[]
    contacts={c['id']:c for c in item['contacts']}
    for name in MESHES:
        path=run/name;points,faces=read_poly(path);tr=meta['display_transforms'][name]
        orientation=f3(tr['Orientation']);origin=f3(tr['Origin'])
        require(orientation==[0.,0.,0.] and origin==[0.,0.,0.],'Viewer v1 requires zero actor rotation/origin')
        if name=='crystal.vtp':
            layer_id='crystal';label='Germanium crystal';role='semiconductor';contact=None
        else:
            cid=int(name[8:10]);c=contacts[cid];layer_id=f'contact:{cid}'
            label=f'Contact {cid}: {c["name"]} ({c["potential_V"]:g} V)';role='contact';contact=c
        style=RC.STYLE[name]
        layers.append({'id':layer_id,'label':label,'role':role,
            'contact':None if contact is None else {'id':contact['id'],'name':contact['name'],'potential_V':contact['potential_V']},
            'vertices_mm':points,'faces':faces,
            'display_transform':{'scale':f3(tr['Scale']),'translation_mm':f3(tr['Translation']),
                'orientation_deg':orientation,'origin_mm':origin,'kind':'display_only_antiflicker'},
            'style':{'rgb':style['rgb'],'opacity':style['opacity'],'color_name':style['color']},
            'source':{'file':name,'sha256':sha(path),'points':len(points),'faces':len(faces)}})
    payload={'schema_version':1,'scene_kind':'ssd_detector_geometry','model_id':model,
        'model_sha256':item['model_sha256'],'physical_length_unit':'mm',
        'coordinate_frame':'SSD model Cartesian coordinates','layers':layers,'bounds_mm':bounds(layers),
        'default_view':{'rotation_rad':[-0.45,0.65],'zoom':1.0},
        'source_run':RUN,'source_state_sha256':sha(state),
        'display_note':'Contact scale/translation are inherited anti-flicker styling only; not physical Li/contact thickness or event-coordinate transforms.'}
    content_id=hashlib.sha256(dump_bytes(payload)).hexdigest()
    scene={**payload,'scene_id':content_id}
    modeldir=out/model/content_id;modeldir.mkdir(parents=True)
    scene_path=modeldir/'scene.json';scene_path.write_bytes(dump_bytes(scene))
    manifest={'schema_version':1,'kind':'ssd_geometry_browser_asset','model_id':model,
        'asset_id':content_id,'asset_id_basis':'sha256 canonical scene payload before scene_id insertion',
        'scene_sha256':sha(scene_path),'scene_bytes':scene_path.stat().st_size,
        'model_sha256':item['model_sha256'],'source_state_sha256':sha(state),
        'source_mesh_sha256':{n:sha(run/n) for n in MESHES},
        'exporter_sha256':sha(__file__),'paraview_version':'6.1.1',
        'physics_recomputed':False,'mesh_regenerated':False}
    (modeldir/'manifest.json').write_bytes(dump_bytes(manifest))
    return {'model':model,'asset_id':content_id,'scene_bytes':scene_path.stat().st_size,
        'layers':{x['id']:{'points':len(x['vertices_mm']),'faces':len(x['faces'])} for x in layers}}
def main(out,models):
    out=out.resolve();local=(ROOT/'.local').resolve()
    require(out.is_relative_to(local) and not out.exists(),'Use a new .local output directory')
    require(models and len(models)==len(set(models)),'Unique model selection required')
    out.mkdir();catalog=RC.canonical_catalog();rows=[export_model(m,out,catalog) for m in models]
    top={'schema_version':1,'kind':'ssd_geometry_export','models':rows,
        'exporter_sha256':sha(__file__),'source':'Existing saved VTP/PVSM only; no physics or mesh generation'}
    (out/'export.json').write_bytes(dump_bytes(top));print(json.dumps(top,indent=2))
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--models',nargs='+',default=list(MODELS));a=p.parse_args();main(a.output,a.models)
