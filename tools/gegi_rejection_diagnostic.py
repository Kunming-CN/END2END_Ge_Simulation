"""Read-only post-hoc census of saved GeGI pulse groups. Never reconstruct from truth.

Truth is used ONLY to diagnose selection losses and evaluate saved coordinates.
An interaction anchor is a gamma -> charged-secondary birth vertex; descendant
electron transport steps remain one anchor. Secondary photon interactions create
their own anchors. Anchor energy means Ge deposition, not incident photon energy.
"""
from __future__ import annotations
import argparse, collections, csv, gzip, hashlib, itertools, json, math
from pathlib import Path
import sqlite3, time, zlib
import numpy as np
import gegi_imaging as I

STRICT = 'requires_two_resolved_strips_per_face'

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def pos(t):
    return tuple(t[k]*1000 for k in ('xloc','yloc','zloc'))

def anchor_key(tid, xyz):
    return (tid, *(round(v, 6) for v in xyz))

def topology(e, names):
    tracks = {t['trackid']: t for t in e['input_group']['parent_event_metadata']['tracks']}
    seeds, track_keys = {}, {}
    for t in tracks.values():
        parent = tracks.get(t['parent_trackid'])
        if t['particle'] != 22 and parent and parent['particle'] == 22:
            key = anchor_key(parent['trackid'], pos(t))
            seeds.setdefault(key, {'position':pos(t), 'processes':set(), 'photon_id':parent['trackid']})['processes'].add(names.get(t['procid'], str(t['procid'])))
            track_keys[t['trackid']] = key
    def ancestor_key(tid):
        seen=set()
        while tid in tracks and tid not in seen:
            seen.add(tid)
            if tid in track_keys:
                return track_keys[tid]
            t=tracks[tid]
            if t['particle'] == 22:
                return None
            tid=t['parent_trackid']
        return None
    sites={}; step_keys=[]; direct=0.0
    for s in e['input_steps']:
        tid=s['track_id']; key=None
        if s['particle_pdg'] == 22:
            key=anchor_key(tid,s['position_mm'])
            if key not in seeds:
                seeds[key]={'position':s['position_mm'],'processes':{'photon_deposit_without_recorded_secondary'},'photon_id':tid}
        else:
            key=ancestor_key(tid)
        step_keys.append(key)
        if key is None:
            direct+=s['energy_keV'];continue
        site=sites.setdefault(key, {'energy':0.,'centroid':np.zeros(3),'x':collections.Counter(),'y':collections.Counter(), **seeds[key]})
        site['energy']+=s['energy_keV'];site['centroid']+=s['energy_keV']*np.asarray(s['position_mm'])
    cells=collections.defaultdict(lambda:[0.,np.zeros(3)])
    for s in e.get('steps',[]) or []:
        idx=s['input_step_index']-1
        assert 0<=idx<len(step_keys)
        original=e['input_steps'][idx]
        assert original['raw_row_index']==s['raw_row_index'] and abs(original['energy_keV']-s['energy_keV'])<1e-7
        xs=[];ys=[]
        for ep in s.get('endpoints',[]):
            for cid in ep.get('contact_ids',[]):
                if 1<=cid<=16: xs.append(cid)
                if 18<=cid<=33: ys.append(cid)
        xs=set(xs);ys=set(ys); key=step_keys[idx]
        if key in sites:
            for cid in xs: sites[key]['x'][cid]+=s['energy_keV']
            for cid in ys: sites[key]['y'][cid]+=s['energy_keV']
        if len(xs)==len(ys)==1:
            cell=cells[next(iter(xs)),next(iter(ys))]
            cell[0]+=s['energy_keV'];cell[1]+=s['energy_keV']*np.asarray(s['position_mm'])
    significant=[s for s in sites.values() if s['energy']>=5.]
    significant1=[s for s in sites.values() if s['energy']>=1.]
    has_compton=any('compt' in s['processes'] for s in significant)
    spread=any(sum(v>=5 for v in s[f].values())>1 for s in significant for f in ('x','y'))
    shared=False
    for f in ('x','y'):
        counts=collections.Counter(cid for s in significant for cid,v in s[f].items() if v>=5.)
        shared |= any(n>1 for n in counts.values())
    for s in sites.values():
        s['centroid']/=s['energy']
    length=max((math.dist(a['position'],b['position']) for a,b in itertools.combinations(significant,2)),default=0.)
    energy=sum(s['energy'] for s in sites.values())+direct
    assert abs(energy-sum(s['energy_keV'] for s in e['input_steps']))<1e-5
    return significant,significant1,has_compton,spread,shared,direct,cells,length

def describe(v):
    a=np.asarray(v,dtype=float)
    return {'n':len(v),'mean':float(a.mean()),'p10':float(np.percentile(a,10)), 'median':float(np.median(a)), 'p90':float(np.percentile(a,90)), 'max':float(a.max())} if len(v) else {'n':0}

def run(campaign, out):
    started=time.perf_counter();out.mkdir(parents=True,exist_ok=True)
    counts=collections.Counter();signal=collections.Counter();truth=collections.Counter();cross=collections.Counter()
    groupcounts=collections.defaultdict(collections.Counter); flags=collections.Counter();accepted=collections.Counter()
    residuals=collections.defaultdict(list);timings=collections.defaultdict(list); inventories=[];examples={}
    rows=[]; energy_matrix=collections.Counter(); truth_matrix=collections.Counter(); rejected_meta_hash=hashlib.sha256()
    for db in sorted(campaign.glob('chunks/*/b*/events.sqlite')):
        cname=db.parent.parent.name; ci=db.parent.name
        manifest=db.parent/'transport/stream/manifest.json'
        names={t['procid']:t['name'] for t in json.loads(manifest.read_text())['processes']}
        timing=json.loads((db.parent/'timings.json').read_text())
        for k,v in timing.items():
            if k.endswith('_s'):timings[cname+':'+k].append(v)
        c=sqlite3.connect(db.resolve().as_uri()+'?mode=ro',uri=True)
        before=db.stat();identity=c.execute('select body from identity').fetchone()[0]
        digest=hashlib.sha256()
        for pid,gid,blob,stored in c.execute('select primary_id,group_id,metadata,metadata_sha256 from events order by primary_id,group_id'):
            body=zlib.decompress(blob); h=hashlib.sha256(body).hexdigest();assert h==stored
            digest.update(h.encode());e=json.loads(body)
            r=e['reconstruction'];reason=r.get('reason') or r['status'];counts[reason]+=1;groupcounts[cname][reason]+=1
            if reason not in (STRICT,'accepted'):continue
            sites,sites1,compton,spread,shared,direct,cells,length=topology(e,names)
            allchannels=e.get('channels') or []
            hits=[v for v in allchannels if I.collected(v,1 if v['contact_id']<=17 else -1)]
            xs=[v for v in hits if v['contact_id']<=16];ys=[v for v in hits if 18<=v['contact_id']<=33]
            nx,ny=len(xs),len(ys)
            energy=e.get('readout_summary',{}).get('energy_keV')
            lines=[662.] if cname.startswith('gamma') else [661.657,1173.228,1332.492]
            photopeak=I.finite(energy) and any(abs(energy-line)<=max(5.,.02*line) for line in lines)
            if reason=='accepted':
                accepted[f'anchors_ge5_{min(len(sites),4)}']+=1
                accepted['compton' if compton else 'no_compton_ge5']+=1
                accepted['direct_charged_ge5' if direct>=5 else 'no_direct_charged_ge5']+=1
                goodcells={k:v for k,v in cells.items() if v[0]>=5.}
                matched=0
                for hyp in r.get('paired_site_hypotheses',[]):
                    if set((s['x_contact'],s['y_contact']) for s in hyp['sites'])==set(goodcells) and len(goodcells)==2:
                        matched+=1
                        for s in hyp['sites']:
                            v=goodcells[s['x_contact'],s['y_contact']]; xyz=v[1]/v[0];d=np.asarray(s['position_mm'])-xyz
                            residuals['matched_pixel_abs_z_mm'].append(abs(d[2]));residuals['matched_pixel_abs_xy_mm'].append(float(np.linalg.norm(d[:2])))
                            residuals['matched_pixel_3d_mm'].append(float(np.linalg.norm(d)))
                accepted['groups_with_endpoint_matched_pairing' if matched else 'groups_without_endpoint_matched_pairing']+=1
                continue
            rejected_meta_hash.update(h.encode())
            if nx==0 or ny==0:cat='missing_above_threshold_face'
            elif nx==ny==1:cat='one_strip_each_face'
            elif min(nx,ny)==1:cat='one_face_merged_other_resolved'
            else:cat='at_least_three_strips_on_one_face'
            signal[cat]+=1;cross[f'{nx}x{ny}']+=1
            n=len(sites)
            tc=('direct_charged_or_mixed' if direct>=5 else 'no_gamma_anchor_ge5' if n==0 else 'one_gamma_anchor_ge5' if n==1 else 'two_gamma_anchors_ge5' if n==2 else 'three_plus_gamma_anchors_ge5')
            truth[tc]+=1;truth_matrix[f'{cat}|{tc}']+=1
            energy_matrix[f'{cat}|'+('inside' if photopeak else 'outside')]+=1
            groupcounts[cname][cat]+=1
            for k,val in [('photopeak',photopeak),('compton_ge5',compton),('single_anchor_multiple_strips',spread),('multiple_anchors_shared_strip',shared),('multiple_ge1_anchors_but_one_ge5',len(sites1)>1 and n==1),('multisite_compton_photopeak_no_direct',n>=2 and compton and photopeak and direct<5),('multisite_compton_photopeak_no_direct_separated_ge5mm',n>=2 and compton and photopeak and direct<5 and length>=5)]:
                if val:flags[k]+=1;groupcounts[cat][k]+=1
            row={'source_group':cname,'chunk':ci,'event_id':pid,'group_id':gid,'metadata_sha256':h,'nx':nx,'ny':ny,'signal_class':cat,'truth_class':tc,'gamma_anchors_ge5':n,'gamma_anchors_ge1':len(sites1),'compton_anchor_ge5':int(compton),'single_anchor_multiple_strips':int(spread),'multiple_anchors_shared_strip':int(shared),'direct_charged_edep_keV':direct,'readout_energy_keV':energy,'inside_frozen_photopeak':int(photopeak),'max_anchor_separation_mm':length}
            rows.append(row)
            key=cat+'|'+tc
            if key not in examples:examples[key]=row
        c.close();after=db.stat();assert before.st_size==after.st_size and before.st_mtime_ns==after.st_mtime_ns
        inventories.append({'db':str(db),'identity_sha256':hashlib.sha256(identity if isinstance(identity,bytes) else identity.encode()).hexdigest(),'metadata_inventory_sha256':digest.hexdigest(),'manifest_sha256':sha(manifest),'size':after.st_size,'mtime_ns':after.st_mtime_ns})
        print(json.dumps({'chunk':len(inventories),'groups':sum(counts.values()),'strict':counts[STRICT],'seconds':round(time.perf_counter()-started,2)}),flush=True)
    assert len(inventories)==100 and sum(counts.values())==57613 and counts[STRICT]==39683 and counts['accepted']==708
    with gzip.open(out/'rejected-groups.csv.gz','wt',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    costs={k:{'sum_s':sum(v),**describe(v)} for k,v in timings.items()}
    report={'kind':'saved_data_rejection_diagnosis_v1','scope':'posthoc truth diagnostics, NOT a new reconstruction; no radiation or native drift','source_sha256':sha(Path(__file__)),'elapsed_s':time.perf_counter()-started,'counts':dict(counts),'strict_signal_classes':dict(signal),'strict_nx_ny':dict(cross),'strict_truth_classes':dict(truth),'signal_truth_cross':dict(truth_matrix),'signal_photopeak_cross':dict(energy_matrix),'overlapping_flags':dict(flags),'group_counts':dict(groupcounts),'accepted_truth_diagnostics':dict(accepted),'accepted_coordinate_residuals':{k:describe(v) for k,v in residuals.items()},'costs':costs,'examples':examples,'input_inventory':inventories,'strict_metadata_inventory_sha256':rejected_meta_hash.hexdigest(),'ledger_sha256':sha(out/'rejected-groups.csv.gz'),'definitions':{'anchor':'gamma-parent charged-secondary birth vertex, matched to Ge deposition descendants; photon direct deposition mapped at endpoint; 1e-6 mm numerical identity rounding only','significant':'at least5keV Ge deposition per anchor; also record1keV sensitivity','direct_charged':'Ge energy whose ancestry does not pass a gamma->charged birth anchor; includes beta/charged-particle transport','sharing':'a single significant interaction anchor feeds at least2 strips on a face, each >=5keV of native input deposits; does not by itself demonstrate diffusion charge sharing','overlap':'at least2 significant anchors feed the same strip, each >=5keV of native input deposits','recoverability':'multisite_compton_photopeak_no_direct is a candidate population, not recovered count; cannot select real reconstruction with truth','residual':'saved accepted coordinates vs energy-weighted deposition centroid in endpoint-matched two-cell hypothesis; not interaction-vertex error or experimental resolution'}}
    (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ['counts','strict_signal_classes','strict_truth_classes','overlapping_flags','accepted_truth_diagnostics','accepted_coordinate_residuals','elapsed_s']},ensure_ascii=False,indent=2))

def supplement(campaign, out):
    """Targeted follow-up: physical anchor support and three dominant edge events."""
    from gegi_event_store import unpack_array
    started=time.perf_counter();r=json.loads((out/'report.json').read_text())
    counters=collections.defaultdict(collections.Counter); examples=[];trace_rows=[]
    targets={('gamma-left',4,2315),('gamma-right',10,1688),('co60-right',28,4042)}
    def inside(p):
        x,y,z=p
        return abs(z)<=5.5+1e-6 and max(abs(x),abs(y))<=45+1e-6 and max(abs(x+y),abs(x-y))<=45*math.sqrt(2)+1e-6
    ledger={}
    with gzip.open(out/'rejected-groups.csv.gz','rt',encoding='utf-8') as f:
        for row in csv.DictReader(f):ledger[row['source_group'],row['chunk'],int(row['event_id']),int(row['group_id'])]=row
    for db in sorted(campaign.glob('chunks/*/b*/events.sqlite')):
        group=db.parent.parent.name;chunk=db.parent.name;before=db.stat()
        names={t['procid']:t['name'] for t in json.loads((db.parent/'transport/stream/manifest.json').read_text())['processes']}
        c=sqlite3.connect(db.resolve().as_uri()+'?mode=ro',uri=True)
        for pid,gid,blob,h in c.execute('select primary_id,group_id,metadata,metadata_sha256 from events'):
            body=zlib.decompress(blob);assert hashlib.sha256(body).hexdigest()==h
            e=json.loads(body);reason=e['reconstruction'].get('reason') or e['reconstruction']['status']
            if reason not in (STRICT,'accepted'):continue
            sites,sites1,compton,spread,shared,direct,cells,length=topology(e,names)
            exterior=sum(s['energy'] for s in sites if not inside(s['position']))
            unknown=sum(s['energy'] for s in sites if 'photon_deposit_without_recorded_secondary' in s['processes'])
            counters[reason]['checked']+=1
            if exterior>=5:counters[reason]['significant_anchor_outside_crystal']+=1
            if unknown>=5:counters[reason]['significant_photon_deposit_unmatched_secondary']+=1
            if reason==STRICT:
                row=ledger[group,chunk,pid,gid];assert row['metadata_sha256']==h
                cat=row['signal_class'];candidate=len(sites)>=2 and compton and int(row['inside_frozen_photopeak']) and direct<5
                if candidate:
                    counters['candidate_nsites'][str(len(sites))]+=1
                    counters['candidate_source'][group]+=1
                    if exterior<5 and unknown<5:counters['candidate_supported'][cat]+=1
                if len(sites)==1:
                    counters['single_anchor']['compton' if compton else 'not_compton']+=1
                    counters['single_anchor']['inside_window' if int(row['inside_frozen_photopeak']) else 'outside_window']+=1
            if (group,int(chunk[1:]),pid) not in targets:continue
            item={'source_group':group,'chunk':chunk,'event_id':pid,'group_id':gid,'campaign_initial_id':e['campaign_initial_offset']+pid,'metadata_sha256':h,'truth_edep_keV':e['truth_edep_keV'],'reconstruction':e['reconstruction'],'anchors':[{'energy_keV':s['energy'],'position_mm':s['position'],'deposition_centroid_mm':s['centroid'].tolist(),'processes':sorted(s['processes']),'native_deposit_x_strips_keV':dict(s['x']),'native_deposit_y_strips_keV':dict(s['y'])} for s in sites],'channel_diagnostics':[]}
            for ch in e['channels']:
                cid=ch['contact_id']
                if not I.collected(ch,1 if cid<=17 else -1):continue
                arrays=e['native_signals'][str(cid)];a={}
                for key,ref in arrays.items():
                    count,blob=c.execute('select count,value from arrays where digest=?',(ref['sha256'],)).fetchone()
                    a[key]=np.asarray(unpack_array(ref['sha256'],count,blob))
                t=a['time_ns'];q=a['signed_induced_keV']*(1 if cid<=17 else -1)
                crossings=[];level=.5*q[-1]
                for j in range(len(t)-1):
                    if q[j]<=level<q[j+1]:crossings.append(float(t[j]+(level-q[j])*(t[j+1]-t[j])/(q[j+1]-q[j])))
                item['channel_diagnostics'].append({'contact_id':cid,'stored_t50_ns':ch['t50_ns'],'recomputed_rising_crossings_ns':crossings,'terminal_keV':float(q[-1]),'minimum_keV':float(q.min()),'maximum_keV':float(q.max()),'maximum_time_ns':float(t[q.argmax()]),'array_sha256':arrays})
                for tx,qx in zip(t,q):trace_rows.append({'campaign_initial_id':item['campaign_initial_id'],'contact_id':cid,'time_ns':float(tx),'wired_induced_keV':float(qx)})
            examples.append(item)
        c.close();after=db.stat();assert (before.st_size,before.st_mtime_ns)==(after.st_size,after.st_mtime_ns)
    with gzip.open(out/'edge-example-native-traces.csv.gz','wt',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(trace_rows[0]));w.writeheader();w.writerows(trace_rows)
    extra={'scope':'truth evaluation and exact native-array extraction only; zero drift/transport calls','source_sha256':sha(Path(__file__)),'elapsed_s':time.perf_counter()-started,'counts':dict(counters),'edge_examples':examples,'native_trace_sha256':sha(out/'edge-example-native-traces.csv.gz')}
    r['supplement']=extra
    (out/'report.json').write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'counts':extra['counts'],'elapsed_s':extra['elapsed_s']},indent=2))

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--campaign',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);ap.add_argument('--supplement',action='store_true');args=ap.parse_args()
    if args.supplement:supplement(args.campaign,args.out)
    else:run(args.campaign,args.out)
