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

MANIFEST = 'site-manifest.json'
EXTENSIONS = {'.html', '.png', '.jpg', '.svg', '.mp4', '.webm', '.csv', '.json', '.md'}
PRIVATE_PATH = re.compile(r'[A-Za-z]:[\\/]+Users[\\/]|file:///|/home/[^/\s]+/', re.I)
CREDENTIAL = re.compile(r'BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY|gh[pousr]_[A-Za-z0-9]{25,}|sk-proj-[A-Za-z0-9_-]{25,}')

class Links(HTMLParser):
    """Collect explicit page, image, poster, and video resource references."""
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        self.urls.extend(v for k, v in attrs if k in ('href', 'src', 'poster') and v)

def local_target(page, url):
    """Resolve case-sensitive project-relative links; reject local/escaping URLs."""
    parsed = urlsplit(url)
    if parsed.scheme in ('https', 'http', 'mailto', 'data') or parsed.netloc:
        return None
    if parsed.scheme:
        raise ValueError(f'{page}: unsupported URL scheme: {parsed.scheme}')
    value = unquote(parsed.path)
    if not value:
        return None
    if value.startswith('/') or '\\' in value:
        raise ValueError(f'{page}: nonportable URL: {url}')
    result = posixpath.normpath(posixpath.join(posixpath.dirname(page), value))
    if result == '..' or result.startswith('../'):
        raise ValueError(f'{page}: URL escapes site: {url}')
    return result


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
        geometry_file = relative.startswith('examples/cs137-10k-geometry/') and f.suffix.lower() in {'.zip','.txt'}
        hit_payload = relative in ('examples/cs137-10k-hits/AK02/selected.json.gz','examples/cs137-10k-hits/SAP22/selected.json.gz')
        million_payload = relative=='examples/cs137-1m/positive-groups.csv.gz'
        native_response_payload = relative=='examples/cs137-1m-response/groups.csv.gz'
        ledger_zip = relative in ('examples/cs137-10k/AK02/response/ledgers.zip', 'examples/cs137-10k/SAP22/response/ledgers.zip')
        if f.name != '.nojekyll' and f.suffix.lower() not in EXTENSIONS and relative not in model_outputs and not ledger_zip and not geometry_file and not hit_payload and not million_payload and not native_response_payload:
            raise ValueError(f'Unapproved public file: {relative}')
        data = f.read_bytes()
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
        if f.suffix.lower() in {'.html', '.json', '.md', '.svg', '.csv', '.yaml', '.txt'}:
            text = data.decode('utf-8-sig')
            if PRIVATE_PATH.search(text) or CREDENTIAL.search(text):
                raise ValueError(f'Local path or possible credential: {relative}')
            if f.suffix == '.json':
                json.loads(text)
            if f.suffix == '.html':
                parser = Links()
                parser.feed(text)
                pages[relative] = parser.urls
    if total >= 800 * 1024**2:
        raise ValueError('Site exceeded the project publication budget (800 MiB).')
    names = {entry['path'] for entry in entries} | {MANIFEST}
    links = 0
    for page, urls in pages.items():
        for url in urls:
            target = local_target(page, url)
            if target is None:
                continue
            links += 1
            if target not in names and posixpath.join(target, 'index.html') not in names:
                raise ValueError(f'Broken or wrong-case link: {page} -> {url}')
    if model_outputs:
        if set(model_outputs) - names:
            raise ValueError('Missing model downloads: ' + ', '.join(sorted(set(model_outputs) - names)))
        required_links = {'index.html': {'downloads/all-models.zip'},
                          'guide.html': {'downloads/all-models.zip'}}
        for detector in ORIGINAL_HASHES:
            required_links[f'detectors/{detector}/index.html'] = {
                f'models/{detector}.yaml', f'downloads/{detector}.zip'}
        for page, required in required_links.items():
            targets = {local_target(page, url) for url in pages.get(page, [])}
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
        from gamma_showcase import validate_bundle as validate_gamma_showcase
        validate_gamma_showcase(site/'examples/gamma-native')
    geometry_viewers=[site/'detectors'/m/'geometry.html' for m in ('AK02','SAP22')]
    if any(p.exists() for p in geometry_viewers):
        if not all(p.exists() for p in geometry_viewers): raise ValueError('Partial SSD geometry viewer publication')
        from ssd_geometry_publication import validate_site as validate_ssd_geometry
        validate_ssd_geometry(site)
    hit_bundle = site/'examples/cs137-10k-hits'
    if hit_bundle.exists():
        from hit_view_publication import validate as validate_hits
        validate_hits(hit_bundle)
    if (site/"spectra/manifest.json").exists():
        from spectrum_display import validate as validate_spectrum_display
        validate_spectrum_display(site)
    if any((site/p).exists() for p in ('viewers/manifest.json','viewers/geant4-assembly.html','viewers/ge-positive.html')):
        from viewer_navigation import validate as validate_readers
        validate_readers(site)
    entries.sort(key=lambda item: item['path'])
    encoded = json.dumps(entries, sort_keys=True, separators=(',', ':')).encode()
    result = {'schema_version': 1, 'build_id': hashlib.sha256(encoded).hexdigest(),
              'file_count': len(entries), 'total_bytes': total,
              'html_pages': len(pages), 'local_links_checked': links,
              'files': entries}
    if require_manifest:
        saved = json.loads((site / MANIFEST).read_text(encoding='utf-8'))
        if saved != result:
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
                     if entry['path'].startswith(('models/', 'downloads/'))})
    # The public campaign is an auditable dataset, not just HTML; verify every file.
    selected.update({entry['path']: entry for entry in entries
                     if entry['path'].startswith(('examples/cs137-10k/', 'examples/cs137-10k-geometry/', 'examples/cs137-10k-hits/', 'examples/cs137-1m/', 'examples/cs137-1m-response/', 'examples/gamma-native/'))})
    # Interactive geometry requires every scene, manifest and active pointer online.
    selected.update({entry['path']: entry for entry in entries
                     if entry['path'].startswith('detectors/') and
                     ('/geometry/' in entry['path'] or entry['path'].endswith('/geometry-active.json')
                      or entry['path']=='detectors/geometry-index.json')})
    selected.update({entry['path']:entry for entry in entries if entry['path'].startswith('spectra/')})
    selected.update({entry['path']:entry for entry in entries if entry['path'].startswith('viewers/')})
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
