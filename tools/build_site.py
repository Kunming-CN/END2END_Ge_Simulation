"""Export the existing library to a public, static site. No physics is rerun."""
import hashlib, html, json, re, shutil
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit
ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / 'Additional_Simulations' / 'Visualization_3D'
OUT = ROOT / 'docs'
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
def adapt(s, rel):
    s = re.sub(r'<section id="gegi-supplement-link">.*?</section>', '', s, flags=re.S)
    s = re.sub(r'<details><summary>Find this folder in Windows</summary>.*?</details>', '', s, flags=re.S)
    s = re.sub(r'<section><h2>Open (?:any event|an event in ParaView)</h2>.*?</section>', '', s, flags=re.S)
    s = re.sub(r'<p>[^<]*(?:<[^>]+>[^<]*)*?</p>', lambda m: '<p>Desktop ParaView controls are available in the local project; this website shows exported results.</p>' if '.cmd' in m[0] else m[0], s)
    s = s.replace(' interactive events', ' event examples')
    s = s.replace('rotatable geometry', 'exported geometry views')
    s = s.replace('Rotate the detector in ParaView', 'Desktop 3D scene preview')
    s = s.replace('</style>', '#copy{display:none!important}</style>', 1)
    if rel == Path('index.html'):
        note = '<section><h2>Simulation results online</h2><p>Browse 17 detector models, field images, drift movies and pulse comparisons. GeGI also has an interactive, time-resolved strip display. These are precomputed SSD results, not a live solver.</p><a class="button" href="detectors/GeGI_3D/strip_explorer.html">GeGI strip explorer</a><a class="button" href="detectors/GeGI_3D/supplement.html">GeGI supplementary study</a><a class="button" href="https://github.com/Kunming-CN/END2END_Ge_Simulation">Code and project progress</a></section>'
        s = s.replace('<main>', '<main>' + note, 1)
    elif rel == Path('detectors/GeGI_3D/index.html'):
        note = '<section><h2>GeGI supplementary study</h2><p>Earlier notebook results: electric fields, weighting potentials, charge/current, collection maps, charge sharing, depth and temperature studies. This is a separate saved study; its settings must not be assumed identical to every event below.</p><a class="button" href="supplement.html">Open supplementary results</a><a class="button" href="octagon_geometry.png">Octagon geometry illustration</a></section>'
        s = s.replace('<main>', '<main>' + note, 1)
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
def build():
    OUT.mkdir(exist_ok=True)
    supplemental = OUT / 'detectors' / 'GeGI_3D'
    supplemental.mkdir(parents=True, exist_ok=True)
    source = ROOT / '2D_GeGI detector Simulation'
    c = NotebookCleaner(); c.feed((source / 'GeGI_3D.html').read_text(encoding='utf-8'))
    nb = scrub(''.join(c.out))
    banner = '<nav style="padding:20px;background:#e8f2fc"><a href="index.html">Back to GeGI results</a> | Supplementary saved notebook; not a live simulation. Original code inputs are omitted. Parameters belong to this earlier study.</nav>'
    nb = re.sub(r'(<body[^>]*>)', r'\1' + banner, nb, count=1)
    (supplemental / 'supplement.html').write_text(nb, encoding='utf-8')
    shutil.copy2(source / 'GeGI_dimension_schematics' / 'corrected_octagon_geometry_3.png', supplemental / 'octagon_geometry.png')
    local_page = LIB / 'detectors' / 'GeGI_3D' / 'index.html'
    local_html = local_page.read_text(encoding='utf-8')
    if 'id="gegi-supplement-link"' not in local_html:
        link = '<section id="gegi-supplement-link"><h2>Supplementary GeGI results</h2><p>Saved fields, collection maps, charge sharing, depth and temperature studies.</p><a class="button" href="../../../../docs/detectors/GeGI_3D/supplement.html">Open supplementary study</a></section>'
        local_page.write_text(local_html.replace('<main>', '<main>' + link, 1), encoding='utf-8')
    queue, done, missing = [Path('index.html')], set(), []
    special = {Path('detectors/GeGI_3D/supplement.html'), Path('detectors/GeGI_3D/octagon_geometry.png')}
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
            s = adapt(f.read_text(encoding='utf-8'), rel)
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
if __name__ == '__main__': build()
