"""Verify and publish the saved geometry/event bundle, without rerunning physics."""
import hashlib, io, json, re, shutil, zipfile
from collections import Counter
from pathlib import Path
from geometry_events import ORIGINALS, validate_event, validate_scene
ROOT = Path(__file__).resolve().parents[1]
PREFIX = 'examples/cs137-10k-geometry'
PRIVATE = re.compile(rb'[A-Za-z]:[\\/]+Users[\\/]|file:///|/home/[^/\s]+/', re.I)
SECRET = re.compile(rb'BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY|gh[pousr]_[A-Za-z0-9]{25,}|sk-proj-[A-Za-z0-9_-]{25,}')
def check(ok, message):
    if not ok: raise ValueError(message)
def sha(data): return hashlib.sha256(data).hexdigest()
def load(p): return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def safe(data, name):
    check(not PRIVATE.search(data) and not SECRET.search(data), 'Private metadata: '+name)
    data.decode('utf-8-sig')
def archive_contents(data):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        expected = set(ORIGINALS) | {'cryostat-source.json'}
        check(len(z.infolist()) == len(expected) and set(z.namelist()) == expected, 'Geometry ZIP inventory')
        check(sum(i.file_size for i in z.infolist()) < 10*1024**2, 'Geometry ZIP too large')
        check(all(not (i.flag_bits & 1) and (i.external_attr >> 16) & 0o170000 != 0o120000 for i in z.infolist()), 'Unsafe ZIP member')
        files = {name:z.read(name) for name in sorted(expected)}
        for name,body in files.items(): safe(body,name)
        return files

def validate_bundle(folder):
    folder = Path(folder)
    check(not folder.is_symlink(), 'Symlink bundle')
    manifest = load(folder/'manifest.json')
    check(manifest['status']=='complete' and manifest['schema_version']==1, 'Incomplete geometry bundle')
    check(set(manifest['models'])=={'AK02','SAP22'}, 'Model census')
    check(not any(p.is_symlink() for p in folder.rglob('*')), 'Symlink member')
    actual = {p.relative_to(folder).as_posix() for p in folder.rglob('*') if p.is_file()}
    check(actual==set(manifest['files'])|{'manifest.json'}, 'Bundle file inventory')
    for name,meta in manifest['files'].items():
        check(not name.startswith('/') and '\\' not in name and '..' not in Path(name).parts, 'Unsafe file path')
        body = (folder/name).read_bytes()
        check(len(body)==meta['bytes'] and sha(body)==meta['sha256'], 'Bundle hash mismatch: '+name)
        if name.endswith('.zip'): archive_contents(body)
        else: safe(body,name)
    for model in ('AK02','SAP22'):
        record = manifest['models'][model]
        check(record['scene']==model+'/scene.json' and record['originals']==model+'/originals.zip', 'Model file identity')
        scene = load(folder/record['scene']); index = scene['event_index']
        originals = archive_contents((folder/record['originals']).read_bytes())
        for name,expected in scene['originals_sha256'].items():
            check(name in originals and sha(originals[name])==expected, 'Original geometry hash mismatch')
        prepared = json.loads(originals['prepared.json'])
        validate_scene(scene,json.loads(originals['geometry-report.json']),prepared)
        check(scene['model']==model and record['event_count']==index['event_count']==10000, 'Event count')
        check(scene['raw_lh5_sha256']==record['raw_lh5_sha256'], 'Raw LH5 identity')
        check(len(index['chunks'])==100, 'Chunk count')
        offsets = Counter(); hits = []
        for n,chunk in enumerate(index['chunks']):
            name = f'events-{n*100:05d}.json'
            check(chunk['file']==name and chunk['first']==n*100 and chunk['count']==100, 'Chunk identity')
            body = (folder/model/name).read_bytes()
            check(sha(body)==chunk['sha256'], 'Chunk checksum')
            data = json.loads(body)
            check(data['model']==model and data['first']==n*100 and len(data['events'])==100, 'Chunk schema')
            for j,event in enumerate(data['events']):
                validate_event(event,n*100+j,offsets)
                if any(r['edep']>0 for r in event['tables']['stp/germanium']): hits.append(event['event_id'])
        check(dict(offsets)=={k:v for k,v in index['raw_rows'].items() if v}, 'Total raw row census')
        check(index['raw_rows']==record['raw_rows'] and hits==index['ge_hit_ids'], 'Saved row/hit census')
        check(len(hits)==record['ge_hit_count'] and index['zero_ge_primaries']==10000-len(hits), 'Zero-event census')
    return manifest

def assemble(source, target):
    source = Path(source).resolve(strict=True); target = Path(target)
    check(source.is_relative_to((ROOT/'.local').resolve()), 'Source outside local project')
    check(not target.exists(), 'Do not overwrite geometry publication')
    original = validate_bundle(source)
    for name,expected in original['computational_dependency_sha256'].items():
        p = (ROOT/name).resolve(strict=True)
        check(p.is_relative_to(ROOT) and sha(p.read_bytes())==expected, 'Original computational dependency changed')
    shutil.copytree(source,target)
    report = ROOT/'.local/geometry-events-publication/source-efficiency.json'
    audit = load(report)
    check(audit['campaign_sha256']==original['campaign_run_sha256'], 'Efficiency audit source mismatch')
    shutil.copyfile(report,target/'source-efficiency.json')
    shutil.copyfile(ROOT/'tools/SOURCE_GEOMETRY.md',target/'SOURCE_GEOMETRY.md')
    manifest = load(target/'manifest.json')
    for name in ('source-efficiency.json','SOURCE_GEOMETRY.md'):
        body = (target/name).read_bytes(); safe(body,name)
        manifest['files'][name] = {'bytes':len(body),'sha256':sha(body)}
    manifest['publication_additions'] = {'export_manifest_sha256':sha((source/'manifest.json').read_bytes()),
        'publisher_sha256':sha(Path(__file__).read_bytes()),'numerical_records_modified':False}
    (target/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8',newline='\n')
    validate_bundle(target)
    return manifest
