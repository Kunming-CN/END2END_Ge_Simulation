"""Lossless saved-LH5 event display + native Geant4 meshes. No simulation entry.

Run with transport/run.sh python -B tools/geometry_events.py (from project root).
Only .local/geometry-events-publication/{build,bundle,logs} is writable.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / '.local/geometry-events-publication'
SAVED = ROOT / '.local/peak-native-delivery/cs10000-v2'
MODELS = ('AK02', 'SAP22')
ORIGINALS = ('geometry.gdml', 'canonical.gdml', 'run.mac', 'scenario.json',
             'prepared.json', 'geometry-report.json', 'run.json', 'prepare-receipt.json')
SOURCE = [0, 37.073, .29]
ROTATION = [[1, 0, 0], [0, 0, 1], [0, -1, 0]]
TRANSLATION = [0, 1.45, .29]
OMISSIONS = [
    'World-air steps are unscored. No connectors are invented across unrecorded paths.',
    'Track rows are creation vertices/momenta/identities, not continuous trajectories.',
    'STEP pre/post pairs are recorded chords, not curved microscopic paths.',
    'No SSD carrier parcels, readout waveforms, charge reconstruction or ADC reruns.',
    'Curved-surface tessellation is visualization only; the downloaded GDML is exact.',
    'Parent solids include daughter regions; transparent surfaces are not a material occupancy map.',
    'Nominal engineering geometry, not surveyed/as-built; no efficiency or calibrated CCE claim.',
    'No upstream .tg source, raw LH5, full energy closure, or measured pulse comparison included.',
    'Central-ray navigator analysis is not included in this exporter.',
]


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def finite(value):
    if isinstance(value, float):
        require(math.isfinite(value), 'nonfinite numeric value')
    elif isinstance(value, dict):
        for child in value.values():
            finite(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            finite(child)


def checked(path, base, new=False):
    """Reject traversal/symlinks, including a symlinked parent, before writes."""
    path, base = Path(path).absolute(), Path(base).resolve()
    require('..' not in path.parts and path == path.resolve(), 'escaped/linked path')
    require(path != base and path.is_relative_to(base), 'escaped output path')
    if new:
        require(not path.exists(), 'output already exists')
    return path


def verified(path, expected):
    require(isinstance(expected, str) and len(expected) == 64, 'missing/invalid hash')
    require(Path(path).is_file() and digest(path) == expected, 'wrong/missing hash: ' + Path(path).name)


def write_json(path, obj):
    finite(obj)
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(obj, stream, ensure_ascii=True, allow_nan=False, separators=(',', ':'))
        stream.write('\n')


def dependencies():
    run = read(SAVED / 'run.json')
    require(run['status'] in ('completed', 'completed_with_native_failures'), 'campaign not terminal')
    hashes = run['source_sha256']
    require(len(hashes) == 17, 'expected all 17 recorded computational dependencies')
    for name, sha in hashes.items():
        verified(checked(ROOT / name, ROOT), sha)
    return run


def inputs(model):
    directory = SAVED / model / 'transport'
    meta, receipt = read(directory / 'prepared.json'), read(directory / 'run.json')
    require(receipt['status'] == 'complete' and receipt['returncode'] == 0, 'transport incomplete')
    verified(directory / 'prepared.json', receipt.get('prepared_sha256'))
    required = {'geometry.gdml', 'canonical.gdml', 'geometry-report.json', 'run.mac', 'scenario.json'}
    require(required <= set(meta['files_sha256']), 'missing prepared hashes')
    for name, sha in meta['files_sha256'].items():
        require(Path(name).name == name, 'escaped prepared filename')
        verified(directory / name, sha)
    verified(directory / 'truth.lh5', receipt.get('source_lh5_sha256'))
    for name, sha in meta['source_sha256'].items():
        require(Path(name).name == name, 'escaped source filename')
        verified(ROOT / 'transport' / name, sha)
    require(meta['model_id'] == model and meta['primary_count'] == 10000, 'wrong model/census')
    scenario = read(directory / 'scenario.json')
    require(meta['source_position_global_mm'] == scenario['source']['position_global_mm'] == SOURCE,
            'source placement changed')
    for item in (meta, scenario):
        transform = item['coordinate_transform']
        require(transform['rotation_local_to_global'] == ROTATION and
                transform['translation_global_mm'] == TRANSLATION, 'Ge transform changed')
    finite(meta); finite(scenario)
    return directory, meta, receipt, scenario


def close_values(a, b, tolerance=1e-9):
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(close_values(x, y, tolerance) for x, y in zip(a, b))
    return isinstance(a, (int, float)) and isinstance(b, (int, float)) and abs(a-b) <= tolerance


def validate_scene(scene, report, meta):
    finite(scene); finite(report)
    require(scene['generator'] == 'G4GDMLParser/G4Polyhedron' and scene['units'] == 'mm', 'non-native scene')
    require(scene['geant4_version_number'] == report['geant4_version_number'] == 1132, 'wrong Geant4')
    expected = {v['name']: v for v in report['volumes']}
    volumes = scene['volumes']
    require(len(volumes) == len(expected) == 20 and {v['name'] for v in volumes} == set(expected), 'volume census')
    for index, volume in enumerate(volumes):
        original = expected[volume['name']]
        for field in ('copy_number', 'material'):
            require(volume[field] == original[field], 'material/copy mismatch')
        for field in ('translation_global_mm', 'rotation_local_to_global', 'density_g_cm3'):
            require(close_values(volume[field], original[field]), 'geometry report transform/material mismatch')
        require(type(volume['parent']) is int and -1 <= volume['parent'] < index, 'invalid hierarchy')
        require((volume['parent'] == -1) == (index == 0), 'invalid world parent')
        if index:
            parent = expected[volumes[volume['parent']]['name']]['original_path']
            require(original['original_path'].rsplit('/', 1)[0] == parent, 'hierarchy/report mismatch')
        vertices = volume['vertices_global_mm']
        require(vertices and all(len(p) == 3 and all(type(x) in (int, float) for x in p) for p in vertices),
                'invalid vertex coordinates')
        for key, length in (('triangles', 3), ('wireframe', 2)):
            require(volume[key] and all(len(face) == length and all(type(i) is int and 0 <= i < len(vertices)
                    for i in face) for face in volume[key]), 'invalid mesh indices')
        if volume['name'] == 'germanium':
            require(close_values(volume['rotation_local_to_global'], ROTATION) and
                    close_values(volume['translation_global_mm'], TRANSLATION), 'Ge placement mismatch')
        if index:
            require(meta['material_tables']['stp/' + volume['name']] == volume['material'], 'scoring material mismatch')
        volume['original_path'] = original['original_path']
    require(close_values(expected['ledger_18']['translation_global_mm'], SOURCE), 'capsule/source mismatch')


def scalar(value):
    if hasattr(value, 'item'):
        value = value.item()
    if isinstance(value, bytes):
        value = value.decode('utf-8')
    finite(value)
    require(type(value) in (str, int, float, bool), 'unsupported raw scalar')
    return value


def table_schema(table):
    return {name: {'dtype': str(ds.dtype), 'attributes': {k: scalar(v) for k, v in ds.attrs.items()}}
            for name, ds in table.items()}


def validate_event(event, eid, offsets):
    require(event['event_id'] == eid, 'ID census mismatch')
    finite(event)
    rows = event['tables']
    require(len(rows['vtx']) == len(rows['particles']) == 1, 'missing primary')
    tracks = {r['trackid']: r for r in rows['tracks']}
    require(len(tracks) == len(rows['tracks']), 'duplicate track identity')
    for table, records in rows.items():
        for r in records:
            require(r['evtid'] == eid and r['raw_row_index'] == offsets[table], 'raw row census mismatch')
            offsets[table] += 1
            if table.startswith('stp/'):
                t = tracks.get(r['trackid'])
                require(t is not None and (t['parent_trackid'], t['particle']) ==
                        (r['parent_trackid'], r['particle']), 'step/track identity mismatch')
    for t in tracks.values():
        require(t['parent_trackid'] == 0 or t['parent_trackid'] in tracks, 'missing track parent')


def export_raw(directory, meta, destination):
    # Existing pinned reader validates float64, units, order, aliases and identities.
    import h5py
    sys.path.insert(0, str(ROOT / 'transport'))
    import cs137 as cs
    chunks, hits, offsets = [], [], Counter()
    with h5py.File(directory / 'truth.lh5', 'r') as raw:
        require(int(raw['number_of_simulated_events'][()]) == meta['primary_count'], 'LH5 census mismatch')
        materials = meta['material_tables']
        require({'stp/' + k for k in raw['stp'] if k != '__by_uid__'} == set(materials), 'scored table census')
        aliases = cs.step_aliases(raw, materials)
        keys = ['vtx', 'particles', 'tracks', *sorted(materials)]
        schemas = {key: table_schema(raw[key]) for key in keys}
        totals = {key: len(raw[key]['evtid']) for key in keys}
        processes = list(cs.table_rows(raw['processes']))
        process_names = {p['procid']: p['name'] for p in processes}
        for key in keys:
            cs.field(raw[key], 'evtid', integer=True)
            for name, ds in raw[key].items():
                require(ds.dtype.kind in 'iu' or ds.dtype.kind == 'f' and ds.dtype.itemsize == 8,
                        'unexpected event column type/precision')
            if key.startswith('stp/') or key in ('tracks', 'vtx'):
                cs.field(raw[key], 'time', 'ns')
                for suffix in ('', '_pre', '_post') if key.startswith('stp/') else ('',):
                    for axis in ('xloc', 'yloc', 'zloc'):
                        cs.field(raw[key], axis + suffix, 'm')
            if key.startswith('stp/'):
                cs.field(raw[key], 'edep', 'keV')
        cursors = {key: cs.Cursor(raw[key], meta['primary_count']) for key in keys}
        chunk = []
        for eid in range(meta['primary_count']):
            tables = {key: cursor.take(eid) for key, cursor in cursors.items()}
            event = {'event_id': eid, 'tables': tables}
            validate_event(event, eid, offsets)
            cs.validate_decay_tracks(tables['tracks'], process_names)
            v = tables['vtx'][0]
            require(close_values([v[a]*1000 for a in ('xloc', 'yloc', 'zloc')], SOURCE), 'raw source mismatch')
            if any(r['edep'] > 0 for r in tables['stp/germanium']):
                hits.append(eid)
            chunk.append(event)
            if len(chunk) == 100:
                first = eid - 99
                name = f'events-{first:05d}.json'
                write_json(destination / name, {'model': meta['model_id'], 'first': first, 'events': chunk})
                chunks.append({'file': name, 'first': first, 'count': 100, 'sha256': digest(destination/name)})
                chunk = []
        require(not chunk and all(c.next is None for c in cursors.values()), 'unconsumed events')
        require(dict(offsets) == {k: n for k, n in totals.items() if n}, 'raw row accounting failed')
    return {'event_count': meta['primary_count'], 'chunks': chunks, 'ge_hit_ids': hits,
            'zero_ge_primaries': meta['primary_count']-len(hits), 'raw_rows': totals,
            'raw_columns': schemas, 'processes': processes, 'step_aliases': aliases,
            'step_alias_policy': 'aliases reference the same rows; exported once per named table'}


def export(executable, output):
    output = checked(output, WORK, new=True)
    require(output == WORK / 'bundle', 'output must be assigned bundle root')
    executable = checked(executable, WORK / 'build')
    require(executable.is_file(), 'native Geant4 scene executable missing')
    run = dependencies()
    prepared = {model: inputs(model) for model in MODELS}
    source_files = ['tools/geometry_events.py', 'tools/geometry_events.html',
                    'tools/geant4_scene/scene.cc', 'tools/geant4_scene/CMakeLists.txt']
    exporter_hashes = {name: digest(ROOT/name) for name in source_files}
    executable_hash = digest(executable)
    # Generate and validate both actual native scenes BEFORE reserving bundle.
    scenes = {}
    logs = checked(WORK/'logs', WORK)
    logs.mkdir(parents=True, exist_ok=True)
    for model, (directory, meta, receipt, scenario) in prepared.items():
        native = checked(WORK/'build'/f'{model}-scene-native.json', WORK/'build', new=True)
        log = checked(logs/f'{model}-native.log', logs, new=True)
        with log.open('x', encoding='utf-8') as stream:
            subprocess.run([str(executable), str(directory/'geometry.gdml'), str(native)],
                           check=True, stdout=stream, stderr=subprocess.STDOUT)
        scene = read(native)
        validate_scene(scene, read(directory/'geometry-report.json'), meta)
        scenes[model] = scene
    output.mkdir()
    manifest = {'schema_version': 1, 'status': 'complete', 'models': {},
                'exporter_sha256': exporter_hashes, 'native_executable_sha256': executable_hash,
                'computational_dependency_sha256': run['source_sha256'], 'omissions': OMISSIONS,
                'campaign_run_sha256': digest(SAVED/'run.json'),
                'upstream': read(ROOT/'transport/cryostat-source.json'),
                'runtime': {'python': sys.version}, 'files': {}}
    for model, (directory, meta, receipt, scenario) in prepared.items():
        target = output/model; target.mkdir()
        index = export_raw(directory, meta, target)
        require(index['zero_ge_primaries'] == run['models'][model]['counts']['zero_deposit_primaries'],
                'campaign zero-Ge accounting mismatch')
        require(index['raw_rows']['stp/germanium'] == receipt['validation']['ge_rows'], 'Ge row accounting mismatch')
        originals = {name: digest(directory/name) for name in ORIGINALS}
        with zipfile.ZipFile(target/'originals.zip', 'x', zipfile.ZIP_DEFLATED) as archive:
            for name in ORIGINALS:
                archive.write(directory/name, name)
            archive.write(ROOT/'transport/cryostat-source.json', 'cryostat-source.json')
        scene = scenes[model]
        scene.update({'model': model, 'source_position_global_mm': SOURCE, 'coordinate_transform': meta['coordinate_transform'],
                      'scenario': scenario, 'material_tables': meta['material_tables'], 'omissions': OMISSIONS,
                      'raw_lh5_sha256': receipt['source_lh5_sha256'], 'originals_sha256': originals,
                      'raw_software_versions': receipt['versions'], 'seed': meta['seed'],
                      'event_index': index})
        write_json(target/'scene.json', scene)
        manifest['models'][model] = {'scene': f'{model}/scene.json', 'originals': f'{model}/originals.zip',
                                     'raw_lh5_sha256': receipt['source_lh5_sha256'], 'raw_rows': index['raw_rows'],
                                     'event_count': index['event_count'], 'ge_hit_count': len(index['ge_hit_ids'])}
    shutil.copyfile(ROOT/'tools/geometry_events.html', output/'geometry.html')
    (output/'README.txt').write_text('Serve this directory over HTTP: python -m http.server 8000 --bind 127.0.0.1\n'
        'Open http://127.0.0.1:8000/geometry.html . No external libraries or network services needed.\n'
        'file:// fetch is unsupported. Every event is accessible in 100-event JSON chunks.\n'
        'Unzip each model originals.zip for exact geometry GDML, macro, scenario and preparation records.\n'
        'Upstream attribution is in manifest.json and originals.zip; no relicensing grant is made.\n', encoding='utf-8')
    dependencies()
    for model in MODELS:
        inputs(model)
    require(exporter_hashes == {name: digest(ROOT/name) for name in source_files} and
            executable_hash == digest(executable), 'exporter changed during export')
    for path in sorted(output.rglob('*')):
        if path.is_file():
            manifest['files'][path.relative_to(output).as_posix()] = {'sha256': digest(path), 'bytes': path.stat().st_size}
    write_json(output/'manifest.json', manifest)
    return manifest


def validate_bundle(bundle):
    bundle = Path(bundle)
    manifest = read(bundle/'manifest.json')
    require(manifest['status'] == 'complete', 'incomplete bundle')
    files = manifest['files']
    actual = {p.relative_to(bundle).as_posix() for p in bundle.rglob('*') if p.is_file()}
    require(actual == {*files, 'manifest.json'}, 'bundle file census mismatch')
    for name, info in files.items():
        path = checked(bundle/name, bundle)
        verified(path, info.get('sha256'))
        require(path.stat().st_size == info['bytes'], 'bundle size mismatch')
    for model in MODELS:
        scene = read(bundle/model/'scene.json')
        _, meta, _, _ = inputs(model)
        validate_scene(scene, read(SAVED/model/'transport/geometry-report.json'), meta)
        offsets = Counter()
        next_id = 0
        hits = []
        index = scene['event_index']
        for entry in index['chunks']:
            path = checked(bundle/model/entry['file'], bundle/model)
            verified(path, entry.get('sha256'))
            chunk = read(path)
            require(chunk['model'] == model and chunk['first'] == entry['first'] == next_id and
                    len(chunk['events']) == entry['count'] == 100, 'chunk census mismatch')
            for event in chunk['events']:
                validate_event(event, next_id, offsets)
                if any(r['edep'] > 0 for r in event['tables']['stp/germanium']):
                    hits.append(next_id)
                next_id += 1
        require(next_id == index['event_count'] == 10000, 'primary census mismatch')
        require(hits == index['ge_hit_ids'] and index['zero_ge_primaries'] == 10000-len(hits), 'Ge-hit census mismatch')
        require(dict(offsets) == {k: v for k, v in index['raw_rows'].items() if v}, 'raw row census mismatch')
        with zipfile.ZipFile(bundle/model/'originals.zip') as archive:
            require(set(archive.namelist()) == {*ORIGINALS, 'cryostat-source.json'}, 'archive census mismatch')
            for name in ORIGINALS:
                require(archive.read(name) == (SAVED/model/'transport'/name).read_bytes(), 'original bytes changed')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scene-executable', type=Path, default=WORK/'build/geant4_scene')
    parser.add_argument('--output', type=Path, default=WORK/'bundle')
    parser.add_argument('--check-inputs', action='store_true')
    parser.add_argument('--validate-bundle', action='store_true')
    args = parser.parse_args()
    if args.validate_bundle:
        validate_bundle(args.output)
        print('Bundle hashes, census, geometry and original bytes verified.')
    elif args.check_inputs:
        dependencies()
        for model in MODELS:
            inputs(model)
        print('Both saved input chains and all 17 computational dependencies verified.')
    else:
        result = export(args.scene_executable, args.output)
        print(json.dumps({'models': result['models'], 'files': len(result['files']),
                          'bytes': sum(f['bytes'] for f in result['files'].values())}))


if __name__ == '__main__':
    main()
