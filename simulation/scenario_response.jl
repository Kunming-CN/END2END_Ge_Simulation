# Fresh rotated gamma connector. Original readers and numerical helpers stay unchanged.
include("gamma_native_example.jl")
module ScenarioResponse
using ..GammaNativeExample, JSON, SHA, Unitful
const G=GammaNativeExample;const B=G.B;const N=G.N;const R=G.R;const Q=G.Q;const E=G.E;const P=G.P
const ROOT=Q.ROOT
check=E.check
function hashfile(path)
    open(io->bytes2hex(sha256(io)),path)
end
function pins(d)
    for (name,value) in d["pins"]
        check(!isabspath(name) && !(".." in split(replace(name,'\\'=>'/'),'/')),"Unsafe request binding")
        path=joinpath(ROOT,name)
        check(isfile(path) && Q.childof(realpath(path),realpath(ROOT)) && hashfile(path)==value,"Scenario input/source changed: "*name)
    end
end
function validate(d)
    check(d["kind"]=="local_scenario_gamma_request_v1","Wrong gamma request kind")
    model=d["model_id"];check(model in ("AK02","SAP22"),"Unsupported gamma detector")
    m=d["source_manifest"];prepared=d["prepared"]
    check(m["kind"]=="scenario_gamma_event_stream_v1" && m["status"]=="complete" &&
          m["model_id"]==model && m["primary_count"]===20,"Gamma source/census mismatch")
    check(m["assets"]==prepared["assets"] && m["coordinate_transform"]==prepared["coordinate_transform"],"Gamma prepared identity mismatch")
    tr=m["coordinate_transform"]
    check(tr["rotation_local_to_global"]==[[1,0,0],[0,0,1],[0,-1,0]] &&
          tr["translation_global_mm"]==[0,1.45,0.29],"Unadmitted gamma transform")
    energy=G.effective_gamma_source(m,prepared)
    check(m["clock_policy"]=="synthetic_primary_time_zero","Gamma source clock mismatch")
    sparse=haskey(m,"gamma_source_configuration")
    if sparse
        check(G.typed_equal(get(d,"gamma_source_configuration",nothing),m["gamma_source_configuration"]),"Request effective gamma marker binding")
        policy=get(d,"event_storage",nothing)
        check(policy isa AbstractDict && G.typed_equal(policy,B.storage_descriptor(policy)) && policy["initial_primaries"]===20,
            "Sparse gamma complete census/denominator")
        check(G.typed_equal(policy,get(m,"event_storage",nothing)),"Source/request sparse gamma census differs")
        summary=m["initial_summary"]
        check(Set(keys(summary))==Set(("initial_primaries","initial_gamma_primaries","zero_deposit_primaries","nonzero_primaries")) &&
            summary["initial_gamma_primaries"]===20 &&
            all(summary[key]===policy[key] for key in ("initial_primaries","zero_deposit_primaries","nonzero_primaries")),"Gamma full initial summary")
    else
        check(!haskey(d,"event_storage") && !haskey(d,"gamma_source_configuration"),"Historical gamma response interpretation changed")
    end
    check(m["assets"]["detector"]["model_sha256"]==G.DETECTOR_PINS[model].model &&
          m["stored_temperature_K"]==78,"Gamma canonical model mismatch")
    check(d["threads"] in (1,2) && Threads.nthreads()==d["threads"],"Requested Julia threads mismatch")
    events=d["events"];check(length(events)==(sparse ? d["event_storage"]["nonzero_primaries"] : 20),"Gamma stored event census")
    previous=-1
    for (i,event) in enumerate(events)
        id=event["event_id"]
        check(id isa Integer && !(id isa Bool) && event["initial_primary_id"]===id && previous<id<20 &&
            (sparse || id==i-1),"Missing/duplicate gamma original ID")
        previous=id
        check(event["zero_ge"] isa Bool && event["zero_ge"]==(event["truth_ge_edep_keV"]==0),"Gamma zero identity mismatch")
        check(!sparse || !event["zero_ge"],"Sparse gamma retained zero-input event")
        particles=event["particles"];vtx=event["vtx"]
        check(length(particles)==length(vtx)==1 && particles[1]["particle"]===22 && vtx[1]["time"]==0 &&
            isapprox(particles[1]["ekin"],energy/1000;atol=1e-12,rtol=0) &&
            all(isapprox(particles[1][axis],expected;atol=1e-12,rtol=0) for (axis,expected) in zip(("px","py","pz"),(0.,-energy/1000,0.))) &&
            all(isapprox(1000vtx[1][axis],expected;atol=1e-10,rtol=0) for (axis,expected) in zip(("xloc","yloc","zloc"),m["source_position_global_mm"])),
            "Gamma initial energy/momentum/position differs from its effective source")
        check(length(event["steps"])==length(event["material_rows"]["stp/germanium"]),"Ge row census mismatch")
        for step in event["steps"]
            check(step["time_ns"]>=0 && step["energy_keV"]>=0,"Invalid deposition energy/time")
        end
    end
    check(d["readout_config"]["expected_primary_count"]===20,"Readout census mismatch")
    P.validate_resolved(d["readout_config"],d["profile"],20)
    pins(d);d
end
function gamma_geometry(prepared,sim)
    check(prepared["kind"]=="scenario_source_prepared_v1","Wrong gamma geometry preparation")
    G.B.S.transform(prepared["coordinate_transform"])
    actual=sort(collect(zip(1000 .* sim.detector.semiconductor.geometry.r,1000 .* sim.detector.semiconductor.geometry.z)))
    expected=sort([Tuple(Float64.(v)) for v in prepared["contour_rz_mm"]])
    check(length(actual)==length(expected) && all(isapprox.(first.(actual),first.(expected);rtol=0,atol=1e-10)) &&
          all(isapprox.(last.(actual),last.(expected);rtol=0,atol=1e-10)),"Gamma SSD/prepared contour mismatch")
    Dict("ssd_contour_matches"=>true,"proper_coordinate_transform"=>true,
         "source_kind"=>"synthetic_gamma","scope"=>"Native checked assembly plus SSD contour and transform")
end
function consumed_ledger(d,request)
    directory=dirname(request);transport=joinpath(directory,"transport")
    m=JSON.parsefile(joinpath(transport,"stream","manifest.json"));prepared=JSON.parsefile(joinpath(transport,"prepared.json"))
    check(G.typed_equal(m,d["source_manifest"]) && G.typed_equal(prepared,d["prepared"]),"Request differs from the bound original gamma ledger")
    chunks=m["chunks"];stored=haskey(d,"event_storage") ? d["event_storage"]["nonzero_primaries"] : 20
    check(length(chunks)==(stored==0 ? 0 : 1) && sum((chunk["count"] for chunk in chunks);init=0)==stored,"Unsupported gamma stored chunk census")
    events=Any[]
    for chunk in chunks
        file=chunk["file"];check(!isabspath(file) && !(".." in splitpath(file)),"Unsafe gamma ledger chunk")
        path=realpath(joinpath(transport,"stream",file))
        check(Q.childof(path,realpath(joinpath(transport,"stream"))) && hashfile(path)==chunk["sha256"],"Original gamma chunk changed")
        append!(events,[JSON.parse(line) for line in eachline(path)])
    end
    if haskey(d,"event_storage")
        check(G.typed_equal(m["event_storage"],d["event_storage"]) && length(events)==stored && all(e->!e["zero_ge"],events),
            "Sparse gamma request changed the complete original/nonzero census")
    end
    check(G.typed_equal(events,d["events"]),"Request changed original gamma rows, coordinates, times or identities")
    check(G.typed_equal(JSON.parsefile(joinpath(directory,"electronics","profile.json")),d["profile"]),"Request differs from the selected electronics profile")
end
function progress(out,stage,status;completed=0,total=nothing)
    value=Dict("kind"=>"scenario_response_progress_v1","stage"=>stage,"status"=>status,
               "completed_primary_count"=>completed,"expected_primary_count"=>total,
               "elapsed_seconds"=>time()-START[])
    tmp=joinpath(out,"progress.json.pending")
    write(tmp,JSON.json(value));mv(tmp,joinpath(out,"progress.json");force=true)
end
const START=Ref(0.)
function run(request,out)
    check(isfile(request) && 0<filesize(request)<=64*1024^2,"Missing/oversized scenario request")
    request=realpath(request);check(Q.childof(request,joinpath(realpath(ROOT),".local","runs")),"Request must belong to a local run")
    raw=read(request);d=validate(JSON.parse(String(copy(raw))));consumed_ledger(d,request)
    out=abspath(out);check(dirname(out)==dirname(request) && basename(out)=="response" && !ispath(out),"Fresh response root required")
    mkdir(out);START[]=time();Q.environment("cpu");E.environment()
    model=d["model_id"];sim,stored=R.setup_simulation(model;temperature=77.0)
    geom=gamma_geometry(d["prepared"],sim)
    R.validate_deposits(Dict("events"=>d["events"]),sim)
    bias=maximum(c.potential for c in sim.detector.contacts)-minimum(c.potential for c in sim.detector.contacts)
    check(bias==(model=="AK02" ? 500 : 700) && stored==78,"Loaded canonical settings changed")
    cfg=Q.parse_args(["--model",model,"--position-mm","3,0,5","--precision","64","--dt-ns","2",
        "--min-grid-mm","0.05","--max-iterations","50000","--contact","1","--output",joinpath(out,"unused")])
    c=d["readout_config"];eion=ustrip(u"eV",sim.detector.semiconductor.material.E_ionisation)
    report=Dict{String,Any}("kind"=>"local_scenario_gamma_response_v1","status"=>"running","model_id"=>model,
        "model_sha256"=>G.DETECTOR_PINS[model].model,"input_kind"=>"scenario_gamma_event_stream_v1",
        "request_sha256"=>bytes2hex(sha256(raw)),"configuration_sha256"=>d["configuration_sha256"],
        "source_lh5_sha256"=>d["source_manifest"]["source_lh5_sha256"],"source_manifest"=>d["source_manifest"],
        "stored_temperature_K"=>78,"temperature_K"=>77,"bias_V"=>bias,"readout_contact_id"=>1,
        "geometry_checks"=>geom,"parcels"=>16,"seed_family"=>2609261,"drift_dt_ns"=>2,
        "nominal_drift_cap_ns"=>10000,"native_failure_policy"=>"record","source_sha256"=>d["pins"],
        "diffusion"=>true,"end_drift_when_no_field"=>false,"self_repulsion"=>false,
        "field_settings"=>Dict("precision_bits"=>64,"min_spacing_mm"=>0.05,"max_spacing_mm"=>2,"sor"=>1,"potential_rechecks"=>4),
        "limitations"=>["Nominal engineering geometry and synthetic isolated electronics; no experimental fit or calibrated Li CCE.",
            "Field iteration gates are not grid/PDE/CCE convergence; numerical parcel variation is not physical resolution.",
            "Analog time samples are not waveform ADC samples; recorded material ledger does not establish full energy closure."],
        "runtime"=>G.runtime(),"cases"=>Any[],"units"=>Dict("charge"=>"fC","current"=>"nA","voltage"=>"V","energy"=>"keV","time"=>"ns"))
    sparse=haskey(d,"event_storage")
    if sparse
        report["event_storage"]=d["event_storage"];report["gamma_source_configuration"]=d["gamma_source_configuration"]
    end
    stage="electric_and_weighting_fields"
    try
        E.save(joinpath(out,"profile.json"),d["profile"]);E.save(joinpath(out,"readout-config.json"),c)
        report["guard"]=G.G.install!();progress(out,stage,"running")
        solver,timing=Base.invokelatest(Q.solve_fields!,sim,cfg,Q.prepare_backend("cpu");sor_consts=1.0,potential_rechecks=4)
        report["solver"]=solver;report["field_timings"]=timing;report["field_fingerprint"]=N.field_fingerprint(sim)
        progress(out,stage,"completed")
        stage="independent_injection_calibration";progress(out,stage,"running");t0=time()
        M=E.transition(c,2.);cal=P.calibration(c,eion,2.,M)
        report["calibration"]=cal;report["calibration_seconds"]=time()-t0;report["calibration_calls"]=1
        report["ionisation_energy_eV"]=eion;E.save(joinpath(out,"calibration.json"),cal)
        progress(out,stage,"completed");stage="charge_and_readout";progress(out,stage,"running";total=20)
        open(joinpath(out,"truth.jsonl"),"w") do truth
            open(joinpath(out,"signals.csv"),"w") do signals
                println(signals,"initial_primary_id,time_since_initial_primary_ns,induced_equivalent_energy_keV")
                for event in d["events"]
                    pins(d);println(truth,JSON.json(event))
                    native_input=Dict("event_id"=>event["event_id"],"primary_time_ns"=>0.,"steps"=>event["steps"])
                    rec=G.event_response(event,"record",
                        ()->Base.invokelatest(N.native_event,native_input,sim,cfg,16,2609261),
                        (t,q)->P.process(t,q,c,eion,cal,M),N.flags;allow_zero=!sparse)
                    check(N.field_fingerprint(sim)==report["field_fingerprint"],"Native response changed shared fields")
                    push!(report["cases"],rec);E.save(joinpath(out,"event-"*string(event["event_id"])*".json"),rec)
                    if rec["charge_input"]!==nothing
                        for (t,q) in zip(rec["charge_input"]["time_since_initial_primary_ns"],rec["charge_input"]["induced_equivalent_energy_keV"])
                            println(signals,join((event["initial_primary_id"],t,q),','))
                        end
                    end
                    progress(out,stage,"running";completed=length(report["cases"]),total=20)
                end
            end
        end
        cases=report["cases"];groups=count(e->!e["zero_ge"],d["events"])
        failures=count(e->e["status"]=="native_failed",cases)
        accepted=count(e->e["readout"]!==nothing && e["readout"]["accepted"],cases)
        readout_rejected=count(e->!e["zero_ge"] && e["readout"]!==nothing && !e["readout"]["accepted"],cases)
        zeros=sparse ? d["event_storage"]["zero_deposit_primaries"] : count(e->e["zero_ge"],d["events"])
        report["counts"]=Dict("initial_primaries"=>20,"initial_decays"=>nothing,
            "zero_deposit_primaries"=>zeros,"groups"=>groups,
            "accepted"=>accepted,"rejected"=>failures+readout_rejected,"native_failed_groups"=>failures,
            "readout_rejected"=>readout_rejected,"processed_primaries"=>20,"unprocessed_primaries"=>0,
            "line_photons"=>nothing,"decay_photons"=>nothing)
        if sparse;report["counts"]["nonzero_primaries"]=groups;end
        check(accepted+failures+readout_rejected==groups,"Gamma response accounting mismatch")
        pins(d);check(hashfile(request)==report["request_sha256"],"Request changed")
        report["native_drift_and_charge_seconds"]=sum((e["native_seconds"] for e in cases);init=0.0)
        report["electronics_seconds"]=sum((e["electronics_seconds"] for e in cases);init=0.0)
        report["status"]=failures>0 ? "completed_with_native_failures" : "completed"
        progress(out,stage,"completed";completed=20,total=20)
        # Presentation uses the existing signed four-plot renderer; no second plot engine.
        open(joinpath(out,"traces.jsonl"),"w") do io
            for rec in cases
                rec["readout"]===nothing && continue
                println(io,JSON.json(Dict("event_id"=>rec["event_id"],"group_id"=>rec["zero_ge"] ? nothing : 0,
                    "origin_time_ns"=>0.,"trace"=>rec["readout"]["trace"])))
            end
        end
        open(joinpath(out,"scalars.jsonl"),"w") do io
            for rec in cases;println(io,JSON.json(rec));end
        end
        open(joinpath(out,"scalars.csv"),"w") do io
            println(io,"initial_primary_id,truth_ge_edep_keV,final_induced_keV,reconstructed_energy_keV,status")
            for rec in cases
                vals=(rec["initial_primary_id"],rec["truth_ge_edep_keV"],rec["final_induced_keV"],
                    rec["readout"]===nothing ? nothing : rec["readout"]["reconstructed_energy_keV"],rec["status"])
                println(io,join(E.csvcell.(vals),','))
            end
        end
        open(joinpath(out,"endpoints.csv"),"w") do io
            println(io,"initial_primary_id,raw_row_index,parcel_index,endpoint_json")
            for rec in cases
                rec["native"]===nothing && continue
                for step in rec["native"]["steps"], endpoint in step["endpoints"]
                    println(io,join(E.csvcell.((rec["initial_primary_id"],step["raw_row_index"],endpoint["parcel_index"],endpoint)),','))
                end
            end
        end
        if failures>0
            open(joinpath(out,"native-failures.jsonl"),"w") do io
                for rec in cases;rec["status"]=="native_failed" && println(io,JSON.json(rec));end
            end
        end
        hist=Dict{String,Dict{Int,Int}}()
        if sparse;B.addhist!(hist,"deposited_per_primary",0.;weight=zeros);end
        for rec in cases
            B.addhist!(hist,"deposited_per_primary",rec["truth_ge_edep_keV"])
            rec["readout"]===nothing && continue
            B.group_hist!(hist,rec["truth_ge_edep_keV"],rec["charge_input"]["induced_equivalent_energy_keV"],rec["readout"],eion)
        end
        B.export_hist(out,hist,report["counts"],cal)
        report["artifacts"]=Dict(name=>hashfile(joinpath(out,name)) for name in readdir(out) if name!="run.json")
        view=copy(report);view["status"]=failures>0 ? "completed_with_native_failures" : "completed_provisional_native_response"
        B.summary_html(out,view)
        report["artifacts"]["summary.html"]=hashfile(joinpath(out,"summary.html"))
    catch err
        report["status"]="failed";report["failure_stage"]=stage;report["error"]=sprint(showerror,err)
        progress(out,stage,"failed";completed=length(report["cases"]),total=20)
        rethrow()
    finally
        report["solve_replay_readout_export_wall_seconds"]=time()-START[]
        E.save(joinpath(out,"run.json"),report)
    end
    report
end
end
if abspath(PROGRAM_FILE)==@__FILE__
    length(ARGS)==4 && ARGS[1]=="--request" && ARGS[3]=="--output" || error("Usage: scenario_response.jl --request FILE --output NEW")
    println(ScenarioResponse.JSON.json(ScenarioResponse.run(ARGS[2],ARGS[4])["counts"]))
end
