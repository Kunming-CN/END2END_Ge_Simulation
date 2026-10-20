#= Bounded read-only endpoint query of a checksum-pinned existing SSD state.

Read a JSON envelope from stdin and write one new JSON result to ARGS[1]. The
envelope supplies recorded starts/endpoints and the original native terminal
values. This script has no field-solve, drift, injection, or waveform-generation
entry. Two-coordinate _calculate_signal calls evaluate the existing endpoint
algebra only; their timestamps are unused by NoChargeTrappingModel.
=#
using SolidStateDetectors, Serialization, JSON, SHA, Unitful, LinearAlgebra
const SSD = SolidStateDetectors
BLAS.set_num_threads(1)
const ROOT = normpath(joinpath(@__DIR__, ".."))
hashfile(p) = open(io -> bytes2hex(sha256(io)), p)
check(ok, message) = ok || throw(ArgumentError(message))

function owned_path(ref)
    path = realpath(isabspath(ref) ? ref : joinpath(ROOT, ref))
    check(startswith(path, realpath(ROOT)*Base.Filesystem.path_separator), "Input outside project")
    path
end

point_saved_endpoint(::Type{T}, xyz) where T = SSD.CartesianPoint{T}((T.(Float64.(xyz)./1000))...)
point_original_start(::Type{T}, xyz) where T = SSD.CartesianPoint{T}((T.(xyz)./T(1000))...)
coordinates_mm(p) = Float64[p.x,p.y,p.z].*1000
contact_ids(sim,p) = [c.id for c in sim.detector.contacts if p in c.geometry]

function corner_diagnostic(wp, p, contact)
    axes = [wp.grid.axes[k].ticks for k in 1:3]
    xyz = (p.x,p.y,p.z)
    ix = [clamp(searchsortedlast(axes[k],xyz[k]),1,length(axes[k])-1) for k in 1:3]
    corners = Any[]
    for i in ix[1]:ix[1]+1, j in ix[2]:ix[2]+1, k in ix[3]:ix[3]+1
        q = SSD.CartesianPoint(axes[1][i],axes[2][j],axes[3][k])
        push!(corners, Dict("position_mm"=>coordinates_mm(q),"weighting_potential"=>Float64(wp.data[i,j,k]),
            "inside_recorded_contact_geometry"=>q in contact.geometry))
    end
    Dict("bracketing_corners"=>corners)
end

function run_query(payload, input_sha)
    check(Threads.nthreads()==1, "Use one Julia thread")
    check(payload["kind"]=="gegi_saved_endpoint_weight_query_v1", "Unknown query schema")
    steps = payload["steps"]
    check(1<=length(steps)<=64 && length(payload["native_terminal_signed_keV"])==34, "Query exceeds bound")
    cache = owned_path(payload["field_cache"]["ref"])
    model = owned_path(payload["model_ref"])
    check(hashfile(cache)==payload["field_cache"]["sha256"], "Pinned native cache changed")
    check(hashfile(model)==payload["model_sha256"]==payload["field_cache"]["model_sha256"], "Pinned model changed")
    # Cartesian interpolation references each existing data array. Deserialization
    # is streamed, with a 25% state/object allowance and 768MiB physical reserve.
    before = Sys.free_memory(); estimated = ceil(Int,1.25*filesize(cache))
    reserve = 768*1024^2
    println(JSON.json(Dict("stage"=>"memory_preflight", "available_physical_bytes"=>before,
        "cache_bytes"=>filesize(cache), "estimated_state_bytes"=>estimated,"reserve_bytes"=>reserve)))
    flush(stdout)
    check(before>=estimated+reserve, "Insufficient physical headroom for saved state; no load attempted")
    tick=time_ns(); sim=deserialize(cache); load_s=(time_ns()-tick)/1e9
    check(length(sim.detector.contacts)==34 && length(sim.weighting_potentials)==34, "Not the34contact state")
    check(sim.detector.semiconductor.charge_trapping_model isa SSD.NoChargeTrappingModel,
        "Endpoint-only algebra requires the original no-trapping model")
    T=SSD.get_precision_type(sim); CS=SSD.get_coordinate_system(sim)
    check(CS==SSD.Cartesian, "Only the original Cartesian state is supported")
    check(Sys.free_memory()>=512*1024^2, "Insufficient physical reserve after saved-state load")
    starts=[point_original_start(T,s["position_mm"]) for s in steps]
    electrons=[point_saved_endpoint(T,only(filter(ep->ep["species"]=="electron",s["endpoints"]))["position_mm"]) for s in steps]
    holes=[point_saved_endpoint(T,only(filter(ep->ep["species"]=="hole",s["endpoints"]))["position_mm"]) for s in steps]
    records=Any[]
    for (i,s) in enumerate(steps)
        emeta=only(filter(ep->ep["species"]=="electron",s["endpoints"]))
        hmeta=only(filter(ep->ep["species"]=="hole",s["endpoints"]))
        check(contact_ids(sim,electrons[i])==emeta["contact_ids"] && contact_ids(sim,holes[i])==hmeta["contact_ids"],
            "Saved/current contact mapping differs")
        push!(records,Dict("input_step_index"=>s["input_step_index"],"raw_row_index"=>s["raw_row_index"],
            "energy_keV"=>s["energy_keV"],"start_position_mm_native_precision"=>coordinates_mm(starts[i]),
            "electron_position_mm"=>coordinates_mm(electrons[i]),"hole_position_mm"=>coordinates_mm(holes[i]),
            "electron_contact_ids"=>contact_ids(sim,electrons[i]),"hole_contact_ids"=>contact_ids(sim,holes[i]),
            "start_weighting_potentials"=>zeros(34),"electron_weighting_potentials"=>zeros(34),
            "hole_weighting_potentials"=>zeros(34),"terminal_signed_keV_from_exact_endpoint_algebra"=>zeros(34),
            "own_contact_corner_diagnostics"=>Dict()))
    end
    totals=zeros(34)
    factor=T(ustrip(u"keV",SSD._convert_internal_energy_to_external_unit(u"keV",sim.detector.semiconductor.material)))
    for cid in 1:34
        check(!ismissing(sim.weighting_potentials[cid]),"Missing pinned weighting potential")
        wp=sim.weighting_potentials[cid]
        itp=SSD.interpolated_scalarfield(wp)
        for (i,s) in enumerate(steps)
            r=records[i]
            for (key,point) in (("start_weighting_potentials",starts[i]),("electron_weighting_potentials",electrons[i]),("hole_weighting_potentials",holes[i]))
                r[key][cid]=Float64(SSD.get_interpolation(itp,point,CS))
            end
            charge=T(SSD.to_internal_units(s["energy_keV"]*u"keV"))
            # Same SSD no-trapping multiplication and Float32 addition/conversion
            # as get_signal; no path between the saved coordinates is inferred.
            es=SSD._calculate_signal(sim.detector.semiconductor.charge_trapping_model,
                [starts[i],electrons[i]],T[0,1],-charge,itp,sim.point_types)
            hs=SSD._calculate_signal(sim.detector.semiconductor.charge_trapping_model,
                [starts[i],holes[i]],T[0,1],charge,itp,sim.point_types)
            value=Float64(T((last(es)+last(hs))*factor))
            r["terminal_signed_keV_from_exact_endpoint_algebra"][cid]=value
            totals[cid]+=value
            for (species,point,key) in (("electron",electrons[i],"electron_contact_ids"),("hole",holes[i],"hole_contact_ids"))
                if cid in r[key]
                    r["own_contact_corner_diagnostics"][species]=corner_diagnostic(wp,point,sim.detector.contacts[cid])
                end
            end
        end
        itp=nothing # The next contact reuses the same saved arrays, without34copies.
    end
    saved=Float64.(payload["native_terminal_signed_keV"])
    for r in records
        for prefix in ("start","electron","hole")
            values=r[prefix*"_weighting_potentials"]
            r[prefix*"_weighting_partition_sum"]=sum(values)
        end
    end
    pkgroot=dirname(dirname(pathof(SSD)))
    refs=("Event/Event.jl","SignalGeneration/SignalGeneration.jl","ChargeTrapping/ChargeTrapping.jl",
        "ElectricField/ElectricField.jl","Simulation/Simulation.jl","ChargeDrift/ChargeDrift.jl","Units.jl")
    Dict("kind"=>"gegi_saved_endpoint_weight_result_v1","input_sha256"=>input_sha,
        "scope"=>"Saved starts/endpoints only; no new trajectories, fields, injection, or native event replay",
        "original_identity"=>payload["original_identity"],"original_bindings"=>payload["original_bindings"],
        "field_cache"=>payload["field_cache"],"model_sha256"=>payload["model_sha256"],
        "julia_version"=>string(VERSION),"SSD_version"=>string(pkgversion(SSD)),"SSD_path"=>pkgroot,
        "science_source_sha256"=>Dict(ref=>hashfile(joinpath(pkgroot,"src",ref)) for ref in refs),
        "diagnostic_source_sha256"=>hashfile(@__FILE__),"native_precision_bits"=>8sizeof(T),
        "memory"=>Dict("available_before_load_bytes"=>before,"estimated_state_bytes"=>estimated,
            "physical_reserve_bytes"=>reserve,"available_after_queries_bytes"=>Sys.free_memory(),
            "julia_maxrss_bytes"=>Sys.maxrss()),"deserialize_seconds"=>load_s,
        "predicted_terminal_signed_keV"=>totals,"saved_terminal_signed_keV"=>saved,
        "predicted_minus_saved_terminal_keV"=>totals-saved,"max_abs_prediction_error_keV"=>maximum(abs.(totals-saved)),
        "partition_sum_at_saved_terminals"=>sum(totals),"deposits"=>records,
        "new_field_solves"=>0,"new_drift_calls"=>0,"new_calibration_calls"=>0)
end

check(length(ARGS)==1,"Pass one new output path; query JSON is read from stdin")
output=abspath(ARGS[1]);check(!ispath(output),"Preserve existing result")
check(startswith(output,realpath(joinpath(ROOT,".local"))*Base.Filesystem.path_separator),"Output must be below project .local")
input=read(stdin,String);payload=JSON.parse(input)
result=run_query(payload,bytes2hex(sha256(input)))
open(output,"w") do io; JSON.print(io,result,2);println(io);end
println(JSON.json(Dict("stage"=>"completed_saved_endpoint_query","deposits"=>length(result["deposits"]),
    "max_abs_prediction_error_keV"=>result["max_abs_prediction_error_keV"],"memory"=>result["memory"])))
