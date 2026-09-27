"""Publish the bounded saved Ge-hit overlay without regenerating old data."""
import gzip, hashlib, io, json, shutil
from pathlib import Path
from native_publication import safe as public_text

MODELS = {'AK02': 121, 'SAP22': 115}
NAMES = {'hit_event_view.html', 'README.md', 'manifest.json'} | {
    model+'/'+name for model in MODELS for name in ('scene.json', 'selected.json.gz')}

def require(ok, message):
    if not ok: raise ValueError(message)

def sha(data): return hashlib.sha256(data).hexdigest()
def read(path): return json.loads(Path(path).read_text(encoding='utf-8'))

def payload(path):
    with gzip.GzipFile(fileobj=io.BytesIO(Path(path).read_bytes())) as stream:
        body = stream.read(64*1024**2+1)
    require(len(body) <= 64*1024**2, 'Oversize hit-view payload')
    public_text(body, 'selected.json.gz (decompressed)')
    return json.loads(body)

def validate(folder):
    folder = Path(folder)
    require(not folder.is_symlink(), 'Linked hit-view bundle')
    require(not any(p.is_symlink() for p in folder.rglob('*')), 'Linked hit-view member')
    actual = {p.relative_to(folder).as_posix() for p in folder.rglob('*') if p.is_file()}
    require(actual == NAMES, 'Unexpected hit-view file inventory')
    meta = read(folder/'manifest.json')
    require(meta['status']=='complete' and set(meta['files'])==NAMES-{'manifest.json'}, 'Incomplete hit-view receipt')
    require(sum(p.stat().st_size for p in folder.rglob('*') if p.is_file()) < 4_100_000, 'Hit-view size exceeded')
    public_text((folder/'manifest.json').read_bytes(), 'hit-view manifest')
    for name, entry in meta['files'].items():
        body = (folder/name).read_bytes()
        require(len(body)==entry['bytes'] and sha(body)==entry['sha256'], 'Changed hit-view artifact: '+name)
        if not name.endswith('.gz'): public_text(body, name)
    require(set(meta['models'])==set(MODELS), 'Hit-view model census')
    for model, count in MODELS.items():
        entry = meta['models'][model]; scene = read(folder/model/'scene.json')
        data = payload(folder/model/'selected.json.gz')
        ids = data['event_ids']; events = data['events']; evidence = data['evidence']
        require(data['model']==scene['model']==model and scene['source_position_global_mm']==[0,37.073,.29], 'Hit-view model/pose mismatch')
        require(ids==scene['event_index']['ge_hit_ids'] and len(ids)==len(events)==len(evidence)==count, 'Hit-view selected census')
        require(ids==sorted(set(ids)) and all(type(i) is int and 0<=i<10000 for i in ids), 'Hit-view duplicate/foreign ID')
        require([e['event_id'] for e in events]==ids==[e['event_id'] for e in evidence], 'Hit-view event/evidence identity')
        require(entry['selected_count']==count and sha((folder/model/'scene.json').read_bytes())==entry['source_scene_sha256'], 'Hit-view scene/census binding')
        columns = {k:['raw_row_index',*v] for k,v in scene['event_index']['raw_columns'].items()}
        require(data['columns']==columns, 'Hit-view original column mismatch')
        for event in events:
            for table, rows in event['tables'].items():
                require(table in columns and all(len(r)==len(columns[table]) for r in rows), 'Hit-view row schema')
                j = columns[table].index('evtid')
                require(all(r[j]==event['event_id'] for r in rows), 'Hit-view mixed event rows')
            ge = event['tables'].get('stp/germanium',[]); j = columns['stp/germanium'].index('edep')
            require(any(r[j]>0 for r in ge), 'Nonpositive event in hit-view population')
        require(set(data['categories'])==set(meta['category_labels']), 'Hit-view category names')
        for category, members in data['categories'].items():
            expected = [{'event_id': e['event_id'], 'group_id': g['group_id']} for e in evidence
                        for g in e['groups'] if category in g['categories']]
            require(members==expected and entry['category_group_counts'][category]==len(members), 'Hit-view category census')
            representative = data['representatives'][category]
            require((representative in members) if members else representative is None, 'Fabricated hit-view representative')
    return meta

def assemble(source, destination):
    from hit_event_view import validate as validate_originals
    source, destination = Path(source), Path(destination)
    require(not destination.exists(), 'Hit-view target already exists')
    # This one-time publication audit recomputes classification from immutable inputs.
    validate_originals(source)
    validate(source)
    shutil.copytree(source, destination)
    return validate(destination)
