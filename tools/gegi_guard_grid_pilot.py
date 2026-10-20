"""Pending owner-approved fixed localXY weighting-potential34 continuation.

No calculation runs on import. Execution requires the exact approved request
SHA256. Pure grid construction is independently testable without Julia.
"""
from __future__ import annotations
import argparse
import bisect
import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import subprocess
import time
from gegi_boundary_path_pilot import sha, available_memory

ROOT = Path(__file__).resolve().parents[1]


def float32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


def axis_bytes(ticks):
    return struct.pack('<'+'f'*len(ticks), *ticks)


def graded_axis(original, positions, subdivisions, *, negative_parity=False):
    if subdivisions not in (8, 16) or len(original) < 3 or any(b <= a for a, b in zip(original, original[1:])):
        raise ValueError('Invalid fixed grid definition')
    cells = [bisect.bisect_right(original, p)-1 for p in positions]
    if not cells or len(set(cells)) != 1 or not 0 <= cells[0] < len(original)-1:
        raise ValueError('Three endpoints must share one original interval inside the grid')
    central = cells[0]; counts = {central: subdivisions}; distance = 1
    division = subdivisions//2
    while division > 1:
        for index in (central-distance, central+distance):
            if not 0 <= index < len(original)-1:
                raise ValueError('Taper would leave original axis; reject rather than clip')
            counts[index] = division
        distance += 1; division //= 2
    parity = None
    if negative_parity:
        index = central-distance
        if not 0 <= index < len(original)-1:
            raise ValueError('Parity interval would leave original axis')
        counts[index] = 2
        parity = {'original_interval_zero_based': index,
                  'original_interval_m': [original[index], original[index+1]],
                  'inserted_midpoint_m': float32((original[index]+original[index+1])/2),
                  'reason': 'SSD Cartesian X node count must be even; one midpoint in the negative interval adjacent to the outermost taper'}
    result = [original[0]]
    for index, (a, b) in enumerate(zip(original, original[1:])):
        n = counts.get(index, 1)
        result.extend(float32(a+(b-a)*j/n) for j in range(1, n))
        result.append(b)
    if any(b <= a for a, b in zip(result, result[1:])) or not set(original).issubset(result):
        raise ValueError('Float32 insertion lost original ticks or strict ordering')
    return {'ticks_m': result, 'float32_le_sha256': hashlib.sha256(axis_bytes(result)).hexdigest(),
            'central_original_interval_zero_based': central,
            'subdivisions_by_original_interval_zero_based': {str(k): v for k, v in sorted(counts.items())},
            'parity_midpoint': parity}


def grid_hash(axes):
    return hashlib.sha256(struct.pack('<III', *(len(a) for a in axes)) + b''.join(axis_bytes(a) for a in axes)).hexdigest()


JULIA_HELPERS = r'''
# Authorized only by an exact request SHA bound by the Python parent.
using SolidStateDetectors, Serialization, JSON, SHA, Unitful, LinearAlgebra
const SSD=SolidStateDetectors
BLAS.set_num_threads(1)
check(ok,message)=ok || throw(ArgumentError(message))
hashfile(p)=open(io->bytes2hex(sha256(io)),p)
function save(path,value)
    check(!ispath(path),"Preserve existing artifact")
    open(path*".pending","w") do io;JSON.print(io,value,2);println(io);end
    mv(path*".pending",path)
end
function stage(out,status,level)
    path=joinpath(out,"progress.json")
    open(path*".pending","w") do io;JSON.print(io,Dict("status"=>status,"level"=>level));println(io);end
    mv(path*".pending",path;force=true)
end
axis_copy(axis::SSD.DiscreteAxis{T,BL,BR},ticks) where {T,BL,BR}=SSD.DiscreteAxis{T,BL,BR}(axis.interval,T.(ticks))
contacts(sim,p)=[c.id for c in sim.detector.contacts if p in c.geometry]
bits_equal(a::Vector{T},b::Vector{T}) where T=reinterpret(UInt8,a)==reinterpret(UInt8,b)
function grid_digest(axes)
    check(ENDIAN_BOM==0x04030201,"Grid hash requires recorded little-endian format")
    io=IOBuffer()
    for ticks in axes;write(io,UInt32(length(ticks)));end
    for ticks in axes;write(io,reinterpret(UInt8,Float32.(ticks)));end
    bytes2hex(sha256(take!(io)))
end
function path_values(sim,wp,recorded;phi_key="phi34")
    itp=SSD.interpolated_scalarfield(wp);p=only(recorded.drift_paths)
    paths=Dict("electron"=>(p.e_path,p.timestamps_e),"hole"=>(p.h_path,p.timestamps_h));result=Dict()
    for (species,(points,times)) in paths
        ids=[contacts(sim,x) for x in points]
        phi=Float64[SSD.get_interpolation(itp,x,SSD.Cartesian) for x in points]
        indexes=[i for i in 1:length(points)-1 if isempty(ids[i]) && !isempty(ids[i+1])]
        check(!isempty(indexes),"No fixed noncontact-contact segment")
        i=last(indexes);a=points[i];b=points[i+1];samples=Any[]
        for lambda in (0.,.5,.9,.99,.999,1.)
            q=lambda==0 ? a : lambda==1 ? b : a+Float32(lambda)*(b-a)
            push!(samples,Dict("lambda"=>lambda,"contact_ids"=>contacts(sim,q),
                phi_key=>Float64(SSD.get_interpolation(itp,q,SSD.Cartesian))))
        end
        result[species]=Dict(phi_key=>phi,"timestamps_s"=>Float64.(times),"contact_ids"=>ids,
            "last_segment_samples"=>samples,"endpoint_"*phi_key=>last(phi))
    end
    result
end
function waveform(sim,recorded,contact_id=34)
    w=SSD.get_signal(sim,recorded.drift_paths,SSD.flatview(recorded.energies),contact_id;Δt=1u"ns",signal_unit=u"keV")
    Float64.(ustrip.(u"keV",w.signal))
end
function update_native_history!(sim,history_path,deadline;contact_id=34,budget_seconds=300)
    wp=sim.weighting_potentials[contact_id]
    pcs=SSD.PotentialCalculationSetup(sim.detector,wp.grid,sim.medium,wp.data,ones(Float32,size(wp.data));
        sor_consts=1.4f0,weighting_potential_contact_id=contact_id,use_nthreads=1,
        not_only_paint_contacts=true,paint_contacts=true,point_types=missing)
    ndrange=size(pcs.potential)[1:3].-2
    kernel=SSD.get_sor_kernel(SSD.Cartesian,SSD._ka_get_backend(pcs.potential),Val(false))
    inner=view(pcs.potential,(2:size(pcs.potential,k)-1 for k in 1:3)...,:)
    before=similar(inner);c=Inf32;native_c=Inf32;n=0;reason="iteration_cap"
    check(!ispath(history_path),"Preserve existing iteration history")
    try
    open(history_path,"w") do io
        for iteration in 1:10000
            if time()>=deadline;reason=string(budget_seconds)*"_second_total_budget";break;end
            iteration%100==0 && copyto!(before,inner)
            SSD.update!(pcs,kernel,ndrange;use_nthreads=1,depletion_handling=Val(false),
                is_weighting_potential=Val(true),only2d=Val(false))
            n=iteration
            if iteration%100==0
                before .-= inner
                halves=[maximum(abs,view(before,:,:,:,k)) for k in axes(before,4)]
                native_c=first(halves);c=maximum(halves)
                JSON.print(io,Dict("iterations"=>n,"native_half1_max"=>isfinite(native_c) ? Float64(native_c) : nothing,
                    "full_max"=>isfinite(c) ? Float64(c) : nothing,"half_maxima"=>[isfinite(x) ? Float64(x) : nothing for x in halves],
                    "definition"=>"One complete native update at every100th step; original native metric is half1; full_max includes both halves"))
                println(io);flush(io)
                if !isfinite(c);reason="nonfinite_update";break;end
                if c<=1f-6;reason="absolute_full_max_gate";break;end
            end
        end
    end
    finally
        sim.weighting_potentials[contact_id]=SSD.WeightingPotential(SSD.ElectricPotentialArray(pcs),wp.grid)
    end
    c,n,reason,native_c
end
'''

JULIA_WORKER = JULIA_HELPERS + r'''
function main(reqpath,out)
    req=JSON.parsefile(reqpath);check(Threads.nthreads()==1,"Use one thread")
    check(req["contact_id"]==34 && length(req["levels"])==2,"Enlarged solver scope")
    pkgroot=dirname(dirname(pathof(SSD)))
    for (ref,digest) in req["SSD_science_source_sha256"]
        check(hashfile(joinpath(pkgroot,"src",ref))==digest,"Installed science source changed")
    end
    cache=req["field_cache"]["absolute_ref"]
    check(hashfile(cache)==req["field_cache"]["sha256"],"Original cache changed")
    stage(out,"deserialize_original_cache",0);sim=deserialize(cache)
    check(SSD.get_precision_type(sim)==Float32 && SSD.get_coordinate_system(sim)==SSD.Cartesian,"Original state type changed")
    check(sim.detector.semiconductor.charge_trapping_model isa SSD.NoChargeTrappingModel,"Original no-trapping model changed")
    original=sim.weighting_potentials[34];check(size(original.data)==(240,240,88),"Original guard grid changed")
    oldEP=sim.electric_potential;oldEF=sim.electric_field
    otherWP=[sim.weighting_potentials[cid] for cid in 1:33]
    recorded=Dict();baseline=Dict();previous=Dict()
    for row in req["path_rows"]
        key=string(row["raw_row_index"]);recorded[key]=deserialize(row["paths_jls"])
        native=JSON.parsefile(row["original_channel34_json"]);q=waveform(sim,recorded[key])
        check(bits_equal(q,Float64.(native["signed_induced_keV"])),"Original saved path channel34 not bitexact")
        baseline[key]=Dict("waveform_keV"=>q,"time_ns"=>native["time_ns"],
            "potentials"=>path_values(sim,original,recorded[key]))
    end
    save(joinpath(out,"baseline.json"),baseline);completed=Any[]
    for level in req["levels"]
        index=level["central_subdivisions"];dir=joinpath(out,"level-"*string(index));mkdir(dir)
        axes=level["axes_ticks_m"]
        check(Float32.(axes[3])==original.grid.axes[3].ticks,"Z refinement is forbidden")
        for k in 1:3
            ticks=Float32.(axes[k])
            check(bytes2hex(sha256(reinterpret(UInt8,ticks)))==level["axis_float32_le_sha256"][k],"Axis hash changed")
            check(all(t->t in ticks,original.grid.axes[k].ticks),"Original ticks removed")
        end
        grid=SSD.CartesianGrid3D{Float32}((axis_copy(original.grid.axes[1],axes[1]),axis_copy(original.grid.axes[2],axes[2]),original.grid.axes[3]))
        SSD.check_grid(grid);check(prod(size(grid))<=7_000_000,"Node cap exceeded")
        check(collect(size(grid))==level["shape"],"Explicit shape mismatch")
        check(grid_digest(axes)==level["grid_float32_le_sha256"],"Explicit grid hash mismatch")
        save(joinpath(dir,"grid.json"),level)
        if index==8
            stage(out,"load_saved_unconverged_WP34",index)
            check(req["level8_continuation_seed"]["absolute_ref"]==joinpath(dirname(reqpath),"results-continuation","level-8","solved-WP34.jls"),"Bind the latest saved level8 seed in a new request")
            seed=deserialize(req["level8_continuation_seed"]["absolute_ref"])
            check(eltype(seed.data)==Float32 && size(seed.data)==size(grid),"Continuation seed shape or precision changed")
            check(all(seed.grid.axes[k].ticks==grid.axes[k].ticks for k in 1:3),"Continuation seed grid ticks changed")
            sim.weighting_potentials[34]=seed
            initial_state="pinned saved unconverged level8 WP34 loaded directly"
        else
            stage(out,"resample_original_WP34",index)
            # Level16 starts from ORIGINAL, never from continued level8.
            sim.weighting_potentials[34]=original[grid]
            initial_state="original WP34 resampled independently"
        end
        serialize(joinpath(dir,"starting-WP34.jls"),sim.weighting_potentials[34])
        stage(out,"CPU_solve_WP34",index);started=time_ns()
        history=joinpath(dir,"update-history.jsonl")
        last_update,iterations,stop_reason,native_update=update_native_history!(sim,history,parse(Float64,ENV["GEGI_WP34_DEADLINE_UNIX"]))
        elapsed=(time_ns()-started)/1e9
        serialize(joinpath(dir,"solved-WP34.jls"),sim.weighting_potentials[34])
        converged=isfinite(last_update) && last_update<=Float32(1e-6)
        receipt=Dict("last_update"=>isfinite(last_update) ? Float64(last_update) : nothing,
            "last_update_raw"=>string(last_update),"converged"=>converged,"solve_seconds"=>elapsed,
            "iterations_performed"=>iterations,"max_n_iterations"=>10000,"initial_state"=>initial_state,
            "stop_reason"=>stop_reason,"native_half1_last_update"=>isfinite(native_update) ? Float64(native_update) : nothing,
            "update_history_sha256"=>hashfile(history),"absolute_full_max_limit"=>1e-6,
            "external_acceptance_last_update_limit"=>1e-6,
            "solver_scope"=>"Last-update stopping gate only, not PDE/grid/global detector validation")
        save(joinpath(dir,"solver.json"),receipt)
        check(converged,"WP34 unconverged; preserve returned state and stop without another solve")
        rows=Dict()
        for row in req["path_rows"]
            key=string(row["raw_row_index"]);q=waveform(sim,recorded[key]);base=baseline[key]["waveform_keV"]
            check(length(q)==length(base),"Fixed path waveform grid changed")
            rows[key]=Dict("time_ns"=>baseline[key]["time_ns"],"signed_induced_keV"=>q,
                "minus_original_keV"=>q-base,"minus_previous_level_keV"=>haskey(previous,key) ? q-previous[key] : nothing,
                "potentials"=>path_values(sim,sim.weighting_potentials[34],recorded[key]))
            previous[key]=q
        end
        save(joinpath(dir,"path-waveforms.json"),rows)
        check(sim.electric_potential===oldEP && sim.electric_field===oldEF && all(sim.weighting_potentials[cid]===otherWP[cid] for cid in 1:33),
            "Unrelated field state was replaced")
        save(joinpath(dir,"COMPLETE.json"),Dict("status"=>"completed_local_WP34_level","solver"=>receipt,
            "solved_WP_sha256"=>hashfile(joinpath(dir,"solved-WP34.jls")),"path_waveforms_sha256"=>hashfile(joinpath(dir,"path-waveforms.json"))))
        push!(completed,receipt);stage(out,"level_completed",index);GC.gc()
    end
    check(hashfile(cache)==req["field_cache"]["sha256"],"Original cache bytes changed")
    save(joinpath(out,"COMPLETE.json"),Dict("status"=>"completed_local_two_level_WP34_pilot","levels"=>completed,
        "request_sha256"=>hashfile(reqpath),"global_validation"=>false,"new_drift_calls"=>0,
        "new_Epotential_or_Efield_solves"=>0,"new_calibration_calls"=>0))
end
check(length(ARGS)==2,"Pass approved request and new output root")
try
    main(ARGS[1],ARGS[2])
catch err
    save(joinpath(ARGS[2],"failure.json"),Dict("status"=>"failed_stop","error"=>sprint(showerror,err),"automatic_retry"=>false))
    rethrow()
end
'''


def execute(request_path, approval_sha):
    request_path = Path(request_path).resolve(); digest = sha(request_path)
    if approval_sha != digest:
        raise ValueError('Explicit human approval must bind this exact request SHA256')
    request = json.loads(request_path.read_bytes())
    if request['kind'] == 'gegi_single_guard34_strict_stop_v1' and request['contact_id'] == 34:
        budget, output_name, worker_name = 300, 'results-strict-stop', 'WP34-worker.jl'
        worker_source, solve_key = JULIA_WORKER, 'maximum_new_WP34_solves'
    elif (request['kind'] == 'gegi_fixed_channels_17_20_level16_v1' and request['contact_ids'] == [17, 20]
          and len(request['levels']) == 1 and request['levels'][0]['central_subdivisions'] == 16):
        from gegi_channel_grid_pilot import JULIA_WORKER as channel_worker
        budget, output_name, worker_name = 600, 'results-channels-17-20', 'WP-channels-worker.jl'
        worker_source, solve_key = channel_worker, 'maximum_new_WP_solves'
    else:
        raise ValueError('Unsupported or enlarged weighting-potential scope')
    expected = {solve_key: 2, 'maximum_total_wall_seconds': budget, 'threads': 1,
                'maximum_nodes_per_level': 7000000}
    if request['resource_caps'] != expected:
        raise ValueError('Approved resource limits changed')
    if request['memory_policy'] != 'measure_only_not_a_launch_or_stop_condition':
        raise ValueError('Unsupported memory policy')
    for ref, expected_sha in request['input_file_sha256'].items():
        if sha(ROOT/ref) != expected_sha:
            raise ValueError('Pinned input/source changed: '+ref)
    try:
        available_before = available_memory()
    except OSError:
        available_before = None
    output = request_path.parent/output_name; output.resolve().relative_to((ROOT/'.local').resolve()); output.mkdir()
    (output/'approved-request.json').write_bytes(request_path.read_bytes())
    worker = output/worker_name; worker.write_text(worker_source, encoding='utf-8')
    env = os.environ.copy(); env.update(JULIA_PKG_OFFLINE='true', JULIA_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1')
    command = [request['environment']['julia_executable'], '--startup-file=no', '--compiled-modules=existing', '--threads=1',
               '--project='+str(ROOT/'simulation'), str(worker), str(request_path), str(output)]
    class PMC(ctypes.Structure):
        _fields_ = [('cb', ctypes.c_ulong), ('faults', ctypes.c_ulong)] + [(k, ctypes.c_size_t) for k in
            ('peak', 'working', 'qpp', 'qp', 'qpnp', 'qnp', 'pagefile', 'peak_pagefile', 'private')]
    getmem = ctypes.windll.psapi.GetProcessMemoryInfo
    getmem.argtypes = [ctypes.c_void_p, ctypes.POINTER(PMC), ctypes.c_ulong]; getmem.restype = ctypes.c_int
    started = time.monotonic(); peak = None; missing_memory_samples = 0; stop = None
    with (output/'worker.log').open('x', encoding='utf-8') as log:
        env['GEGI_WP34_DEADLINE_UNIX'] = str(time.time()+budget)
        child = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
        while child.poll() is None:
            memory = PMC(); memory.cb = ctypes.sizeof(memory)
            if getmem(ctypes.c_void_p(int(child._handle)), ctypes.byref(memory), memory.cb):
                peak = max(peak or 0, memory.peak)
            else:
                missing_memory_samples += 1
            if time.monotonic()-started >= budget:
                stop = f'{budget}_second_total_budget'; child.kill(); break
            time.sleep(.1)
        code = child.wait()
    receipt = {'returncode': code, 'stop_reason': stop, 'elapsed_seconds': time.monotonic()-started,
               'peak_working_set_bytes': peak, 'available_physical_before_bytes': available_before,
               'unavailable_process_memory_samples': missing_memory_samples,
               'memory_policy': request['memory_policy'], 'request_sha256': digest, 'runner_sha256': sha(__file__),
               'worker_sha256': sha(worker), 'automatic_retry': False,
               'status': 'completed_local_pilot' if code == 0 else 'failed_or_stopped_preserve_partial'}
    (output/'runtime.json').write_text(json.dumps(receipt, indent=2)+'\n', encoding='utf-8')
    return receipt


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--request', type=Path, required=True)
    p.add_argument('--owner-approved-request-sha256', required=True); a = p.parse_args()
    result = execute(a.request, a.owner_approved_request_sha256)
    print(json.dumps(result, indent=2)); raise SystemExit(0 if result['returncode'] == 0 else 1)
