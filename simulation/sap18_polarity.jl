# SAP18 fixed wiring around unchanged native-sign-independent readout routines.
isdefined(@__MODULE__, :RingPolarity) || include("ring_polarity.jl")
module Sap18Polarity
using ..RingPolarity
const RP=RingPolarity;const E=RP.E;const P=RP.P
const MODEL="SAP18_ring08_scenario";const FACTOR=-1.0
wiring()=Dict("kind"=>"fixed_sap18_readout_wiring_v1","model_id"=>MODEL,"factor"=>FACTOR,
    "stage"=>"native signed induced charge -> electronics input","raw_signal_policy"=>"fixed linear input wiring; no abs or event-specific sign/gain")
function negative_calibration(c,eion,dt,M=E.transition(c,dt))
    # One independent negative injection through the same fixed linear transfer.
    r=RP.negative_calibration(c,eion,dt,M)
    r.calibration["method"]="independent negative delta-charge at t=0 through fixed -1 SAP18 wiring; unchanged sampled analog transfer; one slope across all events"
    r.injection["wiring"]=wiring()
    r
end
function process(t,q,c,eion,cal,M;horizon_ns)
    E.check(all(E.finite,q),"Nonfinite signed SAP18 charge")
    r=P.process(t,FACTOR .* q,c,eion,cal,M;horizon_ns=horizon_ns)
    E.check(r["current_balance"]["passed"],"SAP18 current/charge balance failed")
    r["wiring"]=wiring();r["raw_native_any_negative_charge"]=any(x->x<0,q)
    r["raw_native_final_charge_keV"]=last(q);r["raw_native_min_charge_keV"]=minimum(q);r["raw_native_max_charge_keV"]=maximum(q)
    trace=r["trace"];trace["raw_native_induced_charge_fC"]=FACTOR .* trace["induced_charge_fC"]
    trace["raw_native_current_nA"]=FACTOR .* trace["current_nA"]
    r
end
end
