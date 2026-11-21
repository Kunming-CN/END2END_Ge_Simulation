"""Publish the saved five-second GeGI reconstruction evidence, without simulations."""

import gzip
from hashlib import sha256
from html import escape
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = Path('results/gegi-five-second-reconstruction')
DATA = DIRECTORY / 'evidence.json'
IMAGE = DIRECTORY / 'source-plane-priors.png'
ENERGY_IMAGE = DIRECTORY / 'peak-energy-offsets.png'
KINEMATICS = DIRECTORY / 'candidate-line-kinematics.json.gz'
PAGE = DIRECTORY / 'index.html'
TITLE = 'GeGI five-second acquisition and reconstruction'
IMAGE_SIZE = (1680, 1020)
BASELINE = ROOT / '.local/gegi-candidate-runs/steady-five-seconds/candidate-imaging.json.gz'
SOURCES = {
    'attribution': ('five-second-edge-attribution.json.gz', '3af3ba2f5e142176efd575544cd0bd8feb4ad8f47701bcc9387e650bf2fc2c56'),
    'position': ('position-compatibility.json', 'da2c8da369b70564508827978c48665565d61859acc55f11764d84cbd6316fea'),
    'partial_lateral': ('partial-lateral-compatibility.json', '2943442b73995841f28d79e3346c7e097d169982e1326552b2a0d010c0ecc006'),
    'truth_control': ('interaction-truth-control.json', '57908dae43d22dbcb5d5a36c1d546bee0ca0b1cc20c8a954fda8eaf9576b5142'),
    'range': ('candidate-range-refined.json', 'f509c9d60e52c951b36855f039f09588c3f79753db40300856ce49d2f25e12a7'),
    'profiled_range': ('candidate-range-profiled.json', '59822b5c5a83ef28fbc7e657ba22a64a94c07923de799c7d61ecf2117f7cdbb8'),
    'uncertainty': ('position-uncertainty-controls.json', '6accb91c8e3076b0b535e5d3a1fea662c951450aab9645b97a1c9ad79fcccd24'),
    'additional_lateral': ('additional-lateral-grid-controls.json', 'd55b7a5a33aac1f2ba9d0633dfd8471758dba81643a1086ebb60a1702640ef3e'),
    'lateral_acceptance': ('candidate-lateral-acceptance.json', '1e4050fd14e11b2ab0455763c654f089f1d52fb4d40f5734c2bfb3b820d38225'),
    'energy_offsets': ('peak-energy-offsets.json.gz', 'f66664f15b2dfa28f78492009b6ec60e24573c09a1b816d5cf55599f105cc0cd'),
    'origins': ('cobalt-top-ten-origin.json', 'bf891c1ecb9c4e544461ae8e2a55d1145daaa70fb929f28f408b9f794b7811dc'),
    'kinematics': ('five-second-line-kinematics.json.gz', 'b77612d1594d93bb194949de03e7be94ad8d72761fc959e10ab533e679726aa2'),
    'angular_tails': ('peak-tail-diagnostic.json', '87e32633dfb8f1756df9bce46f2b4aab365e224e14d2d4ebfd3c3455ed2551c2'),
    'escape_geometry': ('conditional-escape-geometry-controls.json', '43b60e4766f6c7812dc5b3b449b43fabd68a08fd489c2a0f1ecb910cfd6671a6'),
    'exact_kinetics': ('chronological-window-origins/same-event-exact-kinetics.json', '9bca9f3d43f5f7fba86965873fe6a431934b2309953cc8343eb3a51dab4e0cd8'),
    'native_repair': ('native-response-repair.json', '45c8ac5afb77ec9c73949fa529861b46a6869213f75ae17677f6969adc6dc0f8'),
    'boundary_response': ('chronological-window-origins/trigger-12271/boundary-adc-comparison.json', '1aa8643fc3578a1d5bff2803df61dfbf43110a2621cc4562f2ebbd317a91b110'),
    'boundary_grid': ('trigger-12271-native-response/blind-grid/comparison.json', '8095c236c5cc97e8e9b197e0dda37bdbbbc8da8d5b926ac8eaccd47edfdc3537'),
    'boundary_grid_causes': ('trigger-12271-native-response/blind-grid/cause-diagnostic.json', '301e6ad4119e4ce7d832db9141b813d0dd7d25452791afd4d62f780eca6228c2'),
    'boundary_depth': ('trigger-12271-native-response/blind-grid/depth-refinement/comparison.json', '35286f3f8051908280c5e81300288da35a4698a094c2e7f07be7638b7e7c02c9'),
    'boundary_overlap': ('trigger-12271-native-response/blind-grid/depth-refinement/weak-overlap-validation-cli.json', '4d3f2c7ce7bb4160eb1707aa0dd46f82c22b9a06fdddfe42d398de43bf0cd8f3'),
    'boundary_xy_isolated': ('trigger-12271-native-response/blind-grid/depth-refinement/xy-interpolation-validation.json', '1827f655b95bc3442e72a410fd075f02456879d8f1927a32a099d30c04f49ab5'),
    'boundary_xy_overlap': ('trigger-12271-native-response/blind-grid/depth-refinement/xy-overlap-and-original-adc.json', 'b6d421683a266d964dd1e176982588befd89efa91070744fe9b532946ef97dec'),
    'positive_cone_spread': ('position-cone-spread.json', 'eca34f3061c45cacc74dfd852e44634a2042a04daf1a6697ac10b72a929360c1'),
    'negative_cone_spread': ('negative-cone-spread.json', '57618e7916b58a4c826a9a5c2f603d55257e2a2d57808e3d29f73110fdc44d14'),
    'candidate_cone_spread': ('candidate-cone-spread.json.gz', '5d0224b85239ef5e86eb020a106bdb331b53838d38f8588394dcb02eb00bcf53'),
}

CONE_SPREAD_SOURCES = {'positive': 'positive_cone_spread', 'negative': 'negative_cone_spread',
                       'candidates': 'candidate_cone_spread'}
WINDOWS = ('661.657_keV', '1173.23_keV', '1332.49_keV')
PRIORS = ('uniform-area', 'uniform-solid-angle')
CASES = tuple(f'{extent}_mm_{prior}' for extent in (120, 240) for prior in PRIORS)
KINDS = {
    'attribution': 'gegi_five_second_candidate_peak_attribution_v1',
    'position': 'gegi_position_compatibility_v1',
    'partial_lateral': 'gegi_partial_lateral_compatibility_v1',
    'truth_control': 'gegi_matched_interaction_truth_control_v1',
    'range': 'gegi_candidate_conditional_range_v1',
    'profiled_range': 'gegi_candidate_conditional_range_v1',
    'uncertainty': 'gegi_position_empirical_uncertainty_controls_v1',
    'additional_lateral': 'gegi_additional_existing_lateral_grid_controls_v1',
    'lateral_acceptance': 'gegi_full_saved_lateral_acceptance_v1',
    'energy_offsets': 'gegi_original_peak_energy_offsets_v1',
    'origins': 'gegi_ten_cobalt_peak_trigger_origins_v1',
    'kinematics': 'gegi_saved_candidate_kinematic_ledger_v1',
    'angular_tails': 'gegi_original_peak_angular_tail_diagnostic_v1',
    'escape_geometry': 'gegi_nominal_escape_geometry_peak_controls_v1',
    'exact_kinetics': 'gegi_same_event_exact_photon_kinetic_substitutions_v1',
    'native_repair': 'gegi_native_response_repair_summary_v1',
    'boundary_response': 'gegi_trigger_12271_boundary_adc_comparison_v1',
    'boundary_grid': 'gegi_measured_cell_boundary_grid_diagnostic_v1',
    'boundary_grid_causes': 'gegi_boundary_grid_cause_diagnostic_v1',
    'boundary_depth': 'gegi_boundary_depth_refinement_v1',
    'boundary_overlap': 'gegi_fresh_weak_component_overlap_validation_v1',
    'boundary_xy_isolated': 'gegi_frozen_xy_interpolation_validation_v1',
    'boundary_xy_overlap': 'gegi_frozen_xy_overlap_and_original_adc_v1',
    'positive_cone_spread': 'gegi_matched_position_cone_spread_v1',
    'negative_cone_spread': 'gegi_wrong_topology_joint_cone_spread_v1',
    'candidate_cone_spread': 'gegi_five_second_candidate_joint_cone_spread_v1',
}


def read_bound(path, digest):
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != digest:
        raise ValueError(f'The saved reconstruction input changed: {path.name}')
    return json.loads(gzip.decompress(raw) if path.suffix == '.gz' else raw)


def validate_cone_spread(inputs, bindings, selection):
    positive, negative, candidates = (inputs[key] for key in CONE_SPREAD_SOURCES.values())
    model_counts = candidates['summary']['models']
    scope = candidates['scope']
    expected_trials = inputs['position']['controls']['general']['matched_comparisons'][
        'waveform_all_center_to_waveform_all_lateral']['trial_ids']
    if (not positive['grid'] == negative['grid'] == candidates['grid']
            or any(row['input_sha256']['position_uncertainty'] != SOURCES['uncertainty'][1] for row in (positive, negative))
            or positive['input_sha256']['position_compatibility'] != SOURCES['position'][1]
            or negative['input_sha256']['positive_cone_spread'] != SOURCES['positive_cone_spread'][1]
            or [t['trial_id'] for t in positive['trials']] != expected_trials
            or len(negative['negative_controls']) != inputs['uncertainty']['negative_conditions']):
        raise ValueError('Cone-spread controls must share the original control ADC and evaluation grid')
    if (candidates['input_sha256']['center_map'] != bindings['saved_plane']
            or candidates['input_sha256']['candidate_store'] != bindings['candidate_store']
            or candidates['input_sha256']['all34_compatibility'] != SOURCES['position'][1]
            or not scope['two_strip_candidates'] == selection['two_strip_triggers'] == len(candidates['triggers'])
            or scope['saved_candidates'] - scope['retained_candidates_outside_two_strip_scope'] != len(candidates['triggers'])
            or candidates['summary']['pairings'] != sum(len(t['pairings']) for t in candidates['triggers'])
            or model_counts['local_center']['pairings_with_saved_model'] != inputs['position']['candidates']['baseline_waveform_center']['scored_pairings']):
        raise ValueError('Candidate cone spread must preserve the original acquisition and fit census')


def validate_inputs(inputs):
    for key, kind in KINDS.items():
        if inputs[key]['kind'] != kind:
            raise ValueError(f'Unexpected saved reconstruction evidence: {key}')
    attribution, fits = inputs['attribution'], inputs['range']
    position = inputs['position']['candidates']
    partial = inputs['partial_lateral']['retained_candidates']
    bindings = attribution['input_sha256']
    offsets = inputs['energy_offsets']
    if (offsets['input_sha256']['attribution'] != SOURCES['attribution'][1] or
            offsets['input_sha256']['baseline'] != bindings['saved_plane'] or
            offsets['full_map_selection'] != attribution['saved_selection']):
        raise ValueError('Energy offsets must describe the same original measured maps')
    origins = inputs['origins']['science']
    if (inputs['angular_tails']['input_sha256']['saved_map'] != bindings['saved_plane'] or
            inputs['angular_tails']['input_sha256']['photon_origins'] != SOURCES['origins'][1] or
            inputs['escape_geometry']['input_sha256']['original_map'] != bindings['saved_plane'] or
            inputs['escape_geometry']['input_sha256']['origin'] != SOURCES['origins'][1]):
        raise ValueError('Angular diagnostics must describe the same measured map and photon histories')
    ledger = inputs['kinematics']
    if (ledger['input_sha256']['saved_plane'] != bindings['saved_plane'] or
            ledger['input_sha256']['candidate_store'] != bindings['candidate_store'] or
            ledger['input_sha256']['photon_origin_score_only'] != SOURCES['origins'][1] or
            ledger['original_selection'] != attribution['saved_selection']):
        raise ValueError('The incident-line ledger must preserve the original candidate selection')
    if (origins['analysis_input_sha256'] != bindings['saved_plane'] or
            origins['attribution_sha256'] != SOURCES['attribution'][1]):
        raise ValueError('Photon origins must refer to the original measured map and attribution')
    for label, window in origins['windows'].items():
        case = attribution['windows'][label]['cases'][CASES[0]]
        shares = {row['original_trigger_id']: row for row in case['trigger_contributions']}
        expected_ids = case['trigger_concentration']['ranked_top_trigger_ids'][:5]
        if [row['original_trigger_id'] for row in window['triggers']] != expected_ids:
            raise ValueError('Photon origins must cover the original five leading peak contributors')
        for row in window['triggers']:
            original = shares[row['original_trigger_id']]
            if not math.isclose(row['original_peak_cell_share'], original['support']['peak_cell']/case['peak']['mass'],
                                rel_tol=0., abs_tol=1e-12):
                raise ValueError('Photon-origin joins changed the original peak contribution')
    same = {k: bindings[k] for k in ('acquisition', 'candidate_store', 'calibration')}
    if (fits['input_sha256'] != bindings['saved_plane'] or fits['input_bindings'] != same
            or fits['acquisition_selection'] != attribution['saved_selection']
            or fits['status'] != 'complete'
            or any(v['input_sha256'] != dict(same, baseline_fit=bindings['saved_plane']) for v in (position, partial))):
        raise ValueError('Reconstruction data do not share the original five-second acquisition and center fits')
    selection = attribution['saved_selection']
    validate_cone_spread(inputs, bindings, selection)
    source = attribution['saved_source_census']
    fitted = position['baseline_waveform_center']['scored_pairings']
    coverage = position['fitted_pairings_by_lateral_supported_site_count']
    if (selection['clock_live_time_ns'] != 5e9 or
            selection['qualified_energies'] + selection['triggers_without_energy'] != selection['qualified_triggers'] or
            source['initial_parents'] + source['initial_daughter_decays'] != source['transport_primaries'] or
            sum(source[k] for k in ('complete_native_groups', 'unavailable_native_groups', 'delayed_groups_after_acquisition'))
            != source['deposit_groups'] or position['retained_two_strip_triggers'] != selection['two_strip_triggers'] or
            sum(coverage.values()) != fitted or partial['full_candidate_fitted_pairings_by_supported_site_count'] != coverage or
            partial['partial_lateral_refits'] != coverage['1']):
        raise ValueError('Saved acquisition or position census does not reconcile')
    for label in WINDOWS:
        row = attribution['windows'][label]
        ids = [trigger['original_trigger_id'] for trigger in row['original_triggers']]
        if (ids != fits['fits'][label]['selected_original_trigger_ids'] or sorted(set(ids)) != ids or
                len(row['cases']) != len(CASES) or set(row['cases']) != set(CASES)):
            raise ValueError(f'Original {label} trigger selection differs across studies')
        for case in row['cases'].values():
            census = case['census']
            if (census['triggers'] != len(ids) or not math.isclose(census['projected_mass'] + census['unresolved_mass'],
                                                                  len(ids), rel_tol=0., abs_tol=1e-9)):
                raise ValueError(f'Saved projected and unresolved counts differ in {label}')


def plane_maps(attribution, baseline):
    """Derive only alternate-prior presentation arrays from the saved cone orders."""
    import numpy as np
    import gegi_candidate_diagnostic as diagnostic
    import gegi_joint_imaging as imaging

    grid = baseline['grid']
    if (baseline['input_sha256'] != {k: attribution['input_sha256'][k] for k in baseline['input_sha256']}
            or baseline['model']['plane_prior'] != 'uniform-area'
            or (grid['extent_mm'], grid['step_mm'], grid['assumed_z_mm']) != (120., 4., 40.)):
        raise ValueError('Saved projection does not match the requested plane panels')
    ticks, points = imaging.plane_grid(grid['extent_mm'], grid['step_mm'], grid['assumed_z_mm'])
    settings = imaging.ResponseSettings(strip_pitch_mm=baseline['model']['strip_pitch_mm'],
                                        angular_nuisance_sigma_deg=baseline['model']['angular_nuisance_sigma_deg'])
    maps = {}
    for label in WINDOWS:
        window = attribution['windows'][label]
        rows = window['original_triggers']
        events = imaging.prepare_events([
            dict(event_id=row['original_trigger_id'], energy_keV=row['energy_keV'],
                 candidates=[dict(order, prior_weight=order['nominal_mass'])
                             for pair in row['pairings'] for order in pair['orders'] if order['status'] == 'available'])
            for row in rows], settings)
        maps[label] = {}
        for prior in PRIORS:
            per_order, _ = diagnostic.order_matrix(events, rows, points, settings, prior, grid['step_mm'])
            mass = per_order.sum(axis=0).reshape(len(ticks), len(ticks))
            if prior == 'uniform-area':
                original = np.array(baseline['layers'][label]['mass'])
                if not np.allclose(mass, original, rtol=0., atol=1e-12):
                    raise ValueError(f'Cannot reproduce the exact saved display grid: {label}')
                mass = original
            case = window['cases'][f'120_mm_{prior}']
            actual_peak = points[mass.argmax()]
            if (list(actual_peak) != case['peak']['position_mm'] or
                    not math.isclose(float(mass.max()), case['peak']['mass'], rel_tol=0., abs_tol=1e-12) or
                    not math.isclose(float(mass.sum()), case['census']['projected_mass'], rel_tol=0., abs_tol=1e-9)):
                raise ValueError(f'The figure differs from the saved case at {label} / {prior}')
            maps[label][prior] = mass.tolist()
    return {**grid, 'mass_by_window_and_prior': maps}


def source_arm(order, source_mm):
    ray = [a - b for a, b in zip(source_mm, order['vertex_mm'], strict=True)]
    cosine = math.fsum(x*y for x, y in zip(ray, order['axis'], strict=True)) / math.hypot(*ray)
    return math.degrees(math.acos(max(-1., min(1., cosine)))) - order['half_angle_deg']


def compact_cone_spread(inputs):
    out = {'grid': inputs['positive_cone_spread']['grid']}
    for scope, key in CONE_SPREAD_SOURCES.items():
        item = inputs[key]
        bindings = item['input_sha256']
        packet = {k: v for k, v in item.items() if k not in ('grid', 'input_sha256')}
        packet['input_sha256'] = {k: digest for k, digest in bindings.items() if Path(k).name == k}
        packet['archived_file_sha256'] = sorted(digest for k, digest in bindings.items() if Path(k).name != k)
        for field in ('source_sha256', 'archived_fit_source_sha256', 'archived_source_sha256'):
            if field in item:
                sources = {Path(k).name: digest for k, digest in item[field].items()}
                if len(sources) != len(item[field]):
                    raise ValueError('Cone-spread source file names are ambiguous')
                packet[field] = sources
        out[scope] = packet
    return out


def compact(inputs, maps):
    a, position, partial, truth, range_fit = (inputs[key] for key in
        ('attribution', 'position', 'partial_lateral', 'truth_control', 'range'))
    candidates = position['candidates']
    residuals = {(event, pair): values for event, pair, values in
                 candidates['baseline_waveform_center']['residual_rows']}
    windows = {}
    for label in WINDOWS:
        original = a['windows'][label]
        cases = {}
        chosen = set()
        for name in CASES:
            case = original['cases'][name]
            selected = case['trigger_concentration']['ranked_top_trigger_ids'][:5]
            cases[name] = {k: case[k] for k in ('plane', 'census', 'peak', 'source_score', 'trigger_concentration')}
            cases[name]['top_triggers'] = [row for row in case['trigger_contributions']
                                          if row['original_trigger_id'] in selected]
            cases[name]['top_triggers'].sort(key=lambda row: selected.index(row['original_trigger_id']))
            chosen.update(selected)
        source_mm = cases[CASES[0]]['source_score']['position_mm']
        triggers = []
        for row in original['original_triggers']:
            event = row['original_trigger_id']
            if event not in chosen:
                continue
            kept = {k: row[k] for k in ('original_trigger_id', 'energy_keV', 'trigger_time_ns', 'archive_record_sha256',
                                       'archive_adc_sha256', 'input_group_ordinals', 'saved_projected_mass')}
            kept['pairs'] = []
            for pair in row['pairings']:
                orders = [dict(order, signed_source_residual_deg=source_arm(order, source_mm))
                          if order['status'] == 'available' else order for order in pair['orders']]
                kept['pairs'].append(dict(pair, orders=orders,
                                          per_contact_adc_rms_codes=residuals.get((event, pair['index']))))
            triggers.append(kept)
        windows[label] = {'center_keV': original['center_keV'], 'half_width_keV': original['half_width_keV'],
                          'cases': cases, 'trigger_details': triggers}
    truth_fields = ('scope', 'arm_definition', 'energy_definition', 'qualified_trigger_denominator', 'two_strip_triggers',
                    'matched_exact_photon_occurrences', 'independent_original_groups', 'full_energy_occurrences',
                    'truth_status_counts', 'fresh_five_second_truth_join')
    return {
        'kind': 'gegi_public_five_second_reconstruction_v1',
        'source_sha256': {key: digest for key, (_, digest) in SOURCES.items()} | a['input_sha256'],
        'selection': a['saved_selection'], 'source_census': a['saved_source_census'],
        'methods': a['methods'], 'windows': windows, 'maps': maps,
        'position': {'fitted_pairings': candidates['baseline_waveform_center']['scored_pairings'],
                     'lateral_grid_cells': candidates['lateral_grid_cells'],
                     'coverage': candidates['fitted_pairings_by_lateral_supported_site_count'],
                     'contacts': position['contact_ids'],
                     'noise_rms_V': position['optional_noise_rms_V'], 'adc_lsb_V': position['adc_lsb_V'],
                     'controls': {label: {k: report[k] for k in ('trials_total', 'computed_waveform_coverage', 'matched_comparisons')}
                                  for label, report in position['controls'].items()},
                     'partial_controls': partial['controlled_mixtures']['summary'],
                     'partial_fresh': partial['retained_candidates']['summary']},
        'range': {'model': range_fit['model'], 'fits': range_fit['fits']},
        'profiled_range': inputs['profiled_range'],
        'uncertainty_controls': inputs['uncertainty'],
        'joint_cone_spread': compact_cone_spread(inputs),
        'additional_lateral_controls': inputs['additional_lateral'],
        'full_lateral_acceptance': inputs['lateral_acceptance'],
        'energy_offsets': inputs['energy_offsets'],
        'photon_origins': inputs['origins']['science'],
        'raw_angular_response': inputs['angular_tails'],
        'conditional_escape_geometry': inputs['escape_geometry'],
        'exact_photon_controls': {k: inputs['exact_kinetics'][k] for k in
                                 ('kind', 'input_sha256', 'source_sha256', 'status_counts', 'definition', 'rows')},
        'native_response_repair': inputs['native_repair'],
        'local_boundary_response': {
            **{k: inputs['boundary_response'][k] for k in
               ('kind', 'original_trigger_id', 'input_sha256', 'source_sha256',
                'measured_adc_samples_relative_to_trigger_ns', 'electrode_ids',
                'original_projected_mass', 'original_unresolved_mass',
                'observed_early_y28_baseline_tail', 'original_12271_adc_comparison',
                'independent_holdouts', 'method', 'interpretation')},
            'native_points': [{k: v for k, v in point.items() if k != 'record_ref'}
                              for point in inputs['boundary_response']['native_points']]},
        'measured_boundary_grid': {
            **{k: inputs['boundary_grid'][k] for k in
               ('kind', 'input_sha256', 'source_sha256', 'measured_scope', 'calibration_support',
                'original_adc', 'independent_single_pulse_controls', 'independent_overlap_controls', 'interpretation')},
            'captured_points': [{k: v for k, v in point.items() if k not in ('record_ref', 'ref')}
                                for point in inputs['boundary_grid']['captured_points']]},
        'boundary_grid_causes': inputs['boundary_grid_causes'],
        'boundary_depth_refinement': inputs['boundary_depth'],
        'boundary_overlap_validation': inputs['boundary_overlap'],
        'boundary_xy_isolated': inputs['boundary_xy_isolated'],
        'boundary_xy_overlap': inputs['boundary_xy_overlap'],
        'line_hypothesis_summary': {k: inputs['kinematics'][k] for k in
                                    ('kind', 'model', 'methods', 'windows', 'photon_origin_score')},
        'historical_truth_control': {**{k: truth[k] for k in truth_fields},
                                     'full_energy_controls': [row for row in truth['rows']
                                                              if row['containment'] == 'full_energy_at_photon_birth']},
    }


def plot(maps, output):
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.colors import Normalize
    import numpy as np

    extent = maps['extent_mm']
    page = Figure(figsize=(11.2, 6.8), layout='constrained')
    FigureCanvasAgg(page)
    axes = page.subplots(2, len(WINDOWS), sharex=True, sharey=True)
    for j, label in enumerate(WINDOWS):
        layers = maps['mass_by_window_and_prior'][label]
        tone = Normalize(0., max(np.max(layers[k]) for k in PRIORS))
        for i, prior in enumerate(PRIORS):
            ax = axes[i, j]
            matrix = np.array(layers[prior])
            image = ax.imshow(matrix, origin='lower', extent=(-extent, extent, -extent, extent),
                              interpolation='nearest', cmap='magma', norm=tone)
            y, x = np.unravel_index(matrix.argmax(), matrix.shape)
            ax.plot(maps['x_mm'][x], maps['y_mm'][y], marker='+', markersize=9,
                    markeredgewidth=1.3, color='#62e6f4', clip_on=False)
            ax.set_xticks([-100, 0, 100])
            ax.set_yticks([-100, 0, 100])
            ax.tick_params(labelsize=9)
            if i == 0:
                ax.set_title(label.removesuffix('_keV') + ' keV', fontsize=12)
            else:
                ax.set_xlabel('Detector X (mm)', fontsize=10)
            if j == 0:
                name = 'Uniform area' if i == 0 else 'Uniform solid angle'
                ax.set_ylabel(f'{name}\nDetector Y (mm)', fontsize=10)
        page.colorbar(image, ax=axes[:, j], shrink=.76, pad=.05, label='Trigger weight / cell')
    page.suptitle('Five-second GeGI acquisition | measured-energy windows at z = 40 mm', fontsize=15)
    page.savefig(output, dpi=150, facecolor='white')


def attach(site, directory):
    inputs = {key: read_bound(directory / name, digest) for key, (name, digest) in SOURCES.items()}
    validate_inputs(inputs)
    baseline = read_bound(BASELINE, inputs['attribution']['input_sha256']['saved_plane'])
    data = compact(inputs, plane_maps(inputs['attribution'], baseline))
    (site / DIRECTORY).mkdir(parents=True, exist_ok=True)
    plot(data['maps'], site / IMAGE)
    data['figure_sha256'] = sha256((site / IMAGE).read_bytes()).hexdigest()
    energy_image = (directory / ENERGY_IMAGE.name).read_bytes()
    if sha256(energy_image).hexdigest() != inputs['energy_offsets']['figure_sha256']:
        raise ValueError('The saved energy-offset figure differs from its numerical evidence')
    (site / ENERGY_IMAGE).write_bytes(energy_image)
    (site / KINEMATICS).write_bytes((directory / SOURCES['kinematics'][0]).read_bytes())
    (site / DATA).write_text(json.dumps(data, allow_nan=False, separators=(',', ':')) + '\n',
                             encoding='utf-8', newline='\n')


def number(value, places=2):
    return f'{value:,.{places}f}'.replace('-', '−')


def coordinates(values, places=2):
    return '(' + ', '.join(number(v, places) for v in values) + ')'


def title(label):
    return 'Co-60 windows pooled' if label == 'cobalt_both_lines' else f'{label.removesuffix("_keV")} keV'


def strip_pair(cell):
    return f'X{cell[0]:02}/Y{cell[1]-17:02}'


def trigger_detail(trigger):
    from gegi_shared_clock_display import table

    ident = trigger['original_trigger_id']
    rows = []
    for pair in trigger['pairs']:
        fit = pair['center_fit_diagnostics'].get('waveform')
        residuals = pair['per_contact_adc_rms_codes']
        channel_fit = pair['fit_contacts'] or []
        for order in pair['orders']:
            sequence = order['order']
            rms = 'Unavailable'
            depths = 'Unavailable'
            if fit is not None and residuals is not None:
                all_rms = math.sqrt(math.fsum(v**2 for v in residuals)/len(residuals))
                rms = (f'{number(all_rms)} ADC codes across all 34 contacts. Weighted fit RMS '
                       f'{number(fit["weighted_residual_rms"])} × nominal noise on {len(channel_fit)} contacts.')
                depths = ' → '.join(number(fit['positions_mm'][i][2]) for i in sequence)
            geometry = ('Unavailable' if 'half_angle_deg' not in order else
                        f'{number(order["half_angle_deg"])}° opening, {number(order["signed_source_residual_deg"])}° source residual')
            rows.append((str(pair['index'] + 1),
                         ' → '.join(strip_pair(pair['cells'][i]) for i in sequence),
                         ' → '.join(number(pair['site_energies_keV'][i]) for i in sequence),
                         depths, geometry, rms))
    summary = f'Trigger {ident:,} · {number(trigger["energy_keV"])} keV'
    return (f'<details id="trigger-{ident}"><summary>{summary}</summary>'
            + table(rows, ('Pairing', 'Order', 'Site energies (keV)', 'Fit depths (mm)', 'Cone', 'Waveform residual'),
                    f'Available measured pairings and orders for trigger {ident:,}')
            + '<p>The source residual is the angle from the cone axis to the programmed source minus the energy-derived opening.'
              ' The evidence JSON includes the original ADC digest and per-contact residuals.</p></details>')


def origin_section(data):
    from gegi_shared_clock_display import table

    rows = []
    for label, window in data['photon_origins']['windows'].items():
        for trigger in window['triggers']:
            truth = trigger['photon_truth']
            emitters = [g for g in truth['emitted_gammas'] if g['ge_deposited_keV'] > 0.]
            processes = [r['child_birth_processes'] for r in truth['ge_interactions_matched_to_births']]
            nc, np = (sum(name in p for p in processes) for name in ('compt', 'phot'))
            history = f'{nc} Compton' + (f' + {np} photoelectric' if np else ' + Ge exit')
            forward = {p['nominal_order_survives_saved_projection'] for p in trigger['measured_pairings']}
            order_status = 'retained' if True in forward else 'excluded' if forward == {False} else 'unassigned'
            ident = trigger['original_trigger_id']
            rows.append((title(label), f'<a href="#trigger-{ident}">{ident:,}</a>',
                         number(100*trigger['original_peak_cell_share'])+'%',
                         ' + '.join(number(g['emitted_keV']) for g in emitters),
                         number(trigger['ge_deposit_keV']), history, order_status))
    details = table(rows, ('Measured window', 'Trigger', 'Peak share', 'Photon energy (keV)',
                          'Ge deposit (keV)', 'Photon history', 'Forward nominal-cell order'),
                    'Verified transport origins of the ten leading cobalt-window peak contributors')
    return f'''<section class="panel" id="photon-origins"><h2>Two recorded sites can hide several photon scatters</h2>
<p>Exact original-state transport replays traced the five largest contributors to each cobalt-window peak.
In the 1,173 keV window, three escaping 1,332 keV photons supplied <strong>47.00%</strong> of the original corner;
two full-energy 1,173 keV photons with merged interactions supplied another <strong>14.36%</strong>.
In the 1,332 keV window, all five were full-energy photons with two to five Compton scatters followed by photoelectric absorption.
They supplied <strong>53.52%</strong> of that corner, including <strong>46.50%</strong> through the reverse nominal-cell order.</p>
<p>For trigger <a href="#trigger-12841">12,841</a>, the first two photon vertices were only <strong>4.54 μm</strong> apart
and deposited 1,154.35 keV together. A third scatter deposited 34.36 keV before the photon left Ge.
The accompanying 1,173 keV photon deposited zero. The two-site full-absorption interpretation excludes the forward order
and returns a 9.18° reverse cone, whose angular residual to the programmed source is 92.35°.</p>
<p>At the original corner, that cone is still 53.90° from its angular center, or 5.65 times its effective 9.54° width.
Its raw angular density is only 2.78 × 10<sup>−7</sup> rad<sup>−1</sup> there. Normalizing this weak tail over the finite grid
nevertheless gives the cone a full unit of weight and places 0.02681 trigger units in the corner, explaining its 24.79% peak share.
This conditional angular density is not a calibrated detector probability. The other leading cones have different residuals;
their individual raw responses and both map extents are retained in the evidence JSON.</p>
{details}
<p>Each selected ADC context overlaps one Ge deposition group. The replay matches the original primary, random-state,
canonical source-stream and native-input hashes; LH5 container byte hashes differ. Interaction processes are matched
from child births to scored photon vertices. Earlier electronics tails were not isolated, and neither drift nor readout
was rerun. Nominal cells describe nearest-strip geometry. Other triggers remain causally unclassified.</p>
<p>These failures distinguish measured energy, photon containment and interaction count. Merged-pixel artifacts are also
examined by <a href="https://doi.org/10.1109/TNS.2020.3005834">Shy, Xia and He (2020)</a>;
<a href="https://doi.org/10.1016/j.astropartphys.2022.102765">Yoneda et al.</a> model absorption and escape separately.
Their detector performance and selection parameters are not transferred to GeGI. Original candidate weights and maps remain unchanged.</p>
<details><summary>Test absorption and escape hypotheses from measured energies</summary>
<p>The new optional incident-line ledger checks all 3,822 original triggers and 7,644 measured pair alternatives,
including 4,607 pairs whose strip energies are incompatible. It reads measured energies and explicitly supplied line energies;
photon history enters only the subsequent comparison. All original projected and unresolved weights remain intact.</p>
<p>At 1,332.492 keV, the measured energies of triggers 42,261 and 19,477 admit their true two-scatter escape order;
trigger 12,841 admits neither order, consistent with its unresolved third scatter. Only 13.06% of the original 1,173-window
corner comes from order geometries compatible with that resolved escape hypothesis. Compatibility alone cannot assign
an isotope: the compatible Cs-window candidates also admit escape under both cobalt lines.</p>
<p>The optional finite-vertex escape diagnostic uses the same saved waveform positions and the supplied incident line.
For the verified two-scatter photons 42,261 and 19,477, the true-order angular residuals are +15.26° and −6.46° at 1,332.492 keV.
Trigger 12,841 returns no such cone. These are three selected controls, not calibrated acceptance rates or a new image;
the original maps retain their weights.</p>
<p><a href="{KINEMATICS.name}">Complete measured-pair and incident-line ledger (lossless JSON gzip)</a> retains raw cosines,
energy margins, both orders, original identities and all unknown cases. It applies no new selection or imaging weight.</p></details></section>'''


def exact_kinetics_section(data):
    from gegi_shared_clock_display import table

    controls = data['exact_photon_controls']
    rows = []
    for row in controls['rows']:
        control = row.get('substitution_control')
        if control is None or row['score_status'] != 'matched_energy_and_positions':
            continue
        terms = control['signed_arm_components_deg']
        rows.append((f'{row["original_trigger_id"]:,}',
                     'Chronological' if row['sample'] == 'chronological_sample' else 'Peak control',
                     number(terms['transported_turn_minus_stationary_energy_angle_deg'], 3),
                     number(terms['signal_position_contribution_deg'], 3),
                     number(terms['measured_transfer_contribution_deg'], 4),
                     number(terms['additional_nominal_incident_energy_contribution_deg'], 5)))
    comparison = table(rows, ('Trigger', 'Sample', 'Transport model (°)', 'Fitted position (°)',
                              'Measured transfer (°)', 'Nominal incident line (°)'),
                       'Additive signed angular-residual terms on eight identical photon histories')
    return f'''<section class="panel" id="exact-photon-controls"><h2>Separate physical angular spread from reconstruction errors</h2>
<p>Ten original transport blocks were replayed with an observational photon-step recorder. Original primaries,
random states, canonical detector streams and native inputs matched. The recorder retains true pre/post photon
energies and directions. In all ten selected histories, the source-to-first-scatter ray matches the recorded incoming
direction to numerical precision; no prior discrete scatter is present on that photon track.</p>
<p>True energies do not imply a zero angular residual under the stationary free-electron formula.
The configured <a href="https://github.com/Geant4/geant4/blob/v11.3.2/source/processes/electromagnetic/lowenergy/src/G4LivermoreComptonModel.cc#L334-L412">Geant4 11.3.2 Livermore model</a>
samples the scattering direction, then updates the photon energy using bound-electron momentum and shell binding
(Doppler broadening). This model contribution is kept separate from errors in fitted positions and measured energies.</p>
<p>On eight histories with matched positions and energies, substituting fitted positions changes the angular residual
by <strong>0.44–16.59°</strong> in magnitude; substituting measured energy transfers changes it by <strong>0.005–0.049°</strong>.
These controls support improving position and charge-sharing models. They are selected cases from the development
acquisition, not a detector resolution or an independent efficiency measurement.</p>
<details><summary>Compare the same-event angular terms and retained unknowns</summary>
{comparison}
<p>The signed terms add to the nominal-line angular residual, with a separate source-alignment term consistent with
floating-point roundoff. The ledger keeps all 18 prespecified chronological triggers plus three named peak controls: eight complete
signal substitutions, trigger 12,271 with truth only, trigger 12,841 with unresolved merged scatters, and eleven without
the new observer. All original projected and unresolved weights remain intact.</p>
<p>The <a href="{DATA.name}">evidence JSON</a> includes every selected identity, exact photon step, substitution and unknown
status, bound to its original ADC and replay hashes. Earlier estimate-based records remain preserved locally.</p>
</details></section>'''


def boundary_response_section(data):
    from gegi_shared_clock_display import table

    response = data['local_boundary_response']
    comparison = response['original_12271_adc_comparison']
    baseline = comparison['baseline_center_three_cell']
    best = comparison['sampled_models'][comparison['best_sampled_all34_model_index']]
    grid = data['measured_boundary_grid']
    grid_fit = grid['original_adc']['within_cell_fit']
    depth = data['boundary_depth_refinement']
    depth_fit = depth['original_adc']['refined_lateral_fit']
    old = depth['existing_development_controls']
    earlier_single = [r for r in old if r['control_set'] == 'independent_single_pulse_controls']
    groups_refined = [
        ('Fresh interior positions', depth['independent_fresh_interior_controls']),
        ('Earlier interior positions', [r for r in earlier_single
                                       if r['coarse']['held_out_positions_for_scoring'][0]['role'] == 'interior_holdout']),
        ('Earlier overlap components', [r for r in old if r['control_set'] == 'independent_overlap_controls']),
        ('Earlier outside-grid gap probes', [r for r in earlier_single
                                           if r['coarse']['held_out_positions_for_scoring'][0]['role'] == 'gap_holdout'])]
    refined_rows = []
    for label, controls in groups_refined:
        before = [e for row in controls for e in row['coarse']['lateral']['position_errors_mm']]
        after = [e for row in controls for e in row['refined']['position_errors_mm']]
        rms = lambda values: math.sqrt(math.fsum(e*e for e in values)/len(values))
        refined_rows.append((label, str(len(before)), number(rms(before), 3), number(rms(after), 3),
                             str(sum(b > a for a, b in zip(before, after, strict=True)))))
    refinement = table(refined_rows, ('Matched positions', 'Count', '3-depth RMS (mm)', '11-depth RMS (mm)',
                                     'Positions worsened'), 'Changing only the depth axis of the response grid')
    overlap = data['boundary_overlap_validation']
    overlap_rows = []
    for row in overlap['summary_by_energy_allocation']:
        fractions = overlap['design']['fractions_in_measured_cell_order'][row['allocation_index']]
        before = row['fit_statistics']['coarse_three_depth']
        after = row['fit_statistics']['refined_eleven_depth']
        overlap_rows.append((' / '.join(f'{100*f:g}%' for f in fractions),
                             str(row['common_position_conditions']),
                             number(before['weak_component_position_rms_mm'], 3),
                             number(after['weak_component_position_rms_mm'], 3),
                             number(after['max_weak_near_tie_displacement_mm'], 3)))
    overlap_table = table(overlap_rows, ('Component energy fractions', 'Matched conditions',
                                        '3-depth weak error RMS (mm)', '11-depth weak error RMS (mm)',
                                        '11-depth weak near-tie spread (mm)'),
                          'Weak-component stability across two physical layouts, ADC phases and noise seeds')
    xy = data['boundary_xy_overlap']
    isolated = data['boundary_xy_isolated']['controls']
    single_errors = [[row['bilinear_xy']['position_errors_mm'][0] for row in isolated],
                     [row['shape_preserving_xy']['position_error_mm'] for row in isolated]]
    paired = xy['summary_on_matched_position_conditions']
    xy_rows = [('Six isolated positions', '6',
                number(math.sqrt(math.fsum(e*e for e in single_errors[0])/6), 3),
                number(math.sqrt(math.fsum(e*e for e in single_errors[1])/6), 3),
                str(sum(b > a for a, b in zip(*single_errors, strict=True))))]
    for label, field, weak_only in (
            ('All overlap components', 'all_component_position_rms_mm', False),
            ('Weak overlap components', 'weak_component_position_rms_mm', True)):
        before, after = [], []
        for row in xy['conditions']:
            a = row['refined_eleven_depth']['position_errors_mm']
            b = row['shape_preserving_xy']['position_errors_mm']
            fractions = xy['design']['fractions_in_measured_cell_order'][row['allocation_index']]
            indices = [min(range(len(fractions)), key=fractions.__getitem__)] if weak_only else range(len(a))
            before.extend(a[i] for i in indices)
            after.extend(b[i] for i in indices)
        xy_rows.append((label, str(len(before)), number(paired['refined_eleven_depth'][field], 3),
                        number(paired['shape_preserving_xy'][field], 3),
                        str(sum(b > a for a, b in zip(before, after, strict=True)))))
    xy_table = table(xy_rows, ('Same saved inputs', 'Positions', 'Linear XY RMS (mm)',
                               'PCHIP XY RMS (mm)', 'Positions worsened'),
                     'Changing only X/Y interpolation in the same eleven-depth response bank')
    xy_original = xy['original_adc']['shape_preserving_xy']
    single = grid['independent_single_pulse_controls']
    interior = [row for row in single if row['held_out_positions_for_scoring'][0]['role'] == 'interior_holdout']
    gap = [row for row in single if row['held_out_positions_for_scoring'][0]['role'] == 'gap_holdout']
    groups = [('Interior single pulses', interior), ('Outside-grid gap probes', gap),
              ('Components in two overlapping pulses', grid['independent_overlap_controls'])]
    errors = []
    for label, controls in groups:
        before = [e for row in controls for e in row['center']['position_errors_mm']]
        after = [e for row in controls for e in row['lateral']['position_errors_mm']]
        rms = lambda values: math.sqrt(math.fsum(e*e for e in values)/len(values))
        errors.append((label, str(len(before)), number(rms(before), 3), number(rms(after), 3),
                       str(sum(b > a for a, b in zip(before, after, strict=True)))))
    independent = table(errors, ('Independent control', 'Positions', 'Center RMS (mm)',
                                 'Grid RMS (mm)', 'Positions worsened'),
                        'Identical native inputs and quantized ADC controls, with energies measured from each ADC')
    rows = []
    for holdout in response['independent_holdouts']:
        fitted = next(row for row in holdout['off_center_alternatives']
                      if row['point_index'] == holdout['best_off_center_training_point_index'])
        rows.append((str(holdout['point_index']),
                     coordinates(holdout['injected_position_mm'], 3),
                     number(holdout['center']['position_error_mm'], 4),
                     number(fitted['position_error_mm'], 4)))
    holdouts = table(rows, ('Point', 'Injected position (mm)', 'Center error (mm)', 'Local-template error (mm)'),
                     'Three noisy ADC controls at positions excluded from the fitted template alternatives')
    return f'''<section class="panel" id="local-boundary-response"><h2>Fit within-strip positions without a replay-defined anchor</h2>
<p>For trigger 12,271, response grids derived from measured strip cells and detector geometry reduce all34 residual
RMS from {baseline["all34_adc_rms_codes"]:.2f} ADC codes at strip centers to {grid_fit["all34_adc_rms_codes"]:.2f} with three
lateral-response depths, then <strong>{depth_fit["all34_adc_rms_codes"]:.2f} with eleven depths</strong>.
Y28 changes from {baseline["y28_adc_rms_codes"]:.2f} to {grid_fit["y28_adc_rms_codes"]:.2f}, then
<strong>{depth_fit["y28_adc_rms_codes"]:.2f} codes</strong>.
The fit keeps the same original ADC and measured component energies; photon vertices and source coordinates do not
select its calibration positions. The depth-only test keeps the X/Y grid and fit unchanged, reuses 72 prior grid responses
and 33 center traces, and adds 192 depth-grid responses plus six fresh validation positions. All responses retain 34
electrodes and complete carrier endpoints. Reusing the old three-depth grid reproduces all twelve prior fits exactly.</p>
{refinement}
<p>All six fresh interior positions improve, with RMS 1.237 → 0.285 mm. The earlier controls now serve as development
evidence: overlap errors decrease in aggregate, but two of six component positions worsen. All three near-gap fits reach
the Y limit and remain outside calibrated X/Y support. These are local simulated point-response tests; position accuracy
over the detector and photon-interaction identification remain unvalidated.</p>
<h3>Overlapping components retain position ambiguity</h3>
<p>The six fresh native responses form two fixed three-component layouts. Three energy allocations, two ADC phases
and two noise realizations produce 24 distinct readout conditions. The eleven-depth fit converges in all 24;
the three-depth fit fails to converge in one, which remains recorded. On the 23 matched conditions, all34 waveform
RMS decreases from 17.445 to 4.403 codes and component-position RMS from 2.055 to 0.982 mm,
but <strong>10 of 69 component positions worsen</strong>.</p>
{overlap_table}
<p>Weak-component near-tied positions still differ by as much as 2.36 mm. For the 29/55/16% allocation, the largest
weak-position change across repeated readouts increases from 0.148 to 0.593 mm; fitted parameters reach the outer
calibration limits in 15 of the 23 matched refined conditions, versus 11 with three depths. These are two physical
layouts with repeated readout conditions, not 24 independent photon histories. No acceptance threshold or imaging
weight is changed.</p>
<h3>Better waveform interpolation does not resolve every component</h3>
<p>A subsequent fixed comparison replaces linear X/Y interpolation with the average of both axis orders of
<a href="https://docs.scipy.org/doc/scipy/reference/generated/scipy.interpolate.PchipInterpolator.html">piecewise cubic Hermite interpolation (PCHIP)</a>.
It uses the same response bank, measured energies and ADC samples, with linear depth/time interpolation and no
extrapolation across collection cells. All 297 training knots reproduce to numerical precision; contact identities
and native charge closure are checked separately from interpolation of voltage templates.</p>
{xy_table}
<p>Both eleven-depth methods return positions for all 24 overlapping readouts. Their all34 waveform RMS changes
from 4.428 to 3.930 ADC codes, but weak-component positions improve in only 12 of 24 conditions.
The largest weak near-tie spread grows from <strong>2.36 to 2.81 mm</strong>, and outer-limit conditions increase
from 15 to 16. The 10/45/45% allocation's weak-position RMS worsens from 0.886 to 1.089 mm.
These 24 matched conditions differ from the earlier three-depth comparison's 23-condition denominator.</p>
<p>On original trigger 12,271, all34 residual changes from {depth_fit['all34_adc_rms_codes']:.2f} to
{xy_original['all34_adc_rms_codes']:.2f} codes and Y28 from {depth_fit['y28_adc_rms_codes']:.2f} to
{xy_original['y28_adc_rms_codes']:.2f}. No independent position score is assigned to that measured fit.
The two unsupported allocation alternatives and unresolved weight of one are retained. This research comparison
is not a new default reconstruction or a detector-wide resolution measurement.</p>
<details><summary>Inspect the initial three-depth grid and its independent controls</summary>
{independent}
<p>Six interior single-pulse controls improve in aggregate. For the two overlapping controls, three of six component
positions worsen even though the aggregate RMS decreases. A lower waveform residual therefore does not establish a
correct interaction position. The three near-gap controls lie outside the fitted ±0.4-pitch grid. All original pairing
alternatives and near-tied fits remain recorded; the uncalibrated fourth cell is explicit.</p></details>
<p>This event contains two photon interaction vertices but charge in three nominal cells. Three charge components do
not establish three photon interactions. Its original imaging weight remains zero, with unresolved weight one.</p>
<details><summary>Why the lower residual still leaves position errors</summary>
<p>All eleven original control ADC hashes reproduce. At the known positions of the two overlapping controls, template
interpolation alone differs from the native waveform by <strong>25.07 and 27.20 ADC codes RMS</strong>. The corresponding
noise contribution is 2.29 and 2.26 codes, and quantization contributes about 0.18 and 0.17 codes. These are separate
same-clock waveform comparisons, not an additive uncertainty budget.</p>
<p>Replacing measured component energies with their known injected values moves any fitted position by at most
0.00475 mm and leaves all three worsened overlap positions worse. Removing noise in the second overlap changes its
positions by at most 0.028 mm. All six isolated fits settle at internal lateral grid knots; the weak overlap component
settles near internal depth knots. Nearly tied overlap solutions differ by up to 1.31 mm. These results identify
interpolation mismatch and ambiguous component positions as priorities; they do not support an energy cut or a narrower
imaging cone. The complete comparisons remain in the <a href="{DATA.name}">evidence JSON</a>.</p></details>
<details><summary>Compare the earlier replay-defined local test</summary>
<p>The earlier ten-point test used a neighborhood specified from the replay geometry, including a first-component
anchor. Its best of 16 alternatives reduced all34 RMS to <strong>{best["all34_adc_rms_codes"]:.2f} ADC codes</strong>
and Y28 to <strong>{best["y28_adc_rms_codes"]:.2f}</strong>. That case-specific benefit is distinct from locating an
unknown event using a grid defined only by measured cells.</p>
{holdouts}
<p>The probe neighborhood was specified from the replay geometry before comparing the ADC. Three additional positions
were excluded from the template alternatives and scored only after fitting independent noisy, quantized ADC controls.
These are local response tests, not a blind detector-wide position-resolution measurement. The ten injected points have
known carrier endpoints; the carrier allocation of the original distributed deposits remains unmeasured.</p>
<p>Models keep the strip-derived component energies fixed, sum full-electrode point responses and fit a common onset.
Only complete responses ending in the required collecting cells enter an alternative; no interpolation crosses a
collection boundary. The quiet pretrigger Y28 tail is approximately −3 ADC codes, and removing it does not account for
the observed residual reduction. Both grid and replay-defined controls, all alternatives, per-channel residuals and
exact source hashes remain in the <a href="{DATA.name}">evidence JSON</a>.</p></details></section>'''


def native_repair_section(data):
    from gegi_shared_clock_display import table

    repair = data['native_response_repair']
    census, mask = repair['census'], repair['conditional_mask']
    labels = {'stopped_without_contact': 'Stopped before contact', 'step_limit': 'Reached configured duration',
              'Deposit starts on a GeGI contact': 'Start classified on a contact',
              'Noncontact endpoint outside crystal': 'Endpoint outside crystal without contact',
              'Invalid native signed charge': 'Signed-charge check failed'}
    rows = []
    for cause in census['cause_transitions']:
        result = cause['outcomes']
        rows.append((labels[cause['original_domain_error'] or cause['original_status']],
                     f'{cause["groups"]:,}', f'{result.get("completed", 0):,}',
                     f'{result.get("step_limit", 0):,}', f'{result.get("native_failed", 0):,}',
                     f'{result.get("stopped_without_contact", 0):,}'))
    outcomes = table(rows, ('Original cause', 'Groups', 'Complete', 'Duration reached',
                            'Boundary projection failed', 'Stopped before contact'),
                     'All originally unavailable native-response groups, with original identities retained')
    return f'''<section class="panel" id="native-repair"><h2>Recover native charge responses by cause</h2>
<p>All <strong>{census["original_unavailable_groups"]:,}</strong> originally unavailable groups have been reprocessed or
matched to exact prior complete responses. <strong>{census["complete_groups"]:,}</strong> now have complete native charge
responses: 810 newly processed and 39 inherited. The remaining {census["remaining_unavailable_groups"]:,} keep their
failure or unknown status. The same field samples and detector model were retained; Float64 drift coordinates and
analytic boundary crossing address identified numerical defects.</p>
{outcomes}
<p>Using the original 1,001 ns numerical support policy, the modeled union of unknown-history intervals changes from
<strong>{mask["original"]["excluded_seconds"]:.9f} s</strong> to <strong>{mask["remaining"]["excluded_seconds"]:.9f} s</strong>.
This is conditional native availability. The original ADC stream, triggers, accepted exposure and source images remain
unchanged; restoring those requires replaying the shared electronic history with the recovered currents.</p>
<details><summary>Why extending every trajectory is not a complete repair</summary>
<p>Sixteen configured drift-only conditions examined 41 original deposited rows, with 47 evaluations including repeated
durations. For transport event 2,590, both carriers are still moving at 1 μs and reach contacts at 2.553 and 2.778 μs.
For transport event 132,649, the electron instead reaches a stationary projected position at 1.712 μs; extending the calculation
from 5 to 20 μs leaves it unchanged. The remaining stopped-row probes retain stationary electrons without contact
and holes at contacts.</p>
<p>Two boundary witnesses expose distinct geometry problems: roundoff in a tangential segment can select its starting
face again, while a projection onto one face can point outward through another face at a corner. These observations
guide the next numerical corrections. A drift-only point reaching a contact does not establish a complete group waveform.</p>
<p>The arbitrary 20,000-sample execution ceiling has been removed; the requested duration and time step determine the
sample count. Default timing remains 1 ns over 1,000 ns. Longer-response studies must use their actual configured support
when calculating unknown-history intervals. Source and ledger hashes, all cause counts and measured resources are in the
<a href="{DATA.name}">evidence JSON</a>.</p></details></section>'''


def cone_spread_section(data):
    from gegi_shared_clock_display import table

    evidence = data['joint_cone_spread']
    comparison = evidence['negative']['comparison']['lateral']
    negative = comparison['negative_trials_all_pairings']
    positive = comparison['retained_positive_trials_all_pairings']
    left, right = (r['trigger_max_axis_span_deg']['median'] for r in (negative, positive))
    models = evidence['candidates']['summary']['models']
    names = (('local_center', 'Local waveform, center'), ('local_lateral', 'Local waveform, lateral (143 partial, 8 full)'),
             ('all34_center', 'All 34 channels, center'), ('all34_lateral', 'All 34 channels, full lateral'))
    rows = []
    for key, label in names:
        model = models[key]
        rows.append((label, f'{model["pairings_with_saved_model"]:,}',
                     f'{model["orders_with_multiple_geometries"]:,}', number(model['maximum_axis_span_deg']),
                     number(model['maximum_finite_vertex_angle_span_deg_by_radius'][0])))
    candidate_table = table(rows, ('Saved waveform fit', 'Pairings with saved fits', 'Orders with alternatives',
                                   'Largest axis span (°)', 'Largest angle span at 50 mm (°)'),
                            'Sampled cone spread in the five-second candidate archive')
    return f'''<h3 id="cone-spread">Stable cones can come from more than two interactions</h3>
<p><strong>{negative['trials_with_multiple_geometries_for_an_order']}/{negative['readout_conditions']}</strong> known three- or
four-point readouts returned two-site cones with multiple sampled solutions. With all 34 channels and lateral fits, the median
of each readout's largest axis span was <strong>{number(left, 6)}°</strong> for those mixtures and
<strong>{number(right, 6)}°</strong> for the {positive['readout_conditions']} two-point controls. Each cohort spans
{positive['physical_layouts']} physical layouts with repeated readout conditions. These results give no basis for a stability cut.</p>
<p>Each sampled fit moves its two positions together. For the same measured order and energies, we compare the cone axis
and the angle from the fitted first interaction to points on four preset shells (50, 100, 300 and 1,000 mm).
The {evidence['candidates']['summary']['triggers']:,} five-second candidates retain their original imaging weights.
The table compares different fit populations, with the all-34-channel results available for a subset.</p>
{candidate_table}'''


def sections(data):
    from gegi_shared_clock_display import table
    from gegi_joint_imaging import REFERENCES

    windows, counts, census = (data[k] for k in ('windows', 'selection', 'source_census'))
    case = windows['1173.23_keV']['cases'][CASES[0]]
    corner = case['top_triggers'][0]
    ident = corner['original_trigger_id']
    new_peak = corner['without_trigger']['peak']['position_mm']
    solid_angle_peak = windows['1173.23_keV']['cases'][CASES[1]]['peak']['position_mm']
    table_rows = []
    for label in WINDOWS:
        for name in CASES:
            r = windows[label]['cases'][name]
            p = r['plane']
            xy = coordinates(r['peak']['position_mm'][:2], 0)
            if r['peak']['on_image_edge']:
                xy += ' (edge)'
            trigger_links = ', '.join(f'<a href="#trigger-{t["original_trigger_id"]}">#{t["original_trigger_id"]}</a>'
                                      for t in r['top_triggers'])
            table_rows.append((title(label), f'±{p["extent_mm"]:g} mm', p['prior'].replace('-', ' '), xy,
                               number(100*r['trigger_concentration']['largest_five_peak_cell_share'], 1) + '%', trigger_links))
    comparison = table(table_rows, ('Window', 'Plane extent', 'Prior', 'Brightest X/Y (mm)', 'Top 5 share', 'Peak contributors'),
                       'Saved source-plane peaks and shares of their brightest cells')
    events = ''.join(trigger_detail(t) for label in WINDOWS for t in windows[label]['trigger_details'])
    fit_rows, primary_rows = [], []
    fit_order = (('primary', 'Primary'), ('first_clock_half', 'First clock half'),
                 ('second_clock_half', 'Second clock half'), ('no_extra_background', 'Extra background 0%'))
    sensitivity = []
    for label in (*WINDOWS, 'cobalt_both_lines'):
        item = data['range']['fits'][label]
        for key, wording in fit_order:
            r = item['fits'][key]
            intervals = r['profile_diagnostic']
            spans = intervals['sampled_support_mm']
            support = ' to '.join(number(v, 1) for v in spans) if spans else 'Unavailable'
            if intervals['lower_open'] or intervals['upper_open']:
                support += ' (open at search boundary)'
            if key == 'primary':
                primary_rows.append((title(label), coordinates(r['position_mm']), number(r['center_distance_mm']), support))
            else:
                fit_rows.append((title(label), wording, coordinates(r['position_mm']), number(r['center_distance_mm']), support))
        sensitivity.append((title(label), number(item['split_position_difference_mm']),
                            number(item['background_position_difference_mm'])))
    primary_table = table(primary_rows, ('Window', 'X/Y/Z (mm)', 'Range (mm)', 'Sampled profile support (mm)'),
                          'Primary conditional source positions')
    range_table = table(fit_rows, ('Window', 'Fit', 'X/Y/Z (mm)', 'Range (mm)', 'Sampled profile support (mm)'),
                        'Clock-half and background sensitivity fits')
    range_sensitivity = table(sensitivity, ('Window', 'Half-to-half displacement (mm)', 'Removing extra background (mm)'),
                              'Sensitivity of conditional source position')
    profiled_rows = []
    for label, item in data['profiled_range']['fits'].items():
        fit = item['fits']['profiled_background']
        profiled_rows.append((title(label), coordinates(fit['position_mm']), number(fit['center_distance_mm']),
                              number(100*fit['uniform_angle_fraction'], 1)+'%',
                              number(fit['score_gain_over_far_field'])))
    profiled_table = table(profiled_rows, ('Window', 'X/Y/Z (mm)', 'Range (mm)', 'Fitted extra background',
                                         'Finite minus far-field score'), 'Source position with profiled background')
    uncertainty = data['uncertainty_controls']
    negatives = uncertainty['summary']['waveform_center']['wrong_topology_groups']
    false_returns = sum(row['wrong_topology_available_to_projection'] for row in negatives.values())
    topology_table = table([(label.replace('_', ' '), str(row['conditions']),
                             str(row['wrong_topology_available_to_projection'])) for label, row in negatives.items()],
                           ('Known injected topology', 'Readout conditions', 'Two-site models with allowed cones'),
                           'Known multi-point mixtures accepted by the current two-site interpretation')
    position = data['position']
    controls = position['controls']['general']['matched_comparisons']
    center = controls['waveform_center_to_waveform_all_center']
    lateral = controls['waveform_all_center_to_waveform_all_lateral']
    targeted = position['controls']['targeted_cs']['matched_comparisons']['waveform_all_center_to_waveform_all_lateral']
    partial = position['partial_controls']['waveform']
    position_rows = []
    for label, r in (('48 general mixtures, local center → 34-channel center', center),
                     ('36 general mixtures, 34-channel center → two lateral grids', lateral),
                     ('8 targeted Cs mixtures, 34-channel center → two lateral grids', targeted),
                     ('12 general mixtures, local center → one lateral grid', partial)):
        position_rows.append((label, ' → '.join(number(v) for v in r['axis_error_rms_deg']),
                              ' → '.join(number(v, 3) for v in r['xy_error_rms_mm']),
                              ' → '.join(number(v, 3) for v in r['depth_error_rms_mm'])))
    position_table = table(position_rows, ('Identical ADC trials', 'Axis RMS error (°)', 'XY RMS error (mm)', 'Depth RMS error (mm)'),
                           'Independent simulated point-injection position controls')
    additional = data['additional_lateral_controls']['matched_comparisons']['waveform']['all']
    coverage = position['coverage']
    held = data['historical_truth_control']
    primary = data['range']['model']
    references = ' · '.join(f'<a href="{escape(ref["url"])}">{escape(ref["title"])}</a>' for ref in REFERENCES)
    return f'''
<div class="reader-page">
<header class="reader-intro"><h1>{TITLE}</h1>
<p>In the 1,173.23 keV window, one original trigger supplied <strong>{number(100*case["trigger_concentration"]["largest_peak_cell_share"])}%</strong>
of the brightest cell on the ±120 mm uniform-area map. Removing <a href="#trigger-{ident}">trigger {ident:,}</a>
moves the maximum {number(corner["without_trigger"]["shift_mm"], 0)} mm to {coordinates(new_peak[:2], 0)} mm.
With the trigger retained, widening the map moves the maximum to the larger corner.
On the same measured events, the uniform-solid-angle peak lies at {coordinates(solid_angle_peak[:2], 0)} mm.</p>
<p>Targeted transport replay identifies the leading trigger as an escaping 1,332 keV photon with three scatters;
the dominant 1,332 keV-window contributors instead contain full-energy photons with merged multiple interactions.</p>
<p>The conditional 3D fits put the Cs-137 window close to the programmed source. The Co-60 positions vary with clock half
and assumed background. These data leave cobalt localization unvalidated.</p></header>
<section class="panel" id="plane"><h2>What drives the source-plane peaks?</h2>
<figure class="gegi-five-second-figure"><a href="{IMAGE.name}"><img src="{IMAGE.name}" width="{IMAGE_SIZE[0]}" height="{IMAGE_SIZE[1]}"
 alt="Six source-plane heat maps compare area and solid-angle priors for the three line windows. The 1173 keV area maximum is at the far upper-right corner."></a>
<figcaption>Crosses mark the brightest cells. Each column shares one color scale for the two priors.
All panels use 4 × 4 mm cells on the z = 40 mm plane. Compare positions across columns and weights within each column.</figcaption></figure>
<p>Each Compton cone distributes its assigned trigger weight over the finite plane grid. Changing the grid changes
the normalization. Equal-area cells have equal initial weights under the area prior. The solid-angle prior weights
cells by the angular area they subtend from the detector center.</p>
{comparison}
<p>Each row links the five largest contributors to its peak cell. The acquisition census includes every retained two-strip trigger.</p>
<p>Energy-window membership uses measured energy. Programmed source positions enter only when scoring the completed fits.</p>
<details><summary>Measured energy offsets and the original peak contributions</summary>
<figure class="gegi-five-second-figure"><a href="{ENERGY_IMAGE.name}"><img src="{ENERGY_IMAGE.name}"
 alt="Energy offset versus peak contribution and cumulative curves for the three measured windows."></a>
<figcaption>Every retained trigger keeps its original contribution, including zero. The curves describe the existing maps;
they do not define a new energy cut.</figcaption></figure>
<p>The 1,173 keV corner reaches half its weight only at an absolute energy offset of 4.577 keV,
although the median retained-candidate offset is 0.075 keV. Its three largest contributors supply 47.00% of the corner.
The 1,332 keV corner reaches half its weight within 0.091 keV of its window center, so a broad energy window alone
cannot explain that second artifact. The original half-widths are max(5 keV, 2% of the nominal line energy).</p>
<p>Separate known point-deposit injections give simulated total-energy residuals of 0.038 keV RMS for 48 general
conditions and 0.035 keV for eight targeted Cs conditions. These are readout checks, not monoenergetic photon
resolution measurements or a calibrated selection rule.</p></details>
<details><summary>Original triggers and interaction orders</summary>{events}</details></section>
{origin_section(data)}
{exact_kinetics_section(data)}
{boundary_response_section(data)}
{native_repair_section(data)}
<section class="panel" id="range"><h2>Conditional three-dimensional position</h2>
<p>The fit searches a full sphere and ranges from {number(primary["radial_search_mm"][0], 0)} to
{number(primary["radial_search_mm"][1], 0)} mm from detector (0, 0, 0). The primary model uses a nominal
{number(primary["response"]["angular_nuisance_sigma_deg"], 0)}° angular width in addition to strip-quantization uncertainty
and a fixed {number(100*primary["extra_uniform_angle_fraction"], 0)}% extra uniform-angle component.
Unresolved trigger weight remains uninformative. The search used {primary["radial_points"]} radial grid points,
{primary["directional_seeds"]} directional seeds and {primary["optimized_starts"]} optimized starts.</p>
{primary_table}
{range_sensitivity}
<details><summary>Fit the background fraction and compare the far-field limit</summary>
{profiled_table}
<p>At every source position the extra uniform-angle fraction was optimized, including the all-signal and all-background
endpoints. The far-field comparison optimizes direction with the exact infinite-range geometry, using the same event
mixtures. The score gains describe this conditional model; they are not detection significances or calibrated distance
intervals. The two cobalt energies still give different best-fit distances.</p></details>
<details><summary>Clock-half and background fits</summary>{range_table}
<p>Profile support gives the lowest and highest sampled ranges within two log-score units of the optimum. Depth, energy and background
response lack independent calibration for these data. The support has no calibrated confidence level.</p></details></section>
<section class="panel" id="position"><h2>Position checks on the saved ADC</h2>
<p>The full-channel check scored all 34 contacts for each of {position["fitted_pairings"]:,} fitted pairings.
Refitting center positions with all contacts gave similar axis errors on the independent mixtures.
Lateral fitting reduced matched errors where six position-tested response grids covered the sites.</p>
{position_table}
<p>In the fresh five-second run, <strong>{coverage["2"]:,}</strong> pairings had grids for both sites and
<strong>{coverage["1"]:,}</strong> had a grid for one. The one-grid fit estimates that site's lateral coordinates
and keeps the other site at its strip center. All {coverage["1"]:,} one-grid fits converged with valid modeled timing crossings.
The twelve independent one-grid trials repeat one pair of injection coordinates across energy, phase and noise settings.</p>
<p>The complete optional lateral replay preserved all 3,822 original trigger identities and assigned weights.
The three line-window peak cells stayed unchanged; the four conditional 3D window fits moved only 0.16–0.47 mm.
Four additional archived lateral grids were tested on {additional['total_conditions']} independent conditions:
their axis RMS error changed from {number(additional['axis_rmse_deg'][0])}° to
{number(additional['axis_rmse_deg'][1])}°, although XY and depth errors decreased. Those grids were not added to the released overlay.</p>
<h3>A small residual does not establish two interactions</h3>
<p>Independent off-template native traces supplied {uncertainty['positive_conditions']} two-point readout conditions
and {uncertainty['negative_conditions']} known three- or four-point conditions. Of the latter,
<strong>{false_returns}/{uncertainty['negative_conditions']}</strong> still produced a converged two-site interpretation
with an energy-allowed cone. These wrong models had valid timing and no fitted parameter at its boundary;
their all-channel residuals overlap those of genuine two-point conditions. No residual acceptance threshold was adopted.</p>
{topology_table}
<p>The signed position/energy errors, all trial outcomes and whole-geometry covariance summaries are retained in the
evidence JSON. Repeated phases and noise realizations share the same physical points; their covariance is descriptive
and is not a detector-wide uncertainty calibration. The comparison follows the useful same-input distinction between
exact and resolution-degraded data in <a href="https://doi.org/10.1118/1.4959551">Andreyev et al. (2016)</a>, while
retaining this detector's own signals and geometries.</p>
{cone_spread_section(data)}
<details><summary>Historical photon and deposit geometry controls</summary>
<p>A separate archived replay links {held["matched_exact_photon_occurrences"]} occurrences to
{held["independent_original_groups"]} original interaction groups with verified photon vertices.
Only two matched line-energy occurrences deposited the photon birth energy in germanium.
The evidence retains measured fit positions, photon vertices and energy-weighted deposit centroids as distinct values.
For the fresh five-second archive, the ten targeted replays above now establish those selected photon histories;
other trigger contexts retain uncertain causal associations.</p></details></section>
<section class="panel" id="data"><h2>Data and methods</h2>
<p>{counts["clock_live_time_ns"]/1e9:g} s from one chronological Cs-137/Co-60 acquisition yielded
{counts["qualified_triggers"]:,} qualified triggers, {counts["qualified_energies"]:,} measured energies and
{counts["two_strip_triggers"]:,} two-strip candidates. The source census contains {census["initial_parents"]:,} new parents
and {census["initial_daughter_decays"]:,} initial daughters. The original readout excluded
{census["unavailable_native_groups"]:,} unavailable response groups, leaving {counts["qualified_adc_live_time_ns"]/1e9:.9f} s
of qualified readout time.</p>
<p><a href="{DATA.name}">Open the exact map arrays, fit results and original trigger evidence (JSON)</a>.</p>
<p><a href="../gegi-shared-readout/index.html">Earlier GeGI readout study with 25 archived-library windows</a> ·
<a href="../../methods/index.html">Signal-chain methods</a></p>
<p>{references}</p></section></div>'''


def render(site):
    target = site / DATA
    if not target.is_file():
        return
    from site_restructure import READER_STYLE, write_page

    data = json.loads(target.read_bytes())
    if (data['kind'] != 'gegi_public_five_second_reconstruction_v1' or
            sha256((site / IMAGE).read_bytes()).hexdigest() != data['figure_sha256'] or
            sha256((site / ENERGY_IMAGE).read_bytes()).hexdigest() != data['energy_offsets']['figure_sha256'] or
            sha256((site / KINEMATICS).read_bytes()).hexdigest() != data['source_sha256']['kinematics']):
        raise ValueError('The saved five-second exhibit figure and evidence do not match')
    styles = READER_STYLE + '''
.gegi-five-second-figure{margin:14px 0 18px}.gegi-five-second-figure img{max-width:100%;height:auto}
.gegi-five-second-figure figcaption{font-size:.94rem;color:#526575}
.reader-page details details{margin:8px 0}.reader-page th[scope="row"]{min-width:8rem}
'''
    write_page(site / PAGE, TITLE + ' · GeSignal', sections(data), 2, extra_style=styles)
