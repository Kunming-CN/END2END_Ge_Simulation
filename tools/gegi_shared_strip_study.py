"""Census saved GeGI collector topology and test shared-strip two-site fits."""

import argparse
from bisect import bisect_right
from collections import Counter, defaultdict
from contextlib import closing
from hashlib import sha256
from itertools import product
import json
import math
from pathlib import Path
from time import perf_counter
import zlib

import numpy as np

import gegi_adc_topology_study as topology
import gegi_candidate_imaging as imaging
import gegi_candidate_storage as storage
import gegi_dual_source as dual
from gegi_event_store import encoded
from gegi_exposure_stream import ADCExposure, reconstruct_exposure
import gegi_imaging as compton
import gegi_joint_calibration as calibration
import gegi_joint_two_site as joint
import gegi_position_compatibility as evidence
import gegi_position_uncertainty_study as controls
import scenario_workflow as workflow


OUTPUT = controls.OUTPUT.with_name('shared-strip-candidate-study.json')
ACQUISITION_SHA256 = 'cacc91e7501bf6dc402fdea6086952506accb360a33f7d765c5e31a294b41403'
SHARED_SHAPES = {(1, 2), (2, 1)}
SAMPLE_PER_STRATUM = 4
CONTROL_LAYOUTS = (
    ('shared_x_1', ('injections/point-165.json', 'injections/point-194.json')),
    ('shared_x_2', ('injections/point-166.json', 'injections/point-195.json')),
    ('shared_y_1', ('injections/point-053.json', 'diagnostic-injections/9-26/x_minus-z2.json')),
    ('shared_y_2', ('injections/point-055.json', 'diagnostic-injections/9-26/x_plus-z4.json')),
)


def energy_window(energy):
    if energy is None:
        return 'energy_unavailable'
    return next((f'{v:g}_keV' for v in imaging.plane.LINE_ENERGIES_KEV if abs(energy-v) <= max(5., .02*v)),
                'other_energy')


def collector_rows(card, readout, neighbors):
    by_contact = {row['contact_id']: row for row in readout['channels']}
    if set(by_contact) != set(joint.digital.CONTACT_IDS) or len(readout['channels']) != len(by_contact):
        raise ValueError('Expected each original scalar readout contact exactly once')
    return [dual._collector_features(cid, by_contact, neighbors)
            for cid in card['x_collecting_strips'] + card['y_collecting_strips']]


def window_status(record, starts, stops):
    ctx = record['context']
    dt = ctx['sample_period_ns']
    trigger = record['trigger_time_ns']
    phase = ctx['adc_phase_ns']
    index = round((trigger-phase)/dt)
    if (trigger != index*dt + phase or dt != joint.digital._DT or ctx['contact_ids'] != list(joint.digital.CONTACT_IDS)
            or ctx['volts_per_code'] != joint.digital._LSB_V
            or ctx['digital_profile_sha256'] != joint.digital.PROFILE_SHA256
            or ctx['digital_timing_sha256'] != joint.digital.TIMING_SHA256):
        raise ValueError('Original ADC clock, profile or contact order differs')
    lo = index + int(joint.SAMPLE_NS[0]/dt)
    hi = lo + len(joint.SAMPLE_NS)
    k = bisect_right(starts, trigger + float(joint.SAMPLE_NS[-1]))
    if lo < 0 or hi > ctx['acquisition_live_samples']:
        return 'outside_live_time'
    if k and stops[k-1] > trigger + joint.SAMPLE_NS[0]:
        return 'excluded_history'
    if lo < ctx['first_sample_index'] or hi > ctx['stop_sample_index']:
        return 'outside_retained_context'
    return 'captured'


def shared_pairing(card, collectors):
    xs, ys = (card[f'{axis}_collecting_strips'] for axis in 'xy')
    if (len(xs), len(ys)) not in SHARED_SHAPES:
        return {'status': 'different_collector_topology'}
    total = card['energy_keV']
    if total is None or card['guard_contact_ids']:
        return {'status': 'unqualified_strip_energy'}
    slow = {row['contact_id']: row['slow_energy_keV'] for row in collectors}
    if sorted(slow) != xs + ys or any(v is None or not math.isfinite(v) or v < compton.MIN_COLLECTED_KEV for v in slow.values()):
        raise ValueError('Three independently measured strips are required for the shared-face energy allocation')
    sums = [math.fsum(slow[cid] for cid in strips) for strips in (xs, ys)]
    if ([card['x_sum_keV'], card['y_sum_keV']] != sums or total != math.fsum(sums)/2 or
            abs(sums[0]-sums[1]) > max(compton.PAIR_ABS_KEV, compton.PAIR_REL*max(sums))):
        raise ValueError('Shared-face allocation needs the original qualified face-energy closure')
    shared_axis = 'x' if len(xs) == 1 else 'y'
    separate = ys if shared_axis == 'x' else xs
    per_site = [total*slow[cid]/math.fsum(slow[x] for x in separate) for cid in separate]
    if min(per_site) < compton.MIN_COLLECTED_KEV:
        return {'status': 'allocated_site_below_collection_threshold'}
    return {'status': 'energy_qualified', 'shared_axis': shared_axis,
            'shared_contact_id': xs[0] if shared_axis == 'x' else ys[0],
            'measured_strip_slow_keV': slow, 'energy_compatible': True,
            'sites': [dict(x_contact_id=x, y_contact_id=y, energy_keV=energy)
                      for (x, y), energy in zip(product(xs, ys), per_site, strict=True)]}


def shared_fit(pair, collectors, templates, volts):
    if pair['status'] != 'energy_qualified':
        return {'status': pair['status']}
    cells = [(site['x_contact_id'], site['y_contact_id']) for site in pair['sites']]
    energies = [s['energy_keV'] for s in pair['sites']]
    fit = topology.fit_flow(cells, templates, volts, energies=energies)
    if fit['status'] != 'scored':
        return fit
    positions = [[*templates[cell].origin_mm, z] for cell, z in zip(cells, fit['fit']['depths_mm'], strict=True)]
    point = [*fit['fit']['depths_mm'], fit['fit']['onset_relative_to_trigger_ns']]
    if all(row['preamp_cfd50_ns'] is not None for row in collectors):
        diagnostic = joint.evaluate_waveform_compatibility(pair, collectors, templates, {'parameters': point},
                                                          joint.digital.CONTACT_IDS, local_adc_volts=volts)
        fit['collector_timing'] = diagnostic['collector_timing']
    else:
        fit['collector_timing'] = None
    orders = []
    for order in ((0, 1), (1, 0)):
        candidate = compton.cone(*(dict(energy_keV=energies[i], position_mm=positions[i]) for i in order))
        orders.append({'site_index_order': order, 'conditional_cone': candidate if fit['optimizer']['optimizer_success'] else None})
    return dict(fit, positions_mm=positions, conditional_orders=orders)


def archived_inputs():
    raw = (evidence.RUN/'candidate-acquisition.json').read_bytes()
    if sha256(raw).hexdigest() != ACQUISITION_SHA256:
        raise ValueError('Expected the verified original five-second acquisition receipt')
    report = json.loads(raw)
    database = evidence.RUN/storage.ARCHIVE_NAME
    summary = storage.store_summary(database)
    if (summary['status'] != 'completed' or report['verification']['status'] != 'verified_exact'
            or summary['metadata']['identity'] != report['identity']
            or summary['completion']['saved_candidates'] != report['storage_counts']['saved_candidates']):
        raise ValueError('Original acquisition and candidate census do not close')
    manifest, templates, _, archive_sha = calibration.load(evidence.CENTERS)
    request, _ = imaging._request_chain(evidence.RUN, report)
    with closing(storage._open_readonly(database)) as db:
        state = imaging._checkpoint(db, report['identity'])
    imaging._admit_calibration(request, manifest, state['channels'])
    return report, database, summary, manifest, templates, archive_sha


def census_and_sample(report, database, summary, channels, templates):
    masked = report['excluded_intervals_ns']
    starts, stops = zip(*masked) if masked else ((), ())
    neighbors = dual._strip_neighbors(channels)
    group_counts = defaultdict(Counter)
    shared_availability = Counter()
    strata = defaultdict(list)
    chain = sha256()
    all_cards = existing = 0
    with closing(storage._open_readonly(database)) as db:
        # Scan the original full record digest chain; decode only retained candidates.
        for trigger, decision, record_body, adc_sha, digest in db.execute(
                'SELECT trigger_id,decision,record,adc_sha256,record_sha256 FROM triggers ORDER BY trigger_id'):
            chain.update(bytes.fromhex(digest))
            if decision != 'candidate':
                continue
            raw = json.loads(zlib.decompress(record_body))
            if raw['trigger_id'] != trigger or adc_sha is None or storage._record_digest(raw, adc_sha) != digest:
                raise ValueError(f'Saved record or ADC binding changed at original trigger {trigger}')
            card = raw['card']
            shape = tuple(len(card[key]) for key in ('x_collecting_strips', 'y_collecting_strips'))
            count = group_counts[shape]
            all_cards += 1
            count['saved_cards'] += 1
            if card.get('two_strip_pairings') is not None:
                existing += 1
                count['existing_two_by_two_receipt'] += 1
            energy = card['energy_keV']
            window = energy_window(energy)
            count[window] += 1
            if energy is not None:
                count['qualified_energy'] += 1
            if card['guard_contact_ids']:
                count['guard_collection'] += 1
            collectors = collector_rows(card, raw['readout'], neighbors)
            _, cfd, fast = joint.feature_measurement(collectors)
            all_cfd = bool(cfd) and all(v is not None for v in cfd.values())
            if all_cfd:
                count['all_collectors_have_cfd'] += 1
            if len(fast) >= 4:
                count['at_least_four_distinct_valid_fast_neighbors'] += 1
            if all_cfd and len(fast) >= 4 and energy is not None:
                count['qualified_energy_all_cfd_four_fast'] += 1
            captured = window_status(raw, starts, stops)
            count['adc_window_' + captured] += 1
            if shape not in SHARED_SHAPES:
                continue
            pair = shared_pairing(card, collectors)
            if pair['status'] != 'energy_qualified':
                shared_availability[pair['status']] += 1
            elif captured != 'captured':
                shared_availability[captured] += 1
            elif any((s['x_contact_id'], s['y_contact_id']) not in templates for s in pair['sites']):
                shared_availability['missing_center_template'] += 1
            else:
                shared_availability['original_adc_and_both_center_templates'] += 1
                count['shared_fit_inputs_available'] += 1
                strata[shape, window].append(trigger)
    if (all_cards != summary['completion']['saved_candidates'] or
            chain.hexdigest() != summary['completion']['records_sha256']):
        raise ValueError('Full saved trigger-record census or identity chain changed')
    samples = []
    for (shape, window), triggers in sorted(strata.items()):
        indices = np.linspace(0, len(triggers)-1, min(SAMPLE_PER_STRATUM, len(triggers))).round().astype(int)
        samples += [(triggers[i], shape, window) for i in indices]
    return {'saved_candidates': all_cards, 'existing_two_by_two_candidates': existing,
            'outside_existing_two_by_two_candidates': all_cards-existing,
            'source_record_chain_sha256': chain.hexdigest(),
            'by_measured_strip_topology': [{'x_strips': shape[0], 'y_strips': shape[1], 'counts': count}
                                           for shape, count in sorted(group_counts.items())],
            'shared_fit_availability': shared_availability,
            'fit_sampling': {'selected_original_trigger_ids': sorted(x[0] for x in samples),
                             'scope': 'Four evenly spaced original triggers per sharing orientation and measured-energy category, among rows with both calibrated templates and intact ADC.'}}, sorted(samples)


def measured_sample(report, database, channels, templates, samples):
    rows = []
    neighbors = dual._strip_neighbors(channels)
    for trigger, shape, label in samples:
        saved = storage.load_candidate(database, trigger)
        card = saved['card']
        volts, status = imaging.voltage_window(saved, report['excluded_intervals_ns'])
        if status != 'captured' or energy_window(card['energy_keV']) != label:
            raise ValueError('Sample no longer corresponds to the saved ADC and measured selection')
        collectors = collector_rows(card, saved['readout'], neighbors)
        pair = shared_pairing(card, collectors)
        rows.append({'original_trigger_id': trigger, 'trigger_time_ns': saved['trigger_time_ns'],
                     'measured_strip_topology': shape, 'measured_energy_keV': card['energy_keV'],
                     'energy_window': label, 'pairing': pair,
                     'original_collector_timings_and_fast_neighbors': collectors,
                     'fit': shared_fit(pair, collectors, templates, volts)})
    return rows


def controls_from_saved(channels, templates):
    inputs = controls.study.cfd.scan.Inputs()
    field = inputs.read(controls.study.cfd.CURVES, controls.study.cfd.CURVES_SHA)['provenance']
    refs = {ref for _, selected in CONTROL_LAYOUTS for ref in selected}
    recorded_channels, native, _ = controls.load_archived_traces(inputs, field, refs, set())
    if recorded_channels != channels:
        raise ValueError('Shared-strip controls and saved candidates do not share channel geometry')
    neighbors = dual._strip_neighbors(channels)
    rows = []
    for label, refs in CONTROL_LAYOUTS:
        items = [native[r] for r in refs]
        for energies, phase in product(((331., 331.), (132.4, 529.6)), controls.study.cfd.PHASE_NS):
            seed = controls.NOISE_BASE + 7000 + len(rows)
            clock = ADCExposure([(r['native'], controls.study.cfd.ONSET_NS, e/controls.study.cfd.depth.ENERGY_KEV)
                                 for r, e in zip(items, energies, strict=True)], live_time_ns=controls.study.cfd.END_NS,
                                phase_ns=phase, noise_seed=seed)
            replay = reconstruct_exposure(clock)
            row = {'geometry': label, 'phase_ns': phase, 'noise_seed': seed, 'adc_sha256': replay['adc_sha256'],
                   'status': 'missing_or_multiple_triggers'}
            rows.append(row)
            if len(replay['events']) != 1:
                continue
            readout, = replay['events']
            card = dual._trigger_card(readout, neighbors, geometry=channels)
            collectors = collector_rows(card, readout, neighbors)
            pair = shared_pairing(card, collectors)
            blocks = list(clock.blocks())
            adc = np.concatenate([block for _, block in blocks], axis=1)
            ii = np.rint((readout['trigger_time_ns']+joint.SAMPLE_NS-phase)/joint.digital._DT).astype(int) - blocks[0][0]
            if ii[0] < 0 or ii[-1] >= adc.shape[1]:
                raise ValueError('Independent control waveform misses its original fitting window')
            fit = shared_fit(pair, collectors, templates, adc[:, ii]*joint.digital._LSB_V)
            row.update(status=fit['status'], pairing=pair, fit=fit)
            cells = [a['truth_contact_ids'] for a in items]
            if fit['status'] != 'scored' or {tuple(c) for c in cells} != set(fit['cells']):
                continue
            coeff = [fit['cells'].index(tuple(cell)) for cell in cells]
            predicted = [fit['positions_mm'][i] for i in coeff]
            truth = [item['truth_xyz_mm'] for item in items]
            row['control_error'] = {'axis_error_deg': controls.study.cfd.angle_error(controls.study.cfd.axis_between(*predicted),
                                                                                   controls.study.cfd.axis_between(*truth)),
                                    'site_errors_mm_and_keV': [
                                        controls.position_error(fit['positions_mm'][i], fit['fit']['energies_keV'][i],
                                                                {'xyz_mm': xyz, 'energy_keV': e})
                                        for i, xyz, e in zip(coeff, truth, energies, strict=True)],
                                    'independent_site_record_sha256': [r['source_sha256'] for r in items]}
    return {'physical_layouts': len(CONTROL_LAYOUTS), 'statuses': Counter(r['status'] for r in rows),
            'trials': rows, 'input_sha256': inputs.hashes}


def run(census_only=False):
    began = perf_counter()
    report, database, summary, manifest, templates, calibration_sha = archived_inputs()
    census, sample = census_and_sample(report, database, summary, manifest['channels'], templates)
    result = {'kind': 'gegi_shared_strip_candidate_study_v1',
              'input_sha256': {'acquisition': ACQUISITION_SHA256, 'calibration': calibration_sha,
                               'candidate_store': report['artifacts'][storage.ARCHIVE_NAME]['sha256']},
              'census': census, 'adc_sample': [], 'heldout_injections': None,
              'method': 'One measured shared strip total and two independently measured separate-strip fractions. Preserve the original '
                        'face-average energy with the fixed gain. Fit two center responses on all34 ADC contacts with independent depths and '
                        'one onset; the shared-face CFD crossing belongs to their sum. Both allowed orders remain conditional. '
                        'A shared-strip count cannot establish the number of photon interactions.'}
    if not census_only:
        result['adc_sample'] = measured_sample(report, database, manifest['channels'], templates, sample)
        result['heldout_injections'] = controls_from_saved(manifest['channels'], templates)
    result['elapsed_seconds'] = perf_counter()-began
    result['source_sha256'] = {Path(m.__file__).name: workflow.sha(Path(m.__file__))
                               for m in (controls, topology, joint, calibration, imaging, storage)}
    result['source_sha256'][Path(__file__).name] = workflow.sha(Path(__file__))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--census-only', action='store_true')
    args = parser.parse_args()
    output = args.output or OUTPUT
    if output.exists() or not output.resolve().is_relative_to(OUTPUT.parent):
        parser.error('Choose a new output in the reconstruction evidence directory')
    report = run(args.census_only)
    output.parent.mkdir(exist_ok=True)
    with output.open('xb') as stream:
        stream.write(encoded(report) + b'\n')
    print(json.dumps({'census': report['census']['shared_fit_availability'], 'fitted_adc_sample': len(report['adc_sample']),
                      'elapsed_seconds': report['elapsed_seconds']}, indent=2))


if __name__ == '__main__':
    main()
