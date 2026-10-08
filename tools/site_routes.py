"""Display identities and formal reading routes, independent of scientific inputs.

Keep existing URLs. Catalog models and publication records remain the science
authority; this module records page ownership and navigation only.
"""
import posixpath
import re
from html import escape
from pathlib import Path

PRIMARY = (("results/index.html", "Results"), ("detectors/index.html", "Detectors"),
           ("guide.html", "Run locally"), ("methods/index.html", "Methods"))
CASE_MODELS = ("AK02", "SAP22", "GeRC02", "KMRC01_candidate")
DATASETS = {
    "teaching": ("Selected Cs137 signals · four 10K cases", "spectra/pipeline.html"),
    "gamma": ("Cryostat gamma · nominal cryostat", "examples/gamma-native/gamma.html"),
    "tenk": ("Cs137 10K · four separate cryostat cases", "results/cs137-10k/index.html"),
    "million": ("Cs137 1M · two separate cryostat cases", "results/cs137-1m/index.html"),
}
FIXED = {
    "index.html": ("GeSignal", None, "Home", "home", "site_restructure"),
    "results/index.html": ("Results", "index.html", "Results", "hub", "site_restructure"),
    "detectors/index.html": ("Detectors", "index.html", "Detectors", "hub", "site_restructure"),
    "guide.html": ("Run locally", "index.html", "Run locally", "guide", "site_guide"),
    "methods/index.html": ("Methods", "index.html", "Methods", "hub", "site_restructure"),
    "learn/index.html": ("Pipeline", "methods/index.html", "Methods", "method", "site_restructure"),
    "scenarios/lbnl-cs137/index.html": ("Nominal LBNL cryostat", "methods/index.html", "Methods", "method", "site_restructure"),
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
DETECTOR_VIEWS = (("index.html", "Overview"), ("geometry.html", "Geometry"),
                  ("gallery.html", "Saved fields & signals"), ("technical.html", "Model & files"))
NAV_STYLE = '''body{overflow-wrap:anywhere}
@media(max-width:450px){.channels{grid-template-columns:repeat(3,minmax(0,1fr))}}
#page-navigation{width:100%;font:16px/1.5 system-ui;color:#173047;margin:12px 0}
#page-navigation [hidden]{display:none}
#page-navigation nav{display:flex;flex-wrap:wrap;gap:8px 14px;margin:10px 0}
#page-navigation a{color:#075e9b;text-decoration:none;padding:4px 0}
#page-navigation a[aria-current]{font-weight:700;text-decoration:underline;text-underline-offset:5px}
#page-navigation ol{display:flex;flex-wrap:wrap;list-style:none;gap:7px;margin:0;padding:0}
#page-navigation li+li:before{content:"›";padding-right:7px;color:#526575}
#page-navigation .dataset-context{padding:8px 0;border-top:1px solid #d7e0e7}
#page-navigation p{margin:5px 0;overflow-wrap:anywhere}#page-navigation a:focus-visible{outline:3px solid #f8ad30}
@media(max-width:600px){#page-navigation{font-size:14px}#page-navigation nav{gap:6px 12px}}'''

def require(ok, message):
    if not ok:
        raise ValueError(message)

def case_result_path(model):
    require(model in CASE_MODELS, "Unknown saved 10K case")
    return f"results/cs137-10k/{model}/charge-readout.html"

def event_view_path(model=None, view="positive"):
    require(view in ("positive", "assembly"), "Unknown event view")
    if model is None:
        return "viewers/events.html"
    require(model in CASE_MODELS, "Unknown saved 10K case")
    return f"viewers/events.html?model={model}&view={view}"

def spectrum_path(model=None):
    require(model is None or model in CASE_MODELS, "Unknown saved 10K case")
    return "spectra/cs137-10k.html" + (f"#tenk-{model}" if model else "")

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
        title, parent, section, role, owner = model + " · saved result", "results/cs137-10k/index.html", "Results", "case", "ring_site"
    elif re.fullmatch(r"detectors/[A-Za-z0-9_-]+/(index|geometry|gallery|technical|strip_explorer|supplement).html", path):
        _, model, name = path.split("/")
        titles = dict(DETECTOR_VIEWS)
        title = model if name == "index.html" else titles.get(name, "Saved strip study" if name == "strip_explorer.html" else "Historical supplemental study")
        parent = "detectors/index.html" if name == "index.html" else f"detectors/{model}/" + ("gallery.html" if name in ("strip_explorer.html", "supplement.html") else "index.html")
        section, role, owner = "Detectors", "detector" if name in titles else "study", "site_detector_pages"
    elif path.startswith("examples/") and path.endswith(".html"):
        if path.startswith("examples/native-li/"):
            parent, section = "methods/native-li.html", "Methods"
        elif path == "examples/pipeline.html":
            parent, section = "spectra/pipeline.html", "Results"
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
    return dict(page_id=path, path=path, title=title, parent_id=parent,
                section=section, role=role, owner=owner)

def registry(site):
    """All HTML, including disconnected archives and compatibility aliases."""
    site = Path(site)
    return {p.relative_to(site).as_posix(): page_record(p.relative_to(site).as_posix())
            for p in sorted(site.rglob("*.html"))}

def primary_navigation(current_path):
    record = page_record(current_path)
    return '<nav aria-label="Primary">' + ''.join(
        f'<a href="{escape(relative_url(path, current_path), quote=True)}"'
        + (' aria-current="page"' if path == current_path else ' aria-current="true"' if record['section'] == label else '')
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
    current = path.split('#')[0].split('?')[0] == current_path
    return f'<a{attrs} href="{href}"' + (' aria-current="page"' if current else '') + f'>{escape(label)}</a>'

def dataset_navigation(dataset, current_path, model=None, model_label=None):
    require(dataset in DATASETS, "Unknown saved dataset")
    if model is not None and dataset == 'tenk':
        case_result_path(model)
    description, home = DATASETS[dataset]
    views = [(home, "Detector cases" if dataset == 'tenk' else "Campaign summary", None)] if dataset in ('tenk', 'million') else []
    if dataset == 'tenk':
        dynamic = current_path in ('spectra/cs137-10k.html','viewers/events.html')
        if model or dynamic:
            views.append((case_result_path(model) if model else None, "Charge & readout", 'result'))
        views.extend(((spectrum_path(model), "Stage spectra", 'spectrum'),
                      (event_view_path(model), "3D radiation events", 'events')))
        if model or dynamic:
            views.append((case_result_path(model) + '#data-files' if model else None, "Data & settings", 'files'))
    elif dataset == 'million':
        views.extend((("spectra/million-truth.html", "Deposition spectra", None),
                      ("spectra/million-response.html", "Response spectra", None),
                      (home + '#data-files', "Data & settings", 'files')))
    elif dataset == 'teaching':
        views.append((home, "Six signal examples", None))
    elif dataset == 'gamma':
        views.append((home, "Waveforms & event ledger", None))
    focus = ('Focused case: ' + (model_label or model)) if model and dataset == 'tenk' else 'All four cases' if dataset == 'tenk' else description
    return (f'<section class="dataset-context" aria-label="Saved dataset" data-dataset="{dataset}" data-model="{escape(model or "", quote=True)}">'
            f'<p><strong>{escape(description)}</strong></p><p data-context-label>{escape(focus)}</p>'
            '<nav aria-label="Dataset views">' + ''.join(_view(path, label, current_path, key) for path, label, key in views) + '</nav></section>')

def detector_navigation(current_path):
    model = current_path.split('/')[1]
    return '<nav aria-label="Detector views">' + ''.join(
        _view(f'detectors/{model}/{name}', label, current_path) for name, label in DETECTOR_VIEWS) + '</nav>'

def page_navigation(path, dataset=None, model=None, model_label=None):
    if dataset is None:
        dataset = {'spectra/pipeline.html':'teaching', 'examples/gamma-native/gamma.html':'gamma',
                   'spectra/cs137-10k.html':'tenk', 'viewers/events.html':'tenk',
                   'spectra/million-truth.html':'million', 'spectra/million-response.html':'million',
                   'results/cs137-1m/index.html':'million'}.get(path)
    if path.startswith('results/cs137-10k/') and path.endswith('/charge-readout.html'):
        dataset, model = 'tenk', path.split('/')[2]
    local = dataset_navigation(dataset, path, model, model_label) if dataset else detector_navigation(path) if re.fullmatch(r'detectors/[^/]+/[^/]+\.html', path) else ''
    return ('<!-- page-navigation:start --><div id="page-navigation"><style id="site-navigation-style">' + NAV_STYLE + '</style>' + primary_navigation(path)
            + breadcrumbs(path) + local + '</div><!-- page-navigation:end -->')

def footer(current_path):
    return ('<footer><a href="https://github.com/Kunming-CN/END2END_Ge_Simulation">GitHub</a> · '
            '<a href="https://github.com/Kunming-CN/END2END_Ge_Simulation/blob/main/CONTRIBUTING.md">Contributing</a> · '
            f'<a href="{escape(relative_url("LICENSE", current_path), quote=True)}">MIT software license</a> · '
            '<a href="https://github.com/Kunming-CN/END2END_Ge_Simulation/blob/main/THIRD_PARTY_NOTICES.md">Third-party and data rights</a></footer>')
