"""Check energy-only Compton orders on two sealed standalone GeGI source runs."""

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path

from gegi_digital_spectra import spectra
from gegi_parent_gamma_reference import evaluate
import scenario_workflow as W


RUNS = ('gegi-source-left-v1', 'gegi-source-right-v1')
FULL_DEPOSIT_ABS_TOL_KEV = 1e-7
SOURCE_REFS = ('gegi_two_source_order_check.py', 'gegi_digital_spectra.py', 'gegi_digital_saved.py',
               'gegi_digital_readout.py', 'gegi_digital_pairs.py', 'gegi_imaging.py',
               'gegi_event_store.py', 'scenario_workflow.py',
               'gegi_substrip.py', 'gegi_substrip_calibration.json', 'gegi_parent_gamma_reference.py',
               'gegi_rejection_diagnostic.py')


def checked_bytes(run, ref, stamp):
    data = W.safe_path(run, ref).read_bytes()
    if len(data) != stamp['bytes'] or hashlib.sha256(data).hexdigest() != stamp['sha256']:
        raise ValueError(f'{run.name}: sealed {ref} changed')
    return data


def run_check(run):
    complete = (run / 'COMPLETE.json').read_bytes()
    stamps = json.loads(complete)['artifacts']

    def sealed(ref):
        return checked_bytes(run, ref, stamps[ref])

    manifest_ref, stream_ref = 'transport/stream/manifest.json', 'transport/stream/events.jsonl'
    receipt = json.loads(sealed('response/run.json'))
    selection = json.loads(sealed('selection.json'))
    manifest = json.loads(sealed(manifest_ref))
    source_keV = selection['gamma_energy_keV']
    if selection['source'] != 'gegi_mono_gamma_v1' or source_keV != 662 or selection['seed'] != manifest['seed']:
        raise ValueError(f'{run.name}: expected the sealed 662 keV source and matching seed')
    if manifest['events_sha256'] != stamps[stream_ref]['sha256']:
        raise ValueError(f'{run.name}: transport stream bindings differ')
    transport = [(line, json.loads(line)) for line in sealed(stream_ref).splitlines()]
    processes = {item['procid']: item['name'] for item in manifest['processes']}
    digital = spectra(run)
    if ([item['event_id'] for _, item in transport] != receipt['nonzero_event_ids'] or
            [item['event_id'] for item in digital['events']] != receipt['nonzero_event_ids']):
        raise ValueError(f'{run.name}: transport, native and digital nonzero IDs differ')
    status_counts, unavailable, unknowns = Counter(), {}, Counter()
    outcomes = dict.fromkeys(('only_true_order', 'only_reverse_order', 'both_allowed', 'neither_allowed'), 0)
    full_nonzero = significant = 0
    candidates = []
    for replay, (transport_line, truth) in zip(digital['events'], transport):
        pid = truth['event_id']
        deposited = truth['truth_edep_keV']
        full = math.isclose(deposited, source_keV, rel_tol=0, abs_tol=FULL_DEPOSIT_ABS_TOL_KEV)
        full_nonzero += full
        if replay['status'] == 'unavailable':
            unavailable[pid] = replay['reason']
            continue
        pairs = replay['two_site']
        status_counts[pairs['status']] += 1
        if pairs['status'] != 'unique_energy_pairing':
            continue
        pairing, = [p for p in pairs['pairings'] if p['energy_compatible']]
        cells = [[site['x_contact_id'], site['y_contact_id']] for site in pairing['sites']]
        native_ref = f'response/events/{pid}.json'
        native = json.loads(sealed(native_ref))
        if (native['event_id'] != pid or not math.isclose(native['truth_edep_keV'], deposited,
                rel_tol=0, abs_tol=FULL_DEPOSIT_ABS_TOL_KEV) or
                native['input_event_sha256'] != hashlib.sha256(transport_line).hexdigest()):
            raise ValueError(f'{run.name}: native and transport event {pid} differ')
        inputs = {'input_group': {'parent_event_metadata': truth},
                  'input_steps': truth['steps'], 'steps': native['steps']}
        reference = evaluate(inputs, processes, {'spatial_diagnostics': [], 'candidates': []})
        ref = reference['references']['ge5keV']
        significant += ref['significant_interaction_count'] == 2
        expected = ref['reference_cells_in_birth_order']
        true_order, outcome = None, None
        reason = ref['unknown_reason']
        orders = pairing['compton_orders']
        allowed = [order['site_index_order'] for order in orders if order['kinematically_allowed']]
        if expected is not None and sorted(cells) == sorted(expected):
            true_order = [cells.index(cell) for cell in expected]
            outcome = ('both_allowed' if len(allowed) == 2 else 'neither_allowed' if not allowed else
                       'only_true_order' if allowed[0] == true_order else 'only_reverse_order')
            if full:
                outcomes[outcome] += 1
        else:
            reason = reason or 'digital_cells_do_not_match_reference'
            unknowns[reason] += 1
        interactions = {tuple(row['interaction_key']): row for row in reference['parent_interactions']}
        births = [interactions[tuple(key)] for key in ref['reference_interaction_keys_in_birth_order'] or ()]
        candidates.append({'event_id': pid, 'native_event_sha256': stamps[native_ref]['sha256'],
                           'native_signals_sha256': native['signals_sha256'],
                           'transport_event_sha256': native['input_event_sha256'],
                           'truth_edep_keV': deposited, 'fully_deposited': full,
                           'slow_energy_keV': pairs['energy_keV'], 'site_cells': cells, 'orders': orders,
                           'reference_significant_interactions': ref['significant_interaction_count'],
                           'reference_cells_in_birth_order': expected, 'reference_match_reason': reason,
                           'reference_birth_processes': [row['birth_process'] for row in births],
                           'reference_unassigned_energy_keV': ref['unassigned_energy_keV'],
                           'reference_site_index_order': true_order, 'order_outcome': outcome})
    return {'run': run.name, 'gamma_energy_keV': source_keV, 'seed': selection['seed'],
            'source_position_mm': selection['source_position_mm'], 'original_counts': receipt['counts'],
            'model_sha256': receipt['model_sha256'], 'field_cache_sha256': receipt['fields']['cache_sha256'],
            'configuration_sha256': receipt['configuration_sha256'],
            'complete_sha256': hashlib.sha256(complete).hexdigest(),
            'input_sha256': {ref: stamps[ref]['sha256'] for ref in
                             ('selection.json', 'response/run.json', manifest_ref, stream_ref)},
            'digital_profile_sha256': digital['digital_profile_sha256'],
            'digital_available': len(digital['events']) - len(unavailable), 'digital_unavailable': unavailable,
            'digital_pairing_status_counts': dict(status_counts), 'fully_deposited_nonzero': full_nonzero,
            'energy_unique': len(candidates), 'energy_unique_fully_deposited': sum(c['fully_deposited'] for c in candidates),
            'energy_unique_two_significant_parent_interactions': significant,
            'energy_unique_exact_cell_matches': sum(c['reference_site_index_order'] is not None for c in candidates),
            'fully_deposited_exact_cell_matches': sum(outcomes.values()),
            'truth_in_allowed': outcomes['only_true_order'] + outcomes['both_allowed'],
            'full_deposit_exact_match_order_outcomes': outcomes, 'reference_unknown_reasons': dict(unknowns),
            'candidates': candidates}


def check(root):
    def source_hashes():
        return {f'tools/{ref}': W.sha(W.ROOT / 'tools' / ref) for ref in SOURCE_REFS}

    sources = source_hashes()
    runs = [run_check(root / name) for name in RUNS]
    for key in ('model_sha256', 'field_cache_sha256', 'digital_profile_sha256'):
        if len({r[key] for r in runs}) != 1:
            raise ValueError(f'Expected both runs to use the same {key}')
    if sources != source_hashes():
        raise ValueError('Order-check source changed during replay')
    return {'kind': 'gegi_two_source_energy_order_check_v1', 'source_sha256': sources,
            'full_deposit_absolute_tolerance_keV': FULL_DEPOSIT_ABS_TOL_KEV,
            'conditional_model': 'One fully absorbed photon with the first scatter on a free electron at rest.',
            'reference': 'At least 5 keV per parent interaction, two distinct exact endpoint cells in birth order. '
                         'Truth labels are applied after the digital replay.',
            'outcome_denominator': 'Energy-unique, fully deposited and exactly matched to the parent-gamma reference.',
            'runs': runs}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs', type=Path, default=W.ROOT / '.local/runs')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    result = check(args.runs)
    with args.output.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write('\n')
