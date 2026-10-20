"""Prepare the original 2991-record full34 bank; execute only with its exact SHA.

Reuse the 15 completed physical pilot points in 18 checkpoint paths. The original
bank stays read-only. K.build owns the grid, checkpointing and timing mathematics.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

import gegi_full34_pilot as P
from gegi_full34_pilot import W, ROOT

REQUEST = P.CALIBRATION+'/full34-bank/request.json'
KIND = 'gegi_original_grid_full34_bank_request_v1'
PILOT_COMPLETE_SHA = '5c3593179a572b16b8adc17926b46363ddfea58cbb54ecca471965102c410e07'
LIMITS = {'maximum_grid_records': 2991, 'maximum_new_checkpoint_attempts': 2973,
          'maximum_new_drift_calls': 2709, 'maximum_total_wall_seconds': 300,
          'julia_threads': 1, 'worker_processes': 1, 'automatic_retry': False}

# Reuse the executed pilot's imports, endpoint arithmetic and parity functions.
JULIA_WORKER = P.JULIA_WORKER.split('function main(reqpath,out)', 1)[0] + r'''
function main(reqpath,out)
    req=G.E.readjson(reqpath);requestsha=G.hashfile(reqpath)
    deadline=parse(Float64,ENV["GEGI_FULL34_DEADLINE_UNIX"]);stop()=time()>=deadline
    check(Threads.nthreads()==1 && length(req["grid"])==2991 && length(req["imports"])==18,"Fixed grid/import limits changed")
    check(G.E.environment()==req["environment"]["native"],"Original native environment changed")
    pkgroot=dirname(dirname(pathof(SSD)))
    for (ref,digest) in req["environment"]["SSD_science_source_sha256"]
        check(G.hashfile(joinpath(pkgroot,"src",ref))==digest,"Installed SSD science source changed")
    end
    cfg=(; (Symbol(k)=>v for (k,v) in req["numerics"])...)
    report=Dict{String,Any}();tick=time()
    sim=G.load_fields(Dict("field_cache"=>req["field_cache"]),joinpath(G.ROOT,req["model_ref"]),out,cfg,report)
    check(report["fields"]["mode"]=="explicit_exact_model_cache" && report["fields"]["solve_seconds"]==0,"No new field solve permitted")
    check(8sizeof(SSD.get_precision_type(sim))==req["field_precision_bits"] &&
        sim.detector.semiconductor.charge_trapping_model isa SSD.NoChargeTrappingModel &&
        G.H.channel_metadata(sim.config_dict)==req["channels"],"Original field/contact state changed")
    fresh(joinpath(out,"startup.json"),Dict("field_load_seconds"=>time()-tick,"fields"=>report["fields"],
        "startup_seconds_including_worker_imports"=>time()-parse(Float64,ENV["GEGI_FULL34_STARTED_UNIX"]),
        "process_peak_rss_bytes"=>Sys.maxrss()))
    # Establish the exact existing K identity without a single new injection.
    bank=joinpath(out,"bank")
    first=K.build(sim,cfg,req["channels"],bank;field_cache=req["field_cache"],stop_requested=()->true)
    check(first.status=="stopped","Identity bootstrap must stop before injection")
    bank_identity=G.E.readjson(joinpath(bank,"identity.json"));banksha=G.hashfile(joinpath(bank,"identity.json"))
    old_identity=G.E.readjson(joinpath(G.ROOT,req["original_identity"]["ref"]))
    for key in ("model_sha256","field_cache","environment","channels","numerics","field_precision_bits",
                "depth_mm","pixel_order","injection_energy_keV","timing_method","diagnostic_pixels",
                "diagnostic_depth_mm","diagnostic_offsets_pitch_fraction","random_seed","randomness")
        check(bank_identity[key]==old_identity[key],"Original grid/input identity changed: "*key)
    end
    imported=Any[]
    for item in req["imports"]
        row=K.read_record(joinpath(G.ROOT,item["source_record"]["ref"]),req["pilot_request"]["sha256"])
        check(K.digest(row)==item["source_payload_sha256"] && row["signal_coverage"]==K.signal_coverage() &&
            row["position_mm"]==item["position_mm"] && row["contact_ids"]==item["contact_ids"],"Pilot import changed")
        row["response_origin"]=Dict("mode"=>"imported_saved_full34_response","source_record"=>item["source_record"],
            "source_payload_sha256"=>item["source_payload_sha256"],"source_identity_sha256"=>req["pilot_request"]["sha256"],
            "pilot_complete"=>req["pilot_complete"],"response_fields_unmodified"=>true,
            "cost_scope"=>"Preserved execution_seconds belongs to the original pilot injection; no new drift for this checkpoint.")
        path=joinpath(bank,item["target_ref"]);check(!ispath(path),"Preserve existing import")
        K.save_record(path,row,banksha)
        push!(imported,Dict("target_ref"=>item["target_ref"],"checkpoint_sha256"=>G.hashfile(path),"source_record"=>item["source_record"]))
    end
    fresh(joinpath(out,"imports.json"),imported)
    fresh(joinpath(out,"identity.json"),Dict("kind"=>"gegi_full34_bank_bundle_identity_v1",
        "request_sha256"=>requestsha,"original_identity"=>req["original_identity"],"original_inventory"=>req["inventory"],
        "pilot_complete"=>req["pilot_complete"],"calibration_identity_sha256"=>banksha,
        "imports_sha256"=>G.hashfile(joinpath(out,"imports.json")),"limits"=>req["limits"],
        "scope"=>"Outer provenance binds original bank and exact completed pilot to the unchanged K calibration identity. Imported records carry their source; no original record was relabeled or overwritten."))
    # Exact original exclusions prove these 264 paths cannot spend a drift call.
    T=SSD.get_precision_type(sim)
    for item in req["grid"]
        if item["original_status"]=="excluded_geometry"
            p=SSD.CartesianPoint{T}((T.(item["position_mm"])./T(1000))...)
            check(!(p in sim.detector.semiconductor) || any(c->p in c.geometry,sim.detector.contacts),"Original geometry exclusion changed")
        end
    end
    built=K.build(sim,cfg,req["channels"],bank;field_cache=req["field_cache"],
        stop_requested=stop,max_new_injections=2973)
    fresh(joinpath(out,"build.json"),Dict("status"=>built.status,"bank_run_sha256"=>G.hashfile(joinpath(bank,"run.json"))))
    if built.status!="completed"
        fresh(joinpath(out,"PARTIAL.json"),Dict("status"=>"checkpointed_budget_stop","phase"=>"K.build","automatic_retry"=>false))
        return false
    end
    mismatch=0;validated=0;full34=0;excluded=0;newdrift=0;maxidentity=0.;maxcontact=0.;unknowncontact=0;knowncontact=0
    importrefs=Set(item["target_ref"] for item in req["imports"])
    validation=joinpath(out,"validation.jsonl")
    finished=open(validation,"w") do io
        for item in req["grid"]
            if stop();return false;end
            row=K.read_record(joinpath(bank,item["target_ref"]),banksha)
            old=K.read_record(joinpath(G.ROOT,item["original_record"]["ref"]),req["original_identity"]["sha256"])
            nulls=("signals","ctd_ns","X_t50_ns","Y_t50_ns","X_final_induced_keV","Y_final_induced_keV","endpoints")
            comparison=old["signals"]===nothing && row["signals"]===nothing ?
                Dict("status"=>"compared_geometry_exclusion","all_exact"=>row["status"]==old["status"] &&
                    row["valid"]==old["valid"] && all(row[k]===old[k] for k in nulls) &&
                    row["channel_signals"]===nothing && row["signal_coverage"]===nothing) : compare_selected(row,old)
            identity=endpoint_identity(sim,row)
            mismatch+=!comparison["all_exact"];validated+=1
            full34+=row["channel_signals"]!==nothing;excluded+=row["status"]=="excluded_geometry"
            newdrift+=!(item["target_ref"] in importrefs) && row["status"]!="excluded_geometry"
            if identity!==nothing
                maxidentity=max(maxidentity,identity["max_absolute_terminal_identity_error_keV"])
                v=identity["max_absolute_terminal_ideal_contact_error_keV"]
                if v===nothing;unknowncontact+=1;else;knowncontact+=1;maxcontact=max(maxcontact,v);end
            end
            JSON.print(io,Dict("record_ref"=>item["target_ref"],"record_sha256"=>G.hashfile(joinpath(bank,item["target_ref"])),
                "original_record"=>item["original_record"],"status"=>row["status"],"valid"=>row["valid"],
                "selected_pair_comparison"=>comparison,"endpoint_identity"=>identity));println(io)
        end
        true
    end
    summary=Dict("validated_records"=>validated,"selected_pair_mismatches"=>mismatch,"full34_records"=>full34,
        "excluded_records"=>excluded,"new_drift_calls"=>newdrift,"imported_physical_pilot_points"=>15,
        "imported_checkpoint_paths"=>18,"max_absolute_terminal_identity_error_keV"=>maxidentity,
        "max_absolute_terminal_ideal_contact_error_keV"=>knowncontact>0 ? maxcontact : nothing,"unknown_ideal_contact_records"=>unknowncontact,
        "validation_sha256"=>G.hashfile(validation),"bank_run_sha256"=>G.hashfile(joinpath(bank,"run.json")),
        "request_sha256"=>requestsha,"bundle_identity_sha256"=>G.hashfile(joinpath(out,"identity.json")),
        "new_field_solves"=>0,"new_transport_calls"=>0,"automatic_retry"=>false,
        "scope"=>"Original fixed-grid forward responses and selected-signal parity only. Native/ideal-contact residuals remain diagnostics, not physical accuracy or imaging validation. No waveform correction.")
    summary["status"]=finished ? (mismatch==0 ? "completed_original_grid_full34_bank" : "completed_with_selected_pair_mismatches") : "checkpointed_budget_stop"
    fresh(joinpath(out,finished ? "COMPLETE.json" : "PARTIAL.json"),summary)
    finished && mismatch==0
end
check(length(ARGS)==2,"Pass request and new result directory")
try
    main(ARGS[1],ARGS[2]) || exit(2)
catch err
    fresh(joinpath(ARGS[2],"failure.json"),Dict("status"=>"failed_stop_preserve_partial","error"=>sprint(showerror,err),"automatic_retry"=>false))
    rethrow()
end
'''


def original_grid(identity, inventory):
    """Match K's fixed order/coordinates to the already hash-bound inventory."""
    manifest = W.safe_path(ROOT, inventory['input_manifest']['ref'])
    W.require(W.sha(manifest) == inventory['input_manifest']['sha256'], 'Original inventory manifest changed.')
    prefix = P.BANK+'/'
    original = {v['ref'][len(prefix):]: v for line in manifest.read_text(encoding='utf-8').splitlines()
                if (v := json.loads(line))['ref'].startswith(prefix) and
                v['ref'][len(prefix):].startswith(('injections/', 'diagnostic-injections/'))}
    grid = [];channels = identity['channels']
    def add(ref, x, y, xyz):
        entry = original.pop(ref)
        W.require(entry['position_mm'] == xyz and entry['contact_ids'] == [x, y], 'Original grid coordinates changed: '+ref)
        W.require(W.sha(W.safe_path(ROOT, entry['ref'])) == entry['sha256'], 'Original grid record changed: '+ref)
        grid.append({'target_ref': ref, 'position_mm': xyz, 'contact_ids': [x, y],
                     'original_status': entry['status'], 'original_record': {'ref': entry['ref'], 'sha256': entry['sha256']}})
    for x, y in identity['pixel_order']:
        for i, z in enumerate(identity['depth_mm'], 1):
            add(f'injections/{x}-{y}/z{i}.json', x, y, [channels[x-1]['strip_center_mm'], channels[y-1]['strip_center_mm'], z])
    dx = channels[9]['strip_center_mm']-channels[8]['strip_center_mm']
    dy = channels[26]['strip_center_mm']-channels[25]['strip_center_mm']
    for x, y in identity['diagnostic_pixels']:
        for label, ox, oy in identity['diagnostic_offsets_pitch_fraction']:
            for i, z in enumerate(identity['diagnostic_depth_mm'], 1):
                add(f'diagnostic-injections/{x}-{y}/{label}-z{i}.json', x, y,
                    [channels[x-1]['strip_center_mm']+ox*dx, channels[y-1]['strip_center_mm']+oy*dy, z])
    W.require(not original and len(grid) == 2991 and Counter(g['original_status'] for g in grid) == inventory['counts']['statuses'],
              'Original fixed grid/status census changed.')
    return grid


def prepare():
    oldpath = ROOT/P.BANK/'identity.json';old = W.read(oldpath)
    invpath = ROOT/P.CALIBRATION/'inventory.json';inventory = W.read(invpath)
    W.require(inventory['identity_sha256'] == W.sha(oldpath), 'Original bank identity changed.')
    pilotpath = ROOT/P.REQUEST;pilot = W.read(pilotpath);donepath = pilotpath.parent/'results/COMPLETE.json';done = W.read(donepath)
    W.require(W.sha(donepath) == PILOT_COMPLETE_SHA and done['request_sha256'] == W.sha(pilotpath) and
              done['status'] == 'completed_fixed15_full34_forward_pilot', 'Completed pilot changed.')
    for key in ('field_cache', 'numerics', 'channels', 'field_precision_bits'):
        W.require(pilot[key] == old[key], 'Pilot/original bank inputs differ: '+key)
    grid = original_grid(old, inventory);imports = []
    for point in done['points']:
        source = donepath.parent/point['record_ref'];record = W.read(source);row = record['payload']
        # Exact file SHA binds Julia's numeric serialization. K.read_record checks
        # its native canonical payload SHA during import; Python re-encoding tiny
        # floating values is not the same byte representation.
        W.require(W.sha(source) == point['record_sha256'] and record['identity_sha256'] == W.sha(pilotpath) and
                  point['selected_pair_comparison']['all_exact'] and
                  row['status'] == 'completed' and [s['contact_id'] for s in row['channel_signals']] == list(range(1, 35)), 'Pilot response changed.')
        for item in grid:
            if item['contact_ids'] == row['contact_ids'] and item['position_mm'] == row['position_mm']:
                baseline = W.read(ROOT/item['original_record']['ref'])['payload']
                keys = ('signals', 'endpoints', 'ctd_ns', 'X_t50_ns', 'Y_t50_ns')
                W.require(W.encoded({k: baseline[k] for k in keys}) == W.encoded({k: row[k] for k in keys}),
                          'Pilot duplicate-coordinate baseline changed.')
                imports.append({'target_ref': item['target_ref'], 'position_mm': row['position_mm'], 'contact_ids': row['contact_ids'],
                    'source_record': P.binding(source), 'source_payload_sha256': record['payload_sha256']})
    W.require(len(imports) == 18 and len({i['source_record']['ref'] for i in imports}) == 15 and
              len({i['target_ref'] for i in imports}) == 18, 'Expected 15 physical responses in 18 checkpoint paths.')
    sources = {ref: W.sha(ROOT/ref) for ref in pilot['input_file_sha256'] if ref.startswith('simulation/')}
    W.require(all(sources[ref] == pilot['input_file_sha256'][ref] for ref in sources), 'Pilot/native source changed.')
    for ref in ('tools/gegi_full34_pilot.py', 'tools/gegi_full34_bank.py'):
        sources[ref] = W.sha(ROOT/ref)
    request = {key: pilot[key] for key in ('model_ref', 'model_sha256', 'field_cache', 'field_precision_bits', 'numerics', 'channels', 'environment')}
    request.update(kind=KIND, status='prepared_not_executed', limits=LIMITS,
        memory_policy='measure_only_not_a_launch_or_stop_condition', injection_energy_keV=500.,
        authorization='Owner bounded repair autonomy; supervisor launches this exact request separately.',
        original_identity=P.binding(oldpath), inventory=P.binding(invpath), original_manifest=inventory['input_manifest'],
        pilot_request=P.binding(pilotpath), pilot_complete=P.binding(donepath), grid=grid, imports=imports,
        input_file_sha256=sources, worker_sha256=hashlib.sha256(JULIA_WORKER.encode('utf-8')).hexdigest(),
        accounting={'original_records': 2991, 'original_full_signal_pairs': 2727, 'original_geometry_exclusions': 264,
                    'reused_physical_pilot_points': 15, 'reused_checkpoint_paths': 18, 'maximum_new_checkpoint_attempts': 2973,
                    'maximum_new_drift_calls': 2709, 'original_incomplete_collection_or_timing': 176},
        measured_basis={'pilot_complete': P.binding(donepath), 'approximate_new_data_bytes': 300_000_000,
            'warm_capture_seconds_per_point_observed_approximate': .006,
            'qualification': 'Scale estimate only; IO, different positions, compilation and post-run endpoint diagnostics are not guaranteed. 300 seconds is a cap, not a prediction.'},
        scope='Original independent grid only. Imported pilot response fields stay unchanged and carry explicit source provenance. Failed/excluded quantities stay null; no field/transport calls or waveform corrections.')
    path = W.safe_path(ROOT, REQUEST);path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():W.require(W.read(path) == request, 'Existing bank request changed; preserve it.')
    else:
        with path.open('xb') as stream:stream.write(W.encoded(request)+b'\n')
    return {'status': 'prepared_not_executed', 'request': str(path), 'request_sha256': W.sha(path), 'accounting': request['accounting']}


def execute(digest):
    path = W.safe_path(ROOT, REQUEST);req = W.read(path)
    W.require(W.sha(path) == digest and req['kind'] == KIND and req['limits'] == LIMITS and
              req['memory_policy'] == 'measure_only_not_a_launch_or_stop_condition' and
              req['worker_sha256'] == hashlib.sha256(JULIA_WORKER.encode('utf-8')).hexdigest(), 'Fixed bank request/source/budget changed.')
    for ref, expected in req['input_file_sha256'].items():W.require(W.sha(ROOT/ref) == expected, 'Pinned bank source changed: '+ref)
    for key in ('original_identity', 'inventory', 'original_manifest', 'pilot_request', 'pilot_complete'):
        value = req[key];W.require(W.sha(W.safe_path(ROOT, value['ref'])) == value['sha256'], 'Pinned bank input changed: '+key)
    W.require(req['grid'] == original_grid(W.read(ROOT/req['original_identity']['ref']), W.read(ROOT/req['inventory']['ref'])), 'Fixed bank grid changed.')
    for item in req['imports']:
        value = item['source_record'];W.require(W.sha(ROOT/value['ref']) == value['sha256'], 'Imported pilot source changed.')
    W.require(W.sha(req['environment']['julia_executable']) == req['environment']['julia_executable_sha256'], 'Pinned Julia changed.')
    return P.launch(path, req, digest, JULIA_WORKER, 'completed_original_grid_full34_bank')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__);parser.add_argument('--execute', action='store_true')
    parser.add_argument('--request-sha256');args = parser.parse_args()
    result = execute(args.request_sha256) if args.execute else prepare()
    print(json.dumps(result, indent=2));raise SystemExit(0 if result.get('returncode', 0) == 0 else 1)
