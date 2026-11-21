"""Measured GeGI shared-strip hypotheses directly from a completed candidate archive."""

from bisect import bisect_right
from collections import Counter
from contextlib import closing
import hashlib
from itertools import product
import json
import math
import zlib

import numpy as np

import gegi_adc_topology as topology
import gegi_candidate_imaging as imaging
import gegi_candidate_storage as storage
import gegi_dual_source as dual
import gegi_imaging as compton
import gegi_joint_two_site as joint


SHARED_SHAPES = {(1, 2), (2, 1)}


def split_energy(card, collectors):
    """Allocate the original face-average energy using the two separate strip fractions."""
    xs, ys = (card[f'{axis}_collecting_strips'] for axis in 'xy')
    if (len(xs), len(ys)) not in SHARED_SHAPES:
        raise ValueError('Shared-strip diagnostics require 1×2 or 2×1 measured collecting strips')
    total = card['energy_keV']
    if total is None or card['guard_contact_ids']:
        return {'status': 'unqualified_strip_energy'}
    slow = {row['contact_id']: row['slow_energy_keV'] for row in collectors}
    if (len(collectors) != 3 or sorted(slow) != xs + ys
            or any(value is None or not math.isfinite(value) or value < compton.MIN_COLLECTED_KEV
                   for value in slow.values())):
        raise ValueError('Three distinct qualified strip energies are required for the shared-face allocation')
    sums = [math.fsum(slow[cid] for cid in face) for face in (xs, ys)]
    if ([card['x_sum_keV'], card['y_sum_keV']] != sums or total != math.fsum(sums)/2
            or abs(sums[0]-sums[1]) > max(compton.PAIR_ABS_KEV, compton.PAIR_REL*max(sums))):
        raise ValueError('Original measured face energies must close before assigning shared-strip energies')
    axis = 'x' if len(xs) == 1 else 'y'
    separate, shared = (ys, xs[0]) if axis == 'x' else (xs, ys[0])
    first = total * slow[separate[0]] / math.fsum(slow[cid] for cid in separate)
    energies = [first, total-first]
    return {'status': 'energy_qualified' if min(energies) >= compton.MIN_COLLECTED_KEV else
                      'allocated_site_below_collection_threshold',
            'shared_axis': axis, 'shared_contact_id': shared, 'measured_strip_slow_keV': slow,
            'site_energies_keV': energies, 'cells': list(product(xs, ys))}


def collector_timing(cells, energies, depths, onset_ns, collectors, shared, templates):
    """Predict exactly one CFD crossing on the shared strip's superposed waveform."""
    predict = joint._predictor([templates[cell] for cell in cells], energies, slice(None), (False, False))
    volts = predict(np.asarray([*depths, onset_ns]))
    indices = [r['contact_id']-1 for r in collectors]
    slow = np.array([r['slow_energy_keV'] for r in collectors])
    _, times, valid = joint.modeled_features(volts, indices, slow)
    result = []
    for row, model, ok in zip(collectors, times, valid, strict=True):
        measured = row['preamp_cfd50_ns']
        result.append({'contact_id': row['contact_id'], 'is_shared_strip': row['contact_id'] == shared,
                       'measured_cfd_ns': measured, 'modeled_cfd_ns': float(model) if ok else None,
                       'modeled_crossing_valid': bool(ok),
                       'measured_minus_modeled_ns': float(measured-model) if ok and measured is not None else None})
    return result


def fit_shared(allocation, collectors, templates, volts):
    joint._check_adc(volts)
    fit = topology.fit_flow(allocation['cells'], templates, volts, energies=allocation['site_energies_keV'])
    if fit['status'] != 'scored':
        return fit
    estimate = fit['fit']
    positions = estimate['site_positions_mm']
    energies = estimate['site_energies_keV']
    timings = collector_timing(allocation['cells'], energies, [p[2] for p in positions],
                               estimate['onset_relative_to_trigger_ns'], collectors, allocation['shared_contact_id'], templates)
    sites = [dict(energy_keV=e, position_mm=p) for e, p in zip(energies, positions, strict=True)]
    return dict(fit, collector_timing=timings,
                conditional_orders=[{'site_index_order': order,
                                     'conditional_cone': compton.cone(*(sites[i] for i in order))}
                                    for order in ((0, 1), (1, 0))])


def context_status(record, starts, stops):
    """Classify the window from original context metadata while scanning the census."""
    ctx = record['context']
    trigger = record['trigger_time_ns']
    phase, period = ctx['adc_phase_ns'], ctx['sample_period_ns']
    sample = round((trigger-phase)/period)
    if (period != joint.digital._DT or sample*period+phase != trigger
            or ctx['contact_ids'] != list(joint.digital.CONTACT_IDS) or ctx['volts_per_code'] != joint.digital._LSB_V
            or ctx['digital_profile_sha256'] != joint.digital.PROFILE_SHA256
            or ctx['digital_timing_sha256'] != joint.digital.TIMING_SHA256):
        raise ValueError('An original shared-strip candidate has a different ADC clock/profile/layout')
    lo = sample + int(joint.SAMPLE_NS[0]/period)
    hi = lo + len(joint.SAMPLE_NS)
    after = bisect_right(starts, trigger + float(joint.SAMPLE_NS[-1]))
    if lo < 0 or hi > ctx['acquisition_live_samples']:
        return 'outside_live_time'
    if after and stops[after-1] > trigger + float(joint.SAMPLE_NS[0]):
        return 'excluded_history'
    if lo < ctx['first_sample_index'] or hi > ctx['stop_sample_index']:
        return 'outside_retained_context'
    return 'captured'


def shared_collectors(card, readout, neighbors):
    by_id = {row['contact_id']: row for row in readout['channels']}
    if len(readout['channels']) != len(by_id) or set(by_id) != set(joint.digital.CONTACT_IDS):
        raise ValueError('Each original scalar ADC channel must be present exactly once')
    return [dual._collector_features(cid, by_id, neighbors) for cid in card['x_collecting_strips'] + card['y_collecting_strips']]


def availability(energy, status, templates):
    if energy['status'] != 'energy_qualified':
        return energy['status']
    if status != 'captured':
        return status
    return 'ready' if all(cell in templates for cell in energy['cells']) else 'missing_center_template'


def census(report, database, binding, neighbors, templates, trigger_ids):
    """Retain the original trigger sequence and availability, including excluded shared cases."""
    selected = None if trigger_ids is None else set(trigger_ids)
    if selected is not None and (len(selected) != len(trigger_ids) or not selected or
                                 any(type(x) is not int or x <= 0 for x in selected)):
        raise ValueError('Select distinct original positive shared-strip trigger IDs')
    intervals = report['excluded_intervals_ns']
    starts, stops = zip(*intervals) if intervals else ((), ())
    counts, shapes, chosen = Counter(), Counter(), []
    chain = hashlib.sha256()
    total = 0
    with closing(storage._open_readonly(database)) as db:
        for trigger, decision, body, adc, digest in db.execute(
                'SELECT trigger_id,decision,record,adc_sha256,record_sha256 FROM triggers ORDER BY trigger_id'):
            chain.update(bytes.fromhex(digest))
            if decision != 'candidate':
                continue
            total += 1
            record = json.loads(zlib.decompress(body))
            if record['trigger_id'] != trigger or record['decision'] != decision or storage._record_digest(record, adc) != digest:
                raise ValueError(f'Original saved candidate identity differs at trigger {trigger}')
            card = record['card']
            shape = (len(card['x_collecting_strips']), len(card['y_collecting_strips']))
            if shape not in SHARED_SHAPES:
                continue
            shapes[shape] += 1
            collectors = shared_collectors(card, record['readout'], neighbors)
            energy = split_energy(card, collectors)
            window = context_status(record, starts, stops)
            available = availability(energy, window, templates)
            counts[available] += 1
            if selected is None or trigger in selected:
                chosen.append((trigger, digest, adc, available, window))
    if total != binding['saved_candidates'] or chain.hexdigest() != binding['records_sha256']:
        raise ValueError('Retained candidate population or original trigger checksum chain differs')
    if selected is not None and selected != {row[0] for row in chosen}:
        raise ValueError('Requested trigger does not belong to the original shared-strip population')
    return {'saved_candidates': total, 'shared_strip_candidates': sum(shapes.values()),
            'candidates_outside_shared_strip_scope': total - sum(shapes.values()),
            'shared_topology_counts': {f'{x}x{y}': count for (x, y), count in sorted(shapes.items())},
            'shared_fit_input_status': dict(counts),
            'original_record_chain_sha256': chain.hexdigest()}, chosen


def run(report, database, manifest, templates, trigger_ids):
    saved = storage.store_summary(database)
    binding = saved['completion']
    if (saved['status'] != 'completed' or saved['metadata']['identity'] != report['identity'] or
            any(binding[key] != value for key, value in report['storage_counts'].items())):
        raise ValueError('Completed acquisition and retained candidate archive identities or counts differ')
    request, _ = imaging._request_chain(database.parent, report)
    with closing(storage._open_readonly(database)) as db:
        state = imaging._checkpoint(db, report['identity'])
    admission = imaging._admit_calibration(request, manifest, state['channels'])
    neighbors = dual._strip_neighbors(state['channels'])
    totals, chosen = census(report, database, binding, neighbors, templates, trigger_ids)
    rows = []
    for trigger, digest, adc, status, window in chosen:
        archived = storage.load_candidate(database, trigger)
        card = archived['card']
        collectors = shared_collectors(card, archived['readout'], neighbors)
        energy = split_energy(card, collectors)
        volts = None
        if window == 'captured':
            volts, check = imaging.voltage_window(archived, report['excluded_intervals_ns'])
            if check != 'captured':
                raise ValueError(f'The original ADC context changed for {trigger}')
        result = fit_shared(energy, collectors, templates, volts) if status == 'ready' else {'status': status}
        rows.append({'original_trigger_id': trigger, 'archive_record_sha256': digest, 'archive_adc_sha256': adc,
                     'trigger_time_ns': archived['trigger_time_ns'], 'original_measured_energy_keV': card['energy_keV'],
                     'original_face_totals_keV': [card['x_sum_keV'], card['y_sum_keV']],
                     'original_x_collecting_strips': card['x_collecting_strips'],
                     'original_y_collecting_strips': card['y_collecting_strips'],
                     'original_event_energy_flags': card['event_energy_flags'], 'adc_window_status': window,
                     'original_projection_status': 'outside_two_by_two_projection_scope',
                     'physical_interaction_multiplicity': 'unidentified', 'imaging_weight': None,
                     'collectors': collectors, 'conditional_energy_allocation': energy, 'fit': result})
    return {'complete_saved_candidate_population': totals, 'exact_center_calibration_admission': admission,
            'analyzed_original_trigger_ids': [r['original_trigger_id'] for r in rows],
            'omitted_original_trigger_count': totals['shared_strip_candidates'] - len(rows),
            'fit_status_counts': dict(Counter(r['fit']['status'] for r in rows)), 'triggers': rows}
