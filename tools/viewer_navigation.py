"""Maintain reciprocal readers of two immutable, signed old-10k Geant4 bundles."""
import hashlib
import html
import json
import posixpath
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT=Path(__file__).resolve().parents[1]
ROUTES={'examples/cs137-10k-geometry/geometry.html':'viewers/geant4-assembly.html',
        'examples/cs137-10k-hits/hit_event_view.html':'viewers/ge-positive.html'}
PINS={'examples/cs137-10k-geometry/manifest.json':'e8d183af05e27f211b6464939d4c667b6d02855d68609a7627753d2f16edc379',
      'examples/cs137-10k-hits/manifest.json':'0ad6a0df52ae725543d0c8474c5db4474e6c28af537ff944660e1ebf9b6a1b3e'}
ORIGINAL_SOURCES={'tools/geometry_events.html':'b6322ea76fc067a0df0596978dae027d7aa7ad395b26d0a10779ce2b83cce0f2',
 'tools/hit_event_view.html':'7d609da3738490c1caa1c861f2810ec418f784f0640231d2465b92a2cc175516',
 'tools/geometry_events.py':'8473e9c6ae0ec8866ac0d720fa55a9cab4766c158d764fd30266668bdf8e05ca',
 'tools/hit_event_view.py':'7df235b8110fb19fbdf7c17ba18f7e7983fd3690af687fcd390cf7376649112e'}
SOURCES=('tools/viewer_navigation.py','tools/viewer_navigation.js','tools/viewer_overlay_selection.js')
# One exact checked pre-review display may be read during the source upgrade.
# This pins the ENTIRE manifest and therefore its exact HTML/artifact bindings;
# self-declared mismatched adapter hashes are never compatibility evidence.
TRUSTED_PREVIOUS_MANIFESTS=frozenset({'4945d697ae27217b3c4ff008d247445af43a6f44c5a327a845a3e48aa20b5675'})

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
        require(sha(site/rel)==expected,'Original viewer manifest changed: '+rel)
        folder=posixpath.dirname(rel);m=read(site/rel)
        for name,record in m['files'].items():
            require(not name.startswith('/') and '\\' not in name and '..' not in Path(name).parts,'Unsafe original path')
            path=folder+'/'+name
            require(sha(site/path)==record['sha256'] and (site/path).stat().st_size==record['bytes'],'Original viewer asset changed: '+path)
            out[path]=record
        out[rel]={'sha256':expected,'bytes':(site/rel).stat().st_size}
    if checked:
        from geometry_publication import validate_bundle
        from hit_view_publication import validate
        validate_bundle(site/'examples/cs137-10k-geometry');validate(site/'examples/cs137-10k-hits')
    return out

def route_links(text,page):
    def link(match):
        parts=urlsplit(html.unescape(match[2]))
        if parts.scheme or parts.netloc or not parts.path or parts.path.startswith('/'):return match[0]
        target=posixpath.normpath(posixpath.join(posixpath.dirname(page),parts.path))
        if target not in ROUTES:return match[0]
        value=urlunsplit(('', '',posixpath.relpath(ROUTES[target],posixpath.dirname(page) or '.'),parts.query,parts.fragment))
        return match[1]+html.escape(value,quote=True)+match[3]
    return re.sub(r'(href=["\'])([^"\']*)(["\'])',link,text)

def render(site,original):
    frozen();assembly='geometry.html'==Path(original).name
    template='tools/geometry_events.html' if assembly else 'tools/hit_event_view.html'
    require(sha(site/original)==ORIGINAL_SOURCES[template],'Original HTML pin mismatch')
    text=(site/original).read_text(encoding='utf-8')
    base='../'+posixpath.dirname(original)+'/'
    text=replace(text,'const response=await fetch(path);','const response=await fetch('+json.dumps(base)+'+path);')
    text=replace(text,'href="manifest.json"','href="'+base+'manifest.json"')
    text=replace(text,'</style>','''a.reader-button{display:inline-block;padding:10px;border:1px solid #9edbff;border-radius:6px;font-weight:600}a:focus-visible{outline:3px solid #ffd179;outline-offset:2px}a[aria-disabled]{opacity:.55}#identity{overflow-wrap:anywhere}.reader-nav{border:1px solid #64788c;padding:12px}*,*:before,*:after{box-sizing:border-box}canvas{max-width:100%}.bar label{max-width:100%}
</style>''')
    other='ge-positive.html' if assembly else 'geant4-assembly.html'
    button='Inspect this primary in the Ge-positive overlay' if assembly else 'Inspect this primary in the all-event assembly'
    note=('<nav class="reader-nav" aria-label="Current and archived event viewers"><div class="bar">'
          f'<a id="reciprocal" class="reader-button" data-kind="'+('assembly' if assembly else 'overlay')+f'" data-route="{other}" href="{other}">{button}</a>'
          '<a href="../results/cs137-10k/index.html">10k results</a></div>'
          '<p>Assembly: all 20,000 initial events (10,000/model), including zeros. Ge-positive overlay: 121 AK02 / 115 SAP22 primaries from the earlier 10k/model campaign; candidate counts are pulse groups.</p>'
          '<p id="identity" role="status" aria-live="polite"></p>'
          f'<p><a href="../{original}">Original viewer (archive; historical navigation, no current selection continuity)</a> · '
          f'<a href="{base}manifest.json">Original data manifest / downloads</a> · <a href="manifest.json">Current display provenance</a></p>'
          '<p>Local offline browsing: serve the complete site on localhost HTTP and open this reader. Direct file:// fetch is unsupported.</p></nav>')
    text=replace(text,'<header>','<header>'+note)
    common=(ROOT/'tools/viewer_navigation.js').read_text(encoding='utf-8')
    text=replace(text,"const $=id=>",common+"\nconst $=id=>")
    text=replace(text,"$('model').onchange=()=>{if(manifest)selectModel($('model').value);};",
                 "$('model').onchange=()=>{requestIdentity($('model').value,navigation.event,navigation.group);if(manifest)selectModel($('model').value);};")
    if assembly:
        text=replace(text,'http://127.0.0.1:8000/geometry.html','http://127.0.0.1:8000/viewers/geant4-assembly.html')
        text=replace(text,'serve the bundle using','serve the complete site root using')
        text=replace(text,"if(!scene)return;gate.invalidate();const chosenModel=model,chosenScene=scene;", "requestIdentity($('model').value,id,id===navigation.event?navigation.group:null);if(!scene)return;gate.invalidate();const chosenModel=model,chosenScene=scene;")
        text=replace(text,"selected=event;const rows=", "selected=event;successfulIdentity(model,id,navigation.group);const rows=")
        text=replace(text,'async function selectModel(name){','async function selectModel(name){\n  requestIdentity(name,navigation.event,navigation.group);')
        text=replace(text,"$('originals').href=manifest.models[name].originals;", "$('originals').href="+json.dumps(base)+"+manifest.models[name].originals;")
        text=replace(text,'fit();selectEvent(scene.event_index.ge_hit_ids[0]??0);', 'fit();selectEvent(navigation.event??scene.event_index.ge_hit_ids[0]??0);')
        text=text.replace("selectEvent(Number($('eid').value))","selectEvent(/^(0|[1-9][0-9]*)$/.test($('eid').value)?Number($('eid').value):NaN)")
        text=replace(text,"if(!Number.isInteger(id)||id<0||id>=scene.event_index.event_count){", "if(!Number.isInteger(id)||id<0||id>=scene.event_index.event_count){navigation.invalid='Invalid event; use an integer from 0 to 9999.';navigationLinks();")
        start="fetchJSON('manifest.json').then(m=>{manifest=m;return selectModel($('model').value);}).catch(error);"
        end="fetchJSON('manifest.json').then(m=>{manifest=m;navigationLinks();if(navigation.invalid){error(Error(navigation.invalid));return;}$('model').value=navigation.model;return selectModel(navigation.model);}).catch(error);"
    else:
        text=replace(text,'serve this directory with a localhost static server and open hit_event_view.html.',
                     'serve the complete site root with a localhost static server and open viewers/ge-positive.html.')
        text=replace(text,'href="../cs137-10k-geometry/geometry.html"','href="../examples/cs137-10k-geometry/geometry.html"')
        a=text.index('async function selectEvent(');b=text.index('function representativeButtons()',a)
        text=text[:a]+(ROOT/'tools/viewer_overlay_selection.js').read_text(encoding='utf-8')+'\n'+text[b:]
        text=replace(text,'async function selectModel(name){activeModel=name;', 'async function selectModel(name){requestIdentity(name,navigation.event,navigation.group);activeModel=name;')
        # Clear evidence synchronously, then reuse the original gate for model and event loads.
        text=replace(text,"function failure(error){$('status').textContent='Load failed: '+error.message;}","function failure(error){unavailableSelection('Load failed: '+error.message);}")
        start="fetchJSON('manifest.json').then(m=>{manifest=m;$('allEvents').href=m.all_events_url;for(const [key,label] of Object.entries(m.category_labels))$('category').append(option(key,label));return selectModel($('model').value);}).catch(failure);"
        end="fetchJSON('manifest.json').then(m=>{manifest=m;navigationLinks();for(const [key,label] of Object.entries(m.category_labels))$('category').append(option(key,label));if(navigation.invalid){failure(Error(navigation.invalid));return;}$('model').value=navigation.model;return selectModel(navigation.model);}).catch(failure);"
    text=replace(text,start,end)
    return text

def assemble(site):
    site=Path(site)
    if not any((site/p).exists() for p in ROUTES):return None
    frozen();original=origins(site,checked=True)
    require({p:sha(ROOT/p) for p in ORIGINAL_SOURCES}==ORIGINAL_SOURCES,'Original viewer source changed')
    pages={}
    for src,dest in ROUTES.items():
        write(site/dest,render(site,src));pages[dest]={'source':src,'sha256':sha(site/dest)}
    frozen()
    m={'kind':'reciprocal_geant4_readers_v1','original_files':original,'original_sources':ORIGINAL_SOURCES,
       'adapter_sources':FROZEN,'pages':pages,'new_simulations':0,'scope':'Earlier 10k/model saved radiation records; no group rendering in assembly, no absent-event substitution in overlay.'}
    write(site/'viewers/manifest.json',json.dumps(m,indent=2)+'\n')
    return validate(site,True)

def validate(site,current=False):
    site=Path(site);m=read(site/'viewers/manifest.json')
    require(m['kind']=='reciprocal_geant4_readers_v1','Wrong display manifest')
    require(m['original_files']==origins(site),'Original file binding mismatch')
    require(m['original_sources']==ORIGINAL_SOURCES,'Original source binding mismatch')
    require(set(m['adapter_sources'])==set(SOURCES),'Adapter source inventory mismatch')
    known_current=m['adapter_sources']==FROZEN
    require(known_current or (not current and sha(site/'viewers/manifest.json') in TRUSTED_PREVIOUS_MANIFESTS),'Unknown adapter source binding; preserve the saved display instead of resealing it')
    require(set(m['pages'])==set(ROUTES.values()),'Reader route inventory mismatch')
    require({p.name for p in (site/'viewers').iterdir()}=={'manifest.json','geant4-assembly.html','ge-positive.html'},'Reader file inventory mismatch')
    if current:frozen();require(m['adapter_sources']==FROZEN,'Adapter source mismatch')
    for src,dest in ROUTES.items():
        require(m['pages'][dest]=={'source':src,'sha256':sha(site/dest)},'Changed display HTML')
        if current or m['adapter_sources']==FROZEN:require((site/dest).read_text(encoding='utf-8')==render(site,src),'Nondeterministic reader')
    return m

def route_current_pages(site):
    for p in Path(site).rglob('*.html'):
        rel=p.relative_to(site).as_posix()
        if rel.startswith(('examples/','spectra/','viewers/','lithium/')):continue
        if rel.startswith('detectors/') and p.name not in ('index.html','gallery.html','technical.html'):continue
        text=p.read_text(encoding='utf-8');updated=route_links(text,rel)
        if text!=updated:write(p,updated)
