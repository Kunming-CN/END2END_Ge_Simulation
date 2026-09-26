# No field solves: small constructors, byte identity and pure comparison/gate tests.
using Test
include("diagnose_transition_axes.jl")
const A=TransitionAxesDiagnostics; const T=A.T; const SSD=A.SSD
function tiny_state()
    sim=SSD.Simulation{Float64}(SSD.SSD_examples[:InfiniteCoaxialCapacitor])
    axes=(SSD.DiscreteAxis(0.,.035,:r0,:infinite,:closed,:closed,[0.,.005,.0051,.01,.02,.03,.0349,.035]),
        SSD.DiscreteAxis(0.,0.,:reflecting,:reflecting,:closed,:closed,[0.]),
        SSD.DiscreteAxis(-.001,.001,:reflecting,:reflecting,:closed,:closed,[-.001,-.0003,.0003,.001]))
    g=SSD.CylindricalGrid{Float64}(axes); SSD.apply_initial_state!(sim,SSD.ElectricPotential,g;depletion_handling=true); SSD.mark_bits!(sim); SSD.calculate_electric_field!(sim;n_points_in_φ=36,use_nthreads=2); sim
end
@testset "Crossed axes retain exact nested ticks and boundaries" begin
    g=SSD.CylindricalGrid{Float64}((SSD.DiscreteAxis(0.,.015,:r0,:infinite,:closed,:closed,[0.,.0078,.01265,.015]),
        SSD.DiscreteAxis(0.,0.,:reflecting,:reflecting,:closed,:closed,[0.]),
        SSD.DiscreteAxis(-.002,.011,:infinite,:infinite,:closed,:closed,[-.002,0.,.0021,.0047,.0094,.011])))
    g1,_=T.nested_grid(g); g2,_=T.nested_grid(g1)
    for (r,z) in ((g1,g1),(g1,g2),(g2,g1),(g2,g2))
        c=A.crossed_grid(r,z)
        @test size(c)==(size(r,1),1,size(z,3)) && iseven(size(c,3))
        for i in 1:3
            expected=i==3 ? z.axes[i] : r.axes[i]
            @test collect(c.axes[i])==collect(expected)
            @test typeof(c.axes[i])==typeof(g.axes[i])
            @test c.axes[i].interval==g.axes[i].interval
            @test all(in(c.axes[i]),g.axes[i]) && all(in(c.axes[i]),g1.axes[i])
        end
        @test prod(size(c))<=250000
    end
    @test_throws ArgumentError A.crossed_grid(g1,g2;cap=4)
    @test_throws ArgumentError A.crossed_grid(g1,g2;cap=250001)
end
@testset "Native copied setup identity excludes only potential" begin
    sim=tiny_state(); before=T.snapshot(sim); p,_=T.setup(sim;restore=false); id=A.identity(p)
    @test T.snapshot(sim)==before
    q=deepcopy(p); q.potential .+= 1.; @test A.identity(q)==id
    @test A.identity_guard(id,A.identity(q))===nothing
    for field in (:q_eff_imp,:q_eff_fix,:ϵ_r,:volume_weights,:sor_const,:point_types,:imp_scale)
        q=deepcopy(p); a=getproperty(q,field); a[1]+=one(eltype(a))
        @test_throws ArgumentError A.identity_guard(id,A.identity(q))
    end
    q=deepcopy(p); q.geom_weights[1][1]+=1.; @test_throws ArgumentError A.identity_guard(id,A.identity(q))
    @test A.update_mask(p)==((SSD.PointTypeArray(p).&SSD.update_bit).!=0)
    @test T.realarray(p,p.imp_scale)==SSD.ImpurityScaleArray(p)
    info=A.accounting(sim,p); @test info["groups"]["update"]["nodes"]+info["groups"]["fixed"]["nodes"]==prod(size(p.grid))
    @test info["unit"]=="q/epsilon_0 = V*m"
    p.q_eff_imp .= 2.; p.q_eff_fix .= -1.; p.imp_scale .= .25
    totals=A.accounting(sim,p)["groups"]["update"]; n=totals["nodes"]
    @test totals["q_imp_raw"]["positive"]==2n && totals["q_imp_alpha_scaled"]["positive"]==.5n
    @test totals["q_total_alpha_scaled"]["negative"]==-.5n
    warm=tiny_state(); sim.imp_scale.data .= .25; T.candidate!(warm,p.grid,sim)
    @test all(==(1.),warm.imp_scale.data)
end
function sample_profile()
    ds=[0.,.0005,.001,.0015]; es=[0.,0.,2.,3.]
    Dict{String,Any}("depth_mm"=>ds,"vectors"=>[[e,0.,0.] for e in es],"E"=>es,
        "onsets"=>Any[T.bracket(ds,es,t) for t in (0.,1.)],"local_source_cm3"=>zeros(4))
end
@testset "E vectors, partial inputs and unchanged gates" begin
    a=sample_profile(); b=deepcopy(a); @test A.compare(a,b)["passed"]
    b["vectors"]=[-v for v in b["vectors"]]; @test A.compare(a,b)["normalized_E"]==2 && !A.compare(a,b)["passed"]
    b=deepcopy(a); b["onsets"][2]=nothing; @test !A.compare(a,b)["passed"]
    b=deepcopy(a); b["onsets"][1]=[nothing,0.]; @test A.compare(a,b)["passed"]
    sim=tiny_state(); other=deepcopy(sim); ok=Dict{String,Any}("status"=>"accepted_fixed_grid"); partial=Dict{String,Any}("status"=>"budget_failed")
    @test A.same_grid(sim,other,a,a,ok,ok,true)["passed"]
    @test !A.same_grid(sim,other,a,a,ok,partial,true)["passed"]
    @test !A.same_grid(sim,other,a,a,ok,ok,false)["passed"]
    other.electric_potential.data[4,1,2]+=1e-4
    @test !A.same_grid(sim,other,a,a,ok,ok,true)["passed"]
    @test A.same_grid(sim,other,a,a,ok,ok,true)["maxV"]>T.LIMITS.V
    d=Dict{String,Any}("E_accepted"=>true,"E_geometric_contacts"=>[Dict{String,Any}("nodes"=>0,"max_error"=>0.)])
    @test !A.contacts_ok(d); d["E_geometric_contacts"][1]["nodes"]=1; @test A.contacts_ok(d)
    native=Dict{String,Any}("frozen"=>Dict{String,Any}("max"=>0.,"max_alpha_voltage"=>0.),"poisson"=>Dict{String,Any}("max"=>0.),"full_sweep"=>Dict{String,Any}("potential"=>0.,"alpha_voltage"=>0.))
    @test T.acceptable(native,false); native["poisson"]["max"]=1e-4; @test !T.acceptable(native,false)
    @test T.next_streak(1,true,true)==2 && T.next_streak(1,true,false)==0
    f=A.factorial(Dict{String,Any}(n=>a for n in ("g11","g12","g21","g22_from50"))); @test f["maxnorm_V_cm"]==0
    b=deepcopy(a); b["vectors"]=[v.+[-1.,0.,0.] for v in b["vectors"]]
    f=A.factorial(Dict{String,Any}("g11"=>a,"g12"=>a,"g21"=>a,"g22_from50"=>b))
    @test f["maxnorm_V_cm"]==1 && all(==(-1.),f["signed_radial_profile_V_cm"])
    @test A.exitcode(Dict{String,Any}("status"=>"partial_cases"))==2
    @test A.exitcode(Dict{String,Any}("status"=>"invalid_source_or_runtime"))==1
    @test A.budget_failure(ArgumentError("Nested point budget exceeded"))
    @test !A.budget_failure(ArgumentError("Changed helper"))
end
@testset "Output and pinned provenance fail closed" begin
    for args in (String[],["--output","docs/escape"],["--output",".local/../escape"],["--output",".local/m2e"],["--output",".local/x","--phase","all"])
        @test_throws ArgumentError A.options(args)
    end
    @test endswith(A.options(["--output",".local/transition-axes-test-never-created"]),"transition-axes-test-never-created")
    @test_throws ArgumentError T.L.check_hashes(@__DIR__,Dict{String,Any}("diagnose_transition_grid.jl"=>repeat("0",64)))
    @test A.provenance()["sources"]==A.SOURCES
end

@testset "Common factorial normalization and immutable storage" begin
    a=sample_profile(); b=deepcopy(a); ref=deepcopy(a)
    b["vectors"] .*= 2; b["E"] .*= 2
    ref["vectors"] .*= 10; ref["E"] .*= 10
    @test A.compare(a,b)["normalized_E"]≈0.5
    @test A.compare(a,b;reference=ref)["normalized_E"]≈0.1
    f=A.factorial(Dict("g11"=>a,"g12"=>a,"g21"=>a,"g22_from50"=>b))
    @test f["normalized_interaction"]≈0.5
    sim=tiny_state(); child=deepcopy(sim); before=A.state_identity(sim)
    @test A.independent_storage(sim,child)
    @test_throws ArgumentError A.independent_storage(sim,sim)
    child.electric_potential.data[4,1,2]+=1
    child.imp_scale.data[4,1,2]=0.2
    probe,_=T.setup(child;restore=false); probe.potential .+= 3
    @test A.state_identity(sim)==before
    @test A.signedsum(Float64[])==Dict("positive"=>0.0,"negative"=>0.0)
    same=A.same_grid(sim,deepcopy(sim),a,a,Dict("status"=>"accepted_fixed_grid"),Dict("status"=>"accepted_fixed_grid"),true)
    @test same["whole_grid_vector_difference_V_cm"]==0
    @test same["classification_changes"]==0
    @test same["alphavoltage"]>=same["alphavoltage_update_only"]
end

@testset "Postprocessing time is inside the cooperative budget" begin
    item=Dict{String,Any}("status"=>"accepted_fixed_grid")
    @test A.finish_budget!(deepcopy(item),900.0)["within_cooperative_time_budget"]
    late=A.finish_budget!(deepcopy(item),900.01)
    @test late["status"]=="budget_failed"
    @test !late["within_cooperative_time_budget"]
    @test A.exitcode(Dict("status"=>"partial_cases"))==2
    @test_throws ArgumentError A.finish_budget!(item,Inf)
    @test_throws ArgumentError A.finish_budget!(item,-1.0)
end

@testset "Reference availability and acceptance are separate" begin
    p=sample_profile(); profiles=Dict("g11"=>p,"g21"=>p)
    @test !A.contrast_available(profiles,"g11","g21")
    profiles["g22_from50"]=p
    @test A.contrast_available(profiles,"g11","g21")
    items=Dict("g11"=>Dict("status"=>"accepted_fixed_grid"),
        "g21"=>Dict("status"=>"accepted_fixed_grid"),
        "g22_from50"=>Dict("status"=>"budget_failed"))
    d=A.contrast_acceptance(items,"g11","g21")
    @test d["accepted_endpoints"] && !d["accepted_reference"] && !d["accepted_inputs"]
    items["g22_from50"]["status"]="accepted_fixed_grid"
    @test A.contrast_acceptance(items,"g11","g21")["accepted_inputs"]
    short=deepcopy(p); pop!(short["vectors"])
    @test_throws ArgumentError A.compare(p,p;reference=short)
    sim=tiny_state(); loc=A.difference_location(sim,deepcopy(sim))
    @test loc["semiconductor_member_max_V"]==0
    @test loc["semiconductor_phi0_max_vector_difference_V_cm"]==0
    @test all(c["nodes"]==0 for c in loc["alpha_class_transitions"])
end
