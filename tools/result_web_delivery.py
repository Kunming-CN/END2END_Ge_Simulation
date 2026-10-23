"""Omit two download-only ring ZIPs while preserving exact saved display data.

The complete, previously checked publication manifest stays unchanged. Portable
validation binds every retained byte to that one manifest; HTML changes remove
only the two ZIPs' anchor tags. Build inputs are restored only in site staging.
"""
from __future__ import annotations

import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import posixpath
import shutil
import stat
from urllib.parse import unquote, urlsplit

import ring_publication as original

ROOT = Path(__file__).resolve().parents[1]
PREFIX = 'examples/cs137-10k-rings'
MARKER = 'web-delivery.json'
KIND = 'ring_download_omission_v1'
SOURCE_MANIFEST_SHA256 = '773e9529ad19b5ff0c48113957248e15d0754429026d7f09d4774332632b6860'
OMITTED = frozenset(model + '/response/ledgers.zip' for model in ('GeRC02', 'KMRC01_candidate'))
OMITTED_BYTES = 93_832_509
# The accepted f442 publication JSON is 253a6e49c4439187df79520dee15d4dfe059ae11304bcd7e36f3fafdd18e0e18.
# This fingerprint excludes ONLY provenance.generator_sha256. All samples,
# flags, units, model settings, original ZIP/member pins and identities remain.
TEACHING_SCIENCE_SHA256 = '8c93849cc98b5de06c800a67ee40f34773871162a9d6daa35522d872abc543e0'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def stamp(body):
    return {'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest()}


def file_stamp(path):
    path = Path(path)
    before = path.lstat()
    require(path.is_file() and not path.is_symlink() and not
            (getattr(before, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT),
            'Linked or non-file delivery input')
    with path.open('rb') as stream:
        result = {'bytes': before.st_size,
                'sha256': hashlib.file_digest(stream, 'sha256').hexdigest()}
    after = path.lstat()
    require((before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns),
            'Delivery input changed during read')
    return result


def encoded(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=True,
                       separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')


def directory(path):
    path = Path(path).absolute()
    require('..' not in path.parts, 'Parent traversal in delivery path')
    for item in (path, *path.parents):
        if item.exists() or item.is_symlink():
            info = item.lstat()
            require(not item.is_symlink() and not
                    (getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT),
                    'Linked delivery path')
    return path


def inventory(folder):
    """Check directory entries before traversal, including Windows junctions."""
    folder = directory(folder)
    names = set()
    for parent, directories, files in os.walk(folder, followlinks=False):
        for name in directories + files:
            path = Path(parent) / name
            info = path.lstat()
            require(not path.is_symlink() and not
                    (getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT),
                    'Linked delivery member')
            if name in files:
                require(path.is_file(), 'Non-file delivery member')
                names.add(path.relative_to(folder).as_posix())
    return names


def _source(folder):
    path = Path(folder) / 'manifest.json'
    file_stamp(path)
    body = path.read_bytes()
    require(stamp(body)['sha256'] == SOURCE_MANIFEST_SHA256,
            'Unknown original ring publication manifest')
    manifest = json.loads(body)
    require(manifest['kind'] == 'ring_saved_publication_v1'
            and manifest['schema_version'] == 1 and manifest['status'] == 'complete'
            and set(manifest['models']) == {'GeRC02', 'KMRC01_candidate'}
            and OMITTED <= set(manifest['files']), 'Original ring publication contract changed')
    return manifest


def _stage(site):
    site = directory(site)
    require(site == directory(ROOT / '.local/site-build'),
            'Result delivery writes are restricted to .local/site-build')
    return site


def _archive_target(page, href):
    parsed = urlsplit(href)
    if parsed.scheme or parsed.netloc:
        return False
    path = unquote(parsed.path)
    if not path or path.startswith('/') or '\\' in path:
        return False
    return posixpath.normpath(posixpath.join(posixpath.dirname(page), path)) in {
        PREFIX + '/' + name for name in OMITTED}


def _rewrite(text, page):
    """Delete only matching opening/closing anchor tags; keep their contents."""
    offsets = [0]
    for line in text.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))

    class Anchors(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=False)
            self.anchor = None
            self.removals = []

        def position(self):
            line, column = self.getpos()
            return offsets[line - 1] + column

        def handle_starttag(self, tag, attrs):
            if tag != 'a':
                return
            require(self.anchor is None, 'Nested archive anchor')
            start = self.position()
            self.anchor = (start, start + len(self.get_starttag_text()),
                           _archive_target(page, dict(attrs).get('href', '')))

        def handle_endtag(self, tag):
            if tag != 'a' or self.anchor is None:
                return
            start, end, selected = self.anchor
            if selected:
                close = self.position()
                self.removals.extend(((start, end), (close, text.index('>', close) + 1)))
            self.anchor = None

    parser = Anchors()
    parser.feed(text)
    parser.close()
    require(parser.anchor is None or not parser.anchor[2], 'Unclosed archive anchor')
    edits, removed = [], 0
    for start, end in sorted(parser.removals):
        edits.append({'at': start - removed, 'text': text[start:end]})
        removed += end - start
    for start, end in sorted(parser.removals, reverse=True):
        text = text[:start] + text[end:]
    return text, edits


def strip_archive_links(text, page):
    """Deterministic hook for maintained report/spectrum HTML generators."""
    return _rewrite(text, page)[0]


def _restore(text, edits):
    previous = -1
    for edit in edits:
        require(set(edit) == {'at', 'text'} and type(edit['at']) is int
                and previous <= edit['at'] <= len(text) and type(edit['text']) is str,
                'Invalid archive-link restoration')
        previous = edit['at']
    for edit in reversed(edits):
        text = text[:edit['at']] + edit['text'] + text[edit['at']:]
    return text


def active(site):
    return (Path(site) / PREFIX / MARKER).is_file()


def validate_bundle(folder):
    """Portable verification of one exact accepted publication derivative."""
    folder = directory(folder)
    names = inventory(folder)
    source = _source(folder)
    receipt = json.loads((folder / MARKER).read_bytes())
    require(set(receipt) == {'kind', 'schema_version', 'original_manifest_sha256',
                            'producer_sha256', 'omitted_downloads', 'omitted_bytes',
                            'html_rewrites', 'teaching_science_sha256', 'new_simulations'},
            'Unexpected result delivery receipt fields')
    require(receipt['kind'] == KIND and receipt['schema_version'] == 1
            and receipt['original_manifest_sha256'] == SOURCE_MANIFEST_SHA256
            and receipt['producer_sha256'] == file_stamp(__file__)['sha256']
            and receipt['new_simulations'] == 0, 'Unknown result delivery binding')
    omitted = {name: source['files'][name] for name in sorted(OMITTED)}
    require(receipt['omitted_downloads'] == omitted
            and receipt['omitted_bytes'] == sum(item['bytes'] for item in omitted.values()) == OMITTED_BYTES,
            'Only the two registered ring ZIP downloads may be omitted')
    require(receipt['teaching_science_sha256'] == TEACHING_SCIENCE_SHA256,
            'Teaching witness changed')
    require(names == (set(source['files']) - OMITTED) | {'manifest.json', MARKER},
            'Result delivery inventory changed')
    rewrites = receipt['html_rewrites']
    expected_rewrites = set()
    for name, meta in source['files'].items():
        if name in OMITTED:
            continue
        path = folder / name
        if name in rewrites:
            require(name.endswith('.html'), 'Only archive anchor HTML may be rewritten')
            binding = rewrites[name]
            require(set(binding) == {'delivered', 'removed_anchor_tags'}, 'Unknown HTML rewrite binding')
            body = path.read_bytes()
            require(stamp(body) == binding['delivered'], 'Delivered report HTML changed: ' + name)
            restored = _restore(body.decode('utf-8'), binding['removed_anchor_tags'])
            require(stamp(restored.encode('utf-8')) == meta, 'Original report content changed: ' + name)
            text, edits = _rewrite(restored, PREFIX + '/' + name)
            require(text.encode('utf-8') == body and edits == binding['removed_anchor_tags'] and edits,
                    'Report change is not an exact archive-anchor removal: ' + name)
            expected_rewrites.add(name)
        else:
            require(file_stamp(path) == meta, 'Retained scientific/publication bytes changed: ' + name)
            if name.endswith('.html'):
                text = path.read_text(encoding='utf-8')
                require(strip_archive_links(text, PREFIX + '/' + name) == text,
                        'Omitted archive still linked: ' + name)
    require(set(rewrites) == expected_rewrites, 'Unregistered report rewrite')
    return receipt


def _teaching_payload(site):
    import teaching_examples as teaching
    data = Path(site) / teaching.DATA
    directory(data.parent)
    require(data.is_file() and not data.is_symlink(), 'Missing or linked teaching data')
    payload = json.loads(data.read_bytes())
    scientific = dict(payload)
    provenance = dict(scientific['provenance'])
    provenance.pop('generator_sha256')
    scientific['provenance'] = provenance
    require(stamp(encoded(scientific))['sha256'] == TEACHING_SCIENCE_SHA256,
            'Accepted teaching scientific payload changed')
    teaching.require_frozen_sources()
    require(payload['provenance']['generator_sha256'] == {
        name: teaching.sha(teaching.ROOT / name) for name in teaching.GENERATORS},
        'Teaching generator binding changed')
    require(data.read_bytes() == teaching.canonical(payload).encode('utf-8'),
            'Teaching serialization changed')
    return payload


def validate_teaching(site):
    """Validate exact accepted teaching science without omitted public ZIPs."""
    import teaching_examples as teaching
    site = Path(site)
    validate_bundle(site / PREFIX)
    payload = _teaching_payload(site)
    # All retained source inputs remain independently pinned. Only the two exact
    # download paths are absent; their hashes are part of the scientific witness.
    for name, expected in teaching.SOURCE_SHA256.items():
        if name not in {PREFIX + '/' + item for item in OMITTED}:
            require(file_stamp(site / name)['sha256'] == expected,
                    'Retained teaching source changed: ' + name)
    page = site / teaching.PAGE
    directory(page.parent)
    require(page.is_file() and not page.is_symlink(), 'Missing or linked teaching HTML')
    html = teaching.render(payload)
    require(page.read_bytes() == html.encode('utf-8'), 'Teaching rendering changed')
    return teaching.metadata(payload, html)


def materialize_for_build(site):
    """Restore only exact staged build inputs from the permanent web bundle."""
    site = _stage(site)
    folder = site / PREFIX
    if not folder.exists():
        return None
    if not active(site):
        _source(folder)
        return None
    receipt = validate_bundle(folder)
    local = directory(ROOT / '.local/ring-publication-v1/web-bundle')
    source = _source(local)
    # Preflight every copy before any stage mutation.
    for name in OMITTED:
        directory((local / name).parent)
        require(not (local / name).is_symlink() and file_stamp(local / name) == source['files'][name],
                'Permanent original archive changed: ' + name)
    restored = {}
    for name, binding in receipt['html_rewrites'].items():
        restored[name] = _restore((folder / name).read_text(encoding='utf-8'),
                                  binding['removed_anchor_tags']).encode('utf-8')
    for name in sorted(OMITTED):
        with (local / name).open('rb') as src, (folder / name).open('xb') as dst:
            shutil.copyfileobj(src, dst)
        require(file_stamp(folder / name) == source['files'][name], 'Stage archive copy changed')
    for name, body in restored.items():
        (folder / name).write_bytes(body)
    (folder / MARKER).unlink()
    return {'restored_downloads': len(OMITTED), 'restored_bytes': receipt['omitted_bytes']}


def finalize(site):
    """Seal the checked derivative and omit only the two staged download ZIPs."""
    site = _stage(site)
    folder = site / PREFIX
    if not folder.exists():
        return None
    if active(site):
        return validate_bundle(folder)
    source = _source(folder)
    require(original.validate_bundle(folder) == source, 'Original ring validation changed')
    local = directory(ROOT / '.local/ring-publication-v1/web-bundle')
    require(_source(local) == source, 'Permanent original publication binding changed')
    for name in OMITTED:
        require(file_stamp(local / name) == source['files'][name]
                and file_stamp(folder / name) == source['files'][name],
                'Archive preservation preflight failed: ' + name)
    _teaching_payload(site)
    rewrites, changes = {}, {}
    # Maintained generators should use strip_archive_links before sealing their
    # own manifests. This final scan also handles the three frozen report pages.
    for name in inventory(site):
        if not name.endswith('.html'):
            continue
        path = site / name
        text = path.read_text(encoding='utf-8')
        updated, edits = _rewrite(text, name)
        if not edits:
            continue
        changes[name] = updated.encode('utf-8')
        if name.startswith(PREFIX + '/'):
            rel = name[len(PREFIX) + 1:]
            require(stamp(text.encode('utf-8')) == source['files'][rel], 'Original report changed before delivery')
            rewrites[rel] = {'delivered': stamp(changes[name]), 'removed_anchor_tags': edits}
    receipt = {'kind': KIND, 'schema_version': 1,
               'original_manifest_sha256': SOURCE_MANIFEST_SHA256,
               'producer_sha256': file_stamp(__file__)['sha256'],
               'omitted_downloads': {name: source['files'][name] for name in sorted(OMITTED)},
               'omitted_bytes': sum(source['files'][name]['bytes'] for name in OMITTED),
               'html_rewrites': rewrites, 'teaching_science_sha256': TEACHING_SCIENCE_SHA256,
               'new_simulations': 0}
    require(receipt['omitted_bytes'] == OMITTED_BYTES, 'Original archive byte count changed')
    for name, body in changes.items():
        (site / name).write_bytes(body)
    # Only canonical staging and these explicit, pinned owned paths are removed.
    for name in sorted(OMITTED):
        path = folder / name
        require(path.absolute().is_relative_to(site), 'Archive outside stage')
        path.unlink()
    with (folder / MARKER).open('xb') as stream:
        stream.write(encoded(receipt))
    validate_bundle(folder)
    return receipt
