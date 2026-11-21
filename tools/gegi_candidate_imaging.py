"""Measured two-strip fits/maps from a completed candidate archive; no simulation.

ADC contexts are read one at a time. The minimal qualified-trigger census includes
saved clean-single/guard summaries; these never receive invented waveforms.
"""
from __future__ import annotations
import argparse
from collections import Counter
from contextlib import closing
import gzip
import hashlib
import json
import math
from pathlib import Path
import platform
import time
import zlib

import numpy as np
import scipy
import gegi_candidate_storage as storage
import gegi_continuous_plane as plane
import gegi_digital_readout as digital
import gegi_joint_calibration as calibration
import gegi_joint_two_site as joint
from gegi_joint_two_site import SAMPLE_NS, fit_pairing
import gegi_source_library as library
import scenario_workflow as W

KIND = 'gegi_candidate_measured_imaging_v1'
QUALIFIED_SUMMARIES = {'qualified_single_strip_pair', 'guard_only_collection'}


def _bound(binding):
    path = W.safe_path(W.ROOT, binding['ref'])
    W.require(W.sha(path) == binding['sha256'], 'Saved analysis input changed: ' + binding['ref'])
    return path


def _request_chain(directory, report):
    """Read saved admissions, without comparing old producers to current source."""
    original = report['identity']; requests = {}; receipts = []; seen = set()
    def request(path, identity):
        digest = W.sha(path)
        W.require(digest == identity['native_request_sha256'], 'Native request identity changed')
        requests[digest] = W.read(path)
    request(directory/'native-request.json', original)
    def visit(identity, path, digest):
        W.require(digest not in seen and W.sha(path) == digest, 'Invalid continuation receipt chain')
        seen.add(digest); record = W.read(path)
        W.require(record['new_identity'] == identity and
                  record.get('original_identity', record['old_identity']) == original,
                  'Continuation does not retain the original acquisition identity')
        for key, value in record.items():
            if key.endswith('_binding'): _bound(value)
        receipts.append({'file': path.name, 'sha256': digest, 'kind': record['kind']})
        if 'new_request_binding' in record:
            request(_bound(record['new_request_binding']), identity)
        previous = record['old_identity']; kind = record['kind']
        if kind == 'gegi_transport_link_continuation_v1':
            binding = record['phase2_receipt_binding']
        elif kind == 'gegi_stream_id_continuation_v1':
            binding = record['phase1_receipt_binding']
        elif kind == 'gegi_native_only_continuation_v1':
            W.require(previous == original, 'Native-only predecessor identity changed')
            proof = W.read(_bound(record['proof_binding']))
            W.require(proof['status'] == 'passed_exact' and all(proof[key] is True for key in
                      ('all34_float64_native_equal', 'endpoint_records_equal', 'status_equal', 'truth_edep_equal')),
                      'Native-only equivalence proof is unavailable')
            return
        else:
            raise ValueError('Unsupported saved acquisition continuation: ' + kind)
        visit(previous, _bound(binding), binding['sha256'])
    execution = report.get('execution_provenance')
    if execution and execution.get('continuation_receipt'):
        binding = execution['continuation_receipt']
        visit(execution['active_producer_identity'], W.safe_path(directory, binding['path']), binding['sha256'])
        W.require(execution['active_producer_identity']['native_request_sha256'] in requests,
                  'Active native request is absent from its saved continuation chain')
    elif execution:
        W.require(execution['active_producer_identity'] == original, 'Unrecorded producer change')
    physical = lambda req: {key: value for key, value in req.items()
                           if key not in ('source_sha256', 'response_mode', 'event_id_policy')}
    baseline = next(iter(requests.values()))
    W.require(all(physical(req) == physical(baseline) for req in requests.values()),
              'Saved native phases changed the detector, fields, numerics or nominal count')
    return baseline, {'native_request_sha256': list(requests), 'continuation_receipts': receipts}


def _admit_calibration(request, manifest, channels):
    identity = manifest['identity']; cache = request['field_cache']
    # Reuse the existing exact-cache admission. The fresh-solve precision setting
    # in numerics is deliberately not interpreted as serialized-cache precision.
    W.require(request['model_sha256'] == library._ADMITTED_MODEL_SHA256 and
              cache['model_sha256'] == request['model_sha256'] and
              cache['sha256'] == library._ADMITTED_CACHE_SHA256,
              'Actual saved field precision is not admitted for this model/cache; retain a native field-identity receipt first')
    expected = {'model_sha256': request['model_sha256'], 'field_cache_sha256': cache['sha256'],
                'field_precision_bits': 32, 'digital_profile_sha256': digital.PROFILE_SHA256,
                'digital_timing_sha256': digital.TIMING_SHA256}
    W.require(identity == expected and manifest['channels'] == channels,
              'Candidate acquisition and center calibration differ in fields, precision, channels or digital settings')
    return {'kind': 'gegi_exact_saved_cache_calibration_admission_v1', 'identity': expected,
            'basis': 'Existing gegi_source_library exact model/cache Float32 admission; saved requests remain hash-bound.',
            'admission_source_sha256': W.sha(Path(library.__file__))}


def voltage_window(record, excluded_intervals):
    """Extract original 34 x 29 signed ADC samples, -80..480 ns from trigger."""
    context = record['context']; codes = context['adc_codes']; period = context['sample_period_ns']
    W.require(context['contact_ids'] == list(digital.CONTACT_IDS) and period == digital._DT and
              context['volts_per_code'] == digital._LSB_V and
              context['digital_profile_sha256'] == digital.PROFILE_SHA256 and
              context['digital_timing_sha256'] == digital.TIMING_SHA256 and
              codes.dtype == np.dtype('<i2') and codes.shape == (34, context['stop_sample_index']-context['first_sample_index']),
              'Saved candidate ADC layout or digital identity differs')
    trigger = record['trigger_time_ns']; phase = context['adc_phase_ns']
    index = round((trigger-phase)/period)
    W.require(index*period+phase == trigger, 'Saved trigger is off its original ADC clock')
    start = index + int(SAMPLE_NS[0]/period); stop = start + len(SAMPLE_NS)
    if start < 0 or stop > context['acquisition_live_samples']: return None, 'outside_live_time'
    if any(lo <= trigger+SAMPLE_NS[-1] and trigger+SAMPLE_NS[0] < hi for lo, hi in excluded_intervals):
        return None, 'excluded_history'
    left = start-context['first_sample_index']; right = stop-context['first_sample_index']
    W.require(0 <= left < right <= codes.shape[1], 'Retained candidate context does not cover the original fitting window')
    return codes[:, left:right] * context['volts_per_code'], 'captured'


def _checkpoint(db, identity):
    reader = object.__new__(storage.CandidateStore); reader.db = db
    reader._identity_sha256 = storage._digest(storage.encoded(identity))
    return reader.load_checkpoint()


def run(report_path, calibration_path, *, z_mm, extent_mm=120., step_mm=4., sigma_deg=5.,
        plane_prior=plane.DEFAULT_PLANE_PRIOR, trigger_ids=None, max_two_strip=None, compatibility=False,
        position_model='center', lateral_calibration_path=None, include_shared_strip=False, shared_trigger_ids=None):
    """Return one map/fit/provenance document. Optional subsets retain unresolved mass."""
    begun = time.perf_counter(); report_path = Path(report_path); calibration_path = Path(calibration_path)
    raw = report_path.read_bytes(); report = json.loads(raw); directory = report_path.parent
    W.require(report.get('kind') == 'gegi_candidate_acquisition_v1' and report.get('status') == 'completed',
              'Select a completed candidate acquisition report')
    W.require(report.get('verification', {}).get('status') == 'verified_exact',
              'Complete saved-candidate verification before measured reconstruction')
    W.require(max_two_strip is None or type(max_two_strip) is int and max_two_strip > 0,
              'The optional two-strip analysis subset must be a positive integer')
    W.require(type(compatibility) is bool, 'Select whether to record all-electrode fit diagnostics')
    W.require(type(include_shared_strip) is bool and (include_shared_strip or shared_trigger_ids is None),
              'Select shared-strip imaging before choosing original shared-strip trigger IDs')
    W.require(position_model in ('center', 'lateral') and (lateral_calibration_path is not None) == (position_model == 'lateral'),
              'The lateral position model requires its separate lateral calibration and the matching center archive')
    fit_options = {'compatibility': True} if compatibility else {}
    requested_ids = None if trigger_ids is None else set(trigger_ids)
    W.require(requested_ids is None or requested_ids and all(type(tid) is int and tid > 0 for tid in requested_ids),
              'Select original positive trigger IDs')
    database = W.safe_path(directory, storage.ARCHIVE_NAME)
    database_sha = W.sha(database)
    W.require(database_sha == report['artifacts'][storage.ARCHIVE_NAME]['sha256'], 'Completed candidate archive changed')
    request, native_provenance = _request_chain(directory, report)
    manifest, templates, calibration_content_sha, calibration_archive_sha = calibration.load(calibration_path)
    lateral_bundle = None
    if lateral_calibration_path is not None:
        lateral_calibration_path = Path(lateral_calibration_path)
        lateral, templates, lateral_content_sha, lateral_archive_sha = calibration.load_lateral(
            lateral_calibration_path, manifest, templates, calibration_content_sha, calibration_archive_sha)
        lateral_bundle = {'archive_sha256': lateral_archive_sha, 'content_sha256': lateral_content_sha,
                          'coverage_cells': lateral['supported_cells'], 'identity': lateral['identity']}
        fit_options['include_partial_lateral'] = True
    summary = storage.store_summary(database)
    W.require(summary['status'] == 'completed' and summary['metadata']['identity'] == report['identity'] and
              all(summary['completion'][key] == value for key, value in report['storage_counts'].items()),
              'Completed report and candidate census differ')
    cards = []; fits = []; original_ids = []; joins = []; reasons = Counter(); fit_status = Counter(); windows = Counter()
    record_chain = hashlib.sha256(); selected_ids = []; all_two_strip = 0; candidate_count = 0; fit_seconds = 0.
    with closing(storage._open_readonly(database)) as db:
        state = _checkpoint(db, report['identity'])
        admission = _admit_calibration(request, manifest, state['channels'])
        W.require(state.get('execution_provenance') == report.get('execution_provenance'), 'Final execution provenance changed')
        cursor = db.execute('SELECT trigger_id,record,adc_sha256,record_sha256 FROM triggers ORDER BY trigger_id')
        for trigger_id, body, adc_sha, record_sha in cursor:
            record = json.loads(zlib.decompress(body))
            W.require(record['trigger_id'] == trigger_id and storage._record_digest(record, adc_sha) == record_sha,
                      'Candidate scalar/context record changed')
            record_chain.update(bytes.fromhex(record_sha)); reasons[record['reason']] += 1
            kept = record['decision'] == 'candidate'; candidate_count += int(kept)
            if not kept and record['reason'] not in QUALIFIED_SUMMARIES: continue
            card = record['card'] if kept else record['summary']
            minimal = {'trigger_time_ns': record['trigger_time_ns'], 'energy_keV': card['energy_keV']}
            if kept and card.get('two_strip_pairings') is not None:
                all_two_strip += 1; event = card['two_strip_pairings']; minimal['two_strip_pairings'] = event
                selected = ((requested_ids is None or trigger_id in requested_ids) and
                            (max_two_strip is None or len(selected_ids) < max_two_strip))
                volts = None; window_status = 'analysis_subset_not_selected'
                if selected:
                    selected_ids.append(trigger_id)
                    loaded = storage.load_candidate(database, trigger_id)
                    W.require(loaded['card'] == card and loaded['identities'] == record['identities'], 'Candidate changed during analysis')
                    volts, window_status = voltage_window(loaded, report['excluded_intervals_ns'])
                windows[window_status] += 1
                fitted = {'ordinal': all_two_strip, 'time_ns': record['trigger_time_ns'],
                          'window_status': window_status, 'flags': event['flags'], 'pairings': []}
                for pairing in event['pairings']:
                    if not pairing['energy_compatible']: result = {'status': 'energy_incompatible'}
                    elif volts is None: result = {'status': window_status}
                    else:
                        started = time.perf_counter()
                        result = fit_pairing(pairing, event['collectors'], templates, manifest['feature_scales'],
                                             local_adc_volts=volts, **fit_options)
                        fit_seconds += time.perf_counter()-started
                    fit_status[result['status']] += 1
                    cells = [[site['x_contact_id'], site['y_contact_id']] for site in pairing['sites']]
                    descriptor = {'index': pairing['index'], 'energy_compatible': pairing['energy_compatible'],
                                  'cells': cells, 'compton_orders': pairing['compton_orders'], 'fit': result}
                    if lateral_bundle is not None:
                        descriptor['lateral_calibration_support'] = [cell in lateral_bundle['coverage_cells'] for cell in cells]
                    fitted['pairings'].append(descriptor)
                fits.append(fitted)
            cards.append(minimal); original_ids.append(trigger_id); joins.append(record['identities'])
    W.require(record_chain.hexdigest() == summary['completion']['records_sha256'] and
              len(cards) == report['counts']['qualified_triggers'] and
              sum(card['energy_keV'] is not None for card in cards) == report['counts']['qualified_energies'] and
              candidate_count == report['storage_counts']['saved_candidates'] and
              dict(reasons) == report['storage_counts']['selection_reason_counts'], 'Measured qualified/rejected populations do not reconcile')
    W.require(requested_ids is None or requested_ids <= set(selected_ids), 'Requested trigger ID is not an eligible selected two-strip candidate')
    live = report['live_time_ns']; mask = report['excluded_intervals_ns']
    W.require(all(0 <= lo < hi <= live and (i == 0 or mask[i-1][1] < lo) for i, (lo, hi) in enumerate(mask)),
              'Acquisition unknown-history intervals are not a disjoint live-time mask')
    acquisition = {'triggers': cards, 'counts': report['counts'], 'exposure': {'clock_live_time_ns': live,
        'qualified_adc_live_time_ns': live-math.fsum(hi-lo for lo, hi in mask)}}
    cells = {tuple(cell) for row in fits for pair in row['pairings'] if pair['energy_compatible'] for cell in pair['cells']}
    bundle = {'archive_sha256': calibration_archive_sha, 'content_sha256': calibration_content_sha,
              'identity': manifest['identity'], 'requested_cells': sorted(cells),
              'calibrated_cells': sorted(cells & templates.keys()), 'missing_cells': sorted(cells - templates.keys())}
    fit_receipt = {'kind': 'gegi_candidate_measured_waveform_fits_v1', 'two_strip_triggers': all_two_strip,
                   'calibration_bundle': bundle, 'candidates': fits}
    if lateral_bundle is not None:
        fit_receipt.update(position_model=position_model, lateral_calibration_bundle=lateral_bundle)
    settings = dict(z_mm=z_mm, extent_mm=extent_mm, step_mm=step_mm, sigma_deg=sigma_deg, plane_prior=plane_prior)
    result = plane.reconstruct(acquisition, fit_receipt, **settings)
    for ledger in result['triggers']:
        index = ledger['trigger_index']-1
        ledger.update(original_trigger_id=original_ids[index], diagnostic_input_group_ordinals=joins[index])
    if include_shared_strip:
        import gegi_candidate_shared_imaging as shared_imaging

        shared_plane = shared_imaging.reconstruct(acquisition, report, database, manifest, templates, shared_trigger_ids,
                                                  **settings)
        W.require(not {row['original_trigger_id'] for row in result['triggers']}.intersection(
            row['original_trigger_id'] for row in shared_plane['triggers']), 'Original two-by-two and shared-strip IDs overlap')
        result['shared_strip_plane'] = shared_plane
    W.require(W.sha(database) == database_sha and report_path.read_bytes() == raw and
              W.sha(calibration_path) == calibration_archive_sha and (lateral_bundle is None or
              W.sha(lateral_calibration_path) == lateral_bundle['archive_sha256']),
              'Completed acquisition or calibration changed during analysis')
    result.update(input_sha256={'acquisition': hashlib.sha256(raw).hexdigest(), 'candidate_store': database_sha,
                               'calibration': calibration_archive_sha}, calibration_bundle=bundle, fit_receipt=fit_receipt,
        candidate_analysis={'kind': KIND, 'scope': 'all_two_strip_candidates' if requested_ids is None and max_two_strip is None else 'explicit_analysis_subset',
            'selected_original_trigger_ids': selected_ids, 'max_two_strip': max_two_strip,
            'requested_original_trigger_ids': None if requested_ids is None else sorted(requested_ids),
            'saved_candidates': candidate_count, 'two_strip_candidates': all_two_strip,
            'retained_candidates_outside_two_strip_scope': candidate_count-all_two_strip,
            'window_status_counts': dict(windows), 'pair_fit_status_counts': dict(fit_status),
            'qualified_counts': report['counts'], 'storage_counts': report['storage_counts'],
            'excluded_intervals_ns': mask, 'source_census': report['source'], 'selection_policy': report['selection_policy'],
            'original_id_policy': 'trigger_index is a qualified-census position; original_trigger_id is the immutable saved readout ID.',
            'diagnostic_join_policy': 'Ordinals refer to original archive input_groups; truth joins never select pairings or fit positions.',
            'streaming_adc_digest': report['readout'].get('adc_digest'), 'native_provenance': native_provenance,
            'saved_readout_verification': report['verification'],
            'calibration_admission': admission, 'fit_seconds': fit_seconds, 'elapsed_seconds': time.perf_counter()-begun,
            'software': {'python': platform.python_version(), 'numpy': np.__version__, 'scipy': scipy.__version__},
            'source_sha256': {Path(module.__file__).name: W.sha(Path(module.__file__)) for module in
                              (storage, plane, calibration, joint, digital, library)} | {Path(__file__).name: W.sha(Path(__file__))}})
    if compatibility:
        result['candidate_analysis']['compatibility'] = True
    if include_shared_strip:
        result['candidate_analysis']['include_shared_strip'] = True
        shared = shared_imaging.shared
        result['candidate_analysis']['source_sha256'].update(
            {Path(module.__file__).name: W.sha(Path(module.__file__)) for module in
             (shared_imaging, shared, shared.topology, shared.dual, shared.compton, shared_imaging.pairs)})
    if lateral_bundle is not None:
        result['input_sha256']['lateral_calibration'] = lateral_bundle['archive_sha256']
        captured = [pair for row in result['triggers'] if row['adc_window_status'] == 'captured' for pair in row['pairings']]
        result['candidate_analysis'].update(position_model=position_model, lateral_calibration=lateral_bundle,
            position_pair_counts=dict(Counter(pair['waveform_position_model'] for pair in captured
                                              if pair['waveform_position_model'] is not None)),
            position_calibration_support_pair_counts=dict(Counter(sum(pair['lateral_calibration_support']) for pair in captured)),
            position_fallback_counts=dict(Counter(pair['lateral_fallback_reason'] for pair in captured
                if pair['lateral_fallback_reason'] is not None)))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True); parser.add_argument('--calibration', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True); parser.add_argument('--plane-z-mm', type=float, required=True)
    parser.add_argument('--extent-mm', type=float, default=120.); parser.add_argument('--step-mm', type=float, default=4.)
    parser.add_argument('--sigma-deg', type=float, default=5.); parser.add_argument('--plane-prior', choices=plane.PLANE_PRIORS, default=plane.DEFAULT_PLANE_PRIOR)
    parser.add_argument('--trigger-id', type=int, action='append'); parser.add_argument('--max-two-strip', type=int)
    parser.add_argument('--compatibility', action='store_true',
                        help='Save all-electrode ADC residuals and sampled fit alternatives for the existing waveform fit')
    parser.add_argument('--position-model', choices=('center', 'lateral'), default='center')
    parser.add_argument('--lateral-calibration', type=Path)
    parser.add_argument('--include-shared-strip', action='store_true',
                        help='Add a separate conditional plane view for 1×2 and 2×1 strip candidates')
    parser.add_argument('--shared-trigger-id', type=int, action='append',
                        help='Select an original shared-strip trigger for a partial companion view, repeatable')
    args = parser.parse_args(); W.safe_path(args.output.absolute().parent, args.output.name)
    W.require(not args.output.exists(), 'Choose a new analysis output; existing evidence is preserved')
    result = run(args.report, args.calibration, z_mm=args.plane_z_mm, extent_mm=args.extent_mm, step_mm=args.step_mm,
                 sigma_deg=args.sigma_deg, plane_prior=args.plane_prior, trigger_ids=args.trigger_id,
                 max_two_strip=args.max_two_strip, compatibility=args.compatibility, position_model=args.position_model,
                 lateral_calibration_path=args.lateral_calibration, include_shared_strip=args.include_shared_strip,
                 shared_trigger_ids=args.shared_trigger_id)
    data = gzip.compress(W.encoded(result), mtime=0)
    with args.output.open('xb') as handle: handle.write(data)
    print(json.dumps({'output': str(args.output), 'scope': result['candidate_analysis']['scope'],
                      'selected': len(result['candidate_analysis']['selected_original_trigger_ids']),
                      'two_strip_candidates': result['candidate_analysis']['two_strip_candidates'],
                      'projected_mass': result['layers']['all']['projected_mass']}))


if __name__ == '__main__': main()
