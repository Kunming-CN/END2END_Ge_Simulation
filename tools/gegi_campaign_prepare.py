"""Explicit measured GeGI preparation; never starts the formal campaign."""
from __future__ import annotations
import argparse
import ctypes
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import time

import scenario_workflow as W
import gegi_campaign_response as R

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / '.local/gegi-10m'
REQUEST = WORK / 'native-request.json'


def bootstrap():
    old = W.read(ROOT / '.local/runs/gegi-source-left-v1/gegi-request.json')
    request = {k: old[k] for k in ('model_ref', 'model_sha256', 'profile_ref',
                                  'profile_sha256', 'field_cache', 'numerics')}
    request.update(kind='gegi_campaign_response_request_v1',
                   selection={'threads': 1, 'primary_count': 10000},
                   pulse_group_horizon_ns=100000)
    request['numerics'] = {**request['numerics'], 'field_policy': 'reuse-only',
        'depth_calibration': 'independent fixed per-pixel simulated timing calibration'}
    refs = set(old['source_sha256']) | {'simulation/gegi_campaign_response.jl',
        'simulation/gegi_pixel_calibration.jl', 'tools/gegi_campaign_response.py',
        'tools/gegi_event_store.py'}
    request['source_sha256'] = {ref: W.sha(ROOT/ref) for ref in sorted(refs)}
    for key in ('model', 'profile'):
        W.require(W.sha(ROOT/request[key+'_ref']) == request[key+'_sha256'], 'Preserved input changed')
    W.require(W.sha(ROOT/request['field_cache']['ref']) == request['field_cache']['sha256'],
              'Preserved native field cache changed')
    WORK.mkdir(parents=True, exist_ok=True)
    if REQUEST.exists():
        W.require(W.read(REQUEST) == request, 'Existing preparation request changed; inspect before rebinding')
    else:
        W.write(REQUEST, request, fresh=True)
    return {'request_ref': REQUEST.relative_to(ROOT).as_posix(), 'sha256': W.sha(REQUEST)}


def calibrate(limit=None, resume=False):
    W.require(REQUEST.is_file(), 'Bootstrap the explicit pinned request first')
    worker = R.ResidentWorker(REQUEST, WORK/'calibration-spool')
    started = time.perf_counter()
    receipt = {'kind': 'gegi_calibration_measurement_v1', 'status': 'starting',
        'request_sha256': W.sha(REQUEST), 'max_new_injections': limit,
        'started_utc': datetime.now(timezone.utc).isoformat(), 'resume': resume}
    target = WORK/'calibration-measurement.json'
    W.write(target, receipt)
    try:
        ready = worker.start()
        receipt['startup_seconds'] = time.perf_counter()-started
        receipt['new_field_solve'] = ready['new_field_solve']
        receipt['field_cache_sha256'] = ready['field_cache_sha256']
        W.require(ready['new_field_solve'] is False, 'Unexpected new field solve')
        receipt['status'] = 'running'; W.write(target, receipt)
        tick = time.perf_counter()
        result = worker.calibrate(WORK/'pixel-calibration', max_new_injections=limit, resume=resume)
        receipt.update(status=result['status'], calibration_seconds=time.perf_counter()-tick, result=result)
    except BaseException as error:
        receipt.update(status='failed', error=str(error))
        raise
    finally:
        worker.close()
        receipt['total_seconds'] = time.perf_counter()-started
        W.write(target, receipt)
    return receipt


def draft():
    import gegi_campaign as C
    run = W.read(WORK/'pixel-calibration/run.json')
    W.require(run['status'] == 'completed', 'Independent calibration is incomplete')
    for ref, digest in run['artifacts'].items():
        W.require(W.sha(WORK/'pixel-calibration'/ref) == digest, 'Calibration artifact changed')
    p = C.draft()
    p['electronics'] = W.read(ROOT/'.local/runs/gegi-source-left-v1/selection.json')['electronics']
    p['native_request'] = {'ref': REQUEST.relative_to(ROOT).as_posix(), 'sha256': W.sha(REQUEST)}
    table = WORK/'pixel-calibration/depth-calibration.json'
    p['calibration'] = {'ref': table.relative_to(ROOT).as_posix(), 'sha256': W.sha(table)}
    C.validate_plan(p)
    target=WORK/'draft-plan.json'
    if target.exists():
        W.require(W.read(target) == p, 'Existing draft differs; inspect before changing the pilot contract')
    else:
        W.write(target,p,fresh=True)
    return {'status':'draft', 'path':str(target), 'formal_initial_primaries':10000000}


def peak_working_set(process):
    if os.name != 'nt':
        return None
    class Counters(ctypes.Structure):
        _fields_=[('cb',ctypes.c_ulong),('PageFaultCount',ctypes.c_ulong)]+[(name,ctypes.c_size_t) for name in
            ('PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage',
             'QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage')]
    value=Counters();value.cb=ctypes.sizeof(value)
    ok=ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.c_void_p(int(process._handle)),ctypes.byref(value),value.cb)
    W.require(ok, 'Could not measure owned native worker memory')
    return value.PeakWorkingSetSize


def pilots(resume=False):
    import gegi_campaign as C
    p=W.read(WORK/'draft-plan.json');C.validate_plan(p)
    worker=None;inventory=[];total=0
    progress=WORK/'pilot-progress.json'
    try:
        for index,group in enumerate(p['groups']):
            folder=WORK/'pilots'/group['id']
            if folder.exists():W.require(resume,'Pilot output exists; inspect and use explicit resume')
            else:folder.mkdir(parents=True)
            spec=C.pilot_spec(p,group['id'],500,261017301+index)
            timing_path=folder/'timings.json'
            timing=W.read(timing_path) if timing_path.exists() else {'initial_primaries':500,'seed':261017301+index,
                'disk_free_before_bytes':shutil.disk_usage(ROOT).free}
            W.write(progress,{'status':'running_transport','source_group':group['id'],
                              'completed_preparation_primaries':total,'formal_primaries_started':0})
            start=time.perf_counter()
            manifest=C.Transport().process(folder,spec['selection'],lambda:None)
            if 'transport_driver_wall_s' not in timing:
                timing['transport_driver_wall_s']=time.perf_counter()-start
                W.write(timing_path,timing)
            if worker is None:
                worker=R.ResidentWorker(REQUEST,WORK/'pilot-spool')
                start=time.perf_counter();ready=worker.start()
                W.write(WORK/'pilot-native-startup.json',{'startup_seconds':time.perf_counter()-start,
                    'native_request_sha256':W.sha(REQUEST),'new_field_solve':ready['new_field_solve'],
                    'field_cache_sha256':ready['field_cache_sha256']})
            W.write(progress,{'status':'running_native','source_group':group['id'],
                              'completed_preparation_primaries':total,'formal_primaries_started':0})
            start=time.perf_counter()
            response=worker.run_chunk(manifest,folder/'events.sqlite',spec['store_identity'],
                calibration=p['calibration'],photopeak_windows=spec['photopeak_windows'],receipt_path=folder/'response.json')
            if 'native_response_and_store_wall_s' not in timing:
                timing.update(native_response_and_store_wall_s=time.perf_counter()-start,
                    native_process_peak_working_set_bytes=peak_working_set(worker.process),
                    disk_free_after_bytes=shutil.disk_usage(ROOT).free)
                W.write(timing_path,timing)
            inventory.append({'source_group':group['id'],'folder':folder.relative_to(ROOT).as_posix(),
                              'timings':timing_path.relative_to(ROOT).as_posix()})
            total+=response['counts']['initial_primaries']
            W.write(WORK/'pilot-inventory.json',inventory)
        W.write(progress,{'status':'completed','completed_preparation_primaries':total,'formal_primaries_started':0})
    except BaseException as error:
        W.write(progress,{'status':'failed','source_group':group['id'],'error':str(error),
                          'completed_preparation_primaries':total,'formal_primaries_started':0})
        raise
    finally:
        if worker is not None:worker.close()
    return {'status':'completed','preparation_initial_primaries':total,'formal_primaries_started':0}


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('request', 'calibrate', 'draft', 'pilots'))
    p.add_argument('--max-new-injections', type=int)
    p.add_argument('--resume', action='store_true')
    args=p.parse_args()
    if args.action=='request':result=bootstrap()
    elif args.action=='calibrate':result=calibrate(args.max_new_injections,args.resume)
    elif args.action=='draft':result=draft()
    else:result=pilots(args.resume)
    print(W.encoded(result).decode('utf-8'))
