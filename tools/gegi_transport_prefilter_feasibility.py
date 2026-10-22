"""Count fixed transport-only predicates against existing saved signal uses.

Read-only workload study: no detector response, reconstruction or selection change.
"""
from __future__ import annotations
import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
import time

import gegi_campaign_response as C
import gegi_saved_reconstruction as S
from gegi_rejection_diagnostic import anchor_key, pos


PREDICATES = {
    'single_positive_row': 'len(pulse_group.steps) == 1',
    'single_exact_position': 'len(set(tuple(step.position_mm) for step in pulse_group.steps)) == 1; no tolerance or clustering',
    'one_recorded_gamma_anchor_no_direct': 'Every positive group row maps to one recorded gamma-parent charged-secondary birth anchor; no direct charged or unmatched photon deposit. Existing anchor_key uses1e-6mm identity rounding, no energy threshold.',
}


def one_gamma_anchor(group, event):
    tracks = {t['trackid']: t for t in event['tracks']}
    births = {}
    for t in tracks.values():
        parent = tracks.get(t['parent_trackid'])
        if t['particle'] != 22 and parent and parent['particle'] == 22:
            births[t['trackid']] = anchor_key(parent['trackid'], pos(t))
    anchors = set(births.values()); used = set()
    for step in group['steps']:
        tid = step['track_id']; key = None
        if step['particle_pdg'] == 22:
            candidate = anchor_key(tid, step['position_mm'])
            if candidate in anchors:
                key = candidate
        else:
            while tid in tracks:
                if tid in births:
                    key = births[tid]; break
                if tracks[tid]['particle'] == 22:
                    break
                tid = tracks[tid]['parent_trackid']
        if key is None:
            return False
        used.add(key)
    return len(used) == 1


def run(campaign, signal_use, output):
    started = time.perf_counter()
    campaign, signal_use, output = map(Path, (campaign, signal_use, output))
    previous = None
    if output.exists():
        old = S.read(output)
        previous = {'sha256': S.sha(output), 'elapsed_seconds': old['elapsed_seconds'],
                    'predicates': old['study']['predicates_frozen_before_scan'], 'count_table': old['count_table']}
    complete, chunks = S.sealed_chunks(campaign)
    use_complete, use_summary = S.read(signal_use/'COMPLETE.json'), S.read(signal_use/'summary.json')
    if (use_complete['summary_sha256'] != S.sha(signal_use/'summary.json') or
            use_summary['campaign_complete_sha256'] != S.sha(campaign/'COMPLETE.json')):
        raise ValueError('Saved signal-use completion binding differs')
    pins = {x['chunk_index']: x for x in use_complete['chunks']}
    counts = {name: Counter() for name in ('all', *PREDICATES)}
    primaries = {name: set() for name in counts}
    deposit_histogram = Counter()
    inventory = []
    for index, seal, done in chunks:
        base = seal.parent
        stream = base/'transport/stream/events.jsonl.gz'
        manifest_path = base/'transport/stream/manifest.json'
        use_path = signal_use/'chunks'/f'{index:03d}.jsonl.gz'
        for path, digest in ((stream, done['artifacts']['transport/stream/events.jsonl.gz']['sha256']),
                             (manifest_path, done['artifacts']['transport/stream/manifest.json']['sha256']),
                             (use_path, pins[index]['sha256'])):
            if S.sha(path) != digest:
                raise ValueError('Bound transport or signal-use chunk changed')
        manifest = S.read(manifest_path)
        with gzip.open(use_path, 'rt', encoding='utf-8') as f:
            uses = {}
            for line in f:
                row = json.loads(line); identity = row['original_identity']
                key = (identity['raw_primary_id'], identity['pulse_group_id'])
                if key in uses or identity['chunk_index'] != index:
                    raise ValueError('Duplicate or mismatched saved-use group')
                uses[key] = row
        context = {k: done['identity'][k] for k in ('source_group', 'chunk_index', 'campaign_initial_offset')}
        seen = set(); before = counts['all']['groups']
        with gzip.open(stream, 'rt', encoding='utf-8') as f:
            for line in f:
                event = json.loads(line)
                for group in C.pulse_groups(event, manifest['source_id'], context):
                    key = (event['event_id'], group['group_id'])
                    saved = uses.pop(key); original = saved['original_identity']; use = saved['signal_use']
                    if (original['campaign_initial_id'] != context['campaign_initial_offset']+key[0]
                            or original['source_group'] != context['source_group'] or key in seen):
                        raise ValueError('Transport and saved-use identity mismatch')
                    seen.add(key)
                    steps = group['steps']; n = len(steps); deposit_histogram[n] += 1
                    selected = ['all']
                    if n == 1:
                        selected.append('single_positive_row')
                    if len({tuple(s['position_mm']) for s in steps}) == 1:
                        selected.append('single_exact_position')
                    if one_gamma_anchor(group, event):
                        selected.append('one_recorded_gamma_anchor_no_direct')
                    for name in selected:
                        tally = counts[name]; tally['groups'] += 1; tally['positive_rows'] += n
                        tally['spectroscopy_accepted'] += bool(use['spectroscopy']['accepted'])
                        tally['conditional_imaging_groups'] += bool(use['conditional_candidate_count'])
                        tally['conditional_imaging_candidates'] += use['conditional_candidate_count']
                        tally['category:'+use['category']] += 1
                        primaries[name].add((index, key[0]))
        if uses or len(seen) != pins[index]['counts']['pulse_groups']:
            raise ValueError('Transport and saved-use group census differs')
        inventory.append({'chunk_index': index, 'groups': counts['all']['groups']-before,
            'transport_gzip_sha256': done['artifacts']['transport/stream/events.jsonl.gz']['sha256'],
            'manifest_sha256': done['artifacts']['transport/stream/manifest.json']['sha256'],
            'signal_use_sha256': pins[index]['sha256'], 'seed': manifest['seed']})
        if (index+1) % 20 == 0:
            print(json.dumps({'chunks': index+1, 'groups': counts['all']['groups']}), flush=True)
    expected = use_summary['counts']
    if (counts['all']['groups'] != expected['pulse_groups'] or
            counts['all']['spectroscopy_accepted'] != expected['spectroscopy_groups'] or
            counts['all']['conditional_imaging_groups'] != expected['conditional_candidate_groups']):
        raise ValueError('Saved totals differ')
    for name, tally in counts.items():
        for key in ('groups', 'positive_rows', 'spectroscopy_accepted', 'conditional_imaging_groups',
                    'conditional_imaging_candidates'):
            tally.setdefault(key, 0)
        tally['distinct_initial_primaries'] = len(primaries[name])
        tally['group_fraction'] = tally['groups']/counts['all']['groups']
        tally['positive_row_work_fraction'] = tally['positive_rows']/counts['all']['positive_rows']
    totals = {k: sum(v[k] for v in complete['groups'].values()) for k in
              ('initial_primaries', 'zero_deposit_primaries', 'nonzero_primaries', 'pulse_groups')}
    source_names = ('tools/gegi_transport_prefilter_feasibility.py', 'tools/gegi_campaign_response.py',
                    'tools/gegi_saved_reconstruction.py', 'transport/gegi_source.py',
                    'simulation/gegi_response.jl', 'simulation/gegi_campaign_response.jl',
                    'tools/gegi_rejection_diagnostic.py')
    result = {
        'kind': 'gegi_transport_prefilter_feasibility_v1', 'status': 'completed_saved_data_only',
        'model': 'gpt-6.1-sol', 'reasoning_effort': 'ultra',
        'model_effort_evidence': 'Assigned worker session context; not external runtime attestation',
        'working_root': str(S.ROOT), 'elapsed_seconds': time.perf_counter()-started,
        'new_science_calls': {'transport': 0, 'native_drift': 0, 'field_solve': 0, 'calibration': 0},
        'production_selection_changed': False, 'denominators': totals,
        'study': {'scope': 'All100completedchunks/all57613savedgroups; no sampling or exclusions',
            'predicates_frozen_before_scan': PREDICATES, 'thresholds_tuned': False,
            'truth_usage': 'Workload/census study only; saved acceptances used to measure losses, never tune cuts or recovery',
            'identity': 'chunk_index/raw_primary_id/pulse_group_id/source_group/campaign_initial_id; compressed transport and use hashes checked',
            'science_originals_opened': 'Only sealed transport sparse JSON gzip/manifests and saved signal-use gzip; no raw LH5, SQLite/native waveform arrays or holdout evaluation records'},
        'already_before_ssd': [
            'Transport extractor removes zero-energy Ge rows; passive-material deposits remain raw truth and are not SSD inputs.',
            'Zero-Ge-deposit primaries are census-only and omitted from sparse events. Positive Ge rows retain original identities and anchored100000ns decay pulse groups.',
            'Native process_event skips any zero-energy step defensively. Campaign pulse_groups requires every input step positive and submits every nonempty group.',
            'Completed hash-identical groups are resumed from store; recorded native failures remain null/unknown. No nonzero energy, deposit-count, imaging, guard or multiplicity cut precedes SSD.'
        ],
        'boundary_facts': {
            'available': ['positive Ge deposition energy_keV, local position_mm, time_ns, raw table/row, track/parent IDs and PDG; pre/post chord endpoints and geometric boundary labels',
                'group row assignment, origin, half-open finite horizon and group counts; total Edep and deposit count computable without SSD',
                'parent-event track birth records with process ID, parent, PDG, birth time, position and kinetic energy; process-ID/name mapping in manifest; decay-photon birth records'],
            'limits': ['Sparse deposit rows do not carry a universal step interaction-process label; a track creation process is not every later gamma interaction.',
                'Deposit-row count is neither gamma interaction count nor photon count. Gamma anchors require ancestry/vertex interpretation; emitted photons are not necessarily contributors within a group.',
                'Transport position/guard vicinity does not give collecting electrode, completed charge, ADC threshold acceptance or reconstructed energy. Deposition time is not drift time.']},
        'count_table': {k: dict(v) for k,v in counts.items()},
        'positive_deposit_count_histogram': dict(sorted(deposit_histogram.items())),
        'candidate_assessment': {
            'single_positive_row_or_single_exact_position': 'Conditional truth-assisted resolved-multisite imaging study only. No two distinct stored charge-deposit locations; this does not make its spectroscopy unusable. Current candidate counts are an algorithm proxy, not validated imaging loss/false-exclusion evidence.',
            'one_gamma_interaction': 'Conditional only, after exact anchor definition and ancestry accounting; electron step multiplicity, secondary photons and direct charged deposition prevent substituting row count. One gamma anchor can remain useful spectroscopy and may distribute charge spatially.',
            'low_total_edep': 'No unconditional positive-energy cut established. A separately declared analysis ROI could preselect truth energy, but it changes the response/threshold/efficiency question; no threshold chosen here.',
            'guard_vicinity': 'Not safe. Geometry alone does not predict charge termination or lost energy; guard signals can contribute valid spectroscopy. Existing guard collection/transient counts require SSD.',
            'more_than_N_deposits': 'Computational truncation only; not physical unusability. High-multiplicity groups can carry complete spectroscopy and imaging; no N chosen.',
            'multiple_photons': 'Conditional single-photon imaging population only, not general spectroscopy. Must identify contributing photons inside the pulse group, not just emitted parent-event photons; preserve pileup/cascade identity.'},
        'cost_interpretation': {'positive_rows': 'Requested native_deposit workload proxy/upper bound on calls avoided; native failure can stop a group before its remaining rows. Cost per row is not constant.',
            'per_group_drift_timing_available_in_this_input': False, 'saved_wall_seconds_claimed': None,
            'known_stage_sums_seconds': {'native_response_and_store': 75541.740, 'transport_driver': 11102.995},
            'stage_sum_scope': 'Reused handoff figures; recovered generations and IO, not pure drift or a calendar runtime. Do not multiply group/row fractions by these stage sums.'},
        'recommendation': 'Keep the existing zero-input skip as default. If the owner wants a separate resolved-multisite-only simulation mode, use an explicit truth-assisted single-position exclusion with this measured spectroscopy loss and original denominators; retain skipped IDs/reasons and raw truth. Do not silently apply it to the full radiation-charge-readout workflow.',
        'bindings': {'campaign_complete_sha256': S.sha(campaign/'COMPLETE.json'),
            'signal_use_complete_sha256': S.sha(signal_use/'COMPLETE.json'),
            'signal_use_summary_sha256': S.sha(signal_use/'summary.json'),
            'source_sha256': {n:S.sha(S.ROOT/n) for n in source_names},
            'chunk_inventory_sha256': S.S.sha(S.S.encoded(inventory))},
    }
    if previous is not None:
        result['preceding_two_predicate_measurement'] = previous
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('w' if previous else 'x', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2, allow_nan=False); f.write('\n')
    print(json.dumps({'output': str(output), 'sha256': S.sha(output),
                      'elapsed_seconds': result['elapsed_seconds'], 'counts': result['count_table']}), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--campaign', type=Path, required=True)
    p.add_argument('--signal-use', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args(); run(a.campaign, a.signal_use, a.output)
