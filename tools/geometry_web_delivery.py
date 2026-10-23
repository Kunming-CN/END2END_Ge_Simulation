"""Lossless gzip delivery of the exact saved AK02/SAP22 10K geometry bundle.

No simulation entry. Original scenes, indices, event JSON and provenance retain
their exact bytes; only the maintained viewer resolves event filenames to gzip.
"""
import argparse
from collections import Counter
import gzip
import hashlib
import io
import json
from pathlib import Path
import platform
import re
import stat
import time
import zlib

import geometry_publication as original
from geometry_events import validate_event

KIND = 'geometry_lossless_web_delivery_v1'
PREFIX = 'examples/cs137-10k-geometry'
SOURCE_MANIFEST_SHA256 = 'e8d183af05e27f211b6464939d4c667b6d02855d68609a7627753d2f16edc379'
MODELS = ('AK02', 'SAP22')
COMPRESSION = {'format': 'gzip', 'level': 6, 'mtime': 0}
CHUNK = re.compile(r'(AK02|SAP22)/events-[0-9]{5}\.json\Z')
REDIRECT = b'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Saved radiation event viewer</title></head><body>
<h1>Saved radiation events</h1><p><a id="viewer" href="../../viewers/events.html?view=assembly">Open the maintained event viewer</a></p>
<script>
'use strict';
const target='../../viewers/events.html'+location.search+(location.search?'&':'?')+'view=assembly'+location.hash;
document.getElementById('viewer').href=target;
location.replace(target);
</script></body></html>
'''


def require(ok, message):
    if not ok:
        raise ValueError(message)


def stamp(body):
    return {'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest()}


def encoded(value):
    return (json.dumps(value, ensure_ascii=True, allow_nan=False,
                       separators=(',', ':'), sort_keys=True) + '\n').encode('utf-8')


def directory(path):
    """Reject linked roots/parents before reading or reserving an output."""
    path = Path(path).absolute()
    require('..' not in path.parts, 'Parent traversal in bundle path')
    for item in (path, *path.parents):
        if item.exists() or item.is_symlink():
            info = item.lstat()
            require(not item.is_symlink() and not
                    (getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT),
                    'Linked bundle path')
    return path


def inventory(folder):
    found = set()
    for path in folder.rglob('*'):
        info = path.lstat()
        require(not path.is_symlink() and not
                (getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT),
                'Linked bundle member')
        if path.is_file():
            found.add(path.relative_to(folder).as_posix())
    return found


def source_manifest(body):
    require(stamp(body)['sha256'] == SOURCE_MANIFEST_SHA256,
            'Unknown original geometry manifest')
    manifest = json.loads(body)
    require(manifest['schema_version'] == 1 and manifest['status'] == 'complete'
            and set(manifest['models']) == set(MODELS), 'Original geometry census')
    return manifest


def delivery_name(name):
    return name + '.gz' if CHUNK.fullmatch(name) or name == 'geometry.html' else name


def _source_bytes(folder, name, meta):
    body = (folder / name).read_bytes()
    require(stamp(body) == meta, 'Original geometry asset changed: ' + name)
    return body


def _uncompressed(folder, name, meta):
    path = folder / delivery_name(name)
    if delivery_name(name) == name:
        return _source_bytes(folder, name, meta)
    # The pinned uncompressed byte count bounds even a deliberately rehashed
    # gzip bomb. No sampled, truncated or reserialized JSON enters validation.
    with gzip.GzipFile(fileobj=io.BytesIO(path.read_bytes())) as stream:
        body = stream.read(meta['bytes'] + 1)
    require(stamp(body) == meta, 'Decompressed original differs: ' + name)
    return body


def validate(folder, check_events=True, *, _manifest_name='manifest.json'):
    folder = directory(folder)
    manifest = json.loads((folder / _manifest_name).read_bytes())
    require(manifest.get('kind') == KIND and manifest.get('schema_version') == 1
            and manifest.get('status') == 'complete', 'Unknown geometry delivery')
    require(manifest.get('compression') == COMPRESSION, 'Geometry compression settings changed')
    require(manifest.get('new_simulations') == 0, 'Geometry delivery cannot run simulations')
    require(manifest.get('producer_sha256') == stamp(Path(__file__).read_bytes())['sha256'],
            'Geometry delivery producer changed')
    raw = (folder / 'original-manifest.json').read_bytes()
    source = source_manifest(raw)
    require(manifest.get('original_manifest') == stamp(raw), 'Original manifest binding changed')
    require(manifest.get('models') == source['models'], 'Original model metadata changed')
    expected_files = {delivery_name(name) for name in source['files']} | {
        'original-manifest.json', 'geometry.html'}
    require(set(manifest['files']) == expected_files and inventory(folder) ==
            expected_files | {_manifest_name}, 'Geometry delivery file inventory')
    for name, meta in manifest['files'].items():
        require(stamp((folder / name).read_bytes()) == meta,
                'Geometry delivery asset changed: ' + name)
    require((folder / 'geometry.html').read_bytes() == REDIRECT,
            'Geometry viewer redirect changed')
    # Verify EVERY preserved source byte, even when a caller only needs origin
    # bindings and can reuse the separate full event-validation boundary.
    for name, meta in source['files'].items():
        if not CHUNK.fullmatch(name):
            _uncompressed(folder, name, meta)
    chunks = 0
    for model in MODELS:
        record = source['models'][model]
        scene = json.loads((folder / record['scene']).read_bytes())
        index = scene['event_index']
        require(record['scene'] == model + '/scene.json' and scene['model'] == model
                and record['event_count'] == index['event_count'] == 10000
                and len(index['chunks']) == 100, 'Original geometry event census')
        require(scene['raw_lh5_sha256'] == record['raw_lh5_sha256'], 'Original raw LH5 identity')
        offsets, hits = Counter(), []
        for n, chunk in enumerate(index['chunks']):
            name = model + f'/events-{n * 100:05d}.json'
            require(chunk['file'] == name.split('/')[1] and chunk['first'] == n * 100
                    and chunk['count'] == 100 and
                    chunk['sha256'] == source['files'][name]['sha256'],
                    'Original chunk identity changed')
            body = _uncompressed(folder, name, source['files'][name])
            chunks += 1
            if not check_events:
                continue
            data = json.loads(body)
            require(data['model'] == model and data['first'] == n * 100
                    and len(data['events']) == 100, 'Decompressed chunk census')
            for j, event in enumerate(data['events']):
                validate_event(event, n * 100 + j, offsets)
                if any(row['edep'] > 0 for row in event['tables']['stp/germanium']):
                    hits.append(event['event_id'])
        if check_events:
            require(dict(offsets) == {k: v for k, v in index['raw_rows'].items() if v}
                    and index['raw_rows'] == record['raw_rows'], 'Original raw row census')
            require(hits == index['ge_hit_ids'] and len(hits) == record['ge_hit_count']
                    and index['zero_ge_primaries'] == 10000 - len(hits), 'Original hit/zero census')
    require(chunks == 200, 'Geometry delivery chunk census')
    return manifest


def assemble(source, output):
    source, output = directory(source), directory(output)
    require(not output.exists(), 'Do not overwrite geometry delivery or failed evidence')
    require(not output.is_relative_to(source) and not source.is_relative_to(output),
            'Geometry source and delivery overlap')
    raw = (source / 'manifest.json').read_bytes()
    manifest = source_manifest(raw)
    require(original.validate_bundle(source) == manifest, 'Original geometry validation changed')
    producer = stamp(Path(__file__).read_bytes())['sha256']
    output.mkdir(parents=True)
    files = {}
    for name, meta in manifest['files'].items():
        target = output / delivery_name(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        if delivery_name(name) == name:
            with target.open('xb') as stream:
                stream.write(_source_bytes(source, name, meta))
        else:
            digest, count = hashlib.sha256(), 0
            with (source / name).open('rb') as src, target.open('xb') as stream:
                with gzip.GzipFile(filename='', mode='wb', fileobj=stream,
                                   compresslevel=COMPRESSION['level'], mtime=0) as zipped:
                    while block := src.read(1024 * 1024):
                        count += len(block)
                        digest.update(block)
                        zipped.write(block)
            require({'bytes': count, 'sha256': digest.hexdigest()} == meta,
                    'Original changed during compression: ' + name)
        files[delivery_name(name)] = stamp(target.read_bytes())
    for name, body in (('original-manifest.json', raw), ('geometry.html', REDIRECT)):
        with (output / name).open('xb') as stream:
            stream.write(body)
        files[name] = stamp(body)
    require((source / 'manifest.json').read_bytes() == raw and
            stamp(Path(__file__).read_bytes())['sha256'] == producer,
            'Geometry source or delivery writer changed')
    receipt = {'kind': KIND, 'schema_version': 1, 'status': 'complete',
               'compression': COMPRESSION, 'original_manifest': stamp(raw),
               'producer_sha256': producer, 'models': manifest['models'], 'files': files,
               'runtime': {'python': platform.python_version(), 'zlib': zlib.ZLIB_VERSION},
               'new_simulations': 0}
    with (output / 'manifest.pending.json').open('xb') as stream:
        stream.write(encoded(receipt))
    validate(output, _manifest_name='manifest.pending.json')
    (output / 'manifest.pending.json').rename(output / 'manifest.json')
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, help='Exact checked original geometry publication')
    parser.add_argument('--output', type=Path, required=True, help='New delivery directory; never overwritten')
    parser.add_argument('--validate', action='store_true', help='Verify an existing derivative without writing')
    args = parser.parse_args()
    started = time.perf_counter()
    if args.validate:
        receipt = validate(args.output)
    else:
        if args.source is None:
            parser.error('--source is required for generation')
        receipt = assemble(args.source, args.output)
    source = source_manifest((args.output / 'original-manifest.json').read_bytes())
    print(json.dumps({'status': 'complete', 'kind': receipt['kind'], 'event_count': 20000,
                      'event_chunks': 200, 'source_bytes': sum(v['bytes'] for v in source['files'].values())
                      + (args.output / 'original-manifest.json').stat().st_size,
                      'delivery_bytes': sum(p.stat().st_size for p in args.output.rglob('*') if p.is_file()),
                      'manifest_sha256': stamp((args.output / 'manifest.json').read_bytes())['sha256'],
                      'elapsed_seconds': time.perf_counter() - started}, indent=2))


if __name__ == '__main__':
    main()
