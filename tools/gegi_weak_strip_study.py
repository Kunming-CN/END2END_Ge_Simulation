"""Apply the frozen GeGI late-step diagnostic to four saved ADC blocks."""

import argparse
from collections import Counter
import gzip
import io
import json
from math import fsum, isclose
from pathlib import Path

import numpy as np

import gegi_digital_readout as digital
import gegi_heldout_pairing_loss_study as historic
from gegi_measured_overlap_study import MASSES, cone_record, read_bytes
from gegi_plane_footprint_study import ACQUISITIONS, ROOT, V1_POOL, V1_POOL_SHA, VIEWS
from gegi_pool_measured_planes import LAYER_COUNTS, LAYER_MASS, RECEIPT_KEYS, digest, require
from gegi_trigger_windows import ARCHIVE_NAME, RELATIVE_NS, is_two_strip
from gegi_weak_strip import analyze_weak_strips


LOCAL = V1_POOL.parent
OUTPUT = LOCAL/'independent-1s-weak-strips.json.gz'
MEASURED = LOCAL/'independent-1s-measured-overlap.json'
MEASURED_SHA = 'ddea3349304ada26bf6c7fed54b7ebfdc84781a3e79eeb7e81d191c4cf5aa9e1'
CLOCK = LOCAL/'independent-1s-overlap-reference.json.gz'
CLOCK_SHA = '6cae1651ccc51c20eeef390ba945128584ac35220d8243b05457e3c869d2ce6f'
HOLDOUT = ROOT/'.local/gegi-continuous-pairing/ordinal55-loss.json'
HOLDOUT_SHA = '617fd393132ca3f52fe6bfeefb8a1a19a36005abdb5a08405d8bd5c76e81497c'
CLASSES = ('energy_incompatible', 'energy_compatible_unique', 'energy_compatible_ambiguous')
IDENTITY = ('block', 'trigger_index', 'two_strip_ordinal', 'trigger_time_ns', 'energy_keV')
HISTORIC_FIELDS = ('status', 'sigma_keV_equiv', 'weak_strips')


def load_bound(path, expected, hashes):
    raw = read_bytes(path, expected)
    hashes[path.relative_to(ROOT).as_posix()] = expected
    return raw


def diagnostic(code, times, baseline, rise_ns, collectors, status):
    eligible = sorted(set(digital.CONTACT_IDS) - set(collectors) - historic.GUARDS)
    rail = [] if code is None else np.flatnonzero(
        ((code == digital._ADC_MIN) | (code == digital._ADC_MAX)).any(axis=1)).tolist()
    saturated = None if code is None else [i+1 for i in rail]
    if code is None:
        result = dict(status=str(status), weak_strips=[], contacts=[])
    else:
        result = analyze_weak_strips(code, times, baseline, rise_ns, set(collectors))
        expected = historic.late_step(code, times, baseline, rise_ns, set(collectors))
        require({key: result[key] for key in expected} == expected,
                'Portable calculation differs from the frozen late-step method')
    result.setdefault('sigma_keV_equiv', None)
    result.setdefault('threshold_keV_equiv', None)
    result.setdefault('late_difference_limit_keV_equiv', None)
    result['saturated_contact_ids'] = saturated
    if result['status'] != 'measured':
        result['contacts'] = [
            dict(contact_id=int(cid), status='unevaluable', step_keV_equiv=None,
                 late_difference_keV_equiv=None, sigma_multiple=None,
                 adc_saturated=None if saturated is None else cid in saturated, late_step_stable=None)
            for cid in eligible]
        return result

    require([c['contact_id'] for c in result['contacts']] == eligible, 'Eligible contact roster changed')
    for row in result['contacts']:
        clipped = row.pop('saturated')
        stable = row.pop('persistent')
        detected = row.pop('detected')
        step = row['step_keV_equiv']
        if clipped:
            reason = 'adc_saturated'
        elif step < result['threshold_keV_equiv']:
            reason = 'below_threshold'
        elif step >= historic.MIN_COLLECTED_KEV:
            reason = 'at_or_above_collection_threshold'
        else:
            reason = 'weak_strip' if stable else 'unstable_late_step'
        require(detected == (reason == 'weak_strip'), 'Diagnostic status and detection disagree')
        row.update(status=reason, adc_saturated=clipped, late_step_stable=stable)
    return result


def analyze_block(item, observed, clock, hashes):
    name = item['name']
    folder = ACQUISITIONS/name
    report = json.loads(load_bound(folder/'report.json', item['report_sha256'], hashes))
    plane = json.loads(gzip.decompress(load_bound(folder/'plane.json.gz', item['plane_sha256'], hashes)))
    raw_adc = load_bound(folder/ARCHIVE_NAME, item['adc_windows_sha256'], hashes)
    receipt = report['receipt']
    require(item == clock['provenance'] and report['status'] == 'completed'
            and plane['input_sha256']['acquisition'] == item['report_sha256']
            and plane['input_sha256'].get('adc_windows', item['adc_windows_sha256']) == item['adc_windows_sha256']
            and receipt['digital_profile_sha256'] == digital.PROFILE_SHA256
            and receipt['digital_timing_sha256'] == digital.TIMING_SHA256
            and report['design']['sample_period_ns'] == digital._DT,
            f'Receipt, ADC profile or time convention differs in {name}')
    selected = [(i, row) for i, row in enumerate(report['triggers'], 1) if is_two_strip(row)]
    require(plane['selection']['two_strip_triggers'] == len(selected), f'Selected census differs in {name}')

    with np.load(io.BytesIO(raw_adc), allow_pickle=False) as adc:
        times, baseline = adc['relative_time_ns'], adc['acquisition_baseline_v']
        statuses, ordinals, codes = (adc[key] for key in ('window_status', 'two_strip_ordinal', 'adc_codes'))
        require(adc['report_sha256'].item() == item['report_sha256']
                and all(adc[key].item() == item[key] == receipt[key] for key in RECEIPT_KEYS)
                and np.array_equal(times, RELATIVE_NS)
                and np.array_equal(adc['contact_ids'], digital.CONTACT_IDS)
                and adc['volts_per_code'].item() == digital._LSB_V
                and np.array_equal(adc['trigger_time_ns'], [row['trigger_time_ns'] for _, row in selected])
                and np.array_equal(ordinals, np.flatnonzero(statuses == 'captured')+1)
                and codes.shape == (len(ordinals), len(digital.CONTACT_IDS), len(times))
                and baseline.shape == (len(digital.CONTACT_IDS),) and np.isfinite(baseline).all(),
                f'ADC binding, capture roster or sample coordinates differ in {name}')
    captured = dict(zip(ordinals, codes, strict=True))
    events, waveforms = [], {}
    for ordinal, ((index, row), saved, reference, timing, status) in enumerate(
            zip(selected, plane['triggers'], observed, clock['events'], statuses, strict=True), 1):
        expected_id = name, index, ordinal, row['trigger_time_ns'], row['energy_keV']
        require(tuple(reference[key] for key in IDENTITY) == tuple(timing[key] for key in IDENTITY) == expected_id
                and tuple(saved[key] for key in IDENTITY[1:]) == expected_id[1:]
                and row['rise_end_ns'] == reference['rise_end_ns']
                and reference['adc_window_status'] == saved.get('adc_window_status', status) == status,
                f'ADC, recorded rise, clock and cone ledger identities differ in {name}')
        cone = cone_record(saved)
        require(all(reference[key] == value for key, value in cone.items())
                and all(timing[key] == cone[key] for key in ('allowed_hypotheses', 'hypotheses', *LAYER_MASS))
                and reference['energy_window'] == timing['energy_window'],
                f'Frozen pairing/order or projection weights differ in {name}')
        pairing = row['two_strip_pairings']
        collectors = sorted(c['contact_id'] for c in pairing['collectors'])
        n = pairing['compatible_pairing_count']
        require(collectors == row['x_collecting_strips']+row['y_collecting_strips']
                and len(collectors) == len(set(collectors)) == 4
                and not set(collectors) & historic.GUARDS and n == len(cone['pairings'])
                and len(pairing['pairings']) == 2
                and [p['index'] for p in pairing['pairings'] if p['energy_compatible']]
                == [p['index'] for p in cone['pairings']],
                f'Original collector roster or measured X/Y alternatives differ in {name}')
        code = captured.get(ordinal)
        scope = diagnostic(code, times, baseline, row['rise_end_ns']-row['trigger_time_ns'], collectors, status)
        require(scope['saturated_contact_ids'] == reference['waveform']['saturated_contact_ids'],
                f'ADC rail checks differ in {name}')
        event = dict(zip(IDENTITY, expected_id, strict=True))
        event.update(**cone, pairing_class=CLASSES[n], two_strip_pairings=pairing, collectors=collectors,
                     rise_end_ns=row['rise_end_ns'], energy_window=reference['energy_window'],
                     adc_diagnostic=scope, adc_window_status=str(status),
                     timing_association=timing['timing_association'], timing_link_scope=timing['timing_link_scope'],
                     timing_anchor_group_index=timing['timing_anchor_group_index'],
                     plausible_group_indices=timing['plausible_group_indices'])
        events.append(event)
        representative = scope['weak_strips'] and CLASSES[n] not in waveforms
        if representative or (name == historic.ACQUISITION.name and ordinal == historic.TARGET_ORDINAL):
            waveform = {key: event[key] for key in IDENTITY}
            waveform.update(relative_time_ns=times.tolist(), contact_ids=list(map(int, digital.CONTACT_IDS)),
                            codes=code.tolist(), baseline_v=baseline.tolist(), volts_per_code=digital._LSB_V)
            if representative:
                waveforms[CLASSES[n]] = waveform
            if name == historic.ACQUISITION.name and ordinal == historic.TARGET_ORDINAL:
                waveforms['holdout_target'] = waveform
    return events, waveforms


def holdout_parity(rows, waveform, saved):
    require(len(rows) == len(saved['roster']) == 79, 'Frozen holdout denominator changed')
    for event, old in zip(rows, saved['roster'], strict=True):
        require((event['trigger_index']-1, event['two_strip_ordinal'], event['trigger_time_ns'])
                == (old['trigger_index'], old['ordinal'], old['trigger_time_ns']), 'Holdout trigger identity changed')
        current = {k: event['adc_diagnostic'][k] for k in HISTORIC_FIELDS}
        expected = {k: old['adc_diagnostic'][k] for k in HISTORIC_FIELDS}
        expected['weak_strips'] = [{k: v for k, v in c.items() if k != 'native_collected_input_keV'}
                                   for c in expected['weak_strips']]
        require(current == expected, 'Holdout diagnostic does not reproduce the original saved result')
    require(all(waveform[k] == v for k, v in saved['target']['adc'].items()),
            'Historical target ADC samples differ')
    return dict(windows=len(rows), matched_windows=len(rows), target_trigger_index=waveform['trigger_index'],
                target_contact_ids=[c['contact_id'] for c in rows[historic.TARGET_ORDINAL-1]['adc_diagnostic']['weak_strips']])


def summarize(events):
    scopes = [row['adc_diagnostic'] for row in events]
    weak = [c['step_keV_equiv'] for scope in scopes for c in scope['weak_strips']]
    contacts = Counter(c['status'] for scope in scopes for c in scope['contacts'])
    status = Counter(scope['status'] for scope in scopes)
    measured = status['measured']
    return dict(selected=len(events), measured=measured, unevaluable=len(events)-measured, adc_status=dict(status),
                flagged_windows=sum(bool(scope['weak_strips']) for scope in scopes), flagged_contacts=len(weak),
                weak_step_range_keV_equiv=[min(weak), max(weak)] if weak else None,
                contact_status=dict(contacts), windows_with_any_saturated_contact=sum(
                    bool(scope['saturated_contact_ids']) for scope in scopes),
                **{key: fsum(row[key] for row in events) for key in (*LAYER_MASS, *MASSES)},
                **{key: sum(row[key] for row in events) for key in ('allowed_hypotheses', 'hypotheses')},
                triggers_with_geometry=sum(row['hypotheses'] > 0 for row in events))


def view(events, saved):
    out = {'all': summarize(events),
           'energy_compatible': summarize([r for r in events if r['pairing_class'] != CLASSES[0]])}
    out.update({cls: summarize([r for r in events if r['pairing_class'] == cls]) for cls in CLASSES})
    selection, cone = saved['selection'], saved['layers']['all']
    require((out['all']['selected'], out[CLASSES[0]]['selected'], out[CLASSES[2]]['selected'])
            == tuple(selection[k] for k in ('two_strip_triggers', 'two_strip_triggers_without_compatible_pairing',
                                            'two_strip_triggers_with_two_compatible_pairings'))
            and out['all']['selected'] == cone['triggers']
            and all(isclose(out['all'][k], cone[k], rel_tol=0, abs_tol=1e-12)
                    for k in (*LAYER_COUNTS[1:], *LAYER_MASS)),
            'Weak-strip census or projection totals differ from the frozen plane study')
    return out


def run():
    implementation = (
        Path(__file__),
        *(ROOT/'tools'/name for name in ('gegi_weak_strip.py', 'gegi_heldout_pairing_loss_study.py',
          'gegi_measured_overlap_study.py', 'gegi_plane_footprint_study.py', 'gegi_pool_measured_planes.py',
          'gegi_trigger_windows.py', 'gegi_digital_readout.py', 'gegi_imaging.py', 'gegi_pulse_stream.py')),
    )
    def current_sources():
        return {p.relative_to(ROOT).as_posix(): digest(p.read_bytes()) for p in implementation}

    sources, hashes = current_sources(), {}
    pool = json.loads(gzip.decompress(load_bound(V1_POOL, V1_POOL_SHA, hashes)))
    measured = json.loads(load_bound(MEASURED, MEASURED_SHA, hashes))
    clock = json.loads(gzip.decompress(load_bound(CLOCK, CLOCK_SHA, hashes)))
    holdout = json.loads(load_bound(HOLDOUT, HOLDOUT_SHA, hashes))
    require(measured['source_pool_sha256'] == V1_POOL_SHA
            and clock['input_sha256'][V1_POOL.relative_to(ROOT).as_posix()] == V1_POOL_SHA
            and clock['input_sha256'][MEASURED.relative_to(ROOT).as_posix()] == MEASURED_SHA
            and sources['tools/gegi_heldout_pairing_loss_study.py']
            == holdout['source_sha256']['tools/gegi_heldout_pairing_loss_study.py'],
            'Frozen measurement, clock and holdout reports do not bind the expected inputs')
    blocks, waveforms = [], {}
    for item, timing in zip(pool['inputs'], clock['blocks'], strict=True):
        observed = [r for r in measured['events'] if r['block'] == item['name']]
        rows, examples = analyze_block(item, observed, timing, hashes)
        blocks.append(rows)
        for key, waveform in examples.items():
            waveforms.setdefault(key, waveform)
    events = [r for block in blocks for r in block]
    require(len(events) == len(measured['events']) == 324
            and len({(r['block'], r['trigger_index']) for r in events}) == len(events),
            'Expected the original 324 two-strip trigger roster')
    views = {label: view([r for i in indices for r in blocks[i]], pool['views'][label])
             for label, indices in VIEWS.items()}
    parity = holdout_parity(blocks[0], waveforms['holdout_target'], holdout)
    require(sources == current_sources(), 'Implementation changed during the saved-window calculation')
    design = dict(
        relative_time_ns=RELATIVE_NS.tolist(), quiet_reference_ns=RELATIVE_NS[:historic._QUIET_SAMPLES].tolist(),
        late_plateau_ns=RELATIVE_NS[-5:].tolist(), minimum_settling_ns=2*historic._QUIET_SAMPLES*digital._DT,
        significance=historic.SIGNIFICANCE, collection_threshold_keV=historic.MIN_COLLECTED_KEV,
        feedback_tau_ns=digital._TAU, tail_gain_v_per_kev=historic.TAIL_GAIN, adc_noise_sigma_v=historic.ADC_SIGMA_V,
        volts_per_code=digital._LSB_V,
        scope='Use all original two-strip windows with the frozen late-step calculation. Keep both measured X/Y '
              'alternatives and original order/projected/unresolved weights. Weak strips are positive preamp '
              'steps between five modeled standard deviations and the nominal collection threshold.',
        limits='Five late samples, the modeled noise and the short quiet reference define this diagnostic. '
               'Rail codes anywhere in the window exclude that contact. A persistent step alone is an ADC '
               'observation in keV-equivalent; carrier endpoints and measured energy are separate quantities.',
        new_transport_calls=0, new_drift_calls=0, new_adc_replays=0,
    )
    return dict(kind='gegi_independent_weak_strip_study_v1', status='completed',
                input_sha256=hashes, source_sha256=sources, design=design, holdout_parity=parity,
                views=views, representative_waveforms=waveforms, events=events)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    output = parser.parse_args().output.resolve()
    require(output.is_relative_to(LOCAL) and output.name.endswith('.json.gz') and not output.exists(),
            'Use a new compressed derivative path in the saved study directory')
    result = run()
    payload = json.dumps(result, allow_nan=False, separators=(',', ':')).encode()
    with output.open('xb') as stream:
        stream.write(gzip.compress(payload+b'\n', mtime=0))
    print(json.dumps(dict(sha256=digest(output.read_bytes()), views=result['views'],
                          holdout_parity=result['holdout_parity']), indent=2))


if __name__ == '__main__':
    main()
