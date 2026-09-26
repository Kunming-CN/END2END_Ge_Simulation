# Lightweight native kernels and helpers only: no converged fields or detector campaign.
using Test
include("diagnose_transition_grid.jl")
const T=TransitionGridDiagnostics
const SSD=T.SSD

function tiny_state()
    sim=SSD.Simulation{Float64}(SSD.SSD_examples[:InfiniteCoaxialCapacitor])
    r=[0.0,0.005,0.0051,0.01,0.02,0.03,0.0349,0.035]
    axes=(SSD.DiscreteAxis(0.0,0.035,:r0,:infinite,:closed,:closed,r),
        SSD.DiscreteAxis(0.0,0.0,:reflecting,:reflecting,:closed,:closed,[0.0]),
        SSD.DiscreteAxis(-0.001,0.001,:reflecting,:reflecting,:closed,:closed,[-0.001,-0.0003,0.0003,0.001]))
    g=SSD.CylindricalGrid{Float64}(axes); SSD.apply_initial_state!(sim,SSD.ElectricPotential,g;depletion_handling=true)
    sim
end

@testset "Saved alpha, copied setup, and all-color native defects" begin
    sim=tiny_state(); sim.imp_scale.data .= 0.25
    before=T.snapshot(sim); p,paint=T.setup(sim)
    @test SSD.ImpurityScaleArray(p)==sim.imp_scale.data
    @test T.snapshot(sim)==before
    @test p.potential !== sim.electric_potential.data
    @test paint["max_change"]==0
    original=deepcopy(p); T.defects(p)
    @test p.potential==original.potential && p.imp_scale==original.imp_scale
    @test T.snapshot(sim)==before
    # Zero-source constant field gives a known zero defect; perturb each color independently.
    p.potential .= 0; p.q_eff_imp .= 0; p.q_eff_fix .= 0
    @test T.frozen(p,:clamp)["max"]==0
    mask=(SSD.PointTypeArray(p).&SSD.update_bit).!=0
    for even in (true,false)
        idx=first(i for i in CartesianIndices(mask) if mask[i]&&iseven(sum(Tuple(i)))==even&&i[1]>2)
        r,f,z=Tuple(idx); c=deepcopy(p); color=even ? SSD.rb_even : SSD.rb_odd
        c.potential[SSD.rbidx(z),f+1,r+1,color]=1.0
        d=T.frozen(c,:clamp)
        @test d["max"]>0.9
        @test only(filter(x->x["color_even"]==even,d["colors"]))["potential"]>0.9
        @test c.potential[SSD.rbidx(z),f+1,r+1,color]==1
        @test T.frozen(c,:weighting)["max"]>0.9
    end
    # Disabling depletion without scaling the source must give a different answer.
    p.q_eff_imp .= 1e-6; p.imp_scale .= 0.25
    full=T.frozen(p,:fullsource)["max"]; scaled=T.frozen(p,:poisson)["max"]
    @test full>0 && scaled≈full/4
    @test all(==(1e-6),p.q_eff_imp)
    @test T.realarray(p,p.imp_scale)==SSD.ImpurityScaleArray(p)
    @test T.sources(p)["q_imp"]["positive"]≈prod(size(p.grid))*1e-6
    @test T.sources(p)["alpha_q_imp"]["positive"]≈prod(size(p.grid))*0.25e-6
    @test_throws ArgumentError T.frozen(p,:invalid)
    # Constructor repaints our deliberately corrupted contact, but never the simulation.
    fixed=findfirst(.!mask); sim.electric_potential.data[fixed]+=0.2
    before=T.snapshot(sim); _,paint=T.setup(sim)
    @test paint["max_change"]≈0.2
    @test T.snapshot(sim)==before
    SSD.apply_initial_state!(sim,SSD.WeightingPotential,1,sim.electric_potential.grid;depletion_handling=true)
    before=T.snapshot(sim); w,_=T.setup(sim;weighting=true); T.defects(w;weighting=true)
    @test T.snapshot(sim)==before
    warm=tiny_state(); T.candidate!(warm,sim.electric_potential.grid,sim)
    @test all(==(1.0),warm.imp_scale.data) # Old alpha must not follow the interpolated potential.
    @test T.snapshot(sim)==before
end

@testset "Independent scalar source and neighbor clamp checks" begin
    # These hand-computed cases test the scalar closure, not an independent spatial stencil.
    neighbors=(0.0,2.0,0.0,2.0,0.0,2.0)
    @test SSD.handle_depletion(1.0,0.3,neighbors,4.0,0.5)==(2.0,0.5)
    @test SSD.handle_depletion(1.0,0.3,neighbors,-4.0,0.5)==(0.0,0.5)
    @test SSD.handle_depletion(1.0,0.3,neighbors,0.0,0.5)==(1.0,0.3)
    @test SSD.handle_depletion(1.0,0.3,ntuple(_->1.0,6),4.0,0.5)==(1.0,0.0)
    @test T.signedsum([-2.,3.,-1.])==Dict("positive"=>3.,"negative"=>-3.)
end

@testset "Nested ticks preserve geometry, even z, and bounded allocation" begin
    t=[-0.002,-0.001,0.0,0.001,0.002,0.011]
    v,c=T.nested_ticks(t,[(-0.001,0.001)];even=true)
    @test iseven(length(v)) && all(in(v),t)
    w,_=T.nested_ticks(v,[(-0.001,0.001)];even=true)
    @test all(in(w),v) && iseven(length(w))
    v,c=T.nested_ticks([-2.,0.,2.,4.],[(0.5,1.5)];even=true)
    @test c==-1.0 && all(in(v),[-2.,0.,2.,4.])
    g=SSD.CylindricalGrid{Float64}((SSD.DiscreteAxis(0.0,0.015,:r0,:infinite,:closed,:closed,[0.,0.0078,0.01265,0.015]),
        SSD.DiscreteAxis(0.0,0.0,:reflecting,:reflecting,:closed,:closed,[0.0]),
        SSD.DiscreteAxis(-0.002,0.011,:infinite,:infinite,:closed,:closed,[-0.002,0.,0.0021,0.0047,0.0094,0.011])))
    g1,_=T.nested_grid(g); g2,_=T.nested_grid(g1)
    for i in 1:3
        @test all(in(g1.axes[i]),g.axes[i]) && all(in(g2.axes[i]),g1.axes[i])
        @test SSD.get_boundary_types(g.axes[i])==SSD.get_boundary_types(g2.axes[i])
    end
    @test iseven(size(g2,3))
    @test_throws ArgumentError T.nested_grid(g;cap=4)
    @test_throws ArgumentError T.nested_grid(g;cap=250001)
    @test_throws ArgumentError T.nested_grid(tiny_state().electric_potential.grid)
    @test_throws ArgumentError T.nested_ticks([0.,1.,1.],[(0.,1.)])
    @test_throws ArgumentError T.nested_ticks([0.,1.],[(-1.,0.5)])
    @test_throws ArgumentError T.nested_ticks([0.,1.],[(0.8,0.2)])
end

@testset "Profiles, normalization, cold/warm and consecutive-check gates" begin
    ds=[0.0,0.002,0.004,0.006]; e=[0.,0.,2.,3.]
    @test T.bracket(ds,e,1.)==[0.002,0.004]
    @test T.bracket(ds,e,4.)===nothing
    @test T.bracket(ds,[1.,1.,1.,1.],0.)==[nothing,0.]
    @test_throws ArgumentError T.bracket(ds,[NaN,0.,2.,3.],1.)
    a=Dict("depth_mm"=>ds,"E"=>e,"vectors"=>[[x,0.,0.] for x in e],"W"=>zeros(4),"onsets"=>Any[T.bracket(ds,e,t) for t in (0.,1.)])
    b=deepcopy(a); b["E"][end]+=0.03; b["vectors"][end][1]+=0.03
    @test T.compare(a,b)["normalized_E"]≈0.03/3.03
    b["vectors"][end][2]=0.2; @test !T.compare(a,b)["passed"]
    b=deepcopy(a); b["onsets"][2]=[0.005,0.006]; @test !T.compare(a,b)["passed"]
    b=deepcopy(a); b["onsets"][1]=nothing; @test T.compare(a,b)["passed"]
    sim=tiny_state(); SSD.apply_initial_state!(sim,SSD.WeightingPotential,1,sim.electric_potential.grid;depletion_handling=true)
    other=deepcopy(sim); @test T.coldwarm(sim,other,a,a)["passed"]
    other.electric_potential.data[4,1,2]+=1e-4; @test !T.coldwarm(sim,other,a,a)["passed"]
    d=Dict("frozen"=>Dict("max"=>1e-7,"max_alpha_voltage"=>0.),"poisson"=>Dict("max"=>1e-4),"full_sweep"=>Dict("potential"=>1e-7,"alpha_voltage"=>0.))
    @test !T.acceptable(d,false)
    d["poisson"]["max"]=1e-7; @test T.acceptable(d,false)
    @test !T.acceptable(d,true)
    @test T.next_streak(0,true,true)==1
    @test T.next_streak(1,true,true)==2
    @test T.next_streak(1,false,true)==0
    @test T.next_streak(1,true,false)==0
    @test T.nested_gate([true,true],true)
    @test !T.nested_gate([true],true)
    @test !T.nested_gate([true,false],true)
    @test !T.nested_gate([true,true],false)
end

@testset "Output escape and pinned provenance" begin
    @test_throws ArgumentError T.options(["--output","docs/escaped"])
    @test_throws ArgumentError T.options(["--output",".local/../outside"])
    @test_throws ArgumentError T.options(["--output",".local/m2d"])
    @test_throws ArgumentError T.options(["--output",".local/test-never-created","--phase","bad"])
    @test_throws ArgumentError T.options(["--output",".local/x","--output",".local/y"])
    @test_throws ArgumentError T.options(String[])
    @test last(T.options(["--output",".local/test-never-created"]))=="all"
    p=T.provenance()
    @test p["historical_report_sha256"]==T.HISTORICAL_REPORT_SHA
    @test p["model_sha256"]==T.L.MODEL_PINS["AK02"]
    @test p["native_tree_sha256"]==T.NATIVE_TREE_SHA
    @test length(p["historical_E_V_W_sha256"]["min25"])==3
    @test_throws ArgumentError T.L.check_hashes(@__DIR__,Dict("diagnose_transition_grid.jl"=>repeat("0",64)))
end

@testset "Derived-bit marking and source-weighted scale gates" begin
    sim=tiny_state(); sim.imp_scale.data .= 0.25
    SSD.mark_bits!(sim)
    bits=copy(sim.point_types.data)
    p,_=T.setup(sim)
    T.copyback!(sim,p,false)
    @test sim.point_types.data==bits
    T.copyback!(sim,p,false)
    @test sim.point_types.data==bits
    @test SSD.ImpurityScaleArray(p)==sim.imp_scale.data
    d=Dict("frozen"=>Dict("max"=>0.,"max_alpha_voltage"=>1e-4),
        "poisson"=>Dict("max"=>0.),"full_sweep"=>Dict("potential"=>0.,"alpha_voltage"=>0.))
    @test !T.acceptable(d,false)
    d["frozen"]["max_alpha_voltage"]=0.
    @test T.acceptable(d,false)
    d["full_sweep"]["alpha_voltage"]=1e-4
    @test !T.acceptable(d,false)
end
