"""Publish the verified 1M native-response summary without raw checkpoints or private paths."""
import csv,gzip,hashlib,json,re,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
COPY=('report.html','summary.json','histograms.json','histograms.csv','groups.csv.gz')
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
    nav='<nav><a href="../cs137-1m/report.html">1M Geant4 deposition truth</a> | <a href="../cs137-10k-hits/hit_event_view.html">3D Ge-hit examples</a> | <a href="summary.json">Response summary</a> | <a href="groups.csv.gz">All group scalars</a></nav>'
    text=text.replace('<h1>',nav+'<h1>',1);page.write_text(text,encoding='utf-8',newline='\n')
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
