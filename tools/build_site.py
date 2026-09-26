"""Export the existing library to a public, static site. No physics is rerun."""
import json, os, re, shutil, stat, sys, time
from html import escape
from html.parser import HTMLParser
import hashlib
from pathlib import Path
from urllib.parse import unquote, urlsplit
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_site import MANIFEST, validate
from pipeline_demo import validate_export as validate_pipeline_export
from lithium_report import validate_bundle as validate_lithium_bundle
from export_models import MODELS, ORIGINAL_HASHES, download_files, read_distribution
from render_contacts import (STYLE, SURFACE_NOTE, CATEGORY_NOTE, canonical_catalog,
                             contacts, contact_label, verify_applied_style)

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / 'Additional_Simulations' / 'Visualization_3D'
DESTINATION = ROOT / 'docs'
OUT = ROOT / '.local' / 'site-build'
ALLOWED = {'.html', '.png', '.jpg', '.svg', '.mp4', '.webm', '.csv', '.json', '.md'}
class Links(HTMLParser):
    def __init__(self):
        super().__init__(); self.links = []
    def handle_starttag(self, tag, attrs):
        for key, val in attrs:
            if key in ('href', 'src', 'poster') and val:
                u = urlsplit(val)
                if not u.scheme and not u.netloc and u.path:
                    self.links.append(unquote(u.path))
def scrub(s):
    # Public metadata preserves scientific values/hashes, not local machine paths.
    s = s.replace(str(ROOT).replace('\\', '\\\\'), '[project]')
    s = s.replace(str(ROOT), '[project]').replace(ROOT.as_posix(), '[project]')
    return re.sub(r'C:[\\/]+Users[^\n<>"`]*', '[external local input]', s)
def contact_legend(item):
    """Text labels keep the geometry color key usable without color perception."""
    rows = []
    for contact in contacts(item):
        style = STYLE['contact_%02d.vtp' % contact['id']]
        color = ','.join(str(round(value * 255)) for value in style['rgb'])
        swatch = f'<span aria-hidden="true" style="display:inline-block;width:1em;height:1em;background:rgb({color});border:1px solid #354354;margin-right:.4em"></span>'
        rows.append(f'<li>{swatch}{escape(style["color"])} — {escape(contact_label(contact))}</li>')
    detail = f'<p><a href="runs/20260922_suite_v3/01_geometry.png">Open full-size geometry (original scale)</a>. Small point contacts may be difficult to distinguish in thumbnails; use the full-size view and contact labels.</p>'
    return ('<section id="contact-legend"><h2>Geometry contact key</h2><ul>'
            + ''.join(rows) + '</ul><p>Grey-blue: translucent germanium bulk. '
            + CATEGORY_NOTE + ' Names and voltages come from the original model catalog.</p><p>'
            + SURFACE_NOTE + ' The original display-only scale of 1.001 and translation '
            'are retained to reduce coplanar flicker. This key applies to the geometry '
            'illustration; field and signal views retain their own legends.</p>' + detail + '</section>')


def adapt(s, rel, catalog=None):
    s = re.sub(r'<section id="gegi-supplement-link">.*?</section>', '', s, flags=re.S)
    s = re.sub(r'<details><summary>Find this folder in Windows</summary>.*?</details>', '', s, flags=re.S)
    s = re.sub(r'<section><h2>Open (?:any event|an event in ParaView)</h2>.*?</section>', '', s, flags=re.S)
    s = re.sub(r'<p>[^<]*(?:<[^>]+>[^<]*)*?</p>', lambda m: '<p>Desktop ParaView controls are available in the local project; this website shows exported results.</p>' if '.cmd' in m[0] else m[0], s)
    s = s.replace(' interactive events', ' event examples')
    s = s.replace('Interactive event library', 'Saved event examples')
    s = s.replace('href="README.md"', 'href="guide.html"')
    s = s.replace('rotatable geometry', 'exported geometry views')
    s = s.replace('Rotate the detector in ParaView', 'Desktop 3D scene preview')
    s = s.replace('</style>', '#copy{display:none!important}</style>', 1)
    if rel == Path('index.html'):
        note = '<section><h2>Simulation results online</h2><p>Browse 17 detector models, field images, drift movies and pulse comparisons. GeGI also has an interactive, time-resolved strip display. These are precomputed SSD results, not a live solver.</p><a class="button" href="detectors/GeGI_3D/strip_explorer.html">GeGI strip explorer</a><a class="button" href="detectors/GeGI_3D/supplement.html">GeGI supplementary study</a><a class="button" href="https://github.com/Kunming-CN/END2END_Ge_Simulation">Code and project progress</a><a class="button" href="https://github.com/Kunming-CN/END2END_Ge_Simulation/blob/main/simulation/README.md">Run the CPU quickstart</a></section>'
        s = s.replace('<main>', '<main>' + note, 1)
    elif rel == Path('detectors/GeGI_3D/index.html'):
        note = '<section><h2>GeGI supplementary study</h2><p>Earlier notebook results: electric fields, weighting potentials, charge/current, collection maps, charge sharing, depth and temperature studies. This is a separate saved study; its settings must not be assumed identical to every event below.</p><a class="button" href="supplement.html">Open supplementary results</a><a class="button" href="octagon_geometry.png">Octagon geometry illustration</a></section>'
        s = s.replace('<main>', '<main>' + note, 1)
    if rel == Path('index.html'):
        note = '<section><h2>Original SSD models</h2><p><a href="downloads/all-models.zip">Download all 17 original models with includes (ZIP)</a> | <a href="models/README.md">Model distribution guide</a></p><p>Geometry and semiconductor configurations; no numerical field caches or CAD/STL files.</p></section>'
        s = s.replace('<main>', '<main>' + note, 1)
        key = '<section><h2>Two-contact geometry colors</h2><p>Contact 1: orange-red; contact 2: cyan-blue; bulk: translucent grey-blue. Colors identify contact IDs, not doping signs. Contact surfaces do not show physical Li diffusion-layer thickness. GeGI retains its separate channel scheme.</p><p><a href="detectors/AK02/index.html#contact-legend">See the contact key and exact model voltages</a></p></section>'
        s = s.replace('<main>', '<main>' + key, 1)
    if len(rel.parts) == 3 and rel.parts[0] == 'detectors' and rel.name == 'index.html':
        detector = rel.parts[1]
        if detector not in ORIGINAL_HASHES:
            raise ValueError('Unknown detector model: ' + detector)
        note = f'<section><h2>Original SSD model configuration</h2><p><a href="../../models/{detector}.yaml">Exact original YAML</a> | <a href="../../downloads/{detector}.zip">Model ZIP with required includes and metadata</a> | <a href="../../models/catalog.json">Provenance and assumptions</a></p><p>Use the ZIP to keep required include paths intact. These are geometry and semiconductor inputs, not CAD/STL files or numerical field caches. Candidate and reference limitations remain unchanged.</p></section>'
        s = s.replace('<main>', '<main>' + note, 1)
        if detector != 'GeGI_3D':
            catalog = canonical_catalog() if catalog is None else catalog
            s = s.replace('<main>', '<main>' + contact_legend(catalog[detector]), 1)
    if rel == Path('index.html'):
        flow = '<section id="pipeline-example"><h2>From a photon to an ADC result</h2><p>Explore the complete AK02/SAP22 engineering example: energy deposits, electrode charge, current, preamplifier, analog shaping and peak ADC. Every primary and unresolved charge flag remains visible.</p><a class="button" href="examples/pipeline.html">Open the end-to-end example</a><p>Small precomputed sample; synthetic electronics, not a calibrated experimental prediction.</p></section>'
        s = s.replace('<main>', '<main>' + flow, 1)
    elif rel in (Path('detectors/AK02/index.html'), Path('detectors/SAP22/index.html')):
        flow = '<section><h2>Radiation-to-readout example</h2><p><a href="../../examples/pipeline.html">Inspect deposits, charge, preamp, shaping and peak ADC event by event</a>. The engineering example is separate from this earlier saved gallery; original temperatures and settings are retained.</p></section>'
        s = s.replace('<main>', '<main>' + flow, 1)
    if rel == Path("index.html"):
        s = s.replace("<main>", '<main><section><h2>Lithium-region diagnostics</h2><p><a href="lithium/lithium.html">Inspect native diffusion, endpoint signals and grid sensitivity</a>. These diagnostic curves are not calibrated Li collection efficiency; the transition remains grid-sensitive.</p></section>', 1)
    elif rel in (Path("detectors/AK02/index.html"), Path("detectors/SAP22/index.html")):
        s = s.replace("<main>", '<main><section><h2>Charge collection diagnostics</h2><p><a href="../../lithium/lithium.html">Compare geometric contacts, remaining induced signal and Li diffusion</a>.</p></section>', 1)
    if rel == Path("index.html"):
        s = s.replace("<main>", '<main><section><h2>Native lithium response through electronics</h2><p><a href="examples/native-li/comparison.html">Compare four original events with native SSD diffusion, preamp, shaping and ADC</a>. Provisional selected-event demonstration; failed accuracy gates and readout restrictions remain visible.</p></section>', 1)
    return scrub(s)
class NotebookCleaner(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False); self.out = []; self.stack = []; self.skip = 0
    def handle_starttag(self, tag, attrs):
        classes = dict(attrs).get('class', '')
        omit = tag == 'div' and ('jp-CodeMirrorEditor' in classes or 'jp-InputPrompt' in classes or 'jp-OutputPrompt' in classes)
        if tag == 'div':
            self.stack.append(omit)
            if omit: self.skip += 1
        if not self.skip: self.out.append(self.get_starttag_text())
    def handle_endtag(self, tag):
        if not self.skip: self.out.append('</' + tag + '>')
        if tag == 'div' and self.stack:
            if self.stack.pop(): self.skip -= 1
    def handle_data(self, data):
        if not self.skip: self.out.append(data)
    def handle_entityref(self, name):
        if not self.skip: self.out.append('&' + name + ';')
    def handle_charref(self, name):
        if not self.skip: self.out.append('&#' + name + ';')
def native_example_files():
    """Publish completed native-SDK output only; never run calculations here."""
    directory = ROOT / '.local' / 'native-li-example'
    report = json.loads((directory / 'report.json').read_text(encoding='utf-8'))
    if report['status'] != 'completed_provisional_native_example' or report['selected_event_ids'] != [0, 2, 41, 78]:
        raise ValueError('Native example incomplete or selection changed')
    if len(report['cases']) != 14 or report['source_primary_count'] != 100:
        raise ValueError('Native example case census mismatch')
    if report['unprocessed_event_ids'] != [i for i in range(100) if i not in (0, 2, 41, 78)]:
        raise ValueError('Native example omitted-event record mismatch')
    expected_sources = {'run.jl', 'replay.jl', 'readout.jl', 'native_li_example.jl', 'test_native_li_example.jl', 'readout_demo.json'}
    if set(report['source_code_sha256']) != expected_sources:
        raise ValueError('Native example source inventory mismatch')
    for name, expected in report['source_code_sha256'].items():
        if Path(name).name != name or hashlib.sha256((ROOT / 'simulation' / name).read_bytes()).hexdigest() != expected:
            raise ValueError('Native example source changed: ' + name)
    names = ('comparison.html', 'report.json', 'summary.csv', 'signals.csv')
    for name in names:
        f = directory / name
        if f.is_symlink() or not f.is_file():
            raise ValueError('Unsafe/missing native example output: ' + name)
        if name != 'report.json' and hashlib.sha256(f.read_bytes()).hexdigest() != report['artifacts'][name]:
            raise ValueError('Native example output changed: ' + name)
    return directory, names


def build_export():
    verify_applied_style(ROOT)
    OUT.mkdir(exist_ok=True)
    distribution = read_distribution(MODELS)
    model_outputs = download_files(distribution)
    catalog = {item['id']: item for item in json.loads(distribution['catalog.json'])['detectors']}
    for name, data in model_outputs.items():
        target = OUT / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    supplemental = OUT / 'detectors' / 'GeGI_3D'
    supplemental.mkdir(parents=True, exist_ok=True)
    source = ROOT / '2D_GeGI detector Simulation'
    c = NotebookCleaner(); c.feed((source / 'GeGI_3D.html').read_text(encoding='utf-8'))
    nb = scrub(''.join(c.out))
    banner = '<nav style="padding:20px;background:#e8f2fc"><a href="index.html">Back to GeGI results</a> | Supplementary saved notebook; not a live simulation. Original code inputs are omitted. Parameters belong to this earlier study.</nav>'
    nb = re.sub(r'(<body[^>]*>)', r'\1' + banner, nb, count=1)
    (supplemental / 'supplement.html').write_text(nb, encoding='utf-8')
    shutil.copy2(source / 'GeGI_dimension_schematics' / 'corrected_octagon_geometry_3.png', supplemental / 'octagon_geometry.png')
    shutil.copyfile(ROOT / 'tools' / 'site_guide.html', OUT / 'guide.html')
    # Presentation-only import of a completed, internally validated offline bundle.
    pipeline_source = ROOT / '.local' / 'pipeline-showcase'
    validate_pipeline_export(pipeline_source)
    (OUT / 'examples').mkdir(exist_ok=True)
    for name in ('pipeline.html', 'data.json'):
        shutil.copyfile(pipeline_source / name, OUT / 'examples' / name)
    native_dir, native_names = native_example_files()
    (OUT / "examples" / "native-li").mkdir(exist_ok=True)
    for name in native_names:
        shutil.copyfile(native_dir / name, OUT / "examples" / "native-li" / name)
    lithium_source = ROOT / ".local" / "lithium-report"
    lithium_data = validate_lithium_bundle(lithium_source)
    lithium_files = ("lithium.html", "summary.json", "endpoint-audit.csv", "depth-scan.csv", "profiles.csv")
    if "transition_grid" in lithium_data:
        lithium_files += ("transition-profiles.csv", "transition-comparisons.csv")
    if "axis_attribution" in lithium_data:
        lithium_files += ("axes-profiles.csv", "axes-comparisons.csv")
    (OUT / "lithium").mkdir(exist_ok=True)
    for name in lithium_files:
        shutil.copyfile(lithium_source / name, OUT / "lithium" / name)
    queue, done, missing = [Path('index.html')], {Path(name) for name in model_outputs}, []
    special = {Path('guide.html'), Path('detectors/GeGI_3D/supplement.html'), Path('detectors/GeGI_3D/octagon_geometry.png')}
    special.update({Path('examples/pipeline.html'), Path('examples/data.json')})
    done.update({Path('examples/pipeline.html'), Path('examples/data.json')})
    native_paths = {Path("examples/native-li") / name for name in native_names}
    special.update(native_paths); done.update(native_paths)
    special.update(Path("lithium") / name for name in lithium_files)
    done.update(Path("lithium") / name for name in lithium_files)
    while queue:
        rel = queue.pop()
        if rel in done: continue
        done.add(rel)
        f = (LIB / rel).resolve(); dest = OUT / rel
        if rel in special: continue
        if not f.is_relative_to(LIB) or f.suffix.lower() not in ALLOWED:
            raise RuntimeError('Unapproved publication path: ' + str(rel))
        if not f.is_file(): missing.append(str(rel)); continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        if f.suffix == '.html':
            s = adapt(f.read_text(encoding='utf-8'), rel, catalog)
            dest.write_text(s, encoding='utf-8')
            parser = Links(); parser.feed(s)
            for link in parser.links:
                absolute = (dest.parent / link).resolve()
                if not absolute.is_relative_to(OUT): raise RuntimeError('Link escapes site: ' + link)
                queue.append(absolute.relative_to(OUT))
        elif f.suffix == '.json':
            def clean(v):
                if isinstance(v, dict): return {k: clean(x) for k, x in v.items()}
                if isinstance(v, list): return [clean(x) for x in v]
                return scrub(v) if isinstance(v, str) else v
            dest.write_text(json.dumps(clean(json.loads(f.read_text(encoding='utf-8'))), indent=2), encoding='utf-8')
        elif f.suffix == '.md':
            dest.write_text(scrub(f.read_text(encoding='utf-8')), encoding='utf-8')
        else:
            shutil.copy2(f, dest)
    if missing: raise RuntimeError('Missing linked files: ' + repr(missing))
    (OUT / '.nojekyll').touch()
    published = [f for f in OUT.rglob('*') if f.is_file()]
    unexpected = [str(f.relative_to(OUT)) for f in published if f.relative_to(OUT) not in done and f.name != '.nojekyll']
    if unexpected: raise RuntimeError('Stale/untracked site outputs; inspect before publication: ' + repr(unexpected))
    for f in published:
        if f.stat().st_size >= 95 * 1024**2: raise RuntimeError('File too large for normal Git: ' + str(f))
    report = {'files': len(published), 'bytes': sum(f.stat().st_size for f in published),
              'detectors': len(json.loads((LIB / 'catalog.json').read_text())['detectors']),
              'source': 'Existing precomputed library; no numerical simulation rerun',
              'excluded': ['raw caches', 'ParaView states', 'logs', 'manual PDFs', 'photographs', 'slides']}
    (ROOT / '.local' / 'site-build.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2), flush=True)


def remove_generated(folder):
    """Clean generated files, handling Drive read-only attributes, never ACLs."""
    if folder not in (OUT, ROOT / '.local' / 'site-previous') or folder.is_symlink():
        raise RuntimeError('Refusing to clean an unexpected folder')
    def readonly_retry(function, target, error):
        target = Path(target)
        if target.is_symlink() or not target.resolve().is_relative_to(folder.resolve()):
            raise error[1]
        if not isinstance(error[1], PermissionError):
            raise error[1]
        # Windows read-only attributes on our generated directory are not ACLs.
        os.chmod(target, stat.S_IREAD | stat.S_IWRITE)
        function(target)

    for attempt in range(8):
        if not folder.exists():
            return
        try:
            shutil.rmtree(folder, onerror=readonly_retry)
            return
        except PermissionError:
            if attempt == 7:
                raise
            time.sleep(0.5 * (attempt + 1))


def rename_generated(source, destination):
    """Retry temporary Drive/open-handle locks during the validated swap."""
    allowed = {OUT, DESTINATION, ROOT / '.local' / 'site-previous'}
    if source not in allowed or destination not in allowed:
        raise RuntimeError('Unexpected publication move')
    for attempt in range(12):
        try:
            source.rename(destination)
            return
        except PermissionError:
            if attempt == 11:
                raise
            time.sleep(min(0.5 * (attempt + 1), 2.0))



def build_campaign_export(campaign):
    """Add saved results to a checked snapshot; preserve historical gallery bytes."""
    from native_publication import assemble, validate_bundle
    validate(DESTINATION)
    shutil.copytree(DESTINATION, OUT)
    (OUT / MANIFEST).unlink()
    target = OUT / 'examples' / 'cs137-10k'
    if target.exists():
        validate_bundle(target)
        shutil.rmtree(target)
    assemble(campaign, target)
    for page, href in (('index.html','examples/cs137-10k/comparison.html'),
                       ('detectors/AK02/index.html','../../examples/cs137-10k/comparison.html'),
                       ('detectors/SAP22/index.html','../../examples/cs137-10k/comparison.html')):
        file = OUT/page
        text = file.read_text(encoding='utf-8')
        text = re.sub(r'<section id="native-cs137-10k">.*?</section>', '', text, flags=re.S)
        if text.count('<main>') != 1:
            raise ValueError('Unexpected saved page structure: '+page)
        section = ('<section id="native-cs137-10k"><h2>Cs137: 10,000 initial decays per detector</h2>'
                   '<p>Saved AK02/SAP22 cryostat-to-native-charge-to-peak-ADC engineering run. '
                   'All events retained; two native failures and trajectory-limit flags remain visible. '
                   'Nominal geometry and synthetic electronics, not an experimental calibration.</p>'
                   '<a class="button" href="'+href+'">Open 10k comparison, traces and complete response ledgers</a></section>')
        file.write_text(text.replace('<main>', '<main>'+section, 1), encoding='utf-8', newline='\n')

def normalize_text_outputs(folder):
    # Historical receipts and all native-bundle bytes are already hash-bound.
    for output in folder.rglob('*'):
        if output.relative_to(folder).parts[:2] == ('examples', 'cs137-10k'):
            continue
        if output.is_file() and output.suffix in {'.html', '.json', '.md', '.svg'}:
            data = output.read_bytes()
            normalized = data.replace(b'\r\n', b'\n')
            if normalized != data: output.write_bytes(normalized)


def build(campaign=None):
    """Validate in staging, then replace only the generated publication folder."""
    local = ROOT / '.local'
    local.mkdir(exist_ok=True)
    previous = local / 'site-previous'
    if previous.exists():
        # Only discard the old generated copy when the installed snapshot is valid.
        validate(DESTINATION)
        remove_generated(previous)
    if DESTINATION.is_symlink() or OUT.is_symlink():
        raise RuntimeError('Publication directories must not be symlinks.')
    old = None
    if (DESTINATION / MANIFEST).exists():
        # Protect unknown files and hand edits: fix the source instead of losing work.
        old = validate(DESTINATION)
    if OUT.exists():
        remove_generated(OUT)
    if campaign is None:
        build_export()
    else:
        build_campaign_export(campaign)
    normalize_text_outputs(OUT)
    report = validate(OUT, require_manifest=False, require_models=True)
    (OUT / MANIFEST).write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8', newline='\n')
    validate(OUT)
    if old and old['build_id'] == report['build_id']:
        shutil.rmtree(OUT)
        print('Unchanged snapshot; docs/ was not rewritten.', flush=True)
    else:
        moved = DESTINATION.exists()
        if moved:
            rename_generated(DESTINATION, previous)
        try:
            rename_generated(OUT, DESTINATION)
        except Exception:
            if moved:
                rename_generated(previous, DESTINATION)
            raise
        if moved:
            remove_generated(previous)
        print('Replaced docs/ with the validated snapshot.', flush=True)
    summary = {k: v for k, v in report.items() if k != 'files'}
    (local / 'site-build.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native-campaign', type=Path, help='Publish saved 10k results onto the validated existing snapshot; no legacy regeneration')
    build(parser.parse_args().native_campaign)
