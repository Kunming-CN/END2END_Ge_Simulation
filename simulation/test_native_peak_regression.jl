# Compare immutable completed native fixtures; no field solve or input writes.
# Usage: julia --project=simulation simulation/test_native_peak_regression.jl BASE LEGACY SIGNED
using Test, JSON, SHA
length(ARGS)==3 || error("Supply baseline, repeated legacy, and signed-policy directories")
paths=abspath.(ARGS)
hashfile(p)=bytes2hex(sha256(read(p)))
need(ok,message)=ok ? nothing : throw(ArgumentError(message))
function subset_equal(a,b)
    a isa AbstractDict && return b isa AbstractDict && all(haskey(b,k)&&subset_equal(v,b[k]) for (k,v) in a)
    a isa AbstractVector && return b isa AbstractVector && length(a)==length(b) && all(subset_equal(x,y) for (x,y) in zip(a,b))
    isequal(a,b)
end
function verify_case(a,b,c,config,cal)
    invariant=Dict(k=>v for (k,v) in a if k!="seconds")
    need(subset_equal(invariant,b),"Legacy case changed")
    need(subset_equal(Dict(k=>v for (k,v) in invariant if k!="readout"),c),"Signed case identity or transport changed")
    br,cr=b["readout"],c["readout"]
    allowed=("peak_policy","accepted","rejection_reason","reconstructed_energy_keV")
    need(subset_equal(Dict(k=>v for (k,v) in br if !(k in allowed)),cr),"Signed analog data or diagnostics changed")
    need(cr["peak_policy"]=="signed_input_positive_peak","Wrong explicit policy")
    peak=cr["peak_V"]
    reason=peak>=config["adc_full_scale_V"] ? "saturated" : cr["window_limited"] ? "peak_at_window_end" :
        cr["gate_limited"] ? "peak_at_gate_boundary" : peak<config["threshold_V"] ? "below_threshold" : nothing
    accepted=reason===nothing
    need(cr["accepted"]===accepted && cr["rejection_reason"]==reason,"Wrong signed-policy acceptance")
    energy=accepted ? (cr["adc_code"]+.5)*cal["adc_lsb_V"]/cal["volts_per_keV"] : nothing
    need(isequal(cr["reconstructed_energy_keV"],energy),"Wrong accepted or null reconstructed energy")
    true
end
reports=[JSON.parsefile(joinpath(p,"report.json")) for p in paths]
a,b,c=reports
@testset "Complete 14-case identities and signed-policy regression" begin
    @test all(r->r["status"]=="completed_provisional_native_example",reports)
    @test all(r->length(r["cases"])==14,reports)
    @test length(unique(hashfile(joinpath(p,"signals.csv")) for p in paths))==1
    @test hashfile(joinpath(paths[1],"summary.csv"))==hashfile(joinpath(paths[2],"summary.csv"))
    for key in ("field_fingerprint","calibration","original_selected_events","selected_event_ids","unprocessed_event_ids","input_sha256","source_lh5_sha256","model_sha256")
        @test a[key]==b[key]==c[key]
    end
    @test get(c["readout_config"],"peak_policy",nothing)=="signed_input_positive_peak"
    for (old,legacy,signed) in zip(a["cases"],b["cases"],c["cases"])
        @test verify_case(old,legacy,signed,c["readout_config"],c["calibration"])
        for key in ("event_id","mode","parcels","seed")
            bad=deepcopy(signed)
            bad[key]=bad[key] isa AbstractString ? "corrupted" : bad[key]+1
            @test_throws ArgumentError verify_case(old,legacy,bad,c["readout_config"],c["calibration"])
        end
        bad=deepcopy(signed); bad["readout"]["accepted"]=!bad["readout"]["accepted"]
        @test_throws ArgumentError verify_case(old,legacy,bad,c["readout_config"],c["calibration"])
    end
    @test count(x->x["readout"]["accepted"],b["cases"])==4
    @test count(x->x["readout"]["accepted"],c["cases"])==8
end
println("NATIVE_PEAK_REGRESSION_RECEIPT ",JSON.json(Dict("status"=>"passed","cases"=>14,
    "signed_accepted"=>8,"signals_sha256"=>hashfile(joinpath(paths[1],"signals.csv")),
    "report_sha256"=>[hashfile(joinpath(p,"report.json")) for p in paths],"test_sha256"=>hashfile(@__FILE__))))
