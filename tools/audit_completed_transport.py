"""Read-only integrity audit; preserve completed transport, never start or resume it."""
import argparse, gzip, hashlib, json, math, sys, time, zipfile
from pathlib import Path
import h5py
import numpy as np
import long_transport as lt
ROOT = Path(__file__).resolve().parents[1]
def require(ok, message):
    if not ok: raise ValueError(message)
def fingerprint(p):
    s=p.stat(); return (s.st_size,s.st_mtime_ns)
def archive_check(p, expected_sha, expected_bytes):
    h=hashlib.sha256(); size=0
    with gzip.open(p,'rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b); size+=len(b)
    require(size==expected_bytes and h.hexdigest()==expected_sha,'Decompressed archive differs')
    return size
def compact_check(p, row, counts):
    with h5py.File(p,'r') as f:
        require(f.attrs['kind']=='compact_cs137_transport_v1','Compact kind')
        require(f.attrs['model_id']==row['model'] and f.attrs['global_offset']==row['start'],'Compact identity')
        e=f['events']; n=row['count']; off=row['start']
        require(np.array_equal(e['local_event_id'][:],np.arange(n)),'Local IDs')
        require(np.array_equal(e['global_decay_id'][:],np.arange(off,off+n)),'Global IDs')
        energy=e['ge_energy_keV'][:]
        require(np.all(np.isfinite(energy)) and np.all(energy>=0),'Invalid energy')
        require(np.array_equal(e['has_ge_energy'][:],energy>0),'Zero census')
        require(int(np.count_nonzero(energy))==counts['ge_positive'],'Positive count')
        ids=f['details/stp/germanium/evtid'][:]; edep=f['details/stp/germanium/edep'][:]
        require(np.all((ids>=0)&(ids<n)),'Step ID outside chunk')
        require(np.allclose(np.bincount(ids,weights=edep,minlength=n),energy,rtol=1e-12,atol=1e-10),'Step/scalar sum')
        for key in ('decay_photons','line_photons'):
            a=e[key][:]; require(a.dtype.kind in 'iu' and np.all(a>=0),'Invalid photon counts')
            require(int(a.sum())==counts[key],'Photon denominator mismatch')
        require(np.all(e['line_photons'][:]<=e['decay_photons'][:]),'Line photon denominator')
        # Read all chunks of all datasets: exercise HDF5 checksums, not headers only.
        def touch(name,obj):
            if isinstance(obj,h5py.Dataset):
                arr=obj[...]
                if arr.dtype.kind=='f': require(np.all(np.isfinite(arr)),'Nonfinite stored dataset '+name)
        f.visititems(touch)
        return int(len(ids)),str(f.attrs['raw_sha256'])
def audit(campaign, output):
    campaign=lt.local(campaign); output=lt.local(output)
    require(not output.exists(),'Audit output exists; preserve prior evidence')
    c=lt.config(campaign); complete=lt.read(campaign/'COMPLETE.json')
    require(complete['status']=='completed_transport','Campaign not terminal')
    require(complete['config_sha256']==lt.sha(campaign/'config.json'),'Completion configuration mismatch')
    rows=lt.plan(c); expected=2*c['events_per_model']
    require(complete['completed_decays']==expected,'Incomplete final census')
    files=[p for p in campaign.rglob('*') if p.is_file()]
    before={str(p.relative_to(campaign)):fingerprint(p) for p in files}
    result={'kind':'completed_transport_preservation_v1','status':'verifying','campaign':str(campaign.relative_to(ROOT)),
        'complete_sha256':lt.sha(campaign/'COMPLETE.json'),'config_sha256':lt.sha(campaign/'config.json'),
        'audit_source_sha256':lt.sha(__file__),'chunks':[],'models':{},'original_files_deleted':0,'original_files_modified':0}
    started=time.monotonic(); total_raw=0; inventory={}
    for row in rows:
        d=lt.validate_done(campaign,c,row); require(d is not None and d['status']=='verified','Missing verified checkpoint')
        base=lt.chunk_dir(campaign,row); attempt=base/d['attempt']; a=lt.read(attempt/'archive.json')
        transport=lt.read(attempt/'transport.json')
        require(transport['plan']==row and transport['returncode']==0 and transport['status']=='process_completed','Transport receipt mismatch')
        require(transport['config_sha256']==result['config_sha256'],'Transport configuration mismatch')
        require(lt.sha(attempt/'geometry.gdml')==c['templates'][row['model']]['geometry.gdml'],'Attempt geometry changed')
        template=(campaign/'inputs'/row['model']/'run.mac').read_text()
        import re
        expected_macro=re.sub(r'^/run/beamOn\s+\d+\s*$',f"/run/beamOn {row['count']}",template,flags=re.M)
        require((attempt/'run.mac').read_text()==expected_macro,'Attempt macro changed')
        require(a['archive_sha256']==d['files_sha256']['truth.lh5.gz'],'Archive binding mismatch')
        require(a['raw_sha256']==transport['raw_sha256'],'Raw receipt binding mismatch')
        rawbytes=archive_check(attempt/'truth.lh5.gz',a['raw_sha256'],a['raw_bytes'])
        steps,rawhash=compact_check(attempt/'compact.h5',row,d['counts'])
        require(rawhash==a['raw_sha256'],'Compact/raw binding mismatch'); total_raw+=rawbytes
        m=result['models'].setdefault(row['model'],dict(decays=0,ge_positive=0,decay_photons=0,line_photons=0,bytes=0,ge_steps=0))
        for key,value in d['counts'].items(): m[key]+=value
        m['bytes']+=d['artifact_bytes']; m['ge_steps']+=steps
        result['chunks'].append(dict(plan=row,done_sha256=lt.sha(base/'DONE.json'),counts=d['counts'],raw_sha256=rawhash,raw_bytes=rawbytes))
        for file in (base/'DONE.json',attempt/'compact.h5',attempt/'truth.lh5.gz',attempt/'archive.json',attempt/'transport.json',attempt/'run.mac',attempt/'geometry.gdml'):
            name=file.relative_to(campaign).as_posix(); known=d['files_sha256'].get(file.name)
            inventory[name]={'sha256':known or lt.sha(file),'bytes':file.stat().st_size}
        if len(result['chunks'])%20==0: print(f"Verified {len(result['chunks'])}/{len(rows)} chunks; archives decompressed in memory",flush=True)
    for model,m in result['models'].items():
        require({k:m[k] for k in complete['models'][model]}==complete['models'][model],'Final model summary mismatch')
    require(sum(m['decays'] for m in result['models'].values())==expected,'Final decoded census mismatch')
    after={str(p.relative_to(campaign)):fingerprint(p) for p in campaign.rglob('*') if p.is_file()}
    require(before==after,'Original files changed during audit')
    require(lt.config(campaign)==c,'Sources changed during audit')
    output.mkdir(parents=True)
    # Small reproducibility snapshot, not a duplicate of the GB-scale science archive.
    snapshot=output/'reproducibility-inputs.zip'
    with zipfile.ZipFile(snapshot,'x',zipfile.ZIP_DEFLATED) as z:
        for name in ('config.json','config.sha256','runtime.json','COMPLETE.json','launcher.json','launcher-exit.json'):
            p=campaign/name
            if p.is_file(): z.write(p,'campaign/'+name)
        for p in (campaign/'inputs').rglob('*'):
            if p.is_file(): z.write(p,'campaign/'+p.relative_to(campaign).as_posix())
        for row in rows:
            p=lt.chunk_dir(campaign,row)/'DONE.json'; z.write(p,'campaign/'+p.relative_to(campaign).as_posix())
        for name in c['source_sha256']: z.write(ROOT/name,'project/'+name)
        for p in (ROOT/'models').rglob('*'):
            if p.is_file(): z.write(p,'project/'+p.relative_to(ROOT).as_posix())
    result.update(status='verified',verified_chunks=len(rows),completed_decays=expected,
        decompressed_raw_bytes=total_raw,seconds=time.monotonic()-started,protected_files=inventory,
        reproducibility_snapshot_sha256=lt.sha(snapshot),source_sha256=c['source_sha256'],
        retention='Keep config/inputs/runtime/COMPLETE plus every DONE, compact.h5, truth.lh5.gz and receipts. Never rerun completed transport for postprocessing.',
        backup_scope='Snapshot and archives are on the same local disk; this is not an independent off-device backup.')
    (output/'audit.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('status','verified_chunks','completed_decays','models','seconds','original_files_modified','original_files_deleted')},indent=2),flush=True)
    return result
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--campaign',default='.local/cs137-1m'); p.add_argument('--output',required=True)
    a=p.parse_args(); audit(ROOT/a.campaign,ROOT/a.output)
