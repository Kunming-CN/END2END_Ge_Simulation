"""One saved-radiation reader with strict aliases and checked ring datasets."""
import hashlib
import html
import json
import posixpath
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
import geometry_web_delivery as geometry_delivery

ROOT=Path(__file__).resolve().parents[1]
MAIN_PAGE='viewers/events.html'
ROUTES={'examples/cs137-10k-geometry/geometry.html':'viewers/geant4-assembly.html',
        'examples/cs137-10k-hits/hit_event_view.html':'viewers/ge-positive.html'}
LEGACY_VIEWS={'examples/cs137-10k-geometry/geometry.html':'assembly',
              'examples/cs137-10k-hits/hit_event_view.html':'positive'}
PAGES={MAIN_PAGE:{'source':'tools/unified_event_viewer.html','view':'assembly','role':'canonical'},
       'viewers/geant4-assembly.html':{'source':'examples/cs137-10k-geometry/geometry.html','view':'assembly','role':'alias'},
       'viewers/ge-positive.html':{'source':'examples/cs137-10k-hits/hit_event_view.html','view':'positive','role':'alias'}}
PINS={'examples/cs137-10k-geometry/manifest.json':'e8d183af05e27f211b6464939d4c667b6d02855d68609a7627753d2f16edc379',
      'examples/cs137-10k-hits/manifest.json':'0ad6a0df52ae725543d0c8474c5db4474e6c28af537ff944660e1ebf9b6a1b3e'}
ORIGINAL_SOURCES={'tools/geometry_events.html':'b6322ea76fc067a0df0596978dae027d7aa7ad395b26d0a10779ce2b83cce0f2',
 'tools/hit_event_view.html':'7d609da3738490c1caa1c861f2810ec418f784f0640231d2465b92a2cc175516',
 'tools/geometry_events.py':'8473e9c6ae0ec8866ac0d720fa55a9cab4766c158d764fd30266668bdf8e05ca',
 'tools/hit_event_view.py':'7df235b8110fb19fbdf7c17ba18f7e7983fd3690af687fcd390cf7376649112e'}
SOURCES=('tools/viewer_navigation.py','tools/viewer_navigation.js',
         'tools/unified_event_viewer.html','tools/unified_event_viewer.js','tools/site_restructure.py','tools/site_routes.py',
         'tools/geometry_web_delivery.py','tools/result_web_delivery.py')
RESPONSE_BASE='examples/cs137-10k'
RESPONSE_PUBLICATION_PIN='554eece013b193baf48310f5dfb62379d63663fa1ac29a83866428ab52805eec'
RING_BASE='examples/cs137-10k-rings'
RING_KIND='ring_saved_publication_v1'
RING_MODELS=('GeRC02','KMRC01_candidate')
# Whole-manifest pins authorize protected older display reads only. New exports
# must bind current sources; a self-declared source inventory is never authority.
TRUSTED_PREVIOUS_MANIFESTS=frozenset({
 '4945d697ae27217b3c4ff008d247445af43a6f44c5a327a845a3e48aa20b5675',
 '2c65448b9bf9ab1eaf603e22e091d061cd6ace669601c9442fb5194a77a23e12'})
TRUSTED_PREVIOUS_UNIFIED_MANIFESTS=frozenset({
 # Exact completed f4422554 site-build predecessor, byte-matched to its
 # recorded site manifest before lossless geometry delivery was introduced.
 '656132da1a570d466238554b79cf0f8aa79df97dac5ec32757fc7267f2495b6e',
 # Exact 18d6b44 installed/Git snapshot before results/catalog curation.
 # Original scene, event and scientific source checks remain mandatory.
 'a4f2bd27ea7d7ab418a0d69bdd3e450c3e9db9891924be9facc72260b480d6f8',
 # Exact 5dfd5fa public/HEAD manifest before the homepage layout refresh;
 # all six source pins match that Git snapshot and saved data remain checked.
 'bfaaa2373df476d2f95e1cf1b266c600119a6692bda40173bde3ca01db17b4c3',
 # Exact 376bd39 manifest, byte matched to Git before geometry/context repair.
 '35f2d69c400f4b94308558b2a869595556acb7bf985c2e3c339c072b669dcbc3',
 # Exact a37cf4d deployed viewer, authenticated before the event-identity repair.
 '4f5e42c2e3ce3635e6007b2e1f66ece1022cb5dabaf7d655f73c3522381fe77d',
 # Exact 47685df Git/public bytes before the conditional GeGI hub schema.
 '0ce8330f3a246620d7d9f501a8232c8c461f5dfbb95c2bd33b0955a380f809e3',
 # Exact bfcb3bb published manifest, byte-matched to installed docs and Git
 # before the GeGI 1M navigation change; saved dataset checks remain strict.
 'e1bb2a61a3eb9f61ce7f794d254292aee4d9bb1678d0a91269495006973c89ca',
 # Exact published59f9d008c4ae Git manifest before the optional campaign route.
 'd44b2095341d3ed08eccd8e89320fe82cfb361d8d077ef8c30ab48599e68b3ee',
 # Exact cb52f02 Git bytes, before adding dedicated GeGI assembly navigation.
 'b748e1b35a7d38938fe0e6588dbf9c1dd5cdc81d49884f52879a55dbe41e4ffe',
 # Exact accepted 6db59a35 reader before Co60/source download updates.
 '7d61a001ff10dd56b50f879fda464edb455e27dcd464aaeaed8f9b76bef0bdc0',
 # Exact accepted0cf58d3 display before the1M overview correction.
 'e6d35df5c14b3de717f8e58235038301ba1384fe2e92260946c8cc7a86b45d92',
 # Exact accepted 5c21a3e display; current exports retain strict source checks.
 '0a42f23b8045a93b2aad96783841c5c6efa6a9320186b982c970974f052c2a10',
 '70c4a84008568b7b9a7fb6159a1e0c5736bafb5259a7d1fbe1232f0b2f51013e',
 '488bf59fe48a2bcfe14bfe8f428f200ee45587ef0f0f50fb79f1aba45b9b293c',
 'bc25cdba48e876df82af56f2713f2227292ae21ee6bf7f949dcfa6bd0cd83988',
 '1cec34532d0166bff8ead1f6d9c3a9d4234bdea9789b32aec06bec78c8cd85d6',
 # Verified before this four-model source upgrade; never derived from a new
 # self-declared adapter inventory.
 '27ec5778f811eae44a70f91106056567cd4bf07d0d503c2e4526ee4cc900941a',
 # Exact accepted 8ef88bd publication receipt, before shared-route navigation.
 '5453b82d3d8e019ffa79e408dcac4901a9188301406c66b5e61d2f9890ab9fc1',
 # Authenticated local 76a8596f stage before the bounded browser corrections.
 '387e4034bd43932320c53c202bf49d0a805b9d3b61a210f2695baaeb06072e4d'})

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def require(ok,message):
    if not ok:raise ValueError(message)
FROZEN={p:sha(ROOT/p) for p in SOURCES}
def frozen():require(FROZEN=={p:sha(ROOT/p) for p in SOURCES},'Viewer adapter sources changed during export')
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def replace(text,old,new):
    require(text.count(old)==1,'Viewer adapter anchor mismatch: '+old[:90])
    return text.replace(old,new,1)
def write(p,text):
    p=Path(p);body=text.encode('utf-8')
    if not p.exists() or p.read_bytes()!=body:p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(body)

def origins(site,checked=False):
    site=Path(site);out={}
    for rel,expected in PINS.items():
        folder=posixpath.dirname(rel);m=read(site/rel)
        compressed=rel==geometry_delivery.PREFIX+'/manifest.json' and m.get('kind')==geometry_delivery.KIND
        if compressed:
            m=geometry_delivery.validate(site/folder,check_events=checked)
            expected=sha(site/rel)
        else:require(sha(site/rel)==expected,'Original viewer manifest changed: '+rel)
        for name,record in m['files'].items():
            require(not name.startswith('/') and '\\' not in name and '..' not in Path(name).parts,'Unsafe original path')
            path=folder+'/'+name
            require(sha(site/path)==record['sha256'] and (site/path).stat().st_size==record['bytes'],'Original viewer asset changed: '+path)
            out[path]=record
        out[rel]={'sha256':expected,'bytes':(site/rel).stat().st_size}
    if checked:
        from geometry_publication import validate_bundle
        from hit_view_publication import validate
        if read(site/(geometry_delivery.PREFIX+'/manifest.json')).get('kind')!=geometry_delivery.KIND:
            validate_bundle(site/geometry_delivery.PREFIX)
        validate(site/'examples/cs137-10k-hits')
    return out

def route_links(text,page):
    def link(match):
        parts=urlsplit(html.unescape(match[2]))
        if parts.scheme or parts.netloc or not parts.path or parts.path.startswith('/'):return match[0]
        target=posixpath.normpath(posixpath.join(posixpath.dirname(page),parts.path))
        if target not in ROUTES:return match[0]
        # Preserve the old default mode explicitly, without dropping malformed or
        # repeated parameters. The canonical reader will reject those requests.
        query=parts.query+('&' if parts.query else '')+'view='+LEGACY_VIEWS[target]
        value=urlunsplit(('', '',posixpath.relpath(MAIN_PAGE,posixpath.dirname(page) or '.'),query,parts.fragment))
        return match[1]+html.escape(value,quote=True)+match[3]
    return re.sub(r'(href=["\'])([^"\']*)(["\'])',link,text)

def ring_bundle(site):
    """Read a completed public bundle only; never invoke its scientific writer."""
    folder=Path(site)/RING_BASE;path=folder/'manifest.json'
    if not path.exists():
        require(not folder.exists(),'Incomplete saved ring bundle: no manifest')
        return None
    m=read(path)
    require(m.get('kind')==RING_KIND and m.get('schema_version')==1 and m.get('status')=='complete'
            and set(m.get('models',{}))==set(RING_MODELS),'Incomplete saved ring manifest')
    for name in m['files']:
        require(isinstance(name,str) and name and not name.startswith('/') and '\\' not in name
                and not any(part in ('','.','..') for part in name.split('/')),'Unsafe saved ring path')
        asset=folder/name
        require(asset.resolve().is_relative_to(folder.resolve()),'Saved ring path outside bundle')
    actual={p.relative_to(folder).as_posix() for p in folder.rglob('*') if p.is_file()}
    if (folder/'web-delivery.json').is_file():
        from result_web_delivery import validate_bundle as validate_delivery
        validate_delivery(folder)
    else:
        require(actual==set(m['files'])|{'manifest.json'},'Saved ring file inventory mismatch')
        for name,record in m['files'].items():
            asset=folder/name
            require(sha(asset)==record['sha256'] and asset.stat().st_size==record['bytes'],
                    'Saved ring asset changed: '+name)
    for name,entry in m['models'].items():
        binding=entry['dataset_binding']
        binding_bytes=(json.dumps(binding,ensure_ascii=True,allow_nan=False,separators=(',',':'))+'\n').encode('utf-8')
        require(binding.get('kind')=='ring_model_saved_dataset_binding_v1' and binding.get('model_id')==name
                and binding.get('primary_count')==10000 and entry.get('model_id')==name
                and hashlib.sha256(binding_bytes).hexdigest()==entry['dataset_binding_sha256'],
                'Saved ring dataset binding mismatch: '+name)
        require(entry['scene']==name+'/scene.json' and entry['selected']==name+'/selected.json.gz'
                and entry['source_scene_sha256']==m['files'][entry['scene']]['sha256'],
                'Saved ring scene/selected binding mismatch: '+name)
        scene=read(folder/entry['scene']);index=scene['event_index']
        require(scene['model']==name and index['event_count']==10000 and len(index['chunks'])==100
                and all(c['first']==i*100 and c['count']==100
                        and m['files'][name+'/'+c['file']]['sha256']==c['sha256']
                        for i,c in enumerate(index['chunks'])),'Saved ring chunk census mismatch: '+name)
        for field in ('originals','response','response_report'):
            require(entry[field] in m['files'] and entry[field].startswith(name+'/'),
                    'Saved ring linked asset missing: '+field)
    return m

def ring_records(site,manifest):
    if manifest is None:return {}
    out={RING_BASE+'/'+name:record for name,record in manifest['files'].items()}
    folder=Path(site)/RING_BASE
    if (folder/'web-delivery.json').is_file():
        from result_web_delivery import MARKER, OMITTED
        delivery=read(folder/MARKER)
        for name in OMITTED:out.pop(RING_BASE+'/'+name)
        for name,record in delivery['html_rewrites'].items():
            out[RING_BASE+'/'+name]=record['delivered']
        out[RING_BASE+'/'+MARKER]={'sha256':sha(folder/MARKER),'bytes':(folder/MARKER).stat().st_size}
    path=Path(site)/RING_BASE/'manifest.json'
    out[RING_BASE+'/manifest.json']={'sha256':sha(path),'bytes':path.stat().st_size}
    return out

def response_records(site):
    """Expose only existing, checked files from the frozen AK02/SAP22 publication."""
    if site is None:return {}
    site=Path(site);publication=site/RESPONSE_BASE/'publication.json'
    if not publication.exists():return {}
    require(sha(publication)==RESPONSE_PUBLICATION_PIN,'Original response publication changed')
    m=read(publication);out={RESPONSE_BASE+'/publication.json':{'sha256':sha(publication),'bytes':publication.stat().st_size}}
    require(m['kind']=='native_publication_v1' and m['status']=='completed_with_native_failures',
            'Original response publication status changed')
    for name in ('AK02','SAP22'):
        for file in ('signals.csv','scalars.csv'):
            rel=name+'/response/'+file
            if rel not in m['files']:continue
            record=m['files'][rel];path=site/RESPONSE_BASE/rel
            require(sha(path)==record['sha256'] and path.stat().st_size==record['bytes'],
                    'Original response asset changed: '+rel)
            out[RESPONSE_BASE+'/'+rel]=record
    return out

def config(site=None):
    from site_routes import case_result_path, spectrum_path, event_view_path, relative_url, assembly_navigation
    out={'assembly':{'base':'../examples/cs137-10k-geometry/','sha256':PINS['examples/cs137-10k-geometry/manifest.json']},
         'positive':{'base':'../examples/cs137-10k-hits/','sha256':PINS['examples/cs137-10k-hits/manifest.json']}}
    # origins() is the byte-validation boundary; rendering selects its already
    # checked delivery without decompressing every shard again for each page.
    geometry=Path(site)/geometry_delivery.PREFIX/'manifest.json' if site is not None else None
    if geometry is not None and geometry.is_file() and read(geometry).get('kind')==geometry_delivery.KIND:
        original=geometry_delivery.source_manifest((geometry.parent/'original-manifest.json').read_bytes())
        out['assembly'].update(sha256=sha(geometry),kind=geometry_delivery.KIND,
            original_manifest_sha256=geometry_delivery.SOURCE_MANIFEST_SHA256,
            campaign_run_sha256=original['campaign_run_sha256'])
    out['geometry_navigation']=assembly_navigation(MAIN_PAGE)
    responses=response_records(site)
    out['case_routes']={name:{'result':relative_url(case_result_path(name),MAIN_PAGE),
        'model':name,
        'label':{'GeRC02':'GeRC02 · Li50min','KMRC01_candidate':'KMRC01 · candidate'}.get(name,name),
        'files':relative_url(case_result_path(name)+'#data-files',MAIN_PAGE),
        'spectrum':relative_url(spectrum_path(name),MAIN_PAGE),
        'events':relative_url(event_view_path(name),MAIN_PAGE),
        'original_files':{key:{'href':'../'+path,**responses[path]}
            for key,file in (('savedSignals','signals.csv'),('savedScalars','scalars.csv'))
            if (path:=RESPONSE_BASE+'/'+name+'/response/'+file) in responses}}
        for name in ('AK02','SAP22')+RING_MODELS}
    m=ring_bundle(site) if site is not None else None
    if m is not None:
        binding={'base':'../'+RING_BASE+'/','sha256':sha(Path(site)/RING_BASE/'manifest.json'),'kind':RING_KIND}
        out['models']={name:{'assembly':dict(binding),'positive':dict(binding)} for name in RING_MODELS}
        for name in RING_MODELS:
            out['case_routes'][name]['original_files']={key:{'href':'../'+RING_BASE+'/'+file,**m['files'][file]}
                for key,file in (('savedSignals',name+'/response/signals.csv'),
                    ('savedScalars',name+'/response/scalars.jsonl'),('savedCurrent',name+'/response/readout-input.csv'))
                if file in m['files']}
    return out

def render(site,page=MAIN_PAGE):
    frozen();site=Path(site);page=ROUTES.get(page,page)
    require(page in PAGES,'Unknown reader page: '+page)
    binding=PAGES[page];common=(ROOT/'tools/viewer_navigation.js').read_text(encoding='utf-8')
    if binding['role']=='canonical':
        text=(ROOT/binding['source']).read_text(encoding='utf-8')
        from site_routes import page_navigation
        text=replace(text,'__PRIMARY_NAVIGATION__',page_navigation(MAIN_PAGE,dataset='tenk'))
        text=replace(text,'__VIEWER_NAVIGATION__',common)
        text=replace(text,'__VIEWER_CONFIG__',json.dumps(config(site),separators=(',',':')))
        return replace(text,'__VIEWER_CONTROLLER__',(ROOT/'tools/unified_event_viewer.js').read_text(encoding='utf-8'))
    original=binding['source'];template='tools/geometry_events.html' if binding['view']=='assembly' else 'tools/hit_event_view.html'
    compressed=binding['view']=='assembly' and config(site)['assembly'].get('kind')==geometry_delivery.KIND
    if compressed:
        require((site/original).read_bytes()==geometry_delivery.REDIRECT,'Geometry redirect changed')
    else:require(sha(site/original)==ORIGINAL_SOURCES[template],'Original HTML pin mismatch')
    view=json.dumps(binding['view'])
    archive='' if compressed else ' · <a href="../'+original+'">Original viewer (archive)</a>'
    fallback=('Use the event viewer link above to choose a saved event.' if compressed else
              'This saved-link transition needs JavaScript. The original archived viewer remains available above.')
    # No renderer or data request lives in an alias. Invalid old queries stay
    # visible here; valid queries replace this history entry with the one reader.
    return ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
      '<title>GeSignal event viewer — saved link</title><meta name="description" content="A preserved event link to the unified saved-radiation viewer.">'
      '<link rel="canonical" href="https://kunming-cn.github.io/END2END_Ge_Simulation/viewers/events.html">'
      '<style>body{font:17px/1.5 system-ui;background:#0c1724;color:#e7f0fa;max-width:760px;margin:3rem auto;padding:1rem}a{color:#9edbff}a:focus-visible{outline:3px solid #ffd179}p{overflow-wrap:anywhere}</style></head><body>'
      '<h1>GeSignal event viewer</h1><p id="aliasStatus" role="status" aria-live="polite">Opening the saved event identity…</p>'
      '<p><a href="events.html">Choose an event in the unified viewer</a>'+archive+'</p>'
      '<noscript>'+fallback+'</noscript>'
      '<script id="viewer-navigation">'+common+'</script>\n<script id="viewer-alias">'
      'const alias=legacyViewerTarget(location.search,'+view+');'
      'if(alias.target)location.replace(alias.target+location.hash);'
      'else document.getElementById("aliasStatus").textContent="Unavailable saved-link request: "+alias.requested.invalid+" Query: "+location.search;'
      '</script></body></html>\n')

def assemble(site):
    site=Path(site)
    if not any((site/p).exists() for p in ROUTES):return None
    frozen();original=origins(site,checked=True);rings=ring_bundle(site)
    require({p:sha(ROOT/p) for p in ORIGINAL_SOURCES}==ORIGINAL_SOURCES,'Original viewer source changed')
    pages={}
    for dest,binding in PAGES.items():
        write(site/dest,render(site,dest));pages[dest]={**binding,'sha256':sha(site/dest)}
    frozen()
    m={'kind':'unified_geant4_reader_v1','original_files':original,'original_sources':ORIGINAL_SOURCES,
       'adapter_sources':FROZEN,'pages':pages,'saved_response_files':response_records(site),'new_simulations':0,
       'scope':'Earlier 10k/model saved radiation records; all primaries including zeros; assembly groups are return context only.'}
    if rings is not None:
        m['saved_ring_files']=ring_records(site,rings)
        m['scope']='Saved 10k/model radiation records: AK02, SAP22, GeRC02 Li50min and KMRC01 candidate; all primaries including zeros; assembly groups are return context only.'
    write(site/'viewers/manifest.json',json.dumps(m,indent=2)+'\n')
    return validate(site,True)

def validate(site,current=False):
    site=Path(site);manifest_path=site/'viewers/manifest.json';m=read(manifest_path)
    require(m['original_files']==origins(site),'Original file binding mismatch')
    require(m['original_sources']==ORIGINAL_SOURCES,'Original source binding mismatch')
    require(m.get('new_simulations')==0,'Display cannot authorize simulations')
    if m['kind']=='reciprocal_geant4_readers_v1':
        require(not current and sha(manifest_path) in TRUSTED_PREVIOUS_MANIFESTS,
                'Unknown older display; preserve the saved display instead of resealing it')
        require(set(m['adapter_sources'])=={'tools/viewer_navigation.py','tools/viewer_navigation.js','tools/viewer_overlay_selection.js'},'Older adapter source inventory mismatch')
        require(set(m['pages'])==set(ROUTES.values()),'Older reader route inventory mismatch')
        require({p.name for p in (site/'viewers').iterdir()}=={'manifest.json','geant4-assembly.html','ge-positive.html'},'Older reader file inventory mismatch')
        for src,dest in ROUTES.items():
            require(m['pages'][dest]=={'source':src,'sha256':sha(site/dest)},'Changed older display HTML')
        return m
    require(m['kind']=='unified_geant4_reader_v1','Wrong display manifest')
    previous=not current and sha(manifest_path) in TRUSTED_PREVIOUS_UNIFIED_MANIFESTS
    legacy_sources=set(SOURCES)-{'tools/geometry_web_delivery.py','tools/result_web_delivery.py'}
    require(set(m['adapter_sources'])==set(SOURCES) or
            (previous and set(m['adapter_sources']) in (legacy_sources,legacy_sources-{'tools/site_routes.py'},
                legacy_sources-{'tools/site_restructure.py','tools/site_routes.py'})),
            'Adapter source inventory mismatch')
    known_current=m['adapter_sources']==FROZEN
    require(known_current or (not current and sha(manifest_path) in TRUSTED_PREVIOUS_UNIFIED_MANIFESTS),
            'Unknown adapter source binding; preserve the saved display instead of resealing it')
    if current or known_current or sha(manifest_path) in (
            'bfaaa2373df476d2f95e1cf1b266c600119a6692bda40173bde3ca01db17b4c3',
            'd44b2095341d3ed08eccd8e89320fe82cfb361d8d077ef8c30ab48599e68b3ee',
            '0ce8330f3a246620d7d9f501a8232c8c461f5dfbb95c2bd33b0955a380f809e3'):
        rings=ring_bundle(site)
        require(m.get('saved_ring_files',{})==ring_records(site,rings),'Saved ring file binding mismatch')
        require(m.get('saved_response_files',{})==response_records(site),'Saved response file binding mismatch')
    require(set(m['pages'])==set(PAGES),'Reader route inventory mismatch')
    require({p.name for p in (site/'viewers').iterdir()}=={'manifest.json','events.html','geant4-assembly.html','ge-positive.html'},'Reader file inventory mismatch')
    if current:frozen()
    for dest,binding in PAGES.items():
        require(m['pages'][dest]=={**binding,'sha256':sha(site/dest)},'Changed display HTML or route binding')
        if current or known_current:require((site/dest).read_text(encoding='utf-8')==render(site,dest),'Nondeterministic reader')
    return m

def route_current_pages(site):
    for p in Path(site).rglob('*.html'):
        rel=p.relative_to(site).as_posix()
        if rel.startswith(('examples/','spectra/','viewers/','lithium/')):continue
        if rel.startswith('detectors/') and p.name not in ('index.html','gallery.html','technical.html'):continue
        text=p.read_text(encoding='utf-8');updated=route_links(text,rel)
        if text!=updated:write(p,updated)
