"""Replay one sealed GeGI native event through the independent digital readout."""
import hashlib
import math
from pathlib import Path

import gegi_event_store as S
import gegi_imaging as I
import scenario_workflow as W

CALIBRATION = Path(__file__).with_name('gegi_substrip_calibration.json')


def single_pixel(digital, channel_metadata):
    """Classify observable strip topology using the digital slow branch only."""
    from gegi_digital_pairs import slow_collectors

    hits, invalid = slow_collectors(digital)
    outcome = {'status': 'unresolved', 'reason': None, 'threshold_keV': I.MIN_COLLECTED_KEV,
               'collecting_contact_ids': sorted(hits), 'energy_keV': None,
               'x_contact_id': None, 'y_contact_id': None}
    if any(c['id'] in hits and c['guard'] for c in channel_metadata):
        outcome['reason'] = 'A guard exceeds the collecting threshold.'
        return outcome
    if invalid:
        outcome['reason'] = 'At least one slow channel has an invalid or incomplete energy measurement.'
        return outcome
    xs, ys = ([c['id'] for c in channel_metadata if c['family'] == family and c['id'] in hits]
              for family in ('X', 'Y'))
    if len(xs) > 1 or len(ys) > 1:
        outcome['reason'] = 'Multiple strips exceed the collecting threshold. Charge sharing or overlapping sites are unresolved.'
        return outcome
    if not xs or not ys:
        outcome['reason'] = 'At least one face has no strip above the collecting threshold.'
        return outcome
    x, y = xs[0], ys[0]
    ex, ey = hits[x], hits[y]
    if abs(ex - ey) > max(I.PAIR_ABS_KEV, I.PAIR_REL * max(ex, ey)):
        outcome['reason'] = 'The two faces disagree beyond the 2 keV or 2% energy tolerance.'
        return outcome
    return dict(outcome, status='conditional_single_pixel', energy_keV=(ex+ey)/2,
                x_contact_id=x, y_contact_id=y)


def _compton_orders(sites):
    """Evaluate the two energy assignments conditional on full photon absorption."""
    orders = []
    for first, second in ((0, 1), (1, 0)):
        scatter, absorbed = sites[first]['energy_keV'], sites[second]['energy_keV']
        # Match the energy expression and closed cosine interval in I.cone.
        cosine = 1-I.ELECTRON_REST_KEV*(1/absorbed-1/(scatter+absorbed))
        allowed = -1 <= cosine <= 1
        orders.append({'site_index_order': [first, second], 'kinematically_allowed': allowed,
                       'half_angle_deg': math.degrees(math.acos(cosine)) if allowed else None,
                       'cos_theta': cosine, 'scatter_energy_keV': scatter,
                       'absorbed_energy_keV': absorbed})
    return orders


def analyze_event(event, native, channel_metadata, *, calibration=None, source_identity=None,
                  include_traces=True, noise_seed=None):
    from gegi_digital_pairs import two_site_pairings
    from gegi_digital_readout import digital_event, terminal_contacts_complete
    from gegi_substrip import infer_position

    digital = digital_event(native, channel_metadata, terminal_complete=terminal_contacts_complete(event),
                            noise_seed=noise_seed, include_traces=include_traces,
                            horizon_ns=event.get('readout_horizon_ns'))
    topology = single_pixel(digital, channel_metadata)
    position = None
    if topology['status'] == 'conditional_single_pixel' and calibration is not None:
        inputs = calibration, topology['x_contact_id'], topology['y_contact_id'], digital, channel_metadata
        position = infer_position(*inputs, source_identity=source_identity, mode='cfd_conditioned')
        pooled = infer_position(*inputs, source_identity=source_identity)
        position['pooled_axes'] = {axis: pooled[axis] for axis in ('x', 'y')}
    pairs = two_site_pairings(digital, channel_metadata, calibration=calibration, source_identity=source_identity)
    pairs['compton_order_scope'] = 'Conditional on one fully absorbed photon.'
    for pairing in pairs['pairings']:
        pairing['compton_orders'] = _compton_orders(pairing['sites']) if pairing['energy_compatible'] else []
    return {'status': 'available', 'reason': None, 'readout': digital, 'topology': topology,
            'position': position, 'pairs': pairs}


def _source_line(run, stamps, measured_keV):
    expected = stamps.get('selection.json', {}).get('sha256')
    if expected is None:
        return None
    data = W.safe_path(run, 'selection.json').read_bytes()
    W.require(hashlib.sha256(data).hexdigest() == expected,
              'Original GeGI source selection differs from the completed run.')
    selection = W.decode_json(data.decode('utf-8-sig'))
    energy = selection.get('gamma_energy_keV')
    if selection.get('source') == 'gegi_mono_gamma_v1' and I.finite(energy) and energy > 0:
        return {'energy_keV': energy, 'measured_minus_line_keV': measured_keV - energy}
    return None


def load_saved_native(event, channel_metadata, run, *, configuration_sha256):
    """Load signed native charge with the original event, wiring and run seals."""
    if event.get('channels') is None:
        return {'status': 'unavailable', 'reason': 'Native carrier response failed for this primary.'}
    if event.get('signals_ref') is None and event.get('signals_sha256') is None:
        return {'status': 'unavailable', 'reason': 'This saved primary has no original signed native charge file.'}
    ref = f'events/{event["event_id"]}-signals.csv'
    complete = W.read(W.safe_path(run, 'COMPLETE.json'))
    receipt_path = W.safe_path(run, 'response/run.json')
    receipt = W.read(receipt_path)
    stamps = complete.get('artifacts', {})
    expected = event.get('signals_sha256')
    W.require(complete.get('configuration_sha256') == receipt.get('configuration_sha256') == configuration_sha256
              and complete.get('status') in W.TERMINAL and receipt.get('status') in W.TERMINAL
              and stamps.get('response/run.json', {}).get('sha256') == W.sha(receipt_path)
              and type(expected) is str and event.get('signals_ref') == ref
              and receipt.get('artifacts', {}).get(ref) == expected
              and stamps.get('response/'+ref, {}).get('sha256') == expected,
              'Original GeGI native signal metadata differs from the completed run.')
    path = W.safe_path(run, 'response/'+ref)
    W.require(path.stat().st_size == stamps['response/'+ref]['bytes'] <= 64*1024*1024
              and W.sha(path) == expected, 'Original GeGI native signal data changed or exceed the viewer limit.')
    channels = event['channels']
    W.require(receipt.get('channels') == channel_metadata and len(channels) == len(channel_metadata) == 34
              and all(c['contact_id'] == m['id'] and c['wiring_factor'] == m['wiring_factor']
                      for c, m in zip(channels, channel_metadata)),
              'Original GeGI electrode census or wiring differs.')
    native = S.native_csv(path, channels)
    W.require(W.sha(path) == expected and all(native[c['contact_id']]['signed_induced_keV'][-1] ==
              c['final_induced_keV'] for c in channels), 'Original GeGI signed native signals differ.')
    fields = receipt.get('fields') or {}
    source = {'model_sha256': receipt.get('model_sha256'), 'field_cache_sha256': fields.get('cache_sha256'),
              'field_precision_bits': fields.get('precision_bits')}
    return {'status': 'available', 'native': native, 'source': source,
            'stamps': stamps, 'native_signals_sha256': expected}


def from_saved_event(event, channel_metadata, run, *, configuration_sha256,
                     calibration_path=CALIBRATION, include_traces=True):
    """Use one selected native CSV, bound to the original event and run seals."""
    from gegi_substrip import load_calibration

    saved = load_saved_native(event, channel_metadata, run, configuration_sha256=configuration_sha256)
    if saved['status'] != 'available':
        return saved
    calibration = load_calibration(calibration_path) if calibration_path is not None else None
    result = analyze_event(event, saved['native'], channel_metadata, calibration=calibration, source_identity=saved['source'],
                           include_traces=include_traces)
    pairs = result['pairs']
    if pairs['compatible_pairing_count']:
        line = _source_line(run, saved['stamps'], pairs['energy_keV'])
        if line is not None:
            pairs['source_line'] = line
    return dict(result, native_signals_sha256=saved['native_signals_sha256'])
