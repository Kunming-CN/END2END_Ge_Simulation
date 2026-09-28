# Additive compatibility guard for saved Geant4 deposits that begin inside an SSD contact.
# Existing checkpoint runner, models and saved inputs remain byte-identical.
include("native_progress_resilience.jl")
module NativeContactStartResilience
using ..NativeProgressResilience, ..NativeCheckpointBatch, SHA
const C=NativeCheckpointBatch
const V=C.V; const B=C.B; const N=C.N; const Q=C.Q
const R=C.R; const G=C.G
const ORIGINAL_RUNNER_SHA="7e5bdafe6767501b01c0bd10afd9a5840f1cdd7e03b1377b4001ec6bc14818a5"
const INSTALLED=Ref(false)

point(s)=R.SSD.CartesianPoint{Float64}((Float64.(s["position_mm"])./1000)...)
function validate_event_allow_contact(e,sim)
    count=0
    for s in e["steps"]
        s["energy_keV"]==0 && continue
        p=point(s)
        R.check(p in sim.detector.semiconductor,
            "Positive-energy deposit outside SSD: row $(s["raw_row_index"])")
        count+=1
    end
    count
end
function contact_rows(e,g,sim)
    byrow=Dict(s["raw_row_index"]=>s for s in e["steps"])
    rows=Any[]
    for row in g["row_indices"]
        s=byrow[row]; s["energy_keV"]==0 && continue
        p=point(s)
        ids=[c.id for c in sim.detector.contacts if p in c.geometry]
        isempty(ids) && continue
        push!(rows,Dict("raw_row_index"=>row,"energy_keV"=>s["energy_keV"],
            "position_mm"=>s["position_mm"],"contact_ids"=>ids))
    end
    rows
end
function provenance()
    Dict("kind"=>"saved_contact_start_fail_closed_v1",
        "change"=>"Positive deposit in SSD contact => whole group response unknown before drift",
        "original_runner_sha256"=>ORIGINAL_RUNNER_SHA,
        "adapter_sha256"=>C.hashfile(@__FILE__),
        "coordinates_modified"=>false,"physics_substitution"=>false)
end
function contact_failure(model,e,g,sim,confighash,linehash)
    bad=contact_rows(e,g,sim)
    isempty(bad) && return nothing
    task=C.key(model,e,g)
    error=Dict("type"=>"NativeInputContactStart",
        "failure_class"=>"input_domain_compatibility",
        "message"=>"Positive-energy deposit starts inside an SSD contact; carrier response unsupported",
        "contact_rows"=>bad,"contact_energy_keV"=>sum(r["energy_keV"] for r in bad),
        "group_response_unknown"=>true,"native"=>nothing,"readout"=>nothing)
    Dict{String,Any}("key"=>task,"input_hash"=>linehash,"config_hash"=>confighash,
        "event"=>e,"group"=>g,"guard"=>G.provenance(),"compatibility_guard"=>provenance(),
        "status"=>"native_failed","accepted"=>false,"native"=>nothing,"readout"=>nothing,
        "error"=>error,"failure_class"=>"input_domain_compatibility")
end
function response_or_contact_failure(model,e,g,sim,cfg,profile,cal,M,eion,confighash,linehash)
    failed=contact_failure(model,e,g,sim,confighash,linehash)
    failed===nothing || return failed
    Base.invokelatest(C.response,model,e,g,sim,cfg,profile,cal,M,eion,confighash,linehash)
end
function patched_main(source::String)
    source=replace(source,"\r\n"=>"\n")
    body=match(r"function main\(out;max_new=typemax\(Int\)\)[\s\S]*?\nend(?=\nend\nif abspath)",source)
    body===nothing && error("Pinned main() not found")
    text=body.match
    old="e=JSON.parse(line);R.validate_deposits(Dict(\"events\"=>[e]),sim);lh=bytes2hex(sha256(line))"
    count(old,text)==1 || error("Unexpected per-event validation call")
    text=replace(text,old=>"e=JSON.parse(line);Main.NativeContactStartResilience.validate_event_allow_contact(e,sim);lh=bytes2hex(sha256(line))")
    old="r=response(model,e,g,sim,cfg,profile,cal,M,eion,confighash,lh)"
    count(old,text)==1 || error("Unexpected response call")
    replace(text,old=>"r=Main.NativeContactStartResilience.response_or_contact_failure(model,e,g,sim,cfg,profile,cal,M,eion,confighash,lh)")
end
function install!()
    INSTALLED[] && return provenance()
    NativeProgressResilience.install!()
    file=joinpath(@__DIR__,"native_checkpoint_batch.jl")
    C.hashfile(file)==ORIGINAL_RUNNER_SHA || error("Unsupported numerical runner; no silent rebaseline")
    body=patched_main(read(file,String))
    Base.include_string(C,body,"native-contact-start-resilience-v1")
    INSTALLED[]=true
    provenance()
end
end
if abspath(PROGRAM_FILE)==@__FILE__
    length(ARGS) in (1,2) || error("Usage: native_contact_start_resilience.jl OUTPUT [MAX_NEW_GROUPS]")
    NativeContactStartResilience.install!()
    println("Contact-start fail-closed and display resilience active; original runner unchanged.");flush(stdout)
    Base.invokelatest(NativeCheckpointBatch.main,ARGS[1];
        max_new=length(ARGS)==2 ? parse(Int,ARGS[2]) : typemax(Int))
end
