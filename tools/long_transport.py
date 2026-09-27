"""Resumable default-angle Cs137 transport only; never invokes SSD/readout."""
import argparse, contextlib, gzip, hashlib, html, json, math, os, re, shutil, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path
import h5py
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'transport'))
import cs137 as cs
OLD=ROOT/'.local/peak-native-delivery/cs10000-v2'
MODELS=('AK02','SAP22')
INPUTS=('geometry.gdml','run.mac','prepared.json','geometry-report.json','scenario.json')
SOURCES=('tools/long_transport.py','tools/Start-Transport.ps1','tools/Monitor-Transport.ps1')

def check(ok,message):
    if not ok: raise ValueError(message)
def utc(): return datetime.now(timezone.utc).isoformat()
def read(p): return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()
def local(p):
    p=Path(p).absolute(); base=(ROOT/'.local').resolve()
    check(p.resolve().is_relative_to(base) and p.resolve()!=base,'Output must be below project .local')
    check(not any(x.is_symlink() for x in (p,*p.parents)),'Linked paths refused')
    return p.resolve()
def syncdir(p):
    if os.name=='posix':
        fd=os.open(p,os.O_RDONLY)
        try: os.fsync(fd)
        finally: os.close(fd)

def atomic(p,value):
    p=Path(p); tmp=p.with_name(p.name+'.tmp-'+str(os.getpid())+'-'+str(time.time_ns()))
    body=json.dumps(value,indent=2,allow_nan=False).encode()+b'\n'
    with tmp.open('xb') as f: f.write(body); f.flush(); os.fsync(f.fileno())
    os.replace(tmp,p); syncdir(p.parent)
def file_atomic(p,body):
    p=Path(p); tmp=p.with_name(p.name+'.tmp-'+str(os.getpid()))
    with tmp.open('wb') as f: f.write(body); f.flush(); os.fsync(f.fileno())
    os.replace(tmp,p); syncdir(p.parent)

def dependencies():
    old=read(OLD/'run.json'); hashes=old['source_sha256']
    check(all(sha(ROOT/n)==v for n,v in hashes.items()),'Frozen scientific dependency changed')
    return {**hashes,**{n:sha(ROOT/n) for n in SOURCES}}
def seed_for(base,model,index):
    h=hashlib.sha256(f'{base}/{model}/{index}'.encode()).digest()
    return 1+int.from_bytes(h[:8],'big')%2147483646
def plan(c):
    rows=[]
    for m in MODELS:
        for i,start in enumerate(range(0,c['events_per_model'],c['chunk_size'])):
            rows.append(dict(model=m,index=i,start=start,count=min(c['chunk_size'],c['events_per_model']-start),seed=seed_for(c['seed'],m,i)))
    check(len({r['seed'] for r in rows})==len(rows),'Seed collision; choose a different campaign seed')
    return rows

def prepare(directory,events=1000000,chunk_size=10000,seed=26092701):
    directory=local(directory)
    check(not directory.exists(),'Campaign already exists; use run to resume')
    check(type(events) is int and 1<=events<=1000000,'Invalid per-model count')
    check(type(chunk_size) is int and 1<=chunk_size<=10000,'Chunk size must be 1..10000')
    check(type(seed) is int and 0<seed<2147483647,'Invalid seed')
    c=dict(kind='long_cs137_transport_v1',events_per_model=events,chunk_size=chunk_size,seed=seed,
           models=list(MODELS),created_utc=utc(),source_sha256=dependencies(),templates={},
           scope='Default uncollimated Cs137; identical saved geometry/cuts; Geant4 only; awaits later analysis',
           storage='Compact gzip/shuffle/Fletcher32 HDF5 plus bit-exact original LH5.gz; no giant JSON expansion')
    plan(c); directory.mkdir()
    for m in MODELS:
        source,meta=cs.read_prepared(OLD/m/'transport')
        target=directory/'inputs'/m; target.mkdir(parents=True)
        c['templates'][m]={}
        for name in INPUTS:
            shutil.copyfile(source/name,target/name)
            c['templates'][m][name]=sha(target/name)
    atomic(directory/'config.json',c)
    file_atomic(directory/'config.sha256',(sha(directory/'config.json')+'\n').encode())
    write_progress(directory,c,'prepared',0,{},None,0,0)
    return c

def config(directory):
    directory=local(directory); c=read(directory/'config.json')
    check(sha(directory/'config.json')==(directory/'config.sha256').read_text().strip(),'Campaign configuration changed')
    check(c['kind']=='long_cs137_transport_v1' and c['models']==list(MODELS),'Unknown campaign kind/models')
    check(c['source_sha256']==dependencies(),'Implementation changed; do not silently rebaseline a campaign')
    check(1<=c['events_per_model']<=1000000 and 1<=c['chunk_size']<=10000,'Invalid campaign bounds')
    for m in MODELS:
        check(set(c['templates'][m])==set(INPUTS),'Template inventory changed')
        for n,h in c['templates'][m].items():
            p=local(directory/'inputs'/m/n)
            check(sha(p)==h==sha(OLD/m/'transport'/n),'Input no longer matches saved physical setup')
    plan(c); return c

@contextlib.contextmanager
def locked(directory):
    check(os.name=='posix','Run transport in the pinned WSL environment')
    import fcntl
    path=local(directory/'.run.lock')
    with path.open('a+b') as handle:
        try: fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: raise RuntimeError('This campaign already has a running worker')
        handle.seek(0); handle.truncate(); handle.write(str(os.getpid()).encode()); handle.flush()
        try: yield handle
        finally: fcntl.flock(handle,fcntl.LOCK_UN)

def runtime():
    versions={n:subprocess.check_output([n,'--version'],text=True).strip() for n in ('remage','geant4-config')}
    check(versions=={'remage':'1.1.0','geant4-config':'11.3.2'},'Pinned runtime version mismatch')
    return dict(versions=versions,data=cs.installed_data(),python=sys.version,
                executable_sha256={n:sha(shutil.which(n)) for n in versions})

def write_progress(directory,c,status,completed,models,current,elapsed,new_completed,error=None):
    total=2*c['events_per_model']; rate=new_completed/elapsed if elapsed>0 and new_completed else None
    record=dict(kind=c['kind'],status=status,heartbeat_utc=utc(),worker_pid=os.getpid(),
                completed_decays=completed,target_decays=total,percent=100*completed/total,
                models=models,current_chunk=current,active_session_seconds=elapsed,
                verified_decays_per_second=rate,eta_seconds=(total-completed)/rate if rate else None,
                error=error,unit='initial Cs137 decays; no SSD/readout',
                checkpoint_rule='Only verified DONE chunks count. At most an incomplete chunk may repeat.')
    atomic(directory/'progress.json',record)
    text=f"Cs137 Geant4 only: {status}\nVerified: {completed:,} / {total:,} decays ({record['percent']:.2f}%)\nUpdated UTC: {record['heartbeat_utc']}\n"
    for m in MODELS: text+=m+': '+json.dumps(models.get(m,{}))+'\n'
    text+='Current: '+json.dumps(current)+'\n'
    if rate: text+=f'Verified throughput: {rate:.1f} decays/s; estimated remaining {record["eta_seconds"]/60:.1f} min (not guaranteed)\n'
    if error: text+='ERROR: '+error+'\n'
    text+='To pause safely, create STOP_AFTER_CHUNK in this folder. To resume, remove that marker and use Start-Transport.ps1.\n'
    file_atomic(directory/'progress.txt',text.encode())
    page='<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width"><meta http-equiv="refresh" content="5"><title>Cs137 progress</title>'
    page+='<style>body{font:17px/1.6 system-ui;max-width:1000px;margin:auto;padding:20px}pre{white-space:pre-wrap;overflow-wrap:anywhere}progress{width:100%;height:26px}</style>'
    page+=f'<h1>Cs137 transport progress</h1><progress value="{completed}" max="{total}"></progress><pre>{html.escape(text)}</pre><p id="age"></p>'
    page+='<script>const t='+json.dumps(record['heartbeat_utc'])+';const age=(Date.now()-Date.parse(t))/1000;document.getElementById("age").textContent="Heartbeat age: "+Math.round(age)+" s. "+(age>90?"A stale heartbeat is not proof the job is still running. Check the monitor before resuming.":"");</script>'
    file_atomic(directory/'progress.html',page.encode())

def dataset(group,name,data,attrs=None):
    d=group.create_dataset(name,data=data,compression='gzip',compression_opts=4,shuffle=True,fletcher32=True)
    if attrs:
        for k,v in attrs.items(): d.attrs[k]=v
    return d

def selections(raw,meta,positive):
    geids=raw['stp/germanium/evtid'][:]
    retained=np.unique(geids)
    keys=['vtx','particles','tracks',*sorted(meta['material_tables'])]
    result={}
    for key in keys:
        ids=raw[key+'/evtid'][:]
        if key in ('vtx','particles','stp/germanium'): mask=np.ones(len(ids),dtype=bool)
        elif key=='tracks': mask=np.isin(ids,retained)
        else: mask=np.isin(ids,np.flatnonzero(positive))
        result[key]=np.flatnonzero(mask)
    return result

def compact(rawfile,meta,outfile,offset=0,tick=lambda:None):
    check(not Path(outfile).exists(),'Compact output already exists')
    n=meta['primary_count']; materials=sorted(set(meta['material_tables'].values()))
    ge=np.zeros(n); photons=np.zeros(n,dtype=np.int64); line=np.zeros(n,dtype=np.int64)
    material=np.zeros((n,len(materials))); visited=0
    for e in cs.iter_decays(rawfile,meta):
        i=e['event_id']; check(i==visited,'Noncontiguous raw census'); visited+=1
        ge[i]=math.fsum(s['energy_keV'] for s in e['steps'])
        photons[i]=e['decay_photon_count']; line[i]=e['line_photon_count']
        material[i]=[e['material_energy_keV'][name] for name in materials]
        if i%250==0: tick()
    check(visited==n,'Incomplete raw census'); positive=ge>0
    with h5py.File(rawfile,'r') as raw,h5py.File(outfile,'x') as out:
        out.attrs.update(kind='compact_cs137_transport_v1',raw_sha256=sha(rawfile),global_offset=offset,
                         primary_count=n,model_id=meta['model_id'],metadata_json=json.dumps(meta))
        ledger=out.create_group('events')
        values={'local_event_id':np.arange(n),'global_decay_id':np.arange(offset,offset+n),
                'ge_energy_keV':ge,'has_ge_energy':positive,'decay_photons':photons,
                'line_photons':line,'material_energy_keV':material}
        for name,value in values.items(): dataset(ledger,name,value)
        ledger['ge_energy_keV'].attrs['units']='keV'
        ledger['material_energy_keV'].attrs['units']='keV'
        ledger['material_energy_keV'].attrs['materials_json']=json.dumps(materials)
        out.attrs['selection']='All primary records and all Ge steps; Ge-crossing track histories; Ge-positive passive steps. Other detail is archived without loss.'
        raw.copy('processes',out)
        for key,indices in selections(raw,meta,positive).items():
            target=out.require_group('details/'+key)
            for k,v in raw[key].attrs.items(): target.attrs[k]=v
            parts=key.split('/')
            parent='row_maps'+('/'+'/'.join(parts[:-1]) if len(parts)>1 else '')
            dataset(out.require_group(parent),parts[-1],indices)
            for name,source in raw[key].items():
                dataset(target,name,source[:][indices],source.attrs)
            tick()
        out.flush()
    with Path(outfile).open('rb') as f: os.fsync(f.fileno())
    verify_compact(rawfile,meta,outfile,offset)
    return dict(decays=n,ge_positive=int(positive.sum()),decay_photons=int(photons.sum()),line_photons=int(line.sum()))

# Verify local simulation-table copies, including exact numeric representation.
def equal_dataset(source,target,indices):
    left=source[:][indices]
    right=target[:]
    check(left.dtype==right.dtype,'Compact numeric dtype changed')
    check(left.tobytes()==right.tobytes(),'Compact numeric values changed')
    check(set(source.attrs)==set(target.attrs),'Compact attribute inventory mismatch')
    for key in source.attrs:
        check(np.array_equal(source.attrs[key],target.attrs[key]),'Compact units/attributes changed')

def verify_compact(rawfile,meta,outfile,offset=0):
    n=meta['primary_count']
    with h5py.File(rawfile,'r') as raw,h5py.File(outfile,'r') as out:
        check(out.attrs['raw_sha256']==sha(rawfile),'Compact source binding')
        check(out.attrs['primary_count']==n,'Compact primary count')
        ledger=out['events']; ids=raw['stp/germanium/evtid'][:]
        ge=np.bincount(ids,weights=raw['stp/germanium/edep'][:],minlength=n)
        positive=ge>0
        check(np.array_equal(ledger['global_decay_id'][:],np.arange(offset,offset+n)),'Global IDs lost/duplicated')
        check(np.array_equal(ledger['local_event_id'][:],np.arange(n)),'Local IDs lost/duplicated')
        check(np.array_equal(ledger['has_ge_energy'][:],positive),'Zero-Ge census changed')
        check(np.allclose(ledger['ge_energy_keV'][:],ge,rtol=1e-12,atol=1e-10),'Ge scalar energy sum mismatch')
        mats=json.loads(ledger['material_energy_keV'].attrs['materials_json'])
        expected=np.zeros((n,len(mats)))
        for key,mat in meta['material_tables'].items():
            expected[:,mats.index(mat)]+=np.bincount(raw[key+'/evtid'][:],weights=raw[key+'/edep'][:],minlength=n)
        check(np.allclose(expected,ledger['material_energy_keV'][:],rtol=1e-12,atol=1e-10),'Material energy sum mismatch')
        for key,indices in selections(raw,meta,positive).items():
            check(np.array_equal(out['row_maps/'+key][:],indices),'Original row map mismatch')
            check(set(out['details/'+key])==set(raw[key]),'Original column inventory mismatch')
            for name,ds in raw[key].items():
                equal_dataset(ds,out['details/'+key+'/'+name],indices)
        for key,ds in raw['processes'].items():
            check(np.array_equal(ds[...],out['processes/'+key][...]),'Process map changed')
        processes={p['procid']:p['name'] for p in cs.table_rows(raw['processes'])}
        tracks=raw['tracks']; particle=tracks['particle'][:]; event=tracks['evtid'][:]
        emitted=(particle==22)&np.array(['radioactivedecay' in processes.get(int(p),'').lower() for p in tracks['procid'][:]])
        energies=tracks['ekin'][:]*1000; window=meta.get('decay_photon_line_window_keV',[660,663])
        in_line=emitted&(energies>=window[0])&(energies<=window[1])
        check(np.array_equal(ledger['decay_photons'][:],np.bincount(event[emitted],minlength=n)),'Emission denominator mismatch')
        check(np.array_equal(ledger['line_photons'][:],np.bincount(event[in_line],minlength=n)),'Line denominator mismatch')
    return True

def compact_counts(file):
    with h5py.File(file,'r') as f:
        e=f['events']
        return dict(decays=len(e['local_event_id']),ge_positive=int(e['has_ge_energy'][:].sum()),decay_photons=int(e['decay_photons'][:].sum()),line_photons=int(e['line_photons'][:].sum()))

def verify_archive(file,expected_hash,expected_bytes):
    h=hashlib.sha256(); size=0
    with gzip.open(file,'rb') as f:
        for body in iter(lambda:f.read(1024*1024),b''):
            h.update(body); size+=len(body)
    check(size==expected_bytes and h.hexdigest()==expected_hash,'Lossless raw archive verification failed')

def archive_raw(rawfile,archive):
    expected_hash=sha(rawfile); size=Path(rawfile).stat().st_size
    if not Path(archive).exists():
        temp=Path(str(archive)+'.partial-'+str(time.time_ns()))
        with temp.open('xb') as dst:
            with gzip.GzipFile(fileobj=dst,mode='wb',compresslevel=4,mtime=0) as zipped:
                with Path(rawfile).open('rb') as src: shutil.copyfileobj(src,zipped,1024*1024)
            dst.flush(); os.fsync(dst.fileno())
        verify_archive(temp,expected_hash,size)
        os.replace(temp,archive); syncdir(Path(archive).parent)
    verify_archive(archive,expected_hash,size)
    return dict(raw_sha256=expected_hash,raw_bytes=size,archive_sha256=sha(archive),archive_bytes=Path(archive).stat().st_size)

def chunk_dir(directory,row): return directory/'chunks'/row['model']/f"{row['index']:04d}"
def validate_done(directory,c,row):
    base=chunk_dir(directory,row); file=base/'DONE.json'
    if not file.exists(): return None
    d=read(file)
    check(d['plan']==row and d['config_sha256']==sha(directory/'config.json'),'Checkpoint plan/config mismatch')
    check(d['counts']['decays']==row['count'],'Checkpoint census mismatch')
    attempt=local(base/d['attempt'])
    check(attempt.parent==base.resolve(),'Checkpoint attempt escapes batch')
    for name,h in d['files_sha256'].items():
        check(Path(name).name==name and sha(local(attempt/name))==h,'Completed chunk artifact changed')
    check(set(d['files_sha256'])=={'compact.h5','truth.lh5.gz','transport.json','archive.json'},'Checkpoint inventory mismatch')
    check(compact_counts(attempt/'compact.h5')==d['counts'],'Checkpoint counts inconsistent')
    return d

def select_attempt(directory,row):
    base=chunk_dir(directory,row); base.mkdir(parents=True,exist_ok=True)
    attempts=sorted(p for p in base.glob('attempt-*') if p.is_dir())
    for attempt in reversed(attempts):
        local(attempt)
        if (attempt/'transport.json').exists():
            r=read(attempt/'transport.json')
            if r['status']=='process_completed':
                check(r['plan']==row and r['config_sha256']==sha(directory/'config.json'),'Recovered raw plan mismatch')
                check(sha(attempt/'truth.lh5')==r['raw_sha256'],'Recovered raw hash mismatch')
                return attempt,r
    attempt=base/f'attempt-{len(attempts)+1:03d}'; attempt.mkdir()
    return attempt,None

def run_transport(directory,row,attempt,lock_handle,tick):
    source=directory/'inputs'/row['model']
    shutil.copyfile(source/'geometry.gdml',attempt/'geometry.gdml')
    text=(source/'run.mac').read_text()
    text,count=re.subn(r'^/run/beamOn\s+\d+\s*$',f"/run/beamOn {row['count']}",text,flags=re.M)
    check(count==1,'Expected exactly one beamOn; no other macro change allowed')
    (attempt/'run.mac').write_text(text,encoding='utf-8')
    command=['remage','--flat-output','-t','1','--rand-seed',str(row['seed']),'-o','truth.lh5','-g','geometry.gdml','--','run.mac']
    record=dict(status='running',plan=row,config_sha256=sha(directory/'config.json'),command=command,started_utc=utc())
    atomic(attempt/'started.json',record); started=time.monotonic()
    with (attempt/'run.log').open('x') as log:
        process=subprocess.Popen(command,cwd=attempt,stdout=log,stderr=subprocess.STDOUT,pass_fds=(lock_handle.fileno(),))
        record['pid']=process.pid; atomic(attempt/'started.json',record)
        try:
            while process.poll() is None: tick(); time.sleep(1)
        except BaseException:
            process.terminate()
            try: process.wait(timeout=15)
            except subprocess.TimeoutExpired: process.kill(); process.wait()
            raise
        record['returncode']=process.returncode
    record['wall_seconds']=time.monotonic()-started; record['finished_utc']=utc()
    if process.returncode!=0:
        record['status']='failed'; atomic(attempt/'transport.json',record)
        raise RuntimeError('remage failed; attempt and checkpoint preserved')
    logtext=(attempt/'run.log').read_text(errors='replace')
    check(not re.search(r'COMMAND NOT FOUND|illegal application state|command refused|parameter out of range|macro.*(failed|error)|\*\*\*\s*(Error|Fatal)|Overlap is detected',logtext,re.I),'Macro/geometry failure in run log')
    record['raw_sha256']=sha(attempt/'truth.lh5'); record['status']='process_completed'
    atomic(attempt/'transport.json',record)
    return record

def process_chunk(directory,c,row,lock_handle,tick):
    attempt,receipt=select_attempt(directory,row)
    if receipt is None: receipt=run_transport(directory,row,attempt,lock_handle,tick)
    meta=read(directory/'inputs'/row['model']/'prepared.json')
    meta['primary_count']=row['count']; meta['seed']=row['seed']
    raw=attempt/'truth.lh5'; target=attempt/'compact.h5'
    if not target.exists():
        temporary=attempt/('compact.partial-'+str(time.time_ns())+'.h5')
        compact(raw,meta,temporary,row['start'],tick)
        os.replace(temporary,target); syncdir(attempt)
    else: verify_compact(raw,meta,target,row['start'])
    tick(); archive=archive_raw(raw,attempt/'truth.lh5.gz')
    check(archive['raw_sha256']==receipt['raw_sha256'],'Raw data changed before archive')
    atomic(attempt/'archive.json',archive)
    files=('compact.h5','truth.lh5.gz','transport.json','archive.json')
    done=dict(status='verified',plan=row,config_sha256=sha(directory/'config.json'),attempt=attempt.name,
              counts=compact_counts(target),files_sha256={n:sha(attempt/n) for n in files},
              artifact_bytes=sum((attempt/n).stat().st_size for n in files),finished_utc=utc())
    check(done['counts']['decays']==row['count'],'Compact census changed')
    atomic(chunk_dir(directory,row)/'DONE.json',done)
    # Only this new temporary raw file is removed, AFTER durable verified copies.
    check(raw.parent==attempt and sha(raw)==archive['raw_sha256'],'Temporary raw changed')
    raw.unlink(); syncdir(attempt)
    return done

def collect(directory,c):
    summaries={m:dict(decays=0,ge_positive=0,decay_photons=0,line_photons=0,bytes=0) for m in MODELS}
    done={}
    for row in plan(c):
        d=validate_done(directory,c,row)
        if d:
            done[(row['model'],row['index'])]=d
            for k,v in d['counts'].items(): summaries[row['model']][k]+=v
            summaries[row['model']]['bytes']+=d['artifact_bytes']
    return done,summaries

def run(directory,max_chunks=None):
    directory=local(directory); c=config(directory)
    with locked(directory) as handle:
        actual=runtime(); rp=directory/'runtime.json'
        if rp.exists(): check(read(rp)==actual,'Runtime/data changed since preparation')
        else: atomic(rp,actual)
        started=time.monotonic(); done,models=collect(directory,c)
        completed=sum(v['decays'] for v in models.values()); initial=completed; current=None; last=0.; made=0
        def tick(stage=None,force=False):
            nonlocal last
            changed=current is not None and stage is not None and current.get('phase')!=stage
            if changed: current['phase']=stage
            now=time.monotonic()
            if force or changed or now-last>=5:
                write_progress(directory,c,'running',completed,models,current,now-started,completed-initial); last=now
        tick(force=True)
        try:
            for row in plan(c):
                if (row['model'],row['index']) in done: continue
                if (directory/'STOP_AFTER_CHUNK').exists() or (max_chunks is not None and made>=max_chunks):
                    write_progress(directory,c,'paused',completed,models,None,time.monotonic()-started,completed-initial)
                    return read(directory/'progress.json')
                check(c==config(directory),'Configuration changed during run')
                remaining=2*c['events_per_model']-completed
                per_decay=max(4000,sum(v['bytes'] for v in models.values())/max(1,completed))
                check(shutil.disk_usage(directory).free>2*1024**3+1.3*remaining*per_decay,'Insufficient free-disk headroom; completed chunks retained')
                current={**row,'phase':'transport_or_recovery'}; tick(force=True)
                d=process_chunk(directory,c,row,handle,tick)
                done[(row['model'],row['index'])]=d; made+=1; completed+=row['count']
                for k,v in d['counts'].items(): models[row['model']][k]+=v
                models[row['model']]['bytes']+=d['artifact_bytes']; tick(force=True)
            check(completed==2*c['events_per_model'],'Final campaign census mismatch')
            final=dict(kind=c['kind'],status='completed_transport',awaiting='User-requested later spectrum/SSD/readout analysis',
                       completed_decays=completed,models=models,config_sha256=sha(directory/'config.json'),finished_utc=utc())
            atomic(directory/'COMPLETE.json',final)
            write_progress(directory,c,'completed_transport',completed,models,None,time.monotonic()-started,completed-initial)
            return final
        except BaseException as error:
            write_progress(directory,c,'failed',completed,models,current,time.monotonic()-started,completed-initial,str(error))
            raise

def verify(directory):
    directory=local(directory); c=config(directory); done,models=collect(directory,c)
    return dict(verified_chunks=len(done),target_chunks=len(plan(c)),models=models,complete=len(done)==len(plan(c)))

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['prepare','run','status','verify','compact-existing'])
    p.add_argument('--campaign',default='.local/cs137-1m')
    p.add_argument('--events',type=int,default=1000000)
    p.add_argument('--chunk-size',type=int,default=10000)
    p.add_argument('--seed',type=int,default=26092701)
    p.add_argument('--max-chunks',type=int)
    p.add_argument('--model',choices=MODELS,default='AK02')
    p.add_argument('--output')
    a=p.parse_args(); directory=Path(a.campaign)
    if not directory.is_absolute(): directory=ROOT/directory
    if a.action=='prepare':
        c=prepare(directory,a.events,a.chunk_size,a.seed)
        result=dict(status='prepared',per_model=c['events_per_model'],chunks=len(plan(c)))
    elif a.action=='run':
        check(a.max_chunks is None or a.max_chunks>0,'Invalid chunk limit')
        result=run(directory,a.max_chunks)
    elif a.action=='status': result=read(local(directory)/'progress.json')
    elif a.action=='verify': result=verify(directory)
    else:
        check(a.output is not None,'Specify a new compact output')
        out=local(ROOT/a.output); out.parent.mkdir(parents=True,exist_ok=True)
        meta=read(OLD/a.model/'transport/prepared.json')
        result=compact(OLD/a.model/'transport/truth.lh5',meta,out)
    print(json.dumps(result,indent=2,allow_nan=False))

if __name__=='__main__': main()
