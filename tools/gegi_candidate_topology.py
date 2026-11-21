"""Evaluate alternate strip-energy topologies from an existing GeGI map and ADC archive."""

import argparse
from collections import Counter
import gzip
import hashlib
import json
import math
from pathlib import Path
import platform
from time import perf_counter

import numpy as np
import scipy

import gegi_adc_topology as topology
import gegi_candidate_imaging as imaging
import gegi_candidate_records as records
import gegi_candidate_shared_topology as shared
import gegi_candidate_storage as storage
from gegi_event_store import encoded
import gegi_incident_hypotheses as incident
import gegi_joint_calibration as calibration
import gegi_joint_two_site as joint
import scenario_workflow as workflow


KIND = 'gegi_candidate_adc_topology_v1'


def population(saved, joined, trigger_ids):
    """Keep measured-trigger order and reject unknown or duplicate requested identities."""
    rows = list(zip(saved['triggers'], saved['fit_receipt']['candidates'], joined, strict=True))
    available = [row['original_trigger_id'] for row, _, _ in rows]
    if trigger_ids is None:
        return rows
    requested = set(trigger_ids)
    if (not requested or len(requested) != len(trigger_ids) or any(type(value) is not int or value <= 0 for value in requested)
            or not requested <= set(available)):
        raise ValueError('Select distinct original trigger IDs that belong to this complete measured two-strip map')
    return [triple for triple in rows if triple[0]['original_trigger_id'] in requested]


def baseline_scores(event, fitted, templates, volts, incident_energies_keV=()):
    result = []
    for old, pairing in zip(fitted['pairings'], event['pairings'], strict=True):
        if old['index'] != pairing['index'] or old['energy_compatible'] != pairing['energy_compatible']:
            raise ValueError('Saved pairing differs from the original ADC card')
        wrapper = old['fit']
        score = {'pairing_index': old['index'], 'cells': old['cells'],
                 'measured_site_energies_keV': [site['energy_keV'] for site in pairing['sites']],
                 'energy_compatible': pairing['energy_compatible'], 'fit_status': wrapper['status']}
        if incident_energies_keV:
            unavailable = None if pairing['energy_compatible'] else 'energy_incompatible'
            score['incident_line_diagnostics'] = incident.evaluate(
                score['measured_site_energies_keV'], incident_energies_keV, unavailable=unavailable)
        center = wrapper.get('fits', {}).get('waveform', {}).get('center')
        if center is not None and volts is not None:
            checked = joint.evaluate_waveform_compatibility(pairing, event['collectors'], templates, center,
                                                             wrapper['contacts'], local_adc_volts=volts)
            adc = checked['adc_rms_codes']
            score.update(center_optimizer_success=center['optimizer_success'],
                         center_positions_mm=center['positions_mm'],
                         center_per_contact_adc_rms_codes=adc,
                         center_global_adc_rms_codes=math.sqrt(math.fsum(v*v for v in adc)/len(adc)),
                         collector_timing=checked['collector_timing'],
                         parameter_boundaries=checked['parameter_boundaries'])
        result.append(score)
    return result


def near_ties(baseline, alternative):
    choices = [{'kind': 'saved_center_pairing', 'index': row['pairing_index'], 'adc_rms_codes': row['center_global_adc_rms_codes']}
               for row in baseline if row.get('center_optimizer_success')]
    choices.extend({'kind': row['kind'], 'index': i, 'adc_rms_codes': row['global_adc_rms_codes']}
                   for i, row in enumerate(alternative) if row['status'] == 'scored')
    if not choices:
        return []
    best = min(row['adc_rms_codes'] for row in choices)
    return [row for row in choices if row['adc_rms_codes'] - best <= topology.NEAR_TIE_ADC_CODES]


def analyze(saved, fitted, joined, original, report, templates, incident_energies_keV=()):
    trigger_id = saved['original_trigger_id']
    card = original['card']
    if (original['trigger_id'] != trigger_id or original['trigger_time_ns'] != fitted['time_ns']
            or original['trigger_time_ns'] != saved['trigger_time_ns'] or card['energy_keV'] != saved['energy_keV']
            or joined['original_trigger_id'] != trigger_id or original['decision'] != 'candidate'):
        raise ValueError('Original acquisition trigger and fitted row differ')
    projected, unresolved = (saved[key] for key in ('projected_mass', 'unresolved_mass'))
    if min(projected, unresolved) < 0 or not math.isclose(projected + unresolved, 1., abs_tol=1e-12, rel_tol=0):
        raise ValueError(f'The original nominal trigger weight does not reconcile for {trigger_id}')
    volts, status = imaging.voltage_window(original, report['excluded_intervals_ns'])
    if status != fitted['window_status']:
        raise ValueError(f'The original ADC window status changed for {trigger_id}')
    event = card['two_strip_pairings']
    baseline = baseline_scores(event, fitted, templates, volts, incident_energies_keV)
    alternatives = topology.scan_allocations(event['collectors'], volts, templates) if volts is not None else None
    ties = near_ties(baseline, alternatives['hypotheses']) if alternatives is not None else []
    return {'original_trigger_id': trigger_id, 'original_trigger_index': saved['trigger_index'],
            'two_strip_ordinal': saved['two_strip_ordinal'], 'trigger_time_ns': saved['trigger_time_ns'],
            'archive_record_sha256': joined['archive_record_sha256'], 'archive_adc_sha256': joined['archive_adc_sha256'],
            'adc_window_status': status, 'original_measured_energy_keV': card['energy_keV'],
            'original_face_totals_keV': [card['x_sum_keV'], card['y_sum_keV']],
            'original_projected_mass': projected, 'original_unresolved_mass': unresolved,
            'original_projected_pairings_and_orders': saved['pairings'],
            'saved_pairings_center_diagnostics': baseline, 'alternative_fit_diagnostics': alternatives,
            'sampled_compatibility_near_ties': ties}


def checked_inputs(report_path, center_path):
    report_raw = report_path.read_bytes()
    report = json.loads(report_raw)
    if (report.get('kind') != 'gegi_candidate_acquisition_v1' or report.get('status') != 'completed'
            or report.get('verification', {}).get('status') != 'verified_exact'):
        raise ValueError('Topology diagnostics require a completed, exactly verified candidate acquisition')
    database = workflow.safe_path(report_path.parent, storage.ARCHIVE_NAME)
    db_hash = workflow.sha(database)
    if db_hash != report['artifacts'][storage.ARCHIVE_NAME]['sha256']:
        raise ValueError('Candidate archive differs from the verified acquisition binding')
    manifest, templates, content_hash, center_hash = calibration.load(center_path)
    expected = {'acquisition': hashlib.sha256(report_raw).hexdigest(), 'candidate_store': db_hash, 'calibration': center_hash}
    return report, database, manifest, templates, content_hash, expected


def require_input_hashes(report_path, database, center_path, expected):
    paths = {'acquisition': report_path, 'candidate_store': database, 'calibration': center_path}
    if any(workflow.sha(path) != expected[key] for key, path in paths.items()):
        raise ValueError('An immutable candidate analysis input changed while generating diagnostics')


def provenance(start, sources):
    return {'contact_ids': list(joint.digital.CONTACT_IDS), 'samples_relative_to_trigger_ns': joint.SAMPLE_NS.tolist(),
            'adc_lsb_V': joint.digital._LSB_V, 'weighted_fit_noise_scale_V': joint.NOISE_RMS_V,
            'software': {'python': platform.python_version(), 'numpy': np.__version__, 'scipy': scipy.__version__},
            'source_sha256': {Path(m.__file__).name: workflow.sha(Path(m.__file__))
                              for m in (topology, imaging, storage, calibration, joint, *sources)}
                             | {Path(__file__).name: workflow.sha(Path(__file__))},
            'elapsed_seconds': perf_counter()-start}


def run(report_path, map_path, center_path, *, trigger_ids=None, incident_energies_keV=()):
    start = perf_counter()
    line_configuration = incident.configuration(incident_energies_keV)
    lines = line_configuration['incident_energies_keV']
    report_path, map_path, center_path = map(Path, (report_path, map_path, center_path))
    report, database, manifest, templates, content_hash, expected = checked_inputs(report_path, center_path)
    map_raw = map_path.read_bytes()
    saved = json.loads(gzip.decompress(map_raw) if map_path.suffix == '.gz' else map_raw)
    if (any(saved.get('input_sha256', {}).get(k) != value for k, value in expected.items()) or
            saved.get('calibration_bundle', {}).get('content_sha256') != content_hash or
            saved.get('calibration_bundle', {}).get('identity') != manifest['identity']):
        raise ValueError('The saved full map, candidate archive or center calibration bindings differ')
    for key in ('qualified_triggers', 'qualified_energies', 'triggers_without_energy'):
        if saved['selection'][key] != report['counts'][key]:
            raise ValueError('The saved map and completed acquisition use different trigger populations')
    _, joined = records.saved_events(saved, database)
    chosen = population(saved, joined, trigger_ids)
    rows = []
    for trigger, fitted, matched in chosen:
        original = storage.load_candidate(database, trigger['original_trigger_id'])
        rows.append(analyze(trigger, fitted, matched, original, report, templates, lines))
    require_input_hashes(report_path, database, center_path, expected)
    if map_path.read_bytes() != map_raw:
        raise ValueError('The immutable candidate map changed while generating diagnostics')
    hypothesis_status = Counter((hyp['kind'], hyp['status']) for row in rows
                                if row['alternative_fit_diagnostics'] is not None
                                for hyp in row['alternative_fit_diagnostics']['hypotheses'])
    return {'kind': KIND, 'status': 'completed',
            'input_sha256': expected | {'saved_map': hashlib.sha256(map_raw).hexdigest()},
            'scope': 'all_two_strip_candidates' if trigger_ids is None else 'explicit_original_trigger_ids',
            'complete_saved_map_population': saved['selection'],
            'analyzed_original_trigger_ids': [row['original_trigger_id'] for row in rows],
            'omitted_original_trigger_count': len(joined) - len(rows),
            'analyzed_original_projected_mass': math.fsum(row['original_projected_mass'] for row in rows),
            'analyzed_original_unresolved_mass': math.fsum(row['original_unresolved_mass'] for row in rows),
            'adc_window_status_counts': dict(Counter(row['adc_window_status'] for row in rows)),
            'alternative_status_counts': [{'kind': k, 'status': s, 'count': v} for (k, s), v in sorted(hypothesis_status.items())],
            'near_tie_rms_increment_adc_codes': topology.NEAR_TIE_ADC_CODES,
            'method': 'Alternate sparse, weak-endpoint and continuous allocations use the original strip tolerances, full ADC windows '
                      'and calibrated center responses. Each modeled corner has its own depth and shares one onset.',
            'interpretation': 'Residuals and optimizer ties describe sampled model compatibility. The trigger energy, existing candidate '
                              'orders and nominal projected and unresolved weights are carried verbatim. Alternate fits have no imaging weight. '
                              'The modeled totals are separately reported because solving within strip tolerances can change them slightly. '
                              'A collecting-strip allocation cannot establish the number or ordering of photon interactions.',
            **({'incident_line_configuration': line_configuration} if lines else {}),
            **provenance(start, (records, incident) if lines else (records,)), 'triggers': rows}


def shared_incident_diagnostics(result, energies):
    for row in result['triggers']:
        allocation = row['conditional_energy_allocation']
        unavailable = None if allocation['status'] == 'energy_qualified' else allocation['status']
        row['incident_line_diagnostics'] = incident.evaluate(
            allocation.get('site_energies_keV'), energies, unavailable=unavailable)


def run_shared(report_path, center_path, *, trigger_ids=None, incident_energies_keV=()):
    start = perf_counter()
    line_configuration = incident.configuration(incident_energies_keV)
    lines = line_configuration['incident_energies_keV']
    report_path, center_path = map(Path, (report_path, center_path))
    report, database, manifest, templates, content_hash, expected = checked_inputs(report_path, center_path)
    result = shared.run(report, database, manifest, templates, trigger_ids)
    if lines:
        shared_incident_diagnostics(result, lines)
    require_input_hashes(report_path, database, center_path, expected)
    return {'kind': 'gegi_candidate_shared_strip_topology_v1', 'status': 'completed',
            'input_sha256': expected, 'center_calibration_content_sha256': content_hash,
            'scope': 'all_shared_strip_candidates' if trigger_ids is None else 'explicit_original_shared_strip_ids',
            'original_readout_counts': report['counts'], 'original_retention_counts': report['storage_counts'],
            'method': 'Use the original qualified face-average total and measured ratios on the two separate strips. '
                      'Two point responses share one onset and add before comparing the all-electrode ADC window. The shared strip '
                      'has one CFD crossing at its observed plateau level.',
            'interpretation': 'Sites and possible orders describe one conditional model. Physical interaction multiplicity and '
                              'chronology remain unidentified. Shared-strip hypotheses are outside the original two-by-two projection.',
            **({'incident_line_configuration': line_configuration} if lines else {}),
            **provenance(start, (shared, incident) if lines else (shared,)), **result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--acquisition', type=Path, required=True, help='Completed candidate-acquisition.json')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--map', type=Path, help='Full saved two-by-two candidate imaging result and fit receipt')
    mode.add_argument('--shared-strip', action='store_true', help='Analyze measured 1×2 or 2×1 cases directly from the completed archive')
    parser.add_argument('--calibration', type=Path, required=True, help='Matching center-template archive')
    parser.add_argument('--output', type=Path, required=True, help='New diagnostics .json.gz file')
    parser.add_argument('--incident-energy-keV', dest='incident_energies_keV', action='append', type=float, default=[],
                        help='Optional incident photon line in keV for the two-cell kinematic checks. Repeat for additional lines.')
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--trigger-id', type=int, action='append', help='Optional original trigger ID, repeatable')
    choice.add_argument('--all-two-strip', action='store_true', help='Process all original two-by-two triggers in the complete map')
    choice.add_argument('--all-shared-strip', action='store_true', help='Process all original 1×2 and 2×1 candidates')
    args = parser.parse_args()
    if args.output.exists() or not args.output.name.endswith('.json.gz'):
        parser.error('Choose a new .json.gz output path')
    if (args.all_two_strip and args.shared_strip) or (args.all_shared_strip and args.map is not None):
        parser.error('Use --all-shared-strip with --shared-strip or --all-two-strip with --map')
    options = {'trigger_ids': args.trigger_id, 'incident_energies_keV': args.incident_energies_keV}
    if args.shared_strip:
        report = run_shared(args.acquisition, args.calibration, **options)
    else:
        report = run(args.acquisition, args.map, args.calibration, **options)
    body = encoded(report) + b'\n'
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('xb') as out, gzip.GzipFile(fileobj=out, filename='', mode='wb', mtime=0) as result:
        result.write(body)
    print(json.dumps({'status': report['status'], 'analyzed_triggers': len(report['triggers']),
                      'omitted_triggers': report['omitted_original_trigger_count'],
                      'elapsed_seconds': report['elapsed_seconds']}))


if __name__ == '__main__':
    main()
