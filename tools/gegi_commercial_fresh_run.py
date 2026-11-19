"""Produce independent RSS5 GeGI libraries, then acquire and image each sealed pair."""

import argparse
import os
import platform
import shutil
import time
from pathlib import Path

import gegi_campaign as transport
import gegi_commercial_dual_run as readout


ROOT = transport.ROOT
BASE = ROOT / '.local/gegi-dual-source/rss5-fresh-230'
ARCHIVE = BASE / 'transport-ssd'
ACQUISITION = BASE / 'acquisition'
N_PAIRS = 230
PILOT_COUNT = 250
FIRST_CLOCK_SEED = 20261201
FIRST_PARENT_ID = 10_000_000
MASTER_SEEDS = {'cs137-left': 271119101, 'co60-right': 271119102}
PILOT_SEEDS = {'cs137-left': 271119201, 'co60-right': 271119202}
NATIVE_MEMORY_BYTES = 2_559_381_504 + 350 * 2**20
RANGE_MILESTONES = (25, 100, N_PAIRS)


def binding(path):
    return dict(ref=path.relative_to(ROOT).as_posix(), sha256=readout.digest(path))


def native_worker(request, spool, checkpoint):
    import psutil
    from gegi_campaign_response import ResidentWorker

    while (available := psutil.virtual_memory().available) < NATIVE_MEMORY_BYTES:
        checkpoint('waiting_for_native_memory', available_bytes=available, needed_bytes=NATIVE_MEMORY_BYTES)
        time.sleep(60)
    return ResidentWorker(request, spool)


def fresh_plan():
    baseline = transport.read(readout.ARCHIVE / 'plan.json')
    request = transport.read(transport.bound_file(ROOT, baseline['native_request']))
    require = transport.require
    require(request['field_cache']['sha256'] == readout.FIELD_CACHE_SHA
            and request['numerics']['field_policy'] == 'reuse-only', 'Expected the accepted reuse-only 34-channel field')
    request['source_sha256'] = {ref: transport.sha(ROOT/ref) for ref in request['source_sha256']}
    path = BASE / 'native-request.json'
    if path.is_file():
        require(transport.read(path) == request, 'Prepared native source or settings changed; restore pinned inputs')
    else:
        transport.write(path, request, fresh=True)
    plan = transport.draft()
    plan.update(campaign_id='gegi-rss5-fresh-230', total_initial_primaries=N_PAIRS * 20_000,
                campaign_initial_id_base=FIRST_PARENT_ID, electronics=baseline['electronics'],
                native_request=binding(path), calibration=baseline['calibration'])
    plan['groups'] = [group for group in plan['groups'] if group['id'] in MASTER_SEEDS]
    for group in plan['groups']:
        key = group['id']
        require(group['source_position_mm'] == readout.SOURCES[key]['position_mm'], 'Nominal source position changed')
        group.update(primary_count=N_PAIRS * 10_000, master_seed=MASTER_SEEDS[key],
                     partition=transport.B.partition(N_PAIRS * 10_000, MASTER_SEEDS[key]))
    prior = {transport.read(done)['identity']['batch']['radiation_seed']
             for key in MASTER_SEEDS for done in (readout.ARCHIVE / 'chunks' / key).glob('b*/DONE.json')}
    fresh = {chunk['batch']['radiation_seed'] for chunk in transport.chunks(plan)}
    require(not (prior & fresh or set(PILOT_SEEDS.values()) & (fresh | prior)), 'Radiation seed overlaps another source sample')
    transport.validate_plan(plan)
    return plan


def current_calibration(plan, checkpoint):
    folder = BASE/'pixel-calibration'
    receipt_path = folder/'run.json'
    previous = transport.read(receipt_path) if receipt_path.is_file() else {}
    if previous.get('status') != 'completed':
        worker = native_worker(transport.bound_file(ROOT, plan['native_request']), BASE/'calibration-spool', checkpoint)
        checkpoint('calibrating_current_depth')
        try:
            worker.start()
            result = worker.calibrate(folder, resume=receipt_path.is_file())
            transport.require(result['status'] == 'completed','Current-source depth calibration is incomplete')
        finally:
            worker.close()
    receipt = transport.read(receipt_path)
    transport.require(receipt['status'] == 'completed' and receipt['completed_pixels'] == 256
                      and all(readout.digest(folder/name) == digest for name, digest in receipt['artifacts'].items()),
                      'Completed independent depth calibration has incorrect artifacts')
    path = folder/'depth-calibration.json'
    table = transport.read(path)
    baseline = transport.read(transport.bound_file(ROOT, plan['calibration']))
    physical_keys = ('field_cache_sha256', 'model_sha256', 'drift_numerics',
                     'injection_energy_keV', 'depth_mm', 'timing_method')
    transport.require(all(table[key] == baseline[key] for key in physical_keys),
                      'Independent current-source calibration does not use the accepted physical settings')
    return binding(path)


def pilot(plan, checkpoint):
    request = transport.bound_file(ROOT, plan['native_request'])
    runner = transport.Transport(ROOT)
    records = []
    transport.inactive_children(BASE/'pilot')
    for key, seed in PILOT_SEEDS.items():
        folder = BASE / 'pilot' / key
        timing_path = folder / 'timings.json'
        choice = transport.pilot_spec(plan, key, PILOT_COUNT, seed)
        timing = transport.read(timing_path) if timing_path.exists() else {}
        if 'transport_driver_wall_s' not in timing:
            record_path = folder/'active-transport.json'
            if record_path.is_file():
                record = transport.read(record_path)
                if record.get('status') not in ('completed', 'failed'):
                    transport.require(record.get('status') == 'running'
                                      and transport.identity(record['pid']) not in ('unknown', record['process_start_identity']),
                                      'The prior pilot transport child might still be active')
            checkpoint('pilot_transport', source=key)
            wall = time.perf_counter()
            manifest = runner.process(folder, choice['selection'], lambda: None)
            timing['transport_driver_wall_s'] = time.perf_counter() - wall
            transport.write(timing_path, timing)
        else:
            manifest = folder / 'transport/stream/manifest.json'
        transport.require(transport.sha(folder/'transport/geometry.gdml') == readout.GEOMETRY_SHA,
                          'Pilot geometry differs from the accepted GeGI cryostat geometry')
        response = transport.completed_response(folder, choice['store_identity'])
        if response is None:
            worker = native_worker(request, BASE / 'pilot/native-spool', checkpoint)
            checkpoint('pilot_native', source=key)
            try:
                worker.start()
                timing['native_started_ns'] = time.time_ns()
                transport.write(timing_path, timing)
                worker.run_chunk(manifest, folder/'events.sqlite', choice['store_identity'],
                    calibration=plan['calibration'], photopeak_windows=choice['photopeak_windows'],
                    receipt_path=folder/'response.json')
            finally:
                worker.close()
        if 'native_response_and_store_wall_s' not in timing:
            finished_ns = (folder/'response.json').stat().st_mtime_ns
            timing['native_response_and_store_wall_s'] = (finished_ns - timing['native_started_ns']) / 1e9
            transport.write(timing_path, timing)
        records.append(dict(source_group=key, folder=folder.relative_to(ROOT).as_posix(),
                            timings=timing_path.relative_to(ROOT).as_posix()))
    return records


def acquire_pairs(stop, config_sha, checkpoint):
    from gegi_fresh_imaging import update as update_image

    pending = [i for i in range(stop) if not (ACQUISITION/f'b{i:06d}'/'receipt.json').is_file()]
    if pending:
        start = pending[0]
        roster = readout.settings(ARCHIVE, range(start, stop), FIRST_CLOCK_SEED + start, fresh=True)['blocks']
        for name, spec in roster.items():
            folder = ACQUISITION / name
            folder.mkdir(exist_ok=True)
            readout.complete_shard(folder, spec, config_sha, lambda stage: checkpoint(stage, block=name))
            checkpoint('updating_image', block=name)
            update_image(ACQUISITION)
    elif stop:
        update_image(ACQUISITION)
    limit = max((size for size in RANGE_MILESTONES if size <= stop), default=0)
    if limit:
        result_path = ACQUISITION/'range.json'
        previous = transport.read(result_path) if result_path.is_file() else {}
        if len(previous.get('processed_blocks', ())) < limit:
            from gegi_commercial_dual_range import run as update_range
            checkpoint('fitting_blind_range', blocks=limit)
            update_range(ACQUISITION, block_limit=limit)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resume', action='store_true', help='Resume the prior job in place after checking process ownership')
    args = parser.parse_args(argv)
    for name in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
        os.environ[name] = '1'
    BASE.mkdir(parents=True, exist_ok=True)
    with transport.locked(BASE, resume=args.resume, name='.supervisor.lock'):
        start = readout.timestamp()

        def checkpoint(stage, **extra):
            value = dict(stage=stage, pid=os.getpid(), started_utc=start, updated_utc=readout.timestamp(),
                         planned_pairs=N_PAIRS, free_disk_bytes=shutil.disk_usage(BASE).free,
                         sealed_pairs=sum((ARCHIVE/'chunks/cs137-left'/done.parent.name/'DONE.json').is_file()
                                          for done in (ARCHIVE/'chunks/co60-right').glob('b*/DONE.json')),
                         acquisition_blocks=sum(1 for _ in ACQUISITION.glob('b*/receipt.json')), **extra)
            readout.write(BASE/'status.json', readout.json_bytes(value))
            print(value, flush=True)

        try:
            checkpoint('checking_configuration')
            plan = fresh_plan()
            plan['calibration'] = current_calibration(plan, checkpoint)
            acceptance = BASE/'acceptance.json'
            if not acceptance.is_file():
                inventory = pilot(plan, checkpoint)
                transport.build_acceptance(plan, inventory, acceptance)
            acceptance_ref = binding(acceptance)
            if not ARCHIVE.exists():
                checkpoint('sealing_transport_plan')
                measurement = BASE/'storage-measurement'
                if not (measurement/'measurement.json').is_file():
                    transport.measure_storage(plan, acceptance_ref, measurement)
                plan['resource_budget'] = transport.budget_from_acceptance(plan, acceptance_ref, multiplier=1.15,
                    storage_measurement=binding(measurement/'measurement.json'))
                transport.freeze(ARCHIVE, plan, acceptance_ref)

            transport.inactive_children(ARCHIVE)
            ACQUISITION.mkdir(exist_ok=True)
            config = dict(archive=binding(ARCHIVE/'plan.json'), sources=readout.SOURCES,
                          activity_reference=readout.ACTIVITY_REFERENCE, sources_model='uncollimated points',
                          pairs=N_PAIRS, histories_per_isotope=N_PAIRS * 10_000,
                          first_campaign_parent_id=FIRST_PARENT_ID, first_clock_seed=FIRST_CLOCK_SEED,
                          first_noise_seed=FIRST_CLOCK_SEED + 100_000_000,
                          live_time_per_block_s=readout.LIVE_S, sample_period_ns=20, channels=34,
                          expected_scheduled_parents=N_PAIRS * 55_500, plane=readout.PLANE,
                          calibration_sha256=readout.CALIBRATION_SHA, trigger_profile='standard',
                          depth_calibration=plan['calibration'], range_milestones=list(RANGE_MILESTONES),
                          python=platform.python_version(), platform=platform.platform(),
                          sources_sha256={p.name:readout.digest(p) for p in
                              (Path(__file__), Path(readout.__file__), ROOT/'tools/gegi_source_library.py',
                               ROOT/'tools/gegi_dual_source.py', ROOT/'tools/gegi_exposure_stream.py',
                               ROOT/'tools/gegi_continuous_plane.py', ROOT/'tools/gegi_joint_calibration.py',
                               ROOT/'tools/gegi_fresh_imaging.py', ROOT/'tools/gegi_commercial_dual_range.py')})
            config_path = ACQUISITION/'campaign.json'
            if config_path.is_file():
                transport.require(transport.read(config_path)==config,'Readout configuration changed; restore pinned inputs')
            else:
                readout.write(config_path, readout.json_bytes(config))
            config_sha = readout.digest(config_path)

            contiguous = 0
            for i in range(N_PAIRS):
                if not all((ARCHIVE/'chunks'/key/f'b{i:06d}'/'DONE.json').is_file() for key in MASTER_SEEDS):
                    break
                contiguous += 1
            if contiguous:
                acquire_pairs(contiguous, config_sha, checkpoint)

            def after_pairs(count):
                acquire_pairs(count, config_sha, checkpoint)
                checkpoint('producing_archive')

            checkpoint('producing_archive')
            result = transport.run(ARCHIVE, resume=args.resume, pair_batch_size=5, after_pairs=after_pairs,
                                   worker_factory=lambda request, spool: native_worker(request, spool, checkpoint))
            if result.get('status') in ('completed','completed_with_native_failures'):
                acquire_pairs(N_PAIRS, config_sha, checkpoint)
                checkpoint('completed', archive_status=result['status'])
            else:
                checkpoint(result['status'])
        except BaseException as error:
            checkpoint('failed', error=f'{type(error).__name__}: {error}')
            raise


if __name__ == '__main__':
    main()
