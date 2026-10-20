"""Prepare or explicitly execute the fixed 15-point GeGI full-response pilot.

Preparation is read-only apart from its new request. Execution reuses the exact
saved fields and shared calibration recorder; no field/transport fallback exists.
"""
from __future__ import annotations
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

import scenario_workflow as W
from gegi_boundary_path_pilot import available_memory

ROOT = Path(__file__).resolve().parents[1]
CALIBRATION = '.local/gegi-10m/signal-recovery-v1/calibration'
BANK = '.local/gegi-10m/pixel-calibration'
REQUEST = CALIBRATION+'/full34-pilot/request.json'
PIXELS = ((9, 26), (1, 26), (3, 20))
DEPTHS = (-4.5, -2.5, 0., 2.5, 4.5)
LIMITS = {'maximum_new_drift_calls': 15, 'maximum_total_wall_seconds': 300,
          'julia_threads': 1, 'worker_processes': 1, 'automatic_retry': False}
KIND = 'gegi_fixed15_full34_forward_pilot_request_v1'

JULIA_WORKER = r'''
using JSON, Unitful, LinearAlgebra
include(joinpath(pwd(),"simulation","gegi_response.jl"))
include(joinpath(pwd(),"simulation","gegi_pixel_calibration.jl"))
const G=GeGIResponse;const K=GeGIPixelCalibration;const SSD=G.SSD
const check=G.check
BLAS.set_num_threads(1)
bits_equal(a,b)=reinterpret(UInt8,Float64.(a))==reinterpret(UInt8,Float64.(b))
function fresh(path,value)
    check(!ispath(path),"Preserve existing pilot artifact: "*path)
    G.save(path,value)
end
function endpoint_identity(sim,row)
    row["endpoints"]===nothing && return nothing
    T=SSD.get_precision_type(sim)
    endpoint(species)=only(filter(e->e["species"]==species,row["endpoints"]))
    e=endpoint("electron");h=endpoint("hole")
    point(ep)=SSD.CartesianPoint{T}((T.(Float64.(ep["position_mm"])./1000))...)
    ep=point(e);hp=point(h)
    charge=T(SSD.to_internal_units(row["injection_energy_keV"]*u"keV"))
    factor=T(ustrip(u"keV",SSD._convert_internal_energy_to_external_unit(u"keV",nothing)))
    known=length(e["contact_ids"])==1 && length(h["contact_ids"])==1
    values=Any[]
    for signal in row["channel_signals"]
        id=signal["contact_id"];itp=SSD.interpolated_scalarfield(sim.weighting_potentials[id])
        pe=SSD.get_interpolation(itp,ep,SSD.Cartesian);ph=SSD.get_interpolation(itp,hp,SSD.Cartesian)
        # Preserve SSD's native precision and electron-then-hole accumulation.
        predicted=(pe*(-charge)+ph*charge)*factor
        ie=known ? T(id in e["contact_ids"]) : nothing
        ih=known ? T(id in h["contact_ids"]) : nothing
        ideal=known ? (ie*(-charge)+ih*charge)*factor : nothing
        actual=last(signal["signed_induced_keV"])
        push!(values,Dict("contact_id"=>id,"electron_phi"=>Float64(pe),"hole_phi"=>Float64(ph),
            "actual_terminal_signed_keV"=>actual,"native_endpoint_algebra_signed_keV"=>Float64(predicted),
            "terminal_minus_endpoint_algebra_keV"=>actual-Float64(predicted),
            "ideal_contact_terminal_signed_keV"=>ideal===nothing ? nothing : Float64(ideal),
            "terminal_minus_ideal_contact_keV"=>ideal===nothing ? nothing : actual-Float64(ideal),
            "electron_phi_minus_contact_value"=>known ? Float64(pe)-Float64(ie) : nothing,
            "hole_phi_minus_contact_value"=>known ? Float64(ph)-Float64(ih) : nothing))
    end
    Dict("channels"=>values,"native_precision_bits"=>8sizeof(T),
        "max_absolute_terminal_identity_error_keV"=>maximum(abs(v["terminal_minus_endpoint_algebra_keV"]) for v in values),
        "max_absolute_terminal_ideal_contact_error_keV"=>known ? maximum(abs(v["terminal_minus_ideal_contact_keV"]) for v in values) : nothing,
        "X_face_terminal_sum_minus_injection_keV"=>sum(last(s["signed_induced_keV"]) for s in row["channel_signals"][1:17])-row["injection_energy_keV"],
        "Y_face_terminal_sum_minus_injection_keV"=>-sum(last(s["signed_induced_keV"]) for s in row["channel_signals"][18:34])-row["injection_energy_keV"],
        "scope"=>"Original weighting-potential interpolation at actual endpoints. Native arithmetic is electron then hole in stored field precision, followed by SSD energy-unit conversion. Ideal contact values and injection energy are evaluation references only; no waveform normalization or correction.")
end
function compare_selected(row,old)
    row["signals"]===nothing && return Dict("status"=>"unavailable_response","all_exact"=>false)
    faces=Dict(face=>Dict("time_samples_bitexact"=>bits_equal(row["signals"][face]["time_ns"],old["signals"][face]["time_ns"]),
        "signed_samples_bitexact"=>bits_equal(row["signals"][face]["signed_induced_keV"],old["signals"][face]["signed_induced_keV"])) for face in ("X","Y"))
    keys=("status","valid","ctd_ns","X_t50_ns","Y_t50_ns","X_final_induced_keV","Y_final_induced_keV","timing_method","endpoints")
    scalars=Dict(key=>row[key]==old[key] for key in keys)
    Dict("status"=>"compared_saved_selected_pair","faces"=>faces,"scalar_and_endpoint_exact"=>scalars,
        "all_exact"=>all(all(values(v)) for v in values(faces)) && all(values(scalars)))
end
function main(reqpath,out)
    started=time();req=G.E.readjson(reqpath);requestsha=G.hashfile(reqpath)
    check(Threads.nthreads()==1 && length(req["points"])==15,"Fixed 15 points and one thread required")
    check(G.E.environment()==req["environment"]["native"],"Original native environment changed")
    pkgroot=dirname(dirname(pathof(SSD)))
    check(string(pkgversion(SSD))=="0.11.8","Original SSD version changed")
    for (ref,digest) in req["environment"]["SSD_science_source_sha256"]
        check(G.hashfile(joinpath(pkgroot,"src",ref))==digest,"Installed SSD science source changed")
    end
    cfg=(; (Symbol(k)=>v for (k,v) in req["numerics"])...)
    report=Dict{String,Any}();field_started=time()
    fieldreq=Dict("field_cache"=>req["field_cache"])
    sim=G.load_fields(fieldreq,joinpath(G.ROOT,req["model_ref"]),out,cfg,report)
    check(report["fields"]["mode"]=="explicit_exact_model_cache" && report["fields"]["solve_seconds"]==0,"Unexpected field calculation")
    check(8sizeof(SSD.get_precision_type(sim))==req["field_precision_bits"] &&
        sim.detector.semiconductor.charge_trapping_model isa SSD.NoChargeTrappingModel,"Original native state changed")
    check(G.H.channel_metadata(sim.config_dict)==req["channels"],"Original channel metadata changed")
    fresh(joinpath(out,"startup.json"),Dict("field_load_seconds"=>time()-field_started,
        "startup_seconds_including_worker_imports"=>time()-parse(Float64,ENV["GEGI_FULL34_STARTED_UNIX"]),
        "fields"=>report["fields"],"process_peak_rss_bytes"=>Sys.maxrss()))
    rows=Any[]
    for (i,p) in enumerate(req["points"])
        check(time()<parse(Float64,ENV["GEGI_FULL34_DEADLINE_UNIX"]),"Total 300 second budget reached before next injection")
        G.save(joinpath(out,"progress.json"),Dict("status"=>"injection_running","attempted_injections"=>i,"completed_records"=>rows))
        old=K.read_record(joinpath(G.ROOT,p["original_record"]["ref"]),req["original_identity"]["sha256"])
        tick=time();record="injections/point-"*lpad(string(i),2,'0')*".json"
        row,reused=K.checkpoint_injection(sim,cfg,p["contact_ids"]...,p["position_mm"],500.,joinpath(out,record),requestsha)
        check(!reused,"Existing attempt must not be recomputed or silently reused")
        capture_seconds=time()-tick;diagnostic_started=time()
        comparison=compare_selected(row,old);identity=endpoint_identity(sim,row)
        item=Dict("point_index"=>i,"contact_ids"=>p["contact_ids"],"position_mm"=>p["position_mm"],
            "status"=>row["status"],"valid"=>row["valid"],"record_ref"=>record,"record_sha256"=>G.hashfile(joinpath(out,record)),
            "original_record"=>p["original_record"],"selected_pair_comparison"=>comparison,"endpoint_identity"=>identity,
            "capture_and_checkpoint_seconds"=>capture_seconds,"endpoint_and_comparison_seconds"=>time()-diagnostic_started,
            "native_injection_internal_seconds"=>row["execution_seconds"],"process_peak_rss_bytes"=>Sys.maxrss())
        fresh(joinpath(out,"point-"*lpad(string(i),2,'0')*"-comparison.json"),item);push!(rows,item)
        check(comparison["all_exact"],"Saved selected-pair parity changed; retain this result and stop without retry")
    end
    fresh(joinpath(out,"COMPLETE.json"),Dict("status"=>"completed_fixed15_full34_forward_pilot","points"=>rows,
        "request_sha256"=>requestsha,"new_drift_calls"=>length(rows),"new_field_solves"=>0,"new_transport_calls"=>0,
        "elapsed_seconds_after_imports"=>time()-started,"scope"=>"Fixed forward-reference pilot only; no imaging, hardware or detector-physics validation. No signal corrections applied."))
end
check(length(ARGS)==2,"Pass request and new result directory")
try
    main(ARGS[1],ARGS[2])
catch err
    fresh(joinpath(ARGS[2],"failure.json"),Dict("status"=>"failed_stop_preserve_partial","error"=>sprint(showerror,err),
        "exception_type"=>string(typeof(err)),"automatic_retry"=>false))
    rethrow()
end
'''


def binding(path):
    return {'ref': path.relative_to(ROOT).as_posix(), 'sha256': W.sha(path)}


def fixed_points(identity):
    """Bind the original 15 records; never rerun or invent an old baseline."""
    points = [];identity_sha = W.sha(ROOT/BANK/'identity.json')
    for x, y in PIXELS:
        for zi, z in enumerate(DEPTHS, 1):
            path = W.safe_path(ROOT, BANK+f'/diagnostic-injections/{x}-{y}/centre-z{zi}.json')
            record = W.read(path);row = record['payload']
            W.require(record['identity_sha256'] == identity_sha and
                      record['payload_sha256'] == W.digest(row), 'Original point checkpoint changed.')
            xyz = [identity['channels'][x-1]['strip_center_mm'], identity['channels'][y-1]['strip_center_mm'], z]
            W.require(row['contact_ids'] == [x, y] and row['position_mm'] == xyz and row['injection_energy_keV'] == 500. and
                      row['status'] == 'completed' and row['valid'] is True and set(row['signals']) == {'X', 'Y'},
                      'Original fixed point coordinates/status/selected-pair baseline changed.')
            points.append({'contact_ids': [x, y], 'position_mm': xyz, 'original_record': binding(path),
                           'original_status': row['status'], 'original_valid': row['valid'],
                           'original_execution_seconds': row['execution_seconds']})
    return points


def prepare():
    identity_path = ROOT/BANK/'identity.json';identity = W.read(identity_path)
    inventory_path = ROOT/CALIBRATION/'inventory.json';inventory = W.read(inventory_path)
    W.require(inventory['identity_sha256'] == W.sha(identity_path) and inventory['field_cache'] == identity['field_cache'],
              'Inventory/original identity changed.')
    proposal = inventory['bounded_proposal']
    W.require(proposal['pixels'] == [list(p) for p in PIXELS] and proposal['depth_mm'] == list(DEPTHS) and
              proposal['pilot_injections'] == 15 and proposal['energy_keV'] == 500., 'Saved fixed15 proposal changed.')
    points = fixed_points(identity)
    environment = W.read(ROOT/'.local/gegi-10m/signal-recovery-v1/validation/boundary-path-pilot/request.json')['environment']
    sources = ['simulation/'+name for name in identity['source_sha256'] if name != 'gegi_pixel_calibration.jl']
    W.require(all(W.sha(ROOT/ref) == identity['source_sha256'][Path(ref).name] for ref in sources),
              'Shared original native source/environment changed.')
    sources += ['simulation/gegi_pixel_calibration.jl', 'tools/gegi_full34_pilot.py']
    inputs = {ref: W.sha(ROOT/ref) for ref in sources}
    inputs.update({p['original_record']['ref']: p['original_record']['sha256'] for p in points})
    for path in (identity_path, inventory_path, ROOT/identity['field_cache']['ref'], ROOT/'models/GeGI_3D.yaml'):
        inputs[path.relative_to(ROOT).as_posix()] = W.sha(path)
    W.require(inputs[identity['field_cache']['ref']] == identity['field_cache']['sha256'] and
              inputs['models/GeGI_3D.yaml'] == identity['model_sha256'], 'Original cache/model changed.')
    request = {'kind': KIND, 'status': 'prepared_not_executed', 'limits': LIMITS,
        'memory_policy': 'measure_only_not_a_launch_or_stop_condition',
        'authorization': 'Owner 2026-10-20 bounded repair autonomy; supervisor launches this exact request separately.',
        'inventory': binding(inventory_path), 'original_identity': binding(identity_path),
        'model_ref': 'models/GeGI_3D.yaml', 'model_sha256': identity['model_sha256'],
        'field_cache': identity['field_cache'], 'field_precision_bits': identity['field_precision_bits'],
        'numerics': identity['numerics'], 'channels': identity['channels'], 'injection_energy_keV': 500.,
        'environment': {'native': identity['environment'], 'julia_executable': environment['julia_executable'],
            'julia_executable_sha256': environment['julia_executable_sha256'],
            'SSD_science_source_sha256': environment['SSD_science_source_sha256']},
        'points': points, 'original_internal_injection_seconds_sum': sum(p['original_execution_seconds'] for p in points),
        'historical_cost_scope': 'Sum of the 15 original checkpoint internal timings only; excludes cold startup and total IO. Not a full34 cost estimate.',
        'input_file_sha256': inputs, 'worker_sha256': hashlib.sha256(JULIA_WORKER.encode('utf-8')).hexdigest(),
        'scope': '15 known independent injections, all34 signed responses and original-WP endpoint diagnostics. Truth energy is evaluation only, never a signal normalization. No imaging/hardware validation.'}
    path = W.safe_path(ROOT, REQUEST);path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        W.require(W.read(path) == request, 'Existing pilot request changed; preserve it and inspect before replacement.')
    else:
        with path.open('xb') as stream:stream.write(W.encoded(request)+b'\n')
    return {'status': 'prepared_not_executed', 'request': str(path), 'request_sha256': W.sha(path),
            'fixed_points': len(points), 'original_internal_injection_seconds_sum': request['original_internal_injection_seconds_sum']}


def execute(digest):
    path = W.safe_path(ROOT, REQUEST);request = W.read(path)
    W.require(W.sha(path) == digest and request['kind'] == KIND and request['limits'] == LIMITS and
              request['memory_policy'] == 'measure_only_not_a_launch_or_stop_condition' and
              request['worker_sha256'] == hashlib.sha256(JULIA_WORKER.encode('utf-8')).hexdigest(), 'Fixed request/source/budget changed.')
    W.require(request['points'] == fixed_points(W.read(ROOT/BANK/'identity.json')), 'Fixed original points changed.')
    # The shared reuse-only field loader checks the large cache hash once itself.
    for ref, expected in request['input_file_sha256'].items():
        if ref != request['field_cache']['ref']:
            W.require(W.sha(W.safe_path(ROOT, ref)) == expected, 'Pinned input/source changed: '+ref)
    W.require(W.sha(request['environment']['julia_executable']) == request['environment']['julia_executable_sha256'],
              'Pinned Julia executable changed.')
    return launch(path, request, digest, JULIA_WORKER, 'completed_fixed15_full34_forward_pilot')


def launch(path, request, digest, worker_source, completed_status):
    """One 300-second worker; shared by the fixed pilot and full-bank recorder."""
    output = path.parent/'results';output.mkdir()  # One attempt; preserve any existing partial directory.
    worker = output/'full34-worker.jl';worker.write_bytes(worker_source.encode('utf-8'))
    (output/'bound-request.json').write_bytes(path.read_bytes())
    env = dict(os.environ, JULIA_PKG_OFFLINE='true', JULIA_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1')
    command = [request['environment']['julia_executable'], '--startup-file=no', '--compiled-modules=existing',
               '--threads=1', '--project='+str(ROOT/'simulation'), str(worker), str(path), str(output)]
    class PMC(ctypes.Structure):
        _fields_ = [('cb', ctypes.c_ulong), ('faults', ctypes.c_ulong)] + [(k, ctypes.c_size_t) for k in
            ('peak', 'working', 'qpp', 'qp', 'qpnp', 'qnp', 'pagefile', 'peak_pagefile', 'private')]
    getmem = ctypes.windll.psapi.GetProcessMemoryInfo
    getmem.argtypes = [ctypes.c_void_p, ctypes.POINTER(PMC), ctypes.c_ulong];getmem.restype = ctypes.c_int
    try:
        before = available_memory()
    except OSError:
        before = None
    started = time.monotonic();peak = None;stop = None
    env.update(GEGI_FULL34_STARTED_UNIX=str(time.time()), GEGI_FULL34_DEADLINE_UNIX=str(time.time()+300))
    with (output/'worker.log').open('x', encoding='utf-8') as log:
        child = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
        while child.poll() is None:
            memory = PMC();memory.cb = ctypes.sizeof(memory)
            if getmem(ctypes.c_void_p(int(child._handle)), ctypes.byref(memory), memory.cb):peak = max(peak or 0, memory.peak)
            if time.monotonic()-started >= 300:
                stop = '300_second_total_budget';child.kill();break
            if (output/'stop.request').exists():
                stop = 'manual_stop';child.kill();break
            time.sleep(.1)
        code = child.wait()
    result = {'status': completed_status if code == 0 else 'failed_or_stopped_preserve_partial',
        'returncode': code, 'stop_reason': stop, 'elapsed_seconds': time.monotonic()-started,
        'peak_working_set_bytes': peak, 'available_physical_before_bytes': before,
        'memory_policy': request['memory_policy'], 'request_sha256': digest, 'runner_sha256': W.sha(__file__),
        'worker_sha256': W.sha(worker), 'automatic_retry': False,
        'output_bytes_before_runtime_receipt': sum(p.stat().st_size for p in output.rglob('*') if p.is_file())}
    with (output/'runtime.json').open('x', encoding='utf-8') as stream:json.dump(result, stream, indent=2);stream.write('\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', help='Launch one bounded worker; otherwise prepare only')
    parser.add_argument('--request-sha256', help='Required exact request SHA256 for execution')
    args = parser.parse_args()
    result = execute(args.request_sha256) if args.execute else prepare()
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result.get('returncode', 0) == 0 else 1)
