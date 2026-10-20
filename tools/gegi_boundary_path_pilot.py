"""Prepare-only by default: three original drift paths require owner approval.

Execution requires --owner-approved-request-sha256 matching the exact request.
One bounded Julia worker preserves actual paths before generating all34signals.
The Python parent enforces the total wall budget and records partial output.
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

ROOT = Path(__file__).resolve().parents[1]

JULIA_WORKER = r'''
# Only this pending pilot worker may run after explicit owner authorization.
using SolidStateDetectors, Serialization, JSON, SHA, Unitful, LinearAlgebra
const SSD=SolidStateDetectors
BLAS.set_num_threads(1)
check(ok,message)=ok || throw(ArgumentError(message))
hashfile(p)=open(io->bytes2hex(sha256(io)),p)
function save(path,value)
    check(!ispath(path),"Preserve existing pilot artifact")
    open(path*".pending","w") do io;JSON.print(io,value,2);println(io);end
    mv(path*".pending",path)
end
function stage(root,value)
    path=joinpath(root,"progress.json")
    open(path*".pending","w") do io;JSON.print(io,value,2);println(io);end
    mv(path*".pending",path;force=true)
end
point_endpoint(::Type{T},xyz) where T=SSD.CartesianPoint{T}((T.(Float64.(xyz)./1000))...)
xyz(p)=Float64[p.x,p.y,p.z]
function main(req,out)
    check(Threads.nthreads()==1,"Use one Julia thread")
    check(length(req["deposits"])<=3 && req["limits"]["max_attempts"]==3,"Pilot bound changed")
    pkgroot=dirname(dirname(pathof(SSD)))
    for (ref,digest) in req["environment"]["SSD_science_source_sha256"]
        check(hashfile(joinpath(pkgroot,"src",ref))==digest,"Installed SSD source changed: "*ref)
    end
    check(string(pkgversion(SSD))==req["environment"]["SSD_version"],"SSD version changed")
    cache=req["field_cache"]["absolute_ref"]
    check(hashfile(cache)==req["field_cache"]["sha256"],"Existing field cache changed")
    check(hashfile(req["model"]["absolute_ref"])==req["model"]["sha256"],"Model changed")
    available=Sys.free_memory();estimate=ceil(Int,1.25*filesize(cache));reserve=768*1024^2
    stage(out,Dict("status"=>"memory_preflight","available_physical_bytes"=>available,
        "estimated_state_bytes"=>estimate,"reserve_bytes"=>reserve,"attempts"=>0))
    check(available>=estimate+reserve,"Insufficient memory; no saved-state load attempted")
    sim=deserialize(cache) # No solve-capable helper or fresh-state fallback.
    check(Sys.free_memory()>=512*1024^2,"Insufficient physical reserve after load")
    check(length(sim.detector.contacts)==34 && all(x->!ismissing(x),sim.weighting_potentials),"Missing34contact native state")
    check(sim.detector.semiconductor.charge_trapping_model isa SSD.NoChargeTrappingModel,"Charge-trapping model changed")
    T=SSD.get_precision_type(sim);check(8sizeof(T)==32,"Original serialized precision changed")
    settings=req["drift_settings"];dt=settings["drift_dt_ns"];maxsteps=settings["max_steps"]
    check(dt==1 && maxsteps==1001 && settings["diffusion"]===false && settings["self_repulsion"]===false,
        "Original fixed drift settings changed")
    complete=Any[]
    for (attempt,deposit) in enumerate(req["deposits"])
        dir=joinpath(out,"row-"*string(deposit["raw_row_index"]));mkdir(dir)
        stage(out,Dict("status"=>"drift_running","attempts"=>attempt,"raw_row_index"=>deposit["raw_row_index"],
            "completed_deposits"=>complete))
        current="drift"
        try
            # Exact original native_deposit position and energy conversion.
            point=SSD.CartesianPoint{T}((T.(deposit["position_mm"])./T(1000))...)
            check(point in sim.detector.semiconductor && !any(c->point in c.geometry,sim.detector.contacts),"Invalid original start")
            event=SSD.Event([point],[deposit["energy_keV"]*u"keV"])
            SSD.drift_charges!(event,sim;Δt=dt*u"ns",max_nsteps=maxsteps,geometry_check=true,
                diffusion=false,self_repulsion=false,end_drift_when_no_field=true,verbose=false)
            check(length(event.drift_paths)==1,"Original single-deposit path changed")
            # Save native typed paths first. Any later error keeps these paths.
            binary=joinpath(dir,"paths.jls")
            serialize(binary,(locations=event.locations,energies=event.energies,drift_paths=event.drift_paths,
                field_cache_sha256=req["field_cache"]["sha256"],deposit=deposit))
            path=only(event.drift_paths);pathjson=Dict("positions_unit"=>"m","time_unit"=>"s",
                "native_precision_bits"=>32,"electron_positions"=>xyz.(path.e_path),
                "hole_positions"=>xyz.(path.h_path),"electron_timestamps"=>Float64.(path.timestamps_e),
                "hole_timestamps"=>Float64.(path.timestamps_h))
            save(joinpath(dir,"paths.json"),pathjson)
            for (species,points) in (("electron",path.e_path),("hole",path.h_path))
                original=only(filter(ep->ep["species"]==species,deposit["original_endpoints"]))
                check(last(points)==point_endpoint(T,original["position_mm"]),"Original endpoint position not reproduced: "*species)
                check(length(points)==original["samples"],"Original endpoint sample count changed: "*species)
                check([c.id for c in sim.detector.contacts if last(points) in c.geometry]==original["contact_ids"],
                    "Original endpoint contact identity changed: "*species)
            end
            current="all34signals";terminal=Float64[]
            for cid in 1:34
                SSD.get_signal!(event,sim,cid;Δt=dt*u"ns",signal_unit=u"keV")
                w=event.waveforms[cid];observed=Float64.(ustrip.(u"ns",w.time));times=collect(0:length(observed)-1).*dt
                check(all(isapprox.(observed,times;rtol=2e-6,atol=max(1e-5,dt*2e-6))),"Native time grid changed")
                charge=Float64.(ustrip.(u"keV",w.signal));check(length(charge)>=2 && all(isfinite,charge) && first(charge)==0,"Invalid original native signal")
                push!(terminal,last(charge))
                save(joinpath(dir,"channel-"*lpad(string(cid),2,'0')*".json"),
                    Dict("time_ns"=>times,"signed_induced_keV"=>charge))
            end
            check(terminal==deposit["original_endpoint_algebra_terminal_signed_keV"],"Original endpoint-algebra terminal identity changed")
            files=Dict(name=>hashfile(joinpath(dir,name)) for name in readdir(dir) if isfile(joinpath(dir,name)))
            receipt=Dict("status"=>"completed_original_paths_and34signals","attempt"=>attempt,
                "raw_row_index"=>deposit["raw_row_index"],"endpoint_positions_samples_contacts_exact"=>true,
                "endpoint_algebra_terminal_exact"=>true,"file_sha256"=>files)
            save(joinpath(dir,"COMPLETE.json"),receipt);push!(complete,receipt)
        catch err
            save(joinpath(dir,"failure.json"),Dict("status"=>"failed_stop","stage"=>current,"error"=>sprint(showerror,err),
                "exception_type"=>string(typeof(err)),"raw_row_index"=>deposit["raw_row_index"],"retry"=>false))
            stage(out,Dict("status"=>"failed_stop","attempts"=>attempt,"completed_deposits"=>complete))
            rethrow()
        end
    end
    save(joinpath(out,"COMPLETE.json"),Dict("status"=>"completed_original_forward_pilot","deposits"=>complete,
        "new_field_solves"=>0,"new_transport_calls"=>0,"new_calibration_calls"=>0,"candidate_correction_applied"=>false))
    stage(out,Dict("status"=>"completed_original_forward_pilot","attempts"=>length(complete)))
end
check(length(ARGS)==2,"Pass request and new result root")
main(JSON.parsefile(ARGS[1]),ARGS[2])
'''


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def available_memory():
    class Memory(ctypes.Structure):
        _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong)] + [
            (name, ctypes.c_ulonglong) for name in ('total', 'available', 'total_page', 'available_page',
                                                  'total_virtual', 'available_virtual', 'extended')]
    value = Memory(); value.length = ctypes.sizeof(value)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(value)):
        raise OSError('Cannot measure available physical memory')
    return value.available


def execute(request_path, approval_sha):
    request_path = Path(request_path).resolve(); digest = sha(request_path)
    if approval_sha != digest:
        raise ValueError('Not authorized: explicit owner approval must bind this exact request SHA256')
    request = json.loads(request_path.read_bytes())
    if request['kind'] != 'gegi_saved_boundary_path_pilot_request_v1' or len(request['deposits']) > 3:
        raise ValueError('Unsupported or enlarged pilot request')
    if request['limits'] != {'max_attempts': 3, 'max_total_wall_seconds': 300, 'julia_threads': 1,
                              'minimum_physical_reserve_bytes': 536870912}:
        raise ValueError('Pilot resource limits changed')
    for ref, expected in request['input_file_sha256'].items():
        if sha(ROOT/ref) != expected:
            raise ValueError('Pinned input/source changed: '+ref)
    cache = Path(request['field_cache']['absolute_ref'])
    estimate = int(1.25*cache.stat().st_size) + (600+768)*1024**2
    before = available_memory()
    if before < estimate:
        raise ValueError(f'Insufficient physical memory: available={before}, estimated_with_runtime_and_reserve={estimate}')
    output = request_path.parent/'results'
    output.resolve().relative_to((ROOT/'.local').resolve())
    output.mkdir()  # Refuse an existing attempt, including partial output.
    worker = output/'native-worker.jl'; worker.write_text(JULIA_WORKER, encoding='utf-8')
    env = os.environ.copy(); env.update(JULIA_PKG_OFFLINE='true', JULIA_NUM_THREADS='1',
                                       OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1')
    command = [request['environment']['julia_executable'], '--startup-file=no', '--compiled-modules=existing',
               '--threads=1', '--project='+str(ROOT/'simulation'), str(worker), str(request_path), str(output)]
    started = time.monotonic(); reason = None
    with (output/'worker.log').open('x', encoding='utf-8') as log:
        child = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
        while child.poll() is None:
            if time.monotonic()-started >= 300:
                reason = 'total_300_second_budget'; child.kill(); break
            if available_memory() < 512*1024**2:
                reason = 'physical_memory_reserve'; child.kill(); break
            if (output/'stop.request').exists():
                reason = 'manual_stop'; child.kill(); break
            time.sleep(.25)
        code = child.wait()
    receipt = {'status': 'completed' if code == 0 else 'stopped_or_failed', 'returncode': code,
               'stop_reason': reason, 'elapsed_seconds': time.monotonic()-started,
               'request_sha256': digest, 'runner_sha256': sha(Path(__file__)), 'worker_sha256': sha(worker),
               'available_physical_before_bytes': before, 'estimated_runtime_state_reserve_bytes': estimate,
               'authorization': 'Explicit owner approval bound to exact request SHA256',
               'retry': False, 'partial_artifacts': 'Retain all results, paths and per-channel partial outputs'}
    (output/'runtime.json').write_text(json.dumps(receipt, indent=2)+'\n', encoding='utf-8')
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--owner-approved-request-sha256', required=True)
    args = parser.parse_args()
    result = execute(args.request, args.owner_approved_request_sha256)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['returncode'] == 0 else 1)
