"""Resume nominal RSS5 GeGI acquisitions from sealed Geant4/SSD inputs."""

import argparse
import gzip
import hashlib
import json
import os
import platform
from pathlib import Path
import tempfile
import time
from datetime import datetime, timezone


ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN = ROOT / '.local/gegi-dual-source/rss5-simultaneous-large'
ARCHIVE = ROOT / '.local/gegi-10m/campaign'
CALIBRATION = ROOT / '.local/gegi-joint-two-site/gegi-center-calibration.npz'
CALIBRATION_SHA = '72884e1c59090913e67cecd4aec742864b1f1e87867b79fee67bd5fe340eb233'
SOURCES = {
    'cs137-left': dict(isotope='Cs-137', activity_bq=185_000, position_mm=[-40, 0, 40]),
    'co60-right': dict(isotope='Co-60', activity_bq=37_000, position_mm=[40, 0, 40]),
}
BLOCKS = range(5, 30)
FIRST_CLOCK_SEED = 20261123
LIVE_S = .25
PLANE = dict(z_mm=40, extent_mm=120, step_mm=4, sigma_deg=5, plane_prior='uniform-area')
ARTIFACTS = ('report.json', 'two-strip-adc.npz', 'plane.json.gz')
ACTIVITY_REFERENCE = 'https://www.spectrumtechniques.com/product/rss5/'
FIELD_CACHE_SHA = 'f75280e7f21b1a1a06c2a6623aed62873065ca72db02bb1f93a61b9b853b90e8'
GEOMETRY_SHA = 'c26f089322dea21f597c13c43950784310795c7fa1a732e29c4fadc931de73a7'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def json_bytes(body):
    return (json.dumps(body, indent=2, allow_nan=False) + '\n').encode()


def write(path, data):
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f'.{path.name}-', delete=False) as file:
        file.write(data)
        file.flush()
        os.fsync(file.fileno())
    Path(file.name).replace(path)


def load(path):
    return json.loads(path.read_bytes())


def settings(archive=ARCHIVE, blocks=BLOCKS, first_clock_seed=FIRST_CLOCK_SEED, *, fresh=False):
    from gegi_source_library import describe_source_library

    complete_path = archive / 'COMPLETE.json'
    complete = load(complete_path) if complete_path.is_file() else None
    require(fresh or complete is not None, 'Campaign transport/SSD completion receipt is missing')
    if complete is not None:
        require(complete['status'] in ('completed', 'completed_with_native_failures'),
                'Invalid campaign transport/SSD completion receipt')
    if fresh:
        plan_sha = digest(archive / 'plan.json')
        require(load(archive / 'FROZEN.json')['plan_sha256'] == plan_sha, 'Transport/SSD plan bytes changed')
        prior_seeds = {
            load(path)['identity']['batch']['radiation_seed']
            for key in SOURCES for path in (ARCHIVE / 'chunks' / key).glob('b*/DONE.json')
        }
    roster, identities = {}, []
    for i in blocks:
        name = f'b{i:06d}'
        entries = {}
        for key, nominal in SOURCES.items():
            path = archive / 'chunks' / key / name
            done_path = path / 'DONE.json'
            require(done_path.is_file(), f'Transport/SSD chunk is not sealed: {key}/{name} in {archive}')
            done_sha = digest(done_path)
            done = load(done_path)
            identity = done['identity']
            batch = identity['batch']
            offset = identity['campaign_initial_offset']
            require((complete is None or complete['chunks'][str(identity['chunk_index'])] == done_sha)
                    and identity['source_group'] == key and batch['batch_index'] == i
                    and batch['primary_count'] == 10_000,
                    f'Unexpected archived input identity for {key}/{name}')
            if fresh:
                original = describe_source_library(path)
                require(identity['campaign_plan_sha256'] == plan_sha and batch['radiation_seed'] not in prior_seeds
                        and original['isotope'] == nominal['isotope']
                        and original['source_position_mm'] == nominal['position_mm']
                        and original['geometry_sha256'] == GEOMETRY_SHA and original['field_cache_sha256'] == FIELD_CACHE_SHA,
                        f'Overlapping seed, mismatched plan, or incompatible geometry/field for {key}/{name}')
            identities.append((offset, batch['radiation_seed']))
            entries[key] = dict(path=path.relative_to(ROOT).as_posix(), done_sha256=done_sha,
                                database_sha256=done['artifacts']['events.sqlite']['sha256'],
                                campaign_initial_ids=[offset, offset + 9_999], radiation_seed=batch['radiation_seed'])
        clock_seed = first_clock_seed + i - blocks.start
        roster[name] = dict(clock_seed=clock_seed, noise_seed=clock_seed + 100_000_000, inputs=entries)
    offsets, radiation_seeds = zip(*sorted(identities), strict=True)
    require(all(b - a >= 10_000 for a, b in zip(offsets, offsets[1:]))
            and len(set(radiation_seeds)) == len(identities), 'Archived source IDs or radiation seeds overlap')
    require(digest(CALIBRATION) == CALIBRATION_SHA, 'External waveform calibration SHA-256 changed')
    scripts = ('gegi_dual_source.py', 'gegi_source_library.py', 'gegi_exposure_stream.py',
               'gegi_pulse_stream.py', 'gegi_trigger_windows.py', 'gegi_continuous_plane.py',
               'gegi_joint_calibration.py', 'gegi_joint_two_site.py')
    archive_binding = (dict(archive_plan_sha256=plan_sha, activity_reference=ACTIVITY_REFERENCE)
                       if fresh else dict(archive_completion_sha256=digest(complete_path)))
    return dict(kind='gegi_commercial_dual_campaign_v1', sources=SOURCES, live_time_per_block_s=LIVE_S,
                total_clock_time_s=LIVE_S * len(blocks),
                expected_scheduled_parents=int(LIVE_S * len(blocks) * sum(s['activity_bq'] for s in SOURCES.values())),
                archived_transport_histories_per_isotope=10_000 * len(blocks), sources_model='uncollimated points',
                clock_scope='Independent parent clocks within each shared ADC block, with delayed groups from earlier parents. '
                            'Electronics reset between blocks. Independent archive shards; empirical histories can repeat within a block.',
                trigger_profile='standard', plane=PLANE, calibration_sha256=CALIBRATION_SHA,
                **archive_binding,
                implementation_sha256={name: digest(ROOT / 'tools' / name) for name in scripts}, blocks=roster)


def validate_report(folder, spec):
    import gegi_dual_source as acquisition
    from gegi_event_store import encoded, sha

    report = load(folder / ARTIFACTS[0])
    design, receipt = report['design'], report['receipt']
    require(report['kind'] == acquisition.KIND and report['status'] == 'completed'
            and design['clock_seed'] == spec['clock_seed'] and design['noise_seed'] == spec['noise_seed']
            and design['live_time_s'] == LIVE_S and design['sample_period_ns'] == 20
            and len(design['nominal_position']['channel_geometry']) == 34
            and design['trigger_profile'] == acquisition.gegi_pulse_stream.trigger_profile_definition('standard')
            and report['exposure']['qualified_adc_live_time_ns'] > 0
            and receipt['new_transport_calls'] == receipt['new_drift_calls'] == 0
            and all(receipt[k] == v for k, v in acquisition._implementation_hashes().items()),
            f'Acquisition does not match the frozen shared-clock design in {folder.name}')
    observed = {k: report[k] for k in ('counts', 'spectra', 'triggers')}
    observed['mask'] = report['exposure']['excluded_intervals_ns']
    require(sha(encoded(observed)) == receipt['observed_result_sha256'],
            f'Observed result hash differs in {folder.name}')
    for source, (key, nominal) in zip(report['sources'], SOURCES.items(), strict=True):
        original, expected = source['original'], spec['inputs'][key]
        require(source['key'] == key and source['activity_bq'] == nominal['activity_bq']
                and original['isotope'] == nominal['isotope'] and original['source_position_mm'] == nominal['position_mm']
                and original['chunk_sha256'] == expected['done_sha256']
                and original['database_sha256'] == expected['database_sha256']
                and original['original']['initial_primaries'] == 10_000,
                f'Source seal or activity differs for {key}/{folder.name}')


def complete_shard(folder, spec, config_sha, checkpoint, *, adopted=False):
    import gegi_continuous_plane as plane
    import gegi_dual_source as acquisition
    import gegi_pool_measured_planes as pooled

    receipt_path = folder / 'receipt.json'
    inputs = {key: entry['done_sha256'] for key, entry in spec['inputs'].items()}
    for entry in spec['inputs'].values():
        require(digest(ROOT / entry['path'] / 'DONE.json') == entry['done_sha256'],
                f'Archive input seal changed for {folder.name}')
    if receipt_path.is_file():
        receipt = load(receipt_path)
        require(receipt['kind'] == 'gegi_commercial_dual_shard_v1' and receipt['block'] == folder.name
                and receipt['config_sha256'] == config_sha and receipt['input_seals'] == inputs
                and receipt['artifacts'] == {name: digest(folder / name) for name in ARTIFACTS},
                f'Completed receipt has altered contents in {folder.name}')
        return

    report, adc, map_path = (folder / name for name in ARTIFACTS)
    stage_seconds = {}
    paths = tuple(ROOT / row['path'] for row in spec['inputs'].values())
    if not adopted and not report.exists():
        checkpoint('acquiring')
        if adc.exists():
            adc.rename(adc.with_name(f'two-strip-adc.orphan-{time.time_ns()}.npz'))
        start = time.monotonic()
        acquisition.run(paths, tuple(row['activity_bq'] for row in SOURCES.values()), LIVE_S,
                        spec['clock_seed'], report, noise_seed=spec['noise_seed'], capture_two_strip_adc=True)
        stage_seconds['acquisition'] = round(time.monotonic() - start, 3)
    validate_report(folder, spec)
    if not adopted and not adc.exists():
        checkpoint('recovering_adc')
        scratch = adc.with_name(f'.adc-recovery-{time.time_ns()}.npz')
        acquisition.windows.export(report, paths, scratch)
        scratch.rename(adc)
    if not adopted and not map_path.exists():
        checkpoint('projecting')
        start = time.monotonic()
        result = plane.run_from_adc(report, adc, CALIBRATION, **PLANE)
        data = json.dumps(result, allow_nan=False, separators=(',', ':')).encode()
        write(map_path, gzip.compress(data + b'\n', mtime=0))
        stage_seconds['measured_plane'] = round(time.monotonic() - start, 3)

    provenance, result = pooled.block(folder)
    require(result['input_sha256']['calibration'] == CALIBRATION_SHA
            and result['input_sha256']['adc_windows'] == provenance['adc_windows_sha256']
            and result['grid']['assumed_z_mm'] == PLANE['z_mm'] and result['grid']['extent_mm'] == PLANE['extent_mm']
            and result['grid']['step_mm'] == PLANE['step_mm']
            and result['model']['plane_prior'] == PLANE['plane_prior']
            and result['model']['angular_nuisance_sigma_deg'] == PLANE['sigma_deg'],
            f'Measured plane does not match the campaign grid, ADC or calibration in {folder.name}')
    write(receipt_path, json_bytes(dict(
        kind='gegi_commercial_dual_shard_v1', block=folder.name, config_sha256=config_sha, input_seals=inputs,
        artifacts={name: digest(folder / name) for name in ARTIFACTS}, stage_seconds=stage_seconds,
        adopted=adopted, python=platform.python_version(), completed_utc=timestamp())))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, default=ARCHIVE, help='Transport/SSD plan and sealed chunks')
    parser.add_argument('--campaign', type=Path, default=CAMPAIGN, help='Acquisition output folder')
    parser.add_argument('--first-block', type=int, default=BLOCKS.start)
    parser.add_argument('--last-block', type=int, default=BLOCKS.stop - 1)
    parser.add_argument('--first-clock-seed', type=int, default=FIRST_CLOCK_SEED)
    parser.add_argument('--preflight', action='store_true', help='Check and print inputs without any writes or acquisition')
    args = parser.parse_args(argv)
    archive, campaign = args.archive.resolve(), args.campaign.resolve()
    blocks = range(args.first_block, args.last_block + 1)
    first_seed = args.first_clock_seed
    fresh = campaign != CAMPAIGN
    if not (archive.is_relative_to(ROOT / '.local') and campaign.is_relative_to(CAMPAIGN.parent)
            and campaign != CAMPAIGN.parent and 0 <= blocks.start < blocks.stop <= 1_000_000):
        parser.error('Use project-local archive/output paths and an inclusive, nonempty block range')
    if fresh:
        if not (20261148 <= first_seed <= (1 << 64) - 100_000_000 - len(blocks)):
            parser.error('Specify --first-clock-seed 20261148 or above to keep old clock/noise seeds disjoint')
        if archive == ARCHIVE or campaign.is_relative_to(archive):
            parser.error('Use separate new transport/SSD and acquisition folders for a fresh campaign')
    elif (archive, blocks, first_seed) != (ARCHIVE, BLOCKS, FIRST_CLOCK_SEED):
        parser.error('The original acquisition is sealed. Specify a new --campaign for different inputs')
    if args.preflight:
        print(json_bytes(settings(archive, blocks, first_seed, fresh=fresh)).decode(), end='')
        return
    for name in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
        os.environ[name] = '1'
    campaign.mkdir(parents=True, exist_ok=True)
    with (campaign / 'worker.lock').open('a+b') as lock:
        if os.name == 'nt':
            import msvcrt
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        active, completed = None, []
        start_utc = timestamp()

        def checkpoint(status, **extra):
            state = dict(status=status, pid=os.getpid(), started_utc=start_utc, updated_utc=timestamp(),
                         active_block=active, completed_blocks=completed, total_blocks=len(blocks), **extra)
            write(campaign / 'status.json', json_bytes(state))
            print(json.dumps(state), flush=True)

        try:
            checkpoint('checking_inputs')
            config = settings(archive, blocks, first_seed, fresh=fresh)
            config_path = campaign / 'campaign.json'
            if config_path.is_file():
                require(load(config_path) == config, 'Campaign configuration changed since the previous run')
            else:
                write(config_path, json_bytes(config))
            config_sha = digest(config_path)
            for active, spec in config['blocks'].items():
                folder = campaign / active
                folder.mkdir(exist_ok=True)
                adopted = not fresh and active == 'b000005'
                if adopted and not (folder / 'receipt.json').is_file():
                    checkpoint('waiting_for_external_first_block')
                    deadline = time.monotonic() + 1800
                    while True:
                        marker = folder / 'external-failure.json'
                        if marker.is_file():
                            raise RuntimeError(f'First-block worker failed. See {marker}')
                        if all((folder / name).is_file() for name in ARTIFACTS):
                            try:
                                with gzip.open(folder / ARTIFACTS[2], 'rb') as packed:
                                    packed.read()
                                break
                            except (EOFError, gzip.BadGzipFile):
                                pass
                        if time.monotonic() >= deadline:
                            raise TimeoutError('First block did not produce an intact report, ADC archive and measured plane in 30 min')
                        time.sleep(5)
                complete_shard(folder, spec, config_sha, checkpoint, adopted=adopted)
                completed.append(active)
                checkpoint('block_completed')
            active = None
            checkpoint('completed')
        except Exception as error:
            checkpoint('failed', error=f'{type(error).__name__}: {error}')
            raise


if __name__ == '__main__':
    main()
