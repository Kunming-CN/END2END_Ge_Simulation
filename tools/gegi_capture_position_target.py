"""Validate the frozen interior transfer at the measured X15/Y07 hotspot."""

import argparse
from collections import Counter
import json
from itertools import product
from pathlib import Path

import gegi_continuous_position_study as continuous
from gegi_event_store import sha
import gegi_full34_pilot as pilot
import gegi_position_transfer_study as transfer
import gegi_pulse_scan as scan
import gegi_substrip as substrip


ROOT = pilot.ROOT
OUT = ROOT / '.local/gegi-position-extension/x15-y07'
SAVED = OUT.parent / 'saved-study.json'
SAVED_SHA256 = '28124066709cb9d907ccc5d195afa5619b64ebf44d435fbd674e62e328179e1e'
TARGET = [15, 24]
DEPTHS_MM = (-4.2, -1.15, 1.85, 3.65)
STATUS = 'completed_fixed_x15_y07_holdout'
W = pilot.W
WORKER = pilot.JULIA_WORKER.split('bits_equal', 1)[0] + r'''
function main(reqpath,out)
    req=G.E.readjson(reqpath);digest=G.hashfile(reqpath)
    check(Threads.nthreads()==1 && length(req["points"])==16,"Fixed 16-point budget")
    check(G.E.environment()==req["environment"]["native"],"Pinned native environment changed")
    check(string(pkgversion(SSD))=="0.11.8","Pinned SSD version changed")
    pkgroot=dirname(dirname(pathof(SSD)))
    for (ref,sha) in req["environment"]["SSD_science_source_sha256"]
        check(G.hashfile(joinpath(pkgroot,"src",ref))==sha,"Pinned SSD science source changed")
    end
    cfg=(; (Symbol(k)=>v for (k,v) in req["numerics"])...)
    field=Dict{String,Any}()
    sim=G.load_fields(Dict("field_cache"=>req["field_cache"]),
        joinpath(G.ROOT,req["model_ref"]),out,cfg,field)
    check(field["fields"]["mode"]=="explicit_exact_model_cache" &&
        field["fields"]["solve_seconds"]==0 && field["fields"]["precision_bits"]==32 &&
        G.H.channel_metadata(sim.config_dict)==req["channels"] &&
        sim.detector.semiconductor.charge_trapping_model isa SSD.NoChargeTrappingModel,
        "Same cached field and channel metadata required")
    G.save(joinpath(out,"startup.json"),merge(field,Dict("peak_rss_bytes"=>Sys.maxrss())))
    records=Any[]
    for (i,p) in enumerate(req["points"])
        check(time()<parse(Float64,ENV["GEGI_FULL34_DEADLINE_UNIX"]),"Reached bounded deadline")
        ref="injections/point-"*lpad(string(i),2,'0')*".json"
        row,reused=K.checkpoint_injection(sim,cfg,p["contact_ids"]...,p["position_mm"],
            req["injection_energy_keV"],joinpath(out,ref),digest)
        check(!reused,"Preserve existing checkpoint")
        push!(records,merge(p,Dict("record_ref"=>ref,"record_sha256"=>G.hashfile(joinpath(out,ref)),
            "status"=>row["status"],"valid"=>row["valid"],"execution_seconds"=>row["execution_seconds"])))
    end
    G.save(joinpath(out,"COMPLETE.json"),Dict("status"=>"completed_fixed_x15_y07_holdout",
        "request_sha256"=>digest,"records"=>records,"new_field_solves"=>0,
        "new_transport_calls"=>0,"native_injection_attempts"=>length(records)))
end
main(ARGS...)
'''


def positions(channels):
    geometry = {c['id']: c for c in channels}
    centers = [geometry[c]['strip_center_mm'] for c in TARGET]
    pitches = [(geometry[c + 1]['strip_center_mm'] - geometry[c - 1]['strip_center_mm']) / 2 for c in TARGET]
    return [{'contact_ids': TARGET, 'role': 'holdout', 'offsets_pitch_fraction': [x, y],
             'position_mm': [centers[0] + pitches[0] * x, centers[1] + pitches[1] * y, z]}
            for x, y, z in product((-.27, .27), (-.31, .31), DEPTHS_MM)]


def request():
    inputs = scan.Inputs()
    saved = inputs.read(SAVED, SAVED_SHA256)
    complete = inputs.read(scan.FULL / 'COMPLETE.json', scan.FULL_COMPLETE_SHA)
    original = inputs.read(scan.FULL / 'bound-request.json', complete['request_sha256'])
    key = {k: original[k] for k in ('model_ref', 'model_sha256', 'field_cache', 'field_precision_bits',
                                    'numerics', 'environment', 'channels')}
    if (any(saved['provenance'][k] != v for k, v in transfer.identity_of(original).items())
            or W.sha(ROOT / key['model_ref']) != key['model_sha256']
            or W.sha(key['environment']['julia_executable']) != key['environment']['julia_executable_sha256']):
        raise ValueError('Original model, field or installed Julia identity changed')
    points = positions(key['channels'])
    source_paths = (Path(__file__), ROOT/'simulation/gegi_response.jl', ROOT/'simulation/gegi_pixel_calibration.jl')
    return key | {'kind': 'gegi_fixed16_position_transfer_holdout_v1', 'points': points,
                  'injection_energy_keV': transfer.ENERGY_KEV, 'diffusion': False, 'self_repulsion': False,
                  'native_random_seed': None, 'drift_time_step_ns': key['numerics']['dt'],
                  'drift_step_limit': key['numerics']['max_steps'], 'worker_sha256': sha(WORKER.encode()),
                  'memory_policy': 'One worker and no retries. Require available RAM above the saved same-field peak.',
                  'transfer_study_input_sha256': inputs.hashes,
                  'source_sha256': {p.relative_to(ROOT).as_posix(): W.sha(p) for p in source_paths}}


def score(capture_dir):
    inputs = scan.Inputs()
    saved = inputs.read(SAVED, SAVED_SHA256)
    complete_path = capture_dir/'results/COMPLETE.json'
    seal = inputs.read(complete_path, W.sha(complete_path))
    bound = inputs.read(capture_dir/'results/bound-request.json', seal['request_sha256'])
    if seal['status'] != STATUS or seal['native_injection_attempts'] != 16:
        raise ValueError('X15/Y07 capture must retain all sixteen original attempts')
    if ([{k: row[k] for k in p} for p, row in zip(bound['points'], seal['records'], strict=True)]
            != bound['points']):
        raise ValueError('X15/Y07 protected holdout coordinates changed')
    channels = bound['channels']
    calibration = substrip.load_calibration()
    identity = transfer.identity_of(bound)
    if (any(saved['provenance'][k] != v or calibration[k] != v for k, v in identity.items())
            or calibration['calibration_sha256'] != saved['provenance']['calibration_sha256']):
        raise ValueError('Frozen fitting or field identity differs')
    cases = []
    records = seal['records']
    native = {}
    for i, row in enumerate(records):
        inputs.read(capture_dir/'results'/row['record_ref'], row['record_sha256'])
        if row['valid']:
            native[i] = transfer.load_record(inputs, capture_dir/'results', row, row, seal['request_sha256'],
                                             channels, 'x15_y07_holdout')
    for offset, seed in product(continuous.ONSET_OFFSETS_NS, (None, continuous.NOMINAL_SEED)):
        onsets = [continuous.FIRST_ONSET_NS + i*continuous.SPACING_NS + offset for i in native]
        result = continuous.replay([(point['native'], onset, 1.)
                                   for point, onset in zip(native.values(), onsets, strict=True)], seed) if native else None
        events = result['events'] if result is not None else []
        windows, extra = continuous.match_windows(onsets, events)
        measurements = {}
        for (i, point), indices in zip(native.items(), windows, strict=True):
            measurement = continuous.evaluate_point(point, indices, events, calibration, channels, identity)
            measurements[i] = transfer.predict(saved['template'], point, measurement) | {'adc': measurement}
        rows = [{'truth_xyz_mm': row['position_mm'], 'truth_contact_ids': row['contact_ids'],
                 'native_record': row['record_ref'], 'native_status': row['status']} |
                measurements.get(i, {'status': 'native_unavailable'}) for i, row in enumerate(records)]
        cases.append({'offset_ns': offset, 'noise_seed': seed, 'trigger_count': len(events),
                      'adc_sha256': result['adc_sha256'] if result else None, 'extra_trigger_indices': extra,
                      'summary': transfer.summarize(rows), 'rows': rows})
    return {'kind': 'gegi_x15_y07_frozen_transfer_holdout_v1', 'nominal_pair': TARGET,
            'new_native_injection_attempts': seal['native_injection_attempts'],
            'native_status_counts': Counter(row['status'] for row in records),
            'new_field_solves': seal['new_field_solves'], 'new_transport_calls': seal['new_transport_calls'],
            'template_report_sha256': SAVED_SHA256, 'calibration_sha256': calibration['calibration_sha256'],
            'input_sha256': inputs.hashes, 'field_identity': identity, 'cases': cases}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', help='Capture one bounded task before scoring')
    parser.add_argument('--score', action='store_true', help='Score completed capture only')
    args = parser.parse_args()
    if args.execute == args.score:
        parser.error('Choose exactly one of --execute and --score')
    report = OUT/'study.json'
    if report.exists():
        raise FileExistsError(report)
    if args.execute:
        prepared = request()
        available = pilot.available_memory()
        peak = W.read(transfer.CAPTURE/'runtime.json')['peak_working_set_bytes']
        if available <= peak:
            raise RuntimeError('Available RAM is below the recorded same-field worker peak')
        OUT.mkdir(parents=True, exist_ok=True)
        path = OUT/'request.json'
        with path.open('xb') as file:
            file.write(W.encoded(prepared) + b'\n')
        result = pilot.launch(path, prepared, W.sha(path), WORKER, STATUS)
        print(json.dumps(result), flush=True)
        if result['returncode']:
            return result['returncode']
    output = score(OUT)
    body = json.dumps(output, allow_nan=False, separators=(',', ':')) + '\n'
    with report.open('x', encoding='utf-8', newline='\n') as file:
        file.write(body)
    print(json.dumps({'native_status_counts': output['native_status_counts'],
                      'cases': [r['summary'] for r in output['cases']]}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
