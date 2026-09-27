"""Prepare native-response inputs from completed Geant4 data without rerunning transport."""
import argparse, json, shutil
from pathlib import Path
import h5py, numpy as np
import native_hdf5_bridge as H
import analyze_million as A
ROOT=H.ROOT
NEW_SOURCES=('tools/prepare_native_batch.py','simulation/native_checkpoint_batch.jl','simulation/native_boundary_guard.jl','tools/native_response_launcher.py')
def sha(path): return A.sha(path)
def write(path,value):
    with path.open('x',encoding='utf-8') as stream:
        json.dump(value,stream,sort_keys=True,separators=(',',':'),allow_nan=False)
def prepare(out,pilot=False):
    out=out.resolve()
    H.require(out.is_relative_to(ROOT/'.local') and not out.exists(),'Use new project-local output')
    c,complete,plans,metas=A.campaign_inputs(A.CAMPAIGN)
    sources={**c['source_sha256'],**{name:sha(ROOT/name) for name in NEW_SOURCES}}
    for name in ('tools/native_hdf5_bridge.py','tools/analyze_million.py','simulation/native_bridge_pilot.jl','simulation/Project.toml'):
        sources[name]=sha(ROOT/name)
    summary=A.read(H.ANALYSIS/'summary.json')
    out.mkdir();(out/'inputs').mkdir();(out/'cache').mkdir()
    config=dict(kind='native_checkpoint_batch_v1',pilot=pilot,source_sha256=sources,
        campaign_sha256=sha(A.CAMPAIGN/'config.json'),transport_complete_sha256=sha(A.CAMPAIGN/'COMPLETE.json'),
        original_census_path=str((H.ANALYSIS/'all-event-scalars.h5').relative_to(ROOT)),
        original_census_sha256=sha(H.ANALYSIS/'all-event-scalars.h5'),models={},
        settings=dict(parcels=16,seed_family=2609261,drift_dt_ns=2,drift_cap_ns=10000,temperature_K=77),
        scope='Engineering response with explicit numerical failures/caps; no calibrated CCE, noise or experimental FWHM')
    caches={'AK02':ROOT/'.local/native-response-fix/cap-pair-v2/AK02-state.jls',
            'SAP22':ROOT/'.local/native-response-fix/boundary-proof/SAP22-state.jls'}
    for model in A.MODELS:
        selected_count=group_count=0; chunks=[]; target=out/'inputs'/f'{model}.jsonl'
        with target.open('x',encoding='utf-8',newline='\n') as stream:
            if pilot:
                document=A.read(ROOT/'.local/native-bridge-pilot/contracts-v3'/f'{model}.json')
                ids=({0,3950,2594,8432} if model=='AK02' else {0,3815,965630,8413})
                events=[e for e in document['events'] if e['event_id'] in ids]
                H.require(len(events)==4,'Pilot census')
                for event in events:
                    stream.write(json.dumps(event,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n')
                    selected_count+=1;group_count+=len(event['pulse_groups'])
            else:
                for row in (row for row in plans if row['model']==model):
                    path,done,evidence=A.checkpoint(A.CAMPAIGN,row,config['campaign_sha256'])
                    with h5py.File(path,'r') as data:
                        ids=list(map(int,data['events/global_decay_id'][:][data['events/has_ge_energy'][:]]))
                    events=H.extract_selected(path,row,metas[model],evidence['raw_sha256'],ids)
                    for event in events:
                        event['source_campaign_sha256']=config['campaign_sha256']
                        stream.write(json.dumps(event,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n')
                        selected_count+=1;group_count+=len(event['pulse_groups'])
                    chunks.append(dict(plan=row,compact_path=str(path.relative_to(ROOT)),compact_sha256=sha(path)))
        if not pilot:
            H.require(selected_count==summary['models'][model]['positive_ge_decays'],'Lost positive primary')
            H.require(group_count==summary['models'][model]['isolated_groups'],'Lost pulse group')
        cache=out/'cache'/f'{model}.jls';shutil.copyfile(caches[model],cache)
        baseline=A.read(ROOT/'.local/native-bridge-pilot/pilot-v2'/model/'run.json')
        config['expected_environment']=baseline['environment']
        config['models'][model]=dict(events_file=str(target.relative_to(out)),events_sha256=sha(target),
            selected_primaries=selected_count,groups=group_count,prepared=metas[model],
            population=summary['models'][model],cache_file=str(cache.relative_to(out)),cache_sha256=sha(cache),
            expected_field_fingerprint=baseline['field_fingerprint_before'],expected_calibration=baseline['calibration'],
            chunks=chunks)
    profile=ROOT/'simulation/native_readout_profile.json';shutil.copyfile(profile,out/'profile.json')
    config['profile_sha256']=sha(profile);config['target_groups']=sum(m['groups'] for m in config['models'].values())
    H.require(all(sha(ROOT/name)==value for name,value in sources.items()),'Source changed during preparation')
    write(out/'config.json',config);(out/'config.sha256').write_text(sha(out/'config.json'),encoding='ascii')
    print(json.dumps(dict(status='prepared',pilot=pilot,target_groups=config['target_groups'],output=str(out))))
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--pilot',action='store_true')
    args=parser.parse_args();prepare(args.output,args.pilot)
