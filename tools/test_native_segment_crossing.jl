# Geometry only: no field cache, solve, carrier drift, waveform or active-worker patch.
using SolidStateDetectors, Test, LinearAlgebra, JSON, SHA
include(joinpath(@__DIR__,"..","simulation","native_segment_crossing.jl"))
const SSD=SolidStateDetectors;const CSG=SSD.ConstructiveSolidGeometry;const N=NativeSegmentCrossing
const ROOT=normpath(joinpath(@__DIR__,".."))
const NATIVE_SHA="0358c255e37c38f62eee6f1e476c0ed48560708dfcd3d367d2688eaa022232ad"
const MODEL_SHA="4b6c71c178c81e68bc1fe093d491b59ab99f19aed5adaba5fc61bba74d445c04"
const WITNESS_SHA="cab9bffd9ff0fe9b08f158746ba49a53d5f7ccb24ee699a87e070f39ee81e51b"
point(x)=SSD.CartesianPoint{Float64}(x...)
xyz(p)=[p.x,p.y,p.z]
function geometry(T)
    det=SSD.Simulation{T}(joinpath(ROOT,"models","GeGI_3D.yaml")).detector
    axis=SSD.DiscreteAxis(T(-.05),T(.05),:infinite,:none,:closed,:closed,T[-.05,0,.05])
    grid=SSD.CartesianGrid3D{T}((axis,axis,axis))
    # Synthetic flags only select the floating-boundary branch. They are not a
    # saved field solution and cannot establish charge motion or collection.
    det,SSD.PointTypes(fill(SSD.update_bit,3,3,3),grid)
end
const DET,PT=geometry(Float64)
const RESULTS=Any[]
@testset "Retained GeGI segment geometry" begin
    @test bytes2hex(sha256(read(joinpath(dirname(pathof(SSD)),"ChargeDrift","ChargeDrift.jl"))))==NATIVE_SHA
    @test bytes2hex(sha256(read(joinpath(ROOT,"models","GeGI_3D.yaml"))))==MODEL_SHA
    @test CSG.csg_default_tol(Float64)==1e-12
    @testset "214613: tangent self-hit must not mask positive x crossing" begin
        a=point([-.04499959976637106,-.018640010540418216,-.0022397254424897854])
        b=point([-.045000607202294145,-.018639003104495126,-.002310360157999424])
        native=SSD.get_crossing_pos(DET,PT,a,b);fixed=N.get_crossing_pos(DET,PT,a,b)
        @test native[2]==SSD.CD_FLOATING_BOUNDARY && native[1]==a
        @test abs(dot(native[3],b-a))<CSG.csg_default_tol(Float64)
        fraction=dot(fixed[1]-a,b-a)/dot(b-a,b-a)
        @test fixed[2]==SSD.CD_FLOATING_BOUNDARY
        @test fraction≈.39727948921451833 atol=1e-12
        @test fixed[1].x==-.045 && fixed[1] in DET.semiconductor
        @test norm((fixed[1]-a)-fraction*(b-a))<CSG.csg_default_tol(Float64)
        @test !(fixed[1] in DET.contacts)
        push!(RESULTS,Dict("event_id"=>214613,"raw_row_index"=>4924,"native_kind"=>native[2],
            "native_hit_equals_start"=>true,"corrected_kind"=>fixed[2],"corrected_fraction"=>fraction,
            "corrected_position_m"=>xyz(fixed[1]),"geometric_contact"=>false))
    end
    @testset "717723: roundoff-sized rear hit represents outward boundary start" begin
        a=point([-.029320016272740165,-.03431959403404911,.005499803500273499])
        b=point([-.029342309610206313,-.03434177297985972,.005539019295290341])
        native=SSD.get_crossing_pos(DET,PT,a,b);fixed=N.get_crossing_pos(DET,PT,a,b)
        @test native[2]==SSD.CD_OUTSIDE
        @test fixed[2]==SSD.CD_FLOATING_BOUNDARY && fixed[1]==a
        @test dot(fixed[3],b-a)<-CSG.csg_default_tol(Float64)
        @test a in DET.semiconductor && !(a in DET.contacts)
        projected=SSD.CartesianVector{Float64}(SSD.project_to_plane(b-a,fixed[3]))
        next=N.get_crossing_pos(DET,PT,a,a+projected)
        fraction=dot(next[1]-a,projected)/dot(projected,projected)
        @test next[2]==SSD.CD_FLOATING_BOUNDARY && 0<fraction<1
        @test next[1] in DET.semiconductor && !(next[1] in DET.contacts)
        push!(RESULTS,Dict("event_id"=>717723,"raw_row_index"=>9951,"native_kind"=>native[2],
            "corrected_kind"=>fixed[2],"corrected_hit_equals_start"=>true,
            "projected_fraction"=>fraction,"projected_position_m"=>xyz(next[1]),"geometric_contact"=>false))
    end
    @testset "119171: near-tangent rear distance is not face distance" begin
        a=point([.018768015936894165,-.04487159436989512,-.004488722367791633])
        step=SSD.CartesianVector{Float64}(9.825162287463676e-6,9.824761405859146e-6,-5.182930914398237e-5)
        b=a+step;tol=CSG.csg_default_tol(Float64)
        surface=only(filter(s->CSG.distance_to_surface(a,s)<=tol,CSG.surfaces(DET.semiconductor.geometry)))
        hit=only(CSG.intersection(surface,CSG.Line{Float64}(a,normalize(b-a))))
        @test SSD.get_crossing_pos(DET,PT,a,b)[2]==SSD.CD_OUTSIDE
        @test norm(hit-a)>tol && dot(hit-a,normalize(b-a))<0
        @test CSG.distance_to_surface(a,surface)<tol
        fixed=N.get_crossing_pos(DET,PT,a,b)
        @test fixed[2]==SSD.CD_FLOATING_BOUNDARY && fixed[1]==a
        @test dot(fixed[3],b-a)<-tol
        projected=N.surface_step(DET,a,b-a,fixed[3])
        @test norm(projected)>0 && a+projected!=a && a+projected in DET.semiconductor
        @test !(a+projected in DET.contacts)
        # A genuinely interior start retains the positive native crossing.
        inside=a+2tol*fixed[3];target=inside+step
        native=SSD.get_crossing_pos(DET,PT,inside,target)
        @test native[2]!=SSD.CD_OUTSIDE && native[1]!=inside
        @test N.get_crossing_pos(DET,PT,inside,target)==native
        push!(RESULTS,Dict("event_id"=>119171,"raw_row_index"=>11425,
            "native_rear_hit_distance_m"=>norm(hit-a),"normal_distance_to_surface_m"=>CSG.distance_to_surface(a,surface),
            "corrected_hit_equals_start"=>true,"projected_step_m"=>xyz(projected),"geometric_contact"=>false))
    end
    @testset "3361: genuine outward uncontacted corner stays unresolved" begin
        a=point([-.045,-.0134494837707869,.0055])
        b=point([-.04505973027955724,-.013449869801858116,.0055])
        native=SSD.get_crossing_pos(DET,PT,a,b);fixed=N.get_crossing_pos(DET,PT,a,b)
        @test fixed==native
        @test fixed[2]==SSD.CD_FLOATING_BOUNDARY && fixed[1]==a
        @test dot(fixed[3],b-a)<-CSG.csg_default_tol(Float64)
        @test dot(fixed[1]-a,b-a)/dot(b-a,b-a)==0
        @test !(fixed[1] in DET.contacts)
        push!(RESULTS,Dict("event_id"=>3361,"raw_row_index"=>3653,"native_kind"=>native[2],
            "unchanged"=>true,"positive_fraction"=>false,"geometric_contact"=>false,"charge_unknown"=>true))
    end
    @testset "Successful native crossings remain bit-identical" begin
        # Two retained contact arrivals from successful prefix event96/raw22.
        controls=[([-.015942131639145856,-.017095565138840894,-.005426788251915503],
                   [-.01594213161084557,-.01709558822807424,-.0055]),
                  ([-.01594900716072815,-.017095413455895544,.005499860292507836],
                   [-.015949031383208846,-.017095413455896047,.0055]),
                  ([.044,0.,0.],[.046,0.,0.]),([-.044,0.,0.],[-.046,0.,0.]),
                  ([.031,.031,0.],[.033,.033,0.]),([.043,0.,.004],[.043,0.,.006])]
        for T in (Float64,Float32)
            det,types=geometry(T)
            for (start,stop) in controls
                a=SSD.CartesianPoint{T}(T.(start)...);b=SSD.CartesianPoint{T}(T.(stop)...)
                native=SSD.get_crossing_pos(det,types,a,b);fixed=N.get_crossing_pos(det,types,a,b)
                @test native[2]!=SSD.CD_OUTSIDE
                @test fixed==native
                bits=sizeof(T)==8 ? UInt64 : UInt32
                @test reinterpret(bits,xyz(fixed[1]))==reinterpret(bits,xyz(native[1]))
            end
        end
    end
    @testset "Actual two-face field steps satisfy every active inward halfspace" begin
        # Exact terminal coordinates/fields from the preserved whole-group v2
        # failures, validation5a2e2a47... . No field cache or new solve is used.
        cases=((214613,[-.045,-.018639610306789275,-.0022677871661882674],
                [11271.527437509492,9350.530403337745,57925.74883439544]),
               (717723,[-.029320016559332966,-.034319593747456315,.0055],
                [30171.39060805545,30107.00201651533,-39610.97713438113]),
               (3361,[-.045,-.0134494837707869,.0055],
                [60142.48686957425,1104.7714135200715,-49892.57712306136]))
        for (eid,coordinates,field) in cases
            p=point(coordinates)
            velocity=SSD.getVe(SSD.SVector{3,Float64}(field),DET.semiconductor.charge_drift_model,p)
            step=SSD.modulate_driftvector(SSD.CartesianVector{Float64}(velocity*1e-9),p,DET.virtual_drift_volumes)
            _,kind,normal=N.get_crossing_pos(DET,PT,p,p+step)
            normals=N.active_inward_normals(DET,p)
            original=SSD.CartesianVector{Float64}(SSD.project_to_plane(step,normal))
            corrected=N.surface_step(DET,p,step,normal)
            @test kind==SSD.CD_FLOATING_BOUNDARY && length(normals)==2
            @test minimum(dot(n,original) for n in normals)<-CSG.csg_default_tol(Float64)
            @test all(n->dot(n,corrected)>=-CSG.csg_default_tol(Float64),normals)
            @test norm(corrected)>0 && p+corrected in DET.semiconductor
            @test !(p+corrected in DET.contacts)
            push!(RESULTS,Dict("event_id"=>eid,"active_inward_normals"=>xyz.(normals),
                "original_field_step_m"=>xyz(step),"single_normal_step_m"=>xyz(original),
                "admissible_step_m"=>xyz(corrected),"normal_components_m"=>[dot(n,corrected) for n in normals],
                "time_step_ns"=>1,"geometric_contact"=>false))
        end
    end
    @testset "Tiny feasible tangent motion survives normal-cost cancellation" begin
        # Exact final V3 717723 electron state from the preserved 5 us run.
        p=point([-.029332772398631777,-.03430683790815734,.0055])
        step=SSD.CartesianVector{Float64}(-2.2208676048537906e-5,-2.2208675136449447e-5,3.9416468193657255e-5)
        normals=N.active_inward_normals(DET,p)
        direction=normalize(cross(normals[1],normals[2]))
        expected=SSD.CartesianVector{Float64}(direction*dot(direction,step))
        corrected=N.surface_step(DET,p,step,SSD.CartesianVector{Float64}(0.,0.,-1.))
        @test length(normals)==2
        @test norm(corrected-expected)<=8eps(Float64)*norm(step) && norm(corrected)>0
        @test p+corrected!=p && p+corrected in DET.semiconductor
        @test all(n->dot(n,corrected)>=-CSG.csg_default_tol(Float64),normals)
        @test !(p+corrected in DET.contacts)
        # The tangent is deliberately much smaller than either outward normal.
        p=point([-.045,-.0134494837707869,.0055])
        step=SSD.CartesianVector{Float64}(-3e-5,1e-13,4e-5)
        corrected=N.surface_step(DET,p,step,SSD.CartesianVector{Float64}(0.,0.,-1.))
        @test corrected==SSD.CartesianVector{Float64}(0.,1e-13,0.)
        @test p+corrected!=p && p+corrected in DET.semiconductor
        @test !(p+corrected in DET.contacts)
        push!(RESULTS,Dict("event_id"=>717723,"saved_v3_projection_was_zero"=>true,
            "stable_projection_m"=>xyz(expected),"coordinate_changes"=>true,"geometric_contact"=>false))
    end
    @testset "Inward motion is retained and an outward-only corner cannot collect" begin
        p=point([-.045,-.0134494837707869,.0055]);normals=N.active_inward_normals(DET,p)
        inward=SSD.CartesianVector{Float64}(1e-5,2e-5,-3e-5)
        @test N.surface_step(DET,p,inward,first(normals))==inward
        outward=SSD.CartesianVector{Float64}(-1e-5,0.,3e-5)
        @test N.surface_step(DET,p,outward,first(normals))==zero(outward)
        @test !(p in DET.contacts)
        mixed=SSD.CartesianVector{Float64}(1e-5,2e-5,3e-5)
        @test N.surface_step(DET,p,mixed,first(normals))==SSD.CartesianVector{Float64}(1e-5,2e-5,0.)
        p=point([.045,0.,0.]);step=SSD.CartesianVector{Float64}(1e-5,2e-5,3e-5)
        normal=SSD.CartesianVector{Float64}(-1.,0.,0.)
        @test N.surface_step(DET,p,step,normal)==SSD.CartesianVector{Float64}(SSD.project_to_plane(step,normal))
    end
end
if !isempty(ARGS)
    @assert length(ARGS)==1 && !ispath(ARGS[1]) "Use a new geometry result file"
    open(ARGS[1],"w") do io
        JSON.print(io,Dict("kind"=>"gegi_isolated_segment_crossing_geometry_v1",
            "native_source_sha256"=>NATIVE_SHA,"model_sha256"=>MODEL_SHA,"witness_diagnosis_sha256"=>WITNESS_SHA,
            "helper_sha256"=>bytes2hex(sha256(read(joinpath(ROOT,"simulation","native_segment_crossing.jl")))),
            "test_sha256"=>bytes2hex(sha256(read(@__FILE__))),"results"=>RESULTS,
            "successful_control_segments"=>6,"control_precision_bits"=>[32,64],"process_peak_rss_bytes"=>Sys.maxrss(),
            "field_caches_loaded"=>0,"new_field_solves"=>0,"new_drift_calls"=>0,
            "scope"=>"Pure nominal CSG geometry with synthetic floating flags. No waveform recovery, drift integration or multi-face charge-collection claim."),2)
    end
end
