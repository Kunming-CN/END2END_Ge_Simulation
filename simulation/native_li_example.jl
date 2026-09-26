# Bounded provisional native-RCC-to-readout example; not a calibrated spectrum.
include("replay.jl")
include("readout.jl")
module NativeLiExample
using ..SSDReplay, ..Readout, Random, Unitful, JSON, SHA
const R=SSDReplay; const Q=R.Q; const SSD=R.SSD; const E=Readout
const IDS=[0,2,41,78]
const SEEDS=[2609261,2609262]
const DT=2.0
const HORIZON_NS=10000.0
function cases()
    rows=[(id=id,mode="legacy",parcels=1,seed=0) for id in IDS]
    append!(rows,[(id=id,mode="native_rcc",parcels=16,seed=SEEDS[1]) for id in IDS])
    append!(rows,[(id=id,mode="native_rcc",parcels=n,seed=s) for id in (41,78),n in (16,32),s in SEEDS if !(n==16&&s==SEEDS[1])])
    rows
end
function parcel_seed(seed,event,row,parcel)
    bytes=sha256(string(seed,'/',event,'/',row,'/',parcel))
    foldl((value,b)->(value<<8)|UInt64(b),bytes[1:8];init=UInt64(0))
end
function options(args)
    length(args) in (4,6) && args[1]=="--input" && args[3]=="--output" || error("Usage: native_li_example.jl --input .local/RUN/AK02/transport/events.json --output .local/NEW [--peak-policy signed_input_positive_peak]")
    length(args)==6 && !(args[5]=="--peak-policy" && args[6] in (E.LEGACY_PEAK_POLICY,E.SIGNED_PEAK_POLICY)) && error("Invalid peak policy option")
    abspath(args[2]),args[4]
end
function sum_parcels(parts,energy)
    R.check(!isempty(parts) && energy>0,"Invalid parcel input")
    R.check(isapprox(sum(p.energy for p in parts),energy;rtol=1e-12,atol=1e-12),"Parcel weights changed deposit energy")
    R.causal_sum([(delay=0.0,times=p.times,charge=p.charge) for p in parts],DT)
end
function native_event(event,sim,cfg,n,seed)
    R.check(n in (16,32)&&seed in SEEDS,"Unreviewed parcel setting")
    components=Any[]; outcomes=Any[]; maxsteps=ceil(Int,HORIZON_NS/DT)+1
    for step in event["steps"]
        energy=step["energy_keV"]; energy==0 && continue
        point=SSD.CartesianPoint{Float64}((Float64.(step["position_mm"])./1000)...)
        parts=Any[]; endpoints=Any[]
        for parcel in 1:n
            Random.seed!(parcel_seed(seed,event["event_id"],step["raw_row_index"],parcel))
            evt=SSD.Event([point],[energy/n*u"keV"])
            SSD.drift_charges!(evt,sim;Δt=DT*u"ns",max_nsteps=maxsteps,
                diffusion=true,end_drift_when_no_field=false,self_repulsion=false,
                geometry_check=true,verbose=false)
            stored=evt.locations[1][1]
            R.check((stored.x,stored.y,stored.z)==(point.x,point.y,point.z),"SDK moved a deposited location")
            SSD.get_signal!(evt,sim,cfg.contact;Δt=DT*u"ns",signal_unit=u"keV")
            w=evt.waveforms[cfg.contact]
            push!(parts,(energy=energy/n,times=Float64.(ustrip.(u"ns",w.time)),charge=Float64.(ustrip.(u"keV",w.signal))))
            for e in Q.endpoint_report(evt,sim,(max_steps=maxsteps,))
                e["parcel_index"]=parcel
                R.check(e["inside_semiconductor"] || !isempty(e["contact_ids"]),"Noncontact endpoint outside crystal")
                push!(endpoints,e)
            end
        end
        t,q=sum_parcels(parts,energy)
        push!(components,(delay=Float64(step["time_ns"]-event["primary_time_ns"]),times=t,charge=q))
        push!(outcomes,Dict("raw_row_index"=>step["raw_row_index"],"deposited_energy_keV"=>energy,
            "deposition_delay_ns"=>step["time_ns"]-event["primary_time_ns"],
            "endpoints"=>endpoints,"parcel_weight_keV"=>energy/n,"final_induced_keV"=>last(q)))
    end
    t,q=R.causal_sum(components,DT)
    (times=t,signal=q,steps=outcomes)
end
function flags(steps)
    endpoints=[e for s in steps for e in s["endpoints"]]
    Dict("carrier_parcels"=>length(endpoints),
        "geometric_contacts"=>count(e->!isempty(e["contact_ids"]),endpoints),
        "step_limits"=>count(e->e["step_limit_reached"],endpoints),
        "stopped_without_contact"=>count(e->e["status"]=="stopped_without_contact",endpoints))
end
escape(s)=replace(string(s),'&'=>"&amp;",'<'=>"&lt;",'>'=>"&gt;",'"'=>"&quot;")
function plot(x,y,label)
    R.check(length(x)==length(y)&&all(isfinite,x)&&all(isfinite,y),"Nonfinite plot")
    lo,hi=extrema(y); hi==lo && (hi=lo+1)
    span=max(last(x),1.0)
    points=join([string(round(55+510*x[i]/span;digits=3),',',round(165-130*(y[i]-lo)/(hi-lo);digits=3)) for i in eachindex(x)],' ')
    "<figure><figcaption>$(escape(label))</figcaption><svg role='img' aria-label='$(escape(label))' viewBox='0 0 600 205'><path d='M55 30 V165 H565' fill='none' stroke='#888'/><polyline points='$points' fill='none' stroke='currentColor' stroke-width='1.7'/><text x='5' y='35'>$(round(hi;sigdigits=4))</text><text x='5' y='165'>$(round(lo;sigdigits=4))</text><text x='50' y='192'>0</text><text x='415' y='192'>$(round(span;sigdigits=4)) ns</text></svg></figure>"
end
function write_html(filename,report)
    text="<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>Native lithium to readout</title><style>body{font:16px/1.55 system-ui;max-width:1150px;margin:auto;padding:20px;color:#17334b;overflow-wrap:anywhere}table{border-collapse:collapse;width:100%;font-size:14px}td,th{border-bottom:1px solid #ccd;padding:8px;text-align:right}.scroll{overflow:auto}.plots{display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr))}figure{margin:12px}svg{width:100%;font-size:12px}.notice{background:#fff3df;padding:16px}summary{cursor:pointer;padding:10px}</style><h1>Native SSD lithium response → electronics</h1>"
    text*="<p class='notice'>Provisional engineering example, not a calibrated spectrum. Four selected original AK02 primaries; all other primaries are explicitly unprocessed. Native diffusion and finite trajectory caps are visible. Existing grid sensitivity and synthetic electronics restrictions remain.</p><p>77 K; +500 V. Legacy: diffusion off, zero-field termination on, unchanged producer budget. Native RCC: diffusion on, zero-field termination off, independent E/N parcels and nominal 10 μs cap. Both: 2 ns, no self-repulsion. The same independent injection calibration is used for every case.</p><p><a href='report.json'>Full records</a> · <a href='summary.csv'>Scalar CSV</a> · <a href='signals.csv'>Full signed charge traces</a></p><div class='scroll'><table><tr><th>Event</th><th>Mode</th><th>N / seed</th><th>Edep keV</th><th>Induced keV-equiv.</th><th>Analog keV-equiv.</th><th>ADC Erec keV</th><th>Readout status</th></tr>"
    for c in report["cases"]
        r=c["readout"]
        vals=(c["event_id"],c["mode"],string(c["parcels"]," / ",c["seed"]),round(c["deposited_energy_keV"];digits=3),round(c["final_induced_keV"];digits=5),round(r["analog_energy_keV"];digits=5),r["reconstructed_energy_keV"]===nothing ? "—" : round(r["reconstructed_energy_keV"];digits=5),r["accepted"] ? "accepted" : r["rejection_reason"])
        text*="<tr>"*join(["<td>$(escape(v))</td>" for v in vals])*"</tr>"
    end
    policy=get(get(report,"readout_config",Dict()),"peak_policy",E.LEGACY_PEAK_POLICY)
    text*="</table></div><p>Analog energy is peak voltage divided by the shared injection slope, not calibrated detector energy. Peak policy: $(escape(policy)). Legacy rejects every negative cumulative input; the explicitly selected signed policy retains negative-input flags and accepts valid positive peaks. Rejected ADC energies remain null. No sign rectification or truth normalization is applied. N/seed differences measure numerical sampling, not physical resolution.</p>"
    for c in report["cases"]
        r=c["readout"]; t=r["trace"]["time_ns"]
        text*="<details><summary>Event $(c["event_id"]) · $(c["mode"]) · N=$(c["parcels"]) · seed $(c["seed"])</summary><p>$(escape(JSON.json(c["transport_flags"])))</p><div class='plots'>"
        for (key,label) in (("induced_charge_fC","Induced charge (fC)"),("current_nA","Original-bin current samples (nA)"),("preamp_V","Preamp output (V)"),("shaped_V","Analog shaper (V)"))
            text*=plot(t,r["trace"][key],label)
        end
        text*="</div><p>Display traces are bounded samples; full charge is in CSV. Current values refer to original bin intervals recorded in JSON, not integrals between the displayed samples.</p></details>"
    end
    write(filename,text*"<p>No new radiation generation or physical fit is performed by this example. Original event positions/times and all selected raw rows are retained in report.json.</p>")
end
function field_fingerprint(sim)
    fields=(("E",sim.electric_field),("V",sim.electric_potential),("W",sim.weighting_potentials[1]))
    Dict(name=>Dict("axes_m_rad_m"=>[collect(a) for a in f.grid.axes],
        "shape"=>collect(size(f.data)),"data_sha256"=>bytes2hex(sha256(reinterpret(UInt8,vec(f.data)))) ) for (name,f) in fields)
end
function main(args=ARGS)
    input,requested=options(args); env=Q.environment("cpu"); E.environment()
    document,prepared=R.load_input(input)
    R.check(document["model_id"]=="AK02" && document["primary_count"]==100,"This example requires a100-primary AK02 source; chosen IDs remain explicit")
    selected=[document["events"][i+1] for i in IDS]
    R.check([e["event_id"] for e in selected]==IDS,"Selected identity mismatch")
    R.check(sum(count(s->s["energy_keV"]>0,e["steps"]) for e in selected)<=100,"Selected workload too large")
    sim,temp=R.setup_simulation("AK02";temperature=77.0)
    R.geometry_check(prepared,sim); R.validate_deposits(document,sim)
    cfg=Q.parse_args(["--model","AK02","--position-mm","3,0,5","--precision","64","--dt-ns","2","--min-grid-mm","0.05","--max-iterations","50000","--output",requested])
    sources=Dict(n=>Q.sha256file(joinpath(@__DIR__,n)) for n in ("run.jl","replay.jl","readout.jl","native_li_example.jl","test_native_li_example.jl","readout_demo.json"))
    inputhash=Q.sha256file(input); out=Q.reserve_output(cfg.output); started=time()
    report=Dict{String,Any}("schema_version"=>1,"status"=>"running","scope"=>"Selected native-RCC engineering demonstration, not full-census replay or physical CCE validation",
        "environment"=>env,"input_sha256"=>inputhash,"source_lh5_sha256"=>document["source_lh5_sha256"],"source_code_sha256"=>sources,
        "model_id"=>"AK02","model_sha256"=>document["model_sha256"],"selected_event_ids"=>IDS,
        "source_primary_count"=>document["primary_count"],"unprocessed_event_ids"=>[e["event_id"] for e in document["events"] if !(e["event_id"] in IDS)],
        "original_selected_events"=>selected,"temperature_K"=>77,"bias_V"=>500,"stored_temperature_K"=>temp,
        "dt_ns"=>DT,"nominal_drift_cap_ns"=>HORIZON_NS,"timing_scope"=>"Field solve, replay, readout and report; excludes initial validation/module startup","self_repulsion"=>false,"cases"=>Any[],
        "limitations"=>["Unresolved min50/min25 transition sensitivity; no physical calibration.","Numerical parcels are weighted samples, not physical Fano or trapping noise.","Legacy no-diffusion response is a regression, not a dead-layer physics model.","Finite caps and geometric endpoint flags are retained; final charge held only for the readout tail.","A deliberately selected sample is not a spectrum or efficiency prediction."])
    try
        println("Solve AK02 once; reuse identical fields for all native/legacy comparisons");flush(stdout)
        solver,timings=Base.invokelatest(Q.solve_fields!,sim,cfg,Q.prepare_backend("cpu");sor_consts=1.0,potential_rechecks=4)
        report["solver"]=solver;report["field_timings"]=timings
        report["field_fingerprint"]=field_fingerprint(sim)
        report["field_settings"]=Dict("min_spacing_mm"=>0.05,"max_spacing_mm"=>2,"precision_bits"=>64,"sor"=>1,"rechecks"=>4)
        config=E.config(joinpath(@__DIR__,"readout_demo.json")); eion=ustrip(u"eV",sim.detector.semiconductor.material.E_ionisation)
        length(args)==6 && (config["peak_policy"]=args[6])
        matrix=E.transition(config,DT); cal=E.calibration(config,eion,DT,matrix)
        report["readout_config"]=config;report["calibration"]=cal;report["ionisation_energy_eV"]=eion
        open(joinpath(out,"signals.csv"),"w") do csv
            println(csv,"event_id,mode,parcels,seed,time_ns,induced_keV")
            for design in cases()
                event=document["events"][design.id+1]; t0=time()
                if design.mode=="legacy"
                    result=Base.invokelatest(R.replay_event,event,sim,cfg)
                    t,q,steps=result.times,result.signal,result.report["steps"]
                else
                    result=native_event(event,sim,cfg,design.parcels,design.seed)
                    t,q,steps=result.times,result.signal,result.steps
                end
                R.check(all(isfinite,q)&&first(q)==0,"Invalid cumulative charge")
                energy=sum((s["energy_keV"] for s in event["steps"]);init=0.0)
                readout=E.process_event(t,q,config,eion,cal,matrix)
                R.check(readout["current_balance"]["passed"],"Current/charge balance failed")
                record=Dict("event_id"=>design.id,"mode"=>design.mode,"parcels"=>design.parcels,"seed"=>design.seed,
                    "diffusion"=>design.mode!="legacy","end_drift_when_no_field"=>design.mode=="legacy",
                    "deposited_energy_keV"=>energy,"final_induced_keV"=>last(q),"charge_end_ns"=>last(t),
                    "raw_row_indices"=>[s["raw_row_index"] for s in event["steps"]],"steps"=>steps,
                    "transport_flags"=>flags(steps),"readout"=>readout,"seconds"=>time()-t0)
                push!(report["cases"],record)
                for (time,value) in zip(t,q)
                    println(csv,join((design.id,design.mode,design.parcels,design.seed,time,value),','))
                end
                println("Event ",design.id," ",design.mode," N=",design.parcels," seed=",design.seed," charge=",last(q)," analog=",readout["analog_energy_keV"]," status=",readout["rejection_reason"]);flush(stdout)
                Q.save_json(joinpath(out,"report.json"),report)
            end
        end
        R.check(field_fingerprint(sim)==report["field_fingerprint"],"Case altered shared field state")
        R.check(Q.sha256file(input)==inputhash,"Input changed during run")
        R.check(all(Q.sha256file(joinpath(@__DIR__,n))==h for (n,h) in sources),"Source changed during run")
        Q.verify_model_files()
        open(joinpath(out,"summary.csv"),"w") do csv
            println(csv,"event_id,mode,parcels,seed,deposited_keV,induced_keV,analog_keV,reconstructed_keV,accepted,rejection,step_limits,stopped_without_contact")
            for c in report["cases"]
                r=c["readout"]; f=c["transport_flags"]
                println(csv,join((c["event_id"],c["mode"],c["parcels"],c["seed"],c["deposited_energy_keV"],c["final_induced_keV"],r["analog_energy_keV"],r["reconstructed_energy_keV"]===nothing ? "" : r["reconstructed_energy_keV"],r["accepted"],r["rejection_reason"]===nothing ? "" : r["rejection_reason"],f["step_limits"],f["stopped_without_contact"]),','))
            end
        end
        report["status"]="completed_provisional_native_example"
        write_html(joinpath(out,"comparison.html"),report)
        report["artifacts"]=Dict(n=>Q.sha256file(joinpath(out,n)) for n in ("summary.csv","signals.csv","comparison.html"))
    catch err
        report["status"]="failed";report["error"]=sprint(showerror,err);rethrow()
    finally
        report["seconds"]=time()-started;Q.save_json(joinpath(out,"report.json"),report)
    end
    report
end
end
if abspath(PROGRAM_FILE)==@__FILE__; NativeLiExample.main(); end
