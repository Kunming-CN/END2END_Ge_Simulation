# Lightweight checks only: no potential solves, package installs or CUDA loading.
using Test
include("verify_ssd_electrostatics.jl")
const S = SSDElectrostatics

function analytic_evidence(n=65; va=0.0,vb=10.0)
    r=S.annulus(n)
    p=repeat(reshape(S.A.exact_potential(r,S.INNER,S.OUTER,va,vb),:,1,1),1,1,2)
    er=repeat(reshape(S.A.exact_field(r,S.INNER,S.OUTER,va,vb),:,1,1),1,8,2)
    (r=r,p=p,er=er,ep=zeros(size(er)),ez=zeros(size(er)))
end
measure(e,va=0.0,vb=10.0)=S.diagnostics(e.r,e.p,e.er,e.ep,e.ez,va,vb)

@testset "synthetic SSD contract, no solves" begin
    @test pkgversion(S.SSD)==v"0.11.8"
    @test !any(id.name=="CUDA" for id in keys(Base.loaded_modules))
    @test S.annulus(17)==S.annulus(33)[1:2:end]
    @test S.annulus(33)==S.annulus(65)[1:2:end]
    for n in S.COUNTS
        @test S.validate_ticks(S.ticks(S.make_grid(n)),S.requested_ticks(n))
    end
    for n in (true,2,18,129)
        @test_throws ArgumentError S.annulus(n)
    end
    @test_throws ArgumentError S.annulus(17;unit="mm")
    for (a,b) in ((0.005,0.035),(0.0,S.OUTER),(S.OUTER,S.INNER),(NaN,S.OUTER))
        @test_throws ArgumentError S.annulus(17;a,b)
    end
    t=S.requested_ticks(17)
    for r in (t.r.*1000,reverse(t.r),vcat(t.r[1:end-1],NaN))
        @test_throws ArgumentError S.validate_ticks((r=r,phi=t.phi,z=t.z),t)
    end
    @test_throws ArgumentError S.validate_ticks((r=t.r,phi=t.phi,z=[-0.002,0.002]),t)
    @test_throws ArgumentError S.A.output_path(joinpath(S.ROOT,"models","forbidden"))
    @test_throws ArgumentError S.A.output_path(joinpath(S.ROOT,".local"))
    @test_throws ArgumentError S.A.output_path(joinpath(S.ROOT,".local","..","simulation"))
    @test_throws ArgumentError S.main(["--device","cuda"])
    @test_throws ArgumentError S.main(["--max-iterations","-1"])

    cfg=deepcopy(S.SSD.Simulation{Float64}(S.SSD.SSD_examples[:InfiniteCoaxialCapacitor]).config_dict)
    @test S.validate_config(cfg)
    bad=deepcopy(cfg);bad["units"]["length"]="m"
    @test_throws ArgumentError S.validate_config(bad)
    bad=deepcopy(cfg);only(bad["detectors"])["contacts"][1]["geometry"]["tube"]["r"]["to"]=5
    @test_throws ArgumentError S.validate_config(bad)
    bad=deepcopy(cfg);bad["grid"]["axes"]["z"]["boundaries"]="inf"
    @test_throws ArgumentError S.validate_config(bad)

    r=S.requested_ticks(17).r
    bits=fill(S.SSD.update_bit,length(r),1,2)
    for i in eachindex(r)
        if 0.005<=r[i]<=S.INNER || S.OUTER<=r[i]<=0.035
            bits[i,:,:].=0
        end
    end
    @test S.validate_masks(r,bits)
    bad=copy(bits);bad[findfirst(==(S.INNER),r),:,:].=S.SSD.update_bit
    @test_throws ArgumentError S.validate_masks(r,bad)
    bad=copy(bits);bad[6,:,:].=0
    @test_throws ArgumentError S.validate_masks(r,bad)
end

@testset "independent diagnostic limits and injected failures" begin
    e=analytic_evidence();m=measure(e)
    @test S.enforce_diagnostics(m,0.0,10.0;finest=true)
    @test all(e.er .< 0)
    @test m["voltage_error_V"]==0
    @test m["reference_FV"][1]["normalized_algebraic_residual"]>0
    @test m["reference_FV"][1]["numeric_potential_V"]==e.p[:,1,1]
    for value in (0.0,42.0)
        equal=analytic_evidence(;va=value,vb=value)
        metric=measure(equal,value,value)
        @test S.enforce_diagnostics(metric,value,value;finest=true)
        @test metric["midpoint_relative_error"]===nothing
        @test metric["interior_field_relative_error"]===nothing
        @test metric["field_absolute_error_V_m"]==0
    end
    reverse=analytic_evidence(;va=10.0,vb=0.0)
    @test S.enforce_diagnostics(measure(reverse,10.0,0.0),10.0,0.0;finest=true)
    @test maximum(abs,reverse.p.+e.p.-10)<1e-13
    offset=analytic_evidence(;va=42.0,vb=52.0)
    @test S.enforce_diagnostics(measure(offset,42.0,52.0),42.0,52.0;finest=true)
    @test offset.er==e.er
    for (array,index,delta) in ((:p,(20,1,1),1.0),(:p,(1,1,1),1e-5),
        (:er,(20,1,1),100.0),(:ep,(20,1,1),1.0),(:ez,(20,1,1),1.0))
        bad=deepcopy(e);getproperty(bad,array)[index...]+=delta
        @test_throws ArgumentError S.enforce_diagnostics(measure(bad),0.0,10.0;finest=true)
    end
    bad=deepcopy(e);bad.er.*=-1
    @test_throws ArgumentError S.enforce_diagnostics(measure(bad),0.0,10.0;finest=true)
    bad=deepcopy(e);bad.r[20]+=1e-6
    @test_throws ArgumentError measure(bad)
    bad=deepcopy(e);bad.r.*=1000
    @test_throws ArgumentError measure(bad)
    bad=deepcopy(e);bad.p[20,1,1]=NaN
    @test_throws ArgumentError measure(bad)
    @test_throws ArgumentError measure(e,NaN,10.0)
    # Exercise Cartesian -> cylindrical projection at all actual sample angles.
    phi=collect(range(0.0,2pi;length=9))[1:8]
    vectors=[S.SSD.SVector(-2cos(a),-2sin(a),0.0) for i in 1:3,a in phi,k in 1:2]
    projected=S.project_field(vectors,phi)
    @test maximum(abs,projected.er.+2)<1e-14
    @test maximum(abs,projected.ep)<1e-14
    @test all(iszero,projected.ez)
    # Log-grid control belongs to the reference FV operator, not to SSD's solver.
    loggrid=S.A.grid(33;a=S.INNER,b=S.OUTER,mapping=:log)
    exact=S.A.exact_potential(loggrid,S.INNER,S.OUTER,0.0,10.0)
    metrics=S.A.metrics(loggrid,exact,0.0,10.0)
    @test metrics["normalized_algebraic_residual"]<1e-12
    @test metrics["relative_face_field_error"]>0
    cases=[Dict("nodes"=>n,"diagnostics"=>measure(analytic_evidence(n))) for n in S.COUNTS]
    ratios=S.enforce_refinement(cases)
    @test all(x -> x<=S.GATES.refinement_ratio,ratios["midpoint_relative_error"])
    bad=deepcopy(cases)
    bad[3]["diagnostics"]["midpoint_relative_error"]=bad[2]["diagnostics"]["midpoint_relative_error"]
    @test_throws ArgumentError S.enforce_refinement(bad)
    @test !any(id.name=="CUDA" for id in keys(Base.loaded_modules))
end

@testset "collapsed-axis source initialization regression" begin
    sim=S.SSD.Simulation{Float64}(S.SSD.SSD_examples[:InfiniteCoaxialCapacitor])
    grid=S.make_grid(17)
    ext=S.SSD.get_extended_ticks(grid.axes[2])
    @test length(ext)==3
    @test all(isfinite,ext) && all(diff(ext).>0)
    @test ext==[-2pi,0.0,2pi]
    S.SSD.apply_initial_state!(sim,S.SSD.ElectricPotential,grid;
        depletion_handling=false,paint_contacts=false,not_only_paint_contacts=true)
    report=S.source_check(sim)
    @test report["max_impurity_source"]==0
    @test report["max_fixed_source"]==0
    @test report["relative_permittivity_extrema"]==[16.0,16.0]
    @test S.validate_masks(S.ticks(grid).r,sim.point_types.data)
    # A zero-width periodic/open custom axis has zero integration volume.
    t=S.requested_ticks(17)
    badphi=S.SSD.DiscreteAxis(0.0,0.0,:periodic,:periodic,:closed,:open,t.phi)
    @test !all(diff(S.SSD.get_extended_ticks(badphi)).>0)
    @test S.provenance()["manifest_sha256"]==S.hashfile(joinpath(S.ROOT,"simulation","Manifest.toml"))
end

@testset "independent native-field stencil diagnostics" begin
    e=analytic_evidence();m=measure(e)
    @test m["SSD_minus_numeric_stencil_interior_max_V_m"] ≈ m["exact_nodal_interior_stencil_error_V_m"]
    slopes=-diff(e.p[:,1,1])./diff(e.r)
    stencil=vcat(first(slopes),(slopes[1:end-1].+slopes[2:end])./2,last(slopes))
    e.er .= reshape(stencil,:,1,1)
    m=measure(e)
    @test m["SSD_minus_numeric_stencil_interior_max_V_m"]==0
    @test m["SSD_minus_numeric_stencil_contact_max_V_m"]==[0,0]
    e.er[20,1,1]+=0.01
    @test measure(e)["SSD_minus_numeric_stencil_interior_max_V_m"]>0.009
end
