"""Validate a published snapshot without Julia, ParaView, or private source data.

Usage: python tools/check_site.py [--site docs] [--write-manifest]
Only Python 3.10+ standard-library modules are required.
"""
import argparse
import hashlib
import json
import posixpath
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit
from export_models import (MODELS, ORIGINAL_HASHES, download_files, public_text,
                           read_distribution, validate_archive)
from site_discovery import SITE_URL

MAX_PUBLIC_FILE_BYTES = 100 * 1024 * 1024
MAX_PUBLIC_SITE_BYTES = 1_000_000_000

MANIFEST = 'site-manifest.json'
NAVIGATION_PREDECESSOR_MANIFEST_SHA256 = '340d8865dfff0339a2e0e0dd086ad9f9a771925e883d0b26c62b82d3909bb1b9'
EXTENSIONS = {'.html', '.png', '.jpg', '.svg', '.mp4', '.webm', '.csv', '.json', '.md'}
PRIVATE_PATH = re.compile(r'[A-Za-z]:[\\/]+Users[\\/]|file:///|/home/[^/\s]+/', re.I)
CREDENTIAL = re.compile(r'BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY|gh[pousr]_[A-Za-z0-9]{25,}|sk-proj-[A-Za-z0-9_-]{25,}')

class Links(HTMLParser):
    """Collect static resources separately from page navigation and JS markers."""
    def __init__(self):
        super().__init__()
        self.urls = []
        self.references, self.anchors, self.dynamic = [], set(), []
        self.script_blocks = 0

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if values.get('id'):
            self.anchors.add(values['id'])
        if tag == 'a' and values.get('name'):
            self.anchors.add(values['name'])
        if tag == 'script':
            self.script_blocks += 1
        self.urls.extend(v for k, v in attrs if k in ('href', 'src', 'poster') and v)
        for attribute, value in attrs:
            if attribute in ('href', 'src', 'poster') and value:
                self.references.append(dict(tag=tag, attribute=attribute, url=value,
                                            download='download' in values,
                                            rel=values.get('rel', '')))
        markers = {k: v for k, v in attrs if k in ('data-context-link', 'data-base-href')}
        if markers or tag == 'a' and not values.get('href') and not values.get('name'):
            self.dynamic.append(dict(tag=tag, id=values.get('id'), markers=markers))


def resolve_reference(page, url):
    """Retain query/fragment while resolving project-absolute and relative URLs."""
    parsed = urlsplit(url)
    project = urlsplit(SITE_URL)
    absolute_internal = (parsed.scheme in ('https', 'http', '') and
                         bool(parsed.netloc) and
                         parsed.netloc.lower() == project.netloc.lower() and
                         (parsed.path.startswith(project.path) or parsed.path == project.path.rstrip('/')))
    if parsed.scheme in ('https', 'http', 'mailto', 'data', 'tel') or parsed.netloc:
        if not absolute_internal:
            return None
        value = unquote(parsed.path[len(project.path):])
        base = ''
    else:
        if parsed.scheme:
            raise ValueError(f'{page}: unsupported URL scheme: {parsed.scheme}')
        value = unquote(parsed.path)
        base = posixpath.dirname(page)
    if value.startswith('/') or '\\' in value:
        raise ValueError(f'{page}: nonportable URL: {url}')
    target = (posixpath.normpath(posixpath.join(base, value)) if value else
              'index.html' if absolute_internal else page)
    if target == '..' or target.startswith('../'):
        raise ValueError(f'{page}: URL escapes site: {url}')
    return dict(path=target, query=parsed.query, fragment=unquote(parsed.fragment),
                project_absolute=absolute_internal)


def reference_kind(reference, target):
    """Classify the action, rather than count every href as a page transition."""
    if reference['tag'] in ('link', 'meta', 'base'):
        return 'metadata'
    if reference['attribute'] in ('src', 'poster'):
        return 'media' if reference['tag'] in ('img', 'video', 'audio', 'source', 'iframe', 'embed', 'object') else 'other'
    if reference['tag'] in ('a', 'area'):
        if reference['download']:
            return 'download'
        path = target['path'] if target is not None else urlsplit(reference['url']).path
        if posixpath.basename(path) == 'LICENSE':
            return 'download'
        if not path or path.endswith('.html') or not posixpath.splitext(path)[1]:
            return 'page_navigation'
        if Path(path).suffix.lower() in {'.png', '.svg', '.jpg', '.jpeg', '.webp', '.mp4', '.webm'}:
            return 'media'
        return 'download'
    return 'other'

def local_target(page, url):
    """Resolve case-sensitive project-relative links; reject local/escaping URLs."""
    target = resolve_reference(page, url)
    return target['path'] if target is not None else None


def validate(site, require_manifest=True, require_models=False):
    """Check the complete snapshot and return its deterministic file inventory."""
    site = Path(site).resolve()
    if not (site / 'index.html').is_file():
        raise ValueError(f'No index.html in {site}')
    # Old snapshots remain valid for protected staging/rollback. Once present,
    # the complete model distribution and every download are mandatory.
    model_outputs = {}
    if require_models or (site / 'models').exists() or (site / 'downloads').exists():
        model_outputs = download_files(read_distribution(MODELS))
    entries, pages, total = [], {}, 0
    for f in sorted(site.rglob('*')):
        if f.is_symlink():
            raise ValueError(f'Symlink is not a publication input: {f}')
        if not f.is_file() or f.name == MANIFEST:
            continue
        relative = f.relative_to(site).as_posix()
        size = f.stat().st_size
        if size > MAX_PUBLIC_FILE_BYTES or total + size > MAX_PUBLIC_SITE_BYTES:
            raise ValueError(f'GitHub publication size limit exceeded: {relative}; use complete lossless archives')
        geometry_file = relative.startswith('examples/cs137-10k-geometry/') and f.suffix.lower() in {'.zip','.txt'}
        hit_payload = relative in ('examples/cs137-10k-hits/AK02/selected.json.gz','examples/cs137-10k-hits/SAP22/selected.json.gz')
        million_payload = relative=='examples/cs137-1m/positive-groups.csv.gz'
        native_response_payload = relative=='examples/cs137-1m-response/groups.csv.gz'
        ledger_zip = relative in ('examples/cs137-10k/AK02/response/ledgers.zip', 'examples/cs137-10k/SAP22/response/ledgers.zip')
        ring_payload = relative.startswith('examples/cs137-10k-rings/') and (f.suffix.lower() in {'.zip', '.gz', '.jsonl'} or relative == 'examples/cs137-10k-rings/README.txt')
        if f.name != '.nojekyll' and f.suffix.lower() not in EXTENSIONS and relative not in {'sitemap.xml', 'LICENSE'} and relative not in model_outputs and not ledger_zip and not geometry_file and not hit_payload and not million_payload and not native_response_payload and not ring_payload:
            raise ValueError(f'Unapproved public file: {relative}')
        data = f.read_bytes()
        if relative == 'LICENSE':
            from site_discovery import SOFTWARE_LICENSE
            if data != SOFTWARE_LICENSE.read_bytes():
                raise ValueError('Published software LICENSE differs from maintained source')
        if geometry_file and f.suffix.lower()=='.zip':
            from geometry_publication import archive_contents
            archive_contents(data)
        if ledger_zip:
            from native_publication import validate_ledger_archive
            validate_ledger_archive(data)
        if relative.startswith(('models/', 'downloads/')):
            if relative not in model_outputs or data != model_outputs[relative]:
                raise ValueError(f'Model download differs from versioned original: {relative}')
            if f.suffix == '.zip':
                # Compare exact bytes above, and independently check archive safety,
                # metadata privacy and complete included contents without extraction.
                import io
                import zipfile
                with zipfile.ZipFile(io.BytesIO(model_outputs[relative])) as archive:
                    expected = {name: archive.read(name) for name in archive.namelist()}
                validate_archive(data, expected)
            else:
                public_text(data, relative)
        if len(data) >= 95 * 1024**2:
            raise ValueError(f'Oversize public file: {relative}')
        total += len(data)
        entries.append({'path': relative, 'bytes': len(data),
                        'sha256': hashlib.sha256(data).hexdigest()})
        if relative == 'LICENSE' or f.suffix.lower() in {'.html', '.json', '.md', '.svg', '.csv', '.yaml', '.txt', '.xml'}:
            text = data.decode('utf-8-sig')
            if PRIVATE_PATH.search(text) or CREDENTIAL.search(text):
                raise ValueError(f'Local path or possible credential: {relative}')
            if f.suffix == '.json':
                json.loads(text)
            if f.suffix == '.html':
                parser = Links()
                parser.feed(text)
                pages[relative] = parser
    if total > MAX_PUBLIC_SITE_BYTES:
        raise ValueError('Site exceeded the GitHub Pages publication budget (1 GB).')
    names = {entry['path'] for entry in entries} | {MANIFEST}
    links = 0
    counts = dict(resource_references_checked=0, page_navigation_checked=0,
                  fragments_checked=0, downloads_checked=0,
                  media_references_checked=0, metadata_references_checked=0,
                  other_references_checked=0)
    fields = dict(page_navigation='page_navigation_checked', download='downloads_checked',
                  media='media_references_checked', metadata='metadata_references_checked',
                  other='other_references_checked')
    for page, parser in pages.items():
        for reference in parser.references:
            url = reference['url']
            resolved = resolve_reference(page, url)
            if resolved is None:
                continue
            target = resolved['path']
            old_url = urlsplit(url)
            # Retain the old manifest field's precise resource-reference census:
            # explicit relative href/src/poster with a nonempty path, no anchors.
            if not old_url.scheme and not old_url.netloc and old_url.path:
                links += 1
            counts['resource_references_checked'] += 1
            counts[fields[reference_kind(reference, resolved)]] += 1
            directory_target = posixpath.normpath(posixpath.join(target, 'index.html'))
            if target not in names and directory_target not in names:
                raise ValueError(f'Broken or wrong-case link: {page} -> {url}')
            if target not in names:
                target = directory_target
            fragment = resolved['fragment'].split(':~:text=', 1)[0]
            if fragment and target in pages:
                counts['fragments_checked'] += 1
                if fragment not in pages[target].anchors:
                    raise ValueError(f'Broken fragment: {page} -> {url}')
    if model_outputs:
        if set(model_outputs) - names:
            raise ValueError('Missing model downloads: ' + ', '.join(sorted(set(model_outputs) - names)))
        required_links = {'guide.html': {'downloads/all-models.zip'}}
        for detector in ORIGINAL_HASHES:
            required_links[f'detectors/{detector}/technical.html'] = {
                f'models/{detector}.yaml', f'downloads/{detector}.zip'}
        for page, required in required_links.items():
            targets = {local_target(page, url) for url in pages[page].urls} if page in pages else set()
            if not required <= targets:
                raise ValueError('Missing model download links: ' + page)
    native_bundle = site / 'examples' / 'cs137-10k'
    if native_bundle.exists():
        from native_publication import validate_bundle
        validate_bundle(native_bundle)
    geometry_bundle = site/'examples/cs137-10k-geometry'
    if geometry_bundle.exists():
        from geometry_publication import validate_bundle as validate_geometry
        validate_geometry(geometry_bundle)
    if (site/'examples/cs137-1m').exists():
        from million_publication import validate as validate_million
        validate_million(site/'examples/cs137-1m')
    if (site/'examples/cs137-1m-response').exists():
        from native_response_publication import validate as validate_native_response
        validate_native_response(site/'examples/cs137-1m-response')
    if (site/'examples/gamma-native').exists():
        from gamma_publication import validate_bundle as validate_gamma_showcase
        validate_gamma_showcase(site/'examples/gamma-native')
    if (site/'examples/pipeline-display.json').exists():
        from saved_focus_pages import validate as validate_teaching_focus
        validate_teaching_focus(site/'examples')
    if (site/'detectors/GeGI_3D/display/manifest.json').exists():
        from saved_plot_repairs import validate as validate_plot_repairs
        validate_plot_repairs(site)
    if (site/'methods/native-li.html').exists() or (site/'methods/native-li-display.json').exists():
        from saved_archive_display import validate as validate_archive_display
        validate_archive_display(site)
    if (site/'methods/lithium-display.json').exists():
        from saved_archive_display import validate_lithium_display
        validate_lithium_display(site)
    geometry_viewers=[site/'detectors'/m/'geometry.html' for m in ('AK02','SAP22')]
    if any(p.exists() for p in geometry_viewers):
        if not all(p.exists() for p in geometry_viewers): raise ValueError('Partial SSD geometry viewer publication')
        from ssd_geometry_publication import validate_site as validate_ssd_geometry
        validate_ssd_geometry(site)
    hit_bundle = site/'examples/cs137-10k-hits'
    if hit_bundle.exists():
        from hit_view_publication import validate as validate_hits
        validate_hits(hit_bundle)
    ring_bundle = site/'examples/cs137-10k-rings'
    if ring_bundle.exists():
        from ring_publication import validate_bundle as validate_rings
        validate_rings(ring_bundle)
    if (site/"spectra/manifest.json").exists():
        from spectrum_display import validate as validate_spectrum_display
        validate_spectrum_display(site)
    if any((site/p).exists() for p in ('viewers/manifest.json','viewers/events.html','viewers/geant4-assembly.html','viewers/ge-positive.html')):
        from viewer_navigation import validate as validate_readers
        validate_readers(site)
    entries.sort(key=lambda item: item['path'])
    encoded = json.dumps(entries, sort_keys=True, separators=(',', ':')).encode()
    from site_discovery import validate as validate_discovery
    validate_discovery(site, snapshot_build_id=hashlib.sha256(encoded).hexdigest())
    result = {'schema_version': 1, 'build_id': hashlib.sha256(encoded).hexdigest(),
              'file_count': len(entries), 'total_bytes': total,
              'html_pages': len(pages), 'local_links_checked': links,
              **counts,
              'files': entries}
    # total_bytes is the payload census; the hosting budget also includes the
    # manifest itself. Before sealing, budget its exact generated serialization.
    manifest_path = site / MANIFEST
    manifest_bytes = (manifest_path.stat().st_size if require_manifest and manifest_path.is_file()
                      else len((json.dumps(result, indent=2) + '\n').encode('utf-8')))
    if manifest_bytes > MAX_PUBLIC_FILE_BYTES or total + manifest_bytes > MAX_PUBLIC_SITE_BYTES:
        raise ValueError('GitHub publication size limit exceeded including the site manifest.')
    if require_manifest:
        saved_raw = (site / MANIFEST).read_bytes()
        saved = json.loads(saved_raw)
        if saved != result:
            # Only this byte-exact predecessor may retain the older counter
            # schema while protected staging validates it before rebuilding.
            from site_discovery import NAVIGATION_PREDECESSOR
            old_result = {key: value for key, value in result.items() if key not in counts}
            predecessor = (result['build_id'] == NAVIGATION_PREDECESSOR and
                           hashlib.sha256(saved_raw).hexdigest() == NAVIGATION_PREDECESSOR_MANIFEST_SHA256 and
                           saved == old_result)
            if not predecessor:
                raise ValueError('Snapshot differs from its manifest; rebuild from sources.')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site', type=Path, default=Path(__file__).resolve().parents[1] / 'docs')
    parser.add_argument('--write-manifest', action='store_true')
    parser.add_argument('--url', help='Also verify this exact snapshot on a public website')
    args = parser.parse_args()
    report = validate(args.site, require_manifest=not args.write_manifest)
    if args.write_manifest:
        (args.site / MANIFEST).write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8', newline='\n')
    if args.url:
        report['live_files_checked'] = verify_live(args.url, report)
    print(json.dumps({k: v for k, v in report.items() if k != 'files'}, indent=2))



def verify_live(url, report):
    """Verify HTML, every model/download artifact, and representative media/data."""
    from concurrent.futures import ThreadPoolExecutor
    from urllib.parse import quote
    from urllib.request import Request, urlopen
    # ParaView's bundled Python may omit SSL; reuse Node HTTPS without relaxing TLS.
    node = None
    try:
        import ssl
    except ImportError:
        import shutil
        node = shutil.which('node')
        if not node:
            raise RuntimeError('Live checks require Python with SSL or Node.js on PATH.')
    base = url.rstrip('/') + '/'
    if urlsplit(base).scheme not in ('http', 'https'):
        raise ValueError('Live verification requires an HTTP(S) website')

    def download(relative):
        target = base + quote(relative, safe='/') + '?build=' + report['build_id']
        if node:
            import subprocess
            script = "fetch(process.argv[1]).then(async r => {if (!r.ok) throw Error(String(r.status)); process.stdout.write(Buffer.from(await r.arrayBuffer()));}).catch(e => {console.error(e.message);process.exit(1);});"
            result = subprocess.run([node, '-e', script, target], capture_output=True, timeout=35, check=True)
            return result.stdout
        request = Request(target, headers={'User-Agent': 'SSD-site-verification/1.0'})
        with urlopen(request, timeout=30) as response:
            return response.read()

    remote = json.loads(download(MANIFEST))
    if remote != report:
        raise ValueError('The live manifest is not this local snapshot; deployment may still be pending.')
    entries = report['files']
    selected = {entry['path']: entry for entry in entries if entry['path'].endswith('.html')}
    selected.update({entry['path']: entry for entry in entries
                     if entry['path'] in {'sitemap.xml','LICENSE','methods/native-li-display.json'}})
    selected.update({entry['path']: entry for entry in entries
                     if entry['path'].startswith(('models/', 'downloads/'))})
    # The public campaign is an auditable dataset, not just HTML; verify every file.
    selected.update({entry['path']: entry for entry in entries
                     if entry['path'].startswith(('examples/cs137-10k/', 'examples/cs137-10k-geometry/', 'examples/cs137-10k-hits/', 'examples/cs137-10k-rings/', 'examples/cs137-1m/', 'examples/cs137-1m-response/', 'examples/gamma-native/'))})
    # Interactive geometry requires every scene, manifest and active pointer online.
    selected.update({entry['path']: entry for entry in entries
                     if entry['path'].startswith('detectors/') and
                     ('/geometry/' in entry['path'] or entry['path'].endswith('/geometry-active.json')
                      or entry['path']=='detectors/geometry-index.json')})
    selected.update({entry['path']:entry for entry in entries if entry['path'].startswith('spectra/')})
    selected.update({entry['path']:entry for entry in entries if entry['path'].startswith('viewers/')})
    selected.update({entry['path']:entry for entry in entries
                     if entry['path'].startswith('detectors/GeGI_3D/display/')})
    for suffix in ('.png', '.svg', '.csv', '.mp4', '.webm', '.json', '.md'):
        examples = [entry for entry in entries if entry['path'].endswith(suffix)]
        for entry in examples[:2] + examples[-1:]:
            selected[entry['path']] = entry

    def verify(entry):
        data = download(entry['path'])
        if len(data) != entry['bytes'] or hashlib.sha256(data).hexdigest() != entry['sha256']:
            raise ValueError('Live content differs: ' + entry['path'])
        return entry['path']

    with ThreadPoolExecutor(max_workers=4) as workers:
        checked = list(workers.map(verify, selected.values()))
    return len(checked)


if __name__ == '__main__':
    main()
