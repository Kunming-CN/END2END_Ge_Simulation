"""Build conditional finite-vertex escape cones from a saved GeGI waveform fit."""

import argparse
from collections import Counter
import gzip
import hashlib
import json
import math
from pathlib import Path

import gegi_candidate_records as records
import gegi_candidate_storage as storage
import gegi_continuous_plane as plane
import gegi_incident_hypotheses as hypotheses
import scenario_workflow as workflow


KIND = 'gegi_saved_incident_escape_geometry_v1'


def xyz(point):
    if len(point) != 3 or any(not math.isfinite(component) for component in point):
        raise ValueError('Expected a finite XYZ position in millimeters')
    return list(point)


def escape_geometry(energies, incident_energies, positions, *, unavailable=None):
    """Keep both orders per line, adding a cone only for a supported escape branch."""
    geometry = hypotheses.evaluate(energies, incident_energies, unavailable=unavailable)
    if positions is not None:
        positions = [xyz(position) for position in positions]
        first, second = positions
        separation = math.dist(first, second)
    for line in geometry.get('incident_line_hypotheses', ()):
        for order in line['two_resolved_scatter_escape_orders']:
            order['cone'] = None
            if not order['nominally_admissible']:
                order['geometry_status'] = 'nominal_escape_inadmissible'
            elif positions is None:
                order['geometry_status'] = 'no_saved_waveform_positions'
            elif separation == 0:
                order['geometry_status'] = 'coincident_fitted_positions'
            else:
                i, j = order['site_index_order']
                vertex, next_vertex = positions[i], positions[j]
                order['geometry_status'] = 'conditional_cone_available'
                order['cone'] = {
                    'vertex_mm': vertex, 'second_site_mm': next_vertex,
                    'axis': [(a-b)/separation for a, b in zip(vertex, next_vertex, strict=True)],
                    'half_angle_deg': order['scatters'][0]['scatter_angle_deg'],
                    'site_separation_mm': separation,
                }
    return geometry


def angular_residual_deg(cone, comparison_position_mm):
    """After reconstruction, score geometric angle minus the cone half-angle."""
    ray = [a-b for a, b in zip(xyz(comparison_position_mm), cone['vertex_mm'], strict=True)]
    length = math.hypot(*ray)
    if length == 0:
        raise ValueError('Angular residual is undefined at the cone vertex')
    cosine = math.fsum((a/length)*b for a, b in zip(ray, cone['axis'], strict=True))
    return math.degrees(math.acos(max(-1., min(1., cosine)))) - cone['half_angle_deg']


def pairing_geometry(fitted, original, position_model, lines):
    positions = None
    saved_position_model = None
    if original is not None:
        waveform, model, _ = plane.waveform_position_fit(fitted, position_model)
        if waveform is not None and waveform['optimizer_success']:
            positions = waveform['positions_mm']
            saved_position_model = model
    return {'pair_index': fitted['index'], 'cells': fitted['cells'], 'original_plane_pairing': original,
            'saved_waveform_positions_mm': positions, 'saved_waveform_position_model': saved_position_model,
            'kinematics': escape_geometry(original['site_energies_keV'] if original is not None else None,
                                          lines, positions,
                                          unavailable=None if original is not None else 'energy_incompatible')}


def run(saved_path, archive, incident_energies_keV, *, trigger_ids=None):
    configuration = hypotheses.configuration(incident_energies_keV)
    lines = configuration['incident_energies_keV']
    if not lines:
        raise ValueError('Supply at least one incident energy in keV for an escape cone')
    raw = saved_path.read_bytes()
    hashes = {'saved_plane': hashlib.sha256(raw).hexdigest(), 'candidate_store': workflow.sha(archive)}
    saved = json.loads(gzip.decompress(raw) if saved_path.suffix == '.gz' else raw)
    if saved.get('kind') != plane.PLANE_KIND or hashes['candidate_store'] != saved['input_sha256']['candidate_store']:
        raise ValueError('The saved measured map and candidate archive differ')
    selected = set(trigger_ids) if trigger_ids is not None else None
    available = {row['original_trigger_id'] for row in saved['triggers']}
    if selected is not None and (len(selected) != len(trigger_ids) or not selected or not selected <= available
                                 or any(type(trigger_id) is not int or trigger_id <= 0 for trigger_id in selected)):
        raise ValueError('Select distinct original trigger IDs from the saved map')
    _, bound = records.saved_events(saved, archive, require_full_scope=False)
    receipt = saved['fit_receipt']
    position_model = receipt.get('position_model', 'center')
    triggers = []
    for old, fit, binding in zip(saved['triggers'], receipt['candidates'], bound, strict=True):
        if selected is not None and old['original_trigger_id'] not in selected:
            continue
        original_pairs = {row['index']: row for row in old['pairings']}
        diagnostics = [pairing_geometry(pair, original_pairs.get(pair['index']), position_model, lines)
                       for pair in fit['pairings']]
        triggers.append(dict(old, archive_record_sha256=binding['archive_record_sha256'],
                             archive_adc_sha256=binding['archive_adc_sha256'],
                             conditional_escape_pairings=diagnostics))
    if workflow.sha(archive) != hashes['candidate_store'] or saved_path.read_bytes() != raw:
        raise ValueError('An input changed while generating the conditional cones')
    counts = Counter(order['geometry_status'] for trigger in triggers
                     for pair in trigger['conditional_escape_pairings']
                     for line in pair['kinematics'].get('incident_line_hypotheses', ())
                     for order in line['two_resolved_scatter_escape_orders'])
    sources = (records, storage, plane, hypotheses, workflow)
    return {'kind': KIND, 'input_sha256': hashes, 'incident_line_configuration': configuration,
            'source_sha256': {Path(module.__file__).name: workflow.sha(module.__file__) for module in sources}
                             | {Path(__file__).name: workflow.sha(__file__)},
            'method': 'The cone starts at the saved first waveform position. Its axis points from the second site toward the first. '
                      'The half-angle uses the supplied line and the first measured cell deposit. Escape kinematics are checked at both cells.',
            'interpretation': 'These cones carry no imaging weights. The original projected and unresolved masses and original fit '
                              'orders are retained. Physical multiplicity, order and possible mixtures remain unidentified.',
            'original_selection': saved['selection'], 'analyzed_original_trigger_ids': [row['original_trigger_id'] for row in triggers],
            'omitted_original_trigger_count': len(available)-len(triggers), 'conditional_order_status_counts': dict(counts),
            'triggers': triggers}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--saved-plane', type=Path, required=True)
    parser.add_argument('--archive', type=Path, help='Candidate archive alongside the saved map by default.')
    parser.add_argument('--incident-energy-keV', type=float, action='append', required=True)
    parser.add_argument('--trigger-id', type=int, action='append', help='Repeat for specific original trigger IDs.')
    parser.add_argument('--output', type=Path, required=True, help='New .json.gz report.')
    args = parser.parse_args()
    if args.output.exists() or not args.output.name.endswith('.json.gz'):
        parser.error('Choose a new .json.gz output path')
    archive = args.archive or args.saved_plane.parent/storage.ARCHIVE_NAME
    report = run(args.saved_plane, archive, args.incident_energy_keV, trigger_ids=args.trigger_id)
    payload = gzip.compress(workflow.encoded(report)+b'\n', mtime=0)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('xb') as stream:
        stream.write(payload)
    print(json.dumps({'analyzed_triggers': len(report['triggers']), **report['conditional_order_status_counts']}))


if __name__ == '__main__':
    main()
