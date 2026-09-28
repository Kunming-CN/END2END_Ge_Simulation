# Analyze completed native-response checkpoints without rerunning physics.
using Serialization, JSON, SHA, Dates
const ROOT=normpath(joinpath(@__DIR__,".."))
hashfile(p)=open(io->bytes2hex(sha256(io)),p)
check(x,m)=x ? nothing : throw(ArgumentError(m))
csvcell(x)=x===nothing ? "" : x isa Bool ? (x ? "true" : "false") :
    x isa Number ? string(x) : "\""*replace(string(x),"\"" => "\"\"")*"\""
function group_energy(r)
    rows=Set(Int.(r["group"]["row_indices"]))
    sum(s["energy_keV"] for s in r["event"]["steps"] if s["raw_row_index"] in rows;init=0.0)
end
objhash(x)=bytes2hex(sha256(codeunits(JSON.json(x))))
function modelof(key)
    startswith(key,"AK02_") && return "AK02"
    startswith(key,"SAP22_") && return "SAP22"
    error("Unknown model key: "*key)
end
function failure_class(r)
    r["status"]=="native_failed" || return nothing
    haskey(r,"failure_class") && return r["failure_class"]
    e=r["error"]; e===nothing && return "unknown_native_failure"
    typ=string(get(e,"type","")); msg=string(get(e,"message",""))
    typ=="NativeBoundaryStall" && return "boundary_stall"
    msg=="Noncontact endpoint outside crystal" && return "noncontact_endpoint"
    msg=="Invalid waveform support" && return "invalid_waveform_support"
    "other_native_failure"
end
const COLS=("model","event_id","group_id","status","failure_class","accepted",
    "rejection_reason","deposited_keV","induced_keV","analog_keV","reconstructed_keV",
    "adc_code","carrier_parcels","geometric_contacts","step_limits",
    "stopped_without_contact","negative_input","below_threshold","saturated",
    "gate_limited","window_limited","contact_start_energy_keV","error_type",
    "error_message","result_key")
function scalar_record(r)
    model=modelof(r["key"]); status=r["status"]; ok=status=="native_completed"
    readout=ok ? r["readout"] : nothing; flags=ok ? r["transport_flags"] : nothing
    err=r["error"]; fc=failure_class(r)
    Dict{String,Any}(
        "model"=>model,"event_id"=>r["event"]["event_id"],
        "group_id"=>r["group"]["group_id"],"status"=>status,"failure_class"=>fc,
        "accepted"=>r["accepted"],"rejection_reason"=>readout===nothing ? nothing : readout["rejection_reason"],
        "deposited_keV"=>group_energy(r),
        "induced_keV"=>ok ? last(r["native"].signal) : nothing,
        "analog_keV"=>readout===nothing ? nothing : readout["analog_energy_keV"],
        "reconstructed_keV"=>readout===nothing ? nothing : readout["reconstructed_energy_keV"],
        "adc_code"=>readout===nothing ? nothing : readout["adc_code"],
        "carrier_parcels"=>flags===nothing ? nothing : flags["carrier_parcels"],
        "geometric_contacts"=>flags===nothing ? nothing : flags["geometric_contacts"],
        "step_limits"=>flags===nothing ? nothing : flags["step_limits"],
        "stopped_without_contact"=>flags===nothing ? nothing : flags["stopped_without_contact"],
        "negative_input"=>readout===nothing ? nothing : readout["negative_input"],
        "below_threshold"=>readout===nothing ? nothing : readout["below_threshold"],
        "saturated"=>readout===nothing ? nothing : readout["saturated"],
        "gate_limited"=>readout===nothing ? nothing : readout["gate_limited"],
        "window_limited"=>readout===nothing ? nothing : readout["window_limited"],
        "contact_start_energy_keV"=>fc=="input_domain_compatibility" ?
            get(err,"contact_energy_keV",nothing) : nothing,
        "error_type"=>err===nothing ? nothing : get(err,"type",nothing),
        "error_message"=>err===nothing ? nothing : get(err,"message",nothing),
        "result_key"=>r["key"])
end
function newstats()
    Dict{String,Any}("groups"=>0,"native_completed"=>0,"native_failed"=>0,
        "accepted"=>0,"readout_rejected"=>0,"groups_with_step_limits"=>0,
        "step_limits"=>0,"groups_stopped_without_contact"=>0,"stopped_without_contact"=>0,
        "negative_input_groups"=>0,"below_threshold_groups"=>0,"saturated_groups"=>0,
        "gate_limited_groups"=>0,"window_limited_groups"=>0,
        "failure_classes"=>Dict{String,Int}(),"rejection_reasons"=>Dict{String,Int}())
end
inc!(d,k,n=1)=(d[k]=get(d,k,0)+n)
function addstats!(s,r)
    s["groups"]+=1
    if r["status"]=="native_failed"
        s["native_failed"]+=1; fc=string(r["failure_class"]); inc!(s["failure_classes"],fc)
        return
    end
    s["native_completed"]+=1
    if r["accepted"]; s["accepted"]+=1
    else
        s["readout_rejected"]+=1
        inc!(s["rejection_reasons"],string(r["rejection_reason"]))
    end
    limits=Int(r["step_limits"]); stopped=Int(r["stopped_without_contact"])
    s["groups_with_step_limits"]+=limits>0; s["step_limits"]+=limits
    s["groups_stopped_without_contact"]+=stopped>0; s["stopped_without_contact"]+=stopped
    s["negative_input_groups"]+=r["negative_input"]===true
    s["below_threshold_groups"]+=r["below_threshold"]===true
    s["saturated_groups"]+=r["saturated"]===true
    s["gate_limited_groups"]+=r["gate_limited"]===true
    s["window_limited_groups"]+=r["window_limited"]===true
end
function main(out)
    out=abspath(out); localroot=realpath(joinpath(ROOT,".local"))
    rel=relpath(out,localroot); check(!isabspath(rel) && first(splitpath(rel))!="..","Output outside .local")
    check(!ispath(out),"Use a new analysis directory")
    campaign=joinpath(ROOT,".local","cs137-1m-native")
    complete=JSON.parsefile(joinpath(campaign,"COMPLETE.json"))
    configfile=joinpath(campaign,"config.json"); confighash=hashfile(configfile)
    config=JSON.parsefile(configfile)
    check(complete["status"]=="completed_with_native_failures","Native campaign not terminal")
    check(complete["completed_groups"]==23693 && complete["config_hash"]==confighash,
        "Completion/config mismatch")
    expected=Dict{String,NamedTuple}()
    for model in ("AK02","SAP22")
        m=config["models"][model]; eventfile=joinpath(campaign,m["events_file"])
        check(hashfile(eventfile)==m["events_sha256"],"Frozen event stream changed: "*model)
        rows=0; groups=0
        open(eventfile) do io
            for line in eachline(io)
                e=JSON.parse(line); rows+=1; lh=bytes2hex(sha256(line)); eh=objhash(e)
                for g in e["pulse_groups"]
                    key=model*"_"*e["namespace"]*"_"*string(e["event_id"])*"_"*string(g["group_id"])
                    check(!haskey(expected,key),"Duplicate input group key")
                    expected[key]=(input_hash=lh,event_hash=eh,group_hash=objhash(g));groups+=1
                end
            end
        end
        check(rows==m["selected_primaries"] && groups==m["groups"],"Frozen input census mismatch: "*model)
    end
    check(length(expected)==complete["completed_groups"],"Frozen input group census mismatch")
    results=joinpath(campaign,"results")
    dones=sort(filter(f->endswith(f,".done.json"),readdir(results;join=true)))
    binaries=sort(filter(f->endswith(f,".jls"),readdir(results;join=true)))
    check(length(dones)==length(binaries)==complete["completed_groups"],"Result census mismatch")
    mkdir(out); started=time(); stats=Dict("AK02"=>newstats(),"SAP22"=>newstats())
    seen=Set{String}(); totalbytes=0
    ledger=joinpath(out,"groups.csv")
    open(ledger,"w") do csv
        println(csv,join(COLS,','))
        for (i,donefile) in enumerate(dones)
            done=JSON.parsefile(donefile); key=done["key"]
            check(!(key in seen),"Duplicate result key"); push!(seen,key)
            check(haskey(expected,key),"Result key absent from frozen input: "*key)
            x=expected[key]
            jls=joinpath(results,key*".jls")
            check(isfile(jls) && hashfile(jls)==done["result_hash"],"Result hash mismatch: "*key)
            check(done["config_hash"]==confighash && done["input_hash"]==x.input_hash &&
                done["status"] in ("native_completed","native_failed"),"DONE input/configuration/status mismatch")
            r=deserialize(jls)
            check(r["key"]==key && r["config_hash"]==confighash &&
                r["input_hash"]==done["input_hash"],"Serialized identity mismatch: "*key)
            check(objhash(r["event"])==x.event_hash && objhash(r["group"])==x.group_hash,
                "Serialized event/group differs from frozen input: "*key)
            check(r["status"]==done["status"] && r["accepted"]==done["accepted"],
                "Serialized summary mismatch: "*key)
            scalar=scalar_record(r); addstats!(stats[scalar["model"]],scalar)
            println(csv,join((csvcell(get(scalar,k,nothing)) for k in COLS),','))
            totalbytes+=filesize(jls)+filesize(donefile)
            i%2000==0 && (println("verified ",i," / ",length(dones));flush(stdout))
        end
    end
    for m in keys(stats)
        s=stats[m]
        check(s["native_completed"]+s["native_failed"]==s["groups"],"Status partition")
        check(s["accepted"]+s["readout_rejected"]==s["native_completed"],"Readout partition")
    end
    totals=Dict(k=>sum(stats[m][k] for m in keys(stats)) for k in
        ("groups","native_completed","native_failed","accepted","readout_rejected"))
    check(totals["groups"]==complete["completed_groups"] &&
        totals["accepted"]==complete["accepted"] &&
        totals["native_failed"]==complete["numerical_failures"],"COMPLETE/count mismatch")
    sourcehash=hashfile(@__FILE__)
    summary=Dict("kind"=>"completed_native_response_analysis_v1",
        "status"=>"completed_native_scalar_analysis","generated_utc"=>string(now(UTC)),
        "campaign_complete_sha256"=>hashfile(joinpath(campaign,"COMPLETE.json")),
        "config_sha256"=>confighash,"analyzer_sha256"=>sourcehash,
        "models"=>stats,"totals"=>totals,"result_files"=>length(dones),
        "input_groups_verified"=>length(expected),"result_bytes_verified"=>totalbytes,"seconds"=>time()-started,
        "scope"=>"Saved native response/readout scalars only; no Geant4, field solve, drift, electronics or calibration rerun.",
        "limitations"=>[
            "Synthetic electronics; no measured-spectrum fit or physical FWHM claim.",
            "Native/input-domain failures retain truth but have unknown charge/readout.",
            "Trajectory-cap/contact flags remain diagnostics; ADC acceptance is not complete collection.",
            "Final public comparison must retain the two-million initial-decay denominator separately."
        ])
    open(joinpath(out,"summary.json"),"w") do io; JSON.print(io,summary,2);println(io);end
    completeout=Dict("status"=>"verified_native_scalar_analysis",
        "summary_sha256"=>hashfile(joinpath(out,"summary.json")),
        "groups_csv_sha256"=>hashfile(ledger),"groups"=>totals["groups"],
        "source_complete_sha256"=>summary["campaign_complete_sha256"])
    open(joinpath(out,"COMPLETE.json"),"w") do io;JSON.print(io,completeout,2);println(io);end
    println(JSON.json(Dict("status"=>summary["status"],"totals"=>totals,"models"=>stats,
        "seconds"=>summary["seconds"])))
end
length(ARGS)==1 || error("Usage: julia analyze_native_complete.jl NEW_OUTPUT")
main(ARGS[1])
