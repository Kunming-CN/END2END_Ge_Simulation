"""Export simulated preamplifier ADC samples around saved two-strip triggers."""

import argparse
from bisect import bisect_left
from hashlib import sha256
import json
from pathlib import Path

import numpy as np

import gegi_digital_readout as digital
from gegi_event_store import encoded, sha
from gegi_exposure_stream import ADCExposure, SAMPLE_PERIOD_NS
import gegi_source_library as library


ARCHIVE_NAME = 'two-strip-adc.npz'
RELATIVE_NS = np.arange(-4 * SAMPLE_PERIOD_NS, digital._TIMING['gate_ns'][1] + 1, SAMPLE_PERIOD_NS)


def is_two_strip(row):
    return (row['additional_multi_strip_energy_keV'] is not None
            and len(row['x_collecting_strips']) == len(row['y_collecting_strips']) == 2)


def _window_location(exposure, t, mask):
    start = round((t + RELATIVE_NS[0] - exposure.phase_ns) / SAMPLE_PERIOD_NS)
    if exposure.sample_time_ns(start) != t + RELATIVE_NS[0]:
        raise ValueError('Recorded trigger time is off the ADC clock')
    if start < 0 or start + len(RELATIVE_NS) > exposure.live_samples:
        return start, 'outside_live_time'
    if any(a <= t + RELATIVE_NS[-1] and t + RELATIVE_NS[0] < b for a, b in mask):
        return start, 'excluded_history'
    return start, 'captured'


def _arrays(times, statuses, codes, baseline, digest):
    statuses = np.asarray(statuses, dtype=str)
    return dict(adc_codes=codes, relative_time_ns=RELATIVE_NS, trigger_time_ns=np.asarray(times, dtype=float),
                window_status=statuses, two_strip_ordinal=np.flatnonzero(statuses == 'captured') + 1,
                acquisition_baseline_v=np.asarray(baseline), known_component_adc_sha256=digest)


def capture_context(exposure, time_ns, mask, offset, block):
    """Copy only the qualified window before the readout context is released."""
    start, status = _window_location(exposure, time_ns, mask)
    if status != 'captured':
        return status, None
    first = start - offset
    stop = first + len(RELATIVE_NS)
    if first < 0 or stop > block.shape[1]:
        raise RuntimeError('Sparse readout context does not cover the qualified two-strip ADC window')
    return status, block[:, first:stop].copy()


def context_arrays(times, windows, baseline, digest):
    statuses, codes = [], []
    for time in times:
        status, code = windows[time]
        statuses.append(status)
        if status == 'captured':
            codes.append(code)
    traces = np.stack(codes) if codes else np.empty((0, len(digital.CONTACT_IDS), len(RELATIVE_NS)), dtype=np.int16)
    return _arrays(times, statuses, traces, baseline, digest)


def write_archive(target, arrays, report_sha256):
    np.savez_compressed(target, **arrays, contact_ids=digital.CONTACT_IDS, volts_per_code=digital._LSB_V,
                        report_sha256=report_sha256, digital_profile_sha256=digital.PROFILE_SHA256,
                        digital_timing_sha256=digital.TIMING_SHA256)


def capture(exposure, trigger_times, mask):
    """Collect complete, qualified windows in one pass over the original ADC clock."""
    starts, statuses = [], []
    n = len(RELATIVE_NS)
    for t in trigger_times:
        start, status = _window_location(exposure, t, mask)
        if status == 'captured':
            starts.append(start)
        statuses.append(status)
    if starts != sorted(starts):
        raise ValueError('Trigger times must be in acquisition order')
    channels = len(digital.CONTACT_IDS)
    codes = np.empty((len(starts), channels, n), dtype=np.int16)
    digest = sha256()
    for offset, block in exposure.blocks():
        digest.update(np.asarray(block.T, dtype='<i2', order='C').tobytes())
        if offset < 0:
            baseline_v = (block * digital._LSB_V).mean(axis=1)
        first = bisect_left(starts, offset - n + 1)
        stop = bisect_left(starts, offset + block.shape[1])
        for i in range(first, stop):
            left = max(offset, starts[i])
            right = min(offset + block.shape[1], starts[i] + n)
            codes[i, :, left-starts[i]:right-starts[i]] = block[:, left-offset:right-offset]
    return _arrays(trigger_times, statuses, codes, baseline_v, digest.hexdigest())


def export(report_path, source_paths, output):
    """Replay only the ADC using the two original charge libraries, and bind bytes to the receipt."""
    import gegi_dual_source as acquisition

    if output.exists():
        raise FileExistsError(output)
    raw = report_path.read_bytes()
    report = json.loads(raw)
    design, receipt = report['design'], report['receipt']
    if report.get('kind') != acquisition.KIND or report['status'] != 'completed' or not receipt['known_component_adc_sha256']:
        raise ValueError('Select a completed simulated GeGI acquisition with qualified ADC samples')
    mask = report['exposure']['excluded_intervals_ns']
    if sha(encoded(dict(counts=report['counts'], spectra=report['spectra'], triggers=report['triggers'], mask=mask))) != receipt['observed_result_sha256']:
        raise ValueError('Trigger measurements differ from the saved acquisition receipt')
    if (receipt['digital_profile_sha256'], receipt['digital_timing_sha256']) != (digital.PROFILE_SHA256, digital.TIMING_SHA256):
        raise ValueError('The saved acquisition uses a different readout profile')
    sources = report['sources']
    saved = [library.load_source_library(path) for path in source_paths]
    if any(s.metadata['chunk_sha256'] != r['original']['chunk_sha256'] for s, r in zip(saved, sources, strict=True)):
        raise ValueError('Supply the two original charge libraries in acquisition order')
    live_ns = report['exposure']['clock_live_time_ns']
    schedule = library.schedule_sources(*saved, activities_bq=[s['activity_bq'] for s in sources],
                                        duration_ns=live_ns, seed=design['clock_seed'], include_prehistory=True)
    components, _, _ = acquisition._native_inputs(saved, schedule)
    exposure = ADCExposure(components, live_time_ns=live_ns, phase_ns=design['adc_phase_ns'], noise_seed=design['noise_seed'])
    times = [row['trigger_time_ns'] for row in report['triggers'] if is_two_strip(row)]
    arrays = capture(exposure, times, mask)
    if arrays['known_component_adc_sha256'] != receipt['known_component_adc_sha256']:
        raise ValueError('Replayed ADC bytes differ from the original acquisition')
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as target:
        write_archive(target, arrays, sha(raw))
    return len(arrays['two_strip_ordinal']), len(times)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    parser.add_argument('--source-a', required=True, type=Path)
    parser.add_argument('--source-b', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    captured, total = export(args.report, (args.source_a, args.source_b), args.output)
    print(f'Captured {captured} of {total} two-strip trigger windows in {args.output}')


if __name__ == '__main__':
    main()
