"""Saved-signal GeGI reconstruction, independent of source labels and event truth.

This is a bounded, conditional inverse model, not validated detector performance.
Independent injection waveforms constrain depth jointly; threshold crossings are
diagnostics only. Default selected-pair and explicit full34 modes retain their
template coverage limits. No transport, field, drift, or injection code is called.

Primary method context (COSI parameters are NOT GeGI parameters):
https://arxiv.org/html/1911.02992v1
https://arxiv.org/html/2602.02442v1
"""
from __future__ import annotations
import hashlib
from contextlib import closing
import itertools
import json
import math
from pathlib import Path
import sqlite3
import zlib
import numpy as np
import gegi_event_store as S
import gegi_imaging as I
import gegi_signal_recovery as U

KIND = 'gegi_saved_signal_hypotheses_v3'
FIT_GRID_NS = np.arange(0., 252., 2.)
ALL34_IDS = list(range(1, 35))
ALL34_COVERAGE = {'kind': 'gegi_all34_signed_induced_v1', 'contact_ids': ALL34_IDS,
    'time_unit': 'ns', 'signal_unit': 'keV', 'polarity': 'native_signed_before_wiring'}
ALL34_METHOD = 'joint_signed_all34_waveform_template_fit'
ALL34_WEIGHTING = 'collecting_terminal_else_flow_total'
LIMITATIONS = [
    'Simulation-derived independent injections, not laboratory calibration.',
    'Only the selected X/Y injection signals were saved; induction on other strips is not modelled.',
    'Charge pixels are not necessarily separate photon interactions: electron paths and charge sharing can span strips.',
    'The sparse energy-flow hypotheses do not exhaust continuous N:N energy allocations, subthreshold pixels, or same-pixel multiplicity.',
    'Profile depth intervals are deterministic calibration-discrepancy sets, not confidence intervals.',
    'Cones are conditional on one fully absorbed photon; cascade, escape and background alternatives remain unresolved.',
]


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def _canonical(v):
    return json.dumps(v, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _wave(signal, wiring=1):
    t = np.asarray(signal['time_ns'], dtype=float)
    q = np.asarray(signal['signed_induced_keV'], dtype=float) * wiring
    if (len(t) < 2 or t.shape != q.shape or not np.isfinite(t).all()
            or not np.isfinite(q).all() or not np.all(np.diff(t) > 0)):
        raise ValueError('Invalid signed native waveform')
    return t, q


def _response_cost(delta):
    return np.mean(delta**2, axis=(1, 2))


def _all34_observed_waves(observed):
    channels = observed['channels']
    if (len(channels) != 34 or {c['contact_id'] for c in channels} != set(ALL34_IDS)
            or set(observed['native']) != set(ALL34_IDS)
            or any(c['wiring_factor'] != (1 if c['contact_id'] <= 17 else -1) for c in channels)):
        raise ValueError('all34 observations require every channel and original fixed wiring')
    return {cid: _wave(observed['native'][cid], 1 if cid <= 17 else -1) for cid in ALL34_IDS}


def read_saved_group(path, event_id, group_id):
    """Read-only SQLite with metadata and native-array hash verification."""
    path = Path(path).resolve()
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        db.execute('PRAGMA query_only=ON')
        row = db.execute('SELECT metadata,metadata_sha256 FROM events WHERE primary_id=? AND group_id=?',
                         (event_id, group_id)).fetchone()
        if row is None:
            raise ValueError('Unknown saved group')
        body = zlib.decompress(row[0])
        if _sha(body) != row[1]:
            raise ValueError('Saved metadata hash changed')
        event = json.loads(body)
        native = None if event['native_signals'] is None else {}
        for cid, refs in (event['native_signals'] or {}).items():
            native[int(cid)] = {}
            for name, ref in refs.items():
                array = db.execute('SELECT count,value FROM arrays WHERE digest=?', (ref['sha256'],)).fetchone()
                if array is None or array[0] != ref['count']:
                    raise ValueError('Saved array missing or count changed')
                native[int(cid)][name] = S.unpack_array(ref['sha256'], *array)
    return event, native, row[1]


def observables(event, native, channels):
    """Explicit allowlist. Tracks, endpoints, Edep, source and old depth are unused."""
    result = {'event_id': event['event_id'], 'pulse_group_id': event.get('group_id', 0),
              'status': event['status'], 'channels': [], 'native': native}
    meta = {c['id']: c for c in channels}
    if event.get('channels') is None:
        result['channels'] = None
        if native is not None:
            raise ValueError('Native failure must retain null signals')
        return result
    for c in event['channels']:
        cid = c['contact_id']
        if cid not in meta:
            raise ValueError('Unknown channel')
        result['channels'].append({k: c.get(k) for k in
            ('contact_id', 'accepted', 'collection_candidate', 'final_induced_keV',
             'reconstructed_energy_keV', 'charge_clipped_at_window', 'saturated')})
        result['channels'][-1].update(wiring_factor=meta[cid]['wiring_factor'],
            strip_center_mm=meta[cid].get('strip_center_mm'),
            strip_pitch_mm=meta[cid].get('strip_pitch_mm', I.PITCH_MM))
    return result


def signal_diagnostics(observed):
    """All-channel signed diagnostics; crossings never choose a depth."""
    summaries = []
    for c in observed['channels']:
        cid = c['contact_id']; t, q = _wave(observed['native'][cid], c['wiring_factor'])
        if np.max(np.abs(q)) < 1e-9:
            continue
        crossings = []
        if q[-1] > 0:
            threshold = q[-1]/2
            for k in np.flatnonzero((q[:-1] < threshold) & (q[1:] >= threshold)):
                crossings.append(float(t[k]+(t[k+1]-t[k])*(threshold-q[k])/(q[k+1]-q[k])))
        summaries.append({'contact_id': cid, 'terminal_wired_keV': float(q[-1]),
            'minimum_wired_keV': float(q.min()), 'maximum_wired_keV': float(q.max()),
            'rising_half_terminal_crossings_ns': crossings,
            'collection_candidate': c['collection_candidate']})
    return {'channel_count': len(observed['channels']), 'nonzero_channels': summaries,
            'scope': 'Fixed family wiring, signed amplitudes; crossings are diagnostics and never depth inputs.'}


class TemplateBank:
    """Saved independent responses; all34 requires an explicit opt-in and full seal."""
    def __init__(self, calibration_dir, response_mode='selected_pair'):
        if response_mode not in ('selected_pair', 'all34'):
            raise ValueError('Unknown response mode; use selected_pair or all34')
        self.response_mode = response_mode
        self.root = Path(calibration_dir).resolve()
        raw = (self.root / 'depth-calibration.json').read_bytes()
        self.table = json.loads(raw)
        self.sha256 = _sha(raw)
        self.identity = json.loads((self.root / 'identity.json').read_bytes())
        if self.table['identity_sha256'] != _sha((self.root / 'identity.json').read_bytes()):
            raise ValueError('Calibration identity changed')
        self.channels = self.identity['channels']
        self.cache = {}
        self.bindings = {}
        self.error_envelope = None
        if response_mode == 'all34':
            self._admit_all34()

    def _admit_all34(self):
        if (self.identity.get('signal_coverage') != ALL34_COVERAGE
                or self.table.get('signal_coverage') != ALL34_COVERAGE):
            raise ValueError('all34 requires native signed coverage in identity and table')
        if ([c['id'] for c in self.channels] != ALL34_IDS
                or any(c['wiring_factor'] != (1 if c['id'] <= 17 else -1) for c in self.channels)):
            raise ValueError('all34 channel identities or fixed wiring convention changed')
        if (self.identity['injection_energy_keV'] != 500 or self.table['injection_energy_keV'] != 500
                or self.identity['depth_mm'] != list(range(-5, 6))
                or self.table['depth_mm'] != self.identity['depth_mm']):
            raise ValueError('all34 independent energy or fixed depth grid changed')
        complete_path = self.root.parent/'COMPLETE.json'
        if not complete_path.is_file():
            raise ValueError('all34 requires sealed COMPLETE; partial-bank fallback is forbidden')
        complete = json.loads(complete_path.read_bytes())
        if (complete.get('status') != 'completed_original_grid_full34_bank'
                or complete.get('selected_pair_mismatches') != 0):
            raise ValueError('all34 requires completed capture with zero selected-pair mismatches')
        raw = (self.root/'run.json').read_bytes(); run = json.loads(raw)
        if _sha(raw) != complete['bank_run_sha256'] or run['status'] != 'completed':
            raise ValueError('all34 requires a completed sealed bank')
        for ref in ('identity.json', 'depth-calibration.json', 'depth-diagnostics.json'):
            if _sha((self.root/ref).read_bytes()) != run['artifacts'][ref]:
                raise ValueError('all34 bank artifact hash changed: '+ref)
        outer_path = self.root.parent/'identity.json'; outer_raw = outer_path.read_bytes()
        outer = json.loads(outer_raw)
        if (_sha(outer_raw) != complete['bundle_identity_sha256']
                or outer['calibration_identity_sha256'] != self.table['identity_sha256']
                or outer['request_sha256'] != complete['request_sha256']):
            raise ValueError('all34 bundle identity changed')
        manifest_path = self.root.parent/'validation.jsonl'; raw = manifest_path.read_bytes()
        if _sha(raw) != complete['validation_sha256']:
            raise ValueError('all34 exact-record manifest changed')
        records = [json.loads(line) for line in raw.splitlines() if line]
        self.record_sha256 = {r['record_ref']: r['record_sha256'] for r in records}
        diagnostics = json.loads((self.root/'depth-diagnostics.json').read_bytes())
        self._all34_diagnostics = diagnostics
        regular = [r['record_ref'] for pixel in self.table['pixels'].values() for r in pixel['rows']]
        diagnostic = [r['record_ref'] for r in diagnostics['rows']]
        expected = regular+diagnostic
        if (complete['validated_records'] != len(records)
                or complete['full34_records']+complete['excluded_records'] != len(records)
                or len(records) != len(self.record_sha256) or len(expected) != len(set(expected))
                or set(expected) != set(self.record_sha256)
                or len(regular) != len(self.identity['pixel_order'])*len(self.identity['depth_mm'])
                or len(diagnostic) != math.prod(len(self.identity[k]) for k in
                    ('diagnostic_pixels', 'diagnostic_depth_mm', 'diagnostic_offsets_pitch_fraction'))
                or diagnostics['identity_sha256'] != self.table['identity_sha256']
                or diagnostics['total_fixed_injections'] != len(diagnostic)):
            raise ValueError('all34 regular/diagnostic record coverage is incomplete')
        for path in (complete_path, self.root/'run.json', outer_path, manifest_path,
                     self.root/'identity.json', self.root/'depth-calibration.json', self.root/'depth-diagnostics.json'):
            self.bindings[str(path.relative_to(self.root)) if path.is_relative_to(self.root)
                          else '../'+path.name] = _sha(path.read_bytes())

    def response(self, row, grid):
        if self.response_mode == 'all34':
            if row.get('signal_coverage') != ALL34_COVERAGE:
                raise ValueError('all34 injection lacks native signed coverage')
            signals = row.get('channel_signals')
            if not isinstance(signals, list) or [s['contact_id'] for s in signals] != ALL34_IDS:
                raise ValueError('all34 injection must contain every channel exactly once')
            waves = [_wave(s, 1 if s['contact_id'] <= 17 else -1) for s in signals]
        else:
            waves = [_wave(row['signals'][f], w) for f, w in (('X', 1), ('Y', -1))]
        energy = row['injection_energy_keV']
        if not math.isfinite(energy) or energy <= 0:
            raise ValueError('Independent injection energy must be positive and finite')
        if self.response_mode == 'all34' and energy != self.identity['injection_energy_keV']:
            raise ValueError('all34 injection energy differs from the fixed independent input')
        return np.asarray([np.interp(grid, t, q, left=0, right=q[-1])/energy for t, q in waves])

    def record(self, ref):
        path = (self.root / ref).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError('Calibration reference escaped root')
        raw = path.read_bytes()
        record = json.loads(raw)
        if self.response_mode == 'all34':
            # Julia and Python render tiny floating values differently. The sealed
            # wrapper already checked native payload SHA; use its exact file SHA.
            valid = (ref in self.record_sha256 and _sha(raw) == self.record_sha256[ref]
                and record.get('kind') == 'gegi_independent_injection_checkpoint_v1')
        else:
            valid = _sha(_canonical(record['payload'])) == record['payload_sha256']
        if record['identity_sha256'] != self.table['identity_sha256'] or not valid:
            raise ValueError('Independent injection checksum changed')
        self.bindings[ref] = _sha(raw)
        return record['payload']

    def pixel(self, x, y):
        key = f'{x}:{y}'
        if key not in self.cache:
            p = self.table['pixels'].get(key)
            if not p or p['status'] != 'available_model_approximation':
                self.cache[key] = None
            else:
                rows = [self.record(r['record_ref']) for r in p['rows']]
                if not all(r['valid'] and r['contact_ids'] == [x, y] for r in rows):
                    raise ValueError('Invalid independent template')
                self.cache[key] = rows
        return self.cache[key]

    def templates(self, x, y, grid):
        rows = self.pixel(x, y)
        if rows is None:
            return None
        out = []
        for row in rows:
            out.append(self.response(row, grid))
        return np.asarray(out)

    def calibrate_discrepancy(self):
        """Read saved held-out positions only; never generates new injections.

        The maximum normalized residual across the fixed independent diagnostic
        set is a finite envelope, not a global bound or measured noise model.
        """
        if self.error_envelope is not None:
            return self.error_envelope
        all34 = self.response_mode == 'all34'
        report = (self._all34_diagnostics if all34
                  else json.loads((self.root / 'depth-diagnostics.json').read_bytes()))
        residuals, channel_residuals, errors, excluded = [], [], [], 0
        for r in report['rows']:
            row = self.record(r['record_ref'])
            if not row.get('valid') or self.pixel(*row['contact_ids']) is None:
                excluded += 1
                continue
            grid = FIT_GRID_NS
            target = self.response(row, grid)
            options = self.templates(*row['contact_ids'], grid)
            # Piecewise interpolation of complete waveforms, not threshold times.
            fine = np.concatenate([options[i:i+1]*(1-f)+options[i+1:i+2]*f
                for i in range(len(options)-1) for f in (0., .25, .5, .75)] + [options[-1:]])
            if all34:
                # Responses retain the fixed injection gain. Weight both sides
                # of each residual by this diagnostic's observed terminal scale.
                scales = np.ones(34)
                for cid in row['contact_ids']:
                    scales[cid-1] = _wave(row['channel_signals'][cid-1],
                        1 if cid <= 17 else -1)[1][-1]/row['injection_energy_keV']
                if not np.all(scales > 0):
                    raise ValueError('all34 diagnostic requires positive collected terminal charge')
                target = target/scales[:, None]
                fine = fine/scales[None, :, None]
            costs = _response_cost(fine-target)
            best = int(np.argmin(costs))
            residuals.append(float(np.sqrt(costs[best])))
            channel_residuals.append(float(np.sqrt(np.mean((fine[best]-target)**2, axis=1)).max()))
            errors.append(float(abs(-5 + .25*best-row['position_mm'][2])))
        if not residuals:
            raise ValueError('No independent diagnostic support')
        self.error_envelope = {'normalized_rms': max(residuals), 'depth_error_mm': max(errors),
            'max_channel_normalized_rms': max(channel_residuals),
            'diagnostic_count': len(residuals), 'excluded_count': excluded,
            'scope': 'Maximum on saved fixed independent diagnostic injections; not a confidence level.'}
        if all34:
            self.error_envelope.update(response_mode='all34',
                residual_weighting=ALL34_WEIGHTING,
                normalization='Same residual scale for data and model: positive wired terminal on selected collectors; fixed injection energy on other channels. Template gain is unchanged.',
                objective='least-squares fit across all channels/time; acceptance uses maximum channel RMS on the fixed diagnostics',
                fixed_diagnostic_count=len(report['rows']))
        return self.error_envelope


def energy_flows(xs, ys, max_hypotheses=64, max_sites=4):
    """Nonnegative sparse joint energy fits within unchanged channel tolerances.

    Enumerate covered bipartite supports, solving one energy per X/Y pixel.
    ADC differences therefore do not create tiny fictitious charge pixels.
    Rank-deficient supports retain an explicit unidentifiable alternative rather
    than selecting one arbitrary allocation from a continuum. Original channel
    values and fixed gain are never rewritten.
    """
    a = np.array([c['reconstructed_energy_keV'] for c in xs])
    b = np.array([c['reconstructed_energy_keV'] for c in ys])
    if abs(a.sum()-b.sum()) > max(I.PAIR_ABS_KEV, I.PAIR_REL*max(a.sum(), b.sum())):
        return [], {'reason': 'face_energy_mismatch'}
    values = np.r_[a, b]
    tolerance = np.maximum(I.PAIR_ABS_KEV, I.PAIR_REL*values)
    edges = list(itertools.product(range(len(xs)), range(len(ys))))
    flows = []; rank_deficient = 0
    for count in range(max(len(xs), len(ys)), min(max_sites, len(edges))+1):
        for support in itertools.combinations(edges, count):
            if len({x for x,y in support}) != len(xs) or len({y for x,y in support}) != len(ys):
                continue
            matrix = np.zeros((len(values), count))
            for k, (x, y) in enumerate(support):
                matrix[x, k] = matrix[len(xs)+y, k] = 1.
            energy, _, rank, _ = np.linalg.lstsq(matrix/tolerance[:, None], values/tolerance, rcond=None)
            if rank < count:
                rank_deficient += 1
                continue
            if np.any(energy < I.MIN_COLLECTED_KEV) or np.any(np.abs(matrix@energy-values) > tolerance+1e-9):
                continue
            flows.append([(xs[x]['contact_id'], ys[y]['contact_id'], float(e)) for (x,y),e in zip(support,energy)])
            if len(flows) > max_hypotheses:
                return [], {'reason': 'energy_hypothesis_budget_exceeded', 'max_hypotheses': max_hypotheses}
    bookkeeping = {'original_x_sum_keV': float(sum(c['reconstructed_energy_keV'] for c in xs)),
        'original_y_sum_keV': float(sum(c['reconstructed_energy_keV'] for c in ys)),
        'continuous_NxN_allocations_exhausted': False, 'rank_deficient_supports': rank_deficient,
        'fit': 'Weighted least squares within existing 2keV/2% channel compatibility tolerance; not gain recalibration.'}
    if not flows:
        bookkeeping['reason'] = 'no_supported_sparse_energy_allocation'
    return flows, bookkeeping


def _fit_flow(flow, observations, bank, envelope, *, all34_waves=None):
    all34 = getattr(bank, 'response_mode', 'selected_pair') == 'all34'
    if all34 and envelope.get('response_mode') != 'all34':
        raise ValueError('all34 fit requires the matching all34 diagnostic envelope')
    if all34 and envelope.get('residual_weighting') != ALL34_WEIGHTING:
        raise ValueError('all34 fit requires the matching residual weighting')
    ids = ALL34_IDS if all34 else sorted({cid for x, y, _ in flow for cid in (x, y)})
    index = {cid: i for i, cid in enumerate(ids)}
    waves = (all34_waves if all34_waves is not None else _all34_observed_waves(observations)) if all34 else {
        cid: _wave(observations['native'][cid], 1 if cid <= 17 else -1) for cid in ids}
    # Fixed window also used for independent diagnostics prevents plateau-length
    # dilution of residuals. Reject activity beyond it instead of silently cropping.
    grid = FIT_GRID_NS
    for t, q in waves.values():
        if np.any(np.abs(q[t > grid[-1]]-q[-1]) > max(1e-7, abs(q[-1])*1e-8)):
            return {'status': 'unsupported', 'reason': 'delayed_waveform_outside_template_support'}
    target = np.asarray([np.interp(grid, *waves[cid], left=0, right=waves[cid][1][-1]) for cid in ids])
    # Collected channels retain their positive-terminal residual weight. Other
    # full34 channels share the observed energy total, preserving bipolar signals.
    total_energy = sum(e for _, _, e in flow)
    collecting_ids = {cid for x, y, _ in flow for cid in (x, y)}
    scales = np.asarray([waves[cid][1][-1] if cid in collecting_ids else total_energy for cid in ids])
    if all34 and (not math.isfinite(total_energy) or total_energy <= 0):
        raise ValueError('all34 energy-flow scale must be positive and finite')
    if not np.all(scales > 0):
        return {'status': 'unsupported', 'reason': 'nonpositive_collected_terminal_charge'}
    target /= scales[:, None]
    bases = []
    for x, y, e in flow:
        options = bank.templates(x, y, grid)
        if options is None:
            return {'status': 'unsupported', 'reason': 'pixel_template_unavailable', 'pixel': [x, y]}
        fine = np.concatenate([options[i:i+1]*(1-f)+options[i+1:i+2]*f
            for i in range(len(options)-1) for f in (0., .25, .5, .75)] + [options[-1:]])
        if all34:
            full = fine * e/scales[None, :, None]
        else:
            full = np.zeros((len(fine), len(ids), len(grid)))
            full[:, index[x], :] = fine[:, 0, :] * e/scales[index[x]]
            full[:, index[y], :] = fine[:, 1, :] * e/scales[index[y]]
        bases.append(full)
    # Three deterministic starts guard against one coordinate-descent minimum.
    fits = []
    for start in (0, 20, 40):
        choices = [start] * len(flow)
        model = sum(b[c] for b, c in zip(bases, choices))
        for _ in range(8):
            previous = choices.copy()
            for k, base in enumerate(bases):
                residual = target-model+base[choices[k]]
                costs = _response_cost(base-residual)
                new = int(np.argmin(costs)); model += base[new]-base[choices[k]]; choices[k] = new
            if choices == previous: break
        objective = float(np.mean((target-model)**2))
        fits.append((objective, choices, model))
    cost, choices, model = min(fits, key=lambda f: f[0])
    rms = math.sqrt(cost)
    channel_rms = np.sqrt(np.mean((target-model)**2, axis=1))
    sites = []
    metadata = {c['contact_id']: c for c in observations['channels']}
    for k, ((x, y, energy), base) in enumerate(zip(flow, bases)):
        residual = target-model+base[choices[k]]
        costs = _response_cost(base-residual)
        compatible = np.flatnonzero(costs <= cost + envelope['normalized_rms']**2 + 1e-15)
        lo, hi = -5+.25*int(compatible[0]), -5+.25*int(compatible[-1])
        z = -5+.25*choices[k]
        sx, sy = metadata[x], metadata[y]
        px = sx['strip_center_mm'] if sx['strip_center_mm'] is not None else (x-8.5)*I.PITCH_MM
        py = sy['strip_center_mm'] if sy['strip_center_mm'] is not None else (y-25.5)*I.PITCH_MM
        sz = max(.25/math.sqrt(12), (hi-lo)/math.sqrt(12), envelope['depth_error_mm']/math.sqrt(3))
        sites.append({'position_mm': [px, py, z], 'energy_keV': energy,
            'x_contact': x, 'y_contact': y, 'depth_support_mm': [lo, hi],
            'position_covariance_mm2': np.diag([sx['strip_pitch_mm']**2/12, sy['strip_pitch_mm']**2/12, sz**2]).tolist(),
            'energy_sigma_keV': None,
            'energy_compatibility_scale_keV': max(I.PAIR_ABS_KEV, I.PAIR_REL*energy),
            'method': ALL34_METHOD if all34 else 'joint_signed_selected_pair_waveform_template_fit'})
    gate = envelope['max_channel_normalized_rms'] if all34 else envelope.get('max_channel_normalized_rms', envelope['normalized_rms'])
    result = {'status': 'conditional_fit' if max(channel_rms) <= gate+1e-12 else 'model_mismatch',
        'normalized_rms': rms, 'diagnostic_envelope': envelope['normalized_rms'], 'sites': sites,
        'channel_normalized_rms': {str(cid): float(v) for cid, v in zip(ids, channel_rms)},
        'max_channel_diagnostic_envelope': gate, 'fit_window_ns': [0., float(grid[-1])],
        'start_solutions_depth_mm': [[-5+.25*c for c in f[1]] for f in fits],
        'depth_profile_holds_other_sites_fixed': True}
    if all34:
        result.update(response_mode='all34', method=ALL34_METHOD, global_energy_scale_keV=total_energy,
            residual_weighting=ALL34_WEIGHTING,
            channel_residual_scales_keV={str(cid): float(v) for cid, v in zip(ids, scales)},
            max_channel_normalized_rms=float(max(channel_rms)),
            normalization='Data and complete summed model share each channel scale: positive wired terminal for flow collectors; observed ADC energy-flow total for other channels. Residual weighting, not gain correction.',
            objective='least-squares weighted fit across all channels/time; separate maximum-channel acceptance gate; finite diagnostic envelope, not noise or confidence')
    return result


def sequence_candidates(sites):
    """Conditional full-absorption sequences; do not treat charge pixels as truth."""
    if not 2 <= len(sites) <= 4:
        return []
    result = []
    for order in itertools.permutations(range(len(sites))):
        ordered = [sites[k] for k in order]; valid = True
        for i in range(len(ordered)-1):
            remaining = sum(s['energy_keV'] for s in ordered[i+1:])
            e = ordered[i]['energy_keV']; cos = 1-I.ELECTRON_REST_KEV*(1/remaining-1/(remaining+e))
            if not -1 <= cos <= 1: valid = False; break
            if i:
                incoming = np.asarray(ordered[i]['position_mm'])-ordered[i-1]['position_mm']
                outgoing = np.asarray(ordered[i+1]['position_mm'])-ordered[i]['position_mm']
                li, lo = np.linalg.norm(incoming), np.linalg.norm(outgoing)
                if min(li, lo) < 1: valid = False; break
                geom = np.dot(incoming, outgoing)/(li*lo)
                sigma = math.sqrt(sum(np.trace(s['position_covariance_mm2']) for s in ordered[i-1:i+2]))
                angular = min(math.pi, 3*sigma*(1/li+1/lo))
                if abs(math.acos(np.clip(geom, -1, 1))-math.acos(cos)) > angular:
                    valid = False; break
        if not valid: continue
        first, second = ordered[:2]
        effective_second = {**second, 'energy_keV': sum(s['energy_keV'] for s in ordered[1:])}
        cone = I.cone(first, effective_second)
        if cone:
            cone.update(second_vertex_mm=second['position_mm'], order=list(order),
                position_covariance_mm2=[first['position_covariance_mm2'], second['position_covariance_mm2']],
                energy_sigma_keV=None,
                assumption='one_fully_absorbed_photon_and_charge_pixels_are_interactions')
            result.append(cone)
    return result


def _reconstruct_observables(observed, bank, *, max_strips=4, max_sites=4, max_hypotheses=64):
    """Return explicit ambiguity; candidates are NEVER unconditional acceptance."""
    out = {'kind': KIND, 'event_id': observed['event_id'], 'pulse_group_id': observed['pulse_group_id'],
        'status': 'unidentifiable', 'reason': None, 'energy_keV': None, 'hypotheses': [], 'candidates': [],
        'calibration_sha256': bank.sha256 if bank is not None else None, 'truth_used': False, 'source_label_used': False,
        'imaging_accepted': False, 'limitations': LIMITATIONS}
    all34 = getattr(bank, 'response_mode', 'selected_pair') == 'all34'
    if all34:
        out.update(response_mode='all34', method=ALL34_METHOD, fit_calls=0,
            limitations=[x for x in LIMITATIONS if not x.startswith('Only the selected X/Y')]+[
                'All34 residuals use collected-terminal weights and total-energy neighbour weights; subthreshold or same-pixel sites can remain hidden below the finite diagnostic envelope.'])
    if observed['status'] != 'completed' or observed['channels'] is None or observed['native'] is None:
        out.update(status='native_failed_or_incomplete', reason='native_response_incomplete')
        return out
    if bank is None:
        out['reason'] = 'independent_waveform_templates_unavailable'
        return out
    all34_waves = _all34_observed_waves(observed) if all34 else None
    out['signed_signal_diagnostics'] = signal_diagnostics(observed)
    collectors = [c for c in observed['channels'] if I.terminal_collection(c, c['wiring_factor'])]
    if any(c['contact_id'] in (17, 34) for c in collectors):
        out['reason'] = 'guard_collection'; return out
    if any(not I.collected(c, c['wiring_factor']) or c['charge_clipped_at_window'] or c['saturated'] for c in collectors):
        out['reason'] = 'collecting_strip_readout_rejected'; return out
    xs = sorted([c for c in collectors if 1 <= c['contact_id'] <= 16], key=lambda c: c['contact_id'])
    ys = sorted([c for c in collectors if 18 <= c['contact_id'] <= 33], key=lambda c: c['contact_id'])
    out['strip_counts'] = [len(xs), len(ys)]
    if not xs or not ys: out['reason'] = 'missing_above_threshold_face'; return out
    out['energy_keV'] = sum(c['reconstructed_energy_keV'] for c in xs+ys)/2
    if max(len(xs), len(ys)) > max_strips:
        out['reason'] = 'strip_budget_exceeded'; return out
    flows, bookkeeping = energy_flows(xs, ys, max_hypotheses, max_sites)
    out['energy_bookkeeping'] = bookkeeping
    if not flows: out['reason'] = bookkeeping['reason']; return out
    envelope = bank.calibrate_discrepancy()
    out['independent_diagnostic_envelope'] = envelope
    for index, flow in enumerate(flows):
        if len(flow) > max_sites:
            fit = {'status': 'unsupported', 'reason': 'site_budget_exceeded'}
        else:
            if all34:
                out['fit_calls'] += 1
            fit = _fit_flow(flow, observed, bank, envelope, all34_waves=all34_waves)
        fit.update(hypothesis_index=index, energy_flow=[list(v) for v in flow])
        out['hypotheses'].append(fit)
        if fit['status'] == 'conditional_fit':
            candidates = sequence_candidates(fit['sites'])
            alternatives = len(flows) + int(bookkeeping['rank_deficient_supports'] > 0)
            order_count = math.factorial(len(fit['sites']))
            for candidate in candidates:
                candidate['hypothesis_index'] = index
                # Unsupported orders and undetermined continuous energy flows
                # retain uninformative mass instead of boosting surviving cones.
                candidate['prior_weight'] = 1/(alternatives*order_count)
                candidate['weight'] = candidate['prior_weight']
                candidate['uncertainty_scope'] = 'Strip-width and saved diagnostic-discrepancy scales. Energy sigma is unknown; 2keV/2% is only an energy compatibility tolerance.'
                out['candidates'].append(candidate)
    if out['candidates']:
        out.update(status='ambiguous', reason='charge_sharing_and_photon_multiplicity_unresolved')
        out['candidate_weight_scope'] = 'Equal site-order priors before kinematic screening within equally weighted energy-flow alternatives; unsupported orders remain unresolved. Not calibrated posterior probabilities.'
    elif len(xs) == len(ys) == 1:
        out['reason'] = 'same_pixel_multiplicity_unidentifiable'
    else:
        out['reason'] = 'no_supported_conditional_sequence'
    out['unsupported_hypothesis_mass'] = max(0., 1-sum(c['prior_weight'] for c in out['candidates']))
    return out


def reconstruct_observables(observed, bank, **kwargs):
    result = _reconstruct_observables(observed, bank, **kwargs)
    result['signal_use'] = U.classify_observables(observed, result)
    return result


def reconstruct_event(event, native, channels, bank, **kwargs):
    return reconstruct_observables(observables(event, native, channels), bank, **kwargs)
