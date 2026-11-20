"""Final, reversible relocation of saved HTML views; scientific assets stay put.

Existing producers and their scientific validators operate on their exact legacy
HTML.  apply() runs after them.  prepare() restores that input on the next build;
validation_view() supplies it to validators without changing the published tree.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
import errno
import gzip
import hashlib
from html import escape, unescape
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import posixpath
import re
import shutil
import tempfile
from urllib.parse import parse_qsl, urlsplit

from site_routes import CANONICAL_VIEWS, page_navigation

ROOT = Path(__file__).resolve().parents[1]
STAGED_ROOT = ROOT / '.local/site-build'
RECEIPT = 'canonical-views.json'
KIND = 'saved_canonical_views_v1'
SOURCES = ('tools/site_canonical_views.py', 'tools/site_routes.py',
           'tools/site_chrome.py', 'tools/site_discovery.py')
VIEWER_ALIASES = {'viewers/ge-positive.html': 'positive',
                  'viewers/geant4-assembly.html': 'assembly'}
FRAMED_REPORTS = (
    'examples/cs137-10k/comparison.html',
    'examples/cs137-10k/AK02/response/summary.html',
    'examples/cs137-10k/SAP22/response/summary.html',
    'examples/cs137-10k-rings/GeRC02/response/summary.html',
    'examples/cs137-10k-rings/KMRC01_candidate/response/summary.html',
    'examples/cs137-10k-rings/KMRC01_candidate/response/original-native/summary.html',
    'examples/cs137-1m/report.html',
    'examples/cs137-1m-response/report.html',
    'examples/native-li/comparison.html',
)
FRAMED_PAGES = FRAMED_REPORTS + ('assemblies/gegi/index.html',)
NAV = re.compile(r'<!-- page-navigation:start -->.*?<!-- page-navigation:end -->', re.S)
SCRIPT = re.compile(r'(<script\b[^>]*>)(.*?)(</script\s*>)', re.I | re.S)
ATTR = re.compile(r'(?P<key>\b(?:href|src|poster|action|data-base-href))\s*=\s*(?P<quote>[\"\x27])(?P<url>.*?)(?P=quote)', re.I | re.S)
URL_STRING = re.compile(r'(?P<quote>[\"\x27`])(?P<url>(?:\.\.?/[^\"\x27`\s<>]*|[A-Za-z0-9_./-]+\.html(?:[?#][^\"\x27`\s<>]*)?))(?P=quote)')
FETCH_STRING = re.compile(r'(?P<prefix>\bfetch\(\s*)(?P<quote>[\"\x27])(?P<url>[A-Za-z0-9_./-]+\.(?:json|csv|gz|bin)(?:[?#][^\"\x27\s<>]*)?)(?P=quote)')
CSS_URL = re.compile(r'url\(\s*(?P<quote>[\"\x27]?)(?P<url>[^)\"\x27\s]+)(?P=quote)\s*\)')


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def sources():
    return {name: digest((ROOT / name).read_bytes()) for name in SOURCES}


def local_path(site, name):
    require(isinstance(name, str) and name and '\\' not in name and
            not name.startswith('/') and '..' not in name.split('/'),
            'Invalid canonical view path: ' + str(name))
    path = Path(site) / name
    require(not path.is_symlink(), 'Linked canonical view: ' + name)
    return path


def rebase_url(value, old, new, *, canonical=True):
    """Resolve the old relative URL, then express it from the new HTML location."""
    if not value or value.startswith(('#', '?', '/', '//')):
        return value
    url = urlsplit(value)
    if url.scheme or url.netloc or not url.path:
        return value
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(old), url.path))
    # Prefix strings such as '../' are used by the teaching controller before
    # adding a saved source folder. Keep their trailing slash after relocation.
    trailing = url.path.endswith('/')
    target = CANONICAL_VIEWS.get(resolved, resolved) if canonical else resolved
    query = url.query
    if canonical and resolved in VIEWER_ALIASES:
        target = CANONICAL_VIEWS['viewers/events.html']
        if not any(key == 'view' for key, _ in parse_qsl(query, keep_blank_values=True)):
            query += ('&' if query else '') + 'view=' + VIEWER_ALIASES[resolved]
    path = posixpath.relpath(target, posixpath.dirname(new))
    if trailing and not path.endswith('/'):
        path += '/'
    # urlunsplit drops an empty '?' delimiter, which is significant in a JS
    # prefix immediately followed by a saved-selection query string.
    return (path + ('?' + query if query or '?' in value.split('#', 1)[0] else '')
            + ('#' + url.fragment if '#' in value else ''))


def direct_url(value, path):
    """Change only links to compatibility addresses, retaining saved selections."""
    if not value or value.startswith(('#', '?', '/', '//')):
        return value
    url = urlsplit(value)
    if url.scheme or url.netloc or not url.path:
        return value
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(path), url.path))
    if resolved not in CANONICAL_VIEWS and resolved not in VIEWER_ALIASES:
        return value
    return rebase_url(value, path, path)


def direct_links_html(raw, path):
    """Rewrite display destinations without modifying embedded scientific JSON."""
    def markup(text):
        def attr(match):
            href = direct_url(unescape(match['url']), path)
            if href == unescape(match['url']):
                return match[0]
            return match['key'] + '=' + match['quote'] + escape(href, quote=True) + match['quote']
        return ATTR.sub(attr, text)
    text = raw.decode('utf-8')
    parts, cursor = [], 0
    for match in SCRIPT.finditer(text):
        parts.append(markup(text[cursor:match.start()]))
        opening, body, closing = match.groups()
        if not re.search(r'type\s*=\s*[\"\x27]application/(?:ld\+)?json[\"\x27]', opening, re.I):
            body = URL_STRING.sub(lambda m: m['quote'] + direct_url(m['url'], path) + m['quote'], body)
        parts.append(markup(opening) + body + closing)
        cursor = match.end()
    parts.append(markup(text[cursor:]))
    return ''.join(parts).encode('utf-8')


def linked_html(raw, path):
    output = direct_links_html(raw, path)
    if output != raw:
        # Discovery runs after canonical relocation. Pin its deterministic
        # landing metadata now so that it cannot invalidate a links-only page.
        from site_discovery import LANDINGS, landing_metadata_html
        if path in LANDINGS:
            output = landing_metadata_html(output.decode('utf-8'), path, LANDINGS[path]).encode('utf-8')
    return output


def rebase_markup(text, old, new):
    def attr(match):
        href = rebase_url(unescape(match['url']), old, new)
        return match['key'] + '=' + match['quote'] + escape(href, quote=True) + match['quote']
    text = ATTR.sub(attr, text)
    return CSS_URL.sub(lambda m: 'url(' + m['quote'] + rebase_url(m['url'], old, new) + m['quote'] + ')', text)


def rebase_script(text, old, new):
    # Only explicit relative URL strings and HTML destinations are relocated.
    # Bare names appended to an already-rebased bundle base (manifest.json,
    # shard filenames) must stay bare. Numeric arrays and calculations stay exact.
    def relative(match):
        return match['quote'] + rebase_url(match['url'], old, new) + match['quote']
    text = URL_STRING.sub(relative, text)
    def fetch(match):
        if match['url'].startswith('.'):
            return match[0]
        return match['prefix'] + match['quote'] + rebase_url(match['url'], old, new, canonical=False) + match['quote']
    return FETCH_STRING.sub(fetch, text)


def canonical_html(raw, old, new):
    text = raw.decode('utf-8')
    require('<base' not in text.lower(), 'Unexpected URL base in saved view: ' + old)
    parts, cursor = [], 0
    original_data = []
    for match in SCRIPT.finditer(text):
        parts.append(rebase_markup(text[cursor:match.start()], old, new))
        opening, body, closing = match.groups()
        if re.search(r'\bid=[\"\x27]spectrum-case-context[\"\x27]', opening):
            # This JSON holds display destinations, not saved scientific data.
            # Its identities stay exact while its old-directory URLs relocate.
            context = json.loads(body)
            for entry in context.values():
                for key in ('result', 'files', 'events', 'spectrum', 'truth', 'response'):
                    if key in entry:
                        entry[key] = rebase_url(entry[key], old, new)
            body = json.dumps(context, ensure_ascii=True, separators=(',', ':'))
        elif re.search(r'type\s*=\s*[\"\x27]application/(?:ld\+)?json[\"\x27]', opening, re.I):
            original_data.append(body)
        else:
            body = rebase_script(body, old, new)
        parts.append(rebase_markup(opening, old, new) + body + closing)
        cursor = match.end()
    parts.append(rebase_markup(text[cursor:], old, new))
    text = ''.join(parts)
    if old == 'detectors/GeGI_3D/strip_explorer.html':
        original = "$('preview').src=current.preview;"
        require(text.count(original) == 1, 'Saved strip preview assignment changed')
        asset_base = rebase_url('./', old, new, canonical=False)
        text = text.replace(original, "$('preview').src=" + json.dumps(asset_base) + '+current.preview;', 1)
    # The public page owns its new study context. Render navigation last so its
    # paths are generated directly for the canonical location, exactly once.
    text = NAV.sub(lambda _: page_navigation(new), text)
    from site_chrome import frame_html
    text = frame_html(text, new)
    from site_discovery import LANDINGS, landing_metadata_html
    from site_routes import page_record
    description = LANDINGS.get(new, page_record(new)['title'] + '. Saved study evidence, original identities, data and methods.')
    text = landing_metadata_html(text, new, description)
    current_data = [m[2] for m in SCRIPT.finditer(text)
                    if re.search(r'type\s*=\s*[\"\x27]application/(?:ld\+)?json[\"\x27]', m[1], re.I)
                    and not re.search(r'\bid=[\"\x27]spectrum-case-context[\"\x27]', m[1])]
    require(current_data == original_data, 'Canonical relocation changed embedded scientific data: ' + old)
    return text.encode('utf-8')


class Anchors(HTMLParser):
    def __init__(self):
        super().__init__()
        self.values = set()

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if value and (key == 'id' or tag == 'a' and key == 'name'):
                self.values.add(value)


def alias_html(old, new, view=None, raw=b''):
    target = posixpath.relpath(new, posixpath.dirname(old))
    public = 'https://kunming-cn.github.io/END2END_Ge_Simulation/' + new
    script = 'const target=' + json.dumps(target) + ';let search=location.search;'
    if view:
        script += ('if(!new URLSearchParams(search).has("view"))search+=(search?"&":"?")+"view=' + view + '";')
    script += 'const next=target+search+location.hash;document.getElementById("canonical-target").href=next;location.replace(next);'
    parser = Anchors()
    parser.feed(raw.decode('utf-8'))
    anchors = ''.join('<span id="' + escape(value, quote=True) + '"></span>'
                      for value in sorted(parser.values - {'canonical-target'}))
    return ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Saved GeSignal view</title><link rel="canonical" href="' + public + '">'
            '<style>body{font:17px/1.6 system-ui;color:#173047;background:#f5f7f7;max-width:46rem;margin:4rem auto;padding:1.5rem}a{color:#075e9b}a:focus-visible{outline:3px solid #e6a040;outline-offset:3px}</style>'
            '</head><body><main><h1>This saved view has moved</h1>'
            '<p><a id="canonical-target" href="' + escape(target, quote=True) + '">Open its maintained study view</a>.</p>'
            '<p>Your saved study, model, event, pulse group and fragment are carried to the new address.</p>'
            '<noscript><p>JavaScript preserves the selection automatically. With scripts disabled, copy the query and fragment from this address to the linked page.</p></noscript>'
            '</main><div hidden aria-hidden="true">' + anchors + '</div><script>' + script + '</script></body></html>\n').encode('utf-8')


def framed_html(raw, path):
    from site_chrome import assembly_html, frame_html
    render = assembly_html if path == 'assemblies/gegi/index.html' else frame_html
    text = render(raw.decode('utf-8'), path)
    if path == 'assemblies/gegi/index.html':
        from site_discovery import LANDINGS, landing_metadata_html
        text = landing_metadata_html(text, path, LANDINGS[path])
    return direct_links_html(text.encode('utf-8'), path)


def source_bytes(record):
    raw = gzip.decompress(base64.b64decode(record['source_gzip_base64'], validate=True))
    require(digest(raw) == record['source_sha256'] and len(raw) == record['source_bytes'],
            'Canonical source receipt differs: ' + record['source'])
    return raw


def read_receipt(site):
    path = local_path(site, RECEIPT)
    receipt = json.loads(path.read_bytes())
    require(receipt['kind'] == KIND and receipt['science_calls'] == 0,
            'Unknown canonical view receipt')
    require(receipt['routes'] == CANONICAL_VIEWS, 'Canonical view route inventory differs')
    require(len({row['source'] for row in receipt['pages']}) == len(receipt['pages']),
            'Repeated canonical source page')
    return receipt


def validate(site, current=False):
    site = Path(site)
    if not (site / RECEIPT).is_file():
        return None
    receipt = read_receipt(site)
    same_sources = receipt['generators'] == sources()
    require(not current or same_sources, 'Canonical display sources changed')
    expected = {old for old in CANONICAL_VIEWS if (site / old).is_file()}
    expected.update(old for old in VIEWER_ALIASES if (site / old).is_file())
    expected.update(old for old in FRAMED_PAGES if (site / old).is_file())
    expected.update(row['source'] for row in receipt['pages'] if row['mode'] == 'linked')
    require({row['source'] for row in receipt['pages']} == expected,
            'Canonical source page inventory differs')
    for row in receipt['pages']:
        raw = source_bytes(row)
        if row['mode'] == 'linked':
            output = local_path(site, row['source']).read_bytes()
            require(digest(output) == row['canonical_sha256'], 'Direct-link page changed: ' + row['source'])
            if same_sources:
                require(output == linked_html(raw, row['source']),
                        'Direct-link page differs from saved source: ' + row['source'])
            continue
        if row['mode'] == 'framed':
            output = local_path(site, row['source']).read_bytes()
            require(digest(output) == row['canonical_sha256'], 'Framed report changed: ' + row['source'])
            if same_sources:
                require(output == framed_html(raw, row['source']), 'Framed report differs from saved source: ' + row['source'])
            continue
        alias = local_path(site, row['source']).read_bytes()
        require(digest(alias) == row['alias_sha256'], 'Saved-link alias changed: ' + row['source'])
        if row['mode'] == 'moved':
            output = local_path(site, row['canonical']).read_bytes()
            require(digest(output) == row['canonical_sha256'], 'Canonical page changed: ' + row['canonical'])
            if same_sources:
                require(output == canonical_html(raw, row['source'], row['canonical']),
                        'Canonical page differs from source transformation: ' + row['canonical'])
        if same_sources:
            require(alias == alias_html(row['source'], row['canonical'], row['view'], raw),
                    'Alias differs from preserved selection contract: ' + row['source'])
    return receipt


def write_owned(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    # validation_view uses hardlinks for unchanged assets. Break any file link
    # before writing so restoring a legacy page cannot modify published bytes.
    if path.exists():
        path.unlink()
    path.write_bytes(data)


def recover_discovery_metadata(site):
    """Undo only an exact, source-proven post-pin discovery transform in a stage.

    Normal validation remains strict. The interrupted publisher may explicitly
    call this before prepare(), then regenerate the presentation from its exact
    saved source. Every other receipt-bound page must already match its pin.
    """
    from site_discovery import LANDINGS, landing_metadata_html
    site = Path(site)
    require(site.resolve() == STAGED_ROOT.resolve(),
            'Discovery recovery requires the existing publication stage')
    receipt = read_receipt(site)
    repairs = []
    for row in receipt['pages']:
        raw = source_bytes(row)
        checks = []
        if row['canonical_sha256']:
            checks.append((row['canonical'], row['canonical_sha256']))
        if row['alias_sha256']:
            checks.append((row['source'], row['alias_sha256']))
        for name, pinned in checks:
            actual = local_path(site, name).read_bytes()
            if digest(actual) == pinned:
                continue
            require(row['mode'] == 'linked' and name == row['source'] and name in LANDINGS,
                    'Staged page differs beyond recoverable discovery metadata: ' + name)
            expected = direct_links_html(raw, name)
            require(digest(expected) == pinned,
                    'Staged direct-link pin cannot be reproduced from source: ' + name)
            discovered = landing_metadata_html(expected.decode('utf-8'), name, LANDINGS[name]).encode('utf-8')
            require(actual == discovered,
                    'Staged page differs beyond exact discovery metadata: ' + name)
            repairs.append((name, expected, digest(actual)))
    for name, expected, _ in repairs:
        write_owned(local_path(site, name), expected)
    validate(site)
    return [dict(path=name, discovered_sha256=actual_hash, restored_sha256=digest(expected),
                 source_proven=True) for name, expected, actual_hash in repairs]


def prepare(site):
    """Restore exact generator inputs after checking the final saved outputs."""
    site = Path(site)
    receipt = validate(site)
    if receipt is None:
        return False
    for row in receipt['pages']:
        write_owned(local_path(site, row['source']), source_bytes(row))
        if row['mode'] == 'moved':
            local_path(site, row['canonical']).unlink()
    local_path(site, RECEIPT).unlink()
    return True


def apply(site):
    site = Path(site)
    if (site / RECEIPT).exists():
        return validate(site, current=True)
    records = []
    for old, new in CANONICAL_VIEWS.items():
        path = local_path(site, old)
        if not path.is_file():
            continue
        require(not (site / new).exists(), 'Canonical target already has another writer: ' + new)
        raw = path.read_bytes()
        output, alias = canonical_html(raw, old, new), alias_html(old, new, raw=raw)
        write_owned(local_path(site, new), output)
        write_owned(path, alias)
        records.append(dict(source=old, canonical=new, mode='moved', view=None,
                            source_sha256=digest(raw), source_bytes=len(raw),
                            source_gzip_base64=base64.b64encode(gzip.compress(raw, mtime=0)).decode('ascii'),
                            canonical_sha256=digest(output), alias_sha256=digest(alias)))
    for old, view in VIEWER_ALIASES.items():
        path = local_path(site, old)
        if not path.is_file() or not (site / CANONICAL_VIEWS['viewers/events.html']).is_file():
            continue
        raw = path.read_bytes()
        new = CANONICAL_VIEWS['viewers/events.html']
        alias = alias_html(old, new, view, raw)
        write_owned(path, alias)
        records.append(dict(source=old, canonical=new, mode='alias', view=view,
                            source_sha256=digest(raw), source_bytes=len(raw),
                            source_gzip_base64=base64.b64encode(gzip.compress(raw, mtime=0)).decode('ascii'),
                            canonical_sha256=None, alias_sha256=digest(alias)))
    for name in FRAMED_PAGES:
        path = local_path(site, name)
        if not path.is_file():
            continue
        raw = path.read_bytes()
        output = framed_html(raw, name)
        write_owned(path, output)
        records.append(dict(source=name, canonical=name, mode='framed', view=None,
                            source_sha256=digest(raw), source_bytes=len(raw),
                            source_gzip_base64=base64.b64encode(gzip.compress(raw, mtime=0)).decode('ascii'),
                            canonical_sha256=digest(output), alias_sha256=None))
    handled = {row[key] for row in records for key in ('source', 'canonical')}
    for path in sorted(site.rglob('*.html')):
        name = path.relative_to(site).as_posix()
        if name in handled:
            continue
        raw = path.read_bytes()
        if direct_links_html(raw, name) == raw:
            continue
        output = linked_html(raw, name)
        write_owned(path, output)
        records.append(dict(source=name, canonical=name, mode='linked', view=None,
                            source_sha256=digest(raw), source_bytes=len(raw),
                            source_gzip_base64=base64.b64encode(gzip.compress(raw, mtime=0)).decode('ascii'),
                            canonical_sha256=digest(output), alias_sha256=None))
    receipt = dict(kind=KIND, science_calls=0, routes=CANONICAL_VIEWS,
                   generators=sources(), pages=records)
    write_owned(local_path(site, RECEIPT), (json.dumps(receipt, sort_keys=True, separators=(',', ':')) + '\n').encode())
    return validate(site, current=True)


@contextmanager
def validation_view(site):
    """Read-only asset mirror with the pre-relocation generator HTML restored."""
    site = Path(site)
    if not (site / RECEIPT).is_file():
        yield site
        return
    validate(site)
    with tempfile.TemporaryDirectory(prefix='canonical-validation-', dir=ROOT / '.local') as directory:
        mirror = Path(directory) / 'site'
        def link(source, target):
            require(not Path(source).is_symlink(), 'Linked asset in canonical validation view')
            try:
                os.link(source, target)
            except OSError as error:
                if error.errno not in (errno.EACCES, errno.EXDEV, errno.EPERM):
                    raise
                shutil.copyfile(source, target)
            return target
        shutil.copytree(site, mirror, copy_function=link)
        prepare(mirror)
        yield mirror
