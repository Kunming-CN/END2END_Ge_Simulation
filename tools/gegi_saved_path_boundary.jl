# Read-only original/candidate weighting signals on three captured native paths.
# Candidate: geometric contact membership => Dirichlet1/0; all other samples
# retain the original Cartesian interpolant. This is an unvalidated candidate.
using SolidStateDetectors, Serialization, JSON, SHA, Unitful, LinearAlgebra
const SSD=SolidStateDetectors
BLAS.set_num_threads(1)
const REQUEST_SHA="c514ed87e5b033f6d52a1cc2e586c365c45fc9ec74efd397939b1f4bd603b11b"
const LAMBDAS=(0.,.5,.9,.99,.999,1.)
check(ok,message)=ok || throw(ArgumentError(message))
hashfile(p)=open(io->bytes2hex(sha256(io)),p)
coordinates(p)=Float64[p.x,p.y,p.z]
contacts(sim,p)=[c.id for c in sim.detector.contacts if p in c.geometry]
function save(path,value)
    check(!ispath(path),"Preserve existing derived evidence")
    open(path*".pending","w") do io;JSON.print(io,value,2);println(io);end
    mv(path*".pending",path)
end
function resample_add!(signal,timestamps,path_times,tmp)
    # Same temporal operations/order as SSD SignalGeneration.add_signal!: only
    # the supplied path-potential samples differ for the candidate calculation.
    itp=SSD.interpolate!((path_times,),tmp,SSD.Gridded(SSD.Linear()))
    i_max=searchsortedlast(timestamps,last(path_times))
    signal[1:i_max]+=itp(timestamps[1:i_max])
    length(signal)>i_max && (signal[i_max+1:end].+=tmp[end])
    nothing
end
bits_equal(a::Vector{T},b::Vector{T}) where T = reinterpret(UInt8,a)==reinterpret(UInt8,b)

function main(requestpath,out)
    check(Threads.nthreads()==1,"Use one Julia thread")
    check(hashfile(requestpath)==REQUEST_SHA,"Approved capture request changed")
    req=JSON.parsefile(requestpath);capture=joinpath(dirname(requestpath),"results")
    whole=JSON.parsefile(joinpath(capture,"COMPLETE.json"))
    check(whole["status"]=="completed_original_forward_pilot","Capture incomplete")
    check([d["raw_row_index"] for d in req["deposits"]]==[10191,10186,10185],"Fixed development rows changed")
    pkgroot=dirname(dirname(pathof(SSD)))
    for (ref,digest) in req["environment"]["SSD_science_source_sha256"]
        check(hashfile(joinpath(pkgroot,"src",ref))==digest,"SSD source changed: "*ref)
    end
    cache=req["field_cache"]["absolute_ref"]
    check(hashfile(cache)==req["field_cache"]["sha256"],"Pinned native cache changed")
    check(hashfile(req["model"]["absolute_ref"])==req["model"]["sha256"],"Pinned model changed")
    # All original capture bytes are checked before the single state load.
    bindings=Dict()
    for deposit in req["deposits"]
        row=string(deposit["raw_row_index"]);dir=joinpath(capture,"row-"*row)
        done=JSON.parsefile(joinpath(dir,"COMPLETE.json"))
        for (ref,digest) in done["file_sha256"]
            check(hashfile(joinpath(dir,ref))==digest,"Captured row artifact changed")
        end
        bindings[row]=Dict("complete_sha256"=>hashfile(joinpath(dir,"COMPLETE.json")),"artifacts"=>done["file_sha256"])
    end
    available=Sys.free_memory();estimate=ceil(Int,1.25*filesize(cache));reserve=768*1024^2
    println(JSON.json(Dict("stage"=>"memory_preflight","available_physical_bytes"=>available,
        "estimated_state_bytes"=>estimate,"reserve_bytes"=>reserve)));flush(stdout)
    check(available>=estimate+reserve,"Insufficient physical headroom; no state loaded")
    sim=deserialize(cache);check(Sys.free_memory()>=512*1024^2,"Insufficient physical reserve after load")
    T=SSD.get_precision_type(sim);check(T==Float32,"Original native precision changed")
    check(SSD.get_coordinate_system(sim)==SSD.Cartesian,"Original coordinate system changed")
    ctm=sim.detector.semiconductor.charge_trapping_model
    check(ctm isa SSD.NoChargeTrappingModel,"Only original no-trapping model is supported")
    guard_grids=Dict(string(cid)=>Dict("shape"=>collect(size(sim.weighting_potentials[cid].data)),
        "axis_ticks_m"=>[Float64.(sim.weighting_potentials[cid].grid.axes[k].ticks) for k in 1:3]) for cid in (17,34))
    dt=T(SSD.to_internal_units(1u"ns"))
    factor=T(ustrip(u"keV",SSD._convert_internal_energy_to_external_unit(u"keV",sim.detector.semiconductor.material)))
    summary=Any[];started=time_ns()
    for deposit in req["deposits"]
        row=string(deposit["raw_row_index"]);inputdir=joinpath(capture,"row-"*row)
        dir=joinpath(out,"row-"*row);mkdir(dir)
        recorded=deserialize(joinpath(inputdir,"paths.jls"))
        check(recorded.field_cache_sha256==req["field_cache"]["sha256"],"Captured path field binding changed")
        paths=recorded.drift_paths;check(length(paths)==1,"Unexpected path census")
        path=only(paths);energies=SSD.flatview(recorded.energies);charge=only(energies)
        times=SSD._common_timestamps(paths,dt)
        pointsets=Dict("electron"=>path.e_path,"hole"=>path.h_path)
        path_times=Dict("electron"=>path.timestamps_e,"hole"=>path.timestamps_h)
        memberships=Dict(species=>[contacts(sim,p) for p in ps] for (species,ps) in pointsets)
        check(all(length(ids)<=1 for ms in values(memberships) for ids in ms),"Ambiguous overlapping contact membership")
        phi=Dict(species=>[zeros(34) for p in ps] for (species,ps) in pointsets)
        segments=Dict()
        for species in ("electron","hole")
            ps=pointsets[species];ids=memberships[species]
            crossings=[i for i in 1:length(ps)-1 if isempty(ids[i]) && !isempty(ids[i+1])]
            check(!isempty(crossings),"No saved noncontact-to-contact segment")
            i=last(crossings);a=ps[i];b=ps[i+1]
            points=[lambda==0 ? a : lambda==1 ? b : a+T(lambda)*(b-a) for lambda in LAMBDAS]
            segments[species]=Dict("last_noncontact_index"=>i,"first_contact_index"=>i+1,
                "points"=>[Dict("lambda"=>lambda,"position_m"=>coordinates(p),"contact_ids"=>contacts(sim,p),
                    "original_phi"=>zeros(34),"candidate_phi"=>zeros(34)) for (lambda,p) in zip(LAMBDAS,points)])
        end
        channel_summaries=Any[]
        for cid in 1:34
            wp=SSD.interpolated_scalarfield(sim.weighting_potentials[cid])
            original=zeros(T,length(times))
            SSD.add_signal!(original,times,paths,energies,wp,sim.point_types,ctm)
            original_keV=Float64.(original.*factor)
            captured=JSON.parsefile(joinpath(inputdir,"channel-"*lpad(string(cid),2,'0')*".json"))
            check(length(original_keV)==length(captured["signed_induced_keV"]),"Original signal sample census changed")
            saved=Float64.(captured["signed_induced_keV"])
            if !bits_equal(original_keV,saved)
                save(joinpath(dir,"baseline-failure.json"),Dict("contact_id"=>cid,
                    "max_abs_error_keV"=>maximum(abs.(original_keV-saved)),
                    "policy"=>"Stop before candidate interpretation; original full waveform is not bitexact"))
                error("Original full waveform not bitexact")
            end
            candidate=zeros(T,length(times));roundtrip=zeros(T,length(times))
            for (species,sign) in (("electron",-one(T)),("hole",one(T)))
                ps=pointsets[species];ids=memberships[species];q=sign*charge
                raw=T[SSD.get_interpolation(wp,p,SSD.Cartesian) for p in ps]
                adjusted=T[isempty(ids[k]) ? raw[k] : (cid in ids[k] ? one(T) : zero(T)) for k in eachindex(ps)]
                for k in eachindex(ps);phi[species][k][cid]=Float64(raw[k]);end
                resample_add!(roundtrip,times,path_times[species],raw.*q)
                resample_add!(candidate,times,path_times[species],adjusted.*q)
            end
            reconstructed=Float64.(roundtrip.*factor)
            check(bits_equal(reconstructed,saved),"Explicit phi/time reconstruction differs from original SSD operations")
            candidate_keV=Float64.(candidate.*factor);delta=candidate_keV-saved
            save(joinpath(dir,"candidate-channel-"*lpad(string(cid),2,'0')*".json"),
                Dict("time_ns"=>captured["time_ns"],"candidate_signed_induced_keV"=>candidate_keV,
                    "candidate_minus_original_keV"=>delta,"original_artifact_sha256"=>bindings[row]["artifacts"]["channel-"*lpad(string(cid),2,'0')*".json"]))
            push!(channel_summaries,Dict("contact_id"=>cid,"original_all_samples_bitexact"=>true,
                "explicit_phi_time_reconstruction_bitexact"=>true,"original_terminal_signed_keV"=>last(saved),
                "candidate_terminal_signed_keV"=>last(candidate_keV),"max_abs_waveform_change_keV"=>maximum(abs.(delta))))
            for (species,seg) in segments
                for point in seg["points"]
                    p=SSD.CartesianPoint{T}(T.(point["position_m"])...)
                    value=SSD.get_interpolation(wp,p,SSD.Cartesian)
                    point["original_phi"][cid]=Float64(value)
                    point["candidate_phi"][cid]=isempty(point["contact_ids"]) ? Float64(value) : (cid in point["contact_ids"] ? 1. : 0.)
                end
            end
        end
        pathrecords=Dict(species=>[Dict("position_m"=>coordinates(p),"timestamp_s"=>Float64(path_times[species][k]),
            "contact_ids"=>memberships[species][k],"original_phi"=>phi[species][k]) for (k,p) in enumerate(ps)]
            for (species,ps) in pointsets)
        save(joinpath(dir,"path-values.json"),Dict("paths"=>pathrecords,"near_boundary_segments"=>segments,
            "candidate_definition"=>"All path samples on a unique geometric contact use its Dirichlet1/0; all other samples retain original phi"))
        record=Dict("raw_row_index"=>deposit["raw_row_index"],"energy_keV"=>deposit["energy_keV"],
            "path_sample_counts"=>Dict(s=>length(ps) for (s,ps) in pointsets),"channels"=>channel_summaries,
            "guard_endpoint_axis_spacing_m"=>Dict(species=>[begin
                cid=species=="electron" ? 34 : 17
                ticks=sim.weighting_potentials[cid].grid.axes[k].ticks
                point=last(pointsets[species]);value=(point.x,point.y,point.z)[k]
                i=clamp(searchsortedlast(ticks,value),1,length(ticks)-1)
                Dict("lower_tick"=>Float64(ticks[i]),"upper_tick"=>Float64(ticks[i+1]),
                    "spacing"=>Float64(ticks[i+1]-ticks[i]))
                end for k in 1:3] for species in ("electron","hole")),
            "near_boundary_own_guard"=>Dict(s=>[Dict("lambda"=>p["lambda"],"contact_ids"=>p["contact_ids"],
                "original_phi"=>p["original_phi"][s=="electron" ? 34 : 17],
                "candidate_phi"=>p["candidate_phi"][s=="electron" ? 34 : 17]) for p in segments[s]["points"]]
                for s in ("electron","hole")),"candidate_status"=>"unvalidated_contact_boundary_candidate; inspect spatial discontinuity")
        save(joinpath(dir,"summary.json"),record);push!(summary,record)
        println(JSON.json(Dict("stage"=>"row_completed","row"=>row,"original_channels_bitexact"=>34)));flush(stdout)
    end
    result=Dict("kind"=>"gegi_saved_path_contact_boundary_candidate_v1","status"=>"completed_diagnostic_not_validated_repair",
        "request_sha256"=>REQUEST_SHA,"capture_complete_sha256"=>hashfile(joinpath(capture,"COMPLETE.json")),
        "model_sha256"=>req["model"]["sha256"],"field_cache_sha256"=>req["field_cache"]["sha256"],
        "source_sha256"=>hashfile(@__FILE__),"SSD_science_source_sha256"=>req["environment"]["SSD_science_source_sha256"],
        "original_artifacts"=>bindings,"guard_native_grids"=>guard_grids,"rows"=>summary,"query_and_signal_seconds"=>(time_ns()-started)/1e9,
        "new_drift_calls"=>0,"new_field_solves"=>0,"new_transport_calls"=>0,"new_calibration_calls"=>0,
        "limitation"=>"Contact-only Dirichlet substitution may introduce a spatial/waveform jump and is not an accepted correction")
    save(joinpath(out,"report.json"),result)
end

check(length(ARGS)==2,"Pass original capture request and a new derived directory")
requestpath=abspath(ARGS[1]);out=abspath(ARGS[2]);check(!ispath(out),"Preserve existing diagnostic")
check(startswith(out,dirname(requestpath)*Base.Filesystem.path_separator),"Output outside owned pilot root")
mkdir(out)
try
    main(requestpath,out)
catch err
    save(joinpath(out,"failure.json"),Dict("status"=>"stopped_failure","error"=>sprint(showerror,err),"retry"=>false))
    rethrow()
end
