using Test
include("native_li_example.jl")
const N=NativeLiExample
@testset "Selected native example contract" begin
    design=N.cases()
    @test length(design)==14
    @test unique(c.id for c in design)==N.IDS
    @test count(c->c.mode=="legacy",design)==4
    @test all(c->c.id in (41,78),filter(c->c.parcels==32,design))
    @test length(unique(N.parcel_seed(s,41,10,p) for s in N.SEEDS for p in 1:32))==64
    @test N.parcel_seed(2609261,41,10,1)==N.parcel_seed(2609261,41,10,1)
    @test N.parcel_seed(2609261,41,10,1)!=N.parcel_seed(2609261,41,11,1)
    a=(energy=0.5,times=[0.,2.,4.],charge=[0.,0.1,0.3])
    b=(energy=0.5,times=[0.,2.],charge=[0.,-0.1])
    t,q=N.sum_parcels([a,b],1.0)
    @test t==[0.,2.,4.] && q≈[0.,0.,0.2]
    @test_throws ArgumentError N.sum_parcels([a],1.0)
    @test_throws ArgumentError N.sum_parcels([],1.0)
    @test N.escape("<untrusted>")=="&lt;untrusted&gt;"
    @test_throws ErrorException N.options(["--input","x"])
    @test_throws ArgumentError N.Q.validate_output("docs/escaped")
    @test N.flags([])["carrier_parcels"]==0
    sim,_=N.R.setup_simulation("AK02";temperature=77.0)
    event=Dict("event_id"=>0,"primary_time_ns"=>0.,"steps"=>Any[])
    z=N.native_event(event,sim,(contact=1,),16,N.SEEDS[1])
    @test z.times==[0.,2.] && z.signal==[0.,0.] && isempty(z.steps)
end

@testset "Field identity and honest presentation" begin
    f=(data=zeros(2,1,2),grid=(axes=([0.,1.],[0.],[0.,1.]),))
    fake=(electric_field=f,electric_potential=deepcopy(f),weighting_potentials=[deepcopy(f)])
    before=N.field_fingerprint(fake)
    fake.weighting_potentials[1].data[1]=1
    @test N.field_fingerprint(fake)!=before
    before=N.field_fingerprint(fake)
    fake.electric_field.grid.axes[1][2]=2
    @test N.field_fingerprint(fake)!=before
    mktempdir(joinpath(N.Q.ROOT,".local")) do dir
        file=joinpath(dir,"comparison.html")
        N.write_html(file,Dict("cases"=>Any[]))
        text=read(file,String)
        @test occursin("Legacy: diffusion off",text)
        @test occursin("Native RCC: diffusion on",text)
        @test occursin("not a calibrated spectrum",text)
        @test !occursin("<script",text)
    end
end
