"""Publish the verified 1M native-response summary without raw checkpoints or private paths."""
import copy,csv,gzip,hashlib,json,re,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
COPY=('report.html','summary.json','histograms.json','histograms.csv','groups.csv.gz')
# Exact installed/Git publication before the October 22 cross-study link repair.
ARCHIVE_PUBLICATION_SHA='b2cbd14d37ba5b1bb0e15d39efb28808f06b63e14d6de04bd947e5ccac24cff5'
ARCHIVE_REPORT={'bytes':52506,'sha256':'4de4b264f6df246982b3991bb1cedf3d5eefcf26aa9726e1379e0e511f135b77'}
ARCHIVE_PUBLISHER_SHA='c23d695c8d5a24da0175902346dc313b3cc6a48c83bfe6772f3772ecf372b47e'
ARCHIVE_TRUTH_PUBLICATION_SHA='e829d66bbf4f315d6dc8b26db921932a7112f98bc08d5cae42eddb9a5553003d'
ORIGINAL_NAV='<nav><a href="../cs137-1m/report.html">1M Geant4 deposition truth</a> | <a href="../cs137-10k-hits/hit_event_view.html">3D Ge-hit examples</a> | <a href="summary.json">Response summary</a> | <a href="groups.csv.gz">All group scalars</a></nav>'
ARCHIVE_NAV=('<nav><a href="../../results/cs137-1m/index.html">1M study overview</a> | '
    '<a data-original-report href="../cs137-1m/report.html">1M Geant4 deposition truth</a> | '
    '<a href="../cs137-10k-hits/hit_event_view.html">Independent Cs137 10K study · 3D examples</a> | '
    '<a href="summary.json">Response summary</a> | <a href="groups.csv.gz">All group scalars</a></nav>'
    '<p class="note">The linked 3D examples belong to the independent Cs137 10K study; '
    'they are not part of this 1M-per-detector study.</p>')
PRIVATE=re.compile(rb'[A-Za-z]:[\\/]+Users[\\/]|file:///|/home/[^/\s]+/|gh[pousr]_[A-Za-z0-9]{25,}|sk-proj-[A-Za-z0-9_-]{25,}')
def require(ok,msg):
    if not ok:raise ValueError(msg)
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def write(p,x):
    with Path(p).open('x',encoding='utf-8',newline='\n') as f:json.dump(x,f,indent=2,allow_nan=False);f.write('\n')
def safe(path):
    p=Path(path);data=gzip.decompress(p.read_bytes()) if p.suffix=='.gz' else p.read_bytes()
    require(not PRIVATE.search(data),'Private metadata: '+p.name)
    return data

def archive_report(raw):
    """Change only the known archive navigation, preserving the exact report body."""
    text=raw.decode('utf-8')
    if hashlib.sha256(raw).hexdigest()==ARCHIVE_REPORT['sha256']:
        require(len(raw)==ARCHIVE_REPORT['bytes'] and text.count(ORIGINAL_NAV)==1,
                'Original response archive navigation changed')
        return text.replace(ORIGINAL_NAV,ARCHIVE_NAV,1).encode('utf-8')
    require(text.count(ARCHIVE_NAV)==1,'Response archive navigation differs')
    original=text.replace(ARCHIVE_NAV,ORIGINAL_NAV,1).encode('utf-8')
    require({'bytes':len(original),'sha256':hashlib.sha256(original).hexdigest()}==ARCHIVE_REPORT,
            'Original response archive differs')
    return raw

def validate_archive_navigation(folder,manifest):
    folder=Path(folder);raw=(folder/'report.html').read_bytes()
    original=copy.deepcopy(manifest);extension=original.pop('archive_navigation',None)
    original['publisher_sha256']=ARCHIVE_PUBLISHER_SHA
    original['files']['report.html']={'sha256':ARCHIVE_REPORT['sha256'],'bytes':ARCHIVE_REPORT['bytes']}
    encoded=(json.dumps(original,indent=2,allow_nan=False)+'\n').encode('utf-8')
    require(hashlib.sha256(encoded).hexdigest()==ARCHIVE_PUBLICATION_SHA,
            'Original response publication binding changed')
    if extension is not None:
        require(manifest['publisher_sha256']==ARCHIVE_PUBLISHER_SHA,'Original response publisher binding changed')
        require(extension=={'kind':'million_response_archive_navigation_v1','science_calls':0,
            'original_publication_sha256':ARCHIVE_PUBLICATION_SHA,
            'source_sha256':sha(__file__)},'Response archive navigation binding changed')
        require(raw==archive_report(raw),'Response archive navigation differs')
    elif sha(folder/'publication.json')==ARCHIVE_PUBLICATION_SHA:
        require({'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}==ARCHIVE_REPORT,
                'Original response archive differs')
    else:
        require(manifest['publisher_sha256']==sha(__file__),'Unknown response publication predecessor')
        require(raw==archive_report(raw),'Response archive navigation differs')

def response_extension_pointer(folder,upgrade=False):
    """Keep the existing truth-to-response display pointer on this exact study."""
    folder=Path(folder);path=folder.parent/'cs137-1m/publication.json'
    if not path.exists():return False
    manifest=read(path);original=copy.deepcopy(manifest)
    extension=original['native_response_extension']
    extension.pop('original_response_publication_sha256',None)
    extension['publication_sha256']=ARCHIVE_PUBLICATION_SHA
    encoded=(json.dumps(original,indent=2,allow_nan=False)+'\n').encode('utf-8')
    require(hashlib.sha256(encoded).hexdigest()==ARCHIVE_TRUTH_PUBLICATION_SHA,
            'Original truth publication binding changed')
    current=sha(folder/'publication.json')
    expected={'publication_sha256':current,'original_truth_artifacts_modified':False}
    if 'archive_navigation' in read(folder/'publication.json'):
        expected['original_response_publication_sha256']=ARCHIVE_PUBLICATION_SHA
    if upgrade and manifest['native_response_extension']!=expected:
        require(manifest['native_response_extension']=={
            'publication_sha256':ARCHIVE_PUBLICATION_SHA,'original_truth_artifacts_modified':False},
            'Unknown truth-to-response publication pointer')
        manifest['native_response_extension']=expected
        path.write_text(json.dumps(manifest,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    require(read(path)['native_response_extension']==expected,'Truth-to-response publication pointer differs')
    return expected

def upgrade_archive_navigation(folder):
    """Migrate the exact prior publication in staging, without touching its data."""
    folder=Path(folder)
    if not folder.exists():return False
    manifest=validate(folder);page=folder/'report.html';raw=page.read_bytes();output=archive_report(raw)
    if raw==output:return manifest
    response_extension_pointer(folder)
    require(sha(folder/'publication.json')==ARCHIVE_PUBLICATION_SHA,'Unknown response publication predecessor')
    manifest['files']['report.html']={'sha256':hashlib.sha256(output).hexdigest(),'bytes':len(output)}
    manifest['archive_navigation']={'kind':'million_response_archive_navigation_v1','science_calls':0,
        'original_publication_sha256':ARCHIVE_PUBLICATION_SHA,'source_sha256':sha(__file__)}
    page.write_bytes(output)
    (folder/'publication.json').write_text(json.dumps(manifest,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    response_extension_pointer(folder,upgrade=True)
    return validate(folder)
def validate_source(source):
    source=Path(source).resolve();require(source.is_relative_to((ROOT/'.local').resolve()),'Source outside .local')
    complete=read(source/'COMPLETE.json');require(complete['status']=='verified_native_response_report','Report incomplete')
    require(set(complete['files'])==set(COPY),'Unexpected local report inventory')
    for name,e in complete['files'].items():
        p=source/name;require(p.is_file() and not p.is_symlink(),'Missing/linked source')
        require(sha(p)==e['sha256'] and p.stat().st_size==e['bytes'],'Changed local report file');safe(p)
    summary=read(source/'summary.json');require(summary['status']=='completed_response_comparison','Summary status')
    require(summary['totals']=={'accepted':21672,'groups':23693,'native_completed':23285,'native_failed':408,'readout_rejected':1613},'Final response totals')
    seen=set()
    with gzip.open(source/'groups.csv.gz','rt',encoding='utf-8',newline='') as f:
        for row in csv.DictReader(f):
            key=(row['model'],int(row['event_id']),int(row['group_id']))
            require(key not in seen,'Duplicate public group');seen.add(key)
    require(len(seen)==23693,'Public scalar census')
    return complete,summary
def assemble(source,target):
    source=Path(source).resolve();target=Path(target);complete,summary=validate_source(source)
    require(not target.exists(),'Public response folder exists');target.mkdir(parents=True)
    for name in COPY:shutil.copyfile(source/name,target/name)
    page=target/'report.html';text=page.read_text(encoding='utf-8')
    text=text.replace('<h1>',ARCHIVE_NAV+'<h1>',1);page.write_text(text,encoding='utf-8',newline='\n')
    manifest={'kind':'million_native_response_publication_v1','source_complete_sha256':sha(source/'COMPLETE.json'),
        'source_summary_sha256':sha(source/'summary.json'),'publisher_sha256':sha(__file__),
        'scope':'Verified saved Geant4 truth joined to native SSD and synthetic peak ADC; no raw checkpoints or physics rerun.',
        'files':{}}
    for p in sorted(target.iterdir()):
        safe(p);manifest['files'][p.name]={'sha256':sha(p),'bytes':p.stat().st_size}
    write(target/'publication.json',manifest);validate(target);return manifest
def validate(folder):
    folder=Path(folder);m=read(folder/'publication.json')
    require(m['kind']=='million_native_response_publication_v1','Publication kind')
    require(not folder.is_symlink() and not any(p.is_symlink() for p in folder.rglob('*')),'Linked public output')
    require({p.name for p in folder.iterdir()}==set(m['files'])|{'publication.json'},'Public inventory')
    for name,e in m['files'].items():
        require(Path(name).name==name,'Unsafe public filename');p=folder/name
        require(sha(p)==e['sha256'] and p.stat().st_size==e['bytes'],'Changed public artifact');safe(p)
    validate_archive_navigation(folder,m)
    if 'archive_navigation' in m:response_extension_pointer(folder)
    s=read(folder/'summary.json');require(s['totals']['groups']==23693 and s['totals']['accepted']==21672,'Public summary counts')
    h=read(folder/'histograms.json')
    for model in ('AK02','SAP22'):
        r=s['models'][model]['response']
        require(h[model]['deposited_truth']['total']==r['groups'],'Truth histogram census')
        require(h[model]['native_induced']['total']==r['native_completed'],'Native histogram census')
        require(h[model]['reconstructed_accepted']['total']==r['accepted'],'ADC histogram census')
    counts={}
    with (folder/'histograms.csv').open(encoding='utf-8',newline='') as f:
        for row in csv.DictReader(f):
            key=(row['model'],row['stage']);counts[key]=counts.get(key,0)+int(row['count'])
    for model,stages in h.items():
        for stage,data in stages.items():require(counts[(model,stage)]==data['total'],'Histogram CSV flow census')
    seen=set()
    with gzip.open(folder/'groups.csv.gz','rt',encoding='utf-8',newline='') as f:
        for row in csv.DictReader(f):
            key=(row['model'],int(row['event_id']),int(row['group_id']));require(key not in seen,'Duplicate public scalar');seen.add(key)
    require(len(seen)==23693,'Public group census')
    return m
if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('target',type=Path)
    a=p.parse_args();print(json.dumps(assemble(a.source,a.target),indent=2))
