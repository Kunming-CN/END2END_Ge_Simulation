"""Publish validated SSD geometry scenes and a lightweight Canvas viewer."""
import hashlib,json,re,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
MODELS=('AK02','SAP22')
TEMPLATE=ROOT/'tools/ssd_geometry_viewer.html'
PRIVATE=re.compile(rb'[A-Za-z]:[\\/]+Users[\\/]|file:///|/home/[^/\s]+/|gh[pousr]_[A-Za-z0-9]{25,}|sk-proj-[A-Za-z0-9_-]{25,}')
def require(ok,msg):
    if not ok: raise ValueError(msg)
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p): return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def canonical_scene_id(scene):
    payload=dict(scene); payload.pop('scene_id',None)
    raw=(json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=False)+'\n').encode()
    return hashlib.sha256(raw).hexdigest()
def validate_asset(directory,model,expected_asset=None):
    directory=Path(directory); man=read(directory/'manifest.json'); scene=read(directory/'scene.json')
    require(man['kind']=='ssd_geometry_browser_asset' and man['model_id']==model,'Geometry manifest identity')
    asset=man['asset_id']; require(re.fullmatch(r'[0-9a-f]{64}',asset) is not None,'Invalid geometry asset ID')
    require(expected_asset is None or asset==expected_asset,'Geometry export/manifest asset mismatch')
    require(directory.name==asset,'Geometry asset directory identity')
    require(scene['scene_id']==asset and scene['model_id']==model,'Geometry scene identity')
    require(canonical_scene_id(scene)==asset,'Geometry content-addressed identity')
    require(sha(directory/'scene.json')==man['scene_sha256'],'Geometry scene hash')
    require(scene['physical_length_unit']=='mm' and scene['scene_kind']=='ssd_detector_geometry','Scene units/kind')
    require([x['id'] for x in scene['layers']]==['crystal','contact:1','contact:2'],'Scene layer IDs')
    require(sum(len(x['faces']) for x in scene['layers'])==3712,'Unexpected polygon census')
    for layer in scene['layers']:
        require(layer['vertices_mm'] and layer['faces'],'Empty scene layer')
        require(layer['display_transform']['kind']=='display_only_antiflicker','Display transform semantics')
    return man,scene
def viewer_html(model,asset):
    require(TEMPLATE.is_file(),'Viewer template missing')
    text=TEMPLATE.read_text(encoding='utf-8')
    scene=f'geometry/{asset}/scene.json'; manifest=f'geometry/{asset}/manifest.json'
    require(text.count('__MODEL__')>=1 and text.count('__SCENE__')>=1 and text.count('__MANIFEST__')==1,'Viewer template placeholders')
    return text.replace('__MODEL__',model).replace('__SCENE__',scene).replace('__MANIFEST__',manifest)
def assemble(source,site):
    source=Path(source).resolve();site=Path(site); export=read(source/'export.json')
    require(export['kind']=='ssd_geometry_export','Wrong geometry export');records={}
    for row in export['models']:
        model=row['model']; require(model in MODELS,'Unexpected exported model')
        asset=row['asset_id']; src=source/model/asset; man,_=validate_asset(src,model,asset)
        dest=site/'detectors'/model/'geometry'/asset
        if dest.exists(): validate_asset(dest,model,asset)
        else:
            dest.mkdir(parents=True)
            for name in ('scene.json','manifest.json'): shutil.copyfile(src/name,dest/name)
        active={'schema_version':1,'model_id':model,'asset_id':asset,'scene_sha256':man['scene_sha256']}
        (site/'detectors'/model/'geometry-active.json').write_text(json.dumps(active,sort_keys=True,separators=(',',':'))+'\n',encoding='utf-8',newline='\n')
        (site/'detectors'/model/'geometry.html').write_text(viewer_html(model,asset),encoding='utf-8',newline='\n')
        page=site/'detectors'/model/'index.html'; text=page.read_text(encoding='utf-8')
        text=re.sub(r'<section id="ssd-interactive-geometry">.*?</section>','',text,flags=re.S)
        require(text.count('<main>')==1,'Unexpected detector main element')
        section=(f'<section id="ssd-interactive-geometry"><h2>Interactive detector geometry</h2>'
                 f'<p>Rotate the saved SSD surface geometry and toggle the crystal/electrodes. '
                 f'<a href="geometry.html">Open full interactive geometry</a>. Display offsets are anti-flicker styling only.</p>'
                 f'<iframe title="{model} interactive detector geometry" src="geometry.html" '
                 f'style="width:100%;height:660px;border:1px solid #ccd;border-radius:8px" loading="lazy"></iframe></section>')
        page.write_text(text.replace('<main>','<main>'+section,1),encoding='utf-8',newline='\n')
        records[model]={'asset_id':asset,'scene_sha256':man['scene_sha256']}
    return records
def validate_site(site):
    site=Path(site);records={}
    require(TEMPLATE.is_file(),'Viewer template missing')
    for model in MODELS:
        viewer=site/'detectors'/model/'geometry.html'
        require(viewer.is_file(),'Missing geometry viewer '+model)
        page=(site/'detectors'/model/'index.html').read_text(encoding='utf-8')
        require(page.count('id="ssd-interactive-geometry"')==1 and 'src="geometry.html"' in page,'Detector viewer link '+model)
        root=site/'detectors'/model/'geometry'; require(root.is_dir(),'Missing geometry asset root '+model)
        active_path=site/'detectors'/model/'geometry-active.json'; require(active_path.is_file(),'Missing active geometry record '+model)
        active=read(active_path); asset=active.get('asset_id','')
        require(active.get('model_id')==model and re.fullmatch(r'[0-9a-f]{64}',asset) is not None,'Invalid active geometry identity')
        dirs=[p for p in root.iterdir() if p.is_dir()]; require(dirs,'No published geometry asset '+model)
        for d in dirs: validate_asset(d,model,d.name)
        man,_=validate_asset(root/asset,model,asset); require(active.get('scene_sha256')==man['scene_sha256'],'Active scene hash mismatch')
        body=viewer.read_bytes(); require(not PRIVATE.search(body) and not PRIVATE.search(active_path.read_bytes()),'Private path in geometry publication')
        require('geometry/'+asset+'/scene.json' in viewer.read_text(encoding='utf-8'),'Viewer scene binding')
        require((site/'detectors'/model/'runs/20260922_suite_v3/01_geometry.png').is_file(),'Viewer poster missing')
        records[model]=asset
    return records
if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('site',type=Path);a=p.parse_args()
    print(json.dumps(assemble(a.source,a.site),indent=2))
