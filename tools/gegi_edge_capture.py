"""Capture the fixed one-axis GeGI edge scans for saved event 2950."""

import argparse
import hashlib
import json
import math
from pathlib import Path

import yaml

import gegi_full34_pilot as pilot


ROOT, W = pilot.ROOT, pilot.W
ORIGINAL = ROOT/'.local/gegi-digital-v1/two-site-position'
BANK = ROOT/pilot.CALIBRATION/'full34-bank/results'
RUN = ROOT/'.local/runs/gegi-5000-imaging-v1'
OUT = ROOT/'.local/gegi-edge-position'
STATUS = 'completed_gegi_2950_edge_injections'
FIT_DEPTHS = (-5., 0., 5.)
HOLDOUT_DEPTHS = (-2.5, 2.5)
HOLDOUT_OFFSETS = (.425, .462, .486, .506, .519, .539)
ENERGY_KEV = 500.
KEYS = ('model_ref', 'model_sha256', 'field_cache', 'field_precision_bits', 'numerics', 'channels', 'environment')

WORKER = pilot.JULIA_WORKER.split('bits_equal', 1)[0] + r'''
function endpoint_status(row)
    endpoints=row["endpoints"]
    endpoints===nothing && return (row["status"], nothing)
    ids=Dict(e["species"]=>e["contact_ids"] for e in endpoints)
    complete=length(endpoints)==2 && all(e->e["status"]=="contact" &&
        !e["step_limit_reached"] && !isempty(e["contact_ids"]),endpoints)
    complete || return ("terminal_unverified", ids)
    any(v->length(v)>1,values(ids)) && return ("multiple_endpoint_contacts", ids)
    expected = ids["hole"]==[row["contact_ids"][1]] && ids["electron"]==[row["contact_ids"][2]]
    return (expected ? "original_strip_pair" : "different_strip_pair", ids)
end

function main(reqpath,out)
    req=G.E.readjson(reqpath);requestsha=G.hashfile(reqpath)
    check(Threads.nthreads()==1 && length(req["points"])==66,"Fixed shot budget and one thread required")
    check(G.E.environment()==req["environment"]["native"],"Pinned native environment changed")
    check(string(pkgversion(SSD))=="0.11.8","Original SSD version changed")
    src=joinpath(dirname(dirname(pathof(SSD))),"src")
    for (ref,digest) in req["environment"]["SSD_science_source_sha256"]
        check(G.hashfile(joinpath(src,ref))==digest,"SSD science source changed")
    end
    cfg=(; (Symbol(k)=>v for (k,v) in req["numerics"])...)
    report=Dict{String,Any}()
    sim=G.load_fields(Dict("field_cache"=>req["field_cache"]),joinpath(G.ROOT,req["model_ref"]),out,cfg,report)
    check(report["fields"]["mode"]=="explicit_exact_model_cache" && report["fields"]["solve_seconds"]==0 &&
        8sizeof(SSD.get_precision_type(sim))==req["field_precision_bits"] &&
        G.H.channel_metadata(sim.config_dict)==req["channels"] &&
        sim.detector.semiconductor.charge_trapping_model isa SSD.NoChargeTrappingModel,"Pinned field or contact state changed")
    ticks(field,k)=1000 .* Float64.(field.grid.axes[k].ticks)
    electric=Dict(axis=>ticks(sim.electric_potential,k) for (axis,k) in (("x",1),("y",2)))
    weighting=Dict(string(id)=>Dict(edge["axis"]=>ticks(sim.weighting_potentials[id],edge["axis_index"]+1))
        for edge in req["edges"] for id in (edge["scanned_contact_id"],edge["adjacent_contact_id"]))
    G.save(joinpath(out,"startup.json"),merge(report,Dict("peak_rss_bytes"=>Sys.maxrss(),
        "axis_ticks_mm"=>Dict("electric_potential"=>electric,"weighting_potentials"=>weighting),
        "startup_seconds_including_worker_imports"=>time()-parse(Float64,ENV["GEGI_FULL34_STARTED_UNIX"]))))
    records=Any[]
    for (i,p) in enumerate(req["points"])
        check(time()<parse(Float64,ENV["GEGI_FULL34_DEADLINE_UNIX"]),"Reached time budget")
        ref="injections/point-"*lpad(string(i),3,'0')*".json"
        path=joinpath(out,ref)
        row,reused=K.checkpoint_injection(sim,cfg,p["contact_ids"]...,p["position_mm"],
            req["injection_energy_keV"],path,requestsha)
        check(!reused,"Keep each original shot and run only into a fresh result directory")
        collection,ids=endpoint_status(row)
        push!(records,merge(p,Dict("record_ref"=>ref,"record_sha256"=>G.hashfile(path),
            "status"=>row["status"],"valid"=>row["valid"],"execution_seconds"=>row["execution_seconds"],
            "terminal_collection"=>collection,"observed_endpoint_contact_ids"=>ids,
            "full34_available"=>row["channel_signals"]!==nothing)))
    end
    totals=Dict(label=>count(r->r["terminal_collection"]==label,records)
        for label in unique(r["terminal_collection"] for r in records))
    G.save(joinpath(out,"COMPLETE.json"),Dict("status"=>"completed_gegi_2950_edge_injections",
        "request_sha256"=>requestsha,"records"=>records,"terminal_collection_counts"=>totals,
        "native_drift_attempts"=>count(r->r["status"]!="excluded_geometry",records),
        "new_field_solves"=>0,"new_transport_calls"=>0,"reused_reference_records"=>req["reused_reference_records"]))
end

try
    main(ARGS...)
catch err
    G.save(joinpath(ARGS[2],"failure.json"),Dict("status"=>"failed_stop_preserve_partial",
        "error"=>sprint(showerror,err),"exception_type"=>string(typeof(err))))
    rethrow()
end
'''


def _geometry(request, study):
    model = yaml.safe_load((ROOT/request['model_ref']).read_bytes())
    contacts = {c['id']: c for c in model['detectors'][0]['contacts']}
    axes = []
    for pair, centroid in zip(study['pixels'], study['simulation_truth_energy_centroids_mm'], strict=True):
        centers = [request['channels'][cid-1]['strip_center_mm'] for cid in pair]
        delta = [p-c for p, c in zip(centroid[:2], centers)]
        axis = max(range(2), key=lambda i: abs(delta[i]))
        direction = 1 if delta[axis] > 0 else -1
        cid, neighbor = pair[axis], pair[axis]+direction
        c, n = (contacts[i]['geometry']['intersection'][-1]['box'] for i in (cid, neighbor))
        center, other = c['origin'][axis], n['origin'][axis]
        pitch = abs(other-center)
        half, neighbor_half = c['widths'][axis]/2, n['widths'][axis]/2
        W.require(center == centers[axis] and math.isclose(pitch, request['pitch_mm'], abs_tol=1e-12)
                  and pitch > half + neighbor_half, 'Original strip centre, pitch or gap changed')
        edges = [half/pitch, 1-neighbor_half/pitch]
        W.require(.4 < abs(delta[axis])/pitch < .5 and .45 < edges[0] < .49 < .51 < edges[1] < .55,
                  'Saved 2950 centroid or actual strip edges differ from this one-axis design')
        axes.append({'edge_id': '-'.join(map(str, pair)), 'contact_ids': pair,
                     'axis': 'xy'[axis], 'axis_index': axis, 'direction': direction, 'strip_centers_mm': centers,
                     'scanned_contact_id': cid, 'adjacent_contact_id': neighbor,
                     'pitch_mm': pitch, 'original_width_mm': 2*half, 'adjacent_width_mm': 2*neighbor_half,
                     'gap_mm': pitch-half-neighbor_half, 'electrode_edges_offset_pitch_fraction': edges,
                     'electrode_edges_axis_mm': [center+direction*half, other-direction*neighbor_half],
                     'centroid_offset_pitch_fraction_toward_neighbor': abs(delta[axis])/pitch,
                     'centroid_mm_evaluation_only': centroid})
    return axes


def _point(edge, offset, depth, role):
    xyz = [*edge['strip_centers_mm'], depth]
    xyz[edge['axis_index']] += edge['direction']*edge['pitch_mm']*offset
    return {'edge_id': edge['edge_id'], 'contact_ids': edge['contact_ids'], 'role': role,
            'offset_pitch_fraction_toward_neighbor': offset, 'position_mm': xyz}


def _reference_records(axes, old_seal, bank_seal, bank_identity):
    validation = BANK/'validation.jsonl'
    W.require(W.sha(validation) == bank_seal['validation_sha256'], 'Centre bank validation ledger changed')
    targets = {f"injections/{edge['edge_id']}/z{int(z+6)}.json" for edge in axes for z in FIT_DEPTHS}
    with validation.open(encoding='utf-8') as src:
        bank = {item['record_ref']: item for item in map(json.loads, src) if item['record_ref'] in targets}
    references = []
    for edge in axes:
        for z in FIT_DEPTHS:
            base = _point(edge, 0., z, 'fit')
            ref = f"injections/{edge['edge_id']}/z{int(z+6)}.json"
            path = BANK/'bank'/ref
            signed = [0., 0.]
            signed[edge['axis_index']] = edge['direction']*.4
            old, = [r for r in old_seal['records'] if r['role'] == 'fit' and r['contact_ids'] == edge['contact_ids']
                    and r['offsets_pitch_fraction'] == signed and r['position_mm'][2] == z]
            for point, path, sealed, identity in (
                (base, path, bank[ref], bank_identity),
                (_point(edge, .4, z, 'fit'), ORIGINAL/'results'/old['record_ref'], old, old_seal['request_sha256']),
            ):
                item = W.read(path)
                payload = item['payload']
                W.require(W.sha(path) == sealed['record_sha256'] and item['identity_sha256'] == identity
                          and payload['status'] == 'completed' and payload['valid'] and
                          payload['contact_ids'] == point['contact_ids'] and payload['injection_energy_keV'] == ENERGY_KEV
                          and all(math.isclose(x, y, abs_tol=1e-12) for x, y in zip(
                              payload['position_mm'], point['position_mm'], strict=True))
                          and len(payload['channel_signals']) == 34, 'Sealed same-field reference changed')
                references.append({**point, 'position_mm': payload['position_mm'], 'reference': pilot.binding(path),
                                   'record_identity_sha256': identity})
    return references


def prepare():
    old_path = ORIGINAL/'request.json'
    old_seal_path = ORIGINAL/'results/COMPLETE.json'
    study_path = ORIGINAL/'position-study.json'
    bank_seal_path = BANK/'COMPLETE.json'
    bank_identity_path = BANK/'bank/identity.json'
    bank_bundle_path = BANK/'identity.json'
    bank_run_path = BANK/'bank/run.json'
    run_seal_path = RUN/'COMPLETE.json'
    event_path = RUN/'response/events/2950.json'
    old, old_seal, study = (W.read(x) for x in (old_path, old_seal_path, study_path))
    bank_seal, bank_identity, run_seal = (W.read(x) for x in (bank_seal_path, bank_identity_path, run_seal_path))
    W.require(W.sha(old_path) == old_seal['request_sha256'] == study['capture_request_sha256']
              and W.sha(old_seal_path) == study['capture_receipt_sha256']
              and W.sha(bank_seal_path) == old['source_bank_seal']['sha256']
              and W.sha(bank_identity_path) == old['source_bank_identity']['sha256']
              and W.sha(bank_bundle_path) == bank_seal['bundle_identity_sha256']
              and W.sha(bank_run_path) == bank_seal['bank_run_sha256']
              and W.sha(bank_identity_path) == W.read(bank_run_path)['identity_sha256']
              and W.sha(run_seal_path) == old['source_run_seal']['sha256']
              and W.sha(event_path) == run_seal['artifacts']['response/events/2950.json']['sha256'],
              'Original reference or event receipt changed')
    W.require(all(old[k] == bank_identity[k] for k in
                  ('model_sha256', 'field_cache', 'field_precision_bits', 'numerics', 'channels'))
              and old['field_precision_bits'] == 32 and old['injection_energy_keV'] == ENERGY_KEV
              and W.sha(ROOT/old['model_ref']) == old['model_sha256'], 'Same-field reference identity changed')
    event = study['events']['2950']
    axes = _geometry(old, event)
    points = []
    for edge in axes:
        lo, hi = edge['electrode_edges_offset_pitch_fraction']
        points += [_point(edge, u, z, role) for role, offsets, depths in (
            ('fit', (.45, lo, .49, .5, .51, hi, .55), FIT_DEPTHS),
            ('holdout', HOLDOUT_OFFSETS, HOLDOUT_DEPTHS)) for u in offsets for z in depths]
    refs = _reference_records(axes, old_seal, bank_seal, W.sha(bank_identity_path))
    W.require(len(points) == len({tuple(p['position_mm']) for p in points}) == 66 and len(refs) == 12,
              'Edge scan split or existing reference census changed')
    inputs = (old_path, old_seal_path, study_path, bank_seal_path, bank_identity_path, bank_bundle_path,
              bank_run_path, BANK/'validation.jsonl',
              run_seal_path, event_path, Path(__file__).resolve(), ROOT/'simulation/gegi_response.jl',
              ROOT/'simulation/gegi_pixel_calibration.jl', ROOT/'tools/gegi_full34_pilot.py', ROOT/old['model_ref'])
    return {**{k: old[k] for k in KEYS}, 'kind': 'gegi_2950_edge_capture_request_v1', 'event_id': 2950,
            'edges': axes, 'points': points, 'reused_reference_records': refs, 'injection_energy_keV': ENERGY_KEV,
            'input_bindings': [pilot.binding(p) for p in inputs],
            'worker_sha256': hashlib.sha256(WORKER.encode('utf-8')).hexdigest(),
            'memory_policy': 'One worker. Available memory checked against the saved same-field peak before launch.',
            'scope': 'Nominal 500 keV isolated point injections with the other strip coordinate fixed at its centre. '
                     'Keep every capture outcome. The original pixel label is fixed across each gap; '
                     'actual endpoint identity, incomplete collection and multiple-contact endpoints are recorded separately.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=OUT)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    output = args.output.resolve()
    W.require(output.is_relative_to(ROOT/'.local') and output != ROOT/'.local', 'Use a new folder below project .local')
    request = prepare()
    path = output/'request.json'
    if path.exists():
        W.require(W.read(path) == request, 'Existing request differs; keep it and use a new output path')
    else:
        output.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as file:
            file.write(W.encoded(request) + b'\n')
    available = pilot.available_memory()
    historical_peak = W.read(ORIGINAL/'results/runtime.json')['peak_working_set_bytes']
    if args.execute:
        W.require(available > historical_peak, 'Available memory is below the recorded same-field worker peak')
        W.require(W.sha(request['environment']['julia_executable']) == request['environment']['julia_executable_sha256'],
                  'Pinned Julia executable changed')
        result = pilot.launch(path, request, W.sha(path), WORKER, STATUS)
    else:
        result = {'status': 'prepared', 'request_sha256': W.sha(path), 'new_points': len(request['points']),
                  'available_memory_bytes': available, 'same_field_historical_peak_bytes': historical_peak}
    print(json.dumps(result, indent=2), flush=True)
    return result.get('returncode', 0)


if __name__ == '__main__':
    raise SystemExit(main())
