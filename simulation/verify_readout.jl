# Fixed-input readout sampling/window check; never reruns or changes SSD transport.
include("readout.jl")
const R = Readout
function resample_charge(t, q, dt)
    olddt=t[2]-t[1]
    times=collect(0.0:dt:ceil(last(t)/dt)*dt)
    values=map(times) do x
        x>=last(t) && return last(q)
        i=min(floor(Int,x/olddt)+1,length(q)-1)
        q[i]+(q[i+1]-q[i])*(x-t[i])/olddt
    end
    times,values
end
function verify(input, output)
    R.environment()
    out=R.reserve_output(output)
    config=R.config(joinpath(@__DIR__,"readout_demo.json"))
    root=R.readjson(joinpath(input,"run.json"))
    R.check(root["status"]=="complete","A complete pipeline run is required")
    report=Dict{String,Any}("status"=>"running","source_sha256"=>R.hashfile(@__FILE__),
        "readout_source_sha256"=>R.hashfile(joinpath(@__DIR__,"readout.jl")),
        "scope"=>"Fixed input charge: electronics sampling and tail check, not SSD drift-step convergence",
        "sampling"=>"Linear cumulative-charge interpolation preserves original constant-current bins at1ns;4ns averages pairs. Final charge is held through any padded final bin.",
        "calibration"=>"Original2ns injection slope retained; only numerical timestep metadata changes",
        "gate_LSB"=>0.25,"cases"=>Any[],"inputs"=>Dict{String,String}())
    try
        for model in root["models"]
            R.check(model in ("AK02","SAP22"),"Unsupported model")
            base=joinpath(input,model)
            charge,truth,_=R.load_inputs(joinpath(base,"charge"),joinpath(base,"transport","events.json"),config)
            saved=R.readjson(joinpath(base,"readout","run.json"))
            R.check(saved["status"]=="completed","Readout is incomplete")
            R.check(charge["time_step_ns"]==2,"This bounded test expects original2ns charge bins")
            for f in ("charge/run.json","charge/signals.csv","readout/run.json")
                report["inputs"][model*"/"*f]=R.hashfile(joinpath(base,f))
            end
            propagators=Dict(dt=>R.transition(config,dt) for dt in (1.0,2.0,4.0))
            open(joinpath(base,"charge","signals.csv")) do io
                readline(io)=="event_id,time_since_primary_ns,induced_equivalent_energy_keV" || error("Bad CSV header")
                for (index,event) in enumerate(charge["events"])
                    t,q=R.read_wave(io,event,charge,config)
                    baseline=saved["events"][index]
                    R.check(baseline["event_id"]==event["event_id"],"Lost event identity")
                    for (name,dt,tail) in (("half_step",1.0,20.0),("double_step",4.0,20.0),("double_tail",2.0,40.0))
                        c=deepcopy(config);c["tail_shaping_constants"]=tail
                        cal=deepcopy(saved["calibration"]);cal["time_step_ns"]=dt
                        tt,qq=dt==2 ? (t,q) : resample_charge(t,q,dt)
                        result=R.process_event(tt,qq,c,charge["ionisation_energy_eV"],cal,propagators[dt])
                        delta=abs(result["peak_V"]-baseline["peak_V"])/cal["adc_lsb_V"]
                        push!(report["cases"],Dict("model"=>model,"event_id"=>event["event_id"],"check"=>name,
                            "peak_difference_LSB"=>delta,"baseline_adc_code"=>baseline["adc_code"],
                            "checked_adc_code"=>result["adc_code"],"passed"=>delta<0.25))
                    end
                end
                R.check(eof(io),"Unexpected trailing signal rows")
            end
        end
        for (name,hash) in report["inputs"]
            R.check(R.hashfile(joinpath(input,name))==hash,"Input changed during verification")
        end
        report["maximum_peak_difference_LSB"]=maximum(c["peak_difference_LSB"] for c in report["cases"])
        report["adc_code_changes"]=count(c->c["baseline_adc_code"]!=c["checked_adc_code"],report["cases"])
        R.check(all(c["passed"] for c in report["cases"]),"Sampling/window gate failed")
        report["status"]="passed"
    catch err
        report["status"]="failed";report["error_type"]=string(typeof(err));rethrow()
    finally
        R.save(joinpath(out,"run.json"),report)
    end
    println("Sampling/window checks: ",length(report["cases"]),"; maximum difference: ",report["maximum_peak_difference_LSB"]," LSB")
    report
end
if abspath(PROGRAM_FILE)==@__FILE__
    length(ARGS)==4 && ARGS[1]=="--input" && ARGS[3]=="--output" || error("Usage: verify_readout.jl --input PIPELINE_DIR --output .local/NEW")
    verify(abspath(ARGS[2]),ARGS[4])
end
