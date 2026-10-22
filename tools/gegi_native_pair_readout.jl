# Saved complete charge -> existing Julia electronics. No native simulation calls.
include(joinpath(@__DIR__,"..","simulation","gegi_response.jl"))
using JSON, LinearAlgebra
const G=GeGIResponse
BLAS.set_num_threads(1)
Threads.nthreads()==1 || error("Use one Julia thread")
length(ARGS)==2 || error("Use REQUEST NEW_OUTPUT")
started=time(); request=JSON.parsefile(ARGS[1]); root=request["root"]
for (ref,digest) in request["source_sha256"]
    G.hashfile(joinpath(root,ref))==digest || error("Source changed: "*ref)
end
for (ref,digest) in request["input_sha256"]
    G.hashfile(joinpath(root,ref))==digest || error("Saved input changed: "*ref)
end
recipe=request["recipe"]; config=recipe["readout_config"]; cal=recipe["electronics_calibration"]
profile=G.P.load(request["profile_ref"])
G.P.validate_resolved(config,profile.profile,config["expected_primary_count"])
dt=cal["time_step_ns"]; matrix=G.E.transition(config,dt)
recipe["drift_dt_ns"]==dt || error("Frozen time step mismatch")
recipe["ionisation_energy_eV"]==cal["ionisation_energy_eV"] || error("Frozen material calibration mismatch")
rows=Any[]
ledgerpath=joinpath(dirname(ARGS[2]),"readout-records.jsonl")
(ispath(ARGS[2]) || ispath(ledgerpath)) && error("Preserve existing readout outputs")
open(ledgerpath,"w") do ledger
    for item in request["cases"]
        components=[JSON.parsefile(joinpath(root,c["ref"]))["payload"] for c in item["components"]]
        channel_rows=Any[]
        case_started=time()
        for channel in recipe["channels"]
            id=channel["id"]
            signals=Any[]
            for (index,payload) in enumerate(components)
                wave=payload["channel_signals"][id]
                wave["contact_id"]==id || error("Native channel order changed")
                push!(signals,(delay=Float64(item["time_offsets_ns"][index]),
                    times=Float64.(wave["time_ns"]),charge=Float64(item["mixing_weights"][index]).*Float64.(wave["signed_induced_keV"])))
            end
            t,q=G.R.causal_sum(signals,dt)
            scalar=G.channel_response(t,q,channel,config,recipe["ionisation_energy_eV"],cal,matrix;horizon_ns=nothing)
            # Display traces are a deterministic derivative; retain every scalar
            # and extrema of the full original signed native support instead.
            delete!(scalar,"trace")
            scalar["native_signed_min_keV"]=minimum(q)
            scalar["native_signed_max_keV"]=maximum(q)
            scalar["native_signed_peak_to_peak_keV"]=maximum(q)-minimum(q)
            scalar["native_sample_count"]=length(t)
            scalar["native_end_ns"]=last(t)
            scalar["channel_name"]=channel["name"]
            scalar["family"]=channel["family"]
            push!(channel_rows,scalar)
        end
        row=Dict("mixture_index"=>item["mixture_index"],"channels"=>channel_rows,
            "component_support"=>[c["complete_support"] for c in item["components"]],"seconds"=>time()-case_started)
        push!(rows,row);println(ledger,JSON.json(row));flush(ledger)
    end
end
result=Dict("kind"=>"gegi_native_pair_readout_julia_v1","request_sha256"=>G.hashfile(ARGS[1]),"cases"=>rows,
    "seconds"=>time()-started,"environment"=>Dict("julia_version"=>string(VERSION),"julia_threads"=>Threads.nthreads(),"blas_threads"=>BLAS.get_num_threads()),
    "units"=>Dict("native_charge"=>"keV equivalent, signed before fixed family wiring","time"=>"ns","voltage"=>"V"))
open(ARGS[2],"w") do io;JSON.print(io,result);write(io,'\n');end
