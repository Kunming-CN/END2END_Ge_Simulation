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


def validate(site, require_manifest=True):
    """Check the complete snapshot and return its deterministic file inventory."""
    site = Path(site).resolve()
    if not (site / 'index.html').is_file():
        raise ValueError(f'No index.html in {site}')
    entries, pages, total = [], {}, 0
    for f in sorted(site.rglob('*')):
        if f.is_symlink():
            raise ValueError(f'Symlink is not a publication input: {f}')
        if not f.is_file() or f.name == MANIFEST:
            continue
        relative = f.relative_to(site).as_posix()
        if f.name != '.nojekyll' and f.suffix.lower() not in EXTENSIONS:
            raise ValueError(f'Unapproved public file: {relative}')
        data = f.read_bytes()
        if len(data) >= 95 * 1024**2:
            raise ValueError(f'Oversize public file: {relative}')
        total += len(data)
        entries.append({'path': relative, 'bytes': len(data),
                        'sha256': hashlib.sha256(data).hexdigest()})
        if f.suffix.lower() in {'.html', '.json', '.md', '.svg', '.csv'}:
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
    """Verify the manifest, every HTML page, and representative media/data bytes."""
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
