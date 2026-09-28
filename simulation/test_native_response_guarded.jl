include("native_response_guarded.jl")
using Test, SHA
const W=GuardedNativeResponse
const G=NativeBoundaryGuard
const R=NativeResponse
@testset "Guarded native response entry" begin
    package=joinpath(dirname(pathof(G.SSD)),"ChargeDrift","ChargeDrift.jl")
    before=bytes2hex(sha256(read(package)))
    provenance=G.install!(); W.install_attempt!()
    @test provenance["kind"]=="ssd_0_11_8_boundary_guard_v1"
    @test provenance["package_files_modified"]===false
    @test bytes2hex(sha256(read(package)))==before==G.EXPECTED
    ok=R.native_attempt(()->7,"record")
    @test ok.result==7 && ok.error===nothing
    bad=G.BoundaryStall(23,(0.,0.,0.),(1.,2.,3.),(4.,5.,6.))
    stalled=R.native_attempt(()->throw(bad),"record")
    @test stalled.result===nothing
    @test stalled.error["type"]=="NativeBoundaryStall"
    @test stalled.error["step"]==23
    allowed=R.native_attempt(()->throw(ArgumentError(first(R.NATIVE_FAILURE_MESSAGES))),"record")
    @test allowed.result===nothing
    @test allowed.error["message"]==first(R.NATIVE_FAILURE_MESSAGES)
    @test_throws G.BoundaryStall R.native_attempt(()->throw(bad),"abort")
    @test_throws DomainError R.native_attempt(()->throw(DomainError(1)),"record")
end
