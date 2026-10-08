"""Publish validated SSD geometry scenes and a lightweight Canvas viewer."""
import hashlib,json,re,shutil
import geometry_catalog as GC
from html import escape
from site_fragments import remove_sections, prepend_main
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
    GC.validate_layers(scene,man)
    require((directory/'scene.json').stat().st_size==man['scene_bytes'],'Scene byte count')
    for layer in scene['layers']:
        require(layer['vertices_mm'] and layer['faces'],'Empty scene layer')
        require(layer['display_transform']['kind']=='display_only_antiflicker','Display transform semantics')
    return man,scene
def viewer_html(model,asset):
    require(TEMPLATE.is_file(),'Viewer template missing')
    text=TEMPLATE.read_text(encoding='utf-8')
    from site_routes import page_navigation
    require(text.count('<body>')==1,'Geometry viewer body anchor')
    require(text.count('__PAGE_NAVIGATION__')==1,'Geometry navigation placeholder')
    text=text.replace('__PAGE_NAVIGATION__',page_navigation('detectors/'+model+'/geometry.html',model=model).replace('<a ','<a target="_top" '))
    scene=f'geometry/{asset}/scene.json'; manifest=f'geometry/{asset}/manifest.json'
    require(text.count('__MODEL__')>=1 and text.count('__SCENE__')>=1 and text.count('__MANIFEST__')==1,'Viewer template placeholders')
    choices=''.join('<option value="'+escape(m)+'"'+(' selected' if m==model else '')+'>'+escape(m)+'</option>' for m in GC.catalog())
    item=GC.catalog()[model]
    qualification='<p class="note">Recorded model status: '+escape(item.get('status','Saved model'))+'.</p>'
    if model=='GeRC02':
        qualification+='<p class="note">Catalog geometry uses the original 30-minute GeRC02 model. The saved Cs137 10K case uses a separate Li50min operating variant.</p>'
    rows=''.join('<tr><td>'+str(c['id'])+'</td><td>'+escape(c['name'])+'</td><td>'+str(c['potential_V'])+'</td></tr>' for c in item['contacts'])
    key='<details><summary>Static contact key and signed potentials (V)</summary><p>Saved catalog reference readout contact: '+str(item['readout_contact_id'])+'. This is geometry metadata, not proof of LBNL full-chain support.</p><table><thead><tr><th>ID</th><th>Name</th><th>V</th></tr></thead><tbody>'+rows+'</tbody></table></details>'
    return text.replace('__MODEL_QUALIFICATION__',qualification).replace('__CONTACT_KEY__',key).replace('__READOUT__',str(item['readout_contact_id'])).replace('__MODELS__',choices).replace('__MODEL__',model).replace('__SCENE__',scene).replace('__MANIFEST__',manifest)
def assemble(source,site):
    source=Path(source).resolve();site=Path(site); export=read(source/'export.json')
    require(export['kind']=='ssd_geometry_export','Wrong geometry export');records={}
    for row in export['models']:
        model=row['model']; require(model in GC.catalog(),'Unexpected exported model')
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
        text=remove_sections(text,{'ssd-interactive-geometry'})
        require(len(re.findall(r'<main\b[^>]*>',text))==1,'Unexpected detector main element')
        section=(f'<section id="ssd-interactive-geometry"><h2>Interactive detector geometry</h2>'
                 f'<p>Rotate the saved SSD surface geometry and toggle the crystal/electrodes. '
                 f'<a href="geometry.html">Open full interactive geometry</a>. Display offsets are anti-flicker styling only.</p>'
                 f'<iframe title="{model} interactive detector geometry" src="geometry.html" '
                 f'style="width:100%;height:660px;border:1px solid #ccd;border-radius:8px" loading="lazy"></iframe></section>')
        page.write_text(prepend_main(text,section),encoding='utf-8',newline='\n')
        records[model]={'asset_id':asset,'scene_sha256':man['scene_sha256']}
    active_models=sorted(p.parent.name for p in (site/'detectors').glob('*/geometry-active.json'))
    coverage={'schema_version':1,'model_ids':active_models,'all_catalog_models':set(active_models)==set(GC.catalog())}
    (site/'detectors/geometry-index.json').write_text(json.dumps(coverage,sort_keys=True)+'\n',encoding='utf-8',newline='\n')
    return records
def validate_site(site):
    site=Path(site);records={}
    require(TEMPLATE.is_file(),'Viewer template missing')
    coverage=site/'detectors/geometry-index.json'
    models=read(coverage)['model_ids'] if coverage.is_file() else list(MODELS)
    require(set(models)<=set(GC.catalog()) and len(models)==len(set(models)),'Invalid viewer coverage')
    if coverage.is_file() and read(coverage)['all_catalog_models']:
        require(set(models)==set(GC.catalog()),'Incomplete all-detector viewer coverage')
    for model in models:
        viewer=site/'detectors'/model/'geometry.html'
        require(viewer.is_file(),'Missing geometry viewer '+model)
        page=(site/'detectors'/model/'index.html').read_text(encoding='utf-8')
        require(page.count('id="ssd-interactive-geometry"')==1 and
                ('src="geometry.html"' in page or 'href="geometry.html"' in page),
                'Detector viewer link '+model)
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

def refresh_viewers(site):
    """Refresh only HTML from verified active assets; no mesh export or solve."""
    site=Path(site)
    updated=[]
    for model in GC.catalog():
        active_file=site/'detectors'/model/'geometry-active.json'
        if not active_file.is_file():
            continue
        active=read(active_file)
        if active.get('model_id')!=model:
            raise ValueError('Active geometry model mismatch')
        asset=active['asset_id']
        validate_asset(active_file.parent/'geometry'/asset,model,asset)
        (active_file.parent/'geometry.html').write_text(viewer_html(model,asset),encoding='utf-8',newline='\n')
        updated.append(model)
    return updated
