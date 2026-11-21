"""Compare saved shared-strip CFD and opposite-face energies without refitting ADC."""

import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path


INPUT_KIND = 'gegi_candidate_shared_strip_topology_v1'
KIND = 'gegi_shared_strip_timing_evidence_v1'
HAYWARD = 'https://hdl.handle.net/2027.42/58429'


def finite(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None


def difference(left, right):
    return left - right if left is not None and right is not None else None


def contrast(left, right, measured, modeled):
    observed = difference(measured[left], measured[right])
    expected = difference(modeled.get(left), modeled.get(right))
    return {'contact_order': [left, right], 'measured_delta_ns': observed, 'modeled_delta_ns': expected,
            'measured_minus_modeled_ns': difference(observed, expected)}


def diagnose(row):
    """Describe observed and fitted timing with separate topology and availability fields."""
    faces = [row['original_x_collecting_strips'], row['original_y_collecting_strips']]
    split_axis = next((i for i in (0, 1) if len(faces[i]) == 2 and len(faces[1-i]) == 1), None)
    if split_axis is None:
        raise ValueError('Expected one original collecting strip on one face and two on the other')
    split = faces[split_axis]
    opposite, = faces[1-split_axis]
    intervening = abs(split[1] - split[0])-1
    collectors = {item['contact_id']: item for item in row['collectors']}
    contacts = [*split, opposite]
    if intervening < 0 or len(collectors) != 3 or set(collectors) != set(contacts):
        raise ValueError('Original collecting contact identities disagree with the strip pattern')
    measured = {cid: finite(collectors[cid]['preamp_cfd50_ns']) for cid in contacts}
    fit = row['fit']
    modeled = {item['contact_id']: finite(item['modeled_cfd_ns']) for item in fit.get('collector_timing', ())
               if fit['status'] == 'scored' and item['modeled_crossing_valid']}
    cross_face = [contrast(cid, opposite, measured, modeled) for cid in split]
    same_face = contrast(split[1], split[0], measured, modeled)
    split_slow = [finite(collectors[cid]['slow_energy_keV']) for cid in split]
    x_total, y_total = map(finite, row['original_face_totals_keV'])
    split_total, opposite_total = (x_total, y_total) if split_axis == 0 else (y_total, x_total)
    balance = difference(opposite_total, split_total)
    fraction = None
    if all(value is not None and value >= 0 for value in split_slow) and sum(split_slow) > 0:
        fraction = min(split_slow) / sum(split_slow)
    return {
        'original_trigger_id': row['original_trigger_id'], 'trigger_time_ns': row['trigger_time_ns'],
        'archive_record_sha256': row['archive_record_sha256'], 'archive_adc_sha256': row['archive_adc_sha256'],
        'original_measured_energy_keV': row['original_measured_energy_keV'],
        'original_event_energy_flags': row['original_event_energy_flags'],
        'original_projection_status': row['original_projection_status'], 'original_imaging_weight': row['imaging_weight'],
        'adc_window_status': row['adc_window_status'], 'original_fit_status': fit['status'],
        'physical_interaction_multiplicity': row['physical_interaction_multiplicity'],
        'strip_pattern': {'two_strip_face': 'xy'[split_axis], 'two_strip_contact_ids': split,
                          'opposite_contact_id': opposite, 'intervening_strips': intervening,
                          'status': 'adjacent_ambiguous' if intervening == 0 else 'nonadjacent_collections'},
        'missing_measured_cfd_contact_ids': [cid for cid in contacts if measured[cid] is None],
        'missing_modeled_cfd_contact_ids': [cid for cid in contacts if modeled.get(cid) is None],
        'timing': {'two_strip_minus_opposite': cross_face, 'second_minus_first_same_face': same_face},
        'energy': {'two_strip_slow_energies_keV': split_slow, 'two_strip_face_keV': split_total,
                   'opposite_face_keV': opposite_total, 'opposite_minus_two_strip_face_keV': balance,
                   'smaller_strip_fraction': fraction},
    }


def run(path, selected_ids=None):
    raw = Path(path).read_bytes()
    saved = json.loads(gzip.decompress(raw) if raw.startswith(b'\x1f\x8b') else raw)
    if saved.get('kind') != INPUT_KIND or saved.get('status') != 'completed':
        raise ValueError('Choose a completed saved shared-strip topology receipt')
    ids = [row['original_trigger_id'] for row in saved['triggers']]
    if ids != saved['analyzed_original_trigger_ids'] or len(ids) != len(set(ids)):
        raise ValueError('Saved original trigger identities differ from the receipt census')
    chosen = set(ids if selected_ids is None else selected_ids)
    if not chosen <= set(ids):
        raise ValueError('A requested original trigger is absent from the saved topology receipt')
    rows = [diagnose(row) for row in saved['triggers'] if row['original_trigger_id'] in chosen]
    return {
        'kind': KIND, 'input_topology_sha256': hashlib.sha256(raw).hexdigest(),
        'input_sha256': saved['input_sha256'], 'producer_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'saved_candidates_in_scope': saved['complete_saved_candidate_population']['shared_strip_candidates'],
        'available_original_trigger_count': len(ids), 'analyzed_original_trigger_ids': [r['original_trigger_id'] for r in rows],
        'method_reference': {'title': 'Hayward, Charge loss correction and inter-strip interpolation (2008)',
                             'url': HAYWARD, 'pages': '63–64, 77, 110–112'},
        'interpretation': 'Compare CFD differences with the saved GeGI two-cell center-template prediction where a '
                          'crossing exists. An adjacent pattern remains ambiguous between charge sharing and multiple '
                          'interactions. The two face energies describe observed balance without a charge-loss '
                          'correction. The comparison applies no timing cutoff or imaging weight.',
        'triggers': rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--topology', type=Path, required=True, help='Completed shared-strip topology receipt')
    parser.add_argument('--trigger-id', type=int, action='append', help='Original trigger ID, repeatable')
    parser.add_argument('--output', type=Path, required=True, help='New timing evidence JSON file')
    args = parser.parse_args()
    result = run(args.topology, args.trigger_id)
    with args.output.open('x', encoding='utf-8', newline='\n') as handle:
        json.dump(result, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write('\n')


if __name__ == '__main__':
    main()
