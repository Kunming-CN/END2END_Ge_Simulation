# Independent, source-free cylindrical electrostatic verifier; not a production solver.
module AnalyticElectrostatics
using LinearAlgebra, SHA, JSON
const ROOT=normpath(joinpath(@__DIR__,".."))
const GATES=(residual=1e-11,flux_spread=1e-10,finest_voltage=1e-3,finest_field=1e-3,refinement_ratio=0.4)
check(ok,msg)=ok ? nothing : throw(ArgumentError(msg))
function grid(n; a=0.005,b=0.015,mapping=:quadratic)
    check(n isa Integer && !(n isa Bool) && 3<=n<=10000,"Invalid node count")
    check(isfinite(a)&&isfinite(b)&&0<a<b,"Require positive ordered radii")
    t=collect(range(0.0,1.0;length=n))
    r = mapping===:quadratic ? a .+ (b-a).*(0.35.*t.+0.65.*t.^2) :
        mapping===:log ? a.*exp.(log(b/a).*t) : throw(ArgumentError("Unknown grid mapping"))
    r[1]=a; r[end]=b
    r
end
function exact_potential(r,a,b,va,vb)
    va .+ (vb-va).*log.(r./a)./log(b/a)
end
exact_field(r,a,b,va,vb)=-(vb-va)./(r.*log(b/a))
function system(r,va,vb)
    check(length(r)>=3 && all(isfinite,r) && first(r)>0 && all(diff(r).>0),"Invalid radial grid")
    check(isfinite(va)&&isfinite(vb),"Nonfinite voltage")
    faces=(r[1:end-1].+r[2:end])./2
    k=faces./diff(r)
    diagonal=k[1:end-1].+k[2:end]
    off=-k[2:end-1]
    matrix=SymTridiagonal(diagonal,off)
    rhs=zeros(length(r)-2); rhs[1]+=k[1]*va; rhs[end]+=k[end]*vb
    (matrix=matrix,rhs=rhs,faces=faces,conductance=k)
end
function metrics(r,v,va,vb)
    check(length(v)==length(r)&&all(isfinite,v),"Invalid potential values")
    sys=system(r,va,vb)
    residual=sys.matrix*v[2:end-1]-sys.rhs
    span=max(abs(vb-va),abs(va),abs(vb),1.0) # Stable absolute scale for constant-potential checks.
    row_scale=maximum(abs,diag(sys.matrix))*span
    flux=-sys.faces.*diff(v)./diff(r) # r E, common 2*pi*epsilon factor omitted.
    expected_flux=-(vb-va)/log(last(r)/first(r))
    normflux=iszero(vb-va) ? span : abs(expected_flux)
    reference=exact_potential(r,first(r),last(r),va,vb)
    field=-diff(v)./diff(r)
    fieldref=exact_field(sys.faces,first(r),last(r),va,vb)
    analyticres=sys.matrix*reference[2:end-1]-sys.rhs
    volumes=0.5 .* (sys.faces[2:end].^2 .- sys.faces[1:end-1].^2)
    Dict("normalized_algebraic_residual"=>maximum(abs,residual)/row_scale,
        "normalized_analytic_FV_residual"=>maximum(abs,analyticres./volumes)/(span/first(r)^2),
        "relative_flux_spread"=>(maximum(flux)-minimum(flux))/normflux,
        "relative_flux_error"=>maximum(abs,flux.-expected_flux)/normflux,
        "relative_voltage_error"=>maximum(abs,v.-reference)/span,
        "absolute_face_field_error_V_m"=>maximum(abs,field.-fieldref),
        "relative_face_field_error"=>iszero(vb-va) ? nothing : maximum(abs.(field.-fieldref)./abs.(fieldref)),
        "boundary_error_V"=>max(abs(first(v)-va),abs(last(v)-vb)),
        "faces_m"=>sys.faces,"numeric_field_V_m"=>field,"analytic_field_V_m"=>fieldref,
        "numeric_potential_V"=>v,"analytic_potential_V"=>reference,"radii_m"=>r)
end
function solve_case(n; mapping=:quadratic,va=0.0,vb=500.0)
    r=grid(n;mapping=mapping); s=system(r,va,vb)
    v=vcat(va,s.matrix\s.rhs,vb)
    m=metrics(r,v,va,vb)
    m["nodes"]=n; m["mapping"]=string(mapping);m["Va_V"]=va;m["Vb_V"]=vb
    m
end
function enforce(cases)
    check(length(cases)==3,"Exactly three nested-grid cases required")
    for c in cases
        check(c["boundary_error_V"]==0,"Dirichlet boundary not exact")
        check(c["normalized_algebraic_residual"]<=GATES.residual,"Algebraic residual failure")
        check(c["relative_flux_spread"]<=GATES.flux_spread,"Conservative flux failure")
        check(all(c["numeric_field_V_m"].<0),"Wrong electric field sign")
    end
    for key in ("relative_voltage_error","relative_face_field_error","normalized_analytic_FV_residual")
        for i in 2:3
            check(cases[i][key]/cases[i-1][key]<=GATES.refinement_ratio,"Refinement rate failed for "*key)
        end
    end
    check(last(cases)["relative_voltage_error"]<=GATES.finest_voltage,"Finest potential error too large")
    check(last(cases)["relative_face_field_error"]<=GATES.finest_field,"Finest field error too large")
    true
end
function output_path(p)
    target=abspath(p); base=joinpath(realpath(ROOT),".local")
    rel=relpath(target,base)
    check(rel!="."&&!isabspath(rel)&&first(splitpath(rel))!="..","Output must be under .local")
    check(!ispath(target)&&!islink(target),"Output already exists")
    parent=dirname(target)
    while !ispath(parent); parent=dirname(parent); end
    check(!islink(parent)&&startswith(relpath(realpath(parent),base),"..")===false,"Linked/outside output parent")
    target
end
function run(output)
    out=output_path(output);mkpath(out)
    report=Dict{String,Any}("status"=>"running","scope"=>"Independent charge-free annulus operator; no AK02 depletion/CCE validation",
        "equation"=>"(1/r) d/dr (r dV/dr)=0; V(a)=0,V(b)=500 V",
        "operator"=>"Midpoint conservative finite volumes with face conductance r_face/(r_right-r_left)",
        "a_m"=>0.005,"b_m"=>0.015,"gates"=>Dict(string(k)=>v for (k,v) in pairs(GATES)),
        "julia_version"=>string(VERSION),"source_sha256"=>bytes2hex(sha256(read(@__FILE__))),"cases"=>Any[])
    try
        for n in (17,33,65)
            push!(report["cases"],solve_case(n))
        end
        enforce(report["cases"])
        report["observed_orders"] = Dict(k=>[log2(report["cases"][i-1][k]/report["cases"][i][k]) for i in 2:3] for k in ("relative_voltage_error","relative_face_field_error","normalized_analytic_FV_residual"))
        report["status"]="passed_independent_operator_only"
        open(joinpath(out,"profiles.csv"),"w") do io
            println(io,"nodes,radius_m,numeric_V,analytic_V")
            for c in report["cases"],i in eachindex(c["radii_m"])
                println(io,join([c["nodes"],c["radii_m"][i],c["numeric_potential_V"][i],c["analytic_potential_V"][i]],','))
            end
        end
    catch e
        report["status"]="failed";report["error"]=sprint(showerror,e);rethrow()
    finally
        open(io->JSON.print(io,report,2),joinpath(out,"run.json"),"w")
    end
    for c in report["cases"]
        println((nodes=c["nodes"],voltage_error=c["relative_voltage_error"],field_error=c["relative_face_field_error"],residual=c["normalized_algebraic_residual"]))
    end
    report
end
end
if abspath(PROGRAM_FILE)==@__FILE__
    length(ARGS)==2&&ARGS[1]=="--output"||error("Usage: julia --project=simulation simulation/verify_electrostatics.jl --output .local/NEW")
    AnalyticElectrostatics.run(ARGS[2])
end
