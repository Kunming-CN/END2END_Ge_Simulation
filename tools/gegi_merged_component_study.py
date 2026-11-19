"""Replay each archived component of two merged GeGI triggers on the original ADC clock."""

import argparse
import gzip
import json
from pathlib import Path
import platform

import numpy as np

import gegi_digital_readout as digital
import gegi_dual_source as dual
import gegi_event_energy as energy
from gegi_event_store import encoded, sha
import gegi_exposure_stream as stream
from gegi_merged_trigger_windows import ROOT, TARGETS, identity
import gegi_overlap_clock_reference as reference
import gegi_pulse_stream as pulse
import gegi_source_library as library
from gegi_trigger_windows import RELATIVE_NS, is_two_strip
from gegi_window_activity import analyze_window


LOCAL = reference.LOCAL
ORIGINAL = LOCAL / 'merged-trigger-windows.json'
ORIGINAL_SHA = '67b6cae7d4d1c3d48945c2f77c413dcc74024f9d1f8d521d4bb6e8350494cfdf'
OUTPUT = LOCAL / 'merged-component-controls.json'
FOCUS_NS = 2400
HISTORY_TAU_COUNT = 40
NOISE_CHUNK = 262144
FEATURE_TOL = 1e-9
CONTACTS = digital.CONTACT_IDS
REQUIRE = reference.REQUIRE


def original_noise(seed, lo, hi):
    """Discard the actual Gaussian draws before the focused ADC slice."""
    preamble = np.zeros((len(CONTACTS), stream.PREAMBLE_SAMPLES))
    noise = np.zeros((len(CONTACTS), hi-lo))
    rms = digital._PROFILE['optional_noise_rms_V']
    for row, cid in enumerate(CONTACTS):
        rng = np.random.Generator(np.random.PCG64([seed, cid]))
        preamble[row] = rng.normal(0., rms, stream.PREAMBLE_SAMPLES)
        for start in range(0, lo, NOISE_CHUNK):
            rng.normal(0., rms, min(NOISE_CHUNK, lo-start))
        noise[row] = rng.normal(0., rms, hi-lo)
    baseline = (digital._digitize(preamble)[0] * digital._LSB_V).mean(axis=1)
    return noise, baseline


def load_native(original, observed, block, time_ns, input_sha, sealed):
    folder = reference.ACQUISITIONS / original['block']
    packs = {}
    for source in observed['sources']:
        pack = library.load_source_library(folder / source['input_directory']['relative_to_report_directory'])
        REQUIRE(pack.metadata == source['original'], 'Archived source differs from the acquisition receipt')
        _, _, done, _, archive, _, _ = library._source_inputs(pack.directory)
        digests = {'DONE.json': pack.metadata['chunk_sha256'], 'events.sqlite': pack.metadata['database_sha256'],
                   archive: done['artifacts'][archive]['sha256'],
                   'transport/stream/manifest.json': done['artifacts']['transport/stream/manifest.json']['sha256']}
        for name, digest in digests.items():
            key = (pack.directory / name).relative_to(ROOT).as_posix()
            REQUIRE(digest == sealed[key], f'Archived source seal changed: {key}')
            input_sha[key] = digest
        packs[source['key']] = pack
    library.validate_compatible(*packs.values())

    requested = {identity(row): row for row in original['components']}
    cutoff = float(time_ns[0] - HISTORY_TAU_COUNT * digital._TAU)
    selected, background, background_ledger = {}, [], []
    earlier_omitted = 0
    for row in block['group_ledger']:
        if not row['native_available'] or row['first_ge_deposit_ns'] > time_ns[-1]:
            continue
        # read_native enforces a maximum native endpoint of last deposit + 1001 ns.
        if row['last_ge_deposit_ns'] + 1001 < cutoff:
            earlier_omitted += 1
            continue
        native, status, digest = library.read_native(packs[row['source']], row)
        REQUIRE(native is not None and status == row['native_status'] and digest == row['metadata_sha256'],
                'Native availability, status or bytes differ from the sealed timing reference')
        ctrl = (native, row['first_ge_deposit_ns'], 1.)
        key = identity(row)
        if key in requested:
            REQUIRE(all(row[name] == requested[key][name] for name in (
                'raw_event_id', 'campaign_initial_id', 'first_ge_deposit_ns', 'last_ge_deposit_ns',
                'truth_edep_keV', 'metadata_sha256', 'parent_decay_time_ns')),
                'Control pulse differs from the selected archived group')
            selected[key] = ctrl
        else:
            background.append(ctrl)
            background_ledger.append({name: row[name] for name in (
                'source', 'occurrence_id', 'group_id', 'first_ge_deposit_ns', 'last_ge_deposit_ns', 'metadata_sha256')})
    REQUIRE(len(selected) == len(requested) == 2, 'Exactly two original native control inputs are required')
    return ([selected[key] for key in requested], background, background_ledger, cutoff, earlier_omitted,
            next(iter(packs.values())).channels)


def read_context(exposure, groups, context, codes, lo, baseline):
    context.codes = codes[:, context.lo-lo:context.hi-lo]
    REQUIRE(context.lo >= lo and context.codes.shape[1] == context.hi-context.lo,
            'Focused ADC does not cover the complete reconstruction context')
    return stream._context_readout(context, exposure, groups, baseline)


def fixed_reference(exposure, fixed_group, codes, lo, baseline, *, short=False):
    groups = [fixed_group]
    context = stream._Context(lo, lo+codes.shape[1], 0, range(1)) if short else stream._contexts(exposure, groups)[0]
    return read_context(exposure, groups, context, codes, lo, baseline)['channels']


def digitize(voltage):
    return digital._digitize(voltage)[0].astype(np.int16)


def observe(exposure, codes, lo, sample_ns, original_slice, baseline, profile, geometry, fixed_group):
    neighbors = dual._strip_neighbors(geometry)
    activity = analyze_window(codes, baseline, sample_ns, profile)

    def index(value):
        return round((value - exposure.phase_ns) / digital._DT)

    groups = [(index(row['trigger_reference_ns']), index(row['last_active_ns']), row['coincident'])
              for row in activity['groups']]
    REQUIRE(all(row['rearm_visible'] and row['right_quiet_visible'] for row in activity['groups']),
            'An activity group meets the edge of the focused ADC reconstruction')
    triggers, rejected = [], []
    for context in stream._contexts(exposure, groups):
        event = read_context(exposure, groups, context, codes, lo, baseline)
        steps = event['face_step_keV']
        if steps is not None and min(steps) < energy.MIN_COLLECTED_KEV:
            rejected.append(dict(trigger_time_ns=event['trigger_time_ns'], face_step_keV=steps,
                                 reason='no_persistent_coincident_charge_step', channels=event['channels']))
            continue
        card = dual._trigger_card(event, neighbors, geometry=geometry)
        by_id = {row['contact_id']: row for row in event['channels']}
        collectors = [dual._collector_features(cid, by_id, neighbors) | dict(own=dual._fast_neighbor(cid, by_id))
                      for cid in card['x_collecting_strips'] + card['y_collecting_strips']]
        triggers.append(card | dict(channels=event['channels'], collectors=collectors, face_step_keV=steps,
                                    energy_estimate=energy.estimate_event_energy(event),
                                    would_capture_two_strip=is_two_strip(card)))
    window = codes[:, original_slice]
    return dict(adc_codes=window.tolist(), activity=analyze_window(window, baseline, RELATIVE_NS, profile),
                triggers=triggers, rejected_rises=rejected,
                status='recorded' if triggers else 'no_recorded_trigger',
                fixed_pair_reference_channels=fixed_reference(exposure, fixed_group, codes, lo, baseline))


def code_residual(replay, original):
    delta = np.asarray(replay, dtype=np.int32) - original
    return dict(compared_codes=delta.size, unequal_codes=int(np.count_nonzero(delta)),
                max_abs_codes=int(np.max(np.abs(delta))), rms_codes=float(np.sqrt(np.mean(delta.astype(float)**2))))


def difference(a, b):
    return a-b if a is not None and b is not None else None


def channel_deltas(pair, isolated):
    return [dict(contact_id=cid, **{key: difference(a[key], b[key]) for key in (
        'slow_energy_keV', 'fast_signal_keV_equiv', 'fast_area_V_ns')})
        for cid, a, b in zip(CONTACTS, pair, isolated, strict=True)]


def paired_match(pair, original, original_fast):
    adc = code_residual(pair['adc_codes'], np.asarray(original['adc_codes']))
    REQUIRE(len(pair['triggers']) == 1 and not pair['rejected_rises'], 'Original pair must reproduce one trigger')
    found, saved = pair['triggers'][0], original['original_trigger']
    numeric = ('trigger_time_ns', 'rise_end_ns', 'energy_keV', 'single_pixel_energy_keV',
               'additional_multi_strip_energy_keV', 'x_sum_keV', 'y_sum_keV')
    equals = {key: found[key] == saved[key] for key in saved if key not in numeric}
    residuals = {key: difference(found[key], saved[key]) for key in numeric}
    nulls = all((found[key] is None) == (saved[key] is None) for key in numeric)
    key = 'fast_signal_keV_equiv'
    fast = [{ 'contact_id': cid, key: difference(a[key], b[key])} for cid, a, b in
            zip(CONTACTS, found['channels'], original_fast, strict=True)]
    fast_nulls = all((a[key] is None) == (b[key] is None) for a, b in zip(found['channels'], original_fast, strict=True))
    max_fast = max(abs(row[key]) for row in fast if row[key] is not None)
    REQUIRE(adc['unequal_codes'] == 0 and nulls and fast_nulls and all(equals.values())
            and max_fast <= FEATURE_TOL and all(abs(v) <= FEATURE_TOL for v in residuals.values() if v is not None),
            f"Paired replay disagrees with the original: ADC {adc}, features {residuals}, flags {equals}, fast {max_fast}")
    return dict(adc=adc, numeric_residuals=residuals, categorical_matches=equals, feature_nulls_match=nulls,
                fast_nulls_match=fast_nulls, fast_residual_by_contact=fast, max_abs_fast_residual_keV_equiv=max_fast)


def evaluate(original, block, input_sha, sealed):
    name, t = original['block'], original['trigger_time_ns']
    path = reference.ACQUISITIONS / name / 'report.json'
    observed = json.loads(reference.bound(path, input_sha, original['report_sha256']))
    design, receipt, exposure = (observed[key] for key in ('design', 'receipt', 'exposure'))
    REQUIRE(observed['triggers'][original['trigger_index']-1] == original['original_trigger']
            and receipt['known_component_adc_sha256'] == original['known_component_adc_sha256']
            and receipt['digital_profile_sha256'] == digital.PROFILE_SHA256
            and receipt['digital_timing_sha256'] == digital.TIMING_SHA256
            and receipt['numpy'] == np.__version__ and receipt['python'] == platform.python_version()
            and design['noise_seed'] == original['noise_seed'] and design['clock_seed'] == original['clock_seed']
            and original['contact_ids'] == list(CONTACTS) and original['relative_time_ns'] == RELATIVE_NS.tolist()
            and original['volts_per_code'] == digital._LSB_V, 'Original trigger, ADC receipt or runtime changed')
    profile = design['trigger_profile']['id']
    phase, period = design['adc_phase_ns'], digital._DT
    pivot = round((t-phase)/period)
    radius = FOCUS_NS//period
    lo, hi = pivot-radius, pivot+radius+1
    live_time = exposure['clock_live_time_ns']
    time_ns = np.arange(lo, hi)*period+phase
    REQUIRE(time_ns[radius] == t and time_ns[0] >= 0 and time_ns[-1] < live_time
            and not any(a <= time_ns[-1] and b > time_ns[0] for a, b in exposure['excluded_intervals_ns']),
            'Focused sample context must be on the original clock and outside unknown-history masks')
    original_start = radius + int(RELATIVE_NS[0])//period
    original_slice = slice(original_start, original_start+len(RELATIVE_NS))
    fixed_group = (pivot, round((original['rise_end_ns']-phase)/period), True)

    selected, background, ledger, cutoff, omitted, geometry = load_native(original, observed, block, time_ns, input_sha, sealed)
    noise, baseline = original_noise(design['noise_seed'], lo, hi)
    REQUIRE(np.array_equal(baseline, original['baseline_v']), 'Recreated preamble baseline differs from original')
    variants = {}
    for key, inputs in (('component_1', selected[:1]), ('component_2', selected[1:]), ('pair', selected)):
        adc = stream.ADCExposure(background + inputs, live_time_ns=live_time, phase_ns=phase)
        analog = adc._analog(time_ns)
        codes = digitize(analog + noise)
        variants[key] = observe(adc, codes, lo, time_ns, original_slice, baseline, profile, geometry, fixed_group)

    original_adc = np.asarray(original['adc_codes'], dtype=np.int16)
    original_fast = fixed_reference(adc, fixed_group, original_adc, lo+original_start, baseline, short=True)
    fast_keys = ('contact_id', 'fast_area_V_ns', 'fast_signal_keV_equiv')
    original_fast = [{key: row[key] for key in fast_keys} for row in original_fast]
    pair = variants['pair']
    match = paired_match(pair, original, original_fast)
    no_history = stream.ADCExposure(selected, live_time_ns=live_time, phase_ns=phase)._analog(time_ns)
    paired_codes = np.asarray(pair['adc_codes'])
    match['sensitivity'] = dict(
        removing_history=code_residual(digitize(no_history + noise)[:, original_slice], paired_codes),
        removing_noise=code_residual(digitize(analog)[:, original_slice], paired_codes),
        max_abs_background_v=float(np.max(np.abs(analog-no_history))),
        max_abs_noise_v=float(np.max(np.abs(noise))),
    )
    deltas = {key: channel_deltas(pair['fixed_pair_reference_channels'], variants[key]['fixed_pair_reference_channels'])
              for key in ('component_1', 'component_2')}
    common = {key: original[key] for key in ('block', 'trigger_index', 'trigger_time_ns', 'rise_end_ns',
              'relative_time_ns', 'contact_ids', 'baseline_v', 'volts_per_code', 'original_trigger', 'clock_seed',
              'noise_seed', 'native_current_gap_ns', 'report_sha256', 'known_component_adc_sha256')}
    return common | dict(adc_phase_ns=phase, original_adc_codes=original['adc_codes'], original_activity=original['waveform'],
        original_fast_channels=original_fast, focus_relative_ns=[-FOCUS_NS, FOCUS_NS],
        omitted_early_known_groups=omitted, history_cutoff_ns=cutoff, background_components=ledger,
        components=[{key: value for key, value in row.items() if key != 'isolated_nominal_preamp_v'}
                    for row in original['components']], variants=variants, fixed_pair_reference_deltas=deltas,
        pair_vs_original=match)


def run():
    inputs = {}
    prior = json.loads(reference.bound(ORIGINAL, inputs, ORIGINAL_SHA))
    sealed = prior['input_sha256']
    local_reference = reference.OUTPUT.relative_to(ROOT).as_posix()
    clock = json.loads(gzip.decompress(reference.bound(reference.OUTPUT, inputs, sealed[local_reference])))
    blocks = {row['provenance']['name']: row for row in clock['blocks']}
    paths = [Path(__file__), *(Path(module.__file__) for module in (digital, dual, energy, stream, pulse, library)),
             ROOT/'tools/gegi_window_activity.py', ROOT/'tools/gegi_merged_trigger_windows.py',
             ROOT/'tools/gegi_overlap_clock_reference.py', ROOT/'tools/gegi_event_store.py', ROOT/'tools/gegi_trigger_windows.py']
    sources = {path.relative_to(ROOT).as_posix(): library._hash(path) for path in paths}
    REQUIRE(prior['status'] == 'completed' and {row['block']: row['trigger_index'] for row in prior['examples']} == TARGETS
            and all(sources[key] == prior['source_sha256'][key] for key in sources.keys() & prior['source_sha256'].keys()),
            'Original window set or bound analysis implementation differs')
    examples = []
    for original in prior['examples']:
        print(f"Focused electronics replay for trigger {original['trigger_index']}", flush=True)
        examples.append(evaluate(original, blocks[original['block']], inputs, sealed))
    REQUIRE(all(library._hash(ROOT/path) == digest for path, digest in sources.items()), 'Replay source changed')
    return dict(kind='gegi_merged_component_controls_v1', status='completed', input_sha256=inputs, source_sha256=sources,
        design=dict(trigger_profile=pulse.trigger_profile_definition('standard'), sample_period_ns=digital._DT,
            quiet_samples=pulse._QUIET_SAMPLES, fast_gate_ns=digital._PROFILE['fast_area_gate_ns'],
            slow_gate_ns=pulse._SLOW_NS, slow_threshold_keV=digital._PROFILE['slow_threshold_keV'],
            energy=energy.DEFINITION, digital_profile_sha256=digital.PROFILE_SHA256, digital_timing_sha256=digital.TIMING_SHA256,
            python=platform.python_version(), numpy=np.__version__, history_cutoff_feedback_time_constants=HISTORY_TAU_COUNT,
            fast_baseline='Mean of the last three quiet fast samples through the reference. Signed area uses the nominal pulser gain.',
            noise='Original per-contact Gaussian draws at the absolute clock indices. Baseline is the original ADC preamble mean.',
            history='Original known analog history within 40 feedback time constants of the focused slice. Earlier known tails omitted. '
                    'The focused slice lies outside unavailable-history exclusions. The same history is held in all three variants.',
            fixed_pair_reference='Diagnostic gates anchored to the original pair trigger for all variants. Each recorded trigger also '
                                 'has features at its own reference. Deltas are pair minus the indicated retained component.'),
        counts=dict(original_triggers=len(examples), selected_native_components=2*len(examples), paired_controls=len(examples),
                    single_component_controls=2*len(examples), full_adc_passes=0, new_transport_calls=0, new_drift_calls=0),
        examples=examples)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    output = parser.parse_args().output.resolve()
    REQUIRE(output.is_relative_to(LOCAL) and not output.exists(), 'Use a new local study output')
    result = encoded(run()) + b'\n'
    with output.open('xb') as target:
        target.write(result)
    print(f'{output.name} SHA-256 {sha(result)}')


if __name__ == '__main__':
    main()
