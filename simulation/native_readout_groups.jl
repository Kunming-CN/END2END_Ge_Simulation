# Output-boundary adapter only: all native math/lifecycle remains NativeGroups.
include("native_groups.jl")
using JSON # Entrypoint scope is Main; NativeGroups' import does not import here.
if abspath(PROGRAM_FILE)==@__FILE__
    if ARGS==["--probe"]
        println(JSON.json(NativeGroups.runtime()))
    elseif length(ARGS)==2 && ARGS[1]=="--session"
        NativeGroups.session(ARGS[2]; allow_primary_selection=true, allow_detector_selection=true, output_base=joinpath(NativeGroups.ROOT,".local",
            "native-readout-integration-v1","implementation","outputs"))
    else
        error("Usage: native_readout_groups.jl --probe | --session FILE")
    end
end
