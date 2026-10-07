# Shared native descriptor admission for canonical catalog models. No per-model runner.
isdefined(@__MODULE__, :SSDQuickstart) || include("run.jl")
module CatalogNativeModel
using ..SSDQuickstart, SolidStateDetectors, JSON, SHA, Unitful
const Q=SSDQuickstart;const ROOT=Q.ROOT;const SSD=SolidStateDetectors
check(x,m)=x || throw(ArgumentError(m))
hashfile(p)=bytes2hex(sha256(read(p)))
integer(x)=x isa Integer && !(x isa Bool)
function relative_file(ref)
    check(ref isa String && !isempty(ref) && !isabspath(ref) && !occursin('\\',ref) && !(".." in split(ref,'/')),"Unsafe catalog dependency reference")
    path=joinpath(ROOT,split(ref,'/')...);check(isfile(path) && realpath(path)==abspath(path),"Missing/linked catalog dependency")
    path
end
function wiring(contacts,selected)
    potential=contacts[string(selected)];deltas=[v-potential for (k,v) in contacts if k!=string(selected) && v!=potential]
    check(!isempty(deltas),"Readout has no nonzero applied detector bias")
    check(all(x->x>0,deltas) || all(x->x<0,deltas),"Readout is between distinct bias levels; fixed single-channel wiring is unspecified")
    all(x->x>0,deltas) ? 1 : -1
end
function validate_model(c;require_placement=false)
    fields=Set(("kind","schema_version","model_id","model_ref","model_sha256","dependencies_sha256","catalog_sha256","coordinate_system","geometry","bounds_mm","contact_potentials_V","readout_contact_id","wiring_factor","bias_span_V","stored_temperature_K","runtime_temperature_K","temperature_policy","qualification","assumptions","cavity","placement","scope"))
    check(c isa AbstractDict && Set(keys(c))==fields && c["kind"]=="catalog_detector_contract_v1" && c["schema_version"]===1,"Wrong catalog detector descriptor")
    catpath=joinpath(ROOT,"models/catalog.json");check(hashfile(catpath)==c["catalog_sha256"],"Catalog authority changed")
    cat=JSON.parsefile(catpath);entry=only(filter(x->x["id"]==c["model_id"],cat["detectors"]))
    check(c["model_ref"]=="models/"*entry["model"] && c["model_sha256"]==entry["model_sha256"],"Canonical catalog/model identity changed")
    path=relative_file(c["model_ref"]);check(hashfile(path)==c["model_sha256"],"Canonical model bytes changed")
    deps=Dict("models/"*r=>only(filter(x->x["path"]==r,cat["dependencies"]))["sha256"] for r in entry["dependencies"])
    check(c["dependencies_sha256"]==deps,"Canonical include authority changed")
    for (ref,h) in deps;check(hashfile(relative_file(ref))==h,"Canonical included model changed");end
    doc=SSD.YAML.load_file(path);check(length(doc["detectors"])==1 && doc["name"]==c["model_id"],"Wrong detector count/identity")
    sc=doc["detectors"][1]["semiconductor"];contacts=doc["detectors"][1]["contacts"]
    check(sc["material"]=="HPGe" && doc["medium"]=="vacuum","Unsupported canonical material/medium")
    actual=Dict(string(x["id"])=>x["potential"] for x in contacts)
    check(length(actual)==length(contacts) && actual==c["contact_potentials_V"] &&
        actual==Dict(string(x["id"])=>x["potential_V"] for x in entry["contacts"]),"Lost/changed canonical contacts or signed potentials")
    check(integer(c["readout_contact_id"]) && c["readout_contact_id"]==entry["readout_contact_id"] && haskey(actual,string(c["readout_contact_id"])),"Changed/missing catalog readout contact")
    check(c["coordinate_system"]==doc["grid"]["coordinates"]==entry["coordinate_system"] && c["geometry"]==sc["geometry"] && c["bounds_mm"]==entry["bounds_mm"],"Canonical geometry/coordinate descriptor changed")
    check(c["stored_temperature_K"]==c["runtime_temperature_K"]==sc["temperature"] &&
        c["temperature_policy"]=="original YAML temperature retained","Catalog model temperature must retain its original value")
    check(c["bias_span_V"]==maximum(values(actual))-minimum(values(actual)) && integer(c["wiring_factor"]) && c["wiring_factor"]==wiring(actual,c["readout_contact_id"]),"Wrong bias span or fixed readout wiring")
    check(c["qualification"]==entry["status"] && c["assumptions"]==entry["assumptions"],"Canonical model qualifications changed")
    nominalpath=relative_file("transport/cryostat_nominal.json");nominal=JSON.parsefile(nominalpath)
    cavity=c["cavity"];check(cavity["nominal_sha256"]==hashfile(nominalpath) && cavity["coordinate_transform"]==nominal["coordinate_transform"] && cavity["crystal_in_vacuum_translation_mm"]==nominal["crystal_in_vacuum_translation_mm"],"Changed fixed nominal placement")
    upstream=JSON.parsefile(relative_file("transport/cryostat-source.json"))
    for name in ("chamber.tg","shield.tg","stage.tg")
        expected=only(filter(x->x["name"]==name,upstream["files"]))["sha256"]
        check(cavity["upstream_sha256"][name]==expected && hashfile(relative_file(".local/transport/LBNL/"*name))==expected,"Changed original cavity input")
    end
    # These dimensions are independently derived from the pinned shield.tg parameters.
    envelope=[-20.574,20.574,-21.463,21.463,-29.21,29.21]
    check(length(cavity["large_box_bounds_vacuum_mm"])==6 && all(isapprox.(cavity["large_box_bounds_vacuum_mm"],envelope;rtol=0,atol=1e-9)) && isapprox(cavity["maximum_front_z_mm"],35.56;rtol=0,atol=1e-9),"Changed cavity dimensions")
    b=c["bounds_mm"];t=nominal["crystal_in_vacuum_translation_mm"]
    occupied=[b[1]+t[1],b[2]+t[1],b[5]+t[2],b[6]+t[2],-b[4]+t[3],-b[3]+t[3]]
    inside=all(occupied[i]>=envelope[i]-1e-9 && occupied[i+1]<=envelope[i+1]+1e-9 for i in (1,3,5))
    check(c["placement"]["occupied_bounds_vacuum_mm"]==occupied && c["placement"]["fits_large_box_envelope"]===inside,"Rehashed placement/fit declaration changed")
    if require_placement
        check(inside && b[5]>=0 && isempty(c["placement"]["blocking_reasons"]),"Canonical detector does not fit the fixed nominal cryostat")
    end
    (path=path,document=doc,entry=entry)
end
function simulation(c;require_placement=true)
    a=validate_model(c;require_placement=require_placement);sim=Simulation{Float64}(a.path)
    check(sim.detector.semiconductor.temperature==c["runtime_temperature_K"] && Dict(string(x.id)=>x.potential for x in sim.detector.contacts)==c["contact_potentials_V"],"Loaded native operating values differ from descriptor")
    (sim=sim,model=a,ionisation_energy_eV=ustrip(u"eV",sim.detector.semiconductor.material.E_ionisation))
end
function validate_probes(meta,sim)
    probes=meta["probes"];check(!isempty(probes),"No checked geometry probes")
    for p in probes
        xyz=Float64.(p["position_mm"]);check(length(xyz)==3 && all(isfinite,xyz),"Invalid model probe")
        expected=p["expected"];check(expected in ("inside","outside","surface"),"Unknown geometry classification")
        expected=="surface" && continue # SSD's membership is inclusive; Geant4 retains exact surface classification.
        actual=SSD.CartesianPoint{Float64}((xyz./1000)... ) in sim.detector.semiconductor.geometry
        check(actual==(expected=="inside"),"SSD/native geometry probe mismatch: "*p["name"])
    end
    Dict("ssd_probe_membership_passed"=>true,"probe_count"=>length(probes),"scope"=>"Original-model SSD membership and native Geant4 probes; not field/CCE convergence")
end
function numerics(c)
    Dict("parcels"=>16,"native_seed_family"=>2609261,"drift_dt_ns"=>2,"drift_cap_ns"=>10000,"stored_temperature_K"=>c["stored_temperature_K"],"runtime_temperature_K"=>c["runtime_temperature_K"],"bias_V"=>c["bias_span_V"],"native_failure_policy"=>"record","models_serial"=>true,"stages_serial"=>true,"precision_bits"=>64,"min_spacing_mm"=>0.25,"max_spacing_mm"=>2,"refinement_limits"=>[0.2,0.1,0.05],"max_iterations_per_refinement"=>50000,"sor"=>1,"potential_rechecks"=>4)
end
function config(c,out)
    Q.parse_args(["--model",c["model_id"],"--contact",string(c["readout_contact_id"]),"--position-mm","3,0,5","--precision","64","--dt-ns","2","--min-grid-mm","0.25","--max-iterations","50000","--output",out])
end
function resource_plan(sim,cfg;free_bytes=Sys.free_memory())
    # SSD's own initial-grid construction allocates ticks only, without any field solve.
    ep=SSD.Grid(sim;max_tick_distance=cfg.max_grid*u"mm",for_weighting_potential=false)
    wp=SSD.Grid(sim;max_tick_distance=cfg.max_grid*u"mm",for_weighting_potential=true)
    defaultwp=SSD.Grid(sim;for_weighting_potential=true)
    shapes=Dict("electric_initial"=>collect(size(ep)),"weighting_initial"=>collect(size(wp)),"weighting_default"=>collect(size(defaultwp)))
    nodes=maximum(prod(BigInt.(shape)) for shape in values(shapes))
    estimated=192*nodes # Explicit conservative initial-grid allowance, not measured peak memory.
    # A spacing-based extrapolation for comparison, not an SSD grid/memory bound.
    # SSD adaptive/surface refinement can exceed these counts; three parity ticks are only part of its behavior.
    # Narrow contact intervals are retained, even when below the requested minimum.
    envelopes=Dict{String,Any}()
    for mm in (0.05,0.25)
        boundaxis(ax)=length(ax)==1 ? 1 : 1+sum(max(1,ceil(Int,abs(w)/(mm/1000))) for w in diff(ax.ticks))+3
        bounds=[[boundaxis(ax) for ax in g.axes] for g in (ep,wp,defaultwp)]
        envelope_nodes=maximum(prod(BigInt.(shape)) for shape in bounds)
        field_multiplier=ep isa SSD.CylindricalGrid ? 36 : 1
        envelopes[string(mm)]=Dict("largest_axis_tick_envelope"=>[maximum(shape[i] for shape in bounds) for i in 1:3],"largest_grid_node_envelope"=>Int(envelope_nodes),"electric_field_phi_multiplier"=>field_multiplier,"estimated_working_byte_envelope"=>Int(192*envelope_nodes*field_multiplier))
    end
    reserve=512*1024^2;available=max(BigInt(free_bytes)-reserve,0)
    plan=Dict("initial_grid_shapes"=>shapes,"refinement_spacing_envelopes"=>envelopes,"largest_initial_grid_nodes"=>Int(nodes),"assumed_working_bytes_per_node"=>192,"estimated_initial_working_bytes"=>Int(estimated),"free_physical_bytes_at_check"=>free_bytes,"reserved_system_bytes"=>reserve,"initial_grid_guard_passed"=>estimated<=available,"min_tick_distance_mm"=>cfg.min_grid,"max_tick_distance_mm"=>cfg.max_grid,"scope"=>"SSD initial ticks only; 192 bytes/node is a working allowance, not measured memory. Spacing extrapolations retain narrow intervals and three parity ticks but are not upper bounds: adaptive/surface refinement can exceed them. Final actual grids and measured process peak RSS govern resource assessment. New engineering route uses portable 0.25/2 mm defaults; no grid-convergence claim.")
    check(plan["initial_grid_guard_passed"],"Initial native grid estimate exceeds available physical-memory allowance; preserve settings and run evidence")
    plan
end
function field_fingerprint(sim,contact)
    fields=(("E",sim.electric_field),("V",sim.electric_potential),("W",sim.weighting_potentials[contact]))
    check(all(f!==missing for (_,f) in fields),"Selected native field/weighting potential missing")
    Dict(name=>Dict("axes"=>[collect(a) for a in f.grid.axes],"coordinate_system"=>string(typeof(f.grid)),"shape"=>collect(size(f.data)),"data_sha256"=>bytes2hex(sha256(reinterpret(UInt8,vec(f.data))))) for (name,f) in fields)
end
end
