"""Freeze an event-disjoint sample, then evaluate saved or new signal hypotheses.

The freeze command reads only the existing reconstruction derivative. Truth and
original native metadata are opened only by the separate evaluate command. No
transport, drift, source pose, or calibration generation is called here. An
explicit calibration and single frozen split enable saved-waveform fitting.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import time

import numpy as np

KIND = 'gegi_saved_recovery_validation_v1'
SALT = 'GeGI saved recovery v1 original-event freeze 2026-10-20'
ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def encoded(value):
    return json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n'


def write_new(path, value):
    """A frozen split or evaluated result is never silently replaced."""
    with Path(path).open('xb') as stream:
        stream.write(encoded(value))


def group_key(record):
    i = record['original_identity']
    return (i['chunk_index'], i['raw_primary_id'], i['pulse_group_id'])


def selection_view(record):
    """Selection allowlist: no truth, source labels, energy or fitted positions."""
    r = record['reconstruction']
    reason = r.get('reason') or r['status']
    if record['native_status'] == 'native_failed':
        reason = 'native_failed'
    strips = r.get('strip_counts')
    return {'campaign_initial_id': record['original_identity']['campaign_initial_id'],
            'reason': reason,
            'stratum': ':'.join(map(str, strips)) if r.get('candidates') and strips else 'all',
            'group_key': list(group_key(record)),
            'metadata_sha256': record['original_identity']['metadata_sha256']}


def rank(event_id):
    return hashlib.sha256(f'{SALT}|{event_id}'.encode()).hexdigest()


def select(views, per_reason=20):
    """Bounded reasons, balanced strip strata, with all groups of an event closed.

    Reasons with fewer than 2*quota distinct events use ceil/half development and
    floor/half holdout targets. Events already assigned by another reason retain
    that split; any unfilled target is reported rather than breaking isolation.
    """
    events = defaultdict(list)
    buckets = defaultdict(lambda: defaultdict(set))
    for v in views:
        events[v['campaign_initial_id']].append(v)
        buckets[v['reason']][v['stratum']].add(v['campaign_initial_id'])
    assignments, selections, targets = {}, [], {}
    # Small classes first prevents a common class consuming their rare events.
    order = sorted(buckets, key=lambda reason: (len(set().union(*buckets[reason].values())), reason))
    for reason in order:
        all_ids = set().union(*buckets[reason].values())
        n = len(all_ids)
        goals = {'development': min(per_reason, (n+1)//2), 'holdout': min(per_reason, n//2)}
        targets[reason] = {'population_events': n, **goals}
        queues = {s: sorted(ids, key=lambda eid: (rank(eid), eid)) for s, ids in buckets[reason].items()}
        chosen, counts = set(), Counter()
        while any(counts[s] < goals[s] for s in goals):
            progressed = False
            for stratum in sorted(queues):
                eligible = [eid for eid in queues[stratum] if eid not in chosen and
                            (eid not in assignments or counts[assignments[eid]] < goals[assignments[eid]])]
                if not eligible:
                    continue
                eid = eligible[0]
                if eid in assignments:
                    split = assignments[eid]
                else:
                    split = min((s for s in goals if counts[s] < goals[s]),
                                key=lambda s: (counts[s]/max(goals[s], 1), s != 'development'))
                    assignments[eid] = split
                chosen.add(eid); counts[split] += 1; progressed = True
                selections.append({'campaign_initial_id': eid, 'reason': reason,
                                   'stratum': stratum, 'split': split})
                if not any(counts[s] < goals[s] for s in goals):
                    break
            if not progressed:
                break
        targets[reason]['selected'] = dict(counts)
    groups = []
    for eid in sorted(assignments):
        for v in sorted(events[eid], key=lambda item: item['group_key']):
            groups.append({**v, 'split': assignments[eid]})
    check_disjoint(groups)
    return {'assignments': [{'campaign_initial_id': eid, 'split': assignments[eid]} for eid in sorted(assignments)],
            'selection_reasons': selections, 'targets': targets, 'groups': groups}


def check_disjoint(groups):
    splits, keys = {}, set()
    for g in groups:
        eid = g['campaign_initial_id']
        if eid in splits and splits[eid] != g['split']:
            raise ValueError('Original event crosses development and holdout')
        splits[eid] = g['split']
        key = tuple(g['group_key'])
        if key in keys:
            raise ValueError('Duplicate saved group in split')
        keys.add(key)


def records(reconstruction):
    complete = read(reconstruction/'COMPLETE.json')
    if complete['summary_sha256'] != sha(reconstruction/'summary.json'):
        raise ValueError('Saved reconstruction summary changed')
    for item in complete['chunks']:
        path = reconstruction/'chunks'/f"{item['chunk_index']:03d}.jsonl.gz"
        receipt = reconstruction/'chunks'/f"{item['chunk_index']:03d}.json"
        if sha(path) != item['data_sha256'] or sha(receipt) != item['receipt_sha256']:
            raise ValueError('Saved reconstruction chunk changed')
        with gzip.open(path, 'rt', encoding='utf-8') as stream:
            for line in stream:
                yield json.loads(line)


def freeze(reconstruction, output, per_reason=20):
    output.mkdir(parents=True, exist_ok=True)
    result = select([selection_view(r) for r in records(reconstruction)], per_reason)
    value = {'kind': KIND, 'stage': 'frozen_before_truth_evaluation', 'selection_truth_used': False,
             'selection_source_labels_used': False, 'salt': SALT, 'per_reason_per_split_max': per_reason,
             'selection_fields': ['campaign_initial_id', 'reconstruction reason', 'native status',
                                  'candidate presence', 'candidate X:Y strip counts'],
             'reconstruction_complete_sha256': sha(reconstruction/'COMPLETE.json'),
             'reconstruction_summary_sha256': sha(reconstruction/'summary.json'),
             'selection_source_sha256': sha(Path(__file__)), **result,
             'closure_rule': 'Every saved group of a selected original event inherits its one split. Quotas count event selections, not closure groups.',
             'counts': {'events': len(result['assignments']), 'groups': len(result['groups']),
                        'groups_by_split': dict(Counter(g['split'] for g in result['groups']))}}
    write_new(output/'split-manifest.json', value)
    return value


def describe(values):
    a = np.asarray(values, dtype=float)
    return {'n': len(a), 'mean': float(a.mean()), 'median': float(np.median(a)),
            'p90': float(np.percentile(a, 90)), 'max': float(a.max())} if len(a) else {'n': 0}


def posthoc_topology(event, names):
    """Native failures retain raw steps rather than endpoint-result rows.

    The independent gamma anchors still come from the original input ledger.
    Completed endpoint topology requires a completed native response; raw or
    partial failure steps cannot supply that truth reference. The original event
    is never edited, and malformed completed rows still fail in topology().
    """
    import gegi_rejection_diagnostic as D
    endpoint_known = event['status'] == 'completed'
    native_view = event if endpoint_known else {**event, 'steps': []}
    return D.topology(native_view, names), endpoint_known


def evaluate_hypothesis(hypothesis, sites, direct, cells):
    """Posthoc endpoint-cell compatibility and conditional gamma oversplitting."""
    predicted = hypothesis.get('sites', [])
    good = {k: v for k, v in cells.items() if v[0] >= 5.}
    pairs = [(s['x_contact'], s['y_contact']) for s in predicted]
    actual = set(good)
    residuals = []
    for s, pair in zip(predicted, pairs):
        if pair not in good:
            continue
        energy, moment = good[pair]
        delta = np.asarray(s['position_mm'])-moment/energy
        residuals.append({'cell': list(pair), 'abs_depth_mm': abs(float(delta[2])),
                          'xy_mm': float(np.linalg.norm(delta[:2])), 'position_3d_mm': float(np.linalg.norm(delta)),
                          'energy_error_keV': s['energy_keV']-energy,
                          'abs_energy_error_keV': abs(s['energy_keV']-energy)})
    gamma_known = direct < 5. and bool(sites) and not any(
        'photon_deposit_without_recorded_secondary' in s['processes'] for s in sites)
    return {'predicted_sites': len(predicted), 'significant_endpoint_cells': len(good),
            'endpoint_pairing_known': bool(good),
            'endpoint_pairing_matches': set(pairs) == actual and len(pairs) == len(actual) if good else None,
            'unsupported_predicted_cells': len(set(pairs)-actual) if good else None,
            'missing_endpoint_cells': len(actual-set(pairs)) if good else None,
            'gamma_anchor_splitting_known': gamma_known,
            'false_gamma_anchor_splitting': len(predicted) > len(sites) if gamma_known else None,
            'matched_cell_residuals': residuals}


def sequence_truth(event, sites, direct):
    """Same recorded photon only, strict birth-time order; no pose input."""
    import gegi_rejection_diagnostic as D
    if direct >= 5. or len(sites) < 2 or len({s['photon_id'] for s in sites}) != 1:
        return None, 'direct_charged_or_multiple_photons_or_fewer_than_two_anchors'
    if any('photon_deposit_without_recorded_secondary' in s['processes'] for s in sites):
        return None, 'unmatched_photon_deposit'
    tracks = event['input_group']['parent_event_metadata']['tracks']
    times = []
    for site in sites:
        births = [t for t in tracks if t['particle'] != 22 and t['parent_trackid'] == site['photon_id']
                  and D.anchor_key(site['photon_id'], D.pos(t)) == D.anchor_key(site['photon_id'], site['position'])]
        # Compare the original recorded track clock directly; no drift-time inference.
        if not births or any('time' not in t for t in births):
            return None, 'anchor_birth_time_unavailable'
        times.append(min(t['time'] for t in births))
    if len(set(times)) != len(times):
        return None, 'anchor_birth_times_tied'
    anchor_cells = []
    for site in sites:
        xs = [cid for cid, energy in site['x'].items() if energy >= 5.]
        ys = [cid for cid, energy in site['y'].items() if energy >= 5.]
        if len(xs) != 1 or len(ys) != 1:
            return None, 'anchor_spans_multiple_or_no_significant_strips'
        anchor_cells.append((xs[0], ys[0]))
    if len(set(anchor_cells)) != len(anchor_cells):
        return None, 'multiple_anchors_share_cell'
    return [anchor_cells[i] for i in sorted(range(len(times)), key=times.__getitem__)], None


def evaluate_reconstruction(result, sites, direct, cells, truth_order, unknown):
    """Apply the same posthoc metrics to baseline and candidate hypotheses."""
    candidate_indices = {c['hypothesis_index'] for c in result['candidates']}
    hrows = [{'hypothesis_index': h['hypothesis_index'], **evaluate_hypothesis(h, sites, direct, cells)}
             for h in result['hypotheses'] if h['hypothesis_index'] in candidate_indices]
    candidates = []
    hypotheses_by_index = {h['hypothesis_index']: h for h in result['hypotheses']}
    evaluated_by_index = {h['hypothesis_index']: h for h in hrows}
    for c in result['candidates']:
        h = hypotheses_by_index[c['hypothesis_index']]
        predicted = [(h['sites'][i]['x_contact'], h['sites'][i]['y_contact']) for i in c['order']]
        status = ('unknown' if truth_order is None or set(predicted) != set(truth_order) or len(predicted) != len(truth_order)
                  else 'correct' if predicted == truth_order else 'wrong')
        candidates.append({'hypothesis_index': c['hypothesis_index'], 'order': c['order'],
            'prior_weight': c['prior_weight'], 'sequence_status': status,
            'endpoint_pairing_matches': evaluated_by_index[c['hypothesis_index']]['endpoint_pairing_matches'],
            'false_gamma_anchor_splitting': evaluated_by_index[c['hypothesis_index']]['false_gamma_anchor_splitting'],
            'sequence_unknown_reason': unknown if truth_order is None else 'unmatched_anchor_cells' if status == 'unknown' else None})
    return hrows, candidates


def summarize(rows):
    counts = Counter(); residuals = defaultdict(list); sequence = Counter(); hypotheses = Counter()
    for row in rows:
        counts['groups'] += 1
        counts['native_failed_groups'] += row['native_status'] == 'native_failed'
        counts['native_incomplete_groups'] += row['native_status'] != 'completed'
        counts['endpoint_topology_known_groups'] += row['endpoint_topology_known']
        counts['endpoint_topology_unknown_groups'] += not row['endpoint_topology_known']
        counts['candidate_groups'] += bool(row['candidates'])
        counts['no_conditional_candidate_groups'] += not row['candidates']
        counts['candidate_count'] += len(row['candidates'])
        counts['classified_imaging_supported_groups'] += row['classification']['supported_imaging']
        counts['spectroscopy_usable_groups'] += row['classification']['spectroscopy']['accepted']
        counts['original_spectroscopy_exact_match_groups'] += row['original_spectroscopy_exact_match']
        counts['repeated_classification_exact_match_groups'] += row['repeated_classification_exact_match']
        counts['spectroscopy_face_compatible_groups'] += row['classification']['spectroscopy'].get('face_compatible', False)
        for key in ('spectroscopy_energy_error_keV', 'native_terminal_energy_error_keV',
                    'adc_minus_terminal_energy_keV', 'adc_x_minus_y_energy_keV'):
            counts[key+'_known_groups'] += row[key] is not None
            counts[key+'_unknown_groups'] += row[key] is None
            if row[key] is not None:
                residuals[key].append(row[key])
                residuals['abs_'+key].append(abs(row[key]))
        for h in row['hypotheses']:
            hypotheses['conditional_hypotheses'] += 1
            hypotheses['pairing_known'] += h['endpoint_pairing_known']
            hypotheses['pairing_unknown'] += not h['endpoint_pairing_known']
            hypotheses['pairing_matches'] += h['endpoint_pairing_matches'] is True
            hypotheses['pairing_mismatches'] += h['endpoint_pairing_matches'] is False
            hypotheses['splitting_known'] += h['gamma_anchor_splitting_known']
            hypotheses['splitting_unknown'] += not h['gamma_anchor_splitting_known']
            hypotheses['false_splitting'] += h['false_gamma_anchor_splitting'] is True
            for v in h['matched_cell_residuals']:
                for key in ('abs_depth_mm', 'xy_mm', 'position_3d_mm', 'abs_energy_error_keV'):
                    residuals[key].append(v[key])
        for c in row['candidates']:
            sequence[c['sequence_status']] += 1
            sequence[c['sequence_status']+'_prior_mass'] += c['prior_weight']
            sequence['pairing_unknown_prior_mass'] += c['prior_weight'] if c['endpoint_pairing_matches'] is None else 0
            sequence['pairing_mismatch_prior_mass'] += c['prior_weight'] if c['endpoint_pairing_matches'] is False else 0
            sequence['pairing_match_prior_mass'] += c['prior_weight'] if c['endpoint_pairing_matches'] is True else 0
            sequence['false_splitting_prior_mass'] += c['prior_weight'] if c['false_gamma_anchor_splitting'] is True else 0
            sequence['splitting_unknown_prior_mass'] += c['prior_weight'] if c['false_gamma_anchor_splitting'] is None else 0
    return {'counts': dict(counts), 'conditional_hypothesis_counts': dict(hypotheses),
            'sequence': dict(sequence), 'errors': {k: describe(v) for k, v in residuals.items()}}


def paired_comparison(rows):
    """Classify each group's ambiguity and compare identical hypothesis/cell pairs."""
    transitions=Counter({k:0 for k in ('new','retained','lost','no_candidate')})
    classes={label:Counter({k:0 for k in ('all_correct','mixed','all_wrong','none','unknown')})
             for label in ('baseline','candidate')}
    metrics=('abs_depth_mm','abs_energy_error_keV','position_3d_mm')
    paired={key:[] for key in metrics};shared_hypotheses=0;shared_cells=0
    for row in rows:
        new=row['candidate_evaluation'];old_present=bool(row['candidates']);new_present=bool(new['candidates'])
        transitions['retained' if old_present and new_present else 'lost' if old_present else
                    'new' if new_present else 'no_candidate']+=1
        row['candidate_pairing_class']={}
        for label,hypotheses in (('baseline',row['hypotheses']),('candidate',new['hypotheses'])):
            matches=[h['endpoint_pairing_matches'] for h in hypotheses]
            category=('none' if not matches else 'unknown' if any(m is None for m in matches) else
                      'all_correct' if all(matches) else 'all_wrong' if not any(matches) else 'mixed')
            row['candidate_pairing_class'][label]=category;classes[label][category]+=1
        old_by_index={h['hypothesis_index']:h for h in row['hypotheses']}
        new_by_index={h['hypothesis_index']:h for h in new['hypotheses']}
        for index in sorted(old_by_index.keys() & new_by_index.keys()):
            shared_hypotheses+=1
            old_cells={tuple(r['cell']):r for r in old_by_index[index]['matched_cell_residuals']}
            new_cells={tuple(r['cell']):r for r in new_by_index[index]['matched_cell_residuals']}
            for cell in sorted(old_cells.keys() & new_cells.keys()):
                shared_cells+=1
                for key in metrics:paired[key].append((old_cells[cell][key],new_cells[cell][key]))
    return {'candidate_group_transitions':dict(transitions),
        'candidate_pairing_classes':{label:dict(values) for label,values in classes.items()},
        'paired_residuals':{'shared_conditional_hypotheses':shared_hypotheses,
            'shared_hypothesis_cells':shared_cells,
            'errors':{key:{'baseline':describe([a for a,b in values]),'candidate':describe([b for a,b in values]),
                'improved':int(sum(b<a for a,b in values)),'worse':int(sum(b>a for a,b in values)),
                'tied':int(sum(b==a for a,b in values))} for key,values in paired.items()},
            'scope':'Same original group, stable energy-flow hypothesis_index and matched endpoint cell only. Smaller errors improve; ties use exact numeric equality. Conditional pairs are not independent events or validated recoveries.'},
        'pairing_class_scope':'One class per group from its conditional hypotheses: unknown if any pairing is unknown; mixed means known correct and wrong alternatives. No candidates is none; all_correct does not validate photon multiplicity or imaging.'}


def evaluate(campaign, reconstruction, output, *, frozen_manifest=None, split=None,
             calibration=None, response_mode='selected_pair'):
    """Read one frozen selection; fit allowlisted signals before truth evaluation.

    Without a calibration this retains the original posthoc path. Candidate runs
    require a single split and a fresh output directory; no sample is reselected.
    """
    import gegi_rejection_diagnostic as D
    import gegi_signal_reconstruction as R
    import gegi_signal_recovery as C
    import gegi_calibration_admission as A
    from gegi_saved_reconstruction import sealed_chunks
    started = time.perf_counter()
    campaign=Path(campaign);reconstruction=Path(reconstruction);output=Path(output)
    candidate_run=calibration is not None
    if split not in (None, 'development', 'holdout') or response_mode not in ('selected_pair', 'all34'):
        raise ValueError('Use development/holdout and an explicit supported response mode')
    if not candidate_run and response_mode != 'selected_pair':
        raise ValueError('A candidate response mode requires an explicit calibration bank')
    if candidate_run:
        calibration=Path(calibration)
        if split is None:
            raise ValueError('Candidate evaluation requires one frozen development or holdout split')
        if output.exists():
            raise FileExistsError('Candidate evaluation needs a separate new output directory')
        if any(output.resolve().is_relative_to(path.resolve()) for path in (campaign,reconstruction,calibration)):
            raise ValueError('Candidate output must be outside immutable inputs')
    manifest_path = Path(frozen_manifest) if frozen_manifest is not None else output/'split-manifest.json'
    source_refs = ('tools/gegi_recovery_validation.py', 'tools/gegi_signal_recovery.py',
                   'tools/gegi_rejection_diagnostic.py', 'tools/gegi_signal_reconstruction.py',
                   'tools/gegi_campaign_response.py', 'tools/gegi_imaging.py')
    if candidate_run:
        source_refs += ('tools/gegi_calibration_admission.py', 'tools/gegi_saved_reconstruction.py',
                        'tools/gegi_event_store.py', 'tools/scenario_workflow.py')
    source_hashes = {ref: sha(ROOT/ref) for ref in source_refs}
    manifest = read(manifest_path); check_disjoint(manifest['groups'])
    if manifest['reconstruction_complete_sha256'] != sha(reconstruction/'COMPLETE.json'):
        raise ValueError('Frozen reconstruction identity changed')
    frozen_hash = sha(manifest_path)
    selected = {tuple(g['group_key']): g for g in manifest['groups'] if split is None or g['split']==split}
    if not selected:
        raise ValueError('Frozen split contains no selected groups')
    saved = {group_key(r): r for r in records(reconstruction) if group_key(r) in selected}
    if set(saved) != set(selected):
        raise ValueError('Frozen group missing from reconstruction')
    _, chunks = sealed_chunks(campaign)
    chunk_map = {index: (seal, done) for index, seal, done in chunks}
    admission=A.campaign(campaign,calibration) if candidate_run else None
    bank=R.TemplateBank(calibration,response_mode=response_mode) if candidate_run else None
    output.mkdir(parents=True,exist_ok=not candidate_run)
    rows = []; native_bindings = {};new_fit_calls=0
    for key, selection in sorted(selected.items()):
        record = saved[key]; identity = record['original_identity']; index, pid, gid = key
        if identity['metadata_sha256'] != selection['metadata_sha256']:
            raise ValueError('Frozen metadata binding changed')
        seal, done = chunk_map[index]; dbpath = seal.parent/'events.sqlite'
        event, native, metadata_hash = R.read_saved_group(dbpath, pid, gid)
        if metadata_hash != selection['metadata_sha256'] or event['campaign_initial_offset']+pid != selection['campaign_initial_id']:
            raise ValueError('Original event identity differs from frozen sample')
        observed = R.observables(event, native, done['response']['readout_recipe']['channels'])
        # Only allowlisted observed signals enter classification; truth is evaluated afterwards.
        classification = C.classify_observables(observed, reconstruction=record['reconstruction'])
        repeated = C.classify_observables(observed, reconstruction=record['reconstruction'])
        repeated_exact = encoded(classification) == encoded(repeated)
        original_exact = all(classification['spectroscopy'].get(k) == v for k, v in event['readout_summary'].items())
        if not original_exact or not repeated_exact:
            raise ValueError('Reused spectroscopy or repeated classification changed')
        if candidate_run:
            # No event, endpoints, tracks, truth energy or source pose enters the fit.
            candidate_result=R.reconstruct_observables(observed,bank)
            candidate_classification=C.classify_observables(observed,reconstruction=candidate_result)
            candidate_repeated=C.classify_observables(observed,reconstruction=candidate_result)
            candidate_exact=encoded(candidate_classification['spectroscopy'])==encoded(classification['spectroscopy'])
            candidate_repeated_exact=encoded(candidate_classification)==encoded(candidate_repeated)
            if not candidate_exact or not candidate_repeated_exact:
                raise ValueError('Candidate changed the original fixed spectroscopy or classification')
            # all34 has an explicit counter; the legacy result has one fit per
            # hypothesis except its explicit pre-fit site-budget rejection.
            new_fit_calls+=(candidate_result['fit_calls'] if response_mode=='all34' else
                sum(h.get('reason')!='site_budget_exceeded' for h in candidate_result['hypotheses']))
        process_manifest = seal.parent/'transport/stream/manifest.json'
        names = {t['procid']: t['name'] for t in read(process_manifest)['processes']}
        topology_result, endpoint_known = posthoc_topology(event, names)
        sites, sites1, compton, spread, shared, direct, cells, length = topology_result
        result = record['reconstruction']
        truth_order, unknown = (sequence_truth(event, sites, direct) if endpoint_known else
                                (None, 'native_endpoint_topology_incomplete'))
        hrows,candidates=evaluate_reconstruction(result,sites,direct,cells,truth_order,unknown)
        spectroscopy = classification.get('spectroscopy', {})
        erec = spectroscopy.get('energy_keV') if spectroscopy.get('accepted') else None
        terminal = classification.get('terminal_charge_diagnostic', {}).get('mean_keV_equivalent')
        face_difference = (spectroscopy['x_energy_keV']-spectroscopy['y_energy_keV']
                           if spectroscopy.get('accepted') else None)
        truth_energy = sum(s['energy_keV'] for s in event['input_steps'])
        rows.append({'original_identity': identity, 'split': selection['split'], 'frozen_reason': selection['reason'],
                     'native_status': record['native_status'], 'classification': classification,
                     'endpoint_topology_known': endpoint_known,
                     'original_spectroscopy_exact_match': original_exact,
                     'repeated_classification_exact_match': repeated_exact,
                     'truth': {'significant_gamma_anchors_ge5keV': len(sites), 'gamma_anchors_ge1keV': len(sites1),
                               'direct_charged_energy_keV': direct, 'compton': compton,
                               'single_anchor_multiple_strips': spread if endpoint_known else None,
                               'multiple_anchors_shared_strip': shared if endpoint_known else None,
                               'input_deposited_energy_keV': truth_energy},
                     'spectroscopy_energy_error_keV': erec-truth_energy if erec is not None else None,
                     'native_terminal_energy_error_keV': terminal-truth_energy if terminal is not None else None,
                     'adc_minus_terminal_energy_keV': erec-terminal if erec is not None and terminal is not None else None,
                     'adc_x_minus_y_energy_keV': face_difference,
                     'hypotheses': hrows, 'candidates': candidates,
                     'unsupported_hypothesis_mass': result.get('unsupported_hypothesis_mass')})
        if candidate_run:
            hnew,cnew=evaluate_reconstruction(candidate_result,sites,direct,cells,truth_order,unknown)
            rows[-1].update(candidate_reconstruction=candidate_result,candidate_evaluation={
                'classification':candidate_classification,'hypotheses':hnew,'candidates':cnew,
                'original_spectroscopy_exact_match':candidate_exact,
                'repeated_classification_exact_match':candidate_repeated_exact,
                'unsupported_hypothesis_mass':candidate_result.get('unsupported_hypothesis_mass')})
        native_bindings[str(index)] = {'events_store_sha256_from_seal': done['artifacts']['events.sqlite']['sha256'],
                                      'seal_sha256': sha(seal), 'process_manifest_sha256': sha(process_manifest)}
    if sha(manifest_path) != frozen_hash:
        raise ValueError('Frozen manifest changed during evaluation')
    if source_hashes != {ref: sha(ROOT/ref) for ref in source_refs}:
        raise ValueError('Evaluation implementation changed during evaluation')
    report = {'kind': KIND, 'stage': 'posthoc_evaluation_completed', 'split_manifest_sha256': frozen_hash,
              'source_sha256': source_hashes, 'original_bindings': native_bindings,
              'counts': {'groups': len(rows), 'events': len({g['campaign_initial_id'] for g in selected.values()})},
              'by_split': {split: summarize([r for r in rows if r['split'] == split]) for split in ('development', 'holdout')},
              'by_split_reason': {split: {reason: summarize([r for r in rows if r['split'] == split and r['frozen_reason'] == reason])
                                        for reason in sorted({r['frozen_reason'] for r in rows if r['split'] == split})}
                                  for split in ('development', 'holdout')},
              'definitions': {'topology': 'Unchanged gegi_rejection_diagnostic.topology: gamma-parent charged birth anchors; significant >=5keV; sensitivity >=1keV.',
                              'pairing': 'Exact set of predicted X/Y cells versus native endpoint cells with >=5keV input deposits. Unknown when no such cells; mismatch is endpoint incompatibility, not proof of the photon-vertex topology.',
                              'false_splitting': 'Predicted site count exceeds significant gamma-anchor count, only when direct charged energy<5keV and all significant photon deposits have recorded-secondary anchors.',
                              'residuals': 'Each conditional hypothesis once; matched endpoint-cell energy and energy-weighted deposition centroid. Repeated cells across hypotheses remain explicit; not independent samples or experimental resolution.',
                              'sequence': 'Strict original charged-secondary track birth time order on one recorded photon_id, unique significant cell per anchor, exact matched cells. Other cases unknown.',
                              'energy': 'Usable signal spectroscopy energy minus total original input deposition; no truth-dependent gain or selection.',
                              'stage_energy': 'Native terminal mean charge-equivalent minus input deposition, peak-ADC energy minus native terminal mean, and signed ADC X-minus-Y face difference are separate. Native terminal is not a new ADC calibration. Failed/incomplete stages remain null.',
                              'incomplete_native': 'Raw failure steps and partial endpoint outputs do not provide a completed endpoint reference. Gamma anchors are still computed from the unchanged original input ledger; endpoint sharing and sequence are unknown.',
                              'sample': 'Stratified diagnostic sample, not campaign efficiency; zero-primary denominators remain in original campaign.'},
              'elapsed_seconds': time.perf_counter()-started, 'new_physics_calls': 0, 'new_fit_calls': new_fit_calls,
              'new_calibration_calls': 0}
    group_output={'split_manifest_sha256': frozen_hash, 'groups': rows}
    if candidate_run:
        bindings=dict(bank.bindings)
        for ref,expected in bindings.items():
            if sha(bank.root/ref)!=expected:
                raise ValueError('Candidate calibration changed during evaluation: '+ref)
        candidate_rows=[{**row,**row['candidate_evaluation']} for row in rows]
        report.update(stage='candidate_evaluation_completed',selected_split=split,response_mode=response_mode,
            calibration_sha256=bank.sha256,calibration_admission=admission,calibration_bindings=bindings,
            calibration_ref=str(bank.root),frozen_manifest_ref=str(manifest_path),
            comparison={'baseline':summarize(rows),'candidate':summarize(candidate_rows),**paired_comparison(rows),
                'reason_transitions':dict(Counter((saved[group_key(row)]['reconstruction'].get('reason') or
                    saved[group_key(row)]['reconstruction']['status'])+' -> '+
                    (row['candidate_reconstruction'].get('reason') or row['candidate_reconstruction']['status']) for row in rows))})
        group_output['selection']={'split':split,'groups':list(selected.values())}
    write_new(output/'evaluation-groups.json', group_output)
    report['evaluation_groups_sha256'] = sha(output/'evaluation-groups.json')
    write_new(output/'report.json', report)
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage', choices=('freeze', 'evaluate'))
    p.add_argument('--reconstruction', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--campaign', type=Path)
    p.add_argument('--frozen-manifest', type=Path, help='Existing frozen split-manifest.json; never reselects')
    p.add_argument('--split', choices=('development','holdout'))
    p.add_argument('--calibration', type=Path, help='Explicit saved bank enables new signal reconstruction')
    p.add_argument('--response-mode', choices=('selected_pair','all34'), default='selected_pair')
    a = p.parse_args()
    if a.stage == 'freeze':
        r = freeze(a.reconstruction, a.output)
    else:
        if a.campaign is None:
            p.error('evaluate requires --campaign')
        r = evaluate(a.campaign, a.reconstruction, a.output,frozen_manifest=a.frozen_manifest,
                     split=a.split,calibration=a.calibration,response_mode=a.response_mode)
    print(json.dumps({k: r[k] for k in ('kind', 'stage', 'counts')}, indent=2))
