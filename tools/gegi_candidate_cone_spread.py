"""Quantify joint cone-geometry spread from retained GeGI candidate fits."""

import argparse
from collections import Counter
import gzip
import json
import math
from pathlib import Path

import numpy as np

import gegi_candidate_range as source_range
import gegi_candidate_records as records
import gegi_cone_spread_geometry as spread
from gegi_event_store import encoded, sha
import scenario_workflow as workflow


MODEL_FIELDS = ('local_center', 'local_lateral', 'all34_center', 'all34_lateral')


def load(path):
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == '.gz' else raw), sha(raw)


def plane_weights(weight):
    if weight is None:
        return None
    return {'nominal_mass': weight['nominal_mass'], 'waveform_fit_status': weight['waveform_fit_status'],
            'orders': [{k: o[k] for k in ('order', 'nominal_mass', 'status')} for o in weight['orders']]}


def fit_samples(model, orders, energies, points, representation):
    samples = spread.solutions(model) if 'sampled_alternates' in model else []
    return {'representation': representation,
            'status': 'joint_samples_retained' if samples else 'joint_samples_not_saved',
            'samples': samples,
            'orders': [dict(site_index_order=o['site_index_order'],
                            **spread.order_geometry(samples, energies, o, points, spread.RADII_MM)) for o in orders]}


def pair_geometry(base, lateral, weights, refit, points):
    index = base['index']
    orders = base['compton_orders']
    if (index, base['cells'], base['energy_compatible'], orders) != (
            lateral['index'], lateral['cells'], lateral['energy_compatible'], lateral['compton_orders']):
        raise ValueError('Original pair cells, compatibility, or order ledger differs')
    center_fit = base['fit']
    later_fit = lateral['fit']
    if center_fit['status'] != later_fit['status']:
        raise ValueError('Original pairing fit status differs between saved maps')
    old, xy = weights
    energies = old['site_energies_keV'] if old is not None else None
    if energies != (xy['site_energies_keV'] if xy is not None else None):
        raise ValueError('Original measured pair energies differ between saved maps')
    geometry = {'pairing_index': index, 'cells': base['cells'], 'energy_compatible': base['energy_compatible'],
                'original_fit_status': center_fit['status'], 'site_energies_keV': energies, 'retained_orders': orders,
                'original_pair_weights': {'center': plane_weights(old), 'lateral': plane_weights(xy)},
                'models': {}}
    models = geometry['models']
    local = later_fit.get('fits', {}).get('waveform', {})
    if 'center' in local:
        prior = center_fit['fits']['waveform']['center']
        later = local['center']
        a, b = prior['positions_mm'], later['positions_mm']
        geometry.update(original_center_positions_mm=a,
                        original_center_joint_alternates_saved='sampled_alternates' in prior,
                        lateral_compatibility_center_best_shift_mm=[math.dist(x, y) for x, y in zip(a, b, strict=True)])
        sample_from = prior if geometry['original_center_joint_alternates_saved'] else later
        models['local_center'] = dict(fit_samples(sample_from, orders, energies, points, 'center'),
                                      sample_receipt='center_map' if sample_from is prior else 'lateral_map')
    lateral_representation = next((key for key in ('lateral', 'partial_lateral') if key in local), None)
    if lateral_representation:
        models['local_lateral'] = fit_samples(local[lateral_representation], orders, energies, points, lateral_representation)
    if refit is not None:
        sites = refit['cells']
        if ([[s['x_contact_id'], s['y_contact_id']] for s in sites] != base['cells']
                or [s['energy_keV'] for s in sites] != energies):
            raise ValueError('The all-34 diagnostic is bound to different measured cells or energies')
        all34 = refit['fits']['waveform_all']
        for name, fit in all34.items():
            key = 'all34_center' if name == 'center' else 'all34_lateral'
            models[key] = fit_samples(fit, orders, energies, points, name)
    return geometry


def map_pair_ids(trial):
    return {pair['index']: pair for pair in trial['pairings']}


def trigger_geometry(base, lateral, base_fit, lateral_fit, archive, all34, points):
    keys = ('original_trigger_id', 'trigger_time_ns', 'trigger_index', 'two_strip_ordinal', 'energy_keV')
    if not all(base[k] == lateral[k] for k in keys) or archive['original_trigger_id'] != base['original_trigger_id']:
        raise ValueError('Original trigger identity differs across saved fits')
    trigger_id = base['original_trigger_id']
    first, second = map_pair_ids(base), map_pair_ids(lateral)
    pairs = []
    for pair, updated in zip(base_fit['pairings'], lateral_fit['pairings'], strict=True):
        index = pair['index']
        pairs.append(pair_geometry(pair, updated, (first.get(index), second.get(index)),
                                   all34.pop((trigger_id, index), None), points))
    masses = {k: {n: row[n] for n in ('projected_mass', 'unresolved_mass')}
              for k, row in (('center', base), ('lateral', lateral))}
    return {k: base[k] for k in keys} | {'archive_adc_sha256': archive['archive_adc_sha256'],
                                        'archive_record_sha256': archive['archive_record_sha256'],
                                        'original_adc_window_status': base['adc_window_status'],
                                        'original_image_weights': masses, 'pairings': pairs}


def summarize(trials):
    pairs = [p for t in trials for p in t['pairings']]
    metrics = {'triggers': len(trials), 'pairings': len(pairs),
               'original_pair_status': dict(Counter(p['original_fit_status'] for p in pairs)), 'models': {}}
    for name in MODEL_FIELDS:
        fits = [p['models'][name] for p in pairs if name in p['models']]
        directions = [o for model in fits for o in model['orders'] if o['geometry_count']]
        metrics['models'][name] = {'pairings_with_saved_model': len(fits),
                                   'representations': dict(Counter(f['representation'] for f in fits)),
                                   'sample_count_by_pairing': dict(Counter(str(len(f['samples'])) for f in fits)),
                                   'conditional_orders_with_geometry': len(directions),
                                   'orders_with_multiple_geometries': sum(o['geometry_count'] > 1 for o in directions),
                                   'orders_with_unconverged_sample_geometry': sum(o['geometry_count'] > o['converged_geometry_count']
                                                                                 for o in directions),
                                   'maximum_axis_span_deg': max((o['axis_pairwise_span_max_deg'] for o in directions), default=None),
                                   'maximum_finite_vertex_angle_span_deg_by_radius': [
                                       max((o['finite_vertex_response_by_radius'][i]['geometric_angle_span_max_deg']
                                            for o in directions), default=None) for i in range(len(spread.RADII_MM))]}
    return metrics


def run(center_path, lateral_path, compatibility_path, archive):
    center, center_sha = load(center_path)
    lateral, lateral_sha = load(lateral_path)
    expected = center['input_sha256']
    if (any(lateral['input_sha256'].get(k) != v for k, v in expected.items())
            or workflow.sha(archive) != expected['candidate_store']):
        raise ValueError('The saved maps must bind to the same original archive and center calibration')
    if (center['fit_receipt'].get('position_model', 'center') != 'center'
            or lateral['fit_receipt']['position_model'] != 'lateral' or center['selection'] != lateral['selection']):
        raise ValueError('Expected center and lateral maps for the same full original census')
    input_sha256 = lateral['input_sha256'] | {'center_map': center_sha, 'lateral_map': lateral_sha}
    all34 = {}
    if compatibility_path is not None:
        compatibility, compat_sha = load(compatibility_path)
        candidate = compatibility['candidates']
        if candidate['input_sha256'] != expected | {'baseline_fit': center_sha}:
            raise ValueError('The all-34 refits must bind to the same original archive and center map')
        all34 = {(row['original_trigger_id'], row['pairing_index']): row for row in candidate['refits']}
        if len(all34) != len(candidate['refits']):
            raise ValueError('Duplicate all-34 original pairing IDs')
        input_sha256['all34_compatibility'] = compat_sha
    _, joined = records.saved_events(center, archive)
    _, lateral_join = records.saved_events(lateral, archive)
    binding_keys = ('original_trigger_id', 'archive_record_sha256', 'archive_adc_sha256')
    if not all(all(a[k] == b[k] for k in binding_keys) for a, b in zip(joined, lateral_join, strict=True)):
        raise ValueError('Candidate ADC bindings differ across map receipts')
    directions = source_range.direction(source_range.sphere_grid(spread.DIRECTIONS))
    points = np.vstack([r*directions for r in spread.RADII_MM])
    trials = [trigger_geometry(a, b, c, d, j, all34, points) for a, b, c, d, j in zip(
        center['triggers'], lateral['triggers'], center['fit_receipt']['candidates'],
        lateral['fit_receipt']['candidates'], joined, strict=True)]
    summary = summarize(trials)
    if all34 or summary['original_pair_status'] != center['candidate_analysis']['pair_fit_status_counts']:
        raise ValueError('Original candidate pair census or all-34 refit coverage changed')
    paths = (Path(__file__), Path(spread.__file__), Path(records.__file__), Path(spread.imaging.__file__),
             Path(spread.response.__file__), Path(source_range.__file__))
    return {'kind': 'gegi_five_second_candidate_joint_cone_spread_v1',
            'input_sha256': input_sha256,
            'source_sha256': {p.name: workflow.sha(p) for p in paths},
            'scope': {k: center['candidate_analysis'][k] for k in ('saved_candidates', 'two_strip_candidates',
                      'retained_candidates_outside_two_strip_scope', 'qualified_counts', 'storage_counts')},
            'grid': {'origin_mm': [0., 0., 0.], 'radii_mm': spread.RADII_MM, 'unit_directions': directions.tolist(),
                     'fixed_angular_kernel_sigma_deg': spread.SIGMA_DEG},
            'summary': summary, 'triggers': trials,
            'definition': 'Source-blind comparison of retained joint position solutions under measured site energies and '
                          'original orders. When the original center map lacks alternative coordinates, the center '
                          'samples come from the same-data lateral compatibility pass, with the original center position '
                          'and shift kept separate. Absent all-34 models remain absent. The fixed angular kernel describes '
                          'shape only. No source position, weighting or new order selection is inferred.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('center-map', 'lateral-map', 'candidate-store', 'output'):
        parser.add_argument(f'--{flag}', type=Path, required=True)
    parser.add_argument('--compatibility', type=Path, help='Optional matching all-34 refit receipt.')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Choose a new output path')
    result = run(args.center_map, args.lateral_map, args.compatibility, args.candidate_store)
    data = gzip.compress(encoded(result), mtime=0)
    with args.output.open('xb') as stream:
        stream.write(data)
    print(json.dumps({'sha256': sha(data), 'summary': result['summary']}))


if __name__ == '__main__':
    main()
