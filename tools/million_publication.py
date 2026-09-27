"""Publish checked saved-data summaries only; no simulation or large raw archive copy."""
import csv, gzip, hashlib, json, re, shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
MODELS=('AK02','SAP22')
COPY=('report.html','histograms.csv','histograms.json','representative-events.json','positive-groups.csv.gz')
PRIVATE=re.compile(rb'[A-Za-z]:[\\/]+Users[\\/]|file:///|/home/[^/\s]+/|gh[pousr]_[A-Za-z0-9]{25,}|sk-proj-[A-Za-z0-9_-]{25,}')
def require(ok,msg):
    if not ok: raise ValueError(msg)
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p): return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def write(p,x):
    with Path(p).open('x',encoding='utf-8',newline='\n') as f:json.dump(x,f,indent=2,allow_nan=False); f.write('\n')
def safe(p):
    b=gzip.decompress(p.read_bytes()) if p.suffix=='.gz' else p.read_bytes()
    require(not PRIVATE.search(b),'Private metadata in '+p.name)
    return b

def checked_group(row):
    import math
    evidence=json.loads(row['evidence_json']); g=evidence['group']
    energy=float(row['ge_energy_keV']); categories=row['categories'].split('|')
    require(math.isfinite(energy) and energy>0 and energy==g['ge_energy_keV'],'CSV/evidence energy mismatch')
    require(int(row['group_id'])==g['group_id'] and categories==g['categories'],'CSV/evidence identity/category mismatch')
    photon=None if row['source_photon_energy_keV']=='' else float(row['source_photon_energy_keV'])
    require(photon==g['source_photon_energy_keV'],'CSV/evidence photon mismatch')
    error=evidence.get('classifier_error'); expected='failed_unknown' if error is not None else 'returned'
    require(row['classifier_status']==expected,'CSV/evidence classifier status mismatch')
    require(sum(k in categories for k in ('full','partial','unknown'))==1,'Energy classes do not partition')
    require(error is None or categories==['unknown'],'Failed classification not unknown')
    return energy

def check_bins(values,h,zeros=0):
    import bisect,math
    edges=h['edges_keV']; counts=[0]*(len(edges)-1); under=over=0
    require(len(edges)>1 and all(math.isfinite(x) for x in edges) and all(a<b for a,b in zip(edges,edges[1:])),'Histogram edges')
    for v in values:
        require(math.isfinite(v),'Nonfinite public energy')
        if v==0: zeros+=1
        elif v<edges[0]: under+=1
        elif v>=edges[-1]: over+=1
        else: counts[bisect.bisect_right(edges,v)-1]+=1
    require((counts,zeros,under,over)==(h['counts'],h['exact_zero'],h['underflow'],h['overflow']),'Histogram bin/evidence mismatch')

def assemble(source,target):
    from analyze_million import verify_output
    source=Path(source).resolve(); target=Path(target)
    require(source.is_relative_to((ROOT/'.local').resolve()),'Source outside project')
    require(not target.exists(),'Public destination exists')
    complete=read(source/'COMPLETE.json'); summary=read(source/'summary.json')
    require(complete['status']=='verified_saved_data_analysis' and complete['summary_sha256']==sha(source/'summary.json'),'Analysis completion binding')
    verify_output(source)
    audit=read(ROOT/'.local/million-analysis/preservation/audit.json')
    require(audit['status']=='verified' and audit['verified_chunks']==200,'Missing full preservation audit')
    require(audit['complete_sha256']==read(source/'provenance.json')['complete_sha256'],'Analysis/audit source mismatch')
    target.mkdir(parents=True)
    for name in COPY:
        p=source/name; require(not p.is_symlink(),'Linked source'); safe(p); shutil.copyfile(p,target/name)
    public={k:v for k,v in summary.items() if k not in ('command','files')}
    public['source_summary_sha256']=sha(source/'summary.json')
    public['publication_scope']='Deposition truth, not SSD/ADC. Local all-event HDF5 and all200 complete raw archives remain preserved; public files are summaries, every positive-group classification, and selected representative raw events.'
    write(target/'summary.json',public)
    write(target/'preservation.json',{k:audit[k] for k in ('status','verified_chunks','completed_decays','models','config_sha256','complete_sha256','decompressed_raw_bytes','original_files_deleted','original_files_modified','chunks','reproducibility_snapshot_sha256','backup_scope')})
    page=target/'report.html'; text=page.read_text(encoding='utf-8')
    links='<nav><a href="../cs137-10k/comparison.html">Earlier 10k full response</a> | <a href="../cs137-10k-hits/hit_event_view.html">Earlier 10k 3D examples</a> | <a href="histograms.csv">1M deposition histograms</a> | <a href="positive-groups.csv.gz">All positive-group classifications (gzip CSV)</a> | <a href="representative-events.json">1M representative records</a> | <a href="summary.json">Summary</a> | <a href="preservation.json">Archive audit</a></nav>'
    if '<body>' in text: text=text.replace('<body>','<body>'+links,1)
    else: text+=links
    page.write_text(text,encoding='utf-8',newline='\n')
    manifest=dict(kind='million_publication_v1',source_summary_sha256=public['source_summary_sha256'],publisher_sha256=sha(__file__),files={})
    for p in sorted(target.iterdir()):
        safe(p); manifest['files'][p.name]={'sha256':sha(p),'bytes':p.stat().st_size}
    write(target/'publication.json',manifest); validate(target)
    return manifest

def validate(folder):
    folder=Path(folder); manifest=read(folder/'publication.json')
    require(manifest['kind']=='million_publication_v1','Public schema')
    require(not folder.is_symlink() and not any(p.is_symlink() for p in folder.rglob('*')),'Linked public data')
    require({p.name for p in folder.iterdir()}==set(manifest['files'])|{'publication.json'},'Public inventory')
    for name,entry in manifest['files'].items():
        require(Path(name).name==name,'Unsafe public name'); p=folder/name
        require(sha(p)==entry['sha256'] and p.stat().st_size==entry['bytes'],'Changed public artifact'); safe(p)
    summary=read(folder/'summary.json'); hist=read(folder/'histograms.json'); audit=read(folder/'preservation.json')
    require(summary['status']=='completed_saved_data_analysis','Incomplete analysis')
    require(summary['source_summary_sha256']==manifest['source_summary_sha256'],'Summary binding')
    seen={m:set() for m in MODELS}; groups={m:set() for m in MODELS}
    from collections import Counter
    categories={m:Counter() for m in MODELS}
    energy_by_id={m:{} for m in MODELS}; group_energies={m:[] for m in MODELS}
    with gzip.open(folder/'positive-groups.csv.gz','rt',encoding='utf-8',newline='') as f:
        for r in csv.DictReader(f):
            m=r['model']; gid=int(r['global_decay_id']); key=(gid,int(r['group_id']))
            require(m in MODELS and 0<=gid<summary['models'][m]['initial_decays'],'Public global ID')
            require(gid==int(r['global_offset'])+int(r['local_event_id']),'Public local/global map')
            require(key not in groups[m],'Duplicate public group'); groups[m].add(key); seen[m].add(gid)
            categories[m].update(r['categories'].split('|'))
            energy=checked_group(r); group_energies[m].append(energy)
            energy_by_id[m].setdefault(gid,[]).append(energy)
    for m in MODELS:
        s=summary['models'][m]
        import math
        per_decay=[math.fsum(v) for v in energy_by_id[m].values()]
        check_bins(group_energies[m],hist[m]['per_isolated_group'])
        check_bins(per_decay,hist[m]['positive_initial_decay'])
        check_bins(per_decay,hist[m]['per_initial_decay'],s['zero_ge_decays'])
        require(s['initial_decays']==audit['models'][m]['decays'] and s['positive_ge_decays']==audit['models'][m]['ge_positive'],'Audit/analysis census')
        require(len(seen[m])==s['positive_ge_decays'] and len(groups[m])==s['isolated_groups'],'Public classification census')
        require({k:categories[m][k] for k in s['category_group_counts']}==s['category_group_counts'],'Public category counts')
        for pop,n in (('per_initial_decay',s['initial_decays']),('positive_initial_decay',len(seen[m])),('per_isolated_group',len(groups[m]))):
            h=hist[m][pop]
            require(all(type(x) is int and x>=0 for x in h['counts']),'Invalid histogram counts')
            require(sum(h['counts'])+h['exact_zero']+h['underflow']+h['overflow']==h['total']==n,'Public histogram census')
    return manifest
