"""Opt-in full-response contracts using tiny sealed synthetic banks; no physics."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
import gegi_signal_reconstruction as G

ROOT = Path(__file__).resolve().parents[1]
PAIRS = [(4, 21), (4, 29), (13, 21), (13, 29)]
TIME = np.arange(151.)
BIPOLAR = np.interp(TIME, [0, 50, 70, 90, 110, 130, 150], [0, 0, 1, 0, -.6, 0, 0])


def signals(x, y, z, energy=500.):
    out = {cid: np.zeros(len(TIME)) for cid in G.ALL34_IDS}
    out[x] = energy*np.clip((TIME-(45+z*6))/20, 0, 1)
    out[y] = -energy*np.clip((TIME-(45-z*6))/20, 0, 1)
    out[2] = energy*(.2 if (x, y) in ((4, 21), (13, 29)) else -.2)*BIPOLAR
    return out


def channels():
    return [{'id': cid, 'wiring_factor': 1 if cid <= 17 else -1,
        'strip_center_mm': None if cid in (17, 34) else (cid-(8.5 if cid <= 17 else 25.5))*G.I.PITCH_MM}
        for cid in G.ALL34_IDS]


def observed():
    total = {cid: np.zeros(len(TIME)) for cid in G.ALL34_IDS}
    for x, y in ((4, 21), (13, 29)):
        for cid, wave in signals(x, y, 0, 100.).items():
            total[cid] += wave
    metadata = []
    for c in channels():
        cid = c['id']; collecting = cid in (4, 13, 21, 29)
        metadata.append({'contact_id': cid, 'wiring_factor': c['wiring_factor'],
            'strip_center_mm': c['strip_center_mm'], 'strip_pitch_mm': G.I.PITCH_MM,
            'accepted': collecting, 'collection_candidate': collecting,
            'reconstructed_energy_keV': 100. if collecting else None,
            'final_induced_keV': float(total[cid][-1]), 'saturated': False, 'charge_clipped_at_window': False})
    return {'event_id': 7, 'pulse_group_id': 2, 'status': 'completed', 'channels': metadata,
        'native': {cid: {'time_ns': TIME.tolist(), 'signed_induced_keV': q.tolist()} for cid, q in total.items()}}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(G._canonical(value))


def fixture(root, *, mutation=None):
    bank = root/'bundle'/'bank'; bank.mkdir(parents=True)
    identity = {'channels': channels(), 'signal_coverage': copy.deepcopy(G.ALL34_COVERAGE),
        'injection_energy_keV': 500., 'depth_mm': list(range(-5, 6)), 'pixel_order': [list(p) for p in PAIRS],
        'diagnostic_pixels': [[4, 21]], 'diagnostic_depth_mm': [0.],
        'diagnostic_offsets_pitch_fraction': [['centre', 0., 0.]]}
    if mutation in ('identity_coverage', 'wiring'):
        if mutation == 'identity_coverage':
            identity.pop('signal_coverage')
        else:
            identity['channels'][19]['wiring_factor'] = 1
    write(bank/'identity.json', identity); identity_sha = G._sha((bank/'identity.json').read_bytes())
    pixels = {}; manifest = []

    def record(ref, x, y, z, diagnostic=False):
        waves = signals(x, y, z)
        if diagnostic:
            waves[2] = waves[2]+5.*BIPOLAR
        payload = {'valid': True, 'status': 'completed', 'position_mm': [0., 0., z],
            'contact_ids': [x, y], 'injection_energy_keV': 500.,
            'signal_coverage': copy.deepcopy(G.ALL34_COVERAGE),
            'channel_signals': [{'contact_id': cid, 'time_ns': TIME.tolist(),
                'signed_induced_keV': waves[cid].tolist()} for cid in G.ALL34_IDS],
            'signals': {face: {'time_ns': TIME.tolist(), 'signed_induced_keV': waves[cid].tolist()}
                        for face, cid in (('X', x), ('Y', y))}}
        if mutation == 'missing_channel':
            payload['channel_signals'].pop()
        elif mutation == 'payload_coverage':
            payload.pop('signal_coverage')
        # Intentionally opaque native SHA: all34 uses the sealed exact file hash,
        # rather than recomputing Julia floating-point JSON with Python.
        saved = {'kind': 'gegi_independent_injection_checkpoint_v1', 'identity_sha256': identity_sha,
            'payload_sha256': 'f'*64, 'payload': payload}
        write(bank/ref, saved)
        manifest.append({'record_ref': ref, 'record_sha256': G._sha((bank/ref).read_bytes())})
        return {'record_ref': ref, 'z_mm': z, 'valid': True}

    for x, y in PAIRS:
        rows = [record(f'injections/{x}-{y}/z{i}.json', x, y, z) for i, z in enumerate(range(-5, 6))]
        pixels[f'{x}:{y}'] = {'status': 'available_model_approximation', 'rows': rows}
    diagnostic = record('diagnostics/centre.json', 4, 21, 0., diagnostic=True)
    table = {'identity_sha256': identity_sha, 'pixels': pixels, 'signal_coverage': copy.deepcopy(G.ALL34_COVERAGE),
        'injection_energy_keV': 500., 'depth_mm': list(range(-5, 6))}
    write(bank/'depth-calibration.json', table)
    write(bank/'depth-diagnostics.json', {'identity_sha256': identity_sha, 'rows': [diagnostic], 'total_fixed_injections': 1})
    artifacts = {ref: G._sha((bank/ref).read_bytes()) for ref in ('identity.json', 'depth-calibration.json', 'depth-diagnostics.json')}
    write(bank/'run.json', {'status': 'completed', 'artifacts': artifacts})
    outer = bank.parent; write(outer/'identity.json', {'calibration_identity_sha256': identity_sha, 'request_sha256': 'request'})
    (outer/'validation.jsonl').write_bytes(b'\n'.join(G._canonical(r) for r in manifest)+b'\n')
    write(outer/'COMPLETE.json', {'bank_run_sha256': G._sha((bank/'run.json').read_bytes()),
        'bundle_identity_sha256': G._sha((outer/'identity.json').read_bytes()),
        'validation_sha256': G._sha((outer/'validation.jsonl').read_bytes()), 'request_sha256': 'request',
        'status': 'completed_original_grid_full34_bank', 'selected_pair_mismatches': 0,
        'validated_records': len(manifest), 'full34_records': len(manifest), 'excluded_records': 0})
    return bank


class All34Tests(unittest.TestCase):
    def make_bank(self, mutation=None):
        temporary = tempfile.TemporaryDirectory(dir=ROOT/'.local')
        self.addCleanup(temporary.cleanup)
        return fixture(Path(temporary.name), mutation=mutation)

    def test_selected_projection_is_identical_but_neighbor_transients_resolve_pairing(self):
        path = self.make_bank(); bank = G.TemplateBank(path, response_mode='all34')
        envelope = bank.calibrate_discrepancy(); observation = observed()
        right = [(4, 21, 100.), (13, 29, 100.)]
        wrong = [(4, 29, 100.), (13, 21, 100.)]
        a = G._fit_flow(right, observation, bank, envelope)
        b = G._fit_flow(wrong, observation, bank, envelope)
        self.assertEqual(a['status'], 'conditional_fit'); self.assertEqual(b['status'], 'model_mismatch')
        self.assertEqual(a['global_energy_scale_keV'], 200.)
        self.assertEqual(len(a['channel_normalized_rms']), 34)
        self.assertIn('2', a['channel_normalized_rms'])
        self.assertEqual(observation['native'][2]['signed_induced_keV'][-1], 0.)
        self.assertLess(min(G._wave(observation['native'][2])[1]), 0.)
        self.assertGreater(max(G._wave(observation['native'][2])[1]), 0.)
        # The selected-only projections of the two hypotheses are indistinguishable.
        selected = type('SelectedProjection', (), {'templates': lambda _, x, y, grid:
            bank.templates(x, y, grid)[:, [x-1, y-1], :]})()
        old_envelope = {'normalized_rms': 1e-6, 'max_channel_normalized_rms': 1e-6, 'depth_error_mm': .25}
        for flow in (right, wrong):
            fit = G._fit_flow(flow, observation, selected, old_envelope)
            self.assertEqual(fit['status'], 'conditional_fit')
            self.assertEqual(fit['sites'][0]['method'], 'joint_signed_selected_pair_waveform_template_fit')
        self.assertEqual(a['method'], G.ALL34_METHOD)

    def test_diagnostic_max_channel_uses_injection_energy_not_terminal_or34_average(self):
        bank = G.TemplateBank(self.make_bank(), response_mode='all34')
        envelope = bank.calibrate_discrepancy()
        expected = float(np.sqrt(np.mean((.01*np.interp(G.FIT_GRID_NS, TIME, BIPOLAR))**2)))
        self.assertAlmostEqual(envelope['max_channel_normalized_rms'], expected)
        self.assertAlmostEqual(envelope['normalized_rms']*np.sqrt(34), expected)
        self.assertEqual(envelope['response_mode'], 'all34')

    def test_weak_collector_mismatch_hidden_by_total_energy_is_rejected(self):
        envelope = G.TemplateBank(self.make_bank(), response_mode='all34').calibrate_discrepancy()

        class ImbalancedBank:
            response_mode = 'all34'
            def templates(self, x, y, grid):
                response = np.zeros((34, len(grid)))
                response[[x-1, y-1]] = np.clip((grid-45)/20, 0, 1)
                if (x, y) == (4, 24):
                    response[x-1] += .1*np.interp(grid, TIME, BIPOLAR)
                return np.repeat(response[None], 11, axis=0)

        bank = ImbalancedBank()
        right = [(4, 21, 6.), (7, 24, 6.), (13, 29, 488.)]
        wrong = [(4, 24, 6.), (7, 21, 6.), (13, 29, 488.)]
        grid = G.FIT_GRID_NS
        target = sum(e*bank.templates(x, y, grid)[0] for x, y, e in right)
        wrong_model = sum(e*bank.templates(x, y, grid)[0] for x, y, e in wrong)
        # The v1 total-only normalization admits this unchanged wrong model.
        total_only_rms = np.sqrt(np.mean(((target-wrong_model)/500.)**2, axis=1)).max()
        self.assertLess(total_only_rms, envelope['max_channel_normalized_rms'])
        observation = observed()
        observation['native'] = {cid: {'time_ns': grid.tolist(),
            'signed_induced_keV': (target[cid-1]*(1 if cid <= 17 else -1)).tolist()} for cid in G.ALL34_IDS}
        totals = {cid: sum(e for x, y, e in right if cid in (x, y)) for cid in G.ALL34_IDS}
        for channel in observation['channels']:
            cid = channel['contact_id']; collecting = totals[cid] > 0
            channel.update(accepted=collecting, collection_candidate=collecting,
                reconstructed_energy_keV=totals[cid] if collecting else None,
                final_induced_keV=target[cid-1, -1]*(1 if cid <= 17 else -1))
        self.assertEqual(G._fit_flow(right, observation, bank, envelope)['status'], 'conditional_fit')
        result = G._fit_flow(wrong, observation, bank, envelope)
        self.assertEqual(result['status'], 'model_mismatch')
        self.assertGreater(result['channel_normalized_rms']['4'], envelope['max_channel_normalized_rms'])
        self.assertEqual(result['channel_residual_scales_keV']['4'], 6.)
        self.assertEqual(result['channel_residual_scales_keV']['13'], 488.)
        self.assertEqual(result['channel_residual_scales_keV']['2'], 500.)

    def test_least_squares_resolves_depth_hidden_by_flat_max_channel_objective(self):
        envelope = G.TemplateBank(self.make_bank(), response_mode='all34').calibrate_discrepancy()

        class PlateauBank:
            response_mode = 'all34'
            def templates(self, x, y, grid):
                unit = np.clip((grid-45)/20, 0, 1)
                bipolar = np.interp(grid, TIME, BIPOLAR)
                responses = np.zeros((11, 34, len(grid)))
                responses[:, [x-1, y-1]] = unit
                for i, z in enumerate(range(-5, 6)):
                    responses[i, x-1] += .0005*(z-1.25)*bipolar
                return responses

        bank = PlateauBank();grid = G.FIT_GRID_NS
        target = np.zeros((34, len(grid)))
        target[[3, 20]] = np.clip((grid-45)/20, 0, 1)
        target[1] = .008*np.interp(grid, TIME, BIPOLAR)
        options = bank.templates(4, 21, grid)
        fine = np.concatenate([options[i:i+1]*(1-f)+options[i+1:i+2]*f
            for i in range(10) for f in (0., .25, .5, .75)]+[options[-1:]])
        delta = fine-target
        minimax = np.max(np.mean(delta**2, axis=2), axis=1)
        np.testing.assert_array_equal(minimax, np.full(41, minimax[0]))
        self.assertEqual(int(np.argmin(minimax)), 0)  # v2 first-index depth=-5.
        self.assertEqual(int(np.argmin(G._response_cost(delta))), 25)  # depth=1.25.
        observation = observed()
        observation['native'] = {cid: {'time_ns': grid.tolist(),
            'signed_induced_keV': (500*target[cid-1]*(1 if cid <= 17 else -1)).tolist()} for cid in G.ALL34_IDS}
        for channel in observation['channels']:
            cid = channel['contact_id'];collecting = cid in (4, 21)
            channel.update(accepted=collecting, collection_candidate=collecting,
                reconstructed_energy_keV=500. if collecting else None,
                final_induced_keV=500*target[cid-1, -1]*(1 if cid <= 17 else -1))
        result = G._fit_flow([(4, 21, 500.)], observation, bank, envelope)
        self.assertEqual(result['status'], 'conditional_fit')
        self.assertEqual(result['sites'][0]['position_mm'][2], 1.25)
        self.assertEqual(result['start_solutions_depth_mm'], [[1.25]]*3)

    def test_full_reconstruction_counts_actual_fits_and_keeps_native_failure_null(self):
        bank = G.TemplateBank(self.make_bank(), response_mode='all34')
        result = G.reconstruct_observables(observed(), bank)
        self.assertEqual(result['response_mode'], 'all34')
        self.assertEqual(result['method'], G.ALL34_METHOD)
        self.assertEqual(result['fit_calls'], len(result['hypotheses']))
        self.assertGreater(result['fit_calls'], 0)
        failed = G.reconstruct_observables({'event_id': 9, 'pulse_group_id': 0,
            'status': 'native_failed', 'channels': None, 'native': None}, bank)
        self.assertEqual(failed['fit_calls'], 0)
        self.assertEqual(failed['response_mode'], 'all34')
        self.assertIsNone(failed['energy_keV'])
        self.assertEqual(failed['hypotheses'], [])

    def test_missing_channel_coverage_and_wrong_wiring_are_rejected_without_fallback(self):
        for mutation in ('identity_coverage', 'wiring', 'payload_coverage', 'missing_channel'):
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                G.TemplateBank(self.make_bank(mutation), response_mode='all34').templates(4, 21, G.FIT_GRID_NS)

    def test_observation_missing_channel_wrong_wiring_and_nan_are_rejected(self):
        bank = G.TemplateBank(self.make_bank(), response_mode='all34'); envelope = bank.calibrate_discrepancy()
        for change in ('missing', 'wiring', 'nan'):
            observation = observed()
            if change == 'missing': observation['native'].pop(2)
            elif change == 'wiring': observation['channels'][19]['wiring_factor'] = 1
            else: observation['native'][2]['signed_induced_keV'][3] = float('nan')
            with self.subTest(change=change), self.assertRaises(ValueError):
                G._fit_flow([(4, 21, 100.), (13, 29, 100.)], observation, bank, envelope)

    def test_partial_or_changed_exact_file_seal_is_rejected(self):
        path = self.make_bank(); (path.parent/'COMPLETE.json').unlink()
        with self.assertRaisesRegex(ValueError, 'sealed COMPLETE'):
            G.TemplateBank(path, response_mode='all34')
        path = self.make_bank(); bank = G.TemplateBank(path, response_mode='all34')
        with (path/'injections/4-21/z0.json').open('ab') as stream: stream.write(b' ')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            bank.templates(4, 21, G.FIT_GRID_NS)
        for change in ('status', 'selected_pair_mismatches', 'validated_records'):
            path = self.make_bank(); seal = path.parent/'COMPLETE.json'
            value = json.loads(seal.read_bytes())
            value[change] = 'incomplete' if change == 'status' else value[change]+1
            write(seal, value)
            with self.subTest(change=change), self.assertRaises(ValueError):
                G.TemplateBank(path, response_mode='all34')


if __name__ == '__main__':
    unittest.main()
