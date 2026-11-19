"""Capture the two Cs full-energy pixels' missing lateral waveforms."""

import argparse
from collections import Counter
from itertools import product
import json
from pathlib import Path

import gegi_capture_position_target as prior
from gegi_event_store import sha
from gegi_joint_two_site import DEPTH_MM, LATERAL_DEPTH_MM, LATERAL_FRACTION
import gegi_pixel_cfd_depth_study as depth


ROOT = prior.ROOT
OUT = ROOT / '.local/gegi-joint-two-site/cs-full-energy-lateral'
GEOMETRY = ROOT / '.local/gegi-continuous-pairing/geometry-reference.json'
GEOMETRY_SHA = 'e45a116a278c5c89c9df7ba1e9d3c9c49aae8d620cea7b00acbf0dd8263672c0'
TARGETS = ((13, 27), (14, 26))
HOLDOUT_X = (-.23, .23)
HOLDOUT_Y = (-.27, .27)
HOLDOUT_Z = (-2.5, 2.5)
ATTEMPTS = 64
STATUS = 'completed_cs_full_energy_joint_lateral_capture'
W, pilot, scan = prior.W, prior.pilot, prior.scan


def worker_source():
    """Reuse the same one-thread, exact-cache worker as the fixed hotspot capture."""
    marker = 'length(req["points"])==16,"Fixed 16-point budget"'
    if prior.WORKER.count(marker) != 1 or prior.WORKER.count(prior.STATUS) != 1:
        raise ValueError('Shared pinned native worker definition changed')
    return prior.WORKER.replace(marker, f'length(req["points"])=={ATTEMPTS},"Fixed {ATTEMPTS}-point budget"').replace(
        prior.STATUS, STATUS)


def plan_points(channels):
    geometry = {row['id']: row for row in channels}
    pitch = channels[1]['strip_center_mm'] - channels[0]['strip_center_mm']
    fit = [(x, y, z) for x, y, z in product(LATERAL_FRACTION, LATERAL_FRACTION, LATERAL_DEPTH_MM) if (x, y) != (0, 0)]
    holdout = list(product(HOLDOUT_X, HOLDOUT_Y, HOLDOUT_Z))
    points = []
    for pair in TARGETS:
        cx, cy = (geometry[cid]['strip_center_mm'] for cid in pair)
        for role, rows in (('fit', fit), ('holdout', holdout)):
            for x, y, z in rows:
                points.append(dict(contact_ids=list(pair), role=role, offsets_pitch_fraction=[x, y],
                                   position_mm=[cx + x*pitch, cy + y*pitch, z]))
    if len(points) != ATTEMPTS or len({tuple(row['position_mm']) for row in points}) != ATTEMPTS:
        raise ValueError('Expected 48 fixed training points and 16 distinct held-out points')
    return points


def prepare(worker):
    inputs = scan.Inputs()
    truth = inputs.read(GEOMETRY, GEOMETRY_SHA)
    complete = inputs.read(scan.FULL/'COMPLETE.json', scan.FULL_COMPLETE_SHA)
    original = inputs.read(scan.FULL/'bound-request.json', complete['request_sha256'])
    relevant = [row for row in truth['geometry_references']
                if row['original_identity']['source'] == 'cs137-left' and row['containment'] == 'full_energy_at_photon_birth']
    group, = relevant
    if (group['original_identity']['raw_event_id'] != 7916
            or {tuple(site['cell']) for site in group['sites_in_child_birth_order']} != set(TARGETS)
            or any(site['joint_training']['lateral'] for site in group['sites_in_child_birth_order'])):
        raise ValueError('Unexpected Cs reference group or pre-existing lateral template')
    keys = ('model_ref', 'model_sha256', 'field_cache', 'field_precision_bits', 'numerics', 'environment', 'channels')
    identity = {key: original[key] for key in keys}
    if (identity['field_precision_bits'] != 32
            or truth['calibration_field']['field_cache_sha256'] != identity['field_cache']['sha256']
            or truth['calibration_field']['model_sha256'] != identity['model_sha256']
            or W.sha(ROOT / identity['model_ref']) != identity['model_sha256']
            or W.sha(identity['environment']['julia_executable']) != identity['environment']['julia_executable_sha256']):
        raise ValueError('The exact original cached Float32 model and Julia runtime are required')
    centers = [row for row in original['grid'] if row['target_ref'].startswith('injections/')
               and tuple(row['contact_ids']) in TARGETS]
    if len(centers) != 2 * len(DEPTH_MM):
        raise ValueError('Both existing center grids are required')
    seals = depth.bank_manifest(inputs, complete, {row['target_ref'] for row in centers})
    reused = []
    for point in centers:
        ref = point['target_ref']
        stamp = seals[ref]
        path = scan.FULL / 'bank' / ref
        if stamp['status'] != 'completed' or stamp['valid'] is not True or W.sha(path) != stamp['record_sha256']:
            raise ValueError('Previously sealed center waveform is unavailable')
        reused.append(dict(ref=path.relative_to(ROOT).as_posix(), sha256=stamp['record_sha256'],
                           contact_ids=point['contact_ids'], position_mm=point['position_mm']))
    names = (Path(__file__).name, 'gegi_capture_position_target.py', 'gegi_full34_pilot.py', 'gegi_joint_two_site.py')
    sources = {f'tools/{name}': W.sha(ROOT/'tools'/name) for name in names}
    sources.update({name: W.sha(ROOT/name) for name in ('simulation/gegi_response.jl', 'simulation/gegi_pixel_calibration.jl')})
    return dict(identity, kind='gegi_cs_full_energy_joint_lateral_request_v1', points=plan_points(identity['channels']),
                injection_energy_keV=depth.ENERGY_KEV, drift_time_step_ns=identity['numerics']['dt'],
                drift_step_limit=identity['numerics']['max_steps'], diffusion=False, self_repulsion=False,
                native_random_seed=None, worker_sha256=sha(worker.encode()),
                memory_policy='One worker, with free memory checked against the same-field capture peak.',
                reference_group=group['original_identity'], reused_center_records=reused, input_sha256=inputs.hashes,
                source_sha256=sources, scope='Targeted post-hoc calibration at two measured Cs cells. '
                'Training and held-out offsets are fixed and coordinate-distinct.')


def verify(request, request_hash, runtime):
    folder = OUT/'results'
    seal = W.read(folder/'COMPLETE.json')
    if (seal['status'] != STATUS or seal['request_sha256'] != request_hash or seal['native_injection_attempts'] != ATTEMPTS
            or seal['new_field_solves'] != 0 or seal['new_transport_calls'] != 0
            or len(seal['records']) != ATTEMPTS or any(W.sha(ROOT/ref) != stamp for ref, stamp in request['source_sha256'].items())):
        raise ValueError('Native capture completion or source identity differs')
    counts = Counter()
    inputs = scan.Inputs()
    for point, record in zip(request['points'], seal['records'], strict=True):
        if {key: record[key] for key in point} != point:
            raise ValueError('Saved injection differs from the fixed capture request')
        raw = inputs.read(folder/record['record_ref'], record['record_sha256'])
        if record['valid']:
            scan.qualify(raw, point, record, request_hash, request['injection_energy_keV'])
        counts[record['role'], record['status']] += 1
    verification = dict(kind='gegi_cs_full_energy_joint_lateral_verification_v1',
                        completion_sha256=W.sha(folder/'COMPLETE.json'), request_sha256=request_hash,
                        runtime_sha256=W.sha(folder/'runtime.json'), native_drift_calls=ATTEMPTS,
                        new_field_solves=0, new_transport_calls=0, reused_center_records=len(request['reused_center_records']),
                        native_status_counts={f'{role}:{status}': count for (role, status), count in counts.items()},
                        elapsed_seconds=runtime['elapsed_seconds'], peak_working_set_bytes=runtime['peak_working_set_bytes'],
                        available_physical_before_bytes=runtime['available_physical_before_bytes'])
    with (folder/'verification.json').open('xb') as out:
        out.write(W.encoded(verification) + b'\n')
    return verification


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', help='Launch one bounded local SSD worker')
    args = parser.parse_args()
    worker = worker_source()
    request = prepare(worker)
    if not args.execute:
        print(json.dumps(dict(points=len(request['points']), reused_centers=len(request['reused_center_records']),
                              per_role=Counter(point['role'] for point in request['points']))))
        return 0
    peak = W.read(depth.CAPTURES[0][1]/'runtime.json')['peak_working_set_bytes']
    available = pilot.available_memory()
    if available <= peak:
        raise RuntimeError('Available RAM is below the recorded same-field worker peak')
    OUT.mkdir(parents=True)
    path = OUT/'request.json'
    with path.open('xb') as out:
        out.write(W.encoded(request) + b'\n')
    request_hash = W.sha(path)
    runtime = pilot.launch(path, request, request_hash, worker, STATUS)
    if runtime['returncode']:
        print(json.dumps(runtime))
        return runtime['returncode']
    print(json.dumps(verify(request, request_hash, runtime), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
