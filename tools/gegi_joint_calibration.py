"""Portable center-template calibration for measured GeGI two-strip fits."""

from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
from time import perf_counter

import numpy as np

import gegi_digital_readout as digital
from gegi_event_store import encoded, sha
from gegi_joint_two_site import DEPTH_MM, SAMPLE_NS, VOLTAGE_NS, Template, fit_pairing


KIND = 'gegi_joint_center_calibration_v1'
FIELD_KEYS = ('model_sha256', 'field_cache_sha256', 'field_precision_bits')
DIGITAL_KEYS = ('digital_profile_sha256', 'digital_timing_sha256')
IDENTITY_KEYS = FIELD_KEYS + DIGITAL_KEYS
AXES = {'depth_mm': DEPTH_MM.tolist(), 'analog_time_from_onset_ns': VOLTAGE_NS.tolist(),
        'adc_time_from_trigger_ns': SAMPLE_NS.tolist(), 'contact_ids': list(digital.CONTACT_IDS)}
UNITS = {'center_templates': 'V/keV', 'center_template_storage': 'little-endian float64',
         'strip_centers': 'mm', 'face_depths': 'mm', 'fast': 'keV-equivalent', 'centered_cfd': 'ns', 'pair_cfd': 'ns'}
TEMPLATE_SHAPE = (len(DEPTH_MM), len(digital.CONTACT_IDS), len(VOLTAGE_NS))


def require_identity(acquisition, identity):
    sources = acquisition['sources']
    if (not sources or any(source['original'].get(key) != identity[key] for source in sources for key in FIELD_KEYS)
            or any(acquisition['receipt'][key] != identity[key] for key in DIGITAL_KEYS)):
        raise ValueError('Acquisition and calibration templates must share detector fields and a digital profile')


def _geometry(channels):
    if [c['id'] for c in channels] != AXES['contact_ids']:
        raise ValueError('Center calibration channels must follow the original 34-contact order')
    families = [[c for c in channels if c['family'] == family and c['guard'] is False] for family in 'XY']
    if any(len(family) != 16 or any(not math.isfinite(c['strip_center_mm']) for c in family) for family in families):
        raise ValueError('Center calibration has invalid X/Y strip geometry')
    pitch = families[0][1]['strip_center_mm'] - families[0][0]['strip_center_mm']
    if not math.isfinite(pitch) or pitch <= 0:
        raise ValueError('Center calibration has invalid X/Y strip geometry')
    centers = {c['id']: c['strip_center_mm'] for family in families for c in family}
    cells = {(x['id'], y['id']) for x in families[0] for y in families[1]}
    return centers, pitch, cells


def detector_cells(channels):
    return _geometry(channels)[2]


def _validate(manifest, voltage):
    if manifest.get('kind') != KIND or manifest.get('axes') != AXES or manifest.get('units') != UNITS:
        raise ValueError('Unsupported GeGI center calibration format, units or sample grids')
    identity = manifest['identity']
    if (identity.get('field_precision_bits') not in (32, 64)
            or any(not re.fullmatch(r'[0-9a-f]{64}', identity.get(key, '')) for key in IDENTITY_KEYS if key.endswith('_sha256'))
            or any(identity[key] != expected for key, expected in zip(
                DIGITAL_KEYS, (digital.PROFILE_SHA256, digital.TIMING_SHA256), strict=True))):
        raise ValueError('Center calibration has invalid field identity or incompatible digital settings')
    scales = manifest['feature_scales']
    if any(not math.isfinite(scales[key]) or scales[key] <= 0 for key in ('fast', 'centered_cfd', 'pair_cfd')):
        raise ValueError('Center calibration has invalid feature scales')
    centers, pitch, detector_cells = _geometry(manifest['channels'])
    requested, calibrated, missing = ([tuple(cell) for cell in manifest[key]] for key in
                                      ('requested_cells', 'calibrated_cells', 'missing_cells'))
    if (any(cells != sorted(set(cells)) for cells in (requested, calibrated, missing))
            or set(requested) != set(calibrated) | set(missing) or set(calibrated) & set(missing)
            or not set(requested) <= detector_cells):
        raise ValueError('Center calibration cell coverage is inconsistent with the detector geometry')
    if (voltage.dtype != np.dtype('<f8') or voltage.shape != (len(calibrated), *TEMPLATE_SHAPE)
            or not voltage.flags.c_contiguous or not np.isfinite(voltage).all()
            or sha(voltage) != manifest['center_sha256']):
        raise ValueError('Center calibration template samples or their hash differ')
    return centers, pitch, calibrated


def save(path, *, identity, channels, scales, requested, templates, provenance):
    """Export lossless center responses and a manifest; leave existing files intact."""
    calibrated = sorted(templates)
    voltage = np.empty((len(calibrated), *TEMPLATE_SHAPE), dtype='<f8')
    centers, pitch, _ = _geometry(channels)
    for i, (x, y) in enumerate(calibrated):
        template = templates[x, y]
        if (template.cell != (x, y) or template.origin_mm != (centers[x], centers[y]) or template.pitch_mm != pitch
                or template.center_v_per_keV.shape != TEMPLATE_SHAPE):
            raise ValueError('Center calibration template and contact geometry differ')
        voltage[i] = template.center_v_per_keV
    manifest = {'kind': KIND, 'identity': {k: identity[k] for k in IDENTITY_KEYS},
                'axes': AXES, 'units': UNITS, 'channels': channels, 'feature_scales': scales,
                'requested_cells': sorted(requested), 'calibrated_cells': calibrated,
                'missing_cells': sorted(set(requested) - set(calibrated)), 'center_sha256': sha(voltage),
                'provenance': provenance}
    manifest_bytes = encoded(manifest)
    _validate(json.loads(manifest_bytes), voltage)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        np.savez_compressed(stream, manifest_utf8=np.frombuffer(manifest_bytes, dtype=np.uint8), center_v_per_keV=voltage)
    return manifest, sha(manifest_bytes)


def load(path):
    """Load the center models without consulting the template-generation archives."""
    with path.open('rb') as stream:
        archive_hash = hashlib.sha256()
        for block in iter(lambda: stream.read(1 << 20), b''):
            archive_hash.update(block)
        stream.seek(0)
        with np.load(stream, allow_pickle=False) as archive:
            manifest_bytes = archive['manifest_utf8'].tobytes()
            manifest = json.loads(manifest_bytes)
            voltage = archive['center_v_per_keV']
    centers, pitch, calibrated = _validate(manifest, voltage)
    templates = {(x, y): Template((x, y), (centers[x], centers[y]), pitch, values)
                 for (x, y), values in zip(calibrated, voltage, strict=True)}
    return manifest, templates, sha(manifest_bytes), archive_hash.hexdigest()


def measured_selection(acquisition):
    records = [r for r in acquisition['triggers'] if r.get('two_strip_pairings') is not None]
    cells = {(s['x_contact_id'], s['y_contact_id']) for r in records for p in r['two_strip_pairings']['pairings']
             if p['energy_compatible'] for s in p['sites']}
    return records, cells


def fit_windows(acquisition, report_sha, records, windows_path, channels, templates, scales, *, portable=False):
    receipt = acquisition['receipt']
    with np.load(windows_path, allow_pickle=False) as data:
        if (str(data['report_sha256']) != report_sha or str(data['known_component_adc_sha256']) != receipt['known_component_adc_sha256']
                or not np.array_equal(data['relative_time_ns'], SAMPLE_NS)
                or not np.array_equal(data['contact_ids'], [c['id'] for c in channels])
                or not np.array_equal(data['trigger_time_ns'], [r['trigger_time_ns'] for r in records])):
            raise ValueError('ADC windows, channel order, or acquisition identity differ')
        codes, volts = data['adc_codes'], float(data['volts_per_code'])
        statuses, ordinals = data['window_status'].tolist(), data['two_strip_ordinal'].tolist()
        if portable and (
            any(str(data[key]) != receipt[key] for key in DIGITAL_KEYS)
            or volts != digital._LSB_V or codes.dtype != np.dtype('<i2')
            or codes.shape != (len(ordinals), len(channels), len(SAMPLE_NS))
            or len(statuses) != len(records)
            or ordinals != [i for i, status in enumerate(statuses, 1) if status == 'captured']
        ):
            raise ValueError('Portable ADC window profile, sample shape, scale or window coverage differs')
        windows = dict(zip(ordinals, codes * volts, strict=True))
    fits = []
    for ordinal, record in enumerate(records, 1):
        event = record['two_strip_pairings']
        row = dict(ordinal=ordinal, time_ns=record['trigger_time_ns'], window_status=statuses[ordinal-1],
                   flags=event['flags'], pairings=[])
        for pairing in event['pairings']:
            fit = fit_pairing(pairing, event['collectors'], templates, scales, local_adc_volts=windows.get(ordinal))
            row['pairings'].append(dict(index=pairing['index'], energy_compatible=pairing['energy_compatible'],
                cells=[[s['x_contact_id'], s['y_contact_id']] for s in pairing['sites']],
                apparent_depths_mm=[s['apparent_depth_mm'] for s in pairing.get('pixel_depths', [])],
                compton_orders=pairing['compton_orders'], fit=fit))
        fits.append(row)
    return fits


def measured_receipt(acquisition, acquisition_sha, windows_path, fits, templates, input_hashes, source_hashes, started):
    return dict(kind='gegi_joint_continuous_acquisition_study_v1', qualified_triggers=acquisition['counts']['qualified_triggers'],
                two_strip_triggers=len(fits), fitted_status_counts=Counter(p['fit']['status'] for r in fits for p in r['pairings']),
                score_scope='Measured ADC fits only. Transport truth was omitted.',
                timing_scope='Simultaneous templates at a shared onset, measured slow energies and local voltage tails.',
                lateral_template_cells=[cell for cell, t in templates.items() if t.lateral_correction_v_per_keV is not None],
                acquisition_sha256=acquisition_sha, input_sha256=input_hashes,
                adc_windows_sha256=sha(windows_path.read_bytes()), source_sha256=source_hashes,
                elapsed_s=perf_counter()-started, summary={}, candidates=fits)


def fit_portable_acquisition(acquisition, acquisition_sha256, windows_path, calibration_path):
    """Fit eligible measured pairings using only the supplied center archive and ADC windows."""
    started = perf_counter()
    manifest, templates, content_hash, archive_hash = load(calibration_path)
    require_identity(acquisition, manifest['identity'])
    records, cells = measured_selection(acquisition)
    fits = fit_windows(acquisition, acquisition_sha256, records, windows_path,
                       manifest['channels'], templates, manifest['feature_scales'], portable=True)
    source_paths = (Path(__file__), Path(__file__).with_name('gegi_joint_two_site.py'))
    source_hashes = {p.name: sha(p.read_bytes()) for p in source_paths}
    result = measured_receipt(acquisition, acquisition_sha256, windows_path, fits, templates,
                              {'acquisition': acquisition_sha256}, source_hashes, started)
    result['calibration_bundle'] = {'archive_sha256': archive_hash, 'content_sha256': content_hash,
                                    'identity': manifest['identity'], 'requested_cells': sorted(cells),
                                    'calibrated_cells': sorted(cells & templates.keys()),
                                    'missing_cells': sorted(cells - templates.keys())}
    return result
