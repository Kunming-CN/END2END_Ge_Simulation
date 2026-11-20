"""Display identities and formal reading routes, independent of scientific inputs.

Keep existing URLs. Catalog models and publication records remain the science
authority; this module records page ownership and navigation only.
"""
import posixpath
import re
import json
from html import escape
from pathlib import Path

PRIMARY = (("results/index.html", "Results"), ("detectors/index.html", "Detectors"),
           ("assemblies/index.html", "Assemblies"),
           ("learn/index.html", "Learn"), ("guide.html", "Run locally"))
CASE_MODELS = ("AK02", "SAP22", "GeRC02", "KMRC01_candidate")
DATASETS = {
    "teaching": ("Six saved signals · selected from Cs-137 10K", "learn/signals/index.html"),
    "gamma": ("Cryostat gamma · nominal cryostat", "examples/gamma-native/gamma.html"),
    "tenk": ("Cs137 10K · four separate cryostat cases", "results/cs137-10k/index.html"),
    "million": ("Cs137 1M · two separate cryostat cases", "results/cs137-1m/index.html"),
    "gegi": ("GeGI · four independent acquisitions at two positions", "results/gegi-campaign/index.html"),
}
FIXED = {
    "index.html": ("GeSignal", None, "Home", "home", "site_restructure"),
    "results/index.html": ("Results", "index.html", "Results", "hub", "site_restructure"),
    "detectors/index.html": ("Detectors", "index.html", "Detectors", "hub", "site_restructure"),
    "assemblies/index.html": ("Assemblies", "index.html", "Assemblies", "hub", "site_restructure"),
    "assemblies/gegi/index.html": ("GeGI cryostat", "assemblies/index.html", "Assemblies", "assembly", "gegi_assembly_publication"),
    "guide.html": ("Run locally", "index.html", "Run locally", "guide", "site_guide"),
    "methods/index.html": ("Methods", "learn/index.html", "Learn", "hub", "site_restructure"),
    "learn/index.html": ("Learn", "index.html", "Learn", "hub", "site_restructure"),
    "scenarios/lbnl-cs137/index.html": ("Nominal LBNL cryostat", "assemblies/index.html", "Assemblies", "assembly", "site_restructure"),
    "examples/gegi/index.html": ("Historical GeGI two-position study", "results/index.html", "Results", "archive", "gegi_publication"),
    "results/gegi-campaign/index.html": ("GeGI four independent acquisitions", "results/index.html", "Results", "reader", "gegi_saved_publication"),
    "methods/native-li.html": ("Saved native Li study", "methods/index.html", "Methods", "method", "saved_archive_display"),
    "lithium/lithium.html": ("Lithium diagnostics", "methods/index.html", "Methods", "method", "saved_archive_display"),
    "results/cs137-10k/index.html": ("Cs137 10K", "results/index.html", "Results", "dataset", "ring_site"),
    "results/cs137-1m/index.html": ("Cs137 1M", "results/index.html", "Results", "dataset", "site_restructure"),
    "spectra/pipeline.html": ("Selected signals", "results/index.html", "Results", "reader", "teaching_examples"),
    "examples/gamma-native/gamma.html": ("Cryostat gamma", "results/index.html", "Results", "reader", "saved_focus_pages"),
    "spectra/cs137-10k.html": ("Stage spectra", "results/cs137-10k/index.html", "Results", "reader", "spectrum_display"),
    "spectra/million-truth.html": ("Deposition spectra", "results/cs137-1m/index.html", "Results", "reader", "spectrum_display"),
    "spectra/million-response.html": ("Response spectra", "results/cs137-1m/index.html", "Results", "reader", "spectrum_display"),
    "viewers/events.html": ("3D radiation events", "results/cs137-10k/index.html", "Results", "reader", "viewer_navigation"),
}
ALIASES = {"viewers/ge-positive.html": "viewers/events.html",
           "viewers/geant4-assembly.html": "viewers/events.html"}
CANONICAL_VIEWS = {
    'spectra/cs137-10k.html': 'results/cs137-10k/spectra.html',
    'viewers/events.html': 'results/cs137-10k/events.html',
    'spectra/million-truth.html': 'results/cs137-1m/spectra/deposition.html',
    'spectra/million-response.html': 'results/cs137-1m/spectra/response.html',
    'spectra/pipeline.html': 'learn/signals/index.html',
    'scenarios/lbnl-cs137/index.html': 'assemblies/lbnl/index.html',
    'methods/native-li.html': 'results/native-li-selected-events/index.html',
    'lithium/lithium.html': 'results/lithium-diagnostics/index.html',
    'detectors/GeGI_3D/strip_explorer.html': 'results/gegi-strip-study/index.html',
    'detectors/GeGI_3D/supplement.html': 'results/gegi-notebook-study/index.html',
}
GEGI_STUDIES = {
    'gegi-shared-readout': 'GeGI historical shared readout · 25 × 250 ms',
    'gegi-short-exposure': 'GeGI short exposure & energy reconstruction',
    'gegi-shared-clock-controls': 'GeGI shared clock & merged triggers',
    'gegi-plane-prior-study': 'GeGI imaging priors & weak strips',
    'gegi-position-calibration': 'GeGI position, depth & threshold calibration',
    'gegi-double-pulse': 'GeGI double-pulse resolution',
    'gegi-pairing-benchmark': 'GeGI strip pairing & order benchmarks',
}
for slug, title in GEGI_STUDIES.items():
    FIXED[f'results/{slug}/index.html'] = (title, 'results/index.html', 'Results', 'study', 'gegi_digital_display')
for old, new in CANONICAL_VIEWS.items():
    if old in FIXED:
        FIXED[new] = FIXED[old]
FIXED['learn/signals/index.html'] = ('Six saved signals', 'learn/index.html', 'Learn', 'reader', 'teaching_examples')
for slug, title in (('native-li-selected-events', 'Selected native Li readout events'),
                    ('lithium-diagnostics', 'Li numerical diagnostics'),
                    ('gegi-strip-study', 'GeGI early strip signals'),
                    ('gegi-notebook-study', 'GeGI executed field & signal notebook')):
    FIXED[f'results/{slug}/index.html'] = (title, 'results/index.html', 'Results', 'study', 'saved_archive_display')
DETECTOR_VIEWS = (("index.html", "Overview"), ("geometry.html", "Geometry"),
                  ("gallery.html", "Saved fields & signals"), ("technical.html", "Model & files"))
NAV_STYLE = '''body{overflow-wrap:anywhere}
@media(max-width:450px){.channels{grid-template-columns:repeat(3,minmax(0,1fr))}}
#page-navigation{width:100%;font:16px/1.6 system-ui;color:#173047;background:#fff;margin:0 0 24px;padding:16px 20px;border:1px solid #d7e0e7;border-radius:12px;box-sizing:border-box;text-align:left}
#page-navigation [hidden]{display:none}
#page-navigation nav{display:flex;flex-wrap:wrap;gap:8px 14px;margin:10px 0}
#page-navigation a{color:#075e9b;background:transparent;border-radius:0;text-decoration:none;padding:4px 0}
#page-navigation a[aria-current]{font-weight:700;text-decoration:underline;text-underline-offset:5px}
#page-navigation ol{display:flex;flex-wrap:wrap;list-style:none;gap:7px;margin:0;padding:0}
#page-navigation li+li:before{content:"›";padding-right:7px;color:#526575}
#page-navigation .dataset-context{padding:8px 0;border-top:1px solid #d7e0e7}
#page-navigation p{margin:5px 0;overflow-wrap:anywhere}#page-navigation a:focus-visible{outline:3px solid #f8ad30}
#page-navigation .site-heading{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:12px 24px;border-bottom:1px solid #d7e0e7;padding-bottom:8px}
#page-navigation .site-brand{font-size:20px;font-weight:750;color:#173047}
#page-navigation .source-link{font-size:14px;color:#34566e}
#page-navigation .dataset-context{font-size:14px}#page-navigation .dataset-context p{max-width:80ch}
#page-navigation nav[aria-label="Primary"]{margin:0;min-height:36px;align-items:center}
#page-navigation nav[aria-label="Primary"] a{padding:8px 4px}
#page-navigation a[aria-current]{text-decoration:none;border-bottom:3px solid #075e9b}
#page-navigation nav[aria-label="Breadcrumb"]{font-size:14px}
button,input,select,summary{font:inherit}button:focus-visible,input:focus-visible,select:focus-visible,summary:focus-visible{outline:3px solid #b25700;outline-offset:3px}
@media(max-width:600px){#page-navigation{font-size:14px}#page-navigation nav{gap:6px 12px}}'''

NAV_SCRIPT = '''<script data-site-navigation>
(()=>{const root=document.getElementById('page-navigation');if(!root)return;
function sync(){const current=new URL(location.href);root.querySelectorAll('nav[aria-label="Dataset views"],nav[aria-label="Detector views"]').forEach(nav=>{
const links=[...nav.querySelectorAll('a[href]')];let match=null;
for(const link of links){link.removeAttribute('aria-current');const url=new URL(link.href);if(url.pathname===current.pathname&&url.hash&&url.hash===current.hash)match=link;}
if(!match)match=links.find(link=>{const url=new URL(link.href);return url.pathname===current.pathname&&!url.hash;});
if(!match){const samePage=links.filter(link=>new URL(link.href).pathname===current.pathname);if(samePage.length===1)match=samePage[0];}
if(match)match.setAttribute('aria-current','page');});
if(current.hash){let id;try{id=decodeURIComponent(current.hash.slice(1));}catch{return;}
const target=document.getElementById(id);if(target){let node=target,opened=false;while(node){if(node.tagName==='DETAILS'&&!node.open){node.open=true;opened=true;}node=node.parentElement;}
if(opened)requestAnimationFrame(()=>target.scrollIntoView());}}}
addEventListener('hashchange',sync);addEventListener('popstate',sync);addEventListener('DOMContentLoaded',sync);sync();})();
</script>'''

def require(ok, message):
    if not ok:
        raise ValueError(message)

def case_result_path(model):
    require(model in CASE_MODELS, "Unknown saved 10K case")
    return f"results/cs137-10k/{model}/charge-readout.html"

def event_view_path(model=None, view="positive"):
    require(view in ("positive", "assembly"), "Unknown event view")
    if model is None:
        return "results/cs137-10k/events.html"
    require(model in CASE_MODELS, "Unknown saved 10K case")
    return f"results/cs137-10k/events.html?model={model}&view={view}"

def spectrum_path(model=None):
    require(model is None or model in CASE_MODELS, "Unknown saved 10K case")
    return "results/cs137-10k/spectra.html" + (f"#tenk-{model}" if model else "")

def relative_url(path, current_path):
    base, suffix = re.split(r"(?=[?#])", path, maxsplit=1) if re.search(r"[?#]", path) else (path, "")
    return posixpath.relpath(base, posixpath.dirname(current_path) or ".") + suffix

def page_record(path):
    """Resolve a fixed display identity; never infer identity from referrer."""
    if path in FIXED:
        title, parent, section, role, owner = FIXED[path]
    elif path in ALIASES:
        title, parent, section, role, owner = "Viewer compatibility address", "results/cs137-10k/index.html", "Results", "alias", "viewer_navigation"
    elif re.fullmatch(r"results/cs137-10k/[^/]+/charge-readout.html", path):
        model = path.split("/")[2]
        case_result_path(model)
        label = 'GeRC02 · Li50min' if model == 'GeRC02' else 'KMRC01 candidate' if model == 'KMRC01_candidate' else model
        title, parent, section, role, owner = label + " · charge & readout", "results/cs137-10k/index.html", "Results", "case", "ring_site"
    elif re.fullmatch(r"detectors/[A-Za-z0-9_-]+/(index|geometry|gallery|technical|strip_explorer|supplement).html", path):
        _, model, name = path.split("/")
        titles = dict(DETECTOR_VIEWS)
        title = model if name == "index.html" else titles.get(name, "Saved strip study" if name == "strip_explorer.html" else "Historical supplemental study")
        parent = "detectors/index.html" if name == "index.html" else f"detectors/{model}/" + ("gallery.html" if name in ("strip_explorer.html", "supplement.html") else "index.html")
        section, role, owner = "Detectors", "detector" if name in titles else "study", "site_detector_pages"
    elif path.startswith("examples/") and path.endswith(".html"):
        if path.startswith("examples/native-li/"):
            parent, section = "results/native-li-selected-events/index.html", "Results"
        elif path == "examples/pipeline.html":
            parent, section = "results/index.html", "Results"
        elif path.startswith("examples/cs137-1m"):
            parent, section = "results/cs137-1m/index.html", "Results"
        elif path.startswith("examples/cs137-10k"):
            models = [part for part in path.split("/") if part in CASE_MODELS]
            parent, section = case_result_path(models[0]) if models else "results/cs137-10k/index.html", "Results"
        else:
            raise ValueError("Unregistered original report: " + path)
        title, role, owner = "Original saved report", "archive", "frozen_publication"
    else:
        raise ValueError("Unregistered display page: " + path)
    canonical = CANONICAL_VIEWS.get(path, path)
    study = canonical.split('/')[1] if canonical.startswith('results/') and canonical != 'results/index.html' else None
    case = canonical.split('/')[2] if re.fullmatch(r'results/cs137-10k/[^/]+/charge-readout.html',canonical) else None
    view = ('readout' if case else 'spectra' if '/spectra' in canonical else 'events' if canonical.endswith('/events.html') else 'overview')
    return dict(page_id=path, path=path, title=title, parent_id=parent,
                section=section, section_id=section.lower().replace(' ','-'), role=role, owner=owner,
                study_id=study, case_id=case, view_id=view, model_id=case or (path.split('/')[1] if path.startswith('detectors/') and path.count('/')>1 else None),
                variant_id='GeRC02_Li50min' if case=='GeRC02' else case,
                canonical_path=canonical)

def registry(site):
    """All HTML, including disconnected archives and compatibility aliases."""
    site = Path(site)
    return {p.relative_to(site).as_posix(): page_record(p.relative_to(site).as_posix())
            for p in sorted(site.rglob("*.html"))}

def primary_navigation(current_path, *, section=None):
    record = page_record(current_path)
    section=record['section'] if section is None else section
    return '<nav aria-label="Primary">' + ''.join(
        f'<a href="{escape(relative_url(path, current_path), quote=True)}"'
        + (' aria-current="page"' if path == current_path else ' aria-current="true"' if section == label else '')
        + f'>{label}</a>' for path, label in PRIMARY) + '</nav>'

def breadcrumbs(current_path):
    trail, seen = [], set()
    path = current_path
    while path is not None:
        require(path not in seen, "Display parent cycle")
        seen.add(path)
        row = page_record(path)
        trail.append(row)
        path = row['parent_id']
    return '<nav aria-label="Breadcrumb"><ol>' + ''.join(
        '<li>' + (f'<span aria-current="page">{escape(row["title"])}</span>' if row['path'] == current_path
                  else f'<a href="{escape(relative_url(row["path"], current_path), quote=True)}">{escape(row["title"])}</a>') + '</li>'
        for row in reversed(trail)) + '</ol></nav>'

def _view(path, label, current_path, context=None):
    if path is None:
        require(context in ('result','files'), "Unknown dynamic navigation placeholder")
        return f'<a hidden data-context-link="{context}" aria-disabled="true">{escape(label)}</a>'
    attrs = f' data-context-link="{context}" data-base-href="{escape(relative_url(path.split("?")[0].split("#")[0], current_path), quote=True)}"' if context else ''
    href = escape(relative_url(path, current_path), quote=True)
    current = path == current_path or '#' not in path and path.split('?')[0] == current_path
    view_id = context or (path.split('#',1)[1] if '#' in path else path.rsplit('/',1)[-1].replace('.html',''))
    return f'<a{attrs} data-view-id="{escape(view_id,quote=True)}" href="{href}"' + (' aria-current="page"' if current else '') + f'>{escape(label)}</a>'

def dataset_navigation(dataset, current_path, model=None, model_label=None):
    require(dataset in DATASETS, "Unknown saved dataset")
    if dataset == 'teaching':
        return ''
    if model is not None and dataset == 'tenk':
        case_result_path(model)
    description, home = DATASETS[dataset]
    views = [(home, "Detector cases" if dataset == 'tenk' else "Campaign summary", None)] if dataset in ('tenk', 'million') else []
    if dataset == 'tenk':
        dynamic = current_path in ('spectra/cs137-10k.html','viewers/events.html','results/cs137-10k/spectra.html','results/cs137-10k/events.html')
        if model or dynamic:
            views.append((case_result_path(model) if model else None, "Charge & readout", 'result'))
        views.extend(((spectrum_path(model), "Stage spectra", 'spectrum'),
                      (event_view_path(model), "3D radiation events", 'events')))
        if model or dynamic:
            views.append((case_result_path(model) + '#data-files' if model else None, "Data & settings", 'files'))
    elif dataset == 'million':
        views.extend((("results/cs137-1m/spectra/deposition.html", "Deposition spectra", 'truth'),
                      ("results/cs137-1m/spectra/response.html", "Response spectra", 'response'),
                      (home + '#data-files', "Data & settings", 'files')))
    elif dataset == 'gamma':
        views.append((home, "Waveforms & event ledger", None))
    elif dataset == 'gegi':
        views.extend(((home,'Study overview',None),
                      (home+'#new-map','Conditional image · 434 groups',None),
                      (home+'#spectra','Historical spectra · 708 groups',None),
                      (home+'#journey','Saved signal example',None),
                      (home+'#accounting','Data & settings',None)))
    focus = ('Focused case: ' + (model_label or model)) if model and dataset == 'tenk' else 'All four cases' if dataset == 'tenk' else description
    study={'tenk':'cs137-10k','million':'cs137-1m','teaching':'cs137-10k-selected-signals','gamma':'gamma-native','gegi':'gegi-campaign'}[dataset]
    return (f'<section class="dataset-context" aria-label="Saved dataset" data-study="{study}" data-dataset="{dataset}" data-model="{escape(model or "", quote=True)}">'
            f'<p><strong>{escape(description)}</strong></p>'
            + (f'<p data-context-label>{escape(focus)}</p>' if dataset == 'tenk' else '')
            + '<nav aria-label="Dataset views">' + ''.join(_view(path, label, current_path, key) for path, label, key in views) + '</nav></section>')

def detector_navigation(current_path):
    model = current_path.split('/')[1]
    return '<nav aria-label="Detector views">' + ''.join(
        _view(f'detectors/{model}/{name}', label, current_path) for name, label in DETECTOR_VIEWS) + '</nav>'

def page_navigation(path, dataset=None, model=None, model_label=None):
    source_path = next((old for old,new in CANONICAL_VIEWS.items() if new==path),path)
    if dataset is None:
        dataset = {'spectra/pipeline.html':'teaching', 'examples/gamma-native/gamma.html':'gamma',
                   'spectra/cs137-10k.html':'tenk', 'viewers/events.html':'tenk',
                   'spectra/million-truth.html':'million', 'spectra/million-response.html':'million',
                   'results/cs137-1m/index.html':'million'}.get(source_path)
        if path=='results/gegi-campaign/index.html':dataset='gegi'
    if path.startswith('results/cs137-10k/') and path.endswith('/charge-readout.html'):
        dataset, model = 'tenk', path.split('/')[2]
    local = dataset_navigation(dataset, path, model, model_label) if dataset else detector_navigation(path) if re.fullmatch(r'detectors/[^/]+/[^/]+\.html', path) else ''
    heading = ('<div class="site-heading"><a class="site-brand" href="'+relative_url('index.html',path)+'">GeSignal</a>'
               +primary_navigation(path)+'<a class="source-link" href="https://github.com/Kunming-CN/END2END_Ge_Simulation">Source</a></div>')
    return ('<!-- page-navigation:start --><div id="page-navigation"><style id="site-navigation-style">' + NAV_STYLE + '</style>' + heading
            + breadcrumbs(path) + local + '</div>'+NAV_SCRIPT+'<!-- page-navigation:end -->')


def assembly_navigation(path):
    """The shared viewer's geometry-only mode belongs to Assemblies."""
    trail='<nav aria-label="Breadcrumb"><ol>'+''.join(
        '<li><a href="'+escape(relative_url(target,path),quote=True)+'">'+label+'</a></li>'
        for target,label in (('index.html','GeSignal'),('assemblies/index.html','Assemblies'))
    )+'<li><span aria-current="page">LBNL cryostat geometry</span></li></ol></nav>'
    return ('<div id="page-navigation"><style id="site-navigation-style">'+NAV_STYLE+'</style>'
            +primary_navigation(path,section='Assemblies')+trail+'</div>')

def footer(current_path):
    return ('<footer><a href="https://github.com/Kunming-CN/END2END_Ge_Simulation">GitHub</a> · '
            '<a href="https://github.com/Kunming-CN/END2END_Ge_Simulation/blob/main/CONTRIBUTING.md">Contributing</a> · '
            f'<a href="{escape(relative_url("LICENSE", current_path), quote=True)}">MIT software license</a> · '
            '<a href="https://github.com/Kunming-CN/END2END_Ge_Simulation/blob/main/THIRD_PARTY_NOTICES.md">Third-party and data rights</a></footer>')


def legacy_results_links(site):
    """Preserve deep links to specific evidence while the old report becomes a directory."""
    from gegi_digital_display import GEGI_SECTION_TARGETS
    path = Path(site) / 'results/index.html'
    if not path.is_file():
        return
    html = path.read_text(encoding='utf-8')
    html = re.sub(r'<!-- legacy-results:start -->.*?<!-- legacy-results:end -->', '', html, flags=re.S)
    targets = dict(GEGI_SECTION_TARGETS)
    targets.setdefault('gegi', 'results/gegi-shared-readout/index.html')
    # These were group headings, not independent scientific samples.
    targets.setdefault('earlier-gegi-work', 'results/index.html#historical-studies')
    links = []
    for anchor, target in sorted(targets.items()):
        if re.search(r'\bid=["\x27]' + re.escape(anchor) + r'["\x27]', html):
            continue
        href = relative_url(target, 'results/index.html')
        title = page_record(target.split('#')[0])['title']
        links.append(f'<li id="{escape(anchor)}"><a href="{escape(href,quote=True)}">{escape(title)} · {escape(anchor)}</a></li>')
    mapping = {key: relative_url(value, 'results/index.html') for key,value in targets.items()}
    block = ('<!-- legacy-results:start --><details class="legacy-links"><summary>Earlier bookmarked sections</summary><ul>'
             + ''.join(links) + '</ul></details><script data-legacy-results>'
             + '(()=>{const routes='+json.dumps(mapping,sort_keys=True)+';function follow(){const key=decodeURIComponent(location.hash.slice(1));'
             + 'const target=routes[key];if(target){const next=new URL(target,location.href);next.search=location.search;'
             + 'if(next.href!==location.href)location.replace(next.href);}}addEventListener("hashchange",follow);follow();})();</script>'
             + '<!-- legacy-results:end -->')
    html = html.replace('</main>', block+'</main>',1)
    path.write_text(html,encoding='utf-8',newline='\n')
